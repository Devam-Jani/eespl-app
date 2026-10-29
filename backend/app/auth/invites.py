# ruff: noqa: E501
"""Account emails to our staff (Prompt 39, Part 5): the invite when the admin creates a user (and its
resend), and the link from "Forgot password". Each goes into the outbox (notification_outbox, kind
'invite' / 'reset') as queued; the worker sends it, with retries, and the admin sees queued, sent or
failed with the reason. The single-use set-password link (7 days) is made by the worker at the moment
it sends, so it is never stored; a resend ends the old link at once. No password is ever in an email.

Only staff are emailed (never a client portal login, a vendor or labour). With EMAIL_ENABLED off and
no Mailpit (the servers until the SMTP settings are in .env) nothing is queued: the admin copies the
link instead ("Email is off: copy the link"). In development every mail lands in Mailpit."""

import html
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import branding
from app.auth.rbac import ROLE_RANK, rank
from app.config import settings
from app.models import User

BACKOFF_MIN = [1, 5, 30, 120, 360]
RESET_GAP = timedelta(minutes=5)  # "Forgot password" pressed again within 5 minutes: one email


def email_mode() -> str:
    """'on' (real SMTP), 'mailpit' (development: caught locally) or 'off' (copy the link)."""
    if settings.email_enabled:
        return "on"
    return "mailpit" if settings.mailpit_host else "off"


def _staff(db: Session, user: User) -> bool:
    from app.process.engine import is_staff  # noqa: PLC0415

    return bool(user.email) and is_staff(db, user)


def queue(db: Session, user: User, kind: str, by: uuid.UUID | None) -> object | None:
    """An invite or reset email for this person, queued for the worker; None when email is off or
    the person is not staff (or has no email). A resend ends the earlier link and queued mail."""
    from app.auth.account import end_links  # noqa: PLC0415
    from app.portal.models import NotificationOutbox  # noqa: PLC0415

    if email_mode() == "off" or not _staff(db, user):
        return None
    end_links(db, user)
    for old in db.scalars(select(NotificationOutbox).where(NotificationOutbox.user_id == user.id, NotificationOutbox.status == "pending")):
        old.status, old.error = "failed", "replaced by a newer email"
    row = NotificationOutbox(channel="email", status="pending", kind=kind, user_id=user.id, by_user_id=by)
    db.add(row)
    db.flush()
    return row


def recent_reset(db: Session, user: User, at: datetime) -> bool:
    from app.portal.models import NotificationOutbox  # noqa: PLC0415

    return db.scalar(
        select(NotificationOutbox.id).where(NotificationOutbox.user_id == user.id, NotificationOutbox.kind == "reset", NotificationOutbox.created_at > at - RESET_GAP).limit(1)
    ) is not None  # fmt: skip


