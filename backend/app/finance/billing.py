"""Client billing: contracts, RA bills, tax invoices and credit notes, receipts, retention,
client ledger and ageing.

billing.view by site (sales: assigned sites); billing.edit makes bills, invoices and receipts;
billing.approve approves extra items beyond the BOQ, credit notes and cancellations.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.db import DbSession
from app.execution.common import names, pdf_response, record
from app.execution.service import today
from app.finance import pdf
from app.finance import service as svc
from app.finance.models import (
    ClientContract,
    ContractLine,
    InvoiceLine,
    RaBill,
    RaBillLine,
    Receipt,
    ReceiptAllocation,
    RetentionRelease,
    TaxInvoice,
)
from app.masters.models import Client, CompanyBankAccount
from app.material import service as material
from app.models import User
from app.portal import service as portal
from app.sites.models import Site
from app.tenders.models import BoqLine, Tender

router = APIRouter(prefix="/api/finance", tags=["finance"])
BillingView = Annotated[str, Depends(require_permission("billing.view"))]
ZERO = Decimal(0)


def _edit(db, principal: Principal, site_id: int | None):
    if not svc.site_ok(db, principal.permissions.get("billing.edit"), principal, site_id):
        raise svc.forbidden("Missing permission: billing.edit")


def _site(db, site_id: int, principal, scope) -> Site:
    site = db.get(Site, site_id)
    if site is None or not svc.site_ok(db, scope, principal, site.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


def _site_filter(scope, principal, col):
    return material.by_site(scope, principal, col, col) if scope != "own" else col.is_(None)


# --- contracts -----------------------------------------------------------------------------------


class ContractTerms(BaseModel):
    contract_value: Decimal | None = Field(default=None, ge=0)  # default: the BOQ total
    retention_percent: Decimal = Field(default=Decimal(5), ge=0, le=50)
    advance_amount: Decimal = Field(default=Decimal(0), ge=0)
    advance_recovery_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    tds_percent: Decimal = Field(default=Decimal(2), ge=0, le=20)
    gst_tds_percent: Decimal = Field(default=Decimal(0), ge=0, le=5)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)
    sac: str | None = Field(default=None, pattern=r"^[0-9]{4,8}$")
    place_of_supply: str | None = None
    client_gstin: str | None = Field(default=None, max_length=15)
    billing_address: str | None = None
    from_gstin_id: int | None = None
    remark: str | None = None


class ExtraItemIn(BaseModel):
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1, max_length=20)
    qty: Decimal = Field(gt=0)
    rate: Decimal = Field(ge=0)


def _contract_out(db, c: ClientContract) -> dict:
    site = db.get(Site, c.site_id)
    who = names(db, [ln.approved_by for ln in c.lines])
    lines = []
    for ln in c.lines:
        billed = svc.billed_before(db, ln.id)
        lines.append(
            {
                "id": ln.id,
                "boq_line_id": ln.boq_line_id,
                "item_no": ln.item_no,
                "description": ln.description,
                "unit": ln.unit,
                "qty": ln.qty,
                "rate": ln.rate,
                "amount": svc.money(Decimal(ln.qty) * Decimal(ln.rate)),
                "is_extra": ln.is_extra,
                "approved": not ln.is_extra or ln.approved_by is not None,
                "approved_by_name": who.get(ln.approved_by),
                "done_qty": svc.done_qty(db, ln.boq_line_id),
                "billed_qty": billed,
            }
        )
    return {
        "id": c.id,
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "tender_id": c.tender_id,
        "client_id": c.client_id,
        "client_name": c.client.name if c.client else None,
        **{
            k: getattr(c, k)
            for k in (
                "contract_value",
                "retention_percent",
                "advance_amount",
                "advance_recovery_percent",
                "tds_percent",
                "gst_tds_percent",
                "gst_percent",
                "sac",
                "place_of_supply",
                "client_gstin",
                "billing_address",
                "from_gstin_id",
                "remark",
            )
        },
        "advance_left": svc.advance_left(db, c),
        "lines": lines,
    }


def _contract(db, cid, principal, scope) -> ClientContract:
    c = db.get(ClientContract, cid)
    if c is None or not svc.site_ok(db, scope, principal, c.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    return c


@router.get("/contracts")
def list_contracts(
    db: DbSession, principal: CurrentPrincipal, scope: BillingView, site_id: int | None = None
) -> list[dict]:
    q = select(ClientContract).where(_site_filter(scope, principal, ClientContract.site_id))
    if site_id is not None:
        q = q.where(ClientContract.site_id == site_id)
    return [_contract_out(db, c) for c in db.scalars(q.order_by(ClientContract.id.desc()))]


@router.get("/contracts/{cid}")
def get_contract(cid: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView) -> dict:
    return _contract_out(db, _contract(db, cid, principal, scope))


@router.get("/sites/{site_id}/contract")
def site_contract(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict | None:
    site = _site(db, site_id, principal, scope)
    c = db.scalar(select(ClientContract).where(ClientContract.site_id == site.id))
    return _contract_out(db, c) if c else None


@router.post("/sites/{site_id}/contract", status_code=status.HTTP_201_CREATED)
def create_contract(
    site_id: int,
    body: ContractTerms,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    """The contract from the won tender: its priced BOQ lines at the agreed rates."""
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    if db.scalar(select(ClientContract.id).where(ClientContract.site_id == site.id)):
        raise svc.conflict(f"{site.code} already has a contract")
    st = svc.settings(db)
    c = ClientContract(
        site_id=site.id,
        tender_id=site.tender_id,
        client_id=site.client_id,
        created_by=principal.user.id,
    )
    _apply_terms(db, c, body, site)
    c.sac = body.sac or st.works_sac
    if site.tender_id:
        n = 0
        for b in db.scalars(
            select(BoqLine)
            .where(BoqLine.tender_id == site.tender_id)
            .order_by(BoqLine.sort_order, BoqLine.id)
        ):
            if b.rate is None or b.qty is None or Decimal(b.qty) <= 0:
                continue
            n += 1
            c.lines.append(
                ContractLine(
                    boq_line_id=b.id,
                    sort_order=n,
                    item_no=b.client_item_no,
                    description=b.description,
                    unit=b.unit or b.unit_raw or "nos",
                    qty=b.qty,
                    rate=b.rate,
                    created_by=principal.user.id,
                )
            )
    if body.contract_value is None:
        c.contract_value = svc.money(
            sum((Decimal(ln.qty) * Decimal(ln.rate) for ln in c.lines), ZERO)
        )
    db.add(c)
    db.flush()
    record(
        db,
        request,
        principal,
        "contract.create",
        "client_contract",
        c.id,
        after={"site": site.code, "lines": len(c.lines)},
    )
    db.commit()
    db.refresh(c)
    return _contract_out(db, c)


def _apply_terms(db, c: ClientContract, body: ContractTerms, site: Site) -> None:
    for k in (
        "retention_percent",
        "advance_amount",
        "advance_recovery_percent",
        "tds_percent",
        "gst_tds_percent",
        "gst_percent",
        "client_gstin",
        "billing_address",
        "from_gstin_id",
        "remark",
    ):
        setattr(c, k, getattr(body, k))
    if body.contract_value is not None:
        c.contract_value = body.contract_value
    if body.sac:
        c.sac = body.sac
    client = db.get(Client, c.client_id) if c.client_id else None
    c.place_of_supply = body.place_of_supply or site.state or (client.state if client else None)
    c.client_gstin = body.client_gstin or (client.gstin if client else None)
    c.billing_address = body.billing_address or (client.address if client else None)


@router.put("/contracts/{cid}")
def update_contract(
    cid: int,
    body: ContractTerms,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    c = _contract(db, cid, principal, scope)
    _edit(db, principal, c.site_id)
    _apply_terms(db, c, body, db.get(Site, c.site_id))
    record(
        db,
        request,
        principal,
        "contract.update",
        "client_contract",
        c.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(c)
    return _contract_out(db, c)


@router.post("/contracts/{cid}/extra-items", status_code=status.HTTP_201_CREATED)
def add_extra(
    cid: int,
    body: ExtraItemIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    """An item beyond the BOQ: billable once approved (billing.approve)."""
    c = _contract(db, cid, principal, scope)
    _edit(db, principal, c.site_id)
    c.lines.append(
        ContractLine(
            sort_order=len(c.lines) + 1,
            item_no="EX",
            description=body.description,
            unit=body.unit,
            qty=body.qty,
            rate=body.rate,
            is_extra=True,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "contract.extra",
        "client_contract",
        c.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(c)
    return _contract_out(db, c)


@router.post("/contract-lines/{lid}/approve")
def approve_extra(
    lid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    ln = db.get(ContractLine, lid)
    if ln is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    c = _contract(db, ln.contract_id, principal, scope)
    if not svc.site_ok(db, principal.permissions.get("billing.approve"), principal, c.site_id):
        raise svc.forbidden("Extra items are approved with billing.approve")
    if not ln.is_extra:
        raise svc.unprocessable("Only extra items are approved")
    ln.approved_by, ln.approved_at = principal.user.id, svc.now()
    record(
        db,
        request,
        principal,
        "contract.extra.approve",
        "client_contract",
        c.id,
        after={"line": ln.id},
    )
    db.commit()
    db.refresh(c)
    return _contract_out(db, c)


# --- RA bills ------------------------------------------------------------------------------------


class RaLineIn(BaseModel):
    contract_line_id: int
    qty: Decimal = Field(ge=0)


class RaIn(BaseModel):
    period_from: date | None = None
    period_to: date | None = None
    lines: list[RaLineIn] | None = None
    other_deduction: Decimal = Field(default=Decimal(0), ge=0)
    other_deduction_remark: str | None = None
    remark: str | None = None


class CertifyLine(BaseModel):
    contract_line_id: int
    certified_qty: Decimal = Field(ge=0)


class CertifyIn(BaseModel):
    lines: list[CertifyLine]
    certified_by_client: str | None = None
    other_deduction: Decimal | None = Field(default=None, ge=0)
    other_deduction_remark: str | None = None


def _ra_out(db, b: RaBill) -> dict:
    c = db.get(ClientContract, b.contract_id)
    cl = {ln.id: ln for ln in c.lines}
    inv = db.scalar(select(TaxInvoice).where(TaxInvoice.ra_bill_id == b.id))
    lines = []
    for ln in b.lines:
        x = cl[ln.contract_line_id]
        cum = Decimal(ln.previous_qty) + Decimal(
            ln.certified_qty if ln.certified_qty is not None else ln.qty
        )
        lines.append(
            {
                "id": ln.id,
                "contract_line_id": x.id,
                "item_no": x.item_no,
                "description": x.description,
                "unit": x.unit,
                "boq_qty": x.qty,
                "is_extra": x.is_extra,
                "previous_qty": ln.previous_qty,
                "suggested_qty": ln.suggested_qty,
                "qty": ln.qty,
                "certified_qty": ln.certified_qty,
                "cumulative_qty": cum,
                "rate": ln.rate,
                "amount": ln.amount,
                "certified_amount": ln.certified_amount,
                "client_qty": ln.client_qty,
                "previous_amount": svc.money(Decimal(ln.previous_qty) * Decimal(ln.rate)),
                "cumulative_amount": svc.money(cum * Decimal(ln.rate)),
            }
        )
    site = db.get(Site, b.site_id)
    return {
        "id": b.id,
        "code": b.code,
        "seq": b.seq,
        "contract_id": c.id,
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "client_name": c.client.name if c.client else None,
        "period_from": b.period_from,
        "period_to": b.period_to,
        "status": b.status,
        "gross": b.gross,
        "certified_gross": b.certified_gross,
        "retention": b.retention,
        "retention_percent": c.retention_percent,
        "advance_recovery": b.advance_recovery,
        "other_deduction": b.other_deduction,
        "other_deduction_remark": b.other_deduction_remark,
        "net": b.net,
        "certified_by_client": b.certified_by_client,
        "remark": b.remark,
        "client_remark": b.client_remark,
        "client_acted_at": b.client_acted_at,
        "lines": lines,
        "invoice_id": inv.id if inv else None,
        "invoice_number": inv.number if inv else None,
    }


def _ra(db, rid, principal, scope) -> RaBill:
    b = db.get(RaBill, rid)
    if b is None or not svc.site_ok(db, scope, principal, b.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RA bill not found")
    return b


@router.get("/ra-bills")
def list_ra(
    db: DbSession, principal: CurrentPrincipal, scope: BillingView, site_id: int | None = None
) -> list[dict]:
    q = select(RaBill).where(_site_filter(scope, principal, RaBill.site_id))
    if site_id is not None:
        q = q.where(RaBill.site_id == site_id)
    return [_ra_out(db, b) for b in db.scalars(q.order_by(RaBill.id.desc()))]


@router.get("/ra-bills/{rid}")
def get_ra(rid: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView) -> dict:
    return _ra_out(db, _ra(db, rid, principal, scope))


def _set_lines(db, b: RaBill, c: ClientContract, given: dict[int, Decimal] | None) -> None:
    """Every billable line, with its previous qty and the suggestion from progress; `given`
    overrides this bill's qty. Beyond the line's qty is refused."""
    existing = {ln.contract_line_id: ln for ln in b.lines}
    keep = []
    for cl in c.lines:
        if cl.is_extra and cl.approved_by is None:
            if given and given.get(cl.id):
                raise svc.unprocessable(
                    f"'{cl.description[:40]}' is an extra item not approved yet (billing.approve)"
                )
            continue
        prev = svc.billed_before(db, cl.id, b)
        suggested = max(
            ZERO, (svc.done_qty(db, cl.boq_line_id) if not cl.is_extra else ZERO) - prev
        )
        suggested = min(suggested, max(ZERO, Decimal(cl.qty) - prev))
        ln = existing.get(cl.id) or RaBillLine(contract_line_id=cl.id, rate=cl.rate, qty=ZERO)
        ln.previous_qty, ln.suggested_qty, ln.rate = prev, suggested, cl.rate
        qty = (
            given.get(cl.id, Decimal(ln.qty) if cl.id in existing else suggested)
            if given is not None
            else (Decimal(ln.qty) if cl.id in existing else suggested)
        )
        if prev + qty > Decimal(cl.qty):
            raise svc.unprocessable(
                f"'{cl.description[:40]}': {prev + qty:f} {cl.unit} is beyond the BOQ qty "
                f"{Decimal(cl.qty):f}; "
                "bill the excess as an extra item (approved with billing.approve)"
            )
        ln.qty = qty
        keep.append(ln)
    b.lines = keep


@router.post("/contracts/{cid}/ra-bills", status_code=status.HTTP_201_CREATED)
def create_ra(
    cid: int,
    body: RaIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    c = _contract(db, cid, principal, scope)
    _edit(db, principal, c.site_id)
    if db.scalar(
        select(RaBill.id).where(RaBill.contract_id == c.id, RaBill.status.in_(("draft",)))
    ):
        raise svc.conflict("Finish (submit or cancel) the draft RA bill first")
    seq = (db.scalar(select(func.max(RaBill.seq)).where(RaBill.contract_id == c.id)) or 0) + 1
    site = db.get(Site, c.site_id)
    b = RaBill(
        code=f"RA-{site.code}-{seq:02d}",
        contract_id=c.id,
        site_id=site.id,
        seq=seq,
        period_from=body.period_from,
        period_to=body.period_to or today(),
        other_deduction=body.other_deduction,
        other_deduction_remark=body.other_deduction_remark,
        remark=body.remark,
        created_by=principal.user.id,
    )
    db.add(b)
    _set_lines(
        db,
        b,
        c,
        {ln.contract_line_id: ln.qty for ln in body.lines} if body.lines is not None else None,
    )
    svc.ra_totals(db, b, c)
    db.flush()
    record(
        db,
        request,
        principal,
        "ra.create",
        "ra_bill",
        b.id,
        after={"code": b.code, "gross": str(b.gross)},
    )
    db.commit()
    db.refresh(b)
    return _ra_out(db, b)


@router.put("/ra-bills/{rid}")
def update_ra(
    rid: int,
    body: RaIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status != "draft":
        raise svc.conflict(f"{b.code} is {b.status}")
    c = db.get(ClientContract, b.contract_id)
    b.period_from, b.period_to = body.period_from or b.period_from, body.period_to or b.period_to
    b.other_deduction, b.other_deduction_remark, b.remark = (
        body.other_deduction,
        body.other_deduction_remark,
        body.remark,
    )
    _set_lines(
        db,
        b,
        c,
        {ln.contract_line_id: ln.qty for ln in body.lines} if body.lines is not None else None,
    )
    svc.ra_totals(db, b, c)
    record(db, request, principal, "ra.update", "ra_bill", b.id, after=body.model_dump(mode="json"))
    db.commit()
    db.refresh(b)
    return _ra_out(db, b)


@router.post("/ra-bills/{rid}/submit")
def submit_ra(
    rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status != "draft":
        raise svc.conflict(f"{b.code} is {b.status}")
    if Decimal(b.gross) <= 0:
        raise svc.unprocessable("Nothing to bill")
    b.status, b.submitted_at = "submitted", svc.now()
    record(db, request, principal, "ra.submit", "ra_bill", b.id)
    portal.tell_clients(
        db,
        b.site_id,
        "billing",
        "ra_submitted",
        f"{b.code} submitted for certification",
        f"/portal/sites/{b.site_id}?tab=billing",
    )
    db.commit()
    return _ra_out(db, b)


@router.post("/ra-bills/{rid}/certify")
def certify_ra(
    rid: int,
    body: CertifyIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    """The client's certified quantities (they may cut what was submitted); both are kept."""
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status not in ("submitted", "certified_by_client"):
        raise svc.conflict(f"{b.code} is {b.status}; submit it first")
    given = {x.contract_line_id: x.certified_qty for x in body.lines}
    for ln in b.lines:
        cq = given.get(ln.contract_line_id, Decimal(ln.qty))
        if cq > Decimal(ln.qty):
            raise svc.unprocessable("The certified qty cannot be more than the qty submitted")
        ln.certified_qty = cq
    if body.other_deduction is not None:
        b.other_deduction, b.other_deduction_remark = (
            body.other_deduction,
            body.other_deduction_remark,
        )
    b.status, b.certified_at, b.certified_by_client = (
        "certified",
        svc.now(),
        body.certified_by_client,
    )
    svc.ra_totals(db, b, db.get(ClientContract, b.contract_id))
    record(
        db,
        request,
        principal,
        "ra.certify",
        "ra_bill",
        b.id,
        after={"certified_gross": str(b.certified_gross), "by": body.certified_by_client},
    )
    db.commit()
    return _ra_out(db, b)


