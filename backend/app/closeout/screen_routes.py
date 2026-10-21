# ruff: noqa: E501  (response shapes read better unwrapped)
"""The close-out screens that were API-only (review of Prompt 26): the measurement book's entry
form (places, the drawing's areas, the lines with the work order's unit), the quality checklist
per area with our sign and the client's, the material reconciliation with "return to godown",
labour claims decided against the approved measurement (above it: the director), and one page
for a bill's story (quantities, steps at the client, payment)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentPrincipal, require_permission
from app.closeout import billing as bsvc
from app.closeout import measure as msvc
from app.closeout import recon as rsvc
from app.closeout.common import locked, not_found, now, unprocessable
from app.closeout.completion import _path
from app.closeout.models import LabourClaim
from app.closeout.routes import (
    Billing,
    BillsView,
    SiteTeam,
    _bill,
    cycle_out,
    get_site,
    record,
    site_ok,
)
from app.db import DbSession
from app.execution.common import save_upload
from app.sites.models import AreaScope, Site, SiteNode, Task

router = APIRouter(prefix="/api/closeout", tags=["close-out screens"])
ClaimApprove = Annotated[str, Depends(require_permission("closeout.claim_approve"))]


# --- the measurement book's entry form ------------------------------------------------------------


def _how(unit: str) -> str:
    from app.closeout.sizes import AREA, LINEAR  # noqa: PLC0415

    if unit in LINEAR:
        return f"per {unit}: measure the running length (or the perimeter)"
    if unit in AREA:
        return f"per {unit}: L x B, or perimeter x height (walls), less deductions"
    return f"per {unit}: type the quantity"


@router.get("/sites/{site_id}/measure-form")
def measure_form(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing) -> dict:
    """What the entry form picks from: the site's places, the drawing's traced areas and the
    contract's lines with their unit (the accepted work order's)."""
    from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine  # noqa: PLC0415
    from app.finance.models import ClientContract  # noqa: PLC0415
    from app.takeoff.models import CadArea, CadFile  # noqa: PLC0415

    site = get_site(db, site_id, scope, principal)
    places = [{"id": n.id, "parent_id": n.parent_id, "kind": n.kind, "name": n.name, "path": _path(db, n.id)}
              for n in db.scalars(select(SiteNode).where(SiteNode.site_id == site.id).order_by(SiteNode.sort_order, SiteNode.id))]  # fmt: skip
    f = db.scalars(select(CadFile).where(CadFile.site_id == site.id, CadFile.status == "ready").order_by(CadFile.id.desc())).first()
    cad = []
    if f is not None:
        cad = [{"id": a.id, "name": a.name, "node_id": a.node_id, "area_sqm": a.traced_area_sqm or a.label_area_sqm, "perimeter_m": a.traced_perimeter_m}
               for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == f.id, CadArea.status != "ignored").order_by(CadArea.name))]  # fmt: skip
    c = db.scalar(select(ClientContract).where(ClientContract.site_id == site.id))
    lines = []
    for cl in c.lines if c else []:
        src = None
        if cl.wo_line_id:
            wl = db.get(ClientWorkOrderLine, cl.wo_line_id)
            wo = db.get(ClientWorkOrder, wl.work_order_id) if wl else None
            src = f"work order {wo.client_ref or wo.code}" if wo else None
        lines.append({"id": cl.id, "description": cl.description, "unit": cl.unit, "rate": cl.rate, "source": src or "contract", "how": _how(cl.unit)})
    return {"site": f"{site.code} {site.name}", "needs_approval": site.measurements_need_approval, "places": places, "cad_areas": cad, "lines": lines}


# --- the quality checklist ------------------------------------------------------------------------


@router.get("/sites/{site_id}/quality")
def site_quality(site_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Every area with stages: each stage's dates, our sign and the client's."""
    scope = principal.permissions.get("closeout.site") or principal.permissions.get("closeout.billing")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: closeout.site")
    site = get_site(db, site_id, scope, principal)
    ids = list(dict.fromkeys(db.scalars(select(AreaScope.node_id).where(AreaScope.site_id == site.id).order_by(AreaScope.node_id))))
    return {"site_id": site.id, "areas": [{"node_id": nid, "path": _path(db, nid), "stages": msvc.quality(db, site, nid)} for nid in ids]}


class QualitySignIn(BaseModel):
    started_on: date | None = None
    ended_on: date | None = None
    remark: str | None = None


