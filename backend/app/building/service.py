# ruff: noqa: E501
"""The building model: made once from the AutoCAD drawing (the plans, their floors, the levels of
the section, the columns), corrected by the user, saved as versions, and raised for the 3D view.

data (stored, drawing units unless _m):
  settings     {floor_height_m 3.0, slab_m 0.15, plinth_m 0.45, column_min_m 0.2, column_max_m 0.9,
                beams_on_walls false, riser_m 0.15, bloom auto|on|off, tower_id, ifc false, ifc_max_mb 150}
  levels       detect.levels(): {source section|default, values_m, floor_height_m, note}
  floor_types  [{key, name, plan (the title), title_xy, floors [levels], outline [[x, y]],
                 columns [[cx, cy, w, d]], columns_confirmed, beams [[i, j]], cores
                 [{kind stair|lift, outline, risers}], shift [dx, dy] onto the reference plan,
                 shift_fixed (a roof traced on another plan's outline), walls (false: a roof)}]
  floors       [{level, node_id, name, type, height_m (override)}]
  ifc_links    {element id: node id}
"""

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.building import detect
from app.building.models import BuildingModel
from app.sites.models import Site, SiteNode
from app.takeoff.models import CadArea, CadFile

DEFAULTS = {"floor_height_m": 3.0, "slab_m": 0.15, "plinth_m": 0.45, "column_min_m": 0.2, "column_max_m": 0.9,
            "beams_on_walls": False, "riser_m": 0.15, "bloom": "auto", "tower_id": None, "ifc": False, "ifc_max_mb": 150}  # fmt: skip
OPENING_LAYERS = re.compile(r"WIN|DOOR|GLASS|RCC|^COL|COLUMN|CURTAIN", re.I)
COLUMN_LAYERS = re.compile(r"^COL(UMN)?\b|^COL[_ -]|COLUMN", re.I)
NOT_DRAWN = re.compile(r"FUR|HATCH|ELE|ELEC|LIGHT|PHE|PLUMB|FFTG|FIRE|HVAC|DIM|TEXT|TITLE", re.I)
WET = ("toilet", "kitchen", "balcony", "terrace", "oh_tank", "ug_tank", "lift_pit", "raft", "swimming_pool", "stp")


# --- the current model ---------------------------------------------------------------------------


def current(db: Session, site_id: int) -> BuildingModel | None:
    return db.scalars(select(BuildingModel).where(BuildingModel.site_id == site_id).order_by(BuildingModel.version.desc())).first()


def save(db: Session, site_id: int, data: dict, cad_file_id: int | None, user, note: str | None = None, changes: dict | None = None) -> BuildingModel:
    last = current(db, site_id)
    m = BuildingModel(site_id=site_id, version=(last.version + 1) if last else 1, cad_file_id=cad_file_id, data=data, note=note,
                      changes=changes, created_by=getattr(user, "id", None), created_by_name=getattr(user, "full_name", None))  # fmt: skip
    db.add(m)
    db.flush()
    m.built = build(db, m, db.get(CadFile, cad_file_id) if cad_file_id else None)  # the 3D geometry, once
    return m


# --- the drawing ---------------------------------------------------------------------------------


def _geometry(cad: CadFile) -> dict:
    from app.takeoff import pipeline, reader  # noqa: PLC0415

    if not cad.geometry_path:
        return {"geometry": {}}
    p: Path = pipeline.media(cad.geometry_path)
    return reader.load_geometry(p) if p.exists() else {"geometry": {}}


