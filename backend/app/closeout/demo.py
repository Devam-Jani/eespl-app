# ruff: noqa: E501
"""DEMO (marked demo, demo users only) on the DEMO Shela site: a tender quoted to three civil
contractors, one wins the main job and we win our stage as L1; the work order with three
deviations, resolved and locked; a client billing user correcting two measurement lines; the
billing checklist of one tower with four flats; a bill tracked to "with the client's accounts"
and overdue by 6 days; the work completion certificate with the marked plan and a 10-year
guarantee; three issues (material late, product discontinued, leakage under the guarantee).

Every step goes through the API as the DEMO user of the role that does it (password from
DEMO_USER_PASSWORD, never printed). A rerun first removes what the previous run made.

    docker compose exec api python -m app.cli demo-closeout
"""

import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.closeout.common import IST
from app.config import settings

SITE = "DEMO Shela"
TENDER = "DEMO Shela Residency tower A (three civil contractors)"
DEVELOPER = "DEMO Shela Developers (demo client)"
CONTRACTORS = ["DEMO Civil Contractor Alpha", "DEMO Civil Contractor Beta", "DEMO Civil Contractor Gamma"]
WINNER = "DEMO Civil Contractor Beta"
PRODUCT = "DEMO FLEXCOAT (demo product)"
SYSTEM = "DEMO-SYS-FLEX"
CLIENT_USERS = {  # invented portal users of the winning contractor (roles, never real names)
    "billing": ("DEMO Client Billing Engineer", "demo-client-billing@example.com"),
    "project_manager": ("DEMO Client Project Manager", "demo-client-pm@example.com"),
    "accounts": ("DEMO Client Accounts", "demo-client-accounts@example.com"),
}
FLATS = ["101", "102", "103", "104"]


class Step(Exception):
    pass


def _ok(r, what: str, code: int = 200):
    if r.status_code not in (code, 200, 201):
        raise Step(f"{what}: {r.status_code} {r.text[:400]}")
    return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r


def _password() -> str:
    secret = settings.demo_user_password
    pw = secret.get_secret_value() if secret else ""
    if not pw:
        raise SystemExit("Set DEMO_USER_PASSWORD in .env and run seed-demo-team first.")
    return pw


def _login(c: TestClient, email: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "password": _password()})
    if r.status_code != 200:
        raise Step(f"login {email}: {r.status_code} (run seed-demo-team first)")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- remove the previous run (only what this demo made) ----------------------------------------------


_FK: dict[str, list[tuple[str, str]]] = {}
_IDS: set[str] = set()


def _load_fk(db: Session) -> None:
    """Every single-column foreign key to an id, once (child table, column) by parent table."""
    if _FK:
        return
    for parent, child, col in db.execute(text("""
        select pc.relname, cc.relname, a.attname from pg_constraint c
        join pg_class pc on pc.oid = c.confrelid join pg_class cc on cc.oid = c.conrelid
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
        join pg_namespace n on n.oid = cc.relnamespace
        where c.contype = 'f' and n.nspname = 'public' and array_length(c.conkey, 1) = 1""")):
        _FK.setdefault(parent, []).append((child, col))
    _IDS.update(db.scalars(text("select table_name from information_schema.columns where table_schema = 'public' and column_name = 'id'")))


def _children(db: Session, table: str) -> list[tuple[str, str]]:
    _load_fk(db)
    return _FK.get(table, [])


def _has_id(db: Session, table: str) -> bool:
    _load_fk(db)
    return table in _IDS


KEEP = {"sites", "site_members", "users", "roles", "clients", "products", "systems", "audit_log"}


def _purge(db: Session, table: str, ids: list, seen: set) -> int:
    """Delete these rows and, first, every row below them (downwards through foreign keys only)."""
    if not ids:
        return 0
    n = 0
    for child, col in _children(db, table):
        if child in KEEP or (child, col) in seen:
            continue
        if _has_id(db, child):
            sub = list(db.scalars(text(f'select id from "{child}" where "{col}" = any(:ids)'), {"ids": ids}))
            n += _purge(db, child, sub, seen | {(child, col)})
        else:
            n += db.execute(text(f'delete from "{child}" where "{col}" = any(:ids)'), {"ids": ids}).rowcount
    n += db.execute(text(f'delete from "{table}" where id = any(:ids)'), {"ids": ids}).rowcount
    return n


