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
    func,
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
    __table_args__ = (CheckConstraint(_in("category", PRODUCT_CATEGORIES), name="category_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20), server_default="other")
    unit: Mapped[str] = mapped_column(ForeignKey("units.code"))
    pack_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    is_active: Mapped[bool] = mapped_column(server_default=true())


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
    latest_client: Mapped[str | None] = mapped_column(String(200))
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
    client_folder: Mapped[str | None] = mapped_column(String(200))
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

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), index=True)
    usage_count: Mapped[int] = mapped_column(Integer, server_default="0")
    default_include: Mapped[bool] = mapped_column(server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


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
