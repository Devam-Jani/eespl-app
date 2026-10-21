# ruff: noqa: E501
"""DEMO (marked demo): the tender "DEMO Godrej Phase-11 (block B1-B3 typical floor)" with toilets,
balconies and wash areas from the typical floor drawing (labels in mm), the terrace from the
same drawing, the domestic OHWT from the O.H.W.T. plan's notes and one UG tank from the second
basement plan's notes; its methodology built with Bronco systems and checked against the Godrej
standard (imported first), exported as Word and PDF.

    docker compose exec api python -m app.cli demo-methodology
"""

from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.methodology import build as bld
from app.methodology import export, sop
from app.methodology.models import ClientStandard, Methodology, MethodSystem

GODREJ = Path(app_settings.data_dir) / "methodology" / "godrej" / "Waterproofing Works"
DRAWINGS = GODREJ / "3_Drawing"
TYPICAL = "01_BLOCK-B1-B2-B3/TYPICAL FLOOR PLAN_GODREJ PHASE-11_(BLOCK-B1-B2-B3)_22-08-2026.dwg"
OHWT = "01_BLOCK-B1-B2-B3/O.H.W.T.PLAN _GODREJ PHASE-11_(BLOCK-B1-B2-B3)_22-08-2026.dwg"
BASEMENT = "Basement/SECOND BASEMENT PLAN_SITE PLAN  _(GODREJ PHASE-11)_17-09-2026.dwg"
STANDARD = "Godrej Properties waterproofing standard"
TITLE = "DEMO Godrej Phase-11 (block B1-B3 typical floor)"
Q = Decimal("0.001")


def _sum(places: list[dict]) -> Decimal:
    return sum(
        (Decimal(str(p["area_sqm"])) for p in places if p.get("area_sqm")), Decimal(0)
    ).quantize(Q)


def _tank_qty(p: dict) -> tuple[Decimal, str]:
    """Inside surface of a tank from its note (the drawing gives the area and depth, not the
    sides: the walls come from a square plan, to confirm)."""
    qty, note, _assumed = bld.tank_qty(
        float(p["area_sqm"]), float(p["depth_m"]), float(p.get("freeboard_m") or 0.3)
    )
    return qty, note


