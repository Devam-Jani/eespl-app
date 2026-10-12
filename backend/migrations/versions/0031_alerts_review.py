"""From the process alerts review: the places a notification is about (one per line), the reason
when a to-do is closed by hand, and systems whose products, consumption or coats are still to
confirm (blank, never guessed), with the systems Ankur Sir named and the suitable systems per area
type.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-13 09:00:00

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAMED = "('SAMGARD', 'SAMGARD-PLUS', 'ULTRA-FLEX', 'HYBRID-PU')"

# stage done: the place and its quantity go on their own line, not into the message
OLD_NEW = {
    "Work done: {site}, {area}, {stage}, {qty} {unit} on {date}. Make the stage bill "
    "(measurement book entry attached).": "Work done on {date}: make the stage bill "
    "(measurement book entry attached).",
    "Work done: {site}, {area}, {stage}, {qty} {unit} on {date}. Billing makes the stage "
    "bill.": "Work done on {date}: billing makes the stage bill.",
}


def upgrade() -> None:
    op.add_column("notifications", sa.Column("body", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("closed_reason", sa.String(length=300), nullable=True))
    op.add_column(
        "systems", sa.Column("to_confirm", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("systems", sa.Column("note", sa.Text(), nullable=True))
    op.alter_column(
        "system_components", "consumption_per_unit", existing_type=sa.Numeric(12, 4), nullable=True
    )
    op.add_column("system_components", sa.Column("coats", sa.Integer(), nullable=True))
    op.add_column(
        "system_components",
        sa.Column("to_confirm", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("system_components", sa.Column("note", sa.Text(), nullable=True))

    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT recipients FROM process_rules WHERE code = 'stage_done'")
    ).first()
    if row is not None:
        recipients = [
            {**r, "message": OLD_NEW.get(r.get("message"), r.get("message"))} for r in row[0]
        ]
        conn.execute(
            sa.text(
                "UPDATE process_rules SET recipients = CAST(:r AS jsonb) WHERE code = 'stage_done'"
            ),
            {"r": json.dumps(recipients)},
        )

    from app.masters.named_systems import seed  # noqa: PLC0415  (plain SQL, safe in a migration)

    seed(conn)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM system_components WHERE consumption_per_unit IS NULL AND system_id IN "
            "(SELECT id FROM systems WHERE code IN "
            + NAMED
            + ")"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE area_types SET suitable_system_ids = '{}' WHERE suitable_system_ids && "
            "ARRAY(SELECT id FROM systems WHERE code IN "
            + NAMED
            + ")"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE area_types SET default_system_id = NULL WHERE default_system_id IN "
            "(SELECT id FROM systems WHERE code IN "
            + NAMED
            + ")"
        )
    )
    conn.execute(sa.text("DELETE FROM systems WHERE code IN " + NAMED))
    conn.execute(sa.text("DELETE FROM system_components WHERE consumption_per_unit IS NULL"))
    op.drop_column("system_components", "note")
    op.drop_column("system_components", "to_confirm")
    op.drop_column("system_components", "coats")
    op.alter_column(
        "system_components", "consumption_per_unit", existing_type=sa.Numeric(12, 4), nullable=False
    )
    op.drop_column("systems", "note")
    op.drop_column("systems", "to_confirm")
    op.drop_column("notifications", "closed_reason")
    op.drop_column("notifications", "body")
