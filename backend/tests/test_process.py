# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""The process chain: one event layer, the 23 seeded rules (plus the follow-up schedule and the
Kylas quotation stage), to-dos that close themselves, escalations on a frozen clock, email to our
staff only through a fake mailer, and the rules settings. Invented data only; no real email."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.portal.models import Notification, NotificationOutbox
from app.process import engine
from app.process.models import ProcessEvent, ProcessPreference, ProcessRule
from app.process.rules import DEFAULT_RULES
from app.sites.models import AreaScope, Site, SiteMember, SiteNode
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)

ROLE_ON_SITE = {"salesperson": "sales", "site_engineer": "incharge", "supervisor": "supervisor"}
COMPANY_ROLES = {
    "planning": "planning",
    "billing": "billing",
    "accounts": "accounts",
    "store_purchase": "store_purchase",
    "estimator": "estimator",
    "director": "director",
    "office_admin": "office_admin",
}


class FakeMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    def send(self, to, subject, text, html=None):
        if self.fail:
            raise OSError("invented SMTP failure")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


@pytest.fixture
def team(world, make_user, db):
    """Two sites. On site A everyone has their role (sales, engineer, supervisor as members; the
    company roles as members too); site B has its own salesperson, engineer and supervisor."""
    a = db.get(Site, world["site"])
    b = Site(code="S-2026-9902", name="Invented Site B", status="active")
    db.add(b)
    db.flush()
    people: dict[str, dict[str, User]] = {"A": {}, "B": {}}
    for key, code in COMPANY_ROLES.items():
        u = make_user(f"{key.replace('_', '-')}@example.com", code, name=f"Invented {key}")
        people["A"][key] = u
        if key in ("planning", "billing", "accounts", "store_purchase", "estimator"):
            db.add(SiteMember(site_id=a.id, user_id=u.id, role_on_site="office"))
    for site, tag in ((a, "A"), (b, "B")):
        for key, member_role in ROLE_ON_SITE.items():
            code = {
                "salesperson": "sales",
                "site_engineer": "site_engineer",
                "supervisor": "site_supervisor",
            }[key]
            u = make_user(
                f"{key.replace('_', '-')}-{tag.lower()}@example.com",
                code,
                name=f"Invented {key} {tag}",
            )
            people[tag][key] = u
            db.add(SiteMember(site_id=site.id, user_id=u.id, role_on_site=member_role))
            if key == "site_engineer":
                site.site_incharge_id = u.id
    db.commit()
    return {"A": a.id, "B": b.id, "people": people}


def notes(db, user) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.rule_code.is_not(None)
            )
        )
    )


SAMPLE_DATA = {
    "lead": "L-T",
    "lead_id": 1,
    "name": "Invented",
    "city": "Ahmedabad",
    "phone": "+91",
    "requirement": "terrace",
    "what": "QTN-T",
    "missing": "guarantee",
    "link": "/x",
    "quotation": "QTN-T R0",
    "quotation_id": 1,
    "client": "Invented Client",
    "day": 2,
    "asked": "match X",
    "tender": "T-T",
    "tender_id": 1,
    "title": "Invented job",
    "assignment_id": 1,
    "area": "Block A raft",
    "node_id": 1,
    "qty": "2000",
    "unit": "sqm",
    "wastage": "raft 5-7%",
    "indent": "IND-T",
    "indent_id": 1,
    "dn": "DN-T",
    "dn_id": 1,
    "items": "PU 100 ltr",
    "expected": "12 Oct",
    "date": "12 Oct",
    "stage": "Coating",
    "ready_id": 1,
    "bill": "RA-T",
    "amount": "₹1,00,000",
    "certified": "₹90,000",
    "billed": "₹1,00,000",
    "contractor": "Invented Applicators",
    "check": "low",
    "flags": 2,
    "flagged": True,
    "author_id": None,
}


