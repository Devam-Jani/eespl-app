# ruff: noqa: E501
"""Section levels in millimetres or metres: the unit is decided for the whole set of levels
(the drawing's $INSUNITS, a level or a gap above 100), and a floor-to-floor height outside
2.4-6.0 m is never filled in silently. Invented DXFs only, read with the takeoff reader."""

from types import SimpleNamespace

import ezdxf

from app.building import detect, service
from app.sites.models import Site
from app.takeoff import reader


def _section(tmp_path, name: str, levels: list[str], insunits: int = 0, x: float = 50000):
    """An invented section: one column of level texts at x, 3000 units apart."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    for i, text in enumerate(levels):
        msp.add_text(text, dxfattribs={"height": 250, "layer": "LVL"}).set_placement((x, i * 3000))
    msp.add_line((0, 0), (12000, 0))
    path = tmp_path / f"{name}.dxf"
    doc.saveas(path)
    p = reader.read(path)
    return detect.levels(p.texts, p.unit_m or 0.001, p.units_code == 4)


def test_levels_in_mm_are_read_as_mm_and_say_so(tmp_path):
    out = _section(tmp_path, "mm", ["±0.000", "+600", "+3600", "+6600"])
    assert out["unit"] == "mm" and out["values_m"] == [0.0, 0.6, 3.6, 6.6]
    assert out["source"] == "section" and out["floor_height_m"] == 3.0
    assert "levels read in mm" in out["note"]


def test_levels_in_metres_stay_metres(tmp_path):
    out = _section(tmp_path, "m", ["±0.000", "+3.000", "+6.000"], insunits=4)  # +3.000 on a mm drawing
    assert out["unit"] == "m" and out["values_m"] == [0.0, 3.0, 6.0] and out["floor_height_m"] == 3.0
    assert "in mm" not in out["note"]


def test_a_mm_drawing_with_whole_number_levels_reads_them_as_mm(tmp_path):
    # small whole numbers: by themselves they could be metres; $INSUNITS = mm says millimetres
    out = _section(tmp_path, "insunits", ["+0", "+45", "+90"], insunits=4)
    assert out["unit"] == "mm" and out["values_m"] == [0.0, 0.045, 0.09]
    same = _section(tmp_path, "unitless", ["+0", "+45", "+90"], insunits=0)
    assert same["unit"] == "m"


def test_the_server_case_plinth_levels_give_no_100_m_floor(tmp_path):
    out = _section(tmp_path, "plinth", ["+600.000", "+700.000", "+800.000"])
    assert out["unit"] == "mm" and out["values_m"] == [0.6, 0.7, 0.8]
    assert out["floor_height_m"] is None and "100" not in out["note"]


def test_a_floor_to_floor_outside_2_4_to_6_m_is_not_filled_in(tmp_path, db):
    out = _section(tmp_path, "tall", ["±0.000", "+9.000", "+18.000"])  # metres, 9 m storeys
    assert out["floor_height_m"] is None and out.get("suspect") is True and out["source"] == "default"
    assert "the levels read look wrong (9 m floor to floor); check them" in out["note"]
    # the building draft keeps the default 3.0 m
    site = Site(code="S-SL-9001", name="Invented section", status="active")
    db.add(site)
    db.flush()
    texts = [[50, i * 3, 0.3, "LVL", t, False] for i, t in enumerate(["±0.000", "+9.000", "+18.000"])]
    cad = SimpleNamespace(texts=texts, unit_m=1.0, units_code=6, summary={}, id=None)
    d = service.draft(db, site, cad)
    assert d["settings"]["floor_height_m"] == 3.0 and d["levels"]["suspect"] is True
    assert service.elevations({**d, "floors": [{"level": 0, "type": None}, {"level": 1, "type": None}]})[1]["elevation_m"] != 9.0


def test_a_single_level_text_above_100_is_mm():
    assert detect.level_m("FFL +3600") == 3.6 and detect.level_m("FFL +3.000") == 3.0
    assert detect.level_m("+0'0\"") == 0.0 and detect.level_m("FFL +800.00 MM") == 0.8
