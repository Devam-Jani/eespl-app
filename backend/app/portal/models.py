"""Client portal: which client users exist and what they may see, invites, per-site portal
settings, documents, snags, comments and in-app notifications.

A client user sees a site only when (1) the site's client is one of theirs (client_users),
(2) the site is visible in the portal (site_portal.visible) and (3) they were given that site
(client_user_sites). Every portal query goes through app.portal.service.portal_site().
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.finance.models  # noqa: F401  (RA bills, invoices)
from app.masters.models import Tracked
from app.models import Base

SECTIONS = ("overview", "dpr", "photos", "inspections", "documents", "billing", "snags")
SNAG_STATUSES = ("open", "in_progress", "fixed", "verified", "closed")
COMMENT_ON = ("dpr", "inspection", "snag", "ra_bill")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ClientUser(Base):
    """A login of the client: a user linked to one or more customers."""

    __tablename__ = "client_users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ClientUserSite(Base):
    """The sites a client user was given (still only while the site is theirs and visible)."""

    __tablename__ = "client_user_sites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PortalInvite(Tracked, Base):
    """A one-time link to set a password. Only the token's hash is stored."""

    __tablename__ = "portal_invites"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SitePortal(Tracked, Base):
    """What a site shows in the portal. Hidden until staff switch it on."""

    __tablename__ = "site_portal"

    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    visible: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # {section: shown}; a section missing is shown
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class SiteDocument(Tracked, Base):
    """A document of a site: uploaded by staff (shared with the client when ticked) or by the
    client (stored apart, under portal/client-uploads)."""

    __tablename__ = "site_documents"
    __table_args__ = (CheckConstraint("source IN ('staff', 'client')", name="source_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), server_default="document")  # drawing, document
    source: Mapped[str] = mapped_column(String(6), server_default="staff")
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))
    share_with_client: Mapped[bool] = mapped_column(Boolean, server_default="false")
    remark: Mapped[str | None] = mapped_column(Text)


class Snag(Tracked, Base):
    __tablename__ = "snags"
    __table_args__ = (
        CheckConstraint(_in("status", SNAG_STATUSES), name="status_valid"),
        CheckConstraint("raised_by_side IN ('client', 'staff')", name="side_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # SNG-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    area: Mapped[str | None] = mapped_column(String(200))  # free text when no node
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    raised_by_side: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(12), server_default="open", index=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened: Mapped[int] = mapped_column(server_default="0")

    photos: Mapped[list["SnagPhoto"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="SnagPhoto.id"
    )


class SnagPhoto(Tracked, Base):
    __tablename__ = "snag_photos"
    __table_args__ = (CheckConstraint("kind IN ('before', 'after')", name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    snag_id: Mapped[int] = mapped_column(ForeignKey("snags.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(6), server_default="before")
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))


class Comment(Base):
    """A comment on a DPR, inspection, snag or RA bill. Internal notes are staff-only."""

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(_in("entity_type", COMMENT_ON), name="entity_valid"),
        Index("ix_comments_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(12))
    entity_id: Mapped[int] = mapped_column()
    body: Mapped[str] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(Boolean, server_default="false")
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_side: Mapped[str] = mapped_column(String(6))  # client | staff
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """An in-app notification (the bell)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class NotificationOutbox(Base):
    """Delivery of a notification per channel. Only 'in_app' now (delivered when written);
    M8 adds email / SMS / WhatsApp rows that a worker sends."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint("channel IN ('in_app', 'email', 'sms', 'whatsapp')", name="channel_valid"),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(10), server_default="in_app")
    status: Mapped[str] = mapped_column(String(8), server_default="sent")
    attempts: Mapped[int] = mapped_column(server_default="0")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
