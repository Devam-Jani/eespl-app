# ruff: noqa: E501
"""DEMO (marked demo, demo users only): the consumption library and a terrace estimated from its
measured drawing.

The library: the Technonicol products of the planning files (SBR Latex, Ultracem GR 60, Epoxy
Primer 021, Ultrathane, Ultrathane Logic Foam, Ultracem 2C, 45 gsm fibre mesh, 120 gsm geotextile,
Cemguard Plus, Cemkrete, Cemcrystal) with coverages checked against the planning sheets and the
makers' data sheets ("to confirm" where no data sheet states it), their wastage and pack sizes; the civil materials of the mixes (nodular, cement, sand,
Technomix WL); three mix designs: nodular concrete 1:1:4, cement-sand plaster 1:4, brick bat coba.

The nodular mix is fitted to the planning team's own figures (3.52 kg/sqft of nodular and of
cement at 165 mm, sand × 4, 2.77 kg/sqft at 130 mm): at 1,440 kg/m³ that is a dry-volume factor
of 0.9568, i.e. the mix is worked by weight at about 1,378 kg/m³ of screed. A textbook dry factor
(1.54) would give 5.66 kg/sqft; the factor is marked "to confirm" for planning to settle.

The terrace (DEMO-TERRACE, made-up names): upper terrace with two shafts, middle and lower
terraces, the lift-machine-room top, a 165 mm nodular screed, PU coating with its primer, fibre
mesh at the corners and a geotextile. The drawing is made here; billing clicks the areas; planning
makes the estimate; a canopy measured afterwards is left out, so the missed-area warning shows.
One BOQ (a tender) with its rate working (the PU line over the 70% material share; cement and
sand free issue; one T&C clause with the wrong "by us at free of cost" wording); one site request
(nodular, 280 sqm, 130 mm) and the indent planning approves it into.

    docker compose exec api python -m app.cli demo-estimate
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.closeout.demo import _login, _ok, _password, _purge
from app.timefmt import ist_today

D = Decimal
SITE_CODE = "DEMO-TERRACE"
SITE_NAME = "DEMO Residency terraces"
CLIENT = "DEMO Residency Developers (demo client)"

# name, unit, pack size, pack unit, wastage %, coverage, min, max, coverage unit, source, note.
# Checked (Prompt 34 review) against the planning team's sheets and the makers' data sheets: "tds"
# only where the product's own data sheet states the figure; the rest stay "to confirm".
TDS = "Maker's data sheet"
PRODUCTS = [
    ("SBR Latex", "ltr", "20", "can", "5", "0.25", "0.2", "0.3", "L/sqm", "to_confirm", "Data sheet: bond coat 200-300 g/sqm (in grams; the litres take a density of about 1, to confirm)"),
    ("Ultracem GR 60", "kg", "25", "bag", "5", "2", "1.8", "2.2", "kg/sqm", "to_confirm", "A grout: the data sheet gives 1,800-2,000 kg per m³ and the sheets price it per sleeve; no per-sqm figure, to confirm"),
    ("Epoxy Primer 021", "kg", "20", "set", "5", "0.2", "0.1", "0.25", "kg/sqm", "tds", f"{TDS}: 100-250 g/sqm (the Dholera sheet books 0.3)"),
    ("Ultrathane", "kg", "20", "drum", "5", "2", "2", "2.5", "kg/sqm", "tds", f"{TDS}: 2,000-2,500 g/sqm (the Dholera sheet's 1.2 is below it)"),
    ("Ultrathane Logic Foam", "kg", "1", "can", "10", "0.65", "0.55", "0.7", "kg/sqm", "to_confirm", "At 10 mm: the Dholera sheet's 0.65; the data sheet gives only the density (55-60 kg/m³)"),
    ("Ultracem 2C", "kg", "30", "set", "5", "3", "1.6", "3.5", "kg/sqm", "tds", f"{TDS}: 3 kg/sqm, as the Dholera sheets; the method statement's sunken areas 2 coats × 0.8 = 1.6"),
    ("45 gsm fibre mesh", "sqm", "50", "roll", "5", "1.05", "1", "1.1", "sqm/sqm", "to_confirm", "The sheets' 1.05 for the laps (the 5% wastage is the cut-offs); no data sheet"),
    ("120 gsm geotextile", "sqm", "100", "roll", "5", "1.05", "1.05", "1.1", "sqm/sqm", "to_confirm", "The sheets' 1.05 (50 mm laps); no data sheet"),
    ("Cemguard Plus", "kg", "20", "bag", "5", "1.75", "1.5", "2", "kg/sqm", "tds", f"{TDS}: a 12 kg kit covers 6-8 sqm at 1.5 mm in 2 coats"),
    ("Cemkrete", "kg", "25", "bag", "5", "0.4", "0.35", "0.5", "kg/sqm", "to_confirm", "The sheets' 0.35-0.4 (the liquid, for patching); the data sheet gives no coverage"),
    ("Cemcrystal", "kg", "25", "bag", "5", "1", "0.5", "1.5", "kg/sqm", "to_confirm", "The Cemcrystal Plus data sheet: 0.5-1.5 by use (the sheets 1.1-1.5); plain Cemcrystal's to confirm"),
]
CIVIL = [("Nodular", "kg", "25", "bag"), ("Cement", "kg", "50", "bag"), ("Sand", "kg", None, None), ("Technomix WL", "ltr", "1", "bottle"),
         ("Brick bats", "kg", None, None)]  # fmt: skip
PRICES = {"Ultrathane": "480", "Epoxy Primer 021": "350", "45 gsm fibre mesh": "18", "120 gsm geotextile": "28", "Nodular": "10", "Cement": "8", "Sand": "1.2", "SBR Latex": "190"}


def _code(name: str) -> str:
    return "DEMO-" + "".join(ch if ch.isalnum() else "-" for ch in name.upper()).strip("-")[:40]


def library(db: Session) -> dict:
    """The DEMO products, coverages and mix designs (rerun: kept, figures reset)."""
    from app.estimate.models import Coverage, MixDesign  # noqa: PLC0415

    ids: dict[str, int] = {}
    for name, unit, pack, pack_unit, w, val, lo, hi, cu, src, note in PRODUCTS:
        p = _product(db, name, unit, pack, pack_unit, brand="Technonicol")
        p.wastage_percent = D(w)
        c = db.scalar(select(Coverage).where(Coverage.product_id == p.id, Coverage.system_id.is_(None)))
        if c is None:
            c = Coverage(product_id=p.id, system_id=None, value=D(val))
            db.add(c)
        c.value, c.min_value, c.max_value, c.unit, c.source, c.note, c.is_demo = D(val), D(lo), D(hi), cu, src, f"DEMO: {note}", True
        ids[name] = p.id
    for name, unit, pack, pack_unit in CIVIL:
        p = _product(db, name, unit, pack, pack_unit, brand=None)
        p.wastage_percent = D(0)
        ids[name] = p.id
    db.flush()
    mixes = [
        ("DEMO-NODULAR-114", "Nodular concrete 1:1:4", "nodular", "165", "0.9568", [("nodular", "Nodular", 1, 1440), ("cement", "Cement", 1, 1440), ("sand", "Sand", 4, 1440)],
         "SBR Latex", "0.5", 2, "Fitted to the planning sheet (3.52 kg/sqft at 165 mm, 2.77 at 130 mm): by weight at about 1,378 kg/m³. To confirm."),
        ("DEMO-PLASTER-14", "Cement-sand plaster 1:4", "plaster", "20", "1.27", [("cement", "Cement", 1, 1440), ("sand", "Sand", 4, 1600)],
         "Technomix WL", "0.2", None, "Technomix WL 200 ml per 50 kg bag of cement (the spec's dose). Dry-volume factor to confirm."),
        ("DEMO-BRICKBAT", "Brick bat coba in 1:4 mortar", "brick_bat", "100", "1.33", [("brick bats", "Brick bats", 4, 1600), ("cement", "Cement", 1, 1440), ("sand", "Sand", 4, 1600)],
         "Technomix WL", "0.2", None, "DEMO proportions: to confirm."),
    ]  # fmt: skip
    for code, name, kind, t, dvf, comps, adm, dose, rnd, note in mixes:
        m = db.scalar(select(MixDesign).where(MixDesign.code == code))
        if m is None:
            m = MixDesign(code=code, name=name, thickness_mm=D(t), dry_volume_factor=D(dvf))
            db.add(m)
        m.name, m.kind, m.thickness_mm, m.dry_volume_factor, m.round_sqft, m.note, m.is_demo, m.source = name, kind, D(t), D(dvf), rnd, note, True, "to_confirm"
        m.components = [{"role": role, "product_id": ids[prod], "parts": parts, "density": dens} for role, prod, parts, dens in comps]
        m.admixture_product_id, m.admixture_per_bag, m.cement_bag_kg = ids[adm], D(dose), D(50)
    db.flush()
    return ids


def _product(db: Session, name: str, unit: str, pack, pack_unit, brand):
    from app.masters.models import Product  # noqa: PLC0415

    p = db.scalar(select(Product).where(Product.code == _code(name)))
    if p is None:
        p = Product(code=_code(name), name=name, unit=unit, brand=brand, is_demo=True)
        db.add(p)
    p.name, p.unit, p.brand, p.is_demo = name, unit, brand, True
    p.pack_size, p.pack_unit = (D(pack), pack_unit) if pack else (None, None)
    db.flush()
    return p


# --- the drawing: the terraces in millimetres ------------------------------------------------------

AREAS = [  # code, name, x, y, w, h (m); the shafts are inside the upper terrace
    ("UT", "Upper terrace", 0, 0, 24, 14),
    ("S1", "Duct shaft 1", 3, 3, 2, 1.5),
    ("S2", "Duct shaft 2", 17, 9, 1.5, 1.2),
    ("MT", "Middle terrace", 28, 0, 15, 10),
    ("LT", "Lower terrace", 0, -12, 25, 8),
    ("LMR", "Lift machine room top", 46, 0, 5, 4),
]
LEFT_OUT = ("CN", "Staircase canopy", 30, -12, 5.45, 5.5028)  # 29.99 sqm, measured after the estimate


def dxf(path: Path) -> None:
    import ezdxf  # noqa: PLC0415

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("TERRACE", color=5)
    doc.layers.add("TEXT", color=2)
    for code, name, x, y, w, h in [*AREAS, LEFT_OUT]:
        pts = [(x * 1000, y * 1000), ((x + w) * 1000, y * 1000), ((x + w) * 1000, (y + h) * 1000), (x * 1000, (y + h) * 1000)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "TERRACE"})
        msp.add_text(f"{code} {name.upper()}", height=200, dxfattribs={"layer": "TEXT", "insert": (x * 1000 + 300, (y + h) * 1000 - 500)})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def _click(code: str) -> tuple[float, float]:
    _c, _n, x, y, w, h = next(a for a in [*AREAS, LEFT_OUT] if a[0] == code)
    if code == "UT":  # away from the shafts
        return x + 10.0, y + 1.0
    return x + w / 2, y + h / 2


def reset(db: Session, site_id: int) -> int:
    n = 0
    for table in ("material_requests", "estimates", "measure_areas", "drawings"):
        ids = list(db.scalars(text(f'select id from "{table}" where site_id = :s'), {"s": site_id}))
        n += _purge(db, table, ids, set())
    db.flush()
    return n


def run(db: Session) -> dict:
    import app.main as main  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415
    from app.costing.models import (  # noqa: PLC0415
        RateGroup,
        RateGroupLine,
        RateGroupProduct,
        RateWorking,
    )
    from app.masters.models import Client, Product, ProductPrice, System  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415
    from app.sites.models import Drawing, DrawingRevision, Site, SiteMember  # noqa: PLC0415
    from app.takeoff import pipeline  # noqa: PLC0415
    from app.takeoff.models import CadFile  # noqa: PLC0415
    from app.team.demo import email_for  # noqa: PLC0415
    from app.tenders.models import BoqLine, BoqSection, Tender, TenderTc  # noqa: PLC0415

    roles = ("billing", "director", "planning", "site_engineer")
    users = {r: db.scalar(select(User.id).where(User.email == email_for(r))) for r in roles}
    if not all(users.values()):
        raise SystemExit("Run seed-demo-team first (the DEMO users).")
    _password()
    ids = library(db)
    pu = db.scalar(select(System).where(System.code == "DEMO-PU-TERRACE"))
    if pu is None:
        pu = System(code="DEMO-PU-TERRACE", name="DEMO PU terrace coating with primer", unit="sqm")
        db.add(pu)
    pu.upturn_mm, pu.note = D(300), "DEMO"
    screed = db.scalar(select(System).where(System.code == "DEMO-NODULAR-SCREED"))
    if screed is None:
        screed = System(code="DEMO-NODULAR-SCREED", name="DEMO nodular screed with SBR latex", unit="sqm")
        db.add(screed)
    screed.upturn_mm, screed.note = D(0), "DEMO: a screed has no upturn"
    db.flush()
    from app.estimate.models import Coverage  # noqa: PLC0415

    for prod, val, cu in (("Nodular", "3.52", "kg/sqft"), ("Cement", "3.52", "kg/sqft"), ("Sand", "14.08", "kg/sqft"), ("SBR Latex", "0.38", "L/sqm")):
        c = db.scalar(select(Coverage).where(Coverage.product_id == ids[prod], Coverage.system_id == screed.id))
        if c is None:
            c = Coverage(product_id=ids[prod], system_id=screed.id, value=D(val))
            db.add(c)
        c.value, c.min_value, c.max_value, c.unit, c.source, c.note, c.is_demo = D(val), None, None, cu, "to_confirm", "DEMO: the nodular mix at 165 mm", True
    for name, rate in PRICES.items():
        for old in db.scalars(select(ProductPrice).where(ProductPrice.product_id == ids[name], ProductPrice.note == "DEMO price")):
            db.delete(old)
        db.add(ProductPrice(product_id=ids[name], purchase_rate=D(rate), effective_from=ist_today() - timedelta(days=30), source="manual", note="DEMO price"))
    cl = db.scalar(select(Client).where(Client.name == CLIENT))
    if cl is None:
        cl = Client(name=CLIENT, type="other", notes="DEMO: invented")
        db.add(cl)
    cl.is_demo = True
    db.flush()
    site = db.scalar(select(Site).where(Site.code == SITE_CODE))
    removed = 0
    if site is None:
        site = Site(code=SITE_CODE, name=SITE_NAME, city="Ahmedabad", state="Gujarat", status="active", is_demo=True, start_date=ist_today() - timedelta(days=20))
        db.add(site)
        db.flush()
    else:
        removed = reset(db, site.id)
    site.client_id = cl.id
    for r, uid in users.items():
        if not db.scalar(select(SiteMember.site_id).where(SiteMember.site_id == site.id, SiteMember.user_id == uid)):
            db.add(SiteMember(site_id=site.id, user_id=uid, role_on_site="incharge" if r == "site_engineer" else "office"))
    db.commit()

    rel = f"sites/{site.id}/drawings/DEMO-terrace-plan-r1.dxf"
    dst = Path(settings.media_dir) / rel
    dxf(dst)
    d = Drawing(site_id=site.id, title="DEMO Terraces: roof plan", discipline="architectural", created_by=users["billing"])
    db.add(d)
    db.flush()
    rv = DrawingRevision(drawing_id=d.id, rev_no=1, stored_path=rel, filename=dst.name, size_bytes=dst.stat().st_size, created_by=users["billing"])
    db.add(rv)
    db.flush()
    d.current_revision_id = rv.id
    f = CadFile(revision_id=rv.id, drawing_id=d.id, site_id=site.id, status="queued", created_by=users["billing"])
    db.add(f)
    db.commit()
    f = pipeline.process(db, f)
    if f.status != "ready":
        raise SystemExit(f"The drawing was not read: {f.error}")

    c = TestClient(main.app)
    H = {r: _login(c, email_for(r)) for r in roles}
    out: dict = {"site": f"{site.code} {site.name}", "removed_rows": removed}
    for code, name, *_ in AREAS:
        x, y = _click(code)
        _ok(c.post(f"/api/measure/sites/{site.id}/areas", json={"cad_file_id": f.id, "x": x, "y": y, "code": code, "name": name}, headers=H["billing"]), f"area {code}", 201)

    # the estimate: every measured area, the materials from the library and the nodular mix
    hp = H["planning"]
    e = _ok(c.post("/api/estimate/estimates", json={"site_id": site.id, "title": "Terrace waterproofing and screed"}, headers=hp), "estimate", 201)
    from app.estimate.models import MixDesign  # noqa: PLC0415

    nod = db.scalar(select(MixDesign.id).where(MixDesign.code == "DEMO-NODULAR-114"))
    for prod in ("Nodular", "Cement", "Sand", "SBR Latex"):
        e = _ok(c.post(f"/api/estimate/estimates/{e['id']}/lines", json={"product_id": ids[prod], "system_id": screed.id, "mix_design_id": nod, "thickness_mm": "165", "part": "floor"}, headers=hp), f"line {prod}", 201)
    for prod, part in (("Epoxy Primer 021", "both"), ("Ultrathane", "both"), ("45 gsm fibre mesh", "upturn"), ("120 gsm geotextile", "floor")):
        e = _ok(c.post(f"/api/estimate/estimates/{e['id']}/lines", json={"product_id": ids[prod], "system_id": pu.id, "part": part}, headers=hp), f"line {prod}", 201)
    # a canopy measured after the estimate was made: in no estimate, not excluded
    x, y = _click("CN")
    _ok(c.post(f"/api/measure/sites/{site.id}/areas", json={"cad_file_id": f.id, "x": x, "y": y, "code": "CN", "name": LEFT_OUT[1]}, headers=H["billing"]), "canopy", 201)
    e = _ok(c.get(f"/api/estimate/estimates/{e['id']}", headers=hp), "estimate")
    out["estimate"] = {"code": e["code"], "areas": [(a["code"], a["name"], a["floor_sqm"], a["deduction_sqm"], a["periphery_m"]) for a in e["areas"]],
                       "lines": [(ln["product"], ln["coverage"], ln["wastage_percent"], ln["qty"], ln["packs"]) for ln in e["lines"]], "warnings": e["warnings"]}  # fmt: skip

    # the BOQ (a tender) and its rate working: the margin check
    t = db.scalar(select(Tender).where(Tender.code == f"T-DEMO-TER-{site.id}"))
    if t is not None:
        db.delete(t)
        db.flush()
    t = Tender(code=f"T-DEMO-TER-{site.id}", name="DEMO Residency terraces: waterproofing", status="draft", client_id=cl.id, guarantee_years=10, site_name=SITE_NAME,
               site_city="Ahmedabad", site_state="Gujarat", is_demo=True, notes="DEMO: invented")  # fmt: skip
    db.add(t)
    db.flush()
    sec = BoqSection(tender_id=t.id, title="Terraces", sort_order=1)
    db.add(sec)
    db.flush()
    boq = [("i", "Nodular concrete screed 165 mm average with SBR latex at 0.38 L/sqm, cement and sand by the client", "650", screed),
           ("ii", "PU waterproofing: Epoxy Primer 021 at 0.2 kg/sqm and Ultrathane at 1.8-1.9 kg/sqm, fibre mesh at the corners", "1072", pu),
           ("iii", "120 gsm geotextile separation layer over the coating", "65", pu)]  # fmt: skip
    lines = []
    for i, (no, desc, rate, sys) in enumerate(boq):
        b = BoqLine(tender_id=t.id, section_id=sec.id, sort_order=i + 1, client_item_no=no, unit="sqm", qty=D(560), description=desc, rate=D(rate), system_id=sys.id)
        db.add(b)
        lines.append(b)
    db.add(TenderTc(tender_id=t.id, sort_order=0, text_override="Cement, sand and water shall be provided by us at free of cost."))
    db.flush()
    w = RateWorking(tender_id=t.id, rev_no=0, free_issue_product_ids=sorted([ids["Cement"], ids["Sand"]]))
    db.add(w)
    db.flush()
    groups = [("Nodular screed", screed, "650", ["Nodular", "Cement", "Sand", "SBR Latex"], "4"), ("PU coating", pu, "1072", ["Epoxy Primer 021", "Ultrathane"], None),
              ("Geotextile", pu, "65", ["120 gsm geotextile"], "1.5")]  # fmt: skip
    for n, (name, sys, rate, prods, lab) in enumerate(groups):
        g = RateGroup(working_id=w.id, sort_order=n, name=name, system_id=sys.id, rate_sqm=D(rate), labour_used_sqft=D(lab) if lab else D(0))
        db.add(g)
        db.flush()
        for k, prod in enumerate(prods):
            db.add(RateGroupProduct(group_id=g.id, product_id=ids[prod], sort_order=k))
        db.add(RateGroupLine(group_id=g.id, boq_line_id=lines[n].id))
    db.commit()
    hd = H["director"]
    m = _ok(c.get(f"/api/estimate/margin?tender_id={t.id}", headers=hd), "margin")
    out["margin"] = [(r["item"], r["rate_sqm"], r["material_sqm"], r.get("material_share_percent"), r.get("margin_percent"), r["warnings"]) for r in m["lines"]]
    out["tender_checks"] = _ok(c.get(f"/api/estimate/checks?tender_id={t.id}", headers=hd), "checks")

    # the site's request (nodular, 280 sqm of the upper terrace, 130 mm) and planning's indent
    est = _ok(c.get(f"/api/estimate/estimates/{e['id']}", headers=hp), "estimate")
    ut = next(a for a in est["areas"] if a["code"] == "UT")
    r = _ok(c.post("/api/estimate/requests", json={"site_id": site.id, "product_id": ids["Nodular"], "area_sqm": "280", "thickness_mm": "130", "mix_design_id": nod,
                                                    "estimate_area_id": ut["id"]}, headers=H["site_engineer"]), "request")  # fmt: skip
    r = _ok(c.post(f"/api/estimate/requests/{r['id']}/decide", json={"approve": True}, headers=hp), "approve")
    out["request"] = {"code": r["code"], "formula": r["formula"], "indent": r["indent"]}
    db.commit()
    out["product"] = {p.name: str(p.id) for p in db.scalars(select(Product).where(Product.id.in_(list(ids.values()))))}
    return out
