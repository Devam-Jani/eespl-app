import uuid
from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.auth import totp
from app.auth.deps import CurrentPrincipal
from app.auth.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    utcnow,
    verify_password,
)
from app.config import settings
from app.db import DbSession
from app.models import RefreshToken, SecuritySettings, User
from app.schemas import LoginIn, MeOut, MeUser, RoleRef, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "eespl_refresh"
REFRESH_COOKIE_PATH = "/api/auth"
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
# the third lockout in a row waits for the office admin (Users > Unlock)
LOCKOUTS_BEFORE_ADMIN = 3
TICKET_MINUTES = 5
INVALID_CREDENTIALS = "Invalid email or password"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS)


def _device(request: Request | None) -> str:
    """phone or desktop: the app says which (X-Device), else the browser's user agent."""
    if request is None:
        return "desktop"
    said = (request.headers.get("x-device") or "").lower()
    if said in ("phone", "desktop"):
        return said
    ua = request.headers.get("user-agent") or ""
    return "phone" if ("Mobi" in ua or "Android" in ua or "iPhone" in ua) else "desktop"


def _issue_tokens(
    db: Session, user: User, response: Response, request: Request | None = None, active_at=None
) -> TokenOut:
    raw = new_refresh_token()
    max_age = int(timedelta(days=settings.refresh_token_days).total_seconds())
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=utcnow() + timedelta(seconds=max_age),
            device=_device(request),
            active_at=active_at or utcnow(),
        )
    )
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_minutes * 60,
    )


def _token_query(token: str):
    return select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> TokenOut:
    email = body.email.strip().lower()
    ip = audit.client_ip(request)
    now = utcnow()
    user = db.scalar(select(User).where(User.email == email))

    def record_failure(reason: str) -> None:
        audit.record(
            db,
            "auth.login_failed",
            "user",
            user.id if user else None,
            user_id=user.id if user else None,
            after={"email": email, "reason": reason},
            ip=ip,
        )

    def fail(reason: str) -> HTTPException:
        record_failure(reason)
        db.commit()
        # Every failure gets the same message, so callers cannot probe which emails exist.
        return _invalid_credentials()

    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise fail("unknown_email")
    if user.locked_by_failures:  # waits for the office admin to unlock it
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise fail("locked_admin")
    if user.locked_until is not None and user.locked_until > now:
        raise fail("locked")

    if user.password_hash is None:  # imported or invited, no password set yet
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise fail("no_password")

    valid, new_hash = verify_password(body.password, user.password_hash)
    if not valid:
        record_failure("bad_password")
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = 0
            user.locked_until = now + LOCKOUT
            user.lockouts += 1
            if user.lockouts >= LOCKOUTS_BEFORE_ADMIN:
                user.locked_by_failures = True
            audit.record(
                db,
                "auth.lockout",
                "user",
                user.id,
                user_id=user.id,
                after={
                    "locked_until": user.locked_until,
                    "lockouts": user.lockouts,
                    "until_unlocked": user.locked_by_failures,
                },
                ip=ip,
            )
        db.commit()
        raise _invalid_credentials()
    if not user.is_active:
        raise fail("inactive")

    if new_hash:
        user.password_hash = new_hash
    user.failed_logins = 0
    user.locked_until = None
    user.lockouts = 0
    # two-step login: the code from the authenticator app (or setting it up when it is required)
    step = two_step_needed(db, user)
    if step:
        audit.record(
            db,
            "auth.password_ok",
            "user",
            user.id,
            user_id=user.id,
            ip=ip,
            after={"two_step": step},
        )
        db.commit()
        out = {"two_step": step, "ticket": make_ticket(user, step)}
        if step == "enroll":
            secret = totp.new_secret()
            out["ticket"] = make_ticket(user, step, secret)
            out["secret"] = secret
            out["qr"] = totp.qr_svg(totp.uri(secret, user.email or str(user.id)))
        return JSONResponse(out)
    user.last_login_at = now
    tokens = _issue_tokens(db, user, response, request)
    audit.record(db, "auth.login", "user", user.id, user_id=user.id, ip=ip)
    db.commit()
    return tokens


def two_step_needed(db: Session, user: User) -> str | None:
    """ "code" when the user has two-step login on; "enroll" when a setting requires it for one of
    their roles and they have not set it up; else None."""
    if user.totp_enabled_at and user.totp_secret:
        return "code"
    s = db.get(SecuritySettings, 1)
    if s is not None and s.totp_required and {r.code for r in user.roles} & set(s.totp_roles or []):
        return "enroll"
    return None


