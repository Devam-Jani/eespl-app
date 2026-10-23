# ruff: noqa: E501
"""The issue log book's scheduled jobs, run by the worker (app.worker):

- every night after 2 am IST: write the open bugs to MEDIA_DIR/issues/open.md (no personal data),
  the file the developer agent reads (the GitHub workflow commits it as docs/issues/open.md);
- Mondays from 8 am IST: the week's summary in the bell of those who keep the log book (once per
  week).

    python -m app.cli issues-open-md [--out PATH]   # write it now
    python -m app.cli issues-released <commit>...   # a deploy: its fixes are released
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.execution.service import IST
from app.issues import service as svc

log = logging.getLogger("eespl.issues")
NIGHTLY_HOUR = 2
WEEKLY_HOUR = 8
WEEKLY_KIND = "issue_weekly"


def open_md_path() -> Path:
    return Path(settings.media_dir) / "issues" / "open.md"


def write_open_md(db: Session, out: Path | None = None) -> Path:
    out = out or open_md_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svc.open_md(db), encoding="utf-8")
    return out


def weekly_notice(db: Session, at: datetime) -> int:
    """The week in the log book, in the bell of the director, the office admin and the super admin
    (once per week). Returns how many were told (0 when it was already sent)."""
    from app.portal import service as portal  # noqa: PLC0415
    from app.portal.models import Notification  # noqa: PLC0415
    from app.team.service import holders  # noqa: PLC0415

    local = at.astimezone(IST)
    week_start = datetime.combine(local.date() - timedelta(days=local.weekday()), datetime.min.time(), IST)
    if db.scalar(select(Notification.id).where(Notification.kind == WEEKLY_KIND, Notification.created_at >= week_start).limit(1)):
        return 0
    w = svc.weekly(db, at)
    title = (
        f"Issue log, the week to {local:%d %b}: {w['new_issues']} new, {w['times_happened']} times something went wrong, "
        f"{w['fixed']} fixed, {w['released']} released, {w['open_bugs']} open bugs"
    )
    n = portal.notify(db, holders(db, "issuelog.view"), WEEKLY_KIND, title, "/settings/issue-log")
    db.commit()
    return n


def sweep(at: datetime | None = None) -> None:
    at = at or datetime.now(UTC)
    local = at.astimezone(IST)
    path = open_md_path()
    with SessionLocal() as db:
        written = datetime.fromtimestamp(path.stat().st_mtime, UTC).astimezone(IST).date() if path.exists() else None
        if local.hour >= NIGHTLY_HOUR and written != local.date():
            write_open_md(db, path)
            log.info("issues: open.md written")
        if local.weekday() == 0 and local.hour >= WEEKLY_HOUR and weekly_notice(db, at):
            log.info("issues: the weekly summary sent")
