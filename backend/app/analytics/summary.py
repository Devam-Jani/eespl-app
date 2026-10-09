"""The summary tables: rebuilt by the worker every night and on demand (Refresh on a dashboard).

Each number is computed the way the finance and execution modules compute it for one site or
invoice (site_profit, actuals, invoice_positions), but in grouped queries over all sites at once,
so the dashboards stay fast with years of data. Tests check that the two agree.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, delete, func, literal, literal_column, select
from sqlalchemy.orm import Session

from app.analytics.common import ZERO, money, now, pct, today
from app.analytics.models import (
    AnalyticsSettings,
    InvoiceSummary,
    KpiSnapshot,
    MonthlySummary,
    ProgressSnapshot,
    SiteSummary,
)
from app.crm.models import Lead
from app.execution import service as ex
from app.execution.models import (
    BUDGET_HEADS,
    Attendance,
    EquipmentUsage,
    Labour,
    SiteBudget,
    SiteCost,
    WoLine,
    WoMeasurement,
    WorkOrder,
)
from app.finance.models import (
    ClientContract,
    ExpenseCategory,
    PayrollRun,
    Payslip,
    PettyCashEntry,
    RaBill,
    Receipt,
    ReceiptAllocation,
    RetentionRelease,
    TaxInvoice,
)
from app.masters.models import Client
from app.material.models import FreightEntry, SiteIssue, SiteIssueLine, StockLedger, Store
from app.portal.models import Snag
from app.sites.models import AreaScope, Site, SiteMember
from app.tenders.models import BoqLine, Tender

SQM_UNITS = {"sqm", "sq.m", "sq m", "m2", "sqmt", "sq.mt", "smt"}


def settings(db: Session) -> AnalyticsSettings:
    s = db.get(AnalyticsSettings, 1)
    if s is None:
        s = AnalyticsSettings(id=1)
        db.add(s)
        db.flush()
    return s


def _month(col):
    return cast(func.date_trunc(literal_column("'month'"), col), Date)


# --- cost by site, month and head ----------------------------------------------------------------


def cost_rows(db: Session) -> list[tuple[int, date, str, Decimal]]:
    """(site, month, head, amount) for every cost the site budget page counts (ex.actuals), with
    approved petty cash as its own head 'petty_cash' (as site profit shows it)."""
    rows: list[tuple[int, date, str, Decimal]] = []
    sign = case((SiteIssue.kind == "issue", 1), else_=-1)
    for site_id, m, v in db.execute(
        select(SiteIssue.site_id, _month(SiteIssue.issued_on), func.sum(SiteIssueLine.value * sign))
        .join(SiteIssueLine, SiteIssueLine.issue_id == SiteIssue.id)
        .group_by(SiteIssue.site_id, _month(SiteIssue.issued_on))
    ):
        rows.append((site_id, m, "material", Decimal(v)))
    at_ist = func.timezone("Asia/Kolkata", StockLedger.at)
    for site_id, m, v in db.execute(
        select(Store.site_id, _month(at_ist), func.sum(StockLedger.value))
        .join(Store, Store.id == StockLedger.store_id)
        .where(Store.site_id.is_not(None), StockLedger.ref_type == "shortage")
        .group_by(Store.site_id, _month(at_ist))
    ):
        rows.append((site_id, m, "material", -Decimal(v)))  # shortage rows are negative
    factor = case(
        (Attendance.status == "present", Decimal(1)),
        (Attendance.status == "half_day", Decimal("0.5")),
        else_=0,
    )
    wage = func.round(
        factor * Attendance.daily_wage + Attendance.ot_hours * Attendance.ot_rate_per_hour, 2
    )
    for site_id, m, v in db.execute(
        select(Attendance.site_id, _month(Attendance.on_date), func.sum(wage))
        .join(Labour, Labour.id == Attendance.labour_id)
        .where(Labour.type == "own")
        .group_by(Attendance.site_id, _month(Attendance.on_date))
    ):
        rows.append((site_id, m, "labour", Decimal(v)))
    for site_id, m, v in db.execute(
        select(
            WorkOrder.site_id,
            _month(WoMeasurement.on_date),
            func.sum(WoMeasurement.qty * WoLine.rate),
        )
        .join(WoLine, WoLine.id == WoMeasurement.line_id)
        .join(WorkOrder, WorkOrder.id == WoLine.wo_id)
        .where(WoMeasurement.status == "verified")
        .group_by(WorkOrder.site_id, _month(WoMeasurement.on_date))
    ):
        rows.append((site_id, m, "subcontract", Decimal(v)))
    for site_id, m, v in db.execute(
        select(
            EquipmentUsage.site_id, _month(EquipmentUsage.on_date), func.sum(EquipmentUsage.amount)
        ).group_by(EquipmentUsage.site_id, _month(EquipmentUsage.on_date))
    ):
        rows.append((site_id, m, "equipment", Decimal(v)))
    for site_id, m, v in db.execute(
        select(FreightEntry.site_id, _month(FreightEntry.on_date), func.sum(FreightEntry.amount))
        .where(FreightEntry.site_id.is_not(None))
        .group_by(FreightEntry.site_id, _month(FreightEntry.on_date))
    ):
        rows.append((site_id, m, "freight", Decimal(v)))
    for site_id, m, v in db.execute(
        select(
            PettyCashEntry.site_id, _month(PettyCashEntry.on_date), func.sum(PettyCashEntry.amount)
        )
        .outerjoin(ExpenseCategory, ExpenseCategory.id == PettyCashEntry.category_id)
        .where(
            PettyCashEntry.site_id.is_not(None),
            PettyCashEntry.kind == "expense",
            PettyCashEntry.status == "approved",
        )
        .group_by(PettyCashEntry.site_id, _month(PettyCashEntry.on_date))
    ):
        rows.append((site_id, m, "petty_cash", Decimal(v)))
    for site_id, m, head, v in db.execute(
        select(
            SiteCost.site_id, _month(SiteCost.on_date), SiteCost.head, func.sum(SiteCost.amount)
        ).group_by(SiteCost.site_id, _month(SiteCost.on_date), SiteCost.head)
    ):
        rows.append((site_id, m, head, Decimal(v)))
    return rows


def salary_rows(db: Session) -> list[tuple[int, date, Decimal]]:
    """Staff salary cost (gross + employer PF / ESI) by site and month, split by check-in days
    (as finance.service.staff_cost)."""
    out = []
    for p, month in db.execute(
        select(Payslip, PayrollRun.month).join(PayrollRun, PayrollRun.id == Payslip.run_id)
    ):
        days = sum(int(v) for v in (p.site_days or {}).values())
        if not days:
            continue
        cost = Decimal(p.gross) + Decimal(p.pf_employer) + Decimal(p.esi_employer)
        m = date(int(month[:4]), int(month[5:7]), 1)
        for site, n in (p.site_days or {}).items():
            if int(n):
                out.append((int(site), m, cost * int(n) / days))
    return out


# --- invoices ------------------------------------------------------------------------------------


def invoice_positions(db: Session) -> list[dict]:
    """finance.service.invoice_positions for every issued invoice, in grouped queries."""
    settled = dict(
        db.execute(
            select(ReceiptAllocation.invoice_id, func.sum(ReceiptAllocation.amount)).group_by(
                ReceiptAllocation.invoice_id
            )
        ).all()
    )
    credited = dict(
        db.execute(
            select(TaxInvoice.against_id, func.sum(TaxInvoice.total))
            .where(TaxInvoice.against_id.is_not(None), TaxInvoice.status == "issued")
            .group_by(TaxInvoice.against_id)
        ).all()
    )
    released = dict(
        db.execute(
            select(RetentionRelease.site_id, func.sum(RetentionRelease.amount)).group_by(
                RetentionRelease.site_id
            )
        ).all()
    )
    pool = {k: Decimal(v) for k, v in released.items()}
    day = today()
    out = []
    invoices = db.scalars(
        select(TaxInvoice)
        .where(TaxInvoice.kind == "invoice", TaxInvoice.status == "issued")
        .order_by(TaxInvoice.invoice_date, TaxInvoice.id)
    )
    for inv in invoices:
        left = pool.get(inv.site_id, ZERO) if inv.site_id else ZERO
        released_here = min(Decimal(inv.retention), left)
        if inv.site_id:
            pool[inv.site_id] = left - released_here
        held = Decimal(inv.retention) - released_here
        os_ = max(
            ZERO,
            Decimal(inv.total)
            - Decimal(settled.get(inv.id, 0))
            - Decimal(inv.advance_recovery)
            - Decimal(inv.other_deduction)
            - Decimal(credited.get(inv.id, 0)),
        )
        out.append(
            {
                "invoice": inv,
                "outstanding": os_,
                "retention_held": min(held, os_),
                "due": max(ZERO, os_ - held),
                "age": (day - inv.invoice_date).days,
            }
        )
    return out


# --- progress and forecast -----------------------------------------------------------------------


MIN_HISTORY_DAYS = 14
MIN_RATE = Decimal("0.05")  # % a day: slower than this is not a forecast
TOO_LATE_DAYS = 730
NOT_ENOUGH = "not enough progress to forecast"
TOO_LATE = "more than 2 years late"


def forecast(history: list[tuple[date, Decimal]], current: Decimal, start: date | None, on: date):
    """(rate % per day, forecast end). The rate is the progress made over the last 30 days of
    snapshots, needing at least 14 days of history (without snapshots: since the start, when that
    was at least 14 days ago). No forecast end below 0.05 % a day."""
    current = Decimal(current)
    if current >= 100:
        return None, on
    rate = None
    past = sorted((d, Decimal(p)) for d, p in history if d < on)
    if past:
        cutoff = on - timedelta(days=30)
        base = next((x for x in reversed(past) if x[0] <= cutoff), None) or past[0]
        days = (on - base[0]).days
        if days >= MIN_HISTORY_DAYS:
            rate = (current - base[1]) / days
    if rate is None and start and (on - start).days >= MIN_HISTORY_DAYS:
        rate = current / (on - start).days
    if rate is None:
        return None, None
    rate = rate.quantize(Decimal("0.0001"))
    if rate <= MIN_RATE:
        return rate, None
    return rate, on + timedelta(days=math.ceil((100 - current) / rate))


def forecast_text(end: date | None, target: date | None, progress) -> tuple[str, int | None]:
    """(what to show for the forecast end, slip in days): a date, or why there is none."""
    if end is None:
        return ("done" if Decimal(progress or 0) >= 100 else NOT_ENOUGH), None
    if target and (end - target).days > TOO_LATE_DAYS:
        return TOO_LATE, None
    return f"{end:%d %b %Y}", (end - target).days if target else None


def elapsed(start: date | None, target: date | None, on: date) -> Decimal | None:
    if not start or not target or target <= start:
        return None
    share = Decimal((on - start).days) / Decimal((target - start).days) * 100
    return max(Decimal(0), min(Decimal(100), share)).quantize(Decimal("0.01"))


def is_delayed(status: str, progress: Decimal, start, target, on: date, threshold) -> str | None:
    """Why a site is delayed, or None: its planned end has passed, or its progress is more than
    `threshold` points behind the share of planned time gone."""
    if status != "active" or Decimal(progress) >= 100:
        return None
    if target and target < on:
        return "past planned end"
    e = elapsed(start, target, on)
    if e is not None and e - Decimal(progress) > Decimal(threshold):
        return "behind time"
    return None


# --- refresh -------------------------------------------------------------------------------------


def _salesperson(db: Session, site: Site) -> object | None:
    if site.tender_id:
        owner = db.scalar(select(Tender.owner_id).where(Tender.id == site.tender_id))
        if owner:
            return owner
        lead_owner = db.scalar(
            select(Lead.owner_id).where(
                Lead.tender_id == site.tender_id, Lead.owner_id.is_not(None)
            )
        )
        if lead_owner:
            return lead_owner
    return db.scalar(
        select(SiteMember.user_id)
        .where(SiteMember.site_id == site.id, SiteMember.role_on_site == "sales")
        .limit(1)
    )


def tender_facts(db: Session, tender_id: int | None) -> tuple[int | None, Decimal | None]:
    """(main system: the one with the largest quoted amount, quoted margin %)."""
    if not tender_id:
        return None, None
    by_system: dict[int, Decimal] = defaultdict(Decimal)
    amount = cost = ZERO
    for ln in db.scalars(select(BoqLine).where(BoqLine.tender_id == tender_id)):
        a = Decimal(ln.amount or 0)
        if ln.system_id:
            by_system[ln.system_id] += a
        if ln.cost_rate is not None and ln.qty is not None and a:
            amount += a
            cost += Decimal(ln.cost_rate) * Decimal(ln.qty)
    system = max(by_system, key=by_system.get) if by_system else None
    return system, pct(amount - cost, amount)


def refresh(db: Session) -> datetime:
    """Rebuild every summary table and today's progress / KPI snapshots. Returns the as-of time."""
    as_of, day = now(), today()
    s = settings(db)
    threshold = s.delay_threshold_points
    sites = list(db.scalars(select(Site)))
    demo_site = {x.id: x.is_demo for x in sites}
    client_demo = dict(db.execute(select(Client.id, Client.is_demo)).all())
    client_type = dict(db.execute(select(Client.id, Client.type)).all())

    # cost
    costs = cost_rows(db)
    salaries = salary_rows(db)
    heads: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    month_cost: dict[tuple[int, date], Decimal] = defaultdict(Decimal)
    month_labour: dict[tuple[int, date], Decimal] = defaultdict(Decimal)
    for site_id, m, head, v in costs:
        heads[site_id][head] += v
        month_cost[(site_id, m)] += v
        if head in ("labour", "subcontract"):
            month_labour[(site_id, m)] += v
    salary: dict[int, Decimal] = defaultdict(Decimal)
    month_salary: dict[tuple[int, date], Decimal] = defaultdict(Decimal)
    for site_id, m, v in salaries:
        salary[site_id] += v
        month_salary[(site_id, m)] += v

    # billing, money in
    sign = case((TaxInvoice.kind == "invoice", 1), else_=-1)
    billed = defaultdict(
        Decimal,
        {
            k: Decimal(v)
            for k, v in db.execute(
                select(TaxInvoice.site_id, func.sum(TaxInvoice.taxable * sign))
                .where(TaxInvoice.status == "issued")
                .group_by(TaxInvoice.site_id)
            )
        },
    )
    certified = defaultdict(
        Decimal,
        {
            k: Decimal(v)
            for k, v in db.execute(
                select(RaBill.site_id, func.sum(func.coalesce(RaBill.certified_gross, 0)))
                .where(RaBill.status.in_(("certified", "invoiced")))
                .group_by(RaBill.site_id)
            )
        },
    )
    received = defaultdict(
        Decimal,
        {
            k: Decimal(v)
            for k, v in db.execute(
                select(TaxInvoice.site_id, func.sum(ReceiptAllocation.amount))
                .join(TaxInvoice, TaxInvoice.id == ReceiptAllocation.invoice_id)
                .group_by(TaxInvoice.site_id)
            )
        },
    )
    retained = defaultdict(
        Decimal,
        {
            k: Decimal(v)
            for k, v in db.execute(
                select(TaxInvoice.site_id, func.sum(TaxInvoice.retention))
                .where(TaxInvoice.kind == "invoice", TaxInvoice.status == "issued")
                .group_by(TaxInvoice.site_id)
            )
        },
    )
    released = defaultdict(
        Decimal,
        {
            k: Decimal(v)
            for k, v in db.execute(
                select(RetentionRelease.site_id, func.sum(RetentionRelease.amount)).group_by(
                    RetentionRelease.site_id
                )
            )
        },
    )
    contracts = {c.site_id: Decimal(c.contract_value) for c in db.scalars(select(ClientContract))}

    # invoices
    positions = invoice_positions(db)
    db.execute(delete(InvoiceSummary))
    outstanding: dict[int, Decimal] = defaultdict(Decimal)
    for p in positions:
        inv = p["invoice"]
        demo = demo_site.get(inv.site_id) if inv.site_id else client_demo.get(inv.client_id, False)
        db.add(
            InvoiceSummary(
                invoice_id=inv.id,
                is_demo=bool(demo),
                site_id=inv.site_id,
                client_id=inv.client_id,
                invoice_date=inv.invoice_date,
                due_date=inv.due_date,
                total=inv.total,
                outstanding=money(p["outstanding"]),
                retention_held=money(p["retention_held"]),
                due=money(p["due"]),
                as_of=as_of,
            )
        )
        if inv.site_id:
            outstanding[inv.site_id] += p["outstanding"]

    # attendance, snags, area, budgets
    att = {
        k: (Decimal(md), n)
        for k, md, n in db.execute(
            select(
                Attendance.site_id,
                func.sum(
                    case(
                        (Attendance.status == "present", Decimal(1)),
                        (Attendance.status == "half_day", Decimal("0.5")),
                        else_=0,
                    )
                ),
                func.count(),
            ).group_by(Attendance.site_id)
        )
    }
    snag_open = dict(
        db.execute(
            select(Snag.site_id, func.count())
            .where(Snag.status.in_(("open", "in_progress", "fixed")))
            .group_by(Snag.site_id)
        ).all()
    )
    closed_at = func.coalesce(Snag.verified_at, Snag.fixed_at)
    snag_closed = {
        k: (n, d)
        for k, n, d in db.execute(
            select(
                Snag.site_id,
                func.count(),
                func.avg(func.extract("epoch", closed_at - Snag.created_at) / 86400),
            )
            .where(Snag.status.in_(("verified", "closed")))
            .group_by(Snag.site_id)
        )
    }
    area: dict[int, Decimal] = defaultdict(Decimal)
    for site_id, unit, qty, prog in db.execute(
        select(AreaScope.site_id, AreaScope.unit, AreaScope.qty, AreaScope.progress_percent)
    ):
        if (unit or "sqm").strip().lower() in SQM_UNITS:
            area[site_id] += Decimal(qty) * Decimal(prog) / 100
    budgets: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for b in db.scalars(select(SiteBudget)):
        budgets[b.site_id][b.head] = Decimal(b.amount)
    history: dict[int, list] = defaultdict(list)
    for site_id, d, p in db.execute(
        select(ProgressSnapshot.site_id, ProgressSnapshot.on_date, ProgressSnapshot.percent).where(
            ProgressSnapshot.on_date >= day - timedelta(days=60)
        )
    ):
        history[site_id].append((d, p))

    db.execute(delete(SiteSummary))
    for site in sites:
        h = heads.get(site.id, {})
        actual = {k: money(h.get(k, ZERO)) for k in BUDGET_HEADS}
        cost_heads = {k: str(v) for k, v in actual.items() if v} | (
            {"petty_cash": str(money(h["petty_cash"]))} if h.get("petty_cash") else {}
        )
        cost = sum(actual.values(), ZERO) + money(h.get("petty_cash", ZERO))
        budget = dict(budgets.get(site.id, {}))
        for head, amount in ex.tender_budget(db, site).items():
            budget.setdefault(head, amount)
        system, tender_margin = tender_facts(db, site.tender_id)
        rate, fc = forecast(history.get(site.id, []), site.progress_percent, site.start_date, day)
        reason = is_delayed(
            site.status, site.progress_percent, site.start_date, site.target_date, day, threshold
        )
        md, _n = att.get(site.id, (ZERO, 0))
        closed = snag_closed.get(site.id)
        db.add(
            SiteSummary(
                site_id=site.id,
                as_of=as_of,
                is_demo=site.is_demo,
                historic=site.source == "powerplay",
                status=site.status,
                client_id=site.client_id,
                client_type=client_type.get(site.client_id),
                region=site.state,
                salesperson_id=_salesperson(db, site),
                system_id=system,
                start_date=site.start_date,
                target_date=site.target_date,
                progress=site.progress_percent,
                elapsed=elapsed(site.start_date, site.target_date, day),
                rate_per_day=rate,
                forecast_end=fc,
                delayed=reason is not None,
                delay_reason=reason,
                contract_value=contracts.get(site.id),
                billed=money(billed[site.id]),
                certified=money(certified[site.id]),
                received=money(received[site.id]),
                outstanding=money(outstanding[site.id]),
                retention_held=money(max(ZERO, retained[site.id] - released[site.id])),
                cost=money(cost),
                cost_heads=cost_heads,
                salary_cost=money(salary[site.id]),
                budget_heads={k: str(money(v)) for k, v in budget.items()},
                tender_margin=tender_margin,
                open_snags=snag_open.get(site.id, 0),
                closed_snags=closed[0] if closed else 0,
                snag_close_days=Decimal(closed[1]).quantize(Decimal("0.1"))
                if closed and closed[1] is not None
                else None,
                man_days=md,
                labour_cost=money(actual["labour"] + actual["subcontract"]),
                area_done=money(area[site.id]),
                material_value=actual["material"],
                freight=actual["freight"],
            )
        )
        if site.status in ("active", "planned", "on_hold"):
            snap = db.get(ProgressSnapshot, (site.id, day))
            if snap is None:
                db.add(
                    ProgressSnapshot(site_id=site.id, on_date=day, percent=site.progress_percent)
                )
            else:
                snap.percent = site.progress_percent

    _monthly(db, as_of, demo_site, client_demo, month_cost, month_salary, month_labour)
    s.refreshed_at = as_of
    db.flush()
    _kpi_snapshots(db, day)
    db.commit()
    return as_of


