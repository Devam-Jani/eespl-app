# ruff: noqa: E501  (the sheet's lines read better unwrapped)
"""Measuring from the drawing (areas, their trims, shared edges, heights) and building the
measurement sheet in the billing team's layout.

The sheet is built from the areas each time it is opened while a draft, so a corrected height or
an answered edge shows at once; once sent its lines are kept as they were sent. What cannot be
measured yet (no height, an unanswered edge, a layer question) is returned as a question, never
guessed."""

import io
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine
from app.measure import geom
from app.measure.models import (
    MeasureArea,
    MeasureBilled,
    MeasureEdge,
    MeasureItem,
    MeasureLine,
    MeasureSheet,
)

ZERO = Decimal(0)
FT_PER_M = Decimal(1) / Decimal("0.3048")
AREA_UNITS = {"sqm": Decimal(1), "sqft": geom.SQFT_PER_SQM}
LENGTH_UNITS = {"rmt": Decimal(1), "m": Decimal(1), "rft": FT_PER_M}
COUNT_UNITS = ("nos", "no", "each", "set", "pcs")
PART_LABEL = {"floor": "Floor", "walls": "Side walls", "tops": "Wall tops", "slope": "Slope face", "count": "Count"}


class Question(Exception):
    """Something the billing team must answer before the line can be measured."""


def unit_kind(unit: str | None) -> str:
    u = (unit or "").strip().lower().replace(".", "")
    if u in AREA_UNITS:
        return "area"
    if u in LENGTH_UNITS:
        return "length"
    if u in COUNT_UNITS:
        return "count"
    return "area"


def factor(unit: str | None) -> Decimal:
    u = (unit or "").strip().lower().replace(".", "")
    return AREA_UNITS.get(u) or LENGTH_UNITS.get(u) or Decimal(1)


# --- the drawing's closed outlines ---------------------------------------------------------------


def _open_dxf(path: Path):
    import ezdxf  # noqa: PLC0415

    from app.takeoff import reader  # noqa: PLC0415

    try:
        return ezdxf.readfile(str(path))
    except Exception:  # noqa: BLE001  (dwg2dxf's raw line breaks: the reader's repair)
        data, _ = reader.repair(path.read_bytes())
        return ezdxf.read(io.StringIO(data.decode("utf-8", errors="replace")))


@lru_cache(maxsize=8)
def _drawing(path: str, mtime: float, unit_m: float) -> dict:
    """Outlines in model space (metres, bulges kept): closed polylines, polylines drawn round but
    left open (their ends within 50 mm: closed by the app, the gap kept), circles; the open lines
    and arcs (a slope line on a section, a wall drawn as its own line) to pick; the circles and
    block inserts as markers to count. The viewer draws the rest."""
    doc = _open_dxf(Path(path))
    u = unit_m
    outlines, markers, lines = [], [], []

    def finite(pts) -> bool:
        return all(math.isfinite(v) for p in pts for v in p)

    def add(e, pts, closed):
        if not finite(pts):
            return  # a broken entity (infinite or missing coordinates): never measured
        got = geom.closable(pts, closed)
        if got is not None:
            o, gap, drawn = got
            outlines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "outline": o, "gap_m": gap or None, "drawn_m": drawn})
        if not closed and (got is None or gap > geom.SAME_POINT_M):
            lines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "points": pts, "length_m": geom.open_length(pts)})

    for e in doc.modelspace():
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE":
                add(e, [[x * u, y * u, b] for x, y, b in e.get_points("xyb")], bool(e.closed))
            elif t == "POLYLINE" and e.is_2d_polyline:
                add(e, [[v.dxf.location.x * u, v.dxf.location.y * u, v.dxf.bulge or 0.0] for v in e.vertices], bool(e.is_closed))
            elif t == "LINE":
                s, f = e.dxf.start, e.dxf.end
                pts = [[s.x * u, s.y * u, 0.0], [f.x * u, f.y * u, 0.0]]
                if finite(pts):
                    lines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "points": pts, "length_m": geom.open_length(pts)})
            elif t == "ARC":
                c, r = e.dxf.center, e.dxf.radius
                a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
                sweep = (a1 - a0) % math.tau or math.tau
                pts = [[(c.x + r * math.cos(a0)) * u, (c.y + r * math.sin(a0)) * u, math.tan(sweep / 4)], [(c.x + r * math.cos(a1)) * u, (c.y + r * math.sin(a1)) * u, 0.0]]
                if finite(pts):
                    lines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "points": pts, "length_m": r * u * sweep})
            elif t == "CIRCLE":
                c, r = e.dxf.center, e.dxf.radius
                outlines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "outline": [[(c.x - r) * u, c.y * u, 1.0], [(c.x + r) * u, c.y * u, 1.0]]})
                markers.append([c.x * u, c.y * u, f"layer:{e.dxf.layer}"])
            elif t == "INSERT":
                p = e.dxf.insert
                markers.append([p.x * u, p.y * u, f"block:{e.dxf.name}"])
                markers.append([p.x * u, p.y * u, f"layer:{e.dxf.layer}"])
        except Exception:  # noqa: BLE001,S112  (one broken entity never stops the rest)
            continue
    lines = [ln for ln in lines if ln["length_m"] > 1e-6]  # a zero-length line cannot be picked
    return {"outlines": outlines[:20000], "markers": markers, "lines": lines[:50000]}


