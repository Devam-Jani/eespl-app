"""Quotation housekeeping for the worker: quotations past their validity expire (their
follow-ups stop). Runs at most once an hour; the overdue follow-up alerts come from the analytics
alert run."""

import logging
import time

from app.db import SessionLocal
from app.quotations import service

EVERY = 3600
_last = 0.0


def expire_sweep() -> None:
    global _last
    if time.time() - _last < EVERY:
        return
    _last = time.time()
    import app.main  # noqa: F401, PLC0415  (every model, for the foreign keys)

    with SessionLocal() as db:
        n = service.expire_due(db)
        db.commit()
    if n:
        logging.getLogger("eespl.quotations").info("%d quotation(s) expired", n)
