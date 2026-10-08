"""The records behind a number: every dashboard tile and chart point links to one of these lists
(/drill?kind=...&filter=...), which shows the rows and links each one to its page."""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.common import (
    OPEN_LEAD,
    ZERO,
    Filters,
    month_end,
    need_any,
    pct,
    quarter_start,
    sees_cost,
    sees_salary,
    today,
)
from app.analytics.kpi import dpr_missing_today, first_submitted, stock_levels, vendor_balances
from app.analytics.models import InvoiceSummary, SiteSummary
from app.auth.deps import Principal
from app.crm.models import Lead
from app.finance.models import PettyCashAccount, PettyCashEntry, RaBill, Receipt, TaxInvoice
from app.masters.models import Client, Vendor
from app.material import service as material
from app.material.models import Grn, Indent, PurchaseOrder
from app.models import User
from app.sites.models import Site
from app.tenders.models import Tender

COMPANY = "dashboard.company"
NEEDS = {
    "invoices": (COMPANY, "dashboard.finance"),
    "receipts": (COMPANY, "dashboard.finance"),
    "ra_bills": (COMPANY, "dashboard.finance"),
    "vendor_bills": (COMPANY, "dashboard.finance"),
    "petty": (COMPANY, "dashboard.finance"),
    "tenders": (COMPANY, "dashboard.sales"),
    "leads": (COMPANY, "dashboard.sales"),
    "sites": (COMPANY, "dashboard.site", "dashboard.finance"),
    "indents": (COMPANY, "dashboard.purchase"),
    "pos": (COMPANY, "dashboard.purchase"),
    "products": (COMPANY, "dashboard.purchase"),
    "grns": (COMPANY, "dashboard.purchase"),
}


def col(key, label, unit="text"):
    return {"key": key, "label": label, "unit": unit}


def _month(value: str | None) -> tuple[date, date]:
    m = date.fromisoformat(value) if value else today().replace(day=1)
    return m, min(month_end(m), today()) if m <= today() else month_end(m)


def drill(db: Session, principal: Principal, kind: str, f: Filters, args: dict) -> dict:
    if kind not in NEEDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown list")
    scope = need_any(principal, *NEEDS[kind])
    fn = globals()[f"_{kind}"]
    title, columns, rows = fn(db, principal, scope, f, args)
    return {
        "kind": kind,
        "filter": args.get("filter"),
        "title": title,
        "columns": columns,
        "rows": rows,
        "total": len(rows),
    }


# --- money ---------------------------------------------------------------------------------------


def _invoices(db, principal, scope, f: Filters, a: dict):
    flt = a.get("filter")
    day = today()
    names = dict(db.execute(select(Client.id, Client.name)).all())
    codes = dict(db.execute(select(Site.id, Site.code)).all())
    if flt == "month":
        start, end = _month(a.get("month"))
        q = (
            select(TaxInvoice)
            .join(Client, Client.id == TaxInvoice.client_id)
            .where(
                TaxInvoice.status == "issued",
                TaxInvoice.invoice_date.between(start, end),
                Client.is_demo == f.demo,
            )
            .order_by(TaxInvoice.invoice_date)
        )
        rows = [
            {
                "id": i.id,
                "number": i.number,
                "kind": i.kind.replace("_", " "),
                "date": i.invoice_date,
                "client": names.get(i.client_id),
                "site": codes.get(i.site_id),
                "taxable": i.taxable if i.kind == "invoice" else -Decimal(i.taxable),
                "total": i.total,
                "link": f"/billing?invoice={i.id}",
            }
            for i in db.scalars(q)
        ]
        cols = [
            col("number", "Invoice"),
            col("kind", "Kind"),
            col("date", "Date", "date"),
            col("client", "Client"),
            col("site", "Site"),
            col("taxable", "Taxable (net of GST)", "inr"),
            col("total", "Total", "inr"),
        ]
        return f"Invoices {start:%b %Y}", cols, rows
    q = (
        select(InvoiceSummary, TaxInvoice.number)
        .join(TaxInvoice, TaxInvoice.id == InvoiceSummary.invoice_id)
        .where(InvoiceSummary.is_demo == f.demo, InvoiceSummary.outstanding > 0)
    )
    title = "Invoices with money outstanding"
    if flt == "overdue":
        days = int(a.get("days") or 60)
        q = q.where(
            InvoiceSummary.invoice_date < day - timedelta(days=days), InvoiceSummary.due > 0
        )
        title = f"Invoices overdue over {days} days (due part, retention excluded)"
    elif flt == "bucket":
        lo, hi = {"0-30": (0, 30), "31-60": (31, 60), "61-90": (61, 90), "90+": (91, 100000)}[
            a.get("bucket", "0-30")
        ]
        q = q.where(
            InvoiceSummary.invoice_date.between(day - timedelta(days=hi), day - timedelta(days=lo)),
            InvoiceSummary.due > 0,
        )
        title = f"Invoices {a.get('bucket')} days old with money due"
    if a.get("client_id"):
        q = q.where(InvoiceSummary.client_id == int(a["client_id"]))
        title += f" · {names.get(int(a['client_id']))}"
    if a.get("site_id"):
        q = q.where(InvoiceSummary.site_id == int(a["site_id"]))
    rows = [
        {
            "id": s.invoice_id,
            "number": number,
            "date": s.invoice_date,
            "due_date": s.due_date,
            "client": names.get(s.client_id),
            "site": codes.get(s.site_id),
            "total": s.total,
            "outstanding": s.outstanding,
            "retention": s.retention_held,
            "due": s.due,
            "age": (day - s.invoice_date).days,
            "link": f"/billing?invoice={s.invoice_id}",
        }
        for s, number in db.execute(q.order_by(InvoiceSummary.invoice_date))
    ]
    cols = [
        col("number", "Invoice"),
        col("date", "Date", "date"),
        col("due_date", "Due", "date"),
        col("client", "Client"),
        col("site", "Site"),
        col("total", "Total", "inr"),
        col("outstanding", "Outstanding", "inr"),
        col("retention", "Retention in it", "inr"),
        col("due", "Due now", "inr"),
        col("age", "Age (days)", "count"),
    ]
    return title, cols, rows


