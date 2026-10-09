"""Vendor bills (three-way matched with the PO and GRN, or direct), payments, subcontractor RA
bills and retention, vendor ledger, ageing and the "due this week" list.

payables.view to see; payables.edit to enter and approve bills and pay up to the approval limit;
a payment above the limit waits for payables.approve.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.db import DbSession
from app.execution.common import names, record
from app.execution.models import WoLine, WoMeasurement, WorkOrder
from app.execution.service import today
from app.finance import service as svc
from app.finance.models import (
    Payment,
    PaymentAllocation,
    SubconBill,
    SubconBillLine,
    SubconRetentionRelease,
    VendorBill,
    VendorBillGrn,
    VendorBillLine,
)
from app.masters.models import CompanyBankAccount, Vendor
from app.material.models import Grn, PoLine, PurchaseOrder, SiteIssue, SiteIssueLine, Store
from app.material.service import is_interstate

router = APIRouter(prefix="/api/finance", tags=["finance"])
PayView = Annotated[str, Depends(require_permission("payables.view"))]
ZERO = Decimal(0)


def _edit(principal: Principal):
    if principal.permissions.get("payables.edit") is None:
        raise svc.forbidden("Missing permission: payables.edit")


# --- vendor bills --------------------------------------------------------------------------------


class GrnLineBill(BaseModel):
    grn_line_id: int
    qty: Decimal | None = Field(default=None, ge=0)  # the vendor's billed qty (default: accepted)
    rate: Decimal | None = Field(default=None, ge=0)  # billed rate (default: the PO's net rate)


class DirectLine(BaseModel):
    description: str = Field(min_length=1)
    hsn_code: str | None = None
    qty: Decimal = Field(default=Decimal(1), gt=0)
    unit: str | None = None
    rate: Decimal = Field(ge=0)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)


class VendorBillIn(BaseModel):
    vendor_id: int
    kind: Literal["material", "service", "freight"] = "material"
    bill_no: str = Field(min_length=1, max_length=60)
    bill_date: date
    due_date: date | None = None  # default: from the vendor's payment terms
    site_id: int | None = None
    grn_ids: list[int] = []
    grn_lines: list[GrnLineBill] = []  # overrides per GRN line
    lines: list[DirectLine] = []  # a direct bill (no GRN)
    itc_eligible: bool = True
    tds_percent: Decimal | None = Field(default=None, ge=0, le=20)  # default: by vendor type
    remark: str | None = None


def _bill_out(db, b: VendorBill) -> dict:
    grns = list(
        db.scalars(
            select(Grn.code)
            .join(VendorBillGrn, VendorBillGrn.grn_id == Grn.id)
            .where(VendorBillGrn.vendor_bill_id == b.id)
        )
    )
    paid = svc.bill_paid(db, b.id)
    who = names(db, [b.approved_by])
    return {
        "id": b.id,
        "number": b.number,
        "kind": b.kind,
        "vendor_id": b.vendor_id,
        "vendor_name": b.vendor.name,
        "vendor_gstin": b.vendor.gstin,
        "bill_no": b.bill_no,
        "bill_date": b.bill_date,
        "due_date": b.due_date,
        "site_id": b.site_id,
        "interstate": b.interstate,
        "itc_eligible": b.itc_eligible,
        "taxable": b.taxable,
        "cgst": b.cgst,
        "sgst": b.sgst,
        "igst": b.igst,
        "round_off": b.round_off,
        "total": b.total,
        "tds_section": b.tds_section,
        "tds_percent": b.tds_percent,
        "tds_amount": b.tds_amount,
        "payable": b.payable,
        "paid": paid,
        "outstanding": svc.bill_outstanding(db, b),
        "status": b.status,
        "match_issues": b.match_issues,
        "blocked_reasons": b.blocked_reasons,
        "blocked": bool(b.blocked_reasons) and b.released_at is None,
        "released_at": b.released_at,
        "released_by": names(db, [b.released_by]).get(b.released_by) if b.released_by else None,
        "release_reason": b.release_reason,
        "grns": grns,
        "approved_by_name": who.get(b.approved_by),
        "remark": b.remark,
        "lines": [
            {
                "id": ln.id,
                "description": ln.description,
                "hsn_code": ln.hsn_code,
                "qty": ln.qty,
                "unit": ln.unit,
                "rate": ln.rate,
                "amount": ln.amount,
                "gst_percent": ln.gst_percent,
                "grn_qty": ln.grn_qty,
                "po_rate": ln.po_rate,
            }
            for ln in b.lines
        ],
    }


def _bill_tax(db, b: VendorBill) -> None:
    taxable = sum((Decimal(ln.amount) for ln in b.lines), ZERO)
    tax = svc.money(
        sum((Decimal(ln.amount) * Decimal(ln.gst_percent) / 100 for ln in b.lines), ZERO)
    )
    b.taxable = svc.money(taxable)
    if b.interstate:
        b.igst, b.cgst, b.sgst = tax, ZERO, ZERO
    else:
        b.cgst = svc.money(tax / 2)
        b.sgst, b.igst = tax - b.cgst, ZERO
    before = b.taxable + tax
    b.total = before.quantize(Decimal(1), "ROUND_HALF_UP")
    b.round_off = b.total - before
    b.tds_amount = svc.money(b.taxable * Decimal(b.tds_percent) / 100)
    b.payable = b.total - b.tds_amount


def _matched_lines(db, body: VendorBillIn, vendor: Vendor, tolerance: Decimal):
    """Lines from the GRNs' accepted quantities, matched against the PO rate and the GRN qty."""
    lines, issues, site_id, interstate, grns = [], [], None, False, []
    given = {g.grn_line_id: g for g in body.grn_lines}
    for gid in dict.fromkeys(body.grn_ids):
        g = db.get(Grn, gid)
        if g is None or g.vendor_id != vendor.id:
            raise svc.unprocessable(f"GRN {gid} is not this vendor's")
        if g.status != "approved":
            raise svc.conflict(f"{g.code} is {g.status}: bill approved GRNs")
        if db.scalar(
            select(VendorBillGrn.vendor_bill_id)
            .join(VendorBill, VendorBill.id == VendorBillGrn.vendor_bill_id)
            .where(VendorBillGrn.grn_id == g.id, VendorBill.status != "cancelled")
        ):
            raise svc.conflict(f"{g.code} is already billed")
        grns.append(g)
        po = db.get(PurchaseOrder, g.po_id) if g.po_id else None
        if po is not None:
            interstate = po.interstate
        store = db.get(Store, g.store_id)
        site_id = site_id or store.site_id
        for gl in g.lines:
            if Decimal(gl.accepted_qty) <= 0:
                continue
            pl = db.get(PoLine, gl.po_line_id) if gl.po_line_id else None
            po_rate = Decimal(gl.rate)  # net of discount, per unit
            o = given.get(gl.id)
            qty = o.qty if o and o.qty is not None else Decimal(gl.accepted_qty)
            rate = o.rate if o and o.rate is not None else po_rate
            name = gl.product.name
            if (
                Decimal(gl.accepted_qty)
                and abs(qty - Decimal(gl.accepted_qty)) / Decimal(gl.accepted_qty) * 100 > tolerance
            ):
                issues.append(
                    {
                        "grn": g.code,
                        "item": name,
                        "kind": "qty",
                        "billed": str(qty),
                        "expected": str(gl.accepted_qty),
                        "message": f"{name}: billed {qty:f} {gl.unit}, "
                        f"GRN accepted {Decimal(gl.accepted_qty).normalize():f}",
                    }
                )
            if po_rate and abs(rate - po_rate) / po_rate * 100 > tolerance:
                issues.append(
                    {
                        "grn": g.code,
                        "item": name,
                        "kind": "rate",
                        "billed": str(rate),
                        "expected": str(po_rate),
                        "message": f"{name}: billed rate {rate:f}, PO rate {po_rate.normalize():f}",
                    }
                )
            gst = Decimal(pl.gst_percent) if pl else Decimal(gl.product.gst_percent)
            if not vendor.gstin:
                gst = ZERO
            lines.append(
                VendorBillLine(
                    grn_line_id=gl.id,
                    po_line_id=gl.po_line_id,
                    description=name,
                    hsn_code=gl.product.hsn_code,
                    qty=qty,
                    unit=gl.unit,
                    rate=rate,
                    amount=svc.money(qty * rate),
                    gst_percent=gst,
                    grn_qty=gl.accepted_qty,
                    po_rate=po_rate,
                )
            )
    return lines, issues, site_id, interstate, grns


