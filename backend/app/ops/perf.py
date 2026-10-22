# ruff: noqa: E501, PLC0415
"""Timings of the drawing and the building, the same steps before and after a change:

    python -m app.ops.perf drawing "/data/samples/dwg/<file>.dwg"   # read: DWG to DXF, parse, geometry, areas
    python -m app.ops.perf served <cad_file_id>                       # the geometry sent, a snap and a propose click

Read-only on the database (the reading runs on a copy in /tmp, nothing is saved)."""

import gzip
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path


def _t(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return out, round(time.perf_counter() - t0, 3)


def drawing(path: str) -> dict:
    from app.takeoff import dwg, reader, service

    src = Path(path)
    out: dict = {"file": src.name, "dwg_mb": round(src.stat().st_size / 1e6, 2)}
    with tempfile.TemporaryDirectory() as tmp:
        dxf = Path(tmp) / "d.dxf"
        _, out["dwg_to_dxf_s"] = _t(dwg.to_dxf, src, dxf)
        parsed, out["parse_s"] = _t(reader.read, dxf)
        geo = Path(tmp) / "d.geometry.json.gz"
        _, out["geometry_s"] = _t(reader.write_geometry, parsed, geo)
        out["geometry_gz_kb"] = round(geo.stat().st_size / 1024)
        with gzip.open(geo, "rb") as fh:
            out["geometry_json_kb"] = round(len(fh.read()) / 1024)
        out["segments"] = sum(len(g["s"]) // 4 for g in parsed.geometry.values())
        _, out["areas_s"] = _t(service.find_areas, parsed.texts, parsed.unit_m, set(), 6.0, parsed.frames, parsed.clusters)
    out["total_s"] = round(out["dwg_to_dxf_s"] + out["parse_s"] + out["geometry_s"] + out["areas_s"], 3)
    return out


def served(cad_file_id: int, clicks: int = 20) -> dict:
    """What the browser gets for a read drawing, and how long a snap and a propose take through
    the API (as the DEMO director: the same path a click takes)."""
    from fastapi.testclient import TestClient

    import app.main as main
    from app.closeout.demo import _login
    from app.db import SessionLocal
    from app.takeoff.models import CadFile
    from app.team.demo import email_for

    c = TestClient(main.app)
    h = _login(c, email_for("director"))
    with SessionLocal() as db:
        f = db.get(CadFile, cad_file_id)
        ext = (f.summary or {}).get("extents") or [0, 0, 1000, 1000]
        unit = f.unit_m or 0.001
    t0 = time.perf_counter()
    r = c.get(f"/api/takeoff/files/{cad_file_id}/geometry", headers=h)
    out: dict = {"cad_file_id": cad_file_id, "geometry_status": r.status_code, "geometry_get_s": round(time.perf_counter() - t0, 3)}
    out["geometry_sent_kb"] = round(len(r.content) / 1024)  # as it travels (gzip unless said otherwise)
    raw = r.content
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    out["geometry_unpacked_kb"] = round(len(raw) / 1024)
    try:
        g = json.loads(raw)
        if g.get("v") == 2:  # polylines: [x0, y0, dx1, dy1, ...] -> points - 1 lines each
            out["layers_sent"] = len(g["g"])
            out["segments_sent"] = sum(len(pl) // 2 - 1 for v in g["g"].values() for pl in v)
            out["polylines_sent"] = sum(len(v) for v in g["g"].values())
        else:
            out["layers_sent"] = len(g.get("geometry", {}))
            out["segments_sent"] = sum(len(v.get("s", [])) // 4 for v in g.get("geometry", {}).values())
    except ValueError:
        out["layers_sent"] = out["segments_sent"] = None
    t0 = time.perf_counter()
    r2 = c.get(f"/api/takeoff/files/{cad_file_id}/geometry", headers=h)
    out["geometry_get_again_s"] = round(time.perf_counter() - t0, 3)
    out["geometry_etag_304"] = c.get(f"/api/takeoff/files/{cad_file_id}/geometry", headers={**h, "If-None-Match": r2.headers.get("etag", "")}).status_code
    rnd = random.Random(7)
    pts = [(rnd.uniform(ext[0], ext[2]), rnd.uniform(ext[1], ext[3])) for _ in range(clicks)]
    radius = 0.3 / unit
    snaps, props = [], []
    c.post(f"/api/takeoff/files/{cad_file_id}/snap", json={"x": pts[0][0], "y": pts[0][1], "radius": radius}, headers=h)  # warm (the index / cache)
    for x, y in pts:
        t0 = time.perf_counter()
        c.post(f"/api/takeoff/files/{cad_file_id}/snap", json={"x": x, "y": y, "radius": radius, "previous": None}, headers=h)
        snaps.append(time.perf_counter() - t0)
    for x, y in pts[:10]:
        t0 = time.perf_counter()
        c.post(f"/api/takeoff/files/{cad_file_id}/propose", json={"x": x, "y": y}, headers=h)
        props.append(time.perf_counter() - t0)
    # the snap itself, without the request around it: every segment scanned, and the grid index
    from app.takeoff import compact, geometry, service
    from app.takeoff.reader import load_geometry

    with SessionLocal() as db:
        f = db.get(CadFile, cad_file_id)
        hidden, walls = service.hidden_layers(db, f), service.wall_layers(db, f)
        from app.takeoff import pipeline

        geo = load_geometry(pipeline.media(f.geometry_path))
    segs = [(s[i], s[i + 1], s[i + 2], s[i + 3]) for layer, g in geo["geometry"].items() if layer not in hidden and (not walls or layer in walls) for s in [g["s"]] for i in range(0, len(s), 4)]
    t0 = time.perf_counter()
    idx = compact.GridIndex(segs)
    out["index_build_ms"] = round((time.perf_counter() - t0) * 1000)
    for name, kw in (("scan", {}), ("index", {"index": idx})):
        t0 = time.perf_counter()
        for x, y in pts:
            geometry.snap((x, y), segs, radius, None, **kw)
        out[f"snap_fn_{name}_ms"] = round((time.perf_counter() - t0) * 1000 / len(pts), 2)
    out["snap_segments"] = len(segs)
    out["snap_ms_median"] = round(statistics.median(snaps) * 1000)
    out["snap_ms_max"] = round(max(snaps) * 1000)
    out["propose_ms_median"] = round(statistics.median(props) * 1000)
    out["propose_ms_max"] = round(max(props) * 1000)
    return out


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    print(json.dumps(drawing(arg) if cmd == "drawing" else served(int(arg)), indent=1))