@pytest.mark.parametrize("rule", DEFAULT_RULES, ids=[r["code"] for r in DEFAULT_RULES])
def test_each_rule_tells_the_right_people_on_its_site_and_nobody_on_another(rule, team, db):
    people = team["people"]
    data = dict(SAMPLE_DATA, author_id=str(people["A"]["salesperson"].id))
    ev = engine.emit(
        db, rule["event"], subject=f"test:{rule['code']}", site_id=team["A"], data=data
    )
    db.commit()
    assert ev is not None
    for entry in rule["recipients"]:
        role = entry["role"]
        who = people["A"]["salesperson"] if role == "author" else people["A"][role]
        got = [n for n in notes(db, who) if n.rule_code == rule["code"]]
        assert got, f"{role} got nothing for {rule['code']}"
        assert got[0].site_id == team["A"] and got[0].needs_action == (not entry.get("info"))
        assert "—" not in got[0].title or rule["code"] in ("lead_allocated",), got[0].title
    for user in people["B"].values():
        assert notes(db, user) == [], f"{user.full_name} on site B was told about site A"


def test_a_retried_event_makes_no_duplicates_and_the_to_do_closes_when_done(team, db):
    people = team["people"]
    for _ in range(2):  # the same step twice (a retry)
        engine.emit(
            db,
            "dpr_submitted",
            subject="dpr:77",
            site_id=team["A"],
            data={"date": "12 Oct", "day": "2026-10-12"},
        )
    db.commit()
    eng = people["A"]["site_engineer"]
    assert (
        len(notes(db, eng)) == 1
        and db.scalar(select(ProcessEvent).where(ProcessEvent.subject == "dpr:77")) is not None
    )
    engine.emit(
        db,
        "dpr_reviewed",
        subject="dpr:77",
        site_id=team["A"],
        actor_id=eng.id,
        dedupe="dpr_reviewed:77:a",
    )
    db.commit()
    n = notes(db, eng)[0]
    assert n.closed_at is not None and n.closed_by == eng.id


def test_stage_done_tells_billing_then_the_director_after_7_days_until_the_bill_is_sent(
    boss, team, db
):
    c, h = boss
    contract(c, h, world_from(team, db))
    scope = db.get(
        AreaScope,
        db.scalar(
            select(AreaScope.id).where(AreaScope.site_id == team["A"]).order_by(AreaScope.id)
        ),
    )
    body = {
        "work_done": "Invented coating",
        "lines": [
            {
                "description": "PU coating",
                "qty": str(scope.qty),
                "unit": "sqm",
                "node_id": scope.node_id,
                "area_scope_id": scope.id,
            }
        ],
        "submit": True,
    }
    d = c.put(
        f"/api/execution/sites/{team['A']}/dprs/{date.today().isoformat()}", json=body, headers=h
    ).json()
    assert c.post(f"/api/execution/dprs/{d['id']}/acknowledge", headers=h).status_code == 200
    billing = team["people"]["A"]["billing"]
    got = [n for n in notes(db, billing) if n.rule_code == "stage_done"]
    assert (
        len(got) == 1
        and f"{Decimal(scope.qty).normalize():f} sqm" in (got[0].body or "")  # one place per line
        and got[0].link.startswith("/ready-to-bill")
    )
    assert got[0].action_label == "Start bill"
    sales = [
        n for n in notes(db, team["people"]["A"]["salesperson"]) if n.rule_code == "stage_done"
    ]
    assert sales and not sales[0].needs_action  # information for the salesperson
    director = team["people"]["A"]["director"]
    start = got[0].created_at
    engine.escalate(db, start + timedelta(days=6, hours=23))
    db.commit()
    assert not [n for n in notes(db, director) if n.rule_code == "stage_done"]
    engine.escalate(db, start + timedelta(days=7, hours=1))
    db.commit()
    esc = [n for n in notes(db, director) if n.rule_code == "stage_done"]
    assert len(esc) == 1 and esc[0].escalated and "Escalated" in esc[0].title
    engine.escalate(db, start + timedelta(days=9))  # once, not again on every tick
    db.commit()
    assert len([n for n in notes(db, director) if n.rule_code == "stage_done"]) == 1
    # the bill is sent: the to-do and its escalation close
    ra = c.post(
        "/api/sitecontrol/ready-to-bill/raise", json={"site_id": team["A"]}, headers=h
    ).json()
    assert c.post(f"/api/finance/ra-bills/{ra['ra_bill_id']}/submit", headers=h).status_code == 200
    db.expire_all()
    assert all(n.closed_at for n in notes(db, director) if n.rule_code == "stage_done")
    assert all(n.closed_at for n in notes(db, billing) if n.rule_code == "stage_done")


