"""Master data: units, clients, products and prices, rate build-up systems, the historical
rate library and the T&C library."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.models import Base

CLIENT_TYPES = ("builder", "developer", "pmc", "contractor", "government", "other")
PRODUCT_CATEGORIES = (
    "membrane",
    "coating",
    "chemical",
    "admixture",
    "sealant",
    "waterstop",
    "accessory",
    "other",
)
LABOUR_UNITS = ("sqm", "sqft")

Money = Numeric(14, 2)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Tracked:
    """created_at / updated_at / created_by on every master table."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Unit(Tracked, Base):
    __tablename__ = "units"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}")


CHANNEL_TYPES = ("salesperson", "partner", "manufacturer", "other")


class Channel(Tracked, Base):
    """Who brought a tender: a salesperson, an applicator partner or a manufacturer route. The
    rate library's folders are channels, not end clients."""

    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint(
            "type IN ('salesperson', 'partner', 'manufacturer', 'other')", name="type_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    type: Mapped[str] = mapped_column(String(20), server_default="other")
    is_active: Mapped[bool] = mapped_column(server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)


class Client(Tracked, Base):
    __tablename__ = "clients"
    __table_args__ = (CheckConstraint(_in("type", CLIENT_TYPES), name="type_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(20), server_default="other")
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    # invented analytics demo data (python -m app.cli seed-demo-analytics); never real
    is_demo: Mapped[bool] = mapped_column(server_default=false(), index=True)

    contacts: Mapped[list["ClientContact"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(ClientContact.is_primary.desc(), ClientContact.id)",
    )


class ClientContact(Tracked, Base):
    __tablename__ = "client_contacts"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(server_default="false")


class Product(Tracked, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    unit: Mapped[str] = mapped_column(ForeignKey("units.code"))
    pack_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    # e.g. "bag" for a 20 kg bag (pack_size 20, unit kg); empty: no pack rounding
    pack_unit: Mapped[str | None] = mapped_column(String(20))
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    hsn_code: Mapped[str | None] = mapped_column(String(8))  # HSN (goods) / SAC (services)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    # invented analytics demo data (python -m app.cli seed-demo-analytics); never real
    is_demo: Mapped[bool] = mapped_column(server_default=false(), index=True)
    # low-stock alert and the purchase dashboard: total stock below this (base unit)
    reorder_level: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))

    category: Mapped["Category | None"] = relationship(lazy="joined")


class ProductPrice(Tracked, Base):
    """Append-only price history. The current price is the latest effective_from <= today."""

    __tablename__ = "product_prices"
    __table_args__ = (
        CheckConstraint("purchase_rate >= 0", name="purchase_rate_nonnegative"),
        CheckConstraint("freight_per_unit >= 0", name="freight_nonnegative"),
        Index("ix_product_prices_product_id_effective_from", "product_id", "effective_from"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    purchase_rate: Mapped[Decimal] = mapped_column(Money)
    freight_per_unit: Mapped[Decimal] = mapped_column(Money, server_default="0")
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class System(Tracked, Base):
    """A rate build-up recipe for one waterproofing system."""

    __tablename__ = "systems"
    __table_args__ = (CheckConstraint(_in("labour_unit", LABOUR_UNITS), name="labour_unit_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(ForeignKey("units.code"), server_default="sqm")
    surface_prep_per_unit: Mapped[Decimal] = mapped_column(Money, server_default="0")
    labour_rate: Mapped[Decimal] = mapped_column(Money, server_default="0")
    labour_unit: Mapped[str] = mapped_column(String(10), server_default="sqm")
    default_margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="30")
    is_active: Mapped[bool] = mapped_column(server_default=true())

    components: Mapped[list["SystemComponent"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SystemComponent.id",
    )


class SystemComponent(Tracked, Base):
    __tablename__ = "system_components"
    __table_args__ = (
        CheckConstraint("consumption_per_unit >= 0", name="consumption_nonnegative"),
        CheckConstraint("wastage_percent >= 0", name="wastage_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    consumption_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    wastage_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="0")

    product: Mapped[Product] = relationship(lazy="joined")


class LibraryItem(Tracked, Base):
    """One distinct BOQ line (description + unit) with rate statistics across past BOQs."""

    __tablename__ = "library_items"
    __table_args__ = (
        CheckConstraint(
            "exclusion_source IS NULL OR exclusion_source IN ('rule', 'manual')",
            name="exclusion_source_valid",
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="not_merged_into_self"
        ),
        Index("ix_library_items_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_library_items_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # sha1 of normalised description + the unit as written in the source; the import's upsert key.
    source_key: Mapped[str] = mapped_column(String(40), unique=True)
    # sha1 of normalised description + normalised unit; how source lines find their item.
    match_key: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(ForeignKey("units.code"), index=True)
    unit_raw: Mapped[str | None] = mapped_column(String(50))
    boq_count: Mapped[int] = mapped_column(Integer, server_default="0")
    latest_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    min_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    median_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    max_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    latest_channel: Mapped[str | None] = mapped_column(String(200))
    latest_source_file: Mapped[str | None] = mapped_column(Text)
    product_make: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    from_eespl_file: Mapped[bool] = mapped_column(server_default="false")
    needs_check: Mapped[bool] = mapped_column(server_default="false")
    check_note: Mapped[str | None] = mapped_column(String(200))
    # Hidden from search by default: working/margin rows, rates below ₹1, or by hand.
    is_excluded: Mapped[bool] = mapped_column(server_default="false")
    excluded_reason: Mapped[str | None] = mapped_column(String(200))
    exclusion_source: Mapped[str | None] = mapped_column(String(10))  # 'rule' | 'manual'
    # Rates from other bidders' comparative sheets, not EESPL's.
    is_competitor: Mapped[bool] = mapped_column(server_default="false")
    # A person changed the unit; re-imports keep it.
    unit_manual: Mapped[bool] = mapped_column(server_default="false")
    # Merged duplicates point at the item they were merged into; their lines count there.
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL"), index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Statistics as the source sheet gave them; the rate columns above may be recomputed from
    # lines (stats_from_lines) when flagged lines are left out or items are merged.
    source_stats: Mapped[dict | None] = mapped_column(JSONB)
    stats_from_lines: Mapped[bool] = mapped_column(server_default="false")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(description, ''))", persisted=True),
    )


class LibraryLine(Tracked, Base):
    """One priced line as read from a past BOQ file."""

    __tablename__ = "library_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # sha1 of file + sheet + row; the import's upsert key.
    source_key: Mapped[str] = mapped_column(String(40), unique=True)
    library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL"), index=True
    )
    # the top-level folder the BOQ came from: a channel (salesperson / partner / manufacturer)
    channel: Mapped[str | None] = mapped_column(String(200))
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    file: Mapped[str] = mapped_column(Text)
    sheet: Mapped[str | None] = mapped_column(String(200))
    row: Mapped[int | None] = mapped_column(Integer)
    item_no: Mapped[str | None] = mapped_column(String(50))
    parent_item: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    unit_raw: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str | None] = mapped_column(ForeignKey("units.code"))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    qty_note: Mapped[str | None] = mapped_column(String(50))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    product_make: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    from_eespl_file: Mapped[bool] = mapped_column(server_default="false")
    needs_check: Mapped[bool] = mapped_column(server_default="false")
    check_note: Mapped[str | None] = mapped_column(String(200))
    is_excluded: Mapped[bool] = mapped_column(server_default="false")
    excluded_reason: Mapped[str | None] = mapped_column(String(200))
    is_competitor: Mapped[bool] = mapped_column(server_default="false")


class TcClause(Tracked, Base):
    __tablename__ = "tc_clauses"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'hidden')", name="status_valid"),
        CheckConstraint(
            "(status = 'active' AND hidden_reason IS NULL) OR (status = 'hidden' AND hidden_reason "
            "IN ('not_a_clause', 'client_checklist', 'project_specific', 'manual'))",
            name="hidden_reason_valid",
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id", name="not_merged_into_self"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)
    # For a master: own_usage_count + the own_usage_count of its merged variants.
    usage_count: Mapped[int] = mapped_column(Integer, server_default="0")
    own_usage_count: Mapped[int] = mapped_column(Integer, server_default="0")
    default_include: Mapped[bool] = mapped_column(server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(10), server_default="active")  # active | hidden
    hidden_reason: Mapped[str | None] = mapped_column(String(30))
    # A near-duplicate points at its master; its text is kept to help match client BOQs.
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_clauses.id", ondelete="SET NULL"), index=True
    )
    needs_review: Mapped[bool] = mapped_column(server_default="false")
    review_note: Mapped[str | None] = mapped_column(Text)
    # A person has made a decision about this clause; the cleanup command leaves it alone.
    curated: Mapped[bool] = mapped_column(server_default="false")


class TcTemplate(Tracked, Base):
    __tablename__ = "tc_templates"
    __table_args__ = (
        # At most one default template.
        Index(
            "uq_tc_templates_single_default",
            "is_default",
            unique=True,
            postgresql_where="is_default",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_default: Mapped[bool] = mapped_column(server_default="false")

    clauses: Mapped[list["TcTemplateClause"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TcTemplateClause.sort_order",
    )


class TcTemplateClause(Tracked, Base):
    __tablename__ = "tc_template_clauses"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="CASCADE"), primary_key=True
    )
    clause_id: Mapped[int] = mapped_column(
        ForeignKey("tc_clauses.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")

    clause: Mapped[TcClause] = relationship(lazy="joined")


# --- M1 part 2: categories, tags, unit conversions, vendors, company settings ---------------

CATEGORY_KINDS = ("work", "material")
TAG_MODULES = ("material", "petty_spend", "work_order", "issue")
VENDOR_TYPES = ("material_supplier", "labour_contractor", "subcontractor", "transporter", "other")


class Category(Tracked, Base):
    """Work categories (where on site) and material categories (what kind of product)."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(_in("kind", CATEGORY_KINDS), name="kind_valid"),
        Index("uq_categories_kind_name", "kind", func.lower(text("name")), unique=True),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


class Tag(Tracked, Base):
    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint(_in("module", TAG_MODULES), name="module_valid"),
        Index("uq_tags_module_name", "module", func.lower(text("name")), unique=True),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    module: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_archived: Mapped[bool] = mapped_column(server_default="false")


class UnitConversion(Tracked, Base):
    """qty_in_to = qty_in_from × factor. product_id set = only for that product
    (1 bag of a product = 25 kg); otherwise generic (1 sqm = 10.7639 sqft)."""

    __tablename__ = "unit_conversions"
    __table_args__ = (
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint("from_unit <> to_unit", name="different_units"),
        Index(
            "uq_unit_conversions_generic",
            "from_unit",
            "to_unit",
            unique=True,
            postgresql_where=text("product_id IS NULL"),
        ),
        Index(
            "uq_unit_conversions_product",
            "from_unit",
            "to_unit",
            "product_id",
            unique=True,
            postgresql_where=text("product_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    from_unit: Mapped[str] = mapped_column(ForeignKey("units.code"))
    to_unit: Mapped[str] = mapped_column(ForeignKey("units.code"))
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )

    product: Mapped["Product | None"] = relationship(lazy="joined")


class Vendor(Tracked, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint(_in("type", VENDOR_TYPES), name="type_valid"),
        CheckConstraint("payment_terms_days >= 0", name="payment_terms_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(30), server_default="material_supplier")
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default=true())
    # invented analytics demo data (python -m app.cli seed-demo-analytics); never real
    is_demo: Mapped[bool] = mapped_column(server_default=false(), index=True)

    contacts: Mapped[list["VendorContact"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(VendorContact.is_primary.desc(), VendorContact.id)",
    )
    bank_accounts: Mapped[list["VendorBankAccount"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(VendorBankAccount.is_primary.desc(), VendorBankAccount.id)",
    )
    products: Mapped[list["VendorProduct"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VendorProduct.id",
    )


class VendorContact(Tracked, Base):
    __tablename__ = "vendor_contacts"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(server_default="false")


class VendorBankAccount(Tracked, Base):
    """Account number and IFSC are finance data: only shown with settings.company or
    finance.view."""

    __tablename__ = "vendor_bank_accounts"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    account_name: Mapped[str] = mapped_column(String(200))
    account_number: Mapped[str] = mapped_column(String(34))
    ifsc: Mapped[str] = mapped_column(String(11))
    bank: Mapped[str | None] = mapped_column(String(100))
    branch: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(server_default="false")


class VendorProduct(Tracked, Base):
    """Who supplies what (optional link)."""

    __tablename__ = "vendor_products"
    __table_args__ = (
        Index("uq_vendor_products_vendor_product", "vendor_id", "product_id", unique=True),
        CheckConstraint("lead_time_days >= 0", name="lead_time_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    last_rate: Mapped[Decimal | None] = mapped_column(Money)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)

    product: Mapped["Product"] = relationship(lazy="joined")


class CompanyProfile(Tracked, Base):
    """EESPL's own details. A single row (id = 1)."""

    __tablename__ = "company_profile"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    legal_name: Mapped[str | None] = mapped_column(String(200))
    trade_name: Mapped[str | None] = mapped_column(String(200))
    logo_path: Mapped[str | None] = mapped_column(String(300))  # under the media volume
    pan: Mapped[str | None] = mapped_column(String(10))
    tan: Mapped[str | None] = mapped_column(String(10))
    tds_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cin: Mapped[str | None] = mapped_column(String(21))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(200))
    default_gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    # Auto-pricing: a suggestion is stored only when its score (0..1) reaches this.
    pricing_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0.55")
    # Which past rate a library suggestion uses (app.masters.rate_policy.POLICIES); the default
    # is the winner of "python -m app.cli backtest-rates".
    rate_policy: Mapped[str] = mapped_column(String(30), server_default="channel_median")
    # Kylas CRM (Settings > Integrations > Kylas; the API key lives in .env only).
    # While kylas_source_id is empty nothing is pushed, so app leads never land in another
    # app's source of the shared Kylas account.
    kylas_source_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_owner_rule: Mapped[str] = mapped_column(String(20), server_default="creator")
    kylas_default_owner_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_deal_pipeline_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_won_stage_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_lead_code_field: Mapped[str] = mapped_column(String(60), server_default="cfInquiryType")
    kylas_category_field: Mapped[str] = mapped_column(
        String(60), server_default="cfCustomerCategrory"
    )
    # material (Settings > Purchase): POs above the limit need po.approve; below it the creator
    # with po.edit approves; stock may go negative only when allowed; GRNs need 1 or 2 approvals
    po_approval_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="50000")
    allow_negative_stock: Mapped[bool] = mapped_column(server_default="false")
    grn_approval_levels: Mapped[int] = mapped_column(Integer, server_default="1")
    asset_overdue_days: Mapped[int] = mapped_column(Integer, server_default="30")
    portal_invite_days: Mapped[int] = mapped_column(Integer, server_default="7")  # invite link life
    freight_sac: Mapped[str] = mapped_column(String(8), server_default="9965")  # on PO freight
    po_tc_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="SET NULL")
    )
    kylas_junk_reasons: Mapped[list[str]] = mapped_column(
        JSONB, server_default='["Wrong number", "False enquiry", "Duplicate"]'
    )


class CompanyGstin(Tracked, Base):
    """Address directory: one row per GST registration, used on bills and POs."""

    __tablename__ = "company_gstins"
    __table_args__ = (
        Index(
            "uq_company_gstins_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    gstin: Mapped[str] = mapped_column(String(15), unique=True)
    state: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(server_default="false")


class CompanyBankAccount(Tracked, Base):
    __tablename__ = "company_bank_accounts"
    __table_args__ = (
        Index(
            "uq_company_bank_accounts_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    account_name: Mapped[str] = mapped_column(String(200))
    account_number: Mapped[str] = mapped_column(String(34))
    ifsc: Mapped[str] = mapped_column(String(11))
    bank: Mapped[str | None] = mapped_column(String(100))
    branch: Mapped[str | None] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(server_default="false")
