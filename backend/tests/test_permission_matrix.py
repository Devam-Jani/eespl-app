"""For every seeded role, hit one endpoint per permission and check 200 vs 403 (and the scope)
against the role table in the M0 spec. EXPECTED is written out independently of the seed
migration so a drift in either shows up here.

admin.users, admin.roles and audit.view have real endpoints. The other permissions guard
modules that do not exist yet, so they are probed through test-only routes that use the same
require_permission() dependency the real endpoints will use.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.deps import require_permission
from app.main import app
from app.models import Permission, Role
from tests.conftest import login, role_id

ALL = [
    "admin.users", "admin.roles", "admin.settings", "audit.view",
    "library.view", "library.edit",
    "tender.view", "tender.edit", "tender.margin",
    "site.view", "site.edit", "site.update",
    "indent.raise", "indent.approve", "indent.dispatch", "indent.receive",
    "attendance.manage", "pettycash.manage",
    "finance.view", "finance.edit",
    "dashboard.view",
]  # fmt: skip


def _all(*codes):
    return dict.fromkeys(codes, "all")


EXPECTED: dict[str, dict[str, str]] = {
    "super_admin": _all(*ALL),
    "office_admin": _all(
        "admin.users", "audit.view",
        "library.view", "library.edit",
        "tender.view", "tender.edit", "tender.margin",
        "site.view", "site.edit", "site.update",
        "indent.raise", "indent.approve",
        "attendance.manage", "pettycash.manage",
        "finance.view", "dashboard.view",
    ),  # fmt: skip
    "estimator": _all(
        "library.view", "library.edit",
        "tender.view", "tender.edit", "tender.margin",
        "site.view", "dashboard.view",
    ),  # fmt: skip
    "sales": {
        "library.view": "all",
        "tender.view": "own",
        "tender.edit": "own",
        "site.view": "assigned",
        "site.update": "assigned",
        "indent.raise": "assigned",
        "dashboard.view": "own",
    },
    "site_supervisor": {
        "site.view": "assigned",
        "site.update": "assigned",
        "indent.raise": "assigned",
        "indent.receive": "assigned",
        "attendance.manage": "assigned",
        "pettycash.manage": "assigned",
    },
    "store_purchase": _all("library.view", "site.view", "indent.dispatch", "indent.approve"),
    "accounts": _all(
        "library.view", "tender.view", "tender.margin", "site.view",
        "indent.raise", "attendance.manage", "pettycash.manage",
        "finance.view", "finance.edit", "dashboard.view",
    ),  # fmt: skip
    "client": {"site.view": "assigned"},
}

REAL_ENDPOINTS = {"admin.users", "admin.roles", "audit.view"}

probe_app = FastAPI()
probe_app.include_router(app.router)
for _code in ALL:
    if _code not in REAL_ENDPOINTS:

        def _probe(scope: str = Depends(require_permission(_code))) -> dict[str, str]:  # noqa: B008
            return {"scope": scope}

        probe_app.add_api_route(f"/_probe/{_code}", _probe, methods=["GET"])


def _call(client: TestClient, code: str, headers, db):
    if code == "admin.users":
        return client.get("/api/users", headers=headers)
    if code == "admin.roles":
        # A no-op edit: exercises the admin.roles guard without changing anything.
        return client.patch(f"/api/roles/{role_id(db, 'client')}", json={}, headers=headers)
    if code == "audit.view":
        return client.get("/api/audit", headers=headers)
    return client.get(f"/_probe/{code}", headers=headers)


def test_catalogue_and_roles_match_the_spec(db):
    assert sorted(db.scalars(select(Permission.code))) == sorted(ALL)
    roles = db.scalars(select(Role)).all()
    assert sorted(r.code for r in roles) == sorted(EXPECTED)
    assert all(r.is_system for r in roles)


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_permission_matrix(role, make_user, db):
    email = f"{role.replace('_', '-')}@example.com"
    make_user(email, role)
    client = TestClient(probe_app)
    headers = login(client, email)
    expected = EXPECTED[role]

    me = client.get("/api/auth/me", headers=headers).json()
    assert me["permissions"] == expected

    mismatches = []
    for code in ALL:
        response = _call(client, code, headers, db)
        want = 200 if code in expected else 403
        if response.status_code != want:
            mismatches.append(f"{code}: got {response.status_code}, want {want}")
        elif want == 200 and code not in REAL_ENDPOINTS:
            if response.json() != {"scope": expected[code]}:
                mismatches.append(f"{code}: scope {response.json()}, want {expected[code]}")
    assert not mismatches, f"{role}:\n" + "\n".join(mismatches)
