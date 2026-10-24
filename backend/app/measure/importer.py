# ruff: noqa: E501  (output shapes read better unwrapped)
"""Old bills read from Excel (the measurement sheet and the proforma as the billing team made them
before the app): their quantities become the "previous" of the first bill in the app.

What is read becomes an imported sheet (status billed, its lines the totals per item), an imported
RA bill (certified, rates from the work order) and the approved book lines behind it. Everything
that could not be read or placed is listed, never guessed."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance import service as svc
from app.finance.models import RaBill, RaBillLine
from app.measure import bill as mb
from app.measure import excel
from app.measure import service as ms
from app.measure.models import MeasureLine
from app.sites.models import Site
from app.team.models import Measurement

ZERO = Decimal(0)


def run(db: Session, site: Site, *, sheet_file: tuple[str, bytes] | None, proforma_file: tuple[str, bytes] | None, measured_on: date, user) -> dict:
    if sheet_file is None and proforma_file is None:
        raise mb.Refused("Choose the old measurement sheet, the proforma, or both")
    c = mb.contract_of(db, site.id)
    if db.scalar(select(RaBill.id).where(RaBill.contract_id == c.id, RaBill.imported.is_(False), RaBill.status != "cancelled")):
        raise mb.Clash("The site has RA bills made in the app: import the old sheets before the first one")
    wo_lines = ms.work_order_lines(db, site.id)
    if not wo_lines:
        raise mb.Refused("The site has no work order to match the old items to")
    skipped: list[str] = []
    sheet_read = pro_read = None
    if sheet_file:
        try:
            sheet_read = excel.read_sheet(sheet_file[1])
        except ValueError as exc:
            raise mb.Refused(f"{sheet_file[0]}: {exc}") from exc
        skipped += [f"{sheet_file[0]}: {s}" for s in sheet_read["skipped"]]
    if proforma_file:
        try:
            pro_read = excel.read_proforma(proforma_file[1])
        except ValueError as exc:
            raise mb.Refused(f"{proforma_file[0]}: {exc}") from exc
        skipped += [f"{proforma_file[0]}: {s}" for s in pro_read["skipped"]]
    source = sheet_read or pro_read
    matched, unplaced = excel.match(source["items"], wo_lines)
    skipped += unplaced
    if not matched:
        raise mb.Refused("Nothing could be read: " + "; ".join(skipped[:5]))
    by_id = {w.id: w for w in wo_lines}
    # the proforma against the sheet: the same quantities, and the work order's rates
    checks = [f"{sheet_file[0]}: {a}" for a in sheet_read["assumed"]] if sheet_read else []
    if sheet_read and pro_read:
        pm, _ = excel.match(pro_read["items"], wo_lines)
        for wid, row in matched.items():
            p = pm.get(wid)
            if p is None:
                checks.append(f"Item {by_id[wid].item_no}: on the sheet, not on the proforma")
            elif excel.geom.round3(p["qty"]) != excel.geom.round3(row["qty"]):
                checks.append(f"Item {by_id[wid].item_no}: sheet {excel.geom.round3(row['qty'])}, proforma {excel.geom.round3(p['qty'])}")
    if pro_read:
        pm, _ = excel.match(pro_read["items"], wo_lines)
        for wid, p in pm.items():
            w = by_id[wid]
            if w.rate is not None and p.get("rate") is not None and Decimal(p["rate"]) != Decimal(w.rate):
                checks.append(f"Item {w.item_no}: the proforma's rate {p['rate']} is not the order's {w.rate}")
    names = ", ".join(f[0] for f in (sheet_file, proforma_file) if f)
    sheet = ms.new_sheet(db, site, measured_on, f"Imported: {names}"[:200], user.id)
    sheet.imported_from, sheet.status, sheet.import_skipped = names[:300], "billed", skipped
    by_wo = mb.contract_lines_by_wo(c)
    seq = (db.scalar(select(RaBill.seq).where(RaBill.contract_id == c.id).order_by(RaBill.seq.desc()).limit(1)) or 0) + 1
    b = RaBill(code=f"RA-{site.code}-{seq:02d}", contract_id=c.id, site_id=site.id, seq=seq, period_to=measured_on, status="certified", imported=True,
               certified_at=svc.now(), remark=f"Imported from {names}", created_by=user.id)  # fmt: skip
    db.add(b)
    out_rows = []
    for i, (wid, row) in enumerate(sorted(matched.items(), key=lambda kv: (by_id[kv[0]].sort_order, kv[0]))):
        w = by_id[wid]
        qty = excel.geom.round3(row["qty"])
        db.add(MeasureLine(sheet_id=sheet.id, sort_order=i, kind="line", wo_line_id=w.id, item_no=w.item_no, layer=1,
                           particulars=f"Imported from {names}: item {row['item_no']}", total=qty, unit=w.unit, qty=row["qty"]))  # fmt: skip
        cl = by_wo.get(wid)
        if cl is None:
            skipped.append(f"Item {w.item_no}: the contract has no line for it (not billed as previous)")
            continue
        rate = Decimal(w.rate if w.rate is not None else cl.rate)
        b.lines.append(RaBillLine(contract_line_id=cl.id, previous_qty=ZERO, suggested_qty=qty, qty=qty, certified_qty=qty, rate=rate))
        db.add(Measurement(site_id=site.id, contract_line_id=cl.id, description=f"{sheet.code}: imported item {w.item_no or ''}".strip(), qty=qty, unit=cl.unit,
                           source="manual", measured_on=measured_on, measured_by=user.id, note=f"{sheet.code}: imported from {names}", status="approved",
                           approved_at=svc.now(), approved_name="Imported bill", created_by=user.id))  # fmt: skip
        out_rows.append({"wo_line_id": w.id, "item_no": w.item_no, "description": w.description, "unit": w.unit, "qty": qty, "rows": row.get("rows")})
    svc.ra_totals(db, b, c)
    db.flush()
    for m in db.scalars(select(Measurement).where(Measurement.note == f"{sheet.code}: imported from {names}")):
        m.ra_bill_id = b.id
    sheet.ra_bill_id = b.id
    sheet.import_skipped = skipped + checks
    if pro_read and pro_read["basic"] is not None and Decimal(pro_read["basic"]) != Decimal(b.certified_gross):
        checks.append(f"The proforma's basic {pro_read['basic']} is not the quantities × the order's rates ({b.certified_gross})")
    totals = {"basic": b.certified_gross, "read_basic": pro_read["basic"] if pro_read else None, "read_grand": pro_read["grand"] if pro_read else None}
    db.flush()
    return {"sheet_id": sheet.id, "sheet_code": sheet.code, "ra_bill_id": b.id, "ra_code": b.code, "items": out_rows, "skipped": skipped, "checks": checks, "totals": totals}
