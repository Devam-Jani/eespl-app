"""Quotations (techno-commercial offers) and the editable libraries they are built from.

Libraries: letterheads, letter templates, specification blocks (per area and option, stage
sections of numbered steps), offer lines (budgetary offer rows), offer items (what the user picks,
one per area: its spec blocks and offer lines with their options) and references ("Our esteemed
clients"). T&C come from the M2 T&C library (a template per letterhead). Every library change is
kept as a version (library_versions: who, when, the whole row as JSON) and can be restored.

A quotation copies everything it uses (a snapshot): editing the quotation never changes the
library, and a library change never changes an issued quotation. "Save back to library" writes
the quotation's text into the library as a new version.

Text markup in the libraries and quotations: **bold** (product names), ==highlight== (notes such
as "Rate shall change for higher thickness"); a newline starts a new paragraph.
"""

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Money, Tracked
from app.models import Base
from app.tenders.models import LOST_REASONS

UOMS = ("sqm", "sqft", "rft", "rmt", "nos", "kg", "ltr", "ls")
UOM_LABELS = {
    "sqm": "SQ MT",
    "sqft": "SQ FT",
    "rft": "R FT",
    "rmt": "RMT",
    "nos": "NOS",
    "kg": "KG",
    "ltr": "LTR",
    "ls": "LS",
}
RATE_SOURCES = ("system", "library", "fixed")
QUOTATION_STATUSES = ("draft", "sent", "negotiation", "won", "lost", "expired")
OPEN_STATUSES = ("sent", "negotiation")
FOLLOWUP_STATUSES = ("open", "done", "cancelled")
LIBRARY_KINDS = ("letterhead", "letter", "spec", "line", "item", "reference", "preset")
# stage sections a spec block offers by default (custom headings are allowed too)
STAGES = (
    "Surface preparation",
    "Laying waterproofing membrane",
    "Pipe sleeve packing",
    "Tie rod hole treatment",
    "Construction joint treatment",
    "Patching work",
    "Patching",
    "Coving",
    "Protective coating",
    "Separation layer",
    "Protection layer",
    "Protection",
    "Termination",
    "Floor area slope & protection",
    "Curing",
)
# T&C library category codes -> the group headings printed in an offer
TC_GROUP_LABELS = {
    "client_scope": "Client's obligations",
    "force_majeure": "Force majeure",
    "taxes": "Taxes",
    "validity": "Validity",
    "applicator": "Applicator",
    "payment": "Terms of payment",
    "general": "General",
    "rates": "Rates",
    "warranty": "Warranty",
    "safety": "Safety",
}
PLACEHOLDERS = (
    "date",
    "client_firm",
    "client_city",
    "attention",
    "project",
    "brand",
    "areas_list",
    "salesperson",
    "designation",
    "enclosures",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class LibraryRow(Tracked):
    """Every library row: a version counter and the "imported, check" flag."""

    version: Mapped[int] = mapped_column(Integer, server_default="1")
    needs_check: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class LibraryVersion(Base):
    """One saved state of a library row (after the change), for the history and restore."""

    __tablename__ = "library_versions"
    __table_args__ = (
        CheckConstraint(_in("kind", LIBRARY_KINDS), name="kind_valid"),
        UniqueConstraint("kind", "entity_id", "version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))  # create, update, restore, save_back, import
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Letterhead(LibraryRow, Base):
    """The company the offer is issued on (EESPL, Bronco, MYK ...): logo, header and footer
    text, the signatory block and colours. The applicator clause still names EESPL."""

    __tablename__ = "letterheads"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    company_name: Mapped[str] = mapped_column(String(200))
    logo_path: Mapped[str | None] = mapped_column(String(300))
    header_text: Mapped[str | None] = mapped_column(Text)
    footer_text: Mapped[str | None] = mapped_column(Text)
    signatory_firm: Mapped[str] = mapped_column(String(200))  # "For BRONCO BUILDWELL PVT. LTD."
    signatory_name: Mapped[str | None] = mapped_column(String(200))
    signatory_designation: Mapped[str | None] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(100))  # {brand}: "BRONCO"
    # image letterheads (EESPL): a band across the top, one across the bottom, a faint logo
    header_image_path: Mapped[str | None] = mapped_column(String(300))
    footer_image_path: Mapped[str | None] = mapped_column(String(300))
    watermark_path: Mapped[str | None] = mapped_column(String(300))  # already faded for the PDF
    # printing on letterhead stationery: leave the header and footer space blank
    preprinted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    primary_color: Mapped[str] = mapped_column(String(7), server_default="#0F6E5A")
    accent_color: Mapped[str] = mapped_column(String(7), server_default="#E69F00")
    tc_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="SET NULL")
    )
    letter_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("letter_templates.id", ondelete="SET NULL")
    )
    references_state: Mapped[str | None] = mapped_column(String(100))  # default reference filter


