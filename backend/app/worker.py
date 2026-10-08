"""The background worker (compose service `worker`): the Kylas push / poll sweeps and the scheduled
analytics jobs (alerts every hour, summary tables nightly, the Monday management summary).

    python -m app.worker          # loop
    python -m app.worker --once   # one round of everything that is due, then exit
"""

import argparse
import logging
import signal
import time

from app.analytics import worker as analytics
from app.crm import worker as kylas

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
        jobs = [kylas.push_sweep, analytics.run_due]
        if time.time() - last_poll >= kylas.POLL_EVERY or args.once:
            jobs.append(kylas.poll_sweep)
        for job in jobs:
            try:
                job()
            except Exception:  # noqa: BLE001  one bad job must not stop the worker
                logging.getLogger("eespl.worker").exception("%s failed", job.__name__)
            if job is kylas.poll_sweep:
                last_poll = time.time()
        if args.once or _stop:
            return
        for _ in range(TICK):
            if _stop:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
