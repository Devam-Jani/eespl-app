# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Team roles and workspaces: roles and grants, My work per role, enquiry allocation, decisions
on won jobs, the status board and allocation list, the measurement book and the monthly RA
to-do, awaiting award and the winner follow-up, the send checklist, daily report approval and the
stage quality checklist. Invented data only."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics import alerts
from app.analytics.models import Alert
from app.crm.models import Lead
from app.execution.models import ChecklistTemplate, Dpr, Inspection
from app.main import app
from app.masters.models import TcClause
from app.models import AuditLog, Role, User
from app.portal.models import Notification
from app.sites import work
from app.sites.models import AreaScope, Site, SiteMember, Task
from app.team import mywork
from app.team.models import JobAssignment, Measurement, UserGrant
from app.tenders.models import BoqLine, Tender, TenderTc
from tests.conftest import login
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)


def D(x) -> Decimal:
    return Decimal(str(x))


@pytest.fixture
def person(make_user, db):
    """A user with roles, optionally a member of a site; returns (client, headers, user)."""

    def _person(email: str, *roles: str, site_id: int | None = None, role_on_site: str = "viewer"):
        u = make_user(email, *roles, name=f"Invented {email.split('@')[0]}")
        if site_id:
            db.add(SiteMember(site_id=site_id, user_id=u.id, role_on_site=role_on_site))
            db.commit()
        c = TestClient(app)
        return c, login(c, email), u

    return _person


def sources(c, h, role: str | None = None) -> dict[str, set[str]]:
    data = c.get("/api/team/my-work", headers=h).json()
    return {
        s["role"]: {i["source"] for i in s["items"]}
        for s in data["sections"]
        if role is None or s["role"] == role
    }


# --- roles ---------------------------------------------------------------------------------------


def test_a_person_with_two_roles_gets_the_union_and_grants_add_on_top(person, db):
    c, h, u = person("two@example.com", "billing", "planning")
    perms = c.get("/api/auth/me", headers=h).json()["permissions"]
    assert {"measurement.edit", "leads.allocate", "planning.edit", "labourcheck.check"} <= set(
        perms
    )
    assert "tender.margin" not in perms and "payables.view" not in perms
    d, dh, _ = person("dir@example.com", "director")
    assert (
        d.put(
            f"/api/team/users/{u.id}/grants", json={"codes": ["tender.margin"]}, headers=dh
        ).status_code
        == 200
    )
    assert c.get("/api/auth/me", headers=h).json()["permissions"]["tender.margin"] == "all"
    assert (
        d.put(
            f"/api/team/users/{u.id}/grants", json={"codes": ["payables.view"]}, headers=dh
        ).status_code
        == 422
    )
    assert c.put(f"/api/team/users/{u.id}/grants", json={"codes": []}, headers=h).status_code == 403
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.grants"))


def test_the_role_grid_is_logged_and_the_director_and_super_admin_cannot_be_reduced(boss, db):
    c, h = boss
    roles = {r["code"]: r for r in c.get("/api/roles", headers=h).json()}
    planning = roles["planning"]
    perms = {**planning["permissions"], "reports.export": "all"}
    r = c.put(f"/api/roles/{planning['id']}/permissions", json={"permissions": perms}, headers=h)
    assert r.status_code == 200 and r.json()["permissions"]["reports.export"] == "all"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "role.permissions_update"))
    director = roles["director"]
    fewer = {k: v for k, v in director["permissions"].items() if k != "tender.margin"}
    r = c.put(f"/api/roles/{director['id']}/permissions", json={"permissions": fewer}, headers=h)
    assert r.status_code == 409 and "tender.margin" in r.json()["detail"]
    more = {**director["permissions"], "admin.settings": "all"}
    assert (
        c.put(
            f"/api/roles/{director['id']}/permissions", json={"permissions": more}, headers=h
        ).status_code
        == 200
    )
    sa = roles["super_admin"]
    assert (
        c.put(f"/api/roles/{sa['id']}/permissions", json={"permissions": {}}, headers=h).status_code
        == 409
    )


