# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""The home dashboards: management (the whole company), sales, site supervisor, accounts and
store / purchase. Every tile carries `drill`: the filtered list of records behind its number
(see drill.py), and `as_of` when it comes from the summary tables.

Headline numbers:
- Order book: contract value of sites that are planned, active or on hold; billed to date on
  them (taxable value of invoices less credit notes); balance = value - billed, per site, never
  below zero.
- Billed this month: taxable value of invoices dated this month less credit notes (net of GST).
- Received this month: money received (receipt amounts, not TDS) dated this month.
- Won this month: tenders marked won this month (count and quoted value).
- Tenders submitted this month: tenders whose first revision was submitted this month.
- Receivables: total still owed on issued invoices; "overdue > 60 days": the due part (owed less
  retention still held) of invoices more than 60 days old; retention held on all sites.
- Payables: approved supplier bills not yet paid, due in the next 7 days / past their due date.
- Sites: active; delayed (planned end passed, or progress behind the time elapsed by more than the
  setting); active sites without a submitted DPR today.
- Margin (tender.margin): (billed - cost) / billed over all sites billed so far; cost includes
  staff salary only for callers with payroll.view.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.common import (
    OPEN_LEAD,
    ZERO,
    add_months,
    money,
    month_end,
    month_start,
    pct,
    quarter_start,
    sees_cost,
    sees_salary,
    today,
)
from app.analytics.models import InvoiceSummary, KpiSnapshot, SiteSummary
from app.analytics.summary import settings
from app.auth.deps import Principal
from app.crm.models import Lead
from app.execution.models import Attendance, Dpr
from app.finance.models import (
    Payment,
    PaymentAllocation,
    PayrollRun,
    Payslip,
    PettyCashAccount,
    PettyCashEntry,
    RaBill,
    Receipt,
    TaxInvoice,
    VendorBill,
)
from app.masters.models import Client, Product, Vendor
from app.material import service as material
from app.material.models import Grn, Indent, IndentLine, PurchaseOrder, StockLedger
from app.models import User
from app.portal.models import Snag
from app.sites.models import Site, StageTemplateStep, Task
from app.tenders.models import Tender, TenderRevision

ACTIVE = ("planned", "active", "on_hold")


def tile(
    key, label, value, unit="inr", prev=None, prev_label=None, drill=None, as_of=None, note=None
) -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "prev": prev,
        "prev_label": prev_label,
        "drill": drill,
        "as_of": as_of,
        "note": note,
    }


def _as_of(db: Session):
    return settings(db).refreshed_at


# --- money flows in a period ---------------------------------------------------------------------


def billed_between(db: Session, start: date, end: date, demo: bool) -> Decimal:
    rows = db.execute(
        select(TaxInvoice.kind, func.coalesce(func.sum(TaxInvoice.taxable), 0))
        .join(Client, Client.id == TaxInvoice.client_id)
        .where(
            TaxInvoice.status == "issued",
            TaxInvoice.invoice_date.between(start, end),
            Client.is_demo == demo,
        )
        .group_by(TaxInvoice.kind)
    ).all()
    d = {k: Decimal(v) for k, v in rows}
    return money(d.get("invoice", ZERO) - d.get("credit_note", ZERO))


def received_between(db: Session, start: date, end: date, demo: bool) -> Decimal:
    return money(
        db.scalar(
            select(func.coalesce(func.sum(Receipt.amount), 0))
            .join(Client, Client.id == Receipt.client_id)
            .where(Receipt.on_date.between(start, end), Client.is_demo == demo)
        )
    )


def won_between(db: Session, start: date, end: date, demo: bool, owner=None) -> tuple[int, Decimal]:
    q = select(func.count(), func.coalesce(func.sum(Tender.quoted_total), 0)).where(
        Tender.status == "won",
        Tender.is_demo == demo,
        func.date(func.timezone("Asia/Kolkata", Tender.decided_at)).between(start, end),
    )
    if owner is not None:
        q = q.where(Tender.owner_id == owner)
    n, v = db.execute(q).one()
    return n, money(v)


def first_submitted():
    return (
        select(TenderRevision.tender_id, func.min(TenderRevision.submitted_at).label("at"))
        .group_by(TenderRevision.tender_id)
        .subquery()
    )


