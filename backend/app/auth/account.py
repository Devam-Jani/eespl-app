# ruff: noqa: E501
"""The person's own account (their password, two-step login), the one-time set-password links
the admin hands out, the unlock after repeated failed sign-ins, and Settings > Security (two-step
login required for some roles; the inactivity limits)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app import audit
from app.auth import totp
from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.auth.passwords import problem, set_password
from app.auth.security import verify_password
from app.config import settings
from app.db import DbSession
from app.models import PasswordLink, SecuritySettings, User

router = APIRouter(tags=["account"])
Admin = Annotated[str, Depends(require_permission("admin.users"))]
SecurityAdmin = Annotated[str, Depends(require_any_permission("admin.users", "system.ops"))]
LINK_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


def _ip(request: Request) -> str | None:
    return audit.client_ip(request)


# --- my password ----------------------------------------------------------------------------------


class ChangeIn(BaseModel):
    current: str = Field(min_length=1, max_length=256)
    new: str = Field(min_length=1, max_length=256)


class ThemeIn(BaseModel):
    theme: Literal["dark", "light"]


@router.put("/api/auth/theme")
def set_theme(body: ThemeIn, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The person's look (dark or light), remembered for them on every device."""
    user = db.get(User, principal.user.id)
    user.ui_theme = body.theme
    db.commit()
    return {"theme": user.ui_theme}