def candidates(cad_file, x: float, y: float, taken: set[str]) -> list[dict]:
    """Every outline around a click, smallest first (a hatch, the wall's face, the billing team's
    own outline on layer 0 ...): the user picks the one to measure."""
    from shapely.geometry import Point  # noqa: PLC0415

    pt = Point(x, y)
    out = []
    for o in drawing(cad_file)["outlines"]:
        if o["handle"] in taken:
            continue
        poly = geom.polygon(o["outline"])
        if poly.contains(pt):
            out.append({"handle": o["handle"], "layer": o["layer"], "area_sqm": geom.area(o["outline"]), "periphery_m": geom.periphery(o["outline"]),
                        "gap_mm": o["gap_m"] * 1000 if o.get("gap_m") else None, "drawn_m": o.get("drawn_m")})  # fmt: skip
    return sorted(out, key=lambda c: c["area_sqm"])


def outline_of(cad_file, handle: str) -> dict:
    for o in drawing(cad_file)["outlines"]:
        if o["handle"] == handle:
            return o
    raise Question("That outline is not on the drawing (or is not closed)")


def line_of(cad_file, handle: str) -> dict:
    """A line picked on the drawing (a slope on a section, a wall drawn on its own): its true
    length (an arc as an arc), its horizontal run and its rise."""
    d = drawing(cad_file)
    for ln in d["lines"]:
        if ln["handle"] == handle:
            pts = ln["points"]
            xs = [p[0] for p in pts]
            return ln | {"run_m": abs(pts[-1][0] - pts[0][0]) or (max(xs) - min(xs)), "rise_m": abs(pts[-1][1] - pts[0][1])}
    raise Question("That line is not on the drawing")


def drawing(cad_file) -> dict:
    from app.takeoff.pipeline import media  # noqa: PLC0415

    if not cad_file.dxf_path or not cad_file.unit_m:
        raise Question("The drawing is not read yet, or its unit is not set")
    p = media(cad_file.dxf_path)
    return _drawing(str(p), p.stat().st_mtime, float(cad_file.unit_m))


def texts_m(cad_file) -> list[list]:
    """The drawing's texts in metres: [x, y, height, text, layer] (the levels on a section)."""
    u = float(cad_file.unit_m or 1)
    return [[t[0] * u, t[1] * u, t[2] * u, t[4], t[3]] for t in (cad_file.texts or []) if len(t) >= 5 and not (len(t) > 5 and t[5])]


def counts_in(outline: geom.Outline, markers: list[list]) -> dict[str, int]:
    from shapely.geometry import Point  # noqa: PLC0415

    poly = geom.polygon(outline)
    out: dict[str, int] = {}
    for x, y, key in markers:
        if poly.contains(Point(x, y)):
            out[key] = out.get(key, 0) + 1
    return out


# --- areas, trims and shared edges ---------------------------------------------------------------


def next_code(db: Session, site_id: int) -> str:
    used = set(db.scalars(select(MeasureArea.code).where(MeasureArea.site_id == site_id)))
    for i in range(26 * 27):
        code = chr(65 + i % 26) + (str(i // 26) if i >= 26 else "")
        if code not in used:
            return code
    raise Question("Too many areas")


def make_area(db: Session, site_id: int, outline: geom.Outline, *, code: str | None, name: str, kind: str = "area",
              cad_file=None, handle: str | None = None, layer: str | None = None, picked: bool = True, user_id=None,
              gap_m: float | None = None, drawn_m: float | None = None) -> MeasureArea:
    if len(outline) < 2 or geom.area(outline) <= 1e-9:
        raise Question("That outline has no area")
    code = (code or "").strip().upper() or next_code(db, site_id)
    if db.scalar(select(MeasureArea.id).where(MeasureArea.site_id == site_id, MeasureArea.code == code)):
        raise Question(f"Area {code} exists: give another letter")
    a = MeasureArea(site_id=site_id, cad_file_id=cad_file.id if cad_file else None, code=code, name=name.strip() or code, kind=kind,
                    outline=[[float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0] for p in outline],
                    picked=picked, handle=handle, layer=layer, area_sqm=geom.d(geom.area(outline)), periphery_m=geom.d(geom.periphery(outline)),
                    net_area_sqm=ZERO, net_periphery_m=ZERO, trim_with=[], counts={}, created_by=user_id,
                    closed_gap_mm=geom.d(gap_m * 1000) if gap_m else None, drawn_length_m=geom.d(drawn_m) if drawn_m is not None else None)  # fmt: skip
    if cad_file is not None:
        try:
            a.counts = counts_in(a.outline, drawing(cad_file)["markers"])
        except Question:
            a.counts = {}
    db.add(a)
    db.flush()
    # a new area that overlaps one already measured is the one trimmed (the user can change it)
    a.trim_with = [o.id for o in areas_of(db, site_id) if o.id != a.id and _overlaps(a.outline, o.outline)]
    refresh(db, site_id)
    return a


def _overlaps(a: geom.Outline, b: geom.Outline) -> bool:
    pa, pb = geom.polygon(a), geom.polygon(b)
    return pa.intersects(pb) and pa.intersection(pb).area > 1e-6


def areas_of(db: Session, site_id: int) -> list[MeasureArea]:
    return list(db.scalars(select(MeasureArea).where(MeasureArea.site_id == site_id).order_by(MeasureArea.code)))


def refresh(db: Session, site_id: int) -> None:
    """Each area's figures after its trim, and the shared edges (an answer stays with its edge)."""
    areas = areas_of(db, site_id)
    by_id = {a.id: a for a in areas}
    for a in areas:
        others = [by_id[i].outline for i in (a.trim_with or []) if i in by_id]
        ar, per, _ = geom.trim(a.outline, others)
        a.net_area_sqm, a.net_periphery_m = geom.d(ar), geom.d(per)
    old = {(e.area_a_id, e.area_b_id, _key(e.line)): e for e in db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == site_id, MeasureEdge.manual.is_(False)))}
    found: dict[tuple, tuple[float, list[float]]] = {}
    for i, a in enumerate(areas):
        for b in areas[i + 1 :]:
            for length, line in geom.shared_paths(a.outline, b.outline, a_trims_b=a.id in (b.trim_with or []), b_trims_a=b.id in (a.trim_with or [])):
                found[(a.id, b.id, _key(line))] = (length, line)
    # the edges gone first (their numbers free), then the ones kept updated and the new ones added
    for k, e in old.items():
        if k not in found:
            db.delete(e)
    db.flush()
    used: dict[tuple[int, int], set[int]] = {}
    for e in db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == site_id)):
        used.setdefault((e.area_a_id, e.area_b_id), set()).add(e.seq)
    for k, (length, line) in found.items():
        e = old.get(k)
        if e is None:
            taken = used.setdefault(k[:2], set())
            seq = next(n for n in range(len(taken) + 1) if n not in taken)
            taken.add(seq)
            e = MeasureEdge(site_id=site_id, area_a_id=k[0], area_b_id=k[1], seq=seq, line=line, length_m=geom.d(length))
            db.add(e)
        e.length_m, e.line = geom.d(length), line
    db.flush()


def _key(line) -> tuple:
    """An edge's ends to the centimetre, in either direction (its path is [x1, y1, ..., xn, yn])."""
    a = (round(line[0], 2), round(line[1], 2))
    b = (round(line[-2], 2), round(line[-1], 2))
    return tuple(sorted((a, b)))


def edges_of(db: Session, site_id: int) -> list[MeasureEdge]:
    return list(db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == site_id).order_by(MeasureEdge.id)))


def avg_height_m(a, way: "Way | None" = None) -> tuple[Decimal, str]:
    """The walls' height: one height, or the average of the shallow and the deep end."""
    fix = way.fix if way else (lambda v: v)
    if a.height_mm is None:
        raise Question(f"{a.code} {a.name}: pick its height from a section")
    h1 = Decimal(a.height_mm)
    if a.height2_mm is None:
        return fix(h1 / 1000), a.height_source or f"{h1.normalize():f} mm"
    h2 = Decimal(a.height2_mm)
    return fix((h1 + h2) / 2000), f"average of {h1.normalize():f} and {h2.normalize():f} mm ({a.height_source}; {a.height2_source})"