def last_mail(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per person, their latest account email: kind, status (queued / sent / failed), when, why."""
    from app.portal.models import NotificationOutbox  # noqa: PLC0415

    out: dict[uuid.UUID, dict] = {}
    if not user_ids:
        return out
    rows = db.scalars(select(NotificationOutbox).where(NotificationOutbox.user_id.in_(user_ids)).order_by(NotificationOutbox.id))
    for r in rows:
        out[r.user_id] = {"kind": r.kind, "status": "queued" if r.status == "pending" else r.status, "at": r.sent_at or r.created_at, "error": r.error}
    return out


def _role_phrase(db: Session, user: User | None) -> str:
    """'The office admin' / 'The super admin': the inviter's highest role, never their name."""
    if user is None:
        return "Your admin"
    top = max(user.roles, key=lambda r: ROLE_RANK.get(r.code, 0), default=None)
    if top is None or not rank(user.roles):
        return "Your admin"
    return f"The {top.name.lower()}"


def _roles_of(user: User) -> str:
    names = [r.name for r in user.roles]
    return ", ".join(names) if names else "a member of staff"


def body(db: Session, user: User, kind: str, link: str, by: User | None) -> tuple[str, str, str]:
    """(subject, text, html). The link is the full address of the single-use set-password page."""
    app_url = settings.public_base_url.rstrip("/")
    title = branding.app_title()
    first = "On your phone, open the app link in the browser and add it to the home screen (Share > Add to Home Screen on an iPhone; the menu > Add to Home screen or Install app on Android): it then opens like an app."
    if kind == "invite":
        subject = f"You're invited to {branding.PRODUCT_NAME}"
        lead = f"{_role_phrase(db, by)} has invited you to the {title} as {_roles_of(user)}."
        button = "Set your password"
        after = "The link works once and for 7 days. After setting your password, sign in with your email address."
    else:
        subject = f"Reset your {branding.PRODUCT_NAME} password"
        lead = f"Someone asked to reset the password of your {title} login. If it was not you, ignore this email: your password stays as it is."
        button = "Set a new password"
        after = "The link works once and for 7 days."
    text = f"{lead}\n\n{button}: {link}\n\n{after}\n\nThe app: {app_url}\n\nFirst login: {first}\n\n{branding.PRODUCT_NAME} · {branding.PRODUCT_TAG}\n"
    e = html.escape
    page = (
        '<div style="font-family:Arial,sans-serif;max-width:560px">'
        f'<div style="background:#0F6B5C;color:#fff;padding:10px 14px;font-weight:bold">{e(branding.PRODUCT_NAME)}</div>'
        f'<p style="font-size:15px">{e(lead)}</p>'
        f'<p><a href="{e(link)}" style="background:#0F6B5C;color:#fff;padding:10px 16px;text-decoration:none;border-radius:4px;display:inline-block">{e(button)}</a></p>'
        f'<p style="color:#555">{e(after)}</p>'
        f'<p>The app: <a href="{e(app_url)}">{e(app_url)}</a></p>'
        f'<p style="color:#555"><b>First login.</b> {e(first)}</p>'
        f'<p style="color:#888;font-size:12px">{e(branding.PRODUCT_NAME)} · {e(branding.PRODUCT_TAG)}</p></div>'
    )
    return subject, text, page


def send_pending(db: Session, at: datetime, mailer) -> dict[str, int]:
    """The worker: every queued account email, with a fresh link each, retried (1, 5, 30 min, 2 h, 6 h)."""
    from app.auth.account import make_link  # noqa: PLC0415
    from app.portal.models import NotificationOutbox  # noqa: PLC0415

    out = {"sent": 0, "failed": 0}
    rows = db.scalars(
        select(NotificationOutbox)
        .where(NotificationOutbox.kind.is_not(None), NotificationOutbox.status == "pending",
               or_(NotificationOutbox.next_attempt_at.is_(None), NotificationOutbox.next_attempt_at <= at))
        .order_by(NotificationOutbox.id).limit(100)
    ).all()  # fmt: skip
    for row in rows:
        user = db.get(User, row.user_id)
        if user is None or not user.is_active or not _staff(db, user):
            row.status, row.error = "failed", "not an active staff login with an email address"
            out["failed"] += 1
            continue
        link = settings.public_base_url.rstrip("/") + make_link(db, user, row.by_user_id)
        subject, text, page = body(db, user, row.kind, link, db.get(User, row.by_user_id) if row.by_user_id else None)
        row.attempts += 1
        try:
            mailer.send(user.email, subject, text, page)
            row.status, row.sent_at, row.error = "sent", at, None
            out["sent"] += 1
        except Exception as exc:  # noqa: BLE001  (any mail failure: retried, then shown to the admin)
            row.error = str(exc)[:300]
            if row.attempts >= len(BACKOFF_MIN):
                row.status = "failed"
                out["failed"] += 1
            else:
                row.next_attempt_at = at + timedelta(minutes=BACKOFF_MIN[row.attempts - 1])
        db.flush()  # one row at a time: a later failure never undoes a sent email's link
    return out
