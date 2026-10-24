# ruff: noqa: E501, PLC0415
"""DEMO: the X-ray building of an invented office tower site from the sample drawing in
data/samples/dwg (CHRIPAL HOUSE, G + 10, a terrace and an overhead tank). Done as a user would:
the drawing read by the takeoff, the typical floor's toilets traced by a click inside each and
mapped to the floor's places, copied to the other floors; the model started from the drawing,
each plan's outline proposed from its walls, its columns found and confirmed, the stair and lift
cores traced (a click at each corner), the heights read from the section; stages over three
months with every status colour. Invented site, DEMO users only; the drawing stays in data/ and
the media volume. Rerunning replaces the previous run.

    python -m app.cli demo-xray
"""

import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

SITE_CODE = "DEMO-X-001"
SITE_NAME = "DEMO Chripal House (X-ray)"
SAMPLE = Path("/data/samples/dwg/CHRIPAL HOUSE R1_ALL FLOOR WORKING GFC AT 30-09-24.dwg")
ARCHITECT = "DEMO architect (sample drawing)"
TOILETS = [("GENT'S TOILET", "west", "Gents toilet (west)"), ("LADIES TOILET", "west", "Ladies toilet (west)"), ("GENT'S TOILET", "east", "Gents toilet (east)"), ("LADIES TOILET", "east", "Ladies toilet (east)")]
TYPICAL = "2ND,3RD,5TH ,6TH,8TH & 9TH FLOOR WORKING PLAN"
# what a user clicks on the typical plan (drawing units, inches): the two dog-leg stairs beside
# the foyers and the two lift banks, corner by corner (the snapping puts them on the walls)
CORES = [("stair", [(-2790, 12420), (-2640, 12420), (-2640, 12595), (-2790, 12595)]),
         ("stair", [(-1165, 12805), (-1025, 12805), (-1025, 12985), (-1165, 12985)]),
         ("lift", [(-2034, 12491), (-1935, 12491), (-1935, 12770), (-2034, 12770)]),
         ("lift", [(-1695, 12491), (-1596, 12491), (-1596, 12770), (-1695, 12770)])]  # fmt: skip
START = date(2026, 7, 27)
# the plans that are floors (the sheet titles in the title blocks and the staircase detail are not)
PLANS = {"GROUND FLOOR PLAN", "1ST FLOOR WORKING PLAN", TYPICAL, "4TH & 7TH FLOOR WORKING PLAN", "10TH FLOOR WORKING PLAN"}
TENTH = "10TH FLOOR WORKING PLAN"
# the ground floor plan also draws the plot, the drives and the compound: the building is clicked
GROUND_CORNERS = [(-3690, 6935), (10, 6935), (10, 7770), (-3690, 7770)]
LIFT_LOBBY = (-1816, 12628)  # the overhead tank stands over the lift core


def _reset(db: Session) -> int:
    from app.closeout.demo import _purge
    from app.sites.models import Site

    site = db.scalar(select(Site).where(Site.code == SITE_CODE, Site.is_demo))
    if site is None:
        return 0
    db.execute(text("delete from site_members where site_id = :s"), {"s": site.id})
    n = _purge(db, "sites", [site.id], set())
    db.commit()
    return n


def _site(db: Session) -> tuple:
    from app.models import User
    from app.sites.models import Site, SiteMember, SiteNode
    from app.team.demo import email_for

    users = {r: db.scalar(select(User.id).where(User.email == email_for(r))) for r in ("site_engineer", "site_supervisor", "billing", "planning", "sales")}
    if not all(users.values()):
        raise SystemExit("Run seed-demo-team first (the DEMO users).")
    # the client of the DEMO portal users (so the client's 3D view can be shown), else a DEMO client
    client = db.scalar(text("select cu.client_id from client_users cu join users u on u.id = cu.user_id where u.email like 'demo-client-%' order by u.email limit 1")) or db.scalar(
        text("select id from clients where is_demo and name like 'DEMO%' order by id limit 1")
    )
    site = Site(code=SITE_CODE, name=SITE_NAME, city="Ahmedabad", state="Gujarat", status="active", is_demo=True, client_id=client,
                start_date=START, target_date=date(2027, 1, 31), site_incharge_id=users["site_engineer"])  # fmt: skip
    db.add(site)
    db.flush()
    for role, uid in users.items():
        db.add(SiteMember(site_id=site.id, user_id=uid, role_on_site={"site_engineer": "incharge", "site_supervisor": "supervisor", "sales": "sales"}.get(role, "office")))
    tower = SiteNode(site_id=site.id, kind="tower", name="Tower", sort_order=0)
    db.add(tower)
    db.flush()
    floors = {}
    for lv in range(0, 11):
        f = SiteNode(site_id=site.id, parent_id=tower.id, kind="floor", name="Ground floor" if lv == 0 else f"Floor {lv}", level_no=lv, sort_order=lv)
        db.add(f)
        db.flush()
        floors[lv] = f.id
    terrace = SiteNode(site_id=site.id, parent_id=tower.id, kind="terrace", name="Terrace", level_no=11, sort_order=11)
    db.add(terrace)
    db.flush()
    oht = SiteNode(site_id=site.id, parent_id=terrace.id, kind="oh_tank", name="Overhead water tank", sort_order=0)
    db.add(oht)
    db.commit()
    return site, floors, terrace.id, oht.id