def slope_of(a) -> tuple[Decimal, str]:
    """Slope length over horizontal run: the slope's own length when it was picked as a line (an
    arc's true length), else from its rise and run."""
    if a.slope_mm and a.run_mm:
        s, run = Decimal(a.slope_mm) / 1000, Decimal(a.run_mm) / 1000
        f = s / run
        return f, f"{_n(s)} m slope / {_n(run)} m run = {_n(f, 6)}"
    if not a.rise_mm or not a.run_mm:
        raise Question(f"{a.code} {a.name}: pick the slope's rise and run from a section")
    rise, run = Decimal(a.rise_mm) / 1000, Decimal(a.run_mm) / 1000
    f = geom.slope_factor(rise, run)
    return f, f"√({_n(rise)}² + {_n(run)}²) / {_n(run)} = {_n(f, 6)}"


def _n(v: Decimal, places: int = 4) -> str:
    q = Decimal(v).quantize(Decimal(1).scaleb(-places))
    return f"{q.normalize():f}" if q == q.to_integral() else f"{q:f}".rstrip("0")


# --- the sheet -----------------------------------------------------------------------------------


@dataclass
class Built:
    lines: list[dict] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)


@dataclass
class Way:
    """How a sheet measures. The app's way: every area, full precision, 10.7639 sqft per sqm, each
    line's total rounded, grouped by area. A study sheet can measure another way to compare (the
    billing team's old sheets: sizes cut to 3 decimals, 10.76, the total converted once per item,
    grouped by item), and take an area, edge or item differently, without changing them."""

    areas: set[int] | None = None
    truncate: bool = False
    sqft: Decimal = geom.SQFT_PER_SQM
    per_item: bool = False
    drawn_periphery: bool = False
    study: bool = False
    over_areas: dict = field(default_factory=dict)
    over_edges: dict = field(default_factory=dict)
    over_items: dict = field(default_factory=dict)

    @classmethod
    def of(cls, sheet: MeasureSheet) -> "Way":
        o = sheet.options or {}
        if sheet.status != "study":
            return cls()
        return cls(areas=set(o["areas"]) if o.get("areas") else None, truncate=o.get("sizes") == "truncate3", sqft=Decimal(str(o.get("sqft_per_sqm") or geom.SQFT_PER_SQM)),
                   per_item=o.get("convert") == "item", drawn_periphery=o.get("periphery") == "drawn", study=True,
                   over_areas=o.get("areas_as") or {}, over_edges=o.get("edges_as") or {}, over_items=o.get("items_as") or {})  # fmt: skip

    def fix(self, v) -> Decimal:
        """A size as this way takes it: full precision, or cut to 3 decimals (never rounded up)."""
        v = Decimal(v)
        return v.quantize(Decimal("0.001"), rounding=ROUND_DOWN) if self.truncate else v

    def factor(self, unit: str | None) -> Decimal:
        u = (unit or "").strip().lower().replace(".", "")
        return self.sqft if u == "sqft" else factor(unit)

    def label(self) -> str:
        if not self.study:
            return "The app's way: full precision, each line rounded to 3 decimals (half up), 1 sqm = 10.7639 sqft"
        bits = ["sizes cut to 3 decimals" if self.truncate else "full precision", f"1 sqm = {self.sqft} sqft",
                "converted once per item" if self.per_item else "each line rounded to 3 decimals (half up)"]  # fmt: skip
        return "A study (not billed): " + ", ".join(bits)


def _copy(obj, cols: tuple[str, ...], over: dict | None) -> SimpleNamespace:
    s = SimpleNamespace(**{c: getattr(obj, c) for c in cols})
    for k, v in (over or {}).items():
        setattr(s, k, Decimal(str(v)) if k.endswith(("_mm", "_m", "_sqm")) and v is not None else v)
    return s


AREA_COLS = ("id", "code", "name", "kind", "net_area_sqm", "net_periphery_m", "drawn_length_m", "closed_gap_mm", "trim_with", "height_mm", "height_source",
             "height2_mm", "height2_source", "wall_top_mm", "rise_mm", "run_mm", "slope_mm", "slope_source", "counts")  # fmt: skip
EDGE_COLS = ("id", "area_a_id", "area_b_id", "length_m", "answer", "weir_mm", "manual", "source")
ITEM_COLS = ("wo_line_id", "parts", "count_of", "layers", "layers_answer", "areas", "skip", "manual")