def _sign_template(db: Session, task: Task):
    """The stage's own checklist, else the one-line stage sign-off."""
    from app.execution.models import ChecklistItem, ChecklistTemplate  # noqa: PLC0415
    from app.sites.models import StageTemplateStep  # noqa: PLC0415

    step = db.get(StageTemplateStep, task.step_id) if task.step_id else None
    tid = getattr(step, "checklist_template_id", None) if step else None
    if tid:
        return db.get(ChecklistTemplate, tid)
    t = db.scalar(select(ChecklistTemplate).where(ChecklistTemplate.name == "Stage sign-off (quality checklist)"))
    if t is None:
        t = ChecklistTemplate(name="Stage sign-off (quality checklist)")
        db.add(t)
        db.flush()
        db.add(ChecklistItem(template_id=t.id, sort_order=0, text="The stage is done as per the method statement", type="pass_fail", required=True))
        db.flush()
        db.refresh(t)
    return t


@router.post("/tasks/{task_id}/quality-sign")
def quality_sign(task_id: int, body: QualitySignIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: SiteTeam) -> dict:
    """Our sign on a stage, with its start and end dates (the client signs after, in the portal
    or on paper recorded by our staff)."""
    from app.execution.models import Inspection  # noqa: PLC0415
    from app.material import service as material  # noqa: PLC0415

    t = db.get(Task, task_id)
    if t is None or not site_ok(db, scope, principal, t.site_id):
        raise not_found("Stage not found")
    if body.started_on and body.ended_on and body.ended_on < body.started_on:
        raise unprocessable("The stage cannot end before it started")
    i = db.scalars(select(Inspection).where(Inspection.task_id == t.id).order_by(Inspection.id.desc())).first()
    if i is not None and i.client_signoff == "signed":
        raise locked(f"Stage {t.name} (signed by the client)")
    if i is None or i.inspected_by is not None and i.result == "fail":
        tpl = _sign_template(db, t)
        i = Inspection(code=material.next_code(db, "INS"), site_id=t.site_id, node_id=t.node_id, task_id=t.id, template_id=tpl.id, on_date=body.ended_on or date.today(),
                       answers=[{"item_id": it.id, "text": it.text, "type": it.type, "required": it.required, "value": "pass" if it.type == "pass_fail" else None} for it in tpl.items],
                       result="pass", remark=body.remark, created_by=principal.user.id, photos=[])  # fmt: skip
        db.add(i)
    i.inspected_by = principal.user.id
    if i.client_signoff in (None, "none"):
        i.client_signoff = "waiting"  # the client signs next: in the portal, or on paper recorded by staff
    i.stage_started_on = body.started_on or i.stage_started_on or t.actual_start
    i.stage_ended_on = body.ended_on or i.stage_ended_on or t.actual_end
    db.flush()
    record(db, request, principal, "quality.sign", "inspection", i.id, after={"task": t.id, "started_on": str(i.stage_started_on), "ended_on": str(i.stage_ended_on)})
    db.commit()
    site = db.get(Site, t.site_id)
    return {"node_id": t.node_id, "stages": msvc.quality(db, site, t.node_id)}


# --- material reconciliation --------------------------------------------------------------------------


@router.get("/sites/{site_id}/reconciliation")
def reconciliation(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing, period: str | None = None, month: str | None = None) -> dict:
    site = get_site(db, site_id, scope, principal)
    return rsvc.material(db, site, month, period)


@router.get("/sites/{site_id}/reconciliation.xlsx")
def reconciliation_xlsx(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: Billing, period: str | None = None) -> Response:
    from app.export import xlsx_response  # noqa: PLC0415

    site = get_site(db, site_id, scope, principal)
    r = rsvc.material(db, site, None, period)
    rows = [[x["product"], x["unit"], x["issued"], x["needed"], x["returned"], x["difference"], x["state"], "; ".join(x["basis"])] for x in r["rows"]]
    return xlsx_response(f"reconciliation-{site.code}", ["Product", "Unit", "Issued", "Needed", "Returned", "Excess (+) / short (-)", "State", "Needed from"], rows)


class ReturnIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)


