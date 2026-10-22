# ruff: noqa: E501
"""What the building model reads from the drawing by itself, as pure functions (tested without a
database): level texts and the storey heights they give, the floors a plan title names, column
rectangles, an outline proposed from the walls, and how two plans line up (by their columns).
Coordinates are drawing units unless a name says _m."""

import math
import re
from collections import defaultdict
from statistics import median

FOOT_M, INCH_M = 0.3048, 0.0254

# +3.000, + 3.000 FFL, SSL +6.000, LVL +58'9", LVL+19'9", -1.500, ±0.000, +0'0"
LEVEL = re.compile(
    r"(?:(?:LVL|LEVEL|FFL|SSL|TOS|TOC|EL)\.?\s*)?(?P<sign>[+\-±])\s*(?:(?P<ft>\d{1,3})\s*'\s*(?P<in>\d{1,2}(?:\.\d+)?)?\s*(?:\"|'')?|(?P<m>\d{1,3}\.\d{2,3})\b)",
    re.IGNORECASE,
)
LEVEL_WORD = re.compile(r"\b(LVL|LEVEL|FFL|SSL|TOS|TOC|EL)\b", re.IGNORECASE)
ORDINAL = {"GROUND": 0, "G": 0, "STILT": 0, "PODIUM": 0, "PLINTH": 0}
WORD_NUM = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10}


def level_m(text: str) -> float | None:
    """A level text in metres: '+3.000' 3.0, 'LVL +58'9"' 17.907, '-1.500' -1.5; a metric value
    needs a sign or a level word (a plain 3.000 is a size, not a level)."""
    t = (text or "").replace("\n", " ")
    m = LEVEL.search(t)
    if not m:
        return None
    sign = -1 if m.group("sign") == "-" else 1
    if m.group("m"):
        return sign * float(m.group("m"))
    return sign * (int(m.group("ft")) * FOOT_M + float(m.group("in") or 0) * INCH_M)


def levels(texts: list[list], unit_m: float) -> dict:
    """The storey levels from a section: the level texts that stand in one column (the same x
    within 2 m), the column with the most distinct levels wins. With a ±0 level in it, each level
    is a floor; otherwise the usual step between levels is the floor-to-floor height.
    Returns {source: section|default, values_m, floor_height_m, note}."""
    found = []
    for t in texts:
        if len(t) > 5 and t[5]:  # inside a block: a symbol, not a level
            continue
        v = level_m(str(t[4]))
        if v is not None and (LEVEL_WORD.search(str(t[4])) or re.match(r"\s*[+\-±]", str(t[4]))):
            found.append((float(t[0]), v))
    tol = 2.0 / unit_m if unit_m else 80.0
    columns: dict[int, set[float]] = defaultdict(set)
    for x, v in found:
        columns[round(x / tol)].add(round(v, 3))
    best = max(columns.values(), key=len, default=set())
    if len(best) < 3:
        return {"source": "default", "values_m": [], "floor_height_m": None, "note": "No section with level texts (+3.000, FFL, SSL, LVL): the defaults are used."}
    values = sorted(best)
    steps = [round(b - a, 3) for a, b in zip(values, values[1:], strict=False) if b - a > 2.0]  # storeys, not slab/finish pairs
    height = round(median(steps), 3) if steps else None
    ground = any(abs(v) < 0.01 for v in values)
    note = f"Read from the section: {len(values)} levels from {values[0]:+.3f} to {values[-1]:+.3f} m"
    note += f", floor to floor {height:.3f} m" if height else ""
    return {"source": "section", "values_m": values, "floor_height_m": height, "from_ground": ground, "note": note + "."}


def floors_in_title(title: str) -> list[int]:
    """'2ND,3RD,5TH ,6TH,8TH & 9TH FLOOR WORKING PLAN' [2, 3, 5, 6, 8, 9]; 'FLOOR 3 TO 12 PLAN'
    3..12; 'GROUND FLOOR PLAN' [0]; 'TYPICAL FLOOR PLAN' [] (the user says which floors)."""
    t = (title or "").upper()
    out: set[int] = set()
    for a, b in re.findall(r"(\d{1,2})(?:ST|ND|RD|TH)?\s*(?:TO|-|–)\s*(\d{1,2})(?:ST|ND|RD|TH)?", t):
        out.update(range(int(a), int(b) + 1))
    out.update(int(n) for n in re.findall(r"\b(\d{1,2})(?:ST|ND|RD|TH)\b", t))
    out.update(int(n) for n in re.findall(r"FLOOR\s+(\d{1,2})\b", t))
    for word, n in {**ORDINAL, **WORD_NUM}.items():
        if re.search(rf"\b{word}\b", t) and (word != "G" or "G+" not in t):
            out.add(n)
    return sorted(out)


