# ruff: noqa: E501  (the flag texts read better unwrapped)
"""The day, the km, the flags, the claim, the gang check-ins and the retention (see models)."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.field import geo
from app.field.models import (
    Consent,
    FieldDay,
    FieldSettings,
    FieldStop,
    GangVisit,
    GangVisitWorker,
    LocationPoint,
    TrackingProfile,
    TravelClaim,
    TravelClaimDay,
    TravelRate,
)
from app.models import User
from app.timefmt import IST

ZERO = Decimal(0)
STOP_LABEL = {
    "site": "Site",
    "vendor": "Vendor",
    "godown": "Godown",
    "client_office": "Client office",
    "other": "Other",
}
CONSENT_TEXT = {
    "what": "Your location from Start day to End day only (never before Start day, after End day or on a day off), your check-ins and check-outs with their location and time, and the selfie at each check-in.",
    "why": "Attendance at sites, the site visits you make, and your travel expense per km.",
    "who": "You, your manager, the director and the office admin. Accounts see your claim (and the route only when they open it from the claim; that view is logged). Clients and vendors never. Every view of your route by someone else is logged.",
    "kept": "Location points 90 days; the day's summary (stops, km) and approved claims 8 years (accounts).",
    "where": "On EESPL's own server only: no third-party tracking service. Road distances come from our own map server.",
}


def now() -> datetime:
    """The clock (tests freeze it)."""
    return datetime.now(UTC)


def ist_date(at: datetime) -> date:
    return at.astimezone(IST).date()


def money(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), ROUND_HALF_UP)


def km3(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.001"), ROUND_HALF_UP)


def unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


def settings(db: Session) -> FieldSettings:
    s = db.get(FieldSettings, 1)
    if s is None:
        s = FieldSettings(id=1)
        db.add(s)
        db.flush()
        db.refresh(s)
    return s


def profile(db: Session, user_id) -> TrackingProfile:
    p = db.get(TrackingProfile, user_id)
    if p is None:
        p = TrackingProfile(
            user_id=user_id, tracked=False, reimbursable=False, vehicle="bike", home_status="none"
        )
        db.add(p)
        db.flush()
    return p


# --- consent -------------------------------------------------------------------------------------


def consent_of(db: Session, user_id) -> Consent | None:
    v = settings(db).consent_version
    return db.scalar(
        select(Consent).where(
            Consent.user_id == user_id, Consent.version == v, Consent.withdrawn_at.is_(None)
        )
    )


def consent_out(db: Session, user_id) -> dict:
    s, c, p = settings(db), consent_of(db, user_id), db.get(TrackingProfile, user_id)
    earlier = db.scalar(
        select(Consent.version)
        .where(Consent.user_id == user_id, Consent.version != s.consent_version)
        .order_by(Consent.given_at.desc())
        .limit(1)
    )
    return {
        "version": s.consent_version, "given": c is not None, "given_at": c.given_at if c else None,
        "asked_again": c is None and earlier is not None, "earlier_version": earlier,
        "tracked": bool(p and p.tracked), "text": CONSENT_TEXT,
    }  # fmt: skip


def give_consent(db: Session, user_id) -> Consent:
    c = consent_of(db, user_id)
    if c is None:
        c = Consent(user_id=user_id, version=settings(db).consent_version, given_at=now())
        db.add(c)
        db.flush()
    return c


def withdraw_consent(db: Session, user_id) -> None:
    c = consent_of(db, user_id)
    if c is not None:
        c.withdrawn_at = now()
        day = open_day(db, user_id)
        if day is not None:
            end_day(db, user_id, None, None, None, auto=True)


def require_tracking(db: Session, user_id) -> TrackingProfile:
    """Tracked and consented, or a plain message (the person can still use the rest of the app)."""
    p = db.get(TrackingProfile, user_id)
    if p is None or not p.tracked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are not set up for field tracking (office admin: Settings > Field tracking)",
        )
    if consent_of(db, user_id) is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Give your consent first (My day > consent): nothing is recorded without it",
        )
    return p


# --- the day -------------------------------------------------------------------------------------


def open_day(db: Session, user_id) -> FieldDay | None:
    return db.scalar(
        select(FieldDay)
        .where(FieldDay.user_id == user_id, FieldDay.ended_at.is_(None))
        .order_by(FieldDay.started_at.desc())
        .limit(1)
    )


def _home_m(p: TrackingProfile, lat, lng) -> float | None:
    if p.home_status != "approved" or p.home_lat is None or lat is None:
        return None
    return round(geo.metres(p.home_lat, p.home_lng, lat, lng), 1)


def start_day(db: Session, user_id, lat: float, lng: float, accuracy: float | None) -> FieldDay:
    p = require_tracking(db, user_id)
    at = now()
    auto_end(db, at)  # yesterday's day left open ends first
    if open_day(db, user_id) is not None:
        raise conflict("Your day is already started")
    if db.scalar(
        select(FieldDay.id).where(FieldDay.user_id == user_id, FieldDay.on_date == ist_date(at))
    ):
        raise conflict("Today's day has already ended")
    day = FieldDay(
        user_id=user_id,
        on_date=ist_date(at),
        started_at=at,
        start_lat=lat,
        start_lng=lng,
        start_accuracy_m=accuracy,
        start_home_m=_home_m(p, lat, lng),
    )
    db.add(day)
    db.flush()
    refresh_flags(db, day)
    return day


def end_day(
    db: Session, user_id, lat, lng, accuracy, auto: bool = False, at: datetime | None = None
) -> FieldDay:
    day = open_day(db, user_id)
    if day is None:
        raise conflict("Your day is not started")
    p = profile(db, user_id)
    at = at or now()
    for s in day.stops:  # a stop still open closes with the day
        if s.out_at is None:
            s.out_at, s.out_reason = at, "checked out by the end of the day"
            _staff_out(db, day, s)
    day.ended_at, day.auto_ended = at, auto
    day.end_lat, day.end_lng, day.end_accuracy_m = lat, lng, accuracy
    day.end_home_m = _home_m(p, lat, lng)
    db.flush()
    compute_km(db, day)
    return day


def auto_end_moment(db: Session, day: FieldDay) -> datetime:
    t = settings(db).auto_end_at
    return datetime.combine(day.on_date, t, tzinfo=IST).astimezone(UTC)


def auto_end(db: Session, at: datetime | None = None) -> int:
    """Open days past the set time (default 21:00 IST) end on their own, at that time."""
    at = at or now()
    n = 0
    for day in db.scalars(select(FieldDay).where(FieldDay.ended_at.is_(None))):
        moment = auto_end_moment(db, day)
        if at >= moment:
            end_day(db, day.user_id, None, None, None, auto=True, at=max(moment, day.started_at))
            n += 1
    return n


def day_for(db: Session, user_id, at: datetime) -> FieldDay | None:
    """The day a point taken at `at` belongs to: started before it and not ended before it."""
    return db.scalar(
        select(FieldDay).where(
            FieldDay.user_id == user_id, FieldDay.started_at <= at,
            (FieldDay.ended_at.is_(None)) | (FieldDay.ended_at >= at),
        ).order_by(FieldDay.started_at.desc()).limit(1)
    )  # fmt: skip


def add_points(db: Session, user_id, points: list[dict], source: str, batch: str | None) -> dict:
    """A batch of points (queued offline and sent later, in any order). Only points inside a day
    (Start day to End day) are stored; a point already stored (the same time) is not stored again."""
    if (
        db.get(TrackingProfile, user_id) is None
        or not db.get(TrackingProfile, user_id).tracked
        or consent_of(db, user_id) is None
    ):
        return {
            "stored": 0,
            "duplicates": 0,
            "rejected": len(points),
            "reason": "no consent or not tracked: nothing is stored",
        }
    stored = dup = rejected = 0
    touched: set[int] = set()
    at_now = now()
    for pt in sorted(points, key=lambda x: x["at"]):
        at = pt["at"]
        day = day_for(db, user_id, at) if at <= at_now + timedelta(minutes=5) else None
        if day is None or (day.ended_at is None and auto_end_moment(db, day) < at):
            rejected += 1
            continue
        res = db.execute(
            insert(LocationPoint).values(user_id=user_id, day_id=day.id, at=at, lat=pt["lat"], lng=pt["lng"], accuracy_m=pt.get("accuracy"), source=source, batch=batch)
            .on_conflict_do_nothing(index_elements=["user_id", "at"])
            .returning(LocationPoint.id)
        )  # fmt: skip
        if res.first() is not None:
            stored += 1
            touched.add(day.id)
        else:
            dup += 1
    db.flush()
    for did in touched:
        d = db.get(FieldDay, did)
        compute_tracked(db, d)
        refresh_flags(db, d)
    return {"stored": stored, "duplicates": dup, "rejected": rejected}


# --- stops ---------------------------------------------------------------------------------------


def site_radius(db: Session, site) -> int:
    return site.radius_m or settings(db).site_radius_m


def _where(db: Session, site, lat: float, lng: float) -> tuple[float | None, bool]:
    if site is None or site.lat is None or site.lng is None:
        return None, False
    d = round(geo.metres(float(site.lat), float(site.lng), lat, lng), 1)
    return d, d > site_radius(db, site)


def _staff_in(db: Session, day: FieldDay, s: FieldStop) -> None:
    """A site check-in is the staff attendance payroll counts (worked days per site)."""
    from app.execution.models import StaffAttendance  # noqa: PLC0415

    if s.kind == "site" and s.site_id:
        db.add(
            StaffAttendance(
                user_id=day.user_id,
                site_id=s.site_id,
                on_date=day.on_date,
                check_in_at=s.in_at,
                lat=Decimal(str(round(s.in_lat, 6))),
                lng=Decimal(str(round(s.in_lng, 6))),
            )
        )


def _staff_out(db: Session, day: FieldDay, s: FieldStop) -> None:
    from app.execution.models import StaffAttendance  # noqa: PLC0415

    if s.kind == "site" and s.site_id:
        row = db.scalar(
            select(StaffAttendance).where(
                StaffAttendance.user_id == day.user_id,
                StaffAttendance.site_id == s.site_id,
                StaffAttendance.check_in_at == s.in_at,
            )
        )
        if row is not None:
            row.check_out_at = s.out_at


def check_in(
    db: Session,
    user_id,
    kind: str,
    site_id: int | None,
    note: str | None,
    lat: float,
    lng: float,
    accuracy: float | None,
    reason: str | None,
    selfie: str | None,
) -> FieldStop:
    from app.sites.models import Site  # noqa: PLC0415

    require_tracking(db, user_id)
    day = open_day(db, user_id)
    if day is None:
        raise conflict("Start your day first")
    if any(s.out_at is None for s in day.stops):
        raise conflict("Check out of the last place first")
    site = None
    if kind == "site":
        site = db.get(Site, site_id) if site_id else None
        if site is None:
            raise unprocessable("Choose the site")
        if not selfie:
            raise unprocessable("Take the selfie (front camera) to check in at a site")
    elif kind == "other" and not (note or "").strip():
        raise unprocessable("Say where (a note) for another stop")
    distance, outside = _where(db, site, lat, lng)
    if outside and not (reason or "").strip():
        raise unprocessable(
            f"You are {round(distance)} m from {site.name}'s pin (the site is within {site_radius(db, site)} m): give the reason"
        )
    s = FieldStop(day_id=day.id, seq=len(day.stops) + 1, kind=kind, site_id=site.id if site else None, note=(note or "").strip() or None,
                  in_at=now(), in_lat=lat, in_lng=lng, in_accuracy_m=accuracy, in_distance_m=distance, in_outside=outside,
                  in_reason=(reason or "").strip() or None, in_selfie=selfie)  # fmt: skip
    day.stops.append(s)
    db.flush()
    _staff_in(db, day, s)
    refresh_flags(db, day)
    return s


def check_out(
    db: Session,
    user_id,
    lat: float,
    lng: float,
    accuracy: float | None,
    reason: str | None,
    selfie: str | None,
) -> FieldStop:
    from app.sites.models import Site  # noqa: PLC0415

    day = open_day(db, user_id)
    s = next((x for x in (day.stops if day else []) if x.out_at is None), None)
    if s is None:
        raise conflict("You are not checked in anywhere")
    site = db.get(Site, s.site_id) if s.site_id else None
    distance, outside = _where(db, site, lat, lng)
    if outside and not (reason or "").strip():
        raise unprocessable(f"You are {round(distance)} m from {site.name}'s pin: give the reason")
    s.out_at, s.out_lat, s.out_lng, s.out_accuracy_m = now(), lat, lng, accuracy
    s.out_distance_m, s.out_outside, s.out_reason, s.out_selfie = (
        distance,
        outside,
        (reason or "").strip() or None,
        selfie,
    )
    _staff_out(db, day, s)
    db.flush()
    refresh_flags(db, day)
    return s


def minutes_on(s: FieldStop) -> int | None:
    return round((s.out_at - s.in_at).total_seconds() / 60) if s.out_at else None


# --- km and flags --------------------------------------------------------------------------------


def _points(db: Session, day: FieldDay) -> list[geo.Point]:
    return [
        geo.Point(at=p.at, lat=p.lat, lng=p.lng, accuracy_m=p.accuracy_m)
        for p in db.scalars(
            select(LocationPoint).where(LocationPoint.day_id == day.id).order_by(LocationPoint.at)
        )
    ]


def compute_tracked(db: Session, day: FieldDay) -> geo.Tracked | None:
    if day.points_deleted_at is not None:
        return None  # the raw points are gone (retention): the km stays as it was
    s = settings(db)
    pts = _points(db, day)
    t = geo.tracked_km(pts, s.accuracy_max_m, s.jitter_m, s.max_speed_kmh)
    day.tracked_km, day.points_total, day.points_good = km3(t.km), len(pts), t.used
    return t


def route_points(db: Session, day: FieldDay) -> list[tuple[str, float, float]]:
    """home (or where the day started) -> each stop -> home (or where the day ended)."""
    p = profile(db, day.user_id)
    home = (
        (p.home_lat, p.home_lng) if p.home_status == "approved" and p.home_lat is not None else None
    )
    start = home or ((day.start_lat, day.start_lng) if day.start_lat is not None else None)
    end = home or ((day.end_lat, day.end_lng) if day.end_lat is not None else None)
    out = []
    if start:
        out.append(("Home" if home else "Start", *start))
    for s in day.stops:
        out.append((stop_name(db, s), s.in_lat, s.in_lng))
    if end and day.ended_at is not None:
        out.append(("Home" if home else "End", *end))
    return out


def stop_name(db: Session, s: FieldStop) -> str:
    from app.sites.models import Site  # noqa: PLC0415

    if s.kind == "site" and s.site_id:
        site = db.get(Site, s.site_id)
        return site.name if site else "Site"
    return f"{STOP_LABEL[s.kind]}: {s.note}" if s.note else STOP_LABEL[s.kind]


def compute_km(db: Session, day: FieldDay) -> FieldDay:
    """Road km stop to stop (OSRM; the straight line x 1.3 marked estimated when it is down) and
    tracked km from the points, then the flags."""
    s = settings(db)
    pts = route_points(db, day)
    legs = geo.road_legs([(a, b) for _n, a, b in pts], float(s.road_factor))
    day.legs = [
        {"from": pts[i][0], "to": pts[i + 1][0], "km": round(leg.km, 3), "minutes": round(leg.minutes, 1) if leg.minutes is not None else None, "estimated": leg.estimated}
        for i, leg in enumerate(legs)
    ]  # fmt: skip
    day.route_km = km3(sum(leg.km for leg in legs)) if legs else km3(0)
    day.route_estimated = any(leg.estimated for leg in legs)
    compute_tracked(db, day)
    refresh_flags(db, day)
    return day


def refresh_flags(db: Session, day: FieldDay) -> list[dict]:
    """The day's flags for the manager (never an automatic rejection)."""
    s = settings(db)
    out: list[dict] = []
    for st in day.stops:
        if st.in_outside:
            out.append(
                {
                    "code": "outside_radius",
                    "text": f"Checked in {round(st.in_distance_m)} m from {stop_name(db, st)}'s pin: {st.in_reason}",
                    "stop": st.seq,
                }
            )
        if st.out_outside:
            out.append(
                {
                    "code": "outside_radius",
                    "text": f"Checked out {round(st.out_distance_m)} m from {stop_name(db, st)}'s pin: {st.out_reason}",
                    "stop": st.seq,
                }
            )
        if st.kind == "site" and st.in_distance_m is None:
            out.append(
                {
                    "code": "site_no_pin",
                    "text": f"{stop_name(db, st)} has no pinned location: the check-in could not be checked",
                    "stop": st.seq,
                }
            )
    if day.start_home_m is not None and day.start_home_m > s.home_flag_m:
        out.append(
            {"code": "start_far", "text": f"Day started {_dist(day.start_home_m)} from home"}
        )
    if day.end_home_m is not None and day.end_home_m > s.home_flag_m:
        out.append({"code": "end_far", "text": f"Day ended {_dist(day.end_home_m)} from home"})
    if day.auto_ended:
        out.append({"code": "auto_ended", "text": "End day not pressed: ended at the set time"})
    if day.points_deleted_at is None:
        pts = _points(db, day)
        t = geo.tracked_km(pts, s.accuracy_max_m, s.jitter_m, s.max_speed_kmh)
        for j in t.jumps:
            out.append(
                {
                    "code": "jump",
                    "text": f"Impossible jump: {j['km']} km at {j['kmh'] or '∞'} km/h (left out of tracked km)",
                }
            )
        if pts and t.poor == len(pts):
            out.append(
                {
                    "code": "poor_accuracy",
                    "text": f"Location accuracy poor all day (worse than {s.accuracy_max_m} m): no tracked km",
                }
            )
        times = [day.started_at, *[p.at for p in pts], *([day.ended_at] if day.ended_at else [])]
        times.sort()
        for a, b in zip(times, times[1:], strict=False):
            if (b - a).total_seconds() > s.gap_minutes * 60:
                out.append(
                    {
                        "code": "gap",
                        "text": f"No location for {round((b - a).total_seconds() / 60)} min ({a.astimezone(IST):%H:%M} to {b.astimezone(IST):%H:%M}) while the day was open",
                    }
                )
    if day.route_estimated:
        out.append(
            {
                "code": "estimated",
                "text": "Road km estimated (straight line x 1.3): the map server was down; recalculated when it is back",
            }
        )
    day.flags = out
    return out


