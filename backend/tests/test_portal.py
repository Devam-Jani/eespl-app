"""Client portal: invites, scoping (another client's anything is a 404, staff endpoints a 403),
what never reaches the portal, forbidden keys, client RA certification, snags, comments and
notifications. Invented data."""

import base64
import re
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth.deps import CLIENT_PATHS
from app.config import settings
from app.execution import service as ex
from app.execution.models import ChecklistTemplate, Dpr, Inspection, Mom, MomPoint
from app.main import app
from app.masters.models import Client
from app.models import User
from app.portal.models import Notification, NotificationOutbox, PortalInvite, Snag
from app.sites.models import Drawing, DrawingRevision, Site, Task, TaskPhoto
from tests.conftest import login
from tests.test_finance import boss, contract, lines_by_desc, world  # noqa: F401  (fixtures)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SIGNATURE = "data:image/png;base64," + base64.b64encode(PNG).decode()
FORBIDDEN = ("cost_rate", "margin", "budget", "salary", "wage", "vendor", "subcontractor")
PASSWORD = "Portal-pass-2026"


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    return tmp_path


class Recorder:
    """A TestClient for one client login that keeps every JSON body the portal returned."""

    def __init__(self, headers):
        self.c, self.h, self.bodies = TestClient(app), headers, []

    def __getattr__(self, method):
        def call(path, **kw):
            r = getattr(self.c, method)(path, headers={**self.h, **kw.pop("headers", {})}, **kw)
            if r.headers.get("content-type", "").startswith("application/json"):
                self.bodies.append((path, r.json()))
            return r

        return call


def forbidden_keys(body, path="") -> list[str]:
    found = []
    if isinstance(body, dict):
        for k, v in body.items():
            if any(f in k.lower() for f in FORBIDDEN):
                found.append(f"{path}.{k}")
            found += forbidden_keys(v, f"{path}.{k}")
    elif isinstance(body, list):
        for i, v in enumerate(body):
            found += forbidden_keys(v, f"{path}[{i}]")
    return found


