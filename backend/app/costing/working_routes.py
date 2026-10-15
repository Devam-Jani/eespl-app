# ruff: noqa: E501  (the build-up rows and queries read better unwrapped)
"""The rate working sheet API: the working of a tender revision or a quotation, the suggested
groups and moving lines between them, a main item's working, the rates flowing to the client's
lines, and the internal Excel export (never part of what goes to the client).

Everyone who sees the BOQ sees the groups and the rates; costs, cushions and margins are for
tender.margin (the director and the estimator), and only they change a working."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, require_permission
from app.costing import prices, working
from app.costing.models import (
    LabourRateCard,
    RateGroup,
    RateGroupProduct,
    RateWorking,
)
from app.db import DbSession
from app.execution.common import record
from app.masters.models import Product, System, Vendor

router = APIRouter(prefix="/api/rate-working", tags=["rate working"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cost(principal) -> bool:
    return principal.permissions.get("tender.margin") is not None


def _visible(db, w: RateWorking, principal) -> None:
    """The working's BOQ must be visible to the caller (tender.view / quotation.view scope)."""
    if w.tender_id:
        from app.tenders.service import get_visible  # noqa: PLC0415

        scope = principal.permissions.get("tender.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to tenders")
        get_visible(db, w.tender_id, scope, principal)
    else:
        from app.quotations import service as qsvc  # noqa: PLC0415

        scope = principal.permissions.get("quotation.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to quotations")
        qsvc.get_visible(db, w.quotation_id, scope, principal)


def _working(db, wid: int, principal) -> RateWorking:
    w = db.get(RateWorking, wid)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Working not found")
    _visible(db, w, principal)
    return w


def _editable(db, w: RateWorking, principal) -> None:
    if not _cost(principal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The rate working is for the estimator and the director"
        )
    if w.tender_id and principal.permissions.get("tender.edit") is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tender editing is not for your role")
    if w.locked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"R{w.rev_no} was submitted: its working is kept as it was; work on the new revision",
        )


def _group(db, gid: int, principal, edit: bool = True) -> tuple[RateGroup, RateWorking]:
    g = db.get(RateGroup, gid)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Main item not found")
    w = _working(db, g.working_id, principal)
    if edit:
        _editable(db, w, principal)
    return g, w


# --- output --------------------------------------------------------------------------------------


def group_out(db, g: RateGroup, lines: dict[str, dict], with_cost: bool) -> dict:
    result = working.work(db, g)
    system = db.get(System, g.system_id) if g.system_id else None
    my_lines = [lines[k] for k in (working._line_key(gl) for gl in g.lines) if k in lines]
    out = {
        "id": g.id,
        "name": g.name,
        "sort_order": g.sort_order,
        "system_id": g.system_id,
        "system": system.name if system else None,
        "system_to_confirm": bool(system and system.to_confirm),
        "lines": my_lines,
        "unit_note": sorted({(x["unit"] or "?") for x in my_lines} - {"sqm", "sqft", "sft"}),
        "rate_sqm": result["rate_sqm"],
        "rate_sqft": result["rate_sqft"],
        "errors": result["errors"],
        "library_flagged": result.get("library_flagged", False),
        "library_diff_percent": result.get("library_diff_percent"),
        "library_median_sqm": result.get("library_median_sqm"),
        "coats": g.coats,
        "application": g.application,
        "margin_basis": result.get("margin_basis") or working.margin_basis(db),
        "margin_basis_label": working.BASIS_LABEL[
            result.get("margin_basis") or working.margin_basis(db)
        ],
    }
    if not with_cost:
        return out
    card = db.get(LabourRateCard, g.labour_rate_card_id) if g.labour_rate_card_id else None
    out |= {
        "wastage_percent": g.wastage_percent,
        "wastage_source": g.wastage_source,
        "applications": _applications(db),
        "system_coats": _system_coats(db, g.system_id),
        "surface_prep": g.surface_prep,
        "labour_rate_card_id": g.labour_rate_card_id,
        "labour_rate_card": (
            f"{db.get(Vendor, card.contractor_id).name}: {card.job} ₹{card.rate}/{card.unit}"
            if card
            else None
        ),
        "labour_used_sqft": g.labour_used_sqft,
        "labour_paid_sqft": g.labour_paid_sqft,
        "margin_percent": g.margin_percent,
        "note": g.note,
        "products": [product_out(db, p) for p in g.products],
        "rows": result["rows"],
        "material_sqm": result.get("material_sqm"),
        "cost_sqm": result.get("cost_sqm"),
        "margin_sqm": result.get("margin_sqm"),
        "cushions": result["cushions"],
        "cushion_sqm": result.get("cushion_sqm"),
        "library_limit_percent": result.get("library_limit_percent"),
    }
    return out