def _monthly(db, as_of, demo_site, client_demo, month_cost, month_salary, month_labour) -> None:
    rows: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

    def key(site_id, m, client_id=None):
        demo = demo_site.get(site_id) if site_id else client_demo.get(client_id, False)
        return (m, site_id, bool(demo))

    inv_month = _month(TaxInvoice.invoice_date)
    for site_id, client_id, kind, m, taxable, total, adv, other in db.execute(
        select(
            TaxInvoice.site_id,
            TaxInvoice.client_id,
            TaxInvoice.kind,
            inv_month,
            func.sum(TaxInvoice.taxable),
            func.sum(TaxInvoice.total),
            func.sum(TaxInvoice.advance_recovery),
            func.sum(TaxInvoice.other_deduction),
        )
        .where(TaxInvoice.status == "issued")
        .group_by(TaxInvoice.site_id, TaxInvoice.client_id, TaxInvoice.kind, inv_month)
    ):
        r = rows[key(site_id, m, client_id)]
        if kind == "invoice":
            r["billed"] += Decimal(taxable)
            r["invoiced"] += Decimal(total) - Decimal(adv) - Decimal(other)
        else:
            r["billed"] -= Decimal(taxable)
            r["credited"] += Decimal(total)
    rec_month = _month(Receipt.on_date)
    for site_id, client_id, m, amount in db.execute(
        select(Receipt.site_id, Receipt.client_id, rec_month, func.sum(Receipt.amount)).group_by(
            Receipt.site_id, Receipt.client_id, rec_month
        )
    ):
        rows[key(site_id, m, client_id)]["received"] += Decimal(amount)
    for site_id, client_id, m, amount in db.execute(
        select(
            TaxInvoice.site_id, TaxInvoice.client_id, rec_month, func.sum(ReceiptAllocation.amount)
        )
        .join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
        .join(TaxInvoice, TaxInvoice.id == ReceiptAllocation.invoice_id)
        .group_by(TaxInvoice.site_id, TaxInvoice.client_id, rec_month)
    ):
        rows[key(site_id, m, client_id)]["settled"] += Decimal(amount)
    for (site_id, m), v in month_cost.items():
        rows[key(site_id, m)]["cost"] += v
    for (site_id, m), v in month_salary.items():
        rows[key(site_id, m)]["salary_cost"] += v
    for (site_id, m), v in month_labour.items():
        rows[key(site_id, m)]["labour_cost"] += v
    att_month = _month(Attendance.on_date)
    for site_id, m, md, n in db.execute(
        select(
            Attendance.site_id,
            att_month,
            func.sum(
                case(
                    (Attendance.status == "present", Decimal(1)),
                    (Attendance.status == "half_day", Decimal("0.5")),
                    else_=0,
                )
            ),
            func.count(),
        ).group_by(Attendance.site_id, att_month)
    ):
        r = rows[key(site_id, m)]
        r["man_days"] += Decimal(md)
        r["marked"] += n
    db.execute(delete(MonthlySummary))
    for (m, site_id, demo), r in rows.items():
        db.add(
            MonthlySummary(
                month=m,
                site_id=site_id,
                is_demo=demo,
                as_of=as_of,
                marked=int(r.pop("marked", 0)),
                **{k: money(v) if k != "man_days" else v for k, v in r.items()},
            )
        )


def _kpi_snapshots(db: Session, day: date) -> None:
    """Today's management tiles, kept for the previous-period comparison of stock values."""
    from app.analytics import kpi

    for demo in (False, True):
        if demo and not db.scalar(select(literal(True)).where(Site.is_demo).limit(1)):
            continue
        data = kpi.stock_values(db, demo)
        snap = db.get(KpiSnapshot, (day, demo))
        if snap is None:
            db.add(KpiSnapshot(on_date=day, is_demo=demo, data=data))
        else:
            snap.data = data


def site_profit_check(db: Session, site_id: int) -> dict:
    """The summary row of a site, for comparisons with the live site profit."""
    s = db.get(SiteSummary, site_id)
    return {"billed": s.billed, "cost": s.cost, "salary": s.salary_cost}


__all__ = ["datetime"]
