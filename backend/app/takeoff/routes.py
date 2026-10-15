# ruff: noqa: E501  (the area rows read better unwrapped)
"""The AutoCAD takeoff API.

takeoff.view: billing, planning, the site engineer (their own sites), sales and the estimator (to
use AutoCAD areas in a BOQ or quotation). takeoff.edit: billing, planning and the site engineer on
their own sites: read a drawing, map layers, trace, map to the site, accept into the survey.
Accepting into the measurement book also needs measurement.edit (billing). Client logins never
hold these permissions."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import names, record
from app.sites import service as site_service
from app.takeoff import geometry, pipeline, service
from app.takeoff.models import LAYER_ROLES, CadArea, CadFile, CadLayerMap
from app.takeoff.reader import UNITS

router = APIRouter(prefix="/api/takeoff", tags=["autocad takeoff"])
View = Annotated[str, Depends(require_permission("takeoff.view"))]
Edit = Annotated[str, Depends(require_permission("takeoff.edit"))]


def _site(db, site_id: int, scope: str, principal):
    return site_service.get_visible(db, site_id, scope, principal)


def _file(db, fid: int, scope: str, principal) -> CadFile:
    f = db.get(CadFile, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not read")
    _site(db, f.site_id, scope, principal)
    return f


def _area(db, aid: int, scope: str, principal) -> tuple[CadArea, CadFile]:
    a = db.get(CadArea, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area not found")
    return a, _file(db, a.cad_file_id, scope, principal)


def _edit_scope(principal) -> str:
    scope = principal.permissions.get("takeoff.edit")
    if scope is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Taking off areas is for billing, planning and the site engineer",
        )
    return scope


# --- drawings and reading -------------------------------------------------------------------------


def file_out(db, f: CadFile) -> dict:
    from app.sites.models import Drawing, DrawingRevision  # noqa: PLC0415

    rev = db.get(DrawingRevision, f.revision_id)
    d = db.get(Drawing, f.drawing_id)
    roles = {}
    if f.architect:
        m = db.scalar(select(CadLayerMap).where(CadLayerMap.architect == f.architect))
        roles = m.roles if m else {}
    s = f.summary or {}
    return {
        "id": f.id, "revision_id": f.revision_id, "drawing_id": f.drawing_id, "site_id": f.site_id,
        "drawing": d.title if d else None, "rev": f"R{rev.rev_no}" if rev else None, "filename": rev.filename if rev else None,
        "status": f.status, "error": f.error, "version": f.dwg_version, "units_code": f.units_code,
        "unit_name": UNITS.get(f.units_code or 0, ("unitless", None))[0] if f.units_code is not None else None,
        "unit_m": f.unit_m, "units_set_by_hand": f.units_set_by_hand, "architect": f.architect,
        "layers": [{**ly, "role": roles.get(ly["name"])} for ly in s.get("layers", [])],
        "counts": s.get("counts", {}), "texts": s.get("texts"), "dimensions": s.get("dimensions"),
        "inserts": s.get("inserts"), "layouts": s.get("layouts", []), "extents": s.get("extents"),
        "size_labels": s.get("size_labels"), "waterproofing_notes": s.get("waterproofing_notes"),
        "candidates": s.get("candidates"), "loose_notes": s.get("loose_notes", []),
        "warnings": f.warnings, "read_at": f.read_at,
    }  # fmt: skip


@router.get("/sites/{site_id}/drawings")
def site_drawings(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: View
) -> list[dict]:
    """The site's AutoCAD drawings (.dwg, .dxf) and how far each revision has been read."""
    from app.sites.models import Drawing  # noqa: PLC0415

    site = _site(db, site_id, scope, principal)
    out = []
    for d in db.scalars(select(Drawing).where(Drawing.site_id == site.id).order_by(Drawing.id)):
        revs = [r for r in d.revisions if Path(r.filename).suffix.lower() in pipeline.READABLE]
        if not revs:
            continue
        files = {
            f.revision_id: f
            for f in db.scalars(
                select(CadFile).where(CadFile.revision_id.in_([r.id for r in revs]))
            )
        }
        out.append({
            "drawing_id": d.id, "title": d.title,
            "revisions": [{"revision_id": r.id, "rev": f"R{r.rev_no}", "filename": r.filename, "size_bytes": r.size_bytes,
                           "file": file_out(db, files[r.id]) if r.id in files else None} for r in sorted(revs, key=lambda r: -r.rev_no)],
        })  # fmt: skip
    return jsonable_encoder(out)


