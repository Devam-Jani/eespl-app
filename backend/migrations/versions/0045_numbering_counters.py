# ruff: noqa: E501
"""Part 0 of the X-ray 3D prompt: the work completion certificates (WCC), the issue log (ISU), the
client work orders (CWO) and the labour bills (LB) take their numbers from the doc_sequences
counter rows like every other numbered document (counting the rows let two requests take the same
number). The counters start from the highest number already given.

Revision ID: 0045
Revises: 0044
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PREFIX-2026-0001: the counter (PREFIX, 2026)
YEARLY = {"WCC": "work_completions", "ISU": "issue_log", "CWO": "client_work_orders"}


def upgrade() -> None:
    for prefix, table in YEARLY.items():
        op.execute(
            f"""INSERT INTO doc_sequences (kind, period, last_value)
            SELECT '{prefix}', split_part(code, '-', 2), max(split_part(code, '-', 3)::int)
            FROM {table} WHERE code ~ '^{prefix}-[0-9]{{4}}-[0-9]+$' GROUP BY 2
            ON CONFLICT (kind, period) DO UPDATE SET last_value = GREATEST(doc_sequences.last_value, EXCLUDED.last_value)"""
        )
    # LB/26-27/0001: the counter (LB, 2026-27), the period as finance.next_number writes it
    op.execute(
        """INSERT INTO doc_sequences (kind, period, last_value)
        SELECT 'LB', '20' || split_part(number, '/', 2), max(split_part(number, '/', 3)::int)
        FROM labour_bills WHERE number ~ '^LB/[0-9]{2}-[0-9]{2}/[0-9]+$' GROUP BY 2
        ON CONFLICT (kind, period) DO UPDATE SET last_value = GREATEST(doc_sequences.last_value, EXCLUDED.last_value)"""
    )


def downgrade() -> None:
    op.execute("DELETE FROM doc_sequences WHERE kind IN ('WCC', 'ISU', 'CWO', 'LB')")
