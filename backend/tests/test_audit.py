from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import role_id


def test_user_create_writes_audit_row(login_as, db):
    c, h = login_as("super_admin")
    actor = c.get("/api/auth/me", headers=h).json()["user"]["id"]
    r = c.post(
        "/api/users",
        json={
            "email": "new@example.com",
            "full_name": "New",
            "password": "a-strong-password",
            "role_ids": [role_id(db, "estimator")],
        },
        headers=h,
    )
    assert r.status_code == 201
    row = db.scalar(select(AuditLog).where(AuditLog.action == "user.create"))
    assert row is not None
    assert str(row.user_id) == actor
    assert row.entity == "user"
    assert row.entity_id == r.json()["id"]
    assert row.after["email"] == "new@example.com"
    assert row.after["roles"] == ["estimator"]
    assert "password" not in str(row.after)
    assert row.ip


def test_failed_login_writes_audit_row(client, make_user, db):
    user = make_user("ana@example.com", "estimator")
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong"})
    client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong"})

    rows = db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.login_failed").order_by(AuditLog.id)
    ).all()
    assert [(r.after["email"], r.after["reason"]) for r in rows] == [
        ("ana@example.com", "bad_password"),
        ("ghost@example.com", "unknown_email"),
    ]
    assert rows[0].user_id == user.id
    assert rows[1].user_id is None


def test_successful_login_and_role_changes_are_audited(login_as, db):
    c, h = login_as("super_admin")
    c.post("/api/roles", json={"code": "temp_role", "name": "Temp"}, headers=h)
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"auth.login", "role.create"} <= actions


def test_audit_endpoint_filters(login_as, make_user, client):
    make_user("ana@example.com", "estimator")
    client.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong"})
    c, h = login_as("super_admin", email="boss@example.com")

    everything = c.get("/api/audit", headers=h).json()
    assert everything["total"] >= 2

    failed = c.get("/api/audit", params={"action": "auth.login_failed"}, headers=h).json()
    assert failed["total"] == 1
    assert failed["items"][0]["after"]["email"] == "ana@example.com"

    by_user = c.get("/api/audit", params={"user": "boss@"}, headers=h).json()
    assert by_user["total"] >= 1
    assert all(i["user_email"] == "boss@example.com" for i in by_user["items"])

    assert c.get("/api/audit", params={"entity": "role"}, headers=h).json()["total"] == 0
    future = c.get("/api/audit", params={"date_from": "2999-01-01"}, headers=h).json()
    assert future["total"] == 0
