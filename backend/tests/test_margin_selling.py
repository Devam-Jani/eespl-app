# ruff: noqa: E501
"""Prompt 38, Part 1: the margin is on the selling price everywhere, rate = cost ÷ (1 − m/100)."""

from decimal import Decimal as D

import pytest

from app.margin import MarginTooHigh, selling_rate, with_margin
from app.masters.rate import ComponentInput, build_rate
from app.tenders import pricing


def _one(cost: str) -> list[ComponentInput]:
    return [
        ComponentInput(
            product_id=1,
            product_name="Invented coating",
            unit="kg",
            consumption_per_unit=D(1),
            wastage_percent=D(0),
            purchase_rate=D(cost),
            freight_per_unit=D(0),
        )
    ]


@pytest.mark.parametrize(
    ("cost", "margin", "rate"),
    [("100", "25", "133.33"), ("542.90", "30", "775.57"), ("320", "20", "400.00")],
)
def test_the_three_examples(cost, margin, rate):
    assert pricing.rate_from_margin(D(cost), D(margin)) == D(rate)
    b = build_rate(
        unit="sqm",
        components=_one(cost),
        surface_prep=D(0),
        labour_rate=D(0),
        labour_unit="sqm",
        margin_percent=D(margin),
    )
    assert b.rate == D(rate) and b.margin_amount == D(rate) - D(cost)
    assert (b.margin_amount / b.rate * 100).quantize(D("0.1")) == D(margin).quantize(
        D("0.1")
    )  # the margin is that share of the rate


def test_100_percent_or_more_is_refused():
    with pytest.raises(MarginTooHigh):
        selling_rate(D(100), D(100))
    with pytest.raises(MarginTooHigh):
        pricing.rate_from_margin(D(100), D(150))
    assert with_margin(D(100), D(100)) is None


def test_a_working_saved_on_the_cost_basis_keeps_it():
    assert with_margin(D(100), D(25), "cost") == D(125)
    b = build_rate(
        unit="sqm",
        components=_one("100"),
        surface_prep=D(0),
        labour_rate=D(0),
        labour_unit="sqm",
        margin_percent=D(25),
        basis="cost",
    )
    assert b.rate == D("125.00")


def test_the_margin_fields_refuse_100(login_as):
    c, h = login_as("super_admin", email="sa-margin@example.com")
    r = c.post("/api/tenders/0/boq/margin", json={"margin_percent": "100"}, headers=h)
    assert r.status_code == 422 and "less than 100" in str(r.json()["detail"])
