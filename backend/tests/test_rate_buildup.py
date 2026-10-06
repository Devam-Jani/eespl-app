from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.masters.rate import ComponentInput, build_rate, labour_per_unit
from tests.conftest import login


def component(consumption, rate, freight="0", wastage="0", name="P"):
    return ComponentInput(
        product_id=1,
        product_name=name,
        unit="kg",
        consumption_per_unit=D(consumption),
        wastage_percent=D(wastage),
        purchase_rate=D(rate),
        freight_per_unit=D(freight),
    )


def test_eespl_working_sheet_example():
    """From EESPL's own Working sheet: 1.13 × ₹365 + 0.11 × ₹95 + ₹120 prep & labour, 30%."""
    b = build_rate(
        unit="sqm",
        components=[component("1.13", "365"), component("0.11", "95")],
        surface_prep=D("40"),
        labour_rate=D("80"),
        labour_unit="sqm",
        margin_percent=D("30"),
    )
    assert b.material_cost == D("422.90")
    assert b.base_cost == D("542.90")
    assert b.rate == D("705.77")


def test_labour_per_sqft_is_converted_to_per_sqm():
    b = build_rate(
        unit="sqm",
        components=[],
        surface_prep=D("0"),
        labour_rate=D("10"),
        labour_unit="sqft",
        margin_percent=D("0"),
    )
    assert b.labour_per_unit == D("107.6390")
    assert b.rate == D("107.64")


def test_sqft_labour_with_materials_wastage_freight_and_margin():
    b = build_rate(
        unit="sqm",
        components=[component("1.5", "300", freight="10", wastage="5")],
        surface_prep=D("25"),
        labour_rate=D("6.5"),
        labour_unit="sqft",
        margin_percent=D("30"),
    )
    # 1.5 × 1.05 × 310 = 488.25; labour 6.5 × 10.7639 = 69.96535; base 583.21535; × 1.3
    assert b.components[0].quantity_with_wastage == D("1.575")
    assert b.material_cost == D("488.25")
    assert b.labour_per_unit == D("69.96535")
    assert b.base_cost == D("583.21535")
    assert b.rate == D("758.18")  # 758.179955 rounded once, at the end


def test_only_the_final_rate_is_rounded():
    b = build_rate(
        unit="sqm",
        components=[component("0.333", "1")],
        surface_prep=D("0"),
        labour_rate=D("0"),
        labour_unit="sqm",
        margin_percent=D("0"),
    )
    assert b.material_cost == D("0.333")
    assert b.rate == D("0.33")


@pytest.mark.parametrize(
    ("rate", "labour_unit", "system_unit", "expected"),
    [
        ("10", "sqm", "sqm", "10"),
        ("10", "sqft", "sqm", "107.639"),
        ("107.639", "sqm", "sqft", "10"),
        ("10", "sqm", "rmt", "10"),
    ],
)
def test_labour_unit_conversion(rate, labour_unit, system_unit, expected):
    assert labour_per_unit(D(rate), labour_unit, system_unit) == D(expected)


# --- through the API, with stored prices ---


