# ruff: noqa: E501
"""The bugs the go-live sweep found (the API fuzz and the nightly check), each kept fixed:
a database refusal caused by what was typed is a plain 4xx, not a crash; a site that does not
exist is a 404 on the receiver and flags; the route plan's start must be a lat/lng pair; the
billing checklist of a site without towers has every list the page draws. Invented data only."""

from fastapi.testclient import TestClient

from app.issues.models import Issue
from app.main import app
from app.sites.models import Site
from tests.test_finance import boss  # noqa: F401  (fixture)


def _crash_free(boss):  # noqa: F811
    c, h = boss
    return TestClient(app, raise_server_exceptions=False), h


def test_a_number_too_large_is_a_wrong_entry_not_a_crash(boss, db):  # noqa: F811
    c, h = _crash_free(boss)
    r = c.post("/api/tc/clauses", json={"text": "Invented clause", "category": "General", "sort_order": 10**20}, headers=h)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("A value is out of range")
    assert db.query(Issue).count() == 0  # a wrong entry is not a bug in the log book


def test_a_record_that_does_not_exist_is_said_plainly(boss, db):  # noqa: F811
    c, h = _crash_free(boss)
    r = c.post("/api/material/stores", json={"name": "Invented store", "address": "Somewhere", "gstin_address_id": 999999}, headers=h)
    assert r.status_code == 422
    assert "does not exist" in r.json()["detail"]


def test_the_receiver_and_flags_of_a_missing_site_are_404(boss):  # noqa: F811
    c, h = _crash_free(boss)
    assert c.put("/api/sitecontrol/sites/999999/receiver", json={}, headers=h).status_code == 404
    assert c.get("/api/sitecontrol/sites/999999/flags", headers=h).status_code == 404


def test_the_route_plan_start_is_a_lat_lng_pair(login_as):
    c, h = login_as("site_engineer")
    r = c.post("/api/field/plan", json={"site_ids": [1], "start": [1.5]}, headers=h)
    assert r.status_code == 422
    assert r.json()["detail"][0]["label"] == "Start"
    assert c.post("/api/field/plan", json={"site_ids": [], "start": [23.02, 72.57]}, headers=h).status_code == 200


def test_the_billing_checklist_of_a_site_without_towers_has_every_list(boss, db):  # noqa: F811
    c, h = boss
    site = Site(code="S-SW-9001", name="Invented site without towers", status="active")
    db.add(site)
    db.commit()
    r = c.get(f"/api/closeout/sites/{site.id}/billing-checklist", headers=h)
    assert r.status_code == 200
    body = r.json()
    for key in ("towers", "months", "columns", "rows"):
        assert body[key] == [], key
    assert body["counts"] == {} and body["tower"] is None
