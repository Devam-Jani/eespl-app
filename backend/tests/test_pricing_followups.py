# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Pricing follow-ups (Prompt 38b, invented data): labour in a system's own unit (₹ per rmt, nos,
cum), "if required" lines of a won order kept out of the contract value and shown under it, a price
per pack kept per the base unit to 4 decimals, and old per-bag prices converted in the margin check
and the survey PDF."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.cli import price_units
from app.costing.models import RateGroup, RateGroupProduct, RateWorking
from app.estimate import margin
from app.estimate.models import Coverage
from app.finance.models import ClientContract
from app.masters.models import Product, ProductPrice
from app.survey import pdf as survey_pdf
from app.tenders.models import BoqLine, Tender
from tests.test_pricing_quotations import _line, _put, boss, lb, media  # noqa: F401  (fixtures)
from tests.test_quotations import lib, new_quotation  # noqa: F401  (fixtures)


def D(x) -> Decimal:
    return Decimal(str(x))


# --- 1. labour in the system's own unit ------------------------------------------------------------


def _system(c, h, unit, labour, labour_unit, code):
    return c.post("/api/systems", json={"code": code, "name": f"Invented {code}", "unit": unit, "labour_rate": labour,
                                        "labour_unit": labour_unit, "default_margin_percent": "0"}, headers=h)  # fmt: skip


def test_labour_per_rmt_on_a_coving_system_and_per_sqft_refused(boss):
    c, h = boss
    r = _system(c, h, "rmt", "40", "rmt", "T38B-COV")
    assert r.status_code == 201, r.text
    cov_id = r.json()["id"]
    b = c.get(f"/api/systems/{cov_id}/rate", headers=h).json()
    assert b["labour_unit"] == "rmt" and D(b["labour_per_unit"]) == 40 and D(b["rate"]) == 40
    for unit in ("nos", "cum"):  # pipe outlets, a cum of screed
        r = _system(c, h, unit, "40", unit, f"T38B-{unit}")
        assert r.status_code == 201, r.text
    r = _system(c, h, "rmt", "40", "sqft", "T38B-BAD")
    assert r.status_code == 422 and "labour" in r.text
    r = _system(c, h, "rmt", "40", "nos", "T38B-BAD2")  # another unit than the system's: refused too
    assert r.status_code == 422
    sid = _system(c, h, "sqm", "40", "sqft", "T38B-SQM").json()["id"]  # sqm and sq ft still convert
    assert D(c.get(f"/api/systems/{sid}/rate", headers=h).json()["labour_per_unit"]) == D(40) * D("10.7639")
    # the system's unit changed away from its labour's: refused while it has labour
    assert c.patch(f"/api/systems/{cov_id}", json={"unit": "nos"}, headers=h).status_code == 422
    zero = _system(c, h, "rmt", "0", "rmt", "T38B-ZERO").json()["id"]  # no labour: the unit changes freely
    r = c.patch(f"/api/systems/{zero}", json={"unit": "nos"}, headers=h)
    assert r.status_code == 200, r.text


# --- 2. "if required" lines of a won order ---------------------------------------------------------


def test_if_required_lines_are_out_of_the_contract_value_and_shown_under_it(boss, lb, db):
    """Quotation total ₹1,35,000 + an if-required line of ₹4,000: contract value ₹1,35,000, the
    ₹4,000 shown separately (billed on measurement)."""
    c, h = boss
    q = new_quotation(c, h, lb)
    for oid, rate, qty in (
        (lb["l_sys"], "1000", "100"),  # option 1: 1,00,000
        (lb["l_fix"], "45", "1000"),  # option 2: not chosen
        (lb["l_lib"], "30", "1000"),  # both options: 30,000
        (lb["l_req"], "400", "10"),  # if required: 4,000
        (lb["l_tank"], "50", "100"),  # tank: 5,000
    ):
        r = _put(c, h, q, _line(q, oid), {"rate": rate, "qty": qty})
        assert r.status_code == 200, r.text
    assert D(r.json()["total"]) == D("135000.00")
    terrace = q["items"][0]
    r = c.post(f"/api/quotations/{q['id']}/status", json={"status": "won", "choices": {str(terrace["id"]): "1"}}, headers=h)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    tender = db.get(Tender, res["tender_id"])
    req = db.scalar(select(BoqLine).where(BoqLine.tender_id == tender.id, BoqLine.description.contains("Pressure grouting")))
    assert req.if_required and D(req.qty) == 10  # still copied, with its qty
    boq = c.get(f"/api/tenders/{tender.id}/boq", headers=h).json()
    assert D(boq["totals"]["subtotal"]) == D("135000.00") and D(boq["totals"]["if_required_amount"]) == D("4000.00")
    r = c.post(f"/api/finance/sites/{res['site_id']}/contract", json={"retention_percent": "5"}, headers=h)
    assert r.status_code == 201, r.text
    k = r.json()
    assert D(k["contract_value"]) == D("135000.00") and D(k["if_required_value"]) == D("4000.00")
    assert any(ln["if_required"] and "Pressure grouting" in ln["description"] for ln in k["lines"])  # billed on measurement
    assert D(db.get(ClientContract, k["id"]).contract_value) == D("135000.00")


