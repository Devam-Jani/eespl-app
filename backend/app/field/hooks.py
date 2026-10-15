# ruff: noqa: E501  (the claim fields read better unwrapped)
"""The travel claim in the process chain (Settings > Process rules): the claim is ready on the 1st
(the person and their manager are told; the manager not approving in 3 days goes to the
director), the manager approved it (accounts approve; not in 5 days: the director), approved.
And the worker's sweep: the auto end of day, road km recalculated when OSRM is back, the claims
on the 1st, the retention."""

import logging
from datetime import date, datetime

from sqlalchemy import select

from app.field import service
from app.field.models import TrackingProfile, TravelClaim
from app.models import User
from app.process.engine import emit
from app.timefmt import IST

log = logging.getLogger("eespl.field")


def _data(db, c: TravelClaim) -> dict:
    u = db.get(User, c.user_id)
    p = db.get(TrackingProfile, c.user_id)
    return {
        "person": u.full_name, "person_id": str(c.user_id), "manager_id": str(p.manager_id) if p and p.manager_id else None,
        "month": c.month, "km": f"{c.km:,.1f}", "amount": f"₹{c.total:,.2f}", "flagged": c.flagged_days,
        "claim_id": c.id, "demo": "DEMO" if u.is_demo else "",
    }  # fmt: skip


def claim_ready(db, c: TravelClaim) -> None:
    emit(db, "travel_claim_ready", subject=f"claim:{c.id}", data=_data(db, c))


def manager_approved(db, c: TravelClaim, actor_id) -> None:
    emit(
        db, "claim_manager_approved", subject=f"claim:{c.id}", actor_id=actor_id, data=_data(db, c)
    )


def claim_approved(db, c: TravelClaim, actor_id) -> None:
    emit(db, "claim_approved", subject=f"claim:{c.id}", actor_id=actor_id, data=_data(db, c))


def previous_month(day: date) -> str:
    y, m = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return f"{y:04d}-{m:02d}"


def claims_on_the_first(db, at: datetime) -> int:
    """On the 1st (IST) last month's claim of every eligible person is made ready."""
    today = at.astimezone(IST).date()
    if today.day != 1:
        return 0
    month = previous_month(today)
    n = 0
    for p in db.scalars(
        select(TrackingProfile).where(
            TrackingProfile.reimbursable.is_(True), TrackingProfile.tracked.is_(True)
        )
    ):
        c = db.scalar(
            select(TravelClaim).where(TravelClaim.user_id == p.user_id, TravelClaim.month == month)
        )
        if c is not None and c.status != "draft":
            continue
        c = service.build_claim(db, p.user_id, month, ready=True)
        if c is not None and c.days:
            claim_ready(db, c)
            n += 1
    return n


_last_retention: date | None = None


def sweep() -> None:
    from app.db import SessionLocal  # noqa: PLC0415

    global _last_retention
    with SessionLocal() as db:
        at = service.now()
        ended = service.auto_end(db, at)
        fixed = service.recalc_estimated(db)
        ready = claims_on_the_first(db, at)
        today = at.astimezone(IST).date()
        kept = None
        if _last_retention != today:
            kept = service.retention(db, at)
            _last_retention = today
        db.commit()
        if ended or fixed or ready or (kept and kept["points"]):
            log.info(
                "field: %s days auto-ended, %s recalculated, %s claims ready, retention %s",
                ended,
                fixed,
                ready,
                kept,
            )
