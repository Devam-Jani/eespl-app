# ruff: noqa: E501  (endpoint texts read better unwrapped)
"""The process chain in the app: notifications with filters (mine to act, information,
escalated), "done" on a to-do, the director's escalated list, a site's Process tab, Settings >
Process rules and each person's channel per rule."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.db import DbSession
from app.execution.common import names, record
from app.material import service as material
from app.process import engine
from app.process.models import EMAIL_MODES, ProcessEvent, ProcessPreference, ProcessRule
from app.process.rules import ROLES
from app.timefmt import label

router = APIRouter(prefix="/api/process", tags=["process"])
RulesEdit = Annotated[str, Depends(require_permission("process.rules"))]


def _age_hours(dt: datetime | None) -> int | None:
    return max(0, int((datetime.now(UTC) - dt).total_seconds() // 3600)) if dt else None


def _note_out(db, n, who: dict) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "lines": n.body.split("\n") if n.body else [],
        "link": n.link,
        "site_id": n.site_id,
        "rule": n.rule_code,
        "kind": n.kind,
        "action": n.action_label,
        "needs_action": n.needs_action,
        "escalated": n.escalated,
        "note": n.note,
        "read": n.read_at is not None,
        "created_at": n.created_at,
        "created_label": label(n.created_at),
        "waiting_hours": _age_hours(n.created_at)
        if n.closed_at is None and n.needs_action
        else None,
        "closed_at": n.closed_at,
        "closed_label": label(n.closed_at) if n.closed_at else None,
        "closed_by": who.get(n.closed_by),
        "closed_reason": n.closed_reason,
        "email": n.email_status,
    }


@router.get("/notifications")
def notifications(
    db: DbSession, principal: CurrentPrincipal, filter: str = "all", limit: int = 100
) -> dict:
    """The bell's list: all, mine to act (open to-dos), information, escalated."""
    from app.portal.models import Notification  # noqa: PLC0415

    q = select(Notification).where(Notification.user_id == principal.user.id)
    if filter == "act":
        q = q.where(Notification.needs_action, Notification.closed_at.is_(None))
    elif filter == "info":
        q = q.where(Notification.needs_action.is_(False))
    elif filter == "escalated":
        q = q.where(Notification.escalated)
    rows = db.scalars(q.order_by(Notification.created_at.desc()).limit(min(limit, 300))).all()
    who = names(db, [n.closed_by for n in rows])
    base = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == principal.user.id)
    )
    counts = {
        "unread": db.scalar(base.where(Notification.read_at.is_(None))),
        "act": db.scalar(base.where(Notification.needs_action, Notification.closed_at.is_(None))),
        "escalated": db.scalar(
            base.where(Notification.escalated, Notification.closed_at.is_(None))
        ),
    }
    return jsonable_encoder({"items": [_note_out(db, n, who) for n in rows], "counts": counts})


class DoneIn(BaseModel):
    reason: str | None = Field(None, max_length=300)


@router.post("/notifications/{nid}/done")
def mark_done(
    nid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    body: DoneIn | None = None,
) -> dict:
    """Closed by hand: the to-do (and its escalations) close, with who and when. Doing the
    action in the app closes it by itself, so closing an action item by hand needs a short
    reason (it shows on the site's process timeline)."""
    from app.portal.models import Notification  # noqa: PLC0415

    n = db.get(Notification, nid)
    if n is None or n.user_id != principal.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if not n.needs_action or n.closed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing to close")
    reason = " ".join(((body.reason if body else None) or "").split())
    if len(reason) < 3:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Say briefly why '{n.action_label or 'the action'}' was not done in the app",
        )
    closed = engine.done(db, n, principal.user.id, reason)
    n.read_at = n.read_at or datetime.now(UTC)
    record(
        db,
        request,
        principal,
        "process.done",
        "notification",
        n.id,
        after={"rule": n.rule_code, "subject": n.subject, "closed": closed, "reason": reason},
    )
    db.commit()
    return {"closed": closed}