def layer_segments(db: Session, cad: CadFile, kind: str) -> list[float]:
    """The lines of the walls ("walls": the walls layers of the layer mapping, else layers named
    wall), of the outline proposal ("outline": walls plus windows, doors, glass, RCC, columns) or
    of the columns ("columns"). Furniture, hatch and electrical layers are never used."""
    from app.takeoff import service as takeoff  # noqa: PLC0415

    geo = _geometry(cad).get("geometry", {})
    walls = takeoff.wall_layers(db, cad) or {name for name in geo if re.search(r"\bWALL", name, re.I)}
    hidden = takeoff.hidden_layers(db, cad)
    out: list[float] = []
    for name, g in geo.items():
        if kind == "columns":
            use = bool(COLUMN_LAYERS.search(name)) and not re.search(r"UP TO|REDUCE|STUB|ADS|MARK", name, re.I)
        elif kind == "outline":
            use = name in walls or (bool(OPENING_LAYERS.search(name)) and name not in hidden and not NOT_DRAWN.search(name))
        else:
            use = name in walls
        if use:
            out.extend(g.get("s", []))
    return out


def plans(cad: CadFile) -> list[dict]:
    """The plans on the drawing: title, where it is, the floors its title names, and the region
    it is drawn in (above its title, up to the next title or the sheet's edge)."""
    from app.takeoff import service as takeoff  # noqa: PLC0415

    titles = takeoff.plan_titles(cad.texts or [])
    frames = (cad.summary or {}).get("frames", [])
    out = []
    for x, y, title in titles:
        frame = min((f for f in frames if f[0] <= x <= f[2] and f[1] <= y <= f[3]), key=lambda f: (f[2] - f[0]) * (f[3] - f[1]), default=None)
        if frame is None:
            continue
        # the plan is drawn above its title, up to the next title in the same column of the sheet
        column = (frame[2] - frame[0]) * 0.3
        above = [ty for tx, ty, _t in titles if abs(tx - x) < column and ty > y + 1 and frame[0] <= tx <= frame[2] and frame[1] <= ty <= frame[3]]
        top = min(above) if above else frame[3]
        if (top - y) * (cad.unit_m or 0.001) < 3:
            continue  # a title in the title block (the sheet's name), not under a plan
        out.append({"title": title, "xy": [x, y], "floors": detect.floors_in_title(title), "region": [frame[0], y, frame[2], top]})
    # the same title twice (a sheet title and the plan's own): keep the one with the tighter region
    best: dict[str, dict] = {}
    for p in out:
        r = p["region"]
        if p["title"] not in best or (r[2] - r[0]) * (r[3] - r[1]) < (best[p["title"]]["region"][2] - best[p["title"]]["region"][0]) * (best[p["title"]]["region"][3] - best[p["title"]]["region"][1]):
            best[p["title"]] = p
    return list(best.values())


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "plan"


def node_level(nodes: dict[int, SiteNode], node_id: int | None) -> tuple[int | None, SiteNode | None]:
    """The floor a node is on (its floor or basement ancestor) and that floor's level number."""
    n = nodes.get(node_id) if node_id else None
    while n is not None and n.kind not in ("floor", "basement", "terrace"):
        n = nodes.get(n.parent_id) if n.parent_id else None
    if n is None:
        return None, None
    return level_of(n), n


def level_of(n: SiteNode) -> int | None:
    if n.level_no is not None:
        return int(n.level_no)
    name = (n.name or "").upper()
    if n.kind == "basement":
        m = re.search(r"(\d+)", name)
        return -int(m.group(1)) if m else -1
    if re.search(r"\b(GROUND|GF|STILT)\b", name):
        return 0
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def site_floors(db: Session, site_id: int, tower_id: int | None = None) -> list[SiteNode]:
    """The floors (and basements) of the building: of the chosen tower, else of the tower with the
    most floors, else every floor of the site."""
    nodes = list(db.scalars(select(SiteNode).where(SiteNode.site_id == site_id)))
    by_id = {n.id: n for n in nodes}
    # the floors, basements and the terrace (with its level number: the roof it stands on)
    floors = [n for n in nodes if n.kind in ("floor", "basement") or (n.kind == "terrace" and n.level_no is not None)]

    def tower(n: SiteNode) -> int | None:
        p = by_id.get(n.parent_id) if n.parent_id else None
        while p is not None and p.kind not in ("tower", "wing"):
            p = by_id.get(p.parent_id) if p.parent_id else None
        return p.id if p else None

    groups: dict[int | None, list[SiteNode]] = {}
    for f in floors:
        groups.setdefault(tower(f), []).append(f)
    if tower_id in groups:
        floors = groups[tower_id]
    elif groups:
        floors = max(groups.values(), key=len)
    return sorted((f for f in floors if level_of(f) is not None), key=lambda f: level_of(f))  # type: ignore[arg-type,return-value]


