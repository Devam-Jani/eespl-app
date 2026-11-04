# ruff: noqa: E501, F811  (invented offer wording unwrapped; the shared `lib` fixture is imported)
"""Prompt 38, quotations: a unit change converts the rate, sent revisions keep their prices, item
totals per option, "if required" printed as extra, unpriced lines on the send checklist, GST
and the amount in words under the total, the old Word offer importer's numbers and units, the
consistency check's zero coverage, the revision diff of a repeated line, rounded areas.
Invented data only."""

import io
from decimal import Decimal

import pdfplumber
import pytest
from docx import Document
from sqlalchemy import select

from app.config import settings
from app.quotations import checks, render
from app.quotations import importer as imp
from app.quotations.models import OfferLine, Quotation
from tests.test_quotations import (  # noqa: F401  (fixtures)
    invented_offer,
    lib,
    lines_of,
    new_quotation,
)


def D(x) -> Decimal:
    return Decimal(str(x))


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


@pytest.fixture
def lb(lib, db):
    """The shared library with the tank and "if required" lines' ids too."""

    def oid(text):
        return db.scalar(select(OfferLine.id).where(OfferLine.description == text))

    return {**lib, "l_tank": oid("Tank coating"), "l_req": oid("Pressure grouting")}


def _line(q, offer_line_id):
    return next(ln for ln in lines_of(q) if ln["offer_line_id"] == offer_line_id)


def _put(client, h, q, ln, body):
    return client.put(f"/api/quotations/{q['id']}/lines/{ln['id']}", json=body, headers=h)


# --- Part 2.3: a unit change converts the rate ---------------------------------------------------


def test_unit_change_converts_a_typed_rate_and_the_qty(boss, lb):
    client, h = boss
    q = new_quotation(client, h, lb)
    tank = q["items"][1]
    r = client.post(
        f"/api/quotations/{q['id']}/items/{tank['id']}/lines",
        json={"description": "Invented membrane", "uom": "sqm", "rate": "705.77"},
        headers=h,
    )
    ln = next(x for x in r.json()["items"][1]["lines"] if x["description"] == "Invented membrane")
    r = _put(client, h, q, ln, {"qty": "100"})
    # the screen sends the unchanged qty with the new unit: it is not a retyped qty
    r = _put(client, h, q, ln, {"uom": "sqft", "qty": "100.000", "description": ln["description"]})
    assert r.status_code == 200, r.text
    ln = next(x for x in lines_of(r.json()) if x["id"] == ln["id"])
    # 705.77 / 10.7639 = 65.568... -> 65.57 per sqft (was 705.77 "per sqft")
    assert ln["uom"] == "sqft" and D(ln["rate"]) == D("65.57") and ln["overridden"]
    assert D(ln["qty"]) == D("1076.390")  # 100 sqm x 10.7639
    # a retyped qty is kept as typed
    r = _put(client, h, q, ln, {"uom": "sqm", "qty": "90"})
    ln = next(x for x in lines_of(r.json()) if x["id"] == ln["id"])
    assert D(ln["qty"]) == D("90") and D(ln["rate"]) == D("705.79")  # 65.57 x 10.7639 = 705.79
    # no factor (sqm -> nos): the price is cleared, not carried over
    r = _put(client, h, q, ln, {"uom": "nos"})
    ln = next(x for x in lines_of(r.json()) if x["id"] == ln["id"])
    assert ln["rate"] is None and ln["qty"] is None and not ln["overridden"]
    assert "enter a rate" in ln["rate_note"]


