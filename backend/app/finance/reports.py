"""Site profit, margins for the site list, finance settings, Tally settings and the Tally export.

Profit and margin reveal cost: they need billing.view and tender.margin; staff salary inside them
needs payroll.view (without it the salary is left out and the result says so). The Tally export
needs finance.export.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import record
from app.export import xlsx_response
from app.finance import service as svc
from app.finance import tally
from app.finance.models import TallyExport
from app.material import service as material
from app.sites.models import Site

router = APIRouter(prefix="/api/finance", tags=["finance"])
BillingView = Annotated[str, Depends(require_permission("billing.view"))]
Export = Annotated[str, Depends(require_permission("finance.export"))]


def _cost_ok(principal):
    if not svc.sees_cost(principal):
        raise svc.forbidden("Profit and margin need tender.margin")


@router.get("/sites/{site_id}/profit")
def site_profit(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    _cost_ok(principal)
    site = db.get(Site, site_id)
    if site is None or not svc.site_ok(db, scope, principal, site.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return svc.site_profit(db, site, principal.permissions.get("payroll.view") is not None)


@router.get("/profit")
def profit_table(db: DbSession, principal: CurrentPrincipal, scope: BillingView) -> list[dict]:
    """Every open site in scope with billing or cost."""
    _cost_ok(principal)
    salary = principal.permissions.get("payroll.view") is not None
    out = []
    for site in db.scalars(
        select(Site)
        .where(
            Site.status != "closed", material.by_site(scope, principal, Site.id, Site.created_by)
        )
        .order_by(Site.code)
    ):
        p = svc.site_profit(db, site, salary)
        if p["billed"] or p["cost_total"]:
            out.append(p)
    return out


@router.get("/site-margins")
def site_margins(db: DbSession, principal: CurrentPrincipal) -> dict:
    """For the Sites list: margin % and the over-cost flag per site (needs tender.margin)."""
    if not svc.sees_cost(principal) or principal.permissions.get("billing.view") is None:
        return {}
    scope = principal.permissions["billing.view"]
    salary = principal.permissions.get("payroll.view") is not None
    out = {}
    for site in db.scalars(
        select(Site).where(
            Site.status != "closed", material.by_site(scope, principal, Site.id, Site.created_by)
        )
    ):
        p = svc.site_profit(db, site, salary)
        if p["billed"] or p["cost_total"]:
            out[str(site.id)] = {"margin_percent": p["margin_percent"], "over_cost": p["over_cost"]}
    return out


# --- settings ------------------------------------------------------------------------------------


class FinanceSettingsIn(BaseModel):
    invoice_prefix: str = Field(min_length=1, max_length=6, pattern=r"^[A-Za-z0-9-]+$")
    works_sac: str = Field(pattern=r"^[0-9]{4,8}$")
    match_tolerance_percent: Decimal = Field(ge=0, le=50)
    payment_approval_limit: Decimal = Field(ge=0)
    expense_photo_limit: Decimal = Field(ge=0)
    tds_rules: dict[str, dict[str, Any]]
    pf_percent: Decimal = Field(ge=0, le=20)
    pf_wage_cap: Decimal = Field(ge=0)
    esi_threshold: Decimal = Field(ge=0)
    esi_employee_percent: Decimal = Field(ge=0, le=10)
    esi_employer_percent: Decimal = Field(ge=0, le=10)
    pt_slabs: list[dict[str, Any]]


FIELDS = list(FinanceSettingsIn.model_fields)


def _settings_out(s) -> dict:
    return {k: getattr(s, k) for k in FIELDS} | {
        "invoice_example": f"{s.invoice_prefix}/26-27/0001"
    }


@router.get("/settings")
def get_settings(db: DbSession, principal: CurrentPrincipal) -> dict:
    if not any(
        principal.permissions.get(c)
        for c in ("billing.view", "payables.view", "payroll.view", "finance.export")
    ):
        raise svc.forbidden("No finance permission")
    return _settings_out(svc.settings(db))


@router.put("/settings")
def put_settings(
    body: FinanceSettingsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("settings.company"))],
) -> dict:
    if len(f"{body.invoice_prefix}/26-27/0001") > 16:
        raise svc.unprocessable("The invoice number would exceed 16 characters")
    s = svc.settings(db)
    before = _settings_out(s)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "finance.settings",
        "finance_settings",
        1,
        {k: str(v) for k, v in before.items()},
        body.model_dump(mode="json"),
    )
    db.commit()
    return _settings_out(s)


class TallySettingsIn(BaseModel):
    ledgers: dict[str, Any]
    party_ledgers: dict[str, str] = {}


@router.get("/tally/settings")
def tally_settings(db: DbSession, _: Export) -> dict:
    s = svc.settings(db)
    return {"ledgers": s.tally_ledgers, "party_ledgers": s.party_ledgers}


@router.put("/tally/settings")
def put_tally_settings(
    body: TallySettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Export
) -> dict:
    s = svc.settings(db)
    s.tally_ledgers, s.party_ledgers = body.ledgers, body.party_ledgers
    record(db, request, principal, "tally.settings", "finance_settings", 1, after=body.model_dump())
    db.commit()
    return {"ledgers": s.tally_ledgers, "party_ledgers": s.party_ledgers}


def _range(date_from: date, date_to: date):
    if date_to < date_from:
        raise svc.unprocessable("The range ends before it starts")


@router.get("/tally/preview")
def tally_preview(
    date_from: date, date_to: date, db: DbSession, _: Export, include_exported: bool = False
) -> dict:
    _range(date_from, date_to)
    vs = tally.vouchers(db, date_from, date_to, include_exported)
    return {
        "count": len(vs),
        "vouchers": [
            {
                "type": v.vtype,
                "number": v.number,
                "date": v.on,
                "party": v.party,
                "narration": v.narration,
                "balanced": v.balanced(),
                "entries": [
                    {
                        "ledger": ledger,
                        "debit": a if a > 0 else None,
                        "credit": -a if a < 0 else None,
                    }
                    for ledger, a in v.entries
                ],
            }
            for v in vs
        ],
    }


@router.post("/tally/export")
def tally_export(
    date_from: date,
    date_to: date,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Export,
    include_exported: bool = False,
) -> Response:
    """TallyPrime import XML for the range; the vouchers are marked exported so the next export
    skips them unless include_exported is set."""
    _range(date_from, date_to)
    vs = tally.vouchers(db, date_from, date_to, include_exported)
    bad = [v.number for v in vs if not v.balanced()]
    if bad:
        raise svc.unprocessable(f"Vouchers that do not balance: {', '.join(bad)}")
    from app.tenders.export import company

    xml = tally.to_xml(vs, company(db).name)
    now = svc.now()
    for v in vs:
        v.source.tally_exported_at = now
    db.add(
        TallyExport(
            date_from=date_from,
            date_to=date_to,
            vouchers=len(vs),
            include_exported=include_exported,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "tally.export",
        "tally_export",
        "range",
        after={"from": str(date_from), "to": str(date_to), "vouchers": len(vs)},
    )
    db.commit()
    name = f"eespl-tally-{date_from:%Y%m%d}-{date_to:%Y%m%d}.xml"
    return Response(
        xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Voucher-Count": str(len(vs)),
        },
    )


@router.get("/tally/day-book")
def day_book(
    date_from: date, date_to: date, db: DbSession, _: Export, include_exported: bool = True
):
    """The same vouchers as an Excel day book for the accountant (does not mark anything)."""
    _range(date_from, date_to)
    rows = tally.day_book_rows(tally.vouchers(db, date_from, date_to, include_exported))
    return xlsx_response(
        f"day-book-{date_from:%Y%m%d}-{date_to:%Y%m%d}",
        ["Date", "Type", "Number", "Party", "Ledger", "Debit", "Credit", "Narration"],
        rows,
        "Day book",
    )
