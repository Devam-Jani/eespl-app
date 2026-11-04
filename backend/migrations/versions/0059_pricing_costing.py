"""The rate working keeps 4 decimals for labour per sq ft and surface preparation per sqm (a per
sqm figure ÷ 10.7639 is not rounded before the rate), and a product keeps its own wastage when
no application matched.

Revision ID: 0059c
Revises: 0058v
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059c"
down_revision: str | None = "0058v"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WIDER = ("surface_prep", "labour_used_sqft", "labour_paid_sqft")


def upgrade() -> None:
    for col in WIDER:
        op.alter_column(
            "rate_groups", col, type_=sa.Numeric(14, 4), existing_type=sa.Numeric(14, 2)
        )
    op.add_column("rate_group_products", sa.Column("wastage_percent", sa.Numeric(7, 3)))


def downgrade() -> None:
    op.drop_column("rate_group_products", "wastage_percent")
    for col in WIDER:
        op.alter_column(
            "rate_groups", col, type_=sa.Numeric(14, 2), existing_type=sa.Numeric(14, 4)
        )