def test_site_roles_see_only_their_sites_and_the_client_gets_403(boss, world, person, db, login_as):
    c, h = boss
    other = c.post(
        "/api/sites", json={"name": "Invented Other Site", "state": "Gujarat"}, headers=h
    ).json()
    e, eh, _ = person(
        "eng@example.com", "site_engineer", site_id=world["site"], role_on_site="incharge"
    )
    board = e.get("/api/team/board", headers=eh).json()
    assert {s["id"] for s in board["sites"]} == {world["site"]}
    assert e.get(f"/api/team/measurements?site_id={other['id']}", headers=eh).status_code == 404
    assert e.get(f"/api/team/measurements?site_id={world['site']}", headers=eh).status_code == 200
    cl, ch = login_as("client", email="customer@example.com")
    for path in (
        "/api/team/my-work",
        "/api/team/board",
        "/api/team/scorecard",
        "/api/team/enquiries",
    ):
        assert cl.get(path, headers=ch).status_code == 403, path


def test_sales_sees_only_their_own_scorecard_and_visits(boss, world, person, db):
    s1, h1, u1 = person("s1@example.com", "sales")
    s2, h2, u2 = person("s2@example.com", "sales")
    db.add(SiteMember(site_id=world["site"], user_id=u1.id, role_on_site="sales"))
    db.add(SiteMember(site_id=world["site"], user_id=u2.id, role_on_site="sales"))
    db.commit()
    r = s1.post(
        "/api/team/site-visits",
        data={"site_id": str(world["site"]), "notes": "Invented visit by s1"},
        headers=h1,
    )
    assert r.status_code == 201, r.text
    s2.post(
        "/api/team/site-visits",
        data={"site_id": str(world["site"]), "notes": "Invented visit by s2"},
        headers=h2,
    )
    assert [
        v["by"] for v in s1.get(f"/api/team/site-visits?site_id={world['site']}", headers=h1).json()
    ] == ["Invented s1"]
    assert [x["name"] for x in s1.get("/api/team/scorecard", headers=h1).json()] == ["Invented s1"]
    c, h = boss
    d, dh, _ = person("d@example.com", "director")
    assert {x["name"] for x in d.get("/api/team/scorecard", headers=dh).json()} >= {
        "Invented s1",
        "Invented s2",
    }


# --- My work -------------------------------------------------------------------------------------


def test_my_work_lists_each_roles_items_and_nothing_from_other_roles(boss, world, person, db):
    from app.sitecontrol.models import ReadyToBill

    c, h = boss
    db.add(Lead(code="L-2026-9001", contact_name="Invented Enquirer", status="new"))  # unassigned
    db.add(
        ReadyToBill(
            site_id=world["site"],
            node_id=db.get(AreaScope, world["scopes"][0]).node_id,
            area_scope_id=world["scopes"][0],
            qty=10,
            unit="sqm",
            status="open",
        )
    )
    db.commit()
    p, ph, _ = person("plan@example.com", "planning")
    b, bh, _ = person("bill@example.com", "billing")
    sup, sh, _ = person(
        "sup@example.com", "site_supervisor", site_id=world["site"], role_on_site="supervisor"
    )
    two, th, _ = person("both@example.com", "planning", "billing")
    plan = sources(p, ph)
    assert (
        set(plan) == {"planning"}
        and "unassigned_lead" in plan["planning"]
        and "ready" not in plan["planning"]
    )
    bill = sources(b, bh)
    assert (
        set(bill) == {"billing"}
        and "ready" in bill["billing"]
        and "unassigned_lead" not in bill["billing"]
    )
    sv = sources(sup, sh)
    assert set(sv) == {"site_supervisor"} and {"attendance", "dpr_today"} <= sv["site_supervisor"]
    both = sources(two, th)
    assert set(both) == {"planning", "billing"}
    counts = two.get("/api/team/my-work", headers=th).json()["counts"]
    assert counts["/ready-to-bill"] == 1 and counts["/my-work"] >= 2


# --- enquiries and won jobs ----------------------------------------------------------------------


