# ruff: noqa: E501  (the route signatures read better unwrapped)
"""Make quotation from drawing (drawquote.make: the super admin, planning, the estimator), on a site
the caller can see (site.view scope). Cost, rates and margin show only to those who see costs
(tender.margin, or consumption.cost); the client's files never carry them."""

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.drawquote import service as svc
from app.drawquote.models import DrawQuote, DrawQuoteExclusion, DrawQuotePick
from app.execution.common import record
from app.masters.models import Product, System
from app.sites import service as site_service
from app.spec import suggest
from app.takeoff.models import CadArea, CadFile

router = APIRouter(prefix="/api/drawquote", tags=["quotation from drawing"])
Make = Annotated[str, Depends(require_permission("drawquote.make"))]
EXACT = {Decimal: str}


def _j(x: Any) -> Any:
    return jsonable_encoder(x, custom_encoder=EXACT)


def _cost(principal) -> bool:
    return (
        principal.permissions.get("tender.margin") is not None
        or principal.permissions.get("consumption.cost") is not None
    )


def _site(db, site_id: int, principal):
    scope = principal.permissions.get("site.view")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to sites")
    return site_service.get_visible(db, site_id, scope, principal)


def _run(db, rid: int, principal) -> DrawQuote:
    run = db.get(DrawQuote, rid)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    _site(db, run.site_id, principal)
    return run


