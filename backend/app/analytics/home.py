# ruff: noqa: E501
"""The home page (EESPL UI v1, Figma 01): four key numbers for the caller's own dashboard, each
with its last six months (the chart below switches between them), "Needs you today" from the
queues that really wait on the caller (labour claims above the measured quantity for the
director, client bills overdue, quotation follow-ups overdue), the active sites with progress,
status, billed of order (only for roles that see money) and the next step, and the site whose
building is shown in 3D. Read-only: the actions go to the existing endpoints."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.analytics import kpi
from app.analytics.common import add_months, month_end, month_start
from app.analytics.models import Alert, AlertRecipient, KpiSnapshot, SiteSummary
from app.analytics.routers import KINDS, _dashboard
from app.auth.deps import CurrentPrincipal
from app.db import DbSession
from app.execution.service import today
from app.sites import progress as progress_of

router = APIRouter(prefix="/api/home", tags=["dashboard"])
MONEY_PERMS = ("dashboard.company", "dashboard.finance", "finance.view", "billing.view", "closeout.billing")
ACTIVE = ("planned", "active", "on_hold")
MONTHS = 6


def _months(day: date) -> list[date]:
    m0 = month_start(day)
    return [add_months(m0, -i) for i in range(MONTHS - 1, -1, -1)]


def _snapshot_series(db, demo: bool, key: str, day: date, live) -> list[dict]:
    """A stock number at each month's end (the nightly snapshot), this month live."""
    out = []
    for m in _months(day):
        if m == month_start(day):
            out.append({"month": f"{m:%b}", "value": live})
            continue
        snap = db.scalar(
            select(KpiSnapshot).where(KpiSnapshot.is_demo == demo, KpiSnapshot.on_date.between(m, month_end(m))).order_by(KpiSnapshot.on_date.desc()).limit(1)
        )
        v = None
        if snap is not None:
            if key == "on_track":
                a, d = snap.data.get("active_sites"), snap.data.get("delayed_sites")
                v = None if a is None else int(a) - int(d or 0)
            else:
                raw = snap.data.get(key)
                v = None if raw is None else float(raw)
        out.append({"month": f"{m:%b}", "value": v})
    return out


def _flow_series(db, demo: bool, fn, day: date) -> list[dict]:
    return [{"month": f"{m:%b}", "value": float(fn(db, m, min(month_end(m), day), demo))} for m in _months(day)]


def _num(v) -> float | None:
    return None if v is None else float(v)


def _kpis(db, principal, demo: bool, day: date) -> tuple[list[dict], str | None]:
    kinds = [k for k, code in KINDS.items() if code in principal.permissions]
    if not kinds:
        return [], None
    kind = kinds[0]
    data = _dashboard(db, principal, kind, demo)
    tiles = {t["key"]: t for s in data.get("sections", []) for t in s.get("tiles", [])} | {t["key"]: t for t in data.get("tiles", [])}
    if kind == "company":
        stock = kpi.stock_values(db, demo)
        active, delayed = int(stock["active_sites"]), int(stock["delayed_sites"])
        won = tiles.get("won_month", {})
        out = [
            {"key": "order_value", "label": "Order book (active contracts)", "value": _num(tiles["order_value"]["value"]), "unit": "inr",
             "note": f"{won.get('note') or 'none'} won this month" if won.get("value") else "Nothing won this month yet",
             "series": _snapshot_series(db, demo, "order_book", day, _num(tiles["order_value"]["value"]))},
            {"key": "billed_month", "label": f"Billed in {day:%B} (net of GST)", "value": _num(tiles["billed_month"]["value"]), "unit": "inr",
             "note": "Tax invoices issued, less credit notes", "series": _flow_series(db, demo, kpi.billed_between, day)},
            {"key": "overdue_60", "label": "Overdue over 60 days", "value": _num(tiles["overdue_60"]["value"]), "unit": "inr",
             "note": "Client invoices past 60 days", "series": _snapshot_series(db, demo, "overdue_60", day, _num(tiles["overdue_60"]["value"]))},
            {"key": "on_track", "label": "Sites on track", "value": active - delayed, "of": active, "unit": "of",
             "note": f"{delayed} late" if delayed else "None late", "series": _snapshot_series(db, demo, "on_track", day, active - delayed)},
        ]  # fmt: skip
        return out, kind
    if kind == "site":  # the supervisor's own sites: no money
        sites = data.get("sites", [])
        todo = sum(1 for s in sites for t in s.get("todos", []) if t.get("key") == "dpr" and not t.get("done"))
        snags = sum(int(s.get("open_snags") or 0) for s in sites)
        avg = round(sum(float(s.get("progress") or 0) for s in sites) / len(sites)) if sites else 0
        return [
            {"key": "my_sites", "label": "My active sites", "value": len(sites), "unit": "count", "note": "Where I am the in-charge or a member", "series": []},
            {"key": "my_progress", "label": "Average progress", "value": avg, "unit": "pct", "note": "Of the work planned on my sites", "series": []},
            {"key": "dpr_due", "label": "Daily reports not sent today", "value": todo, "unit": "count", "note": "Send them before 8 pm", "series": []},
            {"key": "open_snags", "label": "Open snags", "value": snags, "unit": "count", "note": "On my sites", "series": []},
        ], kind
    out = []
    for t in list(tiles.values())[:4]:
        unit = t.get("unit") or "count"
        live = _num(t["value"]) if isinstance(t["value"], int | float | Decimal | str) and str(t["value"]).replace(".", "", 1).lstrip("-").isdigit() else None
        out.append({"key": t["key"], "label": t["label"], "value": live if live is not None else t["value"], "unit": unit, "note": t.get("note") or "",
                    "series": _snapshot_series(db, demo, t["key"], day, live)})  # fmt: skip
    return out, kind


