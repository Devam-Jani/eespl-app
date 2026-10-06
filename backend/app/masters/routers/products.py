"""Products and their append-only price history.

Purchase prices and freight are cost data: they are only returned to callers holding
tender.margin (in `cost`), and only they may add prices. Everyone with library.view sees the
product itself.
"""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Category, Product, ProductPrice, SystemComponent, Unit
from app.masters.rate import current_prices
from app.masters.routers.common import (
    Limit,
    Offset,
    Search,
    conflict,
    get_or_404,
    like,
    paginate,
    unprocessable,
)
from app.masters.schemas import (
    Page,
    PriceIn,
    PriceOut,
    ProductCost,
    ProductIn,
    ProductOut,
    ProductUpdate,
)

router = APIRouter(prefix="/api/products", tags=["products"])

view = [Depends(require_permission("library.view"))]
edit = [Depends(require_permission("library.edit"))]
cost_edit = [
    Depends(require_permission("library.edit")),
    Depends(require_permission("tender.margin")),
]


def can_see_cost(principal: CurrentPrincipal) -> bool:
    return "tender.margin" in principal.permissions


def _out(db: Session, products: list[Product], with_cost: bool) -> list[ProductOut]:
    prices = current_prices(db, [p.id for p in products]) if with_cost else {}
    result = []
    for p in products:
        out = ProductOut.model_validate(p)
        if with_cost:
            price = prices.get(p.id)
            out.cost = ProductCost(current_price=PriceOut.model_validate(price) if price else None)
        result.append(out)
    return result


def _resolve_category(db: Session, category_id: int | None, name: str | None) -> int | None:
    """A material category given by id or by name (case-insensitive)."""
    if category_id is not None:
        category = db.get(Category, category_id)
        if category is None or category.kind != "material":
            raise unprocessable(f"Unknown material category id: {category_id}")
        return category.id
    if name:
        found = db.scalar(
            select(Category.id).where(
                Category.kind == "material", func.lower(Category.name) == name.strip().lower()
            )
        )
        if found is None:
            raise unprocessable(f"Unknown material category: {name}")
        return found
    return None


def _query(q: str | None, category: str | None, category_id: int | None, active: bool | None):
    query = select(Product)
    if q:
        pattern = like(q)
        query = query.where(
            or_(
                Product.code.ilike(pattern),
                Product.name.ilike(pattern),
                Product.brand.ilike(pattern),
            )
        )
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    elif category:
        query = query.where(
            Product.category_id.in_(
                select(Category.id).where(func.lower(Category.name) == category.strip().lower())
            )
        )
    if active is not None:
        query = query.where(Product.is_active == active)
    return query.order_by(Product.name, Product.id)


def _check_unit(db: Session, unit: str) -> None:
    if db.get(Unit, unit) is None:
        raise unprocessable(f"Unknown unit: {unit}")


def _check_code(db: Session, code: str, exclude: int | None = None) -> None:
    query = select(func.count()).select_from(Product).where(Product.code == code)
    if exclude is not None:
        query = query.where(Product.id != exclude)
    if db.scalar(query):
        raise conflict(f"A product with code {code} already exists")


@router.get("", dependencies=view)
def list_products(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Search = None,
    category: str | None = None,
    category_id: int | None = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ProductOut]:
    rows, total = paginate(db, _query(q, category, category_id, active), limit, offset)
    return Page(
        items=_out(db, rows, can_see_cost(principal)), total=total, limit=limit, offset=offset
    )


