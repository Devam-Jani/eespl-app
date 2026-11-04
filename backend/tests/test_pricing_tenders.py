"""Prompt 38, tenders: a line's unit change converts its rate, BOQ quantities written with their
unit, a revised BOQ's carried-over rates, suggested and unpriced lines block submit and the client
exports (director override with a reason), an old revision's client-format export, one rounding
for a per-sqft system on a sqm line, an empty section's subtotal and the "Unit Rate" heading."""

import io
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog
from app.tenders import boq_import, export
from app.tenders.models import BoqImport, TenderRevision
from app.timefmt import ist_today
from tests.test_tender_export import ready_to_send
from tests.test_tenders import boq, line, new_client, new_tender


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def add_line(client, headers, tid, description, unit, qty, item_no=None):
    r = client.post(
        f"/api/tenders/{tid}/lines",
        json={"description": description, "unit": unit, "qty": qty, "client_item_no": item_no},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    return line(r.json(), description) if "lines" in r.json() else r.json()


def patch(client, headers, tid, *lines):
    return client.patch(f"/api/tenders/{tid}/lines", json={"lines": list(lines)}, headers=headers)


# --- Part 2.3: a unit change converts the rate -----------------------------------------------


def test_unit_change_converts_the_rate_and_qty_or_clears_the_price(boss):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    add_line(client, headers, tid, "Invented terrace coating", "sqm", "100")
    add_line(client, headers, tid, "Invented sump coating", "sqm", "40")
    add_line(client, headers, tid, "Invented retyped coating", "sqm", "10")
    data = boq(client, headers, tid)
    terrace, sump, retyped = (
        line(data, "Invented terrace"),
        line(data, "Invented sump"),
        line(data, "Invented retyped"),
    )
    r = patch(
        client,
        headers,
        tid,
        {"id": terrace["id"], "rate": "705.77"},
        {"id": sump["id"], "rate": "500"},
        {"id": retyped["id"], "rate": "705.77"},
    )
    assert r.status_code == 200, r.text
    r = patch(
        client,
        headers,
        tid,
        {"id": terrace["id"], "unit": "sqft"},
        {"id": sump["id"], "unit": "nos"},  # sqm -> nos: no factor, the price is cleared
        {"id": retyped["id"], "unit": "Sq.ft", "qty": "120"},  # the qty typed with it stays
    )
    assert r.status_code == 200, r.text
    data = r.json()
    terrace = line(data, "Invented terrace")
    # 705.77 ÷ 10.7639 = 65.5682 -> 65.57 per sqft; 100 sqm × 10.7639 = 1076.39 sqft
    assert (terrace["unit"], terrace["rate"], terrace["qty"]) == ("sqft", "65.57", "1076.390")
    assert terrace["amount"] == "70578.89"  # 1076.39 × 65.57
    sump = line(data, "Invented sump")
    assert (sump["unit"], sump["rate"], sump["status"]) == ("nos", None, "unpriced")
    retyped = line(data, "Invented retyped")
    assert (retyped["rate"], Decimal(retyped["qty"])) == ("65.57", Decimal(120))


# --- Part 4.1: quantities written with their unit ----------------------------------------------


def test_qty_with_unit_or_rupee_text_is_read():
    for text, value in (
        ("1,250 sqm", "1250"),
        ("12.5 Sqm", "12.5"),
        ("450/-", "450"),
        ("Rs. 450", "450"),
        ("Rs 1,250/-", "1250"),
        ("₹ 75", "75"),
    ):
        assert boq_import._number(text) == Decimal(value), text
    assert boq_import._number("about twenty") is None
    rows = [
        ["Sr no", "Description", "Unit", "Qty", "Rate"],
        ["1", "Invented terrace coating", "sqm", "1,250 sqm", "Rs. 450"],
        ["2", "Invented sump coating", "sqm", "12.5 Sqm", "450/-"],
        ["3", "Invented wall coating", "sqm", "as per drawing", None],
        ["4", "Invented screed", "sqm", "QRO", None],
        ["5", "Invented pit", "sqm", "-", None],
    ]
    parsed = boq_import.parse(
        rows, 1, {"item_no": 0, "description": 1, "unit": 2, "qty": 3, "rate": 4}
    )
    qty = {ln.description: ln.qty for ln in parsed.lines}
    assert qty["Invented terrace coating"] == Decimal("1250.000")
    assert qty["Invented sump coating"] == Decimal("12.500")
    assert parsed.lines[0].client_file_rate == Decimal("450.00")
    assert parsed.lines[1].client_file_rate == Decimal("450.00")
    # a qty that is still not a number is listed; QRO and a dash are not
    assert parsed.counts()["qty_not_read"] == [{"row": 4, "text": "as per drawing"}]


# --- Part 4.2: a revised BOQ carries rates over on (item no, description, unit) ----------------


def _xlsx(path: Path, rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["Sr no", "Description", "Unit", "Qty", "Rate", "Amount"])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def _import(client, headers, tid, path, replace=False):
    with path.open("rb") as fh:
        r = client.post(
            f"/api/tenders/{tid}/boq/import", files={"file": (path.name, fh)}, headers=headers
        )
    assert r.status_code == 200, r.text
    preview = r.json()
    cols = {f: g["column"] for f, g in preview["column_map"].items()}
    r = client.post(
        f"/api/tenders/{tid}/boq/import/confirm",
        json={
            "upload_id": preview["upload_id"],
            "sheet": preview["sheet"],
            "header_row": preview["header_row"],
            "column_map": cols,
            "replace": replace,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


FIRST = [
    ["1", "Invented crystalline coating to raft", "sqm", 100, None, None],
    [None, "Invented grout injection", "nos", 10, None, None],
    [None, "Invented grout injection", "nos", 12, None, None],
    ["3", "Invented PU coating", "sqm", 20, None, None],
]
REVISED = [
    ["1", "Invented crystalline coating to raft", "sqft", 1076.39, None, None],
    [None, "Invented grout injection", "nos", 10, None, None],
    [None, "Invented grout injection", "nos", 12, None, None],
    [None, "Invented grout injection", "nos", 14, None, None],
    ["3", "Invented PU coating", "sqm", 20, None, None],
]


def test_reimport_keys_on_unit_converts_and_marks_lines_suggested(boss, tmp_path):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    _import(client, headers, tid, _xlsx(tmp_path / "first.xlsx", FIRST))
    data = boq(client, headers, tid)
    grout = [ln for ln in data["lines"] if "grout" in ln["description"]]
    r = patch(
        client,
        headers,
        tid,
        {"id": line(data, "Invented crystalline")["id"], "rate": "705.77"},
        {"id": grout[0]["id"], "rate": "100"},
        {"id": grout[1]["id"], "rate": "120"},
        {"id": line(data, "Invented PU")["id"], "rate": "300"},
    )
    assert r.status_code == 200, r.text
    report = _import(client, headers, tid, _xlsx(tmp_path / "revised.xlsx", REVISED), True)
    assert report["kept_prices"] == 4
    data = boq(client, headers, tid)
    crystal = line(data, "Invented crystalline")
    # per sqm -> per sqft: 705.77 ÷ 10.7639 = 65.57; carried over, so it needs a review
    assert (crystal["unit"], crystal["rate"], crystal["status"]) == ("sqft", "65.57", "suggested")
    grout = [ln for ln in data["lines"] if "grout" in ln["description"]]
    # each old rate once, in order: 100 and 120 (not 120 twice); the third line has none
    assert [(g["rate"], g["status"]) for g in grout] == [
        ("100.00", "suggested"),
        ("120.00", "suggested"),
        (None, "unpriced"),
    ]
    assert (line(data, "Invented PU")["rate"], line(data, "Invented PU")["status"]) == (
        "300.00",
        "suggested",
    )


# --- Part 4.3: suggested and unpriced lines block submit and the client exports ----------------


def _membrane_system(client, headers, unit="sqm", price="300", consumption="1", prep="20"):
    r = client.post(
        "/api/products",
        json={
            "code": f"P-APP-{unit}",
            "name": "APP membrane 4 mm",
            "brand": "Acme",
            "category": "membrane",
            "unit": "sqm",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post(
        f"/api/products/{pid}/prices",
        json={
            "purchase_rate": price,
            "effective_from": (ist_today() - timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/systems",
        json={
            "code": f"SYS-APP-{unit}",
            "name": "APP membrane terrace",
            "unit": unit,
            "surface_prep_per_unit": prep,
            "labour_rate": "0",
            "labour_unit": unit,
            "default_margin_percent": "20",
            "components": [{"product_id": pid, "consumption_per_unit": consumption}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_suggested_and_unpriced_lines_block_submit_and_client_exports(boss, login_as, db, tmp_path):
    client, headers = boss
    _membrane_system(client, headers)
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    add_line(client, headers, tid, "APP membrane terrace waterproofing", "sqm", "10")
    add_line(client, headers, tid, "Invented expansion joint", "rmt", "5")
    add_line(client, headers, tid, "Invented PU coating", "sqm", "2")
    data = boq(client, headers, tid)
    patch(client, headers, tid, {"id": line(data, "Invented PU")["id"], "rate": "300"})
    client.post(f"/api/tenders/{tid}/boq/suggest", headers=headers)
    data = boq(client, headers, tid)
    membrane = line(data, "APP membrane")
    assert (membrane["status"], membrane["rate"]) == ("suggested", "400.00")
    # the BOQ screen: "1 line still suggested, Rs 4,000" (10 × 400)
    assert data["totals"]["suggested_amount"] == "4000.00"
    assert data["totals"]["counts"]["suggested"] == 1
    ready_to_send(db, tid)

    r = client.post(f"/api/tenders/{tid}/submit", json={}, headers=headers)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "1 line(s) still suggested, ₹4,000.00" in detail and "1 line(s) without a rate" in detail
    for path in ("export.xlsx", "export.pdf", "export/client"):
        r = client.get(f"/api/tenders/{tid}/{path}", headers=headers)
        assert r.status_code == 409 and "still suggested" in r.json()["detail"], path
    # the internal export (never sent to the client) is not held
    r = client.get(f"/api/tenders/{tid}/export.xlsx?internal=true", headers=headers)
    assert r.status_code == 200, r.text

    # someone without sendcheck.override cannot export past it, even with a reason
    est, est_headers = login_as("estimator", email="est@example.com")
    r = est.get(
        f"/api/tenders/{tid}/export.xlsx?override_reason=Invented reason", headers=est_headers
    )
    assert r.status_code in (403, 404)
    # the director can, with a reason, which is logged
    r = client.get(
        f"/api/tenders/{tid}/export.xlsx?override_reason=Invented: client asked", headers=headers
    )
    assert r.status_code == 200, r.text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "tender.export_override"))
    r = client.post(
        f"/api/tenders/{tid}/submit",
        json={"override_reason": "Invented: due today"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # all reviewed: nothing held
    tid2 = new_tender(client, headers, new_client(client, headers, "Other Co"))["id"]
    add_line(client, headers, tid2, "Invented PU coating", "sqm", "2")
    patch(
        client, headers, tid2, {"id": boq(client, headers, tid2)["lines"][0]["id"], "rate": "300"}
    )
    assert boq(client, headers, tid2)["totals"]["suggested_amount"] == "0.00"
    assert client.get(f"/api/tenders/{tid2}/export.pdf", headers=headers).status_code == 200


# --- Part 4.4: an old revision's client-format export uses its own import -----------------------


def test_client_format_of_an_old_revision_uses_that_revisions_import(boss, db, tmp_path):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    first = [["1", "Invented PU coating", "sqm", 20, None, None]]
    revised = [
        ["0", "Invented primer", "sqm", 5, None, None],
        ["1", "Invented PU coating", "sqm", 20, None, None],
    ]
    _import(client, headers, tid, _xlsx(tmp_path / "first.xlsx", first))
    data = boq(client, headers, tid)
    patch(client, headers, tid, {"id": line(data, "Invented PU")["id"], "rate": "300"})
    ready_to_send(db, tid)
    r = client.post(f"/api/tenders/{tid}/submit", json={}, headers=headers)
    assert r.status_code == 200, r.text
    first_import = db.scalar(select(BoqImport).where(BoqImport.tender_id == tid))
    rev0 = db.scalar(select(TenderRevision).where(TenderRevision.tender_id == tid))
    assert rev0.snapshot["boq_import_id"] == first_import.id

    _import(client, headers, tid, _xlsx(tmp_path / "revised.xlsx", revised), True)
    r = client.get(f"/api/tenders/{tid}/export/client?rev=0", headers=headers)
    assert r.status_code == 200, r.text
    ws = load_workbook(io.BytesIO(r.content))["BOQ"]
    # R0's rows: the PU coating on row 2 of the first file, with R0's rate
    assert (ws["B2"].value, ws["E2"].value) == ("Invented PU coating", 300)
    assert ws["B3"].value is None


# --- Part 5: one rounding for a per-sqft system on a sqm line ----------------------------------


def test_per_sqft_system_on_a_sqm_line_rounds_once(boss):
    client, headers = boss
    # cost 371.23 × 0.1 = 37.123 per sqft, 20 % margin on the selling price
    _membrane_system(client, headers, unit="sqft", price="371.23", consumption="0.1", prep="0")
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    add_line(client, headers, tid, "APP membrane terrace waterproofing", "sqm", "1")
    client.post(f"/api/tenders/{tid}/boq/suggest", headers=headers)
    membrane = line(boq(client, headers, tid), "APP membrane")
    # 37.123 × 10.7639 = 399.5883 per sqm ÷ (1 − 0.20) = 499.49, rounded once (rounding the
    # per-sqft rate first gave 46.40 × 10.7639 = 499.45). The prompt's 479.51 is the same
    # working with the old markup (399.5883 × 1.2); the margin is on the selling price now.
    assert (membrane["rate"], membrane["cost_rate"]) == ("499.49", "399.59")


# --- Part 5: an empty section's subtotal, the "Unit Rate" heading ------------------------------


def test_empty_section_subtotal_is_zero_not_self_referencing():
    snapshot = {
        "tender": {
            "code": "T-1",
            "name": "Invented",
            "client_name": None,
            "site_name": None,
            "site_city": None,
            "site_state": None,
        },
        "sections": [
            {"id": 1, "title": "Empty section", "note": None, "sort_order": 1, "total": "0"},
        ],
        "lines": [],
        "tc": [],
        "totals": {"subtotal": "0", "gst_percent": "18", "gst": "0", "grand_total": "0"},
    }
    doc = export.Document(
        export.Company("Invented Co", None, None, None),
        snapshot,
        "R0",
        date(2026, 1, 1),
        Decimal(18),
    )
    ws = load_workbook(io.BytesIO(export.xlsx(doc))).active
    row = next(r for r in range(1, ws.max_row + 1) if ws[f"B{r}"].value == "Total — Empty section")
    assert ws[f"F{row}"].value == 0


def test_unit_rate_heading_maps_to_rate_not_unit():
    cols = boq_import.guess_columns(["Sr no", "Description", "Qty", "Unit Rate", "Amount"])
    assert cols["rate"]["column"] == 3
    assert "unit" not in cols
    cols = boq_import.guess_columns(["Sr no", "Description", "Unit Rate", "Unit", "Qty"])
    assert (cols["rate"]["column"], cols["unit"]["column"]) == (2, 3)
