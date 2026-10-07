"""Site budget vs actual (cost only; client billing is M5), other site costs, and the site's
execution overview (DPRs missing, open MOM points).

budget.view shows the table; the budget amounts that come from the won tender's BOQ cost lines
(material, labour) are cost data, so they are hidden from a caller without tender.margin.
budget.edit sets budgets and enters other costs.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import service as svc
from app.execution.common import record
from app.execution.models import BUDGET_HEADS, Dpr, Mom, MomPoint, SiteBudget, SiteCost
from app.material import service as material

router = APIRouter(prefix="/api/execution", tags=["execution"])
BudgetView = Annotated[str, Depends(require_permission("budget.view"))]
Head = Literal["material", "labour", "subcontract", "equipment", "freight", "other"]


def _table(db, site, principal) -> dict:
    saved = {b.head: b for b in db.scalars(select(SiteBudget).where(SiteBudget.site_id == site.id))}
    suggested = svc.tender_budget(db, site)
    actual = svc.actuals(db, site.id)
    sees_cost = principal.permissions.get("tender.margin") is not None
    rows = []
    for head in BUDGET_HEADS:
        b = saved.get(head)
        amount, source = (
            (b.amount, b.source)
            if b
            else (suggested.get(head), "tender" if head in suggested else None)
        )
        hidden = source == "tender" and not sees_cost
        budget = None if hidden or amount is None else Decimal(amount)
        used = (actual[head] / budget * 100).quantize(Decimal("0.1")) if budget else None
        rows.append(
            {
                "head": head,
                "budget": budget,
                "source": source,
                "saved": b is not None,
                "hidden": hidden,
                "actual": actual[head],
                "variance": None if budget is None else budget - actual[head],
                "percent_used": used,
                "warn": used is not None and used > 90,
            }
        )
    known = [r for r in rows if r["budget"] is not None]
    total_budget = sum((r["budget"] for r in known), Decimal(0)) if known else None
    total_actual = sum((r["actual"] for r in rows), Decimal(0))
    return {
        "site_id": site.id,
        "site_code": site.code,
        "rows": rows,
        "cost_hidden": any(r["hidden"] for r in rows),
        "total_budget": total_budget,
        "total_actual": total_actual,
        "tender_suggestion": {k: v for k, v in suggested.items()} if sees_cost else None,
        "can_edit": material.covers_site(
            db, principal.permissions.get("budget.edit"), principal, site.id, site.created_by
        ),
    }


@router.get("/sites/{site_id}/budget")
def get_budget(site_id: int, db: DbSession, principal: CurrentPrincipal, _: BudgetView) -> dict:
    return _table(db, svc.site_for(db, site_id, principal, "budget.view"), principal)


class BudgetIn(BaseModel):
    heads: dict[Head, Decimal | None]  # None removes the saved amount (back to the suggestion)


@router.put("/sites/{site_id}/budget")
def set_budget(
    site_id: int,
    body: BudgetIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: BudgetView,
) -> dict:
    site = svc.site_for(db, site_id, principal, "budget.view", "budget.edit")
    saved = {b.head: b for b in db.scalars(select(SiteBudget).where(SiteBudget.site_id == site.id))}
    for head, amount in body.heads.items():
        if amount is not None and amount < 0:
            raise svc.unprocessable("A budget cannot be negative")
        b = saved.get(head)
        if amount is None:
            if b is not None:
                db.delete(b)
            continue
        if b is None:
            b = SiteBudget(site_id=site.id, head=head, created_by=principal.user.id)
            db.add(b)
        b.amount, b.source = amount, "manual"
    record(
        db, request, principal, "budget.set", "site", site.id, after=body.model_dump(mode="json")
    )
    db.commit()
    return _table(db, site, principal)


@router.post("/sites/{site_id}/budget/from-tender")
def budget_from_tender(
    site_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: BudgetView
) -> dict:
    """Save the tender's material and labour cost as the budget (needs tender.margin)."""
    site = svc.site_for(db, site_id, principal, "budget.view", "budget.edit")
    svc.need(principal, "tender.margin")
    suggested = svc.tender_budget(db, site)
    if not suggested:
        raise svc.unprocessable("The site's tender has no costed BOQ lines")
    for head, amount in suggested.items():
        b = db.scalar(
            select(SiteBudget).where(SiteBudget.site_id == site.id, SiteBudget.head == head)
        )
        if b is None:
            b = SiteBudget(site_id=site.id, head=head, created_by=principal.user.id)
            db.add(b)
        b.amount, b.source = amount, "tender"
    record(
        db,
        request,
        principal,
        "budget.from_tender",
        "site",
        site.id,
        after={k: str(v) for k, v in suggested.items()},
    )
    db.commit()
    return _table(db, site, principal)