def draft(db: Session, site: Site, cad: CadFile) -> dict:
    """The first model from a drawing: its plans as floor types with the floors their titles name
    (outlines and columns still to trace and confirm), the levels of the section, the floors of
    the site structure. Nothing is guessed silently: what came from the defaults says so."""
    settings = dict(DEFAULTS)
    levels = detect.levels(cad.texts or [], cad.unit_m or 0.001)
    if levels.get("floor_height_m"):
        settings["floor_height_m"] = levels["floor_height_m"]
    types = []
    for p in plans(cad):
        if not p["floors"] and not re.search(r"TYPICAL|TERRACE|ROOF|O\.?H\.?W\.?T|BASEMENT", p["title"], re.I):
            continue
        types.append({"key": _slug(p["title"]), "name": p["title"].title(), "plan": p["title"], "title_xy": p["xy"], "region": p["region"],
                      "floors": p["floors"], "outline": [], "columns": [], "columns_confirmed": False, "beams": [], "cores": [], "shift": [0, 0]})  # fmt: skip
    floors = [{"level": level_of(f), "node_id": f.id, "name": f.name, "type": None, "height_m": None} for f in site_floors(db, site.id)]
    _assign_types(floors, types)
    return {"settings": settings, "levels": levels, "floor_types": types, "floors": floors, "ifc_links": {}}


def _assign_types(floors: list[dict], types: list[dict]) -> None:
    for f in floors:
        if f.get("type"):
            continue
        f["type"] = next((t["key"] for t in types if f["level"] in (t.get("floors") or [])), None)


def propose_outline(db: Session, cad: CadFile, ftype: dict) -> list[list[float]]:
    region = ftype.get("region")
    if not region:
        return []
    return detect.outline_from_walls(layer_segments(db, cad, "outline"), region, cad.unit_m or 0.001)


def detect_columns(db: Session, cad: CadFile, ftype: dict, settings: dict) -> list[list[float]]:
    if not ftype.get("outline"):
        return []
    shapes = detect.shapes(layer_segments(db, cad, "columns"))
    return detect.columns(shapes, ftype["outline"], cad.unit_m or 0.001, settings.get("column_min_m", 0.2), settings.get("column_max_m", 0.9))


def align_types(data: dict, unit_m: float) -> None:
    """Every plan shifted onto the reference plan (the one for the most floors) by its columns;
    a plan without enough columns in common lines up its outline's corner instead."""
    types = [t for t in data["floor_types"] if t.get("outline")]
    if not types:
        return
    ref = max(types, key=lambda t: len(t.get("floors") or []))
    ref["shift"] = [0, 0]
    for t in types:
        if t is ref or t.get("shift_fixed"):
            continue  # a roof traced on another plan's outline keeps that plan's shift
        dx, dy, n = detect.align(ref.get("columns") or [], t.get("columns") or [], 0.15 / unit_m)
        if n < 3:
            (rx, ry), (tx, ty) = _corner(ref["outline"]), _corner(t["outline"])
            dx, dy = rx - tx, ry - ty
        t["shift"] = [round(dx, 3), round(dy, 3)]


def _corner(poly: list[list[float]]) -> tuple[float, float]:
    return min(p[0] for p in poly), min(p[1] for p in poly)


# --- floors and heights ----------------------------------------------------------------------------


def storey_levels(values: list[float]) -> tuple[list[float], int | None]:
    """The section's levels as one per storey: a pair under 0.3 m apart (slab top and finished
    floor) is one level (the finished floor, the higher); the ground is the first level at or above
    -0.5 m (a plinth level such as +0.914 is the ground floor's)."""
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] < 0.3:
            out[-1] = v
        else:
            out.append(v)
    ground = next((i for i, v in enumerate(out) if v >= -0.5), None)
    return out, ground


