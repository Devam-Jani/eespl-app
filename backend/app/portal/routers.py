"""The client portal API (/api/portal). Every endpoint resolves the site through
service.portal_site(), so another client's site, a hidden site or a switched-off section is a 404.
Responses are built field by field: no cost, rate paid to suppliers, margin, budget, salary,
wage, supplier or subcontractor data ever leaves here.
"""

import base64
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import audit
from app.auth.security import hash_password, utcnow
from app.db import DbSession
from app.execution import pdf as xpdf
from app.execution.common import media, names, pdf_response, save_upload, send_file
from app.execution.models import Dpr, Inspection, Mom, MomPoint
from app.execution.service import today
from app.finance import pdf as fpdf
from app.finance import service as fsvc
from app.finance.billing import _invoice_out, _ra_out
from app.finance.models import ClientContract, RaBill, Receipt, ReceiptAllocation, TaxInvoice
from app.models import User
from app.portal import service as svc
from app.portal.models import ClientUser, Comment, PortalInvite, SiteDocument, Snag, SnagPhoto
from app.portal.service import PortalCtx, portal_ctx
from app.sites import model3d
from app.sites.models import (
    Drawing,
    DrawingRevision,
    Site,
    SiteNode,
    StageTemplate,
    Task,
    TaskPhoto,
)

router = APIRouter(prefix="/api/portal", tags=["portal"])
Ctx = Annotated[PortalCtx, Depends(portal_ctx)]
ZERO = Decimal(0)


def _audit(db, request: Request, ctx: PortalCtx, action: str, entity: str, ident, after=None):
    if ctx.preview:
        return
    audit.record(
        db, action, entity, ident, user_id=ctx.user.id, after=after, ip=audit.client_ip(request)
    )


# --- invites (no login) --------------------------------------------------------------------------


class AcceptIn(BaseModel):
    password: str = Field(min_length=10, max_length=128)


def _invite(db, token: str) -> PortalInvite:
    inv = db.scalar(select(PortalInvite).where(PortalInvite.token_hash == svc.hash_token(token)))
    if inv is None or inv.used_at or inv.revoked_at or inv.expires_at < svc.now():
        raise HTTPException(
            status.HTTP_410_GONE, "This invite link has expired or was already used"
        )
    return inv


@router.get("/invite/{token}")
def invite_info(token: str, db: DbSession) -> dict:
    inv = _invite(db, token)
    user = db.get(User, inv.user_id)
    return {"full_name": user.full_name, "email": user.email, "expires_at": inv.expires_at}


@router.post("/invite/{token}")
def accept_invite(token: str, body: AcceptIn, request: Request, db: DbSession) -> dict:
    """Set the password from a one-time link; then sign in on the normal login page."""
    inv = _invite(db, token)
    user = db.get(User, inv.user_id)
    user.password_hash = hash_password(body.password)
    user.is_active = True
    inv.used_at = utcnow()
    audit.record(
        db, "portal.invite.accept", "user", user.id, user_id=user.id, ip=audit.client_ip(request)
    )
    db.commit()
    return {"email": user.email}


@router.get("/logo")
def logo(db: DbSession, _ctx: Ctx):
    """The EESPL logo for the portal header."""
    from app.masters.models import CompanyProfile

    p = db.get(CompanyProfile, 1)
    return send_file(p.logo_path if p else None)


# --- sites ---------------------------------------------------------------------------------------


def _open_snags(db, site_id) -> int:
    return db.scalar(
        select(func.count()).where(
            Snag.site_id == site_id, Snag.status.in_(("open", "in_progress", "fixed"))
        )
    )


def _last_dpr(db, site_id):
    return db.scalar(
        select(func.max(Dpr.on_date)).where(Dpr.site_id == site_id, Dpr.status != "draft")
    )


@router.get("/me")
def me(db: DbSession, ctx: Ctx) -> dict:
    clients = (
        db.execute(select(ClientUser.client_id).where(ClientUser.user_id == ctx.user.id))
        .scalars()
        .all()
    )
    from app.masters.models import Client

    return {
        "full_name": ctx.user.full_name,
        "preview": ctx.preview,
        "clients": [db.get(Client, c).name for c in clients],
    }


@router.get("/sites")
def my_sites(db: DbSession, ctx: Ctx) -> list[dict]:
    out = []
    for site in db.scalars(
        select(Site).where(Site.id.in_(svc.visible_sites(ctx.user.id))).order_by(Site.code)
    ):
        out.append(
            {
                "id": site.id,
                "code": site.code,
                "name": site.name,
                "city": site.city,
                "percent": float(site.progress_percent or 0),
                "last_dpr": _last_dpr(db, site.id),
                "open_snags": _open_snags(db, site.id),
                "sections": svc.sections(db, site.id),
            }
        )
    return out


