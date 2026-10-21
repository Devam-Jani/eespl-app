# ruff: noqa: E501
"""The client's side in the portal (only their own sites, by their client roles):
- planning enters and updates the promised handover dates;
- site signs RFIs;
- billing approves or corrects measurements and signs the work completion;
- accounts and the project manager see the overdue bills.

Clients are told inside the portal only: in-app notices and the overdue list, never an email."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import audit
from app.closeout import billing as bsvc
from app.closeout import completion as csvc
from app.closeout import measure as msvc
from app.closeout.common import locked, not_found, now, today
from app.closeout.models import ClientRoleDef, RfiZone, WorkCompletion
from app.db import DbSession
from app.finance.models import RaBill
from app.portal import service as portal
from app.portal.models import ClientUser
from app.sites.models import AreaScope, SiteNode
from app.team.models import Measurement

router = APIRouter(prefix="/api/portal", tags=["portal: close-out"])
Ctx = Annotated[portal.PortalCtx, Depends(portal.portal_ctx)]


def _audit(db, request: Request, ctx, action: str, entity: str, ident, after=None) -> None:
    audit.record(
        db, action, entity, ident, user_id=ctx.user.id, after=after, ip=audit.client_ip(request)
    )


@router.get("/me/roles")
def my_roles(db: DbSession, ctx: Ctx) -> dict:
    roles: set[str] = set()
    for r in db.scalars(select(ClientUser.roles).where(ClientUser.user_id == ctx.user.id)):
        roles |= set(r or [])
    rights = portal.rights_of(db, ctx.user.id)
    labels = {d.code: d.label for d in db.scalars(select(ClientRoleDef))}
    return {
        "roles": [{"code": r, "label": labels.get(r, r)} for r in sorted(roles)],
        "rights": sorted(rights) if rights is not None else None,
    }


# --- handover dates -------------------------------------------------------------------------------


@router.get("/sites/{site_id}/handover")
def handover(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    from app.schedule import service as schedule  # noqa: PLC0415

    site = portal.portal_site(db, ctx, site_id, "handover")
    out = []
    for n in db.scalars(
        select(SiteNode)
        .where(
            SiteNode.site_id == site.id,
            SiteNode.kind.in_(("tower", "wing", "floor", "flat", "basement", "terrace", "podium"))
            | SiteNode.id.in_(select(AreaScope.node_id).where(AreaScope.site_id == site.id)),  # the areas we work on
        )
        .order_by(SiteNode.sort_order, SiteNode.id)
    ):
        s = schedule.node_schedule(db, n)
        out.append({"node_id": n.id, "name": n.name, "kind": n.kind, "parent_id": n.parent_id, "promised_on": n.handover_promised_on, "promised_by": n.handover_promised_by,
                    "status": n.handover_status, "received_on": n.handover_received_on, "client_delay_days": s.get("client_delay_days"),
                    "client_promised_on": s.get("client_promised_on"), "moved_to": s.get("moved_to"), "moved_because": s.get("moved_because")})  # fmt: skip
    return out


class PromiseIn(BaseModel):
    promised_on: date


@router.put("/sites/{site_id}/nodes/{node_id}/handover-promise")
def promise(
    site_id: int, node_id: int, body: PromiseIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    """The client's planning role: the date they promise to hand the place over."""
    portal.need(ctx, "portal.comment")
    portal.need_right(db, ctx, "handover.edit")
    site = portal.portal_site(db, ctx, site_id, "handover")
    n = db.get(SiteNode, node_id)
    if n is None or n.site_id != site.id:
        raise not_found("Place not found")
    if n.handover_status == "received":
        raise locked(f"{n.name}'s handover (received on {n.handover_received_on:%d.%m.%Y})")
    n.handover_promised_on, n.handover_promised_by, n.handover_promised_entered_by = (
        body.promised_on,
        f"{ctx.user.full_name} (client, in the portal)",
        ctx.user.id,
    )
    from app.closeout import handover  # noqa: PLC0415

    handover.note(n, "promised", body.promised_on, f"{ctx.user.full_name} (client, in the portal)")
    portal.tell_staff(
        db,
        site.id,
        "handover_promised",
        f"{n.name}: the client promises handover by {body.promised_on:%d.%m.%Y}",
        f"/sites/{site.id}?tab=handover",
    )
    _audit(
        db,
        request,
        ctx,
        "portal.handover.promise",
        "site_node",
        n.id,
        after={"promised_on": body.promised_on.isoformat()},
    )
    db.commit()
    return {
        "node_id": n.id,
        "promised_on": n.handover_promised_on,
        "promised_by": n.handover_promised_by,
    }


