"""Survey maths and the consumption engine.

Per area (metres, Decimal):
  floor area   = (L x W, or the polygon's area by the shoelace formula, or the area typed in)
                 - deductions (never below 0)
  perimeter    = 2 (L + W) or the polygon's sides (typed in for a direct area; editable)
  upturn area  = perimeter x upturn
  wall area    = perimeter x wall height            (area types that include walls)
  sunk sides   = perimeter x sunk depth             (area types that need a sunk depth)
  treated area = (floor + upturn + wall + sunk) x count

Per product: qty = treated area x consumption per unit x (1 + wastage %), the wastage taken from
the area's override, else its area type, else the system component. Totals per area, floor,
tower and survey; whole packs only on the survey (or chosen floors) total, never per area.
"""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.crm.models import Lead
from app.masters.models import Product, System, SystemComponent
from app.material import service as material
from app.survey.models import (
    CAMERA_METHODS,
    AreaType,
    Survey,
    SurveyArea,
    SurveyBoqLink,
    SurveySettings,
)
from app.tenders.models import Tender

ZERO = Decimal(0)
Q3 = Decimal("0.001")
SQFT_PER_SQM = Decimal("10.7639104")


def q3(v) -> Decimal:
    return Decimal(v).quantize(Q3, ROUND_HALF_UP)


def settings(db: Session) -> SurveySettings:
    s = db.get(SurveySettings, 1)
    if s is None:
        s = SurveySettings(id=1)
        db.add(s)
        db.flush()
    return s


# --- geometry ------------------------------------------------------------------------------------


def shoelace(points: list[list[float]] | None) -> Decimal:
    """Area of a simple polygon (metres) by the shoelace formula."""
    if not points or len(points) < 3:
        return ZERO
    pts = [(Decimal(str(x)), Decimal(str(y))) for x, y in points]
    s = sum(
        (x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True)), ZERO
    )
    return abs(s) / 2


def polygon_perimeter(points: list[list[float]] | None) -> Decimal:
    if not points or len(points) < 2:
        return ZERO
    pts = [(float(x), float(y)) for x, y in points]
    return Decimal(str(sum(math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1], strict=True))))


def floor_number(label: str | None) -> int | None:
    """For sorting floors: B2 = -2, B1 = -1, G = 0, 1, 2 ... terrace / roof last."""
    if not label:
        return None
    t = label.strip().lower()
    if m := re.fullmatch(r"(?:b|basement)\s*-?\s*(\d+)", t):
        return -int(m.group(1))
    if t in ("g", "gf", "ground", "ground floor", "stilt", "podium"):
        return 0
    if t in ("terrace", "roof", "top"):
        return 999
    if m := re.search(r"(\d+)", t):
        return int(m.group(1))
    return None


def compute(area: SurveyArea, area_type: AreaType | None) -> None:
    """Recalculate every computed field of an area from its inputs."""
    if area.shape == "rect":
        floor = Decimal(area.length_m or 0) * Decimal(area.width_m or 0)
        perimeter = 2 * (Decimal(area.length_m or 0) + Decimal(area.width_m or 0))
    elif area.shape == "polygon":
        floor = shoelace(area.polygon_m)
        perimeter = polygon_perimeter(area.polygon_m)
    else:
        floor = Decimal(area.direct_area_sqm or 0)
        perimeter = Decimal(area.perimeter_m or 0)
    if area.perimeter_manual and area.perimeter_m is not None:
        perimeter = Decimal(area.perimeter_m)
    area.perimeter_m = q3(perimeter)
    floor = max(ZERO, floor - Decimal(area.deductions_sqm or 0))
    upturn = perimeter * Decimal(area.upturn_mm or 0) / 1000
    wall = (
        perimeter * Decimal(area.wall_height_m or 0)
        if area_type and area_type.includes_walls
        else ZERO
    )
    sunk = (
        perimeter * Decimal(area.sunk_depth_mm or 0) / 1000
        if area_type and area_type.needs_sunk_depth
        else ZERO
    )
    area.floor_area_sqm, area.upturn_area_sqm = q3(floor), q3(upturn)
    area.wall_area_sqm, area.sunk_area_sqm = q3(wall), q3(sunk)
    area.treated_area_sqm = q3((floor + upturn + wall + sunk) * int(area.count or 1))


def is_camera_only(area: SurveyArea) -> bool:
    return area.method in CAMERA_METHODS


def mismatch_percent(area: SurveyArea) -> Decimal | None:
    """Camera floor area vs the laser / manual one, in % of the laser value."""
    if (
        area.camera_floor_sqm is None
        or area.method in CAMERA_METHODS
        or not Decimal(area.floor_area_sqm or 0)
    ):
        return None
    laser = Decimal(area.floor_area_sqm) + Decimal(area.deductions_sqm or 0)
    if not laser:
        return None
    return (abs(Decimal(area.camera_floor_sqm) - laser) / laser * 100).quantize(Decimal("0.1"))


# --- consumption ---------------------------------------------------------------------------------


