"""Rate build-up for a waterproofing system.

    material  = Σ consumption × (1 + wastage%) × (purchase_rate + freight)
    base      = material + surface_prep + labour_per_unit
    rate      = base × (1 + margin%)                      → rounded to 2 decimals, half up

labour_per_unit converts the labour rate to the system's unit: a per-sqft labour rate on a
per-sqm system is × 10.7639 (and ÷ for the reverse). Everything is Decimal; only the final
rate is rounded, so intermediate figures in the breakdown are exact.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import ProductPrice, System

SQFT_PER_SQM = Decimal("10.7639")
HUNDRED = Decimal(100)
CENT = Decimal("0.01")


class MissingPriceError(ValueError):
    """A component's product has no price effective on the costing date."""

    def __init__(self, products: list[str]):
        self.products = products
        super().__init__(f"No current price for: {', '.join(products)}")


@dataclass(frozen=True)
class ComponentInput:
    product_id: int
    product_name: str
    unit: str
    consumption_per_unit: Decimal
    wastage_percent: Decimal
    purchase_rate: Decimal
    freight_per_unit: Decimal


@dataclass(frozen=True)
class ComponentCost:
    product_id: int
    product_name: str
    unit: str
    consumption_per_unit: Decimal
    wastage_percent: Decimal
    quantity_with_wastage: Decimal
    purchase_rate: Decimal
    freight_per_unit: Decimal
    landed_rate: Decimal
    cost: Decimal


@dataclass(frozen=True)
class RateBreakdown:
    unit: str
    components: list[ComponentCost]
    material_cost: Decimal
    surface_prep: Decimal
    labour_rate: Decimal
    labour_unit: str
    labour_per_unit: Decimal
    base_cost: Decimal
    margin_percent: Decimal
    margin_amount: Decimal
    rate: Decimal  # the only rounded figure


def labour_per_unit(labour_rate: Decimal, labour_unit: str, system_unit: str) -> Decimal:
    if labour_unit == "sqft" and system_unit == "sqm":
        return labour_rate * SQFT_PER_SQM
    if labour_unit == "sqm" and system_unit == "sqft":
        return labour_rate / SQFT_PER_SQM
    return labour_rate


def build_rate(
    *,
    unit: str,
    components: list[ComponentInput],
    surface_prep: Decimal,
    labour_rate: Decimal,
    labour_unit: str,
    margin_percent: Decimal,
) -> RateBreakdown:
    costs = []
    for c in components:
        quantity = c.consumption_per_unit * (1 + c.wastage_percent / HUNDRED)
        landed = c.purchase_rate + c.freight_per_unit
        costs.append(
            ComponentCost(
                product_id=c.product_id,
                product_name=c.product_name,
                unit=c.unit,
                consumption_per_unit=c.consumption_per_unit,
                wastage_percent=c.wastage_percent,
                quantity_with_wastage=quantity,
                purchase_rate=c.purchase_rate,
                freight_per_unit=c.freight_per_unit,
                landed_rate=landed,
                cost=quantity * landed,
            )
        )
    material = sum((c.cost for c in costs), Decimal(0))
    labour = labour_per_unit(labour_rate, labour_unit, unit)
    base = material + surface_prep + labour
    margin_amount = base * margin_percent / HUNDRED
    return RateBreakdown(
        unit=unit,
        components=costs,
        material_cost=material,
        surface_prep=surface_prep,
        labour_rate=labour_rate,
        labour_unit=labour_unit,
        labour_per_unit=labour,
        base_cost=base,
        margin_percent=margin_percent,
        margin_amount=margin_amount,
        rate=(base + margin_amount).quantize(CENT, rounding=ROUND_HALF_UP),
    )


def current_prices(
    db: Session, product_ids: list[int], on: date | None = None
) -> dict[int, ProductPrice]:
    """The price row in force on `on` (default today) for each product that has one."""
    if not product_ids:
        return {}
    on = on or date.today()
    rows = db.scalars(
        select(ProductPrice)
        .where(ProductPrice.product_id.in_(product_ids), ProductPrice.effective_from <= on)
        .order_by(
            ProductPrice.product_id,
            ProductPrice.effective_from.desc(),
            ProductPrice.id.desc(),
        )
        .distinct(ProductPrice.product_id)
    )
    return {p.product_id: p for p in rows}


def system_rate(
    db: Session, system: System, margin_percent: Decimal | None = None, on: date | None = None
) -> RateBreakdown:
    """Build up the rate for a stored system using today's prices. Raises MissingPriceError."""
    prices = current_prices(db, [c.product_id for c in system.components], on)
    missing = [c.product.name for c in system.components if c.product_id not in prices]
    if missing:
        raise MissingPriceError(missing)
    inputs = [
        ComponentInput(
            product_id=c.product_id,
            product_name=c.product.name,
            unit=c.product.unit,
            consumption_per_unit=c.consumption_per_unit,
            wastage_percent=c.wastage_percent,
            purchase_rate=prices[c.product_id].purchase_rate,
            freight_per_unit=prices[c.product_id].freight_per_unit,
        )
        for c in system.components
    ]
    return build_rate(
        unit=system.unit,
        components=inputs,
        surface_prep=system.surface_prep_per_unit,
        labour_rate=system.labour_rate,
        labour_unit=system.labour_unit,
        margin_percent=system.default_margin_percent if margin_percent is None else margin_percent,
    )
