# ruff: noqa: E501  (the area rows read better unwrapped)
"""Finding the areas we waterproof on a read drawing, measuring them, and putting them into the
site: the survey (method "cad"), the measurement book (source "autocad"), the material plan and the
3D view.

- Candidates come from room labels that carry their size (LADIES TOILET 10'6"X7'3") and from room
  names we waterproof (TERRACE, TOILET ...) without a size (those need a trace). Rooms are not
  closed outlines in these drawings, so no outline is built automatically.
- Waterproofing notes (CHEMICAL WATER PROOFING, 600 MM SUNK, 6" SUNK + 6" RAISE) attach to the
  nearest candidate within a radius; a sunk depth or raise is read into the area.
- Each candidate gets the title of the floor plan under it (2ND,3RD ... FLOOR WORKING PLAN): a
  suggestion for mapping it to the site's floors.
- Traced outlines give the area and perimeter; a sunken area also gets its side walls (perimeter ×
  depth) as a line of its own. Label and trace are both kept; a difference past 3 % is flagged.
"""

import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.takeoff import geometry
from app.takeoff.models import CadArea, CadFile, CadLayerMap, TakeoffSettings
from app.takeoff.sizes import dec, depths, is_waterproofing_note, label_name, parse_size
from app.timefmt import ist_today

ROOM_WORDS = (
    "TOILET", "BATH", "W.C", "WC", "WASH", "TERRACE", "KITCHEN", "BALCONY", "VERANDAH", "OHT", "O.H.W.T", "UG TANK", "UGT", "U.G.", "LIFT PIT", "LIFT WELL", "PLANTER",
    "POOL", "RAFT", "PODIUM", "UTILITY",
)  # fmt: skip
# a note, never a room name: what to do to an area (and how deep), not what the area is
NOTE_WORDS = re.compile(r"WATER\s*-?\s*PROOF|CHEMICAL|SUNK|RAISE|\bDEPTH\b|\bDEEP\b", re.I)
TITLE_WORDS = re.compile(
    r"PLAN|SCHEDULE|DETAIL|SECTION|ELEVATION|LEGEND|NOTE[S]?\b|LEVEL\b|SCALE|DRAWING", re.I
)
PLAN_TITLE = re.compile(
    r"(GROUND|BASEMENT|STILT|TERRACE|PODIUM|\d+\s*(ST|ND|RD|TH)|TYPICAL|O\.?H\.?W\.?T|ROOF).*(FLOOR|PLAN|LEVEL)",
    re.I,
)
# area type (by name in the area types master) from the words of a room name
AREA_TYPE_WORDS = [
    (r"TOILET|BATH|W\.?C\b|WASH", "Toilet / bathroom"),
    (r"TERRACE|ROOF", "Terrace"),
    (r"KITCHEN", "Kitchen"),
    (r"BALCONY|VERANDAH", "Balcony"),
    (r"SUNK", "Sunken slab"),
    (r"LIFT PIT|LIFT WELL", "Lift pit"),
    (r"O\.?H\.?W\.?T|OHT|OVERHEAD", "Overhead water tank"),
    (r"U\.?G\.?\s*TANK|UGT|UNDERGROUND", "Underground water tank"),
    (r"PLANTER|PODIUM", "Podium / planter"),
    (r"POOL", "Swimming pool"),
    (r"RAFT", "Raft"),
]


def settings(db: Session) -> TakeoffSettings:
    s = db.get(TakeoffSettings, 1)
    if s is None:
        s = TakeoffSettings(id=1, label_trace_diff_percent=Decimal(3), note_radius_m=Decimal(6))
        db.add(s)
        db.flush()
    return s


def clean(text: str) -> str:
    """A drawing text without AutoCAD codes (%%U underline, %%C diameter ...)."""
    return " ".join(re.sub(r"%%[UuOoCcDdPp]", "", text or "").split())


