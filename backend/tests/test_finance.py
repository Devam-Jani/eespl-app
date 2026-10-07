"""Finance: RA bills, invoices and numbering, receipts and ageing, vendor bills and payments,
subcontractor bills, petty cash, payroll, site profit, Tally XML, permissions. Invented data."""

import uuid
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import settings
from app.execution import service as ex
from app.execution.models import StaffAttendance
from app.finance.models import Payslip
from app.masters.models import Client, CompanyGstin, Product, Vendor
from app.models import User
from app.sites.models import AreaScope, Site, SiteNode, StageTemplate
from app.tenders.models import BoqLine, Tender
from tests.conftest import login

D = Decimal
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def uid(db, email):
    return str(db.scalar(select(User.id).where(User.email == email)))


@pytest.fixture
def world(boss, db):
    """A client in Gujarat, our Gujarat GSTIN, a won tender with two BOQ lines, its site, and
    area scopes with progress: PU coating 70 of 100 sqm done, coving 10 of 50 rmt."""
    client, h = boss
    cl = Client(
        name="Invented Builders", gstin="24AAACI1111A1Z1", state="Gujarat", address="Invented Road"
    )
    db.add_all(
        [
            cl,
            CompanyGstin(
                gstin="24AAACE1234A1Z1", state="Gujarat", address="Our office", is_default=True
            ),
        ]
    )
    db.flush()
    t = Tender(code="T-2026-9001", name="Invented tower", status="won", client_id=cl.id)
    db.add(t)
    db.flush()
    l1 = BoqLine(
        tender_id=t.id,
        sort_order=1,
        client_item_no="1",
        description="PU coating",
        unit="sqm",
        qty=100,
        rate=500,
        cost_rate=320,
    )
    l2 = BoqLine(
        tender_id=t.id,
        sort_order=2,
        client_item_no="2",
        description="Coving",
        unit="rmt",
        qty=50,
        rate=200,
    )
    db.add_all([l1, l2])
    db.commit()
    s = client.post(
        "/api/sites",
        json={
            "name": "Invented Tower Site",
            "client_id": cl.id,
            "state": "Gujarat",
            "start_date": "2026-09-01",
        },
        headers=h,
    ).json()
    site = db.get(Site, s["id"])
    site.tender_id, site.status = t.id, "active"
    node = SiteNode(site_id=site.id, kind="terrace", name="Terrace")
    db.add(node)
    db.flush()
    tpl = db.scalars(select(StageTemplate)).first()
    scopes = [
        AreaScope(
            site_id=site.id,
            node_id=node.id,
            boq_line_id=l1.id,
            stage_template_id=tpl.id,
            qty=60,
            progress_percent=50,
        ),
        AreaScope(
            site_id=site.id,
            node_id=node.id,
            boq_line_id=l1.id,
            stage_template_id=tpl.id,
            qty=40,
            progress_percent=100,
        ),
        AreaScope(
            site_id=site.id,
            node_id=node.id,
            boq_line_id=l2.id,
            stage_template_id=tpl.id,
            qty=50,
            progress_percent=20,
        ),
    ]
    db.add_all(scopes)
    db.commit()
    return {
        "client": cl.id,
        "site": site.id,
        "site_code": site.code,
        "scopes": [x.id for x in scopes],
    }


