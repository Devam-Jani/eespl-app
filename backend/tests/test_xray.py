# ruff: noqa: E501
"""The X-ray 3D building: what is read from the drawing (levels, the floors a plan names, columns,
an outline from the walls), the model made from a drawing and moved onto its next revision, the
3D payload for staff and for the client, and who may build it. Invented drawings only."""

import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.building import detect, service
from app.building.models import BuildingModel
from app.main import app
from app.models import User
from app.sites.models import Drawing, DrawingRevision, Site, SiteMember, SiteNode
from app.takeoff.models import CadArea, CadFile
from tests.conftest import login
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_portal import FORBIDDEN, forbidden_keys, media, portal  # noqa: F401  (fixtures)

TITLE = "3RD TO 12TH FLOOR PLAN"
# an L: 20 x 10 m with an 8 x 6 m corner cut away (152 sqm), drawn in metres
L_SHAPE = [[10, 10], [30, 10], [30, 14], [22, 14], [22, 20], [10, 20]]
COLUMNS = [(11, 11), (29, 11), (11, 19)]


def _square(cx, cy, s=0.45):
    h = s / 2
    return [cx - h, cy - h, cx + h, cy - h, cx + h, cy - h, cx + h, cy + h, cx + h, cy + h, cx - h, cy + h, cx - h, cy + h, cx - h, cy - h]


def _walls(shift=(0, 0)):
    s = []
    for i, (x, y) in enumerate(L_SHAPE):
        x2, y2 = L_SHAPE[(i + 1) % len(L_SHAPE)]
        s += [x + shift[0], y + shift[1], x2 + shift[0], y2 + shift[1]]
    return s


def _texts(shift=(0, 0)):
    levels = [[60, 10 + i * 3, 0.3, "LVL", f"{'±' if v == 0 else '+'}{v:.3f}", False] for i, v in enumerate((0, 3, 6, 9))]
    return [[5 + shift[0], 5 + shift[1], 0.6, "TITLE", TITLE, False], *levels]


def _cad(db, media, site: Site, drawing: Drawing, rev_no: int, shift=(0, 0)) -> CadFile:  # noqa: F811
    r = DrawingRevision(drawing_id=drawing.id, rev_no=rev_no, stored_path=f"d/r{rev_no}.dwg", filename=f"r{rev_no}.dwg", size_bytes=1)
    db.add(r)
    db.flush()
    rel = f"d/r{rev_no}.geometry.json.gz"
    p = Path(media) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    geometry = {"wall": {"s": _walls(shift)}, "COLUMN": {"s": [v for cx, cy in COLUMNS for v in _square(cx + shift[0], cy + shift[1])]}}
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump({"extents": [0, 0, 100, 100], "unit_m": 1.0, "layers": [], "geometry": geometry, "texts": []}, fh)
    f = CadFile(revision_id=r.id, drawing_id=drawing.id, site_id=site.id, status="ready", unit_m=1.0, geometry_path=rel,
                summary={"frames": [[0 + shift[0], 0 + shift[1], 100 + shift[0], 100 + shift[1], "rectangle on P"]]}, texts=_texts(shift))  # fmt: skip
    db.add(f)
    db.flush()
    return f


@pytest.fixture
def building_site(db, media):  # noqa: F811
    site = Site(code="S-XR-9001", name="Invented tower", status="active")
    db.add(site)
    db.flush()
    tower = SiteNode(site_id=site.id, kind="tower", name="Tower")
    db.add(tower)
    db.flush()
    floors = {}
    for lv in range(3, 13):
        f = SiteNode(site_id=site.id, parent_id=tower.id, kind="floor", name=f"Floor {lv}", level_no=lv, sort_order=lv)
        db.add(f)
        db.flush()
        floors[lv] = f
    toilet = SiteNode(site_id=site.id, parent_id=floors[3].id, kind="toilet", name="Toilet 301")
    db.add(toilet)
    d = Drawing(site_id=site.id, title="Invented working drawings", discipline="architectural")
    db.add(d)
    db.flush()
    cad = _cad(db, media, site, d, 1)
    db.add(CadArea(cad_file_id=cad.id, key="toilet-301", name="TOILET", x=13, y=12.7, plan=TITLE, outline=[[12, 12], [14, 12], [14, 13.5], [12, 13.5]],
                   traced_area_sqm=3, sunk_m=0.2, node_id=toilet.id, status="mapped"))  # fmt: skip
    db.commit()
    return {"site": site, "drawing": d, "cad": cad, "floors": floors, "toilet": toilet}


