# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""The close-out screens on invented data: Settings > Client roles, the measurement book's entry
form, the quality checklist's signs, the handover moved by our engineer, the material
reconciliation with the return to the godown, labour claims above the approved measurement, and
one page for a bill's story."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.closeout.models import LabourClaim
from app.main import app
from app.material import service as stock
from app.material.models import SiteIssue, SiteIssueLine, Store, Transfer
from app.models import AuditLog
from app.portal.models import Notification
from app.process.models import ProcessEvent
from app.sites.models import AreaScope, Site, StageTemplate, StageTemplateStep, Task
from app.team.models import Measurement
from tests.test_closeout import (  # noqa: F401  (fixtures)
    _client_login,
    _give_system,
    measured,
    portal_site,
)
from tests.test_finance import boss, invoiced, world  # noqa: F401  (fixtures)

D = Decimal


def _m(c, h, w, node, **body):
    r = c.post(f"/api/closeout/sites/{w['site']}/measurements", json={"description": "PU coating", "contract_line_id": w["pu"], "node_id": node, **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# --- Settings > Client roles ------------------------------------------------------------------------


def test_a_changed_client_role_default_applies_to_new_invites_and_is_audit_logged(boss, portal_site, db, login_as):
    c, h = boss
    w = portal_site
    before = _client_login(c, h, w["client"], [w["site"]], "acc-before@example.com", ["accounts"])
    r = c.get("/api/closeout/client-roles", headers=h).json()
    acc = next(x for x in r["roles"] if x["code"] == "accounts")
    assert acc["rights"] == acc["default_rights"] and "measurement.approve" not in acc["rights"]
    cb, hb = login_as("billing", email="billing-roles@example.com")
    assert cb.put("/api/closeout/client-roles/accounts", json={"rights": acc["rights"]}, headers=hb).status_code == 403  # office_admin and director only
    co, ho = login_as("office_admin", email="oa-roles@example.com")
    r = co.put("/api/closeout/client-roles/accounts", json={"rights": [*acc["rights"], "measurement.approve"]}, headers=ho)
    assert r.status_code == 200 and "measurement.approve" in next(x for x in r.json()["roles"] if x["code"] == "accounts")["rights"]
    log = db.scalars(select(AuditLog).where(AuditLog.action == "client_role.update").order_by(AuditLog.id.desc())).first()
    assert log is not None and "measurement.approve" in str(log.after) and "measurement.approve" not in str(log.before)
    after = _client_login(c, h, w["client"], [w["site"]], "acc-after@example.com", ["accounts"])
    cc = TestClient(app)
    assert cc.get(f"/api/portal/sites/{w['site']}/measurements", headers=after).status_code == 200  # the new invite has it
    assert cc.get(f"/api/portal/sites/{w['site']}/measurements", headers=before).status_code == 403  # the earlier one kept its rights
    r = co.post("/api/closeout/client-roles/accounts/reset", headers=ho)
    assert next(x for x in r.json()["roles"] if x["code"] == "accounts")["rights"] == sorted(acc["default_rights"])
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "client_role.reset")) is not None


# --- the measurement book's entry form -------------------------------------------------------------


def test_the_entry_form_gives_the_lines_unit_and_a_set_is_sent_with_photos(boss, measured, db):
    c, h = boss
    w = measured
    f = c.get(f"/api/closeout/sites/{w['site']}/measure-form", headers=h).json()
    pu = next(x for x in f["lines"] if x["id"] == w["pu"])
    assert pu["unit"] == "sqm" and "L x B" in pu["how"] and f["needs_approval"]
    assert {p["path"] for p in f["places"]} >= {"Tower A / Flat 101 / Toilet"}
    (f1, t1, b1), _ = w["flats"]
    a = _m(c, h, w, t1, length_m="7 ft", breadth_m="4 ft 11 in")
    assert a["shown"] == {"length_m": "7 ft = 2.134 m", "breadth_m": "4 ft 11 in = 1.499 m"} and a["status"] == "draft"
    r = c.post(f"/api/closeout/measurements/{a['id']}/photos", files={"file": ("toilet.jpg", b"\xff\xd8\xffinvented", "image/jpeg")}, headers=h)
    assert r.status_code == 200, r.text
    assert c.post(f"/api/closeout/sites/{w['site']}/measurement-sets", json={"ids": [a["id"]]}, headers=h).status_code == 200
    line = next(x for x in c.get(f"/api/closeout/sites/{w['site']}/measurements", headers=h).json()["lines"] if x["id"] == a["id"])
    assert line["status"] == "sent" and line["photos"] == 1 and line["set_id"]


def test_the_older_quick_entry_waits_for_the_client_on_a_site_that_needs_approval(boss, measured, db):
    c, h = boss
    w = measured
    r = c.post("/api/team/measurements", json={"site_id": w["site"], "contract_line_id": w["pu"], "qty": "5", "source": "laser"}, headers=h)
    assert r.status_code == 201
    assert db.scalars(select(Measurement).where(Measurement.site_id == w["site"]).order_by(Measurement.id.desc())).first().status == "draft"


# --- the quality checklist --------------------------------------------------------------------------