def submitted_between(db: Session, start: date, end: date, demo: bool) -> int:
    fs = first_submitted()
    return db.scalar(
        select(func.count())
        .select_from(fs)
        .join(Tender, Tender.id == fs.c.tender_id)
        .where(
            Tender.is_demo == demo,
            func.date(func.timezone("Asia/Kolkata", fs.c.at)).between(start, end),
        )
    )


# --- stock values (also kept daily in kpi_snapshots) ---------------------------------------------


def vendor_balances(db: Session, demo: bool):
    """(bill, balance) for approved supplier bills with something left to pay."""
    paid = (
        select(PaymentAllocation.vendor_bill_id, func.sum(PaymentAllocation.amount).label("paid"))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(Payment.status == "paid")
        .group_by(PaymentAllocation.vendor_bill_id)
        .subquery()
    )
    q = (
        select(VendorBill, (VendorBill.payable - func.coalesce(paid.c.paid, 0)).label("balance"))
        .join(Vendor, Vendor.id == VendorBill.vendor_id)
        .outerjoin(paid, paid.c.vendor_bill_id == VendorBill.id)
        .where(VendorBill.status.in_(("approved", "partly_paid")), Vendor.is_demo == demo)
    )
    return [(b, Decimal(bal)) for b, bal in db.execute(q) if Decimal(bal) > 0]


def dpr_missing_today(db: Session, demo: bool, site_ids=None) -> list[Site]:
    day = today()
    done = select(Dpr.site_id).where(Dpr.on_date == day, Dpr.status != "draft")
    q = (
        select(Site)
        .where(Site.status == "active", Site.is_demo == demo, Site.id.not_in(done))
        .order_by(Site.code)
    )
    if site_ids is not None:
        q = q.where(Site.id.in_(site_ids or [0]))
    return [s for s in db.scalars(q) if not s.start_date or s.start_date <= day]


def stock_values(db: Session, demo: bool) -> dict:
    inv = db.execute(
        select(
            func.coalesce(func.sum(InvoiceSummary.outstanding), 0),
            func.coalesce(
                func.sum(InvoiceSummary.due).filter(
                    InvoiceSummary.invoice_date < today() - timedelta(days=60)
                ),
                0,
            ),
        ).where(InvoiceSummary.is_demo == demo)
    ).one()
    sums = db.execute(
        select(
            func.coalesce(func.sum(SiteSummary.retention_held), 0),
            func.count().filter(SiteSummary.status == "active"),
            func.count().filter(SiteSummary.delayed),
            func.coalesce(
                func.sum(SiteSummary.contract_value).filter(SiteSummary.status.in_(ACTIVE)), 0
            ),
        ).where(SiteSummary.is_demo == demo)
    ).one()
    day = today()
    bills = vendor_balances(db, demo)
    return {
        "outstanding": str(money(inv[0])),
        "overdue_60": str(money(inv[1])),
        "retention_held": str(money(sums[0])),
        "active_sites": sums[1],
        "delayed_sites": sums[2],
        "order_book": str(money(sums[3])),
        "payables_week": str(
            money(
                sum((bal for b, bal in bills if day <= b.due_date <= day + timedelta(days=7)), ZERO)
            )
        ),
        "payables_overdue": str(money(sum((bal for b, bal in bills if b.due_date < day), ZERO))),
    }


def _previous_snapshot(db: Session, demo: bool) -> tuple[dict | None, str | None]:
    snap = db.scalar(
        select(KpiSnapshot)
        .where(KpiSnapshot.is_demo == demo, KpiSnapshot.on_date <= today() - timedelta(days=28))
        .order_by(KpiSnapshot.on_date.desc())
        .limit(1)
    )
    return (snap.data, f"{snap.on_date:%d %b}") if snap else (None, None)


# --- management ----------------------------------------------------------------------------------


