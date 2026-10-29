# ruff: noqa: E501  (invented data reads better unwrapped)
"""Bug sweep, group A: settings 1, 7, 8 and My work 6, 10 (data/sop/bugs-found-writing-the-sops.md)."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.field.models import FieldDay, TravelClaim, TravelClaimDay
from app.ops.help import DEFAULTS

STEPS = [
    {"name": "Prep", "weight_percent": "60", "needs_photo": False},
    {"name": "Coat", "weight_percent": "40", "needs_photo": False},
]
CHECKLIST = {"name": "Bug sweep A checks", "items": [{"text": "Surface dry", "type": "pass_fail", "required": True}]}  # fmt: skip


def test_process_settings_default_person_can_be_cleared(login_as, make_user):
    """Settings 1: choosing the empty option sends null and clears the default person."""
    c, h = login_as("super_admin")
    planner = make_user("planner-a@example.com", "planning")
    r = c.put(
        "/api/process/settings", json={"default_users": {"planning": str(planner.id)}}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_users"] == {"planning": str(planner.id)}
    r = c.put("/api/process/settings", json={"default_users": {"planning": None}}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["default_users"] == {}


def test_planning_edits_stage_and_checklist_templates_others_still_cannot(login_as):
    """Settings 7 and 8: the planning role (planning.edit, no site.edit) may keep the templates."""
    c, h = login_as("planning")
    r = c.post(
        "/api/stage-templates", json={"name": "Bug sweep A coating", "steps": STEPS}, headers=h
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = c.put(
        f"/api/stage-templates/{tid}",
        json={"name": "Bug sweep A coating 2", "steps": STEPS},
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = c.post("/api/execution/checklists", json=CHECKLIST, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = c.put(f"/api/execution/checklists/{cid}", json={**CHECKLIST, "is_active": False}, headers=h)
    assert r.status_code == 200 and r.json()["is_active"] is False
    # a site role (inspection.edit for its own sites only) and the estimator still may not
    c2, h2 = login_as("site_engineer")
    assert (
        c2.post(
            "/api/execution/checklists", json={**CHECKLIST, "name": "x"}, headers=h2
        ).status_code
        == 403
    )
    assert (
        c2.post("/api/stage-templates", json={"name": "x", "steps": STEPS}, headers=h2).status_code
        == 403
    )
    c3, h3 = login_as("estimator")
    assert (
        c3.post("/api/stage-templates", json={"name": "y", "steps": STEPS}, headers=h3).status_code
        == 403
    )


def test_day_km_basis_is_refused_once_the_claim_no_longer_follows_it(login_as, make_user, db):
    """My work 6: Use road / tracked km after the manager approved the claim (or edited that day)
    used to change the day silently while the claim kept the old km."""
    worker = make_user("walker-a@example.com", "sales")
    c, h = login_as("office_admin")  # field.team all: sees everyone, field.track: may choose
    day = FieldDay(
        user_id=worker.id,
        on_date=date(2026, 10, 6),
        started_at=datetime(2026, 10, 6, 3, 30, tzinfo=UTC),
        ended_at=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
        route_km=Decimal("15"),
        tracked_km=Decimal("18"),
    )
    claim = TravelClaim(user_id=worker.id, month="2026-10", status="ready")
    db.add_all([day, claim])
    db.flush()
    row = TravelClaimDay(claim_id=claim.id, day_id=day.id, on_date=day.on_date, km=Decimal("15"), rate_per_km=Decimal("4"), amount=Decimal("60"))  # fmt: skip
    db.add(row)
    db.commit()
    body = {"basis": "tracked", "reason": "A detour the stops don't show"}
    # still with the manager, not edited: allowed, and the map says nothing is locked
    got = c.get(f"/api/field/days/{day.id}", headers=h).json()
    assert got["can_choose_basis"] is True and got["basis_locked"] is None
    assert c.put(f"/api/field/days/{day.id}/basis", json=body, headers=h).status_code == 200
    # the manager edited the day on the claim: refused, the claim's Edit is the way
    row.edited_by = worker.id
    db.commit()
    r = c.put(f"/api/field/days/{day.id}/basis", json={"basis": "route"}, headers=h)
    assert r.status_code == 409 and "changed this day" in r.json()["detail"]
    # approved by the manager: refused, and the map hides the buttons with the reason
    row.edited_by = None
    claim.status = "manager_approved"
    db.commit()
    r = c.put(f"/api/field/days/{day.id}/basis", json={"basis": "route"}, headers=h)
    assert r.status_code == 409 and "already approved" in r.json()["detail"]
    assert (
        "already approved" in c.get(f"/api/field/days/{day.id}", headers=h).json()["basis_locked"]
    )
    db.refresh(day)
    assert day.km_basis == "tracked"  # unchanged by the refused calls


def test_help_texts_promise_only_what_the_app_does():
    """My work 10 (and 7): the help texts no longer describe missing features."""
    text = {page: " ".join(v[""][1]) for page, v in DEFAULTS.items() if "" in v}
    assert (
        "moves to Done" not in text["/my-work"] and "goes to your manager" not in text["/my-work"]
    )
    assert "Mark all read when" not in text["/notifications"]
    assert "Submit the claim" not in text["/field/claims"]
    assert "fill in by themselves" not in text["/attendance"]
    assert "a rejected one tells you why" in text["/petty-cash"]