def _applications(db) -> list[dict]:
    """The applications with a wastage in Settings > Process rules (raft, footing ...)."""
    from app.process.engine import settings as process_settings  # noqa: PLC0415

    return [
        {"name": k, "min": v["min"], "max": v["max"]}
        for k, v in (process_settings(db).wastage or {}).items()
    ]


def _system_coats(db, system_id: int | None) -> list[dict]:
    """The coats the system's products have (blank: to confirm)."""
    system = db.get(System, system_id) if system_id else None
    if system is None:
        return []
    return [
        {"product": c.product.name, "coats": c.coats, "to_confirm": c.to_confirm}
        for c in system.components
    ]


def product_out(db, p: RateGroupProduct) -> dict:
    product = db.get(Product, p.product_id)
    used = db.get(prices.ProductPrice, p.price_id) if p.price_id else None
    return {
        "id": p.id,
        "product_id": p.product_id,
        "product": product.name,
        "unit": product.unit,
        "consumption": p.consumption,
        "default_consumption": p.default_consumption,
        "consumption_changed": p.consumption != p.default_consumption,
        "consumption_reason": p.consumption_reason,
        "price": p.price,
        "price_info": prices.price_out(db, used),
        "freight_used": p.freight_used,
        "freight_actual": p.freight_actual,
    }


def working_out(db, w: RateWorking, principal) -> dict:
    lines = {x["key"]: x for x in working.client_lines(db, w)}
    with_cost = _cost(principal)
    grouped = {working._line_key(gl) for g in w.groups for gl in g.lines}
    groups = [group_out(db, g, lines, with_cost) for g in w.groups]
    if not with_cost:
        for x in lines.values():
            x.pop("system_id", None)
    out = {
        "id": w.id,
        "tender_id": w.tender_id,
        "quotation_id": w.quotation_id,
        "rev_no": w.rev_no,
        "locked": w.locked,
        "can_edit": with_cost and not w.locked,
        "sees_cost": with_cost,
        "margin_basis": working.margin_basis(db),
        "margin_basis_label": working.BASIS_LABEL[working.margin_basis(db)],
        "line_count": len(lines),
        "groups": groups,
        "ungrouped": [x for k, x in lines.items() if k not in grouped],
    }
    db.flush()
    return jsonable_encoder(out)


# --- the working of a tender revision or a quotation ---------------------------------------------


@router.get("/tenders/{tender_id}")
def tender_working(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("tender.view"))],
) -> dict:
    from app.tenders.service import get_visible  # noqa: PLC0415

    tender = get_visible(db, tender_id, scope, principal)
    w = working.for_tender(db, tender, principal.user.id)
    out = working_out(db, w, principal)
    db.commit()
    return out


@router.get("/quotations/{qid}")
def quotation_working(
    qid: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("quotation.view"))],
) -> dict:
    from app.quotations import service as qsvc  # noqa: PLC0415

    q = qsvc.get_visible(db, qid, scope, principal)
    w = working.for_quotation(db, q, principal.user.id)
    out = working_out(db, w, principal)
    db.commit()
    return out


