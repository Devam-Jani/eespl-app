"""Checklist templates, inspections (with a drawn signature and photos) and minutes of meeting.

inspection.view / inspection.edit by site; checklist templates are changed with inspection.edit
scope all. A hold-point step whose stage step names a checklist is certified only after a
passed inspection with that checklist (pass, or pass with remarks).
"""

import base64
import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import pdf
from app.execution import service as svc
from app.execution.common import media, names, pdf_response, record, save_upload, send_file
from app.execution.models import ChecklistItem, ChecklistTemplate, Inspection, Mom, MomPoint
from app.material import service as material
from app.models import User
from app.sites import work
from app.sites.models import AreaScope, Site, SiteNode, Task

router = APIRouter(prefix="/api/execution", tags=["execution"])
InspView = Annotated[str, Depends(require_permission("inspection.view"))]


# --- checklist templates -------------------------------------------------------------------------


class ItemIn(BaseModel):
    id: int | None = None
    text: str = Field(min_length=1)
    type: Literal["pass_fail", "number", "text", "photo"] = "pass_fail"
    required: bool = True


class ChecklistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True
    items: list[ItemIn] = Field(min_length=1)


def _checklist_out(t: ChecklistTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "is_active": t.is_active,
        "items": [
            {"id": i.id, "text": i.text, "type": i.type, "required": i.required} for i in t.items
        ],
    }


@router.get("/checklists")
def list_checklists(db: DbSession, _: CurrentPrincipal) -> list[dict]:
    """Anyone signed in may read them (they fill the stage-template and inspection forms)."""
    return [
        _checklist_out(t)
        for t in db.scalars(select(ChecklistTemplate).order_by(ChecklistTemplate.name))
    ]


def _save_checklist(db, t: ChecklistTemplate, body: ChecklistIn, principal):
    if principal.permissions.get("inspection.edit") != "all":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Checklists are kept by the office (inspection.edit, all)"
        )
    clash = db.scalar(select(ChecklistTemplate.id).where(ChecklistTemplate.name == body.name))
    if clash and clash != t.id:
        raise svc.conflict(f"A checklist named {body.name} exists")
    t.name, t.is_active = body.name, body.is_active
    existing = {i.id: i for i in t.items}
    items = []
    for n, it in enumerate(body.items, start=1):
        row = existing.get(it.id or 0) or ChecklistItem(created_by=principal.user.id)
        row.sort_order, row.text, row.type, row.required = n, it.text, it.type, it.required
        items.append(row)
    t.items = items


