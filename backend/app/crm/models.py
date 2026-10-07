"""CRM leads, their activity timeline, and the Kylas sync (outbox + poll cursors)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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

import app.tenders.models  # noqa: F401  (leads point at tenders)
from app.masters.models import Channel, Client, Tracked
from app.models import Base, User

LEAD_SOURCES = ("website", "call", "referral", "channel", "walk_in", "exhibition", "other")
LEAD_STATUSES = ("new", "contacted", "site_visit", "quoted", "won", "lost", "junk")
CLOSED_STATUSES = ("won", "lost", "junk")
ACTIVITY_TYPES = ("note", "call", "visit", "status_change", "kylas")
SYNC_STATUSES = ("disabled", "pending", "synced", "failed")
OUTBOX_STATUSES = ("pending", "unknown", "done", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class LeadSequence(Base):
    __tablename__ = "lead_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer)


class Lead(Tracked, Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(_in("status", LEAD_STATUSES), name="status_valid"),
        CheckConstraint(_in("lead_source", LEAD_SOURCES), name="source_valid"),
        CheckConstraint(_in("kylas_sync_status", SYNC_STATUSES), name="sync_status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # L-2026-0001
    contact_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)  # +91XXXXXXXXXX
    email: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    lead_source: Mapped[str] = mapped_column(String(12), server_default="other")
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), index=True
    )
    requirement: Mapped[str | None] = mapped_column(Text)
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    work_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    est_area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    est_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(12), server_default="new", index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    next_follow_up: Mapped[date | None] = mapped_column(Date, index=True)
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="SET NULL"), index=True
    )
    # Kylas: created there once, never updated from here; outcomes are polled back.
    kylas_lead_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    kylas_owner_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_sync_status: Mapped[str] = mapped_column(String(10), server_default="disabled")
    kylas_last_error: Mapped[str | None] = mapped_column(Text)  # never holds a secret
    kylas_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kylas_forecasting: Mapped[str | None] = mapped_column(String(30))  # OPEN / CLOSED_* in Kylas
    kylas_converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kylas_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    kylas_won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    channel: Mapped[Channel | None] = relationship(lazy="joined")
    client: Mapped[Client | None] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[owner_id])
    creator: Mapped[User | None] = relationship(lazy="joined", foreign_keys="Lead.created_by")


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    __table_args__ = (CheckConstraint(_in("type", ACTIVITY_TYPES), name="type_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(15))
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    author: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[by])


class KylasOutbox(Base):
    """One row per lead to create in Kylas, written in the lead's own transaction. The worker
    claims due rows with FOR UPDATE SKIP LOCKED (see app.crm.kylas_push)."""

    __tablename__ = "kylas_outbox"
    __table_args__ = (CheckConstraint(_in("status", OUTBOX_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(10), server_default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KylasCursor(Base):
    """Where a poll got to (deal search: the newest updatedAt seen)."""

    __tablename__ = "kylas_cursors"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_ids: Mapped[list[int] | None] = mapped_column(JSONB)
