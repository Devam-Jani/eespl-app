# ruff: noqa: E501
"""The site's material request, in place of the WhatsApp order: the site engineer asks by area and
thickness ("nodular, 280 sqm, 130 mm"); the app works out the kg and the packs from the library and
the mix design and shows the formula ("280 sqm × 10.7639 × 2.77 kg/sqft = 8,349 kg = 334 bags of
25 kg"), so a 4,345 for an 8,345 cannot slip through. The request is checked against what the
estimate still has for that area and material: more needs a reason. Planning approves (or
changes) it and it becomes an indent, the existing indent → PO flow."""

import math
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.estimate import library as lib
from app.estimate import mix as mixes
from app.estimate import service as est_svc
from app.estimate.models import Estimate, EstimateArea, MaterialRequest, MixDesign
from app.masters.models import Product

D = Decimal
ZERO = D(0)


class Refused(ValueError):
    pass


def estimate_for(db: Session, site_id: int) -> Estimate | None:
    """The site's estimate: the latest issued, else the latest draft."""
    rows = list(db.scalars(select(Estimate).where(Estimate.site_id == site_id).order_by(Estimate.id.desc())))
    return next((e for e in rows if e.status == "issued"), rows[0] if rows else None)


def work_out(db: Session, product: Product, area_sqm: Decimal, thickness_mm: Decimal | None, mix: MixDesign | None, system_id: int | None) -> tuple[Decimal, str, lib.Packs | None]:
    """The quantity (rounded up to a whole unit: material is ordered whole), its formula, its packs."""
    a = D(area_sqm)
    w = lib.wastage(product)
    waste = f" × (1 + {lib.n(w, 2)}%)" if w else ""
    if mix is not None:
        part = mixes.part_for(db, mix, product.id, thickness_mm)
        if part is None:
            raise Refused(f"{product.name} is not in {mix.name}")
        if mix.round_sqft is not None and part.unit == "kg":
            raw = a * lib.SQFT_PER_SQM * part.per_sqft * (1 + w / 100)
            how = f"{lib.n(a)} sqm × {lib.n(lib.SQFT_PER_SQM, 4)} × {lib.n(part.per_sqft, mix.round_sqft)} kg/sqft{waste}"
        else:
            raw = a * part.per_sqm * (1 + w / 100)
            how = f"{lib.n(a)} sqm × {lib.n(part.per_sqm, 4)} {part.unit}/sqm{waste}"
        how += f" ({mix.name}, {lib.n(thickness_mm or mix.thickness_mm, 1)} mm)"
    else:
        c = lib.coverage_for(db, product.id, system_id)
        if c is None:
            raise Refused(f"{product.name} has no coverage in the library: planning adds it first")
        per = lib.per_sqm(c.value, c.unit)
        raw = a * per * (1 + w / 100)
        how = f"{lib.n(a)} sqm × {lib.n(c.value, 4)} {c.unit}{waste}"
        if c.unit not in ("kg/sqm", "L/sqm", "sqm/sqm"):
            how += f" (= {lib.n(per, 4)} {product.unit}/sqm)"
    qty = D(math.ceil(raw))
    pk = lib.packs(qty, product)
    formula = f"{how} = {lib.grouped(qty)} {product.unit}" + (f" = {pk.text}" if pk else "")
    return qty, formula, pk


def left(db: Session, est: Estimate, product_id: int, area: EstimateArea | None, exclude_id: int | None = None) -> Decimal | None:
    """What the estimate still has of this material (for this area, or in all), less what the site
    asked for already (not refused)."""
    planned = ZERO
    found = False
    for lo in est_svc.worked(db, est):
        if lo.product.id != product_id:
            continue
        for r in lo.rows:
            if (area is None or r.area_id == area.id) and r.qty is not None:
                planned += r.qty
                found = True
    if not found:
        return None
    q = select(func.coalesce(func.sum(func.coalesce(MaterialRequest.approved_qty, MaterialRequest.qty)), 0)).where(
        MaterialRequest.estimate_id == est.id, MaterialRequest.product_id == product_id, MaterialRequest.status != "rejected")
    if area is not None:
        q = q.where(MaterialRequest.estimate_area_id == area.id)
    if exclude_id is not None:
        q = q.where(MaterialRequest.id != exclude_id)
    return planned - D(db.scalar(q) or 0)