def invite(client, h, client_id, site_ids, email):
    r = client.post(
        "/api/portal-admin/invites",
        json={
            "full_name": f"DEMO {email.split('@')[0]}",
            "email": email,
            "client_id": client_id,
            "site_ids": site_ids,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def accept(link):
    token = link.rsplit("/", 1)[1]
    return TestClient(app).post(f"/api/portal/invite/{token}", json={"password": PASSWORD})


@pytest.fixture
def portal(boss, world, db, media):  # noqa: F811
    """Client A (the finance world's site, with an RA bill submitted, a submitted and a draft
    DPR, a shared and an unshared photo / drawing, an inspection and a MOM) and client B with
    its own site and the same kind of records. One portal login for each."""
    client, h = boss
    boss_id = db.scalar(select(User.id).where(User.email == "boss@example.com"))
    other = Client(name="Other Invented Client", state="Gujarat")
    db.add(other)
    db.commit()
    sb = client.post(
        "/api/sites",
        json={"name": "Other Site", "client_id": other.id, "state": "Gujarat"},
        headers=h,
    ).json()
    sites = {"A": world["site"], "B": sb["id"]}
    for s in sites.values():
        db.get(Site, s).site_incharge_id = boss_id
        r = client.put(
            f"/api/portal-admin/sites/{s}", json={"visible": True, "sections": {}}, headers=h
        )
        assert r.status_code == 200, r.text
    tpl = db.scalars(select(ChecklistTemplate)).first()
    out = {"sites": sites, "client_ids": {"A": world["client"], "B": other.id}}
    for k, s in sites.items():
        auto = {
            "tasks": [],
            "issued": [],
            "equipment": [
                {
                    "asset": "AST-1 Invented mixer",
                    "quantity": "1",
                    "basis": "day",
                    "operator": "Operator Invented",
                }
            ],
            "received": [
                {"code": "GRN-2026-0001", "from": "Invented Supplier", "items": "PU 10 kg"}
            ],
            "labour": {
                "present": 2,
                "half_day": 1,
                "absent": 0,
                "by_trade": {"applicator": 3},
                "names": ["Ramesh Invented", "Suresh Invented", "Mahesh Invented"],
            },
        }
        sub = Dpr(
            site_id=s,
            on_date=ex.today() - timedelta(days=2),
            status="submitted",
            work_done=f"Work {k}",
            auto=auto,
        )
        draft = Dpr(
            site_id=s,
            on_date=ex.today() - timedelta(days=1),
            status="draft",
            work_done=f"Draft {k}",
        )
        task = Task(site_id=s, name=f"Primer {k}")
        db.add_all([sub, draft, task])
        db.flush()
        (media / f"p{k}.png").write_bytes(PNG)
        shared = TaskPhoto(
            task_id=task.id, stored_path=f"p{k}.png", filename="shared.png", share_with_client=True
        )
        hidden = TaskPhoto(task_id=task.id, stored_path=f"p{k}.png", filename="hidden.png")
        drw = Drawing(site_id=s, title=f"Terrace plan {k}", share_with_client=True)
        drw_hidden = Drawing(site_id=s, title=f"Internal {k}")
        db.add_all([shared, hidden, drw, drw_hidden])
        db.flush()
        for d in (drw, drw_hidden):
            rev = DrawingRevision(
                drawing_id=d.id,
                rev_no=0,
                stored_path=f"p{k}.png",
                filename="plan.png",
                size_bytes=72,
                status="approved",
            )
            db.add(rev)
            db.flush()
            d.current_revision_id = rev.id
        insp = Inspection(
            code=f"INS-2026-90{len(k)}{k}",
            site_id=s,
            template_id=tpl.id,
            on_date=ex.today(),
            answers=[{"item_id": 1, "text": "Ponding", "type": "pass_fail", "value": "pass"}],
            result="pass",
        )
        mom = Mom(code=f"MOM-2026-90{k}", site_id=s, on_date=ex.today(), title=f"Review {k}")
        db.add_all([insp, mom])
        db.flush()
        db.add(MomPoint(mom_id=mom.id, text="Client to clear the terrace", owner_name="Client PMC"))
        db.commit()
        out[k] = {
            "dpr": sub.id,
            "draft": draft.id,
            "photo": shared.id,
            "hidden_photo": hidden.id,
            "drawing": f"drawing-{drw.id}",
            "hidden_drawing": f"drawing-{drw_hidden.id}",
            "inspection": insp.id,
            "mom": mom.id,
        }
    for k in ("A", "B"):
        link = invite(
            client, h, out["client_ids"][k], [sites[k]], f"client-{k.lower()}@example.com"
        )["link"]
        assert accept(link).status_code == 200
        out[f"user_{k}"] = Recorder(
            login(TestClient(app), f"client-{k.lower()}@example.com", PASSWORD)
        )
    c = contract(client, h, world)
    ra = client.post(
        f"/api/finance/contracts/{c['id']}/ra-bills", json={"period_to": "2026-09-30"}, headers=h
    ).json()
    assert client.post(f"/api/finance/ra-bills/{ra['id']}/submit", headers=h).status_code == 200
    out["A"]["ra"] = ra["id"]
    out["ra_lines"] = lines_by_desc(ra)
    out["contract"] = c["id"]
    return out


# --- invites and login ---------------------------------------------------------------------------


def test_invite_link_is_one_time_and_expires(boss, world, db):  # noqa: F811
    client, h = boss
    client.put(f"/api/portal-admin/sites/{world['site']}", json={"visible": True}, headers=h)
    res = invite(client, h, world["client"], [world["site"]], "new-client@example.com")
    assert res["link"].startswith("/portal/invite/") and "token" not in str(
        db.scalar(select(PortalInvite.token_hash))
    )
    days = (res["expires_at"][:10], str(ex.today() + timedelta(days=7)))
    assert days[0] >= days[1] or abs(int(days[0][-2:]) - int(days[1][-2:])) <= 1  # 7 days (setting)
    token = res["link"].rsplit("/", 1)[1]
    # no password yet: cannot log in
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"email": "new-client@example.com", "password": PASSWORD})
        .status_code
        == 401
    )
    assert (
        TestClient(app).get(f"/api/portal/invite/{token}").json()["email"]
        == "new-client@example.com"
    )
    assert accept(res["link"]).status_code == 200
    assert accept(res["link"]).status_code == 410  # one-time
    headers = login(TestClient(app), "new-client@example.com", PASSWORD)
    me = TestClient(app).get("/api/auth/me", headers=headers).json()
    assert set(me["permissions"]) == {
        "portal.view",
        "portal.comment",
        "portal.snag",
        "portal.approve",
    }

    # a re-invite revokes the earlier link; an expired link is refused
    uid = db.scalar(select(User.id).where(User.email == "new-client@example.com"))
    first = client.post(f"/api/portal-admin/users/{uid}/reinvite", headers=h).json()["link"]
    second = client.post(f"/api/portal-admin/users/{uid}/reinvite", headers=h).json()["link"]
    assert accept(first).status_code == 410
    db.execute(
        text(
            "UPDATE portal_invites SET expires_at = now() - interval '1 minute' "
            "WHERE used_at IS NULL AND revoked_at IS NULL"
        )
    )
    db.commit()
    assert accept(second).status_code == 410
    # a staff email cannot be turned into a client login
    r = client.post(
        "/api/portal-admin/invites",
        json={
            "full_name": "x",
            "email": "boss@example.com",
            "client_id": world["client"],
            "site_ids": [world["site"]],
        },
        headers=h,
    )
    assert r.status_code == 409
    audit = (
        db.execute(
            text(
                "SELECT action FROM audit_log WHERE action LIKE 'portal.%' OR action = 'auth.login'"
            )
        )
        .scalars()
        .all()
    )
    assert {"portal.invite", "portal.invite.accept", "portal.reinvite", "auth.login"} <= set(audit)


