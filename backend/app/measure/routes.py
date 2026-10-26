# ruff: noqa: E501  (output shapes read better unwrapped)
"""Measuring from the drawing, the measurement sheet and the RA bill made from it.

billing.view sees a site's areas, sheets and bills (by site, as billing does); billing.edit
measures, answers the questions, sends sheets and makes the bills."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.db import DbSession
from app.execution.common import pdf_response, record
from app.finance import service as svc
from app.finance.models import RaBill
from app.measure import bill as mb
from app.measure import excel, geom, importer, variation
from app.measure import pdf as mpdf
from app.measure import service as ms
from app.measure.models import (
    PARTS,
    MeasureArea,
    MeasureBilled,
    MeasureEdge,
    MeasureItem,
    MeasureLine,
    MeasureSheet,
    VariationRequest,
)
from app.sites.models import Drawing, DrawingRevision, Site
from app.takeoff.models import CadFile
from app.tenders.export import company

router = APIRouter(prefix="/api/measure", tags=["measure"])
View = Annotated[str, Depends(require_permission("billing.view"))]


def _site(db, site_id: int, principal: Principal, scope: str) -> Site:
    site = db.get(Site, site_id)
    if site is None or not svc.site_ok(db, scope, principal, site.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


def _edit(db, principal: Principal, site_id: int) -> None:
    if not svc.site_ok(db, principal.permissions.get("billing.edit"), principal, site_id):
        raise svc.forbidden("Missing permission: billing.edit")


def _said(fn, *args, **kw):
    """The service's questions and refusals as 422, clashes as 409."""
    try:
        return fn(*args, **kw)
    except (ms.Question, mb.Refused, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except mb.Clash as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _s(v) -> str | None:
    return None if v is None else f"{Decimal(v):f}"


def _area_out(a: MeasureArea, billed: set[int]) -> dict:
    return {"id": a.id, "code": a.code, "name": a.name, "kind": a.kind, "outline": a.outline, "picked": a.picked, "handle": a.handle, "layer": a.layer,
            "cad_file_id": a.cad_file_id, "area_sqm": _s(a.area_sqm), "periphery_m": _s(a.periphery_m), "trim_with": a.trim_with,
            "net_area_sqm": _s(a.net_area_sqm), "net_periphery_m": _s(a.net_periphery_m), "height_mm": _s(a.height_mm), "height_source": a.height_source,
            "height2_mm": _s(a.height2_mm), "height2_source": a.height2_source, "wall_top_mm": _s(a.wall_top_mm), "rise_mm": _s(a.rise_mm), "run_mm": _s(a.run_mm),
            "slope_source": a.slope_source, "slope_mm": _s(a.slope_mm), "closed_gap_mm": _s(a.closed_gap_mm), "drawn_length_m": _s(a.drawn_length_m),
            "counts": a.counts, "billed": a.id in billed}  # fmt: skip


def _edge_out(e: MeasureEdge, codes: dict[int, str]) -> dict:
    return {"id": e.id, "area_a_id": e.area_a_id, "area_b_id": e.area_b_id, "a": codes.get(e.area_a_id), "b": codes.get(e.area_b_id), "length_m": _s(e.length_m),
            "line": e.line, "answer": e.answer, "weir_mm": _s(e.weir_mm), "manual": e.manual, "source": e.source}  # fmt: skip


@router.get("/sites/{site_id}")
def state(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    areas = ms.areas_of(db, site.id)
    codes = {a.id: a.code for a in areas}
    billed = set(db.scalars(select(MeasureBilled.area_id).join(MeasureArea, MeasureArea.id == MeasureBilled.area_id).where(MeasureArea.site_id == site.id)))
    items = {m.wo_line_id: m for m in db.scalars(select(MeasureItem).where(MeasureItem.site_id == site.id))}
    wo = ms.work_order_lines(db, site.id)
    files = db.execute(
        select(CadFile, Drawing.title, DrawingRevision.rev_no).join(Drawing, Drawing.id == CadFile.drawing_id).join(DrawingRevision, DrawingRevision.id == CadFile.revision_id)
        .where(CadFile.site_id == site.id, CadFile.status == "ready").order_by(CadFile.id.desc())
    )  # fmt: skip
    sheets = list(db.scalars(select(MeasureSheet).where(MeasureSheet.site_id == site.id).order_by(MeasureSheet.seq)))
    for s in sheets:
        mb.status_of(db, s)
    db.commit()
    return {
        "site": {"id": site.id, "code": site.code, "name": site.name},
        "drawings": [{"id": f.id, "title": t, "rev": r, "unit_m": f.unit_m} for f, t, r in files],
        "areas": [_area_out(a, billed) for a in areas],
        "edges": [_edge_out(e, codes) for e in ms.edges_of(db, site.id)],
        "items": [{"wo_line_id": w.id, "item_no": w.item_no, "description": w.description, "unit": w.unit, "qty": _s(w.qty), "rate": _s(w.rate), "per_layer": w.per_layer,
                   "wo_layers": w.layers, "sac": w.sac, "parts": items[w.id].parts if w.id in items else [], "count_of": items[w.id].count_of if w.id in items else None,
                   "layers": items[w.id].layers if w.id in items else w.layers, "layers_answer": items[w.id].layers_answer if w.id in items else None,
                   "areas": items[w.id].areas if w.id in items else None, "skip": items[w.id].skip if w.id in items else {},
                   "manual": items[w.id].manual if w.id in items else {}, "measured": w.id in items} for w in wo],  # fmt: skip
        "sheets": [{"id": s.id, "code": s.code, "seq": s.seq, "title": s.title, "measured_on": s.measured_on, "status": s.status, "imported_from": s.imported_from, "ra_bill_id": s.ra_bill_id} for s in sheets],
        "parts": list(PARTS),
        "sqft_per_sqm": str(geom.SQFT_PER_SQM),
    }


@router.get("/sites/{site_id}/drawing/{cad_file_id}")
def drawing(site_id: int, cad_file_id: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    f = db.get(CadFile, cad_file_id)
    if f is None or f.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    d = _said(ms.drawing, f)
    return {"id": f.id, "unit_m": f.unit_m, "outlines": d["outlines"], "texts": ms.texts_m(f)}


def _file(db, site: Site, cad_file_id: int) -> CadFile:
    f = db.get(CadFile, cad_file_id)
    if f is None or f.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    return f


@router.get("/sites/{site_id}/drawing/{cad_file_id}/at")
def outlines_at(site_id: int, cad_file_id: int, x: float, y: float, db: DbSession, principal: CurrentPrincipal, scope: View) -> list[dict]:
    """Every outline around a click, smallest first, to choose the one to measure."""
    site = _site(db, site_id, principal, scope)
    f = _file(db, site, cad_file_id)
    taken = {a.handle for a in ms.areas_of(db, site.id) if a.cad_file_id == f.id and a.handle}
    return [c | {"area_sqm": f"{c['area_sqm']:.6f}", "periphery_m": f"{c['periphery_m']:.6f}"} for c in _said(ms.candidates, f, x, y, taken)]


@router.get("/sites/{site_id}/drawing/{cad_file_id}/near")
def lines_near(site_id: int, cad_file_id: int, x: float, y: float, db: DbSession, principal: CurrentPrincipal, scope: View, within_m: float = 0.5) -> list[dict]:
    """The lines and arcs near a click (a slope line on a section, a wall drawn on its own), nearest
    first, with their true length."""
    from shapely.geometry import LineString, Point  # noqa: PLC0415

    site = _site(db, site_id, principal, scope)
    f = _file(db, site, cad_file_id)
    pt = Point(x, y)
    out = []
    for ln in _said(ms.drawing, f)["lines"]:
        pts = ln["points"]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if not (min(xs) - within_m <= x <= max(xs) + within_m and min(ys) - within_m <= y <= max(ys) + within_m):
            continue
        path = geom.flatten_open(pts)
        dist = LineString(path).distance(pt) if len(path) > 1 else pt.distance(Point(path[0]))
        if dist <= within_m:
            out.append({"handle": ln["handle"], "layer": ln["layer"], "length_m": f"{ln['length_m']:.6f}", "distance_m": dist, "path": [round(v, 6) for p in path[:: max(1, len(path) // 96)] for v in p]})
    return sorted(out, key=lambda r: r["distance_m"])[:8]


class AreaIn(BaseModel):
    cad_file_id: int | None = None
    x: float | None = None  # a click inside an outline (metres)
    y: float | None = None
    handle: str | None = Field(default=None, max_length=20)  # or the outline chosen among those around the click
    outline: list[list[float]] | None = None  # or traced: [[x, y, bulge], ...]
    code: str | None = Field(default=None, max_length=10)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["area", "slope"] = "area"


@router.post("/sites/{site_id}/areas", status_code=status.HTTP_201_CREATED)
def add_area(site_id: int, body: AreaIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    f = db.get(CadFile, body.cad_file_id) if body.cad_file_id else None
    if f is not None and f.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    if body.outline:
        a = _said(ms.make_area, db, site.id, body.outline, code=body.code, name=body.name, kind=body.kind, cad_file=f, picked=False, user_id=principal.user.id)
    else:
        if f is None or (body.handle is None and (body.x is None or body.y is None)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Click inside an outline on a drawing, or trace one")
        taken = {a.handle for a in ms.areas_of(db, site.id) if a.cad_file_id == f.id and a.handle}
        if body.handle:
            if body.handle in taken:
                raise HTTPException(status.HTTP_409_CONFLICT, "That outline is measured already")
            o = _said(ms.outline_of, f, body.handle)
        else:
            around = _said(ms.candidates, f, body.x, body.y, taken)
            if not around:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No closed outline around that point (not measured yet): trace it instead")
            o = _said(ms.outline_of, f, around[0]["handle"])  # the smallest around the click
        a = _said(ms.make_area, db, site.id, o["outline"], code=body.code, name=body.name, kind=body.kind, cad_file=f, handle=o["handle"], layer=o["layer"],
                  user_id=principal.user.id, gap_m=o.get("gap_m"), drawn_m=o.get("drawn_m"))  # fmt: skip
    record(db, request, principal, "measure.area", "measure_area", a.id, after={"code": a.code, "area_sqm": str(a.area_sqm), "periphery_m": str(a.periphery_m)})
    db.commit()
    return _area_out(a, set())


class AreaPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    kind: Literal["area", "slope"] | None = None
    trim_with: list[int] | None = None
    wall_top_mm: Decimal | None = Field(default=None, ge=0, le=2000)


def _area(db, area_id: int, principal, scope) -> MeasureArea:
    a = db.get(MeasureArea, area_id)
    if a is None or not svc.site_ok(db, scope, principal, a.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area not found")
    return a


def _not_billed(db, a: MeasureArea) -> None:
    if db.scalar(select(MeasureBilled.id).where(MeasureBilled.area_id == a.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Area {a.code} is billed: its sizes are locked")


@router.patch("/areas/{area_id}")
def patch_area(area_id: int, body: AreaPatch, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    a = _area(db, area_id, principal, scope)
    _edit(db, principal, a.site_id)
    data = body.model_dump(exclude_unset=True)
    if set(data) - {"name"}:
        _not_billed(db, a)
    for k, v in data.items():
        setattr(a, k, v)
    ms.refresh(db, a.site_id)
    record(db, request, principal, "measure.area.edit", "measure_area", a.id, after=body.model_dump(mode="json", exclude_unset=True))
    db.commit()
    return _area_out(a, set())


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_area(area_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    a = _area(db, area_id, principal, scope)
    _edit(db, principal, a.site_id)
    _not_billed(db, a)
    site_id = a.site_id
    for o in ms.areas_of(db, site_id):
        if a.id in (o.trim_with or []):
            o.trim_with = [i for i in o.trim_with if i != a.id]
    db.delete(a)
    db.flush()
    ms.refresh(db, site_id)
    record(db, request, principal, "measure.area.delete", "measure_area", area_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class HeightIn(BaseModel):
    section: str = Field(min_length=1, max_length=100)  # "Section Y-Y"
    top: str | None = Field(default=None, max_length=60)  # the level texts as picked: "+1800"
    bottom: str | None = Field(default=None, max_length=60)
    sum_of: list[str] | None = Field(default=None, max_length=6)  # or numbers picked and added: ["750", "150"]
    cad_file_id: int | None = None  # or a line picked on the drawing (a slope's length as a wall's height)
    line_handle: str | None = Field(default=None, max_length=20)
    which: Literal[1, 2] = 1  # 2: the deep end of a floor that slopes


def _height(db, a: MeasureArea, body: HeightIn) -> tuple[Decimal, str]:
    if body.line_handle:
        site = db.get(Site, a.site_id)
        ln = _said(ms.line_of, _file(db, site, body.cad_file_id or a.cad_file_id or 0), body.line_handle)
        h = geom.d(ln["length_m"] * 1000)
        return h, f"{body.section}: the line on layer {ln['layer']}, {h.quantize(Decimal('0.01'))} mm long (an arc measured as an arc)"
    if body.sum_of:
        return _said(geom.height_sum, body.section, body.sum_of)
    if not body.top or not body.bottom:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick two levels, numbers to add, or a line")
    return _said(geom.height_from, body.section, body.top, body.bottom)


@router.post("/areas/{area_id}/height")
def set_height(area_id: int, body: HeightIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    a = _area(db, area_id, principal, scope)
    _edit(db, principal, a.site_id)
    _not_billed(db, a)
    h, src = _height(db, a, body)
    if body.which == 1:
        a.height_mm, a.height_source = h, src
    else:
        a.height2_mm, a.height2_source = h, src
    record(db, request, principal, "measure.height", "measure_area", a.id, after={"height_mm": str(h), "source": src, "which": body.which})
    db.commit()
    return _area_out(a, set())


class SlopeIn(BaseModel):
    section: str = Field(min_length=1, max_length=100)
    top: str | None = Field(default=None, max_length=60)
    bottom: str | None = Field(default=None, max_length=60)
    run_mm: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    run_source: str | None = Field(default=None, max_length=100)
    cad_file_id: int | None = None  # or the slope's line picked on the section
    line_handle: str | None = Field(default=None, max_length=20)


@router.post("/areas/{area_id}/slope")
def set_slope(area_id: int, body: SlopeIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    a = _area(db, area_id, principal, scope)
    _edit(db, principal, a.site_id)
    _not_billed(db, a)
    if body.line_handle:
        site = db.get(Site, a.site_id)
        ln = _said(ms.line_of, _file(db, site, body.cad_file_id or a.cad_file_id or 0), body.line_handle)
        if ln["run_m"] <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That line has no horizontal run: pick the slope's line")
        a.kind, a.slope_mm, a.run_mm, a.rise_mm = "slope", geom.d(ln["length_m"] * 1000), geom.d(ln["run_m"] * 1000), geom.d(ln["rise_m"] * 1000)
        a.slope_source = (f"{body.section}: the slope line on layer {ln['layer']}, {Decimal(a.slope_mm).quantize(Decimal('0.01'))} mm long over a "
                          f"{Decimal(a.run_mm).quantize(Decimal('0.01'))} mm run (rise {Decimal(a.rise_mm).quantize(Decimal('0.01'))} mm)")  # fmt: skip
    else:
        if not body.top or not body.bottom or body.run_mm is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick the slope's line, or two levels and its run")
        rise, src = _said(geom.height_from, body.section, body.top, body.bottom)
        a.kind, a.rise_mm, a.run_mm, a.slope_mm = "slope", rise, body.run_mm, None
        a.slope_source = f"{src.replace(' = ', ', rise ')}; run {body.run_mm.normalize():f} mm{f' ({body.run_source})' if body.run_source else ''}"
    record(db, request, principal, "measure.slope", "measure_area", a.id, after={"rise_mm": str(a.rise_mm), "run_mm": str(a.run_mm), "slope_mm": _s(a.slope_mm)})
    db.commit()
    return _area_out(a, set())


class DrawnEdgeIn(BaseModel):
    area_a_id: int
    area_b_id: int
    cad_file_id: int
    line_handle: str = Field(min_length=1, max_length=20)


@router.post("/sites/{site_id}/edges", status_code=status.HTTP_201_CREATED)
def drawn_edge(site_id: int, body: DrawnEdgeIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    """The wall between two areas drawn apart (each outline on its own), taken from the line drawn
    for it: its true length, asked once like any shared edge."""
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    ids = {body.area_a_id, body.area_b_id}
    found = {a.id: a for a in ms.areas_of(db, site.id) if a.id in ids}
    if len(found) != 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick two areas of this site")
    ln = _said(ms.line_of, _file(db, site, body.cad_file_id), body.line_handle)
    a_id, b_id = sorted(ids)
    seq = len(list(db.scalars(select(MeasureEdge.id).where(MeasureEdge.area_a_id == a_id, MeasureEdge.area_b_id == b_id))))
    path = geom.flatten_open(ln["points"])
    e = MeasureEdge(site_id=site.id, area_a_id=a_id, area_b_id=b_id, seq=seq + 100, length_m=geom.d(ln["length_m"]), manual=True,
                    line=[round(v, 6) for p in path[:: max(1, len(path) // 96)] for v in p], source=f"the line on layer {ln['layer']} drawn between them")  # fmt: skip
    db.add(e)
    record(db, request, principal, "measure.edge.drawn", "measure_edge", None, after={"areas": [a_id, b_id], "length_m": str(e.length_m)})
    db.commit()
    return _edge_out(e, {a.id: a.code for a in found.values()})


class EdgeIn(BaseModel):
    answer: Literal["both", "open", "weir", "none"]  # none: drawn close, not one wall
    weir_mm: Decimal | None = Field(default=None, ge=0, le=100_000)


@router.post("/edges/{edge_id}/answer")
def answer_edge(edge_id: int, body: EdgeIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    e = db.get(MeasureEdge, edge_id)
    if e is None or not svc.site_ok(db, scope, principal, e.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Edge not found")
    _edit(db, principal, e.site_id)
    if body.answer == "weir" and body.weir_mm is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the weir's height")
    for aid in (e.area_a_id, e.area_b_id):
        _not_billed(db, db.get(MeasureArea, aid))
    e.answer, e.weir_mm = body.answer, body.weir_mm if body.answer == "weir" else None
    e.answered_by, e.answered_at = principal.user.id, svc.now()
    record(db, request, principal, "measure.edge", "measure_edge", e.id, after=body.model_dump(mode="json"))
    db.commit()
    codes = {a.id: a.code for a in ms.areas_of(db, e.site_id)}
    return _edge_out(e, codes)


class ItemIn(BaseModel):
    parts: list[Literal["floor", "walls", "tops", "slope", "count"]] = []
    count_of: str | None = Field(default=None, max_length=200)
    layers: int = Field(default=1, ge=1, le=10)
    layers_answer: Literal["each", "once"] | None = None
    areas: list[int] | None = None
    skip: dict[str, list[Literal["floor", "walls", "tops", "slope", "count"]]] = {}
    manual: dict[str, Decimal] = {}


@router.put("/sites/{site_id}/items/{wo_line_id}")
def set_item(site_id: int, wo_line_id: int, body: ItemIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    if wo_line_id not in {w.id for w in ms.work_order_lines(db, site.id)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not an item of this site's work order")
    if "count" in body.parts and not body.count_of and not body.manual:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Say what to count: a layer or a block")
    m = db.scalar(select(MeasureItem).where(MeasureItem.site_id == site.id, MeasureItem.wo_line_id == wo_line_id)) or MeasureItem(site_id=site.id, wo_line_id=wo_line_id)
    m.parts, m.count_of, m.layers, m.layers_answer, m.areas = list(body.parts), body.count_of, body.layers, body.layers_answer, body.areas
    m.skip, m.manual = {k: list(v) for k, v in body.skip.items()}, {k: str(v) for k, v in body.manual.items()}
    db.add(m)
    record(db, request, principal, "measure.item", "measure_item", wo_line_id, after=body.model_dump(mode="json"))
    db.commit()
    return {"ok": True}


# --- sheets --------------------------------------------------------------------------------------


class SheetIn(BaseModel):
    measured_on: date
    title: str | None = Field(default=None, max_length=200)


class StudyOptions(BaseModel):
    """Another way of measuring, to compare with the app's (never sent or billed)."""

    areas: list[int] | None = None
    sizes: Literal["full", "truncate3"] = "full"
    sqft_per_sqm: Decimal = Field(default=Decimal("10.7639"), gt=10, lt=11)
    convert: Literal["line", "item"] = "line"
    periphery: Literal["closed", "drawn"] = "closed"
    areas_as: dict[str, dict[str, str | float | int | None]] = {}
    edges_as: dict[str, dict[str, str | float | int | None]] = {}
    items_as: dict[str, dict] = {}


class StudyIn(SheetIn):
    options: StudyOptions


def _sheet(db, sheet_id: int, principal, scope) -> MeasureSheet:
    s = db.get(MeasureSheet, sheet_id)
    if s is None or not svc.site_ok(db, scope, principal, s.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sheet not found")
    return s


def _line_out(ln) -> dict:
    g = (lambda k: ln.get(k)) if isinstance(ln, dict) else (lambda k: getattr(ln, k, None))
    return {k: (_s(g(k)) if k in ("no", "length_m", "width_m", "height_m", "qty", "total") else g(k))
            for k in ("id", "kind", "area_id", "edge_id", "wo_line_id", "item_no", "layer", "part", "particulars", "no", "length_m", "width_m", "height_m", "qty", "total", "unit",
                      "formula", "reason", "typed", "billed")}  # fmt: skip


def sheet_out(db, s: MeasureSheet) -> dict:
    mb.status_of(db, s)
    site = db.get(Site, s.site_id)
    from app.measure import slip  # noqa: PLC0415

    questions = []
    live = s.status in ("draft", "study") and not slip.is_slip(s)
    if live:
        built = ms.build(db, s)
        lines, questions = [_line_out(x) for x in built.lines], built.questions
    else:
        lines = [_line_out(x) for x in ms.lines_of(db, s.id)]
    wo = ms.work_order_lines(db, s.site_id)
    if live:
        this: dict[int, Decimal] = {}
        for ln in lines:
            if ln["wo_line_id"] and ln["total"] is not None:
                this[ln["wo_line_id"]] = this.get(ln["wo_line_id"], Decimal(0)) + Decimal(ln["total"])
        cum = ms.cumulative(db, s, wo)
        for r in cum:
            r["this"] = r["drawing"] = this.get(r["wo_line_id"], Decimal(0))
            r["approved"], r["note"] = None, None
            r["upto"] = r["previous"] + r["this"]
    else:
        cum = ms.cumulative(db, s, wo)
    ra = db.get(RaBill, s.ra_bill_id) if s.ra_bill_id else None
    return {"id": s.id, "code": s.code, "seq": s.seq, "title": s.title, "measured_on": s.measured_on, "status": s.status, "site_id": site.id, "site_code": site.code, "site_name": site.name,
            "not_done": s.not_done, "imported_from": s.imported_from, "import_skipped": s.import_skipped, "ra_bill_id": s.ra_bill_id, "ra_code": ra.code if ra else None,
            "lines": lines, "questions": questions, "cumulative": [{k: (_s(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in cum],
            "corrections": mb.corrections(db, s), "sqft_per_sqm": str(ms.Way.of(s).sqft), "way": ms.Way.of(s).label(), "options": s.options,
            "slip": {"name": s.slip_name, "on": s.slip_on, "signed_by": s.signed_by, "signed_on": s.signed_on, "has_file": bool(s.slip_path),
                     "unbilled": slip.unmapped(db, s), "typed": {ln.id: ln.typed for ln in ms.lines_of(db, s.id) if ln.typed},
                     "variations": [_plain(variation.out(v)) for v in variation.for_sheet(db, s.id)]} if slip.is_slip(s) else None}  # fmt: skip


@router.post("/sites/{site_id}/sheets", status_code=status.HTTP_201_CREATED)
def new_sheet(site_id: int, body: SheetIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    if db.scalar(select(MeasureSheet.id).where(MeasureSheet.site_id == site.id, MeasureSheet.status == "draft")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Send or delete the draft sheet first")
    s = ms.new_sheet(db, site, body.measured_on, body.title, principal.user.id)
    record(db, request, principal, "measure.sheet", "measure_sheet", s.id, after={"code": s.code})
    db.commit()
    return sheet_out(db, s)


@router.post("/sites/{site_id}/studies", status_code=status.HTTP_201_CREATED)
def new_study(site_id: int, body: StudyIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    s = ms.new_sheet(db, site, body.measured_on, body.title, principal.user.id)
    s.status, s.options = "study", body.options.model_dump(mode="json")
    record(db, request, principal, "measure.study", "measure_sheet", s.id, after={"code": s.code, "options": s.options})
    db.commit()
    return sheet_out(db, s)


@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = _sheet(db, sheet_id, principal, scope)
    out = sheet_out(db, s)
    db.commit()
    return out


class NotDoneIn(BaseModel):
    area_id: int
    wo_line_id: int
    layer: int = 1
    not_done: bool = True


@router.post("/sheets/{sheet_id}/not-done")
def not_done(sheet_id: int, body: NotDoneIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    if s.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}")
    key = [body.area_id, body.wo_line_id, body.layer]
    rest = [k for k in (s.not_done or []) if list(k) != key]
    s.not_done = rest + ([key] if body.not_done else [])
    record(db, request, principal, "measure.not_done", "measure_sheet", s.id, after=body.model_dump())
    db.commit()
    return sheet_out(db, s)


@router.delete("/sheets/{sheet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sheet(sheet_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    if s.status not in ("draft", "study"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}: it stays")
    db.delete(s)
    record(db, request, principal, "measure.sheet.delete", "measure_sheet", sheet_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sheets/{sheet_id}/send")
def send_sheet(sheet_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    _said(mb.send, db, s, principal.user)
    record(db, request, principal, "measure.sheet.send", "measure_sheet", s.id, after={"status": s.status})
    db.commit()
    return sheet_out(db, s)


def _slopes(db, s: MeasureSheet) -> dict:
    out = {}
    for a in ms.areas_of(db, s.site_id):
        if a.kind == "slope" and a.run_mm and (a.rise_mm or a.slope_mm):
            out[a.id] = (float(a.net_area_sqm), float(Decimal(a.rise_mm or 0) / 1000), float(Decimal(a.run_mm) / 1000),
                         float(Decimal(a.slope_mm) / 1000) if a.slope_mm else None)  # fmt: skip
    return out


@router.get("/sheets/{sheet_id}/xlsx")
def sheet_xlsx(sheet_id: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    s = _sheet(db, sheet_id, principal, scope)
    site = db.get(Site, s.site_id)
    if s.status in ("draft", "study"):
        lines = ms.store(db, s, ms.build(db, s))  # the draft (or study) as it is now (not kept)
    else:
        lines = ms.lines_of(db, s.id)
    cum = ms.cumulative(db, s, ms.work_order_lines(db, s.site_id))
    data = excel.export(s, site, lines, cum, {}, _slopes(db, s), company(db).name, sqft=ms.Way.of(s).sqft)
    db.rollback()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{s.code}.xlsx"'})


@router.get("/sheets/{sheet_id}/pdf")
def sheet_pdf(sheet_id: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    s = _sheet(db, sheet_id, principal, scope)
    out = sheet_out(db, s)
    return pdf_response(mpdf.sheet(db, out), s.code)


# --- bills from a site slip ----------------------------------------------------------------------

SLIP_TYPES = (".jpg", ".jpeg", ".png", ".pdf", ".webp", ".heic")


@router.post("/sites/{site_id}/slips", status_code=status.HTTP_201_CREATED)
async def new_slip(site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View,
                   measured_on: Annotated[date, Form()], signed_by: Annotated[str, Form(min_length=1, max_length=200)], signed_on: Annotated[date, Form()],
                   slip_on: Annotated[date | None, Form()] = None, title: Annotated[str | None, Form(max_length=200)] = None,
                   file: Annotated[UploadFile | None, File()] = None) -> dict:  # fmt: skip
    """A bill from a site slip: its photo or PDF, the date on it, who signed it (their role) and when."""
    from app.config import settings  # noqa: PLC0415
    from app.measure import slip  # noqa: PLC0415

    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    if db.scalar(select(MeasureSheet.id).where(MeasureSheet.site_id == site.id, MeasureSheet.status == "draft")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Send or delete the draft sheet first")
    rel = name = None
    if file is not None and file.filename:
        if not file.filename.lower().endswith(SLIP_TYPES):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The slip as a photo (jpg, png) or a PDF")
        data = await file.read(MAX_XLSX + 1)
        if len(data) > MAX_XLSX:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The slip is over 15 MB")
        s = slip.new(db, site, measured_on=measured_on, title=title, slip_path=None, slip_name=file.filename[:300], slip_on=slip_on, signed_by=signed_by.strip(), signed_on=signed_on, user_id=principal.user.id)
        rel = f"sites/{site.id}/slips/{s.code}{Path(file.filename).suffix.lower()}"
        dst = Path(settings.media_dir) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        s.slip_path, name = rel, file.filename
    else:
        s = slip.new(db, site, measured_on=measured_on, title=title, slip_path=None, slip_name=None, slip_on=slip_on, signed_by=signed_by.strip(), signed_on=signed_on, user_id=principal.user.id)
    record(db, request, principal, "measure.slip", "measure_sheet", s.id, after={"code": s.code, "slip": name, "signed_by": s.signed_by})
    db.commit()
    return sheet_out(db, s)


class SlipLineIn(BaseModel):
    particulars: str = Field(min_length=1, max_length=300)
    no: str | None = Field(default=None, max_length=20)  # as written: 26, -1
    length: str | None = Field(default=None, max_length=30)  # 16'0", 116'9", 13.83
    width: str | None = Field(default=None, max_length=30)
    wo_line_id: int | None = None  # none: not mapped to a work-order item (listed, not billed)
    billed: bool = True
    reason: str | None = Field(default=None, max_length=300)


@router.post("/sheets/{sheet_id}/slip-lines", status_code=status.HTTP_201_CREATED)
def add_slip_line(sheet_id: int, body: SlipLineIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    from app.measure import slip  # noqa: PLC0415

    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    if body.wo_line_id and body.wo_line_id not in {w.id for w in ms.work_order_lines(db, s.site_id)}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not an item of this site's work order")
    ln = _said(slip.add_line, db, s, particulars=body.particulars, no=body.no, length=body.length, width=body.width, wo_line_id=body.wo_line_id, billed=body.billed, reason=body.reason)
    record(db, request, principal, "measure.slip.line", "measure_line", ln.id, after=body.model_dump())
    db.commit()
    return sheet_out(db, s)


@router.delete("/sheets/{sheet_id}/slip-lines/{line_id}")
def delete_slip_line(sheet_id: int, line_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    if s.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}")
    ln = db.get(MeasureLine, line_id)
    if ln is None or ln.sheet_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    db.delete(ln)
    record(db, request, principal, "measure.slip.line.delete", "measure_line", line_id)
    db.commit()
    return sheet_out(db, s)


class VariationIn(BaseModel):
    description: str = Field(min_length=3, max_length=500)
    unit: str = Field(min_length=1, max_length=20)
    rate: Decimal = Field(gt=0)


@router.post("/sheets/{sheet_id}/slip-lines/{line_id}/variation", status_code=status.HTTP_201_CREATED)
def ask_variation(sheet_id: int, line_id: int, body: VariationIn, request: Request, db: DbSession, principal: CurrentPrincipal,
                  _: Annotated[str, Depends(require_permission("variation.request"))], scope: View) -> dict:  # fmt: skip
    """Billing asks for a new item or variation for a slip line no work-order item covers."""
    s = _sheet(db, sheet_id, principal, scope)
    ln = db.get(MeasureLine, line_id)
    if ln is None or ln.sheet_id != s.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    v = _said(variation.propose, db, s, ln, description=body.description, unit=body.unit, rate=body.rate, user_id=principal.user.id)
    record(db, request, principal, "variation.request", "variation_request", v.id, after=_plain(variation.out(v)))
    db.commit()
    return sheet_out(db, s)


@router.get("/variations")
def list_variations(db: DbSession, principal: CurrentPrincipal, scope: View, status_: Annotated[str | None, Query(alias="status")] = None, site_id: int | None = None) -> list[dict]:
    q = select(VariationRequest).order_by(VariationRequest.id.desc())
    if status_:
        q = q.where(VariationRequest.status == status_)
    if site_id is not None:
        q = q.where(VariationRequest.site_id == site_id)
    out = []
    for v in db.scalars(q.limit(200)):
        site = db.get(Site, v.site_id)
        if site is None or not svc.site_ok(db, scope, principal, site.id):
            continue
        sheet = db.get(MeasureSheet, v.sheet_id)
        out.append(_plain(variation.out(v)) | {"site": f"{site.code} {site.name}", "site_id": site.id, "sheet_code": sheet.code if sheet else None})
    return out


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


@router.post("/variations/{vid}/decide")
def decide_variation(vid: int, body: DecisionIn, request: Request, db: DbSession, principal: CurrentPrincipal,
                     _: Annotated[str, Depends(require_permission("variation.approve"))], scope: View) -> dict:  # fmt: skip
    """The director approves the variation (it joins the work order, the line can be billed) or not."""
    v = db.get(VariationRequest, vid)
    if v is None or not svc.site_ok(db, scope, principal, v.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variation not found")
    done = _said(variation.decide, db, v, approve=body.approve, note=body.note, user_id=principal.user.id)
    record(db, request, principal, "variation.approve" if body.approve else "variation.reject", "variation_request", v.id, after=_plain(variation.out(v)) | {"done": done})
    db.commit()
    return _plain(variation.out(v)) | {"done": done}


@router.get("/sheets/{sheet_id}/slip")
def slip_file(sheet_id: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    """The slip as scanned (photo or PDF)."""
    from fastapi.responses import FileResponse  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    s = _sheet(db, sheet_id, principal, scope)
    if not s.slip_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No slip attached")
    p = Path(settings.media_dir) / s.slip_path
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The slip's file is missing")
    return FileResponse(p, filename=s.slip_name or p.name)


# --- the RA bill from the sheet ------------------------------------------------------------------


class BillIn(BaseModel):
    proforma_on: date | None = None
    basis: Literal["wo", "verbal"] = "wo"
    verbal_by: str | None = Field(default=None, max_length=200)
    verbal_on: date | None = None


def _bill(db, rid: int, principal, scope) -> RaBill:
    b = db.get(RaBill, rid)
    if b is None or not svc.site_ok(db, scope, principal, b.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RA bill not found")
    return b


def _bill_out(db, b: RaBill) -> dict:
    p = mb.proforma(db, b)
    p["checklist"] = mb.checklist(db, b)
    return p


@router.post("/sheets/{sheet_id}/bill", status_code=status.HTTP_201_CREATED)
def bill_sheet(sheet_id: int, body: BillIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = _sheet(db, sheet_id, principal, scope)
    _edit(db, principal, s.site_id)
    b, _ = _said(mb.bill_from_sheet, db, s, principal.user, proforma_on=body.proforma_on, basis=body.basis, verbal_by=body.verbal_by, verbal_on=body.verbal_on)
    record(db, request, principal, "ra.create", "ra_bill", b.id, after={"code": b.code, "proforma": b.proforma_no, "gross": str(b.gross), "sheet": s.code})
    db.commit()
    return _bill_out(db, b)


@router.get("/bills/{rid}")
def get_bill(rid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    return _bill_out(db, _bill(db, rid, principal, scope))


@router.get("/bills/{rid}/pdf")
def bill_pdf(rid: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    b = _bill(db, rid, principal, scope)
    if not b.proforma_no:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This bill has no proforma")
    return pdf_response(mpdf.proforma(db, mb.proforma(db, b)), b.proforma_no.replace("/", "-"))


class InvoiceIn(BaseModel):
    invoice_date: date | None = None


@router.post("/bills/{rid}/tax-invoice", status_code=status.HTTP_201_CREATED)
def tax_invoice(rid: int, body: InvoiceIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    b = _bill(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    inv = _said(mb.to_tax_invoice, db, b, principal.user, body.invoice_date)
    record(db, request, principal, "invoice.create", "tax_invoice", inv.id, after={"number": inv.number, "ra": b.code, "proforma": b.proforma_no})
    db.commit()
    return {"id": inv.id, "number": inv.number, "taxable": _s(inv.taxable), "cgst": _s(inv.cgst), "sgst": _s(inv.sgst), "igst": _s(inv.igst),
            "round_off": _s(inv.round_off), "total": _s(inv.total), "lines": len(inv.lines)}  # fmt: skip


# --- the register, revisions, material check -----------------------------------------------------


def _plain(v):
    if isinstance(v, Decimal):
        return _s(v)
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


@router.get("/sites/{site_id}/register")
def site_register(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: View, q: str | None = None) -> dict:
    """The site's RA bills in order (proforma or tax invoice, date, basic, GST, total, received,
    revisions, the old number of a renumbered bill), the old register beside them and what was
    found. q: find a bill by its number, the app's or the old files' ("RA 16")."""
    from app.measure import register  # noqa: PLC0415

    site = _site(db, site_id, principal, scope)
    return _plain(register.site_register(db, site.id, (q or "").strip() or None))


@router.post("/sites/{site_id}/register", status_code=status.HTTP_201_CREATED)
async def import_register(site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View, file: Annotated[UploadFile, File()]) -> dict:
    """The billing team's old register (Excel): its rows matched to the site's bills by basic; the
    bills missing from it listed."""
    from app.measure import register  # noqa: PLC0415
    from app.measure.models import RegisterImport  # noqa: PLC0415

    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    got = await _read(file)
    try:
        rows = register.read_register(got[1])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{got[0]}: not a register that can be read") from exc
    bills = list(db.scalars(select(RaBill).where(RaBill.site_id == site.id).order_by(RaBill.seq)))
    for r in rows:
        hit = next((b for b in bills if abs(Decimal(b.certified_gross if b.certified_gross is not None else b.gross) - Decimal(r["basic"])) <= 1), None)
        r["ra"] = hit.seq if hit else None
    matched = {r["ra"] for r in rows if r["ra"] is not None}
    found = [{"kind": "register", "ra": None, "text": f"Missing from the old register: {', '.join(f'RA {b.seq}' for b in bills if b.seq not in matched)}"}] if any(b.seq not in matched for b in bills) else []
    imp = RegisterImport(site_id=site.id, source=got[0][:300], rows=_plain([{k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()} for r in rows]), files=[], findings=found, created_by=principal.user.id)
    db.add(imp)
    record(db, request, principal, "measure.register", "register_import", None, after={"rows": len(rows)})
    db.commit()
    return _plain(register.site_register(db, site.id))


@router.get("/bills/{rid}/revisions")
def bill_revisions(rid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> list[dict]:
    from app.measure import register  # noqa: PLC0415

    return _plain(register.revisions(db, _bill(db, rid, principal, scope)))


class RevisionIn(BaseModel):
    label: str | None = Field(default=None, max_length=200)


@router.post("/bills/{rid}/revisions", status_code=status.HTTP_201_CREATED)
def new_revision(rid: int, body: RevisionIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> list[dict]:
    """The bill as it is now kept as its next revision (R0, R1 ...)."""
    from app.measure import register  # noqa: PLC0415

    b = _bill(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    r = register.add_revision(db, b, label=body.label, source="the app", made_on=date.today(), user_id=principal.user.id)
    record(db, request, principal, "ra.revision", "ra_bill", b.id, after={"rev": r.rev_no, "basic": str(r.basic)})
    db.commit()
    return _plain(register.revisions(db, b))


@router.post("/bills/{rid}/revisions/{rev_id}/sent")
def revision_sent(rid: int, rev_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View) -> list[dict]:
    """The revision sent to the client (one per bill)."""
    from app.measure import register  # noqa: PLC0415
    from app.measure.models import BillRevision  # noqa: PLC0415

    b = _bill(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    r = db.get(BillRevision, rev_id)
    if r is None or r.ra_bill_id != b.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    register.mark_sent(db, b, r)
    record(db, request, principal, "ra.revision.sent", "ra_bill", b.id, after={"rev": r.rev_no})
    db.commit()
    return _plain(register.revisions(db, b))


@router.get("/bills/{rid}/material")
def bill_material(rid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    """What the bills up to this one need of each product against what the site used."""
    from app.measure import register  # noqa: PLC0415

    return _plain(register.material_check(db, _bill(db, rid, principal, scope)))


# --- old Excel bills -----------------------------------------------------------------------------

MAX_XLSX = 15 * 1024 * 1024


async def _read(f: UploadFile | None) -> tuple[str, bytes] | None:
    if f is None or not f.filename:
        return None
    data = await f.read(MAX_XLSX + 1)
    if len(data) > MAX_XLSX:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} is over 15 MB")
    if not f.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{f.filename}: an Excel workbook (.xlsx) is read")
    return f.filename, data


@router.post("/sites/{site_id}/import", status_code=status.HTTP_201_CREATED)
async def import_old(site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View,
                     measured_on: Annotated[date, Form()], sheet: Annotated[UploadFile | None, File()] = None, proforma: Annotated[UploadFile | None, File()] = None,
                     ra_no: Annotated[int | None, Form(ge=1, le=999)] = None) -> dict:  # fmt: skip
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    out = _said(importer.run, db, site, sheet_file=await _read(sheet), proforma_file=await _read(proforma), measured_on=measured_on, user=principal.user, ra_no=ra_no)
    record(db, request, principal, "measure.import", "measure_sheet", out["sheet_id"], after={"items": len(out["items"]), "skipped": len(out["skipped"])})
    db.commit()
    return {k: v for k, v in out.items()} | {"totals": {k: _s(v) for k, v in out["totals"].items()},
                                             "items": [r | {"qty": _s(r["qty"]), "read": _s(r["read"]), "sqm": _s(r["sqm"])} for r in out["items"]]}  # fmt: skip
