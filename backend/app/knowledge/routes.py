# ruff: noqa: E501  (the rows read better unwrapped)
"""The BOQ knowledge library API.

knowledge.view: estimator, planning, director, sales (templates, descriptions and the rates we
sold at); knowledge.cost: estimator, planning, director (cost, consumption, products, margins);
knowledge.edit: estimator, planning, director (merge, split, rename, hide, fix a value with a
reason). Clients never hold these permissions."""

import statistics
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import record
from app.knowledge import extract, library, service
from app.knowledge.models import (
    KnowledgeFile,
    KnowledgeFix,
    KnowledgeLine,
    KnowledgeMatch,
    KnowledgeTemplate,
)

router = APIRouter(prefix="/api/knowledge", tags=["boq knowledge"])
View = Annotated[str, Depends(require_permission("knowledge.view"))]
Edit = Annotated[str, Depends(require_permission("knowledge.edit"))]


def _cost(principal) -> bool:
    return "knowledge.cost" in principal.permissions


def _template(db, tid: int) -> KnowledgeTemplate:
    t = db.get(KnowledgeTemplate, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return t


@router.get("/options")
def options(db: DbSession, _: View) -> dict:
    s = library.settings(db)
    return {
        "areas": [{"key": k, "label": label} for k, label, _p in extract.AREA_TYPES],
        "surfaces": [{"key": k, "label": library.SURFACE_LABEL[k]} for k, _p in extract.SURFACES],
        "families": [{"key": k, "label": v} for k, v in extract.FAMILY_LABEL.items()],
        "brands": [b for b, _p in extract.BRANDS],
        "regions": s.regions or extract.DEFAULT_REGIONS,
        "old_after_months": s.old_after_months,
    }


@router.get("/report")
def report(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """The reading report: files read / failed / scanned, lines found, with a working, a place, a
    date; templates; the top templates by number of BOQs with their median rate."""
    s = library.settings(db)
    live = library.reading_report(db)
    top = db.scalars(select(KnowledgeTemplate).where(KnowledgeTemplate.merged_into_id.is_(None), KnowledgeTemplate.hidden.is_(False))
                     .order_by(KnowledgeTemplate.files_count.desc(), KnowledgeTemplate.lines_count.desc()).limit(10))  # fmt: skip
    templates = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeTemplate)
            .where(KnowledgeTemplate.merged_into_id.is_(None))
        )
        or 0
    )
    return jsonable_encoder({
        "last_run": {k: v for k, v in (s.last_run or {}).items() if k not in ("failed", "scanned")}, "live": live, "templates": templates,
        "top": [service.template_brief(t) for t in top], "source_folder": s.source_folder,
    })  # fmt: skip


@router.get("/templates")
def templates(
    db: DbSession,
    _: View,
    q: str | None = None,
    area: str | None = None,
    hidden: bool = False,
    limit: int = 200,
) -> list[dict]:
    query = select(KnowledgeTemplate).where(KnowledgeTemplate.merged_into_id.is_(None))
    if not hidden:
        query = query.where(KnowledgeTemplate.hidden.is_(False))
    if area:
        query = query.where(KnowledgeTemplate.area_type == area)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(KnowledgeTemplate.name.ilike(like), KnowledgeTemplate.description.ilike(like))
        )
    rows = db.scalars(
        query.order_by(
            KnowledgeTemplate.files_count.desc(), KnowledgeTemplate.lines_count.desc()
        ).limit(min(limit, 1000))
    )
    return jsonable_encoder([service.template_brief(t) for t in rows])


@router.get("/templates/{tid}")
def template(
    tid: int, db: DbSession, principal: CurrentPrincipal, _: View, city: str | None = None
) -> dict:
    t = _template(db, tid)
    cost = _cost(principal)
    out = service.template_brief(t) | {
        "rates": service.rates(db, t, city, cost),
        "can_edit": "knowledge.edit" in principal.permissions,
        "sees_cost": cost,
    }
    if cost:
        out["products"] = service.products(db, t, t.surface, city)
        out["margins"] = service.margins(db, t)
    out["fixes"] = [{"field": f.field, "old": f.old, "new": f.new, "reason": f.reason, "at": f.at}
                    for f in db.scalars(select(KnowledgeFix).where(KnowledgeFix.entity == "template", KnowledgeFix.entity_id == t.id).order_by(KnowledgeFix.at.desc()).limit(50))]  # fmt: skip
    return jsonable_encoder(out)


