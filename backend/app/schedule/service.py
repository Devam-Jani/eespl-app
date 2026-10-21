# ruff: noqa: E501  (the build-up rows and queries read better unwrapped)
"""Handover dates and the schedule, and the project plan with its lots.

Per place: the site engineer enters the date the client promised to hand it over (after talking
to the client) and who promised it. The supervisor confirms the real handover: received on a date,
or "not received yet"; what the client says does not count until then (that confirmation is the
work-front-ready tick, with its date). The target finish = the confirmed handover + the days of the
place's stages (the stage template's days, changed per site): 5 + 2 + 8 = 15 days.

Delay is split: the client's (handed over later than promised) and ours (finished later than the
target from the real handover)."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.closeout import handover
from app.schedule.models import (
    MaterialLot,
    MaterialLotLine,
    ProjectPlanLine,
    SiteStageDays,
)
from app.sites.models import AreaScope, Site, SiteMember, SiteNode, StageTemplate, StageTemplateStep
from app.timefmt import IST

ZERO = Decimal(0)


def today() -> date:
    return datetime.now(IST).date()


# --- stage days and the target finish ------------------------------------------------------------


def stage_days(db: Session, site_id: int, template_id: int) -> list[dict]:
    """The template's stages with their days on this site (the site's own, else the template's)."""
    own = dict(
        db.execute(
            select(SiteStageDays.step_id, SiteStageDays.days).where(
                SiteStageDays.site_id == site_id
            )
        ).all()
    )
    steps = db.scalars(
        select(StageTemplateStep)
        .where(StageTemplateStep.template_id == template_id)
        .order_by(StageTemplateStep.sort_order)
    ).all()
    return [
        {
            "step_id": s.id,
            "name": s.name,
            "typical_days": s.typical_days,
            "days": own.get(s.id, s.typical_days),
            "site_value": s.id in own,
        }
        for s in steps
    ]


def node_days(db: Session, node: SiteNode) -> int | None:
    """The days of the place's work: its stages' days (the longest of its BOQ items)."""
    templates = set(
        db.scalars(select(AreaScope.stage_template_id).where(AreaScope.node_id == node.id))
    )
    if not templates:
        return None
    return max(sum(s["days"] for s in stage_days(db, node.site_id, t)) for t in templates)


def finished_on(db: Session, node: SiteNode) -> date | None:
    rows = db.execute(
        select(AreaScope.progress_percent, AreaScope.completed_at).where(
            AreaScope.node_id == node.id
        )
    ).all()
    if not rows or any(Decimal(p) < 100 or c is None for p, c in rows):
        return None
    return max(c for _p, c in rows).astimezone(IST).date()


def node_schedule(db: Session, node: SiteNode, on: date | None = None) -> dict:
    on = on or today()
    days = node_days(db, node)
    received = node.handover_received_on if node.handover_status == "received" else None
    target = received + timedelta(days=days) if received and days is not None else None
    done = finished_on(db, node)
    client_delay = None
    if node.handover_promised_on:
        until = received or (on if on > node.handover_promised_on else None)
        if until is not None:
            client_delay = max(0, (until - node.handover_promised_on).days)
    our_delay = None
    if target is not None:
        end = done or (on if on > target else None)
        our_delay = max(0, (end - target).days) if end else 0
    return {
        "node_id": node.id,
        "promised_on": node.handover_promised_on,
        "promised_by": node.handover_promised_by,
        "client_says_on": node.handover_client_says_on,
        "status": node.handover_status or ("awaited" if node.handover_promised_on else None),
        "received_on": received,
        "checked_at": node.handover_checked_at,
        "stage_days": days,
        "target_finish": target,
        "finished_on": done,
        "client_delay_days": client_delay,
        "our_delay_days": our_delay,
        "overdue_handover": bool(node.handover_promised_on and not received and on > node.handover_promised_on),
        "overdue_finish": bool(target and not done and on > target),
        **handover.summary(node),
    }  # fmt: skip


def site_schedule(db: Session, site: Site) -> dict:
    from app.sitecontrol.service import node_label  # noqa: PLC0415

    nodes = db.scalars(
        select(SiteNode)
        .where(SiteNode.site_id == site.id, SiteNode.id.in_(select(AreaScope.node_id).where(AreaScope.site_id == site.id)))
        .order_by(SiteNode.sort_order, SiteNode.id)
    ).all()  # fmt: skip
    rows = []
    for n in nodes:
        s = node_schedule(db, n)
        rows.append(s | {"place": node_label(db, n), "front_ready": n.front_ready})
    # the places with a handover date first (late ones at the top), then the rest in site order
    rows.sort(
        key=lambda r: (
            r["promised_on"] is None,
            -((r["our_delay_days"] or 0) + (r["client_delay_days"] or 0)),
        )
    )
    return {
        "site_id": site.id,
        "site": f"{site.code} {site.name}",
        "areas": rows,
        "client_delay_days": sum(r["client_delay_days"] or 0 for r in rows),
        "our_delay_days": sum(r["our_delay_days"] or 0 for r in rows),
        "late_by_client": sum(1 for r in rows if r["client_delay_days"]),
        "late_by_us": sum(1 for r in rows if r["our_delay_days"]),
    }


