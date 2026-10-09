# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""The analytics pages. Each returns `tables` ({key: {title, columns, rows}}): the charts are drawn
from them and the Excel export writes one sheet per table.

- Sites: progress against the share of planned time gone (scatter), planned vs forecast end
  (forecast from the last 30 days of progress), stage bottlenecks (open steps stuck longest),
  snags and how long they took to close.
- Finance: billed vs received vs cost by month, cash flow for the next 8 weeks (invoice due dates
  vs supplier bill due dates), DSO by month, outstanding by client.
- Profitability (tender.margin): margin by site, client, system and salesperson; quoted vs actual
  margin on finished sites.
- Purchase: spend by supplier and by category, price trend of the top 20 products, freight as % of
  the material value used per site.
- Labour: man-days per site per month, labour cost per sqm done, attendance rate.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import summary as summary_mod
from app.analytics.common import (
    ZERO,
    Filters,
    add_months,
    money,
    month_end,
    months,
    pct,
    sees_cost,
    sees_salary,
    today,
)
from app.analytics.kpi import vendor_balances
from app.analytics.models import InvoiceSummary, MonthlySummary, SiteSummary
from app.analytics.summary import settings
from app.auth.deps import Principal
from app.masters.models import Category, Client, Product, System, Vendor
from app.material import service as material
from app.material.models import PoLine, PurchaseOrder
from app.models import User
from app.sites.models import Site, StageTemplateStep, Task

PO_COUNTED = ("approved", "sent", "partly_received", "received", "closed")


def col(key, label, unit="text"):
    return {"key": key, "label": label, "unit": unit}


def table(title, columns, rows, note=None) -> dict:
    return {"title": title, "columns": columns, "rows": rows, "note": note}


def summaries(db: Session, principal: Principal, scope: str, f: Filters, statuses=None):
    q = (
        select(SiteSummary, Site.code, Site.name)
        .join(Site, Site.id == SiteSummary.site_id)
        .where(SiteSummary.is_demo == f.demo)
    )
    if scope != "all":
        q = q.where(Site.id.in_(material.assigned_sites(principal)))
    if f.region:
        q = q.where(SiteSummary.region == f.region)
    if f.salesperson:
        q = q.where(SiteSummary.salesperson_id == f.salesperson)
    if f.client_type:
        q = q.where(SiteSummary.client_type == f.client_type)
    if f.site_status:
        q = q.where(SiteSummary.status == f.site_status)
    elif statuses:
        q = q.where(SiteSummary.status.in_(statuses))
    return db.execute(q.order_by(Site.code)).all()


# --- sites ---------------------------------------------------------------------------------------


