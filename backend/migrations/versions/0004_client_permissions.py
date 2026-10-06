"""add clients.view / clients.edit and grant them to the system roles

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("clients.view", "clients", "View clients and their contacts"),
    ("clients.edit", "clients", "Create and edit clients and their contacts"),
]

# role code -> {permission: scope}
GRANTS = {
    "super_admin": {"clients.view": "all", "clients.edit": "all"},
    "office_admin": {"clients.view": "all", "clients.edit": "all"},
    "estimator": {"clients.view": "all", "clients.edit": "all"},
    "sales": {"clients.view": "all", "clients.edit": "own"},
    "accounts": {"clients.view": "all"},
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
    rows = [
        {"role_id": role_ids[role], "permission_code": code, "scope": scope}
        for role, grants in GRANTS.items()
        if role in role_ids
        for code, scope in grants.items()
    ]
    op.bulk_insert(role_permissions, rows)


def downgrade() -> None:
    # role_permissions rows go with the permissions (ON DELETE CASCADE).
    codes = [code for code, _, _ in PERMISSIONS]
    op.execute(permissions.delete().where(permissions.c.code.in_(codes)))
