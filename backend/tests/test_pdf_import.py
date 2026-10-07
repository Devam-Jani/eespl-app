"""PDF client BOQs (invented PDFs drawn with reportlab in the test) and the channel rename."""

import io
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select, text

from app.config import settings
from app.db import SessionLocal, engine
from app.masters.models import Channel, LibraryLine
from app.masters.rate_policy import History, Obs, backtest, file_order, load_histories
from app.tenders import boq_import
from tests.test_tenders import confirm, new_client, new_tender

HEADER = ["Sr No", "Description of Item", "Unit", "Qty", "Rate"]
WIDTHS = [45, 330, 50, 60, 70]


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def _table(rows, spans=()):
    t = Table(rows, colWidths=WIDTHS)
    t.setStyle(
        TableStyle(
            [("GRID", (0, 0), (-1, -1), 0.5, "black"), ("FONTSIZE", (0, 0), (-1, -1), 8), *spans]
        )
    )
    return t


def _pdf(*flowables) -> bytes:
    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=landscape(A4)).build(list(flowables))
    return out.getvalue()


def three_page_boq() -> bytes:
    """Page 1: title, header, section 1 with two items (one with unit/qty/rate cells spanning two
    description rows). Page 2: header repeated, section 2, an item whose text runs on into the
    next row, QRO and NQ items, a sub-total. Page 3: header repeated, a row continuing the last
    item of page 2, a main item, then the terms & conditions."""
    title = Paragraph("Waterproofing BOQ for Invented Towers", getSampleStyleSheet()["Title"])
    page1 = _table(
        [
            HEADER,
            ["1", "Basement waterproofing", "", "", ""],
            ["a)", "Crystalline coating to raft with two coats", "sqm", "120.5", "450"],
            ["b)", "Pipe sleeve sealing with polymer mortar", "nos", "", ""],
            ["", "for pipes up to 110 mm", "", "", ""],
        ],
        spans=[("SPAN", (2, 3), (2, 4)), ("SPAN", (3, 3), (3, 4)), ("SPAN", (4, 3), (4, 4))],
    )
    # the spanned cells hold the values of item b) (written on the first row of the span)
    page1._cellvalues[3][3] = "12"
    page1._cellvalues[3][4] = "350"
    page2 = _table(
        [
            HEADER,
            ["2", "Terrace waterproofing", "", "", ""],
            ["a)", "APP membrane 4 mm thick laid over terrace slab,", "sqm", "300", "520"],
            ["", "including primer and 100 mm laps", "", "", ""],
            ["b)", "Protective screed 50 mm over membrane", "sqm", "QRO", "260"],
            ["c)", "Brick bat coba 100 mm", "sqm", "NQ", ""],
            ["d)", "Expansion joint sealing with PU sealant", "rmt", "40", "310"],
            ["", "Sub Total of Terrace", "", "", ""],
        ]
    )
    page3 = _table(
        [
            HEADER,
            ["", "with backer rod, complete", "", "", ""],
            ["3", "Lift pit injection grouting", "Pair", "2", "1500"],
            ["", "Terms & Conditions", "", "", ""],
            ["1", "Water and power by the client", "", "", ""],
        ]
    )
    return _pdf(title, Spacer(1, 12), page1, PageBreak(), page2, PageBreak(), page3)


def _grid(data: bytes, tmp_path: Path):
    path = tmp_path / "boq.pdf"
    path.write_bytes(data)
    return boq_import.read_grid(path)


def _parse(db, grid):
    from app.masters.units import load_aliases

    sheet = boq_import.choose_sheet(grid)[0]
    rows = grid[sheet["name"]]
    guess = boq_import.header_guess(rows, sheet["header_row"] - 1)
    cols = {f: g["column"] for f, g in guess.items()}
    return sheet, boq_import.parse(rows, sheet["header_row"], cols, load_aliases(db))