def _receipts(db, principal, scope, f: Filters, a: dict):
    start, end = _month(a.get("month"))
    q = (
        select(Receipt, Client.name)
        .join(Client, Client.id == Receipt.client_id)
        .where(Receipt.on_date.between(start, end), Client.is_demo == f.demo)
        .order_by(Receipt.on_date)
    )
    rows = [
        {
            "id": r.id,
            "number": r.number,
            "date": r.on_date,
            "client": name,
            "mode": r.mode.upper(),
            "amount": r.amount,
            "tds": r.tds_amount,
            "link": "/billing?tab=receipts",
        }
        for r, name in db.execute(q)
    ]
    return (
        f"Receipts {start:%b %Y}",
        [
            col("number", "Receipt"),
            col("date", "Date", "date"),
            col("client", "Client"),
            col("mode", "Mode"),
            col("amount", "Received", "inr"),
            col("tds", "TDS", "inr"),
        ],
        rows,
    )


def _ra_bills(db, principal, scope, f: Filters, a: dict):
    q = (
        select(RaBill, Site.code)
        .join(Site, Site.id == RaBill.site_id)
        .where(RaBill.status == "certified", Site.is_demo == f.demo)
        .order_by(RaBill.certified_at)
    )
    rows = [
        {
            "id": b.id,
            "code": b.code,
            "site": code,
            "certified_at": b.certified_at,
            "certified": b.certified_gross,
            "link": f"/sites/{b.site_id}?tab=finance",
        }
        for b, code in db.execute(q)
    ]
    return (
        "Certified RA bills not invoiced yet",
        [
            col("code", "RA bill"),
            col("site", "Site"),
            col("certified_at", "Certified", "date"),
            col("certified", "Certified gross", "inr"),
        ],
        rows,
    )


def _vendor_bills(db, principal, scope, f: Filters, a: dict):
    day, flt = today(), a.get("filter")
    names = dict(db.execute(select(Vendor.id, Vendor.name)).all())
    bills = vendor_balances(db, f.demo)
    if flt == "due_week":
        bills, title = (
            [x for x in bills if day <= x[0].due_date <= day + timedelta(days=7)],
            "Supplier bills due this week",
        )
    elif flt == "overdue":
        bills, title = [x for x in bills if x[0].due_date < day], "Supplier bills overdue"
    else:
        bills, title = (
            [x for x in bills if x[0].due_date <= day + timedelta(days=7)],
            "Supplier bills due in 7 days (incl. overdue)",
        )
    rows = [
        {
            "id": b.id,
            "number": b.number,
            "bill_no": b.bill_no,
            "vendor": names.get(b.vendor_id),
            "due_date": b.due_date,
            "balance": bal,
            "overdue": b.due_date < day,
            "link": "/payables",
        }
        for b, bal in sorted(bills, key=lambda x: x[0].due_date)
    ]
    return (
        title,
        [
            col("number", "Bill"),
            col("bill_no", "Supplier's no."),
            col("vendor", "Supplier"),
            col("due_date", "Due", "date"),
            col("balance", "To pay", "inr"),
        ],
        rows,
    )


