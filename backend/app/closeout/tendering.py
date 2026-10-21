# ruff: noqa: E501  (column definitions read better unwrapped)
"""One tender, several civil contractors: a developer's BOQ reaches us through the contractors
bidding for the main job. Each gets its own quotation (its own revisions and rates), all built
from the same BOQ and working. When one wins the main contract, the others close as "main job
lost by the contractor" (not our loss); our own stage (bidders L1/L2/L3, negotiation, won or lost)
then runs with the winner."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.common import not_found, now, today, unprocessable
from app.closeout.models import TenderCustomer
from app.masters.models import Client
from app.quotations.models import UOMS, Quotation, QuotationItem, QuotationLine
from app.tenders.models import BoqLine, BoqSection, Tender

UNIT_TO_UOM = {"sqm": "sqm", "sq m": "sqm", "sqft": "sqft", "sq ft": "sqft", "rmt": "rmt", "rm": "rmt", "rft": "rft", "nos": "nos", "no": "nos", "kg": "kg", "ltr": "ltr", "ls": "ls"}  # fmt: skip


def _uom(unit: str | None) -> str:
    u = (unit or "sqm").strip().lower().rstrip(".")
    u = UNIT_TO_UOM.get(u, u)
    return u if u in UOMS else "sqm"


def quotation_for(db: Session, tender: Tender, client: Client, user_id=None) -> Quotation:
    """A quotation of the tender for one contractor: the BOQ's sections as items, its lines with
    the working's rates (the same for every contractor until someone changes one)."""
    from app.material import service as material  # noqa: PLC0415

    q = Quotation(
        code=material.next_code(db, "QTN"), revision=0, is_latest=True, client_id=client.id, tender_id=tender.id,
        client_firm=client.name, client_city=client.city, client_state=client.state, project=tender.name,
        quote_date=today(), status="draft", salesperson_id=tender.owner_id, guarantee_years=tender.guarantee_years,
        created_by=user_id,
    )  # fmt: skip
    sections = list(
        db.scalars(
            select(BoqSection)
            .where(BoqSection.tender_id == tender.id)
            .order_by(BoqSection.sort_order, BoqSection.id)
        )
    )
    lines = list(
        db.scalars(
            select(BoqLine)
            .where(BoqLine.tender_id == tender.id)
            .order_by(BoqLine.sort_order, BoqLine.id)
        )
    )
    groups: list[tuple[str, list[BoqLine]]] = [
        (s.title, [ln for ln in lines if ln.section_id == s.id]) for s in sections
    ]
    loose = [ln for ln in lines if ln.section_id is None]
    if loose:
        groups.append((tender.name, loose))
    for i, (title, rows) in enumerate(g for g in groups if g[1]):
        item = QuotationItem(
            sort_order=i, name=title[:200], budget_title=title, options=[], specs=[]
        )
        for j, ln in enumerate(rows):
            item.lines.append(
                QuotationLine(
                    sort_order=j,
                    description=ln.description,
                    uom=_uom(ln.unit),
                    rate=ln.rate,
                    rate_source="working" if ln.rate else None,
                    cost_rate=ln.cost_rate,
                    margin_percent=ln.margin_percent,
                    qty=ln.qty,
                )  # fmt: skip
            )
        q.items.append(item)
    db.add(q)
    db.flush()
    return q


def add_customer(
    db: Session, tender: Tender, client_id: int, user_id=None, note: str | None = None
) -> TenderCustomer:
    client = db.get(Client, client_id)
    if client is None:
        raise not_found("Client not found")
    if db.scalar(
        select(TenderCustomer.id).where(
            TenderCustomer.tender_id == tender.id, TenderCustomer.client_id == client_id
        )
    ):
        raise unprocessable(f"The tender is already quoted to {client.name}")
    if tender.main_contractor_id:
        raise unprocessable("The main contract is already decided")
    q = quotation_for(db, tender, client, user_id)
    tc = TenderCustomer(
        tender_id=tender.id, client_id=client_id, quotation_id=q.id, note=note, created_by=user_id
    )
    db.add(tc)
    db.flush()
    return tc


def main_won(db: Session, tender: Tender, customer: TenderCustomer, user_id=None) -> dict:
    """The contractor who won the main contract; the others close as "main job lost by the
    contractor". Their open quotations close with that reason (not counted as our loss)."""
    if customer.tender_id != tender.id:
        raise not_found("Not a customer of this tender")
    if tender.main_contractor_id:
        raise unprocessable("The main contract is already decided")
    at = now()
    closed = []
    for c in db.scalars(select(TenderCustomer).where(TenderCustomer.tender_id == tender.id)):
        c.main_status = "won" if c.id == customer.id else "lost"
        c.decided_at = at
        if c.id == customer.id or not c.quotation_id:
            continue
        q = db.get(Quotation, c.quotation_id)
        latest = (
            db.scalar(select(Quotation).where(Quotation.code == q.code, Quotation.is_latest))
            if q
            else None
        )
        if latest is not None and latest.status in ("draft", "sent", "negotiation"):
            latest.status, latest.lost_reason, latest.decided_at = "lost", "main_job_lost", at
            client = db.get(Client, c.client_id)
            latest.lost_note = f"Main job lost by the contractor ({client.name if client else ''} did not win the main contract)"
            closed.append(latest.code)
    tender.main_contractor_id = customer.client_id
    db.flush()
    return {"winner": customer.client_id, "closed_quotations": closed}


def customers_out(db: Session, tender: Tender) -> list[dict]:
    out = []
    for c in db.scalars(
        select(TenderCustomer)
        .where(TenderCustomer.tender_id == tender.id)
        .order_by(TenderCustomer.id)
    ):
        client = db.get(Client, c.client_id)
        q = db.get(Quotation, c.quotation_id) if c.quotation_id else None
        latest = (
            db.scalar(select(Quotation).where(Quotation.code == q.code, Quotation.is_latest))
            if q
            else None
        )
        total = sum(
            (
                Decimal(ln.rate or 0) * Decimal(ln.qty or 0)
                for it in (latest.items if latest else [])
                for ln in it.lines
            ),
            Decimal(0),
        )
        out.append({"id": c.id, "client_id": c.client_id, "client": client.name if client else None, "main_status": c.main_status,
                    "main_label": {"pending": "bidding for the main job", "won": "won the main contract", "lost": "main job lost by the contractor"}[c.main_status],
                    "quotation": {"id": latest.id, "code": latest.code, "revision": latest.revision, "status": latest.status, "lost_reason": latest.lost_reason,
                                  "total": total} if latest else None, "decided_at": c.decided_at, "note": c.note})  # fmt: skip
    return out
