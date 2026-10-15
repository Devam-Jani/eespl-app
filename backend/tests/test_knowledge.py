# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""The BOQ knowledge library with invented BOQs (the real ones are company data and never
committed): reading a workbook whose rate cell is a formula into its Working sheet, QRO and NQ,
the requirements, the place and date; a broken file reported; similar lines grouped; rates by
city, region and all, old ones flagged; a fix needs a reason; proposing and filling a rate working
with the gap; learning from a final BOQ; matching a client BOQ; who sees what."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.knowledge import extract, library, service
from app.knowledge.models import KnowledgeFile, KnowledgeLine, KnowledgeTemplate
from app.knowledge.reader import read_file
from tests.conftest import login
from tests.test_finance import boss  # noqa: F401  (fixtures)
from tests.test_rate_working import _group, _working, boq  # noqa: F401  (fixtures)

SUNKEN = "Sunken toilet waterproofing: providing and applying two coats of crystalline waterproofing on the RCC slab, min 1.5 kg/sqm, with protection screed"


def d(v) -> Decimal:
    return Decimal(str(v))


def make_boq(path: Path) -> None:
    """An invented BOQ like ours: the client lines on "BOQ", the rate a formula into "Working"
    (surface preparation, the product at price + freight, labour as ₹/sq ft × 10.76, a total, a
    25 % margin on it, the rate). Saved by openpyxl: formulas without their values."""
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append(["Sr No", "Description", "Unit", "Qty", "Rate", "Amount", "Make", "Remarks"])
    ws.append(
        [
            1,
            SUNKEN,
            "Sqm",
            120,
            "=Working!E8",
            "=D2*E2",
            "Invented Crystal",
            "Surface preparation included",
        ]
    )
    ws.append(
        [2, "Terrace waterproofing with PU coating, 2 coats", "Sqm", "QRO", 950, None, None, None]
    )
    ws.append(
        [
            3,
            "Dismantling of the existing tiles and carting away",
            "Sqm",
            50,
            "Not quoted",
            None,
            None,
            "Client scope",
        ]
    )
    w = wb.create_sheet("Working")
    rows = {
        2: ("SP", 1, 80),
        3: ("Invented Crystal", 1.5, "=200+10"),
        4: ("Labour", 1, "=12*10.76"),
    }
    for r, (label, c, p) in rows.items():
        w[f"B{r}"], w[f"C{r}"], w[f"D{r}"], w[f"E{r}"] = label, c, p, f"=C{r}*D{r}"
    w["B5"], w["E5"] = "Total", "=SUM(E2:E4)"
    w["D6"], w["E6"] = 0.25, "=D6*E5"
    w["E8"] = "=SUM(E5:E6)"
    wb.save(path)


def test_reading_follows_the_rate_into_the_working_and_reads_requirements_place_and_date(tmp_path):
    root = tmp_path / "files"
    (root / "Invented Client").mkdir(parents=True)
    p = root / "Invented Client" / "EESPL_Invented Tower Shela_Waterproofing 15.03.2025.xlsx"
    make_boq(p)
    f = read_file(root, p, extract.DEFAULT_REGIONS)
    assert f.status == "read" and len(f.lines) == 3
    assert (f.city, f.region, f.place_source) == ("Shela", "Ahmedabad", "file name")
    assert f.on_date == date(2025, 3, 15) and f.date_source == "file name"
    sunk, terrace, nq = f.lines
    w = sunk["working"]
    assert w["sheet"] == "BOQ" and w["cell"] == "E2"
    items = {i["label"]: i for i in w["items"]}
    assert items["SP"]["kind"] == "surface_prep" and d(items["SP"]["amount"]) == 80
    crystal = items["Invented Crystal"]
    assert (
        crystal["kind"] == "product"
        and d(crystal["consumption"]) == d("1.5")
        and d(crystal["price"]) == 200
        and d(crystal["freight"]) == 10
    )
    assert (
        items["Labour"]["kind"] == "labour"
        and d(items["Labour"]["per_sqft"]) == 12
        and w["labour_sqft"] == "12"
    )
    cost = d(80) + d("1.5") * 210 + 12 * d("10.76")
    assert d(w["cost"]) == round(cost, 2) and d(w["margin_on_cost_percent"]) == 25
    assert d(w["margin_on_selling_percent"]) == 20  # 25 % on cost is 20 % of the selling price
    assert sunk["rate"] == round(cost * d("1.25"), 2) or abs(sunk["rate"] - cost * d("1.25")) < d(
        "0.01"
    )
    assert crystal["ref"] == "Working!E3"  # every fact links to its sheet and cell
    r = sunk["requirements"]
    assert (r["area_type"], r["surface"], r["coats"], r["min_kg_sqm"], r["protection"]) == (
        "sunken",
        "rcc",
        2,
        "1.5",
        "screed",
    )
    assert "crystalline" in r["families"]
    assert (
        terrace["qty_note"] == "QRO"
        and terrace["rate"] == 950
        and terrace["requirements"]["coats"] == 2
    )
    assert nq["qty_note"] == "NQ"