@router.post("/ra-bills/{rid}/confirm-client")
def confirm_client(
    rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    """Accept the client's own certification from the portal: their qty per line becomes the
    certified figure. Until this, a client certification changes nothing in the books."""
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status != "certified_by_client":
        raise svc.conflict(f"{b.code} is {b.status}")
    for ln in b.lines:
        ln.certified_qty = ln.client_qty if ln.client_qty is not None else ln.qty
    who = db.get(User, b.client_acted_by) if b.client_acted_by else None
    b.status, b.certified_at = "certified", svc.now()
    b.certified_by_client = who.full_name if who else b.certified_by_client
    svc.ra_totals(db, b, db.get(ClientContract, b.contract_id))
    record(
        db,
        request,
        principal,
        "ra.confirm_client",
        "ra_bill",
        b.id,
        after={"certified_gross": str(b.certified_gross), "by": b.certified_by_client},
    )
    portal.tell_clients(
        db,
        b.site_id,
        "billing",
        "ra_certified",
        f"{b.code}: your certification was confirmed",
        f"/portal/sites/{b.site_id}?tab=billing",
    )
    db.commit()
    return _ra_out(db, b)


@router.post("/ra-bills/{rid}/reopen")
def reopen_ra(
    rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    """A bill the client rejected (or certified, when EESPL disagrees) goes back to draft."""
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status not in ("rejected_by_client", "certified_by_client"):
        raise svc.conflict(f"{b.code} is {b.status}")
    b.status, b.submitted_at = "draft", None
    for ln in b.lines:
        ln.client_qty = None
    record(db, request, principal, "ra.reopen", "ra_bill", b.id)
    db.commit()
    return _ra_out(db, b)


@router.post("/ra-bills/{rid}/cancel")
def cancel_ra(
    rid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status not in (
        "draft",
        "submitted",
        "certified_by_client",
        "rejected_by_client",
        "certified",
    ):
        raise svc.conflict(f"{b.code} is {b.status}; cancel its invoice with a credit note")
    b.status = "cancelled"  # keeps its number
    record(db, request, principal, "ra.cancel", "ra_bill", b.id)
    db.commit()
    return _ra_out(db, b)


class InvoiceFromRa(BaseModel):
    invoice_date: date | None = None
    due_days: int = Field(default=30, ge=0, le=365)
    remark: str | None = None


def camera_gate(db, b: RaBill, c: ClientContract) -> None:
    """While camera sizes are not allowed for billing, a quantity whose BOQ line came from survey
    areas measured only by the camera needs a laser / manual size, or the client's certification."""
    from app.survey import service as survey

    if survey.settings(db).camera_billing_allowed or b.certified_by_client:
        return
    contract_lines = {cl.id: cl for cl in c.lines}
    billed = [contract_lines[ln.contract_line_id].boq_line_id for ln in b.lines
              if Decimal(ln.certified_qty if ln.certified_qty is not None else ln.qty) > 0
              and contract_lines[ln.contract_line_id].boq_line_id]  # fmt: skip
    found = survey.camera_only_for_boq_lines(db, billed)
    if found:
        names = sorted({a.name for areas in found.values() for a in areas})
        raise svc.conflict(
            f"{b.code} bills quantities measured only by the camera ({', '.join(names[:5])}"
            f"{' …' if len(names) > 5 else ''}): give a laser or manual size, or record the "
            "client's certified quantity"
        )


@router.post("/ra-bills/{rid}/invoice", status_code=status.HTTP_201_CREATED)
def invoice_ra(
    rid: int,
    body: InvoiceFromRa,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    b = _ra(db, rid, principal, scope)
    _edit(db, principal, b.site_id)
    if b.status != "certified":
        raise svc.conflict(f"{b.code} is {b.status}; a tax invoice is raised on the certified bill")
    c = db.get(ClientContract, b.contract_id)
    camera_gate(db, b, c)
    if c.client_id is None:
        raise svc.unprocessable("The contract has no client")
    on = body.invoice_date or today()
    ours = svc.our_gstin(db, c.from_gstin_id)
    inv = TaxInvoice(
        number=svc.invoice_number(db, on),
        invoice_date=on,
        due_date=on + svc.timedelta(days=body.due_days),
        site_id=b.site_id,
        contract_id=c.id,
        ra_bill_id=b.id,
        client_id=c.client_id,
        client_gstin=c.client_gstin,
        billing_address=c.billing_address,
        place_of_supply=c.place_of_supply,
        from_gstin_id=ours.id if ours else None,
        interstate=svc.interstate(ours, c.place_of_supply, c.client_gstin),
        retention=b.retention,
        advance_recovery=b.advance_recovery,
        other_deduction=b.other_deduction,
        remark=body.remark or f"Against {b.code}",
        created_by=principal.user.id,
    )
    cl = {x.id: x for x in c.lines}
    for ln in b.lines:
        if not ln.certified_amount:
            continue
        x = cl[ln.contract_line_id]
        inv.lines.append(
            InvoiceLine(
                description=f"{x.item_no + ': ' if x.item_no else ''}{x.description}",
                sac=c.sac,
                qty=ln.certified_qty,
                unit=x.unit,
                rate=ln.rate,
                amount=ln.certified_amount,
                gst_percent=c.gst_percent,
            )
        )
    svc.invoice_tax(inv)
    db.add(inv)
    b.status = "invoiced"
    db.flush()
    record(
        db,
        request,
        principal,
        "invoice.create",
        "tax_invoice",
        inv.id,
        after={"number": inv.number, "ra": b.code},
    )
    db.commit()
    return _invoice_out(db, inv)


@router.get("/ra-bills/{rid}/pdf")
def ra_pdf(rid: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView):
    b = _ra(db, rid, principal, scope)
    return pdf_response(pdf.ra_bill(db, _ra_out(db, b)), b.code)


# --- invoices ------------------------------------------------------------------------------------


class InvLineIn(BaseModel):
    description: str = Field(min_length=1)
    sac: str | None = None
    qty: Decimal | None = None
    unit: str | None = None
    rate: Decimal | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)


class InvoiceIn(BaseModel):
    client_id: int
    site_id: int | None = None
    invoice_date: date | None = None
    due_days: int = Field(default=30, ge=0, le=365)
    place_of_supply: str | None = None
    client_gstin: str | None = None
    billing_address: str | None = None
    remark: str | None = None
    lines: list[InvLineIn] = Field(min_length=1)


class CreditNoteIn(BaseModel):
    on_date: date | None = None
    taxable: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)


def _invoice_out(db, inv: TaxInvoice) -> dict:
    site = db.get(Site, inv.site_id) if inv.site_id else None
    pos = svc.invoice_positions(db, [inv], today())[0] if inv.kind == "invoice" else None
    notes = list(db.scalars(select(TaxInvoice).where(TaxInvoice.against_id == inv.id)))
    return {
        "id": inv.id,
        "number": inv.number,
        "kind": inv.kind,
        "status": inv.status,
        "invoice_date": inv.invoice_date,
        "due_date": inv.due_date,
        "site_id": inv.site_id,
        "site_code": site.code if site else None,
        "client_id": inv.client_id,
        "client_name": inv.client.name,
        "client_gstin": inv.client_gstin,
        "place_of_supply": inv.place_of_supply,
        "interstate": inv.interstate,
        "ra_bill_id": inv.ra_bill_id,
        "against_id": inv.against_id,
        "taxable": inv.taxable,
        "cgst": inv.cgst,
        "sgst": inv.sgst,
        "igst": inv.igst,
        "round_off": inv.round_off,
        "total": inv.total,
        "retention": inv.retention,
        "advance_recovery": inv.advance_recovery,
        "other_deduction": inv.other_deduction,
        "remark": inv.remark,
        "settled": svc.settled(db, inv.id),
        "credited": svc.credited(db, inv.id),
        "outstanding": pos["outstanding"] if pos else None,
        "retention_held": pos["retention_held"] if pos else None,
        "due": pos["due"] if pos else None,
        "age_days": pos["age"] if pos else None,
        "credit_notes": [{"id": n.id, "number": n.number, "total": n.total} for n in notes],
        "lines": [
            {
                "description": ln.description,
                "sac": ln.sac,
                "qty": ln.qty,
                "unit": ln.unit,
                "rate": ln.rate,
                "amount": ln.amount,
                "gst_percent": ln.gst_percent,
            }
            for ln in inv.lines
        ],
        "exported": inv.tally_exported_at is not None,
    }


def _invoice(db, iid, principal, scope) -> TaxInvoice:
    inv = db.get(TaxInvoice, iid)
    if inv is None or not svc.site_ok(db, scope, principal, inv.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


@router.get("/invoices")
def list_invoices(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
    site_id: int | None = None,
    client_id: int | None = None,
) -> list[dict]:
    q = select(TaxInvoice).where(_site_filter(scope, principal, TaxInvoice.site_id))
    if site_id is not None:
        q = q.where(TaxInvoice.site_id == site_id)
    if client_id is not None:
        q = q.where(TaxInvoice.client_id == client_id)
    return [
        _invoice_out(db, i)
        for i in db.scalars(q.order_by(TaxInvoice.invoice_date.desc(), TaxInvoice.id.desc()))
    ]


@router.get("/invoices/{iid}")
def get_invoice(iid: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView) -> dict:
    return _invoice_out(db, _invoice(db, iid, principal, scope))


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: BillingView
) -> dict:
    """A standalone tax invoice (not from an RA bill)."""
    _edit(db, principal, body.site_id)
    client = db.get(Client, body.client_id)
    if client is None:
        raise svc.unprocessable("Client not found")
    site = db.get(Site, body.site_id) if body.site_id else None
    on = body.invoice_date or today()
    ours = svc.our_gstin(db, None)
    pos = body.place_of_supply or (site.state if site else None) or client.state
    inv = TaxInvoice(
        number=svc.invoice_number(db, on),
        invoice_date=on,
        due_date=on + svc.timedelta(days=body.due_days),
        site_id=site.id if site else None,
        client_id=client.id,
        client_gstin=body.client_gstin or client.gstin,
        billing_address=body.billing_address or client.address,
        place_of_supply=pos,
        from_gstin_id=ours.id if ours else None,
        interstate=svc.interstate(ours, pos, body.client_gstin or client.gstin),
        remark=body.remark,
        created_by=principal.user.id,
    )
    sac = svc.settings(db).works_sac
    for ln in body.lines:
        amount = ln.amount if ln.amount is not None else svc.money((ln.qty or 0) * (ln.rate or 0))
        inv.lines.append(
            InvoiceLine(
                description=ln.description,
                sac=ln.sac or sac,
                qty=ln.qty,
                unit=ln.unit,
                rate=ln.rate,
                amount=amount,
                gst_percent=ln.gst_percent,
            )
        )
    svc.invoice_tax(inv)
    db.add(inv)
    db.flush()
    record(
        db,
        request,
        principal,
        "invoice.create",
        "tax_invoice",
        inv.id,
        after={"number": inv.number},
    )
    db.commit()
    return _invoice_out(db, inv)


@router.post("/invoices/{iid}/credit-note", status_code=status.HTTP_201_CREATED)
def credit_note(
    iid: int,
    body: CreditNoteIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    """A reduction of an invoice (needs billing.approve): same tax rate and split, reduces what
    is outstanding."""
    inv = _invoice(db, iid, principal, scope)
    if not svc.site_ok(db, principal.permissions.get("billing.approve"), principal, inv.site_id):
        raise svc.forbidden("Credit notes need billing.approve")
    if inv.kind != "invoice" or inv.status != "issued":
        raise svc.conflict("A credit note is raised against an issued invoice")
    if body.taxable > Decimal(inv.taxable) - sum(
        (
            Decimal(n.taxable)
            for n in db.scalars(select(TaxInvoice).where(TaxInvoice.against_id == inv.id))
        ),
        ZERO,
    ):
        raise svc.unprocessable("The credit note is more than what is left on the invoice")
    on = body.on_date or today()
    rate = inv.lines[0].gst_percent if inv.lines else Decimal(18)
    cn = TaxInvoice(
        number=svc.next_number(db, "CN", on),
        kind="credit_note",
        invoice_date=on,
        site_id=inv.site_id,
        contract_id=inv.contract_id,
        against_id=inv.id,
        client_id=inv.client_id,
        client_gstin=inv.client_gstin,
        billing_address=inv.billing_address,
        place_of_supply=inv.place_of_supply,
        from_gstin_id=inv.from_gstin_id,
        interstate=inv.interstate,
        remark=body.reason,
        created_by=principal.user.id,
    )
    cn.lines.append(
        InvoiceLine(
            description=f"Credit against {inv.number}: {body.reason}",
            sac=inv.lines[0].sac if inv.lines else None,
            amount=body.taxable,
            gst_percent=rate,
        )
    )
    svc.invoice_tax(cn)
    db.add(cn)
    db.flush()
    record(
        db,
        request,
        principal,
        "invoice.credit_note",
        "tax_invoice",
        inv.id,
        after={"number": cn.number, "total": str(cn.total)},
    )
    db.commit()
    return _invoice_out(db, inv)


@router.get("/invoices/{iid}/pdf")
def invoice_pdf(iid: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView):
    inv = _invoice(db, iid, principal, scope)
    return pdf_response(
        pdf.tax_invoice(db, inv, _invoice_out(db, inv)), inv.number.replace("/", "-")
    )


# --- receipts ------------------------------------------------------------------------------------


class AllocIn(BaseModel):
    invoice_id: int
    amount: Decimal = Field(gt=0)


class ReceiptIn(BaseModel):
    client_id: int
    site_id: int | None = None
    on_date: date | None = None
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "neft"
    ref_no: str | None = None
    bank_account_id: int | None = None
    amount: Decimal = Field(ge=0)
    tds_amount: Decimal = Field(default=Decimal(0), ge=0)
    gst_tds_amount: Decimal = Field(default=Decimal(0), ge=0)
    write_off: Decimal = Field(default=Decimal(0), ge=0)
    write_off_reason: str | None = None
    is_advance: bool = False
    is_retention: bool = False
    remark: str | None = None
    allocations: list[AllocIn] = []


def _receipt_out(db, r: Receipt) -> dict:
    invs = {
        i.id: i.number
        for i in db.scalars(
            select(TaxInvoice).where(
                TaxInvoice.id.in_([a.invoice_id for a in r.allocations] or [0])
            )
        )
    }
    return {
        "id": r.id,
        "number": r.number,
        "client_id": r.client_id,
        "client_name": db.get(Client, r.client_id).name,
        "site_id": r.site_id,
        "on_date": r.on_date,
        "mode": r.mode,
        "ref_no": r.ref_no,
        "amount": r.amount,
        "tds_amount": r.tds_amount,
        "gst_tds_amount": r.gst_tds_amount,
        "write_off": r.write_off,
        "write_off_reason": r.write_off_reason,
        "is_advance": r.is_advance,
        "is_retention": r.is_retention,
        "allocations": [
            {"invoice_id": a.invoice_id, "number": invs.get(a.invoice_id), "amount": a.amount}
            for a in r.allocations
        ],
    }


@router.get("/receipts")
def list_receipts(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
    client_id: int | None = None,
    site_id: int | None = None,
) -> list[dict]:
    q = select(Receipt).where(_site_filter(scope, principal, Receipt.site_id))
    if client_id is not None:
        q = q.where(Receipt.client_id == client_id)
    if site_id is not None:
        q = q.where(Receipt.site_id == site_id)
    return [
        _receipt_out(db, r)
        for r in db.scalars(q.order_by(Receipt.on_date.desc(), Receipt.id.desc()))
    ]


@router.post("/receipts", status_code=status.HTTP_201_CREATED)
def create_receipt(
    body: ReceiptIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: BillingView
) -> dict:
    """Money received with the client's TDS (income tax and GST, kept apart to claim them) and
    any write-off, spread over invoices. An advance receipt is not spread."""
    _edit(db, principal, body.site_id)
    if db.get(Client, body.client_id) is None:
        raise svc.unprocessable("Client not found")
    if body.bank_account_id and db.get(CompanyBankAccount, body.bank_account_id) is None:
        raise svc.unprocessable("Bank account not found")
    if body.write_off and not (body.write_off_reason or "").strip():
        raise svc.unprocessable("Give the reason for the short payment / write-off")
    settled_total = body.amount + body.tds_amount + body.gst_tds_amount + body.write_off
    if body.is_advance:
        if body.allocations:
            raise svc.unprocessable("An advance is not set against invoices")
    else:
        if sum((a.amount for a in body.allocations), ZERO) != settled_total:
            raise svc.unprocessable(
                f"Spread the full {settled_total:f} (received + TDS + GST TDS + write-off) "
                "over invoices"
            )
    on = body.on_date or today()
    r = Receipt(
        number=svc.next_number(db, "RCT", on),
        on_date=on,
        created_by=principal.user.id,
        **body.model_dump(exclude={"allocations", "on_date"}),
    )
    for a in body.allocations:
        inv = db.get(TaxInvoice, a.invoice_id)
        if inv is None or inv.client_id != body.client_id or inv.kind != "invoice":
            raise svc.unprocessable("An allocation is not an invoice of this client")
        if a.amount > svc.outstanding(db, inv):
            raise svc.unprocessable(
                f"{inv.number}: {a.amount:f} is more than the "
                f"{svc.outstanding(db, inv):f} outstanding"
            )
        r.allocations.append(ReceiptAllocation(invoice_id=inv.id, amount=a.amount))
        if r.site_id is None:
            r.site_id = inv.site_id
    db.add(r)
    db.flush()
    record(
        db,
        request,
        principal,
        "receipt.create",
        "receipt",
        r.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _receipt_out(db, r)


class ReleaseIn(BaseModel):
    on_date: date | None = None
    amount: Decimal = Field(gt=0)
    remark: str | None = None


@router.post("/sites/{site_id}/retention-release", status_code=status.HTTP_201_CREATED)
def release_retention(
    site_id: int,
    body: ReleaseIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    """The client releases retention: that amount falls due (and is collected with a receipt)."""
    site = _site(db, site_id, principal, scope)
    _edit(db, principal, site.id)
    held = svc.retention_held(db, site.id)[2]
    if body.amount > held:
        raise svc.unprocessable(f"Only {held:f} is held on {site.code}")
    db.add(
        RetentionRelease(
            site_id=site.id,
            on_date=body.on_date or today(),
            amount=body.amount,
            remark=body.remark,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "retention.release",
        "site",
        site.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    retained, released, held = svc.retention_held(db, site.id)
    return {"site_id": site.id, "retained": retained, "released": released, "held": held}


@router.get("/sites/{site_id}/retention")
def site_retention(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    site = _site(db, site_id, principal, scope)
    retained, released, held = svc.retention_held(db, site.id)
    return {"site_id": site.id, "retained": retained, "released": released, "held": held}


# --- ledger and ageing ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/ledger")
def client_ledger(
    client_id: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    rows = []
    for inv in db.scalars(
        select(TaxInvoice).where(
            TaxInvoice.client_id == client.id,
            TaxInvoice.status == "issued",
            _site_filter(scope, principal, TaxInvoice.site_id),
        )
    ):
        if inv.kind == "invoice":
            rows.append((inv.invoice_date, inv.number, "Invoice", Decimal(inv.total), ZERO))
            for label, amt in (
                ("Advance recovery", inv.advance_recovery),
                ("Other deduction", inv.other_deduction),
            ):
                if Decimal(amt):
                    rows.append((inv.invoice_date, inv.number, label, ZERO, Decimal(amt)))
        else:
            rows.append((inv.invoice_date, inv.number, "Credit note", ZERO, Decimal(inv.total)))
    for r in db.scalars(
        select(Receipt).where(
            Receipt.client_id == client.id, _site_filter(scope, principal, Receipt.site_id)
        )
    ):
        rows.append(
            (
                r.on_date,
                r.number,
                "Advance received" if r.is_advance else "Receipt",
                ZERO,
                Decimal(r.amount),
            )
        )
        for label, amt in (
            ("Client TDS", r.tds_amount),
            ("GST TDS", r.gst_tds_amount),
            ("Write-off", r.write_off),
        ):
            if Decimal(amt):
                rows.append((r.on_date, r.number, label, ZERO, Decimal(amt)))
    rows.sort(key=lambda x: (x[0], x[1]))
    balance = ZERO
    out = []
    for d, ref, kind, dr, cr in rows:
        balance += dr - cr
        out.append(
            {"date": d, "ref": ref, "kind": kind, "debit": dr, "credit": cr, "balance": balance}
        )
    return {"client_id": client.id, "client_name": client.name, "rows": out, "balance": balance}


@router.get("/ageing")
def ageing(
    db: DbSession, principal: CurrentPrincipal, scope: BillingView, site_id: int | None = None
) -> dict:
    """Receivables due by age (0-30, 31-60, 61-90, 90+ days from the invoice date), with the
    retention still held shown apart."""
    q = select(TaxInvoice).where(
        TaxInvoice.kind == "invoice",
        TaxInvoice.status == "issued",
        _site_filter(scope, principal, TaxInvoice.site_id),
    )
    if site_id is not None:
        q = q.where(TaxInvoice.site_id == site_id)
    by_client: dict[int, dict] = {}
    for p in svc.invoice_positions(db, list(db.scalars(q)), today()):
        inv = p["invoice"]
        row = by_client.setdefault(
            inv.client_id,
            {
                "client_id": inv.client_id,
                "client_name": inv.client.name,
                "0-30": ZERO,
                "31-60": ZERO,
                "61-90": ZERO,
                "90+": ZERO,
                "due": ZERO,
                "retention_held": ZERO,
                "invoices": [],
            },
        )
        row[svc.bucket(p["age"])] += p["due"]
        row["due"] += p["due"]
        row["retention_held"] += p["retention_held"]
        if p["outstanding"]:
            row["invoices"].append(
                {
                    "id": inv.id,
                    "number": inv.number,
                    "date": inv.invoice_date,
                    "age": p["age"],
                    "outstanding": p["outstanding"],
                    "due": p["due"],
                    "retention_held": p["retention_held"],
                }
            )
    rows = sorted(by_client.values(), key=lambda r: -r["due"])
    return {
        "rows": rows,
        "totals": {
            k: sum((r[k] for r in rows), ZERO)
            for k in ("0-30", "31-60", "61-90", "90+", "due", "retention_held")
        },
    }


@router.get("/lookups")
def lookups(db: DbSession, principal: CurrentPrincipal) -> dict:
    perms = principal.permissions
    if not any(
        perms.get(c)
        for c in (
            "billing.view",
            "payables.view",
            "expense.create",
            "payroll.view",
            "finance.export",
        )
    ):
        raise svc.forbidden("No finance permission")
    banks = [
        {"id": b.id, "name": f"{b.bank or 'Bank'} ••••{b.account_number[-4:]}"}
        for b in db.scalars(select(CompanyBankAccount))
    ]
    sites = db.execute(
        select(Site.id, Site.code, Site.name)
        .where(Site.status != "closed")
        .order_by(Site.code.desc())
    ).all()
    return {
        "banks": banks,
        "sites": [{"id": i, "code": c, "name": n} for i, c, n in sites],
        "clients": [
            {"id": c.id, "name": c.name} for c in db.scalars(select(Client).order_by(Client.name))
        ],
        "tenders_with_sites": [
            t for t in db.scalars(select(Tender.id).where(Tender.status == "won"))
        ],
        "permissions": {
            k: v
            for k, v in perms.items()
            if k.split(".")[0] in ("billing", "payables", "expense", "payroll", "finance", "tender")
        },
    }
