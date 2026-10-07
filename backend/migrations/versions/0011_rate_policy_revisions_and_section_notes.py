"""rate policy (company setting), library candidate details, tender revisions, section notes
and the client-sheet row of each BOQ line.

Data: section headings imported with a long general note ("600 WATER PROOFING — Unless
otherwise specified ...") keep the short title; the rest moves to the new note column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tender_revisions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("rev_no", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("submitted_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_tender_revisions_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_tender_revisions_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_revisions")),
        sa.UniqueConstraint("tender_id", "rev_no", name=op.f("uq_tender_revisions_tender_id")),
    )
    op.create_index(
        op.f("ix_tender_revisions_tender_id"), "tender_revisions", ["tender_id"], unique=False
    )
    op.add_column(
        "boq_line_candidates",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("boq_lines", sa.Column("source_row", sa.Integer(), nullable=True))
    op.add_column("boq_sections", sa.Column("note", sa.Text(), nullable=True))
    op.add_column(
        "company_profile",
        sa.Column(
            "rate_policy", sa.String(length=30), server_default="client_median", nullable=False
        ),
    )
    op.add_column(
        "tenders", sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
    )
    op.execute(
        "UPDATE boq_sections SET note = substr(title, position(' — ' in title) + 3), "
        "title = left(title, position(' — ' in title) - 1) "
        "WHERE position(' — ' in title) > 0 AND length(title) > 100"
    )


def downgrade() -> None:
    op.execute("UPDATE boq_sections SET title = title || ' — ' || note WHERE note IS NOT NULL")
    op.drop_column("tenders", "revision")
    op.drop_column("company_profile", "rate_policy")
    op.drop_column("boq_sections", "note")
    op.drop_column("boq_lines", "source_row")
    op.drop_column("boq_line_candidates", "details")
    op.drop_index(op.f("ix_tender_revisions_tender_id"), table_name="tender_revisions")
    op.drop_table("tender_revisions")
