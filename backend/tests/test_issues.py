# ruff: noqa: E501
"""The helper and the issue log book: a wrong entry said plainly field by field, every 5xx recorded
with its request id, the browser's reports without values (unless agreed) or secrets, repeats
grouped, statuses and fixes kept by the director's side only, released on deploy, the Excel export,
the nightly open.md without personal data, the weekly summary once, and the helper's AI: off
without the flag, mocked here (never called), never sent a client's costs or margins or a place."""

import io
from datetime import UTC, datetime

import openpyxl
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.audit import AuditLog
from app.config import settings
from app.issues import fields, helper_ai
from app.issues import service as svc
from app.issues import worker as issues_worker
from app.issues.models import HelperAnswer, Issue, IssueEvent
from app.main import app
from app.portal.models import Notification

KEEPERS = ("director", "office_admin", "super_admin")


@pytest.fixture
def boom():
    """A route that crashes (added for the test only)."""

    def _boom() -> dict:
        raise RuntimeError("the invented crash")

    app.add_api_route("/api/test-boom", _boom, methods=["GET"])
    yield
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/test-boom"]


# --- a wrong entry, in plain words ----------------------------------------------------------------------


def test_a_wrong_entry_says_what_is_wrong_and_how_to_fix_it(login_as):
    c, h = login_as("director")
    r = c.post("/api/me/issues", json={"kind": "oops", "status_code": -1}, headers=h)
    assert r.status_code == 422
    by_field = {d["field"]: d for d in r.json()["detail"]}
    assert by_field["kind"]["plain"] == "Kind is not in the right form."
    assert by_field["status_code"]["plain"] == "Status code must be 0 or more."
    assert by_field["status_code"]["fix"] == "Type a number of 0 or more (not a negative one)."
    assert by_field["status_code"]["msg"] == "Status code must be 0 or more. Type a number of 0 or more (not a negative one)."
    assert by_field["status_code"]["loc"] == ["body", "status_code"]  # what older screens read stays
    # a wrong entry is a user's mistake, not a crash: nothing is recorded by the server
    assert r.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("err", "plain", "fix"),
    [
        ({"type": "missing", "loc": ("body", "contact_name")}, "Contact name is needed.", "Fill it in."),
        ({"type": "string_too_short", "loc": ("body", "name"), "ctx": {"min_length": 1}}, "Name is empty.", "Fill it in."),
        ({"type": "string_too_long", "loc": ("body", "gstin"), "ctx": {"max_length": 15}}, "GSTIN is too long.", "Shorten it to 15 characters or fewer."),
        ({"type": "decimal_parsing", "loc": ("body", "lines", 1, "qty")}, "Line 2: Quantity must be a number.", "Type digits only, like 12.5 (no letters, units or commas)."),
        ({"type": "less_than_equal", "loc": ("body", "pct"), "ctx": {"le": 100}}, "% must be 100 or less.", "Type a number up to 100."),
        ({"type": "date_from_datetime_parsing", "loc": ("body", "due_date")}, "Due date is not a date.", "Pick a date, or type it as 2026-10-22."),
        ({"type": "literal_error", "loc": ("body", "status"), "ctx": {"expected": "'new' or 'bug'"}}, "Status is not one of the choices.", "Pick one of: new or bug."),
        ({"type": "value_error", "loc": ("body", "phone"), "msg": "Value error, a mobile number has 10 digits"}, "Phone: a mobile number has 10 digits.", "Correct it as the message says."),
    ],
)
def test_each_rule_reads_plainly(err, plain, fix):
    assert fields.plain(err) == (plain, fix)


# --- every 5xx recorded with its request id -------------------------------------------------------------


