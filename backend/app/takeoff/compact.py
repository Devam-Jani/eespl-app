# ruff: noqa: E501
"""The drawing as the browser gets it (version 2), and the grid index snap and propose use.

Version 2 is what the viewer draws and nothing else: the layers the mapping hides (furniture,
hatch, electrical, ...) are left out on the server; coordinates are whole steps of 1 mm from the
drawing's corner; the lines that touch end to end are chained into polylines, each written as its
first point and then the steps to the next ones. {v: 2, unit_m, extents, origin, q, layers:
[{name, color, role}], g: {layer: [[x0, y0, dx1, dy1, ...], ...]}, t: [[x, y, h, layer, text]]}.
A coordinate is origin + value * q (q: drawing units per mm)."""

import gzip
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def quantum(unit_m: float | None) -> float:
    """Drawing units in 1 mm (a drawing in mm: 1; in inches: 1/25.4; in metres: 0.001)."""
    return 0.001 / (unit_m or 0.001)


def chain(segs: list[tuple[int, int, int, int]]) -> list[list[int]]:
    """Segments (integer ends) chained into polylines where they meet end to end."""
    by_end: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x1, y1, x2, y2) in enumerate(segs):
        by_end[(x1, y1)].append(i)
        by_end[(x2, y2)].append(i)
    used = bytearray(len(segs))
    out: list[list[int]] = []

    def take(at: tuple[int, int]) -> tuple[int, int] | None:
        for j in by_end.get(at, ()):
            if not used[j]:
                used[j] = 1
                x1, y1, x2, y2 = segs[j]
                return (x2, y2) if (x1, y1) == at else (x1, y1)
        return None

    for i, (x1, y1, x2, y2) in enumerate(segs):
        if used[i]:
            continue
        used[i] = 1
        pts = [(x1, y1), (x2, y2)]
        while (nxt := take(pts[-1])) is not None:
            pts.append(nxt)
        back = []
        while (prv := take(pts[0] if not back else back[-1])) is not None:
            back.append(prv)
        pts = back[::-1] + pts
        flat = [pts[0][0], pts[0][1]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            flat += [bx - ax, by - ay]
        out.append(flat)
    return out


def encode(geo: dict, hidden: set[str], roles: dict[str, str], layer_info: list[dict]) -> dict:
    unit = geo.get("unit_m") or 0.001
    q = quantum(unit)
    ext = geo.get("extents") or [0, 0, 0, 0]
    ox, oy = math.floor(ext[0]), math.floor(ext[1])
    g: dict[str, list[list[int]]] = {}
    for layer, data in (geo.get("geometry") or {}).items():
        if layer in hidden:
            continue
        s = data.get("s", [])
        segs = []
        for i in range(0, len(s) - 3, 4):
            a = (round((s[i] - ox) / q), round((s[i + 1] - oy) / q), round((s[i + 2] - ox) / q), round((s[i + 3] - oy) / q))
            if a[0] != a[2] or a[1] != a[3]:  # a line shorter than a mm draws nothing
                segs.append(a)
        if segs:
            g[layer] = chain(segs)
    texts = [[round((t[0] - ox) / q), round((t[1] - oy) / q), round((t[2] or 0) / q), t[3], t[4]] for t in geo.get("texts") or [] if t[3] not in hidden and not (len(t) > 5 and t[5])]
    layers = [{"name": ly["name"], "color": ly.get("color", 7), "role": roles.get(ly["name"])} for ly in layer_info if ly.get("name") in g]
    return {"v": 2, "unit_m": unit, "extents": ext, "origin": [ox, oy], "q": q, "layers": layers, "g": g, "t": texts}


def etag(revision_id: int, geometry: Path, roles: dict[str, str]) -> str:
    """Changes with the revision, its geometry file and the layer mapping."""
    st = geometry.stat()
    key = json.dumps([revision_id, st.st_mtime_ns, st.st_size, sorted(roles.items())])
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def cached(geometry: Path, tag: str, build) -> bytes:
    """The encoded drawing (gzip JSON), made once per ETag and kept beside the geometry file."""
    out = geometry.with_name(f"{geometry.name.split('.')[0]}.v2.{tag}.json.gz")
    if not out.exists():
        for old in geometry.parent.glob(f"{geometry.name.split('.')[0]}.v2.*.json.gz"):
            old.unlink(missing_ok=True)
        data = gzip.compress(json.dumps(build(), separators=(",", ":")).encode(), compresslevel=6)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
    return out.read_bytes()


# --- the grid index (snap and propose) ----------------------------------------------------------


class GridIndex:
    """Segments in square cells: a click looks only in the cells around it, a ray only in the
    cells along it (instead of every segment of the drawing)."""

    def __init__(self, segments: list[tuple], cells: int = 256):
        self.segments = segments
        self.cells = cells
        if not segments:
            self.x0 = self.y0 = 0.0
            self.size = 1.0
            self.grid: dict[tuple[int, int], list[int]] = {}
            return
        xs = [v for s in segments for v in (s[0], s[2])]
        ys = [v for s in segments for v in (s[1], s[3])]
        self.x0, self.y0 = min(xs), min(ys)
        span = max(max(xs) - self.x0, max(ys) - self.y0, 1e-9)
        self.size = span / cells
        grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (x1, y1, x2, y2) in enumerate(segments):
            for cx in range(self._c(min(x1, x2), self.x0), self._c(max(x1, x2), self.x0) + 1):
                for cy in range(self._c(min(y1, y2), self.y0), self._c(max(y1, y2), self.y0) + 1):
                    grid[(cx, cy)].append(i)
        self.grid = dict(grid)

    def _c(self, v: float, o: float) -> int:
        """The cell of a coordinate, kept to the grid (a ray of any reach stops at its edge)."""
        return min(max(int((v - o) // self.size), -1), self.cells + 1)

    def box(self, x1: float, y1: float, x2: float, y2: float) -> list[tuple]:
        """The segments in the cells the box touches (each once)."""
        seen: set[int] = set()
        for cx in range(self._c(x1, self.x0), self._c(x2, self.x0) + 1):
            for cy in range(self._c(y1, self.y0), self._c(y2, self.y0) + 1):
                seen.update(self.grid.get((cx, cy), ()))
        return [self.segments[i] for i in sorted(seen)]  # in the drawing's order: ties fall as before
