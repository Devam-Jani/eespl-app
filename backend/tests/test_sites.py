"""Sites: builder preset, BOQ to areas, tasks, progress, drawings, Powerplay projects, access."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Role, RolePermission
from app.sites import builder
from app.sites.models import Site
from app.sites.powerplay_projects import import_projects
from tests.conftest import login
from tests.test_tenders import boq, imported_tender, line

TOWER = builder.TowerPreset(
    name="T1",
    basements=2,
    ground=True,
    upper_floors=14,
    flats_per_floor=4,
    flats_from="G",
    rooms_per_flat={"toilet": 2, "kitchen": 1, "balcony": 1},
    terrace=True,
    oh_tanks=1,
    lift_pits=2,
    ug_tanks=1,
)


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def new_site(client, headers, **extra):
    r = client.post(
        "/api/sites",
        json={"name": "Invented Towers", "start_date": "2026-11-02", **extra},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def node(client, headers, site_id, kind, name, parent_id=None, area=None):
    r = client.post(
        f"/api/sites/{site_id}/nodes",
        json={"kind": kind, "name": name, "parent_id": parent_id, "area_sqm": area},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return next(n for n in r.json() if n["name"] == name and n["parent_id"] == parent_id)["id"]


# --- builder ------------------------------------------------------------------------------------


def test_tower_preset_counts(boss):
    expected = {
        "total": 323,
        "tower": 1,
        "basement": 2,
        "floor": 15,
        "flat": 60,
        "toilet": 120,
        "kitchen": 60,
        "balcony": 60,
        "terrace": 1,
        "oh_tank": 1,
        "lift_pit": 2,
        "ug_tank": 1,
    }
    assert builder.preview(TOWER) == expected
    client, headers = boss
    site = new_site(client, headers)
    body = TOWER.model_dump()
    r = client.post(f"/api/sites/{site['id']}/builder/tower/preview", json=body, headers=headers)
    assert r.json() == expected
    r = client.post(f"/api/sites/{site['id']}/builder/tower", json=body, headers=headers)
    assert r.status_code == 201 and len(r.json()) == 323
    nodes = {n["path"]: n for n in r.json()}
    assert nodes["T1 › B2"]["level_no"] == -2 and nodes["T1 › Floor 14"]["level_no"] == 14
    assert "T1 › G › G01 › Toilet 2" in nodes and "T1 › Floor 3 › 304 › Balcony" in nodes
    assert nodes["T1 › Terrace › OHT 1"]["kind"] == "oh_tank"
    tower = nodes["T1"]["id"]
    toilets = client.get(
        f"/api/sites/{site['id']}/nodes/select?kind=toilet&under={tower}", headers=headers
    ).json()
    assert len(toilets) == 120


# --- tender -> site -> scope -> tasks --------------------------------------------------------


@pytest.fixture
def won_site(boss):
    """A won tender with three priced lines, its site, and a small structure."""
    client, headers = boss
    tid = imported_tender(client, headers)["id"]
    data = boq(client, headers, tid)
    edits = [
        {"id": line(data, t)["id"], "rate": r}
        for t, r in (
            ("Crystalline coating", "470"),
            ("Pipe sleeve", "355"),
            ("APP membrane", "520"),
        )
    ]
    assert (
        client.patch(
            f"/api/tenders/{tid}/lines", json={"lines": edits}, headers=headers
        ).status_code
        == 200
    )
    r = client.post("/api/sites/from-tender", json={"tender_id": tid}, headers=headers)
    assert r.status_code == 409  # not won yet
    client.patch(f"/api/tenders/{tid}", json={"status": "won"}, headers=headers)
    r = client.post(
        "/api/sites/from-tender",
        json={"tender_id": tid, "start_date": "2026-11-02"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    site = r.json()
    assert site["tender_id"] == tid and site["client_name"] == "Example Developers"
    assert (
        client.post("/api/sites/from-tender", json={"tender_id": tid}, headers=headers).status_code
        == 409
    )  # one site per tender
    assert client.get(f"/api/tenders/{tid}", headers=headers).json()["site_id"] == site["id"]
    sid = site["id"]
    t1 = node(client, headers, sid, "tower", "T1")
    flat = node(client, headers, sid, "flat", "101", t1)
    toilets = [
        node(client, headers, sid, "toilet", "Toilet 1", flat, 10),
        node(client, headers, sid, "toilet", "Toilet 2", flat, 30),
    ]
    kitchen = node(client, headers, sid, "kitchen", "Kitchen", flat)
    scope = client.get(f"/api/sites/{sid}/scope", headers=headers).json()
    lines = {ln["description"].split(" — ")[-1][:20]: ln for ln in scope["lines"]}
    return client, headers, sid, lines, toilets, kitchen, t1


def test_boq_to_areas_split_and_qty_check(won_site):
    client, headers, sid, lines, toilets, kitchen, _ = won_site
    assert len(lines) == 3  # the priced lines only
    crystal = lines["Crystalline coating "]
    assert crystal["state"] == "under" and crystal["boq_qty"] == "120.500"
    templates = {
        t["name"]: t["id"] for t in client.get("/api/stage-templates", headers=headers).json()
    }
    # suggested from the description's words
    assert (
        lines["APP membrane 4 mm th"]["suggested_template_id"]
        == templates["Terrace (APP membrane)"]
    )
    # by area: 10 and 30 sqm
    r = client.post(
        f"/api/sites/{sid}/scope/assign",
        json={
            "boq_line_id": crystal["boq_line_id"],
            "node_ids": toilets,
            "stage_template_id": templates["Toilet / wet area (coating)"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    got = next(ln for ln in r.json()["lines"] if ln["boq_line_id"] == crystal["boq_line_id"])
    assert [s["qty"] for s in got["scopes"]] == ["30.125", "90.375"]
    assert got["state"] == "ok"
    # equally when a node has no area (3 nodes, the rounding remainder on the last)
    pipe = lines["Pipe sleeve sealing "]
    r = client.post(
        f"/api/sites/{sid}/scope/assign",
        json={
            "boq_line_id": pipe["boq_line_id"],
            "node_ids": [*toilets, kitchen],
            "qty": "10",
            "stage_template_id": templates["Toilet / wet area (coating)"],
        },
        headers=headers,
    )
    got = next(ln for ln in r.json()["lines"] if ln["boq_line_id"] == pipe["boq_line_id"])
    assert [s["qty"] for s in got["scopes"]] == ["3.333", "3.333", "3.334"]
    assert got["state"] == "under" and got["difference"] == "-2.000"  # 10 of 12 nos
    # over-assignment
    first = got["scopes"][0]["id"]
    r = client.patch(f"/api/sites/{sid}/scopes/{first}", json={"qty": "6"}, headers=headers)
    got = next(ln for ln in r.json()["lines"] if ln["boq_line_id"] == pipe["boq_line_id"])
    assert got["state"] == "over" and got["assigned"] == "12.667"


def _assign(client, headers, sid, line_id, node_ids, template_id, qty=None):
    r = client.post(
        f"/api/sites/{sid}/scope/assign",
        json={
            "boq_line_id": line_id,
            "node_ids": node_ids,
            "stage_template_id": template_id,
            **({"qty": qty} if qty else {}),
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_task_generation_is_chained_and_idempotent(won_site):
    client, headers, sid, lines, toilets, _, _ = won_site
    templates = client.get("/api/stage-templates", headers=headers).json()
    toilet = next(t for t in templates if t["name"] == "Toilet / wet area (coating)")
    _assign(
        client, headers, sid, lines["Crystalline coating "]["boq_line_id"], toilets, toilet["id"]
    )
    r = client.post(f"/api/sites/{sid}/tasks/generate", headers=headers)
    assert r.status_code == 200, r.text
    steps = len(toilet["steps"])
    assert r.json()["added"] == 2 * steps and r.json()["tasks"] == 2 * steps
    assert r.json()["planned_end"] == str(
        date(2026, 11, 2) + timedelta(days=toilet["total_days"] - 1)
    )
    tasks = client.get(f"/api/sites/{sid}/tasks", headers=headers).json()
    first_scope = [t for t in tasks if t["area_scope_id"] == tasks[0]["area_scope_id"]]
    assert [t["name"] for t in first_scope] == [s["name"] for s in toilet["steps"]]
    assert first_scope[0]["depends_on"] == []
    for prev, nxt in zip(first_scope, first_scope[1:], strict=False):
        assert nxt["depends_on"] == [prev["id"]]
        assert date.fromisoformat(nxt["planned_start"]) == date.fromisoformat(
            prev["planned_end"]
        ) + timedelta(days=1)
    # start one, generate again: nothing added, nothing lost
    client.patch(
        f"/api/sites/{sid}/tasks/{first_scope[0]['id']}",
        json={"status": "in_progress"},
        headers=headers,
    )
    r = client.post(f"/api/sites/{sid}/tasks/generate", headers=headers).json()
    assert (r["added"], r["kept"], r["tasks"]) == (0, 2 * steps, 2 * steps)
    after = client.get(f"/api/sites/{sid}/tasks", headers=headers).json()
    assert next(t for t in after if t["id"] == first_scope[0]["id"])["status"] == "in_progress"
    # a scope with started tasks cannot be replaced
    r = client.post(
        f"/api/sites/{sid}/scope/assign",
        json={
            "boq_line_id": lines["Crystalline coating "]["boq_line_id"],
            "node_ids": toilets,
            "stage_template_id": toilet["id"],
            "replace": True,
        },
        headers=headers,
    )
    assert r.status_code == 409


def test_progress_weights_hold_points_and_qty_weighting(won_site):
    client, headers, sid, lines, toilets, _, t1 = won_site
    r = client.post(
        "/api/stage-templates",
        json={
            "name": "Test coating",
            "steps": [
                {"name": "Prep", "weight_percent": "40", "needs_photo": False},
                {
                    "name": "Ponding",
                    "weight_percent": "30",
                    "needs_photo": False,
                    "hold_point": True,
                },
                {"name": "Screed", "weight_percent": "30", "needs_photo": False, "typical_days": 2},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    bad = client.post(
        "/api/stage-templates",
        json={"name": "Bad", "steps": [{"name": "Only", "weight_percent": "90"}]},
        headers=headers,
    )
    assert bad.status_code == 422  # weights must add up to 100
    # 10 + 30 sqm over the two toilets
    _assign(
        client,
        headers,
        sid,
        lines["Crystalline coating "]["boq_line_id"],
        toilets,
        r.json()["id"],
        qty="40",
    )
    client.post(f"/api/sites/{sid}/tasks/generate", headers=headers)
    tasks = client.get(f"/api/sites/{sid}/tasks", headers=headers).json()
    small = [t for t in tasks if t["node_id"] == toilets[0]]  # the 10 sqm toilet
    prep, ponding, screed = small

    def patch(task, **body):
        return client.patch(f"/api/sites/{sid}/tasks/{task['id']}", json=body, headers=headers)

    def site_pct():
        return Decimal(client.get(f"/api/sites/{sid}", headers=headers).json()["progress_percent"])

    assert patch(ponding, status="in_progress").status_code == 409  # prep is not done
    assert patch(prep, status="done").status_code == 200
    assert site_pct() == Decimal("10.00")  # 10 sqm at 40% of 40 sqm
    assert patch(ponding, status="done").status_code == 200
    assert site_pct() == Decimal("10.00")  # a hold point counts only once certified
    r = patch(screed, status="in_progress")
    assert r.status_code == 409 and "hold point" in r.json()["detail"]
    r = client.post(
        f"/api/sites/{sid}/tasks/{ponding['id']}/certify", json={"remark": "Dry"}, headers=headers
    )
    assert r.status_code == 200 and r.json()["status"] == "certified"
    assert site_pct() == Decimal("17.50")  # 10 × 70% / 40
    assert patch(screed, status="done").status_code == 200
    assert site_pct() == Decimal("25.00")
    nodes = {n["id"]: n for n in client.get(f"/api/sites/{sid}/nodes", headers=headers).json()}
    assert nodes[toilets[0]]["progress_percent"] == "100.00"
    assert nodes[t1]["progress_percent"] == "25.00"  # the tower: qty-weighted over its scopes
    pending = client.get(f"/api/sites/{sid}/tasks?filter=pending_certification", headers=headers)
    assert pending.json() == []


def test_done_needs_photo_and_passed_inspection(won_site):
    client, headers, sid, lines, toilets, _, _ = won_site
    templates = client.get("/api/stage-templates", headers=headers).json()
    toilet = next(t for t in templates if t["name"] == "Toilet / wet area (coating)")
    _assign(
        client,
        headers,
        sid,
        lines["Crystalline coating "]["boq_line_id"],
        toilets[:1],
        toilet["id"],
    )
    client.post(f"/api/sites/{sid}/tasks/generate", headers=headers)
    first = client.get(f"/api/sites/{sid}/tasks", headers=headers).json()[0]
    url = f"/api/sites/{sid}/tasks/{first['id']}"
    r = client.patch(url, json={"status": "done"}, headers=headers)
    assert r.status_code == 422 and "photo" in r.json()["detail"]
    r = client.post(
        f"{url}/photos", files={"file": ("prep.jpg", b"\xff\xd8\xff fake")}, headers=headers
    )
    assert r.status_code == 201 and len(r.json()["photos"]) == 1
    assert client.patch(url, json={"status": "done"}, headers=headers).status_code == 200


# --- drawings -----------------------------------------------------------------------------------


def test_drawing_revisions_and_approval(boss, make_user, db):
    client, headers = boss
    site = new_site(client, headers)
    sid = site["id"]
    r = client.post(
        f"/api/sites/{sid}/drawings",
        data={"title": "Terrace layout"},
        files={"file": ("terrace.pdf", b"%PDF-1.4 fake")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    drawing = r.json()[0]
    assert drawing["latest"]["rev"] == "R0" and drawing["latest_approved"] is None
    for name in ("terrace-r1.pdf", "terrace-r2.pdf"):
        r = client.post(
            f"/api/sites/{sid}/drawings/{drawing['id']}/revisions",
            files={"file": (name, b"%PDF-1.4 fake")},
            headers=headers,
        )
    drawing = r.json()[0]
    assert [x["rev"] for x in drawing["revisions"]] == ["R2", "R1", "R0"]
    r1 = next(x for x in drawing["revisions"] if x["rev"] == "R1")
    bad = client.post(
        f"/api/sites/{sid}/drawings",
        data={"title": "x"},
        files={"file": ("x.exe", b"MZ")},
        headers=headers,
    )
    assert bad.status_code == 422

    # a supervisor on the site may upload but not approve
    make_user("sup@example.com", "site_supervisor")
    sup = db.scalar(select(Role.id).where(Role.code == "site_supervisor"))
    assert sup
    client.put(
        f"/api/sites/{sid}/members",
        json={
            "members": [{"user_id": str(_uid(db, "sup@example.com")), "role_on_site": "supervisor"}]
        },
        headers=headers,
    )
    sup_headers = login(client, "sup@example.com")
    base = f"/api/sites/{sid}/drawings/{drawing['id']}/revisions/{r1['id']}"
    assert client.post(f"{base}/approve", json={}, headers=sup_headers).status_code == 403
    assert client.post(f"{base}/reject", json={}, headers=headers).status_code == 422  # remark
    r = client.post(f"{base}/approve", json={"remark": "OK for site"}, headers=headers)
    assert r.status_code == 200
    drawing = r.json()[0]
    assert drawing["latest_approved"]["rev"] == "R1" and drawing["latest"]["rev"] == "R2"
    r = client.get(f"{base}/file", headers=sup_headers)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def _uid(db, email):
    from app.models import User

    db.expire_all()
    return db.scalar(select(User.id).where(User.email == email))


# --- Powerplay projects -------------------------------------------------------------------------


def test_powerplay_projects_import(tmp_path):
    wb = Workbook()
    wb.active.title = "Material List"
    ws = wb.create_sheet("project Raw")
    ws.append(["_id", "name"])
    names = [
        "Demo Site",
        "Project ABC",
        "Zaveri House",
        "ZAVERI  HOUSE",
        "Raag Bungalow",
        "raag bungalow",
        "Anmaya Infrabuild",
        "Anamaya Infrabuild",
        "test",
        "A",
        "Copy Orchid Gold",
        "return material",
        "Devambhai site",
        "Khusboo",
        "Orchid Gold",
        "Riviera Springs",
        "xyz",
    ]
    for i, name in enumerate(names):
        ws.append([f"PRJ{i:03d}", name])
    path = tmp_path / "po_extract.xlsx"
    wb.save(path)
    with SessionLocal() as db:
        result = import_projects(db, path)
        db.commit()
        assert {n for n, _ in result.skipped} == {
            "Demo Site",
            "Project ABC",
            "test",
            "A",
            "Copy Orchid Gold",
            "return material",
            "Devambhai site",
            "Khusboo",
            "xyz",
        }
        assert sorted(result.merged) == [("Raag Bungalow", 2), ("Zaveri House", 2)]
        assert result.near_duplicates == [("Anmaya Infrabuild", "Anamaya Infrabuild")]
        assert sorted(result.imported) == [
            "Anamaya Infrabuild",
            "Anmaya Infrabuild",
            "Orchid Gold",
            "Raag Bungalow",
            "Riviera Springs",
            "Zaveri House",
        ]
        sites = {s.name: s for s in db.scalars(select(Site))}
        assert all(
            s.status == "closed" and s.source == "powerplay" and s.client_id is None
            for s in sites.values()
        )
        assert sites["Zaveri House"].source_ref == "PRJ002"
        assert "PRJ003" in sites["Zaveri House"].notes
        assert "Anamaya" in sites["Anmaya Infrabuild"].notes
        again = import_projects(db, path)
        db.commit()
        assert (again.imported, again.already) == ([], 6)


# --- access -------------------------------------------------------------------------------------


def test_supervisor_sees_assigned_sites_and_updates_only(won_site, make_user, db, login_as):
    client, headers, sid, lines, toilets, _, _ = won_site
    templates = client.get("/api/stage-templates", headers=headers).json()
    toilet = next(t for t in templates if t["name"] == "Toilet / wet area (coating)")
    _assign(
        client,
        headers,
        sid,
        lines["Crystalline coating "]["boq_line_id"],
        toilets[:1],
        toilet["id"],
    )
    client.post(f"/api/sites/{sid}/tasks/generate", headers=headers)
    other = new_site(client, headers, name="Other site")
    make_user("sup@example.com", "site_supervisor")
    client.put(
        f"/api/sites/{sid}/members",
        json={
            "members": [{"user_id": str(_uid(db, "sup@example.com")), "role_on_site": "supervisor"}]
        },
        headers=headers,
    )
    sup = login(client, "sup@example.com")
    listed = client.get("/api/sites", headers=sup).json()
    assert [s["id"] for s in listed["items"]] == [sid]
    assert client.get(f"/api/sites/{other['id']}", headers=sup).status_code == 404
    task = client.get(f"/api/sites/{sid}/tasks", headers=sup).json()[0]
    r = client.patch(
        f"/api/sites/{sid}/tasks/{task['id']}",
        json={"status": "in_progress", "remark": "Started"},
        headers=sup,
    )
    assert r.status_code == 200
    r = client.post(f"/api/sites/{sid}/nodes", json={"kind": "toilet", "name": "X"}, headers=sup)
    assert r.status_code == 403  # structure needs site.edit
    assert client.post(f"/api/sites/{sid}/tasks/generate", headers=sup).status_code == 403
    client_role, client_headers = login_as("client", email="customer@example.com")
    assert client_role.get("/api/sites", headers=client_headers).status_code == 403
    assert client_role.get(f"/api/sites/{sid}", headers=client_headers).status_code == 403


def test_sales_role_scope_is_assigned(db):
    sales = db.scalar(select(Role.id).where(Role.code == "sales"))
    grants = dict(
        db.execute(
            select(RolePermission.permission_code, RolePermission.scope).where(
                RolePermission.role_id == sales
            )
        ).all()
    )
    assert grants["site.view"] == "assigned"