def items_of(db: Session, site_id: int) -> list[tuple[MeasureItem, ClientWorkOrderLine]]:
    rows = db.execute(
        select(MeasureItem, ClientWorkOrderLine).join(ClientWorkOrderLine, ClientWorkOrderLine.id == MeasureItem.wo_line_id)
        .where(MeasureItem.site_id == site_id).order_by(ClientWorkOrderLine.sort_order, ClientWorkOrderLine.id)
    )  # fmt: skip
    return [(m, w) for m, w in rows]


def layers_billed(item, wo: ClientWorkOrderLine) -> list[int]:
    """The layers billed as lines of their own: each one when the order's rate is per layer;
    otherwise the billing team says (each, or the item once) and until then it is a question."""
    n = item.layers or 1
    if n == 1:
        return [1]
    if wo.per_layer or item.layers_answer == "each":
        return list(range(1, n + 1))
    if item.layers_answer == "once":
        return [1]
    raise Question(f"Item {wo.item_no or wo.id}: {n} layers are measured but the order's rate is not per layer. Bill each layer, or the item once?")


def billed_elsewhere(db: Session, sheet: MeasureSheet) -> set[tuple[int, int, int]]:
    rows = db.execute(select(MeasureBilled.area_id, MeasureBilled.wo_line_id, MeasureBilled.layer).where(MeasureBilled.sheet_id != sheet.id))
    return {(a, w, la) for a, w, la in rows}


def build(db: Session, sheet: MeasureSheet) -> Built:
    """The sheet's lines from the areas: per area a header, then per item and layer its lines,
    each deduction a negative line with its reason. Totals per line in the item's unit (a study
    converting per item: grouped by item, a total line per item)."""
    out = Built()
    way = Way.of(sheet)
    real = [a for a in areas_of(db, sheet.site_id) if way.areas is None or a.id in way.areas]
    areas = [_copy(a, AREA_COLS, way.over_areas.get(str(a.id))) for a in real]
    by_id = {a.id: a for a in areas}
    edges = [_copy(e, EDGE_COLS, way.over_edges.get(str(e.id))) for e in edges_of(db, sheet.site_id) if e.area_a_id in by_id and e.area_b_id in by_id]
    done_elsewhere = set() if way.study else billed_elsewhere(db, sheet)
    not_done = set() if way.study else {tuple(x) for x in (sheet.not_done or [])}
    items = []
    for m, w in items_of(db, sheet.site_id):
        over = dict(way.over_items.get(str(w.id)) or {})
        as_no, by_area = bool(over.pop("layers_as_no", False)), over.pop("layers_by_area", None) or {}
        item = _copy(m, ITEM_COLS, over)
        item.layers_as_no, item.layers_by_area = as_no, by_area
        items.append((item, w))
    blocks: dict[tuple[int, int], list[dict]] = {}  # (area, item): its lines
    for a in areas:
        for item, wo in items:
            if item.areas and a.id not in item.areas:
                continue
            n_layers = int(item.layers_by_area.get(str(a.id), item.layers or 1))
            try:
                layers = [1] if item.layers_as_no else layers_billed(item, wo)
            except Question as q:
                out.questions.append({"kind": "layers", "wo_line_id": wo.id, "text": str(q)})
                continue
            body: list[dict] = []
            for layer in layers:
                key = (a.id, wo.id, layer)
                if key in done_elsewhere:
                    continue  # billed on an earlier sheet: it is in the previous quantity
                tag = {"area_id": a.id, "wo_line_id": wo.id, "layer": layer, "item_no": wo.item_no, "unit": wo.unit}
                if key in not_done:
                    body.append(tag | {"kind": "not_done", "particulars": f"{_item_label(wo, layer, item)}: work not done"})
                    continue
                try:
                    lines = _lines_for(a, item, wo, layer, edges, by_id, way)
                except Question as q:
                    out.questions.append({"kind": "area", "area_id": a.id, "wo_line_id": wo.id, "text": str(q)})
                    continue
                for ln in lines:
                    ln.update(tag)
                    if item.layers_as_no and n_layers > 1:
                        ln["no"], ln["qty"] = Decimal(ln.get("no") or 1) * n_layers, Decimal(ln["qty"]) * n_layers
                        ln["particulars"] += f" ({n_layers} layers)"
                    ln["total"] = None if way.per_item else geom.round3(Decimal(ln["qty"]) * way.factor(wo.unit))
                body.extend(lines)
            if body:
                blocks[(a.id, wo.id)] = body
    if way.per_item:
        # the billing team's layout: per item its areas, then the item's total, converted once
        for _item, wo in items:
            mine = [(a, blocks[(a.id, wo.id)]) for a in areas if (a.id, wo.id) in blocks]
            if not mine:
                continue
            first = (wo.description or "").splitlines()[0][:90] if wo.description else ""
            out.lines.append({"kind": "area", "wo_line_id": wo.id, "item_no": wo.item_no, "particulars": f"{wo.item_no or ''} {first}".strip()})
            for a, body in mine:
                out.lines.append({"kind": "area", "area_id": a.id, "particulars": _area_head(a, by_id, way)})
                out.lines.extend(body)
            q = sum((Decimal(ln["qty"]) for _, body in mine for ln in body if ln.get("qty") is not None), ZERO)
            f = way.factor(wo.unit)
            out.lines.append({"kind": "total", "wo_line_id": wo.id, "item_no": wo.item_no, "unit": wo.unit, "particulars": "Total quantity", "qty": q,
                              "total": geom.round3(q * f), "formula": f"{_n(q, 6)} sqm × {f} = {_n(q * f, 6)} {wo.unit}" if f != 1 else None})  # fmt: skip
    else:
        for a in areas:
            body = [ln for _item, wo in items for ln in blocks.get((a.id, wo.id), [])]
            if body:
                out.lines.append({"kind": "area", "area_id": a.id, "particulars": _area_head(a, by_id, way)})
                out.lines.extend(body)
    for e in edges:
        if e.answer is None:
            a, b = by_id[e.area_a_id], by_id[e.area_b_id]
            out.questions.append({"kind": "edge", "edge_id": e.id, "text": f"{a.code}|{b.code}: {_n(Decimal(e.length_m), 3)} m shared. Wall on this edge?"})
    return out


