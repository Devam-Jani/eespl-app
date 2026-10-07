"""Tenders: client BOQ import, auto-pricing, margins, totals, permissions, numbering, T&C."""

import threading
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.masters.models import LibraryItem, TcClause, TcTemplate, TcTemplateClause
from app.masters.units import load_aliases
from app.models import AuditLog, Role, RolePermission
from app.tenders import boq_import, pricing
from app.tenders.service import next_code

FIXTURES = Path(__file__).parent / "fixtures"
XLSX = FIXTURES / "client_boq.xlsx"
CSV = FIXTURES / "client_boq.csv"

COST_KEYS = {
    "cost_rate",
    "margin_percent",
    "source",
    "system_id",
    "library_item_id",
    "ref_id",
    "cost_total",
    "margin_amount",
    "library_stats",
    "system_breakdown",
}


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


def parse_file(db, path):
    grid = boq_import.read_grid(path)
    sheet = boq_import.choose_sheet(grid)[0]
    guess = boq_import.guess_columns(grid[sheet["name"]][sheet["header_row"] - 1])
    cols = {f: g["column"] for f, g in guess.items()}
    return sheet, boq_import.parse(grid[sheet["name"]], sheet["header_row"], cols, load_aliases(db))


def lines_by_text(parsed):
    return {ln.description.split(" — ")[-1][:20]: ln for ln in parsed.lines}


# --- parsing -------------------------------------------------------------------------------------


def test_import_xlsx_structure(db):
    sheet, parsed = parse_file(db, XLSX)
    assert (sheet["name"], sheet["header_row"]) == ("BOQ", 4)  # skips the cover sheet, row 4
    assert [s.title for s in parsed.sections] == [
        "1 Basement waterproofing",
        "2 Terrace waterproofing",
        "5 External areas",  # heading merged across B:G
    ]
    counts = parsed.counts()
    assert {k: counts[k] for k in ("lines", "sections", "qro", "nq", "skipped")} == {
        "lines": 8,
        "sections": 3,
        "qro": 2,
        "nq": 1,
        "skipped": 6,
    }
    assert counts["skipped_by_reason"] == {
        "blank row": 2,
        "total row": 2,
        "terms & conditions block": 2,
    }
    assert counts["unrecognised_units"] == {"Pair": 1}

    by = lines_by_text(parsed)
    membrane = by["APP membrane 4 mm th"]
    assert membrane.description.endswith(
        "laid over terrace slab, including primer and 100 mm laps, complete."
    )  # the continuation row is joined
    assert membrane.item_no == "a)" and membrane.rows == [10, 11]
    assert by["Crystalline coating "].unit == "sqm"  # "Sq.Mt"
    assert by["Pipe sleeve sealing "].unit == "nos"  # "Nos."
    screed, joint = by["Protective screed 50"], by["Expansion joint seal"]
    assert (screed.qty, screed.qty_note, screed.client_file_rate) == (None, "QRO", Decimal("260"))
    assert (joint.qty, joint.qty_note, joint.unit) == (None, "QRO", "rmt")  # "Rate only"
    coba = by["Brick bat coba with "]
    assert (coba.qty_note, coba.status, coba.client_remarks) == ("NQ", "not_quoted", "By others")
    lift = by["Lift pit injection g"]
    assert (lift.unit, lift.unit_raw, lift.qty) == (None, "Pair", Decimal("2.000"))
    assert lift.client_file_rate == Decimal("1500.00")  # 1500.004 rounded half up
    assert by["Planter box waterpro"].qty == Decimal("40.123")


def test_import_csv_with_rate_only(db):
    sheet, parsed = parse_file(db, CSV)
    assert sheet["header_row"] == 1
    assert [s.title for s in parsed.sections] == ["A Toilet waterproofing"]
    assert [(ln.item_no, ln.unit, ln.qty, ln.qty_note) for ln in parsed.lines] == [
        ("A.1", "sqm", Decimal("85.000"), None),
        ("A.2", "nos", Decimal("16.000"), None),
        ("B", "sqm", None, "QRO"),  # "RO"
    ]
    assert parsed.counts()["skipped_by_reason"] == {"blank row": 1, "total row": 1}


@pytest.mark.parametrize(
    "header, expected",
    [
        (
            [
                "Sr. No.",
                "Description of Item",
                "Unit",
                "Qty",
                "Rate (Rs.)",
                "Amount (Rs.)",
                "Remarks",
            ],
            {
                "item_no": 0,
                "description": 1,
                "unit": 2,
                "qty": 3,
                "rate": 4,
                "amount": 5,
                "remarks": 6,
            },
        ),
        (
            [
                None,
                "S.N",
                "Item",
                "Detail Description",
                "UOM",
                "Quantity",
                "Unit Rate",
                "Total Amount",
                "Make",
            ],
            {
                "item_no": 1,
                "description": 2,
                "description2": 3,
                "unit": 4,
                "qty": 5,
                "rate": 6,
                "amount": 7,
                "product": 8,
            },
        ),
        (
            [
                "Item No",
                "Particulars",
                "Units",
                "Qty",
                "Sika Rate",
                "Saint Gobain Rate",
                "EESPL Remarks",
            ],
            {"item_no": 0, "description": 1, "unit": 2, "qty": 3, "rate": 4, "our_remarks": 6},
        ),
    ],
)
def test_column_guessing(header, expected):
    guess = boq_import.guess_columns(header)
    assert {f: g["column"] for f, g in guess.items()} == expected
    assert all(
        g["confidence"] >= 0.75 for f, g in guess.items() if f != "rate" or not g["alternatives"]
    )
    if "Sika Rate" in header:  # two rate columns: the first, with lower confidence
        assert guess["rate"]["confidence"] == 0.6 and guess["rate"]["alternatives"] == ["F"]


# --- helpers for the API tests -------------------------------------------------------------------


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def new_client(client, headers, name="Example Developers"):
    r = client.post("/api/clients", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def new_tender(client, headers, client_id, **extra):
    r = client.post(
        "/api/tenders",
        json={"name": "Invented Towers", "client_id": client_id, **extra},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, headers, tender_id, path=XLSX):
    with path.open("rb") as fh:
        r = client.post(
            f"/api/tenders/{tender_id}/boq/import", files={"file": (path.name, fh)}, headers=headers
        )
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, headers, tender_id, preview, replace=False):
    cols = {f: g["column"] for f, g in preview["column_map"].items()}
    return client.post(
        f"/api/tenders/{tender_id}/boq/import/confirm",
        json={
            "upload_id": preview["upload_id"],
            "sheet": preview["sheet"],
            "header_row": preview["header_row"],
            "column_map": cols,
            "replace": replace,
        },
        headers=headers,
    )


