# ruff: noqa: E501  (the sheet's lines read better unwrapped)
"""Measuring from the drawing (areas, their trims, shared edges, heights) and building the
measurement sheet in the billing team's layout.

The sheet is built from the areas each time it is opened while a draft, so a corrected height or
an answered edge shows at once; once sent its lines are kept as they were sent. What cannot be
measured yet (no height, an unanswered edge, a layer question) is returned as a question, never
guessed."""

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

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
    """Closed polylines and circles in model space (metres, bulges kept), the circles and block
    inserts as markers to count, and nothing else: the viewer draws the rest."""
    doc = _open_dxf(Path(path))
    u = unit_m
    outlines, markers = [], []
    for e in doc.modelspace():
        t = e.dxftype()
        try:
            if t == "LWPOLYLINE" and e.closed:
                pts = [[x * u, y * u, b] for x, y, b in e.get_points("xyb")]
                if len(pts) >= 2:
                    outlines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "outline": pts})
            elif t == "POLYLINE" and e.is_2d_polyline and e.is_closed:
                pts = [[v.dxf.location.x * u, v.dxf.location.y * u, v.dxf.bulge or 0.0] for v in e.vertices]
                if len(pts) >= 2:
                    outlines.append({"handle": e.dxf.handle, "layer": e.dxf.layer, "outline": pts})
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
    return {"outlines": outlines[:20000], "markers": markers}


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
              cad_file=None, handle: str | None = None, layer: str | None = None, picked: bool = True, user_id=None) -> MeasureArea:
    if len(outline) < 2 or geom.area(outline) <= 1e-9:
        raise Question("That outline has no area")
    code = (code or "").strip().upper() or next_code(db, site_id)
    if db.scalar(select(MeasureArea.id).where(MeasureArea.site_id == site_id, MeasureArea.code == code)):
        raise Question(f"Area {code} exists: give another letter")
    a = MeasureArea(site_id=site_id, cad_file_id=cad_file.id if cad_file else None, code=code, name=name.strip() or code, kind=kind,
                    outline=[[float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0] for p in outline],
                    picked=picked, handle=handle, layer=layer, area_sqm=geom.d(geom.area(outline)), periphery_m=geom.d(geom.periphery(outline)),
                    net_area_sqm=ZERO, net_periphery_m=ZERO, trim_with=[], counts={}, created_by=user_id)  # fmt: skip
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
    old = {(e.area_a_id, e.area_b_id, _key(e.line)): e for e in db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == site_id))}
    keep = set()
    for i, a in enumerate(areas):
        for b in areas[i + 1 :]:
            for seq, (length, line) in enumerate(geom.shared_edges(a.outline, b.outline)):
                k = (a.id, b.id, _key(line))
                e = old.get(k)
                if e is None:
                    e = MeasureEdge(site_id=site_id, area_a_id=a.id, area_b_id=b.id, seq=seq, length_m=geom.d(length), line=list(line))
                    db.add(e)
                    old[k] = e
                e.length_m, e.line = geom.d(length), list(line)
                keep.add(k)
    for k, e in old.items():
        if k not in keep:
            db.delete(e)
    db.flush()


def _key(line) -> tuple:
    """An edge's ends to the millimetre, in either direction."""
    a = (round(line[0], 3), round(line[1], 3))
    b = (round(line[2], 3), round(line[3], 3))
    return tuple(sorted((a, b)))


def edges_of(db: Session, site_id: int) -> list[MeasureEdge]:
    return list(db.scalars(select(MeasureEdge).where(MeasureEdge.site_id == site_id).order_by(MeasureEdge.id)))


def avg_height_m(a: MeasureArea) -> tuple[Decimal, str]:
    """The walls' height: one height, or the average of the shallow and the deep end."""
    if a.height_mm is None:
        raise Question(f"{a.code} {a.name}: pick its height from a section")
    h1 = Decimal(a.height_mm)
    if a.height2_mm is None:
        return h1 / 1000, a.height_source or f"{h1.normalize():f} mm"
    h2 = Decimal(a.height2_mm)
    return (h1 + h2) / 2000, f"average of {h1.normalize():f} and {h2.normalize():f} mm ({a.height_source}; {a.height2_source})"


