# ruff: noqa: E501
"""The product consumption library, mix designs, estimates from the measured areas, the site's
material requests, and the checks (coverage written in a BOQ or method statement, T&C wording on
free-issue materials, the margin against the BOQ rate)."""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import model_snapshot
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.costing import prices
from app.costing.models import RateWorking
from app.db import DbSession
from app.estimate import export, importer, margin, terms
from app.estimate import library as lib
from app.estimate import mix as mixes
from app.estimate import requests as reqs
from app.estimate import service as svc
from app.estimate.models import (
    COVERAGE_SOURCES,
    COVERAGE_UNITS,
    Coverage,
    Estimate,
    EstimateArea,
    EstimateLine,
    MaterialRequest,
    MixDesign,
)
from app.execution.common import pdf_response, record, save_upload, send_file
from app.masters.models import Product, System
from app.material import service as msvc
from app.models import AuditLog
from app.sites.models import Site

router = APIRouter(prefix="/api/estimate", tags=["estimate"])

View = Annotated[str, Depends(require_permission("estimate.view"))]
Edit = Annotated[str, Depends(require_permission("estimate.edit"))]
LibEdit = Annotated[str, Depends(require_permission("coverage.edit"))]
Ask = Annotated[str, Depends(require_permission("material_request.create"))]
Approve = Annotated[str, Depends(require_permission("material_request.approve"))]
D = Decimal


def _j(value: Any) -> Any:
    """Decimals as strings (quantities and money never pass through a float)."""
    return jsonable_encoder(value, custom_encoder={Decimal: str})


