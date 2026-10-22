# ruff: noqa: E501
"""Part 0 of the X-ray prompt: sales follows its own clients' bills and payments read-only under
Sales, without the Billing group."""

from fastapi.testclient import TestClient

from app.main import app
from app.ops import roles_report
from app.sites.models import SiteMember
from tests.conftest import login
from tests.test_finance import boss, certified_ra, world  # noqa: F401  (fixtures)


def test_sales_sees_its_own_clients_bills_read_only_and_no_one_elses(boss, world, db, make_user):  # noqa: F811
    client, h = boss
    certified_ra(client, h, world)
    mine = make_user("sales-mine@example.com", "sales")
    make_user("sales-other@example.com", "sales")
    db.add(SiteMember(site_id=world["site"], user_id=mine.id, role_on_site="sales"))
    db.commit()

    c = TestClient(app)
    rows = c.get("/api/closeout/sales-bills", headers=login(c, "sales-mine@example.com")).json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"id", "bill_no", "ra_code", "date", "site", "client", "amount", "certified", "received", "overdue_days"}  # no cost, steps or notes
    assert float(row["certified"]) > 0 and float(row["received"]) == 0

    other = TestClient(app)
    assert other.get("/api/closeout/sales-bills", headers=login(other, "sales-other@example.com")).json() == []
    # read-only: sales cannot work the bill (steps, follow-ups are billing's and accounts')
    assert c.post(f"/api/closeout/bills/{row['id']}/steps", data={"step": "submitted", "on_date": "2026-10-01"}, headers=login(c, "sales-mine@example.com")).status_code == 403


def test_the_roles_report_shows_sales_bills_under_sales_and_no_billing_group(db):
    sales = next(r for r in roles_report.report(db) if r["code"] == "sales")
    assert "Billing" not in sales["pages"]
    assert "Bills and payments" in sales["pages"]["Sales"]