def test_disabled_client_is_logged_out_at_once(boss, portal, db):  # noqa: F811
    client, h = boss
    a = portal["user_A"]
    assert a.get("/api/portal/sites").status_code == 200
    uid = db.scalar(select(User.id).where(User.email == "client-a@example.com"))
    assert (
        client.put(
            f"/api/portal-admin/users/{uid}/active", json={"is_active": False}, headers=h
        ).status_code
        == 200
    )
    assert a.get("/api/portal/sites").status_code == 401  # the same access token
    assert a.c.post("/api/auth/refresh").status_code == 401  # and the refresh cookie
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"email": "client-a@example.com", "password": PASSWORD})
        .status_code
        == 401
    )
    assert (
        client.put(
            f"/api/portal-admin/users/{uid}/active", json={"is_active": True}, headers=h
        ).status_code
        == 200
    )
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"email": "client-a@example.com", "password": PASSWORD})
        .status_code
        == 200
    )


# --- scoping -------------------------------------------------------------------------------------


def portal_paths(p, k):
    s, x = p["sites"][k], p[k]
    paths = [
        f"/api/portal/sites/{s}",
        f"/api/portal/sites/{s}/model",
        f"/api/portal/sites/{s}/dprs",
        f"/api/portal/sites/{s}/dprs/{x['dpr']}/pdf",
        f"/api/portal/sites/{s}/photos",
        f"/api/portal/sites/{s}/photos/{x['photo']}",
        f"/api/portal/sites/{s}/inspections",
        f"/api/portal/sites/{s}/inspections/{x['inspection']}/pdf",
        f"/api/portal/sites/{s}/moms",
        f"/api/portal/sites/{s}/moms/{x['mom']}/pdf",
        f"/api/portal/sites/{s}/documents",
        f"/api/portal/sites/{s}/documents/{x['drawing']}",
        f"/api/portal/sites/{s}/billing",
        f"/api/portal/sites/{s}/snags",
        f"/api/portal/comments?entity_type=dpr&entity_id={x['dpr']}",
        f"/api/portal/comments?entity_type=inspection&entity_id={x['inspection']}",
    ]
    if "ra" in x:
        paths += [
            f"/api/portal/sites/{s}/ra-bills/{x['ra']}/pdf",
            f"/api/portal/comments?entity_type=ra_bill&entity_id={x['ra']}",
        ]
    return paths