def reset(db: Session, site_id: int) -> int:
    """The rows the previous run made: on the DEMO site (its nodes, contract, bills, work orders,
    measurements, zones, completions, issues), the demo tender with its quotations, and the demo
    clients' cycles and portal users' links. The site, its members and the other demos stay."""
    from app.masters.models import Client, Product, System
    from app.sites.models import Site
    from app.tenders.models import Tender

    site = db.get(Site, site_id)
    site.client_id = site.tender_id = None
    db.flush()
    n = 0
    store = db.scalar(text("select id from stores where site_id = :s"), {"s": site_id})
    if store:
        moved = list(db.scalars(text("select id from transfers where from_store_id = :st or to_store_id = :st"), {"st": store}))
        n += db.execute(text("delete from stock_ledger where store_id = :st or (ref_type in ('transfer_out', 'transfer_in') and ref_id = any(:t))"), {"st": store, "t": moved}).rowcount
        n += _purge(db, "transfers", moved, set())
    n += _purge(db, "site_issues", list(db.scalars(text("select id from site_issues where site_id = :s"), {"s": site_id})), set())
    for table in ("issue_log", "work_completions", "labour_claims", "rfi_zones", "measurement_sets", "measurements", "tax_invoices", "ra_bills",
                  "client_contracts", "client_work_orders", "client_billing_cycles", "tasks", "area_scopes", "drawings", "site_nodes"):  # fmt: skip
        ids = list(db.scalars(text(f'select id from "{table}" where site_id = :s'), {"s": site_id}))
        n += _purge(db, table, ids, set())
    # this demo's process events and notices on the site (the other demos' stay)
    kinds = ("labour_claim_above", "labour_claim_decided", "handover_moved", "wo_amend", "bill_not_submitted", "bill_stuck", "bill_stuck_long", "payment_due", "payment_overdue", "payment_overdue_long", "payment_promised", "issue_raised", "issue_overdue", "job_won")
    n += db.execute(text("delete from notifications where site_id = :s and (kind = 'bill_overdue' or rule_code = any(:k) or event_id in (select id from process_events where site_id = :s and type = any(:k)))"), {"s": site_id, "k": list(kinds)}).rowcount
    n += db.execute(text("delete from process_events where site_id = :s and type = any(:k)"), {"s": site_id, "k": list(kinds)}).rowcount
    t = db.scalar(select(Tender.id).where(Tender.name == TENDER, Tender.is_demo))
    if t:
        n += _purge(db, "client_work_orders", list(db.scalars(text("select id from client_work_orders where tender_id = :t"), {"t": t})), set())
        n += _purge(db, "quotations", list(db.scalars(text("select id from quotations where tender_id = :t"), {"t": t})), set())
        n += _purge(db, "tenders", [t], set())
    clients = list(db.scalars(select(Client.id).where(Client.name.in_([DEVELOPER, *CONTRACTORS]), Client.is_demo)))
    for table, col in (("client_billing_cycles", "client_id"), ("quotations", "client_id")):
        n += _purge(db, table, list(db.scalars(text(f'select id from "{table}" where "{col}" = any(:c)'), {"c": clients})), set())
    p = db.scalar(select(Product.id).where(Product.name == PRODUCT, Product.is_demo))
    if p:
        n += _purge(db, "issue_log", list(db.scalars(text("select id from issue_log where product_id = :p"), {"p": p})), set())
        db.execute(text("update products set discontinued_on = null where id = :p"), {"p": p})
    for sysid in db.scalars(select(System.id).where(System.code.in_((SYSTEM, "DEMO-SYS-PU")))):
        db.execute(text("update boq_lines set system_id = null where system_id = :s and tender_id in (select id from tenders where is_demo)"), {"s": sysid})
    db.flush()
    return n


# --- the masters this demo needs -----------------------------------------------------------------------

PU_PRODUCT = "DEMO PU COAT (demo product)"
PU_SYSTEM = "DEMO-SYS-PU"
TOILET_TEMPLATE = "DEMO toilet acrylic coating (demo)"
BALCONY_TEMPLATE = "DEMO balcony PU coating (demo)"
STAGES = ["Surface preparation", "Primer", "Coat 1 with mesh", "Coat 2", "Pond test"]


def _masters(db: Session) -> dict:
    from app.masters.models import Client, Product, System, SystemComponent
    from app.sites.models import StageTemplate, StageTemplateStep

    out = {}
    for name in (DEVELOPER, *CONTRACTORS):
        c = db.scalar(select(Client).where(Client.name == name))
        if c is None:
            c = Client(name=name, type="builder", city="Ahmedabad", state="Gujarat", address="DEMO address, Shela, Ahmedabad", notes="DEMO: invented")
            db.add(c)
        c.is_demo = True
        db.flush()
        out[name] = c.id
    for key, code, name, unit, sys_code, sys_name, cons in (
        ("product", "DEMO-FLEXCOAT", PRODUCT, "kg", SYSTEM, "DEMO acrylic flexible coating with 45 GSM mesh (demo)", "1.2"),
        ("pu_product", "DEMO-PUCOAT", PU_PRODUCT, "kg", PU_SYSTEM, "DEMO PU coating for balconies (demo)", "1.5"),
    ):
        p = db.scalar(select(Product).where(Product.name == name))
        if p is None:
            p = Product(code=code, name=name, unit=unit)
            db.add(p)
        p.is_demo, p.discontinued_on = True, None
        db.flush()
        s = db.scalar(select(System).where(System.code == sys_code))
        if s is None:
            s = System(code=sys_code, name=sys_name, unit="sqm")
            db.add(s)
            db.flush()
            db.add(SystemComponent(system_id=s.id, product_id=p.id, consumption_per_unit=Decimal(cons), wastage_percent=Decimal("5"), coats=2))
        db.flush()
        out[key], out[key.replace("product", "system")] = p.id, s.id
    for key, name, sys_key in (("toilet_template", TOILET_TEMPLATE, "system"), ("balcony_template", BALCONY_TEMPLATE, "pu_system")):
        tpl = db.scalar(select(StageTemplate).where(StageTemplate.name == name))
        if tpl is None:
            tpl = StageTemplate(name=name, system_id=out[sys_key])
            db.add(tpl)
            db.flush()
            for i, (step, w) in enumerate(zip(STAGES, (10, 10, 25, 25, 30), strict=True)):
                db.add(StageTemplateStep(template_id=tpl.id, sort_order=i, name=step, weight_percent=Decimal(w), needs_inspection=True, hold_point=step == "Pond test"))
            db.flush()
        out[key] = tpl.id
    return out


def _file(name: str, body: bytes, kind: str = "application/pdf"):
    return {"file": (name, body, kind)}


