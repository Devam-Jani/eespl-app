# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Quotations (/api/quotations): techno-commercial offers built from the editable libraries,
their revisions, issued Word / PDF files, follow-ups; the libraries themselves with version
history; quotation settings.

quotation.view / quotation.edit / quotation.send carry the scope (all, or own: the caller's
quotations and those of their leads); quotation.template.edit changes the libraries and saves a
quotation's text back to them. Cost and margin need tender.margin; the offer only ever prints
selling rates.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.crm.models import Lead
from app.db import DbSession
from app.execution.common import media, record, save_upload
from app.masters.models import Client, ClientContact, Product, TcClause, TcTemplateClause
from app.material import service as material
from app.models import RolePermission, User, UserRole
from app.quotations import docx_out, html_out, render
from app.quotations import library as lib
from app.quotations import service as svc
from app.quotations.markup import plain
from app.quotations.models import (
    PLACEHOLDERS,
    RATE_SOURCES,
    STAGES,
    TC_GROUP_LABELS,
    UOM_LABELS,
    UOMS,
    Letterhead,
    LetterTemplate,
    LibraryVersion,
    OfferItem,
    OfferItemLine,
    OfferLine,
    Quotation,
    QuotationFile,
    QuotationFollowUp,
    QuotationItem,
    QuotationLine,
    Reference,
    SpecBlock,
)
from app.survey import service as survey_svc
from app.survey.models import AreaType, Survey
from app.tenders.models import LOST_REASONS

router = APIRouter(prefix="/api/quotations", tags=["quotations"])
View = Annotated[str, Depends(require_permission("quotation.view"))]
TemplateEdit = Annotated[str, Depends(require_permission("quotation.template.edit"))]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SQFT_PER_SQM = Decimal("10.7639")


def _margin(principal) -> bool:
    return "tender.margin" in principal.permissions


def _send_scope(db, q: Quotation, principal) -> None:
    scope = principal.permissions.get("quotation.send")
    if (
        scope is None
        or db.scalar(svc.visible_q(scope, principal).where(Quotation.id == q.id)) is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot send or close this quotation")


# --- serialising ---------------------------------------------------------------------------------


def _line_out(ln: QuotationLine, item: QuotationItem, margin: bool) -> dict:
    out = {
        "id": ln.id,
        "offer_line_id": ln.offer_line_id,
        "library_version": ln.library_version,
        "sort_order": ln.sort_order,
        "option": ln.option,
        "offered": svc.is_offered(item, ln.option),
        "description": ln.description,
        "uom": ln.uom,
        "rate": ln.rate,
        "rate_source": ln.rate_source,
        "rate_note": ln.rate_note,
        "overridden": ln.overridden,
        "qty": ln.qty,
        "amount": svc.line_amount(ln),
        "if_required": ln.if_required,
        "client_scope": ln.client_scope,
        "system_id": ln.system_id,
        "library_item_id": ln.library_item_id,
    }
    if margin:
        out["cost_rate"] = ln.cost_rate
        out["margin_percent"] = ln.margin_percent
        if ln.cost_rate is not None and ln.rate:
            out["margin_amount"] = svc.money(Decimal(ln.rate) - Decimal(ln.cost_rate))
    return out


def _q_out(db, q: Quotation, principal) -> dict:
    margin = _margin(principal)
    perms = principal.permissions
    lead = db.get(Lead, q.lead_id) if q.lead_id else None
    head = db.get(Letterhead, q.letterhead_id) if q.letterhead_id else None
    person = db.get(User, q.salesperson_id) if q.salesperson_id else None
    revisions = db.execute(
        select(Quotation.id, Quotation.revision, Quotation.status, Quotation.quote_date)
        .where(Quotation.code == q.code)
        .order_by(Quotation.revision)
    ).all()
    files = db.scalars(
        select(QuotationFile).where(QuotationFile.quotation_id == q.id).order_by(QuotationFile.id)
    ).all()
    t = svc.totals(q)
    can_edit = (
        "quotation.edit" in perms
        and db.scalar(svc.visible_q(perms["quotation.edit"], principal).where(Quotation.id == q.id))
        is not None
    )
    can_send = (
        "quotation.send" in perms
        and db.scalar(svc.visible_q(perms["quotation.send"], principal).where(Quotation.id == q.id))
        is not None
    )
    out = {
        **{
            c: getattr(q, c)
            for c in (
                "id code revision is_latest previous_id lead_id client_id survey_id tender_id site_id letterhead_id "
                "salesperson_id client_firm client_city client_state attention project brand areas_list quote_date "
                "validity_days status lost_reason lost_note sent_at decided_at show_amounts letter_template_id opening "
                "subject body enclosures signatory_name signatory_designation terms references references_title notes"
            ).split()
        },
        "valid_until": date.fromordinal(q.quote_date.toordinal() + q.validity_days),
        "lead_code": lead.code if lead else None,
        "letterhead_name": head.name if head else None,
        "salesperson_name": person.full_name if person else None,
        "areas_list_auto": svc.areas_list(q),
        "items": [
            {
                "id": i.id,
                "offer_item_id": i.offer_item_id,
                "sort_order": i.sort_order,
                "name": i.name,
                "budget_title": i.budget_title,
                "area_type_id": i.area_type_id,
                "options": i.options,
                "option_labels": svc.option_labels(i),
                "specs": i.specs,
                "lines": [_line_out(ln, i, margin) for ln in i.lines],
                "total": next((x["total"] for x in t["items"] if x["item_id"] == i.id), None),
            }
            for i in q.items
        ],
        "total": t["total"],
        "total_option_note": t["option_note"],
        "revisions": [
            {"id": r.id, "revision": r.revision, "status": r.status, "quote_date": r.quote_date}
            for r in revisions
        ],
        "files": [
            {
                "id": f.id,
                "kind": f.kind,
                "file_name": f.file_name,
                "size_bytes": f.size_bytes,
                "created_at": f.created_at,
            }
            for f in files
        ],
        "followups": svc.followup_rows(db, quotation_code=q.code, status_=None),
        "can_edit": bool(can_edit) and q.is_latest and q.status not in svc.TERMINAL,
        "can_send": bool(can_send),
        "can_template_edit": "quotation.template.edit" in perms,
        "can_margin": margin,
    }
    return jsonable_encoder(out)


# --- lookups -------------------------------------------------------------------------------------


@router.get("/lookups")
def lookups(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    people = db.execute(
        select(User.id, User.full_name, User.job_title)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(
            RolePermission.permission_code == "quotation.edit",
            User.is_active,
            User.is_demo.is_(False),
        )
        .distinct()
        .order_by(User.full_name)
    ).all()
    items = []
    for it in db.scalars(
        select(OfferItem).where(OfferItem.is_active).order_by(OfferItem.sort_order, OfferItem.name)
    ):
        labels = sorted(
            {s.spec.option_label for s in it.specs if s.spec.option_label}
            | {
                sec["option"]
                for s in it.specs
                for sec in s.spec.sections or []
                if sec.get("option")
            }
            | {ln.option for ln in it.lines if ln.option}
        )
        items.append(
            {
                "id": it.id,
                "name": it.name,
                "area_type_id": it.area_type_id,
                "option_labels": labels,
                "needs_check": it.needs_check,
                "lines": len(it.lines),
                "specs": len(it.specs),
            }
        )
    s = svc.settings(db)
    return jsonable_encoder(
        {
            "letterheads": [
                {"id": h.id, "name": h.name, "company_name": h.company_name}
                for h in render.letterhead_options(db)
            ],
            "letters": [
                {"id": t.id, "name": t.name}
                for t in db.scalars(
                    select(LetterTemplate)
                    .where(LetterTemplate.is_active)
                    .order_by(LetterTemplate.name)
                )
            ],
            "offer_items": items,
            "lost_reasons": LOST_REASONS,
            "uoms": [{"code": u, "label": UOM_LABELS[u]} for u in UOMS],
            "rate_sources": RATE_SOURCES,
            "stages": STAGES,
            "placeholders": PLACEHOLDERS,
            "tc_groups": TC_GROUP_LABELS,
            "salespeople": [
                {"id": p.id, "full_name": p.full_name, "job_title": p.job_title} for p in people
            ],
            "area_types": [
                {"id": a.id, "name": a.name}
                for a in db.scalars(
                    select(AreaType).where(AreaType.is_active).order_by(AreaType.sort_order)
                )
            ],
            "default_validity_days": s.default_validity_days,
            "default_letterhead_id": s.default_letterhead_id,
            "me": principal.user.id,
        }
    )


@router.get("/products")
def products(db: DbSession, _: View, q: str = "") -> list[dict]:
    """Product names from the products master (they print bold in the offer)."""
    query = select(Product.id, Product.code, Product.name).where(Product.is_active)
    if q:
        query = query.where(or_(Product.name.ilike(f"%{q}%"), Product.code.ilike(f"%{q}%")))
    return [
        {"id": i, "code": c, "name": n}
        for i, c, n in db.execute(query.order_by(Product.name).limit(25))
    ]


@router.get("/tc-clauses")
def tc_clauses(db: DbSession, _: View, category: str | None = None) -> list[dict]:
    """T&C clauses to add to a quotation (the M2 library's active clauses)."""
    query = select(TcClause).where(TcClause.status == "active")
    if category:
        query = query.where(TcClause.category == category)
    return [
        {"id": c.id, "category": c.category, "text": c.text}
        for c in db.scalars(
            query.order_by(TcClause.category, TcClause.sort_order, TcClause.id).limit(500)
        )
    ]


@router.get("/media")
def library_media(path: str, _: View):
    """A library image (letterhead logo, spec block photo)."""
    if not (path.startswith("quotations/library/") or path.startswith("company/")) or ".." in path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    p = media(path)
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(p)


# --- settings ------------------------------------------------------------------------------------


class SettingsIn(BaseModel):
    default_validity_days: int | None = Field(None, ge=1, le=365)
    followup_days: list[int] | None = None
    closure_target_percent: Decimal | None = Field(None, ge=0, le=100)
    closure_targets: dict[str, Decimal] | None = None
    default_letterhead_id: int | None = None


def _settings_out(db) -> dict:
    s = svc.settings(db)
    return jsonable_encoder(
        {
            "default_validity_days": s.default_validity_days,
            "followup_days": s.followup_days,
            "closure_target_percent": s.closure_target_percent,
            "closure_targets": s.closure_targets,
            "default_letterhead_id": s.default_letterhead_id,
            "word_template": "uploaded" if s.word_template_path else "built-in",
        }
    )


@router.get("/settings")
def get_settings(db: DbSession, _: View) -> dict:
    return _settings_out(db)


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: TemplateEdit
) -> dict:
    s = svc.settings(db)
    data = body.model_dump(exclude_unset=True)
    if "followup_days" in data:
        days = sorted({int(d) for d in data["followup_days"] or []})
        if any(d < 1 or d > 365 for d in days):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Follow-up days run from 1 to 365"
            )
        data["followup_days"] = days
    if "closure_targets" in data:
        data["closure_targets"] = {
            k: float(v) for k, v in (data["closure_targets"] or {}).items() if v is not None
        }
    for k, v in data.items():
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "quotation.settings",
        "quotation_settings",
        1,
        after=jsonable_encoder(data),
    )
    db.commit()
    return _settings_out(db)


