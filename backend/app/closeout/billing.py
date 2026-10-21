# ruff: noqa: E501  (messages read better unwrapped)
"""The client's billing cycle, each bill's tracking steps, the payment due date and the follow-up.

The cycle per client (or per site where it differs): the days bills must reach the site, the
head office's processing days and the payment days. A bill goes through prepared, submitted at
site, signed by the client's project manager, sent to head office, with their accounts, paid;
each step with its date, who and the signed copy (our proof when a bill goes missing).

Due date = the invoice date, or the certification date when the work order says so, plus the term
days. On the due date accounts are told; after 5 days (setting) the salesperson; after 30 the
director, the salesperson and the site engineer. The client's accounts and project manager see
the bill overdue in the portal with an in-app notice: never an email to a client."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.common import IST, unprocessable
from app.closeout.models import (
    BILL_STEP_LABEL,
    BILL_STEPS,
    BillTrackingStep,
    ClientBillingCycle,
    ClientWorkOrder,
    CloseoutSettings,
    PaymentFollowUp,
)
from app.finance.models import RaBill, TaxInvoice
from app.sites.models import Site


def settings(db: Session) -> CloseoutSettings:
    s = db.get(CloseoutSettings, 1)
    if s is None:
        s = CloseoutSettings(id=1)
        db.add(s)
        db.flush()
    return s


def cycle_for(db: Session, site: Site) -> ClientBillingCycle | None:
    own = db.scalar(select(ClientBillingCycle).where(ClientBillingCycle.site_id == site.id))
    if own is not None or site.client_id is None:
        return own
    return db.scalar(
        select(ClientBillingCycle).where(
            ClientBillingCycle.client_id == site.client_id, ClientBillingCycle.site_id.is_(None)
        )
    )


def work_order_of(db: Session, site_id: int) -> ClientWorkOrder | None:
    return db.scalars(
        select(ClientWorkOrder)
        .where(ClientWorkOrder.site_id == site_id, ClientWorkOrder.status == "accepted")
        .order_by(ClientWorkOrder.id.desc())
    ).first()


def steps_of(db: Session, ra: RaBill) -> list[BillTrackingStep]:
    return list(
        db.scalars(
            select(BillTrackingStep)
            .where(BillTrackingStep.ra_bill_id == ra.id)
            .order_by(BillTrackingStep.on_date, BillTrackingStep.id)
        )
    )


def add_step(
    db: Session,
    ra: RaBill,
    step: str,
    on: date,
    user_id,
    by_name: str | None,
    note: str | None,
    file_path: str | None,
    file_name: str | None,
) -> BillTrackingStep:
    if step not in BILL_STEPS:
        raise unprocessable(f"Step is one of {', '.join(BILL_STEPS)}")
    have = steps_of(db, ra)
    if have and BILL_STEPS.index(step) < BILL_STEPS.index(have[-1].step):
        raise unprocessable(f"The bill is already at '{BILL_STEP_LABEL[have[-1].step]}'")
    if have and on < have[-1].on_date:
        raise unprocessable("A step cannot be dated before the step before it")
    if step == "signed_pm" and not file_path:
        raise unprocessable("Upload the signed copy: it is our proof when a bill goes missing")
    s = BillTrackingStep(
        ra_bill_id=ra.id,
        step=step,
        on_date=on,
        by_user=user_id,
        by_name=by_name,
        note=note,
        file_path=file_path,
        file_name=file_name,
    )
    db.add(s)
    db.flush()
    return s


def invoice_of(db: Session, ra: RaBill) -> TaxInvoice | None:
    return db.scalars(
        select(TaxInvoice)
        .where(
            TaxInvoice.ra_bill_id == ra.id,
            TaxInvoice.kind == "invoice",
            TaxInvoice.status == "issued",
        )
        .order_by(TaxInvoice.id)
    ).first()


def due_of(db: Session, ra: RaBill) -> tuple[date | None, str]:
    """The due date and how it was worked: the work order's term (after the invoice or the
    certification), else the client's cycle, else the invoice's own due date."""
    inv = invoice_of(db, ra)
    site = db.get(Site, ra.site_id)
    wo = work_order_of(db, ra.site_id)
    cyc = cycle_for(db, site) if site else None
    basis = (wo.payment_basis if wo else None) or "invoice"
    days = wo.payment_days if wo and wo.payment_days is not None else None
    source = f"work order {wo.client_ref or wo.code}" if wo and days is not None else None
    if days is None and cyc is not None:
        days, source = cyc.payment_days, "the client's billing cycle"
    if basis == "certification":
        start = (
            ra.certified_at.astimezone(IST).date() if ra.certified_at else None
        ) or ra.client_cert_on
        what = "certification"
    else:
        start = inv.invoice_date if inv else None
        what = "invoice"
    if start is None:
        return (
            inv.due_date if inv else None
        ), "not invoiced yet" if inv is None else "the invoice's due date"
    if days is None:
        return (inv.due_date if inv else None), "the invoice's due date"
    return start + timedelta(days=days), f"{days} days after the {what} ({source})"


def outstanding(db: Session, ra: RaBill) -> Decimal:
    from app.finance import service as fsvc  # noqa: PLC0415

    inv = invoice_of(db, ra)
    return fsvc.outstanding(db, inv) if inv else Decimal(0)


def bill_out(db: Session, ra: RaBill, day: date) -> dict:
    due, how = due_of(db, ra)
    owed = outstanding(db, ra)
    inv = invoice_of(db, ra)
    steps = steps_of(db, ra)
    fus = list(
        db.scalars(
            select(PaymentFollowUp)
            .where(PaymentFollowUp.ra_bill_id == ra.id)
            .order_by(PaymentFollowUp.at.desc())
        )
    )
    return {"id": ra.id, "code": ra.code, "site_id": ra.site_id, "status": ra.status, "period_to": ra.period_to, "invoice": inv.number if inv else None,
            "invoice_date": inv.invoice_date if inv else None, "outstanding": owed, "due_on": due, "due_how": how,
            "overdue_days": (day - due).days if due and owed > 0 and day > due else 0,
            "steps": [{"step": s.step, "label": BILL_STEP_LABEL[s.step], "on": s.on_date, "by": s.by_name, "file": s.file_name, "note": s.note,
                       "days": ((steps[i + 1].on_date if i + 1 < len(steps) else day) - s.on_date).days} for i, s in enumerate(steps)],
            "at": BILL_STEP_LABEL[steps[-1].step] if steps else "not tracked yet",
            "followups": [{"at": f.at, "spoke_to": f.spoke_to, "said": f.said, "promised_on": f.promised_on} for f in fus]}  # fmt: skip


def log_followup(
    db: Session, ra: RaBill, spoke_to: str, said: str, promised_on: date | None, user_id
) -> PaymentFollowUp:
    f = PaymentFollowUp(
        ra_bill_id=ra.id, by_user=user_id, spoke_to=spoke_to, said=said, promised_on=promised_on
    )
    db.add(f)
    db.flush()
    return f


# --- the timed rules -------------------------------------------------------------------------------


def _at(day: date) -> datetime:
    return datetime.combine(day, time(9, 0), tzinfo=IST)


def timed_events(db: Session, at: datetime, site_ids: list[int] | None = None) -> int:
    """Daily: a bill not submitted by the end of the cycle window, a bill stuck at a step, and
    the payment reminders (due, +5, +30, the promised date); the client sees the overdue bill in
    the portal. site_ids limits the sweep (the DEMO runs it on its own site only)."""
    from app.process import engine  # noqa: PLC0415

    day = at.astimezone(IST).date()
    s = settings(db)
    n = 0
    q = select(Site).where(Site.status.in_(("active", "planned", "completed")))
    if site_ids is not None:
        q = q.where(Site.id.in_(site_ids))
    for site in db.scalars(q):
        cyc = cycle_for(db, site)
        bills = list(
            db.scalars(
                select(RaBill).where(RaBill.site_id == site.id, RaBill.status != "cancelled")
            )
        )
        if cyc is not None and day.day > cyc.submit_to_day:
            window = (
                date(day.year, day.month, min(cyc.submit_from_day, 28)),
                date(day.year, day.month, min(cyc.submit_to_day, 28 if day.month == 2 else 30)),
            )
            submitted = any(
                st.step != "prepared" and window[0] <= st.on_date <= day
                for b in bills
                for st in steps_of(db, b)
            )
            waiting = [
                b
                for b in bills
                if b.status == "draft"
                or not steps_of(db, b)
                or steps_of(db, b)[-1].step == "prepared"
            ]
            if waiting and not submitted:
                n += bool(engine.emit(db, "bill_not_submitted", subject=f"cycle:{site.id}:{day:%Y-%m}", site_id=site.id, at=at,
                                      data={"bill": waiting[0].code, "ra_bill_id": waiting[0].id, "window": f"{cyc.submit_from_day}–{cyc.submit_to_day}"}))  # fmt: skip
        for b in bills:
            steps = steps_of(db, b)
            if steps and steps[-1].step != "paid":
                stuck = (day - steps[-1].on_date).days
                data = {
                    "bill": b.code,
                    "ra_bill_id": b.id,
                    "step": BILL_STEP_LABEL[steps[-1].step],
                    "days": stuck,
                }
                if stuck >= s.bill_stuck_days:
                    n += bool(
                        engine.emit(
                            db,
                            "bill_stuck",
                            subject=f"stuck:{b.id}:{steps[-1].id}",
                            site_id=site.id,
                            at=at,
                            data=data,
                        )
                    )
                if stuck >= s.bill_stuck_days + s.bill_stuck_escalate_days:
                    n += bool(
                        engine.emit(
                            db,
                            "bill_stuck_long",
                            subject=f"stuck2:{b.id}:{steps[-1].id}",
                            site_id=site.id,
                            at=at,
                            data=data,
                        )
                    )
            n += _payment(db, engine, site, b, day, at, s)
    return n


def _payment(
    db: Session, engine, site: Site, b: RaBill, day: date, at: datetime, s: CloseoutSettings
) -> int:
    owed = outstanding(db, b)
    due, how = due_of(db, b)
    if owed <= 0 or due is None or day < due:
        return 0
    late = (day - due).days
    data = {
        "bill": b.code,
        "ra_bill_id": b.id,
        "due": due.strftime("%d.%m.%Y"),
        "days": late,
        "amount": f"{owed:,.2f}",
        "how": how,
    }
    n = 0
    n += bool(
        engine.emit(
            db, "payment_due", subject=f"due:{b.id}:{due}", site_id=site.id, at=at, data=data
        )
    )
    if late >= s.overdue_salesperson_days:
        n += bool(
            engine.emit(
                db,
                "payment_overdue",
                subject=f"late:{b.id}:{due}",
                site_id=site.id,
                at=at,
                data=data,
            )
        )
    if late >= s.overdue_director_days:
        n += bool(
            engine.emit(
                db,
                "payment_overdue_long",
                subject=f"late2:{b.id}:{due}",
                site_id=site.id,
                at=at,
                data=data,
            )
        )
    f = db.scalars(
        select(PaymentFollowUp)
        .where(PaymentFollowUp.ra_bill_id == b.id)
        .order_by(PaymentFollowUp.at.desc())
    ).first()
    if f and f.promised_on and day >= f.promised_on:
        n += bool(engine.emit(db, "payment_promised", subject=f"promised:{b.id}:{f.id}", site_id=site.id, at=at,
                              data={**data, "promised": f.promised_on.strftime("%d.%m.%Y"), "spoke_to": f.spoke_to}))  # fmt: skip
    if late >= 1:
        n += tell_client_overdue(db, site, b, late)
    return n


def tell_client_overdue(db: Session, site: Site, b: RaBill, late: int) -> int:
    """The client's accounts and project manager: an in-app notice in the portal (once per bill;
    never an email)."""
    from app.portal import service as portal  # noqa: PLC0415
    from app.portal.models import Notification  # noqa: PLC0415

    link = f"/portal/sites/{site.id}?tab=billing&bill={b.id}"
    if db.scalar(
        select(Notification.id)
        .where(Notification.kind == "bill_overdue", Notification.link == link)
        .limit(1)
    ):
        return 0
    users = [u for u in portal.client_users_of(db, site.id) if _client_pays(db, u)]
    return portal.notify(
        db, users, "bill_overdue", f"{b.code} is overdue by {late} day(s)", link, site.id
    )


def _client_pays(db: Session, user_id) -> bool:
    """The client's accounts and project manager (the roles that see payments)."""
    from app.portal import service as portal  # noqa: PLC0415

    have = portal.rights_of(db, user_id)
    return have is None or "payment.view" in have