# --- read from the drawing --------------------------------------------------------------------------


def test_level_texts_of_a_section_set_the_floor_heights_and_without_them_the_defaults_are_flagged():
    lv = detect.levels(_texts(), 1.0)
    assert lv["source"] == "section" and lv["floor_height_m"] == 3.0 and lv["from_ground"] is True
    assert lv["values_m"] == [0.0, 3.0, 6.0, 9.0]
    assert detect.level_m("LVL +58'9\"") == pytest.approx(17.907, abs=1e-3)  # feet and inches
    assert detect.level_m("FFL +3.000") == 3.0 and detect.level_m("-1.500") == -1.5
    none = detect.levels([[0, 0, 0.3, "TEXT", "TOILET 6'X8'", False]], 1.0)
    assert none["source"] == "default" and "defaults are used" in none["note"]
    # the floors from those levels: ±0 ground, one level per floor; 3 m above the last
    data = {"settings": {"plinth_m": 0.45, "floor_height_m": 3.2}, "levels": lv, "floors": [{"level": n, "type": "t"} for n in range(0, 6)]}
    el = {f["level"]: f for f in service.elevations(data)}
    assert el[1]["elevation_m"] == pytest.approx(3.0) and el[1]["level_source"] == "section" and el[2]["height_m"] == pytest.approx(3.0)
    assert el[4]["level_source"] == "default" and "no level on the section" in el[4]["level_flag"]
    assert el[4]["elevation_m"] - el[3]["elevation_m"] == pytest.approx(3.2)  # past the section: the setting
    default = {f["level"]: f for f in service.elevations({**data, "levels": none})}
    assert default[5]["elevation_m"] == pytest.approx(0.45 + 5 * 3.2)


def test_a_plan_title_names_its_floors_and_columns_and_the_outline_come_from_the_drawing():
    assert detect.floors_in_title("2ND,3RD,5TH ,6TH,8TH & 9TH FLOOR WORKING PLAN") == [2, 3, 5, 6, 8, 9]
    assert detect.floors_in_title(TITLE) == list(range(3, 13))
    assert detect.floors_in_title("GROUND FLOOR PLAN") == [0] and detect.floors_in_title("TYPICAL FLOOR PLAN") == []
    shapes = detect.shapes([v for cx, cy in COLUMNS for v in _square(cx, cy)] + _square(15, 15, 1.5))  # and a 1.5 m shaft
    cols = detect.columns(shapes, L_SHAPE, 1.0)
    assert sorted((c[0], c[1]) for c in cols) == sorted(COLUMNS)  # the shaft is not column-sized
    assert detect.columns(shapes, L_SHAPE, 1.0, high_m=2.0) != cols  # the size limit is a setting
    ol = detect.outline_from_walls(_walls(), [0, 0, 40, 30], 1.0, cell_m=0.1, close_m=0.3)
    assert detect.area(ol) == pytest.approx(152, rel=0.06)  # the L, not its 200 sqm box


# --- the model --------------------------------------------------------------------------------------


