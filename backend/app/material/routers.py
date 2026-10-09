"""Material: indents, RFQs, purchase orders, GRNs, stores and stock, transfers, site issues and
returns, freight, and the purchase settings.

Permissions (scope all | assigned: the caller's sites | own: what the caller created):
  indent.view / indent.create / indent.approve    by the indent's site
  po.view / po.edit / po.approve                  by the delivery store's site
  grn.view / grn.edit / grn.approve               by the receiving store's site
  store.view / store.edit                         by the store's site (the godown needs "all")
A record outside the caller's view scope is a 404; an action without the permission is a 403.
A PO up to the approval limit is approved by its creator (po.edit); above it needs po.approve.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

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
from fastapi.responses import FileResponse, Response
from sqlalchemy import ColumnElement, extract, false, func, or_, select, true
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_any_permission, require_permission
from app.auth.rbac import widest
from app.config import settings
from app.db import DbSession
from app.masters.models import (
    CompanyGstin,
    CompanyProfile,
    Product,
    TcTemplate,
    Unit,
    Vendor,
)
from app.masters.routers.common import Limit, Offset, Search, like, paginate, unprocessable
from app.masters.schemas import Page
from app.material import po_pdf
from app.material import service as svc
from app.material.models import (
    FreightEntry,
    Grn,
    GrnLine,
    GrnPhoto,
    Indent,
    IndentLine,
    PoCharge,
    PoIndent,
    PoLine,
    PurchaseOrder,
    Rfq,
    RfqIndent,
    RfqLine,
    RfqQuote,
    RfqVendor,
    SiteIssue,
    SiteIssueLine,
    StockLedger,
    Store,
    Transfer,
    TransferLine,
)
from app.material.schemas import (
    AdjustIn,
    ChoiceIn,
    FreightBillIn,
    FreightOut,
    FreightReportRow,
    GrnIn,
    GrnLineOut,
    GrnOut,
    GrnPhotoOut,
    IndentIn,
    IndentLineOut,
    IndentOut,
    IssueIn,
    IssueLineOut,
    IssueOut,
    LedgerRow,
    PoChargeOut,
    PoIn,
    PoLineOut,
    PoOut,
    PurchaseSettings,
    QuoteCell,
    QuotesIn,
    ReasonIn,
    ReceiveIn,
    RfqIn,
    RfqLineOut,
    RfqOut,
    RfqVendorOut,
    StockRow,
    StoreIn,
    StoreOut,
    TransferIn,
    TransferLineOut,
    TransferOut,
)
from app.models import User
from app.sites.models import AreaScope, Site, Task

router = APIRouter(prefix="/api/material", tags=["material"])

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
PHOTO_MAX = 15 * 1024 * 1024
ZERO = Decimal(0)


def _scope(code: str):
    def dep(principal: CurrentPrincipal) -> str | None:
        return principal.permissions.get(code)

    dep.__name__ = f"optional_scope[{code}]"
    return dep


IndentView = Annotated[str, Depends(require_permission("indent.view"))]
PoView = Annotated[str, Depends(require_permission("po.view"))]
PoEdit = Annotated[str, Depends(require_permission("po.edit"))]
GrnView = Annotated[str, Depends(require_permission("grn.view"))]
StoreView = Annotated[str, Depends(require_permission("store.view"))]
AnyMaterial = Annotated[
    str,
    Depends(require_any_permission("indent.view", "po.view", "grn.view", "store.view")),
]


def _record(db, request, principal, action, entity, ident, before=None, after=None):
    audit.record(
        db,
        action,
        entity,
        ident,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _now() -> datetime:
    return datetime.now(UTC)


def _profile(db: Session) -> CompanyProfile:
    profile = db.get(CompanyProfile, 1)
    if profile is None:
        profile = CompanyProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


def _product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise unprocessable(f"Product {product_id} not found")
    return product


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _forbidden(what: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, f"You cannot {what}")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


# --- store access --------------------------------------------------------------------------------


def _store_cond(scope: str | None, principal: Principal, store_col) -> ColumnElement[bool]:
    """Rows whose store the caller may see under `scope`."""
    if scope is None:
        return false()
    if scope == "all":
        return true()
    stores = select(Store.id).where(svc.by_site(scope, principal, Store.site_id, Store.created_by))
    return store_col.in_(stores)


def _store_ok(db: Session, scope: str | None, principal: Principal, store: Store) -> bool:
    return svc.covers_site(db, scope, principal, store.site_id, store.created_by)


def _store(db: Session, store_id: int, scope: str | None, principal: Principal) -> Store:
    store = db.get(Store, store_id)
    if store is None or not _store_ok(db, scope, principal, store):
        raise _not_found("Store")
    return store


def _store_for_edit(db, store_id, code, principal, what) -> Store:
    store = db.get(Store, store_id)
    if store is None:
        raise unprocessable(f"Store {store_id} not found")
    if not _store_ok(db, principal.permissions.get(code), principal, store):
        raise _forbidden(f"{what} in {store.name}")
    return store


# --- settings and lookups ------------------------------------------------------------------------


def _settings_out(p: CompanyProfile) -> PurchaseSettings:
    return PurchaseSettings(
        po_approval_limit=p.po_approval_limit,
        allow_negative_stock=p.allow_negative_stock,
        grn_approval_levels=p.grn_approval_levels,
        po_tc_template_id=p.po_tc_template_id,
        freight_sac=p.freight_sac,
    )


@router.get("/settings")
def get_settings(db: DbSession, _: AnyMaterial) -> PurchaseSettings:
    return _settings_out(_profile(db))


@router.put("/settings")
def put_settings(
    body: PurchaseSettings,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("settings.company"))],
) -> PurchaseSettings:
    p = _profile(db)
    if body.po_tc_template_id and db.get(TcTemplate, body.po_tc_template_id) is None:
        raise unprocessable("T&C template not found")
    before = _settings_out(p).model_dump(mode="json")
    for k, v in body.model_dump().items():
        if k == "freight_sac" and v is None:
            continue
        setattr(p, k, v)
    _record(
        db,
        request,
        principal,
        "material.settings",
        "company_profile",
        1,
        before,
        body.model_dump(mode="json"),
    )
    db.commit()
    return _settings_out(p)


@router.get("/lookups")
def lookups(db: DbSession, principal: CurrentPrincipal, _: AnyMaterial) -> dict:
    """Everything the material forms pick from, limited to what the caller may use."""
    perms = principal.permissions
    site_scope = None
    for code in ("indent.view", "indent.create", "store.view", "store.edit", "grn.edit"):
        site_scope = widest(site_scope, perms.get(code))
    sites = db.execute(
        select(Site.id, Site.code, Site.name)
        .where(
            Site.status != "closed",
            svc.by_site(site_scope or "", principal, Site.id, Site.created_by),
        )
        .order_by(Site.code.desc())
    ).all()
    store_scope = None
    for code in ("store.view", "grn.edit", "po.view", "store.edit"):
        store_scope = widest(store_scope, perms.get(code))
    stores = db.scalars(
        select(Store)
        .where(Store.is_active, _store_cond(store_scope, principal, Store.id))
        .order_by(Store.kind, Store.name)
    )
    profile = _profile(db)
    return {
        "sites": [{"id": i, "code": c, "name": n} for i, c, n in sites],
        "stores": [
            {"id": s.id, "name": s.name, "kind": s.kind, "site_id": s.site_id} for s in stores
        ],
        "products": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "unit": p.unit,
                "gst_percent": p.gst_percent,
            }
            for p in db.scalars(select(Product).where(Product.is_active).order_by(Product.name))
        ],
        "vendors": [
            {"id": v.id, "name": v.name, "gstin": v.gstin, "state": v.state}
            for v in db.scalars(select(Vendor).where(Vendor.is_active).order_by(Vendor.name))
        ],
        "units": [u for u in db.scalars(select(Unit.code).order_by(Unit.code))],
        "gstins": [
            {"id": g.id, "gstin": g.gstin, "state": g.state, "is_default": g.is_default}
            for g in db.scalars(select(CompanyGstin).order_by(CompanyGstin.is_default.desc()))
        ],
        "tc_templates": [
            {"id": i, "name": n}
            for i, n in db.execute(select(TcTemplate.id, TcTemplate.name).order_by(TcTemplate.name))
        ],
        "settings": _settings_out(profile).model_dump(mode="json"),
        "permissions": {
            k: v
            for k, v in perms.items()
            if k.split(".")[0] in ("indent", "po", "grn", "store", "settings")
        },
    }


# --- stores and stock ----------------------------------------------------------------------------


def _store_out(db: Session, s: Store) -> StoreOut:
    items, value = db.execute(
        select(
            func.count(func.distinct(StockLedger.product_id)).filter(StockLedger.qty != 0),
            func.coalesce(func.sum(StockLedger.value), 0),
        ).where(StockLedger.store_id == s.id)
    ).one()
    site_code = db.scalar(select(Site.code).where(Site.id == s.site_id)) if s.site_id else None
    return StoreOut(
        id=s.id,
        name=s.name,
        kind=s.kind,
        site_id=s.site_id,
        site_code=site_code,
        address=s.address,
        gstin_address_id=s.gstin_address_id,
        is_active=s.is_active,
        items=items or 0,
        value=Decimal(value),
    )


@router.get("/stores")
def list_stores(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: StoreView,
    site_id: int | None = None,
) -> list[StoreOut]:
    query = select(Store).where(_store_cond(scope, principal, Store.id))
    if site_id is not None:
        query = query.where(Store.site_id == site_id)
    return [_store_out(db, s) for s in db.scalars(query.order_by(Store.kind, Store.name))]


@router.post("/stores", status_code=status.HTTP_201_CREATED)
def create_store(
    body: StoreIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("store.edit"))],
) -> StoreOut:
    """A godown (site stores are made with their site)."""
    if scope != "all":
        raise _forbidden("add a godown")
    if db.scalar(select(Store.id).where(Store.name == body.name)):
        raise _conflict(f"A store named {body.name} exists")
    store = Store(kind="godown", created_by=principal.user.id, **body.model_dump())
    db.add(store)
    db.flush()
    _record(
        db, request, principal, "store.create", "store", store.id, after=audit.model_snapshot(store)
    )
    db.commit()
    return _store_out(db, store)


def _stock_rows(db: Session, store_id: int) -> list[StockRow]:
    rows = db.execute(
        select(StockLedger.product_id, func.sum(StockLedger.qty), func.sum(StockLedger.value))
        .where(StockLedger.store_id == store_id)
        .group_by(StockLedger.product_id)
    ).all()
    out = []
    for product_id, qty, value in rows:
        if qty == 0 and value == 0:
            continue
        p = db.get(Product, product_id)
        avg = svc.average_rate(db, store_id, product_id)
        out.append(
            StockRow(
                product_id=p.id,
                product_code=p.code,
                product_name=p.name,
                unit=p.unit,
                qty=qty,
                avg_rate=avg,
                value=value,
            )
        )
    return sorted(out, key=lambda r: r.product_name)


@router.get("/stores/{store_id}/stock")
def store_stock(
    store_id: int, db: DbSession, principal: CurrentPrincipal, scope: StoreView
) -> list[StockRow]:
    store = _store(db, store_id, scope, principal)
    return _stock_rows(db, store.id)


def _ref_codes(db: Session, rows: list[StockLedger]) -> dict[tuple[str, int], str]:
    by_type: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        if r.ref_id:
            by_type[r.ref_type].add(r.ref_id)
    out = {}
    tables = {
        "grn": Grn,
        "transfer_out": Transfer,
        "shortage": Transfer,
        "transfer_in": Transfer,
        "issue": SiteIssue,
        "return": SiteIssue,
    }
    for ref_type, ids in by_type.items():
        model = tables.get(ref_type)
        if model is None:
            continue
        for i, code in db.execute(select(model.id, model.code).where(model.id.in_(ids))):
            out[(ref_type, i)] = code
    return out


@router.get("/stores/{store_id}/ledger")
def store_ledger(
    store_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: StoreView,
    product_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[LedgerRow]:
    """Newest first, with the running balance of each row's product."""
    store = _store(db, store_id, scope, principal)
    query = select(StockLedger).where(StockLedger.store_id == store.id)
    if product_id is not None:
        query = query.where(StockLedger.product_id == product_id)
    rows = list(db.scalars(query.order_by(StockLedger.id)))
    codes = _ref_codes(db, rows)
    names = dict(
        db.execute(
            select(Product.id, Product.name).where(
                Product.id.in_({r.product_id for r in rows} or {0})
            )
        ).all()
    )
    running: dict[int, Decimal] = defaultdict(Decimal)
    out = []
    for r in rows:
        running[r.product_id] += r.qty
        out.append(
            LedgerRow(
                id=r.id,
                at=r.at,
                product_id=r.product_id,
                product_name=names.get(r.product_id, ""),
                qty=r.qty,
                unit=r.unit,
                rate=r.rate,
                value=r.value,
                ref_type=r.ref_type,
                ref_id=r.ref_id,
                ref_code=codes.get((r.ref_type, r.ref_id)),
                note=r.note,
                balance=running[r.product_id],
            )
        )
    return list(reversed(out))[:limit]