def is_supervisor(db: Session, principal, site_id: int) -> bool:
    """Who may confirm a handover: the site's supervisor (by role or as the site's supervisor
    member), or someone who edits every site (director, office admin)."""
    if principal.permissions.get("site.edit") == "all":
        return True
    codes = {r.code for r in principal.user.roles}
    if "site_supervisor" in codes:
        return True
    return bool(
        db.scalar(
            select(func.count())
            .select_from(SiteMember)
            .where(
                SiteMember.site_id == site_id,
                SiteMember.user_id == principal.user.id,
                SiteMember.role_on_site == "supervisor",
            )
        )
    )


def confirm_handover(db: Session, node: SiteNode, user_id, received: bool, on: date | None) -> None:
    """The supervisor's word: received on a date (the work front is ready), or not yet."""
    node.handover_checked_at = datetime.now(UTC)
    if not received:
        node.handover_status, node.handover_received_on = "not_received", None
        return
    on = on or today()
    node.handover_status, node.handover_received_on = "received", on
    node.handover_confirmed_by = user_id
    from app.process import engine  # noqa: PLC0415

    engine.emit(
        db,
        "handover_received",
        subject=f"handover:{node.id}",
        site_id=node.site_id,
        actor_id=user_id,
        dedupe=f"handover_received:{node.id}:{on.isoformat()}",
        data={"node_id": node.id},
    )


def on_area_finished(db: Session, scope: AreaScope) -> None:
    """Every BOQ item of the place done: the target-finish to-do closes."""
    node = db.get(SiteNode, scope.node_id)
    if node is None or finished_on(db, node) is None:
        return
    from app.process import engine  # noqa: PLC0415

    engine.emit(
        db,
        "area_finished",
        subject=f"finish:{node.id}",
        site_id=node.site_id,
        dedupe=f"area_finished:{node.id}:{finished_on(db, node).isoformat()}",
        data={"node_id": node.id},
    )


def timed_events(db: Session, at: datetime) -> int:
    """Daily: a promised handover passed and not confirmed; a target finish passed."""
    from app.process import engine  # noqa: PLC0415
    from app.sitecontrol.service import node_label  # noqa: PLC0415

    on = at.astimezone(IST).date()
    n = 0
    for node in db.scalars(
        select(SiteNode)
        .join(Site, Site.id == SiteNode.site_id)
        .where(SiteNode.handover_promised_on.is_not(None), Site.status == "active")
    ):
        s = node_schedule(db, node, on)
        place = node_label(db, node)
        if s["overdue_handover"]:
            n += bool(
                engine.emit(
                    db,
                    "handover_overdue",
                    subject=f"handover:{node.id}",
                    site_id=node.site_id,
                    at=at,
                    dedupe=f"handover_overdue:{node.id}:{node.handover_promised_on.isoformat()}",
                    data={"area": place, "node_id": node.id,
                          "promised": f"{node.handover_promised_on:%d %b %Y}",
                          "promised_by": node.handover_promised_by or "the client",
                          "places": [{"place": place, "qty": f"promised {node.handover_promised_on:%d %b}"}]},
                )
            )  # fmt: skip
        if s["overdue_finish"]:
            n += bool(
                engine.emit(
                    db,
                    "finish_overdue",
                    subject=f"finish:{node.id}",
                    site_id=node.site_id,
                    at=at,
                    dedupe=f"finish_overdue:{node.id}:{s['target_finish'].isoformat()}",
                    data={"area": place, "node_id": node.id,
                          "target": f"{s['target_finish']:%d %b %Y}",
                          "received": f"{s['received_on']:%d %b %Y}",
                          "places": [{"place": place, "qty": f"target {s['target_finish']:%d %b}"}]},
                )
            )  # fmt: skip
    return n


# --- the project plan and its lots ---------------------------------------------------------------


