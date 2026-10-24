# ruff: noqa: E501
"""DEMO (marked demo, demo users only): a swimming pool site measured from its drawing and billed.

The drawing is made here (no sample file): pool A (straight sides, round ends), slope Q along the
pool's far side (drawn 300 mm into the pool, so it is trimmed), balancing tank R below the pool
(its top edge is 5.19 m of the pool's wall: the shared edge, a weir 450 mm high) with a bulged
bottom, pipe sleeves as circles, and Section Y-Y with its levels. The shapes are worked out to
give the figures of the billing team's own example: A 55.0027 sqm / 30.119 m, Q 6.1324 sqm /
13.772 m after the trim, R 16.9877 sqm / 15.786 m.

The work order has three items: coating per sqft, pipe sleeve per No, brick bat per sqft per layer
(two layers). Sheet 1 bills A and Q (R and the second brick-bat layer not done yet: "–"); the
client approves it in the portal; RA bill 1 is made from it, sent and turned into the tax invoice.
Sheet 2 bills the rest; the client corrects one line (logged, accepted); RA bill 2 is the draft
proforma with its checklist.

Every measuring and billing step goes through the API as the DEMO user of the role that does it
(password from DEMO_USER_PASSWORD, never printed). A rerun first removes what the previous run made.

    docker compose exec api python -m app.cli demo-measure
"""

import math
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.closeout.demo import Step, _login, _ok, _password, _purge
from app.measure import geom

SITE_CODE = "DEMO-POOL"
SITE_NAME = "DEMO Club house swimming pool"
CLIENT = "DEMO Pool Club (demo client)"
CLIENT_GSTIN = "24DEMOP0000D1Z0"  # invented; 24 is Gujarat
CLIENT_USER = ("DEMO Client Pool Billing", "demo-client-pool-billing@example.com")
SAC = "995454"
SHARED = 5.19


def shapes() -> dict:
    """The three outlines in metres ([x, y, bulge]), the sleeves and the click inside each."""
    P, A = 30.119, 55.0027
    r = (P - math.sqrt(P * P - 4 * math.pi * A)) / (2 * math.pi)
    L = (P - 2 * math.pi * r) / 2
    pool = [[0.0, 0.0, 0.0], [L, 0.0, 1.0], [L, 2 * r, 0.0], [0.0, 2 * r, 1.0]]
    s = 6.886  # the slope after the trim: Lq + wq (13.772 / 2), Lq × wq = 6.1324
    lq = (s + math.sqrt(s * s - 4 * 6.1324)) / 2
    wq = s - lq
    xq = (L - lq) / 2
    slope = [[xq, 2 * r - 0.3, 0.0], [xq + lq, 2 * r - 0.3, 0.0], [xq + lq, 2 * r + wq, 0.0], [xq, 2 * r + wq, 0.0]]
    x1, e = L - SHARED - 0.4, 0.1

    def tank(dd, b):
        return [[x1, 0.0, 0.0], [x1 - e, -dd, b], [x1 + SHARED + e, -dd, 0.0], [x1 + SHARED, 0.0, 0.0]]

    def depth(b):  # the depth giving the periphery for this bulge
        lo, hi = 0.0, 10.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if geom.periphery(tank(mid, b)) > 15.786 else (mid, hi)
        return lo

    lo, hi = 0.5, 1.0  # the bulge giving the area (one root in this range)
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if geom.area(tank(depth(mid), mid)) < 16.9877 else (lo, mid)
    dd = depth(lo)
    sleeves = [(1.0, 0.8), (L - 1.0, 0.8), (1.0, 2 * r - 0.8), (L - 1.0, 2 * r - 0.8), (x1 + 1.0, -dd / 2), (x1 + SHARED - 1.0, -dd / 2)]
    return {"pool": pool, "slope": slope, "tank": tank(dd, lo), "sleeves": sleeves, "clicks": {"A": (L / 2, r), "Q": (xq + lq / 2, 2 * r + wq / 2), "R": (x1 + SHARED / 2, -dd / 2)},
            "r": r, "L": L, "wq": wq, "depth": dd}  # fmt: skip