@router.post("/stores/{store_id}/adjust", status_code=status.HTTP_201_CREATED)
def adjust_stock(
    store_id: int,
    body: AdjustIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("store.edit"))],
) -> list[StockRow]:
    """Opening stock or a physical-count correction (store.edit with scope all)."""
    if scope != "all":
        raise _forbidden("adjust stock")
    store = _store(db, store_id, scope, principal)
    product = _product(db, body.product_id)
    if body.qty == 0:
        raise unprocessable("Give a quantity")
    if body.qty > 0:
        if body.rate is None:
            raise unprocessable("Give the rate of the stock added")
        svc.post(
            db,
            store_id=store.id,
            product=product,
            qty=body.qty,
            rate=body.rate,
            ref_type=body.kind,
            ref_id=None,
            user_id=principal.user.id,
            note=body.note,
        )
    else:
        svc.take_out(
            db,
            store=store,
            product=product,
            qty=-body.qty,
            ref_type=body.kind,
            ref_id=None,
            user_id=principal.user.id,
            note=body.note,
        )
    _record(
        db,
        request,
        principal,
        "store.adjust",
        "store",
        store.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _stock_rows(db, store.id)


# --- indents -------------------------------------------------------------------------------------


def _indent_out(db: Session, ind: Indent, principal: Principal) -> IndentOut:
    site = db.get(Site, ind.site_id)
    names = _names(db, [ind.created_by])
    create = principal.permissions.get("indent.create")
    approve = principal.permissions.get("indent.approve")
    can_edit = ind.status in ("draft", "submitted") and (
        ind.created_by == principal.user.id or svc.covers_site(db, create, principal, ind.site_id)
    )
    can_approve = ind.status == "submitted" and svc.covers_site(db, approve, principal, ind.site_id)
    return IndentOut(
        id=ind.id,
        code=ind.code,
        site_id=ind.site_id,
        site_code=site.code,
        site_name=site.name,
        store_id=ind.store_id,
        required_by=ind.required_by,
        priority=ind.priority,
        status=ind.status,
        remark=ind.remark,
        reject_reason=ind.reject_reason,
        created_at=ind.created_at,
        created_by_name=names.get(ind.created_by),
        approved_at=ind.approved_at,
        lines=[
            IndentLineOut(
                id=ln.id,
                product_id=ln.product_id,
                product_name=ln.product.name if ln.product else None,
                free_text=ln.free_text,
                qty=ln.qty,
                unit=ln.unit,
                base_qty=ln.base_qty,
                base_unit=ln.product.unit if ln.product else ln.unit,
                boq_line_id=ln.boq_line_id,
                area_scope_id=ln.area_scope_id,
                remark=ln.remark,
                ordered_qty=ln.ordered_qty,
                received_qty=ln.received_qty,
            )
            for ln in ind.lines
        ],
        can_edit=can_edit,
        can_approve=can_approve,
    )


def _visible_indent(db, indent_id, scope, principal) -> Indent:
    ind = db.get(Indent, indent_id)
    if ind is None or not svc.covers_site(db, scope, principal, ind.site_id, ind.created_by):
        raise _not_found("Indent")
    return ind


def _indent_lines(db: Session, site_id: int, body: IndentIn, user_id) -> list[IndentLine]:
    out = []
    for ln in body.lines:
        if ln.area_scope_id:
            scope = db.get(AreaScope, ln.area_scope_id)
            if scope is None or scope.site_id != site_id:
                raise unprocessable("That area scope is not on this site")
        if ln.product_id:
            product = _product(db, ln.product_id)
            unit = ln.unit or product.unit
            base = svc.to_base(db, product, ln.qty, unit)
        else:
            unit, base = ln.unit, ln.qty
        out.append(
            IndentLine(
                product_id=ln.product_id,
                free_text=(ln.free_text or None),
                qty=ln.qty,
                unit=unit,
                base_qty=base,
                boq_line_id=ln.boq_line_id,
                area_scope_id=ln.area_scope_id,
                remark=ln.remark,
                created_by=user_id,
            )
        )
    return out


@router.get("/indents")
def list_indents(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IndentView,
    limit: Limit = 50,
    offset: Offset = 0,
    q: Search = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    site_id: int | None = None,
) -> Page[IndentOut]:
    query = select(Indent).where(svc.by_site(scope, principal, Indent.site_id, Indent.created_by))
    if status_:
        query = query.where(Indent.status.in_(status_.split(",")))
    if site_id is not None:
        query = query.where(Indent.site_id == site_id)
    if q:
        query = query.where(Indent.code.ilike(like(q)))
    rows, total = paginate(db, query.order_by(Indent.id.desc()), limit, offset)
    return Page(
        items=[_indent_out(db, i, principal) for i in rows], total=total, limit=limit, offset=offset
    )


@router.get("/indents/{indent_id}")
def get_indent(
    indent_id: int, db: DbSession, principal: CurrentPrincipal, scope: IndentView
) -> IndentOut:
    return _indent_out(db, _visible_indent(db, indent_id, scope, principal), principal)


@router.post("/indents", status_code=status.HTTP_201_CREATED)
def create_indent(
    body: IndentIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("indent.create"))],
) -> IndentOut:
    site = db.get(Site, body.site_id)
    if site is None:
        raise unprocessable("Site not found")
    if not svc.covers_site(db, scope, principal, site.id, site.created_by):
        raise _forbidden(f"raise an indent for {site.code}")
    if site.status == "closed":
        raise _conflict(f"{site.code} is closed")
    store = svc.site_store(db, site, principal.user.id)
    ind = Indent(
        code=svc.next_code(db, "IND"),
        site_id=site.id,
        store_id=store.id,
        required_by=body.required_by,
        priority=body.priority,
        remark=body.remark,
        status="submitted" if body.submit else "draft",
        created_by=principal.user.id,
    )
    ind.lines = _indent_lines(db, site.id, body, principal.user.id)
    db.add(ind)
    db.flush()
    _record(
        db,
        request,
        principal,
        "indent.create",
        "indent",
        ind.id,
        after=audit.model_snapshot(ind, "lines"),
    )
    db.commit()
    db.refresh(ind)
    return _indent_out(db, ind, principal)


@router.put("/indents/{indent_id}")
def update_indent(
    indent_id: int,
    body: IndentIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IndentView,
) -> IndentOut:
    ind = _visible_indent(db, indent_id, scope, principal)
    if not _indent_out(db, ind, principal).can_edit:
        raise _forbidden(f"change {ind.code}")
    if body.site_id != ind.site_id:
        raise unprocessable("An indent cannot move to another site")
    before = audit.model_snapshot(ind, "lines")
    ind.required_by, ind.priority, ind.remark = body.required_by, body.priority, body.remark
    ind.lines = _indent_lines(db, ind.site_id, body, principal.user.id)
    if body.submit:
        ind.status = "submitted"
    db.flush()
    _record(
        db,
        request,
        principal,
        "indent.update",
        "indent",
        ind.id,
        before,
        audit.model_snapshot(ind, "lines"),
    )
    db.commit()
    db.refresh(ind)
    return _indent_out(db, ind, principal)


def _indent_action(db, request, principal, scope, indent_id, action) -> IndentOut:
    ind = _visible_indent(db, indent_id, scope, principal)
    before = {"status": ind.status}
    action(ind)
    _record(
        db,
        request,
        principal,
        "indent.status",
        "indent",
        ind.id,
        before,
        {"status": ind.status, "reason": ind.reject_reason},
    )
    db.commit()
    db.refresh(ind)
    return _indent_out(db, ind, principal)


@router.post("/indents/{indent_id}/submit")
def submit_indent(
    indent_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: IndentView
) -> IndentOut:
    def act(ind):
        if ind.status != "draft":
            raise _conflict(f"{ind.code} is {ind.status}")
        if not _indent_out(db, ind, principal).can_edit:
            raise _forbidden(f"submit {ind.code}")
        ind.status = "submitted"

    return _indent_action(db, request, principal, scope, indent_id, act)


def _approver(db, principal, ind):
    if not svc.covers_site(db, principal.permissions.get("indent.approve"), principal, ind.site_id):
        raise _forbidden(f"approve {ind.code}")
    if ind.status != "submitted":
        raise _conflict(f"{ind.code} is {ind.status}")


