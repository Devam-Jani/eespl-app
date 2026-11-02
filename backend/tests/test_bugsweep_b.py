"""Part 0 bug sweep, group B (sites): the scope of a site without a tender, hold-point
inspections that cannot certify, photos on a returned DPR, the site pin's radius, RFI zones,
the status board (who moves a card, the allocation list for its recipients), the new area's
"top level" and the board's help. Invented data only."""

import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.execution import service as svc
from app.main import app
from app.models import Role, User
from app.ops.help import DEFAULTS as HELP
from app.sites.models import Site, SiteMember, SiteNode, Task
from tests.conftest import _PASSWORD_HASH, login
from tests.test_execution import hold_point_task, inspect, photo_files, ponding_answers

TODAY = svc.today()


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss-b@example.com")


def jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (90, 120, 150)).save(buf, "JPEG")
    return buf.getvalue()


def new_site(c, h, name="Invented Plaza"):
    r = c.post(
        "/api/sites",
        json={"name": name, "start_date": str(TODAY - timedelta(days=30))},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def node(c, h, sid, kind, name, parent_id=None):
    r = c.post(
        f"/api/sites/{sid}/nodes",
        json={"kind": kind, "name": name, "parent_id": parent_id},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return next(n for n in r.json() if n["name"] == name and n["parent_id"] == parent_id)["id"]


def member(db, sid, email, *roles, role_on_site="supervisor"):
    """A user with roles (a member of the site when sid is given): (client, headers, user)."""
    u = User(
        email=email,
        full_name=email.split("@")[0],
        password_hash=_PASSWORD_HASH,
        is_active=True,
        roles=list(db.scalars(select(Role).where(Role.code.in_(roles)))),
    )
    db.add(u)
    db.flush()
    if sid:
        db.add(SiteMember(site_id=sid, user_id=u.id, role_on_site=role_on_site))
    db.commit()
    c = TestClient(app)
    return c, login(c, email), u


# --- Scope: a site without a tender ---------------------------------------------------------------


def test_a_scope_is_added_to_a_place_on_a_site_without_a_tender(boss):
    c, h = boss
    sid = new_site(c, h)
    t1 = node(c, h, sid, "tower", "T1")
    terrace = node(c, h, sid, "terrace", "Terrace", t1)
    template = c.get("/api/stage-templates", headers=h).json()[0]["id"]
    # the body the Scope tab's "Add a scope" sends (addScopeBody)
    r = c.post(
        f"/api/sites/{sid}/scope/assign",
        json={
            "boq_line_id": None,
            "node_ids": [terrace],
            "stage_template_id": template,
            "qty": "25",
            "unit": "sqm",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["lines"] == []
    (scope,) = r.json()["other_scopes"]
    assert scope["node_id"] == terrace and scope["qty"] == "25.000" and scope["unit"] == "sqm"
    gen = c.post(f"/api/sites/{sid}/tasks/generate", headers=h)
    assert gen.status_code == 200 and gen.json()["added"] > 0  # tasks for a site without a tender


# --- Inspections: a hold point that cannot be certified yet ---------------------------------------


def test_an_inspection_on_a_hold_point_is_saved_when_it_cannot_certify(boss, db):
    c, h = boss
    sid = new_site(c, h)
    # the step is not done yet: saved, not certified
    task_id, cl = hold_point_task(db, sid, status="in_progress")
    r = inspect(c, h, sid, cl, task_id, ponding_answers(cl), photo_files(cl), certify=True)
    assert r.status_code == 201, r.text
    db.expire_all()
    assert db.get(Task, task_id).status == "in_progress"
    # a supervisor (site.update, no site.edit) on a done step: saved, not certified
    sid2 = new_site(c, h, "Invented Plaza Two")
    sup, sh, _ = member(db, sid2, "sup-b@example.com", "site_supervisor")
    task2, cl = hold_point_task(db, sid2, status="done")
    r = inspect(sup, sh, sid2, cl, task2, ponding_answers(cl), photo_files(cl), certify=True)
    assert r.status_code == 201, r.text
    db.expire_all()
    assert db.get(Task, task2).status == "done"
    # the office still certifies on save
    r = inspect(c, h, sid2, cl, task2, ponding_answers(cl), photo_files(cl), certify=True)
    assert r.status_code == 201 and r.json()["task_status"] == "certified"


# --- DPR: photos on a returned report -------------------------------------------------------------


def test_photos_are_added_to_a_returned_dpr(boss):
    c, h = boss
    sid = new_site(c, h)
    day = TODAY - timedelta(days=1)
    url = f"/api/execution/sites/{sid}/dprs/{day}"
    r = c.put(url, json={"work_done": "Invented primer coat", "submit": True}, headers=h)
    assert r.status_code == 200, r.text
    dpr_id = r.json()["id"]
    photo = {"file": ("site.jpg", jpg(), "image/jpeg")}
    assert c.post(f"{url}/photos", files=photo, headers=h).status_code == 409  # submitted
    r = c.post(f"/api/execution/dprs/{dpr_id}/return", json={"comment": "Add photos"}, headers=h)
    assert r.status_code == 200, r.text
    r = c.post(f"{url}/photos", files={"file": ("site.jpg", jpg(), "image/jpeg")}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "returned" and len(r.json()["photos"]) == 1


# --- Location: the pin keeps the site's radius ----------------------------------------------------


def test_saving_the_pin_without_a_radius_keeps_the_sites_radius(boss, db):
    c, h = boss
    sid = new_site(c, h)
    url = f"/api/field/sites/{sid}/location"
    assert (
        c.put(url, json={"lat": 23.0, "lng": 72.5, "radius_m": 300}, headers=h).status_code == 200
    )
    r = c.put(url, json={"lat": 23.01, "lng": 72.51}, headers=h)  # the field left empty
    assert r.status_code == 200 and r.json()["radius_m"] == 300
    db.expire_all()
    assert db.get(Site, sid).radius_m == 300
    # an explicit null still goes back to the company default
    c.put(url, json={"lat": 23.01, "lng": 72.51, "radius_m": None}, headers=h)
    db.expire_all()
    assert db.get(Site, sid).radius_m is None


# --- RFI zones: add, record the client's signature, remove ----------------------------------------


def test_rfi_zones_are_marked_signed_and_removed(boss):
    c, h = boss
    sid = new_site(c, h)
    t1 = node(c, h, sid, "tower", "T1")
    f101 = node(c, h, sid, "flat", "101", t1)
    f102 = node(c, h, sid, "flat", "102", t1)
    url = f"/api/closeout/sites/{sid}/zones"
    # the bodies the zones page sends (zoneBody)
    ours = c.post(
        url,
        json={"name": "Flat 101", "node_id": f101, "ours": True, "other_applicator": None},
        headers=h,
    )
    assert ours.status_code == 201, ours.text
    bad = c.post(
        url,
        json={"name": "Flat 102", "node_id": f102, "ours": False, "other_applicator": None},
        headers=h,
    )
    assert bad.status_code == 422
    theirs = c.post(
        url,
        json={
            "name": "Flat 102",
            "node_id": f102,
            "ours": False,
            "other_applicator": "Invented Applicator",
        },
        headers=h,
    )
    assert theirs.status_code == 201
    zid = ours.json()["id"]
    r = c.post(
        f"/api/closeout/zones/{zid}/record-signature",
        data={"signed_name": "Invented Client PM"},
        files={"file": ("rfi.pdf", b"%PDF-1.4 invented", "application/pdf")},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["recorded_by_staff"]
        and r.json()["signed_name"] == "Invented Client PM"
    )
    assert c.delete(f"/api/closeout/zones/{zid}", headers=h).status_code == 409  # signed: locked
    assert c.delete(f"/api/closeout/zones/{theirs.json()['id']}", headers=h).status_code == 204
    zones = c.get(url, headers=h).json()["zones"]
    assert [z["name"] for z in zones] == ["Flat 101"]


# --- Status board ---------------------------------------------------------------------------------


def test_the_board_says_who_may_move_a_card(boss, db):
    c, h = boss
    mine = new_site(c, h, "Invented Mine")
    other = new_site(c, h, "Invented Other")
    for s in (mine, other):
        c.post(f"/api/team/board/{s}", json={"column": "upcoming"}, headers=h)
    eng, eh, _ = member(db, mine, "eng-b@example.com", "site_engineer", role_on_site="incharge")
    rows = {s["id"]: s for s in eng.get("/api/team/board", headers=eh).json()["sites"]}
    assert rows[mine]["can_move"] is True
    assert other not in rows or rows[other]["can_move"] is False
    acc, ah, _ = member(db, None, "acc-b@example.com", "accounts")
    rows = acc.get("/api/team/board", headers=ah).json()["sites"]
    assert rows and not any(s["can_move"] for s in rows)  # site.view only
    plan, ph, _ = member(db, None, "plan-b@example.com", "planning")
    assert all(s["can_move"] for s in plan.get("/api/team/board", headers=ph).json()["sites"])


def test_the_allocation_list_downloads_for_its_recipients(boss, db):
    c, h = boss
    new_site(c, h)
    rec, rh, ru = member(db, None, "rec-b@example.com", "accounts")
    nobody, nh, _ = member(db, None, "nobody-b@example.com", "accounts")
    assert rec.get("/api/team/allocation-list?format=xlsx", headers=rh).status_code == 403
    r = c.put("/api/team/settings", json={"allocation_recipients": [str(ru.id)]}, headers=h)
    assert r.status_code == 200, r.text
    assert c.post("/api/team/allocation-list/send", headers=h).json() == {"sent_to": 1}
    r = rec.get("/api/team/allocation-list?format=xlsx", headers=rh)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert nobody.get("/api/team/allocation-list?format=xlsx", headers=nh).status_code == 403


def test_the_board_help_says_what_the_board_does():
    _, lines = HELP["/planning/board"][""]
    text = " ".join(lines)
    assert "Drag" not in text and "Red sites" not in text and "Move to" in text


# --- New areas: "the site (top level)" ------------------------------------------------------------


def test_approving_a_new_area_at_the_top_level(boss, db):
    c, h = boss
    sid = new_site(c, h)
    floor = node(c, h, sid, "floor", "Floor 1")

    def ask(name):
        r = c.post(
            "/api/sitecontrol/new-areas",
            data={"site_id": str(sid), "name": name, "parent_node_id": str(floor)},
            files={"photo": ("p.jpg", jpg(), "image/jpeg")},
            headers=h,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    top = ask("Invented machine room")
    r = c.post(
        f"/api/sitecontrol/new-areas/{top}/approve",
        json={"parent_node_id": None, "kind": "other"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert db.get(SiteNode, r.json()["node_id"]).parent_id is None  # the top level, as picked
    under = ask("Invented duct")
    r = c.post(f"/api/sitecontrol/new-areas/{under}/approve", json={}, headers=h)
    assert db.get(SiteNode, r.json()["node_id"]).parent_id == floor  # left out: the asked place
    third = ask("Invented shaft")
    elsewhere = node(c, h, new_site(c, h, "Invented Elsewhere"), "floor", "F9")
    r = c.post(
        f"/api/sitecontrol/new-areas/{third}/approve", json={"parent_node_id": elsewhere}, headers=h
    )
    assert r.status_code == 422
