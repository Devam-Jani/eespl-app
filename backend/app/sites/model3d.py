"""The site model for the 3D view: every node with its work status, in one call.

Per node, from the node's OWN scopes and tasks (top-level tasks only):
  percent                 the stored progress (the node and everything below it)
  counts                  tasks by status
  current_step            the first step in progress (else the first blocked one)
  next_step               the first step not started yet
  is_late                 a task whose planned end has passed and is not done/certified
  waiting_certification   a hold-point step that is done but not certified
  has_scope               the node has at least one area scope, or an accepted AutoCAD area (work
                          to do there, so it shows as not started rather than "no work here")
  template_ids            the stage templates of its scopes (for the template filter)
  timeline                per top-level task [name, planned_start, planned_end, actual_start,
                          actual_end, status, hold_point, certified_on]: the date slider shows the
                          status on a past date from these (no status history is kept)

Nothing is recomputed: percent is what task updates stored; the rest is one read of the site's
tasks. `version` changes whenever a node, scope or task changes, for cheap polling (ETag).
"""

import hashlib
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sites.models import AreaScope, SiteNode, StageTemplateStep, Task
from app.timefmt import ist_today

DONE = ("done", "certified")
STATUSES = ("not_started", "in_progress", "done", "certified", "blocked")


def version(db: Session, site_id: int) -> str:
    """Changes when any node, scope or task of the site changes (or is added / removed)."""
    parts = []
    from app.takeoff.models import CadArea, CadFile  # noqa: PLC0415

    cad = db.execute(
        select(func.count(), func.max(CadArea.updated_at))
        .join(CadFile, CadFile.id == CadArea.cad_file_id)
        .where(CadFile.site_id == site_id, CadArea.status == "accepted")
    ).one()
    parts.append(f"cad{cad[0]}:{cad[1].isoformat() if cad[1] else '-'}")
    from app.building.models import BuildingModel  # noqa: PLC0415

    built = db.scalar(
        select(func.max(BuildingModel.version)).where(BuildingModel.site_id == site_id)
    )
    parts.append(f"b{built or 0}")
    for model in (SiteNode, AreaScope, Task):
        count, latest = db.execute(
            select(func.count(), func.max(model.updated_at)).where(model.site_id == site_id)
        ).one()
        parts.append(f"{count}:{latest.isoformat() if latest else '-'}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _d(v: date | None) -> str | None:
    return v.isoformat() if v else None


def _timeline(t) -> list:
    """[name, planned_start, planned_end, actual_start, actual_end, status, hold, certified]"""
    certified = t.certified_at.date() if t.certified_at else None
    return [t.name, _d(t.planned_start), _d(t.planned_end), _d(t.actual_start),
            _d(t.actual_end), t.status, bool(t.hold_point), _d(certified)]  # fmt: skip


def build(db: Session, site_id: int, client: bool = False) -> dict[str, Any]:
    from app.sites import progress  # noqa: PLC0415

    _total, live = progress.rollup(db, site_id)
    nodes = db.scalars(
        select(SiteNode)
        .where(SiteNode.site_id == site_id)
        .order_by(SiteNode.parent_id.nulls_first(), SiteNode.sort_order, SiteNode.id)
    ).all()
    templates: dict[int, set[int]] = defaultdict(set)
    for node_id, template_id in db.execute(
        select(AreaScope.node_id, AreaScope.stage_template_id).where(AreaScope.site_id == site_id)
    ):
        templates[node_id].add(template_id)
    rows = db.execute(
        select(Task.node_id, Task.name, Task.status, Task.planned_start, Task.planned_end,
               Task.actual_start, Task.actual_end, Task.certified_at, Task.sort_order,
               Task.area_scope_id, StageTemplateStep.hold_point)
        .outerjoin(StageTemplateStep, StageTemplateStep.id == Task.step_id)
        .where(Task.site_id == site_id, Task.parent_task_id.is_(None))
        .order_by(Task.node_id, Task.area_scope_id, Task.sort_order, Task.id)
    ).all()  # fmt: skip
    tasks: dict[int, list] = defaultdict(list)
    for row in rows:
        if row.node_id is not None:
            tasks[row.node_id].append(row)
    today = ist_today()
    from app.takeoff.service import node_sqm  # noqa: PLC0415

    autocad = node_sqm(db, site_id)  # accepted AutoCAD areas, shown on hover
    out = []
    for n in nodes:
        own = tasks.get(n.id, [])
        counts = dict.fromkeys(STATUSES, 0)
        for t in own:
            counts[t.status] += 1
        current = next((t.name for t in own if t.status == "in_progress"), None) or next(
            (t.name for t in own if t.status == "blocked"), None
        )
        upcoming = next((t.name for t in own if t.status == "not_started"), None)
        out.append(
            {
                "id": n.id,
                "parent_id": n.parent_id,
                "kind": n.kind,
                "name": n.name,
                "level_no": n.level_no,
                "area_sqm": float(n.area_sqm) if n.area_sqm is not None else None,
                "autocad_sqm": round(autocad[n.id], 2) if n.id in autocad else None,
                "sort_order": n.sort_order,
                "status": {
                    "percent": float(live.get(n.id, 0)),
                    "counts": counts,
                    "tasks": len(own),
                    "current_step": current,
                    "next_step": upcoming,
                    "is_late": any(
                        t.planned_end and t.planned_end < today and t.status not in DONE
                        for t in own
                    ),
                    "waiting_certification": any(t.hold_point and t.status == "done" for t in own),
                    "has_scope": n.id in templates or n.id in autocad,
                    "template_ids": sorted(templates.get(n.id, ())),
                },
                "timeline": [_timeline(t) for t in own],
            }
        )
    from app.building.service import payload  # noqa: PLC0415

    return {"site_id": site_id, "nodes": out, "building": payload(db, site_id, client=client)}