@router.get("/{wid}")
def get_working(wid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    out = working_out(db, _working(db, wid, principal), principal)
    db.commit()
    return out


@router.post("/{wid}/suggest")
def suggest(
    wid: int, request: Request, db: DbSession, principal: CurrentPrincipal, fresh: bool = False
) -> dict:
    """Group the lines not in a main item yet (fresh: start the grouping again)."""
    w = _working(db, wid, principal)
    _editable(db, w, principal)
    if fresh:
        for g in list(w.groups):
            db.delete(g)
        db.flush()
        db.refresh(w)
    made = working.suggest(db, w, principal.user.id)
    record(db, request, principal, "rate_working.suggest", "rate_working", w.id,
           after={"groups": [g.name for g in made], "fresh": fresh})  # fmt: skip
    out = working_out(db, w, principal)
    db.commit()
    return out


class MoveIn(BaseModel):
    line_key: str = Field(pattern=r"^[bq][0-9]+$")
    to_group_id: int | None = None  # none: out of every main item
    new_group_name: str | None = Field(None, max_length=200)


@router.post("/{wid}/move")
def move(
    wid: int, body: MoveIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Move a client line to another main item (or a new one, or out of all of them)."""
    w = _working(db, wid, principal)
    _editable(db, w, principal)
    if body.line_key not in {x["key"] for x in working.client_lines(db, w)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not in this BOQ")
    for g in w.groups:
        for gl in list(g.lines):
            if working._line_key(gl) == body.line_key:
                g.lines.remove(gl)
    target = None
    if body.new_group_name:
        target = RateGroup(
            working_id=w.id,
            name=body.new_group_name.strip(),
            sort_order=max((g.sort_order for g in w.groups), default=0) + 1,
            created_by=principal.user.id,
        )
        db.add(target)
        db.flush()
        working.init_from_system(db, target)
    elif body.to_group_id is not None:
        target = next((g for g in w.groups if g.id == body.to_group_id), None)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Main item not in this working")
    if target is not None:
        target.lines.append(working._group_line(body.line_key))
    db.flush()
    record(db, request, principal, "rate_working.move", "rate_working", w.id,
           after={"line": body.line_key, "to": target.name if target else None})  # fmt: skip
    db.refresh(w)
    out = working_out(db, w, principal)
    db.commit()
    return out


class ProductIn(BaseModel):
    id: int | None = None
    product_id: int
    consumption: Decimal | None = Field(None, ge=0)
    consumption_reason: str | None = Field(None, max_length=300)
    price: Decimal | None = Field(None, ge=0)
    freight_used: Decimal = Field(Decimal(0), ge=0)
    freight_actual: Decimal | None = Field(None, ge=0)


class GroupIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    system_id: int | None = None
    application: str | None = Field(None, max_length=40)
    coats: int | None = Field(None, ge=1, le=20)
    wastage_percent: Decimal | None = Field(None, ge=0, le=100)
    surface_prep: Decimal | None = Field(None, ge=0)
    labour_rate_card_id: int | None = None
    labour_used_sqft: Decimal | None = Field(None, ge=0)
    labour_paid_sqft: Decimal | None = Field(None, ge=0)
    margin_percent: Decimal | None = Field(None, ge=0, le=500)
    note: str | None = None
    products: list[ProductIn] | None = None


@router.put("/groups/{gid}")
def update_group(
    gid: int, body: GroupIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """A main item's working. Choosing another system starts its products from the system; a
    consumption other than the system's needs a reason; a price typed here goes into the master
    price list (with the change flag)."""
    g, w = _group(db, gid, principal)
    before = {"rate_sqm": str(g.rate_sqm) if g.rate_sqm is not None else None}
    data = body.model_dump(exclude_unset=True)
    products = data.pop("products", None)
    new_system = "system_id" in data and data["system_id"] != g.system_id
    if new_system and data["system_id"] and db.get(System, data["system_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown system")
    if "labour_rate_card_id" in data and data["labour_rate_card_id"]:
        if db.get(LabourRateCard, data["labour_rate_card_id"]) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown labour rate card")
    if new_system:  # the system's build-up first; what was typed with it wins
        g.system_id = data.pop("system_id")
        working.init_from_system(db, g, " ".join(working.words(g.name)))
    old_wastage = g.wastage_percent
    for k, v in data.items():
        setattr(g, k, v)
    # the application picked: its wastage from Settings > Process rules (and where it came from)
    if "application" in data and "wastage_percent" not in data:
        found = working.wastage_from_settings(db, g.application)
        if found:
            g.wastage_percent, g.wastage_source = found
    elif "wastage_percent" in data and data["wastage_percent"] != old_wastage:
        from_app = working.wastage_from_settings(db, g.application)
        if not (from_app and from_app[0] == data["wastage_percent"]):
            g.wastage_source = "typed for this site"
    if "labour_rate_card_id" in data and "labour_paid_sqft" not in data:
        working.labour_from_card(db, g)
    flags = []
    if products is not None and not new_system:
        keep = {p["id"] for p in products if p.get("id")}
        for p in list(g.products):
            if p.id not in keep:
                g.products.remove(p)
        by_id = {p.id: p for p in g.products}
        for i, row in enumerate(products):
            if db.get(Product, row["product_id"]) is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown product")
            p = by_id.get(row.get("id")) if row.get("id") else None
            if p is None:
                p = working.new_product(db, row["product_id"], row.get("consumption"), i)
                p.default_consumption = None
                g.products.append(p)
            p.sort_order = i
            if "consumption" in row:
                p.consumption = row["consumption"]
            reason = " ".join((row.get("consumption_reason") or "").split()) or None
            if p.default_consumption is not None and p.consumption != p.default_consumption:
                if not reason or len(reason) < 3:
                    name = db.get(Product, p.product_id).name
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"{name}: say why the consumption differs from the system's "
                        f"{p.default_consumption.normalize():f} for this site",
                    )
            p.consumption_reason = reason if p.consumption != p.default_consumption else None
            p.freight_used = row.get("freight_used") or Decimal(0)
            p.freight_actual = row.get("freight_actual")
            if row.get("price") is not None and (
                p.price is None or Decimal(row["price"]) != Decimal(p.price)
            ):
                flag = prices.check(db, p.product_id, Decimal(row["price"]))
                rec = prices.record_price(
                    db, p.product_id, Decimal(row["price"]), source="manual",
                    user_id=principal.user.id, ref=f"Rate working {w.id}",
                    note=f"Typed in the rate working of {g.name}",
                )  # fmt: skip
                p.price = Decimal(row["price"])
                p.price_id = rec.id if rec else p.price_id
                flags.append(flag | {"product": db.get(Product, p.product_id).name})
    db.flush()
    lines = {x["key"]: x for x in working.client_lines(db, w)}
    out = group_out(db, g, lines, True)
    record(db, request, principal, "rate_working.group", "rate_group", g.id, before=before,
           after={"rate_sqm": str(out["rate_sqm"]), "changes": jsonable_encoder(body.model_dump(exclude_unset=True))})  # fmt: skip
    db.commit()
    return jsonable_encoder(out | {"price_checks": flags})


@router.post("/groups/{gid}/refresh-prices")
def refresh_prices(gid: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Today's prices and freight from the master price list for every product of the item."""
    g, w = _group(db, gid, principal)
    for p in g.products:
        cur = prices.current(db, p.product_id)
        f = prices.freight_for(db, p.product_id)
        if cur is not None:
            p.price, p.price_id = cur.purchase_rate, cur.id
        if f is not None:
            p.freight_used = f.per_unit
    db.flush()
    lines = {x["key"]: x for x in working.client_lines(db, w)}
    out = group_out(db, g, lines, True)
    record(db, request, principal, "rate_working.prices", "rate_group", g.id,
           after={"rate_sqm": str(out["rate_sqm"])})  # fmt: skip
    db.commit()
    return jsonable_encoder(out)


@router.delete("/groups/{gid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    gid: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> Response:
    """The main item goes; its lines are left ungrouped."""
    g, w = _group(db, gid, principal)
    record(
        db,
        request,
        principal,
        "rate_working.delete_group",
        "rate_group",
        g.id,
        before={"name": g.name},
    )
    db.delete(g)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{wid}/apply")
def apply(wid: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The worked rates flow to every client line of their main item."""
    w = _working(db, wid, principal)
    _editable(db, w, principal)
    for g in w.groups:
        working.work(db, g)
    out = working.apply_rates(db, w)
    record(
        db,
        request,
        principal,
        "rate_working.apply",
        "rate_working",
        w.id,
        after=jsonable_encoder(out),
    )
    db.commit()
    return jsonable_encoder(out)


@router.get("/{wid}/export.xlsx")
def export_xlsx(wid: int, db: DbSession, principal: CurrentPrincipal) -> Response:
    """The working sheet in the layout of our Working sheets (internal: costs and margins)."""
    from app.costing import export  # noqa: PLC0415

    if not _cost(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The working sheet is internal")
    w = _working(db, wid, principal)
    data, name = export.working_xlsx(db, w)
    db.commit()
    return Response(
        data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )
