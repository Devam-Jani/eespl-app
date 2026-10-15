"""From the rate working review: Samgard is Bronco Cemguard (the systems renamed, linked to the
Bronco products with "Samgard" kept as an alias, consumption still to confirm), the margin basis
(on cost or on the selling price), and where a main item's wastage came from.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-13 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "costing_settings",
        sa.Column("margin_basis", sa.String(length=8), server_default="cost", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_costing_settings_margin_basis_valid"),
        "costing_settings",
        "margin_basis IN ('cost', 'selling')",
    )
    op.add_column("rate_groups", sa.Column("wastage_source", sa.String(length=200), nullable=True))

    from app.masters.named_systems import cemguard  # noqa: PLC0415  (plain SQL, safe here)

    cemguard(op.get_bind())


def downgrade() -> None:
    op.execute(
        "UPDATE systems SET code = 'SAMGARD', name = 'Samgard' WHERE code = 'CEMGUARD'; "
        "UPDATE systems SET code = 'SAMGARD-PLUS', name = 'Samgard Plus' "
        "WHERE code = 'CEMGUARD-PLUS'"
    )
    op.drop_column("rate_groups", "wastage_source")
    op.drop_constraint(
        op.f("ck_costing_settings_margin_basis_valid"), "costing_settings", type_="check"
    )
    op.drop_column("costing_settings", "margin_basis")