class LetterTemplate(LibraryRow, Base):
    """The cover letter: the opening (date, firm, attention, salutation), subject and body with
    {placeholders} (PLACEHOLDERS only). The signatory block comes from the letterhead and the
    salesperson; the enclosures list follows it."""

    __tablename__ = "letter_templates"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    opening: Mapped[str] = mapped_column(Text, server_default="")
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    enclosures: Mapped[str] = mapped_column(Text, server_default="")  # one per line


class SpecBlock(LibraryRow, Base):
    """The technical specification of one area and option: stage sections in order, each a
    numbered list of steps. sections: [{heading, option, steps: [{text, client_scope,
    if_required}]}] (a section with an option is an alternative: "OR" goes between them);
    images: [{path, caption}] (printed after the steps)."""

    __tablename__ = "spec_blocks"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(Text)  # "Raft treatment waterproofing using HDPE ..."
    heading_prefix: Mapped[str] = mapped_column(
        String(100), server_default="TECHNICAL SPECIFICATION FOR"
    )
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    option_label: Mapped[str | None] = mapped_column(String(20))  # "1", "2"; none: always
    subtitle: Mapped[str | None] = mapped_column(Text)  # a line under the item title
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    images: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")


class OfferLine(LibraryRow, Base):
    """A budgetary offer row: description (markup), UoM, where its rate comes from."""

    __tablename__ = "offer_lines"
    __table_args__ = (
        CheckConstraint(_in("uom", UOMS), name="uom_valid"),
        CheckConstraint(_in("rate_source", RATE_SOURCES), name="rate_source_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(String(10))
    rate_source: Mapped[str] = mapped_column(String(10), server_default="fixed")
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL")
    )
    default_rate: Mapped[Decimal | None] = mapped_column(Money)
    if_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    client_scope: Mapped[bool] = mapped_column(Boolean, server_default="false")


class OfferItem(LibraryRow, Base):
    """What the user picks, one per area: its spec blocks and offer lines (with options)."""

    __tablename__ = "offer_items"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))  # "Garden & planter area"
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    budget_title: Mapped[str] = mapped_column(Text)  # "Garden area waterproofing work"
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    specs: Mapped[list["OfferItemSpec"]] = relationship(
        order_by="OfferItemSpec.sort_order", cascade="all, delete-orphan"
    )
    lines: Mapped[list["OfferItemLine"]] = relationship(
        order_by="OfferItemLine.sort_order", cascade="all, delete-orphan"
    )


class OfferItemSpec(Base):
    __tablename__ = "offer_item_specs"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("offer_items.id", ondelete="CASCADE"), index=True
    )
    spec_block_id: Mapped[int] = mapped_column(ForeignKey("spec_blocks.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    spec: Mapped[SpecBlock] = relationship()


class OfferItemLine(Base):
    __tablename__ = "offer_item_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("offer_items.id", ondelete="CASCADE"), index=True
    )
    offer_line_id: Mapped[int] = mapped_column(ForeignKey("offer_lines.id", ondelete="CASCADE"))
    option: Mapped[str | None] = mapped_column(String(20))  # "1": the Opt.1 row
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    line: Mapped[OfferLine] = relationship()


class Reference(LibraryRow, Base):
    """A row of "Our esteemed clients": from a completed site, or typed in for older jobs."""

    __tablename__ = "quotation_references"
    __table_args__ = (
        CheckConstraint("source IN ('site', 'manual', 'imported')", name="source_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(300))
    project: Mapped[str] = mapped_column(Text)
    application: Mapped[str] = mapped_column(Text)
    area_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    area_unit: Mapped[str | None] = mapped_column(String(10))  # SQFT, SQMT, RMT
    state: Mapped[str | None] = mapped_column(String(100), index=True)
    area_type_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), unique=True
    )
    include: Mapped[bool] = mapped_column(Boolean, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    source: Mapped[str] = mapped_column(String(10), server_default="manual")


class OfferPreset(LibraryRow, Base):
    """A saved starting point: letterhead, letter, items in order (with their options), the T&C
    template and whether references go in ("Bungalow - EESPL", "Project - Bronco")."""

    __tablename__ = "offer_presets"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    letterhead_id: Mapped[int | None] = mapped_column(
        ForeignKey("letterheads.id", ondelete="SET NULL")
    )
    letter_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("letter_templates.id", ondelete="SET NULL")
    )
    tc_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("tc_templates.id", ondelete="SET NULL")
    )
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    include_references: Mapped[bool] = mapped_column(Boolean, server_default="true")


