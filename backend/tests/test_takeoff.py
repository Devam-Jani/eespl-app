# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""AutoCAD takeoff with invented drawings (DXF made here with ezdxf; the real drawings are company
data and never committed): reading sizes, units, notes and depths, tracing and snapping, label vs
trace and AutoCAD vs survey, repeated floors, revision changes, plain errors, permissions."""

import io
import stat
from decimal import Decimal

import ezdxf
import pytest
from sqlalchemy import select

from app.config import settings
from app.sites.models import Site, SiteMember, SiteNode
from app.survey.models import AreaType, SurveyArea
from app.takeoff import dwg, geometry
from app.takeoff.models import CadArea, CadFile
from app.takeoff.sizes import depths, label_name, parse_size
from app.team.models import Measurement
from tests.conftest import login
from tests.test_finance import boss, world  # noqa: F401  (fixtures)

FT = 0.3048
INCH = 0.0254


# --- invented drawings ----------------------------------------------------------------------------


def make_dxf(units: str = "mm", rooms=None, extra_texts=(), insunits: int | None = None) -> bytes:
    """A floor plan: each room's four walls (loose lines with a door gap), its label and notes,
    and the plan's title under it. Sizes in metres, drawn in the drawing's unit."""
    k = {"mm": 1000.0, "in": 1 / INCH}[units]
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits if insunits is not None else {"mm": 4, "in": 1}[units]
    msp = doc.modelspace()
    for layer in ("A-WALL", "A-TEXT", "A-FURN"):
        doc.layers.add(layer)
    rooms = rooms if rooms is not None else default_rooms()
    for r in rooms:
        x, y, w, h = (v * k for v in r["box"])
        gap = 0.9 * k
        msp.add_line((x, y), (x + w, y), dxfattribs={"layer": "A-WALL"})
        msp.add_line((x + w, y), (x + w, y + h), dxfattribs={"layer": "A-WALL"})
        msp.add_line(
            (x + w, y + h), (x + gap + 0.3 * k, y + h), dxfattribs={"layer": "A-WALL"}
        )  # door gap
        msp.add_line((x + 0.3 * k, y + h), (x, y + h), dxfattribs={"layer": "A-WALL"})
        msp.add_line((x, y + h), (x, y), dxfattribs={"layer": "A-WALL"})
        msp.add_circle((x + w / 2, y + h / 2), 0.2 * k, dxfattribs={"layer": "A-FURN"})  # a WC
        msp.add_mtext(
            r["label"],
            dxfattribs={
                "layer": "A-TEXT",
                "insert": (x + w / 2, y + h / 2),
                "char_height": 0.15 * k,
            },
        )
        for note, (dx, dy) in r.get("notes", []):
            msp.add_text(
                note,
                dxfattribs={
                    "layer": "A-TEXT",
                    "insert": (x + dx * k, y + dy * k),
                    "height": 0.1 * k,
                },
            )
    msp.add_text(
        "%%U1ST FLOOR WORKING PLAN",
        dxfattribs={"layer": "A-TEXT", "insert": (0, -3 * k), "height": 0.3 * k},
    )
    for text, (tx, ty) in extra_texts:
        msp.add_text(
            text, dxfattribs={"layer": "A-TEXT", "insert": (tx * k, ty * k), "height": 0.15 * k}
        )
    msp.add_aligned_dim(
        p1=(0, 0), p2=(3.2004 * k, 0), distance=0.5 * k, dxfattribs={"layer": "A-DIM"}
    ).render()
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def default_rooms():
    return [
        # LADIES TOILET 10'6"X7'3" = 3.2004 x 2.2098 m, a 600 mm sunken slab
        {"box": (0, 0, 3.2004, 2.2098), "label": "LADIES TOILET\\P10'6\"X7'3\"",
         "notes": [("CHEMICAL WATER PROOFING", (0.4, 0.4)), ("600 MM SUNK", (0.4, 0.8))]},
        {"box": (6, 0, 4.0, 3.0), "label": "TERRACE 4000X3000"},
        {"box": (12, 0, 3.0, 2.4), "label": "KITCHEN 3.0 x 2.4 m"},
    ]  # fmt: skip


@pytest.fixture
def place(world, db, make_user):
    """The site's structure: Tower A, floors 1 to 3, a ladies toilet and a terrace on floor 1."""
    site = db.get(Site, world["site"])
    tower = SiteNode(site_id=site.id, kind="tower", name="Tower A")
    db.add(tower)
    db.flush()
    floors = []
    for i in (1, 2, 3):
        f = SiteNode(
            site_id=site.id,
            parent_id=tower.id,
            kind="floor",
            name=f"Floor {i}",
            sort_order=i,
            level_no=i,
        )
        db.add(f)
        db.flush()
        floors.append(f)
    toilet = SiteNode(site_id=site.id, parent_id=floors[0].id, kind="toilet", name="Ladies toilet")
    terrace = SiteNode(site_id=site.id, parent_id=floors[0].id, kind="terrace", name="Terrace")
    db.add_all([toilet, terrace])
    db.commit()
    return {
        "site": site.id,
        "floors": [f.id for f in floors],
        "toilet": toilet.id,
        "terrace": terrace.id,
    }