def test_three_page_pdf_boq(db, tmp_path):
    grid = _grid(three_page_boq(), tmp_path)
    assert grid.page_count == 3
    sheet, parsed = _parse(db, grid)
    pages = grid.pages[sheet["name"]]
    assert [s.title for s in parsed.sections] == [
        "1 Basement waterproofing",
        "2 Terrace waterproofing",
    ]
    lines = [
        (
            ln.item_no,
            ln.description,
            ln.unit,
            ln.qty,
            ln.qty_note,
            ln.client_file_rate,
            boq_import.page_label(pages, ln.rows),
        )
        for ln in parsed.lines
    ]
    assert lines == [
        (
            "a)",
            "Basement waterproofing — Crystalline coating to raft with two coats",
            "sqm",
            Decimal("120.500"),
            None,
            Decimal("450.00"),
            "p. 1",
        ),
        # unit, qty and rate span two description rows: one item
        (
            "b)",
            "Basement waterproofing — Pipe sleeve sealing with polymer mortar for pipes up to "
            "110 mm",
            "nos",
            Decimal("12.000"),
            None,
            Decimal("350.00"),
            "p. 1",
        ),
        (
            "a)",
            "Terrace waterproofing — APP membrane 4 mm thick laid over terrace slab, including "
            "primer and 100 mm laps",
            "sqm",
            Decimal("300.000"),
            None,
            Decimal("520.00"),
            "p. 2",
        ),
        (
            "b)",
            "Terrace waterproofing — Protective screed 50 mm over membrane",
            "sqm",
            None,
            "QRO",
            Decimal("260.00"),
            "p. 2",
        ),
        ("c)", "Terrace waterproofing — Brick bat coba 100 mm", "sqm", None, "NQ", None, "p. 2"),
        # its last words are on page 3, under the repeated header
        (
            "d)",
            "Terrace waterproofing — Expansion joint sealing with PU sealant with backer rod, "
            "complete",
            "rmt",
            Decimal("40.000"),
            None,
            Decimal("310.00"),
            "p. 2–3",
        ),
        (
            "3",
            "Lift pit injection grouting",
            None,
            Decimal("2.000"),
            None,
            Decimal("1500.00"),
            "p. 3",
        ),
    ]
    counts = parsed.counts()
    assert (counts["lines"], counts["sections"], counts["qro"], counts["nq"]) == (7, 2, 1, 1)
    assert counts["skipped_by_reason"] == {"total row": 1, "terms & conditions block": 2}
    assert counts["unrecognised_units"] == {"Pair": 1}
    # the repeated headers are gone: only one header row in the whole grid
    assert sum(1 for r in grid[sheet["name"]] if r and r[0] == "Sr No") == 1


def test_picks_the_boq_table_among_two(db, tmp_path):
    info = Table(
        [["Name of work", "Invented Towers"], ["Date", "07-10-2026"]], colWidths=[120, 200]
    )
    info.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    boq = _table(
        [
            HEADER,
            ["1", "Crystalline coating to raft", "sqm", "100", "450"],
            ["2", "Pipe sleeve sealing", "nos", "10", "350"],
        ]
    )
    contacts = Table([["Engineer", "Phone"], ["A. Person", "99999 00000"]], colWidths=[120, 200])
    contacts.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    grid = _grid(_pdf(info, Spacer(1, 20), boq, Spacer(1, 20), contacts), tmp_path)
    sheet, parsed = _parse(db, grid)
    assert [(ln.item_no, ln.description, ln.qty) for ln in parsed.lines] == [
        ("1", "Crystalline coating to raft", Decimal("100.000")),
        ("2", "Pipe sleeve sealing", Decimal("10.000")),
    ]
    assert not any("Engineer" in str(c) or "Name of work" in str(c) for r in grid["PDF"] for c in r)


def _scanned_pdf() -> bytes:
    img = Image.new("RGB", (400, 200), "white")
    for x in range(20, 380):
        img.putpixel((x, 100), (0, 0, 0))
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.drawImage(ImageReader(img), 50, 500, width=400, height=200)
    c.showPage()
    c.save()
    return out.getvalue()


def _upload(client, headers, tid, data, name="boq.pdf"):
    return client.post(
        f"/api/tenders/{tid}/boq/import", files={"file": (name, data)}, headers=headers
    )


def test_pdf_import_through_the_api(boss):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    r = _upload(client, headers, tid, three_page_boq())
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["page_count"] == 3 and preview["sheet"] == "PDF"
    assert [row["page"] for row in preview["rows"] if row["type"] == "line"][-2:] == [
        "p. 2–3",
        "p. 3",
    ]
    assert confirm(client, headers, tid, preview).status_code == 200
    lines = client.get(f"/api/tenders/{tid}/boq", headers=headers).json()["lines"]
    assert [(ln["source_page"], ln["source_page_to"]) for ln in lines][-2:] == [(2, 3), (3, 3)]
    # client format needs a spreadsheet; the EESPL export still works
    r = client.get(f"/api/tenders/{tid}/export/client", headers=headers)
    assert r.status_code == 409 and "PDF" in r.json()["detail"]
    assert client.get(f"/api/tenders/{tid}/export.xlsx", headers=headers).status_code == 200


def test_scanned_pdf_is_refused(boss):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    r = _upload(client, headers, tid, _scanned_pdf())
    assert r.status_code == 422 and r.json()["detail"] == "Scanned PDF, OCR not supported yet"