def _petty(db, principal, scope, f: Filters, a: dict):
    q = (
        select(PettyCashEntry, User.full_name)
        .join(PettyCashAccount, PettyCashAccount.id == PettyCashEntry.account_id)
        .join(User, User.id == PettyCashAccount.user_id)
        .where(PettyCashEntry.status == "submitted", User.is_demo == f.demo)
        .order_by(PettyCashEntry.on_date)
    )
    rows = [
        {
            "id": e.id,
            "number": e.number,
            "date": e.on_date,
            "by": name,
            "kind": e.kind,
            "amount": e.amount,
            "link": "/petty-cash",
        }
        for e, name in db.execute(q)
    ]
    return (
        "Petty cash awaiting approval",
        [
            col("number", "Entry"),
            col("date", "Date", "date"),
            col("by", "Holder"),
            col("kind", "Kind"),
            col("amount", "Amount", "inr"),
        ],
        rows,
    )


# --- sales ---------------------------------------------------------------------------------------


def _tenders(db, principal, scope, f: Filters, a: dict):
    flt, day = a.get("filter"), today()
    q = select(Tender).where(Tender.is_demo == f.demo)
    if scope == "own" or a.get("owner") == "me":
        q = q.where(Tender.owner_id == principal.user.id)
    decided = func.date(func.timezone("Asia/Kolkata", Tender.decided_at))
    title = "Tenders"
    if flt == "won_month":
        start, end = _month(a.get("month"))
        q, title = (
            q.where(Tender.status == "won", decided.between(start, end)),
            f"Tenders won in {start:%b %Y}",
        )
    elif flt == "submitted_month":
        start, end = _month(a.get("month"))
        fs = first_submitted()
        q = q.join(fs, fs.c.tender_id == Tender.id).where(
            func.date(func.timezone("Asia/Kolkata", fs.c.at)).between(start, end)
        )
        title = f"Tenders first submitted in {start:%b %Y}"
    elif flt == "due_week":
        q, title = (
            q.where(Tender.status == "draft", Tender.due_on.between(day, day + timedelta(days=7))),
            "Tenders due this week",
        )
    elif flt == "status":
        q, title = q.where(Tender.status == a.get("status")), f"Tenders: {a.get('status')}"
    elif flt == "decided_quarter":
        q = q.where(Tender.status.in_(("won", "lost")), decided >= quarter_start(day))
        title = f"Tenders won or lost since {quarter_start(day):%d %b}"
    elif flt == "segment":  # from the strategy pages
        from app.analytics.strategy import tender_rows

        by = "decided" if a.get("decided") else "received"
        ids = [r["id"] for r in tender_rows(db, principal, scope, f, by) if _segment_match(r, a)]
        q, title = (
            q.where(Tender.id.in_(ids or [0])),
            "Tenders: "
            + ", ".join(f"{k} {v}" for k, v in a.items() if k not in ("filter", "kind")),
        )
    names = dict(db.execute(select(Client.id, Client.name)).all())
    users = dict(db.execute(select(User.id, User.full_name)).all())
    rows = [
        {
            "id": t.id,
            "code": t.code,
            "name": t.name,
            "client": names.get(t.client_id),
            "owner": users.get(t.owner_id),
            "status": t.status,
            "due_on": t.due_on,
            "quoted": t.quoted_total,
            "lost_reason": t.lost_reason,
            "lost_to": t.lost_to,
            "link": f"/tenders/{t.id}",
        }
        for t in db.scalars(q.order_by(Tender.code))
    ]
    return (
        title,
        [
            col("code", "Tender"),
            col("name", "Name"),
            col("client", "Client"),
            col("owner", "Salesperson"),
            col("status", "Status"),
            col("due_on", "Due", "date"),
            col("quoted", "Quoted", "inr"),
            col("lost_reason", "Lost reason"),
            col("lost_to", "Lost to"),
        ],
        rows,
    )


def _segment_match(row: dict, a: dict) -> bool:
    for key in (
        "status",
        "month",
        "salesperson",
        "client_type",
        "source",
        "region",
        "system",
        "band",
        "lost_reason",
        "submitted",
    ):
        if a.get(key) is not None and str(row.get(key)) != str(a[key]):
            return False
    return True