def _periphery(a, way: Way) -> Decimal:
    """The periphery a way takes: the closed outline's (the app's), or the line as drawn when the
    outline was left open (the length AutoCAD shows for it)."""
    if way.drawn_periphery and a.drawn_length_m is not None and not a.trim_with:
        return way.fix(a.drawn_length_m)
    return way.fix(a.net_periphery_m)


def _area_head(a, by_id: dict, way: Way) -> str:
    gap = f"; drawn open ({_n(Decimal(a.closed_gap_mm), 1)} mm gap), closed by the app" if a.closed_gap_mm and not way.drawn_periphery else ""
    return (f"{a.code} — {a.name}: {'plan ' if a.kind == 'slope' else ''}area {_n(way.fix(a.net_area_sqm))} sqm, periphery {_n(_periphery(a, way), 3)} m"
            + (f" (less the overlap with {', '.join(by_id[i].code for i in a.trim_with if i in by_id)})" if a.trim_with else "") + gap)  # fmt: skip


def _item_label(wo: ClientWorkOrderLine, layer: int, item) -> str:
    text = (wo.description or "").splitlines()[0][:80] if wo.description else ""
    return f"{text}{f' (layer {layer})' if (item.layers or 1) > 1 and (wo.per_layer or item.layers_answer == 'each') else ''}"


