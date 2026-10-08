"""The scheduled analytics jobs, run by the worker process (app.worker):

- every hour: check the alert rules;
- every night after 1 am IST (and when the tables have never been built): rebuild the summary
  tables and today's progress / KPI snapshots;
- Mondays from 8 am IST: file the weekly management summary (once per week).
"""

import logging
from datetime import datetime, timedelta

from app.analytics import alerts, reports, summary
from app.analytics.common import now
from app.db import SessionLocal
from app.execution.service import IST

logger = logging.getLogger("eespl.analytics")
NIGHTLY_HOUR = 1
WEEKLY_HOUR = 8


def due(at: datetime) -> list[str]:
    """Which jobs are due at `at` (from what the settings row says ran last)."""
    with SessionLocal() as db:
        s = summary.settings(db)
        refreshed, alerted = s.refreshed_at, s.alerts_run_at
        weekly_on = s.weekly_report
    local = at.astimezone(IST)
    jobs = []
    if refreshed is None or (
        local.hour >= NIGHTLY_HOUR and refreshed.astimezone(IST).date() < local.date()
    ):
        jobs.append("refresh")
    if alerted is None or at - alerted >= timedelta(hours=1):
        jobs.append("alerts")
    if weekly_on and local.weekday() == 0 and local.hour >= WEEKLY_HOUR:
        jobs.append("weekly")
    return jobs


def run_due(at: datetime | None = None) -> None:
    at = at or now()
    for job in due(at):
        try:
            with SessionLocal() as db:
                if job == "refresh":
                    logger.info("analytics: summary tables as of %s", summary.refresh(db))
                elif job == "alerts":
                    raised = alerts.run(db, at)
                    logger.info(
                        "analytics: alerts %s", {k: v for k, v in raised.items() if v} or "none new"
                    )
                elif job == "weekly" and reports.weekly(db, at):
                    logger.info("analytics: weekly management summary filed")
        except Exception:  # noqa: BLE001  one bad job must not stop the worker
            logger.exception("analytics %s failed", job)
