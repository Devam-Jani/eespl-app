# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Site control endpoints.

/api/receipt/{token}: the delivery receipt page's API, with NO login. It answers for one delivery
(found by the hash of the token), shows its items and quantities only, takes the count once.
Rate-limited per address.

/api/sitecontrol/...: deliveries (delivery.view / delivery.confirm, scope all or assigned:
the caller's sites), bill release (delivery.escalate), rate contracts (ratecontract.view /
.edit), ready to bill (billing), new areas (site.update to ask, sitearea.approve to decide),
labour check override (labourcheck.override), reports.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import media, record, save_upload, send_file
from app.finance.models import ClientContract, SubconBill, VendorBill
from app.masters.models import Product, Vendor
from app.material import service as material
from app.material.models import PurchaseOrder
from app.models import User
from app.sitecontrol import deliveries as dlv
from app.sitecontrol import pdf as dn_pdf
from app.sitecontrol import ratelimit
from app.sitecontrol import service as sc
from app.sitecontrol.models import (
    DebitNote,
    DeliveryNote,
    Discrepancy,
    NewAreaRequest,
    ProductivityNorm,
    RateContract,
    RateContractVersion,
    ReadyToBill,
)
from app.sites.models import Site, SiteNode
from app.timefmt import label

public = APIRouter(prefix="/api/receipt", tags=["receipt"])
router = APIRouter(prefix="/api/sitecontrol", tags=["sitecontrol"])

DeliveryView = Annotated[str, Depends(require_permission("delivery.view"))]
RcView = Annotated[str, Depends(require_permission("ratecontract.view"))]
RcEdit = Annotated[str, Depends(require_permission("ratecontract.edit"))]


def _book(name: str, sheets: list[tuple[str, list[str], list[list]]]):
    """An Excel workbook, one sheet per (title, headers, rows)."""
    from fastapi.responses import Response  # noqa: PLC0415

    from app.analytics.reports import xlsx_book  # noqa: PLC0415

    book = xlsx_book(
        [
            (
                title,
                [{"key": str(i), "label": h} for i, h in enumerate(heads)],
                [{str(i): v for i, v in enumerate(r)} for r in rows],
            )
            for title, heads, rows in sheets
        ]
    )
    return Response(
        book,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{name}-{date.today():%Y%m%d}.xlsx"'
        },
    )


def _sites_for(scope: str, principal) -> list[int] | None:
    """None: every site; else the caller's sites."""
    return None if scope == "all" else list(material.assigned_sites(principal))


def _dn(db, dn_id: int, scope: str, principal) -> DeliveryNote:
    dn = db.get(DeliveryNote, dn_id)
    allowed = _sites_for(scope, principal)
    if dn is None or (allowed is not None and dn.site_id not in allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    return dn


def _decimal(v: str | None) -> Decimal | None:
    try:
        return Decimal(v) if v not in (None, "") else None
    except InvalidOperation as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter numbers only") from e


def _counts(lines: str) -> dict[int, tuple[Decimal, Decimal]]:
    """[{line_id, received, damaged}] as sent by the receipt page."""
    try:
        rows = json.loads(lines)
        return {
            int(r["line_id"]): (Decimal(str(r["received"])), Decimal(str(r.get("damaged") or 0)))
            for r in rows
            if r.get("received") not in (None, "")
        }
    except (ValueError, KeyError, TypeError, InvalidOperation) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the count for each item"
        ) from e


async def _photo(file: UploadFile | None, dn: DeliveryNote, what: str) -> str:
    if file is None or not file.filename:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Take both photos: the material as unloaded and the signed challan",
        )
    rel, _name = await save_upload(file, f"deliveries/{dn.code}")
    return rel


# --- the public receipt page ---------------------------------------------------------------------


@public.get("/{token}")
def receipt(token: str, request: Request, db: DbSession) -> dict:
    ratelimit.check(request, "receipt-get", limit=60, window_s=600)
    dn = dlv.by_token(db, token)
    return jsonable_encoder(dlv.receipt_view(db, dn))


@public.post("/{token}")
async def submit_receipt(
    token: str,
    request: Request,
    db: DbSession,
    name: Annotated[str, Form(max_length=100)],
    lines: Annotated[str, Form()],
    photo_goods: Annotated[UploadFile | None, File()] = None,
    photo_challan: Annotated[UploadFile | None, File()] = None,
    phone: Annotated[str | None, Form(max_length=20)] = None,
    lat: Annotated[str | None, Form()] = None,
    lng: Annotated[str | None, Form()] = None,
    accuracy: Annotated[str | None, Form()] = None,
) -> dict:
    """The count, once: who (name, phone), what came and what was damaged per item, two photos
    (the material as unloaded, the signed challan), GPS when the phone allows."""
    ratelimit.check(request, "receipt-post", limit=10, window_s=600)
    dn = dlv.by_token(db, token)
    if dn.confirmed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Already confirmed by {dn.receiver_name} at {dn.confirmed_at:%d %b %Y %H:%M}",
        )
    goods = await _photo(photo_goods, dn, "goods")
    challan = await _photo(photo_challan, dn, "challan")
    dlv.confirm(
        db,
        dn,
        name=name,
        phone=phone,
        counts=_counts(lines),
        photo_goods=goods,
        photo_challan=challan,
        lat=_decimal(lat),
        lng=_decimal(lng),
        accuracy=_decimal(accuracy),
    )
    from app import audit  # noqa: PLC0415

    audit.record(
        db,
        "delivery.confirm",
        "delivery_note",
        dn.id,
        user_id=None,
        after={"by": dn.receiver_name, "status": dn.status, "unlisted": dn.unlisted_receiver},
        ip=audit.client_ip(request),
    )
    db.commit()
    return jsonable_encoder(dlv.receipt_view(db, dn))


