"""Site control (the 9 Oct planning and billing meeting): delivery notes confirmed at site,
discrepancies and debit-note drafts, vendor rate contracts, "ready to bill" when a stage is done,
new-area requests, labour productivity norms, and the settings for all of them.

A delivery note's receipt link carries a random token (192 bits) of which only the SHA-256 hash
is stored; the link opens one delivery's items and counts, never rates or values.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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

from app.masters.models import Money, Tracked
from app.models import Base

Qty = Numeric(14, 3)
DN_STATUSES = ("dispatched", "confirmed", "short", "cancelled")
DN_KINDS = ("po", "transfer")
DISCREPANCY_KINDS = ("short", "damaged")
AREA_REQUEST_STATUSES = ("pending", "approved", "rejected")
READY_STATUSES = ("open", "billed", "dismissed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class SiteControlSettings(Base):
    """One row (id 1)."""

    __tablename__ = "sitecontrol_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_link_days: Mapped[int] = mapped_column(Integer, server_default="7")
    escalate_first_hours: Mapped[int] = mapped_column(
        Integer, server_default="24"
    )  # site in-charge
    escalate_second_hours: Mapped[int] = mapped_column(Integer, server_default="48")  # planning
    planning_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )  # none: the office admins
    bill_alert_days: Mapped[int] = mapped_column(Integer, server_default="7")
    contract_expiry_days: Mapped[int] = mapped_column(Integer, server_default="15")
    productivity_drop_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="20")
    consumption_tolerance_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default="15"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeliveryNote(Tracked, Base):
    """One dispatch to a site: a PO delivery straight to the site or a godown-to-site transfer."""

    __tablename__ = "delivery_notes"
    __table_args__ = (
        CheckConstraint(_in("status", DN_STATUSES), name="status_valid"),
        CheckConstraint(_in("kind", DN_KINDS), name="kind_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # DN-2026-0001
    kind: Mapped[str] = mapped_column(String(10))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"))
    po_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True
    )
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfers.id", ondelete="SET NULL"), index=True
    )
    grn_id: Mapped[int | None] = mapped_column(ForeignKey("grns.id", ondelete="SET NULL"))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), server_default="dispatched", index=True)
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vehicle_no: Mapped[str | None] = mapped_column(String(30))
    driver_name: Mapped[str | None] = mapped_column(String(100))
    driver_phone: Mapped[str | None] = mapped_column(String(20))
    # the receipt link: only the token's hash is kept
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_path: Mapped[str | None] = mapped_column(String(300))
    # the receipt
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receiver_name: Mapped[str | None] = mapped_column(String(100))
    receiver_phone: Mapped[str | None] = mapped_column(String(20))
    receiver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    unlisted_receiver: Mapped[bool] = mapped_column(Boolean, server_default="false")
    photo_goods: Mapped[str | None] = mapped_column(String(300))
    photo_challan: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    gps_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    # the driver's drop-off photo when no one at site confirms: proof of drop-off, not quantity
    drop_photo: Mapped[str | None] = mapped_column(String(300))
    drop_photo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drop_photo_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    lines: Mapped[list["DeliveryNoteLine"]] = relationship(
        order_by="DeliveryNoteLine.id", cascade="all, delete-orphan"
    )


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id", ondelete="SET NULL"))
    transfer_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_lines.id", ondelete="SET NULL")
    )
    qty: Mapped[Decimal] = mapped_column(Qty)  # dispatched, in the line unit
    unit: Mapped[str] = mapped_column(String(10))
    base_qty: Mapped[Decimal] = mapped_column(Qty)
    packs: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    pack_unit: Mapped[str | None] = mapped_column(String(20))
    received_qty: Mapped[Decimal | None] = mapped_column(Qty)  # counted at site (line unit)
    damaged_qty: Mapped[Decimal | None] = mapped_column(Qty)


class Discrepancy(Base):
    """Received below dispatched (short) or damaged, on one delivery line."""

    __tablename__ = "delivery_discrepancies"
    __table_args__ = (CheckConstraint(_in("kind", DISCREPANCY_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="CASCADE"), index=True
    )
    line_id: Mapped[int] = mapped_column(ForeignKey("delivery_note_lines.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(10))
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(10))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    debit_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("debit_notes.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DebitNote(Tracked, Base):
    """A draft debit note against the vendor for a short or damaged PO delivery."""

    __tablename__ = "debit_notes"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'issued', 'cancelled')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # DBN-2026-0001
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"))
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"))
    delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    amount: Mapped[Decimal] = mapped_column(Money, server_default="0")
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    remark: Mapped[str | None] = mapped_column(Text)


class RateContract(Tracked, Base):
    """The rate agreed with a vendor for a product, per base unit, for a period. One active
    contract per vendor and product on any date; every change keeps a version."""

    __tablename__ = "rate_contracts"
    __table_args__ = (CheckConstraint("valid_till >= valid_from", name="period_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 4))  # per base unit
    freight_terms: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_till: Mapped[date] = mapped_column(Date)
    agreed_by: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    attachment_path: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class RateContractVersion(Base):
    __tablename__ = "rate_contract_versions"
    __table_args__ = (UniqueConstraint("contract_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("rate_contracts.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReadyToBill(Base):
    """A stage finished on a place (its last task done): billing raises it on the RA bill."""

    __tablename__ = "ready_to_bill"
    __table_args__ = (CheckConstraint(_in("status", READY_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("site_nodes.id", ondelete="CASCADE"))
    area_scope_id: Mapped[int] = mapped_column(
        ForeignKey("area_scopes.id", ondelete="CASCADE"), index=True
    )
    stage_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("stage_templates.id", ondelete="SET NULL")
    )
    boq_line_id: Mapped[int | None] = mapped_column(ForeignKey("boq_lines.id", ondelete="SET NULL"))
    contract_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_lines.id", ondelete="SET NULL")
    )
    qty: Mapped[Decimal] = mapped_column(Qty)  # measured (progress / survey)
    unit: Mapped[str | None] = mapped_column(String(20))
    survey_qty: Mapped[Decimal | None] = mapped_column(Qty)
    camera_only: Mapped[bool] = mapped_column(Boolean, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="open", index=True)
    ra_bill_id: Mapped[int | None] = mapped_column(ForeignKey("ra_bills.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewAreaRequest(Base):
    """An area not on the site's list, asked for from the phone; planning approves or rejects."""

    __tablename__ = "new_area_requests"
    __table_args__ = (CheckConstraint(_in("status", AREA_REQUEST_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    parent_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    approx_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    photo: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="pending", index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="SET NULL")
    )  # approved: the new place
    moved_to_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="SET NULL")
    )  # rejected: where the booked work went


class ProductivityNorm(Tracked, Base):
    """Expected sqm per man-day for a system (or an area type when the system has none)."""

    __tablename__ = "productivity_norms"
    __table_args__ = (
        CheckConstraint("system_id IS NOT NULL OR area_type_id IS NOT NULL", name="target_set"),
        UniqueConstraint("system_id"),
        UniqueConstraint("area_type_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"))
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="CASCADE")
    )
    sqm_per_manday: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # empty: "to be set"
