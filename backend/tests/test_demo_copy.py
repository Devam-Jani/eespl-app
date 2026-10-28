# ruff: noqa: E501
"""Copying the DEMO company to another database (app.ops.democopy): only DEMO rows and what hangs
off them, never a real row, new ids with every link remapped, an excluded site left out with its
tender, and a second run adds nothing. One test database plays both sides: the export is taken,
the DEMO site removed, and the import brings it back."""

import json

from sqlalchemy import delete, func, select

from app.ops import democopy
from app.sites.models import Site, SiteMember, SiteNode
from app.tenders.models import Tender


def _demo_site(db, make_user) -> tuple[Site, object, object]:
    real = make_user("real-engineer@example.com", name="Real engineer")
    demo_user = make_user("demo-copy-engineer@demo.invalid", "site_engineer", name="DEMO engineer")
    demo_user.is_demo = True
    site = Site(code="DEMO-CPY-1", name="DEMO copy site", is_demo=True, created_by=real.id)
    db.add(site)
    db.flush()
    tower = SiteNode(site_id=site.id, kind="tower", name="DEMO Tower")
    db.add(tower)
    db.flush()
    db.add(SiteNode(site_id=site.id, parent_id=tower.id, kind="floor", name="DEMO Floor 1"))
    db.add(SiteMember(site_id=site.id, user_id=demo_user.id))
    # a real site the DEMO user also works on: real, never copied
    real_site = Site(code="S-REAL-1", name="Real client tower", is_demo=False)
    db.add(real_site)
    db.flush()
    db.add(SiteMember(site_id=real_site.id, user_id=demo_user.id))
    db.commit()
    return site, demo_user, real_site


def _drop_demo_site(db, site_id: int) -> None:
    db.execute(delete(SiteMember).where(SiteMember.site_id == site_id))
    db.execute(delete(SiteNode).where(SiteNode.site_id == site_id).where(SiteNode.parent_id.is_not(None)))
    db.execute(delete(SiteNode).where(SiteNode.site_id == site_id))
    db.execute(delete(Site).where(Site.id == site_id))
    db.commit()


def test_the_closure_takes_the_demo_rows_and_what_hangs_off_them_but_no_real_row(db, make_user):
    site, demo_user, real_site = _demo_site(db, make_user)
    found, left_out = democopy.closure(db)
    assert {r["code"] for r in found["sites"]} >= {"DEMO-CPY-1"}
    assert "S-REAL-1" not in {r["code"] for r in found["sites"]}
    nodes = [r for r in found["site_nodes"] if r["site_id"] == site.id]
    assert len(nodes) == 2
    members = [(r["site_id"], r["user_id"]) for r in found["site_members"]]
    assert (site.id, demo_user.id) in members
    assert (real_site.id, demo_user.id) not in members  # the real site's membership stays home
    assert any("a real sites row" in x for x in left_out["site_members"])
    assert "refresh_tokens" not in found and "audit_log" not in found


def test_the_import_brings_the_site_back_with_new_ids_and_a_second_run_adds_nothing(db, make_user):
    site, demo_user, real_site = _demo_site(db, make_user)
    data = json.loads(json.dumps(democopy.export(db)))  # through JSON, as it travels
    old_id = site.id
    _drop_demo_site(db, old_id)
    assert db.scalar(select(Site).where(Site.code == "DEMO-CPY-1")) is None

    plan = democopy.import_(db, data, None, dry_run=True)
    assert plan["inserted"]["sites"] == 1 and plan["inserted"]["site_nodes"] == 2
    assert db.scalar(select(Site).where(Site.code == "DEMO-CPY-1")) is None  # a dry run keeps nothing

    out = democopy.import_(db, data, None)
    assert out["inserted"]["sites"] == 1
    assert out["existing"]["users"] >= 1  # the DEMO user is already here: matched by email
    back = db.scalar(select(Site).where(Site.code == "DEMO-CPY-1"))
    assert back is not None and back.id != old_id and back.is_demo
    assert back.created_by is None  # a real user is never carried: the link is emptied
    nodes = {n.name: n for n in db.scalars(select(SiteNode).where(SiteNode.site_id == back.id))}
    assert nodes["DEMO Floor 1"].parent_id == nodes["DEMO Tower"].id  # links remapped
    assert db.scalar(select(func.count()).select_from(SiteMember).where(SiteMember.site_id == back.id)) == 1
    assert db.scalar(select(func.count()).select_from(SiteMember).where(SiteMember.site_id == real_site.id)) == 1

    again = democopy.import_(db, data, None)
    assert not again["inserted"]
    assert db.scalar(select(func.count()).select_from(Site).where(Site.code == "DEMO-CPY-1")) == 1


def test_an_excluded_site_is_left_out_with_its_tender_and_what_hangs_off_them(db, make_user):
    site, _, _ = _demo_site(db, make_user)
    tender = Tender(code="T-DEMO-CPY", name="DEMO built from a client's drawings", is_demo=True)
    db.add(tender)
    db.flush()
    site.tender_id = tender.id
    db.commit()
    found, left_out = democopy.closure(db, ("DEMO-CPY-1",))
    assert "DEMO-CPY-1" not in {r["code"] for r in found.get("sites", [])}
    assert "T-DEMO-CPY" not in {r["code"] for r in found.get("tenders", [])}
    assert not [r for r in found.get("site_nodes", []) if r["site_id"] == site.id]
    assert any("DEMO-CPY-1" in x for x in left_out["sites"])


def test_values_survive_the_trip_through_json():
    from datetime import UTC, date, datetime
    from decimal import Decimal
    from uuid import uuid4

    u = uuid4()
    vals = [Decimal("12.345"), date(2026, 10, 28), datetime(2026, 10, 28, 5, 30, tzinfo=UTC), u, b"\x00\x01", {"a": [1, 2]}, [1, "x"], None, "text"]
    back = [democopy.dec(json.loads(json.dumps(democopy.enc(v)))) for v in vals]
    assert back == vals
