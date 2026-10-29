# ruff: noqa: E501
"""Prompt 39, Part 0 (security first): who may manage whom, deactivation ends every link, and the
user import follows the Add user rule."""

import io

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import PasswordLink, User
from tests.conftest import PASSWORD, login, role_id


def _sheet(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    ws.append(
        [
            "Name",
            "Email",
            "Phone",
            "Roles",
            "Manager email",
            "Sites",
            "Tracked",
            "Travel eligible",
            "Rate per km",
        ]
    )
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_office_admin_cannot_take_over_a_super_admin_or_director_or_another_office_admin(
    login_as, make_user
):
    c, h = login_as("office_admin", email="oa-sec@example.com")
    boss = make_user("boss-sec@example.com", "super_admin")
    director = make_user("dir-sec@example.com", "director")
    peer = make_user("peer-sec@example.com", "office_admin")
    worker = make_user("est-sec@example.com", "estimator")
    for target in (boss, director, peer):
        for method, path, body in (
            ("post", f"/api/admin/users/{target.id}/password-link", None),
            ("post", f"/api/admin/users/{target.id}/unlock", None),
            ("post", f"/api/admin/users/{target.id}/two-step-reset", None),
            ("post", f"/api/users/{target.id}/reset-password", {"password": "Tide-Lamp-Orchid-42"}),
            ("patch", f"/api/users/{target.id}", {"full_name": "Changed"}),
            ("post", f"/api/users/{target.id}/deactivate", None),
        ):
            r = getattr(c, method)(path, json=body, headers=h)
            assert r.status_code == 403, (target.email, path, r.text)
    # a role below theirs is fine
    assert c.post(f"/api/admin/users/{worker.id}/password-link", headers=h).status_code == 200
    # only a super admin manages a super admin
    cs, hs = login_as("super_admin", email="sa-sec@example.com")
    assert cs.post(f"/api/admin/users/{boss.id}/password-link", headers=hs).status_code == 200
    assert cs.post(f"/api/admin/users/{peer.id}/unlock", headers=hs).status_code == 200


def test_the_office_admin_creates_every_role_but_super_admin_and_director(login_as, db):
    c, h = login_as("office_admin", email="oa-roles@example.com")
    for code in (
        "accounts",
        "billing",
        "planning",
        "sales",
        "site_engineer",
        "site_supervisor",
        "store_purchase",
        "estimator",
        "site_receiver",
        "office_admin",
    ):
        r = c.post(
            "/api/users",
            json={
                "email": f"{code.replace('_', '-')}-new@example.com",
                "full_name": f"New {code}",
                "password": "Tide-Lamp-Orchid-42",
                "role_ids": [role_id(db, code)],
            },
            headers=h,
        )
        assert r.status_code == 201, (code, r.text)
    for code in ("super_admin", "director"):
        r = c.post(
            "/api/users",
            json={
                "email": f"{code.replace('_', '-')}-new@example.com",
                "full_name": "x",
                "password": "Tide-Lamp-Orchid-42",
                "role_ids": [role_id(db, code)],
            },
            headers=h,
        )
        assert r.status_code == 403 and "above your own" in r.json()["detail"], code
    # and manages the people below them (an accounts user holds payroll.view, which the office admin lacks)
    acc = db.scalar(select(User).where(User.email == "accounts-new@example.com"))
    assert (
        c.patch(
            f"/api/users/{acc.id}", json={"full_name": "Accounts Renamed"}, headers=h
        ).status_code
        == 200
    )


def test_add_user_applies_the_password_rules(login_as, db):
    c, h = login_as("super_admin", email="sa-pw@example.com")
    r = c.post(
        "/api/users",
        json={
            "email": "weak@example.com",
            "full_name": "Weak",
            "password": "password123",
            "role_ids": [],
        },
        headers=h,
    )
    assert r.status_code == 422


def test_deactivating_ends_every_open_link_and_a_link_never_reactivates(login_as, make_user, db):
    c, h = login_as("super_admin", email="sa-deact@example.com")
    leaver = make_user("leaver@example.com", "sales")
    token = (
        c.post(f"/api/admin/users/{leaver.id}/password-link", headers=h)
        .json()["link"]
        .rsplit("/", 1)[1]
    )
    assert c.post(f"/api/users/{leaver.id}/deactivate", headers=h).status_code == 200
    db.expire_all()
    assert (
        db.scalar(
            select(PasswordLink).where(
                PasswordLink.user_id == leaver.id, PasswordLink.used_at.is_(None)
            )
        )
        is None
    )
    p = TestClient(app)
    assert p.get(f"/api/auth/password-link/{token}").status_code == 404
    assert (
        p.post(
            f"/api/auth/password-link/{token}", json={"password": "Tide-Lamp-Orchid-42"}
        ).status_code
        == 404
    )
    db.expire_all()
    assert db.get(User, leaver.id).is_active is False
    # a new link for a deactivated person is refused (activate them first)
    assert c.post(f"/api/admin/users/{leaver.id}/password-link", headers=h).status_code == 409
    # PATCH is_active false ends links too
    other = make_user("leaver2@example.com", "sales")
    token = (
        c.post(f"/api/admin/users/{other.id}/password-link", headers=h)
        .json()["link"]
        .rsplit("/", 1)[1]
    )
    assert (
        c.patch(f"/api/users/{other.id}", json={"is_active": False}, headers=h).status_code == 200
    )
    assert p.get(f"/api/auth/password-link/{token}").status_code == 404
    # a link sent while active still works and leaves is_active as it was
    stays = make_user("stays@example.com", "sales")
    token = (
        c.post(f"/api/admin/users/{stays.id}/password-link", headers=h)
        .json()["link"]
        .rsplit("/", 1)[1]
    )
    assert (
        p.post(
            f"/api/auth/password-link/{token}", json={"password": "Tide-Lamp-Orchid-42"}
        ).status_code
        == 204
    )
    assert login(TestClient(app), "stays@example.com", "Tide-Lamp-Orchid-42")
    assert login(TestClient(app), "sa-deact@example.com", PASSWORD)


def test_the_user_import_checks_roles_against_the_importer(login_as, db):
    c, h = login_as("office_admin", email="oa-imp-sec@example.com")
    f = _sheet([["Invented Boss", "boss.imp@example.com", "", "super_admin", "", "", "no", "no", ""],
                ["Invented Director", "dir.imp@example.com", "", "director", "", "", "no", "no", ""],
                ["Invented Accounts", "acc.imp@example.com", "", "accounts", "", "", "no", "no", ""]])  # fmt: skip
    r = c.post("/api/ops/user-import/check", files={"file": ("users.xlsx", f)}, headers=h).json()
    errors = {x["row"]: x["errors"] for x in r["rows"] if x["errors"]}
    assert set(errors) == {2, 3} and all("above your own" in e[0] for e in errors.values())
    assert (
        c.post(
            "/api/ops/user-import/save", files={"file": ("users.xlsx", f)}, headers=h
        ).status_code
        == 422
    )
    assert db.scalar(select(User).where(User.email == "boss.imp@example.com")) is None