def test_the_model_from_a_drawing_repeats_the_typical_floor_on_floors_3_to_12_with_its_rooms(boss, building_site):  # noqa: F811
    client, h = boss
    s = building_site["site"]
    out = client.post(f"/api/sites/{s.id}/building/from-drawing", json={"cad_file_id": building_site["cad"].id}, headers=h)
    assert out.status_code == 201, out.text
    data = out.json()["model"]["data"]
    t = next(t for t in data["floor_types"] if t["plan"] == TITLE)
    assert t["floors"] == list(range(3, 13)) and data["levels"]["source"] == "section" and data["settings"]["floor_height_m"] == 3.0
    t["outline"] = client.post(f"/api/sites/{s.id}/building/propose-outline", json={"key": t["key"]}, headers=h).json()["outline"]
    assert detect.area(t["outline"]) == pytest.approx(152, rel=0.12)
    t["outline"] = L_SHAPE  # traced exactly with the snapping
    cols = client.post(f"/api/sites/{s.id}/building/detect-columns", json={"key": t["key"], "outline": L_SHAPE}, headers=h).json()["columns"]
    assert len(cols) == 3
    t["columns"], t["columns_confirmed"] = cols, True
    t["cores"] = [{"kind": "stair", "outline": [[23, 15], [28, 15], [28, 17.4], [23, 17.4]], "risers": None}]
    assert client.put(f"/api/sites/{s.id}/building", json={"data": data}, headers=h).status_code == 200
    m = client.get(f"/api/sites/{s.id}/model", headers=h)
    b = m.json()["building"]
    assert len(b["floors"]) == 10 and [f["level"] for f in b["floors"]] == list(range(3, 13))
    heights = {f["level"]: f for f in b["floors"]}
    assert heights[3]["elevation_m"] == pytest.approx(9.0) and heights[12]["elevation_m"] - heights[11]["elevation_m"] == pytest.approx(3.0)
    (typ,) = b["types"].values()
    assert typ["area_sqm"] == pytest.approx(152) and len(typ["columns"]) == 3 and len(typ["cores"]) == 1
    (room,) = b["rooms"]
    assert room["level"] == 3 and room["sunk_m"] == pytest.approx(0.2) and room["name"] == "Toilet 301"
    assert room["outline"][0] == [2.0, 2.0]  # metres from the building's corner
    # the ETag: 304 until something changes, a new version changes it
    tag = m.headers["etag"]
    assert client.get(f"/api/sites/{s.id}/model", headers={**h, "If-None-Match": tag}).status_code == 304
    client.put(f"/api/sites/{s.id}/building", json={"data": data, "note": "again"}, headers=h)
    assert client.get(f"/api/sites/{s.id}/model", headers={**h, "If-None-Match": tag}).status_code == 200


def test_a_new_drawing_revision_keeps_what_still_matches_and_lists_the_changes(boss, building_site, db, media):  # noqa: F811
    client, h = boss
    s, d = building_site["site"], building_site["drawing"]
    data = client.post(f"/api/sites/{s.id}/building/from-drawing", json={"cad_file_id": building_site["cad"].id}, headers=h).json()["model"]["data"]
    t = data["floor_types"][0]
    t["outline"], t["columns"], t["columns_confirmed"] = L_SHAPE, [[x, y, 0.45, 0.45] for x, y in COLUMNS], True
    client.put(f"/api/sites/{s.id}/building", json={"data": data}, headers=h)
    # revision 2: the plan drawn 50 m further right on the sheet, one column more, a new room
    new = _cad(db, media, s, d, 2, shift=(50, 0))
    db.add_all([CadArea(cad_file_id=new.id, key="toilet-301", name="TOILET", x=63, y=12.7, plan=TITLE, outline=[[62, 12], [64, 12], [64, 13.5], [62, 13.5]],
                        node_id=building_site["toilet"].id, status="mapped"),
                CadArea(cad_file_id=new.id, key="balcony-302", name="BALCONY", x=70, y=18, plan=TITLE, change="added", status="candidate")])  # fmt: skip
    p = Path(media) / new.geometry_path
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        geo = json.load(fh)
    geo["geometry"]["COLUMN"]["s"] += _square(70, 11)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(geo, fh)
    db.commit()
    r = client.post(f"/api/sites/{s.id}/building/from-drawing", json={"cad_file_id": new.id}, headers=h)
    assert r.status_code == 201, r.text
    m = r.json()["model"]
    ch = m["changes"]
    assert ch["plans_kept"] == [TITLE] and ch["plans_missing"] == []
    assert list(ch["columns"].values()) == [{"kept": 3, "added": 1, "removed": 0}]
    assert ch["rooms"]["kept"] == 1 and ch["rooms"]["added"] == ["BALCONY"]
    moved = m["data"]["floor_types"][0]
    assert moved["outline"][0] == [60, 10] and moved["columns_confirmed"] is False  # moved with its title; the new column to confirm
    b = client.get(f"/api/sites/{s.id}/model", headers=h).json()["building"]
    assert len(b["rooms"]) == 1 and b["rooms"][0]["outline"][0] == [2.0, 2.0]  # the same place in the building