def test_a_5xx_is_logged_with_its_request_id_and_the_browser_report_joins_it(login_as, db, boom):
    from fastapi.testclient import TestClient

    c, h = login_as("planning")
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/test-boom", headers={**h, "X-Request-ID": "feedc0de12345678"})
    assert r.status_code == 500
    assert r.headers["X-Request-ID"] == "feedc0de12345678"
    assert "feedc0de12345678" in r.json()["detail"] and "invented crash" not in r.json()["detail"]  # the trace stays on the server
    ev = db.scalar(select(IssueEvent).where(IssueEvent.request_id == "feedc0de12345678"))
    issue = db.get(Issue, ev.issue_id)
    assert (issue.kind, issue.status_code, issue.found_by, issue.page) == ("error", 500, "server", "GET /api/test-boom")
    assert "RuntimeError: the invented crash" in issue.error and "_boom" in issue.stack
    assert ev.role == "planning" and ev.user_id is not None
    # the browser reports the same failure: it goes on the server's event, not a second issue
    r = c.post("/api/me/issues", json={"kind": "error", "page": "/sites/4", "action": 'pressed "Save"', "status_code": 500, "request_id": "feedc0de12345678", "browser": "Chrome 130 · Windows"}, headers=h)
    assert r.status_code == 201 and r.json()["issue_id"] == issue.id
    db.expire_all()
    assert db.scalar(select(IssueEvent.browser).where(IssueEvent.id == ev.id)) == "Chrome 130 · Windows"
    assert db.query(Issue).count() == 1


# --- what the browser sends ----------------------------------------------------------------------------


def test_the_report_keeps_no_values_without_consent_and_never_a_secret(login_as, db):
    c, h = login_as("billing")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    body = {"kind": "error", "page": "/bills/7", "error": f"TypeError: x is undefined (Bearer {jwt}, password=hunter22)", "values": {"Quantity": "-5"}}
    r = c.post("/api/me/issues", json=body, headers=h)
    assert r.status_code == 201
    ev = db.get(IssueEvent, r.json()["event_id"])
    assert ev.values is None
    assert "hunter22" not in ev.error and jwt not in ev.error and "eyJ" not in ev.error
    r = c.post("/api/me/issues", json={**body, "include_values": True, "values": {"Quantity": "-5", "Password": "hunter22", "api_key": "sk-abcdefghijklmnop", "Note": f"token={jwt}"}}, headers=h)
    ev = db.get(IssueEvent, r.json()["event_id"])
    assert ev.values == {"Quantity": "-5", "Note": "token=[hidden]"}


def test_repeats_are_grouped_and_people_s_own_reports_are_not(login_as, db):
    c, h = login_as("site_engineer")
    c2, h2 = login_as("billing")
    for page, hh, cc in (("/sites/4", h, c), ("/sites/91", h2, c2), ("/sites/4", h, c)):
        cc.post("/api/me/issues", json={"kind": "error", "page": page, "error": f"TypeError: Cannot read properties of undefined (reading 'qty') at row {page[-1]}"}, headers=hh)
    issue = db.scalar(select(Issue))
    assert db.query(Issue).count() == 1
    assert issue.count == 3 and issue.page == "/sites/:id" and sorted(issue.roles) == ["billing", "site_engineer"]
    assert issue.first_seen <= issue.last_seen
    c.post("/api/me/issues", json={"kind": "error", "page": "/sites/4", "error": "RangeError: another one"}, headers=h)
    assert db.query(Issue).count() == 2
    for words in ("the save button did nothing", "the save button did nothing"):
        c.post("/api/me/issues", json={"kind": "report", "page": "/sites/4", "words": words}, headers=h)
    assert db.query(Issue).count() == 4  # two people's words are two reports
    # a wrong entry the card guided is marked so at once
    r = c.post("/api/me/issues", json={"kind": "mistake", "page": "/leads", "status_code": 422, "error": "Phone is needed."}, headers=h)
    assert r.json()["status"] == "guided"