def sites_page(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    day = today()
    rows = summaries(db, principal, scope, f, statuses=("active", "planned", "on_hold"))
    scatter = [
        {
            "id": s.site_id,
            "code": code,
            "name": name,
            "elapsed": s.elapsed,
            "progress": s.progress,
            "delayed": s.delayed,
            "link": f"/sites/{s.site_id}",
        }
        for s, code, name in rows
        if s.elapsed is not None
    ]
    forecast = []
    for s, code, name in rows:
        shown, slip = summary_mod.forecast_text(s.forecast_end, s.target_date, s.progress)
        forecast.append(
            {
                "id": s.site_id,
                "code": code,
                "name": name,
                "start": s.start_date,
                "target": s.target_date,
                "forecast": shown,
                "slip_days": slip,
                "progress": s.progress,
                "rate": s.rate_per_day,
                "delay": s.delay_reason,
                "link": f"/sites/{s.site_id}",
            }
        )
    forecast.sort(
        key=lambda r: (
            0 if r["forecast"] == summary_mod.TOO_LATE else 1 if r["slip_days"] is not None else 2,
            -(r["slip_days"] or 0),
        )
    )
    ids = [s.site_id for s, _, _ in rows]
    started = func.coalesce(Task.actual_start, Task.planned_start, func.date(Task.created_at))
    stuck = []
    for step, n, avg_days, max_days, where in db.execute(
        select(
            func.coalesce(StageTemplateStep.name, Task.name),
            func.count(),
            func.avg(day - started),
            func.max(day - started),
            func.array_agg(func.distinct(Task.site_id)),
        )
        .outerjoin(StageTemplateStep, StageTemplateStep.id == Task.step_id)
        .where(
            Task.site_id.in_(ids or [0]),
            Task.status.in_(("in_progress", "blocked")),
            Task.parent_task_id.is_(None),
        )
        .group_by(func.coalesce(StageTemplateStep.name, Task.name))
        .order_by(func.avg(day - started).desc())
        .limit(12)
    ):
        stuck.append(
            {
                "step": step,
                "open": n,
                "avg_days": round(float(avg_days or 0), 1),
                "max_days": max_days or 0,
                "sites": len(where),
                "drill": {
                    "kind": "sites",
                    "filter": "ids",
                    "ids": ",".join(map(str, sorted(where))),
                },
            }
        )
    snag_rows = [
        {
            "id": s.site_id,
            "code": code,
            "name": name,
            "open": s.open_snags,
            "closed": s.closed_snags,
            "close_days": s.snag_close_days,
            "link": f"/snags?site_id={s.site_id}",
        }
        for s, code, name in summaries(db, principal, scope, f)
        if s.open_snags or s.closed_snags
    ]
    closed = [r for r in snag_rows if r["close_days"] is not None]
    avg_close = (
        round(
            sum(float(r["close_days"]) * r["closed"] for r in closed)
            / max(1, sum(r["closed"] for r in closed)),
            1,
        )
        if closed
        else None
    )
    return {
        "as_of": settings(db).refreshed_at,
        "summary": {
            "sites": len(rows),
            "delayed": sum(1 for s, _, _ in rows if s.delayed),
            "open_snags": sum(r["open"] for r in snag_rows),
            "avg_close_days": avg_close,
            "threshold": settings(db).delay_threshold_points,
        },
        "tables": {
            "scatter": table(
                "Progress vs time elapsed",
                [
                    col("code", "Site"),
                    col("elapsed", "Time gone %", "pct"),
                    col("progress", "Progress %", "pct"),
                    col("delayed", "Delayed", "bool"),
                ],
                scatter,
            ),
            "forecast": table(
                "Planned vs forecast end",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("start", "Start", "date"),
                    col("target", "Planned end", "date"),
                    col("forecast", "Forecast end"),
                    col("slip_days", "Slip (days)", "count"),
                    col("progress", "Progress %", "pct"),
                    col("rate", "% per day (30 d)", "num"),
                    col("delay", "Delay"),
                ],
                forecast,
                "Forecast = today + remaining % / the progress rate of the last 30 days; it needs 14 days of history and more than 0.05 % a day.",
            ),
            "bottlenecks": table(
                "Stage bottlenecks: steps open longest",
                [
                    col("step", "Step"),
                    col("open", "Open", "count"),
                    col("sites", "Sites", "count"),
                    col("avg_days", "Avg days open", "num"),
                    col("max_days", "Longest (days)", "count"),
                ],
                stuck,
            ),
            "snags": table(
                "Snags by site",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("open", "Open", "count"),
                    col("closed", "Closed", "count"),
                    col("close_days", "Avg days to close", "num"),
                ],
                snag_rows,
            ),
        },
    }


# --- finance -------------------------------------------------------------------------------------


def _monthly(db: Session, f: Filters, site_ids=None):
    q = select(
        MonthlySummary.month,
        func.sum(MonthlySummary.billed),
        func.sum(MonthlySummary.received),
        func.sum(MonthlySummary.cost),
        func.sum(MonthlySummary.salary_cost),
        func.sum(MonthlySummary.invoiced),
        func.sum(MonthlySummary.credited),
        func.sum(MonthlySummary.settled),
        func.sum(MonthlySummary.man_days),
        func.sum(MonthlySummary.labour_cost),
        func.sum(MonthlySummary.marked),
    ).where(MonthlySummary.is_demo == f.demo)
    if site_ids is not None:
        q = q.where(MonthlySummary.site_id.in_(site_ids or [0]))
    return {
        m: [Decimal(v or 0) for v in rest]
        for m, *rest in db.execute(q.group_by(MonthlySummary.month))
    }