@router.post("/indents/{indent_id}/approve")
def approve_indent(
    indent_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: IndentView
) -> IndentOut:
    def act(ind):
        _approver(db, principal, ind)
        ind.status, ind.approved_by, ind.approved_at = "approved", principal.user.id, _now()
        ind.reject_reason = None

    return _indent_action(db, request, principal, scope, indent_id, act)


@router.post("/indents/{indent_id}/reject")
def reject_indent(
    indent_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: IndentView,
) -> IndentOut:
    def act(ind):
        _approver(db, principal, ind)
        ind.status, ind.reject_reason = "rejected", body.reason

    return _indent_action(db, request, principal, scope, indent_id, act)


@router.post("/indents/{indent_id}/cancel")
def cancel_indent(
    indent_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: IndentView
) -> IndentOut:
    def act(ind):
        if ind.status not in ("draft", "submitted", "approved"):
            raise _conflict(f"{ind.code} is {ind.status}")
        mine = ind.created_by == principal.user.id
        approver = svc.covers_site(
            db, principal.permissions.get("indent.approve"), principal, ind.site_id
        )
        if not (mine or approver):
            raise _forbidden(f"cancel {ind.code}")
        ind.status = "cancelled"

    return _indent_action(db, request, principal, scope, indent_id, act)


# --- RFQs ----------------------------------------------------------------------------------------


def _po_cond(scope: str, principal: Principal) -> ColumnElement[bool]:
    if scope == "own":
        return PurchaseOrder.created_by == principal.user.id
    return _store_cond(scope, principal, PurchaseOrder.store_id)


def _rfq_out(db: Session, rfq: Rfq) -> RfqOut:
    indent_ids = list(db.scalars(select(RfqIndent.indent_id).where(RfqIndent.rfq_id == rfq.id)))
    codes = list(db.scalars(select(Indent.code).where(Indent.id.in_(indent_ids or [0]))))
    quotes = {(q.rfq_line_id, q.vendor_id): q for q in rfq.quotes}
    vendor_freight = {v.vendor_id: Decimal(v.freight) for v in rfq.vendors}
    # each vendor's freight is shared over the lines it quoted, by value
    value = defaultdict(Decimal)
    for (line_id, vendor_id), q in quotes.items():
        line = next((ln for ln in rfq.lines if ln.id == line_id), None)
        if line is not None:
            value[vendor_id] += Decimal(q.rate) * Decimal(line.qty)
    totals = defaultdict(Decimal)
    lines = []
    for ln in rfq.lines:
        cells = []
        for v in rfq.vendors:
            q = quotes.get((ln.id, v.vendor_id))
            if q is None:
                continue
            line_value = Decimal(q.rate) * Decimal(ln.qty)
            share = (
                vendor_freight[v.vendor_id] * line_value / value[v.vendor_id]
                if value[v.vendor_id]
                else ZERO
            )
            landed = Decimal(q.rate) + (Decimal(q.freight) + share) / Decimal(ln.qty)
            totals[v.vendor_id] += line_value + Decimal(q.freight) + share
            cells.append(
                QuoteCell(
                    vendor_id=v.vendor_id,
                    rate=q.rate,
                    gst_percent=q.gst_percent,
                    freight=q.freight,
                    lead_days=q.lead_days,
                    landed_rate=landed.quantize(svc.RATE),
                    lowest=False,
                )
            )
        if cells:
            low = min(c.landed_rate for c in cells)
            for c in cells:
                c.lowest = c.landed_rate == low
        lines.append(
            RfqLineOut(
                id=ln.id,
                indent_line_id=ln.indent_line_id,
                product_id=ln.product_id,
                product_name=ln.product.name,
                qty=ln.qty,
                unit=ln.unit,
                chosen_vendor_id=ln.chosen_vendor_id,
                choice_reason=ln.choice_reason,
                quotes=cells,
            )
        )
    return RfqOut(
        id=rfq.id,
        code=rfq.code,
        due_date=rfq.due_date,
        status=rfq.status,
        remark=rfq.remark,
        created_at=rfq.created_at,
        indent_ids=indent_ids,
        indent_codes=codes,
        vendors=[
            RfqVendorOut(
                vendor_id=v.vendor_id,
                name=v.vendor.name,
                freight=v.freight,
                total=svc.money(totals[v.vendor_id]),
            )
            for v in rfq.vendors
        ],
        lines=lines,
        po_ids=list(db.scalars(select(PurchaseOrder.id).where(PurchaseOrder.rfq_id == rfq.id))),
    )


def _rfq(db, rfq_id) -> Rfq:
    rfq = db.get(Rfq, rfq_id)
    if rfq is None:
        raise _not_found("RFQ")
    return rfq


def _orderable_indents(db: Session, indent_ids: list[int], principal: Principal) -> list[Indent]:
    out = []
    view = principal.permissions.get("indent.view")
    for i in dict.fromkeys(indent_ids):
        ind = db.get(Indent, i)
        if ind is None or not svc.covers_site(db, view, principal, ind.site_id, ind.created_by):
            raise unprocessable(f"Indent {i} not found")
        if ind.status not in ("approved", "partly_ordered"):
            raise _conflict(f"{ind.code} is {ind.status}; only approved indents are ordered")
        out.append(ind)
    return out


