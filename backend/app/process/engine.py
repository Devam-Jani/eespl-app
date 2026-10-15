# ruff: noqa: E501  (queries read better unwrapped)
"""One event layer. Every step of the chain writes a process event; a rule turns it into one
notification per person (never twice for a retried event), which is also the person's to-do until
the action is done; the escalation runs on a clock and stops the moment the to-do closes. Email
goes to our own staff only, from a background job, and never blocks the step that caused it."""

import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.rbac import effective_permissions
from app.models import Role, User, UserRole
from app.process.models import ProcessEvent, ProcessPreference, ProcessRule, ProcessSettings
from app.process.rules import DEFAULT_RULES, DEFAULT_WASTAGE
from app.timefmt import IST, label

log = logging.getLogger(__name__)
SITE_ROLES = {"planning", "billing", "accounts", "store_purchase", "estimator"}
SUBJECT_MAX = 80
RULE_TEXT = {r["code"]: r for r in DEFAULT_RULES}  # short subject and place reference per rule
DEMO_WORD = re.compile(r"\bDEMO\b")


def now() -> datetime:
    return datetime.now(UTC)


# --- rules and settings --------------------------------------------------------------------------


def ensure_rules(db: Session) -> None:
    """The seeded chain, added once (edits made in Settings > Process rules are kept)."""
    have = set(db.scalars(select(ProcessRule.code)))
    for r in DEFAULT_RULES:
        if r["code"] in have:
            continue
        info_only = all(x.get("info") for x in r["recipients"])
        db.add(
            ProcessRule(
                code=r["code"],
                number=r["number"],
                event=r["event"],
                title=r["title"],
                recipients=r["recipients"],
                link=r.get("link"),
                closed_by=r.get("closed_by", []),
                escalations=[] if info_only else r.get("escalations", []),
                email=not info_only,
            )
        )
    db.flush()


def settings(db: Session) -> ProcessSettings:
    s = db.get(ProcessSettings, 1)
    if s is None:
        s = ProcessSettings(id=1, default_users={}, wastage=DEFAULT_WASTAGE)
        db.add(s)
        db.flush()
    if not s.wastage:
        s.wastage = DEFAULT_WASTAGE
    return s


def wastage_for(db: Session, place: str | None) -> tuple[str, dict] | None:
    """The application a place is (raft, footing...) from its name or kind, with its wastage."""
    text = (place or "").lower()
    for app_name, w in (settings(db).wastage or {}).items():
        if app_name.lower() in text:
            return app_name, w
    return None


# --- recipients ----------------------------------------------------------------------------------


def _role_holders(db: Session, code: str) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == code, User.is_active)
            .order_by(User.created_at)
        )
    )


def _default(db: Session, role: str) -> uuid.UUID | None:
    uid = (settings(db).default_users or {}).get(role)
    if uid:
        try:
            u = db.get(User, uuid.UUID(str(uid)))
        except ValueError:
            u = None
        if u is not None and u.is_active:
            return u.id
    return None