def make_ticket(user: User, step: str, secret: str | None = None) -> str:
    """The password was right: this short ticket (5 minutes) lets the second step finish it."""
    payload = {
        "sub": str(user.id),
        "type": "two_step",
        "step": step,
        "exp": utcnow() + timedelta(minutes=TICKET_MINUTES),
    }
    if secret:
        payload["sec"] = totp.seal(secret)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class TwoStepIn(BaseModel):
    ticket: str
    code: str = Field(min_length=6, max_length=8)


@router.post("/login/two-step")
def login_two_step(
    body: TwoStepIn, request: Request, response: Response, db: DbSession
) -> TokenOut:
    """The code from the authenticator app; when enrolling, it also turns two-step login on."""
    try:
        p = jwt.decode(
            body.ticket,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "The sign-in took too long: start again"
        ) from exc
    if p.get("type") != "two_step":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Start the sign-in again")
    user = db.get(User, uuid.UUID(p["sub"]))
    if user is None or not user.is_active or user.locked_by_failures:
        raise _invalid_credentials()
    ip = audit.client_ip(request)
    secret = (
        totp.unseal(p["sec"])
        if p.get("step") == "enroll" and p.get("sec")
        else (totp.unseal(user.totp_secret) if user.totp_secret else None)
    )
    if not secret or not totp.verify(secret, body.code):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins, user.locked_until, user.lockouts = (
                0,
                utcnow() + LOCKOUT,
                user.lockouts + 1,
            )
            user.locked_by_failures = user.lockouts >= LOCKOUTS_BEFORE_ADMIN
        audit.record(db, "auth.two_step_failed", "user", user.id, user_id=user.id, ip=ip)
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "That code is not right: check the time on your phone and try the newest code",
        )
    if p.get("step") == "enroll":
        user.totp_secret, user.totp_enabled_at = totp.seal(secret), utcnow()
        audit.record(db, "auth.two_step_on", "user", user.id, user_id=user.id, ip=ip)
    user.failed_logins, user.last_login_at = 0, utcnow()
    tokens = _issue_tokens(db, user, response, request)
    audit.record(
        db, "auth.login", "user", user.id, user_id=user.id, ip=ip, after={"two_step": True}
    )
    db.commit()
    return tokens


def idle_limit(db: Session, device: str) -> timedelta:
    s = db.get(SecuritySettings, 1)
    hours = (
        (s.idle_hours_phone if device == "phone" else s.idle_hours_desktop)
        if s
        else (12 if device == "phone" else 8)
    )
    return timedelta(hours=hours)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: DbSession, token: RefreshCookie = None):
    """A new access token. The app says how long ago the person last used it (X-Idle-Seconds):
    past the inactivity limit (Settings > Security: 12 hours on a phone, 8 on a desktop) the
    session is over, as it is after a password change."""
    # FOR UPDATE: a second refresh with the same token waits here until the first commits,
    # then sees the token as revoked, so one token can never be rotated twice.
    stored = db.scalar(_token_query(token).with_for_update()) if token else None
    now = utcnow()
    try:
        idle = timedelta(seconds=max(0, int(request.headers.get("x-idle-seconds") or 0)))
    except ValueError:
        idle = timedelta(0)
    over = changed = False
    seen = now
    if stored is not None:
        # the person's last use: what the app reports, else the last activity we were told of
        seen = (
            now - idle
            if request.headers.get("x-idle-seconds")
            else (stored.active_at or stored.created_at)
        )
        over = now - seen > idle_limit(db, stored.device)
        pc = stored.user.password_changed_at
        changed = pc is not None and stored.created_at < pc
    if (
        stored is None
        or stored.revoked_at is not None
        or stored.expires_at <= now
        or not stored.user.is_active
        or over
        or changed
    ):
        expired = JSONResponse({"detail": "Session expired"}, status.HTTP_401_UNAUTHORIZED)
        _clear_cookie(expired)
        if stored is not None and stored.revoked_at is None and (over or changed):
            stored.revoked_at = now
            db.commit()
        return expired
    # Rotate: the presented token can never be used again.
    stored.revoked_at = now
    tokens = _issue_tokens(db, stored.user, response, request, active_at=seen)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, token: RefreshCookie = None):
    if token:
        stored = db.scalar(_token_query(token).with_for_update())
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = utcnow()
            audit.record(
                db,
                "auth.logout",
                "user",
                stored.user_id,
                user_id=stored.user_id,
                ip=audit.client_ip(request),
            )
            db.commit()
    _clear_cookie(response)


@router.get("/me")
def me(principal: CurrentPrincipal) -> MeOut:
    return MeOut(
        user=MeUser.model_validate(principal.user),
        roles=[RoleRef.model_validate(r) for r in principal.user.roles],
        permissions=principal.permissions,
    )


def revoke_all_refresh_tokens(db: Session, user: User) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
