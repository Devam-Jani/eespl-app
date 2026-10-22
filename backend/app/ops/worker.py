"""The worker's own round: its heartbeat (read by the health page) and, once an hour, the check
for a night without a backup."""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import SessionLocal
from app.ops import service

IST = ZoneInfo("Asia/Kolkata")
_last_check = 0.0
CHECK_EVERY = 3600


def worker_round() -> None:
    global _last_check
    with SessionLocal() as db:
        service.heartbeat(db)
        if settings.training_mode:
            training_night(db)
            return
        if time.time() - _last_check >= CHECK_EVERY:
            _last_check = time.time()
            service.missed_backup_sweep(db)


def training_night(db, now: datetime | None = None) -> bool:
    """The training company is rebuilt every night at 03:30 (once a day)."""
    now = now or datetime.now(IST)
    last = service.get(db, "training")
    done_today = last is not None and last.at.astimezone(IST).date() == now.date()
    if done_today or (now.hour, now.minute) < (3, 30):
        return False
    from app.ops import training  # noqa: PLC0415

    training.reset()
    return True
