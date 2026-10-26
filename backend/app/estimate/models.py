# ruff: noqa: E501  (column definitions read better unwrapped)
"""Material estimates from the measured drawing, read from one product library.

The library holds one coverage per product per system (a product's own row, system blank, is used
where the system has none): the value used with its min and max, its unit and where it came from
(a data sheet, the BOQ spec, the method statement, a site trial) with the document. Wastage is the
product's own factor and pack sizes are the product's; a mix design (nodular concrete, plaster,
brick bat) gives cement, sand, aggregate and admixture per sqm from its thickness.

An estimate has one set of areas, taken from the site's measured areas (Measure and bill, or the
accepted takeoff areas): each gives its floor and its periphery × the upturn height; an area drawn
inside another (a shaft in a terrace) is cut out of it and kept as a Misc area with its own
periphery. Every material line reads that one set, so two lines can never use two figures for the
same floor. A measured area left out of the estimate must be marked excluded with a reason.

The site asks for a material by area and thickness; planning approves it into an indent."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.masters.models import Tracked
from app.models import Base

Exact = Numeric(24, 10)
Qty = Numeric(14, 3)

COVERAGE_UNITS = ("kg/sqm", "L/sqm", "sqm/kg", "sqm/L", "kg/sqft", "sqm/sqm")  # sqm/sqm: a fabric laid per sqm
COVERAGE_SOURCES = ("tds", "boq_spec", "method_statement", "site_trial", "to_confirm")
MIX_KINDS = ("nodular", "plaster", "brick_bat", "other")
AREA_SOURCES = ("measure", "takeoff", "misc", "manual")
ESTIMATE_STATUSES = ("draft", "issued")
LINE_PARTS = ("both", "floor", "upturn")
REQUEST_STATUSES = ("requested", "approved", "rejected", "indented")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Coverage(Tracked, Base):
    """A product's coverage in a system (system blank: the product's own, for any system)."""

    __tablename__ = "coverages"
    __table_args__ = (
        CheckConstraint(_in("unit", COVERAGE_UNITS), name="unit_valid"),
        CheckConstraint(_in("source", COVERAGE_SOURCES), name="source_valid"),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("min_value IS NULL OR max_value IS NULL OR min_value <= max_value", name="range_valid"),
        Index("ux_coverages_product_system", "product_id", text("coalesce(system_id, 0)"), unique=True),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4))  # the one used
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit: Mapped[str] = mapped_column(String(10), server_default="kg/sqm")
    source: Mapped[str] = mapped_column(String(16), server_default="to_confirm")
    doc_path: Mapped[str | None] = mapped_column(String(400))  # under media/
    doc_name: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MixDesign(Tracked, Base):
    """A site mix: per component its share of the mix (parts) and its bulk density; per sqm =
    thickness × dry-volume factor × parts / all parts × density. The admixture is dosed per bag of
    cement. round_sqft: the planning sheet's kg per sqft is rounded to this many decimals first."""

    __tablename__ = "mix_designs"
    __table_args__ = (CheckConstraint(_in("kind", MIX_KINDS), name="kind_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), server_default="other")
    thickness_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2))  # the default
    dry_volume_factor: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    # [{"role": "cement", "product_id": 1, "parts": 1, "density": 1440}]
    components: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    admixture_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    admixture_per_bag: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # L (or kg) per cement bag
    cement_bag_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="50")
    round_sqft: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), server_default="to_confirm")
    note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Estimate(Tracked, Base):
    __tablename__ = "estimates"
    __table_args__ = (
        CheckConstraint(_in("status", ESTIMATE_STATUSES), name="status_valid"),
        CheckConstraint("site_id IS NOT NULL OR tender_id IS NOT NULL", name="has_parent"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    upturn_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="300")  # when the system sets none
    note: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")


class EstimateArea(Base):
    """One area of the estimate's one area set. A Misc area is a cut-out of its parent (a shaft):
    its floor is out of the parent's and, by default, only its periphery's upturn is counted."""

    __tablename__ = "estimate_areas"
    __table_args__ = (
        CheckConstraint(_in("source", AREA_SOURCES), name="source_valid"),
        CheckConstraint("included OR excluded_reason IS NOT NULL", name="excluded_has_reason"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(10))
    measure_area_id: Mapped[int | None] = mapped_column(ForeignKey("measure_areas.id", ondelete="SET NULL"))
    cad_area_id: Mapped[int | None] = mapped_column(ForeignKey("cad_areas.id", ondelete="SET NULL"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("estimate_areas.id", ondelete="CASCADE"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    code: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    floor_sqm: Mapped[Decimal] = mapped_column(Exact)  # as drawn
    deduction_sqm: Mapped[Decimal] = mapped_column(Exact, server_default="0")  # the cut-outs inside it
    periphery_m: Mapped[Decimal] = mapped_column(Exact)
    upturn_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # blank: the line's system, else the estimate's
    use_floor: Mapped[bool] = mapped_column(Boolean, server_default="true")
    use_upturn: Mapped[bool] = mapped_column(Boolean, server_default="true")
    included: Mapped[bool] = mapped_column(Boolean, server_default="true")
    excluded_reason: Mapped[str | None] = mapped_column(Text)


class EstimateLine(Base):
    """One material: the library's coverage for its product in its system (or a mix design's
    component at a thickness), its wastage, on the parts and areas it covers (blank: all)."""

    __tablename__ = "estimate_lines"
    __table_args__ = (CheckConstraint(_in("part", LINE_PARTS), name="part_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    mix_design_id: Mapped[int | None] = mapped_column(ForeignKey("mix_designs.id", ondelete="SET NULL"))
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    part: Mapped[str] = mapped_column(String(6), server_default="both")
    area_ids: Mapped[list[int] | None] = mapped_column(JSONB)  # blank: every included area
    note: Mapped[str | None] = mapped_column(Text)


class MaterialRequest(Tracked, Base):
    """The site's ask ("nodular, 280 sqm, 130 mm"), worked out from the library and the mix, its
    formula as shown, checked against what the estimate still has for that area and material."""

    __tablename__ = "material_requests"
    __table_args__ = (CheckConstraint(_in("status", REQUEST_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    estimate_id: Mapped[int | None] = mapped_column(ForeignKey("estimates.id", ondelete="SET NULL"))
    estimate_area_id: Mapped[int | None] = mapped_column(ForeignKey("estimate_areas.id", ondelete="SET NULL"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    mix_design_id: Mapped[int | None] = mapped_column(ForeignKey("mix_designs.id", ondelete="SET NULL"))
    area_sqm: Mapped[Decimal] = mapped_column(Qty)
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    qty: Mapped[Decimal] = mapped_column(Qty)  # in the product's unit
    packs: Mapped[int | None] = mapped_column(Integer)
    formula: Mapped[str] = mapped_column(Text)
    left_before: Mapped[Decimal | None] = mapped_column(Qty)  # the estimate's balance when asked
    over_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="requested")
    approved_qty: Mapped[Decimal | None] = mapped_column(Qty)
    change_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indent_id: Mapped[int | None] = mapped_column(ForeignKey("indents.id", ondelete="SET NULL"))