def _needs(db, principal, site_ids: list[int] | None) -> list[dict]:
    from app.closeout import billing as bsvc  # noqa: PLC0415
    from app.closeout.models import LabourClaim  # noqa: PLC0415
    from app.closeout.recon import approved_of  # noqa: PLC0415
    from app.finance.models import RaBill  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    perms = principal.permissions
    out: list[dict] = []
    if "closeout.claim_approve" in perms:
        q = select(LabourClaim, Site).join(Site, Site.id == LabourClaim.site_id).where(LabourClaim.status == "director").order_by(LabourClaim.id)
        if site_ids is not None:
            q = q.where(LabourClaim.site_id.in_(site_ids or [0]))
        for c, s in db.execute(q.limit(3)):
            approved, _ = approved_of(db, c)
            unit = c.unit or ""
            more = (Decimal(c.claimed_qty) / approved - 1) * 100 if approved else None
            path = f"/api/closeout/labour-claims/{c.id}/director"
            out.append({"key": f"claim:{c.id}", "tag": "Labour claim · above measured", "tone": "prog",
                        "title": f"{s.name}: {c.contractor} claims {c.claimed_qty:g} {unit}, measured {approved:g} {unit}" + (f" ({more:.0f}% more)" if more else ""),
                        "link": f"/sites/{s.id}/labour-claims",
                        "actions": [{"label": "Pay measured", "primary": True, "method": "POST", "path": path, "body": {"approve": False, "reason": "Pay the measured quantity (decided from the dashboard)"}, "done": "Paying the measured quantity"},
                                    {"label": "Pay claimed", "method": "POST", "path": path, "body": {"approve": True, "reason": "Pay the claimed quantity (approved from the dashboard)"}, "done": "Paying the claimed quantity"}]})  # fmt: skip
    if "closeout.billing" in perms or "closeout.payments" in perms:
        q = select(RaBill, Site).join(Site, Site.id == RaBill.site_id).where(RaBill.status.in_(("submitted", "certified", "part_paid"))).order_by(RaBill.id)
        if site_ids is not None:
            q = q.where(RaBill.site_id.in_(site_ids or [0]))
        day = today()
        rows = []
        for b, s in db.execute(q.limit(200)):
            o = bsvc.bill_out(db, b, day)
            if o.get("overdue_days"):
                rows.append((o["overdue_days"], b, s))
        for days, b, s in sorted(rows, key=lambda r: -r[0])[:3]:
            out.append({"key": f"bill:{b.id}", "tag": f"Payment · {days} days overdue", "tone": "block", "title": f"{s.name}: {b.code}",
                        "link": f"/bills/{b.id}", "actions": [{"label": "Follow up", "primary": True, "link": f"/bills/{b.id}?tab=follow-up"}]})  # fmt: skip
    if "quotation.view" in perms:
        q = (
            select(Alert)
            .join(AlertRecipient, AlertRecipient.alert_id == Alert.id)
            .where(AlertRecipient.user_id == principal.user.id, Alert.rule == "followup_overdue", Alert.closed_at.is_(None), Alert.acknowledged_at.is_(None))
            .order_by(Alert.day.desc())
        )
        seen = set()
        for a in db.scalars(q.limit(10)):
            if a.item_key.split(":")[1] in seen or len(seen) >= 2:
                continue
            seen.add(a.item_key.split(":")[1])
            out.append({"key": f"alert:{a.id}", "tag": "Quotation · follow-up overdue", "tone": "hold", "title": a.title,
                        "link": a.link or "/quotations", "actions": [{"label": "Open", "primary": True, "link": a.link or "/quotations"}]})  # fmt: skip
    return out[:6]


class _Blank:
    """A site not yet in the nightly summary: its own dates, no money, not late."""

    def __init__(self, s) -> None:
        self.status, self.target_date, self.delayed, self.elapsed, self.forecast_end = s.status, s.target_date, False, None, None
        self.billed, self.contract_value = Decimal(0), None


