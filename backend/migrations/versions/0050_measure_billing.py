# ruff: noqa: E501
"""Measurement and RA bills from the drawing: measure areas (arcs kept), shared edges and their
answer, how each work-order item is measured, measurement sheets and their lines, what was billed
per area, item and layer; the work-order line's per-layer rate, layers and SAC; the RA bill's
proforma (number, date, the order it is billed against) and old bills read from Excel.

Revision ID: 0050
Revises: 0049
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXACT = sa.Numeric(24, 10)
JSON = postgresql.JSONB(astext_type=sa.Text())


def _tracked() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    ]


def upgrade() -> None:
    op.add_column("client_work_order_lines", sa.Column("per_layer", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("client_work_order_lines", sa.Column("layers", sa.Integer(), server_default="1", nullable=False))
    op.add_column("client_work_order_lines", sa.Column("sac", sa.String(length=8), nullable=True))
    op.add_column("ra_bills", sa.Column("proforma_no", sa.String(length=20), nullable=True))
    op.add_column("ra_bills", sa.Column("proforma_on", sa.Date(), nullable=True))
    op.add_column("ra_bills", sa.Column("order_basis", sa.String(length=6), nullable=True))
    op.add_column("ra_bills", sa.Column("verbal_by", sa.String(length=200), nullable=True))
    op.add_column("ra_bills", sa.Column("verbal_on", sa.Date(), nullable=True))
    op.add_column("ra_bills", sa.Column("imported", sa.Boolean(), server_default="false", nullable=False))
    op.create_unique_constraint(op.f("uq_ra_bills_proforma_no"), "ra_bills", ["proforma_no"])
    op.create_check_constraint(op.f("ck_ra_bills_order_basis_valid"), "ra_bills", "order_basis IS NULL OR order_basis IN ('wo', 'verbal')")

    op.create_table(
        "measure_areas",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cad_file_id", sa.Integer(), sa.ForeignKey("cad_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=6), server_default="area", nullable=False),
        sa.Column("outline", JSON, nullable=False),
        sa.Column("picked", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("handle", sa.String(length=20), nullable=True),
        sa.Column("layer", sa.String(length=200), nullable=True),
        sa.Column("area_sqm", EXACT, nullable=False),
        sa.Column("periphery_m", EXACT, nullable=False),
        sa.Column("trim_with", JSON, server_default="[]", nullable=False),
        sa.Column("net_area_sqm", EXACT, nullable=False),
        sa.Column("net_periphery_m", EXACT, nullable=False),
        sa.Column("height_mm", EXACT, nullable=True),
        sa.Column("height_source", sa.Text(), nullable=True),
        sa.Column("height2_mm", EXACT, nullable=True),
        sa.Column("height2_source", sa.Text(), nullable=True),
        sa.Column("wall_top_mm", EXACT, server_default="250", nullable=False),
        sa.Column("rise_mm", EXACT, nullable=True),
        sa.Column("run_mm", EXACT, nullable=True),
        sa.Column("slope_source", sa.Text(), nullable=True),
        sa.Column("counts", JSON, server_default="{}", nullable=False),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("site_nodes.id", ondelete="SET NULL"), nullable=True),
        *_tracked(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_areas")),
        sa.UniqueConstraint("site_id", "code", name=op.f("uq_measure_areas_site_id")),
        sa.CheckConstraint("kind IN ('area', 'slope')", name=op.f("ck_measure_areas_kind_valid")),
    )
    op.create_index(op.f("ix_measure_areas_site_id"), "measure_areas", ["site_id"])

    op.create_table(
        "measure_edges",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("area_a_id", sa.Integer(), sa.ForeignKey("measure_areas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("area_b_id", sa.Integer(), sa.ForeignKey("measure_areas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("length_m", EXACT, nullable=False),
        sa.Column("line", JSON, nullable=False),
        sa.Column("answer", sa.String(length=5), nullable=True),
        sa.Column("weir_mm", EXACT, nullable=True),
        sa.Column("answered_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_edges")),
        sa.UniqueConstraint("area_a_id", "area_b_id", "seq", name=op.f("uq_measure_edges_area_a_id")),
        sa.CheckConstraint("answer IS NULL OR answer IN ('both', 'open', 'weir')", name=op.f("ck_measure_edges_answer_valid")),
        sa.CheckConstraint("answer <> 'weir' OR weir_mm IS NOT NULL", name=op.f("ck_measure_edges_weir_has_height")),
    )
    op.create_index(op.f("ix_measure_edges_site_id"), "measure_edges", ["site_id"])

    op.create_table(
        "measure_items",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wo_line_id", sa.Integer(), sa.ForeignKey("client_work_order_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parts", JSON, server_default="[]", nullable=False),
        sa.Column("count_of", sa.String(length=200), nullable=True),
        sa.Column("layers", sa.Integer(), server_default="1", nullable=False),
        sa.Column("layers_answer", sa.String(length=4), nullable=True),
        sa.Column("areas", JSON, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_items")),
        sa.UniqueConstraint("site_id", "wo_line_id", name=op.f("uq_measure_items_site_id")),
        sa.CheckConstraint("layers >= 1", name=op.f("ck_measure_items_layers_positive")),
        sa.CheckConstraint("layers_answer IS NULL OR layers_answer IN ('each', 'once')", name=op.f("ck_measure_items_layers_answer_valid")),
    )
    op.create_index(op.f("ix_measure_items_site_id"), "measure_items", ["site_id"])

    op.create_table(
        "measure_sheets",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="draft", nullable=False),
        sa.Column("not_done", JSON, server_default="[]", nullable=False),
        sa.Column("set_id", sa.Integer(), sa.ForeignKey("measurement_sets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ra_bill_id", sa.Integer(), sa.ForeignKey("ra_bills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("imported_from", sa.String(length=300), nullable=True),
        sa.Column("import_skipped", JSON, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_tracked(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_sheets")),
        sa.UniqueConstraint("site_id", "seq", name=op.f("uq_measure_sheets_site_id")),
        sa.UniqueConstraint("code", name=op.f("uq_measure_sheets_code")),
        sa.CheckConstraint("status IN ('draft', 'sent', 'approved', 'billed')", name=op.f("ck_measure_sheets_status_valid")),
    )
    op.create_index(op.f("ix_measure_sheets_site_id"), "measure_sheets", ["site_id"])

    op.create_table(
        "measure_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("measure_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("measure_areas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("edge_id", sa.Integer(), sa.ForeignKey("measure_edges.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wo_line_id", sa.Integer(), sa.ForeignKey("client_work_order_lines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_no", sa.String(length=30), nullable=True),
        sa.Column("layer", sa.Integer(), server_default="1", nullable=False),
        sa.Column("part", sa.String(length=6), nullable=True),
        sa.Column("particulars", sa.Text(), nullable=False),
        sa.Column("no", EXACT, nullable=True),
        sa.Column("length_m", EXACT, nullable=True),
        sa.Column("width_m", EXACT, nullable=True),
        sa.Column("height_m", EXACT, nullable=True),
        sa.Column("qty", EXACT, nullable=True),
        sa.Column("total", sa.Numeric(16, 3), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_lines")),
        sa.CheckConstraint("kind IN ('area', 'line', 'deduction', 'not_done')", name=op.f("ck_measure_lines_kind_valid")),
    )
    op.create_index(op.f("ix_measure_lines_sheet_id"), "measure_lines", ["sheet_id"])

    op.create_table(
        "measure_billed",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("measure_areas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wo_line_id", sa.Integer(), sa.ForeignKey("client_work_order_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layer", sa.Integer(), nullable=False),
        sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("measure_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measure_billed")),
        sa.UniqueConstraint("area_id", "wo_line_id", "layer", name=op.f("uq_measure_billed_area_id")),
    )
    op.create_index(op.f("ix_measure_billed_sheet_id"), "measure_billed", ["sheet_id"])


def downgrade() -> None:
    for t in ("measure_billed", "measure_lines", "measure_sheets", "measure_items", "measure_edges", "measure_areas"):
        op.drop_table(t)
    op.drop_constraint(op.f("ck_ra_bills_order_basis_valid"), "ra_bills", type_="check")
    op.drop_constraint(op.f("uq_ra_bills_proforma_no"), "ra_bills", type_="unique")
    for c in ("imported", "verbal_on", "verbal_by", "order_basis", "proforma_on", "proforma_no"):
        op.drop_column("ra_bills", c)
    for c in ("sac", "layers", "per_layer"):
        op.drop_column("client_work_order_lines", c)
