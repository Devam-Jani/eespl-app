# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Field tracking with invented people, places and points, on a frozen clock; OSRM is mocked
except in one smoke test: consent, the day, points, check-ins and their flags, km, the claim,
offline batches, gang check-ins into the attendance bill, who sees what, retention, Google Maps."""

import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.execution.models import Labour
from app.field import geo, hooks, service
from app.field.models import FieldDay, LocationPoint, TravelClaim
from app.masters.models import Vendor
from app.models import AuditLog, User
from app.sites.models import Site, SiteMember
from tests.conftest import login
from tests.test_finance import boss, world  # noqa: F401  (fixtures)

HOME = (23.0300, 72.5000)
SHELA = (23.0000, 72.4600)
M_LAT = 1 / 111_195  # degrees of latitude in a metre


def d(v) -> Decimal:
    return Decimal(str(v))


def north(p, metres):
    return (p[0] + metres * M_LAT, p[1])


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime(2026, 10, 6, 3, 30, tzinfo=UTC))  # 09:00 IST, a Tuesday
    monkeypatch.setattr(service, "now", c)
    return c


@pytest.fixture
def osrm(monkeypatch):
    """A fake OSRM: each leg 5 km more than the one before (5, 10, 15 ...), 10 minutes each;
    `down` makes it unreachable."""
    state = {"down": False, "calls": 0}

    def fake(path):
        state["calls"] += 1
        if state["down"]:
            raise urllib.error.URLError("down")
        n = len(path.split("?")[0].rsplit("/", 1)[1].split(";"))
        if path.startswith("/trip/"):
            return {
                "code": "Ok",
                "waypoints": [{"waypoint_index": 0}]
                + [{"waypoint_index": n - i} for i in range(1, n)],
            }
        legs = [{"distance": 5000 * (i + 1), "duration": 600} for i in range(n - 1)]
        return {
            "code": "Ok",
            "routes": [{"legs": legs, "geometry": {"coordinates": [[72.5, 23.03], [72.46, 23.0]]}}],
        }

    monkeypatch.setattr(geo, "_get", fake)
    return state


@pytest.fixture
def team(world, db, make_user, boss, clock, osrm):
    """A salesperson (tracked, eligible, a bike at ₹4/km) whose manager is a site engineer; a
    second salesperson; office admin, accounts, a client; the site pinned at Shela."""
    c, h = boss
    for email, role, name in [
        ("sales@example.com", "sales", "Invented Sales"), ("sales2@example.com", "sales", "Invented Sales Two"),
        ("engineer@example.com", "site_engineer", "Invented Manager"), ("admin@example.com", "office_admin", "Invented Admin"),
        ("accounts@example.com", "accounts", "Invented Accounts"), ("client@example.com", "client", "Invented Client"),
    ]:  # fmt: skip
        make_user(email, role, name=name)
    ids = {
        e.split("@")[0]: str(db.scalar(select(User.id).where(User.email == e)))
        for e in ("sales@example.com", "sales2@example.com", "engineer@example.com")
    }
    admin = login(c, "admin@example.com")
    for who in ("sales", "sales2"):
        r = c.put(
            f"/api/field/admin/people/{ids[who]}",
            json={
                "tracked": True,
                "reimbursable": who == "sales",
                "vehicle": "bike",
                "manager_id": ids["engineer"],
            },
            headers=admin,
        )
        assert r.status_code == 200, r.text
    assert (
        c.post(
            f"/api/field/admin/people/{ids['sales']}/rates",
            json={"rate_per_km": "4", "valid_from": "2026-10-01"},
            headers=admin,
        ).status_code
        == 201
    )
    r = c.put(
        f"/api/field/sites/{world['site']}/location",
        json={"lat": SHELA[0], "lng": SHELA[1]},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["radius_m"] == 150
    hs = {
        k: login(c, f"{k}@example.com")
        for k in ("sales", "sales2", "engineer", "admin", "accounts")
    }
    # home: picked by the person, approved by office admin
    c.put("/api/field/home", json={"lat": HOME[0], "lng": HOME[1]}, headers=hs["sales"])
    assert (
        c.post(
            f"/api/field/admin/people/{ids['sales']}/home", json={"approve": True}, headers=admin
        ).json()["home_status"]
        == "approved"
    )
    return {
        "c": c,
        "h": hs,
        "ids": ids,
        "site": world["site"],
        "client": login(c, "client@example.com"),
    }


def consent(t, who="sales"):
    r = t["c"].post("/api/field/consent", headers=t["h"][who])
    assert r.status_code == 200 and r.json()["given"]


def start(t, at=HOME, who="sales", accuracy=10):
    return t["c"].post(
        "/api/field/day/start",
        json={"lat": at[0], "lng": at[1], "accuracy": accuracy},
        headers=t["h"][who],
    )


def end(t, at=HOME, who="sales"):
    return t["c"].post(
        "/api/field/day/end", json={"lat": at[0], "lng": at[1], "accuracy": 10}, headers=t["h"][who]
    )


def points(t, pts, who="sales", batch=None):
    body = {
        "source": "web",
        "batch": batch,
        "points": [
            {"at": a.isoformat(), "lat": p[0], "lng": p[1], "accuracy": acc} for a, p, acc in pts
        ],
    }
    r = t["c"].post("/api/field/points", json=body, headers=t["h"][who])
    assert r.status_code == 200, r.text
    return r.json()


def check_in(t, at, reason=None, kind="site", note=None, who="sales"):
    data = {"kind": kind, "lat": at[0], "lng": at[1], "accuracy": 8}
    if kind == "site":
        data["site_id"] = t["site"]
    if reason:
        data["reason"] = reason
    if note:
        data["note"] = note
    files = {"selfie": ("me.jpg", b"\xff\xd8 invented selfie", "image/jpeg")}
    return t["c"].post("/api/field/stops/in", data=data, files=files, headers=t["h"][who])


def check_out(t, at, who="sales", reason=None):
    return t["c"].post(
        "/api/field/stops/out",
        data={"lat": at[0], "lng": at[1], "accuracy": 8} | ({"reason": reason} if reason else {}),
        headers=t["h"][who],
    )


def test_no_consent_no_points_no_claim_and_a_new_version_asks_again(team, clock, db):
    t = team
    assert start(t).status_code == 403  # nothing is recorded without consent
    r = points(t, [(clock.at, HOME, 10)])
    assert r["stored"] == 0 and r["rejected"] == 1
    assert (
        t["c"]
        .post("/api/field/claims/build", json={"month": "2026-10"}, headers=t["h"]["sales"])
        .status_code
        == 422
    )
    assert db.scalar(select(LocationPoint.id)) is None and db.scalar(select(TravelClaim.id)) is None
    me = t["c"].get("/api/field/me", headers=t["h"]["sales"]).json()
    assert not me["consent"]["given"] and "Start day to End day" in me["consent"]["text"]["what"]
    consent(t)
    assert start(t).status_code == 200
    # a new consent version: asked again, and nothing is stored meanwhile
    admin = t["c"].post("/api/auth/login", json={"email": "admin@example.com", "password": "x"})  # noqa: F841
    t["c"].put(
        "/api/field/admin/settings", json={"consent_version": "2027-01"}, headers=t["h"]["admin"]
    )
    me = t["c"].get("/api/field/me", headers=t["h"]["sales"]).json()["consent"]
    assert not me["given"] and me["asked_again"] and me["earlier_version"] == "2026-10"
    clock.at += timedelta(minutes=5)
    assert points(t, [(clock.at, HOME, 10)])["stored"] == 0
    consent(t)
    assert points(t, [(clock.at, HOME, 10)])["stored"] == 1


def test_points_only_between_start_and_end_and_the_day_ends_itself_at_the_set_time(team, clock, db):
    t = team
    consent(t)
    before = clock.at - timedelta(minutes=10)
    assert points(t, [(before, HOME, 10)])["rejected"] == 1  # before Start day
    start(t)
    clock.at += timedelta(hours=1)
    assert points(t, [(before, HOME, 10), (clock.at, north(HOME, 500), 10)]) == {
        "stored": 1,
        "duplicates": 0,
        "rejected": 1,
    }
    assert end(t).status_code == 200
    clock.at += timedelta(minutes=5)
    assert points(t, [(clock.at, HOME, 10)])["rejected"] == 1  # after End day
    # the next day nobody presses End day: it ends at 21:00 IST on its own
    clock.at = datetime(2026, 10, 7, 3, 30, tzinfo=UTC)
    assert start(t).status_code == 200
    clock.at = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)  # 21:30 IST
    assert points(t, [(clock.at, HOME, 10)])["rejected"] == 1  # past the auto end
    service.auto_end(db)
    db.commit()
    day = db.scalar(select(FieldDay).where(FieldDay.on_date == date(2026, 10, 7)))
    assert day.auto_ended and day.ended_at == datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
    assert any(f["code"] == "auto_ended" for f in day.flags)


def test_check_in_inside_the_radius_is_ok_outside_is_flagged_with_the_distance_and_needs_a_reason(
    team, clock, db
):
    t = team
    consent(t)
    start(t)
    clock.at += timedelta(minutes=30)
    r = check_in(t, north(SHELA, 60))
    assert (
        r.status_code == 200
        and not r.json()["in_outside"]
        and round(r.json()["in_distance_m"]) == 60
    )
    clock.at += timedelta(minutes=45)
    assert check_out(t, north(SHELA, 40)).json()["minutes"] == 45
    clock.at += timedelta(hours=1)
    r = check_in(t, north(SHELA, 420))
    assert r.status_code == 422 and "420 m" in r.json()["detail"] and "reason" in r.json()["detail"]
    r = check_in(t, north(SHELA, 420), reason="Gate closed, waited at the main road")
    assert r.status_code == 200 and r.json()["in_outside"]
    day = t["c"].get("/api/field/me", headers=t["h"]["sales"]).json()["day"]
    flag = next(f for f in day["flags"] if f["code"] == "outside_radius")
    assert "420 m" in flag["text"] and "Gate closed" in flag["text"]
    # a stop that is not a site: a vendor, with a note
    assert check_out(t, north(SHELA, 420)).status_code == 422  # outside: the reason again
    assert check_out(t, north(SHELA, 420), reason="Left from the gate").status_code == 200
    assert check_in(t, (23.01, 72.48), kind="vendor", note="Invented Polymers").status_code == 200
    # the site check-in is the staff attendance payroll counts
    from app.execution.models import StaffAttendance

    assert (
        db.scalar(select(StaffAttendance).where(StaffAttendance.site_id == t["site"])).check_out_at
        is not None
    )


def test_start_or_end_far_from_home_is_flagged(team, clock, db):
    t = team
    consent(t)
    start(t, at=north(HOME, 300))
    clock.at += timedelta(hours=8)
    end(t, at=north(HOME, 2500))
    day = db.scalar(select(FieldDay))
    codes = {f["code"] for f in day.flags}
    assert "start_far" not in codes and "end_far" in codes  # 300 m is near, 2.5 km is not
    assert any("2.5 km from home" in f["text"] for f in day.flags)


def test_tracked_km_drops_jitter_and_a_300_kmh_jump_route_km_from_osrm_and_estimated_when_down(
    team, clock, osrm, db
):
    t = team
    consent(t)
    start(t)
    t0 = clock.at
    pts = [
        (t0 + timedelta(minutes=2), HOME, 10),
        (t0 + timedelta(minutes=4), north(HOME, 10), 10),  # jitter: under 30 m
        (t0 + timedelta(minutes=6), north(HOME, 20), 10),  # jitter
        (t0 + timedelta(minutes=10), north(HOME, 1000), 10),  # 1 km in 8 minutes
        (t0 + timedelta(minutes=11), north(HOME, 6000), 10),  # 5 km in 1 minute: 300 km/h, dropped
        (t0 + timedelta(minutes=20), north(HOME, 2000), 10),  # 1 km more
        (t0 + timedelta(minutes=22), north(HOME, 9000), 500),  # poor accuracy: kept, not used
    ]
    clock.at += timedelta(minutes=25)  # sent after they were taken
    assert points(t, pts)["stored"] == 7
    day = db.scalar(select(FieldDay))
    db.refresh(day)
    assert d(day.tracked_km) == d("2.000") and day.points_total == 7
    assert any(f["code"] == "jump" and "300 km/h" in f["text"] for f in day.flags)
    clock.at += timedelta(minutes=30)
    check_in(t, SHELA)
    clock.at += timedelta(minutes=30)
    check_out(t, SHELA)
    clock.at += timedelta(minutes=30)
    out = end(t).json()
    # home -> Shela -> home: the mocked legs are 5 and 10 km
    assert (
        [leg["km"] for leg in out["legs"]] == [5.0, 10.0]
        and d(out["route_km"]) == 15
        and not out["route_estimated"]
    )
    assert out["km_basis"] == "route" and d(out["km"]) == 15
    # OSRM down: the straight line x 1.3, estimated; recalculated when it is back
    osrm["down"] = True
    db.expire_all()  # the day as the API left it (ended, with its stop)
    day = db.scalar(select(FieldDay))
    service.compute_km(db, day)
    straight = geo.metres(*HOME, *SHELA) / 1000 * 1.3 * 2
    assert day.route_estimated and abs(float(day.route_km) - straight) < 0.01
    assert any(f["code"] == "estimated" for f in day.flags)
    osrm["down"] = False
    assert service.recalc_estimated(db) == 1 and d(day.route_km) == 15 and not day.route_estimated


def test_the_claim_km_times_the_rate_on_each_date_manager_edits_with_a_reason_accounts_lock_it(
    team, clock, osrm, db
):
    t = team
    consent(t)
    consent(t, "sales2")
    # a new rate from the 15th: ₹5/km (the ₹4 rate ends on the 14th; the history is kept)
    r = t["c"].post(
        f"/api/field/admin/people/{t['ids']['sales']}/rates",
        json={"rate_per_km": "5", "valid_from": "2026-10-15"},
        headers=t["h"]["admin"],
    )
    assert [(x["rate_per_km"], x["valid_to"]) for x in r.json()["rates"]] == [
        (5.0, None),
        (4.0, "2026-10-14"),
    ]
    for day_ in (6, 20):
        clock.at = datetime(2026, 10, day_, 3, 30, tzinfo=UTC)
        start(t)
        start(t, who="sales2")
        clock.at += timedelta(hours=1)
        check_in(t, SHELA)
        clock.at += timedelta(hours=1)
        check_out(t, SHELA)
        clock.at += timedelta(hours=1)
        end(t)
        end(t, who="sales2")
    # the 1st: the claim is ready (the person and the manager are told)
    clock.at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    assert hooks.claims_on_the_first(db, clock.at) == 1  # sales2 is not eligible: no claim
    db.commit()
    c = db.scalar(select(TravelClaim))
    assert c.status == "ready" and c.user_id == db.get(User, c.user_id).id
    claim = t["c"].get(f"/api/field/claims/{c.id}", headers=t["h"]["sales"]).json()
    assert [(x["on_date"], x["km"], x["rate_per_km"], x["amount"]) for x in claim["days"]] == [
        ("2026-10-06", 15.0, 4.0, 60.0), ("2026-10-20", 15.0, 5.0, 75.0)]  # fmt: skip
    assert claim["total"] == 135
    assert t["c"].get("/api/field/claims?month=2026-10", headers=t["h"]["sales2"]).json() == []
    # a toll with its bill photo
    r = t["c"].post(f"/api/field/claims/{c.id}/extras", data={"on_date": "2026-10-20", "kind": "toll", "amount": "40"},
                    files={"bill": ("toll.jpg", b"\xff\xd8 invented bill", "image/jpeg")}, headers=t["h"]["sales"])  # fmt: skip
    assert r.status_code == 201 and r.json()["total"] == 175
    # the manager: an edit needs a reason; the person cannot approve their own claim
    did = claim["days"][1]["id"]
    assert (
        t["c"]
        .put(f"/api/field/claims/{c.id}/days/{did}", json={"km": "12"}, headers=t["h"]["engineer"])
        .status_code
        == 422
    )
    r = t["c"].put(
        f"/api/field/claims/{c.id}/days/{did}",
        json={"km": "12", "reason": "The second site was on the way back"},
        headers=t["h"]["engineer"],
    )
    assert (
        r.status_code == 200
        and r.json()["days"][1]["amount"] == 60
        and r.json()["days"][1]["edited_km_from"] == 15
    )
    assert (
        t["c"]
        .post(f"/api/field/claims/{c.id}/manager-approve", headers=t["h"]["sales"])
        .status_code
        == 403
    )
    assert (
        t["c"].post(f"/api/field/claims/{c.id}/approve", headers=t["h"]["accounts"]).status_code
        == 409
    )  # the manager first
    assert (
        t["c"]
        .post(f"/api/field/claims/{c.id}/manager-approve", headers=t["h"]["engineer"])
        .json()["status"]
        == "manager_approved"
    )
    r = t["c"].post(f"/api/field/claims/{c.id}/approve", headers=t["h"]["accounts"])
    assert (
        r.status_code == 200
        and r.json()["locked"]
        and r.json()["total"] == 160
        and r.json()["payroll_month"] == "2026-11"
    )
    # locked: no more edits, extras or rebuilds
    assert (
        t["c"]
        .put(
            f"/api/field/claims/{c.id}/days/{did}",
            json={"km": "1", "reason": "x"},
            headers=t["h"]["engineer"],
        )
        .status_code
        == 403
    )
    db.expire_all()
    assert service.build_claim(db, c.user_id, "2026-10").total == d("160.00")
    assert service.payroll_reimbursement(db, c.user_id, "2026-11") == d("160.00")
    xlsx = t["c"].get(f"/api/field/claims/{c.id}/export.xlsx", headers=t["h"]["accounts"])
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_offline_points_are_sent_in_order_and_a_duplicate_batch_is_not_counted_twice(
    team, clock, db
):
    t = team
    consent(t)
    start(t)
    t0 = clock.at
    batch = [
        (t0 + timedelta(minutes=m), north(HOME, 1000 * k), 10) for k, m in enumerate((10, 20, 30))
    ]
    clock.at += timedelta(hours=1)
    # queued offline, sent when back online in a scrambled order: stored in time order
    assert points(t, [batch[2], batch[0], batch[1]], batch="b1")["stored"] == 3
    day = db.scalar(select(FieldDay))
    db.refresh(day)
    assert d(day.tracked_km) == d("2.000")
    # the same batch sent again (the phone did not hear the answer): not counted twice
    assert points(t, batch, batch="b1") == {"stored": 0, "duplicates": 3, "rejected": 0}
    db.refresh(day)
    assert d(day.tracked_km) == d("2.000") and day.points_total == 3


def test_gang_check_in_hours_feed_the_attendance_gang_bill_split_by_site(
    team, clock, db, make_user
):
    t = team
    c = t["c"]
    other = Site(
        code="S-2026-9812",
        name="Invented second site",
        status="active",
        lat=d("23.1000"),
        lng=d("72.6000"),
    )
    gang = Vendor(name="Invented Laxmanbhai gang", type="labour_contractor")
    db.add_all([other, gang])
    db.flush()
    workers = [
        Labour(
            name=f"Invented worker {i}",
            type="subcontractor",
            subcontractor_id=gang.id,
            daily_wage=800,
        )
        for i in (1, 2)
    ]
    db.add_all(workers)
    sup = make_user("sup@example.com", "site_supervisor", name="Invented Supervisor")
    db.add_all(
        [
            SiteMember(site_id=t["site"], user_id=sup.id, role_on_site="supervisor"),
            SiteMember(site_id=other.id, user_id=sup.id, role_on_site="supervisor"),
        ]
    )
    db.commit()
    hs = login(c, "sup@example.com")
    photo = {"photo": ("gang.jpg", b"\xff\xd8 invented group photo", "image/jpeg")}
    names = ",".join(str(w.id) for w in workers)
    r = c.post(
        "/api/field/gangs/in",
        data={
            "site_id": t["site"],
            "contractor_id": gang.id,
            "labour_ids": names,
            "lat": SHELA[0],
            "lng": SHELA[1],
        },
        files=photo,
        headers=hs,
    )
    assert r.status_code == 201, r.text
    clock.at += timedelta(hours=4)
    c.post(
        f"/api/field/gangs/{r.json()['id']}/out",
        data={"lat": SHELA[0], "lng": SHELA[1]},
        headers=hs,
    )
    clock.at += timedelta(minutes=30)
    # the second site, outside its radius: allowed with a reason, flagged
    data = {
        "site_id": other.id,
        "contractor_id": gang.id,
        "labour_ids": names,
        "lat": 23.105,
        "lng": 72.6,
    }
    assert c.post("/api/field/gangs/in", data=data, files=photo, headers=hs).status_code == 422
    r = c.post(
        "/api/field/gangs/in",
        data=data | {"reason": "Gang waited at the gate"},
        files=photo,
        headers=hs,
    )
    assert r.status_code == 201 and r.json()["in_outside"]
    clock.at += timedelta(hours=3)
    assert (
        c.post(
            f"/api/field/gangs/{r.json()['id']}/out", data={"lat": 23.1, "lng": 72.6}, headers=hs
        ).json()["hours"]
        == 3
    )
    from app.costing.labour import gang_lines

    lines = {
        ln["site_id"]: ln for ln in gang_lines(db, gang.id, date(2026, 10, 1), date(2026, 10, 31))
    }
    assert (
        d(lines[t["site"]]["qty"]) == 8 and d(lines[other.id]["qty"]) == 6
    )  # 2 people x 4 h, 2 x 3 h
    assert (
        d(lines[t["site"]]["amount"]) == 800 and d(lines[other.id]["amount"]) == 600
    )  # 8 h day at ₹800
    # labour are never tracked and never claim: no point, day or claim is made for them
    assert db.scalar(select(FieldDay.id)) is None and db.scalar(select(TravelClaim.id)) is None
    # a supervisor on someone else's site: not found
    third = Site(code="S-2026-9813", name="Invented third site", status="active")
    db.add(third)
    db.commit()
    assert (
        c.post(
            "/api/field/gangs/in", data=data | {"site_id": third.id}, files=photo, headers=hs
        ).status_code
        == 404
    )


def test_who_sees_a_route_a_salesperson_not_another_accounts_from_the_claim_logged_client_never(
    team, clock, db
):
    t = team
    c = t["c"]
    consent(t)
    consent(t, "sales2")
    start(t)
    day2 = start(t, who="sales2").json()["id"]
    clock.at += timedelta(hours=2)
    day1 = end(t).json()["id"]
    assert c.get(f"/api/field/days/{day1}", headers=t["h"]["sales"]).status_code == 200
    assert (
        c.get(f"/api/field/days/{day2}", headers=t["h"]["sales"]).status_code == 403
    )  # not another's
    assert (
        c.get(f"/api/field/days/{day1}", headers=t["h"]["engineer"]).status_code == 200
    )  # the manager
    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "field.route_view")) is not None
    )  # logged
    # accounts: not the route on its own, only from the claim (and that view is logged)
    assert c.get(f"/api/field/days/{day1}", headers=t["h"]["accounts"]).status_code == 403
    claim = service.build_claim(db, db.get(FieldDay, day1).user_id, "2026-10")
    db.commit()
    assert (
        c.get(f"/api/field/days/{day1}?claim={claim.id}", headers=t["h"]["accounts"]).status_code
        == 200
    )
    log = db.scalars(select(AuditLog).where(AuditLog.action == "field.route_view")).all()
    assert any(x.after["via_claim"] for x in log)
    # a client: 403 everywhere
    for method, path in [("get", "/api/field/me"), ("get", f"/api/field/days/{day1}"), ("get", "/api/field/team"), ("get", "/api/field/claims"),
                         ("post", "/api/field/day/start"), ("post", "/api/field/points"), ("get", f"/api/field/claims/{claim.id}"),
                         ("get", f"/api/field/sites/{t['site']}/visits"), ("get", "/api/field/gangs"), ("get", "/api/field/admin/people")]:  # fmt: skip
        r = getattr(c, method)(
            path, headers=t["client"], **({"json": {}} if method == "post" else {})
        )
        assert r.status_code == 403, (path, r.status_code)
    # the team map: the manager sees their team (both), a salesperson none
    people = c.get("/api/field/team", headers=t["h"]["engineer"]).json()["people"]
    assert {p["name"] for p in people} == {"Invented Sales", "Invented Sales Two"}
    assert c.get("/api/field/team", headers=t["h"]["sales2"]).json()["people"] == []


def test_retention_deletes_raw_points_after_90_days_and_keeps_the_day(team, clock, db):
    t = team
    consent(t)
    start(t)
    t0 = clock.at
    clock.at += timedelta(minutes=30)
    points(
        t,
        [
            (t0 + timedelta(minutes=10), HOME, 10),
            (t0 + timedelta(minutes=20), north(HOME, 1500), 10),
        ],
    )
    clock.at += timedelta(hours=1)
    end(t)
    day = db.scalar(select(FieldDay))
    km = day.tracked_km
    assert service.retention(db, t0 + timedelta(days=89))["points"] == 0
    out = service.retention(db, t0 + timedelta(days=91))
    db.commit()
    assert out["points"] == 2 and db.scalar(select(LocationPoint.id)) is None
    db.refresh(day)
    assert day.points_deleted_at is not None and day.tracked_km == km and day.route_km is not None


def test_go_to_site_is_a_plain_google_maps_link_with_the_pin_and_no_key(team, clock):
    link = geo.maps_link(23.0, 72.46)
    assert link == "https://www.google.com/maps/dir/?api=1&destination=23.000000,72.460000"
    assert "key" not in link
    me = team["c"].get("/api/field/me", headers=team["h"]["engineer"]).json()
    r = (
        team["c"]
        .get(
            f"/api/field/route-to/{team['site']}?lat={HOME[0]}&lng={HOME[1]}",
            headers=team["h"]["sales"],
        )
        .json()
    )
    assert r["maps_link"] == link and r["km"] == 5.0 and me is not None


def test_osrm_smoke_a_real_road_route_in_ahmedabad():
    """The one test against our own OSRM container (skipped when it is not running)."""
    try:
        urllib.request.urlopen(
            geo.settings.osrm_url + "/route/v1/driving/72.46,23.0;72.47,23.0?overview=false",
            timeout=3,
        )
    except (OSError, urllib.error.URLError):
        pytest.skip("OSRM is not running")
    legs = geo.road_legs([(22.9975, 72.4600), (23.0250, 72.5070)], 1.3)
    assert not legs[0].estimated and 5 < legs[0].km < 15 and legs[0].minutes > 0
