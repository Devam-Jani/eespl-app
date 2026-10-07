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
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sites import service
from app.sites.models import AreaScope, Site, SiteNode, StageTemplate, Task
from app.tenders.models import BoqLine

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
    start = site.start_date or date.today()
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


def _counts(task: Task) -> bool:
    if task.status == "certified":
        return True
    return task.status == "done" and not (task.step and task.step.hold_point)


def refresh_scope(db: Session, scope: AreaScope) -> None:
    """Recompute one scope, then its node and the nodes above it, then the site."""
    tasks = db.scalars(
        select(Task).where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
    ).all()
    scope.progress_percent = sum(
        (Decimal(t.step.weight_percent) for t in tasks if t.step and _counts(t)), Decimal(0)
    ).quantize(PCT)
    db.flush()
    site = db.get(Site, scope.site_id)
    all_nodes = service.nodes(db, scope.site_id)
    refresh_nodes(db, site, all_nodes, service.ancestors(all_nodes, scope.node_id))


def refresh_nodes(db: Session, site: Site, all_nodes: list[SiteNode], node_ids: list[int]) -> None:
    """Recompute the given nodes (each over its whole subtree) and the site."""
    rows = db.execute(
        select(AreaScope.node_id, AreaScope.qty, AreaScope.progress_percent).where(
            AreaScope.site_id == site.id
        )
    ).all()
    by_node: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)
    for node_id, qty, pct in rows:
        by_node[node_id].append((Decimal(qty), Decimal(pct)))
    by_id = {n.id: n for n in all_nodes}
    kids = service.children_map(all_nodes)

    def weighted(pairs: list[tuple[Decimal, Decimal]]) -> Decimal:
        total = sum((q for q, _ in pairs), Decimal(0))
        if total <= 0:
            return Decimal(0)
        return (sum((q * p for q, p in pairs), Decimal(0)) / total).quantize(PCT, ROUND_HALF_UP)

    def subtree(node_id: int) -> list[tuple[Decimal, Decimal]]:
        out = list(by_node.get(node_id, []))
        for child in kids.get(node_id, []):
            out.extend(subtree(child.id))
        return out

    for node_id in node_ids:
        if node_id in by_id:
            by_id[node_id].progress_percent = weighted(subtree(node_id))
    site.progress_percent = weighted([p for pairs in by_node.values() for p in pairs])
    db.flush()


def refresh_site(db: Session, site: Site) -> None:
    """Everything (after structure or scope changes, not on every task update)."""
    for scope in db.scalars(select(AreaScope).where(AreaScope.site_id == site.id)):
        tasks = db.scalars(
            select(Task).where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
        ).all()
        scope.progress_percent = sum(
            (Decimal(t.step.weight_percent) for t in tasks if t.step and _counts(t)), Decimal(0)
        ).quantize(PCT)
    db.flush()
    all_nodes = service.nodes(db, site.id)
    refresh_nodes(db, site, all_nodes, [n.id for n in all_nodes])