def test_client_sees_only_their_visible_sites(boss, portal, db):  # noqa: F811
    a, b = portal["user_A"], portal["user_B"]
    assert [s["id"] for s in a.get("/api/portal/sites").json()] == [portal["sites"]["A"]]
    for path in portal_paths(portal, "A"):
        assert a.get(path).status_code == 200, path
        assert (
            b.get(path).status_code == 404
        ), path  # client B, client A's site / bill / DPR / photo / file
    # B's own records through A's site id: still 404
    sa, xb = portal["sites"]["A"], portal["B"]
    for path in (
        f"/api/portal/sites/{sa}/dprs/{xb['dpr']}/pdf",
        f"/api/portal/sites/{sa}/photos/{xb['photo']}",
        f"/api/portal/sites/{sa}/documents/{xb['drawing']}",
        f"/api/portal/sites/{sa}/inspections/{xb['inspection']}/pdf",
        f"/api/portal/sites/{sa}/moms/{xb['mom']}/pdf",
    ):
        assert a.get(path).status_code == 404, path
    for method, path, kw in (
        ("post", f"/api/portal/sites/{portal['sites']['A']}/snags", {"data": {"title": "x"}}),
        (
            "post",
            f"/api/portal/sites/{portal['sites']['A']}/ra-bills/{portal['A']['ra']}/certify",
            {"json": {}},
        ),
        (
            "post",
            f"/api/portal/sites/{portal['sites']['A']}/inspections/{portal['A']['inspection']}/sign",
            {"json": {"name": "x", "signature": SIGNATURE}},
        ),
        (
            "post",
            "/api/portal/comments",
            {"json": {"entity_type": "dpr", "entity_id": portal["A"]["dpr"], "body": "x"}},
        ),
    ):
        assert getattr(b, method)(path, **kw).status_code == 404, path
    # hidden in the portal, or a section switched off: 404 too
    client, h = boss
    client.put(
        f"/api/portal-admin/sites/{portal['sites']['A']}",
        json={"visible": True, "sections": {"billing": False}},
        headers=h,
    )
    assert a.get(f"/api/portal/sites/{portal['sites']['A']}/billing").status_code == 404
    assert a.get(f"/api/portal/sites/{portal['sites']['A']}/dprs").status_code == 200
    client.put(
        f"/api/portal-admin/sites/{portal['sites']['A']}", json={"visible": False}, headers=h
    )
    assert a.get(f"/api/portal/sites/{portal['sites']['A']}").status_code == 404
    assert a.get("/api/portal/sites").json() == []


