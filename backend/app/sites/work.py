"""What we do where (area scopes), the tasks that come from it, and progress.

Scope: a BOQ line is spread over the nodes picked for it. The quantity is split by area_sqm
when every picked node has one, otherwise equally; the remainder of the rounding goes to the
last node, so the parts add up exactly.

Tasks: one per (area scope × template step). Each scope's steps run one after another from the
site start date, each lasting the step's typical_days; a step depends on the step before it.
Generating again only adds what is missing; nothing that exists is changed or deleted.

Progress (stored when a task changes, see refresh_scope):
- scope %: the sum of the weights of its steps that are done or certified. A hold-point step
  counts only once it is certified.
- node %: qty-weighted average of the scopes on the node and every node below it.
- site %: qty-weighted average of all its scopes.
"""

import re
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sites import service
from app.sites.models import AreaScope, Site, SiteNode, StageTemplate, Task
from app.tenders.models import BoqLine
from app.timefmt import ist_today

QTY = Decimal("0.001")
PCT = Decimal("0.01")
DONE = ("done", "certified")


# --- template suggestion ------------------------------------------------------------------------


# words every waterproofing line has: they tell templates apart no better than chance
GENERIC = {
    "water",
    "proofing",
    "waterproofing",
    "treatment",
    "area",
    "areas",
    "work",
    "works",
    "system",
    "the",
    "and",
    "of",
    "on",
    "in",
    "with",
    "for",
    "to",
    "a",
    "by",
    "as",
    "at",
    "providing",
    "applying",
    "laying",
    "including",
    "complete",
    "etc",
    "per",
    "all",
}


