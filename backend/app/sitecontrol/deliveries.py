# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Delivery notes: every dispatch to a site (a PO delivery straight to the site, a godown-to-site
transfer) gets a delivery note with a receipt link (QR + short link on the PDF the driver
carries; nothing is sent by SMS or WhatsApp, the link also goes to the site's in-app outbox).

The link opens one delivery's items and quantities to count; it never shows rates or values.
Its token is random (192 bits), only its SHA-256 hash is kept, it works until the delivery is
confirmed or for 7 days (setting), and it cannot reach anything else.

Confirming posts the GRN (a PO delivery) or completes the transfer with the COUNTED
quantities, so the site's stock follows what was counted, not what was sent. Anything short or
damaged becomes a discrepancy, alerts store / purchase at once and, on a PO delivery, starts a
debit-note draft against the vendor.
"""

import hashlib
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.masters.models import Product, Vendor
from app.material import service as material
from app.material.models import Grn, GrnLine, PoLine, PurchaseOrder, Store, Transfer
from app.models import Role, User, UserRole
from app.sitecontrol.models import (
    DebitNote,
    DeliveryNote,
    DeliveryNoteLine,
    Discrepancy,
    SiteControlSettings,
)
from app.sites.models import Site, SiteMember
from app.timefmt import IST, label

ZERO = Decimal(0)


def settings(db: Session) -> SiteControlSettings:
    s = db.get(SiteControlSettings, 1)
    if s is None:
        s = SiteControlSettings(id=1)
        db.add(s)
        db.flush()
    return s


def now() -> datetime:
    return datetime.now(UTC)


# --- the receipt link ----------------------------------------------------------------------------


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def is_test_link() -> bool:
    """PUBLIC_BASE_URL still points at this PC: phones at site cannot open the link."""
    host = app_settings.public_base_url.split("//")[-1].split("/")[0].split(":")[0].lower()
    return host in ("localhost", "127.0.0.1", "0.0.0.0", "") or host.endswith(".local")


def receipt_url(raw: str) -> str:
    return f"{app_settings.public_base_url.rstrip('/')}/r/{raw}"


def new_link(db: Session, dn: DeliveryNote) -> str:
    """A fresh token for the delivery (the old link stops working); returns the raw token,
    which is printed on the note and never stored."""
    raw = secrets.token_urlsafe(24)  # 192 bits
    dn.token_hash = hash_token(raw)
    dn.token_expires_at = now() + timedelta(days=settings(db).receipt_link_days)
    return raw


def by_token(db: Session, raw: str) -> DeliveryNote:
    """The delivery for a receipt link, or 404 (unknown) / 410 (expired). Confirmed
    deliveries are returned (the page shows who confirmed)."""
    if not raw or len(raw) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This receipt link is not valid")
    dn = db.scalar(select(DeliveryNote).where(DeliveryNote.token_hash == hash_token(raw)))
    if dn is None or dn.status == "cancelled":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This receipt link is not valid")
    if dn.confirmed_at is None and dn.token_expires_at and dn.token_expires_at < now():
        raise HTTPException(
            status.HTTP_410_GONE,
            "This receipt link has expired: ask the store for a new delivery note",
        )
    return dn


# --- making delivery notes ------------------------------------------------------------------------


def _packs(product: Product, base_qty: Decimal) -> tuple[Decimal | None, str | None]:
    if product.pack_size and Decimal(product.pack_size) > 0:
        return (Decimal(base_qty) / Decimal(product.pack_size)).quantize(
            Decimal("0.01")
        ), product.pack_unit or "pack"
    return None, None


def _expected(when: date | None) -> datetime:
    """Expected at the site: the PO's delivery date (noon) or the next working hours."""
    if when:
        return datetime(when.year, when.month, when.day, 12, 0, tzinfo=IST)  # noon in India
    return now() + timedelta(hours=6)


def _site_store(db: Session, store_id: int) -> Store | None:
    store = db.get(Store, store_id)
    return store if store is not None and store.kind == "site" and store.site_id else None


def _notify_site(db: Session, dn: DeliveryNote, raw: str, fallback=None) -> None:
    """The receipt link in the site's in-app outbox (supervisors of the site and its in-charge)."""
    from app.portal.service import notify  # noqa: PLC0415

    site = db.get(Site, dn.site_id)
    users = [site.site_incharge_id] + list(
        db.scalars(select(SiteMember.user_id).where(SiteMember.site_id == site.id))
    )
    if not any(users) and fallback:  # no supervisor on the site yet: whoever dispatched it
        users = [fallback]
    notify(
        db,
        users,
        "delivery",
        f"{dn.code} on its way to {site.name}: count it at site ({label(dn.expected_at, '%d %b %H:%M')}). Receipt link: {receipt_url(raw)}",
        link=f"/r/{raw}",
        site_id=site.id,
    )


def _finish(db: Session, dn: DeliveryNote, user_id) -> str:
    db.add(dn)
    db.flush()
    raw = new_link(db, dn)
    from app.sitecontrol import pdf  # noqa: PLC0415

    dn.pdf_path = pdf.save(db, dn, raw)
    _notify_site(db, dn, raw, user_id)
    return raw


def for_po(
    db: Session, po: PurchaseOrder, user_id, lines: dict[int, Decimal] | None = None
) -> DeliveryNote | None:
    """A PO going straight to a site store: a delivery note for what is still to come (or the
    given {PO line id: qty} for a part delivery)."""
    store = _site_store(db, po.store_id)
    if store is None:
        return None
    dn = DeliveryNote(
        code=material.next_code(db, "DN"),
        kind="po",
        site_id=store.site_id,
        store_id=store.id,
        po_id=po.id,
        vendor_id=po.vendor_id,
        expected_at=_expected(po.expected_delivery),
        created_by=user_id,
    )
    for pl in po.lines:
        pending = Decimal(pl.qty) - Decimal(pl.received_qty or 0)
        qty = lines.get(pl.id, ZERO) if lines is not None else pending
        if qty <= 0:
            continue
        product = db.get(Product, pl.product_id)
        base = material.to_base(db, product, qty, pl.unit)
        packs, pack_unit = _packs(product, base)
        dn.lines.append(
            DeliveryNoteLine(
                product_id=product.id,
                po_line_id=pl.id,
                qty=qty,
                unit=pl.unit,
                base_qty=base,
                packs=packs,
                pack_unit=pack_unit,
            )
        )
    if not dn.lines:
        return None
    _finish(db, dn, user_id)
    return dn


def for_transfer(db: Session, t: Transfer, user_id) -> DeliveryNote | None:
    """A dispatched godown-to-site transfer."""
    store = _site_store(db, t.to_store_id)
    if store is None:
        return None
    dn = DeliveryNote(
        code=material.next_code(db, "DN"),
        kind="transfer",
        site_id=store.site_id,
        store_id=store.id,
        transfer_id=t.id,
        vehicle_no=t.vehicle_no,
        expected_at=now() + timedelta(hours=6),
        created_by=user_id,
    )
    for ln in t.lines:
        product = db.get(Product, ln.product_id)
        packs, pack_unit = _packs(product, Decimal(ln.qty_sent))
        dn.lines.append(
            DeliveryNoteLine(
                product_id=product.id,
                transfer_line_id=ln.id,
                qty=ln.qty_sent,
                unit=product.unit,
                base_qty=ln.qty_sent,
                packs=packs,
                pack_unit=pack_unit,
            )
        )
    _finish(db, dn, user_id)
    return dn


# --- what the receipt page shows -----------------------------------------------------------------


def receipt_view(db: Session, dn: DeliveryNote) -> dict:
    """Only this delivery: its items and quantities to count, the site and the expected time.
    Never rates, values, the vendor's prices or anything else."""
    site = db.get(Site, dn.site_id)
    by = dn.receiver_name
    return {
        "code": dn.code,
        "site": site.name,
        "expected_at": dn.expected_at,
        "expected_label": label(dn.expected_at),
        "vehicle_no": dn.vehicle_no,
        "driver_name": dn.driver_name,
        "receiver_named": site.receiver_name,
        "status": dn.status,
        "confirmed": dn.confirmed_at is not None,
        "confirmed_by": by,
        "confirmed_at": dn.confirmed_at,
        "items": [
            {
                "line_id": ln.id,
                "product": db.get(Product, ln.product_id).name,
                "qty": ln.qty,
                "unit": ln.unit,
                "packs": ln.packs,
                "pack_unit": ln.pack_unit,
            }
            for ln in dn.lines
        ],
    }


# --- confirming ----------------------------------------------------------------------------------


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


def is_listed(
    db: Session, dn: DeliveryNote, name: str, phone: str | None, user: User | None
) -> bool:
    """The supervisor (a logged-in member or in-charge of the site) or the site's named receiver."""
    site = db.get(Site, dn.site_id)
    if user is not None and (
        user.id == site.site_incharge_id
        or db.scalar(
            select(SiteMember.id).where(
                SiteMember.site_id == site.id, SiteMember.user_id == user.id
            )
        )
    ):
        return True
    if site.receiver_phone and _digits(phone) and _digits(phone) == _digits(site.receiver_phone):
        return True
    if site.receiver_name and name.strip().casefold() == site.receiver_name.strip().casefold():
        return True
    incharge = db.get(User, site.site_incharge_id) if site.site_incharge_id else None
    return bool(
        incharge and incharge.phone and _digits(phone) and _digits(phone) == _digits(incharge.phone)
    )


def confirm(
    db: Session,
    dn: DeliveryNote,
    *,
    name: str,
    phone: str | None,
    counts: dict[int, tuple[Decimal, Decimal]],
    photo_goods: str,
    photo_challan: str,
    user: User | None = None,
    lat: Decimal | None = None,
    lng: Decimal | None = None,
    accuracy: Decimal | None = None,
) -> DeliveryNote:
    """Record the count once. counts: {line id: (received, damaged)} in the line unit; every
    line must be counted. Then stock follows the count."""
    if dn.confirmed_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Already confirmed by {dn.receiver_name} at {dn.confirmed_at:%d %b %Y %H:%M}",
        )
    if dn.status == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "This delivery was cancelled")
    if not name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter your name")
    if not photo_goods or not photo_challan:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Take both photos: the material as unloaded and the signed challan",
        )
    missing = [ln for ln in dn.lines if ln.id not in counts]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Count every item (enter 0 for an item that did not come)",
        )
    for ln in dn.lines:
        got, damaged = counts[ln.id]
        if got < 0 or damaged < 0 or damaged > got:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Counts cannot be negative, and damaged is part of what came",
            )
        if got > Decimal(ln.qty) * Decimal("1.5"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A count is far above what was sent: count again",
            )
        ln.received_qty, ln.damaged_qty = got, damaged
    dn.receiver_name, dn.receiver_phone = name.strip()[:100], (phone or "").strip()[:20] or None
    dn.receiver_user_id = user.id if user else None
    dn.unlisted_receiver = not is_listed(db, dn, name, phone, user)
    dn.photo_goods, dn.photo_challan = photo_goods, photo_challan
    dn.lat, dn.lng, dn.gps_accuracy_m = lat, lng, accuracy
    dn.confirmed_at = now()
    uid = user.id if user else None
    if dn.kind == "po":
        _post_po_delivery(db, dn, uid)
    else:
        _post_transfer_delivery(db, dn, uid)
    short = _discrepancies(db, dn, uid)
    dn.status = "short" if short else "confirmed"
    return dn


