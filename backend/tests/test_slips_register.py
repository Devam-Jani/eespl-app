# ruff: noqa: E501
"""Bills from site slips, RA numbering, bill revisions, the old register and the material check.
Invented data, except the last test (the billing team's real folder, skipped when it is absent)."""

import io
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.finance.models import RaBill
from app.measure import register, slip
from app.measure.models import BillRevision, MeasureSheet
from app.team.models import Measurement
from app.timefmt import ist_today
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_measure_billing import (
    pool,  # noqa: F401  (fixture: a site, its work order and contract)
)
from tests.test_real_billing import FOLDER

D = Decimal
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a1c40000000049454e44ae426082")


def test_feet_and_inches_as_written_on_a_slip():
    assert slip.feet("16'0\"") == 16 and slip.feet("116'9\"") == D("116.75") and slip.feet("13' 10\"") == 13 + D(10) / 12
    assert slip.feet('9"') == D("0.75") and slip.feet("16 ft 9 in") == D("16.75") and slip.feet("13.83") == D("13.83") and slip.feet("") is None
    with pytest.raises(ValueError):
        slip.feet("4'12\"")
    q, how = slip.work_out("rmt", D(1), D("1407.66"), None)
    assert q == D("1407.66") / D("3.2808") and "3.2808" in how  # feet to metres with 3.2808
    assert slip.work_out("sqft", D(4), D(23), D("12.83"))[0] == D("1180.36")
    assert slip.work_out("sqm", D(1), D("3.2808"), D("3.2808"))[0] == 1
    assert slip.work_out("nos", D(1), D(25), None)[0] == 25 and slip.work_out("nos", D(6), None, None)[0] == 6


def _slip(pool, **extra):  # noqa: F811
    r = pool["c"].post(f"/api/measure/sites/{pool['site'].id}/slips", data={"measured_on": "2026-06-01", "signed_by": "Client's site engineer", "signed_on": "2026-05-23", "slip_on": "2026-05-23", **extra},
                       files={"file": ("slip.png", PNG, "image/png")}, headers=pool["h"])  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def test_a_bill_from_a_slip_lists_what_it_does_not_bill(pool, db):  # noqa: F811
    c, h, wl = pool["c"], pool["h"], pool["wl"]
    s = _slip(pool)
    for body in ({"particulars": "Terrace floor", "no": "4", "length": "23'0\"", "width": "12'10\"", "wo_line_id": wl["1"]},
                 {"particulars": "Deduction", "no": "-4", "length": "12", "width": "2", "wo_line_id": wl["1"]},
                 {"particulars": "Pipe sleeves", "no": "3", "wo_line_id": wl["2"]},
                 {"particulars": "Gabda", "no": "6"},  # no item for it in the order
                 {"particulars": "Extra sleeve", "no": "1", "wo_line_id": wl["2"], "billed": False, "reason": "Not in the order yet"}):  # fmt: skip
        r = c.post(f"/api/measure/sheets/{s['id']}/slip-lines", json=body, headers=h)
        assert r.status_code == 201, r.text
    out = r.json()
    totals = {ln["item_no"]: D(ln["total"]) for ln in out["lines"] if ln["kind"] == "total"}
    assert totals["1"] == (4 * 23 * (12 + D(10) / 12) - 96).quantize(D("0.001")) and totals["2"] == 3
    assert {u["particulars"] for u in out["slip"]["unbilled"]} == {"Gabda", "Extra sleeve"}
    assert c.get(f"/api/measure/sheets/{s['id']}/slip", headers=h).content == PNG
    sent = c.post(f"/api/measure/sheets/{s['id']}/send", headers=h)
    assert sent.status_code == 200 and sent.json()["status"] == "approved"  # the signed slip is the client's approval
    book = list(db.scalars(select(Measurement).where(Measurement.note.like(f"{s['code']}:%"))))
    assert book and all(m.status == "approved" and m.approved_name == "Client's site engineer" and m.recorded_by_staff and m.signed_copy_path for m in book)
    b = c.post(f"/api/measure/sheets/{s['id']}/bill", json={"basis": "verbal", "verbal_by": "Client's site engineer", "verbal_on": "2026-05-23", "proforma_on": "2026-06-01"}, headers=h)
    assert b.status_code == 201, b.text
    chk = {x["key"]: x for x in b.json()["checklist"]}
    assert chk["slip"]["ok"] and len(chk["slip_lines"]["detail"]) == 2


def test_ra_numbers_are_never_reused_or_renamed(pool, db):  # noqa: F811
    from app.measure import importer

    c, h = pool["c"], pool["h"]
    pool_edge_answers(pool)
    s1 = c.post(f"/api/measure/sites/{pool['site'].id}/sheets", json={"measured_on": "2026-09-01"}, headers=h).json()
    assert c.post(f"/api/measure/sheets/{s1['id']}/send", headers=h).status_code == 200
    b1 = c.post(f"/api/measure/sheets/{s1['id']}/bill", json={}, headers=h).json()
    assert c.post(f"/api/finance/ra-bills/{b1['id']}/cancel", json={"reason": "made in error"}, headers=h).status_code in (200, 201)
    bill = db.get(RaBill, b1["id"])
    db.refresh(bill)
    assert bill.status == "cancelled"
    # the next bill takes the next number: the cancelled one's is never given again
    from app.finance.models import ClientContract
    from app.measure import bill as mb

    k = db.get(ClientContract, pool["contract"].id)
    nxt = RaBill(code="x", contract_id=k.id, site_id=k.site_id, seq=0, period_to=ist_today())
    seq = (db.scalar(select(RaBill.seq).where(RaBill.contract_id == k.id).order_by(RaBill.seq.desc()).limit(1)) or 0) + 1
    assert seq == bill.seq + 1
    del nxt
    # an old bill cannot come in under a number the app has given
    with pytest.raises(mb.Clash):
        importer.run(db, db.get(type(pool["site"]), pool["site"].id), sheet_file=None, proforma_file=("p.xlsx", b"x"), measured_on=ist_today(), user=pool["me"], ra_no=bill.seq)


def pool_edge_answers(pool):  # noqa: F811
    r = pool["c"].post(f"/api/measure/edges/{pool['edge'].id}/answer", json={"answer": "both"}, headers=pool["h"])
    assert r.status_code == 200


def test_revisions_one_sent_and_what_changed(pool, db):  # noqa: F811
    c, h = pool["c"], pool["h"]
    pool_edge_answers(pool)
    s = c.post(f"/api/measure/sites/{pool['site'].id}/sheets", json={"measured_on": "2026-09-01"}, headers=h).json()
    c.post(f"/api/measure/sheets/{s['id']}/send", headers=h)
    b = c.post(f"/api/measure/sheets/{s['id']}/bill", json={}, headers=h).json()
    revs = c.post(f"/api/measure/bills/{b['id']}/revisions", json={"label": "first"}, headers=h).json()
    bill = db.get(RaBill, b["id"])
    register.add_revision(db, bill, label="revised", source="an old file", made_on=ist_today(), lines=[{"item_no": "1", "description": "Coating", "unit": "sqft", "qty": "10", "rate": "85", "amount": "850"}],
                          basic=D(850), gst=D(153), total=D(1003))  # fmt: skip
    db.commit()
    revs = c.get(f"/api/measure/bills/{b['id']}/revisions", headers=h).json()
    assert [r["rev"] for r in revs] == ["R0", "R1"] and revs[1]["changes"] and D(revs[1]["basic_change"]) == D(850) - D(revs[0]["basic"])
    for r in revs:
        out = c.post(f"/api/measure/bills/{b['id']}/revisions/{r['id']}/sent", headers=h).json()
    assert [x["sent"] for x in out] == [False, True]  # one sent: the last marked
    db.add(BillRevision(ra_bill_id=b["id"], rev_no=9, sent=True))
    with pytest.raises(IntegrityError):  # the database keeps it to one
        db.commit()
    db.rollback()


def test_material_check_needed_against_used(pool, db):  # noqa: F811
    from app.closeout.models import ClientWorkOrderLine
    from app.masters.models import Product, System, SystemComponent
    from app.material.models import StockLedger, Store

    c, h = pool["c"], pool["h"]
    p = Product(code="P-INV-1", name="Invented coating", unit="kg")
    db.add(p)
    db.flush()
    sy = System(code="S-INV-1", name="Invented coating system", unit="sqm")
    db.add(sy)
    db.flush()
    db.add(SystemComponent(system_id=sy.id, product_id=p.id, consumption_per_unit=D("1.5")))
    w = db.get(ClientWorkOrderLine, pool["wl"]["1"])
    w.system_id = sy.id
    store = Store(name="Invented site store", kind="site", site_id=pool["site"].id)
    db.add(store)
    db.flush()
    at = datetime.combine(date(2026, 8, 1), time(12)).astimezone()
    for ref, q in (("transfer_in", D(800)), ("transfer_out", D(-100)), ("issue", D(-652))):
        db.add(StockLedger(store_id=store.id, product_id=p.id, qty=q, unit="kg", rate=D(0), value=D(0), ref_type=ref, at=at))
    db.commit()
    s = _slip(pool)
    c.post(f"/api/measure/sheets/{s['id']}/slip-lines", json={"particulars": "Floor", "no": "1", "length": "100", "width": "10", "wo_line_id": w.id}, headers=h)  # 1,000 sqft
    c.post(f"/api/measure/sheets/{s['id']}/send", headers=h)
    b = c.post(f"/api/measure/sheets/{s['id']}/bill", json={"basis": "verbal", "verbal_by": "Client's site engineer", "verbal_on": "2026-05-23", "proforma_on": "2026-09-01"}, headers=h).json()
    m = c.get(f"/api/measure/bills/{b['id']}/material", headers=h).json()
    row = m["rows"][0]
    needed = (D(1000) / D("10.7639") * D("1.5")).quantize(D("0.01"))
    assert D(row["needed"]) == needed and D(row["sent"]) == 800 and D(row["returned"]) == 100 and D(row["site_stock"]) == 48 and D(row["used"]) == 652
    assert D(row["variance_percent"]) == ((D(652) - needed) / needed * 100).quantize(D("0.1"))