def _422(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


# --- the drawing ---------------------------------------------------------------------------------


@router.get("/sites/{site_id}")
def site_drawings(site_id: int, db: DbSession, principal: CurrentPrincipal, _: Make) -> dict:
    """The site's read drawing revisions (newest first) and its runs."""
    from app.sites.models import Drawing, DrawingRevision  # noqa: PLC0415

    site = _site(db, site_id, principal)
    files = []
    for f in db.scalars(
        select(CadFile)
        .where(CadFile.site_id == site_id, CadFile.status == "ready")
        .order_by(CadFile.id.desc())
    ):
        rev = db.get(DrawingRevision, f.revision_id)
        d = db.get(Drawing, f.drawing_id)
        mapped = len(svc.mapped_areas(db, f))
        total = db.scalar(
            select(func.count()).select_from(CadArea).where(CadArea.cad_file_id == f.id)
        )
        files.append(
            {
                "cad_file_id": f.id,
                "drawing": d.title if d else None,
                "rev_no": rev.rev_no if rev else None,
                "areas": total,
                "mapped": mapped,
            }
        )
    runs = [{"id": r.id, "cad_file_id": r.cad_file_id, "status": r.status, "quotation_id": r.quotation_id, "created_at": r.created_at}
            for r in db.scalars(select(DrawQuote).where(DrawQuote.site_id == site_id).order_by(DrawQuote.id.desc()))]  # fmt: skip
    return _j(
        {
            "site": {
                "id": site.id,
                "name": site.name,
                "client_id": getattr(site, "client_id", None),
            },
            "files": files,
            "runs": runs,
        }
    )


@router.get("/files/{fid}/check")
def check(fid: int, db: DbSession, principal: CurrentPrincipal, _: Make) -> dict:
    f = db.get(CadFile, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not read")
    _site(db, f.site_id, principal)
    return _j(svc.check(db, f))


class StartIn(BaseModel):
    cad_file_id: int
    client_id: int | None = None
    unit: str = Field(default="sqm", pattern="^(sqm|sqft)$")


@router.post("/sites/{site_id}/runs", status_code=status.HTTP_201_CREATED)
def start(
    site_id: int,
    body: StartIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Make,
) -> dict:
    site = _site(db, site_id, principal)
    f = db.get(CadFile, body.cad_file_id)
    if f is None or f.site_id != site.id or f.status != "ready":
        raise _422("Pick a drawing revision of this site that has been read")
    run = svc.start(
        db,
        site.id,
        f,
        body.client_id or getattr(site, "client_id", None),
        body.unit,
        principal.user.id,
    )
    record(
        db, request, principal, "drawquote.start", "draw_quote", run.id, after={"cad_file_id": f.id}
    )
    db.commit()
    return {"id": run.id}


def _run_out(db, run: DrawQuote, principal) -> dict:
    cost = _cost(principal)
    items = []
    for item in run.items:
        picked_systems = {p.system_id for p in item.picks}
        system = (
            db.get(System, item.picks[0].system_id)
            if item.picks and item.picks[0].system_id
            else None
        )
        rows = svc.item_rows(db, run, item, system)
        chips = svc.chips_for(db, item, rows)
        ranked = suggest.suggest(db, chips, with_cost=cost)
        for o in ranked["options"]:
            o["picked"] = any(
                p.system_id == o["system_id"] and p.option_id == o["option_id"] for p in item.picks
            )
        items.append({
            "id": item.id, "name": item.name, "area_type_id": item.area_type_id, "spec_text": item.spec_text, "excluded_reason": item.excluded_reason,
            "total_sqm": sum((r.total_sqm for r in rows), Decimal(0)), "areas": [
                {"id": r.area.id, "key": r.area.key, "name": r.area.name, "floor": r.floor, "floor_sqm": r.qty.floor_sqm, "cutout_sqm": r.qty.cutout_sqm,
                 "periphery_m": r.qty.periphery_m, "upturn_m": r.qty.upturn_m, "upturn_from": r.upturn_from, "sunk_m": r.qty.sunk_m, "wall_sqm": r.qty.wall_sqm,
                 "total_sqm": r.total_sqm, "formula": r.formula(), "outline": r.area.outline, "holes": r.area.holes} for r in rows],
            "chips": chips, "options": ranked["options"], "gaps": ranked["gaps"],
            "picks": [{"id": p.id, "system_id": p.system_id, "option_id": p.option_id, "product_id": p.product_id, "consumption": p.consumption,
                       "label": svc.pick_label(db, p)[0], "quotation_line_id": p.quotation_line_id} for p in item.picks],
            "default_picked": bool(picked_systems),
        })  # fmt: skip
    open_areas = [
        {"id": a.id, "name": a.name, "plan": a.plan, "status": a.status}
        for a in svc.open_areas(db, run)
    ]
    excluded = [{"id": e.id, "cad_area_id": e.cad_area_id, "name": db.get(CadArea, e.cad_area_id).name, "reason": e.reason}
                for e in db.scalars(select(DrawQuoteExclusion).where(DrawQuoteExclusion.run_id == run.id))]  # fmt: skip
    out = {"id": run.id, "site_id": run.site_id, "cad_file_id": run.cad_file_id, "client_id": run.client_id, "unit": run.unit, "status": run.status,
           "quotation_id": run.quotation_id, "previous_id": run.previous_id, "changes": run.changes, "items": items, "open_areas": open_areas,
           "excluded": excluded, "blockers": svc.blockers(db, run), "can_cost": cost}  # fmt: skip
    if run.status == "made":
        g = svc.grid(db, run)
        if not cost:  # cost, price and margin are for those who see costs
            for r in g:
                for k in ("rate_sqm", "cost_sqm", "labour", "margin"):
                    r.pop(k, None)
                for p in r["products"]:
                    p.pop("price", None)
                    p.pop("freight", None)
        out["grid"] = g
    return out


@router.get("/runs/{rid}")
def get_run(rid: int, db: DbSession, principal: CurrentPrincipal, _: Make) -> dict:
    return _j(_run_out(db, _run(db, rid, principal), principal))


class PickIn(BaseModel):
    system_id: int | None = None
    option_id: int | None = None
    product_id: int | None = None
    consumption: Decimal | None = Field(default=None, ge=0)


class ItemIn(BaseModel):
    picks: list[PickIn] | None = None
    spec_text: str | None = Field(default=None, max_length=4000)
    excluded_reason: str | None = Field(default=None, max_length=500)


def _picking(run: DrawQuote) -> None:
    if run.status != "picking":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The quotation is made: change it in the review grid, or start a run on a new drawing revision",
        )


@router.put("/runs/{rid}/items/{iid}")
def set_item(
    rid: int,
    iid: int,
    body: ItemIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Make,
) -> dict:
    """The options ticked for an area type (one or more; a product added by search with its
    consumption), the client's spec line for it, or leave the type out with a reason."""
    run = _run(db, rid, principal)
    _picking(run)
    item = next((i for i in run.items if i.id == iid), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area type not found")
    data = body.model_dump(exclude_unset=True)
    if "excluded_reason" in data:
        reason = " ".join((body.excluded_reason or "").split())
        if body.excluded_reason is not None and len(reason) < 3:
            raise _422("Say why the area type is left out")
        item.excluded_reason = reason or None
    if "spec_text" in data:
        item.spec_text = (body.spec_text or "").strip() or None
    if body.picks is not None:
        item.picks.clear()
        db.flush()
        for n, p in enumerate(body.picks):
            if p.system_id:
                s = db.get(System, p.system_id)
                if s is None or (p.option_id and p.option_id not in {o.id for o in s.options}):
                    raise _422("Unknown work item or brand option")
            elif not p.product_id or db.get(Product, p.product_id) is None:
                raise _422("Pick a work item's brand option or a product")
            item.picks.append(DrawQuotePick(system_id=p.system_id, option_id=p.option_id if p.system_id else None, product_id=None if p.system_id else p.product_id,
                                            consumption=None if p.system_id else p.consumption, sort_order=n))  # fmt: skip
    record(db, request, principal, "drawquote.item", "draw_quote_item", item.id, after=_j(data))
    db.commit()
    return _j(_run_out(db, run, principal))


class ExcludeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)  # blank: back in


@router.put("/runs/{rid}/areas/{aid}/exclude")
def exclude(
    rid: int,
    aid: int,
    body: ExcludeIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Make,
) -> dict:
    """Leave an area of the drawing out of the quotation, with why (or take it back in)."""
    run = _run(db, rid, principal)
    _picking(run)
    a = db.get(CadArea, aid)
    if a is None or a.cad_file_id != run.cad_file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area not found on this drawing")
    e = db.scalar(
        select(DrawQuoteExclusion).where(
            DrawQuoteExclusion.run_id == run.id, DrawQuoteExclusion.cad_area_id == aid
        )
    )
    reason = " ".join((body.reason or "").split())
    if body.reason is None:
        if e is not None:
            db.delete(e)
    else:
        if len(reason) < 3:
            raise _422("Say why the area is left out")
        if e is None:
            e = DrawQuoteExclusion(
                run_id=run.id, cad_area_id=aid, reason=reason, by=principal.user.id
            )
            db.add(e)
        e.reason = reason
    record(
        db,
        request,
        principal,
        "drawquote.exclude",
        "cad_area",
        aid,
        after={"reason": reason or None},
    )
    db.commit()
    return _j(_run_out(db, run, principal))


@router.post("/runs/{rid}/make")
def make(rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: Make) -> dict:
    """The draft quotation and its rate working (nothing is sent)."""
    run = _run(db, rid, principal)
    try:
        made = svc.make(db, run, principal)
    except svc.Blocked as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "Not ready to make the quotation", "reasons": exc.reasons},
        ) from None
    record(
        db,
        request,
        principal,
        "drawquote.make",
        "quotation",
        made.quotation.id,
        after={"run": run.id, "revision": made.quotation.revision, "changes": len(made.changes)},
    )
    db.commit()
    return _j(
        _run_out(db, run, principal)
        | {
            "quotation": {
                "id": made.quotation.id,
                "code": made.quotation.code,
                "revision": made.quotation.revision,
            }
        }
    )


