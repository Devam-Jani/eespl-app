"""Distances: the straight line between two points, tracked km from a day's points, and road km
from our own OSRM (osrm-backend in docker, the Geofabrik western India extract). Nothing goes to a
paid or third-party routing service. OSRM down: the straight line x 1.3, marked estimated."""

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from app.config import settings

EARTH_M = 6371008.8


def metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """The great-circle distance in metres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class Point:
    at: datetime
    lat: float
    lng: float
    accuracy_m: float | None = None


@dataclass
class Tracked:
    km: float
    used: int  # good points used
    jitter: int  # moves under the jitter distance, dropped
    jumps: list[dict]  # impossible jumps, dropped: {at, kmh, km}
    poor: int  # points with poor accuracy, kept but not used


def tracked_km(
    points: list[Point], accuracy_max_m: float, jitter_m: float, max_kmh: float
) -> Tracked:
    """The sum of distances between good points in time order: points with poor accuracy are left
    out, a move under the jitter distance is not a move (the next point is measured from the last
    kept one), and a jump faster than max_kmh from the last kept point is dropped."""
    good = [
        p
        for p in sorted(points, key=lambda p: p.at)
        if p.accuracy_m is None or p.accuracy_m <= accuracy_max_m
    ]
    poor = len(points) - len(good)
    total, jitter, jumps, used = 0.0, 0, [], 0
    last: Point | None = None
    for p in good:
        if last is None:
            last, used = p, 1
            continue
        d = metres(last.lat, last.lng, p.lat, p.lng)
        secs = (p.at - last.at).total_seconds()
        if d < jitter_m:
            jitter += 1
            continue
        kmh = (d / 1000) / (secs / 3600) if secs > 0 else math.inf
        if kmh > max_kmh:
            jumps.append(
                {
                    "at": p.at.isoformat(),
                    "kmh": round(kmh) if math.isfinite(kmh) else None,
                    "km": round(d / 1000, 2),
                }
            )
            continue
        total += d
        last = p
        used += 1
    return Tracked(km=total / 1000, used=used, jitter=jitter, jumps=jumps, poor=poor)


@dataclass
class Leg:
    km: float
    minutes: float | None
    estimated: bool
    geometry: list[list[float]] | None = None  # [[lat, lng], ...] when asked for


def _get(path: str) -> dict:
    url = settings.osrm_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=settings.osrm_timeout_s) as r:  # noqa: S310  (our own OSRM)
        return json.loads(r.read().decode())


def _coords(points: list[tuple[float, float]]) -> str:
    return ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)


def straight(points: list[tuple[float, float]], factor: float) -> list[Leg]:
    return [
        Leg(km=metres(a[0], a[1], b[0], b[1]) / 1000 * factor, minutes=None, estimated=True)
        for a, b in zip(points, points[1:], strict=False)
    ]


def road_legs(
    points: list[tuple[float, float]], factor: float, geometry: bool = False
) -> list[Leg]:
    """Road km (and minutes) for each leg between consecutive points, from OSRM; OSRM down or no
    road found: the straight line x factor, estimated."""
    if len(points) < 2:
        return []
    try:
        overview = "full&geometries=geojson" if geometry else "false"
        data = _get(f"/route/v1/driving/{_coords(points)}?overview={overview}&steps=false")
        if data.get("code") != "Ok" or not data.get("routes"):
            return straight(points, factor)
        route = data["routes"][0]
        legs = [
            Leg(km=leg["distance"] / 1000, minutes=leg["duration"] / 60, estimated=False)
            for leg in route["legs"]
        ]
        if geometry and legs:
            legs[0].geometry = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
        return legs
    except (OSError, urllib.error.URLError, ValueError, KeyError):
        return straight(points, factor)


def trip_order(home: tuple[float, float], stops: list[tuple[float, float]]) -> list[int] | None:
    """The shortest road round trip from home through the stops (OSRM trip, home first and last):
    the stops' order as indexes into `stops`; None when OSRM is down."""
    if not stops:
        return []
    try:
        data = _get(
            f"/trip/v1/driving/{_coords([home, *stops])}?source=first&roundtrip=true&overview=false"
        )
        if data.get("code") != "Ok":
            return None
        order = sorted(
            range(1, len(stops) + 1), key=lambda i: data["waypoints"][i]["waypoint_index"]
        )
        return [i - 1 for i in order]
    except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError):
        return None


def maps_link(lat: float, lng: float) -> str:
    """Directions on the phone's Google Maps to the pin: a plain link, no key, nothing sent from
    our server."""
    return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lng:.6f}"