def management(db: Session, principal: Principal, demo: bool = False) -> dict:
    day = today()
    m0, prev0 = month_start(day), add_months(month_start(day), -1)
    prev_end = min(
        month_end(prev0), prev0 + timedelta(days=(day - m0).days)
    )  # same days into last month
    as_of = _as_of(db)
    prev, prev_label = _previous_snapshot(db, demo)

    def p(key):
        return prev.get(key) if prev else None

    sites = db.scalars(select(SiteSummary).where(SiteSummary.is_demo == demo)).all()
    book = [s for s in sites if s.status in ACTIVE and s.contract_value is not None]
    order_value = sum((Decimal(s.contract_value) for s in book), ZERO)
    billed_book = sum((Decimal(s.billed) for s in book), ZERO)
    balance = sum((max(ZERO, Decimal(s.contract_value) - Decimal(s.billed)) for s in book), ZERO)
    stock = stock_values(db, demo)
    won_n, won_v = won_between(db, m0, day, demo)
    pwon_n, pwon_v = won_between(db, prev0, prev_end, demo)
    vs = f"same days of {prev0:%b}"
    sections = [
        {
            "key": "order_book",
            "title": "Order book",
            "tiles": [
                tile(
                    "order_value",
                    "Active contracts",
                    money(order_value),
                    prev=p("order_book"),
                    prev_label=prev_label,
                    drill={"kind": "sites", "filter": "order_book"},
                    as_of=as_of,
                ),
                tile(
                    "order_billed",
                    "Billed to date",
                    money(billed_book),
                    drill={"kind": "sites", "filter": "order_book"},
                    as_of=as_of,
                ),
                tile(
                    "order_balance",
                    "Balance to bill",
                    money(balance),
                    drill={"kind": "sites", "filter": "order_book"},
                    as_of=as_of,
                ),
            ],
        },
        {
            "key": "month",
            "title": f"This month ({day:%b %Y})",
            "tiles": [
                tile(
                    "billed_month",
                    "Billed (net of GST)",
                    billed_between(db, m0, day, demo),
                    prev=billed_between(db, prev0, prev_end, demo),
                    prev_label=vs,
                    drill={"kind": "invoices", "filter": "month", "month": str(m0)},
                ),
                tile(
                    "received_month",
                    "Received",
                    received_between(db, m0, day, demo),
                    prev=received_between(db, prev0, prev_end, demo),
                    prev_label=vs,
                    drill={"kind": "receipts", "filter": "month", "month": str(m0)},
                ),
                tile(
                    "won_month",
                    "New orders won",
                    won_v,
                    prev=pwon_v,
                    prev_label=vs,
                    note=f"{won_n} tender(s)",
                    drill={"kind": "tenders", "filter": "won_month", "month": str(m0)},
                ),
                tile(
                    "submitted_month",
                    "Tenders submitted",
                    submitted_between(db, m0, day, demo),
                    unit="count",
                    prev=submitted_between(db, prev0, prev_end, demo),
                    prev_label=vs,
                    drill={"kind": "tenders", "filter": "submitted_month", "month": str(m0)},
                ),
            ],
        },
        {
            "key": "receivables",
            "title": "Receivables",
            "tiles": [
                tile(
                    "outstanding",
                    "Total outstanding",
                    Decimal(stock["outstanding"]),
                    prev=p("outstanding"),
                    prev_label=prev_label,
                    drill={"kind": "invoices", "filter": "outstanding"},
                    as_of=as_of,
                ),
                tile(
                    "overdue_60",
                    "Overdue over 60 days",
                    Decimal(stock["overdue_60"]),
                    prev=p("overdue_60"),
                    prev_label=prev_label,
                    drill={"kind": "invoices", "filter": "overdue", "days": 60},
                    as_of=as_of,
                ),
                tile(
                    "retention_held",
                    "Retention held",
                    Decimal(stock["retention_held"]),
                    prev=p("retention_held"),
                    prev_label=prev_label,
                    drill={"kind": "sites", "filter": "retention"},
                    as_of=as_of,
                ),
            ],
        },
        {
            "key": "payables",
            "title": "Payables",
            "tiles": [
                tile(
                    "payables_week",
                    "Due this week",
                    Decimal(stock["payables_week"]),
                    prev=p("payables_week"),
                    prev_label=prev_label,
                    drill={"kind": "vendor_bills", "filter": "due_week"},
                ),
                tile(
                    "payables_overdue",
                    "Overdue",
                    Decimal(stock["payables_overdue"]),
                    prev=p("payables_overdue"),
                    prev_label=prev_label,
                    drill={"kind": "vendor_bills", "filter": "overdue"},
                ),
            ],
        },
        {
            "key": "sites",
            "title": "Sites",
            "tiles": [
                tile(
                    "active_sites",
                    "Active",
                    stock["active_sites"],
                    unit="count",
                    prev=p("active_sites"),
                    prev_label=prev_label,
                    drill={"kind": "sites", "filter": "active"},
                    as_of=as_of,
                ),
                tile(
                    "delayed_sites",
                    "Delayed",
                    stock["delayed_sites"],
                    unit="count",
                    prev=p("delayed_sites"),
                    prev_label=prev_label,
                    drill={"kind": "sites", "filter": "delayed"},
                    as_of=as_of,
                    note=f"planned end passed, or > {settings(db).delay_threshold_points:.0f} points behind time",
                ),
                tile(
                    "dpr_missing",
                    "DPR missing today",
                    len(dpr_missing_today(db, demo)),
                    unit="count",
                    drill={"kind": "sites", "filter": "dpr_missing"},
                ),
            ],
        },
    ]
    out = {"as_of": as_of, "sections": sections, "margin": None}
    if sees_cost(principal):
        codes = dict(db.execute(select(Site.id, Site.code).where(Site.is_demo == demo)).all())
        out["margin"] = margin_block(sites, sees_salary(principal), as_of, codes)
    return out


