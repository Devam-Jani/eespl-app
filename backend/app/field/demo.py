# ruff: noqa: E501  (the invented day reads better unwrapped)
"""DEMO field tracking (invented, demo users only): python -m app.cli seed-demo-field

- DEMO Sales, 14 Oct 2026: home -> DEMO Shela -> a vendor -> DEMO Gota Clinic -> home, the points
  sampled along the real road (our OSRM), one gap (the phone's screen off for 53 minutes) and the
  check-in at DEMO Gota Clinic outside its circle (with the reason).
- DEMO Site Engineer, September 2026: 20 working days, the rate per km from ₹4.00 to ₹4.50 on the
  15th; the claim approved by the manager (DEMO Director) and waiting for accounts.
- DEMO Site Supervisor checks DEMO Laxman gang in at DEMO Shela in the morning and at DEMO Gota
  Clinic in the afternoon of 14 Oct.
Everything runs through the field service on a moved clock, as a real day would. Re-running
replaces the DEMO field data."""

import io
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.field import geo, hooks, service
from app.field.models import FieldDay, GangVisit, TravelClaim, TravelRate
from app.models import User
from app.sites.models import Site, SiteMember
from app.team.demo import email_for
from app.timefmt import IST

SHELA = (22.99750, 72.46000)
GOTA = (23.10300, 72.54100)
VENDOR = (22.99200, 72.50150)  # invented polymers dealer, Sarkhej
HOMES = {"sales": (23.03370, 72.46330), "site_engineer": (23.03000, 72.51700)}  # Bopal, Satellite