def run(db: Session, user_id=None) -> dict:
    from app.masters.models import Client
    from app.tenders import service as tender_service
    from app.tenders.models import BoqLine, BoqSection, Tender

    std = db.scalar(select(ClientStandard).where(ClientStandard.name == STANDARD))
    if std is None:
        std = sop.import_standard(db, GODREJ, STANDARD, "Godrej Properties Ltd.")
    if not db.scalar(select(MethodSystem.id).limit(1)):
        raise SystemExit(
            "Seed the method library first: python -m app.cli seed-methodology <our offers>"
        )
    old = db.scalar(select(Tender).where(Tender.name == TITLE, Tender.is_demo))
    if old is not None:
        db.delete(old)
        db.flush()
    client = db.scalar(select(Client).where(Client.name == "DEMO Godrej Properties (demo client)"))
    if client is None:
        client = Client(
            name="DEMO Godrej Properties (demo client)",
            type="builder",
            city="Ahmedabad",
            state="Gujarat",
            is_demo=True,
            notes="DEMO: for the methodology demo",
        )
        db.add(client)
        db.flush()
    t = Tender(code=tender_service.next_code(db), name=TITLE, client_id=client.id, site_name="DEMO Phase-11, blocks B1-B3", site_city="Ahmedabad", site_state="Gujarat",
               status="draft", is_demo=True, client_standard_id=std.id, owner_id=user_id, notes="DEMO: quantities from the Godrej Phase-11 drawings (typical floor, O.H.W.T. plan, second basement)")  # fmt: skip
    db.add(t)
    db.flush()

    read = {
        k: bld.read_drawing(DRAWINGS / p)
        for k, p in (("typical", TYPICAL), ("ohwt", OHWT), ("basement", BASEMENT))
    }
    typ = read["typical"]["places"]
    toilets = [p for p in typ if p["element"] == "toilet" and p.get("area_sqm")]
    unsized = sum(1 for p in typ if p["element"] == "toilet" and not p.get("area_sqm"))
    balconies = [
        p
        for p in typ
        if p["element"] == "balcony" and p.get("area_sqm") and "BALCONY" in p["name"].upper()
    ]
    wash = [
        p
        for p in typ
        if p["element"] == "balcony" and p.get("area_sqm") and "WASH" in p["name"].upper()
    ]
    terrace = [p for p in typ if p["element"] == "terrace" and p.get("area_sqm")]
    oht = next(
        p for p in read["ohwt"]["places"] if "DOMESTIC" in p["label"].upper() and p.get("depth_m")
    )
    ug = next(
        p
        for p in read["basement"]["places"]
        if p["element"] == "ug_tank"
        and p.get("area_sqm")
        and p.get("depth_m")
        and "2,00,000" in p["label"]
    )
    oht_qty, oht_note = _tank_qty(oht)
    ug_qty, ug_note = _tank_qty(ug)
    lines = [
        (
            "Toilets",
            "Waterproofing of toilets (typical floor, blocks B1-B3): floor and walls up to the specified height, as per the client's SOP for wet areas.",
            _sum(toilets),
            f"{len(toilets)} toilets with size labels ({min(p['area_sqm'] for p in toilets):.2f}–{max(p['area_sqm'] for p in toilets):.2f} sqm); {unsized} labels without a size",
        ),
        (
            "Balconies",
            "Waterproofing of balconies (typical floor): floor and up to 100 mm on the walls.",
            _sum(balconies),
            f"{len(balconies)} balconies with size labels",
        ),
        (
            "Wash / utility areas",
            "Waterproofing of wash / utility areas (typical floor).",
            _sum(wash),
            f"{len(wash)} wash areas with size labels",
        ),
        (
            "Terrace",
            "Waterproofing of the open terraces (typical floor plan).",
            _sum(terrace),
            f"{len(terrace)} terraces with size labels",
        ),
        (
            "Overhead water tank (domestic)",
            "Internal waterproofing of the domestic overhead water tank (12,500 L).",
            oht_qty,
            oht_note,
        ),
        (
            "Underground water tank 1A (domestic)",
            "Internal waterproofing of the domestic underground water tank 1A (2,00,000 L).",
            ug_qty,
            ug_note,
        ),
    ]
    for i, (sec, text, qty, note) in enumerate(lines, 1):
        s = BoqSection(tender_id=t.id, title=sec, sort_order=i)
        db.add(s)
        db.flush()
        db.add(
            BoqLine(
                tender_id=t.id,
                section_id=s.id,
                sort_order=1,
                client_item_no=str(i),
                description=f"{sec} — {text}",
                unit="sqm",
                qty=qty,
                client_remarks=f"DEMO quantity: {note}",
            )
        )
    db.flush()

    from app.methodology.routes import groups_for

    groups, rev = groups_for(db, t.id, None, user_id)
    m = Methodology(
        code=bld.new_code(db),
        title=f"{TITLE}: waterproofing methodology",
        tender_id=t.id,
        standard_id=std.id,
        brand="Bronco",
        revision=rev,
        is_demo=True,
        created_by=user_id,
    )
    db.add(m)
    db.flush()
    drawings = [{"places": typ}, {"places": [oht]}, {"places": [ug]}]
    by_hand = {
        "Overhead water tank (domestic)": {"face": "inner"},
        "Underground water tank 1A (domestic)": {"face": "inner"},
    }
    bld.build(db, m, groups, drawings, by_hand)
    for it in m.items:  # Bronco is not on Godrej's list: keep it and ask for its approval (TPT)
        if any(
            r["topic"] == "Make" and r["status"] == "red"
            for r in (it.compliance or {}).get("rows", [])
        ):
            it.make_choice = "keep"
    bld.recheck(db, m)
    bld.save_version(db, m, "DEMO built from the Godrej Phase-11 drawings", user_id)
    files = {aud: export.issue(db, m, aud, user_id) for aud in ("client", "internal")}
    db.flush()
    site_out = _site(db, t, m, user_id)
    return {"tender": t.code, "methodology": m.code, "standard": std.name, "drawings": {k: {"file": v["file"], "texts": v["texts"], "repairs": v["repairs"]} for k, v in read.items()},
            "lines": [(sec, str(qty), note) for sec, _t, qty, note in lines],
            "items": [{"name": it.name, "element": it.element, "qty": str(it.qty), "system": db.get(MethodSystem, it.system_id).name if it.system_id else None, "reason": it.reason,
                       "rule": it.rule_note, "green": it.compliance.get("green"), "red": it.compliance.get("red"), "confirm": it.compliance.get("confirm"),
                       "reds": [(r["topic"], r["required"], r.get("ours"), r.get("gap")) for r in it.compliance["rows"] if r["status"] == "red"],
                       "confirms": [(r["topic"], r.get("gap")) for r in it.compliance["rows"] if r["status"] == "confirm"]} for it in m.items],
            "files": {aud: [f.path for f in fs] for aud, fs in files.items()}, "site": site_out}  # fmt: skip


