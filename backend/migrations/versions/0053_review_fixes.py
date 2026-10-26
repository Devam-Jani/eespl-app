# ruff: noqa: E501
"""From the Prompt 33 review: a renumbered RA bill keeps its number in the old files ("was RA 16"),
shown in the register and searched; a slip line with no work-order item can be proposed as a new
item or variation (description, unit, rate), approved by the director, then billed and sent to the
client with the bill.

Revision ID: 0053
Revises: 0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    ("variation.request", "finance", "Propose a new item or variation for a slip line with no work-order item"),
    ("variation.approve", "finance", "Approve a new item or variation before it goes to the client"),
]
GRANTS = {"super_admin": {"variation.request": "all", "variation.approve": "all"}, "director": {"variation.request": "all", "variation.approve": "all"},
          "billing": {"variation.request": "all"}}


def upgrade() -> None:
    op.add_column("ra_bills", sa.Column("old_no", sa.String(length=20), nullable=True))
    op.create_index("ix_ra_bills_old_no", "ra_bills", ["old_no"])
    op.create_table(
        "variation_requests",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("measure_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_id", sa.BigInteger(), sa.ForeignKey("measure_lines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("particulars", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="proposed", nullable=False),
        sa.Column("decided_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("wo_line_id", sa.Integer(), sa.ForeignKey("client_work_order_lines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ra_bill_id", sa.Integer(), sa.ForeignKey("ra_bills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("status IN ('proposed', 'approved', 'rejected')", name=op.f("ck_variation_requests_status_valid")),
    )
    op.create_index("ix_variation_requests_site_id", "variation_requests", ["site_id"])
    op.create_index("ix_variation_requests_sheet_id", "variation_requests", ["sheet_id"])
    for code, module, description in NEW_PERMISSIONS:
        op.execute(f"INSERT INTO permissions (code, module, description) VALUES ('{code}', '{module}', '{description}')")
    for role, codes in GRANTS.items():
        for code, scope in codes.items():
            op.execute(f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{code}', '{scope}' FROM roles WHERE code = '{role}'")


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c, _m, _d in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_code IN ({codes})")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes})")
    op.drop_table("variation_requests")
    op.drop_index("ix_ra_bills_old_no", table_name="ra_bills")
    op.drop_column("ra_bills", "old_no")