class QuotationSettings(Base):
    """One row (id 1)."""

    __tablename__ = "quotation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_validity_days: Mapped[int] = mapped_column(Integer, server_default="30")
    followup_days: Mapped[list[int]] = mapped_column(JSONB, server_default="[2, 7, 15, 30]")
    closure_target_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="65")
    # per salesperson: {user id: percent}
    closure_targets: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    default_letterhead_id: Mapped[int | None] = mapped_column(
        ForeignKey("letterheads.id", ondelete="SET NULL")
    )
    word_template_path: Mapped[str | None] = mapped_column(String(300))  # restyled by the team
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Quotation(Tracked, Base):
    """One revision of an offer (QTN-YYYY-NNNN R0, R1 ...). Holds its own copy of every text."""

    __tablename__ = "quotations"
    __table_args__ = (
        UniqueConstraint("code", "revision"),
        CheckConstraint(_in("status", QUOTATION_STATUSES), name="status_valid"),
        CheckConstraint(
            f"lost_reason IS NULL OR {_in('lost_reason', LOST_REASONS)}", name="lost_reason_valid"
        ),
        CheckConstraint("status <> 'lost' OR lost_reason IS NOT NULL", name="lost_needs_reason"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    is_latest: Mapped[bool] = mapped_column(Boolean, server_default="true")
    previous_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    survey_id: Mapped[int | None] = mapped_column(ForeignKey("surveys.id", ondelete="SET NULL"))
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="SET NULL"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    letterhead_id: Mapped[int | None] = mapped_column(
        ForeignKey("letterheads.id", ondelete="SET NULL")
    )
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    client_firm: Mapped[str] = mapped_column(String(300))
    client_city: Mapped[str | None] = mapped_column(String(100))
    client_state: Mapped[str | None] = mapped_column(String(100))
    attention: Mapped[str | None] = mapped_column(String(200))
    project: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100))
    areas_list: Mapped[str | None] = mapped_column(String(300))  # {areas_list}; empty: from items
    quote_date: Mapped[date] = mapped_column(Date)
    validity_days: Mapped[int] = mapped_column(Integer, server_default="30")
    status: Mapped[str] = mapped_column(String(12), server_default="draft", index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    lost_note: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    show_amounts: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # the letter (copied from the template, editable here only)
    letter_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("letter_templates.id", ondelete="SET NULL")
    )
    opening: Mapped[str] = mapped_column(Text, server_default="")
    subject: Mapped[str] = mapped_column(Text, server_default="")
    body: Mapped[str] = mapped_column(Text, server_default="")
    enclosures: Mapped[str] = mapped_column(Text, server_default="")
    signatory_name: Mapped[str | None] = mapped_column(String(200))
    signatory_designation: Mapped[str | None] = mapped_column(String(200))
    # T&C and references (copied, editable here only): [{category, text, clause_id}], [{...}]
    terms: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    references_title: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list["QuotationItem"]] = relationship(
        order_by="QuotationItem.sort_order", cascade="all, delete-orphan"
    )


class QuotationItem(Base):
    """An area in the offer: the options ticked, its specs (copied) and its offer lines."""

    __tablename__ = "quotation_items"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    offer_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("offer_items.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    name: Mapped[str] = mapped_column(String(200))
    budget_title: Mapped[str] = mapped_column(Text)
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    options: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")  # ticked; [] = all
    # [{spec_block_id, version, title, heading_prefix, option_label, sections, images}]
    specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    lines: Mapped[list["QuotationLine"]] = relationship(
        order_by="QuotationLine.sort_order", cascade="all, delete-orphan"
    )


class QuotationLine(Base):
    """A budgetary offer row in this quotation: selling rate (filled or overridden), optional
    quantity. cost_rate / margin_percent are only shown with tender.margin, never printed."""

    __tablename__ = "quotation_lines"
    __table_args__ = (CheckConstraint(_in("uom", UOMS), name="uom_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_items.id", ondelete="CASCADE"), index=True
    )
    offer_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("offer_lines.id", ondelete="SET NULL")
    )
    library_version: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    option: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(String(10))
    rate: Mapped[Decimal | None] = mapped_column(Money)
    rate_source: Mapped[str | None] = mapped_column(String(20))  # system, library, fixed, manual
    rate_note: Mapped[str | None] = mapped_column(Text)
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_items.id", ondelete="SET NULL")
    )
    cost_rate: Mapped[Decimal | None] = mapped_column(Money)
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    overridden: Mapped[bool] = mapped_column(Boolean, server_default="false")
    qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    if_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    client_scope: Mapped[bool] = mapped_column(Boolean, server_default="false")


class QuotationFile(Base):
    """An issued .docx / .pdf: one per issue, kept with its revision (never overwritten)."""

    __tablename__ = "quotation_files"
    __table_args__ = (CheckConstraint("kind IN ('docx', 'pdf')", name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(4))
    path: Mapped[str] = mapped_column(String(300))
    file_name: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # a re-issue of the same revision replaces the earlier file (both are kept)
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_files.id", ondelete="SET NULL")
    )
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotationFollowUp(Base):
    """A follow-up call for the salesperson: made on "sent" (days 2, 7, 15, 30 by default),
    cancelled when the quotation is won, lost or expires."""

    __tablename__ = "quotation_followups"
    __table_args__ = (CheckConstraint(_in("status", FOLLOWUP_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)  # days after sending
    due_on: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10), server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
