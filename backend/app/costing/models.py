"""Rate working, the master price list's freight, and labour paid back to back (the director's
review with the director, 12 Oct).

- Freight per unit per product (or per vendor and godown), with its own history; the price
  history itself is masters.ProductPrice (source, unit, vendor, who and when).
- A rate working per BOQ (a tender's BOQ revision, or a quotation): the client's lines grouped
  into main items; per main item the system, its products (consumption for this site, price,
  freight), coats, the application's wastage, surface preparation, the labour piece rate and the
  margin. Cushions (labour used vs paid, freight used vs actual) are visible lines.
- Labour rate cards per labour contractor (job, unit, rate, valid from / to); labour bills: piece
  rate (the quantity billed to the client, or certified when less, times the rate) and attendance
  (a gang's hours per site from attendance), each line on its site.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

Money = Numeric(14, 2)
Rate = Numeric(14, 4)
Qty = Numeric(14, 3)
Pct = Numeric(7, 3)

LABOUR_UNITS = ("sqft", "sqm", "rmt", "nos", "cum")
# the surface a product goes on: its consumption differs (Devam, 15 Oct)
SURFACES = ("any", "rcc", "brick", "plaster", "screed", "old_tiles", "metal")
SURFACE_LABEL = {
    "any": "Any surface",
    "rcc": "RCC",
    "brick": "Brick",
    "plaster": "Plaster",
    "screed": "Screed",
    "old_tiles": "Old tiles",
    "metal": "Metal",
}
CONSUMPTION_SOURCES = ("old_boq", "data_sheet", "site_actual", "manual", "system")
LABOUR_BILL_KINDS = ("piece", "attendance")
LABOUR_BILL_STATUSES = ("draft", "approved", "cancelled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CostingSettings(Base):
    """One row (id 1): the flags. Wastage per application stays in Settings > Process rules."""

    __tablename__ = "costing_settings"
    __table_args__ = (
        CheckConstraint("margin_basis IN ('cost', 'selling')", name="margin_basis_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_change_flag_percent: Mapped[Decimal] = mapped_column(Pct, server_default="10")
    library_diff_flag_percent: Mapped[Decimal] = mapped_column(Pct, server_default="15")
    calloff_tolerance_percent: Mapped[Decimal] = mapped_column(Pct, server_default="5")
    day_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), server_default="8")  # a gang's day
    # the basis new workings take: "selling": rate = cost ÷ (1 − margin) (the default, Devam
    # 15 Oct); "cost": rate = cost × (1 + margin)
    margin_basis: Mapped[str] = mapped_column(String(8), server_default="selling")
    # the margin check warns when material alone is over this share of a BOQ line's rate (the
    # director sets it)
    material_share_warn_percent: Mapped[Decimal] = mapped_column(Pct, server_default="70")


class FreightRate(Tracked, Base):
    """Freight per unit of a product, optionally for one vendor and one godown (store). The most
    specific rate in force wins: vendor + godown, then vendor, then the product alone."""

    __tablename__ = "freight_rates"
    __table_args__ = (CheckConstraint("per_unit >= 0", name="per_unit_nonnegative"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"))
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    per_unit: Mapped[Decimal] = mapped_column(Money)
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class RateWorking(Tracked, Base):
    """The working of one BOQ: a tender's revision (tender_id + rev_no) or a quotation (each
    quotation revision is its own row). A new revision copies the previous working; a submitted
    revision's working is kept as it was (locked)."""

    __tablename__ = "rate_workings"
    __table_args__ = (
        CheckConstraint("(tender_id IS NOT NULL) <> (quotation_id IS NOT NULL)", name="one_parent"),
        UniqueConstraint("tender_id", "rev_no"),
        UniqueConstraint("quotation_id"),
        CheckConstraint("margin_basis IN ('cost', 'selling')", name="margin_basis_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # the margin basis this working is priced on, fixed when it is made (the settings' default
    # at that time); a working saved on cost keeps it and says so
    margin_basis: Mapped[str] = mapped_column(String(8), server_default="selling")
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE")
    )
    rev_no: Mapped[int] = mapped_column(Integer, server_default="0")
    locked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    copied_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("rate_workings.id", ondelete="SET NULL")
    )
    # products the client supplies free of cost (cement, sand ...): out of our cost, in the T&C
    free_issue_product_ids: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")

    groups: Mapped[list["RateGroup"]] = relationship(
        order_by="RateGroup.sort_order, RateGroup.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RateGroup(Tracked, Base):
    """A main item: the client's lines it covers and how its rate is worked (per sqm)."""

    __tablename__ = "rate_groups"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    working_id: Mapped[int] = mapped_column(
        ForeignKey("rate_workings.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    name: Mapped[str] = mapped_column(String(200))
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    application: Mapped[str | None] = mapped_column(String(40))  # raft, footing ... (wastage)
    # the main item's surface and what the client's spec asks: they pick the consumption
    surface: Mapped[str | None] = mapped_column(String(10))
    req_min_kg_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    req_dft_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    coats: Mapped[int | None] = mapped_column(Integer)
    wastage_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    # where the wastage came from: the application in Settings > Process rules, the system, typed
    wastage_source: Mapped[str | None] = mapped_column(String(200))
    surface_prep: Mapped[Decimal] = mapped_column(Money, server_default="0")  # ₹ per sqm
    labour_rate_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("labour_rate_cards.id", ondelete="SET NULL")
    )
    labour_used_sqft: Mapped[Decimal] = mapped_column(Money, server_default="0")  # in the rate
    labour_paid_sqft: Mapped[Decimal | None] = mapped_column(Money)  # what the gang is paid
    margin_percent: Mapped[Decimal] = mapped_column(Pct, server_default="30")
    # the worked result, kept so the lines and exports show it without re-working
    cost_sqm: Mapped[Decimal | None] = mapped_column(Rate)
    rate_sqm: Mapped[Decimal | None] = mapped_column(Money)
    rate_sqft: Mapped[Decimal | None] = mapped_column(Money)
    library_median_sqm: Mapped[Decimal | None] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text)

    products: Mapped[list["RateGroupProduct"]] = relationship(
        order_by="RateGroupProduct.sort_order, RateGroupProduct.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    lines: Mapped[list["RateGroupLine"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )


class ProductConsumption(Tracked, Base):
    """A product's consumption (per sqm, all coats) for a surface and what the client's spec asks
    (coats, a minimum kg per sqm, a DFT): never one fixed number per product. Where it came from
    (an old BOQ's working, the manufacturer's data sheet, a site's actual, typed) and how many
    times it was used."""

    __tablename__ = "product_consumptions"
    __table_args__ = (
        CheckConstraint(_in("surface", SURFACES), name="surface_valid"),
        CheckConstraint(_in("source", CONSUMPTION_SOURCES), name="source_valid"),
        CheckConstraint("consumption >= 0", name="consumption_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    system_id: Mapped[int | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    surface: Mapped[str] = mapped_column(String(10), server_default="any")
    coats: Mapped[int | None] = mapped_column(Integer)
    min_kg_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))  # the spec's minimum
    dft_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    consumption: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    source: Mapped[str] = mapped_column(String(12), server_default="manual")
    source_ref: Mapped[str | None] = mapped_column(Text)  # file / sheet / row, data sheet, site
    used_count: Mapped[int] = mapped_column(Integer, server_default="0")
    to_check: Mapped[bool] = mapped_column(Boolean, server_default="false")


class RateGroupProduct(Base):
    """One product of a main item: the consumption for this site (the system's default kept
    beside it, a reason when changed), the price used (from the master price list, with its date)
    and the freight used against the actual."""

    __tablename__ = "rate_group_products"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("rate_groups.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    consumption: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # per sqm, all coats
    default_consumption: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    consumption_reason: Mapped[str | None] = mapped_column(String(300))
    # where the starting consumption came from (the consumption table's row, or the system)
    consumption_source: Mapped[str | None] = mapped_column(String(300))
    consumption_row_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_consumptions.id", ondelete="SET NULL")
    )
    price: Mapped[Decimal | None] = mapped_column(Money)
    price_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_prices.id", ondelete="SET NULL")
    )
    freight_used: Mapped[Decimal] = mapped_column(Money, server_default="0")
    freight_actual: Mapped[Decimal | None] = mapped_column(Money)

    product = relationship("Product", lazy="joined")


class RateGroupLine(Base):
    """A client line in a main item: a tender BOQ line or a quotation line."""

    __tablename__ = "rate_group_lines"
    __table_args__ = (
        CheckConstraint(
            "(boq_line_id IS NOT NULL) <> (quotation_line_id IS NOT NULL)", name="one_line"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("rate_groups.id", ondelete="CASCADE"), index=True
    )
    boq_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_lines.id", ondelete="CASCADE"), index=True
    )
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="CASCADE"), index=True
    )


