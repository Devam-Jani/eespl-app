"""Material: indents, RFQs, purchase orders, GRNs, stores, the stock ledger, transfers, site
issues and freight.

Stock is never a stored balance: it is the sum of the append-only stock_ledger per store and
product, in the product's base unit. Each row carries its rate and value, so the weighted average
rate is sum(value) / sum(qty). See app.material.stock.
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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.sites.models  # noqa: F401  (stores and indents point at sites and scopes)
from app.masters.models import Product, Tracked, Vendor
from app.models import Base

Qty = Numeric(14, 3)
Money = Numeric(14, 2)
Rate = Numeric(14, 4)

STORE_KINDS = ("godown", "site")
LEDGER_REFS = ("grn", "transfer_out", "transfer_in", "issue", "return", "adjust", "opening")
INDENT_STATUSES = (
    "draft",
    "submitted",
    "approved",
    "partly_ordered",
    "ordered",
    "closed",
    "rejected",
    "cancelled",
)
RFQ_STATUSES = ("draft", "sent", "closed", "cancelled")
PO_STATUSES = (
    "draft",
    "pending_approval",
    "approved",
    "sent",
    "partly_received",
    "received",
    "closed",
    "cancelled",
)
CHARGE_KINDS = ("freight", "loading", "unloading", "packing", "other")
GRN_STATUSES = ("draft", "submitted", "approved", "rejected")
TRANSFER_STATUSES = ("draft", "dispatched", "received", "cancelled")
FREIGHT_DIRECTIONS = ("inbound", "godown_to_site", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class DocSequence(Base):
    """Last number per document kind and period (IND 2026, PO 2026-27 ...)."""

    __tablename__ = "doc_sequences"

    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)


class Store(Tracked, Base):
    __tablename__ = "stores"
    __table_args__ = (CheckConstraint(_in("kind", STORE_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(10), server_default="godown")
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), unique=True
    )
    address: Mapped[str | None] = mapped_column(Text)
    gstin_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_gstins.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class StockLedger(Base):
    """Append-only. qty is signed and in the product's base unit; value = qty x rate."""

    __tablename__ = "stock_ledger"
    __table_args__ = (
        CheckConstraint(_in("ref_type", LEDGER_REFS), name="ref_type_valid"),
        Index("ix_stock_ledger_store_product", "store_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(20))
    rate: Mapped[Decimal] = mapped_column(Rate)
    value: Mapped[Decimal] = mapped_column(Money)
    ref_type: Mapped[str] = mapped_column(String(15))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# --- indents -------------------------------------------------------------------------------------


class Indent(Tracked, Base):
    __tablename__ = "indents"
    __table_args__ = (
        CheckConstraint(_in("status", INDENT_STATUSES), name="status_valid"),
        CheckConstraint("priority IN ('normal', 'urgent')", name="priority_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # IND-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"))
    required_by: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    status: Mapped[str] = mapped_column(String(15), server_default="draft", index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["IndentLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IndentLine.id",
    )


class IndentLine(Tracked, Base):
    """qty in `unit` as asked; base_qty in the product's unit. ordered / received in base."""

    __tablename__ = "indent_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    indent_id: Mapped[int] = mapped_column(ForeignKey("indents.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    free_text: Mapped[str | None] = mapped_column(String(300))  # not in the master: flagged
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(20))
    base_qty: Mapped[Decimal] = mapped_column(Qty)
    boq_line_id: Mapped[int | None] = mapped_column(ForeignKey("boq_lines.id", ondelete="SET NULL"))
    area_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_scopes.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)
    ordered_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")
    received_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")

    product: Mapped[Product | None] = relationship(lazy="joined")


# --- RFQ -----------------------------------------------------------------------------------------


class Rfq(Tracked, Base):
    __tablename__ = "rfqs"
    __table_args__ = (CheckConstraint(_in("status", RFQ_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # RFQ-2026-0001
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    remark: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["RfqLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="RfqLine.id"
    )
    vendors: Mapped[list["RfqVendor"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )
    quotes: Mapped[list["RfqQuote"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class RfqIndent(Base):
    __tablename__ = "rfq_indents"

    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True)
    indent_id: Mapped[int] = mapped_column(
        ForeignKey("indents.id", ondelete="CASCADE"), primary_key=True
    )


class RfqLine(Tracked, Base):
    __tablename__ = "rfq_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), index=True)
    indent_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("indent_lines.id", ondelete="SET NULL")
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(Qty)  # in the product's unit
    unit: Mapped[str] = mapped_column(String(20))
    chosen_vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL")
    )
    choice_reason: Mapped[str | None] = mapped_column(Text)  # when not the lowest landed rate

    product: Mapped[Product] = relationship(lazy="joined")


class RfqVendor(Tracked, Base):
    """An invited vendor; freight is the vendor's total freight for the RFQ (shared by value)."""

    __tablename__ = "rfq_vendors"

    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), primary_key=True
    )
    freight: Mapped[Decimal] = mapped_column(Money, server_default="0")

    vendor: Mapped[Vendor] = relationship(lazy="joined")


class RfqQuote(Tracked, Base):
    __tablename__ = "rfq_quotes"
    __table_args__ = (UniqueConstraint("rfq_line_id", "vendor_id"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), index=True)
    rfq_line_id: Mapped[int] = mapped_column(ForeignKey("rfq_lines.id", ondelete="CASCADE"))
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    rate: Mapped[Decimal] = mapped_column(Rate)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    freight: Mapped[Decimal] = mapped_column(Money, server_default="0")  # this line's own freight
    lead_days: Mapped[int | None] = mapped_column(Integer)
    valid_till: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(Text)


# --- purchase orders -----------------------------------------------------------------------------


class PurchaseOrder(Tracked, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (CheckConstraint(_in("status", PO_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(25), unique=True)  # PO-2026-27-000001
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    from_gstin_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_gstins.id", ondelete="SET NULL")
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), index=True)
    rfq_id: Mapped[int | None] = mapped_column(ForeignKey("rfqs.id", ondelete="SET NULL"))
    po_date: Mapped[date] = mapped_column(Date)
    expected_delivery: Mapped[date | None] = mapped_column(Date)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="draft", index=True)
    interstate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # totals, kept in step with the lines and charges (app.material.gst)
    subtotal: Mapped[Decimal] = mapped_column(Money, server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(Money, server_default="0")
    taxable: Mapped[Decimal] = mapped_column(Money, server_default="0")
    cgst: Mapped[Decimal] = mapped_column(Money, server_default="0")
    sgst: Mapped[Decimal] = mapped_column(Money, server_default="0")
    igst: Mapped[Decimal] = mapped_column(Money, server_default="0")
    charges_total: Mapped[Decimal] = mapped_column(Money, server_default="0")
    round_off: Mapped[Decimal] = mapped_column(Money, server_default="0")
    grand_total: Mapped[Decimal] = mapped_column(Money, server_default="0")

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list["PoLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="PoLine.id"
    )
    charges: Mapped[list["PoCharge"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="PoCharge.id"
    )


class PoIndent(Base):
    __tablename__ = "po_indents"

    po_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), primary_key=True
    )
    indent_id: Mapped[int] = mapped_column(
        ForeignKey("indents.id", ondelete="CASCADE"), primary_key=True
    )


class PoLine(Tracked, Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    po_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    indent_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("indent_lines.id", ondelete="SET NULL")
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(Qty)  # in `unit`
    unit: Mapped[str] = mapped_column(String(20))
    base_qty: Mapped[Decimal] = mapped_column(Qty)  # in the product's unit
    rate: Mapped[Decimal] = mapped_column(Rate)  # per `unit`, before discount
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="0")
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    amount: Mapped[Decimal] = mapped_column(Money)  # taxable: qty x rate less discount
    received_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")  # in `unit`

    product: Mapped[Product] = relationship(lazy="joined")


class PoCharge(Tracked, Base):
    __tablename__ = "po_charges"
    __table_args__ = (CheckConstraint(_in("kind", CHARGE_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    po_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))
    description: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="18")
    add_to_cost: Mapped[bool] = mapped_column(Boolean, server_default="true")  # into landed cost


# --- GRN -----------------------------------------------------------------------------------------


class Grn(Tracked, Base):
    __tablename__ = "grns"
    __table_args__ = (CheckConstraint(_in("status", GRN_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # GRN-2026-0001
    po_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"))
    challan_no: Mapped[str | None] = mapped_column(String(60))
    invoice_no: Mapped[str | None] = mapped_column(String(60))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_amount: Mapped[Decimal | None] = mapped_column(Money)
    vehicle_no: Mapped[str | None] = mapped_column(String(30))
    received_at: Mapped[date] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="draft", index=True)
    levels_required: Mapped[int] = mapped_column(Integer, server_default="1")
    approved_by_1: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at_1: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_2: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at_2: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(Text)

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list["GrnLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="GrnLine.id"
    )
    photos: Mapped[list["GrnPhoto"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="GrnPhoto.id"
    )


class GrnLine(Tracked, Base):
    """Quantities in `unit` (the PO line's unit); landed_rate per base unit, set on approval."""

    __tablename__ = "grn_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("grns.id", ondelete="CASCADE"), index=True)
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id", ondelete="SET NULL"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    unit: Mapped[str] = mapped_column(String(20))
    ordered_qty: Mapped[Decimal | None] = mapped_column(Qty)
    received_qty: Mapped[Decimal] = mapped_column(Qty)
    invoice_qty: Mapped[Decimal | None] = mapped_column(Qty)
    accepted_qty: Mapped[Decimal] = mapped_column(Qty)
    rejected_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")
    reason: Mapped[str | None] = mapped_column(Text)
    rate: Mapped[Decimal] = mapped_column(Rate)  # net of discount, per `unit`
    landed_rate: Mapped[Decimal | None] = mapped_column(Rate)  # per base unit, with costs added

    product: Mapped[Product] = relationship(lazy="joined")


class GrnPhoto(Tracked, Base):
    __tablename__ = "grn_photos"
    __table_args__ = (
        CheckConstraint("kind IN ('challan', 'invoice', 'material')", name="kind_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("grns.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), server_default="material")
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))


# --- transfers and site issues -------------------------------------------------------------------


class Transfer(Tracked, Base):
    __tablename__ = "transfers"
    __table_args__ = (CheckConstraint(_in("status", TRANSFER_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # TO-2026-0001
    from_store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), index=True
    )
    to_store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), server_default="draft", index=True)
    vehicle_no: Mapped[str | None] = mapped_column(String(30))
    transporter: Mapped[str | None] = mapped_column(String(200))
    freight_amount: Mapped[Decimal] = mapped_column(Money, server_default="0")
    remark: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    lines: Mapped[list["TransferLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TransferLine.id",
    )


class TransferLine(Tracked, Base):
    """Quantities in the product's unit; rate = the sending store's average at dispatch."""

    __tablename__ = "transfer_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty_sent: Mapped[Decimal] = mapped_column(Qty)
    qty_received: Mapped[Decimal | None] = mapped_column(Qty)
    shortage_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")
    shortage_reason: Mapped[str | None] = mapped_column(Text)
    rate: Mapped[Decimal | None] = mapped_column(Rate)

    product: Mapped[Product] = relationship(lazy="joined")


class SiteIssue(Tracked, Base):
    """Material used on site (issue) or brought back to the store (return)."""

    __tablename__ = "site_issues"
    __table_args__ = (CheckConstraint("kind IN ('issue', 'return')", name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # ISS-2026-0001
    kind: Mapped[str] = mapped_column(String(10), server_default="issue")
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    area_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_scopes.id", ondelete="SET NULL")
    )
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    issued_on: Mapped[date] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["SiteIssueLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SiteIssueLine.id",
    )


class SiteIssueLine(Base):
    __tablename__ = "site_issue_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("site_issues.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(Qty)  # in the product's unit
    rate: Mapped[Decimal] = mapped_column(Rate)
    value: Mapped[Decimal] = mapped_column(Money)

    product: Mapped[Product] = relationship(lazy="joined")


# --- freight -------------------------------------------------------------------------------------


class FreightEntry(Tracked, Base):
    """Every freight cost, charged to a site: a PO's freight charge (inbound), a transfer's freight
    (godown to site), or a standalone transporter bill."""

    __tablename__ = "freight_entries"
    __table_args__ = (
        CheckConstraint(_in("direction", FREIGHT_DIRECTIONS), name="direction_valid"),
        CheckConstraint("source IN ('po', 'transfer', 'bill')", name="source_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(10))
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    grn_id: Mapped[int | None] = mapped_column(ForeignKey("grns.id", ondelete="SET NULL"))
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[str] = mapped_column(String(15))
    on_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="0")
    transporter: Mapped[str | None] = mapped_column(String(200))
    vehicle_no: Mapped[str | None] = mapped_column(String(30))
    from_place: Mapped[str | None] = mapped_column(String(200))
    to_place: Mapped[str | None] = mapped_column(String(200))
    bill_no: Mapped[str | None] = mapped_column(String(60))
    remark: Mapped[str | None] = mapped_column(Text)
