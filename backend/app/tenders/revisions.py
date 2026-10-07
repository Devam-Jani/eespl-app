"""Tender revisions: R0 is frozen when the tender is submitted; the next change to the BOQ or the
T&C starts R1 as a draft, and so on.

A snapshot holds what was sent to the client and nothing else: the header, sections, lines with
selling rates, the T&C text and the totals. Cost, margin, price source, suggestion scores and
the client's own rates are never in it, so an exported revision cannot leak them either.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import TcClause
from app.tenders import pricing
from app.tenders.models import BoqLine, BoqSection, Tender, TenderRevision, TenderTc
from app.tenders.service import clause_text

LINE_FIELDS = (
    "id",
    "section_id",
    "sort_order",
    "client_item_no",
    "description",
    "unit",
    "unit_raw",
    "qty",
    "qty_note",
    "rate",
    "amount",
    "our_product",
    "our_remarks",
    "status",
    "source_row",
)


def label(rev_no: int) -> str:
    return f"R{rev_no}"


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def frozen(db: Session, tender: Tender) -> TenderRevision | None:
    """The submitted revision for the tender's current revision number, if there is one."""
    return db.scalar(
        select(TenderRevision).where(
            TenderRevision.tender_id == tender.id, TenderRevision.rev_no == tender.revision
        )
    )


def submitted_count(db: Session, tender: Tender) -> int:
    return len(
        db.scalars(select(TenderRevision.id).where(TenderRevision.tender_id == tender.id)).all()
    )


def revision_label(db: Session, tender: Tender) -> str:
    return label(tender.revision) if frozen(db, tender) else f"{label(tender.revision)} (draft)"


def build_snapshot(db: Session, tender: Tender) -> dict[str, Any]:
    """The tender as it stands now, in the snapshot shape (also used for live exports)."""
    totals = pricing.tender_totals(db, tender)
    sections = db.scalars(
        select(BoqSection).where(BoqSection.tender_id == tender.id).order_by(BoqSection.sort_order)
    ).all()
    lines = db.scalars(
        select(BoqLine)
        .where(BoqLine.tender_id == tender.id)
        .order_by(BoqLine.sort_order, BoqLine.id)
    ).all()
    tc = db.execute(
        select(TenderTc, TcClause)
        .outerjoin(TcClause, TcClause.id == TenderTc.clause_id)
        .where(TenderTc.tender_id == tender.id)
        .order_by(TenderTc.sort_order, TenderTc.id)
    ).all()
    return {
        "rev_no": tender.revision,
        "label": label(tender.revision),
        "tender": {
            "code": tender.code,
            "name": tender.name,
            "client_name": tender.client.name,
            "site_name": tender.site_name,
            "site_city": tender.site_city,
            "site_state": tender.site_state,
        },
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "note": s.note,
                "sort_order": s.sort_order,
                "total": _json(totals.sections.get(s.id, Decimal(0))),
            }
            for s in sections
        ],
        "lines": [{f: _json(getattr(ln, f)) for f in LINE_FIELDS} for ln in lines],
        "tc": [clause_text(c, t.text_override) for t, c in tc],
        "totals": {
            "subtotal": _json(totals.subtotal),
            "gst_percent": _json(totals.gst_percent),
            "gst": _json(totals.gst),
            "grand_total": _json(totals.grand_total),
        },
    }


def submit(
    db: Session, tender: Tender, user_id: uuid.UUID | None, note: str | None
) -> TenderRevision:
    """Freeze the current revision and mark the tender submitted. When this revision is already
    frozen (set back to draft without changes), the tender is marked submitted again."""
    if tender.status == "submitted" and frozen(db, tender):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{label(tender.revision)} is already submitted. Change the BOQ or T&C to start "
            f"{label(tender.revision + 1)}.",
        )
    revision = frozen(db, tender)
    if revision is None:
        revision = TenderRevision(
            tender_id=tender.id,
            rev_no=tender.revision,
            snapshot=build_snapshot(db, tender),
            submitted_by=user_id,
            note=(note or "").strip() or None,
        )
        db.add(revision)
    tender.status = "submitted"
    db.flush()
    return revision


def start_next_if_frozen(db: Session, tender: Tender) -> tuple[int, int] | None:
    """Before a change to the BOQ or T&C: if the current revision was submitted, the change goes
    into the next revision, as a draft. Returns (old, new) revision numbers when one started."""
    if frozen(db, tender) is None:
        return None
    old = tender.revision
    tender.revision = old + 1
    if tender.status == "submitted":
        tender.status = "draft"
    db.flush()
    return old, tender.revision


def get_revision(db: Session, tender: Tender, rev_no: int) -> TenderRevision:
    revision = db.scalar(
        select(TenderRevision).where(
            TenderRevision.tender_id == tender.id, TenderRevision.rev_no == rev_no
        )
    )
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label(rev_no)} has not been submitted")
    return revision


def _key(line: dict[str, Any]) -> tuple[str, str]:
    return (
        (line.get("client_item_no") or "").strip().lower(),
        " ".join(line["description"].lower().split()),
    )


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _delta(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None and b is None:
        return None
    return (b or Decimal(0)) - (a or Decimal(0))


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Per line: rate and amount in a and b, and the change. Lines are matched by id, else by
    (item no, description) — a re-import gives lines new ids."""
    b_by_id = {ln["id"]: ln for ln in b["lines"]}
    b_by_key: dict[tuple[str, str], list[dict]] = {}
    for ln in b["lines"]:
        b_by_key.setdefault(_key(ln), []).append(ln)
    used: set[int] = set()
    rows = []

    def row(la: dict | None, lb: dict | None) -> dict[str, Any]:
        src = lb or la
        ra, rb = _dec(la and la["rate"]), _dec(lb and lb["rate"])
        aa, ab = _dec(la and la["amount"]), _dec(lb and lb["amount"])
        if la is None:
            change = "added"
        elif lb is None:
            change = "removed"
        else:
            change = "same" if (ra, aa) == (rb, ab) else "changed"
        return {
            "item_no": src["client_item_no"],
            "description": src["description"],
            "change": change,
            "rate_a": ra,
            "rate_b": rb,
            "rate_delta": _delta(ra, rb),
            "amount_a": aa,
            "amount_b": ab,
            "amount_delta": _delta(aa, ab),
        }

    for la in a["lines"]:
        lb = b_by_id.get(la["id"])
        if lb is None or lb["id"] in used:
            lb = next((x for x in b_by_key.get(_key(la), []) if x["id"] not in used), None)
        if lb is not None:
            used.add(lb["id"])
        rows.append(row(la, lb))
    rows.extend(row(None, lb) for lb in b["lines"] if lb["id"] not in used)
    ta, tb = a["totals"], b["totals"]
    return {
        "a": a["label"],
        "b": b["label"],
        "lines": rows,
        "subtotal_a": Decimal(ta["subtotal"]),
        "subtotal_b": Decimal(tb["subtotal"]),
        "subtotal_delta": Decimal(tb["subtotal"]) - Decimal(ta["subtotal"]),
        "grand_total_a": Decimal(ta["grand_total"]),
        "grand_total_b": Decimal(tb["grand_total"]),
        "grand_total_delta": Decimal(tb["grand_total"]) - Decimal(ta["grand_total"]),
    }