def test_fixed_rate_refill_converts_to_the_line_unit(boss, lb, db):
    client, h = boss
    q = new_quotation(client, h, lb)
    fix = _line(q, lb["l_fix"])  # the library's fixed rate: Rs 45 per sqft
    r = _put(client, h, q, fix, {"uom": "sqm"})
    fix = _line(r.json(), lb["l_fix"])
    assert D(fix["rate"]) == D("484.38")  # 45 x 10.7639 = 484.3755
    # refilling from the library keeps the line's unit (was Rs 45.00 "per sqm")
    r = client.post(f"/api/quotations/{q['id']}/refill-rates", headers=h)
    assert r.status_code == 200, r.text
    assert D(_line(r.json(), lb["l_fix"])["rate"]) == D("484.38")
    # no factor: refused, no rate
    r = _put(client, h, q, fix, {"uom": "nos"})
    r = client.post(f"/api/quotations/{q['id']}/refill-rates", headers=h)
    fix = _line(r.json(), lb["l_fix"])
    assert fix["rate"] is None and "per sqft" in fix["rate_note"]
    # the default-rate path (a library-sourced line whose item is gone) converts too
    ol = db.get(OfferLine, lb["l_tank"])
    ol.rate_source, ol.default_rate = "library", D(49)
    db.commit()
    tank = _line(q, lb["l_tank"])
    _put(client, h, q, tank, {"uom": "sqm"})
    r = client.post(f"/api/quotations/{q['id']}/refill-rates", headers=h)
    assert D(_line(r.json(), lb["l_tank"])["rate"]) == D("527.43")  # 49 x 10.7639 = 527.4311


# --- Part 4.5: a sent revision keeps its prices --------------------------------------------------