def over(qty: Decimal, remaining: Decimal | None) -> bool:
    """More than the estimate has left (material is ordered whole: all that is left, rounded up,
    is not over it)."""
    return remaining is not None and qty > remaining.to_integral_value(ROUND_CEILING)


def ask(db: Session, site, *, product_id: int, area_sqm: Decimal, thickness_mm: Decimal | None, mix_design_id: int | None, estimate_area_id: int | None,
        reason: str | None, user_id) -> MaterialRequest:  # fmt: skip
    from app.material.service import next_code  # noqa: PLC0415

    product = db.get(Product, product_id)
    if product is None:
        raise Refused("Choose the material")
    if D(area_sqm) <= 0:
        raise Refused("Give the area in sqm")
    mix = db.get(MixDesign, mix_design_id) if mix_design_id else None
    if mix is not None and thickness_mm is None:
        thickness_mm = mix.thickness_mm
    est = estimate_for(db, site.id)
    area = db.get(EstimateArea, estimate_area_id) if estimate_area_id else None
    if area is not None and (est is None or area.estimate_id != est.id):
        raise Refused("That area is not in the site's estimate")
    system_id = None
    if est is not None:
        line = next((ln for ln in est_svc.lines_of(db, est) if ln.product_id == product_id), None)
        system_id = line.system_id if line else None
    qty, formula, pk = work_out(db, product, D(area_sqm), D(thickness_mm) if thickness_mm is not None else None, mix, system_id)
    remaining = left(db, est, product_id, area) if est is not None else None
    is_over = over(qty, remaining)
    if is_over and not (reason or "").strip():
        raise Refused(f"{lib.grouped(qty)} {product.unit} is more than the estimate has left ({lib.grouped(max(remaining, ZERO), 3)} {product.unit}): say why")
    reason = reason if is_over else None  # only an over request keeps a reason (not a hidden one)
    r = MaterialRequest(code=next_code(db, "MR"), site_id=site.id, estimate_id=est.id if est else None, estimate_area_id=area.id if area else None,
                        product_id=product.id, mix_design_id=mix.id if mix else None, area_sqm=D(area_sqm), thickness_mm=thickness_mm, qty=qty,
                        packs=pk.count if pk else None, formula=formula, left_before=remaining, over_reason=(reason or "").strip() or None, created_by=user_id)  # fmt: skip
    db.add(r)
    db.flush()
    return r


def approve(db: Session, r: MaterialRequest, *, qty: Decimal | None, note: str | None, user_id, required_by=None):
    """Planning approves (changing the quantity, with a note) and the indent is raised for it."""
    from app.material import service as msvc  # noqa: PLC0415
    from app.material.models import Indent, IndentLine  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    if r.status != "requested":
        raise Refused(f"{r.code} is {r.status}")
    if qty is not None and D(qty) != D(r.qty) and not (note or "").strip():
        raise Refused("Say why the quantity is changed")
    product = db.get(Product, r.product_id)
    r.approved_qty = D(qty) if qty is not None else D(r.qty)
    r.change_note = (note or "").strip() or None
    r.decided_by, r.decided_at = user_id, datetime.now(UTC)
    site = db.get(Site, r.site_id)
    store = msvc.site_store(db, site, user_id)
    pk = lib.packs(r.approved_qty, product)
    remark = f"{r.code}: {r.formula}" + (f"; changed by planning to {lib.grouped(r.approved_qty)} {product.unit}: {r.change_note}" if r.change_note else "")
    ind = Indent(code=msvc.next_code(db, "IND"), site_id=site.id, store_id=store.id, required_by=required_by, priority="normal", status="submitted",
                 remark=remark[:2000], created_by=user_id)  # fmt: skip
    ind.lines = [IndentLine(product_id=product.id, qty=r.approved_qty, unit=product.unit, base_qty=r.approved_qty, created_by=user_id,
                            remark=(f"{pk.text}. " if pk else "") + f"From {r.code}")]  # fmt: skip
    db.add(ind)
    db.flush()
    r.indent_id, r.status = ind.id, "indented"
    return ind


def reject(db: Session, r: MaterialRequest, *, note: str, user_id) -> None:
    if r.status != "requested":
        raise Refused(f"{r.code} is {r.status}")
    if not (note or "").strip():
        raise Refused("Say why it is refused")
    r.status, r.change_note, r.decided_by, r.decided_at = "rejected", note.strip(), user_id, datetime.now(UTC)