class LabourRateCard(Tracked, Base):
    """A labour contractor's piece rate for a job: "Coating" covers surface preparation,
    cleaning, crack and joint treatment, the vata (cove), primer and coat; ₹10 per sq ft.
    A range (plaster ₹15 to ₹18) keeps both ends; the bill uses the rate."""

    __tablename__ = "labour_rate_cards"
    __table_args__ = (
        CheckConstraint(_in("unit", LABOUR_UNITS), name="unit_valid"),
        CheckConstraint("rate >= 0", name="rate_nonnegative"),
        CheckConstraint("rate_max IS NULL OR rate_max >= rate", name="range_valid"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="dates_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    contractor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), index=True
    )
    job: Mapped[str] = mapped_column(String(100))
    covers: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(6), server_default="sqft")
    rate: Mapped[Decimal] = mapped_column(Money)
    rate_max: Mapped[Decimal | None] = mapped_column(Money)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class LabourBill(Tracked, Base):
    """A labour contractor's bill for a period: piece rate (from the measurement book's billed
    or certified quantities) or attendance (a gang's hours per site). TDS as in finance."""

    __tablename__ = "labour_bills"
    __table_args__ = (
        CheckConstraint(_in("kind", LABOUR_BILL_KINDS), name="kind_valid"),
        CheckConstraint(_in("status", LABOUR_BILL_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # LB/26-27/0001
    kind: Mapped[str] = mapped_column(String(10))
    contractor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    bill_date: Mapped[date] = mapped_column(Date)
    gross: Mapped[Decimal] = mapped_column(Money, server_default="0")
    tds_section: Mapped[str | None] = mapped_column(String(8))
    tds_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    tds: Mapped[Decimal] = mapped_column(Money, server_default="0")
    tds_note: Mapped[str | None] = mapped_column(Text)
    net: Mapped[Decimal] = mapped_column(Money, server_default="0")
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vendor_bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["LabourBillLine"]] = relationship(
        order_by="LabourBillLine.id", cascade="all, delete-orphan", lazy="selectin"
    )


class LabourBillLine(Base):
    """One site's part of a labour bill. Piece rate: a contract line (the area and item billed to
    the client) and the job's rate; the quantity is what the client was billed (or certified, when
    less), never typed. Attendance: the gang's hours on that site in the period."""

    __tablename__ = "labour_bill_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        ForeignKey("labour_bills.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    contract_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_lines.id", ondelete="SET NULL")
    )
    rate_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("labour_rate_cards.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(String(10))  # billed, certified, hours
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(10))
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
