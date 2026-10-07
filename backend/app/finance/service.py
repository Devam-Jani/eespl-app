"""Finance rules.

RA bill quantities: for a contract line from a BOQ line, the work done is the sum over the BOQ
line's area scopes of (scope qty x scope progress %); the suggested qty for this bill is that
less what earlier bills already billed (their certified qty, else the submitted qty). Billing
beyond the BOQ qty needs an extra-item line approved with billing.approve.

Invoice outstanding = total - receipts allocated - advance recovery - other deductions - credit
notes. The retention part of it is held until the client releases it (site-level releases, applied
to the oldest invoices first); the rest is due and is aged by invoice date.

Site profit: billed (taxable value of invoices less credit notes) against cost to date = the M4
budget actuals (material, labour, subcontract, equipment, freight, other; approved petty cash
expenses are in their head) + staff salary allocated by the days each person checked in at the
site (only with payroll.view).
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.execution import service as ex
from app.execution.models import SiteBudget, StaffAttendance
from app.finance.models import (
    ClientContract,
    FinanceSettings,
    Payment,
    PaymentAllocation,
    PayrollRun,
    Payslip,
    PettyCashEntry,
    RaBill,
    RaBillLine,
    Receipt,
    ReceiptAllocation,
    RetentionRelease,
    TaxInvoice,
    VendorBill,
)
from app.masters.models import CompanyGstin
from app.material import service as material
from app.sites.models import AreaScope, Site

ZERO = Decimal(0)
CENT = Decimal("0.01")


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, ROUND_HALF_UP)


def unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


def forbidden(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, msg)


def settings(db: Session) -> FinanceSettings:
    s = db.get(FinanceSettings, 1)
    if s is None:  # recreated with the seeded defaults
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Finance settings are missing")
    return s


# --- numbering -----------------------------------------------------------------------------------


def fy_short(on: date) -> str:
    """1 Apr 2026 - 31 Mar 2027 -> "26-27"."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def next_number(db: Session, prefix: str, on: date, kind: str | None = None) -> str:
    """PREFIX/26-27/0001, per financial year, never reused (one atomic statement)."""
    period = material.financial_year(on)
    value = db.execute(
        text(
            "INSERT INTO doc_sequences (kind, period, last_value) VALUES (:k, :p, 1) "
            "ON CONFLICT (kind, period) DO UPDATE SET last_value = doc_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"k": kind or prefix[:10], "p": period},
    ).scalar_one()
    return f"{prefix}/{fy_short(on)}/{value:04d}"


def invoice_number(db: Session, on: date) -> str:
    number = next_number(db, settings(db).invoice_prefix, on, "INV")
    if len(number) > 16:
        raise unprocessable("The invoice number would exceed 16 characters: shorten the prefix")
    return number


# --- access --------------------------------------------------------------------------------------


def site_ok(db: Session, scope: str | None, principal: Principal, site_id: int | None) -> bool:
    if scope == "all":
        return True
    if site_id is None:
        return False
    return material.covers_site(db, scope, principal, site_id)


def sees_cost(principal: Principal) -> bool:
    return principal.permissions.get("tender.margin") is not None


# --- contracts and RA bills ----------------------------------------------------------------------


def done_qty(db: Session, boq_line_id: int | None) -> Decimal:
    """Work done on a BOQ line: its area scopes' qty x progress %."""
    if not boq_line_id:
        return ZERO
    total = ZERO
    for sc in db.scalars(select(AreaScope).where(AreaScope.boq_line_id == boq_line_id)):
        total += Decimal(sc.qty) * Decimal(sc.progress_percent) / 100
    return total.quantize(Decimal("0.001"), ROUND_HALF_UP)


def billed_before(db: Session, contract_line_id: int, before_bill: RaBill | None = None) -> Decimal:
    """Qty already billed on the line by earlier bills that are not drafts or cancelled."""
    q = (
        select(RaBillLine, RaBill)
        .join(RaBill, RaBill.id == RaBillLine.ra_bill_id)
        .where(
            RaBillLine.contract_line_id == contract_line_id,
            RaBill.status.in_(("submitted", "certified", "invoiced")),
        )
    )
    if before_bill is not None:
        q = q.where(RaBill.seq < before_bill.seq)
    total = ZERO
    for ln, _bill in db.execute(q):
        total += Decimal(ln.certified_qty if ln.certified_qty is not None else ln.qty)
    return total


def advance_left(
    db: Session, contract: ClientContract, exclude_bill_id: int | None = None
) -> Decimal:
    used = db.scalar(
        select(func.coalesce(func.sum(RaBill.advance_recovery), 0)).where(
            RaBill.contract_id == contract.id,
            RaBill.status != "cancelled",
            RaBill.id != (exclude_bill_id or 0),
        )
    )
    return max(ZERO, Decimal(contract.advance_amount) - Decimal(used))


def ra_totals(db: Session, bill: RaBill, contract: ClientContract) -> None:
    """Amounts, gross, retention, advance recovery and net (on the certified figures once
    certified)."""
    gross = ZERO
    cert = ZERO
    for ln in bill.lines:
        ln.amount = money(Decimal(ln.qty) * Decimal(ln.rate))
        gross += ln.amount
        if ln.certified_qty is not None:
            ln.certified_amount = money(Decimal(ln.certified_qty) * Decimal(ln.rate))
            cert += ln.certified_amount
    bill.gross = gross
    certified = bill.status in ("certified", "invoiced")
    bill.certified_gross = cert if certified else None
    base = cert if certified else gross
    bill.retention = money(base * Decimal(contract.retention_percent) / 100)
    bill.advance_recovery = min(
        money(base * Decimal(contract.advance_recovery_percent) / 100),
        advance_left(db, contract, bill.id),
    )
    bill.net = base - bill.retention - bill.advance_recovery - Decimal(bill.other_deduction)


# --- invoices, receipts, ageing ------------------------------------------------------------------


def our_gstin(db: Session, gstin_id: int | None) -> CompanyGstin | None:
    if gstin_id:
        return db.get(CompanyGstin, gstin_id)
    return db.scalar(
        select(CompanyGstin).order_by(CompanyGstin.is_default.desc(), CompanyGstin.id).limit(1)
    )


def interstate(
    ours: CompanyGstin | None, place_of_supply: str | None, client_gstin: str | None
) -> bool:
    """IGST when the place of supply (client GSTIN state code, else the state named) is not our
    state; CGST + SGST otherwise."""
    if ours is None:
        return False
    if client_gstin and ours.gstin:
        return client_gstin[:2] != ours.gstin[:2]
    if place_of_supply and ours.state:
        return place_of_supply.strip().casefold() != ours.state.strip().casefold()
    return False


def invoice_tax(inv: TaxInvoice) -> None:
    taxable = ZERO
    tax = ZERO
    for ln in inv.lines:
        taxable += Decimal(ln.amount)
        tax += Decimal(ln.amount) * Decimal(ln.gst_percent) / 100
    inv.taxable = money(taxable)
    tax = money(tax)
    if inv.interstate:
        inv.igst, inv.cgst, inv.sgst = tax, ZERO, ZERO
    else:
        inv.cgst = money(tax / 2)
        inv.sgst = tax - inv.cgst
        inv.igst = ZERO
    before = inv.taxable + tax
    inv.total = before.quantize(Decimal(1), ROUND_HALF_UP)
    inv.round_off = inv.total - before


def settled(db: Session, invoice_id: int) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(ReceiptAllocation.amount), 0)).where(
                ReceiptAllocation.invoice_id == invoice_id
            )
        )
    )


