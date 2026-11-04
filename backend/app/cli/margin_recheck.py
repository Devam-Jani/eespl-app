# ruff: noqa: E501
"""python -m app.cli margin-recheck [--apply] (Prompt 38, Part 1): the margin was worked as a
markup, cost × (1 + m); it is on the selling price, cost ÷ (1 − m). No rate changes silently:

- without --apply: every system-priced line on a draft or submitted tender, and on a draft, sent or
  negotiation quotation, whose rate would change, with its old rate, new rate and difference;
- with --apply: such a tender line becomes "suggested" at the new rate (someone accepts it on the BOQ
  screen); a quotation line has no "suggested" state, so its rate stays and its rate note carries the
  new rate for someone to accept by re-pricing the line.

Submitted tender revisions (frozen snapshots) and issued estimates are never touched."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.margin import MarginTooHigh
from app.quotations.models import Quotation, QuotationItem, QuotationLine
from app.tenders import pricing
from app.tenders.models import BoqLine, Tender

TENDER_OPEN = ("draft", "submitted")
QUOTATION_OPEN = ("draft", "sent", "negotiation")
NOTE = "Margin on the selling price: the new rate is ₹{new} (was ₹{old}); re-price this line to accept it."


@dataclass
class Change:
    kind: str  # tender, quotation
    doc: str  # T-... / QTN-... R0
    line_id: int
    description: str
    cost: Decimal
    margin: Decimal
    old: Decimal
    new: Decimal | None  # None: a margin of 100 % or more, which has no rate now

    @property
    def diff(self) -> Decimal | None:
        return None if self.new is None else self.new - self.old


def _new(cost: Decimal, margin: Decimal) -> Decimal | None:
    try:
        return pricing.rate_from_margin(Decimal(cost), Decimal(margin))
    except MarginTooHigh:
        return None


def find(db: Session) -> list[Change]:
    out: list[Change] = []
    q = (select(BoqLine, Tender).join(Tender, Tender.id == BoqLine.tender_id)
         .where(Tender.status.in_(TENDER_OPEN), BoqLine.source == "system", BoqLine.cost_rate.is_not(None), BoqLine.margin_percent.is_not(None), BoqLine.rate.is_not(None))
         .order_by(Tender.id, BoqLine.id))  # fmt: skip
    for ln, t in db.execute(q):
        new = _new(ln.cost_rate, ln.margin_percent)
        if new != ln.rate:
            out.append(Change("tender", t.code, ln.id, (ln.description or "")[:60], ln.cost_rate, ln.margin_percent, ln.rate, new))
    q = (select(QuotationLine, Quotation).join(QuotationItem, QuotationItem.id == QuotationLine.item_id).join(Quotation, Quotation.id == QuotationItem.quotation_id)
         .where(Quotation.status.in_(QUOTATION_OPEN), QuotationLine.rate_source == "system", QuotationLine.cost_rate.is_not(None), QuotationLine.margin_percent.is_not(None), QuotationLine.rate.is_not(None))
         .order_by(Quotation.id, QuotationLine.id))  # fmt: skip
    for ln, qt in db.execute(q):
        new = _new(ln.cost_rate, ln.margin_percent)
        if new != ln.rate:
            out.append(Change("quotation", f"{qt.code} R{qt.revision}" if hasattr(qt, "revision") else qt.code, ln.id, (ln.description or "")[:60], ln.cost_rate, ln.margin_percent, ln.rate, new))
    return out


def apply(db: Session, changes: list[Change]) -> dict[str, int]:
    done = {"tender_lines_suggested": 0, "quotation_lines_noted": 0, "left_as_they_are": 0}
    touched: set[int] = set()
    for c in changes:
        if c.new is None:  # 100 % or more: no rate to suggest; a person sets a margin below 100 %
            done["left_as_they_are"] += 1
            continue
        if c.kind == "tender":
            ln = db.get(BoqLine, c.line_id)
            ln.rate, ln.status = c.new, "suggested"
            pricing.refresh_amount(ln)
            touched.add(ln.tender_id)
            done["tender_lines_suggested"] += 1
        else:
            ln = db.get(QuotationLine, c.line_id)
            ln.rate_note = NOTE.format(new=c.new, old=c.old)
            done["quotation_lines_noted"] += 1
    for tid in touched:
        pricing.refresh_tender_total(db, db.get(Tender, tid))
    return done


def report(changes: list[Change]) -> str:
    rows = [f"{c.kind:9} {c.doc:22} line {c.line_id:<7} cost {c.cost:>10} at {c.margin:>5}%  old {c.old:>10}  new {('none: ' + chr(8805) + '100%') if c.new is None else c.new:>10}  diff {c.diff if c.diff is not None else '-':>9}  {c.description}" for c in changes]
    by = {k: sum(1 for c in changes if c.kind == k) for k in ("tender", "quotation")}
    total = sum((c.diff for c in changes if c.diff is not None), Decimal(0))
    rows.append(f"lines whose rate would change: {len(changes)} (tender {by['tender']}, quotation {by['quotation']}); sum of the differences ₹{total}")
    return "\n".join(rows)