# --- deliveries (staff) --------------------------------------------------------------------------


def _dn_row(db, dn: DeliveryNote) -> dict:
    site = db.get(Site, dn.site_id)
    short = db.scalar(select(func.count()).where(Discrepancy.delivery_id == dn.id))
    return {
        "id": dn.id,
        "code": dn.code,
        "kind": dn.kind,
        "site_id": site.id,
        "site": f"{site.code} · {site.name}",
        "vendor": dlv.vendor_name(db, dn),
        "po_id": dn.po_id,
        "transfer_id": dn.transfer_id,
        "status": dn.status,
        "expected_at": dn.expected_at,
        "expected_label": label(dn.expected_at),
        "confirmed_at": dn.confirmed_at,
        "confirmed_label": label(dn.confirmed_at),
        "receiver_name": dn.receiver_name,
        "unlisted_receiver": dn.unlisted_receiver,
        "age_hours": round(dlv.age_hours(dn), 1) if dn.confirmed_at is None else None,
        "discrepancies": short,
        "items": len(dn.lines),
        "drop_photo": bool(dn.drop_photo),
    }


@router.get("/deliveries")
def list_deliveries(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DeliveryView,
    site_id: int | None = None,
    state: str | None = None,  # unconfirmed, confirmed, short
) -> list[dict]:
    q = select(DeliveryNote).order_by(DeliveryNote.id.desc())
    allowed = _sites_for(scope, principal)
    if allowed is not None:
        q = q.where(DeliveryNote.site_id.in_(allowed or [-1]))
    if site_id:
        q = q.where(DeliveryNote.site_id == site_id)
    if state == "unconfirmed":
        q = q.where(DeliveryNote.confirmed_at.is_(None), DeliveryNote.status == "dispatched")
    elif state in ("confirmed", "short"):
        q = q.where(DeliveryNote.status == state)
    return jsonable_encoder([_dn_row(db, d) for d in db.scalars(q.limit(500))])


@router.get("/link-status")
def link_status(_: DeliveryView) -> dict:
    """While PUBLIC_BASE_URL is still this PC, receipt links only open in the office."""
    return {"test_link": dlv.is_test_link()}


@router.get("/deliveries/{dn_id}")
def get_delivery(
    dn_id: int, db: DbSession, principal: CurrentPrincipal, scope: DeliveryView
) -> dict:
    dn = _dn(db, dn_id, scope, principal)
    out = _dn_row(db, dn)
    out.update(
        vehicle_no=dn.vehicle_no,
        driver_name=dn.driver_name,
        driver_phone=dn.driver_phone,
        receiver_phone=dn.receiver_phone,
        gps={"lat": dn.lat, "lng": dn.lng, "accuracy_m": dn.gps_accuracy_m}
        if dn.lat is not None
        else None,
        photos=[
            k
            for k in ("goods", "challan", "drop")
            if getattr(
                dn, {"goods": "photo_goods", "challan": "photo_challan", "drop": "drop_photo"}[k]
            )
        ],
        drop_photo_at=dn.drop_photo_at,
        lines=[
            {
                "id": ln.id,
                "product": db.get(Product, ln.product_id).name,
                "qty": ln.qty,
                "unit": ln.unit,
                "packs": ln.packs,
                "pack_unit": ln.pack_unit,
                "received_qty": ln.received_qty,
                "damaged_qty": ln.damaged_qty,
            }
            for ln in dn.lines
        ],
        discrepancies=[
            {
                "kind": d.kind,
                "qty": d.qty,
                "unit": d.unit,
                "product": db.get(Product, d.product_id).name,
                "debit_note_id": d.debit_note_id,
            }
            for d in db.scalars(select(Discrepancy).where(Discrepancy.delivery_id == dn.id))
        ],
        debit_notes=[
            {"id": n.id, "code": n.code, "status": n.status, "amount": n.amount, "lines": n.lines}
            for n in db.scalars(select(DebitNote).where(DebitNote.delivery_id == dn.id))
        ],
        grn_id=dn.grn_id,
        can_confirm=dn.confirmed_at is None
        and dn.status == "dispatched"
        and _may(principal, "delivery.confirm", dn.site_id),
    )
    return jsonable_encoder(out)


def _may(principal, code: str, site_id: int) -> bool:
    scope = principal.permissions.get(code)
    if scope is None:
        return False
    return scope == "all" or site_id in set(material.assigned_sites(principal))


