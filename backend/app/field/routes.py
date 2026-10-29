# ruff: noqa: E501  (the rows read better unwrapped)
"""The field tracking API.

field.track (own): every staff user: their consent, their day, their map, their claim. A manager
sees their team (the people whose profile names them). field.team (all): director, office_admin.
field.admin: office_admin: who is tracked, eligible, the vehicle, the rate per km, the home.
field.claims: accounts: every claim, a route only when opened from a claim (logged);
field.claims_approve: accounts approve the month. field.gang (assigned): the supervisor checks in
a labour gang on their sites. site.location: planning, the site engineer (their sites): the pin.
Clients, vendors and the site receiver hold none of these. Every view of someone else's route is
logged."""

import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.db import DbSession
from app.execution.common import names, record, save_upload, send_file
from app.field import geo, hooks, service
from app.field.models import (
    STOP_KINDS,
    VEHICLES,
    FieldDay,
    FieldStop,
    GangVisit,
    LocationPoint,
    TrackingProfile,
    TravelClaim,
    TravelClaimDay,
    TravelClaimExtra,
    TravelRate,
)
from app.models import User
from app.sites import service as site_service
from app.timefmt import IST

router = APIRouter(prefix="/api/field", tags=["field tracking"])
Track = Annotated[str, Depends(require_permission("field.track"))]
Admin = Annotated[str, Depends(require_permission("field.admin"))]
Gang = Annotated[str, Depends(require_permission("field.gang"))]
Pin = Annotated[str, Depends(require_permission("site.location"))]


def _uid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found") from exc


def _see(
    db, principal, user_id, request: Request, what: str, ident, via_claim: bool = False
) -> None:
    """Allowed to see this person's location, and the view logged when it is someone else's."""
    if not service.can_see(db, principal, user_id, via_claim):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the person, their manager, the director and the office admin see this route",
        )
    if principal.user.id != user_id:
        record(
            db,
            request,
            principal,
            "field.route_view",
            what,
            ident,
            after={"person": str(user_id), "via_claim": via_claim},
        )
        db.commit()


def _site_name(db, site_id):
    from app.sites.models import Site  # noqa: PLC0415

    s = db.get(Site, site_id) if site_id else None
    return s.name if s else None


def stop_out(db, s: FieldStop, with_place: bool = True) -> dict:
    return {
        "id": s.id, "seq": s.seq, "kind": s.kind, "site_id": s.site_id, "name": service.stop_name(db, s), "note": s.note,
        "in_at": s.in_at, "out_at": s.out_at, "minutes": service.minutes_on(s),
        "in_outside": s.in_outside, "in_distance_m": s.in_distance_m, "in_reason": s.in_reason,
        "out_outside": s.out_outside, "out_distance_m": s.out_distance_m, "out_reason": s.out_reason,
        "has_selfie": bool(s.in_selfie), "has_out_selfie": bool(s.out_selfie),
        **({"in_lat": s.in_lat, "in_lng": s.in_lng, "in_accuracy_m": s.in_accuracy_m, "out_lat": s.out_lat, "out_lng": s.out_lng} if with_place else {}),
    }  # fmt: skip


def day_out(db, d: FieldDay, points: bool = False) -> dict:
    user = db.get(User, d.user_id)
    out = {
        "id": d.id, "user_id": str(d.user_id), "person": user.full_name if user else None, "on_date": d.on_date,
        "started_at": d.started_at, "ended_at": d.ended_at, "auto_ended": d.auto_ended,
        "start": [d.start_lat, d.start_lng] if d.start_lat is not None else None, "start_home_m": d.start_home_m,
        "end": [d.end_lat, d.end_lng] if d.end_lat is not None else None, "end_home_m": d.end_home_m,
        "legs": d.legs, "route_km": d.route_km, "route_estimated": d.route_estimated, "tracked_km": d.tracked_km,
        "km_basis": d.km_basis, "km_basis_reason": d.km_basis_reason, "km": service.day_km(d),
        "flags": d.flags, "points_total": d.points_total, "points_good": d.points_good,
        "points_deleted": d.points_deleted_at is not None,
        "stops": [stop_out(db, s) for s in d.stops],
    }  # fmt: skip
    if points:
        s = service.settings(db)
        out["points"] = [
            [
                p.lat,
                p.lng,
                p.at,
                p.accuracy_m,
                p.accuracy_m is None or p.accuracy_m <= s.accuracy_max_m,
            ]
            for p in db.scalars(
                select(LocationPoint).where(LocationPoint.day_id == d.id).order_by(LocationPoint.at)
            )
        ]
        p = db.get(TrackingProfile, d.user_id)
        out["home"] = [p.home_lat, p.home_lng] if p and p.home_status == "approved" else None
        # the road route between the stops, drawn on the map (our own OSRM)
        pts = service.route_points(db, d)
        legs = (
            geo.road_legs([(a, b) for _n, a, b in pts], float(s.road_factor), geometry=True)
            if len(pts) > 1
            else []
        )
        out["road"] = legs[0].geometry if legs and legs[0].geometry else None
    return out


def map_settings(db) -> dict:
    s = service.settings(db)
    return {
        "tile_url": s.tile_url, "tile_attribution": s.tile_attribution, "point_every_s": s.point_every_s,
        "point_move_m": s.point_move_m, "accuracy_max_m": s.accuracy_max_m, "site_radius_m": s.site_radius_m,
        "auto_end_at": s.auto_end_at.strftime("%H:%M"), "home_flag_m": s.home_flag_m,
    }  # fmt: skip


def _my_sites(db, principal) -> list[dict]:
    """The sites the person can check in at: their sites (all sites for those who see all)."""
    from app.sites.models import Site, SiteMember  # noqa: PLC0415

    q = select(Site).where(Site.status.in_(("planned", "active", "on_hold")))
    scope = principal.permissions.get("site.view")
    if scope:
        q = q.where(site_service.scope_condition(scope, principal))
    else:  # no site list: the sites they are a member of
        q = q.where(
            Site.id.in_(select(SiteMember.site_id).where(SiteMember.user_id == principal.user.id))
        )
    return [
        {"id": s.id, "code": s.code, "name": s.name, "lat": float(s.lat) if s.lat is not None else None, "lng": float(s.lng) if s.lng is not None else None,
         "radius_m": service.site_radius(db, s), "maps_link": geo.maps_link(float(s.lat), float(s.lng)) if s.lat is not None else None}
        for s in db.scalars(q.order_by(Site.name).limit(300))
    ]  # fmt: skip