def test_the_old_register_and_the_folder_findings():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SUMMARY"])
    ws.append(["Sr No.", "Description ", "Status ", "DATE", "Invoice No.", "Basic Amount ", "Total Basic Amount ", " TAX Amount ", "Total TAX amount", "Remarks"])
    ws.append([1, "Wall", "TAX INVOICE", "24.04.2025", "S/0020/25-26", 1000, None, 1180, None, "sent to a named person"])
    ws.append([2, "Terrace", "PROFORMA INVOICE", "07.10.2025", "-", 500, None, 590])
    buf = io.BytesIO()
    wb.save(buf)
    rows = register.read_register(buf.getvalue())
    assert [r["basic"] for r in rows] == [D("1000.00"), D("500.00")] and rows[0]["invoice_no"] == "S/0020/25-26" and "remark" not in rows[0]  # names never kept
    files = [
        {"file": "A/(RA - 1) Wall 24.04.2025.xlsx", "kind": "xlsx", "ra": 1, "folder_ra": None, "name_date": date(2025, 4, 24), "bill_date": date(2025, 4, 24), "version": "final", "subject": "WALL", "fy": "FROM APRIL 2025 TO MARCH 2026", "basic": D(1000)},
        {"file": "A/(RA - 2) Terrace 07.10.2025.xlsx", "kind": "xlsx", "ra": 2, "folder_ra": None, "name_date": date(2025, 10, 7), "bill_date": date(2025, 10, 7), "version": None, "subject": "TERRACE", "fy": "FROM APRIL 2025 TO MARCH 2026", "basic": D(500)},
        {"file": "B/(RA - 5) Pool 01.09.2026.xlsx", "kind": "xlsx", "ra": 5, "folder_ra": None, "name_date": date(2026, 9, 1), "bill_date": date(2025, 9, 1), "version": None, "subject": "POOL A", "fy": "FROM APRIL 2026 TO MARCH 2027", "basic": D(700)},
        {"file": "B/RA 4/(RA - 3) Pool 01.10.2026.pdf", "kind": "pdf", "ra": 3, "folder_ra": 4, "name_date": date(2026, 10, 1), "version": None, "subject": "POOL B", "fy": "FROM APRIL 2026 TO MARCH 2027"},
    ]
    rows = register.match_register(rows, files)
    assert [r["ra"] for r in rows] == [1, 2]
    found = {f["kind"]: f["text"] for f in register.findings(files, rows)}
    assert "RA 3 is missing" in found["missing"] or "RA 4 is missing" in found["missing"]
    assert "numbered RA 3" in found["clash"]
    assert "RA 5 is dated 01.09.2025 inside" in found["year"]
    assert "Missing from the old register: RA 5" in found["register"]


@pytest.mark.skipif(FOLDER is None, reason="the billing team's real folder is not here (data/samples/billing/)")
def test_the_real_slip_bills_register_and_material_check(boss, db):  # noqa: F811
    from app.measure import billingcheck

    out = billingcheck.run(db, FOLDER)
    by = {s["key"]: s for s in out["slips"]}
    ra7, ra16, draft = by["RA 7"], by["RA 16"], by["21.10.2026"]
    # RA 16 from its slips: every quantity, the basic and the grand total as their Excel
    ex = ra16["excel"]
    assert ra16["basic"] == D(ex["basic"]) == D("134956.66") and ra16["grand"] == D(ex["grand"]) == D("159249.00")
    assert all(D(ra16["lines"][k]) == D(v).quantize(D("0.001")) for k, v in zip(("T1", "T2", "T3", "T4", "T5", "T6"), ex["items"].values(), strict=True))
    # RA 7: the same 1,407.66 R ft; to metres with 3.2808 (their sheet used 3.28)
    assert D(ra7["lines"]["S1"]) == (D("1407.66") / D("3.2808")).quantize(D("0.001"))
    assert D(ra7["excel"]["items"]["1"]).quantize(D("0.001")) == (D("1407.66") / D("3.28")).quantize(D("0.001"))
    # numbered by the app in order after the old bills RA 0 to RA 6; the 21.10.2026 slip a draft with its lines unmapped
    assert (ra7["ra"], ra16["ra"]) == (7, 8) and len(draft["unbilled"]) == 5 and draft.get("ra") is None
    texts = " | ".join(f["text"] for f in out["findings"])
    assert "RA 9 is missing" in texts and "RA 16 is dated 31.08.2026, before RA 10" in texts and "RA 14 is dated 04.10.2025 inside" in texts
    assert "Missing from the old register: RA 6, RA 7, RA 8, RA 10, RA 11, RA 12, RA 13, RA 14, RA 15, RA 16" in texts
    row = out["material"]["rows"][0]
    assert D(row["used"]) == 652 and D(row["needed"]) > 0
    assert any(b["revisions"] > 1 and b["sent_revision"] for b in out["app_register"])
    assert Path(FOLDER).exists() and db.scalar(select(MeasureSheet.id).where(MeasureSheet.status == "draft", MeasureSheet.slip_path.isnot(None)))