class ReadIn(BaseModel):
    architect: str | None = Field(None, max_length=200)


@router.post("/revisions/{revision_id}/read", status_code=status.HTTP_202_ACCEPTED)
def read_revision(
    revision_id: int,
    body: ReadIn,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    principal: CurrentPrincipal,
    _: View,
) -> dict:
    """Read the drawing (in the background: a large DWG takes a minute or two)."""
    from app.sites.models import Drawing, DrawingRevision  # noqa: PLC0415

    rev = db.get(DrawingRevision, revision_id)
    if rev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    d = db.get(Drawing, rev.drawing_id)
    _site(db, d.site_id, _edit_scope(principal), principal)
    if Path(rev.filename).suffix.lower() not in pipeline.READABLE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only AutoCAD drawings (.dwg or .dxf) can be read for areas",
        )
    f = db.scalar(select(CadFile).where(CadFile.revision_id == rev.id))
    if f is None:
        # the architect of the drawing's last read revision: their layer mapping is reused
        last = db.scalar(
            select(CadFile.architect)
            .where(CadFile.drawing_id == d.id, CadFile.architect.is_not(None))
            .order_by(CadFile.id.desc())
            .limit(1)
        )
        f = CadFile(
            revision_id=rev.id,
            drawing_id=d.id,
            site_id=d.site_id,
            created_by=principal.user.id,
            architect=body.architect or last,
        )
        db.add(f)
    elif body.architect:
        f.architect = body.architect
    if f.status == "reading":
        raise HTTPException(status.HTTP_409_CONFLICT, "It is being read now")
    f.status, f.error = "queued", None
    db.flush()
    record(
        db, request, principal, "takeoff.read", "cad_file", f.id, after={"revision": revision_id}
    )
    db.commit()
    background.add_task(pipeline.process_id, f.id)
    return jsonable_encoder(file_out(db, f))