def margin_block(sites, with_salary: bool, as_of, codes: dict | None = None) -> dict:
    billed = [s for s in sites if Decimal(s.billed) > 0 and not s.historic]

    def cost(s):
        return Decimal(s.cost) + (Decimal(s.salary_cost) if with_salary else ZERO)

    total_b = sum((Decimal(s.billed) for s in billed), ZERO)
    total_c = sum((cost(s) for s in billed), ZERO)
    rows = sorted(
        (
            {
                "site_id": s.site_id,
                "code": (codes or {}).get(s.site_id),
                "margin": pct(Decimal(s.billed) - cost(s), s.billed),
                "billed": s.billed,
                "cost": money(cost(s)),
            }
            for s in billed
        ),
        key=lambda r: r["margin"],
    )
    over = [s for s in sites if cost(s) > Decimal(s.billed) and cost(s) > 0 and not s.historic]
    return {
        "tiles": [
            tile(
                "margin",
                "Gross margin to date",
                pct(total_b - total_c, total_b),
                unit="pct",
                as_of=as_of,
                drill={"kind": "sites", "filter": "margin"},
                note=None if with_salary else "staff salary not included (needs payroll.view)",
            ),
            tile(
                "over_cost",
                "Sites where cost passed billed value",
                len(over),
                unit="count",
                as_of=as_of,
                drill={"kind": "sites", "filter": "over_cost"},
            ),
        ],
        "lowest": rows[:5],
        "salary_included": with_salary,
    }


# --- sales ---------------------------------------------------------------------------------------


