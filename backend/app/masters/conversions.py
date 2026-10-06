"""Unit conversions.

A conversion row says: quantity in `to_unit` = quantity in `from_unit` × factor. Rows work in
both directions (the reverse uses 1 / factor) and can be chained (bag -> kg -> ...). A row with
a product_id applies only to that product ("1 bag of Chryso Armourcrete = 20 kg") and is
preferred over a generic row for the same pair of units.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.masters.models import UnitConversion


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    from_unit: str
    to_unit: str
    factor: Decimal
    product_id: int | None = None


def convert_with(
    rules: Iterable[Rule],
    qty: Decimal,
    from_unit: str,
    to_unit: str,
    product_id: int | None = None,
) -> Decimal:
    """Convert `qty` using the given rules. Finds the shortest chain of conversions; for each
    pair of units a product-specific rule wins over a generic one. Raises ConversionError when
    no chain exists."""
    if from_unit == to_unit:
        return qty
    edges: dict[str, dict[str, tuple[Decimal, bool]]] = {}

    def add(a: str, b: str, factor: Decimal, specific: bool) -> None:
        current = edges.setdefault(a, {}).get(b)
        if current is None or (specific and not current[1]):
            edges[a][b] = (factor, specific)

    for r in rules:
        if r.product_id is not None and r.product_id != product_id:
            continue
        specific = r.product_id is not None
        add(r.from_unit, r.to_unit, r.factor, specific)
        add(r.to_unit, r.from_unit, Decimal(1) / r.factor, specific)

    # breadth-first: the fewest conversion steps
    queue: deque[tuple[str, Decimal]] = deque([(from_unit, Decimal(1))])
    seen = {from_unit}
    while queue:
        unit, factor = queue.popleft()
        for nxt, (step, _) in edges.get(unit, {}).items():
            if nxt in seen:
                continue
            if nxt == to_unit:
                return qty * factor * step
            seen.add(nxt)
            queue.append((nxt, factor * step))
    product = f" for product {product_id}" if product_id is not None else ""
    raise ConversionError(f"No conversion from {from_unit} to {to_unit}{product}")


def convert(
    db: Session,
    qty: Decimal,
    from_unit: str,
    to_unit: str,
    product_id: int | None = None,
) -> Decimal:
    """convert(qty, from, to, product=None) using the conversions stored in the database."""
    rows = db.scalars(
        select(UnitConversion).where(
            or_(UnitConversion.product_id.is_(None), UnitConversion.product_id == product_id)
        )
    )
    rules = [Rule(r.from_unit, r.to_unit, r.factor, r.product_id) for r in rows]
    return convert_with(rules, qty, from_unit, to_unit, product_id)