# --- 3. a price per pack: 4 decimals per the base unit ----------------------------------------------


def test_a_price_per_bag_is_kept_to_4_decimals_per_kg(boss, db):
    """₹2,500 per 30 kg bag = ₹83.3333/kg (not ₹83.33); 30 bags' worth still costs ₹2,500 × 30."""
    c, h = boss
    p = Product(code="T38B-BAG", name="Invented repair mortar", unit="kg", pack_size=30, pack_unit="bag")
    db.add(p)
    db.commit()
    r = c.post(f"/api/prices/products/{p.id}", json={"rate": "2500", "unit": "bag"}, headers=h)
    assert r.status_code == 201, r.text
    assert D(r.json()["rate"]) == D("83.3333")
    row = db.get(ProductPrice, r.json()["id"])
    db.refresh(row)
    assert row.purchase_rate == D("83.3333")
    r = c.post(f"/api/prices/products/{p.id}/freight", json={"per_unit": "100", "unit": "bag"}, headers=h)
    assert r.status_code == 201 and D(r.json()["per_unit"]) == D("3.3333")
    from app.costing import prices  # noqa: PLC0415

    kept = prices.record_price(db, p.id, D("2500"), source="po", unit="bag", ref="PO-INV-38B")
    assert kept.purchase_rate == D("83.3333")


# --- 4. old per-bag prices in the margin check and the survey PDF ---------------------------------


def _old_bag_price(db, name, unit="kg", pack=None, price_unit="bag", rate="1000"):
    p = Product(code=f"T38B-{name.split()[-1]}-{name.split()[-2]}", name=name, unit=unit, pack_size=pack, pack_unit="bag" if pack else None)
    db.add(p)
    db.flush()
    db.add(ProductPrice(product_id=p.id, purchase_rate=D(rate), unit=price_unit, effective_from=date(2026, 1, 1), source="manual"))
    db.flush()
    return p


def test_old_per_bag_prices_are_converted_in_the_margin_check_and_survey_pdf(db):
    grout = _old_bag_price(db, "Invented old grout", pack=20)  # ₹1,000 per 20 kg bag = ₹50/kg
    sealant = _old_bag_price(db, "Invented old sealant", unit="ltr", price_unit="drum", rate="700")
    t = Tender(code="T-2026-38B1", name="Invented old prices", status="draft")
    db.add(t)
    db.flush()
    w = RateWorking(tender_id=t.id, rev_no=0)
    db.add(w)
    db.flush()
    g = RateGroup(working_id=w.id, name="Invented grouting")
    db.add(g)
    db.flush()
    for k, p in enumerate((grout, sealant)):
        db.add(Coverage(product_id=p.id, value=D(2), unit="kg/sqm", source="tds"))
        db.add(RateGroupProduct(group_id=g.id, product_id=p.id, sort_order=k))
    db.flush()
    db.refresh(g)
    m = margin.material_sqm(db, g, set())
    assert [(r["product"], r["price"]) for r in m["rows"]] == [("Invented old grout", D(50))]
    assert m["total"] == D("100.00")  # 2 kg × ₹50, not 2 × ₹1,000
    assert m["not_converted"] == ["Invented old sealant"]
    rates = survey_pdf.rates_of(db, [grout.id, sealant.id])
    assert rates == {grout.id: D(50), sealant.id: survey_pdf.NOT_CONVERTED}
    assert survey_pdf.NOT_CONVERTED == "price unit not converted"


def test_price_units_lists_rows_kept_in_another_unit(db):
    _old_bag_price(db, "Invented count grout", pack=20)
    _old_bag_price(db, "Invented count sealant", unit="ltr", price_unit="drum", rate="700")
    ok = Product(code="T38B-OK", name="Invented plain", unit="kg")
    db.add(ok)
    db.flush()
    db.add(ProductPrice(product_id=ok.id, purchase_rate=D(5), unit="kg", effective_from=date(2026, 1, 1), source="manual"))
    db.flush()
    rows = price_units.find(db)
    assert {(r.product, r.unit, r.convertible) for r in rows} == {("Invented count grout", "bag", True), ("Invented count sealant", "drum", False)}
    assert "2 price row(s)" in price_units.report(rows)