def sales(db: Session, principal: Principal, scope: str, demo: bool = False) -> dict:
    me = principal.user.id
    own = scope == "own"
    day = today()
    lq = select(Lead).where(Lead.is_demo == demo)
    tq = select(Tender).where(Tender.is_demo == demo)
    if own:
        lq, tq = lq.where(Lead.owner_id == me), tq.where(Tender.owner_id == me)
    leads = lq.subquery()
    pipeline = [
        {"stage": st, "kind": "lead", "count": n, "value": money(v)}
        for st, n, v in db.execute(
            select(leads.c.status, func.count(), func.coalesce(func.sum(leads.c.est_value), 0))
            .where(leads.c.status.in_(OPEN_LEAD))
            .group_by(leads.c.status)
        )
    ]
    pipeline.sort(key=lambda r: OPEN_LEAD.index(r["stage"]))
    tenders = tq.subquery()
    for st, n, v in db.execute(
        select(tenders.c.status, func.count(), func.coalesce(func.sum(tenders.c.quoted_total), 0))
        .where(tenders.c.status.in_(("draft", "submitted")))
        .group_by(tenders.c.status)
    ):
        pipeline.append({"stage": f"tender {st}", "kind": "tender", "count": n, "value": money(v)})
    open_leads = select(func.count()).select_from(leads).where(leads.c.status.in_(OPEN_LEAD))
    due_today = db.scalar(open_leads.where(leads.c.next_follow_up == day))
    overdue = db.scalar(open_leads.where(leads.c.next_follow_up < day))
    due_week = db.scalar(
        select(func.count())
        .select_from(tenders)
        .where(tenders.c.status == "draft", tenders.c.due_on.between(day, day + timedelta(days=7)))
    )
    q0 = quarter_start(day)
    decided = (
        select(tenders.c.status, func.count())
        .where(
            tenders.c.status.in_(("won", "lost")),
            func.date(func.timezone("Asia/Kolkata", tenders.c.decided_at)) >= q0,
        )
        .group_by(tenders.c.status)
    )
    d = dict(db.execute(decided).all())
    # quotations (most work starts as one) count too; a tender made from a won quotation is
    # the same deal, so it is not counted twice
    from app.quotations import service as quotes  # noqa: PLC0415  (avoids an import cycle)
    from app.quotations.models import Quotation  # noqa: PLC0415

    qd: dict[str, int] = {}
    followups: list[dict] = []
    if not demo:
        qq = select(Quotation.status, func.count(func.distinct(Quotation.code))).where(
            Quotation.is_latest,
            Quotation.status.in_(("won", "lost")),
            func.date(func.timezone("Asia/Kolkata", Quotation.decided_at)) >= q0,
        )
        if own:
            qq = qq.where(Quotation.salesperson_id == me)
        qd = dict(db.execute(qq.group_by(Quotation.status)).all())
        from_quotes = db.scalar(
            select(func.count())
            .select_from(tenders)
            .where(
                tenders.c.status == "won",
                tenders.c.id.in_(select(Quotation.tender_id).where(Quotation.status == "won")),
                func.date(func.timezone("Asia/Kolkata", tenders.c.decided_at)) >= q0,
            )
        )
        d["won"] = d.get("won", 0) - (from_quotes or 0)
        followups = quotes.followup_rows(db, me if own else None, upto=day + timedelta(days=7))
    won = d.get("won", 0) + qd.get("won", 0)
    lost = d.get("lost", 0) + qd.get("lost", 0)
    target = quotes.closure_target(db, me if own else None)
    kylas = db.scalar(
        select(func.count()).select_from(leads).where(leads.c.kylas_sync_status == "failed")
    )
    who = {"owner": "me"} if own else {}
    return {
        "scope": scope,
        "pipeline": pipeline,
        "quotation_followups": followups,
        "tiles": [
            tile(
                "followups_today",
                "Follow-ups due today",
                due_today,
                unit="count",
                drill={"kind": "leads", "filter": "follow_today", **who},
            ),
            tile(
                "followups_overdue",
                "Follow-ups overdue",
                overdue,
                unit="count",
                drill={"kind": "leads", "filter": "follow_overdue", **who},
            ),
            tile(
                "tenders_due_week",
                "Tenders due this week",
                due_week,
                unit="count",
                drill={"kind": "tenders", "filter": "due_week", **who},
            ),
            {
                **tile(
                    "win_rate_quarter",
                    f"Win rate since {q0:%d %b}",
                    pct(won, won + lost),
                    unit="pct",
                    note=f"{won} won, {lost} lost (tenders and quotations) · target {float(target):g}%",
                    drill={"kind": "tenders", "filter": "decided_quarter", **who},
                ),
                "target": target,
            },
            tile(
                "kylas_errors",
                "Kylas sync errors",
                kylas,
                unit="count",
                drill={"kind": "leads", "filter": "kylas_failed", **who},
            ),
        ],
    }


# --- site supervisor -----------------------------------------------------------------------------


