# ruff: noqa: E501  (response shapes read better unwrapped)
"""The staff side of the work order, billing and close-out milestone.

Permissions: wo.view / wo.edit (the work order check; sales: their own), closeout.billing
(measurements, the billing checklist, bill tracking, work completion), closeout.site (zones, RFI,
handover, quality checklist on own sites), closeout.payments (payment follow-up, the client's
billing cycle), issues.view / issues.edit (the issue log, by allocation). Planning and the director
hold all of them. Locked records (an accepted work order, an approved measurement, a signed work
completion) give 409 to every role."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

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
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_any_permission, require_permission
from app.closeout import billing as bsvc
from app.closeout import completion as csvc
from app.closeout import issues as isvc
from app.closeout import measure as msvc
from app.closeout import recon as rsvc
from app.closeout import tendering as tsvc
from app.closeout import workorder as wsvc
from app.closeout.common import locked, next_code, not_found, today, unprocessable
from app.closeout.models import (
    CLIENT_RIGHTS,
    ClientBillingCycle,
    ClientRoleDef,
    ClientWorkOrder,
    IssueComment,
    LabourClaim,
    MeasurementChange,
    RfiZone,
    SiteIssueLog,
    TenderCustomer,
    WoDeviation,
    WorkCompletion,
)
from app.db import DbSession
from app.execution.common import media, save_upload
from app.finance.models import RaBill
from app.models import User
from app.sites.models import Site, SiteMember, SiteNode
from app.team.models import Measurement

router = APIRouter(prefix="/api/closeout", tags=["work order, billing, close-out"])
WoView = Annotated[str, Depends(require_permission("wo.view"))]
WoEdit = Annotated[str, Depends(require_permission("wo.edit"))]
Billing = Annotated[str, Depends(require_permission("closeout.billing"))]
SiteTeam = Annotated[str, Depends(require_permission("closeout.site"))]
Payments = Annotated[str, Depends(require_permission("closeout.payments"))]
BillsView = Annotated[str, Depends(require_any_permission("closeout.billing", "closeout.payments"))]
CompletionEdit = Annotated[
    str, Depends(require_any_permission("closeout.billing", "closeout.site"))
]
IssueView = Annotated[str, Depends(require_permission("issues.view"))]
IssueEdit = Annotated[str, Depends(require_permission("issues.edit"))]
DOC_TYPES = frozenset({".xlsx", ".xlsm"})


def record(
    db: Session,
    request: Request,
    principal: Principal,
    action: str,
    entity: str,
    ident,
    before=None,
    after=None,
) -> None:
    audit.record(
        db,
        action,
        entity,
        ident,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def site_ok(db: Session, scope: str, principal: Principal, site_id: int | None) -> bool:
    """all: every site; assigned or own: the sites the person is allocated to."""
    if scope == "all":
        return True
    if site_id is None:
        return False
    uid = principal.user.id
    s = db.get(Site, site_id)
    return bool(
        s
        and (
            s.site_incharge_id == uid
            or db.scalar(
                select(SiteMember.site_id).where(
                    SiteMember.site_id == site_id, SiteMember.user_id == uid
                )
            )
        )
    )


def get_site(db: Session, site_id: int, scope: str, principal: Principal) -> Site:
    s = db.get(Site, site_id)
    if s is None or not site_ok(db, scope, principal, site_id):
        raise not_found("Site not found")
    return s


def allowed_sites(db: Session, scope: str, principal: Principal) -> list[int] | None:
    if scope == "all":
        return None
    uid = principal.user.id
    return list(
        set(db.scalars(select(SiteMember.site_id).where(SiteMember.user_id == uid)))
        | set(db.scalars(select(Site.id).where(Site.site_incharge_id == uid)))
    )


# --- 1. one tender, several civil contractors -----------------------------------------------------


def _tender(db: Session, tid: int, principal: Principal, edit: bool = False):
    from app.tenders import service as tenders  # noqa: PLC0415

    code = "tender.edit" if edit else "tender.view"
    scope = principal.permissions.get(code)
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {code}")
    return tenders.get_visible(db, tid, scope, principal)


@router.get("/tenders/{tid}/customers")
def tender_customers(tid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    t = _tender(db, tid, principal)
    from app.masters.models import Client  # noqa: PLC0415

    main = db.get(Client, t.main_contractor_id) if t.main_contractor_id else None
    return {
        "tender_id": t.id,
        "status": t.status,
        "main_contractor": main.name if main else None,
        "customers": tsvc.customers_out(db, t),
    }


class CustomerIn(BaseModel):
    client_id: int
    note: str | None = None


@router.post("/tenders/{tid}/customers", status_code=status.HTTP_201_CREATED)
def add_customer(
    tid: int, body: CustomerIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = _tender(db, tid, principal, edit=True)
    c = tsvc.add_customer(db, t, body.client_id, principal.user.id, body.note)
    record(
        db,
        request,
        principal,
        "tender.customer.add",
        "tender",
        t.id,
        after={"client_id": body.client_id, "quotation_id": c.quotation_id},
    )
    db.commit()
    return tender_customers(tid, db, principal)


@router.post("/tenders/{tid}/customers/{cid}/main-won")
def main_won(
    tid: int, cid: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = _tender(db, tid, principal, edit=True)
    c = db.get(TenderCustomer, cid)
    if c is None:
        raise not_found("Customer not found")
    out = tsvc.main_won(db, t, c, principal.user.id)
    record(db, request, principal, "tender.main_won", "tender", t.id, after=out)
    db.commit()
    return tender_customers(tid, db, principal)


# --- 2. the work order check ----------------------------------------------------------------------


def wo_out(db: Session, wo: ClientWorkOrder) -> dict:
    from app.quotations.models import Quotation  # noqa: PLC0415

    q = db.get(Quotation, wo.quotation_id) if wo.quotation_id else None
    return {"id": wo.id, "code": wo.code, "client_ref": wo.client_ref, "tender_id": wo.tender_id, "site_id": wo.site_id, "client_id": wo.client_id,
            "quotation": {"id": q.id, "code": q.code, "revision": q.revision} if q else None, "file_name": wo.file_name, "lines_from": wo.lines_from,
            "status": wo.status, "locked": wo.status == "accepted", "accepted_at": wo.accepted_at,
            "terms": {"payment_basis": wo.payment_basis, "payment_days": wo.payment_days, "retention_percent": wo.retention_percent, "retention_release": wo.retention_release,
                      "advance_percent": wo.advance_percent, "penalty": wo.penalty, "time_limit_days": wo.time_limit_days, "guarantee_years": wo.guarantee_years,
                      "scope_on_us": wo.scope_on_us, "scope_on_client": wo.scope_on_client},
            "ours": wsvc.our_terms(q) if q else None,
            "lines": [{"id": ln.id, "item_no": ln.item_no, "description": ln.description, "unit": ln.unit, "qty": ln.qty, "rate": ln.rate} for ln in wo.lines],
            "deviations": [{"id": d.id, "kind": d.kind, "topic": d.topic, "ours": d.ours, "theirs": d.theirs, "status": d.status, "note": d.note, "amend_text": d.amend_text} for d in wo.deviations],
            "open": sum(1 for d in wo.deviations if d.status == "open")}  # fmt: skip


def _wo(db: Session, wid: int, scope: str, principal: Principal) -> ClientWorkOrder:
    wo = db.get(ClientWorkOrder, wid)
    if wo is None:
        raise not_found("Work order not found")
    if scope != "all":
        from app.quotations.models import Quotation  # noqa: PLC0415

        q = db.get(Quotation, wo.quotation_id) if wo.quotation_id else None
        if not (
            (q and q.salesperson_id == principal.user.id)
            or site_ok(db, scope, principal, wo.site_id)
            or wo.created_by == principal.user.id
        ):
            raise not_found("Work order not found")
    return wo


@router.get("/work-orders")
def work_orders(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: WoView,
    site_id: int | None = None,
    tender_id: int | None = None,
) -> list[dict]:
    q = select(ClientWorkOrder).order_by(ClientWorkOrder.id.desc())
    if site_id:
        q = q.where(ClientWorkOrder.site_id == site_id)
    if tender_id:
        q = q.where(ClientWorkOrder.tender_id == tender_id)
    out = []
    for wo in db.scalars(q.limit(200)):
        try:
            _wo(db, wo.id, scope, principal)
        except HTTPException:
            continue
        out.append(wo_out(db, wo))
    return out


class WoIn(BaseModel):
    quotation_id: int
    tender_id: int | None = None
    site_id: int | None = None
    client_ref: str | None = Field(default=None, max_length=100)


@router.post("/work-orders", status_code=status.HTTP_201_CREATED)
def create_wo(
    body: WoIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: WoEdit
) -> dict:
    from app.quotations.models import Quotation  # noqa: PLC0415

    q = db.get(Quotation, body.quotation_id)
    if q is None:
        raise not_found("Quotation not found")
    wo = ClientWorkOrder(code=next_code(db, ClientWorkOrder, "CWO"), client_ref=body.client_ref, quotation_id=q.id, tender_id=body.tender_id or q.tender_id,
                         site_id=body.site_id or q.site_id, client_id=q.client_id, created_by=principal.user.id)  # fmt: skip
    db.add(wo)
    db.flush()
    record(db, request, principal, "wo.create", "client_work_order", wo.id, after={"code": wo.code})
    db.commit()
    return wo_out(db, wo)


@router.get("/work-orders/{wid}")
def get_wo(wid: int, db: DbSession, principal: CurrentPrincipal, scope: WoView) -> dict:
    return wo_out(db, _wo(db, wid, scope, principal))


class TermsIn(BaseModel):
    client_ref: str | None = None
    site_id: int | None = None
    payment_basis: Literal["invoice", "certification", "final_bill"] | None = None
    payment_days: int | None = Field(default=None, ge=0, le=720)
    retention_percent: Decimal | None = Field(default=None, ge=0, le=100)
    retention_release: str | None = None
    advance_percent: Decimal | None = Field(default=None, ge=0, le=100)
    penalty: str | None = None
    time_limit_days: int | None = Field(default=None, ge=0, le=3650)
    guarantee_years: int | None = Field(default=None, ge=0, le=50)
    scope_on_us: list[str] | None = None
    scope_on_client: list[str] | None = None


@router.put("/work-orders/{wid}")
def set_terms(
    wid: int,
    body: TermsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: WoEdit,
) -> dict:
    wo = _wo(db, wid, scope, principal)
    wsvc.guard(wo)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(wo, k, v)
    record(
        db,
        request,
        principal,
        "wo.terms",
        "client_work_order",
        wo.id,
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return wo_out(db, wo)


@router.post("/work-orders/{wid}/file")
async def upload_wo(
    wid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: WoEdit,
    file: Annotated[UploadFile, File()],
) -> dict:
    wo = _wo(db, wid, scope, principal)
    wsvc.guard(wo)
    rel, name = await save_upload(file, f"work-orders/{wo.code}", DOC_TYPES)
    lines, text = wsvc.read_file(media(rel))
    wo.file_path, wo.file_name = rel, name
    if lines:
        wsvc.set_lines(db, wo, lines, "file")
    terms = wsvc.terms_from_text(text)
    for k, v in terms.items():
        if v not in (None, [], "") and getattr(wo, k) in (None, [], ""):
            setattr(wo, k, v)
    record(
        db,
        request,
        principal,
        "wo.file",
        "client_work_order",
        wo.id,
        after={"file": name, "lines": len(lines), "terms": list(terms)},
    )
    db.commit()
    db.refresh(wo)
    return {
        **wo_out(db, wo),
        "read": {
            "lines": len(lines),
            "terms": [k for k, v in terms.items() if v not in (None, [], "")],
        },
    }


class LineIn(BaseModel):
    item_no: str | None = None
    description: str = Field(min_length=1)
    unit: str | None = None
    qty: Decimal | None = None
    rate: Decimal | None = None
    product_id: int | None = None


class LinesIn(BaseModel):
    lines: list[LineIn]


@router.put("/work-orders/{wid}/lines")
def set_wo_lines(
    wid: int,
    body: LinesIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: WoEdit,
) -> dict:
    wo = _wo(db, wid, scope, principal)
    wsvc.set_lines(db, wo, [ln.model_dump() for ln in body.lines], "typed")
    record(
        db,
        request,
        principal,
        "wo.lines",
        "client_work_order",
        wo.id,
        after={"lines": len(body.lines)},
    )
    db.commit()
    db.refresh(wo)
    return wo_out(db, wo)


@router.post("/work-orders/{wid}/copy-quotation")
def copy_quotation(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: WoEdit
) -> dict:
    wo = _wo(db, wid, scope, principal)
    wsvc.copy_from_quotation(db, wo)
    record(db, request, principal, "wo.copy_quotation", "client_work_order", wo.id)
    db.commit()
    db.refresh(wo)
    return wo_out(db, wo)


@router.post("/work-orders/{wid}/compare")
def compare(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: WoEdit
) -> dict:
    wo = _wo(db, wid, scope, principal)
    devs = wsvc.compare(db, wo)
    record(
        db,
        request,
        principal,
        "wo.compare",
        "client_work_order",
        wo.id,
        after={"deviations": len(devs)},
    )
    db.commit()
    db.refresh(wo)
    return wo_out(db, wo)


class ResolveIn(BaseModel):
    action: Literal["accept", "amend"]
    note: str = Field(min_length=2, max_length=2000)
    amend_text: str | None = None


@router.post("/work-orders/{wid}/deviations/{did}")
def resolve(
    wid: int,
    did: int,
    body: ResolveIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: WoEdit,
) -> dict:
    wo = _wo(db, wid, scope, principal)
    d = db.get(WoDeviation, did)
    if d is None or d.work_order_id != wo.id:
        raise not_found("Deviation not found")
    wsvc.resolve(db, wo, d, body.action, body.note, body.amend_text, principal.user)
    record(db, request, principal, "wo.deviation", "wo_deviation", d.id, after=body.model_dump())
    db.commit()
    db.refresh(wo)
    return wo_out(db, wo)


@router.post("/work-orders/{wid}/accept")
def accept_wo(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: WoEdit
) -> dict:
    wo = _wo(db, wid, scope, principal)
    wsvc.accept(db, wo, principal.user)
    record(db, request, principal, "wo.accept", "client_work_order", wo.id, after={"code": wo.code})
    db.commit()
    return wo_out(db, wo)


@router.delete("/work-orders/{wid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wo(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: WoEdit
) -> None:
    wo = _wo(db, wid, scope, principal)
    wsvc.guard(wo)
    record(
        db, request, principal, "wo.delete", "client_work_order", wo.id, before={"code": wo.code}
    )
    db.delete(wo)
    db.commit()


# --- 3. client roles (Settings > Client roles) ----------------------------------------------------

PortalManage = Annotated[str, Depends(require_permission("portal.manage"))]


@router.get("/client-roles")
def client_roles(db: DbSession, _: PortalManage) -> dict:
    return {
        "rights": list(CLIENT_RIGHTS),
        "roles": [
            {"code": r.code, "label": r.label, "rights": r.rights}
            for r in db.scalars(select(ClientRoleDef).order_by(ClientRoleDef.sort_order))
        ],
    }


class RoleIn(BaseModel):
    label: str | None = None
    rights: list[str]


@router.put("/client-roles/{code}")
def set_client_role(
    code: str,
    body: RoleIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PortalManage,
) -> dict:
    r = db.get(ClientRoleDef, code)
    if r is None:
        raise not_found("Client role not found")
    bad = set(body.rights) - set(CLIENT_RIGHTS)
    if bad:
        raise unprocessable(f"Unknown rights: {', '.join(sorted(bad))}")
    before = {"rights": r.rights}
    r.rights, r.label = sorted(set(body.rights)), body.label or r.label
    record(
        db,
        request,
        principal,
        "client_role.update",
        "client_role",
        code,
        before=before,
        after={"rights": r.rights},
    )
    db.commit()
    return client_roles(db, "all")


class UserRolesIn(BaseModel):
    roles: list[str]


@router.put("/client-users/{uid}/roles")
def set_user_roles(
    uid: str,
    body: UserRolesIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PortalManage,
) -> dict:
    from app.portal.models import ClientUser  # noqa: PLC0415

    known = set(db.scalars(select(ClientRoleDef.code)))
    if set(body.roles) - known:
        raise unprocessable("Unknown client role")
    rows = list(db.scalars(select(ClientUser).where(ClientUser.user_id == uid)))
    if not rows:
        raise not_found("Client user not found")
    for r in rows:
        r.roles = sorted(set(body.roles))
    record(db, request, principal, "client_user.roles", "user", uid, after={"roles": body.roles})
    db.commit()
    return {"user_id": uid, "roles": sorted(set(body.roles))}


# --- 4. handover moved by the site engineer ------------------------------------------------------


class MoveIn(BaseModel):
    promised_on: date
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/sites/{site_id}/nodes/{node_id}/handover-move")
def move_handover(
    site_id: int,
    node_id: int,
    body: MoveIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteTeam,
) -> dict:
    """The site engineer moves the promised handover date, with the reason; the client sees the
    new date and gets an in-app notice."""
    site = get_site(db, site_id, scope, principal)
    node = db.get(SiteNode, node_id)
    if node is None or node.site_id != site.id:
        raise not_found("Place not found")
    before = {"promised_on": node.handover_promised_on}
    node.handover_promised_on = body.promised_on
    node.handover_promised_by = f"moved by {principal.user.full_name}: {body.reason}"[:200]
    node.handover_promised_entered_by = principal.user.id
    from app.portal import service as portal  # noqa: PLC0415

    portal.tell_clients(
        db,
        site.id,
        "handover",
        "handover_moved",
        f"{node.name}: handover date moved to {body.promised_on:%d.%m.%Y} ({body.reason})",
        f"/portal/sites/{site.id}?tab=handover",
    )
    record(
        db,
        request,
        principal,
        "handover.move",
        "site_node",
        node.id,
        before={"promised_on": str(before["promised_on"])},
        after=body.model_dump(mode="json"),
    )
    db.commit()
    from app.schedule import service as schedule  # noqa: PLC0415

    return schedule.node_schedule(db, node)


# --- 5. measurements approved by the client ------------------------------------------------------


class MeasureIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    contract_line_id: int | None = None
    node_id: int | None = None
    cad_area_id: int | None = None
    unit: str | None = None  # the contract line's (the work order's) when not given
    # metres (5.918) or feet and inches as typed ("19 ft 5 in"): stored in metres
    length_m: Decimal | str | None = None
    breadth_m: Decimal | str | None = None
    perimeter_m: Decimal | str | None = None
    height_m: Decimal | str | None = None
    deductions_sqm: Decimal | None = None
    qty: Decimal | None = None
    measured_on: date | None = None
    note: str | None = None
    zone_reason: str | None = None


def _m(db: Session, mid: int, scope: str, principal: Principal) -> Measurement:
    m = db.get(Measurement, mid)
    if m is None or not site_ok(db, scope, principal, m.site_id):
        raise not_found("Measurement not found")
    return m


@router.get("/sites/{site_id}/measurements")
def measurements(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing) -> dict:
    site = get_site(db, site_id, scope, principal)
    rows = list(
        db.scalars(
            select(Measurement)
            .where(Measurement.site_id == site.id)
            .order_by(Measurement.measured_on, Measurement.id)
        )
    )
    return {"site_id": site.id, "needs_approval": site.measurements_need_approval, "lines": [msvc.line_out(db, m) for m in rows],
            "zones": db.scalar(select(RfiZone.id).where(RfiZone.site_id == site.id).limit(1)) is not None}  # fmt: skip


class ApprovalFlagIn(BaseModel):
    needs_approval: bool


@router.put("/sites/{site_id}/measurement-approval")
def approval_flag(
    site_id: int,
    body: ApprovalFlagIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    site.measurements_need_approval = body.needs_approval
    record(
        db,
        request,
        principal,
        "site.measurement_approval",
        "site",
        site.id,
        after=body.model_dump(),
    )
    db.commit()
    return {"site_id": site.id, "needs_approval": site.measurements_need_approval}


@router.post("/sites/{site_id}/measurements", status_code=status.HTTP_201_CREATED)
def add_measurement(
    site_id: int,
    body: MeasureIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    m, warning = msvc.write(db, site, body.model_dump(), principal.user)
    record(
        db,
        request,
        principal,
        "measurement.create",
        "measurement",
        m.id,
        after={**body.model_dump(mode="json"), "qty": str(m.qty), "warning": warning},
    )
    db.commit()
    return {**msvc.line_out(db, m), "warning": warning}


@router.put("/measurements/{mid}")
def update_measurement(
    mid: int,
    body: MeasureIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> dict:
    m = _m(db, mid, scope, principal)
    before = msvc.line_out(db, m)
    msvc.update(db, m, body.model_dump(exclude_unset=True))
    record(
        db,
        request,
        principal,
        "measurement.update",
        "measurement",
        m.id,
        before={k: str(v) for k, v in before.items() if k != "changes"},
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return msvc.line_out(db, m)


@router.delete("/measurements/{mid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(
    mid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Billing
) -> None:
    m = _m(db, mid, scope, principal)
    msvc.guard(m)
    if m.status == "sent":
        raise unprocessable("The client has this line")
    record(
        db,
        request,
        principal,
        "measurement.delete",
        "measurement",
        m.id,
        before={"qty": str(m.qty), "description": m.description},
    )
    db.delete(m)
    db.commit()


@router.post("/measurements/{mid}/photos")
async def measurement_photo(
    mid: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
    file: Annotated[UploadFile, File()],
) -> dict:
    m = _m(db, mid, scope, principal)
    msvc.guard(m)
    rel, name = await save_upload(file, f"measurements/{m.site_id}")
    m.photos = [*(m.photos or []), {"path": rel, "name": name}]
    db.commit()
    return msvc.line_out(db, m)


class SendIn(BaseModel):
    ids: list[int]
    title: str | None = None


@router.post("/sites/{site_id}/measurement-sets")
def send_set(
    site_id: int,
    body: SendIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    s = msvc.send(db, site, body.ids, body.title, principal.user)
    record(
        db,
        request,
        principal,
        "measurement.send",
        "measurement_set",
        s.id,
        after={"code": s.code, "ids": body.ids},
    )
    db.commit()
    return {"id": s.id, "code": s.code, "lines": len(body.ids)}


class AnswerIn(BaseModel):
    accept: bool
    reply: str | None = None


@router.post("/measurement-changes/{cid}/answer")
def answer_change(
    cid: int,
    body: AnswerIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> dict:
    c = db.get(MeasurementChange, cid)
    if c is None:
        raise not_found("Correction not found")
    m = _m(db, c.measurement_id, scope, principal)
    msvc.answer(db, m, c, body.accept, body.reply, principal.user)
    record(
        db,
        request,
        principal,
        "measurement.correction.answer",
        "measurement_change",
        c.id,
        after=body.model_dump(),
    )
    db.commit()
    return msvc.line_out(db, m)


@router.post("/measurements/{mid}/record-approval")
async def record_approval(
    mid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Billing,
    approved_name: Annotated[str, Form(min_length=2, max_length=200)], on_date: Annotated[date | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:  # fmt: skip
    """The client signed the paper sheet: recorded by our staff, with the signed copy."""
    m = _m(db, mid, scope, principal)
    msvc.guard(m)
    rel = None
    if file is not None:
        rel, _name = await save_upload(file, f"measurements/{m.site_id}/signed")
    msvc.record_approval(db, m, approved_name, on_date, rel, principal.user)
    record(
        db,
        request,
        principal,
        "measurement.approval_recorded",
        "measurement",
        m.id,
        after={"approved_name": approved_name, "copy": rel},
    )
    db.commit()
    return msvc.line_out(db, m)


def sheet_rows(db: Session, site: Site) -> tuple[list[str], list[list]]:
    cols = [
        "#",
        "Place",
        "Description",
        "L",
        "B",
        "Perimeter",
        "Height",
        "Deductions",
        "Qty",
        "Unit",
        "Status",
        "Approved by",
        "Approved on",
        "Corrections",
    ]
    rows = []
    for i, m in enumerate(
        db.scalars(
            select(Measurement)
            .where(Measurement.site_id == site.id)
            .order_by(Measurement.measured_on, Measurement.id)
        ),
        1,
    ):
        ln = msvc.line_out(db, m)
        corr = "; ".join(
            f"{c['field']} {c['old_shown']} -> {c['new_shown']} by {c['by']} on {c['at']:%d.%m.%Y %H:%M} ({c['status']}{': ' + c['remark'] if c['remark'] else ''})"
            for c in ln["changes"]
        )
        size = ln["shown"]
        rows.append([i, ln["place"] or "", ln["description"], size.get("length_m", ""), size.get("breadth_m", ""), size.get("perimeter_m", ""), size.get("height_m", ""),
                     m.deductions_sqm, m.qty, m.unit, m.status,
                     (m.approved_name or "") + (" (recorded by staff)" if m.recorded_by_staff else ""), m.approved_at.strftime("%d.%m.%Y") if m.approved_at else "", corr])  # fmt: skip
    return cols, rows


@router.get("/sites/{site_id}/measurement-sheet.xlsx")
def sheet_xlsx(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing
) -> Response:
    from app.export import xlsx_response  # noqa: PLC0415

    site = get_site(db, site_id, scope, principal)
    cols, rows = sheet_rows(db, site)
    return xlsx_response(f"measurements-{site.code}", cols, rows)


@router.get("/sites/{site_id}/measurement-sheet.pdf")
def sheet_pdf(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing) -> Response:
    from html import escape  # noqa: PLC0415

    site = get_site(db, site_id, scope, principal)
    cols, rows = sheet_rows(db, site)
    body = f"<h2 class='c'>MEASUREMENT SHEET — {escape(site.code)} {escape(site.name)}</h2><table class='wcc'><thead><tr>{''.join(f'<th>{escape(c)}</th>' for c in cols)}</tr></thead><tbody>"
    body += (
        "".join(
            "<tr>" + "".join(f"<td>{escape('' if v is None else str(v))}</td>" for v in r) + "</tr>"
            for r in rows
        )
        + "</tbody></table>"
    )
    data = csvc.pdf(csvc._page(db, f"MB {site.code}", body))
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="measurements-{site.code}.pdf"'},
    )


# --- 6. RFI zones, the billing checklist, the quality checklist ----------------------------------


def zone_out(db: Session, z: RfiZone) -> dict:
    node = db.get(SiteNode, z.node_id) if z.node_id else None
    return {"id": z.id, "name": z.name, "node_id": z.node_id, "place": node.name if node else None, "ours": z.ours, "other_applicator": z.other_applicator,
            "outline": z.outline, "cad_file_id": z.cad_file_id, "signed_at": z.signed_at, "signed_name": z.signed_name, "recorded_by_staff": z.recorded_by_staff}  # fmt: skip


@router.get("/sites/{site_id}/zones")
def zones(site_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    scope = principal.permissions.get("closeout.site") or principal.permissions.get(
        "closeout.billing"
    )
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: closeout.site")
    site = get_site(db, site_id, scope, principal)
    from app.closeout.completion import _path  # noqa: PLC0415

    nodes = [
        {
            "id": n.id,
            "parent_id": n.parent_id,
            "kind": n.kind,
            "name": n.name,
            "path": _path(db, n.id),
        }
        for n in db.scalars(
            select(SiteNode)
            .where(SiteNode.site_id == site.id)
            .order_by(SiteNode.sort_order, SiteNode.id)
        )
    ]
    return {
        "site_id": site.id,
        "zones": [
            zone_out(db, z)
            for z in db.scalars(
                select(RfiZone).where(RfiZone.site_id == site.id).order_by(RfiZone.id)
            )
        ],
        "nodes": nodes,
    }


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    node_id: int | None = None
    ours: bool = True
    other_applicator: str | None = None
    outline: list[list[float]] | None = None
    cad_file_id: int | None = None


@router.post("/sites/{site_id}/zones", status_code=status.HTTP_201_CREATED)
def add_zone(
    site_id: int,
    body: ZoneIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteTeam,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    if not body.ours and not (body.other_applicator or "").strip():
        raise unprocessable("Name the applicator the zone went to")
    if body.node_id and (n := db.get(SiteNode, body.node_id)) and n.site_id != site.id:
        raise not_found("Place not found")
    z = RfiZone(site_id=site.id, created_by=principal.user.id, **body.model_dump())
    db.add(z)
    db.flush()
    record(db, request, principal, "zone.create", "rfi_zone", z.id, after=body.model_dump())
    db.commit()
    return zone_out(db, z)


@router.post("/zones/{zid}/record-signature")
async def record_zone_signature(
    zid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: SiteTeam,
    signed_name: Annotated[str, Form(min_length=2)], file: Annotated[UploadFile, File()],
) -> dict:  # fmt: skip
    z = db.get(RfiZone, zid)
    if z is None or not site_ok(db, scope, principal, z.site_id):
        raise not_found("Zone not found")
    if z.signed_at:
        raise locked(f"RFI {z.name} (signed)")
    rel, _n = await save_upload(file, f"rfi/{z.site_id}")
    from app.closeout.common import now  # noqa: PLC0415

    z.signed_at, z.signed_name, z.recorded_by_staff, z.signed_copy_path = (
        now(),
        signed_name,
        True,
        rel,
    )
    record(
        db,
        request,
        principal,
        "zone.signature_recorded",
        "rfi_zone",
        z.id,
        after={"signed_name": signed_name},
    )
    db.commit()
    return zone_out(db, z)


@router.delete("/zones/{zid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: SiteTeam
) -> None:
    z = db.get(RfiZone, zid)
    if z is None or not site_ok(db, scope, principal, z.site_id):
        raise not_found("Zone not found")
    if z.signed_at:
        raise locked(f"RFI {z.name} (signed)")
    record(db, request, principal, "zone.delete", "rfi_zone", z.id, before={"name": z.name})
    db.delete(z)
    db.commit()


@router.get("/sites/{site_id}/billing-checklist")
def billing_checklist(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
    tower_id: int | None = None,
    month: str | None = None,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    towers = list(
        db.scalars(
            select(SiteNode)
            .where(SiteNode.site_id == site.id, SiteNode.kind.in_(("tower", "wing")))
            .order_by(SiteNode.sort_order, SiteNode.id)
        )
    )
    if not towers:
        return {"site_id": site.id, "towers": [], "columns": [], "rows": [], "counts": {}}
    t = next((x for x in towers if x.id == tower_id), towers[0])
    from app.finance.models import RaBill as RB  # noqa: PLC0415

    months = sorted(
        {
            b.period_to.strftime("%Y-%m")
            for b in db.scalars(select(RB).where(RB.site_id == site.id))
            if b.period_to
        }
    )
    return {
        **msvc.checklist(db, site, t.id, month),
        "towers": [{"id": x.id, "name": x.name} for x in towers],
        "tower_id": t.id,
        "months": months,
    }


@router.get("/sites/{site_id}/billing-checklist.xlsx")
def billing_checklist_xlsx(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
    tower_id: int | None = None,
    month: str | None = None,
) -> Response:
    from app.export import xlsx_response  # noqa: PLC0415

    g = billing_checklist(site_id, db, principal, scope, tower_id, month)
    rows = [
        [r["flat"], *[(r["cells"].get(c) or {}).get("label", "") for c in g["columns"]]]
        for r in g["rows"]
    ]
    return xlsx_response(f"billing-checklist-{site_id}", ["Flat", *g["columns"]], rows)


@router.get("/sites/{site_id}/nodes/{node_id}/quality")
def quality(
    site_id: int, node_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteTeam
) -> dict:
    site = get_site(db, site_id, scope, principal)
    node = db.get(SiteNode, node_id)
    if node is None or node.site_id != site.id:
        raise not_found("Place not found")
    return {"node_id": node.id, "place": node.name, "stages": msvc.quality(db, site, node.id)}


class StageDatesIn(BaseModel):
    stage_started_on: date | None = None
    stage_ended_on: date | None = None


@router.put("/inspections/{iid}/stage-dates")
def stage_dates(
    iid: int,
    body: StageDatesIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteTeam,
) -> dict:
    from app.execution.models import Inspection  # noqa: PLC0415

    i = db.get(Inspection, iid)
    if i is None or not site_ok(db, scope, principal, i.site_id):
        raise not_found("Inspection not found")
    i.stage_started_on, i.stage_ended_on = body.stage_started_on, body.stage_ended_on
    record(
        db,
        request,
        principal,
        "inspection.stage_dates",
        "inspection",
        i.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return {"id": i.id, "stage_started_on": i.stage_started_on, "stage_ended_on": i.stage_ended_on}


@router.post("/inspections/{iid}/client-sign-record")
async def record_client_sign(
    iid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: SiteTeam,
    signed_name: Annotated[str, Form(min_length=2)], file: Annotated[UploadFile, File()],
) -> dict:  # fmt: skip
    """The client signed the paper checklist: recorded by our staff, with the copy."""
    from app.closeout.common import now  # noqa: PLC0415
    from app.execution.models import Inspection  # noqa: PLC0415

    i = db.get(Inspection, iid)
    if i is None or not site_ok(db, scope, principal, i.site_id):
        raise not_found("Inspection not found")
    if i.client_signoff == "signed":
        raise locked(f"Inspection {i.code} (signed by the client)")
    rel, _n = await save_upload(file, f"inspections/{i.site_id}/client")
    i.client_signoff, i.client_signed_name, i.client_signed_at = "signed", signed_name, now()
    i.client_recorded_by_staff, i.client_signed_copy_path = True, rel
    record(
        db,
        request,
        principal,
        "inspection.client_sign_recorded",
        "inspection",
        i.id,
        after={"signed_name": signed_name},
    )
    db.commit()
    return {
        "id": i.id,
        "client_signoff": i.client_signoff,
        "client_signed_name": i.client_signed_name,
        "recorded_by_staff": True,
    }


# --- 7-8. billing cycle, bill tracking, payment follow-up -----------------------------------------


def cycle_out(c: ClientBillingCycle | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "client_id": c.client_id, "site_id": c.site_id, "submit_from_day": c.submit_from_day, "submit_to_day": c.submit_to_day,
            "ho_from_day": c.ho_from_day, "ho_to_day": c.ho_to_day, "payment_days": c.payment_days, "note": c.note}  # fmt: skip


class CycleIn(BaseModel):
    site_id: int | None = None
    submit_from_day: int = Field(ge=1, le=31)
    submit_to_day: int = Field(ge=1, le=31)
    ho_from_day: int = Field(ge=1, le=31)
    ho_to_day: int = Field(ge=1, le=31)
    payment_days: int = Field(ge=0, le=365)
    note: str | None = None


@router.get("/clients/{client_id}/billing-cycle")
def get_cycle(client_id: int, db: DbSession, _: Payments) -> list[dict]:
    return [
        cycle_out(c)
        for c in db.scalars(
            select(ClientBillingCycle)
            .where(ClientBillingCycle.client_id == client_id)
            .order_by(ClientBillingCycle.site_id.nulls_first())
        )
    ]


@router.put("/clients/{client_id}/billing-cycle")
def set_cycle(
    client_id: int,
    body: CycleIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Payments,
) -> dict:
    c = db.scalar(
        select(ClientBillingCycle).where(
            ClientBillingCycle.client_id == client_id,
            (ClientBillingCycle.site_id == body.site_id)
            if body.site_id
            else ClientBillingCycle.site_id.is_(None),
        )
    )
    if c is None:
        c = ClientBillingCycle(
            client_id=client_id, site_id=body.site_id, created_by=principal.user.id
        )
        db.add(c)
    for k, v in body.model_dump(exclude={"site_id"}).items():
        setattr(c, k, v)
    db.flush()
    record(
        db, request, principal, "billing_cycle.set", "client", client_id, after=body.model_dump()
    )
    db.commit()
    return cycle_out(c)


@router.get("/bills")
def bills(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillsView,
    site_id: int | None = None,
    overdue: bool = False,
) -> list[dict]:
    q = select(RaBill).where(RaBill.status != "cancelled").order_by(RaBill.id.desc())
    if site_id:
        q = q.where(RaBill.site_id == site_id)
    allowed = allowed_sites(db, scope, principal)
    if allowed is not None:
        q = q.where(RaBill.site_id.in_(allowed or [0]))
    day = today()
    out = []
    for b in db.scalars(q.limit(300)):
        row = bsvc.bill_out(db, b, day)
        if overdue and not row["overdue_days"]:
            continue
        site = db.get(Site, b.site_id)
        cyc = bsvc.cycle_for(db, site) if site else None
        row["site"] = f"{site.code} {site.name}" if site else None
        row["cycle"] = cycle_out(cyc)
        if "tender.margin" not in principal.permissions:
            row.pop("cost", None)
        out.append(row)
    return out


def _bill(db: Session, rid: int, scope: str, principal: Principal) -> RaBill:
    b = db.get(RaBill, rid)
    if b is None or not site_ok(db, scope, principal, b.site_id):
        raise not_found("Bill not found")
    return b


@router.post("/bills/{rid}/steps")
async def add_step(
    rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Billing,
    step: Annotated[str, Form()], on_date: Annotated[date, Form()], by_name: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None, file: Annotated[UploadFile | None, File()] = None,
) -> dict:  # fmt: skip
    b = _bill(db, rid, scope, principal)
    rel = name = None
    if file is not None:
        rel, name = await save_upload(file, f"bills/{b.site_id}")
    s = bsvc.add_step(db, b, step, on_date, principal.user.id, by_name, note, rel, name)
    record(
        db,
        request,
        principal,
        "bill.step",
        "ra_bill",
        b.id,
        after={"step": step, "on": on_date.isoformat(), "file": name},
    )
    db.commit()
    return {**bsvc.bill_out(db, b, today()), "step_id": s.id}


class FollowIn(BaseModel):
    spoke_to: str = Field(min_length=2, max_length=200)
    said: str = Field(min_length=2, max_length=4000)
    promised_on: date | None = None


@router.post("/bills/{rid}/followups")
def add_followup(
    rid: int,
    body: FollowIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Payments,
) -> dict:
    b = _bill(db, rid, scope, principal)
    bsvc.log_followup(db, b, body.spoke_to, body.said, body.promised_on, principal.user.id)
    record(
        db,
        request,
        principal,
        "payment.followup",
        "ra_bill",
        b.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return bsvc.bill_out(db, b, today())


class SettingsIn(BaseModel):
    bill_stuck_days: int = Field(ge=1, le=90)
    bill_stuck_escalate_days: int = Field(ge=0, le=90)
    overdue_salesperson_days: int = Field(ge=0, le=180)
    overdue_director_days: int = Field(ge=0, le=365)


@router.get("/settings")
def get_settings(db: DbSession, _: BillsView) -> dict:
    s = bsvc.settings(db)
    db.commit()
    return {k: getattr(s, k) for k in SettingsIn.model_fields}


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    if "process.rules" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: process.rules")
    s = bsvc.settings(db)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    record(
        db, request, principal, "closeout.settings", "closeout_settings", 1, after=body.model_dump()
    )
    db.commit()
    return body.model_dump()


# --- 9. work completion and guarantee ------------------------------------------------------------


def wcc_out(db: Session, w: WorkCompletion) -> dict:
    site = db.get(Site, w.site_id)
    return {"id": w.id, "code": w.code, "site_id": w.site_id, "site": f"{site.code} {site.name}" if site else None, "addendum_of_id": w.addendum_of_id,
            "completion_date": w.completion_date, "started_on": w.started_on, "guarantee_years": w.guarantee_years, "guarantee_from": w.guarantee_from,
            "guarantee_expiry": w.guarantee_expiry, "areas": w.areas, "systems": w.systems, "products": w.products, "note": w.note, "status": w.status,
            "locked": w.status == "signed", "signed_name": w.signed_name, "signed_at": w.signed_at, "recorded_by_staff": w.recorded_by_staff, "is_demo": w.is_demo}  # fmt: skip


def _w(db: Session, wid: int, scope: str, principal: Principal) -> WorkCompletion:
    w = db.get(WorkCompletion, wid)
    if w is None or not site_ok(db, scope, principal, w.site_id):
        raise not_found("Work completion not found")
    return w


@router.get("/sites/{site_id}/work-completions")
def site_wccs(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit
) -> list[dict]:
    site = get_site(db, site_id, scope, principal)
    return [
        wcc_out(db, w)
        for w in db.scalars(
            select(WorkCompletion)
            .where(WorkCompletion.site_id == site.id)
            .order_by(WorkCompletion.id)
        )
    ]


class WccIn(BaseModel):
    completion_date: date
    guarantee_years: int | None = Field(default=None, ge=1, le=50)
    node_ids: list[int] | None = None
    note: str | None = None


@router.post("/sites/{site_id}/work-completions", status_code=status.HTTP_201_CREATED)
def create_wcc(
    site_id: int,
    body: WccIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: CompletionEdit,
) -> dict:
    site = get_site(db, site_id, scope, principal)
    w = csvc.make(
        db,
        site,
        body.completion_date,
        body.guarantee_years,
        body.node_ids,
        body.note,
        principal.user,
        demo=site.is_demo,
    )
    record(
        db,
        request,
        principal,
        "wcc.create",
        "work_completion",
        w.id,
        after={"code": w.code, "areas": len(w.areas)},
    )
    db.commit()
    return wcc_out(db, w)


@router.get("/work-completions/{wid}")
def get_wcc(wid: int, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit) -> dict:
    return wcc_out(db, _w(db, wid, scope, principal))


@router.get("/work-completions/{wid}/pdf")
def wcc_pdf(
    wid: int, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit
) -> Response:
    w = _w(db, wid, scope, principal)
    return Response(
        csvc.pdf(csvc.html(db, w)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{w.code}.pdf"'},
    )


@router.get("/work-completions/{wid}/bond.pdf")
def wcc_bond(
    wid: int, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit
) -> Response:
    w = _w(db, wid, scope, principal)
    return Response(
        csvc.pdf(csvc.bond_html(db, w)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{w.code}-guarantee-bond.pdf"'},
    )


@router.get("/work-completions/{wid}/plan.svg")
def wcc_plan(
    wid: int, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit
) -> Response:
    w = _w(db, wid, scope, principal)
    return Response(csvc.plan_svg(db, db.get(Site, w.site_id), w), media_type="image/svg+xml")


@router.post("/work-completions/{wid}/sign-record")
async def wcc_sign_record(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit,
    signed_name: Annotated[str, Form(min_length=2)], file: Annotated[UploadFile, File()],
) -> dict:  # fmt: skip
    w = _w(db, wid, scope, principal)
    csvc.guard(w)
    rel, _n = await save_upload(file, f"wcc/{w.site_id}")
    csvc.sign(db, w, signed_name, None, True, rel)
    record(
        db,
        request,
        principal,
        "wcc.sign_recorded",
        "work_completion",
        w.id,
        after={"signed_name": signed_name},
    )
    db.commit()
    return wcc_out(db, w)


class WccPatch(BaseModel):
    note: str | None = None
    completion_date: date | None = None


@router.put("/work-completions/{wid}")
def update_wcc(
    wid: int,
    body: WccPatch,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: CompletionEdit,
) -> dict:
    w = _w(db, wid, scope, principal)
    csvc.guard(w)
    if body.completion_date:
        w.completion_date = body.completion_date
        w.guarantee_expiry = csvc.add_years(body.completion_date, w.guarantee_years)
    if body.note is not None:
        w.note = body.note
    record(
        db,
        request,
        principal,
        "wcc.update",
        "work_completion",
        w.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return wcc_out(db, w)


@router.delete("/work-completions/{wid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wcc(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: CompletionEdit
) -> None:
    w = _w(db, wid, scope, principal)
    csvc.guard(w)
    record(db, request, principal, "wcc.delete", "work_completion", w.id, before={"code": w.code})
    db.delete(w)
    db.commit()


class AddendumIn(BaseModel):
    completion_date: date
    node_ids: list[int] | None = None
    note: str = Field(min_length=3)


@router.post("/work-completions/{wid}/addendum", status_code=status.HTTP_201_CREATED)
def wcc_addendum(
    wid: int,
    body: AddendumIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: CompletionEdit,
) -> dict:
    w = _w(db, wid, scope, principal)
    a = csvc.addendum(db, w, body.completion_date, body.node_ids, body.note, principal.user)
    record(
        db,
        request,
        principal,
        "wcc.addendum",
        "work_completion",
        a.id,
        after={"addendum_of": w.code, "code": a.code},
    )
    db.commit()
    return wcc_out(db, a)


@router.get("/guarantees")
def guarantees(db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    scope = (
        principal.permissions.get("closeout.billing")
        or principal.permissions.get("closeout.site")
        or principal.permissions.get("issues.view")
    )
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: closeout.billing")
    return csvc.register(db, allowed_sites(db, scope, principal), today())


@router.get("/past-projects")
def past_projects(db: DbSession, _: Billing) -> list[dict]:
    return csvc.past_projects(db)


@router.get("/past-projects.xlsx")
def past_projects_xlsx(db: DbSession, _: Billing) -> Response:
    from app.export import xlsx_response  # noqa: PLC0415

    rows = [
        [
            r["client"],
            r["site"],
            r["city"],
            r["systems"],
            r["quantities"],
            r["completion"],
            r["guarantee_years"],
        ]
        for r in csvc.past_projects(db)
        if not r["is_demo"]
    ]
    return xlsx_response(
        "past-projects",
        ["Client", "Site", "City", "Systems", "Quantities", "Completed", "Guarantee (years)"],
        rows,
    )


@router.get("/past-projects.pdf")
def past_projects_pdf(db: DbSession, _: Billing, include_demo: bool = False) -> Response:
    from html import escape  # noqa: PLC0415

    rows = [r for r in csvc.past_projects(db) if include_demo or not r["is_demo"]]
    body = "<h2 class='c'>OUR COMPLETED WATERPROOFING PROJECTS</h2><table class='wcc'><thead><tr><th>#</th><th>Client</th><th>Site</th><th>City</th><th>Systems</th><th>Quantities</th><th>Completed</th><th>Guarantee</th></tr></thead><tbody>"
    body += "".join(
        f"<tr><td>{i}</td><td>{escape(r['client'])}</td><td>{escape(r['site'])}</td><td>{escape(r['city'] or '')}</td><td>{escape(r['systems'])}</td><td>{escape(r['quantities'])}</td><td>{r['completion']:%d.%m.%Y}</td><td>{r['guarantee_years']} years</td></tr>"
        for i, r in enumerate(rows, 1)
    )
    body += "</tbody></table>"
    return Response(
        csvc.pdf(csvc._page(db, "Past projects", body)),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="past-projects.pdf"'},
    )


# --- 10. issue log -------------------------------------------------------------------------------


def issue_out(db: Session, i: SiteIssueLog) -> dict:
    site = db.get(Site, i.site_id) if i.site_id else None
    who = lambda u: (db.get(User, u).full_name if u and db.get(User, u) else None)  # noqa: E731
    return {"id": i.id, "code": i.code, "site_id": i.site_id, "site": f"{site.code} {site.name}" if site else None, "methodology_id": i.methodology_id,
            "category": i.category, "category_label": isvc.CATEGORY_LABEL[i.category], "title": i.title, "description": i.description,
            "raised_by": who(i.raised_by), "assigned_to": who(i.assigned_to), "assigned_to_id": str(i.assigned_to) if i.assigned_to else None,
            "due_on": i.due_on, "status": i.status, "overdue": bool(i.due_on and i.status in ("open", "in_progress") and i.due_on < today()),
            "photos": len(i.photos or []), "snag_id": i.snag_id, "work_completion_id": i.work_completion_id, "node_id": i.node_id, "product_id": i.product_id,
            "created_at": i.created_at,
            "comments": [{"by": who(c.author_id) or "system", "body": c.body, "at": c.at} for c in db.scalars(select(IssueComment).where(IssueComment.issue_id == i.id).order_by(IssueComment.id))]}  # fmt: skip


def _issue(db: Session, iid: int, scope: str, principal: Principal) -> SiteIssueLog:
    i = db.get(SiteIssueLog, iid)
    if i is None or not (
        site_ok(db, scope, principal, i.site_id)
        or i.raised_by == principal.user.id
        or i.assigned_to == principal.user.id
    ):
        raise not_found("Issue not found")
    return i


@router.get("/issues")
def list_issues(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IssueView,
    site_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[dict]:
    q = select(SiteIssueLog).order_by(SiteIssueLog.id.desc())
    if site_id:
        q = q.where(SiteIssueLog.site_id == site_id)
    if status_:
        q = q.where(SiteIssueLog.status == status_)
    allowed = allowed_sites(db, scope, principal)
    out = []
    for i in db.scalars(q.limit(500)):
        if (
            allowed is not None
            and i.site_id not in allowed
            and principal.user.id not in (i.raised_by, i.assigned_to)
        ):
            continue
        out.append(issue_out(db, i))
    return out


class IssueIn(BaseModel):
    site_id: int
    category: str
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    assigned_to: str | None = None
    due_on: date | None = None
    node_id: int | None = None
    work_completion_id: int | None = None
    ra_bill_id: int | None = None


@router.post("/issues", status_code=status.HTTP_201_CREATED)
def create_issue(
    body: IssueIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: IssueEdit
) -> dict:
    site = get_site(db, body.site_id, scope, principal)
    i = isvc.raise_issue(db, site_id=site.id, category=body.category, title=body.title, user_id=principal.user.id, description=body.description,
                         assigned_to=body.assigned_to, due_on=body.due_on, node_id=body.node_id, work_completion_id=body.work_completion_id,
                         ra_bill_id=body.ra_bill_id, demo=site.is_demo)  # fmt: skip
    record(
        db,
        request,
        principal,
        "issue.create",
        "issue",
        i.id,
        after={"code": i.code, "category": i.category},
    )
    db.commit()
    return issue_out(db, i)


@router.get("/issues/{iid}")
def get_issue(iid: int, db: DbSession, principal: CurrentPrincipal, scope: IssueView) -> dict:
    return issue_out(db, _issue(db, iid, scope, principal))


class IssuePatch(BaseModel):
    status: str | None = None
    assigned_to: str | None = None
    due_on: date | None = None
    title: str | None = None


@router.put("/issues/{iid}")
def update_issue(
    iid: int,
    body: IssuePatch,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IssueEdit,
) -> dict:
    i = _issue(db, iid, scope, principal)
    ch = body.model_dump(exclude_unset=True)
    if "status" in ch:
        isvc.set_status(db, i, ch.pop("status"))
    for k, v in ch.items():
        setattr(i, k, v)
    record(
        db,
        request,
        principal,
        "issue.update",
        "issue",
        i.id,
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return issue_out(db, i)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/issues/{iid}/comments")
def comment_issue(
    iid: int, body: CommentIn, db: DbSession, principal: CurrentPrincipal, scope: IssueEdit
) -> dict:
    i = _issue(db, iid, scope, principal)
    isvc.comment(db, i, body.body, principal.user.id)
    db.commit()
    return issue_out(db, i)


@router.post("/issues/{iid}/photos")
async def issue_photo(
    iid: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IssueEdit,
    file: Annotated[UploadFile, File()],
) -> dict:
    i = _issue(db, iid, scope, principal)
    rel, name = await save_upload(file, f"issues/{i.site_id}")
    i.photos = [*(i.photos or []), {"path": rel, "name": name}]
    db.commit()
    return issue_out(db, i)


@router.post("/issues/{iid}/share")
def share_issue(
    iid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: IssueEdit
) -> dict:
    i = _issue(db, iid, scope, principal)
    sid = isvc.share(db, i, principal.user.id)
    record(db, request, principal, "issue.share", "issue", i.id, after={"snag_id": sid})
    db.commit()
    return issue_out(db, i)


# --- 11. material reconciliation and labour claims ------------------------------------------------


@router.get("/sites/{site_id}/reconciliation")
def reconciliation(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
    month: str | None = None,
) -> dict:
    return rsvc.material(db, get_site(db, site_id, scope, principal), month)


class ClaimIn(BaseModel):
    contractor: str = Field(min_length=2, max_length=200)
    vendor_id: int | None = None
    node_id: int | None = None
    contract_line_id: int | None = None
    claimed_qty: Decimal = Field(ge=0)
    unit: str | None = "sqm"
    period: str | None = None
    note: str | None = None


@router.get("/sites/{site_id}/labour-claims")
def labour_claims(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
    period: str | None = None,
) -> list[dict]:
    return rsvc.claims(db, get_site(db, site_id, scope, principal), period)


@router.post("/sites/{site_id}/labour-claims", status_code=status.HTTP_201_CREATED)
def add_claim(
    site_id: int,
    body: ClaimIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Billing,
) -> list[dict]:
    site = get_site(db, site_id, scope, principal)
    c = LabourClaim(site_id=site.id, created_by=principal.user.id, **body.model_dump())
    db.add(c)
    db.flush()
    record(
        db,
        request,
        principal,
        "labour_claim.create",
        "labour_claim",
        c.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return rsvc.claims(db, site, body.period)
