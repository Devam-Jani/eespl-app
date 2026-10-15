"""A won BOQ teaches the library: its workings are added as new evidence (place and date)."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("eespl.knowledge")


def _learn(db: Session, w) -> int:
    from app.knowledge import routes, service  # noqa: PLC0415

    try:
        with db.begin_nested():
            return service.learn(db, w, routes.place_of(db, w))
    except Exception:  # noqa: BLE001  (the win itself never fails on the library)
        log.exception("learning from working %s failed", w.id)
        return 0


def won_tender(db: Session, tender) -> int:
    from app.costing.models import RateWorking  # noqa: PLC0415

    w = db.scalar(
        select(RateWorking)
        .where(RateWorking.tender_id == tender.id)
        .order_by(RateWorking.rev_no.desc())
        .limit(1)
    )
    return _learn(db, w) if w is not None and w.groups else 0


def won_quotation(db: Session, q) -> int:
    from app.costing.models import RateWorking  # noqa: PLC0415

    w = db.scalar(select(RateWorking).where(RateWorking.quotation_id == q.id))
    return _learn(db, w) if w is not None and w.groups else 0