def _fix(
    db,
    principal,
    entity: str,
    ident: int,
    field: str,
    old,
    new,
    reason: str | None,
    need_reason: bool = True,
) -> None:
    reason = " ".join((reason or "").split())
    if need_reason and len(reason) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the reason for the change")
    db.add(KnowledgeFix(entity=entity, entity_id=ident, field=field, old=None if old is None else str(old), new=None if new is None else str(new),
                        reason=reason or "renamed or edited", by=principal.user.id))  # fmt: skip


class TemplateIn(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, min_length=10)
    steps: list[str] | None = None
    hidden: bool | None = None
    surface: str | None = None
    coats: int | None = Field(None, ge=1, le=10)
    min_kg_sqm: Decimal | None = Field(None, ge=0, le=50)
    dft_mm: Decimal | None = Field(None, ge=0, le=20)
    area_type: str | None = None
    reason: str | None = Field(None, max_length=1000)


VALUE_FIELDS = ("surface", "coats", "min_kg_sqm", "dft_mm", "area_type")


@router.put("/templates/{tid}")
def edit_template(
    tid: int,
    body: TemplateIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    """Rename, reword the description or the method statement, hide; a wrong extracted value
    (area, surface, coats, kg, DFT) is put right with a reason."""
    t = _template(db, tid)
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    for k, v in data.items():
        old = getattr(t, k)
        if old == v:
            continue
        _fix(db, principal, "template", t.id, k, old, v, reason, need_reason=k in VALUE_FIELDS)
        setattr(t, k, v)
    t.reviewed = True
    record(
        db,
        request,
        principal,
        "knowledge.template",
        "knowledge_template",
        t.id,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return template(t.id, db, principal, "all")


class MergeIn(BaseModel):
    into_id: int


@router.post("/templates/{tid}/merge")
def merge(
    tid: int, body: MergeIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    t, into = _template(db, tid), _template(db, body.into_id)
    if t.id == into.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick another template to merge into"
        )
    for ln in db.scalars(select(KnowledgeLine).where(KnowledgeLine.template_id == t.id)):
        ln.template_id = into.id
    t.merged_into_id = into.id
    library.refresh(into, service.members(db, into))
    library.refresh(t, [])
    _fix(db, principal, "template", t.id, "merged_into", None, into.id, None, need_reason=False)
    record(
        db,
        request,
        principal,
        "knowledge.merge",
        "knowledge_template",
        t.id,
        after={"into": into.id},
    )
    db.commit()
    return template(into.id, db, principal, "all")


class SplitIn(BaseModel):
    line_ids: list[int] = Field(min_length=1)
    name: str = Field(min_length=3, max_length=200)


@router.post("/templates/{tid}/split")
def split(
    tid: int, body: SplitIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    """Some of a template's lines become a template of their own."""
    t = _template(db, tid)
    lines = list(
        db.scalars(
            select(KnowledgeLine).where(
                KnowledgeLine.id.in_(body.line_ids), KnowledgeLine.template_id == t.id
            )
        )
    )
    if not lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick lines of this template")
    new = KnowledgeTemplate(key=t.key, name=body.name, area_type=t.area_type, surface=t.surface, coats=t.coats, min_kg_sqm=t.min_kg_sqm,
                            dft_mm=t.dft_mm, families=t.families, unit=t.unit, description=library.best_description(lines), steps=t.steps,
                            steps_source=t.steps_source, reviewed=True, created_by=principal.user.id)  # fmt: skip
    db.add(new)
    db.flush()
    for ln in lines:
        ln.template_id = new.id
    library.refresh(new, lines)
    library.refresh(t, service.members(db, t))
    _fix(
        db,
        principal,
        "template",
        t.id,
        "split",
        None,
        f"{len(lines)} line(s) to template {new.id}",
        None,
        need_reason=False,
    )
    record(
        db,
        request,
        principal,
        "knowledge.split",
        "knowledge_template",
        t.id,
        after={"new": new.id, "lines": len(lines)},
    )
    db.commit()
    return template(new.id, db, principal, "all")


class LineFixIn(BaseModel):
    field: str = Field(
        pattern="^(rate|area_type|surface|coats|min_kg_sqm|dft_mm|city|on_date|template_id|hidden|margin_percent)$"
    )
    value: Any = None
    reason: str = Field(min_length=5, max_length=1000)


@router.put("/lines/{lid}")
def fix_line(
    lid: int, body: LineFixIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    """A wrong extracted value put right, with the reason (kept, and shown)."""
    ln = db.get(KnowledgeLine, lid)
    if ln is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    if body.field == "margin_percent" and not _cost(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Margins are not for your role")
    old = getattr(ln, body.field)
    value = body.value
    if body.field in ("rate", "min_kg_sqm", "dft_mm", "margin_percent") and value is not None:
        value = Decimal(str(value))
    if body.field == "on_date" and value:
        value = date.fromisoformat(str(value))
    if body.field == "template_id" and value is not None:
        _template(db, int(value))
    _fix(db, principal, "line", ln.id, body.field, old, value, body.reason)
    setattr(ln, body.field, value)
    if body.field == "rate":
        ln.rate_sqm = (
            value
            if ln.unit == "sqm"
            else (value * service.SQFT).quantize(Decimal("0.01"))
            if ln.unit in ("sqft", "sft") and value is not None
            else None
        )
    if body.field == "city":
        ln.region = service.region_of(db, value)
    ln.to_check = False
    for tid in {old, value} if body.field == "template_id" else {ln.template_id}:
        if tid:
            t = db.get(KnowledgeTemplate, int(tid))
            library.refresh(t, service.members(db, t))
    record(
        db,
        request,
        principal,
        "knowledge.fix",
        "knowledge_line",
        ln.id,
        before={body.field: jsonable_encoder(old)},
        after={body.field: jsonable_encoder(value), "reason": body.reason},
    )
    db.commit()
    return jsonable_encoder(line_out(db, ln, _cost(principal)))


def line_out(db, ln: KnowledgeLine, cost: bool) -> dict:
    f = db.get(KnowledgeFile, ln.file_id) if ln.file_id else None
    out = {
        "id": ln.id, "file": f.path if f else None, "sheet": ln.sheet, "row": ln.row, "item_no": ln.item_no, "parent_item": ln.parent_item,
        "description": ln.description, "unit": ln.unit, "qty": ln.qty, "qty_note": ln.qty_note, "rate": ln.rate, "rate_sqm": ln.rate_sqm,
        "product_make": ln.product_make, "remarks": ln.remarks, "area_type": ln.area_type, "surface": ln.surface, "coats": ln.coats,
        "min_kg_sqm": ln.min_kg_sqm, "dft_mm": ln.dft_mm, "requirements": ln.requirements, "city": ln.city, "region": ln.region,
        "on_date": ln.on_date, "folder": ln.folder, "template_id": ln.template_id, "to_check": ln.to_check, "check_note": ln.check_note,
        "source": ln.source,
    }  # fmt: skip
    if cost:
        out |= {"working": ln.working, "cost_sqm": ln.cost_sqm, "margin_percent": ln.margin_percent}
    return out


@router.get("/templates/{tid}/lines")
def template_lines(tid: int, db: DbSession, principal: CurrentPrincipal, _: View) -> list[dict]:
    t = _template(db, tid)
    return jsonable_encoder(
        [line_out(db, ln, _cost(principal)) for ln in service.members(db, t)[:500]]
    )


@router.get("/files")
def files(
    db: DbSession,
    _: View,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 500,
) -> list[dict]:
    q = select(KnowledgeFile).order_by(KnowledgeFile.path)
    if status_:
        q = q.where(KnowledgeFile.status == status_)
    return jsonable_encoder([{"id": f.id, "path": f.path, "kind": f.kind, "status": f.status, "error": f.error, "lines": f.lines,
                              "lines_with_working": f.lines_with_working, "city": f.city, "region": f.region, "place_source": f.place_source,
                              "on_date": f.on_date, "date_source": f.date_source} for f in db.scalars(q.limit(min(limit, 5000)))])  # fmt: skip


# --- a new main item from the library --------------------------------------------------------------


class ProposeIn(BaseModel):
    area_type: str | None = None
    surface: str | None = None
    coats: int | None = Field(None, ge=1, le=10)
    min_kg_sqm: Decimal | None = Field(None, ge=0, le=50)
    dft_mm: Decimal | None = Field(None, ge=0, le=20)
    protection: str | None = None
    warranty_years: int | None = Field(None, ge=0, le=50)
    brand: str | None = None
    city: str | None = Field(None, max_length=100)
    unit: str = "sqm"
    text: str | None = None


@router.post("/propose")
def propose(body: ProposeIn, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """The templates that fit, best first, with their system, products and consumption for that
    surface (cost users), the method statement, and the past rates near the place."""
    found = service.propose(db, area=body.area_type, surface=body.surface, coats=body.coats, kg=body.min_kg_sqm, dft=body.dft_mm,
                            protection=body.protection, brand=body.brand, city=body.city, unit=body.unit, text=body.text,
                            with_cost=_cost(principal))  # fmt: skip
    return jsonable_encoder({"templates": found, "region": service.region_of(db, body.city)})


def _group(db, gid: int, principal, edit: bool = False):
    from app.costing import working_routes  # noqa: PLC0415

    return working_routes._group(db, gid, principal, edit)


def place_of(db, w) -> str | None:
    """The working's place: the site's city, else the tender's or the quotation's client city."""
    from app.quotations.models import Quotation  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415
    from app.tenders.models import Tender  # noqa: PLC0415

    if w.tender_id:
        t = db.get(Tender, w.tender_id)
        site = db.scalar(select(Site).where(Site.tender_id == t.id)) if t else None
        if site and site.city:
            return site.city
        return getattr(t, "site_city", None) if t else None
    q = db.get(Quotation, w.quotation_id)
    if q is None:
        return None
    if q.site_id:
        site = db.get(Site, q.site_id)
        if site and site.city:
            return site.city
    return q.client_city


@router.get("/groups/{gid}/context")
def group_context(gid: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    g, w = _group(db, gid, principal)
    req = extract.requirements(g.name)
    return {"city": place_of(db, w), "area_type": req.area_type, "surface": g.surface or req.surface, "coats": g.coats or req.coats,
            "min_kg_sqm": g.req_min_kg_sqm, "dft_mm": g.req_dft_mm, "name": g.name}  # fmt: skip


class ApplyIn(BaseModel):
    template_id: int
    city: str | None = None
    surface: str | None = None
    coats: int | None = None
    min_kg_sqm: Decimal | None = None
    dft_mm: Decimal | None = None


@router.post("/groups/{gid}/apply")
def apply(
    gid: int, body: ApplyIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    """Fill the main item's rate working from the template (estimator and director: the working
    holds costs)."""
    from app.costing import working_routes  # noqa: PLC0415

    g, w = _group(db, gid, principal, edit=True)
    t = _template(db, body.template_id)
    out = service.fill_group(
        db,
        g,
        t,
        body.city or place_of(db, w),
        body.surface,
        body.coats,
        body.min_kg_sqm,
        body.dft_mm,
        principal.user.id,
    )
    lines = {x["key"]: x for x in working_routes.working.client_lines(db, w)}
    group = working_routes.group_out(db, g, lines, True)
    record(
        db,
        request,
        principal,
        "knowledge.apply",
        "rate_group",
        g.id,
        after={"template": t.id, "rate_sqm": str(g.rate_sqm), "gap": jsonable_encoder(out["gap"])},
    )
    db.commit()
    return jsonable_encoder(
        {
            "group": group,
            "gap": out["gap"],
            "missing_products": out["missing_products"],
            "added_products": out["added_products"],
            "template": service.template_brief(t),
        }
    )


@router.get("/groups/{gid}/gap")
def gap(gid: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    g, w = _group(db, gid, principal)
    import re  # noqa: PLC0415

    m = re.search(r"\(template (\d+)\)", g.note or "")
    if not m:
        return {"gap": None}
    t = db.get(KnowledgeTemplate, int(m.group(1)))
    return jsonable_encoder(
        {
            "gap": service.gap_to_past(db, t, g, place_of(db, w)) if t else None,
            "template": service.template_brief(t) if t else None,
        }
    )


# --- an imported client BOQ, matched -------------------------------------------------------------------


def _match_rows(
    db, rows: list[tuple[str, int, str, str | None]], city: str | None, principal
) -> list[dict]:
    out = []
    for kind, lid, desc, unit in rows:
        col = KnowledgeMatch.boq_line_id if kind == "boq" else KnowledgeMatch.quotation_line_id
        m = db.scalar(select(KnowledgeMatch).where(col == lid))
        if m is None:
            t, conf = service.match_text(db, desc, unit, city)
            m = KnowledgeMatch(
                template_id=t.id if t else None, confidence=conf, status="proposed" if t else "none"
            )
            setattr(m, "boq_line_id" if kind == "boq" else "quotation_line_id", lid)
            db.add(m)
            db.flush()
        t = db.get(KnowledgeTemplate, m.template_id) if m.template_id else None
        near = service.near_median(db, t, city) if t else (None, None)
        out.append({"match_id": m.id, "line_id": lid, "kind": kind, "description": desc, "unit": unit, "template": service.template_brief(t) if t else None,
                    "confidence": m.confidence, "status": m.status, "median_near": near[0], "median_where": near[1]})  # fmt: skip
    db.commit()
    return out


@router.get("/match/tenders/{tender_id}")
def match_tender(tender_id: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """Each line of the client's own BOQ matched to a template, with a confidence."""
    from app.tenders.models import BoqLine, Tender  # noqa: PLC0415
    from app.tenders.service import get_visible  # noqa: PLC0415

    scope = principal.permissions.get("tender.view")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to tenders")
    t: Tender = get_visible(db, tender_id, scope, principal)
    from app.costing.models import RateWorking  # noqa: PLC0415

    w = db.scalar(
        select(RateWorking)
        .where(RateWorking.tender_id == t.id)
        .order_by(RateWorking.rev_no.desc())
        .limit(1)
    )
    city = place_of(db, w) if w else getattr(t, "site_city", None)
    lines = db.scalars(
        select(BoqLine).where(BoqLine.tender_id == t.id).order_by(BoqLine.sort_order, BoqLine.id)
    ).all()
    rows = [
        ("boq", ln.id, ln.description or "", ln.unit or ln.unit_raw)
        for ln in lines
        if (ln.description or "").strip()
    ]
    return jsonable_encoder(
        {
            "tender": {"id": t.id, "code": t.code, "name": t.name},
            "city": city,
            "lines": _match_rows(db, rows, city, principal),
        }
    )


class MatchIn(BaseModel):
    template_id: int | None = None
    status: str = Field(pattern="^(accepted|changed|none)$")


@router.put("/match/{mid}")
def set_match(
    mid: int, body: MatchIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    m = db.get(KnowledgeMatch, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if body.template_id is not None:
        _template(db, body.template_id)
    m.template_id = body.template_id if body.status != "none" else None
    m.status, m.by = body.status, principal.user.id
    record(
        db, request, principal, "knowledge.match", "knowledge_match", m.id, after=body.model_dump()
    )
    db.commit()
    return {"id": m.id, "status": m.status, "template_id": m.template_id}


@router.post("/learn/workings/{wid}")
def learn(wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit) -> dict:
    """The user marks a BOQ final: its workings are added to the library as new evidence."""
    from app.costing import working_routes  # noqa: PLC0415

    w = working_routes._working(db, wid, principal)
    n = service.learn(db, w, place_of(db, w))
    record(db, request, principal, "knowledge.learn", "rate_working", w.id, after={"lines": n})
    db.commit()
    return {"lines": n}


class SettingsIn(BaseModel):
    regions: dict[str, list[str]] | None = None
    old_after_months: int | None = Field(None, ge=1, le=120)


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    s = library.settings(db)
    if body.regions is not None:
        s.regions = body.regions
    if body.old_after_months is not None:
        s.old_after_months = body.old_after_months
    record(
        db,
        request,
        principal,
        "knowledge.settings",
        "knowledge_settings",
        1,
        after=body.model_dump(exclude_unset=True),
    )
    db.commit()
    return {"regions": s.regions, "old_after_months": s.old_after_months}


def _median(values):
    return statistics.median(values) if values else None
