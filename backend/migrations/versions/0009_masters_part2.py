"""masters part 2: categories, tags, unit conversions, vendors, company settings

- products.category (a fixed list) becomes products.category_id; every product keeps its
  category through the seeded material categories.
- users.email and users.password_hash become nullable (people imported from Powerplay have no
  password yet, some have no email); users.job_title added.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The values products.category allowed before this migration, in display order.
MATERIAL_CATEGORIES = [
    ("membrane", "Membrane"),
    ("coating", "Coating"),
    ("chemical", "Chemical"),
    ("admixture", "Admixture"),
    ("sealant", "Sealant"),
    ("waterstop", "Waterstop"),
    ("accessory", "Accessory"),
    ("other", "Other"),
]
WORK_CATEGORIES = [
    "Raft / basement", "Retaining wall", "Lift pit", "Water tanks (UG/OH)",
    "Toilets & wet areas", "Kitchen", "Balcony", "Terrace", "Podium / garden",
    "Expansion joints", "Injection grouting", "Other",
]  # fmt: skip
# Generic conversions (from, to, factor): qty_in_to = qty_in_from × factor
CONVERSIONS = [
    ("sqm", "sqft", "10.76391042"),
    ("rmt", "rft", "3.28083990"),
    ("cum", "cft", "35.31466672"),
]


def _tracked(table: str) -> list:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"],
                                name=op.f(f"fk_{table}_created_by_users"), ondelete="SET NULL"),
    ]  # fmt: skip


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False)


def _pk(table: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}"))


def _fk(table: str, column: str, target: str, ondelete: str | None = None):
    return sa.ForeignKeyConstraint([column], [target],
                                   name=op.f(f"fk_{table}_{column}_{target.split('.')[0]}"),
                                   ondelete=ondelete)  # fmt: skip


def _flag(name: str, default: str = "false") -> sa.Column:
    server_default = sa.text("true") if default == "true" else default
    return sa.Column(name, sa.Boolean(), server_default=server_default, nullable=False)


def _bank(table: str, flag: str) -> list:
    return [
        _id(),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("account_number", sa.String(34), nullable=False),
        sa.Column("ifsc", sa.String(11), nullable=False),
        sa.Column("bank", sa.String(100), nullable=True),
        sa.Column("branch", sa.String(100), nullable=True),
        _flag(flag),
        *_tracked(table),
        _pk(table),
    ]


def upgrade() -> None:
    # categories ------------------------------------------------------------------------
    op.create_table(
        "categories",
        _id(),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _flag("is_active", "true"),
        *_tracked("categories"),
        sa.CheckConstraint("kind IN ('work', 'material')", name=op.f("ck_categories_kind_valid")),
        _fk("categories", "parent_id", "categories.id", "SET NULL"),
        _pk("categories"),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"])
    op.create_index(
        "uq_categories_kind_name", "categories", ["kind", sa.text("lower(name)")], unique=True
    )
    categories = sa.table("categories", sa.column("kind"), sa.column("name"),
                          sa.column("sort_order"))  # fmt: skip
    op.bulk_insert(
        categories,
        [{"kind": "material", "name": n, "sort_order": i}
         for i, (_, n) in enumerate(MATERIAL_CATEGORIES, start=1)]
        + [{"kind": "work", "name": n, "sort_order": i}
           for i, n in enumerate(WORK_CATEGORIES, start=1)],
    )  # fmt: skip

    # products.category -> products.category_id (keeping every product's category)
    op.add_column("products", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_products_category_id_categories"), "products", "categories",
        ["category_id"], ["id"], ondelete="SET NULL",
    )  # fmt: skip
    op.create_index(op.f("ix_products_category_id"), "products", ["category_id"])
    op.execute(
        """
        UPDATE products p SET category_id = c.id
        FROM categories c
        WHERE c.kind = 'material' AND lower(c.name) = lower(p.category)
        """
    )
    op.drop_constraint(op.f("ck_products_category_valid"), "products", type_="check")
    op.drop_column("products", "category")

    # tags ------------------------------------------------------------------------------
    op.create_table(
        "tags",
        _id(),
        sa.Column("module", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        _flag("is_archived"),
        *_tracked("tags"),
        sa.CheckConstraint(
            "module IN ('material', 'petty_spend', 'work_order', 'issue')",
            name=op.f("ck_tags_module_valid"),
        ),
        _pk("tags"),
    )
    op.create_index("uq_tags_module_name", "tags", ["module", sa.text("lower(name)")], unique=True)

    # unit conversions ------------------------------------------------------------------
    op.create_table(
        "unit_conversions",
        _id(),
        sa.Column("from_unit", sa.String(10), nullable=False),
        sa.Column("to_unit", sa.String(10), nullable=False),
        sa.Column("factor", sa.Numeric(18, 8), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        *_tracked("unit_conversions"),
        sa.CheckConstraint("factor > 0", name=op.f("ck_unit_conversions_factor_positive")),
        sa.CheckConstraint(
            "from_unit <> to_unit", name=op.f("ck_unit_conversions_different_units")
        ),
        _fk("unit_conversions", "from_unit", "units.code"),
        _fk("unit_conversions", "to_unit", "units.code"),
        _fk("unit_conversions", "product_id", "products.id", "CASCADE"),
        _pk("unit_conversions"),
    )
    op.create_index(op.f("ix_unit_conversions_product_id"), "unit_conversions", ["product_id"])
    op.create_index("uq_unit_conversions_generic", "unit_conversions", ["from_unit", "to_unit"],
                    unique=True, postgresql_where=sa.text("product_id IS NULL"))  # fmt: skip
    op.create_index("uq_unit_conversions_product", "unit_conversions",
                    ["from_unit", "to_unit", "product_id"], unique=True,
                    postgresql_where=sa.text("product_id IS NOT NULL"))  # fmt: skip
    conversions = sa.table("unit_conversions", sa.column("from_unit"), sa.column("to_unit"),
                           sa.column("factor", sa.Numeric))  # fmt: skip
    op.bulk_insert(conversions, [{"from_unit": f, "to_unit": t, "factor": x}
                                 for f, t, x in CONVERSIONS])  # fmt: skip

    # vendors ---------------------------------------------------------------------------
    op.create_table(
        "vendors",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(30), server_default="material_supplier", nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("pan", sa.String(10), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _flag("is_active", "true"),
        *_tracked("vendors"),
        sa.CheckConstraint(
            "type IN ('material_supplier', 'labour_contractor', 'subcontractor', 'transporter', "
            "'other')",
            name=op.f("ck_vendors_type_valid"),
        ),
        sa.CheckConstraint("payment_terms_days >= 0",
                           name=op.f("ck_vendors_payment_terms_nonnegative")),
        _pk("vendors"),
    )  # fmt: skip
    op.create_index(op.f("ix_vendors_name"), "vendors", ["name"])
    op.create_table(
        "vendor_contacts",
        _id(),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        _flag("is_primary"),
        *_tracked("vendor_contacts"),
        _fk("vendor_contacts", "vendor_id", "vendors.id", "CASCADE"),
        _pk("vendor_contacts"),
    )
    op.create_index(op.f("ix_vendor_contacts_vendor_id"), "vendor_contacts", ["vendor_id"])
    op.create_table(
        "vendor_bank_accounts",
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        *_bank("vendor_bank_accounts", "is_primary"),
        _fk("vendor_bank_accounts", "vendor_id", "vendors.id", "CASCADE"),
    )
    op.create_index(op.f("ix_vendor_bank_accounts_vendor_id"), "vendor_bank_accounts",
                    ["vendor_id"])  # fmt: skip
    op.create_table(
        "vendor_products",
        _id(),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("last_rate", sa.Numeric(14, 2), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        *_tracked("vendor_products"),
        sa.CheckConstraint("lead_time_days >= 0",
                           name=op.f("ck_vendor_products_lead_time_nonnegative")),
        _fk("vendor_products", "vendor_id", "vendors.id", "CASCADE"),
        _fk("vendor_products", "product_id", "products.id", "CASCADE"),
        _pk("vendor_products"),
    )  # fmt: skip
    op.create_index(op.f("ix_vendor_products_product_id"), "vendor_products", ["product_id"])
    op.create_index("uq_vendor_products_vendor_product", "vendor_products",
                    ["vendor_id", "product_id"], unique=True)  # fmt: skip

    # company settings ------------------------------------------------------------------
    op.create_table(
        "company_profile",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=True),
        sa.Column("trade_name", sa.String(200), nullable=True),
        sa.Column("logo_path", sa.String(300), nullable=True),
        sa.Column("pan", sa.String(10), nullable=True),
        sa.Column("tan", sa.String(10), nullable=True),
        sa.Column("tds_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("cin", sa.String(21), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("website", sa.String(200), nullable=True),
        sa.Column("default_gst_percent", sa.Numeric(5, 2), server_default="18", nullable=False),
        *_tracked("company_profile"),
        sa.CheckConstraint("id = 1", name=op.f("ck_company_profile_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_profile")),
    )
    op.execute("INSERT INTO company_profile (id) VALUES (1)")
    op.create_table(
        "company_gstins",
        _id(),
        sa.Column("gstin", sa.String(15), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        _flag("is_default"),
        *_tracked("company_gstins"),
        _pk("company_gstins"),
        sa.UniqueConstraint("gstin", name=op.f("uq_company_gstins_gstin")),
    )
    op.create_index("uq_company_gstins_single_default", "company_gstins", ["is_default"],
                    unique=True, postgresql_where=sa.text("is_default"))  # fmt: skip
    op.create_table("company_bank_accounts", *_bank("company_bank_accounts", "is_default"))
    op.create_index(
        "uq_company_bank_accounts_single_default",
        "company_bank_accounts",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # users -----------------------------------------------------------------------------
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column("users", sa.Column("job_title", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "job_title")
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)

    for table in ("company_bank_accounts", "company_gstins", "company_profile", "vendor_products",
                  "vendor_bank_accounts", "vendor_contacts", "vendors", "unit_conversions",
                  "tags"):  # fmt: skip
        op.drop_table(table)

    op.add_column(
        "products",
        sa.Column("category", sa.String(20), server_default="other", nullable=False),
    )
    op.execute(
        """
        UPDATE products p SET category = lower(c.name)
        FROM categories c
        WHERE c.id = p.category_id AND lower(c.name) IN
          ('membrane', 'coating', 'chemical', 'admixture', 'sealant', 'waterstop', 'accessory')
        """
    )
    op.create_check_constraint(
        op.f("ck_products_category_valid"),
        "products",
        "category IN ('membrane', 'coating', 'chemical', 'admixture', 'sealant', 'waterstop', "
        "'accessory', 'other')",
    )
    op.drop_index(op.f("ix_products_category_id"), table_name="products")
    op.drop_constraint(op.f("fk_products_category_id_categories"), "products", type_="foreignkey")
    op.drop_column("products", "category_id")
    op.drop_table("categories")