@router.get("/rfqs")
def list_rfqs(
    db: DbSession, _: PoView, limit: Limit = 50, offset: Offset = 0, q: Search = None
) -> Page[RfqOut]:
    query = select(Rfq)
    if q:
        query = query.where(Rfq.code.ilike(like(q)))
    rows, total = paginate(db, query.order_by(Rfq.id.desc()), limit, offset)
    return Page(items=[_rfq_out(db, r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: int, db: DbSession, _: PoView) -> RfqOut:
    return _rfq_out(db, _rfq(db, rfq_id))


@router.post("/rfqs", status_code=status.HTTP_201_CREATED)
def create_rfq(
    body: RfqIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PoEdit
) -> RfqOut:
    """An RFQ for what the approved indents still need (product lines only)."""
    indents = _orderable_indents(db, body.indent_ids, principal)
    vendors = [db.get(Vendor, v) for v in dict.fromkeys(body.vendor_ids)]
    if any(v is None for v in vendors):
        raise unprocessable("Vendor not found")
    rfq = Rfq(
        code=svc.next_code(db, "RFQ"),
        due_date=body.due_date,
        remark=body.remark,
        created_by=principal.user.id,
    )
    for ind in indents:
        for ln in ind.lines:
            left = Decimal(ln.base_qty) - Decimal(ln.ordered_qty)
            if ln.product_id is None or left <= 0:
                continue
            rfq.lines.append(
                RfqLine(
                    indent_line_id=ln.id,
                    product_id=ln.product_id,
                    qty=left,
                    unit=ln.product.unit,
                    created_by=principal.user.id,
                )
            )
    if not rfq.lines:
        raise unprocessable(
            "Nothing left to order on these indents (lines not in the product master are "
            "bought with a direct PO)"
        )
    rfq.vendors = [RfqVendor(vendor_id=v.id, created_by=principal.user.id) for v in vendors]
    db.add(rfq)
    db.flush()
    for ind in indents:
        db.add(RfqIndent(rfq_id=rfq.id, indent_id=ind.id))
    _record(
        db,
        request,
        principal,
        "rfq.create",
        "rfq",
        rfq.id,
        after=audit.model_snapshot(rfq, "lines"),
    )
    db.commit()
    db.refresh(rfq)
    return _rfq_out(db, rfq)


@router.put("/rfqs/{rfq_id}/quotes")
def save_quotes(
    rfq_id: int,
    body: QuotesIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PoEdit,
) -> RfqOut:
    """Enter or change the vendors' rates (a line left out keeps its quote)."""
    rfq = _rfq(db, rfq_id)
    if rfq.status in ("closed", "cancelled"):
        raise _conflict(f"{rfq.code} is {rfq.status}")
    line_ids = {ln.id: ln for ln in rfq.lines}
    vendors = {v.vendor_id: v for v in rfq.vendors}
    existing = {(q.rfq_line_id, q.vendor_id): q for q in rfq.quotes}
    for q in body.quotes:
        if q.rfq_line_id not in line_ids or q.vendor_id not in vendors:
            raise unprocessable("A quote is for a line or vendor that is not on this RFQ")
        row = existing.get((q.rfq_line_id, q.vendor_id))
        if row is None:
            row = RfqQuote(
                rfq_id=rfq.id,
                rfq_line_id=q.rfq_line_id,
                vendor_id=q.vendor_id,
                product_id=line_ids[q.rfq_line_id].product_id,
                created_by=principal.user.id,
            )
            rfq.quotes.append(row)
        for k in ("rate", "gst_percent", "freight", "lead_days", "remark"):
            setattr(row, k, getattr(q, k))
    for vf in body.vendor_freight:
        if vf.vendor_id not in vendors:
            raise unprocessable("Freight for a vendor that is not on this RFQ")
        vendors[vf.vendor_id].freight = vf.freight
    if rfq.status == "draft":
        rfq.status = "sent"
    _record(db, request, principal, "rfq.quotes", "rfq", rfq.id, after=body.model_dump(mode="json"))
    db.commit()
    db.refresh(rfq)
    return _rfq_out(db, rfq)


@router.post("/rfqs/{rfq_id}/choose")
def choose_vendor(
    rfq_id: int,
    body: list[ChoiceIn],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PoEdit,
) -> RfqOut:
    """Pick the vendor of a line. Anything but the lowest landed rate needs a reason."""
    rfq = _rfq(db, rfq_id)
    if rfq.status in ("closed", "cancelled"):
        raise _conflict(f"{rfq.code} is {rfq.status}")
    out = _rfq_out(db, rfq)
    lines = {ln.id: ln for ln in out.lines}
    for c in body:
        line = lines.get(c.rfq_line_id)
        cell = next((q for q in line.quotes if q.vendor_id == c.vendor_id), None) if line else None
        if cell is None:
            raise unprocessable("That vendor has not quoted this line")
        if not cell.lowest and not (c.reason or "").strip():
            raise unprocessable(
                f"{line.product_name}: give a reason for not taking the lowest landed rate"
            )
        row = next(ln for ln in rfq.lines if ln.id == c.rfq_line_id)
        row.chosen_vendor_id = c.vendor_id
        row.choice_reason = None if cell.lowest else c.reason
    _record(
        db, request, principal, "rfq.choose", "rfq", rfq.id, after=[c.model_dump() for c in body]
    )
    db.commit()
    db.refresh(rfq)
    return _rfq_out(db, rfq)


@router.post("/rfqs/{rfq_id}/po", status_code=status.HTTP_201_CREATED)
def rfq_to_po(
    rfq_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: PoEdit,
    store_id: int | None = None,
    from_gstin_id: int | None = None,
) -> list[PoOut]:
    """One draft PO per chosen vendor (a line without a choice takes the lowest landed rate).
    The vendor's freight becomes a freight charge (added to material cost)."""
    rfq = _rfq(db, rfq_id)
    if rfq.status in ("closed", "cancelled"):
        raise _conflict(f"{rfq.code} is {rfq.status}")
    out = _rfq_out(db, rfq)
    by_vendor: dict[int, list] = defaultdict(list)
    for ln in out.lines:
        vendor_id = ln.chosen_vendor_id or next((q.vendor_id for q in ln.quotes if q.lowest), None)
        if vendor_id is None:
            raise unprocessable(f"{ln.product_name}: no vendor has quoted")
        by_vendor[vendor_id].append(ln)
    indents = [db.get(Indent, i) for i in out.indent_ids]
    if store_id is None:
        stores = {i.store_id for i in indents}
        store_id = stores.pop() if len(stores) == 1 else svc.godown(db).id
    quotes = {(q.rfq_line_id, q.vendor_id): q for q in rfq.quotes}
    vendor_freight = {v.vendor_id: Decimal(v.freight) for v in rfq.vendors}
    pos = []
    for vendor_id, lines in by_vendor.items():
        line_freight = sum((Decimal(quotes[(ln.id, vendor_id)].freight) for ln in lines), ZERO)
        freight = vendor_freight[vendor_id] + line_freight
        body = PoIn(
            vendor_id=vendor_id,
            store_id=store_id,
            from_gstin_id=from_gstin_id,
            indent_ids=out.indent_ids,
            lines=[
                {
                    "indent_line_id": ln.indent_line_id,
                    "product_id": ln.product_id,
                    "qty": ln.qty,
                    "unit": ln.unit,
                    "rate": quotes[(ln.id, vendor_id)].rate,
                    "gst_percent": quotes[(ln.id, vendor_id)].gst_percent
                    if db.get(Vendor, vendor_id).gstin
                    else ZERO,
                }
                for ln in lines
            ],
            charges=[{"kind": "freight", "description": "Freight", "amount": freight}]
            if freight > 0
            else [],
        )
        po = _new_po(db, body, principal)
        po.rfq_id = rfq.id
        pos.append(po)
    rfq.status = "closed"
    db.flush()
    for po in pos:
        _record(
            db,
            request,
            principal,
            "po.create",
            "purchase_order",
            po.id,
            after={"code": po.code, "rfq": rfq.code},
        )
    db.commit()
    return [_po_out(db, db.get(PurchaseOrder, po.id), principal) for po in pos]


# --- purchase orders -----------------------------------------------------------------------------


def _limit(db: Session) -> Decimal:
    return Decimal(_profile(db).po_approval_limit)


def _po_out(db: Session, po: PurchaseOrder, principal: Principal) -> PoOut:
    store = db.get(Store, po.store_id)
    gstin = db.get(CompanyGstin, po.from_gstin_id) if po.from_gstin_id else None
    names = _names(db, [po.created_by, po.approved_by])
    limit = _limit(db)
    needs_approver = Decimal(po.grand_total) > limit
    perms = principal.permissions
    edit_ok = _store_ok(db, perms.get("po.edit"), principal, store)
    approve_ok = _store_ok(db, perms.get("po.approve"), principal, store)
    return PoOut(
        id=po.id,
        code=po.code,
        vendor_id=po.vendor_id,
        vendor_name=po.vendor.name,
        vendor_gstin=po.vendor.gstin,
        from_gstin_id=po.from_gstin_id,
        from_gstin=gstin.gstin if gstin else None,
        store_id=po.store_id,
        store_name=store.name,
        rfq_id=po.rfq_id,
        po_date=po.po_date,
        expected_delivery=po.expected_delivery,
        payment_terms=po.payment_terms,
        remark=po.remark,
        status=po.status,
        interstate=po.interstate,
        approved_at=po.approved_at,
        approved_by_name=names.get(po.approved_by),
        sent_at=po.sent_at,
        created_at=po.created_at,
        created_by_name=names.get(po.created_by),
        subtotal=po.subtotal,
        discount_total=po.discount_total,
        taxable=po.taxable,
        cgst=po.cgst,
        sgst=po.sgst,
        igst=po.igst,
        charges_total=po.charges_total,
        round_off=po.round_off,
        grand_total=po.grand_total,
        indent_ids=list(db.scalars(select(PoIndent.indent_id).where(PoIndent.po_id == po.id))),
        lines=[
            PoLineOut(
                id=ln.id,
                indent_line_id=ln.indent_line_id,
                product_id=ln.product_id,
                product_code=ln.product.code,
                product_name=ln.product.name,
                qty=ln.qty,
                unit=ln.unit,
                base_qty=ln.base_qty,
                rate=ln.rate,
                discount_percent=ln.discount_percent,
                gst_percent=ln.gst_percent,
                amount=ln.amount,
                received_qty=ln.received_qty,
                hsn_code=ln.product.hsn_code,
                indent_qty=svc.indent_qty_text(db, ln),
                contract_rate=ln.contract_rate,
                above_contract_percent=(
                    (
                        (Decimal(ln.rate) - Decimal(ln.contract_rate))
                        / Decimal(ln.contract_rate)
                        * 100
                    ).quantize(Decimal("0.1"))
                    if ln.contract_rate and Decimal(ln.rate) > Decimal(ln.contract_rate)
                    else None
                ),
                rate_reason=ln.rate_reason,
            )
            for ln in po.lines
        ],
        charges=[
            PoChargeOut(
                id=c.id,
                kind=c.kind,
                description=c.description,
                amount=c.amount,
                gst_percent=c.gst_percent,
                add_to_cost=c.add_to_cost,
            )
            for c in po.charges
        ],
        approval_limit=limit,
        vendor_registered=bool(po.vendor.gstin),
        gstin_missing=svc.our_gstin(db, po) is None,
        warnings=svc.po_warnings(db, po),
        needs_approver=needs_approver,
        can_edit=edit_ok and po.status in ("draft", "pending_approval"),
        can_approve=po.status == "pending_approval"
        and (approve_ok or (edit_ok and not needs_approver)),
    )


def _visible_po(db, po_id, scope, principal) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise _not_found("Purchase order")
    store = db.get(Store, po.store_id)
    if not (
        _store_ok(db, scope, principal, store)
        or (scope == "own" and po.created_by == principal.user.id)
    ):
        raise _not_found("Purchase order")
    return po


def _fill_po(db: Session, po: PurchaseOrder, body: PoIn, principal: Principal) -> None:
    vendor = db.get(Vendor, body.vendor_id)
    if vendor is None:
        raise unprocessable("Vendor not found")
    store = _store_for_edit(db, body.store_id, "po.edit", principal, "order material")
    gstin = None
    if body.from_gstin_id:
        gstin = db.get(CompanyGstin, body.from_gstin_id)
        if gstin is None:
            raise unprocessable("GSTIN address not found")
    else:
        gstin = (
            db.get(CompanyGstin, store.gstin_address_id)
            if store.gstin_address_id
            else db.scalar(
                select(CompanyGstin)
                .order_by(CompanyGstin.is_default.desc(), CompanyGstin.id)
                .limit(1)
            )
        )
    po.vendor_id, po.vendor = vendor.id, vendor
    po.store_id = store.id
    po.from_gstin_id = gstin.id if gstin else None
    po.interstate = svc.is_interstate(vendor, gstin)
    for k in ("expected_delivery", "payment_terms", "remark"):
        setattr(po, k, getattr(body, k))
    if body.payment_terms is None and vendor.payment_terms_days:
        po.payment_terms = f"{vendor.payment_terms_days} days from the invoice"
    # an unregistered supplier cannot charge GST: 0 % unless someone typed a rate (then warned)
    unregistered = not vendor.gstin
    lines = []
    for ln in body.lines:
        product = _product(db, ln.product_id)
        if unregistered and "gst_percent" not in ln.model_fields_set:
            ln.gst_percent = ZERO
        if ln.indent_line_id:
            il = db.get(IndentLine, ln.indent_line_id)
            if il is None or il.product_id != product.id:
                raise unprocessable(f"{product.name}: the indent line is for another product")
        unit = ln.unit or product.unit
        base_qty = svc.to_base(db, product, ln.qty, unit)
        # the vendor's rate contract fills the rate; a higher rate needs a reason
        from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

        rate, contract, contract_rate = sitecontrol.po_line_rate(
            db,
            vendor.id,
            product,
            unit,
            ln.qty,
            base_qty,
            ln.rate,
            ln.rate_reason,
            po.po_date or date.today(),
        )
        lines.append(
            PoLine(
                indent_line_id=ln.indent_line_id,
                product_id=product.id,
                product=product,
                qty=ln.qty,
                unit=unit,
                base_qty=base_qty,
                rate=rate,
                contract_id=contract.id if contract else None,
                contract_rate=contract_rate,
                rate_reason=(ln.rate_reason or None)
                if contract_rate is not None and rate > contract_rate
                else None,
                discount_percent=ln.discount_percent,
                gst_percent=ln.gst_percent,
                amount=ZERO,
                created_by=principal.user.id,
            )
        )
    po.lines = lines
    for c in body.charges:
        if unregistered and "gst_percent" not in c.model_fields_set:
            c.gst_percent = ZERO
    po.charges = [
        PoCharge(
            kind=c.kind,
            description=c.description,
            amount=c.amount,
            gst_percent=c.gst_percent,
            add_to_cost=c.kind == "freight" if c.add_to_cost is None else c.add_to_cost,
            created_by=principal.user.id,
        )
        for c in body.charges
    ]
    svc.compute_totals(po)


def _link_indents(db: Session, po: PurchaseOrder, body: PoIn) -> None:
    ids = set(body.indent_ids)
    for ln in po.lines:
        if ln.indent_line_id:
            ids.add(db.get(IndentLine, ln.indent_line_id).indent_id)
    db.query(PoIndent).filter(PoIndent.po_id == po.id).delete()
    for i in ids:
        if db.get(Indent, i) is None:
            raise unprocessable(f"Indent {i} not found")
        db.add(PoIndent(po_id=po.id, indent_id=i))


def _new_po(db: Session, body: PoIn, principal: Principal) -> PurchaseOrder:
    on = body.po_date or date.today()
    po = PurchaseOrder(
        code=svc.next_code(db, "PO", on), po_date=on, status="draft", created_by=principal.user.id
    )
    _fill_po(db, po, body, principal)
    db.add(po)
    db.flush()
    _link_indents(db, po, body)
    return po


@router.get("/pos")
def list_pos(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: PoView,
    limit: Limit = 50,
    offset: Offset = 0,
    q: Search = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    vendor_id: int | None = None,
    site_id: int | None = None,
) -> Page[PoOut]:
    query = select(PurchaseOrder).where(_po_cond(scope, principal))
    if status_:
        query = query.where(PurchaseOrder.status.in_(status_.split(",")))
    if vendor_id is not None:
        query = query.where(PurchaseOrder.vendor_id == vendor_id)
    if site_id is not None:
        query = query.where(
            or_(
                PurchaseOrder.store_id.in_(select(Store.id).where(Store.site_id == site_id)),
                PurchaseOrder.id.in_(
                    select(PoIndent.po_id)
                    .join(Indent, Indent.id == PoIndent.indent_id)
                    .where(Indent.site_id == site_id)
                ),
            )
        )
    if q:
        query = query.where(
            or_(
                PurchaseOrder.code.ilike(like(q)),
                PurchaseOrder.vendor_id.in_(select(Vendor.id).where(Vendor.name.ilike(like(q)))),
            )
        )
    rows, total = paginate(db, query.order_by(PurchaseOrder.id.desc()), limit, offset)
    return Page(
        items=[_po_out(db, p, principal) for p in rows], total=total, limit=limit, offset=offset
    )


@router.get("/pos/{po_id}")
def get_po(po_id: int, db: DbSession, principal: CurrentPrincipal, scope: PoView) -> PoOut:
    return _po_out(db, _visible_po(db, po_id, scope, principal), principal)


@router.post("/pos", status_code=status.HTTP_201_CREATED)
def create_po(
    body: PoIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PoEdit
) -> PoOut:
    po = _new_po(db, body, principal)
    _record(
        db,
        request,
        principal,
        "po.create",
        "purchase_order",
        po.id,
        after=audit.model_snapshot(po, "lines", "charges"),
    )
    db.commit()
    return _po_out(db, db.get(PurchaseOrder, po.id), principal)


@router.put("/pos/{po_id}")
def update_po(
    po_id: int,
    body: PoIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: PoView,
) -> PoOut:
    po = _visible_po(db, po_id, scope, principal)
    if po.status not in ("draft", "pending_approval"):
        raise _conflict(f"{po.code} is {po.status}; it can no longer be changed")
    before = audit.model_snapshot(po, "lines", "charges")
    if body.po_date and body.po_date != po.po_date:
        if svc.financial_year(body.po_date) != svc.financial_year(po.po_date):
            raise unprocessable("A PO cannot move to another financial year")
        po.po_date = body.po_date
    _fill_po(db, po, body, principal)
    po.status = "draft"  # changed: approve again
    db.flush()
    _link_indents(db, po, body)
    _record(
        db,
        request,
        principal,
        "po.update",
        "purchase_order",
        po.id,
        before,
        audit.model_snapshot(po, "lines", "charges"),
    )
    db.commit()
    db.refresh(po)
    return _po_out(db, po, principal)


def _approve_po(db: Session, po: PurchaseOrder, principal: Principal) -> None:
    po.status, po.approved_by, po.approved_at = "approved", principal.user.id, _now()
    for ln in po.lines:
        if ln.indent_line_id:
            il = db.get(IndentLine, ln.indent_line_id)
            il.ordered_qty = Decimal(il.ordered_qty) + Decimal(ln.base_qty)
    db.flush()
    for i in db.scalars(select(PoIndent.indent_id).where(PoIndent.po_id == po.id)):
        ind = db.get(Indent, i)
        db.refresh(ind)
        svc.refresh_indent(ind)


def _po_status(db, request, principal, po, before, reason=None) -> PoOut:
    _record(
        db,
        request,
        principal,
        "po.status",
        "purchase_order",
        po.id,
        {"status": before},
        {"status": po.status, "reason": reason},
    )
    db.commit()
    db.refresh(po)
    return _po_out(db, po, principal)


@router.post("/pos/{po_id}/submit")
def submit_po(
    po_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: PoView
) -> PoOut:
    """Up to the approval limit the creator's PO is approved at once; above it, or for a
    caller who may approve any amount, it waits for (or gets) po.approve."""
    po = _visible_po(db, po_id, scope, principal)
    if po.status != "draft":
        raise _conflict(f"{po.code} is {po.status}")
    out = _po_out(db, po, principal)
    if not _store_ok(
        db, principal.permissions.get("po.edit"), principal, db.get(Store, po.store_id)
    ):
        raise _forbidden(f"submit {po.code}")
    if not po.lines:
        raise unprocessable("Add a line first")
    if out.needs_approver:
        po.status = "pending_approval"
    else:
        _approve_po(db, po, principal)
    return _po_status(db, request, principal, po, "draft")


@router.post("/pos/{po_id}/approve")
def approve_po(
    po_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: PoView
) -> PoOut:
    po = _visible_po(db, po_id, scope, principal)
    if po.status != "pending_approval":
        raise _conflict(f"{po.code} is {po.status}")
    if not _po_out(db, po, principal).can_approve:
        limit = _limit(db)
        raise _forbidden(
            f"approve {po.code}: above ₹{limit:,.0f} it needs a PO approver (po.approve)"
        )
    _approve_po(db, po, principal)
    return _po_status(db, request, principal, po, "pending_approval")


@router.post("/pos/{po_id}/reject")
def reject_po(
    po_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: PoView,
) -> PoOut:
    po = _visible_po(db, po_id, scope, principal)
    if po.status != "pending_approval":
        raise _conflict(f"{po.code} is {po.status}")
    if not _po_out(db, po, principal).can_approve:
        raise _forbidden(f"reject {po.code}")
    po.status = "draft"
    po.remark = f"{po.remark}\n" if po.remark else ""
    po.remark += f"Sent back: {body.reason}"
    return _po_status(db, request, principal, po, "pending_approval", body.reason)


def _po_edit(db, principal, po, what):
    if not _store_ok(
        db, principal.permissions.get("po.edit"), principal, db.get(Store, po.store_id)
    ):
        raise _forbidden(f"{what} {po.code}")


@router.post("/pos/{po_id}/send")
def mark_sent(
    po_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: PoView
) -> PoOut:
    po = _visible_po(db, po_id, scope, principal)
    _po_edit(db, principal, po, "send")
    if po.status != "approved":
        raise _conflict(f"{po.code} is {po.status}; approve it first")
    if svc.our_gstin(db, po) is None:
        raise unprocessable(
            "GSTIN not set: add the company GSTIN (Settings > GSTIN addresses) first"
        )
    po.status, po.sent_at = "sent", _now()
    # a PO going straight to a site gets a delivery note to be confirmed at the site
    from app.sitecontrol import deliveries  # noqa: PLC0415  (sitecontrol imports this module)

    deliveries.for_po(db, po, principal.user.id)
    return _po_status(db, request, principal, po, "approved")


@router.post("/pos/{po_id}/cancel")
def cancel_po(
    po_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: PoView,
) -> PoOut:
    po = _visible_po(db, po_id, scope, principal)
    _po_edit(db, principal, po, "cancel")
    if po.status in ("partly_received", "received", "closed", "cancelled"):
        raise _conflict(f"{po.code} is {po.status}")
    if db.scalar(select(Grn.id).where(Grn.po_id == po.id, Grn.status != "rejected").limit(1)):
        raise _conflict(f"{po.code} has a GRN; reject it first")
    before = po.status
    if before in ("approved", "sent"):
        for ln in po.lines:
            if ln.indent_line_id:
                il = db.get(IndentLine, ln.indent_line_id)
                il.ordered_qty = max(ZERO, Decimal(il.ordered_qty) - Decimal(ln.base_qty))
        db.flush()
        for i in db.scalars(select(PoIndent.indent_id).where(PoIndent.po_id == po.id)):
            svc.refresh_indent(db.get(Indent, i))
        db.query(FreightEntry).filter(FreightEntry.po_id == po.id).delete()
    po.status = "cancelled"
    return _po_status(db, request, principal, po, before, body.reason)


@router.post("/pos/{po_id}/close")
def close_po(
    po_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: PoView,
) -> PoOut:
    """Short-close a partly received PO: the rest will not come."""
    po = _visible_po(db, po_id, scope, principal)
    _po_edit(db, principal, po, "close")
    if po.status not in ("partly_received", "received", "sent", "approved"):
        raise _conflict(f"{po.code} is {po.status}")
    before = po.status
    po.status = "closed"
    return _po_status(db, request, principal, po, before, body.reason)


@router.get("/pos/{po_id}/pdf")
def po_pdf_file(po_id: int, db: DbSession, principal: CurrentPrincipal, scope: PoView) -> Response:
    po = _visible_po(db, po_id, scope, principal)
    data = po_pdf.pdf(db, po)
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{po.code}.pdf"'},
    )


# --- GRNs ----------------------------------------------------------------------------------------


def _grn_out(db: Session, g: Grn, principal: Principal) -> GrnOut:
    store = db.get(Store, g.store_id)
    names = _names(db, [g.created_by])
    perms = principal.permissions
    approvals = (1 if g.approved_by_1 else 0) + (1 if g.approved_by_2 else 0)
    approve_ok = _store_ok(db, perms.get("grn.approve"), principal, store)
    return GrnOut(
        id=g.id,
        code=g.code,
        po_id=g.po_id,
        po_code=db.scalar(select(PurchaseOrder.code).where(PurchaseOrder.id == g.po_id))
        if g.po_id
        else None,
        store_id=g.store_id,
        store_name=store.name,
        vendor_id=g.vendor_id,
        vendor_name=g.vendor.name,
        challan_no=g.challan_no,
        invoice_no=g.invoice_no,
        invoice_date=g.invoice_date,
        invoice_amount=g.invoice_amount,
        vehicle_no=g.vehicle_no,
        received_at=g.received_at,
        remark=g.remark,
        status=g.status,
        levels_required=g.levels_required,
        approvals=approvals,
        reject_reason=g.reject_reason,
        created_at=g.created_at,
        created_by_name=names.get(g.created_by),
        lines=[
            GrnLineOut(
                id=ln.id,
                po_line_id=ln.po_line_id,
                product_id=ln.product_id,
                product_name=ln.product.name,
                unit=ln.unit,
                ordered_qty=ln.ordered_qty,
                received_qty=ln.received_qty,
                invoice_qty=ln.invoice_qty,
                accepted_qty=ln.accepted_qty,
                rejected_qty=ln.rejected_qty,
                reason=ln.reason,
                rate=ln.rate,
                landed_rate=ln.landed_rate,
                base_unit=ln.product.unit,
            )
            for ln in g.lines
        ],
        photos=[GrnPhotoOut(id=p.id, kind=p.kind, filename=p.filename) for p in g.photos],
        can_edit=g.status == "draft" and _store_ok(db, perms.get("grn.edit"), principal, store),
        can_approve=g.status == "submitted" and approve_ok and g.approved_by_1 != principal.user.id,
    )


def _visible_grn(db, grn_id, scope, principal) -> Grn:
    g = db.get(Grn, grn_id)
    if g is None:
        raise _not_found("GRN")
    store = db.get(Store, g.store_id)
    if not (
        _store_ok(db, scope, principal, store)
        or (scope == "own" and g.created_by == principal.user.id)
    ):
        raise _not_found("GRN")
    return g


def _grn_lines(
    db: Session, body: GrnIn, po: PurchaseOrder | None, grn_id: int | None, user_id
) -> list[GrnLine]:
    out = []
    po_lines = {ln.id: ln for ln in po.lines} if po else {}
    for ln in body.lines:
        rejected = ln.rejected_qty
        accepted = ln.accepted_qty if ln.accepted_qty is not None else ln.received_qty - rejected
        if accepted < 0 or accepted + rejected > ln.received_qty:
            raise unprocessable("Accepted + rejected cannot be more than received")
        if rejected > 0 and not (ln.reason or "").strip():
            raise unprocessable("Give the reason for the rejected quantity")
        if po is not None:
            pl = po_lines.get(ln.po_line_id or 0)
            if pl is None:
                raise unprocessable("Each line must be a line of the PO")
            pending = Decimal(pl.qty) - Decimal(pl.received_qty)
            if accepted > pending:
                raise unprocessable(
                    f"{pl.product.name}: {accepted:f} {pl.unit} accepted but only "
                    f"{pending.normalize():f} pending on {po.code}"
                )
            rate = (Decimal(pl.amount) / Decimal(pl.qty)).quantize(svc.RATE)
            out.append(
                GrnLine(
                    po_line_id=pl.id,
                    product_id=pl.product_id,
                    unit=pl.unit,
                    ordered_qty=pending,
                    received_qty=ln.received_qty,
                    invoice_qty=ln.invoice_qty,
                    accepted_qty=accepted,
                    rejected_qty=rejected,
                    reason=ln.reason,
                    rate=rate,
                    created_by=user_id,
                )
            )
        else:
            if ln.product_id is None or ln.rate is None:
                raise unprocessable("A direct purchase line needs the product and its rate")
            product = _product(db, ln.product_id)
            unit = ln.unit or product.unit
            svc.to_base(db, product, Decimal(1), unit)  # the unit must convert
            out.append(
                GrnLine(
                    product_id=product.id,
                    unit=unit,
                    received_qty=ln.received_qty,
                    invoice_qty=ln.invoice_qty,
                    accepted_qty=accepted,
                    rejected_qty=rejected,
                    reason=ln.reason,
                    rate=ln.rate,
                    created_by=user_id,
                )
            )
    return out


@router.get("/grns")
def list_grns(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: GrnView,
    limit: Limit = 50,
    offset: Offset = 0,
    q: Search = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    po_id: int | None = None,
    store_id: int | None = None,
) -> Page[GrnOut]:
    cond = (
        Grn.created_by == principal.user.id
        if scope == "own"
        else _store_cond(scope, principal, Grn.store_id)
    )
    query = select(Grn).where(cond)
    if status_:
        query = query.where(Grn.status.in_(status_.split(",")))
    if po_id is not None:
        query = query.where(Grn.po_id == po_id)
    if store_id is not None:
        query = query.where(Grn.store_id == store_id)
    if q:
        query = query.where(or_(Grn.code.ilike(like(q)), Grn.invoice_no.ilike(like(q))))
    rows, total = paginate(db, query.order_by(Grn.id.desc()), limit, offset)
    return Page(
        items=[_grn_out(db, g, principal) for g in rows], total=total, limit=limit, offset=offset
    )


@router.get("/grns/{grn_id}")
def get_grn(grn_id: int, db: DbSession, principal: CurrentPrincipal, scope: GrnView) -> GrnOut:
    return _grn_out(db, _visible_grn(db, grn_id, scope, principal), principal)


def _grn_header(db: Session, g: Grn, body: GrnIn, principal: Principal) -> PurchaseOrder | None:
    po = None
    if body.po_id:
        po = db.get(PurchaseOrder, body.po_id)
        if po is None:
            raise unprocessable("Purchase order not found")
        if po.status not in ("approved", "sent", "partly_received"):
            raise _conflict(
                f"{po.code} is {po.status}; material is received against an " "approved PO"
            )
        g.vendor_id = po.vendor_id
        store_id = body.store_id or po.store_id
    else:
        if body.vendor_id is None or body.store_id is None:
            raise unprocessable("A direct purchase needs the vendor and the store")
        if db.get(Vendor, body.vendor_id) is None:
            raise unprocessable("Vendor not found")
        g.vendor_id = body.vendor_id
        store_id = body.store_id
    store = _store_for_edit(db, store_id, "grn.edit", principal, "receive material")
    g.po_id, g.store_id = po.id if po else None, store.id
    for k in ("challan_no", "invoice_no", "invoice_date", "invoice_amount", "vehicle_no", "remark"):
        setattr(g, k, getattr(body, k))
    g.received_at = body.received_at or date.today()
    return po


@router.post("/grns", status_code=status.HTTP_201_CREATED)
def create_grn(
    body: GrnIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("grn.edit"))],
) -> GrnOut:
    g = Grn(
        code=svc.next_code(db, "GRN"),
        status="submitted" if body.submit else "draft",
        levels_required=_profile(db).grn_approval_levels,
        created_by=principal.user.id,
    )
    po = _grn_header(db, g, body, principal)
    g.lines = _grn_lines(db, body, po, None, principal.user.id)
    db.add(g)
    db.flush()
    _record(
        db, request, principal, "grn.create", "grn", g.id, after=audit.model_snapshot(g, "lines")
    )
    db.commit()
    db.refresh(g)
    return _grn_out(db, g, principal)


