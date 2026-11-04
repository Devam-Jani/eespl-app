# ruff: noqa: E501  (the queries and messages read better unwrapped)
"""The master price list: every product's price history (price, unit, date, source, who entered
it), the current price (a valid rate contract, else the latest PO or vendor quote, else a typed
price; a price per bag kept per the product's unit), freight per unit with its own history, and the
"last price used" shown wherever a price is entered (rate working, PO, rate contract), with a
change of more than 10 % (setting) flagged.

Prices are cost data: the history and the master list are for tender.margin; the last-price hint
also reaches whoever enters prices (purchase, rate contracts, payables)."""

import re
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


def _contract_id(p: ProductPrice) -> int | None:
    """The rate contract a price row came from ("RC 12 v2": 12), else None."""
    m = re.match(r"RC (\d+)\b", p.ref or "") if p.source == "rate_contract" else None
    return int(m.group(1)) if m else None


def _valid_contracts(db: Session, product_ids, on: date) -> tuple[dict, set[int]]:
    """{contract id: contract} of the rate contracts in force on `on`, and every contract id the
    products have (valid or not)."""
    from app.sitecontrol.models import RateContract  # noqa: PLC0415

    rows = db.scalars(select(RateContract).where(RateContract.product_id.in_(list(product_ids)))).all()
    valid = {c.id: c for c in rows if c.is_active and c.valid_from <= on <= c.valid_till}
    return valid, {c.id for c in rows}


def _tier(p: ProductPrice, valid: dict, known: set[int]) -> int:
    """0 a rate contract in force; 1 a PO or a vendor quote (or a contract price with no contract
    record); 2 a typed price; 3 the price of a contract no longer in force."""
    rc = _contract_id(p)
    if rc is not None and rc in valid:
        return 0
    if rc is not None and rc in known:
        return 3
    return 2 if p.source == "manual" else 1


def current_many(db: Session, product_ids, on: date | None = None) -> dict[int, ProductPrice]:
    """The price in force on `on` (default today) per product, in this order: a valid rate
    contract, then the latest PO or vendor quote, then a typed price (a one-off price typed in a
    working never beats a contract); the newest within each."""
    ids = list(product_ids)
    if not ids:
        return {}
    on = on or ist_today()
    valid, known = _valid_contracts(db, ids, on)
    best: dict[int, tuple[int, ProductPrice]] = {}
    for p in db.scalars(
        select(ProductPrice)
        .where(ProductPrice.product_id.in_(ids), ProductPrice.effective_from <= on)
        .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
    ):
        tier = _tier(p, valid, known)
        if p.product_id not in best or tier < best[p.product_id][0]:
            best[p.product_id] = (tier, p)  # newest first: the first of a tier is its newest
    return {pid: p for pid, (_t, p) in best.items()}


def current(db: Session, product_id: int, on: date | None = None) -> ProductPrice | None:
    """The price in force on `on` (default today): see current_many."""
    return current_many(db, [product_id], on).get(product_id)


def basis_of(db: Session, p: ProductPrice, on: date | None = None) -> str:
    """Which kind of price it is, said beside the price used."""
    on = on or ist_today()
    valid, known = _valid_contracts(db, [p.product_id], on)
    tier = _tier(p, valid, known)
    if tier == 0:
        return f"rate contract {p.ref} (valid till {valid[_contract_id(p)].valid_till:%d-%m-%Y})"
    if tier == 3:
        return f"rate contract {p.ref}, no longer in force"
    if tier == 1:
        return f"latest PO or vendor quote{f' ({p.ref})' if p.ref else ''}"
    return "typed price"


# --- a price per bag or pack: per the product's base unit -----------------------------------------


