import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.export import xlsx_response
from app.masters.library import MergeError, merge, unmerge
from app.masters.models import LibraryItem, LibraryLine, Unit
from app.masters.routers.common import get_or_404, unprocessable
from app.masters.schemas import (
    LibraryHit,
    LibraryItemDetail,
    LibraryItemUpdate,
    LibraryLineOut,
    LibrarySearchOut,
    MergedItemRef,
    MergeIn,
    UnitOut,
)
from app.masters.search import search_library
from app.masters.units import load_aliases, normalise_unit

router = APIRouter(prefix="/api/library", tags=["library"])
units_router = APIRouter(prefix="/api/units", tags=["library"])

view = [Depends(require_permission("library.view"))]
edit = [Depends(require_permission("library.edit"))]

ITEM_AUDIT_FIELDS = (
    "unit",
    "unit_raw",
    "unit_manual",
    "is_excluded",
    "excluded_reason",
    "exclusion_source",
    "merged_into_id",
    "boq_count",
    "latest_rate",
    "min_rate",
    "median_rate",
    "max_rate",
)


def _item_snapshot(item: LibraryItem) -> dict:
    return {k: getattr(item, k) for k in ITEM_AUDIT_FIELDS}


def _ref(item: LibraryItem) -> MergedItemRef:
    return MergedItemRef(id=item.id, description=item.description, unit=item.unit)


def _detail(db: Session, item: LibraryItem) -> LibraryItemDetail:
    merged = db.scalars(
        select(LibraryItem).where(LibraryItem.merged_into_id == item.id).order_by(LibraryItem.id)
    )
    target = db.get(LibraryItem, item.merged_into_id) if item.merged_into_id else None
    return LibraryItemDetail.model_validate(
        {
            **{c.key: getattr(item, c.key) for c in LibraryItem.__table__.columns},
            "merged_into": _ref(target) if target else None,
            "merged_items": [_ref(m) for m in merged],
        }
    )


@units_router.get("")
def list_units(db: DbSession, _: CurrentPrincipal) -> list[UnitOut]:
    return [UnitOut.model_validate(u) for u in db.scalars(select(Unit).order_by(Unit.code))]


