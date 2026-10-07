"""Execution rules: access, local dates, the DPR's pulled-in activity, the muster roll, work-order
money, and budget vs actual.

Budget "actual so far" per head:
  material     site issues at value, less returns, plus transfer shortages written off in the
               site's store (the 'shortage' ledger entries, at value)
  labour       the muster roll's wage due for the site's own labour (days x wage + OT hours x OT
               rate); subcontractor labour is paid through its work order, so it is not counted
               twice
  subcontract  verified measurements x the work-order line rate
  equipment    equipment usage amounts (hours or days x rate, plus fuel)
  freight      the site's freight entries (PO freight as GRNs arrive, transfers, bills)
  other        costs entered by hand (site_costs), under any head
  (approved petty cash expenses are added to the head of their category, mostly other)
"""

import calendar
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import Date as SqlDate
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.execution.models import (
    BUDGET_HEADS,
    Attendance,
    EquipmentUsage,
    Labour,
    SiteCost,
    WoLine,
    WoMeasurement,
    WorkOrder,
)
from app.masters.models import System
from app.material import service as material
from app.material.models import (
    FreightEntry,
    Grn,
    SiteIssue,
    SiteIssueLine,
    StockLedger,
    Store,
    Transfer,
)
from app.models import AuditLog
from app.sites.models import Site, SiteNode, Task, TaskPhoto
from app.tenders.models import BoqLine

IST = ZoneInfo("Asia/Kolkata")
DPR_DUE = time(20, 0)  # a DPR is missing when it is not in by 8 pm
ZERO = Decimal(0)
CENT = Decimal("0.01")


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, ROUND_HALF_UP)


def today() -> date:
    return datetime.now(IST).date()


def now() -> datetime:
    return datetime.now(UTC)


def local_date(col):
    """A timestamptz column as a date in India."""
    return cast(func.timezone("Asia/Kolkata", col), SqlDate)


# --- access --------------------------------------------------------------------------------------


def scope_of(principal: Principal, *codes: str) -> str | None:
    from app.auth.rbac import widest

    out = None
    for c in codes:
        out = widest(out, principal.permissions.get(c))
    return out


