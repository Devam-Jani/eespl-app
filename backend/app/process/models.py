"""The process chain: rules (editable seeds of app.process.rules), the events every step writes,
each person's choice of channel per rule, and the settings (default user per role, wastage per
application, the daily summary hour)."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

EMAIL_MODES = ("app", "email", "summary")


class ProcessRule(Base):
    """Event -> who is told (by role), the message and action, what closes it, the escalation."""

    __tablename__ = "process_rules"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    number: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    event: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    # [{role, message, action?, info?, when?, link?, closed_by?}]
    recipients: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    link: Mapped[str | None] = mapped_column(String(300))
    closed_by: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    # [{after_hours, to: [roles]}], in order; information-only rules have none
    escalations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    email: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ProcessEvent(Base):
    """One step of the chain done: what, on which site, about which record, who, when (UTC).
    The dedupe key makes a retried step a no-op."""

    __tablename__ = "process_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(60), index=True)  # e.g. ready:12, ra:3, lead:7
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ProcessPreference(Base):
    """A person's channel for one rule: app only, app and email, or the 9:00 daily summary."""

    __tablename__ = "process_preferences"
    __table_args__ = (CheckConstraint("mode IN ('app', 'email', 'summary')", name="mode_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    rule_code: Mapped[str] = mapped_column(
        ForeignKey("process_rules.code", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(10))


class ProcessSettings(Base):
    """One row (id 1)."""

    __tablename__ = "process_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # role -> the user told when a site has nobody in that role (planning: the planning head's user)
    default_users: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    # application -> {min, max} wastage percent (raft 5-7, footing 12-15); planning uses max
    wastage: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    summary_hour: Mapped[int] = mapped_column(Integer, server_default="9")  # IST
    last_summary_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
