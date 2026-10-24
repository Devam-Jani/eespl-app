# ruff: noqa: E501  (the geometry reads better unwrapped)
"""Measuring from the drawing: an outline is the closed polyline as drawn, its vertices in metres
with the bulge of the segment that leaves each one ([x, y, bulge]; bulge = tan(angle / 4), 0 for a
straight segment, as AutoCAD stores it). Area and periphery are exact (arcs as arcs, never as
chords). Only the overlap trim works on the outline flattened to chords a hundredth of a micron
off the arc, which keeps it within a fraction of a square millimetre.

Quantities leave here as Decimal at full precision; only a sheet line's total is rounded (to 3
decimals, half up, never truncated)."""

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from shapely.geometry import Polygon
from shapely.ops import unary_union

Outline = list[list[float]]  # [[x, y, bulge], ...] metres, closed (the last joins the first)

SQFT_PER_SQM = Decimal("10.7639")
WALL_TOP_MM = 250  # a wall's top, measured with its walls unless the area says otherwise
SAGITTA_M = 1e-8  # how far a chord may sit inside its arc when an outline is flattened
EDGE_TOL_M = 0.001  # two edges closer than a millimetre and parallel are one shared edge


def d(x: float) -> Decimal:
    """A float at its full precision (repr is the shortest exact round trip)."""
    return Decimal(repr(float(x)))


def round3(q: Decimal) -> Decimal:
    """A line total: 3 decimals, half up (so 0.0005 becomes 0.001), never truncated."""
    return Decimal(q).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def to_sqft(sqm: Decimal) -> Decimal:
    return Decimal(sqm) * SQFT_PER_SQM


def _bulge(p) -> float:
    """A vertex's bulge; one too small to make an arc (under 1e-9) is a straight segment."""
    b = (p[2] if len(p) > 2 else 0.0) or 0.0
    return b if abs(b) >= 1e-9 else 0.0


def _arc(p, q, b: float) -> tuple[float, float, float]:
    """(included angle, radius, chord) of the segment p -> q with bulge b (angle signed)."""
    chord = math.dist(p[:2], q[:2])
    theta = 4 * math.atan(b)
    r = chord / (2 * abs(math.sin(theta / 2))) if b else math.inf
    return theta, r, chord


def _segments(o: Outline):
    n = len(o)
    for i in range(n):
        p, q = o[i], o[(i + 1) % n]
        yield p, q, _bulge(p)


def signed_area(o: Outline) -> float:
    """Shoelace on the vertices plus each arc's segment (the part between chord and arc): a
    positive bulge turns counter-clockwise, which adds area to a counter-clockwise outline."""
    s = 0.0
    for p, q, b in _segments(o):
        s += (p[0] * q[1] - q[0] * p[1]) / 2
        if b:
            theta, r, _ = _arc(p, q, b)
            s += r * r / 2 * (theta - math.sin(theta))
    return s


def open_length(points: list[list[float]]) -> float:
    """A polyline's length as drawn, not closed (each segment to the next, arcs as arcs)."""
    total = 0.0
    for p, q in zip(points, points[1:], strict=False):
        b = _bulge(p)
        theta, r, chord = _arc(p, q, b)
        total += abs(r * theta) if b else chord
    return total


CLOSE_TOL_M = 0.05  # a polyline whose ends are this close was drawn round: the app closes it
SAME_POINT_M = 0.002  # ends this close are one point (the last vertex repeats the first)


def closable(points: list[list[float]], closed: bool) -> tuple[list[list[float]], float, float | None] | None:
    """An outline from a polyline: (its vertices, the gap closed in metres, its length as drawn), or
    None when it is open (its ends further apart than CLOSE_TOL_M). Closed in the drawing: no gap."""
    if len(points) < 2:
        return None
    if closed:
        return points, 0.0, None
    gap = math.dist(points[0][:2], points[-1][:2])
    if gap > CLOSE_TOL_M or len(points) < 3:
        return None
    drawn = open_length(points)
    if gap <= SAME_POINT_M:
        return points[:-1], gap, drawn
    pts = [list(p) for p in points]
    pts[-1] = [pts[-1][0], pts[-1][1], 0.0]  # the app's closing segment is straight
    return pts, gap, drawn


def area(o: Outline) -> float:
    return abs(signed_area(o))


def periphery(o: Outline) -> float:
    total = 0.0
    for p, q, b in _segments(o):
        theta, r, chord = _arc(p, q, b)
        total += abs(r * theta) if b else chord
    return total


