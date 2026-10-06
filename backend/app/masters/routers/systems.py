"""Rate build-up systems.

Everyone with library.view sees a system, the products it uses and its final selling rate.
Consumption, wastage, surface prep, labour, margin and the breakdown (`cost`, and
GET /{id}/rate) are cost data, only for tender.margin; so is changing a system.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.masters.models import Product, System, SystemComponent, Unit
from app.masters.rate import MissingPriceError, system_rate
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
    ComponentBreakdown,
    ComponentCostOut,
    ComponentIn,
    ComponentPublic,
    Page,
    RateBreakdownOut,
    SystemCost,
    SystemIn,
    SystemOut,
    SystemUpdate,
)

router = APIRouter(prefix="/api/systems", tags=["systems"])

view = [Depends(require_permission("library.view"))]
cost_edit = [
    Depends(require_permission("library.edit")),
    Depends(require_permission("tender.margin")),
]


def _public(c: SystemComponent) -> dict:
    p = c.product
    return {
        "product_id": p.id,
        "product_code": p.code,
        "product_name": p.name,
        "brand": p.brand,
        "unit": p.unit,
    }


def _out(db: Session, system: System, with_cost: bool) -> SystemOut:
    try:
        rate, error = system_rate(db, system).rate, None
    except MissingPriceError as exc:
        rate, error = None, str(exc)
    out = SystemOut(
        id=system.id,
        code=system.code,
        name=system.name,
        description=system.description,
        unit=system.unit,
        is_active=system.is_active,
        rate=rate,
        rate_error=error,
        components=[ComponentPublic(**_public(c)) for c in system.components],
    )
    if with_cost:
        out.cost = SystemCost(
            surface_prep_per_unit=system.surface_prep_per_unit,
            labour_rate=system.labour_rate,
            labour_unit=system.labour_unit,
            default_margin_percent=system.default_margin_percent,
            components=[
                ComponentCostOut(
                    **_public(c),
                    consumption_per_unit=c.consumption_per_unit,
                    wastage_percent=c.wastage_percent,
                )
                for c in system.components
            ],
        )
    return out


def _components(
    db: Session, items: list[ComponentIn], principal: CurrentPrincipal
) -> list[SystemComponent]:
    ids = {c.product_id for c in items}
    found = set(db.scalars(select(Product.id).where(Product.id.in_(ids)))) if ids else set()
    if ids - found:
        raise unprocessable(f"Unknown product ids: {sorted(ids - found)}")
    return [SystemComponent(**c.model_dump(), created_by=principal.user.id) for c in items]


def _check(db: Session, code: str | None, unit: str | None, exclude: int | None = None) -> None:
    if unit is not None and db.get(Unit, unit) is None:
        raise unprocessable(f"Unknown unit: {unit}")
    if code is not None:
        query = select(func.count()).select_from(System).where(System.code == code)
        if exclude is not None:
            query = query.where(System.id != exclude)
        if db.scalar(query):
            raise conflict(f"A system with code {code} already exists")


@router.get("", dependencies=view)
def list_systems(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Search = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[SystemOut]:
    query = select(System)
    if q:
        pattern = like(q)
        query = query.where(or_(System.code.ilike(pattern), System.name.ilike(pattern)))
    if active is not None:
        query = query.where(System.is_active == active)
    rows, total = paginate(db, query.order_by(System.name, System.id), limit, offset)
    with_cost = "tender.margin" in principal.permissions
    return Page(
        items=[_out(db, s, with_cost) for s in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{system_id}", dependencies=view)
def get_system(system_id: int, db: DbSession, principal: CurrentPrincipal) -> SystemOut:
    system = get_or_404(db, System, system_id, "System")
    return _out(db, system, "tender.margin" in principal.permissions)


@router.get("/{system_id}/rate", dependencies=[Depends(require_permission("tender.margin"))])
def rate_breakdown(
    system_id: int,
    db: DbSession,
    margin: Annotated[
        Decimal | None, Query(ge=0, lt=1000, description="Margin %; default: the system's")
    ] = None,
) -> RateBreakdownOut:
    system = get_or_404(db, System, system_id, "System")
    try:
        b = system_rate(db, system, margin)
    except MissingPriceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return RateBreakdownOut(
        system_id=system.id,
        unit=b.unit,
        components=[ComponentBreakdown(**vars(c)) for c in b.components],
        material_cost=b.material_cost,
        surface_prep=b.surface_prep,
        labour_rate=b.labour_rate,
        labour_unit=b.labour_unit,
        labour_per_unit=b.labour_per_unit,
        base_cost=b.base_cost,
        margin_percent=b.margin_percent,
        margin_amount=b.margin_amount,
        rate=b.rate,
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=cost_edit)
def create_system(
    body: SystemIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> SystemOut:
    _check(db, body.code, body.unit)
    fields = body.model_dump(exclude={"components"}, exclude_none=True)
    system = System(
        **fields,
        created_by=principal.user.id,
        components=_components(db, body.components, principal),
    )
    db.add(system)
    db.flush()
    db.refresh(system)
    audit.record(db, "system.create", "system", system.id, user_id=principal.user.id,
                 after=audit.model_snapshot(system, "components"),
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return _out(db, system, True)


@router.patch("/{system_id}", dependencies=cost_edit)
def update_system(
    system_id: int,
    body: SystemUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> SystemOut:
    system = get_or_404(db, System, system_id, "System")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True, exclude={"components"}).items()
               if v is not None or k == "description"}  # fmt: skip
    _check(db, changes.get("code"), changes.get("unit"), exclude=system.id)
    before = audit.model_snapshot(system, "components")
    for field, value in changes.items():
        setattr(system, field, value)
    if body.components is not None:
        system.components = _components(db, body.components, principal)
    db.flush()
    after = audit.model_snapshot(system, "components")
    if after != before:
        audit.record(db, "system.update", "system", system.id, user_id=principal.user.id,
                     before=before, after=after, ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(system)
    return _out(db, system, True)


@router.delete(
    "/{system_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("library.edit"))],
)
def delete_system(
    system_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    system = get_or_404(db, System, system_id, "System")
    audit.record(db, "system.delete", "system", system.id, user_id=principal.user.id,
                 before=audit.model_snapshot(system, "components"),
                 ip=audit.client_ip(request))  # fmt: skip
    db.delete(system)
    db.commit()