@pytest.fixture
def working_sheet_system(login_as):
    """The Working sheet example stored as products, prices and a system."""
    client, headers = login_as("super_admin", email="boss@example.com")

    def product(code, name):
        r = client.post(
            "/api/products",
            json={"code": code, "name": name, "brand": "Acme", "category": "coating", "unit": "kg"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    a, b = product("P-A", "Polymer coating"), product("P-B", "Primer")
    today = date.today()
    for pid, price in ((a, "365"), (b, "95")):
        # an old price and a future price around the current one: only the current one counts
        for when, value in (
            (today - timedelta(days=400), "300"),
            (today, price),
            (today + timedelta(days=30), "999"),
        ):
            r = client.post(
                f"/api/products/{pid}/prices",
                json={"purchase_rate": value, "effective_from": when.isoformat()},
                headers=headers,
            )
            assert r.status_code == 201, r.text
    r = client.post(
        "/api/systems",
        json={
            "code": "WS-1",
            "name": "Working sheet system",
            "unit": "sqm",
            "surface_prep_per_unit": "40",
            "labour_rate": "80",
            "labour_unit": "sqm",
            "default_margin_percent": "30",
            "components": [
                {"product_id": a, "consumption_per_unit": "1.13"},
                {"product_id": b, "consumption_per_unit": "0.11"},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return client, headers, r.json()["id"]


def test_system_rate_endpoint_uses_current_prices(working_sheet_system):
    client, headers, system_id = working_sheet_system
    r = client.get(f"/api/systems/{system_id}/rate", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert D(body["rate"]) == D("705.77")
    assert [D(c["purchase_rate"]) for c in body["components"]] == [D("365"), D("95")]

    r = client.get(f"/api/systems/{system_id}/rate", params={"margin": "0"}, headers=headers)
    assert D(r.json()["rate"]) == D("542.90")

    assert D(client.get(f"/api/systems/{system_id}", headers=headers).json()["rate"]) == D("705.77")


def test_system_without_a_current_price_reports_it(login_as):
    client, headers = login_as("super_admin", email="boss@example.com")
    pid = client.post(
        "/api/products",
        json={"code": "NP", "name": "Unpriced", "unit": "kg"},
        headers=headers,
    ).json()["id"]
    sid = client.post(
        "/api/systems",
        json={
            "code": "S",
            "name": "S",
            "components": [{"product_id": pid, "consumption_per_unit": 1}],
        },
        headers=headers,
    ).json()["id"]
    assert client.get(f"/api/systems/{sid}/rate", headers=headers).status_code == 422
    body = client.get(f"/api/systems/{sid}", headers=headers).json()
    assert body["rate"] is None
    assert "Unpriced" in body["rate_error"]


def test_cost_data_hidden_without_tender_margin(working_sheet_system, make_user):
    client, headers, system_id = working_sheet_system
    from fastapi.testclient import TestClient

    from app.main import app

    make_user("sales@example.com", "sales")
    make_user("est@example.com", "estimator")
    sales, est = TestClient(app), TestClient(app)
    sales_h, est_h = login(sales, "sales@example.com"), login(est, "est@example.com")

    # sales: library.view without tender.margin -> names and final rate only
    s = sales.get(f"/api/systems/{system_id}", headers=sales_h).json()
    assert D(s["rate"]) == D("705.77")
    assert s["cost"] is None
    assert [c["product_name"] for c in s["components"]] == ["Polymer coating", "Primer"]
    flat = str(s)
    for secret in ("consumption", "wastage", "labour", "margin", "purchase", "freight", "365"):
        assert secret not in flat, secret
    assert sales.get(f"/api/systems/{system_id}/rate", headers=sales_h).status_code == 403

    products = sales.get("/api/products", headers=sales_h).json()["items"]
    assert {p["name"] for p in products} == {"Polymer coating", "Primer"}
    assert all(p["cost"] is None for p in products)
    pid = products[0]["id"]
    assert sales.get(f"/api/products/{pid}/prices", headers=sales_h).status_code == 403
    assert (
        sales.post(
            f"/api/products/{pid}/prices", json={"purchase_rate": 1}, headers=sales_h
        ).status_code
        == 403
    )

    # estimator: has tender.margin -> sees the build-up and prices
    e = est.get(f"/api/systems/{system_id}", headers=est_h).json()
    assert D(e["cost"]["default_margin_percent"]) == D("30")
    assert [D(c["consumption_per_unit"]) for c in e["cost"]["components"]] == [D("1.13"), D("0.11")]
    assert D(est.get(f"/api/systems/{system_id}/rate", headers=est_h).json()["rate"]) == D("705.77")
    prods = est.get("/api/products", headers=est_h).json()["items"]
    assert {D(p["cost"]["current_price"]["purchase_rate"]) for p in prods} == {D("365"), D("95")}
    assert len(est.get(f"/api/products/{pid}/prices", headers=est_h).json()) == 3


def test_prices_are_append_only(working_sheet_system):
    client, headers, _ = working_sheet_system
    pid = client.get("/api/products", headers=headers).json()["items"][0]["id"]
    history = client.get(f"/api/products/{pid}/prices", headers=headers).json()
    # there is no endpoint to change or delete a price row
    for method in ("put", "patch", "delete"):
        r = getattr(client, method)(
            f"/api/products/{pid}/prices/{history[0]['id']}", headers=headers
        )
        assert r.status_code in (404, 405)
