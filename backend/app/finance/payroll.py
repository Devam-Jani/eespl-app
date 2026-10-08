"""Payroll: salary structures, staff advances, monthly runs with payslips (PF, ESI, PT, LOP),
the month lock; labour wage payments from the muster roll, with labour advances.

Salary figures are only ever returned with payroll.view; payroll.edit changes them. Labour wages
(from the muster roll) are payables: payables.view / payables.edit.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import service as ex
from app.execution.common import pdf_response, record
from app.execution.models import Labour
from app.finance import pdf
from app.finance import service as svc
from app.finance.models import (
    LabourAdvance,
    LabourWagePayment,
    PayrollRun,
    Payslip,
    SalaryStructure,
    StaffAdvance,
)
from app.models import User
from app.sites.models import Site

router = APIRouter(prefix="/api/finance", tags=["finance"])
PayrollView = Annotated[str, Depends(require_permission("payroll.view"))]
PayView = Annotated[str, Depends(require_permission("payables.view"))]
Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]
ZERO = Decimal(0)


def _edit(principal):
    if principal.permissions.get("payroll.edit") is None:
        raise svc.forbidden("Missing permission: payroll.edit")


def _uid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as exc:
        raise svc.unprocessable("Not a user id") from exc


# --- salary structures and advances --------------------------------------------------------------


class StructureIn(BaseModel):
    user_id: str
    effective_from: date
    basic: Decimal = Field(gt=0)
    hra: Decimal = Field(default=Decimal(0), ge=0)
    other_allowance: Decimal = Field(default=Decimal(0), ge=0)
    pf: bool = True
    esi: bool = True
    pt_state: str = "Gujarat"


def _structure_out(db, s: SalaryStructure) -> dict:
    return {
        "id": s.id,
        "user_id": str(s.user_id),
        "user_name": db.get(User, s.user_id).full_name,
        "effective_from": s.effective_from,
        "basic": s.basic,
        "hra": s.hra,
        "other_allowance": s.other_allowance,
        "pf": s.pf,
        "esi": s.esi,
        "pt_state": s.pt_state,
        "monthly_ctc": s.monthly_ctc,
    }


def structure_on(db, user_id, on: date) -> SalaryStructure | None:
    return db.scalar(
        select(SalaryStructure)
        .where(SalaryStructure.user_id == user_id, SalaryStructure.effective_from <= on)
        .order_by(SalaryStructure.effective_from.desc())
        .limit(1)
    )


@router.get("/salary-structures")
def list_structures(db: DbSession, _: PayrollView) -> list[dict]:
    return [
        _structure_out(db, s)
        for s in db.scalars(
            select(SalaryStructure).order_by(
                SalaryStructure.user_id, SalaryStructure.effective_from.desc()
            )
        )
    ]


@router.post("/salary-structures", status_code=status.HTTP_201_CREATED)
def set_structure(
    body: StructureIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayrollView
) -> dict:
    _edit(principal)
    user = db.get(User, _uid(body.user_id))
    if user is None:
        raise svc.unprocessable("User not found")
    s = db.scalar(
        select(SalaryStructure).where(
            SalaryStructure.user_id == user.id,
            SalaryStructure.effective_from == body.effective_from,
        )
    )
    if s is None:
        s = SalaryStructure(
            user_id=user.id, effective_from=body.effective_from, created_by=principal.user.id
        )
        db.add(s)
    for k in ("basic", "hra", "other_allowance", "pf", "esi", "pt_state"):
        setattr(s, k, getattr(body, k))
    st = svc.settings(db)
    gross = body.basic + body.hra + body.other_allowance
    pf = (
        svc.money(min(body.basic, Decimal(st.pf_wage_cap)) * Decimal(st.pf_percent) / 100)
        if body.pf
        else ZERO
    )
    esi = (
        svc.money(gross * Decimal(st.esi_employer_percent) / 100)
        if body.esi and gross <= Decimal(st.esi_threshold)
        else ZERO
    )
    s.monthly_ctc = gross + pf + esi
    db.flush()
    record(
        db,
        request,
        principal,
        "salary.set",
        "user",
        str(user.id),
        after={"effective_from": str(body.effective_from)},
    )
    db.commit()
    return _structure_out(db, s)


class StaffAdvanceIn(BaseModel):
    user_id: str
    amount: Decimal = Field(gt=0)
    on_date: date | None = None
    remark: str | None = None


@router.post("/staff-advances", status_code=status.HTTP_201_CREATED)
def staff_advance(
    body: StaffAdvanceIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PayrollView,
) -> dict:
    """A salary advance, recovered in the next payroll run."""
    _edit(principal)
    user = db.get(User, _uid(body.user_id))
    if user is None:
        raise svc.unprocessable("User not found")
    a = StaffAdvance(
        user_id=user.id,
        amount=body.amount,
        on_date=body.on_date or ex.today(),
        remark=body.remark,
        created_by=principal.user.id,
    )
    db.add(a)
    db.flush()
    record(
        db,
        request,
        principal,
        "salary.advance",
        "user",
        str(user.id),
        after={"amount": str(body.amount)},
    )
    db.commit()
    return {"id": a.id, "user_id": str(a.user_id), "amount": a.amount, "on_date": a.on_date}


# --- payroll runs --------------------------------------------------------------------------------


class Adjust(BaseModel):
    user_id: str
    leave_days: Decimal = Field(default=Decimal(0), ge=0, le=31)
    lop_days: Decimal = Field(default=Decimal(0), ge=0, le=31)


class RunIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    adjustments: list[Adjust] = []


def _slip_out(db, p: Payslip) -> dict:
    sites = dict(db.execute(select(Site.id, Site.code)).all())
    return {
        "id": p.id,
        "user_id": str(p.user_id),
        "user_name": db.get(User, p.user_id).full_name,
        **{
            k: getattr(p, k)
            for k in (
                "days_in_month",
                "worked_days",
                "leave_days",
                "lop_days",
                "paid_days",
                "basic",
                "hra",
                "other_allowance",
                "gross",
                "pf_employee",
                "pf_employer",
                "esi_employee",
                "esi_employer",
                "pt",
                "advance_recovery",
                "round_off",
                "net",
            )
        },
        "site_days": {sites.get(int(k), k): v for k, v in (p.site_days or {}).items()},
    }


def _run_out(db, r: PayrollRun) -> dict:
    slips = [_slip_out(db, p) for p in r.payslips]
    return {
        "id": r.id,
        "month": r.month,
        "status": r.status,
        "locked_at": r.locked_at,
        "paid_mode": r.paid_mode,
        "paid_ref": r.paid_ref,
        "payslips": slips,
        "totals": {
            k: sum((Decimal(s[k]) for s in slips), ZERO)
            for k in (
                "gross",
                "pf_employee",
                "pf_employer",
                "esi_employee",
                "esi_employer",
                "pt",
                "advance_recovery",
                "net",
            )
        },
    }


@router.get("/payroll")
def list_runs(db: DbSession, _: PayrollView) -> list[dict]:
    return [
        _run_out(db, r) for r in db.scalars(select(PayrollRun).order_by(PayrollRun.month.desc()))
    ]


@router.post("/payroll", status_code=status.HTTP_201_CREATED)
def run_payroll(
    body: RunIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayrollView
) -> dict:
    """(Re)compute a month for everyone with a salary structure in force. Worked days come from
    staff check-ins; leave and loss of pay are entered by hand. A locked month is not changed."""
    _edit(principal)
    run = db.scalar(select(PayrollRun).where(PayrollRun.month == body.month))
    if run is not None and run.status == "locked":
        raise svc.conflict(f"{body.month} is locked (paid)")
    if run is None:
        run = PayrollRun(month=body.month, created_by=principal.user.id)
        db.add(run)
        db.flush()
    adj = {_uid(a.user_id): a for a in body.adjustments}
    start, end = ex.month_range(body.month)
    dim = svc.month_days(body.month)
    users = {
        s.user_id
        for s in db.scalars(select(SalaryStructure).where(SalaryStructure.effective_from <= end))
    }
    existing = {p.user_id: p for p in run.payslips}
    for p in list(run.payslips):  # free advances recovered by an earlier compute of this run
        for a in db.scalars(
            select(StaffAdvance).where(StaffAdvance.recovered_in_payslip_id == p.id)
        ):
            a.recovered_in_payslip_id = None
    for uid in sorted(users, key=str):
        s = structure_on(db, uid, end)
        p = existing.get(uid) or Payslip(user_id=uid, created_by=principal.user.id)
        if p not in run.payslips:
            run.payslips.append(p)
        a = adj.get(uid)
        p.structure_id, p.days_in_month = s.id, dim
        p.leave_days = a.leave_days if a else (p.leave_days or ZERO)
        p.lop_days = a.lop_days if a else (p.lop_days or ZERO)
        if Decimal(p.lop_days) > dim:
            raise svc.unprocessable("LOP is more than the days in the month")
        p.paid_days = Decimal(dim) - Decimal(p.lop_days)  # set before any query flushes the row
        p.worked_days, p.site_days = svc.staff_days(db, uid, body.month)
        pending = list(
            db.scalars(
                select(StaffAdvance).where(
                    StaffAdvance.user_id == uid,
                    StaffAdvance.on_date <= end,
                    StaffAdvance.recovered_in_payslip_id.is_(None),
                )
            )
        )
        svc.compute_payslip(db, p, s, sum((Decimal(x.amount) for x in pending), ZERO))
        db.flush()
        left = Decimal(p.advance_recovery)
        for x in pending:  # whole advances only; the rest waits for next month
            if Decimal(x.amount) <= left:
                x.recovered_in_payslip_id, left = p.id, left - Decimal(x.amount)
        p.advance_recovery = Decimal(p.advance_recovery) - left
        svc.round_net(p)
    record(
        db,
        request,
        principal,
        "payroll.run",
        "payroll_run",
        run.id,
        after={"month": body.month, "people": len(users)},
    )
    db.commit()
    db.refresh(run)
    return _run_out(db, run)


class LockIn(BaseModel):
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "neft"
    ref_no: str | None = None


@router.post("/payroll/{rid}/lock")
def lock_run(
    rid: int,
    body: LockIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PayrollView,
) -> dict:
    """Paid: the month is locked and cannot be recomputed."""
    _edit(principal)
    run = db.get(PayrollRun, rid)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payroll run not found")
    if run.status == "locked":
        raise svc.conflict(f"{run.month} is already locked")
    run.status, run.locked_at, run.locked_by = "locked", svc.now(), principal.user.id
    run.paid_mode, run.paid_ref = body.mode, body.ref_no
    record(
        db, request, principal, "payroll.lock", "payroll_run", run.id, after={"month": run.month}
    )
    db.commit()
    return _run_out(db, run)


@router.get("/payslips/{pid}/pdf")
def payslip_pdf(pid: int, db: DbSession, _: PayrollView):
    p = db.get(Payslip, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payslip not found")
    run = db.get(PayrollRun, p.run_id)
    user = db.get(User, p.user_id)
    return pdf_response(
        pdf.payslip(db, run, p, user), f"Payslip-{run.month}-{user.full_name.replace(' ', '-')}"
    )


# --- labour wages --------------------------------------------------------------------------------


class LabourAdvanceIn(BaseModel):
    labour_id: int
    site_id: int
    amount: Decimal = Field(gt=0)
    on_date: date | None = None


class WagesIn(BaseModel):
    site_id: int
    period_from: date
    period_to: date


class PaidIn(BaseModel):
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "cash"
    ref_no: str | None = None
    paid_on: date | None = None


def _wage_out(db, w: LabourWagePayment) -> dict:
    lab = db.get(Labour, w.labour_id)
    return {
        "id": w.id,
        "labour_id": lab.id,
        "name": lab.name,
        "trade": lab.trade,
        "site_id": w.site_id,
        "period_from": w.period_from,
        "period_to": w.period_to,
        "days": w.days,
        "ot_hours": w.ot_hours,
        "wage_due": w.wage_due,
        "advances_recovered": w.advances_recovered,
        "net": w.net,
        "status": w.status,
        "paid_on": w.paid_on,
        "mode": w.mode,
        "ref_no": w.ref_no,
    }


def _pay_edit(principal):
    if principal.permissions.get("payables.edit") is None:
        raise svc.forbidden("Missing permission: payables.edit")


@router.post("/labour-advances", status_code=status.HTTP_201_CREATED)
def labour_advance(
    body: LabourAdvanceIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    _pay_edit(principal)
    lab = db.get(Labour, body.labour_id)
    if lab is None or db.get(Site, body.site_id) is None:
        raise svc.unprocessable("Worker or site not found")
    a = LabourAdvance(
        labour_id=lab.id,
        site_id=body.site_id,
        amount=body.amount,
        on_date=body.on_date or ex.today(),
        created_by=principal.user.id,
    )
    db.add(a)
    db.flush()
    record(
        db,
        request,
        principal,
        "labour.advance",
        "labour",
        lab.id,
        after={"amount": str(body.amount)},
    )
    db.commit()
    return {"id": a.id, "labour_id": lab.id, "amount": a.amount, "on_date": a.on_date}


@router.get("/labour-wages")
def list_wages(db: DbSession, _: PayView, site_id: int | None = None) -> list[dict]:
    q = select(LabourWagePayment)
    if site_id is not None:
        q = q.where(LabourWagePayment.site_id == site_id)
    return [
        _wage_out(db, w)
        for w in db.scalars(q.order_by(LabourWagePayment.period_from.desc(), LabourWagePayment.id))
    ]


@router.post("/labour-wages", status_code=status.HTTP_201_CREATED)
def make_wages(
    body: WagesIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> list[dict]:
    """Wage payments for a site and period from the muster roll (own labour; subcontractor
    workers are paid by their subcontractor), less the advances given to each worker."""
    _pay_edit(principal)
    if db.get(Site, body.site_id) is None:
        raise svc.unprocessable("Site not found")
    if body.period_to < body.period_from:
        raise svc.unprocessable("The period ends before it starts")
    out = []
    for r in ex.muster(db, body.period_from, body.period_to, body.site_id):
        if r["type"] != "own" or not r["wage_due"]:
            continue
        if db.scalar(
            select(LabourWagePayment.id).where(
                LabourWagePayment.labour_id == r["labour_id"],
                LabourWagePayment.site_id == body.site_id,
                LabourWagePayment.period_from <= body.period_to,
                LabourWagePayment.period_to >= body.period_from,
            )
        ):
            raise svc.conflict(f"{r['name']}'s wages for part of this period are already made")
        w = LabourWagePayment(
            labour_id=r["labour_id"],
            site_id=body.site_id,
            period_from=body.period_from,
            period_to=body.period_to,
            days=r["days"],
            ot_hours=r["ot_hours"],
            wage_due=r["wage_due"],
            net=r["wage_due"],
            created_by=principal.user.id,
        )
        db.add(w)
        db.flush()
        left = Decimal(r["wage_due"])
        for a in db.scalars(
            select(LabourAdvance)
            .where(
                LabourAdvance.labour_id == r["labour_id"],
                LabourAdvance.site_id == body.site_id,
                LabourAdvance.recovered_in_id.is_(None),
                LabourAdvance.on_date <= body.period_to,
            )
            .order_by(LabourAdvance.on_date)
        ):
            if Decimal(a.amount) <= left:
                a.recovered_in_id, left = w.id, left - Decimal(a.amount)
                w.advances_recovered = Decimal(w.advances_recovered) + Decimal(a.amount)
        w.net = Decimal(w.wage_due) - Decimal(w.advances_recovered)
        out.append(w)
    record(
        db,
        request,
        principal,
        "labour.wages",
        "site",
        body.site_id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return [_wage_out(db, w) for w in out]


@router.post("/labour-wages/{wid}/paid")
def wages_paid(
    wid: int, body: PaidIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayView
) -> dict:
    _pay_edit(principal)
    w = db.get(LabourWagePayment, wid)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wage payment not found")
    if w.status == "paid":
        raise svc.conflict("Already paid")
    w.status, w.paid_on, w.mode, w.ref_no = (
        "paid",
        body.paid_on or ex.today(),
        body.mode,
        body.ref_no,
    )
    record(db, request, principal, "labour.wages.paid", "site", w.site_id, after={"id": w.id})
    db.commit()
    return _wage_out(db, w)
