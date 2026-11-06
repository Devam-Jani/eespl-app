# ruff: noqa: E501, F811  (invented data reads better unwrapped)
"""Prompt 39a, spec products: a BOQ line read into key points, the data sheet (TDS) reader and
import, the consumption master with its history, and every brand's option ranked against the line's
key points, picked into the rate working. Invented brands and products only (Zentrafix, Arvox,
Corvane, Duramix, Elbrite)."""

import io
from decimal import Decimal

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.costing.models import RateGroup
from app.estimate import service as est
from app.estimate.models import Estimate, EstimateArea
from app.masters.models import Product, ProductPrice, System, SystemComponent, SystemOption
from app.spec import ai, keypoints, suggest, tds, vocab
from app.spec.models import ConsumptionChange, SpecPick, TdsDoc, TdsFact
from app.tenders.models import BoqLine, Tender
from app.timefmt import ist_today
from tests.test_finance import boss  # noqa: F401  (fixture)

D = Decimal

EXAMPLE_1 = (
    "1) Applying primer as per concrete surface... 2) Providing and applying two coats single component liquid application PU membrane "
    "to achieve minimum DFT of 1.2 to 1.5 mm... Required pond test for at least 48 hours... filling surface + 50 mm water depth... Terrace"
)
EXAMPLE_2 = (
    "Providing and applying PU flashing - polyester mesh sandwiched between 2 coats of Zentrafix Flexi PU... primer Zentrafix MIEP... "
    "Elongation at break > 400% as per ASTM D-412, Shore A 65, Tensile > 4 N/mm2, Adhesion > 2 N/mm2 as per ASTM D 903"
)


def _by(chips: list[dict], kind: str) -> list[dict]:
    return [c for c in chips if c["kind"] == kind]


# --- Part 3: the key points --------------------------------------------------------------------------


def test_the_terrace_example_reads_into_its_key_points():
    chips = keypoints.parse(EXAMPLE_1, "Sqm", D(120), ["Zentrafix"])
    assert _by(chips, "area")[0]["value"]["area"] == "terrace"
    system = _by(chips, "system")[0]
    assert system["label"] == "PU 1K liquid membrane" and system["value"]["type"] == "pu"
    assert [s["label"] for s in _by(chips, "steps")[0]["value"]["steps"]] == [
        "primer",
        "PU coat 1",
        "PU coat 2",
        "pond test",
    ]
    assert _by(chips, "coats")[0]["value"]["coats"] == 2
    assert _by(chips, "dft")[0]["value"] == {"lo": "1.2", "hi": "1.5"}
    assert _by(chips, "pond_test")[0]["value"] == {"hours": 48, "depth_mm": "50"}
    make = _by(chips, "make")[0]
    assert make["label"] == "make not named (any brand)" and make["value"]["brands"] == []
    # every chip shows the words it came from (where they are in the description)
    s, e = _by(chips, "dft")[0]["spans"][0]
    assert EXAMPLE_1[s:e] == "DFT of 1.2 to 1.5 mm"
    assert _by(chips, "unit")[0]["value"] == {"unit": "Sqm", "qty": "120"}


def test_the_flashing_example_reads_its_make_and_property_minimums():
    chips = keypoints.parse(EXAMPLE_2, "Nos", D(40), ["Zentrafix"])
    assert _by(chips, "area")[0]["value"]["area"] == "pipe_outlet"
    assert _by(chips, "system")[0]["label"] == "PU flashing with mesh"
    assert [s["label"] for s in _by(chips, "steps")[0]["value"]["steps"]] == [
        "primer",
        "PU coat 1",
        "mesh",
        "PU coat 2",
    ]
    make = _by(chips, "make")[0]["value"]
    assert make == {"brands": ["Zentrafix"], "equivalent": False}
    props = {c["value"]["property"]: c["value"] for c in _by(chips, "property")}
    assert props["elongation"]["min"] == "400" and props["elongation"]["standard"] == "ASTM D412"
    assert props["shore_a"]["min"] == "65"
    assert props["tensile"]["min"] == "4" and props["tensile"]["unit"] == "N/mm²"
    assert props["adhesion"]["min"] == "2" and props["adhesion"]["standard"] == "ASTM D903"
    asks = keypoints.asks(chips)
    assert (
        asks["brands"] == ["Zentrafix"]
        and asks["equivalent"] is False
        and asks["props"]["elongation"]["min"] == D(400)
    )


def test_an_ai_chip_is_suggested_until_confirmed(monkeypatch):
    sent = {}

    def fake(payload):
        sent["payload"] = payload
        return {
            "content": [
                {
                    "type": "text",
                    "text": '[{"kind": "upturn", "label": "upturn 300 mm", "value": {"mm": "300"}, "words": "up the parapet 1 ft"}, {"kind": "area", "label": "Terrace / roof"}]',
                }
            ]
        }

    monkeypatch.setattr(ai, "_post", fake)
    text = "PU coating on terrace taken up the parapet 1 ft"
    rules = keypoints.parse(text, "sqm", None, [])
    extra = ai.line_points(text, rules)
    assert [c["label"] for c in extra] == [
        "upturn 300 mm"
    ]  # the area the rules read is not repeated
    assert extra[0]["source"] == "ai" and extra[0]["confirmed"] is False and extra[0]["spans"]
    chips = rules + [{**extra[0], "value": {"coats": 3}, "kind": "coats"}]
    assert "coats" not in keypoints.asks(chips)  # not confirmed: not used for ranking
    chips[-1]["confirmed"] = True
    assert keypoints.asks(chips)["coats"] == 3
    assert "Already read" in sent["payload"]["messages"][0]["content"]


# --- Part 1: the data sheets -------------------------------------------------------------------------