def resolve(db: Session, role: str, ev: ProcessEvent) -> tuple[list[uuid.UUID], str | None]:
    """Who holds the role for this event's site; the role's default user (or, for planning, the
    office admin) when nobody does, flagged "no one assigned"."""
    from app.sites.models import Site, SiteMember  # noqa: PLC0415

    data = ev.data or {}
    site = db.get(Site, ev.site_id) if ev.site_id else None
    members = (
        db.execute(
            select(SiteMember.user_id, SiteMember.role_on_site).where(SiteMember.site_id == site.id)
        ).all()
        if site
        else []
    )
    found: list = []
    if role == "author":
        found = [data.get("author_id") or ev.actor_id]
    elif role == "person":  # the person the event is about (their own travel claim)
        found = [data.get("person_id")]
    elif role == "manager":  # that person's manager (field tracking profile)
        found = [data.get("manager_id")]
    elif role == "director":
        found = _role_holders(db, "director") or _role_holders(db, "super_admin")
    elif role == "office_admin":
        found = _role_holders(db, "office_admin")
    elif role == "salesperson":
        found = [u for u, r in members if r == "sales"] or [data.get("salesperson_id")]
    elif role == "site_engineer":
        found = (
            [site.site_incharge_id]
            if site and site.site_incharge_id
            else [u for u, r in members if r == "incharge"]
        )
    elif role == "supervisor":
        found = [u for u, r in members if r == "supervisor"]
    elif role in SITE_ROLES:
        holders = set(_role_holders(db, role))
        found = [u for u, _r in members if u in holders]
        if not found and not site:
            found = []
    found = [uuid.UUID(str(u)) for u in dict.fromkeys(found) if u]
    if found:
        return found, None
    default = _default(db, role)
    on_site = role in ("salesperson", "site_engineer", "supervisor")
    if default:
        # office roles are rarely on a site: their default user is the normal case, not a gap
        return [
            default
        ], "no one assigned on this site: sent to the default user" if on_site else None
    if role == "planning":
        return _role_holders(
            db, "office_admin"
        ), "no planning user assigned: sent to the office admin"
    if role in SITE_ROLES:
        return _role_holders(db, role), None
    if on_site:
        fallback = {
            "salesperson": "sales",
            "site_engineer": "site_engineer",
            "supervisor": "site_supervisor",
        }.get(role, role)
        return _role_holders(db, fallback), "no one assigned on this site"
    return [], None


# --- messages ------------------------------------------------------------------------------------


class _Fields(dict):
    def __missing__(self, key):
        return "—"


def perms_of(db: Session, user: User) -> dict[str, str]:
    from app.team.models import UserGrant  # noqa: PLC0415

    p = effective_permissions(user.roles)
    for code in db.scalars(select(UserGrant.permission_code).where(UserGrant.user_id == user.id)):
        p[code] = "all"
    return p


def render(template: str, data: dict, perms: dict[str, str]) -> str:
    """The message with the event's fields; amounts only for roles that may see them, costs and
    margins only with tender.margin."""
    fields = _Fields({k: v for k, v in (data or {}).items() if v is not None})
    if not ({"finance.view", "billing.view", "payables.view", "tender.margin"} & set(perms)):
        fields["amount"] = "amount not shown"
    if "tender.margin" not in perms:
        fields["cost"] = "cost not shown"
        fields["margin"] = "margin not shown"
    try:
        return template.format_map(fields)[:300]
    except (ValueError, IndexError):
        return template[:300]


def is_staff(db: Session, user: User) -> bool:
    """Our own people: not a client portal login (vendors and labour have no login)."""
    from app.auth.deps import is_client_login  # noqa: PLC0415
    from app.portal.models import ClientUser  # noqa: PLC0415

    if db.scalar(select(ClientUser.user_id).where(ClientUser.user_id == user.id)):
        return False
    return not is_client_login(effective_permissions(user.roles))


def is_demo_user(user: User) -> bool:
    """The invented demo team (Prompt 19): @demo.invalid addresses, names starting "DEMO"."""
    return (user.email or "").lower().endswith("@demo.invalid") or (
        user.full_name or ""
    ).startswith("DEMO")


def _has_demo(value: Any) -> bool:
    if isinstance(value, str):
        return bool(DEMO_WORD.search(value))
    if isinstance(value, dict):
        return any(_has_demo(v) for k, v in value.items() if not str(k).startswith("_"))
    if isinstance(value, list | tuple):
        return any(_has_demo(v) for v in value)
    return False


def is_demo_event(db: Session, ev: ProcessEvent) -> bool:
    """A step on demo data: a demo site, a demo person did it, or the record is marked DEMO
    (demo data is always marked so). Its notifications go to DEMO users only."""
    from app.sites.models import Site  # noqa: PLC0415

    site = db.get(Site, ev.site_id) if ev.site_id else None
    if site is not None and site.is_demo:
        return True
    actor = db.get(User, ev.actor_id) if ev.actor_id else None
    if actor is not None and is_demo_user(actor):
        return True
    return _has_demo(ev.data)


