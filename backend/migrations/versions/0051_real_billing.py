# ruff: noqa: E501
"""Measuring the billing team's real drawings: an outline drawn round but not closed (its gap and
its length as drawn), a slope's own length, a shared edge drawn as its own line (and "not a shared
edge" for outlines drawn close that are not one wall), an item's parts
not done in an area and counts made on site, and study sheets (another way of measuring, kept to
compare, never sent or billed) with their own options and item total lines.

Revision ID: 0051
Revises: 0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXACT = sa.Numeric(24, 10)
JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("measure_areas", sa.Column("closed_gap_mm", EXACT, nullable=True))
    op.add_column("measure_areas", sa.Column("drawn_length_m", EXACT, nullable=True))
    op.add_column("measure_areas", sa.Column("slope_mm", EXACT, nullable=True))
    op.add_column("measure_edges", sa.Column("source", sa.Text(), nullable=True))
    op.add_column("measure_edges", sa.Column("manual", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("measure_items", sa.Column("skip", JSON, server_default="{}", nullable=False))
    op.add_column("measure_items", sa.Column("manual", JSON, server_default="{}", nullable=False))
    op.add_column("measure_sheets", sa.Column("options", JSON, server_default="{}", nullable=False))
    op.drop_constraint(op.f("ck_measure_sheets_status_valid"), "measure_sheets", type_="check")
    op.create_check_constraint(op.f("ck_measure_sheets_status_valid"), "measure_sheets", "status IN ('draft', 'sent', 'approved', 'billed', 'study')")
    op.drop_constraint(op.f("ck_measure_lines_kind_valid"), "measure_lines", type_="check")
    op.create_check_constraint(op.f("ck_measure_lines_kind_valid"), "measure_lines", "kind IN ('area', 'line', 'deduction', 'not_done', 'total')")
    op.drop_constraint(op.f("ck_measure_edges_answer_valid"), "measure_edges", type_="check")
    op.create_check_constraint(op.f("ck_measure_edges_answer_valid"), "measure_edges", "answer IS NULL OR answer IN ('both', 'open', 'weir', 'none')")


def downgrade() -> None:
    op.execute("UPDATE measure_edges SET answer = NULL WHERE answer = 'none'")
    op.drop_constraint(op.f("ck_measure_edges_answer_valid"), "measure_edges", type_="check")
    op.create_check_constraint(op.f("ck_measure_edges_answer_valid"), "measure_edges", "answer IS NULL OR answer IN ('both', 'open', 'weir')")
    op.execute("DELETE FROM measure_lines WHERE kind = 'total'")
    op.execute("DELETE FROM measure_sheets WHERE status = 'study'")
    op.drop_constraint(op.f("ck_measure_lines_kind_valid"), "measure_lines", type_="check")
    op.create_check_constraint(op.f("ck_measure_lines_kind_valid"), "measure_lines", "kind IN ('area', 'line', 'deduction', 'not_done')")
    op.drop_constraint(op.f("ck_measure_sheets_status_valid"), "measure_sheets", type_="check")
    op.create_check_constraint(op.f("ck_measure_sheets_status_valid"), "measure_sheets", "status IN ('draft', 'sent', 'approved', 'billed')")
    op.drop_column("measure_sheets", "options")
    for c in ("manual", "skip"):
        op.drop_column("measure_items", c)
    for c in ("manual", "source"):
        op.drop_column("measure_edges", c)
    for c in ("slope_mm", "drawn_length_m", "closed_gap_mm"):
        op.drop_column("measure_areas", c)
