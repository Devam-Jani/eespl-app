"""Material planned for the whole project and delivered in lots, and the per-site stage days that,
with the client's handover dates (on the site's places), drive the schedule.

- The project plan: per product, the whole site's quantity (from the BOQ and survey quantities
  with consumption and wastage), fixed by planning.
- Lots: the site calls off part of the plan for the work fronts that are ready (the next few
  days); each lot becomes an indent, then a delivery note as today. A call-off past the plan's
  balance plus the tolerance (5 %) waits for planning's approval, with a reason.
- Stage days: the stage template's days per stage, changed for one site.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

Qty = Numeric(14, 3)
LOT_STATUSES = ("approved", "pending", "rejected")


class ProjectPlanLine(Tracked, Base):
    __tablename__ = "project_plan_lines"
    __table_args__ = (UniqueConstraint("site_id", "product_id"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    planned_qty: Mapped[Decimal] = mapped_column(Qty)
    computed_qty: Mapped[Decimal | None] = mapped_column(Qty)  # from the BOQ and survey
    note: Mapped[str | None] = mapped_column(Text)  # why it differs from the computed figure


class MaterialLot(Tracked, Base):
    __tablename__ = "material_lots"
    __table_args__ = (
        CheckConstraint("status IN ('approved', 'pending', 'rejected')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # S-2026-0001/L3
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    days: Mapped[int | None] = mapped_column(Integer)  # "the next 4 days"
    need_by: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), server_default="approved")
    over_plan: Mapped[bool] = mapped_column(server_default="false")
    reason: Mapped[str | None] = mapped_column(Text)  # why more than the plan
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    indent_id: Mapped[int | None] = mapped_column(ForeignKey("indents.id", ondelete="SET NULL"))

    lines: Mapped[list["MaterialLotLine"]] = relationship(
        order_by="MaterialLotLine.id", cascade="all, delete-orphan", lazy="selectin"
    )


class MaterialLotLine(Tracked, Base):
    __tablename__ = "material_lot_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    lot_id: Mapped[int] = mapped_column(
        ForeignKey("material_lots.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    qty: Mapped[Decimal] = mapped_column(Qty)


class SiteStageDays(Tracked, Base):
    """A stage's days on one site (the template's typical days otherwise)."""

    __tablename__ = "site_stage_days"
    __table_args__ = (
        UniqueConstraint("site_id", "step_id"),
        CheckConstraint("days >= 0 AND days <= 365", name="days_range"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("stage_template_steps.id", ondelete="CASCADE"))
    days: Mapped[int] = mapped_column(Integer)
