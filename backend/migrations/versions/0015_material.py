"""material: stores (with the Ethios Godown and a store per open site), the stock ledger,
indents, RFQs, purchase orders, GRNs, transfers, site issues, freight; purchase settings; the
indent / po / grn / store permissions, which replace the M0 indent placeholders.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_sequences",
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("kind", "period", name=op.f("pk_doc_sequences")),
    )
    op.create_table(
        "rfqs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
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
            "status IN ('draft', 'sent', 'closed', 'cancelled')", name=op.f("ck_rfqs_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_rfqs_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rfqs")),
        sa.UniqueConstraint("code", name=op.f("uq_rfqs_code")),
    )
    op.create_table(
        "rfq_vendors",
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("freight", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
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
            name=op.f("fk_rfq_vendors_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"], ["rfqs.id"], name=op.f("fk_rfq_vendors_rfq_id_rfqs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_rfq_vendors_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rfq_id", "vendor_id", name=op.f("pk_rfq_vendors")),
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), server_default="godown", nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("gstin_address_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.CheckConstraint("kind IN ('godown', 'site')", name=op.f("ck_stores_kind_valid")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_stores_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["gstin_address_id"],
            ["company_gstins.id"],
            name=op.f("fk_stores_gstin_address_id_company_gstins"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_stores_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("name", name=op.f("uq_stores_name")),
        sa.UniqueConstraint("site_id", name=op.f("uq_stores_site_id")),
    )
    op.create_table(
        "indents",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("required_by", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=15), server_default="draft", nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
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
            "priority IN ('normal', 'urgent')", name=op.f("ck_indents_priority_valid")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partly_ordered', 'ordered', 'closed', "
            "'rejected', 'cancelled')",
            name=op.f("ck_indents_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_indents_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_indents_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_indents_site_id_sites"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_indents_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indents")),
        sa.UniqueConstraint("code", name=op.f("uq_indents_code")),
    )
    op.create_index(op.f("ix_indents_site_id"), "indents", ["site_id"], unique=False)
    op.create_index(op.f("ix_indents_status"), "indents", ["status"], unique=False)
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=25), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("from_gstin_id", sa.Integer(), nullable=True),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=True),
        sa.Column("po_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery", sa.Date(), nullable=True),
        sa.Column("payment_terms", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("interstate", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "subtotal", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "discount_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("taxable", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("cgst", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("sgst", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("igst", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column(
            "charges_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "round_off", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "grand_total", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
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
        sa.CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'sent', 'partly_received', "
            "'received', 'closed', 'cancelled')",
            name=op.f("ck_purchase_orders_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_purchase_orders_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_purchase_orders_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_gstin_id"],
            ["company_gstins.id"],
            name=op.f("fk_purchase_orders_from_gstin_id_company_gstins"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"],
            ["rfqs.id"],
            name=op.f("fk_purchase_orders_rfq_id_rfqs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_purchase_orders_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_purchase_orders_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
        sa.UniqueConstraint("code", name=op.f("uq_purchase_orders_code")),
    )
    op.create_index(op.f("ix_purchase_orders_status"), "purchase_orders", ["status"], unique=False)
    op.create_index(
        op.f("ix_purchase_orders_store_id"), "purchase_orders", ["store_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_orders_vendor_id"), "purchase_orders", ["vendor_id"], unique=False
    )
    op.create_table(
        "stock_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("ref_type", sa.String(length=15), nullable=False),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "ref_type IN ('grn', 'transfer_out', 'transfer_in', 'issue', 'return', 'adjust', "
            "'opening')",
            name=op.f("ck_stock_ledger_ref_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["by"], ["users.id"], name=op.f("fk_stock_ledger_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_ledger_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_stock_ledger_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_ledger")),
    )
    op.create_index(
        "ix_stock_ledger_store_product", "stock_ledger", ["store_id", "product_id"], unique=False
    )
    op.create_table(
        "transfers",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("from_store_id", sa.Integer(), nullable=False),
        sa.Column("to_store_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("vehicle_no", sa.String(length=30), nullable=True),
        sa.Column("transporter", sa.String(length=200), nullable=True),
        sa.Column(
            "freight_amount", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False
        ),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_by", sa.UUID(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_by", sa.UUID(), nullable=True),
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
            "status IN ('draft', 'dispatched', 'received', 'cancelled')",
            name=op.f("ck_transfers_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_transfers_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dispatched_by"],
            ["users.id"],
            name=op.f("fk_transfers_dispatched_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_store_id"],
            ["stores.id"],
            name=op.f("fk_transfers_from_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by"],
            ["users.id"],
            name=op.f("fk_transfers_received_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_store_id"],
            ["stores.id"],
            name=op.f("fk_transfers_to_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfers")),
        sa.UniqueConstraint("code", name=op.f("uq_transfers_code")),
    )
    op.create_index(
        op.f("ix_transfers_from_store_id"), "transfers", ["from_store_id"], unique=False
    )
    op.create_index(op.f("ix_transfers_status"), "transfers", ["status"], unique=False)
    op.create_index(op.f("ix_transfers_to_store_id"), "transfers", ["to_store_id"], unique=False)
    op.create_table(
        "grns",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=True),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("challan_no", sa.String(length=60), nullable=True),
        sa.Column("invoice_no", sa.String(length=60), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("invoice_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("vehicle_no", sa.String(length=30), nullable=True),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("levels_required", sa.Integer(), server_default="1", nullable=False),
        sa.Column("approved_by_1", sa.UUID(), nullable=True),
        sa.Column("approved_at_1", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_2", sa.UUID(), nullable=True),
        sa.Column("approved_at_2", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
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
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name=op.f("ck_grns_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_1"],
            ["users.id"],
            name=op.f("fk_grns_approved_by_1_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_2"],
            ["users.id"],
            name=op.f("fk_grns_approved_by_2_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_grns_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["po_id"],
            ["purchase_orders.id"],
            name=op.f("fk_grns_po_id_purchase_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_grns_store_id_stores"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_grns_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grns")),
        sa.UniqueConstraint("code", name=op.f("uq_grns_code")),
    )
    op.create_index(op.f("ix_grns_po_id"), "grns", ["po_id"], unique=False)
    op.create_index(op.f("ix_grns_status"), "grns", ["status"], unique=False)
    op.create_index(op.f("ix_grns_store_id"), "grns", ["store_id"], unique=False)
    op.create_table(
        "indent_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("indent_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("free_text", sa.String(length=300), nullable=True),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("base_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("boq_line_id", sa.BigInteger(), nullable=True),
        sa.Column("area_scope_id", sa.BigInteger(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column(
            "ordered_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column(
            "received_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
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
            ["area_scope_id"],
            ["area_scopes.id"],
            name=op.f("fk_indent_lines_area_scope_id_area_scopes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["boq_line_id"],
            ["boq_lines.id"],
            name=op.f("fk_indent_lines_boq_line_id_boq_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_indent_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["indent_id"],
            ["indents.id"],
            name=op.f("fk_indent_lines_indent_id_indents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_indent_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indent_lines")),
    )
    op.create_index(op.f("ix_indent_lines_indent_id"), "indent_lines", ["indent_id"], unique=False)
    op.create_table(
        "po_charges",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "gst_percent", sa.Numeric(precision=5, scale=2), server_default="18", nullable=False
        ),
        sa.Column("add_to_cost", sa.Boolean(), server_default="true", nullable=False),
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
            "kind IN ('freight', 'loading', 'unloading', 'packing', 'other')",
            name=op.f("ck_po_charges_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_po_charges_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["po_id"],
            ["purchase_orders.id"],
            name=op.f("fk_po_charges_po_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_po_charges")),
    )
    op.create_index(op.f("ix_po_charges_po_id"), "po_charges", ["po_id"], unique=False)
    op.create_table(
        "po_indents",
        sa.Column("po_id", sa.Integer(), nullable=False),
        sa.Column("indent_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["indent_id"],
            ["indents.id"],
            name=op.f("fk_po_indents_indent_id_indents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["po_id"],
            ["purchase_orders.id"],
            name=op.f("fk_po_indents_po_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("po_id", "indent_id", name=op.f("pk_po_indents")),
    )
    op.create_table(
        "rfq_indents",
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("indent_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["indent_id"],
            ["indents.id"],
            name=op.f("fk_rfq_indents_indent_id_indents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"], ["rfqs.id"], name=op.f("fk_rfq_indents_rfq_id_rfqs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("rfq_id", "indent_id", name=op.f("pk_rfq_indents")),
    )
    op.create_table(
        "transfer_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("transfer_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty_sent", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("qty_received", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column(
            "shortage_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("shortage_reason", sa.Text(), nullable=True),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=True),
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
            name=op.f("fk_transfer_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_transfer_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transfers.id"],
            name=op.f("fk_transfer_lines_transfer_id_transfers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfer_lines")),
    )
    op.create_index(
        op.f("ix_transfer_lines_transfer_id"), "transfer_lines", ["transfer_id"], unique=False
    )
    op.create_table(
        "freight_entries",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=True),
        sa.Column("grn_id", sa.Integer(), nullable=True),
        sa.Column("transfer_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=15), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "gst_percent", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False
        ),
        sa.Column("transporter", sa.String(length=200), nullable=True),
        sa.Column("vehicle_no", sa.String(length=30), nullable=True),
        sa.Column("from_place", sa.String(length=200), nullable=True),
        sa.Column("to_place", sa.String(length=200), nullable=True),
        sa.Column("bill_no", sa.String(length=60), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
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
            "direction IN ('inbound', 'godown_to_site', 'other')",
            name=op.f("ck_freight_entries_direction_valid"),
        ),
        sa.CheckConstraint(
            "source IN ('po', 'transfer', 'bill')", name=op.f("ck_freight_entries_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_freight_entries_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["grn_id"],
            ["grns.id"],
            name=op.f("fk_freight_entries_grn_id_grns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["po_id"],
            ["purchase_orders.id"],
            name=op.f("fk_freight_entries_po_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_freight_entries_site_id_sites"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transfers.id"],
            name=op.f("fk_freight_entries_transfer_id_transfers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_freight_entries")),
    )
    op.create_index(
        op.f("ix_freight_entries_on_date"), "freight_entries", ["on_date"], unique=False
    )
    op.create_index(
        op.f("ix_freight_entries_site_id"), "freight_entries", ["site_id"], unique=False
    )
    op.create_table(
        "grn_photos",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("grn_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), server_default="material", nullable=False),
        sa.Column("stored_path", sa.String(length=400), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
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
            "kind IN ('challan', 'invoice', 'material')", name=op.f("ck_grn_photos_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_grn_photos_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["grn_id"], ["grns.id"], name=op.f("fk_grn_photos_grn_id_grns"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grn_photos")),
    )
    op.create_index(op.f("ix_grn_photos_grn_id"), "grn_photos", ["grn_id"], unique=False)
    op.create_table(
        "po_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=False),
        sa.Column("indent_line_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("base_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "discount_percent", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "gst_percent", sa.Numeric(precision=5, scale=2), server_default="18", nullable=False
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "received_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
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
            name=op.f("fk_po_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["indent_line_id"],
            ["indent_lines.id"],
            name=op.f("fk_po_lines_indent_line_id_indent_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["po_id"],
            ["purchase_orders.id"],
            name=op.f("fk_po_lines_po_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_po_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_po_lines")),
    )
    op.create_index(op.f("ix_po_lines_po_id"), "po_lines", ["po_id"], unique=False)
    op.create_table(
        "rfq_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("indent_line_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("chosen_vendor_id", sa.Integer(), nullable=True),
        sa.Column("choice_reason", sa.Text(), nullable=True),
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
            ["chosen_vendor_id"],
            ["vendors.id"],
            name=op.f("fk_rfq_lines_chosen_vendor_id_vendors"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_rfq_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["indent_line_id"],
            ["indent_lines.id"],
            name=op.f("fk_rfq_lines_indent_line_id_indent_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_rfq_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"], ["rfqs.id"], name=op.f("fk_rfq_lines_rfq_id_rfqs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rfq_lines")),
    )
    op.create_index(op.f("ix_rfq_lines_rfq_id"), "rfq_lines", ["rfq_id"], unique=False)
    op.create_table(
        "site_issues",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=10), server_default="issue", nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("area_scope_id", sa.BigInteger(), nullable=True),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
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
        sa.CheckConstraint("kind IN ('issue', 'return')", name=op.f("ck_site_issues_kind_valid")),
        sa.ForeignKeyConstraint(
            ["area_scope_id"],
            ["area_scopes.id"],
            name=op.f("fk_site_issues_area_scope_id_area_scopes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_site_issues_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_site_issues_site_id_sites"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_site_issues_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_site_issues_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_issues")),
        sa.UniqueConstraint("code", name=op.f("uq_site_issues_code")),
    )
    op.create_index(op.f("ix_site_issues_site_id"), "site_issues", ["site_id"], unique=False)
    op.create_index(op.f("ix_site_issues_store_id"), "site_issues", ["store_id"], unique=False)
    op.create_table(
        "grn_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("grn_id", sa.Integer(), nullable=False),
        sa.Column("po_line_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("ordered_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("received_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("invoice_qty", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("accepted_qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "rejected_qty", sa.Numeric(precision=14, scale=3), server_default="0", nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("landed_rate", sa.Numeric(precision=14, scale=4), nullable=True),
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
            name=op.f("fk_grn_lines_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["grn_id"], ["grns.id"], name=op.f("fk_grn_lines_grn_id_grns"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["po_line_id"],
            ["po_lines.id"],
            name=op.f("fk_grn_lines_po_line_id_po_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_grn_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grn_lines")),
    )
    op.create_index(op.f("ix_grn_lines_grn_id"), "grn_lines", ["grn_id"], unique=False)
    op.create_table(
        "rfq_quotes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("rfq_line_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "gst_percent", sa.Numeric(precision=5, scale=2), server_default="18", nullable=False
        ),
        sa.Column("freight", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=True),
        sa.Column("valid_till", sa.Date(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
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
            name=op.f("fk_rfq_quotes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_rfq_quotes_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"], ["rfqs.id"], name=op.f("fk_rfq_quotes_rfq_id_rfqs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["rfq_line_id"],
            ["rfq_lines.id"],
            name=op.f("fk_rfq_quotes_rfq_line_id_rfq_lines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_rfq_quotes_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rfq_quotes")),
        sa.UniqueConstraint("rfq_line_id", "vendor_id", name=op.f("uq_rfq_quotes_rfq_line_id")),
    )
    op.create_index(op.f("ix_rfq_quotes_rfq_id"), "rfq_quotes", ["rfq_id"], unique=False)
    op.create_table(
        "site_issue_lines",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["site_issues.id"],
            name=op.f("fk_site_issue_lines_issue_id_site_issues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_site_issue_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_issue_lines")),
    )
    op.create_index(
        op.f("ix_site_issue_lines_issue_id"), "site_issue_lines", ["issue_id"], unique=False
    )
    op.add_column(
        "company_profile",
        sa.Column(
            "po_approval_limit",
            sa.Numeric(precision=14, scale=2),
            server_default="50000",
            nullable=False,
        ),
    )
    op.add_column(
        "company_profile",
        sa.Column("allow_negative_stock", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "company_profile",
        sa.Column("grn_approval_levels", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("company_profile", sa.Column("po_tc_template_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_company_profile_po_tc_template_id_tc_templates"),
        "company_profile",
        "tc_templates",
        ["po_tc_template_id"],
        ["id"],
        ondelete="SET NULL",
    )

    _seed()


def downgrade() -> None:
    _unseed()
    op.drop_constraint(
        op.f("fk_company_profile_po_tc_template_id_tc_templates"),
        "company_profile",
        type_="foreignkey",
    )
    op.drop_column("company_profile", "po_tc_template_id")
    op.drop_column("company_profile", "grn_approval_levels")
    op.drop_column("company_profile", "allow_negative_stock")
    op.drop_column("company_profile", "po_approval_limit")
    op.drop_index(op.f("ix_site_issue_lines_issue_id"), table_name="site_issue_lines")
    op.drop_table("site_issue_lines")
    op.drop_index(op.f("ix_rfq_quotes_rfq_id"), table_name="rfq_quotes")
    op.drop_table("rfq_quotes")
    op.drop_index(op.f("ix_grn_lines_grn_id"), table_name="grn_lines")
    op.drop_table("grn_lines")
    op.drop_index(op.f("ix_site_issues_store_id"), table_name="site_issues")
    op.drop_index(op.f("ix_site_issues_site_id"), table_name="site_issues")
    op.drop_table("site_issues")
    op.drop_index(op.f("ix_rfq_lines_rfq_id"), table_name="rfq_lines")
    op.drop_table("rfq_lines")
    op.drop_index(op.f("ix_po_lines_po_id"), table_name="po_lines")
    op.drop_table("po_lines")
    op.drop_index(op.f("ix_grn_photos_grn_id"), table_name="grn_photos")
    op.drop_table("grn_photos")
    op.drop_index(op.f("ix_freight_entries_site_id"), table_name="freight_entries")
    op.drop_index(op.f("ix_freight_entries_on_date"), table_name="freight_entries")
    op.drop_table("freight_entries")
    op.drop_index(op.f("ix_transfer_lines_transfer_id"), table_name="transfer_lines")
    op.drop_table("transfer_lines")
    op.drop_table("rfq_indents")
    op.drop_table("po_indents")
    op.drop_index(op.f("ix_po_charges_po_id"), table_name="po_charges")
    op.drop_table("po_charges")
    op.drop_index(op.f("ix_indent_lines_indent_id"), table_name="indent_lines")
    op.drop_table("indent_lines")
    op.drop_index(op.f("ix_grns_store_id"), table_name="grns")
    op.drop_index(op.f("ix_grns_status"), table_name="grns")
    op.drop_index(op.f("ix_grns_po_id"), table_name="grns")
    op.drop_table("grns")
    op.drop_index(op.f("ix_transfers_to_store_id"), table_name="transfers")
    op.drop_index(op.f("ix_transfers_status"), table_name="transfers")
    op.drop_index(op.f("ix_transfers_from_store_id"), table_name="transfers")
    op.drop_table("transfers")
    op.drop_index("ix_stock_ledger_store_product", table_name="stock_ledger")
    op.drop_table("stock_ledger")
    op.drop_index(op.f("ix_purchase_orders_vendor_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_store_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_status"), table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.drop_index(op.f("ix_indents_status"), table_name="indents")
    op.drop_index(op.f("ix_indents_site_id"), table_name="indents")
    op.drop_table("indents")
    op.drop_table("stores")
    op.drop_table("rfq_vendors")
    op.drop_table("rfqs")
    op.drop_table("doc_sequences")


# --- data ----------------------------------------------------------------------------------------

NEW_PERMISSIONS = [
    ("indent.view", "material", "View material indents"),
    ("indent.create", "material", "Raise material indents"),
    ("po.view", "material", "View purchase orders and RFQs"),
    ("po.edit", "material", "Create RFQs and purchase orders; approve own POs under the limit"),
    ("po.approve", "material", "Approve purchase orders above the approval limit"),
    ("grn.view", "material", "View goods receipts (GRN)"),
    ("grn.edit", "material", "Record goods receipts"),
    ("grn.approve", "material", "Approve goods receipts (stock goes in)"),
    ("store.view", "material", "View stores, stock and transfers"),
    ("store.edit", "material", "Transfers, site issues and returns, stock adjustments"),
]
ALL = [c for c, _, _ in NEW_PERMISSIONS] + ["indent.approve"]
GRANTS = {
    "super_admin": dict.fromkeys(ALL, "all"),
    "office_admin": dict.fromkeys(ALL, "all"),
    # everything except approving POs above the limit
    "store_purchase": dict.fromkeys(
        ["indent.view", "indent.create", "indent.approve", "po.view", "po.edit", "grn.view",
         "grn.edit", "grn.approve", "store.view", "store.edit"], "all"),
    "site_supervisor": dict.fromkeys(
        ["indent.view", "indent.create", "grn.view", "grn.edit", "store.view", "store.edit"],
        "assigned"),
    "accounts": dict.fromkeys(["po.view", "grn.view"], "all"),
    "sales": {"indent.view": "assigned"},
}  # fmt: skip
# the M0 placeholders the new codes replace (indent.approve stays)
OLD_PERMISSIONS = [
    ("indent.raise", "indent", "Raise material indents"),
    ("indent.dispatch", "indent", "Dispatch material against indents"),
    ("indent.receive", "indent", "Receive material at site"),
]
OLD_GRANTS = [
    ("accounts", "indent.raise", "all"), ("office_admin", "indent.raise", "all"),
    ("sales", "indent.raise", "assigned"), ("site_supervisor", "indent.raise", "assigned"),
    ("super_admin", "indent.raise", "all"), ("store_purchase", "indent.dispatch", "all"),
    ("super_admin", "indent.dispatch", "all"), ("site_supervisor", "indent.receive", "assigned"),
    ("super_admin", "indent.receive", "all"),
]  # fmt: skip


def _grant(role: str, code: str, scope: str) -> None:
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_code, scope) "
        f"SELECT id, '{code}', '{scope}' FROM roles WHERE code = '{role}' "
        f"ON CONFLICT (role_id, permission_code) DO UPDATE SET scope = '{scope}'"
    )


def _seed() -> None:
    for code, module, description in NEW_PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (code, module, description) VALUES "
            f"('{code}', '{module}', '{description}')"
        )
    for role, grants in GRANTS.items():
        for code, scope in grants.items():
            _grant(role, code, scope)
    op.execute(
        "DELETE FROM permissions WHERE code IN ("
        + ", ".join(f"'{c}'" for c, _, _ in OLD_PERMISSIONS)
        + ")"
    )
    # the company godown, and a store for every site that is not closed
    op.execute("INSERT INTO stores (name, kind) VALUES ('Ethios Godown', 'godown')")
    op.execute(
        "INSERT INTO stores (name, kind, site_id) SELECT code || ' ' || left(name, 150), 'site', "
        "id FROM sites WHERE status <> 'closed'"
    )


def _unseed() -> None:
    for code, module, description in OLD_PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (code, module, description) VALUES "
            f"('{code}', '{module}', '{description}') ON CONFLICT DO NOTHING"
        )
    for role, code, scope in OLD_GRANTS:
        _grant(role, code, scope)
    op.execute(
        "DELETE FROM permissions WHERE code IN ("
        + ", ".join(f"'{c}'" for c, _, _ in NEW_PERMISSIONS)
        + ")"
    )
