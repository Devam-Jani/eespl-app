# ruff: noqa: E501
"""The building model API: everyone who sees the site sees the model; building.edit (billing,
planning, the office admin, the director on every site, the site engineer on their own) builds
and edits it. Each save is a new version; the 3D view reads it through GET /api/sites/{id}/model."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.building import service
from app.building.models import BuildingModel
from app.db import DbSession
from app.sites import progress
from app.sites import service as sites
from app.sites.models import Drawing, DrawingRevision, Site
from app.takeoff.models import CadFile

router = APIRouter(prefix="/api/sites", tags=["building"])
View = Annotated[str, Depends(require_permission("site.view"))]


def _site(db, site_id: int, view: str, principal) -> Site:
    return sites.get_visible(db, site_id, view, principal)


def _can_edit(site: Site, principal) -> bool:
    scope = principal.permissions.get("building.edit")
    return scope is not None and sites.covers(scope, principal, site)


def _editable(db, site_id: int, view: str, principal) -> Site:
    site = _site(db, site_id, view, principal)
    if not _can_edit(site, principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Building the 3D model needs building.edit on this site")
    return site


def _cad(db, site: Site, cad_file_id: int) -> CadFile:
    f = db.get(CadFile, cad_file_id)
    if f is None or f.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing file not found")
    if f.status != "ready":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The drawing is not read yet")
    return f


def drawing_state(f: CadFile | None) -> str:
    """not read, queued, reading, ready, failed, or missing (read, but its geometry is not on the
    server: read it again)."""
    from app.takeoff import pipeline  # noqa: PLC0415

    if f is None:
        return "not read"
    if f.status == "ready" and not (f.geometry_path and pipeline.media(f.geometry_path).exists()):
        return "missing"
    return f.status


def _out(db, site: Site, principal) -> dict:
    from pathlib import Path  # noqa: PLC0415

    m = service.current(db, site.id)
    revs = db.execute(
        select(DrawingRevision, Drawing.title, CadFile)
        .join(Drawing, Drawing.id == DrawingRevision.drawing_id)
        .outerjoin(CadFile, CadFile.revision_id == DrawingRevision.id)
        .where(Drawing.site_id == site.id)
        .order_by(DrawingRevision.id.desc())
    ).all()
    files = [(f, title, r.rev_no) for r, title, f in revs if f is not None and drawing_state(f) == "ready"]
    cad = db.get(CadFile, m.cad_file_id) if m and m.cad_file_id else None
    can_read = principal.permissions.get("takeoff.edit") is not None and sites.covers(principal.permissions["takeoff.edit"], principal, site)
    readable = [(r, title, f) for r, title, f in revs if Path(r.filename or "").suffix.lower() in (".dwg", ".dxf")]
    model_rev = next(((r, title, f) for r, title, f in revs if cad is not None and f is not None and f.id == cad.id), None)
    state = None
    if model_rev is not None:
        r, title, f = model_rev
        state = {"revision_id": r.id, "cad_file_id": f.id, "title": title, "filename": r.filename, "rev_no": r.rev_no, "state": drawing_state(f),
                 "progress": f.progress, "progress_at": f.progress_at, "error": f.error}  # fmt: skip
    return {
        "site_id": site.id,
        "can_edit": _can_edit(site, principal),
        "model": None if m is None else {"id": m.id, "version": m.version, "cad_file_id": m.cad_file_id, "data": m.data, "note": m.note, "changes": m.changes,
                                          "by": m.created_by_name, "at": m.created_at, "unit_m": cad.unit_m if cad else None,
                                          "floors": service.elevations(m.data or {}), "unmatched_levels": service.unmatched_levels(m.data or {})},  # fmt: skip
        "drawings": [{"cad_file_id": f.id, "title": title, "rev_no": rev, "unit_m": f.unit_m, "newer": bool(m and m.cad_file_id and f.id > m.cad_file_id)} for f, title, rev in files],
        # every AutoCAD revision of the site with how far it is read (the page shows it, and a
        # "Read the drawing" button to those who may read drawings)
        "revisions": [{"revision_id": r.id, "title": title, "rev_no": r.rev_no, "filename": r.filename, "cad_file_id": f.id if f else None, "state": drawing_state(f),
                       "progress": f.progress if f else None, "progress_at": f.progress_at if f else None, "error": f.error if f else None} for r, title, f in readable],  # fmt: skip
        "model_drawing": state,
        "can_read": can_read,
        "plans": service.plans(cad) if cad else [],
        "site_floors": [{"node_id": f.id, "name": f.name, "level": service.level_of(f)} for f in service.site_floors(db, site.id)],
    }


@router.get("/{site_id}/building")
def get_building(site_id: int, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    return _out(db, _site(db, site_id, view, principal), principal)


class FromDrawingIn(BaseModel):
    cad_file_id: int


@router.post("/{site_id}/building/from-drawing", status_code=status.HTTP_201_CREATED)
def from_drawing(site_id: int, body: FromDrawingIn, request: Request, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    """The model from a drawing: the first time a draft (the plans as floor types, the floors their
    titles name, the section's levels); on a newer revision of the drawing, the model moved onto it
    with what changed."""
    site = _editable(db, site_id, view, principal)
    cad = _cad(db, site, body.cad_file_id)
    last = service.current(db, site.id)
    if last is not None and last.cad_file_id and last.cad_file_id != cad.id:
        data, changes = service.rebuild(db, site, last, cad)
        m = service.save(db, site.id, data, cad.id, principal.user, "Moved onto the new drawing revision", changes)
    else:
        m = service.save(db, site.id, service.draft(db, site, cad), cad.id, principal.user, "Started from the drawing")
    audit.record(db, user_id=principal.user.id, action="building.from_drawing", entity="site", entity_id=site.id, after={"version": m.version, "cad_file_id": cad.id}, ip=audit.client_ip(request))
    db.commit()
    return _out(db, site, principal)


class SaveIn(BaseModel):
    data: dict[str, Any]
    note: str | None = Field(default=None, max_length=500)


@router.put("/{site_id}/building")
def save_building(site_id: int, body: SaveIn, request: Request, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    site = _editable(db, site_id, view, principal)
    last = service.current(db, site.id)
    if last is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start the model from a drawing first")
    data = _checked(body.data)
    cad = db.get(CadFile, last.cad_file_id) if last.cad_file_id else None
    if cad is not None:
        service.align_types(data, cad.unit_m or 0.001)
    m = service.save(db, site.id, data, last.cad_file_id, principal.user, body.note)
    audit.record(db, user_id=principal.user.id, action="building.save", entity="site", entity_id=site.id, after={"version": m.version}, ip=audit.client_ip(request))
    db.commit()
    return _out(db, site, principal)


def _checked(data: dict) -> dict:
    """The shape the 3D view needs, refused plainly when wrong (a broken model draws nothing)."""
    s = {**service.DEFAULTS, **(data.get("settings") or {})}
    for k, lo, hi in (("floor_height_m", 2.0, 8.0), ("slab_m", 0.05, 0.6), ("plinth_m", -5.0, 3.0), ("column_min_m", 0.1, 1.0), ("column_max_m", 0.2, 2.0), ("riser_m", 0.1, 0.25), ("ifc_max_mb", 10, 600)):
        if not lo <= float(s[k]) <= hi:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{k} must be between {lo} and {hi}")
    if s["bloom"] not in ("auto", "on", "off"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bloom is auto, on or off")
    keys = set()
    for t in data.get("floor_types") or []:
        if not t.get("key") or t["key"] in keys:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each floor type needs its own key")
        keys.add(t["key"])
        if t.get("outline") and len(t["outline"]) < 3:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The outline of {t.get('name')} needs at least 3 corners")
        for c in t.get("cores") or []:
            if c.get("kind") not in ("stair", "lift"):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A core is a stair or a lift")
    for f in data.get("floors") or []:
        if f.get("type") and f["type"] not in keys:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Floor {f.get('name')}: unknown floor type {f['type']}")
        if f.get("height_m") is not None and not 2.0 <= float(f["height_m"]) <= 10.0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Floor {f.get('name')}: height between 2 and 10 m")
        if f.get("level_by_hand") and f.get("elevation_m") is not None and not -30.0 <= float(f["elevation_m"]) <= 400.0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Floor {f.get('name')}: a level between -30 and +400 m")
    return {**data, "settings": s}


class TypeIn(BaseModel):
    key: str
    outline: list[list[float]] | None = None  # the outline being edited (columns: inside this)


def _type(m: BuildingModel, key: str) -> dict:
    t = next((t for t in (m.data or {}).get("floor_types", []) if t.get("key") == key), None)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Floor type not found")
    return t


@router.post("/{site_id}/building/propose-outline")
def propose_outline(site_id: int, body: TypeIn, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    """A proposal for the plan's outer outline from its walls (doors and windows bridged), to
    correct with the snapping tracer. Drawing units."""
    site = _editable(db, site_id, view, principal)
    m = service.current(db, site.id)
    if m is None or not m.cad_file_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start the model from a drawing first")
    return {"outline": service.propose_outline(db, db.get(CadFile, m.cad_file_id), _type(m, body.key))}


@router.post("/{site_id}/building/detect-columns")
def detect_columns(site_id: int, body: TypeIn, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    """The column-sized closed shapes on the column layers inside the outline, for the user to
    confirm once per floor type (click to add or remove)."""
    site = _editable(db, site_id, view, principal)
    m = service.current(db, site.id)
    if m is None or not m.cad_file_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start the model from a drawing first")
    t = {**_type(m, body.key), **({"outline": body.outline} if body.outline else {})}
    settings = {**service.DEFAULTS, **((m.data or {}).get("settings") or {})}
    cols = service.detect_columns(db, db.get(CadFile, m.cad_file_id), t, settings)
    return {"columns": cols, "limits_m": [settings["column_min_m"], settings["column_max_m"]]}


@router.get("/{site_id}/building/versions")
def versions(site_id: int, db: DbSession, principal: CurrentPrincipal, view: View) -> list[dict]:
    site = _site(db, site_id, view, principal)
    return [{"version": m.version, "cad_file_id": m.cad_file_id, "note": m.note, "changes": m.changes, "by": m.created_by_name, "at": m.created_at}
            for m in db.scalars(select(BuildingModel).where(BuildingModel.site_id == site.id).order_by(BuildingModel.version.desc()))]  # fmt: skip


tiles = APIRouter(prefix="/api/building", tags=["building"])


@tiles.get("/active-sites")
def active_sites(db: DbSession, principal: CurrentPrincipal, view: View) -> list[dict]:
    """The active sites with a building model that the person may see: the dashboard's tiles."""
    rows = db.execute(
        select(Site, BuildingModel.version)
        .join(BuildingModel, BuildingModel.site_id == Site.id)
        .where(Site.status == "active")
        .order_by(Site.code, BuildingModel.version.desc())
    ).all()
    out, seen = [], set()
    for site, version in rows:
        if site.id in seen or not sites.covers(view, principal, site):
            continue
        seen.add(site.id)
        out.append({"site_id": site.id, "code": site.code, "name": site.name, "version": version, "progress": float(progress.site_percent(db, site.id))})
    return out


# --- a client's BIM (IFC) file ---------------------------------------------------------------------

IFC_HARD_MAX_MB = 600  # beyond this the upload is refused outright; the laptop limit is the setting


@router.post("/{site_id}/building/ifc", status_code=status.HTTP_201_CREATED)
async def upload_ifc(site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, view: View, file: Annotated[UploadFile, File()]) -> dict:
    """The client's IFC file, kept with the site's drawings as a new revision of its "BIM model
    (IFC)" drawing; the 3D view offers it when the site's IFC setting is on."""
    from pathlib import Path  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415
    from app.execution.common import safe_name  # noqa: PLC0415

    site = _editable(db, site_id, view, principal)
    name = safe_name(file.filename or "model.ifc")
    if Path(name).suffix.lower() != ".ifc":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload the IFC file (.ifc)")
    head = await file.read(64)
    if not head.lstrip().upper().startswith(b"ISO-10303-21"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This is not an IFC file (it does not start with ISO-10303-21)")
    d = db.scalar(select(Drawing).where(Drawing.site_id == site.id, Drawing.title == "BIM model (IFC)"))
    if d is None:
        d = Drawing(site_id=site.id, title="BIM model (IFC)", discipline="other", created_by=principal.user.id)
        db.add(d)
        db.flush()
    rev = (db.scalar(select(func.max(DrawingRevision.rev_no)).where(DrawingRevision.drawing_id == d.id)) or -1) + 1
    rel = f"sites/{site.id}/drawings/bim-r{rev}-{name}"
    dst = Path(settings.media_dir) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    size = len(head)
    with dst.open("wb") as out:
        out.write(head)
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > IFC_HARD_MAX_MB * 1024 * 1024:
                out.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The IFC file is over {IFC_HARD_MAX_MB} MB: ask the client for a lighter export (one building, no furniture).")
            out.write(chunk)
    r = DrawingRevision(drawing_id=d.id, rev_no=rev, stored_path=rel, filename=name, size_bytes=size, uploaded_by=principal.user.id)
    db.add(r)
    db.flush()
    d.current_revision_id = r.id
    m = service.current(db, site.id)
    data = dict(m.data) if m else {"settings": dict(service.DEFAULTS), "levels": {"source": "default", "values_m": [], "note": "No drawing: the BIM file only."}, "floor_types": [], "floors": [], "ifc_links": {}}
    data["settings"] = {**service.DEFAULTS, **data.get("settings", {}), "ifc": True}
    data["ifc"] = {"drawing_id": d.id, "revision_id": r.id, "rev_no": rev, "filename": name, "size_mb": round(size / 1024 / 1024, 1)}
    m2 = service.save(db, site.id, data, m.cad_file_id if m else None, principal.user, f"BIM file {name} (R{rev})")
    audit.record(db, user_id=principal.user.id, action="building.ifc", entity="site", entity_id=site.id, after={"file": name, "size": size, "version": m2.version}, ip=audit.client_ip(request))
    db.commit()
    return _out(db, site, principal)


def ifc_file(db, site: Site):
    """The current revision of the site's IFC drawing, as a file response."""
    from app.execution.common import send_file  # noqa: PLC0415

    d = db.scalar(select(Drawing).where(Drawing.site_id == site.id, Drawing.title == "BIM model (IFC)"))
    r = db.get(DrawingRevision, d.current_revision_id) if d and d.current_revision_id else None
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No IFC file for this site")
    return send_file(r.stored_path, r.filename)


@router.get("/{site_id}/building/ifc")
def get_ifc(site_id: int, db: DbSession, principal: CurrentPrincipal, view: View):
    return ifc_file(db, _site(db, site_id, view, principal))


class LinkIn(BaseModel):
    element: int  # the IFC element's express id
    node_id: int | None  # the site's place, None to unlink


@router.put("/{site_id}/building/ifc-links")
def link_ifc(site_id: int, body: LinkIn, request: Request, db: DbSession, principal: CurrentPrincipal, view: View) -> dict:
    """An IFC space or slab linked once to one of our places (planning): it then takes the place's
    status colour."""
    from app.sites.models import SiteNode  # noqa: PLC0415

    site = _editable(db, site_id, view, principal)
    m = service.current(db, site.id)
    if m is None or not (m.data or {}).get("ifc"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload the IFC file first")
    if body.node_id is not None:
        n = db.get(SiteNode, body.node_id)
        if n is None or n.site_id != site.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found on this site")
    data = dict(m.data)
    links = dict(data.get("ifc_links") or {})
    if body.node_id is None:
        links.pop(str(body.element), None)
    else:
        links[str(body.element)] = body.node_id
    data["ifc_links"] = links
    service.save(db, site.id, data, m.cad_file_id, principal.user, f"IFC element {body.element} linked")
    audit.record(db, user_id=principal.user.id, action="building.ifc_link", entity="site", entity_id=site.id, after={"element": body.element, "node_id": body.node_id}, ip=audit.client_ip(request))
    db.commit()
    return {"ifc_links": links}
