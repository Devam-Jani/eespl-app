"""Tracing an area on a drawing: area and perimeter of the traced outline, snapping a click to the
drawing (an end point, an intersection, the foot of a perpendicular), and the outline proposed
for a click inside a room from the nearest wall lines in four directions (the user corrects it).

Rooms are not closed polylines in our drawings (loose wall lines, gaps at doors), so nothing here
builds an outline on its own: a proposal is a starting point the user accepts or corrects.
Everything is in drawing units; the caller converts with the drawing's unit."""

import math
from dataclasses import dataclass

Point = tuple[float, float]
Segment = tuple[float, float, float, float]


def area(points: list[Point]) -> float:
    """The shoelace area of a closed outline (absolute)."""
    n = len(points)
    if n < 3:
        return 0.0
    s = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(s) / 2


def perimeter(points: list[Point]) -> float:
    n = len(points)
    if n < 2:
        return 0.0
    return sum(math.dist(points[i], points[(i + 1) % n]) for i in range(n))


def _intersection(a: Segment, b: Segment) -> Point | None:
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _foot(p: Point, s: Segment) -> Point | None:
    """The foot of the perpendicular from p on the segment (None when it falls outside it)."""
    x1, y1, x2, y2 = s
    dx, dy = x2 - x1, y2 - y1
    ll = dx * dx + dy * dy
    if ll == 0:
        return None
    t = ((p[0] - x1) * dx + (p[1] - y1) * dy) / ll
    if t < 0 or t > 1:
        return None
    return (x1 + t * dx, y1 + t * dy)


def near(segments: list[Segment], p: Point, radius: float) -> list[Segment]:
    """The segments with a part within the radius of p (a box test, then the distance)."""
    out = []
    for s in segments:
        x1, y1, x2, y2 = s
        if min(x1, x2) - radius > p[0] or max(x1, x2) + radius < p[0]:
            continue
        if min(y1, y2) - radius > p[1] or max(y1, y2) + radius < p[1]:
            continue
        f = _foot(p, s)
        d = math.dist(p, f) if f else min(math.dist(p, (x1, y1)), math.dist(p, (x2, y2)))
        if d <= radius:
            out.append(s)
    return out


@dataclass
class Snap:
    point: Point
    kind: str  # end, intersection, perpendicular, none


def snap(p: Point, segments: list[Segment], radius: float, previous: Point | None = None) -> Snap:
    """The point the click means: the nearest end point, else intersection, else the foot of
    the perpendicular from the previous corner onto a nearby wall, within the radius."""
    close = near(segments, p, radius)
    best: tuple[float, Snap] | None = None
    for s in close:
        for e in ((s[0], s[1]), (s[2], s[3])):
            d = math.dist(p, e)
            if d <= radius and (best is None or d < best[0]):
                best = (d, Snap(e, "end"))
    if best:
        return best[1]
    for i, a in enumerate(close):
        for b in close[i + 1 :]:
            x = _intersection(a, b)
            if x is not None:
                d = math.dist(p, x)
                if d <= radius and (best is None or d < best[0]):
                    best = (d, Snap(x, "intersection"))
    if best:
        return best[1]
    if previous is not None:
        for s in close:
            f = _foot(previous, s)
            if (
                f is not None
                and math.dist(p, f) <= radius
                and (best is None or math.dist(p, f) < best[0])
            ):
                best = (math.dist(p, f), Snap(f, "perpendicular"))
        if best:
            return best[1]
    return Snap(p, "none")


def _ray(p: Point, dx: float, dy: float, segments: list[Segment], reach: float) -> float | None:
    """How far a ray from p goes before it meets a wall line."""
    far = (p[0] + dx * reach, p[1] + dy * reach)
    ray = (p[0], p[1], far[0], far[1])
    best = None
    for s in segments:
        x = _intersection(ray, s)
        if x is not None:
            d = math.dist(p, x)
            if d > 1e-9 and (best is None or d < best):
                best = d
    return best


def propose(p: Point, segments: list[Segment], reach: float) -> list[Point] | None:
    """For a click inside a room: the rectangle up to the nearest wall in each of the four
    directions (None when a direction meets no wall within the reach)."""
    right = _ray(p, 1, 0, segments, reach)
    left = _ray(p, -1, 0, segments, reach)
    up = _ray(p, 0, 1, segments, reach)
    down = _ray(p, 0, -1, segments, reach)
    if None in (right, left, up, down):
        return None
    x0, x1, y0, y1 = p[0] - left, p[0] + right, p[1] - down, p[1] + up
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def diff_percent(a: float | None, b: float | None) -> float | None:
    """How far b is from a, in percent of a."""
    if not a or b is None:
        return None
    return abs(b - a) / a * 100