@router.get("/escalated")
def escalated(
    db: DbSession,
    _: Annotated[str, Depends(require_any_permission("process.escalations", "process.rules"))],
) -> list[dict]:
    """Every escalated item still open, across sites, oldest first (one row per item)."""
    from app.portal.models import Notification  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    rows = db.scalars(
        select(Notification)
        .where(Notification.escalated, Notification.closed_at.is_(None))
        .order_by(Notification.created_at)
    ).all()
    out, seen = [], set()
    rules = {r.code: r for r in db.scalars(select(ProcessRule))}
    for n in rows:
        key = (n.rule_code, n.subject, n.escalation_level)
        if key in seen:
            continue
        seen.add(key)
        first = db.scalar(
            select(Notification)
            .where(
                Notification.rule_code == n.rule_code,
                Notification.subject == n.subject,
                Notification.escalation_level == 0,
            )
            .order_by(Notification.created_at)
        )
        owners = names(
            db,
            [
                x.user_id
                for x in db.scalars(
                    select(Notification).where(
                        Notification.rule_code == n.rule_code,
                        Notification.subject == n.subject,
                        Notification.escalation_level == 0,
                        Notification.closed_at.is_(None),
                    )
                )
            ],
        )
        site = db.get(Site, n.site_id) if n.site_id else None
        out.append(
            {
                "id": n.id,
                "rule": n.rule_code,
                "step": f"{rules[n.rule_code].number:g}. {rules[n.rule_code].title}"
                if n.rule_code in rules
                else n.rule_code,
                "title": first.title if first else n.title,
                "site": f"{site.code} {site.name}" if site else None,
                "site_id": n.site_id,
                "waiting_on": ", ".join(owners.values()) or "—",
                "since": first.created_at if first else n.created_at,
                "since_label": label(first.created_at if first else n.created_at),
                "waiting_hours": _age_hours(first.created_at if first else n.created_at),
                "level": n.escalation_level,
                "link": n.link,
            }
        )
    return jsonable_encoder(out)


def _reasons(db, where, rule_code: str) -> list[dict]:
    from app.portal.models import Notification  # noqa: PLC0415

    rows = db.scalars(
        select(Notification)
        .where(where, Notification.rule_code == rule_code, Notification.closed_reason.is_not(None))
        .order_by(Notification.closed_at)
    ).all()
    who = names(db, [n.closed_by for n in rows])
    return [
        {"by": who.get(n.closed_by), "at": label(n.closed_at), "reason": n.closed_reason}
        for n in rows
    ]


def _pre_site_subjects(db, site) -> list[str]:
    from app.quotations.models import Quotation, QuotationFollowUp  # noqa: PLC0415

    quotes = db.execute(
        select(Quotation.id, Quotation.code, Quotation.lead_id).where(Quotation.site_id == site.id)
    ).all()
    out = [f"quotation:{code}" for _i, code, _l in quotes]
    out += [f"lead:{lead}" for _i, _c, lead in quotes if lead]
    if quotes:
        ids = [i for i, _c, _l in quotes]
        out += [
            f"followup:{f}"
            for f in db.scalars(
                select(QuotationFollowUp.id).where(QuotationFollowUp.quotation_id.in_(ids))
            )
        ]
    if site.tender_id:
        out.append(f"tender:{site.tender_id}")
    return out