def _drawing(db: Session, site, user_id) -> int:
    from app.config import settings
    from app.sites.models import Drawing, DrawingRevision
    from app.takeoff import pipeline
    from app.takeoff.models import CadFile, CadLayerMap

    if not SAMPLE.exists():
        raise SystemExit(f"The sample drawing is missing: {SAMPLE}")
    rel = f"sites/{site.id}/drawings/DEMO-chripal-house-r1.dwg"
    dst = Path(settings.media_dir) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE, dst)
    d = Drawing(site_id=site.id, title="DEMO Chripal House: all floors, working (sample drawing)", discipline="architectural", created_by=user_id)
    db.add(d)
    db.flush()
    r = DrawingRevision(drawing_id=d.id, rev_no=1, stored_path=rel, filename=dst.name, size_bytes=dst.stat().st_size, created_by=user_id)
    db.add(r)
    db.flush()
    d.current_revision_id = r.id
    # the layer mapping, as set once for this architect: walls, and the services never drawn
    if not db.scalar(select(CadLayerMap).where(CadLayerMap.architect == ARCHITECT)):
        roles = {"wall": "walls", "fur": "hide", "TITLE": "hide", "dim": "hide", "DIM OUTER": "hide", "DIM_SECTIONS": "hide"}
        db.add(CadLayerMap(architect=ARCHITECT, roles=roles, created_by=user_id))
    f = CadFile(revision_id=r.id, drawing_id=d.id, site_id=site.id, status="queued", architect=ARCHITECT, created_by=user_id)
    db.add(f)
    db.commit()
    f = pipeline.process(db, f)
    if f.status != "ready":
        raise SystemExit(f"The drawing was not read: {f.error}")
    return f.id


