"""EESPL -> Kylas: create each new lead once (ported from the loyalty app's
services/kylas_push_service.py: claim with SKIP LOCKED, backoff, search before re-create).

  save     the lead and its kylas_outbox row are written in ONE transaction (queue_lead).
           Saving never calls Kylas; the API answers at once.
  at once  a background task tries the push right after the response (push_now).
  retries  the worker (app.crm.worker) sends whatever is due: backoff 1 min, 5 min, 30 min,
           2 h, then every 6 h; after 8 tries the row is `failed` and the lead shows Retry.

EXACTLY ONCE. A row is claimed with FOR UPDATE SKIP LOCKED, so two senders never send the same
lead. A create whose fate is unknown (timeout, 5xx, 2xx without id) is never re-sent blindly:
the next attempt SEARCHES Kylas by phone for a lead carrying our lead code in the code custom
field, and adopts it if found. Only a complete search that proves it is absent lets it be
created again.

OFF. With KYLAS_ENABLED=false, no API key or no source id in Settings, a new lead is marked
`disabled` and nothing is queued or sent. Edits to a lead are not pushed (as in the loyalty app).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.crm.kylas_client import CreateResult, KylasClient, Outcome
from app.crm.models import KylasOutbox, Lead, LeadActivity
from app.masters.models import CompanyProfile
from app.models import User

logger = logging.getLogger("eespl.kylas")

#: wait after the Nth failed try: 1 min, 5 min, 30 min, 2 h, then every 6 h
BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
MAX_ATTEMPTS = 8
SEARCH_MAX_PAGES = 5
_ERROR_LIMIT = 500
OWNER_RULES = ("creator", "default")  # a later "by city/district" rule slots in resolve_owner


def now() -> datetime:
    return datetime.now(UTC)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[max(0, min(attempts - 1, len(BACKOFF_SECONDS) - 1))])


def profile(db: Session) -> CompanyProfile | None:
    return db.get(CompanyProfile, 1)


def enabled(db: Session) -> tuple[bool, str | None]:
    """(on, why not)."""
    if not settings.kylas_enabled:
        return False, "KYLAS_ENABLED is false"
    if settings.kylas_api_key is None or not settings.kylas_api_key.get_secret_value().strip():
        return False, "no Kylas API key in .env"
    p = profile(db)
    if p is None or not p.kylas_source_id:
        return False, "no Kylas source id in Settings"
    return True, None


# --- what to send --------------------------------------------------------------------------------


def split_name(full_name: str) -> tuple[str | None, str]:
    """(firstName, lastName) split on the first space; Kylas requires lastName (loyalty rule)."""
    parts = " ".join((full_name or "").split()).split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


def national_number(phone: str | None) -> str | None:
    """+91XXXXXXXXXX -> XXXXXXXXXX (what Kylas' multi-field search matches)."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def resolve_owner(db: Session, lead: Lead, p: CompanyProfile) -> int | None:
    """The Kylas owner by the company's owner rule.

    creator  the Kylas user of the EESPL user who entered the lead, else the default owner
    default  always the default owner
    (a "by city/district" rule would be added here as another branch)"""
    if p.kylas_owner_rule == "creator" and lead.created_by:
        user = db.get(User, lead.created_by)
        if user is not None and user.kylas_user_id:
            return int(user.kylas_user_id)
    return int(p.kylas_default_owner_id) if p.kylas_default_owner_id else None


def build_payload(lead: Lead, p: CompanyProfile, owner_id: int | None) -> dict:
    """The POST /v1/leads body (loyalty: build_lead_payload). Source only: Kylas puts the lead
    in its default lead pipeline itself."""
    first, last = split_name(lead.contact_name)
    body: dict = {"lastName": last}
    if first:
        body["firstName"] = first
    if lead.phone:
        body["phoneNumbers"] = [{"type": "MOBILE", "value": lead.phone, "primary": True}]
    if lead.email:
        body["emails"] = [{"type": "OFFICE", "value": lead.email, "primary": True}]
    if lead.company:
        body["companyName"] = lead.company
    if lead.city:
        body["city"] = lead.city
    if lead.state:
        body["state"] = lead.state
    if lead.requirement:
        body["requirementName"] = lead.requirement[:255]
    body["source"] = int(p.kylas_source_id)
    if owner_id is not None:
        body["ownerId"] = owner_id
    body["customFieldValues"] = {p.kylas_lead_code_field: lead.code}
    return body


# --- queueing ------------------------------------------------------------------------------------


def queue_lead(db: Session, lead: Lead) -> bool:
    """Inside the lead's own transaction. True when an outbox row was written."""
    on, _ = enabled(db)
    if not on:
        lead.kylas_sync_status = "disabled"
        return False
    lead.kylas_sync_status = "pending"
    db.add(KylasOutbox(lead_id=lead.id, status="pending", attempts=0, next_attempt_at=now()))
    return True


def retry(db: Session, lead: Lead) -> bool:
    """Retry a failed (or, now that Kylas is on, a disabled) lead: due again, attempts reset."""
    on, why = enabled(db)
    if not on:
        lead.kylas_sync_status = "disabled"
        lead.kylas_last_error = f"Kylas is off: {why}"
        return False
    if lead.kylas_lead_id:
        return False
    row = db.scalar(select(KylasOutbox).where(KylasOutbox.lead_id == lead.id))
    if row is None:
        row = KylasOutbox(lead_id=lead.id)
        db.add(row)
    # a create that may have landed is searched for first, even after a manual retry
    row.status = "unknown" if row.status == "unknown" else "pending"
    row.attempts = 0
    row.next_attempt_at = now()
    lead.kylas_sync_status = "pending"
    return True


def claim(db: Session, at: datetime, lead_id: int | None = None) -> KylasOutbox | None:
    """One due pending/unknown row, row-locked; rows another sender holds are skipped."""
    query = select(KylasOutbox).where(
        KylasOutbox.status.in_(("pending", "unknown")), KylasOutbox.next_attempt_at <= at
    )
    if lead_id is not None:
        query = query.where(KylasOutbox.lead_id == lead_id)
    query = query.order_by(KylasOutbox.next_attempt_at, KylasOutbox.id).limit(1)
    return db.scalars(query.with_for_update(skip_locked=True)).first()


# --- sending -------------------------------------------------------------------------------------


@dataclass
class PushReport:
    created: int = 0
    adopted: int = 0
    retrying: int = 0
    unknown: int = 0
    failed: int = 0
    disabled: int = 0

    def summary(self) -> str:
        return " ".join(f"{k}={v}" for k, v in vars(self).items())


def _activity(db: Session, lead: Lead, text: str) -> None:
    db.add(LeadActivity(lead_id=lead.id, type="kylas", text=text))


def _fail_or_wait(
    row: KylasOutbox, lead: Lead, error: str, at: datetime, report: PushReport, status: str
) -> None:
    row.last_error = lead.kylas_last_error = error[:_ERROR_LIMIT]
    if row.attempts >= MAX_ATTEMPTS:
        row.status, row.next_attempt_at, lead.kylas_sync_status = "failed", None, "failed"
        report.failed += 1
    else:
        row.status = status
        row.next_attempt_at = at + backoff(row.attempts)
        lead.kylas_sync_status = "pending"
        if status == "unknown":
            report.unknown += 1
        else:
            report.retrying += 1


def _done(row: KylasOutbox, lead: Lead, kylas_id: int, owner_id: int | None, at: datetime) -> None:
    row.status, row.next_attempt_at, row.last_error = "done", None, None
    lead.kylas_lead_id = kylas_id
    lead.kylas_owner_id = owner_id
    lead.kylas_sync_status = "synced"
    lead.kylas_synced_at = at
    lead.kylas_last_error = None
    lead.kylas_forecasting = "OPEN"


def _search_for(client: KylasClient, lead: Lead, field: str) -> tuple[str, dict | None, str | None]:
    """("found", match) / ("absent", None) / ("inconclusive", error) for our lead code."""
    phone = national_number(lead.phone)
    if not phone:
        return "absent", None, None  # nothing to search on; it can only be created again
    for page in range(SEARCH_MAX_PAGES):
        result = client.search_lead_by_phone(phone, page=page)
        if not result.ok:
            return "inconclusive", None, result.error
        for item in result.items:
            custom = item.get("customFieldValues") if isinstance(item, dict) else None
            if isinstance(custom, dict) and str(custom.get(field) or "").strip() == lead.code:
                return "found", item, None
        if result.last_page:
            return "absent", None, None
    return "inconclusive", None, f"search incomplete after {SEARCH_MAX_PAGES} pages"


def send(db: Session, row: KylasOutbox, client: KylasClient, report: PushReport) -> None:
    """Work one claimed row (search first when its last create may have landed). Commits."""
    at = now()
    lead = db.get(Lead, row.lead_id)
    on, why = enabled(db)
    if lead is None or lead.kylas_lead_id:
        row.status, row.next_attempt_at = "done", None
        db.commit()
        return
    if not on:
        row.status, row.next_attempt_at = "failed", None
        lead.kylas_sync_status = "disabled"
        lead.kylas_last_error = f"Kylas is off: {why}"
        report.disabled += 1
        db.commit()
        return
    p = profile(db)
    owner_id = resolve_owner(db, lead, p)
    row.attempts += 1

    if row.status == "unknown":
        verdict, match, error = _search_for(client, lead, p.kylas_lead_code_field)
        if verdict == "found":
            kylas_id = int(match["id"])
            _done(row, lead, kylas_id, match.get("ownerId") or owner_id, at)
            _activity(
                db,
                lead,
                f"Found in Kylas after a timeout (lead {kylas_id}); adopted, " "not created again",
            )
            report.adopted += 1
            logger.info("kylas push lead=%s adopted kylas_lead=%s", lead.id, kylas_id)
            db.commit()
            return
        if verdict == "inconclusive":
            _fail_or_wait(row, lead, f"search before re-create: {error}", at, report, "unknown")
            logger.info("kylas push lead=%s search inconclusive attempt=%s", lead.id, row.attempts)
            db.commit()
            return
        # proven absent: it never landed, so it is created now (once)

    result: CreateResult = client.create_lead(build_payload(lead, p, owner_id))
    if result.outcome is Outcome.CREATED:
        _done(row, lead, result.lead_id, owner_id, at)
        _activity(db, lead, f"Created in Kylas (lead {result.lead_id})")
        report.created += 1
    elif result.outcome is Outcome.PERMANENT:
        row.status, row.next_attempt_at = "failed", None
        row.last_error = lead.kylas_last_error = (result.error or "")[:_ERROR_LIMIT]
        lead.kylas_sync_status = "failed"
        report.failed += 1
    elif result.outcome is Outcome.UNKNOWN:
        _fail_or_wait(row, lead, result.error or "no answer", at, report, "unknown")
    else:  # RETRYABLE / NOT_CONFIGURED
        _fail_or_wait(row, lead, result.error or "not sent", at, report, "pending")
    # ids, attempt and outcome only: never the payload (phone) or a header (the key)
    logger.info(
        "kylas push lead=%s attempt=%s outcome=%s status=%s kylas_lead=%s",
        lead.id,
        row.attempts,
        result.outcome.value,
        result.status_code,
        result.lead_id,
    )
    db.commit()


def run_due(db: Session, client: KylasClient, limit: int = 100) -> PushReport:
    report = PushReport()
    for _ in range(limit):
        row = claim(db, now())
        if row is None:
            db.rollback()
            break
        send(db, row, client, report)
    return report


def push_now(lead_id: int) -> None:
    """The immediate attempt after the API response, in its own session. Never raises; on any
    problem the row is simply still due for the worker."""
    from app.crm.kylas_client import client
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            row = claim(db, now(), lead_id=lead_id)
            if row is None:
                db.rollback()
                return
            send(db, row, client(), PushReport())
    except Exception:  # noqa: BLE001
        logger.exception("kylas immediate push failed for lead=%s; left for the worker", lead_id)