def _words(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - GENERIC


def suggest_template(line: BoqLine, templates: list[StageTemplate]) -> StageTemplate | None:
    """The line's system's template, else the template whose keywords and name share the most
    words with the line. Words in the line's title (the text before " — ", e.g. "WATER
    PROOFING TREATMENT ON TERRACE AREA") count three times as much as words in the long
    specification after it."""
    active = [t for t in templates if t.is_active]
    if line.system_id:
        for t in active:
            if t.system_id == line.system_id:
                return t
    title = _words(line.description.split(" — ")[0])
    words = _words(line.description)
    best, best_score = None, 0
    for t in active:
        vocab = _words(t.keywords) | _words(t.name)
        score = 3 * len(title & vocab) + len(words & vocab)
        if score > best_score:
            best, best_score = t, score
    return best


# --- splitting ----------------------------------------------------------------------------------


def split_qty(total: Decimal, nodes: list[SiteNode]) -> list[Decimal]:
    if not nodes:
        return []
    areas = [n.area_sqm for n in nodes]
    if all(a is not None and a > 0 for a in areas):
        weights = [Decimal(a) for a in areas]
    else:
        weights = [Decimal(1)] * len(nodes)
    whole = sum(weights)
    parts = [(total * w / whole).quantize(QTY, ROUND_HALF_UP) for w in weights[:-1]]
    parts.append(total - sum(parts, Decimal(0)))
    return parts


def qty_check(db: Session, site: Site, lines: list[BoqLine]) -> dict[int, dict]:
    """Per BOQ line: its qty, what is assigned to areas, and ok / under / over / no_qty."""
    assigned = dict(
        db.execute(
            select(AreaScope.boq_line_id, func.sum(AreaScope.qty))
            .where(AreaScope.site_id == site.id, AreaScope.boq_line_id.is_not(None))
            .group_by(AreaScope.boq_line_id)
        ).all()
    )
    out = {}
    for ln in lines:
        got = Decimal(assigned.get(ln.id) or 0)
        if ln.qty is None:
            state = "no_qty"  # QRO: no BOQ quantity to check against
        elif abs(got - ln.qty) < QTY:
            state = "ok"
        elif got < ln.qty:
            state = "under"
        else:
            state = "over"
        out[ln.id] = {
            "boq_qty": ln.qty,
            "assigned": got,
            "difference": (got - (ln.qty or 0)),
            "state": state,
        }
    return out


# --- tasks --------------------------------------------------------------------------------------


def generate_tasks(db: Session, site: Site, user_id) -> dict[str, int]:
    """Add the missing (scope × step) tasks. Existing tasks are kept as they are."""
    start = site.start_date or ist_today()
    scopes = list(db.scalars(select(AreaScope).where(AreaScope.site_id == site.id)))
    existing = {
        (t.area_scope_id, t.step_id): t
        for t in db.scalars(
            select(Task).where(Task.site_id == site.id, Task.parent_task_id.is_(None))
        )
    }
    templates = {t.id: t for t in db.scalars(select(StageTemplate))}
    added = kept = 0
    for scope in scopes:
        cursor = start
        previous: Task | None = None
        for order, step in enumerate(templates[scope.stage_template_id].steps, start=1):
            days = max(1, step.typical_days or 1)
            task = existing.get((scope.id, step.id))
            if task is None:
                task = Task(
                    site_id=site.id,
                    node_id=scope.node_id,
                    area_scope_id=scope.id,
                    step_id=step.id,
                    name=step.name,
                    sort_order=order,
                    planned_start=cursor,
                    planned_end=cursor + timedelta(days=days - 1),
                    depends_on=[previous.id] if previous else [],
                    created_by=user_id,
                )
                db.add(task)
                db.flush()
                added += 1
            else:
                kept += 1
            cursor = (task.planned_end or cursor) + timedelta(days=1)
            previous = task
    db.flush()
    return {"added": added, "kept": kept}


# --- progress -----------------------------------------------------------------------------------


def weights_by_days(days: list[int]) -> list[Decimal]:
    """Weights from the stages' days, to two decimals, totalling exactly 100 (the remainder of
    the rounding goes to the longest stage)."""
    total = sum(max(0, d) for d in days)
    if not days:
        return []
    if total <= 0:
        days, total = [1] * len(days), len(days)
    out = [(Decimal(100) * max(0, d) / total).quantize(PCT, ROUND_HALF_UP) for d in days]
    out[max(range(len(days)), key=lambda i: days[i])] += Decimal(100) - sum(out, Decimal(0))
    return out


def site_weights(db: Session, site_id: int, template: StageTemplate) -> dict[int, Decimal]:
    """The weight of each step on this site: from the site's own stage days where the planner
    changed them (Prompt 20), else the template's weights."""
    from app.schedule.models import SiteStageDays  # noqa: PLC0415

    own = dict(
        db.execute(
            select(SiteStageDays.step_id, SiteStageDays.days).where(
                SiteStageDays.site_id == site_id,
                SiteStageDays.step_id.in_([s.id for s in template.steps] or [0]),
            )
        ).all()
    )
    if not own:
        return {s.id: Decimal(s.weight_percent) for s in template.steps}
    days = [own.get(s.id, s.typical_days or 1) for s in template.steps]
    return dict(zip([s.id for s in template.steps], weights_by_days(days), strict=True))


def _counts(task: Task) -> bool:
    from app.sites.progress import counts  # noqa: PLC0415

    return counts(task)


def refresh_scope(db: Session, scope: AreaScope) -> None:
    """Recompute one scope, then its node and the nodes above it, then the site."""
    tasks = db.scalars(
        select(Task).where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
    ).all()
    before = scope.progress_percent
    from app.sites.progress import scope_percent  # noqa: PLC0415

    scope.progress_percent = scope_percent(db, scope, list(tasks))
    # the day the area was finished (for the schedule: our delay against the target finish)
    if scope.progress_percent >= 100 and scope.completed_at is None:
        scope.completed_at = datetime.now(UTC)
        from app.schedule import service as schedule  # noqa: PLC0415

        db.flush()
        schedule.on_area_finished(db, scope)
    elif scope.progress_percent < 100:
        scope.completed_at = None
    db.flush()
    # the stage's last task done: billing gets a "ready to bill" item
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    sitecontrol.on_scope_refresh(db, scope, before)
    site = db.get(Site, scope.site_id)
    all_nodes = service.nodes(db, scope.site_id)
    refresh_nodes(db, site, all_nodes, service.ancestors(all_nodes, scope.node_id))


def refresh_nodes(db: Session, site: Site, all_nodes: list[SiteNode], node_ids: list[int]) -> None:
    """Write the cached progress of the given nodes (each over its whole subtree) and the site."""
    from app.sites.progress import rollup  # noqa: PLC0415

    total, per_node = rollup(db, site.id)
    wanted = set(node_ids)
    for n in all_nodes:
        if n.id in wanted:
            n.progress_percent = per_node.get(n.id, Decimal(0))
    site.progress_percent = total
    db.flush()


def refresh_site(db: Session, site: Site) -> None:
    """Everything (after structure or scope changes, not on every task update): every area by the
    same formula as a task update, then the floors and the site."""
    from app.sites.progress import refresh  # noqa: PLC0415

    refresh(db, site)

