# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Part 0 of the close-out review on invented data: the accepted work order's unit rules the
measurement book, the bill and the certificate; sizes typed in feet and inches; the certificate's
system, stored quantities and real stage dates; one material-test line per spec; the demo
tender priced through the rate working."""

import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.closeout import completion as csvc
from app.closeout import sizes
from app.closeout import workorder as wsvc
from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine, WorkCompletion
from app.finance.models import ContractLine
from app.main import app
from app.masters.models import Product, System, SystemComponent
from app.methodology import site as msite
from app.models import User
from app.sites.models import AreaScope, StageTemplate, StageTemplateStep, Task
from app.team.models import Measurement
from app.tenders.models import BoqLine, Tender
from tests.test_closeout import _client_login, measured, portal_site  # noqa: F401  (fixtures)
from tests.test_finance import boss, world  # noqa: F401  (fixtures)

D = Decimal


def _accepted_wo(db, w, pu_unit="rmt", pu_rate="450", pu_qty="120") -> ClientWorkOrder:
    wo = ClientWorkOrder(code="CWO-2026-9101", client_ref="WO/INV/9", site_id=w["site"], client_id=w["client"], status="draft")
    wo.lines = [ClientWorkOrderLine(sort_order=0, description="PU coating", unit=pu_unit, qty=D(pu_qty), rate=D(pu_rate)),
                ClientWorkOrderLine(sort_order=1, description="Coving", unit="rmt", qty=D(50), rate=D(200))]  # fmt: skip
    db.add(wo)
    db.flush()
    wsvc.accept(db, wo, db.scalar(select(User).where(User.email == "boss@example.com")))
    db.commit()
    return wo


def _m(c, h, w, node, **body):
    return c.post(f"/api/closeout/sites/{w['site']}/measurements", json={"description": "PU coating", "contract_line_id": w["pu"], "node_id": node, **body}, headers=h)


def test_an_rmt_work_order_line_refuses_an_sqm_measurement_and_the_bill_and_certificate_use_rmt(boss, measured, db):
    c, h = boss
    w = measured
    _accepted_wo(db, w)
    cl = db.get(ContractLine, w["pu"])
    db.refresh(cl)
    assert (cl.unit, D(cl.rate), D(cl.qty), cl.wo_line_id is not None) == ("rmt", D("450"), D("120"), True)
    (f1, t1, b1), _ = w["flats"]
    r = _m(c, h, w, t1, length_m="3.6", breadth_m="1.2")
    assert r.status_code == 422 and "The work order WO/INV/9 measures 'PU coating' per rmt" in r.json()["detail"] and "not L x B" in r.json()["detail"]
    r = _m(c, h, w, t1, length_m="3.6", unit="sqm")
    assert r.status_code == 422 and "a measurement in sqm is refused" in r.json()["detail"]
    r = _m(c, h, w, b1, length_m="3.6")
    assert r.status_code == 201 and r.json()["unit"] == "rmt" and D(str(r.json()["qty"])) == D("3.600")
    db.get(Measurement, r.json()["id"]).status = "approved"
    db.commit()
    ra = c.post(f"/api/finance/contracts/{w['contract']['id']}/ra-bills", json={"period_to": "2026-10-31"}, headers=h).json()
    ln = next(x for x in ra["lines"] if x["contract_line_id"] == w["pu"])
    assert D(str(ln["suggested_qty"])) == D("3.600") and D(str(ln["rate"])) == D("450")
    sysm = System(code="INV-PU-R", name="Invented PU", unit="sqm")
    db.add(sysm)
    db.flush()
    db.get(BoqLine, cl.boq_line_id).system_id = sysm.id
    db.commit()
    wc = c.post(f"/api/closeout/sites/{w['site']}/work-completions", json={"completion_date": "2026-11-15", "guarantee_years": 10}, headers=h).json()
    assert [(a["unit"], a["qty"]) for a in wc["areas"]] == [("rmt", "3.600")]


def test_sizes_in_feet_and_inches_are_stored_in_metres_and_shown_both_ways(boss, measured, db):
    assert sizes.parse_length("19 ft 5 in") == (D("5.918"), "19 ft 5 in")
    assert sizes.parse_length("19' 5\"") == (D("5.918"), "19 ft 5 in")
    assert sizes.parse_length("5.918") == (D("5.918"), None) and sizes.parse_length("5.918 m") == (D("5.918"), None)
    assert sizes.shown(D("5.918"), "19 ft 5 in") == "19 ft 5 in = 5.918 m"
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    a = _m(c, h, w, t1, length_m="7 ft", breadth_m="1.5").json()
    assert a["entered"] == {"length_m": "7 ft"} and D(str(a["length_m"])) == D("2.134") and D(str(a["qty"])) == D("3.201")
    assert a["shown"]["length_m"] == "7 ft = 2.134 m"
    assert c.post(f"/api/closeout/sites/{w['site']}/measurement-sets", json={"ids": [a["id"]]}, headers=h).status_code == 200
    hh = _client_login(c, h, w["client"], [w["site"]], "billing-ft@example.com", ["billing"])
    r = TestClient(app).post(f"/api/portal/sites/{w['site']}/measurements/{a['id']}/correct", json={"field": "length_m", "new_value": "6 ft 10 in", "remark": "taped again"}, headers=hh)
    assert r.status_code == 200, r.text
    ch = r.json()["changes"][0]
    assert ch["old_shown"] == "7 ft = 2.134 m" and ch["new_shown"] == "6 ft 10 in = 2.083 m" and ch["new_text"] == "6 ft 10 in"
    out = c.post(f"/api/closeout/measurement-changes/{ch['id']}/answer", json={"accept": True}, headers=h).json()
    assert out["entered"] == {"length_m": "6 ft 10 in"} and D(str(out["qty"])) == D("3.125")  # the unit the client typed is kept
    x = c.get(f"/api/closeout/sites/{w['site']}/measurement-sheet.xlsx", headers=h)
    text = " ".join(str(v) for row in openpyxl.load_workbook(io.BytesIO(x.content)).active.iter_rows(values_only=True) for v in row if v is not None)
    assert "6 ft 10 in = 2.083 m" in text and "7 ft = 2.134 m" in text


def test_the_certificate_takes_the_system_from_the_stage_template_with_stored_quantities_and_real_stage_dates(boss, measured, db):
    c, h = boss
    w = measured
    (f1, t1, b1), _ = w["flats"]
    a = _m(c, h, w, t1, length_m="6.1", breadth_m="1.15").json()
    db.get(Measurement, a["id"]).status = "approved"
    p = Product(code="INV-PU-2", name="Invented PU coat", unit="kg")
    s = System(code="INV-PU-T", name="Invented PU from the template", unit="sqm")
    db.add_all([p, s])
    db.flush()
    db.add(SystemComponent(system_id=s.id, product_id=p.id, consumption_per_unit=D("1.5")))
    tpl = StageTemplate(name="Invented toilet PU", system_id=s.id)
    db.add(tpl)
    db.flush()
    steps = [StageTemplateStep(template_id=tpl.id, sort_order=i, name=n, weight_percent=D(50)) for i, n in enumerate(("Primer", "Coat"))]
    db.add_all(steps)
    db.flush()
    sc = AreaScope(site_id=w["site"], node_id=t1, stage_template_id=tpl.id, qty=D("7.015"), unit="sqm")
    db.add(sc)
    db.flush()
    db.add_all([Task(site_id=w["site"], node_id=t1, area_scope_id=sc.id, step_id=steps[0].id, name="Primer", actual_start=date(2026, 9, 2), actual_end=date(2026, 9, 2), status="done"),
                Task(site_id=w["site"], node_id=t1, area_scope_id=sc.id, step_id=steps[1].id, name="Coat", actual_start=date(2026, 9, 4), actual_end=date(2026, 9, 9), status="done")])  # fmt: skip
    db.commit()
    r = c.post(f"/api/closeout/sites/{w['site']}/work-completions", json={"completion_date": "2026-11-15", "guarantee_years": 10}, headers=h)
    assert r.status_code == 201, r.text
    area = r.json()["areas"][0]
    assert (area["qty"], area["system"], area["products"], area["from"], area["to"], area["dates_from"]) == (
        "7.015", "Invented PU from the template", ["Invented PU coat"], "2026-09-02", "2026-09-09", "stages")
    assert area["system_from"] == "stage template Invented toilet PU"
    page = csvc.html(db, db.get(WorkCompletion, r.json()["id"]))
    assert "7.015" in page and "7.02<" not in page and "02.09.2026 to 09.09.2026" in page
    assert "Schematic" in csvc.plan_svg(db, _site(db, w), db.get(WorkCompletion, r.json()["id"]))  # no drawing traced here


def _site(db, w):
    from app.sites.models import Site

    return db.get(Site, w["site"])


def test_material_tests_show_one_line_per_spec_with_its_sop_and_the_other_value_as_also_asked():
    rule_a = SimpleNamespace(document_id=1, system_type="acrylic_cementitious", min_specs=[
        {"property": "elongation", "label": "Elongation", "required": "min. 150%", "num": 150, "op": "min", "system_type": "acrylic_cementitious", "standard": "ASTM D 412", "page": 4},
        {"property": "tensile", "label": "Tensile strength", "required": "min. 1.5 MPa", "num": 1.5, "op": "min", "system_type": "acrylic_cementitious", "standard": "ASTM D412", "page": 8},
    ])  # fmt: skip
    rule_b = SimpleNamespace(document_id=2, system_type="acrylic_cementitious", min_specs=[
        {"property": "elongation", "label": "Elongation", "required": ">40 %", "num": 40, "op": "min", "system_type": "acrylic_cementitious", "standard": None, "page": 3},
    ])  # fmt: skip
    rows = msite.product_specs([rule_a, rule_b], "INVENTED GUARD PLUS acrylic cementitious", "coating", [], {1: "SOP INV-WP-04 R2", 2: "SOP INV-WP-07 R0"})
    assert [(r["property"], r["required"], r["source"]) for r in rows] == [
        ("Elongation", "min. 150%", "SOP INV-WP-04 R2, p.4"), ("Tensile strength", "min. 1.5 MPa", "SOP INV-WP-04 R2, p.8")]
    assert rows[0]["also"] == [{"required": ">40 %", "source": "SOP INV-WP-07 R0, p.3"}] and rows[1]["also"] == []
    assert all("note" not in r for r in rows)  # nothing inline: the other value is under "also asked"


def test_the_demo_tender_priced_through_the_rate_working_has_a_real_total(boss, db):
    from app.closeout.demo import price_through_working
    from app.masters.models import Client

    c, h = boss
    cl = Client(name="Invented Developer for pricing", state="Gujarat")
    p = Product(code="INV-FLEX", name="Invented flex coat", unit="kg")
    db.add_all([cl, p])
    db.flush()
    s = System(code="INV-FLEX-S", name="Invented flexible coating", unit="sqm")
    db.add(s)
    db.flush()
    db.add(SystemComponent(system_id=s.id, product_id=p.id, consumption_per_unit=D("1.2"), wastage_percent=D(5)))
    t = Tender(code="T-2026-9701", name="Invented priced tender", status="draft", client_id=cl.id)
    db.add(t)
    db.flush()
    db.add(BoqLine(tender_id=t.id, sort_order=1, client_item_no="1", description="Toilet waterproofing with flexible coating", unit="sqm", qty=D(40), system_id=s.id))
    db.commit()
    assert c.post(f"/api/prices/products/{p.id}", json={"rate": "185", "source": "manual"}, headers=h).status_code == 201
    out = price_through_working(c, h, t.id, {"toilet": s.id})
    assert D(str(out["quoted_total"])) > 0 and all(v and v > 0 for v in out["rates_sqm"].values())
    db.expire_all()
    line = db.scalar(select(BoqLine).where(BoqLine.tender_id == t.id))
    assert line.status == "priced" and line.rate and D(line.rate) > 0
