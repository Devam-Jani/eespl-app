# ruff: noqa: E501
"""From the Prompt 33 review (Part 0 of the material estimate milestone): a renumbered bill keeps its old number (shown, searched); a slip line
with no work-order item becomes a variation the director approves, then billed with its sheet."""

from decimal import Decimal

from app.finance.models import RaBill
from app.measure import register
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_measure_billing import (
    pool,  # noqa: F401  (fixture: a site, its work order and contract)
)
from tests.test_slips_register import _slip

D = Decimal


def test_the_old_number_stays_with_a_renumbered_bill_and_finds_it(pool, db):  # noqa: F811
    c, h = pool["c"], pool["h"]
    s = _slip(pool)
    c.post(f"/api/measure/sheets/{s['id']}/slip-lines", json={"particulars": "Floor", "no": "1", "length": "10", "width": "10", "wo_line_id": pool["wl"]["1"]}, headers=h)
    c.post(f"/api/measure/sheets/{s['id']}/send", headers=h)
    b = c.post(f"/api/measure/sheets/{s['id']}/bill", json={"basis": "verbal", "verbal_by": "Client's site engineer", "verbal_on": "2026-05-23", "proforma_on": "2026-06-01"}, headers=h).json()
    bill = db.get(RaBill, b["id"])
    assert register.old_number("(4) R A  - 16  THE SITE 08.09.2026.xlsx") == 16 and register.old_number("RA 16") == 16 and register.old_number("Abstract") is None
    bill.old_no = "RA 16"
    db.commit()
    reg = c.get(f"/api/measure/sites/{pool['site'].id}/register", headers=h).json()
    row = next(x for x in reg["bills"] if x["id"] == bill.id)
    assert row["old_no"] == "RA 16" and row["was"] == "was RA 16 in the old files" and row["ra"] == bill.seq != 16
    found = c.get(f"/api/measure/sites/{pool['site'].id}/register", params={"q": "RA 16"}, headers=h).json()["bills"]
    assert [x["id"] for x in found] == [bill.id]  # by the old number
    assert [x["id"] for x in c.get(f"/api/measure/sites/{pool['site'].id}/register", params={"q": "RA 99"}, headers=h).json()["bills"]] == []
    hits = c.get("/api/search", params={"q": "RA 16"}, headers=h).json()["bills"]
    assert any(x["id"] == bill.id and "was RA 16 in the old files" in x["note"] for x in hits)
    assert c.get(f"/api/measure/bills/{bill.id}", headers=h).json()["old_no"] == "RA 16"


def test_a_variation_for_a_slip_line_is_approved_then_billed(pool, db, login_as):  # noqa: F811
    c, h = pool["c"], pool["h"]
    s = _slip(pool)
    out = c.post(f"/api/measure/sheets/{s['id']}/slip-lines", json={"particulars": "Swimming pool No. 1: gabda", "no": "6"}, headers=h).json()
    line = next(u for u in out["slip"]["unbilled"] if u["particulars"].endswith("gabda"))
    assert line["why"] == "not mapped to a work-order item" and line["variation"] is None
    # billing proposes; the line stays unbilled, waiting for the director
    bc, bh = login_as("billing", email="billing@example.com")
    from sqlalchemy import select

    from app.models import User
    from app.sites.models import SiteMember

    db.add(SiteMember(site_id=pool["site"].id, user_id=db.scalar(select(User.id).where(User.email == "billing@example.com")), role_on_site="office"))
    db.commit()
    r = bc.post(f"/api/measure/sheets/{s['id']}/slip-lines/{line['line_id']}/variation", json={"description": "Gabda (pool bottom pit) filling", "unit": "nos", "rate": "450"}, headers=bh)
    assert r.status_code == 201, r.text
    un = next(u for u in r.json()["slip"]["unbilled"] if u["line_id"] == line["line_id"])
    assert "waiting for the director" in un["why"] and un["variation"]["status"] == "proposed" and "₹450.00" in un["why"]
    assert bc.post(f"/api/measure/sheets/{s['id']}/slip-lines/{line['line_id']}/variation", json={"description": "again", "unit": "nos", "rate": "1"}, headers=bh).status_code == 422
    vid = un["variation"]["id"]
    assert bc.post(f"/api/measure/variations/{vid}/decide", json={"approve": True}, headers=bh).status_code == 403  # only the director
    work = c.get("/api/team/my-work", headers=h).json()
    assert any(i["source"] == "variation" for sec in work.get("sections", []) for i in sec.get("items", [])) or "variation" in str(work)
    d = c.post(f"/api/measure/variations/{vid}/decide", json={"approve": True}, headers=h)
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "approved" and "item V1" in d.json()["done"][0]
    sheet = c.get(f"/api/measure/sheets/{s['id']}", headers=h).json()
    assert not any(u["line_id"] == line["line_id"] for u in sheet["slip"]["unbilled"])  # billed now
    totals = {ln["item_no"]: D(ln["total"]) for ln in sheet["lines"] if ln["kind"] == "total"}
    assert totals["V1"] == 6
    c.post(f"/api/measure/sheets/{s['id']}/send", headers=h)
    b = c.post(f"/api/measure/sheets/{s['id']}/bill", json={"basis": "verbal", "verbal_by": "Client's site engineer", "verbal_on": "2026-05-23", "proforma_on": "2026-06-01"}, headers=h)
    assert b.status_code == 201, b.text
    bill = c.get(f"/api/measure/bills/{b.json()['id']}", headers=h).json()
    v1 = next(ln for ln in bill["lines"] if ln["item_no"] == "V1")
    assert D(v1["amount"]) == 2700 and bill["variations"][0]["item_no"] == "V1" and "for the client's agreement" in bill["variations"][0]["text"]


def test_a_variation_not_approved_needs_why_and_the_line_stays_unbilled(pool, db):  # noqa: F811
    c, h = pool["c"], pool["h"]
    s = _slip(pool)
    out = c.post(f"/api/measure/sheets/{s['id']}/slip-lines", json={"particulars": "Frame fitting", "no": "2"}, headers=h).json()
    lid = out["slip"]["unbilled"][0]["line_id"]
    vid = c.post(f"/api/measure/sheets/{s['id']}/slip-lines/{lid}/variation", json={"description": "Frame fitting", "unit": "nos", "rate": "300"}, headers=h).json()["slip"]["unbilled"][0]["variation"]["id"]
    assert c.post(f"/api/measure/variations/{vid}/decide", json={"approve": False}, headers=h).status_code == 422
    r = c.post(f"/api/measure/variations/{vid}/decide", json={"approve": False, "note": "Part of the main item's rate"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    un = c.get(f"/api/measure/sheets/{s['id']}", headers=h).json()["slip"]["unbilled"]
    assert un[0]["line_id"] == lid and "not approved (Part of the main item's rate)" in un[0]["why"]
