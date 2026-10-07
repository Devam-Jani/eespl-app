"""The Kylas worker (compose service `worker`): every minute it sends queued leads; every
5 minutes it polls lead and deal outcomes. While Kylas is off it sends and polls nothing.

    python -m app.crm.worker          # loop
    python -m app.crm.worker --once   # one push sweep and one poll, then exit
"""

import argparse
import logging
import signal
import time

from app.crm import kylas_client, kylas_poll, kylas_push
from app.db import SessionLocal

PUSH_EVERY = 60
POLL_EVERY = 300

logger = logging.getLogger("eespl.kylas")
_stop = False


def _request_stop(signum, _frame) -> None:
    global _stop
    _stop = True


def push_sweep() -> None:
    with SessionLocal() as db:
        on, why = kylas_push.enabled(db)
        if not on:
            return
        report = kylas_push.run_due(db, kylas_client.client())
        if any(vars(report).values()):
            logger.info("kylas push: %s", report.summary())


def poll_sweep() -> None:
    with SessionLocal() as db:
        report = kylas_poll.run(db, kylas_client.client())
        logger.info("kylas poll: %s", report.summary() or "nothing changed")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.crm.worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    last_poll = 0.0
    while True:
        for job in (push_sweep,) + (
            (poll_sweep,) if time.time() - last_poll >= POLL_EVERY or args.once else ()
        ):
            try:
                job()
            except Exception:  # noqa: BLE001  one bad sweep must not stop the worker
                logger.exception("kylas %s failed", job.__name__)
            if job is poll_sweep:
                last_poll = time.time()
        if args.once or _stop:
            return
        for _ in range(PUSH_EVERY):
            if _stop:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