def _client_points(db, site_id, client_user_ids) -> list[MomPoint]:
    """Open MOM points that are the client's: owned by one of their logins, or by someone named
    outside EESPL."""
    rows = db.scalars(
        select(MomPoint)
        .join(Mom, Mom.id == MomPoint.mom_id)
        .where(Mom.site_id == site_id, MomPoint.status == "open")
    ).all()
    return [
        p
        for p in rows
        if p.owner_user_id in client_user_ids or (p.owner_user_id is None and p.owner_name)
    ]


def _client_ids(db, ctx: PortalCtx) -> set:
    theirs = select(ClientUser.client_id).where(ClientUser.user_id == ctx.user.id)
    return set(db.scalars(select(ClientUser.user_id).where(ClientUser.client_id.in_(theirs))))


@router.get("/sites/{site_id}")
def overview(site_id: int, db: DbSession, ctx: Ctx) -> dict:
    site = svc.portal_site(db, ctx, site_id, "overview")
    nodes = db.scalars(
        select(SiteNode)
        .where(
            SiteNode.site_id == site.id, SiteNode.kind.in_(("tower", "wing", "floor", "basement"))
        )
        .order_by(SiteNode.parent_id.nulls_first(), SiteNode.sort_order, SiteNode.id)
    ).all()
    counts = dict(
        db.execute(
            select(Task.status, func.count())
            .where(Task.site_id == site.id, Task.parent_task_id.is_(None))
            .group_by(Task.status)
        ).all()
    )
    points = _client_points(db, site.id, _client_ids(db, ctx))
    return {
        "id": site.id,
        "code": site.code,
        "name": site.name,
        "city": site.city,
        "start_date": site.start_date,
        "target_date": site.target_date,
        "percent": float(site.progress_percent or 0),
        "parts": [
            {
                "id": n.id,
                "parent_id": n.parent_id,
                "kind": n.kind,
                "name": n.name,
                "percent": float(n.progress_percent or 0),
            }
            for n in nodes
        ],
        "stages": {
            k: counts.get(k, 0)
            for k in ("not_started", "in_progress", "done", "certified", "blocked")
        },
        "last_dpr": _last_dpr(db, site.id),
        "open_snags": _open_snags(db, site.id),
        "open_points": [
            {
                "id": p.id,
                "text": p.text,
                "due_date": p.due_date,
                "acknowledged": p.client_acknowledged_at is not None,
            }
            for p in points
        ],
        "sections": svc.sections(db, site.id),
    }


@router.get("/sites/{site_id}/model")
def model(site_id: int, db: DbSession, ctx: Ctx) -> dict:
    """The 3D view's data (read-only)."""
    site = svc.portal_site(db, ctx, site_id, "overview")
    payload = model3d.build(db, site.id)
    ids = {t for n in payload["nodes"] for t in n["status"]["template_ids"]}
    templates = [
        {"id": i, "name": n}
        for i, n in db.execute(
            select(StageTemplate.id, StageTemplate.name).where(StageTemplate.id.in_(ids or [0]))
        )
    ]
    return {
        **payload,
        "version": model3d.version(db, site.id),
        "site_progress": float(site.progress_percent or 0),
        "templates": templates,
    }


# --- daily reports -------------------------------------------------------------------------------


def _dpr_out(d: Dpr) -> dict:
    a = d.auto or {}
    lab = a.get("labour", {})
    return {
        "id": d.id,
        "on_date": d.on_date,
        "weather": d.weather,
        "work_done": d.work_done,
        "hindrances": d.hindrances,
        "next_day_plan": d.next_day_plan,
        "status": d.status,
        "photos": [{"id": p.id, "caption": p.caption or p.filename} for p in d.photos],
        "tasks": [
            {
                "where": t.get("where"),
                "name": t.get("name"),
                "status": t.get("status"),
                "percent": t.get("percent"),
            }
            for t in a.get("tasks", [])
        ],
        "material_in": [r.get("items") for r in a.get("received", [])],
        "material_used": [r.get("items") for r in a.get("issued", []) if r.get("kind") == "issue"],
        # headcount only: never names or wages
        "headcount": {
            "present": lab.get("present", 0),
            "half_day": lab.get("half_day", 0),
            "by_trade": lab.get("by_trade", {}),
        },
        "equipment": [u.get("asset") for u in a.get("equipment", [])],
    }


