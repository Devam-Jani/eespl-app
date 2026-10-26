# ruff: noqa: E501
"""From the Prompt 34 review, invented data: the library's seeded coverages as checked against the
planning sheets and the makers' data sheets; a tender's quoted total from lines written outside the
pricing routes; planning's read-only drawing of an estimate (no billing permission); the slip's
frame allowed by the production CSP."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.estimate import demo
from app.estimate.models import Coverage
from app.masters.models import Product
from app.tenders.models import BoqLine, Tender
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_material_estimate import _estimate, terrace  # noqa: F401  (fixture)

D = Decimal
REPO = Path("/repo")  # the repository, mounted in the dev stack

# product: value, min, max, source (the list in the Prompt 34 report)
SEEDED = {
    "SBR Latex": ("0.25", "0.2", "0.3", "to_confirm"),
    "Ultracem GR 60": ("2", "1.8", "2.2", "to_confirm"),
    "Epoxy Primer 021": ("0.2", "0.1", "0.25", "tds"),
    "Ultrathane": ("2", "2", "2.5", "tds"),
    "Ultrathane Logic Foam": ("0.65", "0.55", "0.7", "to_confirm"),
    "Ultracem 2C": ("3", "1.6", "3.5", "tds"),
    "45 gsm fibre mesh": ("1.05", "1", "1.1", "to_confirm"),
    "120 gsm geotextile": ("1.05", "1.05", "1.1", "to_confirm"),
    "Cemguard Plus": ("1.75", "1.5", "2", "tds"),
    "Cemkrete": ("0.4", "0.35", "0.5", "to_confirm"),
    "Cemcrystal": ("1", "0.5", "1.5", "to_confirm"),
}


def test_the_seeded_coverages_are_the_checked_figures(db):
    ids = demo.library(db)
    assert set(SEEDED) <= set(ids)
    for name, (val, lo, hi, src) in SEEDED.items():
        c = db.scalar(select(Coverage).where(Coverage.product_id == ids[name], Coverage.system_id.is_(None)))
        assert (c.value, c.min_value, c.max_value, c.source) == (D(val), D(lo), D(hi), src), name
        assert c.note.startswith("DEMO: ") and c.is_demo, name
    # the Dholera figures the review named: Logic Foam 0.65 (not 0.05), Ultracem 2C's 1.6 inside its range
    assert D(SEEDED["Ultrathane Logic Foam"][0]) == D("0.65") and D(SEEDED["Ultracem 2C"][1]) <= D("1.6")
    # the laps are in the mesh's coverage, so its wastage is the cut-offs only
    assert db.get(Product, ids["45 gsm fibre mesh"]).wastage_percent == 5


def test_the_quoted_total_is_the_lines_however_they_are_written(db):
    """The header read ₹0.00 for a tender whose lines (written by the demo) had a qty and a rate."""
    t = Tender(code="T-INV-QT", name="Invented quoted total", status="draft")
    db.add(t)
    db.flush()
    a = BoqLine(tender_id=t.id, sort_order=1, unit="sqm", qty=D(560), rate=D("1072"), description="PU coating")
    b = BoqLine(tender_id=t.id, sort_order=2, unit="sqm", qty=D("12.5"), rate=D("65.30"), description="Geotextile")
    q = BoqLine(tender_id=t.id, sort_order=3, unit="sqm", qty=D(10), qty_note="QRO", rate=D(100), description="Rate only")
    db.add_all([a, b, q])
    db.commit()
    assert (a.amount, b.amount, q.amount) == (D("600320.00"), D("816.25"), None)  # 816.25: 12.5 × 65.30
    assert t.quoted_total == D("601136.25")
    a.rate = D("1100")
    db.commit()
    assert a.amount == D("616000.00") and t.quoted_total == D("616816.25")
    db.delete(b)
    db.commit()
    db.refresh(t)
    assert t.quoted_total == D("616000.00")


def test_planning_sees_the_estimates_drawing_read_only(terrace, db, login_as):  # noqa: F811
    t = terrace
    e = _estimate(t)
    pc, ph = login_as("planning", email="planner-p34@example.com")
    assert pc.get(f"/api/measure/sites/{t['site'].id}", headers=ph).status_code == 403  # Measure and bill: billing's
    r = pc.get(f"/api/estimate/estimates/{e['id']}/drawing", headers=ph)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["site"]["code"] == "S-TER-1" and v["can_measure"] is False and v["drawing"] is None  # outlines only, no DWG read here
    by = {a["code"]: a for a in v["areas"]}
    assert set(by) == {"UT", "S1", "S2", "LT"} and all(a["in_estimate"] == "in" for a in by.values())
    assert "billed" not in by["UT"] and by["UT"]["outline"]
    assert not {"items", "sheets", "rate"} & set(v)  # nothing of the bills
    # nothing to write: the drawing view has no POST, and planning still cannot measure
    assert pc.post(f"/api/estimate/estimates/{e['id']}/drawing", headers=ph).status_code == 405
    assert pc.post(f"/api/measure/sites/{t['site'].id}/areas", json={"outline": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "code": "X", "name": "X"}, headers=ph).status_code == 403
    # a site engineer not on this site does not see it; the director gets the link to Measure and bill
    sc, sh = login_as("site_engineer", email="se-p34@example.com")
    assert sc.get(f"/api/estimate/estimates/{e['id']}/drawing", headers=sh).status_code == 404
    assert t["c"].get(f"/api/estimate/estimates/{e['id']}/drawing", headers=t["h"]).json()["can_measure"] is True


@pytest.mark.skipif(not (REPO / "deploy/prod/Caddyfile").exists(), reason="the production files are mounted at /repo in the dev stack")
def test_the_csp_lets_the_app_frame_its_own_slip():
    """A PDF slip is shown in a frame of a blob: URL: default-src 'self' refused it ("This content is
    blocked"). frame-src allows our own blobs only; no other page may frame the app."""
    caddy = (REPO / "deploy/prod/Caddyfile").read_text()
    csp = next(line for line in caddy.splitlines() if "Content-Security-Policy" in line)
    assert "frame-src 'self' blob:;" in csp and "frame-ancestors 'none'" in csp and "X-Frame-Options \"DENY\"" in caddy