def test_a_coverage_per_kg_in_sq_ft_becomes_kg_per_sqm():
    """23 to 25 sq ft per kg: 10.7639 / 25 = 0.4306 and 10.7639 / 23 = 0.4680 kg per sqm."""
    f = tds.consumption("Coverage: 23 to 25 sft/kg in two coats")[0]
    assert f.key == "kg/sqm" and f.coats == 2
    assert round(f.lo, 4) == D("0.4306") and round(f.hi, 4) == D("0.4680")
    g = tds.consumption("Consumption 80 - 100 gram per sq. m per coat")[0]
    assert (g.lo, g.hi, g.per_coat) == (D("0.08"), D("0.1"), True)
    assert tds.consumption("1.2-1.3 kg/mm/m2")[0].key == "kg/sqm/mm"


def test_a_ligature_read_as_a_nul_byte_is_fi_again():
    raw = "For waterproo\x00ng: 22 to 25 sq.ft./kg in 2 coats\u0178 x\x00"
    assert tds.clean(raw) == "For waterproofing: 22 to 25 sq.ft./kg in 2 coats  x"
    assert tds.consumption(tds.clean(raw))[0].coats == 2


def test_the_reader_finds_properties_with_their_standard_and_skips_unit_digits():
    fs = tds.properties(
        "Tensile Strength, 7 days, N/mm2, ASTM D 412 1.5 Elongation at break, % ASTM D 412 >450"
    )
    got = {f.key: (f.lo, f.standard) for f in fs}
    assert got["tensile"] == (D("1.5"), "ASTM D412") and got["elongation"] == (D(450), "ASTM D412")
    assert tds.properties("Tensile Strength, kg/cm2 30")[0].lo == D(30) * D("0.0980665")
    assert tds.product_name("TDS_ZENTRAFIX FLEXI PU (1).pdf") == "ZENTRAFIX FLEXI PU"
    assert (
        tds.brand_of("Technical Data Sheet (Product TDS)/Zentrafix/Roof/TDS_ZENTRAFIX FLEXI PU.pdf")
        == "Zentrafix"
    )


def _pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for ln in lines:
        c.drawString(40, y, ln)
        y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


SHEET = ["ZENTRAFIX FLEXI PU", "Single component polyurethane liquid waterproofing membrane for terraces and roofs.",
         "Elongation at break, %, ASTM D 412 >600", "Tensile strength, N/mm2, ASTM D 412 4.5",
         "Coverage 1.5 kg per sq. m in two coats", "Apply Zentrafix MIEP primer before the membrane.", "Packaging: 20 kg pail"]  # fmt: skip


