import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.masters.models import LibraryItem, LibraryLine, Unit
from app.masters.routers.common import get_or_404
from app.masters.schemas import (
    LibraryHit,
    LibraryItemOut,
    LibraryLineOut,
    LibrarySearchOut,
    UnitOut,
)
from app.masters.search import search_library
from app.masters.units import load_aliases, normalise_unit

router = APIRouter(prefix="/api/library", tags=["library"])
units_router = APIRouter(prefix="/api/units", tags=["library"])

view = [Depends(require_permission("library.view"))]


@units_router.get("")
def list_units(db: DbSession, _: CurrentPrincipal) -> list[UnitOut]:
    return [UnitOut.model_validate(u) for u in db.scalars(select(Unit).order_by(Unit.code))]


@router.get("/search", dependencies=view)
def search(
    db: DbSession,
    q: Annotated[str, Query(max_length=300)] = "",
    unit: Annotated[str | None, Query(max_length=50, description="Unit code or spelling")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LibrarySearchOut:
    started = time.perf_counter()
    unit_code = normalise_unit(unit, load_aliases(db)) if unit else None
    if unit and unit_code is None:
        return LibrarySearchOut(items=[], took_ms=0)
    rows = search_library(db, q, unit_code, limit)
    return LibrarySearchOut(
        items=[LibraryHit(**r) for r in rows],
        took_ms=round((time.perf_counter() - started) * 1000, 1),
    )


@router.get("/items/{item_id}", dependencies=view)
def get_item(item_id: int, db: DbSession) -> LibraryItemOut:
    item = get_or_404(db, LibraryItem, item_id, "Library item")
    return LibraryItemOut.model_validate(item, from_attributes=True)


@router.get("/items/{item_id}/lines", dependencies=view)
def item_lines(item_id: int, db: DbSession) -> list[LibraryLineOut]:
    get_or_404(db, LibraryItem, item_id, "Library item")
    rows = db.scalars(
        select(LibraryLine)
        .where(LibraryLine.library_item_id == item_id)
        .order_by(LibraryLine.from_eespl_file.desc(), LibraryLine.client_folder, LibraryLine.file)
    )
    return [LibraryLineOut.model_validate(r) for r in rows]
