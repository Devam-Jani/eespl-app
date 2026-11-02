# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Bug sweep group D (billing, client work orders): a cancelled RA bill gives back its measurements
and its "ready to bill" items, a client work order is entered against a won quotation (by sales,
for their own quotation) and its terms typed in, labour claims and their photos are entered, and
the guarantee register's export stays with closeout.billing."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.finance.models import RaBill
from app.models import User
from app.quotations.models import Quotation
from app.sitecontrol.models import ReadyToBill
from app.sites.models import AreaScope
from app.team.models import Measurement
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)

D = Decimal


def _uid(db, email):
    return db.scalar(select(User.id).where(User.email == email))


def _quotation(db, code, status, salesperson_id=None, site_id=None):
    q = Quotation(code=code, revision=0, is_latest=True, client_firm="Invented Builders", project="Invented tower", quote_date=date(2026, 10, 1),
                  status=status, salesperson_id=salesperson_id, site_id=site_id)  # fmt: skip
    db.add(q)
    db.commit()
    return q


def test_cancel_bill_releases_its_measurements_and_reopens_its_ready_to_bill_items(boss, world, db):
    c, h = boss
    k = contract(c, h, world)
    pu = next(ln for ln in k["lines"] if ln["description"] == "PU coating")
    sc = db.get(AreaScope, world["scopes"][1])
    db.add(
        ReadyToBill(
            site_id=world["site"],
            node_id=sc.node_id,
            area_scope_id=sc.id,
            contract_line_id=pu["id"],
            qty=D("40"),
            unit="sqm",
        )
    )
    db.commit()
    r = c.post("/api/sitecontrol/ready-to-bill/raise", json={"site_id": world["site"]}, headers=h)
    assert r.status_code == 200, r.text
    rid = r.json()["ra_bill_id"]
    db.expire_all()
    taken = list(db.scalars(select(Measurement).where(Measurement.ra_bill_id == rid)))
    assert taken  # the approved measurements of the line are stamped with the draft
    item = db.scalar(select(ReadyToBill).where(ReadyToBill.site_id == world["site"]))
    assert item.status == "billed" and item.ra_bill_id == rid
    r = c.post(f"/api/finance/ra-bills/{rid}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    db.expire_all()
    assert not db.scalar(select(Measurement.id).where(Measurement.ra_bill_id == rid))
    item = db.get(ReadyToBill, item.id)
    assert item.status == "open" and item.ra_bill_id is None and item.billed_at is None
    # the checklist no longer says "billed in" the cancelled bill
    book = c.get(f"/api/closeout/sites/{world['site']}/measurements", headers=h).json()
    assert all(m["billed_in"] is None for m in book["lines"])
    # and the next bill takes those measurements as its own
    r = c.post("/api/sitecontrol/ready-to-bill/raise", json={"site_id": world["site"]}, headers=h)
    assert r.status_code == 200, r.text
    new = r.json()["ra_bill_id"]
    db.expire_all()
    assert new != rid and db.get(RaBill, new).status == "draft"
    assert {m.id for m in db.scalars(select(Measurement).where(Measurement.ra_bill_id == new))} == {
        m.id for m in taken
    }


def test_sales_enters_a_work_order_against_their_own_won_quotation_and_types_its_terms(
    boss, world, db, login_as
):
    cs, hs = login_as("sales", email="sales-d@example.com")
    me = _uid(db, "sales-d@example.com")
    won = _quotation(db, "QTN-2026-9801", "won", salesperson_id=me, site_id=world["site"])
    sent = _quotation(db, "QTN-2026-9802", "sent", salesperson_id=me)
    other = _quotation(db, "QTN-2026-9803", "won")  # not this salesperson's
    r = cs.post("/api/closeout/work-orders", json={"quotation_id": sent.id}, headers=hs)
    assert r.status_code == 422 and "won quotation" in r.json()["detail"]
    r = cs.post("/api/closeout/work-orders", json={"quotation_id": other.id}, headers=hs)
    assert r.status_code == 404
    r = cs.post(
        "/api/closeout/work-orders",
        json={"quotation_id": won.id, "client_ref": "WO/INV/117"},
        headers=hs,
    )
    assert r.status_code == 201, r.text
    wo = r.json()
    assert (
        wo["site_id"] == world["site"]
        and wo["quotation"]["code"] == "QTN-2026-9801"
        and not wo["locked"]
    )
    # the client's file, read at once
    r = cs.post(
        f"/api/closeout/work-orders/{wo['id']}/file",
        files={"file": ("wo.pdf", b"%PDF-1.4 invented", "application/pdf")},
        headers=hs,
    )
    assert (
        r.status_code == 200 and r.json()["read"]["lines"] == 0
    ), r.text  # an unreadable PDF is kept with nothing read, never a 500
    assert r.json()["file_name"] == "wo.pdf"
    # the structured terms, typed in
    body = {"payment_days": 45, "payment_basis": "certification", "retention_percent": "5", "advance_percent": None, "guarantee_years": 10,
            "time_limit_days": 120, "penalty": "0.5 % a week", "scope_on_us": ["material lifting and shifting"], "scope_on_client": ["water", "electricity"]}  # fmt: skip
    r = cs.put(f"/api/closeout/work-orders/{wo['id']}", json=body, headers=hs)
    assert r.status_code == 200, r.text
    t = r.json()["terms"]
    assert (
        t["payment_days"] == 45
        and t["payment_basis"] == "certification"
        and D(str(t["retention_percent"])) == D("5")
    )
    assert t["guarantee_years"] == 10 and t["scope_on_client"] == ["water", "electricity"]
    # it is in the salesperson's list; billing (wo.view, no wo.edit) cannot make one
    assert [x["id"] for x in cs.get("/api/closeout/work-orders", headers=hs).json()] == [wo["id"]]
    cb, hb = login_as("billing", email="billing-d@example.com")
    assert (
        cb.post("/api/closeout/work-orders", json={"quotation_id": won.id}, headers=hb).status_code
        == 403
    )


def test_billing_enters_a_labour_claim_and_its_photos(boss, world, db, login_as):
    c, h = boss
    contract(c, h, world)
    cb, hb = login_as("billing", email="billing-d2@example.com")
    r = cb.post(
        f"/api/closeout/sites/{world['site']}/labour-claims",
        json={
            "contractor": "Invented Labour Co",
            "claimed_qty": "12.5",
            "unit": "sqm",
            "period": "2026-10",
        },
        headers=hb,
    )
    assert r.status_code == 201, r.text
    cid = max(x["id"] for x in r.json())
    r = cb.post(
        f"/api/closeout/labour-claims/{cid}/photos",
        files={"file": ("claim.jpg", b"\xff\xd8\xff\xe0invented", "image/jpeg")},
        headers=hb,
    )
    assert r.status_code == 200 and r.json()["photos"] == 1, r.text
    got = cb.get(f"/api/closeout/sites/{world['site']}/labour-claims", headers=hb).json()
    assert got[0]["claim_photos"] == 1 and D(str(got[0]["claimed"])) == D("12.5")


def test_the_past_projects_export_is_for_closeout_billing_only(login_as):
    ca, ha = login_as("accounts", email="accounts-d@example.com")
    assert ca.get("/api/closeout/guarantees", headers=ha).status_code == 200
    assert (
        ca.get("/api/closeout/past-projects.xlsx", headers=ha).status_code == 403
    )  # so the page hides the buttons
    cb, hb = login_as("billing", email="billing-d3@example.com")
    assert cb.get("/api/closeout/past-projects.xlsx", headers=hb).status_code == 200
