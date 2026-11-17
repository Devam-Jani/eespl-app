# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Prompt 39c: the default system per area type (filled only where none is set), planning edits its
own draft quotation, structural tags and a plan drawn twice left out on their own (and brought
back), past use for the same area type first, and the wall-layer hint on the building page.
Synthetic drawings and invented products only."""

import importlib.util
import io
from decimal import Decimal
from pathlib import Path

import ezdxf
from sqlalchemy import select

from app.masters.models import System, SystemOption
from app.quotations.models import Quotation, QuotationItem, QuotationLine
from app.sites.models import Site
from app.spec import keypoints, suggest
from app.survey.models import AreaType
from app.takeoff.models import CadArea
from app.timefmt import ist_today
from tests.test_drawing_to_quote import plot  # noqa: F401  (fixture)
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_takeoff import read, upload

D = Decimal
MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0066_drawing_followups.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("m0066", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _area_type(db, name) -> AreaType:
    at = db.scalar(select(AreaType).where(AreaType.name == name))
    if at is None:
        at = AreaType(name=name)
        db.add(at)
        db.flush()
    return at


def test_area_types_get_the_most_used_systems_and_a_default_set_by_someone_stays(db):
    def system(code, name, used=0):
        s = System(code=code, name=name, unit="sqm")
        db.add(s)
        db.flush()
        return s

    cem_mesh = system("T39C-CM", "Invented two component cementitious coating with glass mesh")
    cem = system("T39C-C", "Invented 2K cementitious coating")
    pu1k = system("T39C-PU", "Invented single component PU membrane")
    hdpe = system("T39C-H", "Invented pre-applied HDPE membrane")
    cry = system("T39C-X", "Invented crystalline slurry")
    system("T39C-CT", "Invented two coats coal tar epoxy")  # not a potable lining
    epoxy = system("T39C-E", "Invented epoxy potable lining")
    mine = system("T39C-MINE", "Invented kitchen system someone chose")
    names = {
        "Terrace": None,
        "Toilet / bathroom": None,
        "Kitchen": mine.id,
        "Basement raft": None,
        "Overhead water tank": None,
        "Expansion joint": None,
    }
    types = {}
    for n, default in names.items():
        at = _area_type(db, n)
        at.default_system_id, at.suitable_system_ids = default, []
        types[n] = at
    db.commit()
    lines = _migration().fill_defaults(db.connection())
    db.commit()
    for at in types.values():
        db.refresh(at)
    assert (
        types["Terrace"].default_system_id == cem_mesh.id
        and pu1k.id in types["Terrace"].suitable_system_ids
    )
    assert types["Toilet / bathroom"].default_system_id in (cem.id, cem_mesh.id)
    assert types["Kitchen"].default_system_id == mine.id  # set by someone: never overwritten
    assert (
        types["Basement raft"].default_system_id == hdpe.id
        and cry.id in types["Basement raft"].suitable_system_ids
    )
    assert (
        types["Overhead water tank"].default_system_id in (cem.id, cem_mesh.id)
        and epoxy.id in types["Overhead water tank"].suitable_system_ids
    )
    assert types["Expansion joint"].default_system_id is None
    assert any("Kitchen: its own default" in x for x in lines) and any(
        "Expansion joint" in x and "joint" in x for x in lines
    )


def test_planning_edits_a_quotation_it_made_while_it_is_a_draft(login_as, db, make_user):
    c, h = login_as("planning")
    from app.models import User  # noqa: PLC0415

    me = db.scalar(select(User).where(User.email == "planning@example.com"))
    other = make_user("sales-39c@example.com", "sales")
    mine = Quotation(
        code="QTN-T39C-1",
        client_firm="Invented Builders",
        project="Invented",
        quote_date=ist_today(),
        created_by=me.id,
        salesperson_id=me.id,
    )
    theirs = Quotation(
        code="QTN-T39C-2",
        client_firm="Invented Builders",
        project="Invented",
        quote_date=ist_today(),
        created_by=other.id,
        salesperson_id=other.id,
    )
    db.add_all([mine, theirs])
    db.commit()
    assert (
        c.put(
            f"/api/quotations/{mine.id}", json={"attention": "Invented contact"}, headers=h
        ).status_code
        == 200
    )
    assert c.put(
        f"/api/quotations/{theirs.id}", json={"attention": "x"}, headers=h
    ).status_code in (403, 404)
    mine.status, mine.sent_at = "sent", mine.created_at
    db.commit()
    assert (
        c.put(f"/api/quotations/{mine.id}", json={"attention": "Another"}, headers=h).status_code
        == 403
    )  # sent: not any more


def tags_and_copies_dxf() -> bytes:
    """A GROUND FLOOR PLAN with four rooms and its beam and column tags, and the same rooms drawn
    again 60 m to the right without a title (a second copy on the sheet)."""
    k = 1000.0
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    def text(t, x, y, h=0.25):
        msp.add_text(t, dxfattribs={"insert": (x * k, y * k), "height": h * k})

    rooms = [
        ("TOILET", 0, 0),
        ("KITCHEN", 6, 0),
        ("BALCONY", 12, 0),
        ("UTILITY", 0, 6),
        ("TERRACE", 6, 6),
    ]
    for dx in (0, 60):
        for name, x, y in rooms:
            text(name, x + dx, y)
    text("GROUND FLOOR PLAN", 3, -4, 0.5)
    for tag, x, y in (
        ("GB1(230X600)", 2, 2),
        ("B12 230X450", 4, 2),
        ("C3 300X600", 8, 2),
        ("F2 1500X1500", 10, 2),
        ("COLUMN FLUSHED WITH COMPOUND WALL 230X230", 2, 9),
        ("PLINTH BEAM 230X450", 9, 9),
    ):
        text(tag, x, y)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def test_structural_tags_and_a_second_copy_of_the_plan_are_left_out_and_can_come_back(
    boss, plot, db
):
    c, h = boss
    _did, rev = upload(c, h, plot["site"], tags_and_copies_dxf(), title="Invented sheet")
    f = read(c, h, rev)
    db.expire_all()
    areas = list(db.scalars(select(CadArea).where(CadArea.cad_file_id == f["id"])))
    structural = sorted(a.name for a in areas if a.left_out == "structural")
    assert structural == sorted(
        ["GB1( )", "B12", "C3", "F2", "COLUMN FLUSHED WITH COMPOUND WALL", "PLINTH BEAM"]
    ), [a.name for a in areas]
    dup = [a for a in areas if a.left_out == "duplicate"]
    assert len(dup) == 5 and all(a.x > 50000 for a in dup)  # the untitled copy, not the titled plan
    kept = [a for a in areas if a.left_out is None]
    assert sorted(a.name for a in kept) == sorted(
        ["TOILET", "KITCHEN", "BALCONY", "UTILITY", "TERRACE"]
    ) and all(a.x < 50000 for a in kept)
    listed = c.get(f"/api/takeoff/files/{f['id']}/areas?show=all", headers=h).json()
    assert {x["reason"] for x in listed["left_out"]} == {"structural", "duplicate"} and not any(
        a["name"].startswith("GB1") for a in listed["areas"]
    )
    gb1 = next(a for a in areas if a.name.startswith("GB1"))
    r = c.put(f"/api/takeoff/areas/{gb1.id}", json={"status": "candidate"}, headers=h)
    assert (
        r.status_code == 200 and r.json()["left_out"] is None and r.json()["status"] == "candidate"
    )


def test_two_titled_floor_plans_drawn_alike_are_not_copies():
    from app.takeoff.service import duplicate_copies  # noqa: PLC0415

    class A:
        def __init__(self, i, name, x, y, plan):
            self.id, self.name, self.x, self.y, self.plan = i, name, x, y, plan

    names = ["TOILET", "KITCHEN", "BALCONY", "UTILITY"]
    floor1 = [A(i, n, i * 5000.0, 0.0, "1ST FLOOR PLAN") for i, n in enumerate(names)]
    floor2 = [A(10 + i, n, 60000 + i * 5000.0, 0.0, "2ND FLOOR PLAN") for i, n in enumerate(names)]
    assert duplicate_copies(floor1 + floor2, 0.001) == []
    elevation = [
        A(20 + i, n, 60000 + i * 5000.0, 0.0, "FRONT ELEVATION") for i, n in enumerate(names)
    ]
    untitled = [A(30 + i, n, i * 5000.0, 0.0, None) for i, n in enumerate(names)]
    # neither says PLAN (an untitled copy and an elevation): the first drawn is kept
    assert {a.id for a in duplicate_copies(untitled + elevation, 0.001)} == {
        a.id for a in elevation
    }
    # the titled PLAN copy is kept against an untitled one
    assert {
        a.id
        for a in duplicate_copies(
            floor1 + [A(40 + i, n, 60000 + i * 5000.0, 0.0, None) for i, n in enumerate(names)],
            0.001,
        )
    } == {40, 41, 42, 43}


def test_past_use_for_the_same_area_type_ranks_first(plot, db):
    pu = plot["pu"]
    arv, zen = pu.options
    terrace_type, toilet_type = plot["types"]["Terrace"], plot["types"]["Toilet / bathroom"]

    def quoted(area_type_id, option: SystemOption, n: int):
        for i in range(n):
            q = Quotation(
                code=f"QTN-T39C-{area_type_id}-{option.id}-{i}",
                client_firm="Invented",
                project="Invented",
                quote_date=ist_today(),
                status="sent",
            )
            item = QuotationItem(
                name="Invented", budget_title="Invented", area_type_id=area_type_id
            )
            item.lines.append(
                QuotationLine(
                    description="Invented", uom="sqm", system_id=pu.id, system_option_id=option.id
                )
            )
            q.items.append(item)
            db.add(q)

    quoted(toilet_type, arv, 3)  # Arvox used more overall, on toilets
    quoted(terrace_type, zen, 1)  # Zentrafix used on terraces
    db.commit()
    chips = keypoints.parse("PU membrane on the terrace", "sqm", None, [])
    here = suggest.suggest(db, chips, with_cost=False, area_type_id=terrace_type)
    pu_opts = [o for o in here["options"] if o["system_id"] == pu.id]
    assert pu_opts[0]["brand"] == "Zentrafix" and pu_opts[0]["past_use_area"] == 1
    overall = suggest.suggest(db, chips, with_cost=False)
    assert [o for o in overall["options"] if o["system_id"] == pu.id][0]["brand"] == "Arvox"


def walls_dxf() -> bytes:
    """A floor plan whose walls are on a layer not named for walls ("A-123"), labels on "TXT"."""
    k = 1000.0
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("A-123")
    doc.layers.add("A-DOOR-SWING")
    for x1, y1, x2, y2 in (
        (0, 0, 20, 0),
        (20, 0, 20, 12),
        (20, 12, 0, 12),
        (0, 12, 0, 0),
        (8, 0, 8, 12),
    ):
        msp.add_line((x1 * k, y1 * k), (x2 * k, y2 * k), dxfattribs={"layer": "A-123"})
    msp.add_line((1 * k, 1 * k), (1.5 * k, 1.2 * k), dxfattribs={"layer": "A-DOOR-SWING"})
    doc.layers.add("S-BEAM")
    for i in range(8):  # more long lines than the walls: still never offered as walls
        msp.add_line((0, i * 1.5 * k), (20 * k, i * 1.5 * k), dxfattribs={"layer": "S-BEAM"})
    msp.add_text("GROUND FLOOR PLAN", dxfattribs={"insert": (5 * k, -3 * k), "height": 0.5 * k})
    msp.add_lwpolyline(
        [(-3 * k, -5 * k), (24 * k, -5 * k), (24 * k, 16 * k), (-3 * k, 16 * k)],
        close=True,
        dxfattribs={"layer": "A-FRAME"},
    )
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def test_the_building_page_offers_the_likely_wall_layers_when_none_is_mapped(boss, plot, db):
    c, h = boss
    _did, rev = upload(c, h, plot["site"], walls_dxf(), title="Invented walls")
    f = read(c, h, rev)
    site = db.get(Site, plot["site"])
    r = c.post(
        f"/api/sites/{site.id}/building/from-drawing", json={"cad_file_id": f["id"]}, headers=h
    )
    assert r.status_code in (200, 201), r.text
    model = c.get(f"/api/sites/{site.id}/building", headers=h).json()
    key = model["model"]["data"]["floor_types"][0]["key"]
    out = c.post(
        f"/api/sites/{site.id}/building/propose-outline", json={"key": key}, headers=h
    ).json()
    assert (
        out["outline"] == []
        and out["wall_hint"]["layers"][0]["layer"] == "A-123"
        and "not mapped" in out["wall_hint"]["message"]
    )
    assert c.post(
        f"/api/sites/{site.id}/building/wall-layer", json={"layer": "A-123"}, headers=h
    ).json()["walls"] == ["A-123"]
    again = c.post(
        f"/api/sites/{site.id}/building/propose-outline", json={"key": key}, headers=h
    ).json()
    assert len(again["outline"]) >= 4 and "wall_hint" not in again


def test_a_plan_whose_title_is_above_it_is_read_below_the_title():
    from app.building import service as building  # noqa: PLC0415

    class Cad:  # a frame 100 m tall; the title near its top; the plan drawn below the title
        unit_m = 0.001
        texts = [[10000.0, 90000.0, 500.0, "TXT", "GROUND FLOOR PLAN", False]]
        summary = {"frames": [[0.0, 0.0, 120000.0, 100000.0, "rectangle on FRAME"]]}

    plan = building.plans(Cad())[0]
    assert plan["region"] == [0.0, 0.0, 120000.0, 90000.0]