def test_unassigned_enquiry_goes_to_a_salesperson(person, db):
    p, ph, _ = person("plan@example.com", "planning")
    s, sh, su = person("sales@example.com", "sales")
    r = p.post(
        "/api/team/enquiries",
        json={"name": "Invented Bungalow Owner", "phone": "+91 90000 12345", "city": "Ahmedabad"},
        headers=ph,
    )
    assert r.status_code == 201, r.text
    lead_id = r.json()["id"]
    assert [x["id"] for x in p.get("/api/team/enquiries", headers=ph).json()] == [lead_id]
    assert (
        s.post(
            f"/api/team/enquiries/{lead_id}/allocate", json={"owner_id": str(su.id)}, headers=sh
        ).status_code
        == 403
    )
    r = p.post(f"/api/team/enquiries/{lead_id}/allocate", json={"owner_id": str(su.id)}, headers=ph)
    assert r.status_code == 200
    assert p.get("/api/team/enquiries", headers=ph).json() == []
    assert "lead_new" in sources(s, sh)["sales"]
    assert db.scalar(
        select(Notification).where(
            Notification.user_id == su.id, Notification.kind == "lead_allocated"
        )
    )


def test_a_win_asks_the_director_who_handles_it_then_the_salesperson_must_visit(
    boss, world, person, db
):
    c, h = boss
    t = Tender(
        code="T-2026-9002", name="Invented Villa", status="submitted", client_id=world["client"]
    )
    db.add(t)
    db.commit()
    r = c.patch(f"/api/tenders/{t.id}", json={"status": "won"}, headers=h)
    assert r.status_code == 200, r.text
    a = db.scalar(select(JobAssignment).where(JobAssignment.tender_id == t.id))
    assert a is not None and a.status == "pending"
    d, dh, _ = person("dir@example.com", "director")
    p, ph, pu = person("plan@example.com", "planning")
    s, sh, su = person("sales@example.com", "sales")
    e, eh, eu = person("eng@example.com", "site_engineer")
    assert "assign" in sources(d, dh)["director"]
    body = {"salesperson_id": str(su.id), "engineer_id": str(eu.id)}
    assert p.post(f"/api/team/assignments/{a.id}/decide", json=body, headers=ph).status_code == 403
    r = d.post(f"/api/team/assignments/{a.id}/decide", json=body, headers=dh)
    assert r.status_code == 200, r.text
    db.expire_all()
    site = db.get(Site, r.json()["site_id"])
    roles = {
        (m.user_id, m.role_on_site)
        for m in db.scalars(select(SiteMember).where(SiteMember.site_id == site.id))
    }
    assert (su.id, "sales") in roles and (eu.id, "incharge") in roles
    assert site.site_incharge_id == eu.id and site.board_status == "upcoming"
    assert "first_visit" in sources(s, sh)["sales"]
    s.post(
        "/api/team/site-visits",
        data={
            "site_id": str(site.id),
            "notes": "Invented first visit",
            "lat": "23.0",
            "lng": "72.5",
        },
        headers=sh,
    )
    assert "first_visit" not in sources(s, sh)["sales"]
    db.expire_all()
    assert db.get(JobAssignment, a.id).first_visit_id is not None
    # planning decides only when the director allows the person
    t2 = Tender(
        code="T-2026-9003",
        name="Invented Row Houses",
        status="submitted",
        client_id=world["client"],
    )
    db.add(t2)
    db.commit()
    c.patch(f"/api/tenders/{t2.id}", json={"status": "won"}, headers=h)
    a2 = db.scalar(select(JobAssignment).where(JobAssignment.tender_id == t2.id))
    db.add(UserGrant(user_id=pu.id, permission_code="jobs.assign"))
    db.commit()
    assert p.post(f"/api/team/assignments/{a2.id}/decide", json=body, headers=ph).status_code == 200


# --- the status board ----------------------------------------------------------------------------


