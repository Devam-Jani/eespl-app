# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Bug sweep group E (stores, vendors, payables, sales, analytics): who may cancel an indent, the
indent links, RFQ POs close "place the PO", the freight year, a vendor in use, the overdue bills
order, the Tally party ledgers, "main job lost by the contractor" on leads, tenders and the
scorecard, the rate working's buttons, clearing product fields, "consumption reviewed" and the
labour productivity scope."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.closeout import routes as closeout_routes
from app.finance.models import FinanceSettings, RaBill
from app.models import User
from app.portal.models import Notification
from app.process import engine
from app.process.rules import DEFAULT_RULES
from app.quotations.models import Quotation
from app.sitecontrol import routers as sc_routers
from app.team import service as team
from tests.test_crm import new_lead
from tests.test_finance import contract, world  # noqa: F401  (fixtures)
from tests.test_material import boss, make_po, masters, site, store_of  # noqa: F401  (fixtures)
from tests.test_tenders import new_client, new_tender

D = Decimal
APP = Path(__file__).resolve().parents[1] / "app"


def _uid(db, email):
    return db.scalar(select(User.id).where(User.email == email))


def _default_user(client, h, role, user):
    r = client.put("/api/process/settings", json={"default_users": {role: str(user.id)}}, headers=h)
    assert r.status_code == 200, r.text


def _open_notes(db, subject, rule):
    db.expire_all()
    return list(
        db.scalars(
            select(Notification).where(
                Notification.subject == subject, Notification.rule_code == rule
            )
        )
    )


