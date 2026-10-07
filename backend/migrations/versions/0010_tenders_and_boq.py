"""tenders: register, members, BOQ sections and lines, pricing candidates, client BOQ imports,
the tender T&C list, the per-year tender number sequence, and the auto-pricing threshold.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tender_sequences",
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_tender_sequences")),
    )
    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("site_name", sa.String(length=200), nullable=True),
        sa.Column("site_city", sa.String(length=100), nullable=True),
        sa.Column("site_state", sa.String(length=100), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("lost_reason", sa.Text(), nullable=True),
        sa.Column("lost_to", sa.String(length=200), nullable=True),
        sa.Column(
            "quoted_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("tc_template_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "status IN ('draft', 'submitted', 'won', 'lost', 'dropped')",
            name=op.f("ck_tenders_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_tenders_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tenders_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_tenders_owner_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tc_template_id"],
            ["tc_templates.id"],
            name=op.f("fk_tenders_tc_template_id_tc_templates"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenders")),
        sa.UniqueConstraint("code", name=op.f("uq_tenders_code")),
    )
    op.create_index(op.f("ix_tenders_client_id"), "tenders", ["client_id"], unique=False)
    op.create_index(op.f("ix_tenders_owner_id"), "tenders", ["owner_id"], unique=False)
    op.create_index(op.f("ix_tenders_status"), "tenders", ["status"], unique=False)
    op.create_table(
        "boq_imports",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=400), nullable=False),
        sa.Column("sheet", sa.String(length=200), nullable=True),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("column_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_boq_imports_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_boq_imports_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_imports")),
    )
    op.create_index(op.f("ix_boq_imports_tender_id"), "boq_imports", ["tender_id"], unique=False)
    op.create_table(
        "boq_sections",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_boq_sections_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_boq_sections_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_sections")),
    )
    op.create_index(op.f("ix_boq_sections_tender_id"), "boq_sections", ["tender_id"], unique=False)
    op.create_table(
        "tender_members",
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tender_members_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_tender_members_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tender_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tender_id", "user_id", name=op.f("pk_tender_members")),
    )
    op.create_index(op.f("ix_tender_members_user_id"), "tender_members", ["user_id"], unique=False)
    op.create_table(
        "tender_tc",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("clause_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text_override", sa.Text(), nullable=True),
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
            "clause_id IS NOT NULL OR text_override IS NOT NULL", name=op.f("ck_tender_tc_has_text")
        ),
        sa.ForeignKeyConstraint(
            ["clause_id"],
            ["tc_clauses.id"],
            name=op.f("fk_tender_tc_clause_id_tc_clauses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tender_tc_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_tender_tc_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_tc")),
    )
    op.create_index(op.f("ix_tender_tc_tender_id"), "tender_tc", ["tender_id"], unique=False)
    op.create_table(
        "boq_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("client_item_no", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=10), nullable=True),
        sa.Column("unit_raw", sa.String(length=50), nullable=True),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("qty_note", sa.String(length=5), nullable=True),
        sa.Column("client_product", sa.Text(), nullable=True),
        sa.Column("client_remarks", sa.Text(), nullable=True),
        sa.Column("client_file_rate", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=True),
        sa.Column("system_id", sa.Integer(), nullable=True),
        sa.Column("library_item_id", sa.BigInteger(), nullable=True),
        sa.Column("cost_rate", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("margin_percent", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("rate", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("suggestion_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("our_remarks", sa.Text(), nullable=True),
        sa.Column("our_product", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="unpriced", nullable=False),
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
            "qty_note IS NULL OR qty_note IN ('QRO', 'NQ')",
            name=op.f("ck_boq_lines_qty_note_valid"),
        ),
        sa.CheckConstraint(
            "source IS NULL OR source IN ('system', 'library', 'manual')",
            name=op.f("ck_boq_lines_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('unpriced', 'suggested', 'priced', 'not_quoted')",
            name=op.f("ck_boq_lines_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_boq_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["library_item_id"],
            ["library_items.id"],
            name=op.f("fk_boq_lines_library_item_id_library_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["boq_sections.id"],
            name=op.f("fk_boq_lines_section_id_boq_sections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_boq_lines_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_boq_lines_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["unit"], ["units.code"], name=op.f("fk_boq_lines_unit_units")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_lines")),
    )
    op.create_index(op.f("ix_boq_lines_section_id"), "boq_lines", ["section_id"], unique=False)
    op.create_index(
        "ix_boq_lines_tender_id_sort_order", "boq_lines", ["tender_id", "sort_order"], unique=False
    )
    op.create_table(
        "boq_line_candidates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("line_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cost_rate", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("margin_percent", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
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
            "source IN ('system', 'library')", name=op.f("ck_boq_line_candidates_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_boq_line_candidates_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["boq_lines.id"],
            name=op.f("fk_boq_line_candidates_line_id_boq_lines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_line_candidates")),
    )
    op.create_index(
        op.f("ix_boq_line_candidates_line_id"), "boq_line_candidates", ["line_id"], unique=False
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "pricing_threshold",
            sa.Numeric(precision=4, scale=3),
            server_default="0.55",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("company_profile", "pricing_threshold")
    op.drop_index(op.f("ix_boq_line_candidates_line_id"), table_name="boq_line_candidates")
    op.drop_table("boq_line_candidates")
    op.drop_index("ix_boq_lines_tender_id_sort_order", table_name="boq_lines")
    op.drop_index(op.f("ix_boq_lines_section_id"), table_name="boq_lines")
    op.drop_table("boq_lines")
    op.drop_index(op.f("ix_tender_tc_tender_id"), table_name="tender_tc")
    op.drop_table("tender_tc")
    op.drop_index(op.f("ix_tender_members_user_id"), table_name="tender_members")
    op.drop_table("tender_members")
    op.drop_index(op.f("ix_boq_sections_tender_id"), table_name="boq_sections")
    op.drop_table("boq_sections")
    op.drop_index(op.f("ix_boq_imports_tender_id"), table_name="boq_imports")
    op.drop_table("boq_imports")
    op.drop_index(op.f("ix_tenders_status"), table_name="tenders")
    op.drop_index(op.f("ix_tenders_owner_id"), table_name="tenders")
    op.drop_index(op.f("ix_tenders_client_id"), table_name="tenders")
    op.drop_table("tenders")
    op.drop_table("tender_sequences")