def test_a_site_engineer_moves_their_own_site_and_planning_exports_the_list(
    boss, world, person, db
):
    c, h = boss
    other = c.post(
        "/api/sites", json={"name": "Invented Other Site", "state": "Gujarat"}, headers=h
    ).json()
    e, eh, _ = person(
        "eng@example.com", "site_engineer", site_id=world["site"], role_on_site="incharge"
    )
    assert (
        e.post(f"/api/team/board/{world['site']}", json={"column": "ongoing"}, headers=eh).json()[
            "column"
        ]
        == "ongoing"
    )
    assert (
        e.post(f"/api/team/board/{other['id']}", json={"column": "ongoing"}, headers=eh).status_code
        == 403
    )
    p, ph, pu = person("plan@example.com", "planning")
    assert (
        p.post(
            f"/api/team/board/{other['id']}", json={"column": "upcoming"}, headers=ph
        ).status_code
        == 200
    )
    board = p.get("/api/team/board", headers=ph).json()
    cols = {s["id"]: s["column"] for s in board["sites"]}
    assert cols[world["site"]] == "ongoing" and cols[other["id"]] == "upcoming"
    pdf = p.get("/api/team/allocation-list?format=pdf", headers=ph)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    xlsx = p.get("/api/team/allocation-list?format=xlsx", headers=ph)
    assert xlsx.content[:2] == b"PK"
    assert (
        p.post("/api/team/allocation-list/send", headers=ph).status_code == 409
    )  # no recipients yet
    p.put("/api/team/settings", json={"allocation_recipients": [str(pu.id)]}, headers=ph)
    assert p.post("/api/team/allocation-list/send", headers=ph).json() == {"sent_to": 1}


# --- the measurement book and the monthly RA bill ------------------------------------------------


def test_the_measurement_book_feeds_the_ra_bill_and_the_monthly_to_do(
    boss, world, person, db, monkeypatch
):
    c, h = boss
    k = contract(c, h, world)  # measures the work done so far (70 sqm PU, 10 rmt coving)
    pu = next(x for x in k["lines"] if x["description"] == "PU coating")
    b, bh, _ = person("bill@example.com", "billing")
    r = b.post(
        "/api/team/measurements",
        json={
            "site_id": world["site"],
            "contract_line_id": pu["id"],
            "qty": "5",
            "source": "client_certified",
        },
        headers=bh,
    )
    assert r.status_code == 201 and r.json()["source"] == "client_certified"
    book = b.get(f"/api/team/measurements?site_id={world['site']}", headers=bh).json()
    line = next(x for x in book["lines"] if x["id"] == pu["id"])
    assert D(line["measured"]) == 75 and D(line["to_bill"]) == 75
    site = db.get(Site, world["site"])
    site.board_status = "ongoing"
    db.commit()
    # before the billing day: nothing; on the 25th (frozen clock): an RA bill to raise
    monkeypatch.setattr(mywork, "today", lambda: date(2026, 10, 24))
    assert "ra_due" not in sources(b, bh)["billing"]
    monkeypatch.setattr(mywork, "today", lambda: date(2026, 10, 25))
    assert "ra_due" in sources(b, bh)["billing"]
    alerts.run(db, datetime(2026, 10, 25, 6, 0, tzinfo=UTC))
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "ra_monthly"))
    ra = c.post(f"/api/finance/contracts/{k['id']}/ra-bills", json={}, headers=h).json()
    assert (
        D(next(x for x in ra["lines"] if x["description"] == "PU coating")["suggested_qty"]) == 75
    )
    over = {"lines": [{"contract_line_id": pu["id"], "qty": "80"}]}
    r = c.put(f"/api/finance/ra-bills/{ra['id']}", json=over, headers=h)
    assert r.status_code == 422 and "measurement book" in r.json()["detail"]