def _sites(db, principal, demo: bool) -> tuple[list[dict], list[int] | None]:
    from app.building.models import BuildingModel  # noqa: PLC0415
    from app.sites import service as site_svc  # noqa: PLC0415
    from app.sites.models import Site, StageTemplateStep, Task  # noqa: PLC0415

    scope = principal.permissions.get("site.view")
    if not scope:
        return [], []
    money = any(p in principal.permissions for p in MONEY_PERMS)
    rows = db.execute(
        # a site made since last night's summary shows too (its money and delay from the next summary)
        select(Site, SiteSummary)
        .outerjoin(SiteSummary, SiteSummary.site_id == Site.id)
        .where(site_svc.scope_condition(scope, principal), Site.status.in_(ACTIVE), Site.is_demo == demo, Site.source.is_distinct_from("powerplay"))
        .order_by(SiteSummary.delayed.desc().nulls_last(), Site.progress_percent.desc())
        .limit(12)
    ).all()
    ids = None if scope == "all" else [s.id for s, _ in rows]
    due = set(db.scalars(select(Alert.site_id).where(Alert.rule.in_(("ready_not_billed", "ra_monthly")), Alert.closed_at.is_(None), Alert.site_id.is_not(None))))
    models = set(db.scalars(select(BuildingModel.site_id).where(BuildingModel.site_id.in_([s.id for s, _ in rows] or [0]))))
    day = today()
    live = progress_of.site_percents(db, [s.id for s, _ in rows])  # live, not last night's copy
    out = []
    for s, ss0 in rows:
        ss = ss0 or _Blank(s)
        progress = float(live.get(s.id, 0))
        if ss.delayed:
            late = (day - ss.target_date).days if ss.target_date and ss.target_date < day else ((ss.forecast_end - ss.target_date).days if ss.forecast_end and ss.target_date else 0)
            status, label = "block", f"Late {late} days" if late > 0 else "Behind time"
        elif ss.status == "on_hold":
            status, label = "hold", "On hold"
        elif ss.status == "planned" or progress == 0:
            status, label = "idle", "Not started"
        elif ss.elapsed is not None and progress >= float(ss.elapsed):
            status, label = "done", "On track"
        else:
            status, label = "prog", "In progress"
        nxt = db.execute(
            select(Task.name, StageTemplateStep.hold_point)
            .outerjoin(StageTemplateStep, StageTemplateStep.id == Task.step_id)
            .where(Task.site_id == s.id, Task.status.in_(("not_started", "in_progress", "blocked")))
            .order_by(Task.planned_start.asc().nulls_last(), Task.sort_order, Task.id)
            .limit(1)
        ).first()
        out.append({
            "id": s.id, "code": s.code, "name": s.name, "city": s.city, "progress": round(progress), "status": status, "status_label": label,
            "billed": float(ss.billed) if money else None, "order": float(ss.contract_value) if money and ss.contract_value is not None else None,
            "next": (f"Hold point: {nxt[0]}" if nxt and nxt[1] else nxt[0]) if nxt else None, "late": bool(ss.delayed), "billing_due": s.id in due,
            "has_building": s.id in models,
        })  # fmt: skip
    return out, ids


@router.get("")
def home(db: DbSession, principal: CurrentPrincipal, demo: bool | None = None) -> dict:
    day = today()
    if demo is None:  # the training company (or a company with only DEMO sites yet): its DEMO data
        demo = not db.scalar(select(SiteSummary.site_id).where(SiteSummary.is_demo.is_(False), SiteSummary.historic.is_(False), SiteSummary.status.in_(ACTIVE)).limit(1))
    kpis, kind = _kpis(db, principal, demo, day)
    sites, ids = _sites(db, principal, demo)
    building = next((s for s in sites if s["has_building"]), None)
    if building is None and principal.permissions.get("site.view"):
        from app.building.models import BuildingModel  # noqa: PLC0415
        from app.sites import service as site_svc  # noqa: PLC0415
        from app.sites.models import Site  # noqa: PLC0415

        row = db.execute(
            select(Site).join(BuildingModel, BuildingModel.site_id == Site.id).where(site_svc.scope_condition(principal.permissions["site.view"], principal)).order_by((Site.is_demo == demo).desc(), BuildingModel.id.desc()).limit(1)
        ).scalar()
        building = {"id": row.id, "name": row.name, "progress": None} if row else None
    return jsonable_encoder({
        "date": day, "demo": demo, "dashboard": kind, "kpis": kpis, "needs": _needs(db, principal, ids), "sites": sites,
        "building": {"site_id": building["id"], "name": building["name"], "progress": building.get("progress")} if building else None,
    })  # fmt: skip