def test_each_user_sees_their_own_reports_and_a_client_never_another_s(login_as, db):
    a, ha = login_as("client", email="client-a@example.com")
    b, hb = login_as("client", email="client-b@example.com")
    r = a.post("/api/me/issues", json={"kind": "report", "page": "/portal/sites/3", "words": "the photos do not open"}, headers=ha)
    assert r.status_code == 201
    iid = r.json()["issue_id"]
    assert [x["words"] for x in a.get("/api/me/issues", headers=ha).json()] == ["the photos do not open"]
    assert b.get("/api/me/issues", headers=hb).json() == []
    assert b.post(f"/api/me/issues/{iid}/words", json={"words": "me too"}, headers=hb).status_code == 404
    assert a.post(f"/api/me/issues/{iid}/words", json={"words": "on the phone"}, headers=ha).status_code == 201
    ev = db.scalar(select(IssueEvent).where(IssueEvent.words == "the photos do not open"))
    assert ev.client is True and ev.role == "client"
    # the log book is not the client's
    assert a.get("/api/issues", headers=ha).status_code == 403


# --- the log book --------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["director", "office_admin", "super_admin", "planning", "billing", "sales", "site_engineer", "accounts"])
def test_only_the_keepers_open_the_log_book(login_as, role):
    c, h = login_as(role)
    expected = 200 if role in KEEPERS else 403
    assert c.get("/api/issues", headers=h).status_code == expected
    assert c.get("/api/issues/export.xlsx", headers=h).status_code == expected
    assert c.put("/api/issues/1", json={"status": "bug"}, headers=h).status_code == (404 if role in KEEPERS else 403)


def test_status_cause_fix_and_pr_link_are_kept_and_audited(login_as, db):
    c, h = login_as("director")
    issue, _ = svc.record(db, "error", page="/sites/1", error="TypeError: boom", status_code=None)
    db.commit()
    r = c.put(f"/api/issues/{issue.id}", json={"status": "bug", "cause": "the line had no unit", "pr_url": "https://github.com/Devam-Jani/eespl-app/pull/31"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "bug" and r.json()["fixed_at"] is None
    bad = c.put(f"/api/issues/{issue.id}", json={"pr_url": "http://elsewhere/pr/1", "commit": "xyz"}, headers=h)
    assert bad.status_code == 422
    assert {d["field"] for d in bad.json()["detail"]} == {"pr_url", "commit"}
    assert "github.com" in next(d for d in bad.json()["detail"] if d["field"] == "pr_url")["fix"]
    r = c.put(f"/api/issues/{issue.id}", json={"status": "fixed", "fix": "the unit is required", "commit": "b89a83c"}, headers=h)
    assert r.json()["status"] == "fixed" and r.json()["fixed_at"] is not None and r.json()["released_at"] is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "issue.update").order_by(AuditLog.id.desc())) is not None
    got = c.get(f"/api/issues/{issue.id}", headers=h).json()
    assert got["cause"] == "the line had no unit" and got["pr_url"].endswith("/pull/31") and got["commit"] == "b89a83c"
    # it comes back after the fix: new again
    svc.record(db, "error", page="/sites/2", error="TypeError: boom", status_code=None)
    db.commit()
    db.refresh(issue)
    assert issue.status == "new" and issue.count == 2


def test_a_deploy_marks_its_fixes_released(db):
    a, _ = svc.record(db, "error", page="/a", error="A")
    b, _ = svc.record(db, "error", page="/b", error="B")
    a.commit, a.status = "b89a83c", "fixing"
    b.commit = "1234567"
    db.commit()
    at = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    assert svc.released(db, ["b89a83c0f00d1e2a3b4c5d6e7f8091a2b3c4d5e6", "9bd4c70"], at) == [a.id]
    db.commit()
    db.refresh(a)
    db.refresh(b)
    assert (a.status, a.released_at, a.fixed_at) == ("fixed", at, at)
    assert b.released_at is None
    assert svc.released(db, ["b89a83c"]) == []  # once


def test_the_cli_marks_released(db, tmp_path, capsys):
    from app.cli import main as cli

    a, _ = svc.record(db, "error", page="/a", error="A")
    a.commit = "abcdef1"
    db.commit()
    f = tmp_path / "commits.txt"
    f.write_text("0000000\nabcdef1234\n")
    cli(["issues-released", f"@{f}"])
    assert f"#{a.id}" in capsys.readouterr().out
    db.expire_all()
    assert db.get(Issue, a.id).released_at is not None