def place_lines(data: dict | None) -> str | None:
    """The places an event is about, one per line with its own quantity."""
    rows = []
    for p in (data or {}).get("places") or []:
        qty = " ".join(str(x) for x in (p.get("qty"), p.get("unit")) if x not in (None, ""))
        rows.append(f"{p.get('place') or '—'}: {qty}" if qty else str(p.get("place") or "—"))
    return "\n".join(rows) or None


def _short_place(text: str) -> str:
    """ "DEMO Block A raft (HDPE line)" -> "DEMO Block A raft": no brackets, one line."""
    text = re.sub(r"\s*\([^)]*\)", "", text or "").replace("—", "")
    return " ".join(text.split())


def email_subject(db: Session, n) -> str:
    """At most 80 characters: "[EESPL] <what> · <site code> <short place>"."""
    from app.sites.models import Site  # noqa: PLC0415

    meta = RULE_TEXT.get(n.rule_code or "")
    if meta is None:
        out = "[EESPL] " + " ".join((n.title or "").split())
        return out if len(out) <= SUBJECT_MAX else out[: SUBJECT_MAX - 1].rstrip() + "…"
    ev = db.get(ProcessEvent, n.event_id) if n.event_id else None
    data = (ev.data if ev else None) or {}
    site_code = data.get("site_code")
    if not site_code and n.site_id:
        site = db.get(Site, n.site_id)
        site_code = site.code if site else None
    try:
        fields = _Fields({k: v for k, v in data.items() if v is not None})
        ref = (meta.get("ref") or "").format_map(fields)
    except (ValueError, IndexError):
        ref = ""
    head = f"[EESPL] {'Escalated: ' if n.escalated else ''}{meta['short']}"
    tail = " ".join(x for x in (site_code, _short_place(ref)) if x)
    out = f"{head} · {tail}" if tail else head
    return out if len(out) <= SUBJECT_MAX else out[: SUBJECT_MAX - 1].rstrip() + "…"


# --- events --------------------------------------------------------------------------------------


def emit(
    db: Session,
    type_: str,
    *,
    subject: str,
    site_id: int | None = None,
    actor_id=None,
    data: dict | None = None,
    dedupe: str | None = None,
    at: datetime | None = None,
) -> ProcessEvent | None:
    """Write the step's event (once: a retry with the same dedupe key does nothing), close the
    to-dos it completes, and notify per the rules listening for it."""
    from app.sites.models import Site  # noqa: PLC0415

    ensure_rules(db)
    key = (dedupe or f"{type_}:{subject}")[:120]
    if db.scalar(select(ProcessEvent.id).where(ProcessEvent.dedupe_key == key)):
        return None
    data = dict(data or {})
    if site_id and "site" not in data:
        site = db.get(Site, site_id)
        if site is not None:
            data["site"] = f"{site.code} {site.name}"
            data.setdefault("site_id", site.id)
            data.setdefault("site_code", site.code)
    data = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}
    ev = ProcessEvent(
        type=type_,
        site_id=site_id,
        subject=subject,
        actor_id=actor_id,
        data=data,
        dedupe_key=key,
        at=at or now(),
    )
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError:
        return None
    close(db, type_, subject, actor_id, at=ev.at)
    for rule in db.scalars(
        select(ProcessRule).where(ProcessRule.event == type_, ProcessRule.is_active)
    ):
        _notify_rule(db, rule, ev)
    return ev