def q3(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def plan(db: Session, site: Site) -> dict:
    """Per product: planned for the whole project (fixed by planning, else as computed from the
    BOQ and survey quantities), called off in lots, delivered, issued and the balance."""
    from app.costing.prices import settings  # noqa: PLC0415
    from app.masters.models import Product  # noqa: PLC0415
    from app.team.service import material_plan  # noqa: PLC0415

    computed = {p["product_id"]: p for p in material_plan(db, site)["products"]}
    fixed = {
        r.product_id: r
        for r in db.scalars(select(ProjectPlanLine).where(ProjectPlanLine.site_id == site.id))
    }
    called: dict[int, Decimal] = {}
    pending: dict[int, Decimal] = {}
    for lot_status, pid, qty in db.execute(
        select(MaterialLot.status, MaterialLotLine.product_id, MaterialLotLine.qty)
        .join(MaterialLotLine, MaterialLotLine.lot_id == MaterialLot.id)
        .where(MaterialLot.site_id == site.id, MaterialLot.status != "rejected")
    ):
        target = called if lot_status == "approved" else pending
        target[pid] = target.get(pid, ZERO) + Decimal(qty)
    tol = Decimal(settings(db).calloff_tolerance_percent)
    rows = []
    for pid in sorted(set(computed) | set(fixed) | set(called) | set(pending)):
        p = db.get(Product, pid)
        c = computed.get(pid, {})
        f = fixed.get(pid)
        planned = Decimal(f.planned_qty) if f else Decimal(c.get("planned") or 0)
        rows.append({
            "product_id": pid, "product": p.name, "unit": p.unit,
            "planned": q3(planned), "computed": q3(c.get("planned")), "fixed": f is not None,
            "note": f.note if f else None,
            "called_off": q3(called.get(pid)), "pending": q3(pending.get(pid)),
            "delivered": q3(c.get("delivered")), "issued": q3(c.get("issued")),
            "balance": q3(planned - called.get(pid, ZERO)),
            "limit": q3(planned * (1 + tol / 100)),
        })  # fmt: skip
    lots = db.scalars(
        select(MaterialLot).where(MaterialLot.site_id == site.id).order_by(MaterialLot.id.desc())
    ).all()
    return {
        "site_id": site.id,
        "tolerance_percent": tol,
        "products": rows,
        "lots": [lot_out(db, x) for x in lots],
    }


def lot_out(db: Session, lot: MaterialLot) -> dict:
    from app.execution.common import names  # noqa: PLC0415
    from app.masters.models import Product  # noqa: PLC0415
    from app.material.models import Indent  # noqa: PLC0415
    from app.sitecontrol.service import node_label  # noqa: PLC0415

    who = names(db, [lot.created_by, lot.decided_by])
    indent = db.get(Indent, lot.indent_id) if lot.indent_id else None
    return {
        "id": lot.id, "code": lot.code, "status": lot.status, "over_plan": lot.over_plan,
        "reason": lot.reason, "days": lot.days, "need_by": lot.need_by,
        "places": [node_label(db, db.get(SiteNode, n)) for n in lot.node_ids if db.get(SiteNode, n)],
        "lines": [{"product_id": ln.product_id, "product": db.get(Product, ln.product_id).name,
                   "unit": db.get(Product, ln.product_id).unit, "qty": ln.qty} for ln in lot.lines],
        "called_by": who.get(lot.created_by), "called_at": lot.created_at,
        "decided_by": who.get(lot.decided_by), "decided_at": lot.decided_at,
        "decision_note": lot.decision_note,
        "indent_id": lot.indent_id, "indent": indent.code if indent else None,
    }  # fmt: skip


def over_plan(
    db: Session, site: Site, lines: list[dict], exclude_lot: int | None = None
) -> list[dict]:
    """The products this call-off takes past the plan's balance plus the tolerance."""
    current = {r["product_id"]: r for r in plan(db, site)["products"]}
    out = []
    for ln in lines:
        r = current.get(ln["product_id"])
        planned = Decimal(r["planned"]) if r else ZERO
        before = (Decimal(r["called_off"]) + Decimal(r["pending"])) if r else ZERO
        if exclude_lot:
            before -= sum(
                (Decimal(x.qty) for x in db.scalars(
                    select(MaterialLotLine).where(MaterialLotLine.lot_id == exclude_lot, MaterialLotLine.product_id == ln["product_id"])
                )),
                ZERO,
            )  # fmt: skip
        limit = Decimal(r["limit"]) if r else ZERO
        if before + Decimal(ln["qty"]) > limit:
            out.append({"product_id": ln["product_id"], "product": r["product"] if r else str(ln["product_id"]),
                        "planned": q3(planned), "already": q3(before), "asked": q3(ln["qty"]), "limit": q3(limit)})  # fmt: skip
    return out


def next_lot_code(db: Session, site: Site) -> str:
    n = db.scalar(
        select(func.count()).select_from(MaterialLot).where(MaterialLot.site_id == site.id)
    )
    return f"{site.code}/L{n + 1}"


__all__ = ["StageTemplate"]
