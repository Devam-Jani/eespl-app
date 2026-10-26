# ruff: noqa: E501
"""The billing team's real example (data/samples/billing/, gitignored): skipped when it is not there
(CI). Point REAL_BILLING_DIR at the folder (it holds check.json and the project folder)."""

import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.measure import realcheck
from tests.test_finance import boss  # noqa: F401  (fixture: a user to act as)

D = Decimal


def _folder() -> Path | None:
    for p in (os.environ.get("REAL_BILLING_DIR"), "/real", str(Path(__file__).resolve().parents[2] / "data" / "samples" / "billing")):
        if p and (Path(p) / "check.json").exists():
            return Path(p)
    return None


FOLDER = _folder()
pytestmark = pytest.mark.skipif(FOLDER is None, reason="the billing team's real example is not here (data/samples/billing/)")


@pytest.fixture(scope="module")
def real():
    return FOLDER


def test_pool_a_measured_both_ways(boss, db, real):  # noqa: F811
    out = realcheck.run(db, real)
    imp = out["imported"]
    # a. the old sheet imported: its totals as the billing team's sheet
    read = {r["item_no"]: r for r in imp["items"]}
    assert read["1"]["qty"] == D("1682.231") and read["1"]["sqm"] == D("156.341204")
    assert read["2"]["qty"] == D("2")
    assert read["3"]["qty"] == D("1366.423") and read["3"]["sqm"] == D("126.991")
    assert imp["totals"]["basic"] == D("130116.15") and D(imp["totals"]["read_grand"]).quantize(D("0.01")) == D("153537.00")
    assert imp["skipped"] == [] and out["ra"].endswith("-12")
    # b. the areas clicked on the drawing
    dr = {d["area"]: d for d in out["drawing"]}
    assert dr["P"]["plan_area"].quantize(D("0.0001")) == D("55.0027") and dr["P"]["plan_periphery"].quantize(D("0.001")) == D("30.119")
    assert dr["Q"]["plan_area"].quantize(D("0.0001")) == D("10.0423")  # as drawn in the plan
    assert dr["Q"]["team_area"].quantize(D("0.0001")) == D("6.1324") and dr["Q"]["team_periphery"].quantize(D("0.001")) == D("13.772")
    assert abs(dr["Q"]["plan_net"] - D("6.1324")) < D("0.001") and dr["Q"]["plan_periphery"].quantize(D("0.001")) == D("13.772")  # trimmed to P
    assert dr["R"]["team_area"].quantize(D("0.0001")) == D("16.9877") and dr["R"]["team_drawn"].quantize(D("0.001")) == D("15.786")
    assert dr["R"]["gap_mm"].quantize(D("1")) == 31  # drawn open: closed it is 15.817 m
    edges = {e["between"]: e for e in out["edges"] if e["how"] == "found along the outlines"}
    assert abs(edges["P|Q"]["length_m"] - D("5.19")) < D("0.001")  # an arc
    # c. heights: the pool 1,200 mm, R 900 mm (750 + 150), Q's slope line 2,997.84 mm
    assert dr["P"]["height_mm"] == 1200 and dr["R"]["height_mm"] == 900
    assert abs(dr["Q"]["slope_mm"] - D("2997.84")) < D("0.05")
    # d. the billing team's way reproduces their quantities
    items = {r["item"]: r for r in out["items"]}
    assert all(r["reproduced"] for r in items.values()), items
    assert items["1"]["team_total"] == D("1682.231") and items["3"]["team_total"] == D("1366.423") and items["2"]["team_total"] == 2