# --- measurements -----------------------------------------------------------------------------------


def _line(db, site_id: int, mid: int) -> Measurement:
    m = db.get(Measurement, mid)
    if m is None or m.site_id != site_id or m.status == "draft":
        raise not_found("Measurement not found")
    return m


@router.get("/sites/{site_id}/measurements")
def measurements(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = portal.portal_site(db, ctx, site_id, "measurements")
    rows = db.scalars(
        select(Measurement)
        .where(
            Measurement.site_id == site.id,
            Measurement.status.in_(("sent", "approved")),
            Measurement.set_id.is_not(None),
        )
        .order_by(Measurement.measured_on, Measurement.id)
    )
    return [msvc.line_out(db, m) for m in rows]


@router.post("/sites/{site_id}/measurements/{mid}/approve")
def approve(site_id: int, mid: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    portal.need(ctx, "portal.approve")
    portal.need_right(db, ctx, "measurement.approve")
    site = portal.portal_site(db, ctx, site_id, "measurements")
    m = _line(db, site.id, mid)
    msvc.client_approve(db, m, ctx.user)
    portal.tell_staff(
        db,
        site.id,
        "measurement_approved",
        f"Measurement #{m.id} approved by {ctx.user.full_name}",
        f"/sites/{site.id}?tab=measurements",
    )
    _audit(
        db,
        request,
        ctx,
        "portal.measurement.approve",
        "measurement",
        m.id,
        after={"qty": str(m.qty)},
    )
    db.commit()
    return msvc.line_out(db, m)


class CorrectIn(BaseModel):
    field: str
    new_value: Decimal | str  # metres, or feet and inches as typed ("19 ft 5 in")
    remark: str | None = Field(default=None, max_length=1000)


@router.post("/sites/{site_id}/measurements/{mid}/correct")
def correct(
    site_id: int, mid: int, body: CorrectIn, request: Request, db: DbSession, ctx: Ctx
) -> dict:
    portal.need(ctx, "portal.approve")
    portal.need_right(db, ctx, "measurement.approve")
    site = portal.portal_site(db, ctx, site_id, "measurements")
    m = _line(db, site.id, mid)
    c = msvc.client_correct(db, m, body.field, body.new_value, body.remark, ctx.user)
    portal.tell_staff(
        db,
        site.id,
        "measurement_corrected",
        f"Measurement #{m.id}: {body.field} {c.old_value} -> {c.new_value} by {ctx.user.full_name}",
        f"/sites/{site.id}?tab=measurements",
    )
    _audit(
        db,
        request,
        ctx,
        "portal.measurement.correct",
        "measurement",
        m.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return msvc.line_out(db, m)


# --- RFI zones ----------------------------------------------------------------------------------------


@router.get("/sites/{site_id}/zones")
def zones(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = portal.portal_site(db, ctx, site_id, "inspections")
    return [{"id": z.id, "name": z.name, "ours": z.ours, "other_applicator": z.other_applicator, "signed_at": z.signed_at, "signed_name": z.signed_name}
            for z in db.scalars(select(RfiZone).where(RfiZone.site_id == site.id).order_by(RfiZone.id))]  # fmt: skip


@router.post("/sites/{site_id}/zones/{zid}/sign")
def sign_zone(site_id: int, zid: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    portal.need(ctx, "portal.approve")
    portal.need_right(db, ctx, "inspection.sign")
    site = portal.portal_site(db, ctx, site_id, "inspections")
    z = db.get(RfiZone, zid)
    if z is None or z.site_id != site.id:
        raise not_found("Zone not found")
    if z.signed_at:
        raise locked(f"RFI {z.name} (signed)")
    z.signed_at, z.signed_by_user, z.signed_name, z.recorded_by_staff = (
        now(),
        ctx.user.id,
        ctx.user.full_name,
        False,
    )
    _audit(db, request, ctx, "portal.zone.sign", "rfi_zone", z.id)
    db.commit()
    return {"id": z.id, "signed_at": z.signed_at, "signed_name": z.signed_name}


# --- overdue bills ------------------------------------------------------------------------------------


@router.get("/sites/{site_id}/overdue")
def overdue(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    """The bills past their due date (the client's accounts and project manager)."""
    site = portal.portal_site(db, ctx, site_id, "billing")
    portal.need_right(db, ctx, "payment.view")
    day = today()
    out = []
    for b in db.scalars(
        select(RaBill)
        .where(RaBill.site_id == site.id, RaBill.status.in_(("certified", "invoiced")))
        .order_by(RaBill.id)
    ):
        row = bsvc.bill_out(db, b, day)
        if row["overdue_days"]:
            out.append(
                {
                    k: row[k]
                    for k in (
                        "id",
                        "code",
                        "invoice",
                        "invoice_date",
                        "outstanding",
                        "due_on",
                        "overdue_days",
                        "at",
                    )
                }
            )
    return out


# --- work completion ---------------------------------------------------------------------------------


@router.get("/sites/{site_id}/work-completions")
def wccs(site_id: int, db: DbSession, ctx: Ctx) -> list[dict]:
    site = portal.portal_site(db, ctx, site_id, "documents")
    return [{"id": w.id, "code": w.code, "completion_date": w.completion_date, "guarantee_years": w.guarantee_years, "guarantee_expiry": w.guarantee_expiry,
             "status": w.status, "signed_name": w.signed_name, "areas": len(w.areas)} for w in db.scalars(select(WorkCompletion).where(WorkCompletion.site_id == site.id).order_by(WorkCompletion.id))]  # fmt: skip


@router.get("/sites/{site_id}/work-completions/{wid}/pdf")
def wcc_pdf(site_id: int, wid: int, db: DbSession, ctx: Ctx) -> Response:
    site = portal.portal_site(db, ctx, site_id, "documents")
    w = db.get(WorkCompletion, wid)
    if w is None or w.site_id != site.id:
        raise not_found("Certificate not found")
    return Response(
        csvc.pdf(csvc.html(db, w)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{w.code}.pdf"'},
    )


@router.post("/sites/{site_id}/work-completions/{wid}/sign")
def sign_wcc(site_id: int, wid: int, request: Request, db: DbSession, ctx: Ctx) -> dict:
    """The client's billing engineer or project manager signs the certificate: locked forever."""
    portal.need(ctx, "portal.approve")
    portal.need_right(db, ctx, "bill.certify", "measurement.approve")
    site = portal.portal_site(db, ctx, site_id, "documents")
    w = db.get(WorkCompletion, wid)
    if w is None or w.site_id != site.id:
        raise not_found("Certificate not found")
    csvc.sign(db, w, ctx.user.full_name, ctx.user.id, False, None)
    portal.tell_staff(
        db,
        site.id,
        "wcc_signed",
        f"{w.code} signed by {ctx.user.full_name}",
        f"/sites/{site.id}?tab=closeout",
    )
    _audit(db, request, ctx, "portal.wcc.sign", "work_completion", w.id)
    db.commit()
    return {"id": w.id, "status": w.status, "signed_name": w.signed_name, "signed_at": w.signed_at}