def elevations(data: dict) -> list[dict]:
    """Each floor's finished level and its height (metres), and where the level came from:
      hand      typed on the building page (wins)
      section   the section's level for that storey: from the ground level up (the basements down)
      default   no level for it: the plinth, then the floor height of the setting
    A section level that is far from where the floors before it put this floor is flagged."""
    s = {**DEFAULTS, **(data.get("settings") or {})}
    floors = sorted((f for f in data.get("floors", []) if f.get("level") is not None), key=lambda f: f["level"])
    lv = data.get("levels") or {}
    values, g = storey_levels(lv.get("values_m") or []) if lv.get("source") == "section" else ([], None)
    fh = float(s["floor_height_m"])
    known: dict[int, tuple[float, str]] = {}
    for f in floors:
        if f.get("elevation_m") is not None and f.get("level_by_hand"):
            known[f["level"]] = (float(f["elevation_m"]), "hand")
        elif g is not None and 0 <= g + f["level"] < len(values):
            known[f["level"]] = (values[g + f["level"]], "section")
    out = []
    prev: dict | None = None
    for f in floors:
        lvl = f["level"]
        if lvl in known:
            bottom, src = known[lvl]
        elif prev is not None:
            bottom, src = prev["elevation_m"] + prev["height_m"], "default"
        else:  # the lowest floor without a level: the plinth, the floors below ground under it
            below = sum(1 for x in floors if x["level"] < 0 and x["level"] >= lvl) if lvl < 0 else 0
            bottom, src = float(s["plinth_m"]) - below * fh, "default"
        nxt = next((x for x in floors if x["level"] > lvl), None)
        if f.get("height_m"):
            h = float(f["height_m"])
        elif nxt is not None and nxt["level"] in known and known[nxt["level"]][0] > bottom:
            h = known[nxt["level"]][0] - bottom
        else:
            h = fh
        flag = None
        if src == "section" and prev is not None and abs(bottom - (prev["elevation_m"] + prev["height_m"])) > 0.3 and prev["level_source"] != "section":
            flag = "the section's level does not follow the floor below: check it"
        if src == "default" and values:
            flag = "no level on the section for this floor: the default height is used"
        if h < 2.0 or h > 8.0:
            flag = f"a storey of {h:.2f} m: check the levels"
        row = {**f, "elevation_m": round(bottom, 3), "height_m": round(h, 3), "level_source": src, "level_flag": flag}
        out.append(row)
        prev = row
    return out


def unmatched_levels(data: dict) -> list[float]:
    """The section's storey levels no floor uses (basements the site has not got, a tank or a
    machine room on the roof): shown so the user can see what was left out."""
    lv = data.get("levels") or {}
    if lv.get("source") != "section":
        return []
    used = {r["elevation_m"] for r in elevations(data) if r["level_source"] == "section"}
    values, _ = storey_levels(lv.get("values_m") or [])
    return [v for v in values if round(v, 3) not in used]


# --- the 3D payload ----------------------------------------------------------------------------------


def _to_m(poly: list[list[float]], shift: list[float], unit_m: float, origin: tuple[float, float]) -> list[list[float]]:
    return [[round((x + shift[0] - origin[0]) * unit_m, 3), round((y + shift[1] - origin[1]) * unit_m, 3)] for x, y in poly]


BUILT_VERSION = 1  # raise it when what build() makes changes: older models are built again