def shapes(segments: list[float]) -> list[tuple[float, float, float, float]]:
    """The closed shapes drawn on a layer, as the boxes (x1, y1, x2, y2) of the groups of lines
    that touch end to end: a column drawn as four lines, as a polyline, or as a symbol with a
    cross or a hatch outline inside comes out as one box."""
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def root(a: tuple[int, int]) -> tuple[int, int]:
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def key(x: float, y: float) -> tuple[int, int]:
        return (round(x * 10), round(y * 10))

    segs = [segments[i:i + 4] for i in range(0, len(segments) - 3, 4)]
    for x1, y1, x2, y2 in segs:
        parent[root(key(x1, y1))] = root(key(x2, y2))
    box: dict[tuple[int, int], list[float]] = {}
    for x1, y1, x2, y2 in segs:
        r = root(key(x1, y1))
        b = box.get(r)
        box[r] = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)] if b is None else [min(b[0], x1, x2), min(b[1], y1, y2), max(b[2], x1, x2), max(b[3], y1, y2)]
    return [tuple(b) for b in box.values()]  # type: ignore[misc]


def inside(x: float, y: float, poly: list[list[float]]) -> bool:
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def columns(rects: list[tuple[float, float, float, float]], outline: list[list[float]], unit_m: float,
            low_m: float = 0.2, high_m: float = 0.9, margin_m: float = 0.5) -> list[list[float]]:
    """The column-sized shapes (each side low_m to high_m, 200 to 900 mm unless the site's
    setting says otherwise) inside the floor outline (or within margin of it): [[cx, cy, w, d]]
    in drawing units, one per position."""
    lo, hi = low_m / unit_m, high_m / unit_m
    grown = _grow(outline, margin_m / unit_m)
    out: list[list[float]] = []
    for x1, y1, x2, y2 in rects:
        w, d = x2 - x1, y2 - y1
        if not (lo <= w <= hi and lo <= d <= hi):
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if not inside(cx, cy, grown):
            continue
        if any(abs(c[0] - cx) < lo / 2 and abs(c[1] - cy) < lo / 2 for c in out):
            continue  # the same column drawn twice (outline and fill)
        out.append([round(float(cx), 3), round(float(cy), 3), round(float(w), 3), round(float(d), 3)])
    return out


def _grow(poly: list[list[float]], by: float) -> list[list[float]]:
    """The outline pushed out from its centre by `by` (enough for "near the outline")."""
    if not poly:
        return poly
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    out = []
    for x, y in poly:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy) or 1
        out.append([x + dx / n * by * 1.5, y + dy / n * by * 1.5])
    return out


def _spread(grid: bytearray, nx: int, ny: int, r: int, on) -> bytearray:
    """The cells within r steps (4-neighbour) of a set cell, set too (a dilation)."""
    out = bytearray(grid)
    front = [i for i, v in enumerate(grid) if on(v)]
    for _ in range(r):
        nxt = []
        for c in front:
            gx, gy = c % nx, c // nx
            for bx, by in ((gx + 1, gy), (gx - 1, gy), (gx, gy + 1), (gx, gy - 1)):
                if 0 <= bx < nx and 0 <= by < ny and not out[by * nx + bx]:
                    out[by * nx + bx] = 1
                    nxt.append(by * nx + bx)
        front = nxt
    return out