def credited(db: Session, invoice_id: int) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(TaxInvoice.total), 0)).where(
                TaxInvoice.against_id == invoice_id, TaxInvoice.status == "issued"
            )
        )
    )


def outstanding(db: Session, inv: TaxInvoice) -> Decimal:
    if inv.kind != "invoice" or inv.status != "issued":
        return ZERO
    return max(
        ZERO,
        Decimal(inv.total)
        - settled(db, inv.id)
        - Decimal(inv.advance_recovery)
        - Decimal(inv.other_deduction)
        - credited(db, inv.id),
    )


def retention_held(db: Session, site_id: int) -> tuple[Decimal, Decimal, Decimal]:
    """(retained on invoices, released by the client, still held)."""
    retained = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(TaxInvoice.retention), 0)).where(
                TaxInvoice.site_id == site_id,
                TaxInvoice.kind == "invoice",
                TaxInvoice.status == "issued",
            )
        )
    )
    released = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(RetentionRelease.amount), 0)).where(
                RetentionRelease.site_id == site_id
            )
        )
    )
    return retained, released, max(ZERO, retained - released)


def invoice_positions(db: Session, invoices: list[TaxInvoice], today: date) -> list[dict]:
    """Per invoice: outstanding, the retention still held in it, the due part and its age."""
    by_site: dict[int | None, Decimal] = {}
    out = []
    for inv in sorted(invoices, key=lambda i: (i.invoice_date, i.id)):
        if inv.site_id not in by_site:
            by_site[inv.site_id] = retention_held(db, inv.site_id)[1] if inv.site_id else ZERO
        released_here = min(Decimal(inv.retention), by_site[inv.site_id])
        by_site[inv.site_id] -= released_here
        held = Decimal(inv.retention) - released_here
        os_ = outstanding(db, inv)
        due = max(ZERO, os_ - held)
        out.append(
            {
                "invoice": inv,
                "outstanding": os_,
                "retention_held": min(held, os_),
                "due": due,
                "age": (today - inv.invoice_date).days,
            }
        )
    return out


