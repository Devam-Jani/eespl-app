# ruff: noqa: E501
"""Bug sweep, group C (site work): material requests, survey edit / reopen, the phone's daily report,
My site today, labour and attendance, the issue log. Invented data only."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.closeout.models import IssueComment, SiteIssueLog
from app.execution import dpr as dpr_mod
from app.execution import service as svc
from app.execution.models import Dpr, DprLine
from app.models import User
from app.portal.models import Snag
from app.sites.models import AreaScope, Site, SiteMember, SiteNode, StageTemplate
from app.survey.models import Survey
from tests.conftest import login
from tests.test_execution import mark, site, worker
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_material_estimate import _engineer, _estimate, terrace  # noqa: F401  (fixture)
from tests.test_survey import add_area, new_survey, world  # noqa: F401  (fixture)

D = Decimal
TODAY = svc.today()


def _uid(db, email):
    return db.scalar(select(User.id).where(User.email == email))


def _member(db, site_id, email, role="supervisor"):
    db.add(SiteMember(site_id=site_id, user_id=_uid(db, email), role_on_site=role))
    db.commit()


# --- material requests ------------------------------------------------------------------------------


def test_a_reason_is_kept_only_on_a_request_over_the_estimate(terrace, db, login_as):  # noqa: F811
    t = terrace
    e = _estimate(
        t,
        [
            {
                "product_id": t["ids"]["Nodular"],
                "mix_design_id": t["nod"],
                "thickness_mm": "165",
                "part": "floor",
            }
        ],
    )
    lt = next(a for a in e["areas"] if a["code"] == "LT")
    ec, eh = _engineer(t, db, login_as)
    body = {
        "site_id": t["site"].id,
        "product_id": t["ids"]["Nodular"],
        "area_sqm": "20",
        "thickness_mm": "165",
        "mix_design_id": t["nod"],
        "estimate_area_id": lt["id"],
    }
    r = ec.post(
        "/api/estimate/requests",
        json=body | {"reason": "typed before the size was changed"},
        headers=eh,
    )
    assert r.status_code == 200, r.text
    assert r.json()["over_reason"] is None  # within the estimate: no "Over: ..." flag


# --- survey ----------------------------------------------------------------------------------------


def test_edit_keeps_a_camera_area_camera_measured_and_reopen_needs_edit_or_approve(
    boss,  # noqa: F811
    world,  # noqa: F811
    db,
    login_as,
):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    a = add_area(
        client,
        h,
        sid,
        area_type_id=world["toilet"],
        shape="direct",
        direct_area_sqm="0",
        upturn_mm=0,
    )
    r = client.post(
        f"/api/surveys/areas/{a['id']}/camera",
        json={"method": "ar", "polygon_m": [[0, 0], [3, 0], [3, 2], [0, 2]]},
        headers=h,
    )
    area = r.json()["areas"][0]
    assert area["camera_measured"] is True
    # Edit → Save without touching "Measured by": the camera method is sent back and kept
    body = {
        "name": "Area",
        "area_type_id": world["toilet"],
        "shape": "polygon",
        "polygon_m": area["polygon_m"],
        "upturn_mm": 0,
        "method": "ar",
    }
    r = client.put(f"/api/surveys/areas/{a['id']}", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert (
        r.json()["areas"][0]["camera_measured"] is True and r.json()["areas"][0]["method"] == "ar"
    )
    # a camera method cannot be typed on an area the camera never measured
    b = add_area(client, h, sid, area_type_id=world["toilet"], length_m="2", width_m="2")
    bad = client.put(
        f"/api/surveys/areas/{b['id']}",
        json={"name": "B", "length_m": "2", "width_m": "2", "method": "marker"},
        headers=h,
    )
    assert bad.status_code == 422
    assert (
        client.post(
            f"/api/surveys/{sid}/areas",
            json={"name": "C", "length_m": "2", "width_m": "2", "method": "ar"},
            headers=h,
        ).status_code
        == 422
    )

    # Reopen on a submitted survey: not a view-only role (planning), yes the editor
    db.get(Survey, sid).status = "submitted"
    db.commit()
    pc, ph = login_as("planning", email="planning@example.com")
    assert pc.get(f"/api/surveys/{sid}", headers=ph).json()["can_edit"] is False
    assert pc.post(f"/api/surveys/{sid}/reopen", headers=ph).status_code == 403
    assert client.post(f"/api/surveys/{sid}/reopen", headers=h).json()["status"] == "draft"


# --- the phone's daily report ------------------------------------------------------------------------


def test_the_phone_send_keeps_the_dpr_tab_fields_and_the_last_place_submits(
    login_as, make_user, db
):
    client, h = login_as("super_admin", email="boss@example.com")
    s = site(client, h, "Invented Phone Site")
    make_user("sup@example.com", "site_supervisor")
    _member(db, s["id"], "sup@example.com")
    sup = login(client, "sup@example.com")
    url = f"/api/execution/sites/{s['id']}/dprs/{TODAY}"
    typed = {
        "weather": "Sunny",
        "work_done": "Typed on the DPR tab",
        "hindrances": "Rain at 4",
        "next_day_plan": "Second coat",
    }
    assert client.put(url, json=typed, headers=sup).status_code == 200
    # a phone send: only the lines (as reportQueue.sendReport), the typed fields stay
    line = {
        "description": "Toilet 1 · Primer: done",
        "qty": None,
        "unit": None,
        "node_id": None,
        "area_scope_id": None,
    }
    r = client.put(url, json={"lines": [line], "submit": False}, headers=sup)
    assert r.status_code == 200, r.text
    got = r.json()
    assert {k: got[k] for k in typed} == typed and len(got["lines"]) == 1
    # the last place: submits (the work done is there)
    r = client.put(url, json={"submit": True}, headers=sup)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted" and r.json()["work_done"] == "Typed on the DPR tab"

    # a day nobody typed on: the phone sends the work done made from its lines, then submits
    s2 = site(client, h, "Invented Phone Site 2")
    _member(db, s2["id"], "sup@example.com")
    url2 = f"/api/execution/sites/{s2['id']}/dprs/{TODAY}"
    assert (
        client.put(url2, json={"lines": [line], "submit": True}, headers=sup).status_code == 422
    )  # still needs a work done
    assert (
        client.put(
            url2,
            json={"lines": [line], "work_done": line["description"], "submit": False},
            headers=sup,
        ).status_code
        == 200
    )
    assert client.put(url2, json={"submit": True}, headers=sup).json()["status"] == "submitted"


def test_running_metres_never_count_on_a_scope_in_sqm(db):
    s = Site(code="S-BSC-1", name="Invented unit site", status="active")
    db.add(s)
    db.flush()
    node = SiteNode(site_id=s.id, kind="balcony", name="Balcony")
    tpl = StageTemplate(name="Invented balcony PU")
    db.add_all([node, tpl])
    db.flush()
    sc = AreaScope(site_id=s.id, node_id=node.id, stage_template_id=tpl.id, qty=D(10), unit="sqm")
    db.add(sc)
    db.flush()
    d = Dpr(site_id=s.id, on_date=TODAY, status="submitted")
    d.lines.append(
        DprLine(
            description="Balcony · Primer · 12 ft 0 in",
            qty=D("3.658"),
            unit="m",
            node_id=node.id,
            area_scope_id=sc.id,
        )
    )
    db.add(d)
    db.flush()
    assert dpr_mod.apply_lines(db, d) == []
    assert D(sc.dpr_done_qty or 0) == 0 and d.lines[0].applied is not True
    d.lines.append(
        DprLine(
            description="Balcony · Primer",
            qty=D("4"),
            unit="sqm",
            node_id=node.id,
            area_scope_id=sc.id,
        )
    )
    db.flush()
    assert dpr_mod.apply_lines(db, d) == [sc.id] and D(sc.dpr_done_qty) == 4


# --- My site today -----------------------------------------------------------------------------------


def test_the_supervisor_items_name_their_site_and_open_snags_count(login_as, make_user, db):
    client, h = login_as("super_admin", email="boss@example.com")
    one, two = site(client, h, "Invented One"), site(client, h, "Invented Two")
    make_user("sup@example.com", "site_supervisor")
    for s in (one, two):
        _member(db, s["id"], "sup@example.com")
    db.add(
        Snag(
            code="SNG-BSC-1",
            site_id=one["id"],
            title="Invented crack at the drain",
            raised_by_side="staff",
            status="open",
        )
    )
    db.add(
        Snag(
            code="SNG-BSC-2",
            site_id=two["id"],
            title="Invented closed snag",
            raised_by_side="staff",
            status="closed",
        )
    )
    db.commit()
    data = client.get("/api/team/my-work", headers=login(client, "sup@example.com")).json()
    items = next(x for x in data["sections"] if x["role"] == "site_supervisor")["items"]
    assert items and all(i["site_id"] in (one["id"], two["id"]) for i in items)
    snags = [i for i in items if i["source"] == "snag"]
    assert [(i["site_id"], i["title"]) for i in snags] == [
        (one["id"], "Invented crack at the drain")
    ]


# --- labour and attendance ---------------------------------------------------------------------------


def test_add_worker_lists_the_supervisors_sites_and_attendance_manage_marks(
    login_as, make_user, db
):
    client, h = login_as("super_admin", email="boss@example.com")
    mine, other = site(client, h, "Invented Mine"), site(client, h, "Invented Other")
    make_user("sup@example.com", "site_supervisor")
    _member(db, mine["id"], "sup@example.com")
    sup = login(client, "sup@example.com")
    assert [s["id"] for s in client.get("/api/execution/labour/sites", headers=sup).json()] == [
        mine["id"]
    ]
    assert {s["id"] for s in client.get("/api/execution/labour/sites", headers=h).json()} >= {
        mine["id"],
        other["id"],
    }
    w = worker(
        client, sup, mine["id"], name="Invented Suresh"
    )  # posted from the Labour page's picker

    # a site engineer holds attendance.manage (not labour.edit): marking works on their site only
    make_user("eng@example.com", "site_engineer")
    _member(db, mine["id"], "eng@example.com", "incharge")
    eng = login(client, "eng@example.com")
    r = mark(client, eng, mine["id"], TODAY, {"labour_id": w["id"], "status": "present"})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["rows"] if x["labour_id"] == w["id"])["status"] == "present"
    assert (
        mark(
            client, eng, other["id"], TODAY, {"labour_id": w["id"], "status": "present"}
        ).status_code
        == 404
    )
    # a role with neither cannot mark
    make_user("est@example.com", "estimator")
    est = login(client, "est@example.com")
    assert mark(
        client,
        est,
        mine["id"],
        TODAY - timedelta(days=1),
        {"labour_id": w["id"], "status": "present"},
    ).status_code in (403, 404)


# --- the issue log -----------------------------------------------------------------------------------


def test_raise_an_issue_resolve_it_with_what_was_done_and_a_closed_one_stays_closed(login_as, db):
    client, h = login_as("super_admin", email="boss@example.com")
    s = site(client, h, "Invented Issue Site")
    cats = client.get("/api/closeout/issue-categories", headers=h).json()
    assert {"code": "leakage", "label": "Leakage"} in cats
    boss_id = str(_uid(db, "boss@example.com"))
    r = client.post(
        "/api/closeout/issues",
        json={
            "site_id": s["id"],
            "category": "quality",
            "title": "Invented hollow tile",
            "assigned_to": boss_id,
            "due_on": str(TODAY),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    i = r.json()
    assert i["assigned_to_id"] == boss_id and i["due_on"] == str(TODAY)
    p = client.post(
        f"/api/closeout/issues/{i['id']}/photos",
        files={"file": ("t.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
        headers=h,
    )
    assert p.status_code == 200 and p.json()["photos"] == 1
    r = client.put(
        f"/api/closeout/issues/{i['id']}",
        json={"status": "resolved", "note": "Tile re-fixed with polymer adhesive"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert r.json()["comments"][-1]["body"] == "What was done: Tile re-fixed with polymer adhesive"
    # closed: "Resolved" again is refused (no second resolved event)
    assert (
        client.put(
            f"/api/closeout/issues/{i['id']}", json={"status": "closed"}, headers=h
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/closeout/issues/{i['id']}", json={"status": "resolved"}, headers=h
        ).status_code
        == 422
    )
    assert db.get(SiteIssueLog, i["id"]).status == "closed"
    assert db.scalar(select(IssueComment.body).where(IssueComment.issue_id == i["id"])).startswith(
        "What was done"
    )
