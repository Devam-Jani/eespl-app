"""Site survey: areas measured on site (laser, by hand, AR or the marker photo), the
waterproofing system per area, and from them product quantities per area, floor and survey.

Sizes are stored in metres (and sqm); every computed area is recalculated from the inputs on
each change (service.compute), never typed in.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

M = Numeric(12, 3)  # metres / sqm
Pct = Numeric(6, 2)

SURVEY_STATUSES = ("draft", "submitted", "approved")
SHAPES = ("rect", "polygon", "direct")
METHODS = ("laser", "manual", "ar", "marker", "cad", "label")
CAMERA_METHODS = ("ar", "marker")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class AreaType(Tracked, Base):
    """Terrace, toilet, sunken slab ... with their default system, upturn and wastage. Seeded
    unconfirmed: the team ticks `confirmed` once they agree with the defaults."""

    __tablename__ = "area_types"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    default_system_id: Mapped[int | None] = mapped_column(
        ForeignKey("systems.id", ondelete="SET NULL")
    )
    default_upturn_mm: Mapped[Decimal] = mapped_column(Numeric(7, 1), server_default="0")
    # overrides each component's wastage when set
    default_wastage_percent: Mapped[Decimal | None] = mapped_column(Pct)
    includes_walls: Mapped[bool] = mapped_column(Boolean, server_default="false")
    needs_sunk_depth: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Survey(Tracked, Base):
    __tablename__ = "surveys"
    __table_args__ = (
        CheckConstraint(_in("status", SURVEY_STATUSES), name="status_valid"),
        CheckConstraint(
            "(lead_id IS NOT NULL)::int + (tender_id IS NOT NULL)::int "
            "+ (site_id IS NOT NULL)::int = 1",
            name="one_parent",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # SUR-2026-0001
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    surveyed_on: Mapped[date | None] = mapped_column(Date)
    surveyed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(10), server_default="draft", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    areas: Mapped[list["SurveyArea"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(SurveyArea.tower, SurveyArea.floor_no, SurveyArea.sort_order, SurveyArea.id)",
    )


class SurveyArea(Tracked, Base):
    __tablename__ = "survey_areas"
    __table_args__ = (
        CheckConstraint(_in("shape", SHAPES), name="shape_valid"),
        CheckConstraint(_in("method", METHODS), name="method_valid"),
        CheckConstraint(
            "camera_method IS NULL OR " + _in("camera_method", CAMERA_METHODS), name="camera_valid"
        ),
        CheckConstraint("count >= 1", name="count_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="SET NULL"), index=True
    )
    tower: Mapped[str | None] = mapped_column(String(60))
    floor_label: Mapped[str | None] = mapped_column(String(60))
    floor_no: Mapped[int | None] = mapped_column(Integer)  # for sorting: B1 = -1, G = 0, 1, 2 ...
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    name: Mapped[str] = mapped_column(String(200))
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    shape: Mapped[str] = mapped_column(String(8), server_default="rect")
    length_m: Mapped[Decimal | None] = mapped_column(M)
    width_m: Mapped[Decimal | None] = mapped_column(M)
    polygon_m: Mapped[list[list[float]] | None] = mapped_column(JSONB)  # [[x, y], ...] metres
    direct_area_sqm: Mapped[Decimal | None] = mapped_column(M)
    deductions_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    perimeter_m: Mapped[Decimal | None] = mapped_column(M)
    perimeter_manual: Mapped[bool] = mapped_column(Boolean, server_default="false")
    upturn_mm: Mapped[Decimal] = mapped_column(Numeric(7, 1), server_default="0")
    wall_height_m: Mapped[Decimal | None] = mapped_column(M)
    sunk_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    count: Mapped[int] = mapped_column(Integer, server_default="1")
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    wastage_override_percent: Mapped[Decimal | None] = mapped_column(Pct)
    method: Mapped[str] = mapped_column(String(8), server_default="manual")
    accuracy_note: Mapped[str | None] = mapped_column(String(300))
    remarks: Mapped[str | None] = mapped_column(Text)
    # the latest camera measurement, kept when a laser / manual size is entered later (pilot)
    camera_method: Mapped[str | None] = mapped_column(String(8))
    camera_floor_sqm: Mapped[Decimal | None] = mapped_column(M)
    camera_polygon_m: Mapped[list[list[float]] | None] = mapped_column(JSONB)
    # computed (service.compute)
    floor_area_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    upturn_area_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    wall_area_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    sunk_area_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    treated_area_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")  # x count
    ai_suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    photos: Mapped[list["SurveyPhoto"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SurveyPhoto.id",
    )


class SurveyPhoto(Tracked, Base):
    __tablename__ = "survey_photos"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    survey_area_id: Mapped[int] = mapped_column(
        ForeignKey("survey_areas.id", ondelete="CASCADE"), index=True
    )
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))
    overlay_path: Mapped[str | None] = mapped_column(String(400))  # the measurement drawn on it
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    gps_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    device: Mapped[str | None] = mapped_column(String(200))
    browser: Mapped[str | None] = mapped_column(String(300))
    tilt_beta: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))  # front-back, degrees
    tilt_gamma: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))  # left-right
    zoom: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str | None] = mapped_column(String(10))  # ar, marker, laser, manual, proof
    marker_found: Mapped[bool | None] = mapped_column(Boolean)
    blur_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    brightness: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))


class SurveyBoqLink(Base):
    """Which survey areas a tender BOQ line was made from."""

    __tablename__ = "survey_boq_links"

    boq_line_id: Mapped[int] = mapped_column(
        ForeignKey("boq_lines.id", ondelete="CASCADE"), primary_key=True
    )
    survey_area_id: Mapped[int] = mapped_column(
        ForeignKey("survey_areas.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class SurveySettings(Tracked, Base):
    """One row (id 1)."""

    __tablename__ = "survey_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_required: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # while off, RA bill quantities from survey areas need a laser / manual size (or the client's)
    camera_billing_allowed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mismatch_percent: Mapped[Decimal] = mapped_column(Pct, server_default="3")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ai_model: Mapped[str] = mapped_column(String(60), server_default="claude-sonnet-5-5")
    ai_monthly_cap_inr: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default="2000")
    # for the cost estimate of each call
    ai_usd_per_mtok_in: Mapped[Decimal] = mapped_column(Numeric(8, 3), server_default="3")
    ai_usd_per_mtok_out: Mapped[Decimal] = mapped_column(Numeric(8, 3), server_default="15")
    ai_inr_per_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="85")


class AiCall(Base):
    """Every photo suggestion asked of the model: what came back, the tokens and the cost."""

    __tablename__ = "ai_calls"
    __table_args__ = (CheckConstraint("status IN ('ok', 'error')", name="status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    survey_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("survey_areas.id", ondelete="SET NULL"), index=True
    )
    photo_id: Mapped[int | None] = mapped_column(
        ForeignKey("survey_photos.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(6))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_inr: Mapped[Decimal] = mapped_column(Numeric(10, 4), server_default="0")
    suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    accepted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