def _arc_points(p, q, b: float) -> list[tuple[float, float]]:
    """The points of the arc p -> q after p (q included), each chord within SAGITTA_M of it."""
    theta, r, chord = _arc(p, q, b)
    if chord <= 1e-12:
        return [(q[0], q[1])]  # a zero-length segment (a repeated vertex) has no arc
    step = 2 * math.acos(max(-1.0, 1 - SAGITTA_M / r)) if r > SAGITTA_M else abs(theta)
    n = min(200_000, max(1, math.ceil(abs(theta) / step)))
    # the centre: from the chord's midpoint, along its normal
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    dx, dy = q[0] - p[0], q[1] - p[1]
    chord = math.hypot(dx, dy)
    # signed distance centre-to-chord: positive to the left of p -> q for a counter-clockwise arc
    off = (chord / 2) / math.tan(theta / 2)
    cx, cy = mx - dy / chord * off, my + dx / chord * off
    a0 = math.atan2(p[1] - cy, p[0] - cx)
    return [(cx + r * math.cos(a0 + theta * k / n), cy + r * math.sin(a0 + theta * k / n)) for k in range(1, n + 1)]


def flatten(o: Outline) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p, q, b in _segments(o):
        if not pts:
            pts.append((p[0], p[1]))
        if b:
            pts.extend(_arc_points(p, q, b))
        else:
            pts.append((q[0], q[1]))
    return pts[:-1]  # the last is the first again


def flatten_open(points: list[list[float]]) -> list[tuple[float, float]]:
    """An open polyline (or arc) in chords, for drawing it and measuring distances to it."""
    if not points:
        return []
    out = [(points[0][0], points[0][1])]
    for p, q in zip(points, points[1:], strict=False):
        b = _bulge(p)
        if b:
            out.extend(_arc_points(p, q, b))
        else:
            out.append((q[0], q[1]))
    return out


def polygon(o: Outline) -> Polygon:
    g = Polygon(flatten(o))
    return g if g.is_valid else g.buffer(0)


def contains(o: Outline, x: float, y: float) -> bool:
    from shapely.geometry import Point  # noqa: PLC0415

    return polygon(o).contains(Point(x, y))


def pick(outlines: list[tuple[int, Outline]], x: float, y: float) -> int | None:
    """A click inside outlines: the smallest one around the point (a tank inside a plant room)."""
    hits = [(area(o), key) for key, o in outlines if contains(o, x, y)]
    return min(hits)[1] if hits else None


def trim(o: Outline, others: list[Outline]) -> tuple[float, float, float]:
    """The outline less where it overlaps the others: (area, periphery, overlap area). With no
    overlap the exact figures; otherwise the exact area less the overlap, and the periphery of
    what is left (its cut edge included)."""
    mine = polygon(o)
    cut = [g for g in (polygon(x) for x in others) if g.intersects(mine) and g.intersection(mine).area > 1e-12]
    if not cut:
        return area(o), periphery(o), 0.0
    over = mine.intersection(unary_union(cut))
    left = mine.difference(unary_union(cut))
    return area(o) - over.area, left.length, over.area


def _straight(o: Outline) -> list[tuple[float, float, float, float]]:
    return [(p[0], p[1], q[0], q[1]) for p, q, b in _segments(o) if not b]


def _overlap(s, t, tol: float) -> tuple[float, tuple[float, float, float, float]] | None:
    """Two straight edges on one line (parallel, within tol of each other): the length they share."""
    ax, ay, bx, by = s
    ux, uy = bx - ax, by - ay
    ln = math.hypot(ux, uy)
    if ln < tol:
        return None
    ux, uy = ux / ln, uy / ln
    cx, cy, ex, ey = t
    # both ends of t within tol of s's line
    for px, py in ((cx, cy), (ex, ey)):
        if abs((px - ax) * uy - (py - ay) * ux) > tol:
            return None
    t0 = (cx - ax) * ux + (cy - ay) * uy
    t1 = (ex - ax) * ux + (ey - ay) * uy
    lo, hi = max(0.0, min(t0, t1)), min(ln, max(t0, t1))
    if hi - lo <= tol:
        return None
    return hi - lo, (ax + ux * lo, ay + uy * lo, ax + ux * hi, ay + uy * hi)


def shared_edges(a: Outline, b: Outline, tol: float = EDGE_TOL_M) -> list[tuple[float, tuple[float, float, float, float]]]:
    """The straight edges two outlines share (a pool and its balancing tank on one wall): each
    with its length and where it runs."""
    out = []
    for s in _straight(a):
        for t in _straight(b):
            hit = _overlap(s, t, tol)
            if hit:
                out.append(hit)
    return out


SHARE_TOL_M = 0.005  # outlines drawn side by side within 5 mm of each other share that edge
COINCIDE_TOL_M = 1e-9  # ... measured where they coincide (the same arc flattened the same way: a nanometre)
MIN_SHARED_M = 0.05  # shorter than 50 mm: a corner touching, not an edge