def dxf(path: Path) -> None:
    """The drawing, in millimetres as the architect draws."""
    import ezdxf  # noqa: PLC0415

    sh = shapes()
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for name, colour in (("POOL", 5), ("SLOPE", 3), ("TANK", 4), ("SLEEVE", 1), ("SECTION", 7), ("TEXT", 2)):
        doc.layers.add(name, color=colour)

    def poly(o, layer):
        msp.add_lwpolyline([(x * 1000, y * 1000, 0, 0, b) for x, y, b in o], format="xyseb", close=True, dxfattribs={"layer": layer})

    poly(sh["pool"], "POOL")
    poly(sh["slope"], "SLOPE")
    poly(sh["tank"], "TANK")
    for x, y in sh["sleeves"]:
        msp.add_circle((x * 1000, y * 1000), 50, dxfattribs={"layer": "SLEEVE"})
    for (x, y), label in zip(sh["clicks"].values(), ("SWIMMING POOL A", "SLOPE Q", "BALANCING TANK R"), strict=True):
        msp.add_text(label, height=180, dxfattribs={"layer": "TEXT", "insert": (x * 1000 - 900, y * 1000 + 300)})
    # Section Y-Y: to the right of the plan, the levels written beside the profile
    ox = (sh["L"] + 2 * sh["r"] + 4) * 1000
    msp.add_text("SECTION Y-Y", height=250, dxfattribs={"layer": "TEXT", "insert": (ox, 7500)})
    profile = [(0, 2250), (1051, 2250), (2100, 1800), (2100, 600), (9000, 600), (9000, 1800), (9300, 1800), (9300, -900), (14500, -900), (14500, 600)]
    msp.add_lwpolyline([(ox + x, y * 1.5 + 2000) for x, y in profile], dxfattribs={"layer": "SECTION"})
    for x, lv in ((-900, "+2250"), (2300, "+1800"), (2300, "+600"), (9500, "-900")):
        y = {"+2250": 2250, "+1800": 1800, "+600": 600, "-900": -900}[lv]
        msp.add_text(lv, height=160, dxfattribs={"layer": "TEXT", "insert": (ox + x, y * 1.5 + 2050)})
    msp.add_text("1051", height=140, dxfattribs={"layer": "TEXT", "insert": (ox + 300, 2250 * 1.5 + 2250)})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def reset(db: Session, site_id: int) -> int:
    n = 0
    for table in ("measure_sheets", "measure_items", "measure_edges", "measure_areas", "measurement_sets", "measurements", "tax_invoices", "ra_bills",
                  "client_contracts", "client_work_orders", "drawings"):  # fmt: skip
        ids = list(db.scalars(text(f'select id from "{table}" where site_id = :s'), {"s": site_id}))
        n += _purge(db, table, ids, set())
    db.flush()
    return n