@router.post("/settings/word-template")
async def upload_word_template(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
    file: Annotated[UploadFile, File()],
) -> dict:
    """The team's restyled Word template (.docx with the Offer styles)."""
    rel, _name = await save_upload(file, "quotations/templates", extra=frozenset({".docx"}))
    try:
        from docx import Document

        Document(str(media(rel)))
    except Exception as e:  # noqa: BLE001  any unreadable file is refused the same way
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That is not a Word .docx file"
        ) from e
    svc.settings(db).word_template_path = rel
    record(
        db,
        request,
        principal,
        "quotation.word_template",
        "quotation_settings",
        1,
        after={"file": _name},
    )
    db.commit()
    return _settings_out(db)


@router.delete("/settings/word-template")
def reset_word_template(
    request: Request, db: DbSession, principal: CurrentPrincipal, _: TemplateEdit
) -> dict:
    svc.settings(db).word_template_path = None
    record(
        db,
        request,
        principal,
        "quotation.word_template",
        "quotation_settings",
        1,
        after={"file": "built-in"},
    )
    db.commit()
    return _settings_out(db)


@router.get("/settings/word-template")
def download_word_template(db: DbSession, _: View):
    rel = svc.settings(db).word_template_path
    p = media(rel) if rel and media(rel).exists() else docx_out.TEMPLATE
    if not p.exists():
        docx_out.make_template()
    return FileResponse(p, media_type=DOCX, filename="EESPL-offer-template.docx")


# --- the libraries -------------------------------------------------------------------------------

Kind = Literal["letterhead", "letter", "spec", "line", "item", "reference"]


class StepIn(BaseModel):
    text: str
    client_scope: bool = False
    if_required: bool = False


class SectionIn(BaseModel):
    heading: str = ""
    option: str | None = None
    steps: list[StepIn] = []


class ImageIn(BaseModel):
    path: str
    caption: str = ""