def _pieces(geometry) -> list:
    from shapely.geometry import LineString, MultiLineString  # noqa: PLC0415
    from shapely.ops import linemerge  # noqa: PLC0415

    lines = [g for g in getattr(geometry, "geoms", [geometry]) if isinstance(g, LineString | MultiLineString)]
    if not lines:
        return []
    joined = unary_union(lines)
    merged = linemerge(joined) if isinstance(joined, MultiLineString) else joined
    return [g for g in getattr(merged, "geoms", [merged]) if g.length >= MIN_SHARED_M]


def _path(line, most: int = 96) -> list[float]:
    """A shared edge's path for drawing it: [x1, y1, x2, y2, ...], at most `most` points."""
    pts = list(line.coords)
    step = max(1, len(pts) // most)
    keep = pts[::step]
    if keep[-1] != pts[-1]:
        keep.append(pts[-1])
    return [round(v, 6) for p in keep for v in p]


def shared_paths(a: Outline, b: Outline, a_trims_b: bool = False, b_trims_a: bool = False) -> list[tuple[float, list[float]]]:
    """Every edge two outlines share, straight or along an arc: (its true length, its path).

    Trimmed by the other (a slope drawn into the pool and cut back to it): the edge is the trimming
    outline inside the trimmed one, exactly. Side by side: the stretch of one outline within a few
    millimetres of the other, measured where the two coincide (within a micron) when they do. The
    arcs are measured on chords a hundredth of a micron off them: the true arc length."""
    pa, pb = polygon(a), polygon(b)
    if a_trims_b or b_trims_a:
        cutter, cut = (pa, pb) if a_trims_b else (pb, pa)
        pieces = _pieces(cutter.exterior.intersection(cut))
        return [(p.length, _path(p)) for p in pieces]
    if pa.intersection(pb).area > 1e-6:
        return []  # overlapping without a trim: not side by side
    from shapely.geometry import LineString  # noqa: PLC0415

    # straight edges on one line: exactly, as before; the rest (arcs) by how close the outlines run
    out = [(length, [round(v, 6) for v in line]) for length, line in shared_edges(a, b)]
    ra, rb = pa.exterior, pb.exterior
    rest = ra.difference(unary_union([LineString([s[1][:2], s[1][2:]]) for s in shared_edges(a, b)]).buffer(1e-6)) if out else ra
    near = _pieces(rest.intersection(rb.buffer(SHARE_TOL_M)))
    for p in near:
        exact = _pieces(p.intersection(rb.buffer(COINCIDE_TOL_M)))
        length = sum(x.length for x in exact)
        if length < 0.9 * p.length:
            # a few millimetres apart: the stretch within 5 mm, less its ends running past the corners
            length = max(0.0, p.length - 2 * SHARE_TOL_M)
        out.append((length, _path(p)))
    return out


def slope_factor(rise_m: Decimal, run_m: Decimal) -> Decimal:
    """Slope length / horizontal run: a sloped face's plan area times this is its true area."""
    rise, run = Decimal(rise_m), Decimal(run_m)
    return (rise * rise + run * run).sqrt() / run


# --- levels on a section -------------------------------------------------------------------------

_LEVEL = re.compile(r"(?<![\w.])([+\-±]\s*)?(\d+(?:\.\d+)?)(?:\s*(mm|m))?(?![\w.])")


def level_mm(text: str) -> Decimal | None:
    """A level written on a section: +1800, +1.800 (metres), -600, ± 0.00, FFL +600. A level
    with a decimal point is in metres unless it says mm."""
    m = _LEVEL.search(text.replace("±", "±"))
    if not m:
        return None
    sign = -1 if (m.group(1) or "").strip() == "-" else 1
    v = Decimal(m.group(2))
    unit = m.group(3)
    if unit == "m" or (unit is None and "." in m.group(2)):
        v *= 1000
    return sign * v


def height_sum(section: str, parts: list[str]) -> tuple[Decimal, str]:
    """A height added up from numbers on the drawing ("750 + 150 = 900 mm"), with its source."""
    vals = []
    for p in parts:
        m = re.search(r"\d+(?:\.\d+)?", p.replace(",", ""))
        if not m:
            raise ValueError(f"'{p}' is not a number")
        vals.append(Decimal(m.group(0)))
    if not vals:
        raise ValueError("Pick the numbers to add")
    h = sum(vals, Decimal(0))
    return h, f"{section.strip()}: {' + '.join(f'{v.normalize():f}' for v in vals)} = {h.normalize():f} mm"


def height_from(section: str, top: str, bottom: str) -> tuple[Decimal, str]:
    """A height picked from two levels on a section, with where it came from (kept on the area,
    shown on the sheet): "Section Y-Y: +1800 to +600 = 1200 mm"."""
    hi, lo = level_mm(top), level_mm(bottom)
    if hi is None or lo is None:
        raise ValueError("Pick two levels written on the section (like +1800 and +600)")
    h = abs(hi - lo)
    a, b = (top, bottom) if hi >= lo else (bottom, top)
    return h, f"{section.strip()}: {a.strip()} to {b.strip()} = {h.normalize():f} mm"
