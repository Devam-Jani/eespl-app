# ruff: noqa: E501  (column definitions read better unwrapped)
"""From the planning and billing process review (16 Oct): a tender quoted to several civil
contractors, the client's work order checked against our offer, client roles in the portal,
measurements the client approves line by line, RFI zones, the client's billing cycle and the bill's
tracking steps, payment follow-ups, the work completion certificate with its guarantee, the issue
log per site, and labour contractors' claims.

Locked means locked: an accepted work order, an approved measurement and a signed work completion
are never edited or deleted (409 for every role); a correction is a new revision or an addendum
pointing to the original."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

Qty = Numeric(14, 3)
Money = Numeric(14, 2)

MAIN_STATUSES = ("pending", "won", "lost")
WO_STATUSES = ("draft", "accepted")
PAYMENT_BASES = ("invoice", "certification", "final_bill")
DEVIATION_KINDS = ("missing", "added", "qty", "rate", "unit", "discontinued", "scope", "payment", "retention", "advance", "penalty", "time")  # fmt: skip
DEVIATION_STATUSES = ("open", "accepted", "amend")
CLIENT_RIGHTS = (
    "progress.view",  # sites, progress, DPRs, photos, 3D
    "handover.edit",  # enter and update the promised handover dates
    "inspection.sign",  # sign inspections and RFIs
    "snag.raise",
    "measurement.approve",
    "bill.view",
    "bill.certify",
    "payment.view",  # bills, payments, what is overdue
    "documents.view",
)
CHANGE_STATUSES = ("pending", "accepted", "disputed")
BILL_STEPS = ("prepared", "submitted_site", "signed_pm", "sent_ho", "with_accounts", "paid")
BILL_STEP_LABEL = {
    "prepared": "Prepared",
    "submitted_site": "Submitted at site",
    "signed_pm": "Signed by the client's project manager",
    "sent_ho": "Sent to the client's head office",
    "with_accounts": "With the client's accounts",
    "paid": "Paid",
}
ISSUE_CATEGORIES = ("material_not_arrived", "material_short", "material_damaged", "product_discontinued", "billing_not_accepted",
                    "billing_over_billed", "billing_wrong_rate", "quality", "leakage", "payment", "site_access", "subcontractor", "other")  # fmt: skip
ISSUE_STATUSES = ("open", "in_progress", "resolved", "closed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TenderCustomer(Tracked, Base):
    """A civil contractor (or the developer) we quoted this tender to: its own quotation, and
    whether it won the main job. The ones that lose it close as "main job lost by the
    contractor", not our loss."""

    __tablename__ = "tender_customers"
    __table_args__ = (CheckConstraint(_in("main_status", MAIN_STATUSES), name="main_status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    main_status: Mapped[str] = mapped_column(String(8), server_default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class ClientWorkOrder(Tracked, Base):
    """The client's work order, checked against our accepted quotation before we sign it.
    Accepted: locked."""

    __tablename__ = "client_work_orders"
    __table_args__ = (
        CheckConstraint(_in("status", WO_STATUSES), name="status_valid"),
        CheckConstraint(
            f"payment_basis IS NULL OR {_in('payment_basis', PAYMENT_BASES)}", name="basis_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # CWO-2026-0001
    client_ref: Mapped[str | None] = mapped_column(String(100))  # the client's WO number
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="SET NULL"), index=True
    )
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    file_path: Mapped[str | None] = mapped_column(String(400))
    file_name: Mapped[str | None] = mapped_column(String(300))
    lines_from: Mapped[str | None] = mapped_column(String(20))  # file, typed, quotation
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    # the payment term, structured: N days after the invoice / certification / final bill
    payment_basis: Mapped[str | None] = mapped_column(String(14))
    payment_days: Mapped[int | None] = mapped_column(Integer)
    retention_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    retention_release: Mapped[str | None] = mapped_column(Text)
    advance_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    penalty: Mapped[str | None] = mapped_column(Text)
    time_limit_days: Mapped[int | None] = mapped_column(Integer)
    guarantee_years: Mapped[int | None] = mapped_column(Integer)
    scope_on_us: Mapped[list[str]] = mapped_column(
        JSONB, server_default="[]"
    )  # what the WO puts on us
    scope_on_client: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["ClientWorkOrderLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientWorkOrderLine.sort_order",
    )
    deviations: Mapped[list["WoDeviation"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WoDeviation.id",
    )


class ClientWorkOrderLine(Base):
    __tablename__ = "client_work_order_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("client_work_orders.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    item_no: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(20))
    qty: Mapped[Decimal | None] = mapped_column(Qty)
    rate: Mapped[Decimal | None] = mapped_column(Money)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="SET NULL")
    )