@router.post("/api/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangeIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> None:
    """The person's own new password: every session of theirs ends (sign in again)."""
    user = principal.user
    ok, _ = verify_password(body.current, user.password_hash or "")
    if not ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The current password is not right")
    set_password(db, user, body.new)
    audit.record(db, "auth.password_change", "user", user.id, user_id=user.id, ip=_ip(request))
    db.commit()


# --- one-time set-password links --------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def end_links(db, user: User) -> None:
    """Every open set-password link of this person stops working (deactivated, or a new link)."""
    db.execute(update(PasswordLink).where(PasswordLink.user_id == user.id, PasswordLink.used_at.is_(None)).values(used_at=_now()))


def make_link(db, user: User, by: uuid.UUID | None) -> str:
    """A new link (earlier unused ones stop working); only its hash is kept. The path to add to
    the app's address: /set-password/<token>."""
    end_links(db, user)
    token = secrets.token_urlsafe(32)
    db.add(PasswordLink(user_id=user.id, token_hash=_hash(token), expires_at=_now() + timedelta(days=LINK_DAYS), created_by=by))
    db.flush()
    return f"/set-password/{token}"


def _link(db, token: str) -> PasswordLink:
    link = db.scalar(select(PasswordLink).where(PasswordLink.token_hash == _hash(token)))
    if link is None or link.used_at is not None or link.expires_at <= _now() or not db.get(User, link.user_id).is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link was used already or has expired: ask the office admin for a new one")
    return link


@router.get("/api/auth/password-link/{token}")
def link_info(token: str, db: DbSession) -> dict:
    user = db.get(User, _link(db, token).user_id)
    return {"full_name": user.full_name, "email": user.email}


class SetIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/api/auth/password-link/{token}", status_code=status.HTTP_204_NO_CONTENT)
def link_set(token: str, body: SetIn, request: Request, db: DbSession) -> None:
    """Set the password from the link; it works once. Then sign in on the login page."""
    link = _link(db, token)
    user = db.get(User, link.user_id)
    set_password(db, user, body.password)
    link.used_at = _now()
    audit.record(db, "auth.password_link_used", "user", user.id, user_id=user.id, ip=_ip(request))
    db.commit()


def _managed(db, principal, user_id: uuid.UUID) -> User:
    """The user, when the caller may manage them (same rule as Edit / Reset password)."""
    from app.routers.users import check_can_manage  # noqa: PLC0415

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    check_can_manage(principal, user)
    return user


@router.post("/api/admin/users/{user_id}/password-link")
def admin_link(user_id: uuid.UUID, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin) -> dict:
    """A one-time link for this person to set their password: copy it and send it yourself (the
    app sends no email until EMAIL_ENABLED). Shown once."""
    user = _managed(db, principal, user_id)
    if user.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not user.is_active:
        if user.password_hash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This user is deactivated: activate them first")
        user.is_active = True  # never set up (e.g. from the PowerPlay import): the admin's link lets them in
    path = make_link(db, user, principal.user.id)
    audit.record(db, "user.password_link", "user", user.id, user_id=principal.user.id, ip=_ip(request))
    db.commit()
    return {"link": path, "expires_in_days": LINK_DAYS}


@router.post("/api/admin/users/{user_id}/unlock")
def unlock(user_id: uuid.UUID, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin) -> dict:
    """After repeated failed sign-ins the account waits for the office admin."""
    user = _managed(db, principal, user_id)
    before = {"locked_by_failures": user.locked_by_failures, "locked_until": user.locked_until, "lockouts": user.lockouts}
    user.failed_logins, user.locked_until, user.lockouts, user.locked_by_failures = 0, None, 0, False
    audit.record(db, "user.unlock", "user", user.id, user_id=principal.user.id, before=before, ip=_ip(request))
    db.commit()
    return {"id": str(user.id), "locked": False}


# --- two-step login (the person's own) ------------------------------------------------------------------


def _required_for(db, user: User) -> bool:
    s = db.get(SecuritySettings, 1)
    return bool(s and s.totp_required and {r.code for r in user.roles} & set(s.totp_roles or []))


@router.get("/api/auth/two-step")
def two_step_status(db: DbSession, principal: CurrentPrincipal) -> dict:
    u = principal.user
    s = db.get(SecuritySettings, 1)
    return {"enabled": bool(u.totp_enabled_at), "enabled_at": u.totp_enabled_at, "required": _required_for(db, u),
            "offered": bool(s and {r.code for r in u.roles} & set(s.totp_roles or []))}  # fmt: skip


@router.post("/api/auth/two-step/start")
def two_step_start(principal: CurrentPrincipal) -> dict:
    """A new secret to scan into the authenticator app; confirmed with a code before it counts."""
    u = principal.user
    secret = totp.new_secret()
    ticket = jwt.encode({"sub": str(u.id), "type": "two_step_setup", "sec": totp.seal(secret), "exp": _now() + timedelta(minutes=10)}, settings.jwt_secret, algorithm="HS256")
    return {"ticket": ticket, "secret": secret, "qr": totp.qr_svg(totp.uri(secret, u.email or str(u.id)))}


class ConfirmIn(BaseModel):
    ticket: str
    code: str = Field(min_length=6, max_length=8)


@router.post("/api/auth/two-step/confirm")
def two_step_confirm(body: ConfirmIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    try:
        p = jwt.decode(body.ticket, settings.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start again: the setup took too long") from exc
    if p.get("type") != "two_step_setup" or p.get("sub") != str(principal.user.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start again")
    secret = totp.unseal(p["sec"])
    if not secret or not totp.verify(secret, body.code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That code is not right: try the newest one")
    u = principal.user
    u.totp_secret, u.totp_enabled_at = totp.seal(secret), _now()
    audit.record(db, "auth.two_step_on", "user", u.id, user_id=u.id, ip=_ip(request))
    db.commit()
    return {"enabled": True}


class OffIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/api/auth/two-step/off")
def two_step_off(body: OffIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    u = principal.user
    if _required_for(db, u):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Two-step login is required for your role (Settings > Security)")
    secret = totp.unseal(u.totp_secret) if u.totp_secret else None
    if not secret or not totp.verify(secret, body.code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That code is not right")
    u.totp_secret, u.totp_enabled_at = None, None
    audit.record(db, "auth.two_step_off", "user", u.id, user_id=u.id, ip=_ip(request))
    db.commit()
    return {"enabled": False}


@router.post("/api/admin/users/{user_id}/two-step-reset")
def two_step_reset(user_id: uuid.UUID, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin) -> dict:
    """A lost phone: two-step login off for this person (they set it up again at the next sign-in
    when their role requires it)."""
    user = _managed(db, principal, user_id)
    user.totp_secret, user.totp_enabled_at = None, None
    audit.record(db, "user.two_step_reset", "user", user.id, user_id=principal.user.id, ip=_ip(request))
    db.commit()
    return {"id": str(user.id), "two_step": False}


# --- Settings > Security -------------------------------------------------------------------------------


class SecurityIn(BaseModel):
    totp_required: bool | None = None
    totp_roles: list[str] | None = None
    idle_hours_phone: int | None = Field(default=None, ge=1, le=72)
    idle_hours_desktop: int | None = Field(default=None, ge=1, le=72)


def _security_out(s: SecuritySettings) -> dict:
    return {"totp_required": s.totp_required, "totp_roles": s.totp_roles, "idle_hours_phone": s.idle_hours_phone, "idle_hours_desktop": s.idle_hours_desktop,
            "min_password_length": 10, "lock_after": 5, "lock_minutes": 15, "admin_unlock_after_lockouts": 3}  # fmt: skip


@router.get("/api/admin/security")
def security_get(db: DbSession, _: SecurityAdmin) -> dict:
    return _security_out(db.get(SecuritySettings, 1))


@router.put("/api/admin/security")
def security_put(body: SecurityIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: SecurityAdmin) -> dict:
    s = db.get(SecuritySettings, 1)
    before = _security_out(s)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(s, k, v)
    audit.record(db, "security.settings", "security_settings", 1, user_id=principal.user.id, before=before, after=_security_out(s), ip=_ip(request))
    db.commit()
    return _security_out(s)


@router.post("/api/auth/password-check")
def password_check(body: SetIn) -> dict:
    """The rules, for the form to tell the person before they submit."""
    return {"problem": problem(body.password)}