def world_from(team, db):
    """The finance world fixture's site is site A (contract() needs its dict)."""
    return {"site": team["A"]}


def test_a_ready_work_front_prefills_the_material_plan_with_the_application_wastage(boss, team, db):
    from app.masters.models import Product, System, SystemComponent
    from app.tenders.models import BoqLine

    c, h = boss
    p = Product(code="WF-HDPE", name="Invented HDPE membrane", unit="sqm")
    sysm = System(code="WF-SYS", name="Invented raft system", unit="sqm", labour_rate=10)
    db.add_all([p, sysm])
    db.flush()
    db.add(
        SystemComponent(
            system_id=sysm.id, product_id=p.id, consumption_per_unit=1, wastage_percent=2
        )
    )
    boq = db.scalar(
        select(BoqLine)
        .join(AreaScope, AreaScope.boq_line_id == BoqLine.id)
        .where(AreaScope.site_id == team["A"])
    )
    boq.system_id = sysm.id
    raft = SiteNode(site_id=team["A"], kind="raft", name="Block A raft")
    footing = SiteNode(site_id=team["A"], kind="other", name="Block A footing F1")
    db.add_all([raft, footing])
    db.flush()
    for node in (raft, footing):
        db.add(
            AreaScope(
                site_id=team["A"],
                node_id=node.id,
                boq_line_id=boq.id,
                stage_template_id=db.scalar(
                    select(AreaScope.stage_template_id)
                    .where(AreaScope.site_id == team["A"])
                    .limit(1)
                ),
                qty=2000 if node is raft else 100,
                progress_percent=0,
            )
        )
    db.commit()
    for node, pct, qty in ((raft, 7, 2000), (footing, 15, 100)):
        r = c.post(
            f"/api/sites/{team['A']}/nodes/{node.id}/front-ready", data={"ready": "true"}, headers=h
        )
        assert r.status_code == 200, r.text
        planning = team["people"]["A"]["planning"]
        got = [
            n
            for n in notes(db, planning)
            if n.rule_code == "front_ready" and n.subject == f"node:{node.id}"
        ]
        assert got and f"node={node.id}" in got[0].link and f"{qty} sqm" in got[0].title
        plan = c.get(f"/api/team/material-plan/{team['A']}?node={node.id}", headers=h).json()
        assert plan["wastage"]["used"] == pct and plan["area"].endswith(node.name)
        row = next(x for x in plan["products"] if x["product"] == "Invented HDPE membrane")
        assert Decimal(row["planned"]) == Decimal(qty) * (1 + Decimal(pct) / 100)
    # the indent from the plan closes the planner's to-do
    r = c.post(
        f"/api/team/material-plan/{team['A']}/indent",
        json={"lines": [{"product_id": p.id, "qty": "2140"}], "node_ids": [raft.id]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    db.expire_all()
    assert all(
        n.closed_at
        for n in notes(db, team["people"]["A"]["planning"])
        if n.subject == f"node:{raft.id}"
    )


def test_the_escalation_chain_on_a_frozen_clock_and_information_never_escalates(team, db):
    people = team["people"]
    t0 = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)
    engine.emit(
        db,
        "job_won",
        subject="assignment:900",
        site_id=team["A"],
        at=t0,
        data={"title": "Invented win", "assignment_id": 900},
    )
    engine.emit(
        db,
        "delivery_confirmed",
        subject="dn:900",
        site_id=team["A"],
        at=t0,
        data={"dn": "DN-T", "dn_id": 900},
    )
    db.commit()
    director, office = people["A"]["director"], people["A"]["office_admin"]
    engine.escalate(db, t0 + timedelta(hours=23))
    assert [n.escalation_level for n in notes(db, director)] == [0]
    engine.escalate(db, t0 + timedelta(hours=25))
    assert sorted(n.escalation_level for n in notes(db, director)) == [0, 1]
    assert not [n for n in notes(db, office) if n.rule_code == "job_won"]
    engine.escalate(db, t0 + timedelta(hours=49))
    assert [n.escalation_level for n in notes(db, office) if n.rule_code == "job_won"] == [2]
    db.commit()
    # information-only (delivery confirmed) never escalates, however long it waits
    engine.escalate(db, t0 + timedelta(days=30))
    assert not [
        n
        for n in db.scalars(
            select(Notification).where(
                Notification.rule_code == "delivery_confirmed", Notification.escalated
            )
        )
    ]


def test_email_goes_by_preference_to_staff_only_hides_amounts_and_a_failure_blocks_nothing(
    team, db, make_user
):
    from app.portal.models import ClientUser

    people = team["people"]
    sales, director = people["A"]["salesperson"], people["A"]["director"]
    # a client login that is somehow a member of the site is never emailed
    client = make_user("client-x@example.com", "client", name="Invented Client User")
    db.add(SiteMember(site_id=team["A"], user_id=client.id, role_on_site="sales"))
    db.add(
        ClientUser(
            user_id=client.id,
            client_id=db.scalar(select(Site.client_id).where(Site.id == team["A"])),
        )
    )
    engine.ensure_rules(db)
    db.add(
        ProcessPreference(user_id=sales.id, rule_code="payment_received", mode="email")
    )  # info: app by default
    db.commit()
    engine.emit(
        db,
        "payment_received",
        subject="receipt:1",
        site_id=team["A"],
        data={"client": "Invented Client", "amount": "₹2,50,000"},
    )
    db.commit()
    s_note = next(n for n in notes(db, sales) if n.rule_code == "payment_received")
    d_note = next(n for n in notes(db, director) if n.rule_code == "payment_received")
    assert "₹2,50,000" in s_note.title and "₹2,50,000" in d_note.title  # bill amounts: both
    # costs and margins only with tender.margin; amounts only for roles that may see them
    tpl = "cost {cost}, margin {margin}, amount {amount}"
    fields = {"cost": "₹320", "margin": "36%", "amount": "₹500"}
    assert (
        engine.render(tpl, fields, engine.perms_of(db, sales))
        == "cost cost not shown, margin margin not shown, amount ₹500"
    )
    assert (
        engine.render(tpl, fields, engine.perms_of(db, director))
        == "cost ₹320, margin 36%, amount ₹500"
    )
    sup = people["A"]["supervisor"]
    assert "₹500" not in engine.render(tpl, fields, engine.perms_of(db, sup))
    assert not notes(db, client)
    mail = FakeMailer()
    engine.send_pending(db, mailer=mail)
    db.commit()
    assert [m["to"] for m in mail.sent] == [
        sales.email
    ]  # the director chose nothing: info is app only
    assert "EESPL" in mail.sent[0]["html"] and "₹320" not in mail.sent[0]["html"]
    # a failing mailer: the step was already saved; the email is retried, then shown as failed
    engine.emit(
        db,
        "job_won",
        subject="assignment:901",
        site_id=team["A"],
        data={"title": "Invented win 2", "assignment_id": 901},
    )
    db.commit()
    broken = FakeMailer(fail=True)
    at = datetime.now(UTC)
    for i in range(6):
        engine.send_pending(db, at=at + timedelta(hours=i * 7), mailer=broken)
    db.commit()
    note = next(n for n in notes(db, director) if n.rule_code == "job_won")
    assert note.email_status == "failed" and db.get(ProcessEvent, note.event_id) is not None
    row = db.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.notification_id == note.id, NotificationOutbox.channel == "email"
        )
    )
    assert row.status == "failed" and "invented SMTP failure" in row.error


