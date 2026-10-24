# ruff: noqa: E501
"""Part 0 of the measure-and-bill prompt (from the new-UI review). Invented data only."""

from decimal import Decimal

from sqlalchemy import select

from app.sites import progress
from app.sites.models import AreaScope, Site, SiteNode, StageTemplate, StageTemplateStep, Task
from tests.test_finance import boss  # noqa: F401  (fixture)


def _site_with_done_steps(db, *, cache: bool) -> tuple[Site, SiteNode]:
    """A site whose steps were written straight into the database (as a demo or an import does):
    two of four steps done on the floor's toilet. cache=False also leaves the area's own number 0."""
    site = Site(code="S-P0-9001", name="Invented progress site", status="active")
    db.add(site)
    db.flush()
    tower = SiteNode(site_id=site.id, kind="tower", name="Tower A")
    db.add(tower)
    db.flush()
    floor = SiteNode(site_id=site.id, parent_id=tower.id, kind="floor", name="Floor 1", level_no=1)
    db.add(floor)
    db.flush()
    toilet = SiteNode(site_id=site.id, parent_id=floor.id, kind="toilet", name="Invented toilet")
    db.add(toilet)
    db.flush()
    tpl = StageTemplate(name="Invented progress stage")
    db.add(tpl)
    db.flush()
    steps = [StageTemplateStep(template_id=tpl.id, sort_order=i, name=f"Step {i}", weight_percent=Decimal(25)) for i in range(4)]
    db.add_all(steps)
    db.flush()
    sc = AreaScope(site_id=site.id, node_id=toilet.id, stage_template_id=tpl.id, qty=Decimal("6"), unit="sqm", progress_percent=Decimal(50) if cache else Decimal(0))
    db.add(sc)
    db.flush()
    for i, st in enumerate(steps):
        db.add(Task(site_id=site.id, node_id=toilet.id, area_scope_id=sc.id, step_id=st.id, name=st.name, sort_order=i, status="done" if i < 2 else "not_started"))
    db.commit()
    return site, floor


def test_a_site_with_done_steps_never_shows_0_percent(boss, db):  # noqa: F811
    c, h = boss
    for cache in (True, False):  # the area's own number written (the demo) or not (an import)
        site, floor = _site_with_done_steps(db, cache=cache)
        assert Decimal(site.progress_percent) == 0  # nothing rolled up: the cached total is still 0
        assert Decimal(c.get(f"/api/sites/{site.id}", headers=h).json()["progress_percent"]) == 50
        nodes = {n["name"]: Decimal(n["progress_percent"]) for n in c.get(f"/api/sites/{site.id}/nodes", headers=h).json()}
        assert nodes["Floor 1"] == 50 and nodes["Tower A"] == 50
        assert c.get(f"/api/sites/{site.id}/model", headers=h).json()["site_progress"] == 50
        listed = {s["id"]: Decimal(s["progress_percent"]) for s in c.get("/api/sites?q=Invented progress", headers=h).json()["items"]}
        assert listed[site.id] == 50
        assert progress.site_percents(db, [site.id])[site.id] == 50
        # the one refresh writes the same numbers into the stored columns
        assert progress.refresh(db, site) == 50
        db.commit()
        db.refresh(floor)
        assert Decimal(floor.progress_percent) == 50
        db.delete(db.get(Site, site.id))
        db.execute(select(StageTemplate))  # keep the session usable
        db.query(StageTemplate).filter(StageTemplate.name == "Invented progress stage").delete()
        db.commit()


def test_a_hold_point_counts_once_certified(db):
    site, _floor = _site_with_done_steps(db, cache=False)
    step = db.scalar(select(StageTemplateStep).where(StageTemplateStep.name == "Step 1"))
    step.hold_point = True
    db.commit()
    assert progress.site_percents(db, [site.id])[site.id] == 25  # step 1 done but not certified
    t = db.scalar(select(Task).where(Task.step_id == step.id))
    t.status = "certified"
    db.commit()
    assert progress.site_percents(db, [site.id])[site.id] == 50


def test_a_5000_line_boq_opens_in_under_a_second(boss, db):  # noqa: F811
    import time

    from sqlalchemy import insert

    from app.tenders.models import BoqLine, Tender

    c, h = boss
    t = Tender(code="T-2026-9790", name="Invented long tender", status="draft")
    db.add(t)
    db.flush()
    db.execute(insert(BoqLine), [{"tender_id": t.id, "sort_order": i, "client_item_no": str(i), "description": f"Invented item {i} with a long description of the work", "unit": "sqm", "qty": Decimal(10), "rate": Decimal("888.82"), "cost_rate": Decimal("711.05")} for i in range(5000)])
    db.commit()
    c.get(f"/api/tenders/{t.id}/boq", headers=h)  # warm
    start = time.perf_counter()
    r = c.get(f"/api/tenders/{t.id}/boq", headers=h)
    took = time.perf_counter() - start
    assert r.status_code == 200
    assert len(r.json()["lines"]) == 5000
    assert took < 1.0, took


def test_a_site_without_areas_keeps_its_stored_progress(db):
    site = Site(code="S-P0-9002", name="Invented imported site", status="active", progress_percent=Decimal(40))
    db.add(site)
    db.commit()
    assert progress.site_percents(db, [site.id])[site.id] == 40
    assert progress.rollup(db, site.id)[0] == 40
    assert progress.refresh(db, site) == 40
