# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""From the process alerts review: short email subjects, one place per line, demo data never
reaching a real person, a reason when a to-do is closed by hand, and the named systems with
nothing guessed. Invented data only; no real email."""

from sqlalchemy import select, text

from app.db import engine as db_engine
from app.masters.models import Product, System, SystemComponent
from app.masters.named_systems import seed
from app.portal.models import Notification
from app.process import engine
from app.sites.models import Site
from app.survey.models import AreaType
from tests.conftest import login
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)
from tests.test_process import FakeMailer, notes, team  # noqa: F401  (fixtures)

LONG_PLACE = "Block A raft (HDPE line) near the north retaining wall and the lift pit of tower 4"


def _stage_done(db, site_id, area=LONG_PLACE, ready_id=7, extra=None):
    engine.emit(
        db,
        "stage_done",
        subject=f"ready:{ready_id}",
        site_id=site_id,
        data={
            "ready_id": ready_id,
            "area": area,
            "stage": "Toilet / wet area (coating)",
            "qty": "2000",
            "unit": "sqm",
            "date": "12 Oct 2026",
            "places": [{"place": area, "qty": "2000", "unit": "sqm"}],
            **(extra or {}),
        },
    )
    db.commit()


def test_email_subject_is_short_with_the_site_code_and_place(team, db):
    _stage_done(db, team["A"])
    billing = team["people"]["A"]["billing"]
    mail = FakeMailer()
    engine.send_pending(db, mailer=mail)
    sent = [m for m in mail.sent if m["to"] == billing.email]
    assert sent, "billing gets the stage-done email"
    subject = sent[0]["subject"]
    code = db.get(Site, team["A"]).code
    assert len(subject) <= 80
    assert subject.startswith(f"[EESPL] Work done, make the bill · {code} Block A raft")
    assert "(HDPE line)" not in subject  # the short place
    # the full message and the place stay in the body
    assert "make the stage bill" in sent[0]["text"]
    assert f"- {LONG_PLACE}: 2000 sqm" in sent[0]["text"]
    # every rule's subject stays within 80 characters, escalated or not
    for n in db.scalars(select(Notification).where(Notification.rule_code.is_not(None))):
        n.escalated = True
        assert len(engine.email_subject(db, n)) <= 80


def test_one_place_per_line_never_joined_into_the_message(team, db):
    _stage_done(db, team["A"], area="Block A raft (HDPE line)")
    n = next(x for x in notes(db, team["people"]["A"]["billing"]) if x.rule_code == "stage_done")
    assert "Block A raft" not in n.title and "Toilet / wet area" not in n.title
    assert n.body == "Block A raft (HDPE line): 2000 sqm"
    # two places done together: two messages, each with its own place and quantity
    _stage_done(db, team["A"], area="Toilet T2", ready_id=8)
    bodies = sorted(
        x.body for x in notes(db, team["people"]["A"]["billing"]) if x.rule_code == "stage_done"
    )
    assert bodies == ["Block A raft (HDPE line): 2000 sqm", "Toilet T2: 2000 sqm"]


def test_demo_events_never_notify_real_people(team, db, make_user):
    demo_sales = make_user("demo-sales@demo.invalid", "sales", name="DEMO Sales")
    real_sales = team["people"]["A"]["salesperson"]
    # a follow-up on a DEMO quotation: our salesperson and the DEMO one both hold the role
    for u in (demo_sales, real_sales):
        engine.emit(
            db,
            "followup_due",
            subject=f"followup:{u.email}",
            site_id=None,
            data={
                "quotation": "QTN-T R0",
                "quotation_id": 1,
                "client": "DEMO Ladani Associates",
                "day": 7,
                "salesperson_id": str(u.id),
            },
        )
    db.commit()
    assert [n for n in notes(db, demo_sales) if n.rule_code == "followup_due"]
    assert not [n for n in notes(db, real_sales) if n.rule_code == "followup_due"]
    # a demo site: nobody real is told either
    site = db.get(Site, team["A"])
    site.is_demo = True
    db.commit()
    _stage_done(db, site.id, area="Invented raft", ready_id=9)
    assert not [n for n in notes(db, team["people"]["A"]["billing"]) if n.rule_code == "stage_done"]
    # real data still reaches real people
    site.is_demo = False
    db.commit()
    _stage_done(db, site.id, area="Invented raft", ready_id=10)
    assert [n for n in notes(db, team["people"]["A"]["billing"]) if n.rule_code == "stage_done"]


def test_done_without_the_action_needs_a_reason_shown_on_the_timeline(team, db, client):
    _stage_done(db, team["A"], area="Invented terrace")
    billing = team["people"]["A"]["billing"]
    n = next(x for x in notes(db, billing) if x.rule_code == "stage_done")
    h = login(client, billing.email)
    r = client.post(f"/api/process/notifications/{n.id}/done", headers=h)
    assert r.status_code == 422 and "Start bill" in r.json()["detail"]
    r = client.post(f"/api/process/notifications/{n.id}/done", json={"reason": "  "}, headers=h)
    assert r.status_code == 422
    r = client.post(
        f"/api/process/notifications/{n.id}/done",
        json={"reason": "Billed by hand in the old sheet"},
        headers=h,
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Notification, n.id).closed_reason == "Billed by hand in the old sheet"
    steps = {
        s["code"]: s
        for s in client.get(f"/api/process/sites/{team['A']}/timeline", headers=h).json()["steps"]
    }
    assert steps["stage_done"]["reasons"][0]["reason"] == "Billed by hand in the old sheet"
    assert steps["stage_done"]["reasons"][0]["by"] == billing.full_name


def test_named_systems_have_no_guessed_consumption_or_coats(db):
    with db_engine.begin() as conn:
        # from scratch, whatever the migration seeded (the product was not there then)
        conn.execute(
            text(
                "DELETE FROM systems WHERE code IN ('CEMGUARD', 'CEMGUARD-PLUS', 'ULTRA-FLEX', 'HYBRID-PU')"
            )
        )
    with db_engine.begin() as conn:
        db.add(Product(code="BRONCO-HYBRID-PU", name="BRONCO HYBRID PU", unit="kg"))
        db.commit()
        ids = seed(conn)
        assert seed(conn) == ids  # safe to run again
    systems = {s.code: s for s in db.scalars(select(System).where(System.id.in_(ids.values())))}
    assert set(systems) == {"CEMGUARD", "CEMGUARD-PLUS", "ULTRA-FLEX", "HYBRID-PU"}
    assert all(s.to_confirm for s in systems.values())
    # Cemguard and Cemguard Plus ("Samgard"): the Bronco products, nothing guessed
    assert [c.product.code for c in systems["CEMGUARD"].components] == ["BRONCO-CEMGUARD"]
    comps = db.scalars(
        select(SystemComponent).where(SystemComponent.system_id.in_(ids.values()))
    ).all()
    assert len(comps) == 4
    assert all(c.consumption_per_unit is None and c.to_confirm for c in comps)
    hybrid = next(c for c in comps if c.system_id == ids["HYBRID-PU"])
    assert hybrid.product.code == "BRONCO-HYBRID-PU" and hybrid.coats is None  # the offers disagree
    flex = next(c for c in comps if c.system_id == ids["ULTRA-FLEX"])
    assert (
        flex.coats == 2 and "15-16 sqm per 25 kg" in flex.note
    )  # quoted, not turned into a number
    sunken = db.scalar(select(AreaType).where(AreaType.name == "Sunken slab"))
    assert sunken.default_system_id == ids["CEMGUARD-PLUS"]
    assert set(sunken.suitable_system_ids) == set(ids.values())
    # no rate until the consumption is confirmed
    from app.masters.rate import MissingConsumptionError, system_rate

    try:
        system_rate(db, systems["HYBRID-PU"])
        raise AssertionError("a rate was built from a blank consumption")
    except MissingConsumptionError as exc:
        assert "to confirm" in str(exc)
    # the seed's area types are put back for the other tests
    for name in ("Sunken slab", "Toilet / bathroom", "Terrace"):
        a = db.scalar(select(AreaType).where(AreaType.name == name))
        a.default_system_id, a.suitable_system_ids = None, []
    db.commit()