def test_client_cannot_call_any_staff_endpoint(portal):
    a = portal["user_A"]
    wrong = []
    for route in app.routes:
        if (
            not isinstance(route, APIRoute)
            or route.path.startswith(CLIENT_PATHS)
            or route.path == "/api/health"
            # public by design: one delivery's items and counts, behind its receipt token
            or route.path.startswith("/api/receipt/")
        ):
            continue
        path = re.sub(r"\{[^}]*(id|uid)\}", "00000000-0000-0000-0000-000000000001", route.path)
        path = re.sub(r"\{[^}]+\}", "1", path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            r = getattr(a.c, method.lower())(path, headers=a.h)
            if r.status_code != 403:
                wrong.append(f"{method} {route.path}: {r.status_code}")
    assert not wrong, "\n".join(wrong)


def test_drafts_unshared_files_and_internal_notes_never_reach_the_portal(boss, portal):  # noqa: F811
    client, h = boss
    a, s, x = portal["user_A"], portal["sites"]["A"], portal["A"]
    dprs = a.get(f"/api/portal/sites/{s}/dprs").json()
    assert [d["id"] for d in dprs] == [x["dpr"]]  # the draft is not there
    assert a.get(f"/api/portal/sites/{s}/dprs/{x['draft']}/pdf").status_code == 404
    assert dprs[0]["headcount"] == {"present": 2, "half_day": 1, "by_trade": {"applicator": 3}}
    flat = str(dprs)
    assert (
        "Ramesh" not in flat and "Invented Supplier" not in flat and "Operator Invented" not in flat
    )
    assert [p["id"] for p in a.get(f"/api/portal/sites/{s}/photos").json()] == [x["photo"]]
    assert a.get(f"/api/portal/sites/{s}/photos/{x['hidden_photo']}").status_code == 404
    docs = a.get(f"/api/portal/sites/{s}/documents").json()
    assert [d["key"] for d in docs] == [x["drawing"]]
    assert a.get(f"/api/portal/sites/{s}/documents/{x['hidden_drawing']}").status_code == 404
    # staff share the photo off again: gone
    assert (
        client.put(
            f"/api/portal-admin/task-photos/{x['photo']}/share", json={"share": False}, headers=h
        ).status_code
        == 200
    )
    assert a.get(f"/api/portal/sites/{s}/photos").json() == []
    # internal notes stay with staff
    for body, internal in (("Visible to the client", False), ("Internal: check the rate", True)):
        r = client.post(
            "/api/comments",
            json={"entity_type": "dpr", "entity_id": x["dpr"], "body": body, "internal": internal},
            headers=h,
        )
        assert r.status_code == 201, r.text
    seen = a.get(f"/api/portal/comments?entity_type=dpr&entity_id={x['dpr']}").json()
    assert [c["body"] for c in seen] == ["Visible to the client"]
    staff = client.get(f"/api/comments?entity_type=dpr&entity_id={x['dpr']}", headers=h).json()
    assert len(staff) == 2
    # comments on a draft DPR are not reachable from the portal either
    assert a.get(f"/api/portal/comments?entity_type=dpr&entity_id={x['draft']}").status_code == 404


def test_no_forbidden_keys_in_any_portal_response(boss, portal):  # noqa: F811
    client, h = boss
    a, s, x = portal["user_A"], portal["sites"]["A"], portal["A"]
    for path in portal_paths(portal, "A") + ["/api/portal/sites", "/api/portal/me"]:
        a.get(path)
    a.post(
        f"/api/portal/sites/{s}/snags",
        data={"title": "Damp patch"},
        files=[("photos", ("d.png", PNG, "image/png"))],
    )
    a.post(f"/api/portal/sites/{s}/ra-bills/{x['ra']}/certify", json={})
    assert len(a.bodies) > 15
    bad = [k for path, body in a.bodies for k in forbidden_keys(body, path)]
    assert not bad, bad


# --- approvals -----------------------------------------------------------------------------------


def test_client_ra_certification_counts_only_after_staff_confirm(boss, portal, db):  # noqa: F811
    client, h = boss
    a, s, rid = portal["user_A"], portal["sites"]["A"], portal["A"]["ra"]
    pu = portal["ra_lines"]["PU coating"]["contract_line_id"]
    r = a.post(
        f"/api/portal/sites/{s}/ra-bills/{rid}/certify",
        json={"lines": [{"contract_line_id": pu, "qty": "200"}]},
    )
    assert r.status_code == 422  # more than billed
    r = a.post(
        f"/api/portal/sites/{s}/ra-bills/{rid}/certify",
        json={"lines": [{"contract_line_id": pu, "qty": "60"}], "remark": "Checked on site"},
    )
    assert r.status_code == 200 and r.json()["status"] == "certified_by_client"
    staff = client.get(f"/api/finance/ra-bills/{rid}", headers=h).json()
    assert (
        staff["certified_gross"] is None
        and lines_by_desc(staff)["PU coating"]["certified_qty"] is None
    )
    assert (
        client.post(f"/api/finance/ra-bills/{rid}/invoice", json={}, headers=h).status_code == 409
    )  # not certified yet
    assert db.scalar(
        select(Notification.id).where(
            Notification.kind == "ra_certified", Notification.title.contains("please confirm")
        )
    )
    r = client.post(f"/api/finance/ra-bills/{rid}/confirm-client", headers=h)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "certified" and done["certified_by_client"] == "DEMO client-a"
    assert (
        lines_by_desc(done)["PU coating"]["certified_qty"] == "60.000"
        or float(lines_by_desc(done)["PU coating"]["certified_qty"]) == 60
    )
    assert float(done["certified_gross"]) == 60 * 500 + 10 * 200
    assert a.post(f"/api/portal/sites/{s}/ra-bills/{rid}/certify", json={}).status_code == 409


def test_client_rejects_and_staff_reopen(boss, portal):  # noqa: F811
    client, h = boss
    a, s, rid = portal["user_A"], portal["sites"]["A"], portal["A"]["ra"]
    assert (
        a.post(f"/api/portal/sites/{s}/ra-bills/{rid}/reject", json={"remark": ""}).status_code
        == 422
    )
    r = a.post(
        f"/api/portal/sites/{s}/ra-bills/{rid}/reject", json={"remark": "Coving qty is wrong"}
    )
    assert r.json()["status"] == "rejected_by_client"
    assert (
        client.get(f"/api/finance/ra-bills/{rid}", headers=h).json()["client_remark"]
        == "Coving qty is wrong"
    )
    assert client.post(f"/api/finance/ra-bills/{rid}/reopen", headers=h).json()["status"] == "draft"
    assert (
        a.get(f"/api/portal/sites/{s}/ra-bills/{rid}/pdf").status_code == 404
    )  # drafts are not shown


def test_inspection_signoff_and_mom_acknowledgement(boss, portal, db):  # noqa: F811
    client, h = boss
    a, s, x = portal["user_A"], portal["sites"]["A"], portal["A"]
    sign = {"name": "Invented PMC", "signature": SIGNATURE}
    assert (
        a.post(f"/api/portal/sites/{s}/inspections/{x['inspection']}/sign", json=sign).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/portal-admin/inspections/{x['inspection']}/request-signoff", headers=h
        ).status_code
        == 200
    )
    uid = db.scalar(select(User.id).where(User.email == "client-a@example.com"))
    assert db.scalar(
        select(Notification.id).where(
            Notification.user_id == uid, Notification.kind == "inspection_signoff"
        )
    )
    r = a.post(f"/api/portal/sites/{s}/inspections/{x['inspection']}/sign", json=sign)
    assert r.status_code == 200 and r.json()["client_signoff"] == "signed"
    assert (
        client.get(f"/api/execution/inspections/{x['inspection']}", headers=h).json()[
            "client_signed_name"
        ]
        == "Invented PMC"
    )
    point = a.get(f"/api/portal/sites/{s}/moms").json()[0]["points"][0]
    assert point["yours"]
    r = a.post(f"/api/portal/sites/{s}/mom-points/{point['id']}/acknowledge")
    assert r.status_code == 200 and r.json()["acknowledged_at"]
    actions = set(db.execute(text("SELECT action FROM audit_log")).scalars())
    assert {"portal.inspection.sign", "portal.mom.acknowledge"} <= actions


