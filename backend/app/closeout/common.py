"""Shared bits: the clock (tests replace it), codes, the lock rule and the client's billing role
lookups."""

from datetime import UTC, date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return now().astimezone(IST).date()


def locked(what: str) -> HTTPException:
    """Locked means locked, for every role: a correction is a new revision or an addendum."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        f"{what} is locked: it cannot be changed or deleted. Make a new revision or an addendum.",
    )


def unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def not_found(msg: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)


def next_code(db: Session, model, prefix: str) -> str:
    """PREFIX-2026-0001, the next free number of the year."""
    year = today().year
    stem = f"{prefix}-{year}-"
    n = db.scalar(select(func.count()).select_from(model).where(model.code.like(stem + "%"))) or 0
    while True:
        n += 1
        code = f"{stem}{n:04d}"
        if not db.scalar(select(model.id).where(model.code == code)):
            return code
