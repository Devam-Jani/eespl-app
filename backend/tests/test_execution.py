"""Execution: DPR, attendance and muster roll, Aadhaar, work orders, inspections and hold points,
assets, budget vs actual (with shortage and GRN-based freight), permissions. Invented data only."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.execution import service as svc
from app.execution.models import ChecklistTemplate, Labour, SiteBudget
from app.masters.models import Product, Vendor
from app.models import AuditLog, Permission, Role, RolePermission, User
from app.sites.models import StageTemplate, StageTemplateStep, Task, TaskPhoto
from tests.conftest import login

D = Decimal
TODAY = svc.today()
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # an invented "photo"


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


@pytest.fixture
def masters(db):
    p = Product(code="T-PU", name="Test PU coating", unit="ltr", gst_percent=18)
    v = Vendor(name="Invented Supplies", state="Gujarat")
    sub = Vendor(
        name="Invented Applicators", type="subcontractor", pan="ABCPD1234E", state="Gujarat"
    )
    db.add_all([p, v, sub])
    db.commit()
    return {"product": p.id, "vendor": v.id, "sub": sub.id}


def site(client, h, name="Invented Heights", active=True):
    r = client.post(
        "/api/sites", json={"name": name, "start_date": str(TODAY - timedelta(days=60))}, headers=h
    )
    assert r.status_code == 201, r.text
    s = r.json()
    if active:
        assert (
            client.patch(f"/api/sites/{s['id']}", json={"status": "active"}, headers=h).status_code
            == 200
        )
    return s


def store_of(client, h, site_id):
    return client.get("/api/material/stores", params={"site_id": site_id}, headers=h).json()[0][
        "id"
    ]


def godown(client, h):
    return next(
        s for s in client.get("/api/material/stores", headers=h).json() if s["kind"] == "godown"
    )["id"]


def worker(client, h, site_id, name="Invented Ramesh", **extra):
    body = {
        "name": name,
        "trade": "applicator",
        "site_id": site_id,
        "daily_wage": "600",
        "ot_rate_per_hour": "75",
        **extra,
    }
    r = client.post("/api/execution/labour", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def mark(client, h, site_id, day, *marks):
    return client.put(
        f"/api/execution/sites/{site_id}/attendance/{day}", json={"marks": list(marks)}, headers=h
    )


def uid(db, email):
    return str(db.scalar(select(User.id).where(User.email == email)))


def hold_point_task(db, site_id, checklist="Ponding test", status="done"):
    cl = db.scalar(select(ChecklistTemplate).where(ChecklistTemplate.name == checklist))
    t = StageTemplate(name=f"Invented terrace {site_id}")
    t.steps = [
        StageTemplateStep(
            sort_order=1,
            name="Ponding test",
            weight_percent=100,
            hold_point=True,
            needs_photo=False,
            checklist_template_id=cl.id,
        )
    ]
    db.add(t)
    db.flush()
    task = Task(
        site_id=site_id,
        name="Ponding test",
        step_id=t.steps[0].id,
        status=status,
        progress_percent=100,
    )
    db.add(task)
    db.commit()
    return task.id, cl


def inspect(client, h, site_id, cl, task_id=None, answers=None, files=None, **extra):
    data = {
        "site_id": site_id,
        "template_id": cl.id,
        "task_id": task_id,
        "answers": answers or [],
        **extra,
    }
    return client.post(
        "/api/execution/inspections", data={"data": json.dumps(data)}, files=files or [], headers=h
    )


def ponding_answers(cl, leak="pass"):
    values = {
        "Outlets plugged and edges bunded": "pass",
        "Water depth (mm)": "50",
        "Duration (hours)": "48",
        "No leakage or dampness below at the end of the test": leak,
    }
    return [{"item_id": i.id, "value": values[i.text]} for i in cl.items if i.text in values]


def photo_files(cl):
    return [
        (f"item_{i.id}", ("ponding.png", PNG, "image/png")) for i in cl.items if i.type == "photo"
    ]


# --- DPR -----------------------------------------------------------------------------------------


def test_dpr_one_per_day_pulls_in_the_day_and_missing_list(boss, masters, db):
    client, h = boss
    s = site(client, h)
    st = store_of(client, h, s["id"])
    # the day's activity: a task update with a photo, a GRN, an issue, attendance, equipment
    task = Task(site_id=s["id"], name="Primer coat", status="in_progress", progress_percent=40)
    db.add(task)
    db.flush()
    db.add(TaskPhoto(task_id=task.id, stored_path="none.png", filename="primer.jpg"))
    db.commit()
    r = client.post(
        "/api/material/grns",
        json={
            "vendor_id": masters["vendor"],
            "store_id": st,
            "submit": True,
            "lines": [{"product_id": masters["product"], "received_qty": "20", "rate": "300"}],
        },
        headers=h,
    )
    assert client.post(f"/api/material/grns/{r.json()['id']}/approve", headers=h).status_code == 200
    r = client.post(
        "/api/material/issues",
        json={"site_id": s["id"], "lines": [{"product_id": masters["product"], "qty": "5"}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    w = worker(client, h, s["id"])
    assert (
        mark(client, h, s["id"], TODAY, {"labour_id": w["id"], "status": "present"}).status_code
        == 200
    )
    a = client.post(
        "/api/execution/assets", json={"name": "Invented grinder", "rate_per_day": "400"}, headers=h
    ).json()
    assert (
        client.post(
            f"/api/execution/assets/{a['id']}/move", data={"to_site_id": s["id"]}, headers=h
        ).status_code
        == 201
    )
    r = client.post(
        "/api/execution/equipment-usage",
        json={"asset_id": a["id"], "site_id": s["id"], "quantity": "1"},
        headers=h,
    )
    assert r.status_code == 201, r.text

    dpr = client.get(f"/api/execution/sites/{s['id']}/dprs/{TODAY}", headers=h).json()
    assert dpr["status"] == "new" and dpr["id"] is None
    auto = dpr["auto"]
    assert [t["name"] for t in auto["tasks"]] == ["Primer coat"] and len(
        auto["tasks"][0]["photos"]
    ) == 1
    assert len(auto["received"]) == 1 and auto["received"][0]["code"].startswith("GRN-")
    assert len(auto["issued"]) == 1 and auto["labour"]["present"] == 1
    assert auto["equipment"][0]["asset"].endswith("Invented grinder")

    url = f"/api/execution/sites/{s['id']}/dprs/{TODAY}"
    r = client.put(
        url, json={"weather": "Sunny", "work_done": "Primer on terrace", "submit": False}, headers=h
    )
    first = r.json()["id"]
    assert client.put(url, json={"work_done": "", "submit": True}, headers=h).status_code == 422
    r = client.put(
        url, json={"weather": "Sunny", "work_done": "Primer on terrace", "submit": True}, headers=h
    )
    assert r.json()["id"] == first and r.json()["status"] == "submitted"  # one DPR per site per day
    assert (
        client.put(url, json={"work_done": "again", "submit": True}, headers=h).status_code == 409
    )
    assert db.execute(text("SELECT count(*) FROM dprs")).scalar() == 1
    pdf = client.get(f"/api/execution/dprs/{first}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    # missing: yesterday had no DPR; a site that is not active is not expected to send one
    site(client, h, "Planned only", active=False)
    yesterday = TODAY - timedelta(days=1)
    missing = client.get(
        "/api/execution/dprs/missing", params={"day": str(yesterday)}, headers=h
    ).json()
    assert [x["id"] for x in missing["sites"]] == [s["id"]]
    client.put(
        f"/api/execution/sites/{s['id']}/dprs/{yesterday}",
        json={"work_done": "Late entry", "submit": True},
        headers=h,
    )
    assert (
        client.get("/api/execution/dprs/missing", params={"day": str(yesterday)}, headers=h).json()[
            "count"
        ]
        == 0
    )
    assert (
        client.put(
            f"/api/execution/sites/{s['id']}/dprs/{TODAY + timedelta(days=1)}", json={}, headers=h
        ).status_code
        == 422
    )


# --- attendance ----------------------------------------------------------------------------------


def test_attendance_double_booking_half_day_ot_and_wage_due(boss, masters):
    client, h = boss
    a, b = site(client, h, "Site A"), site(client, h, "Site B")
    w = worker(client, h, a["id"])
    sub = worker(
        client,
        h,
        a["id"],
        "Invented Suresh",
        type="subcontractor",
        subcontractor_id=masters["sub"],
        daily_wage="500",
    )
    d1, d2, d3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    r = mark(
        client,
        h,
        a["id"],
        d1,
        {"labour_id": w["id"], "status": "present", "ot_hours": "2"},
        {"labour_id": sub["id"], "status": "present"},
    )
    assert r.status_code == 200 and r.json()["counts"]["present"] == 2
    r = mark(client, h, b["id"], d1, {"labour_id": w["id"], "status": "present"})
    assert r.status_code == 422 and "already marked at" in r.json()["detail"]
    sheet = client.get(f"/api/execution/sites/{b['id']}/attendance/{d1}", headers=h).json()
    assert sheet["rows"] == []  # not posted to B
    mark(client, h, a["id"], d2, {"labour_id": w["id"], "status": "half_day"})
    mark(client, h, a["id"], d3, {"labour_id": w["id"], "status": "absent"})
    assert (
        mark(
            client, h, a["id"], d3, {"labour_id": w["id"], "status": "absent", "ot_hours": "1"}
        ).status_code
        == 422
    )

    roll = client.get(
        "/api/execution/muster", params={"month": "2026-09", "site_id": a["id"]}, headers=h
    ).json()
    row = next(r for r in roll["rows"] if r["labour_id"] == w["id"])
    assert D(row["days"]) == D("1.5") and row["half_days"] == 1 and row["absent"] == 1
    assert D(row["ot_hours"]) == 2
    assert D(row["wage_due"]) == D("1050.00")  # 600 + 0.5 x 600 + 2 h x 75
    assert D(roll["wage_due"]) == D("1550.00")  # + the subcontractor's worker, 500
    x = client.get("/api/execution/muster/export", params={"month": "2026-09"}, headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    # a later wage change does not rewrite the past
    client.put(
        f"/api/execution/labour/{w['id']}",
        json={"name": w["name"], "site_id": a["id"], "daily_wage": "900"},
        headers=h,
    )
    roll = client.get(
        "/api/execution/muster", params={"month": "2026-09", "labour_id": w["id"]}, headers=h
    ).json()
    assert D(roll["wage_due"]) == D("1050.00")
    # staff check in / out
    assert (
        client.post(f"/api/execution/sites/{a['id']}/check-in", json={}, headers=h).status_code
        == 201
    )
    assert (
        client.post(f"/api/execution/sites/{b['id']}/check-in", json={}, headers=h).status_code
        == 409
    )
    assert client.post("/api/execution/check-out", headers=h).json()["check_out_at"]


def test_aadhaar_only_last_4_is_stored_and_never_logged(boss, db):
    client, h = boss
    s = site(client, h)
    w = worker(client, h, s["id"], aadhaar="1234 5678 9012")
    assert w["aadhaar_last4"] == "9012"
    row = db.get(Labour, w["id"])
    assert row.aadhaar_last4 == "9012"
    logged = json.dumps([a.after for a in db.scalars(select(AuditLog))], default=str)
    assert "9012" in logged and "123456789012" not in logged and "5678" not in logged
    r = client.post(
        "/api/execution/labour", json={"name": "X", "site_id": s["id"], "aadhaar": "12"}, headers=h
    )
    assert r.status_code == 422
    assert (
        db.execute(text("SELECT count(*) FROM labour WHERE length(aadhaar_last4) <> 4")).scalar()
        == 0
    )


# --- work orders ---------------------------------------------------------------------------------


def test_work_order_amounts_over_measurement_and_billable(boss, login_as, masters):
    client, h = boss
    s = site(client, h)
    r = client.post(
        "/api/execution/work-orders",
        json={
            "site_id": s["id"],
            "subcontractor_id": masters["sub"],
            "retention_percent": "5",
            "lines": [
                {"description": "PU coating on terrace", "unit": "sqm", "qty": "100", "rate": "50"},
                {"description": "Coving at the parapet", "unit": "rmt", "qty": "20", "rate": "120"},
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    wo = r.json()
    assert wo["code"] == f"WO-{TODAY.year}-0001"
    assert D(wo["amount"]) == 7400 and D(wo["retention"]) == 370
    assert D(wo["tds_percent"]) == 1 and D(wo["tds"]) == 74  # PAN of an individual: 1 %
    line = wo["lines"][0]["id"]
    url = f"/api/execution/work-orders/{wo['id']}/lines/{line}/measurements"
    assert client.post(url, json={"qty": "10"}, headers=h).status_code == 403  # not approved yet
    assert (
        client.post(f"/api/execution/work-orders/{wo['id']}/approve", headers=h).json()["status"]
        == "approved"
    )

    wo = client.post(url, json={"qty": "60"}, headers=h).json()
    assert wo["status"] == "active" and wo["warning"] is None
    m1 = wo["lines"][0]["measurements"][0]["id"]
    assert D(wo["billable_to_date"]) == 0  # not verified yet
    wo = client.post(f"/api/execution/measurements/{m1}/verify", headers=h).json()
    assert D(wo["billable_to_date"]) == 3000
    wo = client.post(url, json={"qty": "50"}, headers=h).json()
    assert "needs approval" in wo["warning"] and wo["lines"][0]["over"]
    m2 = wo["lines"][0]["measurements"][1]
    assert m2["status"] == "pending_approval"
    assert (
        client.post(f"/api/execution/work-orders/{wo['id']}/complete", headers=h).status_code == 409
    )
    files = {"file": ("m.png", PNG, "image/png")}
    assert (
        client.post(
            f"/api/execution/measurements/{m2['id']}/photos", files=files, headers=h
        ).status_code
        == 201
    )
    wo = client.post(f"/api/execution/measurements/{m2['id']}/approve", headers=h).json()
    assert D(wo["billable_to_date"]) == 5500 and D(wo["retention_to_date"]) == 275
    assert (
        client.get(f"/api/execution/work-orders/{wo['id']}/pdf", headers=h).content[:4] == b"%PDF"
    )

    acc, ah = login_as("accounts", email="accounts@example.com")
    assert acc.get(f"/api/execution/work-orders/{wo['id']}", headers=ah).status_code == 200
    assert acc.post(url, json={"qty": "1"}, headers=ah).status_code == 403
    subs = acc.get("/api/execution/subcontractors", headers=ah).json()
    assert subs[0]["name"] == "Invented Applicators" and D(subs[0]["tds_percent"]) == 1


# --- inspections ---------------------------------------------------------------------------------


def test_required_items_and_hold_point_needs_a_passed_inspection(boss, db):
    client, h = boss
    s = site(client, h)
    task_id, cl = hold_point_task(db, s["id"])
    certify = f"/api/sites/{s['id']}/tasks/{task_id}/certify"
    r = client.post(certify, json={}, headers=h)
    assert r.status_code == 422 and "passed inspection" in r.json()["detail"]

    # a required item missing, then a required photo missing
    r = inspect(client, h, s["id"], cl, task_id, ponding_answers(cl)[1:], photo_files(cl))
    assert r.status_code == 422
    r = inspect(client, h, s["id"], cl, task_id, ponding_answers(cl))
    assert r.status_code == 422 and "photo" in r.json()["detail"]
    # a failed check: the result is fail and the hold point stays
    r = inspect(
        client, h, s["id"], cl, task_id, ponding_answers(cl, "fail"), photo_files(cl), result="pass"
    )
    assert r.status_code == 422
    r = inspect(client, h, s["id"], cl, task_id, ponding_answers(cl, "fail"), photo_files(cl))
    assert r.status_code == 201, r.text
    assert r.json()["result"] == "fail"
    assert client.post(certify, json={}, headers=h).status_code == 422

    sig = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
        "hQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    r = inspect(
        client,
        h,
        s["id"],
        cl,
        task_id,
        ponding_answers(cl),
        photo_files(cl),
        client_rep="Invented Client Rep",
        signature=sig,
        certify=True,
    )
    assert r.status_code == 201, r.text
    ins = r.json()
    assert ins["result"] == "pass" and ins["has_signature"] and ins["task_status"] == "certified"
    assert db.get(Task, task_id).status == "certified"
    assert (
        client.get(f"/api/execution/inspections/{ins['id']}/pdf", headers=h).content[:4] == b"%PDF"
    )

    # MOM with open points on the site overview
    r = client.post(
        "/api/execution/moms",
        json={
            "site_id": s["id"],
            "title": "Weekly review",
            "attendee_user_ids": [uid(db, "boss@example.com")],
            "attendee_others": ["Invented Client Engineer"],
            "points": [
                {
                    "text": "Clear the terrace",
                    "owner_name": "Client",
                    "due_date": str(TODAY - timedelta(days=1)),
                },
                {"text": "Share the test report", "owner_user_id": uid(db, "boss@example.com")},
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    mom = r.json()
    ov = client.get(f"/api/execution/sites/{s['id']}/overview", headers=h).json()
    assert len(ov["open_points"]) == 2 and ov["open_points"][0]["overdue"]
    client.patch(
        f"/api/execution/mom-points/{mom['points'][0]['id']}", json={"status": "done"}, headers=h
    )
    assert len(client.get(f"/api/execution/sites/{s['id']}/open-points", headers=h).json()) == 1
    assert client.get(f"/api/execution/moms/{mom['id']}/pdf", headers=h).content[:4] == b"%PDF"


# --- assets --------------------------------------------------------------------------------------


def test_asset_movement_location_and_no_double_issue(boss):
    client, h = boss
    a_site, b_site = site(client, h, "Site A"), site(client, h, "Site B")
    gd = godown(client, h)
    a = client.post(
        "/api/execution/assets",
        json={"name": "Invented mixer", "category": "machine", "rate_per_day": "1500"},
        headers=h,
    ).json()
    assert a["code"] == "AST-0001" and a["store_id"] == gd and a["status"] == "available"
    moved = client.post(
        f"/api/execution/assets/{a['id']}/move",
        data={"to_site_id": a_site["id"], "condition": "Good"},
        files={"photo": ("m.png", PNG, "image/png")},
        headers=h,
    )
    assert (
        moved.status_code == 201
        and moved.json()["status"] == "at_site"
        and moved.json()["site_id"] == a_site["id"]
    )
    r = client.post(
        f"/api/execution/assets/{a['id']}/move", data={"to_site_id": b_site["id"]}, headers=h
    )
    assert r.status_code == 409 and "return it" in r.json()["detail"]
    usage = {"asset_id": a["id"], "site_id": b_site["id"], "quantity": "2", "fuel_cost": "500"}
    assert client.post("/api/execution/equipment-usage", json=usage, headers=h).status_code == 422
    client.post(f"/api/execution/assets/{a['id']}/move", data={"to_store_id": gd}, headers=h)
    r = client.post(
        f"/api/execution/assets/{a['id']}/move", data={"to_site_id": b_site["id"]}, headers=h
    )
    assert r.json()["location"].startswith(b_site["code"])
    u = client.post("/api/execution/equipment-usage", json=usage, headers=h).json()
    assert D(u["amount"]) == 3500  # 2 days x 1,500 + fuel 500
    moves = client.get(f"/api/execution/assets/{a['id']}/movements", headers=h).json()
    assert len(moves) == 3 and moves[-1]["photo"]
    cost = client.get("/api/execution/equipment-cost", headers=h).json()
    assert [(c["site_code"], D(c["amount"])) for c in cost] == [(b_site["code"], 3500)]


# --- budget --------------------------------------------------------------------------------------


def test_budget_actuals_shortage_and_freight_follows_grns(boss, masters, db):
    client, h = boss
    s = site(client, h)
    st, gd = store_of(client, h, s["id"]), godown(client, h)
    pid = masters["product"]
    # material: issue 10 @ 50 at the site, plus a transfer shortage of 2 @ 50 charged to the site
    client.post(
        f"/api/material/stores/{st}/adjust",
        json={"product_id": pid, "qty": "100", "rate": "50", "kind": "opening", "note": "Opening"},
        headers=h,
    )
    client.post(
        f"/api/material/stores/{gd}/adjust",
        json={"product_id": pid, "qty": "20", "rate": "50", "kind": "opening", "note": "Opening"},
        headers=h,
    )
    client.post(
        "/api/material/issues",
        json={"site_id": s["id"], "lines": [{"product_id": pid, "qty": "10"}]},
        headers=h,
    )
    t = client.post(
        "/api/material/transfers",
        json={
            "from_store_id": gd,
            "to_store_id": st,
            "freight_amount": "300",
            "dispatch": True,
            "lines": [{"product_id": pid, "qty": "10"}],
        },
        headers=h,
    ).json()
    client.post(
        f"/api/material/transfers/{t['id']}/receive",
        json={
            "lines": [
                {"line_id": t["lines"][0]["id"], "qty_received": "8", "shortage_reason": "Spilt"}
            ]
        },
        headers=h,
    )
    ledger = client.get(
        f"/api/material/stores/{st}/ledger", params={"product_id": pid}, headers=h
    ).json()
    shortage = next(r for r in ledger if r["ref_type"] == "shortage")
    assert D(shortage["qty"]) == -2 and D(shortage["value"]) == -100

    # freight follows the GRNs (40 of 100 in = 40 % of the freight); a cancelled PO adds none
    def po(qty="100"):
        r = client.post(
            "/api/material/pos",
            json={
                "vendor_id": masters["vendor"],
                "store_id": st,
                "lines": [{"product_id": pid, "qty": qty, "rate": "50"}],
                "charges": [{"kind": "freight", "amount": "1000"}],
            },
            headers=h,
        )
        assert (
            client.post(f"/api/material/pos/{r.json()['id']}/submit", headers=h).json()["status"]
            == "approved"
        )
        return r.json()

    p = po()
    assert (
        client.get("/api/material/freight", params={"site_id": s["id"]}, headers=h).json()["total"]
        == 1
    )  # transfer only
    g = client.post(
        "/api/material/grns",
        json={
            "po_id": p["id"],
            "submit": True,
            "lines": [{"po_line_id": p["lines"][0]["id"], "received_qty": "40"}],
        },
        headers=h,
    ).json()
    client.post(f"/api/material/grns/{g['id']}/approve", headers=h)
    cancelled = po("10")
    client.post(
        f"/api/material/pos/{cancelled['id']}/cancel", json={"reason": "Not needed"}, headers=h
    )

    # labour (own only), subcontract (verified), equipment, other
    w = worker(client, h, s["id"])
    sw = worker(
        client, h, s["id"], "Invented Sub", type="subcontractor", subcontractor_id=masters["sub"]
    )
    mark(
        client,
        h,
        s["id"],
        TODAY,
        {"labour_id": w["id"], "status": "present"},
        {"labour_id": sw["id"], "status": "present"},
    )
    wo = client.post(
        "/api/execution/work-orders",
        json={
            "site_id": s["id"],
            "subcontractor_id": masters["sub"],
            "lines": [{"description": "Coating", "unit": "sqm", "qty": "100", "rate": "50"}],
        },
        headers=h,
    ).json()
    client.post(f"/api/execution/work-orders/{wo['id']}/approve", headers=h)
    wo = client.post(
        f"/api/execution/work-orders/{wo['id']}/lines/{wo['lines'][0]['id']}/measurements",
        json={"qty": "60"},
        headers=h,
    ).json()
    client.post(
        f"/api/execution/measurements/{wo['lines'][0]['measurements'][0]['id']}/verify", headers=h
    )
    a = client.post(
        "/api/execution/assets", json={"name": "Invented mixer", "rate_per_day": "1500"}, headers=h
    ).json()
    client.post(f"/api/execution/assets/{a['id']}/move", data={"to_site_id": s["id"]}, headers=h)
    client.post(
        "/api/execution/equipment-usage",
        json={"asset_id": a["id"], "site_id": s["id"], "quantity": "2", "fuel_cost": "500"},
        headers=h,
    )
    client.post(
        f"/api/execution/sites/{s['id']}/costs",
        json={"amount": "250", "description": "Site security"},
        headers=h,
    )
    r = client.put(
        f"/api/execution/sites/{s['id']}/budget",
        json={"heads": {"material": "650", "labour": "5000"}},
        headers=h,
    )
    rows = {row["head"]: row for row in r.json()["rows"]}
    assert D(rows["material"]["actual"]) == 600  # 500 issued + 100 shortage
    assert D(rows["labour"]["actual"]) == 600  # own worker only
    assert D(rows["subcontract"]["actual"]) == 3000
    assert D(rows["equipment"]["actual"]) == 3500
    assert D(rows["freight"]["actual"]) == 700  # 400 (40 % of 1,000) + 300 transfer
    assert D(rows["other"]["actual"]) == 250
    assert rows["material"]["warn"] and D(rows["material"]["percent_used"]) == D("92.3")
    assert not rows["labour"]["warn"] and D(rows["labour"]["variance"]) == 4400


# --- permissions ---------------------------------------------------------------------------------


def test_scopes_read_only_accounts_hidden_cost_and_client(boss, login_as, make_user, db):
    client, h = boss
    mine, other = site(client, h, "Mine"), site(client, h, "Other")
    make_user("sup@example.com", "site_supervisor")
    client.put(
        f"/api/sites/{mine['id']}/members",
        json={"members": [{"user_id": uid(db, "sup@example.com"), "role_on_site": "supervisor"}]},
        headers=h,
    )
    sup = login(client, "sup@example.com")
    client.put(
        f"/api/execution/sites/{other['id']}/dprs/{TODAY}",
        json={"work_done": "x", "submit": True},
        headers=h,
    )
    r = client.put(
        f"/api/execution/sites/{mine['id']}/dprs/{TODAY}",
        json={"work_done": "Mine", "submit": True},
        headers=sup,
    )
    assert r.status_code == 200
    assert (
        client.put(
            f"/api/execution/sites/{other['id']}/dprs/{TODAY}", json={}, headers=sup
        ).status_code
        == 404
    )
    assert [d["site_id"] for d in client.get("/api/execution/dprs", headers=sup).json()] == [
        mine["id"]
    ]
    assert worker(client, sup, mine["id"])["site_id"] == mine["id"]
    assert (
        client.post(
            "/api/execution/labour", json={"name": "X", "site_id": other["id"]}, headers=sup
        ).status_code
        == 404
    )
    assert client.get("/api/execution/work-orders", headers=sup).status_code == 403
    assert client.get(f"/api/execution/sites/{mine['id']}/budget", headers=sup).status_code == 403

    # accounts: read-only
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert acc.get(f"/api/execution/sites/{mine['id']}/budget", headers=ah).status_code == 200
    assert (
        acc.put(
            f"/api/execution/sites/{mine['id']}/budget", json={"heads": {"other": "1"}}, headers=ah
        ).status_code
        == 403
    )
    assert (
        acc.put(f"/api/execution/sites/{mine['id']}/dprs/{TODAY}", json={}, headers=ah).status_code
        == 403
    )
    assert acc.get("/api/execution/dprs", headers=ah).status_code == 200

    # budget.view without tender.margin: the tender-derived (cost) budget is hidden
    db.add(SiteBudget(site_id=mine["id"], head="material", amount=12345, source="tender"))
    role = Role(code="site_auditor", name="Site auditor", is_system=False)
    db.add(role)
    db.flush()
    db.add_all(
        [
            RolePermission(role_id=role.id, permission_code=c, scope="all")
            for c in ("budget.view", "site.view")
        ]
    )
    db.commit()
    assert db.get(Permission, "budget.view") is not None
    make_user("auditor@example.com", "site_auditor")
    aud = login(client, "auditor@example.com")
    rows = {
        r["head"]: r
        for r in client.get(f"/api/execution/sites/{mine['id']}/budget", headers=aud).json()["rows"]
    }
    assert (
        rows["material"]["hidden"]
        and rows["material"]["budget"] is None
        and rows["material"]["variance"] is None
    )
    rows = {
        r["head"]: r
        for r in client.get(f"/api/execution/sites/{mine['id']}/budget", headers=h).json()["rows"]
    }
    assert D(rows["material"]["budget"]) == 12345

    cl, ch = login_as("client", email="customer@example.com")
    for path in (
        "dprs",
        "labour",
        "work-orders",
        "inspections",
        "moms",
        "assets",
        "equipment-usage",
        "muster?month=2026-09",
        f"sites/{mine['id']}/budget",
        "subcontractors",
    ):
        assert cl.get(f"/api/execution/{path}", headers=ch).status_code == 403, path