def _stages(db: Session, site_id: int, node_id: int, template: str, start: date | None, state: str) -> None:
    """The area's scope and its stages: done (hold points certified), hold (up to the first hold
    point, done but not certified), progress (about half done, the next in progress), late (the
    current step past its planned end), blocked, not_started; two days a step (a pond test four)."""
    from app.sites.models import AreaScope, StageTemplate, StageTemplateStep, Task

    tid = db.scalar(select(StageTemplate.id).where(StageTemplate.name == template))
    steps = list(db.scalars(select(StageTemplateStep).where(StageTemplateStep.template_id == tid).order_by(StageTemplateStep.sort_order)))
    sc = AreaScope(site_id=site_id, node_id=node_id, stage_template_id=tid, qty=Decimal("6"), unit="sqm", progress_percent=Decimal(0))
    db.add(sc)
    db.flush()
    first_hold = next((i for i, s in enumerate(steps) if s.hold_point), len(steps) - 1)
    upto = {"done": len(steps), "hold": first_hold + 1, "progress": max(1, len(steps) // 2), "late": max(1, len(steps) // 2), "blocked": max(1, len(steps) // 3), "not_started": 0}[state]
    today = date.today()
    day = start or today + timedelta(days=10)  # not started: planned from next week
    pct = Decimal(0)
    for i, st in enumerate(steps):
        span = 4 if "pond" in st.name.lower() else 2
        done = start is not None and i < upto
        current = start is not None and i == upto and state in ("progress", "late", "blocked")
        if not done and not current and start is not None:
            day = max(day, today + timedelta(days=3))  # what is still to do is planned from today
        end = day + timedelta(days=span - 1)
        status = "done" if done else "not_started"
        if done and st.hold_point and not (state == "hold" and i == first_hold):
            status = "certified"
        planned_end = end
        if current:
            status = "blocked" if state == "blocked" else "in_progress"
            planned_end = today - timedelta(days=6) if state == "late" else max(end, today + timedelta(days=2))
        db.add(Task(site_id=site_id, node_id=node_id, area_scope_id=sc.id, step_id=st.id, name=st.name, sort_order=i, planned_start=day, planned_end=planned_end,
                    actual_start=day if (done or current) else None, actual_end=end if done else None, status=status,
                    certified_at=datetime.combine(end + timedelta(days=3), datetime.min.time(), UTC) if status == "certified" else None,
                    progress_percent=Decimal(100) if done else Decimal(40) if current else Decimal(0)))  # fmt: skip
        if done:
            pct += Decimal(st.weight_percent or 0)
        day = (planned_end if current else end) + timedelta(days=1)
    sc.progress_percent = min(pct, Decimal(100))


def run(db: Session) -> dict:
    import app.main as main
    from app.building.service import current
    from app.closeout.demo import _login, _ok
    from app.models import User
    from app.sites.models import SiteNode
    from app.team.demo import email_for

    removed = _reset(db)
    site, floors, terrace_id, oht_id = _site(db)
    billing = db.scalar(select(User.id).where(User.email == email_for("billing")))
    fid = _drawing(db, site, billing)
    c = TestClient(main.app)
    h = _login(c, email_for("billing"))
    out: dict = {"site": f"{site.code} {site.name}", "removed_rows": removed, "drawing_file": fid}

    # 1. the typical floor's toilets: a click inside each (the rectangle to the walls), mapped -----
    areas = _ok(c.get(f"/api/takeoff/files/{fid}/areas?show=all", headers=h), "areas")
    rows = areas["areas"]
    from app.building import service as bsvc
    from app.takeoff.models import CadFile

    cad = db.get(CadFile, fid)
    region = next(p["region"] for p in bsvc.plans(cad) if p["title"] == TYPICAL)
    typical = [a for a in rows if region[0] <= a["x"] <= region[2] and region[1] <= a["y"] <= region[3]]
    floor2 = floors[2]
    made = []
    taken: set[int] = set()
    for label, side, node_name in TOILETS:
        cands = sorted((a for a in typical if label in (a.get("name") or "").upper().replace("’", "'") and a["id"] not in taken), key=lambda a: a["x"])
        a = cands[0] if side == "west" else cands[-1]
        taken.add(a["id"])
        node = SiteNode(site_id=site.id, parent_id=floor2, kind="toilet", name=node_name, sort_order=len(made))
        db.add(node)
        db.commit()
        r = c.post(f"/api/takeoff/files/{fid}/propose", json={"x": a["x"], "y": a["y"]}, headers=h)
        how = "one click inside"
        if r.status_code == 200:
            pts = r.json()["outline"]
        else:  # a gap in the walls: the four corners clicked instead (the label's size around it), each snapped
            from app.takeoff.sizes import parse_size

            s = parse_size(a.get("size_text") or "")
            hw, hl = (s.width_m / 2 / cad.unit_m, s.length_m / 2 / cad.unit_m) if s else (40, 40)
            pts = []
            for dx, dy in ((-hw, -hl), (hw, -hl), (hw, hl), (-hw, hl)):
                q = _ok(c.post(f"/api/takeoff/files/{fid}/snap", json={"x": a["x"] + dx, "y": a["y"] + dy, "radius": 12, "previous": pts[-1] if pts else None}, headers=h), "snap")
                pts.append([q["x"], q["y"]])
            how = "four corners clicked"
        prop = _ok(c.post(f"/api/takeoff/areas/{a['id']}/trace", json={"points": pts}, headers=h), "trace")
        prop["how"] = how
        body = {"node_id": node.id}
        if not a.get("sunk_m"):
            body["sunk_mm"] = 152  # 6" sunk: the drawing's note sits by the shafts, not by these toilets
        _ok(c.put(f"/api/takeoff/areas/{a['id']}", json=body, headers=h), "map")
        made.append({"area": a["id"], "node": node_name, "traced_sqm": prop.get("traced_area_sqm"), "label": a.get("size_text"), "label_sqm": a.get("label_area_sqm"), "how": how})
    out["toilets_on_the_typical_floor"] = made
    targets = [floors[lv] for lv in range(1, 11) if lv != 2]
    _ok(c.post(f"/api/takeoff/files/{fid}/copy-floors", json={"area_ids": [m["area"] for m in made], "source_floor_id": floor2, "target_floor_ids": targets}, headers=h), "copy to floors", 201)

    # 2. the model from the drawing ---------------------------------------------------------------------
    b = _ok(c.post(f"/api/sites/{site.id}/building/from-drawing", json={"cad_file_id": fid}, headers=h), "from drawing", 201)
    data = b["model"]["data"]
    out["levels"] = data["levels"]["note"]
    out["plans"] = {t["plan"]: t["floors"] for t in data["floor_types"]}
    data["settings"]["column_max_m"] = 1.1  # the columns here are up to 30" x 42" (1.07 m)
    known = {t["plan"] for t in data["floor_types"]}
    for p in bsvc.plans(cad):  # a plan the draft left out (its title names no floor): added from the list
        if p["title"] in PLANS and p["title"] not in known:
            data["floor_types"].append({"key": bsvc._slug(p["title"]), "name": p["title"].title(), "plan": p["title"], "title_xy": p["xy"], "region": p["region"],
                                        "floors": p["floors"], "outline": [], "columns": [], "columns_confirmed": False, "beams": [], "cores": [], "shift": [0, 0]})  # fmt: skip
    data["floor_types"] = [t for t in data["floor_types"] if t["plan"] in PLANS]
    for f in data["floors"]:
        f["type"] = None
    _ok(c.put(f"/api/sites/{site.id}/building", json={"data": data, "note": "DEMO: the plans as floor types"}, headers=h), "save types")
    found = {}
    for t in data["floor_types"]:
        if t["plan"] == "GROUND FLOOR PLAN":  # four corners clicked, each snapped to the walls
            pts: list = []
            for x, y in GROUND_CORNERS:
                q = _ok(c.post(f"/api/takeoff/files/{fid}/snap", json={"x": x, "y": y, "radius": 12, "previous": pts[-1] if pts else None}, headers=h), "snap")
                pts.append([q["x"], q["y"]])
            t["outline"] = pts
            continue
        r = _ok(c.post(f"/api/sites/{site.id}/building/propose-outline", json={"key": t["key"]}, headers=h), f"outline {t['key']}")
        t["outline"] = r["outline"]
    _ok(c.put(f"/api/sites/{site.id}/building", json={"data": data, "note": "DEMO: outlines proposed from the walls"}, headers=h), "save outlines")
    for t in data["floor_types"]:
        r = _ok(c.post(f"/api/sites/{site.id}/building/detect-columns", json={"key": t["key"], "outline": t["outline"]}, headers=h), f"columns {t['key']}")
        t["columns"], t["columns_confirmed"] = r["columns"], bool(r["columns"])
        found[t["plan"]] = len(r["columns"])
    out["columns_found"] = found
    saved = _ok(c.put(f"/api/sites/{site.id}/building", json={"data": data, "note": "DEMO: columns confirmed"}, headers=h), "save columns")
    # the cores, traced on the typical plan and on the plans that line up with it
    data = saved["model"]["data"]
    ref = next(t for t in data["floor_types"] if t["plan"] == TYPICAL)
    for t in data["floor_types"]:
        if "TERRACE" in t["plan"].upper() or "O.H.W.T" in t["plan"].upper():
            continue
        dx, dy = ref["shift"][0] - t["shift"][0], ref["shift"][1] - t["shift"][1]
        t["cores"] = [{"kind": k, "outline": [[x + dx, y + dy] for x, y in pts], "risers": None} for k, pts in CORES]
    # the terrace: the roof of the 10th floor, traced on its outline (the terrace plan draws its
    # level marks and the stair cabin, not its edge); no walls of its own, the stair cabin's stair
    tenth = next(t for t in data["floor_types"] if t["plan"] == TENTH)
    data["floor_types"].append({"key": "terrace", "name": "Terrace (roof of the 10th)", "plan": "TERRACE WORKING PLAN", "title_xy": None, "region": None, "floors": [11],
                                "outline": tenth["outline"], "columns": [], "columns_confirmed": True, "beams": [], "cores": [c for c in tenth["cores"] if c["kind"] == "stair"][:1],
                                "shift": tenth["shift"], "shift_fixed": True, "walls": False})  # fmt: skip
    data["settings"]["beams_on_walls"] = True
    _ok(c.put(f"/api/sites/{site.id}/building", json={"data": data, "note": "DEMO: stair and lift cores traced, beams on the column lines"}, headers=h), "save cores")

    # 3. the terrace (its waterproofing: the whole roof) and the overhead tank (6 x 4 m over the lift core) --
    data = _ok(c.get(f"/api/sites/{site.id}/building", headers=h), "model")["model"]["data"]
    tenth = next(t for t in data["floor_types"] if t["plan"] == TENTH)
    ref = next(t for t in data["floor_types"] if t["plan"] == TYPICAL)
    ox, oy = LIFT_LOBBY[0] + ref["shift"][0] - tenth["shift"][0], LIFT_LOBBY[1] + ref["shift"][1] - tenth["shift"][1]
    half_w, half_d = 3 / cad.unit_m, 2 / cad.unit_m
    for node_id, name, pts in ((terrace_id, "Terrace", tenth["outline"]), (oht_id, "Overhead water tank", [[ox - half_w, oy - half_d], [ox + half_w, oy - half_d], [ox + half_w, oy + half_d], [ox - half_w, oy + half_d]])):
        a = _ok(c.post(f"/api/takeoff/files/{fid}/areas", json={"name": name, "points": pts, "sunk_mm": 0}, headers=h), f"trace {name}", 201)
        _ok(c.put(f"/api/takeoff/areas/{a['id']}", json={"node_id": node_id, "plan": "TERRACE WORKING PLAN"}, headers=h), f"map {name}")
    db.commit()

    # 4. stages over three months: every status colour somewhere ---------------------------------------
    plan = {1: "done", 2: "done", 3: "done", 4: ("done", "done", "hold", "hold"), 5: ("progress", "late", "progress", "progress"), 6: ("hold", "hold", "progress", "progress"),
            7: ("blocked", "progress", "progress", "late"), 8: ("progress", "not_started", "late", "not_started"), 9: "not_started", 10: ("not_started", "not_started", None, None)}  # fmt: skip
    toilets = db.scalars(select(SiteNode).where(SiteNode.site_id == site.id, SiteNode.kind == "toilet").order_by(SiteNode.sort_order, SiteNode.id)).all()
    by_floor: dict[int, list] = {}
    for n in toilets:
        by_floor.setdefault(n.parent_id, []).append(n)
    for lv in range(1, 11):
        states = plan[lv] if isinstance(plan[lv], tuple) else (plan[lv],) * 4
        for i, n in enumerate(sorted(by_floor.get(floors[lv], []), key=lambda x: x.name)):
            st = states[i % 4]
            if st is None:
                continue  # no scope here (another applicator)
            start = START + timedelta(days=(lv - 1) * 8 + i) if st != "not_started" else None
            _stages(db, site.id, n.id, "Toilet / wet area (coating)", start, st)
    _stages(db, site.id, terrace_id, "Terrace (APP membrane)", date(2026, 9, 28), "progress")
    _stages(db, site.id, oht_id, "Water tank (UG / OH)", date(2026, 8, 20), "done")
    from app.sites import progress  # noqa: PLC0415

    progress.refresh(db, site)  # the steps were written here: the floors and the site from them
    db.commit()
    # 5. the client sees it in the portal: the site visible, the DEMO client users on it ---------------
    from app.portal.models import ClientUser, ClientUserSite

    hd = _login(c, email_for("director"))
    _ok(c.put(f"/api/portal-admin/sites/{site.id}", json={"visible": True, "sections": {}}, headers=hd), "portal visible")
    for cu in db.scalars(select(ClientUser).where(ClientUser.client_id == site.client_id)):
        if not db.get(ClientUserSite, (cu.user_id, site.id)):
            db.add(ClientUserSite(user_id=cu.user_id, site_id=site.id))
    db.commit()
    m = current(db, site.id)
    payload = bsvc.payload(db, site.id)
    out["model"] = {"version": m.version, "floors": len(payload["floors"]) if payload else 0, "rooms": len(payload["rooms"]) if payload else 0,
                    "types": {k: {"outline_sqm": v["area_sqm"], "columns": len(v["columns"]), "cores": len(v["cores"]), "walls": len(v["walls"])} for k, v in (payload or {}).get("types", {}).items()}}  # fmt: skip
    return out