def build(db: Session, m: BuildingModel, cad: CadFile | None) -> dict:
    """The floor types' geometry for the 3D view (metres, from the reference plan's corner): the
    slab outline, the walls cut out of the drawing, columns, beams, cores. Made once when the model
    is saved (the drawing's lines are read only then), kept with the version."""
    unit = (cad.unit_m if cad else None) or 0.001
    data = m.data or {}
    s = {**DEFAULTS, **(data.get("settings") or {})}
    types = [t for t in data.get("floor_types", []) if t.get("outline")]
    if not types:
        return {"version": BUILT_VERSION, "types": {}, "origin": [0, 0], "ref": None}
    ref = max(types, key=lambda t: len(t.get("floors") or []))
    ox, oy = _corner([[x + ref["shift"][0], y + ref["shift"][1]] for x, y in ref["outline"]])
    origin = (ox, oy)
    walls_all = layer_segments(db, cad, "walls") if cad else []
    out_types = {}
    for t in types:
        sh = t.get("shift") or [0, 0]
        outline_m = _to_m(t["outline"], sh, unit, origin)
        xs, ys = [p[0] for p in t["outline"]], [p[1] for p in t["outline"]]
        pad = 0.5 / unit
        box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
        walls = []
        for i in range(0, len(walls_all) - 3, 4) if t.get("walls", True) else ():
            x1, y1, x2, y2 = walls_all[i:i + 4]
            if box[0] <= x1 <= box[2] and box[1] <= y1 <= box[3] and box[0] <= x2 <= box[2] and box[1] <= y2 <= box[3] and math.hypot(x2 - x1, y2 - y1) * unit > 0.15:
                walls.append([round((x1 + sh[0] - ox) * unit, 3), round((y1 + sh[1] - oy) * unit, 3), round((x2 + sh[0] - ox) * unit, 3), round((y2 + sh[1] - oy) * unit, 3)])
        cols = [[round((c[0] + sh[0] - ox) * unit, 3), round((c[1] + sh[1] - oy) * unit, 3), round(c[2] * unit, 3), round(c[3] * unit, 3)] for c in t.get("columns") or []]
        beams = [list(b) for b in t.get("beams") or [] if max(b) < len(cols)]
        if s.get("beams_on_walls") and not beams:
            beams = beams_on_column_lines(cols)
        out_types[t["key"]] = {"name": t["name"], "outline": outline_m, "area_sqm": round(detect.area(outline_m), 2), "walls": walls[:6000], "columns": cols, "beams": beams,
                               "cores": [{"kind": c.get("kind", "stair"), "outline": _to_m(c.get("outline") or [], sh, unit, origin), "risers": c.get("risers")} for c in t.get("cores") or []]}  # fmt: skip
    return {"version": BUILT_VERSION, "types": out_types, "origin": list(origin), "ref": ref["key"]}


def payload(db: Session, site_id: int, client: bool = False) -> dict | None:
    """The building for the 3D view, in metres with y up from the plinth: floors with their type,
    elevation and height; per type the slab outline, the walls, columns, beams and cores; the
    rooms (traced AutoCAD areas mapped to nodes) on their floors with sunk depth and the height of
    the waterproofing on their walls. None when the site has no building model (the 3D view then
    shows the schematic boxes). The client's copy leaves out the drawing's file and settings."""
    m = current(db, site_id)
    if m is None:
        return None
    cad = db.get(CadFile, m.cad_file_id) if m.cad_file_id else None
    unit = (cad.unit_m if cad else None) or 0.001
    data = m.data or {}
    s = {**DEFAULTS, **(data.get("settings") or {})}
    types = [t for t in data.get("floor_types", []) if t.get("outline")]
    ifc = None
    if s.get("ifc") and data.get("ifc"):
        f = data["ifc"]
        ifc = {"url": f"/api/sites/{site_id}/building/ifc", "filename": f.get("filename"), "rev_no": f.get("rev_no"), "size_mb": f.get("size_mb"), "max_mb": s["ifc_max_mb"]}
        if client:
            ifc["url"] = f"/api/portal/sites/{site_id}/building/ifc"
    if not types:
        if ifc is None:
            return None
        return {"version": m.version, "schematic": False, "settings": {k: s[k] for k in ("floor_height_m", "slab_m", "plinth_m", "riser_m", "bloom", "ifc")},
                "levels": {"source": "default", "note": None}, "floors": [], "types": {}, "rooms": [], "ifc_links": data.get("ifc_links") or {}, "ifc": ifc}  # fmt: skip
    built = m.built if m.built and m.built.get("version") == BUILT_VERSION else None
    if built is None:  # an older model: built now, once, and kept
        built = build(db, m, cad)
        m.built = built
        db.commit()
    out_types, origin = built["types"], tuple(built["origin"])
    ref = {"key": built["ref"]}
    floors = elevations(data)
    _assign_types(floors, [t for t in data.get("floor_types", []) if t.get("outline")])
    for f in floors:
        if not f.get("type") or f["type"] not in out_types:
            f["type"] = ref["key"] if f["level"] >= 0 else None
    by_level = {f["level"]: f for f in floors}
    rooms = _rooms(db, site_id, cad, data, unit, origin, by_level) if cad else []
    out = {"version": m.version, "schematic": False, "settings": {k: s[k] for k in ("floor_height_m", "slab_m", "plinth_m", "riser_m", "bloom", "ifc")},
           "levels": {"source": (data.get("levels") or {}).get("source", "default"), "note": None if client else (data.get("levels") or {}).get("note")},  # the section line is for staff
           "floors": [{k: f.get(k) for k in ("level", "node_id", "name", "type", "elevation_m", "height_m")} for f in floors],
           "types": out_types, "rooms": rooms, "ifc_links": data.get("ifc_links") or {}, "ifc": ifc}  # fmt: skip
    if not client:
        out["source"] = {"cad_file_id": m.cad_file_id, "note": m.note, "changes": m.changes, "by": m.created_by_name, "at": m.created_at.isoformat() if m.created_at else None}
    return out


