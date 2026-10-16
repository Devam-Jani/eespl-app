# ruff: noqa: E501  (response shapes read better unwrapped)
"""The methodology builder's API.

Permissions: methodology.view (the library, standards and methodologies; sales: those of their own
tenders and quotations, without compliance), methodology.edit (planning, estimator, director:
edit the library, import standards, build and edit), methodology.compliance (the compliance
check, the pre-bid sheet, the internal export), methodology.site (the site's methodology, stages,
pond tests and material tests: site engineers on their sites). Clients get only the exported
methodology shared with them in the portal."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.config import settings as app_settings
from app.db import DbSession
from app.execution.common import media, save_upload
from app.methodology import build as bld
from app.methodology import datasheet, export, vocab
from app.methodology import site as site_mod
from app.methodology.models import (
    ClientStandard,
    MaterialTest,
    Methodology,
    MethodologyFile,
    MethodologyItem,
    MethodologyVersion,
    MethodProduct,
    MethodSystem,
    MethodSystemChange,
    PondTest,
    PreBidQuery,
    StandardContradiction,
    StandardDocument,
    StandardRule,
)

router = APIRouter(prefix="/api/methodology", tags=["methodology"])


def record(
    db: Session,
    request: Request,
    principal: Principal,
    action: str,
    entity: str,
    entity_id,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    audit.record(
        db,
        action,
        entity,
        entity_id,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


View = Annotated[str, Depends(require_permission("methodology.view"))]
Edit = Annotated[str, Depends(require_permission("methodology.edit"))]
Compliance = Annotated[str, Depends(require_permission("methodology.compliance"))]
SiteView = Annotated[str, Depends(require_permission("methodology.site"))]


def _404(what: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def _422(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def internals(principal: Principal) -> bool:
    return "methodology.compliance" in principal.permissions


# --- the library ------------------------------------------------------------------------------------


def system_brief(s: MethodSystem) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "brand": s.brand, "system_type": s.system_type, "system_type_label": vocab.SYSTEM_LABEL.get(s.system_type or "", s.system_type),
            "elements": s.elements, "element_labels": [vocab.ELEMENT_LABEL.get(e, e) for e in s.elements], "version": s.version, "to_confirm": len(s.to_confirm or []),
            "steps": sum(len(x["steps"]) for x in s.stages), "sources": s.sources, "is_active": s.is_active, "is_demo": s.is_demo}  # fmt: skip


@router.get("/systems")
def systems(db: DbSession, _: View, element: str | None = None) -> list[dict]:
    rows = db.scalars(select(MethodSystem).order_by(MethodSystem.code))
    return [system_brief(s) for s in rows if not element or element in (s.elements or [])]


def _products_of(db: Session, s: MethodSystem) -> list[dict]:
    names = []
    for st in s.stages:
        for x in st["steps"]:
            for n in x.get("products") or []:
                if n not in names:
                    names.append(n)
    out = []
    for n in names:
        p = db.scalar(select(MethodProduct).where(MethodProduct.name == n))
        out.append(product_out(p) if p else {"name": n, "values": {}, "datasheet": None})
    return out


def product_out(p: MethodProduct) -> dict:
    return {"id": p.id, "name": p.name, "brand": p.brand, "kind": p.kind, "product_id": p.product_id, "values": p.values, "standards": p.standards,
            "datasheet": p.datasheet_name, "source": p.source, "missing": [k for k in ("elongation", "tensile", "adhesion", "dft", "coverage", "pot_life") if k not in (p.values or {})]}  # fmt: skip


@router.get("/systems/{sid}")
def system_detail(sid: int, db: DbSession, _: View) -> dict:
    s = db.get(MethodSystem, sid)
    if s is None:
        raise _404("System not found")
    from app.knowledge.models import KnowledgeTemplate

    templates = [
        {"id": t.id, "name": t.name, "lines": t.lines_count, "median_rate": t.median_rate}
        for t in db.scalars(
            select(KnowledgeTemplate).where(KnowledgeTemplate.id.in_(s.template_ids or [0]))
        )
    ]
    changes = [
        {
            "version": c.version,
            "reason": c.reason,
            "changes": [{"field": x["field"]} for x in c.changes],
            "at": c.changed_at,
            "by": c.changed_by,
        }
        for c in db.scalars(
            select(MethodSystemChange)
            .where(MethodSystemChange.system_id == s.id)
            .order_by(MethodSystemChange.version.desc())
        )
    ]
    return {**system_brief(s), "conditions": s.conditions, "why": s.why, "competing": s.competing, "stages": s.stages, "hold_points": s.hold_points, "tests": s.tests,
            "checklist": s.checklist, "guarantee_years": s.guarantee_years, "boq_description": s.boq_description, "measurement_rule": s.measurement_rule, "specs": s.specs,
            "to_confirm_list": s.to_confirm, "fixes": s.fixes, "templates": templates, "products": _products_of(db, s), "changes": changes}  # fmt: skip


class SystemEdit(BaseModel):
    change: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/systems/{sid}")
def edit_system(
    sid: int,
    body: SystemEdit,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    s = db.get(MethodSystem, sid)
    if s is None:
        raise _404("System not found")
    try:
        row = bld.library_edit(db, s, body.change, body.reason, principal.user)
    except ValueError as e:
        raise _422(str(e)) from e
    record(
        db,
        request,
        principal,
        "methodology.system.edit",
        "method_system",
        s.id,
        after={
            "version": s.version,
            "reason": body.reason,
            "fields": [c["field"] for c in row.changes],
        },
    )
    db.commit()
    return system_detail(sid, db, "all")


@router.get("/products")
def products(db: DbSession, _: View) -> list[dict]:
    return [product_out(p) for p in db.scalars(select(MethodProduct).order_by(MethodProduct.name))]


class ProductEdit(BaseModel):
    values: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/products/{pid}")
def edit_product(
    pid: int,
    body: ProductEdit,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    p = db.get(MethodProduct, pid)
    if p is None:
        raise _404("Product not found")
    before = dict(p.values or {})
    vals = dict(before)
    for k, v in body.values.items():
        if v in (None, ""):
            vals.pop(k, None)
            continue
        lim = vocab.limit_of(str(v), k)
        vals[k] = {
            "value": str(v),
            "num": lim.num if lim else None,
            "op": lim.op if lim else None,
            "unit": lim.unit if lim else "",
            "source": f"typed by {principal.user.full_name}: {body.reason}",
        }
    p.values = vals
    record(
        db,
        request,
        principal,
        "methodology.product.edit",
        "method_product",
        p.id,
        before=before,
        after=vals,
    )
    db.commit()
    return product_out(p)


@router.post("/products/{pid}/datasheet")
async def upload_datasheet(
    pid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
    file: Annotated[UploadFile, File()],
) -> dict:
    p = db.get(MethodProduct, pid)
    if p is None:
        raise _404("Product not found")
    rel, name = await save_upload(file, "methodology/datasheets")
    values, standards = datasheet.read_values(datasheet.text_of(media(rel)), source=name)
    p.values = {**(p.values or {}), **values}
    p.standards = sorted(set(p.standards or []) | set(standards))
    p.datasheet_path, p.datasheet_name, p.source = "media:" + rel, name, f"data sheet {name}"
    record(
        db,
        request,
        principal,
        "methodology.product.datasheet",
        "method_product",
        p.id,
        after={"file": name, "values": list(values)},
    )
    db.commit()
    return product_out(p)


@router.get("/products/{pid}/datasheet")
def get_datasheet(pid: int, db: DbSession, _: View) -> FileResponse:
    p = db.get(MethodProduct, pid)
    if p is None or not p.datasheet_path:
        raise _404("No data sheet")
    path = (
        media(p.datasheet_path[6:])
        if p.datasheet_path.startswith("media:")
        else Path(app_settings.data_dir) / p.datasheet_path
    )
    if not path.exists():
        raise _404("The data sheet file is not there")
    return FileResponse(path, filename=p.datasheet_name or path.name, media_type="application/pdf")


# --- client standards ---------------------------------------------------------------------------------


def rule_out(r: StandardRule) -> dict:
    d = r.document
    return {"id": r.id, "element": r.element, "element_label": r.element_label, "condition_label": r.condition_label, "condition": r.condition,
            "system_type": r.system_type, "system_type_label": vocab.SYSTEM_LABEL.get(r.system_type or "", r.system_type), "system_text": r.system_text,
            "required_types": [{"where": w, "type": t, "label": vocab.SYSTEM_LABEL.get(t, t)} for w, t in bld.required_types(r)],
            "min_specs": r.min_specs, "makes": r.makes, "tests": r.tests, "hold_points": r.hold_points, "checklist": r.checklist, "options_evaluated": r.options_evaluated,
            "guarantee_years": r.guarantee_years, "boq_wording": r.boq_wording, "measurement": r.measurement, "page": r.page, "confidence": r.confidence, "status": r.status,
            "check_note": r.check_note, "sop": {"id": d.id, "sop_no": d.sop_no, "revision": d.revision, "date": d.issue_date, "file": d.file_name, "format": d.fmt} if d else None}  # fmt: skip


@router.get("/standards")
def standards(db: DbSession, _: View) -> list[dict]:
    return [{"id": s.id, "name": s.name, "client_name": s.client_name, "rules": len(s.rules), "to_check": sum(1 for r in s.rules if r.status == "to_check"),
             "approved_makes": s.approved_makes, "guarantee_years": s.guarantee_years, "is_demo": s.is_demo} for s in db.scalars(select(ClientStandard).order_by(ClientStandard.name))]  # fmt: skip


@router.get("/standards/{sid}")
def standard_detail(sid: int, db: DbSession, _: View) -> dict:
    s = db.get(ClientStandard, sid)
    if s is None:
        raise _404("Standard not found")
    docs = list(
        db.scalars(
            select(StandardDocument)
            .where(StandardDocument.standard_id == s.id)
            .order_by(StandardDocument.file_name)
        )
    )
    contra = list(
        db.scalars(
            select(StandardContradiction)
            .where(StandardContradiction.standard_id == s.id)
            .order_by(StandardContradiction.id)
        )
    )
    return {"id": s.id, "name": s.name, "client_name": s.client_name, "source": s.source, "approved_makes": s.approved_makes, "guarantee_years": s.guarantee_years, "report": s.report,
            "documents": [{"id": d.id, "sop_no": d.sop_no, "revision": d.revision, "date": d.issue_date, "title": d.title, "file": d.file_name, "format": d.fmt, "pages": d.pages, "element": d.element,
                           "rules": sum(1 for r in s.rules if r.document_id == d.id)} for d in docs],
            "rules": [rule_out(r) for r in s.rules],
            "contradictions": [{"id": c.id, "topic": c.topic, "element": c.element, "values": c.values, "sop_no": c.document.sop_no if c.document else None, "file": c.document.file_name if c.document else None} for c in contra]}  # fmt: skip


class RuleEdit(BaseModel):
    status: Literal["ok", "to_check"] | None = None
    system_type: str | None = None
    condition: dict[str, Any] | None = None
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/rules/{rid}")
def edit_rule(
    rid: int, body: RuleEdit, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    r = db.get(StandardRule, rid)
    if r is None:
        raise _404("Rule not found")
    before = {"status": r.status, "system_type": r.system_type, "condition": r.condition}
    if body.status:
        r.status = body.status
        r.confidence = "high" if body.status == "ok" else r.confidence
    if body.system_type is not None:
        r.system_type = body.system_type
    if body.condition is not None:
        r.condition = body.condition
    r.check_note = "; ".join(
        filter(None, [r.check_note, f"{principal.user.full_name}: {body.reason}"])
    )
    record(
        db,
        request,
        principal,
        "methodology.rule.edit",
        "standard_rule",
        r.id,
        before=before,
        after={**body.model_dump()},
    )
    db.commit()
    return rule_out(r)


@router.get("/documents/{did}/file")
def sop_file(did: int, db: DbSession, _: Compliance) -> FileResponse:
    d = db.get(StandardDocument, did)
    if d is None:
        raise _404("Document not found")
    s = db.get(ClientStandard, d.standard_id)
    root = Path(app_settings.data_dir) / "methodology"
    hits = [p for p in root.rglob(d.file_name)] if root.exists() else []
    if not hits:
        raise _404("The SOP file is not in data/methodology")
    return FileResponse(
        hits[0],
        filename=d.file_name,
        media_type="application/pdf" if d.fmt != "xlsx" else None,
        headers={"X-Standard": s.name if s else ""},
    )


class Link(BaseModel):
    standard_id: int | None


@router.put("/tenders/{tid}/standard")
def link_tender(
    tid: int, body: Link, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    from app.tenders.models import Tender

    t = db.get(Tender, tid)
    if t is None:
        raise _404("Tender not found")
    t.client_standard_id = body.standard_id
    record(
        db,
        request,
        principal,
        "methodology.standard.link",
        "tender",
        t.id,
        after={"standard_id": body.standard_id},
    )
    db.commit()
    return {"tender_id": t.id, "standard_id": t.client_standard_id}


@router.put("/quotations/{qid}/standard")
def link_quotation(
    qid: int, body: Link, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    from app.quotations.models import Quotation

    q = db.get(Quotation, qid)
    if q is None:
        raise _404("Quotation not found")
    q.client_standard_id = body.standard_id
    record(
        db,
        request,
        principal,
        "methodology.standard.link",
        "quotation",
        q.id,
        after={"standard_id": body.standard_id},
    )
    db.commit()
    return {"quotation_id": q.id, "standard_id": q.client_standard_id}


# --- methodologies ------------------------------------------------------------------------------------


def _visible(db: Session, mid: int, scope: str, principal: Principal) -> Methodology:
    m = db.get(Methodology, mid)
    if m is None:
        raise _404("Methodology not found")
    if scope == "all":
        return m
    uid = principal.user.id
    from app.quotations.models import Quotation
    from app.tenders.models import Tender

    q = db.get(Quotation, m.quotation_id) if m.quotation_id else None
    t = db.get(Tender, m.tender_id) if m.tender_id else None
    if (
        (q and q.salesperson_id == uid)
        or (t and (t.owner_id == uid or any(x.user_id == uid for x in t.members)))
        or m.created_by == uid
    ):
        return m
    raise _404("Methodology not found")


def item_out(db: Session, it: MethodologyItem, full: bool) -> dict:
    system = db.get(MethodSystem, it.system_id) if it.system_id else None
    rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
    out = {"id": it.id, "name": it.name, "element": it.element, "element_label": vocab.ELEMENT_LABEL.get(it.element or "", it.element), "qty": it.qty, "unit": it.unit,
           "places": it.places, "conditions": {k: v for k, v in (it.conditions or {}).items() if not k.startswith("_")}, "missing": (it.conditions or {}).get("_missing", []),
           "system": system_brief(system) if system else None, "options": [system_brief(s) for s in (db.get(MethodSystem, i) for i in it.option_ids or []) if s],
           "reason": it.reason, "stages": it.stages, "edits": it.edits, "rule": rule_out(rule) if rule and full else ({"id": rule.id, "condition_label": rule.condition_label} if rule else None),
           "rule_note": it.rule_note if full else None, "make_choice": it.make_choice}  # fmt: skip
    if full:
        out["compliance"] = it.compliance
    return out


def methodology_out(db: Session, m: Methodology, principal: Principal) -> dict:
    full = internals(principal)
    files = db.scalars(
        select(MethodologyFile)
        .where(MethodologyFile.methodology_id == m.id)
        .order_by(MethodologyFile.id.desc())
    )
    out = {"id": m.id, "code": m.code, "title": m.title, "tender_id": m.tender_id, "quotation_id": m.quotation_id, "standard_id": m.standard_id, "site_id": m.site_id,
           "brand": m.brand, "revision": m.revision, "version": m.version, "status": m.status, "is_demo": m.is_demo,
           "items": [item_out(db, it, full) for it in m.items],
           "files": [{"id": f.id, "kind": f.kind, "audience": f.audience, "file_name": f.file_name, "version": f.version, "revision": f.revision, "size": f.size_bytes, "at": f.created_at}
                     for f in files if full or f.audience == "client"]}  # fmt: skip
    if full:
        tot = {
            k: sum((it.compliance or {}).get(k, 0) for it in m.items)
            for k in ("green", "red", "confirm")
        }
        out["compliance"] = tot
        out["prebid"] = [
            prebid_out(q)
            for q in db.scalars(
                select(PreBidQuery)
                .where(PreBidQuery.methodology_id == m.id)
                .order_by(PreBidQuery.kind, PreBidQuery.id)
            )
        ]
    return out


def prebid_out(q: PreBidQuery) -> dict:
    return {
        "id": q.id,
        "item_id": q.item_id,
        "kind": q.kind,
        "text": q.text,
        "reference": q.reference,
        "status": q.status,
        "answer": q.answer,
    }


@router.get("/methodologies")
def list_methodologies(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    tender_id: int | None = None,
    quotation_id: int | None = None,
) -> list[dict]:
    q = select(Methodology).order_by(Methodology.id.desc())
    if tender_id:
        q = q.where(Methodology.tender_id == tender_id)
    if quotation_id:
        q = q.where(Methodology.quotation_id == quotation_id)
    out = []
    for m in db.scalars(q.limit(200)):
        try:
            _visible(db, m.id, scope, principal)
        except HTTPException:
            continue
        row = {
            "id": m.id,
            "code": m.code,
            "title": m.title,
            "tender_id": m.tender_id,
            "quotation_id": m.quotation_id,
            "revision": m.revision,
            "version": m.version,
            "items": len(m.items),
            "is_demo": m.is_demo,
        }
        if internals(principal):
            row["compliance"] = {
                k: sum((it.compliance or {}).get(k, 0) for it in m.items)
                for k in ("green", "red", "confirm")
            }
        out.append(row)
    return out


class BuildIn(BaseModel):
    tender_id: int | None = None
    quotation_id: int | None = None
    standard_id: int | None = None
    brand: str | None = "Bronco"
    title: str | None = None
    by_hand: dict[str, dict[str, Any]] = {}


def groups_for(
    db: Session, tender_id: int | None, quotation_id: int | None, user_id
) -> tuple[list[dict], int]:
    """The main items of the BOQ: the rate working's groups (suggested when there are none)."""
    from app.costing import working
    from app.tenders.models import BoqLine, Tender

    if tender_id:
        t = db.get(Tender, tender_id)
        if t is None:
            raise _404("Tender not found")
        w = working.for_tender(db, t, user_id)
        rev = t.revision
    else:
        from app.quotations.models import Quotation

        q = db.get(Quotation, quotation_id)
        if q is None:
            raise _404("Quotation not found")
        w = working.for_quotation(db, q, user_id)
        rev = q.revision
    if not w.groups:
        working.suggest(db, w, user_id)
        db.flush()
        db.refresh(w)
    out = []
    for g in w.groups:
        ids = [gl.boq_line_id for gl in g.lines if gl.boq_line_id]
        lines = list(
            db.scalars(
                select(BoqLine)
                .where(BoqLine.id.in_(ids or [0]))
                .order_by(BoqLine.sort_order, BoqLine.id)
            )
        )
        # one item per element: a group priced as one (an OHWT and a UG tank) still has two
        # client rules, two methods
        by_el: dict[str | None, list] = {}
        for ln in lines:
            by_el.setdefault(
                vocab.element_of(ln.description.split(" — ")[0])
                or vocab.element_of(ln.description),
                [],
            ).append(ln)
        parts = list(by_el.values()) if len(by_el) > 1 else [lines]
        for part in parts:
            qty = sum((Decimal(ln.qty or 0) for ln in part), Decimal(0)) or None
            heads = list(dict.fromkeys(ln.description.split(" — ")[0].strip() for ln in part))
            name = (", ".join(heads) if all(len(h) < 60 for h in heads) else g.name)[:200]
            out.append({"name": name, "rate_group_id": g.id, "boq_line_ids": [ln.id for ln in part], "qty": qty, "unit": part[0].unit if part else None,
                        "text": " ".join(ln.description for ln in part)[:4000]})  # fmt: skip
    return out, rev


