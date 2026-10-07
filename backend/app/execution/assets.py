"""Tools, assets and equipment: where each one is, movements (issue to a site, return to a
store), equipment usage and its cost per site.

asset.view sees assets at the caller's sites (scope all: everything, including the stores);
asset.edit with scope all keeps the register, moves assets and records usage.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import service as svc
from app.execution.common import names, record, save_upload, send_file
from app.execution.models import Asset, AssetMovement, EquipmentUsage
from app.masters.models import CompanyProfile, Vendor
from app.material import service as material
from app.material.models import Store
from app.sites.models import Site

router = APIRouter(prefix="/api/execution", tags=["execution"])
AssetView = Annotated[str, Depends(require_permission("asset.view"))]


class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Literal["tool", "equipment", "machine", "vehicle"] = "tool"
    make: str | None = None
    model: str | None = None
    serial_no: str | None = None
    purchase_date: date | None = None
    purchase_value: Decimal | None = Field(default=None, ge=0)
    ownership: Literal["own", "hired"] = "own"
    vendor_id: int | None = None
    rate_per_hour: Decimal | None = Field(default=None, ge=0)
    rate_per_day: Decimal | None = Field(default=None, ge=0)
    status: Literal["available", "at_site", "repair", "lost", "disposed"] | None = None
    store_id: int | None = None  # where a new asset is kept (default: the godown)
    is_active: bool = True


def _where(db, a: Asset) -> str:
    if a.site_id:
        s = db.get(Site, a.site_id)
        return f"{s.code} {s.name}"
    if a.store_id:
        return db.get(Store, a.store_id).name
    return "—"


def _asset_out(db, a: Asset, overdue_days: int | None = None) -> dict:
    days = (svc.today() - a.located_since).days if a.located_since else None
    return {
        "id": a.id,
        "code": a.code,
        "name": a.name,
        "category": a.category,
        "make": a.make,
        "model": a.model,
        "serial_no": a.serial_no,
        "purchase_date": a.purchase_date,
        "purchase_value": a.purchase_value,
        "ownership": a.ownership,
        "vendor_id": a.vendor_id,
        "vendor_name": a.vendor.name if a.vendor else None,
        "rate_per_hour": a.rate_per_hour,
        "rate_per_day": a.rate_per_day,
        "status": a.status,
        "store_id": a.store_id,
        "site_id": a.site_id,
        "location": _where(db, a),
        "located_since": a.located_since,
        "days_here": days,
        "overdue": bool(
            a.site_id and overdue_days is not None and days is not None and days > overdue_days
        ),
        "is_active": a.is_active,
    }


def _overdue_days(db) -> int:
    p = db.get(CompanyProfile, 1)
    return p.asset_overdue_days if p else 30


def _edit(principal):
    if principal.permissions.get("asset.edit") != "all":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The asset register needs asset.edit (all)")


def _visible(db, aid, principal, scope) -> Asset:
    a = db.get(Asset, aid)
    if a is None or not (
        scope == "all" or (a.site_id and material.covers_site(db, scope, principal, a.site_id))
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    return a


@router.get("/assets")
def list_assets(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: AssetView,
    site_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    category: str | None = None,
    q: str | None = None,
    overdue: bool = False,
) -> list[dict]:
    query = select(Asset)
    if scope != "all":
        query = query.where(Asset.site_id.in_(material.assigned_sites(principal)))
    if site_id is not None:
        query = query.where(Asset.site_id == site_id)
    if status_:
        query = query.where(Asset.status == status_)
    if category:
        query = query.where(Asset.category == category)
    if q:
        query = query.where(
            or_(
                Asset.name.ilike(f"%{q}%"),
                Asset.code.ilike(f"%{q}%"),
                Asset.serial_no.ilike(f"%{q}%"),
            )
        )
    n = _overdue_days(db)
    rows = [_asset_out(db, a, n) for a in db.scalars(query.order_by(Asset.code))]
    return [r for r in rows if r["overdue"]] if overdue else rows


def _fill(db, a: Asset, body: AssetIn):
    if body.ownership == "hired":
        if body.vendor_id is None or db.get(Vendor, body.vendor_id) is None:
            raise svc.unprocessable("A hired asset needs the vendor it is hired from")
    for k in (
        "name",
        "category",
        "make",
        "model",
        "serial_no",
        "purchase_date",
        "purchase_value",
        "ownership",
        "vendor_id",
        "rate_per_hour",
        "rate_per_day",
        "is_active",
    ):
        setattr(a, k, getattr(body, k))
    if body.status in ("repair", "lost", "disposed", "available") and body.status != a.status:
        if a.site_id and body.status == "available":
            raise svc.unprocessable("Return it from the site first")
        a.status = body.status


@router.post("/assets", status_code=status.HTTP_201_CREATED)
def create_asset(
    body: AssetIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: AssetView
) -> dict:
    _edit(principal)
    store = db.get(Store, body.store_id) if body.store_id else material.godown(db)
    if store is None:
        raise svc.unprocessable("Store not found")
    a = Asset(
        code=material.next_code_plain(db, "AST"),
        status="available",
        store_id=store.id,
        located_since=svc.today(),
        created_by=principal.user.id,
    )
    _fill(db, a, body)
    db.add(a)
    db.flush()
    record(
        db, request, principal, "asset.create", "asset", a.id, after=body.model_dump(mode="json")
    )
    db.commit()
    db.refresh(a)
    return _asset_out(db, a, _overdue_days(db))


@router.put("/assets/{aid}")
def update_asset(
    aid: int,
    body: AssetIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: AssetView,
) -> dict:
    _edit(principal)
    a = _visible(db, aid, principal, scope)
    _fill(db, a, body)
    record(
        db, request, principal, "asset.update", "asset", a.id, after=body.model_dump(mode="json")
    )
    db.commit()
    db.refresh(a)
    return _asset_out(db, a, _overdue_days(db))


@router.post("/assets/{aid}/move", status_code=status.HTTP_201_CREATED)
async def move_asset(
    aid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: AssetView,
    to_site_id: Annotated[int | None, Form()] = None,
    to_store_id: Annotated[int | None, Form()] = None,
    on_date: Annotated[date | None, Form()] = None,
    condition: Annotated[str | None, Form()] = None,
    photo: Annotated[UploadFile | None, File()] = None,
) -> dict:
    """Issue to a site or return to a store (multipart, so a phone can attach a photo). An asset
    already at a site must come back (or be moved site to site) explicitly: issuing it to
    another site while it is out is a 409."""
    _edit(principal)
    a = _visible(db, aid, principal, scope)
    if (to_site_id is None) == (to_store_id is None):
        raise svc.unprocessable("Move it to a site or to a store")
    if a.status in ("lost", "disposed"):
        raise svc.conflict(f"{a.code} is {a.status}")
    if to_site_id is not None:
        site = db.get(Site, to_site_id)
        if site is None:
            raise svc.unprocessable("Site not found")
        if a.site_id == site.id:
            raise svc.conflict(f"{a.code} is already at {site.code}")
        if a.site_id is not None:
            raise svc.conflict(
                f"{a.code} is at {db.get(Site, a.site_id).code}; return it to a store first"
            )
    else:
        if db.get(Store, to_store_id) is None:
            raise svc.unprocessable("Store not found")
        if a.store_id == to_store_id:
            raise svc.conflict(f"{a.code} is already in that store")
    mv = AssetMovement(
        asset_id=a.id,
        from_store_id=a.store_id,
        from_site_id=a.site_id,
        to_store_id=to_store_id,
        to_site_id=to_site_id,
        on_date=on_date or svc.today(),
        condition=condition,
        created_by=principal.user.id,
    )
    if photo is not None and photo.filename:
        mv.photo_path, _ = await save_upload(photo, f"assets/{a.id}")
    a.site_id, a.store_id, a.located_since = to_site_id, to_store_id, mv.on_date
    if a.status != "repair":
        a.status = "at_site" if to_site_id else "available"
    db.add(mv)
    db.flush()
    record(
        db,
        request,
        principal,
        "asset.move",
        "asset",
        a.id,
        {"site_id": mv.from_site_id, "store_id": mv.from_store_id},
        {"site_id": to_site_id, "store_id": to_store_id, "condition": condition},
    )
    db.commit()
    db.refresh(a)
    return _asset_out(db, a, _overdue_days(db))


@router.get("/assets/{aid}/movements")
def movements(aid: int, db: DbSession, principal: CurrentPrincipal, scope: AssetView) -> list[dict]:
    a = _visible(db, aid, principal, scope)
    rows = list(
        db.scalars(
            select(AssetMovement)
            .where(AssetMovement.asset_id == a.id)
            .order_by(AssetMovement.id.desc())
        )
    )
    who = names(db, [m.created_by for m in rows])

    def place(site_id, store_id):
        if site_id:
            return db.get(Site, site_id).code
        return db.get(Store, store_id).name if store_id else "—"

    return [
        {
            "id": m.id,
            "on_date": m.on_date,
            "from": place(m.from_site_id, m.from_store_id),
            "to": place(m.to_site_id, m.to_store_id),
            "condition": m.condition,
            "by": who.get(m.created_by),
            "photo": bool(m.photo_path),
        }
        for m in rows
    ]


@router.get("/asset-movements/{mid}/photo")
def movement_photo(mid: int, db: DbSession, principal: CurrentPrincipal, scope: AssetView):
    m = db.get(AssetMovement, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Movement not found")
    _visible(db, m.asset_id, principal, scope)
    return send_file(m.photo_path)


# --- equipment usage -----------------------------------------------------------------------------


class UsageIn(BaseModel):
    asset_id: int
    site_id: int
    on_date: date | None = None
    basis: Literal["hour", "day"] = "day"
    quantity: Decimal = Field(gt=0, le=744)
    rate: Decimal | None = Field(default=None, ge=0)  # default: the asset's rate
    fuel_litres: Decimal = Field(default=Decimal(0), ge=0)
    fuel_cost: Decimal = Field(default=Decimal(0), ge=0)
    operator: str | None = Field(default=None, max_length=200)
    remark: str | None = None


def _usage_out(db, u: EquipmentUsage) -> dict:
    a = db.get(Asset, u.asset_id)
    return {
        "id": u.id,
        "asset_id": a.id,
        "asset": f"{a.code} {a.name}",
        "ownership": a.ownership,
        "site_id": u.site_id,
        "site_code": db.get(Site, u.site_id).code,
        "on_date": u.on_date,
        "basis": u.basis,
        "quantity": u.quantity,
        "rate": u.rate,
        "fuel_litres": u.fuel_litres,
        "fuel_cost": u.fuel_cost,
        "operator": u.operator,
        "amount": u.amount,
        "remark": u.remark,
    }


@router.post("/equipment-usage", status_code=status.HTTP_201_CREATED)
def add_usage(
    body: UsageIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: AssetView
) -> dict:
    site = svc.site_for(db, body.site_id, principal, "asset.view", "asset.edit")
    a = db.get(Asset, body.asset_id)
    if a is None:
        raise svc.unprocessable("Asset not found")
    if a.site_id != site.id:
        raise svc.unprocessable(f"{a.code} is not at {site.code}: issue it to the site first")
    rate = (
        body.rate
        if body.rate is not None
        else (a.rate_per_hour if body.basis == "hour" else a.rate_per_day)
    )
    if rate is None:
        raise svc.unprocessable(f"{a.code} has no rate per {body.basis}: give the rate")
    u = EquipmentUsage(
        asset_id=a.id,
        site_id=site.id,
        on_date=body.on_date or svc.today(),
        basis=body.basis,
        quantity=body.quantity,
        rate=rate,
        fuel_litres=body.fuel_litres,
        fuel_cost=body.fuel_cost,
        operator=body.operator,
        remark=body.remark,
        amount=svc.money(body.quantity * Decimal(rate) + body.fuel_cost),
        created_by=principal.user.id,
    )
    db.add(u)
    db.flush()
    record(
        db, request, principal, "equipment.usage", "asset", a.id, after=body.model_dump(mode="json")
    )
    db.commit()
    return _usage_out(db, u)


@router.get("/equipment-usage")
def list_usage(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: AssetView,
    site_id: int | None = None,
    asset_id: int | None = None,
    days: int = 90,
) -> list[dict]:
    q = select(EquipmentUsage).where(
        material.by_site(scope, principal, EquipmentUsage.site_id, EquipmentUsage.created_by),
        EquipmentUsage.on_date >= svc.today() - timedelta(days=days),
    )
    if site_id is not None:
        q = q.where(EquipmentUsage.site_id == site_id)
    if asset_id is not None:
        q = q.where(EquipmentUsage.asset_id == asset_id)
    return [
        _usage_out(db, u)
        for u in db.scalars(q.order_by(EquipmentUsage.on_date.desc(), EquipmentUsage.id.desc()))
    ]


@router.get("/equipment-cost")
def equipment_cost(db: DbSession, principal: CurrentPrincipal, scope: AssetView) -> list[dict]:
    rows = db.execute(
        select(
            EquipmentUsage.site_id,
            func.sum(EquipmentUsage.amount),
            func.sum(EquipmentUsage.fuel_cost),
            func.count(),
        )
        .where(
            material.by_site(scope, principal, EquipmentUsage.site_id, EquipmentUsage.created_by)
        )
        .group_by(EquipmentUsage.site_id)
    ).all()
    sites = {i: (c, n) for i, c, n in db.execute(select(Site.id, Site.code, Site.name))}
    return [
        {
            "site_id": s,
            "site_code": sites[s][0],
            "site_name": sites[s][1],
            "amount": amt,
            "fuel_cost": fuel,
            "entries": n,
        }
        for s, amt, fuel, n in sorted(rows, key=lambda r: sites[r[0]][0])
    ]