def test_a_finished_stage_goes_into_the_book(boss, world, db):
    c, h = boss
    contract(c, h, world)
    n = db.scalar(select(Measurement.id).where(Measurement.ready_id.is_not(None)))
    assert n is None
    site = db.get(Site, world["site"])
    work.generate_tasks(db, site, None)
    db.commit()
    scope = db.get(AreaScope, world["scopes"][0])
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
            .order_by(Task.id)
        )
    )
    last = next(
        t
        for t in reversed(tasks)
        if t.step and not t.step.hold_point and not t.step.checklist_template_id
    )
    last.step.needs_photo = False
    for t in tasks:
        if t.id != last.id:
            t.status = "certified"
    db.commit()
    assert (
        c.patch(
            f"/api/sites/{site.id}/tasks/{last.id}", json={"status": "done"}, headers=h
        ).status_code
        == 200
    )
    m = db.scalar(select(Measurement).where(Measurement.ready_id.is_not(None)))
    assert m is not None and D(m.qty) == 60 and m.source in ("manual", "laser", "camera")


# --- tenders: awaiting award, the winner, the send checklist -------------------------------------


def _tender_with_line(db, world, **line) -> Tender:
    t = Tender(
        code="T-2026-9101", name="Invented Hospital", status="draft", client_id=world["client"]
    )
    db.add(t)
    db.flush()
    db.add(
        BoqLine(
            tender_id=t.id,
            sort_order=1,
            description="Invented PU coating",
            unit="sqm",
            qty=100,
            rate=500,
            status="priced",
            **line,
        )
    )
    db.commit()
    return t


def test_the_send_checklist_blocks_and_the_director_override_is_logged(boss, world, person, db):
    c, h = boss
    t = _tender_with_line(db, world)
    e, eh, _ = person("est@example.com", "estimator")
    r = e.patch(f"/api/tenders/{t.id}", json={"status": "submitted"}, headers=eh)
    assert (
        r.status_code == 409
        and "manufacturer" in r.json()["detail"]
        and "Guarantee" in r.json()["detail"]
    )
    r = e.patch(
        f"/api/tenders/{t.id}",
        json={"status": "submitted", "override_reason": "Invented: due today"},
        headers=eh,
    )
    assert r.status_code == 403
    d, dh, _ = person("dir@example.com", "director")
    r = d.patch(
        f"/api/tenders/{t.id}",
        json={"status": "submitted", "override_reason": "Invented: the client asked for it today"},
        headers=dh,
    )
    assert r.status_code == 200, r.text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "tender.sendcheck_override"))


def test_a_complete_tender_passes_the_checklist(boss, world, db):
    c, h = boss
    t = _tender_with_line(db, world, our_product="BRONCO HYBRID PU", manufacturer="Invented Bronco")
    ours = TcClause(text="Invented: we supply and apply", category="our_scope")
    theirs = TcClause(text="Invented: water and power by the client", category="client_scope")
    db.add_all([ours, theirs])
    db.flush()
    db.add_all(
        [
            TenderTc(tender_id=t.id, clause_id=ours.id, sort_order=1),
            TenderTc(tender_id=t.id, clause_id=theirs.id, sort_order=2),
        ]
    )
    db.commit()
    assert c.get(f"/api/team/send-check?tender_id={t.id}", headers=h).json() == {
        "missing": ["Guarantee years not filled"]
    }
    r = c.patch(
        f"/api/tenders/{t.id}", json={"status": "submitted", "guarantee_years": 10}, headers=h
    )
    assert r.status_code == 200, r.text


