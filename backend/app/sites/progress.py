# ruff: noqa: E501
"""A site's progress, one way everywhere (the site page, its floors, the 3D, the portal, the sites
list, the dashboard and the nightly summary).

An area's progress is its counted steps' weights (the site's own weights where the planner
changed the stage days; a hold point counts once certified), or what the approved daily reports
say was done, whichever is more. A floor's or the site's progress is its areas' progress weighted
by their quantities, read live from the areas, so a site whose areas have done steps never shows
0% because a cached total was not rolled up (what the DEMO X-ray site showed: its demo wrote the
steps and areas but never rolled them up to the floors and the site).

refresh() writes the cached numbers (the scope, its node and the site columns) for code that
sorts or filters on them; the readers use rollup() / site_percents()."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.sites.models import AreaScope, Site, SiteNode, StageTemplate, StageTemplateStep, Task

PCT = Decimal("0.01")


def counts(task: Task) -> bool:
    """A step that counts towards progress: certified, or done when it is not a hold point."""
    if task.status == "certified":
        return True
    return task.status == "done" and not (task.step and task.step.hold_point)


def scope_percent(db: Session, scope: AreaScope, tasks: list[Task] | None = None) -> Decimal:
    """The one formula for an area."""
    from app.sites.work import site_weights  # noqa: PLC0415

    if tasks is None:
        tasks = list(db.scalars(select(Task).where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))))
    template = db.get(StageTemplate, scope.stage_template_id) if scope.stage_template_id else None
    weights = site_weights(db, scope.site_id, template) if template else {}
    from_steps = sum((weights.get(t.step.id, Decimal(t.step.weight_percent)) for t in tasks if t.step and counts(t)), Decimal(0))
    from_reports = (
        min(Decimal(100), Decimal(scope.dpr_done_qty or 0) * 100 / Decimal(scope.qty)) if scope.qty and Decimal(scope.qty) > 0 else Decimal(0)
    )
    return min(Decimal(100), max(from_steps, from_reports)).quantize(PCT)


def _weighted(pairs: list[tuple[Decimal, Decimal]]) -> Decimal:
    total = sum((q for q, _ in pairs), Decimal(0))
    if total <= 0:
        # areas without a quantity: their plain average (a site with done steps is never 0%)
        return (sum((p for _, p in pairs), Decimal(0)) / len(pairs)).quantize(PCT, ROUND_HALF_UP) if pairs else Decimal(0)
    return (sum((q * p for q, p in pairs), Decimal(0)) / total).quantize(PCT, ROUND_HALF_UP)


def _steps_done(db: Session, site_ids: list[int]) -> dict[int, Decimal]:
    """Each area's counted steps straight from its tasks (the template weights): for an area whose
    stored number was never updated after its steps were written."""
    counted = or_(Task.status == "certified", and_(Task.status == "done", StageTemplateStep.hold_point.is_(False)))
    rows = db.execute(
        select(Task.area_scope_id, func.sum(StageTemplateStep.weight_percent))
        .join(StageTemplateStep, StageTemplateStep.id == Task.step_id)
        .where(Task.site_id.in_(site_ids), Task.parent_task_id.is_(None), Task.area_scope_id.is_not(None), counted)
        .group_by(Task.area_scope_id)
    ).all()
    return {sid: min(Decimal(100), Decimal(w or 0)) for sid, w in rows}


def _area_rows(db: Session, site_ids: list[int]) -> list[tuple[int, int, Decimal, Decimal]]:
    """(site, node, quantity, progress) of every area: its stored progress, or its steps when the
    stored number is 0 though steps are done."""
    steps = _steps_done(db, site_ids)
    rows = db.execute(select(AreaScope.id, AreaScope.site_id, AreaScope.node_id, AreaScope.qty, AreaScope.progress_percent).where(AreaScope.site_id.in_(site_ids))).all()
    out = []
    for aid, sid, node_id, qty, pct in rows:
        p = Decimal(pct or 0)
        if p == 0 and steps.get(aid):
            p = steps[aid]
        out.append((sid, node_id, Decimal(qty or 0), p))
    return out


def rollup(db: Session, site_id: int) -> tuple[Decimal, dict[int, Decimal]]:
    """The site's progress and each node's (over its whole subtree), from its areas."""
    by_node: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for _sid, node_id, qty, pct in _area_rows(db, [site_id]):
        by_node[node_id].append((qty, pct))
    nodes = db.execute(select(SiteNode.id, SiteNode.parent_id).where(SiteNode.site_id == site_id)).all()
    kids: dict[int | None, list[int]] = defaultdict(list)
    for nid, parent in nodes:
        kids[parent].append(nid)
    memo: dict[int, list[tuple[Decimal, Decimal]]] = {}

    def subtree(nid: int) -> list[tuple[Decimal, Decimal]]:
        if nid not in memo:
            out = list(by_node.get(nid, []))
            for child in kids.get(nid, []):
                out.extend(subtree(child))
            memo[nid] = out
        return memo[nid]

    per_node = {nid: _weighted(subtree(nid)) for nid, _ in nodes}
    return _weighted([p for pairs in by_node.values() for p in pairs]), per_node


def site_percents(db: Session, site_ids: list[int]) -> dict[int, Decimal]:
    """Many sites at once (the sites list, the dashboard): the same numbers as rollup()."""
    if not site_ids:
        return {}
    by_site: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for sid, _node, qty, pct in _area_rows(db, site_ids):
        by_site[sid].append((qty, pct))
    return {sid: _weighted(by_site.get(sid, [])) for sid in site_ids}


def site_percent(db: Session, site_id: int) -> Decimal:
    """One site's progress (the same as rollup()'s total, in one query)."""
    return site_percents(db, [site_id])[site_id]


def refresh(db: Session, site: Site, scopes: list[AreaScope] | None = None) -> Decimal:
    """Recompute the given areas (all when None) and write the cached numbers of every node and
    the site. Returns the site's progress."""
    if scopes is None:
        scopes = list(db.scalars(select(AreaScope).where(AreaScope.site_id == site.id)))
    for sc in scopes:
        sc.progress_percent = scope_percent(db, sc)
    db.flush()
    total, per_node = rollup(db, site.id)
    for n in db.scalars(select(SiteNode).where(SiteNode.site_id == site.id)):
        n.progress_percent = per_node.get(n.id, Decimal(0))
    site.progress_percent = total
    db.flush()
    return total