@router.get("/export", dependencies=view)
def export_products(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Search = None,
    category: str | None = None,
    category_id: int | None = None,
    active: bool | None = None,
):
    """Same filters as the list. Purchase rate and freight only with tender.margin."""
    with_cost = can_see_cost(principal)
    query = _query(q, category, category_id, active).limit(EXPORT_ROW_LIMIT)
    products = _out(db, list(db.scalars(query)), with_cost)
    columns = ["Code", "Name", "Brand", "Category", "Unit", "Pack size", "GST %", "Active"]
    if with_cost:
        columns += ["Purchase rate", "Freight / unit", "Price effective from"]
    rows = []
    for p in products:
        row = [p.code, p.name, p.brand, p.category, p.unit, p.pack_size, p.gst_percent,
               p.is_active]  # fmt: skip
        if with_cost:
            price = p.cost.current_price if p.cost else None
            if price:
                row += [price.purchase_rate, price.freight_per_unit, price.effective_from]
            else:
                row += [None, None, None]
        rows.append(row)
    return xlsx_response("products", columns, rows)


@router.get("/{product_id}", dependencies=view)
def get_product(product_id: int, db: DbSession, principal: CurrentPrincipal) -> ProductOut:
    product = get_or_404(db, Product, product_id, "Product")
    return _out(db, [product], can_see_cost(principal))[0]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_product(
    body: ProductIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ProductOut:
    _check_unit(db, body.unit)
    _check_code(db, body.code)
    fields = body.model_dump(exclude={"category", "category_id"})
    fields["category_id"] = _resolve_category(db, body.category_id, body.category)
    product = Product(**fields, created_by=principal.user.id)
    db.add(product)
    db.flush()
    db.refresh(product)  # numeric columns come back at their stored scale
    audit.record(db, "product.create", "product", product.id, user_id=principal.user.id,
                 after=audit.model_snapshot(product), ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return _out(db, [product], can_see_cost(principal))[0]


@router.patch("/{product_id}", dependencies=edit)
def update_product(
    product_id: int,
    body: ProductUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ProductOut:
    product = get_or_404(db, Product, product_id, "Product")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items()
               if v is not None or k in ("brand", "pack_size", "category_id")}  # fmt: skip
    if "category" in changes or "category_id" in changes:
        changes["category_id"] = _resolve_category(
            db, changes.get("category_id"), changes.pop("category", None)
        )
    if "unit" in changes:
        _check_unit(db, changes["unit"])
    if "code" in changes:
        _check_code(db, changes["code"], exclude=product.id)
    before = audit.model_snapshot(product)
    for field, value in changes.items():
        setattr(product, field, value)
    db.flush()
    after = audit.model_snapshot(product)
    if after != before:
        audit.record(db, "product.update", "product", product.id, user_id=principal.user.id,
                     before=before, after=after, ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return _out(db, [product], can_see_cost(principal))[0]


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit)
def delete_product(
    product_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    product = get_or_404(db, Product, product_id, "Product")
    used = db.scalar(
        select(func.count()).select_from(SystemComponent)
        .where(SystemComponent.product_id == product.id)
    )  # fmt: skip
    if used:
        raise conflict("This product is used in a system; remove it there or deactivate it")
    audit.record(db, "product.delete", "product", product.id, user_id=principal.user.id,
                 before=audit.model_snapshot(product), ip=audit.client_ip(request))  # fmt: skip
    db.delete(product)
    db.commit()


@router.get("/{product_id}/prices", dependencies=[Depends(require_permission("tender.margin"))])
def price_history(product_id: int, db: DbSession) -> list[PriceOut]:
    get_or_404(db, Product, product_id, "Product")
    rows = db.scalars(
        select(ProductPrice)
        .where(ProductPrice.product_id == product_id)
        .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
    )
    return [PriceOut.model_validate(p) for p in rows]


@router.post("/{product_id}/prices", status_code=status.HTTP_201_CREATED, dependencies=cost_edit)
def add_price(
    product_id: int,
    body: PriceIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> PriceOut:
    """Prices are never edited; a change is a new row with its own effective date."""
    get_or_404(db, Product, product_id, "Product")
    price = ProductPrice(product_id=product_id, **body.model_dump(), created_by=principal.user.id)
    db.add(price)
    db.flush()
    audit.record(db, "product_price.create", "product", product_id, user_id=principal.user.id,
                 after=audit.model_snapshot(price), ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(price)
    return PriceOut.model_validate(price)