def _masters(db: Session, users: dict) -> tuple:
    from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine
    from app.finance.models import ClientContract, ContractLine
    from app.masters.models import Client
    from app.sites.models import Site, SiteMember

    cl = db.scalar(select(Client).where(Client.name == CLIENT))
    if cl is None:
        cl = Client(name=CLIENT, type="other", notes="DEMO: invented")
        db.add(cl)
    cl.is_demo, cl.gstin, cl.address, cl.city, cl.state = True, CLIENT_GSTIN, "DEMO Club house, Plot 0, Sindhu Bhavan Road", "Ahmedabad", "Gujarat"
    db.flush()
    site = db.scalar(select(Site).where(Site.code == SITE_CODE))
    removed = 0
    if site is None:
        site = Site(code=SITE_CODE, name=SITE_NAME, city="Ahmedabad", state="Gujarat", status="active", is_demo=True, start_date=date.today() - timedelta(days=60))
        db.add(site)
        db.flush()
    else:
        removed = reset(db, site.id)
    site.client_id, site.measurements_need_approval = cl.id, True
    for uid in users.values():
        if not db.scalar(select(SiteMember.site_id).where(SiteMember.site_id == site.id, SiteMember.user_id == uid)):
            db.add(SiteMember(site_id=site.id, user_id=uid, role_on_site="office"))
    wo = ClientWorkOrder(code=f"CWO-{SITE_CODE}", client_ref="DEMO/POOL/WO/01", site_id=site.id, client_id=cl.id, lines_from="typed", status="accepted",
                         accepted_by=users["billing"], accepted_at=date.today() - timedelta(days=50), payment_basis="invoice", payment_days=30)  # fmt: skip
    items = [("1", "Waterproofing coating, two coats, on floors, side walls, wall tops and slopes", "sqft", "3000", "85", False, 1),
             ("2", "Pipe sleeve with puddle flange, fixed in the wall", "nos", "10", "1250", False, 1),
             ("3", "Brick bat coba, per layer", "sqft", "1700", "42", True, 2)]  # fmt: skip
    for i, (no, desc, unit, qty, rate, per_layer, layers) in enumerate(items):
        wo.lines.append(ClientWorkOrderLine(sort_order=i, item_no=no, description=desc, unit=unit, qty=Decimal(qty), rate=Decimal(rate), per_layer=per_layer, layers=layers, sac=SAC))
    db.add(wo)
    db.flush()
    c = ClientContract(site_id=site.id, client_id=cl.id, contract_value=sum(Decimal(q) * Decimal(r) for _, _, _, q, r, _, _ in items), retention_percent=Decimal(0),
                       sac=SAC, place_of_supply="Gujarat", client_gstin=CLIENT_GSTIN, billing_address=f"{cl.address}, {cl.city}, {cl.state}", created_by=users["billing"])  # fmt: skip
    for w in wo.lines:
        c.lines.append(ContractLine(sort_order=w.sort_order, item_no=w.item_no, description=w.description, unit=w.unit, qty=w.qty, rate=w.rate, wo_line_id=w.id))
    db.add(c)
    db.commit()
    return site, wo, removed


def _drawing(db: Session, site, user_id) -> int:
    from app.config import settings
    from app.sites.models import Drawing, DrawingRevision
    from app.takeoff import pipeline
    from app.takeoff.models import CadFile

    rel = f"sites/{site.id}/drawings/DEMO-pool-plan-and-section-r1.dxf"
    dst = Path(settings.media_dir) / rel
    dxf(dst)
    d = Drawing(site_id=site.id, title="DEMO Pool: plan and Section Y-Y", discipline="architectural", created_by=user_id)
    db.add(d)
    db.flush()
    r = DrawingRevision(drawing_id=d.id, rev_no=1, stored_path=rel, filename=dst.name, size_bytes=dst.stat().st_size, created_by=user_id)
    db.add(r)
    db.flush()
    d.current_revision_id = r.id
    f = CadFile(revision_id=r.id, drawing_id=d.id, site_id=site.id, status="queued", created_by=user_id)
    db.add(f)
    db.commit()
    f = pipeline.process(db, f)
    if f.status != "ready":
        raise SystemExit(f"The drawing was not read: {f.error}")
    return f.id


