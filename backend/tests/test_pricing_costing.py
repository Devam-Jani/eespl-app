# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Prompt 38, the rate working and the costing: units (a sq ft system, a price per bag, labour per
sq ft on a system in rmt), the labour piece bill per job, the master freight on a new product,
free-issue material, the current price's order, and the low items (labour kept to 4 decimals,
step rates adding up, each product's own wastage, "no rate" in Excel, a 0 price warned).
Invented data only."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.costing import prices, working
from app.costing.models import RateGroup, RateWorking
from app.finance.models import ClientContract, ContractLine, RaBill, RaBillLine
from app.masters.models import Product, ProductPrice, System, SystemComponent, Vendor
from app.masters.rate import (
    SQFT_PER_SQM,
    MissingPriceError,
    build_rate,
    system_rate,
)
from app.tenders.models import BoqLine, BoqSection, Tender
from app.timefmt import ist_today
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)


def d(v) -> Decimal:
    return Decimal(str(v))


def cents(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


_seq = iter(range(1, 10_000))


def _tender(db) -> Tender:
    t = Tender(code=f"T-2026-38{next(_seq):02d}", name="Invented pricing check", status="draft")
    db.add(t)
    db.flush()
    return t


def _product(db, name, unit="kg", price=None, **kw) -> Product:
    p = Product(code=f"T38-{next(_seq)}", name=name, unit=unit, **kw)
    db.add(p)
    db.flush()
    if price is not None:
        db.add(
            ProductPrice(
                product_id=p.id,
                purchase_rate=d(price),
                effective_from=ist_today() - timedelta(days=10),
                source="manual",
            )
        )
        db.flush()
    return p


def _group(db, system=None, name="Invented main item") -> RateGroup:
    t = _tender(db)
    w = RateWorking(tender_id=t.id, rev_no=0, margin_basis="selling")
    db.add(w)
    db.flush()
    g = RateGroup(working_id=w.id, name=name, sort_order=1, system_id=system.id if system else None)
    db.add(g)
    db.flush()
    if system is not None:
        working.init_from_system(db, g)
        db.flush()
    return g


# --- Part 2.1: a system per sq ft is worked per sqm ------------------------------------------------


def test_a_sqft_system_is_converted_to_per_sqm_in_the_working(db):
    # 0.1 kg/sqft at ₹200/kg + ₹5/sqft prep = ₹269.10/sqm (it was ₹25.00: per sq ft figures as per sqm)
    p = _product(db, "Invented sqft coating", price="200")
    s = System(code="T38-SQFT", name="Invented sqft system", unit="sqft", surface_prep_per_unit=5,
               labour_rate=0, labour_unit="sqft", default_margin_percent=0)  # fmt: skip
    s.components = [
        SystemComponent(product_id=p.id, consumption_per_unit=d("0.1"), wastage_percent=0)
    ]
    db.add(s)
    db.flush()
    g = _group(db, s)
    out = working.work(db, g)
    assert out["errors"] == []
    assert d(out["cost_sqm"]) == d("269.10")
    assert d(g.products[0].consumption) == d("0.1") * SQFT_PER_SQM  # per sqm (kept to 4 decimals)
    assert d(g.surface_prep) == d("53.8195")  # ₹5 per sq ft × 10.7639


def test_a_working_refuses_a_system_in_another_unit(db):
    # per rmt is worked per rmt and rft since Prompt 38e (test_bom_import); per nos has no working
    p = _product(db, "Invented sleeve compound", price="100")
    s = System(
        code="T38-NOS", name="Invented sleeve system", unit="nos", labour_rate=0, labour_unit="sqm"
    )
    s.components = [SystemComponent(product_id=p.id, consumption_per_unit=d("0.5"))]
    db.add(s)
    db.flush()
    with pytest.raises(working.WorkingUnitError, match="per nos"):
        _group(db, s)


# --- Part 2.2: a price per bag is a price per kg ---------------------------------------------------


def test_a_price_per_bag_is_converted_to_the_base_unit(boss, db):
    # ₹2,500 per 25 kg pack at 1.2 kg/sqm = ₹120/sqm of material (it was ₹3,000: the bag price per kg)
    c, h = boss
    p = _product(db, "Invented tile adhesive", pack_size=25, pack_unit="bag")
    db.commit()
    r = c.post(f"/api/prices/products/{p.id}", json={"rate": "2500", "unit": "bag"}, headers=h)
    assert r.status_code == 201, r.text
    assert d(r.json()["rate"]) == 100 and r.json()["unit"] == "kg"
    r = c.post(f"/api/prices/products/{p.id}", json={"rate": "9000", "unit": "drum"}, headers=h)
    assert r.status_code == 422 and "drum" in r.json()["detail"]
    # freight entered per bag: the same
    r = c.post(
        f"/api/prices/products/{p.id}/freight", json={"per_unit": "50", "unit": "bag"}, headers=h
    )
    assert r.status_code == 201, r.text
    assert d(r.json()["per_unit"]) == 2
    r = c.post(
        f"/api/prices/products/{p.id}/freight", json={"per_unit": "50", "unit": "drum"}, headers=h
    )
    assert r.status_code == 422
    s = System(
        code="T38-BAG",
        name="Invented adhesive system",
        unit="sqm",
        labour_rate=0,
        labour_unit="sqm",
    )
    s.components = [
        SystemComponent(product_id=p.id, consumption_per_unit=d("1.2"), wastage_percent=0)
    ]
    db.add(s)
    db.flush()
    g = _group(db, s)
    g.products[0].freight_used = 0
    out = working.work(db, g)
    assert d(out["material_sqm"]) == d("120.00")
    assert system_rate(db, s, Decimal(0)).material_cost == 120  # the build-up too


def test_an_old_price_kept_per_bag_is_converted_when_used(db):
    p = _product(db, "Invented grout", pack_size=20, pack_unit="bag")
    db.add(
        ProductPrice(
            product_id=p.id,
            purchase_rate=d("1000"),
            unit="bag",
            effective_from=ist_today(),
            source="manual",
        )
    )
    s = System(
        code="T38-OLD", name="Invented grout system", unit="sqm", labour_rate=0, labour_unit="sqm"
    )
    s.components = [
        SystemComponent(product_id=p.id, consumption_per_unit=d("1"), wastage_percent=0)
    ]
    db.add(s)
    db.flush()
    assert system_rate(db, s, Decimal(0)).material_cost == 50
    g = _group(db, s)
    assert d(g.products[0].price) == 50
    q = _product(db, "Invented sealant", unit="ltr")
    db.add(
        ProductPrice(
            product_id=q.id,
            purchase_rate=d("700"),
            unit="drum",
            effective_from=ist_today(),
            source="manual",
        )
    )
    s2 = System(
        code="T38-OLD2",
        name="Invented sealant system",
        unit="sqm",
        labour_rate=0,
        labour_unit="sqm",
    )
    s2.components = [SystemComponent(product_id=q.id, consumption_per_unit=d("1"))]
    db.add(s2)
    db.flush()
    with pytest.raises(MissingPriceError, match="drum"):
        system_rate(db, s2)


# --- Part 2.6: labour per sq ft on a system in rmt -------------------------------------------------


def test_a_labour_unit_that_does_not_fit_the_system_is_refused(db):
    with pytest.raises(MissingPriceError, match="labour"):
        build_rate(unit="rmt", components=[], surface_prep=Decimal(0), labour_rate=Decimal(10),
                   labour_unit="sqft", margin_percent=Decimal(0))  # fmt: skip
    ok = build_rate(unit="sqm", components=[], surface_prep=Decimal(0), labour_rate=Decimal(10),
                    labour_unit="sqft", margin_percent=Decimal(0))  # fmt: skip
    assert ok.labour_per_unit == 10 * SQFT_PER_SQM
    assert build_rate(unit="rmt", components=[], surface_prep=Decimal(0), labour_rate=Decimal(10),
                      labour_unit="rmt", margin_percent=Decimal(0)).rate == 10  # fmt: skip
    # a stored system in rmt with labour per sq ft: no rate, said plainly (and refused on save)
    s = System(
        code="T38-RMTLAB",
        name="Invented coving labour",
        unit="rmt",
        labour_rate=12,
        labour_unit="sqft",
    )
    db.add(s)
    db.flush()
    with pytest.raises(MissingPriceError, match="labour"):
        system_rate(db, s)


# --- Part 3.1: a labour piece bill subtracts only what was paid for that job -------------------------


def test_a_plaster_bill_is_not_reduced_by_the_coating_paid_on_the_same_item(boss, world, db):
    # item billed 100 sqm, coating paid 100 sqm: the plaster bill is 100 × ₹15 = ₹1,500 (it was 0)
    c, h = boss
    contract(c, h, world)
    k = db.scalar(select(ClientContract).where(ClientContract.site_id == world["site"]))
    line = db.scalar(
        select(ContractLine).where(ContractLine.contract_id == k.id, ContractLine.unit == "sqm")
    )
    gang = Vendor(name="Invented Applicators 38", type="labour_contractor", pan="ABCPA3838A")
    db.add(gang)
    db.commit()
    cards = {}
    for job, rate in (("Coating", "10"), ("Plaster", "15")):
        cards[job] = c.post("/api/labour/rate-cards", json={"contractor_id": gang.id, "job": job, "unit": "sqm",
                                                             "rate": rate, "valid_from": "2026-04-01"}, headers=h).json()  # fmt: skip
    b = RaBill(
        code="RA-T38-1",
        contract_id=k.id,
        site_id=world["site"],
        seq=1,
        period_to=date(2026, 9, 30),
        status="submitted",
    )
    db.add(b)
    db.flush()
    db.add(
        RaBillLine(ra_bill_id=b.id, contract_line_id=line.id, qty=d(100), rate=500, amount=d(50000))
    )
    db.commit()
    period = {
        "contractor_id": gang.id,
        "site_id": world["site"],
        "period_from": "2026-09-01",
        "period_to": "2026-09-30",
    }
    coat = c.post(
        "/api/labour/bills/piece",
        json=period
        | {"lines": [{"contract_line_id": line.id, "rate_card_id": cards["Coating"]["id"]}]},
        headers=h,
    )
    assert coat.status_code == 201, coat.text
    assert d(coat.json()["lines"][0]["qty"]) == 100
    plaster = c.post(
        "/api/labour/bills/piece",
        json=period
        | {"lines": [{"contract_line_id": line.id, "rate_card_id": cards["Plaster"]["id"]}]},
        headers=h,
    )
    assert plaster.status_code == 201, plaster.text
    assert d(plaster.json()["lines"][0]["qty"]) == 100 and d(plaster.json()["gross"]) == d(
        "1500.00"
    )
    # the coating, paid already, has nothing more
    again = c.post(
        "/api/labour/bills/piece",
        json=period
        | {"lines": [{"contract_line_id": line.id, "rate_card_id": cards["Coating"]["id"]}]},
        headers=h,
    )
    assert again.status_code == 422


# --- Part 3.2: a product added to a working keeps the master freight --------------------------------


def test_a_product_added_in_a_working_keeps_the_master_freight(boss, db):
    # master freight ₹5/kg at 1.5 kg/sqm and 7 % wastage keeps ₹8.03/sqm of freight (it was 0)
    c, h = boss
    p = _product(db, "Invented primer 38", price="80")
    g = _group(db)
    db.commit()
    c.post(f"/api/prices/products/{p.id}/freight", json={"per_unit": "5"}, headers=h)
    r = c.put(
        f"/api/rate-working/groups/{g.id}",
        json={"wastage_percent": "7", "products": [{"product_id": p.id, "consumption": "1.5"}]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert d(out["products"][0]["freight_used"]) == 5
    row = next(x for x in out["rows"] if x["item"] == p.name)
    assert cents(d(row["freight"]) * d(row["coverage"])) == d("8.03")
    # saved again with the freight left blank: still the master's; typed 0: 0
    pid = out["products"][0]["id"]
    out = c.put(
        f"/api/rate-working/groups/{g.id}",
        json={
            "products": [
                {"id": pid, "product_id": p.id, "consumption": "1.5", "freight_used": None}
            ]
        },
        headers=h,
    ).json()
    assert d(out["products"][0]["freight_used"]) == 5
    out = c.put(
        f"/api/rate-working/groups/{g.id}",
        json={
            "products": [{"id": pid, "product_id": p.id, "consumption": "1.5", "freight_used": "0"}]
        },
        headers=h,
    ).json()
    assert d(out["products"][0]["freight_used"]) == 0


# --- Part 3.3: free-issue material is not costed ----------------------------------------------------


def test_free_issue_material_is_shown_and_not_costed(boss, db):
    c, h = boss
    cement = _product(db, "Invented cement", price="8")
    coat = _product(db, "Invented coat 38", price="100")
    s = System(
        code="T38-FREE", name="Invented screed system", unit="sqm", labour_rate=0, labour_unit="sqm"
    )
    s.components = [SystemComponent(product_id=cement.id, consumption_per_unit=d("10"), wastage_percent=0),
                    SystemComponent(product_id=coat.id, consumption_per_unit=d("1"), wastage_percent=0)]  # fmt: skip
    db.add(s)
    db.flush()
    g = _group(db, s)
    for p in g.products:
        p.freight_used = 0
    w = db.get(RateWorking, g.working_id)
    w.free_issue_product_ids = [cement.id]
    db.commit()
    out = working.work(db, g)
    assert d(out["material_sqm"]) == 100  # the cement (₹80/sqm) is the client's
    row = next(x for x in out["rows"] if x["item"] == cement.name)
    assert row["ref"] == "free issue" and d(row["per_sqm"]) == 0
    db.commit()  # work() keeps the result on the group: the export works it again
    sheet = load_workbook(
        BytesIO(c.get(f"/api/rate-working/{w.id}/export.xlsx", headers=h).content)
    )["WORKING"]
    cement_row = next(r for r in sheet.iter_rows(values_only=True) if r[1] == cement.name)
    assert "free issue" in cement_row and cement_row[4] in (None, 0)


# --- Part 3.5: the current price: a valid rate contract first ----------------------------------------


def test_a_valid_rate_contract_beats_a_price_typed_in_a_working(db):
    from app.sitecontrol.models import RateContract

    p = _product(db, "Invented membrane 38", unit="sqm")
    v = Vendor(name="Invented Membranes 38", type="material_supplier")
    db.add(v)
    db.flush()
    today = ist_today()
    rc = RateContract(
        vendor_id=v.id,
        product_id=p.id,
        rate=d(240),
        valid_from=today - timedelta(days=30),
        valid_till=today + timedelta(days=30),
    )
    db.add(rc)
    db.flush()
    prices.record_price(
        db,
        p.id,
        d(240),
        source="rate_contract",
        ref=f"RC {rc.id} v1",
        vendor_id=v.id,
        on=rc.valid_from,
    )
    prices.record_price(db, p.id, d(260), source="po", ref="PO-T38-1", on=today - timedelta(days=5))
    prices.record_price(db, p.id, d(300), source="manual", ref="Rate working 1", on=today)
    cur = prices.current(db, p.id)
    assert cur.purchase_rate == 240 and prices.basis_of(db, cur).startswith("rate contract")
    rc.valid_till = today - timedelta(days=1)  # expired: the latest PO or vendor quote
    db.flush()
    cur = prices.current(db, p.id)
    assert cur.purchase_rate == 260 and prices.basis_of(db, cur).startswith("latest PO")
    rc.is_active = False
    db.execute(
        ProductPrice.__table__.delete().where(
            ProductPrice.source == "po", ProductPrice.product_id == p.id
        )
    )
    cur = prices.current(db, p.id)
    assert cur.purchase_rate == 300 and prices.basis_of(db, cur).startswith("typed")


def test_retyping_an_older_price_on_another_day_is_recorded(db):
    p = _product(db, "Invented sealer 38")
    today = ist_today()
    first = prices.record_price(
        db, p.id, d(100), source="manual", ref="Rate working 7", on=today - timedelta(days=3)
    )
    prices.record_price(
        db, p.id, d(110), source="manual", ref="Rate working 7", on=today - timedelta(days=2)
    )
    again = prices.record_price(db, p.id, d(100), source="manual", ref="Rate working 7", on=today)
    assert again is not None and again.id != first.id
    assert prices.current(db, p.id).id == again.id
    # the same day again is a retry: nothing new, and the row it is can be asked for
    assert (
        prices.record_price(db, p.id, d(100), source="manual", ref="Rate working 7", on=today)
        is None
    )
    assert (
        prices.record_price(
            db, p.id, d(100), source="manual", ref="Rate working 7", on=today, return_existing=True
        ).id
        == again.id
    )


# --- Part 5: low items ----------------------------------------------------------------------------


def test_labour_per_sqm_is_kept_to_4_decimals_until_the_rate(db, boss):
    # ₹10 per sqm is ₹0.9290 per sq ft (4 decimals), × 10.7639 = ₹10.00 per sqm (it was 0.93 → ₹10.01)
    s = System(
        code="T38-LAB", name="Invented labour system", unit="sqm", labour_rate=10, labour_unit="sqm"
    )
    db.add(s)
    db.flush()
    g = _group(db, s)
    db.commit()
    db.refresh(g)
    assert d(g.labour_used_sqft) == d("0.9290")
    br = build_rate(unit="sqm", components=[], surface_prep=Decimal(0), labour_rate=Decimal(g.labour_used_sqft),
                    labour_unit="sqft", margin_percent=Decimal(0))  # fmt: skip
    assert br.rate == d("10.00")
    gang = Vendor(name="Invented plasterers 38", type="labour_contractor")
    db.add(gang)
    db.flush()
    from app.costing.models import LabourRateCard

    card = LabourRateCard(
        contractor_id=gang.id, job="Plaster", unit="sqm", rate=15, valid_from=date(2026, 4, 1)
    )
    db.add(card)
    db.flush()
    g.labour_rate_card_id = card.id
    working.labour_from_card(db, g)
    db.commit()
    db.refresh(g)
    assert d(g.labour_paid_sqft) == d("1.3935")  # 15 ÷ 10.7639


def test_step_rates_add_up_to_the_main_item_rate(db):
    # three steps of ₹10 each at 30 % margin: 14.29 × 3 = 42.87, but the rate is 42.86
    t = _tender(db)
    sec = BoqSection(tender_id=t.id, title="Invented terrace", sort_order=1)
    db.add(sec)
    db.flush()
    texts = [
        "Surface preparation of the terrace",
        "Waterproof coating, two coats",
        "Protection plaster over the coating",
    ]
    lines = [
        BoqLine(tender_id=t.id, section_id=sec.id, sort_order=i, description=x, unit="sqm", qty=100)
        for i, x in enumerate(texts)
    ]
    db.add_all(lines)
    db.flush()
    w = working.for_tender(db, t)
    (g,) = working.suggest(db, w)
    coat = _product(db, "Invented waterproof coating 38", price="10")
    prot = _product(db, "Invented protection plaster 38", price="10")
    g.surface_prep, g.margin_percent, g.wastage_percent = d(10), d(30), d(0)
    g.products = [
        working.new_product(db, coat.id, d(1), 0),
        working.new_product(db, prot.id, d(1), 1),
    ]
    for p in g.products:
        p.freight_used = 0
    db.flush()
    shares = working.step_shares(db, w, g)
    assert g.rate_sqm == d("42.86")
    assert sum(shares.values()) == g.rate_sqm
    assert sorted(shares.values()) == [d("14.28"), d("14.29"), d("14.29")]


def test_each_product_keeps_its_own_wastage_when_no_application_matched(db):
    a = _product(db, "Invented base coat 38", price="100")
    b = _product(db, "Invented top coat 38", price="100")
    s = System(
        code="T38-WAST",
        name="Invented two-coat system",
        unit="sqm",
        labour_rate=0,
        labour_unit="sqm",
    )
    s.components = [SystemComponent(product_id=a.id, consumption_per_unit=d("1"), wastage_percent=5),
                    SystemComponent(product_id=b.id, consumption_per_unit=d("1"), wastage_percent=10)]  # fmt: skip
    db.add(s)
    db.flush()
    g = _group(db, s, name="Invented podium")
    for p in g.products:
        p.freight_used = 0
    out = working.work(db, g)
    # 1.05 × 100 + 1.10 × 100 (it was 1.10 × 100 for both: the highest)
    assert d(out["material_sqm"]) == d("215.00")


def test_excel_writes_no_rate_for_a_product_without_a_price(boss, db):
    c, h = boss
    a = _product(db, "Invented priced coat 38", price="100")
    b = _product(db, "Invented unpriced coat 38")
    s = System(
        code="T38-NORATE",
        name="Invented unpriced system",
        unit="sqm",
        labour_rate=0,
        labour_unit="sqm",
    )
    s.components = [SystemComponent(product_id=a.id, consumption_per_unit=d("1")),
                    SystemComponent(product_id=b.id, consumption_per_unit=d("1"))]  # fmt: skip
    db.add(s)
    db.flush()
    g = _group(db, s)
    db.commit()
    sheet = load_workbook(
        BytesIO(c.get(f"/api/rate-working/{g.working_id}/export.xlsx", headers=h).content)
    )["WORKING"]
    rate_row = next(r for r in sheet.iter_rows(values_only=True) if r[1] == "RATE")
    assert rate_row[4] == "no rate" and rate_row[5] == "no rate"


def test_a_zero_price_or_consumption_is_warned_not_blocked(db):
    a = _product(db, "Invented free sample 38", price="0")
    b = _product(db, "Invented thin coat 38", price="50")
    s = System(
        code="T38-ZERO", name="Invented zero system", unit="sqm", labour_rate=0, labour_unit="sqm"
    )
    s.components = [SystemComponent(product_id=a.id, consumption_per_unit=d("1")),
                    SystemComponent(product_id=b.id, consumption_per_unit=d("0"))]  # fmt: skip
    db.add(s)
    db.flush()
    g = _group(db, s)
    out = working.work(db, g)
    assert out["errors"] == [] and out["rate_sqm"] is not None
    assert any(a.name in x and "price is 0" in x for x in out["warnings"])
    assert any(b.name in x and "consumption is 0" in x for x in out["warnings"])
    br = system_rate(db, s, Decimal(0))
    assert any("price is 0" in x for x in br.warnings) and any(
        "consumption is 0" in x for x in br.warnings
    )
