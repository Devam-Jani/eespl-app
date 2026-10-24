# ruff: noqa: E501
"""Bills from site slips (the slip's file, its date, who signed it and when; each line as written,
billed or not), bill revisions (R0, R1 ... one sent), old bill registers and project folders read
for a site, and the work-order line's system (for the bill's material check).

Revision ID: 0052
Revises: 0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("measure_sheets", sa.Column("slip_path", sa.String(length=400), nullable=True))
    op.add_column("measure_sheets", sa.Column("slip_name", sa.String(length=300), nullable=True))
    op.add_column("measure_sheets", sa.Column("slip_on", sa.Date(), nullable=True))
    op.add_column("measure_sheets", sa.Column("signed_by", sa.String(length=200), nullable=True))
    op.add_column("measure_sheets", sa.Column("signed_on", sa.Date(), nullable=True))
    op.add_column("measure_lines", sa.Column("typed", JSON, nullable=True))
    op.add_column("measure_lines", sa.Column("billed", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("client_work_order_lines", sa.Column("system_id", sa.Integer(), sa.ForeignKey("systems.id", ondelete="SET NULL"), nullable=True))
    op.create_table(
        "bill_revisions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("ra_bill_id", sa.Integer(), sa.ForeignKey("ra_bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rev_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=300), nullable=True),
        sa.Column("made_on", sa.Date(), nullable=True),
        sa.Column("lines", JSON, server_default="[]", nullable=False),
        sa.Column("basic", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("gst", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("sent", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bill_revisions")),
        sa.UniqueConstraint("ra_bill_id", "rev_no", name=op.f("uq_bill_revisions_ra_bill_id")),
    )
    op.create_index(op.f("ix_bill_revisions_ra_bill_id"), "bill_revisions", ["ra_bill_id"])
    # one revision of a bill is the one sent to the client
    op.create_index("ux_bill_revisions_one_sent", "bill_revisions", ["ra_bill_id"], unique=True, postgresql_where=sa.text("sent"))
    op.create_table(
        "register_imports",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("rows", JSON, server_default="[]", nullable=False),
        sa.Column("files", JSON, server_default="[]", nullable=False),
        sa.Column("findings", JSON, server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_register_imports")),
    )
    op.create_index(op.f("ix_register_imports_site_id"), "register_imports", ["site_id"])


def downgrade() -> None:
    op.drop_table("register_imports")
    op.drop_index("ux_bill_revisions_one_sent", table_name="bill_revisions")
    op.drop_table("bill_revisions")
    op.drop_column("client_work_order_lines", "system_id")
    for c in ("billed", "typed"):
        op.drop_column("measure_lines", c)
    for c in ("signed_on", "signed_by", "slip_on", "slip_name", "slip_path"):
        op.drop_column("measure_sheets", c)
