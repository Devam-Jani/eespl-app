"""The new UI: each person's look (dark or light), remembered on the user.

Revision ID: 0049
Revises: 0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ui_theme", sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ui_theme")