def test_a_broken_file_is_reported_and_the_reading_goes_on(tmp_path, db, monkeypatch):
    root = tmp_path / "files"
    root.mkdir()
    make_boq(root / "EESPL_Invented Jamnagar Terrace.xlsx")
    (root / "broken.xlsx").write_bytes(b"this is not a workbook")
    monkeypatch.setattr(library, "root", lambda: root)
    report = library.run(db, workers=2)
    assert report["files_by_status"] == {"read": 1, "failed": 1}
    assert report["failed"][0]["path"] == "broken.xlsx" and report["failed"][0]["error"]
    assert (
        report["lines"] == 3
        and report["lines_with_working"] == 1
        and report["lines_with_place"] == 3
    )
    line = db.scalar(select(KnowledgeLine).where(KnowledgeLine.working.is_not(None)))
    assert line.city == "Jamnagar" and line.region == "Saurashtra" and line.margin_percent == 20


def _line(db, desc, city, rate, on, folder="Invented Client", **kw):
    f = KnowledgeFile(
        path=f"invented/{desc[:20]}/{city}/{rate}/{on}.xlsx",
        kind="xlsx",
        status="read",
        folder=folder,
        city=city,
        region=service.region_of(db, city),
    )
    db.add(f)
    db.flush()
    req = extract.requirements(desc)
    ln = KnowledgeLine(file_id=f.id, sheet="BOQ", row=2, description=desc, unit="sqm", rate=d(rate), rate_sqm=d(rate), area_type=req.area_type,
                       surface=req.surface, coats=req.coats, min_kg_sqm=req.min_kg_sqm, dft_mm=req.dft_mm, requirements=req.as_dict(),
                       city=city, region=f.region, on_date=on, folder=folder, **kw)  # fmt: skip
    db.add(ln)
    db.flush()
    return ln


@pytest.fixture
def library_lines(db):
    today = date.today()
    lines = [
        _line(db, SUNKEN, "Shela", 640, today - timedelta(days=40)),
        _line(
            db,
            SUNKEN.replace("Sunken toilet", "Sunken toilet of tower B"),
            "Bopal",
            700,
            today - timedelta(days=100),
        ),
        _line(
            db,
            SUNKEN + " as approved",
            "Jamnagar",
            560,
            today - timedelta(days=800),
            folder="Invented Channel",
        ),
        _line(
            db,
            "Terrace waterproofing with PU coating, 2 coats over the RCC roof slab",
            "Rajkot",
            900,
            today - timedelta(days=30),
        ),
    ]
    db.commit()
    return lines


def test_similar_lines_group_into_one_template_and_rates_go_city_region_all_with_old_flagged(
    library_lines, db
):
    made = library.group(db)
    db.commit()
    assert made == 2
    sunk = db.get(KnowledgeTemplate, library_lines[0].template_id)
    assert {ln.template_id for ln in library_lines[:3]} == {sunk.id} and library_lines[
        3
    ].template_id != sunk.id
    assert (
        sunk.name.startswith("Sunken area, RCC, 2 coats crystalline") and "1.5 kg/sqm" in sunk.name
    )
    assert (
        sunk.files_count == 3 and sunk.median_rate == 640 and sunk.steps
    )  # the method statement from a stage template
    r = service.rates(db, sunk, "Shela")
    assert r["region"] == "Ahmedabad"
    assert (r["city_stats"]["n"], r["region_stats"]["n"], r["all_stats"]["n"]) == (1, 2, 3)
    assert r["region_stats"]["median"] == 670 and r["all_stats"]["latest"]["city"] == "Shela"
    old = next(x for x in r["rows"] if x["city"] == "Jamnagar")
    assert (
        old["old"] and not next(x for x in r["rows"] if x["city"] == "Shela")["old"]
    )  # older than 12 months: flagged