@router.put("/grns/{grn_id}")
def update_grn(
    grn_id: int,
    body: GrnIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: GrnView,
) -> GrnOut:
    g = _visible_grn(db, grn_id, scope, principal)
    if not _grn_out(db, g, principal).can_edit:
        raise (
            _conflict(f"{g.code} is {g.status}")
            if g.status != "draft"
            else _forbidden(f"change {g.code}")
        )
    before = audit.model_snapshot(g, "lines")
    po = _grn_header(db, g, body, principal)
    g.lines = _grn_lines(db, body, po, g.id, principal.user.id)
    if body.submit:
        g.status = "submitted"
    db.flush()
    _record(
        db, request, principal, "grn.update", "grn", g.id, before, audit.model_snapshot(g, "lines")
    )
    db.commit()
    db.refresh(g)
    return _grn_out(db, g, principal)


@router.post("/grns/{grn_id}/submit")
def submit_grn(
    grn_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: GrnView
) -> GrnOut:
    g = _visible_grn(db, grn_id, scope, principal)
    if g.status != "draft":
        raise _conflict(f"{g.code} is {g.status}")
    if not _grn_out(db, g, principal).can_edit:
        raise _forbidden(f"submit {g.code}")
    g.status = "submitted"
    _record(
        db,
        request,
        principal,
        "grn.status",
        "grn",
        g.id,
        {"status": "draft"},
        {"status": "submitted"},
    )
    db.commit()
    return _grn_out(db, g, principal)


