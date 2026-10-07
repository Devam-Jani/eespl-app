"""Material rules: numbering, access, units, GST and totals, stock, landed cost, freight.

GST (per PO): each line's taxable amount = qty x rate less its discount (discount before tax).
Tax = taxable x GST %, for lines and charges alike. Intra-state (vendor's state = the state of
the GSTIN we buy from) splits it into CGST + SGST; inter-state is IGST. The grand total is rounded
to the rupee and the difference shown as round off.

Landed cost (when a GRN is approved): a line's net rate (after discount, before GST, which is
input credit) is raised by the PO's "add to material cost" charges in proportion to value:
    landed rate = net rate x (1 + those charges / PO taxable value)
and converted to the product's base unit. That is the rate written to the stock ledger.

Stock: sum of stock_ledger qty per store and product. Outflows (transfer out, issue) are valued at
the store's weighted average rate = sum(value) / sum(qty); a return comes back at that average.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, false, func, or_, select, text, true
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.masters.conversions import ConversionError, convert
from app.masters.models import CompanyGstin, CompanyProfile, Product, Vendor
from app.material.models import (
    FreightEntry,
    Grn,
    Indent,
    IndentLine,
    PoLine,
    PurchaseOrder,
    StockLedger,
    Store,
)
from app.sites.models import Site, SiteMember

CENT = Decimal("0.01")
QTY = Decimal("0.001")
RATE = Decimal("0.0001")
ZERO = Decimal(0)


def money(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, ROUND_HALF_UP)


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


# --- numbering -----------------------------------------------------------------------------------


def financial_year(on: date) -> str:
    """1 Apr 2026 - 31 Mar 2027 -> "2026-27"."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def next_code(db: Session, kind: str, on: date | None = None) -> str:
    """IND-2026-0001, RFQ-, GRN-, TO-, ISS-, FR- by calendar year; PO-2026-27-000001 by
    financial year. One atomic statement, so two users never get the same number."""
    on = on or date.today()
    period = financial_year(on) if kind == "PO" else str(on.year)
    value = db.execute(
        text(
            "INSERT INTO doc_sequences (kind, period, last_value) VALUES (:k, :p, 1) "
            "ON CONFLICT (kind, period) DO UPDATE SET last_value = doc_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"k": kind, "p": period},
    ).scalar_one()
    return f"PO-{period}-{value:06d}" if kind == "PO" else f"{kind}-{period}-{value:04d}"


# --- access --------------------------------------------------------------------------------------


def assigned_sites(principal: Principal):
    """Sites the caller works on: a member or the in-charge."""
    uid = principal.user.id
    members = select(SiteMember.site_id).where(SiteMember.user_id == uid)
    return select(Site.id).where(or_(Site.site_incharge_id == uid, Site.id.in_(members)))


def site_ids(db: Session, principal: Principal) -> set[int]:
    return set(db.scalars(assigned_sites(principal)))


def by_site(scope: str, principal: Principal, site_col, owner_col) -> ColumnElement[bool]:
    """all: everything; assigned: rows of the caller's sites; own: rows the caller created."""
    if scope == "all":
        return true()
    if scope == "assigned":
        return site_col.in_(assigned_sites(principal))
    if scope == "own":
        return owner_col == principal.user.id
    return false()


def covers_site(
    db: Session, scope: str | None, principal: Principal, site_id: int | None, owner=None
) -> bool:
    if scope == "all":
        return True
    if scope == "assigned":
        return site_id is not None and site_id in site_ids(db, principal)
    if scope == "own":
        return owner == principal.user.id
    return False


def need(principal: Principal, code: str) -> str:
    scope = principal.permissions.get(code)
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {code}")
    return scope


# --- stores --------------------------------------------------------------------------------------


def godown(db: Session) -> Store:
    store = db.scalar(select(Store).where(Store.kind == "godown").order_by(Store.id).limit(1))
    if store is None:
        store = Store(name="Ethios Godown", kind="godown")
        db.add(store)
        db.flush()
    return store


def site_store(db: Session, site: Site, user_id=None) -> Store:
    """The site's own store, made on first need (every new site gets one)."""
    store = db.scalar(select(Store).where(Store.site_id == site.id))
    if store is None:
        name = f"{site.code} {site.name}"[:200]
        store = Store(
            name=name, kind="site", site_id=site.id, address=site.address, created_by=user_id
        )
        db.add(store)
        db.flush()
    return store


# --- units ---------------------------------------------------------------------------------------


def to_base(db: Session, product: Product, qty: Decimal, unit: str) -> Decimal:
    """qty in `unit` -> the product's own unit (stock is kept in that)."""
    if unit == product.unit:
        return Decimal(qty)
    try:
        return convert(db, Decimal(qty), unit, product.unit, product.id).quantize(
            QTY, ROUND_HALF_UP
        )
    except ConversionError as exc:
        raise unprocessable(
            f"{product.name}: {unit} cannot be converted to {product.unit} (add a unit "
            "conversion for this product first)"
        ) from exc


# --- GST and totals ------------------------------------------------------------------------------


def is_interstate(vendor: Vendor, gstin: CompanyGstin | None) -> bool:
    """Inter-state when the vendor's GSTIN state code (or state name) differs from ours."""
    if gstin is None:
        return False
    if vendor.gstin and gstin.gstin:
        return vendor.gstin[:2] != gstin.gstin[:2]
    if vendor.state and gstin.state:
        return vendor.state.strip().casefold() != gstin.state.strip().casefold()
    return False


def compute_totals(po: PurchaseOrder) -> None:
    gross = ZERO
    taxable = ZERO
    tax = ZERO
    for ln in po.lines:
        line_gross = Decimal(ln.qty) * Decimal(ln.rate)
        ln.amount = money(line_gross * (1 - Decimal(ln.discount_percent) / 100))
        gross += line_gross
        taxable += ln.amount
        tax += ln.amount * Decimal(ln.gst_percent) / 100
    charges = ZERO
    for c in po.charges:
        charges += Decimal(c.amount)
        tax += Decimal(c.amount) * Decimal(c.gst_percent) / 100
    po.subtotal = money(gross)
    po.taxable = money(taxable)
    po.discount_total = po.subtotal - po.taxable
    tax = money(tax)
    if po.interstate:
        po.igst, po.cgst, po.sgst = tax, ZERO, ZERO
    else:
        po.cgst = money(tax / 2)
        po.sgst = tax - po.cgst
        po.igst = ZERO
    po.charges_total = money(charges)
    before = po.taxable + po.charges_total + tax
    po.grand_total = before.quantize(Decimal(1), ROUND_HALF_UP)
    po.round_off = po.grand_total - before


def cost_uplift(po: PurchaseOrder | None) -> Decimal:
    """1 + (charges added to material cost / taxable value of the PO)."""
    if po is None or not po.taxable:
        return Decimal(1)
    extra = sum((Decimal(c.amount) for c in po.charges if c.add_to_cost), ZERO)
    return 1 + extra / Decimal(po.taxable)


# --- stock ---------------------------------------------------------------------------------------


def balance(db: Session, store_id: int, product_id: int) -> tuple[Decimal, Decimal]:
    """(qty, value) of a product in a store."""
    qty, value = db.execute(
        select(
            func.coalesce(func.sum(StockLedger.qty), 0),
            func.coalesce(func.sum(StockLedger.value), 0),
        ).where(StockLedger.store_id == store_id, StockLedger.product_id == product_id)
    ).one()
    return Decimal(qty), Decimal(value)


def average_rate(db: Session, store_id: int, product_id: int) -> Decimal:
    qty, value = balance(db, store_id, product_id)
    if qty > 0:
        return (value / qty).quantize(RATE, ROUND_HALF_UP)
    last = db.scalar(
        select(StockLedger.rate)
        .where(StockLedger.store_id == store_id, StockLedger.product_id == product_id)
        .order_by(StockLedger.id.desc())
        .limit(1)
    )
    return Decimal(last or 0)


def post(
    db: Session,
    *,
    store_id: int,
    product: Product,
    qty: Decimal,
    rate: Decimal,
    ref_type: str,
    ref_id: int | None,
    user_id,
    note: str | None = None,
) -> StockLedger:
    """Append one ledger row (qty signed, in the product's unit)."""
    row = StockLedger(
        store_id=store_id,
        product_id=product.id,
        qty=Decimal(qty).quantize(QTY),
        unit=product.unit,
        rate=Decimal(rate).quantize(RATE, ROUND_HALF_UP),
        value=money(Decimal(qty) * Decimal(rate)),
        ref_type=ref_type,
        ref_id=ref_id,
        by=user_id,
        note=note,
    )
    db.add(row)
    db.flush()
    return row


def take_out(
    db: Session,
    *,
    store: Store,
    product: Product,
    qty: Decimal,
    ref_type: str,
    ref_id: int | None,
    user_id,
    note: str | None = None,
) -> Decimal:
    """An outflow at the store's average rate; refused (422) if it would go below zero, unless
    the company allows negative stock. Returns the rate used."""
    have, _ = balance(db, store.id, product.id)
    allow = bool(getattr(db.get(CompanyProfile, 1), "allow_negative_stock", False))
    if Decimal(qty) > have and not allow:
        raise unprocessable(
            f"Only {have.normalize():f} {product.unit} of {product.name} in {store.name}; "
            f"{Decimal(qty).normalize():f} asked"
        )
    rate = average_rate(db, store.id, product.id)
    post(
        db,
        store_id=store.id,
        product=product,
        qty=-Decimal(qty),
        rate=rate,
        ref_type=ref_type,
        ref_id=ref_id,
        user_id=user_id,
        note=note,
    )
    return rate


# --- indents and POs -----------------------------------------------------------------------------


def refresh_indent(indent: Indent) -> None:
    """Status from the lines: ordered / partly ordered; closed when everything was received."""
    if indent.status in ("draft", "submitted", "rejected", "cancelled"):
        return
    lines = [ln for ln in indent.lines if ln.product_id is not None or ln.free_text]
    if lines and all(Decimal(ln.received_qty) >= Decimal(ln.base_qty) for ln in lines):
        indent.status = "closed"
    elif lines and all(Decimal(ln.ordered_qty) >= Decimal(ln.base_qty) for ln in lines):
        indent.status = "ordered"
    elif any(Decimal(ln.ordered_qty) > 0 for ln in lines):
        indent.status = "partly_ordered"
    else:
        indent.status = "approved"


def refresh_po(po: PurchaseOrder) -> None:
    if po.status not in ("approved", "sent", "partly_received", "received"):
        return
    received = [Decimal(ln.received_qty) for ln in po.lines]
    if all(r >= Decimal(ln.qty) for r, ln in zip(received, po.lines, strict=True)):
        po.status = "received"
    elif any(r > 0 for r in received):
        po.status = "partly_received"


def line_site(db: Session, po: PurchaseOrder, line: PoLine) -> int | None:
    """The site a PO line is for: its indent's site, else the delivery store's site."""
    if line.indent_line_id:
        il = db.get(IndentLine, line.indent_line_id)
        if il is not None:
            return db.get(Indent, il.indent_id).site_id
    store = db.get(Store, po.store_id)
    return store.site_id if store else None


def grn_freight(db: Session, po: PurchaseOrder, grn: Grn, user_id) -> None:
    """A PO's freight is charged to sites as the material arrives: each GRN carries the share of
    every freight charge that its received value bears to the PO's taxable value, split over
    the sites of the lines received. A cancelled or short-closed PO charges no more freight."""
    freight = [c for c in po.charges if c.kind == "freight" and Decimal(c.amount) > 0]
    if not freight or not po.taxable:
        return
    lines = {ln.id: ln for ln in po.lines}
    value: dict[int | None, Decimal] = defaultdict(Decimal)
    for gl in grn.lines:
        pl = lines.get(gl.po_line_id or 0)
        if pl is not None and Decimal(gl.accepted_qty) > 0:
            value[line_site(db, po, pl)] += Decimal(gl.accepted_qty) * Decimal(gl.rate)
    store = db.get(Store, po.store_id)
    for charge in freight:
        for site_id, v in value.items():
            amount = money(Decimal(charge.amount) * v / Decimal(po.taxable))
            if amount <= 0:
                continue
            db.add(
                FreightEntry(
                    source="po",
                    po_id=po.id,
                    grn_id=grn.id,
                    site_id=site_id,
                    direction="inbound",
                    on_date=grn.received_at,
                    amount=amount,
                    gst_percent=charge.gst_percent,
                    transporter=po.vendor.name,
                    to_place=store.name if store else None,
                    remark=f"{charge.description or 'Freight'} ({grn.code})",
                    created_by=user_id,
                )
            )


def next_code_plain(db: Session, kind: str) -> str:
    """AST-0001 ...: one running number, not reset by year."""
    value = db.execute(
        text(
            "INSERT INTO doc_sequences (kind, period, last_value) VALUES (:k, 'all', 1) "
            "ON CONFLICT (kind, period) DO UPDATE SET last_value = doc_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"k": kind},
    ).scalar_one()
    return f"{kind}-{value:04d}"


# --- PO checks and texts -------------------------------------------------------------------------


def our_gstin(db: Session, po: PurchaseOrder) -> CompanyGstin | None:
    """The GSTIN the PO is billed from (its own, else the company default)."""
    if po.from_gstin_id:
        return db.get(CompanyGstin, po.from_gstin_id)
    return db.scalar(
        select(CompanyGstin).order_by(CompanyGstin.is_default.desc(), CompanyGstin.id).limit(1)
    )


def po_warnings(db: Session, po: PurchaseOrder) -> list[str]:
    out = []
    if our_gstin(db, po) is None:
        out.append("GSTIN not set: add the company GSTIN before the PO is sent")
    if not po.vendor.gstin:
        taxed = [ln.product.name for ln in po.lines if Decimal(ln.gst_percent) > 0]
        taxed += [c.description or c.kind for c in po.charges if Decimal(c.gst_percent) > 0]
        if taxed:
            out.append(
                "Supplier unregistered (no GSTIN), but GST is entered on: "
                + ", ".join(taxed)
                + ". An unregistered supplier cannot charge GST."
            )
    return out


def indent_qty_text(db: Session, line: PoLine) -> str | None:
    """The PO qty in the unit it was indented in, when that differs: "20 nos"."""
    if not line.indent_line_id:
        return None
    il = db.get(IndentLine, line.indent_line_id)
    if il is None or il.unit == line.unit or not Decimal(il.base_qty):
        return None
    qty = Decimal(line.base_qty) * Decimal(il.qty) / Decimal(il.base_qty)
    return f"{qty.quantize(QTY, ROUND_HALF_UP).normalize():f} {il.unit}"
