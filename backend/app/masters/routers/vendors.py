"""Vendors with contacts, bank accounts and the products they supply.

Bank account numbers and IFSC codes are finance data: they are returned only to callers with
settings.company or finance.view (others get them as None with masked=True), and only such
callers, who also have vendors.edit, can add or change them.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select, update

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Product, Vendor, VendorBankAccount, VendorContact, VendorProduct
from app.masters.routers.common import (
    Limit,
    Offset,
    Search,
    get_or_404,
    like,
    paginate,
    unprocessable,
)
from app.masters.schemas import (
    BankAccountIn,
    BankAccountOut,
    ContactIn,
    ContactOut,
    Page,
    VendorIn,
    VendorOut,
    VendorProductIn,
    VendorProductOut,
    VendorUpdate,
)

router = APIRouter(prefix="/api/vendors", tags=["vendors"])

view = [Depends(require_permission("vendors.view"))]
edit = [Depends(require_permission("vendors.edit"))]
BANK_PERMISSIONS = ("settings.company", "finance.view")


def can_see_bank(principal: Principal) -> bool:
    return any(code in principal.permissions for code in BANK_PERMISSIONS)


def require_bank_access(principal: CurrentPrincipal) -> None:
    if not can_see_bank(principal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Missing permission: one of settings.company, finance.view (bank details)",
        )


BankAccess = Annotated[None, Depends(require_bank_access)]


def _bank_out(account: VendorBankAccount, visible: bool) -> BankAccountOut:
    return BankAccountOut(
        id=account.id,
        account_name=account.account_name,
        bank=account.bank,
        branch=account.branch,
        is_primary=account.is_primary,
        account_number=account.account_number if visible else None,
        ifsc=account.ifsc if visible else None,
        masked=not visible,
    )


def _product_out(vp: VendorProduct) -> VendorProductOut:
    return VendorProductOut(
        id=vp.id,
        product_id=vp.product_id,
        product_code=vp.product.code,
        product_name=vp.product.name,
        unit=vp.product.unit,
        last_rate=vp.last_rate,
        lead_time_days=vp.lead_time_days,
    )


def _out(vendor: Vendor, principal: Principal) -> VendorOut:
    visible = can_see_bank(principal)
    return VendorOut(
        **{c: getattr(vendor, c) for c in VendorOut.model_fields if c not in
           ("contacts", "bank_accounts", "products")},
        contacts=[ContactOut.model_validate(c) for c in vendor.contacts],
        bank_accounts=[_bank_out(b, visible) for b in vendor.bank_accounts],
        products=[_product_out(p) for p in vendor.products],
    )  # fmt: skip


def _snapshot(vendor: Vendor) -> dict:
    data = audit.model_snapshot(vendor, "contacts")
    data["bank_accounts"] = [
        {"account_name": b.account_name, "bank": b.bank, "is_primary": b.is_primary,
         "account_number_last4": b.account_number[-4:]}
        for b in vendor.bank_accounts
    ]  # fmt: skip
    data["products"] = [
        {"product_id": p.product_id, "last_rate": p.last_rate, "lead_time_days": p.lead_time_days}
        for p in vendor.products
    ]
    return data


def _contacts(items: list[ContactIn], principal: Principal) -> list[VendorContact]:
    return [VendorContact(**c.model_dump(), created_by=principal.user.id) for c in items]


def _query(q: str | None, type_: str | None, active: bool | None):
    query = select(Vendor)
    if q:
        pattern = like(q)
        query = query.where(
            or_(Vendor.name.ilike(pattern), Vendor.city.ilike(pattern), Vendor.gstin.ilike(pattern))
        )
    if type_:
        query = query.where(Vendor.type == type_)
    if active is not None:
        query = query.where(Vendor.is_active == active)
    return query.order_by(Vendor.name, Vendor.id)


def _record(db, request, principal, action, vendor, before=None, after=None):
    audit.record(db, action, "vendor", vendor.id, user_id=principal.user.id, before=before,
                 after=after, ip=audit.client_ip(request))  # fmt: skip


@router.get("", dependencies=view)
def list_vendors(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Search = None,
    type: str | None = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[VendorOut]:
    rows, total = paginate(db, _query(q, type, active), limit, offset)
    return Page(items=[_out(v, principal) for v in rows], total=total, limit=limit, offset=offset)


@router.get("/export", dependencies=view)
def export_vendors(
    db: DbSession,
    principal: CurrentPrincipal,
    q: Search = None,
    type: str | None = None,
    active: bool | None = None,
):
    visible = can_see_bank(principal)
    columns = ["Name", "Type", "GSTIN", "PAN", "City", "State", "Payment terms (days)",
               "Primary contact", "Phone", "Email", "Products supplied", "Active"]  # fmt: skip
    if visible:
        columns += ["Bank account name", "Account number", "IFSC", "Bank"]
    rows = []
    for v in db.scalars(_query(q, type, active).limit(EXPORT_ROW_LIMIT)):
        contact = next(
            (c for c in v.contacts if c.is_primary), v.contacts[0] if v.contacts else None
        )
        row = [v.name, v.type, v.gstin, v.pan, v.city, v.state, v.payment_terms_days,
               contact.name if contact else None, contact.phone if contact else None,
               contact.email if contact else None, len(v.products), v.is_active]  # fmt: skip
        if visible:
            bank = next((b for b in v.bank_accounts if b.is_primary),
                        v.bank_accounts[0] if v.bank_accounts else None)  # fmt: skip
            row += [bank.account_name, bank.account_number, bank.ifsc, bank.bank] if bank \
                else [None] * 4  # fmt: skip
        rows.append(row)
    return xlsx_response("vendors", columns, rows)


@router.get("/{vendor_id}", dependencies=view)
def get_vendor(vendor_id: int, db: DbSession, principal: CurrentPrincipal) -> VendorOut:
    return _out(get_or_404(db, Vendor, vendor_id, "Vendor"), principal)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_vendor(
    body: VendorIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> VendorOut:
    vendor = Vendor(
        **body.model_dump(exclude={"contacts"}),
        created_by=principal.user.id,
        contacts=_contacts(body.contacts, principal),
    )
    db.add(vendor)
    db.flush()
    _record(db, request, principal, "vendor.create", vendor, after=_snapshot(vendor))
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)


@router.patch("/{vendor_id}", dependencies=edit)
def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> VendorOut:
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    before = _snapshot(vendor)
    for field, value in body.model_dump(exclude_unset=True, exclude={"contacts"}).items():
        if field in ("name", "type", "is_active") and value is None:
            continue
        setattr(vendor, field, value)
    if body.contacts is not None:
        vendor.contacts = _contacts(body.contacts, principal)
    db.flush()
    after = _snapshot(vendor)
    if after != before:
        _record(db, request, principal, "vendor.update", vendor, before, after)
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit)
def delete_vendor(
    vendor_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    _record(db, request, principal, "vendor.delete", vendor, before=_snapshot(vendor))
    db.delete(vendor)
    db.commit()


# --- bank accounts ---


def _clear_primary(db, vendor_id: int, keep: int | None = None) -> None:
    query = update(VendorBankAccount).where(VendorBankAccount.vendor_id == vendor_id)
    if keep is not None:
        query = query.where(VendorBankAccount.id != keep)
    db.execute(query.values(is_primary=False))


@router.post("/{vendor_id}/bank-accounts", status_code=status.HTTP_201_CREATED, dependencies=edit)
def add_bank_account(
    vendor_id: int,
    body: BankAccountIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: BankAccess,
) -> VendorOut:
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    before = _snapshot(vendor)
    first = not vendor.bank_accounts
    if body.is_primary:
        _clear_primary(db, vendor.id)
    vendor.bank_accounts.append(
        VendorBankAccount(**body.model_dump(exclude={"is_primary"}),
                          is_primary=body.is_primary or first, created_by=principal.user.id)
    )  # fmt: skip
    db.flush()
    _record(db, request, principal, "vendor.bank_account.create", vendor, before, _snapshot(vendor))
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)


@router.put("/{vendor_id}/bank-accounts/{account_id}", dependencies=edit)
def replace_bank_account(
    vendor_id: int,
    account_id: int,
    body: BankAccountIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: BankAccess,
) -> VendorOut:
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    account = db.get(VendorBankAccount, account_id)
    if account is None or account.vendor_id != vendor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank account not found")
    before = _snapshot(vendor)
    if body.is_primary:
        _clear_primary(db, vendor.id, keep=account.id)
    for field, value in body.model_dump().items():
        setattr(account, field, value)
    db.flush()
    _record(db, request, principal, "vendor.bank_account.update", vendor, before, _snapshot(vendor))
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)


@router.delete("/{vendor_id}/bank-accounts/{account_id}", dependencies=edit)
def delete_bank_account(
    vendor_id: int,
    account_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: BankAccess,
) -> VendorOut:
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    account = db.get(VendorBankAccount, account_id)
    if account is None or account.vendor_id != vendor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank account not found")
    before = _snapshot(vendor)
    vendor.bank_accounts.remove(account)
    db.flush()
    _record(db, request, principal, "vendor.bank_account.delete", vendor, before, _snapshot(vendor))
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)


# --- products supplied ---


@router.put("/{vendor_id}/products", dependencies=edit)
def set_products(
    vendor_id: int,
    body: list[VendorProductIn],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> VendorOut:
    """Replace the list of products this vendor supplies."""
    vendor = get_or_404(db, Vendor, vendor_id, "Vendor")
    ids = [p.product_id for p in body]
    if len(set(ids)) != len(ids):
        raise unprocessable("A product can appear only once")
    found = set(db.scalars(select(Product.id).where(Product.id.in_(ids)))) if ids else set()
    if found != set(ids):
        raise unprocessable(f"Unknown product ids: {sorted(set(ids) - found)}")
    before = _snapshot(vendor)
    vendor.products = []
    db.flush()
    vendor.products = [VendorProduct(**p.model_dump(), created_by=principal.user.id) for p in body]
    db.flush()
    _record(db, request, principal, "vendor.products.update", vendor, before, _snapshot(vendor))
    db.commit()
    db.refresh(vendor)
    return _out(vendor, principal)