@router.get("/map-settings")
def map_settings_(
    db: DbSession, _: Annotated[str, Depends(require_any_permission("field.track", "site.view"))]
) -> dict:
    """The map tiles (OpenStreetMap by default, a provider at go-live) and the day's settings."""
    return map_settings(db)


# --- me ------------------------------------------------------------------------------------------


@router.get("/me")
def me(db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    uid = principal.user.id
    service.auto_end(db)
    p = db.get(TrackingProfile, uid)
    day = service.open_day(db, uid) or db.scalar(
        select(FieldDay).where(
            FieldDay.user_id == uid, FieldDay.on_date == service.ist_date(service.now())
        )
    )
    out = {
        "consent": service.consent_out(db, uid),
        "profile": {
            "tracked": bool(p and p.tracked), "reimbursable": bool(p and p.reimbursable), "vehicle": p.vehicle if p else None,
            "home_status": p.home_status if p else "none", "home": [p.home_lat, p.home_lng] if p and p.home_lat is not None else None,
            "pending": [p.pending_lat, p.pending_lng] if p and p.pending_lat is not None else None,
            "manager": db.get(User, p.manager_id).full_name if p and p.manager_id else None,
        },
        "settings": map_settings(db),
        "day": day_out(db, day) if day else None,
        "sites": _my_sites(db, principal),
        "now": service.now(),
    }  # fmt: skip
    db.commit()
    return jsonable_encoder(out)


@router.post("/consent")
def consent(request: Request, db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    c = service.give_consent(db, principal.user.id)
    record(
        db,
        request,
        principal,
        "field.consent",
        "user",
        principal.user.id,
        after={"version": c.version},
    )
    db.commit()
    return jsonable_encoder(service.consent_out(db, principal.user.id))


@router.delete("/consent")
def withdraw(request: Request, db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    service.withdraw_consent(db, principal.user.id)
    record(db, request, principal, "field.consent_withdrawn", "user", principal.user.id)
    db.commit()
    return jsonable_encoder(service.consent_out(db, principal.user.id))


class Where(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0, le=100000)


@router.post("/day/start")
def start(
    body: Where, request: Request, db: DbSession, principal: CurrentPrincipal, _: Track
) -> dict:
    d = service.start_day(db, principal.user.id, body.lat, body.lng, body.accuracy)
    record(db, request, principal, "field.day_start", "field_day", d.id)
    db.commit()
    return jsonable_encoder(day_out(db, d))


@router.post("/day/end")
def end(
    body: Where, request: Request, db: DbSession, principal: CurrentPrincipal, _: Track
) -> dict:
    d = service.end_day(db, principal.user.id, body.lat, body.lng, body.accuracy)
    record(
        db,
        request,
        principal,
        "field.day_end",
        "field_day",
        d.id,
        after={"route_km": str(d.route_km), "tracked_km": str(d.tracked_km)},
    )
    db.commit()
    return jsonable_encoder(day_out(db, d))


class PointIn(BaseModel):
    at: datetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0, le=100000)


class PointsIn(BaseModel):
    source: Literal["web", "android"] = "web"
    batch: str | None = Field(None, max_length=64)
    points: list[PointIn] = Field(max_length=1000)


@router.post("/points")
def points(body: PointsIn, db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    """A batch of points from the browser (or the Android app: the same endpoint, source
    "android"). Points outside Start day to End day, or without consent, are not stored."""
    for p in body.points:
        if p.at.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Point times need their time zone"
            )
    out = service.add_points(
        db, principal.user.id, [p.model_dump() for p in body.points], body.source, body.batch
    )
    db.commit()
    return out


@router.post("/stops/in")
async def stop_in(
    request: Request, db: DbSession, principal: CurrentPrincipal, _: Track,
    kind: Annotated[str, Form()], lat: Annotated[float, Form()], lng: Annotated[float, Form()],
    accuracy: Annotated[float | None, Form()] = None, site_id: Annotated[int | None, Form()] = None,
    note: Annotated[str | None, Form(max_length=300)] = None, reason: Annotated[str | None, Form(max_length=1000)] = None,
    selfie: Annotated[UploadFile | None, File()] = None,
) -> dict:  # fmt: skip
    if kind not in STOP_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown kind of stop")
    service.require_tracking(db, principal.user.id)
    rel = (await save_upload(selfie, f"field/{principal.user.id}"))[0] if selfie else None
    s = service.check_in(
        db, principal.user.id, kind, site_id, note, lat, lng, accuracy, reason, rel
    )
    record(
        db,
        request,
        principal,
        "field.check_in",
        "field_stop",
        s.id,
        after={"kind": kind, "site_id": site_id, "outside": s.in_outside},
    )
    db.commit()
    return jsonable_encoder(stop_out(db, s))


@router.post("/stops/out")
async def stop_leave(
    request: Request, db: DbSession, principal: CurrentPrincipal, _: Track,
    lat: Annotated[float, Form()], lng: Annotated[float, Form()], accuracy: Annotated[float | None, Form()] = None,
    reason: Annotated[str | None, Form(max_length=1000)] = None, selfie: Annotated[UploadFile | None, File()] = None,
) -> dict:  # fmt: skip
    rel = (await save_upload(selfie, f"field/{principal.user.id}"))[0] if selfie else None
    s = service.check_out(db, principal.user.id, lat, lng, accuracy, reason, rel)
    record(
        db,
        request,
        principal,
        "field.check_out",
        "field_stop",
        s.id,
        after={"minutes": service.minutes_on(s), "outside": s.out_outside},
    )
    db.commit()
    return jsonable_encoder(stop_out(db, s))


class HomeIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.put("/home")
def ask_home(
    body: HomeIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Track
) -> dict:
    """The person picks their home on the map; office_admin approves it (a change: again)."""
    p = service.profile(db, principal.user.id)
    p.pending_lat, p.pending_lng, p.home_requested_at = body.lat, body.lng, service.now()
    p.home_status = "pending" if p.home_lat is None or p.home_status != "approved" else "approved"
    record(db, request, principal, "field.home_asked", "user", principal.user.id)
    db.commit()
    return {"home_status": p.home_status, "pending": [p.pending_lat, p.pending_lng]}


# --- days and maps -------------------------------------------------------------------------------


@router.get("/days")
def days(
    db: DbSession,
    principal: CurrentPrincipal,
    _: Track,
    user_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    uid = _uid(user_id) if user_id else principal.user.id
    if not service.can_see(db, principal, uid):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the person, their manager, the director and the office admin see these days",
        )
    end = end or service.ist_date(service.now())
    start = start or end - timedelta(days=31)
    rows = db.scalars(
        select(FieldDay)
        .where(FieldDay.user_id == uid, FieldDay.on_date >= start, FieldDay.on_date <= end)
        .order_by(FieldDay.on_date.desc())
    )
    return jsonable_encoder([day_out(db, d) for d in rows])


@router.get("/days/{day_id}")
def day(
    day_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    claim: int | None = None,
) -> dict:
    """A person's day on the map: the tracked points, the stops (numbered, times, selfies), the
    road route between them, km per leg and the flags. Accounts open it from a claim (logged)."""
    d = db.get(FieldDay, day_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Day not found")
    via_claim = False
    if claim is not None:
        c = db.get(TravelClaim, claim)
        via_claim = bool(c and c.user_id == d.user_id and any(x.day_id == d.id for x in c.days))
    _see(db, principal, d.user_id, request, "field_day", d.id, via_claim)
    out = day_out(db, d, points=True)
    out["settings"] = map_settings(db)
    out["can_choose_basis"] = (
        principal.user.id != d.user_id
        and service.can_see(db, principal, d.user_id)
        and "field.track" in principal.permissions
    )
    out["basis_locked"] = service.basis_locked(db, d) if out["can_choose_basis"] else None
    return jsonable_encoder(out)


class BasisIn(BaseModel):
    basis: Literal["route", "tracked"]
    reason: str | None = Field(None, max_length=1000)


@router.put("/days/{day_id}/basis")
def basis(
    day_id: int, body: BasisIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """The manager (or the director) uses tracked km for a day instead of road km, with a reason."""
    d = db.get(FieldDay, day_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Day not found")
    if principal.user.id == d.user_id or not service.can_see(db, principal, d.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The manager chooses the km of a day")
    if locked := service.basis_locked(db, d):
        raise service.conflict(locked)
    service.choose_basis(db, d, body.basis, body.reason, principal.user.id)
    record(db, request, principal, "field.km_basis", "field_day", d.id, after=body.model_dump())
    db.commit()
    return jsonable_encoder(day_out(db, d))


@router.get("/stops/{stop_id}/selfie")
def selfie(
    stop_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    which: Literal["in", "out"] = "in",
    claim: int | None = None,
):
    s = db.get(FieldStop, stop_id)
    d = db.get(FieldDay, s.day_id) if s else None
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    via = bool(claim and (c := db.get(TravelClaim, claim)) and c.user_id == d.user_id)
    if not service.can_see(db, principal, d.user_id, via):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not yours to see")
    return send_file(s.in_selfie if which == "in" else s.out_selfie)


@router.get("/team")
def team(db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    """Everyone the caller manages (all for the director and office_admin): the latest location
    today with its time, and who has not started the day."""
    if principal.permissions.get("field.team") == "all":
        ids = list(
            db.scalars(select(TrackingProfile.user_id).where(TrackingProfile.tracked.is_(True)))
        )
    else:
        ids = service.team_of(db, principal.user.id)
    if not ids:
        return {"people": [], "settings": map_settings(db)}
    today = service.ist_date(service.now())
    days_ = {
        d.user_id: d
        for d in db.scalars(
            select(FieldDay).where(FieldDay.user_id.in_(ids), FieldDay.on_date == today)
        )
    }
    latest = service.latest_points(db, ids)
    who = names(db, ids)
    people = []
    for uid in sorted(ids, key=lambda u: who.get(u) or ""):
        d, p = days_.get(uid), latest.get(uid)
        stop = next((s for s in reversed(d.stops) if s.out_at is None), None) if d else None
        people.append({
            "user_id": str(uid), "name": who.get(uid), "started": d is not None, "ended": bool(d and d.ended_at),
            "day_id": d.id if d else None, "last": [p.lat, p.lng] if p else ([d.start_lat, d.start_lng] if d and d.start_lat is not None else None),
            "last_at": p.at if p else (d.started_at if d else None), "at_stop": service.stop_name(db, stop) if stop else None,
            "flags": len(d.flags) if d else 0, "km": service.day_km(d) if d else None,
        })  # fmt: skip
    from app import audit  # noqa: PLC0415

    audit.record(
        db,
        "field.team_view",
        "user",
        principal.user.id,
        user_id=principal.user.id,
        after={"people": len(people)},
    )
    db.commit()
    return jsonable_encoder({"people": people, "settings": map_settings(db), "today": today})


# --- guide to the site ---------------------------------------------------------------------------


class PlanIn(BaseModel):
    site_ids: list[int] = Field(max_length=25)
    keep_order: bool = False  # the user reordered: just the legs in this order
    # where the person is now, [lat, lng] (else home)
    start: list[float] | None = Field(None, min_length=2, max_length=2)


@router.post("/plan")
def plan(body: PlanIn, db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    """Today's route: the sites in the shortest road order from home through them (OSRM trip),
    or in the user's own order, with km and minutes per leg and the road on the map."""
    from app.sites.models import Site  # noqa: PLC0415

    allowed = {s["id"]: s for s in _my_sites(db, principal)}
    sites = [allowed[i] for i in body.site_ids if i in allowed and allowed[i]["lat"] is not None]
    p = db.get(TrackingProfile, principal.user.id)
    home = (
        tuple(body.start)
        if body.start
        else ((p.home_lat, p.home_lng) if p and p.home_status == "approved" else None)
    )
    if home is None and sites:
        home = (sites[0]["lat"], sites[0]["lng"])
    order = list(range(len(sites)))
    suggested = False
    if not body.keep_order and len(sites) > 1:
        o = geo.trip_order(home, [(s["lat"], s["lng"]) for s in sites])
        if o is not None:
            order, suggested = o, True
    sites = [sites[i] for i in order]
    s = service.settings(db)
    pts = [home, *[(x["lat"], x["lng"]) for x in sites], home] if home else []
    legs = geo.road_legs(pts, float(s.road_factor), geometry=True) if len(pts) > 1 else []
    names_ = [
        "Home" if p and p.home_status == "approved" and not body.start else "Start",
        *[x["name"] for x in sites],
        "Home",
    ]
    missing = [
        db.get(Site, i).name for i in body.site_ids if i in allowed and allowed[i]["lat"] is None
    ]
    return jsonable_encoder({
        "sites": sites, "suggested": suggested, "missing_location": missing, "road": legs[0].geometry if legs else None,
        "legs": [{"from": names_[i], "to": names_[i + 1], "km": round(leg.km, 2), "minutes": round(leg.minutes) if leg.minutes is not None else None, "estimated": leg.estimated} for i, leg in enumerate(legs)],
        "km": round(sum(leg.km for leg in legs), 2), "minutes": round(sum(leg.minutes or 0 for leg in legs)), "home": home, "settings": map_settings(db),
    })  # fmt: skip


@router.get("/route-to/{site_id}")
def route_to(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Track,
    lat: float | None = None,
    lng: float | None = None,
) -> dict:
    """The road route from where the person is (or home) to the site, on our own map, and the
    Google Maps directions link (opened on the phone; nothing is sent from our server)."""
    from app.sites.models import Site  # noqa: PLC0415

    site = db.get(Site, site_id)
    if site is None or site.lat is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The site has no pinned location yet"
        )
    p = db.get(TrackingProfile, principal.user.id)
    start = (
        (lat, lng)
        if lat is not None and lng is not None
        else ((p.home_lat, p.home_lng) if p and p.home_status == "approved" else None)
    )
    dest = (float(site.lat), float(site.lng))
    legs = (
        geo.road_legs([start, dest], float(service.settings(db).road_factor), geometry=True)
        if start
        else []
    )
    return jsonable_encoder({
        "site": {"id": site.id, "name": site.name, "lat": dest[0], "lng": dest[1], "radius_m": service.site_radius(db, site)},
        "maps_link": geo.maps_link(*dest), "start": start, "road": legs[0].geometry if legs else None,
        "km": round(legs[0].km, 2) if legs else None, "minutes": round(legs[0].minutes) if legs and legs[0].minutes is not None else None,
        "estimated": bool(legs and legs[0].estimated), "settings": map_settings(db),
    })  # fmt: skip


# --- sites ---------------------------------------------------------------------------------------


@router.get("/sites/{site_id}/visits")
def site_visits(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("site.view"))],
    days_back: int = 30,
) -> dict:
    """Who checked in at this site, when and for how long (no location trail), and the gangs."""
    site = site_service.get_visible(db, site_id, scope, principal)
    since = service.ist_date(service.now()) - timedelta(days=days_back)
    rows = db.execute(
        select(FieldStop, FieldDay)
        .join(FieldDay, FieldDay.id == FieldStop.day_id)
        .where(FieldStop.site_id == site.id, FieldDay.on_date >= since)
        .order_by(FieldStop.in_at.desc())
    ).all()
    who = names(db, [d.user_id for _s, d in rows])
    gangs = db.scalars(
        select(GangVisit)
        .where(GangVisit.site_id == site.id, GangVisit.on_date >= since)
        .order_by(GangVisit.in_at.desc())
    ).all()
    from app.masters.models import Vendor  # noqa: PLC0415

    return jsonable_encoder({
        "site": {"id": site.id, "name": site.name, "lat": site.lat, "lng": site.lng, "radius_m": service.site_radius(db, site),
                 "maps_link": geo.maps_link(float(site.lat), float(site.lng)) if site.lat is not None else None},
        "visits": [{"person": who.get(d.user_id), "on_date": d.on_date, "in_at": s.in_at, "out_at": s.out_at, "minutes": service.minutes_on(s), "outside": s.in_outside or s.out_outside} for s, d in rows],
        "gangs": [{"id": g.id, "contractor": db.get(Vendor, g.contractor_id).name, "headcount": g.headcount, "on_date": g.on_date, "in_at": g.in_at, "out_at": g.out_at,
                   "hours": round((g.out_at - g.in_at).total_seconds() / 3600, 2) if g.out_at else None, "outside": g.in_outside or g.out_outside} for g in gangs],
    })  # fmt: skip


class SitePinIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int | None = Field(None, ge=20, le=5000)


@router.put("/sites/{site_id}/location")
def site_pin(
    site_id: int,
    body: SitePinIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Pin,
) -> dict:
    """Pin the site (picked on the map, or "use my location" standing at the site) and its radius;
    the change is logged."""
    site = site_service.get_visible(db, site_id, scope, principal)
    before = {
        "lat": str(site.lat) if site.lat is not None else None,
        "lng": str(site.lng) if site.lng is not None else None,
        "radius_m": site.radius_m,
    }
    site.lat, site.lng = Decimal(str(round(body.lat, 6))), Decimal(str(round(body.lng, 6)))
    site.radius_m, site.location_set_by, site.location_set_at = (
        # no radius sent: the site keeps its own (an explicit null goes back to the default)
        body.radius_m if "radius_m" in body.model_fields_set else site.radius_m,
        principal.user.id,
        service.now(),
    )
    record(
        db,
        request,
        principal,
        "site.location",
        "site",
        site.id,
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    return {
        "id": site.id,
        "lat": float(site.lat),
        "lng": float(site.lng),
        "radius_m": service.site_radius(db, site),
        "maps_link": geo.maps_link(float(site.lat), float(site.lng)),
    }


@router.get("/sites-missing-location")
def missing_location(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("site.view"))],
) -> list[dict]:
    """The sites on the planning list without a pin: "location missing"."""
    from app.sites.models import Site  # noqa: PLC0415

    q = select(Site).where(
        Site.lat.is_(None),
        Site.status.in_(("planned", "active", "on_hold")),
        site_service.scope_condition(scope, principal),
    )
    rows = db.scalars(q.order_by(Site.name))
    return [{"id": s.id, "code": s.code, "name": s.name, "status": s.status} for s in rows]


# --- settings per person (office_admin) ----------------------------------------------------------


def person_out(db, u: User) -> dict:
    p = db.get(TrackingProfile, u.id)
    rates = db.scalars(
        select(TravelRate).where(TravelRate.user_id == u.id).order_by(TravelRate.valid_from.desc())
    ).all()
    c = service.consent_of(db, u.id)
    return {
        "user_id": str(u.id), "name": u.full_name, "job_title": u.job_title, "roles": [r.code for r in u.roles], "is_demo": u.is_demo,
        "tracked": bool(p and p.tracked), "reimbursable": bool(p and p.reimbursable), "vehicle": p.vehicle if p else "bike",
        "manager_id": str(p.manager_id) if p and p.manager_id else None, "weekly_off": p.weekly_off if p else 6, "manager": db.get(User, p.manager_id).full_name if p and p.manager_id else None,
        "home_status": p.home_status if p else "none", "home": [p.home_lat, p.home_lng] if p and p.home_lat is not None else None,
        "pending": [p.pending_lat, p.pending_lng] if p and p.pending_lat is not None else None,
        "home_requested_at": p.home_requested_at if p else None, "consent_given_at": c.given_at if c else None,
        "rates": [{"id": r.id, "vehicle": r.vehicle, "rate_per_km": r.rate_per_km, "valid_from": r.valid_from, "valid_to": r.valid_to} for r in rates],
        "rate_today": next((r.rate_per_km for r in rates if r.valid_from <= service.ist_date(service.now()) and (r.valid_to is None or r.valid_to >= service.ist_date(service.now()))), None),
    }  # fmt: skip


LABOUR_ROLES = {"client", "site_receiver"}


@router.get("/admin/people")
def people(db: DbSession, _: Admin) -> list[dict]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name)).all()
    return jsonable_encoder(
        [
            person_out(db, u)
            for u in users
            if u.roles and not ({r.code for r in u.roles} <= LABOUR_ROLES)
        ]
    )


class PersonIn(BaseModel):
    tracked: bool | None = None
    reimbursable: bool | None = None
    vehicle: Literal["bike", "car", "other"] | None = None
    manager_id: str | None = None
    weekly_off: int | None = Field(None, ge=0, le=6)


@router.put("/admin/people/{user_id}")
def set_person(
    user_id: str,
    body: PersonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Admin,
) -> dict:
    u = db.get(User, _uid(user_id))
    if u is None or {r.code for r in u.roles} & LABOUR_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Only office employees are tracked or reimbursed"
        )
    p = service.profile(db, u.id)
    data = body.model_dump(exclude_unset=True)
    if "manager_id" in data:
        m = _uid(data["manager_id"]) if data["manager_id"] else None
        if m == u.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "A person is not their own manager"
            )
        p.manager_id = m
        data.pop("manager_id")
    for k, v in data.items():
        setattr(p, k, v)
    record(
        db,
        request,
        principal,
        "field.person",
        "user",
        u.id,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return jsonable_encoder(person_out(db, u))


class RateIn(BaseModel):
    vehicle: Literal["bike", "car", "other"] = "bike"
    rate_per_km: Decimal = Field(ge=0, le=1000)
    valid_from: date


@router.post("/admin/people/{user_id}/rates", status_code=status.HTTP_201_CREATED)
def add_rate(
    user_id: str,
    body: RateIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Admin,
) -> dict:
    """A new rate per km from a date (typed by hand): the rate in force until then ends the day
    before; the history is kept."""
    uid = _uid(user_id)
    if body.vehicle not in VEHICLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown vehicle")
    for r in db.scalars(
        select(TravelRate).where(
            TravelRate.user_id == uid,
            TravelRate.valid_from < body.valid_from,
            (TravelRate.valid_to.is_(None)) | (TravelRate.valid_to >= body.valid_from),
        )
    ):
        r.valid_to = body.valid_from - timedelta(days=1)
    if db.scalar(
        select(TravelRate.id).where(
            TravelRate.user_id == uid, TravelRate.valid_from >= body.valid_from
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "A rate already starts on or after that date")
    db.add(
        TravelRate(
            user_id=uid,
            vehicle=body.vehicle,
            rate_per_km=body.rate_per_km,
            valid_from=body.valid_from,
            created_by=principal.user.id,
        )
    )
    record(
        db, request, principal, "field.rate", "user", uid, after=jsonable_encoder(body.model_dump())
    )
    db.commit()
    return jsonable_encoder(person_out(db, db.get(User, uid)))


class HomeDecision(BaseModel):
    approve: bool


@router.post("/admin/people/{user_id}/home")
def decide_home(
    user_id: str,
    body: HomeDecision,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Admin,
) -> dict:
    uid = _uid(user_id)
    p = service.profile(db, uid)
    if p.pending_lat is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No home location waiting for approval")
    if body.approve:
        p.home_lat, p.home_lng, p.home_status = p.pending_lat, p.pending_lng, "approved"
        p.home_approved_by, p.home_approved_at = principal.user.id, service.now()
    else:
        p.home_status = "approved" if p.home_lat is not None else "rejected"
    p.pending_lat = p.pending_lng = None
    record(
        db, request, principal, "field.home_decided", "user", uid, after={"approved": body.approve}
    )
    db.commit()
    return jsonable_encoder(person_out(db, db.get(User, uid)))


@router.get("/admin/holidays")
def holidays(db: DbSession, _: Admin) -> list[dict]:
    from app.field.models import CompanyHoliday  # noqa: PLC0415

    return jsonable_encoder(
        [
            {"id": h.id, "on_date": h.on_date, "name": h.name}
            for h in db.scalars(select(CompanyHoliday).order_by(CompanyHoliday.on_date))
        ]
    )


class HolidayIn(BaseModel):
    on_date: date
    name: str = Field(min_length=1, max_length=100)


@router.post("/admin/holidays", status_code=status.HTTP_201_CREATED)
def add_holiday(
    body: HolidayIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin
) -> list[dict]:
    from app.field.models import CompanyHoliday  # noqa: PLC0415

    if db.scalar(select(CompanyHoliday.id).where(CompanyHoliday.on_date == body.on_date)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That date is already a holiday")
    db.add(
        CompanyHoliday(on_date=body.on_date, name=body.name.strip(), created_by=principal.user.id)
    )
    record(
        db,
        request,
        principal,
        "field.holiday",
        "field_holiday",
        str(body.on_date),
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return holidays(db, "all")


@router.delete("/admin/holidays/{hid}")
def remove_holiday(
    hid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin
) -> list[dict]:
    from app.field.models import CompanyHoliday  # noqa: PLC0415

    h = db.get(CompanyHoliday, hid)
    if h is not None:
        record(
            db,
            request,
            principal,
            "field.holiday_removed",
            "field_holiday",
            str(h.on_date),
            before={"name": h.name},
        )
        db.delete(h)
        db.commit()
    return holidays(db, "all")


@router.get("/admin/settings")
def get_settings(db: DbSession, _: Admin) -> dict:
    s = service.settings(db)
    return jsonable_encoder(
        {c.name: getattr(s, c.name) for c in s.__table__.columns if c.name != "id"}
    )


class SettingsIn(BaseModel):
    consent_version: str | None = Field(None, min_length=1, max_length=20)
    auto_end_at: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    site_radius_m: int | None = Field(None, ge=20, le=5000)
    home_flag_m: int | None = Field(None, ge=50, le=50000)
    gap_minutes: int | None = Field(None, ge=5, le=600)
    raw_days: int | None = Field(None, ge=1, le=3650)
    summary_years: int | None = Field(None, ge=1, le=30)
    tile_url: str | None = Field(None, max_length=300, pattern=r"^https://")
    tile_attribution: str | None = Field(None, max_length=300)


@router.put("/admin/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Admin
) -> dict:
    s = service.settings(db)
    data = body.model_dump(exclude_unset=True)
    if "auto_end_at" in data:
        h, m = (int(x) for x in data.pop("auto_end_at").split(":"))
        s.auto_end_at = s.auto_end_at.replace(hour=h, minute=m)
    for k, v in data.items():
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "field.settings",
        "field_settings",
        1,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return get_settings(db, "all")


# --- the travel claim ----------------------------------------------------------------------------


def claim_out(db, c: TravelClaim, principal) -> dict:
    u = db.get(User, c.user_id)
    p = db.get(TrackingProfile, c.user_id)
    who = names(db, [c.manager_approved_by, c.approved_by, *[d.edited_by for d in c.days]])
    mine = principal.user.id == c.user_id
    is_manager = (
        bool(p and p.manager_id == principal.user.id)
        or principal.permissions.get("field.team") == "all"
    )
    return {
        "id": c.id, "user_id": str(c.user_id), "person": u.full_name, "month": c.month, "status": c.status,
        "km": c.km, "days_amount": c.days_amount, "extras_amount": c.extras_amount, "total": c.total, "flagged_days": c.flagged_days,
        "manager": db.get(User, p.manager_id).full_name if p and p.manager_id else None,
        "manager_approved_by": who.get(c.manager_approved_by), "manager_approved_at": c.manager_approved_at,
        "approved_by": who.get(c.approved_by), "approved_at": c.approved_at, "payroll_month": c.payroll_month,
        "locked": c.status == "approved",
        "days": [{"id": d.id, "day_id": d.day_id, "on_date": d.on_date, "stops": d.stops, "km_basis": d.km_basis, "km": d.km, "estimated": d.estimated,
                  "rate_per_km": d.rate_per_km, "amount": d.amount, "flags": d.flags, "edited_km_from": d.edited_km_from,
                  "edit_reason": d.edit_reason, "edited_by": who.get(d.edited_by)} for d in c.days],
        "extras": [{"id": x.id, "on_date": x.on_date, "kind": x.kind, "amount": x.amount, "note": x.note} for x in c.extras],
        "can_add_extras": mine and c.status in ("draft", "ready"),
        "can_manager_approve": not mine and is_manager and c.status in ("draft", "ready"),
        "can_approve": "field.claims_approve" in principal.permissions and c.status == "manager_approved",
    }  # fmt: skip


def _claim(db, cid: int, principal) -> TravelClaim:
    c = db.get(TravelClaim, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if not (service.can_see(db, principal, c.user_id) or "field.claims" in principal.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your claim to see")
    return c


@router.get("/claims")
def claims(
    db: DbSession,
    principal: CurrentPrincipal,
    _: Track,
    month: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    q = select(TravelClaim)
    if month:
        q = q.where(TravelClaim.month == month)
    if user_id:
        q = q.where(TravelClaim.user_id == _uid(user_id))
    rows = [
        c
        for c in db.scalars(q.order_by(TravelClaim.month.desc(), TravelClaim.id))
        if service.can_see(db, principal, c.user_id) or "field.claims" in principal.permissions
    ]
    return jsonable_encoder(
        [
            {k: v for k, v in claim_out(db, c, principal).items() if k not in ("days", "extras")}
            for c in rows
        ]
    )


@router.get("/claims/{cid}")
def claim(cid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    c = _claim(db, cid, principal)
    if c.status in ("draft", "ready"):
        service.build_claim(db, c.user_id, c.month)
        db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


class BuildIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    user_id: str | None = None


@router.post("/claims/build")
def build(body: BuildIn, db: DbSession, principal: CurrentPrincipal, _: Track) -> dict:
    """The month's claim so far (the person's own; office_admin for anyone)."""
    uid = _uid(body.user_id) if body.user_id else principal.user.id
    if uid != principal.user.id and "field.admin" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your own claim only")
    u = db.get(User, uid)
    if u is None or not service.eligible(db, u) or service.consent_of(db, uid) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No travel claim: not eligible for travel reimbursement, or no consent",
        )
    c = service.build_claim(db, uid, body.month)
    db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


@router.post("/claims/{cid}/extras", status_code=status.HTTP_201_CREATED)
async def add_extra(
    cid: int, request: Request, db: DbSession, principal: CurrentPrincipal,
    on_date: Annotated[date, Form()], kind: Annotated[Literal["toll", "parking", "other"], Form()],
    amount: Annotated[Decimal, Form(gt=0, le=100000)], bill: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form(max_length=300)] = None,
) -> dict:  # fmt: skip
    c = _claim(db, cid, principal)
    if c.user_id != principal.user.id or c.status not in ("draft", "ready"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tolls and parking are added by the person, before the manager approves",
        )
    start, end = service.month_range(c.month)
    if not start <= on_date <= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The date is not in {c.month}")
    rel, _n = await save_upload(bill, f"field/{c.user_id}/bills")
    c.extras.append(
        TravelClaimExtra(on_date=on_date, kind=kind, amount=amount, note=note, bill_path=rel)
    )
    service.totals(c)
    record(
        db,
        request,
        principal,
        "field.claim_extra",
        "field_claim",
        c.id,
        after={"kind": kind, "amount": str(amount)},
    )
    db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


@router.get("/claims/{cid}/extras/{eid}/bill")
def extra_bill(cid: int, eid: int, db: DbSession, principal: CurrentPrincipal):
    c = _claim(db, cid, principal)
    x = next((x for x in c.extras if x.id == eid), None)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return send_file(x.bill_path)


class DayEditIn(BaseModel):
    km: Decimal | None = Field(None, ge=0, le=5000)
    basis: Literal["route", "tracked"] | None = None
    reason: str | None = Field(None, max_length=1000)


@router.put("/claims/{cid}/days/{did}")
def edit_day(
    cid: int,
    did: int,
    body: DayEditIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict:
    c = _claim(db, cid, principal)
    out = claim_out(db, c, principal)
    if not out["can_manager_approve"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The person's manager edits the days")
    d = db.get(TravelClaimDay, did)
    if d is None or d.claim_id != c.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Day not found")
    service.edit_claim_day(db, c, d, body.km, body.basis, body.reason, principal.user.id)
    record(
        db,
        request,
        principal,
        "field.claim_day_edit",
        "field_claim",
        c.id,
        before={"km": str(d.edited_km_from)},
        after={"km": str(d.km), "reason": d.edit_reason},
    )
    db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


@router.post("/claims/{cid}/manager-approve")
def manager_approve(cid: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    c = _claim(db, cid, principal)
    if not claim_out(db, c, principal)["can_manager_approve"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person's manager (or the director) approves the days"
        )
    service.build_claim(db, c.user_id, c.month)
    c.status, c.manager_approved_by, c.manager_approved_at = (
        "manager_approved",
        principal.user.id,
        service.now(),
    )
    for d in c.days:
        d.approved = True
    record(
        db,
        request,
        principal,
        "field.claim_manager_approved",
        "field_claim",
        c.id,
        after={"total": str(c.total)},
    )
    hooks.manager_approved(db, c, principal.user.id)
    db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


@router.post("/claims/{cid}/approve")
def approve(
    cid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("field.claims_approve"))],
) -> dict:
    """Accounts approve the month: the claim is locked and paid with this month's payroll
    (a reimbursement, outside the salary's gross)."""
    c = _claim(db, cid, principal)
    if c.status != "manager_approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "The manager approves the days first")
    c.status, c.approved_by, c.approved_at = "approved", principal.user.id, service.now()
    c.payroll_month = f"{service.now().astimezone(IST):%Y-%m}"
    record(
        db,
        request,
        principal,
        "field.claim_approved",
        "field_claim",
        c.id,
        after={"total": str(c.total), "payroll_month": c.payroll_month},
    )
    hooks.claim_approved(db, c, principal.user.id)
    db.commit()
    return jsonable_encoder(claim_out(db, c, principal))


def _xlsx(claims_: list[TravelClaim], db) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415

    wb = Workbook()
    ws = wb.active
    ws.title = "CLAIMS"
    ws.append(
        [
            "Person",
            "Month",
            "Status",
            "Km",
            "Days ₹",
            "Tolls and parking ₹",
            "Total ₹",
            "Flagged days",
            "Approved by",
            "Payroll month",
        ]
    )
    who = names(db, [c.approved_by for c in claims_] + [c.user_id for c in claims_])
    for c in claims_:
        ws.append(
            [
                who.get(c.user_id),
                c.month,
                c.status,
                float(c.km),
                float(c.days_amount),
                float(c.extras_amount),
                float(c.total),
                c.flagged_days,
                who.get(c.approved_by),
                c.payroll_month,
            ]
        )
    d = wb.create_sheet("DAYS")
    d.append(
        [
            "Person",
            "Date",
            "Stops",
            "Km basis",
            "Km",
            "Estimated",
            "Rate ₹/km",
            "Amount ₹",
            "Flags",
            "Edited from km",
            "Reason",
        ]
    )
    for c in claims_:
        for x in c.days:
            d.append([who.get(c.user_id), x.on_date, x.stops, x.km_basis, float(x.km), "yes" if x.estimated else "", float(x.rate_per_km), float(x.amount),
                      "; ".join(f["text"] for f in x.flags or []), float(x.edited_km_from) if x.edited_km_from is not None else None, x.edit_reason])  # fmt: skip
        for e in c.extras:
            d.append(
                [
                    who.get(c.user_id),
                    e.on_date,
                    f"{e.kind}: {e.note or ''}",
                    "",
                    None,
                    "",
                    None,
                    float(e.amount),
                    "",
                    None,
                    None,
                ]
            )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/claims/{cid}/export.xlsx")
def claim_xlsx(cid: int, db: DbSession, principal: CurrentPrincipal):
    c = _claim(db, cid, principal)
    return StreamingResponse(io.BytesIO(_xlsx([c], db)), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="travel-claim-{c.month}-{c.id}.xlsx"'})  # fmt: skip


@router.get("/claims-export.xlsx")
def month_xlsx(
    month: str, db: DbSession, _: Annotated[str, Depends(require_permission("field.claims"))]
):
    rows = list(
        db.scalars(select(TravelClaim).where(TravelClaim.month == month).order_by(TravelClaim.id))
    )
    return StreamingResponse(io.BytesIO(_xlsx(rows, db)), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="travel-claims-{month}.xlsx"'})  # fmt: skip


# --- labour gangs --------------------------------------------------------------------------------


def gang_out(db, v: GangVisit) -> dict:
    from app.execution.models import Labour  # noqa: PLC0415
    from app.masters.models import Vendor  # noqa: PLC0415

    workers = [db.get(Labour, w.labour_id).name for w in v.workers]
    return {
        "id": v.id, "site_id": v.site_id, "site": _site_name(db, v.site_id), "contractor_id": v.contractor_id, "contractor": db.get(Vendor, v.contractor_id).name,
        "on_date": v.on_date, "headcount": v.headcount, "workers": workers, "in_at": v.in_at, "out_at": v.out_at,
        "hours": round((v.out_at - v.in_at).total_seconds() / 3600, 2) if v.out_at else None,
        "in_outside": v.in_outside, "in_distance_m": v.in_distance_m, "in_reason": v.in_reason,
        "out_outside": v.out_outside, "out_distance_m": v.out_distance_m, "out_reason": v.out_reason,
        "supervisor": names(db, [v.supervisor_id]).get(v.supervisor_id),
    }  # fmt: skip


def _gang_site(db, site_id: int, scope: str, principal):
    return site_service.get_visible(db, site_id, scope, principal)


@router.get("/gangs")
def gangs(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Gang,
    site_id: int | None = None,
    on: date | None = None,
) -> dict:
    """The gangs checked in today (on the caller's sites), and the labour contractors with their
    workers to pick from."""
    from app.execution.models import Labour  # noqa: PLC0415
    from app.masters.models import Vendor  # noqa: PLC0415

    on = on or service.ist_date(service.now())
    q = select(GangVisit).where(GangVisit.on_date == on)
    if site_id:
        _gang_site(db, site_id, scope, principal)
        q = q.where(GangVisit.site_id == site_id)
    from app.sites.models import Site  # noqa: PLC0415

    visits = [
        v
        for v in db.scalars(q.order_by(GangVisit.in_at))
        if site_service.covers(scope, principal, db.get(Site, v.site_id))
    ]
    contractors = {}
    for w in db.scalars(
        select(Labour)
        .where(Labour.is_active.is_(True), Labour.subcontractor_id.is_not(None))
        .order_by(Labour.name)
    ):
        c = contractors.setdefault(
            w.subcontractor_id,
            {
                "id": w.subcontractor_id,
                "name": db.get(Vendor, w.subcontractor_id).name,
                "workers": [],
            },
        )
        c["workers"].append({"id": w.id, "name": w.name, "trade": w.trade})
    return jsonable_encoder(
        {
            "visits": [gang_out(db, v) for v in visits],
            "contractors": sorted(contractors.values(), key=lambda c: c["name"]),
            "sites": _my_sites(db, principal),
        }
    )


@router.post("/gangs/in", status_code=status.HTTP_201_CREATED)
async def gang_in(
    request: Request, db: DbSession, principal: CurrentPrincipal, scope: Gang,
    site_id: Annotated[int, Form()], contractor_id: Annotated[int, Form()], lat: Annotated[float, Form()], lng: Annotated[float, Form()],
    photo: Annotated[UploadFile, File()], accuracy: Annotated[float | None, Form()] = None,
    labour_ids: Annotated[str | None, Form()] = None, headcount: Annotated[int | None, Form(ge=1, le=500)] = None,
    reason: Annotated[str | None, Form(max_length=1000)] = None,
) -> dict:  # fmt: skip
    site = _gang_site(db, site_id, scope, principal)
    ids = [int(x) for x in (labour_ids or "").split(",") if x.strip().isdigit()]
    rel, _n = await save_upload(photo, f"field/gangs/{site.id}")
    v = service.gang_check_in(
        db, principal.user.id, site, contractor_id, ids, headcount, lat, lng, accuracy, reason, rel
    )
    record(
        db,
        request,
        principal,
        "field.gang_in",
        "field_gang_visit",
        v.id,
        after={
            "site_id": site.id,
            "contractor_id": contractor_id,
            "headcount": v.headcount,
            "outside": v.in_outside,
        },
    )
    db.commit()
    return jsonable_encoder(gang_out(db, v))


@router.post("/gangs/{vid}/out")
async def gang_out_(
    vid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: Gang,
    lat: Annotated[float, Form()], lng: Annotated[float, Form()], accuracy: Annotated[float | None, Form()] = None,
    reason: Annotated[str | None, Form(max_length=1000)] = None, photo: Annotated[UploadFile | None, File()] = None,
) -> dict:  # fmt: skip
    v = db.get(GangVisit, vid)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    site = _gang_site(db, v.site_id, scope, principal)
    rel = (await save_upload(photo, f"field/gangs/{site.id}"))[0] if photo else None
    service.gang_check_out(db, v, site, lat, lng, accuracy, reason, rel)
    record(
        db,
        request,
        principal,
        "field.gang_out",
        "field_gang_visit",
        v.id,
        after={"hours": gang_out(db, v)["hours"]},
    )
    db.commit()
    return jsonable_encoder(gang_out(db, v))


@router.get("/gangs/{vid}/photo")
def gang_photo(
    vid: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Gang,
    which: Literal["in", "out"] = "in",
):
    v = db.get(GangVisit, vid)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _gang_site(db, v.site_id, scope, principal)
    return send_file(v.in_photo if which == "in" else v.out_photo)
