from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.masters.schemas import gstin_check_digit
from app.models import AuditLog
from tests.conftest import login

VALID_GSTIN = "27AAPFU0939F1ZV"


def test_gstin_check_digit():
    assert gstin_check_digit(VALID_GSTIN[:14]) == VALID_GSTIN[14]


def _client_body(name="Acme Builders", **extra):
    return {
        "name": name,
        "type": "builder",
        "city": "Ahmedabad",
        "contacts": [
            {"name": "Ravi", "phone": "98250 00000", "is_primary": True},
            {"name": "Meera", "email": "meera@example.com"},
        ],
        **extra,
    }


def test_client_crud_with_contacts_and_audit(login_as, db):
    c, h = login_as("office_admin")
    r = c.post(
        "/api/clients", json=_client_body(gstin=" 27aapfu0939f1zv ", pan="AAPFU0939F"), headers=h
    )
    assert r.status_code == 201, r.text
    client = r.json()
    assert client["gstin"] == VALID_GSTIN
    assert [x["name"] for x in client["contacts"]] == ["Ravi", "Meera"]

    r = c.patch(
        f"/api/clients/{client['id']}",
        json={"city": "Surat", "contacts": [{"name": "Only One", "is_primary": True}]},
        headers=h,
    )
    assert r.json()["city"] == "Surat"
    assert [x["name"] for x in r.json()["contacts"]] == ["Only One"]

    found = c.get("/api/clients", params={"q": "acme"}, headers=h).json()
    assert found["total"] == 1 and found["items"][0]["id"] == client["id"]

    assert c.delete(f"/api/clients/{client['id']}", headers=h).status_code == 204
    actions = [
        a.action
        for a in db.scalars(
            select(AuditLog).where(AuditLog.entity == "client").order_by(AuditLog.id)
        )
    ]
    assert actions == ["client.create", "client.update", "client.delete"]


def test_client_validation(login_as):
    c, h = login_as("office_admin")
    for bad in (
        {"gstin": "27AAPFU0939F1ZX"},  # wrong check digit
        {"gstin": "ABC"},
        {"pan": "12345"},
        {"gstin": VALID_GSTIN, "pan": "ABCDE1234F"},  # PAN not the one inside the GSTIN
        {"type": "alien"},
        {"contacts": [{"name": "A", "is_primary": True}, {"name": "B", "is_primary": True}]},
    ):
        r = c.post("/api/clients", json=_client_body(**bad), headers=h)
        assert r.status_code == 422, bad


def test_sales_edits_only_their_own_clients(login_as, make_user):
    admin, admin_h = login_as("office_admin")
    theirs = admin.post("/api/clients", json=_client_body("Office Client"), headers=admin_h).json()

    make_user("sales@example.com", "sales")
    sales = TestClient(app)
    sh = login(sales, "sales@example.com")
    mine = sales.post("/api/clients", json=_client_body("Sales Client"), headers=sh)
    assert mine.status_code == 201
    mine = mine.json()

    # view scope is 'all': both are visible
    listed = sales.get("/api/clients", headers=sh).json()
    assert {x["name"] for x in listed["items"]} == {"Office Client", "Sales Client"}
    assert sales.get(f"/api/clients/{theirs['id']}", headers=sh).status_code == 200

    # edit scope is 'own'
    assert (
        sales.patch(f"/api/clients/{mine['id']}", json={"city": "Rajkot"}, headers=sh).status_code
        == 200
    )
    r = sales.patch(f"/api/clients/{theirs['id']}", json={"city": "Rajkot"}, headers=sh)
    assert r.status_code == 403
    assert sales.delete(f"/api/clients/{theirs['id']}", headers=sh).status_code == 403
    assert sales.delete(f"/api/clients/{mine['id']}", headers=sh).status_code == 204


def test_accounts_can_view_but_not_edit_clients(login_as):
    c, h = login_as("accounts")
    assert c.get("/api/clients", headers=h).status_code == 200
    assert c.post("/api/clients", json=_client_body(), headers=h).status_code == 403


