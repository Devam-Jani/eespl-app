"""masters: units, clients, products and prices, systems, rate library, T&C library

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of app.masters.units.DEFAULT_UNITS at the time of this migration.
UNITS = {
    "sqm": ("Square metre", ["sqm", "sq.m", "sq m", "sq.mt", "sqmt", "sq mtr", "sqmtr", "sq meter",
            "sq metre", "square metre", "square meter", "m2", "m²", "smt", "sm", "sqmts",
            "sqmtrs", "sq.mts"]),
    "sqft": ("Square foot", ["sqft", "sq.ft", "sq ft", "sft", "sqf", "sq feet", "square feet",
             "square foot", "ft2", "sq.fts", "sqfts"]),
    "rmt": ("Running metre", ["rmt", "rm", "r.mt", "rmtr", "rn.mtr", "running metre",
            "running meter", "rmts", "m", "mtr", "mtrs", "meter", "meters", "metre", "metres",
            "lm", "rm.", "r mt", "rn mt"]),
    "rft": ("Running foot", ["rft", "r ft", "r.ft", "running feet", "running foot", "rfeet"]),
    "cum": ("Cubic metre", ["cum", "cu.m", "cu m", "cumt", "cumtr", "cu mt", "cubic metre",
            "cubic meter", "m3", "m³", "cmt"]),
    "cft": ("Cubic foot", ["cft", "cu ft", "cu.ft", "cubic feet", "ft3"]),
    "kg": ("Kilogram", ["kg", "kgs", "kilogram", "kilograms", "kilo"]),
    "ltr": ("Litre", ["ltr", "ltrs", "litre", "litres", "liter", "liters", "lit", "l"]),
    "nos": ("Number", ["nos", "no", "no.", "nos.", "number", "numbers", "each", "ea", "ea.", "nr",
            "pcs", "pc", "piece", "pieces", "pt", "point", "points", "sausage"]),
    "set": ("Set", ["set", "sets"]),
    "roll": ("Roll", ["roll", "rolls"]),
    "ls": ("Lump sum", ["ls", "l.s", "lumpsum", "lump sum", "lumpsump", "job", "adhoc", "adhok"]),
}  # fmt: skip


def _tracked(table: str) -> list:
    """created_at, updated_at, created_by (+ its foreign key) for every master table."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"],
                                name=op.f(f"fk_{table}_created_by_users"), ondelete="SET NULL"),
    ]  # fmt: skip


def _id(big: bool = False) -> sa.Column:
    return sa.Column("id", sa.BigInteger() if big else sa.Integer(), sa.Identity(always=False),
                     nullable=False)  # fmt: skip


def _fk(table: str, column: str, target: str, ondelete: str | None = None):
    ref_table = target.split(".")[0]
    return sa.ForeignKeyConstraint([column], [target],
                                   name=op.f(f"fk_{table}_{column}_{ref_table}"),
                                   ondelete=ondelete)  # fmt: skip