def _post_po_delivery(db: Session, dn: DeliveryNote, user_id) -> None:
    """The GRN with the counted quantities (damaged ones rejected), posted at once."""
    from app.material.routers import _post_grn  # noqa: PLC0415  (the router owns the posting)

    po = db.get(PurchaseOrder, dn.po_id)
    g = Grn(
        code=material.next_code(db, "GRN"),
        po_id=po.id,
        store_id=dn.store_id,
        vendor_id=po.vendor_id,
        vehicle_no=dn.vehicle_no,
        received_at=dn.confirmed_at.date(),
        remark=f"Counted at site on {dn.code} by {dn.receiver_name}",
        status="approved",
        levels_required=1,
        approved_by_1=user_id,
        approved_at_1=now(),
        created_by=user_id,
    )
    for ln in dn.lines:
        pl = db.get(PoLine, ln.po_line_id)
        got, damaged = Decimal(ln.received_qty or 0), Decimal(ln.damaged_qty or 0)
        g.lines.append(
            GrnLine(
                po_line_id=pl.id,
                product_id=pl.product_id,
                unit=pl.unit,
                ordered_qty=Decimal(pl.qty) - Decimal(pl.received_qty or 0),
                received_qty=got,
                accepted_qty=got - damaged,
                rejected_qty=damaged,
                reason="damaged at delivery" if damaged else None,
                rate=(Decimal(pl.amount) / Decimal(pl.qty)).quantize(material.RATE)
                if Decimal(pl.qty)
                else ZERO,
            )
        )
    db.add(g)
    db.flush()
    _post_grn(db, g, user_id)
    dn.grn_id = g.id


