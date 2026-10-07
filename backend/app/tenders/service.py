"""Tender access rules, numbering and T&C copying."""

import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, false, or_, select, text, true
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.masters.models import TcClause, TcTemplate
from app.tenders.models import Tender, TenderMember, TenderTc


def scope_condition(scope: str, principal: Principal) -> ColumnElement[bool]:
    """Which tenders a scope covers.

    all: every tender; assigned: the caller is the owner or a member; own: the caller created it.
    """
    uid = principal.user.id
    if scope == "all":
        return true()
    if scope == "assigned":
        members = select(TenderMember.tender_id).where(TenderMember.user_id == uid)
        return or_(Tender.owner_id == uid, Tender.id.in_(members))
    if scope == "own":
        return Tender.created_by == uid
    return false()


def covers(scope: str, principal: Principal, tender: Tender) -> bool:
    uid = principal.user.id
    if scope == "all":
        return True
    if scope == "assigned":
        return tender.owner_id == uid or any(m.user_id == uid for m in tender.members)
    if scope == "own":
        return tender.created_by == uid
    return False


def get_visible(db: Session, tender_id: int, view_scope: str, principal: Principal) -> Tender:
    """The tender, or 404 when it does not exist *or* the caller may not see it."""
    tender = db.get(Tender, tender_id)
    if tender is None or not covers(view_scope, principal, tender):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tender not found")
    return tender


def check_edit(tender: Tender, edit_scope: str, principal: Principal) -> None:
    if not covers(edit_scope, principal, tender):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this tender")


def next_code(db: Session, on: date | None = None) -> str:
    """T-2026-0001, T-2026-0002 ... per year. One atomic statement, so concurrent creations
    never get the same number."""
    year = (on or date.today()).year
    value = db.execute(
        text(
            "INSERT INTO tender_sequences (year, last_value) VALUES (:y, 1) "
            "ON CONFLICT (year) DO UPDATE SET last_value = tender_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"y": year},
    ).scalar_one()
    return f"T-{year}-{value:04d}"


def copy_template(db: Session, tender: Tender, template_id: int | None, user_id: uuid.UUID) -> None:
    """Copy a template's clauses (default template when none is given) into the tender."""
    template = (
        db.get(TcTemplate, template_id)
        if template_id
        else db.scalar(select(TcTemplate).where(TcTemplate.is_default))
    )
    if template_id and template is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown T&C template")
    if template is None:
        return
    tender.tc_template_id = template.id
    for i, item in enumerate(template.clauses, start=1):
        db.add(
            TenderTc(
                tender_id=tender.id, clause_id=item.clause_id, sort_order=i, created_by=user_id
            )
        )


def clause_text(clause: TcClause | None, override: str | None) -> str:
    return override if override else (clause.text if clause else "")
