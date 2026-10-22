# ruff: noqa: E501
"""Speed: a drawing's read is a worker job with its stage shown (converting, reading, finding
areas, done); the building's geometry for the 3D view is built once per model version and kept.

Revision ID: 0047
Revises: 0046
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cad_files", sa.Column("progress", sa.String(length=30), nullable=True))
    op.add_column("cad_files", sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("building_models", sa.Column("built", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("building_models", "built")
    op.drop_column("cad_files", "progress_at")
    op.drop_column("cad_files", "progress")
