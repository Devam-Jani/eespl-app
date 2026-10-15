# ruff: noqa: E501  (the entity table reads better unwrapped)
"""Reading a DXF with ezdxf: the units ($INSUNITS, never assumed), the layers with their entity
counts, texts and multi-line texts with their positions, dimensions with their values, blocks
(inserts, their attributes, and what they draw), lines, polylines, arcs and circles, and the
layouts. The geometry for the viewer is written as compact JSON (segments per layer)."""

import gzip
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.takeoff.dwg import CadError

# $INSUNITS -> (name, metres per unit); 0 is "unitless": the user says what it is
UNITS = {
    0: ("unitless", None), 1: ("inches", 0.0254), 2: ("feet", 0.3048), 3: ("miles", 1609.344),
    4: ("millimetres", 0.001), 5: ("centimetres", 0.01), 6: ("metres", 1.0), 7: ("kilometres", 1000.0),
    8: ("microinches", 0.0000000254), 9: ("mils", 0.0000254), 10: ("yards", 0.9144),
    14: ("decimetres", 0.1),
}  # fmt: skip
GEOMETRY = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
MAX_DEPTH = 3  # blocks inside blocks


@dataclass
class Parsed:
    version: str | None
    units_code: int
    unit_name: str
    unit_m: float | None
    layers: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # everything, blocks expanded
    top: dict[str, int] = field(default_factory=dict)  # in model space itself
    # [x, y, h, layer, text, in_block]: texts inside blocks (symbols, tags) are drawn, not read
    texts: list[list] = field(default_factory=list)
    dimensions: list[list] = field(default_factory=list)  # [x, y, value, text, layer]
    inserts: list[dict] = field(default_factory=list)
    layouts: list[str] = field(default_factory=list)
    # sheet frames: [x1, y1, x2, y2, source] (title-block rectangles, layout viewport windows)
    frames: list[list] = field(default_factory=list)
    # model-space clusters: the bounding boxes of groups of drawn things that touch [x1, y1, x2, y2]
    clusters: list[list] = field(default_factory=list)
    extents: list[float] | None = None
    geometry: dict = field(default_factory=dict)  # {layer: {"s": [x1, y1, x2, y2, ...]}}

    def summary(self) -> dict:
        return {
            "version": self.version, "units_code": self.units_code, "unit_name": self.unit_name,
            "unit_m": self.unit_m, "layers": self.layers, "counts": self.counts, "top": self.top,
            "texts": len(self.texts), "dimensions": len(self.dimensions),
            "inserts": len(self.inserts), "blocks": sorted({i["block"] for i in self.inserts})[:300],
            "layouts": self.layouts, "extents": self.extents, "frames": self.frames, "clusters": self.clusters,
        }  # fmt: skip


def plain(e) -> str:
    try:
        if e.dxftype() == "MTEXT":
            return e.plain_text()
        return e.plain_text() if hasattr(e, "plain_text") else (e.dxf.text or "")
    except Exception:  # noqa: BLE001  (broken formatting codes: the raw text)
        return getattr(e.dxf, "text", "") or ""


def _point(e) -> tuple[float, float]:
    if e.dxftype() == "TEXT" and e.dxf.hasattr("align_point") and e.dxf.halign + e.dxf.valign:
        p = e.dxf.align_point
    else:
        p = e.dxf.insert
    return (float(p.x), float(p.y))


def _flatten(e) -> list[tuple[float, float]]:
    """The entity's points as a polyline (arcs, circles, ellipses and splines approximated)."""
    t = e.dxftype()
    if t == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if t == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in e.get_points("xy")]
        if e.closed and pts:
            pts.append(pts[0])
        return pts
    if t == "POLYLINE":
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        if e.is_closed and pts:
            pts.append(pts[0])
        return pts
    if t == "CIRCLE":
        r, c = e.dxf.radius, e.dxf.center
        return [
            (c.x + r * math.cos(a / 16 * math.tau), c.y + r * math.sin(a / 16 * math.tau))
            for a in range(17)
        ]
    if t in ("ARC", "ELLIPSE", "SPLINE"):
        try:
            return [(p.x, p.y) for p in e.flattening(max(1e-3, _size(e) / 50))]
        except Exception:  # noqa: BLE001
            return []
    return []


def _size(e) -> float:
    try:
        return float(getattr(e.dxf, "radius", 0) or 1.0)
    except Exception:  # noqa: BLE001
        return 1.0


