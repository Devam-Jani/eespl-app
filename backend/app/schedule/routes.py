# ruff: noqa: E501  (the build-up rows and queries read better unwrapped)
"""The schedule API: the project plan and its lots, the handover dates and target finish per place,
the stage days per site, and the delays across sites for the director's dashboard."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import record
from app.schedule import service as svc
from app.schedule.models import MaterialLot, MaterialLotLine, ProjectPlanLine, SiteStageDays
from app.sites import service as site_service
from app.sites.models import AreaScope, Site, SiteNode, StageTemplateStep

router = APIRouter(prefix="/api/schedule", tags=["schedule"])
SiteView = Annotated[str, Depends(require_permission("site.view"))]


def _site(db, site_id: int, scope: str, principal) -> Site:
    return site_service.get_visible(db, site_id, scope, principal)


def _node(db, site: Site, node_id: int) -> SiteNode:
    node = db.get(SiteNode, node_id)
    if node is None or node.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found")
    return node


def _may(principal, code: str) -> str:
    scope = principal.permissions.get(code)
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Needs {code}")
    return scope


# --- the project plan and its lots ---------------------------------------------------------------


@router.get("/sites/{site_id}/plan")
def get_plan(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteView) -> dict:
    return jsonable_encoder(svc.plan(db, _site(db, site_id, scope, principal)))


class PlanLineIn(BaseModel):
    product_id: int
    planned_qty: Decimal = Field(ge=0)
    note: str | None = None


class FixIn(BaseModel):
    lines: list[PlanLineIn] | None = None  # none: fix the computed quantities as they are


@router.post("/sites/{site_id}/plan/fix")
def fix_plan(
    site_id: int,
    body: FixIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    """Planning fixes the whole project's quantity per product (from the BOQ and survey
    quantities with consumption and wastage, or as adjusted with a note)."""
    _may(principal, "planning.edit")
    site = _site(db, site_id, scope, principal)
    current = {r["product_id"]: r for r in svc.plan(db, site)["products"]}
    lines = body.lines or [
        PlanLineIn(product_id=pid, planned_qty=r["computed"])
        for pid, r in current.items()
        if Decimal(r["computed"]) > 0
    ]
    for ln in lines:
        row = db.scalar(
            select(ProjectPlanLine).where(
                ProjectPlanLine.site_id == site.id, ProjectPlanLine.product_id == ln.product_id
            )
        )
        computed = Decimal(current.get(ln.product_id, {}).get("computed") or 0)
        if (
            computed is not None
            and Decimal(ln.planned_qty) != Decimal(computed)
            and not (ln.note or "").strip()
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Say why the plan differs from the computed quantity",
            )
        if row is None:
            row = ProjectPlanLine(
                site_id=site.id, product_id=ln.product_id, created_by=principal.user.id
            )
            db.add(row)
        row.planned_qty, row.computed_qty, row.note = ln.planned_qty, computed, ln.note
    db.flush()
    record(
        db,
        request,
        principal,
        "plan.fix",
        "site",
        site.id,
        after=jsonable_encoder([x.model_dump() for x in lines]),
    )
    db.commit()
    return jsonable_encoder(svc.plan(db, site))


class LotLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)


class LotIn(BaseModel):
    node_ids: list[int] = []
    days: int | None = Field(None, ge=1, le=60)
    need_by: date | None = None
    lines: list[LotLineIn] = Field(min_length=1)
    reason: str | None = Field(None, max_length=1000)


def _lot_indent(db, request, principal, site: Site, lot: MaterialLot) -> None:
    """The lot becomes an indent (submitted), then the delivery note as today."""
    from app.material.routers import create_indent  # noqa: PLC0415
    from app.material.schemas import IndentIn, IndentLineIn  # noqa: PLC0415

    scope = principal.permissions.get("indent.create") or "all"
    out = create_indent(
        IndentIn(
            site_id=site.id,
            required_by=lot.need_by,
            remark=f"Lot {lot.code}" + (f" for the next {lot.days} days" if lot.days else ""),
            lines=[IndentLineIn(product_id=ln.product_id, qty=ln.qty) for ln in lot.lines],
            submit=True,
        ),
        request,
        db,
        principal,
        scope,
    )
    lot.indent_id = out.id
    if lot.node_ids:
        from app.material.models import Indent  # noqa: PLC0415
        from app.process import hooks  # noqa: PLC0415

        hooks.indent_created(db, db.get(Indent, out.id), lot.node_ids, principal.user.id)


@router.post("/sites/{site_id}/lots", status_code=status.HTTP_201_CREATED)
def call_off(
    site_id: int,
    body: LotIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    """The site calls off a lot for the ready work fronts. Within the plan (balance plus the
    tolerance) it becomes an indent at once; past it, it waits for planning with a reason."""
    _may(principal, "indent.create")
    site = _site(db, site_id, scope, principal)
    for nid in body.node_ids:
        _node(db, site, nid)
    lines = [ln.model_dump() for ln in body.lines]
    over = svc.over_plan(db, site, lines)
    reason = " ".join((body.reason or "").split()) or None
    if over and (not reason or len(reason) < 3):
        names = ", ".join(o["product"] for o in over)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"More than the plan's balance plus the tolerance for {names}: give the reason (planning approves it)",
        )
    lot = MaterialLot(
        code=svc.next_lot_code(db, site), site_id=site.id, node_ids=body.node_ids, days=body.days,
        need_by=body.need_by, status="pending" if over else "approved", over_plan=bool(over),
        reason=reason, created_by=principal.user.id,
    )  # fmt: skip
    lot.lines = [
        MaterialLotLine(product_id=ln["product_id"], qty=ln["qty"], created_by=principal.user.id)
        for ln in lines
    ]
    db.add(lot)
    db.flush()
    if not over:
        _lot_indent(db, request, principal, site, lot)
    record(db, request, principal, "lot.call_off", "material_lot", lot.id,
           after={"code": lot.code, "status": lot.status, "over": jsonable_encoder(over), "reason": reason})  # fmt: skip
    db.commit()
    return jsonable_encoder(svc.lot_out(db, lot) | {"over": over})


class DecideIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=1000)


@router.post("/lots/{lot_id}/decide")
def decide(
    lot_id: int,
    body: DecideIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    """Planning approves a call-off past the plan (it becomes an indent) or rejects it."""
    _may(principal, "planning.edit")
    lot = db.get(MaterialLot, lot_id)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lot not found")
    site = _site(db, lot.site_id, scope, principal)
    if lot.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{lot.code} is {lot.status}")
    if not body.approve and not (body.note or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Say why it is rejected")
    lot.status = "approved" if body.approve else "rejected"
    lot.decided_by, lot.decided_at, lot.decision_note = (
        principal.user.id,
        datetime.now(UTC),
        body.note,
    )
    db.flush()
    if body.approve:
        _lot_indent(db, request, principal, site, lot)
    record(
        db,
        request,
        principal,
        "lot.decide",
        "material_lot",
        lot.id,
        after={"status": lot.status, "note": body.note},
    )
    db.commit()
    return jsonable_encoder(svc.lot_out(db, lot))


# --- handover dates and the target finish --------------------------------------------------------


@router.get("/sites/{site_id}/handover")
def handover(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteView) -> dict:
    site = _site(db, site_id, scope, principal)
    out = svc.site_schedule(db, site)
    out["can_promise"] = principal.permissions.get("site.update") is not None
    out["can_confirm"] = svc.is_supervisor(db, principal, site.id)
    return jsonable_encoder(out)


class PromiseIn(BaseModel):
    promised_on: date
    promised_by: str = Field(min_length=2, max_length=200)
    client_says_on: date | None = None  # what the client says; it does not start the clock


@router.put("/sites/{site_id}/nodes/{node_id}/promise")
def promise(
    site_id: int,
    node_id: int,
    body: PromiseIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    """The site engineer, after talking to the client: the date the client promised to hand the
    place over, and who promised it."""
    _may(principal, "site.update")
    site = _site(db, site_id, scope, principal)
    node = _node(db, site, node_id)
    before = {"promised_on": node.handover_promised_on, "promised_by": node.handover_promised_by}
    node.handover_promised_on, node.handover_promised_by = (
        body.promised_on,
        body.promised_by.strip(),
    )
    node.handover_client_says_on = body.client_says_on
    node.handover_promised_entered_by = principal.user.id
    record(db, request, principal, "handover.promise", "site_node", node.id,
           before=jsonable_encoder(before), after=jsonable_encoder(body.model_dump()))  # fmt: skip
    db.commit()
    return jsonable_encoder(svc.node_schedule(db, node))


class ConfirmIn(BaseModel):
    received: bool
    on_date: date | None = None


@router.post("/sites/{site_id}/nodes/{node_id}/handover")
def confirm(
    site_id: int,
    node_id: int,
    body: ConfirmIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> dict:
    """The supervisor confirms the real handover: received on a date (the work front is ready),
    or not received yet. The client saying so does not count until then."""
    site = _site(db, site_id, scope, principal)
    node = _node(db, site, node_id)
    if not svc.is_supervisor(db, principal, site.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The site's supervisor confirms the handover"
        )
    if body.on_date and body.on_date > svc.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The handover date cannot be in the future"
        )
    svc.confirm_handover(db, node, principal.user.id, body.received, body.on_date)
    if body.received and not node.front_ready:
        node.front_ready, node.front_ready_by, node.front_ready_at = (
            True,
            principal.user.id,
            datetime.now(UTC),
        )
        from app.process import hooks  # noqa: PLC0415

        hooks.front_ready(db, node, principal.user.id)  # planning: the material plan for it
    record(
        db,
        request,
        principal,
        "handover.confirm",
        "site_node",
        node.id,
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return jsonable_encoder(svc.node_schedule(db, node))


@router.get("/sites/{site_id}/stage-days")
def get_stage_days(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteView
) -> list[dict]:
    from app.sites.models import StageTemplate  # noqa: PLC0415

    site = _site(db, site_id, scope, principal)
    ids = sorted(
        set(db.scalars(select(AreaScope.stage_template_id).where(AreaScope.site_id == site.id)))
    )
    return jsonable_encoder([
        {"template_id": t, "template": db.get(StageTemplate, t).name, "steps": svc.stage_days(db, site.id, t),
         "total_days": sum(s["days"] for s in svc.stage_days(db, site.id, t))}
        for t in ids
    ])  # fmt: skip


class DaysIn(BaseModel):
    step_id: int
    days: int = Field(ge=0, le=365)


@router.put("/sites/{site_id}/stage-days")
def put_stage_days(
    site_id: int,
    body: list[DaysIn],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
) -> list[dict]:
    """A stage's days on this site (planning or the site engineer)."""
    _may(principal, "site.update")
    site = _site(db, site_id, scope, principal)
    for d in body:
        if db.get(StageTemplateStep, d.step_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown stage")
        row = db.scalar(
            select(SiteStageDays).where(
                SiteStageDays.site_id == site.id, SiteStageDays.step_id == d.step_id
            )
        )
        if row is None:
            row = SiteStageDays(
                site_id=site.id, step_id=d.step_id, days=d.days, created_by=principal.user.id
            )
            db.add(row)
        row.days = d.days
    record(
        db,
        request,
        principal,
        "schedule.stage_days",
        "site",
        site.id,
        after=jsonable_encoder([d.model_dump() for d in body]),
    )
    db.commit()
    return get_stage_days(site_id, db, principal, scope)


@router.get("/delays")
def delays(db: DbSession, principal: CurrentPrincipal, scope: SiteView) -> dict:
    """Every active site in scope with a delay: the client's and ours (the director's view)."""
    from app.material.service import by_site  # noqa: PLC0415

    rows = []
    for site in db.scalars(
        select(Site)
        .where(Site.status == "active", by_site(scope, principal, Site.id, Site.created_by))
        .order_by(Site.code)
    ):
        s = svc.site_schedule(db, site)
        if (
            s["client_delay_days"]
            or s["our_delay_days"]
            or any(a["promised_on"] for a in s["areas"])
        ):
            rows.append({k: s[k] for k in ("site_id", "site", "client_delay_days", "our_delay_days", "late_by_client", "late_by_us")}
                        | {"areas": [a for a in s["areas"] if a["client_delay_days"] or a["our_delay_days"]]})  # fmt: skip
    return jsonable_encoder({
        "sites": rows,
        "client_delay_days": sum(r["client_delay_days"] for r in rows),
        "our_delay_days": sum(r["our_delay_days"] for r in rows),
    })  # fmt: skip
