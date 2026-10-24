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
        yield p, q, (p[2] if len(p) > 2 else 0.0) or 0.0


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
    theta, r, _ = _arc(p, q, b)
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


def height_from(section: str, top: str, bottom: str) -> tuple[Decimal, str]:
    """A height picked from two levels on a section, with where it came from (kept on the area,
    shown on the sheet): "Section Y-Y: +1800 to +600 = 1200 mm"."""
    hi, lo = level_mm(top), level_mm(bottom)
    if hi is None or lo is None:
        raise ValueError("Pick two levels written on the section (like +1800 and +600)")
    h = abs(hi - lo)
    a, b = (top, bottom) if hi >= lo else (bottom, top)
    return h, f"{section.strip()}: {a.strip()} to {b.strip()} = {h.normalize():f} mm"
