"""The background worker (compose service `worker`): the Kylas push / poll sweeps, the scheduled
analytics jobs (alerts every hour, summary tables nightly, the Monday management summary) and
the process clock (escalations, emails, the daily summary) every minute.

    python -m app.worker          # loop
    python -m app.worker --once   # one round of everything that is due, then exit
"""

import argparse
import logging
import signal
import time

from app.analytics import worker as analytics
from app.config import settings
from app.crm import worker as kylas
from app.field import hooks as field
from app.ops import worker as ops
from app.process import worker as process
from app.quotations import worker as quotations
from app.takeoff import pipeline as takeoff

TICK = 60
_stop = False


def _request_stop(signum, _frame) -> None:
    global _stop
    _stop = True


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    last_poll = 0.0
    while True:
        jobs = [
            ops.worker_round,
            kylas.push_sweep,
            analytics.run_due,
            quotations.expire_sweep,
            process.process_sweep,
        ]
        jobs.append(takeoff.sweep)  # AutoCAD drawings queued to be read
        jobs.append(field.sweep)  # auto end of day, road km when OSRM is back, claims, retention
        if time.time() - last_poll >= kylas.POLL_EVERY or args.once:
            jobs.append(kylas.poll_sweep)
        if settings.training_mode:  # the training company: its heartbeat, nightly rebuild, drawings
            jobs = [ops.worker_round, takeoff.sweep]
        for job in jobs:
            try:
                job()
            except Exception:  # noqa: BLE001  one bad job must not stop the worker
                logging.getLogger("eespl.worker").exception("%s failed", job.__name__)
            if job is kylas.poll_sweep:
                last_poll = time.time()
        if args.once or _stop:
            return
        for i in range(TICK):
            if _stop:
                return
            time.sleep(1)
            if i % 2 == 1:  # a drawing someone just asked to read starts within two seconds
                try:
                    takeoff.sweep()
                except Exception:  # noqa: BLE001
                    logging.getLogger("eespl.worker").exception("drawing read failed")


if __name__ == "__main__":
    main()
