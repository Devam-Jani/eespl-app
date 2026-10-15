"""The BOQ knowledge library: what our old BOQs say, read from the files (company data: the files
stay in data/boq-knowledge/, the facts here, each linked to its file, sheet and row), grouped into
specification templates that a new BOQ starts from, with the rates we sold at by place and date
and the margins we carried."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.knowledge.extract import DEFAULT_REGIONS
from app.masters.models import Tracked
from app.models import Base

FILE_STATUSES = ("read", "failed", "scanned", "not_boq", "skipped")
MATCH_STATUSES = ("proposed", "accepted", "changed", "none")


class KnowledgeSettings(Base):
    """One row (id 1): the regions (city -> region, editable) and when a rate is old."""

    __tablename__ = "knowledge_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: dict(DEFAULT_REGIONS))
    old_after_months: Mapped[int] = mapped_column(Integer, server_default="12")
    source_folder: Mapped[str | None] = mapped_column(Text)  # where the reading ran from (shown)
    last_run: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}"
    )  # the reading report


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"
    __table_args__ = (
        CheckConstraint(
            "status IN ('read', 'failed', 'scanned', 'not_boq', 'skipped')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True)  # under data/boq-knowledge/files/
    kind: Mapped[str] = mapped_column(String(8))
    size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(Text)
    sheets: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    lines: Mapped[int] = mapped_column(Integer, server_default="0")
    lines_with_working: Mapped[int] = mapped_column(Integer, server_default="0")
    folder: Mapped[str | None] = mapped_column(Text)  # the top folder: the client or channel
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    place_source: Mapped[str | None] = mapped_column(String(40))
    on_date: Mapped[date | None] = mapped_column(Date)
    date_source: Mapped[str | None] = mapped_column(String(40))
    is_eespl: Mapped[bool] = mapped_column(Boolean, server_default="false")  # our own offer file
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeLine(Base):
    """One priced client line of an old BOQ (or a won BOQ of ours), what it asks, its build-up
    when the file has a working, and the place and date."""

    __tablename__ = "knowledge_lines"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(10), server_default="file")  # file | won
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="SET NULL"))
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    sheet: Mapped[str | None] = mapped_column(String(200))
    row: Mapped[int | None] = mapped_column(Integer)
    item_no: Mapped[str | None] = mapped_column(String(50))
    parent_item: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_raw: Mapped[str | None] = mapped_column(String(50))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    qty_note: Mapped[str | None] = mapped_column(String(10))  # QRO | NQ
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # as sold, in the line's unit
    rate_sqm: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # area lines: per sqm
    product_make: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    area_type: Mapped[str | None] = mapped_column(String(20), index=True)
    surface: Mapped[str | None] = mapped_column(String(10))
    coats: Mapped[int | None] = mapped_column(Integer)
    min_kg_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    dft_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    working: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # traced build-up
    cost_sqm: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))  # on the selling price
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    on_date: Mapped[date | None] = mapped_column(Date)
    folder: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_templates.id", ondelete="SET NULL"), index=True
    )
    to_check: Mapped[bool] = mapped_column(Boolean, server_default="false")
    check_note: Mapped[str | None] = mapped_column(String(300))
    hidden: Mapped[bool] = mapped_column(Boolean, server_default="false")


class KnowledgeTemplate(Tracked, Base):
    """A specification template: similar client lines (area, surface, requirements, close words)
    with the standard description, the method statement, the systems and products we used and
    every past rate. Reviewed by planning or the estimator: merged, split, renamed, hidden."""

    __tablename__ = "knowledge_templates"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), index=True)  # how it was grouped
    name: Mapped[str] = mapped_column(String(200))
    area_type: Mapped[str | None] = mapped_column(String(20), index=True)
    surface: Mapped[str | None] = mapped_column(String(10))
    coats: Mapped[int | None] = mapped_column(Integer)
    min_kg_sqm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    dft_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    families: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    unit: Mapped[str | None] = mapped_column(String(20))  # sqm (area lines per sqm), rmt, nos ...
    description: Mapped[str] = mapped_column(Text)  # the standard (best written) client text
    steps: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")  # the method statement
    steps_source: Mapped[str | None] = mapped_column(String(200))
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    hidden: Mapped[bool] = mapped_column(Boolean, server_default="false")
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_templates.id", ondelete="SET NULL")
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    to_check: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # cached for the list (recomputed after a reading or a change)
    lines_count: Mapped[int] = mapped_column(Integer, server_default="0")
    files_count: Mapped[int] = mapped_column(Integer, server_default="0")
    median_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    latest_on: Mapped[date | None] = mapped_column(Date)


class KnowledgeFix(Base):
    """A value of the library put right by hand, always with the reason."""

    __tablename__ = "knowledge_fixes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    entity: Mapped[str] = mapped_column(String(10))  # line | template
    entity_id: Mapped[int] = mapped_column(BigInteger, index=True)
    field: Mapped[str] = mapped_column(String(40))
    old: Mapped[str | None] = mapped_column(Text)
    new: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeMatch(Base):
    """An imported client BOQ line matched to a template, with a confidence, for the user to
    accept or change."""

    __tablename__ = "knowledge_matches"
    __table_args__ = (
        UniqueConstraint("boq_line_id"),
        UniqueConstraint("quotation_line_id"),
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'changed', 'none')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    boq_line_id: Mapped[int | None] = mapped_column(ForeignKey("boq_lines.id", ondelete="CASCADE"))
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="CASCADE")
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_templates.id", ondelete="SET NULL")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(10), server_default="proposed")
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