@router.get("/search", dependencies=view)
def search(
    db: DbSession,
    q: Annotated[str, Query(max_length=300)] = "",
    unit: Annotated[str | None, Query(max_length=50, description="Unit code or spelling")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_flagged: Annotated[
        bool, Query(description="Also return items hidden as working rows / below ₹1 / by hand")
    ] = False,
    include_competitor: Annotated[
        bool, Query(description="Also return other bidders' rates from comparative sheets")
    ] = False,
    cut: Annotated[
        bool, Query(description="Apply the relevance cut on the first page (see search.py)")
    ] = True,
) -> LibrarySearchOut:
    started = time.perf_counter()
    unit_code = normalise_unit(unit, load_aliases(db)) if unit else None
    if unit and unit_code is None:
        return LibrarySearchOut(
            items=[], took_ms=0, has_more=False, next_offset=offset, cut_applied=False
        )
    result = search_library(
        db,
        q,
        unit=unit_code,
        limit=limit,
        offset=offset,
        include_flagged=include_flagged,
        include_competitor=include_competitor,
        cut=cut,
    )
    return LibrarySearchOut(
        items=[LibraryHit(**r) for r in result.items],
        took_ms=round((time.perf_counter() - started) * 1000, 1),
        has_more=result.has_more,
        next_offset=offset + len(result.items),
        cut_applied=result.cut_applied,
    )


@router.get("/search/export", dependencies=view)
def export_search(
    db: DbSession,
    q: Annotated[str, Query(max_length=300)] = "",
    unit: Annotated[str | None, Query(max_length=50)] = None,
    include_flagged: bool = False,
    include_competitor: bool = False,
):
    """The ranked results for a search (up to 500, without the relevance cut)."""
    unit_code = normalise_unit(unit, load_aliases(db)) if unit else None
    items = []
    if not (unit and unit_code is None):
        items = search_library(db, q, unit=unit_code, limit=500, include_flagged=include_flagged,
                               include_competitor=include_competitor, cut=False).items  # fmt: skip
    hits = [LibraryHit(**r) for r in items]
    return xlsx_response(
        "rate-library",
        ["Description", "Unit", "Suggested rate", "Latest", "Min", "Median", "Max", "BOQs",
         "Latest channel", "Other bidder", "Hidden", "Check note"],
        [[h.description, h.unit, h.suggested_rate, h.latest_rate, h.min_rate, h.median_rate,
          h.max_rate, h.boq_count, h.latest_channel, h.is_competitor, h.is_excluded, h.check_note]
         for h in hits],
    )  # fmt: skip


@router.get("/items/{item_id}", dependencies=view)
def get_item(item_id: int, db: DbSession) -> LibraryItemDetail:
    return _detail(db, get_or_404(db, LibraryItem, item_id, "Library item"))


@router.get("/items/{item_id}/lines", dependencies=view)
def item_lines(item_id: int, db: DbSession) -> list[LibraryLineOut]:
    """The item's source lines, including those of items merged into it."""
    get_or_404(db, LibraryItem, item_id, "Library item")
    merged = select(LibraryItem.id).where(LibraryItem.merged_into_id == item_id)
    rows = db.scalars(
        select(LibraryLine)
        .where(
            or_(LibraryLine.library_item_id == item_id, LibraryLine.library_item_id.in_(merged))
        )
        .order_by(
            LibraryLine.is_competitor,
            LibraryLine.is_excluded,
            LibraryLine.from_eespl_file.desc(),
            LibraryLine.channel,
            LibraryLine.file,
        )
    )
    return [LibraryLineOut.model_validate(r) for r in rows]


@router.patch("/items/{item_id}", dependencies=edit)
def update_item(
    item_id: int,
    body: LibraryItemUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> LibraryItemDetail:
    """Hide from search / show again, and change the unit. Both survive re-imports."""
    item = get_or_404(db, LibraryItem, item_id, "Library item")
    before = _item_snapshot(item)
    if body.is_excluded is True:
        item.is_excluded = True
        item.excluded_reason = body.excluded_reason.strip()
        item.exclusion_source = "manual"
    elif body.is_excluded is False:
        item.is_excluded = False
        item.excluded_reason = None
        item.exclusion_source = "manual"
    if body.unit is not None:
        code = normalise_unit(body.unit, load_aliases(db))
        if code is None:
            raise unprocessable(f"Unknown unit: {body.unit}")
        item.unit = code  # unit_raw keeps what the source said
        item.unit_manual = True
    db.flush()
    after = _item_snapshot(item)
    if after != before:
        audit.record(db, "library_item.update", "library_item", item.id,
                     user_id=principal.user.id, before=before, after=after,
                     ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(item)
    return _detail(db, item)


@router.post("/items/{item_id}/merge", dependencies=edit)
def merge_item(
    item_id: int,
    body: MergeIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> LibraryItemDetail:
    """Merge this item into another: its lines count there and it leaves search. Reversible."""
    source = get_or_404(db, LibraryItem, item_id, "Library item")
    target = get_or_404(db, LibraryItem, body.into_id, "Target item")
    target_before = _item_snapshot(target)
    try:
        moved = merge(db, source, target)
    except MergeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.refresh(target)
    audit.record(db, "library_item.merge", "library_item", source.id,
                 user_id=principal.user.id,
                 before={"target": target.id, "target_stats": target_before},
                 after={"target": target.id, "merged_ids": moved,
                        "target_stats": _item_snapshot(target)},
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(target)
    return _detail(db, target)


@router.post("/items/{item_id}/unmerge", dependencies=edit)
def unmerge_item(
    item_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> LibraryItemDetail:
    item = get_or_404(db, LibraryItem, item_id, "Library item")
    try:
        target_id = unmerge(db, item)
    except MergeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.record(db, "library_item.unmerge", "library_item", item.id,
                 user_id=principal.user.id, before={"merged_into_id": target_id},
                 after={"merged_into_id": None}, ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(item)
    return _detail(db, item)

