"""add vendors.view / vendors.edit / settings.company and grant them

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("vendors.view", "vendors", "View vendors, their contacts and products supplied"),
    ("vendors.edit", "vendors", "Create and edit vendors"),
    ("settings.company", "settings", "Company profile, GSTIN addresses and bank accounts"),
]

GRANTS = {
    "super_admin": {"vendors.view": "all", "vendors.edit": "all", "settings.company": "all"},
    "office_admin": {"vendors.view": "all", "vendors.edit": "all", "settings.company": "all"},
    "store_purchase": {"vendors.view": "all", "vendors.edit": "all"},
    "accounts": {"vendors.view": "all", "settings.company": "all"},
    "estimator": {"vendors.view": "all"},
}

permissions = sa.table(
    "permissions", sa.column("code"), sa.column("module"), sa.column("description")
)
roles = sa.table("roles", sa.column("id"), sa.column("code"))
role_permissions = sa.table(
    "role_permissions", sa.column("role_id"), sa.column("permission_code"), sa.column("scope")
)


def upgrade() -> None:
    op.bulk_insert(
        permissions, [{"code": c, "module": m, "description": d} for c, m, d in PERMISSIONS]
    )
    conn = op.get_bind()
    role_ids = {code: id_ for code, id_ in conn.execute(sa.select(roles.c.code, roles.c.id))}
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": role_ids[role], "permission_code": code, "scope": scope}
            for role, grants in GRANTS.items()
            if role in role_ids
            for code, scope in grants.items()
        ],
    )


def downgrade() -> None:
    codes = [code for code, _, _ in PERMISSIONS]
    op.execute(permissions.delete().where(permissions.c.code.in_(codes)))