@dataclass
class Consumption:
    areas: list[dict] = field(default_factory=list)  # per area: system, products
    no_system: list[dict] = field(default_factory=list)
    products: dict[int, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    by_floor: dict[tuple, dict[int, Decimal]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Decimal))
    )
    by_tower: dict[str, dict[int, Decimal]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Decimal))
    )
    by_node: dict[int, dict[int, Decimal]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Decimal))
    )


def wastage(area: SurveyArea, area_type: AreaType | None, component: SystemComponent) -> Decimal:
    if area.wastage_override_percent is not None:
        return Decimal(area.wastage_override_percent)
    if area_type is not None and area_type.default_wastage_percent is not None:
        return Decimal(area_type.default_wastage_percent)
    return Decimal(component.wastage_percent or 0)


def area_system_id(area: SurveyArea, area_type: AreaType | None) -> int | None:
    return area.system_id or (area_type.default_system_id if area_type else None)


def consumption(db: Session, areas: list[SurveyArea]) -> Consumption:
    types = {t.id: t for t in db.scalars(select(AreaType))}
    systems = {s.id: s for s in db.scalars(select(System))}
    comps: dict[int, list[SystemComponent]] = defaultdict(list)
    for c in db.scalars(select(SystemComponent)):
        comps[c.system_id].append(c)
    out = Consumption()
    for a in areas:
        t = types.get(a.area_type_id)
        sid = area_system_id(a, t)
        if sid is None or sid not in systems:
            out.no_system.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "tower": a.tower,
                    "floor": a.floor_label,
                    "treated": a.treated_area_sqm,
                }
            )
            continue
        system = systems[sid]
        units = Decimal(a.treated_area_sqm or 0)
        if (system.unit or "sqm").lower() in ("sqft", "sft"):
            units = units * SQFT_PER_SQM
        lines = {}
        for c in comps[sid]:
            qty = units * Decimal(c.consumption_per_unit) * (1 + wastage(a, t, c) / 100)
            lines[c.product_id] = lines.get(c.product_id, ZERO) + qty
        floor_key = (
            a.tower or "",
            a.floor_no if a.floor_no is not None else 10**6,
            a.floor_label or "",
        )
        for pid, qty in lines.items():
            out.products[pid] += qty
            out.by_floor[floor_key][pid] += qty
            out.by_tower[a.tower or ""][pid] += qty
            if a.node_id:
                out.by_node[a.node_id][pid] += qty
        out.areas.append(
            {
                "id": a.id,
                "system_id": sid,
                "system": system.name,
                "products": {pid: q3(v) for pid, v in lines.items()},
            }
        )
    return out


def packs(db: Session, totals: dict[int, Decimal]) -> list[dict]:
    """Product totals with whole packs: rounded up only here, on the total."""
    products = {
        p.id: p for p in db.scalars(select(Product).where(Product.id.in_(list(totals) or [0])))
    }
    rows = []
    for pid, qty in sorted(
        totals.items(), key=lambda kv: products[kv[0]].name if kv[0] in products else ""
    ):
        p = products.get(pid)
        if p is None:
            continue
        size = Decimal(p.pack_size or 0)
        n = math.ceil(q3(qty) / size) if size > 0 else None
        rows.append(
            {
                "product_id": pid,
                "code": p.code,
                "name": p.name,
                "unit": p.unit,
                "qty": q3(qty),
                "pack_size": p.pack_size if size > 0 else None,
                "pack_unit": p.pack_unit if size > 0 else None,
                "packs": n,
                "pack_qty": q3(size * n) if n is not None else None,
                "spare_qty": q3(size * n - qty) if n is not None else None,
            }
        )
    return rows


# --- who sees what -------------------------------------------------------------------------------


def visible_q(scope: str, principal: Principal):
    """all: every survey; assigned: those of the caller's sites (and their own); own: those they
    made, or of their leads and tenders."""
    me = principal.user.id
    q = select(Survey)
    if scope == "all":
        return q
    if scope == "assigned":
        return q.where(
            or_(Survey.site_id.in_(material.assigned_sites(principal)), Survey.created_by == me)
        )
    return q.where(
        or_(
            Survey.created_by == me,
            Survey.surveyed_by == me,
            Survey.lead_id.in_(select(Lead.id).where(Lead.owner_id == me)),
            Survey.tender_id.in_(select(Tender.id).where(Tender.owner_id == me)),
        )
    )


def get_visible(db: Session, survey_id: int, scope: str, principal: Principal) -> Survey:
    s = db.scalar(visible_q(scope, principal).where(Survey.id == survey_id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Survey not found")
    return s


# --- the billing gate ----------------------------------------------------------------------------


def camera_only_for_boq_lines(db: Session, boq_line_ids: list[int]) -> dict[int, list[SurveyArea]]:
    """{BOQ line: its survey areas measured only by the camera}."""
    out: dict[int, list[SurveyArea]] = defaultdict(list)
    for line_id, area in db.execute(
        select(SurveyBoqLink.boq_line_id, SurveyArea)
        .join(SurveyArea, SurveyArea.id == SurveyBoqLink.survey_area_id)
        .where(SurveyBoqLink.boq_line_id.in_(boq_line_ids or [0]))
    ):
        if is_camera_only(area):
            out[line_id].append(area)
    return out