def supervisor(db: Session, principal: Principal, scope: str, demo: bool = False) -> dict:
    day = today()
    q = select(Site).where(Site.status == "active", Site.is_demo == demo).order_by(Site.code)
    if scope != "all":
        q = q.where(Site.id.in_(material.assigned_sites(principal)))
    out = []
    for s in db.scalars(q):
        dpr = db.scalar(select(Dpr.status).where(Dpr.site_id == s.id, Dpr.on_date == day))
        marked = db.scalar(
            select(func.count()).where(Attendance.site_id == s.id, Attendance.on_date == day)
        )
        pending = db.scalar(
            select(func.count())
            .select_from(Task)
            .join(StageTemplateStep, StageTemplateStep.id == Task.step_id)
            .where(
                Task.site_id == s.id,
                Task.status == "done",
                or_(StageTemplateStep.needs_inspection, StageTemplateStep.hold_point),
            )
        )
        snags = db.scalar(
            select(func.count()).where(
                Snag.site_id == s.id, Snag.status.in_(("open", "in_progress"))
            )
        )
        waiting = db.scalar(
            select(func.count(func.distinct(Indent.id)))
            .join(IndentLine, IndentLine.indent_id == Indent.id)
            .where(
                Indent.site_id == s.id,
                Indent.status.in_(("approved", "partly_ordered", "ordered")),
                IndentLine.received_qty < IndentLine.qty,
            )
        )
        out.append(
            {
                "site_id": s.id,
                "code": s.code,
                "name": s.name,
                "progress": s.progress_percent,
                "todos": [
                    {
                        "key": "dpr",
                        "label": "DPR today",
                        "done": dpr in ("submitted", "acknowledged"),
                        "value": dpr or "not started",
                        "link": f"/sites/{s.id}?tab=dpr",
                    },
                    {
                        "key": "attendance",
                        "label": "Attendance marked",
                        "done": marked > 0,
                        "value": marked,
                        "link": "/attendance",
                    },
                    {
                        "key": "inspections",
                        "label": "Steps waiting for inspection",
                        "done": pending == 0,
                        "value": pending,
                        "link": f"/sites/{s.id}?tab=inspections",
                    },
                    {
                        "key": "snags",
                        "label": "Open snags",
                        "done": snags == 0,
                        "value": snags,
                        "link": f"/snags?site_id={s.id}",
                    },
                    {
                        "key": "indents",
                        "label": "Indents awaiting delivery",
                        "done": waiting == 0,
                        "value": waiting,
                        "link": f"/sites/{s.id}?tab=material",
                    },
                ],
            }
        )
    return {"scope": scope, "sites": out}


# --- accounts ------------------------------------------------------------------------------------


def accounts(db: Session, principal: Principal, demo: bool = False) -> dict:
    day = today()
    as_of = _as_of(db)
    buckets = {"0-30": ZERO, "31-60": ZERO, "61-90": ZERO, "90+": ZERO}
    for inv_date, due in db.execute(
        select(InvoiceSummary.invoice_date, InvoiceSummary.due).where(
            InvoiceSummary.is_demo == demo, InvoiceSummary.due > 0
        )
    ):
        a = (day - inv_date).days
        buckets["0-30" if a <= 30 else "31-60" if a <= 60 else "61-90" if a <= 90 else "90+"] += (
            Decimal(due)
        )
    to_raise = db.execute(
        select(func.count(), func.coalesce(func.sum(RaBill.certified_gross), 0))
        .join(Site, Site.id == RaBill.site_id)
        .where(RaBill.status == "certified", Site.is_demo == demo)
    ).one()
    bills = vendor_balances(db, demo)
    week = [(b, bal) for b, bal in bills if b.due_date <= day + timedelta(days=7)]
    petty = db.execute(
        select(func.count(), func.coalesce(func.sum(PettyCashEntry.amount), 0))
        .join(PettyCashAccount, PettyCashAccount.id == PettyCashEntry.account_id)
        .join(User, User.id == PettyCashAccount.user_id)
        .where(PettyCashEntry.status == "submitted", User.is_demo == demo)
    ).one()
    month = f"{day:%Y-%m}"
    run = db.scalar(select(PayrollRun).where(PayrollRun.month == month))
    slips = db.scalar(select(func.count()).where(Payslip.run_id == run.id)) if run else 0
    return {
        "as_of": as_of,
        "ageing": [
            {
                "bucket": k,
                "amount": money(v),
                "drill": {"kind": "invoices", "filter": "bucket", "bucket": k},
            }
            for k, v in buckets.items()
        ],
        "tiles": [
            tile(
                "to_invoice",
                "Certified RA bills to invoice",
                money(to_raise[1]),
                note=f"{to_raise[0]} bill(s)",
                drill={"kind": "ra_bills", "filter": "to_invoice"},
            ),
            tile(
                "payments_due",
                "Supplier payments due in 7 days (incl. overdue)",
                money(sum((x[1] for x in week), ZERO)),
                note=f"{len(week)} bill(s)",
                drill={"kind": "vendor_bills", "filter": "due_7"},
            ),
            tile(
                "petty_pending",
                "Petty cash awaiting approval",
                money(petty[1]),
                note=f"{petty[0]} entr(ies)",
                drill={"kind": "petty", "filter": "pending"},
            ),
            tile(
                "payroll",
                f"Payroll {day:%b %Y}",
                run.status if run else "not started",
                unit="text",
                note=f"{slips} payslip(s)" if run else None,
                drill=None,
            ),
        ],
    }