# --- who sees what ------------------------------------------------------------------------------------


def test_the_client_gets_the_building_of_its_own_site_only_without_the_drawing_or_costs(boss, portal, db):  # noqa: F811
    sa, sb = portal["sites"]["A"], portal["sites"]["B"]
    data = {"settings": {}, "levels": {"source": "default", "note": None}, "floors": [{"level": 0, "node_id": None, "name": "Ground", "type": "g"}],
            "floor_types": [{"key": "g", "name": "Ground", "plan": "GROUND FLOOR PLAN", "floors": [0], "outline": [[0, 0], [20000, 0], [20000, 10000], [0, 10000]],
                             "columns": [], "beams": [], "cores": [], "shift": [0, 0]}], "ifc_links": {}}  # fmt: skip
    db.add(BuildingModel(site_id=sa, version=1, data=data, note="invented"))
    db.commit()
    a, b = portal["user_A"], portal["user_B"]
    body = a.get(f"/api/portal/sites/{sa}/model").json()
    assert body["building"]["types"]["g"]["area_sqm"] == pytest.approx(200)
    assert "source" not in body["building"] and not forbidden_keys(body) and "cad_file_id" not in json.dumps(body)
    assert body["building"]["levels"]["note"] is None  # the section line is for staff
    assert b.get(f"/api/portal/sites/{sa}/model").status_code == 404
    assert b.get(f"/api/portal/sites/{sb}/model").json()["building"] is None  # no model: the schematic boxes
    for path in (f"/api/sites/{sa}/building", f"/api/sites/{sa}/building/versions", f"/api/sites/{sa}/model"):
        assert a.get(path).status_code in (401, 403), path  # no drawing tools in the portal
    client, h = boss
    staff = client.get(f"/api/sites/{sa}/model", headers=h).json()["building"]
    assert staff["source"]["note"] == "invented"


def test_billing_planning_and_the_site_engineer_on_their_own_site_build_it_and_sales_does_not(building_site, db, make_user):
    s = building_site["site"]
    users = {r: make_user(f"{r.replace('_', '-')}-x@example.com", r) for r in ("billing", "planning", "site_engineer", "sales")}
    other_engineer = make_user("engineer-elsewhere@example.com", "site_engineer")
    db.add(SiteMember(site_id=s.id, user_id=users["site_engineer"].id, role_on_site="incharge"))
    db.add(SiteMember(site_id=s.id, user_id=users["sales"].id, role_on_site="sales"))
    db.commit()
    body = {"cad_file_id": building_site["cad"].id}
    codes = {}
    for who, u in [*users.items(), ("engineer elsewhere", other_engineer)]:
        c = TestClient(app)
        hh = login(c, u.email)
        codes[who] = c.post(f"/api/sites/{s.id}/building/from-drawing", json=body, headers=hh).status_code
    assert codes == {"billing": 201, "planning": 201, "site_engineer": 201, "sales": 403, "engineer elsewhere": 404}
    assert db.scalar(select(User.id).where(User.email == "sales-x@example.com"))


