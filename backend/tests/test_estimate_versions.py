# ruff: noqa: E501
"""An issued estimate keeps its figures whatever the library does afterwards; the page says when the
library has moved on; Revise makes the next version and the old one stays read-only."""

import io
from decimal import Decimal

import openpyxl
from sqlalchemy import select

from app.estimate import requests as reqs
from app.estimate import service as svc
from app.estimate.models import Coverage, Estimate, EstimateArea
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_material_estimate import _estimate, terrace  # noqa: F401  (fixture)

D = Decimal


def _issued(t, db):
    c, h = t["c"], t["h"]
    pid = t["ids"]["Ultrathane"]
    e = _estimate(t, [{"product_id": pid, "system_id": t["pu"].id}])
    r = c.post(f"/api/estimate/estimates/{e['id']}/issue", headers=h)
    assert r.status_code == 200, r.text
    return c, h, r.json(), pid


def _raise_coverage(c, h, db, pid, value="2.4"):
    cov = db.scalar(select(Coverage).where(Coverage.product_id == pid))
    r = c.put(f"/api/estimate/coverages/{cov.id}", json={"product_id": pid, "value": value, "min_value": "2", "max_value": "2.5", "unit": "kg/sqm", "source": "tds"}, headers=h)
    assert r.status_code == 200, r.text


def _sheet_total(data: bytes) -> list:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    return [row for ws in wb for row in ws.iter_rows(values_only=True) if row[0] == "Total"]


def test_a_library_change_does_not_move_an_issued_estimate_and_the_page_says_so(terrace, db):  # noqa: F811
    c, h, e, pid = _issued(terrace, db)
    url = f"/api/estimate/estimates/{e['id']}"
    assert e["library_changes"] == [] and e["can_revise"] is True and e["version"] == 1
    excel = _sheet_total(c.get(f"{url}/excel", headers=h).content)
    balance = c.get(f"{url}/balance", headers=h).json()
    _raise_coverage(c, h, db, pid)
    db.expire_all()
    after = c.get(url, headers=h).json()
    # everything read from the estimate is as issued: lines, areas, summary, Excel, the balance
    assert after["lines"] == e["lines"] and after["summary"] == e["summary"]
    assert _sheet_total(c.get(f"{url}/excel", headers=h).content) == excel
    assert c.get(f"{url}/balance", headers=h).json() == balance
    est = db.get(Estimate, e["id"])
    assert reqs.left(db, est, pid, None) == D(e["lines"][0]["qty"])
    # ... and the page says what the library would give now
    [ch] = after["library_changes"]
    assert ch["product"] == "Ultrathane" and D(ch["issued_qty"]) == D(e["lines"][0]["qty"])
    assert D(ch["library_qty"]) == D(ch["issued_qty"]) * D("2.4") / D(e["lines"][0]["per_sqm"])


def test_a_draft_still_follows_the_library(terrace, db):  # noqa: F811
    pid = terrace["ids"]["Ultrathane"]
    e = _estimate(terrace, [{"product_id": pid, "system_id": terrace["pu"].id}])
    c, h = terrace["c"], terrace["h"]
    _raise_coverage(c, h, db, pid)
    db.expire_all()
    now = c.get(f"/api/estimate/estimates/{e['id']}", headers=h).json()
    assert D(now["lines"][0]["qty"]) > D(e["lines"][0]["qty"]) and now["library_changes"] == [] and now["can_revise"] is False


def test_revise_makes_the_next_version_and_the_old_one_stays_read_only(terrace, db):  # noqa: F811
    c, h, e, pid = _issued(terrace, db)
    url = f"/api/estimate/estimates/{e['id']}"
    _raise_coverage(c, h, db, pid)
    db.expire_all()
    r = c.post(f"{url}/revise", headers=h)
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["code"] == f"{e['code']}-V2" and v2["version"] == 2 and v2["status"] == "draft" and v2["can_edit"] is True
    assert v2["replaces"]["id"] == e["id"] and v2["library_changes"] == []
    assert D(v2["lines"][0]["qty"]) > D(e["lines"][0]["qty"])  # on today's library
    # the same areas, new rows, a cut-out still under its own parent's copy
    assert [(a["code"], a["included"]) for a in v2["areas"]] == [(a["code"], a["included"]) for a in e["areas"]]
    new_areas = {a.id: a for a in db.scalars(select(EstimateArea).where(EstimateArea.estimate_id == v2["id"]))}
    assert not set(new_areas) & {a["id"] for a in e["areas"]}
    cut = [a for a in new_areas.values() if a.parent_id]
    assert cut and all(a.parent_id in new_areas for a in cut)
    # the old version: as issued, no second next version, no edits
    old = c.get(url, headers=h).json()
    assert old["lines"] == e["lines"] and old["can_revise"] is False and old["next_version"]["code"] == v2["code"] and old["library_changes"] == []
    assert c.post(f"{url}/revise", headers=h).status_code == 409
    assert c.post(f"{url}/lines", json={"product_id": pid, "system_id": terrace["pu"].id}, headers=h).status_code == 409
    # V3 from V2 only once V2 is issued; the code does not grow -V2-V3
    assert c.post(f"/api/estimate/estimates/{v2['id']}/revise", headers=h).status_code == 409
    c.post(f"/api/estimate/estimates/{v2['id']}/issue", headers=h)
    v3 = c.post(f"/api/estimate/estimates/{v2['id']}/revise", headers=h).json()
    assert v3["code"] == f"{e['code']}-V3"


def test_what_the_site_asked_on_the_old_version_still_counts_on_the_new_one(terrace, db):  # noqa: F811
    c, h, e, pid = _issued(terrace, db)
    site = terrace["site"]
    area = e["lines"][0]["rows"][0]["area_id"]
    r = reqs.ask(db, site, product_id=pid, area_sqm=D(10), thickness_mm=None, mix_design_id=None, estimate_area_id=area, reason=None, user_id=None)
    db.commit()
    asked = D(r.qty)
    v1 = db.get(Estimate, e["id"])
    left_area_v1 = reqs.left(db, v1, pid, db.get(EstimateArea, area))
    # V1 stays the site's estimate while V2 is a draft
    v2 = c.post(f"/api/estimate/estimates/{e['id']}/revise", headers=h).json()
    assert reqs.estimate_for(db, site.id).id == e["id"]
    c.post(f"/api/estimate/estimates/{v2['id']}/issue", headers=h)
    db.expire_all()
    assert reqs.estimate_for(db, site.id).id == v2["id"]
    new = db.get(Estimate, v2["id"])
    same = db.scalar(select(EstimateArea).where(EstimateArea.estimate_id == new.id, EstimateArea.copied_from_id == area))
    assert reqs.left(db, new, pid, same) == left_area_v1
    assert reqs.left(db, new, pid, None) == D(v2["lines"][0]["qty"]) - asked
    bal = next(b for b in c.get(f"/api/estimate/estimates/{v2['id']}/balance", headers=h).json() if b["product_id"] == pid)
    assert D(bal["requested"]) == asked


def test_estimates_issued_before_snapshots_read_live_until_the_backfill(terrace, db):  # noqa: F811
    c, h, e, pid = _issued(terrace, db)
    est = db.get(Estimate, e["id"])
    est.snapshot = None
    db.commit()
    assert svc.library_changes(db, est) == []
    est.snapshot = svc.freeze(db, est)
    db.commit()
    assert svc.worked(db, est)[0].qty == D(e["lines"][0]["qty"])