def finance_page(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    day = today()
    cost_ok, salary_ok = sees_cost(principal), sees_salary(principal)
    data = _monthly(db, f)
    monthly = []
    for m in months(f.date_from, f.date_to):
        b, r, c, sal, *_ = data.get(m, [ZERO] * 10)
        row = {
            "month": f"{m:%Y-%m}",
            "label": f"{m:%b %y}",
            "billed": money(b),
            "received": money(r),
            "drill": {"kind": "invoices", "filter": "month", "month": str(m)},
        }
        if cost_ok:
            row["cost"] = money(c + (sal if salary_ok else ZERO))
        monthly.append(row)
    # cash flow: the next 8 weeks from Monday
    week0 = day - timedelta(days=day.weekday())
    weeks = [{"week": "overdue", "label": "Overdue", "receipts": ZERO, "payments": ZERO}] + [
        {
            "week": str(week0 + timedelta(weeks=i)),
            "label": f"{week0 + timedelta(weeks=i):%d %b}",
            "receipts": ZERO,
            "payments": ZERO,
        }
        for i in range(8)
    ]

    def slot(d: date | None):
        if d is None or d < day:
            return 0
        i = (d - week0).days // 7
        return i + 1 if i < 8 else None

    for due_date, inv_date, due in db.execute(
        select(InvoiceSummary.due_date, InvoiceSummary.invoice_date, InvoiceSummary.due).where(
            InvoiceSummary.is_demo == f.demo, InvoiceSummary.due > 0
        )
    ):
        i = slot(due_date or inv_date + timedelta(days=30))
        if i is not None:
            weeks[i]["receipts"] += Decimal(due)
    for b, bal in vendor_balances(db, f.demo):
        i = slot(b.due_date)
        if i is not None:
            weeks[i]["payments"] += bal
    for w in weeks:
        w["receipts"], w["payments"] = money(w["receipts"]), money(w["payments"])
        w["net"] = money(w["receipts"] - w["payments"])
    # DSO: receivable at month end / invoiced in the 90 days to it x 90
    all_months = sorted(data)
    dso, ar = [], ZERO
    for m in months(min(all_months[0], f.date_from) if all_months else f.date_from, f.date_to):
        _b, _r, _c, _s, invoiced, credited, settled, *_ = data.get(m, [ZERO] * 10)
        ar += invoiced - credited - settled
        if m >= f.date_from.replace(day=1):
            last3 = sum((data.get(add_months(m, -k), [ZERO] * 10)[4] for k in range(3)), ZERO)
            dso.append(
                {
                    "month": f"{m:%Y-%m}",
                    "label": f"{m:%b %y}",
                    "receivable": money(ar),
                    "dso": round(float(ar / last3 * 90), 0) if last3 > 0 else None,
                }
            )
    clients = dict(db.execute(select(Client.id, Client.name)).all())
    by_client = [
        {
            "client_id": cid,
            "client": clients.get(cid),
            "outstanding": money(o),
            "due": money(d),
            "retention": money(r),
            "drill": {"kind": "invoices", "filter": "outstanding", "client_id": cid},
        }
        for cid, o, d, r in db.execute(
            select(
                InvoiceSummary.client_id,
                func.sum(InvoiceSummary.outstanding),
                func.sum(InvoiceSummary.due),
                func.sum(InvoiceSummary.retention_held),
            )
            .where(InvoiceSummary.is_demo == f.demo, InvoiceSummary.outstanding > 0)
            .group_by(InvoiceSummary.client_id)
            .order_by(func.sum(InvoiceSummary.outstanding).desc())
        )
    ]
    cols = [
        col("label", "Month"),
        col("billed", "Billed (net of GST)", "inr"),
        col("received", "Received", "inr"),
    ]
    if cost_ok:
        cols.append(col("cost", "Cost" + ("" if salary_ok else " (without staff salary)"), "inr"))
    return {
        "as_of": settings(db).refreshed_at,
        "cost_shown": cost_ok,
        "tables": {
            "monthly": table("Billed vs received vs cost by month", cols, monthly),
            "cashflow": table(
                "Cash flow, next 8 weeks",
                [
                    col("label", "Week of"),
                    col("receipts", "Expected receipts", "inr"),
                    col("payments", "Supplier payments due", "inr"),
                    col("net", "Net", "inr"),
                ],
                weeks,
                "Receipts: the due part (retention excluded) of invoices by due date; payments: approved supplier bills by due date.",
            ),
            "dso": table(
                "Days sales outstanding",
                [
                    col("label", "Month"),
                    col("receivable", "Receivable at month end", "inr"),
                    col("dso", "DSO (days)", "num"),
                ],
                dso,
                "DSO = receivable at month end / invoiced in the last 3 months x 90.",
            ),
            "clients": table(
                "Outstanding by client",
                [
                    col("client", "Client"),
                    col("outstanding", "Outstanding", "inr"),
                    col("due", "Due now", "inr"),
                    col("retention", "Retention in it", "inr"),
                ],
                by_client,
            ),
        },
    }


# --- profitability -------------------------------------------------------------------------------


def profitability_page(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    salary_ok = sees_salary(principal)
    rows = summaries(db, principal, scope, f)
    users = dict(db.execute(select(User.id, User.full_name)).all())
    clients = dict(db.execute(select(Client.id, Client.name)).all())
    systems = dict(db.execute(select(System.id, System.name)).all())

    def cost(s):
        return Decimal(s.cost) + (Decimal(s.salary_cost) if salary_ok else ZERO)

    by_site, groups = (
        [],
        {
            "client": defaultdict(lambda: [ZERO, ZERO, 0]),
            "system": defaultdict(lambda: [ZERO, ZERO, 0]),
            "salesperson": defaultdict(lambda: [ZERO, ZERO, 0]),
        },
    )
    finished = []
    for s, code, name in rows:
        if s.historic or (not Decimal(s.billed) and not cost(s)):
            continue
        c, b = cost(s), Decimal(s.billed)
        margin = pct(b - c, b)
        by_site.append(
            {
                "id": s.site_id,
                "code": code,
                "name": name,
                "billed": s.billed,
                "cost": money(c),
                "profit": money(b - c),
                "margin": margin,
                "quoted_margin": s.tender_margin,
                "link": f"/sites/{s.site_id}",
            }
        )
        for key, value in (
            ("client", clients.get(s.client_id, "No client")),
            ("system", systems.get(s.system_id, "unspecified")),
            ("salesperson", users.get(s.salesperson_id, "unassigned")),
        ):
            g = groups[key][value]
            g[0] += b
            g[1] += c
            g[2] += 1
        if s.status in ("completed", "closed") and b > 0:
            budget = {k: Decimal(v) for k, v in (s.budget_heads or {}).items()}
            heads = {k: Decimal(v) for k, v in (s.cost_heads or {}).items()}
            over = sorted(
                ((k, heads.get(k, ZERO) - v) for k, v in budget.items() if heads.get(k, ZERO) > v),
                key=lambda x: -x[1],
            )
            finished.append(
                {
                    "id": s.site_id,
                    "code": code,
                    "name": name,
                    "quoted_margin": s.tender_margin,
                    "actual_margin": margin,
                    "gap": (margin - s.tender_margin)
                    if margin is not None and s.tender_margin is not None
                    else None,
                    "overruns": ", ".join(f"{k} +{money(v):,.0f}" for k, v in over[:3]) or "—",
                    "link": f"/sites/{s.site_id}",
                }
            )
    by_site.sort(key=lambda r: (r["margin"] is None, r["margin"]))
    finished.sort(key=lambda r: (r["gap"] is None, r["gap"]))

    def group_table(key, label):
        out = [
            {"key": k, "sites": n, "billed": money(b), "cost": money(c), "margin": pct(b - c, b)}
            for k, (b, c, n) in groups[key].items()
        ]
        out.sort(key=lambda r: -r["billed"])
        return table(
            f"Margin by {label}",
            [
                col("key", label.capitalize()),
                col("sites", "Sites", "count"),
                col("billed", "Billed", "inr"),
                col("cost", "Cost", "inr"),
                col("margin", "Margin %", "pct"),
            ],
            out,
        )

    note = None if salary_ok else "Staff salary is not included (needs payroll.view)."
    return {
        "as_of": settings(db).refreshed_at,
        "salary_included": salary_ok,
        "tables": {
            "sites": table(
                "Margin by site",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("billed", "Billed", "inr"),
                    col("cost", "Cost", "inr"),
                    col("profit", "Gross profit", "inr"),
                    col("margin", "Margin %", "pct"),
                    col("quoted_margin", "Quoted margin %", "pct"),
                ],
                by_site,
                note,
            ),
            "clients": group_table("client", "client"),
            "systems": group_table("system", "system"),
            "salespeople": group_table("salesperson", "salesperson"),
            "quoted_vs_actual": table(
                "Quoted vs actual margin, finished sites",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("quoted_margin", "Quoted %", "pct"),
                    col("actual_margin", "Actual %", "pct"),
                    col("gap", "Gap (points)", "pct"),
                    col("overruns", "Heads over budget"),
                ],
                finished,
                "Quoted margin: from the won tender's costed BOQ lines. A site's system is the one with the largest quoted amount.",
            ),
        },
    }