def _stages(db, w, node):
    tpl = StageTemplate(name="Invented quality template")
    db.add(tpl)
    db.flush()
    steps = [StageTemplateStep(template_id=tpl.id, sort_order=i, name=n, weight_percent=D(50)) for i, n in enumerate(("Primer", "Coat"))]
    db.add_all(steps)
    db.flush()
    sc = AreaScope(site_id=w["site"], node_id=node, stage_template_id=tpl.id, qty=D(10), unit="sqm")
    db.add(sc)
    db.flush()
    tasks = [Task(site_id=w["site"], node_id=node, area_scope_id=sc.id, step_id=s.id, name=s.name, sort_order=i) for i, s in enumerate(steps)]
    db.add_all(tasks)
    db.commit()
    return tasks


def test_the_quality_checklist_our_sign_with_dates_and_the_clients_sign_recorded_needs_the_copy(boss, measured, db):
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    tasks = _stages(db, w, t1)
    r = c.post(f"/api/closeout/tasks/{tasks[0].id}/quality-sign", json={"started_on": "2026-09-02", "ended_on": "2026-09-01"}, headers=h)
    assert r.status_code == 422  # ends before it started
    r = c.post(f"/api/closeout/tasks/{tasks[0].id}/quality-sign", json={"started_on": "2026-09-02", "ended_on": "2026-09-03"}, headers=h)
    assert r.status_code == 200, r.text
    st = r.json()["stages"][0]
    assert (st["started_on"], st["ended_on"]) == ("2026-09-02", "2026-09-03") and st["our_sign"]
    iid = st["inspection_id"]
    r = c.post(f"/api/closeout/inspections/{iid}/client-sign-record", data={"signed_name": "Invented Client Engineer"}, headers=h)
    assert r.status_code == 422  # the signed copy is needed
    r = c.post(f"/api/closeout/inspections/{iid}/client-sign-record", data={"signed_name": "Invented Client Engineer"}, files={"file": ("sign.pdf", b"%PDF-1.4 invented", "application/pdf")}, headers=h)
    assert r.status_code == 200 and r.json()["recorded_by_staff"]
    q = c.get(f"/api/closeout/sites/{w['site']}/quality", headers=h).json()
    area = next(a for a in q["areas"] if a["node_id"] == t1)
    assert area["path"] == "Tower A / Flat 101 / Toilet" and area["stages"][0]["client_sign"] == "Invented Client Engineer" and area["stages"][0]["recorded_by_staff"]
    assert c.post(f"/api/closeout/tasks/{tasks[0].id}/quality-sign", json={}, headers=h).status_code == 409  # signed by the client: locked


# --- the handover moved by our site engineer ------------------------------------------------------------


def test_the_handover_moved_with_a_reason_and_the_client_sees_it(boss, measured, db):
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    hh = _client_login(c, h, w["client"], [w["site"]], "planning-ho@example.com", ["planning"])
    cc = TestClient(app)
    assert cc.put(f"/api/portal/sites/{w['site']}/nodes/{f1}/handover-promise", json={"promised_on": "2026-11-10"}, headers=hh).status_code == 200
    r = c.post(f"/api/closeout/sites/{w['site']}/nodes/{f1}/handover-move", json={"promised_on": "2026-11-20", "reason": "Plumbing chases still open in the toilet"}, headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["client_promised_on"], r.json()["moved_to"], r.json()["moved_because"]) == ("2026-11-10", "2026-11-20", "Plumbing chases still open in the toilet")
    row = next(x for x in cc.get(f"/api/portal/sites/{w['site']}/handover", headers=hh).json() if x["node_id"] == f1)
    assert row["promised_on"] == "2026-11-20" and row["moved_because"] == "Plumbing chases still open in the toilet" and row["client_promised_on"] == "2026-11-10"
    uid = db.scalar(select(Notification.user_id).where(Notification.kind == "handover_moved"))
    assert uid is not None  # the client's in-app notice (never an email)


# --- material reconciliation ----------------------------------------------------------------------------