def test_the_excel_export(login_as, db):
    c, h = login_as("office_admin")
    svc.record(db, "error", page="/sites/1", error="TypeError: boom", role="billing")
    svc.record(db, "error", page="/sites/2", error="TypeError: boom", role="planning")
    svc.record(db, "mistake", page="/leads", error="Phone is needed.", status_code=422)
    db.commit()
    r = c.get("/api/issues/export.xlsx", headers=h)
    assert r.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.values)
    assert rows[0][:4] == ("id", "kind", "status", "title")
    by_title = {row[3]: row for row in rows[1:]}
    assert by_title["TypeError: boom"][6] == 2 and by_title["TypeError: boom"][5] == "billing, planning"
    assert by_title["Phone is needed."][2] == "guided"


def test_the_list_filters_and_the_weekly_summary(login_as, db):
    c, h = login_as("director")
    svc.record(db, "error", page="/a", error="A")
    svc.record(db, "mistake", page="/b", error="B", status_code=422)
    db.commit()
    assert [i["title"] for i in c.get("/api/issues?status=guided", headers=h).json()] == ["B"]
    assert [i["title"] for i in c.get("/api/issues?kind=error", headers=h).json()] == ["A"]
    w = c.get("/api/issues/weekly", headers=h).json()
    assert w["new_issues"] == 2 and w["open_bugs"] == 1 and w["times_happened"] == 2


def test_the_weekly_summary_reaches_the_keepers_once(make_user, db):
    keepers = [make_user(f"{r}@example.com", r) for r in KEEPERS]
    other = make_user("sales@example.com", "sales")
    svc.record(db, "error", page="/a", error="A")
    db.commit()
    monday = datetime(2026, 10, 19, 4, 0, tzinfo=UTC)  # 9:30 IST
    assert issues_worker.weekly_notice(db, monday) == 3
    assert issues_worker.weekly_notice(db, monday.replace(hour=6)) == 0
    told = set(db.scalars(select(Notification.user_id).where(Notification.kind == "issue_weekly")))
    assert told == {u.id for u in keepers} and other.id not in told


# --- the nightly list for the developer: no personal data ------------------------------------------------


def test_open_md_has_no_personal_data(make_user, db, tmp_path):
    u = make_user("ravi.invented@example.com", "billing", name="Ravi Inventedname")
    svc.record(db, "error", page="/sites/4", error="TypeError: no bill for ravi.invented@example.com, phone 9876543210 at 23.0225, 72.5714",
               stack="at Bill (bills.tsx:12)\nuser ravi.invented@example.com", role="billing", user_id=u.id,
               words="Ravi here: it broke when I typed my number 9876543210", values={"Client": "Invented Pvt Ltd"})  # fmt: skip
    svc.record(db, "report", page="/x", error=None, words="only words", role="billing", group=False)
    svc.record(db, "mistake", page="/leads", error="Phone is needed.", status_code=422)
    db.commit()
    out = issues_worker.write_open_md(db, tmp_path / "open.md").read_text(encoding="utf-8")
    assert "TypeError: no bill for [email], phone [phone] at [location]" in out
    for personal in ("ravi", "Ravi", "Inventedname", "@example.com", "9876543210", "23.0225", "72.5714", "Invented Pvt", "it broke when"):
        assert personal not in out
    assert "role" in out and "billing" in out
    assert "Phone is needed." not in out and "only words" not in out  # mistakes and words are not bugs to fix
    # a user's report the keepers marked a bug goes in, with their cause, never the user's words
    rep, _ = svc.record(db, "report", page="/my-site/4", error=None, words="Ravi: the upload spins at 9876543210", role="site_engineer", group=False)
    rep.status, rep.cause = "bug", "the photo upload has no timeout on a slow connection"
    db.commit()
    out = svc.open_md(db)
    assert f"Issue #{rep.id}: A user's report on /my-site/:id" in out and "no timeout on a slow connection" in out
    assert "Ravi" not in out and "9876543210" not in out and "upload spins" not in out


