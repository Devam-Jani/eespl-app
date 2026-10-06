"""T&C clauses: hidden status with reason, merging, review flags

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tc_clauses", sa.Column("status", sa.String(10), server_default="active", nullable=False)
    )
    op.add_column("tc_clauses", sa.Column("hidden_reason", sa.String(30), nullable=True))
    op.add_column("tc_clauses", sa.Column("merged_into_id", sa.Integer(), nullable=True))
    op.add_column(
        "tc_clauses",
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("tc_clauses", sa.Column("review_note", sa.Text(), nullable=True))
    # A clause's own count from the source; usage_count of a master = own + its variants' own,
    # so unmerging can restore the original numbers exactly.
    op.add_column(
        "tc_clauses",
        sa.Column("own_usage_count", sa.Integer(), server_default="0", nullable=False),
    )
    # Set when a person hides, unhides, merges, unmerges, edits or reviews a clause; the
    # cleanup command never overrides such a decision.
    op.add_column(
        "tc_clauses", sa.Column("curated", sa.Boolean(), server_default="false", nullable=False)
    )
    op.execute("UPDATE tc_clauses SET own_usage_count = usage_count")
    # status replaces the old is_active switch
    op.execute(
        "UPDATE tc_clauses SET status = 'hidden', hidden_reason = 'manual' WHERE NOT is_active"
    )
    op.drop_column("tc_clauses", "is_active")

    op.create_check_constraint(
        op.f("ck_tc_clauses_status_valid"), "tc_clauses", "status IN ('active', 'hidden')"
    )
    op.create_check_constraint(
        op.f("ck_tc_clauses_hidden_reason_valid"),
        "tc_clauses",
        "(status = 'active' AND hidden_reason IS NULL) OR (status = 'hidden' AND hidden_reason "
        "IN ('not_a_clause', 'client_checklist', 'project_specific', 'manual'))",
    )
    op.create_check_constraint(
        op.f("ck_tc_clauses_not_merged_into_self"),
        "tc_clauses",
        "merged_into_id IS NULL OR merged_into_id <> id",
    )
    op.create_foreign_key(
        op.f("fk_tc_clauses_merged_into_id_tc_clauses"),
        "tc_clauses",
        "tc_clauses",
        ["merged_into_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_tc_clauses_merged_into_id"), "tc_clauses", ["merged_into_id"])


def downgrade() -> None:
    op.add_column(
        "tc_clauses",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.execute("UPDATE tc_clauses SET is_active = (status = 'active')")
    op.drop_index(op.f("ix_tc_clauses_merged_into_id"), table_name="tc_clauses")
    op.drop_constraint(
        op.f("fk_tc_clauses_merged_into_id_tc_clauses"), "tc_clauses", type_="foreignkey"
    )
    for name in ("not_merged_into_self", "hidden_reason_valid", "status_valid"):
        op.drop_constraint(op.f(f"ck_tc_clauses_{name}"), "tc_clauses", type_="check")
    for column in (
        "curated",
        "own_usage_count",
        "review_note",
        "needs_review",
        "merged_into_id",
        "hidden_reason",
        "status",
    ):
        op.drop_column("tc_clauses", column)