def bucket(age: int) -> str:
    return "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"


# --- vendor side ---------------------------------------------------------------------------------


def tds_for(db: Session, vendor) -> tuple[str | None, Decimal]:
    """(section, %) for a vendor from the settings: individual / HUF by the PAN's 4th letter."""
    rules = settings(db).tds_rules or {}
    rule = rules.get(vendor.type) or rules.get("other")
    if not rule:
        return None, ZERO
    individual = bool(vendor.pan and len(vendor.pan) >= 4 and vendor.pan[3].upper() in "PH")
    return rule.get("section"), Decimal(str(rule["individual" if individual else "other"]))


def bill_paid(db: Session, bill_id: int) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(PaymentAllocation.vendor_bill_id == bill_id, Payment.status == "paid")
        )
    )


def bill_outstanding(db: Session, bill: VendorBill) -> Decimal:
    if bill.status in ("draft", "cancelled"):
        return ZERO
    return max(ZERO, Decimal(bill.payable) - bill_paid(db, bill.id))


def refresh_bill(db: Session, bill: VendorBill) -> None:
    if bill.status in ("draft", "cancelled"):
        return
    paid = bill_paid(db, bill.id)
    bill.status = (
        "paid" if paid >= Decimal(bill.payable) else "partly_paid" if paid > 0 else "approved"
    )


# --- petty cash ----------------------------------------------------------------------------------


def petty_balance(db: Session, account_id: int) -> dict:
    rows = dict(
        db.execute(
            select(PettyCashEntry.kind, func.sum(PettyCashEntry.amount))
            .where(PettyCashEntry.account_id == account_id, PettyCashEntry.status == "approved")
            .group_by(PettyCashEntry.kind)
        ).all()
    )
    pending = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(PettyCashEntry.amount), 0)).where(
                PettyCashEntry.account_id == account_id,
                PettyCashEntry.kind == "expense",
                PettyCashEntry.status == "submitted",
            )
        )
    )
    adv, spent, settled_ = (Decimal(rows.get(k, 0)) for k in ("advance", "expense", "settlement"))
    return {
        "advances": adv,
        "expenses": spent,
        "settlements": settled_,
        "pending": pending,
        "balance": adv - spent - settled_,
    }


# --- payroll -------------------------------------------------------------------------------------


def pt_for(db: Session, gross: Decimal) -> Decimal:
    for slab in settings(db).pt_slabs or []:
        lo = Decimal(str(slab["from"]))
        hi = Decimal(str(slab["to"])) if slab.get("to") is not None else None
        if gross >= lo and (hi is None or gross <= hi):
            return Decimal(str(slab["amount"]))
    return ZERO


def compute_payslip(db: Session, p: Payslip, s, advances: Decimal) -> None:
    """Pro-rata on paid days; PF on basic up to the wage cap; ESI below the threshold; PT slab."""
    st = settings(db)
    p.paid_days = Decimal(p.days_in_month) - Decimal(p.lop_days)
    f = Decimal(p.paid_days) / Decimal(p.days_in_month)
    p.basic, p.hra, p.other_allowance = (
        money(Decimal(x) * f) for x in (s.basic, s.hra, s.other_allowance)
    )
    p.gross = p.basic + p.hra + p.other_allowance
    if s.pf:
        wage = min(p.basic, Decimal(st.pf_wage_cap))
        p.pf_employee = p.pf_employer = money(wage * Decimal(st.pf_percent) / 100)
    else:
        p.pf_employee = p.pf_employer = ZERO
    if s.esi and p.gross <= Decimal(st.esi_threshold):
        p.esi_employee = (p.gross * Decimal(st.esi_employee_percent) / 100).quantize(
            Decimal(1), "ROUND_CEILING"
        )
        p.esi_employer = (p.gross * Decimal(st.esi_employer_percent) / 100).quantize(
            Decimal(1), "ROUND_CEILING"
        )
    else:
        p.esi_employee = p.esi_employer = ZERO
    p.pt = pt_for(db, p.gross)
    before = p.gross - p.pf_employee - p.esi_employee - p.pt
    p.advance_recovery = min(advances, max(ZERO, before))
    p.net = before - p.advance_recovery


def staff_days(db: Session, user_id, month: str) -> tuple[int, dict[str, int]]:
    start, end = ex.month_range(month)
    rows = db.execute(
        select(StaffAttendance.site_id, func.count(func.distinct(StaffAttendance.on_date)))
        .where(
            StaffAttendance.user_id == user_id,
            StaffAttendance.on_date >= start,
            StaffAttendance.on_date <= end,
        )
        .group_by(StaffAttendance.site_id)
    ).all()
    days = db.scalar(
        select(func.count(func.distinct(StaffAttendance.on_date))).where(
            StaffAttendance.user_id == user_id,
            StaffAttendance.on_date >= start,
            StaffAttendance.on_date <= end,
        )
    )
    return days or 0, {str(s): n for s, n in rows}