def contract(client, h, w, **terms):
    body = {
        "retention_percent": "5",
        "advance_amount": "10000",
        "advance_recovery_percent": "10",
        **terms,
    }
    r = client.post(f"/api/finance/sites/{w['site']}/contract", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def lines_by_desc(bill):
    return {ln["description"]: ln for ln in bill["lines"]}


def certified_ra(client, h, w, cut=None):
    c = contract(client, h, w)
    ra = client.post(
        f"/api/finance/contracts/{c['id']}/ra-bills", json={"period_to": "2026-09-30"}, headers=h
    ).json()
    client.post(f"/api/finance/ra-bills/{ra['id']}/submit", headers=h)
    ln = lines_by_desc(ra)
    body = {
        "lines": [
            {"contract_line_id": ln["PU coating"]["contract_line_id"], "certified_qty": cut or "65"}
        ],
        "certified_by_client": "Invented PMC",
    }
    r = client.post(f"/api/finance/ra-bills/{ra['id']}/certify", json=body, headers=h)
    assert r.status_code == 200, r.text
    return c, r.json()


def invoiced(client, h, w, on="2026-10-07"):
    c, ra = certified_ra(client, h, w)
    r = client.post(
        f"/api/finance/ra-bills/{ra['id']}/invoice", json={"invoice_date": on}, headers=h
    )
    assert r.status_code == 201, r.text
    return c, ra, r.json()


# --- RA bills ------------------------------------------------------------------------------------


def test_ra_bill_from_progress_with_previous_cumulative_extra_and_deductions(
    boss, world, db, login_as
):
    client, h = boss
    c = contract(client, h, world)
    assert len(c["lines"]) == 2 and D(c["contract_value"]) == 60000  # 100 x 500 + 50 x 200
    ra = client.post(
        f"/api/finance/contracts/{c['id']}/ra-bills", json={"period_to": "2026-09-30"}, headers=h
    ).json()
    assert ra["code"] == f"RA-{world['site_code']}-01"
    ln = lines_by_desc(ra)
    assert (
        D(ln["PU coating"]["suggested_qty"]) == 70 and D(ln["Coving"]["suggested_qty"]) == 10
    )  # from progress
    assert D(ra["gross"]) == 37000  # 70 x 500 + 10 x 200
    assert (
        D(ra["retention"]) == 1850 and D(ra["advance_recovery"]) == 3700 and D(ra["net"]) == 31450
    )
    over = {"lines": [{"contract_line_id": ln["PU coating"]["contract_line_id"], "qty": "120"}]}
    r = client.put(f"/api/finance/ra-bills/{ra['id']}", json=over, headers=h)
    assert r.status_code == 422 and "beyond the BOQ" in r.json()["detail"]

    # the client cuts PU coating to 65: both figures are kept, deductions follow the certified
    client.post(f"/api/finance/ra-bills/{ra['id']}/submit", headers=h)
    r = client.post(
        f"/api/finance/ra-bills/{ra['id']}/certify",
        json={
            "lines": [
                {"contract_line_id": ln["PU coating"]["contract_line_id"], "certified_qty": "65"}
            ]
        },
        headers=h,
    )
    ra = r.json()
    assert D(ra["gross"]) == 37000 and D(ra["certified_gross"]) == 34500
    assert (
        D(ra["retention"]) == D("1725")
        and D(ra["advance_recovery"]) == 3450
        and D(ra["net"]) == 29325
    )

    # bill 2: progress moved on; previous = certified 65, so 35 is suggested
    db.get(AreaScope, world["scopes"][0]).progress_percent = 100
    db.commit()
    ra2 = client.post(f"/api/finance/contracts/{c['id']}/ra-bills", json={}, headers=h).json()
    pu = lines_by_desc(ra2)["PU coating"]
    assert (
        D(pu["previous_qty"]) == 65
        and D(pu["suggested_qty"]) == 35
        and D(pu["cumulative_qty"]) == 100
    )
    assert D(lines_by_desc(ra2)["Coving"]["suggested_qty"]) == 0
    r = client.put(
        f"/api/finance/ra-bills/{ra2['id']}",
        json={"lines": [{"contract_line_id": pu["contract_line_id"], "qty": "40"}]},
        headers=h,
    )
    assert r.status_code == 422  # 65 + 40 > 100: needs an extra item

    c = client.post(
        f"/api/finance/contracts/{c['id']}/extra-items",
        json={
            "description": "Extra PU on the lift machine room",
            "unit": "sqm",
            "qty": "10",
            "rate": "300",
        },
        headers=h,
    ).json()
    extra = next(x for x in c["lines"] if x["is_extra"])
    body = {
        "lines": [
            {"contract_line_id": pu["contract_line_id"], "qty": "35"},
            {"contract_line_id": extra["id"], "qty": "10"},
        ]
    }
    assert (
        client.put(f"/api/finance/ra-bills/{ra2['id']}", json=body, headers=h).status_code == 422
    )  # not approved
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert (
        acc.post(f"/api/finance/contract-lines/{extra['id']}/approve", headers=ah).status_code
        == 403
    )
    assert (
        client.post(f"/api/finance/contract-lines/{extra['id']}/approve", headers=h).status_code
        == 200
    )
    ra2 = client.put(f"/api/finance/ra-bills/{ra2['id']}", json=body, headers=h).json()
    assert D(ra2["gross"]) == 20500  # 35 x 500 + 10 x 300
    assert D(ra2["advance_recovery"]) == 2050  # 10 %, within the 6,550 still to recover


# --- invoices ------------------------------------------------------------------------------------


def test_invoice_gst_by_place_of_supply_numbering_and_credit_note(boss, world, db):
    client, h = boss
    c, ra, inv = invoiced(client, h, world)
    assert inv["number"] == "EESPL/26-27/0001" and len(inv["number"]) <= 16
    assert not inv["interstate"]
    assert (
        D(inv["taxable"]) == 34500 and D(inv["cgst"]) == D("3105") and D(inv["sgst"]) == D("3105")
    )
    assert D(inv["igst"]) == 0 and D(inv["total"]) == 40710
    assert client.get(f"/api/finance/ra-bills/{ra['id']}", headers=h).json()["status"] == "invoiced"
    pdf = client.get(f"/api/finance/invoices/{inv['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    other = Client(name="Invented Mumbai Client", gstin="27AAACM2222B1Z2", state="Maharashtra")
    db.add(other)
    db.commit()
    line = [{"description": "Waterproofing consultancy", "amount": "10000", "gst_percent": "18"}]
    a = client.post(
        "/api/finance/invoices",
        json={"client_id": other.id, "invoice_date": "2027-03-31", "lines": line},
        headers=h,
    ).json()
    b = client.post(
        "/api/finance/invoices",
        json={"client_id": other.id, "invoice_date": "2027-04-01", "lines": line},
        headers=h,
    ).json()
    assert (a["number"], b["number"]) == ("EESPL/26-27/0002", "EESPL/27-28/0001")  # FY rollover
    assert a["interstate"] and D(a["igst"]) == 1800 and D(a["cgst"]) == 0

    r = client.post(
        f"/api/finance/invoices/{inv['id']}/credit-note",
        json={"taxable": "1000", "reason": "Rate revised"},
        headers=h,
    )
    assert r.status_code == 201
    inv2 = r.json()
    assert inv2["credit_notes"][0]["number"] == "CN/26-27/0001" and D(inv2["credited"]) == 1180
    # outstanding = 40,710 - advance recovery 3,450 - credit 1,180
    assert D(inv2["outstanding"]) == D("36080")


# --- receipts, ageing, retention -----------------------------------------------------------------


def test_receipt_with_tds_ageing_and_retention_release(boss, world, db):
    client, h = boss
    on = ex.today() - timedelta(days=45)
    c, ra, inv = invoiced(client, h, world, on=str(on))
    assert (
        D(inv["outstanding"]) == 37260
        and D(inv["retention_held"]) == 1725
        and D(inv["due"]) == 35535
    )
    r = client.post(
        "/api/finance/receipts",
        json={
            "client_id": world["client"],
            "mode": "neft",
            "ref_no": "UTR123",
            "amount": "34000",
            "tds_amount": "690",
            "gst_tds_amount": "345",
            "allocations": [{"invoice_id": inv["id"], "amount": "35000"}],
        },
        headers=h,
    )
    assert r.status_code == 422  # the allocation must cover received + TDS + GST TDS
    r = client.post(
        "/api/finance/receipts",
        json={
            "client_id": world["client"],
            "mode": "neft",
            "ref_no": "UTR123",
            "amount": "34000",
            "tds_amount": "690",
            "gst_tds_amount": "345",
            "allocations": [{"invoice_id": inv["id"], "amount": "35035"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["number"].startswith("RCT/26-27/")
    age = client.get("/api/finance/ageing", headers=h).json()
    row = age["rows"][0]
    assert D(row["31-60"]) == 500 and D(row["due"]) == 500 and D(row["retention_held"]) == 1725

    ret = client.get(f"/api/finance/sites/{world['site']}/retention", headers=h).json()
    assert D(ret["held"]) == 1725
    assert (
        client.post(
            f"/api/finance/sites/{world['site']}/retention-release",
            json={"amount": "2000"},
            headers=h,
        ).status_code
        == 422
    )
    client.post(
        f"/api/finance/sites/{world['site']}/retention-release", json={"amount": "1725"}, headers=h
    )
    inv = client.get(f"/api/finance/invoices/{inv['id']}", headers=h).json()
    assert D(inv["due"]) == 2225 and D(inv["retention_held"]) == 0
    client.post(
        "/api/finance/receipts",
        json={
            "client_id": world["client"],
            "amount": "2225",
            "is_retention": True,
            "allocations": [{"invoice_id": inv["id"], "amount": "2225"}],
        },
        headers=h,
    )
    assert D(client.get(f"/api/finance/invoices/{inv['id']}", headers=h).json()["outstanding"]) == 0
    ledger = client.get(f"/api/finance/clients/{world['client']}/ledger", headers=h).json()
    assert D(ledger["balance"]) == 0


# --- vendor bills and payments -------------------------------------------------------------------


def grn_for(client, h, db, vendor_id, qty="100", rate="50"):
    p = Product(
        code=f"T-{uuid.uuid4().hex[:6]}",
        name="Test primer",
        unit="ltr",
        gst_percent=18,
        hsn_code="3208",
    )
    db.add(p)
    db.commit()
    gd = next(
        s for s in client.get("/api/material/stores", headers=h).json() if s["kind"] == "godown"
    )["id"]
    po = client.post(
        "/api/material/pos",
        json={
            "vendor_id": vendor_id,
            "store_id": gd,
            "lines": [{"product_id": p.id, "qty": qty, "rate": rate}],
        },
        headers=h,
    ).json()
    client.post(f"/api/material/pos/{po['id']}/submit", headers=h)
    g = client.post(
        "/api/material/grns",
        json={
            "po_id": po["id"],
            "submit": True,
            "lines": [{"po_line_id": po["lines"][0]["id"], "received_qty": qty}],
        },
        headers=h,
    ).json()
    client.post(f"/api/material/grns/{g['id']}/approve", headers=h)
    return g


def test_vendor_bill_match_tds_partial_payment_and_approval_limit(boss, world, db, login_as):
    client, h = boss
    sup = Vendor(
        name="Invented Chem Supplier",
        type="material_supplier",
        gstin="24ABCFD1234E1Z5",
        pan="ABCFD1234E",
    )
    trans = Vendor(
        name="Invented Transport", type="transporter", pan="ABCPD1234E", payment_terms_days=7
    )
    db.add_all([sup, trans])
    db.commit()
    g = grn_for(client, h, db, sup.id)
    gl = g["lines"][0]
    r = client.post(
        "/api/finance/vendor-bills",
        json={
            "vendor_id": sup.id,
            "bill_no": "INV-77",
            "bill_date": "2026-10-07",
            "grn_ids": [g["id"]],
            "grn_lines": [{"grn_line_id": gl["id"], "rate": "52"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    bill = r.json()
    assert [i["kind"] for i in bill["match_issues"]] == ["rate"]  # 52 vs PO 50: 4 % > 1 %
    assert bill["tds_section"] == "194Q" and D(bill["tds_amount"]) == D("5.20")  # 0.1 % of 5,200
    assert D(bill["total"]) == 6136 and D(bill["payable"]) == D("6130.80")
    assert (
        client.post(
            f"/api/finance/vendor-bills/{bill['id']}/approve", json={}, headers=h
        ).status_code
        == 422
    )
    bill = client.post(
        f"/api/finance/vendor-bills/{bill['id']}/approve",
        json={"accept_differences": True},
        headers=h,
    ).json()
    assert bill["status"] == "approved"
    pay = client.post(
        "/api/finance/payments",
        json={
            "vendor_id": sup.id,
            "allocations": [{"vendor_bill_id": bill["id"], "amount": "2000"}],
        },
        headers=h,
    ).json()
    assert pay["status"] == "paid" and pay["number"].startswith("PAY/26-27/")
    bill = client.get(f"/api/finance/vendor-bills/{bill['id']}", headers=h).json()
    assert bill["status"] == "partly_paid" and D(bill["outstanding"]) == D("4130.80")
    r = client.post(
        "/api/finance/payments",
        json={
            "vendor_id": sup.id,
            "allocations": [{"vendor_bill_id": bill["id"], "amount": "5000"}],
        },
        headers=h,
    )
    assert r.status_code == 422  # more than outstanding

    # a direct transporter bill: 194C at 1 % (individual PAN), due by the payment terms
    tb = client.post(
        "/api/finance/vendor-bills",
        json={
            "vendor_id": trans.id,
            "kind": "freight",
            "bill_no": "LR-9",
            "bill_date": "2026-10-07",
            "lines": [
                {"description": "Freight Ahmedabad to site", "rate": "150000", "gst_percent": "0"}
            ],
        },
        headers=h,
    ).json()
    assert (
        tb["tds_section"] == "194C"
        and D(tb["tds_amount"]) == 1500
        and tb["due_date"] == "2026-10-14"
    )
    client.post(f"/api/finance/vendor-bills/{tb['id']}/approve", json={}, headers=h)
    acc, ah = login_as("accounts", email="accounts@example.com")
    pay = acc.post(
        "/api/finance/payments",
        json={
            "vendor_id": trans.id,
            "allocations": [{"vendor_bill_id": tb["id"], "amount": "120000"}],
        },
        headers=ah,
    ).json()
    assert pay["status"] == "pending_approval"  # above the ₹1,00,000 limit
    assert acc.post(f"/api/finance/payments/{pay['id']}/approve", headers=ah).status_code == 403
    off, oh = login_as("office_admin", email="office@example.com")
    assert (
        off.post(f"/api/finance/payments/{pay['id']}/approve", headers=oh).json()["status"]
        == "paid"
    )
    due = client.get("/api/finance/payables/due", params={"days": 30}, headers=h).json()
    assert {d["vendor_name"] for d in due} == {"Invented Chem Supplier", "Invented Transport"}
    ageing = client.get("/api/finance/payables/ageing", headers=h).json()
    assert D(ageing["totals"]["total"]) == D("4130.80") + D("148500") - 120000


# --- subcontractor RA bills ----------------------------------------------------------------------


def test_subcon_bill_material_recovery_retention_and_nothing_twice(boss, world, db):
    client, h = boss
    sub = Vendor(name="Invented Applicators", type="subcontractor", pan="ABCPD9999Z")
    p = Product(code="T-PU2", name="Test PU", unit="ltr", gst_percent=18)
    db.add_all([sub, p])
    db.commit()
    site, st = world["site"], None
    st = client.get("/api/material/stores", params={"site_id": site}, headers=h).json()[0]["id"]
    client.post(
        f"/api/material/stores/{st}/adjust",
        json={"product_id": p.id, "qty": "20", "rate": "200", "kind": "opening", "note": "Opening"},
        headers=h,
    )
    r = client.post(
        "/api/material/issues",
        json={
            "site_id": site,
            "subcontractor_id": sub.id,
            "lines": [{"product_id": p.id, "qty": "5"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    wo = client.post(
        "/api/execution/work-orders",
        json={
            "site_id": site,
            "subcontractor_id": sub.id,
            "material_by": "eespl",
            "retention_percent": "5",
            "lines": [{"description": "Coating labour", "unit": "sqm", "qty": "100", "rate": "50"}],
        },
        headers=h,
    ).json()
    client.post(f"/api/execution/work-orders/{wo['id']}/approve", headers=h)
    wo = client.post(
        f"/api/execution/work-orders/{wo['id']}/lines/{wo['lines'][0]['id']}/measurements",
        json={"qty": "60"},
        headers=h,
    ).json()
    m = wo["lines"][0]["measurements"][0]["id"]
    client.post(f"/api/execution/measurements/{m}/verify", headers=h)
    billable = client.get(f"/api/finance/work-orders/{wo['id']}/billable", headers=h).json()
    assert D(billable["material_to_recover"]) == 1000 and len(billable["measurements"]) == 1
    sb = client.post(f"/api/finance/work-orders/{wo['id']}/subcon-bills", json={}, headers=h).json()
    assert (
        D(sb["gross"]) == 3000 and D(sb["retention"]) == 150 and D(sb["tds"]) == 30
    )  # 5 %, 1 % (individual)
    assert D(sb["material_recovery"]) == 1000 and D(sb["gst"]) == 0  # unregistered: no GST
    assert D(sb["net"]) == 1820  # 3,000 - 150 - 30 - 1,000
    assert (
        client.post(
            f"/api/finance/work-orders/{wo['id']}/subcon-bills", json={}, headers=h
        ).status_code
        == 422
    )
    sb = client.post(f"/api/finance/subcon-bills/{sb['id']}/approve", headers=h).json()
    vb = client.get(f"/api/finance/vendor-bills/{sb['vendor_bill_id']}", headers=h).json()
    assert vb["kind"] == "subcontract" and D(vb["payable"]) == 1820 and vb["status"] == "approved"
    rel = client.post(
        f"/api/finance/work-orders/{wo['id']}/retention-release", json={"amount": "150"}, headers=h
    ).json()
    assert D(rel["released"]) == 150
    assert (
        client.post(
            f"/api/finance/work-orders/{wo['id']}/retention-release",
            json={"amount": "1"},
            headers=h,
        ).status_code
        == 422
    )


# --- petty cash ----------------------------------------------------------------------------------


def test_petty_cash_balance_photo_limit_and_budget(boss, world, db, make_user):
    client, h = boss
    make_user("sup@example.com", "site_supervisor")
    make_user("sup2@example.com", "site_supervisor")
    sup = login(client, "sup@example.com")
    cats = {
        c["name"]: c["id"] for c in client.get("/api/finance/expense-categories", headers=h).json()
    }
    assert set(cats) >= {
        "Food",
        "Travel",
        "Local purchase",
        "Labour advance",
        "Transport",
        "Site misc",
    }
    assert (
        client.post(
            "/api/finance/petty-cash/advances",
            json={"user_id": uid(db, "sup@example.com"), "amount": "5000"},
            headers=sup,
        ).status_code
        == 403
    )
    acc = client.post(
        "/api/finance/petty-cash/advances",
        json={"user_id": uid(db, "sup@example.com"), "amount": "5000"},
        headers=h,
    ).json()
    client.post(
        "/api/finance/petty-cash/advances",
        json={"user_id": uid(db, "sup2@example.com"), "amount": "100"},
        headers=h,
    )

    def spend(amount, photo=False, cat="Food"):
        files = {"photo": ("bill.png", PNG, "image/png")} if photo else None
        return client.post(
            "/api/finance/petty-cash/expenses",
            data={
                "amount": amount,
                "category_id": cats[cat],
                "site_id": world["site"],
                "paid_to": "Invented dhaba",
            },
            files=files,
            headers=sup,
        )

    assert spend("400").status_code == 201
    r = spend("800")
    assert r.status_code == 422 and "photo" in r.json()["detail"]  # above the ₹500 limit
    acc = spend("800", photo=True).json()
    assert D(acc["pending"]) == 1200 and D(acc["balance"]) == 5000
    for e in acc["entries"]:
        if e["kind"] == "expense":
            assert (
                client.post(
                    f"/api/finance/petty-cash/expenses/{e['id']}/decide",
                    json={"approve": True},
                    headers=h,
                ).status_code
                == 200
            )
    acc = client.post(
        f"/api/finance/petty-cash/{acc['id']}/settle", json={"amount": "1000"}, headers=h
    ).json()
    assert D(acc["balance"]) == 2800  # 5,000 - 1,200 - 1,000
    assert [a["user_name"] for a in client.get("/api/finance/petty-cash", headers=sup).json()] == [
        "sup"
    ]
    budget = client.get(f"/api/execution/sites/{world['site']}/budget", headers=h).json()
    assert D(next(r for r in budget["rows"] if r["head"] == "other")["actual"]) == 1200


# --- payroll -------------------------------------------------------------------------------------


def test_payroll_pf_cap_esi_pt_lop_lock_and_hidden_salary(boss, world, db, make_user, login_as):
    client, h = boss
    make_user("asha@example.com", "site_supervisor", name="Invented Asha")
    make_user("vik@example.com", "site_supervisor", name="Invented Vikram")
    a, v = uid(db, "asha@example.com"), uid(db, "vik@example.com")
    client.post(
        "/api/finance/salary-structures",
        json={
            "user_id": a,
            "effective_from": "2026-04-01",
            "basic": "20000",
            "hra": "8000",
            "other_allowance": "2000",
        },
        headers=h,
    )
    client.post(
        "/api/finance/salary-structures",
        json={"user_id": v, "effective_from": "2026-04-01", "basic": "9000", "hra": "3000"},
        headers=h,
    )
    client.post(
        "/api/finance/staff-advances",
        json={"user_id": a, "amount": "1000", "on_date": "2026-09-10"},
        headers=h,
    )
    for n in range(1, 11):  # Asha checked in at the site on 10 days
        db.add(
            StaffAttendance(
                user_id=uuid.UUID(a),
                site_id=world["site"],
                on_date=date(2026, 9, n),
                check_in_at=ex.now(),
            )
        )
    db.commit()
    run = client.post(
        "/api/finance/payroll",
        json={"month": "2026-09", "adjustments": [{"user_id": v, "lop_days": "3"}]},
        headers=h,
    ).json()
    slips = {s["user_name"]: s for s in run["payslips"]}
    asha, vik = slips["Invented Asha"], slips["Invented Vikram"]
    assert D(asha["gross"]) == 30000 and asha["worked_days"] == 10
    assert D(asha["pf_employee"]) == 1800  # 12 % of the 15,000 cap, not of 20,000
    assert D(asha["esi_employee"]) == 0  # 30,000 is above the 21,000 threshold
    assert D(asha["pt"]) == 200 and D(asha["advance_recovery"]) == 1000
    assert D(asha["net"]) == 27000  # 30,000 - 1,800 - 200 - 1,000
    assert D(vik["paid_days"]) == 27 and D(vik["gross"]) == 10800  # 12,000 x 27 / 30 (LOP 3)
    assert (
        D(vik["pf_employee"]) == 972
        and D(vik["esi_employee"]) == 81
        and D(vik["esi_employer"]) == 351
    )
    assert D(vik["pt"]) == 0  # below the ₹12,000 Gujarat slab
    pdf = client.get(f"/api/finance/payslips/{asha['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert (
        client.post(
            f"/api/finance/payroll/{run['id']}/lock",
            json={"mode": "neft", "ref_no": "SAL-SEP"},
            headers=h,
        ).json()["status"]
        == "locked"
    )
    assert (
        client.post("/api/finance/payroll", json={"month": "2026-09"}, headers=h).status_code == 409
    )

    # salaries are visible only with payroll.view
    off, oh = login_as("office_admin", email="office@example.com")
    for path in ("payroll", "salary-structures", f"payslips/{asha['id']}/pdf"):
        assert off.get(f"/api/finance/{path}", headers=oh).status_code == 403, path
    profit = off.get(f"/api/finance/sites/{world['site']}/profit", headers=oh).json()
    assert profit["salary_hidden"] and "staff_salary" not in profit["cost"]
    profit = client.get(f"/api/finance/sites/{world['site']}/profit", headers=h).json()
    assert D(profit["cost"]["staff_salary"]) == D(
        "31800"
    )  # (30,000 + PF 1,800) x 10 / 10 days at this site
    assert db.scalar(select(Payslip.id)) is not None


# --- site profit ---------------------------------------------------------------------------------


def test_site_profit_from_fixed_inputs(boss, world):
    client, h = boss
    c, ra, inv = invoiced(client, h, world)
    for head, amount in (("material", "12000"), ("other", "3000")):
        client.post(
            f"/api/execution/sites/{world['site']}/costs",
            json={"head": head, "amount": amount, "description": "Invented cost"},
            headers=h,
        )
    client.post(
        "/api/finance/receipts",
        json={
            "client_id": world["client"],
            "amount": "20000",
            "allocations": [{"invoice_id": inv["id"], "amount": "20000"}],
        },
        headers=h,
    )
    p = client.get(f"/api/finance/sites/{world['site']}/profit", headers=h).json()
    assert D(p["billed"]) == 34500 and D(p["certified"]) == 34500 and D(p["received"]) == 20000
    assert D(p["retention_held"]) == 1725 and D(p["cost_total"]) == 15000
    assert (
        D(p["gross_profit"]) == 19500 and D(p["margin_percent"]) == D("56.5") and not p["over_cost"]
    )
    assert D(p["contract_value"]) == 60000
    client.post(
        f"/api/execution/sites/{world['site']}/costs",
        json={"head": "other", "amount": "30000", "description": "Invented overrun"},
        headers=h,
    )
    p = client.get(f"/api/finance/sites/{world['site']}/profit", headers=h).json()
    assert p["over_cost"] and D(p["gross_profit"]) == -10500
    margins = client.get("/api/finance/site-margins", headers=h).json()
    assert margins[str(world["site"])]["over_cost"]


# --- Tally ---------------------------------------------------------------------------------------


def test_tally_xml_balanced_and_exported_vouchers_skipped(boss, world, db):
    client, h = boss
    c, ra, inv = invoiced(client, h, world)
    client.post(
        "/api/finance/receipts",
        json={
            "client_id": world["client"],
            "amount": "30000",
            "tds_amount": "690",
            "allocations": [{"invoice_id": inv["id"], "amount": "30690"}],
        },
        headers=h,
    )
    sup = Vendor(
        name="Invented & Co <Chem>",
        type="material_supplier",
        gstin="24ABCFD1234E1Z5",
        pan="ABCFD1234E",
    )
    db.add(sup)
    db.commit()
    g = grn_for(client, h, db, sup.id)
    bill = client.post(
        "/api/finance/vendor-bills",
        json={
            "vendor_id": sup.id,
            "bill_no": "B-1",
            "bill_date": "2026-10-07",
            "grn_ids": [g["id"]],
        },
        headers=h,
    ).json()
    client.post(f"/api/finance/vendor-bills/{bill['id']}/approve", json={}, headers=h)
    client.post(
        "/api/finance/payments",
        json={
            "vendor_id": sup.id,
            "on_date": "2026-10-07",
            "allocations": [{"vendor_bill_id": bill["id"], "amount": "1000"}],
        },
        headers=h,
    )
    params = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
    r = client.post("/api/finance/tally/export", params=params, headers=h)
    assert r.status_code == 200 and r.headers["X-Voucher-Count"] == "4"
    root = ET.fromstring(r.content)  # well-formed (the "&" and "<" in the vendor name are escaped)
    vouchers = root.findall(".//VOUCHER")
    assert sorted(v.get("VCHTYPE") for v in vouchers) == ["Payment", "Purchase", "Receipt", "Sales"]
    for v in vouchers:
        amounts = [D(a.text) for a in v.findall("ALLLEDGERENTRIES.LIST/AMOUNT")]
        assert sum(amounts) == 0, v.findtext("VOUCHERNUMBER")
    assert (
        client.post("/api/finance/tally/export", params=params, headers=h).headers[
            "X-Voucher-Count"
        ]
        == "0"
    )
    again = client.post(
        "/api/finance/tally/export", params={**params, "include_exported": "true"}, headers=h
    )
    assert again.headers["X-Voucher-Count"] == "4"
    book = client.get("/api/finance/tally/day-book", params=params, headers=h)
    assert book.status_code == 200 and book.content[:2] == b"PK"


# --- permissions ---------------------------------------------------------------------------------


def test_finance_permissions(boss, world, db, make_user, login_as):
    client, h = boss
    c, ra, inv = invoiced(client, h, world)
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert acc.get("/api/finance/invoices", headers=ah).status_code == 200
    assert (
        acc.post(
            f"/api/finance/invoices/{inv['id']}/credit-note",
            json={"taxable": "10", "reason": "x"},
            headers=ah,
        ).status_code
        == 403
    )  # billing.approve (office_admin)
    assert acc.get("/api/finance/payroll", headers=ah).status_code == 200
    off, oh = login_as("office_admin", email="office@example.com")
    assert (
        off.post(
            f"/api/finance/invoices/{inv['id']}/credit-note",
            json={"taxable": "10", "reason": "x"},
            headers=oh,
        ).status_code
        == 201
    )

    make_user("sup@example.com", "site_supervisor")
    sup = login(client, "sup@example.com")
    assert client.get("/api/finance/invoices", headers=sup).status_code == 403
    assert client.get("/api/finance/vendor-bills", headers=sup).status_code == 403
    assert client.get("/api/finance/petty-cash", headers=sup).status_code == 200  # their own

    # sales: billing of assigned sites, no costs
    make_user("sales@example.com", "sales")
    sales = login(client, "sales@example.com")
    assert client.get("/api/finance/invoices", headers=sales).json() == []
    client.put(
        f"/api/sites/{world['site']}/members",
        json={"members": [{"user_id": uid(db, "sales@example.com"), "role_on_site": "sales"}]},
        headers=h,
    )
    assert sorted(
        i["number"] for i in client.get("/api/finance/invoices", headers=sales).json()
    ) == ["CN/26-27/0001", inv["number"]]
    assert (
        client.get(f"/api/finance/sites/{world['site']}/profit", headers=sales).status_code == 403
    )
    assert client.get("/api/finance/site-margins", headers=sales).json() == {}

    cl, ch = login_as("client", email="customer@example.com")
    for path in (
        "invoices",
        "ra-bills",
        "receipts",
        "vendor-bills",
        "payments",
        "payroll",
        "petty-cash",
        "profit",
        "ageing",
        "lookups",
        "settings",
    ):
        assert cl.get(f"/api/finance/{path}", headers=ch).status_code == 403, path
    assert (
        cl.post(
            "/api/finance/tally/export",
            params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
            headers=ch,
        ).status_code
        == 403
    )