def _422(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _404(msg: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)


def _site(db, site_id: int, scope: str, principal: Principal) -> Site:
    site = db.get(Site, site_id)
    if site is None or not msvc.covers_site(db, scope, principal, site.id):
        raise _404("Site not found")
    return site


def _estimate(db, eid: int, scope: str, principal: Principal) -> Estimate:
    e = db.get(Estimate, eid)
    if e is None or (e.site_id is not None and not msvc.covers_site(db, scope, principal, e.site_id)):
        raise _404("Estimate not found")
    return e


def _said(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except (svc.Refused, reqs.Refused, ValueError) as exc:
        raise _422(str(exc)) from exc


# --- the library ----------------------------------------------------------------------------------


def _cov_out(db, c: Coverage) -> dict:
    s = db.get(System, c.system_id) if c.system_id else None
    return {"id": c.id, "product_id": c.product_id, "system_id": c.system_id, "system": s.name if s else None, "value": c.value, "min_value": c.min_value,
            "max_value": c.max_value, "unit": c.unit, "source": c.source, "source_label": lib.SOURCE_LABELS.get(c.source, c.source), "doc_name": c.doc_name,
            "has_doc": bool(c.doc_path), "note": c.note, "per_sqm": lib.per_sqm(c.value, c.unit), "label": lib.label(c), "updated_at": c.updated_at}  # fmt: skip


def _product_out(db, p: Product, covs: list[Coverage]) -> dict:
    return {"id": p.id, "code": p.code, "name": p.name, "brand": p.brand, "unit": p.unit, "wastage_percent": p.wastage_percent, "pack_size": p.pack_size,
            "pack_unit": p.pack_unit, "coverages": [_cov_out(db, c) for c in covs]}  # fmt: skip


@router.get("/library")
def library(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    covs = list(db.scalars(select(Coverage).order_by(Coverage.product_id, Coverage.system_id.nulls_first())))
    by: dict[int, list[Coverage]] = {}
    for c in covs:
        by.setdefault(c.product_id, []).append(c)
    products = [_product_out(db, p, by.get(p.id, [])) for p in db.scalars(select(Product).where(Product.id.in_(list(by) or [0])).order_by(Product.name))]
    return _j({"products": products, "units": COVERAGE_UNITS, "sources": [{"key": k, "label": lib.SOURCE_LABELS[k]} for k in COVERAGE_SOURCES],
                             "systems": [{"id": s.id, "name": s.name, "upturn_mm": s.upturn_mm} for s in db.scalars(select(System).where(System.is_active.is_(True)).order_by(System.name))],
                             "can_edit": "coverage.edit" in principal.permissions})  # fmt: skip


class CoverageIn(BaseModel):
    product_id: int
    system_id: int | None = None
    value: Decimal = Field(gt=0)
    min_value: Decimal | None = Field(None, gt=0)
    max_value: Decimal | None = Field(None, gt=0)
    unit: Literal["kg/sqm", "L/sqm", "sqm/kg", "sqm/L", "kg/sqft", "sqm/sqm"] = "kg/sqm"
    source: Literal["tds", "boq_spec", "method_statement", "site_trial", "to_confirm"] = "to_confirm"
    note: str | None = None


def _check_range(body: CoverageIn) -> None:
    if body.min_value is not None and body.max_value is not None and body.min_value > body.max_value:
        raise _422("The min is more than the max")
    if body.min_value is not None and body.value < body.min_value or body.max_value is not None and body.value > body.max_value:
        raise _422("The value used is outside its own min and max")


@router.post("/coverages", status_code=status.HTTP_201_CREATED)
def add_coverage(body: CoverageIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> dict:
    _check_range(body)
    if db.get(Product, body.product_id) is None:
        raise _422("Product not found")
    if lib.coverage_for(db, body.product_id, body.system_id) and db.scalar(select(Coverage.id).where(Coverage.product_id == body.product_id, Coverage.system_id.is_(None) if body.system_id is None else Coverage.system_id == body.system_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The product has a coverage in that system already: change it")
    c = Coverage(**body.model_dump(), created_by=principal.user.id)
    db.add(c)
    db.flush()
    record(db, request, principal, "coverage.create", "coverage", c.id, after=_j(model_snapshot(c)))
    db.commit()
    return _j(_cov_out(db, c))


@router.put("/coverages/{cid}")
def put_coverage(cid: int, body: CoverageIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> dict:
    c = db.get(Coverage, cid)
    if c is None:
        raise _404("Coverage not found")
    _check_range(body)
    before = _j(model_snapshot(c))
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.flush()
    record(db, request, principal, "coverage.update", "coverage", c.id, before=before, after=_j(model_snapshot(c)))
    db.commit()
    return _j(_cov_out(db, c))


@router.delete("/coverages/{cid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coverage(cid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> Response:
    c = db.get(Coverage, cid)
    if c is None:
        raise _404("Coverage not found")
    record(db, request, principal, "coverage.delete", "coverage", c.id, before=_j(model_snapshot(c)))
    db.delete(c)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/coverages/{cid}/doc")
async def coverage_doc(cid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit, file: Annotated[UploadFile, File()]) -> dict:
    c = db.get(Coverage, cid)
    if c is None:
        raise _404("Coverage not found")
    rel, name = await save_upload(file, f"library/coverage-{c.id}", frozenset({".docx", ".xlsx", ".xls"}))
    c.doc_path, c.doc_name = rel, name
    record(db, request, principal, "coverage.document", "coverage", c.id, after={"doc_name": name})
    db.commit()
    return _j(_cov_out(db, c))


@router.get("/coverages/{cid}/doc")
def get_coverage_doc(cid: int, db: DbSession, principal: CurrentPrincipal, _: View):
    c = db.get(Coverage, cid)
    if c is None:
        raise _404("Coverage not found")
    return send_file(c.doc_path, c.doc_name)


class ProductIn(BaseModel):
    wastage_percent: Decimal = Field(ge=0, le=100)
    pack_size: Decimal | None = Field(None, gt=0)
    pack_unit: str | None = Field(None, max_length=20)


@router.put("/products/{pid}")
def put_product(pid: int, body: ProductIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> dict:
    p = db.get(Product, pid)
    if p is None:
        raise _404("Product not found")
    before = {"wastage_percent": p.wastage_percent, "pack_size": p.pack_size, "pack_unit": p.pack_unit}
    p.wastage_percent, p.pack_size, p.pack_unit = body.wastage_percent, body.pack_size, (body.pack_unit or None)
    record(db, request, principal, "coverage.product", "product", p.id, before=_j(before), after=_j(body.model_dump()))
    db.commit()
    return _j(_product_out(db, p, list(db.scalars(select(Coverage).where(Coverage.product_id == p.id)))))


@router.get("/library/changes")
def library_changes(db: DbSession, principal: CurrentPrincipal, _: View, limit: int = 100) -> list[dict]:
    """Every change to the library: when, what, before and after."""
    rows = db.scalars(select(AuditLog).where(AuditLog.action.like("coverage.%") | AuditLog.action.like("mix.%")).order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    out = []
    for a in rows:
        out.append({"id": a.id, "at": a.at, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "before": a.before, "after": a.after})
    return _j(out)


class TextIn(BaseModel):
    text: str = Field(max_length=200_000)
    system_id: int | None = None


@router.post("/check-text")
def check_text(body: TextIn, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """Coverage written in a BOQ or method statement, against the library (as one types)."""
    return _j({"warnings": lib.check_text(db, body.text, body.system_id), "terms": terms.check_all([("", body.text)])})


# --- mix designs ----------------------------------------------------------------------------------


def _mix_out(db, m: MixDesign, thickness: Decimal | None = None) -> dict:
    ps = mixes.parts(db, m, thickness)
    return {"id": m.id, "code": m.code, "name": m.name, "kind": m.kind, "thickness_mm": m.thickness_mm, "dry_volume_factor": m.dry_volume_factor,
            "components": m.components, "admixture_product_id": m.admixture_product_id, "admixture_per_bag": m.admixture_per_bag, "cement_bag_kg": m.cement_bag_kg,
            "round_sqft": m.round_sqft, "source": m.source, "note": m.note, "at_mm": thickness if thickness is not None else m.thickness_mm,
            "parts": [{"role": p.role, "product_id": p.product_id, "product": p.product, "unit": p.unit, "per_sqm": p.per_sqm, "per_sqft": p.per_sqft, "how": p.how} for p in ps]}  # fmt: skip


@router.get("/mixes")
def list_mixes(db: DbSession, principal: CurrentPrincipal, _: View) -> list[dict]:
    return _j([_mix_out(db, m) for m in db.scalars(select(MixDesign).order_by(MixDesign.name))])


@router.get("/mixes/{mid}")
def get_mix(mid: int, db: DbSession, principal: CurrentPrincipal, _: View, thickness_mm: Decimal | None = None) -> dict:
    m = db.get(MixDesign, mid)
    if m is None:
        raise _404("Mix design not found")
    return _j(_mix_out(db, m, thickness_mm))


class MixPart(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    product_id: int | None = None
    parts: Decimal = Field(gt=0)
    density: Decimal = Field(gt=0)


class MixIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["nodular", "plaster", "brick_bat", "other"] = "other"
    thickness_mm: Decimal = Field(gt=0)
    dry_volume_factor: Decimal = Field(gt=0)
    components: list[MixPart]
    admixture_product_id: int | None = None
    admixture_per_bag: Decimal | None = Field(None, gt=0)
    cement_bag_kg: Decimal = Field(Decimal(50), gt=0)
    round_sqft: int | None = Field(None, ge=0, le=4)
    source: Literal["tds", "boq_spec", "method_statement", "site_trial", "to_confirm"] = "to_confirm"
    note: str | None = None


def _mix_fields(body: MixIn) -> dict:
    d = body.model_dump()
    d["components"] = [_j(c) for c in body.components]
    for c in d["components"]:
        c["parts"], c["density"] = float(c["parts"]), float(c["density"])
    return d


@router.post("/mixes", status_code=status.HTTP_201_CREATED)
def add_mix(body: MixIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> dict:
    if db.scalar(select(MixDesign.id).where(MixDesign.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{body.code} exists")
    m = MixDesign(**_mix_fields(body), created_by=principal.user.id)
    db.add(m)
    db.flush()
    record(db, request, principal, "mix.create", "mix_design", m.id, after=_j(model_snapshot(m)))
    db.commit()
    return _j(_mix_out(db, m))


@router.put("/mixes/{mid}")
def put_mix(mid: int, body: MixIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: LibEdit) -> dict:
    m = db.get(MixDesign, mid)
    if m is None:
        raise _404("Mix design not found")
    before = _j(model_snapshot(m))
    for k, v in _mix_fields(body).items():
        setattr(m, k, v)
    db.flush()
    record(db, request, principal, "mix.update", "mix_design", m.id, before=before, after=_j(model_snapshot(m)))
    db.commit()
    return _j(_mix_out(db, m))


# --- estimates ------------------------------------------------------------------------------------


def _area_out(a: EstimateArea) -> dict:
    return {"id": a.id, "source": a.source, "measure_area_id": a.measure_area_id, "cad_area_id": a.cad_area_id, "parent_id": a.parent_id, "code": a.code, "name": a.name,
            "floor_sqm": a.floor_sqm, "deduction_sqm": a.deduction_sqm, "periphery_m": a.periphery_m, "upturn_mm": a.upturn_mm, "use_floor": a.use_floor,
            "use_upturn": a.use_upturn, "included": a.included, "excluded_reason": a.excluded_reason}  # fmt: skip


def _line_out(lo: svc.LineOut) -> dict:
    ln = lo.line
    return {"id": ln.id, "product_id": lo.product.id, "product": lo.product.name, "unit": lo.product.unit, "system_id": ln.system_id, "system": lo.system,
            "mix_design_id": ln.mix_design_id, "thickness_mm": ln.thickness_mm, "part": ln.part, "area_ids": ln.area_ids, "note": ln.note,
            "coverage": lo.cov.shown if lo.cov else None, "coverage_id": lo.cov.coverage_id if lo.cov else None, "per_sqm": lo.cov.per_sqm if lo.cov else None,
            "wastage_percent": lo.wastage, "qty": lo.qty, "packs": lo.packs.text if lo.packs else None, "pack_count": lo.packs.count if lo.packs else None,
            "pack_size": lo.packs.size if lo.packs else None, "complete": lo.cov is not None,
            "rows": [{"area_id": r.area_id, "code": r.code, "name": r.name, "measure_area_id": r.measure_area_id, "floor_sqm": r.floor_sqm, "upturn_sqm": r.upturn_sqm,
                      "base_sqm": r.base_sqm, "qty": r.qty, "formula": r.formula} for r in lo.rows]}  # fmt: skip


def _est_out(db, e: Estimate, principal: Principal) -> dict:
    site = db.get(Site, e.site_id) if e.site_id else None
    missed = svc.missed(db, e)
    lines = svc.worked(db, e)
    return {"id": e.id, "code": e.code, "title": e.title, "status": e.status, "site_id": e.site_id, "tender_id": e.tender_id, "upturn_mm": e.upturn_mm, "note": e.note,
            "site": {"id": site.id, "code": site.code, "name": site.name} if site else None, "issued_at": e.issued_at,
            "areas": [_area_out(a) for a in svc.areas_of(db, e)], "lines": [_line_out(lo) for lo in lines], "summary": svc.summary(db, e),
            "missed": [{"key": m.key, "source": m.source, "code": m.code, "name": m.name, "floor_sqm": m.floor_sqm, "periphery_m": m.periphery_m} for m in missed],
            "warnings": ([f"{len(missed)} measured area(s) are not in the estimate and not excluded: " + "; ".join(f"{m.name} ({lib.n(m.floor_sqm, 2)} sqm)" for m in missed)] if missed else [])
            + [f"{lo.product.name}: no coverage in the library, the estimate is not complete" for lo in lines if lo.cov is None],
            "can_edit": "estimate.edit" in principal.permissions and e.status == "draft"}  # fmt: skip


@router.get("/estimates")
def list_estimates(db: DbSession, principal: CurrentPrincipal, scope: View, site_id: int | None = None) -> list[dict]:
    q = select(Estimate).order_by(Estimate.id.desc())
    if site_id is not None:
        q = q.where(Estimate.site_id == site_id)
    out = []
    for e in db.scalars(q.limit(200)):
        if e.site_id is not None and not msvc.covers_site(db, scope, principal, e.site_id):
            continue
        site = db.get(Site, e.site_id) if e.site_id else None
        out.append({"id": e.id, "code": e.code, "title": e.title, "status": e.status, "site": f"{site.code} {site.name}" if site else None, "site_id": e.site_id,
                    "missed": len(svc.missed(db, e))})  # fmt: skip
    return _j(out)


class EstimateIn(BaseModel):
    site_id: int | None = None
    tender_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    upturn_mm: Decimal = Field(Decimal(300), ge=0, le=3000)
    note: str | None = None
    take_areas: bool = True


@router.post("/estimates", status_code=status.HTTP_201_CREATED)
def create_estimate(body: EstimateIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    if body.site_id is None and body.tender_id is None:
        raise _422("Choose the site (or tender)")
    if body.site_id is not None:
        _site(db, body.site_id, scope, principal)
    e = Estimate(code=msvc.next_code(db, "EST"), site_id=body.site_id, tender_id=body.tender_id, title=body.title.strip(), upturn_mm=body.upturn_mm, note=body.note, created_by=principal.user.id)
    db.add(e)
    db.flush()
    if body.take_areas and e.site_id is not None:
        _said(svc.add_measured, db, e)
    record(db, request, principal, "estimate.create", "estimate", e.id, after={"code": e.code, "title": e.title})
    db.commit()
    return _j(_est_out(db, e, principal))


@router.get("/estimates/{eid}")
def get_estimate(eid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    return _j(_est_out(db, _estimate(db, eid, scope, principal), principal))


def _draft(db, eid: int, scope: str, principal: Principal) -> Estimate:
    e = _estimate(db, eid, scope, principal)
    if e.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{e.code} is issued: make a new one to change it")
    return e


class AreasIn(BaseModel):
    keys: list[str] | None = None  # measure:12, takeoff:40; none: every area not in it yet


@router.post("/estimates/{eid}/areas")
def add_areas(eid: int, body: AreasIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    made = _said(svc.add_measured, db, e, body.keys)
    record(db, request, principal, "estimate.areas", "estimate", e.id, after={"added": [a.name for a in made]})
    db.commit()
    return _j(_est_out(db, e, principal))


class ExcludeIn(BaseModel):
    key: str
    reason: str = Field(min_length=3, max_length=500)


@router.post("/estimates/{eid}/exclude")
def exclude_area(eid: int, body: ExcludeIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    a = _said(svc.exclude, db, e, body.key, body.reason)
    record(db, request, principal, "estimate.exclude", "estimate", e.id, after={"area": a.name, "reason": a.excluded_reason})
    db.commit()
    return _j(_est_out(db, e, principal))


class AreaIn(BaseModel):
    upturn_mm: Decimal | None = Field(None, ge=0, le=3000)
    use_floor: bool = True
    use_upturn: bool = True
    included: bool = True
    excluded_reason: str | None = None


@router.put("/estimates/{eid}/areas/{aid}")
def put_area(eid: int, aid: int, body: AreaIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    a = db.get(EstimateArea, aid)
    if a is None or a.estimate_id != e.id:
        raise _404("Area not found")
    if not body.included and not (body.excluded_reason or "").strip():
        raise _422("Say why the area is left out")
    a.upturn_mm, a.use_floor, a.use_upturn, a.included = body.upturn_mm, body.use_floor, body.use_upturn, body.included
    a.excluded_reason = None if body.included else body.excluded_reason.strip()
    record(db, request, principal, "estimate.area", "estimate", e.id, after=_j(_area_out(a)))
    db.commit()
    return _j(_est_out(db, e, principal))


class LineIn(BaseModel):
    product_id: int
    system_id: int | None = None
    mix_design_id: int | None = None
    thickness_mm: Decimal | None = Field(None, gt=0, le=1000)
    part: Literal["both", "floor", "upturn"] = "both"
    area_ids: list[int] | None = None
    note: str | None = None


def _line_fields(db, e: Estimate, body: LineIn) -> dict:
    if db.get(Product, body.product_id) is None:
        raise _422("Product not found")
    if body.mix_design_id is not None:
        mx = db.get(MixDesign, body.mix_design_id)
        if mx is None or mixes.part_for(db, mx, body.product_id, body.thickness_mm) is None:
            raise _422("That product is not in the mix design")
    if body.area_ids:
        ids = {a.id for a in svc.areas_of(db, e)}
        if not set(body.area_ids) <= ids:
            raise _422("An area is not in this estimate")
    return body.model_dump()


@router.post("/estimates/{eid}/lines", status_code=status.HTTP_201_CREATED)
def add_line(eid: int, body: LineIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    order = max((ln.sort_order for ln in svc.lines_of(db, e)), default=0) + 1
    ln = EstimateLine(estimate_id=e.id, sort_order=order, **_line_fields(db, e, body))
    db.add(ln)
    db.flush()
    record(db, request, principal, "estimate.line", "estimate", e.id, after=_j(body.model_dump()))
    db.commit()
    return _j(_est_out(db, e, principal))


@router.put("/estimates/{eid}/lines/{lid}")
def put_line(eid: int, lid: int, body: LineIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    ln = db.get(EstimateLine, lid)
    if ln is None or ln.estimate_id != e.id:
        raise _404("Line not found")
    for k, v in _line_fields(db, e, body).items():
        setattr(ln, k, v)
    record(db, request, principal, "estimate.line", "estimate", e.id, after=_j(body.model_dump()))
    db.commit()
    return _j(_est_out(db, e, principal))


@router.delete("/estimates/{eid}/lines/{lid}")
def delete_line(eid: int, lid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    ln = db.get(EstimateLine, lid)
    if ln is None or ln.estimate_id != e.id:
        raise _404("Line not found")
    db.delete(ln)
    record(db, request, principal, "estimate.line_delete", "estimate", e.id, after={"line": lid})
    db.commit()
    return _j(_est_out(db, e, principal))


@router.post("/estimates/{eid}/issue")
def issue(eid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Edit) -> dict:
    e = _draft(db, eid, scope, principal)
    missed = svc.missed(db, e)
    if missed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Put these measured areas in the estimate or exclude them with a reason first: " + "; ".join(f"{m.name} ({lib.n(m.floor_sqm, 2)} sqm)" for m in missed))
    if not svc.lines_of(db, e):
        raise _422("Add the materials first")
    e.status, e.issued_at, e.issued_by = "issued", datetime.now(UTC), principal.user.id
    record(db, request, principal, "estimate.issue", "estimate", e.id, after={"code": e.code})
    db.commit()
    return _j(_est_out(db, e, principal))


@router.get("/estimates/{eid}/balance")
def estimate_balance(eid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> list[dict]:
    """Per material: needed, asked for, sent, returned, in stock, used, left."""
    return _j(svc.balance(db, _estimate(db, eid, scope, principal)))


@router.get("/estimates/{eid}/excel")
def estimate_excel(eid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    e = _estimate(db, eid, scope, principal)
    site = db.get(Site, e.site_id) if e.site_id else None
    data = export.workbook(db, e, f"{site.code} {site.name}" if site else None)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{e.code}.xlsx"'})


@router.get("/estimates/{eid}/pdf")
def estimate_pdf(eid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> Response:
    e = _estimate(db, eid, scope, principal)
    site = db.get(Site, e.site_id) if e.site_id else None
    return pdf_response(export.pdf(db, e, f"{site.code} {site.name}" if site else None), e.code)


@router.post("/estimates/{eid}/import")
async def import_old(eid: int, db: DbSession, principal: CurrentPrincipal, scope: View, file: Annotated[UploadFile, File()]) -> dict:
    """An old planning sheet read against this estimate's site drawing and the library."""
    e = _estimate(db, eid, scope, principal)
    data = await file.read()
    try:
        return _j(importer.read(db, data, file.filename or "sheet.xlsx", svc.measured(db, e.site_id) if e.site_id else None))
    except (OSError, ValueError, KeyError) as exc:
        raise _422(f"The file could not be read as a workbook: {exc}") from exc


# --- the site's material requests -----------------------------------------------------------------


def _req_out(db, r: MaterialRequest) -> dict:
    p = db.get(Product, r.product_id)
    a = db.get(EstimateArea, r.estimate_area_id) if r.estimate_area_id else None
    from app.material.models import Indent  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    ind = db.get(Indent, r.indent_id) if r.indent_id else None
    by = db.get(User, r.created_by) if r.created_by else None
    site = db.get(Site, r.site_id)
    return {"id": r.id, "code": r.code, "site_id": r.site_id, "site": f"{site.code} {site.name}" if site else None, "estimate_id": r.estimate_id, "area": f"{a.code + ' ' if a and a.code else ''}{a.name}" if a else None,
            "estimate_area_id": r.estimate_area_id, "product_id": r.product_id, "product": p.name if p else None, "unit": p.unit if p else None, "mix_design_id": r.mix_design_id,
            "area_sqm": r.area_sqm, "thickness_mm": r.thickness_mm, "qty": r.qty, "packs": r.packs, "formula": r.formula, "left_before": r.left_before,
            "over_reason": r.over_reason, "status": r.status, "approved_qty": r.approved_qty, "change_note": r.change_note, "decided_at": r.decided_at,
            "indent": {"id": ind.id, "code": ind.code, "status": ind.status} if ind else None, "asked_by_role": "site" if by else None, "created_at": r.created_at}  # fmt: skip


class AskIn(BaseModel):
    site_id: int
    product_id: int
    area_sqm: Decimal = Field(gt=0)
    thickness_mm: Decimal | None = Field(None, gt=0, le=1000)
    mix_design_id: int | None = None
    estimate_area_id: int | None = None
    reason: str | None = None
    preview: bool = False


@router.post("/requests")
def ask(body: AskIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Ask) -> dict:
    """The site's ask; preview: only the working, nothing saved (the phone shows it as one types)."""
    site = _site(db, body.site_id, scope, principal)
    if body.preview:
        p = db.get(Product, body.product_id)
        if p is None:
            raise _422("Choose the material")
        mx = db.get(MixDesign, body.mix_design_id) if body.mix_design_id else None
        est = reqs.estimate_for(db, site.id)
        line = next((ln for ln in svc.lines_of(db, est) if ln.product_id == p.id), None) if est else None
        qty, formula, pk = _said(reqs.work_out, db, p, body.area_sqm, body.thickness_mm if body.thickness_mm is not None else (mx.thickness_mm if mx else None), mx, line.system_id if line else None)
        area = db.get(EstimateArea, body.estimate_area_id) if body.estimate_area_id else None
        left = reqs.left(db, est, p.id, area) if est else None
        return _j({"qty": qty, "formula": formula, "packs": pk.count if pk else None, "left": left, "over": reqs.over(qty, left)})
    r = _said(reqs.ask, db, site, product_id=body.product_id, area_sqm=body.area_sqm, thickness_mm=body.thickness_mm, mix_design_id=body.mix_design_id,
              estimate_area_id=body.estimate_area_id, reason=body.reason, user_id=principal.user.id)  # fmt: skip
    record(db, request, principal, "material_request.create", "material_request", r.id, after={"code": r.code, "formula": r.formula, "over_reason": r.over_reason})
    db.commit()
    return _j(_req_out(db, r))


@router.get("/requests")
def list_requests(db: DbSession, principal: CurrentPrincipal, _: View, site_id: int | None = None, state: str | None = None) -> list[dict]:
    q = select(MaterialRequest).order_by(MaterialRequest.id.desc())
    if site_id is not None:
        q = q.where(MaterialRequest.site_id == site_id)
    if state:
        q = q.where(MaterialRequest.status.in_(state.split(",")))
    scope = principal.permissions.get("estimate.view")
    out = []
    for r in db.scalars(q.limit(300)):
        if not msvc.covers_site(db, scope, principal, r.site_id):
            continue
        out.append(_req_out(db, r))
    return _j(out)


@router.get("/sites/{site_id}/ask")
def ask_form(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Ask) -> dict:
    """What the phone's request form offers: the estimate's materials and areas, the mix designs."""
    site = _site(db, site_id, scope, principal)
    est = reqs.estimate_for(db, site.id)
    products, areas = [], []
    if est is not None:
        seen = set()
        for ln in svc.lines_of(db, est):
            if ln.product_id in seen:
                continue
            seen.add(ln.product_id)
            p = db.get(Product, ln.product_id)
            products.append({"id": p.id, "name": p.name, "unit": p.unit, "mix_design_id": ln.mix_design_id, "thickness_mm": ln.thickness_mm, "pack_size": p.pack_size, "pack_unit": p.pack_unit})
        areas = [{"id": a.id, "code": a.code, "name": a.name, "floor_sqm": a.floor_sqm} for a in svc.areas_of(db, est) if a.included]
    return _j({"site": {"id": site.id, "code": site.code, "name": site.name}, "estimate": {"id": est.id, "code": est.code, "status": est.status} if est else None,
                             "products": products, "areas": areas, "mixes": [{"id": m.id, "name": m.name, "thickness_mm": m.thickness_mm} for m in db.scalars(select(MixDesign).order_by(MixDesign.name))],
                             "requests": [_req_out(db, r) for r in db.scalars(select(MaterialRequest).where(MaterialRequest.site_id == site.id).order_by(MaterialRequest.id.desc()).limit(20))]})  # fmt: skip


class DecideIn(BaseModel):
    approve: bool = True
    qty: Decimal | None = Field(None, gt=0)
    note: str | None = None
    required_by: date | None = None


@router.post("/requests/{rid}/decide")
def decide(rid: int, body: DecideIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Approve) -> dict:
    r = db.get(MaterialRequest, rid)
    if r is None or not msvc.covers_site(db, scope, principal, r.site_id):
        raise _404("Request not found")
    if body.approve:
        ind = _said(reqs.approve, db, r, qty=body.qty, note=body.note, user_id=principal.user.id, required_by=body.required_by)
        record(db, request, principal, "material_request.approve", "material_request", r.id, after={"indent": ind.code, "qty": str(r.approved_qty), "note": r.change_note})
    else:
        _said(reqs.reject, db, r, note=body.note or "", user_id=principal.user.id)
        record(db, request, principal, "material_request.reject", "material_request", r.id, after={"note": r.change_note})
    db.commit()
    return _j(_req_out(db, r))


# --- checks before a BOQ, a quotation or a method statement is sent ----------------------------------


def _tender_texts(db, tender_id: int) -> tuple[list[tuple[str, str, int | None]], list[tuple[str, str]]]:
    from app.masters.models import TcClause  # noqa: PLC0415
    from app.tenders.models import BoqLine, TenderTc  # noqa: PLC0415

    boq = [(f"BOQ item {ln.client_item_no or ln.id}", " ".join(x for x in (ln.description, ln.client_product, ln.our_remarks) if x), ln.system_id)
           for ln in db.scalars(select(BoqLine).where(BoqLine.tender_id == tender_id).order_by(BoqLine.sort_order, BoqLine.id))]  # fmt: skip
    tcs = []
    for t in db.scalars(select(TenderTc).where(TenderTc.tender_id == tender_id).order_by(TenderTc.sort_order)):
        c = db.get(TcClause, t.clause_id) if t.clause_id else None
        tcs.append((f"T&C {t.sort_order + 1}", t.text_override or (c.text if c else "")))
    return boq, tcs


def tender_checks(db, tender_id: int) -> dict:
    boq, tcs = _tender_texts(db, tender_id)
    cov = [w for where, text, sid in boq for w in lib.check_text(db, text, sid, where)]
    return {"coverage": cov, "terms": terms.check_all(tcs)}


def quotation_checks(db, q) -> dict:
    texts: list[tuple[str, str, int | None]] = []
    for i in q.items:
        spec = " ".join(str(s.get("text") or s.get("body") or "") for s in (i.specs or []) if isinstance(s, dict))
        texts.append((f"{i.name} (spec)", spec, None))
        for ln in i.lines:
            texts.append((f"{i.name}: {ln.description[:40]}", ln.description, ln.system_id))
    cov = [w for where, text, sid in texts for w in lib.check_text(db, text, sid, where)]
    return {"coverage": cov, "terms": terms.check_all([(f"T&C {n + 1}", t.get("text") or "") for n, t in enumerate(q.terms or [])])}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def methodology_checks(db, m) -> dict:
    from app.methodology.models import MethodologyItem  # noqa: PLC0415

    cov = []
    for it in db.scalars(select(MethodologyItem).where(MethodologyItem.methodology_id == m.id).order_by(MethodologyItem.sort_order)):
        text = "\n".join(_strings(it.stages) + _strings(it.edits))
        cov += lib.check_text(db, text, None, f"Method statement, {it.name}")
    return {"coverage": cov, "terms": []}


@router.get("/checks")
def checks(db: DbSession, principal: CurrentPrincipal, _: View, tender_id: int | None = None, quotation_id: int | None = None, methodology_id: int | None = None) -> dict:
    """The coverage and T&C checks of a tender's BOQ, a quotation or a method statement."""
    if tender_id is not None:
        return _j(tender_checks(db, tender_id))
    if quotation_id is not None:
        from app.quotations.models import Quotation  # noqa: PLC0415

        q = db.get(Quotation, quotation_id)
        if q is None:
            raise _404("Quotation not found")
        return _j(quotation_checks(db, q))
    if methodology_id is not None:
        from app.methodology.models import Methodology  # noqa: PLC0415

        m = db.get(Methodology, methodology_id)
        if m is None:
            raise _404("Method statement not found")
        return _j(methodology_checks(db, m))
    raise _422("Say what to check")


@router.get("/terms/library")
def terms_library(db: DbSession, principal: CurrentPrincipal, _: View) -> list[dict]:
    """The T&C library's clauses that say we supply materials free, with the corrected text."""
    return _j(terms.library(db))


class FixIn(BaseModel):
    clause_id: int


@router.post("/terms/fix")
def fix_clause(body: FixIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Annotated[str, Depends(require_permission("library.edit"))]) -> list[dict]:
    from app.masters.models import TcClause  # noqa: PLC0415

    c = db.get(TcClause, body.clause_id)
    if c is None:
        raise _404("Clause not found")
    before = c.text
    c.text = terms.corrected(c.text)
    record(db, request, principal, "tc.fix_free_issue", "tc_clause", c.id, before={"text": before}, after={"text": c.text})
    db.commit()
    return _j(terms.library(db))


# --- the margin check -----------------------------------------------------------------------------


def _working(db, tender_id: int | None, quotation_id: int | None) -> RateWorking:
    q = select(RateWorking)
    if tender_id is not None:
        q = q.where(RateWorking.tender_id == tender_id).order_by(RateWorking.rev_no.desc())
    elif quotation_id is not None:
        q = q.where(RateWorking.quotation_id == quotation_id)
    else:
        raise _422("Say which tender or quotation")
    w = db.scalar(q.limit(1))
    if w is None:
        raise _404("No rate working yet")
    return w


@router.get("/margin")
def margin_check(db: DbSession, principal: CurrentPrincipal, _: Annotated[str, Depends(require_permission("tender.margin"))], tender_id: int | None = None, quotation_id: int | None = None) -> dict:
    w = _working(db, tender_id, quotation_id)
    out = margin.check(db, w)
    out["free_issue_ids"] = w.free_issue_product_ids or []
    out["free_issue_clause"] = terms.free_issue_text(db, w.free_issue_product_ids or [])
    out["products"] = _working_products(db, w)
    return _j(out)


class FreeIn(BaseModel):
    tender_id: int | None = None
    quotation_id: int | None = None
    product_ids: list[int]


@router.put("/margin/free-issue")
def free_issue(body: FreeIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Annotated[str, Depends(require_permission("tender.margin"))]) -> dict:
    """Mark products the client supplies free of cost: out of our cost; the T&C clause written."""
    w = _working(db, body.tender_id, body.quotation_id)
    if w.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "That revision is submitted: its working is kept as it was")
    w.free_issue_product_ids = sorted({int(x) for x in body.product_ids})
    text = terms.free_issue_text(db, w.free_issue_product_ids)
    _write_free_clause(db, w, text)
    record(db, request, principal, "margin.free_issue", "rate_working", w.id, after={"products": w.free_issue_product_ids, "clause": text})
    db.commit()
    out = margin.check(db, w)
    out["free_issue_ids"], out["free_issue_clause"] = w.free_issue_product_ids, text
    out["products"] = _working_products(db, w)
    return _j(out)


def _working_products(db, w: RateWorking) -> list[dict]:
    """Every product of the working (for the free-issue choice), with or without a coverage."""
    seen: dict[int, str] = {}
    for g in w.groups:
        for gp in g.products:
            p = db.get(Product, gp.product_id)
            seen.setdefault(p.id, p.name)
    return [{"id": i, "name": n} for i, n in sorted(seen.items(), key=lambda t: t[1])]


def _write_free_clause(db, w: RateWorking, text: str | None) -> None:
    """The free-issue clause in the tender's or quotation's T&C (one, kept in step)."""
    if w.tender_id is not None:
        from app.tenders.models import TenderTc  # noqa: PLC0415

        rows = [t for t in db.scalars(select(TenderTc).where(TenderTc.tender_id == w.tender_id)) if (t.text_override or "").startswith(terms.MARK)]
        for t in rows[1:]:
            db.delete(t)
        if text is None:
            for t in rows[:1]:
                db.delete(t)
        elif rows:
            rows[0].text_override = f"{terms.MARK} {text}"
        else:
            order = max((t.sort_order for t in db.scalars(select(TenderTc).where(TenderTc.tender_id == w.tender_id))), default=-1) + 1
            db.add(TenderTc(tender_id=w.tender_id, sort_order=order, text_override=f"{terms.MARK} {text}"))
    elif w.quotation_id is not None:
        from app.quotations.models import Quotation  # noqa: PLC0415

        q = db.get(Quotation, w.quotation_id)
        kept = [t for t in (q.terms or []) if not t.get("free_issue")]
        if text is not None:
            kept.append({"category": "client_scope", "text": text, "free_issue": True})
        q.terms = kept


class ShareIn(BaseModel):
    material_share_warn_percent: Decimal = Field(gt=0, le=100)


@router.get("/margin/settings")
def margin_settings(db: DbSession, principal: CurrentPrincipal, _: Annotated[str, Depends(require_permission("tender.margin"))]) -> dict:
    s = prices.settings(db)
    return _j({"material_share_warn_percent": s.material_share_warn_percent, "can_edit": "margin.settings" in principal.permissions})


@router.put("/margin/settings")
def put_margin_settings(body: ShareIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Annotated[str, Depends(require_permission("margin.settings"))]) -> dict:
    s = prices.settings(db)
    before = s.material_share_warn_percent
    s.material_share_warn_percent = body.material_share_warn_percent
    record(db, request, principal, "margin.settings", "costing_settings", 1, before={"material_share_warn_percent": str(before)}, after=_j(body.model_dump()))
    db.commit()
    return _j({"material_share_warn_percent": s.material_share_warn_percent, "can_edit": True})


def xlsx_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
