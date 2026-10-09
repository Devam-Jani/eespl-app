"""Dashboards (/api/dashboard) and analytics, alerts and reports (/api/analytics).

Access: each dashboard needs its own permission (dashboard.company / sales / site / finance /
purchase) with its scope; numbers that reveal cost or margin also need tender.margin, staff salary
needs payroll.view; Excel and PDF exports need reports.export. Client logins never get here (403).
`demo=true` switches every number to the invented demo company.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.analytics import alerts as alert_svc
from app.analytics import drill as drill_svc
from app.analytics import kpi, pages, reports, strategy, summary
from app.analytics.common import Filtered, cost_or_403, need_any, sees_cost
from app.analytics.models import ALERT_RULES, RULE_LABELS, Alert, WeeklyReport
from app.auth.deps import CurrentPrincipal
from app.db import DbSession
from app.execution.common import names, pdf_response, record
from app.execution.service import site_for
from app.masters.models import CLIENT_TYPES
from app.models import User
from app.sites.models import SITE_STATUSES, Site

dashboard = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
router = APIRouter(prefix="/api/analytics", tags=["analytics"])

KINDS = {
    "company": "dashboard.company",
    "sales": "dashboard.sales",
    "site": "dashboard.site",
    "finance": "dashboard.finance",
    "purchase": "dashboard.purchase",
}
TITLES = {
    "company": "Management",
    "sales": "Sales",
    "site": "My sites",
    "finance": "Accounts",
    "purchase": "Store and purchase",
}


def _xlsx(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type=reports.XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


def _export(principal) -> None:
    need_any(principal, "reports.export")


def demo_available(db) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Site).where(Site.is_demo)))


# --- dashboards ----------------------------------------------------------------------------------


@dashboard.get("")
def home(db: DbSession, principal: CurrentPrincipal) -> dict:
    """Which dashboards the caller has (the home page shows the first and offers the others)."""
    mine = [
        {"key": k, "title": TITLES[k], "scope": principal.permissions[code]}
        for k, code in KINDS.items()
        if code in principal.permissions
    ]
    return {
        "dashboards": mine,
        "demo_available": "dashboard.company" in principal.permissions and demo_available(db),
        "as_of": summary.settings(db).refreshed_at,
        "can_export": "reports.export" in principal.permissions,
    }


def _dashboard(db, principal, kind: str, demo: bool) -> dict:
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown dashboard")
    scope = need_any(principal, KINDS[kind])
    if kind == "company":
        return kpi.management(db, principal, demo)
    if kind == "sales":
        return kpi.sales(db, principal, scope, demo)
    if kind == "site":
        return kpi.supervisor(db, principal, scope, demo)
    if kind == "finance":
        return kpi.accounts(db, principal, demo)
    return kpi.purchase(db, principal, demo)


@dashboard.get("/{kind}")
def get_dashboard(
    kind: str, db: DbSession, principal: CurrentPrincipal, demo: bool = False
) -> dict:
    return jsonable_encoder(_dashboard(db, principal, kind, demo))


@dashboard.get("/{kind}/xlsx")
def dashboard_xlsx(
    kind: str, request: Request, db: DbSession, principal: CurrentPrincipal, demo: bool = False
):
    data = _dashboard(db, principal, kind, demo)
    _export(principal)
    sheets = [reports.tiles_sheet(data)]
    if kind == "sales":
        sheets.append(
            (
                "Pipeline",
                [
                    {"key": "stage", "label": "Stage"},
                    {"key": "count", "label": "Count"},
                    {"key": "value", "label": "Value"},
                ],
                data["pipeline"],
            )
        )
    if kind == "site":
        rows = [
            {"site": s["code"], **{t["label"]: t["value"] for t in s["todos"]}}
            for s in data["sites"]
        ]
        cols = [{"key": "site", "label": "Site"}] + [
            {"key": t["label"], "label": t["label"]}
            for t in (data["sites"][0]["todos"] if data["sites"] else [])
        ]
        sheets = [("My sites", cols, rows)]
    if kind == "finance":
        sheets.append(
            (
                "Ageing",
                [{"key": "bucket", "label": "Age (days)"}, {"key": "amount", "label": "Due"}],
                data["ageing"],
            )
        )
    record(
        db,
        request,
        principal,
        "report.export",
        "dashboard",
        None,
        after={"kind": kind, "demo": demo},
    )
    db.commit()
    return _xlsx(reports.xlsx_book(sheets), f"dashboard-{kind}")


@dashboard.post("/refresh")
def refresh(db: DbSession, principal: CurrentPrincipal) -> dict:
    """Rebuild the summary tables now (the worker also does it every night)."""
    need_any(principal, *KINDS.values())
    return {"as_of": summary.refresh(db)}


# --- drill-down ----------------------------------------------------------------------------------

FILTER_KEYS = {
    "date_from",
    "date_to",
    "region",
    "salesperson",
    "client_type",
    "site_status",
    "demo",
    "format",
    "kind",
}


@router.get("/drill")
def drill(
    request: Request,
    kind: str,
    f: Filtered,
    db: DbSession,
    principal: CurrentPrincipal,
    format: Literal["json", "xlsx"] = "json",
):
    args = {k: v for k, v in request.query_params.items() if k not in FILTER_KEYS}
    data = drill_svc.drill(db, principal, kind, f, args)
    if format == "xlsx":
        _export(principal)
        record(db, request, principal, "report.export", "drill", None, after={"kind": kind, **args})
        db.commit()
        return _xlsx(
            reports.xlsx_book([(data["title"][:31], data["columns"], data["rows"])]),
            f"{kind}-{args.get('filter') or 'list'}",
        )
    return jsonable_encoder(data)


@router.get("/filters")
def filter_options(db: DbSession, principal: CurrentPrincipal, demo: bool = False) -> dict:
    need_any(principal, *KINDS.values())
    regions = sorted(
        {
            r
            for (r,) in db.execute(
                select(Site.state).where(Site.state.is_not(None), Site.is_demo == demo).distinct()
            )
        }
    )
    from app.analytics.models import SiteSummary
    from app.crm.models import Lead
    from app.tenders.models import Tender

    ids = (
        set(db.scalars(select(Tender.owner_id).where(Tender.is_demo == demo).distinct()))
        | set(db.scalars(select(Lead.owner_id).where(Lead.is_demo == demo).distinct()))
        | set(
            db.scalars(
                select(SiteSummary.salesperson_id).where(SiteSummary.is_demo == demo).distinct()
            )
        )
    )
    people = sorted(
        ({"id": str(u), "name": n} for u, n in names(db, ids).items()), key=lambda x: x["name"]
    )
    return {
        "regions": regions,
        "salespeople": people,
        "client_types": list(CLIENT_TYPES),
        "site_statuses": list(SITE_STATUSES),
    }


# --- analytics pages -----------------------------------------------------------------------------

PAGES = {
    "sites": (("dashboard.company", "dashboard.site"), pages.sites_page, False),
    "finance": (("dashboard.company", "dashboard.finance"), pages.finance_page, False),
    "profitability": (("dashboard.company", "dashboard.finance"), pages.profitability_page, True),
    "purchase": (("dashboard.company", "dashboard.purchase"), pages.purchase_page, False),
    "labour": (("dashboard.company", "dashboard.site"), pages.labour_page, False),
}


@router.get("/pages/{page}")
def analytics_page(
    page: str,
    request: Request,
    f: Filtered,
    db: DbSession,
    principal: CurrentPrincipal,
    format: Literal["json", "xlsx"] = "json",
):
    if page not in PAGES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown page")
    codes, fn, cost = PAGES[page]
    scope = need_any(principal, *codes)
    if cost:
        cost_or_403(principal)
    data = fn(db, principal, scope, f)
    if format == "xlsx":
        _export(principal)
        record(
            db,
            request,
            principal,
            "report.export",
            "analytics",
            None,
            after={"page": page, **f.as_dict()},
        )
        db.commit()
        return _xlsx(
            reports.xlsx_book(
                [(t["title"], t["columns"], t["rows"]) for t in data["tables"].values()]
            ),
            f"analytics-{page}",
        )
    return jsonable_encoder(data | {"filters": f.as_dict()})


@router.get("/strategy/{part}")
def strategy_part(
    part: str,
    request: Request,
    f: Filtered,
    db: DbSession,
    principal: CurrentPrincipal,
    group_by: Literal["month", "salesperson", "client_type", "source", "region"] | None = None,
    format: Literal["json", "xlsx"] = "json",
):
    scope = need_any(principal, "dashboard.company", "dashboard.sales")
    if part == "funnel":
        data = strategy.funnel(db, principal, scope, f, group_by)
        sheets = [
            (
                "Funnel",
                [
                    {"key": "label", "label": "Step"},
                    {"key": "count", "label": "Count"},
                    {"key": "value", "label": "Value"},
                    {"key": "conversion", "label": "Conversion %"},
                ],
                data["total"]["steps"],
            )
        ]
        for g in data["groups"]:
            sheets.append((str(g["key"])[:31], sheets[0][1], g["steps"]))
    elif part == "winloss":
        data = strategy.winloss(db, principal, scope, f)
        seg_cols = [
            {"key": "key", "label": "Segment"},
            {"key": "won", "label": "Won"},
            {"key": "lost", "label": "Lost"},
            {"key": "win_rate", "label": "Win rate %"},
            {"key": "won_value", "label": "Won value"},
        ]
        sheets = [(f"By {k}", seg_cols, v) for k, v in data["segments"].items()]
        sheets.append(
            (
                "Lost reasons",
                [
                    {"key": "reason", "label": "Reason"},
                    {"key": "tenders", "label": "Tenders"},
                    {"key": "value", "label": "Value"},
                    {"key": "leads", "label": "Leads"},
                ],
                data["lost_reasons"],
            )
        )
        sheets.append(
            (
                "Competitors",
                [{"key": "name", "label": "Competitor"}, {"key": "count", "label": "Lost to them"}],
                data["competitors"],
            )
        )
    elif part == "pricing":
        data = strategy.pricing(db, principal, scope, f)
        rows = [
            {
                "system": r["system"],
                "won_lines": r["won"]["lines"],
                "won_ratio": r["won"]["median_ratio"],
                "lost_lines": r["lost"]["lines"],
                "lost_ratio": r["lost"]["median_ratio"],
            }
            for r in data["systems"]
        ]
        sheets = [
            (
                "Pricing position",
                [
                    {"key": "system", "label": "System"},
                    {"key": "won_lines", "label": "Won: lines"},
                    {"key": "won_ratio", "label": "Won: our rate / median"},
                    {"key": "lost_lines", "label": "Lost: lines"},
                    {"key": "lost_ratio", "label": "Lost: our rate / median"},
                ],
                rows,
            )
        ]
    elif part == "repeat":
        need_any(principal, "dashboard.company")  # revenue by client is company-wide
        data = strategy.repeat_clients(db, f)
        sheets = [
            (
                "Top clients",
                [
                    {"key": "name", "label": "Client"},
                    {"key": "billed", "label": "Billed"},
                    {"key": "repeat", "label": "Repeat"},
                ],
                data["top"],
            ),
            (
                "No enquiry 12 months",
                [
                    {"key": "name", "label": "Client"},
                    {"key": "type", "label": "Type"},
                    {"key": "sites", "label": "Sites"},
                    {"key": "last_enquiry", "label": "Last enquiry"},
                    {"key": "billed", "label": "Billed in range"},
                ],
                data["quiet"],
            ),
        ]
    elif part == "historic":
        data, sheets = strategy.historic(db), []
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown analysis")
    if format == "xlsx":
        _export(principal)
        record(
            db,
            request,
            principal,
            "report.export",
            "strategy",
            None,
            after={"part": part, **f.as_dict()},
        )
        db.commit()
        return _xlsx(
            reports.xlsx_book(sheets, data.get("basis") if isinstance(data, dict) else None),
            f"strategy-{part}",
        )
    return jsonable_encoder(data | {"filters": f.as_dict()})


# --- alerts --------------------------------------------------------------------------------------


@router.get("/alerts")
def list_alerts(
    db: DbSession,
    principal: CurrentPrincipal,
    rule: str | None = None,
    site_id: int | None = None,
    state: Literal["open", "acknowledged", "all"] = "open",
) -> dict:
    rows = alert_svc.visible(db, principal, rule, site_id, state)
    who = names(db, [a.acknowledged_by for a in rows])
    return jsonable_encoder(
        {
            "alerts": [alert_svc.alert_out(a, who) for a in rows],
            "rules": RULE_LABELS,
            "run_at": summary.settings(db).alerts_run_at,
        }
    )


@router.post("/alerts/{aid}/ack")
def acknowledge(aid: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    a = db.get(Alert, aid)
    if a is None or a not in alert_svc.visible(db, principal, state="all", limit=100000):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if a.acknowledged_at is None:
        a.acknowledged_at, a.acknowledged_by = summary.now(), principal.user.id
        record(
            db,
            request,
            principal,
            "alert.acknowledge",
            "alert",
            a.id,
            after={"rule": a.rule, "item": a.item_key},
        )
        db.commit()
    return jsonable_encoder(alert_svc.alert_out(a, names(db, [a.acknowledged_by])))


@router.post("/alerts/run")
def run_alerts(db: DbSession, principal: CurrentPrincipal) -> dict:
    need_any(principal, "dashboard.company")
    return {"raised": alert_svc.run(db)}


class SettingsIn(BaseModel):
    delay_threshold_points: float = Field(ge=0, le=100)
    ack_snooze_days: int = Field(ge=0, le=90)
    weekly_report: bool = True
    alert_rules: dict[str, dict] = {}


@router.get("/settings")
def get_settings(db: DbSession, principal: CurrentPrincipal) -> dict:
    need_any(principal, "dashboard.company")
    s = summary.settings(db)
    return jsonable_encoder(
        {
            "delay_threshold_points": s.delay_threshold_points,
            "ack_snooze_days": s.ack_snooze_days,
            "weekly_report": s.weekly_report,
            "alert_rules": alert_svc.rules(db),
            "labels": RULE_LABELS,
            "refreshed_at": s.refreshed_at,
            "alerts_run_at": s.alerts_run_at,
        }
    )


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    need_any(principal, "admin.settings", "settings.company")
    need_any(principal, "dashboard.company")
    bad = set(body.alert_rules) - set(ALERT_RULES)
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rules: {', '.join(sorted(bad))}"
        )
    s = summary.settings(db)
    s.delay_threshold_points, s.ack_snooze_days, s.weekly_report = (
        body.delay_threshold_points,
        body.ack_snooze_days,
        body.weekly_report,
    )
    s.alert_rules = {k: {**ALERT_RULES[k], **v} for k, v in body.alert_rules.items()}
    record(
        db,
        request,
        principal,
        "analytics.settings",
        "analytics_settings",
        1,
        after=body.model_dump(),
    )
    db.commit()
    return get_settings(db, principal)


# --- reports and PDFs ----------------------------------------------------------------------------


@router.get("/reports")
def weekly_reports(db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    need_any(principal, "dashboard.company")
    return jsonable_encoder(
        [
            {
                "id": r.id,
                "week_start": r.week_start,
                "generated_at": r.generated_at,
                "tiles": [t for sec in r.data.get("sections", []) for t in sec["tiles"]][:6],
            }
            for r in db.scalars(
                select(WeeklyReport).order_by(WeeklyReport.week_start.desc()).limit(104)
            )
        ]
    )


@router.post("/reports/weekly")
def make_weekly(db: DbSession, principal: CurrentPrincipal) -> dict:
    need_any(principal, "dashboard.company")
    r = reports.weekly(db)
    return {"created": r is not None}


@router.get("/reports/{rid}/pdf")
def weekly_pdf(rid: int, db: DbSession, principal: CurrentPrincipal):
    need_any(principal, "dashboard.company")
    r = db.get(WeeklyReport, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return pdf_response(
        reports.weekly_pdf(db, r, sees_cost(principal)), f"Management-summary-{r.week_start}"
    )


@router.get("/pdf/management")
def management_pdf(
    request: Request, db: DbSession, principal: CurrentPrincipal, demo: bool = False
):
    need_any(principal, "dashboard.company")
    _export(principal)
    data = kpi.management(db, principal, demo)
    out = reports.management_pdf(
        db,
        data,
        sees_cost(principal),
        reports.open_alerts_for(db, principal),
        reports.delayed_sites(db, demo),
        "DEMO company (invented data)" if demo else "",
    )
    record(
        db,
        request,
        principal,
        "report.export",
        "pdf",
        None,
        after={"report": "management", "demo": demo},
    )
    db.commit()
    return pdf_response(out, f"Management-summary-{summary.today()}{'-DEMO' if demo else ''}")


@router.get("/pdf/site/{site_id}")
def site_pdf(site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal):
    _export(principal)
    site = site_for(db, site_id, principal, "site.view")
    record(db, request, principal, "report.export", "pdf", site.id, after={"report": "site_status"})
    db.commit()
    return pdf_response(
        reports.site_status_pdf(db, site), f"Site-status-{site.code}-{summary.today()}"
    )


@router.get("/pdf/receivables")
def receivables_pdf(
    request: Request, db: DbSession, principal: CurrentPrincipal, demo: bool = False
):
    need_any(principal, "dashboard.company", "dashboard.finance")
    _export(principal)
    record(
        db,
        request,
        principal,
        "report.export",
        "pdf",
        None,
        after={"report": "receivables", "demo": demo},
    )
    db.commit()
    return pdf_response(reports.receivables_pdf(db, demo), f"Receivables-{summary.today()}")


@router.get("/pdf/pipeline")
def pipeline_pdf(request: Request, db: DbSession, principal: CurrentPrincipal, demo: bool = False):
    scope = need_any(principal, "dashboard.company", "dashboard.sales")
    _export(principal)
    record(
        db,
        request,
        principal,
        "report.export",
        "pdf",
        None,
        after={"report": "pipeline", "demo": demo},
    )
    db.commit()
    return pdf_response(
        reports.pipeline_pdf(db, principal, scope, demo), f"Sales-pipeline-{summary.today()}"
    )


__all__ = ["Annotated", "Query", "User"]
