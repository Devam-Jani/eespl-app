"""The master price list: every product's price history (price, unit, date, source, who entered
it), the current price (the newest in force), freight per unit with its own history, and the
"last price used" shown wherever a price is entered (rate working, PO, rate contract), with a
change of more than 10 % (setting) flagged.

Prices are cost data: the history and the master list are for tender.margin; the last-price hint
also reaches whoever enters prices (purchase, rate contracts, payables)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentPrincipal, require_permission
from app.costing.models import CostingSettings, FreightRate
from app.db import DbSession
from app.execution.common import record
from app.masters.models import PRICE_SOURCES, Product, ProductPrice, Vendor
from app.models import User
from app.timefmt import ist_today

router = APIRouter(prefix="/api/prices", tags=["prices"])
HUNDRED = Decimal(100)
ENTERS_PRICES = ("tender.margin", "ratecontract.edit", "payables.edit", "indent.approve")


def settings(db: Session) -> CostingSettings:
    s = db.get(CostingSettings, 1)
    if s is None:
        s = CostingSettings(
            id=1,
            price_change_flag_percent=Decimal(10),
            library_diff_flag_percent=Decimal(15),
            calloff_tolerance_percent=Decimal(5),
            day_hours=Decimal(8),
        )
        db.add(s)
        db.flush()
    return s


def _who(db: Session, uid) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.full_name if u else None


def history(db: Session, product_id: int) -> list[ProductPrice]:
    return list(
        db.scalars(
            select(ProductPrice)
            .where(ProductPrice.product_id == product_id)
            .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
        )
    )


def current(db: Session, product_id: int, on: date | None = None) -> ProductPrice | None:
    """The newest price in force on `on` (default today)."""
    return db.scalar(
        select(ProductPrice)
        .where(
            ProductPrice.product_id == product_id,
            ProductPrice.effective_from <= (on or ist_today()),
        )
        .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
        .limit(1)
    )


def price_out(db: Session, p: ProductPrice | None) -> dict | None:
    if p is None:
        return None
    product = db.get(Product, p.product_id)
    vendor = db.get(Vendor, p.vendor_id) if p.vendor_id else None
    return {
        "id": p.id,
        "rate": p.purchase_rate,
        "unit": p.unit or (product.unit if product else None),
        "freight_per_unit": p.freight_per_unit,
        "date": p.effective_from,
        "source": p.source,
        "ref": p.ref,
        "vendor": vendor.name if vendor else None,
        "by": _who(db, p.created_by),
        "note": p.note,
        "entered_at": p.created_at,
    }


def change_percent(old: Decimal | None, new: Decimal | None) -> Decimal | None:
    if old is None or new is None or Decimal(old) == 0:
        return None
    return ((Decimal(new) - Decimal(old)) / Decimal(old) * HUNDRED).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def check(db: Session, product_id: int, rate: Decimal | None, exclude_id: int | None = None):
    """The last price used for the product (with its date and who entered it) and whether `rate`
    changes it by more than the setting (10 %)."""
    q = select(ProductPrice).where(ProductPrice.product_id == product_id)
    if exclude_id:
        q = q.where(ProductPrice.id != exclude_id)
    last = db.scalar(
        q.where(ProductPrice.effective_from <= ist_today())
        .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
        .limit(1)
    )
    limit = Decimal(settings(db).price_change_flag_percent)
    pct = change_percent(last.purchase_rate if last else None, rate)
    return {
        "product_id": product_id,
        "last": price_out(db, last),
        "rate": rate,
        "change_percent": pct,
        "limit_percent": limit,
        "flagged": pct is not None and abs(pct) > limit,
    }


def record_price(
    db: Session,
    product_id: int,
    rate: Decimal,
    *,
    source: str,
    user_id=None,
    ref: str | None = None,
    vendor_id: int | None = None,
    unit: str | None = None,
    on: date | None = None,
    note: str | None = None,
    freight: Decimal = Decimal(0),
) -> ProductPrice | None:
    """Add a price to the history (a PO sent, a rate contract agreed): never edits one; the same
    reference at the same rate again (a retry) adds nothing."""
    if source not in PRICE_SOURCES:
        raise ValueError(source)
    rate = Decimal(rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if ref and db.scalar(
        select(ProductPrice.id).where(
            ProductPrice.product_id == product_id,
            ProductPrice.ref == ref,
            ProductPrice.purchase_rate == rate,
        )
    ):
        return None
    p = ProductPrice(
        product_id=product_id,
        purchase_rate=rate,
        freight_per_unit=freight,
        effective_from=on or ist_today(),
        source=source,
        ref=ref,
        vendor_id=vendor_id,
        unit=unit,
        note=note,
        created_by=user_id,
    )
    db.add(p)
    db.flush()
    return p


def freight_for(
    db: Session,
    product_id: int,
    vendor_id: int | None = None,
    store_id: int | None = None,
    on: date | None = None,
) -> FreightRate | None:
    """The freight per unit in force: vendor + godown, then vendor, then the product alone."""
    on = on or ist_today()
    rows = db.scalars(
        select(FreightRate)
        .where(
            FreightRate.product_id == product_id,
            FreightRate.effective_from <= on,
            or_(FreightRate.vendor_id.is_(None), FreightRate.vendor_id == vendor_id),
            or_(FreightRate.store_id.is_(None), FreightRate.store_id == store_id),
        )
        .order_by(FreightRate.effective_from.desc(), FreightRate.id.desc())
    ).all()

    def rank(f: FreightRate) -> int:
        return (2 if f.vendor_id else 0) + (1 if f.store_id else 0)

    return max(rows, key=rank, default=None) if rows else None


def freight_out(db: Session, f: FreightRate) -> dict:
    from app.material.models import Store  # noqa: PLC0415

    vendor = db.get(Vendor, f.vendor_id) if f.vendor_id else None
    store = db.get(Store, f.store_id) if f.store_id else None
    return {
        "id": f.id,
        "per_unit": f.per_unit,
        "date": f.effective_from,
        "vendor": vendor.name if vendor else None,
        "store": store.name if store else None,
        "by": _who(db, f.created_by),
        "note": f.note,
    }


# --- API -----------------------------------------------------------------------------------------

CostView = Annotated[str, Depends(require_permission("tender.margin"))]


def _enters_prices(principal) -> None:
    if not any(principal.permissions.get(c) for c in ENTERS_PRICES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Prices are not for your role")


@router.get("/last")
def last_price(
    product_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    rate: Decimal | None = None,
    exclude_id: int | None = None,
) -> dict:
    """The hint beside a price being entered: the last price used, its date and who entered it,
    and the change flag."""
    _enters_prices(principal)
    if db.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    # exclude_id: the price being shown itself (it was just entered), so the hint is the one before
    return jsonable_encoder(check(db, product_id, rate, exclude_id))


@router.get("/products/{product_id}")
def product_prices(product_id: int, db: DbSession, _: CostView) -> dict:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    rows = history(db, product_id)
    out = []
    for i, p in enumerate(rows):
        prev = rows[i + 1] if i + 1 < len(rows) else None
        pct = change_percent(prev.purchase_rate if prev else None, p.purchase_rate)
        limit = Decimal(settings(db).price_change_flag_percent)
        out.append(
            price_out(db, p)
            | {"change_percent": pct, "flagged": pct is not None and abs(pct) > limit}
        )
    freight = db.scalars(
        select(FreightRate)
        .where(FreightRate.product_id == product_id)
        .order_by(FreightRate.effective_from.desc(), FreightRate.id.desc())
    ).all()
    cur = current(db, product_id)
    f = freight_for(db, product_id)
    return jsonable_encoder(
        {
            "product": {"id": product.id, "code": product.code, "name": product.name,
                        "unit": product.unit, "brand": product.brand},
            "current": price_out(db, cur),
            "freight_current": freight_out(db, f) if f else None,
            "history": out,
            "freight": [freight_out(db, x) for x in freight],
            "limit_percent": settings(db).price_change_flag_percent,
        }
    )  # fmt: skip


class PriceIn(BaseModel):
    rate: Decimal = Field(ge=0)
    unit: str | None = Field(None, max_length=20)
    effective_from: date | None = None
    source: str = Field("manual", pattern="^(vendor_quote|rate_contract|po|manual)$")
    vendor_id: int | None = None
    ref: str | None = Field(None, max_length=60)
    note: str | None = None


@router.post("/products/{product_id}", status_code=status.HTTP_201_CREATED)
def add_price(
    product_id: int,
    body: PriceIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: CostView,
    __: Annotated[str, Depends(require_permission("library.edit"))],
) -> dict:
    """A new price (never an edit); the response says how it compares with the last one used."""
    if db.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    flag = check(db, product_id, body.rate)
    p = ProductPrice(
        product_id=product_id,
        purchase_rate=body.rate,
        unit=body.unit,
        effective_from=body.effective_from or ist_today(),
        source=body.source,
        vendor_id=body.vendor_id,
        ref=body.ref,
        note=body.note,
        created_by=principal.user.id,
    )
    db.add(p)
    db.flush()
    record(db, request, principal, "product_price.create", "product", product_id,
           after={"rate": str(body.rate), "source": body.source, "ref": body.ref,
                  "change_percent": str(flag["change_percent"])})  # fmt: skip
    db.commit()
    return jsonable_encoder(price_out(db, p) | {"check": flag})


class FreightIn(BaseModel):
    per_unit: Decimal = Field(ge=0)
    vendor_id: int | None = None
    store_id: int | None = None
    effective_from: date | None = None
    note: str | None = None


@router.post("/products/{product_id}/freight", status_code=status.HTTP_201_CREATED)
def add_freight(
    product_id: int,
    body: FreightIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: CostView,
    __: Annotated[str, Depends(require_permission("library.edit"))],
) -> dict:
    if db.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    f = FreightRate(
        product_id=product_id,
        per_unit=body.per_unit,
        vendor_id=body.vendor_id,
        store_id=body.store_id,
        effective_from=body.effective_from or ist_today(),
        note=body.note,
        created_by=principal.user.id,
    )
    db.add(f)
    db.flush()
    record(db, request, principal, "freight_rate.create", "product", product_id,
           after={"per_unit": str(body.per_unit), "vendor_id": body.vendor_id,
                  "store_id": body.store_id})  # fmt: skip
    db.commit()
    return jsonable_encoder(freight_out(db, f))


class SettingsIn(BaseModel):
    price_change_flag_percent: Decimal | None = Field(None, ge=0, le=100)
    library_diff_flag_percent: Decimal | None = Field(None, ge=0, le=100)
    calloff_tolerance_percent: Decimal | None = Field(None, ge=0, le=100)
    day_hours: Decimal | None = Field(None, gt=0, le=24)
    margin_basis: str | None = Field(None, pattern="^(cost|selling)$")


def _settings_out(s: CostingSettings) -> dict:
    return {
        "price_change_flag_percent": s.price_change_flag_percent,
        "library_diff_flag_percent": s.library_diff_flag_percent,
        "calloff_tolerance_percent": s.calloff_tolerance_percent,
        "day_hours": s.day_hours,
        "margin_basis": s.margin_basis or "selling",
    }


@router.get("/settings")
def get_settings(db: DbSession, principal: CurrentPrincipal) -> dict:
    return jsonable_encoder(_settings_out(settings(db)))


@router.put("/settings")
def put_settings(
    body: SettingsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("process.rules"))],
) -> dict:
    s = settings(db)
    before = _settings_out(s)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    record(db, request, principal, "costing.settings", "costing_settings", 1,
           before=jsonable_encoder(before), after=jsonable_encoder(_settings_out(s)))  # fmt: skip
    db.commit()
    return jsonable_encoder(_settings_out(s))