@router.post("/checklists", status_code=status.HTTP_201_CREATED)
def create_checklist(
    body: ChecklistIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = ChecklistTemplate(created_by=principal.user.id)
    _save_checklist(db, t, body, principal)
    db.add(t)
    db.flush()
    record(
        db,
        request,
        principal,
        "checklist.create",
        "checklist_template",
        t.id,
        after=body.model_dump(),
    )
    db.commit()
    db.refresh(t)
    return _checklist_out(t)


@router.put("/checklists/{cid}")
def update_checklist(
    cid: int, body: ChecklistIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = db.get(ChecklistTemplate, cid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist not found")
    before = _checklist_out(t)
    _save_checklist(db, t, body, principal)
    record(
        db,
        request,
        principal,
        "checklist.update",
        "checklist_template",
        t.id,
        before,
        body.model_dump(),
    )
    db.commit()
    db.refresh(t)
    return _checklist_out(t)


# --- inspections ---------------------------------------------------------------------------------


class AnswerIn(BaseModel):
    item_id: int
    value: str | None = None  # pass / fail / na; a number; text; (photos come as files)


class InspectionIn(BaseModel):
    site_id: int
    template_id: int
    task_id: int | None = None
    node_id: int | None = None
    on_date: date | None = None
    answers: list[AnswerIn]
    result: Literal["pass", "fail", "pass_with_remarks"] | None = None  # default: from answers
    remark: str | None = None
    client_rep: str | None = Field(default=None, max_length=200)
    signature: str | None = None  # a PNG data URL drawn on screen
    certify: bool = False  # also certify the task's hold point when it passes


def passed_inspection(db, task: Task) -> bool:
    step = task.step
    if not (step and step.checklist_template_id):
        return True
    return (
        db.scalar(
            select(Inspection.id)
            .where(
                Inspection.task_id == task.id,
                Inspection.template_id == step.checklist_template_id,
                Inspection.result.in_(("pass", "pass_with_remarks")),
            )
            .limit(1)
        )
        is not None
    )


def _insp_out(db, i: Inspection) -> dict:
    site = db.get(Site, i.site_id)
    task = db.get(Task, i.task_id) if i.task_id else None
    node_id = i.node_id or (task.node_id if task else None)
    node = db.get(SiteNode, node_id) if node_id else None
    who = names(db, [i.inspected_by])
    return {
        "id": i.id,
        "code": i.code,
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "template_id": i.template_id,
        "template_name": i.template.name,
        "task_id": i.task_id,
        "task_name": task.name if task else None,
        "task_status": task.status if task else None,
        "node_id": i.node_id,
        "node_name": node.name if node else None,
        "on_date": i.on_date,
        "answers": i.answers,
        "result": i.result,
        "remark": i.remark,
        "client_rep": i.client_rep,
        "inspected_by_name": who.get(i.inspected_by),
        "has_signature": bool(i.signature_path),
        "client_signoff": i.client_signoff,
        "client_signed_name": i.client_signed_name,
        "client_signed_at": i.client_signed_at,
        "photos": [
            {"n": n, "filename": p["filename"], "item_id": p.get("item_id")}
            for n, p in enumerate(i.photos)
        ],
    }


def _visible(db, iid, principal) -> Inspection:
    i = db.get(Inspection, iid)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inspection not found")
    svc.site_for(db, i.site_id, principal, "inspection.view")
    return i


@router.get("/inspections")
def list_inspections(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: InspView,
    site_id: int | None = None,
    task_id: int | None = None,
) -> list[dict]:
    q = select(Inspection).where(
        material.by_site(scope, principal, Inspection.site_id, Inspection.created_by)
    )
    if site_id is not None:
        q = q.where(Inspection.site_id == site_id)
    if task_id is not None:
        q = q.where(Inspection.task_id == task_id)
    return [_insp_out(db, i) for i in db.scalars(q.order_by(Inspection.id.desc()).limit(500))]


@router.get("/inspections/{iid}")
def get_inspection(iid: int, db: DbSession, principal: CurrentPrincipal, _: InspView) -> dict:
    return _insp_out(db, _visible(db, iid, principal))


def certify(db, request, principal, site: Site, task: Task, remark: str | None) -> None:
    """Certify a done hold-point task (the office: site.edit)."""
    if not material.covers_site(
        db, principal.permissions.get("site.edit"), principal, site.id, site.created_by
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Certifying a hold point needs site.edit")
    if not (task.step and task.step.hold_point):
        raise svc.unprocessable("Only hold-point steps are certified")
    if task.status != "done":
        raise svc.conflict("The step must be done first")
    if not passed_inspection(db, task):
        raise svc.unprocessable(
            "This hold point needs a passed inspection with its checklist first"
        )
    task.status, task.certified_by, task.certified_at = "certified", principal.user.id, svc.now()
    if remark:
        task.remark = f"{task.remark}\n{remark}" if task.remark else remark
    db.flush()
    if task.area_scope_id:
        work.refresh_scope(db, db.get(AreaScope, task.area_scope_id))
    record(db, request, principal, "site.task.certify", "site", site.id, after={"task_id": task.id})


def _value(item: ChecklistItem, raw: str | None, has_photo: bool):
    raw = (raw or "").strip()
    if item.type == "photo":
        if item.required and not has_photo:
            raise svc.unprocessable(f"'{item.text}': add the photo")
        return "photo" if has_photo else None
    if not raw:
        if item.required:
            raise svc.unprocessable(f"'{item.text}' is required")
        return None
    if item.type == "pass_fail":
        if raw not in ("pass", "fail", "na"):
            raise svc.unprocessable(f"'{item.text}': answer pass, fail or n/a")
        return raw
    if item.type == "number":
        try:
            return str(Decimal(raw))
        except InvalidOperation as exc:
            raise svc.unprocessable(f"'{item.text}': give a number") from exc
    return raw


@router.post("/inspections", status_code=status.HTTP_201_CREATED)
async def create_inspection(
    request: Request, db: DbSession, principal: CurrentPrincipal, _: InspView
) -> dict:
    """Multipart: `data` (JSON, InspectionIn), files `item_<item id>` for photo items and `photo`
    (any number) for other photos."""
    form = await request.form()
    try:
        body = InspectionIn.model_validate(json.loads(form.get("data") or "{}"))
    except ValueError as exc:
        raise svc.unprocessable(f"Invalid inspection: {exc}") from exc
    site = svc.site_for(db, body.site_id, principal, "inspection.view", "inspection.edit")
    t = db.get(ChecklistTemplate, body.template_id)
    if t is None:
        raise svc.unprocessable("Checklist not found")
    task = None
    if body.task_id:
        task = db.get(Task, body.task_id)
        if task is None or task.site_id != site.id:
            raise svc.unprocessable("That task is not on this site")
    if body.node_id:
        node = db.get(SiteNode, body.node_id)
        if node is None or node.site_id != site.id:
            raise svc.unprocessable("That place is not on this site")
    item_files = {
        k: v for k, v in form.multi_items() if isinstance(v, UploadFile) and k.startswith("item_")
    }
    given = {a.item_id: a.value for a in body.answers}
    answers, failed = [], False
    for item in t.items:
        value = _value(item, given.get(item.id), f"item_{item.id}" in item_files)
        failed |= item.type == "pass_fail" and value == "fail"
        answers.append(
            {
                "item_id": item.id,
                "text": item.text,
                "type": item.type,
                "required": item.required,
                "value": value,
            }
        )
    result = body.result or ("fail" if failed else "pass")
    if failed and result != "fail":
        raise svc.unprocessable("A checklist item failed: the result is fail")
    i = Inspection(
        code=material.next_code(db, "INS"),
        site_id=site.id,
        node_id=body.node_id,
        task_id=body.task_id,
        template_id=t.id,
        on_date=body.on_date or svc.today(),
        answers=answers,
        result=result,
        remark=body.remark,
        client_rep=body.client_rep,
        inspected_by=principal.user.id,
        created_by=principal.user.id,
        photos=[],
    )
    db.add(i)
    db.flush()
    photos = []
    for key, f in form.multi_items():
        if isinstance(f, UploadFile) and (key == "photo" or key.startswith("item_")):
            rel, name = await save_upload(f, f"inspections/{i.id}")
            photos.append(
                {
                    "path": rel,
                    "filename": name,
                    "item_id": int(key[5:]) if key.startswith("item_") else None,
                }
            )
    i.photos = photos
    if body.signature:
        if not body.signature.startswith("data:image/png;base64,"):
            raise svc.unprocessable("The signature must be a PNG drawn on screen")
        data = base64.b64decode(body.signature.split(",", 1)[1], validate=True)
        if len(data) > 2 * 1024 * 1024:
            raise svc.unprocessable("The signature image is too large")
        rel = f"inspections/{i.id}/signature-{uuid.uuid4().hex[:8]}.png"
        media(rel).parent.mkdir(parents=True, exist_ok=True)
        media(rel).write_bytes(data)
        i.signature_path = rel
    record(
        db,
        request,
        principal,
        "inspection.create",
        "inspection",
        i.id,
        after={"site": site.code, "template": t.name, "result": result, "task_id": body.task_id},
    )
    if body.certify and task is not None and result != "fail":
        db.flush()
        certify(db, request, principal, site, task, f"Certified on {i.code}")
    db.commit()
    db.refresh(i)
    return _insp_out(db, i)


@router.get("/inspections/{iid}/photos/{n}")
def inspection_photo(iid: int, n: int, db: DbSession, principal: CurrentPrincipal, _: InspView):
    i = _visible(db, iid, principal)
    p = i.photos[n] if 0 <= n < len(i.photos) else None
    return send_file(p["path"] if p else None, p["filename"] if p else None)


@router.get("/inspections/{iid}/signature")
def inspection_signature(iid: int, db: DbSession, principal: CurrentPrincipal, _: InspView):
    return send_file(_visible(db, iid, principal).signature_path, "signature.png")


@router.get("/inspections/{iid}/pdf")
def inspection_pdf(iid: int, db: DbSession, principal: CurrentPrincipal, _: InspView):
    i = _visible(db, iid, principal)
    return pdf_response(pdf.inspection(db, i, _insp_out(db, i)), i.code)


# --- minutes of meeting --------------------------------------------------------------------------


class PointIn(BaseModel):
    id: int | None = None
    text: str = Field(min_length=1)
    owner_user_id: str | None = None
    owner_name: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    status: Literal["open", "done", "dropped"] = "open"


class MomIn(BaseModel):
    site_id: int
    on_date: date | None = None
    title: str = Field(min_length=1, max_length=300)
    venue: str | None = Field(default=None, max_length=200)
    attendee_user_ids: list[str] = []
    attendee_others: list[str] = []
    notes: str | None = None
    points: list[PointIn] = []


def _point_out(p: MomPoint, who) -> dict:
    return {
        "id": p.id,
        "text": p.text,
        "owner_user_id": str(p.owner_user_id) if p.owner_user_id else None,
        "owner": who.get(p.owner_user_id) or p.owner_name,
        "owner_name": p.owner_name,
        "due_date": p.due_date,
        "status": p.status,
        "overdue": p.status == "open" and bool(p.due_date and p.due_date < svc.today()),
    }


def _mom_out(db, m: Mom) -> dict:
    site = db.get(Site, m.site_id)
    who = names(
        db, [*[uuid.UUID(u) for u in m.attendee_user_ids], *[p.owner_user_id for p in m.points]]
    )
    return {
        "id": m.id,
        "code": m.code,
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "on_date": m.on_date,
        "title": m.title,
        "venue": m.venue,
        "attendee_user_ids": m.attendee_user_ids,
        "attendees": [who.get(uuid.UUID(u), "?") for u in m.attendee_user_ids] + m.attendee_others,
        "attendee_others": m.attendee_others,
        "notes": m.notes,
        "points": [_point_out(p, who) for p in m.points],
    }


def _fill_mom(db, m: Mom, body: MomIn, principal):
    users = {
        str(u)
        for u in db.scalars(
            select(User.id).where(
                User.id.in_(
                    [
                        uuid.UUID(u)
                        for u in [
                            *body.attendee_user_ids,
                            *[p.owner_user_id for p in body.points if p.owner_user_id],
                        ]
                    ]
                    or [uuid.uuid4()]
                )
            )
        )
    }
    for u in [*body.attendee_user_ids, *[p.owner_user_id for p in body.points if p.owner_user_id]]:
        if u not in users:
            raise svc.unprocessable("An attendee or owner is not a user")
    m.on_date = body.on_date or svc.today()
    m.title, m.venue, m.notes = body.title, body.venue, body.notes
    m.attendee_user_ids = list(dict.fromkeys(body.attendee_user_ids))
    m.attendee_others = [x.strip() for x in body.attendee_others if x.strip()]
    existing = {p.id: p for p in m.points}
    pts = []
    for pi in body.points:
        p = existing.get(pi.id or 0) or MomPoint(created_by=principal.user.id)
        p.text, p.owner_name, p.due_date, p.status = pi.text, pi.owner_name, pi.due_date, pi.status
        p.owner_user_id = uuid.UUID(pi.owner_user_id) if pi.owner_user_id else None
        pts.append(p)
    m.points = pts


def _visible_mom(db, mid, principal) -> Mom:
    m = db.get(Mom, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MOM not found")
    svc.site_for(db, m.site_id, principal, "inspection.view")
    return m


@router.get("/moms")
def list_moms(
    db: DbSession, principal: CurrentPrincipal, scope: InspView, site_id: int | None = None
) -> list[dict]:
    q = select(Mom).where(material.by_site(scope, principal, Mom.site_id, Mom.created_by))
    if site_id is not None:
        q = q.where(Mom.site_id == site_id)
    return [
        _mom_out(db, m)
        for m in db.scalars(q.order_by(Mom.on_date.desc(), Mom.id.desc()).limit(300))
    ]


@router.get("/moms/{mid}")
def get_mom(mid: int, db: DbSession, principal: CurrentPrincipal, _: InspView) -> dict:
    return _mom_out(db, _visible_mom(db, mid, principal))


@router.post("/moms", status_code=status.HTTP_201_CREATED)
def create_mom(
    body: MomIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: InspView
) -> dict:
    site = svc.site_for(db, body.site_id, principal, "inspection.view", "inspection.edit")
    m = Mom(code=material.next_code(db, "MOM"), site_id=site.id, created_by=principal.user.id)
    _fill_mom(db, m, body, principal)
    db.add(m)
    db.flush()
    record(db, request, principal, "mom.create", "mom", m.id, after=body.model_dump(mode="json"))
    db.commit()
    db.refresh(m)
    return _mom_out(db, m)


@router.put("/moms/{mid}")
def update_mom(
    mid: int, body: MomIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: InspView
) -> dict:
    m = _visible_mom(db, mid, principal)
    svc.site_for(db, m.site_id, principal, "inspection.view", "inspection.edit")
    if body.site_id != m.site_id:
        raise svc.unprocessable("A MOM cannot move to another site")
    _fill_mom(db, m, body, principal)
    record(db, request, principal, "mom.update", "mom", m.id, after=body.model_dump(mode="json"))
    db.commit()
    db.refresh(m)
    return _mom_out(db, m)


class PointStatus(BaseModel):
    status: Literal["open", "done", "dropped"]


@router.patch("/mom-points/{pid}")
def point_status(
    pid: int,
    body: PointStatus,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: InspView,
) -> dict:
    p = db.get(MomPoint, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Point not found")
    m = _visible_mom(db, p.mom_id, principal)
    svc.site_for(db, m.site_id, principal, "inspection.view", "inspection.edit")
    before = p.status
    p.status = body.status
    record(
        db,
        request,
        principal,
        "mom.point",
        "mom",
        m.id,
        {"point": p.id, "status": before},
        {"status": p.status},
    )
    db.commit()
    return _mom_out(db, m)


@router.get("/sites/{site_id}/open-points")
def open_points(
    site_id: int, db: DbSession, principal: CurrentPrincipal, _: InspView
) -> list[dict]:
    site = svc.site_for(db, site_id, principal, "inspection.view")
    rows = db.execute(
        select(MomPoint, Mom.code, Mom.id)
        .join(Mom, Mom.id == MomPoint.mom_id)
        .where(Mom.site_id == site.id, MomPoint.status == "open")
        .order_by(MomPoint.due_date.nulls_last())
    ).all()
    who = names(db, [p.owner_user_id for p, _, _ in rows])
    return [{**_point_out(p, who), "mom_code": code, "mom_id": mid} for p, code, mid in rows]


@router.get("/moms/{mid}/pdf")
def mom_pdf(mid: int, db: DbSession, principal: CurrentPrincipal, _: InspView):
    m = _visible_mom(db, mid, principal)
    return pdf_response(pdf.mom(db, _mom_out(db, m)), m.code)