def _bool(name: str, default: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), server_default=sa.text(default) if default == "true"
                     else default, nullable=False)  # fmt: skip


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "units",
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("aliases", sa.ARRAY(sa.String(50)), server_default="{}", nullable=False),
        *_tracked("units"),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_units")),
    )
    units = sa.table("units", sa.column("code"), sa.column("name"),
                     sa.column("aliases", sa.ARRAY(sa.String)))  # fmt: skip
    op.bulk_insert(
        units, [{"code": c, "name": n, "aliases": a} for c, (n, a) in UNITS.items()]
    )

    op.create_table(
        "clients",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(20), server_default="other", nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("pan", sa.String(10), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _bool("is_active", "true"),
        *_tracked("clients"),
        sa.CheckConstraint(
            "type IN ('builder', 'developer', 'pmc', 'contractor', 'government', 'other')",
            name=op.f("ck_clients_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_index(op.f("ix_clients_name"), "clients", ["name"])

    op.create_table(
        "client_contacts",
        _id(),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        _bool("is_primary", "false"),
        *_tracked("client_contacts"),
        _fk("client_contacts", "client_id", "clients.id", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_contacts")),
    )
    op.create_index(op.f("ix_client_contacts_client_id"), "client_contacts", ["client_id"])

    op.create_table(
        "products",
        _id(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("category", sa.String(20), server_default="other", nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("pack_size", sa.Numeric(12, 3), nullable=True),
        sa.Column("gst_percent", sa.Numeric(5, 2), server_default="18", nullable=False),
        _bool("is_active", "true"),
        *_tracked("products"),
        sa.CheckConstraint(
            "category IN ('membrane', 'coating', 'chemical', 'admixture', 'sealant', "
            "'waterstop', 'accessory', 'other')",
            name=op.f("ck_products_category_valid"),
        ),
        _fk("products", "unit", "units.code"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("code", name=op.f("uq_products_code")),
    )
    op.create_index(op.f("ix_products_name"), "products", ["name"])

    op.create_table(
        "product_prices",
        _id(),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("purchase_rate", sa.Numeric(14, 2), nullable=False),
        sa.Column("freight_per_unit", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_tracked("product_prices"),
        sa.CheckConstraint("freight_per_unit >= 0",
                           name=op.f("ck_product_prices_freight_nonnegative")),
        sa.CheckConstraint("purchase_rate >= 0",
                           name=op.f("ck_product_prices_purchase_rate_nonnegative")),
        _fk("product_prices", "product_id", "products.id", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_prices")),
    )  # fmt: skip
    op.create_index(
        "ix_product_prices_product_id_effective_from",
        "product_prices",
        ["product_id", "effective_from"],
    )

    op.create_table(
        "systems",
        _id(),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(10), server_default="sqm", nullable=False),
        sa.Column("surface_prep_per_unit", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("labour_rate", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("labour_unit", sa.String(10), server_default="sqm", nullable=False),
        sa.Column("default_margin_percent", sa.Numeric(6, 2), server_default="30",
                  nullable=False),
        _bool("is_active", "true"),
        *_tracked("systems"),
        sa.CheckConstraint("labour_unit IN ('sqm', 'sqft')",
                           name=op.f("ck_systems_labour_unit_valid")),
        _fk("systems", "unit", "units.code"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_systems")),
        sa.UniqueConstraint("code", name=op.f("uq_systems_code")),
    )  # fmt: skip

    op.create_table(
        "system_components",
        _id(),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("consumption_per_unit", sa.Numeric(12, 4), nullable=False),
        sa.Column("wastage_percent", sa.Numeric(6, 2), server_default="0", nullable=False),
        *_tracked("system_components"),
        sa.CheckConstraint("consumption_per_unit >= 0",
                           name=op.f("ck_system_components_consumption_nonnegative")),
        sa.CheckConstraint("wastage_percent >= 0",
                           name=op.f("ck_system_components_wastage_nonnegative")),
        _fk("system_components", "product_id", "products.id", "RESTRICT"),
        _fk("system_components", "system_id", "systems.id", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_components")),
    )  # fmt: skip
    op.create_index(op.f("ix_system_components_system_id"), "system_components", ["system_id"])

    op.create_table(
        "library_items",
        _id(big=True),
        sa.Column("source_key", sa.String(40), nullable=False),
        sa.Column("match_key", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(10), nullable=True),
        sa.Column("unit_raw", sa.String(50), nullable=True),
        sa.Column("boq_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("min_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("median_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("max_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("latest_client", sa.String(200), nullable=True),
        sa.Column("latest_source_file", sa.Text(), nullable=True),
        sa.Column("product_make", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        _bool("from_eespl_file", "false"),
        _bool("needs_check", "false"),
        sa.Column("check_note", sa.String(200), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(description, ''))", persisted=True),
            nullable=False,
        ),
        *_tracked("library_items"),
        _fk("library_items", "unit", "units.code"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_items")),
        sa.UniqueConstraint("source_key", name=op.f("uq_library_items_source_key")),
    )
    op.create_index(
        "ix_library_items_description_trgm",
        "library_items",
        ["description"],
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_library_items_search_vector", "library_items", ["search_vector"],
        postgresql_using="gin",
    )  # fmt: skip
    op.create_index(op.f("ix_library_items_match_key"), "library_items", ["match_key"])
    op.create_index(op.f("ix_library_items_unit"), "library_items", ["unit"])

    op.create_table(
        "library_lines",
        _id(big=True),
        sa.Column("source_key", sa.String(40), nullable=False),
        sa.Column("library_item_id", sa.BigInteger(), nullable=True),
        sa.Column("client_folder", sa.String(200), nullable=True),
        sa.Column("file", sa.Text(), nullable=False),
        sa.Column("sheet", sa.String(200), nullable=True),
        sa.Column("row", sa.Integer(), nullable=True),
        sa.Column("item_no", sa.String(50), nullable=True),
        sa.Column("parent_item", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit_raw", sa.String(50), nullable=True),
        sa.Column("unit", sa.String(10), nullable=True),
        sa.Column("qty", sa.Numeric(16, 4), nullable=True),
        sa.Column("qty_note", sa.String(50), nullable=True),
        sa.Column("rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("product_make", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        _bool("from_eespl_file", "false"),
        _bool("needs_check", "false"),
        sa.Column("check_note", sa.String(200), nullable=True),
        *_tracked("library_lines"),
        _fk("library_lines", "library_item_id", "library_items.id", "SET NULL"),
        _fk("library_lines", "unit", "units.code"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_lines")),
        sa.UniqueConstraint("source_key", name=op.f("uq_library_lines_source_key")),
    )
    op.create_index(op.f("ix_library_lines_library_item_id"), "library_lines", ["library_item_id"])

    op.create_table(
        "tc_clauses",
        _id(),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False),
        _bool("default_include", "false"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _bool("is_active", "true"),
        *_tracked("tc_clauses"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tc_clauses")),
    )
    op.create_index(op.f("ix_tc_clauses_category"), "tc_clauses", ["category"])

    op.create_table(
        "tc_templates",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        _bool("is_default", "false"),
        *_tracked("tc_templates"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tc_templates")),
        sa.UniqueConstraint("name", name=op.f("uq_tc_templates_name")),
    )
    op.create_index(
        "uq_tc_templates_single_default", "tc_templates", ["is_default"], unique=True,
        postgresql_where="is_default",
    )  # fmt: skip

    op.create_table(
        "tc_template_clauses",
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("clause_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_tracked("tc_template_clauses"),
        _fk("tc_template_clauses", "clause_id", "tc_clauses.id", "CASCADE"),
        _fk("tc_template_clauses", "template_id", "tc_templates.id", "CASCADE"),
        sa.PrimaryKeyConstraint("template_id", "clause_id", name=op.f("pk_tc_template_clauses")),
    )
    op.create_index(
        op.f("ix_tc_template_clauses_clause_id"), "tc_template_clauses", ["clause_id"]
    )


def downgrade() -> None:
    for table in [
        "tc_template_clauses",
        "tc_templates",
        "tc_clauses",
        "library_lines",
        "library_items",
        "system_components",
        "systems",
        "product_prices",
        "products",
        "client_contacts",
        "clients",
        "units",
    ]:
        op.drop_table(table)
    # pg_trgm is left installed: other databases objects may come to rely on it.
