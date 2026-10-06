"""seed the permission catalogue and the system roles

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06

Data only. The values are frozen here on purpose (no imports from app code), so this migration
keeps producing the same result as the application evolves. Later changes to role permissions
are made in the app and recorded in the audit log.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS: list[tuple[str, str, str]] = [
    ("admin.users", "admin", "Manage users: create, edit, deactivate, reset passwords, set roles"),
    ("admin.roles", "admin", "Manage roles and their permissions"),
    ("admin.settings", "admin", "Change application settings"),
    ("audit.view", "audit", "View the audit log"),
    ("library.view", "library", "View the item and rate library"),
    ("library.edit", "library", "Edit the item and rate library"),
    ("tender.view", "tender", "View tenders"),
    ("tender.edit", "tender", "Create and edit tenders"),
    ("tender.margin", "tender", "See and change tender margins"),
    ("site.view", "site", "View sites"),
    ("site.edit", "site", "Create and edit sites"),
    ("site.update", "site", "Post site progress updates"),
    ("indent.raise", "indent", "Raise material indents"),
    ("indent.approve", "indent", "Approve material indents"),
    ("indent.dispatch", "indent", "Dispatch material against indents"),
    ("indent.receive", "indent", "Receive material at site"),
    ("attendance.manage", "attendance", "Manage site attendance"),
    ("pettycash.manage", "pettycash", "Manage petty cash"),
    ("finance.view", "finance", "View finance"),
    ("finance.edit", "finance", "Edit finance"),
    ("dashboard.view", "dashboard", "View dashboards"),
]

ALL_CODES = [code for code, _, _ in PERMISSIONS]


def _all(*codes: str) -> dict[str, str]:
    return dict.fromkeys(codes, "all")


# (code, name, description, {permission: scope})
ROLES: list[tuple[str, str, str, dict[str, str]]] = [
    ("super_admin", "Super admin", "Full access to everything", _all(*ALL_CODES)),
    (
        "office_admin",
        "Office admin",
        "Runs the office: users, tenders, sites, indents, attendance and petty cash",
        _all(
            "admin.users",
            "audit.view",
            "library.view",
            "library.edit",
            "tender.view",
            "tender.edit",
            "tender.margin",
            "site.view",
            "site.edit",
            "site.update",
            "indent.raise",
            "indent.approve",
            "attendance.manage",
            "pettycash.manage",
            "finance.view",
            "dashboard.view",
        ),
    ),
    (
        "estimator",
        "Estimator",
        "Prepares tenders and maintains the library",
        _all(
            "library.view",
            "library.edit",
            "tender.view",
            "tender.edit",
            "tender.margin",
            "site.view",
            "dashboard.view",
        ),
    ),
    (
        "sales",
        "Sales",
        "Works their own tenders and the sites assigned to them",
        {
            "library.view": "all",
            "tender.view": "own",
            "tender.edit": "own",
            "site.view": "assigned",
            "site.update": "assigned",
            "indent.raise": "assigned",
            "dashboard.view": "own",
        },
    ),
    (
        "site_supervisor",
        "Site supervisor",
        "Runs the sites assigned to them",
        {
            "site.view": "assigned",
            "site.update": "assigned",
            "indent.raise": "assigned",
            "indent.receive": "assigned",
            "attendance.manage": "assigned",
            "pettycash.manage": "assigned",
        },
    ),
    (
        "store_purchase",
        "Store / purchase",
        "Approves and dispatches indents",
        _all("library.view", "site.view", "indent.dispatch", "indent.approve"),
    ),
    (
        "accounts",
        "Accounts",
        "Finance, attendance and petty cash",
        _all(
            "library.view",
            "tender.view",
            "tender.margin",
            "site.view",
            "indent.raise",
            "attendance.manage",
            "pettycash.manage",
            "finance.view",
            "finance.edit",
            "dashboard.view",
        ),
    ),
    ("client", "Client", "External client: sees only assigned sites", {"site.view": "assigned"}),
]

permissions_table = sa.table(
    "permissions",
    sa.column("code", sa.String),
    sa.column("module", sa.String),
    sa.column("description", sa.Text),
)
roles_table = sa.table(
    "roles",
    sa.column("id", sa.Integer),
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_system", sa.Boolean),
)
role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role_id", sa.Integer),
    sa.column("permission_code", sa.String),
    sa.column("scope", sa.String),
)


def upgrade() -> None:
    conn = op.get_bind()
    op.bulk_insert(
        permissions_table,
        [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS],
    )
    for code, name, description, grants in ROLES:
        role_id = conn.execute(
            roles_table.insert()
            .values(code=code, name=name, description=description, is_system=True)
            .returning(roles_table.c.id)
        ).scalar_one()
        op.bulk_insert(
            role_permissions_table,
            [
                {"role_id": role_id, "permission_code": perm, "scope": scope}
                for perm, scope in grants.items()
            ],
        )


def downgrade() -> None:
    codes = [code for code, _, _, _ in ROLES]
    # role_permissions and user_roles rows go with the roles (ON DELETE CASCADE).
    op.execute(roles_table.delete().where(roles_table.c.code.in_(codes)))
    op.execute(permissions_table.delete().where(permissions_table.c.code.in_(ALL_CODES)))
