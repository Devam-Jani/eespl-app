# ruff: noqa: E501
"""Prompt 39, Part 5: the invite email when a user is created, its resend, the forgotten-password
link, and email off (copy the link instead)."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models import User
from app.portal.models import NotificationOutbox
from app.process import engine
from app.process.engine import now
from tests.conftest import login, role_id


class FakeMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str, str, str | None]] = []
        self.fail = fail

    def send(self, to, subject, text, html=None):
        if self.fail:
            raise OSError("SMTP refused the login")
        self.sent.append((to, subject, text, html))


@pytest.fixture
def mail_on(monkeypatch):
    monkeypatch.setattr(settings, "email_enabled", False)
    monkeypatch.setattr(settings, "mailpit_host", "mailpit")  # development: queued and sent to Mailpit
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.com")


def _token(text: str) -> str:
    return re.search(r"/set-password/([\w-]+)", text).group(1)


def test_creating_a_user_queues_one_invite_with_a_valid_link_and_no_password(mail_on, login_as, db):
    c, h = login_as("office_admin", email="oa-inv@example.com")
    r = c.post("/api/users", json={"email": "new.planner@example.com", "full_name": "New Planner", "role_ids": [role_id(db, "planning")]}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["invite"]["status"] == "queued" and r.json()["has_password"] is False
    mail = FakeMailer()
    assert engine.send_pending(db, at=now(), mailer=mail)["sent"] == 1
    db.commit()
    assert len(mail.sent) == 1
    to, subject, text, html = mail.sent[0]
    assert to == "new.planner@example.com" and subject == "You're invited to EESPL"
    assert "The office admin has invited you to the EESPL Site & Tender app as Planning" in text
    assert "Set your password" in html and "https://app.example.com/set-password/" in text and "Add to Home" in text
    assert "Tide" not in text and "Your password is" not in text  # never a password
    token = _token(text)
    p = TestClient(app)
    assert p.get(f"/api/auth/password-link/{token}").json()["email"] == "new.planner@example.com"
    assert p.post(f"/api/auth/password-link/{token}", json={"password": "Tide-Lamp-Orchid-42"}).status_code == 204
    assert login(TestClient(app), "new.planner@example.com", "Tide-Lamp-Orchid-42")
    # the used link: a clear message
    r = p.get(f"/api/auth/password-link/{token}")
    assert r.status_code == 404 and "Ask your admin to resend the invite" in r.json()["detail"]
    # the admin sees it sent, with the time
    row = next(u for u in c.get("/api/users", headers=h).json() if u["email"] == "new.planner@example.com")
    assert row["invite"]["status"] == "sent" and row["invite"]["at"]


def test_resend_kills_the_old_link(mail_on, login_as, make_user, db):
    c, h = login_as("super_admin", email="sa-inv@example.com")
    u = make_user("resend@example.com", "sales")
    u.password_hash = None
    db.commit()
    assert c.post(f"/api/admin/users/{u.id}/invite", headers=h).json()["status"] == "queued"
    mail = FakeMailer()
    engine.send_pending(db, at=now(), mailer=mail)
    db.commit()
    first = _token(mail.sent[-1][2])
    assert c.post(f"/api/admin/users/{u.id}/invite", headers=h).status_code == 200
    p = TestClient(app)
    assert p.get(f"/api/auth/password-link/{first}").status_code == 404  # dead at once
    engine.send_pending(db, at=now(), mailer=mail)
    db.commit()
    second = _token(mail.sent[-1][2])
    assert second != first and p.get(f"/api/auth/password-link/{second}").status_code == 200


def test_an_expired_link_says_ask_your_admin(mail_on, login_as, make_user, db):
    from app.models import PasswordLink

    c, h = login_as("super_admin", email="sa-exp@example.com")
    u = make_user("expired@example.com", "sales")
    token = c.post(f"/api/admin/users/{u.id}/password-link", headers=h).json()["link"].rsplit("/", 1)[1]
    link = db.scalar(select(PasswordLink).where(PasswordLink.user_id == u.id, PasswordLink.used_at.is_(None)))
    link.expires_at = now() - timedelta(minutes=1)
    db.commit()
    r = TestClient(app).get(f"/api/auth/password-link/{token}")
    assert r.status_code == 404 and "Ask your admin to resend the invite" in r.json()["detail"]


def test_forgot_password_says_the_same_for_known_and_unknown_emails(mail_on, make_user, db):
    make_user("known@example.com", "sales")
    p = TestClient(app)
    a = p.post("/api/auth/forgot-password", json={"email": "known@example.com"})
    b = p.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert p.post("/api/auth/forgot-password", json={"email": "known@example.com"}).json() == a.json()  # again: no second mail
    rows = db.scalars(select(NotificationOutbox).where(NotificationOutbox.kind == "reset")).all()
    assert len(rows) == 1
    mail = FakeMailer()
    engine.send_pending(db, at=now(), mailer=mail)
    assert mail.sent[0][0] == "known@example.com" and "Reset your EESPL password" == mail.sent[0][1]


def test_clients_are_never_emailed(mail_on, make_user, db):
    make_user("client.person@example.com", "client")
    TestClient(app).post("/api/auth/forgot-password", json={"email": "client.person@example.com"})
    assert db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind.is_not(None))) is None


def test_a_failed_send_is_retried_then_shown_with_the_reason(mail_on, login_as, db):
    c, h = login_as("super_admin", email="sa-fail@example.com")
    c.post("/api/users", json={"email": "fails@example.com", "full_name": "Fails", "role_ids": [role_id(db, "sales")]}, headers=h)
    broken = FakeMailer(fail=True)
    at = now()
    for i in range(6):
        engine.send_pending(db, at=at + timedelta(hours=i * 7), mailer=broken)
    db.commit()
    row = next(u for u in c.get("/api/users", headers=h).json() if u["email"] == "fails@example.com")
    assert row["invite"]["status"] == "failed" and "SMTP refused" in row["invite"]["error"]


def test_with_email_off_nothing_is_sent_and_the_link_can_be_copied(monkeypatch, login_as, db):
    monkeypatch.setattr(settings, "email_enabled", False)
    monkeypatch.setattr(settings, "mailpit_host", "")
    c, h = login_as("super_admin", email="sa-off@example.com")
    assert c.get("/api/admin/email-mode", headers=h).json() == {"mode": "off"}
    r = c.post("/api/users", json={"email": "off.user@example.com", "full_name": "Off User", "role_ids": [role_id(db, "sales")]}, headers=h)
    assert r.status_code == 201 and r.json()["invite"] is None
    assert db.scalar(select(NotificationOutbox).where(NotificationOutbox.kind.is_not(None))) is None
    u = db.scalar(select(User).where(User.email == "off.user@example.com"))
    assert c.post(f"/api/admin/users/{u.id}/invite", headers=h).json()["detail"] == "Email is off: copy the link"
    link = c.post(f"/api/admin/users/{u.id}/password-link", headers=h).json()["link"]
    assert TestClient(app).post(f"/api/auth/password-link/{link.rsplit('/', 1)[1]}", json={"password": "Tide-Lamp-Orchid-42"}).status_code == 204