def slope_of(a: MeasureArea) -> tuple[Decimal, str]:
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


def items_of(db: Session, site_id: int) -> list[tuple[MeasureItem, ClientWorkOrderLine]]:
    rows = db.execute(
        select(MeasureItem, ClientWorkOrderLine).join(ClientWorkOrderLine, ClientWorkOrderLine.id == MeasureItem.wo_line_id)
        .where(MeasureItem.site_id == site_id).order_by(ClientWorkOrderLine.sort_order, ClientWorkOrderLine.id)
    )  # fmt: skip
    return [(m, w) for m, w in rows]


def layers_billed(item: MeasureItem, wo: ClientWorkOrderLine) -> list[int]:
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
    each deduction a negative line with its reason. Totals per line in the item's unit."""
    out = Built()
    areas = areas_of(db, sheet.site_id)
    edges = edges_of(db, sheet.site_id)
    by_id = {a.id: a for a in areas}
    done_elsewhere = billed_elsewhere(db, sheet)
    not_done = {tuple(x) for x in (sheet.not_done or [])}
    items = items_of(db, sheet.site_id)
    for a in areas:
        head = {"kind": "area", "area_id": a.id, "particulars": f"{a.code} — {a.name}: {'plan ' if a.kind == 'slope' else ''}area {_n(Decimal(a.net_area_sqm))} sqm, periphery {_n(Decimal(a.net_periphery_m), 3)} m"
                + (f" (less the overlap with {', '.join(by_id[i].code for i in a.trim_with if i in by_id)})" if a.trim_with else "")}  # fmt: skip
        body: list[dict] = []
        for item, wo in items:
            if item.areas and a.id not in item.areas:
                continue
            try:
                layers = layers_billed(item, wo)
            except Question as q:
                out.questions.append({"kind": "layers", "wo_line_id": wo.id, "text": str(q)})
                continue
            for layer in layers:
                key = (a.id, wo.id, layer)
                if key in done_elsewhere:
                    continue  # billed on an earlier sheet: it is in the previous quantity
                tag = {"area_id": a.id, "wo_line_id": wo.id, "layer": layer, "item_no": wo.item_no, "unit": wo.unit}
                if key in not_done:
                    body.append(tag | {"kind": "not_done", "particulars": f"{_item_label(wo, layer, item)}: work not done"})
                    continue
                try:
                    lines = _lines_for(a, item, wo, layer, edges, by_id)
                except Question as q:
                    out.questions.append({"kind": "area", "area_id": a.id, "wo_line_id": wo.id, "text": str(q)})
                    continue
                for ln in lines:
                    ln.update(tag)
                    ln["total"] = geom.round3(Decimal(ln["qty"]) * factor(wo.unit))
                body.extend(lines)
        if body:
            out.lines.append(head)
            out.lines.extend(body)
    for e in edges:
        if e.answer is None and e.area_a_id in by_id and e.area_b_id in by_id:
            a, b = by_id[e.area_a_id], by_id[e.area_b_id]
            out.questions.append({"kind": "edge", "edge_id": e.id, "text": f"{a.code}|{b.code}: {_n(Decimal(e.length_m), 3)} m shared. Wall on this edge?"})
    return out


def _item_label(wo: ClientWorkOrderLine, layer: int, item: MeasureItem) -> str:
    text = (wo.description or "").split("\n")[0][:80]
    return f"{text}{f' (layer {layer})' if (item.layers or 1) > 1 and (wo.per_layer or item.layers_answer == 'each') else ''}"