def _dpr(db, ctx, site_id, dpr_id) -> tuple[Site, Dpr]:
    site = svc.portal_site(db, ctx, site_id, "dpr")
    d = db.get(Dpr, dpr_id)
    if d is None or d.site_id != site.id or d.status == "draft":
        raise svc.not_found("Report not found")
    return site, d


@router.get("/sites/{site_id}/dprs")
def dprs(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = svc.portal_site(db, ctx, site_id, "dpr")
    q = (
        select(Dpr)
        .where(Dpr.site_id == site.id, Dpr.status != "draft")
        .order_by(Dpr.on_date.desc())
        .limit(120)
    )
    return [_dpr_out(d) for d in db.scalars(q)]


@router.get("/sites/{site_id}/dprs/{dpr_id}/pdf")
def dpr_pdf(site_id: int, dpr_id: int, db: DbSession, ctx: Ctx):
    site, d = _dpr(db, ctx, site_id, dpr_id)
    out = {
        "auto": d.auto or {},
        "submitted_by_name": names(db, [d.submitted_by]).get(d.submitted_by),
    }
    return pdf_response(xpdf.dpr(db, site, out, d, client=True), f"DPR-{site.code}-{d.on_date}")


@router.get("/sites/{site_id}/dprs/{dpr_id}/photos/{photo_id}")
def dpr_photo(site_id: int, dpr_id: int, photo_id: int, db: DbSession, ctx: Ctx):
    _site, d = _dpr(db, ctx, site_id, dpr_id)
    p = next((x for x in d.photos if x.id == photo_id), None)
    return send_file(p.stored_path if p else None, p.filename if p else None)


# --- photos --------------------------------------------------------------------------------------


@router.get("/sites/{site_id}/photos")
def photos(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    """Task photos staff shared with the client, newest first."""
    site = svc.portal_site(db, ctx, site_id, "photos")
    from app.sites import service as sites_service

    paths = sites_service.path_names(sites_service.nodes(db, site.id))
    rows = db.execute(
        select(TaskPhoto, Task.name, Task.node_id)
        .join(Task, Task.id == TaskPhoto.task_id)
        .where(Task.site_id == site.id, TaskPhoto.share_with_client)
        .order_by(TaskPhoto.created_at.desc())
        .limit(500)
    ).all()
    return [
        {"id": p.id, "taken_on": p.created_at.date(), "step": name, "area": paths.get(node_id, "")}
        for p, name, node_id in rows
    ]


@router.get("/sites/{site_id}/photos/{photo_id}")
def photo_file(site_id: int, photo_id: int, db: DbSession, ctx: Ctx):
    site = svc.portal_site(db, ctx, site_id, "photos")
    p = db.get(TaskPhoto, photo_id)
    task = db.get(Task, p.task_id) if p else None
    if p is None or not p.share_with_client or task.site_id != site.id:
        raise svc.not_found("Photo not found")
    return send_file(p.stored_path, p.filename)


# --- inspections and MOM -------------------------------------------------------------------------


def _insp_out(db, i: Inspection) -> dict:
    task = db.get(Task, i.task_id) if i.task_id else None
    return {
        "id": i.id,
        "code": i.code,
        "checklist": i.template.name,
        "on_date": i.on_date,
        "result": i.result,
        "step": task.name if task else None,
        "remark": i.remark,
        "client_rep": i.client_rep,
        "client_signoff": i.client_signoff,
        "client_signed_name": i.client_signed_name,
        "client_signed_at": i.client_signed_at,
        "answers": [{"text": a.get("text"), "value": a.get("value")} for a in i.answers],
    }


def _inspection(db, ctx, site_id, iid) -> tuple[Site, Inspection]:
    site = svc.portal_site(db, ctx, site_id, "inspections")
    i = db.get(Inspection, iid)
    if i is None or i.site_id != site.id:
        raise svc.not_found("Inspection not found")
    return site, i


@router.get("/sites/{site_id}/inspections")
def inspections(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = svc.portal_site(db, ctx, site_id, "inspections")
    return [
        _insp_out(db, i)
        for i in db.scalars(
            select(Inspection).where(Inspection.site_id == site.id).order_by(Inspection.id.desc())
        )
    ]


@router.get("/sites/{site_id}/inspections/{iid}/pdf")
def inspection_pdf(site_id: int, iid: int, db: DbSession, ctx: Ctx):
    from app.execution.inspections import _insp_out as staff_out

    _site, i = _inspection(db, ctx, site_id, iid)
    return pdf_response(xpdf.inspection(db, i, staff_out(db, i)), i.code)


class SignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    signature: str  # PNG data URL drawn on screen


@router.post("/sites/{site_id}/inspections/{iid}/sign")
def sign_inspection(
    site_id: int, iid: int, body: SignIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    """The client representative signs an inspection that waits for their sign-off."""
    svc.need(ctx, "portal.approve")
    site, i = _inspection(db, ctx, site_id, iid)
    if i.client_signoff != "waiting":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This inspection is not waiting for your sign-off"
        )
    if not body.signature.startswith("data:image/png;base64,"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Draw the signature on screen")
    data = base64.b64decode(body.signature.split(",", 1)[1], validate=True)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The signature image is too large"
        )
    rel = f"inspections/{i.id}/client-signature-{uuid.uuid4().hex[:8]}.png"
    media(rel).parent.mkdir(parents=True, exist_ok=True)
    media(rel).write_bytes(data)
    i.client_signoff, i.client_signed_name, i.client_signed_by = "signed", body.name, ctx.user.id
    i.client_signed_at, i.client_signature_path = svc.now(), rel
    if not i.client_rep:
        i.client_rep = body.name
    if not i.signature_path:
        i.signature_path = rel
    _audit(db, request, ctx, "portal.inspection.sign", "inspection", i.id, {"name": body.name})
    svc.tell_staff(
        db,
        site.id,
        "inspection_signed",
        f"{i.code} signed by the client ({body.name})",
        f"/sites/{site.id}?tab=inspections",
    )
    db.commit()
    return _insp_out(db, i)


@router.get("/sites/{site_id}/moms")
def moms(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = svc.portal_site(db, ctx, site_id, "inspections")
    mine = _client_ids(db, ctx)
    out = []
    for m in db.scalars(select(Mom).where(Mom.site_id == site.id).order_by(Mom.on_date.desc())):
        out.append(
            {
                "id": m.id,
                "code": m.code,
                "on_date": m.on_date,
                "title": m.title,
                "venue": m.venue,
                "notes": m.notes,
                "attendees": m.attendee_others,
                "points": [
                    {
                        "id": p.id,
                        "text": p.text,
                        "due_date": p.due_date,
                        "status": p.status,
                        "yours": p.owner_user_id in mine
                        or (p.owner_user_id is None and bool(p.owner_name)),
                        "owner": p.owner_name,
                        "acknowledged_at": p.client_acknowledged_at,
                    }
                    for p in m.points
                ],
            }
        )
    return out


@router.get("/sites/{site_id}/moms/{mid}/pdf")
def mom_pdf(site_id: int, mid: int, db: DbSession, ctx: Ctx):
    from app.execution.inspections import _mom_out

    site = svc.portal_site(db, ctx, site_id, "inspections")
    m = db.get(Mom, mid)
    if m is None or m.site_id != site.id:
        raise svc.not_found("MOM not found")
    return pdf_response(xpdf.mom(db, _mom_out(db, m)), m.code)


@router.post("/sites/{site_id}/mom-points/{pid}/acknowledge")
def acknowledge_point(site_id: int, pid: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    svc.need(ctx, "portal.approve")
    site = svc.portal_site(db, ctx, site_id, "inspections")
    p = db.get(MomPoint, pid)
    m = db.get(Mom, p.mom_id) if p else None
    if p is None or m.site_id != site.id:
        raise svc.not_found("Point not found")
    p.client_acknowledged_at, p.client_acknowledged_by = svc.now(), ctx.user.id
    _audit(db, request, ctx, "portal.mom.acknowledge", "mom", m.id, {"point": p.id})
    svc.tell_staff(
        db,
        site.id,
        "mom_acknowledged",
        f"{m.code}: the client acknowledged '{p.text[:80]}'",
        f"/sites/{site.id}?tab=mom",
    )
    db.commit()
    return {"id": p.id, "acknowledged_at": p.client_acknowledged_at}


# --- drawings and documents ----------------------------------------------------------------------


@router.get("/sites/{site_id}/documents")
def documents(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = svc.portal_site(db, ctx, site_id, "documents")
    out = []
    for d in db.scalars(
        select(Drawing).where(
            Drawing.site_id == site.id,
            Drawing.share_with_client,
            Drawing.current_revision_id.is_not(None),
        )
    ):
        rev = db.get(DrawingRevision, d.current_revision_id)
        out.append(
            {
                "key": f"drawing-{d.id}",
                "title": d.title,
                "kind": "drawing",
                "source": "EESPL",
                "revision": f"R{rev.rev_no}",
                "filename": rev.filename,
                "date": rev.created_at.date(),
                "url": f"/api/portal/sites/{site.id}/documents/drawing-{d.id}",
            }
        )
    for doc in db.scalars(
        select(SiteDocument).where(SiteDocument.site_id == site.id).order_by(SiteDocument.id.desc())
    ):
        if doc.source == "staff" and not doc.share_with_client:
            continue
        out.append(
            {
                "key": f"doc-{doc.id}",
                "title": doc.title,
                "kind": doc.kind,
                "source": "You" if doc.source == "client" else "EESPL",
                "revision": None,
                "filename": doc.filename,
                "date": doc.created_at.date(),
                "url": f"/api/portal/sites/{site.id}/documents/doc-{doc.id}",
            }
        )
    return out


@router.get("/sites/{site_id}/documents/{key}")
def document_file(site_id: int, key: str, request: Request, db: DbSession, ctx: Ctx):
    site = svc.portal_site(db, ctx, site_id, "documents")
    kind, _, raw = key.partition("-")
    if not raw.isdigit():
        raise svc.not_found("File not found")
    if kind == "drawing":
        d = db.get(Drawing, int(raw))
        if (
            d is None
            or d.site_id != site.id
            or not d.share_with_client
            or not d.current_revision_id
        ):
            raise svc.not_found("File not found")
        rev = db.get(DrawingRevision, d.current_revision_id)
        return send_file(rev.stored_path, rev.filename)
    doc = db.get(SiteDocument, int(raw)) if kind == "doc" else None
    if (
        doc is None
        or doc.site_id != site.id
        or (doc.source == "staff" and not doc.share_with_client)
    ):
        raise svc.not_found("File not found")
    return send_file(doc.stored_path, doc.filename)


@router.post("/sites/{site_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    site_id: int,
    request: Request,
    db: DbSession,
    ctx: Ctx,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    kind: Annotated[str, Form(pattern="^(drawing|document)$")] = "drawing",
) -> dict:
    """The client's own drawing or document (kept apart from EESPL's); staff are told."""
    svc.need(ctx, "portal.comment")
    site = svc.portal_site(db, ctx, site_id, "documents")
    rel, name = await save_upload(file, f"portal/client-uploads/{site.id}")
    doc = SiteDocument(
        site_id=site.id,
        title=title,
        kind=kind,
        source="client",
        stored_path=rel,
        filename=name,
        created_by=ctx.user.id,
    )
    db.add(doc)
    db.flush()
    _audit(
        db,
        request,
        ctx,
        "portal.upload",
        "site_document",
        doc.id,
        {"site": site.code, "file": name},
    )
    svc.tell_staff(
        db,
        site.id,
        "client_upload",
        f"The client uploaded '{title}' on {site.code}",
        f"/sites/{site.id}?tab=portal",
    )
    db.commit()
    return {"key": f"doc-{doc.id}", "title": doc.title, "filename": doc.filename}


# --- billing -------------------------------------------------------------------------------------

RA_LINE_KEYS = (
    "contract_line_id",
    "item_no",
    "description",
    "unit",
    "boq_qty",
    "previous_qty",
    "qty",
    "certified_qty",
    "cumulative_qty",
    "rate",
    "amount",
    "certified_amount",
)


def _ra_client(db, b: RaBill) -> dict:
    full = _ra_out(db, b)
    lines = {ln.contract_line_id: ln for ln in b.lines}
    return {
        **{
            k: full[k]
            for k in (
                "id",
                "code",
                "seq",
                "period_from",
                "period_to",
                "status",
                "gross",
                "certified_gross",
                "retention",
                "retention_percent",
                "advance_recovery",
                "other_deduction",
                "other_deduction_remark",
                "net",
                "invoice_number",
            )
        },
        "client_remark": b.client_remark,
        "lines": [
            {
                **{k: ln[k] for k in RA_LINE_KEYS},
                "your_qty": lines[ln["contract_line_id"]].client_qty,
            }
            for ln in full["lines"]
            if Decimal(ln["qty"]) or Decimal(ln["previous_qty"])
        ],
    }


INVOICE_KEYS = (
    "id",
    "number",
    "kind",
    "invoice_date",
    "due_date",
    "taxable",
    "cgst",
    "sgst",
    "igst",
    "total",
    "retention",
    "advance_recovery",
    "outstanding",
    "retention_held",
    "due",
    "age_days",
    "credit_notes",
)


def _ra(db, ctx, site_id, rid) -> tuple[Site, RaBill]:
    site = svc.portal_site(db, ctx, site_id, "billing")
    b = db.get(RaBill, rid)
    if b is None or b.site_id != site.id or b.status in ("draft", "cancelled"):
        raise svc.not_found("Bill not found")
    return site, b


@router.get("/sites/{site_id}/billing")
def billing(site_id: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    site = svc.portal_site(db, ctx, site_id, "billing")
    contract = db.scalar(select(ClientContract).where(ClientContract.site_id == site.id))
    bills = db.scalars(
        select(RaBill)
        .where(RaBill.site_id == site.id, RaBill.status.not_in(("draft", "cancelled")))
        .order_by(RaBill.seq.desc())
    ).all()
    invs = list(
        db.scalars(
            select(TaxInvoice)
            .where(TaxInvoice.site_id == site.id, TaxInvoice.status == "issued")
            .order_by(TaxInvoice.invoice_date.desc(), TaxInvoice.id.desc())
        )
    )
    invoices = [{k: _invoice_out(db, i)[k] for k in INVOICE_KEYS} for i in invs]
    receipts = db.scalars(
        select(Receipt)
        .where(
            Receipt.id.in_(
                select(ReceiptAllocation.receipt_id)
                .join(TaxInvoice, TaxInvoice.id == ReceiptAllocation.invoice_id)
                .where(TaxInvoice.site_id == site.id)
            )
            | (Receipt.site_id == site.id)
        )
        .order_by(Receipt.on_date.desc())
    ).all()
    buckets = dict.fromkeys(("0-30", "31-60", "61-90", "90+"), ZERO)
    due = ZERO
    for p in fsvc.invoice_positions(db, [i for i in invs if i.kind == "invoice"], today()):
        buckets[fsvc.bucket(p["age"])] += p["due"]
        due += p["due"]
    _retained, released, held = fsvc.retention_held(db, site.id)
    _audit(db, request, ctx, "portal.billing.view", "site", site.id)
    db.commit()
    return {
        "contract": {
            "value": contract.contract_value,
            "retention_percent": contract.retention_percent,
            "gst_percent": contract.gst_percent,
        }
        if contract
        else None,
        "ra_bills": [_ra_client(db, b) for b in bills],
        "invoices": invoices,
        "receipts": [
            {
                "number": r.number,
                "on_date": r.on_date,
                "mode": r.mode,
                "ref_no": r.ref_no,
                "amount": r.amount,
                "tds_amount": r.tds_amount,
                "gst_tds_amount": r.gst_tds_amount,
                "is_advance": r.is_advance,
            }
            for r in receipts
        ],
        "outstanding": {
            "due": due,
            **buckets,
            "retention_held": held,
            "retention_released": released,
        },
    }


@router.get("/sites/{site_id}/ra-bills/{rid}/pdf")
def ra_pdf(site_id: int, rid: int, request: Request, db: DbSession, ctx: Ctx):
    _site, b = _ra(db, ctx, site_id, rid)
    _audit(db, request, ctx, "portal.bill.view", "ra_bill", b.id)
    db.commit()
    return pdf_response(fpdf.ra_bill(db, _ra_out(db, b)), b.code)


@router.get("/sites/{site_id}/invoices/{iid}/pdf")
def invoice_pdf(site_id: int, iid: int, request: Request, db: DbSession, ctx: Ctx):
    site = svc.portal_site(db, ctx, site_id, "billing")
    inv = db.get(TaxInvoice, iid)
    if inv is None or inv.site_id != site.id or inv.status != "issued":
        raise svc.not_found("Invoice not found")
    _audit(db, request, ctx, "portal.bill.view", "tax_invoice", inv.id)
    db.commit()
    return pdf_response(
        fpdf.tax_invoice(db, inv, _invoice_out(db, inv)), inv.number.replace("/", "-")
    )


class ClientCertLine(BaseModel):
    contract_line_id: int
    qty: Decimal = Field(ge=0)


class ClientCertIn(BaseModel):
    lines: list[ClientCertLine] = []  # a line left out: as submitted
    remark: str | None = None


class RemarkIn(BaseModel):
    remark: str = Field(min_length=1)


@router.post("/sites/{site_id}/ra-bills/{rid}/certify")
def client_certify(
    site_id: int, rid: int, body: ClientCertIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    """The client certifies a submitted RA bill with their qty per line. It only becomes the
    certified figure when EESPL confirms."""
    svc.need(ctx, "portal.approve")
    site, b = _ra(db, ctx, site_id, rid)
    if b.status != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.code} is {b.status}")
    given = {x.contract_line_id: x.qty for x in body.lines}
    for ln in b.lines:
        q = given.get(ln.contract_line_id, Decimal(ln.qty))
        if q > Decimal(ln.qty):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "You cannot certify more than was billed"
            )
        ln.client_qty = q
    b.status, b.client_remark, b.client_acted_by, b.client_acted_at = (
        "certified_by_client",
        body.remark,
        ctx.user.id,
        svc.now(),
    )
    _audit(
        db,
        request,
        ctx,
        "portal.ra.certify",
        "ra_bill",
        b.id,
        {"lines": {str(k): str(v) for k, v in given.items()}},
    )
    svc.tell_staff(
        db,
        site.id,
        "ra_certified",
        f"{b.code} certified by the client: please confirm",
        f"/sites/{site.id}?tab=finance",
    )
    db.commit()
    return _ra_client(db, b)


@router.post("/sites/{site_id}/ra-bills/{rid}/reject")
def client_reject(
    site_id: int, rid: int, body: RemarkIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    svc.need(ctx, "portal.approve")
    site, b = _ra(db, ctx, site_id, rid)
    if b.status != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.code} is {b.status}")
    b.status, b.client_remark, b.client_acted_by, b.client_acted_at = (
        "rejected_by_client",
        body.remark,
        ctx.user.id,
        svc.now(),
    )
    _audit(db, request, ctx, "portal.ra.reject", "ra_bill", b.id, {"remark": body.remark})
    svc.tell_staff(
        db,
        site.id,
        "ra_rejected",
        f"{b.code} rejected by the client: {body.remark[:80]}",
        f"/sites/{site.id}?tab=finance",
    )
    db.commit()
    return _ra_client(db, b)


# --- snags ---------------------------------------------------------------------------------------


def snag_out(db, s: Snag, client: bool = True) -> dict:
    node = db.get(SiteNode, s.node_id) if s.node_id else None
    who = names(db, [s.assigned_to, s.created_by])
    out = {
        "id": s.id,
        "code": s.code,
        "site_id": s.site_id,
        "title": s.title,
        "description": s.description,
        "area": node.name if node else s.area,
        "node_id": s.node_id,
        "status": s.status,
        "raised_by_side": s.raised_by_side,
        "due_date": s.due_date,
        "reopened": s.reopened,
        "created_at": s.created_at,
        "fixed_at": s.fixed_at,
        "verified_at": s.verified_at,
        "photos": [{"id": p.id, "kind": p.kind, "filename": p.filename} for p in s.photos],
    }
    if not client:
        out |= {
            "assigned_to": str(s.assigned_to) if s.assigned_to else None,
            "assigned_to_name": who.get(s.assigned_to),
            "raised_by_name": who.get(s.created_by),
        }
    return out


def _snag(db, ctx, site_id, sid) -> tuple[Site, Snag]:
    site = svc.portal_site(db, ctx, site_id, "snags")
    s = db.get(Snag, sid)
    if s is None or s.site_id != site.id:
        raise svc.not_found("Snag not found")
    return site, s


@router.get("/sites/{site_id}/snags")
def snags(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = svc.portal_site(db, ctx, site_id, "snags")
    return [
        snag_out(db, s)
        for s in db.scalars(select(Snag).where(Snag.site_id == site.id).order_by(Snag.id.desc()))
    ]


@router.post("/sites/{site_id}/snags", status_code=status.HTTP_201_CREATED)
async def raise_snag(
    site_id: int,
    request: Request,
    db: DbSession,
    ctx: Ctx,
    title: Annotated[str, Form(min_length=1, max_length=300)],
    description: Annotated[str | None, Form()] = None,
    node_id: Annotated[int | None, Form()] = None,
    area: Annotated[str | None, Form(max_length=200)] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    svc.need(ctx, "portal.snag")
    site = svc.portal_site(db, ctx, site_id, "snags")
    if node_id is not None:
        n = db.get(SiteNode, node_id)
        if n is None or n.site_id != site.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That place is not on this site"
            )
    from app.material.service import next_code

    s = Snag(
        code=next_code(db, "SNG"),
        site_id=site.id,
        node_id=node_id,
        area=area,
        title=title,
        description=description,
        raised_by_side="client",
        created_by=ctx.user.id,
    )
    db.add(s)
    db.flush()
    for f in photos or []:
        if f.filename:
            rel, name = await save_upload(f, f"snags/{s.id}")
            s.photos.append(
                SnagPhoto(kind="before", stored_path=rel, filename=name, created_by=ctx.user.id)
            )
    _audit(
        db,
        request,
        ctx,
        "portal.snag.raise",
        "snag",
        s.id,
        {"title": title, "photos": len(s.photos)},
    )
    svc.tell_staff(
        db,
        site.id,
        "snag_raised",
        f"{s.code}: the client raised '{title[:80]}'",
        f"/snags?open={s.id}",
    )
    db.commit()
    db.refresh(s)
    return snag_out(db, s)


@router.post("/sites/{site_id}/snags/{sid}/verify")
def verify_snag(site_id: int, sid: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    svc.need(ctx, "portal.snag")
    site, s = _snag(db, ctx, site_id, sid)
    if s.status != "fixed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}")
    s.status, s.verified_at = "verified", svc.now()
    _audit(db, request, ctx, "portal.snag.verify", "snag", s.id)
    svc.tell_staff(
        db, site.id, "snag_verified", f"{s.code} verified by the client", f"/snags?open={s.id}"
    )
    db.commit()
    return snag_out(db, s)


@router.post("/sites/{site_id}/snags/{sid}/reopen")
def reopen_snag(
    site_id: int, sid: int, body: RemarkIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    svc.need(ctx, "portal.snag")
    site, s = _snag(db, ctx, site_id, sid)
    if s.status not in ("fixed", "verified"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}")
    s.status, s.reopened, s.fixed_at, s.verified_at = "open", s.reopened + 1, None, None
    db.add(
        Comment(
            site_id=site.id,
            entity_type="snag",
            entity_id=s.id,
            body=f"Reopened: {body.remark}",
            author_id=ctx.user.id,
            author_side="client",
        )
    )
    _audit(db, request, ctx, "portal.snag.reopen", "snag", s.id, {"remark": body.remark})
    svc.tell_staff(
        db,
        site.id,
        "snag_reopened",
        f"{s.code} reopened by the client: {body.remark[:80]}",
        f"/snags?open={s.id}",
    )
    db.commit()
    return snag_out(db, s)


@router.get("/sites/{site_id}/snags/{sid}/photos/{pid}")
def snag_photo(site_id: int, sid: int, pid: int, db: DbSession, ctx: Ctx):
    _site, s = _snag(db, ctx, site_id, sid)
    p = next((x for x in s.photos if x.id == pid), None)
    return send_file(p.stored_path if p else None, p.filename if p else None)


# --- comments ------------------------------------------------------------------------------------


def entity_site(db, entity_type: str, entity_id: int, client: bool) -> tuple[int, str] | None:
    """(site id, portal section) of a commentable thing; None if a client may not see it."""
    if entity_type == "dpr":
        d = db.get(Dpr, entity_id)
        return (d.site_id, "dpr") if d and (not client or d.status != "draft") else None
    if entity_type == "inspection":
        i = db.get(Inspection, entity_id)
        return (i.site_id, "inspections") if i else None
    if entity_type == "snag":
        s = db.get(Snag, entity_id)
        return (s.site_id, "snags") if s else None
    if entity_type == "ra_bill":
        b = db.get(RaBill, entity_id)
        return (
            (b.site_id, "billing")
            if b and (not client or b.status not in ("draft", "cancelled"))
            else None
        )
    return None


def comment_out(db, c: Comment, who: dict) -> dict:
    return {
        "id": c.id,
        "body": c.body,
        "internal": c.internal,
        "author": who.get(c.author_id),
        "side": c.author_side,
        "created_at": c.created_at,
    }


class CommentIn(BaseModel):
    entity_type: str = Field(pattern="^(dpr|inspection|snag|ra_bill)$")
    entity_id: int
    body: str = Field(min_length=1, max_length=4000)


def _thread(db, ctx, entity_type, entity_id) -> int:
    found = entity_site(db, entity_type, entity_id, client=True)
    if found is None:
        raise svc.not_found("Not found")
    site = svc.portal_site(db, ctx, found[0], found[1])
    return site.id


@router.get("/comments")
def comments(entity_type: str, entity_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    """The thread, without staff's internal notes."""
    _thread(db, ctx, entity_type, entity_id)
    rows = list(
        db.scalars(
            select(Comment)
            .where(
                Comment.entity_type == entity_type,
                Comment.entity_id == entity_id,
                Comment.internal.is_(False),
            )
            .order_by(Comment.id)
        )
    )
    who = names(db, [c.author_id for c in rows])
    return [comment_out(db, c, who) for c in rows]


@router.post("/comments", status_code=status.HTTP_201_CREATED)
def add_comment(body: CommentIn, request: Request, db: DbSession, ctx: Ctx) -> dict:
    svc.need(ctx, "portal.comment")
    site_id = _thread(db, ctx, body.entity_type, body.entity_id)
    c = Comment(
        site_id=site_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        body=body.body,
        author_id=ctx.user.id,
        author_side="client",
    )
    db.add(c)
    db.flush()
    _audit(db, request, ctx, "portal.comment", body.entity_type, body.entity_id)
    svc.tell_staff(
        db,
        site_id,
        "comment",
        f"Client comment on {body.entity_type.replace('_', ' ')}: {body.body[:80]}",
        f"/sites/{site_id}?tab=portal",
    )
    db.commit()
    return comment_out(db, c, names(db, [c.author_id]))


__all__ = ["date"]
