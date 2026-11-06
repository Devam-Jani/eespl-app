"""Product data sheets (TDS) and their facts, a BOQ line's key points and the option picked for it,
and the consumption master's change history."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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

IMPORT_STATUSES = ("preview", "saved", "discarded")
# preview: read, not kept yet; saved: the product's sheet; replaced: a newer one took its place;
# duplicate: the same sheet (or product) again in one import, merged into the first
DOC_STATUSES = ("preview", "saved", "replaced", "duplicate", "skipped")
FACT_SOURCES = ("rule", "ai", "manual")


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TdsImport(Base):
    """One import of data sheets (a folder, or files): previewed first, then saved or dropped."""

    __tablename__ = "tds_imports"
    __table_args__ = (CheckConstraint(_in("status", IMPORT_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), server_default="preview")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TdsDoc(Base):
    __tablename__ = "tds_docs"
    __table_args__ = (CheckConstraint(_in("status", DOC_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    import_id: Mapped[int | None] = mapped_column(
        ForeignKey("tds_imports.id", ondelete="SET NULL"), index=True
    )
    brand: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(300))
    rel_path: Mapped[str | None] = mapped_column(Text)  # as in the folder imported
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str | None] = mapped_column(String(400))  # under media/
    pages: Mapped[int] = mapped_column(Integer, server_default="0")
    chars: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(10), server_default="preview")
    needs_reading: Mapped[bool] = mapped_column(Boolean, server_default="false")  # scanned: no text
    read_error: Mapped[str | None] = mapped_column(String(300))
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    # matched: the product master's; create: a new product on save; skip: kept without a product
    match: Mapped[str] = mapped_column(String(8), server_default="create")
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("tds_docs.id", ondelete="SET NULL")
    )
    # the saved sheet of the same product this one would replace (only once confirmed)
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("tds_docs.id", ondelete="SET NULL"))
    replace_confirmed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    pdf_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class TdsFact(Base):
    """One fact a data sheet gives, with the page and the sentence it came from. Edited by a
    person: "checked by" who and when, the value as read kept in `original`."""

    __tablename__ = "tds_facts"
    __table_args__ = (CheckConstraint(_in("source", FACT_SOURCES), name="source_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("tds_docs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    key: Mapped[str | None] = mapped_column(String(30))
    lo: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    hi: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    unit: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str | None] = mapped_column(Text)
    standard: Mapped[str | None] = mapped_column(String(40))
    page: Mapped[int | None] = mapped_column(Integer)
    sentence: Mapped[str | None] = mapped_column(Text)
    per_coat: Mapped[bool] = mapped_column(Boolean, server_default="false")
    coats: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(6), server_default="rule")
    checked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SpecPoints(Base):
    """A line's key points as a person left them (read from the words until someone edits them or
    an AI pass adds some): the chips, and the description they were read from."""

    __tablename__ = "spec_points"
    __table_args__ = (
        CheckConstraint(
            "(boq_line_id IS NOT NULL) <> (quotation_line_id IS NOT NULL)", name="one_line"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    boq_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_lines.id", ondelete="CASCADE"), unique=True
    )
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="CASCADE"), unique=True
    )
    text_hash: Mapped[str] = mapped_column(String(64))
    chips: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SpecPick(Base):
    """The option a person ticked for a line (rank 1; rank 2 is the alternate): a work item's
    brand option, built into the rate working's main item."""

    __tablename__ = "spec_picks"
    __table_args__ = (
        CheckConstraint(
            "(boq_line_id IS NOT NULL) <> (quotation_line_id IS NOT NULL)", name="one_line"
        ),
        CheckConstraint("rank IN (1, 2)", name="rank_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    boq_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_lines.id", ondelete="CASCADE"), index=True
    )
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer, server_default="1")
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"))
    option_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_options.id", ondelete="SET NULL")
    )
    group_id: Mapped[int | None] = mapped_column(ForeignKey("rate_groups.id", ondelete="SET NULL"))
    picked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    picked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ConsumptionChange(Base):
    """One change in the consumption master: who, when, the old and new value, why."""

    __tablename__ = "consumption_changes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    system_id: Mapped[int | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    option_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_options.id", ondelete="SET NULL")
    )
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_components.id", ondelete="SET NULL")
    )
    what: Mapped[str] = mapped_column(String(200))  # "Bronco: Flexi PU, consumption"
    field: Mapped[str] = mapped_column(String(30))
    old: Mapped[str | None] = mapped_column(Text)
    new: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
