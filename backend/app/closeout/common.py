"""Shared bits: the clock (tests replace it), codes, the lock rule and the client's billing role
lookups."""

from datetime import UTC, date, datetime, timedelta, timezone

from fastapi import HTTPException, status
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
    """PREFIX-2026-0001 by year, from the series' counter row (app.numbering): counting the rows
    let two requests take the same number. The model is kept for the callers."""
    from app.numbering import next_value  # noqa: PLC0415

    year = today().year
    return f"{prefix}-{year}-{next_value(db, prefix, str(year)):04d}"