@router.get("/deliveries/{dn_id}/pdf")
def delivery_pdf(dn_id: int, db: DbSession, principal: CurrentPrincipal, scope: DeliveryView):
    dn = _dn(db, dn_id, scope, principal)
    if not dn.pdf_path or not media(dn.pdf_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF: make a new receipt link")
    return FileResponse(media(dn.pdf_path), media_type="application/pdf", filename=f"{dn.code}.pdf")


@router.get("/deliveries/{dn_id}/photo/{which}")
def delivery_photo(
    dn_id: int, which: str, db: DbSession, principal: CurrentPrincipal, scope: DeliveryView
):
    dn = _dn(db, dn_id, scope, principal)
    rel = {"goods": dn.photo_goods, "challan": dn.photo_challan, "drop": dn.drop_photo}.get(which)
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No photo")
    return send_file(rel, f"{dn.code}-{which}.jpg")


@router.post("/deliveries/{dn_id}/confirm")
async def confirm_delivery(
    dn_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DeliveryView,
    lines: Annotated[str, Form()],
    photo_goods: Annotated[UploadFile | None, File()] = None,
    photo_challan: Annotated[UploadFile | None, File()] = None,
    lat: Annotated[str | None, Form()] = None,
    lng: Annotated[str | None, Form()] = None,
    accuracy: Annotated[str | None, Form()] = None,
) -> dict:
    """A logged-in supervisor confirms the same way (their name is filled in)."""
    dn = _dn(db, dn_id, scope, principal)
    if not _may(principal, "delivery.confirm", dn.site_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot confirm deliveries for this site"
        )
    goods = await _photo(photo_goods, dn, "goods")
    challan = await _photo(photo_challan, dn, "challan")
    u = principal.user
    dlv.confirm(
        db,
        dn,
        name=u.full_name,
        phone=u.phone,
        counts=_counts(lines),
        photo_goods=goods,
        photo_challan=challan,
        user=u,
        lat=_decimal(lat),
        lng=_decimal(lng),
        accuracy=_decimal(accuracy),
    )
    record(
        db,
        request,
        principal,
        "delivery.confirm",
        "delivery_note",
        dn.id,
        after={"status": dn.status},
    )
    db.commit()
    return get_delivery(dn.id, db, principal, scope)


def _store_edit(principal) -> None:
    if not ({"store.edit", "po.edit"} & set(principal.permissions)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the store can do this")


@router.post("/deliveries/{dn_id}/drop-photo")
async def drop_photo(
    dn_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DeliveryView,
    photo: Annotated[UploadFile, File()],
) -> dict:
    """The driver's drop-off photo when no one at site confirms: proof of drop-off, not quantity."""
    _store_edit(principal)
    dn = _dn(db, dn_id, scope, principal)
    rel, _n = await save_upload(photo, f"deliveries/{dn.code}")
    dlv.drop_off(db, dn, rel, principal.user.id)
    record(db, request, principal, "delivery.drop_photo", "delivery_note", dn.id)
    db.commit()
    return get_delivery(dn.id, db, principal, scope)


class DeliveryUpdate(BaseModel):
    vehicle_no: str | None = Field(None, max_length=30)
    driver_name: str | None = Field(None, max_length=100)
    driver_phone: str | None = Field(None, max_length=20)
    expected_at: datetime | None = None


@router.put("/deliveries/{dn_id}")
def update_delivery(
    dn_id: int,
    body: DeliveryUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DeliveryView,
) -> dict:
    """Vehicle, driver, expected time. The note is printed again with a new receipt link (the
    old link stops working)."""
    _store_edit(principal)
    dn = _dn(db, dn_id, scope, principal)
    if dn.confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{dn.code} is already confirmed")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(dn, k, v)
    raw = dlv.new_link(db, dn)
    dn.pdf_path = dn_pdf.save(db, dn, raw)
    dlv._notify_site(db, dn, raw, principal.user.id)
    record(
        db,
        request,
        principal,
        "delivery.update",
        "delivery_note",
        dn.id,
        after=jsonable_encoder(body.model_dump(exclude_unset=True)),
    )
    db.commit()
    return get_delivery(dn.id, db, principal, scope)


class PartDelivery(BaseModel):
    lines: dict[int, Decimal]  # PO line id -> qty in this dispatch
    vehicle_no: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None
    expected_at: datetime | None = None


@router.post("/pos/{po_id}/delivery", status_code=status.HTTP_201_CREATED)
def part_delivery(
    po_id: int,
    body: PartDelivery,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: DeliveryView,
) -> dict:
    """A part dispatch of a PO going to a site: its own delivery note."""
    _store_edit(principal)
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO not found")
    dn = dlv.for_po(db, po, principal.user.id, {int(k): v for k, v in body.lines.items()})
    if dn is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to deliver to a site on that PO"
        )
    for k in ("vehicle_no", "driver_name", "driver_phone", "expected_at"):
        if getattr(body, k):
            setattr(dn, k, getattr(body, k))
    raw = dlv.new_link(db, dn)
    dn.pdf_path = dn_pdf.save(db, dn, raw)
    record(db, request, principal, "delivery.create", "delivery_note", dn.id, after={"po": po.code})
    db.commit()
    return {"id": dn.id, "code": dn.code}


@router.get("/debit-notes")
def debit_notes(db: DbSession, principal: CurrentPrincipal, _: DeliveryView) -> list[dict]:
    return jsonable_encoder(
        [
            {
                "id": n.id,
                "code": n.code,
                "vendor": db.get(Vendor, n.vendor_id).name,
                "po_id": n.po_id,
                "delivery_id": n.delivery_id,
                "status": n.status,
                "amount": n.amount,
                "lines": n.lines,
                "created_at": n.created_at,
            }
            for n in db.scalars(select(DebitNote).order_by(DebitNote.id.desc()).limit(300))
        ]
    )


# --- three-way match -----------------------------------------------------------------------------


class Release(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/vendor-bills/{bid}/release")
def release_bill(
    bid: int,
    body: Release,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("delivery.escalate"))],
) -> dict:
    """Release a bill blocked by the three-way match (logged and shown on the bill)."""
    b = db.get(VendorBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    reasons = sc.refresh_block(db, b)
    if not reasons:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.number} is not blocked")
    b.released_by, b.released_at, b.release_reason = principal.user.id, sc.now(), body.reason
    record(
        db,
        request,
        principal,
        "vendor_bill.release",
        "vendor_bill",
        b.id,
        after={"reason": body.reason, "blocked": reasons},
    )
    db.commit()
    return jsonable_encoder(
        {
            "id": b.id,
            "number": b.number,
            "blocked_reasons": reasons,
            "released_at": b.released_at,
            "release_reason": b.release_reason,
        }
    )