def _leads(db, principal, scope, f: Filters, a: dict):
    flt, day = a.get("filter"), today()
    q = select(Lead).where(Lead.is_demo == f.demo)
    if scope == "own" or a.get("owner") == "me":
        q = q.where(Lead.owner_id == principal.user.id)
    title = "Leads"
    if flt == "follow_today":
        q, title = (
            q.where(Lead.status.in_(OPEN_LEAD), Lead.next_follow_up == day),
            "Follow-ups due today",
        )
    elif flt == "follow_overdue":
        q, title = (
            q.where(Lead.status.in_(OPEN_LEAD), Lead.next_follow_up < day),
            "Follow-ups overdue",
        )
    elif flt == "status":
        q, title = (
            q.where(Lead.status == a.get("status")),
            f"Leads: {a.get('status', '').replace('_', ' ')}",
        )
    elif flt == "kylas_failed":
        q, title = q.where(Lead.kylas_sync_status == "failed"), "Leads that failed to sync to Kylas"
    elif flt == "segment":
        from app.analytics.strategy import lead_rows

        ids = [r["id"] for r in lead_rows(db, principal, scope, f) if _segment_match(r, a)]
        q, title = (
            q.where(Lead.id.in_(ids or [0])),
            "Leads: "
            + ", ".join(f"{k} {v}" for k, v in a.items() if k not in ("filter", "kind", "decided")),
        )
    users = dict(db.execute(select(User.id, User.full_name)).all())
    rows = [
        {
            "id": x.id,
            "code": x.code,
            "contact": x.contact_name,
            "company": x.company,
            "status": x.status,
            "owner": users.get(x.owner_id),
            "follow_up": x.next_follow_up,
            "value": x.est_value,
            "error": x.kylas_last_error if flt == "kylas_failed" else None,
            "link": f"/leads/{x.id}",
        }
        for x in db.scalars(q.order_by(Lead.next_follow_up.nulls_last(), Lead.code))
    ]
    cols = [
        col("code", "Lead"),
        col("contact", "Contact"),
        col("company", "Company"),
        col("status", "Status"),
        col("owner", "Owner"),
        col("follow_up", "Follow-up", "date"),
        col("value", "Est. value", "inr"),
    ]
    if flt == "kylas_failed":
        cols.append(col("error", "Kylas error"))
    return title, cols, rows


# --- sites ---------------------------------------------------------------------------------------


def _sites(db, principal, scope, f: Filters, a: dict):
    flt = a.get("filter")
    if flt in ("margin", "over_cost", "low_margin"):
        if not sees_cost(principal):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cost and margin need tender.margin")
    q = (
        select(SiteSummary, Site.code, Site.name)
        .join(Site, Site.id == SiteSummary.site_id)
        .where(SiteSummary.is_demo == f.demo)
    )
    if scope != "all":
        q = q.where(Site.id.in_(material.assigned_sites(principal)))
    title = "Sites"
    salary = sees_salary(principal)
    if flt == "order_book":
        q, title = (
            q.where(
                SiteSummary.status.in_(("planned", "active", "on_hold")),
                SiteSummary.contract_value.is_not(None),
            ),
            "Order book",
        )
    elif flt == "retention":
        q, title = q.where(SiteSummary.retention_held > 0), "Retention held"
    elif flt == "active":
        q, title = q.where(SiteSummary.status == "active"), "Active sites"
    elif flt == "delayed":
        q, title = q.where(SiteSummary.delayed), "Delayed sites"
    elif flt == "dpr_missing":
        ids = [s.id for s in dpr_missing_today(db, f.demo)]
        q, title = q.where(Site.id.in_(ids or [0])), "Active sites without a submitted DPR today"
    elif flt in ("margin", "low_margin"):
        q, title = (
            q.where(SiteSummary.billed > 0, SiteSummary.historic.is_(False)),
            "Margin by site",
        )
    elif flt == "over_cost":
        cost = SiteSummary.cost + (SiteSummary.salary_cost if salary else 0)
        q, title = (
            q.where(cost > SiteSummary.billed, cost > 0, SiteSummary.historic.is_(False)),
            "Sites where cost passed billed value",
        )
    elif flt == "ids":
        ids = [int(x) for x in str(a.get("ids", "")).split(",") if x.strip().isdigit()]
        q = q.where(Site.id.in_(ids or [0]))
    rows = []
    for s, code, name in db.execute(q.order_by(Site.code)):
        r = {
            "id": s.site_id,
            "code": code,
            "name": name,
            "status": s.status,
            "progress": s.progress,
            "elapsed": s.elapsed,
            "target": s.target_date,
            "forecast": s.forecast_end,
            "delay": s.delay_reason,
            "contract": s.contract_value,
            "billed": s.billed,
            "outstanding": s.outstanding,
            "retention": s.retention_held,
            "link": f"/sites/{s.site_id}",
        }
        if sees_cost(principal):
            c = Decimal(s.cost) + (Decimal(s.salary_cost) if salary else ZERO)
            r |= {"cost": c, "margin": pct(Decimal(s.billed) - c, s.billed)}
        rows.append(r)
    if flt in ("margin", "low_margin"):
        rows.sort(key=lambda r: (r["margin"] is None, r["margin"]))
    cols = [
        col("code", "Site"),
        col("name", "Name"),
        col("status", "Status"),
        col("progress", "Progress %", "pct"),
        col("elapsed", "Time gone %", "pct"),
        col("target", "Planned end", "date"),
        col("forecast", "Forecast end", "date"),
        col("delay", "Delay"),
        col("contract", "Contract", "inr"),
        col("billed", "Billed", "inr"),
        col("outstanding", "Outstanding", "inr"),
        col("retention", "Retention held", "inr"),
    ]
    if sees_cost(principal):
        cols += [col("cost", "Cost", "inr"), col("margin", "Margin %", "pct")]
    return title, cols, rows


