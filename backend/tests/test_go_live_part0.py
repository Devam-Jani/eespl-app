# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Part 0 of the go-live review on invented data: the reconciliation's columns in the order a
store keeper reads them (issued, returned, net used, needed, excess or short), the rmt line's
products shown "to check" until its width is given, and the certificate signed by the
letterhead's chosen signatory with their designation (never a made-up "Authorised signatory")."""

import io
from decimal import Decimal

import openpyxl
from sqlalchemy import select

from app.closeout import completion as csvc
from app.finance.models import ContractLine
from app.masters.models import Product
from app.quotations.models import Letterhead
from app.team.models import Measurement
from tests.test_closeout import _give_system, measured, portal_site  # noqa: F401  (fixtures)
from tests.test_closeout_part0 import _accepted_wo
from tests.test_finance import boss, world  # noqa: F401  (fixtures)

D = Decimal


def test_the_reconciliation_reads_issued_returned_net_used_needed_and_an_rmt_line_waits_for_its_width(boss, measured, db):
    c, h = boss
    w = measured
    _give_system(db, w)  # PU coating: 1.5 kg per sqm
    _accepted_wo(db, w)  # the work order measures PU coating per rmt
    (f1, t1, b1), _ = w["flats"]
    r = c.post(f"/api/closeout/sites/{w['site']}/measurements", json={"description": "PU coating, balcony", "contract_line_id": w["pu"], "node_id": b1, "length_m": "3.6"}, headers=h)
    assert r.status_code == 201, r.text
    db.get(Measurement, r.json()["id"]).status = "approved"
    db.commit()
    p = db.scalar(select(Product).where(Product.name == "Invented PU coat"))
    rec = c.get(f"/api/closeout/sites/{w['site']}/reconciliation", headers=h).json()
    row = next(x for x in rec["rows"] if x["product_id"] == p.id)  # shown, not hidden
    keys = list(row)
    assert keys.index("issued") < keys.index("returned") < keys.index("net_used") < keys.index("needed") < keys.index("difference")
    assert row["state"] == "to check" and row["note"] == "to check: give the width" and "give the width" in row["basis"][0]
    assert [x["contract_line_id"] for x in rec["widths"]] == [w["pu"]] and rec["widths"][0]["width_m"] is None
    rec = c.put(f"/api/closeout/contract-lines/{w['pu']}/width", json={"width_m": "1.2"}, headers=h).json()
    row = next(x for x in rec["rows"] if x["product_id"] == p.id)
    assert D(str(row["needed"])) == D("6.480") and row["state"] == "short"  # 3.6 rmt x 1.2 m x 1.5 kg
    assert "3.600 rmt x 1.200 m wide" in row["basis"][0]
    assert D(str(db.get(ContractLine, w["pu"]).width_m)) == D("1.2")
    x = c.get(f"/api/closeout/sites/{w['site']}/reconciliation.xlsx", headers=h)
    header = next(openpyxl.load_workbook(io.BytesIO(x.content)).active.iter_rows(values_only=True))
    assert list(header[2:7]) == ["Issued (gross)", "Returned", "Net used", "Needed", "Excess (+) / short (-)"]


def test_the_certificate_names_the_chosen_signatory_with_the_designation(db):
    for other in db.scalars(select(Letterhead)):
        other.is_active = False  # the seeded letterheads: this one is the company's
    db.add(Letterhead(name="Invented head", company_name="Invented Applicators Pvt Ltd", signatory_firm="For INVENTED APPLICATORS PVT. LTD.",
                      signatory_name="Invented Signatory One", signatory_designation=None, is_active=True))  # fmt: skip
    db.commit()
    firm, name, role = csvc.signatory(db)
    assert (firm, name) == ("For INVENTED APPLICATORS PVT. LTD.", "Invented Signatory One")
    assert role == "Designation: ______________" and "Authorised signatory" not in role  # never made up
    head = db.scalar(select(Letterhead).where(Letterhead.name == "Invented head"))
    head.signatory_designation = "Director (Projects)"
    head.signatory2_name, head.signatory2_designation = "Invented Signatory Two", "Head of Quality"
    db.commit()
    assert csvc.signatory(db)[1:] == ("Invented Signatory One", "Director (Projects)")
    head.certificate_signatory = 2
    db.commit()
    assert csvc.signatory(db)[1:] == ("Invented Signatory Two", "Head of Quality")