class WoDeviation(Base):
    """A difference between the work order and our offer: accepted, or the client asked to amend
    (a to-do for the salesperson with the text to send)."""

    __tablename__ = "wo_deviations"
    __table_args__ = (
        CheckConstraint(_in("kind", DEVIATION_KINDS), name="kind_valid"),
        CheckConstraint(_in("status", DEVIATION_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("client_work_orders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(14))
    topic: Mapped[str] = mapped_column(Text)
    ours: Mapped[str | None] = mapped_column(Text)
    theirs: Mapped[str | None] = mapped_column(Text)
    wo_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_work_order_lines.id", ondelete="SET NULL")
    )
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(8), server_default="open")
    note: Mapped[str | None] = mapped_column(Text)
    amend_text: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClientRoleDef(Base):
    """A client role in the portal and what it may do (Settings > Client roles)."""

    __tablename__ = "client_role_defs"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    rights: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


class MeasurementSet(Tracked, Base):
    """Measurement lines sent together to the client's billing role for approval."""

    __tablename__ = "measurement_sets"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # MB-<site>-01
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MeasurementChange(Base):
    """A client's correction of one value of a measurement line (old, new, remark, who, when),
    and our answer: accepted, or disputed with a reason."""

    __tablename__ = "measurement_changes"
    __table_args__ = (CheckConstraint(_in("status", CHANGE_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    measurement_id: Mapped[int] = mapped_column(
        ForeignKey("measurements.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(20))  # length_m, breadth_m, qty ...
    old_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    new_value: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    # as typed (19 ft 5 in): the value columns hold metres
    old_text: Mapped[str | None] = mapped_column(String(40))
    new_text: Mapped[str | None] = mapped_column(String(40))
    remark: Mapped[str | None] = mapped_column(Text)
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    by_name: Mapped[str] = mapped_column(String(200))
    side: Mapped[str] = mapped_column(String(6), server_default="client")  # client | staff
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(8), server_default="pending")
    reply: Mapped[str | None] = mapped_column(Text)
    replied_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfiZone(Tracked, Base):
    """A zone of the site: handed to us (ours) or to another applicator (named), marked on the
    drawing or 3D, and the client's RFI signature (in the app or recorded by our staff)."""

    __tablename__ = "rfi_zones"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="CASCADE"))
    cad_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id", ondelete="SET NULL"))
    outline: Mapped[list[Any] | None] = mapped_column(JSONB)  # [[x, y], ...] drawing units
    name: Mapped[str] = mapped_column(String(200))
    ours: Mapped[bool] = mapped_column(Boolean, server_default="true")
    other_applicator: Mapped[str | None] = mapped_column(String(200))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_user: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_name: Mapped[str | None] = mapped_column(String(200))
    recorded_by_staff: Mapped[bool] = mapped_column(Boolean, server_default="false")
    signed_copy_path: Mapped[str | None] = mapped_column(String(400))


class ClientBillingCycle(Tracked, Base):
    """When the client takes bills: the days bills must reach the site (25th to 30th), the head
    office's processing days (1st to 7th), and the payment days after head office. Per client,
    or per site where it differs."""

    __tablename__ = "client_billing_cycles"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    submit_from_day: Mapped[int] = mapped_column(Integer, server_default="25")
    submit_to_day: Mapped[int] = mapped_column(Integer, server_default="30")
    ho_from_day: Mapped[int] = mapped_column(Integer, server_default="1")
    ho_to_day: Mapped[int] = mapped_column(Integer, server_default="7")
    payment_days: Mapped[int] = mapped_column(Integer, server_default="30")
    note: Mapped[str | None] = mapped_column(Text)


class BillTrackingStep(Base):
    """A bill's way through the client: each step with its date, who and the signed copy (our
    proof when a bill goes missing)."""

    __tablename__ = "bill_tracking_steps"
    __table_args__ = (CheckConstraint(_in("step", BILL_STEPS), name="step_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ra_bill_id: Mapped[int] = mapped_column(
        ForeignKey("ra_bills.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(16))
    on_date: Mapped[date] = mapped_column(Date)
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    by_name: Mapped[str | None] = mapped_column(String(200))  # the client's person, when told
    file_path: Mapped[str | None] = mapped_column(String(400))
    file_name: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentFollowUp(Base):
    """Accounts' call about an unpaid bill: who they spoke to, what was said, the promised date
    (the next reminder)."""

    __tablename__ = "payment_followups"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ra_bill_id: Mapped[int] = mapped_column(
        ForeignKey("ra_bills.id", ondelete="CASCADE"), index=True
    )
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    spoke_to: Mapped[str] = mapped_column(String(200))
    said: Mapped[str] = mapped_column(Text)
    promised_on: Mapped[date | None] = mapped_column(Date)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CloseoutSettings(Base):
    """One row (id 1): the days in the bill and payment rules (Settings > Process rules)."""

    __tablename__ = "closeout_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_stuck_days: Mapped[int] = mapped_column(Integer, server_default="7")
    bill_stuck_escalate_days: Mapped[int] = mapped_column(Integer, server_default="3")
    overdue_salesperson_days: Mapped[int] = mapped_column(Integer, server_default="5")
    overdue_director_days: Mapped[int] = mapped_column(Integer, server_default="30")


class WorkCompletion(Tracked, Base):
    """The work completion certificate: our areas with their approved quantities, the system and
    products, the dates and the guarantee. Signed: locked forever; a change is an addendum."""

    __tablename__ = "work_completions"
    __table_args__ = (CheckConstraint("status IN ('draft', 'signed')", name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # WCC-2026-0001
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_work_orders.id", ondelete="SET NULL")
    )
    addendum_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_completions.id", ondelete="RESTRICT")
    )
    completion_date: Mapped[date] = mapped_column(Date)
    started_on: Mapped[date | None] = mapped_column(Date)
    guarantee_years: Mapped[int] = mapped_column(Integer)
    guarantee_from: Mapped[str | None] = mapped_column(String(40))  # work order, quotation, typed
    guarantee_expiry: Mapped[date] = mapped_column(Date)
    areas: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    systems: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    products: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_user: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_name: Mapped[str | None] = mapped_column(String(200))
    recorded_by_staff: Mapped[bool] = mapped_column(Boolean, server_default="false")
    signed_copy_path: Mapped[str | None] = mapped_column(String(400))
    pdf_path: Mapped[str | None] = mapped_column(String(400))
    bond_path: Mapped[str | None] = mapped_column(String(400))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class SiteIssueLog(Tracked, Base):
    """An issue on a site: who raised it, who has it, by when, photos, a comment thread; shared
    with the client it becomes a portal snag. A leakage links to the guarantee and the area."""

    __tablename__ = "issue_log"
    __table_args__ = (
        CheckConstraint(_in("category", ISSUE_CATEGORIES), name="category_valid"),
        CheckConstraint(_in("status", ISSUE_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # ISU-2026-0001
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    methodology_id: Mapped[int | None] = mapped_column(
        ForeignKey("methodologies.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    raised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), server_default="open")
    photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    snag_id: Mapped[int | None] = mapped_column(ForeignKey("snags.id", ondelete="SET NULL"))
    work_completion_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_completions.id", ondelete="SET NULL")
    )
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    ra_bill_id: Mapped[int | None] = mapped_column(ForeignKey("ra_bills.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class IssueComment(Base):
    __tablename__ = "issue_comments"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issue_log.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabourClaim(Tracked, Base):
    """What a labour contractor claims per area, against the approved measurement."""

    __tablename__ = "labour_claims"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    contractor: Mapped[str] = mapped_column(String(200))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    contract_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("contract_lines.id", ondelete="SET NULL")
    )
    claimed_qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str | None] = mapped_column(String(20))
    period: Mapped[str | None] = mapped_column(String(7))  # 2026-10
    note: Mapped[str | None] = mapped_column(Text)