def test_the_daily_summary_groups_the_days_items(team, db):
    people = team["people"]
    billing = people["A"]["billing"]
    engine.ensure_rules(db)
    for code in ("stage_done", "monthly_ra_due", "labour_bill_entered"):
        db.add(ProcessPreference(user_id=billing.id, rule_code=code, mode="summary"))
    engine.ensure_rules(db)
    db.commit()
    for i, (event, subject) in enumerate(
        (
            ("stage_done", "ready:1"),
            ("monthly_ra_due", "site:x"),
            ("labour_bill_entered", "subcon:1"),
        )
    ):
        engine.emit(
            db,
            event,
            subject=subject,
            site_id=team["A"],
            data=dict(SAMPLE_DATA, flagged=False),
            dedupe=f"sum:{i}",
        )
    db.commit()
    mail = FakeMailer()
    assert engine.send_pending(db, mailer=mail) == {"sent": 0, "failed": 0}  # nothing until 9:00
    nine = datetime(2026, 10, 13, 3, 35, tzinfo=UTC)  # 9:05 IST
    assert engine.daily_summary(db, at=nine, mailer=mail) >= 1
    mine = [m for m in mail.sent if m["to"] == billing.email]
    assert len(mine) == 1 and "3 items" in mine[0]["subject"]
    assert engine.daily_summary(db, at=nine + timedelta(hours=1), mailer=mail) == 0  # once a day