def read(path: Path, version: str | None = None, hidden: set[str] | None = None) -> Parsed:
    """Read the DXF (recovering from the errors converted drawings carry)."""
    import ezdxf  # noqa: PLC0415  (only the takeoff needs it)
    from ezdxf import recover  # noqa: PLC0415

    try:
        doc, _auditor = recover.readfile(str(path))
    except (OSError, ezdxf.DXFStructureError) as exc:
        raise CadError(
            f"The drawing could not be read after conversion ({type(exc).__name__})."
        ) from exc
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    name, unit_m = UNITS.get(code, (f"code {code}", None))
    out = Parsed(version=version, units_code=code, unit_name=name, unit_m=unit_m)
    hidden = hidden or set()
    counts: Counter = Counter()
    top: Counter = Counter()
    per_layer: Counter = Counter()
    segs: dict[str, list[float]] = defaultdict(list)
    xs: list[float] = []
    ys: list[float] = []
    rects: list[list] = []

    def take(e, depth: int) -> None:
        t = e.dxftype()
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        counts[t] += 1
        if depth == 0:
            top[t] += 1
        per_layer[layer] += 1
        if t in ("TEXT", "MTEXT"):
            text = " ".join(plain(e).split()) if t == "TEXT" else plain(e).strip()
            if text:
                x, y = _point(e)
                h = float(e.dxf.char_height if t == "MTEXT" else e.dxf.height or 0)
                out.texts.append([round(x, 2), round(y, 2), round(h, 2), layer, text, depth > 0])
        elif t == "DIMENSION":
            try:
                value = float(e.get_measurement())
            except Exception:  # noqa: BLE001
                value = float(e.dxf.get("actual_measurement", 0) or 0)
            p = e.dxf.get("text_midpoint") or e.dxf.get("defpoint")
            text = e.dxf.get("text", "") or ""
            out.dimensions.append(
                [
                    round(p.x, 2) if p else None,
                    round(p.y, 2) if p else None,
                    round(value, 3),
                    text.replace("<>", "").strip(),
                    layer,
                ]
            )
        elif t == "INSERT":
            attribs = {a.dxf.tag: a.dxf.text for a in e.attribs} if e.attribs else {}
            if depth == 0:
                out.inserts.append({"block": e.dxf.name, "layer": layer, "x": round(e.dxf.insert.x, 2),
                                    "y": round(e.dxf.insert.y, 2), "attribs": attribs})  # fmt: skip
            for v in attribs.values():
                if v:
                    out.texts.append(
                        [round(e.dxf.insert.x, 2), round(e.dxf.insert.y, 2), 0, layer, f"{v}", True]
                    )
            if depth < MAX_DEPTH:
                try:
                    for v in e.virtual_entities():
                        if not (v.dxf.hasattr("layer") and v.dxf.layer == "0"):
                            take(v, depth + 1)
                        else:  # entities on layer 0 in a block take the insert's layer
                            v.dxf.layer = layer
                            take(v, depth + 1)
                except Exception:  # noqa: BLE001  (a broken block: skipped, the rest read)
                    counts["broken_block"] += 1
        if t in ("LWPOLYLINE", "POLYLINE"):
            r = _rectangle(_flatten(e))
            if r:
                rects.append([*r, f"rectangle on {layer}"])
        if t in GEOMETRY and layer not in hidden:
            pts = _flatten(e)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
                segs[layer].extend((round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)))
                xs.extend((x1, x2))
                ys.extend((y1, y2))

    for e in doc.modelspace():
        take(e, 0)
    if not counts:
        raise CadError(
            "The file has nothing drawn in it (or is not a real DXF); export it again from "
            "AutoCAD, or upload the .dwg."
        )
    colors = {ly.dxf.name: (ly.dxf.color, ly.is_off(), ly.is_frozen()) for ly in doc.layers}
    out.layers = [
        {"name": n, "count": per_layer.get(n, 0), "color": colors.get(n, (7, False, False))[0],
         "off": colors.get(n, (7, False, False))[1], "frozen": colors.get(n, (7, False, False))[2]}
        for n in sorted(set(colors) | set(per_layer), key=lambda n: (-per_layer.get(n, 0), n))
    ]  # fmt: skip
    out.counts = dict(counts.most_common())
    out.top = dict(top.most_common())
    out.layouts = [lay.name for lay in doc.layouts]
    if xs:
        # the bulk of the drawing (a stray far point would make the view useless)
        xs.sort()
        ys.sort()
        lo, hi = int(len(xs) * 0.001), max(0, int(len(xs) * 0.999) - 1)
        out.extents = [xs[lo], ys[lo], xs[hi], ys[hi]]
    out.geometry = {layer: {"s": s} for layer, s in segs.items()}
    out.frames = _frames(rects, out.extents) + _viewports(doc, out.extents)
    out.clusters = clusters(segs, out.extents)
    return out