def _notify_rule(
    db: Session, rule: ProcessRule, ev: ProcessEvent, level: int = 0, roles: list[str] | None = None
) -> int:
    from app.portal.models import Notification, NotificationOutbox  # noqa: PLC0415

    entries = (
        rule.recipients
        if roles is None
        else [{"role": r, "message": None, "action": "Act now"} for r in roles]
    )
    made = 0
    demo = is_demo_event(db, ev)
    body = place_lines(ev.data)
    for entry in entries:
        if entry.get("when") == "flagged" and not (ev.data or {}).get("flagged"):
            continue
        users, note = resolve(db, entry["role"], ev)
        info = bool(entry.get("info"))
        for uid in users:
            user = db.get(User, uid)
            if user is None or not user.is_active or not is_staff(db, user):
                continue
            if demo and not is_demo_user(user):
                continue  # demo data never reaches a real person
            perms = perms_of(db, user)
            if level == 0:
                title = render(entry["message"], ev.data, perms)
            else:
                base = next((e for e in rule.recipients if not e.get("info")), rule.recipients[0])
                waited = (ev.data or {}).get("_waited")
                title = render(f"Escalated ({waited}): " + base["message"], ev.data, perms)
            link = render(entry.get("link") or rule.link or "", ev.data, perms) or None
            n = Notification(
                user_id=uid,
                site_id=ev.site_id,
                kind=f"process:{rule.code}"[:30],
                title=title,
                body=body,
                link=link,
                event_id=ev.id,
                rule_code=rule.code,
                subject=ev.subject,
                action_label=None if info else (entry.get("action") or "Open"),
                needs_action=not info,
                close_on=(entry.get("closed_by") or rule.closed_by or [])
                if level == 0
                else sorted(
                    {
                        *(rule.closed_by or []),
                        *(c for e in rule.recipients for c in e.get("closed_by", [])),
                    }
                ),
                escalated=level > 0,
                escalation_level=level,
                note=note,
                created_at=ev.at if level == 0 else now(),
            )
            try:
                with db.begin_nested():
                    db.add(n)
                    db.flush()
            except IntegrityError:
                continue  # this person already has it (a retried event)
            db.add(
                NotificationOutbox(
                    notification_id=n.id, channel="in_app", status="sent", sent_at=now()
                )
            )
            _queue_email(db, n, user, rule, info, escalated=level > 0)
            made += 1
    return made


def _mode(db: Session, user_id, rule: ProcessRule, info: bool, escalated: bool) -> str:
    """app, email or summary: the person's choice; defaults: action items app and email,
    information app only, escalations always email."""
    if escalated:
        return "email"
    pref = db.get(ProcessPreference, (user_id, rule.code))
    if pref is not None:
        return pref.mode
    return "app" if info or not rule.email else "email"


def _queue_email(
    db: Session, n, user: User, rule: ProcessRule, info: bool, escalated: bool
) -> None:
    from app.portal.models import NotificationOutbox  # noqa: PLC0415

    mode = _mode(db, user.id, rule, info, escalated)
    if mode == "app" or not user.email:
        return
    if mode == "summary":
        db.add(NotificationOutbox(notification_id=n.id, channel="email", status="summary"))
        n.email_status = "summary"
    else:
        db.add(
            NotificationOutbox(
                notification_id=n.id, channel="email", status="pending", next_attempt_at=now()
            )
        )
        n.email_status = "queued"


# --- closing -------------------------------------------------------------------------------------


def close(
    db: Session,
    event_type: str | None,
    subject: str,
    actor_id=None,
    at: datetime | None = None,
    rule_code: str | None = None,
    reason: str | None = None,
) -> int:
    """Close the open to-dos on this subject that this event completes (or, with rule_code and no
    event type, every open one of that rule: "done" pressed). Escalations stop with them."""
    from app.portal.models import Notification  # noqa: PLC0415

    q = select(Notification).where(
        Notification.subject == subject,
        Notification.closed_at.is_(None),
        Notification.rule_code.is_not(None),
    )
    if rule_code:
        q = q.where(Notification.rule_code == rule_code)
    n = 0
    for note in db.scalars(q):
        if event_type is None or event_type in (note.close_on or []):
            note.closed_at, note.closed_by = at or now(), actor_id
            note.closed_reason = reason
            n += 1
    if n:
        db.flush()
    return n