def _post_grn(db: Session, g: Grn, user_id) -> None:
    """Stock in at the landed rate; PO and indent received quantities move up."""
    po = db.get(PurchaseOrder, g.po_id) if g.po_id else None
    uplift = svc.cost_uplift(po)
    touched_indents = set()
    for ln in g.lines:
        accepted = Decimal(ln.accepted_qty)
        if accepted <= 0:
            continue
        product = db.get(Product, ln.product_id)
        base = svc.to_base(db, product, accepted, ln.unit)
        landed = Decimal(ln.rate) * uplift * accepted / base
        ln.landed_rate = landed.quantize(svc.RATE)
        svc.post(
            db,
            store_id=g.store_id,
            product=product,
            qty=base,
            rate=landed,
            ref_type="grn",
            ref_id=g.id,
            user_id=user_id,
            note=g.code,
        )
        if ln.po_line_id:
            pl = db.get(PoLine, ln.po_line_id)
            pl.received_qty = Decimal(pl.received_qty) + accepted
            if pl.indent_line_id:
                il = db.get(IndentLine, pl.indent_line_id)
                il.received_qty = Decimal(il.received_qty) + base
                touched_indents.add(il.indent_id)
    db.flush()
    if po is not None:
        db.refresh(po)
        svc.refresh_po(po)
        svc.grn_freight(db, po, g, user_id)
    for i in touched_indents:
        ind = db.get(Indent, i)
        db.refresh(ind)
        svc.refresh_indent(ind)


@router.post("/grns/{grn_id}/approve")
def approve_grn(
    grn_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: GrnView
) -> GrnOut:
    """Level 1, then level 2 by another person when two levels are required. The last approval
    puts the material in stock."""
    g = _visible_grn(db, grn_id, scope, principal)
    if g.status != "submitted":
        raise _conflict(f"{g.code} is {g.status}")
    store = db.get(Store, g.store_id)
    if not _store_ok(db, principal.permissions.get("grn.approve"), principal, store):
        raise _forbidden(f"approve {g.code}")
    if g.approved_by_1 == principal.user.id:
        raise _conflict(f"{g.code}: the second approval must be by someone else")
    if g.approved_by_1 is None:
        g.approved_by_1, g.approved_at_1 = principal.user.id, _now()
    else:
        g.approved_by_2, g.approved_at_2 = principal.user.id, _now()
    approvals = 1 if g.approved_by_2 is None else 2
    if approvals >= g.levels_required:
        g.status = "approved"
        _post_grn(db, g, principal.user.id)
    _record(
        db,
        request,
        principal,
        "grn.approve",
        "grn",
        g.id,
        {"status": "submitted"},
        {"status": g.status, "level": approvals},
    )
    db.commit()
    db.refresh(g)
    return _grn_out(db, g, principal)


@router.post("/grns/{grn_id}/reject")
def reject_grn(
    grn_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: GrnView,
) -> GrnOut:
    g = _visible_grn(db, grn_id, scope, principal)
    if g.status not in ("draft", "submitted"):
        raise _conflict(f"{g.code} is {g.status}")
    store = db.get(Store, g.store_id)
    if not _store_ok(db, principal.permissions.get("grn.approve"), principal, store):
        raise _forbidden(f"reject {g.code}")
    before = g.status
    g.status, g.reject_reason = "rejected", body.reason
    _record(
        db,
        request,
        principal,
        "grn.status",
        "grn",
        g.id,
        {"status": before},
        {"status": "rejected", "reason": body.reason},
    )
    db.commit()
    return _grn_out(db, g, principal)


def _media(rel: str) -> Path:
    return Path(settings.media_dir) / rel


