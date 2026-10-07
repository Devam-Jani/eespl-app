"""Settings: categories, tags, units and conversions, company profile, GSTIN addresses and
company bank accounts.

Who can do what
- categories, tags, units, conversions: anyone signed in can read (they fill dropdowns);
  library.edit changes them.
- company profile, GSTIN addresses: settings.company reads and changes them.
- company bank accounts: settings.company or finance.view reads them, settings.company changes.
"""

from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.config import settings
from app.db import DbSession
from app.export import xlsx_response
from app.masters.conversions import ConversionError, convert
from app.masters.models import (
    Category,
    CompanyBankAccount,
    CompanyGstin,
    CompanyProfile,
    Product,
    Tag,
    Unit,
    UnitConversion,
)
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
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    CompanyBankIn,
    CompanyBankOut,
    CompanyBankUpdate,
    CompanyProfileIn,
    CompanyProfileOut,
    ConversionIn,
    ConversionOut,
    ConversionUpdate,
    ConvertOut,
    GstinIn,
    GstinOut,
    GstinUpdate,
    Page,
    TagIn,
    TagOut,
    TagUpdate,
    UnitOut,
    UnitUpdate,
)
from app.masters.units import build_alias_map

router = APIRouter(tags=["settings"])

edit_library = [Depends(require_permission("library.edit"))]
company = [Depends(require_permission("settings.company"))]
company_bank_read = [Depends(require_any_permission("settings.company", "finance.view"))]

LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
LOGO_SIGNATURES = {".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".webp": b"RIFF"}
LOGO_MAX_BYTES = 2 * 1024 * 1024


def _record(db, request, principal, action, entity, entity_id, before=None, after=None):
    audit.record(db, action, entity, entity_id, user_id=principal.user.id, before=before,
                 after=after, ip=audit.client_ip(request))  # fmt: skip


# --- categories -------------------------------------------------------------------------------


def _category_query(kind: str | None, q: str | None, active: bool | None):
    query = select(Category)
    if kind:
        query = query.where(Category.kind == kind)
    if q:
        query = query.where(Category.name.ilike(like(q)))
    if active is not None:
        query = query.where(Category.is_active == active)
    return query.order_by(Category.kind, Category.sort_order, Category.name)


def _category_out(db: Session, categories: list[Category]) -> list[CategoryOut]:
    ids = [c.id for c in categories]
    counts = dict(
        db.execute(
            select(Product.category_id, func.count())
            .where(Product.category_id.in_(ids))
            .group_by(Product.category_id)
        ).all()
    ) if ids else {}  # fmt: skip
    out = []
    for c in categories:
        item = CategoryOut.model_validate(c)
        item.product_count = counts.get(c.id, 0)
        out.append(item)
    return out


def _check_parent(db: Session, parent_id: int | None, kind: str, self_id: int | None = None):
    if parent_id is None:
        return
    parent = db.get(Category, parent_id)
    if parent is None or parent.kind != kind or parent.id == self_id:
        raise unprocessable("Parent must be another category of the same kind")


@router.get("/api/categories")
def list_categories(
    db: DbSession,
    _: CurrentPrincipal,
    kind: str | None = None,
    q: Search = None,
    active: bool | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> Page[CategoryOut]:
    rows, total = paginate(db, _category_query(kind, q, active), limit, offset)
    return Page(items=_category_out(db, rows), total=total, limit=limit, offset=offset)


@router.get("/api/categories/export")
def export_categories(
    db: DbSession, _: CurrentPrincipal, kind: str | None = None, q: Search = None,
    active: bool | None = None,
):  # fmt: skip
    rows = _category_out(db, list(db.scalars(_category_query(kind, q, active))))
    names = {c.id: c.name for c in rows}
    return xlsx_response(
        "categories",
        ["Kind", "Name", "Parent", "Order", "Products", "Active"],
        [[c.kind, c.name, names.get(c.parent_id), c.sort_order, c.product_count, c.is_active]
         for c in rows],
    )  # fmt: skip


@router.post("/api/categories", status_code=status.HTTP_201_CREATED, dependencies=edit_library)
def create_category(
    body: CategoryIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> CategoryOut:
    _check_parent(db, body.parent_id, body.kind)
    category = Category(**body.model_dump(), created_by=principal.user.id)
    category.name = category.name.strip()
    db.add(category)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("A category with this name already exists") from exc
    _record(db, request, principal, "category.create", "category", category.id,
            after=audit.model_snapshot(category))  # fmt: skip
    db.commit()
    return _category_out(db, [category])[0]


@router.patch("/api/categories/{category_id}", dependencies=edit_library)
def update_category(
    category_id: int,
    body: CategoryUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> CategoryOut:
    category = get_or_404(db, Category, category_id, "Category")
    before = audit.model_snapshot(category)
    changes = body.model_dump(exclude_unset=True)
    if "parent_id" in changes:
        _check_parent(db, changes["parent_id"], category.kind, category.id)
    for field, value in changes.items():
        if value is not None or field == "parent_id":
            setattr(category, field, value.strip() if field == "name" else value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("A category with this name already exists") from exc
    after = audit.model_snapshot(category)
    if after != before:
        _record(db, request, principal, "category.update", "category", category.id, before, after)
    db.commit()
    return _category_out(db, [category])[0]


@router.delete(
    "/api/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=edit_library,
)
def delete_category(
    category_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    category = get_or_404(db, Category, category_id, "Category")
    used = db.scalar(select(func.count()).where(Product.category_id == category.id))
    if used:
        raise conflict(f"{used} products use this category; deactivate it instead")
    _record(db, request, principal, "category.delete", "category", category.id,
            before=audit.model_snapshot(category))  # fmt: skip
    db.delete(category)
    db.commit()


# --- tags ---------------------------------------------------------------------------------------


def _tag_query(module: str | None, q: str | None, archived: bool | None):
    query = select(Tag)
    if module:
        query = query.where(Tag.module == module)
    if q:
        query = query.where(Tag.name.ilike(like(q)))
    if archived is not None:
        query = query.where(Tag.is_archived == archived)
    return query.order_by(Tag.module, Tag.name)


@router.get("/api/tags")
def list_tags(
    db: DbSession,
    _: CurrentPrincipal,
    module: str | None = None,
    q: Search = None,
    archived: bool | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> Page[TagOut]:
    rows, total = paginate(db, _tag_query(module, q, archived), limit, offset)
    return Page(
        items=[TagOut.model_validate(t) for t in rows], total=total, limit=limit, offset=offset
    )


@router.get("/api/tags/export")
def export_tags(
    db: DbSession, _: CurrentPrincipal, module: str | None = None, q: Search = None,
    archived: bool | None = None,
):  # fmt: skip
    return xlsx_response(
        "tags",
        ["Module", "Name", "Archived"],
        [[t.module, t.name, t.is_archived] for t in db.scalars(_tag_query(module, q, archived))],
    )


@router.post("/api/tags", status_code=status.HTTP_201_CREATED, dependencies=edit_library)
def create_tag(body: TagIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> TagOut:
    tag = Tag(**body.model_dump(), created_by=principal.user.id)
    tag.name = tag.name.strip()
    db.add(tag)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("This tag already exists in that module") from exc
    _record(db, request, principal, "tag.create", "tag", tag.id, after=audit.model_snapshot(tag))
    db.commit()
    return TagOut.model_validate(tag)


@router.patch("/api/tags/{tag_id}", dependencies=edit_library)
def update_tag(
    tag_id: int, body: TagUpdate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> TagOut:
    tag = get_or_404(db, Tag, tag_id, "Tag")
    before = audit.model_snapshot(tag)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(tag, field, value.strip() if field == "name" else value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("This tag already exists in that module") from exc
    after = audit.model_snapshot(tag)
    if after != before:
        _record(db, request, principal, "tag.update", "tag", tag.id, before, after)
    db.commit()
    return TagOut.model_validate(tag)


@router.delete(
    "/api/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit_library
)
def delete_tag(tag_id: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> None:
    tag = get_or_404(db, Tag, tag_id, "Tag")
    _record(db, request, principal, "tag.delete", "tag", tag.id, before=audit.model_snapshot(tag))
    db.delete(tag)
    db.commit()


# --- units and conversions -------------------------------------------------------------------


@router.patch("/api/units/{code}", dependencies=edit_library)
def update_unit(
    code: str, body: UnitUpdate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> UnitOut:
    unit = get_or_404(db, Unit, code, "Unit")
    before = audit.model_snapshot(unit)
    if body.name is not None:
        unit.name = body.name.strip()
    if body.aliases is not None:
        aliases = sorted({a.strip() for a in body.aliases if a.strip()})
        # an alias may point at only one unit
        others = build_alias_map(
            db.execute(select(Unit.code, Unit.aliases).where(Unit.code != unit.code)).tuples()
        )
        taken = sorted(a for a in aliases if build_alias_map([("x", [a])]).keys() & others.keys())
        if taken:
            raise conflict(f"Already an alias of another unit: {', '.join(taken)}")
        unit.aliases = aliases
    db.flush()
    after = audit.model_snapshot(unit)
    if after != before:
        _record(db, request, principal, "unit.update", "unit", unit.code, before, after)
    db.commit()
    return UnitOut.model_validate(unit)


def _conversion_out(c: UnitConversion) -> ConversionOut:
    return ConversionOut(
        id=c.id,
        from_unit=c.from_unit,
        to_unit=c.to_unit,
        factor=c.factor,
        product_id=c.product_id,
        product_name=c.product.name if c.product else None,
    )


def _conversion_query(product_id: int | None):
    query = select(UnitConversion)
    if product_id is not None:
        query = query.where(UnitConversion.product_id == product_id)
    return query.order_by(
        UnitConversion.product_id.nulls_first(), UnitConversion.from_unit, UnitConversion.to_unit
    )


@router.get("/api/unit-conversions")
def list_conversions(
    db: DbSession,
    _: CurrentPrincipal,
    product_id: int | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> Page[ConversionOut]:
    rows, total = paginate(db, _conversion_query(product_id), limit, offset)
    return Page(items=[_conversion_out(c) for c in rows], total=total, limit=limit, offset=offset)


@router.get("/api/unit-conversions/export")
def export_conversions(db: DbSession, _: CurrentPrincipal, product_id: int | None = None):
    rows = [_conversion_out(c) for c in db.scalars(_conversion_query(product_id))]
    return xlsx_response(
        "unit-conversions",
        ["From", "To", "Factor (1 from = factor × to)", "Product"],
        [[c.from_unit, c.to_unit, c.factor, c.product_name or "All products"] for c in rows],
    )


@router.get("/api/units/convert")
def convert_quantity(
    db: DbSession,
    _: CurrentPrincipal,
    qty: Annotated[Decimal, Query()],
    from_unit: str,
    to_unit: str,
    product_id: int | None = None,
) -> ConvertOut:
    try:
        result = convert(db, qty, from_unit, to_unit, product_id)
    except ConversionError as exc:
        raise unprocessable(str(exc)) from exc
    return ConvertOut(qty=qty, from_unit=from_unit, to_unit=to_unit, product_id=product_id,
                      result=result)  # fmt: skip


@router.post(
    "/api/unit-conversions", status_code=status.HTTP_201_CREATED, dependencies=edit_library
)
def create_conversion(
    body: ConversionIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ConversionOut:
    for code in (body.from_unit, body.to_unit):
        if db.get(Unit, code) is None:
            raise unprocessable(f"Unknown unit: {code}")
    if body.from_unit == body.to_unit:
        raise unprocessable("Choose two different units")
    if body.product_id is not None and db.get(Product, body.product_id) is None:
        raise unprocessable(f"Unknown product id: {body.product_id}")
    conversion = UnitConversion(**body.model_dump(), created_by=principal.user.id)
    db.add(conversion)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("This conversion already exists") from exc
    _record(db, request, principal, "unit_conversion.create", "unit_conversion", conversion.id,
            after=audit.model_snapshot(conversion))  # fmt: skip
    db.commit()
    db.refresh(conversion)
    return _conversion_out(conversion)


@router.patch("/api/unit-conversions/{conversion_id}", dependencies=edit_library)
def update_conversion(
    conversion_id: int,
    body: ConversionUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ConversionOut:
    conversion = get_or_404(db, UnitConversion, conversion_id, "Conversion")
    before = audit.model_snapshot(conversion)
    conversion.factor = body.factor
    db.flush()
    _record(db, request, principal, "unit_conversion.update", "unit_conversion", conversion.id,
            before, audit.model_snapshot(conversion))  # fmt: skip
    db.commit()
    db.refresh(conversion)
    return _conversion_out(conversion)


@router.delete(
    "/api/unit-conversions/{conversion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=edit_library,
)
def delete_conversion(
    conversion_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    conversion = get_or_404(db, UnitConversion, conversion_id, "Conversion")
    _record(db, request, principal, "unit_conversion.delete", "unit_conversion", conversion.id,
            before=audit.model_snapshot(conversion))  # fmt: skip
    db.delete(conversion)
    db.commit()


# --- company profile ----------------------------------------------------------------------------


def _profile(db: Session) -> CompanyProfile:
    profile = db.get(CompanyProfile, 1)
    if profile is None:  # the migration creates it; recreate if someone removed it
        profile = CompanyProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


def _profile_out(profile: CompanyProfile) -> CompanyProfileOut:
    out = CompanyProfileOut.model_validate(profile)
    out.has_logo = (
        bool(profile.logo_path) and (Path(settings.media_dir) / profile.logo_path).exists()
    )
    return out


@router.get("/api/settings/company", dependencies=company)
def get_company(db: DbSession) -> CompanyProfileOut:
    profile = _profile(db)
    db.commit()
    return _profile_out(profile)


@router.patch("/api/settings/company", dependencies=company)
def update_company(
    body: CompanyProfileIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> CompanyProfileOut:
    profile = _profile(db)
    before = audit.model_snapshot(profile)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("default_gst_percent", "pricing_threshold", "rate_policy") and value is None:
            continue
        setattr(profile, field, value)
    db.flush()
    after = audit.model_snapshot(profile)
    if after != before:
        _record(db, request, principal, "company.update", "company", 1, before, after)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.post("/api/settings/company/logo", dependencies=company)
async def upload_logo(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, up to 2 MB")],
) -> CompanyProfileOut:
    extension = LOGO_TYPES.get(file.content_type or "")
    if extension is None:
        raise unprocessable("The logo must be a PNG, JPEG or WebP image")
    data = await file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise unprocessable("The logo must be 2 MB or smaller")
    if not data.startswith(LOGO_SIGNATURES[extension]):
        raise unprocessable("The file content is not a valid image of that type")
    folder = Path(settings.media_dir) / "company"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("logo.*"):
        old.unlink()
    (folder / f"logo{extension}").write_bytes(data)
    profile = _profile(db)
    before = {"logo_path": profile.logo_path}
    profile.logo_path = f"company/logo{extension}"
    _record(db, request, principal, "company.logo.upload", "company", 1, before,
            {"logo_path": profile.logo_path, "bytes": len(data)})  # fmt: skip
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.get("/api/settings/company/logo")
def get_logo(db: DbSession, _: CurrentPrincipal) -> FileResponse:
    """Any signed-in user may fetch the logo (it goes on documents)."""
    profile = db.get(CompanyProfile, 1)
    path = Path(settings.media_dir) / profile.logo_path if profile and profile.logo_path else None
    if path is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo uploaded")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.delete(
    "/api/settings/company/logo", status_code=status.HTTP_204_NO_CONTENT, dependencies=company
)
def delete_logo(request: Request, db: DbSession, principal: CurrentPrincipal) -> None:
    profile = _profile(db)
    if profile.logo_path:
        (Path(settings.media_dir) / profile.logo_path).unlink(missing_ok=True)
        _record(db, request, principal, "company.logo.delete", "company", 1,
                {"logo_path": profile.logo_path}, {"logo_path": None})  # fmt: skip
        profile.logo_path = None
    db.commit()


# --- GSTIN addresses ----------------------------------------------------------------------------


def _clear_default(db: Session, model, keep: int | None = None) -> None:
    query = update(model).where(model.is_default)
    if keep is not None:
        query = query.where(model.id != keep)
    db.execute(query.values(is_default=False))
    db.flush()


@router.get("/api/settings/gstins", dependencies=company)
def list_gstins(db: DbSession) -> list[GstinOut]:
    rows = db.scalars(
        select(CompanyGstin).order_by(CompanyGstin.is_default.desc(), CompanyGstin.state)
    )
    return [GstinOut.model_validate(g) for g in rows]


@router.get("/api/settings/gstins/export", dependencies=company)
def export_gstins(db: DbSession):
    rows = db.scalars(
        select(CompanyGstin).order_by(CompanyGstin.is_default.desc(), CompanyGstin.state)
    )
    return xlsx_response(
        "gstin-addresses",
        ["GSTIN", "State", "Address", "Default"],
        [[g.gstin, g.state, g.address, g.is_default] for g in rows],
    )


@router.post("/api/settings/gstins", status_code=status.HTTP_201_CREATED, dependencies=company)
def create_gstin(
    body: GstinIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> GstinOut:
    first = not db.scalar(select(func.count()).select_from(CompanyGstin))
    if body.is_default:
        _clear_default(db, CompanyGstin)
    gstin = CompanyGstin(
        **body.model_dump(exclude={"is_default"}),
        is_default=body.is_default or first,
        created_by=principal.user.id,
    )
    db.add(gstin)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("This GSTIN is already in the address directory") from exc
    _record(db, request, principal, "company.gstin.create", "company_gstin", gstin.id,
            after=audit.model_snapshot(gstin))  # fmt: skip
    db.commit()
    return GstinOut.model_validate(gstin)


@router.patch("/api/settings/gstins/{gstin_id}", dependencies=company)
def update_gstin(
    gstin_id: int, body: GstinUpdate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> GstinOut:
    gstin = get_or_404(db, CompanyGstin, gstin_id, "GSTIN")
    before = audit.model_snapshot(gstin)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if changes.get("is_default"):
        _clear_default(db, CompanyGstin, keep=gstin.id)
    for field, value in changes.items():
        setattr(gstin, field, value)
    db.flush()
    after = audit.model_snapshot(gstin)
    if after != before:
        _record(db, request, principal, "company.gstin.update", "company_gstin", gstin.id,
                before, after)  # fmt: skip
    db.commit()
    return GstinOut.model_validate(gstin)


@router.delete(
    "/api/settings/gstins/{gstin_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=company
)
def delete_gstin(gstin_id: int, request: Request, db: DbSession, principal: CurrentPrincipal):
    gstin = get_or_404(db, CompanyGstin, gstin_id, "GSTIN")
    _record(db, request, principal, "company.gstin.delete", "company_gstin", gstin.id,
            before=audit.model_snapshot(gstin))  # fmt: skip
    db.delete(gstin)
    db.commit()


# --- company bank accounts ----------------------------------------------------------------------


def _bank_snapshot(account: CompanyBankAccount) -> dict:
    data = audit.model_snapshot(account)
    data["account_number"] = f"…{account.account_number[-4:]}"  # never the full number in audit
    return data


@router.get("/api/settings/bank-accounts", dependencies=company_bank_read)
def list_company_banks(db: DbSession) -> list[CompanyBankOut]:
    rows = db.scalars(
        select(CompanyBankAccount).order_by(
            CompanyBankAccount.is_default.desc(), CompanyBankAccount.account_name
        )
    )
    return [CompanyBankOut.model_validate(b) for b in rows]


@router.get("/api/settings/bank-accounts/export", dependencies=company_bank_read)
def export_company_banks(db: DbSession):
    rows = db.scalars(select(CompanyBankAccount).order_by(CompanyBankAccount.account_name))
    return xlsx_response(
        "bank-accounts",
        ["Account name", "Account number", "IFSC", "Bank", "Branch", "Default"],
        [[b.account_name, b.account_number, b.ifsc, b.bank, b.branch, b.is_default] for b in rows],
    )


@router.post(
    "/api/settings/bank-accounts", status_code=status.HTTP_201_CREATED, dependencies=company
)
def create_company_bank(
    body: CompanyBankIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> CompanyBankOut:
    first = not db.scalar(select(func.count()).select_from(CompanyBankAccount))
    if body.is_default:
        _clear_default(db, CompanyBankAccount)
    account = CompanyBankAccount(**body.model_dump(exclude={"is_default"}),
                                 is_default=body.is_default or first,
                                 created_by=principal.user.id)  # fmt: skip
    db.add(account)
    db.flush()
    _record(db, request, principal, "company.bank_account.create", "company_bank_account",
            account.id, after=_bank_snapshot(account))  # fmt: skip
    db.commit()
    return CompanyBankOut.model_validate(account)


@router.patch("/api/settings/bank-accounts/{account_id}", dependencies=company)
def update_company_bank(
    account_id: int,
    body: CompanyBankUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> CompanyBankOut:
    account = get_or_404(db, CompanyBankAccount, account_id, "Bank account")
    before = _bank_snapshot(account)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_default"):
        _clear_default(db, CompanyBankAccount, keep=account.id)
    for field, value in changes.items():
        if value is not None or field in ("bank", "branch"):
            setattr(account, field, value)
    db.flush()
    after = _bank_snapshot(account)
    if after != before:
        _record(db, request, principal, "company.bank_account.update", "company_bank_account",
                account.id, before, after)  # fmt: skip
    db.commit()
    return CompanyBankOut.model_validate(account)


@router.delete(
    "/api/settings/bank-accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=company,
)
def delete_company_bank(
    account_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    account = get_or_404(db, CompanyBankAccount, account_id, "Bank account")
    _record(db, request, principal, "company.bank_account.delete", "company_bank_account",
            account.id, before=_bank_snapshot(account))  # fmt: skip
    db.delete(account)
    db.commit()