def boq(client, headers, tender_id):
    r = client.get(f"/api/tenders/{tender_id}/boq", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def line(data, start):
    return next(ln for ln in data["lines"] if start in ln["description"])


def imported_tender(client, headers):
    tender = new_tender(client, headers, new_client(client, headers))
    r = confirm(client, headers, tender["id"], upload(client, headers, tender["id"]))
    assert r.status_code == 200, r.text
    return tender


def library_item(db, description, unit, rate, **flags):
    item = LibraryItem(
        source_key=f"t-{description[:30]}-{unit}",
        match_key=description[:40],
        description=description,
        unit=unit,
        unit_raw=unit,
        boq_count=3,
        latest_rate=Decimal(rate),
        min_rate=Decimal(rate) - 10,
        median_rate=Decimal(rate),
        max_rate=Decimal(rate) + 10,
        **flags,
    )
    db.add(item)
    db.commit()
    return item


def membrane_system(client, headers):
    """A system whose name matches the 'APP membrane … terrace' line: cost 300 + 20 per sqm."""
    r = client.post(
        "/api/products",
        json={
            "code": "P-APP",
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
            "purchase_rate": "300",
            "effective_from": (date.today() - timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/systems",
        json={
            "code": "SYS-APP",
            "name": "APP membrane terrace",
            "unit": "sqm",
            "surface_prep_per_unit": "20",
            "labour_rate": "0",
            "labour_unit": "sqm",
            "default_margin_percent": "20",
            "components": [{"product_id": pid, "consumption_per_unit": "1"}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- import API ----------------------------------------------------------------------------------


def test_preview_saves_nothing_then_confirm_replace_keeps_prices(boss, db):
    client, headers = boss
    tender = new_tender(client, headers, new_client(client, headers))
    tid = tender["id"]
    preview = upload(client, headers, tid)
    assert preview["sheet"] == "BOQ" and preview["header_row"] == 4
    assert {s["name"] for s in preview["sheets"]} == {"BOQ", "Cover"}
    assert preview["column_map"]["description"]["letter"] == "B"
    assert preview["counts"]["lines"] == 8 and len(preview["rows"]) <= 30
    assert boq(client, headers, tid)["lines"] == []  # the preview saved nothing

    # re-reading with a different header row is a preview too
    r = client.post(
        f"/api/tenders/{tid}/boq/import/preview",
        json={
            "upload_id": preview["upload_id"],
            "sheet": "BOQ",
            "header_row": 4,
            "column_map": {"description": 1, "unit": 2, "qty": 3},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["column_map"]) == {"description", "unit", "qty"}

    report = confirm(client, headers, tid, preview).json()
    assert {k: report[k] for k in ("lines", "sections", "qro", "nq", "skipped")} == {
        "lines": 8,
        "sections": 3,
        "qro": 2,
        "nq": 1,
        "skipped": 6,
    }
    assert report["unrecognised_units"] == {"Pair": 1}
    data = boq(client, headers, tid)
    assert len(data["lines"]) == 8 and len(data["sections"]) == 3
    crystal = line(data, "Crystalline coating")
    # the client's rate column goes to client_file_rate, never to rate
    assert crystal["client_file_rate"] == "450.00" and crystal["rate"] is None
    assert line(data, "Brick bat coba")["status"] == "not_quoted"
    assert all(ln["status"] in ("unpriced", "not_quoted") for ln in data["lines"])
    stored = list((Path(settings.media_dir) / "tenders" / str(tid) / "uploads").iterdir())
    assert len(stored) == 1 and stored[0].name.endswith("client_boq.xlsx")

    # a second import is refused unless replace is set
    preview2 = upload(client, headers, tid)
    assert confirm(client, headers, tid, preview2).status_code == 409
    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": crystal["id"], "rate": "470"}]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = confirm(client, headers, tid, preview2, replace=True)
    assert r.status_code == 200, r.text
    assert r.json()["kept_prices"] == 1
    data = boq(client, headers, tid)
    kept = line(data, "Crystalline coating")
    assert (kept["rate"], kept["status"], kept["amount"]) == ("470.00", "priced", "56635.00")
    assert db.scalar(select(func.count()).select_from(LibraryItem)) == 0  # nothing leaks out


def test_upload_rejects_other_files(boss):
    client, headers = boss
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    r = client.post(
        f"/api/tenders/{tid}/boq/import", files={"file": ("boq.pdf", b"%PDF")}, headers=headers
    )
    assert r.status_code == 422


# --- suggest, accept, margins, totals ------------------------------------------------------------


@pytest.fixture
def priced_setup(boss, db):
    client, headers = boss
    system_id = membrane_system(client, headers)
    library_item(db, "Crystalline coating to raft with two coats", "sqm", "455")
    # same words, but per sqm while the line is per nos, and nos→sqm has no conversion
    library_item(db, "Pipe sleeve sealing with polymer modified mortar", "sqm", "300")
    library_item(db, "Expansion joint sealing with PU sealant", "rmt", "999", is_competitor=True)
    library_item(
        db, "Lift pit injection grouting", "rmt", "888", is_excluded=True, excluded_reason="test"
    )
    library_item(db, "Planter box waterproofing with two coats", "sqm", "610")
    tender = imported_tender(client, headers)
    tid = tender["id"]
    planter = line(boq(client, headers, tid), "Planter box")
    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": planter["id"], "rate": "777"}]},
        headers=headers,
    )
    assert r.status_code == 200
    r = client.post(f"/api/tenders/{tid}/boq/suggest", headers=headers)
    assert r.status_code == 200, r.text
    return client, headers, tid, system_id, r.json()


def test_suggest_sources_units_and_priced_lines(priced_setup):
    client, headers, tid, system_id, result = priced_setup
    assert result["threshold"] == "0.550"
    assert result["skipped_priced"] == 1
    data = boq(client, headers, tid)

    membrane = line(data, "APP membrane")  # system match: cost 320, default margin 20%
    assert (membrane["status"], membrane["source"], membrane["system_id"]) == (
        "suggested",
        "system",
        system_id,
    )
    assert (membrane["cost_rate"], membrane["margin_percent"], membrane["rate"]) == (
        "320.00",
        "20.00",
        "384.00",
    )

    crystal = line(data, "Crystalline coating")  # library-only match
    assert (crystal["status"], crystal["source"], crystal["rate"]) == (
        "suggested",
        "library",
        "455.00",
    )
    assert crystal["cost_rate"] is None and Decimal(crystal["suggestion_score"]) >= Decimal("0.55")

    pipe = line(data, "Pipe sleeve")  # unit mismatch without a conversion: no price
    assert pipe["rate"] is None and pipe["status"] == "unpriced"
    detail = client.get(f"/api/tenders/{tid}/lines/{pipe['id']}", headers=headers).json()
    assert all(c["rate"] != "300.00" for c in detail["candidates"])

    joint = line(data, "Expansion joint")  # competitor rates are never used
    assert joint["rate"] != "999.00"
    lift = line(data, "Lift pit")  # excluded items are never used
    assert lift["rate"] != "888.00"

    planter = line(data, "Planter box")  # priced lines are never overwritten
    assert (planter["rate"], planter["status"], planter["source"]) == ("777.00", "priced", "manual")
    assert line(data, "Brick bat coba")["rate"] is None  # NQ lines are not priced


def test_candidates_accept_and_use(priced_setup):
    client, headers, tid, _, _ = priced_setup
    data = boq(client, headers, tid)
    crystal = line(data, "Crystalline coating")
    detail = client.get(f"/api/tenders/{tid}/lines/{crystal['id']}", headers=headers).json()
    assert 1 <= len(detail["candidates"]) <= 3
    assert [c["rank"] for c in detail["candidates"]] == list(
        range(1, len(detail["candidates"]) + 1)
    )
    stats = {s["description"]: s for s in detail["library_stats"]}
    assert stats["Crystalline coating to raft with two coats"]["min_rate"] == "445.0000"

    r = client.post(f"/api/tenders/{tid}/boq/accept", json={"min_score": "0.99"}, headers=headers)
    assert line(r.json(), "Crystalline coating")["status"] == "suggested"  # below 99%
    r = client.post(f"/api/tenders/{tid}/boq/accept", json={"min_score": "0.5"}, headers=headers)
    data = r.json()
    assert {ln["status"] for ln in data["lines"]} <= {"priced", "unpriced", "not_quoted"}
    assert line(data, "Crystalline coating")["status"] == "priced"

    pipe = line(data, "Pipe sleeve")
    detail = client.get(f"/api/tenders/{tid}/lines/{pipe['id']}", headers=headers).json()
    if detail["candidates"]:
        cand = detail["candidates"][0]
        r = client.post(
            f"/api/tenders/{tid}/lines/{pipe['id']}/use-candidate",
            json={"candidate_id": cand["id"]},
            headers=headers,
        )
        assert line(r.json(), "Pipe sleeve")["status"] == "priced"


def test_margin_recalculates_system_lines_only_and_totals(priced_setup, db):
    client, headers, tid, _, _ = priced_setup
    r = client.post(
        f"/api/tenders/{tid}/boq/margin", json={"margin_percent": "12.5"}, headers=headers
    )
    assert r.status_code == 200, r.text
    data = r.json()
    membrane = line(data, "APP membrane")
    assert (membrane["margin_percent"], membrane["rate"], membrane["amount"]) == (
        "12.50",
        "360.00",
        "108000.00",
    )
    crystal = line(data, "Crystalline coating")
    assert (crystal["rate"], crystal["margin_percent"]) == ("455.00", None)  # library: untouched

    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": crystal["id"], "margin_percent": "30"}]},
        headers=headers,
    )
    assert r.status_code == 422  # a margin needs a cost

    # QRO lines carry a rate but no amount, and stay out of the totals
    screed = line(data, "Protective screed")
    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": screed["id"], "rate": "260"}]},
        headers=headers,
    )
    data = r.json()
    assert line(data, "Protective screed")["amount"] is None
    amounts = [Decimal(ln["amount"]) for ln in data["lines"] if ln["amount"]]
    totals = data["totals"]
    assert Decimal(totals["subtotal"]) == sum(amounts)
    assert totals["gst_percent"] == "18.00"
    assert Decimal(totals["gst"]) == pricing.money(sum(amounts) * Decimal("0.18"))
    assert Decimal(totals["grand_total"]) == Decimal(totals["subtotal"]) + Decimal(totals["gst"])
    section_sum = sum(Decimal(s["total"]) for s in data["sections"])
    unsectioned = sum(
        Decimal(ln["amount"]) for ln in data["lines"] if ln["amount"] and ln["section_id"] is None
    )
    assert section_sum + unsectioned == Decimal(totals["subtotal"])
    listed = client.get("/api/tenders", headers=headers).json()["items"][0]
    assert listed["quoted_total"] == totals["subtotal"]


def test_decimal_rounding_on_the_final_value_only():
    assert pricing.rate_from_margin(Decimal("10.10"), Decimal("25")) == Decimal("12.63")  # half up
    assert pricing.rate_from_margin(Decimal("10.02"), Decimal("12.5")) == Decimal("11.27")
    assert pricing.money(Decimal("40.123") * Decimal("600.00")) == Decimal("24073.80")
    assert pricing.money(Decimal("0.005")) == Decimal("0.01")


def test_one_audit_row_per_save(boss, db):
    client, headers = boss
    tid = imported_tender(client, headers)["id"]
    data = boq(client, headers, tid)
    ids = [ln["id"] for ln in data["lines"][:3]]
    before = db.scalar(select(func.count()).select_from(AuditLog))
    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": i, "rate": "100", "our_remarks": "batch"} for i in ids]},
        headers=headers,
    )
    assert r.status_code == 200
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(5)).all()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == before + 1
    assert rows[0].action == "tender.lines.update" and rows[0].after["lines"] == 3


# --- register, status, permissions ---------------------------------------------------------------


def test_lost_needs_a_reason_and_overdue_flag(boss):
    client, headers = boss
    cid = new_client(client, headers)
    tender = new_tender(client, headers, cid, due_on=(date.today() - timedelta(days=2)).isoformat())
    assert tender["code"] == f"T-{date.today().year}-0001" and tender["overdue"] is True
    r = client.patch(f"/api/tenders/{tender['id']}", json={"status": "lost"}, headers=headers)
    assert r.status_code == 422
    r = client.patch(
        f"/api/tenders/{tender['id']}",
        json={"status": "lost", "lost_reason": "Price", "lost_to": "Rival Co"},
        headers=headers,
    )
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["lost_to"], r.json()["overdue"]) == (
        "lost",
        "Rival Co",
        False,
    )
    r = client.get("/api/tenders/export", headers=headers)
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_assigned_scope_sees_only_their_tenders(boss, db, make_user):
    client, headers = boss
    role = Role(
        code="tender_assigned",
        name="Assigned tenders",
        permissions=[
            RolePermission(permission_code="tender.view", scope="assigned"),
            RolePermission(permission_code="tender.edit", scope="assigned"),
        ],
    )
    db.add(role)
    db.commit()
    rep = make_user("rep@example.com", "tender_assigned")
    cid = new_client(client, headers)
    owned = new_tender(client, headers, cid, owner_id=str(rep.id))
    member = new_tender(client, headers, cid, member_ids=[str(rep.id)])
    other = new_tender(client, headers, cid)

    from tests.conftest import login

    rep_headers = login(client, "rep@example.com")
    listed = client.get("/api/tenders", headers=rep_headers).json()
    assert {t["id"] for t in listed["items"]} == {owned["id"], member["id"]}
    assert client.get(f"/api/tenders/{other['id']}", headers=rep_headers).status_code == 404
    assert client.get(f"/api/tenders/{other['id']}/boq", headers=rep_headers).status_code == 404
    r = client.patch(f"/api/tenders/{member['id']}", json={"notes": "mine"}, headers=rep_headers)
    assert r.status_code == 200


def _keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_cost_fields_absent_without_tender_margin(login_as, db):
    client, headers = login_as("sales", email="sales@example.com")  # tender.* own, no margin
    # the tender form choices work without the client / user admin permissions
    assert client.get("/api/tenders/lookups", headers=headers).status_code == 200
    library_item(db, "Crystalline coating to raft with two coats", "sqm", "455")
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    preview = upload(client, headers, tid)
    assert not _keys(preview) & COST_KEYS
    assert confirm(client, headers, tid, preview).status_code == 200
    assert client.post(f"/api/tenders/{tid}/boq/suggest", headers=headers).status_code == 200

    data = boq(client, headers, tid)
    crystal = line(data, "Crystalline coating")
    assert crystal["status"] == "suggested" and crystal["rate"] == "455.00"
    detail = client.get(f"/api/tenders/{tid}/lines/{crystal['id']}", headers=headers).json()
    assert detail["candidates"]
    for payload in (
        data,
        detail,
        client.get("/api/tenders", headers=headers).json(),
        client.get(f"/api/tenders/{tid}", headers=headers).json(),
    ):
        assert not _keys(payload) & COST_KEYS, _keys(payload) & COST_KEYS
    r = client.post(
        f"/api/tenders/{tid}/boq/margin", json={"margin_percent": "10"}, headers=headers
    )
    assert r.status_code == 403
    r = client.patch(
        f"/api/tenders/{tid}/lines",
        json={"lines": [{"id": crystal["id"], "margin_percent": "10"}]},
        headers=headers,
    )
    assert r.status_code == 403


def test_client_role_is_refused(login_as, boss):
    boss_client, boss_headers = boss
    tid = new_tender(boss_client, boss_headers, new_client(boss_client, boss_headers))["id"]
    client, headers = login_as("client", email="customer@example.com")
    assert client.get("/api/tenders", headers=headers).status_code == 403
    assert client.get(f"/api/tenders/{tid}", headers=headers).status_code == 403
    assert client.get(f"/api/tenders/{tid}/boq", headers=headers).status_code == 403
    r = client.post("/api/tenders", json={"name": "x", "client_id": 1}, headers=headers)
    assert r.status_code == 403


def test_tender_codes_unique_under_concurrency():
    on = date(2031, 3, 1)
    codes: list[str] = []
    barrier = threading.Barrier(12)

    def create():
        with SessionLocal() as session:
            barrier.wait()
            codes.append(next_code(session, on))
            session.commit()

    threads = [threading.Thread(target=create) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [f"T-2031-{n:04d}" for n in range(1, 13)]


# --- T&C -----------------------------------------------------------------------------------------


def test_tender_terms_copy_reorder_and_edit_locally(boss, db):
    client, headers = boss
    clauses = [
        TcClause(text=t, category="general")
        for t in ("Water by client", "GST extra", "Payment 30 days")
    ]
    db.add_all(clauses)
    db.flush()
    db.add(
        TcTemplate(
            name="Standard",
            is_default=True,
            clauses=[
                TcTemplateClause(clause_id=c.id, sort_order=i) for i, c in enumerate(clauses[:2])
            ],
        )
    )
    db.commit()
    tid = new_tender(client, headers, new_client(client, headers))["id"]
    terms = client.get(f"/api/tenders/{tid}/tc", headers=headers).json()
    assert [t["text"] for t in terms] == ["Water by client", "GST extra"]

    r = client.put(
        f"/api/tenders/{tid}/tc",
        json={
            "items": [
                {"clause_id": clauses[2].id},
                {"clause_id": clauses[0].id, "text_override": "Water and power by client"},
                {"text_override": "Site-specific: night work allowed"},
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [t["text"] for t in r.json()] == [
        "Payment 30 days",
        "Water and power by client",
        "Site-specific: night work allowed",
    ]
    db.expire_all()
    assert db.get(TcClause, clauses[0].id).text == "Water by client"  # library unchanged
