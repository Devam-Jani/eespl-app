"""The methodology builder: our method library (systems with stages and numbered steps, products
with their data sheet values), the client standards read from the client's SOPs (one rule per
element and condition, each linked to its SOP, revision and page), the methodology built for a
BOQ (per main item: conditions, system, compliance, edits with reasons, versions and exports),
and what a won BOQ hands to the site (pond tests, material tests on deliveries).

Client documents (the SOP PDFs) stay in data/; only the facts read from them are kept here."""

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

TO_CONFIRM = "to confirm"


class MethodProduct(Tracked, Base):
    """A product as our methods use it, with its data sheet values: {property: {value, num, unit,
    standard, source}}; a value nobody has read stays out (shown "to confirm"), never invented."""

    __tablename__ = "method_products"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    brand: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str | None] = mapped_column(String(30))  # coating, membrane, primer, mortar ...
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    standards: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    datasheet_path: Mapped[str | None] = mapped_column(Text)  # under data/ or media/
    datasheet_name: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MethodSystem(Tracked, Base):
    """One of our systems: where it suits, why we pick it over the others, its stages with numbered
    steps (text, product, consumption, coats, waiting time, tools, ours or the client's scope),
    hold points, tests, the checklist per stage, guarantee, BOQ text and measurement rule.

    stages = [{heading, option, steps: [{text, product, consumption, unit, coats, wait, tools,
    scope: ours|client, if_required, to_confirm: [note]}]}]"""

    __tablename__ = "method_systems"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100))
    system_type: Mapped[str | None] = mapped_column(String(40), index=True)
    elements: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    why: Mapped[str | None] = mapped_column(Text)
    competing: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    hold_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    guarantee_years: Mapped[int | None] = mapped_column(Integer)
    boq_description: Mapped[str | None] = mapped_column(Text)
    measurement_rule: Mapped[str | None] = mapped_column(Text)
    specs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")  # what we claim
    to_confirm: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    fixes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    template_ids: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")
    master_system_id: Mapped[int | None] = mapped_column(
        ForeignKey("systems.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MethodSystemChange(Base):
    """Every change to a system: the version it made, why, what changed and the whole before."""

    __tablename__ = "method_system_changes"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("method_systems.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientStandard(Tracked, Base):
    """A client's waterproofing standard (Godrej's SOP set): approved makes, guarantee, rules."""

    __tablename__ = "client_standards"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    client_name: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(Text)
    approved_makes: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    guarantee_years: Mapped[int | None] = mapped_column(Integer)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")  # the import
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")

    rules: Mapped[list["StandardRule"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StandardRule.id",
    )


class StandardDocument(Base):
    """One SOP (or the summary sheet) as read: number, revision, date, format, pages."""

    __tablename__ = "standard_documents"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        ForeignKey("client_standards.id", ondelete="CASCADE"), index=True
    )
    sop_no: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[str | None] = mapped_column(String(20))
    issue_date: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(String(300))
    file_name: Mapped[str] = mapped_column(String(300))
    fmt: Mapped[str] = mapped_column(String(10))  # old, new, xlsx
    pages: Mapped[int] = mapped_column(Integer, server_default="0")
    element: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)


class StandardRule(Base):
    """element + condition -> the system type the client requires, its minimum specs, makes
    (approved / approved as per TPT / not approved), tests, hold points, checklist, guarantee and
    BOQ wording; linked to the SOP, its revision and page. confidence low -> status to_check."""

    __tablename__ = "standard_rules"
    __table_args__ = (CheckConstraint("status IN ('ok', 'to_check')", name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        ForeignKey("client_standards.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("standard_documents.id", ondelete="SET NULL")
    )
    element: Mapped[str] = mapped_column(String(40), index=True)
    element_label: Mapped[str | None] = mapped_column(String(200))
    condition_label: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    system_type: Mapped[str | None] = mapped_column(String(40))
    system_text: Mapped[str | None] = mapped_column(Text)
    min_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    makes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    hold_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    options_evaluated: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    guarantee_years: Mapped[int | None] = mapped_column(Integer)
    boq_wording: Mapped[str | None] = mapped_column(Text)
    measurement: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(6), server_default="high")
    status: Mapped[str] = mapped_column(String(8), server_default="ok")
    check_note: Mapped[str | None] = mapped_column(Text)

    document: Mapped[StandardDocument | None] = relationship(lazy="joined")


class StandardContradiction(Base):
    """Two values for one thing in the client's documents: a pre-bid query to raise."""

    __tablename__ = "standard_contradictions"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        ForeignKey("client_standards.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("standard_documents.id", ondelete="SET NULL")
    )
    element: Mapped[str | None] = mapped_column(String(40))
    topic: Mapped[str] = mapped_column(String(200))
    values: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    note: Mapped[str | None] = mapped_column(Text)

    document: Mapped[StandardDocument | None] = relationship(lazy="joined")


class Methodology(Tracked, Base):
    """The methodology of one tender or quotation (versioned with its BOQ revision)."""

    __tablename__ = "methodologies"
    __table_args__ = (CheckConstraint("status IN ('draft', 'final')", name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # MS-2026-0001
    title: Mapped[str] = mapped_column(String(300))
    tender_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"), index=True
    )
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL"), index=True
    )
    standard_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_standards.id", ondelete="SET NULL")
    )
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    letterhead_id: Mapped[int | None] = mapped_column(
        ForeignKey("letterheads.id", ondelete="SET NULL")
    )
    brand: Mapped[str | None] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer, server_default="0")  # the BOQ revision
    version: Mapped[int] = mapped_column(Integer, server_default="1")  # our edits
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")

    items: Mapped[list["MethodologyItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MethodologyItem.sort_order, MethodologyItem.id",
    )


class MethodologyItem(Base):
    """A main item: element, places and quantities, the conditions read (each with its source),
    the client's rule, our system with the reason and the other options, the steps as edited,
    the compliance result."""

    __tablename__ = "methodology_items"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    methodology_id: Mapped[int] = mapped_column(
        ForeignKey("methodologies.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    rate_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("rate_groups.id", ondelete="SET NULL")
    )
    boq_line_ids: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")
    name: Mapped[str] = mapped_column(String(300))
    element: Mapped[str | None] = mapped_column(String(40))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(20))
    places: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("standard_rules.id", ondelete="SET NULL")
    )
    rule_note: Mapped[str | None] = mapped_column(Text)
    system_id: Mapped[int | None] = mapped_column(
        ForeignKey("method_systems.id", ondelete="SET NULL")
    )
    option_ids: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")
    reason: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    edits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    compliance: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    make_choice: Mapped[str | None] = mapped_column(String(10))  # approved | keep (TPT query)
    stage_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("stage_templates.id", ondelete="SET NULL")
    )