def test_reconciliation_issued_needed_excess_and_the_return_to_godown_makes_a_transfer(boss, measured, db):
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    _give_system(db, w)  # PU coating: 1.5 kg of Invented PU coat per sqm
    a = _m(c, h, w, t1, length_m="4", breadth_m="2.5")  # 10 sqm -> 15 kg needed
    db.get(Measurement, a["id"]).status = "approved"
    from app.masters.models import Product

    p = db.scalar(select(Product).where(Product.name == "Invented PU coat"))
    site = db.get(Site, w["site"])
    store = stock.site_store(db, site)
    stock.post(db, store_id=store.id, product=p, qty=D(20), rate=D(300), ref_type="opening", ref_id=None, user_id=None)
    iss = SiteIssue(code="ISS-2026-9901", kind="issue", store_id=store.id, site_id=site.id, issued_on=date(2026, 10, 1))
    db.add(iss)
    db.flush()
    stock.take_out(db, store=store, product=p, qty=D(18), ref_type="issue", ref_id=iss.id, user_id=None)
    iss.lines.append(SiteIssueLine(product_id=p.id, product=p, qty=D(18), rate=D(300), value=D(5400)))
    db.commit()
    r = c.get(f"/api/closeout/sites/{w['site']}/reconciliation", headers=h).json()
    row = next(x for x in r["rows"] if x["product_id"] == p.id)
    assert (D(str(row["issued"])), D(str(row["needed"])), D(str(row["difference"])), row["state"]) == (D(18), D(15), D(3), "excess")
    assert c.post(f"/api/closeout/sites/{w['site']}/reconciliation/return", json={"product_id": p.id, "qty": "4"}, headers=h).status_code == 422  # more than the excess
    r = c.post(f"/api/closeout/sites/{w['site']}/reconciliation/return", json={"product_id": p.id, "qty": "3"}, headers=h)
    assert r.status_code == 201, r.text
    t = db.scalar(select(Transfer).where(Transfer.code == r.json()["transfer"]))
    assert t.status == "dispatched" and db.get(Store, t.to_store_id).kind == "godown" and D(t.lines[0].qty_sent) == D(3)
    row = next(x for x in r.json()["rows"] if x["product_id"] == p.id)
    assert (D(str(row["issued"])), D(str(row["returned"])), row["state"]) == (D(15), D(3), "even")
    x = c.get(f"/api/closeout/sites/{w['site']}/reconciliation.xlsx", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"


# --- labour claims ------------------------------------------------------------------------------------------


def test_a_labour_claim_paid_above_the_approved_quantity_needs_the_director(boss, measured, db, login_as):
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    a = _m(c, h, w, t1, length_m="4", breadth_m="2.5")
    db.get(Measurement, a["id"]).status = "approved"
    db.commit()
    cl = c.post(f"/api/closeout/sites/{w['site']}/labour-claims", json={"contractor": "Invented Labour Co", "node_id": t1, "contract_line_id": w["pu"], "claimed_qty": "11", "unit": "sqm"}, headers=h).json()
    claim = cl[-1]
    assert (D(str(claim["approved"])), D(str(claim["excess_claim"])), claim["status"]) == (D(10), D(1), "open")
    cb, hb = login_as("billing", email="billing-claims@example.com")
    assert cb.post(f"/api/closeout/labour-claims/{claim['id']}/decide", json={"decision": "claimed"}, headers=hb).status_code == 422  # the reason
    r = cb.post(f"/api/closeout/labour-claims/{claim['id']}/decide", json={"decision": "claimed", "reason": "the toilet's skirting was not in the book"}, headers=hb)
    assert r.status_code == 200 and r.json()["status"] == "director"
    assert db.scalar(select(ProcessEvent).where(ProcessEvent.type == "labour_claim_above")) is not None
    assert cb.post(f"/api/closeout/labour-claims/{claim['id']}/director", json={"approve": True, "reason": "ok"}, headers=hb).status_code == 403
    cd, hd = login_as("director", email="director-claims@example.com")
    r = cd.post(f"/api/closeout/labour-claims/{claim['id']}/director", json={"approve": True, "reason": "Measured again on site: 11 sqm"}, headers=hd)
    assert r.status_code == 200 and D(str(r.json()["pays"])) == D(11) and r.json()["status"] == "decided" and r.json()["director"]
    assert cb.post(f"/api/closeout/labour-claims/{claim['id']}/decide", json={"decision": "approved"}, headers=hb).status_code == 409  # decided: locked
    second = c.post(f"/api/closeout/sites/{w['site']}/labour-claims", json={"contractor": "Invented Labour Co", "node_id": t1, "contract_line_id": w["pu"], "claimed_qty": "12", "unit": "sqm"}, headers=h).json()[-1]
    r = cb.post(f"/api/closeout/labour-claims/{second['id']}/decide", json={"decision": "approved"}, headers=hb)
    assert D(str(r.json()["pays"])) == D(10) and r.json()["status"] == "decided"  # the approved quantity, no director
    assert db.get(LabourClaim, second["id"]).decision == "approved"


# --- one place for a bill's story -----------------------------------------------------------------------------


def test_the_bill_page_has_quantities_steps_and_payment(boss, portal_site, db):
    c, h = boss
    w = portal_site
    k, ra, inv = invoiced(c, h, w, on="2026-10-07")
    assert c.post(f"/api/closeout/bills/{ra['id']}/steps", data={"step": "prepared", "on_date": "2026-10-01"}, headers=h).status_code == 200
    s = c.get(f"/api/closeout/bills/{ra['id']}/story", headers=h).json()
    assert s["bill"]["code"] == ra["code"] and s["bill"]["at"] == "Prepared"
    pu = next(x for x in s["quantities"]["lines"] if x["description"] == "PU coating")
    assert D(str(pu["billed_qty"])) == D(70) and D(str(pu["certified_qty"])) == D(65) and D(str(pu["difference"])) == D(-5)
    assert s["quantities"]["certified"] is not None and D(str(s["quantities"]["difference"])) < 0
    assert s["payment"]["invoice"] == inv["number"] and D(str(s["payment"]["outstanding"])) > 0 and s["payment"]["receipts"] == []
