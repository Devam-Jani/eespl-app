"""Password hashing, access tokens (JWT) and refresh tokens."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import settings

MIN_PASSWORD_LENGTH = 10
JWT_ALGORITHM = "HS256"

_hasher = PasswordHash.recommended()  # argon2id


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (valid, new_hash); new_hash is set when the stored hash should be upgraded."""
    return _hasher.verify_and_update(password, password_hash)


# Verified against when the email is unknown so both failure paths take the same time.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: uuid.UUID) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id, or raise jwt.InvalidTokenError."""
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]}
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    try:
        return uuid.UUID(payload["sub"])
    except ValueError as exc:
        raise jwt.InvalidTokenError("bad subject") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    # Refresh tokens are 256-bit random values, so a fast hash is sufficient.
    return hashlib.sha256(token.encode()).hexdigest()
