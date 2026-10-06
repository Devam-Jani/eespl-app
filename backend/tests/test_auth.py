from datetime import timedelta

from sqlalchemy import select

from app.auth.router import REFRESH_COOKIE
from app.auth.security import utcnow
from app.models import AuditLog, User
from tests.conftest import PASSWORD, login

GENERIC = {"detail": "Invalid email or password"}


def test_login_success_sets_refresh_cookie(client, make_user, db):
    make_user("ana@example.com", "estimator")
    response = client.post(
        "/api/auth/login", json={"email": "  Ana@Example.com ", "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    cookie = response.headers["set-cookie"]
    assert f"{REFRESH_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/auth" in cookie
    assert "Max-Age=604800" in cookie

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ana@example.com"
    assert [r["code"] for r in me.json()["roles"]] == ["estimator"]

    user = db.scalar(select(User).where(User.email == "ana@example.com"))
    db.refresh(user)
    assert user.last_login_at is not None


def test_wrong_password_and_unknown_email_get_the_same_error(client, make_user):
    make_user("ana@example.com", "estimator")
    wrong = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "nope"})
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == GENERIC
    assert "set-cookie" not in wrong.headers


def test_lockout_after_five_failures(client, make_user, db):
    user = make_user("ana@example.com", "estimator")
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "bad"})
        assert r.status_code == 401
    db.refresh(user)
    assert user.locked_until is not None
    assert user.locked_until > utcnow() + timedelta(minutes=14)

    # Locked: even the correct password is refused, with the same generic error.
    r = client.post("/api/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json() == GENERIC
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.lockout")) is not None

    # Once the lock expires the user can log in again.
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.commit()
    login(client, "ana@example.com")


def test_four_failures_then_success_resets_counter(client, make_user, db):
    user = make_user("ana@example.com", "estimator")
    for _ in range(4):
        client.post("/api/auth/login", json={"email": "ana@example.com", "password": "bad"})
    login(client, "ana@example.com")
    db.refresh(user)
    assert user.failed_logins == 0
    assert user.locked_until is None


def test_inactive_user_cannot_log_in(client, make_user):
    make_user("gone@example.com", "estimator", is_active=False)
    r = client.post("/api/auth/login", json={"email": "gone@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json() == GENERIC


def test_deactivated_user_cannot_refresh_or_use_access_token(client, make_user, db):
    user = make_user("ana@example.com", "estimator")
    headers = login(client, "ana@example.com")
    user.is_active = False
    db.commit()
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_refresh_rotates_and_old_token_is_rejected(client, make_user):
    make_user("ana@example.com", "estimator")
    login(client, "ana@example.com")
    old = client.cookies.get(REFRESH_COOKIE)

    r = client.post("/api/auth/refresh")
    assert r.status_code == 200
    new = client.cookies.get(REFRESH_COOKIE)
    assert new and new != old
    assert (
        client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
        ).status_code
        == 200
    )

    client.cookies.set(REFRESH_COOKIE, old, path="/api/auth")
    reused = client.post("/api/auth/refresh")
    assert reused.status_code == 401
    assert reused.json() == {"detail": "Session expired"}


def test_refresh_without_cookie_is_rejected(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token(client, make_user):
    make_user("ana@example.com", "estimator")
    login(client, "ana@example.com")
    token = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/api/auth/logout").status_code == 204

    client.cookies.set(REFRESH_COOKIE, token, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


def test_me_requires_a_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_me_merges_roles_to_the_widest_scope(login_as):
    # sales has tender.view 'own'; estimator has it 'all'.
    c, headers = login_as("sales", "estimator")
    perms = c.get("/api/auth/me", headers=headers).json()["permissions"]
    assert perms["tender.view"] == "all"
    assert perms["site.view"] == "all"
    assert perms["indent.raise"] == "assigned"  # only sales has it


def test_concurrent_refreshes_rotate_a_token_only_once(make_user, monkeypatch):
    """Two refreshes racing with the same cookie: the row lock lets exactly one win."""
    import threading
    import time

    from fastapi.testclient import TestClient

    import app.auth.router as auth_router
    from app.main import app

    make_user("ana@example.com", "estimator")
    first = TestClient(app)
    login(first, "ana@example.com")
    token = first.cookies.get(REFRESH_COOKIE)

    # Widen the race window: pause after the token row is read, before the commit.
    original = auth_router.create_access_token

    def slow_create_access_token(user_id):
        time.sleep(0.5)
        return original(user_id)

    monkeypatch.setattr(auth_router, "create_access_token", slow_create_access_token)

    statuses: list[int] = []

    def refresh_once():
        c = TestClient(app)
        c.cookies.set(REFRESH_COOKIE, token, path="/api/auth")
        statuses.append(c.post("/api/auth/refresh").status_code)

    threads = [threading.Thread(target=refresh_once) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200, 401]
