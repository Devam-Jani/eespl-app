# ruff: noqa: E501  (column definitions read better unwrapped)
"""Measuring from the drawing and the measurement sheet the RA bill is made from.

An area is an outline on the drawing (clicked or traced, arcs kept as arcs) with its true area and
periphery, what it was trimmed by, its heights with where each came from on a section, its wall
top and, for a slope, its rise and run. A shared edge between two areas is asked once: wall on it
(both faces), open, or a weir of some height. A work-order item says how it is measured (floor,
walls, wall tops, slope face, a count), in how many layers, and whether its rate is per layer.

A sheet is one bill's measurement, in the billing team's layout: per area a header, then the
lines (No, L, W, H, Qty) with deductions as negative lines and their reason; its totals go to the
measurement book, the client approves them, and the RA bill takes them. An area is billed once
per item and layer (measure_billed's unique key)."""

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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.masters.models import Tracked
from app.models import Base

Exact = Numeric(24, 10)  # sizes and quantities at full precision
Total = Numeric(16, 3)  # a sheet line's total, rounded half up to 3 decimals

AREA_KINDS = ("area", "slope")
EDGE_ANSWERS = ("both", "open", "weir", "none")  # none: drawn close, not one wall
PARTS = ("floor", "walls", "tops", "slope", "count")
SHEET_STATUSES = ("draft", "sent", "approved", "billed", "study")  # study: a what-if, never sent or billed
LINE_KINDS = ("area", "line", "deduction", "not_done", "total")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MeasureArea(Tracked, Base):
    __tablename__ = "measure_areas"
    __table_args__ = (
        CheckConstraint(_in("kind", AREA_KINDS), name="kind_valid"),
        UniqueConstraint("site_id", "code"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    cad_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id", ondelete="SET NULL"))
    code: Mapped[str] = mapped_column(String(10))  # A, Q, R: as the billing team marks the drawing
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(6), server_default="area")
    # [[x, y, bulge], ...] in metres, as drawn (picked: the polyline's handle and layer)
    outline: Mapped[list[Any]] = mapped_column(JSONB)
    picked: Mapped[bool] = mapped_column(Boolean, server_default="true")  # false: traced by hand
    handle: Mapped[str | None] = mapped_column(String(20))
    layer: Mapped[str | None] = mapped_column(String(200))
    area_sqm: Mapped[Decimal] = mapped_column(Exact)  # the outline's, exact
    periphery_m: Mapped[Decimal] = mapped_column(Exact)
    # a polyline drawn round but not closed (its ends this far apart): the app closes it; the line
    # as drawn (without the closing gap) is what AutoCAD shows as its length
    closed_gap_mm: Mapped[Decimal | None] = mapped_column(Exact)
    drawn_length_m: Mapped[Decimal | None] = mapped_column(Exact)
    trim_with: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")  # area ids cut away
    net_area_sqm: Mapped[Decimal] = mapped_column(Exact)  # after the trim
    net_periphery_m: Mapped[Decimal] = mapped_column(Exact)
    # heights in mm with where each came from ("Section Y-Y: +1800 to +600 = 1200 mm"); two for a
    # floor that slopes (shallow and deep end): the walls use their average
    height_mm: Mapped[Decimal | None] = mapped_column(Exact)
    height_source: Mapped[str | None] = mapped_column(Text)
    height2_mm: Mapped[Decimal | None] = mapped_column(Exact)
    height2_source: Mapped[str | None] = mapped_column(Text)
    wall_top_mm: Mapped[Decimal] = mapped_column(Exact, server_default="250")
    # a slope: its rise over its horizontal run (mm), from the section
    rise_mm: Mapped[Decimal | None] = mapped_column(Exact)
    run_mm: Mapped[Decimal | None] = mapped_column(Exact)
    slope_mm: Mapped[Decimal | None] = mapped_column(Exact)  # the slope's own length (a picked line, an arc kept)
    slope_source: Mapped[str | None] = mapped_column(Text)
    # what is drawn inside it, counted when it was picked: {"layer:SLEEVE": 4, "block:SLV": 2}
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, server_default="{}")
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))