class LetterheadIn(BaseModel):
    name: str | None = Field(None, max_length=100)
    company_name: str | None = None
    header_text: str | None = None
    footer_text: str | None = None
    signatory_firm: str | None = None
    signatory_name: str | None = None
    signatory_designation: str | None = None
    brand: str | None = None
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    tc_template_id: int | None = None
    letter_template_id: int | None = None
    references_state: str | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


class LetterIn(BaseModel):
    name: str | None = Field(None, max_length=100)
    opening: str | None = None
    subject: str | None = None
    body: str | None = None
    enclosures: str | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


class SpecIn(BaseModel):
    title: str | None = None
    heading_prefix: str | None = None
    area_type_id: int | None = None
    system_id: int | None = None
    option_label: str | None = None
    sections: list[SectionIn] | None = None
    images: list[ImageIn] | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


class LineIn(BaseModel):
    description: str | None = None
    uom: Literal[UOMS] | None = None  # type: ignore[valid-type]
    rate_source: Literal[RATE_SOURCES] | None = None  # type: ignore[valid-type]
    system_id: int | None = None
    library_item_id: int | None = None
    default_rate: Decimal | None = Field(None, ge=0)
    if_required: bool | None = None
    client_scope: bool | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


class ItemSpecIn(BaseModel):
    spec_block_id: int


class ItemLineIn(BaseModel):
    offer_line_id: int
    option: str | None = None


class ItemIn(BaseModel):
    name: str | None = None
    area_type_id: int | None = None
    budget_title: str | None = None
    sort_order: int | None = None
    specs: list[ItemSpecIn] | None = None
    lines: list[ItemLineIn] | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


class ReferenceIn(BaseModel):
    client_name: str | None = None
    project: str | None = None
    application: str | None = None
    area_value: Decimal | None = None
    area_unit: str | None = None
    state: str | None = None
    area_type_ids: list[int] | None = None
    include: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    needs_check: bool | None = None


SCHEMAS = {
    "letterhead": LetterheadIn,
    "letter": LetterIn,
    "spec": SpecIn,
    "line": LineIn,
    "item": ItemIn,
    "reference": ReferenceIn,
}
REQUIRED = {
    "letterhead": ("name", "company_name", "signatory_firm"),
    "letter": ("name", "subject", "body"),
    "spec": ("title",),
    "line": ("description", "uom"),
    "item": ("name", "budget_title"),
    "reference": ("client_name", "project"),
}


def _lib_out(db, row) -> dict:
    data = lib.snapshot(row)
    data.update(id=row.id, version=row.version, updated_at=row.updated_at, kind=lib.kind_of(row))
    if isinstance(row, OfferItem):
        data["specs"] = [
            {
                "spec_block_id": s.spec_block_id,
                "title": s.spec.title,
                "option_label": s.spec.option_label,
                "version": s.spec.version,
            }
            for s in row.specs
        ]
        data["lines"] = [
            {
                "offer_line_id": ln.offer_line_id,
                "option": ln.option,
                "description": ln.line.description,
                "uom": ln.line.uom,
                "default_rate": ln.line.default_rate,
                "rate_source": ln.line.rate_source,
            }
            for ln in row.lines
        ]
    if getattr(row, "area_type_id", None):
        at = db.get(AreaType, row.area_type_id)
        data["area_type_name"] = at.name if at else None
    return jsonable_encoder(data)


def _lib_text(row) -> str:
    return " ".join(
        str(getattr(row, f, "") or "")
        for f in (
            "name",
            "title",
            "description",
            "client_name",
            "project",
            "application",
            "subject",
            "company_name",
            "budget_title",
        )
    )


@router.get("/library/{kind}")
def library_list(
    kind: Kind,
    db: DbSession,
    _: View,
    q: str = "",
    area_type_id: int | None = None,
    state: str | None = None,
    needs_check: bool | None = None,
    include_inactive: bool = False,
) -> list[dict]:
    model = lib.MODELS[kind]
    query = select(model)
    if not include_inactive:
        query = query.where(model.is_active)
    if needs_check is not None:
        query = query.where(model.needs_check.is_(needs_check))
    if area_type_id and hasattr(model, "area_type_id"):
        query = query.where(model.area_type_id == area_type_id)
    if area_type_id and kind == "reference":
        query = query.where(Reference.area_type_ids.any(area_type_id))
    if state and kind == "reference":
        query = query.where(func.lower(Reference.state) == state.lower())
    order = {
        "item": (OfferItem.sort_order, OfferItem.name),
        "reference": (Reference.sort_order, Reference.id),
    }.get(kind, (model.id,))
    rows = list(db.scalars(query.order_by(*order)))
    if q:
        words = q.lower().split()
        rows = [r for r in rows if all(w in plain(_lib_text(r)).lower() for w in words)]
    return [_lib_out(db, r) for r in rows]


@router.get("/library/{kind}/{entity_id}")
def library_get(kind: Kind, entity_id: int, db: DbSession, _: View) -> dict:
    row = db.get(lib.MODELS[kind], entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return _lib_out(db, row)


def _validate(db, kind: str, data: dict) -> dict:
    if kind == "letter":
        lib.check_letter(
            data.get("subject") or "", data.get("body") or "", data.get("opening") or ""
        )
    if kind == "spec" and "sections" in data:
        data["sections"] = [s if isinstance(s, dict) else s.model_dump() for s in data["sections"]]
    if kind == "spec" and "images" in data:
        data["images"] = [i if isinstance(i, dict) else i.model_dump() for i in data["images"]]
    if kind == "item":
        if "specs" in data:
            ids = [s["spec_block_id"] for s in data["specs"]]
            if len(set(ids)) != len(ids) or len(
                db.scalars(select(SpecBlock.id).where(SpecBlock.id.in_(ids))).all()
            ) != len(set(ids)):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown or repeated specification block"
                )
        if "lines" in data:
            ids = {ln["offer_line_id"] for ln in data["lines"]}
            if len(db.scalars(select(OfferLine.id).where(OfferLine.id.in_(ids))).all()) != len(ids):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown offer line")
    return data


@router.post("/library/{kind}", status_code=status.HTTP_201_CREATED)
def library_create(
    kind: Kind,
    body: dict[str, Any],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
) -> dict:
    data = SCHEMAS[kind].model_validate(body).model_dump(exclude_unset=True)
    missing = [f for f in REQUIRED[kind] if not data.get(f)]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Fill in: " + ", ".join(m.replace("_", " ") for m in missing),
        )
    data = _validate(db, kind, data)
    row = lib.MODELS[kind](created_by=principal.user.id)
    lib.apply(row, data)
    db.add(row)
    lib.save_version(db, row, "create", principal.user.id)
    record(
        db,
        request,
        principal,
        f"quotation_library.{kind}.create",
        "quotation_library",
        row.id,
        after=lib.snapshot(row),
    )
    db.commit()
    return _lib_out(db, row)