class MethodologyVersion(Base):
    """A saved version: the whole methodology as it was, with why."""

    __tablename__ = "methodology_versions"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    methodology_id: Mapped[int] = mapped_column(
        ForeignKey("methodologies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MethodologyFile(Base):
    """An exported .docx / .pdf: for the client (no internals) or internal (with compliance)."""

    __tablename__ = "methodology_files"
    __table_args__ = (
        CheckConstraint("kind IN ('docx', 'pdf')", name="kind_valid"),
        CheckConstraint("audience IN ('client', 'internal')", name="audience_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    methodology_id: Mapped[int] = mapped_column(
        ForeignKey("methodologies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(4))
    audience: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(400))
    file_name: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(Integer)
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PreBidQuery(Base):
    """A question for the client before the bid: a contradiction in their documents, a make to
    approve (TPT), a gap, a value to confirm."""

    __tablename__ = "prebid_queries"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'sent', 'answered')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    methodology_id: Mapped[int] = mapped_column(
        ForeignKey("methodologies.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("methodology_items.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20))  # contradiction, make, gap, confirm, condition
    text: Mapped[str] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), server_default="open")
    answer: Mapped[str | None] = mapped_column(Text)


class PondTest(Tracked, Base):
    """A pond (flood) test on site: the hours the standard asks, when it started and ended, the
    drop, the photos and the result."""

    __tablename__ = "pond_tests"
    __table_args__ = (
        CheckConstraint("result IN ('pending', 'pass', 'fail')", name="result_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    methodology_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("methodology_items.id", ondelete="SET NULL")
    )
    stage_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("stage_templates.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(12))  # pre_pond, pond, fill
    required_hours: Mapped[int] = mapped_column(Integer)
    depth_mm: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drop_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    result: Mapped[str] = mapped_column(String(8), server_default="pending")
    photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    reference: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text)


class MaterialTest(Tracked, Base):
    """Sampling on deliveries: the product, the tests and values the standard asks, how often;
    a delivery (GRN) of the product makes one due."""

    __tablename__ = "material_tests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'due', 'sampled', 'pass', 'fail')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    methodology_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("methodology_items.id", ondelete="SET NULL")
    )
    product_name: Mapped[str] = mapped_column(String(300))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    tests: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    frequency: Mapped[str | None] = mapped_column(Text)
    grn_id: Mapped[int | None] = mapped_column(ForeignKey("grns.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(8), server_default="planned")
    sampled_on: Mapped[date | None] = mapped_column(Date)
    result_note: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