@router.get("/files/{fid}")
def get_file(fid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    f = _file(db, fid, scope, principal)
    return jsonable_encoder(
        file_out(db, f) | {"changes": service.changes(db, f) if f.status == "ready" else None}
    )


@router.get("/files/{fid}/geometry")
def get_geometry(fid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    """The viewer's drawing: segments per layer, texts and dimensions (gzip JSON)."""
    f = _file(db, fid, scope, principal)
    if f.status != "ready" or not f.geometry_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "The drawing has not been read yet")
    data = pipeline.media(f.geometry_path).read_bytes()
    return Response(
        data,
        media_type="application/json",
        headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600"},
    )


class UnitsIn(BaseModel):
    units_code: int


@router.put("/files/{fid}/units")
def set_units(
    fid: int, body: UnitsIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """The drawing's unit when it says "unitless" (or says it wrong): never assumed."""
    f = _file(db, fid, _edit_scope(principal), principal)
    if body.units_code not in UNITS or UNITS[body.units_code][1] is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick a real unit (inches, feet, mm, cm, m)"
        )
    f.units_code, f.unit_m, f.units_set_by_hand = body.units_code, UNITS[body.units_code][1], True
    for a in db.scalars(
        select(CadArea).where(CadArea.cad_file_id == f.id, CadArea.outline.is_not(None))
    ):
        service.trace(db, f, a, a.outline)
    record(
        db,
        request,
        principal,
        "takeoff.units",
        "cad_file",
        f.id,
        after={"units": UNITS[body.units_code][0]},
    )
    db.commit()
    return jsonable_encoder(file_out(db, f))


# --- layer mapping per architect ----------------------------------------------------------------


class LayerMapIn(BaseModel):
    architect: str = Field(min_length=2, max_length=200)
    roles: dict[str, str]


@router.get("/layer-maps")
def layer_maps(db: DbSession, _: View) -> list[dict]:
    return [
        {"architect": m.architect, "roles": m.roles}
        for m in db.scalars(select(CadLayerMap).order_by(CadLayerMap.architect))
    ]


@router.put("/files/{fid}/layer-map")
def put_layer_map(
    fid: int, body: LayerMapIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Which layers are walls, rooms, dimensions, text, and which to hide: saved for the
    architect and reused for their next drawings. The areas are found again without the hidden
    layers."""
    f = _file(db, fid, _edit_scope(principal), principal)
    bad = {v for v in body.roles.values() if v not in LAYER_ROLES}
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown layer roles: {', '.join(sorted(bad))}"
        )
    m = db.scalar(select(CadLayerMap).where(CadLayerMap.architect == body.architect.strip()))
    if m is None:
        m = CadLayerMap(architect=body.architect.strip(), created_by=principal.user.id)
        db.add(m)
    m.roles, m.updated_by = {k: v for k, v in body.roles.items() if v}, principal.user.id
    f.architect = m.architect
    db.flush()
    if f.status == "ready":
        service.build_areas(db, f)
    record(
        db,
        request,
        principal,
        "takeoff.layer_map",
        "cad_layer_map",
        m.architect,
        after={"roles": m.roles},
    )
    db.commit()
    return jsonable_encoder(file_out(db, f))


# --- areas ---------------------------------------------------------------------------------------


def area_out(db, a: CadArea, f: CadFile) -> dict:
    from app.masters.models import System  # noqa: PLC0415
    from app.survey.models import AreaType  # noqa: PLC0415

    diff, flagged = service.label_trace_diff(db, a)
    at = db.get(AreaType, a.area_type_id) if a.area_type_id else None
    path = service.node_path(db, a.node_id) if a.node_id else []
    who = names(db, [a.accepted_by])
    return {
        "id": a.id, "key": a.key, "name": a.name, "label_text": a.label_text, "size_text": a.size_text,
        "size_kind": a.size_kind, "label_w_m": a.label_w_m, "label_l_m": a.label_l_m,
        "label_area_sqm": a.label_area_sqm, "x": a.x, "y": a.y, "plan": a.plan, "notes": a.notes,
        "sunk_m": a.sunk_m, "raise_m": a.raise_m, "outline": a.outline, "traced_area_sqm": a.traced_area_sqm,
        "traced_perimeter_m": a.traced_perimeter_m, "side_wall_sqm": a.side_wall_sqm,
        "label_trace_diff_percent": diff, "label_trace_flagged": flagged,
        "area_sqm": service.area_sqm(a), "node_id": a.node_id, "place": " / ".join(n.name for n in path) or None,
        "area_type_id": a.area_type_id, "area_type": at.name if at else None,
        "system_id": a.system_id, "system": db.get(System, a.system_id).name if a.system_id else (db.get(System, at.default_system_id).name if at and at.default_system_id else None),
        "status": a.status, "copied_from_id": a.copied_from_id, "floor_label": a.floor_label,
        "change": a.change, "previous_area_sqm": a.previous_area_sqm,
        "survey_area_id": a.survey_area_id, "measurement_id": a.measurement_id, "side_measurement_id": a.side_measurement_id,
        "accepted_by": who.get(a.accepted_by), "accepted_at": a.accepted_at,
        "survey_check": service.survey_check(db, a),
        "waterproofing": bool(at or a.notes or a.sunk_m),
    }  # fmt: skip


@router.get("/files/{fid}/areas")
def areas(
    fid: int, db: DbSession, principal: CurrentPrincipal, scope: View, show: str = "waterproofing"
) -> dict:
    """The candidate areas with their label sizes, traces, notes and flags. show: waterproofing
    (the areas we treat: an area type, a note or a sunk depth), all."""
    f = _file(db, fid, scope, principal)
    rows = db.scalars(
        select(CadArea)
        .where(CadArea.cad_file_id == f.id)
        .order_by(CadArea.plan, CadArea.y.desc(), CadArea.x)
    ).all()
    out = [area_out(db, a, f) for a in rows]
    if show == "waterproofing":
        out = [a for a in out if a["waterproofing"] or a["status"] != "candidate"]
    return jsonable_encoder(
        {
            "file": file_out(db, f),
            "areas": out,
            "settings": {"label_trace_diff_percent": service.settings(db).label_trace_diff_percent},
        }
    )


@lru_cache(maxsize=8)
def _segments(path: str, mtime: float, layers: frozenset, only: frozenset) -> list[tuple]:
    from app.takeoff.reader import load_geometry  # noqa: PLC0415

    geo = load_geometry(Path(path))
    out = []
    for layer, g in geo["geometry"].items():
        if layer in layers or (only and layer not in only):
            continue
        s = g["s"]
        out.extend((s[i], s[i + 1], s[i + 2], s[i + 3]) for i in range(0, len(s), 4))
    return out


def segments(db, f: CadFile) -> list[tuple]:
    p = pipeline.media(f.geometry_path)
    return _segments(
        str(p),
        p.stat().st_mtime,
        frozenset(service.hidden_layers(db, f)),
        frozenset(service.wall_layers(db, f)),
    )


class SnapIn(BaseModel):
    x: float
    y: float
    radius: float = Field(gt=0)  # drawing units (a few screen pixels at the current zoom)
    previous: list[float] | None = None


@router.post("/files/{fid}/snap")
def snap(fid: int, body: SnapIn, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    """The point a click means: an end point, an intersection, or the foot of the perpendicular
    from the previous corner (walls only, when the architect's walls layers are mapped)."""
    f = _file(db, fid, scope, principal)
    s = geometry.snap(
        (body.x, body.y),
        segments(db, f),
        body.radius,
        tuple(body.previous) if body.previous else None,
    )
    return {"x": s.point[0], "y": s.point[1], "kind": s.kind}


class ProposeIn(BaseModel):
    x: float
    y: float


@router.post("/files/{fid}/propose")
def propose(
    fid: int, body: ProposeIn, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    """For a click inside a room: an outline from the nearest wall lines (to correct, not to
    trust: the walls have gaps at doors)."""
    f = _file(db, fid, scope, principal)
    reach = 30 / f.unit_m if f.unit_m else 1e9  # 30 m
    out = geometry.propose((body.x, body.y), segments(db, f), reach)
    if out is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No wall found in every direction from that point: click the corners instead",
        )
    u = f.unit_m or 1
    return {"outline": [list(p) for p in out], "area_sqm": round(geometry.area(out) * u * u, 3)}


class TraceIn(BaseModel):
    points: list[list[float]] = Field(min_length=3)


@router.post("/areas/{aid}/trace")
def trace(
    aid: int, body: TraceIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    a, f = _area(db, aid, _edit_scope(principal), principal)
    if a.status == "accepted":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{a.name} is accepted; its trace is kept as it was"
        )
    try:
        service.trace(db, f, a, body.points)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    record(
        db,
        request,
        principal,
        "takeoff.trace",
        "cad_area",
        a.id,
        after={"area_sqm": str(a.traced_area_sqm), "corners": len(body.points)},
    )
    db.commit()
    return jsonable_encoder(area_out(db, a, f))


class NewAreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    points: list[list[float]] = Field(min_length=3)
    sunk_mm: Decimal | None = Field(None, ge=0, le=3000)


@router.post("/files/{fid}/areas", status_code=status.HTTP_201_CREATED)
def new_area(
    fid: int, body: NewAreaIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """An area traced where the drawing has no label (Trident: rooms without sizes)."""
    f = _file(db, fid, _edit_scope(principal), principal)
    xs = [p[0] for p in body.points]
    ys = [p[1] for p in body.points]
    a = CadArea(cad_file_id=f.id, key=f"TRACED|{body.name.upper()}|{round(sum(xs) / len(xs))}|{round(sum(ys) / len(ys))}"[:160],
                name=body.name.strip(), x=sum(xs) / len(xs), y=sum(ys) / len(ys),
                sunk_m=(body.sunk_mm / 1000) if body.sunk_mm else None, created_by=principal.user.id)  # fmt: skip
    from app.survey.models import AreaType  # noqa: PLC0415

    guess = service.guess_area_type(a.name)
    a.area_type_id = db.scalar(select(AreaType.id).where(AreaType.name == guess)) if guess else None
    db.add(a)
    db.flush()
    try:
        service.trace(db, f, a, body.points)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    record(
        db,
        request,
        principal,
        "takeoff.area",
        "cad_area",
        a.id,
        after={"name": a.name, "area_sqm": str(a.traced_area_sqm)},
    )
    db.commit()
    return jsonable_encoder(area_out(db, a, f))


class AreaIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    node_id: int | None = None
    area_type_id: int | None = None
    system_id: int | None = None
    sunk_mm: Decimal | None = Field(None, ge=0, le=3000)
    status: str | None = Field(None, pattern="^(candidate|ignored)$")


@router.put("/areas/{aid}")
def update_area(
    aid: int, body: AreaIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Map the area to the site's place and area type (or leave it out)."""
    from app.sites.models import SiteNode  # noqa: PLC0415

    a, f = _area(db, aid, _edit_scope(principal), principal)
    data = body.model_dump(exclude_unset=True)
    if a.status == "accepted" and set(data) - {"name"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{a.name} is accepted into the survey; change it there"
        )
    if data.get("node_id"):
        n = db.get(SiteNode, data["node_id"])
        if n is None or n.site_id != f.site_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That place is not on this site"
            )
    if "sunk_mm" in data:
        a.sunk_m = (data.pop("sunk_mm") or 0) / 1000 or None
        service.side(a)
    for k, v in data.items():
        setattr(a, k, v)
    if a.status in ("candidate", "mapped"):
        a.status = "mapped" if a.node_id else "candidate"
    record(
        db,
        request,
        principal,
        "takeoff.map",
        "cad_area",
        a.id,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return jsonable_encoder(area_out(db, a, f))


class CopyIn(BaseModel):
    area_ids: list[int] = Field(min_length=1)
    source_floor_id: int
    target_floor_ids: list[int] = Field(min_length=1)


@router.post("/files/{fid}/copy-floors", status_code=status.HTTP_201_CREATED)
def copy_floors(
    fid: int, body: CopyIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> list[dict]:
    """ "Same as floor 3 for floors 4 to 12": the areas copied to each floor, onto the places
    with the same names there."""
    f = _file(db, fid, _edit_scope(principal), principal)
    rows = db.scalars(
        select(CadArea).where(CadArea.cad_file_id == f.id, CadArea.id.in_(body.area_ids))
    ).all()
    try:
        made = service.copy_to_floors(
            db, rows, body.source_floor_id, body.target_floor_ids, principal.user.id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    record(
        db,
        request,
        principal,
        "takeoff.copy_floors",
        "cad_file",
        f.id,
        after={"areas": body.area_ids, "floors": body.target_floor_ids, "made": len(made)},
    )
    db.commit()
    return jsonable_encoder([area_out(db, a, f) for a in made])


class AcceptIn(BaseModel):
    survey: bool = True
    measurement_book: bool = False
    contract_line_id: int | None = None


@router.post("/areas/{aid}/accept")
def accept(
    aid: int, body: AcceptIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Into the survey (method cad, with the outline) and, when billing accepts, into the
    measurement book (source autocad)."""
    a, f = _area(db, aid, _edit_scope(principal), principal)
    if body.measurement_book and principal.permissions.get("measurement.edit") is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Billing accepts areas into the measurement book"
        )
    try:
        service.accept(
            db, f, a, principal.user.id, body.survey, body.measurement_book, body.contract_line_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    record(
        db,
        request,
        principal,
        "takeoff.accept",
        "cad_area",
        a.id,
        after=jsonable_encoder(body.model_dump())
        | {"survey_area": a.survey_area_id, "measurement": a.measurement_id},
    )
    db.commit()
    return jsonable_encoder(area_out(db, a, f))


@router.get("/sites/{site_id}/quantities")
def site_quantities(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    """Accepted AutoCAD areas per floor, per system and per area type."""
    site = _site(db, site_id, scope, principal)
    return jsonable_encoder(service.quantities(db, site.id))


class UseIn(BaseModel):
    area_ids: list[int] = Field(min_length=1)
    boq_line_id: int | None = None
    quotation_line_id: int | None = None


@router.post("/use-in-line")
def use_in_line(
    body: UseIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    """AutoCAD areas as the quantity of a tender BOQ line or a quotation line (sales and the
    estimator): the sum of the areas, in the line's unit."""
    from app.masters.rate import SQFT_PER_SQM  # noqa: PLC0415

    rows = []
    for aid in body.area_ids:
        a, _f = _area(db, aid, scope, principal)
        if service.area_sqm(a) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{a.name} has no size yet")
        rows.append(a)
    sqm = sum((Decimal(service.area_sqm(a)) for a in rows), Decimal(0))
    if body.boq_line_id:
        from app.tenders.models import BoqLine, Tender  # noqa: PLC0415
        from app.tenders.pricing import refresh_amount, refresh_tender_total  # noqa: PLC0415
        from app.tenders.service import check_edit  # noqa: PLC0415

        ln = db.get(BoqLine, body.boq_line_id)
        if ln is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "BOQ line not found")
        edit = principal.permissions.get("tender.edit")
        if edit is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tender editing is not for your role")
        tender = db.get(Tender, ln.tender_id)
        check_edit(tender, edit, principal)
        unit = (ln.unit or "").lower()
        ln.qty = (sqm * SQFT_PER_SQM if unit in ("sqft", "sft") else sqm).quantize(Decimal("0.001"))
        refresh_amount(ln)
        refresh_tender_total(db, tender)
        target = {"boq_line_id": ln.id, "qty": ln.qty, "unit": ln.unit}
    elif body.quotation_line_id:
        from app.quotations import service as qsvc  # noqa: PLC0415
        from app.quotations.models import QuotationItem, QuotationLine  # noqa: PLC0415

        ql = db.get(QuotationLine, body.quotation_line_id)
        if ql is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation line not found")
        qscope = principal.permissions.get("quotation.view")
        if qscope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to quotations")
        qsvc.get_visible(db, db.get(QuotationItem, ql.item_id).quotation_id, qscope, principal)
        ql.qty = (sqm * SQFT_PER_SQM if ql.uom == "sqft" else sqm).quantize(Decimal("0.001"))
        target = {"quotation_line_id": ql.id, "qty": ql.qty, "unit": ql.uom}
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a BOQ line or a quotation line"
        )
    record(
        db,
        request,
        principal,
        "takeoff.use_in_line",
        "cad_area",
        ",".join(map(str, body.area_ids)),
        after=jsonable_encoder(target),
    )
    db.commit()
    return jsonable_encoder(target | {"sqm": sqm})


@router.get("/area-types")
def area_types(db: DbSession, _: View) -> list[dict]:
    """The area types to map to (toilet, sunken, terrace, raft ...)."""
    from app.survey.models import AreaType  # noqa: PLC0415

    return [
        {"id": t.id, "name": t.name, "default_system_id": t.default_system_id}
        for t in db.scalars(
            select(AreaType).where(AreaType.is_active).order_by(AreaType.sort_order, AreaType.name)
        )
    ]
