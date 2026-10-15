# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""From the DWG takeoff review, with invented drawings and data: the plan name from the sheet frame
(not the nearest title), "sheet unknown" and picking it, both sets of counts, repeated labels
grouped, and the rates not sent to the client lines blocking Submit."""

import io

import ezdxf
from sqlalchemy import select

from app.models import AuditLog
from tests.test_finance import boss, world  # noqa: F401  (fixtures)
from tests.test_rate_working import _group, _working, boq  # noqa: F401  (fixtures)
from tests.test_takeoff import areas, make_dxf, place, read, upload  # noqa: F401  (fixtures)


def sheets_dxf() -> bytes:
    """The invented plan on its sheet (a frame around the rooms and the 1ST FLOOR title), and
    above it a schedule sheet (its own frame, no plan title) with a ladies toilet's size and
    TERRACE three times without a size, on the schedule's layer. Between the two sheets, outside
    both frames: an O.H.W.T. PLAN title, the nearest title below the schedule's labels."""
    doc = ezdxf.read(io.StringIO(make_dxf().decode()))
    msp = doc.modelspace()
    k = 1000.0
    msp.add_lwpolyline(
        [(-2 * k, -5 * k), (17 * k, -5 * k), (17 * k, 5 * k), (-2 * k, 5 * k)],
        close=True,
        dxfattribs={"layer": "SHEET"},
    )
    msp.add_lwpolyline(
        [(-2 * k, 10 * k), (17 * k, 10 * k), (17 * k, 20 * k), (-2 * k, 20 * k)],
        close=True,
        dxfattribs={"layer": "SHEET"},
    )
    msp.add_text(
        "O.H.W.T. PLAN", dxfattribs={"layer": "A-TEXT", "insert": (0, 8 * k), "height": 0.3 * k}
    )
    msp.add_mtext(
        "LADIES TOILET\\P7'0\"X10'0\"",
        dxfattribs={"layer": "A-SCHED", "insert": (2 * k, 15 * k), "char_height": 0.15 * k},
    )
    for x in (5, 8, 11):
        msp.add_text(
            "TERRACE",
            dxfattribs={"layer": "A-SCHED", "insert": (x * k, 12 * k), "height": 0.15 * k},
        )
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


def test_the_plan_comes_from_the_sheet_frame_and_an_unknown_sheet_is_picked_by_hand(
    boss, place, db
):
    c, h = boss
    _d, rev = upload(c, h, place["site"], sheets_dxf())
    f = read(c, h, rev)
    assert f["status"] == "ready", f["error"]
    rows = c.get(f"/api/takeoff/files/{f['id']}/areas?show=all", headers=h).json()["areas"]
    toilet = next(
        a for a in rows if a["name"] == "LADIES TOILET" and a["size_text"] == "10'6\"X7'3\""
    )
    assert toilet["plan"] == "1ST FLOOR WORKING PLAN"  # inside the plan's frame
    sched = next(
        a for a in rows if a["name"] == "LADIES TOILET" and a["size_text"] != "10'6\"X7'3\""
    )
    assert sched["plan"] is None  # not "O.H.W.T. PLAN", the nearest title below it
    f = c.get(f"/api/takeoff/files/{f['id']}", headers=h).json()
    assert f["sheet_unknown"] == 4  # the schedule's toilet and its three TERRACE labels
    assert set(f["plan_titles"]) == {"1ST FLOOR WORKING PLAN", "O.H.W.T. PLAN"}
    r = c.put(f"/api/takeoff/areas/{sched['id']}", json={"plan": "O.H.W.T. PLAN"}, headers=h)
    assert r.status_code == 200 and r.json()["plan"] == "O.H.W.T. PLAN"


