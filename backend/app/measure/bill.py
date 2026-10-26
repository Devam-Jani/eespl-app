# ruff: noqa: E501  (output shapes read better unwrapped)
"""From the measurement sheet to the bill.

Sending a sheet writes one measurement-book line per work-order item (source AutoCAD) and, where
the client approves measurements, sends them as a set (the Prompt 26 flow: approve, or correct with
the old and new value, who and when). The areas, items and layers on it are marked billed: the
same three are never billed again.

The RA bill takes the approved sheet's quantities, its previous quantities from the earlier bills,
and its rates from the work order only. Its proforma invoice has a number from the counter and the
buyer from the client master; GST is CGST 9 % + SGST 9 % inside the state of our GSTIN, IGST 18 %
outside it (the GSTINs' state codes), a SAC on each line, and the round-off to the rupee. The
proforma becomes the tax invoice in one click, with its lines."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine, MeasurementChange, WoDeviation
from app.finance import service as svc
from app.finance.models import ClientContract, ContractLine, InvoiceLine, RaBill, TaxInvoice
from app.masters.models import Client
from app.measure import service as ms
from app.measure.models import MeasureArea, MeasureBilled, MeasureEdge, MeasureLine, MeasureSheet
from app.sites.models import Site
from app.team.models import Measurement

ZERO = Decimal(0)


class Refused(Exception):
    """Said to the billing team as it is (422)."""


class Clash(Exception):
    """Already done or in the way (409)."""


def contract_of(db: Session, site_id: int) -> ClientContract:
    c = db.scalar(select(ClientContract).where(ClientContract.site_id == site_id))
    if c is None:
        raise Refused("The site has no client contract: make it from the accepted work order first")
    return c


def contract_lines_by_wo(c: ClientContract) -> dict[int, ContractLine]:
    return {cl.wo_line_id: cl for cl in c.lines if cl.wo_line_id}


# --- sending the sheet ---------------------------------------------------------------------------


def book_lines(db: Session, sheet: MeasureSheet) -> list[Measurement]:
    return list(db.scalars(select(Measurement).where(Measurement.site_id == sheet.site_id, Measurement.note.like(f"{sheet.code}:%")).order_by(Measurement.id)))


def status_of(db: Session, sheet: MeasureSheet) -> str:
    """A sent sheet is approved once the client approved every line of it in the book."""
    if sheet.status == "sent":
        book = book_lines(db, sheet)
        if book and all(m.status == "approved" for m in book):
            sheet.status = "approved"
    return sheet.status


def send(db: Session, sheet: MeasureSheet, user) -> MeasureSheet:
    if sheet.status != "draft":
        raise Clash(f"{sheet.code} is {sheet.status}")
    from app.measure import slip  # noqa: PLC0415

    from_slip = slip.is_slip(sheet)
    if from_slip:
        lines = ms.lines_of(db, sheet.id)  # the slip's lines as entered
    else:
        built = ms.build(db, sheet)
        if built.questions:
            raise Refused("Answer first: " + "; ".join(q["text"] for q in built.questions[:5]))
        lines = ms.store(db, sheet, built)
    if not any(ln.total for ln in lines):
        raise Refused("Nothing measured on this sheet")
    site = db.get(Site, sheet.site_id)
    c = contract_of(db, site.id)
    by_wo = contract_lines_by_wo(c)
    # the areas, items and layers it bills: never billed again
    keys = {(ln.area_id, ln.wo_line_id, ln.layer) for ln in lines if ln.kind == "line" and ln.area_id and ln.wo_line_id}
    for area_id, wo_id, layer in sorted(keys):
        other = db.scalar(select(MeasureSheet.code).join(MeasureBilled, MeasureBilled.sheet_id == MeasureSheet.id)
                          .where(MeasureBilled.area_id == area_id, MeasureBilled.wo_line_id == wo_id, MeasureBilled.layer == layer))  # fmt: skip
        if other:
            a = db.get(MeasureArea, area_id)
            raise Clash(f"Area {a.code} is already billed for this item and layer on {other}")
        db.add(MeasureBilled(area_id=area_id, wo_line_id=wo_id, layer=layer, sheet_id=sheet.id))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Clash("An area on this sheet was billed for the same item and layer meanwhile") from exc
    book = []
    for wo_id, total in ms.totals(lines).items():
        if total <= 0:
            continue
        cl = by_wo.get(wo_id)
        wo = db.get(ClientWorkOrderLine, wo_id)
        if cl is None:
            raise Refused(f"The contract has no line for work-order item {wo.item_no or wo.id}")
        codes = sorted({db.get(MeasureArea, ln.area_id).code for ln in lines if ln.wo_line_id == wo_id and ln.area_id})
        where = f"from the slip of {sheet.slip_on:%d-%m-%Y}" if from_slip and sheet.slip_on else "from the slip" if from_slip else f"from the drawing, areas {', '.join(codes)}"
        m = Measurement(site_id=site.id, contract_line_id=cl.id, description=f"{sheet.code}: {wo.item_no + ' ' if wo.item_no else ''}{(wo.description or '')[:200]}",
                        qty=total, unit=cl.unit, source="manual" if from_slip else "autocad", measured_on=sheet.measured_on, measured_by=user.id,
                        note=f"{sheet.code}: {where}", status="draft" if site.measurements_need_approval and not from_slip else "approved",
                        created_by=user.id)  # fmt: skip
        if from_slip:
            # the slip is signed and dated by the client's person on site: their approval, recorded by us
            m.approved_name, m.recorded_by_staff, m.signed_copy_path = sheet.signed_by, True, sheet.slip_path
            m.approved_at = svc.now() if sheet.signed_on is None else svc.now().replace(year=sheet.signed_on.year, month=sheet.signed_on.month, day=sheet.signed_on.day)
        db.add(m)
        book.append(m)
    db.flush()
    if site.measurements_need_approval and not from_slip:
        from app.closeout import measure  # noqa: PLC0415

        s = measure.send(db, site, [m.id for m in book], sheet.code + (f": {sheet.title}" if sheet.title else ""), user)
        sheet.set_id, sheet.status = s.id, "sent"
    else:
        sheet.status = "approved"
    sheet.sent_at = svc.now()
    return sheet


def corrections(db: Session, sheet: MeasureSheet) -> list[dict]:
    """The client's corrections of this sheet's lines in the book, and our answers."""
    ids = [m.id for m in book_lines(db, sheet)]
    rows = db.scalars(select(MeasurementChange).where(MeasurementChange.measurement_id.in_(ids or [0])).order_by(MeasurementChange.id))
    return [{"measurement_id": c.measurement_id, "field": c.field, "old": c.old_value, "new": c.new_value, "remark": c.remark, "by": c.by_name,
             "at": c.at, "status": c.status, "reply": c.reply} for c in rows]  # fmt: skip


# --- the RA bill and its proforma ----------------------------------------------------------------


def sheet_of_bill(db: Session, b: RaBill) -> MeasureSheet | None:
    return db.scalar(select(MeasureSheet).where(MeasureSheet.ra_bill_id == b.id))


def bill_from_sheet(db: Session, sheet: MeasureSheet, user, *, proforma_on: date | None, basis: str, verbal_by: str | None, verbal_on: date | None) -> tuple[RaBill, list[str]]:
    from app.closeout import measure  # noqa: PLC0415
    from app.finance import billing  # noqa: PLC0415

    if status_of(db, sheet) != "approved":
        raise Refused(f"{sheet.code} is {sheet.status}: the RA bill is made from an approved sheet")
    if sheet.ra_bill_id:
        raise Clash(f"{sheet.code} is billed already")
    c = contract_of(db, sheet.site_id)
    if db.scalar(select(RaBill.id).where(RaBill.contract_id == c.id, RaBill.status == "draft")):
        raise Clash("Finish (submit or cancel) the draft RA bill first")
    wo = _work_order(db, sheet.site_id)
    if basis == "verbal":
        if not (verbal_by or "").strip() or verbal_on is None:
            raise Refused("A verbal order: say who at the client confirmed it, and when")
    elif wo is None or wo.status != "accepted":
        raise Refused("No accepted work order: bill against a verbal order (who confirmed it, when)")
    by_wo = contract_lines_by_wo(c)
    # only this sheet's quantities, as the client approved them (a correction included)
    given = {x.id: ZERO for x in c.lines}
    for wo_id in ms.totals(ms.lines_of(db, sheet.id)):
        if by_wo.get(wo_id) is None:
            raise Refused("The contract has no line for an item on the sheet")
    for m in book_lines(db, sheet):
        if m.status == "approved" and m.contract_line_id in given:
            given[m.contract_line_id] += Decimal(m.qty)
    seq = (db.scalar(select(RaBill.seq).where(RaBill.contract_id == c.id).order_by(RaBill.seq.desc()).limit(1)) or 0) + 1
    site = db.get(Site, c.site_id)
    on = proforma_on or date.today()
    b = RaBill(code=f"RA-{site.code}-{seq:02d}", contract_id=c.id, site_id=site.id, seq=seq, period_to=sheet.measured_on, order_basis=basis,
               verbal_by=((verbal_by or "").strip() or None) if basis == "verbal" else None, verbal_on=verbal_on if basis == "verbal" else None,
               proforma_on=on, created_by=user.id)  # fmt: skip
    db.add(b)
    try:
        billing._set_lines(db, b, c, given)
    except Exception as exc:  # noqa: BLE001  (its own message: beyond the order, or not in the book)
        detail = getattr(exc, "detail", None) or str(exc)
        raise Refused(detail) from exc
    # rates from the work order only: never typed, never the contract's if they differ
    wl = {cl.id: db.get(ClientWorkOrderLine, cl.wo_line_id) for cl in c.lines if cl.wo_line_id}
    for ln in b.lines:
        if wl.get(ln.contract_line_id) is not None and wl[ln.contract_line_id].rate is not None:
            ln.rate = wl[ln.contract_line_id].rate
    svc.ra_totals(db, b, c)
    b.proforma_no = svc.next_number(db, "PI", on, "PROFORMA")
    db.flush()
    measure.stamp_billed(db, b)
    sheet.ra_bill_id, sheet.status = b.id, "billed"
    return b, warnings(db, b, sheet)


def _work_order(db: Session, site_id: int) -> ClientWorkOrder | None:
    return db.scalar(select(ClientWorkOrder).where(ClientWorkOrder.site_id == site_id).order_by(ClientWorkOrder.status != "accepted", ClientWorkOrder.id.desc()).limit(1))


def warnings(db: Session, b: RaBill, sheet: MeasureSheet | None) -> list[str]:
    out = []
    if sheet and b.proforma_on and b.proforma_on < sheet.measured_on:
        out.append(f"The bill is dated {b.proforma_on:%d-%m-%Y}, before the measurement ({sheet.measured_on:%d-%m-%Y})")
    return out


def tax(db: Session, b: RaBill, c: ClientContract, lines: list[dict]) -> dict:
    """GST on this bill's amounts: the state codes of our GSTIN and the client's decide CGST + SGST
    or IGST; the round-off takes the total to the rupee."""
    ours = svc.our_gstin(db, c.from_gstin_id)
    client = db.get(Client, c.client_id) if c.client_id else None
    gstin = c.client_gstin or (client.gstin if client else None)
    inter = svc.interstate(ours, c.place_of_supply or (client.state if client else None), gstin)
    taxable = cgst = sgst = igst = ZERO
    for ln in lines:
        amt = Decimal(ln["amount"])
        taxable += amt
        cg, sg, ig = svc.line_tax(amt, c.gst_percent, inter)
        cgst, sgst, igst = cgst + cg, sgst + sg, igst + ig
    before = svc.money(taxable) + cgst + sgst + igst
    total = before.quantize(Decimal(1), ROUND_HALF_UP)
    half = Decimal(c.gst_percent) / 2
    return {"interstate": inter, "gst_percent": Decimal(c.gst_percent), "cgst_percent": ZERO if inter else half, "sgst_percent": ZERO if inter else half,
            "igst_percent": Decimal(c.gst_percent) if inter else ZERO, "taxable": svc.money(taxable), "cgst": cgst, "sgst": sgst, "igst": igst,
            "round_off": total - before, "total": total, "our_gstin": ours.gstin if ours else None, "client_gstin": gstin}  # fmt: skip


def proforma(db: Session, b: RaBill) -> dict:
    c = db.get(ClientContract, b.contract_id)
    client = db.get(Client, c.client_id) if c.client_id else None
    sheet = sheet_of_bill(db, b)
    wo = _work_order(db, b.site_id)
    cl = {x.id: x for x in c.lines}
    lines = []
    for ln in b.lines:
        x = cl[ln.contract_line_id]
        w = db.get(ClientWorkOrderLine, x.wo_line_id) if x.wo_line_id else None
        qty = Decimal(ln.certified_qty if ln.certified_qty is not None else ln.qty)
        if not qty and not Decimal(ln.previous_qty):
            continue
        amount = svc.money(qty * Decimal(ln.rate))
        lines.append({"contract_line_id": x.id, "item_no": (w.item_no if w else None) or x.item_no, "description": x.description, "sac": (w.sac if w else None) or c.sac,
                      "unit": x.unit, "previous": Decimal(ln.previous_qty), "this": qty, "cumulative": Decimal(ln.previous_qty) + qty, "rate": Decimal(ln.rate), "amount": amount})  # fmt: skip
    site = db.get(Site, b.site_id)
    order = ({"basis": "verbal", "text": f"Verbal order confirmed by {b.verbal_by} on {b.verbal_on:%d-%m-%Y}"} if b.order_basis == "verbal"
             else {"basis": "wo", "text": f"Work order {wo.client_ref or wo.code}" + (f" dated {wo.accepted_at:%d-%m-%Y}" if wo and wo.accepted_at else "") if wo else "Work order"})  # fmt: skip
    return {
        "id": b.id, "code": b.code, "status": b.status, "title": "PROFORMA INVOICE", "proforma_no": b.proforma_no, "proforma_on": b.proforma_on,
        "measured_on": sheet.measured_on if sheet else None, "sheet_id": sheet.id if sheet else None, "sheet_code": sheet.code if sheet else None,
        "order": order, "buyer": {"name": client.name if client else None, "address": client.address if client else None, "city": client.city if client else None,
                                    "state": client.state if client else None, "gstin": (c.client_gstin or (client.gstin if client else None))},
        "site": {"id": site.id, "code": site.code, "name": site.name}, "lines": lines, "tax": tax(db, b, c, lines), "warnings": warnings(db, b, sheet),
        "invoice_id": db.scalar(select(TaxInvoice.id).where(TaxInvoice.ra_bill_id == b.id)),
    }  # fmt: skip


def checklist(db: Session, b: RaBill) -> list[dict]:
    """Before the bill is sent: each check with what failed. All must pass to send it."""
    c = db.get(ClientContract, b.contract_id)
    cl = {x.id: x for x in c.lines}
    sheet = sheet_of_bill(db, b)
    out = []
    bad = []
    for ln in b.lines:
        x = cl[ln.contract_line_id]
        w = db.get(ClientWorkOrderLine, x.wo_line_id) if x.wo_line_id else None
        if Decimal(ln.qty) and (w is None or w.rate is None or Decimal(w.rate) != Decimal(ln.rate)):
            bad.append(f"{x.item_no or x.description[:30]}: {ln.rate} vs the order's {w.rate if w else 'none'}")
    out.append({"key": "rates", "label": "Rates match the work order", "ok": not bad or b.order_basis == "verbal" and all("none" in m for m in bad), "detail": bad})
    over = []
    for ln in b.lines:
        x = cl[ln.contract_line_id]
        w = db.get(ClientWorkOrderLine, x.wo_line_id) if x.wo_line_id else None
        cum = Decimal(ln.previous_qty) + Decimal(ln.qty)
        if w is not None and w.qty is not None and cum > Decimal(w.qty):
            varied = db.scalar(select(WoDeviation.id).where(WoDeviation.wo_line_id == w.id, WoDeviation.status == "accepted"))
            if not varied and not (x.is_extra and x.approved_by):
                over.append(f"{w.item_no or w.description[:30]}: {cum:f} {w.unit} against the order's {Decimal(w.qty):f}")
    out.append({"key": "qty", "label": "Quantities within the work order (or an approved variation)", "ok": not over, "detail": over})
    layers, edges, unlinked = [], [], []
    if sheet:
        lines = ms.lines_of(db, sheet.id)
        for ln in lines:
            if ln.wo_line_id and ln.kind == "line":
                w = db.get(ClientWorkOrderLine, ln.wo_line_id)
                if ln.layer > (w.layers or 1):
                    layers.append(f"{w.item_no or w.description[:30]}: layer {ln.layer}, the order has {w.layers or 1}")
        area_ids = {ln.area_id for ln in lines if ln.area_id}
        for e in db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == sheet.site_id)):
            if e.answer is None and (e.area_a_id in area_ids or e.area_b_id in area_ids):
                a, z = db.get(MeasureArea, e.area_a_id), db.get(MeasureArea, e.area_b_id)
                edges.append(f"{a.code}|{z.code}: {Decimal(e.length_m):.3f} m")
        for aid in sorted(area_ids):
            a = db.get(MeasureArea, aid)
            if a.cad_file_id is None or not a.outline:
                unlinked.append(f"{a.code} {a.name}")
    else:
        unlinked.append("The bill is not made from a measurement sheet")
    out.append({"key": "layers", "label": "No item billed for a layer the work order doesn't have", "ok": not layers, "detail": layers})
    from app.measure import slip  # noqa: PLC0415

    if sheet and slip.is_slip(sheet):
        missing = [w for w, ok in (("the slip's file", sheet.slip_path), ("who signed it", sheet.signed_by), ("when", sheet.signed_on)) if not ok]
        out.append({"key": "slip", "label": "The client's signed slip is attached (who signed it, when)", "ok": not missing, "detail": missing})
        left = [f"{u['particulars']}: {u['why']}" for u in slip.unmapped(db, sheet)]
        out.append({"key": "slip_lines", "label": "Every slip line billed, or listed with why", "ok": True, "detail": left})
    else:
        out.append({"key": "edges", "label": "Shared edges answered", "ok": not edges, "detail": edges})
        out.append({"key": "drawing", "label": "Every area linked to the drawing", "ok": not unlinked, "detail": unlinked})
    return out


def to_tax_invoice(db: Session, b: RaBill, user, on: date | None = None) -> TaxInvoice:
    """The proforma becomes the tax invoice, with its lines (the client's certified quantities
    where they certified)."""
    from app.finance import billing  # noqa: PLC0415

    if b.status not in ("submitted", "certified_by_client", "certified"):
        raise Clash(f"{b.code} is {b.status}: send it first")
    if db.scalar(select(TaxInvoice.id).where(TaxInvoice.ra_bill_id == b.id)):
        raise Clash(f"{b.code} has its tax invoice")
    c = db.get(ClientContract, b.contract_id)
    billing.camera_gate(db, b, c)
    p = proforma(db, b)
    on = on or date.today()
    ours = svc.our_gstin(db, c.from_gstin_id)
    inv = TaxInvoice(number=svc.invoice_number(db, on), invoice_date=on, due_date=on + svc.timedelta(days=30), site_id=b.site_id, contract_id=c.id, ra_bill_id=b.id,
                     client_id=c.client_id, client_gstin=p["buyer"]["gstin"], billing_address=c.billing_address or ", ".join(x for x in (p["buyer"]["address"], p["buyer"]["city"], p["buyer"]["state"]) if x),
                     place_of_supply=c.place_of_supply or p["buyer"]["state"], from_gstin_id=ours.id if ours else None, interstate=p["tax"]["interstate"],
                     retention=b.retention, advance_recovery=b.advance_recovery, other_deduction=b.other_deduction,
                     remark=f"Against {b.code} (proforma {b.proforma_no})", created_by=user.id)  # fmt: skip
    for ln in p["lines"]:
        if not ln["amount"]:
            continue
        inv.lines.append(InvoiceLine(description=f"{ln['item_no'] + ': ' if ln['item_no'] else ''}{ln['description']}", sac=ln["sac"], qty=ln["this"], unit=ln["unit"],
                                     rate=ln["rate"], amount=ln["amount"], gst_percent=c.gst_percent))  # fmt: skip
    svc.invoice_tax(inv)
    db.add(inv)
    b.status = "invoiced"
    db.flush()
    return inv


def area_ids_of(db: Session, sheet_id: int) -> list[int]:
    return sorted({a for a in db.scalars(select(MeasureLine.area_id).where(MeasureLine.sheet_id == sheet_id)) if a})