def test_client_upload_is_kept_apart_and_staff_are_told(boss, portal, db, media):  # noqa: F811
    client, h = boss
    a, s = portal["user_A"], portal["sites"]["A"]
    r = a.post(
        f"/api/portal/sites/{s}/documents",
        data={"title": "Our revised layout"},
        files={"file": ("layout.pdf", b"%PDF-1.4 x", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    docs = client.get(f"/api/portal-admin/sites/{s}/documents", headers=h).json()
    assert docs[0]["source"] == "client" and (media / "portal" / "client-uploads" / str(s)).is_dir()
    assert db.scalar(
        select(Notification.title).where(Notification.kind == "client_upload")
    ).startswith("The client uploaded")
    assert "portal.upload" in set(db.execute(text("SELECT action FROM audit_log")).scalars())
    # client B never sees it
    assert (
        portal["user_B"].get(f"/api/portal/sites/{s}/documents/{r.json()['key']}").status_code
        == 404
    )


# --- snags and notifications ---------------------------------------------------------------------


def test_snag_lifecycle_with_reopen(boss, portal, db):  # noqa: F811
    client, h = boss
    a, s = portal["user_A"], portal["sites"]["A"]
    boss_id = db.scalar(select(User.id).where(User.email == "boss@example.com"))
    client_id = db.scalar(select(User.id).where(User.email == "client-a@example.com"))
    r = a.post(
        f"/api/portal/sites/{s}/snags",
        data={"title": "Damp patch below terrace", "area": "Flat 302"},
        files=[("photos", ("before.png", PNG, "image/png"))],
    )
    assert r.status_code == 201, r.text
    sn = r.json()
    assert (
        sn["status"] == "open"
        and sn["raised_by_side"] == "client"
        and sn["photos"][0]["kind"] == "before"
    )
    assert db.scalar(
        select(Notification.id).where(
            Notification.user_id == boss_id, Notification.kind == "snag_raised"
        )
    )
    assert db.scalar(select(NotificationOutbox.channel)) == "in_app"

    listed = client.get("/api/snags", params={"site_id": s, "status": "open"}, headers=h).json()
    assert [x["id"] for x in listed] == [sn["id"]]
    r = client.patch(f"/api/snags/{sn['id']}", json={"status": "fixed"}, headers=h)
    assert r.status_code == 422  # needs an after photo
    assert (
        client.post(
            f"/api/snags/{sn['id']}/photos",
            files={"file": ("after.png", PNG, "image/png")},
            headers=h,
        ).status_code
        == 201
    )
    r = client.patch(
        f"/api/snags/{sn['id']}", json={"status": "fixed", "assigned_to": str(boss_id)}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "fixed"
    assert db.scalar(
        select(Notification.id).where(
            Notification.user_id == client_id, Notification.kind == "snag_updated"
        )
    )
    assert (
        client.patch(f"/api/snags/{sn['id']}", json={"status": "verified"}, headers=h).status_code
        == 409
    )  # the client verifies

    r = a.post(
        f"/api/portal/sites/{s}/snags/{sn['id']}/reopen", json={"remark": "Still damp after rain"}
    )
    assert r.json()["status"] == "open" and r.json()["reopened"] == 1
    client.patch(f"/api/snags/{sn['id']}", json={"status": "fixed"}, headers=h)
    r = a.post(f"/api/portal/sites/{s}/snags/{sn['id']}/verify")
    assert r.json()["status"] == "verified"
    assert (
        client.patch(f"/api/snags/{sn['id']}", json={"status": "closed"}, headers=h).json()[
            "status"
        ]
        == "closed"
    )
    assert db.get(Snag, sn["id"]).verified_at is not None
    thread = a.get(f"/api/portal/comments?entity_type=snag&entity_id={sn['id']}").json()
    assert thread[0]["body"].startswith("Reopened")
    photo = sn["photos"][0]["id"]
    assert (
        portal["user_B"].get(f"/api/portal/sites/{s}/snags/{sn['id']}/photos/{photo}").status_code
        == 404
    )


def test_notifications_go_to_the_right_side(boss, portal, db):  # noqa: F811
    client, h = boss
    a, s = portal["user_A"], portal["sites"]["A"]
    client_a = db.scalar(select(User.id).where(User.email == "client-a@example.com"))
    client_b = db.scalar(select(User.id).where(User.email == "client-b@example.com"))
    boss_id = db.scalar(select(User.id).where(User.email == "boss@example.com"))

    # the RA bill submitted in the fixture told client A only
    def kinds(uid):
        return set(db.scalars(select(Notification.kind).where(Notification.user_id == uid)))

    assert "ra_submitted" in kinds(client_a) and "ra_submitted" not in kinds(client_b)
    # a DPR submitted through the staff API reaches client A
    url = f"/api/execution/sites/{s}/dprs/{ex.today()}"
    assert (
        client.put(
            url, json={"work_done": "Primer on terrace", "submit": True}, headers=h
        ).status_code
        == 200
    )
    assert "dpr_submitted" in kinds(client_a) and "dpr_submitted" not in kinds(boss_id)
    # a client comment reaches staff, not the client
    r = a.post(
        "/api/portal/comments",
        json={"entity_type": "dpr", "entity_id": portal["A"]["dpr"], "body": "Please share photos"},
    )
    assert r.status_code == 201
    assert "comment" in kinds(boss_id) and "comment" not in kinds(client_a)
    bell = a.get("/api/notifications").json()
    assert bell["unread"] >= 2 and all(n["site_id"] == s for n in bell["items"])
    assert a.post("/api/notifications/read-all").status_code == 200
    assert a.get("/api/notifications").json()["unread"] == 0
    # a staff member previews as the client, read-only
    pv = {"X-Preview-As": str(client_a)}
    assert client.get(f"/api/portal/sites/{s}", headers={**h, **pv}).status_code == 200
    assert (
        client.post(
            f"/api/portal/sites/{s}/snags", data={"title": "x"}, headers={**h, **pv}
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/portal/sites/{portal['sites']['B']}", headers={**h, **pv}).status_code
        == 404
    )
    assert (
        client.get(f"/api/portal/sites/{s}", headers=h).status_code == 403
    )  # staff without preview


# --- M6 review fixes -----------------------------------------------------------------------------


def test_snag_can_be_assigned_to_another_staff_member_of_the_site(boss, portal, db, make_user):  # noqa: F811
    from app.sites.models import SiteMember

    client, h = boss
    s = portal["sites"]["A"]
    member = make_user("supervisor-on-a@example.com", "site_supervisor", name="DEMO Supervisor A")
    outsider = make_user("supervisor-elsewhere@example.com", "site_supervisor")
    gone = make_user("left@example.com", "site_supervisor", is_active=False)
    db.add_all(
        [
            SiteMember(site_id=s, user_id=member.id, role_on_site="supervisor"),
            SiteMember(site_id=s, user_id=gone.id, role_on_site="supervisor"),
        ]
    )
    db.commit()
    names = {
        u["full_name"]
        for u in client.get("/api/snags/assignees", params={"site_id": s}, headers=h).json()
    }
    assert (
        "DEMO Supervisor A" in names and "left" not in names and "supervisor-elsewhere" not in names
    )
    sn = client.post("/api/snags", data={"site_id": s, "title": "Loose tile"}, headers=h).json()
    r = client.patch(f"/api/snags/{sn['id']}", json={"assigned_to": str(member.id)}, headers=h)
    assert r.status_code == 200 and r.json()["assigned_to_name"] == "DEMO Supervisor A"
    assert db.scalar(
        select(Notification.id).where(
            Notification.user_id == member.id, Notification.kind == "snag_assigned"
        )
    )
    for other in (outsider, gone):
        assert (
            client.patch(
                f"/api/snags/{sn['id']}", json={"assigned_to": str(other.id)}, headers=h
            ).status_code
            == 422
        )
    bad = client.post(
        "/api/snags", data={"site_id": s, "title": "x", "assigned_to": str(outsider.id)}, headers=h
    )
    assert bad.status_code == 422


def test_portal_billing_labels_due_now_and_total_outstanding(boss, portal):  # noqa: F811
    client, h = boss
    a, s, rid = portal["user_A"], portal["sites"]["A"], portal["A"]["ra"]
    pu = portal["ra_lines"]["PU coating"]["contract_line_id"]
    body = {
        "lines": [{"contract_line_id": pu, "certified_qty": "70"}],
        "certified_by_client": "PMC",
    }
    assert (
        client.post(f"/api/finance/ra-bills/{rid}/certify", json=body, headers=h).status_code == 200
    )
    assert (
        client.post(f"/api/finance/ra-bills/{rid}/invoice", json={}, headers=h).status_code == 201
    )
    o = a.get(f"/api/portal/sites/{s}/billing").json()["outstanding"]
    total, due, ret = float(o["total"]), float(o["due"]), float(o["retention_in_total"])
    assert ret > 0 and due > 0 and abs(total - (due + ret)) < 0.01


def test_client_can_upload_dwg_and_dxf_but_not_other_files(portal):
    a, s = portal["user_A"], portal["sites"]["A"]
    for name in ("layout.dwg", "layout.DXF"):
        r = a.post(
            f"/api/portal/sites/{s}/documents",
            data={"title": name},
            files={"file": (name, b"AC1032 invented", "application/octet-stream")},
        )
        assert r.status_code == 201, r.text
    r = a.post(
        f"/api/portal/sites/{s}/documents",
        data={"title": "x"},
        files={"file": ("run.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 422 and ".dwg" in r.text
    keys = [
        d["key"]
        for d in a.get(f"/api/portal/sites/{s}/documents").json()
        if d["filename"].lower().startswith("layout")
    ]
    assert (
        len(keys) == 2
        and a.get(f"/api/portal/sites/{s}/documents/{keys[0]}").content == b"AC1032 invented"
    )
