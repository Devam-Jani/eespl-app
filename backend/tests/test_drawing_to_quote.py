# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Prompt 39: from the drawing to the 3D model, the quotation and its rate working. A synthetic DXF
made here with ezdxf (company drawings are never committed): a first floor with two toilets (300 mm
sunk) and an "FFL +3.000" level, a terrace 20 x 15 m with a 2 x 2 m shaft and a 300 mm upturn, a
balcony left unmapped. Invented products and brands only."""

import io
from decimal import Decimal

import ezdxf
import pytest
from sqlalchemy import select

from app.building import service as building
from app.costing.models import RateGroup, RateGroupLine
from app.drawquote.models import DrawQuote, QuoteLineArea
from app.estimate import rules
from app.masters.models import Product, ProductPrice, System, SystemComponent, SystemOption
from app.quotations.models import Quotation
from app.sites.models import Site, SiteNode
from app.survey.models import AreaType
from app.takeoff.models import CadArea, CadFile
from app.timefmt import ist_today
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_takeoff import read, upload

D = Decimal


def make_dxf(terrace_h: float = 15.0, balcony: bool = True) -> bytes:
    """mm. A FIRST FLOOR PLAN with two toilets and FFL +3.000; a TERRACE PLAN with the terrace,
    its shaft and its upturn note; each plan in a frame with its title."""
    k = 1000.0
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for layer in ("A-ROOM", "A-TEXT", "A-FRAME"):
        doc.layers.add(layer)

    def rect(x, y, w, h, layer="A-ROOM"):
        msp.add_lwpolyline(
            [
                (x * k, y * k),
                ((x + w) * k, y * k),
                ((x + w) * k, (y + h) * k),
                (x * k, (y + h) * k),
            ],
            close=True,
            dxfattribs={"layer": layer},
        )

    def text(t, x, y, h=0.2):
        msp.add_text(t, dxfattribs={"layer": "A-TEXT", "insert": (x * k, y * k), "height": h * k})

    # first floor: frame, title, two toilets, the level
    rect(-2, -4, 16, 12, "A-FRAME")
    text("FIRST FLOOR PLAN", 2, -3, 0.4)
    text("FFL +3.000", 9, 6)
    for x in (0, 4):
        rect(x, 0, 2.4, 1.8)
        text("TOILET", x + 0.5, 1.0)
        text("300 MM SUNK", x + 0.5, 0.4, 0.1)
    if balcony:
        rect(8, 0, 3, 1.5)
        text("BALCONY", 8.5, 0.7)
    # terrace: frame, title, the terrace with its shaft
    rect(28, -4, 26, 26, "A-FRAME")
    text("TERRACE PLAN", 32, -3, 0.4)
    rect(30, 0, 20, terrace_h)
    text("TERRACE", 33, 3)
    text("300 MM UPTURN WATER PROOFING", 33, 2.5, 0.1)
    rect(40, 6, 2, 2)
    text("SHAFT", 40.5, 7)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def _priced(db, name, brand, price, unit="kg") -> Product:
    p = Product(code=f"T39D-{name[:22]}", name=name, brand=brand, unit=unit)
    db.add(p)
    db.flush()
    db.add(
        ProductPrice(
            product_id=p.id, purchase_rate=D(price), effective_from=ist_today(), source="manual"
        )
    )
    return p


@pytest.fixture
def plot(world, db):
    """The site's places (Tower A: floor 1 with two toilets, the terrace), the area types with
    their default systems, and the systems with invented products and prices."""
    site = db.get(Site, world["site"])
    tower = SiteNode(site_id=site.id, kind="tower", name="Tower A")
    db.add(tower)
    db.flush()
    f0 = SiteNode(
        site_id=site.id,
        parent_id=tower.id,
        kind="floor",
        name="Ground floor",
        sort_order=0,
        level_no=0,
    )
    f1 = SiteNode(
        site_id=site.id, parent_id=tower.id, kind="floor", name="Floor 1", sort_order=1, level_no=1
    )
    db.add_all([f0, f1])
    db.flush()
    t1 = SiteNode(site_id=site.id, parent_id=f1.id, kind="toilet", name="Toilet 1")
    t2 = SiteNode(site_id=site.id, parent_id=f1.id, kind="toilet", name="Toilet 2")
    terrace = SiteNode(site_id=site.id, parent_id=tower.id, kind="terrace", name="Main terrace")
    db.add_all([t1, t2, terrace])
    db.flush()
    pu = System(
        code="T39D-PU",
        name="Invented PU terrace system",
        unit="sqm",
        labour_rate=D(40),
        labour_unit="sqm",
        default_margin_percent=D(25),
        area_keys=["terrace"],
    )
    cem = System(
        code="T39D-CEM",
        name="Invented cementitious toilet system",
        unit="sqm",
        labour_rate=D(30),
        labour_unit="sqm",
        default_margin_percent=D(25),
        area_keys=["toilet"],
    )
    db.add_all([pu, cem])
    db.flush()
    for s, brand, items in ((pu, "Arvox", [("Arvox Primer", "200", "0.2"), ("Arvox Flexi PU", "300", "1.5")]),
                            (pu, "Zentrafix", [("Zentrafix Primer", "210", "0.2"), ("Zentrafix PU Coat", "280", "1.6")]),
                            (cem, "Arvox", [("Arvox Cemcoat 2K", "90", "2.0")])):  # fmt: skip
        o = SystemOption(
            system_id=s.id, brand=brand, is_default=not s.options, sort_order=len(s.options)
        )
        s.options.append(o)
        db.flush()
        for name, price, per in items:
            p = _priced(db, name, brand, price)
            s.components.append(
                SystemComponent(
                    system_id=s.id,
                    option_id=o.id,
                    product_id=p.id,
                    consumption_per_unit=D(per),
                    source="company_bom",
                )
            )
    types = {}
    for name, system in (("Terrace", pu), ("Toilet / bathroom", cem), ("Balcony", None)):
        at = db.scalar(select(AreaType).where(AreaType.name == name))
        if at is None:
            at = AreaType(name=name)
            db.add(at)
        at.default_system_id = system.id if system else None
        at.default_upturn_mm = 0
        types[name] = at
    db.commit()
    return {"site": site.id, "client": world["client"], "f0": f0.id, "f1": f1.id, "t1": t1.id, "t2": t2.id, "terrace": terrace.id, "pu": pu, "cem": cem,
            "types": {k: v.id for k, v in types.items()}}  # fmt: skip


def _map(c, h, db, fid, plot):
    by_name: dict[str, list[CadArea]] = {}
    for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == fid).order_by(CadArea.x)):
        by_name.setdefault(a.name, []).append(a)
    for a, node in zip(by_name["TOILET"], (plot["t1"], plot["t2"]), strict=True):
        r = c.put(
            f"/api/takeoff/areas/{a.id}",
            json={"node_id": node, "area_type_id": plot["types"]["Toilet / bathroom"]},
            headers=h,
        )
        assert r.status_code == 200, r.text
    r = c.put(
        f"/api/takeoff/areas/{by_name['TERRACE'][0].id}",
        json={"node_id": plot["terrace"], "area_type_id": plot["types"]["Terrace"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    return by_name


def test_the_shared_rule_works_the_terrace_and_the_toilet_out():
    terrace = rules.area_quantity(300, 78, cutout_sqm=4, upturn_m=D("0.3"))
    assert (terrace.net_floor_sqm, terrace.upturn_sqm, terrace.total_sqm) == (
        D(296),
        D("23.40"),
        D("319.40"),
    )
    assert (
        terrace.formula("Terrace (L7)")
        == "Terrace (L7): (300.00 − 4.00 cut-outs) floor + 78.00 rmt × 0.30 upturn = 319.40 sqm"
    )
    toilet = rules.area_quantity(D("4.32"), D("8.4"), sunk_m=D("0.3"))
    assert (toilet.sunk_sqm, toilet.total_sqm) == (D("2.52"), D("6.84"))
    up, why = rules.upturn_height(None, None, 300, 300, D("0.3"))
    assert up == 0 and why.startswith("sunk")


def test_the_drawing_makes_the_quotation_and_its_working_with_traceable_quantities(boss, plot, db):
    c, h = boss
    did, rev = upload(c, h, plot["site"], make_dxf(), title="Invented tower plans")
    f = read(c, h, rev)
    assert f["status"] == "ready", f
    areas = _map(c, h, db, f["id"], plot)
    terrace = areas["TERRACE"][0]
    assert (
        terrace.outline_source == "drawing"
        and D(terrace.traced_area_sqm) == D(300)
        and D(terrace.holes_sqm) == D(4)
    )
    assert D(terrace.traced_perimeter_m) + D(terrace.holes_perimeter_m) == D(
        78
    ) and terrace.upturn_mm == D(300)
    toilet = areas["TOILET"][0]
    assert D(toilet.traced_area_sqm) == D("4.32") and D(toilet.sunk_m) == D("0.3")

    # the floor heights come from the drawing's level text
    cad = db.get(CadFile, f["id"])
    data = building.draft(db, db.get(Site, plot["site"]), cad)
    ff = next(t for t in data["floor_types"] if t["plan"] == "FIRST FLOOR PLAN")
    assert ff["level_m"] == 3.0
    rows = {r["level"]: r for r in building.elevations(data)}
    assert (rows[1]["elevation_m"], rows[1]["level_source"]) == (3.0, "drawing")
    assert (rows[0]["elevation_m"], rows[0]["height_m"]) == (0.0, 3.0)

    # start: one item per area type, the default systems pre-ticked; the balcony blocks the button
    r = c.post(
        f"/api/drawquote/sites/{plot['site']}/runs",
        json={"cad_file_id": f["id"], "client_id": plot["client"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    run = c.get(f"/api/drawquote/runs/{rid}", headers=h).json()
    items = {i["name"]: i for i in run["items"]}
    assert set(items) == {"Terrace", "Toilet / bathroom"}
    t = items["Terrace"]
    assert (
        D(t["total_sqm"]) == D("319.40")
        and t["areas"][0]["formula"]
        == "TERRACE (TERRACE PLAN): (300.00 − 4.00 cut-outs) floor + 78.00 rmt × 0.30 upturn = 319.40 sqm"
    )
    assert [p["system_id"] for p in t["picks"]] == [plot["pu"].id] and any(
        o["picked"] for o in t["options"]
    )
    loo = items["Toilet / bathroom"]
    assert [D(a["total_sqm"]) for a in loo["areas"]] == [
        D("6.84"),
        D("6.84"),
    ]  # 4.32 floor + 8.4 × 0.30 sunk walls
    assert any("BALCONY" in b for b in run["blockers"])
    r = c.post(f"/api/drawquote/runs/{rid}/make", headers=h)
    assert r.status_code == 409 and any("BALCONY" in x for x in r.json()["detail"]["reasons"])
    balcony = areas["BALCONY"][0]
    assert (
        c.put(
            f"/api/drawquote/runs/{rid}/areas/{balcony.id}/exclude", json={"reason": "x"}, headers=h
        ).status_code
        == 422
    )
    run = c.put(
        f"/api/drawquote/runs/{rid}/areas/{balcony.id}/exclude",
        json={"reason": "the client does it"},
        headers=h,
    ).json()
    assert run["blockers"] == []
    # two options for the terrace: Arvox and Zentrafix
    zen = plot["pu"].options[1]
    arv = plot["pu"].options[0]
    c.put(
        f"/api/drawquote/runs/{rid}/items/{t['id']}",
        json={
            "picks": [
                {"system_id": plot["pu"].id, "option_id": arv.id},
                {"system_id": plot["pu"].id, "option_id": zen.id},
            ]
        },
        headers=h,
    )

    r = c.post(f"/api/drawquote/runs/{rid}/make", headers=h)
    assert r.status_code == 200, r.text
    made = r.json()
    q = db.get(Quotation, made["quotation"]["id"])
    assert q.status == "draft" and q.revision == 0
    lines = {(ln.description.split(":")[0], ln.option): ln for item in q.items for ln in item.lines}
    tl = lines[("Terrace", "1")]
    assert (
        tl.qty == D("319.400") and tl.uom == "sqm" and lines[("Terrace", "2")].qty == D("319.400")
    )
    assert lines[("Toilet / bathroom", None)].qty == D("13.680")
    # the lines carry the working's rates
    for ln in (tl, lines[("Terrace", "2")], lines[("Toilet / bathroom", None)]):
        g = db.get(
            RateGroup,
            db.scalar(
                select(RateGroupLine.group_id).where(RateGroupLine.quotation_line_id == ln.id)
            ),
        )
        assert ln.rate is not None and ln.rate == g.rate_sqm
    # every quantity is traceable to the drawing
    trace = c.get(f"/api/drawquote/lines/{tl.id}/areas", headers=h).json()
    assert (
        [a["name"] for a in trace["areas"]] == ["TERRACE"]
        and trace["areas"][0]["outline"]
        and trace["areas"][0]["holes"]
    )
    assert D(trace["areas"][0]["total_sqm"]) == D("319.400")

    # the review grid: a cell changed by a person says so, the rate follows, and it goes back
    grid = {(r_["label"], r_["option"]): r_ for r_ in made["grid"]}
    row = grid[("Invented PU terrace system (Arvox)", "1")]
    coat = next(p for p in row["products"] if p["product"] == "Arvox Flexi PU")
    old_rate = D(row["rate"])
    out = c.put(
        f"/api/drawquote/runs/{rid}/cells",
        json={"kind": "consumption", "ref": coat["consumption"]["ref"], "value": "1.8"},
        headers=h,
    ).json()
    row2 = next(r_ for r_ in out["grid"] if r_["line_id"] == row["line_id"])
    cell = next(p for p in row2["products"] if p["id"] == coat["id"])["consumption"]
    assert (
        cell["changed"] is True
        and cell["by"]
        and D(cell["calculated"]) == D("1.5")
        and D(row2["rate"]) > old_rate
    )
    out = c.put(
        f"/api/drawquote/runs/{rid}/cells",
        json={"kind": "consumption", "ref": coat["consumption"]["ref"]},
        headers=h,
    ).json()
    row3 = next(r_ for r_ in out["grid"] if r_["line_id"] == row["line_id"])
    assert (
        D(row3["rate"]) == old_rate
        and not next(p for p in row3["products"] if p["id"] == coat["id"])["consumption"]["changed"]
    )
    out = c.put(
        f"/api/drawquote/runs/{rid}/cells",
        json={"kind": "qty", "ref": row["line_id"], "value": "330"},
        headers=h,
    ).json()
    assert (
        next(r_ for r_ in out["grid"] if r_["line_id"] == row["line_id"])["qty"]["changed"] is True
    )

    # the annexure, and the working's Quantities sheet
    from app.quotations import render  # noqa: PLC0415

    doc = render.build(db, q)
    assert any(r_.area == "TERRACE" and r_.total == "319.40" for a in doc.annexure for r_ in a.rows)
    from app.costing import export  # noqa: PLC0415
    from app.costing.models import RateWorking  # noqa: PLC0415

    w = db.scalar(select(RateWorking).where(RateWorking.quotation_id == q.id))
    data, _name = export.working_xlsx(db, w)
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "Quantities" in wb.sheetnames
    assert any(row_[0] == "TERRACE" for row_ in wb["Quantities"].iter_rows(values_only=True))


def test_a_changed_drawing_makes_the_next_revision_and_says_the_terrace_changed(boss, plot, db):
    c, h = boss
    did, rev = upload(c, h, plot["site"], make_dxf(balcony=False), title="Invented tower plans")
    f = read(c, h, rev)
    _map(c, h, db, f["id"], plot)
    rid = c.post(
        f"/api/drawquote/sites/{plot['site']}/runs",
        json={"cad_file_id": f["id"], "client_id": plot["client"]},
        headers=h,
    ).json()["id"]
    first = c.post(f"/api/drawquote/runs/{rid}/make", headers=h)
    assert first.status_code == 200, first.text
    q0 = first.json()["quotation"]
    # the architect's next revision: the terrace 20 x 16
    r = c.post(
        f"/api/sites/{plot['site']}/drawings/{did}/revisions",
        files={
            "file": (
                "plan-r1.dxf",
                make_dxf(terrace_h=16.0, balcony=False),
                "application/octet-stream",
            )
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    rev1 = next(d for d in r.json() if d["id"] == did)["latest"]["id"]
    f1 = read(c, h, rev1, architect=None)
    db.expire_all()
    new_areas = list(db.scalars(select(CadArea).where(CadArea.cad_file_id == f1["id"])))
    if not all(
        a.status == "mapped" for a in new_areas
    ):  # the mapping carried over by the takeoff, else mapped again
        _map(c, h, db, f1["id"], plot)
    rid1 = c.post(
        f"/api/drawquote/sites/{plot['site']}/runs", json={"cad_file_id": f1["id"]}, headers=h
    ).json()["id"]
    r = c.post(f"/api/drawquote/runs/{rid1}/make", headers=h)
    assert r.status_code == 200, r.text
    q1 = r.json()["quotation"]
    assert q1["code"] == q0["code"] and q1["revision"] == q0["revision"] + 1
    changes = r.json()["changes"]
    assert [ch["item"] for ch in changes] == ["Terrace"]
    ch = changes[0]
    # 320 - 4 floor + (72 + 8) × 0.30 = 340.00
    assert (D(ch["old_qty"]), D(ch["new_qty"])) == (D("319.400"), D("340.000")) and ch["areas"][
        "resized"
    ]
    assert db.get(Quotation, q0["id"]).is_latest is False
    run1 = db.get(DrawQuote, rid1)
    assert run1.previous_id == rid
    toilet_line = next(
        ln
        for item in db.get(Quotation, q1["id"]).items
        for ln in item.lines
        if ln.description.startswith("Toilet")
    )
    assert toilet_line.qty == D("13.680") and db.scalar(
        select(QuoteLineArea.id).where(QuoteLineArea.quotation_line_id == toilet_line.id)
    )


def test_only_the_three_roles_make_a_quotation_from_a_drawing(login_as, plot):
    c, h = login_as("sales")
    assert c.get(f"/api/drawquote/sites/{plot['site']}", headers=h).status_code == 403
    for role in ("planning", "estimator"):
        c, h = login_as(role, email=f"{role}-dq@example.com")
        assert c.get(f"/api/drawquote/sites/{plot['site']}", headers=h).status_code in (200, 404)


def site_plan_dxf() -> bytes:
    """A site development plan: two buildings (G+7 and G+3) and a podium on one plot."""
    k = 1000.0
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    def rect(x, y, w, h):
        msp.add_lwpolyline(
            [
                (x * k, y * k),
                ((x + w) * k, y * k),
                ((x + w) * k, (y + h) * k),
                (x * k, (y + h) * k),
            ],
            close=True,
        )

    def text(t, x, y):
        msp.add_text(t, dxfattribs={"insert": (x * k, y * k), "height": 0.5 * k})

    rect(-5, -10, 120, 90)
    text("SITE DEVELOPMENT PLAN", 10, -8)
    rect(0, 0, 30, 20)
    text("BLOCK A", 5, 10)
    text("G+7", 5, 8)
    rect(50, 0, 25, 18)
    text("BLOCK B (G+3)", 55, 9)
    rect(0, 30, 80, 30)
    text("PODIUM", 20, 45)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def test_a_site_plan_gives_a_block_per_building_and_says_rooms_need_floor_plans(boss, plot, db):
    c, h = boss
    _did, rev = upload(c, h, plot["site"], site_plan_dxf(), title="Invented site plan")
    f = read(c, h, rev)
    cad = db.get(CadFile, f["id"])
    blocks = building.site_blocks(cad)
    assert [(b["kind"], b["name"], b["floors"]) for b in blocks] == [
        ("block", "BLOCK A", 8),
        ("block", "BLOCK B (G+3)", 4),
        ("flat", "PODIUM", 0),
    ]
    data = building.draft(db, db.get(Site, plot["site"]), cad)
    assert "footprints, not their rooms" in data["site_plan_note"]
    building.save(db, plot["site"], data, cad.id, None)
    db.commit()
    out = building.payload(db, plot["site"])
    a = next(b for b in out["blocks"] if b["name"] == "BLOCK A")
    assert a["height_m"] == 24.0 and len(a["outline"]) == 4 and out["site_plan_note"]
    assert next(b for b in out["blocks"] if b["kind"] == "flat")["height_m"] == 0.15


def test_the_check_against_the_drawing_lists_what_is_not_mapped(boss, plot, db):
    c, h = boss
    _did, rev = upload(c, h, plot["site"], make_dxf(), title="Invented tower plans")
    f = read(c, h, rev)
    _map(c, h, db, f["id"], plot)
    out = c.get(f"/api/drawquote/files/{f['id']}/check", headers=h).json()
    assert [x["name"] for x in out["unmapped_labels"]] == ["BALCONY"]
    terrace = next(p for p in out["plans"] if p["plan"] == "TERRACE PLAN")
    assert (terrace["areas"], terrace["mapped"], D(terrace["mapped_sqm"])) == (1, 1, D("300.00"))
    # the balcony's own outline is no area's mapped outline yet, but it is an area's: not "unused"
    assert out["closed_unused_count"] == 0


def test_a_quotation_in_sq_ft_converts_once_and_shows_both(boss, plot, db):
    c, h = boss
    _did, rev = upload(c, h, plot["site"], make_dxf(balcony=False), title="Invented tower plans")
    f = read(c, h, rev)
    _map(c, h, db, f["id"], plot)
    rid = c.post(
        f"/api/drawquote/sites/{plot['site']}/runs",
        json={"cad_file_id": f["id"], "client_id": plot["client"], "unit": "sqft"},
        headers=h,
    ).json()["id"]
    q = c.post(f"/api/drawquote/runs/{rid}/make", headers=h).json()["quotation"]
    line = next(
        ln
        for item in db.get(Quotation, q["id"]).items
        for ln in item.lines
        if ln.description.startswith("Terrace")
    )
    assert line.uom == "sqft" and line.qty == (D("319.40") * D("10.7639")).quantize(D("0.001"))
    assert "319.40 sqm = 3,438.0 sq ft" in line.description
    g = db.get(
        RateGroup,
        db.scalar(select(RateGroupLine.group_id).where(RateGroupLine.quotation_line_id == line.id)),
    )
    assert line.rate == g.rate_sqft  # the working's rate per sq ft


def test_a_level_in_mm_and_an_outline_that_is_not_the_rooms():
    from app.building import detect  # noqa: PLC0415
    from app.takeoff import service as takeoff  # noqa: PLC0415

    assert detect.level_m("FFL +800.00 MM") == 0.8 and detect.level_m("FFL +3.000") == 3.0

    class F:  # a flat drawn round two rooms, one room drawn on its own
        unit_m = 0.001
        texts: list = []
        summary = {
            "closed": [
                ["A", [[0, 0], [10000, 0], [10000, 8000], [0, 8000]]],
                ["A", [[0, 0], [2400, 0], [2400, 1800], [0, 1800]]],
            ]
        }

    assert takeoff.closed_around(F, 1000, 900, 4.32, [(6000, 4000)]) is not None  # the toilet's own
    assert (
        takeoff.closed_around(F, 6000, 4000, 12, [(1000, 900)]) is None
    )  # the flat holds the toilet's label
    assert takeoff.closed_around(F, 6000, 4000, 12, []) is None  # 80 sqm drawn, 12 sqm labelled