@router.put("/library/{kind}/{entity_id}")
def library_update(
    kind: Kind,
    entity_id: int,
    body: dict[str, Any],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
) -> dict:
    row = db.get(lib.MODELS[kind], entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    before = lib.snapshot(row)
    data = SCHEMAS[kind].model_validate(body).model_dump(exclude_unset=True)
    if kind == "letter":
        merged = {**before, **data}
        lib.check_letter(
            merged.get("subject") or "", merged.get("body") or "", merged.get("opening") or ""
        )
    data = _validate(db, kind, data) if kind != "letter" else data
    lib.apply(row, data)
    lib.save_version(
        db,
        row,
        "update",
        principal.user.id,
        note=body.get("note") if isinstance(body.get("note"), str) else None,
    )
    record(
        db,
        request,
        principal,
        f"quotation_library.{kind}.update",
        "quotation_library",
        row.id,
        before=before,
        after=lib.snapshot(row),
    )
    db.commit()
    return _lib_out(db, row)


@router.get("/library/{kind}/{entity_id}/versions")
def library_versions(kind: Kind, entity_id: int, db: DbSession, _: View) -> list[dict]:
    rows = db.execute(
        select(LibraryVersion, User.full_name)
        .outerjoin(User, User.id == LibraryVersion.created_by)
        .where(LibraryVersion.kind == kind, LibraryVersion.entity_id == entity_id)
        .order_by(LibraryVersion.version.desc())
    ).all()
    return jsonable_encoder(
        [
            {
                "version": v.version,
                "action": v.action,
                "note": v.note,
                "by": name,
                "at": v.created_at,
                "data": v.data,
            }
            for v, name in rows
        ]
    )


@router.post("/library/{kind}/{entity_id}/restore/{version}")
def library_restore(
    kind: Kind,
    entity_id: int,
    version: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
) -> dict:
    row = lib.restore(db, kind, entity_id, version, principal.user.id)
    record(
        db,
        request,
        principal,
        f"quotation_library.{kind}.restore",
        "quotation_library",
        entity_id,
        after={"version": version},
    )
    db.commit()
    return _lib_out(db, row)


@router.post("/library/letterhead/{entity_id}/logo")
async def letterhead_logo(
    entity_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
    file: Annotated[UploadFile, File()],
) -> dict:
    row = db.get(Letterhead, entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    rel, _name = await save_upload(file, "quotations/library")
    row.logo_path = rel
    lib.save_version(db, row, "update", principal.user.id, note="new logo")
    record(db, request, principal, "quotation_library.letterhead.logo", "quotation_library", row.id)
    db.commit()
    return _lib_out(db, row)


@router.post("/library/spec/{entity_id}/images")
async def spec_image(
    entity_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TemplateEdit,
    file: Annotated[UploadFile, File()],
    caption: str = Form(""),
) -> dict:
    row = db.get(SpecBlock, entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    rel, _name = await save_upload(file, "quotations/library")
    row.images = [*(row.images or []), {"path": rel, "caption": caption}]
    lib.save_version(db, row, "update", principal.user.id, note="image added")
    record(db, request, principal, "quotation_library.spec.image", "quotation_library", row.id)
    db.commit()
    return _lib_out(db, row)


@router.post("/library/reference/from-sites")
def references_from_sites(
    request: Request, db: DbSession, principal: CurrentPrincipal, _: TemplateEdit
) -> dict:
    n = svc.references_from_sites(db, principal.user.id)
    record(
        db,
        request,
        principal,
        "quotation_library.reference.from_sites",
        "quotation_library",
        None,
        after={"added": n},
    )
    db.commit()
    return {"added": n}


def _preview_quotation(db, kind: str, row) -> Quotation:
    """A throwaway quotation (never saved) showing one library row as it prints."""
    s = svc.settings(db)
    head = (
        row
        if kind == "letterhead"
        else (db.get(Letterhead, s.default_letterhead_id) if s.default_letterhead_id else None)
    )
    letter = (
        row
        if kind == "letter"
        else (
            db.get(LetterTemplate, head.letter_template_id)
            if head and head.letter_template_id
            else None
        )
    )
    q = Quotation(
        code="PREVIEW",
        revision=0,
        quote_date=date.today(),
        validity_days=30,
        letterhead_id=head.id if head else None,
        client_firm="Sample Builders Pvt. Ltd.",
        client_city="Ahmedabad",
        attention="Mr. Sample",
        project="Sample Residency",
        opening=letter.opening if letter and kind in ("letter", "letterhead") else "",
        subject=letter.subject if letter and kind in ("letter", "letterhead") else "",
        body=letter.body if letter and kind in ("letter", "letterhead") else "",
        enclosures=letter.enclosures if letter and kind in ("letter", "letterhead") else "",
        show_amounts=False,
        terms=[],
        references=[],
    )
    q.items = []
    rc = svc.RateContext.make(db)
    if kind == "item":
        svc.add_item(db, q, row, [], rc)
    elif kind == "spec":
        q.items.append(
            QuotationItem(
                name="Preview", budget_title="(preview)", options=[], specs=[svc.spec_copy(row)]
            )
        )
    elif kind == "line":
        item = QuotationItem(name="Preview", budget_title="(preview)", options=[], specs=[])
        ln = svc.line_copy(row, None, 0)
        svc.fill_rate(rc, ln, row)
        item.lines.append(ln)
        q.items.append(item)
    elif kind == "reference":
        q.references = [{**lib.snapshot(row), "include": True}]
    return q


@router.get("/library/{kind}/{entity_id}/preview")
def library_preview(kind: Kind, entity_id: int, db: DbSession, _: View) -> dict:
    row = db.get(lib.MODELS[kind], entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    q = _preview_quotation(db, kind, row)
    html = html_out.html(render.build(db, q), for_pdf=False)
    db.expunge_all()  # the throwaway quotation never reaches the database
    db.rollback()
    return {"html": html}


# --- quotations ----------------------------------------------------------------------------------


class ItemPick(BaseModel):
    offer_item_id: int
    options: list[str] = []


class QuotationIn(BaseModel):
    lead_id: int | None = None
    client_id: int | None = None
    survey_id: int | None = None
    letterhead_id: int | None = None
    letter_template_id: int | None = None
    salesperson_id: uuid.UUID | None = None
    client_firm: str | None = Field(None, max_length=300)
    client_city: str | None = None
    client_state: str | None = None
    attention: str | None = None
    project: str | None = Field(None, max_length=300)
    brand: str | None = None
    quote_date: date | None = None
    validity_days: int | None = Field(None, ge=1, le=365)
    items: list[ItemPick] = []
    show_amounts: bool = False


def _terms_for(db, head: Letterhead | None) -> list[dict]:
    if head is None or head.tc_template_id is None:
        return []
    rows = db.execute(
        select(TcClause)
        .join(TcTemplateClause, TcTemplateClause.clause_id == TcClause.id)
        .where(TcTemplateClause.template_id == head.tc_template_id, TcClause.status == "active")
        .order_by(TcTemplateClause.sort_order)
    ).scalars()
    return [{"clause_id": c.id, "category": c.category, "text": c.text} for c in rows]


def _references_for(db, state: str | None) -> tuple[list[dict], str]:
    query = select(Reference).where(Reference.is_active, Reference.include)
    if state:
        query = query.where(
            or_(func.lower(Reference.state) == state.lower(), Reference.state.is_(None))
        )
    rows = [
        {**lib.snapshot(r), "id": r.id}
        for r in db.scalars(query.order_by(Reference.sort_order, Reference.id))
    ]
    title = "Our Esteemed Clients for Waterproofing Projects" + (f" in {state}" if state else "")
    return rows, title


@router.post("", status_code=status.HTTP_201_CREATED)
def create_quotation(
    body: QuotationIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    scope = principal.permissions.get("quotation.edit")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot make quotations")
    s = svc.settings(db)
    lead = db.get(Lead, body.lead_id) if body.lead_id else None
    if body.lead_id and (lead is None or (scope != "all" and lead.owner_id != principal.user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    client = db.get(Client, body.client_id or (lead.client_id if lead else None) or -1)
    contact = None
    if client:
        contact = db.scalar(
            select(ClientContact)
            .where(ClientContact.client_id == client.id)
            .order_by(ClientContact.is_primary.desc(), ClientContact.id)
            .limit(1)
        )
    head = db.get(Letterhead, body.letterhead_id or s.default_letterhead_id or -1)
    letter = db.get(
        LetterTemplate, body.letter_template_id or (head.letter_template_id if head else None) or -1
    )
    if letter is None:
        letter = db.scalar(
            select(LetterTemplate)
            .where(LetterTemplate.is_active)
            .order_by(LetterTemplate.id)
            .limit(1)
        )
    firm = (
        body.client_firm
        or (client.name if client else None)
        or (lead.company or lead.contact_name if lead else None)
    )
    project = body.project or (lead.company if lead and lead.company else None) or firm
    if not firm or not project:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the client firm and the project"
        )
    salesperson = body.salesperson_id or (lead.owner_id if lead else None) or principal.user.id
    if scope != "all" and salesperson != principal.user.id:
        salesperson = principal.user.id  # sales make their own quotations
    state = (
        body.client_state or (client.state if client else None) or (lead.state if lead else None)
    )
    refs, refs_title = _references_for(db, (head.references_state if head else None) or state)
    q = Quotation(
        code=material.next_code(db, "QTN"),
        revision=0,
        lead_id=lead.id if lead else None,
        client_id=client.id if client else None,
        survey_id=body.survey_id,
        letterhead_id=head.id if head else None,
        salesperson_id=salesperson,
        client_firm=firm,
        client_city=body.client_city
        or (client.city if client else None)
        or (lead.city if lead else None),
        client_state=state,
        attention=body.attention
        or (contact.name if contact else None)
        or (lead.contact_name if lead else None),
        project=project,
        brand=body.brand or (head.brand if head else None),
        quote_date=body.quote_date or date.today(),
        validity_days=body.validity_days or s.default_validity_days,
        show_amounts=body.show_amounts,
        letter_template_id=letter.id if letter else None,
        opening=letter.opening if letter else "",
        subject=letter.subject if letter else "",
        body=letter.body if letter else "",
        enclosures=letter.enclosures if letter else "",
        terms=_terms_for(db, head),
        references=refs,
        references_title=refs_title,
        created_by=principal.user.id,
    )
    db.add(q)
    rc = svc.RateContext.make(db)
    for pick in body.items:
        offer = db.get(OfferItem, pick.offer_item_id)
        if offer is None or not offer.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Offer item {pick.offer_item_id} not found"
            )
        svc.add_item(db, q, offer, pick.options, rc)
    db.flush()
    record(
        db,
        request,
        principal,
        "quotation.create",
        "quotation",
        q.id,
        after={"code": q.code, "items": len(q.items)},
    )
    db.commit()
    return _q_out(db, q, principal)


@router.get("")
def list_quotations(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    q: str = "",
    status_: Annotated[str | None, Query(alias="status")] = None,
    lead_id: int | None = None,
    all_revisions: bool = False,
    mine: bool = False,
) -> list[dict]:
    if svc.expire_due(db):
        db.commit()
    query = svc.visible_q(scope, principal)
    if not all_revisions:
        query = query.where(Quotation.is_latest)
    if status_:
        query = query.where(Quotation.status == status_)
    if lead_id:
        query = query.where(Quotation.lead_id == lead_id)
    if mine:
        query = query.where(Quotation.salesperson_id == principal.user.id)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Quotation.code.ilike(like),
                Quotation.client_firm.ilike(like),
                Quotation.project.ilike(like),
            )
        )
    rows = list(db.scalars(query.order_by(Quotation.id.desc()).limit(300)))
    names = dict(
        db.execute(
            select(User.id, User.full_name).where(
                User.id.in_({r.salesperson_id for r in rows if r.salesperson_id} or {uuid.uuid4()})
            )
        ).all()
    )
    return jsonable_encoder(
        [
            {
                "id": r.id,
                "code": r.code,
                "revision": r.revision,
                "client_firm": r.client_firm,
                "project": r.project,
                "client_city": r.client_city,
                "status": r.status,
                "quote_date": r.quote_date,
                "valid_until": date.fromordinal(r.quote_date.toordinal() + r.validity_days),
                "salesperson": names.get(r.salesperson_id),
                "items": len(r.items),
                "total": svc.totals(r)["total"] if r.show_amounts else None,
                "lead_id": r.lead_id,
            }
            for r in rows
        ]
    )


@router.get("/followups")
def list_followups(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    mine: bool = True,
    status_: Annotated[str, Query(alias="status")] = "open",
) -> list[dict]:
    me = principal.user.id if (mine or scope != "all") else None
    return jsonable_encoder(svc.followup_rows(db, me, None, status_))


class FollowUpDone(BaseModel):
    note: str | None = Field(None, max_length=2000)


@router.post("/followups/{fid}/done")
def followup_done(
    fid: int,
    body: FollowUpDone,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    f = db.get(QuotationFollowUp, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Follow-up not found")
    q = svc.get_visible(db, f.quotation_id, scope, principal)
    if f.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "This follow-up is already closed")
    from datetime import UTC, datetime

    f.status, f.done_at, f.note = "done", datetime.now(UTC), body.note
    svc._activity(
        db,
        q,
        f"Follow-up (day {f.day}) on {q.code} R{q.revision}: {body.note or 'done'}",
        principal.user.id,
    )
    record(
        db, request, principal, "quotation.followup", "quotation", q.id, after={"followup": f.id}
    )
    db.commit()
    return {"ok": True}


@router.get("/files/{file_id}")
def download_file(file_id: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    f = db.get(QuotationFile, file_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    svc.get_visible(db, f.quotation_id, scope, principal)
    p = media(f.path)
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(
        p, media_type=DOCX if f.kind == "docx" else "application/pdf", filename=f.file_name
    )


@router.get("/{qid}")
def get_quotation(qid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    return _q_out(db, svc.get_visible(db, qid, scope, principal), principal)


class QuotationUpdate(BaseModel):
    letterhead_id: int | None = None
    salesperson_id: uuid.UUID | None = None
    client_firm: str | None = Field(None, max_length=300)
    client_city: str | None = None
    client_state: str | None = None
    attention: str | None = None
    project: str | None = Field(None, max_length=300)
    brand: str | None = None
    areas_list: str | None = None
    quote_date: date | None = None
    validity_days: int | None = Field(None, ge=1, le=365)
    show_amounts: bool | None = None
    opening: str | None = None
    subject: str | None = None
    body: str | None = None
    enclosures: str | None = None
    signatory_name: str | None = None
    signatory_designation: str | None = None
    terms: list[dict[str, Any]] | None = None
    references: list[dict[str, Any]] | None = None
    references_title: str | None = None
    notes: str | None = None


@router.put("/{qid}")
def update_quotation(
    qid: int,
    body: QuotationUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """Edits this quotation only: the library stays as it is."""
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    data = body.model_dump(exclude_unset=True)
    lib.check_letter(
        data.get("subject", q.subject), data.get("body", q.body), data.get("opening", q.opening)
    )
    if "salesperson_id" in data and principal.permissions.get("quotation.edit") != "all":
        data.pop("salesperson_id")
    if "terms" in data:
        data["terms"] = [
            {
                "category": t.get("category") or "general",
                "text": str(t.get("text") or ""),
                "clause_id": t.get("clause_id"),
            }
            for t in data["terms"] or []
            if str(t.get("text") or "").strip()
        ]
    if (
        "letterhead_id" in data
        and data["letterhead_id"]
        and db.get(Letterhead, data["letterhead_id"]) is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Letterhead not found")
    for k, v in data.items():
        setattr(q, k, v)
    record(
        db,
        request,
        principal,
        "quotation.update",
        "quotation",
        q.id,
        after=jsonable_encoder({k: v for k, v in data.items() if k not in ("terms", "references")}),
    )
    db.commit()
    return _q_out(db, q, principal)


@router.post("/{qid}/items", status_code=status.HTTP_201_CREATED)
def add_item(
    qid: int,
    body: ItemPick,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    offer = db.get(OfferItem, body.offer_item_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer item not found")
    svc.add_item(db, q, offer, body.options, svc.RateContext.make(db))
    record(
        db,
        request,
        principal,
        "quotation.item.add",
        "quotation",
        q.id,
        after={"offer_item": offer.name},
    )
    db.commit()
    return _q_out(db, q, principal)


class ItemUpdate(BaseModel):
    name: str | None = None
    budget_title: str | None = None
    options: list[str] | None = None
    specs: list[dict[str, Any]] | None = None
    sort_order: int | None = None


def _item(db, q: Quotation, item_id: int) -> QuotationItem:
    item = db.get(QuotationItem, item_id)
    if item is None or item.quotation_id != q.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@router.put("/{qid}/items/{item_id}")
def update_item(
    qid: int,
    item_id: int,
    body: ItemUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    item = _item(db, q, item_id)
    data = body.model_dump(exclude_unset=True)
    if "specs" in data:
        data["specs"] = [
            {
                **s,
                "sections": [
                    SectionIn.model_validate(x).model_dump() for x in s.get("sections") or []
                ],
                "images": [ImageIn.model_validate(x).model_dump() for x in s.get("images") or []],
            }
            for s in data["specs"]
        ]
    if "options" in data:
        data["options"] = [str(o) for o in data["options"] or []]
    for k, v in data.items():
        setattr(item, k, v)
    record(
        db,
        request,
        principal,
        "quotation.item.update",
        "quotation",
        q.id,
        after={"item": item.name},
    )
    db.commit()
    return _q_out(db, q, principal)


@router.delete("/{qid}/items/{item_id}")
def delete_item(
    qid: int,
    item_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    item = _item(db, q, item_id)
    q.items.remove(item)
    record(
        db,
        request,
        principal,
        "quotation.item.delete",
        "quotation",
        q.id,
        before={"item": item.name},
    )
    db.commit()
    return _q_out(db, q, principal)


class LineUpdate(BaseModel):
    description: str | None = None
    uom: Literal[UOMS] | None = None  # type: ignore[valid-type]
    rate: Decimal | None = Field(None, ge=0)
    qty: Decimal | None = Field(None, ge=0)
    option: str | None = None
    if_required: bool | None = None
    client_scope: bool | None = None
    sort_order: int | None = None


def _line(db, q: Quotation, line_id: int) -> tuple[QuotationItem, QuotationLine]:
    ln = db.get(QuotationLine, line_id)
    item = db.get(QuotationItem, ln.item_id) if ln else None
    if ln is None or item is None or item.quotation_id != q.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    return item, ln


@router.put("/{qid}/lines/{line_id}")
def update_line(
    qid: int,
    line_id: int,
    body: LineUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """A rate typed here overrides the filled one (for this quotation only)."""
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    _item_, ln = _line(db, q, line_id)
    data = body.model_dump(exclude_unset=True)
    before = {"rate": ln.rate, "qty": ln.qty}
    if "rate" in data:
        ln.overridden = data["rate"] is not None
        if data["rate"] is not None:
            ln.rate_source, ln.rate_note = "manual", "Typed in this quotation"
    for k, v in data.items():
        setattr(ln, k, v)
    if "rate" in data and data["rate"] is None:
        svc.fill_rate(
            svc.RateContext.make(db),
            ln,
            db.get(OfferLine, ln.offer_line_id) if ln.offer_line_id else None,
        )
    if "qty" in data and data["qty"] is not None:
        q.show_amounts = True
    record(
        db,
        request,
        principal,
        "quotation.line.update",
        "quotation",
        q.id,
        before=jsonable_encoder(before),
        after=jsonable_encoder(data),
    )
    db.commit()
    return _q_out(db, q, principal)


class LineNew(BaseModel):
    offer_line_id: int | None = None
    description: str | None = None
    uom: Literal[UOMS] = "sqft"  # type: ignore[valid-type]
    option: str | None = None
    rate: Decimal | None = Field(None, ge=0)


@router.post("/{qid}/items/{item_id}/lines", status_code=status.HTTP_201_CREATED)
def add_line(
    qid: int,
    item_id: int,
    body: LineNew,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    item = _item(db, q, item_id)
    order = max((ln.sort_order for ln in item.lines), default=0) + 10
    if body.offer_line_id:
        src = db.get(OfferLine, body.offer_line_id)
        if src is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer line not found")
        ln = svc.line_copy(src, body.option, order)
        svc.fill_rate(svc.RateContext.make(db), ln, src)
    else:
        if not (body.description or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Describe the line")
        ln = QuotationLine(
            sort_order=order, option=body.option, description=body.description, uom=body.uom
        )
        if body.rate is not None:
            ln.rate, ln.overridden, ln.rate_source, ln.rate_note = (
                body.rate,
                True,
                "manual",
                "Typed in this quotation",
            )
        else:
            svc.fill_rate(svc.RateContext.make(db), ln, None)
    item.lines.append(ln)
    record(
        db, request, principal, "quotation.line.add", "quotation", q.id, after={"item": item.name}
    )
    db.commit()
    return _q_out(db, q, principal)


@router.delete("/{qid}/lines/{line_id}")
def delete_line(
    qid: int,
    line_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    item, ln = _line(db, q, line_id)
    item.lines.remove(ln)
    record(
        db,
        request,
        principal,
        "quotation.line.delete",
        "quotation",
        q.id,
        before={"line": plain(ln.description)[:80]},
    )
    db.commit()
    return _q_out(db, q, principal)


@router.post("/{qid}/refill-rates")
def refill_rates(
    qid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    n = svc.refill_rates(db, q)
    record(db, request, principal, "quotation.refill", "quotation", q.id, after={"lines": n})
    db.commit()
    return _q_out(db, q, principal)


class SurveyQty(BaseModel):
    survey_id: int


@router.post("/{qid}/survey-quantities")
def survey_quantities(
    qid: int,
    body: SurveyQty,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """Quantities from an M6b survey: each item's area type -> the treated area of the survey's
    areas of that type, on its sqm / sqft lines (rft and nos lines stay as they are)."""
    q = svc.get_visible(db, qid, scope, principal)
    svc.check_edit(db, q, principal)
    sscope = principal.permissions.get("survey.view")
    if sscope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot see surveys")
    s: Survey = survey_svc.get_visible(db, body.survey_id, sscope, principal)
    by_type: dict[int, Decimal] = {}
    for a in s.areas:
        if a.area_type_id:
            by_type[a.area_type_id] = by_type.get(a.area_type_id, Decimal(0)) + Decimal(
                a.treated_area_sqm or 0
            )
    filled = skipped = 0
    for item in q.items:
        sqm = by_type.get(item.area_type_id) if item.area_type_id else None
        if sqm is None:
            skipped += 1
            continue
        for ln in item.lines:
            if ln.client_scope:
                continue
            if ln.uom == "sqm":
                ln.qty = sqm.quantize(Decimal("0.001"))
            elif ln.uom == "sqft":
                ln.qty = (sqm * SQFT_PER_SQM).quantize(Decimal("0.001"))
            else:
                continue
            filled += 1
    q.survey_id, q.show_amounts = s.id, True
    record(
        db,
        request,
        principal,
        "quotation.survey_qty",
        "quotation",
        q.id,
        after={"survey": s.code, "lines": filled},
    )
    db.commit()
    out = _q_out(db, q, principal)
    out["survey_fill"] = {"survey": s.code, "lines_filled": filled, "items_without_match": skipped}
    return out


class SaveBack(BaseModel):
    kind: Literal["letter", "spec", "line", "item"]
    item_id: int | None = None
    spec_index: int | None = None
    line_id: int | None = None
    note: str | None = None


@router.post("/{qid}/save-back")
def save_back(
    qid: int,
    body: SaveBack,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    _: TemplateEdit,
) -> dict:
    """Write this quotation's text into the library as a new version (quotation.template.edit).
    Older quotations keep their own copy."""
    q = svc.get_visible(db, qid, scope, principal)
    uid = principal.user.id
    note = body.note or f"saved back from {q.code} R{q.revision}"
    if body.kind == "letter":
        row = db.get(LetterTemplate, q.letter_template_id or -1)
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "This quotation's letter has no template to save into"
            )
        lib.check_letter(q.subject, q.body, q.opening)
        row.opening, row.subject, row.body, row.enclosures = (
            q.opening,
            q.subject,
            q.body,
            q.enclosures,
        )
        v = lib.save_version(db, row, "save_back", uid, note)
    elif body.kind == "spec":
        item = _item(db, q, body.item_id or -1)
        try:
            spec = item.specs[body.spec_index or 0]
        except IndexError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Specification not found") from e
        row = db.get(SpecBlock, spec.get("spec_block_id") or -1)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "The library block is gone")
        row.title, row.heading_prefix = (
            spec["title"],
            spec.get("heading_prefix") or row.heading_prefix,
        )
        row.sections, row.images = spec.get("sections") or [], spec.get("images") or []
        v = lib.save_version(db, row, "save_back", uid, note)
        specs = list(item.specs)
        specs[body.spec_index or 0] = {**spec, "version": row.version}
        item.specs = specs
    elif body.kind == "line":
        item, ln = _line(db, q, body.line_id or -1)
        row = db.get(OfferLine, ln.offer_line_id) if ln.offer_line_id else None
        if row is None:  # a line typed in the quotation: a new library line, added to the item
            row = OfferLine(
                description=ln.description,
                uom=ln.uom,
                rate_source="fixed",
                default_rate=ln.rate,
                if_required=ln.if_required,
                client_scope=ln.client_scope,
                created_by=uid,
            )
            db.add(row)
            v = lib.save_version(db, row, "save_back", uid, note)
            ln.offer_line_id = row.id
            offer = db.get(OfferItem, item.offer_item_id) if item.offer_item_id else None
            if offer:
                offer.lines.append(
                    OfferItemLine(
                        offer_line_id=row.id,
                        option=ln.option,
                        sort_order=max((x.sort_order for x in offer.lines), default=0) + 1,
                    )
                )
                lib.save_version(db, offer, "save_back", uid, note)
        else:
            row.description, row.uom, row.if_required, row.client_scope = (
                ln.description,
                ln.uom,
                ln.if_required,
                ln.client_scope,
            )
            if row.rate_source == "fixed" and ln.rate is not None:
                row.default_rate = ln.rate
            v = lib.save_version(db, row, "save_back", uid, note)
        ln.library_version = row.version
    else:
        item = _item(db, q, body.item_id or -1)
        row = db.get(OfferItem, item.offer_item_id or -1)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "The library item is gone")
        row.name, row.budget_title = item.name, item.budget_title
        v = lib.save_version(db, row, "save_back", uid, note)
    record(
        db,
        request,
        principal,
        f"quotation_library.{body.kind}.save_back",
        "quotation_library",
        row.id,
        after={"quotation": f"{q.code} R{q.revision}", "version": v.version},
    )
    db.commit()
    out = _q_out(db, q, principal)
    out["saved_back"] = {"kind": body.kind, "id": row.id, "version": v.version}
    return out


@router.post("/{qid}/revision", status_code=status.HTTP_201_CREATED)
def new_revision(
    qid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    escope = principal.permissions.get("quotation.edit")
    if (
        escope is None
        or db.scalar(svc.visible_q(escope, principal).where(Quotation.id == q.id)) is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this quotation")
    if not q.is_latest:
        raise HTTPException(status.HTTP_409_CONFLICT, "Make the new revision from the latest one")
    if q.status == "won":
        raise HTTPException(status.HTTP_409_CONFLICT, "A won quotation is not revised")
    new = svc.copy_quotation(db, q, principal.user.id)
    if q.status in svc.OPEN_STATUSES:
        q.status = "negotiation" if q.status == "sent" else q.status
    record(
        db,
        request,
        principal,
        "quotation.revision",
        "quotation",
        new.id,
        after={"code": new.code, "revision": new.revision},
    )
    db.commit()
    return _q_out(db, new, principal)


@router.get("/{qid}/diff")
def revision_diff(
    qid: int, db: DbSession, principal: CurrentPrincipal, scope: View, against: int | None = None
) -> dict:
    """What changed from the previous revision (or `against`): rates, quantities, lines."""
    q = svc.get_visible(db, qid, scope, principal)
    other_id = against or q.previous_id
    if other_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no earlier revision")
    other = svc.get_visible(db, other_id, scope, principal)
    if other.code != q.code:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Compare revisions of the same quotation"
        )
    old, new = (other, q) if other.revision < q.revision else (q, other)
    return jsonable_encoder(svc.diff(old, new))


class StatusIn(BaseModel):
    status: Literal["sent", "negotiation", "won", "lost"]
    lost_reason: str | None = None
    lost_note: str | None = None
    site_id: int | None = None
    choices: dict[int, str] | None = None  # item id -> the option the client chose


def _issue(db, q: Quotation, user_id) -> list[QuotationFile]:
    """Build and keep the Word and PDF files of this revision (never overwriting), and attach
    them to the lead's activity."""
    doc = render.build(db, q)
    template = svc.settings(db).word_template_path
    made = []
    for kind, data in (("docx", docx_out.docx(doc, template)), ("pdf", html_out.pdf(doc))):
        n = (
            db.scalar(
                select(func.count()).where(
                    QuotationFile.quotation_id == q.id, QuotationFile.kind == kind
                )
            )
            + 1
        )
        name = f"{q.code}-R{q.revision}" + (f"-{n}" if n > 1 else "") + f".{kind}"
        rel = f"quotations/{q.code}/{name}"
        path = media(rel)
        while path.exists():  # never overwrite an issued file
            n += 1
            name = f"{q.code}-R{q.revision}-{n}.{kind}"
            rel = f"quotations/{q.code}/{name}"
            path = media(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        f = QuotationFile(
            quotation_id=q.id,
            kind=kind,
            path=rel,
            file_name=name,
            size_bytes=len(data),
            created_by=user_id,
        )
        db.add(f)
        db.flush()
        made.append(f)
    pdf_file = next(f for f in made if f.kind == "pdf")
    svc._activity(
        db,
        q,
        f"Quotation {q.code} R{q.revision} issued ({', '.join(f.file_name for f in made)})",
        user_id,
        pdf_file.id,
    )
    return made


@router.post("/{qid}/issue")
def issue(
    qid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    _send_scope(db, q, principal)
    files = _issue(db, q, principal.user.id)
    record(
        db,
        request,
        principal,
        "quotation.issue",
        "quotation",
        q.id,
        after={"files": [f.file_name for f in files]},
    )
    db.commit()
    return _q_out(db, q, principal)


@router.post("/{qid}/status")
def set_status(
    qid: int,
    body: StatusIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    if not q.is_latest:
        raise HTTPException(status.HTTP_409_CONFLICT, "Change the status on the latest revision")
    before = q.status
    extra: dict[str, Any] = {}
    if body.status == "negotiation":
        svc.check_edit(db, q, principal)
        if q.status != "sent":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Only a sent quotation goes into negotiation"
            )
        q.status = "negotiation"
    else:
        _send_scope(db, q, principal)
        if body.status == "sent":
            has_files = db.scalar(select(func.count()).where(QuotationFile.quotation_id == q.id))
            if not has_files:
                _issue(db, q, principal.user.id)
            svc.mark_sent(db, q, principal.user.id)
        elif body.status == "lost":
            if body.lost_reason not in LOST_REASONS:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose why the quotation was lost"
                )
            if q.status in svc.TERMINAL:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"The quotation is already {q.status}"
                )
            svc.mark_lost(db, q, body.lost_reason, body.lost_note, principal.user.id)
        elif body.status == "won":
            tender, site = svc.mark_won(db, q, principal.user.id, body.site_id, body.choices)
            extra = {
                "tender_id": tender.id,
                "tender_code": tender.code,
                "site_id": site.id,
                "site_code": site.code,
            }
    record(
        db,
        request,
        principal,
        f"quotation.{body.status}",
        "quotation",
        q.id,
        before={"status": before},
        after={"status": q.status, **extra},
    )
    db.commit()
    out = _q_out(db, q, principal)
    out["result"] = extra
    return out


@router.get("/{qid}/preview")
def preview(qid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    q = svc.get_visible(db, qid, scope, principal)
    return {"html": html_out.html(render.build(db, q), for_pdf=False)}


@router.get("/{qid}/docx")
def download_docx(qid: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    q = svc.get_visible(db, qid, scope, principal)
    data = docx_out.docx(render.build(db, q), svc.settings(db).word_template_path)
    return Response(
        data,
        media_type=DOCX,
        headers={"Content-Disposition": f'attachment; filename="{q.code}-R{q.revision}.docx"'},
    )


@router.get("/{qid}/pdf")
def download_pdf(qid: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    q = svc.get_visible(db, qid, scope, principal)
    data = html_out.pdf(render.build(db, q))
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{q.code}-R{q.revision}.pdf"'},
    )