class CostIn(BaseModel):
    head: Head = "other"
    on_date: date | None = None
    amount: Decimal = Field(gt=0)
    description: str = Field(min_length=1)


@router.get("/sites/{site_id}/costs")
def list_costs(
    site_id: int, db: DbSession, principal: CurrentPrincipal, _: BudgetView
) -> list[dict]:
    site = svc.site_for(db, site_id, principal, "budget.view")
    return [
        {
            "id": c.id,
            "head": c.head,
            "on_date": c.on_date,
            "amount": c.amount,
            "description": c.description,
        }
        for c in db.scalars(
            select(SiteCost).where(SiteCost.site_id == site.id).order_by(SiteCost.on_date.desc())
        )
    ]


@router.post("/sites/{site_id}/costs", status_code=status.HTTP_201_CREATED)
def add_cost(
    site_id: int,
    body: CostIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: BudgetView,
) -> dict:
    site = svc.site_for(db, site_id, principal, "budget.view", "budget.edit")
    c = SiteCost(
        site_id=site.id,
        head=body.head,
        on_date=body.on_date or svc.today(),
        amount=body.amount,
        description=body.description,
        created_by=principal.user.id,
    )
    db.add(c)
    db.flush()
    record(db, request, principal, "site.cost", "site", site.id, after=body.model_dump(mode="json"))
    db.commit()
    return _table(db, site, principal)


@router.get("/sites/{site_id}/overview")
def overview(site_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """For the site's Overview tab: DPRs missing in the last 30 days, open MOM points."""
    site = svc.site_for(db, site_id, principal, "site.view")
    perms = principal.permissions
    out: dict = {"dpr_missing": None, "open_points": None}
    if (
        material.covers_site(db, perms.get("dpr.view"), principal, site.id, site.created_by)
        and site.status == "active"
    ):
        have = set(
            db.scalars(select(Dpr.on_date).where(Dpr.site_id == site.id, Dpr.status != "draft"))
        )
        local_now = svc.datetime.now(svc.IST)
        last = (
            local_now.date()
            if local_now.time() >= svc.DPR_DUE
            else local_now.date() - timedelta(days=1)
        )
        first = max(last - timedelta(days=29), site.start_date or last - timedelta(days=29))
        days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
        missing = [d for d in days if d not in have]
        out["dpr_missing"] = {"count": len(missing), "days": missing[-10:]}
    if material.covers_site(db, perms.get("inspection.view"), principal, site.id, site.created_by):
        rows = db.execute(
            select(MomPoint, Mom.code)
            .join(Mom, Mom.id == MomPoint.mom_id)
            .where(Mom.site_id == site.id, MomPoint.status == "open")
            .order_by(MomPoint.due_date.nulls_last())
        ).all()
        out["open_points"] = [
            {
                "id": p.id,
                "text": p.text,
                "due_date": p.due_date,
                "mom_code": c,
                "overdue": bool(p.due_date and p.due_date < svc.today()),
            }
            for p, c in rows
        ]
    return out