@router.post("/methodologies")
def create_methodology(
    body: BuildIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    if not (body.tender_id or body.quotation_id):
        raise _422("Build it for a tender or a quotation")
    groups, rev = groups_for(db, body.tender_id, body.quotation_id, principal.user.id)
    std_id = body.standard_id
    if std_id is None and body.tender_id:
        from app.tenders.models import Tender

        std_id = db.get(Tender, body.tender_id).client_standard_id
    m = Methodology(code=bld.new_code(db), title=body.title or "Methodology", tender_id=body.tender_id, quotation_id=body.quotation_id, standard_id=std_id, brand=body.brand,
                    revision=rev, created_by=principal.user.id)  # fmt: skip
    db.add(m)
    db.flush()
    bld.build(db, m, groups, None, body.by_hand)
    bld.save_version(db, m, "built", principal.user.id)
    record(
        db,
        request,
        principal,
        "methodology.build",
        "methodology",
        m.id,
        after={"code": m.code, "items": len(m.items)},
    )
    db.commit()
    db.refresh(m)
    return methodology_out(db, m, principal)


@router.get("/methodologies/{mid}")
def get_methodology(mid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    return methodology_out(db, _visible(db, mid, scope, principal), principal)


@router.post("/methodologies/{mid}/drawing")
async def read_drawing(
    mid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
    file: Annotated[UploadFile, File()],
) -> dict:
    """A drawing (DWG / DXF) read for the conditions: toilet sizes, sunk depths, tanks."""
    from app.execution.common import CAD_TYPES

    m = _visible(db, mid, "all", principal)
    rel, name = await save_upload(file, f"methodology/{m.code}/drawings", CAD_TYPES)
    try:
        got = bld.read_drawing(media(rel), name)
    except Exception as e:  # noqa: BLE001  (an unreadable drawing is said as it is)
        raise _422(f"The drawing could not be read: {e}") from e
    apply_places(db, m, got["places"])
    record(
        db,
        request,
        principal,
        "methodology.drawing",
        "methodology",
        m.id,
        after={"file": name, "places": len(got["places"]), "repairs": got["repairs"]},
    )
    db.commit()
    return {
        "file": name,
        "texts": got["texts"],
        "repairs": got["repairs"],
        "places": len(got["places"]),
        "methodology": methodology_out(db, m, principal),
    }


def apply_places(db: Session, m: Methodology, places: list[dict]) -> None:
    std = db.get(ClientStandard, m.standard_id) if m.standard_id else None
    for it in list(m.items):
        mine = [p for p in places if p["element"] == it.element]
        if not mine:
            continue
        bld.set_places(it, mine)
        for x in bld.split_toilets(db, m, it):
            db.flush()
            bld.choose(db, m, x, std)
    db.flush()
    db.refresh(m)
    bld.refresh_queries(db, m)


class ConditionsIn(BaseModel):
    values: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/items/{iid}/conditions")
def set_conditions(
    iid: int,
    body: ConditionsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    it = db.get(MethodologyItem, iid)
    if it is None:
        raise _404("Item not found")
    m = db.get(Methodology, it.methodology_id)
    bld.save_version(db, m, f"{it.name}: conditions — {body.reason}", principal.user.id)
    conds = {k: v for k, v in (it.conditions or {}).items() if k != "_missing"}
    for k, v in body.values.items():
        if v is None:
            conds.pop(k, None)
        else:
            conds[k] = {
                "value": v,
                "source": f"by hand ({principal.user.full_name}): {body.reason}",
            }
    it.conditions = conds
    bld.choose(db, m, it, db.get(ClientStandard, m.standard_id) if m.standard_id else None)
    bld.refresh_queries(db, m)
    record(
        db,
        request,
        principal,
        "methodology.conditions",
        "methodology_item",
        it.id,
        after=body.model_dump(),
    )
    db.commit()
    return methodology_out(db, m, principal)


class SystemPick(BaseModel):
    system_id: int
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/items/{iid}/system")
def pick_system(
    iid: int,
    body: SystemPick,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    it = db.get(MethodologyItem, iid)
    s = db.get(MethodSystem, body.system_id)
    if it is None or s is None:
        raise _404("Item or system not found")
    m = db.get(Methodology, it.methodology_id)
    bld.save_version(db, m, f"{it.name}: system {s.code} — {body.reason}", principal.user.id)
    rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
    old = it.system_id
    it.system_id = s.id
    it.option_ids = [
        x for x in ([old] if old and old != s.id else []) + (it.option_ids or []) if x != s.id
    ][:2]
    it.reason = f"{body.reason} (chosen by {principal.user.full_name})"
    it.stages = bld.stages_for(s, rule, it)
    it.make_choice = None
    it.compliance = bld.check(
        db, it, db.get(ClientStandard, m.standard_id) if m.standard_id else None, rule, s
    )
    bld.refresh_queries(db, m)
    record(
        db,
        request,
        principal,
        "methodology.system",
        "methodology_item",
        it.id,
        after={"system": s.code, "reason": body.reason},
    )
    db.commit()
    return methodology_out(db, m, principal)


class StepEdit(BaseModel):
    stage: int
    step: int | None = None
    text: str | None = None
    product: str | None = None
    consumption: str | None = None
    coats: int | None = None
    wait: str | None = None
    scope: Literal["ours", "client"] | None = None
    remove: bool = False
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/items/{iid}/steps")
def edit_step(
    iid: int, body: StepEdit, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    it = db.get(MethodologyItem, iid)
    if it is None:
        raise _404("Item not found")
    m = db.get(Methodology, it.methodology_id)
    change = {
        k: v
        for k, v in body.model_dump(exclude={"stage", "step", "reason"}).items()
        if v not in (None, False) or k == "remove" and v
    }
    if not change.get("remove") and body.step is None and not body.text:
        raise _422("Write the step")
    try:
        bld.edit_step(db, m, it, body.stage, body.step, change, body.reason, principal.user)
    except ValueError as e:
        raise _422(str(e)) from e
    record(
        db,
        request,
        principal,
        "methodology.step",
        "methodology_item",
        it.id,
        after=body.model_dump(),
    )
    db.commit()
    return methodology_out(db, m, principal)


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/items/{iid}/to-library")
def to_library(
    iid: int, body: Reason, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit
) -> dict:
    it = db.get(MethodologyItem, iid)
    if it is None:
        raise _404("Item not found")
    try:
        s = bld.to_library(db, it, body.reason, principal.user)
    except ValueError as e:
        raise _422(str(e)) from e
    record(
        db,
        request,
        principal,
        "methodology.to_library",
        "method_system",
        s.id,
        after={"version": s.version, "reason": body.reason},
    )
    db.commit()
    return system_detail(s.id, db, "all")


class MakeChoice(BaseModel):
    choice: Literal["approved", "keep"]
    reason: str = Field(min_length=3, max_length=2000)


@router.put("/items/{iid}/make")
def make_choice(
    iid: int,
    body: MakeChoice,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Compliance,
    __: Edit,
) -> dict:
    it = db.get(MethodologyItem, iid)
    if it is None:
        raise _404("Item not found")
    m = db.get(Methodology, it.methodology_id)
    it.make_choice = body.choice
    bld.recheck(db, m)
    record(
        db,
        request,
        principal,
        "methodology.make",
        "methodology_item",
        it.id,
        after=body.model_dump(),
    )
    db.commit()
    return methodology_out(db, m, principal)


@router.post("/methodologies/{mid}/recheck")
def recheck(mid: int, db: DbSession, principal: CurrentPrincipal, _: Compliance) -> dict:
    m = _visible(db, mid, "all", principal)
    bld.recheck(db, m)
    db.commit()
    return methodology_out(db, m, principal)


class PrebidEdit(BaseModel):
    status: Literal["open", "sent", "answered"]
    answer: str | None = None


@router.put("/prebid/{qid}")
def edit_prebid(
    qid: int,
    body: PrebidEdit,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Compliance,
) -> dict:
    q = db.get(PreBidQuery, qid)
    if q is None:
        raise _404("Query not found")
    q.status, q.answer = body.status, body.answer
    record(
        db, request, principal, "methodology.prebid", "prebid_query", q.id, after=body.model_dump()
    )
    db.commit()
    return prebid_out(q)


@router.get("/methodologies/{mid}/versions")
def versions(mid: int, db: DbSession, principal: CurrentPrincipal, _: Compliance) -> list[dict]:
    m = _visible(db, mid, "all", principal)
    return [
        {
            "version": v.version,
            "revision": v.revision,
            "reason": v.reason,
            "at": v.created_at,
            "by": v.created_by,
        }
        for v in db.scalars(
            select(MethodologyVersion)
            .where(MethodologyVersion.methodology_id == m.id)
            .order_by(MethodologyVersion.version.desc())
        )
    ]


# --- exports and attaching --------------------------------------------------------------------------------


class ExportIn(BaseModel):
    audience: Literal["client", "internal"] = "client"


@router.post("/methodologies/{mid}/export")
def export_files(
    mid: int,
    body: ExportIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> list[dict]:
    m = _visible(db, mid, scope, principal)
    if body.audience == "internal" and not internals(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: methodology.compliance")
    made = export.issue(db, m, body.audience, principal.user.id)
    record(
        db,
        request,
        principal,
        "methodology.export",
        "methodology",
        m.id,
        after={"files": [f.file_name for f in made]},
    )
    db.commit()
    return [
        {"id": f.id, "kind": f.kind, "audience": f.audience, "file_name": f.file_name} for f in made
    ]


@router.get("/files/{fid}")
def get_file(fid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> FileResponse:
    f = db.get(MethodologyFile, fid)
    if f is None:
        raise _404("File not found")
    _visible(db, f.methodology_id, scope, principal)
    if f.audience == "internal" and not internals(principal):
        raise _404("File not found")
    if not media(f.path).exists():
        raise _404("File not found")
    return FileResponse(media(f.path), filename=f.file_name)


class AttachIn(BaseModel):
    quotation_id: int


@router.post("/methodologies/{mid}/attach")
def attach(
    mid: int,
    body: AttachIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """The methodology goes with a quotation (sales: their own): its client copy is issued with it."""
    from app.quotations import service as qsvc

    m = _visible(db, mid, scope, principal)
    qscope = principal.permissions.get("quotation.edit")
    if qscope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: quotation.edit")
    q = qsvc.get_visible(db, body.quotation_id, qscope, principal)
    m.quotation_id = q.id
    made = export.issue(db, m, "client", principal.user.id)
    record(
        db,
        request,
        principal,
        "methodology.attach",
        "quotation",
        q.id,
        after={"methodology": m.code, "files": [f.file_name for f in made]},
    )
    db.commit()
    return methodology_out(db, m, principal)


class HandoverIn(BaseModel):
    site_id: int | None = None


@router.post("/methodologies/{mid}/handover")
def handover(
    mid: int,
    body: HandoverIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Edit,
) -> dict:
    m = _visible(db, mid, "all", principal)
    out = site_mod.handover(db, m, body.site_id, principal.user.id)
    if body.site_id:
        export.share_with_client(db, m, body.site_id, principal.user.id)
    record(
        db,
        request,
        principal,
        "methodology.handover",
        "methodology",
        m.id,
        after={**out, "site_id": body.site_id},
    )
    db.commit()
    return out


# --- the site ------------------------------------------------------------------------------------------------


def _site(db: Session, site_id: int, scope: str, principal: Principal):
    from app.sites import service as site_service

    return site_service.get_visible(db, site_id, scope, principal)


@router.get("/sites/{site_id}")
def site_methodology(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteView
) -> dict:
    site = _site(db, site_id, scope, principal)
    from app.sites.models import StageTemplate

    ms = list(
        db.scalars(
            select(Methodology)
            .where(Methodology.site_id == site.id)
            .order_by(Methodology.id.desc())
        )
    )
    items = []
    for m in ms[:1]:
        for it in m.items:
            t = db.get(StageTemplate, it.stage_template_id) if it.stage_template_id else None
            items.append({"id": it.id, "name": it.name, "element": it.element, "system": (db.get(MethodSystem, it.system_id).name if it.system_id else None), "stages": it.stages,
                          "stage_template": {"id": t.id, "name": t.name, "steps": [{"name": s.name, "hold_point": s.hold_point, "checklist_template_id": s.checklist_template_id, "weight": s.weight_percent} for s in t.steps]} if t else None})  # fmt: skip
    pond = [
        pond_out(p)
        for p in db.scalars(
            select(PondTest).where(PondTest.site_id == site.id).order_by(PondTest.id)
        )
    ]
    mats = [
        mat_out(x)
        for x in db.scalars(
            select(MaterialTest).where(MaterialTest.site_id == site.id).order_by(MaterialTest.id)
        )
    ]
    return {
        "site_id": site.id,
        "methodology": {"id": ms[0].id, "code": ms[0].code, "title": ms[0].title} if ms else None,
        "items": items,
        "pond_tests": pond,
        "material_tests": mats,
    }


def pond_out(p: PondTest) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "required_hours": p.required_hours, "depth_mm": p.depth_mm, "started_at": p.started_at, "ended_at": p.ended_at,
            "hours": site_mod.pond_hours(p), "drop_mm": p.drop_mm, "result": p.result, "photos": p.photos, "remark": p.remark, "reference": p.reference}  # fmt: skip


def mat_out(x: MaterialTest) -> dict:
    return {
        "id": x.id,
        "product_name": x.product_name,
        "tests": x.tests,
        "frequency": x.frequency,
        "grn_id": x.grn_id,
        "status": x.status,
        "sampled_on": x.sampled_on,
        "result_note": x.result_note,
        "reference": x.reference,
    }


class PondIn(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None
    drop_mm: Decimal | None = None
    result: Literal["pending", "pass", "fail"] | None = None
    remark: str | None = None


@router.put("/pond-tests/{pid}")
def edit_pond(
    pid: int,
    body: PondIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    p = db.get(PondTest, pid)
    if p is None:
        raise _404("Pond test not found")
    _site(db, p.site_id, scope, principal)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    if p.result == "pass":
        hours = site_mod.pond_hours(p)
        if hours is None or hours < p.required_hours:
            raise _422(
                f"The test needs {p.required_hours} hours from start to end before it passes"
            )
        if not p.photos:
            raise _422("Add the photos (start and end levels) before it passes")
    record(
        db,
        request,
        principal,
        "methodology.pond",
        "pond_test",
        p.id,
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return pond_out(p)


@router.post("/pond-tests/{pid}/photos")
async def pond_photo(
    pid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
    file: Annotated[UploadFile, File()],
) -> dict:
    p = db.get(PondTest, pid)
    if p is None:
        raise _404("Pond test not found")
    _site(db, p.site_id, scope, principal)
    rel, name = await save_upload(file, f"methodology/pond/{p.site_id}")
    p.photos = (p.photos or []) + [{"path": rel, "name": name, "at": datetime.now().isoformat()}]
    db.commit()
    return pond_out(p)


class MatIn(BaseModel):
    status: Literal["planned", "due", "sampled", "pass", "fail"]
    sampled_on: Any = None
    result_note: str | None = None


@router.put("/material-tests/{tid}")
def edit_material(
    tid: int,
    body: MatIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    x = db.get(MaterialTest, tid)
    if x is None:
        raise _404("Material test not found")
    _site(db, x.site_id, scope, principal)
    x.status, x.result_note = body.status, body.result_note
    if body.sampled_on:
        x.sampled_on = datetime.fromisoformat(str(body.sampled_on)).date()
    record(
        db,
        request,
        principal,
        "methodology.material_test",
        "material_test",
        x.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return mat_out(x)


@router.get("/elements")
def elements(_: View) -> dict:
    return {"elements": [{"key": k, "label": label} for k, label, _p in vocab.ELEMENTS], "system_types": [{"key": k, "label": label} for k, label, _p in vocab.SYSTEM_TYPES],
            "properties": [{"key": k, "label": label, "unit": u} for k, label, u, _p in vocab.PROPERTIES]}  # fmt: skip