def _indent(client, h, site_id, product_id, submit=True):
    r = client.post(
        "/api/material/indents",
        json={
            "site_id": site_id,
            "submit": submit,
            "lines": [{"product_id": product_id, "qty": "10"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- stores --------------------------------------------------------------------------------------


def test_cancel_indent_only_for_the_creator_or_an_approver_and_on_approved_too(
    boss, login_as, masters
):
    client, h = boss
    products, _ = masters
    s = site(client, h)
    ind = _indent(client, h, s["id"], products["T-PU"])
    planner, ph = login_as("planning", email="planner@example.com")
    seen = planner.get(f"/api/material/indents/{ind['id']}", headers=ph).json()
    assert seen["can_edit"] and not seen["can_cancel"]  # indent.create all, not the creator
    assert planner.post(f"/api/material/indents/{ind['id']}/cancel", headers=ph).status_code == 403
    r = client.post(f"/api/material/indents/{ind['id']}/approve", headers=h)
    assert r.json()["status"] == "approved" and r.json()["can_cancel"]  # the API allows it
    r = client.post(f"/api/material/indents/{ind['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and not r.json()["can_cancel"]


def test_indent_links_open_the_indent_on_the_list_page():
    rule = next(r for r in DEFAULT_RULES if r["code"] == "indent_approved")
    assert rule["link"] == "/indents?open={indent_id}"
    mywork = (APP / "team" / "mywork.py").read_text(encoding="utf-8")
    assert 'f"/indents?open={ind.id}"' in mywork and 'f"/indents/{ind.id}"' not in mywork


def test_pos_made_from_an_rfq_close_place_the_po(boss, make_user, masters, db):
    client, h = boss
    products, (v_guj, _) = masters
    buyer = make_user("buyer@example.com", "store_purchase")
    _default_user(client, h, "store_purchase", buyer)
    s = site(client, h)
    ind = _indent(client, h, s["id"], products["T-PU"])
    assert client.post(f"/api/material/indents/{ind['id']}/approve", headers=h).status_code == 200
    db.commit()
    notes = _open_notes(db, f"indent:{ind['id']}", "indent_approved")
    assert notes and all(n.closed_at is None for n in notes)
    rfq = client.post(
        "/api/material/rfqs", json={"indent_ids": [ind["id"]], "vendor_ids": [v_guj]}, headers=h
    ).json()
    line = rfq["lines"][0]["id"]
    r = client.put(
        f"/api/material/rfqs/{rfq['id']}/quotes",
        json={"quotes": [{"rfq_line_id": line, "vendor_id": v_guj, "rate": "300"}]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/material/rfqs/{rfq['id']}/po", headers=h)
    assert r.status_code == 201, r.text
    notes = _open_notes(db, f"indent:{ind['id']}", "indent_approved")
    assert notes and all(n.closed_at is not None for n in notes)


def test_the_freight_entries_follow_the_year(boss):
    client, h = boss
    s = site(client, h)
    for on in ("2025-06-01", "2026-06-01"):
        r = client.post(
            "/api/material/freight",
            json={"site_id": s["id"], "on_date": on, "amount": "1000"},
            headers=h,
        )
        assert r.status_code == 201, r.text
    rows = client.get(
        "/api/material/freight", params={"site_id": s["id"], "year": 2025}, headers=h
    ).json()["items"]
    assert [r["on_date"] for r in rows] == ["2025-06-01"]
    assert (
        len(
            client.get("/api/material/freight", params={"site_id": s["id"]}, headers=h).json()[
                "items"
            ]
        )
        == 2
    )


# --- vendors, payment follow-up, payables --------------------------------------------------------


def test_a_vendor_in_use_is_refused_in_plain_words(boss, masters):
    client, h = boss
    products, (v_guj, _) = masters
    s = site(client, h)
    make_po(
        client,
        h,
        v_guj,
        store_of(client, h, s["id"])["id"],
        [{"product_id": products["T-PU"], "qty": "1", "rate": "10"}],
    )
    r = client.delete(f"/api/vendors/{v_guj}", headers=h)
    assert r.status_code == 409, r.text
    assert "in use" in r.json()["detail"] and "inactive" in r.json()["detail"]
    assert client.get(f"/api/vendors/{v_guj}", headers=h).status_code == 200  # still there


def test_overdue_bills_most_overdue_first_even_past_the_newest_300(boss, world, db, monkeypatch):
    client, h = boss
    k = contract(client, h, world)
    bills = [
        RaBill(
            code=f"RA-T-{i:04d}",
            contract_id=k["id"],
            site_id=world["site"],
            seq=i,
            period_to=date(2026, 1, 1),
        )
        for i in range(1, 303)
    ]
    db.add_all(bills)
    db.commit()
    oldest, second = bills[0].id, bills[150].id
    overdue = {oldest: 90, second: 10}
    monkeypatch.setattr(
        closeout_routes.bsvc,
        "bill_out",
        lambda _db, b, _day: {"id": b.id, "overdue_days": overdue.get(b.id, 0)},
    )
    rows = client.get("/api/closeout/bills?overdue=true", headers=h).json()
    assert [r["id"] for r in rows] == [oldest, second]


def test_saving_ledger_names_keeps_the_party_ledgers(boss, db):
    client, h = boss
    r = client.put(
        "/api/finance/tally/settings",
        json={
            "ledgers": {"sales": "Sales"},
            "party_ledgers": {"Invented Builders": "Invented Builders Ltd"},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/finance/tally/settings", json={"ledgers": {"sales": "Sales 18%"}}, headers=h
    )
    assert r.json() == {
        "ledgers": {"sales": "Sales 18%"},
        "party_ledgers": {"Invented Builders": "Invented Builders Ltd"},
    }
    db.expire_all()
    assert db.get(FinanceSettings, 1).party_ledgers == {
        "Invented Builders": "Invented Builders Ltd"
    }


# --- sales ---------------------------------------------------------------------------------------


def test_main_job_lost_is_accepted_on_a_lead_and_a_tender(boss):
    client, h = boss
    lead = new_lead(client, h)
    r = client.patch(
        f"/api/leads/{lead['id']}",
        json={"status": "lost", "lost_reason": "main_job_lost"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["lost_reason"] == "main_job_lost", r.text
    tender = new_tender(client, h, new_client(client, h))
    r = client.patch(
        f"/api/tenders/{tender['id']}",
        json={"status": "lost", "lost_reason": "main_job_lost"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["lost_reason"] == "main_job_lost", r.text


def test_the_scorecard_does_not_count_main_job_lost_as_our_loss(make_user, db):
    person = make_user("seller@example.com", "sales")
    for code, status, reason in (
        ("Q-T-1", "won", None),
        ("Q-T-2", "lost", "price"),
        ("Q-T-3", "lost", "main_job_lost"),
    ):
        db.add(Quotation(code=code, revision=0, is_latest=True, client_firm="Invented Builders", project="Invented tower", quote_date=date(2026, 10, 1),
                         status=status, lost_reason=reason, salesperson_id=person.id))  # fmt: skip
    db.commit()
    (row,) = team.scorecard(db, [person.id])
    assert (row["won"], row["lost"], row["closure_percent"]) == (1, 1, D("50.0"))
    assert row["lost_reasons"] == {"price": 1}


def test_the_tender_rate_working_is_read_only_without_tender_edit(boss, login_as):
    client, h = boss
    tender = new_tender(client, h, new_client(client, h))
    mine = client.get(f"/api/rate-working/tenders/{tender['id']}", headers=h).json()
    assert mine["can_edit"]
    accounts, ah = login_as("accounts", email="accounts@example.com")
    seen = accounts.get(f"/api/rate-working/tenders/{tender['id']}", headers=ah).json()
    assert seen["sees_cost"] and not seen["can_edit"]  # tender.margin, no tender.edit


# --- analytics -----------------------------------------------------------------------------------


def test_clearing_pack_hsn_and_reorder_level(boss):
    client, h = boss
    r = client.post(
        "/api/products",
        json={
            "code": "T-CLR",
            "name": "Test clearable",
            "unit": "kg",
            "pack_unit": "bag",
            "hsn_code": "3824",
            "reorder_level": "5",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.patch(
        f"/api/products/{pid}",
        json={"pack_unit": None, "hsn_code": None, "reorder_level": None, "name": None},
        headers=h,
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["pack_unit"], p["hsn_code"], p["reorder_level"], p["name"]) == (
        None,
        None,
        None,
        "Test clearable",
    )


def test_consumption_reviewed_closes_the_to_do(boss, make_user, login_as, db):
    client, h = boss
    planner = make_user("planner@example.com", "planning")
    _default_user(client, h, "planning", planner)
    s = site(client, h)
    engine.emit(
        db, "consumption_high", subject=f"consumption:{s['id']}", site_id=s["id"], data={"flags": 2}
    )
    db.commit()
    notes = _open_notes(db, f"consumption:{s['id']}", "consumption_high")
    assert notes and all(n.closed_at is None for n in notes)
    eng, eh = login_as("site_engineer", email="engineer@example.com")  # not on this site
    assert (
        eng.post(
            "/api/sitecontrol/reports/consumption/reviewed", params={"site_id": s["id"]}, headers=eh
        ).status_code
        == 404
    )
    r = client.post(
        "/api/sitecontrol/reports/consumption/reviewed", params={"site_id": s["id"]}, headers=h
    )
    assert r.status_code == 200, r.text
    assert all(
        n.closed_at is not None
        for n in _open_notes(db, f"consumption:{s['id']}", "consumption_high")
    )


def test_labour_productivity_keeps_assigned_users_to_their_sites(boss, login_as, monkeypatch):
    seen = []
    monkeypatch.setattr(
        sc_routers.sc,
        "productivity_report",
        lambda _db, site_id, site_ids=None: seen.append(site_ids) or [],
    )
    client, h = boss
    assert client.get("/api/sitecontrol/reports/productivity", headers=h).status_code == 200
    eng, eh = login_as("site_engineer", email="engineer@example.com")
    assert eng.get("/api/sitecontrol/reports/productivity", headers=eh).status_code == 200
    assert seen == [None, []]  # every site for the boss; none for an engineer on no site
