# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Part 0 of the work order and billing milestone, from the methodology review, on invented
data: stage weights from the stages' days (total 100 %), every test of the client's rule reaches
the site, one material-test row per product with only its material's specs and the stricter of
two contradicting values, the drawing labels summarised in the client's copy, readable sources,
makes from the client's other SOPs, and a tank's square-plan area marked to confirm until the
real perimeter is given."""

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.costing.working import readable_source
from app.methodology import build as bld
from app.methodology import site as msite
from app.methodology.export import places_text
from app.methodology.models import (
    ClientStandard,
    Methodology,
    MethodSystem,
    PondTest,
    StandardDocument,
    StandardRule,
)
from app.sites.models import StageTemplate
from app.sites.work import weights_by_days
from tests.test_finance import boss  # noqa: F401  (fixtures)
from tests.test_methodology import _tender


def test_stage_weights_come_from_the_stages_days_and_total_100():
    assert (
        weights_by_days([1, 1, 1]) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
        or sum(weights_by_days([1, 1, 1])) == 100
    )
    w = weights_by_days([1, 2, 5, 1])
    assert sum(w) == Decimal(100) and w[2] == max(w) and w[0] < w[1]
    coating = {
        "heading": "PROTECTIVE COATING",
        "steps": [
            {"text": "1st coat", "wait": "3 to 4 hrs"},
            {"text": "2nd coat", "wait": "8 hrs"},
            {"text": "cure", "wait": "air curing for 48 hours"},
        ],
    }
    prep = {
        "heading": "SURFACE PREPARATION",
        "steps": [{"text": "clean", "scope": "client"}, {"text": "fill cracks"}],
    }
    testing = {
        "heading": "TESTING",
        "steps": [{"text": "pond", "wait": "72 hours"}, {"text": "pre-pond", "wait": "24 hours"}],
    }
    days = [msite.stage_days(x) for x in (prep, coating, testing)]
    assert days == [1, 4, 5]  # 0.5 day per step of ours + waits (2.5 days of curing ...)
    assert (
        sum(weights_by_days(days)) == 100 and len(set(weights_by_days(days))) == 3
    )  # not an equal split


def _tank_standard(db) -> ClientStandard:
    std = ClientStandard(
        name="Invented tank standard", approved_makes=["INVENTA"], guarantee_years=10
    )
    db.add(std)
    db.flush()
    doc = StandardDocument(
        standard_id=std.id,
        sop_no="INV-WP-OHT-015",
        revision="0",
        file_name="invented.pdf",
        fmt="old",
        pages=3,
        element="oht",
    )
    db.add(doc)
    db.flush()
    db.add(StandardRule(standard_id=std.id, document_id=doc.id, element="oht", element_label="Overhead tank", condition={}, system_type="acrylic_cementitious",
                        system_text="2K elastomeric cementitious coating with screed", page=1,
                        tests=[{"kind": "pre_pond", "hours": 24, "text": "Pre pond test for 24 hours", "page": 2},
                               {"kind": "fill", "hours": 72, "text": "fill the tank completely ... no leakages after 72 hrs", "page": 2}],
                        makes=[{"system": "2K elastomeric cementitious coating", "brand": "INVENTA", "product": "INVENTA FLEX", "status": "approved", "note": None, "page": 2}]))  # fmt: skip
    db.add(MethodSystem(code="T-TANK", name="Invented tank system", brand="Invented", system_type="acrylic_cementitious", elements=["oht", "ug_tank"],
                        stages=[{"heading": "PROTECTIVE COATING", "steps": [{"text": "2 coats of INVENTED TANK COAT.", "product": "INVENTED TANK COAT", "products": ["INVENTED TANK COAT"], "scope": "ours", "to_confirm": []}]},
                                {"heading": "PROTECTION LAYER", "steps": [{"text": "Screed.", "scope": "ours", "products": [], "to_confirm": []}]}]))  # fmt: skip
    db.commit()
    return std


def test_every_test_of_the_client_rule_reaches_the_site(boss, db):
    c, h = boss
    std = _tank_standard(db)
    t = _tender(
        db,
        std,
        lines=(("Overhead water tank", "Internal waterproofing of the overhead water tank"),),
    )
    m = c.post("/api/methodology/methodologies", json={"tender_id": t.id}, headers=h).json()
    assert c.patch(f"/api/tenders/{t.id}", json={"status": "won"}, headers=h).status_code == 200
    site = c.post(
        "/api/sites/from-tender", json={"tender_id": t.id, "start_date": "2026-11-02"}, headers=h
    ).json()
    db.expire_all()
    item = db.get(Methodology, m["id"]).items[0]
    rule = db.get(StandardRule, item.rule_id)
    wanted = {(x["kind"], x["hours"]) for x in rule.tests if x.get("hours")}
    got = {
        (p.kind, p.required_hours)
        for p in db.scalars(select(PondTest).where(PondTest.site_id == site["id"]))
    }
    assert wanted == got == {("pre_pond", 24), ("fill", 72)}
    tpl = db.get(StageTemplate, item.stage_template_id)
    testing = next(s for s in tpl.steps if s.name == "Testing")
    assert testing.hold_point
    steps = next(s for s in item.stages if s["heading"] == "TESTING")["steps"]
    assert all(
        any(f"{hrs} hours" in x["text"] for x in steps) for _k, hrs in wanted
    )  # each test is a hold-point step


def test_one_material_row_per_product_with_its_own_specs_and_the_stricter_value():
    q = SimpleNamespace(
        id=7,
        text="Elongation of the acrylic (elastomeric) cementitious coating: the SOP says min. 120% (p.8); min. 150% (p.4). Which applies?",
    )
    rule = SimpleNamespace(document_id=1, system_type="acrylic_cementitious", min_specs=[
        {"property": "elongation", "label": "Elongation", "required": "min. 120%", "num": 120, "op": "min", "system_type": "acrylic_cementitious", "standard": "ASTM D 412", "page": 8},
        {"property": "elongation", "label": "Elongation", "required": "min. 150%", "num": 150, "op": "min", "system_type": "cementitious", "standard": None, "page": 4},
        {"property": "tensile", "label": "Tensile strength", "required": "4 MPa", "num": 4, "op": "min", "system_type": "pu", "standard": "ASTM D412", "page": 8},
        {"property": "mesh_gsm", "label": "Mesh / fabric", "required": "min. 45 GSM", "num": 45, "op": "min", "system_type": "acrylic_cementitious", "standard": None, "page": 4},
    ])  # fmt: skip
    coat = msite.product_specs(
        [rule], "BRONCO INVENTGUARD PLUS acrylic cementitious", "coating", [q]
    )
    assert [x["property"] for x in coat] == ["Elongation"]  # not the PU's tensile, not the mesh
    assert (
        coat[0]["required"] == "min. 150%"
        and coat[0]["prebid_query_id"] == 7
        and "120%" in coat[0]["note"]
    )
    mesh = msite.product_specs([rule], "Geotextile 40 GSM", "mesh", [q])
    assert [x["property"] for x in mesh] == ["Mesh / fabric"]


def test_the_client_copy_summarises_the_drawing_labels():
    places = [
        {"name": "TOILET", "label": f"TOILET {a}", "area_sqm": s}
        for a, s in (("1480 X 2135", 3.16), ("2135X1480", 3.16), ("1365 X 2135", 2.91))
    ]
    assert (
        places_text(places, internal=False)
        == "3 toilets, 2.91 to 3.16 sqm: 1480 × 2135 (2), 1365 × 2135 (1)"
    )
    assert "TOILET 2135X1480" in places_text(places, internal=True)


def test_sources_read_as_words():
    assert (
        readable_source("old_boq") == "old BOQs" and readable_source("data_sheet") == "data sheet"
    )
    assert readable_source("site_actual") == "site actual" and readable_source("manual") == "manual"


def test_a_sop_without_makes_borrows_the_clients_makes_for_the_same_material():
    doc = SimpleNamespace(sop_no="INV-WP-OHT-015")
    own = SimpleNamespace(id=1, makes=[], document=None)
    other = SimpleNamespace(id=2, document=doc, makes=[{"system": "2K elastomeric cementitious coating", "brand": "INVENTA", "product": "FLEX 2K", "status": "approved"},
                                                       {"system": "Pre-applied HDPE membrane", "brand": "INVENTA", "product": "HDPE 12", "status": "approved"}])  # fmt: skip
    std = SimpleNamespace(rules=[own, other])
    alts, note = bld.other_sop_makes(std, own, {"acrylic_cementitious"})
    assert alts == ["INVENTA FLEX 2K — from SOP INV-WP-OHT-015"] and "other SOPs" in note
    none, why = bld.other_sop_makes(std, own, {"pu"})
    assert none == [] and "no other SOP" in why


def test_a_tank_area_from_a_square_plan_is_to_confirm_until_the_perimeter_is_given(boss, db):
    c, h = boss
    std = _tank_standard(db)
    t = _tender(
        db,
        std,
        lines=(("Overhead water tank", "Internal waterproofing of the overhead water tank"),),
    )
    m = c.post("/api/methodology/methodologies", json={"tender_id": t.id}, headers=h).json()
    mo = db.get(Methodology, m["id"])
    it = mo.items[0]
    bld.set_places(
        it,
        bld.tanks_from_note(
            "DOMESTIC WATER TANK | CAP: 12,500 LTRS | HEIGHT : 1.9+0.3M F.B.", "invented.dxf"
        ),
    )
    bld.recheck(db, mo)
    db.commit()
    rows = {r["topic"]: r for r in it.compliance["rows"]}
    assert (
        rows["Tank wall area"]["status"] == "confirm"
        and "square plan" in rows["Tank wall area"]["gap"]
    )
    assert (
        it.conditions["tank_perimeter_m"]["assumed"]
        and it.conditions["tank_freeboard_m"]["value"] == 0.3
    )
    r = c.put(
        f"/api/methodology/items/{it.id}/perimeter",
        json={"perimeter_m": 11.0, "reason": "Measured on the structural drawing"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    out = r.json()["items"][0]
    area = 12.5 / 1.9
    assert abs(float(out["qty"]) - (area + 11.0 * 2.2)) < 0.01
    assert not any(x["topic"] == "Tank wall area" for x in out["compliance"]["rows"])
    assert (
        c.put(
            f"/api/methodology/items/{it.id}/perimeter", json={"perimeter_m": 11.0}, headers=h
        ).status_code
        == 422
    )  # a reason is needed