def done(db: Session, note, user_id, reason: str | None = None) -> int:
    """Closed by hand: the to-do and its escalations close. The action itself was not done in
    the app (doing it closes the to-do by itself), so an action item carries the reason, shown
    on the site's process timeline."""
    return close(db, None, note.subject, user_id, rule_code=note.rule_code, reason=reason)


# --- the clock: escalations ----------------------------------------------------------------------


def escalate(db: Session, at: datetime | None = None) -> int:
    """For every open action item whose next escalation step is due (hours since it was made),
    tell the step's roles once; information-only rules never escalate."""
    from app.portal.models import Notification  # noqa: PLC0415

    at = at or now()
    rules = {r.code: r for r in db.scalars(select(ProcessRule).where(ProcessRule.is_active))}
    made = 0
    seen: set[tuple[str, str, int]] = set()
    for n in db.scalars(
        select(Notification)
        .where(
            Notification.closed_at.is_(None),
            Notification.needs_action,
            Notification.escalation_level == 0,
            Notification.rule_code.is_not(None),
        )
        .order_by(Notification.created_at)
    ):
        rule = rules.get(n.rule_code)
        if rule is None or not rule.escalations:
            continue
        step = n.escalation_step
        if step >= len(rule.escalations):
            continue
        due = n.created_at + timedelta(hours=float(rule.escalations[step]["after_hours"]))
        if due > at:
            continue
        key = (rule.code, n.subject or "", step)
        n.escalation_step = step + 1
        if key in seen:
            continue
        seen.add(key)
        ev = db.get(ProcessEvent, n.event_id) if n.event_id else None
        if ev is None:
            continue
        hours = int((at - n.created_at).total_seconds() // 3600)
        ev.data = {
            **(ev.data or {}),
            "_waited": f"waiting {hours // 24} d" if hours >= 48 else f"waiting {hours} h",
        }
        made += _notify_rule(db, rule, ev, level=step + 1, roles=rule.escalations[step]["to"])
    db.flush()
    return made


# --- email: the outbox job and the daily summary -------------------------------------------------


def _email_body(db: Session, n, user: User) -> tuple[str, str, str]:
    from app.config import settings as app_settings  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    site = db.get(Site, n.site_id) if n.site_id else None
    base = app_settings.public_base_url.rstrip("/")
    link = f"{base}{n.link}" if n.link and n.link.startswith("/") else (n.link or base)
    subject = email_subject(db, n)
    action = n.action_label or "Open in the app"
    lines = n.body.split("\n") if n.body else []
    text = (
        f"{n.title}\n"
        + "".join(f"- {x}\n" for x in lines)
        + f"{('Site: ' + site.code + ' ' + site.name) if site else ''}\n{action}: {link}\n\nEESPL App, sent to {user.full_name}."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:560px">'
        '<div style="background:#0F6B5C;color:#fff;padding:10px 14px;font-weight:bold">EESPL</div>'
        f'<p style="font-size:15px">{_esc(n.title)}</p>'
        + "".join(f'<p style="margin:4px 0;font-weight:bold">{_esc(x)}</p>' for x in lines)
        + (f'<p style="color:#555">Site: {_esc(site.code)} {_esc(site.name)}</p>' if site else "")
        + (f'<p style="color:#b42318">{_esc(n.note)}</p>' if n.note else "")
        + f'<p><a href="{_esc(link)}" style="background:#0F6B5C;color:#fff;padding:8px 14px;text-decoration:none;border-radius:4px">{_esc(action)}</a></p>'
        f'<p style="color:#888;font-size:12px">{label(n.created_at)} IST · EESPL App</p></div>'
    )
    return subject, text, html


def _esc(s: Any) -> str:
    from html import escape  # noqa: PLC0415

    return escape(str(s or ""))


def send_pending(db: Session, at: datetime | None = None, mailer=None) -> dict[str, int]:
    """Send the queued emails, with retries (1, 5, 30 minutes, 2 h, 6 h); a failure shows on the
    notification and never blocks anything."""
    from app.portal.models import Notification, NotificationOutbox  # noqa: PLC0415
    from app.process import mailer as default_mailer  # noqa: PLC0415

    mailer = mailer or default_mailer
    at = at or now()
    out = {"sent": 0, "failed": 0}
    backoff = [1, 5, 30, 120, 360]
    for row in db.scalars(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.channel == "email",
            NotificationOutbox.status == "pending",
            or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= at,
            ),
        )
        .order_by(NotificationOutbox.id)
        .limit(200)
    ):
        n = db.get(Notification, row.notification_id)
        user = db.get(User, n.user_id) if n else None
        if n is None or user is None or not user.email or not is_staff(db, user):
            row.status, row.error = "failed", "no staff email address"
            continue
        subject, text, html = _email_body(db, n, user)
        row.attempts += 1
        try:
            mailer.send(user.email, subject, text, html)
            row.status, row.sent_at, n.email_status = "sent", at, "sent"
            out["sent"] += 1
        except Exception as exc:  # noqa: BLE001  (any mail failure: retried, then shown)
            row.error = str(exc)[:300]
            if row.attempts >= len(backoff):
                row.status, n.email_status = "failed", "failed"
                out["failed"] += 1
            else:
                row.next_attempt_at = at + timedelta(minutes=backoff[row.attempts - 1])
    db.flush()
    return out


