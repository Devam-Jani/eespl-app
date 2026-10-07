"""Material: indent -> RFQ -> PO -> GRN -> stock -> transfer -> issue, GST, landed cost,
numbering, the approval limit, stock rules, unit conversion and permissions."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.masters.models import CompanyGstin, Product, UnitConversion, Vendor
from app.material import service as svc
from app.models import User
from tests.conftest import login

D = Decimal


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


@pytest.fixture
def masters(db):
    """Invented products, vendors (one in Gujarat, one in Maharashtra) and our Gujarat GSTIN."""
    products = [
        Product(code="T-CRYS", name="Test crystalline powder", unit="kg", gst_percent=18),
        Product(code="T-PU", name="Test PU coating", unit="ltr", gst_percent=18),
        Product(code="T-MESH", name="Test glass fibre mesh", unit="sqm", gst_percent=12),
    ]
    vendors = [
        Vendor(name="Invented Chemicals Ahmedabad", gstin="24ABCDE1234F1Z5", state="Gujarat"),
        Vendor(name="Invented Polymers Pune", gstin="27ABCDE1234F1Z5", state="Maharashtra"),
    ]
    db.add_all(products + vendors)
    db.add(
        CompanyGstin(
            gstin="24AAACE1234A1Z1", state="Gujarat", address="Test address", is_default=True
        )
    )
    db.flush()
    # 1 bag (nos) of the crystalline powder = 25 kg
    db.add(UnitConversion(from_unit="nos", to_unit="kg", factor=25, product_id=products[0].id))
    db.commit()
    return {p.code: p.id for p in products}, [v.id for v in vendors]


def site(client, headers, name="Invented Heights"):
    r = client.post("/api/sites", json={"name": name, "start_date": "2026-10-01"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def store_of(client, headers, site_id):
    stores = client.get("/api/material/stores", params={"site_id": site_id}, headers=headers)
    return stores.json()[0]


def godown(client, headers):
    stores = client.get("/api/material/stores", headers=headers).json()
    return next(s for s in stores if s["kind"] == "godown")


def stock(client, headers, store_id):
    rows = client.get(f"/api/material/stores/{store_id}/stock", headers=headers).json()
    return {r["product_id"]: (D(r["qty"]), D(r["avg_rate"])) for r in rows}


def make_po(client, headers, vendor, store, lines, charges=(), **extra):
    body = {
        "vendor_id": vendor,
        "store_id": store,
        "lines": list(lines),
        "charges": list(charges),
        **extra,
    }
    r = client.post("/api/material/pos", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def approved_po(client, headers, *args, **kwargs):
    po = make_po(client, headers, *args, **kwargs)
    r = client.post(f"/api/material/pos/{po['id']}/submit", headers=headers)
    assert r.status_code == 200, r.text
    if r.json()["status"] == "pending_approval":
        r = client.post(f"/api/material/pos/{po['id']}/approve", headers=headers)
    assert r.json()["status"] == "approved", r.text
    return r.json()


def receive(client, headers, po, qtys, approve=True):
    lines = [
        {"po_line_id": ln["id"], "received_qty": str(q)}
        for ln, q in zip(po["lines"], qtys, strict=True)
        if q
    ]
    r = client.post(
        "/api/material/grns",
        json={"po_id": po["id"], "challan_no": "CH-1", "lines": lines, "submit": True},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    if approve:
        r = client.post(f"/api/material/grns/{r.json()['id']}/approve", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
    return r.json()


def uid(db, email):
    return str(db.scalar(select(User.id).where(User.email == email)))


# --- the whole flow ------------------------------------------------------------------------------


def test_full_flow_indent_rfq_po_grn_transfer_issue(boss, masters, db):
    client, h = boss
    products, (v_guj, v_pune) = masters
    s = site(client, h)
    site_store = store_of(client, h, s["id"])
    assert site_store["kind"] == "site" and site_store["name"].startswith(s["code"])
    gd = godown(client, h)

    # indent: 3 products, one in bags converted to kg
    r = client.post(
        "/api/material/indents",
        json={
            "site_id": s["id"],
            "priority": "urgent",
            "submit": True,
            "lines": [
                {"product_id": products["T-CRYS"], "qty": "8", "unit": "nos"},
                {"product_id": products["T-PU"], "qty": "40"},
                {"product_id": products["T-MESH"], "qty": "100"},
                {"free_text": "Special primer, not in master", "qty": "5", "unit": "ltr"},
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    indent = r.json()
    assert indent["code"] == f"IND-{date.today().year}-0001"
    assert indent["status"] == "submitted"
    assert [D(ln["base_qty"]) for ln in indent["lines"]] == [200, 40, 100, 5]
    r = client.post(f"/api/material/indents/{indent['id']}/approve", headers=h)
    assert r.json()["status"] == "approved"

    # RFQ to two vendors; Pune is cheaper on rate but its freight makes the PU dearer landed
    r = client.post(
        "/api/material/rfqs",
        json={"indent_ids": [indent["id"]], "vendor_ids": [v_guj, v_pune]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    rfq = r.json()
    assert len(rfq["lines"]) == 3  # the free-text line is bought on a direct PO
    lid = {ln["product_id"]: ln["id"] for ln in rfq["lines"]}
    quotes = [
        {"rfq_line_id": lid[products["T-CRYS"]], "vendor_id": v_guj, "rate": "48"},
        {"rfq_line_id": lid[products["T-CRYS"]], "vendor_id": v_pune, "rate": "45"},
        {"rfq_line_id": lid[products["T-PU"]], "vendor_id": v_guj, "rate": "300"},
        {"rfq_line_id": lid[products["T-PU"]], "vendor_id": v_pune, "rate": "290"},
        {
            "rfq_line_id": lid[products["T-MESH"]],
            "vendor_id": v_guj,
            "rate": "60",
            "gst_percent": "12",
        },
        {
            "rfq_line_id": lid[products["T-MESH"]],
            "vendor_id": v_pune,
            "rate": "70",
            "gst_percent": "12",
        },
    ]
    r = client.put(
        f"/api/material/rfqs/{rfq['id']}/quotes",
        json={
            "quotes": quotes,
            "vendor_freight": [
                {"vendor_id": v_guj, "freight": "1000"},
                {"vendor_id": v_pune, "freight": "6000"},
            ],
        },
        headers=h,
    )
    rfq = r.json()
    lowest = {
        ln["product_id"]: next(q["vendor_id"] for q in ln["quotes"] if q["lowest"])
        for ln in rfq["lines"]
    }
    # Gujarat 9600+12000+6000 = 27600, freight 1000; Pune 9000+11600+7000 = 27600, freight 6000
    assert lowest == dict.fromkeys(products.values(), v_guj)
    # overriding the lowest needs a reason
    r = client.post(
        f"/api/material/rfqs/{rfq['id']}/choose",
        json=[{"rfq_line_id": lid[products["T-PU"]], "vendor_id": v_pune}],
        headers=h,
    )
    assert r.status_code == 422
    r = client.post(f"/api/material/rfqs/{rfq['id']}/po", params={"store_id": gd["id"]}, headers=h)
    assert r.status_code == 201, r.text
    (po,) = r.json()
    assert po["code"].startswith("PO-") and po["status"] == "draft"
    assert not po["interstate"]
    assert [c["kind"] for c in po["charges"]] == ["freight"] and po["charges"][0]["add_to_cost"]
    # 27600 + 1000 freight, GST 18% on 9600 + 12000 + 1000, 12% on 6000
    assert D(po["taxable"]) == D("27600.00")
    tax = D("22600") * D("0.18") + D("6000") * D("0.12")
    assert D(po["cgst"]) + D(po["sgst"]) == tax and D(po["igst"]) == 0
    assert D(po["grand_total"]) == D("28600") + tax
    r = client.post(f"/api/material/pos/{po['id']}/submit", headers=h)
    assert r.json()["status"] == "approved"  # super admin has po.approve: under the limit anyway
    assert client.get(f"/api/material/indents/{indent['id']}", headers=h).json()["status"] == (
        "partly_ordered"  # the free-text line is still open
    )
    r = client.post(f"/api/material/pos/{po['id']}/send", headers=h)
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    pdf = client.get(f"/api/material/pos/{po['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    # partial GRN into the godown: 150 of 200 kg, all the PU, none of the mesh
    po = r.json()
    grn = receive(client, h, po, [150, 40, 0])
    landed = {ln["product_id"]: D(ln["landed_rate"]) for ln in grn["lines"]}
    uplift = 1 + D(1000) / D(27600)
    assert landed[products["T-CRYS"]] == (D(48) * uplift).quantize(svc.RATE)
    assert landed[products["T-PU"]] == (D(300) * uplift).quantize(svc.RATE)
    got = stock(client, h, gd["id"])
    assert got[products["T-CRYS"]][0] == 150 and got[products["T-PU"]][0] == 40
    po = client.get(f"/api/material/pos/{po['id']}", headers=h).json()
    assert po["status"] == "partly_received"
    assert [D(ln["received_qty"]) for ln in po["lines"]] == [150, 40, 0]
    ind = client.get(f"/api/material/indents/{indent['id']}", headers=h).json()
    assert [D(ln["received_qty"]) for ln in ind["lines"]] == [150, 40, 0, 0]

    # transfer to the site: 100 kg sent, 98 arrive; freight 750 charged to the site
    r = client.post(
        "/api/material/transfers",
        json={
            "from_store_id": gd["id"],
            "to_store_id": site_store["id"],
            "freight_amount": "750",
            "transporter": "Invented Roadways",
            "dispatch": True,
            "lines": [
                {"product_id": products["T-CRYS"], "qty": "4", "unit": "nos"},
                {"product_id": products["T-PU"], "qty": "20"},
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["code"] == f"TO-{date.today().year}-0001" and t["status"] == "dispatched"
    assert stock(client, h, gd["id"])[products["T-CRYS"]][0] == 50
    r = client.post(
        f"/api/material/transfers/{t['id']}/receive",
        json={
            "lines": [
                {"line_id": t["lines"][0]["id"], "qty_received": "98"},
            ]
        },
        headers=h,
    )
    assert r.status_code == 422  # a shortage needs its reason
    r = client.post(
        f"/api/material/transfers/{t['id']}/receive",
        json={
            "lines": [
                {
                    "line_id": t["lines"][0]["id"],
                    "qty_received": "98",
                    "shortage_reason": "Bag torn",
                },
            ]
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert D(r.json()["lines"][0]["shortage_qty"]) == 2
    at_site = stock(client, h, site_store["id"])
    assert at_site[products["T-CRYS"]] == (98, landed[products["T-CRYS"]])
    assert at_site[products["T-PU"]][0] == 20

    # issue to a task-less area of the site, then return some
    r = client.post(
        "/api/material/issues",
        json={"site_id": s["id"], "lines": [{"product_id": products["T-CRYS"], "qty": "60"}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert D(r.json()["lines"][0]["rate"]) == landed[products["T-CRYS"]]
    r = client.post(
        "/api/material/issues",
        json={
            "site_id": s["id"],
            "kind": "return",
            "lines": [{"product_id": products["T-CRYS"], "qty": "10"}],
        },
        headers=h,
    )
    assert r.status_code == 201
    assert stock(client, h, site_store["id"])[products["T-CRYS"]][0] == 48

    # freight: the PO freight follows the GRN (19,200 of 27,600 received), the transfer godown->site
    report = client.get(
        "/api/material/freight/report", params={"site_id": s["id"]}, headers=h
    ).json()
    assert len(report) == 1
    assert D(report[0]["inbound"]) == D("695.65") and D(report[0]["godown_to_site"]) == 750
    summary = client.get(f"/api/material/sites/{s['id']}/summary", headers=h).json()
    assert D(summary["freight"]["total"]) == D("1445.65")

    # the ledger is append-only and explains the balance
    ledger = client.get(
        f"/api/material/stores/{site_store['id']}/ledger",
        params={"product_id": products["T-CRYS"]},
        headers=h,
    ).json()
    assert [r["ref_type"] for r in ledger] == ["return", "issue", "shortage", "transfer_in"]
    assert D(ledger[0]["balance"]) == 48 and ledger[3]["ref_code"] == t["code"]
    assert D(ledger[2]["qty"]) == -2 and ledger[2]["ref_code"] == t["code"]


# --- GST and landed cost -------------------------------------------------------------------------


GST_LINES = [
    {
        "product_id": None,
        "qty": "10",
        "rate": "1000",
        "discount_percent": "10",
        "gst_percent": "18",
    },
    {"product_id": None, "qty": "3", "rate": "333.33", "gst_percent": "12"},
]


def _gst_lines(products):
    lines = [dict(ln) for ln in GST_LINES]
    lines[0]["product_id"], lines[1]["product_id"] = products["T-PU"], products["T-MESH"]
    return lines


def test_gst_intra_state_discount_before_tax(boss, masters):
    client, h = boss
    products, (v_guj, _) = masters
    po = make_po(
        client,
        h,
        v_guj,
        godown(client, h)["id"],
        _gst_lines(products),
        [{"kind": "freight", "amount": "500", "gst_percent": "18"}],
    )
    assert not po["interstate"]
    assert D(po["subtotal"]) == D("10999.99")
    assert D(po["discount_total"]) == D("1000.00")
    assert D(po["taxable"]) == D("9999.99")  # 9000 after the 10 % discount + 999.99
    # tax: 9000 x 18 % + 999.99 x 12 % + 500 x 18 % = 1620 + 119.9988 + 90
    assert (D(po["cgst"]), D(po["sgst"]), D(po["igst"])) == (D("915.00"), D("915.00"), 0)
    assert D(po["charges_total"]) == 500
    assert D(po["grand_total"]) == D("12330") and D(po["round_off"]) == D("0.01")
    assert [D(ln["amount"]) for ln in po["lines"]] == [D("9000.00"), D("999.99")]


def test_gst_inter_state_is_igst(boss, masters):
    client, h = boss
    products, (_, v_pune) = masters
    po = make_po(
        client,
        h,
        v_pune,
        godown(client, h)["id"],
        _gst_lines(products),
        [{"kind": "freight", "amount": "500", "gst_percent": "18"}],
    )
    assert po["interstate"]
    assert (D(po["cgst"]), D(po["sgst"]), D(po["igst"])) == (0, 0, D("1830.00"))
    assert D(po["grand_total"]) == D("12330")


def test_freight_added_to_cost_raises_the_landed_rate(boss, masters):
    client, h = boss
    products, (v_guj, _) = masters
    gd = godown(client, h)["id"]
    line = [{"product_id": products["T-CRYS"], "qty": "100", "rate": "50"}]
    with_freight = approved_po(
        client,
        h,
        v_guj,
        gd,
        line,
        [
            {"kind": "freight", "amount": "1000"},  # add to cost: on by default
            {"kind": "loading", "amount": "300"},  # off by default
        ],
    )
    assert [c["add_to_cost"] for c in with_freight["charges"]] == [True, False]
    grn = receive(client, h, with_freight, [100])
    assert D(grn["lines"][0]["landed_rate"]) == 60  # 50 x (1 + 1000 / 5000)

    no_cost = approved_po(
        client, h, v_guj, gd, line, [{"kind": "freight", "amount": "1000", "add_to_cost": False}]
    )
    grn = receive(client, h, no_cost, [100])
    assert D(grn["lines"][0]["landed_rate"]) == 50
    assert stock(client, h, gd)[products["T-CRYS"]] == (200, 55)  # weighted average


# --- numbering -----------------------------------------------------------------------------------


def test_po_numbers_roll_over_with_the_financial_year(boss, masters, db):
    client, h = boss
    products, (v_guj, _) = masters
    gd = godown(client, h)["id"]
    line = [{"product_id": products["T-PU"], "qty": "1", "rate": "10"}]
    codes = [
        make_po(client, h, v_guj, gd, line, po_date=d)["code"]
        for d in ("2027-03-30", "2027-03-31", "2027-04-01")
    ]
    assert codes == ["PO-2026-27-000001", "PO-2026-27-000002", "PO-2027-28-000001"]
    assert svc.financial_year(date(2026, 3, 31)) == "2025-26"
    assert svc.financial_year(date(2026, 4, 1)) == "2026-27"
    assert svc.next_code(db, "IND", date(2027, 1, 5)) == "IND-2027-0001"


# --- approval limit ------------------------------------------------------------------------------


def test_approval_limit(login_as, masters):
    products, (v_guj, _) = masters
    buyer, bh = login_as("store_purchase", email="buyer@example.com")
    admin, ah = login_as("office_admin", email="admin@example.com")
    gd = godown(buyer, bh)["id"]
    assert D(buyer.get("/api/material/settings", headers=bh).json()["po_approval_limit"]) == 50000

    small = make_po(
        buyer, bh, v_guj, gd, [{"product_id": products["T-PU"], "qty": "100", "rate": "400"}]
    )
    assert D(small["grand_total"]) == D("47200")
    r = buyer.post(f"/api/material/pos/{small['id']}/submit", headers=bh)
    assert r.json()["status"] == "approved"  # the buyer approves their own PO under the limit

    big = make_po(
        buyer, bh, v_guj, gd, [{"product_id": products["T-PU"], "qty": "200", "rate": "400"}]
    )
    r = buyer.post(f"/api/material/pos/{big['id']}/submit", headers=bh)
    assert r.json()["status"] == "pending_approval" and r.json()["needs_approver"]
    assert buyer.post(f"/api/material/pos/{big['id']}/approve", headers=bh).status_code == 403
    r = admin.post(f"/api/material/pos/{big['id']}/approve", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # the limit is a company setting
    r = admin.put(
        "/api/material/settings",
        json={
            "po_approval_limit": "100000",
            "allow_negative_stock": False,
            "grn_approval_levels": 1,
        },
        headers=ah,
    )
    assert r.status_code == 200
    again = make_po(
        buyer, bh, v_guj, gd, [{"product_id": products["T-PU"], "qty": "200", "rate": "400"}]
    )
    assert buyer.post(f"/api/material/pos/{again['id']}/submit", headers=bh).json()["status"] == (
        "approved"
    )
    assert (
        buyer.put(
            "/api/material/settings",
            json={"po_approval_limit": "1", "allow_negative_stock": True, "grn_approval_levels": 1},
            headers=bh,
        ).status_code
        == 403
    )


def test_grn_with_two_approval_levels(boss, login_as, masters):
    client, h = boss
    products, (v_guj, _) = masters
    client.put(
        "/api/material/settings",
        json={
            "po_approval_limit": "50000",
            "allow_negative_stock": False,
            "grn_approval_levels": 2,
        },
        headers=h,
    )
    gd = godown(client, h)["id"]
    po = approved_po(
        client, h, v_guj, gd, [{"product_id": products["T-PU"], "qty": "10", "rate": "100"}]
    )
    grn = receive(client, h, po, [10], approve=False)
    r = client.post(f"/api/material/grns/{grn['id']}/approve", headers=h)
    assert r.json()["status"] == "submitted" and r.json()["approvals"] == 1
    assert stock(client, h, gd) == {}
    assert client.post(f"/api/material/grns/{grn['id']}/approve", headers=h).status_code == 409
    other, oh = login_as("store_purchase", email="second@example.com")
    r = other.post(f"/api/material/grns/{grn['id']}/approve", headers=oh)
    assert r.json()["status"] == "approved"
    assert stock(client, h, gd)[products["T-PU"]][0] == 10


# --- stock rules ---------------------------------------------------------------------------------


def test_no_negative_stock_unless_allowed(boss, masters):
    client, h = boss
    products, _ = masters
    s = site(client, h)
    st = store_of(client, h, s["id"])["id"]
    r = client.post(
        f"/api/material/stores/{st}/adjust",
        json={
            "product_id": products["T-PU"],
            "qty": "5",
            "rate": "200",
            "kind": "opening",
            "note": "Opening count",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    issue = {"site_id": s["id"], "lines": [{"product_id": products["T-PU"], "qty": "8"}]}
    r = client.post("/api/material/issues", json=issue, headers=h)
    assert r.status_code == 422 and "Only 5" in r.json()["detail"]
    assert stock(client, h, st)[products["T-PU"]][0] == 5  # nothing half-written

    client.put(
        "/api/material/settings",
        json={"po_approval_limit": "50000", "allow_negative_stock": True, "grn_approval_levels": 1},
        headers=h,
    )
    r = client.post("/api/material/issues", json=issue, headers=h)
    assert r.status_code == 201
    assert stock(client, h, st)[products["T-PU"]][0] == -3

    # a transfer from an empty store is refused the same way
    client.put(
        "/api/material/settings",
        json={
            "po_approval_limit": "50000",
            "allow_negative_stock": False,
            "grn_approval_levels": 1,
        },
        headers=h,
    )
    r = client.post(
        "/api/material/transfers",
        json={
            "from_store_id": godown(client, h)["id"],
            "to_store_id": st,
            "dispatch": True,
            "lines": [{"product_id": products["T-MESH"], "qty": "1"}],
        },
        headers=h,
    )
    assert r.status_code == 422


def test_unit_conversion_into_the_base_unit(boss, masters):
    client, h = boss
    products, (v_guj, _) = masters
    gd = godown(client, h)["id"]
    po = approved_po(
        client,
        h,
        v_guj,
        gd,
        [{"product_id": products["T-CRYS"], "qty": "4", "unit": "nos", "rate": "1250"}],
    )
    assert D(po["lines"][0]["base_qty"]) == 100
    grn = receive(client, h, po, [4])
    assert D(grn["lines"][0]["landed_rate"]) == 50  # 1250 per 25 kg bag
    assert stock(client, h, gd)[products["T-CRYS"]] == (100, 50)
    r = client.post(
        "/api/material/pos",
        json={
            "vendor_id": v_guj,
            "store_id": gd,
            "lines": [{"product_id": products["T-PU"], "qty": "1", "unit": "nos", "rate": "1"}],
        },
        headers=h,
    )
    assert r.status_code == 422 and "cannot be converted" in r.json()["detail"]


def test_new_sites_get_their_own_store(boss, db):
    client, h = boss
    s = site(client, h, name="Store check")
    (st,) = client.get("/api/material/stores", params={"site_id": s["id"]}, headers=h).json()
    assert st["kind"] == "site" and st["site_id"] == s["id"]
    assert db.execute(text("SELECT count(*) FROM stores WHERE kind = 'godown'")).scalar() == 1


# --- permissions ---------------------------------------------------------------------------------


def test_supervisor_works_on_assigned_sites_only(boss, make_user, masters, db):
    client, h = boss
    products, (v_guj, _) = masters
    mine, other = site(client, h, "Mine"), site(client, h, "Other")
    make_user("sup@example.com", "site_supervisor")
    client.put(
        f"/api/sites/{mine['id']}/members",
        json={"members": [{"user_id": uid(db, "sup@example.com"), "role_on_site": "supervisor"}]},
        headers=h,
    )
    sup = login(client, "sup@example.com")
    line = [{"product_id": products["T-PU"], "qty": "2"}]
    r = client.post(
        "/api/material/indents",
        json={"site_id": mine["id"], "lines": line, "submit": True},
        headers=sup,
    )
    assert r.status_code == 201, r.text
    assert not r.json()["can_approve"]
    assert (
        client.post(f"/api/material/indents/{r.json()['id']}/approve", headers=sup).status_code
        == 403
    )
    r = client.post(
        "/api/material/indents", json={"site_id": other["id"], "lines": line}, headers=sup
    )
    assert r.status_code == 403
    theirs = client.post(
        "/api/material/indents", json={"site_id": other["id"], "lines": line}, headers=h
    ).json()
    listed = client.get("/api/material/indents", headers=sup).json()["items"]
    assert [i["site_id"] for i in listed] == [mine["id"]]
    assert client.get(f"/api/material/indents/{theirs['id']}", headers=sup).status_code == 404
    stores = client.get("/api/material/stores", headers=sup).json()
    assert [s["site_id"] for s in stores] == [mine["id"]]  # not the godown, not the other site
    # a GRN into their site store is fine; into the godown it is not
    mine_store = stores[0]["id"]
    direct = {
        "vendor_id": v_guj,
        "lines": [{"product_id": products["T-PU"], "received_qty": "2", "rate": "100"}],
        "submit": True,
    }
    r = client.post("/api/material/grns", json={**direct, "store_id": mine_store}, headers=sup)
    assert r.status_code == 201, r.text
    assert (
        client.post(f"/api/material/grns/{r.json()['id']}/approve", headers=sup).status_code == 403
    )
    r = client.post(
        "/api/material/grns", json={**direct, "store_id": godown(client, h)["id"]}, headers=sup
    )
    assert r.status_code == 403
    assert client.get("/api/material/pos", headers=sup).status_code == 403


def test_accounts_view_only_and_client_forbidden(boss, login_as, masters):
    client, h = boss
    products, (v_guj, _) = masters
    gd = godown(client, h)["id"]
    po = approved_po(
        client, h, v_guj, gd, [{"product_id": products["T-PU"], "qty": "1", "rate": "10"}]
    )
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert acc.get("/api/material/pos", headers=ah).json()["total"] == 1
    assert acc.get(f"/api/material/pos/{po['id']}/pdf", headers=ah).status_code == 200
    assert acc.get("/api/material/grns", headers=ah).status_code == 200
    body = {
        "vendor_id": v_guj,
        "store_id": gd,
        "lines": [{"product_id": products["T-PU"], "qty": "1", "rate": "1"}],
    }
    assert acc.post("/api/material/pos", json=body, headers=ah).status_code == 403
    assert acc.post(f"/api/material/pos/{po['id']}/send", headers=ah).status_code == 403
    assert (
        acc.post(
            "/api/material/grns",
            json={
                "po_id": po["id"],
                "lines": [{"po_line_id": po["lines"][0]["id"], "received_qty": "1"}],
            },
            headers=ah,
        ).status_code
        == 403
    )
    assert acc.get("/api/material/indents", headers=ah).status_code == 403

    cl, ch = login_as("client", email="customer@example.com")
    for path in (
        "indents",
        "rfqs",
        "pos",
        "grns",
        "stores",
        "transfers",
        "issues",
        "freight",
        "lookups",
        "settings",
    ):
        assert cl.get(f"/api/material/{path}", headers=ch).status_code == 403, path
