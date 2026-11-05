# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Drawings that convert but show nothing (Prompt 38c), with small DXFs made here with ezdxf (never a
company drawing): model space empty but a layout drawn (the layout is read and named), the content
in external references (said plainly), LibreDWG writing a DXF without its ENTITIES section (its
minimal run's entities spliced in, or the save-as-DXF message with its last warning, never "not a
real DXF"), and removing a drawing that could not be read."""

import io
import stat
from pathlib import Path

import ezdxf
import pytest

from app.config import settings
from app.sites.models import Drawing
from app.takeoff import dwg, pipeline, reader
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_takeoff import make_dxf, place, read, upload  # noqa: F401  (fixtures)


def _text(doc) -> str:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue()


def _write(doc, path: Path) -> Path:
    path.write_text(_text(doc))
    return path


def test_an_empty_model_space_reads_the_layout_with_the_most_drawn_and_says_which(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    small = doc.layouts.new("Title only")
    small.add_text("SHEET 1", dxfattribs={"insert": (5, 5), "height": 3})
    plan = doc.layouts.new("Site plan")
    for (x1, y1), (x2, y2) in [
        ((0, 0), (400, 0)),
        ((400, 0), (400, 300)),
        ((400, 300), (0, 300)),
        ((0, 300), (0, 0)),
    ]:
        plan.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "A-WALL"})
    plan.add_text("GROUND FLOOR PLAN", dxfattribs={"insert": (100, -20), "height": 5})
    p = reader.read(_write(doc, tmp_path / "layout.dxf"), "DXF")
    assert p.space == "Site plan" and p.summary()["space"] == "Site plan"
    assert p.top["LINE"] == 4 and [t[4] for t in p.texts] == ["GROUND FLOOR PLAN"]
    # a drawing in model space is read there, as before
    doc.modelspace().add_line((0, 0), (1000, 0))
    assert reader.read(_write(doc, tmp_path / "model.dxf"), "DXF").space == "Model"


def test_a_drawing_whose_content_is_in_external_references_says_so(tmp_path):
    doc = ezdxf.new("R2018")
    doc.add_xref_def("C:/arch/LOT-PLAN.dwg", "LOT-PLAN")
    doc.add_xref_def("C:/arch/GRID.dwg", "GRID")
    doc.modelspace().add_blockref("LOT-PLAN", (0, 0))
    doc.modelspace().add_blockref("GRID", (0, 0))
    doc.layouts.get("Layout1").add_text(
        "TITLE BLOCK", dxfattribs={"insert": (5, 5)}
    )  # not the drawing
    with pytest.raises(
        dwg.CadError,
        match=r"uses 2 external references \(GRID, LOT-PLAN\); ask the architect for a bound drawing \(eTransmit or Bind\)",
    ):
        reader.read(_write(doc, tmp_path / "xref.dxf"), "DXF")
    # drawn here as well: read, the references listed
    doc.modelspace().add_line((0, 0), (1000, 0))
    p = reader.read(_write(doc, tmp_path / "both.dxf"), "DXF")
    assert p.xrefs == ["GRID", "LOT-PLAN"] and p.top == {"LINE": 1}


def test_an_empty_dxf_upload_keeps_its_message(tmp_path):
    with pytest.raises(reader.EmptyDrawing, match="nothing drawn"):
        reader.read(_write(ezdxf.new("R2018"), tmp_path / "empty.dxf"), "DXF")


