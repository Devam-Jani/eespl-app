from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
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
from app.models import RefreshToken, User
from app.schemas import LoginIn, MeOut, MeUser, RoleRef, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "eespl_refresh"
REFRESH_COOKIE_PATH = "/api/auth"
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
INVALID_CREDENTIALS = "Invalid email or password"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS)


def _issue_tokens(db: Session, user: User, response: Response) -> TokenOut:
    raw = new_refresh_token()
    max_age = int(timedelta(days=settings.refresh_token_days).total_seconds())
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=utcnow() + timedelta(seconds=max_age),
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
            audit.record(
                db,
                "auth.lockout",
                "user",
                user.id,
                user_id=user.id,
                after={"locked_until": user.locked_until},
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
    user.last_login_at = now
    tokens = _issue_tokens(db, user, response)
    audit.record(db, "auth.login", "user", user.id, user_id=user.id, ip=ip)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenOut)
def refresh(response: Response, db: DbSession, token: RefreshCookie = None):
    # FOR UPDATE: a second refresh with the same token waits here until the first commits,
    # then sees the token as revoked, so one token can never be rotated twice.
    stored = db.scalar(_token_query(token).with_for_update()) if token else None
    now = utcnow()
    if (
        stored is None
        or stored.revoked_at is not None
        or stored.expires_at <= now
        or not stored.user.is_active
    ):
        expired = JSONResponse({"detail": "Session expired"}, status.HTTP_401_UNAUTHORIZED)
        _clear_cookie(expired)
        return expired
    # Rotate: the presented token can never be used again.
    stored.revoked_at = now
    tokens = _issue_tokens(db, stored.user, response)
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