def _post_transfer_delivery(db: Session, dn: DeliveryNote, user_id) -> None:
    """The transfer completes with what was counted as good: damaged and missing material is
    written off at the site (a shortage), so the site's stock follows the count."""
    t = db.get(Transfer, dn.transfer_id)
    if t is None or t.status != "dispatched":
        return  # the store already received it: the count is still kept on the note
    received = {}
    for ln in dn.lines:
        good = Decimal(ln.received_qty or 0) - Decimal(ln.damaged_qty or 0)
        reason = []
        if Decimal(ln.damaged_qty or 0) > 0:
            reason.append(f"{ln.damaged_qty} damaged")
        if Decimal(ln.received_qty or 0) < Decimal(ln.qty):
            reason.append(f"{Decimal(ln.qty) - Decimal(ln.received_qty or 0)} not received")
        received[ln.transfer_line_id] = (
            good,
            f"{dn.code}: " + ", ".join(reason) if reason else None,
        )
    material.receive_transfer(db, t, received, user_id)


def _discrepancies(db: Session, dn: DeliveryNote, user_id) -> list[Discrepancy]:
    out = []
    for ln in dn.lines:
        short = Decimal(ln.qty) - Decimal(ln.received_qty or 0)
        damaged = Decimal(ln.damaged_qty or 0)
        for kind, q in (("short", short), ("damaged", damaged)):
            if q > 0:
                d = Discrepancy(
                    delivery_id=dn.id,
                    line_id=ln.id,
                    product_id=ln.product_id,
                    kind=kind,
                    qty=q,
                    unit=ln.unit,
                )
                db.add(d)
                out.append(d)
    if not out:
        return out
    db.flush()
    if dn.kind == "po":
        _debit_note(db, dn, out, user_id)
    _alert_discrepancy(db, dn, out)
    return out