def per_unit_price(v) -> Decimal:
    """A price per the product's unit: 4 decimals (₹2,500 a 30 kg bag = ₹83.3333/kg); money totals
    round once at the end."""
    return Decimal(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


class UnitNotConvertible(ValueError):
    """A price or freight per a unit that does not convert to the product's unit."""


def base_factor(db: Session, product: Product, unit: str | None) -> Decimal:
    """How many of the product's unit one `unit` is: a 25 kg bag is 25 (the pack size), else the
    unit conversions (Settings); blank or the product's own unit is 1. Raises UnitNotConvertible."""
    from app.masters.conversions import ConversionError, convert  # noqa: PLC0415

    u = " ".join((unit or "").lower().split())
    base = (product.unit or "").lower()
    if not u or u == base:
        return Decimal(1)
    pack = " ".join((product.pack_unit or "").lower().split())
    if product.pack_size and Decimal(product.pack_size) > 0 and u in {pack, "pack"} - {""}:
        return Decimal(product.pack_size)
    try:
        return convert(db, Decimal(1), u, product.unit, product.id)
    except ConversionError:
        raise UnitNotConvertible(
            f"{product.name} is priced per {product.unit}: a price per {unit} does not convert "
            f"(set its pack size or a unit conversion)"
        ) from None


def base_price(db: Session, p: ProductPrice) -> tuple[Decimal, Decimal]:
    """(price, freight) per the product's unit, unrounded: a row kept per bag is ÷ the pack size."""
    product = db.get(Product, p.product_id)
    f = base_factor(db, product, p.unit)
    return Decimal(p.purchase_rate) / f, Decimal(p.freight_per_unit or 0) / f


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
        "basis": basis_of(db, p),  # rate contract / latest PO or vendor quote / typed price
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
    return_existing: bool = False,
) -> ProductPrice | None:
    """Add a price to the history (a PO sent, a rate contract agreed): never edits one; the same
    reference at the same rate on the same date again (a retry) adds nothing (None, or that row
    with return_existing). A price per bag (unit) is kept per the product's unit (UnitNotConvertible
    when it does not convert)."""
    if source not in PRICE_SOURCES:
        raise ValueError(source)
    if unit:
        product = db.get(Product, product_id)
        f = base_factor(db, product, unit)
        if f != 1:
            note = f"entered ₹{rate} per {unit} ({f.normalize():f} {product.unit})" + (f"; {note}" if note else "")
            rate, freight = Decimal(rate) / f, Decimal(freight) / f
        unit = product.unit
    rate, freight = per_unit_price(rate), per_unit_price(freight)
    on = on or ist_today()
    if ref:
        same = db.scalar(
            select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.ref == ref,
                ProductPrice.purchase_rate == rate,
                ProductPrice.effective_from == on,
            )
        )
        if same is not None:
            return same if return_existing else None
    p = ProductPrice(
        product_id=product_id,
        purchase_rate=rate,
        freight_per_unit=freight,
        effective_from=on,
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
    """A new price (never an edit); the response says how it compares with the last one used. A
    price per bag or pack is kept per the product's unit (÷ the pack size or the unit conversion);
    a unit that does not convert is refused."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    rate, unit, note = _per_base(db, product, body.rate, body.unit, body.note)
    flag = check(db, product_id, rate)
    p = ProductPrice(
        product_id=product_id,
        purchase_rate=rate,
        unit=unit,
        effective_from=body.effective_from or ist_today(),
        source=body.source,
        vendor_id=body.vendor_id,
        ref=body.ref,
        note=note,
        created_by=principal.user.id,
    )
    db.add(p)
    db.flush()
    record(db, request, principal, "product_price.create", "product", product_id,
           after={"rate": str(rate), "entered": f"{body.rate} per {body.unit or unit}", "source": body.source, "ref": body.ref,
                  "change_percent": str(flag["change_percent"])})  # fmt: skip
    db.commit()
    return jsonable_encoder(price_out(db, p) | {"check": flag})


def _per_base(db: Session, product: Product, value: Decimal, unit: str | None, note: str | None):
    """(value per the product's unit to 4 decimals, the product's unit, the note saying what was
    entered); 422 for a unit that does not convert."""
    try:
        f = base_factor(db, product, unit)
    except UnitNotConvertible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    if f == 1:
        return Decimal(value), product.unit if unit else None, note
    entered = f"entered ₹{value} per {unit} ({f.normalize():f} {product.unit})"
    per = per_unit_price(Decimal(value) / f)
    return per, product.unit, entered + (f"; {note}" if note else "")


class FreightIn(BaseModel):
    per_unit: Decimal = Field(ge=0)
    unit: str | None = Field(None, max_length=20)  # per bag: kept per the product's unit
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
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    per_unit, _unit, note = _per_base(db, product, body.per_unit, body.unit, body.note)
    f = FreightRate(
        product_id=product_id,
        per_unit=per_unit,
        vendor_id=body.vendor_id,
        store_id=body.store_id,
        effective_from=body.effective_from or ist_today(),
        note=note,
        created_by=principal.user.id,
    )
    db.add(f)
    db.flush()
    record(db, request, principal, "freight_rate.create", "product", product_id,
           after={"per_unit": str(per_unit), "entered": f"{body.per_unit} per {body.unit or product.unit}", "vendor_id": body.vendor_id,
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