@router.get("/reports/match")
def match_report(
    db: DbSession, principal: CurrentPrincipal, _: DeliveryView, format: str | None = None
):
    """Bills blocked and why; deliveries billed but not confirmed at site."""
    blocked = [
        {
            "bill": b.number,
            "bill_id": b.id,
            "vendor": b.vendor.name,
            "bill_date": b.bill_date,
            "status": b.status,
            "released": b.released_at is not None,
            "release_reason": b.release_reason,
            "why": "; ".join(r["message"] for r in b.blocked_reasons),
        }
        for b in db.scalars(
            select(VendorBill)
            .where(func.jsonb_array_length(VendorBill.blocked_reasons) > 0)
            .order_by(VendorBill.id.desc())
        )
    ]
    unconfirmed = sc.billed_not_confirmed(db)
    if format == "xlsx":
        return _book(
            "three-way-match",
            [
                (
                    "Bills blocked",
                    ["Bill", "Vendor", "Date", "Status", "Released", "Release reason", "Why"],
                    [
                        [
                            r["bill"],
                            r["vendor"],
                            r["bill_date"],
                            r["status"],
                            "yes" if r["released"] else "",
                            r["release_reason"] or "",
                            r["why"],
                        ]
                        for r in blocked
                    ],
                ),
                (
                    "Billed, not confirmed",
                    ["Bill", "Delivery", "Expected"],
                    [[r["bill"], r["delivery"], label(r["expected_at"])] for r in unconfirmed],
                ),
            ],
        )
    return jsonable_encoder({"blocked": blocked, "billed_not_confirmed": unconfirmed})


# --- rate contracts ------------------------------------------------------------------------------


class ContractIn(BaseModel):
    vendor_id: int | None = None
    product_id: int | None = None
    rate: Decimal | None = Field(None, gt=0)
    freight_terms: str | None = Field(None, max_length=200)
    valid_from: date | None = None
    valid_till: date | None = None
    agreed_by: str | None = Field(None, max_length=100)
    notes: str | None = None
    is_active: bool | None = None


def _rc_out(db, c: RateContract) -> dict:
    p = db.get(Product, c.product_id)
    return {
        "id": c.id,
        "vendor_id": c.vendor_id,
        "vendor": db.get(Vendor, c.vendor_id).name,
        "product_id": c.product_id,
        "product": p.name,
        "unit": p.unit,
        "rate": c.rate,
        "freight_terms": c.freight_terms,
        "valid_from": c.valid_from,
        "valid_till": c.valid_till,
        "agreed_by": c.agreed_by,
        "notes": c.notes,
        "attachment": bool(c.attachment_path),
        "is_active": c.is_active,
        "version": c.version,
        "expires_in_days": (c.valid_till - date.today()).days,
    }


@router.get("/rate-contracts")
def list_contracts(
    db: DbSession,
    _: RcView,
    vendor_id: int | None = None,
    product_id: int | None = None,
    current: bool = False,
) -> list[dict]:
    q = select(RateContract).order_by(RateContract.valid_till.desc())
    if vendor_id:
        q = q.where(RateContract.vendor_id == vendor_id)
    if product_id:
        q = q.where(RateContract.product_id == product_id)
    if current:
        q = q.where(
            RateContract.is_active,
            RateContract.valid_from <= date.today(),
            RateContract.valid_till >= date.today(),
        )
    return jsonable_encoder([_rc_out(db, c) for c in db.scalars(q.limit(500))])


