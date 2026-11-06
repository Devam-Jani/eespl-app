# ruff: noqa: E501  (the column lists read better unwrapped)
"""Spec products (Prompt 39a): the data sheets (TDS) with their facts, a BOQ line's key points and
the option picked for it, the consumption master's change history; a work item's use areas and
system type, a brand option's formulation (mix design and thickness); tds.import and
consumption.edit for the super admin and planning.

The downgrade drops the tables and columns (the data sheets' files under media/tds stay).

Revision ID: 0063f
Revises: 0062e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063f"
down_revision: str | None = "0062e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMS = {
    "tds.import": "Import product data sheets (TDS) and edit their facts",
    "consumption.edit": "Change the consumption master: work items, brand options, consumption",
}
ROLES = ("super_admin", "planning")


def _user(table: str, col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], ["users.id"], name=op.f(f"fk_{table}_{col}_users"), ondelete="SET NULL"
    )


def upgrade() -> None:
    op.create_table(
        "tds_imports",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="preview", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('preview', 'saved', 'discarded')", name=op.f("ck_tds_imports_status_valid")),
        _user("tds_imports", "created_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tds_imports")),
    )  # fmt: skip
    op.create_table(
        "tds_docs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("file_name", sa.String(length=300), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("stored_path", sa.String(length=400), nullable=True),
        sa.Column("pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="preview", nullable=False),
        sa.Column("needs_reading", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("read_error", sa.String(length=300), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("match", sa.String(length=8), server_default="create", nullable=False),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("replaces_id", sa.Integer(), nullable=True),
        sa.Column("replace_confirmed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("pdf_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("imported_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('preview', 'saved', 'replaced', 'duplicate', 'skipped')", name=op.f("ck_tds_docs_status_valid")),
        sa.ForeignKeyConstraint(["import_id"], ["tds_imports.id"], name=op.f("fk_tds_docs_import_id_tds_imports"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_tds_docs_product_id_products"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["tds_docs.id"], name=op.f("fk_tds_docs_duplicate_of_id_tds_docs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["replaces_id"], ["tds_docs.id"], name=op.f("fk_tds_docs_replaces_id_tds_docs"), ondelete="SET NULL"),
        _user("tds_docs", "imported_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tds_docs")),
    )  # fmt: skip
    for col in ("import_id", "sha256", "product_id"):
        op.create_index(f"ix_tds_docs_{col}", "tds_docs", [col])
    op.create_table(
        "tds_facts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=30), nullable=True),
        sa.Column("lo", sa.Numeric(14, 6), nullable=True),
        sa.Column("hi", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("standard", sa.String(length=40), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("sentence", sa.Text(), nullable=True),
        sa.Column("per_coat", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("coats", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=6), server_default="rule", nullable=False),
        sa.Column("checked_by", sa.Uuid(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("source IN ('rule', 'ai', 'manual')", name=op.f("ck_tds_facts_source_valid")),
        sa.ForeignKeyConstraint(["doc_id"], ["tds_docs.id"], name=op.f("fk_tds_facts_doc_id_tds_docs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_tds_facts_product_id_products"), ondelete="CASCADE"),
        _user("tds_facts", "checked_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tds_facts")),
    )  # fmt: skip
    op.create_index("ix_tds_facts_doc_id", "tds_facts", ["doc_id"])
    op.create_index("ix_tds_facts_product_id", "tds_facts", ["product_id"])
    op.create_table(
        "spec_points",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("boq_line_id", sa.BigInteger(), nullable=True),
        sa.Column("quotation_line_id", sa.Integer(), nullable=True),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("chips", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("(boq_line_id IS NOT NULL) <> (quotation_line_id IS NOT NULL)", name=op.f("ck_spec_points_one_line")),
        sa.ForeignKeyConstraint(["boq_line_id"], ["boq_lines.id"], name=op.f("fk_spec_points_boq_line_id_boq_lines"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quotation_line_id"], ["quotation_lines.id"], name=op.f("fk_spec_points_quotation_line_id_quotation_lines"), ondelete="CASCADE"),
        _user("spec_points", "updated_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_points")),
        sa.UniqueConstraint("boq_line_id", name=op.f("uq_spec_points_boq_line_id")),
        sa.UniqueConstraint("quotation_line_id", name=op.f("uq_spec_points_quotation_line_id")),
    )  # fmt: skip
    op.create_table(
        "spec_picks",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("boq_line_id", sa.BigInteger(), nullable=True),
        sa.Column("quotation_line_id", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), server_default="1", nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("picked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("picked_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("(boq_line_id IS NOT NULL) <> (quotation_line_id IS NOT NULL)", name=op.f("ck_spec_picks_one_line")),
        sa.CheckConstraint("rank IN (1, 2)", name=op.f("ck_spec_picks_rank_valid")),
        sa.ForeignKeyConstraint(["boq_line_id"], ["boq_lines.id"], name=op.f("fk_spec_picks_boq_line_id_boq_lines"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quotation_line_id"], ["quotation_lines.id"], name=op.f("fk_spec_picks_quotation_line_id_quotation_lines"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], name=op.f("fk_spec_picks_system_id_systems"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["option_id"], ["system_options.id"], name=op.f("fk_spec_picks_option_id_system_options"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["rate_groups.id"], name=op.f("fk_spec_picks_group_id_rate_groups"), ondelete="SET NULL"),
        _user("spec_picks", "picked_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_picks")),
    )  # fmt: skip
    op.create_index("ix_spec_picks_boq_line_id", "spec_picks", ["boq_line_id"])
    op.create_index("ix_spec_picks_quotation_line_id", "spec_picks", ["quotation_line_id"])
    op.create_table(
        "consumption_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("system_id", sa.Integer(), nullable=True),
        sa.Column("option_id", sa.Integer(), nullable=True),
        sa.Column("component_id", sa.Integer(), nullable=True),
        sa.Column("what", sa.String(length=200), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("old", sa.Text(), nullable=True),
        sa.Column("new", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], name=op.f("fk_consumption_changes_system_id_systems"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["option_id"], ["system_options.id"], name=op.f("fk_consumption_changes_option_id_system_options"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["component_id"], ["system_components.id"], name=op.f("fk_consumption_changes_component_id_system_components"), ondelete="SET NULL"),
        _user("consumption_changes", "changed_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consumption_changes")),
    )  # fmt: skip
    op.create_index("ix_consumption_changes_system_id", "consumption_changes", ["system_id"])

    op.add_column(
        "systems",
        sa.Column("area_keys", sa.ARRAY(sa.String(length=30)), server_default="{}", nullable=False),
    )
    op.add_column("systems", sa.Column("spec_type", sa.String(length=30), nullable=True))
    op.add_column("system_options", sa.Column("mix_design_id", sa.Integer(), nullable=True))
    op.add_column("system_options", sa.Column("mix_thickness_mm", sa.Numeric(8, 2), nullable=True))
    op.create_foreign_key(
        op.f("fk_system_options_mix_design_id_mix_designs"), "system_options", "mix_designs",
        ["mix_design_id"], ["id"], ondelete="SET NULL",
    )  # fmt: skip

    for code, text in PERMS.items():
        op.execute(
            f"INSERT INTO permissions (code, module, description) VALUES ('{code}', 'masters', '{text}')"
        )
        for role in ROLES:
            op.execute(
                "INSERT INTO role_permissions (role_id, permission_code, scope) "
                f"SELECT id, '{code}', 'all' FROM roles WHERE code = '{role}'"
            )


def downgrade() -> None:
    for code in PERMS:
        op.execute(f"DELETE FROM role_permissions WHERE permission_code = '{code}'")
        op.execute(f"DELETE FROM permissions WHERE code = '{code}'")
    op.drop_constraint(
        op.f("fk_system_options_mix_design_id_mix_designs"), "system_options", type_="foreignkey"
    )
    op.drop_column("system_options", "mix_thickness_mm")
    op.drop_column("system_options", "mix_design_id")
    op.drop_column("systems", "spec_type")
    op.drop_column("systems", "area_keys")
    op.drop_table("consumption_changes")
    op.drop_table("spec_picks")
    op.drop_table("spec_points")
    op.drop_table("tds_facts")
    op.drop_table("tds_docs")
    op.drop_table("tds_imports")