def test_the_worker_writes_open_md_nightly(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    issues_worker.sweep(datetime(2026, 10, 22, 0, 0, tzinfo=UTC))  # 5:30 IST
    assert (tmp_path / "issues" / "open.md").read_text(encoding="utf-8").startswith("# Open bugs")


# --- ask the helper ------------------------------------------------------------------------------------


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(settings, "helper_ai_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("test-key-not-real"))
    sent: list[dict] = []

    def fake_post(payload: dict) -> dict:
        sent.append(payload)
        return {"content": [{"type": "text", "text": "The quantity cannot be negative: type 0 or more and save again."}]}

    monkeypatch.setattr(helper_ai, "_post", fake_post)
    return sent


def test_the_helper_ai_is_off_without_the_flag(login_as, monkeypatch):
    monkeypatch.setattr(settings, "helper_ai_enabled", False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("test-key-not-real"))
    called = []
    monkeypatch.setattr(helper_ai, "_post", lambda p: called.append(p))
    c, h = login_as("billing")
    assert c.get("/api/me/helper", headers=h).json() == {"ai": False}
    assert c.post("/api/me/helper/ask", json={"error": "x"}, headers=h).status_code == 409
    assert called == []


def test_the_helper_answers_from_the_field_rules_and_keeps_the_answer(login_as, db, ai_on):
    c, h = login_as("billing")
    assert c.get("/api/me/helper", headers=h).json() == {"ai": True}
    r = c.post("/api/me/issues", json={"kind": "mistake", "page": "/bills/7", "status_code": 422, "error": "Quantity must be 0 or more."}, headers=h)
    iid = r.json()["issue_id"]
    r = c.post("/api/me/helper/ask", json={"issue_id": iid, "page": "/bills/7?x=1", "error": "Quantity must be 0 or more.", "field_rules": ["Line 2: Quantity: Quantity must be 0 or more. Type a number of 0 or more."]}, headers=h)
    assert r.status_code == 200 and r.json()["answer"].startswith("The quantity cannot be negative")
    sent = ai_on[0]
    assert sent["model"] == settings.helper_ai_model == "claude-sonnet-5-5"
    msg = sent["messages"][0]["content"]
    assert "Page: /bills/:id" in msg and "Quantity must be 0 or more" in msg and "x=1" not in msg
    assert "never" in sent["system"].lower() and "cannot change data" in sent["system"]
    a = db.scalar(select(HelperAnswer))
    assert a.issue_id == iid and a.role == "billing" and a.answer.startswith("The quantity")
    # it changed nothing: the issue is as it was
    assert db.get(Issue, iid).status == "guided"


def test_a_client_s_question_never_carries_costs_margins_places_or_secrets(login_as, ai_on):
    c, h = login_as("client")
    error = "Could not load the bill: cost ₹ 12,50,000 (Rs. 9,800 per sqm), margin 18% at 23.0225, 72.5714; password=hunter22"
    r = c.post("/api/me/helper/ask", json={"page": "/portal/sites/3", "error": error, "question": "why is the rate 450 INR and what is your margin?"}, headers=h)
    assert r.status_code == 200
    msg = ai_on[0]["messages"][0]["content"]
    for leak in ("12,50,000", "9,800", "18%", "450", "margin 18", "23.0225", "72.5714", "hunter22"):
        assert leak not in msg, leak
    assert "Could not load the bill" in msg
    # staff see their own numbers (no place, no secret still)
    c2, h2 = login_as("billing")
    c2.post("/api/me/helper/ask", json={"page": "/bills/3", "error": error}, headers=h2)
    staff = ai_on[1]["messages"][0]["content"]
    assert "12,50,000" in staff and "23.0225" not in staff and "hunter22" not in staff


def test_the_helper_says_so_plainly_when_the_ai_is_down(login_as, monkeypatch, ai_on):
    def down(payload):
        raise RuntimeError("HTTP 529 from the AI service")

    monkeypatch.setattr(helper_ai, "_post", down)
    c, h = login_as("billing")
    r = c.post("/api/me/helper/ask", json={"error": "x"}, headers=h)
    assert r.status_code == 503 and "Report this" in r.json()["detail"]
