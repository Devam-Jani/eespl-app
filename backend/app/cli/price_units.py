"""python -m app.cli price-units (Prompt 38b, read-only): the price rows kept in another unit than
the product's (a bag, a drum), saved before a price per pack was converted on entry. Each is said
with whether it converts now (the pack size or a unit conversion) or not; nothing is changed."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.costing.prices import UnitNotConvertible, base_factor
from app.masters.models import Product, ProductPrice


@dataclass
class Row:
    price_id: int
    product: str
    product_unit: str
    unit: str
    convertible: bool


def find(db: Session) -> list[Row]:
    out: list[Row] = []
    q = (
        select(ProductPrice, Product)
        .join(Product, Product.id == ProductPrice.product_id)
        .where(
            ProductPrice.unit.is_not(None),
            func.lower(func.trim(ProductPrice.unit)) != func.lower(func.trim(Product.unit)),
        )
        .order_by(Product.name, ProductPrice.id)
    )
    for price, product in db.execute(q):
        try:
            base_factor(db, product, price.unit)
            ok = True
        except UnitNotConvertible:
            ok = False
        out.append(Row(price.id, product.name, product.unit, price.unit, ok))
    return out


def report(rows: list[Row]) -> str:
    ok = sum(r.convertible for r in rows)
    lines = [
        f"{len(rows)} price row(s) kept in another unit than the product's "
        f"({ok} convert, {len(rows) - ok} do not)"
    ]
    for r in rows:
        how = "converts" if r.convertible else "price unit not converted"
        lines.append(f"  #{r.price_id} {r.product}: per {r.unit}, the product per {r.product_unit} "
                     f"({how})")  # fmt: skip
    return "\n".join(lines)