@router.post("/grns/{grn_id}/photos", status_code=status.HTTP_201_CREATED)
async def add_grn_photo(
    grn_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: GrnView,
    file: Annotated[UploadFile, File(description="Photo or PDF, up to 15 MB")],
    kind: Annotated[str, Form(pattern="^(challan|invoice|material)$")] = "material",
) -> GrnOut:
    import re

    g = _visible_grn(db, grn_id, scope, principal)
    store = db.get(Store, g.store_id)
    if g.status == "approved" or not _store_ok(
        db, principal.permissions.get("grn.edit"), principal, store
    ):
        raise _forbidden(f"add photos to {g.code}")
    name = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", Path(file.filename or "photo.jpg").name)[:150]
    if Path(name).suffix.lower() not in PHOTO_TYPES:
        raise unprocessable("Upload a photo (.jpg, .png, .webp, .heic) or a PDF")
    data = await file.read(PHOTO_MAX + 1)
    if len(data) > PHOTO_MAX:
        raise unprocessable("The file is larger than 15 MB")
    rel = Path("grns") / str(g.id) / f"{uuid.uuid4().hex}__{name}"
    _media(str(rel)).parent.mkdir(parents=True, exist_ok=True)
    _media(str(rel)).write_bytes(data)
    g.photos.append(
        GrnPhoto(kind=kind, stored_path=str(rel), filename=name, created_by=principal.user.id)
    )
    _record(db, request, principal, "grn.photo", "grn", g.id, after={"file": name, "kind": kind})
    db.commit()
    db.refresh(g)
    return _grn_out(db, g, principal)


@router.get("/grns/{grn_id}/photos/{photo_id}")
def get_grn_photo(
    grn_id: int, photo_id: int, db: DbSession, principal: CurrentPrincipal, scope: GrnView
) -> FileResponse:
    g = _visible_grn(db, grn_id, scope, principal)
    photo = next((p for p in g.photos if p.id == photo_id), None)
    if photo is None or not _media(photo.stored_path).exists():
        raise _not_found("Photo")
    return FileResponse(_media(photo.stored_path), filename=photo.filename)


# --- transfers -----------------------------------------------------------------------------------


def _transfer_out(db: Session, t: Transfer, principal: Principal) -> TransferOut:
    src, dst = db.get(Store, t.from_store_id), db.get(Store, t.to_store_id)
    edit = principal.permissions.get("store.edit")
    return TransferOut(
        id=t.id,
        code=t.code,
        from_store_id=src.id,
        from_store_name=src.name,
        to_store_id=dst.id,
        to_store_name=dst.name,
        status=t.status,
        vehicle_no=t.vehicle_no,
        transporter=t.transporter,
        freight_amount=t.freight_amount,
        remark=t.remark,
        created_at=t.created_at,
        dispatched_at=t.dispatched_at,
        received_at=t.received_at,
        lines=[
            TransferLineOut(
                id=ln.id,
                product_id=ln.product_id,
                product_name=ln.product.name,
                unit=ln.product.unit,
                qty_sent=ln.qty_sent,
                qty_received=ln.qty_received,
                shortage_qty=ln.shortage_qty,
                shortage_reason=ln.shortage_reason,
                rate=ln.rate,
            )
            for ln in t.lines
        ],
        can_dispatch=t.status == "draft" and _store_ok(db, edit, principal, src),
        can_receive=t.status == "dispatched" and _store_ok(db, edit, principal, dst),
    )


def _transfer_cond(scope: str, principal: Principal) -> ColumnElement[bool]:
    return or_(
        _store_cond(scope, principal, Transfer.from_store_id),
        _store_cond(scope, principal, Transfer.to_store_id),
    )


def _visible_transfer(db, transfer_id, scope, principal) -> Transfer:
    t = db.get(Transfer, transfer_id)
    if t is None or not (
        _store_ok(db, scope, principal, db.get(Store, t.from_store_id))
        or _store_ok(db, scope, principal, db.get(Store, t.to_store_id))
    ):
        raise _not_found("Transfer")
    return t


def _dispatch(db: Session, t: Transfer, principal: Principal) -> None:
    src = db.get(Store, t.from_store_id)
    if not _store_ok(db, principal.permissions.get("store.edit"), principal, src):
        raise _forbidden(f"dispatch from {src.name}")
    for ln in t.lines:
        ln.rate = svc.take_out(
            db,
            store=src,
            product=ln.product,
            qty=ln.qty_sent,
            ref_type="transfer_out",
            ref_id=t.id,
            user_id=principal.user.id,
            note=t.code,
        )
    t.status, t.dispatched_at, t.dispatched_by = "dispatched", _now(), principal.user.id
    # a dispatch to a site store gets a delivery note to be confirmed at the site
    from app.sitecontrol import deliveries  # noqa: PLC0415  (sitecontrol imports this module)

    deliveries.for_transfer(db, t, principal.user.id)


@router.get("/transfers")
def list_transfers(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: StoreView,
    limit: Limit = 50,
    offset: Offset = 0,
    status_: Annotated[str | None, Query(alias="status")] = None,
    store_id: int | None = None,
    site_id: int | None = None,
) -> Page[TransferOut]:
    query = select(Transfer).where(_transfer_cond(scope, principal))
    if status_:
        query = query.where(Transfer.status.in_(status_.split(",")))
    if store_id is not None:
        query = query.where(
            or_(Transfer.from_store_id == store_id, Transfer.to_store_id == store_id)
        )
    if site_id is not None:
        stores = select(Store.id).where(Store.site_id == site_id)
        query = query.where(
            or_(Transfer.from_store_id.in_(stores), Transfer.to_store_id.in_(stores))
        )
    rows, total = paginate(db, query.order_by(Transfer.id.desc()), limit, offset)
    return Page(
        items=[_transfer_out(db, t, principal) for t in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/transfers/{transfer_id}")
def get_transfer(
    transfer_id: int, db: DbSession, principal: CurrentPrincipal, scope: StoreView
) -> TransferOut:
    return _transfer_out(db, _visible_transfer(db, transfer_id, scope, principal), principal)


@router.post("/transfers", status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: TransferIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("store.edit"))],
) -> TransferOut:
    if body.from_store_id == body.to_store_id:
        raise unprocessable("Pick two different stores")
    src, dst = db.get(Store, body.from_store_id), db.get(Store, body.to_store_id)
    if src is None or dst is None:
        raise unprocessable("Store not found")
    if not (_store_ok(db, scope, principal, src) or _store_ok(db, scope, principal, dst)):
        raise _forbidden(f"move material from {src.name} to {dst.name}")
    t = Transfer(
        code=svc.next_code(db, "TO"),
        from_store_id=src.id,
        to_store_id=dst.id,
        vehicle_no=body.vehicle_no,
        transporter=body.transporter,
        freight_amount=body.freight_amount,
        remark=body.remark,
        created_by=principal.user.id,
    )
    for ln in body.lines:
        product = _product(db, ln.product_id)
        qty = svc.to_base(db, product, ln.qty, ln.unit or product.unit)
        t.lines.append(
            TransferLine(
                product_id=product.id, product=product, qty_sent=qty, created_by=principal.user.id
            )
        )
    db.add(t)
    db.flush()
    if body.dispatch:
        _dispatch(db, t, principal)
    _record(
        db,
        request,
        principal,
        "transfer.create",
        "transfer",
        t.id,
        after=audit.model_snapshot(t, "lines"),
    )
    db.commit()
    db.refresh(t)
    return _transfer_out(db, t, principal)


@router.post("/transfers/{transfer_id}/dispatch")
def dispatch_transfer(
    transfer_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: StoreView
) -> TransferOut:
    t = _visible_transfer(db, transfer_id, scope, principal)
    if t.status != "draft":
        raise _conflict(f"{t.code} is {t.status}")
    _dispatch(db, t, principal)
    _record(
        db,
        request,
        principal,
        "transfer.dispatch",
        "transfer",
        t.id,
        {"status": "draft"},
        {"status": t.status},
    )
    db.commit()
    db.refresh(t)
    return _transfer_out(db, t, principal)


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(
    transfer_id: int,
    body: ReceiveIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: StoreView,
) -> TransferOut:
    """What arrived goes into the receiving store at the dispatch rate; the rest is recorded as
    a shortage. The freight is charged to the receiving site."""
    t = _visible_transfer(db, transfer_id, scope, principal)
    if t.status != "dispatched":
        raise _conflict(f"{t.code} is {t.status}")
    dst = db.get(Store, t.to_store_id)
    if not _store_ok(db, principal.permissions.get("store.edit"), principal, dst):
        raise _forbidden(f"receive into {dst.name}")
    given = {r.line_id: r for r in body.lines}
    if set(given) - {ln.id for ln in t.lines}:
        raise unprocessable("A line is not on this transfer")
    received = {}
    for ln in t.lines:
        r = given.get(ln.id)
        got = r.qty_received if r else Decimal(ln.qty_sent)
        if got > Decimal(ln.qty_sent):
            raise unprocessable(f"{ln.product.name}: more received than was sent")
        if Decimal(ln.qty_sent) - got > 0 and not (r and (r.shortage_reason or "").strip()):
            raise unprocessable(f"{ln.product.name}: give the reason for the shortage")
        received[ln.id] = (got, r.shortage_reason if r else None)
    svc.receive_transfer(db, t, received, principal.user.id)
    # a delivery note waiting for this transfer is settled by the store's receipt too
    from app.sitecontrol import deliveries  # noqa: PLC0415  (sitecontrol imports this module)

    deliveries.settle_by_transfer_receipt(db, t, principal.user.id)
    _record(
        db,
        request,
        principal,
        "transfer.receive",
        "transfer",
        t.id,
        {"status": "dispatched"},
        {"status": "received", "lines": [r.model_dump(mode="json") for r in body.lines]},
    )
    db.commit()
    db.refresh(t)
    return _transfer_out(db, t, principal)


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(
    transfer_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: StoreView
) -> TransferOut:
    t = _visible_transfer(db, transfer_id, scope, principal)
    if t.status != "draft":
        raise _conflict(f"{t.code} is {t.status}; only a draft can be cancelled")
    if not _transfer_out(db, t, principal).can_dispatch:
        raise _forbidden(f"cancel {t.code}")
    t.status = "cancelled"
    _record(
        db,
        request,
        principal,
        "transfer.cancel",
        "transfer",
        t.id,
        {"status": "draft"},
        {"status": "cancelled"},
    )
    db.commit()
    return _transfer_out(db, t, principal)


# --- site issues and returns ---------------------------------------------------------------------


def _issue_out(db: Session, i: SiteIssue) -> IssueOut:
    task = db.get(Task, i.task_id) if i.task_id else None
    return IssueOut(
        id=i.id,
        code=i.code,
        kind=i.kind,
        store_id=i.store_id,
        store_name=db.get(Store, i.store_id).name,
        site_id=i.site_id,
        task_id=i.task_id,
        task_name=task.name if task else None,
        area_scope_id=i.area_scope_id,
        issued_on=i.issued_on,
        remark=i.remark,
        created_at=i.created_at,
        lines=[
            IssueLineOut(
                product_id=ln.product_id,
                product_name=ln.product.name,
                unit=ln.product.unit,
                qty=ln.qty,
                rate=ln.rate,
                value=ln.value,
            )
            for ln in i.lines
        ],
    )


