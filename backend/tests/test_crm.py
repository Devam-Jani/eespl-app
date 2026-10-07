"""CRM leads and the Kylas sync. Kylas is an httpx.MockTransport: nothing reaches the network."""

import json
import logging
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.config import settings
from app.crm import kylas_client, kylas_poll, kylas_push
from app.crm.kylas_client import KylasClient
from app.crm.models import KylasOutbox, Lead, LeadActivity
from app.db import SessionLocal
from app.models import User
from tests.conftest import login

KEY = "test-kylas-key-DO-NOT-LEAK-1234567890"


class FakeKylas:
    """Records every request; answers from per-path handlers."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.create = lambda req: httpx.Response(201, json={"id": 5001})
        self.search_lead = lambda req: httpx.Response(200, json={"content": [], "last": True})
        self.leads: dict[int, dict] = {}
        self.deals_search: list[dict] = []
        self.deals: dict[int, dict] = {}
        self.sources = [
            {"id": 999, "displayName": "EESPL App"},
            {"id": 3005767, "displayName": "Ethios Loyalty"},
            {"id": 1, "displayName": "Old", "deleted": True},
        ]
        # two pages, as Kylas pages lists
        self.pipelines = [
            {
                "id": 10,
                "name": "Project",
                "stages": [
                    {"id": 21, "name": "Open", "position": 1},
                    {"id": 20, "name": "Won", "position": 2},
                ],
            },
            {"id": 11, "name": "Deal", "stages": [{"id": 30, "name": "Closure", "position": 1}]},
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1")
        if request.method == "POST" and path == "/leads":
            return self.create(request)
        if request.method == "POST" and path == "/search/lead":
            return self.search_lead(request)
        if request.method == "POST" and path == "/search/deal":
            return httpx.Response(200, json={"content": self.deals_search, "last": True})
        if request.method == "GET" and path.startswith("/leads/"):
            body = self.leads.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=body) if body else httpx.Response(404)
        if request.method == "GET" and path.startswith("/deals/"):
            body = self.deals.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=body) if body else httpx.Response(404)
        if request.method == "GET" and path == "/sources":
            return httpx.Response(404)  # as the real Kylas answers
        if request.method == "GET" and path == "/entities/lead/fields":
            return httpx.Response(
                200,
                json=[
                    {"id": 7, "name": "firstName"},
                    {"id": 8, "name": "source", "picklist": {"values": self.sources}},
                ],
            )
        if request.method == "GET" and path == "/pipelines":
            if request.url.params.get("entityType") != "DEAL":
                return httpx.Response(400)
            page = int(request.url.params.get("page", 0))
            return httpx.Response(
                200,
                json={
                    "content": self.pipelines[page : page + 1],
                    "last": page >= len(self.pipelines) - 1,
                },
            )
        return httpx.Response(404)

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.method == method and r.url.path.removeprefix("/v1") == path
        ]


@pytest.fixture
def kylas(monkeypatch):
    fake = FakeKylas()
    monkeypatch.setattr(settings, "kylas_enabled", True)
    monkeypatch.setattr(settings, "kylas_api_key", SecretStr(KEY))
    monkeypatch.setattr(
        kylas_client,
        "client",
        lambda: KylasClient(base_url="https://kylas.test/v1", transport=httpx.MockTransport(fake)),
    )
    return fake


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def configure(client, headers, **extra):
    body = {"source_id": 999, "owner_rule": "creator", "default_owner_id": 222, **extra}
    r = client.put("/api/settings/kylas", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def new_lead(client, headers, phone="98765 43210", **extra):
    r = client.post(
        "/api/leads",
        json={
            "contact_name": "Ramesh Kumar Patel",
            "phone": phone,
            "email": "ramesh@example.com",
            "company": "Invented Infra",
            "city": "Ahmedabad",
            "requirement": "Terrace waterproofing, 1200 sqm",
            **extra,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def set_kylas_user(db, email, kylas_id):
    db.expire_all()
    user = db.scalar(select(User).where(User.email == email))
    user.kylas_user_id = kylas_id
    db.commit()


def due_now(lead_id):
    with SessionLocal() as db:
        row = db.scalar(select(KylasOutbox).where(KylasOutbox.lead_id == lead_id))
        row.next_attempt_at = kylas_push.now() - timedelta(seconds=1)
        db.commit()


def sweep():
    with SessionLocal() as db:
        return kylas_push.run_due(db, kylas_client.client())


def reload(lead_id) -> Lead:
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        db.expunge(lead)
        return lead


# --- outbound ------------------------------------------------------------------------------------


def test_create_queues_and_pushes_with_the_right_body(boss, kylas, db):
    client, headers = boss
    configure(client, headers)
    set_kylas_user(db, "boss@example.com", 111)
    lead = new_lead(client, headers)
    assert lead["code"].startswith("L-") and lead["phone"] == "+919876543210"
    # the background push ran after the response
    (create,) = kylas.calls("POST", "/leads")
    body = json.loads(create.content)
    assert body == {
        "firstName": "Ramesh",
        "lastName": "Kumar Patel",
        "phoneNumbers": [{"type": "MOBILE", "value": "+919876543210", "primary": True}],
        "emails": [{"type": "OFFICE", "value": "ramesh@example.com", "primary": True}],
        "companyName": "Invented Infra",
        "city": "Ahmedabad",
        "requirementName": "Terrace waterproofing, 1200 sqm",
        "source": 999,
        "ownerId": 111,
        "customFieldValues": {"cfInquiryType": lead["code"]},
    }
    assert create.headers["api-key"] == KEY
    got = client.get(f"/api/leads/{lead['id']}", headers=headers).json()
    assert (got["kylas_sync_status"], got["kylas_lead_id"]) == ("synced", 5001)
    assert any(a["type"] == "kylas" and "5001" in a["text"] for a in got["activities"])
    # edits are not pushed
    client.patch(f"/api/leads/{lead['id']}", json={"city": "Surat"}, headers=headers)
    assert len(kylas.calls("POST", "/leads")) == 1


def test_owner_rule(boss, kylas, db):
    client, headers = boss
    configure(client, headers)  # creator rule, default owner 222
    new_lead(client, headers, phone="9000000001")  # the creator has no Kylas id yet
    set_kylas_user(db, "boss@example.com", 111)
    new_lead(client, headers, phone="9000000002")
    configure(client, headers, owner_rule="default")
    new_lead(client, headers, phone="9000000003")
    owners = [json.loads(r.content)["ownerId"] for r in kylas.calls("POST", "/leads")]
    assert owners == [222, 111, 222]


def test_timeout_then_found_is_adopted_not_created_again(boss, kylas):
    client, headers = boss
    configure(client, headers)

    def timeout(req):
        raise httpx.ReadTimeout("read timed out", request=req)

    kylas.create = timeout
    lead = new_lead(client, headers)
    assert reload(lead["id"]).kylas_sync_status == "pending"  # unknown: searched next time
    kylas.search_lead = lambda req: httpx.Response(
        200,
        json={
            "content": [
                {"id": 7001, "ownerId": 222, "customFieldValues": {"cfInquiryType": lead["code"]}}
            ],
            "last": True,
        },
    )
    due_now(lead["id"])
    report = sweep()
    assert report.adopted == 1
    assert len(kylas.calls("POST", "/leads")) == 1  # no second create
    search = json.loads(kylas.calls("POST", "/search/lead")[0].content)
    assert search["jsonRule"]["rules"][0]["value"] == "9876543210"
    assert (reload(lead["id"]).kylas_lead_id, reload(lead["id"]).kylas_sync_status) == (
        7001,
        "synced",
    )


def test_timeout_then_search_empty_creates_once_more(boss, kylas):
    client, headers = boss
    configure(client, headers)
    calls = {"n": 0}

    def first_times_out(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("read timed out", request=req)
        return httpx.Response(201, json={"id": 8001})

    kylas.create = first_times_out
    lead = new_lead(client, headers)
    due_now(lead["id"])
    sweep()
    assert len(kylas.calls("POST", "/search/lead")) == 1
    assert len(kylas.calls("POST", "/leads")) == 2
    assert reload(lead["id"]).kylas_lead_id == 8001
    assert sweep().created == 0


def test_backoff_then_failed_then_retry(boss, kylas):
    client, headers = boss
    configure(client, headers)
    kylas.create = lambda req: httpx.Response(429, text="slow down")
    lead = new_lead(client, headers)  # attempt 1 (the immediate one)
    waits = []
    for attempt in range(1, kylas_push.MAX_ATTEMPTS + 1):
        with SessionLocal() as db:
            row = db.scalar(select(KylasOutbox).where(KylasOutbox.lead_id == lead["id"]))
            assert row.attempts == attempt
            if row.status == "failed":
                break
            waits.append(round((row.next_attempt_at - kylas_push.now()).total_seconds() / 60))
        due_now(lead["id"])
        sweep()
    assert waits == [1, 5, 30, 120, 360, 360, 360]
    got = client.get(f"/api/leads/{lead['id']}", headers=headers).json()
    assert got["kylas_sync_status"] == "failed" and "429" in got["kylas_last_error"]
    assert len(kylas.calls("POST", "/leads")) == kylas_push.MAX_ATTEMPTS
    kylas.create = lambda req: httpx.Response(201, json={"id": 9001})
    r = client.post(f"/api/leads/{lead['id']}/kylas/retry", headers=headers)
    assert r.status_code == 200 and r.json()["kylas_sync_status"] == "pending"
    # the push runs right after the response
    got = client.get(f"/api/leads/{lead['id']}", headers=headers).json()
    assert (got["kylas_lead_id"], got["kylas_sync_status"]) == (9001, "synced")


def test_off_means_disabled_and_no_calls(boss, kylas, monkeypatch):
    client, headers = boss
    lead = new_lead(client, headers)  # no source id yet
    assert lead["kylas_sync_status"] == "disabled"
    configure(client, headers)
    monkeypatch.setattr(settings, "kylas_enabled", False)
    lead = new_lead(client, headers, phone="9000000009")
    assert lead["kylas_sync_status"] == "disabled"
    with SessionLocal() as db:
        assert db.scalar(select(KylasOutbox)) is None
    assert kylas.requests == []
    s = client.get("/api/settings/kylas", headers=headers).json()
    assert s["active"] is False and s["api_key"] == "set"


def test_api_key_never_leaks(boss, kylas, caplog):
    caplog.set_level(logging.DEBUG)
    client, headers = boss
    configure(client, headers)
    kylas.create = lambda req: httpx.Response(400, text=f"bad request for key {KEY}")
    lead = new_lead(client, headers)
    detail = client.get(f"/api/leads/{lead['id']}", headers=headers)
    assert detail.json()["kylas_sync_status"] == "failed"
    settings_out = client.get("/api/settings/kylas", headers=headers)
    test = client.post("/api/settings/kylas/test", headers=headers)
    assert test.json()["ok"] is True
    for text in (
        caplog.text,
        detail.text,
        settings_out.text,
        test.text,
        repr(kylas_client.client()),
        str(kylas_client.client()),
    ):
        assert KEY not in text
    assert "***" in detail.json()["kylas_last_error"]


# --- inbound -------------------------------------------------------------------------------------


def _synced(db, code, kylas_id, **extra):
    lead = Lead(
        code=code,
        contact_name="X",
        phone="+919000000000",
        kylas_lead_id=kylas_id,
        kylas_sync_status="synced",
        **extra,
    )
    db.add(lead)
    db.commit()
    return lead.id


def test_lead_poll_mapping(boss, kylas, db):
    client, headers = boss
    configure(client, headers)
    ids = {
        "lost": _synced(db, "L-T-1", 1),
        "junk": _synced(db, "L-T-2", 2),
        "open": _synced(db, "L-T-3", 3),
        "conv": _synced(db, "L-T-4", 4),
        "other": _synced(db, "L-T-5", 5),
    }
    kylas.leads = {
        1: {"id": 1, "forecastingType": "CLOSED_LOST", "pipelineStageReason": "Price"},
        2: {
            "id": 2,
            "forecastingType": "CLOSED_UNQUALIFIED",
            "pipelineStageReason": "wrong  NUMBER",
        },
        3: {"id": 3, "forecastingType": "OPEN"},
        4: {"id": 4, "forecastingType": "OPEN", "conversionDetails": [{"entityType": "DEAL"}]},
        5: {"id": 5, "forecastingType": "CLOSED_UNQUALIFIED", "pipelineStageReason": "Budget"},
    }
    with SessionLocal() as s:
        report = kylas_poll.run(s, kylas_client.client())
    assert (report.lost, report.junk, report.converted) == (2, 1, 1)
    status = {k: reload(v).status for k, v in ids.items()}
    assert status == {"lost": "lost", "junk": "junk", "open": "new", "conv": "new", "other": "lost"}
    assert reload(ids["conv"]).kylas_converted_at is not None
    with SessionLocal() as s:
        kylas_poll.run(s, kylas_client.client())  # closed leads are not polled again
        notes = s.scalars(select(LeadActivity.text).where(LeadActivity.type == "kylas")).all()
    assert len(notes) == 4  # lost, junk, converted, other: once each
    assert not any(r.method != "GET" and "/search/" not in r.url.path for r in kylas.requests)


def test_deal_poll_won_and_overlap(boss, kylas, db):
    client, headers = boss
    configure(client, headers, deal_pipeline_id=10, won_stage_id=20)
    client_id = client.post(
        "/api/clients", json={"name": "Invented Client"}, headers=headers
    ).json()["id"]
    tender = client.post(
        "/api/tenders", json={"name": "Lead tender", "client_id": client_id}, headers=headers
    ).json()
    lead_id = _synced(db, "L-T-9", 900, tender_id=tender["id"])
    other = _synced(db, "L-T-8", 800)
    at = kylas_push.now().isoformat()
    kylas.deals_search = [
        {"id": 55, "updatedAt": at, "pipeline": {"id": 10}, "convertedLeads": [{"id": 900}]},
        {"id": 56, "updatedAt": at, "pipeline": {"id": 99}, "convertedLeads": [{"id": 800}]},
        {"id": 57, "updatedAt": at, "pipeline": {"id": 10}, "convertedLeads": [{"id": 123}]},
    ]
    kylas.deals = {
        55: {
            "id": 55,
            "pipeline": {"id": 10},
            "pipelineStage": {"id": 20},
            "convertedLeads": [{"id": 900}],
        }
    }
    kylas.leads = {
        900: {"id": 900, "forecastingType": "OPEN"},
        800: {"id": 800, "forecastingType": "OPEN"},
    }
    with SessionLocal() as s:
        report = kylas_poll.run(s, kylas_client.client())
    assert report.won == 1
    won = reload(lead_id)
    assert (won.status, won.kylas_deal_id) == ("won", 55)
    assert reload(other).status == "new"
    assert [r.url.path for r in kylas.calls("GET", "/deals/55")] == ["/v1/deals/55"]
    t = client.get(f"/api/tenders/{tender['id']}", headers=headers).json()
    assert t["kylas_won_lead"] == "L-T-9" and t["status"] == "draft"  # confirm by hand
    with SessionLocal() as s:  # the overlap re-reads deal 55: nothing new happens
        again = kylas_poll.run(s, kylas_client.client())
        notes = s.scalars(select(LeadActivity).where(LeadActivity.lead_id == lead_id)).all()
    assert again.won == 0 and len(notes) == 1


# --- leads module --------------------------------------------------------------------------------


def test_duplicate_warning_and_convert(boss, kylas):
    client, headers = boss
    first = new_lead(client, headers)
    dupes = client.get(
        "/api/leads/check-phone", params={"phone": "+91 98765-43210"}, headers=headers
    ).json()
    assert [d["code"] for d in dupes] == [first["code"]]
    second = new_lead(client, headers)  # still allowed
    assert [d["code"] for d in second["duplicates"]] == [first["code"]]
    assert client.post(f"/api/leads/{first['id']}/convert", headers=headers).status_code == 422
    channel = client.post(
        "/api/channels", json={"name": "Partner One", "type": "partner"}, headers=headers
    ).json()
    client.patch(f"/api/leads/{first['id']}", json={"channel_id": channel["id"]}, headers=headers)
    r = client.post(f"/api/leads/{first['id']}/convert", headers=headers)
    assert r.status_code == 201, r.text
    lead = r.json()
    assert lead["tender_code"].startswith("T-") and lead["status"] == "quoted"
    tender = client.get(f"/api/tenders/{lead['tender_id']}", headers=headers).json()
    assert tender["channel_name"] == "Partner One"
    assert client.post(f"/api/leads/{first['id']}/convert", headers=headers).status_code == 409


def test_sales_sees_own_leads_and_client_is_refused(boss, login_as, make_user):
    client, headers = boss
    new_lead(client, headers)
    make_user("sales@example.com", "sales")
    sales = login(client, "sales@example.com")
    mine = client.post(
        "/api/leads", json={"contact_name": "Own Lead", "phone": "9111111111"}, headers=sales
    ).json()
    listed = client.get("/api/leads", headers=sales).json()
    assert [x["id"] for x in listed["items"]] == [mine["id"]]
    others = client.get("/api/leads", headers=headers).json()["items"]
    other_id = next(x["id"] for x in others if x["id"] != mine["id"])
    assert client.get(f"/api/leads/{other_id}", headers=sales).status_code == 404
    assert client.get("/api/settings/kylas", headers=sales).status_code == 403
    customer, customer_headers = login_as("client", email="customer@example.com")
    assert customer.get("/api/leads", headers=customer_headers).status_code == 403
    r = customer.post("/api/leads", json={"contact_name": "x"}, headers=customer_headers)
    assert r.status_code == 403


def test_kylas_user_id_needs_admin_settings(boss, login_as, make_user, db):
    client, headers = boss
    target = make_user("rep@example.com", "sales")
    r = client.patch(f"/api/users/{target.id}", json={"kylas_user_id": 4242}, headers=headers)
    assert r.status_code == 200 and r.json()["kylas_user_id"] == 4242
    office, office_headers = login_as("office_admin", email="office@example.com")
    r = office.patch(f"/api/users/{target.id}", json={"kylas_user_id": 1}, headers=office_headers)
    assert r.status_code == 403


# --- settings checks -----------------------------------------------------------------------------


def test_connection_counts_the_lead_sources(boss, kylas):
    client, headers = boss
    configure(client, headers)  # source 999
    r = client.post("/api/settings/kylas/test", headers=headers).json()
    assert r["ok"] is True
    assert r["message"] == "Connected: 2 lead sources; source 999 is 'EESPL App'"
    assert [x.url.path for x in kylas.requests] == ["/v1/entities/lead/fields"]  # one GET
    configure(client, headers, source_id=12345)
    r = client.post("/api/settings/kylas/test", headers=headers).json()
    assert "12345 is NOT a Kylas lead source" in r["message"]


def test_won_stage_must_belong_to_the_pipeline(boss, kylas):
    client, headers = boss
    base = {"source_id": 999, "owner_rule": "default", "default_owner_id": 222}

    def put(**extra):
        return client.put("/api/settings/kylas", json={**base, **extra}, headers=headers)

    r = put(won_stage_id=20)
    assert r.status_code == 422 and "pipeline id together" in r.json()["detail"]
    r = put(deal_pipeline_id=11, won_stage_id=20)  # 20 belongs to pipeline 10
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "20 is not a stage of pipeline 11 (Deal); its stages are " "30 Closure"
    )
    r = put(deal_pipeline_id=99, won_stage_id=20)
    assert r.status_code == 422 and "99 is not a deal pipeline" in r.json()["detail"]
    r = put(deal_pipeline_id=10, won_stage_id=20)
    assert r.status_code == 200
    assert (r.json()["deal_pipeline_id"], r.json()["won_stage_id"]) == (10, 20)
    assert put(deal_pipeline_id=10).status_code == 200  # a pipeline alone is fine


def test_won_stage_needs_kylas_to_check_it(boss, kylas, monkeypatch):
    client, headers = boss
    monkeypatch.setattr(settings, "kylas_api_key", None)
    r = client.put(
        "/api/settings/kylas",
        json={"source_id": 999, "deal_pipeline_id": 10, "won_stage_id": 20},
        headers=headers,
    )
    assert r.status_code == 422 and "API key" in r.json()["detail"]
