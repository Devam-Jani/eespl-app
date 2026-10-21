# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Part 0 of the BOQ knowledge milestone, invented data: consumption picked per surface and the
client's requirement with its source, a day started on a holiday or weekly off flagged, and a
drawing without frames getting its sheet guessed for the user to confirm."""

import io
from datetime import UTC, datetime
from decimal import Decimal

import ezdxf

from app.costing.models import ProductConsumption
from tests.test_field import HOME, clock, consent, osrm, start, team  # noqa: F401  (fixtures)
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_rate_working import _group, _working, boq  # noqa: F401  (fixtures)
from tests.test_takeoff import make_dxf, place, read, upload  # noqa: F401  (fixtures)


def d(v) -> Decimal:
    return Decimal(str(v))


def test_consumption_is_picked_by_surface_and_requirement_with_its_source(boss, boq, db):
    c, h = boss
    hdpe = boq["products"][0]
    db.add_all([
        ProductConsumption(product_id=hdpe, surface="rcc", coats=2, consumption=d("1.40"), source="old_boq", source_ref="Invented BOQ.xlsx · Working · row 12", used_count=7),
        ProductConsumption(product_id=hdpe, surface="brick", coats=2, consumption=d("1.80"), source="data_sheet", source_ref="Invented TDS p.2", used_count=1),
        ProductConsumption(product_id=hdpe, surface="rcc", min_kg_sqm=d("1.5"), consumption=d("1.55"), source="site_actual", source_ref="Invented site", used_count=2),
    ])  # fmt: skip
    db.commit()
    w = c.post(f"/api/rate-working/{_working(c, h, boq)['id']}/suggest", headers=h).json()
    raft = _group(w, "raft")
    g = c.put(
        f"/api/rate-working/groups/{raft['id']}", json={"system_id": boq["system"]}, headers=h
    ).json()
    p = next(x for x in g["products"] if x["product_id"] == hdpe)
    assert d(p["consumption"]) == d("1.2") and p["consumption_source"].startswith(
        "the system"
    )  # no surface yet: the system's figure (seeded row)
    g = c.put(
        f"/api/rate-working/groups/{raft['id']}", json={"surface": "rcc", "coats": 2}, headers=h
    ).json()
    p = next(x for x in g["products"] if x["product_id"] == hdpe)
    assert d(p["consumption"]) == d("1.40") and p["consumption_source"].startswith(
        "old BOQs: RCC, 2 coats (used 7×)"
    )
    assert "Invented BOQ.xlsx" in p["consumption_source"]
    g = c.put(f"/api/rate-working/groups/{raft['id']}", json={"surface": "brick"}, headers=h).json()
    p = next(x for x in g["products"] if x["product_id"] == hdpe)
    assert d(p["consumption"]) == d("1.80") and p["consumption_source"].startswith(
        "data sheet: Brick"
    )
    # the client asks for a minimum of 1.5 kg/sqm on RCC: a row below it is never picked
    g = c.put(
        f"/api/rate-working/groups/{raft['id']}",
        json={"surface": "rcc", "req_min_kg_sqm": "1.5"},
        headers=h,
    ).json()
    p = next(x for x in g["products"] if x["product_id"] == hdpe)
    assert d(p["consumption"]) == d("1.55") and p["consumption_source"].startswith(
        "site actual: RCC, min 1.5 kg/sqm"
    )
    # changing it by hand still needs a reason
    rows = [
        {"id": x["id"], "product_id": x["product_id"], "consumption": x["consumption"]}
        for x in g["products"]
    ]
    rows[[x["product_id"] for x in rows].index(hdpe)]["consumption"] = "1.7"
    r = c.put(f"/api/rate-working/groups/{raft['id']}", json={"products": rows}, headers=h)
    assert r.status_code == 422 and "site actual" in r.json()["detail"]


def test_a_day_started_on_a_holiday_or_the_weekly_off_is_flagged_not_blocked(team, clock, db):
    t = team
    consent(t)
    r = t["c"].post(
        "/api/field/admin/holidays",
        json={"on_date": "2026-10-20", "name": "Invented Diwali"},
        headers=t["h"]["admin"],
    )
    assert r.status_code == 201
    clock.at = datetime(2026, 10, 20, 3, 30, tzinfo=UTC)  # a Tuesday, the holiday
    day = start(t).json()
    assert any(f["code"] == "day_off" and "Invented Diwali" in f["text"] for f in day["flags"])
    t["c"].post(
        "/api/field/day/end", json={"lat": HOME[0], "lng": HOME[1]}, headers=t["h"]["sales"]
    )
    clock.at = datetime(2026, 10, 25, 3, 30, tzinfo=UTC)  # a Sunday: the default weekly off
    r = start(t)
    assert r.status_code == 200 and any(
        "weekly off (Sunday)" in f["text"] for f in r.json()["flags"]
    )
    # the weekly off moved to Monday: a Sunday is a working day
    t["c"].put(
        f"/api/field/admin/people/{t['ids']['sales']}",
        json={"weekly_off": 0},
        headers=t["h"]["admin"],
    )
    t["c"].post(
        "/api/field/day/end", json={"lat": HOME[0], "lng": HOME[1]}, headers=t["h"]["sales"]
    )
    clock.at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)  # the next Sunday
    assert not any(f["code"] == "day_off" for f in start(t).json()["flags"])


def test_a_drawing_without_frames_gets_its_sheet_guessed_to_confirm(boss, place, db):
    c, h = boss
    # the rooms joined by a corridor wall, as on a real plan; its title under it; no frame
    doc = ezdxf.read(io.StringIO(make_dxf().decode()))
    doc.modelspace().add_line((0, 0), (15000, 0), dxfattribs={"layer": "A-WALL"})
    buf = io.StringIO()
    doc.write(buf)
    _d, rev = upload(c, h, place["site"], buf.getvalue().encode())
    f = read(c, h, rev)
    rows = c.get(f"/api/takeoff/files/{f['id']}/areas?show=all", headers=h).json()["areas"]
    toilet = next(a for a in rows if a["name"] == "LADIES TOILET")
    assert toilet["plan"] == "1ST FLOOR WORKING PLAN" and toilet["plan_guessed"]
    assert c.get(f"/api/takeoff/files/{f['id']}", headers=h).json()["sheet_guessed"] == len(rows)
    r = c.put(
        f"/api/takeoff/areas/{toilet['id']}", json={"plan": toilet["plan"]}, headers=h
    )  # confirmed
    assert r.json()["plan"] == "1ST FLOOR WORKING PLAN" and not r.json()["plan_guessed"]
