"""The process clock in the worker: timed events, escalations, the email outbox and the 9:00
summary."""

import logging

from app.db import SessionLocal
from app.process import engine

log = logging.getLogger("eespl.process")


def process_sweep() -> None:
    with SessionLocal() as db:
        out = engine.tick(db)
        db.commit()
    if any(out.values()):
        log.info("process: %s", out)