def _dist(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{round(m)} m"


def recalc_estimated(db: Session) -> int:
    """Days whose road km were estimated (OSRM down): worked again; still down: unchanged."""
    n = 0
    for day in db.scalars(
        select(FieldDay).where(FieldDay.route_estimated.is_(True), FieldDay.ended_at.is_not(None))
    ):
        compute_km(db, day)
        n += not day.route_estimated
    return n


def day_km(day: FieldDay) -> Decimal:
    return Decimal(day.tracked_km if day.km_basis == "tracked" else day.route_km or 0)


def choose_basis(db: Session, day: FieldDay, basis: str, reason: str | None, by) -> None:
    if basis == "tracked" and not (reason or "").strip():
        raise unprocessable(
            "Give the reason for using tracked km (for example a detour the stops don't show)"
        )
    day.km_basis, day.km_basis_reason, day.km_basis_by = basis, (reason or "").strip() or None, by


# --- who sees whom -------------------------------------------------------------------------------


def team_of(db: Session, manager_id) -> list[uuid.UUID]:
    return list(
        db.scalars(select(TrackingProfile.user_id).where(TrackingProfile.manager_id == manager_id))
    )


def can_see(db: Session, principal, user_id, via_claim: bool = False) -> bool:
    """The person, their manager, the director and office_admin (field.team); accounts only when
    the route is opened from a claim. Clients and vendors never (they hold none of this)."""
    if principal.user.id == user_id:
        return True
    if (
        "field.track" not in principal.permissions
        and "field.team" not in principal.permissions
        and "field.claims" not in principal.permissions
    ):
        return False
    if principal.permissions.get("field.team") == "all":
        return True
    p = db.get(TrackingProfile, user_id)
    if p is not None and p.manager_id == principal.user.id:
        return True
    return via_claim and "field.claims" in principal.permissions


# --- the travel claim ----------------------------------------------------------------------------


def month_range(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def rate_on(db: Session, user_id, on: date) -> TravelRate | None:
    return db.scalar(
        select(TravelRate).where(TravelRate.user_id == user_id, TravelRate.valid_from <= on, (TravelRate.valid_to.is_(None)) | (TravelRate.valid_to >= on))
        .order_by(TravelRate.valid_from.desc()).limit(1)
    )  # fmt: skip


def eligible(db: Session, user: User) -> bool:
    """Office employees with travel reimbursement on (labour are not users: they never claim)."""
    p = db.get(TrackingProfile, user.id)
    return bool(user.is_active and p and p.reimbursable and p.tracked)


def build_claim(db: Session, user_id, month: str, ready: bool = False) -> TravelClaim | None:
    """The month's claim from the ended days: km (road, or tracked where the manager chose) x the
    rate valid on each date. A claim already with the manager or approved is left as it is; days
    the manager edited keep the edit."""
    user = db.get(User, user_id)
    if user is None or not eligible(db, user):
        return None
    c = db.scalar(
        select(TravelClaim).where(TravelClaim.user_id == user_id, TravelClaim.month == month)
    )
    if c is None:
        c = TravelClaim(user_id=user_id, month=month, status="draft")
        db.add(c)
        db.flush()
    if c.status not in ("draft", "ready"):
        return c
    start, end = month_range(month)
    rows = {d.on_date: d for d in c.days}  # updated in place (a day the manager edited is kept)
    seen = set()
    for day in db.scalars(
        select(FieldDay)
        .where(
            FieldDay.user_id == user_id,
            FieldDay.on_date >= start,
            FieldDay.on_date <= end,
            FieldDay.ended_at.is_not(None),
        )
        .order_by(FieldDay.on_date)
    ):
        seen.add(day.on_date)
        row = rows.get(day.on_date)
        if row is not None and row.edited_by:
            continue
        rate = rate_on(db, user_id, day.on_date)
        km = day_km(day)
        flags = list(day.flags or [])
        if rate is None:
            flags.append(
                {
                    "code": "no_rate",
                    "text": "No rate per km on this date (Settings > Field tracking)",
                }
            )
        r = Decimal(rate.rate_per_km) if rate else ZERO
        values = {
            "day_id": day.id, "stops": " → ".join(n for n, _a, _b in route_points(db, day)), "km_basis": day.km_basis,
            "km": km3(km), "estimated": day.route_estimated and day.km_basis == "route", "rate_per_km": r,
            "amount": money(km * r), "flags": flags,
        }  # fmt: skip
        if row is None:
            c.days.append(TravelClaimDay(on_date=day.on_date, **values))
        else:
            for k, v in values.items():
                setattr(row, k, v)
    for on, row in rows.items():
        if on not in seen and not row.edited_by:
            c.days.remove(row)
    totals(c)
    if ready and c.status == "draft":
        c.status = "ready"
    db.flush()
    return c


def totals(c: TravelClaim) -> None:
    c.km = km3(sum((Decimal(d.km) for d in c.days), ZERO))
    c.days_amount = money(sum((Decimal(d.amount) for d in c.days), ZERO))
    c.extras_amount = money(sum((Decimal(x.amount) for x in c.extras), ZERO))
    c.total = money(Decimal(c.days_amount) + Decimal(c.extras_amount))
    c.flagged_days = sum(1 for d in c.days if d.flags)


def edit_claim_day(
    db: Session,
    c: TravelClaim,
    d: TravelClaimDay,
    km: Decimal | None,
    basis: str | None,
    reason: str | None,
    by,
) -> None:
    """The manager changes a day's km (or switches it to tracked km), always with a reason."""
    if c.status not in ("draft", "ready"):
        raise conflict("The claim is already approved by the manager")
    if not (reason or "").strip():
        raise unprocessable("Give the reason for the change")
    day = db.get(FieldDay, d.day_id) if d.day_id else None
    before = Decimal(d.km)
    if basis:
        if day is None:
            raise unprocessable("The day's record is gone: type the km instead")
        choose_basis(db, day, basis, reason, by)
        d.km_basis, km = basis, day_km(day) if km is None else km
    if km is not None:
        d.km = km3(km)
    d.edited_km_from, d.edit_reason, d.edited_by = before, reason.strip(), by
    d.amount = money(Decimal(d.km) * Decimal(d.rate_per_km))
    totals(c)


def payroll_reimbursement(db: Session, user_id, month: str) -> Decimal:
    """Approved claims paid with this payroll month (outside the salary's gross)."""
    return money(
        sum(
            db.scalars(
                select(TravelClaim.total).where(
                    TravelClaim.user_id == user_id,
                    TravelClaim.status == "approved",
                    TravelClaim.payroll_month == month,
                )
            ),
            ZERO,
        )
    )


# --- labour gangs (the supervisor checks them in) -------------------------------------------------


def gang_hours(
    db: Session, contractor_id: int, start: date, end: date
) -> dict[tuple[int, int | None, date], Decimal]:
    """Hours per (site, worker, date) from the gang check-ins (worker None: a headcount without
    names, the hours being the whole headcount's)."""
    out: dict[tuple[int, int | None, date], Decimal] = defaultdict(lambda: ZERO)
    for v in db.scalars(
        select(GangVisit).where(
            GangVisit.contractor_id == contractor_id,
            GangVisit.on_date >= start,
            GangVisit.on_date <= end,
            GangVisit.out_at.is_not(None),
        )
    ):
        h = Decimal(str(round((v.out_at - v.in_at).total_seconds() / 3600, 2)))
        if v.workers:
            for w in v.workers:
                out[(v.site_id, w.labour_id, v.on_date)] += h
        else:
            out[(v.site_id, None, v.on_date)] += h * v.headcount
    return out


def gang_check_in(
    db: Session,
    user_id,
    site,
    contractor_id: int,
    labour_ids: list[int],
    headcount: int | None,
    lat: float,
    lng: float,
    accuracy: float | None,
    reason: str | None,
    photo: str | None,
) -> GangVisit:
    from app.execution.models import Labour  # noqa: PLC0415

    if not photo:
        raise unprocessable("Take one photo of the gang")
    workers = (
        list(db.scalars(select(Labour).where(Labour.id.in_(labour_ids)))) if labour_ids else []
    )
    if any(w.subcontractor_id != contractor_id for w in workers):
        raise unprocessable("Every name must be of this contractor's gang")
    count = len(workers) or (headcount or 0)
    if count <= 0:
        raise unprocessable("Pick the names or give the headcount")
    distance, outside = _where(db, site, lat, lng)
    if outside and not (reason or "").strip():
        raise unprocessable(f"You are {round(distance)} m from {site.name}'s pin: give the reason")
    open_ = db.scalar(
        select(GangVisit).where(
            GangVisit.contractor_id == contractor_id, GangVisit.out_at.is_(None)
        )
    )
    if open_ is not None:
        raise conflict("This gang is checked in at a site: check it out there first")
    at = now()
    v = GangVisit(site_id=site.id, contractor_id=contractor_id, supervisor_id=user_id, on_date=ist_date(at), headcount=count, in_at=at,
                  in_lat=lat, in_lng=lng, in_accuracy_m=accuracy, in_distance_m=distance, in_outside=outside,
                  in_reason=(reason or "").strip() or None, in_photo=photo, created_by=user_id)  # fmt: skip
    v.workers = [GangVisitWorker(labour_id=w.id) for w in workers]
    db.add(v)
    db.flush()
    return v


def gang_check_out(
    db: Session,
    v: GangVisit,
    site,
    lat: float,
    lng: float,
    accuracy: float | None,
    reason: str | None,
    photo: str | None,
) -> GangVisit:
    if v.out_at is not None:
        raise conflict("The gang is already checked out")
    distance, outside = _where(db, site, lat, lng)
    if outside and not (reason or "").strip():
        raise unprocessable(f"You are {round(distance)} m from {site.name}'s pin: give the reason")
    v.out_at, v.out_lat, v.out_lng, v.out_accuracy_m = now(), lat, lng, accuracy
    v.out_distance_m, v.out_outside, v.out_reason, v.out_photo = (
        distance,
        outside,
        (reason or "").strip() or None,
        photo,
    )
    db.flush()
    return v


# --- retention -----------------------------------------------------------------------------------


def retention(db: Session, at: datetime | None = None) -> dict:
    """Raw points older than the set days (90) are deleted; the day keeps its km and stops. Day
    summaries and approved claims older than the set years (8) are deleted."""
    at = at or now()
    s = settings(db)
    cut = at - timedelta(days=s.raw_days)
    days = list(
        db.scalars(
            select(FieldDay.id).where(
                FieldDay.on_date < ist_date(cut),
                FieldDay.points_deleted_at.is_(None),
                FieldDay.ended_at.is_not(None),
            )
        )
    )
    gone = db.execute(delete(LocationPoint).where(LocationPoint.at < cut)).rowcount or 0
    for d in db.scalars(select(FieldDay).where(FieldDay.id.in_(days))):
        d.points_deleted_at = at
    old = date(ist_date(at).year - s.summary_years, ist_date(at).month, 1)
    old_claims = (
        db.execute(delete(TravelClaim).where(TravelClaim.month < f"{old:%Y-%m}")).rowcount or 0
    )
    old_days = db.execute(delete(FieldDay).where(FieldDay.on_date < old)).rowcount or 0
    db.flush()
    return {
        "points": gone,
        "days_cleared": len(days),
        "old_days": old_days,
        "old_claims": old_claims,
    }


def latest_points(db: Session, user_ids: list) -> dict:
    """Each person's latest point today."""
    if not user_ids:
        return {}
    sub = (
        select(LocationPoint.user_id, func.max(LocationPoint.at).label("at"))
        .where(LocationPoint.user_id.in_(user_ids), LocationPoint.at >= now() - timedelta(hours=20))
        .group_by(LocationPoint.user_id)
        .subquery()
    )
    rows = db.execute(
        select(LocationPoint).join(
            sub, (sub.c.user_id == LocationPoint.user_id) & (sub.c.at == LocationPoint.at)
        )
    ).scalars()
    return {p.user_id: p for p in rows}
