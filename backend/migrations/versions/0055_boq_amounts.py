# ruff: noqa: E501
"""From the Prompt 34 review: a BOQ line written outside the pricing routes (a demo, an import) kept
no amount, so its tender's quoted total read ₹0.00 although the lines had a quantity and a rate.
The models now keep both on every write; this fills the lines already stored and their tenders'
totals. Nothing else changes; the downgrade leaves the filled amounts (they are qty × rate).

Revision ID: 0055
Revises: 0054
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TEMP TABLE boq_fixed ON COMMIT DROP AS SELECT DISTINCT tender_id FROM boq_lines "
        "WHERE amount IS NULL AND qty_note IS NULL AND qty IS NOT NULL AND rate IS NOT NULL"
    )
    op.execute("UPDATE boq_lines SET amount = ROUND(qty * rate, 2) WHERE amount IS NULL AND qty_note IS NULL AND qty IS NOT NULL AND rate IS NOT NULL")
    op.execute(
        "UPDATE tenders t SET quoted_total = COALESCE((SELECT SUM(amount) FROM boq_lines WHERE tender_id = t.id), 0) "
        "WHERE t.id IN (SELECT tender_id FROM boq_fixed)"
    )


def downgrade() -> None:
    pass