def clusters(
    segs: dict[str, list[float]], extents: list[float] | None, cells: int = 300
) -> list[list]:
    """Groups of drawn things that touch, on a coarse grid (a plan with its labels, a schedule,
    a title block): their bounding boxes, largest first. Used when a drawing has no frames."""
    if not extents:
        return []
    x0, y0, x1, y1 = extents
    size = max(x1 - x0, y1 - y0) / cells or 1.0
    filled: set[tuple[int, int]] = set()
    for s in segs.values():
        for i in range(0, len(s), 4):
            ax, ay, bx, by = s[i : i + 4]
            n = max(1, int(max(abs(bx - ax), abs(by - ay)) / size))
            for k in range(n + 1):
                x, y = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
                if x0 - size <= x <= x1 + size and y0 - size <= y <= y1 + size:
                    filled.add((int((x - x0) // size), int((y - y0) // size)))
    seen: set[tuple[int, int]] = set()
    out = []
    for start in filled:
        if start in seen:
            continue
        stack, cells_ = [start], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            cells_.append((cx, cy))
            for dx in (-2, -1, 0, 1, 2):  # a gap of one empty cell still joins
                for dy in (-2, -1, 0, 1, 2):
                    nb = (cx + dx, cy + dy)
                    if nb in filled and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        if len(cells_) < 4:
            continue
        xs = [c[0] for c in cells_]
        ys = [c[1] for c in cells_]
        out.append([round(x0 + min(xs) * size, 2), round(y0 + min(ys) * size, 2),
                    round(x0 + (max(xs) + 1) * size, 2), round(y0 + (max(ys) + 1) * size, 2), len(cells_)])  # fmt: skip
    out.sort(key=lambda c: -c[4])
    return out[:400]


def _rectangle(pts: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """A closed axis-aligned rectangle (4 corners, the first repeated or not) as x1, y1, x2, y2."""
    if len(pts) == 5 and math.dist(pts[0], pts[4]) < 1e-6:
        pts = pts[:4]
    if len(pts) != 4:
        return None
    xs = sorted({round(p[0], 3) for p in pts})
    ys = sorted({round(p[1], 3) for p in pts})
    if len(xs) != 2 or len(ys) != 2:
        return None
    return (xs[0], ys[0], xs[1], ys[1])


def _frames(rects: list[list], extents: list[float] | None) -> list[list]:
    """The rectangles big enough to be a sheet or a plan's frame (at least 1 % of the drawing
    each way: drawings with many sheets side by side are wide); window and door rectangles are
    far smaller. Only those around a plan title are used (see service._plan_for)."""
    if not extents:
        return []
    w, h = extents[2] - extents[0], extents[3] - extents[1]
    out = {
        tuple(round(v, 2) for v in r[:4]): r[4]
        for r in rects
        if r[2] - r[0] >= 0.01 * w and r[3] - r[1] >= 0.01 * h
    }
    return [[*k, v] for k, v in out.items()][:3000]


def _viewports(doc, extents: list[float] | None) -> list[list]:
    """The model-space window each layout viewport shows (a plan put on its sheet), named by the
    layout; the layout's own sheet viewport shows paper, not the drawing, so only windows over
    the drawing count (converted drawings number every viewport 1)."""
    out = []
    for lay in doc.layouts:
        if lay.name == "Model":
            continue
        for v in lay.query("VIEWPORT"):
            try:
                if not extents or not v.dxf.height or not v.dxf.view_height:
                    continue
                c, vh = v.dxf.view_center_point, float(v.dxf.view_height)
                vw = vh * float(v.dxf.width) / float(v.dxf.height)
                if (c.x + vw / 2 < extents[0] or c.x - vw / 2 > extents[2]
                        or c.y + vh / 2 < extents[1] or c.y - vh / 2 > extents[3]):  # fmt: skip
                    continue
                out.append([round(c.x - vw / 2, 2), round(c.y - vh / 2, 2), round(c.x + vw / 2, 2),
                            round(c.y + vh / 2, 2), f"layout {lay.name}"])  # fmt: skip
            except Exception:  # noqa: BLE001,S112  (a broken viewport: no window)
                continue
    return out[:200]


def write_geometry(parsed: Parsed, path: Path) -> None:
    """The viewer's file: layers (with colours and counts), segments per layer, texts, extents."""
    data = {
        "extents": parsed.extents,
        "unit_m": parsed.unit_m,
        "layers": parsed.layers,
        "geometry": parsed.geometry,
        "texts": parsed.texts,
        "dimensions": parsed.dimensions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def load_geometry(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)
