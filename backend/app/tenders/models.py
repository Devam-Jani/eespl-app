"""Tenders: the register, the BOQ (sections, lines, pricing candidates), imports and T&C."""

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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Client, Tracked
from app.models import Base, User

TENDER_STATUSES = ("draft", "submitted", "won", "lost", "dropped")
LINE_STATUSES = ("unpriced", "suggested", "priced", "not_quoted")
PRICE_SOURCES = ("system", "library", "manual")
QTY_NOTES = ("QRO", "NQ")

Money = Numeric(14, 2)
Rate = Numeric(14, 2)
Qty = Numeric(14, 3)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TenderSequence(Base):
    """Next tender number per year; incremented atomically (INSERT ... ON CONFLICT)."""

    __tablename__ = "tender_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer)


class Tender(Tracked, Base):
    __tablename__ = "tenders"
    __table_args__ = (CheckConstraint(_in("status", TENDER_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # T-2026-0001
    name: Mapped[str] = mapped_column(String(300))
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    site_name: Mapped[str | None] = mapped_column(String(200))
    site_city: Mapped[str | None] = mapped_column(String(100))
    site_state: Mapped[str | None] = mapped_column(String(100))
    received_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), server_default="draft", index=True)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    lost_to: Mapped[str | None] = mapped_column(String(200))
    quoted_total: Mapped[Decimal] = mapped_column(Money, server_default="0")  # cached
    tc_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[owner_id])
    members: Mapped[list["TenderMember"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class TenderMember(Tracked, Base):
    __tablename__ = "tender_members"

    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])


class BoqSection(Tracked, Base):
    __tablename__ = "boq_sections"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


class BoqLine(Tracked, Base):
    __tablename__ = "boq_lines"
    __table_args__ = (
        CheckConstraint(_in("status", LINE_STATUSES), name="status_valid"),
        CheckConstraint(f"source IS NULL OR {_in('source', PRICE_SOURCES)}", name="source_valid"),
        CheckConstraint(f"qty_note IS NULL OR {_in('qty_note', QTY_NOTES)}", name="qty_note_valid"),
        Index("ix_boq_lines_tender_id_sort_order", "tender_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("boq_sections.id", ondelete="SET NULL"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    client_item_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(ForeignKey("units.code"))
    unit_raw: Mapped[str | None] = mapped_column(String(50))
    qty: Mapped[Decimal | None] = mapped_column(Qty)
    qty_note: Mapped[str | None] = mapped_column(String(5))
    client_product: Mapped[str | None] = mapped_column(Text)
    client_remarks: Mapped[str | None] = mapped_column(Text)
    # The rate printed in the client's file (theirs, a competitor's, or ours from an earlier
    # round). Informational only: never copied into `rate`.
    client_file_rate: Mapped[Decimal | None] = mapped_column(Rate)
    # pricing
    source: Mapped[str | None] = mapped_column(String(10))
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL")
    )
    cost_rate: Mapped[Decimal | None] = mapped_column(Rate)
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rate: Mapped[Decimal | None] = mapped_column(Rate)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    suggestion_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    our_remarks: Mapped[str | None] = mapped_column(Text)
    our_product: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), server_default="unpriced")

    candidates: Mapped[list["BoqLineCandidate"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BoqLineCandidate.rank",
    )


class BoqLineCandidate(Tracked, Base):
    """Up to three pricing candidates per line, kept from the last Suggest run."""

    __tablename__ = "boq_line_candidates"
    __table_args__ = (CheckConstraint(_in("source", ("system", "library")), name="source_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("boq_lines.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10))
    ref_id: Mapped[int] = mapped_column(BigInteger)  # system id or library item id
    rate: Mapped[Decimal] = mapped_column(Rate)
    cost_rate: Mapped[Decimal | None] = mapped_column(Rate)
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    reason: Mapped[str] = mapped_column(Text)


class BoqImport(Tracked, Base):
    __tablename__ = "boq_imports"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(400))  # under the media volume
    sheet: Mapped[str | None] = mapped_column(String(200))
    header_row: Mapped[int] = mapped_column(Integer)
    column_map: Mapped[dict[str, Any]] = mapped_column(JSONB)
    row_count: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenderTc(Tracked, Base):
    """The tender's own T&C list: copied from a template, then edited per tender."""

    __tablename__ = "tender_tc"
    __table_args__ = (
        CheckConstraint("clause_id IS NOT NULL OR text_override IS NOT NULL", name="has_text"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    clause_id: Mapped[int | None] = mapped_column(ForeignKey("tc_clauses.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    text_override: Mapped[str | None] = mapped_column(Text)
