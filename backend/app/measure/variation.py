# ruff: noqa: E501
"""A new item or variation for a slip line no work-order item covers (gabda, frame fitting).
Billing proposes its description, unit and rate; the director approves it (or not, with why). On
approval it is added to the work order and the contract as a variation item (V1, V2 ... an extra
beyond the BOQ), the slip line is mapped to it and worked out in its unit, and it is billed with
the sheet and goes to the client with that bill. Until then the line stays listed as unbilled."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.closeout.models import ClientWorkOrderLine
from app.finance.models import ContractLine
from app.measure import slip
from app.measure.models import MeasureLine, MeasureSheet, VariationRequest
from app.tenders.export import inr

D = Decimal


class Refused(ValueError):
    pass


def propose(db: Session, sheet: MeasureSheet, line: MeasureLine, *, description: str, unit: str, rate: Decimal, user_id) -> VariationRequest:
    if line.sheet_id != sheet.id:
        raise Refused("That line is not on this sheet")
    if line.wo_line_id is not None:
        raise Refused("That line is mapped to a work-order item already")
    if not description.strip() or not unit.strip():
        raise Refused("Give the item's description and unit")
    if D(rate) <= 0:
        raise Refused("Give the rate")
    if db.scalar(select(VariationRequest.id).where(VariationRequest.line_id == line.id, VariationRequest.status != "rejected")):
        raise Refused("A variation is asked for this line already")
    v = VariationRequest(site_id=sheet.site_id, sheet_id=sheet.id, line_id=line.id, particulars=line.particulars, description=description.strip(),
                         unit=unit.strip(), rate=D(rate).quantize(D("0.01")), created_by=user_id)  # fmt: skip
    db.add(v)
    db.flush()
    return v


def decide(db: Session, v: VariationRequest, *, approve: bool, note: str | None, user_id) -> list[str]:
    """The director's decision. Approved: the variation item on the work order and the contract,
    the slip line mapped to it (when its sheet is still a draft). Returns what was done."""
    from app.measure import bill  # noqa: PLC0415

    if v.status != "proposed":
        raise Refused(f"The variation is {v.status} already")
    v.decided_by, v.decided_at, v.decision_note = user_id, datetime.now(UTC), (note or "").strip() or None
    if not approve:
        if not v.decision_note:
            raise Refused("Say why it is not approved")
        v.status = "rejected"
        return ["Not approved: the line stays unbilled"]
    wo = bill._work_order(db, v.site_id)
    if wo is None:
        raise Refused("The site has no work order to add the variation to")
    c = bill.contract_of(db, v.site_id)
    line = db.get(MeasureLine, v.line_id) if v.line_id else None
    sheet = db.get(MeasureSheet, v.sheet_id)
    mapped = line is not None and sheet is not None and sheet.status == "draft"
    q = how = None
    if mapped:  # the slip line in the new item's unit: the variation's quantity
        t = line.typed or {}
        no = D(str(t.get("no")).strip()) if t.get("no") not in (None, "") else D(1)
        q, how = slip.work_out(v.unit, no, slip.feet(t.get("length")), slip.feet(t.get("width")))
    n = (db.scalar(select(func.count(VariationRequest.id)).where(VariationRequest.site_id == v.site_id, VariationRequest.status == "approved")) or 0) + 1
    order = (db.scalar(select(func.max(ClientWorkOrderLine.sort_order)).where(ClientWorkOrderLine.work_order_id == wo.id)) or 0) + 1
    w = ClientWorkOrderLine(work_order_id=wo.id, sort_order=order, item_no=f"V{n}", description=f"Variation: {v.description}", unit=v.unit, rate=v.rate,
                            qty=q.quantize(D("0.001")) if q is not None else None)  # fmt: skip
    db.add(w)
    db.flush()
    # an extra beyond the BOQ, approved by the director's decision here
    c.lines.append(ContractLine(sort_order=order, item_no=w.item_no, description=w.description, unit=v.unit, qty=w.qty or D(0), rate=v.rate, is_extra=True,
                                wo_line_id=w.id, approved_by=user_id, approved_at=v.decided_at))  # fmt: skip
    v.status, v.wo_line_id = "approved", w.id
    done = [f"Added to the work order as item {w.item_no} ({v.unit} at {inr(v.rate)}), an extra beyond the BOQ"]
    if mapped:
        line.wo_line_id, line.item_no, line.unit, line.qty, line.formula = w.id, w.item_no, v.unit, q, how
        db.flush()
        slip.totals(db, sheet)
        done.append(f"The slip line is mapped to {w.item_no} and billed with {sheet.code}")
    else:
        done.append("Map the slip line to the new item on a draft sheet to bill it")
    return done


def for_sheet(db: Session, sheet_id: int) -> list[VariationRequest]:
    return list(db.scalars(select(VariationRequest).where(VariationRequest.sheet_id == sheet_id).order_by(VariationRequest.id)))


def out(v: VariationRequest) -> dict:
    return {"id": v.id, "sheet_id": v.sheet_id, "line_id": v.line_id, "particulars": v.particulars, "description": v.description, "unit": v.unit, "rate": v.rate,
            "status": v.status, "decided_at": v.decided_at, "decision_note": v.decision_note, "wo_line_id": v.wo_line_id, "ra_bill_id": v.ra_bill_id,
            "created_at": v.created_at}  # fmt: skip