class MeasureEdge(Base):
    """A straight edge two areas share, and the one answer about it."""

    __tablename__ = "measure_edges"
    __table_args__ = (
        CheckConstraint(f"answer IS NULL OR {_in('answer', EDGE_ANSWERS)}", name="answer_valid"),
        CheckConstraint("answer <> 'weir' OR weir_mm IS NOT NULL", name="weir_has_height"),
        UniqueConstraint("area_a_id", "area_b_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    area_a_id: Mapped[int] = mapped_column(ForeignKey("measure_areas.id", ondelete="CASCADE"))
    area_b_id: Mapped[int] = mapped_column(ForeignKey("measure_areas.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, server_default="0")
    length_m: Mapped[Decimal] = mapped_column(Exact)
    line: Mapped[list[float]] = mapped_column(JSONB)  # [x1, y1, x2, y2] metres
    answer: Mapped[str | None] = mapped_column(String(5))
    weir_mm: Mapped[Decimal | None] = mapped_column(Exact)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # drawn as its own line between two areas drawn apart (not found from the outlines): kept
    source: Mapped[str | None] = mapped_column(Text)
    manual: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MeasureItem(Base):
    """How a work-order item is measured on this site: which parts of each area, a count's layer
    or block, how many layers, and (rate not per layer, more than one layer) the answer to
    "bill each layer, or the item once?"."""

    __tablename__ = "measure_items"
    __table_args__ = (
        UniqueConstraint("site_id", "wo_line_id"),
        CheckConstraint("layers >= 1", name="layers_positive"),
        CheckConstraint("layers_answer IS NULL OR layers_answer IN ('each', 'once')", name="layers_answer_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    wo_line_id: Mapped[int] = mapped_column(ForeignKey("client_work_order_lines.id", ondelete="CASCADE"))
    parts: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    count_of: Mapped[str | None] = mapped_column(String(200))  # "layer:SLEEVE" or "block:SLV"
    layers: Mapped[int] = mapped_column(Integer, server_default="1")
    layers_answer: Mapped[str | None] = mapped_column(String(4))
    areas: Mapped[list[int] | None] = mapped_column(JSONB)  # only these areas (none: every area)
    skip: Mapped[dict[str, list[str]]] = mapped_column(JSONB, server_default="{}")  # {area id: parts not done there}
    manual: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")  # {area id: count on site}


class MeasureSheet(Tracked, Base):
    __tablename__ = "measure_sheets"
    __table_args__ = (
        CheckConstraint(_in("status", SHEET_STATUSES), name="status_valid"),
        UniqueConstraint("site_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40), unique=True)  # MS-<site>-01
    title: Mapped[str | None] = mapped_column(String(200))
    measured_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    # (area, item, layer) the billing team marked as work not done on this bill: "–" on the sheet
    not_done: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    # a study sheet's way of measuring (another way to compare with the app's): its areas, sizes
    # truncated or not, sqft per sqm, converted per line or per item, grouped by area or item, and
    # what it takes differently for an area, an edge or an item
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    set_id: Mapped[int | None] = mapped_column(ForeignKey("measurement_sets.id", ondelete="SET NULL"))
    ra_bill_id: Mapped[int | None] = mapped_column(ForeignKey("ra_bills.id", ondelete="SET NULL"))
    # read from an old Excel sheet: its quantities are the "previous" (what could not be read is kept)
    imported_from: Mapped[str | None] = mapped_column(String(300))
    import_skipped: Mapped[list[Any] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # a bill from a site slip: the client's handwritten page (photo or PDF) with its lines in ft-in,
    # signed and dated by the client's person on site (their role, never a name)
    slip_path: Mapped[str | None] = mapped_column(String(400))
    slip_name: Mapped[str | None] = mapped_column(String(300))
    slip_on: Mapped[date | None] = mapped_column(Date)
    signed_by: Mapped[str | None] = mapped_column(String(200))
    signed_on: Mapped[date | None] = mapped_column(Date)


class MeasureLine(Base):
    __tablename__ = "measure_lines"
    __table_args__ = (CheckConstraint(_in("kind", LINE_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("measure_sheets.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("measure_areas.id", ondelete="SET NULL"))
    edge_id: Mapped[int | None] = mapped_column(ForeignKey("measure_edges.id", ondelete="SET NULL"))
    wo_line_id: Mapped[int | None] = mapped_column(ForeignKey("client_work_order_lines.id", ondelete="SET NULL"))
    item_no: Mapped[str | None] = mapped_column(String(30))  # the WO item as printed (imported sheets)
    layer: Mapped[int] = mapped_column(Integer, server_default="1")
    part: Mapped[str | None] = mapped_column(String(6))
    particulars: Mapped[str] = mapped_column(Text)
    no: Mapped[Decimal | None] = mapped_column(Exact)
    length_m: Mapped[Decimal | None] = mapped_column(Exact)
    width_m: Mapped[Decimal | None] = mapped_column(Exact)
    height_m: Mapped[Decimal | None] = mapped_column(Exact)
    qty: Mapped[Decimal | None] = mapped_column(Exact)  # sqm (or nos), signed, full precision
    total: Mapped[Decimal | None] = mapped_column(Total)  # in the item's unit, rounded
    unit: Mapped[str | None] = mapped_column(String(20))
    formula: Mapped[str | None] = mapped_column(Text)  # how the qty was worked out, in words
    reason: Mapped[str | None] = mapped_column(Text)  # a deduction's
    # a slip's line as written ({"no": "26", "length": "16'0\"", "width": null}) and whether it is
    # billed (a line the billing team leaves out stays listed, with the reason)
    typed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    billed: Mapped[bool] = mapped_column(Boolean, server_default="true")


class BillRevision(Base):
    """One version of an RA bill (R0, R1 ...) as it was made: its lines and totals kept as they
    were, where it came from (the app, or an old file: "Not for invoice", "revised"), and the one
    sent to the client."""

    __tablename__ = "bill_revisions"
    __table_args__ = (
        UniqueConstraint("ra_bill_id", "rev_no"),
        Index("ux_bill_revisions_one_sent", "ra_bill_id", unique=True, postgresql_where=text("sent")),  # one sent per bill
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ra_bill_id: Mapped[int] = mapped_column(ForeignKey("ra_bills.id", ondelete="CASCADE"), index=True)
    rev_no: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(300))  # "the app", or the old file's name
    made_on: Mapped[date | None] = mapped_column(Date)
    lines: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")  # [{item_no, description, unit, qty, rate, amount}]
    basic: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    gst: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    sent: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegisterImport(Tracked, Base):
    """An old bill register (the billing team's Excel) and the project folder read for a site: the
    register's rows as written, and what was found (numbers missing or used twice, dates out of
    order, bills missing from the register)."""

    __tablename__ = "register_imports"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(300))
    rows: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    files: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")  # the folder's bill files as read
    findings: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")


class MeasureBilled(Base):
    """An area billed for an item in a layer, by which sheet: the same three are never billed twice."""

    __tablename__ = "measure_billed"
    __table_args__ = (UniqueConstraint("area_id", "wo_line_id", "layer"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("measure_areas.id", ondelete="CASCADE"))
    wo_line_id: Mapped[int] = mapped_column(ForeignKey("client_work_order_lines.id", ondelete="CASCADE"))
    layer: Mapped[int] = mapped_column(Integer)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("measure_sheets.id", ondelete="CASCADE"), index=True)


VARIATION_STATUSES = ("proposed", "approved", "rejected")


class VariationRequest(Tracked, Base):
    """A slip line with no work-order item (gabda, frame fitting): billing proposes a new item or
    variation (description, unit, rate); the director approves it; it is added to the work order
    as a variation item, the line is mapped to it and can be billed, and it goes to the client with
    the bill. Until then the line stays listed as unbilled."""

    __tablename__ = "variation_requests"
    __table_args__ = (CheckConstraint(_in("status", VARIATION_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("measure_sheets.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("measure_lines.id", ondelete="SET NULL"))
    particulars: Mapped[str] = mapped_column(Text)  # the slip line as written
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20))
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(10), server_default="proposed")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    wo_line_id: Mapped[int | None] = mapped_column(ForeignKey("client_work_order_lines.id", ondelete="SET NULL"))
    ra_bill_id: Mapped[int | None] = mapped_column(ForeignKey("ra_bills.id", ondelete="SET NULL"))