# --- store / purchase ----------------------------------------------------------------------------


def stock_levels(db: Session, demo: bool) -> list[dict]:
    """Products with a reorder level and their total stock in all stores (base unit)."""
    stock = (
        select(StockLedger.product_id, func.sum(StockLedger.qty).label("qty"))
        .group_by(StockLedger.product_id)
        .subquery()
    )
    rows = db.execute(
        select(Product, func.coalesce(stock.c.qty, 0))
        .outerjoin(stock, stock.c.product_id == Product.id)
        .where(Product.reorder_level.is_not(None), Product.is_demo == demo, Product.is_active)
        .order_by(Product.name)
    )
    return [
        {
            "product_id": p.id,
            "code": p.code,
            "name": p.name,
            "unit": p.unit,
            "stock": Decimal(q),
            "reorder_level": p.reorder_level,
            "low": Decimal(q) < Decimal(p.reorder_level),
        }
        for p, q in rows
    ]


def purchase(db: Session, principal: Principal, demo: bool = False) -> dict:
    day = today()
    awaiting_po = db.scalar(
        select(func.count())
        .select_from(Indent)
        .join(Site, Site.id == Indent.site_id)
        .where(Indent.status.in_(("approved", "partly_ordered")), Site.is_demo == demo)
    )
    pos = db.execute(
        select(PurchaseOrder.id, PurchaseOrder.code, PurchaseOrder.expected_delivery, Vendor.name)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.status.in_(("approved", "sent", "partly_received")),
            Vendor.is_demo == demo,
        )
        .order_by(PurchaseOrder.expected_delivery.nulls_last())
    ).all()
    late = [p for p in pos if p.expected_delivery and p.expected_delivery < day]
    low = [r for r in stock_levels(db, demo) if r["low"]]
    grns = db.scalar(
        select(func.count())
        .select_from(Grn)
        .join(Vendor, Vendor.id == Grn.vendor_id)
        .where(Grn.status == "submitted", Vendor.is_demo == demo)
    )
    return {
        "tiles": [
            tile(
                "indents_awaiting_po",
                "Indents awaiting PO",
                awaiting_po,
                unit="count",
                drill={"kind": "indents", "filter": "awaiting_po"},
            ),
            tile(
                "pos_awaiting",
                "POs awaiting delivery",
                len(pos),
                unit="count",
                note=f"{len(late)} late",
                drill={"kind": "pos", "filter": "awaiting"},
            ),
            tile(
                "pos_late",
                "POs late",
                len(late),
                unit="count",
                drill={"kind": "pos", "filter": "late"},
            ),
            tile(
                "low_stock",
                "Products below reorder level",
                len(low),
                unit="count",
                drill={"kind": "products", "filter": "low_stock"},
            ),
            tile(
                "grns_pending",
                "GRNs awaiting approval",
                grns,
                unit="count",
                drill={"kind": "grns", "filter": "submitted"},
            ),
        ],
        "pos": [
            {
                "id": p.id,
                "code": p.code,
                "vendor": p[3],
                "expected": p.expected_delivery,
                "late": bool(p.expected_delivery and p.expected_delivery < day),
                "link": f"/purchase-orders/{p.id}",
            }
            for p in pos[:15]
        ],
        "low_stock": low[:15],
    }


__all__ = ["and_"]