def _lines_for(a: MeasureArea, item: MeasureItem, wo: ClientWorkOrderLine, layer: int, edges: list[MeasureEdge], by_id: dict) -> list[dict]:
    kind = unit_kind(wo.unit)
    parts = list(item.parts or [])
    lab = _item_label(wo, layer, item)
    out: list[dict] = []
    net, per = Decimal(a.net_area_sqm), Decimal(a.net_periphery_m)
    mine = [e for e in edges if a.id in (e.area_a_id, e.area_b_id)]

    def other(e):
        return by_id.get(e.area_b_id if e.area_a_id == a.id else e.area_a_id)

    def unanswered():
        for e in mine:
            if e.answer is None:
                o = other(e)
                raise Question(f"{a.code}|{o.code if o else '?'}: answer the shared edge ({_n(Decimal(e.length_m), 3)} m) first")

    if kind == "count" or "count" in parts:
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
        h, src = avg_height_m(a)
        q = per * h
        out.append({"kind": "line", "part": "walls", "particulars": f"{lab}: side walls, periphery × height ({src})", "no": Decimal(1), "length_m": per, "height_m": h,
                    "qty": q, "formula": f"{_n(per, 3)} m × {_n(h, 3)} m = {_n(q)} sqm"})  # fmt: skip
        for e in mine:
            o, ln = other(e), Decimal(e.length_m)
            if e.answer == "open":
                out.append({"kind": "deduction", "part": "walls", "edge_id": e.id, "particulars": f"Less: no wall on the edge with {o.code}", "no": Decimal(1), "length_m": ln, "height_m": h,
                            "qty": -(ln * h), "reason": f"Open edge with {o.code} {o.name} (answered: open, no wall)"})  # fmt: skip
            elif e.answer == "weir":
                w = min(Decimal(e.weir_mm) / 1000, h)
                if h - w > 0:
                    out.append({"kind": "deduction", "part": "walls", "edge_id": e.id, "particulars": f"Less: weir to {o.code}, wall only up to {_n(w * 1000, 1)} mm", "no": Decimal(1), "length_m": ln,
                                "height_m": h - w, "qty": -(ln * (h - w)), "reason": f"Weir or cut wall on the edge with {o.code} {o.name}: {_n(w * 1000, 1)} mm high"})  # fmt: skip
    if "tops" in parts:
        unanswered()
        t = Decimal(a.wall_top_mm) / 1000
        q = per * t
        out.append({"kind": "line", "part": "tops", "particulars": f"{lab}: wall tops, periphery × {_n(t * 1000, 1)} mm", "no": Decimal(1), "length_m": per, "width_m": t,
                    "qty": q, "formula": f"{_n(per, 3)} m × {_n(t, 3)} m = {_n(q)} sqm"})  # fmt: skip
        for e in mine:
            o, ln = other(e), Decimal(e.length_m)
            if e.answer == "open":
                out.append({"kind": "deduction", "part": "tops", "edge_id": e.id, "particulars": f"Less: no wall top on the edge with {o.code}", "no": Decimal(1), "length_m": ln, "width_m": t,
                            "qty": -(ln * t), "reason": f"Open edge with {o.code} {o.name}"})  # fmt: skip
            elif e.area_b_id == a.id:
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


def cumulative(db: Session, sheet: MeasureSheet, wo_lines: list[ClientWorkOrderLine]) -> list[dict]:
    """Per item: the previous sheets' totals (sent or later, imported ones included), this
    sheet's, and up to date."""
    earlier = list(db.scalars(select(MeasureSheet.id).where(MeasureSheet.site_id == sheet.site_id, MeasureSheet.seq < sheet.seq, MeasureSheet.status != "draft")))
    prev: dict[int, Decimal] = {}
    for sid in earlier:
        for k, v in totals(lines_of(db, sid)).items():
            prev[k] = prev.get(k, ZERO) + v
    this = totals(lines_of(db, sheet.id))
    rows = []
    for w in wo_lines:
        p, t = prev.get(w.id, ZERO), this.get(w.id, ZERO)
        rows.append({"wo_line_id": w.id, "item_no": w.item_no, "description": w.description, "unit": w.unit, "wo_qty": w.qty, "rate": w.rate,
                     "previous": p, "this": t, "upto": p + t})  # fmt: skip
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
