# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Pricing fixes around the rate library, the BOQ knowledge library, PO freight and the estimate
(Prompt 38, invented data): library histories and merges keep each line's unit, the knowledge
match shows the median in the line's unit, unit fixes convert the cost too, a median of 0 or a
coverage bound of 0 never divides, PO freight added to cost is not booked to the site again, and
an estimate cut-out found after its host is not counted twice."""

import hashlib
from decimal import Decimal

import pytest

from app.estimate import demo
from app.estimate import library as est_lib
from app.knowledge import library as kn_library
from app.knowledge import routes as kn_routes
from app.knowledge import service as kn_service
from app.knowledge.models import KnowledgeLine
from app.knowledge.reader import _facts_of_line
from app.masters import library as lib
from app.masters.models import LibraryItem, LibraryLine, System
from app.masters.rate_policy import choose, load_histories
from app.sites.models import Site
from tests.test_finance import boss  # noqa: F401  (fixture)
from tests.test_material import (  # noqa: F401  (fixtures)
    approved_po,
    masters,
    receive,
    site,
    store_of,
)

D = Decimal


def _key(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


def _item(db, desc, unit, lines):
    """A library item with its priced lines: [(rate, unit, file)]."""
    item = LibraryItem(
        source_key=_key("item", desc, unit),
        match_key=_key("match", desc, unit),
        description=desc,
        unit=unit,
        unit_raw=unit,
    )
    db.add(item)
    db.flush()
    for rate, line_unit, file in lines:
        db.add(LibraryLine(source_key=_key("line", desc, unit, file, rate), library_item_id=item.id, file=file, description=desc,
                           unit=line_unit, unit_raw=line_unit, rate=D(rate), channel="Invented Channel"))  # fmt: skip
    db.flush()
    return item


# --- Part 2.4: library history mixing units -------------------------------------------------------


def test_a_sqft_line_counts_in_a_sqm_item_converted_not_as_it_is(db):
    """Rs 700/sqm + Rs 65/sqft: the median is near Rs 700/sqm (65 x 10.7639 = 699.65), not 382.50."""
    item = _item(
        db,
        "Invented terrace PU coating",
        "sqm",
        [("700", "sqm", "A/a.xlsx"), ("65", "sqft", "B/b.xlsx")],
    )
    h = load_histories(db, [item.id])[item.id]
    assert sorted(o.rate for o in h.lines) == [D("65") * D("10.7639"), D("700")]
    got = choose("median", h.lines).rate
    assert got.quantize(D("0.01")) == D("699.83")  # (699.6535 + 700) / 2; mixed it was 382.50


def test_a_line_whose_unit_cannot_be_converted_is_left_out(db):
    item = _item(
        db, "Invented pipe sleeve", "sqm", [("700", "sqm", "A/a.xlsx"), ("250", "nos", "B/b.xlsx")]
    )
    h = load_histories(db, [item.id])[item.id]
    assert [o.rate for o in h.lines] == [D("700")]


def test_merging_a_sqft_item_into_a_sqm_item_converts_its_lines(db):
    sqm = _item(db, "Invented basement coating", "sqm", [("700", "sqm", "A/a.xlsx")])
    sqft = _item(db, "Invented basement coating", "sqft", [("65", "sqft", "B/b.xlsx")])
    lib.merge(db, sqft, sqm)
    db.refresh(sqm)
    assert sqm.stats_from_lines and sqm.boq_count == 2
    assert (sqm.min_rate, sqm.median_rate, sqm.max_rate) == (
        D("699.6535"),
        D("699.8268"),
        D("700.0000"),
    )  # mixed: 65, 382.50, 700
    h = load_histories(db, [sqm.id])[sqm.id]
    assert choose("median", h.lines).rate.quantize(D("0.01")) == D("699.83")


def test_a_merge_across_units_that_do_not_convert_is_refused(db):
    sqm = _item(db, "Invented outlet treatment", "sqm", [("700", "sqm", "A/a.xlsx")])
    nos = _item(db, "Invented outlet treatment", "nos", [("250", "nos", "B/b.xlsx")])
    with pytest.raises(lib.MergeError, match="nos.*sqm"):
        lib.merge(db, nos, sqm)
    assert nos.merged_into_id is None


# --- Part 2.5: knowledge match median in the line's unit -------------------------------------------


@pytest.mark.parametrize(
    ("line_unit", "median", "unit"),
    [
        ("sqft", D("65.03"), "sqft"),
        ("Sft", D("65.03"), "sqft"),
        ("Sq. Ft.", D("65.03"), "sqft"),
        ("sqm", D("700"), "sqm"),
        (None, D("700"), "sqm"),
    ],
)
def test_the_match_median_is_shown_in_the_client_lines_unit(line_unit, median, unit):
    """A per-sqm median of Rs 700 next to a sqft line is Rs 65.03 per sqft (700 / 10.7639)."""
    assert kn_routes.median_in_line_unit(D("700"), "sqm", line_unit) == (median, unit)


def test_a_non_area_template_keeps_its_own_unit():
    assert kn_routes.median_in_line_unit(D("250"), "nos", "sqft") == (D("250"), "nos")
    assert kn_routes.median_in_line_unit(None, "sqm", "sqft") == (None, "sqft")


# --- Part 5: knowledge library units and a median of 0 ---------------------------------------------


def test_a_unit_fix_to_sq_ft_converts_the_cost_too(db):
    for i in range(5):
        db.add(
            KnowledgeLine(
                description=f"Invented terrace line {i}",
                unit="sqm",
                unit_raw="sqm",
                rate=D(700),
                rate_sqm=D(700),
                area_type="terrace",
            )
        )
    ln = KnowledgeLine(
        description="Invented terrace at 65",
        unit="sqm",
        unit_raw="",
        rate=D(65),
        rate_sqm=D(65),
        cost_sqm=D(52),
        margin_percent=D(20),
        area_type="terrace",
    )
    db.add(ln)
    db.flush()
    assert kn_library.check_units(db)["converted"] == 1
    assert ln.rate_sqm == D("699.65")  # 65 x 10.7639
    assert ln.cost_sqm == D("559.72")  # 52 x 10.7639 = 559.7228; it stayed 52 per "sqm"


def test_sft_converts_the_cost_like_sqft():
    ln = {"parent_item": None, "description": "Invented terrace coating", "remarks": None, "product_make": None, "unit": "sft", "unit_raw": "Sft",
          "rate": "65", "working": {"cost": "52", "margin_on_selling_percent": "20", "rate": "65"}}  # fmt: skip
    _facts_of_line(ln)
    assert ln["rate_sqm"] == D("699.65")
    assert ln["cost_sqm"] == D("559.72")  # it stayed 52 for "sft"


def test_a_past_median_of_zero_gives_no_gap_instead_of_an_error(db, monkeypatch):
    monkeypatch.setattr(kn_service, "near_median", lambda *a: (D(0), "everywhere"))

    class T:
        unit = "sqm"

    class G:
        rate_sqm = D(700)
        margin_percent = D(20)
        working_id = None
        cost_sqm = D(500)

    got = kn_service.gap_to_past(db, T(), G(), None)
    assert got["diff_percent"] is None and got["flagged"] is False


# --- Part 5: a coverage bound of 0 -----------------------------------------------------------------


def test_a_written_range_from_zero_sqm_per_kg_is_skipped():
    """0-4 sqm/kg cannot be turned into kg/sqm (1 / 0): the range is not judged."""
    assert est_lib._to_unit(D(0), D(4), "sqm/kg", "kg/sqm") is None
    assert est_lib._to_unit(D(2), D(4), "sqm/kg", "kg/sqm") == (D("0.25"), D("0.5"))


# --- Part 3.4: PO freight ---------------------------------------------------------------------------


def test_po_freight_added_to_cost_reaches_the_site_once(boss, masters, db):
    """PO Rs 10,000 + Rs 1,000 freight (added to cost), all received and issued to one site: the
    site's cost is Rs 11,000 (material at the landed rate), not 12,000 (and the freight again)."""
    from app.execution.service import actuals  # noqa: PLC0415

    client, h = boss
    products, (v_guj, _) = masters
    s = site(client, h, "Invented Freight Site")
    store = store_of(client, h, s["id"])
    po = approved_po(client, h, v_guj, store["id"], [{"product_id": products["T-CRYS"], "qty": "100", "rate": "100"}],
                     [{"kind": "freight", "amount": "1000"}])  # fmt: skip
    assert po["charges"][0]["add_to_cost"]
    grn = receive(client, h, po, [100])
    assert D(grn["lines"][0]["landed_rate"]) == 110
    r = client.post(
        "/api/material/issues",
        json={"site_id": s["id"], "lines": [{"product_id": products["T-CRYS"], "qty": "100"}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    cost = actuals(db, s["id"])
    assert cost["material"] == D("11000.00")
    assert sum(cost.values()) == D("11000.00")  # the freight is in the material's landed rate only


def test_po_freight_not_added_to_cost_is_booked_to_the_site(boss, masters, db):
    from app.execution.service import actuals  # noqa: PLC0415

    client, h = boss
    products, (v_guj, _) = masters
    s = site(client, h, "Invented Freight Site 2")
    store = store_of(client, h, s["id"])
    po = approved_po(client, h, v_guj, store["id"], [{"product_id": products["T-CRYS"], "qty": "100", "rate": "100"}],
                     [{"kind": "freight", "amount": "1000", "add_to_cost": False}])  # fmt: skip
    receive(client, h, po, [100])
    r = client.post(
        "/api/material/issues",
        json={"site_id": s["id"], "lines": [{"product_id": products["T-CRYS"], "qty": "100"}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    cost = actuals(db, s["id"])
    assert (cost["material"], cost["freight"]) == (D("10000.00"), D("1000.00"))


# --- Part 4.9: estimate cut-out found after its host ----------------------------------------------


def _rect(x, y, w, h):
    return [[x, y, 0], [x + w, y, 0], [x + w, y + h, 0], [x, y + h, 0]]


def test_a_host_added_after_its_cut_out_takes_it_out_of_its_floor(boss, db):
    """Shaft 5 sqm added first, terrace 100 sqm after: the terrace is 95 + the shaft's upturn, not 105."""
    c, h = boss
    ids = demo.library(db)
    pu = System(code="S-PU-CUT", name="Invented PU coating", unit="sqm", upturn_mm=D(300))
    st = Site(code="S-CUT-1", name="Invented shaft first", status="active")
    db.add_all([pu, st])
    db.commit()
    r = c.post(
        f"/api/measure/sites/{st.id}/areas",
        json={"outline": _rect(2, 2, 2, 2.5), "code": "SH", "name": "Shaft"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    e = c.post("/api/estimate/estimates", json={"site_id": st.id, "title": "Terrace"}, headers=h)
    assert e.status_code == 201, e.text
    e = c.post(
        f"/api/estimate/estimates/{e.json()['id']}/lines",
        json={"product_id": ids["Ultrathane"], "system_id": pu.id},
        headers=h,
    )
    assert e.status_code == 201, e.text
    e = e.json()
    assert [a["code"] for a in e["areas"]] == ["SH"] and e["areas"][0]["parent_id"] is None
    r = c.post(
        f"/api/measure/sites/{st.id}/areas",
        json={"outline": _rect(0, 0, 10, 10), "code": "TR", "name": "Terrace"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = c.post(f"/api/estimate/estimates/{e['id']}/areas", json={}, headers=h)
    assert r.status_code == 200, r.text
    e = c.get(f"/api/estimate/estimates/{e['id']}", headers=h).json()
    by = {a["code"]: a for a in e["areas"]}
    tr, sh = by["TR"], by["SH"]
    assert D(tr["floor_sqm"]) == 100 and D(tr["deduction_sqm"]) == 5
    assert (
        sh["parent_id"] == tr["id"]
        and sh["source"] == "misc"
        and sh["use_floor"] is False
        and sh["use_upturn"] is True
    )
    assert sh["name"].startswith("Misc: Shaft (cut out of TR")
    floors = {r["area_id"]: D(r["floor_sqm"]) for r in e["lines"][0]["rows"]}
    assert (
        floors[tr["id"]] == 95 and sum(floors.values()) == 95
    )  # 105 before: the shaft's floor counted twice