class CellIn(BaseModel):
    kind: str = Field(pattern="^(qty|consumption|price|freight|wastage|labour|margin)$")
    ref: int
    value: Decimal | None = None  # blank: back to the calculated figure


@router.put("/runs/{rid}/cells")
def set_cell(
    rid: int, body: CellIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Make
) -> dict:
    """A cell of the review grid (before or after the quotation is sent to the client, the
    quotation's own rules apply: a sent revision keeps its prices)."""
    run = _run(db, rid, principal)
    if run.status != "made":
        raise HTTPException(status.HTTP_409_CONFLICT, "Make the quotation first")
    if body.kind in ("price", "freight", "labour", "margin") and not _cost(principal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Prices, labour and margin are for those who see costs"
        )
    from app.quotations import service as qsvc  # noqa: PLC0415
    from app.quotations.models import Quotation  # noqa: PLC0415

    qsvc.check_price_edit(db.get(Quotation, run.quotation_id))
    try:
        svc.set_cell(db, run, body.kind, body.ref, body.value, principal.user.id)
    except ValueError as exc:
        db.rollback()
        raise _422(str(exc)) from None
    record(
        db, request, principal, "drawquote.cell", "draw_quote", run.id, after=_j(body.model_dump())
    )
    db.commit()
    return _j(_run_out(db, run, principal))


@router.get("/lines/{line_id}/areas")
def line_areas(line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The areas behind a quotation line (to light them in 2D and 3D), for whoever sees the
    quotation."""
    from app.quotations import service as qsvc  # noqa: PLC0415
    from app.quotations.models import QuotationItem, QuotationLine  # noqa: PLC0415

    ln = db.get(QuotationLine, line_id)
    if ln is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    scope = principal.permissions.get("quotation.view")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to quotations")
    qsvc.get_visible(db, db.get(QuotationItem, ln.item_id).quotation_id, scope, principal)
    rows = svc.line_areas(db, line_id)
    areas = []
    for r in rows:
        a = db.get(CadArea, r.cad_area_id) if r.cad_area_id else None
        areas.append({"key": r.area_key, "name": r.area_name, "floor": r.floor, "total_sqm": r.total_sqm, "formula": r.formula, "cad_area_id": r.cad_area_id,
                      "outline": a.outline if a else None, "holes": a.holes if a else [], "node_id": a.node_id if a else None})  # fmt: skip
    return _j(
        {"line_id": line_id, "cad_file_id": rows[0].cad_file_id if rows else None, "areas": areas}
    )