def test_a_client_bim_file_is_kept_with_the_drawings_and_its_elements_link_to_places(boss, portal, db):  # noqa: F811
    client, h = boss
    sa = portal["sites"]["A"]
    ifc = (Path(__file__).parent / "fixtures/invented-small.ifc").read_bytes()  # the same invented file as the frontend test
    assert client.post(f"/api/sites/{sa}/building/ifc", files={"file": ("tower.ifc", b"not an ifc", "application/octet-stream")}, headers=h).status_code == 422
    r = client.post(f"/api/sites/{sa}/building/ifc", files={"file": ("tower.ifc", ifc, "application/octet-stream")}, headers=h)
    assert r.status_code == 201, r.text
    b = client.get(f"/api/sites/{sa}/model", headers=h).json()["building"]
    assert b["ifc"]["filename"] == "tower.ifc" and b["ifc"]["max_mb"] == 150 and b["types"] == {}
    assert client.get(b["ifc"]["url"], headers=h).content == ifc
    node = db.scalar(select(SiteNode.id).where(SiteNode.site_id == sa))
    assert client.put(f"/api/sites/{sa}/building/ifc-links", json={"element": 200, "node_id": node}, headers=h).json() == {"ifc_links": {"200": node}}
    a, bb = portal["user_A"], portal["user_B"]
    body = a.get(f"/api/portal/sites/{sa}/model").json()["building"]
    assert body["ifc_links"] == {"200": node} and body["ifc"]["url"] == f"/api/portal/sites/{sa}/building/ifc"
    assert a.get(body["ifc"]["url"]).status_code == 200 and bb.get(body["ifc"]["url"]).status_code == 404
    assert len(db.scalars(select(DrawingRevision).join(Drawing, Drawing.id == DrawingRevision.drawing_id).where(Drawing.site_id == sa, Drawing.title == "BIM model (IFC)")).all()) == 1
    _ = FORBIDDEN


def test_the_completion_certificate_has_its_3d_page_only_when_one_was_added(media):  # noqa: F811
    from app.closeout.completion import _image_3d
    from app.closeout.models import WorkCompletion

    w = WorkCompletion(code="WCC-2026-9001")
    assert _image_3d(w) == ""
    (Path(media) / "wcc").mkdir()
    (Path(media) / "wcc/building-3d.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    w.image_3d_path = "wcc/building-3d.png"
    page = _image_3d(w)
    assert "THE BUILDING IN 3D" in page and "building-3d.png" in page and "page-break-before" in page


def test_the_section_levels_map_to_the_floors_from_the_ground_up_and_the_rest_are_flagged():
    """The sample office drawing's section: basement pairs, a +0.914 plinth for the ground floor,
    one level per storey (slab top and finished floor pairs), a tank level above the terrace."""
    values = [-11.049, -10.973, -7.087, -7.01, -3.124, -3.048, 0.914, 6.172, 9.982, 10.135, 13.945, 17.907, 21.869, 25.832, 29.794, 33.757, 37.719, 41.681, 45.72, 48.692]
    lv = {"source": "section", "values_m": values}
    data = {"settings": {"floor_height_m": 3.962}, "levels": lv, "floors": [{"level": n, "name": f"F{n}", "type": "t"} for n in range(0, 12)]}
    el = {f["level"]: f for f in service.elevations(data)}
    assert el[0]["elevation_m"] == pytest.approx(0.914) and el[0]["height_m"] == pytest.approx(5.258)  # a tall ground floor
    assert el[2]["elevation_m"] == pytest.approx(10.135)  # the finished floor of the 32'9" / 33'3" pair
    assert el[10]["elevation_m"] == pytest.approx(41.681) and el[11]["elevation_m"] == pytest.approx(45.72)
    assert all(f["level_source"] == "section" and f["level_flag"] is None for f in el.values())
    assert service.unmatched_levels(data) == [-10.973, -7.01, -3.048, 48.692]  # basements the site has not, the tank
    # corrected by hand on the building page: that floor's level wins, the floor below takes its height from it
    data["floors"][3] |= {"elevation_m": 14.2, "level_by_hand": True}
    el = {f["level"]: f for f in service.elevations(data)}
    assert el[3]["elevation_m"] == pytest.approx(14.2) and el[3]["level_source"] == "hand" and el[2]["height_m"] == pytest.approx(4.065)
