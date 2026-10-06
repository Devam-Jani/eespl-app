from fastapi.testclient import TestClient

from app.main import app
from app.models import Role
from tests.conftest import PASSWORD, role_id

NEW_PASSWORD = "another-strong-pass"


def _create_user_body(email, *role_ids):
    return {
        "email": email,
        "full_name": "New Person",
        "password": NEW_PASSWORD,
        "role_ids": list(role_ids),
    }


def test_office_admin_can_create_users_with_lesser_roles(login_as, db):
    c, h = login_as("office_admin")
    r = c.post("/api/users", json=_create_user_body("est@example.com", role_id(db, "estimator")),
               headers=h)  # fmt: skip
    assert r.status_code == 201, r.text
    assert [x["code"] for x in r.json()["roles"]] == ["estimator"]


def test_office_admin_cannot_assign_super_admin(login_as, make_user, db):
    c, h = login_as("office_admin")
    sa = role_id(db, "super_admin")

    r = c.post("/api/users", json=_create_user_body("x@example.com", sa), headers=h)
    assert r.status_code == 403
    assert "admin.roles" in r.json()["detail"]

    target = make_user("est@example.com", "estimator")
    r = c.put(f"/api/users/{target.id}/roles", json={"role_ids": [sa]}, headers=h)
    assert r.status_code == 403


def test_office_admin_cannot_edit_roles(login_as, db):
    c, h = login_as("office_admin")
    r = c.put(
        f"/api/roles/{role_id(db, 'estimator')}/permissions",
        json={"permissions": {"library.view": "all"}},
        headers=h,
    )
    assert r.status_code == 403
    assert c.post("/api/roles", json={"code": "x_role", "name": "X"}, headers=h).status_code == 403


def test_office_admin_cannot_manage_a_super_admin(login_as, make_user):
    c, h = login_as("office_admin")
    boss = make_user("boss@example.com", "super_admin")
    r = c.post(f"/api/users/{boss.id}/reset-password", json={"password": NEW_PASSWORD}, headers=h)
    assert r.status_code == 403
    assert c.post(f"/api/users/{boss.id}/deactivate", headers=h).status_code == 403


def test_client_role_cannot_be_given_margin_finance_or_admin(login_as, db):
    c, h = login_as("super_admin")
    client_id = role_id(db, "client")
    for perm in ("tender.margin", "finance.edit", "admin.users", "admin.settings"):
        r = c.put(
            f"/api/roles/{client_id}/permissions",
            json={"permissions": {"site.view": "assigned", perm: "all"}},
            headers=h,
        )
        assert r.status_code == 422, perm
        assert perm in r.json()["detail"]
    # Harmless permissions are fine.
    r = c.put(
        f"/api/roles/{client_id}/permissions",
        json={"permissions": {"site.view": "assigned", "dashboard.view": "own"}},
        headers=h,
    )
    assert r.status_code == 200


def test_client_user_cannot_gain_forbidden_permissions_via_another_role(login_as, make_user, db):
    c, h = login_as("super_admin")
    customer = make_user("customer@example.com", "client")

    # Directly: client + accounts (which has tender.margin and finance.edit).
    r = c.put(
        f"/api/users/{customer.id}/roles",
        json={"role_ids": [role_id(db, "client"), role_id(db, "accounts")]},
        headers=h,
    )
    assert r.status_code == 422

    # Indirectly: give the client user a harmless custom role, then widen that role.
    r = c.post(
        "/api/roles",
        json={"code": "viewer", "name": "Viewer", "permissions": {"library.view": "all"}},
        headers=h,
    )
    viewer = r.json()["id"]
    r = c.put(
        f"/api/users/{customer.id}/roles",
        json={"role_ids": [role_id(db, "client"), viewer]},
        headers=h,
    )
    assert r.status_code == 200
    r = c.put(
        f"/api/roles/{viewer}/permissions",
        json={"permissions": {"library.view": "all", "tender.margin": "all"}},
        headers=h,
    )
    assert r.status_code == 422


def test_system_roles_cannot_be_deleted_but_custom_ones_can(login_as, db):
    c, h = login_as("super_admin")
    for code in ("super_admin", "client", "estimator"):
        r = c.delete(f"/api/roles/{role_id(db, code)}", headers=h)
        assert r.status_code == 409
    r = c.post("/api/roles", json={"code": "temp_role", "name": "Temp"}, headers=h)
    assert r.status_code == 201
    assert c.delete(f"/api/roles/{r.json()['id']}", headers=h).status_code == 204
    assert db.get(Role, r.json()["id"]) is None


def test_super_admin_role_permissions_are_locked(login_as, db):
    c, h = login_as("super_admin")
    r = c.put(
        f"/api/roles/{role_id(db, 'super_admin')}/permissions",
        json={"permissions": {}},
        headers=h,
    )
    assert r.status_code == 409


def test_role_permission_edit_takes_effect_immediately(login_as, make_user, db):
    c, h = login_as("super_admin")
    est = make_user("est@example.com", "estimator")
    r = c.put(
        f"/api/roles/{role_id(db, 'estimator')}/permissions",
        json={"permissions": {"library.view": "all", "tender.view": "own"}},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["permissions"] == {"library.view": "all", "tender.view": "own"}
    est_client = TestClient(app)
    est_h = {
        "Authorization": "Bearer "
        + est_client.post(
            "/api/auth/login", json={"email": est.email, "password": PASSWORD}
        ).json()["access_token"]
    }
    perms = est_client.get("/api/auth/me", headers=est_h).json()["permissions"]
    assert perms == {"library.view": "all", "tender.view": "own"}


def test_user_admin_lifecycle(login_as, db):
    c, h = login_as("super_admin")
    r = c.post("/api/users", json=_create_user_body("Pat@Example.com"), headers=h)
    assert r.status_code == 201
    uid = r.json()["id"]
    assert r.json()["email"] == "pat@example.com"

    duplicate = _create_user_body("pat@example.com")
    assert c.post("/api/users", json=duplicate, headers=h).status_code == 409
    short = {**_create_user_body("q@example.com"), "password": "short"}
    assert c.post("/api/users", json=short, headers=h).status_code == 422

    r = c.patch(f"/api/users/{uid}", json={"full_name": "Pat Doe", "phone": "+91 98"}, headers=h)
    assert r.json()["full_name"] == "Pat Doe"

    r = c.post(f"/api/users/{uid}/reset-password", json={"password": "brand-new-pass"}, headers=h)
    assert r.status_code == 204
    assert c.post(
        "/api/auth/login", json={"email": "pat@example.com", "password": "brand-new-pass"}
    ).status_code == 200

    r = c.post(f"/api/users/{uid}/deactivate", headers=h)
    assert r.json()["is_active"] is False
    assert c.post(
        "/api/auth/login", json={"email": "pat@example.com", "password": "brand-new-pass"}
    ).status_code == 401


def test_cannot_deactivate_yourself(login_as, db):
    c, h = login_as("super_admin")
    me = c.get("/api/auth/me", headers=h).json()["user"]["id"]
    assert c.post(f"/api/users/{me}/deactivate", headers=h).status_code == 409