def test_product_crud_and_validation(login_as, db):
    c, h = login_as("estimator")
    body = {
        "code": "MEM-4",
        "name": "APP membrane 4mm",
        "brand": "Texsa",
        "category": "membrane",
        "unit": "roll",
        "pack_size": "10",
    }
    r = c.post("/api/products", json=body, headers=h)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["gst_percent"] == "18.00"
    assert c.post("/api/products", json=body, headers=h).status_code == 409
    assert (
        c.post(
            "/api/products", json={**body, "code": "X", "unit": "furlong"}, headers=h
        ).status_code
        == 422
    )
    r = c.patch(f"/api/products/{pid}", json={"brand": "Other"}, headers=h)
    assert r.json()["brand"] == "Other"
    assert (
        c.post(f"/api/products/{pid}/prices", json={"purchase_rate": "-1"}, headers=h).status_code
        == 422
    )
    assert c.delete(f"/api/products/{pid}", headers=h).status_code == 204
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"product.create", "product.update", "product.delete"} <= actions


def test_tc_clauses_and_templates(login_as, db):
    c, h = login_as("estimator")
    ids = []
    for text, cat in (("Clause A", "general"), ("Clause B", "general"), ("Clause C", "payment")):
        r = c.post("/api/tc/clauses", json={"text": text, "category": cat}, headers=h)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    r = c.put("/api/tc/clauses/order", json={"ids": [ids[1], ids[0]]}, headers=h)
    assert [x["sort_order"] for x in r.json()] == [1, 2]
    general = c.get("/api/tc/clauses", params={"category": "general"}, headers=h).json()["items"]
    assert [x["text"] for x in general] == ["Clause B", "Clause A"]

    r = c.patch(f"/api/tc/clauses/{ids[2]}", json={"text": "Clause C (edited)"}, headers=h)
    assert r.json()["text"] == "Clause C (edited)"

    t1 = c.post(
        "/api/tc/templates",
        json={"name": "T1", "is_default": True, "clause_ids": [ids[2], ids[0]]},
        headers=h,
    ).json()
    assert [x["id"] for x in t1["clauses"]] == [ids[2], ids[0]]
    t2 = c.post("/api/tc/templates", json={"name": "T2", "is_default": True}, headers=h).json()
    listed = {t["name"]: t for t in c.get("/api/tc/templates", headers=h).json()}
    assert (listed["T1"]["is_default"], listed["T2"]["is_default"]) == (False, True)
    assert listed["T1"]["clause_count"] == 2

    r = c.patch(
        f"/api/tc/templates/{t1['id']}", json={"clause_ids": [ids[0], ids[1], ids[2]]}, headers=h
    )
    assert [x["id"] for x in r.json()["clauses"]] == ids
    assert (
        c.post(
            "/api/tc/templates", json={"name": "T3", "clause_ids": [ids[0], ids[0]]}, headers=h
        ).status_code
        == 422
    )
    assert c.delete(f"/api/tc/templates/{t2['id']}", headers=h).status_code == 204
    assert c.delete(f"/api/tc/clauses/{ids[0]}", headers=h).status_code == 204

    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {
        "tc_clause.create",
        "tc_clause.reorder",
        "tc_clause.update",
        "tc_clause.delete",
        "tc_template.create",
        "tc_template.update",
        "tc_template.delete",
    } <= actions


def test_library_view_cannot_change_masters(login_as):
    c, h = login_as("store_purchase")  # library.view only
    assert c.get("/api/tc/clauses", headers=h).status_code == 200
    assert (
        c.post("/api/tc/clauses", json={"text": "x", "category": "y"}, headers=h).status_code == 403
    )
    assert (
        c.post(
            "/api/products", json={"code": "x", "name": "y", "unit": "kg"}, headers=h
        ).status_code
        == 403
    )
