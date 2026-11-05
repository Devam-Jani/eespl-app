# ruff: noqa: E501, F811  (invented data reads better unwrapped)
"""Prompt 38e, the company BOM: reading the layout (a work item with its unit at the end of its
name, its products in [ ], one recipe per brand), the preview's checks, the import (systems, brand
options, components converted from sq ft and rft, products not in the master listed and created
on request), and the rate working, the estimate and a system's rate using the BOM's figures.
Invented data only: two work items, one per sq ft and per sqm, two brands."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from app.costing import working
from app.costing.models import ProductConsumption, RateGroup, RateWorking
from app.estimate import service as est
from app.estimate.models import Estimate, EstimateArea
from app.masters import bom
from app.masters.models import Product, ProductPrice, System
from app.masters.rate import system_rate
from app.tenders.models import Tender
from app.timefmt import ist_today
from tests.test_finance import boss  # noqa: F401  (fixture)

D = Decimal
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _rows(extra: list[tuple] | None = None) -> list[tuple]:
    """An invented BOM: a roof coating per sq ft and per sqm by two brands (Arvox, Zento), and a
    joint filling per rft by one."""
    return [
        (None,),
        ("ItemName", "Consumption", "Unit", "Rate", "Amount", None, None, None, "Last P Price ", "Lspdate"),
        (None,),
        ("INVENTED ROOF COATING_SQFT", None, "SQF"),
        ("[ ARVOX ROOFCOAT - 20 KG ]", 0.1393, "KGS", None, None, None, None, None, 150.5, datetime(2026, 1, 10)),
        ("[ INVENTED GLASS MESH - 50 MTR ]", 0.0975, "SQM"),
        ("[ PROCESS FOR PROJECT ]", 1, None, 0, 0),
        ("Rate Per ", None, None, 0, 0),
        (None,),
        ("INVENTED ROOF COATING_SQMT", None, "SQM"),
        ("[ ARVOX ROOFCOAT - 20 KG ]", 1.5, "KGS"),
        ("[ INVENTED GLASS MESH - 50 MTR ]", 1.05, "SQM"),
        ("[ PROCESS FOR PROJECT ]", 1, None, 0, 0),
        ("Rate Per ", None, None, 0, 0),
        ("INVENTED ROOF COATING_SQMT", None, "SQM"),
        ("[ ZENTO FLEXCOAT ]", 6, "KG"),
        ("[ INVENTED GLASS MESH - 50 MTR ]", 1.05, "SQMT"),
        ("Rate Per ", None, None, 0, 0),
        ("INVENTED ROOF COATING_SQFT", None, "SQF"),
        ("[ ZENTO FLEXCOAT ]", 0.2323, "KG"),
        ("[ INVENTED GLASS MESH - 50 MTR ]", 0.3, "SQ. MTR."),
        ("Rate Per ", None, None, 0, 0),
        ("INVENTED JOINT FILLING_RFT", None, "SQF"),
        ("[ ARVOX JOINTMIX - 10 KG ]", 0.05, "KGS", None, None, None, None, None, 88, datetime(2026, 2, 1)),
        ("[ INVENTED BACKER ROD ]", 0.3048, "RMT"),
        ("[ PROCESS FOR PROJECT ]", 1, None, 0, 0),
        ("Rate Per ", None, None, 0, 0),
        *(extra or []),
        ("Page -1 of 1",),
    ]


def _file(extra: list[tuple] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in _rows(extra):
        ws.append(list(r))
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _product(db, name, unit="kg", price=None, **kw) -> Product:
    p = Product(code=f"T38E-{name[:20]}", name=name, unit=unit, **kw)
    db.add(p)
    db.flush()
    if price is not None:
        db.add(ProductPrice(product_id=p.id, purchase_rate=D(price), effective_from=ist_today() - timedelta(days=5), source="manual"))
        db.flush()
    return p


def _master(db) -> dict[str, Product]:
    """The products the master already has (the joint's two are not in it)."""
    out = {
        "roofcoat": _product(db, "ARVOX ROOFCOAT", price="200", wastage_percent=D(5)),
        "flexcoat": _product(db, "ZENTO FLEXCOAT", price="150"),
        "mesh": _product(db, "Invented glass mesh", unit="sqm", price="20", aliases=["INVENTED GLASS MESH - 50 MTR"], wastage_percent=D(5)),
    }
    db.commit()
    return out


def _import(db, data: bytes, create=None, default_brand=None) -> dict:
    out = bom.save(db, data, None, create, default_brand)
    db.commit()
    return out


def _system(db, name, unit) -> System:
    return db.scalar(select(System).where(System.name == name, System.unit == unit))


def _group(db, s: System, name="Invented roof main item") -> RateGroup:
    t = Tender(code=f"T-2026-38E{s.id % 100:02d}", name="Invented BOM check", status="draft")
    db.add(t)
    db.flush()
    w = RateWorking(tender_id=t.id, rev_no=0, margin_basis="selling")
    db.add(w)
    db.flush()
    g = RateGroup(working_id=w.id, name=name, sort_order=1, system_id=s.id, margin_percent=0)
    db.add(g)
    db.flush()
    working.init_from_system(db, g)
    db.flush()
    return g


# --- reading the file and the preview's checks -----------------------------------------------------


def test_the_preview_reads_the_layout_converts_and_lists_unmatched_products(login_as, db):
    _master(db)
    c, h = login_as("planning")
    r = c.post("/api/bom/preview", files={"file": ("bom.xlsx", _file(), XLSX)}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    n = out["counts"]
    assert (n["work_items"], n["product_rows"], n["products"]) == (5, 10, 5)
    # the sq ft and sqm roof coating are one system per sqm; the joint per rft is one per rmt
    assert (n["systems"], n["options"], n["components"], n["converted_options"]) == (2, 3, 6, 1)
    roof = next(s for s in out["systems"] if s["unit"] == "sqm")
    assert roof["name"] == "INVENTED ROOF COATING" and [o["brand"] for o in roof["options"]] == ["Arvox", "Zento"]
    arvox = roof["options"][0]
    assert not arvox["converted"] and arvox["checked_against"] == [4]  # its sq ft recipe, checked only
    assert [(x["consumption"], x["wastage_included"]) for x in arvox["components"]] == [("1.5000", False), ("1.0500", True)]
    joint = next(s for s in out["systems"] if s["unit"] == "rmt")
    mix = joint["options"][0]["components"][0]
    # 0.05 per rft × 3.2808 per rmt, the file's figure kept beside it
    assert mix["consumption"] == "0.1640" and mix["original"] == {"consumption": "0.05", "per": "rft"}
    # not in the master: listed with what creating it would make, never dropped
    missing = {u["name"]: u for u in out["unmatched"]}
    assert set(missing) == {"ARVOX JOINTMIX - 10 KG", "INVENTED BACKER ROD"}
    assert missing["ARVOX JOINTMIX - 10 KG"]["create_as"] == "ARVOX JOINTMIX"
    assert missing["ARVOX JOINTMIX - 10 KG"]["pack"] == {"size": "10", "unit": "kg"}
    assert missing["ARVOX JOINTMIX - 10 KG"]["last_price"] == "88"
    # the alias and the name without the pack both match
    assert {x["matched_by"] for x in arvox["components"]} == {"name without the pack", "alias"}


def test_the_preview_warns_on_the_checks_without_blocking(login_as, db):
    c, h = login_as("super_admin")
    extra = [("INVENTED SLEEVE FILLING", None, "NOS"), ("[ ARVOX JOINTMIX - 10 KG ]", 0.5, "KGS"), ("Rate Per ", None, None, 0, 0)]
    r = c.post("/api/bom/preview", files={"file": ("bom.xlsx", _file(extra), XLSX)}, headers=h)
    assert r.status_code == 200, r.text
    warnings = r.json()["warnings"]
    kinds = {(w["kind"], w["brand"]) for w in warnings}
    # Zento's sq ft figure 0.2323 is 2.5004 per sqm against 6 in its sqm item; Arvox's agree
    assert ("unit_gap", "Zento") in kinds and ("unit_gap", "Arvox") not in kinds
    # Arvox 1.5 against Zento 6 for the main material: 4×
    assert any(w["kind"] == "brand_ratio" and "4×" in w["message"] for w in warnings)
    # 0.3 sqm of mesh per sq ft of the work, above 0.2
    assert any(w["kind"] == "sheet_high" and w["rows"] == [21] for w in warnings)
    # no unit in the name: read per nos, flagged
    sleeve = next(w for w in warnings if w["kind"] == "no_unit")
    assert sleeve["unit"] == "nos" and "per nos" in sleeve["message"]
    assert r.json()["counts"]["systems"] == 3


def test_only_the_super_admin_and_planning_import_the_bom(login_as):
    c, h = login_as("estimator")
    r = c.post("/api/bom/preview", files={"file": ("bom.xlsx", _file(), XLSX)}, headers=h)
    assert r.status_code == 403
    c, h = login_as("planning", email="planner@example.com")
    r = c.post("/api/bom/preview", files={"file": ("x.xlsx", b"not a workbook", XLSX)}, headers=h)
    assert r.status_code == 422 and "workbook" in r.json()["detail"]


# --- the import ----------------------------------------------------------------------------------


def test_the_import_makes_systems_with_brand_options_and_creates_products_asked_for(login_as, db):
    m = _master(db)
    c, h = login_as("planning")
    r = c.post("/api/bom/import", files={"file": ("bom.xlsx", _file(), XLSX)},
               data={"create": '["ARVOX JOINTMIX - 10 KG"]'}, headers=h)  # fmt: skip
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"]["systems_created"] == 2
    assert (out["counts"]["options"], out["counts"]["components"], out["counts"]["products_created"]) == (3, 5, 1)
    assert out["left_out"] == [{"name": "INVENTED BACKER ROD", "rows": [25]}]
    db.expire_all()
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    assert roof.source == "company_bom" and not roof.to_confirm
    assert [(o.brand, o.is_default) for o in roof.options] == [("Arvox", True), ("Zento", False)]
    assert [c.product_id for c in roof.recipe()] == [m["roofcoat"].id, m["mesh"].id]  # the default's
    zento = roof.options[1]
    assert [c.product_id for c in roof.recipe(zento.id)] == [m["flexcoat"].id, m["mesh"].id]
    mesh = roof.recipe()[1]
    assert mesh.wastage_included and mesh.source == "company_bom" and "row 12" in mesh.original_ref
    # the joint: per rmt, its figure from rft kept; the product not created is said, not dropped
    joint = _system(db, "INVENTED JOINT FILLING", "rmt")
    mix = joint.recipe()[0]
    assert (mix.consumption_per_unit, mix.original_consumption, mix.original_unit) == (D("0.1640"), D("0.05"), "rft")
    assert joint.to_confirm and "INVENTED BACKER ROD" in joint.note
    made = db.scalar(select(Product).where(Product.name == "ARVOX JOINTMIX"))
    assert made.aliases == ["ARVOX JOINTMIX - 10 KG"] and made.pack_size == D(10) and made.unit == "kg"
    price = db.scalar(select(ProductPrice).where(ProductPrice.product_id == made.id))
    assert price.purchase_rate == D("88") and price.effective_from == date(2026, 2, 1)


def test_a_second_import_updates_the_same_systems_and_keeps_options_made_by_hand(db):
    _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    first_id = roof.id
    out = _import(db, _file(), default_brand="Zento")
    assert out["counts"]["systems_updated"] == 2 and "systems_created" not in out["counts"]
    db.expire_all()
    roof = db.get(System, first_id)
    assert db.scalar(select(System.id).where(System.name == "INVENTED ROOF COATING").order_by(System.id.desc())) == first_id
    assert [(o.brand, o.is_default) for o in roof.options] == [("Arvox", False), ("Zento", True)]
    assert len(roof.components) == 4  # two options of two products: the old ones replaced


def test_a_system_made_by_hand_keeps_its_recipe_as_an_option(db):
    m = _master(db)
    from app.masters.models import SystemComponent  # noqa: PLC0415

    s = System(code="T38E-HAND", name="Invented roof coating", unit="sqm", labour_rate=0, labour_unit="sqm")
    s.components = [SystemComponent(product_id=m["roofcoat"].id, consumption_per_unit=D("1.2"), wastage_percent=0)]
    db.add(s)
    db.commit()
    _import(db, _file())
    db.expire_all()
    s = db.get(System, s.id)
    assert [o.brand for o in s.options] == ["Arvox", "Zento", "Before the BOM"]
    assert s.default_option().brand == "Arvox"
    assert [c.consumption_per_unit for c in s.recipe()] == [D("1.5000"), D("1.0500")]  # never mixed in


# --- the rate working, the estimate and a system's rate -------------------------------------------


def test_the_working_takes_the_company_bom_figure_with_its_source_and_wastage(db):
    m = _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    # a data sheet's figure for the same product: the company BOM ranks above it
    db.add(ProductConsumption(product_id=m["roofcoat"].id, surface="any", consumption=D("2.2"), source="data_sheet"))
    db.flush()
    g = _group(db, roof, "Invented raft roof coating")  # raft: 5-7 % wastage from Settings
    coat, mesh = g.products
    assert coat.consumption == D("1.5") and coat.consumption_source.startswith("company BOM: Arvox")
    assert "wastage from Settings" in coat.consumption_source
    assert mesh.wastage_included and "wastage included" in mesh.consumption_source
    out = working.work(db, g)
    assert out["errors"] == [] and out["unit"] == "sqm" and out["system_option"] == "Arvox"
    rows = {r["item"]: r for r in out["rows"]}
    assert rows["ARVOX ROOFCOAT"]["coverage"] == D("1.5") * D("1.07")  # the raft's 7 %
    assert rows["Invented glass mesh"]["coverage"] == D("1.05")  # the overlap is in it already
    assert rows["Invented glass mesh"]["wastage_note"] == "included in the company BOM figure"
    # material 1.605 × 200 + 1.05 × 20 = 342 per sqm
    assert out["material_sqm"] == D("342.00")


def test_the_clients_minimum_still_wins_over_the_company_bom(db):
    m = _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    g = _group(db, roof)
    g.req_min_kg_sqm = D("1.8")
    working.repick(db, g)
    assert g.products[0].consumption == D("1.8") and "client's minimum" in g.products[0].consumption_source
    # a consumption row that meets the minimum comes before the minimum itself
    db.add(ProductConsumption(product_id=m["roofcoat"].id, surface="any", consumption=D("2.2"), source="data_sheet"))
    db.flush()
    working.repick(db, g)
    assert g.products[0].consumption == D("2.2") and g.products[0].consumption_source.startswith("data sheet")


def test_the_working_switches_to_another_brand_option(boss, db):
    m = _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    g = _group(db, roof)
    db.commit()
    c, h = boss
    zento = roof.options[1].id
    r = c.put(f"/api/rate-working/groups/{g.id}", json={"system_option_id": zento}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["system_option"] == "Zento" and [o["brand"] for o in out["system_options"]] == ["Arvox", "Zento"]
    assert [p["product_id"] for p in out["products"]] == [m["flexcoat"].id, m["mesh"].id]
    assert [p["wastage_included"] for p in out["products"]] == [False, True]
    r = c.put(f"/api/rate-working/groups/{g.id}", json={"system_option_id": 999999}, headers=h)
    assert r.status_code == 422


def test_a_main_item_per_rmt_is_worked_per_rmt_and_rft(db):
    _master(db)
    _import(db, _file(), create=["ARVOX JOINTMIX - 10 KG"])
    joint = _system(db, "INVENTED JOINT FILLING", "rmt")
    g = _group(db, joint, "Invented joint")
    g.margin_percent = 0
    assert g.unit == "rmt"
    p = g.products[0]
    assert p.consumption == D("0.1640") and "0.05 per rft × 3.2808" in p.consumption_source
    out = working.work(db, g)
    assert out["errors"] == [] and (out["unit"], out["small_unit"]) == ("rmt", "rft")
    assert out["rate_sqm"] == D("14.43")  # 0.164 kg × ₹88, no margin: per rmt
    assert out["rate_sqft"] == (D("14.432") / D("3.2808")).quantize(D("0.01"))  # per rft


def test_a_system_per_nos_has_no_working(db):
    _master(db)
    _import(db, _file([("INVENTED SLEEVE FILLING", None, "NOS"), ("[ ARVOX ROOFCOAT - 20 KG ]", 0.5, "KGS")]))
    sleeve = _system(db, "INVENTED SLEEVE FILLING", "nos")
    assert sleeve.to_confirm and "per nos" in sleeve.note
    import pytest  # noqa: PLC0415

    with pytest.raises(working.WorkingUnitError, match="per nos"):
        _group(db, sleeve)


def test_the_estimate_uses_the_company_bom_and_adds_no_wastage_on_the_mesh(db):
    _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    t = Tender(code="T-2026-38E99", name="Invented estimate check", status="draft")
    db.add(t)
    db.flush()
    e = Estimate(code="EST-T38E", tender_id=t.id, title="Invented roof")
    db.add(e)
    db.flush()
    db.add(EstimateArea(estimate_id=e.id, source="manual", name="Invented terrace", floor_sqm=D(100), periphery_m=D(0)))
    db.flush()
    zento = roof.options[1]
    lines = est.add_system(db, e, roof, zento.id)
    coat, mesh = (est.work_line(db, e, ln) for ln in lines)
    assert coat.system == "INVENTED ROOF COATING (Zento)"
    assert coat.cov.per_sqm == D("6") and "company BOM: Zento" in coat.cov.shown
    assert coat.qty == D(600)  # the product's own wastage is 0
    assert mesh.wastage == 0 and mesh.qty == D(105)  # its own 5 % is not added: the overlap is in 1.05


def test_a_systems_rate_is_built_from_the_chosen_brand_option(db):
    _master(db)
    _import(db, _file())
    roof = _system(db, "INVENTED ROOF COATING", "sqm")
    arvox, zento = roof.options
    a = system_rate(db, roof, margin_percent=D(0))
    z = system_rate(db, roof, margin_percent=D(0), option_id=zento.id)
    assert a.material_cost == D("1.5") * 200 + D("1.05") * 20  # no wastage on the mesh
    assert z.material_cost == D(6) * 150 + D("1.05") * 20
    assert system_rate(db, roof, margin_percent=D(0), option_id=arvox.id).rate == a.rate