# --- purchase ------------------------------------------------------------------------------------


def _indents(db, principal, scope, f: Filters, a: dict):
    q = (
        select(Indent, Site.code)
        .join(Site, Site.id == Indent.site_id)
        .where(Indent.status.in_(("approved", "partly_ordered")), Site.is_demo == f.demo)
        .order_by(Indent.required_by.nulls_last())
    )
    rows = [
        {
            "id": i.id,
            "code": i.code,
            "site": code,
            "required_by": i.required_by,
            "status": i.status.replace("_", " "),
            "link": "/indents",
        }
        for i, code in db.execute(q)
    ]
    return (
        "Indents awaiting a PO",
        [
            col("code", "Indent"),
            col("site", "Site"),
            col("required_by", "Needed by", "date"),
            col("status", "Status"),
        ],
        rows,
    )


def _pos(db, principal, scope, f: Filters, a: dict):
    day = today()
    q = (
        select(PurchaseOrder, Vendor.name)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.status.in_(("approved", "sent", "partly_received")),
            Vendor.is_demo == f.demo,
        )
        .order_by(PurchaseOrder.expected_delivery.nulls_last())
    )
    if a.get("filter") == "late":
        q = q.where(PurchaseOrder.expected_delivery < day)
    rows = [
        {
            "id": p.id,
            "code": p.code,
            "vendor": name,
            "po_date": p.po_date,
            "expected": p.expected_delivery,
            "late": bool(p.expected_delivery and p.expected_delivery < day),
            "total": p.grand_total,
            "status": p.status.replace("_", " "),
            "link": f"/purchase-orders/{p.id}",
        }
        for p, name in db.execute(q)
    ]
    return (
        "POs late" if a.get("filter") == "late" else "POs awaiting delivery",
        [
            col("code", "PO"),
            col("vendor", "Supplier"),
            col("po_date", "Date", "date"),
            col("expected", "Expected", "date"),
            col("status", "Status"),
            col("total", "Value", "inr"),
        ],
        rows,
    )


def _products(db, principal, scope, f: Filters, a: dict):
    rows = [
        r | {"id": r["product_id"], "link": "/products"}
        for r in stock_levels(db, f.demo)
        if r["low"]
    ]
    return (
        "Products below their reorder level",
        [
            col("code", "Code"),
            col("name", "Product"),
            col("unit", "Unit"),
            col("stock", "Stock", "qty"),
            col("reorder_level", "Reorder level", "qty"),
        ],
        rows,
    )


def _grns(db, principal, scope, f: Filters, a: dict):
    q = (
        select(Grn, Vendor.name)
        .join(Vendor, Vendor.id == Grn.vendor_id)
        .where(Grn.status == "submitted", Vendor.is_demo == f.demo)
        .order_by(Grn.received_at)
    )
    rows = [
        {"id": g.id, "code": g.code, "vendor": name, "received": g.received_at, "link": "/grns"}
        for g, name in db.execute(q)
    ]
    return (
        "GRNs awaiting approval",
        [col("code", "GRN"), col("vendor", "Supplier"), col("received", "Received", "date")],
        rows,
    )
