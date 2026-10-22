# ruff: noqa: E501
"""Password rules: at least 10 characters, not a common password, not the person's own email or
name, not one character repeated or a plain sequence. The reason is told in plain words."""

import re

MIN_LENGTH = 10

# the most used passwords (and the forms people pad them to 10 characters with); lower case
COMMON = {
    "password", "password1", "password12", "password123", "password1234", "passw0rd", "p@ssw0rd", "p@ssword", "p@ssword1", "p@ssword123",
    "123456", "1234567", "12345678", "123456789", "1234567890", "12345678910", "0123456789", "0987654321", "9876543210", "1111111111",
    "qwerty", "qwerty123", "qwertyuiop", "qwerty1234", "qwertyuiop1", "asdfghjkl", "asdfghjkl1", "zxcvbnm", "zxcvbnm123", "1qaz2wsx",
    "1q2w3e4r", "1q2w3e4r5t", "1q2w3e4r5t6y", "q1w2e3r4t5", "abc123", "abcd1234", "abcdef123", "abcdefghij", "a1b2c3d4e5", "aa12345678",
    "iloveyou", "iloveyou1", "welcome", "welcome1", "welcome123", "welcome@123", "welcome2024", "welcome2025", "welcome2026", "admin",
    "admin123", "admin@123", "admin1234", "administrator", "letmein", "letmein123", "monkey", "dragon", "football", "baseball",
    "cricket", "cricket123", "sunshine", "princess", "master", "master123", "shadow", "superman", "batman", "trustno1",
    "india", "india123", "india@123", "india12345", "bharat", "bharat123", "jaihind", "jaishreeram", "jaimatadi", "hanuman",
    "krishna", "krishna123", "ganesh", "ganesh123", "mumbai", "mumbai123", "ahmedabad", "ahmedabad1", "gujarat", "gujarat123",
    "changeme", "changeme123", "default", "default123", "secret", "secret123", "pass@123", "pass1234", "test1234", "test@123",
    "testtest", "test123456", "temp1234", "temporary", "computer", "computer1", "internet", "samsung", "samsung123", "nokia1234",
    "google", "google123", "facebook", "whatsapp", "login123", "user1234", "guest1234", "hello123", "hello@123", "hellohello",
    "summer2024", "summer2025", "winter2025", "spring2026", "monday123", "october2026", "november2026", "company123", "office123", "office@123",
    "eespl", "eespl123", "eespl@123", "eespl2026", "ethios", "ethios123", "ethios@123", "bronco", "bronco123", "waterproof",
    "waterproofing", "construction", "builder123", "site1234", "project123", "engineer", "engineer123", "manager", "manager123", "director",
}  # fmt: skip


def problem(password: str, email: str | None = None, name: str | None = None) -> str | None:
    """The reason the password is refused, or None when it is fine."""
    if len(password) < MIN_LENGTH:
        return f"The password needs at least {MIN_LENGTH} characters"
    low = password.lower()
    if low in COMMON or re.sub(r"[^a-z0-9]", "", low) in COMMON or re.sub(r"\d+$", "", low) in COMMON:
        return "That password is too common: choose another"
    if len(set(low)) <= 2:
        return "The password repeats the same characters: choose another"
    if low in "abcdefghijklmnopqrstuvwxyz0123456789" or low in "0123456789876543210" or low in "qwertyuiopasdfghjklzxcvbnm":
        return "The password is a plain sequence: choose another"
    local = (email or "").split("@")[0].lower()
    if local and len(local) >= 4 and local in low:
        return "The password must not contain your email"
    for part in (name or "").lower().split():
        if len(part) >= 4 and part in low:
            return "The password must not contain your name"
    return None


def set_password(db, user, password: str) -> None:
    """The rules, then the new password: every session ends (the refresh tokens and the access
    tokens issued before now), and a lock from failed sign-ins is lifted."""
    from datetime import UTC, datetime  # noqa: PLC0415

    from fastapi import HTTPException, status  # noqa: PLC0415

    from app.auth.router import revoke_all_refresh_tokens  # noqa: PLC0415
    from app.auth.security import hash_password  # noqa: PLC0415

    why = problem(password, user.email, user.full_name)
    if why:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, why)
    user.password_hash = hash_password(password)
    user.password_changed_at = datetime.now(UTC)
    user.failed_logins, user.locked_until, user.lockouts, user.locked_by_failures = 0, None, 0, False
    revoke_all_refresh_tokens(db, user)
