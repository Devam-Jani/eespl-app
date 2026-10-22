# ruff: noqa: E501
"""The building model of a site, versioned: what the 3D view raises from the AutoCAD drawing.

Each save is a new version (the newest is the one shown). `data` holds, in drawing units with the
drawing's unit_m (see app.building.service for the shape):
  settings     floor height, slab, plinth, column size limit, beams on column lines, bloom, IFC
  levels       what the section's level texts gave (or that the defaults are used, and why)
  floor_types  per typical plan: its title, the floors it is for, the traced outline, the
               confirmed columns, beams between columns, the stair and lift cores, its shift onto
               the reference plan
  floors       per floor: level, name, node, type, elevation and height (metres)
  ifc_links    IFC element id -> site node (when the client gave a BIM file)
The rooms are not copied here: they are the traced and mapped AutoCAD areas of the same drawing
file (their node links and keys carry over to the next revision), raised on their floor."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class BuildingModel(Base):
    __tablename__ = "building_models"
    __table_args__ = (UniqueConstraint("site_id", "version"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    cad_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # what a new drawing revision changed
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
