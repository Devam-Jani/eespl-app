"""Field attendance, location tracking and the travel claim.

- Consent (India's DPDP Act 2023): one row per person per consent version; a new version asks
  again. Without consent a person works as before, but nothing is tracked and no claim is made.
- A day runs from Start day to End day (or the auto end at the set time): location points are
  taken only inside it. Stops: check-in / check-out at a site (selfie, location, accuracy) or at a
  vendor, godown, client office or other place with a note.
- Points come from the browser (while the app is open) or, later, the Android app; points with
  poor accuracy are kept but not used for km. A duplicate batch is not stored twice.
- Km: road km stop to stop (our own OSRM; straight line x 1.3 "estimated" while it is down) and
  tracked km from the good points. The claim uses road km unless the manager chose tracked km
  for a day, with a reason.
- Gangs: labour carry no phone; the supervisor checks a labour contractor's gang in and out of a
  site (names or a headcount, one group photo). Labour are never tracked and never claim.
- The monthly travel claim per eligible person: the days (km x the rate per km on that date)
  plus tolls and parking with a bill photo; manager, then accounts; approved is locked.
Location data is personal data: it stays on our server and clients never see it.
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
    Float,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

Money = Numeric(14, 2)
Km = Numeric(10, 3)
VEHICLES = ("bike", "car", "other")
STOP_KINDS = ("site", "vendor", "godown", "client_office", "other")
POINT_SOURCES = ("web", "android")
CLAIM_STATUSES = ("draft", "ready", "manager_approved", "approved")
EXTRA_KINDS = ("toll", "parking", "other")
HOME_STATUSES = ("none", "pending", "approved", "rejected")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class FieldSettings(Base):
    """One row (id 1): the day, the flags, the retention and the map tiles."""

    __tablename__ = "field_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consent_version: Mapped[str] = mapped_column(String(20), server_default="2026-10")
    auto_end_at: Mapped[time] = mapped_column(Time, server_default="21:00")  # IST
    site_radius_m: Mapped[int] = mapped_column(Integer, server_default="150")
    home_flag_m: Mapped[int] = mapped_column(Integer, server_default="500")
    point_every_s: Mapped[int] = mapped_column(Integer, server_default="120")
    point_move_m: Mapped[int] = mapped_column(Integer, server_default="100")
    accuracy_max_m: Mapped[int] = mapped_column(Integer, server_default="100")
    jitter_m: Mapped[int] = mapped_column(Integer, server_default="30")
    max_speed_kmh: Mapped[int] = mapped_column(Integer, server_default="120")
    gap_minutes: Mapped[int] = mapped_column(Integer, server_default="45")
    road_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2), server_default="1.3")
    raw_days: Mapped[int] = mapped_column(Integer, server_default="90")
    summary_years: Mapped[int] = mapped_column(Integer, server_default="8")
    tile_url: Mapped[str] = mapped_column(
        String(300), server_default="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    tile_attribution: Mapped[str] = mapped_column(
        String(300), server_default="© OpenStreetMap contributors"
    )


class Consent(Base):
    __tablename__ = "field_consents"
    __table_args__ = (UniqueConstraint("user_id", "version"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(20))
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackingProfile(Tracked, Base):
    """Per person (office_admin): tracked or not, eligible for travel reimbursement (office
    employees only), the vehicle, who they report to, and their home (picked by the person on the
    map, approved by office_admin; a change needs approval again)."""

    __tablename__ = "field_profiles"
    __table_args__ = (
        CheckConstraint(_in("vehicle", VEHICLES), name="vehicle_valid"),
        CheckConstraint(_in("home_status", HOME_STATUSES), name="home_status_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tracked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reimbursable: Mapped[bool] = mapped_column(Boolean, server_default="false")
    vehicle: Mapped[str] = mapped_column(String(6), server_default="bike")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    home_lat: Mapped[float | None] = mapped_column(Float)  # the approved home
    home_lng: Mapped[float | None] = mapped_column(Float)
    home_status: Mapped[str] = mapped_column(String(8), server_default="none")
    pending_lat: Mapped[float | None] = mapped_column(Float)  # asked for, waiting for approval
    pending_lng: Mapped[float | None] = mapped_column(Float)
    home_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    home_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TravelRate(Tracked, Base):
    """The rate per km from a date (typed by hand; the history is kept)."""

    __tablename__ = "field_travel_rates"
    __table_args__ = (
        CheckConstraint("rate_per_km >= 0", name="rate_nonnegative"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="dates_valid"),
        CheckConstraint(_in("vehicle", VEHICLES), name="vehicle_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    vehicle: Mapped[str] = mapped_column(String(6), server_default="bike")
    rate_per_km: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class FieldDay(Base):
    """A person's working day from Start day to End day, its km and its flags."""

    __tablename__ = "field_days"
    __table_args__ = (
        UniqueConstraint("user_id", "on_date"),
        CheckConstraint("km_basis IN ('route', 'tracked')", name="km_basis_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date, index=True)  # IST
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lng: Mapped[float | None] = mapped_column(Float)
    start_accuracy_m: Mapped[float | None] = mapped_column(Float)
    start_home_m: Mapped[float | None] = mapped_column(Float)  # distance from the approved home
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_lat: Mapped[float | None] = mapped_column(Float)
    end_lng: Mapped[float | None] = mapped_column(Float)
    end_accuracy_m: Mapped[float | None] = mapped_column(Float)
    end_home_m: Mapped[float | None] = mapped_column(Float)
    auto_ended: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # [{from, to, km, minutes, estimated}] home -> stop 1 -> ... -> home
    legs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    route_km: Mapped[Decimal | None] = mapped_column(Km)
    route_estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    tracked_km: Mapped[Decimal | None] = mapped_column(Km)
    km_basis: Mapped[str] = mapped_column(String(8), server_default="route")
    km_basis_reason: Mapped[str | None] = mapped_column(Text)
    km_basis_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    points_total: Mapped[int] = mapped_column(Integer, server_default="0")
    points_good: Mapped[int] = mapped_column(Integer, server_default="0")
    points_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stops: Mapped[list["FieldStop"]] = relationship(
        order_by="FieldStop.seq", cascade="all, delete-orphan", lazy="selectin"
    )


class FieldStop(Base):
    """A check-in and check-out: a site, or a vendor / godown / client office / other place."""

    __tablename__ = "field_stops"
    __table_args__ = (CheckConstraint(_in("kind", STOP_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("field_days.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(14))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    note: Mapped[str | None] = mapped_column(String(300))
    in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    in_lat: Mapped[float] = mapped_column(Float)
    in_lng: Mapped[float] = mapped_column(Float)
    in_accuracy_m: Mapped[float | None] = mapped_column(Float)
    in_distance_m: Mapped[float | None] = mapped_column(Float)  # from the site's pin
    in_outside: Mapped[bool] = mapped_column(Boolean, server_default="false")
    in_reason: Mapped[str | None] = mapped_column(Text)
    in_selfie: Mapped[str | None] = mapped_column(String(400))
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_lat: Mapped[float | None] = mapped_column(Float)
    out_lng: Mapped[float | None] = mapped_column(Float)
    out_accuracy_m: Mapped[float | None] = mapped_column(Float)
    out_distance_m: Mapped[float | None] = mapped_column(Float)
    out_outside: Mapped[bool] = mapped_column(Boolean, server_default="false")
    out_reason: Mapped[str | None] = mapped_column(Text)
    out_selfie: Mapped[str | None] = mapped_column(String(400))


class LocationPoint(Base):
    """A raw location point (deleted after the retention days; the day keeps its km)."""

    __tablename__ = "field_points"
    __table_args__ = (
        UniqueConstraint("user_id", "at"),  # a batch sent twice is stored once
        CheckConstraint(_in("source", POINT_SOURCES), name="source_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day_id: Mapped[int] = mapped_column(ForeignKey("field_days.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when it was taken
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(8), server_default="web")
    batch: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GangVisit(Tracked, Base):
    """A labour contractor's gang checked in and out of a site by the supervisor."""

    __tablename__ = "field_gang_visits"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    contractor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    supervisor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    on_date: Mapped[date] = mapped_column(Date, index=True)
    headcount: Mapped[int] = mapped_column(Integer)  # the named workers, or a count
    in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    in_lat: Mapped[float] = mapped_column(Float)
    in_lng: Mapped[float] = mapped_column(Float)
    in_accuracy_m: Mapped[float | None] = mapped_column(Float)
    in_distance_m: Mapped[float | None] = mapped_column(Float)
    in_outside: Mapped[bool] = mapped_column(Boolean, server_default="false")
    in_reason: Mapped[str | None] = mapped_column(Text)
    in_photo: Mapped[str | None] = mapped_column(String(400))
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_lat: Mapped[float | None] = mapped_column(Float)
    out_lng: Mapped[float | None] = mapped_column(Float)
    out_accuracy_m: Mapped[float | None] = mapped_column(Float)
    out_distance_m: Mapped[float | None] = mapped_column(Float)
    out_outside: Mapped[bool] = mapped_column(Boolean, server_default="false")
    out_reason: Mapped[str | None] = mapped_column(Text)
    out_photo: Mapped[str | None] = mapped_column(String(400))

    workers: Mapped[list["GangVisitWorker"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class GangVisitWorker(Base):
    __tablename__ = "field_gang_workers"
    __table_args__ = (UniqueConstraint("visit_id", "labour_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    visit_id: Mapped[int] = mapped_column(
        ForeignKey("field_gang_visits.id", ondelete="CASCADE"), index=True
    )
    labour_id: Mapped[int] = mapped_column(ForeignKey("labour.id", ondelete="CASCADE"))


class TravelClaim(Tracked, Base):
    """A person's travel claim for a month: built on the 1st from their days."""

    __tablename__ = "field_claims"
    __table_args__ = (
        UniqueConstraint("user_id", "month"),
        CheckConstraint(_in("status", CLAIM_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    month: Mapped[str] = mapped_column(String(7))  # 2026-10
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    km: Mapped[Decimal] = mapped_column(Km, server_default="0")
    days_amount: Mapped[Decimal] = mapped_column(Money, server_default="0")
    extras_amount: Mapped[Decimal] = mapped_column(Money, server_default="0")
    total: Mapped[Decimal] = mapped_column(Money, server_default="0")
    flagged_days: Mapped[int] = mapped_column(Integer, server_default="0")
    manager_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    manager_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # the payroll month it is paid with (reimbursement, outside the salary's gross)
    payroll_month: Mapped[str | None] = mapped_column(String(7))

    days: Mapped[list["TravelClaimDay"]] = relationship(
        order_by="TravelClaimDay.on_date", cascade="all, delete-orphan", lazy="selectin"
    )
    extras: Mapped[list["TravelClaimExtra"]] = relationship(
        order_by="TravelClaimExtra.on_date", cascade="all, delete-orphan", lazy="selectin"
    )


class TravelClaimDay(Base):
    __tablename__ = "field_claim_days"
    __table_args__ = (UniqueConstraint("claim_id", "on_date"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("field_claims.id", ondelete="CASCADE"), index=True
    )
    day_id: Mapped[int | None] = mapped_column(ForeignKey("field_days.id", ondelete="SET NULL"))
    on_date: Mapped[date] = mapped_column(Date)
    stops: Mapped[str] = mapped_column(Text, server_default="")
    km_basis: Mapped[str] = mapped_column(String(8), server_default="route")
    km: Mapped[Decimal] = mapped_column(Km)
    estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    rate_per_km: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    amount: Mapped[Decimal] = mapped_column(Money)
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    # the manager's change: the km (or the basis) with the reason, the earlier km kept
    edited_km_from: Mapped[Decimal | None] = mapped_column(Km)
    edit_reason: Mapped[str | None] = mapped_column(Text)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved: Mapped[bool] = mapped_column(Boolean, server_default="false")


class TravelClaimExtra(Base):
    """A toll, parking or other cost with its bill photo, added by the person."""

    __tablename__ = "field_claim_extras"
    __table_args__ = (
        CheckConstraint(_in("kind", EXTRA_KINDS), name="kind_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("field_claims.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(String(300))
    bill_path: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