def test_a_fix_by_hand_needs_a_reason_and_is_kept(boss, library_lines, db):
    c, h = boss
    library.group(db)
    db.commit()
    ln = library_lines[0]
    r = c.put(f"/api/knowledge/lines/{ln.id}", json={"field": "rate", "value": "660"}, headers=h)
    assert r.status_code == 422
    r = c.put(
        f"/api/knowledge/lines/{ln.id}",
        json={"field": "rate", "value": "660", "reason": "Invented: the BOQ was revised to 660"},
        headers=h,
    )
    assert r.status_code == 200 and d(r.json()["rate"]) == 660
    t = c.get(f"/api/knowledge/templates/{ln.template_id}", headers=h).json()
    assert t["median_rate"] in ("660.00", 660.0, "660")
    r = c.put(f"/api/knowledge/templates/{ln.template_id}", json={"coats": 3}, headers=h)
    assert r.status_code == 422  # a value: with a reason
    r = c.put(
        f"/api/knowledge/templates/{ln.template_id}",
        json={"name": "Sunken toilet, RCC, crystalline 2 coats"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["reviewed"]  # a rename: no reason needed, logged


def test_picking_area_surface_and_requirements_proposes_the_template_and_fills_the_working(
    boss, boq, db
):
    c, h = boss
    hdpe, primer = boq["products"]
    today = date.today()
    working = {"items": [
        {"label": "Invented HDPE membrane", "kind": "product", "consumption": "1.4", "price": "250", "freight": "6", "ref": "Working!E3"},
        {"label": "Invented primer", "kind": "product", "consumption": "0.25", "price": "80", "freight": None, "ref": "Working!E4"},
    ], "labour_sqft": "14", "surface_prep_sqm": "40", "cost": "600", "margin_on_selling_percent": "22"}  # fmt: skip
    for city, rate in (("Shela", 560), ("Bopal", 590), ("Sanand", 575)):
        _line(db, "Raft waterproofing with HDPE membrane below the raft on PCC, 2 coats of primer", city, rate, today - timedelta(days=60),
              working=working, cost_sqm=d(600), margin_percent=d(22))  # fmt: skip
    db.commit()
    library.group(db)
    db.commit()
    found = c.post(
        "/api/knowledge/propose",
        json={"area_type": "raft", "surface": "rcc", "city": "Shela"},
        headers=h,
    ).json()
    best = found["templates"][0]
    assert best["area_type"] == "raft" and found["region"] == "Ahmedabad"
    assert best["rates"]["city_stats"]["n"] == 1 and best["rates"]["region_stats"]["n"] == 3
    assert [p["label"] for p in best["products"]["products"]][:2] == [
        "Invented HDPE membrane",
        "Invented primer",
    ]
    assert best["margins"]["all"]["median"] == 22
    w = _working(c, h, boq)
    raft = _group(c.post(f"/api/rate-working/{w['id']}/suggest", headers=h).json(), "raft")
    r = c.post(
        f"/api/knowledge/groups/{raft['id']}/apply",
        json={"template_id": best["id"], "city": "Shela"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    g = r.json()["group"]
    p = next(x for x in g["products"] if x["product_id"] == hdpe)
    assert d(p["consumption"]) == d("1.4") and p["consumption_source"].startswith("old BOQ")
    assert (
        d(g["margin_percent"]) == 22
        and g["margin_basis"] == "selling"
        and d(g["labour_used_sqft"]) == 14
    )
    gap = r.json()["gap"]
    assert d(gap["median"]) == 575 and gap["where"] == "in Ahmedabad" or gap["where"] == "in Shela"
    assert gap["flagged"] == (abs(d(gap["diff_percent"])) > 15) and (
        not gap["flagged"] or gap["reasons"]
    )
    # a BOQ marked final teaches the library
    n = c.post(f"/api/knowledge/learn/workings/{w['id']}", headers=h).json()["lines"]
    assert (
        n >= 1 and db.scalar(select(KnowledgeLine).where(KnowledgeLine.source == "won")) is not None
    )
    # the client's own BOQ, matched line by line with a confidence
    m = c.get(f"/api/knowledge/match/tenders/{boq['tender']}", headers=h).json()
    raft_lines = [x for x in m["lines"] if "Raft" in x["description"]]
    assert (
        raft_lines
        and raft_lines[0]["template"]["area_type"] == "raft"
        and Decimal(str(raft_lines[0]["confidence"])) > 0
    )
    r = c.put(
        f"/api/knowledge/match/{raft_lines[0]['match_id']}",
        json={"status": "accepted", "template_id": raft_lines[0]["template"]["id"]},
        headers=h,
    )
    assert r.json()["status"] == "accepted"


def test_sales_see_rates_but_never_cost_or_margin_and_a_client_gets_403(
    library_lines, db, login_as, make_user, client
):
    library.group(db)
    db.commit()
    c, h = login_as("sales")
    tid = library_lines[0].template_id
    t = c.get(f"/api/knowledge/templates/{tid}", headers=h).json()
    assert t["rates"]["rows"] and "products" not in t and "margins" not in t and not t["sees_cost"]
    assert all("cost" not in r and "margin_percent" not in r for r in t["rates"]["rows"])
    lines = c.get(f"/api/knowledge/templates/{tid}/lines", headers=h).json()
    assert lines and all("working" not in x and "margin_percent" not in x for x in lines)
    assert (
        c.put(
            f"/api/knowledge/lines/{lines[0]['id']}",
            json={"field": "rate", "value": "1", "reason": "invented"},
            headers=h,
        ).status_code
        == 403
    )
    found = c.post("/api/knowledge/propose", json={"area_type": "sunken"}, headers=h).json()[
        "templates"
    ]
    assert found and "products" not in found[0] and "margins" not in found[0]
    make_user("client@example.com", "client")
    hc = login(client, "client@example.com")
    for path in (
        "/api/knowledge/report",
        f"/api/knowledge/templates/{tid}",
        "/api/knowledge/options",
    ):
        assert client.get(path, headers=hc).status_code == 403