SIGNED = b"%PDF-1.4\n% DEMO signed copy (invented)\n"
# a drawn signature (a small invented mark), as the portal's signature pad sends it
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def price_through_working(c: TestClient, h: dict, tender_id: int, systems: dict[str, int], margin: str = "25") -> dict:
    """The tender's rates from the rate working: group the lines into main items, give each its
    system (by a word of its lines), work the rate (products, consumption, master prices, labour,
    margin) and apply it to the BOQ lines. Returns the main items' rates and the quoted total."""
    w = _ok(c.get(f"/api/rate-working/tenders/{tender_id}", headers=h), "working")
    w = _ok(c.post(f"/api/rate-working/{w['id']}/suggest?fresh=true", headers=h), "suggest")
    rates = {}
    for g in w["groups"]:
        words = " ".join(x["description"].lower() for x in g["lines"])
        sid = next((s for k, s in systems.items() if k in words), None)
        if sid is None:
            raise Step(f"no system for the main item {g['name']}")
        g = _ok(c.put(f"/api/rate-working/groups/{g['id']}", json={"system_id": sid, "margin_percent": margin, "labour_used_sqft": "6", "labour_paid_sqft": "6",
                                                                       "surface_prep": "12"}, headers=h), "main item")  # fmt: skip
        g = g.get("group", g)
        if g.get("errors"):
            raise Step(f"main item {g['name']}: {g['errors']}")
        rates[g["name"]] = g["rate_sqm"]
    applied = _ok(c.post(f"/api/rate-working/{w['id']}/apply", headers=h), "apply")
    if applied.get("skipped"):
        raise Step(f"rates not applied: {applied['skipped']}")
    t = _ok(c.get(f"/api/tenders/{tender_id}", headers=h), "tender")
    return {"rates_sqm": rates, "quoted_total": t["quoted_total"]}


# --- the drawing: a typical floor of tower A, traced (the plan on the certificate, the 3D view) -------

ROOMS = [  # name, x, y, w, h (mm, within one flat 9000 wide); toilet and balcony are our areas
    ("Living", 0, 1200, 4500, 5000), ("Bedroom", 4500, 1200, 4500, 4000), ("Toilet", 4500, 5200, 2100, 1500),
    ("Kitchen", 6600, 5200, 2400, 3000), ("Passage", 0, 6200, 4500, 2000), ("Balcony", 0, 0, 3600, 1200),
]


def _drawing(db: Session, site, nodes: dict, user_id) -> int:
    from app.sites.models import Drawing, DrawingRevision
    from app.takeoff.models import CadArea, CadFile

    d = Drawing(site_id=site.id, title="DEMO Tower A typical floor plan (demo)", created_by=user_id)
    db.add(d)
    db.flush()
    r = DrawingRevision(drawing_id=d.id, rev_no=0, stored_path="demo/none.dwg", filename="DEMO-tower-a-typical-floor.dwg", size_bytes=0, created_by=user_id)
    db.add(r)
    db.flush()
    f = CadFile(revision_id=r.id, drawing_id=d.id, site_id=site.id, status="ready", unit_m=0.001, units_code=4, summary={"demo": True}, created_by=user_id)
    db.add(f)
    db.flush()
    for i, flat in enumerate(FLATS):
        ox = i * 9600
        for name, x, y, w, h in ROOMS:
            node = nodes[flat][1] if name == "Toilet" else nodes[flat][2] if name == "Balcony" else None
            pts = [[ox + x, y], [ox + x + w, y], [ox + x + w, y + h], [ox + x, y + h]]
            db.add(CadArea(cad_file_id=f.id, key=f"demo:{flat}:{name}", name=f"{flat} {name}", outline=pts, node_id=node, label_w_m=Decimal(w) / 1000,
                           label_l_m=Decimal(h) / 1000, traced_area_sqm=Decimal(w * h) / 1000000, status="accepted" if node else "candidate", plan="TYPICAL FLOOR"))  # fmt: skip
    db.flush()
    return f.id


def _stages(db: Session, site, node_id: int, template_id: int, boq_line_id: int | None, qty, unit: str, start: date | None, done: int) -> None:
    """The area's scope with its stages as tasks: the first `done` stages done, a day or more each
    (the pond test 4 days), from `start`."""
    from app.sites.models import AreaScope, StageTemplateStep, Task

    sc = AreaScope(site_id=site.id, node_id=node_id, boq_line_id=boq_line_id, stage_template_id=template_id, qty=qty, unit=unit,
                   progress_percent=Decimal(0))  # fmt: skip
    db.add(sc)
    db.flush()
    day, pct = start, Decimal(0)
    for i, st in enumerate(db.scalars(select(StageTemplateStep).where(StageTemplateStep.template_id == template_id).order_by(StageTemplateStep.sort_order))):
        span = 4 if st.name == "Pond test" else 1
        is_done = start is not None and i < done
        end = day + timedelta(days=span - 1) if is_done else None
        db.add(Task(site_id=site.id, node_id=node_id, area_scope_id=sc.id, step_id=st.id, name=st.name, sort_order=i, planned_start=day, planned_end=end,
                    actual_start=day if is_done else None, actual_end=end, status="done" if is_done else "not_started",
                    progress_percent=Decimal(100) if is_done else Decimal(0)))  # fmt: skip
        if is_done:
            pct += Decimal(st.weight_percent)
            day = end + timedelta(days=1)
    sc.progress_percent = pct
    if pct >= 100:
        sc.completed_at = datetime.combine(day, time(18, 0), IST)
    db.flush()


# --- the run ---------------------------------------------------------------------------------------------