def beams_on_column_lines(cols: list[list[float]], tol: float = 0.3, reach: float = 9.0) -> list[list[int]]:
    """Beams along the column lines: each column to its nearest neighbour on the same x or y line
    (within reach), once."""
    out: set[tuple[int, int]] = set()
    for i, a in enumerate(cols):
        for axis in (0, 1):
            other = 1 - axis
            near = [(abs(b[other] - a[other]), j) for j, b in enumerate(cols) if j != i and abs(b[axis] - a[axis]) < tol and b[other] > a[other] and abs(b[other] - a[other]) <= reach]
            if near:
                j = min(near)[1]
                out.add((min(i, j), max(i, j)))
    return [list(p) for p in sorted(out)]


def _rooms(db: Session, site_id: int, cad: CadFile, data: dict, unit: float, origin: tuple[float, float], by_level: dict) -> list[dict]:
    from app.survey.models import AreaType, SurveyArea  # noqa: PLC0415

    nodes = {n.id: n for n in db.scalars(select(SiteNode).where(SiteNode.site_id == site_id))}
    traced = [t for t in data.get("floor_types", []) if t.get("outline")]
    shift_by_plan = {t.get("plan"): t.get("shift") or [0, 0] for t in data.get("floor_types", [])}

    def shift_for(a: CadArea) -> list[float]:
        """The shift of the plan the room is drawn on: the floor type whose outline holds it (the
        takeoff may have named its sheet differently), else the one with its plan's title."""
        cx = sum(p[0] for p in a.outline) / len(a.outline)
        cy = sum(p[1] for p in a.outline) / len(a.outline)
        hit = next((t for t in traced if detect.inside(cx, cy, t["outline"])), None)
        return (hit.get("shift") if hit else None) or shift_by_plan.get(a.plan) or [0, 0]

    types_by_id = {t.id: t for t in db.scalars(select(AreaType))}
    out = []
    for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == cad.id, CadArea.node_id.is_not(None), CadArea.status.in_(("mapped", "accepted")))):
        if not a.outline:
            continue
        level, _floor = node_level(nodes, a.node_id)
        node = nodes.get(a.node_id)
        if node is None:
            continue
        if level is None or level not in by_level:
            if node.kind not in ("terrace", "oh_tank", "ug_tank", "lift_pit", "raft"):
                continue
            level = max(by_level) if node.kind in ("terrace", "oh_tank") and by_level else min(by_level, default=0)
        sh = shift_for(a)
        band = None
        sa = db.get(SurveyArea, a.survey_area_id) if a.survey_area_id else None
        if sa is not None and sa.wall_height_m:
            band = float(sa.wall_height_m)
        elif sa is not None and sa.upturn_mm:
            band = float(sa.upturn_mm) / 1000
        elif a.area_type_id and a.area_type_id in types_by_id and types_by_id[a.area_type_id].default_upturn_mm:
            band = float(types_by_id[a.area_type_id].default_upturn_mm) / 1000
        elif node.kind in ("toilet", "kitchen", "balcony", "terrace"):
            band = 0.3
        name = node.name if node else a.name
        out.append({"node_id": a.node_id, "key": a.key, "level": level, "kind": node.kind, "name": name, "label": a.name,
                    "outline": _to_m(a.outline, sh, unit, origin), "area_sqm": float(a.traced_area_sqm or a.label_area_sqm or 0) or None,
                    "sunk_m": float(a.sunk_m or 0), "raise_m": float(a.raise_m or 0), "wp_height_m": band})  # fmt: skip
    return out