def test_repeated_labels_without_a_size_are_one_row_and_sized_labels_come_first(boss, place, db):
    c, h = boss
    _d, rev = upload(c, h, place["site"], sheets_dxf())
    f = read(c, h, rev)
    rows = c.get(f"/api/takeoff/files/{f['id']}/areas?show=all", headers=h).json()["areas"]
    terraces = [a for a in rows if a["name"] == "TERRACE" and a["size_text"] is None]
    assert len(terraces) == 1 and terraces[0]["count"] == 3 and len(terraces[0]["group_ids"]) == 3
    sized = [a["label_area_sqm"] is not None for a in rows]
    assert sized == sorted(sized, reverse=True)  # every sized label before the first without a size
    # leaving the group out leaves out each of its labels
    for aid in terraces[0]["group_ids"]:
        assert (
            c.put(f"/api/takeoff/areas/{aid}", json={"status": "ignored"}, headers=h).status_code
            == 200
        )
    rows = c.get(f"/api/takeoff/files/{f['id']}/areas?show=all", headers=h).json()["areas"]
    assert all(
        a["status"] == "ignored" for a in rows if a["name"] == "TERRACE" and a["size_text"] is None
    )


def test_both_sets_of_counts_all_texts_and_the_mapped_layers(boss, place, db):
    c, h = boss
    _d, rev = upload(c, h, place["site"], sheets_dxf())
    f = read(c, h, rev)
    before = f["count_sets"]
    assert before["all"]["texts"] == f["texts"]  # every text read, what the screen used to show
    assert before["all"]["size_labels"] == before["mapped"]["size_labels"] == 4
    assert before["mapped"]["hidden_layers"] == 0
    r = c.put(
        f"/api/takeoff/files/{f['id']}/layer-map",
        json={"architect": "Invented Architects", "roles": {"A-SCHED": "hide"}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    after = c.get(f"/api/takeoff/files/{f['id']}", headers=h).json()["count_sets"]
    assert after["all"] == before["all"]  # every layer: unchanged
    assert after["mapped"]["size_labels"] == 3 and after["mapped"]["hidden_layers"] == 1
    assert after["mapped"]["texts"] == before["mapped"]["texts"] - 4
    assert after["all"]["notes"] == after["mapped"]["notes"] == 2


def test_rates_not_sent_to_the_lines_hold_submit_until_sent_or_confirmed(boss, boq, db):
    c, h = boss
    w = c.post(f"/api/rate-working/{_working(c, h, boq)['id']}/suggest", headers=h).json()
    raft = _group(w, "raft")
    c.put(f"/api/rate-working/groups/{raft['id']}", json={"system_id": boq["system"]}, headers=h)
    assert c.post(f"/api/rate-working/{w['id']}/apply", headers=h).status_code == 200

    def unsent():
        return c.get(f"/api/rate-working/tenders/{boq['tender']}/unsent", headers=h).json()[
            "unsent"
        ]

    assert unsent() is None  # sent: the lines carry the working's rates
    # the margin basis changes in the settings: the worked rate moves, the lines do not
    c.put("/api/prices/settings", json={"margin_basis": "selling"}, headers=h)
    u = unsent()
    assert u and u["lines"] == 4 and u["message"].startswith("Rates not sent to the lines")
    row = u["rows"][0]
    assert row["worked_rate"] != row["line_rate"] and float(row["difference"]) > 0
    body = {"note": "invented", "override_reason": "invented checklist pass"}
    r = c.post(f"/api/tenders/{boq['tender']}/submit", json=body, headers=h)
    assert r.status_code == 409 and "Rates not sent to the lines" in r.json()["detail"]
    # sending the rates clears it ...
    assert c.post(f"/api/rate-working/{w['id']}/apply", headers=h).status_code == 200
    assert unsent() is None
    # ... or the user confirms the lines' rates (logged)
    c.put("/api/prices/settings", json={"margin_basis": "cost"}, headers=h)
    assert unsent()["lines"] == 4
    r = c.post(
        f"/api/tenders/{boq['tender']}/submit", json=body | {"rates_confirmed": True}, headers=h
    )
    assert r.status_code == 200, r.text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "tender.rates_not_sent_confirmed"))