def run(db: Session) -> dict:
    import app.main as main
    from app.models import User
    from app.portal.models import ClientUser
    from app.team.demo import email_for

    users = {r: db.scalar(select(User.id).where(User.email == email_for(r))) for r in ("billing", "director")}
    if not all(users.values()):
        raise SystemExit("Run seed-demo-team first (the DEMO users).")
    _password()
    site, wo, removed = _masters(db, users)
    fid = _drawing(db, site, users["billing"])
    c = TestClient(main.app)
    hb, hd = _login(c, email_for("billing")), _login(c, email_for("director"))
    out: dict = {"site": f"{site.code} {site.name}", "removed_rows": removed}
    sh = shapes()
    base = f"/api/measure/sites/{site.id}"

    # 1. click inside each outline and name it ------------------------------------------------------
    areas = {}
    for code, name, kind in (("A", "Swimming pool", "area"), ("Q", "Slope along the deck", "area"), ("R", "Balancing tank", "area")):
        x, y = sh["clicks"][code]
        areas[code] = _ok(c.post(f"{base}/areas", json={"cad_file_id": fid, "x": x, "y": y, "code": code, "name": name, "kind": kind}, headers=hb), f"area {code}", 201)
    st = _ok(c.get(base, headers=hb), "state")
    out["areas"] = {a["code"]: {"area_sqm": a["area_sqm"], "periphery_m": a["periphery_m"], "net_area_sqm": a["net_area_sqm"], "net_periphery_m": a["net_periphery_m"], "counts": a["counts"]} for a in st["areas"]}
    edge = st["edges"][0]
    out["shared_edge"] = {"between": f"{edge['a']}|{edge['b']}", "length_m": edge["length_m"]}

    # 2. heights and the slope from Section Y-Y; the shared edge's answer ------------------------------
    sec = "Section Y-Y"
    _ok(c.post(f"/api/measure/areas/{areas['A']['id']}/height", json={"section": sec, "top": "+1800", "bottom": "+600"}, headers=hb), "height A")
    _ok(c.post(f"/api/measure/areas/{areas['R']['id']}/height", json={"section": sec, "top": "+600", "bottom": "-900"}, headers=hb), "height R")
    _ok(c.post(f"/api/measure/areas/{areas['Q']['id']}/slope", json={"section": sec, "top": "+2250", "bottom": "+1800", "run_mm": "1051", "run_source": "Section Y-Y dimension"}, headers=hb), "slope Q")
    _ok(c.post(f"/api/measure/edges/{edge['id']}/answer", json={"answer": "weir", "weir_mm": "450"}, headers=hb), "edge")
    # 3. how each order item is measured ----------------------------------------------------------------
    wl = {w.item_no: w.id for w in wo.lines}
    _ok(c.put(f"{base}/items/{wl['1']}", json={"parts": ["floor", "walls", "tops", "slope"]}, headers=hb), "item 1")
    _ok(c.put(f"{base}/items/{wl['2']}", json={"parts": ["count"], "count_of": "layer:SLEEVE"}, headers=hb), "item 2")
    _ok(c.put(f"{base}/items/{wl['3']}", json={"parts": ["floor"], "layers": 2, "areas": [areas["A"]["id"], areas["R"]["id"]]}, headers=hb), "item 3")

    # the client's billing person in the portal
    from app.masters.models import Client

    client_id = db.scalar(select(Client.id).where(Client.name == CLIENT))
    _ok(c.put(f"/api/portal-admin/sites/{site.id}", json={"visible": True, "sections": {}}, headers=hd), "portal")
    name, email = CLIENT_USER
    u = db.scalar(select(User).where(User.email == email))
    if u is not None and db.get(ClientUser, (u.id, client_id)) is None:
        db.add(ClientUser(user_id=u.id, client_id=client_id, roles=["billing"]))
        db.commit()
    r = _ok(c.post("/api/portal-admin/invites", json={"full_name": name, "email": email, "client_id": client_id, "site_ids": [site.id], "roles": ["billing"]}, headers=hd), "invite", 201)
    _ok(c.post(f"/api/portal/invite/{r['link'].rsplit('/', 1)[1]}", json={"password": _password()}), "invite accept")
    u = db.scalar(select(User).where(User.email == email))
    u.is_demo = True
    db.commit()
    pb = _login(c, email)

    def approve_all(sheet: dict, correct: tuple | None = None) -> list:
        book = [m for m in _ok(c.get(f"/api/portal/sites/{site.id}/measurements", headers=pb), "portal book") if (m.get("description") or "").startswith(sheet["code"])]
        logged = []
        for m in book:
            if correct and correct[0] in m["description"]:
                ch = _ok(c.post(f"/api/portal/sites/{site.id}/measurements/{m['id']}/correct", json={"field": "qty", "new_value": correct[1], "remark": correct[2]}, headers=pb), "correct")["changes"][0]
                _ok(c.post(f"/api/closeout/measurement-changes/{ch['id']}/answer", json={"accept": True}, headers=hb), "accept correction")
                logged.append(ch)
            else:
                _ok(c.post(f"/api/portal/sites/{site.id}/measurements/{m['id']}/approve", headers=pb), "approve")
        return logged

    # 4. sheet 1: A and Q (R, and brick bat's second layer, not done yet) --------------------------------
    d1 = date.today() - timedelta(days=30)
    s1 = _ok(c.post(f"{base}/sheets", json={"measured_on": d1.isoformat(), "title": "Pool and slope"}, headers=hb), "sheet 1", 201)
    for wid, layer in ((wl["1"], 1), (wl["2"], 1), (wl["3"], 1), (wl["3"], 2)):
        _ok(c.post(f"/api/measure/sheets/{s1['id']}/not-done", json={"area_id": areas["R"]["id"], "wo_line_id": wid, "layer": layer}, headers=hb), "not done")
    s1 = _ok(c.post(f"/api/measure/sheets/{s1['id']}/not-done", json={"area_id": areas["A"]["id"], "wo_line_id": wl["3"], "layer": 2}, headers=hb), "not done")
    s1 = _ok(c.post(f"/api/measure/sheets/{s1['id']}/send", headers=hb), "send 1")
    approve_all(s1)
    s1 = _ok(c.get(f"/api/measure/sheets/{s1['id']}", headers=hb), "sheet 1")
    b1 = _ok(c.post(f"/api/measure/sheets/{s1['id']}/bill", json={"proforma_on": (d1 + timedelta(days=2)).isoformat()}, headers=hb), "RA 1", 201)
    _ok(c.post(f"/api/finance/ra-bills/{b1['id']}/submit", headers=hb), "submit RA 1")
    inv = _ok(c.post(f"/api/measure/bills/{b1['id']}/tax-invoice", json={"invoice_date": (d1 + timedelta(days=5)).isoformat()}, headers=hb), "tax invoice", 201)

    # 5. sheet 2: the rest; the client corrects the sleeves (one was not fixed yet) ---------------------
    d2 = date.today() - timedelta(days=3)
    s2 = _ok(c.post(f"{base}/sheets", json={"measured_on": d2.isoformat(), "title": "Balancing tank, second layer"}, headers=hb), "sheet 2", 201)
    s2 = _ok(c.post(f"/api/measure/sheets/{s2['id']}/send", headers=hb), "send 2")
    corr = approve_all(s2, ("Pipe sleeve", "1", "One sleeve in the tank is not fixed yet: 1 No this bill"))
    s2 = _ok(c.get(f"/api/measure/sheets/{s2['id']}", headers=hb), "sheet 2")
    b2 = _ok(c.post(f"/api/measure/sheets/{s2['id']}/bill", json={"proforma_on": (d2 - timedelta(days=1)).isoformat()}, headers=hb), "RA 2", 201)
    if not s1["cumulative"] or not s2["cumulative"]:
        raise Step("no cumulative quantities")
    out["sheets"] = {s["code"]: {"status": s["status"], "this": {r["item_no"]: r["this"] for r in s["cumulative"]}, "previous": {r["item_no"]: r["previous"] for r in s["cumulative"]}}
                     for s in (s1, s2)}  # fmt: skip
    out["corrections"] = [(x["field"], str(x.get("old_value") or x.get("old_shown")), str(x.get("new_value") or x.get("new_shown")), x.get("remark")) for x in corr]
    out["bills"] = {b["code"]: {"proforma": b["proforma_no"], "basic": b["tax"]["taxable"], "cgst": b["tax"]["cgst"], "sgst": b["tax"]["sgst"], "round_off": b["tax"]["round_off"],
                                "grand": b["tax"]["total"], "warnings": b["warnings"], "checklist_ok": all(x["ok"] for x in b["checklist"])} for b in (b1, b2)}  # fmt: skip
    out["tax_invoice"] = {"number": inv["number"], "total": inv["total"]}
    out["drawing"] = fid
    return out
