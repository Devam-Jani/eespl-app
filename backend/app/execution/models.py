"""Site execution: daily progress reports, labour and attendance, staff check-in, subcontractor
work orders and measurements, checklist inspections, minutes of meeting, tools / equipment and
their usage, and the site budget.
"""

import uuid
from datetime import date, datetime, time
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
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.material.models  # noqa: F401  (stores)
from app.masters.models import Tracked, Vendor
from app.models import Base

Qty = Numeric(14, 3)
Money = Numeric(14, 2)
Rate = Numeric(14, 4)

DPR_STATUSES = ("draft", "submitted", "acknowledged")
TRADES = ("applicator", "helper", "mason", "supervisor", "other")
LABOUR_TYPES = ("own", "subcontractor")
ATTENDANCE = ("present", "half_day", "absent")
WO_STATUSES = ("draft", "approved", "active", "completed", "closed")
MEASURE_STATUSES = ("recorded", "pending_approval", "verified", "rejected")
ITEM_TYPES = ("pass_fail", "number", "text", "photo")
RESULTS = ("pass", "fail", "pass_with_remarks")
POINT_STATUSES = ("open", "done", "dropped")
ASSET_CATEGORIES = ("tool", "equipment", "machine", "vehicle")
ASSET_STATUSES = ("available", "at_site", "repair", "lost", "disposed")
BUDGET_HEADS = ("material", "labour", "subcontract", "equipment", "freight", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# --- DPR -----------------------------------------------------------------------------------------


class Dpr(Tracked, Base):
    """One daily progress report per site per day. `auto` is the day's pulled-in activity, frozen
    when the report is submitted (live while it is a draft)."""

    __tablename__ = "dprs"
    __table_args__ = (
        UniqueConstraint("site_id", "on_date"),
        CheckConstraint(_in("status", DPR_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    weather: Mapped[str | None] = mapped_column(String(60))
    work_done: Mapped[str | None] = mapped_column(Text)
    hindrances: Mapped[str | None] = mapped_column(Text)
    next_day_plan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="draft")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    photos: Mapped[list["DprPhoto"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="DprPhoto.id"
    )


class DprPhoto(Tracked, Base):
    __tablename__ = "dpr_photos"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    dpr_id: Mapped[int] = mapped_column(ForeignKey("dprs.id", ondelete="CASCADE"), index=True)
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))
    caption: Mapped[str | None] = mapped_column(String(300))


# --- labour --------------------------------------------------------------------------------------


class Labour(Tracked, Base):
    """A worker. Only the last 4 digits of the Aadhaar number are ever stored."""

    __tablename__ = "labour"
    __table_args__ = (
        CheckConstraint(_in("trade", TRADES), name="trade_valid"),
        CheckConstraint(_in("type", LABOUR_TYPES), name="type_valid"),
        CheckConstraint("aadhaar_last4 ~ '^[0-9]{4}$'", name="aadhaar_last4_only"),
        CheckConstraint(
            "(type = 'subcontractor') = (subcontractor_id IS NOT NULL)", name="subcontractor_set"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    trade: Mapped[str] = mapped_column(String(12), server_default="helper")
    type: Mapped[str] = mapped_column(String(14), server_default="own")
    subcontractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[int | None] = mapped_column(  # the site the worker is posted to now
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    daily_wage: Mapped[Decimal] = mapped_column(Money, server_default="0")
    ot_rate_per_hour: Mapped[Decimal] = mapped_column(Money, server_default="0")
    aadhaar_last4: Mapped[str | None] = mapped_column(String(4))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    subcontractor: Mapped[Vendor | None] = relationship(lazy="joined")


class Attendance(Tracked, Base):
    """A worker's day: one row per worker per date, so nobody is at two sites the same day."""

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("labour_id", "on_date"),
        CheckConstraint(_in("status", ATTENDANCE), name="status_valid"),
        CheckConstraint("ot_hours >= 0 AND ot_hours <= 16", name="ot_hours_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    labour_id: Mapped[int] = mapped_column(ForeignKey("labour.id", ondelete="CASCADE"))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10))
    in_time: Mapped[time | None] = mapped_column(Time)
    out_time: Mapped[time | None] = mapped_column(Time)
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), server_default="0")
    # wage and OT rate on the day, so a later wage change does not rewrite past muster rolls
    daily_wage: Mapped[Decimal] = mapped_column(Money, server_default="0")
    ot_rate_per_hour: Mapped[Decimal] = mapped_column(Money, server_default="0")
    marked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    photo_path: Mapped[str | None] = mapped_column(String(400))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    labour: Mapped[Labour] = relationship(lazy="joined")


class StaffAttendance(Base):
    """A user's check-in / check-out at a site (feeds payroll in M5)."""

    __tablename__ = "staff_attendance"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))


# --- subcontractor work orders -------------------------------------------------------------------


class WorkOrder(Tracked, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(_in("status", WO_STATUSES), name="status_valid"),
        CheckConstraint("material_by IN ('eespl', 'subcontractor')", name="material_by_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # WO-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    subcontractor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    material_by: Mapped[str] = mapped_column(String(14), server_default="eespl")
    retention_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="5")
    tds_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="2")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    tc_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="draft", index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Money, server_default="0")  # sum of the lines

    subcontractor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list["WoLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="WoLine.id"
    )


class WoLine(Tracked, Base):
    __tablename__ = "wo_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    wo_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    area_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_scopes.id", ondelete="SET NULL")
    )
    boq_line_id: Mapped[int | None] = mapped_column(ForeignKey("boq_lines.id", ondelete="SET NULL"))
    unit: Mapped[str] = mapped_column(String(20))
    qty: Mapped[Decimal] = mapped_column(Qty)
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)

    measurements: Mapped[list["WoMeasurement"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WoMeasurement.id",
    )


class WoMeasurement(Tracked, Base):
    """Work done on a line. Beyond the line's WO qty it waits for subcon.approve."""

    __tablename__ = "wo_measurements"
    __table_args__ = (
        CheckConstraint(_in("status", MEASURE_STATUSES), name="status_valid"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("wo_lines.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date)
    qty: Mapped[Decimal] = mapped_column(Qty)
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="recorded")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")


# --- inspections and MOM -------------------------------------------------------------------------


class ChecklistTemplate(Tracked, Base):
    __tablename__ = "checklist_templates"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    items: Mapped[list["ChecklistItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChecklistItem.sort_order",
    )


class ChecklistItem(Tracked, Base):
    __tablename__ = "checklist_items"
    __table_args__ = (CheckConstraint(_in("type", ITEM_TYPES), name="type_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("checklist_templates.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(10), server_default="pass_fail")
    required: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Inspection(Tracked, Base):
    """A filled checklist. `answers` = [{item_id, text, type, value}] copied from the template
    so a later template edit does not change a signed inspection."""

    __tablename__ = "inspections"
    __table_args__ = (CheckConstraint(_in("result", RESULTS), name="result_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # INS-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("checklist_templates.id", ondelete="RESTRICT")
    )
    on_date: Mapped[date] = mapped_column(Date)
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(String(20))
    remark: Mapped[str | None] = mapped_column(Text)
    inspected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    client_rep: Mapped[str | None] = mapped_column(String(200))
    signature_path: Mapped[str | None] = mapped_column(String(400))
    # client sign-off in the portal: none | waiting | signed
    client_signoff: Mapped[str] = mapped_column(String(8), server_default="none")
    client_signed_name: Mapped[str | None] = mapped_column(String(200))
    client_signed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    client_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_signature_path: Mapped[str | None] = mapped_column(String(400))
    photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")

    template: Mapped[ChecklistTemplate] = relationship(lazy="joined")


class Mom(Tracked, Base):
    __tablename__ = "moms"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # MOM-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(300))
    venue: Mapped[str | None] = mapped_column(String(200))
    attendee_user_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    attendee_others: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    notes: Mapped[str | None] = mapped_column(Text)

    points: Mapped[list["MomPoint"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="MomPoint.id"
    )


class MomPoint(Tracked, Base):
    __tablename__ = "mom_points"
    __table_args__ = (CheckConstraint(_in("status", POINT_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    mom_id: Mapped[int] = mapped_column(ForeignKey("moms.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    owner_name: Mapped[str | None] = mapped_column(String(200))  # someone outside EESPL
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), server_default="open")
    client_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


# --- tools, assets and equipment -----------------------------------------------------------------


class Asset(Tracked, Base):
    """A tool, machine or vehicle: where it is now is store_id or site_id (one of them)."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(_in("category", ASSET_CATEGORIES), name="category_valid"),
        CheckConstraint(_in("status", ASSET_STATUSES), name="status_valid"),
        CheckConstraint("ownership IN ('own', 'hired')", name="ownership_valid"),
        CheckConstraint("ownership = 'own' OR vendor_id IS NOT NULL", name="hired_has_vendor"),
        CheckConstraint("store_id IS NULL OR site_id IS NULL", name="one_location"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # AST-0001
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(10), server_default="tool")
    make: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    serial_no: Mapped[str | None] = mapped_column(String(100))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_value: Mapped[Decimal | None] = mapped_column(Money)
    ownership: Mapped[str] = mapped_column(String(5), server_default="own")
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"))
    rate_per_hour: Mapped[Decimal | None] = mapped_column(Money)  # internal or hire rate
    rate_per_day: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(10), server_default="available", index=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    located_since: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    vendor: Mapped[Vendor | None] = relationship(lazy="joined")


class AssetMovement(Tracked, Base):
    __tablename__ = "asset_movements"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    from_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    from_site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    to_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    to_site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    on_date: Mapped[date] = mapped_column(Date)
    condition: Mapped[str | None] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(400))


class EquipmentUsage(Tracked, Base):
    """amount = hours x rate_per_hour or days x rate_per_day, plus the fuel cost."""

    __tablename__ = "equipment_usage"
    __table_args__ = (CheckConstraint("basis IN ('hour', 'day')", name="basis_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    basis: Mapped[str] = mapped_column(String(4), server_default="day")
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2))  # hours or days
    rate: Mapped[Decimal] = mapped_column(Money)
    fuel_litres: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="0")
    fuel_cost: Mapped[Decimal] = mapped_column(Money, server_default="0")
    operator: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money)
    remark: Mapped[str | None] = mapped_column(Text)


# --- budget --------------------------------------------------------------------------------------


class SiteBudget(Tracked, Base):
    __tablename__ = "site_budgets"
    __table_args__ = (
        UniqueConstraint("site_id", "head"),
        CheckConstraint(_in("head", BUDGET_HEADS), name="head_valid"),
        CheckConstraint("source IN ('tender', 'manual')", name="source_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    head: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(6), server_default="manual")


class SiteCost(Tracked, Base):
    """A cost entered by hand (the 'other' head, or a correction under any head)."""

    __tablename__ = "site_costs"
    __table_args__ = (CheckConstraint(_in("head", BUDGET_HEADS), name="head_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    head: Mapped[str] = mapped_column(String(12), server_default="other")
    on_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    description: Mapped[str] = mapped_column(Text)
