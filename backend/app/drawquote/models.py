# ruff: noqa: E501  (the column notes read better unwrapped)
"""From the drawing to the quotation: one run per drawing revision (its area types, the options
picked for each, the areas left out with their reason), the areas behind each quotation line with
their numbers, and the review grid's cells a person changed."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.masters.models import Tracked
from app.models import Base

M = Numeric(14, 3)
RUN_STATUSES = ("picking", "made")
EDIT_KINDS = ("qty", "consumption", "price", "freight", "wastage", "labour", "margin")


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class DrawQuote(Tracked, Base):
    """ "Make quotation from drawing" on one drawing revision: picking, then made (its quotation,
    whose rate working is the quotation's). A run on a newer revision of the same site's drawing
    makes the next revision of that quotation (previous_id)."""

    __tablename__ = "draw_quotes"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status_valid"),
        CheckConstraint("unit IN ('sqm', 'sqft')", name="unit_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    cad_file_id: Mapped[int] = mapped_column(
        ForeignKey("cad_files.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    unit: Mapped[str] = mapped_column(String(4), server_default="sqm")  # the quotation's lines
    status: Mapped[str] = mapped_column(String(8), server_default="picking")
    quotation_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotations.id", ondelete="SET NULL")
    )
    previous_id: Mapped[int | None] = mapped_column(
        ForeignKey("draw_quotes.id", ondelete="SET NULL")
    )
    # what the new revision changed, line by line: [{line, old_qty, new_qty, areas: {added, removed, resized}}]
    changes: Mapped[list | None] = mapped_column(JSONB)

    items: Mapped[list["DrawQuoteItem"]] = relationship(
        order_by="DrawQuoteItem.sort_order, DrawQuoteItem.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DrawQuoteItem(Base):
    """An area type on the drawing: its key points (the area, sunk or exposed, the client's spec
    line when one is attached), the options picked, or left out with its reason."""

    __tablename__ = "draw_quote_items"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("draw_quotes.id", ondelete="CASCADE"), index=True
    )
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    spec_text: Mapped[str | None] = mapped_column(Text)
    excluded_reason: Mapped[str | None] = mapped_column(Text)
    quotation_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_items.id", ondelete="SET NULL")
    )
    picks: Mapped[list["DrawQuotePick"]] = relationship(
        order_by="DrawQuotePick.sort_order, DrawQuotePick.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DrawQuotePick(Base):
    """One thing quoted for an area type: a work item's brand option, or a product added by
    search (its consumption typed). Two picks for one area type are two options of the item."""

    __tablename__ = "draw_quote_picks"
    __table_args__ = (
        CheckConstraint("(system_id IS NOT NULL) OR (product_id IS NOT NULL)", name="what_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("draw_quote_items.id", ondelete="CASCADE"), index=True
    )
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    option_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_options.id", ondelete="SET NULL")
    )
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    consumption: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # a product's, per sqm
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    quotation_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="SET NULL")
    )
    group_id: Mapped[int | None] = mapped_column(ForeignKey("rate_groups.id", ondelete="SET NULL"))


class DrawQuoteExclusion(Base):
    """An area on the drawing left out of the quotation, with why."""

    __tablename__ = "draw_quote_exclusions"
    __table_args__ = (UniqueConstraint("run_id", "cad_area_id"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("draw_quotes.id", ondelete="CASCADE"), index=True
    )
    cad_area_id: Mapped[int] = mapped_column(ForeignKey("cad_areas.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteLineArea(Base):
    """An area behind a quotation line, with its numbers as taken from the drawing."""

    __tablename__ = "quote_line_areas"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    quotation_line_id: Mapped[int] = mapped_column(
        ForeignKey("quotation_lines.id", ondelete="CASCADE"), index=True
    )
    cad_area_id: Mapped[int | None] = mapped_column(ForeignKey("cad_areas.id", ondelete="SET NULL"))
    cad_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id", ondelete="SET NULL"))
    area_key: Mapped[str] = mapped_column(String(160))
    area_name: Mapped[str] = mapped_column(String(200))
    floor: Mapped[str | None] = mapped_column(String(200))
    floor_sqm: Mapped[Decimal] = mapped_column(M)
    cutout_sqm: Mapped[Decimal] = mapped_column(M, server_default="0")
    periphery_m: Mapped[Decimal] = mapped_column(M, server_default="0")
    upturn_m: Mapped[Decimal] = mapped_column(M, server_default="0")
    upturn_from: Mapped[str | None] = mapped_column(String(40))
    sunk_m: Mapped[Decimal] = mapped_column(M, server_default="0")
    wall_length_m: Mapped[Decimal] = mapped_column(M, server_default="0")
    wall_height_m: Mapped[Decimal] = mapped_column(M, server_default="0")
    total_sqm: Mapped[Decimal] = mapped_column(M)
    formula: Mapped[str] = mapped_column(Text)


class DrawQuoteEdit(Base):
    """A review-grid cell a person changed: what the app worked out, what they typed, who, when.
    "Back to calculated" deletes the row and puts the calculated figure back."""

    __tablename__ = "draw_quote_edits"
    __table_args__ = (
        CheckConstraint(_in("kind", EDIT_KINDS), name="kind_valid"),
        UniqueConstraint("run_id", "kind", "ref_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("draw_quotes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))
    ref_id: Mapped[int] = mapped_column(
        BigInteger
    )  # the quotation line, the working's product or main item
    calculated: Mapped[str | None] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text)
    by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
