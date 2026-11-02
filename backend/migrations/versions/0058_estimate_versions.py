# ruff: noqa: E501
"""An issued estimate keeps its figures (snapshot) and is changed by a next version (version,
revises_id; an area remembers the area it was copied from, so the site's requests carry over).
Estimates issued before this have no snapshot until `python -m app.cli estimate-snapshots`.

Revision ID: 0058v
Revises: 0057m
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0058v"
down_revision: str | None = "0057m"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("estimates", sa.Column("snapshot", JSONB()))
    op.add_column("estimates", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("estimates", sa.Column("revises_id", sa.Integer()))
    op.create_foreign_key(op.f("fk_estimates_revises_id_estimates"), "estimates", "estimates", ["revises_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint(op.f("uq_estimates_revises_id"), "estimates", ["revises_id"])
    op.add_column("estimate_areas", sa.Column("copied_from_id", sa.Integer()))
    op.create_foreign_key(op.f("fk_estimate_areas_copied_from_id_estimate_areas"), "estimate_areas", "estimate_areas", ["copied_from_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_estimate_areas_copied_from_id_estimate_areas"), "estimate_areas", type_="foreignkey")
    op.drop_column("estimate_areas", "copied_from_id")
    op.drop_constraint(op.f("uq_estimates_revises_id"), "estimates", type_="unique")
    op.drop_constraint(op.f("fk_estimates_revises_id_estimates"), "estimates", type_="foreignkey")
    op.drop_column("estimates", "revises_id")
    op.drop_column("estimates", "version")
    op.drop_column("estimates", "snapshot")
