"""Pricing follow-ups (Prompt 38b): labour per a system's own unit (₹ per rmt, nos, cum) besides
sqm and sq ft; a won order's "if required" lines kept on its BOQ and contract lines but out of the
contract value; a price per the product's unit (a bag's price ÷ its kg) kept to 4 decimals.

The downgrade puts labour in another unit back to sqm with no labour (sqm and sq ft were the only
units), counts "if required" lines in the totals again and rounds the prices to paise.

Revision ID: 0060f
Revises: 0059c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060f"
down_revision: str | None = "0059c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICES = (
    ("product_prices", "purchase_rate"),
    ("product_prices", "freight_per_unit"),
    ("freight_rates", "per_unit"),
    ("rate_group_products", "price"),
    ("rate_group_products", "freight_used"),
)
QUOTED = (
    "UPDATE tenders t SET quoted_total = COALESCE((SELECT SUM(amount) FROM boq_lines "
    "WHERE tender_id = t.id), 0) WHERE t.id IN (SELECT tender_id FROM boq_lines WHERE if_required)"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_systems_labour_unit_valid"), "systems", type_="check")
    op.create_check_constraint(
        op.f("ck_systems_labour_unit_valid"),
        "systems",
        "labour_unit IN ('sqm', 'sqft') OR labour_unit = unit",
    )
    for table in ("boq_lines", "contract_lines"):
        op.add_column(
            table, sa.Column("if_required", sa.Boolean(), server_default="false", nullable=False)
        )
    for table, col in PRICES:
        op.alter_column(table, col, type_=sa.Numeric(14, 4), existing_type=sa.Numeric(14, 2))


def downgrade() -> None:
    for table, col in PRICES:
        op.alter_column(table, col, type_=sa.Numeric(14, 2), existing_type=sa.Numeric(14, 4))
    op.execute(QUOTED)  # the "if required" lines count in the total again
    for table in ("boq_lines", "contract_lines"):
        op.drop_column(table, "if_required")
    op.execute(
        "UPDATE systems SET labour_unit = 'sqm', labour_rate = 0 "
        "WHERE labour_unit NOT IN ('sqm', 'sqft')"
    )
    op.drop_constraint(op.f("ck_systems_labour_unit_valid"), "systems", type_="check")
    op.create_check_constraint(
        op.f("ck_systems_labour_unit_valid"), "systems", "labour_unit IN ('sqm', 'sqft')"
    )