def outline_from_walls(segments: list[float], region: list[float], unit_m: float, cell_m: float = 0.25, close_m: float = 0.75) -> list[list[float]]:
    """A proposal for the outer outline: the wall lines inside region [x1, y1, x2, y2] drawn on a
    grid, the outside flooded from the border, the edge between outside and the rest followed
    and straightened. The user corrects it with the snapping tracer."""
    x0, y0, x1, y1 = region
    cell = cell_m / unit_m
    nx, ny = max(1, int((x1 - x0) / cell) + 3), max(1, int((y1 - y0) / cell) + 3)
    if nx * ny > 4_000_000:
        return []
    wall = bytearray(nx * ny)
    for i in range(0, len(segments) - 3, 4):
        ax, ay, bx, by = segments[i:i + 4]
        if not (x0 <= ax <= x1 and y0 <= ay <= y1 and x0 <= bx <= x1 and y0 <= by <= y1):
            continue
        steps = max(1, int(math.hypot(bx - ax, by - ay) / (cell / 2)))
        for k in range(steps + 1):
            px, py = ax + (bx - ax) * k / steps, ay + (by - ay) * k / steps
            gx, gy = int((px - x0) / cell) + 1, int((py - y0) / cell) + 1
            wall[gy * nx + gx] = 1
    r = max(1, round(close_m / cell_m))  # doors and windows: gaps closed for the flood
    wall = _spread(wall, nx, ny, r, lambda v: v == 1)
    out = bytearray(nx * ny)  # flood the outside from the border
    stack = [0]
    out[0] = 1
    while stack:
        c = stack.pop()
        gx, gy = c % nx, c // nx
        for nb in ((gx + 1, gy), (gx - 1, gy), (gx, gy + 1), (gx, gy - 1)):
            if 0 <= nb[0] < nx and 0 <= nb[1] < ny:
                j = nb[1] * nx + nb[0]
                if not out[j] and not wall[j]:
                    out[j] = 1
                    stack.append(j)
    out = _spread(out, nx, ny, r, lambda v: v == 1)  # back in by what the walls grew
    # the boundary edges between outside and inside cells, chained into loops (inside on the left)
    nxt: dict[tuple[int, int], tuple[int, int]] = {}
    for gy in range(ny):
        for gx in range(nx):
            if out[gy * nx + gx]:
                continue
            if gy == 0 or out[(gy - 1) * nx + gx]:
                nxt[(gx, gy)] = (gx + 1, gy)
            if gx == nx - 1 or out[gy * nx + gx + 1]:
                nxt[(gx + 1, gy)] = (gx + 1, gy + 1)
            if gy == ny - 1 or out[(gy + 1) * nx + gx]:
                nxt[(gx + 1, gy + 1)] = (gx, gy + 1)
            if gx == 0 or out[gy * nx + gx - 1]:
                nxt[(gx, gy + 1)] = (gx, gy)
    best: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for start in list(nxt):
        if start in seen:
            continue
        loop, p = [], start
        while p not in seen and p in nxt:
            seen.add(p)
            loop.append(p)
            p = nxt[p]
        if len(loop) > len(best):
            best = loop
    corners = [p for i, p in enumerate(best) if _turns(best[i - 1], p, best[(i + 1) % len(best)])]
    pts = [[x0 + (gx - 1) * cell, y0 + (gy - 1) * cell] for gx, gy in corners]
    return simplify(pts, 0.4 / unit_m)


def _turns(a, b, c) -> bool:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0


def simplify(poly: list[list[float]], step: float) -> list[list[float]]:
    """The grid's stair-steps smoothed away (Ramer-Douglas-Peucker on the closed loop, tolerance
    `step`), then the edges that are nearly level or plumb made exactly so."""
    if len(poly) < 4:
        return poly

    def rdp(pts: list[list[float]]) -> list[list[float]]:
        (ax, ay), (bx, by) = pts[0], pts[-1]
        n = math.hypot(bx - ax, by - ay) or 1e-9
        far, k = 0.0, 0
        for i in range(1, len(pts) - 1):
            d = abs((bx - ax) * (ay - pts[i][1]) - (ax - pts[i][0]) * (by - ay)) / n
            if d > far:
                far, k = d, i
        if far <= step:
            return [pts[0], pts[-1]]
        return rdp(pts[: k + 1])[:-1] + rdp(pts[k:])

    # split the loop at its two farthest-apart corners so RDP has fixed ends
    a = 0
    b = max(range(len(poly)), key=lambda i: math.hypot(poly[i][0] - poly[0][0], poly[i][1] - poly[0][1]))
    loop = rdp(poly[a: b + 1])[:-1] + rdp(poly[b:] + [poly[0]])[:-1]
    out = [p[:] for p in loop]
    for i in range(len(out)):  # square it up
        p, q = out[i], out[(i + 1) % len(out)]
        dx, dy = q[0] - p[0], q[1] - p[1]
        if abs(dx) < abs(dy) * 0.15:
            q[0] = p[0]
        elif abs(dy) < abs(dx) * 0.15:
            q[1] = p[1]
    return [[round(x, 2), round(y, 2)] for x, y in out]


def align(reference: list[list[float]], other: list[list[float]], tol: float) -> tuple[float, float, int]:
    """The shift that lays `other`'s columns on `reference`'s (plans drawn in different places on
    the sheet): the translation that matches the most columns within tol. (dx, dy, matches)."""
    best = (0.0, 0.0, 0)
    if not reference or not other:
        return best
    for c in other[:12]:
        for r in reference:
            dx, dy = r[0] - c[0], r[1] - c[1]
            n = sum(1 for o in other if any(abs(o[0] + dx - q[0]) < tol and abs(o[1] + dy - q[1]) < tol for q in reference))
            if n > best[2]:
                best = (dx, dy, n)
    return best


def area(poly: list[list[float]]) -> float:
    """Shoelace area (in the square of the coordinates' unit)."""
    return abs(sum(poly[i - 1][0] * p[1] - p[0] * poly[i - 1][1] for i, p in enumerate(poly))) / 2