def layer_roles(db: Session, f: CadFile) -> dict[str, str]:
    """The architect's layer mapping {layer: role} for this drawing (empty when none)."""
    m = (
        db.scalar(select(CadLayerMap).where(CadLayerMap.architect == f.architect))
        if f.architect
        else None
    )
    return dict(m.roles) if m else {}


def hidden_layers(db: Session, f: CadFile) -> set[str]:
    m = (
        db.scalar(select(CadLayerMap).where(CadLayerMap.architect == f.architect))
        if f.architect
        else None
    )
    return {k for k, v in (m.roles if m else {}).items() if v == "hide"}


def wall_layers(db: Session, f: CadFile) -> set[str]:
    m = (
        db.scalar(select(CadLayerMap).where(CadLayerMap.architect == f.architect))
        if f.architect
        else None
    )
    return {k for k, v in (m.roles if m else {}).items() if v == "walls"}


def guess_area_type(name: str) -> str | None:
    up = (name or "").upper()
    for pattern, area_type in AREA_TYPE_WORDS:
        if re.search(pattern, up):
            return area_type
    return None


def is_room_name(text: str) -> bool:
    t = clean(text).upper()
    if not t or len(t) > 40 or TITLE_WORDS.search(t) or NOTE_WORDS.search(t):
        return False
    return any(re.search(rf"(?<![A-Z]){re.escape(w)}(?![A-Z])", t) for w in ROOM_WORDS)


def plan_titles(texts: list[list]) -> list[tuple[float, float, str]]:
    out = []
    for x, y, _h, _layer, text, *rest in texts:
        t = clean(text)
        if rest and rest[0]:
            continue  # a title inside a block is not the title of a plan
        # the title of a plan: 1ST FLOOR WORKING PLAN, TYPICAL FLOOR PLAN (not a level mark such
        # as 1ST FLOOR LVL, nor a schedule, a detail or a section)
        if (
            len(t) < 80
            and PLAN_TITLE.search(t)
            and re.search(r"\bPLAN\b", t, re.I)
            and not re.search(r"SCHEDULE|DETAIL|SECTION|ELEVATION|\bLVL\b", t, re.I)
        ):
            out.append((x, y, t))
    return out


def _inside(x: float, y: float, fr: list) -> bool:
    return fr[0] <= x <= fr[2] and fr[1] <= y <= fr[3]


def _plan_for(
    x: float, y: float, titles: list[tuple[float, float, str]], frames: list[list]
) -> str | None:
    """The plan title of the sheet the label is on: the smallest frame around the label that
    holds a plan title (a title block, a sheet border, a layout viewport's window); several
    plans on one sheet: the title nearest below the label, on that sheet only (titles sit under
    their plan). No frame around the label with a title: None, "sheet unknown" (the user picks).
    """
    for fr in sorted(
        (fr for fr in frames if _inside(x, y, fr)), key=lambda f: (f[2] - f[0]) * (f[3] - f[1])
    ):
        inner = [(tx, ty, t) for tx, ty, t in titles if _inside(tx, ty, fr)]
        if inner:
            below = [(y - ty, abs(x - tx), t) for tx, ty, t in inner if ty <= y]
            near = below or [(abs(y - ty), abs(x - tx), t) for tx, ty, t in inner]
            return min(near)[2]
        name = str(fr[4])
        if name.startswith("layout ") and not re.fullmatch(r"layout layout\s*\d*", name, re.I):
            return name[7:]
    return None