def test_sent_revision_refuses_money_edits(boss, lb):
    client, h = boss
    q = new_quotation(client, h, lb)
    r = client.post(f"/api/quotations/{q['id']}/status", json={"status": "sent"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["can_edit_prices"] is False
    tank = _line(q, lb["l_tank"])
    for body in ({"rate": "40"}, {"qty": "10"}, {"uom": "sqm"}, {"if_required": True}):
        r = _put(client, h, q, tank, body)
        assert (
            r.status_code == 409 and "Make a new revision to change prices" in r.json()["detail"]
        ), body
    base = f"/api/quotations/{q['id']}"
    assert client.post(f"{base}/refill-rates", headers=h).status_code == 409
    assert client.delete(f"{base}/lines/{tank['id']}", headers=h).status_code == 409
    assert (
        client.post(
            f"{base}/items/{q['items'][1]['id']}/lines",
            json={"description": "Extra", "uom": "nos", "rate": "10"},
            headers=h,
        ).status_code
        == 409
    )
    # wording still changes (the screen sends the unchanged money fields with it)
    r = _put(
        client,
        h,
        q,
        tank,
        {
            "description": "Tank coating, two coats",
            "uom": "sqft",
            "qty": None,
            "if_required": False,
            "client_scope": False,
        },
    )
    assert r.status_code == 200, r.text
    # a new revision takes price changes
    r1 = client.post(f"{base}/revision", headers=h).json()
    assert r1["can_edit_prices"] is True
    r = _put(client, h, r1, _line(r1, lb["l_tank"]), {"rate": "40"})
    assert r.status_code == 200, r.text


# --- Part 4.6 and the GST line: item totals per option, "if required" as extra --------------------


def _priced(client, h, lb):
    q = new_quotation(client, h, lb)
    for oid, rate, qty in (
        (lb["l_sys"], "600", "100"),  # option 1: 60,000
        (lb["l_fix"], "45", "1000"),  # option 2: 45,000
        (lb["l_lib"], "27", "1000"),  # both options: 27,000
        (lb["l_req"], "350", "10"),  # if required: 3,500 extra
        (lb["l_tank"], "49", "100"),  # tank: 4,900
    ):
        r = _put(client, h, q, _line(q, oid), {"rate": rate, "qty": qty})
        assert r.status_code == 200, r.text
    return r.json()


def test_item_totals_per_option_and_if_required_extra_and_gst(boss, lb, db):
    client, h = boss
    q = _priced(client, h, lb)
    terrace = q["items"][0]
    assert [(o["option"], D(o["total"])) for o in terrace["option_totals"]] == [
        ("1", D("87000.00")),
        ("2", D("72000.00")),
    ]
    assert D(q["total"]) == D("91900.00")  # 87,000 (option 1) + 4,900
    # GST @18% on 91,900 = 16,542; total with GST 1,08,442
    assert D(q["gst_amount"]) == D("16542.00") and D(q["total_with_gst"]) == D("108442.00")
    words = "Rupees One Lakh Eight Thousand Four Hundred Forty Two Only"
    assert q["total_with_gst_words"] == words
    doc = render.build(db, db.get(Quotation, q["id"]))
    b = doc.budgets[0]
    assert b.subtotals == [
        ("Item total, Option 1", "87,000.00"),
        ("Item total, Option 2", "72,000.00"),
    ]
    assert doc.budgets[1].subtotals == [("Item total", "4,900.00")]
    req = next(r for r in b.rows if "Pressure grouting" in r.description)
    assert req.amount == "3,500.00 (extra, if required)"
    gst = "GST @18% extra: Rs 16,542.00, total with GST Rs 1,08,442.00"
    html = client.get(f"/api/quotations/{q['id']}/preview", headers=h).json()["html"]
    for text in (
        "Item total, Option 1",
        "Item total, Option 2",
        "extra, if required",
        "Total (excluding GST)",
        gst,
        words,
    ):
        assert text in html, text
    d = Document(io.BytesIO(client.get(f"/api/quotations/{q['id']}/docx", headers=h).content))
    text = "\n".join(p.text for p in d.paragraphs) + "\n".join(
        c.text for t in d.tables for row in t.rows for c in row.cells
    )
    for t in ("Item total, Option 1", "Item total, Option 2", "extra, if required", gst, words):
        assert t in text, t
    pdf = client.get(f"/api/quotations/{q['id']}/pdf", headers=h).content
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        text = " ".join((pg.extract_text() or "").replace("\n", " ") for pg in p.pages)
    for t in (
        "Item total, Option 1",
        "Item total, Option 2",
        "16,542.00",
        "1,08,442.00",
        "Lakh Eight Thousand",
    ):
        assert t in text, t


# --- Part 4.7: unpriced lines on the send checklist ----------------------------------------------


def test_send_checklist_lists_lines_without_a_rate(boss, lb, db):
    client, h = boss
    q = new_quotation(client, h, lb)
    for oid in (lb["l_fix"], lb["l_tank"]):
        ol = db.get(OfferLine, oid)
        ol.default_rate = None
    db.commit()
    client.post(f"/api/quotations/{q['id']}/refill-rates", headers=h)
    r = client.post(f"/api/quotations/{q['id']}/status", json={"status": "sent"}, headers=h)
    assert r.status_code == 409 and "2 lines have no rate" in r.json()["detail"], r.text
    r = client.post(
        f"/api/quotations/{q['id']}/status",
        json={"status": "sent", "override_reason": "Client asked for the open items as on request"},
        headers=h,
    )
    assert r.status_code == 200, r.text


# --- Part 4.8: the old Word offer importer -------------------------------------------------------


def test_importer_reads_the_first_number_and_more_units():
    assert imp._decimal("Rs. 1,250/-") == D("1250")  # was 0.125
    assert imp._decimal("625.00 (18% GST extra)") == D("625.00")  # was 625.0018
    assert imp._decimal("550-600") == D("550")  # was 550600
    assert imp._rate("550-600") == (D("550"), "range")
    assert imp._rate("625.00") == (D("625.00"), None)
    for text, unit in (
        ("Sq. Mtr.", "sqm"),
        ("Per Sqm", "sqm"),
        ("M2", "sqm"),
        ("Sq.Meter", "sqm"),
        ("RM", "rmt"),
        ("Each", "nos"),
        ("SQ FT", "sqft"),
        ("R FT", "rft"),
    ):
        assert imp._uom(text) == unit, text
    assert imp._uom("Bag") is None  # was sqft
    res = imp.Result()
    rows = [
        [["1."], ["Invented coating"], ["Bag"], ["450.00"]],
        [["2."], ["Invented grout"], ["Sq. Mtr."], ["Rs. 1,250/-"]],
        [["3."], ["Invented sealant"], ["RM"], ["550-600"]],
    ]
    out = imp._lines(rows, imp.Fixer(res), 1, "Terrace", res)
    assert [(x["uom"], x["rate"]) for x in out] == [
        ("sqft", None),
        ("sqm", D("1250")),
        ("rmt", D("550")),
    ]
    assert any("“Bag”" in n and "450.00" in n for n in res.notes)
    assert any("550-600" in n and "range" in n for n in res.notes)


def test_importer_dry_run_lists_what_a_fresh_read_would_change(db, tmp_path):
    path = invented_offer(tmp_path / "offer.docx")
    imp.import_offer(db, path)
    db.commit()
    r = imp.recheck(db, path)
    assert r["rows"] > 0 and r["matched"] == r["rows"]
    assert r["rate_changes"] == [] and r["unit_changes"] == []
    pipe = db.scalar(select(OfferLine).where(OfferLine.description == "Pipe sleeve packing"))
    pipe.default_rate, pipe.uom = D("0.40"), "sqft"  # as an older read could have left it
    db.commit()
    r = imp.recheck(db, path)
    assert [(old, new) for _, old, new in r["rate_changes"]] == [(D("0.40"), D("400.00"))]
    assert [(old, new) for _, old, new in r["unit_changes"]] == [("sqft", "nos")]
    db.refresh(pipe)
    assert pipe.default_rate == D("0.40")  # nothing written


# --- Part 5 --------------------------------------------------------------------------------------


def test_coverage_bound_of_zero_is_skipped():
    assert checks.consumption("coverage of 0 - 5 sq. mtr. per kg") == []
    spec = [{"sections": [{"steps": [{"text": "Coverage of 0 - 5 sq. mtr. per Kg."}]}]}]
    assert checks.check(spec, ["Primer 0.25 kg / m2"]) == []


def test_revision_diff_keeps_a_repeated_library_line(boss, lb):
    client, h = boss
    q = new_quotation(client, h, lb)
    tank = q["items"][1]
    client.post(
        f"/api/quotations/{q['id']}/items/{tank['id']}/lines",
        json={"offer_line_id": lb["l_tank"]},
        headers=h,
    )
    r1 = client.post(f"/api/quotations/{q['id']}/revision", headers=h).json()
    first, second = r1["items"][1]["lines"]
    assert first["offer_line_id"] == second["offer_line_id"] == lb["l_tank"]
    _put(client, h, r1, first, {"rate": "44"})  # the first copy only
    diff = client.get(f"/api/quotations/{r1['id']}/diff", headers=h).json()
    assert [(D(c["old_rate"]), D(c["new_rate"])) for c in diff["changed"]] == [(D(49), D(44))]
    assert diff["added"] == [] and diff["removed"] == []


def test_reference_areas_are_rounded():
    assert render.fmt_area(D("1234.6")) == "1,235"  # was cut to 1,234
    assert render.fmt_area(D("1234.4")) == "1,234"
    assert render.fmt_area(D("10.5")) == "11"
    assert render.fmt_money(D("0.125")) == "0.13"  # half up


def test_a_rate_working_cannot_reprice_a_sent_quotation(boss, lb, db):
    """The rate working's Apply is the third way to change a sent revision's prices: refused too."""
    from fastapi import HTTPException

    from app.costing import working
    from app.costing.models import RateWorking

    client, h = boss
    q = new_quotation(client, h, lb)
    assert client.post(f"/api/quotations/{q['id']}/status", json={"status": "sent"}, headers=h).status_code == 200
    w = RateWorking(quotation_id=q["id"])
    db.add(w)
    db.commit()
    with pytest.raises(HTTPException) as e:
        working.apply_rates(db, w)
    assert e.value.status_code == 409 and "Make a new revision to change prices" in e.value.detail
