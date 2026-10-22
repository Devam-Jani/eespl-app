# ruff: noqa: E501
"""Speed: a drawing is read by the worker (the API only queues it and stays quick), the building
page shows an unread drawing's state, the browser gets only the shown layers (with an ETag that
follows the revision and the mapping), and snap / propose give the same points with the grid
index as without it. Invented drawings only."""

import multiprocessing
import random
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.building.models import BuildingModel
from app.main import app
from app.sites.models import Drawing, DrawingRevision, Site, SiteMember
from app.takeoff import compact, geometry, pipeline
from app.takeoff.models import CadFile, CadLayerMap
from tests.conftest import login
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_portal import media  # noqa: F401  (fixture)

ARCHITECT = "Invented architect"


def _dxf(path: Path, lines: int = 40) -> None:
    import ezdxf

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    for layer in ("wall", "fur"):
        doc.layers.add(layer)
    for i in range(lines):
        msp.add_line((0, i * 100), (5000, i * 100), dxfattribs={"layer": "wall"})
    msp.add_line((0, 0), (0, (lines - 1) * 100), dxfattribs={"layer": "wall"})
    msp.add_line((100, 100), (900, 900), dxfattribs={"layer": "fur"})  # a sofa: never sent
    msp.add_text("TOILET 6'X8'", dxfattribs={"layer": "wall", "height": 120, "insert": (1200, 1200)})
    msp.add_text("SOFA", dxfattribs={"layer": "fur", "height": 120, "insert": (300, 300)})
    doc.saveas(path)


@pytest.fixture
def drawing_site(db, media):  # noqa: F811
    site = Site(code="S-SP-9001", name="Invented site", status="active")
    db.add(site)
    db.flush()
    d = Drawing(site_id=site.id, title="Invented plan", discipline="architectural")
    db.add(d)
    db.flush()
    rel = "d/plan-r0.dxf"
    (Path(media) / "d").mkdir(parents=True, exist_ok=True)
    _dxf(Path(media) / rel)
    r = DrawingRevision(drawing_id=d.id, rev_no=0, stored_path=rel, filename="plan-r0.dxf", size_bytes=1)
    db.add(r)
    db.add(CadLayerMap(architect=ARCHITECT, roles={"wall": "walls", "fur": "hide"}))
    db.commit()
    return {"site": site, "drawing": d, "revision": r}


def _read(client, h, revision_id: int) -> dict:
    r = client.post(f"/api/takeoff/revisions/{revision_id}/read", json={"architect": ARCHITECT}, headers=h)
    assert r.status_code == 202, r.text
    return r.json()


def test_reading_a_drawing_is_a_worker_job_with_its_stage(boss, drawing_site, db):  # noqa: F811
    client, h = boss
    f = _read(client, h, drawing_site["revision"].id)
    assert f["status"] == "queued" and f["progress"] == "queued"  # the API only queued it
    seen = []
    real = pipeline._stage
    pipeline._stage = lambda db_, f_, stage: (seen.append(stage), real(db_, f_, stage))
    try:
        pipeline.sweep()  # the worker's job
    finally:
        pipeline._stage = real
    after = client.get(f"/api/takeoff/files/{f['id']}", headers=h).json()
    assert after["status"] == "ready" and after["progress"] == "done"
    assert seen == ["converting", "finding areas"]  # a DXF needs no conversion: the reading follows it


def _worker_read(revision_id: int) -> None:
    from app.db import SessionLocal, engine

    engine.dispose(close=False)  # a forked process: its own connections, not the parent's

    with SessionLocal() as db:
        f = db.query(CadFile).filter(CadFile.revision_id == revision_id).one()
        pipeline.process(db, f)


def test_the_api_answers_in_under_a_second_while_a_big_drawing_is_read(boss, drawing_site, db, media):  # noqa: F811
    client, h = boss
    big = Path(media) / "d/big.dxf"
    _dxf(big, lines=120_000)  # a large drawing (several seconds to read)
    r = DrawingRevision(drawing_id=drawing_site["drawing"].id, rev_no=1, stored_path="d/big.dxf", filename="big.dxf", size_bytes=big.stat().st_size)
    db.add(r)
    db.commit()
    _read(client, h, r.id)
    worker = multiprocessing.get_context("fork").Process(target=_worker_read, args=(r.id,))
    worker.start()
    try:
        time.sleep(0.5)
        assert worker.is_alive()  # still reading
        for path in ("/api/sites", f"/api/sites/{drawing_site['site'].id}", "/api/takeoff/area-types"):
            t0 = time.perf_counter()
            assert client.get(path, headers=h).status_code == 200
            assert time.perf_counter() - t0 < 1.0, path
    finally:
        worker.join(120)
    db.expire_all()
    assert db.query(CadFile).filter(CadFile.revision_id == r.id).one().status == "ready"


