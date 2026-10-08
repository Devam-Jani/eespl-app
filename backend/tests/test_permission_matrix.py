"""For every seeded role, hit one endpoint per permission and check 200 vs 403 (and the scope)
against the role table in the M0 spec. EXPECTED is written out independently of the seed
migration so a drift in either shows up here.

admin.users, admin.roles, audit.view, clients.view and library.view are checked on real
endpoints. The other permissions guard
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
    "clients.view", "clients.edit",
    "vendors.view", "vendors.edit", "settings.company",
    "library.view", "library.edit",
    "tender.view", "tender.edit", "tender.margin",
    "site.view", "site.edit", "site.update", "drawings.approve",
    "indent.view", "indent.create", "indent.approve",
    "po.view", "po.edit", "po.approve", "grn.view", "grn.edit", "grn.approve",
    "store.view", "store.edit",
    "dpr.view", "dpr.edit", "labour.view", "labour.edit", "subcon.view", "subcon.edit",
    "subcon.approve", "inspection.view", "inspection.edit", "asset.view", "asset.edit",
    "budget.view", "budget.edit",
    "attendance.manage",
    "billing.view", "billing.edit", "billing.approve", "payables.view", "payables.edit",
    "payables.approve", "expense.create", "expense.approve", "payroll.view", "payroll.edit",
    "finance.export",
    "finance.view", "finance.edit",
    "dashboard.view",
    "leads.view", "leads.edit",
    "portal.view", "portal.comment", "portal.snag", "portal.approve", "portal.manage",
]  # fmt: skip


def _all(*codes):
    return dict.fromkeys(codes, "all")


EXPECTED: dict[str, dict[str, str]] = {
    "super_admin": _all(*ALL),
    "office_admin": _all(
        "admin.users",
        "audit.view",
        "clients.view",
        "clients.edit",
        "vendors.view",
        "vendors.edit",
        "settings.company",
        "library.view",
        "library.edit",
        "tender.view",
        "tender.edit",
        "tender.margin",
        "site.view",
        "site.edit",
        "site.update",
        "drawings.approve",
        "indent.view",
        "indent.create",
        "indent.approve",
        "po.view",
        "po.edit",
        "po.approve",
        "grn.view",
        "grn.edit",
        "grn.approve",
        "store.view",
        "store.edit",
        "dpr.view",
        "dpr.edit",
        "labour.view",
        "labour.edit",
        "subcon.view",
        "subcon.edit",
        "subcon.approve",
        "inspection.view",
        "inspection.edit",
        "asset.view",
        "asset.edit",
        "budget.view",
        "budget.edit",
        "attendance.manage",
        "billing.view",
        "billing.edit",
        "billing.approve",
        "payables.view",
        "payables.edit",
        "payables.approve",
        "expense.create",
        "expense.approve",
        "finance.export",
        "finance.view",
        "dashboard.view",
        "leads.view",
        "leads.edit",
        "portal.manage",
    ),  # fmt: skip
    "estimator": _all(
        "clients.view",
        "clients.edit",
        "vendors.view",
        "library.view",
        "library.edit",
        "tender.view",
        "tender.edit",
        "tender.margin",
        "site.view",
        "dashboard.view",
    ),  # fmt: skip
    "sales": {
        "clients.view": "all",
        "clients.edit": "own",
        "library.view": "all",
        "tender.view": "own",
        "tender.edit": "own",
        "site.view": "assigned",
        "site.update": "assigned",
        "indent.view": "assigned",
        "dpr.view": "assigned",
        "billing.view": "assigned",
        "dashboard.view": "own",
        "leads.view": "own",
        "leads.edit": "own",
        "portal.manage": "assigned",
    },
    "site_supervisor": {
        "site.view": "assigned",
        "site.update": "assigned",
        "indent.view": "assigned",
        "indent.create": "assigned",
        "grn.view": "assigned",
        "grn.edit": "assigned",
        "store.view": "assigned",
        "store.edit": "assigned",
        "dpr.view": "assigned",
        "dpr.edit": "assigned",
        "labour.view": "assigned",
        "labour.edit": "assigned",
        "inspection.view": "assigned",
        "inspection.edit": "assigned",
        "asset.view": "assigned",
        "attendance.manage": "assigned",
        "expense.create": "own",
    },
    "store_purchase": _all(
        "vendors.view",
        "vendors.edit",
        "library.view",
        "site.view",
        "indent.view",
        "indent.create",
        "indent.approve",
        "po.view",
        "po.edit",
        "grn.view",
        "grn.edit",
        "grn.approve",
        "store.view",
        "store.edit",
        "asset.view",
        "asset.edit",
    ),  # fmt: skip
    "accounts": _all(
        "clients.view",
        "vendors.view",
        "settings.company",
        "library.view",
        "tender.view",
        "tender.margin",
        "site.view",
        "po.view",
        "grn.view",
        "dpr.view",
        "labour.view",
        "subcon.view",
        "inspection.view",
        "asset.view",
        "budget.view",
        "attendance.manage",
        "billing.view",
        "billing.edit",
        "payables.view",
        "payables.edit",
        "expense.create",
        "expense.approve",
        "payroll.view",
        "payroll.edit",
        "finance.export",
        "finance.view",
        "finance.edit",
        "dashboard.view",
    ),  # fmt: skip
    # the client portal only; every staff endpoint stays 403 (tests/test_portal.py)
    "client": dict.fromkeys(
        ["portal.view", "portal.comment", "portal.snag", "portal.approve"], "own"
    ),
}

REAL_ENDPOINTS = {
    "admin.users", "admin.roles", "audit.view", "clients.view", "library.view",
    "vendors.view", "settings.company", "site.view", "leads.view",
    "indent.view", "po.view", "grn.view", "store.view",
    "dpr.view", "labour.view", "subcon.view", "inspection.view", "asset.view",
    "billing.view", "payables.view", "payroll.view",
}  # fmt: skip


def _probe_path(code: str) -> str:
    # client logins only reach /api/portal/..., so the portal codes are probed there
    return f"/api/portal/_probe/{code}" if code.startswith("portal.") else f"/_probe/{code}"


probe_app = FastAPI()
probe_app.include_router(app.router)
for _code in ALL:
    if _code not in REAL_ENDPOINTS:

        def _probe(scope: str = Depends(require_permission(_code))) -> dict[str, str]:  # noqa: B008
            return {"scope": scope}

        probe_app.add_api_route(_probe_path(_code), _probe, methods=["GET"])


def _call(client: TestClient, code: str, headers, db):
    if code == "admin.users":
        return client.get("/api/users", headers=headers)
    if code == "admin.roles":
        # A no-op edit: exercises the admin.roles guard without changing anything.
        return client.patch(f"/api/roles/{role_id(db, 'client')}", json={}, headers=headers)
    if code == "audit.view":
        return client.get("/api/audit", headers=headers)
    if code == "clients.view":
        return client.get("/api/clients", headers=headers)
    if code == "vendors.view":
        return client.get("/api/vendors", headers=headers)
    if code == "settings.company":
        return client.get("/api/settings/company", headers=headers)
    if code == "leads.view":
        return client.get("/api/leads", headers=headers)
    if code == "site.view":
        return client.get("/api/sites", headers=headers)
    if code in ("indent.view", "po.view", "grn.view"):
        path = {"indent.view": "indents", "po.view": "pos", "grn.view": "grns"}[code]
        return client.get(f"/api/material/{path}", headers=headers)
    execution = {"dpr.view": "dprs", "labour.view": "labour", "subcon.view": "work-orders",
                 "inspection.view": "inspections", "asset.view": "assets"}  # fmt: skip
    finance = {"billing.view": "invoices", "payables.view": "vendor-bills",
               "payroll.view": "payroll"}  # fmt: skip
    if code in finance:
        return client.get(f"/api/finance/{finance[code]}", headers=headers)
    if code in execution:
        return client.get(f"/api/execution/{execution[code]}", headers=headers)
    if code == "store.view":
        return client.get("/api/material/stores", headers=headers)
    if code == "library.view":
        return client.get("/api/products", headers=headers)
    return client.get(_probe_path(code), headers=headers)


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
