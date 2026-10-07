"""Kylas -> EESPL: read-only polls (no webhooks). Nothing here writes to Kylas.

Lead poll (loyalty: lead_guardrail_service.classify). For each synced lead that is not closed
here, GET /leads/{id}:
  converted to a deal (conversionDetails has a DEAL, or CLOSED_WON)
                         -> log "converted to deal in Kylas" once; status unchanged ('won'
                            only comes from the deal rule)
  closed (CLOSED_LOST / CLOSED_UNQUALIFIED) with a junk reason -> 'junk'
  CLOSED_LOST, or CLOSED_UNQUALIFIED for another reason        -> 'lost'
  OPEN                   -> nothing
Each change is a 'kylas' activity on the lead.

Deal poll (loyalty: kylas_deal_reward_service.run_sweep), only when the deal pipeline and the
won stage are set. Deals are read newest-updated first down to the cursor minus a 10-minute
overlap (clock skew never drops one); each candidate is fetched with GET /deals/{id}. A deal at
the won stage of that pipeline whose convertedLeads[].id is one of our kylas_lead_ids makes
that lead 'won'. Kylas drops our lead-code field on conversion, hence the match by lead id.
Re-reading a deal is harmless: a lead already won is left alone. Never creates a site.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crm.kylas_client import KylasClient
from app.crm.kylas_push import enabled, now, profile
from app.crm.models import CLOSED_STATUSES, KylasCursor, Lead, LeadActivity

logger = logging.getLogger("eespl.kylas")

CURSOR = "deals"
CURSOR_OVERLAP = timedelta(minutes=10)
MAX_SEARCH_PAGES = 20
LEADS_PER_SWEEP = 300


def _norm(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def _id(value) -> int | None:
    if isinstance(value, dict):
        value = value.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if len(text) > 5 and text[-5] in "+-" and text[-4:].isdigit():
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _note(db: Session, lead: Lead, text: str) -> None:
    db.add(LeadActivity(lead_id=lead.id, type="kylas", text=text))


# --- leads ---------------------------------------------------------------------------------------


def classify(kylas_lead: dict, junk_reasons) -> tuple[str | None, str | None]:
    """(what happened, reason): 'converted' | 'junk' | 'lost' | None (open)."""
    stage = str(kylas_lead.get("forecastingType") or "").strip().upper()
    reason = kylas_lead.get("pipelineStageReason")
    reason = " ".join(str(reason).split())[:200] if reason else None
    converted = any(
        isinstance(e, dict) and str(e.get("entityType") or "").upper() == "DEAL"
        for e in kylas_lead.get("conversionDetails") or []
    )
    if converted or stage == "CLOSED_WON":
        return "converted", reason
    if stage in ("CLOSED_LOST", "CLOSED_UNQUALIFIED"):
        if reason and _norm(reason) in {_norm(r) for r in junk_reasons or []}:
            return "junk", reason
        return "lost", reason
    return None, reason


@dataclass
class PollReport:
    leads_checked: int = 0
    converted: int = 0
    lost: int = 0
    junk: int = 0
    deals_seen: int = 0
    won: int = 0
    failed: int = 0
    skipped: str | None = None

    def summary(self) -> str:
        return " ".join(f"{k}={v}" for k, v in vars(self).items() if v not in (None, 0))


def poll_leads(db: Session, client: KylasClient, report: PollReport) -> None:
    p = profile(db)
    leads = list(
        db.scalars(
            select(Lead)
            .where(Lead.kylas_lead_id.is_not(None), Lead.status.not_in(CLOSED_STATUSES))
            .order_by(Lead.kylas_synced_at.nulls_first(), Lead.id)
            .limit(LEADS_PER_SWEEP)
        )
    )
    for lead in leads:
        result = client.get_lead(lead.kylas_lead_id)
        report.leads_checked += 1
        if not result.ok or not isinstance(result.body, dict):
            report.failed += int(not result.ok)
            continue
        body = result.body
        lead.kylas_forecasting = str(body.get("forecastingType") or "")[:30] or None
        outcome, reason = classify(body, p.kylas_junk_reasons if p else [])
        if outcome == "converted" and lead.kylas_converted_at is None:
            lead.kylas_converted_at = now()
            _note(db, lead, "Converted to a deal in Kylas")
            report.converted += 1
        elif outcome in ("lost", "junk") and lead.status != outcome:
            before = lead.status
            lead.status = outcome
            _note(
                db,
                lead,
                f"Kylas closed the lead ({body.get('forecastingType')}"
                f"{', ' + reason if reason else ''}): {before} -> {outcome}",
            )
            setattr(report, outcome, getattr(report, outcome) + 1)
    db.commit()


# --- deals ---------------------------------------------------------------------------------------


def _cursor(db: Session) -> KylasCursor:
    cursor = db.get(KylasCursor, CURSOR)
    if cursor is None:
        cursor = KylasCursor(name=CURSOR, last_updated_at=None, pending_ids=[])
        db.add(cursor)
        db.flush()
    return cursor


def poll_deals(
    db: Session, client: KylasClient, report: PollReport, at: datetime | None = None
) -> None:
    p = profile(db)
    if not p or not p.kylas_deal_pipeline_id or not p.kylas_won_stage_id:
        report.skipped = "deal poll off: no pipeline / won stage in Settings"
        return
    ours = {
        int(k): i
        for k, i in db.execute(
            select(Lead.kylas_lead_id, Lead.id).where(Lead.kylas_lead_id.is_not(None))
        )
    }
    if not ours:
        return  # nothing of ours is in Kylas: no call at all
    at = at or now()
    cursor = _cursor(db)
    since = cursor.last_updated_at or (at - timedelta(days=1))
    floor = since - CURSOR_OVERLAP
    candidates: list[int] = []
    newest: datetime | None = None
    reached = search_failed = False
    for page in range(MAX_SEARCH_PAGES):
        result = client.search_deals(page=page)
        if not result.ok:
            search_failed = True
            logger.warning("kylas deal search failed: %s", result.error)
            break
        for item in result.items:
            if not isinstance(item, dict):
                continue
            updated = parse_time(item.get("updatedAt"))
            if updated is not None and updated < floor:
                reached = True
                break
            if updated is not None and (newest is None or updated > newest):
                newest = updated
            deal_id = _id(item.get("id"))
            if deal_id is None:
                continue
            pipeline = _id(item.get("pipeline"))
            if pipeline is not None and pipeline != int(p.kylas_deal_pipeline_id):
                continue
            converted = item.get("convertedLeads")
            if isinstance(converted, list) and not any(_id(c) in ours for c in converted):
                continue
            candidates.append(deal_id)
        if reached or result.last_page:
            reached = True
            break

    failed: list[int] = []
    for deal_id in dict.fromkeys(candidates + [int(d) for d in cursor.pending_ids or []]):
        fetched = client.get_deal(deal_id)
        if not fetched.ok:
            failed.append(deal_id)
            report.failed += 1
            continue
        deal = fetched.body
        if not isinstance(deal, dict):
            continue  # deleted in Kylas
        report.deals_seen += 1
        won = _id(deal.get("pipeline")) == int(p.kylas_deal_pipeline_id) and _id(
            deal.get("pipelineStage")
        ) == int(p.kylas_won_stage_id)
        if not won:
            continue
        for kylas_lead_id in sorted({_id(c) for c in deal.get("convertedLeads") or []} - {None}):
            if kylas_lead_id not in ours:
                continue
            lead = db.get(Lead, ours[kylas_lead_id])
            if lead.status == "won" and lead.kylas_deal_id == deal_id:
                continue  # seen in an earlier sweep (the cursor overlap re-reads it)
            before = lead.status
            lead.status, lead.kylas_deal_id, lead.kylas_won_at = "won", deal_id, at
            _note(
                db,
                lead,
                f"Deal {deal_id} is at the won stage in Kylas: {before} -> won"
                + (" (confirm on the tender)" if lead.tender_id else ""),
            )
            report.won += 1
    cursor = _cursor(db)
    if reached and not search_failed:
        if newest is not None and (
            cursor.last_updated_at is None or newest > cursor.last_updated_at
        ):
            cursor.last_updated_at = newest
        elif cursor.last_updated_at is None:
            cursor.last_updated_at = since
    cursor.pending_ids = sorted(set(failed))
    db.commit()


def run(db: Session, client: KylasClient) -> PollReport:
    report = PollReport()
    on, why = enabled(db)
    if not on or not client.is_configured:
        report.skipped = why or "no Kylas API key"
        return report
    poll_leads(db, client, report)
    poll_deals(db, client, report)
    return report
