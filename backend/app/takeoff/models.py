"""AutoCAD takeoff: a drawing revision read from its DWG (or DXF), the layer roles per architect,
and the areas found on it (from size labels and waterproofing notes, or traced), mapped to the site
and accepted into the survey and the measurement book.

Coordinates stay in drawing units (unit_m converts them: 0.0254 for inches, 0.001 for mm); areas
and lengths are stored in metres."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.masters.models import Tracked
from app.models import Base

READ_STATUSES = ("queued", "reading", "ready", "failed")
AREA_STATUSES = ("candidate", "mapped", "accepted", "ignored")
LAYER_ROLES = ("walls", "rooms", "dimensions", "text", "hide")
M = Numeric(12, 3)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CadFile(Tracked, Base):
    """One drawing revision read: its format and units, the DXF and the viewer's geometry kept
    beside the DWG (versioned with the revision), and the parsed summary."""

    __tablename__ = "cad_files"
    __table_args__ = (CheckConstraint(_in("status", READ_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("drawing_revisions.id", ondelete="CASCADE"), unique=True
    )
    drawing_id: Mapped[int] = mapped_column(
        ForeignKey("drawings.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(10), server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)  # shown as it is: what to do about it
    dwg_version: Mapped[str | None] = mapped_column(String(40))
    dxf_path: Mapped[str | None] = mapped_column(String(400))
    geometry_path: Mapped[str | None] = mapped_column(String(400))
    units_code: Mapped[int | None] = mapped_column(Integer)  # $INSUNITS as read
    unit_m: Mapped[float | None] = mapped_column(Float)  # metres per drawing unit
    units_set_by_hand: Mapped[bool] = mapped_column(Boolean, server_default="false")
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    texts: Mapped[list[Any] | None] = mapped_column(JSONB)  # [[x, y, h, layer, text], ...]
    dimensions: Mapped[list[Any] | None] = mapped_column(JSONB)  # [[x, y, value, text, layer]]
    warnings: Mapped[int] = mapped_column(Integer, server_default="0")
    architect: Mapped[str | None] = mapped_column(String(200))  # whose layer mapping applies
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # where the worker's read is: converting, reading, finding areas, done (or failed)
    progress: Mapped[str | None] = mapped_column(String(30))
    progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CadLayerMap(Tracked, Base):
    """An architect's layers, saved once and reused: {layer: walls | rooms | dimensions | text |
    hide}. Hidden layers (furniture, electrical, hatch) are off in the viewer and not read."""

    __tablename__ = "cad_layer_maps"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    architect: Mapped[str] = mapped_column(String(200), unique=True)
    roles: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class CadArea(Tracked, Base):
    """An area on the drawing: from a label with its size, or traced (both kept when both exist),
    with the notes near it (CHEMICAL WATER PROOFING, 600 MM SUNK), mapped to the site's place and
    area type, and once accepted, its survey area and measurement-book lines."""

    __tablename__ = "cad_areas"
    __table_args__ = (CheckConstraint(_in("status", AREA_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    cad_file_id: Mapped[int] = mapped_column(
        ForeignKey("cad_files.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(160), index=True)  # matches it on the next revision
    name: Mapped[str] = mapped_column(String(200))
    label_text: Mapped[str | None] = mapped_column(Text)
    size_text: Mapped[str | None] = mapped_column(String(60))
    size_kind: Mapped[str | None] = mapped_column(String(6))  # ft-in, mm, m
    label_w_m: Mapped[Decimal | None] = mapped_column(M)
    label_l_m: Mapped[Decimal | None] = mapped_column(M)
    label_area_sqm: Mapped[Decimal | None] = mapped_column(M)
    x: Mapped[float | None] = mapped_column(Float)  # the label, drawing units
    y: Mapped[float | None] = mapped_column(Float)
    plan: Mapped[str | None] = mapped_column(String(200))  # the floor plan's title under it
    # no frame around it: the nearest title in its cluster, for the user to confirm
    plan_guessed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notes: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    sunk_m: Mapped[Decimal | None] = mapped_column(M)
    raise_m: Mapped[Decimal | None] = mapped_column(M)
    outline: Mapped[list[Any] | None] = mapped_column(JSONB)  # [[x, y], ...] drawing units
    traced_area_sqm: Mapped[Decimal | None] = mapped_column(M)
    traced_perimeter_m: Mapped[Decimal | None] = mapped_column(M)
    side_wall_sqm: Mapped[Decimal | None] = mapped_column(M)  # perimeter × sunk depth
    node_id: Mapped[int | None] = mapped_column(ForeignKey("site_nodes.id", ondelete="SET NULL"))
    area_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("area_types.id", ondelete="SET NULL")
    )
    system_id: Mapped[int | None] = mapped_column(ForeignKey("systems.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), server_default="candidate")
    copied_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("cad_areas.id", ondelete="SET NULL")
    )
    floor_label: Mapped[str | None] = mapped_column(String(60))  # for copies: "4TH FLOOR"
    change: Mapped[str | None] = mapped_column(String(10))  # added, resized (vs the last revision)
    previous_area_sqm: Mapped[Decimal | None] = mapped_column(M)
    survey_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("survey_areas.id", ondelete="SET NULL")
    )
    measurement_id: Mapped[int | None] = mapped_column(
        ForeignKey("measurements.id", ondelete="SET NULL")
    )
    side_measurement_id: Mapped[int | None] = mapped_column(
        ForeignKey("measurements.id", ondelete="SET NULL")
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TakeoffSettings(Base):
    """One row (id 1)."""

    __tablename__ = "takeoff_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # label size against the traced outline: flag past this (the survey's own check uses its
    # mismatch setting for AutoCAD against laser or manual)
    label_trace_diff_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="3")
    note_radius_m: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="6")
