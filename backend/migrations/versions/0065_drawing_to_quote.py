# ruff: noqa: E501  (the column lists read better unwrapped)
"""From the drawing to the quotation (Prompt 39): an area's outline from the drawing's closed
polyline (or traced), its cut-outs and its own upturn; the runs of "Make quotation from drawing"
with their area types, picks and the areas left out; the areas behind each quotation line; the
review grid's changed cells; drawquote.make for the super admin, planning and the estimator.

The downgrade drops the tables and columns (the quotations and workings made stay).

Revision ID: 0065h
Revises: 0064g
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0065h"
down_revision: str | None = "0064g"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CODE = "drawquote.make"
ROLES = ("super_admin", "planning", "estimator")


def upgrade() -> None:
    op.create_table(
        "draw_quotes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("cad_file_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=4), server_default="sqm", nullable=False),
        sa.Column("status", sa.String(length=8), server_default="picking", nullable=False),
        sa.Column("quotation_id", sa.Integer(), nullable=True),
        sa.Column("previous_id", sa.Integer(), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('picking', 'made')", name=op.f("ck_draw_quotes_status_valid")
        ),
        sa.CheckConstraint("unit IN ('sqm', 'sqft')", name=op.f("ck_draw_quotes_unit_valid")),
        sa.ForeignKeyConstraint(
            ["cad_file_id"],
            ["cad_files.id"],
            name=op.f("fk_draw_quotes_cad_file_id_cad_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_draw_quotes_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_draw_quotes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_id"],
            ["draw_quotes.id"],
            name=op.f("fk_draw_quotes_previous_id_draw_quotes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["quotation_id"],
            ["quotations.id"],
            name=op.f("fk_draw_quotes_quotation_id_quotations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_draw_quotes_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draw_quotes")),
    )
    op.create_index(
        op.f("ix_draw_quotes_cad_file_id"), "draw_quotes", ["cad_file_id"], unique=False
    )
    op.create_index(op.f("ix_draw_quotes_site_id"), "draw_quotes", ["site_id"], unique=False)
    op.create_table(
        "quote_line_areas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("quotation_line_id", sa.Integer(), nullable=False),
        sa.Column("cad_area_id", sa.BigInteger(), nullable=True),
        sa.Column("cad_file_id", sa.Integer(), nullable=True),
        sa.Column("area_key", sa.String(length=160), nullable=False),
        sa.Column("area_name", sa.String(length=200), nullable=False),
        sa.Column("floor", sa.String(length=200), nullable=True),
        sa.Column("floor_sqm", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "cutout_sqm", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "periphery_m", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "upturn_m", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("upturn_from", sa.String(length=40), nullable=True),
        sa.Column("sunk_m", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False),
        sa.Column(
            "wall_length_m", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "wall_height_m", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("total_sqm", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cad_area_id"],
            ["cad_areas.id"],
            name=op.f("fk_quote_line_areas_cad_area_id_cad_areas"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cad_file_id"],
            ["cad_files.id"],
            name=op.f("fk_quote_line_areas_cad_file_id_cad_files"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["quotation_line_id"],
            ["quotation_lines.id"],
            name=op.f("fk_quote_line_areas_quotation_line_id_quotation_lines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_line_areas")),
    )
    op.create_index(
        op.f("ix_quote_line_areas_quotation_line_id"),
        "quote_line_areas",
        ["quotation_line_id"],
        unique=False,
    )
    op.create_table(
        "draw_quote_edits",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=False),
        sa.Column("calculated", sa.Text(), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('qty', 'consumption', 'price', 'freight', 'wastage', 'labour', 'margin')",
            name=op.f("ck_draw_quote_edits_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["by"], ["users.id"], name=op.f("fk_draw_quote_edits_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["draw_quotes.id"],
            name=op.f("fk_draw_quote_edits_run_id_draw_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draw_quote_edits")),
        sa.UniqueConstraint("run_id", "kind", "ref_id", name=op.f("uq_draw_quote_edits_run_id")),
    )
    op.create_index(
        op.f("ix_draw_quote_edits_run_id"), "draw_quote_edits", ["run_id"], unique=False
    )
    op.create_table(
        "draw_quote_exclusions",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("cad_area_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["by"],
            ["users.id"],
            name=op.f("fk_draw_quote_exclusions_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cad_area_id"],
            ["cad_areas.id"],
            name=op.f("fk_draw_quote_exclusions_cad_area_id_cad_areas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["draw_quotes.id"],
            name=op.f("fk_draw_quote_exclusions_run_id_draw_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draw_quote_exclusions")),
        sa.UniqueConstraint("run_id", "cad_area_id", name=op.f("uq_draw_quote_exclusions_run_id")),
    )
    op.create_index(
        op.f("ix_draw_quote_exclusions_run_id"), "draw_quote_exclusions", ["run_id"], unique=False
    )
    op.create_table(
        "draw_quote_items",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("area_type_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("spec_text", sa.Text(), nullable=True),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column("quotation_item_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["area_type_id"],
            ["area_types.id"],
            name=op.f("fk_draw_quote_items_area_type_id_area_types"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["quotation_item_id"],
            ["quotation_items.id"],
            name=op.f("fk_draw_quote_items_quotation_item_id_quotation_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["draw_quotes.id"],
            name=op.f("fk_draw_quote_items_run_id_draw_quotes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draw_quote_items")),
    )
    op.create_index(
        op.f("ix_draw_quote_items_run_id"), "draw_quote_items", ["run_id"], unique=False
    )
    op.create_table(
        "draw_quote_picks",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=True),
        sa.Column("option_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("consumption", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quotation_line_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(system_id IS NOT NULL) OR (product_id IS NOT NULL)",
            name=op.f("ck_draw_quote_picks_what_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["rate_groups.id"],
            name=op.f("fk_draw_quote_picks_group_id_rate_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["draw_quote_items.id"],
            name=op.f("fk_draw_quote_picks_item_id_draw_quote_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["system_options.id"],
            name=op.f("fk_draw_quote_picks_option_id_system_options"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_draw_quote_picks_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["quotation_line_id"],
            ["quotation_lines.id"],
            name=op.f("fk_draw_quote_picks_quotation_line_id_quotation_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_draw_quote_picks_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draw_quote_picks")),
    )
    op.create_index(
        op.f("ix_draw_quote_picks_item_id"), "draw_quote_picks", ["item_id"], unique=False
    )
    op.add_column("cad_areas", sa.Column("outline_source", sa.String(length=8), nullable=True))
    op.add_column(
        "cad_areas",
        sa.Column(
            "holes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "cad_areas", sa.Column("holes_sqm", sa.Numeric(precision=12, scale=3), nullable=True)
    )
    op.add_column(
        "cad_areas",
        sa.Column("holes_perimeter_m", sa.Numeric(precision=12, scale=3), nullable=True),
    )
    op.add_column(
        "cad_areas", sa.Column("upturn_mm", sa.Numeric(precision=8, scale=2), nullable=True)
    )
    op.execute(
        f"INSERT INTO permissions (code, module, description) VALUES ('{CODE}', 'sites', 'Make a quotation and its rate working from a site drawing')"
    )
    for role in ROLES:
        op.execute(
            f"INSERT INTO role_permissions (role_id, permission_code, scope) SELECT id, '{CODE}', 'all' FROM roles WHERE code = '{role}'"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{CODE}'")
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}'")
    op.drop_column("cad_areas", "upturn_mm")
    op.drop_column("cad_areas", "holes_perimeter_m")
    op.drop_column("cad_areas", "holes_sqm")
    op.drop_column("cad_areas", "holes")
    op.drop_column("cad_areas", "outline_source")
    op.drop_index(op.f("ix_draw_quote_picks_item_id"), table_name="draw_quote_picks")
    op.drop_table("draw_quote_picks")
    op.drop_index(op.f("ix_draw_quote_items_run_id"), table_name="draw_quote_items")
    op.drop_table("draw_quote_items")
    op.drop_index(op.f("ix_draw_quote_exclusions_run_id"), table_name="draw_quote_exclusions")
    op.drop_table("draw_quote_exclusions")
    op.drop_index(op.f("ix_draw_quote_edits_run_id"), table_name="draw_quote_edits")
    op.drop_table("draw_quote_edits")
    op.drop_index(op.f("ix_quote_line_areas_quotation_line_id"), table_name="quote_line_areas")
    op.drop_table("quote_line_areas")
    op.drop_index(op.f("ix_draw_quotes_site_id"), table_name="draw_quotes")
    op.drop_index(op.f("ix_draw_quotes_cad_file_id"), table_name="draw_quotes")
    op.drop_table("draw_quotes")