def test_awaiting_award_reminds_every_60_days_and_the_winner_gets_a_follow_up(
    boss, world, person, db
):
    c, h = boss
    t = _tender_with_line(db, world)
    r = c.patch(
        f"/api/tenders/{t.id}",
        json={"status": "submitted", "override_reason": "Invented: test"},
        headers=h,
    )
    assert r.status_code == 200
    award = c.get(f"/api/team/tenders/{t.id}/award", headers=h).json()
    assert award["status"] == "awaiting award"
    now = datetime.now(UTC)
    alerts.run(db, now + timedelta(days=59))
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "award_followup")) is None
    alerts.run(db, now + timedelta(days=61))
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "award_followup"))
    for name, rank, rate in (("Invented Coatings Pvt Ltd", 1, "450"), ("Us", 2, "500")):
        c.post(
            f"/api/team/tenders/{t.id}/bidders",
            json={"name": name, "rank": rank, "rate": rate, "is_us": name == "Us"},
            headers=h,
        )
    bidders = c.get(f"/api/team/tenders/{t.id}/award", headers=h).json()["bidders"]
    assert [b["label"] for b in bidders] == ["L1", "L2"]
    r = c.post(
        f"/api/team/tenders/{t.id}/winner",
        json={"bidder_id": bidders[0]["id"], "followup_on": "2027-01-15"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    lead = db.get(Lead, r.json()["lead_id"])
    db.expire_all()
    assert lead.next_follow_up == date(2027, 1, 15) and db.get(Tender, t.id).status == "lost"
    assert db.get(Tender, t.id).lost_to == "Invented Coatings Pvt Ltd"


# --- daily reports and the stage checklist -------------------------------------------------------


def test_the_engineer_approves_or_returns_the_supervisors_daily_report(world, person, db):
    sup, sh, _ = person(
        "sup@example.com", "site_supervisor", site_id=world["site"], role_on_site="supervisor"
    )
    e, eh, _ = person(
        "eng@example.com", "site_engineer", site_id=world["site"], role_on_site="incharge"
    )
    day = date.today().isoformat()
    url = f"/api/execution/sites/{world['site']}/dprs/{day}"
    terrace = db.scalar(select(AreaScope).where(AreaScope.id == world["scopes"][0])).node_id
    body = {
        "work_done": "Invented primer",
        "lines": [{"description": "Primer", "qty": "20", "unit": "sqm", "node_id": terrace}],
        "submit": True,
    }
    d = sup.put(url, json=body, headers=sh).json()
    assert d["status"] == "submitted" and "dpr_approve" in sources(e, eh)["site_engineer"]
    assert (
        sup.post(
            f"/api/execution/dprs/{d['id']}/return", json={"comment": "Invented"}, headers=sh
        ).status_code
        == 403
    )
    r = e.post(
        f"/api/execution/dprs/{d['id']}/return",
        json={"comment": "Invented: add the photos"},
        headers=eh,
    )
    assert r.json()["status"] == "returned"
    assert "dpr_returned" in sources(sup, sh)["site_supervisor"]
    d = sup.put(url, json=body, headers=sh).json()
    assert d["status"] == "submitted"
    assert (
        e.post(f"/api/execution/dprs/{d['id']}/acknowledge", headers=eh).json()["status"]
        == "acknowledged"
    )
    assert db.scalar(select(Dpr)).return_comment is None


def test_the_quality_checklist_comes_before_the_stage_is_done(boss, world, db):
    c, h = boss
    site = db.get(Site, world["site"])
    work.generate_tasks(db, site, None)
    db.commit()
    scope = db.get(AreaScope, world["scopes"][0])
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
            .order_by(Task.id)
        )
    )
    tpl = ChecklistTemplate(
        name="Invented coating checklist", created_by=db.scalar(select(User.id))
    )
    db.add(tpl)
    db.flush()
    last = tasks[-1]
    step = last.step
    old = (step.checklist_template_id, step.needs_photo, step.needs_inspection, step.hold_point)
    try:
        step.checklist_template_id, step.needs_photo, step.needs_inspection = tpl.id, False, False
        for t in tasks[:-1]:
            t.status = "certified"
        db.commit()
        r = c.patch(f"/api/sites/{site.id}/tasks/{last.id}", json={"status": "done"}, headers=h)
        assert r.status_code == 422 and "quality checklist" in r.json()["detail"]
        db.add(
            Inspection(
                code="INS-2026-9001",
                site_id=site.id,
                task_id=last.id,
                template_id=tpl.id,
                answers=[],
                result="pass",
                on_date=date.today(),
            )
        )
        db.commit()
        assert (
            c.patch(
                f"/api/sites/{site.id}/tasks/{last.id}", json={"status": "done"}, headers=h
            ).status_code
            == 200
        )
    finally:
        step.checklist_template_id, step.needs_photo, step.needs_inspection, step.hold_point = old
        db.commit()


def test_seeded_roles_exist(db):
    codes = set(db.scalars(select(Role.code)))
    assert {"director", "planning", "billing", "site_engineer"} <= codes
