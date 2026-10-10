"""Team roles and workspaces (the 9 Oct planning and billing meeting): per-person extra rights the
director allows, who handles a won job, the site status board, the measurement book, site visits,
negotiations, tender bidders, and the team settings."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.masters.models import Tracked
from app.models import Base

Qty = Numeric(14, 3)
BOARD_COLUMNS = ("upcoming", "ongoing", "completed_to_bill")
MEASURE_SOURCES = ("laser", "manual", "camera", "client_certified", "autocad")
ASSIGNMENT_STATUSES = ("pending", "done")
# what the director can allow one person on top of their roles
GRANTABLE = ("tender.margin", "jobs.assign")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class UserGrant(Base):
    """An extra permission for one person (costs and margins for a planner, deciding won jobs),
    allowed by the director. Only the GRANTABLE codes."""

    __tablename__ = "user_grants"
    __table_args__ = (CheckConstraint(_in("permission_code", GRANTABLE), name="grantable"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamSettings(Base):
    """One row (id 1)."""

    __tablename__ = "team_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    billing_day: Mapped[int] = mapped_column(Integer, server_default="25")  # monthly RA bills
    award_followup_days: Mapped[int] = mapped_column(Integer, server_default="60")
    closure_target_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="30")
    # who receives the site allocation list (Kaka and others)
    allocation_recipients: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}"
    )
    allocation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAssignment(Base):
    """A won quotation or tender waiting for the director (or planning, when allowed) to pick its
    salesperson and site engineer."""

    __tablename__ = "job_assignments"
    __table_args__ = (CheckConstraint(_in("status", ASSIGNMENT_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="SET NULL"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), server_default="pending", index=True)
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    engineer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_visit_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_visits.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteVisit(Base):
    """A salesperson's (or engineer's) visit: date, notes, photos and GPS."""

    __tablename__ = "site_visits"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    visited_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    photos: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    first_after_win: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Negotiation(Base):
    """What the client asked ("match X on this item"), what we gave, and the revision that
    followed."""

    __tablename__ = "negotiations"
    __table_args__ = (
        CheckConstraint(
            "(quotation_id IS NOT NULL)::int + (tender_id IS NOT NULL)::int = 1", name="one_parent"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    asked: Mapped[str] = mapped_column(Text)
    given: Mapped[str | None] = mapped_column(Text)
    revision_quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    tender_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("tender_revisions.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Measurement(Tracked, Base):
    """The measurement book: every billable quantity with its source, date and who measured it.
    RA bills take their quantities only from here."""

    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint(_in("source", MEASURE_SOURCES), name="source_valid"),
        CheckConstraint("qty >= 0", name="qty_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    contract_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_lines.id", ondelete="SET NULL"), index=True
    )
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    survey_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("survey_areas.id", ondelete="SET NULL")
    )
    ready_id: Mapped[int | None] = mapped_column(
        ForeignKey("ready_to_bill.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(String(500))
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    measured_on: Mapped[date] = mapped_column(Date)
    measured_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)


class TenderBidder(Base):
    """Another contractor on a tender: their rate when known, the rank (L1, L2...) and the
    winner."""

    __tablename__ = "tender_bidders"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    rank: Mapped[int | None] = mapped_column(Integer)
    is_winner: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_us: Mapped[bool] = mapped_column(Boolean, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def board_label(column: str | None) -> str:
    return {
        "upcoming": "Upcoming",
        "ongoing": "Ongoing",
        "completed_to_bill": "Completed, to bill",
    }.get(column or "", "Not on the board")