@router.get("/sites/{site_id}/timeline")
def timeline(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("site.view"))],
) -> dict:
    """The chain on one site: each step, who did it and when, the current step, how long it has
    been waiting. Planning sees every site without phoning anyone."""
    from app.portal.models import Notification  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    site = db.get(Site, site_id)
    if site is None or not material.covers_site(db, scope, principal, site.id, site.created_by):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    engine.ensure_rules(db)
    rules = db.scalars(select(ProcessRule).order_by(ProcessRule.number)).all()
    # the steps before the job had a site (enquiry, quotation, follow-ups, tender) by subject
    subjects = _pre_site_subjects(db, site)

    def on_site(model):
        return or_(
            model.site_id == site.id, and_(model.site_id.is_(None), model.subject.in_(subjects))
        )

    steps = []
    current = None
    for r in rules:
        events = db.scalars(
            select(ProcessEvent)
            .where(on_site(ProcessEvent), ProcessEvent.type == r.event)
            .order_by(ProcessEvent.at)
        ).all()
        open_items = db.scalars(
            select(Notification)
            .where(
                on_site(Notification),
                Notification.rule_code == r.code,
                Notification.needs_action,
                Notification.closed_at.is_(None),
                Notification.escalation_level == 0,
            )
            .order_by(Notification.created_at)
        ).all()
        who = names(db, [e.actor_id for e in events] + [n.user_id for n in open_items])
        last = events[-1] if events else None
        state = "waiting" if open_items else ("done" if events else "not_reached")
        if state == "waiting" and current is None:
            current = r.code
        steps.append(
            {
                "code": r.code,
                "number": float(r.number),
                "title": r.title,
                "state": state,
                "times": len(events),
                "last_by": who.get(last.actor_id)
                if last and last.actor_id
                else ("the app" if last else None),
                "last_at": last.at if last else None,
                "last_label": label(last.at) if last else None,
                "waiting_on": ", ".join(dict.fromkeys(who.get(n.user_id, "?") for n in open_items))
                or None,
                "waiting_hours": _age_hours(open_items[0].created_at) if open_items else None,
                "escalated": bool(
                    db.scalar(
                        select(func.count())
                        .select_from(Notification)
                        .where(
                            on_site(Notification),
                            Notification.rule_code == r.code,
                            Notification.escalated,
                            Notification.closed_at.is_(None),
                        )
                    )
                ),
                # closed by hand without the action: who, when and why
                "reasons": _reasons(db, on_site(Notification), r.code),
            }
        )
    if current is None:
        done = [s for s in steps if s["state"] == "done"]
        current = done[-1]["code"] if done else None
    return jsonable_encoder(
        {"site": f"{site.code} {site.name}", "current": current, "steps": steps}
    )


# --- Settings > Process rules ---------------------------------------------------------------------


def _rule_out(r: ProcessRule) -> dict:
    return {
        "code": r.code,
        "number": float(r.number),
        "event": r.event,
        "title": r.title,
        "recipients": r.recipients,
        "link": r.link,
        "closed_by": r.closed_by,
        "escalations": r.escalations,
        "info_only": all(x.get("info") for x in r.recipients),
        "email": r.email,
        "is_active": r.is_active,
    }


@router.get("/rules")
def rules(db: DbSession, _: CurrentPrincipal) -> dict:
    engine.ensure_rules(db)
    db.commit()
    return {
        "rules": [
            _rule_out(r) for r in db.scalars(select(ProcessRule).order_by(ProcessRule.number))
        ],
        "roles": list(ROLES),
    }


class Recipient(BaseModel):
    role: str
    message: str = Field(min_length=3, max_length=300)
    action: str | None = Field(None, max_length=60)
    info: bool = False
    when: str | None = None
    link: str | None = Field(None, max_length=300)
    closed_by: list[str] | None = None


class Escalation(BaseModel):
    after_hours: float = Field(gt=0, le=24 * 60)
    to: list[str] = Field(min_length=1)


class RuleIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    recipients: list[Recipient] | None = None
    escalations: list[Escalation] | None = None
    email: bool | None = None
    is_active: bool | None = None


@router.put("/rules/{code}")
def edit_rule(
    code: str,
    body: RuleIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: RulesEdit,
) -> dict:
    """Edit, switch off, add a recipient, change the escalation; every change logged."""
    r = db.get(ProcessRule, code)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    before = _rule_out(r)
    data = body.model_dump(exclude_unset=True)
    bad = {x["role"] for x in data.get("recipients") or []} | {
        t for e in data.get("escalations") or [] for t in e["to"]
    }
    if bad - set(ROLES):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown role: {', '.join(sorted(bad - set(ROLES)))}",
        )
    if "recipients" in data:
        r.recipients = [
            {k: v for k, v in x.items() if v not in (None, False) or k == "info"}
            for x in data["recipients"]
        ]
    if "escalations" in data:
        if data["escalations"] and all(x.get("info") for x in r.recipients):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "An information-only rule never escalates"
            )
        r.escalations = data["escalations"]
    for k in ("title", "email", "is_active"):
        if data.get(k) is not None:
            setattr(r, k, data[k])
    r.updated_by = principal.user.id
    record(
        db,
        request,
        principal,
        "process.rule",
        "process_rule",
        code,
        before=before,
        after=_rule_out(r),
    )
    db.commit()
    return _rule_out(r)


