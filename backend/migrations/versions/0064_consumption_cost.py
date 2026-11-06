"""consumption.cost (Prompt 39b): the consumption master's prices, material cost and selling rate,
and "update rate" there, without tender.margin as a whole; for the super admin and planning.

Revision ID: 0064g
Revises: 0063f
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064g"
down_revision: str | None = "0063f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "consumption.cost"
ROLES = ("super_admin", "planning")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO permissions (code, module, description) VALUES ('{CODE}', 'masters', "
        "'Consumption master: see prices, material cost and selling rate; update rates')"
    )
    for role in ROLES:
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            f"SELECT id, '{CODE}', 'all' FROM roles WHERE code = '{role}'"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{CODE}'")
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
