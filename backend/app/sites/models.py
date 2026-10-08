"""Sites: the structure tree, stage templates, scopes (what we do where), tasks and drawings.

Progress is stored as it changes (see app.sites.progress): a task update recomputes its area
scope, then that scope's node and its ancestors, then the site. Nothing recomputes a whole site
from its tasks on read.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.tenders.models  # noqa: F401  (sites point at tenders and BOQ lines)
from app.masters.models import Channel, Client, Tracked
from app.models import Base, User

SITE_STATUSES = ("planned", "active", "on_hold", "completed", "closed")
MEMBER_ROLES = ("incharge", "supervisor", "sales", "office", "viewer")
NODE_KINDS = (
    "tower",
    "wing",
    "basement",
    "floor",
    "flat",
    "toilet",
    "kitchen",
    "balcony",
    "terrace",
    "podium",
    "lift_pit",
    "ug_tank",
    "oh_tank",
    "retaining_wall",
    "raft",
    "stp",
    "swimming_pool",
    "other",
)
TASK_STATUSES = ("not_started", "in_progress", "done", "certified", "blocked")
DISCIPLINES = ("architectural", "structural", "waterproofing", "other")
DRAWING_STATUSES = ("draft", "submitted", "approved", "rejected")
SITE_SOURCES = ("app", "powerplay")

Percent = Numeric(6, 2)
Qty = Numeric(14, 3)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class SiteSequence(Base):
    """Last number used per year for site codes (S-2026-0001)."""

    __tablename__ = "site_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer)


class Site(Tracked, Base):
    __tablename__ = "sites"
    __table_args__ = (
        CheckConstraint(_in("status", SITE_STATUSES), name="status_valid"),
        CheckConstraint(_in("source", SITE_SOURCES), name="source_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # S-2026-0001
    name: Mapped[str] = mapped_column(String(300))
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), index=True
    )
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="SET NULL"), unique=True
    )
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    start_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), server_default="planned", index=True)
    site_incharge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), server_default="app")
    source_ref: Mapped[str | None] = mapped_column(String(50), unique=True)  # Powerplay id
    progress_percent: Mapped[Decimal] = mapped_column(Percent, server_default="0")  # stored

    client: Mapped[Client | None] = relationship(lazy="joined")
    channel: Mapped[Channel | None] = relationship(lazy="joined")
    incharge: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[site_incharge_id])
    members: Mapped[list["SiteMember"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class SiteMember(Tracked, Base):
    __tablename__ = "site_members"
    __table_args__ = (CheckConstraint(_in("role_on_site", MEMBER_ROLES), name="role_valid"),)

    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role_on_site: Mapped[str] = mapped_column(String(12), server_default="viewer")

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class SiteNode(Tracked, Base):
    """One place on site: tower > floor > flat > toilet, or a raft, a UG tank, a terrace ..."""

    __tablename__ = "site_nodes"
    __table_args__ = (
        CheckConstraint(_in("kind", NODE_KINDS), name="kind_valid"),
        Index("ix_site_nodes_site_parent", "site_id", "parent_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    level_no: Mapped[int | None] = mapped_column(Integer)  # B2 = -2, G = 0, 14th floor = 14
    area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progress_percent: Mapped[Decimal] = mapped_column(Percent, server_default="0")  # stored


class StageTemplate(Tracked, Base):
    """The steps of one kind of work (toilet coating, APP terrace ...) with their weights."""

    __tablename__ = "stage_templates"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    work_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    # words that suggest this template for a BOQ line ("toilet sunk bath wet")
    keywords: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(server_default="true")

    steps: Mapped[list["StageTemplateStep"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StageTemplateStep.sort_order",
    )


class StageTemplateStep(Tracked, Base):
    __tablename__ = "stage_template_steps"
    __table_args__ = (
        CheckConstraint("weight_percent >= 0 AND weight_percent <= 100", name="weight_range"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("stage_templates.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    weight_percent: Mapped[Decimal] = mapped_column(Percent)
    needs_photo: Mapped[bool] = mapped_column(server_default="true")
    needs_inspection: Mapped[bool] = mapped_column(server_default="false")
    hold_point: Mapped[bool] = mapped_column(server_default="false")  # certify before next step
    # certifying the hold point needs a passed inspection with this checklist
    checklist_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("checklist_templates.id", ondelete="SET NULL")
    )
    typical_days: Mapped[int] = mapped_column(Integer, server_default="1")


class AreaScope(Tracked, Base):
    """What we do where: a BOQ line's work on one node, with its share of the quantity."""

    __tablename__ = "area_scopes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="CASCADE"), index=True
    )
    boq_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_lines.id", ondelete="SET NULL"), index=True
    )
    stage_template_id: Mapped[int] = mapped_column(
        ForeignKey("stage_templates.id", ondelete="RESTRICT")
    )
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str | None] = mapped_column(String(20))
    progress_percent: Mapped[Decimal] = mapped_column(Percent, server_default="0")  # stored


class Task(Tracked, Base):
    """One step of one area scope (or a sub-task of such a task)."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status_valid"),
        CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="progress"),
        Index(
            "uq_tasks_scope_step",
            "area_scope_id",
            "step_id",
            unique=True,
            postgresql_where="parent_task_id IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_nodes.id", ondelete="CASCADE"), index=True
    )
    area_scope_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_scopes.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[int | None] = mapped_column(
        ForeignKey("stage_template_steps.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), server_default="not_started", index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    progress_percent: Mapped[Decimal] = mapped_column(Percent, server_default="0")
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    depends_on: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), server_default="{}")
    remark: Mapped[str | None] = mapped_column(Text)
    # [{"item": "No leakage after 48 h", "passed": true}, ...]
    inspection: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    certified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    step: Mapped[StageTemplateStep | None] = relationship(lazy="joined")
    assignee: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[assignee_id])
    photos: Mapped[list["TaskPhoto"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class TaskPhoto(Tracked, Base):
    __tablename__ = "task_photos"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    stored_path: Mapped[str] = mapped_column(String(400))  # under the media volume
    filename: Mapped[str] = mapped_column(String(200))
    share_with_client: Mapped[bool] = mapped_column(server_default="false")  # portal


class Drawing(Tracked, Base):
    __tablename__ = "drawings"
    __table_args__ = (CheckConstraint(_in("discipline", DISCIPLINES), name="discipline_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    discipline: Mapped[str] = mapped_column(String(15), server_default="waterproofing")
    share_with_client: Mapped[bool] = mapped_column(server_default="false")  # portal
    # the latest approved revision (None until one is approved)
    current_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("drawing_revisions.id", ondelete="SET NULL", use_alter=True)
    )

    revisions: Mapped[list["DrawingRevision"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DrawingRevision.rev_no",
        foreign_keys="DrawingRevision.drawing_id",
    )


class DrawingRevision(Tracked, Base):
    __tablename__ = "drawing_revisions"
    __table_args__ = (
        CheckConstraint(_in("status", DRAWING_STATUSES), name="status_valid"),
        UniqueConstraint("drawing_id", "rev_no"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    drawing_id: Mapped[int] = mapped_column(
        ForeignKey("drawings.id", ondelete="CASCADE"), index=True
    )
    rev_no: Mapped[int] = mapped_column(Integer)  # 0, 1 ... shown as R0, R1
    stored_path: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)

    uploader: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[uploaded_by])
    approver: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[approved_by])

    @property
    def rev(self) -> str:
        return f"R{self.rev_no}"