def daily_summary(db: Session, at: datetime | None = None, mailer=None, force: bool = False) -> int:
    """At 9:00 IST: one email per person with the day's items they chose to get as a summary."""
    from app.portal.models import Notification, NotificationOutbox  # noqa: PLC0415
    from app.process import mailer as default_mailer  # noqa: PLC0415

    mailer = mailer or default_mailer
    at = at or now()
    s = settings(db)
    local = at.astimezone(IST)
    if not force and (local.hour < s.summary_hour or s.last_summary_on == local.date()):
        return 0
    rows = db.execute(
        select(NotificationOutbox, Notification)
        .join(Notification, Notification.id == NotificationOutbox.notification_id)
        .where(NotificationOutbox.channel == "email", NotificationOutbox.status == "summary")
        .order_by(Notification.user_id, Notification.created_at)
    ).all()
    by_user: dict = defaultdict(list)
    for row, n in rows:
        by_user[n.user_id].append((row, n))
    sent = 0
    for uid, items in by_user.items():
        user = db.get(User, uid)
        if user is None or not user.email or not is_staff(db, user):
            continue
        lines = [f"- {n.title}" + (" (done)" if n.closed_at else "") for _row, n in items]
        text = f"Your EESPL summary for {local:%d %b %Y}:\n" + "\n".join(lines)
        html = (
            '<div style="font-family:Arial,sans-serif"><div style="background:#0F6B5C;color:#fff;padding:10px 14px;font-weight:bold">EESPL</div><p>Your summary for '
            + f"{local:%d %b %Y}"
            + ":</p><ul>"
            + "".join(
                f"<li>{_esc(n.title)}{' (done)' if n.closed_at else ''}</li>" for _r, n in items
            )
            + "</ul></div>"
        )
        try:
            mailer.send(
                user.email,
                f"[EESPL] Your summary for {local:%d %b %Y} ({len(items)} items)",
                text,
                html,
            )
            for row, n in items:
                row.status, row.sent_at, n.email_status = "sent", at, "sent"
            sent += 1
        except Exception as exc:  # noqa: BLE001
            for row, _n in items:
                row.error = str(exc)[:300]
    s.last_summary_on = local.date()
    db.flush()
    return sent


def tick(db: Session, at: datetime | None = None) -> dict[str, int]:
    """The worker's periodic run: the time-based events, the escalations, the emails."""
    from app.process import hooks  # noqa: PLC0415

    at = at or now()
    ensure_rules(db)
    out = {"timed": hooks.timed_events(db, at), "escalated": escalate(db, at)}
    out.update(send_pending(db, at))
    out["summaries"] = daily_summary(db, at)
    return out