def _debit_note(db: Session, dn: DeliveryNote, found: list[Discrepancy], user_id) -> DebitNote:
    lines, total = [], ZERO
    for d in found:
        ln = next(x for x in dn.lines if x.id == d.line_id)
        pl = db.get(PoLine, ln.po_line_id)
        rate = (
            (Decimal(pl.amount) / Decimal(pl.qty)).quantize(Decimal("0.01"))
            if Decimal(pl.qty)
            else ZERO
        )
        amount = (rate * Decimal(d.qty)).quantize(Decimal("0.01"))
        total += amount
        lines.append(
            {
                "product": db.get(Product, d.product_id).name,
                "kind": d.kind,
                "qty": str(d.qty),
                "unit": d.unit,
                "rate": str(rate),
                "amount": str(amount),
            }
        )
    po = db.get(PurchaseOrder, dn.po_id)
    note = DebitNote(
        code=material.next_code(db, "DBN"),
        vendor_id=po.vendor_id,
        po_id=po.id,
        delivery_id=dn.id,
        amount=total,
        lines=lines,
        remark=f"{dn.code}: short or damaged at site (counted by {dn.receiver_name})",
        created_by=user_id,
    )
    db.add(note)
    db.flush()
    for d in found:
        d.debit_note_id = note.id
    return note


def _alert_discrepancy(db: Session, dn: DeliveryNote, found: list[Discrepancy]) -> None:
    """At once, in-app: the store and purchase people (and whoever raised the PO)."""
    from app.portal.service import notify  # noqa: PLC0415

    users = list(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code.in_(("store_purchase",)), User.is_active, User.is_demo.is_(False))
        )
    )
    if dn.po_id:
        po = db.get(PurchaseOrder, dn.po_id)
        users.append(po.created_by)
    what = ", ".join(
        f"{d.qty:f} {d.unit} {db.get(Product, d.product_id).name} {d.kind}" for d in found
    )
    site = db.get(Site, dn.site_id)
    notify(
        db,
        users,
        "delivery_discrepancy",
        f"{dn.code} at {site.name}: {what}",
        link=f"/deliveries/{dn.id}",
        site_id=site.id,
    )


def settle_by_transfer_receipt(db: Session, t: Transfer, user_id) -> None:
    """The store received the transfer in the app itself: an open delivery note for it is closed
    with those quantities (no receipt photos; marked as received by the store)."""
    dn = db.scalar(
        select(DeliveryNote).where(
            DeliveryNote.transfer_id == t.id, DeliveryNote.confirmed_at.is_(None)
        )
    )
    if dn is None:
        return
    user = db.get(User, user_id) if user_id else None
    for ln in dn.lines:
        tl = next((x for x in t.lines if x.id == ln.transfer_line_id), None)
        ln.received_qty, ln.damaged_qty = (tl.qty_received if tl else ZERO), ZERO
    dn.receiver_name = (user.full_name if user else "store")[:100]
    dn.receiver_user_id = user_id
    dn.confirmed_at = now()
    dn.unlisted_receiver = False
    dn.status = "short" if _discrepancies(db, dn, user_id) else "confirmed"


def drop_off(db: Session, dn: DeliveryNote, photo: str, user_id) -> None:
    """The driver's drop-off photo, attached by the store: proof of drop-off, not of quantity."""
    dn.drop_photo, dn.drop_photo_at, dn.drop_photo_by = photo, now(), user_id


def age_hours(dn: DeliveryNote, at: datetime | None = None) -> float:
    return max(0.0, ((at or now()) - dn.expected_at).total_seconds() / 3600)


def media_path(rel: str) -> Path:
    return Path(app_settings.media_dir) / rel


def vendor_name(db: Session, dn: DeliveryNote) -> str | None:
    v = db.get(Vendor, dn.vendor_id) if dn.vendor_id else None
    return v.name if v else None