@router.get("/issues")
def list_issues(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: StoreView,
    limit: Limit = 50,
    offset: Offset = 0,
    site_id: int | None = None,
    store_id: int | None = None,
    kind: str | None = None,
) -> Page[IssueOut]:
    query = select(SiteIssue).where(
        svc.by_site(scope, principal, SiteIssue.site_id, SiteIssue.created_by)
    )
    if site_id is not None:
        query = query.where(SiteIssue.site_id == site_id)
    if store_id is not None:
        query = query.where(SiteIssue.store_id == store_id)
    if kind:
        query = query.where(SiteIssue.kind == kind)
    rows, total = paginate(db, query.order_by(SiteIssue.id.desc()), limit, offset)
    return Page(items=[_issue_out(db, i) for i in rows], total=total, limit=limit, offset=offset)


@router.post("/issues", status_code=status.HTTP_201_CREATED)
def create_issue(
    body: IssueIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("store.edit"))],
) -> IssueOut:
    """Issue: material used on the site (out of the store at its average rate). Return: unused
    material back into the store at that average."""
    site = db.get(Site, body.site_id)
    if site is None:
        raise unprocessable("Site not found")
    if not svc.covers_site(db, scope, principal, site.id, site.created_by):
        raise _forbidden(f"issue material on {site.code}")
    store = (
        _store_for_edit(db, body.store_id, "store.edit", principal, "issue material")
        if body.store_id
        else svc.site_store(db, site, principal.user.id)
    )
    if body.task_id:
        task = db.get(Task, body.task_id)
        if task is None or task.site_id != site.id:
            raise unprocessable("That task is not on this site")
    if body.area_scope_id:
        sc = db.get(AreaScope, body.area_scope_id)
        if sc is None or sc.site_id != site.id:
            raise unprocessable("That area scope is not on this site")
    # issued material is booked on an area of the site's list (or a new area asked for)
    from app.sitecontrol import service as sitecontrol  # noqa: PLC0415

    if body.kind == "issue":
        sitecontrol.check_booking(
            db, site, body.node_id, body.new_area_id, body.area_scope_id or body.task_id
        )
    issue = SiteIssue(
        code=svc.next_code(db, "ISS"),
        kind=body.kind,
        store_id=store.id,
        site_id=site.id,
        task_id=body.task_id,
        area_scope_id=body.area_scope_id,
        node_id=body.node_id,
        new_area_id=body.new_area_id,
        subcontractor_id=body.subcontractor_id,
        issued_on=body.issued_on or date.today(),
        remark=body.remark,
        created_by=principal.user.id,
    )
    if body.subcontractor_id:
        sub = db.get(Vendor, body.subcontractor_id)
        if sub is None or sub.type != "subcontractor":
            raise unprocessable("Pick a subcontractor (a vendor of type subcontractor)")
    db.add(issue)
    db.flush()
    for ln in body.lines:
        product = _product(db, ln.product_id)
        qty = svc.to_base(db, product, ln.qty, ln.unit or product.unit)
        if body.kind == "issue":
            rate = svc.take_out(
                db,
                store=store,
                product=product,
                qty=qty,
                ref_type="issue",
                ref_id=issue.id,
                user_id=principal.user.id,
                note=issue.code,
            )
        else:
            rate = svc.average_rate(db, store.id, product.id)
            svc.post(
                db,
                store_id=store.id,
                product=product,
                qty=qty,
                rate=rate,
                ref_type="return",
                ref_id=issue.id,
                user_id=principal.user.id,
                note=issue.code,
            )
        issue.lines.append(
            SiteIssueLine(
                product_id=product.id,
                product=product,
                qty=qty,
                rate=rate,
                value=svc.money(qty * rate),
            )
        )
    _record(
        db,
        request,
        principal,
        f"site.{body.kind}",
        "site_issue",
        issue.id,
        after=audit.model_snapshot(issue, "lines"),
    )
    db.commit()
    db.refresh(issue)
    return _issue_out(db, issue)


# --- freight -------------------------------------------------------------------------------------

FreightScope = Annotated[str, Depends(require_any_permission("po.view", "store.view"))]


def _freight_cond(scope: str, principal: Principal) -> ColumnElement[bool]:
    return svc.by_site(scope, principal, FreightEntry.site_id, FreightEntry.created_by)


def _freight_ref(db: Session, f: FreightEntry) -> str | None:
    if f.po_id:
        return db.scalar(select(PurchaseOrder.code).where(PurchaseOrder.id == f.po_id))
    if f.transfer_id:
        return db.scalar(select(Transfer.code).where(Transfer.id == f.transfer_id))
    return f.bill_no


@router.get("/freight")
def list_freight(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: FreightScope,
    limit: Limit = 100,
    offset: Offset = 0,
    site_id: int | None = None,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> Page[FreightOut]:
    query = select(FreightEntry).where(_freight_cond(scope, principal))
    if site_id is not None:
        query = query.where(FreightEntry.site_id == site_id)
    if month:
        y, m = (int(x) for x in month.split("-"))
        query = query.where(
            extract("year", FreightEntry.on_date) == y, extract("month", FreightEntry.on_date) == m
        )
    rows, total = paginate(
        db, query.order_by(FreightEntry.on_date.desc(), FreightEntry.id.desc()), limit, offset
    )
    codes = dict(db.execute(select(Site.id, Site.code)).all())
    return Page(
        items=[
            FreightOut(
                id=f.id,
                source=f.source,
                ref_code=_freight_ref(db, f),
                site_id=f.site_id,
                site_code=codes.get(f.site_id),
                direction=f.direction,
                on_date=f.on_date,
                amount=f.amount,
                gst_percent=f.gst_percent,
                transporter=f.transporter,
                vehicle_no=f.vehicle_no,
                bill_no=f.bill_no,
                remark=f.remark,
            )
            for f in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/freight", status_code=status.HTTP_201_CREATED)
def add_freight_bill(
    body: FreightBillIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_any_permission("po.edit", "store.edit"))],
) -> FreightOut:
    """A transporter's bill that is not on a PO or a transfer, charged to a site."""
    site = db.get(Site, body.site_id)
    if site is None:
        raise unprocessable("Site not found")
    scope = widest(principal.permissions.get("po.edit"), principal.permissions.get("store.edit"))
    if not svc.covers_site(db, scope, principal, site.id, site.created_by):
        raise _forbidden(f"charge freight to {site.code}")
    f = FreightEntry(source="bill", created_by=principal.user.id, **body.model_dump())
    db.add(f)
    db.flush()
    _record(
        db,
        request,
        principal,
        "freight.bill",
        "freight_entry",
        f.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return FreightOut(
        id=f.id,
        source=f.source,
        ref_code=f.bill_no,
        site_id=site.id,
        site_code=site.code,
        direction=f.direction,
        on_date=f.on_date,
        amount=f.amount,
        gst_percent=f.gst_percent,
        transporter=f.transporter,
        vehicle_no=f.vehicle_no,
        bill_no=f.bill_no,
        remark=f.remark,
    )


@router.get("/freight/report")
def freight_report(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: FreightScope,
    site_id: int | None = None,
    year: int | None = None,
) -> list[FreightReportRow]:
    """Freight per site and month: inbound (on POs and bills), godown to site, other."""
    month = func.to_char(FreightEntry.on_date, "YYYY-MM")
    query = (
        select(FreightEntry.site_id, month, FreightEntry.direction, func.sum(FreightEntry.amount))
        .where(_freight_cond(scope, principal))
        .group_by(FreightEntry.site_id, month, FreightEntry.direction)
    )
    if site_id is not None:
        query = query.where(FreightEntry.site_id == site_id)
    if year is not None:
        query = query.where(extract("year", FreightEntry.on_date) == year)
    sites = {i: (c, n) for i, c, n in db.execute(select(Site.id, Site.code, Site.name))}
    rows: dict[tuple, dict] = {}
    for sid, mon, direction, amount in db.execute(query):
        row = rows.setdefault((sid, mon), {"inbound": ZERO, "godown_to_site": ZERO, "other": ZERO})
        row[direction] += Decimal(amount)
    out = []
    for (sid, mon), r in sorted(
        rows.items(), key=lambda kv: (sites.get(kv[0][0], ("~",))[0], kv[0][1])
    ):
        code, name = sites.get(sid, (None, None))
        out.append(
            FreightReportRow(
                site_id=sid,
                site_code=code,
                site_name=name,
                month=mon,
                total=sum(r.values(), ZERO),
                **r,
            )
        )
    return out


# --- a site's material ---------------------------------------------------------------------------


@router.get("/sites/{site_id}/summary")
def site_summary(site_id: int, db: DbSession, principal: CurrentPrincipal, _: AnyMaterial) -> dict:
    """The site's store and stock, its open indents and the freight charged to it."""
    perms = principal.permissions
    site = db.get(Site, site_id)
    scope = None
    for code in ("indent.view", "store.view", "po.view", "grn.view"):
        scope = widest(scope, perms.get(code))
    if site is None or not svc.covers_site(db, scope, principal, site.id, site.created_by):
        raise _not_found("Site")
    store = db.scalar(select(Store).where(Store.site_id == site.id))
    stock = _stock_rows(db, store.id) if store and perms.get("store.view") else []
    freight = db.execute(
        select(FreightEntry.direction, func.sum(FreightEntry.amount))
        .where(FreightEntry.site_id == site.id)
        .group_by(FreightEntry.direction)
    ).all()
    issued = db.scalar(
        select(func.coalesce(func.sum(SiteIssueLine.value), 0))
        .join(SiteIssue, SiteIssue.id == SiteIssueLine.issue_id)
        .where(SiteIssue.site_id == site.id, SiteIssue.kind == "issue")
    )
    returned = db.scalar(
        select(func.coalesce(func.sum(SiteIssueLine.value), 0))
        .join(SiteIssue, SiteIssue.id == SiteIssueLine.issue_id)
        .where(SiteIssue.site_id == site.id, SiteIssue.kind == "return")
    )
    by_dir = {d: Decimal(a) for d, a in freight}
    return {
        "store": _store_out(db, store).model_dump(mode="json") if store else None,
        "stock": [r.model_dump(mode="json") for r in stock],
        "freight": {
            "inbound": str(by_dir.get("inbound", ZERO)),
            "godown_to_site": str(by_dir.get("godown_to_site", ZERO)),
            "other": str(by_dir.get("other", ZERO)),
            "total": str(sum(by_dir.values(), ZERO)),
        },
        "issued_value": str(Decimal(issued)),
        "returned_value": str(Decimal(returned)),
        "permissions": {
            k: v for k, v in perms.items() if k.split(".")[0] in ("indent", "po", "grn", "store")
        },
    }