class SettingsIn(BaseModel):
    default_users: dict[str, uuid.UUID | None] | None = None
    wastage: dict[str, dict[str, float]] | None = None
    summary_hour: int | None = Field(None, ge=0, le=23)
    stage_bill_days: int | None = Field(None, ge=1, le=60)


def _settings_out(db) -> dict:
    s = engine.settings(db)
    stage = db.get(ProcessRule, "stage_done")
    days = (
        round(float(stage.escalations[0]["after_hours"]) / 24)
        if stage and stage.escalations
        else None
    )
    return jsonable_encoder(
        {
            "default_users": s.default_users or {},
            "wastage": s.wastage or {},
            "summary_hour": s.summary_hour,
            "stage_bill_days": days,
        }
    )


@router.get("/settings")
def get_settings(db: DbSession, _: CurrentPrincipal) -> dict:
    engine.ensure_rules(db)
    out = _settings_out(db)
    db.commit()
    return out


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: RulesEdit
) -> dict:
    """The default user per role, the wastage per application and the stage-bill limit (days),
    so Mr. Sunil can change them."""
    engine.ensure_rules(db)
    s = engine.settings(db)
    before = _settings_out(db)
    if body.default_users is not None:
        s.default_users = {k: str(v) for k, v in body.default_users.items() if v and k in ROLES}
    if body.wastage is not None:
        for k, w in body.wastage.items():
            if not (0 <= w.get("min", 0) <= w.get("max", 0) <= 100):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, f"Wastage for {k}: 0 <= min <= max <= 100"
                )
        s.wastage = body.wastage
    if body.summary_hour is not None:
        s.summary_hour = body.summary_hour
    if body.stage_bill_days is not None:
        stage = db.get(ProcessRule, "stage_done")
        stage.escalations = [
            {
                **(stage.escalations[0] if stage.escalations else {"to": ["director"]}),
                "after_hours": body.stage_bill_days * 24,
            }
        ]
    record(
        db,
        request,
        principal,
        "process.settings",
        "process_settings",
        1,
        before=before,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return _settings_out(db)


# --- my channels per rule -------------------------------------------------------------------------


@router.get("/preferences")
def preferences(db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    engine.ensure_rules(db)
    mine = {
        p.rule_code: p.mode
        for p in db.scalars(
            select(ProcessPreference).where(ProcessPreference.user_id == principal.user.id)
        )
    }
    out = []
    for r in db.scalars(select(ProcessRule).order_by(ProcessRule.number)):
        info = all(x.get("info") for x in r.recipients)
        default = "app" if info or not r.email else "email"
        out.append(
            {
                "code": r.code,
                "number": float(r.number),
                "title": r.title,
                "mode": mine.get(r.code, default),
                "default": default,
            }
        )
    db.commit()
    return out


class PrefIn(BaseModel):
    modes: dict[str, str]


@router.put("/preferences")
def set_preferences(body: PrefIn, db: DbSession, principal: CurrentPrincipal) -> dict:
    """App only, app and email, or the 9:00 daily summary; escalations always email."""
    for code, mode in body.modes.items():
        if mode not in EMAIL_MODES or db.get(ProcessRule, code) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{code}: {mode}?")
        p = db.get(ProcessPreference, (principal.user.id, code))
        if p is None:
            db.add(ProcessPreference(user_id=principal.user.id, rule_code=code, mode=mode))
        else:
            p.mode = mode
    db.commit()
    return {"saved": len(body.modes)}


@router.post("/tick")
def run_tick(db: DbSession, _: RulesEdit) -> dict[str, Any]:
    """Run the clock now (the worker does it every few minutes)."""
    out = engine.tick(db)
    db.commit()
    return out