@router.get("/vendor-bills")
def list_bills(
    db: DbSession,
    _: PayView,
    vendor_id: int | None = None,
    status_: str | None = None,
    site_id: int | None = None,
) -> list[dict]:
    q = select(VendorBill)
    if vendor_id is not None:
        q = q.where(VendorBill.vendor_id == vendor_id)
    if status_:
        q = q.where(VendorBill.status.in_(status_.split(",")))
    if site_id is not None:
        q = q.where(VendorBill.site_id == site_id)
    return [
        _bill_out(db, b)
        for b in db.scalars(q.order_by(VendorBill.bill_date.desc(), VendorBill.id.desc()))
    ]


@router.get("/vendor-bills/{bid}")
def get_bill(bid: int, db: DbSession, _: PayView) -> dict:
    b = db.get(VendorBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return _bill_out(db, b)


@router.post("/vendor-bills", status_code=status.HTTP_201_CREATED)
def create_bill(
    body: VendorBillIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    _edit(principal)
    vendor = db.get(Vendor, body.vendor_id)
    if vendor is None:
        raise svc.unprocessable("Vendor not found")
    if db.scalar(
        select(VendorBill.id).where(
            VendorBill.vendor_id == vendor.id,
            VendorBill.bill_no == body.bill_no,
            VendorBill.status != "cancelled",
        )
    ):
        raise svc.conflict(f"{vendor.name}'s bill {body.bill_no} is already entered")
    st = svc.settings(db)
    section, tds = svc.tds_for(db, vendor)
    b = VendorBill(
        number=svc.next_number(db, "VB", body.bill_date),
        kind=body.kind,
        vendor_id=vendor.id,
        vendor=vendor,
        bill_no=body.bill_no,
        bill_date=body.bill_date,
        itc_eligible=body.itc_eligible and bool(vendor.gstin),
        tds_section=section,
        tds_percent=body.tds_percent if body.tds_percent is not None else tds,
        remark=body.remark,
        created_by=principal.user.id,
    )
    if body.grn_ids:
        lines, issues, site_id, interstate, grns = _matched_lines(
            db, body, vendor, Decimal(st.match_tolerance_percent)
        )
        b.lines, b.match_issues, b.site_id, b.interstate = (
            lines,
            issues,
            body.site_id or site_id,
            interstate,
        )
    elif body.lines:
        b.site_id = body.site_id
        b.interstate = is_interstate(vendor, svc.our_gstin(db, None))
        b.lines = [
            VendorBillLine(
                description=ln.description,
                hsn_code=ln.hsn_code,
                qty=ln.qty,
                unit=ln.unit,
                rate=ln.rate,
                amount=svc.money(ln.qty * ln.rate),
                gst_percent=ln.gst_percent if vendor.gstin else ZERO,
            )
            for ln in body.lines
        ]
        grns = []
    else:
        raise svc.unprocessable("Bill GRNs, or give the lines of a direct bill")
    days = vendor.payment_terms_days or 30
    b.due_date = body.due_date or body.bill_date + timedelta(days=days)
    _bill_tax(db, b)
    b.tds_section, b.tds_percent, b.tds_amount, tds_note = svc.tds_on_bill(
        db, vendor, Decimal(b.taxable), body.bill_date, None, body.tds_percent
    )
    if tds_note:
        b.remark = f"{b.remark}\n{tds_note}" if b.remark else tds_note
    b.payable = b.total - b.tds_amount
    db.add(b)
    db.flush()
    for g in grns:
        db.add(VendorBillGrn(vendor_bill_id=b.id, grn_id=g.id))
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    sitecontrol.refresh_block(db, b)
    record(
        db,
        request,
        principal,
        "vendor_bill.create",
        "vendor_bill",
        b.id,
        after={"number": b.number, "bill_no": b.bill_no, "issues": len(b.match_issues)},
    )
    db.commit()
    db.refresh(b)
    return _bill_out(db, b)


class ApproveBill(BaseModel):
    accept_differences: bool = False


@router.post("/vendor-bills/{bid}/approve")
def approve_bill(
    bid: int,
    body: ApproveBill,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PayView,
) -> dict:
    """Approved bills can be paid. A bill whose match flagged differences is approved only when
    they are accepted explicitly."""
    _edit(principal)
    b = db.get(VendorBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if b.status != "draft":
        raise svc.conflict(f"{b.number} is {b.status}")
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    sitecontrol.approval_gate(db, b)  # blocked by the three-way match until released
    if b.match_issues and not body.accept_differences and b.released_at is None:
        raise svc.unprocessable(
            "The bill does not match the PO / GRN: accept the differences to approve it"
        )
    b.status, b.approved_by, b.approved_at = (
        "approved",
        principal.user.id,
        svc.now(),
    )
    record(
        db,
        request,
        principal,
        "vendor_bill.approve",
        "vendor_bill",
        b.id,
        after={"accepted": body.accept_differences},
    )
    db.commit()
    return _bill_out(db, b)


@router.post("/vendor-bills/{bid}/cancel")
def cancel_bill(
    bid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    _edit(principal)
    b = db.get(VendorBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if svc.bill_paid(db, b.id) > 0:
        raise svc.conflict(f"{b.number} has payments")
    b.status = "cancelled"
    record(db, request, principal, "vendor_bill.cancel", "vendor_bill", b.id)
    db.commit()
    return _bill_out(db, b)


# --- payments ------------------------------------------------------------------------------------


class PayAlloc(BaseModel):
    vendor_bill_id: int
    amount: Decimal = Field(gt=0)


class PaymentIn(BaseModel):
    vendor_id: int
    on_date: date | None = None
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "neft"
    ref_no: str | None = None
    bank_account_id: int | None = None
    allocations: list[PayAlloc] = Field(min_length=1)
    remark: str | None = None


def _payment_out(db, p: Payment) -> dict:
    nums = dict(
        db.execute(
            select(VendorBill.id, VendorBill.number).where(
                VendorBill.id.in_([a.vendor_bill_id for a in p.allocations] or [0])
            )
        ).all()
    )
    who = names(db, [p.approved_by, p.created_by])
    return {
        "id": p.id,
        "number": p.number,
        "vendor_id": p.vendor_id,
        "vendor_name": p.vendor.name,
        "on_date": p.on_date,
        "mode": p.mode,
        "ref_no": p.ref_no,
        "bank_account_id": p.bank_account_id,
        "amount": p.amount,
        "status": p.status,
        "approved_by_name": who.get(p.approved_by),
        "created_by_name": who.get(p.created_by),
        "remark": p.remark,
        "allocations": [
            {
                "vendor_bill_id": a.vendor_bill_id,
                "number": nums.get(a.vendor_bill_id),
                "amount": a.amount,
            }
            for a in p.allocations
        ],
    }


@router.get("/payments")
def list_payments(
    db: DbSession, _: PayView, vendor_id: int | None = None, status_: str | None = None
) -> list[dict]:
    q = select(Payment)
    if vendor_id is not None:
        q = q.where(Payment.vendor_id == vendor_id)
    if status_:
        q = q.where(Payment.status == status_)
    return [
        _payment_out(db, p)
        for p in db.scalars(q.order_by(Payment.on_date.desc(), Payment.id.desc()))
    ]


@router.post("/payments", status_code=status.HTTP_201_CREATED)
def create_payment(
    body: PaymentIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    """Partial payments are fine. Above the approval limit the payment waits for
    payables.approve (unless the payer holds it)."""
    _edit(principal)
    vendor = db.get(Vendor, body.vendor_id)
    if vendor is None:
        raise svc.unprocessable("Vendor not found")
    if body.bank_account_id and db.get(CompanyBankAccount, body.bank_account_id) is None:
        raise svc.unprocessable("Bank account not found")
    on = body.on_date or today()
    amount = sum((a.amount for a in body.allocations), ZERO)
    p = Payment(
        number=svc.next_number(db, "PAY", on),
        vendor_id=vendor.id,
        vendor=vendor,
        on_date=on,
        mode=body.mode,
        ref_no=body.ref_no,
        bank_account_id=body.bank_account_id,
        amount=amount,
        remark=body.remark,
        created_by=principal.user.id,
    )
    pending_others = {}
    for a in body.allocations:
        b = db.get(VendorBill, a.vendor_bill_id)
        if b is None or b.vendor_id != vendor.id:
            raise svc.unprocessable("A bill is not this vendor's")
        if b.status not in ("approved", "partly_paid"):
            raise svc.conflict(f"{b.number} is {b.status}: approve it first")
        waiting = pending_others.setdefault(
            b.id,
            Decimal(
                db.scalar(
                    select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
                    .join(Payment, Payment.id == PaymentAllocation.payment_id)
                    .where(
                        PaymentAllocation.vendor_bill_id == b.id,
                        Payment.status == "pending_approval",
                    )
                )
            ),
        )
        if a.amount > svc.bill_outstanding(db, b) - waiting:
            raise svc.unprocessable(f"{b.number}: {a.amount:f} is more than what is left to pay")
        p.allocations.append(PaymentAllocation(vendor_bill_id=b.id, amount=a.amount))
    limit = Decimal(svc.settings(db).payment_approval_limit)
    if amount > limit and principal.permissions.get("payables.approve") is None:
        p.status = "pending_approval"
    else:
        p.status, p.approved_by, p.approved_at = (
            "paid",
            principal.user.id,
            svc.now(),
        )
    db.add(p)
    db.flush()
    for a in p.allocations:
        svc.refresh_bill(db, db.get(VendorBill, a.vendor_bill_id))
    record(
        db,
        request,
        principal,
        "payment.create",
        "payment",
        p.id,
        after={"number": p.number, "amount": str(amount), "status": p.status},
    )
    db.commit()
    return _payment_out(db, p)


@router.post("/payments/{pid}/approve")
def approve_payment(
    pid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    if principal.permissions.get("payables.approve") is None:
        raise svc.forbidden(
            f"Payments above ₹{svc.settings(db).payment_approval_limit:,.0f} need payables.approve"
        )
    p = db.get(Payment, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if p.status != "pending_approval":
        raise svc.conflict(f"{p.number} is {p.status}")
    p.status, p.approved_by, p.approved_at = "paid", principal.user.id, svc.now()
    db.flush()
    for a in p.allocations:
        svc.refresh_bill(db, db.get(VendorBill, a.vendor_bill_id))
    record(db, request, principal, "payment.approve", "payment", p.id)
    db.commit()
    return _payment_out(db, p)


@router.post("/payments/{pid}/cancel")
def cancel_payment(
    pid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    _edit(principal)
    p = db.get(Payment, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if p.status != "pending_approval":
        raise svc.conflict(
            "Only a payment waiting for approval is cancelled (a paid one is reversed in Tally)"
        )
    p.status = "cancelled"
    record(db, request, principal, "payment.cancel", "payment", p.id)
    db.commit()
    return _payment_out(db, p)


# --- ledger, ageing, due -------------------------------------------------------------------------


@router.get("/vendors/{vendor_id}/ledger")
def vendor_ledger(vendor_id: int, db: DbSession, _: PayView) -> dict:
    v = db.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    rows = []
    for b in db.scalars(
        select(VendorBill).where(
            VendorBill.vendor_id == v.id, VendorBill.status.not_in(("draft", "cancelled"))
        )
    ):
        rows.append((b.bill_date, b.number, f"Bill {b.bill_no}", ZERO, Decimal(b.total)))
        if Decimal(b.tds_amount):
            rows.append((b.bill_date, b.number, "TDS deducted", Decimal(b.tds_amount), ZERO))
        other = Decimal(b.total) - Decimal(b.tds_amount) - Decimal(b.payable)
        if other:
            rows.append((b.bill_date, b.number, "Retention / recoveries", other, ZERO))
    for p in db.scalars(select(Payment).where(Payment.vendor_id == v.id, Payment.status == "paid")):
        rows.append((p.on_date, p.number, f"Payment ({p.mode})", Decimal(p.amount), ZERO))
    rows.sort(key=lambda x: (x[0], x[1]))
    bal, out = ZERO, []
    for d, ref, kind, dr, cr in rows:
        bal += cr - dr  # what we owe
        out.append({"date": d, "ref": ref, "kind": kind, "debit": dr, "credit": cr, "balance": bal})
    return {"vendor_id": v.id, "vendor_name": v.name, "rows": out, "balance": bal}


@router.get("/payables/ageing")
def payables_ageing(db: DbSession, _: PayView) -> dict:
    """Outstanding by days past the due date (not yet due, 0-30, 31-60, 61-90, 90+)."""
    t = today()
    by_vendor: dict[int, dict] = {}
    for b in db.scalars(
        select(VendorBill).where(VendorBill.status.in_(("approved", "partly_paid")))
    ):
        os_ = svc.bill_outstanding(db, b)
        if not os_:
            continue
        late = (t - b.due_date).days
        key = "not_due" if late < 0 else svc.bucket(late)
        row = by_vendor.setdefault(
            b.vendor_id,
            {
                "vendor_id": b.vendor_id,
                "vendor_name": b.vendor.name,
                "not_due": ZERO,
                "0-30": ZERO,
                "31-60": ZERO,
                "61-90": ZERO,
                "90+": ZERO,
                "total": ZERO,
            },
        )
        row[key] += os_
        row["total"] += os_
    rows = sorted(by_vendor.values(), key=lambda r: -r["total"])
    return {
        "rows": rows,
        "totals": {
            k: sum((r[k] for r in rows), ZERO)
            for k in ("not_due", "0-30", "31-60", "61-90", "90+", "total")
        },
    }


@router.get("/payables/due")
def due_this_week(db: DbSession, _: PayView, days: int = 7) -> list[dict]:
    """Bills due within `days` (and overdue ones), oldest due first."""
    until = svc.due_by(days)
    out = []
    for b in db.scalars(
        select(VendorBill)
        .where(VendorBill.status.in_(("approved", "partly_paid")), VendorBill.due_date <= until)
        .order_by(VendorBill.due_date)
    ):
        os_ = svc.bill_outstanding(db, b)
        if os_:
            out.append(
                {
                    "id": b.id,
                    "number": b.number,
                    "vendor_id": b.vendor_id,
                    "vendor_name": b.vendor.name,
                    "bill_no": b.bill_no,
                    "due_date": b.due_date,
                    "outstanding": os_,
                    "overdue": b.due_date < today(),
                }
            )
    return out


# --- subcontractor RA bills ----------------------------------------------------------------------


class SubconBillIn(BaseModel):
    bill_date: date | None = None
    measurement_ids: list[int] | None = None  # default: every verified, unbilled measurement
    material_recovery: Decimal | None = Field(
        default=None, ge=0
    )  # default: issued to them, not yet recovered
    advance_recovery: Decimal = Field(default=Decimal(0), ge=0)
    gst_percent: Decimal | None = Field(default=None, ge=0, le=28)  # default: 18 if registered
    remark: str | None = None


def material_issued(db, wo: WorkOrder) -> Decimal:
    """EESPL material handed to the subcontractor on the WO's site (issues less returns)."""
    total = ZERO
    for kind, value in db.execute(
        select(SiteIssue.kind, func.coalesce(func.sum(SiteIssueLine.value), 0))
        .join(SiteIssueLine, SiteIssueLine.issue_id == SiteIssue.id)
        .where(SiteIssue.site_id == wo.site_id, SiteIssue.subcontractor_id == wo.subcontractor_id)
        .group_by(SiteIssue.kind)
    ):
        total += Decimal(value) if kind == "issue" else -Decimal(value)
    return total


def material_recovered(db, wo: WorkOrder, exclude: int | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(SubconBill.material_recovery), 0)).where(
        SubconBill.wo_id == wo.id, SubconBill.status != "cancelled"
    )
    if exclude:
        q = q.where(SubconBill.id != exclude)
    return Decimal(db.scalar(q))


def unbilled(db, wo: WorkOrder) -> list[tuple[WoMeasurement, WoLine]]:
    billed = (
        select(SubconBillLine.measurement_id)
        .join(SubconBill, SubconBill.id == SubconBillLine.subcon_bill_id)
        .where(SubconBill.status != "cancelled")
    )
    return list(
        db.execute(
            select(WoMeasurement, WoLine)
            .join(WoLine, WoLine.id == WoMeasurement.line_id)
            .where(
                WoLine.wo_id == wo.id,
                WoMeasurement.status == "verified",
                WoMeasurement.id.not_in(billed),
            )
            .order_by(WoMeasurement.on_date, WoMeasurement.id)
        ).all()
    )


def _retained(db, wo_id: int) -> tuple[Decimal, Decimal]:
    held = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(SubconBill.retention), 0)).where(
                SubconBill.wo_id == wo_id, SubconBill.status == "approved"
            )
        )
    )
    released = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(SubconRetentionRelease.amount), 0)).where(
                SubconRetentionRelease.wo_id == wo_id
            )
        )
    )
    return held, released


def _subcon_out(db, b: SubconBill) -> dict:
    wo = db.get(WorkOrder, b.wo_id)
    lines = db.execute(
        select(SubconBillLine, WoMeasurement, WoLine)
        .join(WoMeasurement, WoMeasurement.id == SubconBillLine.measurement_id)
        .join(WoLine, WoLine.id == WoMeasurement.line_id)
        .where(SubconBillLine.subcon_bill_id == b.id)
    ).all()
    vb = db.get(VendorBill, b.vendor_bill_id) if b.vendor_bill_id else None
    held, released = _retained(db, wo.id)
    return {
        "id": b.id,
        "number": b.number,
        "wo_id": wo.id,
        "wo_code": wo.code,
        "site_id": wo.site_id,
        "subcontractor_name": wo.subcontractor.name,
        "bill_date": b.bill_date,
        "gross": b.gross,
        "retention": b.retention,
        "tds": b.tds,
        "material_recovery": b.material_recovery,
        "advance_recovery": b.advance_recovery,
        "gst_percent": b.gst_percent,
        "gst": b.gst,
        "net": b.net,
        "status": b.status,
        "vendor_bill_id": b.vendor_bill_id,
        "vendor_bill_number": vb.number if vb else None,
        "retention_held_on_wo": held - released,
        "productivity_status": b.productivity_status,
        "productivity": b.productivity,
        "productivity_override_note": b.productivity_override_note,
        "remark": b.remark,
        "lines": [
            {
                "measurement_id": m.id,
                "on_date": m.on_date,
                "description": wl.description,
                "qty": ln.qty,
                "unit": wl.unit,
                "rate": ln.rate,
                "amount": ln.amount,
            }
            for ln, m, wl in lines
        ],
    }


def _wo(db, wo_id) -> WorkOrder:
    wo = db.get(WorkOrder, wo_id)
    if wo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    return wo


@router.get("/subcon-bills")
def list_subcon(db: DbSession, _: PayView, wo_id: int | None = None) -> list[dict]:
    q = select(SubconBill)
    if wo_id is not None:
        q = q.where(SubconBill.wo_id == wo_id)
    return [_subcon_out(db, b) for b in db.scalars(q.order_by(SubconBill.id.desc()))]


@router.get("/work-orders/{wo_id}/billable")
def wo_billable(wo_id: int, db: DbSession, _: PayView) -> dict:
    wo = _wo(db, wo_id)
    rows = unbilled(db, wo)
    held, released = _retained(db, wo.id)
    return {
        "wo_id": wo.id,
        "measurements": [
            {
                "id": m.id,
                "on_date": m.on_date,
                "description": wl.description,
                "qty": m.qty,
                "unit": wl.unit,
                "rate": wl.rate,
                "amount": svc.money(Decimal(m.qty) * Decimal(wl.rate)),
            }
            for m, wl in rows
        ],
        "material_to_recover": max(ZERO, material_issued(db, wo) - material_recovered(db, wo)),
        "retention_held": held - released,
    }


@router.post("/work-orders/{wo_id}/subcon-bills", status_code=status.HTTP_201_CREATED)
def create_subcon_bill(
    wo_id: int,
    body: SubconBillIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PayView,
) -> dict:
    """From verified measurements not billed before (a measurement is billed once): gross less
    retention, TDS, material recovery (EESPL material given to them, when the WO says material by
    EESPL) and advance recovery, plus GST when they are registered."""
    _edit(principal)
    wo = _wo(db, wo_id)
    rows = unbilled(db, wo)
    if body.measurement_ids is not None:
        want = set(body.measurement_ids)
        rows = [r for r in rows if r[0].id in want]
        if len(rows) != len(want):
            raise svc.conflict("A measurement is not verified, not on this WO, or already billed")
    if not rows:
        raise svc.unprocessable("No verified, unbilled measurements")
    on = body.bill_date or today()
    b = SubconBill(
        number=svc.next_number(db, "SB", on),
        wo_id=wo.id,
        bill_date=on,
        remark=body.remark,
        created_by=principal.user.id,
    )
    gross = ZERO
    db.add(b)
    db.flush()
    for m, wl in rows:
        amount = svc.money(Decimal(m.qty) * Decimal(wl.rate))
        gross += amount
        db.add(
            SubconBillLine(
                subcon_bill_id=b.id, measurement_id=m.id, qty=m.qty, rate=wl.rate, amount=amount
            )
        )
    b.gross = gross
    b.retention = svc.money(gross * Decimal(wo.retention_percent) / 100)
    b.tds = svc.money(gross * Decimal(wo.tds_percent) / 100)
    if wo.material_by == "eespl":
        left = max(ZERO, material_issued(db, wo) - material_recovered(db, wo, b.id))
        b.material_recovery = (
            min(body.material_recovery, left) if body.material_recovery is not None else left
        )
    b.advance_recovery = body.advance_recovery
    sub = wo.subcontractor
    b.gst_percent = (
        body.gst_percent if body.gst_percent is not None else (Decimal(18) if sub.gstin else ZERO)
    )
    if not sub.gstin:
        b.gst_percent = ZERO
    b.gst = svc.money(gross * Decimal(b.gst_percent) / 100)
    b.net = gross + b.gst - b.retention - b.tds - b.material_recovery - b.advance_recovery
    if b.net < 0:
        raise svc.unprocessable("Recoveries exceed the bill")
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    db.flush()
    sitecontrol.productivity_check(db, b)
    record(
        db,
        request,
        principal,
        "subcon_bill.create",
        "subcon_bill",
        b.id,
        after={"number": b.number, "gross": str(gross)},
    )
    db.commit()
    return _subcon_out(db, b)


@router.post("/subcon-bills/{sid}/approve")
def approve_subcon(
    sid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    """Approved: a vendor bill (kind subcontract) for the net is raised and paid like any bill."""
    _edit(principal)
    b = db.get(SubconBill, sid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if b.status != "draft":
        raise svc.conflict(f"{b.number} is {b.status}")
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    sitecontrol.productivity_gate(db, b)  # "productivity low" needs labourcheck.override
    wo = db.get(WorkOrder, b.wo_id)
    sub = wo.subcontractor
    section, _pct = svc.tds_for(db, sub)
    vb = VendorBill(
        number=svc.next_number(db, "VB", b.bill_date),
        kind="subcontract",
        vendor_id=sub.id,
        vendor=sub,
        bill_no=b.number,
        bill_date=b.bill_date,
        due_date=b.bill_date + timedelta(days=sub.payment_terms_days or 15),
        site_id=wo.site_id,
        interstate=is_interstate(sub, svc.our_gstin(db, None)),
        itc_eligible=bool(sub.gstin),
        tds_section=section,
        tds_percent=wo.tds_percent,
        status="approved",
        approved_by=principal.user.id,
        approved_at=svc.now(),
        remark=f"{wo.code}: retention {b.retention}, material recovery {b.material_recovery}, "
        f"advance recovery {b.advance_recovery}",
        created_by=principal.user.id,
    )
    vb.lines = [
        VendorBillLine(
            description=f"{wo.code} RA bill {b.number}",
            qty=1,
            rate=b.gross,
            amount=b.gross,
            gst_percent=b.gst_percent,
        )
    ]
    _bill_tax(db, vb)
    vb.tds_amount = b.tds
    vb.payable = b.net  # less retention and recoveries too
    db.add(vb)
    db.flush()
    b.status, b.vendor_bill_id = "approved", vb.id
    record(
        db,
        request,
        principal,
        "subcon_bill.approve",
        "subcon_bill",
        b.id,
        after={"vendor_bill": vb.number},
    )
    db.commit()
    return _subcon_out(db, b)


class ReleaseIn(BaseModel):
    amount: Decimal = Field(gt=0)
    on_date: date | None = None


@router.post("/work-orders/{wo_id}/retention-release", status_code=status.HTTP_201_CREATED)
def release_subcon_retention(
    wo_id: int,
    body: ReleaseIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PayView,
) -> dict:
    """Release retention held on a WO (at the end of the work): a payable bill for it."""
    _edit(principal)
    wo = _wo(db, wo_id)
    held, released = _retained(db, wo.id)
    if body.amount > held - released:
        raise svc.unprocessable(f"Only {held - released:f} is held on {wo.code}")
    on = body.on_date or today()
    sub = wo.subcontractor
    vb = VendorBill(
        number=svc.next_number(db, "VB", on),
        kind="retention",
        vendor_id=sub.id,
        vendor=sub,
        bill_no=f"{wo.code}-RET-{on:%Y%m%d}",
        bill_date=on,
        due_date=on,
        site_id=wo.site_id,
        status="approved",
        approved_by=principal.user.id,
        approved_at=svc.now(),
        taxable=ZERO,
        total=body.amount,
        payable=body.amount,
        itc_eligible=False,
        remark=f"Retention release on {wo.code}",
        created_by=principal.user.id,
    )
    db.add(vb)
    db.flush()
    db.add(
        SubconRetentionRelease(
            wo_id=wo.id,
            on_date=on,
            amount=body.amount,
            vendor_bill_id=vb.id,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "subcon.retention_release",
        "work_order",
        wo.id,
        after={"amount": str(body.amount)},
    )
    db.commit()
    held, released = _retained(db, wo.id)
    return {
        "wo_id": wo.id,
        "held": held,
        "released": released,
        "vendor_bill_id": vb.id,
        "vendor_bill_number": vb.number,
    }


@router.get("/vendors/{vendor_id}/unbilled-grns")
def unbilled_grns(vendor_id: int, db: DbSession, _: PayView) -> list[dict]:
    """Approved GRNs of the vendor not on a (non-cancelled) bill yet, with their lines."""
    billed = (
        select(VendorBillGrn.grn_id)
        .join(VendorBill, VendorBill.id == VendorBillGrn.vendor_bill_id)
        .where(VendorBill.status != "cancelled")
    )
    out = []
    for g in db.scalars(
        select(Grn)
        .where(Grn.vendor_id == vendor_id, Grn.status == "approved", Grn.id.not_in(billed))
        .order_by(Grn.received_at)
    ):
        out.append(
            {
                "id": g.id,
                "code": g.code,
                "received_at": g.received_at,
                "invoice_no": g.invoice_no,
                "lines": [
                    {
                        "id": ln.id,
                        "product_name": ln.product.name,
                        "unit": ln.unit,
                        "accepted_qty": ln.accepted_qty,
                        "rate": ln.rate,
                    }
                    for ln in g.lines
                    if Decimal(ln.accepted_qty) > 0
                ],
            }
        )
    return out