def test_the_tds_import_previews_matches_saves_and_merges_duplicates(login_as, db):
    p = Product(code="T39-FLEXI", name="Zentrafix Flexi PU", brand="Zentrafix", unit="kg")
    db.add(p)
    db.commit()
    c, h = login_as("planning")
    imp = c.post("/api/spec/tds/imports", headers=h).json()["id"]
    files = [("files", ("TDS_ZENTRAFIX FLEXI PU.pdf", _pdf(SHEET), "application/pdf")),
             ("files", ("TDS_ZENTRAFIX FLEXI PU (1).pdf", _pdf(SHEET), "application/pdf")),
             ("files", ("Elbrite Seal 22.pdf", _pdf([" "]), "application/pdf"))]  # fmt: skip
    paths = '["TDS/Zentrafix/TDS_ZENTRAFIX FLEXI PU.pdf", "TDS/Zentrafix/TDS_ZENTRAFIX FLEXI PU (1).pdf", "TDS/Elbrite/Elbrite Seal 22.pdf"]'
    r = c.post(f"/api/spec/tds/imports/{imp}/files", files=files, data={"paths": paths}, headers=h)
    assert r.status_code == 200, r.text
    docs = r.json()["docs"]
    assert [d["status"] for d in docs] == ["preview", "duplicate", "preview"]
    assert (
        docs[0]["brand"] == "Zentrafix"
        and docs[0]["product_id"] == p.id
        and docs[0]["match"] == "matched"
    )
    assert docs[2]["needs_reading"] is True and docs[2]["match"] == "create"
    n = c.get(f"/api/spec/tds/imports/{imp}", headers=h).json()["counts"]
    assert (
        n["products_read"],
        n["duplicates"],
        n["needs_reading"],
        n["matched"],
        n["to_create"],
    ) == (2, 1, 1, 1, 1)
    facts = {
        (f.kind, f.key): f
        for f in db.scalars(select(TdsFact).where(TdsFact.doc_id == docs[0]["id"]))
    }
    assert (
        facts[("property", "elongation")].lo == D(600)
        and facts[("property", "elongation")].standard == "ASTM D412"
    )
    assert (
        facts[("consumption", "kg/sqm")].lo == D("1.5")
        and facts[("consumption", "kg/sqm")].page == 1
    )
    assert "1.5 kg per sq. m" in facts[("consumption", "kg/sqm")].sentence
    assert ("primer", "yes") in facts and ("pack", "kg") in facts and ("chemistry", "pu") in facts
    # nothing is the product's sheet before the save
    assert db.scalar(select(TdsFact.id).where(TdsFact.product_id == p.id)) is None
    r = c.post(f"/api/spec/tds/imports/{imp}/save", json={"create_all": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == 2 and r.json()["products_created"] == 1
    db.expire_all()
    assert db.scalar(select(Product).where(Product.name == "Elbrite Seal 22")).brand == "Elbrite"
    assert db.scalar(select(TdsFact.id).where(TdsFact.product_id == p.id)) is not None
    assert c.get(f"/api/spec/tds/docs/{docs[0]['id']}/file", headers=h).status_code == 200
    # a newer sheet of the same product replaces the saved one only once confirmed
    imp2 = c.post("/api/spec/tds/imports", headers=h).json()["id"]
    newer = _pdf([*SHEET, "Shore A hardness 70"])
    d2 = c.post(f"/api/spec/tds/imports/{imp2}/files", files=[("files", ("TDS_ZENTRAFIX FLEXI PU.pdf", newer, "application/pdf"))],
                data={"paths": '["TDS/Zentrafix/TDS_ZENTRAFIX FLEXI PU.pdf"]'}, headers=h).json()["docs"][0]  # fmt: skip
    assert d2["replaces_id"] == docs[0]["id"]
    out = c.post(f"/api/spec/tds/imports/{imp2}/save", json={}, headers=h).json()
    assert out["kept_older"] == 1 and db.get(TdsDoc, docs[0]["id"]).status == "saved"


def test_an_edited_fact_is_checked_by_whom_and_keeps_the_value_read(login_as, db):
    c, h = login_as("super_admin")
    imp = c.post("/api/spec/tds/imports", headers=h).json()["id"]
    d = c.post(
        f"/api/spec/tds/imports/{imp}/files",
        files=[("files", ("Arvox Coat.pdf", _pdf(SHEET), "application/pdf"))],
        headers=h,
    ).json()["docs"][0]
    fact = db.scalar(
        select(TdsFact).where(
            TdsFact.doc_id == d["id"], TdsFact.kind == "property", TdsFact.key == "elongation"
        )
    )
    r = c.patch(
        f"/api/spec/tds/facts/{fact.id}",
        json={
            "kind": "property",
            "key": "elongation",
            "lo": "550",
            "hi": None,
            "unit": "%",
            "standard": "ASTM D412",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["checked_by_name"]
        and r.json()["original"]["lo"] == "600.000000"
        and r.json()["lo"] == "550"
    )
    c2, h2 = login_as("estimator")
    assert (
        c2.patch(
            f"/api/spec/tds/facts/{fact.id}", json={"kind": "property"}, headers=h2
        ).status_code
        == 403
    )
    assert (
        c2.get(f"/api/spec/tds/docs/{d['id']}", headers=h2).status_code == 200
    )  # reading is for everyone with the library


def test_a_scanned_sheet_read_with_ai_is_never_saved_without_a_click(login_as, db, monkeypatch):
    c, h = login_as("super_admin")
    imp = c.post("/api/spec/tds/imports", headers=h).json()["id"]
    d = c.post(
        f"/api/spec/tds/imports/{imp}/files",
        files=[("files", ("Corvane Scan.pdf", _pdf([" "]), "application/pdf"))],
        headers=h,
    ).json()["docs"][0]
    assert d["needs_reading"]
    assert (
        c.post(f"/api/spec/tds/docs/{d['id']}/ai-read", headers=h).status_code == 409
    )  # off: manual entry
    monkeypatch.setattr(ai, "enabled", lambda: True)
    monkeypatch.setattr(ai, "page_images", lambda data: ["iVBORw0KGgo="])
    monkeypatch.setattr(
        ai,
        "_post",
        lambda payload: {
            "content": [
                {
                    "type": "text",
                    "text": '[{"kind": "property", "key": "elongation", "lo": 350, "unit": "%", "standard": "ASTM D412", "page": 1, "sentence": "Elongation 350 %"}]',
                }
            ]
        },
    )
    r = c.post(f"/api/spec/tds/docs/{d['id']}/ai-read", headers=h)
    assert r.status_code == 200 and r.json()["proposed"][0]["lo"] == "350"
    assert db.scalar(select(TdsFact.id).where(TdsFact.doc_id == d["id"])) is None
    r = c.post(
        f"/api/spec/tds/docs/{d['id']}/facts",
        json=[r.json()["proposed"][0] | {"source": "ai"}],
        headers=h,
    )
    assert (
        r.status_code == 201
        and r.json()["facts"][0]["source"] == "ai"
        and not r.json()["needs_reading"]
    )


# --- Parts 2 and 4: the consumption master and the options --------------------------------------------


def _priced(db, name, brand, price, unit="kg") -> Product:
    p = Product(code=f"T39-{name[:24]}", name=name, brand=brand, unit=unit)
    db.add(p)
    db.flush()
    db.add(
        ProductPrice(
            product_id=p.id, purchase_rate=D(price), effective_from=ist_today(), source="manual"
        )
    )
    return p


def _sheet_for(db, p: Product, facts: list[dict]) -> None:
    d = TdsDoc(
        brand=p.brand,
        product_name=p.name,
        file_name=f"{p.name}.pdf",
        sha256=p.name.ljust(64, "0")[:64],
        status="saved",
        product_id=p.id,
        match="matched",
    )
    db.add(d)
    db.flush()
    for f in facts:
        db.add(TdsFact(doc_id=d.id, product_id=p.id, **f))


def _pu_world(db) -> dict:
    """One terrace PU work item with three brand options: Zentrafix (elongation 600 %), Arvox (300 %),
    Corvane (its sheet gives none); a primer for each."""
    s = System(
        code="T39-PU",
        name="Invented PU liquid membrane terrace",
        unit="sqm",
        labour_rate=D(40),
        labour_unit="sqm",
        default_margin_percent=D(30),
        area_keys=["terrace"],
    )
    db.add(s)
    db.flush()
    out = {"system": s}
    for i, (brand, elong, per) in enumerate(
        (("Arvox", "300", "1.6"), ("Zentrafix", "600", "1.6"), ("Corvane", None, "1.2"))
    ):
        o = SystemOption(system_id=s.id, brand=brand, is_default=i == 0, sort_order=i)
        db.add(o)
        db.flush()
        coat = _priced(db, f"{brand} Flexi PU", brand, "300")
        primer = _priced(db, f"{brand} Primer", brand, "200")
        _sheet_for(
            db,
            coat,
            [{"kind": "chemistry", "key": "pu"}]
            + (
                [
                    {
                        "kind": "property",
                        "key": "elongation",
                        "lo": D(elong),
                        "unit": "%",
                        "standard": "ASTM D412",
                    }
                ]
                if elong
                else []
            ),
        )
        _sheet_for(db, primer, [{"kind": "chemistry", "key": "primer"}])
        db.add(
            SystemComponent(
                system_id=s.id,
                option_id=o.id,
                product_id=primer.id,
                consumption_per_unit=D("0.2"),
                coats=1,
                source="company_bom",
            )
        )
        db.add(
            SystemComponent(
                system_id=s.id,
                option_id=o.id,
                product_id=coat.id,
                consumption_per_unit=D(per),
                coats=2,
                source="company_bom",
            )
        )
        out[brand] = o
    db.commit()
    db.refresh(s)
    return out


def test_a_line_asking_elongation_400_ranks_600_above_not_stated_and_300(db):
    w = _pu_world(db)
    chips = keypoints.parse(
        "Two coats PU liquid membrane on terrace, elongation at break > 400 % ASTM D 412, Arvox or equivalent",
        "sqm",
        D(100),
        ["Arvox", "Zentrafix", "Corvane"],
    )
    out = suggest.suggest(db, chips, with_cost=True)
    brands = [o["brand"] for o in out["options"]]
    # the make named comes first even with a cross; then the 600 %, then the one with no value
    assert brands == ["Arvox", "Zentrafix", "Corvane"]
    states = {
        o["brand"]: next(c for c in o["checks"] if c["point"] == "prop:elongation")
        for o in out["options"]
    }
    assert (
        states["Zentrafix"]["state"] == "yes"
        and states["Arvox"]["state"] == "no"
        and states["Corvane"]["state"] == "not_stated"
    )
    assert states["Corvane"]["note"] == "not stated in TDS"
    # no make named: the 600 % is first, the one with no value next, the 300 % last (shown, never hidden)
    chips = keypoints.parse(
        "PU liquid membrane on terrace, elongation at break > 400 %",
        "sqm",
        D(100),
        ["Arvox", "Zentrafix", "Corvane"],
    )
    assert [o["brand"] for o in suggest.suggest(db, chips, with_cost=False)["options"]] == [
        "Zentrafix",
        "Corvane",
        "Arvox",
    ]
    z = next(o for o in out["options"] if o["brand"] == "Zentrafix")
    assert [r["step"] for r in z["rows"]] == ["primer", "coat"] and z["rows"][1]["per_small"] == D(
        "1.6"
    ) / D("10.7639")
    assert (
        z["cost"]["material"] == D("0.2") * 200 + D("1.6") * 300 and z["cost"]["rate"] is not None
    )
    assert w["Zentrafix"].id == z["option_id"]


def test_a_minimum_kg_per_sqm_is_warned_and_wins_in_the_working(login_as, db):
    w = _pu_world(db)
    t = Tender(code="T-2026-39A01", name="Invented spec tender", status="draft")
    db.add(t)
    db.flush()
    line = BoqLine(
        tender_id=t.id,
        description="PU liquid membrane on terrace, minimum 1.5 kg/sqm in two coats",
        unit="sqft",
        qty=D("1076.39"),
        sort_order=1,
    )
    db.add(line)
    db.commit()
    c, h = login_as("estimator")
    out = c.get(f"/api/spec/lines/boq/{line.id}/options", headers=h).json()
    corvane = next(o for o in out["options"] if o["brand"] == "Corvane")
    kg = next(x for x in corvane["checks"] if x["point"] == "kg_sqm")
    assert kg["state"] == "no" and "below the line's minimum, the working uses 1.5" in kg["note"]
    assert out["options"][-1]["brand"] == "Corvane"  # below the minimum: after those that meet it
    r = c.post(
        f"/api/spec/lines/boq/{line.id}/pick",
        json={"system_id": w["system"].id, "option_id": w["Corvane"].id},
        headers=h,
    )
    assert r.status_code == 200, r.text
    subs = r.json()["sub_lines"]
    coat = next(x for x in subs["rows"] if x["product"] == "Corvane Flexi PU")
    assert (
        D(coat["consumption"]) == D("1.5") and "client's minimum" in coat["source"]
    )  # not the BOM's 1.2
    assert D(subs["qty_in_unit"]) == D(100)  # 1076.39 sq ft = 100 sqm
    assert D(coat["qty"]) == D("150.000")
    assert [x["step"] for x in subs["rows"]] == ["primer", "coat"]
    db.expire_all()
    assert (
        db.get(BoqLine, line.id).manufacturer == "Corvane"
        and "coat: Corvane Flexi PU" in db.get(BoqLine, line.id).our_product
    )
    # a step changed by hand says so, and goes back to the calculated figure
    r = c.put(
        f"/api/spec/lines/boq/{line.id}/sub-lines/{coat['id']}",
        json={"consumption": "1.8"},
        headers=h,
    )
    assert (
        next(x for x in r.json()["sub_lines"]["rows"] if x["id"] == coat["id"])["changed"] is True
    )
    r = c.put(
        f"/api/spec/lines/boq/{line.id}/sub-lines/{coat['id']}",
        json={"consumption": None},
        headers=h,
    )
    back = next(x for x in r.json()["sub_lines"]["rows"] if x["id"] == coat["id"])
    assert back["changed"] is False and D(back["consumption"]) == D("1.5")
    # an alternate is kept beside it; the working is built from the first pick only
    r = c.post(
        f"/api/spec/lines/boq/{line.id}/pick",
        json={"system_id": w["system"].id, "option_id": w["Zentrafix"].id, "rank": 2},
        headers=h,
    )
    assert sorted(p["rank"] for p in r.json()["picks"]) == [1, 2]
    assert len(db.scalars(select(RateGroup)).all()) == 1


def test_no_option_meets_a_point_says_which_and_offers_the_closest(db):
    _pu_world(db)
    chips = keypoints.parse(
        "PU membrane on terrace, elongation at break > 900 %, tensile > 6 N/mm2", "sqm", None, []
    )
    out = suggest.suggest(db, chips, with_cost=False)
    assert "No option meets elongation ≥ 900 %" in out["gaps"]
    assert any(
        g.startswith("No option meets tensile strength ≥ 6") and "the TDS do not state it" in g
        for g in out["gaps"]
    )
    assert len(out["options"]) == 3 and not any(o["meets_all"] for o in out["options"])


def test_a_named_make_without_equivalent_marks_the_others_for_client_approval(db):
    _pu_world(db)
    chips = keypoints.parse(
        EXAMPLE_2.replace("Zentrafix", "Arvox"), "Nos", D(10), ["Arvox", "Zentrafix", "Corvane"]
    )
    chips = [c for c in chips if c["kind"] != "area"]  # the work item here is a terrace one
    out = suggest.suggest(db, chips, with_cost=False)
    make = {
        o["brand"]: next(c for c in o["checks"] if c["point"] == "make") for o in out["options"]
    }
    assert out["options"][0]["brand"] == "Arvox" and make["Arvox"]["state"] == "yes"
    assert (
        make["Zentrafix"]["state"] == "approval"
        and make["Zentrafix"]["note"] == "needs client approval"
    )


def test_the_consumption_master_keeps_every_change_and_an_issued_estimate_keeps_its_figure(
    login_as, db
):
    w = _pu_world(db)
    s = w["system"]
    coat = next(
        c
        for c in s.components
        if c.option_id == w["Zentrafix"].id and c.product.name == "Zentrafix Flexi PU"
    )
    t = Tender(code="T-2026-39A02", name="Invented estimate check", status="draft")
    db.add(t)
    db.flush()
    e = Estimate(code="EST-T39A", tender_id=t.id, title="Invented terrace")
    db.add(e)
    db.flush()
    db.add(
        EstimateArea(
            estimate_id=e.id,
            source="manual",
            name="Invented terrace",
            floor_sqm=D(100),
            periphery_m=D(0),
        )
    )
    db.flush()
    est.add_system(db, e, s, w["Zentrafix"].id)
    e.snapshot, e.status = est.freeze(db, e), "issued"
    db.commit()
    issued = {ln.product.name: ln.qty for ln in est.worked(db, e)}
    assert issued["Zentrafix Flexi PU"] == D(160)

    c, h = login_as("estimator")
    assert c.get("/api/spec/master?q=zentrafix", headers=h).json()["items"][0]["id"] == s.id
    assert (
        c.put(
            f"/api/spec/master/{s.id}/components/{coat.id}",
            json={"consumption_per_unit": "2", "reason": "site trial"},
            headers=h,
        ).status_code
        == 403
    )
    c, h = login_as("planning")
    assert (
        c.put(
            f"/api/spec/master/{s.id}/components/{coat.id}",
            json={"consumption_per_unit": "2"},
            headers=h,
        ).status_code
        == 422
    )  # a reason is asked
    r = c.put(
        f"/api/spec/master/{s.id}/components/{coat.id}",
        json={"consumption_per_unit": "2", "reason": "site trial at 2 kg"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    ch = db.scalar(select(ConsumptionChange).where(ConsumptionChange.component_id == coat.id))
    assert (ch.field, ch.old, ch.new, ch.reason) == (
        "consumption_per_unit",
        "1.6",
        "2",
        "site trial at 2 kg",
    ) and ch.changed_by is not None
    item = c.get(f"/api/spec/master/{s.id}", headers=h).json()
    # planning sees prices, cost and the selling rate here (consumption.cost), not tender.margin
    assert item["history"][0]["reason"] == "site trial at 2 kg" and item["can_cost"] is True
    zo = next(o for o in item["options"] if o["brand"] == "Zentrafix")
    assert zo["cost"]["rate"] is not None and zo["rows"][0]["price_per_unit"] is not None
    db.expire_all()
    e = db.get(Estimate, e.id)
    assert {ln.product.name: ln.qty for ln in est.worked(db, e)}["Zentrafix Flexi PU"] == D(
        160
    )  # as issued
    assert {ln.product.name: ln.qty for ln in est.live_worked(db, e)}["Zentrafix Flexi PU"] == D(
        200
    )  # the library moved on


def test_the_master_copies_an_option_to_another_brand_and_swaps_products(login_as, db):
    w = _pu_world(db)
    s = w["system"]
    duramix = _priced(db, "Duramix Flexi PU", "Duramix", "280")
    db.commit()
    zcoat = next(
        c
        for c in s.components
        if c.option_id == w["Zentrafix"].id and c.product.name == "Zentrafix Flexi PU"
    )
    c, h = login_as("planning")
    r = c.post(
        f"/api/spec/master/{s.id}/options/{w['Zentrafix'].id}/copy",
        json={"brand": "Duramix", "swaps": {str(zcoat.product_id): duramix.id}},
        headers=h,
    )
    assert r.status_code == 201, r.text
    db.expire_all()
    o = db.get(SystemOption, r.json()["id"])
    names = sorted(x.product.name for x in db.get(System, s.id).components if x.option_id == o.id)
    assert names == ["Duramix Flexi PU", "Zentrafix Primer"]
    assert (
        c.post(f"/api/spec/master/{s.id}/options", json={"brand": "duramix"}, headers=h).status_code
        == 422
    )  # already one
    assert (
        c.post(
            f"/api/spec/master/products/{duramix.id}/price", json={"rate": "290"}, headers=h
        ).status_code
        == 201
    )  # planning updates rates here
    c2, h2 = login_as("site_engineer")
    assert (
        c2.post(
            f"/api/spec/master/products/{duramix.id}/price", json={"rate": "290"}, headers=h2
        ).status_code
        == 403
    )


def test_the_master_warns_when_the_bom_is_outside_the_tds_range(db):
    w = _pu_world(db)
    z = next(
        c
        for c in w["system"].components
        if c.option_id == w["Zentrafix"].id and c.product.name == "Zentrafix Flexi PU"
    )
    _sheet_for(
        db,
        z.product,
        [
            {
                "kind": "consumption",
                "key": "kg/sqm",
                "lo": D("0.4"),
                "hi": D("0.5"),
                "per_coat": True,
                "coats": 2,
                "text": "0.4-0.5 kg/sqm per coat",
            }
        ],
    )
    db.commit()
    from app.spec import master  # noqa: PLC0415

    item = master.items(db, system_id=w["system"].id)[0]
    zo = next(o for o in item["options"] if o["brand"] == "Zentrafix")
    row = next(r for r in zo["rows"] if r["product"] == "Zentrafix Flexi PU")
    assert (
        row["tds_range"]["lo"] == D("0.8") and row["outside_tds"] is True
    )  # 0.4-0.5 per coat × 2 coats; the BOM's 1.6 is outside
    assert "outside the TDS 0.800–1.000" in zo["warnings"][0]


@pytest.mark.parametrize("kind", ["boq"])
def test_key_points_edited_by_a_person_are_kept_until_the_words_change(login_as, db, kind):
    t = Tender(code="T-2026-39A03", name="Invented chips", status="draft")
    db.add(t)
    db.flush()
    line = BoqLine(
        tender_id=t.id,
        description="Two coats acrylic coating on terrace",
        unit="sqm",
        qty=D(10),
        sort_order=1,
    )
    db.add(line)
    db.commit()
    c, h = login_as("estimator")
    pts = c.get(f"/api/spec/lines/{kind}/{line.id}/points", headers=h).json()
    assert pts["kept"] is False
    chips = [x for x in pts["chips"] if x["kind"] != "coats"] + [
        {"kind": "coats", "label": "3 coats", "value": {"coats": 3}}
    ]
    r = c.put(f"/api/spec/lines/{kind}/{line.id}/points", json={"chips": chips}, headers=h)
    assert r.status_code == 200 and r.json()["kept"] is True
    assert next(x for x in r.json()["chips"] if x["kind"] == "coats")["source"] == "user"
    line.description = "Three coats acrylic coating on terrace"
    db.commit()
    assert c.get(f"/api/spec/lines/{kind}/{line.id}/points", headers=h).json()["kept"] is False
    assert db.scalar(select(SpecPick.id)) is None


def test_real_line_shapes_read_right():
    """Shapes seen on real BOQs: the area named first wins over a weak word, a value before its
    property, a primer's coverage is not the system's minimum, "standard make" names no brand."""
    chips = keypoints.parse(
        "TANK WATERPROOFING : 2 coats of 2 component cementitious coating, joints sealed, on floor and walls",
        "Sqm",
        None,
        ["Standard", "Arvox"],
    )
    assert _by(chips, "area")[0]["value"]["area"] == "oht"
    assert _by(chips, "system")[0]["value"]["type"] == "cementitious"
    chips = keypoints.parse(
        "Flexible acrylic membrane with > 200% Elongation at Break, > 2N/mm2 Tensile Strength, of standard make",
        "sqm",
        None,
        ["Standard", "Arvox"],
    )
    props = {c["value"]["property"]: c["value"]["min"] for c in _by(chips, "property")}
    assert props == {"elongation": "200", "tensile": "2"}
    assert _by(chips, "make")[0]["value"]["brands"] == []
    chips = keypoints.parse(
        "Torch applied 4 mm APP membrane over primer @ 0.25 kg/sqm on the terrace", "sqm", None, []
    )
    assert _by(chips, "kg_sqm") == [] and _by(chips, "area")[0]["value"]["area"] == "terrace"
    chips = keypoints.parse(
        "Two component PU based membrane, grout around the outlets, grout at the corners",
        "sqm",
        None,
        [],
    )
    assert _by(chips, "system")[0]["value"]["type"] == "pu"
    assert (
        _by(
            keypoints.parse("Expansion Jt. treatment with a liquid membrane band", "rmt", None, []),
            "area",
        )[0]["value"]["area"]
        == "expansion_joint"
    )


def test_waterproofing_is_not_a_roof():
    chips = keypoints.parse(
        "Supplying and installing waterproofing treatment for the raft using a fully bonded HDPE sheet",
        "sqm",
        None,
        [],
    )
    assert _by(chips, "area")[0]["value"]["area"] == "raft"
    chips = keypoints.parse(
        "Acrylic membrane on the terrace with crack bridging of 2 mm", "sqm", None, []
    )
    assert _by(chips, "area")[0]["value"]["area"] == "terrace"


# --- 39b: the area from the section heading ----------------------------------------------------------


def _area(text, unit="sqm", context=None):
    chips = keypoints.parse(text, unit, None, ["Arvox"], context)
    a = _by(chips, "area")
    return (a[0]["value"]["area"], a[0]["value"]["from"]) if a else (None, None)


def _type(text, unit="sqm", context=None):
    return _by(keypoints.parse(text, unit, None, ["Arvox"], context), "system")[0]["value"]["type"]


@pytest.mark.parametrize(
    ("text", "unit", "context", "area", "said"),
    [
        # no area in the line: the section heading's
        (
            "Provide and apply two component PU based root resistant membrane @ 1.9 kg/m2",
            "sqm",
            ["8 PODIUM WATERPROOFING WITH TWO COMPONENT PU :"],
            "podium",
            "heading",
        ),
        # a weak word in the line ("on the floor") does not beat the section
        (
            "Two component acrylic polymer cementitious coating on the floor and walls up to 300 mm",
            "sqm",
            ["Toilets / kitchen / balcony waterproofing"],
            "toilet",
            "heading",
        ),
        # an area named in passing ("terrace drain") keeps the section's
        (
            "Sealing around the terrace drain pipes passing through the slab",
            "sqm",
            ["Toilet waterproofing"],
            "toilet",
            "heading",
        ),
        # a joint line per rmt under a joint heading is that joint, whatever tank it mentions
        (
            "Supply and fix a swellable water stop 20 x 15 mm, safe with potable water tanks",
            "rmt",
            ["TREATMENT OF CONSTRUCTION JOINTS ON RAFT & RETAINING WALL"],
            "construction_joint",
            "heading",
        ),
        # in a basement, the heading says raft or retaining wall
        (
            "Fully bonded HDPE sheet on the RCC wall / retaining wall before the raft is cast",
            "sqm",
            ["7 RETAINING WALL (CONFINED) WATERPROOFING :"],
            "retaining_wall",
            "heading",
        ),
        # no heading: raft when the line names it among basement parts
        (
            "Crystalline slurry to the diaphragm walls of the basement, swell bar at the junction of raft and wall",
            "sqm",
            [],
            "raft",
            "line",
        ),
        # a deck slab is a roof
        (
            "Flexible acrylic membrane with > 200% elongation and crack bridging of 2 mm",
            "sqm",
            ["WATER PROOFING TREATMENT ON DECK SLAB"],
            "terrace",
            "heading",
        ),
        # the line's own area in its head wins over the section's
        (
            "Terrace: PU membrane two coats over the existing tiles",
            "sqm",
            ["Toilet waterproofing"],
            "terrace",
            "line",
        ),
        # nothing says it: the area the system usually is
        (
            "Providing and laying 4 mm thick APP modified bituminous membrane by gas torching",
            "sqm",
            ["DETAIL DESCRIPTION"],
            "terrace",
            "system",
        ),
        # an outlet line per nos keeps its own area in a toilet section
        (
            "PIPE INLET / OUTLET TREATMENT (at all locations): sealing the pipe inserts with a 1.5 mm thick tape",
            "nos",
            ["Toilets / kitchen waterproofing"],
            "pipe_outlet",
            "line",
        ),
        # a joint line per rmt: the joint heading, though a tank heading comes first
        (
            "Swellable water bar 20 x 10 mm fixed with adhesive",
            "rmt",
            ["UG TANK / SUMP / STP TANKS", "TREATMENT OF CONSTRUCTION JOINTS ON RAFT"],
            "construction_joint",
            "heading",
        ),
        # an expansion joint written short
        (
            "Expansion Jt. treatment with a polyester resin base flexible membrane in two layers",
            "rmt",
            [],
            "expansion_joint",
            "line",
        ),
    ],
)
def test_the_area_comes_from_the_line_then_its_heading(text, unit, context, area, said):
    assert _area(text, unit, context) == (area, said)


def test_a_liquid_membrane_named_by_its_system_is_not_a_repair_mortar():
    assert (
        _type(
            "Expansion Jt. treatment with a polyester resin base flexible membrane in two layers",
            "rmt",
        )
        == "liquid_membrane"
    )
    chips = keypoints.parse("P/A liquid applied flexible membrane in two layers", "rmt", None, [])
    assert _by(chips, "system")[0]["label"] == "liquid membrane"
    text = "Toilet area: single component liquid applied membrane by roller, pipe holes filled with non-shrink grout, grout at the corners"
    assert _type(text) == "liquid_membrane"
    # a liquid membrane line takes a PU work item
    assert vocab.same_family("liquid_membrane", "pu") and not vocab.same_family(
        "liquid_membrane", "crystalline"
    )
    # a PU sheet that also says "liquid applied membrane" stays PU
    assert vocab.main_type("Arvox PU: a polyurethane liquid applied membrane") == "pu"


def test_a_tender_line_takes_its_section_heading(login_as, db):
    from app.tenders.models import BoqSection  # noqa: PLC0415

    t = Tender(code="T-2026-39B01", name="Invented headings", status="draft")
    db.add(t)
    db.flush()
    sec = BoqSection(tender_id=t.id, title="PODIUM WATERPROOFING", sort_order=1)
    db.add(sec)
    db.flush()
    db.add(BoqLine(tender_id=t.id, section_id=sec.id, description="Planter boxes", sort_order=1))
    line = BoqLine(
        tender_id=t.id,
        section_id=sec.id,
        description="Two component PU membrane, 2 coats",
        unit="sqm",
        qty=D(50),
        sort_order=2,
    )
    db.add(line)
    db.commit()
    c, h = login_as("estimator")
    chips = c.get(f"/api/spec/lines/boq/{line.id}/points", headers=h).json()["chips"]
    area = _by(chips, "area")[0]
    assert (
        area["value"] == {"area": "podium", "use": "podium", "from": "heading"}
        and area["words"] == "PODIUM WATERPROOFING"
    )


# --- 39b: matching before creating, near-duplicates as a group ----------------------------------------


def test_names_match_without_pack_new_grade_or_punctuation():
    from app.spec import tds_import  # noqa: PLC0415

    k = tds_import.norm_key
    assert k("Zentrafix", "Zentrafix Fast-Flex Ultra 20 kg (new)") == "fastflexultra"
    assert k("Zentrafix", "ZENTRAFIXV Fast Flex Grade 2") == "fastflex"
    assert k("Arvox", "Arvox Seal 60") == "seal60"  # a number that is not a pack stays


def test_near_duplicates_are_one_group_with_a_pick_and_only_unmatched_sheets_are_new(login_as, db):
    db.add(Product(code="T39B-SEAL", name="Arvox Roofseal 20 Kg", brand="Arvox", unit="kg"))
    db.commit()
    c, h = login_as("planning")
    imp = c.post("/api/spec/tds/imports", headers=h).json()["id"]
    names = [
        "Zentrafix Fast Flex.pdf",
        "Zentrafix Fastflex Ultra.pdf",
        "ZENTRAFIXV Fast Flex.pdf",
        "Arvox Roofseal (new).pdf",
        "Arvox Primer 7.pdf",
    ]
    texts = [
        [f"{n} sheet {i}", "Coverage 1.5 kg per sq. m in two coats"] for i, n in enumerate(names)
    ]
    files = [("files", (n, _pdf(t), "application/pdf")) for n, t in zip(names, texts, strict=True)]
    paths = [f"TDS/{'Zentrafix' if n.startswith('Z') else 'Arvox'}/{n}" for n in names]
    r = c.post(
        f"/api/spec/tds/imports/{imp}/files",
        files=files,
        data={"paths": __import__("json").dumps(paths)},
        headers=h,
    )
    assert r.status_code == 200, r.text
    view = c.get(f"/api/spec/tds/imports/{imp}", headers=h).json()
    by = {d["file_name"]: d for d in view["docs"]}
    assert by["Arvox Roofseal (new).pdf"]["match"] == "matched"  # pack and "new" left out
    group = {by[n]["group"] for n in names[:3]}
    assert len(group) == 1 and None not in group and by["Arvox Primer 7.pdf"]["group"] is None
    n = view["counts"]
    assert (n["matched"], n["grouped"], n["in_groups"], n["new"]) == (
        1,
        1,
        3,
        2,
    )  # the group counts once
    keep = by["Zentrafix Fastflex Ultra.pdf"]["id"]
    out = c.post(
        f"/api/spec/tds/imports/{imp}/save", json={"keep": {str(group.pop()): keep}}, headers=h
    ).json()
    assert out["merged"] == 2 and out["products_created"] == 0  # nothing ticked: no product made
    db.expire_all()
    assert db.get(TdsDoc, by["Zentrafix Fast Flex.pdf"]["id"]).duplicate_of_id == keep


# --- 39b: a pick puts the rate on the line -------------------------------------------------------------


def test_a_pick_prices_a_line_with_no_rate_and_asks_before_changing_one(login_as, db):
    w = _pu_world(db)
    t = Tender(code="T-2026-39B02", name="Invented rates", status="draft")
    db.add(t)
    db.flush()
    free = BoqLine(
        tender_id=t.id,
        description="PU liquid membrane on terrace",
        unit="sqm",
        qty=D(10),
        sort_order=1,
    )
    priced = BoqLine(
        tender_id=t.id,
        description="PU liquid membrane on podium",
        unit="sqm",
        qty=D(10),
        sort_order=2,
        rate=D(500),
    )
    db.add_all([free, priced])
    db.commit()
    c, h = login_as("estimator")
    r = c.post(
        f"/api/spec/lines/boq/{free.id}/pick",
        json={"system_id": w["system"].id, "option_id": w["Zentrafix"].id},
        headers=h,
    ).json()
    assert r["rate"]["applied"] is True and r["rate"]["old"] is None
    db.expire_all()
    assert (
        db.get(BoqLine, free.id).rate == D(r["rate"]["new"])
        and db.get(BoqLine, free.id).status == "priced"
    )
    r = c.post(
        f"/api/spec/lines/boq/{priced.id}/pick",
        json={"system_id": w["system"].id, "option_id": w["Zentrafix"].id},
        headers=h,
    ).json()
    assert (
        r["rate"]["ask"] is True and r["rate"]["applied"] is False and D(r["rate"]["old"]) == D(500)
    )
    db.expire_all()
    assert db.get(BoqLine, priced.id).rate == D(500)  # not changed without asking
    r = c.post(f"/api/spec/lines/boq/{priced.id}/apply-rate", headers=h)
    assert r.status_code == 200 and D(r.json()["rate"]) != D(500)


# --- 39b: brand options with no brand's name ------------------------------------------------------------


def test_generic_brand_options_are_listed_and_renamed_with_a_reason(login_as, db):
    w = _pu_world(db)
    s = w["system"]
    o = SystemOption(system_id=s.id, brand="Standard (2)", sort_order=9)
    db.add(o)
    db.commit()
    c, h = login_as("planning")
    listed = c.get("/api/spec/master", headers=h).json()["generic_brands"]
    assert [x["brand"] for x in listed] == ["Standard (2)"]
    assert (
        c.patch(
            f"/api/spec/master/{s.id}/options/{o.id}", json={"brand": "SC"}, headers=h
        ).status_code
        == 422
    )
    assert (
        c.patch(
            f"/api/spec/master/{s.id}/options/{o.id}", json={"brand": "Arvox"}, headers=h
        ).status_code
        == 422
    )  # already one
    r = c.patch(
        f"/api/spec/master/{s.id}/options/{o.id}",
        json={"brand": "Duramix", "reason": "the BOM's maker"},
        headers=h,
    )
    assert (
        r.status_code == 200 and c.get("/api/spec/master", headers=h).json()["generic_brands"] == []
    )
    ch = db.scalar(select(ConsumptionChange).where(ConsumptionChange.field == "brand"))
    assert (ch.old, ch.new, ch.reason) == ("Standard (2)", "Duramix", "the BOM's maker")