@router.post("/sites/{site_id}/reconciliation/return", status_code=status.HTTP_201_CREATED)
def return_to_godown(site_id: int, body: ReturnIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The excess back to the godown: a return from the work into the site store, and a
    dispatched transfer from the site store to the godown (received there by stores)."""
    scope = principal.permissions.get("store.edit") or principal.permissions.get("closeout.billing")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: store.edit")
    site = get_site(db, site_id, scope, principal)
    t = rsvc.return_excess(db, site, body.product_id, body.qty, principal.user.id)
    record(db, request, principal, "reconciliation.return", "transfer", t.id, after={"site": site.code, "product_id": body.product_id, "qty": str(body.qty)})
    db.commit()
    return {"transfer": t.code, "transfer_id": t.id, **rsvc.material(db, site)}


# --- labour claims ----------------------------------------------------------------------------------------


def _claim(db: Session, cid: int, scope: str, principal) -> LabourClaim:
    c = db.get(LabourClaim, cid)
    if c is None or not site_ok(db, scope, principal, c.site_id):
        raise not_found("Claim not found")
    return c


class DecideIn(BaseModel):
    decision: Literal["approved", "claimed"]
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/labour-claims/{cid}/decide")
def decide_claim(cid: int, body: DecideIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Billing) -> dict:
    """Pay the approved quantity, or the claimed one: above the approved quantity that needs a
    reason and the director's approval (the director decides it at once)."""
    c = _claim(db, cid, scope, principal)
    rsvc.decide(db, c, body.decision, body.reason, principal)
    record(db, request, principal, "labour_claim.decide", "labour_claim", c.id, after={**body.model_dump(), "status": c.status})
    db.commit()
    return next(x for x in rsvc.claims(db, db.get(Site, c.site_id)) if x["id"] == c.id)


class DirectorIn(BaseModel):
    approve: bool
    reason: str = Field(min_length=2, max_length=1000)


@router.post("/labour-claims/{cid}/director")
def director_claim(cid: int, body: DirectorIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: ClaimApprove) -> dict:
    c = _claim(db, cid, scope, principal)
    rsvc.director(db, c, body.approve, body.reason, principal.user.id)
    record(db, request, principal, "labour_claim.director", "labour_claim", c.id, after=body.model_dump())
    db.commit()
    return next(x for x in rsvc.claims(db, db.get(Site, c.site_id)) if x["id"] == c.id)


@router.post("/labour-claims/{cid}/photos")
async def claim_photo(cid: int, db: DbSession, principal: CurrentPrincipal, scope: Billing, file: Annotated[UploadFile, File()]) -> dict:
    c = _claim(db, cid, scope, principal)
    if c.status == "decided":
        raise locked(f"Claim #{c.id} (decided)")
    rel, name = await save_upload(file, f"labour-claims/{c.site_id}")
    c.photos = [*(c.photos or []), {"path": rel, "filename": name, "at": now().isoformat()}]
    db.commit()
    return {"id": c.id, "photos": len(c.photos)}


# --- one page for a bill's story ----------------------------------------------------------------------------


@router.get("/bills/{rid}/story")
def bill_story(rid: int, db: DbSession, principal: CurrentPrincipal, scope: BillsView) -> dict:
    """Quantities (billed, certified, the difference and why), its steps at the client with the
    billing cycle, and the payment (due, follow-ups, receipts). Selling amounts only."""
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import (  # noqa: PLC0415
        ContractLine,
        RaBillLine,
        Receipt,
        ReceiptAllocation,
    )

    b = _bill(db, rid, scope, principal)
    row = bsvc.bill_out(db, b, date.today())
    site = db.get(Site, b.site_id)
    row["site"] = f"{site.code} {site.name}" if site else None
    row["cycle"] = cycle_out(bsvc.cycle_for(db, site)) if site else None
    lines, billed, certified, any_cert = [], Decimal(0), Decimal(0), False
    for ln in db.scalars(select(RaBillLine).where(RaBillLine.ra_bill_id == b.id).order_by(RaBillLine.id)):
        if not ln.qty and ln.certified_qty is None:
            continue
        cl = db.get(ContractLine, ln.contract_line_id)
        amt = Decimal(ln.qty) * Decimal(ln.rate)
        cert = Decimal(ln.certified_amount) if ln.certified_amount is not None else None
        billed += amt
        if cert is not None:
            certified += cert
            any_cert = True
        lines.append({"line_id": ln.id, "contract_line_id": ln.contract_line_id, "description": cl.description if cl else "", "unit": cl.unit if cl else "", "rate": ln.rate, "billed_qty": ln.qty, "certified_qty": ln.certified_qty,
                      "difference": (Decimal(ln.certified_qty) - Decimal(ln.qty)) if ln.certified_qty is not None else None, "reason": ln.client_diff_reason,
                      "billed": amt.quantize(Decimal("0.01")), "certified": cert})  # fmt: skip
    inv = bsvc.invoice_of(db, b)
    receipts = []
    if inv is not None:
        for ra, rc in db.execute(select(ReceiptAllocation, Receipt).join(Receipt, Receipt.id == ReceiptAllocation.receipt_id).where(ReceiptAllocation.invoice_id == inv.id).order_by(Receipt.on_date)):
            receipts.append({"number": rc.number, "on_date": rc.on_date, "amount": ra.amount, "ref": rc.ref_no})
    total = Decimal(inv.total) if inv is not None else None
    owed = fsvc.outstanding(db, inv) if inv is not None else Decimal(0)
    return {"bill": row,
            "quantities": {"lines": lines, "billed": billed.quantize(Decimal("0.01")), "certified": certified.quantize(Decimal("0.01")) if any_cert else None,
                           "difference": (certified - billed).quantize(Decimal("0.01")) if any_cert else None, "certified_by": b.certified_by_client, "certified_on": b.client_cert_on},
            "payment": {"invoice": inv.number if inv else None, "total": total, "received": (total - owed) if total is not None else Decimal(0), "outstanding": owed, "receipts": receipts}}  # fmt: skip