def site_for(db: Session, site_id: int, principal: Principal, view: str, edit: str | None = None):
    """The site, or 404 when the caller cannot see it under `view` (any of the comma-separated
    codes); 403 when `edit` is asked and not held for this site."""
    site = db.get(Site, site_id)
    scope = scope_of(principal, *view.split(","))
    if site is None or not material.covers_site(db, scope, principal, site.id, site.created_by):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    if edit and not material.covers_site(
        db, principal.permissions.get(edit), principal, site.id, site.created_by
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {edit} on {site.code}")
    return site


def need(principal: Principal, code: str) -> str:
    scope = principal.permissions.get(code)
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {code}")
    return scope


def unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


def aadhaar_last4(value: str | None) -> str | None:
    """Keep only the last 4 digits of whatever was typed (the full number is never stored)."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        raise ValueError("give at least the last 4 digits of the Aadhaar number")
    return digits[-4:]


def tds_default(pan: str | None) -> Decimal:
    """194C: 1 % for an individual or HUF (4th PAN letter P or H), 2 % for others."""
    if pan and len(pan) >= 4 and pan[3].upper() in ("P", "H"):
        return Decimal(1)
    return Decimal(2)


# --- DPR: the day's activity ---------------------------------------------------------------------


def _items(lines) -> str:
    return ", ".join(
        f"{ln.product.name} {Decimal(ln.qty).normalize():f} {ln.product.unit}" for ln in lines
    )


def day_activity(db: Session, site_id: int, day: date) -> dict:
    """Everything recorded on the site that day: task updates (with photos), material in and out,
    labour present and equipment used."""
    paths = {}
    nodes = list(db.scalars(select(SiteNode).where(SiteNode.site_id == site_id)))
    by_id = {n.id: n for n in nodes}

    def path(node_id):
        out, n = [], by_id.get(node_id)
        while n is not None:
            out.append(n.name)
            n = by_id.get(n.parent_id)
        return " › ".join(reversed(out))

    photos = defaultdict(list)
    for p, t_id in db.execute(
        select(TaskPhoto, TaskPhoto.task_id)
        .join(Task, Task.id == TaskPhoto.task_id)
        .where(Task.site_id == site_id, local_date(TaskPhoto.created_at) == day)
    ):
        photos[t_id].append({"id": p.id, "filename": p.filename})
    # tasks touched that day: progress posted, a photo added, certified (from the audit log), or
    # started / finished that day
    touched = select(AuditLog.after["task_id"].as_integer()).where(
        AuditLog.entity == "site",
        AuditLog.entity_id == str(site_id),
        AuditLog.action.in_(("site.task.update", "site.task.photo", "site.task.certify")),
        local_date(AuditLog.at) == day,
    )
    tasks = db.scalars(
        select(Task)
        .where(Task.site_id == site_id)
        .where(
            Task.id.in_(touched)
            | (Task.actual_start == day)
            | (Task.actual_end == day)
            | Task.id.in_(list(photos) or [0])
        )
        .order_by(Task.id)
    )
    task_rows = []
    for t in tasks:
        if t.node_id not in paths:
            paths[t.node_id] = path(t.node_id) if t.node_id else ""
        task_rows.append(
            {
                "id": t.id,
                "name": t.name,
                "where": paths[t.node_id],
                "status": t.status,
                "percent": float(t.progress_percent),
                "photos": photos.get(t.id, []),
            }
        )

    store = db.scalar(select(Store).where(Store.site_id == site_id))
    received = []
    if store is not None:
        for g in db.scalars(
            select(Grn).where(
                Grn.store_id == store.id, Grn.status == "approved", Grn.received_at == day
            )
        ):
            items = ", ".join(
                f"{ln.product.name} {Decimal(ln.accepted_qty).normalize():f} {ln.unit}"
                for ln in g.lines
                if Decimal(ln.accepted_qty) > 0
            )
            received.append({"code": g.code, "from": g.vendor.name, "items": items})
        for t in db.scalars(
            select(Transfer).where(
                Transfer.to_store_id == store.id,
                Transfer.status == "received",
                local_date(Transfer.received_at) == day,
            )
        ):
            items = ", ".join(
                f"{ln.product.name} {Decimal(ln.qty_received or 0).normalize():f} {ln.product.unit}"
                for ln in t.lines
            )
            received.append(
                {"code": t.code, "from": db.get(Store, t.from_store_id).name, "items": items}
            )
    issued = []
    for i in db.scalars(
        select(SiteIssue).where(SiteIssue.site_id == site_id, SiteIssue.issued_on == day)
    ):
        task = db.get(Task, i.task_id) if i.task_id else None
        issued.append(
            {
                "code": i.code,
                "kind": i.kind,
                "for": task.name if task else None,
                "items": _items(i.lines),
                "value": str(sum((Decimal(ln.value) for ln in i.lines), ZERO)),
            }
        )

    labour = {"present": 0, "half_day": 0, "absent": 0, "by_trade": {}, "names": []}
    for a in db.scalars(
        select(Attendance).where(Attendance.site_id == site_id, Attendance.on_date == day)
    ):
        labour[a.status] += 1
        if a.status != "absent":
            labour["by_trade"][a.labour.trade] = labour["by_trade"].get(a.labour.trade, 0) + 1
            labour["names"].append(a.labour.name)
    equipment = []
    from app.execution.models import Asset

    for u in db.scalars(
        select(EquipmentUsage).where(
            EquipmentUsage.site_id == site_id, EquipmentUsage.on_date == day
        )
    ):
        a = db.get(Asset, u.asset_id)
        equipment.append(
            {
                "asset": f"{a.code} {a.name}",
                "quantity": str(u.quantity),
                "basis": u.basis,
                "operator": u.operator,
            }
        )
    return {
        "tasks": task_rows,
        "received": received,
        "issued": issued,
        "labour": labour,
        "equipment": equipment,
    }


# --- muster roll ---------------------------------------------------------------------------------

DAY_FACTOR = {"present": Decimal(1), "half_day": Decimal("0.5"), "absent": ZERO}


def month_range(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def wage_due(a: Attendance) -> Decimal:
    return money(
        DAY_FACTOR[a.status] * Decimal(a.daily_wage)
        + Decimal(a.ot_hours) * Decimal(a.ot_rate_per_hour)
    )


def muster(
    db: Session, start: date, end: date, site_id: int | None = None, labour_id: int | None = None
) -> list[dict]:
    """Per worker (and site): days (a half day counts 0.5), OT hours and the wage due, plus a
    mark per day (P / H / A) for the Excel sheet."""
    q = select(Attendance).where(Attendance.on_date >= start, Attendance.on_date <= end)
    if site_id is not None:
        q = q.where(Attendance.site_id == site_id)
    if labour_id is not None:
        q = q.where(Attendance.labour_id == labour_id)
    rows: dict[tuple[int, int], dict] = {}
    for a in db.scalars(q.order_by(Attendance.on_date)):
        key = (a.labour_id, a.site_id)
        r = rows.setdefault(
            key,
            {
                "labour_id": a.labour_id,
                "name": a.labour.name,
                "trade": a.labour.trade,
                "type": a.labour.type,
                "site_id": a.site_id,
                "days": ZERO,
                "present": 0,
                "half_days": 0,
                "absent": 0,
                "ot_hours": ZERO,
                "wage_due": ZERO,
                "marks": {},
                "daily_wage": a.daily_wage,
            },
        )
        r["days"] += DAY_FACTOR[a.status]
        r[
            "present"
            if a.status == "present"
            else "half_days"
            if a.status == "half_day"
            else "absent"
        ] += 1
        r["ot_hours"] += Decimal(a.ot_hours)
        r["wage_due"] += wage_due(a)
        r["marks"][a.on_date.day] = {"present": "P", "half_day": "H", "absent": "A"}[a.status]
    return sorted(rows.values(), key=lambda r: (r["site_id"], r["name"]))


# --- work orders ---------------------------------------------------------------------------------


def line_progress(line: WoLine) -> dict:
    counted = [
        m for m in line.measurements if m.status in ("recorded", "verified", "pending_approval")
    ]
    verified = sum((Decimal(m.qty) for m in line.measurements if m.status == "verified"), ZERO)
    measured = sum((Decimal(m.qty) for m in counted), ZERO)
    return {
        "measured": measured,
        "verified": verified,
        "billable": money(verified * Decimal(line.rate)),
        "over": measured > Decimal(line.qty),
    }


def wo_money(wo: WorkOrder) -> dict:
    billable = sum((line_progress(ln)["billable"] for ln in wo.lines), ZERO)
    return {
        "amount": money(wo.amount),
        "retention": money(Decimal(wo.amount) * Decimal(wo.retention_percent) / 100),
        "tds": money(Decimal(wo.amount) * Decimal(wo.tds_percent) / 100),
        "billable_to_date": money(billable),
        "retention_to_date": money(billable * Decimal(wo.retention_percent) / 100),
        "tds_to_date": money(billable * Decimal(wo.tds_percent) / 100),
    }


# --- budget --------------------------------------------------------------------------------------


def tender_budget(db: Session, site: Site) -> dict[str, Decimal]:
    """Material and labour from the won tender's costed BOQ lines: labour = qty x the system's
    labour rate (lines priced from a system), material = the rest of the cost."""
    if not site.tender_id:
        return {}
    material_cost = labour = ZERO
    for ln in db.scalars(
        select(BoqLine).where(
            BoqLine.tender_id == site.tender_id,
            BoqLine.cost_rate.is_not(None),
            BoqLine.qty.is_not(None),
        )
    ):
        total = Decimal(ln.cost_rate) * Decimal(ln.qty)
        lab = ZERO
        if ln.system_id:
            system = db.get(System, ln.system_id)
            lab = min(total, Decimal(system.labour_rate) * Decimal(ln.qty)) if system else ZERO
        labour += lab
        material_cost += total - lab
    if material_cost == 0 and labour == 0:
        return {}
    return {"material": money(material_cost), "labour": money(labour)}


def actuals(db: Session, site_id: int) -> dict[str, Decimal]:
    out = dict.fromkeys(BUDGET_HEADS, ZERO)
    issued = db.execute(
        select(SiteIssue.kind, func.coalesce(func.sum(SiteIssueLine.value), 0))
        .join(SiteIssueLine, SiteIssueLine.issue_id == SiteIssue.id)
        .where(SiteIssue.site_id == site_id)
        .group_by(SiteIssue.kind)
    ).all()
    for kind, value in issued:
        out["material"] += Decimal(value) if kind == "issue" else -Decimal(value)
    shortage = db.scalar(
        select(func.coalesce(func.sum(StockLedger.value), 0))
        .join(Store, Store.id == StockLedger.store_id)
        .where(Store.site_id == site_id, StockLedger.ref_type == "shortage")
    )
    out["material"] += -Decimal(shortage)  # shortage rows are negative
    for a in db.scalars(
        select(Attendance)
        .join(Labour, Labour.id == Attendance.labour_id)
        .where(Attendance.site_id == site_id, Labour.type == "own")
    ):
        out["labour"] += wage_due(a)
    for m, rate in db.execute(
        select(WoMeasurement, WoLine.rate)
        .join(WoLine, WoLine.id == WoMeasurement.line_id)
        .join(WorkOrder, WorkOrder.id == WoLine.wo_id)
        .where(WorkOrder.site_id == site_id, WoMeasurement.status == "verified")
    ):
        out["subcontract"] += Decimal(m.qty) * Decimal(rate)
    out["equipment"] += Decimal(
        db.scalar(
            select(func.coalesce(func.sum(EquipmentUsage.amount), 0)).where(
                EquipmentUsage.site_id == site_id
            )
        )
    )
    out["freight"] += Decimal(
        db.scalar(
            select(func.coalesce(func.sum(FreightEntry.amount), 0)).where(
                FreightEntry.site_id == site_id
            )
        )
    )
    from app.finance.service import expenses_by_head  # approved petty cash expenses

    for head, amount in expenses_by_head(db, site_id).items():
        out[head] += amount
    for head, amount in db.execute(
        select(SiteCost.head, func.sum(SiteCost.amount))
        .where(SiteCost.site_id == site_id)
        .group_by(SiteCost.head)
    ):
        out[head] += Decimal(amount)
    return {k: money(v) for k, v in out.items()}


def missing_dprs(db: Session, day: date, site_ids=None) -> list[Site]:
    """Active sites without a submitted DPR for `day` (once it is past 8 pm that day)."""
    from app.execution.models import Dpr

    local_now = datetime.now(IST)
    if day > local_now.date() or (day == local_now.date() and local_now.time() < DPR_DUE):
        return []
    done = select(Dpr.site_id).where(Dpr.on_date == day, Dpr.status != "draft")
    q = select(Site).where(Site.status == "active", Site.id.not_in(done)).order_by(Site.code)
    if site_ids is not None:
        q = q.where(Site.id.in_(site_ids or [0]))
    return [s for s in db.scalars(q) if not s.start_date or s.start_date <= day]
