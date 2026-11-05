"""Removing a drawing that could not be read (Prompt 38c): drawings.delete, for the super admin and
planning only (a test upload or a wrong file, removed from the card that shows it failed).

Revision ID: 0061d
Revises: 0060f
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061d"
down_revision: str | None = "0060f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODE = "drawings.delete"
ROLES = ("super_admin", "planning")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO permissions (code, module, description) VALUES ('{CODE}', 'site', "
        "'Remove a drawing that could not be read (a test upload or a wrong file)')"
    )
    for role in ROLES:
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            f"SELECT id, '{CODE}', 'all' FROM roles WHERE code = '{role}'"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{CODE}'")
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
