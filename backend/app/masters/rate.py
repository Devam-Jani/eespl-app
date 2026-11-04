"""Rate build-up for a waterproofing system.

    material  = Σ consumption × (1 + wastage%) × (purchase_rate + freight)
    base      = material + surface_prep + labour_per_unit
    rate      = base × (1 + margin%)                      → rounded to 2 decimals, half up

labour_per_unit converts the labour rate to the system's unit: a per-sqft labour rate on a
per-sqm system is × 10.7639 (and ÷ for the reverse). Everything is Decimal; only the final
rate is rounded, so intermediate figures in the breakdown are exact.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.margin import selling_rate, with_margin
from app.masters.models import ProductPrice, System

SQFT_PER_SQM = Decimal("10.7639")
HUNDRED = Decimal(100)
CENT = Decimal("0.01")


class MissingPriceError(ValueError):
    """A component's product has no price effective on the costing date."""

    def __init__(self, products: list[str]):
        self.products = products
        super().__init__(f"No current price for: {', '.join(products)}")


class MissingConsumptionError(MissingPriceError):
    """A component's consumption is still "to confirm": no rate until it is filled."""

    def __init__(self, products: list[str]):
        self.products = products
        ValueError.__init__(self, f"Consumption to confirm for: {', '.join(products)}")


class LabourUnitError(MissingPriceError):
    """The labour's unit does not fit the system's (₹ per sq ft on a system in rmt): no rate."""

    def __init__(self, labour_unit: str, system_unit: str):
        self.products = []
        ValueError.__init__(
            self,
            f"The labour is per {labour_unit} but the system is per {system_unit}: "
            "labour per sqm or sq ft fits a system per sqm or sq ft; otherwise give it per "
            f"{system_unit}",
        )


class PriceUnitError(MissingPriceError):
    """A price kept per a unit (a drum) that does not convert to the product's unit."""

    def __init__(self, messages: list[str]):
        self.products = messages
        ValueError.__init__(self, "; ".join(messages))


AREA = {"sqm", "sqft"}


def labour_fits(labour_unit: str, system_unit: str) -> bool:
    """Labour per sqm or sq ft on a system per sqm or sq ft (converted), or the system's unit."""
    return labour_unit == system_unit or {labour_unit, system_unit} <= AREA


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
    # a price or a consumption of 0: worked, but said (a free sample, a figure not filled in)
    warnings: list[str] = field(default_factory=list)


def labour_per_unit(labour_rate: Decimal, labour_unit: str, system_unit: str) -> Decimal:
    """The labour in the system's unit; a unit that does not fit is refused (LabourUnitError),
    except for no labour at all."""
    if not labour_fits(labour_unit, system_unit):
        if Decimal(labour_rate or 0) == 0:
            return Decimal(0)
        raise LabourUnitError(labour_unit, system_unit)
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
    basis: str = "selling",
) -> RateBreakdown:
    """The rate: (material + surface prep + labour) with the margin on the selling price,
    rate = base ÷ (1 − m/100) (app.margin); a rate working saved on the cost basis passes
    basis="cost". A selling margin of 100 % or more raises MarginTooHigh."""
    costs = []
    warnings = []
    for c in components:
        if Decimal(c.purchase_rate) == 0:
            warnings.append(f"{c.product_name}: price is 0")
        if Decimal(c.consumption_per_unit) == 0:
            warnings.append(f"{c.product_name}: consumption is 0")
        quantity =c.consumption_per_unit * (1 + c.wastage_percent / HUNDRED)
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
    if basis == "selling":
        gross = selling_rate(base, margin_percent)
    else:
        gross = with_margin(base, margin_percent, basis)
    rate = gross.quantize(CENT, rounding=ROUND_HALF_UP)
    margin_amount = rate - base
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
        rate=rate,
        warnings=warnings,
    )


def current_prices(
    db: Session, product_ids: list[int], on: date | None = None
) -> dict[int, ProductPrice]:
    """The price row in force on `on` (default today) for each product that has one: a valid
    rate contract, else the latest PO or vendor quote, else a typed price (costing.prices)."""
    from app.costing.prices import current_many  # noqa: PLC0415  (costing imports masters)

    return current_many(db, product_ids, on)


def system_rate(
    db: Session, system: System, margin_percent: Decimal | None = None, on: date | None = None
) -> RateBreakdown:
    """Build up the rate for a stored system using today's prices. Raises MissingPriceError
    (or MissingConsumptionError when a consumption is still to confirm)."""
    blank = [c.product.name for c in system.components if c.consumption_per_unit is None]
    if blank:
        raise MissingConsumptionError(blank)
    prices = current_prices(db, [c.product_id for c in system.components], on)
    missing = [c.product.name for c in system.components if c.product_id not in prices]
    if missing:
        raise MissingPriceError(missing)
    from app.costing.prices import UnitNotConvertible, base_price  # noqa: PLC0415

    per_base, wrong_unit = {}, []
    for c in system.components:
        try:  # a price kept per bag is per kg here (÷ the pack size or the unit conversion)
            per_base[c.product_id] = base_price(db, prices[c.product_id])
        except UnitNotConvertible as exc:
            wrong_unit.append(str(exc))
    if wrong_unit:
        raise PriceUnitError(wrong_unit)
    inputs = [
        ComponentInput(
            product_id=c.product_id,
            product_name=c.product.name,
            unit=c.product.unit,
            consumption_per_unit=c.consumption_per_unit,
            wastage_percent=c.wastage_percent,
            purchase_rate=per_base[c.product_id][0],
            freight_per_unit=per_base[c.product_id][1],
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