# --- a new drawing revision ----------------------------------------------------------------------------


def rebuild(db: Session, site: Site, model: BuildingModel, cad: CadFile) -> tuple[dict, dict]:
    """The model moved onto a new revision of the drawing: each plan found again by its title (its
    outline, columns and cores moved with the title if the plan moved on the sheet), its columns
    looked for again and compared; the rooms are the new file's areas (their keys and node links
    carried over by the takeoff). Returns (data, changes)."""
    old = model.data or {}
    new_plans = {p["title"]: p for p in plans(cad)}
    data = {**old, "floor_types": [], "levels": detect.levels(cad.texts or [], cad.unit_m or 0.001) if (old.get("levels") or {}).get("source") == "section" else old.get("levels")}
    changes: dict[str, Any] = {"plans_kept": [], "plans_missing": [], "columns": {}, "rooms": {}}
    settings = {**DEFAULTS, **(old.get("settings") or {})}
    for t in old.get("floor_types", []):
        p = new_plans.get(t.get("plan"))
        if p is None:
            changes["plans_missing"].append(t.get("plan"))
            continue
        dx, dy = (p["xy"][0] - t["title_xy"][0], p["xy"][1] - t["title_xy"][1]) if t.get("title_xy") else (0, 0)

        def mv(poly: list[list[float]], dx: float = dx, dy: float = dy) -> list[list[float]]:
            return [[x + dx, y + dy] for x, y in poly]

        nt = {**t, "title_xy": p["xy"], "region": p["region"], "outline": mv(t.get("outline") or []),
              "cores": [{**c, "outline": mv(c.get("outline") or [])} for c in t.get("cores") or []]}  # fmt: skip
        found = detect_columns(db, cad, nt, settings)
        before = [[c[0] + dx, c[1] + dy, c[2], c[3]] for c in t.get("columns") or []]
        tol = 0.15 / (cad.unit_m or 0.001)
        kept = [c for c in before if any(abs(c[0] - f[0]) < tol and abs(c[1] - f[1]) < tol for f in found)]
        added = [f for f in found if not any(abs(c[0] - f[0]) < tol and abs(c[1] - f[1]) < tol for c in before)]
        nt["columns"] = kept + added
        nt["columns_confirmed"] = not added and len(kept) == len(before)
        changes["columns"][t["key"]] = {"kept": len(kept), "added": len(added), "removed": len(before) - len(kept)}
        changes["plans_kept"].append(t.get("plan"))
        data["floor_types"].append(nt)
    from app.takeoff import service as takeoff  # noqa: PLC0415

    rooms = list(db.scalars(select(CadArea).where(CadArea.cad_file_id == cad.id, CadArea.node_id.is_not(None))))
    ch = takeoff.changes(db, cad)
    changes["rooms"] = {"kept": sum(1 for a in rooms if not a.change), "added": [r["name"] for r in ch.get("added", [])],
                        "resized": [r["name"] for r in ch.get("resized", [])], "removed": [r["name"] for r in ch.get("removed", [])]}  # fmt: skip
    changes["at"] = datetime.now().isoformat(timespec="minutes")
    return data, changes