def run(db: Session) -> dict:
    import app.main as main
    from app.finance.models import RaBill
    from app.models import User
    from app.portal.models import ClientUser
    from app.quotations.models import Quotation
    from app.sites.models import Site, SiteNode
    from app.team.demo import email_for
    from app.tenders.models import BoqLine, BoqSection, Tender

    site = db.scalar(select(Site).where(Site.name == SITE, Site.is_demo))
    if site is None:
        raise SystemExit("The DEMO Shela site is missing: run the field demo first.")
    removed = reset(db, site.id)
    m = _masters(db)
    db.commit()
    c = TestClient(main.app)
    H = {r: _login(c, email_for(r)) for r in ("director", "planning", "billing", "accounts", "sales", "site_engineer")}
    sales_id = db.scalar(select(User.id).where(User.email == email_for("sales")))
    out: dict = {"site": f"{site.code} {site.name}", "removed_rows": removed}

    # 1. the tender, priced through the rate working, quoted to three civil contractors ----------------
    hd = H["director"]
    for pid, rate in ((m["product"], "185"), (m["pu_product"], "310")):  # the master price list (DEMO prices)
        _ok(c.post(f"/api/prices/products/{pid}", json={"rate": rate, "source": "manual", "note": "DEMO price"}, headers=hd), "price", 201)
    t = Tender(code=f"T-DEMO-{site.id}", name=TENDER, status="draft", client_id=m[DEVELOPER], guarantee_years=10, site_name=SITE, site_city="Ahmedabad",
               site_state="Gujarat", owner_id=sales_id, is_demo=True, notes="DEMO: invented")  # fmt: skip
    db.add(t)
    db.flush()
    sec = BoqSection(tender_id=t.id, title="Toilets and balconies", sort_order=1)
    db.add(sec)
    db.flush()
    db.add_all([BoqLine(tender_id=t.id, section_id=sec.id, sort_order=1, client_item_no="1", unit="sqm", qty=Decimal("22"), system_id=m["system"],
                        description=f"Toilet waterproofing with {PRODUCT} acrylic coating and 45 GSM mesh, floor and walls up to 300 mm"),
                BoqLine(tender_id=t.id, section_id=sec.id, sort_order=2, client_item_no="2", unit="sqm", qty=Decimal("18"), system_id=m["pu_system"],
                        description="Balcony waterproofing with PU coating")])  # fmt: skip
    db.commit()
    priced = price_through_working(c, hd, t.id, {"toilet": m["system"], "balcony": m["pu_system"]})
    for name in CONTRACTORS:
        r = _ok(c.post(f"/api/closeout/tenders/{t.id}/customers", json={"client_id": m[name]}, headers=hd), f"quote to {name}", 201)
    win = next(x for x in r["customers"] if x["client"] == WINNER)
    r = _ok(c.post(f"/api/closeout/tenders/{t.id}/customers/{win['id']}/main-won", headers=hd), "main job won")
    out["tender"] = {"code": t.code, "rates_sqm": priced["rates_sqm"], "quoted_total": priced["quoted_total"], "main_contractor": r["main_contractor"],
                     "customers": [(x["client"], x["quotation"]["code"], x["quotation"]["total"], x["main_label"]) for x in r["customers"]]}  # fmt: skip
    for name, rank, us, rate in (("EESPL", 1, True, None), ("DEMO Applicator Two", 2, False, None), ("DEMO Applicator Three", 3, False, None)):
        _ok(c.post(f"/api/team/tenders/{t.id}/bidders", json={"name": name, "rank": rank, "is_us": us, "rate": rate}, headers=hd), "bidder", 201)
    _ok(c.patch(f"/api/tenders/{t.id}", json={"status": "won"}, headers=hd), "won")
    out["tender"]["our_stage"] = "won as L1 (EESPL, DEMO Applicator Two, DEMO Applicator Three)"

    site = db.get(Site, site.id)
    site.client_id, site.tender_id, site.state, site.city = m[WINNER], t.id, "Gujarat", "Ahmedabad"
    q = db.get(Quotation, win["quotation"]["id"])
    q.site_id, q.salesperson_id, q.status = site.id, sales_id, "won"
    q.terms = [{"category": "client_scope", "text": "Lifting and shifting of material to all floors shall be provided by the client free of cost."},
               {"category": "client_scope", "text": "Water and electricity shall be provided by the client."},
               {"category": "payment", "text": "Our R.A. bills shall be released within 7 (seven) days from the date of submission."}]  # fmt: skip
    db.commit()
    qrates = {("toilet" if ln.description.startswith("Toilet") else "balcony"): Decimal(ln.rate) for it in q.items for ln in it.lines}

    # 2. the work order: the balcony per rmt of its length (1.2 m wide), checked, resolved, locked ----
    hp = H["planning"]
    wo = _ok(c.post("/api/closeout/work-orders", json={"quotation_id": q.id, "site_id": site.id, "client_ref": "DEMO/WO/BETA/031"}, headers=hp), "work order", 201)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sr No", "Description", "Unit", "Qty", "Rate"])
    ws.append(["1", f"Toilet waterproofing with {PRODUCT} acrylic coating and 45 GSM mesh, floor and walls up to 300 mm", "sqm", 22, float(qrates["toilet"])])
    balcony_rmt = (qrates["balcony"] * Decimal("1.2")).quantize(Decimal("1"))
    ws.append(["2", "Balcony waterproofing with PU coating", "rmt", 14.4, float(balcony_rmt)])  # per rmt of the balcony's length
    ws.append([])
    ws.append(["Terms: Lifting and shifting of material shall be provided by the contractor. Payment within 45 days of certification. Guarantee 10 years."])
    buf = io.BytesIO()
    wb.save(buf)
    _ok(c.post(f"/api/closeout/work-orders/{wo['id']}/file", files=_file("DEMO-work-order-beta.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), headers=hp), "upload")
    wo = _ok(c.post(f"/api/closeout/work-orders/{wo['id']}/compare", headers=hp), "compare")
    devs = [(d["kind"], d["topic"], d["ours"], d["theirs"]) for d in wo["deviations"]]
    blocked = c.post(f"/api/closeout/work-orders/{wo['id']}/accept", headers=hp).status_code
    for d in wo["deviations"]:
        if d["kind"] == "scope":
            body = {"action": "amend", "note": "Material lifting stays with the client as in our offer: ask for the amendment", "amend_text": None}
        elif d["kind"] in ("unit", "qty", "rate"):
            body = {"action": "accept", "note": f"The balcony per rmt of its length (1.2 m wide): {balcony_rmt} per rmt = {qrates['balcony']} per sqm x 1.2, agreed on the call"}
        else:
            body = {"action": "accept", "note": "45 days after certification agreed with the client"}
        _ok(c.post(f"/api/closeout/work-orders/{wo['id']}/deviations/{d['id']}", json=body, headers=hp), "resolve")
    wo = _ok(c.post(f"/api/closeout/work-orders/{wo['id']}/accept", headers=hp), "accept")
    out["work_order"] = {"code": wo["code"], "ref": wo["client_ref"], "deviations": devs, "accept_while_open": blocked, "locked": wo["locked"],
                         "edit_after_lock": c.put(f"/api/closeout/work-orders/{wo['id']}", json={"payment_days": 30}, headers=hd).status_code,
                         "payment": f"{wo['terms']['payment_days']} days after the {wo['terms']['payment_basis']}"}  # fmt: skip

    # the tower, four flats, their stages; the contract (after the work order: its units and rates) ---
    tower = SiteNode(site_id=site.id, kind="tower", name="DEMO Tower A")
    db.add(tower)
    db.flush()
    nodes = {}
    for i, f in enumerate(FLATS):
        flat = SiteNode(site_id=site.id, parent_id=tower.id, kind="flat", name=f"Flat {f}", sort_order=i)
        db.add(flat)
        db.flush()
        toilet = SiteNode(site_id=site.id, parent_id=flat.id, kind="toilet", name="Toilet", sort_order=1)
        balcony = SiteNode(site_id=site.id, parent_id=flat.id, kind="balcony", name="Balcony", sort_order=2)
        db.add_all([toilet, balcony])
        db.flush()
        if f != "104":  # 104 went to another applicator; the rest handed over to us (103's balcony not yet)
            for n in (flat, toilet, balcony) if f != "103" else (flat, toilet):
                n.handover_status, n.handover_received_on = "received", date(2026, 8, 10)
        nodes[f] = (flat.id, toilet.id, balcony.id)
    site.measurements_need_approval = True
    db.commit()
    hb = H["billing"]
    k = _ok(c.post(f"/api/finance/sites/{site.id}/contract", json={"retention_percent": "5"}, headers=hd), "contract", 201)
    lines = {("toilet" if ln["description"].startswith("Toilet") else "balcony"): ln for ln in k["lines"]}
    boq = {("toilet" if b.description.startswith("Toilet") else "balcony"): b.id for b in db.scalars(select(BoqLine).where(BoqLine.tender_id == t.id))}
    starts = {"101": (date(2026, 8, 10), date(2026, 8, 12)), "102": (date(2026, 8, 11), date(2026, 8, 13)), "103": (date(2026, 10, 14), None)}
    for f, (ts, bs) in starts.items():
        _stages(db, site, nodes[f][1], m["toilet_template"], boq["toilet"], Decimal("5.31"), "sqm", ts, 5 if f != "103" else 2)
        _stages(db, site, nodes[f][2], m["balcony_template"], boq["balcony"], Decimal("3.6"), "rmt", bs, 5 if bs else 0)
    _drawing(db, site, nodes, None)
    db.commit()
    out["contract"] = {k2: f"{v['unit']} @ {v['rate']} x {v['qty']}" for k2, v in lines.items()}

    # 6. RFI zones: flats 101-103 ours (the client signs 101 in the app, the rest recorded), 104 another applicator
    hs = H["site_engineer"]
    zones = {}
    for f in FLATS:
        body = {"name": f"Flat {f}", "node_id": nodes[f][0]} if f != "104" else {"name": "Flat 104", "node_id": nodes[f][0], "ours": False, "other_applicator": "DEMO Other Applicator"}
        zones[f] = _ok(c.post(f"/api/closeout/sites/{site.id}/zones", json=body, headers=hs), "zone", 201)["id"]
    for f in ("102", "103"):
        _ok(c.post(f"/api/closeout/zones/{zones[f]}/record-signature", data={"signed_name": "DEMO Client Project Manager"}, files=_file("rfi-signed.pdf", SIGNED), headers=hs), "zone sign")

    # the portal: visible, and the winner's people with their client roles
    _ok(c.put(f"/api/portal-admin/sites/{site.id}", json={"visible": True, "sections": {}}, headers=hd), "portal")
    P = {}
    for role, (name, email) in CLIENT_USERS.items():
        u = db.scalar(select(User).where(User.email == email))
        if u is not None and db.get(ClientUser, (u.id, m[WINNER])) is None:  # a portal login of an earlier run
            db.add(ClientUser(user_id=u.id, client_id=m[WINNER], roles=[role]))
            db.commit()
        r = _ok(c.post("/api/portal-admin/invites", json={"full_name": name, "email": email, "client_id": m[WINNER], "site_ids": [site.id], "roles": [role]}, headers=hd), "invite", 201)
        token = r["link"].rsplit("/", 1)[1]
        _ok(c.post(f"/api/portal/invite/{token}", json={"password": _password()}), "invite accept")
        u = db.scalar(select(User).where(User.email == email))
        u.is_demo = True
        db.commit()
        P[role] = _login(c, email)
    _ok(c.post(f"/api/portal/sites/{site.id}/zones/{zones['101']}/sign", headers=P["project_manager"]), "zone signed in the portal")

    # 5. measurements: the toilet floor (L x B) and walls up to 300 mm (perimeter x height), the
    #    balcony per rmt (its running length); one size taken in feet and inches --------------------
    def line(f, area, on, **sizes_):
        what = {"toilet_floor": "toilet floor", "toilet_walls": "toilet walls up to 300 mm", "balcony": "balcony, running length"}[area]
        key = "balcony" if area == "balcony" else "toilet"
        return c.post(f"/api/closeout/sites/{site.id}/measurements", json={"description": f"Flat {f} {what}", "contract_line_id": lines[key]["id"],
                                                                           "node_id": nodes[f][2 if key == "balcony" else 1], "measured_on": on, **sizes_}, headers=hb)  # fmt: skip

    refused = line("101", "balcony", "2026-08-20", length_m="3.6", breadth_m="1.2", unit="sqm")
    out["unit_refused"] = {"status": refused.status_code, "reason": refused.json().get("detail")}
    made = {}
    for f, on in (("101", "2026-08-20"), ("102", "2026-08-21")):
        made[f, "floor"] = _ok(line(f, "toilet_floor", on, length_m="7 ft" if f == "101" else "2.1", breadth_m="1.5"), "floor", 201)
        made[f, "walls"] = _ok(line(f, "toilet_walls", on, perimeter_m="7.2", height_m="0.3"), "walls", 201)
        made[f, "balcony"] = _ok(line(f, "balcony", on, length_m="3.6"), "balcony", 201)
    made["103", "floor"] = _ok(line("103", "toilet_floor", "2026-10-18", length_m="2.1", breadth_m="1.5"), "floor", 201)
    _ok(c.post(f"/api/closeout/sites/{site.id}/measurement-sets", json={"ids": [x["id"] for x in made.values()]}, headers=hb), "send")
    pb = P["billing"]
    corr = []
    for key, field, new, remark in ((("101", "floor"), "length_m", "6 ft 10 in", "Taped again with your engineer: 6 ft 10 in, not 7 ft"),
                                    (("101", "balcony"), "length_m", "3.45", "The balcony is 3.45 m inside the parapet returns")):  # fmt: skip
        ml = made[key]
        r = _ok(c.post(f"/api/portal/sites/{site.id}/measurements/{ml['id']}/correct", json={"field": field, "new_value": new, "remark": remark}, headers=pb), "correct")
        ch = r["changes"][0]
        corr.append(ch)
        _ok(c.post(f"/api/closeout/measurement-changes/{ch['id']}/answer", json={"accept": True}, headers=hb), "accept correction")
    for key in (("101", "walls"), ("102", "floor"), ("102", "walls")):
        _ok(c.post(f"/api/portal/sites/{site.id}/measurements/{made[key]['id']}/approve", headers=pb), "approve")
    _ok(c.post(f"/api/closeout/measurements/{made['102', 'balcony']['id']}/record-approval", data={"approved_name": "DEMO Client Billing Engineer"},
               files=_file("mb-signed.pdf", SIGNED), headers=hb), "record")  # fmt: skip
    a = made["101", "floor"]
    lock = c.put(f"/api/closeout/measurements/{a['id']}", json={"description": "x", "length_m": "25"}, headers=hd).status_code
    book = _ok(c.get(f"/api/closeout/sites/{site.id}/measurements", headers=hb), "book")["lines"]
    out["measurements"] = {"corrections": [(x["field"], x["old_shown"], x["new_shown"], x["by"], x["at"], x["remark"]) for x in corr], "edit_approved_line": lock,
                           "lines": [(x["description"], x["shown"], str(x["qty"]), x["unit"], x["status"]) for x in book]}  # fmt: skip

    # 7. the RA bill: flat 101 only (102 approved after the bill was made), certified, invoiced ---------
    later = [made["102", k2]["id"] for k2 in ("floor", "walls", "balcony")]
    db.expire_all()
    db.execute(text("update measurements set status = 'sent' where id = any(:i)"), {"i": later})  # approved after the bill: held back
    db.commit()
    ra = _ok(c.post(f"/api/finance/contracts/{k['id']}/ra-bills", json={"period_to": "2026-08-25"}, headers=hb), "RA bill", 201)
    db.execute(text("update measurements set status = 'approved' where id = any(:i)"), {"i": later})
    db.commit()
    _ok(c.post(f"/api/finance/ra-bills/{ra['id']}/submit", headers=hb), "submit")
    _ok(c.post(f"/api/finance/ra-bills/{ra['id']}/certify", json={"lines": [{"contract_line_id": ln["contract_line_id"], "certified_qty": str(ln["qty"])} for ln in ra["lines"] if Decimal(str(ln["qty"])) > 0]}, headers=hb), "certify")
    rb = db.get(RaBill, ra["id"])
    rb.certified_at = datetime.combine(date(2026, 8, 31), time(16, 0), IST)  # the client's certificate date (DEMO back-dated)
    rb.client_cert_on = date(2026, 8, 31)
    db.commit()
    _ok(c.post(f"/api/finance/ra-bills/{ra['id']}/invoice", json={"invoice_date": "2026-09-01"}, headers=hd), "invoice", 201)
    out["bill_lines"] = [(ln["description"][:40], str(ln["qty"]), ln.get("unit"), str(ln["rate"])) for ln in ra["lines"]]
    _ok(c.put(f"/api/closeout/clients/{m[WINNER]}/billing-cycle", json={"submit_from_day": 20, "submit_to_day": 25, "ho_from_day": 1, "ho_to_day": 5, "payment_days": 45,
                                                                       "note": "DEMO: bills reach the site on the 20th-25th, head office on the 1st-5th"}, headers=H["accounts"]), "cycle")  # fmt: skip
    for step, on, signed in (("prepared", "2026-08-25", False), ("submitted_site", "2026-08-26", False), ("signed_pm", "2026-08-31", True), ("sent_ho", "2026-09-02", False), ("with_accounts", "2026-09-04", False)):
        _ok(c.post(f"/api/closeout/bills/{ra['id']}/steps", data={"step": step, "on_date": on, "by_name": "DEMO Billing"}, files=_file("bill-signed.pdf", SIGNED) if signed else None, headers=hb), step)

    # 8. reminders on the DEMO site only: the due day, +5 and today -------------------------------------
    from app.closeout import billing as bsvc
    from app.portal.models import Notification
    from app.process.models import ProcessEvent

    bill = next(x for x in _ok(c.get(f"/api/closeout/bills?site_id={site.id}", headers=H["accounts"]), "bills") if x["id"] == ra["id"])
    due = date.fromisoformat(str(bill["due_on"]))
    for day in (due, due + timedelta(days=5), date(2026, 10, 21)):
        bsvc.timed_events(db, datetime.combine(day, time(9, 0), IST), site_ids=[site.id])
        db.commit()
    told = []
    for ev in db.scalars(select(ProcessEvent).where(ProcessEvent.site_id == site.id, ProcessEvent.type.in_(("payment_due", "payment_overdue", "payment_overdue_long", "bill_stuck", "bill_stuck_long")))):
        for n in db.scalars(select(Notification).where(Notification.event_id == ev.id)):
            u = db.get(User, n.user_id)
            told.append((ev.type, u.full_name if u else None))
    _ok(c.post(f"/api/closeout/bills/{ra['id']}/followups", json={"spoke_to": "DEMO Client Accounts", "said": "Cheque in the next run", "promised_on": "2026-10-25"}, headers=H["accounts"]), "follow-up", 201)
    client_ids = list(db.scalars(select(ClientUser.user_id).where(ClientUser.client_id == m[WINNER])))
    out["bill"] = {"code": ra["code"], "at": bill["at"], "due": str(due), "how": bill["due_how"], "overdue_days": bill["overdue_days"], "outstanding": str(bill["outstanding"]),
                   "reminded": sorted(set(told)),
                   "client_in_app": [(db.get(User, n.user_id).full_name, n.title) for n in db.scalars(select(Notification).where(Notification.user_id.in_(client_ids), Notification.kind == "bill_overdue", Notification.site_id == site.id))],
                   "client_emails": db.scalar(text("select count(*) from notification_outbox o join notifications n on n.id = o.notification_id where o.channel = 'email' and n.user_id = any(:u)"), {"u": client_ids}),
                   "client_portal_overdue": [x["overdue_days"] for x in _ok(c.get(f"/api/portal/sites/{site.id}/overdue", headers=P["accounts"]), "portal overdue")]}  # fmt: skip

    # 6. the billing checklist of the tower
    g = _ok(c.get(f"/api/closeout/sites/{site.id}/billing-checklist", params={"tower_id": tower.id}, headers=hb), "checklist")
    out["checklist"] = {"counts": g["counts"], "cells": {r["flat"]: {k2: v["label"] for k2, v in r["cells"].items()} for r in g["rows"]}}

    # 9. the work completion certificate (flats 101-102), signed by the client's PM in the portal ------
    w = _ok(c.post(f"/api/closeout/sites/{site.id}/work-completions", json={"completion_date": "2026-10-10", "guarantee_years": 10, "node_ids": [nodes["101"][0], nodes["102"][0]],
                                                                             "note": "DEMO: flats 101 and 102 of tower A"}, headers=hb), "WCC", 201)  # fmt: skip
    _ok(c.post(f"/api/portal/sites/{site.id}/work-completions/{w['id']}/sign", headers=P["project_manager"]), "WCC signed")
    w = _ok(c.get(f"/api/closeout/work-completions/{w['id']}", headers=hb), "WCC")
    out["wcc"] = {"code": w["code"], "areas": [(x["area"], x["item"][:30], x["qty"], x["unit"], x["system"], x["products"], x["from"], x["to"], x["dates_from"]) for x in w["areas"]],
                  "completion": str(w["completion_date"]), "expiry": str(w["guarantee_expiry"]), "signed": w["signed_name"],
                  "edit_after_sign": c.put(f"/api/closeout/work-completions/{w['id']}", json={"note": "x"}, headers=hd).status_code}  # fmt: skip

    # the quality checklist of flat 101's toilet: our sign on each stage with its dates; the client
    # signs the first three on paper (recorded with the copy) and the fourth in the portal
    from app.execution.models import Inspection
    from app.sites.models import Task

    tasks = list(db.scalars(select(Task).where(Task.node_id == nodes["101"][1], Task.parent_task_id.is_(None)).order_by(Task.sort_order)))
    signs = []
    for i, tk in enumerate(tasks):
        r = _ok(c.post(f"/api/closeout/tasks/{tk.id}/quality-sign", json={"started_on": str(tk.actual_start), "ended_on": str(tk.actual_end)}, headers=hs), "quality sign")
        iid = r["stages"][i]["inspection_id"]
        if i < 3:
            _ok(c.post(f"/api/closeout/inspections/{iid}/client-sign-record", data={"signed_name": "DEMO Client Project Manager"}, files=_file("qc-signed.pdf", SIGNED), headers=hs), "client sign recorded")
        elif i == 3:
            _ok(c.post(f"/api/portal/sites/{site.id}/inspections/{iid}/sign", json={"name": "DEMO Client Project Manager", "signature": PNG}, headers=P["project_manager"]), "client sign in the portal")
        signs.append((tk.name, str(tk.actual_start), str(tk.actual_end), db.get(Inspection, iid).client_signoff))
    out["quality"] = signs

    # the handover: the client promised flat 103's balcony for 15 Oct; our engineer moves it
    _ok(c.put(f"/api/portal/sites/{site.id}/nodes/{nodes['103'][2]}/handover-promise", json={"promised_on": "2026-10-15"}, headers=P["project_manager"]), "client promise")
    mv = _ok(c.post(f"/api/closeout/sites/{site.id}/nodes/{nodes['103'][2]}/handover-move", json={"promised_on": "2026-10-28",
                    "reason": "The railing grouting by the civil contractor is not done: the balcony cannot be waterproofed before it"}, headers=hs), "handover moved")  # fmt: skip
    seen = next(x for x in _ok(c.get(f"/api/portal/sites/{site.id}/handover", headers=P["project_manager"]), "portal handover") if x["node_id"] == nodes["103"][2])
    out["handover"] = {"client_promised": mv["client_promised_on"], "moved_to": mv["moved_to"], "because": mv["moved_because"], "client_sees": (seen["promised_on"], seen["moved_because"])}

    # material reconciliation: 16 kg of DEMO FLEXCOAT issued to the toilets of 101 and 102; the
    # approved quantity needs less: the excess goes back to the godown with a transfer
    from app.masters.models import Product
    from app.material import service as stock
    from app.material.models import SiteIssue, SiteIssueLine

    p = db.get(Product, m["product"])
    store = stock.site_store(db, site)
    stock.post(db, store_id=store.id, product=p, qty=Decimal(20), rate=Decimal(185), ref_type="opening", ref_id=None, user_id=None, note="DEMO opening stock")
    iss = SiteIssue(code=stock.next_code(db, "ISS"), kind="issue", store_id=store.id, site_id=site.id, node_id=nodes["101"][1], issued_on=date(2026, 8, 12), remark="DEMO: to the toilets of 101 and 102")
    db.add(iss)
    db.flush()
    stock.take_out(db, store=store, product=p, qty=Decimal(16), ref_type="issue", ref_id=iss.id, user_id=None, note=iss.code)
    iss.lines.append(SiteIssueLine(product_id=p.id, product=p, qty=Decimal(16), rate=Decimal(185), value=Decimal(2960)))
    db.commit()
    rec = _ok(c.get(f"/api/closeout/sites/{site.id}/reconciliation", headers=hb), "reconciliation")
    row = next(x for x in rec["rows"] if x["product_id"] == p.id)
    before = {k2: str(row[k2]) for k2 in ("issued", "needed", "difference", "state")}
    back = _ok(c.post(f"/api/closeout/sites/{site.id}/reconciliation/return", json={"product_id": p.id, "qty": str(row["difference"])}, headers=hb), "return to godown", 201)
    row = next(x for x in back["rows"] if x["product_id"] == p.id)
    out["reconciliation"] = {"before": before, "transfer": back["transfer"], "after": {k2: str(row[k2]) for k2 in ("issued", "needed", "returned", "difference", "state")}}

    # labour claims: 10 % above the measured toilet of 101 (billing asks to pay it: the director
    # decides), and 102's toilet as measured
    claims = []
    for f, factor, decision, reason in (("101", Decimal("1.10"), "claimed", "The gang says the toilet's door sill and the shower step were done too"),
                                        ("102", Decimal("1"), "approved", None)):  # fmt: skip
        approved = sum(Decimal(str(x[2])) for x in out["measurements"]["lines"] if x[0].startswith(f"Flat {f} toilet") and x[4] == "approved")
        lst = _ok(c.post(f"/api/closeout/sites/{site.id}/labour-claims", json={"contractor": "DEMO Labour Contractor", "node_id": nodes[f][1], "contract_line_id": lines["toilet"]["id"],
                                                                               "claimed_qty": str((approved * factor).quantize(Decimal("0.001"))), "unit": "sqm", "period": "2026-08"}, headers=hb), "claim", 201)  # fmt: skip
        r = _ok(c.post(f"/api/closeout/labour-claims/{lst[-1]['id']}/decide", json={"decision": decision, "reason": reason}, headers=hb), "decide")
        claims.append((f, str(r["claimed"]), str(r["approved"]), str(r["excess_claim"]), r["status"], str(r["pays"])))
    out["labour_claims"] = claims

    # 10. three issues --------------------------------------------------------------------------------
    late = _ok(c.post("/api/closeout/issues", json={"site_id": site.id, "category": "material_not_arrived", "title": "PU coating for the flat 103 balcony not delivered",
                                                     "description": "Indent raised 14 Oct, promised for 17 Oct; the gang is idle on the balcony.", "due_on": "2026-10-23"}, headers=hs), "issue", 201)  # fmt: skip
    _ok(c.post(f"/api/closeout/issues/{late['id']}/comments", json={"body": "Vendor says dispatch on 22 Oct."}, headers=hs), "comment", 201)
    _ok(c.patch(f"/api/products/{m['product']}", json={"discontinued_on": "2026-10-15"}, headers=hd), "discontinued")
    _ok(c.post("/api/closeout/issues", json={"site_id": site.id, "category": "leakage", "title": "Damp patch below the flat 101 toilet", "node_id": nodes["101"][1],
                                            "description": "Seen from the flat below after a 24 h pond test by the client."}, headers=hs), "leakage", 201)  # fmt: skip
    issues = _ok(c.get(f"/api/closeout/issues?site_id={site.id}", headers=hs), "issues")
    for i in issues:
        db.execute(text("update issue_log set is_demo = true where id = :i"), {"i": i["id"]})
    db.commit()
    out["issues"] = [(i["code"], i["category_label"], i["title"], "guarantee " + str(i["work_completion_id"]) if i["work_completion_id"] else "") for i in issues]
    out["ids"] = {"site": site.id, "tender": t.id, "work_order": wo["id"], "ra_bill": ra["id"], "wcc": w["id"], "tower": tower.id, "client": m[WINNER],
                  "flats": {f: list(v) for f, v in nodes.items()}}  # fmt: skip
    return out