def test_the_building_page_shows_an_unread_drawing_and_who_may_read_it(drawing_site, db, make_user):
    s = drawing_site["site"]
    billing = make_user("billing-sp@example.com", "billing")
    sales = make_user("sales-sp@example.com", "sales")
    db.add(SiteMember(site_id=s.id, user_id=sales.id, role_on_site="sales"))
    db.commit()
    c = TestClient(app)
    out = c.get(f"/api/sites/{s.id}/building", headers=login(c, billing.email)).json()
    (rev,) = out["revisions"]
    assert rev["state"] == "not read" and out["can_read"] is True and out["drawings"] == []
    c2 = TestClient(app)
    assert c2.get(f"/api/sites/{s.id}/building", headers=login(c2, sales.email)).json()["can_read"] is False
    # read, then its lines gone from the server: "missing", with the button again (not a loader)
    f = CadFile(revision_id=rev["revision_id"], drawing_id=drawing_site["drawing"].id, site_id=s.id, status="ready", geometry_path="d/gone.geometry.json.gz", unit_m=0.001)
    db.add(f)
    db.flush()
    db.add(BuildingModel(site_id=s.id, version=1, cad_file_id=f.id, data={"floor_types": [], "floors": []}))
    db.commit()
    out = c.get(f"/api/sites/{s.id}/building", headers=login(c, billing.email)).json()
    assert out["model_drawing"]["state"] == "missing" and out["revisions"][0]["state"] == "missing"
    assert c.get(f"/api/takeoff/files/{f.id}/geometry", headers=login(c, billing.email)).status_code == 409


def test_hidden_layers_are_not_sent_and_the_etag_follows_revision_and_mapping(boss, drawing_site, db):  # noqa: F811
    client, h = boss
    f = _read(client, h, drawing_site["revision"].id)
    pipeline.sweep()
    r = client.get(f"/api/takeoff/files/{f['id']}/geometry", headers=h)
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    body = r.json()
    assert body["v"] == 2 and "fur" not in body["g"] and "wall" in body["g"]
    assert all(t[3] != "fur" for t in body["t"]) and any(t[4].startswith("TOILET") for t in body["t"])
    assert all(isinstance(v, int) for pl in body["g"]["wall"] for v in pl)  # 1 mm steps
    tag = r.headers["etag"]
    assert client.get(f"/api/takeoff/files/{f['id']}/geometry", headers={**h, "If-None-Match": tag}).status_code == 304
    # the mapping changes (the walls hidden too): a new ETag, and they are left out
    m = db.query(CadLayerMap).filter(CadLayerMap.architect == ARCHITECT).one()
    m.roles = {"wall": "hide", "fur": "hide"}
    db.commit()
    r2 = client.get(f"/api/takeoff/files/{f['id']}/geometry", headers={**h, "If-None-Match": tag})
    assert r2.status_code == 200 and r2.headers["etag"] != tag and r2.json()["g"] == {}
    # a new revision of the same drawing: another ETag
    geo_path = pipeline.media(db.get(CadFile, f["id"]).geometry_path)
    assert compact.etag(f["revision_id"] + 1, geo_path, m.roles) != r2.headers["etag"].strip('"')


def test_polylines_decode_back_to_the_same_lines():
    segs = [(0, 0, 10, 0), (10, 0, 10, 5), (10, 5, 0, 5), (20, 20, 25, 20)]  # an open U and a loose line
    pls = compact.chain(segs)
    back = set()
    for pl in pls:
        x, y = pl[0], pl[1]
        for i in range(2, len(pl), 2):
            nx, ny = x + pl[i], y + pl[i + 1]
            back.add(tuple(sorted([(x, y), (nx, ny)])))
            x, y = nx, ny
    assert back == {tuple(sorted([(a, b), (c, d)])) for a, b, c, d in segs} and len(pls) == 2


def test_snap_and_propose_with_the_grid_index_give_the_same_points_as_before():
    rnd = random.Random(11)
    segs = []
    for _ in range(3000):  # walls of rooms, door gaps and loose lines
        x, y = rnd.uniform(0, 50_000), rnd.uniform(0, 30_000)
        if rnd.random() < 0.5:
            segs.append((x, y, x + rnd.uniform(200, 6000), y))
        else:
            segs.append((x, y, x, y + rnd.uniform(200, 6000)))
    idx = compact.GridIndex(segs)
    for _ in range(400):
        p = (rnd.uniform(0, 50_000), rnd.uniform(0, 30_000))
        prev = (p[0] + rnd.uniform(-900, 900), p[1] + rnd.uniform(-900, 900)) if rnd.random() < 0.5 else None
        for radius in (150, 600):
            a = geometry.snap(p, segs, radius, prev)
            b = geometry.snap(p, segs, radius, prev, index=idx)
            assert (a.kind, a.point) == (b.kind, b.point)
        assert geometry.propose(p, segs, 30_000) == geometry.propose(p, segs, 30_000, index=idx)