def test_split_rates_and_two_quantity_columns(db):
    rows = [
        ["", "", "", "TOTAL QUANTITY", None, "", "", "", ""],
        [
            "S. No.",
            "Description of Item",
            "Unit",
            "Up to Plinth",
            "Above plinth",
            "Material Rate",
            "Application Rate",
            "Total Rate (M+L)",
            "Remarks",
        ],
        ["#", "GENERAL NOTES :", "", "", "", "", "", "", ""],
        ["1", "Quantities are indicative", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", ""],
        ["1", "Terrace waterproofing", "sqm", "1,200", "3 ,936", "605", "400", "1005", ""],
    ]
    guess = boq_import.header_guess(rows, 1)
    cols = {f: g["column"] for f, g in guess.items()}
    assert (cols["qty"], cols["qty2"], cols["rate"]) == (3, 4, 7)
    assert (cols["material_rate"], cols["application_rate"]) == (5, 6)
    parsed = boq_import.parse(rows, 2, cols)
    (line,) = parsed.lines
    assert line.qty == Decimal("5136.000")  # the two quantity columns added
    assert line.client_remarks == "Up to Plinth: 1,200; Above plinth: 3 ,936"
    assert (line.client_file_rate, line.client_material_rate, line.client_application_rate) == (
        Decimal("1005.00"),
        Decimal("605.00"),
        Decimal("400.00"),
    )
    assert parsed.counts()["skipped_by_reason"] == {"general notes": 2, "blank row": 1}


# --- channels -----------------------------------------------------------------------------------


def _alembic() -> Config:
    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    return cfg


def test_channel_migration_moves_folders_and_keeps_the_backtest():
    engine.dispose()
    command.downgrade(_alembic(), "0011")
    try:
        lines = [
            ("TAPANBHAI", "t/a.xlsx", 100),
            ("HI TECH", "h/b.xlsx", 110),
            ("TAPANBHAI", "t/c.xlsx", 130),
        ]
        with engine.begin() as conn:
            item = conn.execute(
                text(
                    "INSERT INTO library_items (source_key, match_key, description, unit, "
                    "latest_client, latest_source_file) VALUES ('k1', 'm1', 'Crystalline coating', "
                    "NULL, 'TAPANBHAI', 'c.xlsx') RETURNING id"
                )
            ).scalar_one()
            for i, (folder, file, rate) in enumerate(lines):
                conn.execute(
                    text(
                        "INSERT INTO library_lines (source_key, library_item_id, client_folder, "
                        "file, description, rate) "
                        "VALUES (:k, :i, :f, :file, 'Crystalline coating', :r)"
                    ),
                    {"k": f"l{i}", "i": item, "f": folder, "file": file, "r": rate},
                )
            conn.execute(text("UPDATE company_profile SET rate_policy = 'client_median'"))
        # what the backtest gave before the rename (folders as written)
        order = file_order({item: {f for _, f, _ in lines}}, {item: "t/c.xlsx"})
        before = backtest(
            {
                item: History(
                    item,
                    None,
                    "t/c.xlsx",
                    [Obs(Decimal(r), f, folder, order[f]) for folder, f, r in lines],
                )
            }
        )
    finally:
        engine.dispose()
        command.upgrade(_alembic(), "head")
    with SessionLocal() as db:
        channels = {c.name: c.id for c in db.scalars(select(Channel))}
        assert set(channels) == {"TAPANBHAI", "HI TECH"}
        moved = db.execute(select(LibraryLine.channel, LibraryLine.channel_id)).all()
        assert {(name, cid) for name, cid in moved} == {
            ("TAPANBHAI", channels["TAPANBHAI"]),
            ("HI TECH", channels["HI TECH"]),
        }
        assert db.scalar(text("SELECT latest_channel FROM library_items")) == "TAPANBHAI"
        assert db.scalar(text("SELECT rate_policy FROM company_profile")) == "channel_median"
        after = backtest(load_histories(db))
    rename = {"client_last": "channel_last", "client_median": "channel_median"}
    assert [{**r, "policy": rename.get(r["policy"], r["policy"])} for r in before] == after


def test_tender_needs_a_client_or_a_channel(boss):
    client, headers = boss
    r = client.post("/api/tenders", json={"name": "No one"}, headers=headers)
    assert r.status_code == 422
    channel = client.post(
        "/api/channels", json={"name": "Tapanbhai", "type": "salesperson"}, headers=headers
    ).json()
    r = client.post(
        "/api/tenders", json={"name": "Via channel", "channel_id": channel["id"]}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert (r.json()["client_name"], r.json()["channel_name"]) == (None, "Tapanbhai")
    listed = client.get(f"/api/tenders?channel_id={channel['id']}", headers=headers).json()
    assert [t["name"] for t in listed["items"]] == ["Via channel"]
    assert client.delete(f"/api/channels/{channel['id']}", headers=headers).status_code == 409
