"""rate library: exclusion and competitor flags, manual overrides, merging

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _flag(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), server_default="false", nullable=False)


def upgrade() -> None:
    # items
    op.add_column("library_items", _flag("is_excluded"))
    op.add_column("library_items", sa.Column("excluded_reason", sa.String(200), nullable=True))
    # 'rule' = set by the importer's rules; 'manual' = set by a person, which the importer keeps
    op.add_column("library_items", sa.Column("exclusion_source", sa.String(10), nullable=True))
    op.add_column("library_items", _flag("is_competitor"))
    op.add_column("library_items", _flag("unit_manual"))
    op.add_column("library_items", sa.Column("merged_into_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "library_items", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True)
    )
    # the statistics exactly as the source sheet gave them, so they can always be restored
    op.add_column(
        "library_items",
        sa.Column("source_stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("library_items", _flag("stats_from_lines"))
    op.create_foreign_key(
        op.f("fk_library_items_merged_into_id_library_items"),
        "library_items",
        "library_items",
        ["merged_into_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_library_items_exclusion_source_valid"),
        "library_items",
        "exclusion_source IS NULL OR exclusion_source IN ('rule', 'manual')",
    )
    op.create_check_constraint(
        op.f("ck_library_items_not_merged_into_self"),
        "library_items",
        "merged_into_id IS NULL OR merged_into_id <> id",
    )
    op.create_index(op.f("ix_library_items_merged_into_id"), "library_items", ["merged_into_id"])

    # lines
    op.add_column("library_lines", _flag("is_excluded"))
    op.add_column("library_lines", sa.Column("excluded_reason", sa.String(200), nullable=True))
    op.add_column("library_lines", _flag("is_competitor"))


def downgrade() -> None:
    for column in ("is_competitor", "excluded_reason", "is_excluded"):
        op.drop_column("library_lines", column)
    op.drop_index(op.f("ix_library_items_merged_into_id"), table_name="library_items")
    op.drop_constraint(
        op.f("ck_library_items_not_merged_into_self"), "library_items", type_="check"
    )
    op.drop_constraint(
        op.f("ck_library_items_exclusion_source_valid"), "library_items", type_="check"
    )
    op.drop_constraint(
        op.f("fk_library_items_merged_into_id_library_items"), "library_items", type_="foreignkey"
    )
    for column in (
        "stats_from_lines",
        "source_stats",
        "merged_at",
        "merged_into_id",
        "unit_manual",
        "is_competitor",
        "exclusion_source",
        "excluded_reason",
        "is_excluded",
    ):
        op.drop_column("library_items", column)