# --- purchase ------------------------------------------------------------------------------------


def purchase_page(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    base = (
        select(PoLine, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.status.in_(PO_COUNTED),
            PurchaseOrder.po_date.between(f.date_from, f.date_to),
            Vendor.is_demo == f.demo,
        )
    )
    vendors = dict(db.execute(select(Vendor.id, Vendor.name)).all())
    products = {p.id: p for p in db.scalars(select(Product))}
    cats = dict(db.execute(select(Category.id, Category.name)).all())
    by_vendor, by_cat, by_product = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    trend: dict[int, dict[date, list[Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: [ZERO, ZERO])
    )
    for line, po in db.execute(base):
        amount = Decimal(line.amount)
        by_vendor[po.vendor_id] += amount
        p = products.get(line.product_id)
        by_cat[cats.get(p.category_id, "Uncategorised") if p else "Uncategorised"] += amount
        by_product[line.product_id] += amount
        t = trend[line.product_id][po.po_date.replace(day=1)]
        t[0] += amount
        t[1] += Decimal(line.qty)
    top = sorted(by_product, key=lambda k: -by_product[k])[:20]
    month_list = months(f.date_from, f.date_to)
    price_rows = []
    for pid in top:
        p = products.get(pid)
        row = {
            "product_id": pid,
            "product": p.name if p else str(pid),
            "unit": p.unit if p else "",
            "spend": money(by_product[pid]),
        }
        for m in month_list:
            a, q = trend[pid].get(m, [ZERO, ZERO])
            row[f"{m:%Y-%m}"] = money(a / q) if q else None
        price_rows.append(row)
    freight = []
    for s, code, name in summaries(db, principal, scope, f):
        if Decimal(s.material_value) > 0 or Decimal(s.freight) > 0:
            freight.append(
                {
                    "id": s.site_id,
                    "code": code,
                    "name": name,
                    "material": s.material_value,
                    "freight": s.freight,
                    "percent": pct(s.freight, s.material_value),
                    "link": f"/sites/{s.site_id}",
                }
            )
    freight.sort(key=lambda r: -(r["percent"] or 0))
    cost_ok = sees_cost(principal)
    return {
        "as_of": settings(db).refreshed_at,
        "tables": {
            "vendors": table(
                "Spend by supplier (PO value before GST)",
                [col("vendor", "Supplier"), col("spend", "Spend", "inr")],
                [
                    {"vendor_id": k, "vendor": vendors.get(k), "spend": money(v)}
                    for k, v in sorted(by_vendor.items(), key=lambda kv: -kv[1])
                ],
            ),
            "categories": table(
                "Spend by product category",
                [col("category", "Category"), col("spend", "Spend", "inr")],
                [
                    {"category": k, "spend": money(v)}
                    for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
                ],
            ),
            "prices": table(
                "PO rate trend, top 20 products by spend",
                [col("product", "Product"), col("unit", "Unit"), col("spend", "Spend", "inr")]
                + [col(f"{m:%Y-%m}", f"{m:%b %y}", "inr") for m in month_list],
                price_rows,
                "Average PO rate after discount, per month.",
            ),
            "freight": table(
                "Freight as % of material used, per site",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("material", "Material used", "inr"),
                    col("freight", "Freight", "inr"),
                    col("percent", "Freight %", "pct"),
                ],
                freight if cost_ok else [],
                None if cost_ok else "Needs tender.margin (it shows cost).",
            ),
        },
    }


# --- labour --------------------------------------------------------------------------------------


def labour_page(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    rows = summaries(db, principal, scope, f)
    ids = [s.site_id for s, _, _ in rows]
    codes = {s.site_id: code for s, code, _ in rows}
    month_list = months(f.date_from, f.date_to)
    per: dict[int, dict[date, Decimal]] = defaultdict(dict)
    marked: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for site_id, m, md, n in db.execute(
        select(
            MonthlySummary.site_id,
            MonthlySummary.month,
            MonthlySummary.man_days,
            MonthlySummary.marked,
        ).where(
            MonthlySummary.site_id.in_(ids or [0]),
            MonthlySummary.is_demo == f.demo,
            MonthlySummary.month.between(f.date_from.replace(day=1), f.date_to),
        )
    ):
        if Decimal(md) or n:
            per[site_id][m] = Decimal(md)
            marked[site_id][0] += Decimal(md)
            marked[site_id][1] += n
    man_days = []
    for sid in sorted(per, key=lambda k: -sum(per[k].values())):
        row = {
            "id": sid,
            "code": codes.get(sid),
            "total": sum(per[sid].values(), ZERO),
            "link": f"/sites/{sid}",
        }
        for m in month_list:
            row[f"{m:%Y-%m}"] = per[sid].get(m)
        man_days.append(row)
    rates = [
        {
            "id": sid,
            "code": codes.get(sid),
            "man_days": md,
            "marked": n,
            "rate": pct(md, n),
            "link": f"/sites/{sid}",
        }
        for sid, (md, n) in marked.items()
        if n
    ]
    rates.sort(key=lambda r: r["rate"] or 0)
    cost_ok = sees_cost(principal)
    per_sqm = []
    if cost_ok:
        for s, code, name in rows:
            if Decimal(s.area_done) > 0 and Decimal(s.labour_cost) > 0:
                per_sqm.append(
                    {
                        "id": s.site_id,
                        "code": code,
                        "name": name,
                        "labour_cost": s.labour_cost,
                        "area": s.area_done,
                        "per_sqm": money(Decimal(s.labour_cost) / Decimal(s.area_done)),
                        "link": f"/sites/{s.site_id}",
                    }
                )
        per_sqm.sort(key=lambda r: -r["per_sqm"])
    totals = {
        f"{m:%Y-%m}": sum((r.get(f"{m:%Y-%m}") or ZERO for r in man_days), ZERO) for m in month_list
    }
    return {
        "as_of": settings(db).refreshed_at,
        "tables": {
            "man_days": table(
                "Man-days per site per month",
                [col("code", "Site"), col("total", "Total", "num")]
                + [col(f"{m:%Y-%m}", f"{m:%b %y}", "num") for m in month_list],
                man_days,
                "A half day counts 0.5. Own labour and subcontractor labour on the muster roll.",
            ),
            "monthly": table(
                "Man-days per month, all sites",
                [col("label", "Month"), col("man_days", "Man-days", "num")],
                [{"label": f"{m:%b %y}", "man_days": totals[f"{m:%Y-%m}"]} for m in month_list],
            ),
            "per_sqm": table(
                "Labour cost per sqm done",
                [
                    col("code", "Site"),
                    col("name", "Name"),
                    col("labour_cost", "Labour cost", "inr"),
                    col("area", "Area done (sqm)", "num"),
                    col("per_sqm", "₹ per sqm", "inr"),
                ],
                per_sqm,
                "Labour cost: muster-roll wages plus verified subcontract measurements; area: sqm scopes x their progress."
                if cost_ok
                else "Needs tender.margin (it shows cost).",
            ),
            "attendance": table(
                "Attendance rate",
                [
                    col("code", "Site"),
                    col("man_days", "Man-days", "num"),
                    col("marked", "Marked", "count"),
                    col("rate", "Rate %", "pct"),
                ],
                rates,
                "Man-days / attendance rows marked (present 1, half day 0.5, absent 0).",
            ),
        },
    }


__all__ = ["month_end"]
