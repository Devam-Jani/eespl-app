# ruff: noqa: E501
"""Bills from a site slip: the client's person writes the work done in a notebook (feet and inches),
signs and dates it, and the page is scanned. The slip is attached, its lines entered as written
(No x L x W, or a count), each mapped to a work-order item; the quantity is worked out in the
item's unit (feet to metres with 3.2808: 1 m = 3.2808 ft); lines not mapped to an item, or left
out of the bill, stay listed with the slip.

The signed slip is the client's approval: sending the sheet puts its totals in the measurement book
as approved by the slip's signatory (recorded by our staff, the slip as the signed copy)."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.models import ClientWorkOrderLine
from app.measure import geom
from app.measure.models import MeasureLine, MeasureSheet

FT_PER_M = Decimal("3.2808")
D = Decimal
_FT_IN = re.compile(r"""^\s*(-?\d+(?:\.\d+)?)\s*(?:'|ft\.?|feet)\s*(?:(\d+(?:\.\d+)?)\s*(?:"|''|in\.?|inch(?:es)?)?)?\s*$""", re.I)
_IN = re.compile(r"""^\s*(\d+(?:\.\d+)?)\s*(?:"|''|in\.?|inch(?:es)?)\s*$""", re.I)


def feet(text: str | float | int | Decimal | None) -> Decimal | None:
    """A length as written on a slip, in feet: 16'0", 116'9" (116.75), 13' 10" (13.8333...),
    16 ft 9 in, 9" (0.75), or decimal feet as typed in the old sheets (13.83)."""
    if text is None:
        return None
    if isinstance(text, int | float | Decimal):
        return D(str(text))
    s = str(text).strip().replace("’", "'").replace("”", '"').replace("″", '"').replace("′", "'")
    if not s:
        return None
    m = _FT_IN.match(s)
    if m:
        ft, inch = D(m.group(1)), D(m.group(2) or 0)
        if inch >= 12:
            raise ValueError(f"'{text}': inches run 0 to 11")
        return ft + inch / 12 if ft >= 0 else ft - inch / 12
    m = _IN.match(s)
    if m:
        return D(m.group(1)) / 12
    try:
        return D(s)
    except ArithmeticError as exc:
        raise ValueError(f"'{text}' is not a length in feet and inches") from exc


def work_out(unit: str | None, no: Decimal, length_ft: Decimal | None, width_ft: Decimal | None) -> tuple[Decimal, str]:
    """A slip line's quantity in its item's unit, and how: sqft = No x L x W in feet; sqm = No x
    (L / 3.2808) x (W / 3.2808); rmt = No x L / 3.2808; rft = No x L; a count = No (x L when the
    slip gives one, "Periphery 1 x 25")."""
    u = (unit or "").strip().lower().replace(".", "").replace(" ", "")
    if u in ("nos", "no", "each", "set", "pcs"):
        q = no * (length_ft if length_ft is not None else D(1))
        return q, f"{_n(no)}{f' × {_n(length_ft)}' if length_ft is not None else ''} = {_n(q)} nos"
    if length_ft is None:
        raise ValueError("Give the length")
    if u in ("rmt", "m", "rm", "rmtr"):
        q = no * length_ft / FT_PER_M
        return q, f"{_n(no)} × {_n(length_ft)} ft = {_n(no * length_ft)} R ft ÷ 3.2808 = {_n(q)} R mt"
    if u in ("rft", "ft"):
        q = no * length_ft
        return q, f"{_n(no)} × {_n(length_ft)} = {_n(q)} R ft"
    if width_ft is None:
        raise ValueError("Give the width (or height) for an area")
    if u == "sqm":
        q = no * (length_ft / FT_PER_M) * (width_ft / FT_PER_M)
        return q, f"{_n(no)} × {_n(length_ft)} ft × {_n(width_ft)} ft ÷ 3.2808² = {_n(q)} sqm"
    q = no * length_ft * width_ft
    return q, f"{_n(no)} × {_n(length_ft)} ft × {_n(width_ft)} ft = {_n(q)} sqft"


def _n(v: Decimal, places: int = 4) -> str:
    q = D(v).quantize(D(1).scaleb(-places))
    return f"{q.normalize():f}"


def new(db: Session, site, *, measured_on: date, title: str | None, slip_path: str | None, slip_name: str | None, slip_on: date | None,
        signed_by: str | None, signed_on: date | None, user_id) -> MeasureSheet:  # fmt: skip
    from app.measure import service as ms  # noqa: PLC0415

    s = ms.new_sheet(db, site, measured_on, title, user_id)
    s.slip_path, s.slip_name, s.slip_on, s.signed_by, s.signed_on = slip_path, slip_name, slip_on, signed_by, signed_on
    return s


def add_line(db: Session, sheet: MeasureSheet, *, particulars: str, no: str | None, length: str | None, width: str | None, wo_line_id: int | None, billed: bool = True,
             reason: str | None = None) -> MeasureLine:  # fmt: skip
    """A slip's line as written; worked out in its item's unit when it is mapped to one."""
    if sheet.status != "draft":
        raise ValueError(f"{sheet.code} is {sheet.status}")
    n = D(str(no).strip()) if no not in (None, "") else D(1)
    lf, wf = feet(length), feet(width)
    wo = db.get(ClientWorkOrderLine, wo_line_id) if wo_line_id else None
    order = (db.scalar(select(MeasureLine.sort_order).where(MeasureLine.sheet_id == sheet.id).order_by(MeasureLine.sort_order.desc()).limit(1)) or 0) + 1
    ln = MeasureLine(sheet_id=sheet.id, sort_order=order, kind="deduction" if n < 0 else "line", particulars=particulars.strip(), billed=billed, reason=reason,
                     typed={"no": no, "length": length, "width": width}, no=n, layer=1)  # fmt: skip
    if lf is not None:
        ln.length_m = lf / FT_PER_M
    if wf is not None:
        ln.width_m = wf / FT_PER_M
    if wo is not None:
        q, how = work_out(wo.unit, n, lf, wf)
        ln.wo_line_id, ln.item_no, ln.unit, ln.qty, ln.formula = wo.id, wo.item_no, wo.unit, q, how
        ln.total = None  # the item's total line converts and rounds once (as the old sheets)
    db.add(ln)
    db.flush()
    totals(db, sheet)
    return ln


def totals(db: Session, sheet: MeasureSheet) -> None:
    """Each item's total line: its billed lines added at full precision, rounded once to 3
    decimals (the billing team's sheet adds its lines the same way)."""
    for old in db.scalars(select(MeasureLine).where(MeasureLine.sheet_id == sheet.id, MeasureLine.kind == "total")):
        db.delete(old)
    db.flush()
    per: dict[int, list[MeasureLine]] = {}
    for ln in lines_of(db, sheet):
        if ln.wo_line_id and ln.billed and ln.qty is not None:
            per.setdefault(ln.wo_line_id, []).append(ln)
    last = (db.scalar(select(MeasureLine.sort_order).where(MeasureLine.sheet_id == sheet.id).order_by(MeasureLine.sort_order.desc()).limit(1)) or 0) + 1000
    for i, (wo_id, rows) in enumerate(per.items()):
        q = sum((D(r.qty) for r in rows), D(0))
        db.add(MeasureLine(sheet_id=sheet.id, sort_order=last + i, kind="total", wo_line_id=wo_id, item_no=rows[0].item_no, unit=rows[0].unit, layer=1,
                           particulars=f"Total quantity, item {rows[0].item_no or ''}".strip(), qty=q, total=geom.round3(q), formula=f"{len(rows)} lines added: {_n(q)}"))  # fmt: skip
    db.flush()


def lines_of(db: Session, sheet: MeasureSheet) -> list[MeasureLine]:
    return list(db.scalars(select(MeasureLine).where(MeasureLine.sheet_id == sheet.id).order_by(MeasureLine.sort_order)))


def unmapped(db: Session, sheet: MeasureSheet) -> list[dict]:
    """The slip's lines not billed: not mapped to a work-order item (with its variation request, if
    one is asked), or left out (with why)."""
    from app.measure.models import VariationRequest  # noqa: PLC0415
    from app.tenders.export import inr  # noqa: PLC0415

    asked = {v.line_id: v for v in db.scalars(select(VariationRequest).where(VariationRequest.sheet_id == sheet.id).order_by(VariationRequest.id))}
    out = []
    for ln in lines_of(db, sheet):
        if ln.wo_line_id is None:
            v = asked.get(ln.id)
            why = "not mapped to a work-order item"
            if v is not None and v.status == "proposed":
                why += f": variation asked ({v.description}, {v.unit} at {inr(v.rate)}), waiting for the director"
            elif v is not None and v.status == "rejected":
                why += f": variation not approved ({v.decision_note})"
            out.append({"line_id": ln.id, "particulars": ln.particulars, "typed": ln.typed, "why": why,
                        "variation": {"id": v.id, "status": v.status} if v is not None else None})
        elif not ln.billed:
            out.append({"line_id": ln.id, "particulars": ln.particulars, "typed": ln.typed, "why": ln.reason or "left out of the bill"})
    return out


def is_slip(sheet: MeasureSheet) -> bool:
    return bool(sheet.slip_path or sheet.signed_by)