def upload(c, h, site_id, data: bytes, name="plan.dxf", title="Invented plan"):
    r = c.post(
        f"/api/sites/{site_id}/drawings",
        data={"title": title, "discipline": "architectural"},
        files={"file": (name, data, "application/octet-stream")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    d = next(x for x in r.json() if x["title"] == title)
    return d["id"], d["latest"]["id"]


def read(c, h, revision_id, architect="Invented Architects"):
    r = c.post(
        f"/api/takeoff/revisions/{revision_id}/read", json={"architect": architect}, headers=h
    )
    assert r.status_code == 202, r.text
    f = c.get(
        f"/api/takeoff/files/{r.json()['id']}", headers=h
    ).json()  # read by the background task
    return f


def areas(c, h, fid, show="all"):
    return {
        a["name"]: a
        for a in c.get(f"/api/takeoff/files/{fid}/areas?show={show}", headers=h).json()["areas"]
    }


# --- sizes, units, notes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "w", "length"),
    [
        ("LADIES TOILET 10'6\"X7'3\"", 10.5 * FT, 7.25 * FT),
        ("TERRACE\n75'3¼\"X13'6\"", 75 * FT + 3.25 * INCH, 13.5 * FT),
        ("TERRACE 75' 3¼\" x 13' 6\"", 75 * FT + 3.25 * INCH, 13.5 * FT),
        ("KITCHEN 3000X2400", 3.0, 2.4),
        ("KITCHEN 3000 x 2400 mm", 3.0, 2.4),
        ("BALCONY 3.0 x 2.4 m", 3.0, 2.4),
        ("BALCONY 3.0X2.4M", 3.0, 2.4),
        ("7'0'X7'8½\"", 7 * FT, 7 * FT + 8.5 * INCH),  # an inch mark typed as '
    ],
)
def test_sizes_in_feet_and_inches_mm_and_m_with_or_without_spaces(text, w, length):
    s = parse_size(text)
    assert s is not None and abs(s.width_m - w) < 1e-6 and abs(s.length_m - length) < 1e-6
    assert abs(s.area_sqm - w * length) < 1e-6


def test_names_notes_and_depths():
    s = parse_size("LADIES TOILET\n10'6\"X7'3\"")
    assert label_name("LADIES TOILET\n10'6\"X7'3\"", s) == "LADIES TOILET" and s.kind == "ft-in"
    assert depths("600 MM SUNK").sunk_m == pytest.approx(0.6)
    d = depths('6" SUNK + 6" RAISE')
    assert d.sunk_m == pytest.approx(6 * INCH) and d.raise_m == pytest.approx(6 * INCH)
    assert parse_size("CHEMICAL WATER PROOFING") is None


def test_a_drawing_in_inches_and_one_in_mm_give_the_same_areas(boss, place, db):
    c, h = boss
    results = {}
    for units in ("in", "mm"):
        _d, rev = upload(
            c,
            h,
            place["site"],
            make_dxf(units),
            name=f"plan-{units}.dxf",
            title=f"Invented plan {units}",
        )
        f = read(c, h, rev)
        assert f["status"] == "ready", f["error"]
        assert f["unit_name"] == {"in": "inches", "mm": "millimetres"}[units]
        a = areas(c, h, f["id"])["LADIES TOILET"]
        # trace the toilet by its corners (drawing units)
        k = {"mm": 1000.0, "in": 1 / INCH}[units]
        pts = [[0, 0], [3.2004 * k, 0], [3.2004 * k, 2.2098 * k], [0, 2.2098 * k]]
        t = c.post(f"/api/takeoff/areas/{a['id']}/trace", json={"points": pts}, headers=h).json()
        results[units] = (
            Decimal(str(a["label_area_sqm"])),
            Decimal(str(t["traced_area_sqm"])),
            Decimal(str(t["traced_perimeter_m"])),
        )
    assert results["in"] == results["mm"]
    assert results["mm"][1] == Decimal("7.072")  # 3.2004 x 2.2098 m


def test_notes_attach_to_the_nearest_area_and_set_the_depth_and_side_walls(boss, place, db):
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    found = areas(c, h, f["id"])
    toilet = found["LADIES TOILET"]
    assert {n["text"] for n in toilet["notes"]} == {"CHEMICAL WATER PROOFING", "600 MM SUNK"}
    assert not found["TERRACE"]["notes"] and Decimal(str(toilet["sunk_m"])) == Decimal("0.600")
    # no frame, and its rooms do not touch (each its own cluster, no title in it): unknown
    assert toilet["plan"] is None and not toilet["plan_guessed"]
    assert toilet["area_type"] == "Toilet / bathroom" and found["TERRACE"]["area_type"] == "Terrace"
    assert f["size_labels"] == 3 and f["waterproofing_notes"] == 2 and f["dimensions"] == 1
    k = 1000
    t = c.post(
        f"/api/takeoff/areas/{toilet['id']}/trace",
        json={"points": [[0, 0], [3.2004 * k, 0], [3.2004 * k, 2.2098 * k], [0, 2.2098 * k]]},
        headers=h,
    ).json()
    perimeter = Decimal(str(t["traced_perimeter_m"]))
    assert perimeter == Decimal("10.820")
    assert Decimal(str(t["side_wall_sqm"])) == (perimeter * Decimal("0.6")).quantize(
        Decimal("0.001")
    )  # a line of its own


def test_tracing_a_square_snapping_and_the_outline_from_the_walls(boss, place, db):
    assert (
        geometry.area([(0, 0), (4, 0), (4, 4), (0, 4)]) == 16
        and geometry.perimeter([(0, 0), (4, 0), (4, 4), (0, 4)]) == 16
    )
    walls = [(0, 0, 10, 0), (10, 0, 10, 5), (10, 5, 0, 5), (0, 5, 0, 0)]
    s = geometry.snap((9.8, 0.15), walls, radius=0.5)
    assert s.kind == "end" and s.point == (10, 0)
    s = geometry.snap((5, 0.2), walls, radius=0.5, previous=(5, 3))
    assert s.kind == "perpendicular" and s.point == (5, 0)
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    r = c.post(
        f"/api/takeoff/files/{f['id']}/snap", json={"x": 3180, "y": 30, "radius": 100}, headers=h
    ).json()
    assert r["kind"] == "end" and (r["x"], r["y"]) == (3200.4, 0)
    # a click inside the terrace: the outline up to its walls (to correct, not to trust)
    p = c.post(
        f"/api/takeoff/files/{f['id']}/propose", json={"x": 9000, "y": 1000}, headers=h
    ).json()
    assert p["area_sqm"] == pytest.approx(12.0)
    # a new area traced where nothing is labelled
    a = c.post(
        f"/api/takeoff/files/{f['id']}/areas",
        json={
            "name": "OPEN TERRACE",
            "points": [[20000, 0], [24000, 0], [24000, 4000], [20000, 4000]],
        },
        headers=h,
    ).json()
    assert Decimal(str(a["traced_area_sqm"])) == Decimal("16.000") and a["area_type"] == "Terrace"


def test_label_against_trace_and_autocad_against_the_survey_are_flagged(boss, place, db):
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    terrace = areas(c, h, f["id"])["TERRACE"]  # labelled 4000X3000: 12 sqm
    t = c.post(
        f"/api/takeoff/areas/{terrace['id']}/trace",
        json={"points": [[6000, 0], [10000, 0], [10000, 3060], [6000, 3060]]},
        headers=h,
    ).json()
    assert t["label_trace_diff_percent"] == 2.0 and not t["label_trace_flagged"]  # within 3 %
    t = c.post(
        f"/api/takeoff/areas/{terrace['id']}/trace",
        json={"points": [[6000, 0], [10000, 0], [10000, 3200], [6000, 3200]]},
        headers=h,
    ).json()
    assert (
        t["label_trace_diff_percent"] == pytest.approx(6.7, abs=0.05) and t["label_trace_flagged"]
    )
    # the engineer's laser survey of the same place says 13.5 sqm: 5.2 % off the AutoCAD area
    from app.survey.models import Survey

    s = Survey(code="SUR-T-1", site_id=place["site"], title="Invented laser survey")
    db.add(s)
    db.flush()
    db.add(
        SurveyArea(
            survey_id=s.id,
            node_id=place["terrace"],
            name="Terrace",
            method="laser",
            shape="rect",
            length_m=Decimal("4.5"),
            width_m=Decimal("3"),
            floor_area_sqm=Decimal("13.5"),
        )
    )
    db.commit()
    a = c.put(
        f"/api/takeoff/areas/{terrace['id']}", json={"node_id": place["terrace"]}, headers=h
    ).json()
    assert a["survey_check"]["flagged"] and a["survey_check"]["methods"] == ["laser"]
    assert Decimal(str(a["survey_check"]["diff_percent"])) == Decimal("5.2")


def test_accepted_areas_go_to_the_survey_the_measurement_book_the_material_plan_and_3d(
    boss, place, db
):
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    toilet = areas(c, h, f["id"])["LADIES TOILET"]
    r = c.post(f"/api/takeoff/areas/{toilet['id']}/accept", json={"survey": True}, headers=h)
    assert r.status_code == 422 and "map it" in r.json()["detail"]
    c.put(f"/api/takeoff/areas/{toilet['id']}", json={"node_id": place["toilet"]}, headers=h)
    a = c.post(
        f"/api/takeoff/areas/{toilet['id']}/accept",
        json={"survey": True, "measurement_book": True},
        headers=h,
    ).json()
    assert (
        a["status"] == "accepted"
        and a["survey_area_id"]
        and a["measurement_id"]
        and a["side_measurement_id"]
    )
    sa = db.get(SurveyArea, a["survey_area_id"])
    assert (
        sa.method == "cad"
        and sa.shape == "rect"
        and sa.floor_area_sqm == Decimal("7.072")
        and sa.sunk_depth_mm == Decimal("600.0")
    )
    assert sa.floor_label == "Floor 1" and sa.tower == "Tower A" and "area #" in sa.remarks
    rows = db.scalars(
        select(Measurement).where(
            Measurement.site_id == place["site"], Measurement.source == "autocad"
        )
    ).all()
    assert sorted(m.qty for m in rows) == sorted(
        [Decimal("7.072"), Decimal(str(a["side_wall_sqm"]))]
    )  # floor and side walls apart
    q = c.get(f"/api/takeoff/sites/{place['site']}/quantities", headers=h).json()
    assert q["by_floor"] == [{"name": "Floor 1", "sqm": 7.072}] and q["areas"] == 1
    model = c.get(f"/api/sites/{place['site']}/model", headers=h).json()
    assert next(n for n in model["nodes"] if n["id"] == place["toilet"])["autocad_sqm"] == 7.07


def test_same_as_floor_1_for_floors_2_and_3_copies_the_areas_with_their_names(boss, place, db):
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    found = areas(c, h, f["id"])
    c.put(
        f"/api/takeoff/areas/{found['LADIES TOILET']['id']}",
        json={"node_id": place["toilet"]},
        headers=h,
    )
    c.put(
        f"/api/takeoff/areas/{found['TERRACE']['id']}",
        json={"node_id": place["terrace"]},
        headers=h,
    )
    made = c.post(
        f"/api/takeoff/files/{f['id']}/copy-floors",
        json={
            "area_ids": [found["LADIES TOILET"]["id"], found["TERRACE"]["id"]],
            "source_floor_id": place["floors"][0],
            "target_floor_ids": place["floors"][1:],
        },
        headers=h,
    ).json()
    assert sorted((m["name"], m["floor_label"], m["place"]) for m in made) == [
        ("LADIES TOILET", "Floor 2", "Tower A / Floor 2 / Ladies toilet"),
        ("LADIES TOILET", "Floor 3", "Tower A / Floor 3 / Ladies toilet"),
        ("TERRACE", "Floor 2", "Tower A / Floor 2 / Terrace"),
        ("TERRACE", "Floor 3", "Tower A / Floor 3 / Terrace"),
    ]
    assert all(m["status"] == "mapped" and m["sunk_m"] == found[m["name"]]["sunk_m"] for m in made)
    # the places were made under floors 2 and 3 with the same names
    assert db.scalar(
        select(SiteNode).where(
            SiteNode.parent_id == place["floors"][2], SiteNode.name == "Ladies toilet"
        )
    )


def test_a_new_revision_keeps_the_mapping_and_says_what_changed(boss, place, db):
    c, h = boss
    did, rev0 = upload(c, h, place["site"], make_dxf("mm"))
    f0 = read(c, h, rev0)
    t0 = areas(c, h, f0["id"])
    c.put(
        f"/api/takeoff/areas/{t0['LADIES TOILET']['id']}",
        json={"node_id": place["toilet"]},
        headers=h,
    )
    rooms = default_rooms()
    rooms[1]["label"] = "TERRACE 4500X3000"  # resized
    del rooms[2]  # the kitchen removed
    rooms.append({"box": (18, 0, 2.0, 1.5), "label": "BALCONY 2000X1500"})  # added
    r = c.post(
        f"/api/sites/{place['site']}/drawings/{did}/revisions",
        files={"file": ("plan-r1.dxf", make_dxf("mm", rooms), "application/octet-stream")},
        headers=h,
    )
    rev1 = next(d for d in r.json() if d["id"] == did)["latest"]["id"]
    f1 = read(c, h, rev1, architect=None)
    assert f1["architect"] == "Invented Architects"  # the architect's layer mapping is reused
    ch = f1["changes"]
    assert [a["name"] for a in ch["added"]] == ["BALCONY"]
    assert [a["name"] for a in ch["removed"]] == ["KITCHEN"]
    assert [(a["name"], a["previous_area_sqm"], a["label_area_sqm"]) for a in ch["resized"]] == [
        ("TERRACE", 12.0, 13.5)
    ]
    t1 = areas(c, h, f1["id"])
    assert (
        t1["LADIES TOILET"]["node_id"] == place["toilet"]
        and t1["LADIES TOILET"]["status"] == "mapped"
    )


def test_a_bad_or_too_new_file_gives_a_plain_message_and_a_slow_converter_is_stopped(
    boss, place, db, tmp_path, monkeypatch
):
    with pytest.raises(dwg.CadError, match="not an AutoCAD drawing"):
        dwg.version(b"%PDF-1")
    with pytest.raises(dwg.CadError, match="newer AutoCAD format than 2018"):
        dwg.version(b"AC1035")
    assert dwg.version(b"AC1032").name == "AutoCAD 2018"
    c, h = boss
    r = c.post(
        f"/api/sites/{place['site']}/drawings",
        data={"title": "Broken", "discipline": "architectural"},
        files={"file": ("broken.dwg", b"this is not a drawing at all", "application/octet-stream")},
        headers=h,
    )
    assert r.status_code == 422 and "not a .dwg file" in r.json()["detail"]  # refused at upload
    _d, rev = upload(c, h, place["site"], b"AC1035" + b"\0" * 200, name="new.dwg", title="Too new")
    f = read(c, h, rev)
    assert f["status"] == "failed" and "save it as AutoCAD 2018" in f["error"]
    # a converter that hangs is stopped after the timeout
    fake = tmp_path / "dwg2dxf"
    fake.write_text("#!/bin/sh\nsleep 10\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "dwg2dxf_path", str(fake))
    monkeypatch.setattr(settings, "dwg_timeout_s", 1)
    _d, rev = upload(c, h, place["site"], b"AC1032" + b"\0" * 200, name="slow.dwg", title="Slow")
    f = read(c, h, rev)
    assert f["status"] == "failed" and "longer than 1 seconds" in f["error"]
    # a DXF that is not one
    _d, rev = upload(
        c, h, place["site"], b"0\nSECTION\n2\nGARBAGE", name="bad.dxf", title="Bad DXF"
    )
    f = read(c, h, rev)
    assert f["status"] == "failed" and f["error"]


def test_who_may_see_and_take_off(boss, place, db, login_as, make_user, client):
    c, h = boss
    _d, rev = upload(c, h, place["site"], make_dxf("mm"))
    f = read(c, h, rev)
    toilet = areas(c, h, f["id"])["LADIES TOILET"]
    # billing: everything, the measurement book included
    bc, bh = login_as("billing")
    assert (
        bc.put(
            f"/api/takeoff/areas/{toilet['id']}", json={"node_id": place["toilet"]}, headers=bh
        ).status_code
        == 200
    )
    # planning: maps and accepts into the survey, not the measurement book
    pc, ph = login_as("planning")
    assert (
        pc.post(
            f"/api/takeoff/areas/{toilet['id']}/accept", json={"measurement_book": True}, headers=ph
        ).status_code
        == 403
    )
    assert (
        pc.post(
            f"/api/takeoff/areas/{toilet['id']}/accept", json={"survey": True}, headers=ph
        ).json()["status"]
        == "accepted"
    )
    # the estimator sees; sales sees on their own sites; neither takes off
    ec, eh = login_as("estimator")
    assert ec.get(f"/api/takeoff/files/{f['id']}/areas", headers=eh).status_code == 200
    assert (
        ec.post(
            f"/api/takeoff/files/{f['id']}/areas",
            json={"name": "X", "points": [[0, 0], [1, 0], [1, 1]]},
            headers=eh,
        ).status_code
        == 403
    )
    sales = make_user("sales-own@example.com", "sales")
    sc, sh = client, login(client, "sales-own@example.com")
    assert (
        sc.get(f"/api/takeoff/files/{f['id']}/areas", headers=sh).status_code == 404
    )  # not their site
    db.add(SiteMember(site_id=place["site"], user_id=sales.id, role_on_site="sales"))
    db.commit()
    assert sc.get(f"/api/takeoff/files/{f['id']}/areas", headers=sh).status_code == 200
    # the site engineer: on their own sites only
    eng = make_user("eng-own@example.com", "site_engineer")
    gh = login(client, "eng-own@example.com")
    assert client.get(f"/api/takeoff/files/{f['id']}", headers=gh).status_code == 404
    db.add(SiteMember(site_id=place["site"], user_id=eng.id, role_on_site="incharge"))
    db.commit()
    assert client.get(f"/api/takeoff/files/{f['id']}", headers=gh).status_code == 200
    # a client login never holds the drawing tools
    vc, vh = login_as("client")
    assert vc.get(f"/api/takeoff/files/{f['id']}", headers=vh).status_code == 403
    assert db.scalar(select(CadArea).where(CadArea.id == toilet["id"])).status == "accepted"
    assert db.scalar(select(CadFile.architect)) == "Invented Architects"
    assert db.scalar(select(AreaType.id).where(AreaType.name == "Terrace"))