def loose_titles(texts: list[list]) -> list[tuple[float, float, str]]:
    """For a drawing without frames: the plan titles, and the large headings with PLAN in them
    (WORKING PLAN at three times the usual text height), not schedules, details or sections."""
    heights = sorted(t[2] for t in texts if t[2] and not (len(t) > 5 and t[5]))
    usual = heights[len(heights) // 2] if heights else 0
    out = list(plan_titles(texts))
    for x, y, h, _layer, text, *rest in texts:
        t = clean(text)
        if rest and rest[0]:
            continue
        if (h and usual and h >= 3 * usual and len(t) < 80 and re.search(r"\bPLAN\b", t, re.I)
                and not re.search(r"SCHEDULE|DETAIL|SECTION|ELEVATION|KEY PLAN|FURNITURE", t, re.I)):  # fmt: skip
            out.append((x, y, t))
    return list(dict.fromkeys(out))


def _guess_for(
    x: float, y: float, titles: list[tuple[float, float, str]], clusters: list[list]
) -> str | None:
    """No frame: the nearest title in the same model-space cluster (a guess, to confirm). A
    cluster reaches 25 % beyond its lines: a plan's title sits just under it."""

    def grown(c):
        m = 0.25 * max(c[2] - c[0], c[3] - c[1])
        return [c[0] - m, c[1] - m, c[2] + m, c[3] + m]

    for cl in sorted(
        (grown(c) for c in clusters if _inside(x, y, c)),
        key=lambda c: (c[2] - c[0]) * (c[3] - c[1]),
    ):
        inner = [((x - tx) ** 2 + (y - ty) ** 2, t) for tx, ty, t in titles if _inside(tx, ty, cl)]
        if inner:
            return min(inner)[1]  # the nearest title in a straight line
    return None


def find_areas(
    texts: list[list],
    unit_m: float | None,
    hidden: set[str],
    note_radius_m: float,
    frames: list[list] | None = None,
    clusters: list[list] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Candidates (labels with sizes, room names to trace) and the notes, attached or not."""
    candidates: list[dict] = []
    notes: list[dict] = []
    titles = plan_titles(texts)
    fallback = loose_titles(texts) if clusters else []
    framed = list(frames or [])  # every sheet frame, with a title or not
    frames = [
        fr
        for fr in frames or []
        if str(fr[4]).startswith("layout ") or any(_inside(tx, ty, fr) for tx, ty, _t in titles)
    ]
    for x, y, _h, layer, text, *rest in texts:
        if layer in hidden or (rest and rest[0]):  # a text inside a block: a symbol, not a label
            continue
        size = parse_size(text)
        if size and size.area_sqm > 0:
            name = clean(label_name(text, size)) or "Unnamed (size only)"
            candidates.append(
                {
                    "name": name[:200],
                    "label_text": text,
                    "size": size,
                    "x": x,
                    "y": y,
                    "layer": layer,
                }
            )
        elif is_room_name(text):
            candidates.append(
                {
                    "name": clean(text)[:200],
                    "label_text": text,
                    "size": None,
                    "x": x,
                    "y": y,
                    "layer": layer,
                }
            )
        elif is_waterproofing_note(text) and not TITLE_WORDS.search(clean(text)):
            notes.append({"text": clean(text), "x": x, "y": y})
    radius = note_radius_m / unit_m if unit_m else None
    for n in notes:
        best = None
        for c in candidates:
            d = ((c["x"] - n["x"]) ** 2 + (c["y"] - n["y"]) ** 2) ** 0.5
            if (radius is None or d <= radius) and (best is None or d < best[0]):
                best = (d, c)
        n["area"] = None
        if best:
            n["distance_m"] = round(best[0] * (unit_m or 0), 2) if unit_m else None
            best[1].setdefault("notes", []).append(n)
            n["area"] = best[1]["name"]
    seen: dict[tuple, int] = defaultdict(int)
    for c in sorted(candidates, key=lambda c: (c["x"], -c["y"])):
        c["plan"] = _plan_for(c["x"], c["y"], titles, frames or [])
        c["plan_guessed"] = False
        if c["plan"] is None and clusters and not any(_inside(c["x"], c["y"], fr) for fr in framed):
            guess = _guess_for(c["x"], c["y"], fallback, clusters)
            c["plan"], c["plan_guessed"] = guess, guess is not None
        dp = depths(c["label_text"])
        for n in c.get("notes", []):
            nd = depths(n["text"])
            dp.sunk_m = dp.sunk_m or nd.sunk_m
            dp.raise_m = dp.raise_m or nd.raise_m
        c["sunk_m"], c["raise_m"] = dp.sunk_m, dp.raise_m
        base = (c["name"].upper(), c["plan"] or "")
        seen[base] += 1
        c["key"] = f"{c['name'].upper()}|{c['plan'] or ''}|{seen[base]}"[:160]
    return candidates, [n for n in notes if n["area"] is None]


def build_areas(db: Session, f: CadFile) -> list[CadArea]:
    """The candidate areas of a freshly read drawing (replacing earlier candidates; accepted
    areas are kept), with the mapping carried from the drawing's previous revision."""
    s = settings(db)
    for a in db.scalars(
        select(CadArea).where(CadArea.cad_file_id == f.id, CadArea.status != "accepted")
    ):
        db.delete(a)
    db.flush()
    summary = dict(f.summary or {})
    hidden = hidden_layers(db, f)
    cands, loose = find_areas(
        f.texts or [],
        f.unit_m,
        hidden,
        float(s.note_radius_m),
        summary.get("frames"),
        summary.get("clusters"),
    )
    from app.survey.models import AreaType  # noqa: PLC0415

    types = {t.name: t.id for t in db.scalars(select(AreaType))}
    made = []
    for c in cands:
        size = c["size"]
        a = CadArea(
            cad_file_id=f.id, key=c["key"], name=c["name"], label_text=c["label_text"],
            size_text=size.text if size else None, size_kind=size.kind if size else None,
            label_w_m=dec(size.width_m) if size else None, label_l_m=dec(size.length_m) if size else None,
            label_area_sqm=dec(size.area_sqm) if size else None, x=c["x"], y=c["y"], plan=c["plan"], plan_guessed=c["plan_guessed"],
            notes=[{k: n[k] for k in ("text", "x", "y", "distance_m") if k in n} for n in c.get("notes", [])],
            sunk_m=dec(c["sunk_m"]) if c["sunk_m"] else None, raise_m=dec(c["raise_m"]) if c["raise_m"] else None,
            area_type_id=types.get(guess_area_type(c["name"]) or ""),
        )  # fmt: skip
        side(a)  # a sunken area's side walls from the label's perimeter (until it is traced)
        db.add(a)
        made.append(a)
    db.flush()
    carry_over(db, f, made)
    summary["loose_notes"] = loose[:200]
    summary["candidates"] = len(made)
    summary["size_labels"] = sum(1 for c in cands if c["size"])
    summary["waterproofing_notes"] = sum(len(c.get("notes", [])) for c in cands) + len(loose)
    summary["count_sets"] = count_sets(f, hidden, cands, loose, float(s.note_radius_m))
    summary["plan_titles"] = sorted(
        {
            t
            for _x, _y, t in (
                loose_titles(f.texts or [])
                if summary.get("clusters")
                else plan_titles(f.texts or [])
            )
        }
    )
    summary["sheet_unknown"] = sum(1 for c in cands if not c["plan"])
    summary["sheet_guessed"] = sum(1 for c in cands if c["plan_guessed"])
    f.summary = summary
    return made


def count_sets(
    f: CadFile, hidden: set[str], cands: list[dict], loose: list[dict], note_radius_m: float
) -> dict:
    """The counts two ways, so the numbers match whatever people compare them with: "all" is
    every text read (texts inside blocks and block attributes too) and the labels and notes on
    every layer; "mapped" is the texts on the layers shown by the architect's layer mapping,
    outside blocks: the ones the candidate list is built from."""
    texts = f.texts or []
    if hidden:
        every, every_loose = find_areas(texts, f.unit_m, set(), note_radius_m)
    else:
        every, every_loose = cands, loose
    top = (f.summary or {}).get("top", {})  # in model space itself, not inside blocks

    def notes(cs, ls):
        return sum(len(c.get("notes", [])) for c in cs) + len(ls)

    return {
        "all": {"texts": len(texts), "text_entities": top.get("TEXT", 0) + top.get("MTEXT", 0),
                "size_labels": sum(1 for c in every if c["size"]), "notes": notes(every, every_loose)},
        "mapped": {"texts": sum(1 for t in texts if t[3] not in hidden and not (len(t) > 5 and t[5])),
                   "size_labels": sum(1 for c in cands if c["size"]), "notes": notes(cands, loose),
                   "hidden_layers": len(hidden)},
    }  # fmt: skip


def previous_file(db: Session, f: CadFile) -> CadFile | None:
    from app.sites.models import DrawingRevision  # noqa: PLC0415

    rev = db.get(DrawingRevision, f.revision_id)
    return db.scalar(
        select(CadFile)
        .join(DrawingRevision, DrawingRevision.id == CadFile.revision_id)
        .where(
            CadFile.drawing_id == f.drawing_id,
            DrawingRevision.rev_no < rev.rev_no,
            CadFile.status == "ready",
        )
        .order_by(DrawingRevision.rev_no.desc())
        .limit(1)
    )


def carry_over(db: Session, f: CadFile, made: list[CadArea]) -> None:
    """A new revision keeps the mapping (place, area type, system, the trace) and says what
    changed: areas added, removed or resized against the last revision."""
    prev = previous_file(db, f)
    if prev is None:
        return
    old = {
        a.key: a
        for a in db.scalars(
            select(CadArea).where(CadArea.cad_file_id == prev.id, CadArea.copied_from_id.is_(None))
        )
    }
    for a in made:
        o = old.get(a.key)
        if o is None:
            a.change = "added"
            continue
        a.node_id, a.area_type_id, a.system_id = (
            o.node_id,
            o.area_type_id or a.area_type_id,
            o.system_id,
        )
        if o.node_id:
            a.status = "mapped"
        a.previous_area_sqm = o.label_area_sqm or o.traced_area_sqm
        if (
            o.label_area_sqm
            and a.label_area_sqm
            and abs(Decimal(a.label_area_sqm) - Decimal(o.label_area_sqm)) > Decimal("0.01")
        ):
            a.change = "resized"
        elif o.outline and not a.outline and not o.label_area_sqm:
            a.outline, a.traced_area_sqm, a.traced_perimeter_m = (
                o.outline,
                o.traced_area_sqm,
                o.traced_perimeter_m,
            )


def changes(db: Session, f: CadFile) -> dict:
    prev = previous_file(db, f)
    if prev is None:
        return {"previous": None, "added": [], "removed": [], "resized": []}
    keys = set(db.scalars(select(CadArea.key).where(CadArea.cad_file_id == f.id)))
    removed = db.scalars(
        select(CadArea).where(
            CadArea.cad_file_id == prev.id,
            CadArea.copied_from_id.is_(None),
            CadArea.key.notin_(keys or {""}),
        )
    ).all()
    rows = db.scalars(
        select(CadArea).where(CadArea.cad_file_id == f.id, CadArea.change.is_not(None))
    ).all()
    return {
        "previous": prev.id,
        "added": [area_brief(a) for a in rows if a.change == "added"],
        "resized": [
            area_brief(a) | {"previous_area_sqm": a.previous_area_sqm}
            for a in rows
            if a.change == "resized"
        ],
        "removed": [area_brief(a) for a in removed],
    }


def area_brief(a: CadArea) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "plan": a.plan,
        "size": a.size_text,
        "label_area_sqm": a.label_area_sqm,
    }


# --- tracing -------------------------------------------------------------------------------------


def trace(db: Session, f: CadFile, a: CadArea, points: list[list[float]]) -> None:
    """The outline the user traced (drawing units): area, perimeter, and the side walls of a
    sunken area (perimeter × depth) kept apart from the floor."""
    if not f.unit_m:
        raise ValueError("Set the drawing's unit first: it says unitless")
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        raise ValueError("An outline needs at least three corners")
    u = float(f.unit_m)
    a.outline = [[round(x, 3), round(y, 3)] for x, y in pts]
    a.traced_area_sqm = dec(geometry.area(pts) * u * u)
    a.traced_perimeter_m = dec(geometry.perimeter(pts) * u)
    side(a)


def side(a: CadArea) -> None:
    per = a.traced_perimeter_m
    if per is None and a.label_w_m and a.label_l_m:
        per = 2 * (Decimal(a.label_w_m) + Decimal(a.label_l_m))
    a.side_wall_sqm = dec(float(per) * float(a.sunk_m)) if per and a.sunk_m else None


def label_trace_diff(db: Session, a: CadArea) -> tuple[float | None, bool]:
    d = geometry.diff_percent(
        float(a.label_area_sqm) if a.label_area_sqm else None,
        float(a.traced_area_sqm) if a.traced_area_sqm is not None else None,
    )
    limit = float(settings(db).label_trace_diff_percent)
    return (round(d, 1) if d is not None else None), (d is not None and d > limit)


def area_sqm(a: CadArea) -> Decimal | None:
    """The quantity taken: the traced outline when there is one, else the label's size."""
    return a.traced_area_sqm if a.traced_area_sqm is not None else a.label_area_sqm


def survey_check(db: Session, a: CadArea) -> dict | None:
    """The same place measured by laser or by hand in a survey: flag past the survey's mismatch
    setting (3 %) for the engineer to check."""
    if not a.node_id or area_sqm(a) is None:
        return None
    from app.survey import service as ssvc  # noqa: PLC0415
    from app.survey.models import SurveyArea  # noqa: PLC0415

    other = db.scalars(
        select(SurveyArea).where(
            SurveyArea.node_id == a.node_id, SurveyArea.method.in_(("laser", "manual"))
        )
    ).all()
    if not other:
        return None
    measured = sum((Decimal(o.floor_area_sqm or 0) for o in other), Decimal(0))
    if not measured:
        return None
    d = abs(Decimal(area_sqm(a)) - measured) / measured * 100
    limit = Decimal(ssvc.settings(db).mismatch_percent)
    return {
        "survey_sqm": measured,
        "autocad_sqm": area_sqm(a),
        "diff_percent": d.quantize(Decimal("0.1")),
        "flagged": d > limit,
        "methods": sorted({o.method for o in other}),
    }


# --- into the site -------------------------------------------------------------------------------


def node_path(db: Session, node_id: int) -> list:
    from app.sites.models import SiteNode  # noqa: PLC0415

    out = []
    n = db.get(SiteNode, node_id)
    while n is not None:
        out.insert(0, n)
        n = db.get(SiteNode, n.parent_id) if n.parent_id else None
    return out


def copy_to_floors(
    db: Session, areas: list[CadArea], source_floor_id: int, target_floor_ids: list[int], user_id
) -> list[CadArea]:
    """ "Same as floor 3 for floors 4 to 12": each area mapped under the source floor is copied to
    each target floor, onto the place with the same names below it (made when missing), named for
    that floor."""
    from app.sites.models import SiteNode  # noqa: PLC0415

    source = db.get(SiteNode, source_floor_id)
    made = []
    for a in areas:
        if not a.node_id:
            continue
        path = node_path(db, a.node_id)
        ids = [n.id for n in path]
        if source_floor_id not in ids:
            raise ValueError(f"{a.name} is not mapped under {source.name}")
        below = path[ids.index(source_floor_id) + 1 :]
        for tid in target_floor_ids:
            target = db.get(SiteNode, tid)
            if target is None or target.site_id != source.site_id:
                raise ValueError("A target floor is not on this site")
            parent = target
            for n in below:  # the same names under the target floor (made when missing)
                child = db.scalar(
                    select(SiteNode).where(
                        SiteNode.parent_id == parent.id, func.lower(SiteNode.name) == n.name.lower()
                    )
                )
                if child is None:
                    child = SiteNode(
                        site_id=parent.site_id,
                        parent_id=parent.id,
                        kind=n.kind,
                        name=n.name,
                        sort_order=n.sort_order,
                        area_sqm=n.area_sqm,
                        created_by=user_id,
                    )
                    db.add(child)
                    db.flush()
                parent = child
            copy = CadArea(
                cad_file_id=a.cad_file_id, key=f"{a.key}|copy:{target.id}"[:160], name=a.name,
                label_text=a.label_text, size_text=a.size_text, size_kind=a.size_kind,
                label_w_m=a.label_w_m, label_l_m=a.label_l_m, label_area_sqm=a.label_area_sqm,
                x=a.x, y=a.y, plan=a.plan, notes=a.notes, sunk_m=a.sunk_m, raise_m=a.raise_m,
                outline=a.outline, traced_area_sqm=a.traced_area_sqm, traced_perimeter_m=a.traced_perimeter_m,
                side_wall_sqm=a.side_wall_sqm, node_id=parent.id, area_type_id=a.area_type_id,
                system_id=a.system_id, status="mapped", copied_from_id=a.id, floor_label=target.name,
                created_by=user_id,
            )  # fmt: skip
            db.add(copy)
            made.append(copy)
    db.flush()
    return made


def floor_of(db: Session, node_id: int | None) -> tuple[str | None, str | None, int | None]:
    """(tower, floor label, floor number) of a place, from the site structure."""
    if not node_id:
        return None, None, None
    from app.survey.service import floor_number  # noqa: PLC0415

    tower = floor = None
    for n in node_path(db, node_id):
        if n.kind in ("tower", "wing"):
            tower = n.name
        if n.kind in ("floor", "basement"):
            floor = n.name
    return tower, floor, floor_number(floor)


def survey_for(db: Session, f: CadFile, user_id):
    """The site's AutoCAD survey for this drawing (one per drawing, kept as a draft)."""
    from app.material.service import next_code  # noqa: PLC0415
    from app.sites.models import Drawing  # noqa: PLC0415
    from app.survey.models import Survey  # noqa: PLC0415

    drawing = db.get(Drawing, f.drawing_id)
    title = f"AutoCAD takeoff: {drawing.title}"[:300]
    s = db.scalar(select(Survey).where(Survey.site_id == f.site_id, Survey.title == title))
    if s is None:
        s = Survey(code=next_code(db, "SUR"), site_id=f.site_id, title=title, status="draft", surveyed_on=ist_today(),
                   surveyed_by=user_id, notes="Areas taken off the AutoCAD drawing (method: cad).", created_by=user_id)  # fmt: skip
        db.add(s)
        db.flush()
    return s


def accept(
    db: Session,
    f: CadFile,
    a: CadArea,
    user_id,
    to_survey: bool,
    to_book: bool,
    contract_line_id: int | None = None,
) -> None:
    """Into the survey (method "cad", the outline in metres, the sunk depth) and, when billing
    accepts, into the measurement book (source "autocad"): the floor, and the side walls of a
    sunken area as a line of its own."""
    from app.survey import service as ssvc  # noqa: PLC0415
    from app.survey.models import AreaType, SurveyArea  # noqa: PLC0415
    from app.team.models import Measurement  # noqa: PLC0415

    qty = area_sqm(a)
    if qty is None:
        raise ValueError(f"{a.name}: no size yet; trace it first")
    if not a.node_id:
        raise ValueError(f"{a.name}: map it to a place on the site first")
    from app.sites.models import DrawingRevision  # noqa: PLC0415

    rev = db.get(DrawingRevision, f.revision_id)
    ref = f"AutoCAD {rev.filename} R{rev.rev_no}, area #{a.id}"
    if to_survey and a.survey_area_id is None:
        s = survey_for(db, f, user_id)
        tower, floor, floor_no = floor_of(db, a.node_id)
        sa = SurveyArea(survey_id=s.id, node_id=a.node_id, tower=tower, floor_label=floor or a.floor_label, floor_no=floor_no,
                        name=a.name, area_type_id=a.area_type_id, system_id=a.system_id, method="cad",
                        sunk_depth_mm=(Decimal(a.sunk_m) * 1000) if a.sunk_m else None,
                        remarks=f"{ref}" + (f"; notes: {', '.join(n['text'] for n in a.notes)}" if a.notes else ""),
                        created_by=user_id)  # fmt: skip
        if a.outline and f.unit_m:
            u = float(f.unit_m)
            x0 = min(p[0] for p in a.outline)
            y0 = min(p[1] for p in a.outline)
            sa.shape = "polygon"
            sa.polygon_m = [
                [round((p[0] - x0) * u, 3), round((p[1] - y0) * u, 3)] for p in a.outline
            ]
        elif a.label_w_m and a.label_l_m:
            sa.shape, sa.length_m, sa.width_m = "rect", a.label_l_m, a.label_w_m
        else:
            sa.shape, sa.direct_area_sqm = "direct", qty
        db.add(sa)
        db.flush()
        ssvc.compute(sa, db.get(AreaType, a.area_type_id) if a.area_type_id else None)
        a.survey_area_id = sa.id
    if to_book and a.measurement_id is None:
        place = a.floor_label or a.plan or ""
        m = Measurement(site_id=f.site_id, contract_line_id=contract_line_id, node_id=a.node_id,
                        survey_area_id=a.survey_area_id, description=f"{a.name} {('(' + place + ')') if place else ''}"[:500].strip(),
                        qty=qty, unit="sqm", source="autocad", measured_on=ist_today(), measured_by=user_id,
                        note=ref, created_by=user_id)  # fmt: skip
        db.add(m)
        db.flush()
        a.measurement_id = m.id
        if a.side_wall_sqm:
            sw = Measurement(site_id=f.site_id, contract_line_id=contract_line_id, node_id=a.node_id,
                             survey_area_id=a.survey_area_id, description=f"{a.name}: sunken side walls (perimeter × {a.sunk_m} m)"[:500],
                             qty=a.side_wall_sqm, unit="sqm", source="autocad", measured_on=ist_today(),
                             measured_by=user_id, note=ref, created_by=user_id)  # fmt: skip
            db.add(sw)
            db.flush()
            a.side_measurement_id = sw.id
    if a.survey_area_id or a.measurement_id:
        a.status, a.accepted_by, a.accepted_at = "accepted", user_id, datetime.now(UTC)


def quantities(db: Session, site_id: int) -> dict:
    """Accepted AutoCAD areas per floor and per system (the material plan and the BOQ)."""
    from app.masters.models import System  # noqa: PLC0415
    from app.survey.models import AreaType  # noqa: PLC0415

    rows = db.execute(
        select(CadArea, CadFile).join(CadFile, CadFile.id == CadArea.cad_file_id)
        .where(CadFile.site_id == site_id, CadArea.status == "accepted")
    ).all()  # fmt: skip
    by_floor: dict[str, Decimal] = defaultdict(Decimal)
    by_system: dict[str, Decimal] = defaultdict(Decimal)
    by_type: dict[str, Decimal] = defaultdict(Decimal)
    for a, _f in rows:
        q = Decimal(area_sqm(a) or 0)
        _t, floor, _n = floor_of(db, a.node_id)
        by_floor[floor or a.floor_label or "—"] += q
        at = db.get(AreaType, a.area_type_id) if a.area_type_id else None
        sid = a.system_id or (at.default_system_id if at else None)
        sysname = db.get(System, sid).name if sid else "no system"
        by_system[sysname] += q
        by_type[at.name if at else "—"] += q

    def rows_of(d):
        return [{"name": k, "sqm": v.quantize(Decimal("0.001"))} for k, v in sorted(d.items())]

    return {
        "by_floor": rows_of(by_floor),
        "by_system": rows_of(by_system),
        "by_area_type": rows_of(by_type),
        "areas": len(rows),
    }


def node_sqm(db: Session, site_id: int) -> dict[int, float]:
    """Accepted AutoCAD area per place (the 3D view's hover)."""
    out: dict[int, float] = defaultdict(float)
    for a in db.scalars(
        select(CadArea)
        .join(CadFile, CadFile.id == CadArea.cad_file_id)
        .where(
            CadFile.site_id == site_id, CadArea.status == "accepted", CadArea.node_id.is_not(None)
        )
    ):
        out[a.node_id] += float(area_sqm(a) or 0)
    return dict(out)
