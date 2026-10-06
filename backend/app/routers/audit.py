import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.auth.deps import require_permission
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.models import AuditLog, User
from app.schemas import AuditOut, AuditPage

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(require_permission("audit.view"))],
)


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _filters(user, entity, entity_id, action, date_from, date_to) -> list:
    filters: list = []
    if user:
        try:
            filters.append(AuditLog.user_id == uuid.UUID(user))
        except ValueError:
            filters.append(AuditLog.user.has(User.email.ilike(f"%{user.strip()}%")))
    if entity:
        filters.append(AuditLog.entity == entity)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)
    if action:
        filters.append(or_(AuditLog.action == action, AuditLog.action.startswith(f"{action}.")))
    if date_from:
        filters.append(AuditLog.at >= _start_of(date_from))
    if date_to:
        filters.append(AuditLog.at < _start_of(date_to + timedelta(days=1)))
    return filters


UserFilter = Annotated[str | None, Query(description="User id, or part of an email")]
DateFrom = Annotated[date | None, Query(description="Inclusive, UTC")]
DateTo = Annotated[date | None, Query(description="Inclusive, UTC")]


@router.get("/export")
def export_audit(
    db: DbSession,
    user: UserFilter = None,
    entity: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    date_from: DateFrom = None,
    date_to: DateTo = None,
):
    rows = db.scalars(
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .where(*_filters(user, entity, entity_id, action, date_from, date_to))
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(EXPORT_ROW_LIMIT)
    )
    return xlsx_response(
        "audit-log",
        ["When", "User", "Action", "Entity", "Entity id", "Before", "After", "IP"],
        [[r.at, r.user.email if r.user else None, r.action, r.entity, r.entity_id,
          json.dumps(r.before, default=str) if r.before else None,
          json.dumps(r.after, default=str) if r.after else None, r.ip] for r in rows],
    )  # fmt: skip


@router.get("")
def list_audit(
    db: DbSession,
    user: Annotated[str | None, Query(description="User id, or part of an email")] = None,
    entity: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    date_from: Annotated[date | None, Query(description="Inclusive, UTC")] = None,
    date_to: Annotated[date | None, Query(description="Inclusive, UTC")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    filters = _filters(user, entity, entity_id, action, date_from, date_to)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    rows = db.scalars(
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .where(*filters)
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        AuditOut(
            id=r.id,
            at=r.at,
            user_id=r.user_id,
            user_email=r.user.email if r.user else None,
            action=r.action,
            entity=r.entity,
            entity_id=r.entity_id,
            before=r.before,
            after=r.after,
            ip=r.ip,
        )
        for r in rows
    ]
    return AuditPage(items=items, total=total)