def month_days(month: str) -> int:
    y, m = (int(x) for x in month.split("-"))
    return calendar.monthrange(y, m)[1]


def staff_cost(db: Session, site_id: int) -> Decimal:
    """Salary cost (gross + employer PF / ESI) allocated by each person's check-in days."""
    total = ZERO
    for p in db.scalars(select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.run_id)):
        days = sum(int(v) for v in (p.site_days or {}).values())
        here = int((p.site_days or {}).get(str(site_id), 0))
        if days and here:
            total += (
                (Decimal(p.gross) + Decimal(p.pf_employer) + Decimal(p.esi_employer)) * here / days
            )
    return money(total)


# --- site profit ---------------------------------------------------------------------------------


def expenses_by_head(db: Session, site_id: int) -> dict[str, Decimal]:
    from app.finance.models import ExpenseCategory

    out: dict[str, Decimal] = defaultdict(Decimal)
    for amount, head in db.execute(
        select(PettyCashEntry.amount, ExpenseCategory.budget_head)
        .join(ExpenseCategory, ExpenseCategory.id == PettyCashEntry.category_id, isouter=True)
        .where(
            PettyCashEntry.site_id == site_id,
            PettyCashEntry.kind == "expense",
            PettyCashEntry.status == "approved",
        )
    ):
        out[head or "other"] += Decimal(amount)
    return out


def site_profit(db: Session, site: Site, with_salary: bool) -> dict:
    invoices = list(
        db.scalars(
            select(TaxInvoice).where(TaxInvoice.site_id == site.id, TaxInvoice.status == "issued")
        )
    )
    billed = sum((Decimal(i.taxable) for i in invoices if i.kind == "invoice"), ZERO) - sum(
        (Decimal(i.taxable) for i in invoices if i.kind == "credit_note"), ZERO
    )
    certified = sum(
        (
            Decimal(b.certified_gross or 0)
            for b in db.scalars(
                select(RaBill).where(
                    RaBill.site_id == site.id, RaBill.status.in_(("certified", "invoiced"))
                )
            )
        ),
        ZERO,
    )
    received = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
            .join(TaxInvoice, TaxInvoice.id == ReceiptAllocation.invoice_id)
            .where(TaxInvoice.site_id == site.id)
        )
    )
    advance_received = Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Receipt.amount), 0)).where(
                Receipt.site_id == site.id, Receipt.is_advance
            )
        )
    )
    actual = ex.actuals(db, site.id)  # approved expenses are in their heads
    expenses = expenses_by_head(db, site.id)
    heads = {h: actual[h] - expenses.get(h, ZERO) for h in actual}
    heads["petty_cash"] = sum(expenses.values(), ZERO)
    salary = staff_cost(db, site.id) if with_salary else None
    if salary is not None:
        heads["staff_salary"] = salary
    cost = sum(heads.values(), ZERO)
    profit = billed - cost
    contract = db.scalar(select(ClientContract).where(ClientContract.site_id == site.id))
    contract_value = Decimal(contract.contract_value) if contract else None
    budget = {
        b.head: Decimal(b.amount)
        for b in db.scalars(select(SiteBudget).where(SiteBudget.site_id == site.id))
    }
    for head, amount in ex.tender_budget(db, site).items():
        budget.setdefault(head, amount)
    budget_total = sum(budget.values(), ZERO) if budget else None
    projected = (
        contract_value - budget_total
        if contract_value is not None and budget_total is not None
        else None
    )
    return {
        "site_id": site.id,
        "site_code": site.code,
        "site_name": site.name,
        "billed": money(billed),
        "certified": money(certified),
        "received": money(received),
        "advance_received": money(advance_received),
        "retention_held": retention_held(db, site.id)[2],
        "cost": {k: money(v) for k, v in heads.items()},
        "cost_total": money(cost),
        "salary_hidden": not with_salary,
        "gross_profit": money(profit),
        "margin_percent": (profit / billed * 100).quantize(Decimal("0.1")) if billed else None,
        "over_cost": cost > billed,
        "contract_value": contract_value,
        "budget_at_completion": budget_total,
        "projected_profit": projected,
        "projected_margin_percent": (projected / contract_value * 100).quantize(Decimal("0.1"))
        if projected is not None and contract_value
        else None,
    }


def due_by(days: int) -> date:
    return ex.today() + timedelta(days=days)


def now() -> datetime:
    return datetime.now(ex.IST)