def _lines_for(a, item, wo: ClientWorkOrderLine, layer: int, edges: list, by_id: dict, way: Way | None = None) -> list[dict]:
    way = way or Way()
    kind = unit_kind(wo.unit)
    skip = set((item.skip or {}).get(str(a.id), []))
    parts = [p for p in (item.parts or []) if p not in skip]
    lab = _item_label(wo, layer, item)
    out: list[dict] = []
    net, per = way.fix(a.net_area_sqm), _periphery(a, way)
    mine = [e for e in edges if a.id in (e.area_a_id, e.area_b_id) and e.answer != "none"]

    def other(e):
        return by_id.get(e.area_b_id if e.area_a_id == a.id else e.area_a_id)

    def unanswered():
        for e in mine:
            if e.answer is None:
                o = other(e)
                raise Question(f"{a.code}|{o.code if o else '?'}: answer the shared edge ({_n(Decimal(e.length_m), 3)} m) first")

    if kind == "count" or "count" in parts:
        typed = (item.manual or {}).get(str(a.id))
        if typed is not None and "count" not in skip:
            n = Decimal(str(typed))
            out.append({"kind": "line", "part": "count", "particulars": f"{lab}: counted on site in {a.code}", "no": n, "qty": n, "formula": f"{_n(n, 3)} counted on site"})
            return out
        n = Decimal((a.counts or {}).get(item.count_of or "", 0))
        if n:
            out.append({"kind": "line", "part": "count", "particulars": f"{lab}: {item.count_of.split(':', 1)[-1] if item.count_of else 'counted'} inside {a.code}", "no": n, "qty": n,
                        "formula": f"{n} counted on the drawing inside {a.code}"})  # fmt: skip
        return out
    if a.kind == "slope":
        if "floor" in parts or "slope" in parts:
            f, how = slope_of(a)
            q = net * f
            out.append({"kind": "line", "part": "slope", "particulars": f"{lab}: slope face, plan × slope length / run ({a.slope_source or 'section'})", "no": Decimal(1),
                        "qty": q, "formula": f"{_n(net)} sqm × {how} = {_n(q)} sqm"})  # fmt: skip
        return out
    if kind == "length":
        if "walls" in parts or "tops" in parts or "floor" in parts:
            out.append({"kind": "line", "part": "walls", "particulars": f"{lab}: periphery of {a.code}", "no": Decimal(1), "length_m": per, "qty": per,
                        "formula": f"periphery {_n(per, 3)} m (arcs as arcs)"})  # fmt: skip
        return out
    if "floor" in parts:
        out.append({"kind": "line", "part": "floor", "particulars": f"{lab}: floor of {a.code} (outline as drawn, arcs as arcs)", "no": Decimal(1), "qty": net,
                    "formula": f"outline area {_n(net)} sqm"})  # fmt: skip
    if "walls" in parts:
        unanswered()
        h, src = avg_height_m(a, way)
        q = per * h
        out.append({"kind": "line", "part": "walls", "particulars": f"{lab}: side walls, periphery × height ({src})", "no": Decimal(1), "length_m": per, "height_m": h,
                    "qty": q, "formula": f"{_n(per, 3)} m × {_n(h, 3)} m = {_n(q)} sqm"})  # fmt: skip
        for e in mine:
            o, ln = other(e), way.fix(e.length_m)
            if e.answer == "open":
                out.append({"kind": "deduction", "part": "walls", "edge_id": e.id, "particulars": f"Less: no wall on the edge with {o.code}", "no": Decimal(1), "length_m": ln, "height_m": h,
                            "qty": -(ln * h), "reason": f"Open edge with {o.code} {o.name} (answered: open, no wall)"})  # fmt: skip
            elif e.answer == "weir":
                w = min(way.fix(Decimal(e.weir_mm) / 1000), h)
                if h - w > 0:
                    out.append({"kind": "deduction", "part": "walls", "edge_id": e.id, "particulars": f"Less: weir to {o.code}, wall only up to {_n(w * 1000, 1)} mm", "no": Decimal(1), "length_m": ln,
                                "height_m": h - w, "qty": -(ln * (h - w)), "reason": f"Weir or cut wall on the edge with {o.code} {o.name}: {_n(w * 1000, 1)} mm high"})  # fmt: skip
    if "tops" in parts:
        unanswered()
        t = way.fix(Decimal(a.wall_top_mm) / 1000)
        q = per * t
        out.append({"kind": "line", "part": "tops", "particulars": f"{lab}: wall tops, periphery × {_n(t * 1000, 1)} mm", "no": Decimal(1), "length_m": per, "width_m": t,
                    "qty": q, "formula": f"{_n(per, 3)} m × {_n(t, 3)} m = {_n(q)} sqm"})  # fmt: skip
        for e in mine:
            o, ln = other(e), way.fix(e.length_m)
            if e.answer == "open":
                out.append({"kind": "deduction", "part": "tops", "edge_id": e.id, "particulars": f"Less: no wall top on the edge with {o.code}", "no": Decimal(1), "length_m": ln, "width_m": t,
                            "qty": -(ln * t), "reason": f"Open edge with {o.code} {o.name}"})  # fmt: skip
            elif e.area_b_id == a.id and "tops" not in (item.skip or {}).get(str(o.id), []):
                # one wall between the two: its top is measured once, with the first area
                out.append({"kind": "deduction", "part": "tops", "edge_id": e.id, "particulars": f"Less: wall top shared with {o.code} (measured there)", "no": Decimal(1), "length_m": ln, "width_m": t,
                            "qty": -(ln * t), "reason": f"One wall between {o.code} and {a.code}: its top counted once"})  # fmt: skip
    return out


def store(db: Session, sheet: MeasureSheet, built: Built) -> list[MeasureLine]:
    """The built lines written onto the sheet (a draft's are replaced each time)."""
    for old in db.scalars(select(MeasureLine).where(MeasureLine.sheet_id == sheet.id)):
        db.delete(old)
    db.flush()
    rows = []
    for i, ln in enumerate(built.lines):
        rows.append(MeasureLine(sheet_id=sheet.id, sort_order=i, kind=ln["kind"], area_id=ln.get("area_id"), edge_id=ln.get("edge_id"), wo_line_id=ln.get("wo_line_id"),
                                item_no=ln.get("item_no"), layer=ln.get("layer") or 1, part=ln.get("part"), particulars=ln["particulars"], no=ln.get("no"),
                                length_m=ln.get("length_m"), width_m=ln.get("width_m"), height_m=ln.get("height_m"), qty=ln.get("qty"), total=ln.get("total"),
                                unit=ln.get("unit"), formula=ln.get("formula"), reason=ln.get("reason")))  # fmt: skip
    db.add_all(rows)
    db.flush()
    return rows