@router.post("/rate-contracts", status_code=status.HTTP_201_CREATED)
def create_contract(
    body: ContractIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: RcEdit
) -> dict:
    data = body.model_dump(exclude_unset=True)
    for k in ("vendor_id", "product_id", "rate", "valid_from", "valid_till"):
        if data.get(k) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Fill in: {k.replace('_', ' ')}"
            )
    if db.get(Vendor, data["vendor_id"]) is None or db.get(Product, data["product_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Vendor or product not found")
    if data["valid_till"] < data["valid_from"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Valid till is before valid from")
    c = RateContract(**data, created_by=principal.user.id)
    sc.check_overlap(db, c)
    db.add(c)
    sc.save_contract_version(db, c, principal.user.id)
    record(
        db,
        request,
        principal,
        "rate_contract.create",
        "rate_contract",
        c.id,
        after=sc.contract_snapshot(c),
    )
    db.commit()
    return jsonable_encoder(_rc_out(db, c))


@router.put("/rate-contracts/{cid}")
def update_contract(
    cid: int,
    body: ContractIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: RcEdit,
) -> dict:
    c = db.get(RateContract, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    before = sc.contract_snapshot(c)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("vendor_id", "product_id") and v != getattr(c, k):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Make a new contract for another vendor or product",
            )
        setattr(c, k, v)
    if c.valid_till < c.valid_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Valid till is before valid from")
    sc.check_overlap(db, c)
    sc.save_contract_version(db, c, principal.user.id)
    record(
        db,
        request,
        principal,
        "rate_contract.update",
        "rate_contract",
        c.id,
        before=before,
        after=sc.contract_snapshot(c),
    )
    db.commit()
    return jsonable_encoder(_rc_out(db, c))


@router.get("/rate-contracts/{cid}/versions")
def contract_versions(cid: int, db: DbSession, _: RcView) -> list[dict]:
    rows = db.execute(
        select(RateContractVersion, User.full_name)
        .outerjoin(User, User.id == RateContractVersion.created_by)
        .where(RateContractVersion.contract_id == cid)
        .order_by(RateContractVersion.version.desc())
    ).all()
    return jsonable_encoder(
        [{"version": v.version, "data": v.data, "by": name, "at": v.created_at} for v, name in rows]
    )


@router.post("/rate-contracts/{cid}/attachment")
async def contract_attachment(
    cid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: RcEdit,
    file: Annotated[UploadFile, File()],
) -> dict:
    """The vendor's quote."""
    c = db.get(RateContract, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contract not found")
    rel, _n = await save_upload(file, "rate-contracts")
    c.attachment_path = rel
    sc.save_contract_version(db, c, principal.user.id)
    record(db, request, principal, "rate_contract.attachment", "rate_contract", c.id)
    db.commit()
    return jsonable_encoder(_rc_out(db, c))


@router.get("/rate-contracts/{cid}/attachment")
def get_contract_attachment(cid: int, db: DbSession, _: RcView):
    c = db.get(RateContract, cid)
    if c is None or not c.attachment_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No attachment")
    return send_file(c.attachment_path, f"rate-contract-{c.id}{media(c.attachment_path).suffix}")


@router.get("/rate-contracts-lookup")
def contract_lookup(
    db: DbSession,
    principal: CurrentPrincipal,
    vendor_id: int,
    product_id: int,
    on: date | None = None,
) -> dict:
    """The agreed rate for a PO line (purchase and accounts see it on every PO)."""
    if not ({"po.view", "po.edit", "ratecontract.view"} & set(principal.permissions)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
    c = sc.active_contract(db, vendor_id, product_id, on or date.today())
    return jsonable_encoder(
        {
            "contract_id": c.id,
            "rate": c.rate,
            "unit": db.get(Product, product_id).unit,
            "valid_till": c.valid_till,
        }
        if c
        else {"contract_id": None}
    )


# --- stage done, bill it -------------------------------------------------------------------------

BillingView = Annotated[str, Depends(require_permission("billing.view"))]


@router.get("/ready-to-bill")
def ready_to_bill(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
    site_id: int | None = None,
    state: str = "open",
) -> list[dict]:
    allowed = _sites_for(scope, principal)
    sites = [site_id] if site_id and (allowed is None or site_id in allowed) else allowed
    return jsonable_encoder(sc.ready_rows(db, sites, state))


class RaiseIn(BaseModel):
    site_id: int


@router.post("/ready-to-bill/raise")
def raise_ra(
    body: RaiseIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: BillingView
) -> dict:
    """Open the RA bill draft with the finished stages' quantities filled in."""
    from app.finance import billing  # noqa: PLC0415
    from app.finance.billing import RaIn  # noqa: PLC0415

    c = db.scalar(select(ClientContract).where(ClientContract.site_id == body.site_id))
    if c is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This site has no client contract yet")
    items = db.scalars(
        select(ReadyToBill).where(
            ReadyToBill.site_id == body.site_id,
            ReadyToBill.status == "open",
            ReadyToBill.contract_line_id.is_not(None),
        )
    ).all()
    if not items:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing ready to bill on a contract line")
    given: dict[int, Decimal] = {}
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import ContractLine  # noqa: PLC0415

    for it in items:
        given[it.contract_line_id] = given.get(it.contract_line_id, Decimal(0)) + Decimal(it.qty)
    for cl_id in list(given):
        cl = db.get(ContractLine, cl_id)
        left = Decimal(cl.qty) - fsvc.billed_before(db, cl.id, None)
        given[cl_id] = min(given[cl_id], max(Decimal(0), left))
    lines = [{"contract_line_id": k, "qty": v} for k, v in given.items()]
    out = billing.create_ra(c.id, RaIn(lines=lines), request, db, principal, scope)
    for it in items:
        it.status, it.ra_bill_id, it.billed_at = "billed", out["id"], sc.now()
    db.commit()
    return {"ra_bill_id": out["id"], "code": out["code"], "lines": len(lines)}


class Dismiss(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/ready-to-bill/{rid}/dismiss")
def dismiss_ready(
    rid: int,
    body: Dismiss,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: BillingView,
) -> dict:
    r = db.get(ReadyToBill, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    r.status, r.note = "dismissed", body.reason
    record(
        db,
        request,
        principal,
        "ready_to_bill.dismiss",
        "ready_to_bill",
        r.id,
        after={"reason": body.reason},
    )
    db.commit()
    return {"ok": True}


# --- new areas -----------------------------------------------------------------------------------

SiteView = Annotated[str, Depends(require_permission("site.view"))]
AreaApprove = Annotated[str, Depends(require_permission("sitearea.approve"))]


def _area_out(db, r: NewAreaRequest) -> dict:
    site = db.get(Site, r.site_id)
    who = db.get(User, r.requested_by) if r.requested_by else None
    from app.survey.models import AreaType  # noqa: PLC0415

    at = db.get(AreaType, r.area_type_id) if r.area_type_id else None
    return {
        "id": r.id,
        "site_id": site.id,
        "site": f"{site.code} · {site.name}",
        "name": r.name,
        "area_type": at.name if at else None,
        "approx_sqm": r.approx_sqm,
        "parent_node_id": r.parent_node_id,
        "photo": bool(r.photo),
        "note": r.note,
        "status": r.status,
        "requested_by": who.full_name if who else None,
        "requested_at": r.requested_at,
        "decided_at": r.decided_at,
        "decision_note": r.decision_note,
        "node_id": r.node_id,
        "moved_to_node_id": r.moved_to_node_id,
    }


@router.post("/new-areas", status_code=status.HTTP_201_CREATED)
async def ask_new_area(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SiteView,
    site_id: Annotated[int, Form()],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    photo: Annotated[UploadFile, File()],
    area_type_id: Annotated[int | None, Form()] = None,
    approx_sqm: Annotated[str | None, Form()] = None,
    parent_node_id: Annotated[int | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
) -> dict:
    """From the phone: a place not on the site's list (name, area type, approximate size, a
    photo). Planning approves it; work can be booked on it meanwhile."""
    if not _may(principal, "site.update", site_id) and not _may(principal, "site.edit", site_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot ask for areas on this site")
    if (
        parent_node_id
        and (db.get(SiteNode, parent_node_id) or SiteNode(site_id=-1)).site_id != site_id
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That place is not on this site")
    rel, _n = await save_upload(photo, f"sites/{site_id}/new-areas")
    r = NewAreaRequest(
        site_id=site_id,
        name=name.strip(),
        area_type_id=area_type_id,
        approx_sqm=_decimal(approx_sqm),
        parent_node_id=parent_node_id,
        note=note,
        photo=rel,
        requested_by=principal.user.id,
    )
    db.add(r)
    db.flush()
    from app.portal.service import notify  # noqa: PLC0415

    site = db.get(Site, site_id)
    notify(
        db,
        [dlv.settings(db).planning_user_id] + list(_approvers(db)),
        "new_area",
        f"New area asked for at {site.name}: {r.name}",
        link="/new-areas",
        site_id=site_id,
    )
    record(
        db,
        request,
        principal,
        "new_area.ask",
        "new_area",
        r.id,
        after={"name": r.name, "site": site.code},
    )
    db.commit()
    return jsonable_encoder(_area_out(db, r))


def _approvers(db):
    from app.models import Role, RolePermission, UserRole  # noqa: PLC0415

    return db.scalars(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            RolePermission.permission_code == "sitearea.approve",
            User.is_active,
            User.is_demo.is_(False),
            Role.code != "super_admin",
        )
    ).all()


@router.get("/new-areas")
def list_new_areas(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
    state: str | None = "pending",
    site_id: int | None = None,
) -> list[dict]:
    q = select(NewAreaRequest).order_by(NewAreaRequest.id.desc())
    if state:
        q = q.where(NewAreaRequest.status == state)
    if site_id:
        q = q.where(NewAreaRequest.site_id == site_id)
    allowed = None if scope == "all" else set(material.assigned_sites(principal))
    return jsonable_encoder(
        [
            _area_out(db, r)
            for r in db.scalars(q.limit(300))
            if allowed is None or r.site_id in allowed
        ]
    )


@router.get("/new-areas/{rid}/photo")
def new_area_photo(rid: int, db: DbSession, _: SiteView):
    r = db.get(NewAreaRequest, rid)
    if r is None or not r.photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No photo")
    return send_file(r.photo, f"new-area-{r.id}.jpg")


class Approve(BaseModel):
    parent_node_id: int | None = None
    kind: str = "other"


@router.post("/new-areas/{rid}/approve")
def approve_new_area(
    rid: int,
    body: Approve,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: AreaApprove,
) -> dict:
    r = db.get(NewAreaRequest, rid)
    if r is None or r.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Not waiting for a decision")
    from app.sites.models import NODE_KINDS  # noqa: PLC0415

    if body.kind not in NODE_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown kind of place")
    node = sc.approve_area(db, r, principal.user.id, body.parent_node_id, body.kind)
    record(db, request, principal, "new_area.approve", "new_area", r.id, after={"node": node.id})
    db.commit()
    return jsonable_encoder(_area_out(db, r))


class Reject(BaseModel):
    move_to_node_id: int
    note: str | None = Field(None, max_length=1000)


@router.post("/new-areas/{rid}/reject")
def reject_new_area(
    rid: int,
    body: Reject,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: AreaApprove,
) -> dict:
    r = db.get(NewAreaRequest, rid)
    if r is None or r.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Not waiting for a decision")
    sc.reject_area(db, r, principal.user.id, body.move_to_node_id, body.note)
    record(
        db,
        request,
        principal,
        "new_area.reject",
        "new_area",
        r.id,
        after={"moved_to": body.move_to_node_id},
    )
    db.commit()
    return jsonable_encoder(_area_out(db, r))


# --- labour productivity -------------------------------------------------------------------------


@router.get("/productivity-norms")
def norms(db: DbSession, _: SiteView) -> list[dict]:
    """Expected sqm per man-day per system (or area type); empty: to be set."""
    from app.masters.models import System  # noqa: PLC0415

    have = {
        n.system_id: n
        for n in db.scalars(select(ProductivityNorm).where(ProductivityNorm.system_id.is_not(None)))
    }
    return jsonable_encoder(
        [
            {
                "system_id": s.id,
                "system": f"{s.code} · {s.name}",
                "sqm_per_manday": have[s.id].sqm_per_manday if s.id in have else None,
            }
            for s in db.scalars(select(System).where(System.is_active).order_by(System.name))
        ]
    )


class NormIn(BaseModel):
    system_id: int | None = None
    area_type_id: int | None = None
    sqm_per_manday: Decimal | None = Field(None, gt=0)


@router.put("/productivity-norms")
def set_norm(
    body: NormIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("settings.company"))],
) -> dict:
    if (body.system_id is None) == (body.area_type_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give a system or an area type")
    col = ProductivityNorm.system_id if body.system_id else ProductivityNorm.area_type_id
    n = db.scalar(select(ProductivityNorm).where(col == (body.system_id or body.area_type_id)))
    if n is None:
        n = ProductivityNorm(
            system_id=body.system_id, area_type_id=body.area_type_id, created_by=principal.user.id
        )
        db.add(n)
    n.sqm_per_manday = body.sqm_per_manday
    record(
        db,
        request,
        principal,
        "productivity_norm.set",
        "productivity_norm",
        None,
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return {"ok": True}


class Override(BaseModel):
    note: str = Field(min_length=5, max_length=1000)


@router.post("/subcon-bills/{sid}/override")
def override_productivity(
    sid: int,
    body: Override,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("labourcheck.override"))],
) -> dict:
    """ "Sir decides": a bill flagged "productivity low" may be approved, with a note."""
    b = db.get(SubconBill, sid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if sc.productivity_check(db, b) != "low":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.number} is not flagged")
    b.productivity_override_by, b.productivity_override_at, b.productivity_override_note = (
        principal.user.id,
        sc.now(),
        body.note,
    )
    record(
        db,
        request,
        principal,
        "subcon_bill.productivity_override",
        "subcon_bill",
        b.id,
        after={"note": body.note, "check": b.productivity},
    )
    db.commit()
    return jsonable_encoder(
        {
            "id": b.id,
            "number": b.number,
            "productivity_status": b.productivity_status,
            "productivity": b.productivity,
            "override_note": b.productivity_override_note,
        }
    )


@router.get("/subcon-bills/{sid}/productivity")
def subcon_productivity(sid: int, db: DbSession, _: SiteView) -> dict:
    b = db.get(SubconBill, sid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    who = db.get(User, b.productivity_override_by) if b.productivity_override_by else None
    return jsonable_encoder(
        {
            "id": b.id,
            "number": b.number,
            "status": b.status,
            "productivity_status": b.productivity_status,
            "productivity": b.productivity,
            "override_by": who.full_name if who else None,
            "override_at": b.productivity_override_at,
            "override_note": b.productivity_override_note,
        }
    )


@router.get("/reports/productivity")
def productivity_report(
    db: DbSession, _: SiteView, site_id: int | None = None, format: str | None = None
):
    rows = sc.productivity_report(db, site_id)
    if format == "xlsx":
        return _book(
            "labour-productivity",
            [
                (
                    "By month",
                    [
                        "Site",
                        "Contractor",
                        "Month",
                        "Man-days",
                        "Sqm done",
                        "Sqm per man-day",
                        "Expected",
                        "Status",
                    ],
                    [
                        [
                            r["site"],
                            r["contractor"],
                            r["month"],
                            r["mandays"],
                            r["sqm"],
                            r["actual"],
                            r["expected"] if r["expected"] is not None else "to be set",
                            r["status"],
                        ]
                        for r in rows
                    ],
                )
            ],
        )
    return jsonable_encoder(rows)


# --- consumption variance ------------------------------------------------------------------------


@router.get("/reports/consumption")
def consumption_report(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: SiteView,
    site_id: int,
    format: str | None = None,
):
    allowed = _sites_for(scope, principal)
    if allowed is not None and site_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    rows = sc.consumption(db, site_id)
    if format == "xlsx":
        return _book(
            "consumption-variance",
            [
                (
                    "By place and product",
                    [
                        "Place",
                        "Product",
                        "Unit",
                        "Sqm done",
                        "Issued",
                        "Expected",
                        "Per sqm",
                        "Variance %",
                        "Flag",
                    ],
                    [
                        [
                            r["node"],
                            r["product"],
                            r["unit"],
                            r["sqm_done"],
                            r["issued"],
                            r["expected"],
                            r["actual_per_sqm"],
                            r["variance_percent"],
                            "yes" if r["flag"] else "",
                        ]
                        for r in rows
                    ],
                )
            ],
        )
    site = db.get(Site, site_id)
    return jsonable_encoder(
        {
            "site": f"{site.code} · {site.name}",
            "tolerance_percent": dlv.settings(db).consumption_tolerance_percent,
            "rows": rows,
        }
    )


@router.get("/learned")
def learned(db: DbSession, principal: CurrentPrincipal, system_id: int | None = None) -> list[dict]:
    """The site average (median actual consumption per sqm over completed areas) per system and
    product, next to the master's figure. Never changes the master."""
    if not ({"library.view", "tender.view", "site.view"} & set(principal.permissions)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
    return jsonable_encoder(sc.learned(db, system_id))


# --- per site, settings --------------------------------------------------------------------------


@router.get("/sites/{site_id}/flags")
def site_flags(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: SiteView) -> dict:
    allowed = _sites_for(scope, principal)
    if allowed is not None and site_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    site = db.get(Site, site_id)
    return jsonable_encoder(
        {
            **sc.site_flags(db, site_id),
            "receiver_name": site.receiver_name,
            "receiver_phone": site.receiver_phone,
        }
    )


class ReceiverIn(BaseModel):
    receiver_name: str | None = Field(None, max_length=100)
    receiver_phone: str | None = Field(None, max_length=20)


@router.put("/sites/{site_id}/receiver")
def set_receiver(
    site_id: int,
    body: ReceiverIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SiteView,
) -> dict:
    """Who may confirm deliveries when the supervisor is away (labour leader, applicator)."""
    if not _may(principal, "site.edit", site_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this site")
    site = db.get(Site, site_id)
    site.receiver_name, site.receiver_phone = (
        body.receiver_name or None,
        body.receiver_phone or None,
    )
    record(db, request, principal, "site.receiver", "site", site.id, after=body.model_dump())
    db.commit()
    return body.model_dump()


class SettingsIn(BaseModel):
    receipt_link_days: int | None = Field(None, ge=1, le=60)
    escalate_first_hours: int | None = Field(None, ge=1, le=240)
    escalate_second_hours: int | None = Field(None, ge=1, le=480)
    planning_user_id: str | None = None
    bill_alert_days: int | None = Field(None, ge=1, le=90)
    contract_expiry_days: int | None = Field(None, ge=1, le=90)
    productivity_drop_percent: Decimal | None = Field(None, ge=0, le=100)
    consumption_tolerance_percent: Decimal | None = Field(None, ge=0, le=100)


def _settings_out(db) -> dict[str, Any]:
    s = dlv.settings(db)
    return jsonable_encoder({c: getattr(s, c) for c in SettingsIn.model_fields})


@router.get("/settings")
def get_settings(db: DbSession, _: SiteView) -> dict:
    return _settings_out(db)


@router.put("/settings")
def put_settings(
    body: SettingsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("settings.company"))],
) -> dict:
    s = dlv.settings(db)
    data = body.model_dump(exclude_unset=True)
    if (
        "planning_user_id" in data
        and data["planning_user_id"]
        and db.get(User, data["planning_user_id"]) is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "User not found")
    for k, v in data.items():
        setattr(s, k, v or None if k == "planning_user_id" else v)
    record(
        db,
        request,
        principal,
        "sitecontrol.settings",
        "sitecontrol_settings",
        1,
        after=jsonable_encoder(data),
    )
    db.commit()
    return _settings_out(db)