def _fake_dwg2dxf(tmp_path: Path, full: Path, minimal: Path | None, note: str) -> Path:
    """A converter that writes `full` (or, with -m, `minimal`) and LibreDWG's kind of log."""
    fake = tmp_path / "dwg2dxf"
    pick = (
        f'case "$*" in *" -m "*) src="{minimal}" ;; *) src="{full}" ;; esac'
        if minimal
        else f'src="{full}"'
    )
    fake.write_text(
        "#!/bin/sh\n"
        'out=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        f"{pick}\n"
        'cp "$src" "$out"\n'
        f'echo "{note}" >&2\n'
        'echo "Writing DXF file $out" >&2\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def _without_entities(doc) -> str:
    """The DXF cut where LibreDWG 0.13 stops on some drawings: after the BLOCKS section."""
    text = _text(doc)
    return text[: text.index("  0\nSECTION\n  2\nENTITIES\n")]


def test_a_dwg_converted_without_its_entities_gets_them_from_the_minimal_run(
    boss, place, db, tmp_path, monkeypatch
):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    doc.layers.add("A-WALL")
    box = doc.blocks.new("BOX")
    for (x1, y1), (x2, y2) in [
        ((0, 0), (900, 0)),
        ((900, 0), (900, 900)),
        ((900, 900), (0, 900)),
        ((0, 900), (0, 0)),
    ]:
        box.add_line((x1, y1), (x2, y2))
    msp = doc.modelspace()
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_blockref("BOX", (1000, 1000), dxfattribs={"layer": "A-WALL"})
    msp.add_text("GROUND FLOOR PLAN", dxfattribs={"insert": (0, -500), "height": 200})
    full = tmp_path / "full.dxf"
    full.write_text(_without_entities(doc))
    assert not dwg.has_entities(full.read_bytes())
    # the minimal run: entities only, its handles numbered from scratch (they clash with the tables)
    mini_doc = ezdxf.new("R2018")
    mini_doc.blocks.new("BOX")
    mini = mini_doc.modelspace()
    mini.add_line((0, 0), (5000, 0), dxfattribs={"layer": "A-WALL"})
    mini.add_blockref("BOX", (1000, 1000), dxfattribs={"layer": "A-WALL"})
    mini.add_text("GROUND FLOOR PLAN", dxfattribs={"insert": (0, -500), "height": 200})
    minimal = _write(mini_doc, tmp_path / "minimal.dxf")
    monkeypatch.setattr(
        settings,
        "dwg2dxf_path",
        str(_fake_dwg2dxf(tmp_path, full, minimal, "Warning: Unstable Class entity 547 WIPEOUT")),
    )
    c, h = boss
    _d, rev = upload(
        c, h, place["site"], b"AC1024" + b"\0" * 200, name="plan.dwg", title="Cut short"
    )
    f = read(c, h, rev)
    assert f["status"] == "ready", f["error"]
    assert f["unit_m"] == 0.001 and f["space"] == "Model"  # the header kept
    assert f["inserts"] == 1 and f["texts"] == 1
    assert f["counts"]["LINE"] == 5  # the block drawn from the full DXF's blocks


def test_a_dwg_with_nothing_readable_says_save_as_dxf_with_the_converters_last_warning(
    boss, place, db, tmp_path, monkeypatch
):
    c, h = boss
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (1, 1))
    cut = tmp_path / "cut.dxf"
    cut.write_text(_without_entities(doc))
    nothing = _write(
        ezdxf.new("R2018"), tmp_path / "nothing.dxf"
    )  # minimal run: an empty ENTITIES section
    # no entities in either run: the converter lost them
    monkeypatch.setattr(
        settings,
        "dwg2dxf_path",
        str(_fake_dwg2dxf(tmp_path, cut, cut, "ERROR: Invalid type 0x7, expected 0x5 ENDBLK")),
    )
    _d, rev = upload(c, h, place["site"], b"AC1024" + b"\0" * 200, name="a.dwg", title="Lost")
    f = read(c, h, rev)
    assert f["status"] == "failed"
    assert (
        "AutoCAD 2010 drawing (AC1024)" in f["error"]
        and "ERROR: Invalid type 0x7, expected 0x5 ENDBLK" in f["error"]
    )
    assert (
        "AutoCAD 2013 DXF" in f["error"]
        and "upload the .dxf" in f["error"]
        and "not a real DXF" not in f["error"]
    )
    # converted whole, nothing drawn anywhere: the same message, never "not a real DXF"
    monkeypatch.setattr(
        settings,
        "dwg2dxf_path",
        str(_fake_dwg2dxf(tmp_path, nothing, None, "Warning: Unhandled Class object 517 DIMASSOC")),
    )
    _d, rev = upload(c, h, place["site"], b"AC1032" + b"\0" * 200, name="b.dwg", title="Empty")
    f = read(c, h, rev)
    assert f["status"] == "failed" and "not a real DXF" not in f["error"]
    assert (
        "AutoCAD 2018 drawing (AC1032)" in f["error"]
        and "DIMASSOC" in f["error"]
        and "AutoCAD 2013 DXF" in f["error"]
    )


def test_a_failed_drawing_is_removed_from_its_card_by_planning_or_the_super_admin(
    boss, place, db, login_as
):
    c, h = boss
    did, rev = upload(c, h, place["site"], ezdxf_empty(), name="hksdfvhdsk.dxf", title="hksdfvhdsk")
    assert read(c, h, rev)["status"] == "failed"
    stored = pipeline.media(db.get(Drawing, did).revisions[0].stored_path)
    assert stored.exists()
    url = f"/api/sites/{place['site']}/building"
    # billing builds the model but may not remove drawings; the director neither
    for role in ("billing", "director"):
        oc, oh = login_as(role)
        assert oc.get(url, headers=oh).json()["can_remove"] is False
        assert oc.delete(f"{url}/revisions/{rev}", headers=oh).status_code == 403
    pc, ph = login_as("planning")
    assert pc.get(url, headers=ph).json()["can_remove"] is True
    # a drawing that was read is removed in the site's Drawings, not here
    _d2, good = upload(c, h, place["site"], make_dxf("mm"), title="Good plan")
    assert read(c, h, good)["status"] == "ready"
    assert pc.delete(f"{url}/revisions/{good}", headers=ph).status_code == 409
    r = pc.delete(f"{url}/revisions/{rev}", headers=ph)
    assert r.status_code == 200, r.text
    assert rev not in [x["revision_id"] for x in r.json()["revisions"]]
    db.expire_all()
    assert db.get(Drawing, did) is None and not stored.exists()
    assert c.delete(f"{url}/revisions/{rev}", headers=h).status_code == 404


def ezdxf_empty() -> bytes:
    return _text(ezdxf.new("R2018")).encode()
