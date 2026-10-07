"""Subcontractors (vendors of type 'subcontractor'), work orders and measurements.

subcon.view / subcon.edit by the work order's site; approving a work order, or a measurement
that takes a line beyond its WO quantity, needs subcon.approve. RA bills are M5: here a WO shows
what is billable to date (verified measurements x rate), with retention and TDS.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import pdf
from app.execution import service as svc
from app.execution.common import names, pdf_response, record, save_upload, send_file
from app.execution.models import WoLine, WoMeasurement, WorkOrder
from app.masters.models import TcTemplate, Vendor, VendorBankAccount
from app.material import service as material
from app.sites.models import AreaScope, Site
from app.tenders.models import BoqLine

router = APIRouter(prefix="/api/execution", tags=["execution"])
SubconView = Annotated[str, Depends(require_permission("subcon.view"))]


@router.get("/subcontractors")
def subcontractors(db: DbSession, _: SubconView) -> list[dict]:
    """Bank accounts are masked to the last 4 digits here."""
    out = []
    for v in db.scalars(select(Vendor).where(Vendor.type == "subcontractor").order_by(Vendor.name)):
        bank = db.scalar(
            select(VendorBankAccount)
            .where(VendorBankAccount.vendor_id == v.id)
            .order_by(VendorBankAccount.is_primary.desc())
            .limit(1)
        )
        out.append(
            {
                "id": v.id,
                "name": v.name,
                "pan": v.pan,
                "gstin": v.gstin,
                "city": v.city,
                "phone": None,
                "is_active": v.is_active,
                "tds_percent": svc.tds_default(v.pan),
                "bank": f"{bank.bank or 'Bank'} ••••{bank.account_number[-4:]}" if bank else None,
                "work_orders": len(
                    list(db.scalars(select(WorkOrder.id).where(WorkOrder.subcontractor_id == v.id)))
                ),
            }
        )
    return out


class LineIn(BaseModel):
    id: int | None = None
    description: str = Field(min_length=1)
    area_scope_id: int | None = None
    boq_line_id: int | None = None
    unit: str = Field(min_length=1, max_length=20)
    qty: Decimal = Field(gt=0)
    rate: Decimal = Field(ge=0)


class WoIn(BaseModel):
    site_id: int
    subcontractor_id: int
    material_by: Literal["eespl", "subcontractor"] = "eespl"
    retention_percent: Decimal = Field(default=Decimal(5), ge=0, le=50)
    tds_percent: Decimal | None = Field(default=None, ge=0, le=20)  # default by PAN type
    start_date: date | None = None
    end_date: date | None = None
    tc_template_id: int | None = None
    remark: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class MeasureIn(BaseModel):
    on_date: date | None = None
    qty: Decimal = Field(gt=0)
    remark: str | None = None


def _wo_out(db, wo: WorkOrder, principal) -> dict:
    site = db.get(Site, wo.site_id)
    perms = principal.permissions
    edit = material.covers_site(db, perms.get("subcon.edit"), principal, site.id, site.created_by)
    approve = material.covers_site(
        db, perms.get("subcon.approve"), principal, site.id, site.created_by
    )
    who = names(
        db,
        [wo.approved_by, wo.created_by]
        + [m.verified_by for ln in wo.lines for m in ln.measurements],
    )
    lines = []
    for ln in wo.lines:
        p = svc.line_progress(ln)
        lines.append(
            {
                "id": ln.id,
                "description": ln.description,
                "area_scope_id": ln.area_scope_id,
                "boq_line_id": ln.boq_line_id,
                "unit": ln.unit,
                "qty": ln.qty,
                "rate": ln.rate,
                "amount": ln.amount,
                "measured": p["measured"],
                "verified": p["verified"],
                "billable": p["billable"],
                "over": p["over"],
                "measurements": [
                    {
                        "id": m.id,
                        "on_date": m.on_date,
                        "qty": m.qty,
                        "remark": m.remark,
                        "status": m.status,
                        "verified_by_name": who.get(m.verified_by),
                        "photos": len(m.photos),
                    }
                    for m in ln.measurements
                ],
            }
        )
    return {
        "id": wo.id,
        "code": wo.code,
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "subcontractor_id": wo.subcontractor_id,
        "subcontractor_name": wo.subcontractor.name,
        "subcontractor_pan": wo.subcontractor.pan,
        "material_by": wo.material_by,
        "retention_percent": wo.retention_percent,
        "tds_percent": wo.tds_percent,
        "start_date": wo.start_date,
        "end_date": wo.end_date,
        "tc_template_id": wo.tc_template_id,
        "remark": wo.remark,
        "status": wo.status,
        "approved_by_name": who.get(wo.approved_by),
        "created_by_name": who.get(wo.created_by),
        "lines": lines,
        **svc.wo_money(wo),
        "can_edit": edit and wo.status == "draft",
        "can_measure": edit and wo.status in ("approved", "active"),
        "can_approve": approve,
        "can_change_status": edit,
    }


def _visible(db, wo_id, principal) -> WorkOrder:
    wo = db.get(WorkOrder, wo_id)
    if wo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    svc.site_for(db, wo.site_id, principal, "subcon.view")
    return wo


def _fill(db, wo: WorkOrder, body: WoIn, principal) -> None:
    v = db.get(Vendor, body.subcontractor_id)
    if v is None or v.type != "subcontractor":
        raise svc.unprocessable("Pick a subcontractor (a vendor of type subcontractor)")
    if body.tc_template_id and db.get(TcTemplate, body.tc_template_id) is None:
        raise svc.unprocessable("T&C template not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise svc.unprocessable("The end date is before the start")
    for k in (
        "subcontractor_id",
        "material_by",
        "retention_percent",
        "start_date",
        "end_date",
        "tc_template_id",
        "remark",
    ):
        setattr(wo, k, getattr(body, k))
    wo.tds_percent = body.tds_percent if body.tds_percent is not None else svc.tds_default(v.pan)
    site = db.get(Site, wo.site_id)
    existing = {ln.id: ln for ln in wo.lines}
    keep = []
    for li in body.lines:
        if li.area_scope_id:
            sc = db.get(AreaScope, li.area_scope_id)
            if sc is None or sc.site_id != site.id:
                raise svc.unprocessable("That area scope is not on this site")
        if li.boq_line_id:
            bl = db.get(BoqLine, li.boq_line_id)
            if bl is None or bl.tender_id != site.tender_id:
                raise svc.unprocessable("That BOQ line is not from this site's tender")
        ln = existing.get(li.id or 0) or WoLine(created_by=principal.user.id)
        for k in ("description", "area_scope_id", "boq_line_id", "unit", "qty", "rate"):
            setattr(ln, k, getattr(li, k))
        ln.amount = svc.money(li.qty * li.rate)
        keep.append(ln)
    wo.lines = keep
    wo.amount = sum((ln.amount for ln in keep), Decimal(0))


@router.get("/work-orders")
def list_wos(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SubconView,
    site_id: int | None = None,
    subcontractor_id: int | None = None,
) -> list[dict]:
    q = select(WorkOrder).where(
        material.by_site(scope, principal, WorkOrder.site_id, WorkOrder.created_by)
    )
    if site_id is not None:
        q = q.where(WorkOrder.site_id == site_id)
    if subcontractor_id is not None:
        q = q.where(WorkOrder.subcontractor_id == subcontractor_id)
    return [_wo_out(db, wo, principal) for wo in db.scalars(q.order_by(WorkOrder.id.desc()))]


@router.get("/work-orders/{wo_id}")
def get_wo(wo_id: int, db: DbSession, principal: CurrentPrincipal, _: SubconView) -> dict:
    return _wo_out(db, _visible(db, wo_id, principal), principal)


@router.post("/work-orders", status_code=status.HTTP_201_CREATED)
def create_wo(
    body: WoIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: SubconView
) -> dict:
    site = svc.site_for(db, body.site_id, principal, "subcon.view", "subcon.edit")
    wo = WorkOrder(code=material.next_code(db, "WO"), site_id=site.id, created_by=principal.user.id)
    _fill(db, wo, body, principal)
    db.add(wo)
    db.flush()
    record(
        db, request, principal, "wo.create", "work_order", wo.id, after=body.model_dump(mode="json")
    )
    db.commit()
    db.refresh(wo)
    return _wo_out(db, wo, principal)


@router.put("/work-orders/{wo_id}")
def update_wo(
    wo_id: int,
    body: WoIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconView,
) -> dict:
    wo = _visible(db, wo_id, principal)
    if not _wo_out(db, wo, principal)["can_edit"]:
        raise svc.conflict(f"{wo.code} is {wo.status}; only a draft is changed")
    if body.site_id != wo.site_id:
        raise svc.unprocessable("A work order cannot move to another site")
    _fill(db, wo, body, principal)
    record(
        db, request, principal, "wo.update", "work_order", wo.id, after=body.model_dump(mode="json")
    )
    db.commit()
    db.refresh(wo)
    return _wo_out(db, wo, principal)


NEXT = {
    "approve": ("draft", "approved"),
    "start": ("approved", "active"),
    "complete": ("active", "completed"),
    "close": ("completed", "closed"),
}


@router.post("/work-orders/{wo_id}/{action}")
def wo_status(
    wo_id: int,
    action: Literal["approve", "start", "complete", "close"],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconView,
) -> dict:
    wo = _visible(db, wo_id, principal)
    out = _wo_out(db, wo, principal)
    if not (out["can_approve"] if action == "approve" else out["can_change_status"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You cannot {action} {wo.code}")
    before, after = NEXT[action]
    if wo.status != before:
        raise svc.conflict(f"{wo.code} is {wo.status}")
    if action == "complete" and any(
        m.status == "pending_approval" for ln in wo.lines for m in ln.measurements
    ):
        raise svc.conflict("Approve or reject the over-measurements first")
    wo.status = after
    if action == "approve":
        wo.approved_by, wo.approved_at = principal.user.id, svc.now()
    record(
        db,
        request,
        principal,
        f"wo.{action}",
        "work_order",
        wo.id,
        {"status": before},
        {"status": after},
    )
    db.commit()
    return _wo_out(db, wo, principal)


@router.post(
    "/work-orders/{wo_id}/lines/{line_id}/measurements", status_code=status.HTTP_201_CREATED
)
def measure(
    wo_id: int,
    line_id: int,
    body: MeasureIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconView,
) -> dict:
    """Work done on a line. Up to the WO qty it is 'recorded' (to be verified); beyond it, it
    waits for subcon.approve and the response says so."""
    wo = _visible(db, wo_id, principal)
    if not _wo_out(db, wo, principal)["can_measure"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"{wo.code}: measurements need subcon.edit on an approved WO"
        )
    line = next((ln for ln in wo.lines if ln.id == line_id), None)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    so_far = svc.line_progress(line)["measured"]
    over = so_far + body.qty > Decimal(line.qty)
    m = WoMeasurement(
        on_date=body.on_date or svc.today(),
        qty=body.qty,
        remark=body.remark,
        status="pending_approval" if over else "recorded",
        created_by=principal.user.id,
    )
    line.measurements.append(m)
    if wo.status == "approved":
        wo.status = "active"
    db.flush()
    record(
        db,
        request,
        principal,
        "wo.measure",
        "work_order",
        wo.id,
        after={"line_id": line.id, "qty": str(body.qty), "over": over},
    )
    db.commit()
    db.refresh(wo)
    out = _wo_out(db, wo, principal)
    out["warning"] = (
        f"Measured {so_far + body.qty:f} {line.unit} against {Decimal(line.qty):f} on the WO: "
        "this measurement needs approval"
        if over
        else None
    )
    return out


def _measurement(db, mid, principal) -> tuple[WoMeasurement, WorkOrder]:
    m = db.get(WoMeasurement, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Measurement not found")
    line = db.get(WoLine, m.line_id)
    return m, _visible(db, line.wo_id, principal)


@router.post("/measurements/{mid}/photos", status_code=status.HTTP_201_CREATED)
async def measurement_photo(
    mid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconView,
    file: Annotated[UploadFile, File()],
) -> dict:
    m, wo = _measurement(db, mid, principal)
    if not _wo_out(db, wo, principal)["can_change_status"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Photos need subcon.edit")
    rel, name = await save_upload(file, f"work-orders/{wo.id}/{m.id}")
    m.photos = [*m.photos, {"path": rel, "filename": name}]
    record(
        db, request, principal, "wo.measurement.photo", "work_order", wo.id, after={"file": name}
    )
    db.commit()
    return _wo_out(db, wo, principal)


@router.post("/measurements/{mid}/{action}")
def measurement_action(
    mid: int,
    action: Literal["verify", "approve", "reject"],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconView,
) -> dict:
    """verify: a recorded measurement checked on site (subcon.edit). approve / reject: an
    over-measurement (subcon.approve)."""
    m, wo = _measurement(db, mid, principal)
    out = _wo_out(db, wo, principal)
    if action == "verify":
        if not out["can_change_status"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Verifying needs subcon.edit")
        if m.status != "recorded":
            raise svc.conflict(f"The measurement is {m.status}")
    else:
        if not out["can_approve"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Over-measurement needs subcon.approve")
        if m.status not in ("pending_approval", "recorded"):
            raise svc.conflict(f"The measurement is {m.status}")
    before = m.status
    m.status = "rejected" if action == "reject" else "verified"
    m.verified_by, m.verified_at = principal.user.id, svc.now()
    record(
        db,
        request,
        principal,
        f"wo.measurement.{action}",
        "work_order",
        wo.id,
        {"measurement": m.id, "status": before},
        {"status": m.status},
    )
    db.commit()
    db.refresh(wo)
    return _wo_out(db, wo, principal)


@router.get("/measurements/{mid}/photos/{n}")
def get_measurement_photo(
    mid: int, n: int, db: DbSession, principal: CurrentPrincipal, _: SubconView
):
    m, _wo = _measurement(db, mid, principal)
    p = m.photos[n] if 0 <= n < len(m.photos) else None
    return send_file(p["path"] if p else None, p["filename"] if p else None)


@router.get("/work-orders/{wo_id}/pdf")
def wo_pdf(wo_id: int, db: DbSession, principal: CurrentPrincipal, _: SubconView):
    wo = _visible(db, wo_id, principal)
    return pdf_response(pdf.work_order(db, wo, _wo_out(db, wo, principal)), wo.code)