def test_rule_edits_are_logged_and_a_switched_off_rule_sends_nothing(boss, team, db):
    c, h = boss
    rules = c.get("/api/process/rules", headers=h).json()["rules"]
    assert len(rules) == len(DEFAULT_RULES) and [r["number"] for r in rules][:3] == [1, 2, 3]
    r = c.put("/api/process/rules/indent_approved", json={"is_active": False}, headers=h)
    assert r.status_code == 200 and not r.json()["is_active"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "process.rule"))
    engine.emit(
        db,
        "indent_approved",
        subject="indent:5",
        site_id=team["A"],
        data={"indent": "IND-T", "indent_id": 5},
    )
    db.commit()
    assert not notes(db, team["people"]["A"]["store_purchase"])
    # information-only rules never get an escalation
    r = c.put(
        "/api/process/rules/delivery_confirmed",
        json={"escalations": [{"after_hours": 5, "to": ["director"]}]},
        headers=h,
    )
    assert r.status_code == 422
    r = c.put(
        "/api/process/settings",
        json={"stage_bill_days": 5, "wastage": {"raft": {"min": 5, "max": 8}}},
        headers=h,
    )
    assert r.json()["stage_bill_days"] == 5 and r.json()["wastage"]["raft"]["max"] == 8
    assert db.get(ProcessRule, "stage_done").escalations[0]["after_hours"] == 120


def test_no_planner_on_the_site_goes_to_the_default_user(boss, team, db, make_user):
    c, h = boss
    mr_sunil = make_user("invented-planner@example.com", "planning", name="Invented Planner")
    c.put(
        "/api/process/settings", json={"default_users": {"planning": str(mr_sunil.id)}}, headers=h
    )
    engine.emit(
        db,
        "front_ready",
        subject="node:42",
        site_id=team["B"],
        data={"area": "Invented place", "node_id": 42, "qty": "10", "unit": "sqm", "wastage": "—"},
    )
    db.commit()
    got = notes(db, mr_sunil)
    assert got and got[0].note is None  # an office role: the default user is the normal case


def test_site_timeline_includes_the_steps_before_the_job_had_a_site(team, db, client):
    """Enquiry, quotation and follow-ups happen before the win links the quotation to a site:
    the site's Process tab still shows them (by subject), and another site's does not."""
    from app.quotations.models import Quotation
    from tests.conftest import login

    q = Quotation(
        code="QTN-T-77",
        client_firm="Invented Client",
        project="Invented job",
        quote_date=date(2026, 10, 1),
        lead_id=None,
    )
    db.add(q)
    db.flush()
    engine.emit(
        db,
        "quotation_sent",
        subject="quotation:QTN-T-77",
        data=dict(SAMPLE_DATA, salesperson_id=None),
    )
    q.site_id = team["A"]  # won on site A
    db.commit()
    login_user = team["people"]["A"]["office_admin"]
    headers = login(client, login_user.email)
    steps = {
        s["code"]: s
        for s in client.get(f"/api/process/sites/{team['A']}/timeline", headers=headers).json()[
            "steps"
        ]
    }
    assert steps["quotation_sent"]["state"] in ("done", "waiting")
    other = {
        s["code"]: s
        for s in client.get(f"/api/process/sites/{team['B']}/timeline", headers=headers).json()[
            "steps"
        ]
    }
    assert other["quotation_sent"]["state"] == "not_reached"


def test_office_roles_are_told_without_a_no_one_assigned_note(team, db):
    """Billing is not a site role: everyone holding it (or the default user) is told, no gap flagged."""
    b = Site(code="S-2026-9903", name="Invented Site C", status="active")
    db.add(b)
    db.commit()
    engine.emit(db, "stage_done", subject="ready:9", site_id=b.id, data=SAMPLE_DATA)
    db.commit()
    got = [n for n in notes(db, team["people"]["A"]["billing"]) if n.rule_code == "stage_done"]
    assert len(got) == 1 and got[0].note is None