def ist(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(UTC)


def _user(db: Session, role: str) -> User:
    u = db.scalar(select(User).where(User.email == email_for(role)))
    if u is None:
        raise SystemExit("Run python -m app.cli seed-demo-team first (the DEMO users).")
    return u


def _photo(text: str) -> str:
    """An invented placeholder photo (never a real face), stored like an upload."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    img = Image.new("RGB", (480, 640), (214, 230, 222))
    d = ImageDraw.Draw(img)
    d.ellipse((150, 120, 330, 330), fill=(160, 186, 172))
    d.rectangle((110, 360, 370, 600), fill=(160, 186, 172))
    d.text((20, 20), text, fill=(20, 50, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    rel = f"field/demo/{uuid.uuid4().hex}__demo.jpg"
    p = Path(settings.media_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    return rel


def _site(db: Session, name: str, at: tuple[float, float], code_hint: str | None = None) -> Site:
    from app.sites.service import next_code  # noqa: PLC0415

    s = db.scalar(select(Site).where(Site.name == name))
    if s is None:
        s = Site(
            code=next_code(db),
            name=name,
            status="active",
            city="Ahmedabad",
            state="Gujarat",
            is_demo=True,
        )
        db.add(s)
        db.flush()
    s.lat, s.lng, s.radius_m = Decimal(str(at[0])), Decimal(str(at[1])), None
    return s


def _member(db: Session, site: Site, user: User, role: str) -> None:
    if not db.scalar(
        select(SiteMember).where(SiteMember.site_id == site.id, SiteMember.user_id == user.id)
    ):
        db.add(SiteMember(site_id=site.id, user_id=user.id, role_on_site=role))


def _along(
    a: tuple[float, float],
    b: tuple[float, float],
    depart: datetime,
    arrive: datetime,
    rnd: random.Random,
    every_s: int = 120,
) -> list[dict]:
    """Points every 2 minutes along the real road from a to b (OSRM), a few metres of GPS noise."""
    legs = geo.road_legs([a, b], 1.3, geometry=True)
    line = legs[0].geometry if legs and legs[0].geometry else [list(a), list(b)]
    cum = [0.0]
    for p, q in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + geo.metres(p[0], p[1], q[0], q[1]))
    total = cum[-1] or 1.0
    out = []
    n = max(1, int((arrive - depart).total_seconds() // every_s))
    for i in range(1, n + 1):
        f = i / n
        target = total * f
        j = max(k for k in range(len(cum)) if cum[k] <= target) if target > 0 else 0
        j = min(j, len(line) - 2)
        seg = (cum[j + 1] - cum[j]) or 1.0
        t = (target - cum[j]) / seg
        lat = line[j][0] + (line[j + 1][0] - line[j][0]) * t + rnd.gauss(0, 4) / 111195
        lng = (
            line[j][1]
            + (line[j + 1][1] - line[j][1]) * t
            + rnd.gauss(0, 4) / (111195 * math.cos(math.radians(lat)))
        )
        out.append(
            {
                "at": depart + (arrive - depart) * f,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "accuracy": round(abs(rnd.gauss(12, 5)) + 4, 1),
            }
        )
    return out


def _stay(
    at: tuple[float, float], start: datetime, end: datetime, rnd: random.Random
) -> list[dict]:
    """Standing at a place: a point every 2 minutes, a few metres around it."""
    out, t = [], start + timedelta(minutes=2)
    while t < end:
        out.append(
            {
                "at": t,
                "lat": round(at[0] + rnd.gauss(0, 6) / 111195, 6),
                "lng": round(at[1] + rnd.gauss(0, 6) / 111195, 6),
                "accuracy": round(abs(rnd.gauss(10, 4)) + 4, 1),
            }
        )
        t += timedelta(minutes=2)
    return out


class _Clock:
    def __init__(self):
        self.at = datetime.now(UTC)

    def __call__(self):
        return self.at


def _profile(db: Session, user: User, home, manager: User, rates: list[tuple[str, date]]) -> None:
    p = service.profile(db, user.id)
    p.tracked, p.reimbursable, p.vehicle, p.manager_id = True, True, "bike", manager.id
    p.home_lat, p.home_lng, p.home_status = home[0], home[1], "approved"
    p.pending_lat = p.pending_lng = None
    p.home_approved_by, p.home_approved_at = _user(db, "office_admin").id, datetime.now(UTC)
    db.execute(delete(TravelRate).where(TravelRate.user_id == user.id))
    for i, (rate, start) in enumerate(rates):
        end = rates[i + 1][1] - timedelta(days=1) if i + 1 < len(rates) else None
        db.add(
            TravelRate(
                user_id=user.id,
                vehicle="bike",
                rate_per_km=Decimal(rate),
                valid_from=start,
                valid_to=end,
            )
        )
    service.give_consent(db, user.id)


def _day(
    db: Session, clock: _Clock, user: User, on: date, plan: list[dict], home, rnd: random.Random
) -> FieldDay:
    """One day through the service: start at home, each stop (travel points, check-in, points
    while there, check-out), back home, end. A stop: {at, site|kind+note, arrive, leave, gap?,
    outside_reason?}."""
    clock.at = plan[0]["depart"]
    service.start_day(db, user.id, home[0] + rnd.gauss(0, 15) / 111195, home[1], 12.0)
    here, t = home, plan[0]["depart"]
    for st in plan:
        pts = _along(here, st["at"], t, st["arrive"], rnd)
        if st.get("gap"):
            a, b = st["gap"]
            pts = [p for p in pts if not a <= p["at"] <= b]
        clock.at = st["arrive"]
        service.add_points(db, user.id, pts, "web", f"demo-{on}-{st['arrive']:%H%M}")
        spot = st.get("check_at", st["at"])
        selfie = _photo(f"DEMO selfie {user.full_name}") if st.get("site") else None
        service.check_in(
            db,
            user.id,
            "site" if st.get("site") else st["kind"],
            st["site"].id if st.get("site") else None,
            st.get("note"),
            spot[0],
            spot[1],
            9.0,
            st.get("outside_reason"),
            selfie,
        )
        clock.at = st["leave"]
        service.add_points(
            db,
            user.id,
            _stay(spot, st["arrive"], st["leave"], rnd),
            "web",
            f"demo-{on}-{st['leave']:%H%M}",
        )
        service.check_out(db, user.id, spot[0], spot[1], 9.0, st.get("outside_reason"), None)
        here, t = st["at"], st["leave"]
    home_at = plan[-1]["home"]
    clock.at = home_at
    service.add_points(db, user.id, _along(here, home, t, home_at, rnd), "web", f"demo-{on}-home")
    return service.end_day(db, user.id, home[0], home[1] + rnd.gauss(0, 15) / 111195, 11.0)


def seed(db: Session) -> list[str]:
    clock = _Clock()
    real_now = service.now
    service.now = clock  # the demo days happen on their own dates
    try:
        return _seed(db, clock)
    finally:
        service.now = real_now


def _seed(db: Session, clock: _Clock) -> list[str]:
    rnd = random.Random(22)
    sales, engineer, supervisor, director = (
        _user(db, r) for r in ("sales", "site_engineer", "site_supervisor", "director")
    )
    shela = _site(db, "DEMO Shela", SHELA)
    gota = _site(db, "DEMO Gota Clinic", GOTA)
    for s in (shela, gota):
        _member(db, s, sales, "sales")
        _member(db, s, engineer, "incharge")
        _member(db, s, supervisor, "supervisor")
    people = [sales, engineer]
    # replace any earlier DEMO field data
    db.execute(delete(TravelClaim).where(TravelClaim.user_id.in_([u.id for u in people])))
    db.execute(delete(FieldDay).where(FieldDay.user_id.in_([u.id for u in people])))
    db.execute(delete(GangVisit).where(GangVisit.supervisor_id == supervisor.id))
    from app.execution.models import StaffAttendance  # noqa: PLC0415

    db.execute(
        delete(StaffAttendance).where(
            StaffAttendance.user_id.in_([u.id for u in people]),
            StaffAttendance.site_id.in_([shela.id, gota.id]),
        )
    )
    _profile(db, sales, HOMES["sales"], director, [("4.00", date(2026, 4, 1))])
    _profile(
        db,
        engineer,
        HOMES["site_engineer"],
        director,
        [("4.00", date(2026, 4, 1)), ("4.50", date(2026, 9, 15))],
    )
    sp = service.profile(db, supervisor.id)
    sp.tracked, sp.reimbursable, sp.manager_id = False, False, engineer.id
    db.flush()
    out = []

    # --- DEMO Sales, 14 Oct: the day on the map ---
    on = date(2026, 10, 14)
    gota_gate = (GOTA[0] + 320 / 111195, GOTA[1])  # 320 m north of the pin: the main gate
    plan = [
        {"depart": ist(on, 9, 5), "at": SHELA, "site": shela, "arrive": ist(on, 9, 32), "leave": ist(on, 10, 45)},
        {"at": VENDOR, "kind": "vendor", "note": "DEMO Polymers dealer, Sarkhej (invented)", "arrive": ist(on, 11, 5), "leave": ist(on, 11, 40)},
        {"at": GOTA, "check_at": gota_gate, "site": gota, "arrive": ist(on, 12, 38), "leave": ist(on, 14, 10),
         "gap": (ist(on, 11, 44), ist(on, 12, 37)), "outside_reason": "DEMO: site gate is on the service road; checked in at the main gate"},
    ]  # fmt: skip
    plan[-1]["home"] = ist(on, 14, 55)
    day = _day(db, clock, sales, on, plan, HOMES["sales"], rnd)
    out.append(
        f"DEMO Sales {on}: road {day.route_km} km, tracked {day.tracked_km} km, flags {[f['code'] for f in day.flags]}"
    )

    # --- DEMO Site Engineer, September: 20 working days, the rate from ₹4.00 to ₹4.50 on the 15th ---
    days, d = [], date(2026, 9, 1)
    while len(days) < 20:
        if d.weekday() != 6 and d.day not in (5, 12, 19, 26):  # Sundays off, and four Saturdays
            days.append(d)
        d += timedelta(days=1)
    for i, on in enumerate(days):
        start = ist(on, 9, rnd.randint(0, 20))
        stops = [
            {
                "depart": start,
                "at": SHELA,
                "site": shela,
                "arrive": start + timedelta(minutes=45),
                "leave": start + timedelta(minutes=45 + rnd.randint(90, 180)),
            }
        ]
        if i % 3 == 1:  # every third day also the Gota clinic
            arr = stops[-1]["leave"] + timedelta(minutes=50)
            stops.append(
                {
                    "at": GOTA,
                    "site": gota,
                    "arrive": arr,
                    "leave": arr + timedelta(minutes=rnd.randint(60, 120)),
                }
            )
        if i == 7:  # one flagged day: checked in at the wrong gate
            stops[0]["check_at"] = (SHELA[0], SHELA[1] + 260 / 102000)
            stops[0]["outside_reason"] = "DEMO: entered from the back lane"
        stops[-1]["home"] = stops[-1]["leave"] + timedelta(minutes=55)
        _day(db, clock, engineer, on, stops, HOMES["site_engineer"], rnd)
    clock.at = ist(date(2026, 10, 1), 7, 0)
    claim = service.build_claim(db, engineer.id, "2026-09", ready=True)
    hooks.claim_ready(db, claim)
    clock.at = ist(date(2026, 10, 2), 11, 0)
    claim.status, claim.manager_approved_by, claim.manager_approved_at = (
        "manager_approved",
        director.id,
        clock.at,
    )
    for x in claim.days:
        x.approved = True
    hooks.manager_approved(db, claim, director.id)
    out.append(
        f"DEMO Site Engineer 2026-09: {len(claim.days)} days, {claim.km} km, ₹{claim.total}, {claim.flagged_days} flagged day(s); approved by DEMO Director, waiting for accounts"
    )

    # --- DEMO Site Supervisor: DEMO Laxman gang on two sites, 14 Oct ---
    from app.execution.models import Labour  # noqa: PLC0415
    from app.masters.models import Vendor  # noqa: PLC0415

    gang = db.scalar(select(Vendor).where(Vendor.name.ilike("DEMO Laxman gang%")))
    if gang is not None:
        workers = [
            w.id
            for w in db.scalars(
                select(Labour).where(Labour.subcontractor_id == gang.id, Labour.is_active.is_(True))
            )
        ]
        on = date(2026, 10, 14)
        for site, (a, b), spot in (
            (shela, ((8, 30), (12, 30)), SHELA),
            (gota, ((13, 30), (17, 30)), GOTA),
        ):
            clock.at = ist(on, *a)
            v = service.gang_check_in(
                db,
                supervisor.id,
                site,
                gang.id,
                workers,
                None,
                spot[0],
                spot[1],
                8.0,
                None,
                _photo("DEMO gang photo"),
            )
            clock.at = ist(on, *b)
            service.gang_check_out(db, v, site, spot[0], spot[1], 8.0, None, None)
        out.append(
            f"DEMO Site Supervisor {on}: {gang.name} ({len(workers)}) at DEMO Shela 08:30-12:30 and DEMO Gota Clinic 13:30-17:30"
        )
    db.commit()
    return out