def _site(db: Session, t, m: Methodology, user_id=None) -> dict:
    """The DEMO tender won: a DEMO site, the methodology handed over (stage templates, pond and
    material tests), the toilets' tasks on one floor, and the hold point blocking the next stage."""
    from datetime import date

    from fastapi import HTTPException

    from app.material import service as material
    from app.methodology import site as msite
    from app.sites import routers as site_routes
    from app.sites import service as site_service
    from app.sites import work
    from app.sites.models import AreaScope, Site, SiteNode, Task
    from app.tenders.models import BoqLine

    t.status = "won"
    for old in db.scalars(
        select(Site).where(Site.name == "DEMO Godrej Phase-11 (B1-B3)", Site.is_demo)
    ):
        db.delete(old)  # an earlier run's DEMO site
    db.flush()
    site = Site(code=site_service.next_code(db), name="DEMO Godrej Phase-11 (B1-B3)", client_id=t.client_id, tender_id=t.id, city="Ahmedabad", state="Gujarat",
                status="active", start_date=date.today(), is_demo=True, created_by=user_id)  # fmt: skip
    db.add(site)
    db.flush()
    material.site_store(db, site, user_id)
    out = msite.handover(db, m, site.id, user_id)
    export.share_with_client(db, m, site.id, user_id)
    node = SiteNode(site_id=site.id, kind="tower", name="Block B1 — typical floor")
    db.add(node)
    db.flush()
    toilets = next(it for it in m.items if it.element == "toilet")
    line = db.get(BoqLine, toilets.boq_line_ids[0])
    db.add(
        AreaScope(
            site_id=site.id,
            node_id=node.id,
            boq_line_id=line.id,
            stage_template_id=toilets.stage_template_id,
            qty=line.qty,
            unit="sqm",
            created_by=user_id,
        )
    )
    db.flush()
    work.generate_tasks(db, site, user_id)
    tasks = list(db.scalars(select(Task).where(Task.site_id == site.id).order_by(Task.sort_order)))
    hold = next(i for i, x in enumerate(tasks) if x.step and x.step.hold_point)
    for x in tasks[: hold + 1]:
        x.status = "done"
    blocked = None
    try:
        site_routes._check_predecessors(db, tasks[hold + 1])
    except HTTPException as e:
        blocked = {"task": tasks[hold + 1].name, "status": e.status_code, "detail": e.detail}
    db.flush()
    return {
        "site": site.code,
        "site_id": site.id,
        **out,
        "tasks": [x.name for x in tasks],
        "blocked": blocked,
    }