def lines_of(db: Session, sheet_id: int) -> list[MeasureLine]:
    return list(db.scalars(select(MeasureLine).where(MeasureLine.sheet_id == sheet_id).order_by(MeasureLine.sort_order)))


def totals(lines: list[MeasureLine]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for ln in lines:
        if ln.wo_line_id and ln.total is not None:
            out[ln.wo_line_id] = out.get(ln.wo_line_id, ZERO) + Decimal(ln.total)
    return out


def approved(db: Session, sheet: MeasureSheet) -> dict[int, Decimal] | None:
    """Per item, what the client approved of this sheet in the measurement book (a correction
    included); None until every line of it is approved (a draft, or still with the client)."""
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.team.models import Measurement  # noqa: PLC0415

    book = list(db.scalars(select(Measurement).where(Measurement.site_id == sheet.site_id, Measurement.note.like(f"{sheet.code}:%"))))
    if not book or any(m.status != "approved" for m in book):
        return None
    wo_of = dict(db.execute(select(ContractLine.id, ContractLine.wo_line_id).where(ContractLine.id.in_({m.contract_line_id for m in book if m.contract_line_id}))).all())
    out: dict[int, Decimal] = {}
    for m in book:
        w = wo_of.get(m.contract_line_id)
        if w:
            out[w] = out.get(w, ZERO) + Decimal(m.qty)
    return out


def billed_totals(db: Session, sheet: MeasureSheet) -> dict[int, Decimal]:
    """What the sheet bills per item: the client's approved figures once they approved it, else
    the drawing's. The sheet's Abstract, the RA bill, the Excel and the PDF all take this."""
    ok = approved(db, sheet)
    return ok if ok is not None else totals(lines_of(db, sheet.id))


def cumulative(db: Session, sheet: MeasureSheet, wo_lines: list[ClientWorkOrderLine]) -> list[dict]:
    """Per item: the previous sheets' (sent or later, imported ones included), this sheet's and up
    to date, as billed (the client's approved figure); this sheet's drawing figure beside it."""
    earlier = list(db.scalars(select(MeasureSheet).where(MeasureSheet.site_id == sheet.site_id, MeasureSheet.seq < sheet.seq, MeasureSheet.status.in_(("sent", "approved", "billed")))))
    prev: dict[int, Decimal] = {}
    for s in earlier:
        for k, v in billed_totals(db, s).items():
            prev[k] = prev.get(k, ZERO) + v
    drawing = totals(lines_of(db, sheet.id))
    ok = approved(db, sheet)
    rows = []
    for w in wo_lines:
        p, d = prev.get(w.id, ZERO), drawing.get(w.id, ZERO)
        a = ok.get(w.id, ZERO) if ok is not None else None
        t = a if a is not None else d
        note = f"{_n(d, 3)} on the drawing, {_n(a, 3)} approved by the client" if a is not None and a != d else None
        rows.append({"wo_line_id": w.id, "item_no": w.item_no, "description": w.description, "unit": w.unit, "wo_qty": w.qty, "rate": w.rate,
                     "previous": p, "drawing": d, "approved": a, "this": t, "upto": p + t, "note": note})  # fmt: skip
    return rows


def work_order_lines(db: Session, site_id: int) -> list[ClientWorkOrderLine]:
    wo = db.scalar(select(ClientWorkOrder).where(ClientWorkOrder.site_id == site_id).order_by(ClientWorkOrder.status != "accepted", ClientWorkOrder.id.desc()).limit(1))
    return list(wo.lines) if wo else []


def new_sheet(db: Session, site, measured_on: date, title: str | None, user_id) -> MeasureSheet:
    seq = (db.scalar(select(MeasureSheet.seq).where(MeasureSheet.site_id == site.id).order_by(MeasureSheet.seq.desc()).limit(1)) or 0) + 1
    s = MeasureSheet(site_id=site.id, seq=seq, code=f"MS-{site.code}-{seq:02d}", title=title, measured_on=measured_on, created_by=user_id)
    db.add(s)
    db.flush()
    return s
