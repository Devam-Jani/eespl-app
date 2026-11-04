# ruff: noqa: E501
"""The estimate: one area set from the measured drawing, every material line read from it.

An area gives its floor (less the cut-outs inside it) plus its periphery × the upturn height (the
area's own, else the line's system's, else the estimate's 300 mm). An area drawn wholly inside
another (a shaft, a cut-out in a terrace) is taken out of that one's floor and kept as a Misc area
with its own periphery (by default only its upturn counts): never lost, never counted twice.

A line: area × coverage × (1 + wastage) = quantity → packs, per area and in total; the coverage is
the library's for the product in the line's system, or a mix design's component at a thickness.
Every measured area on the site's drawings is in the estimate or excluded with a reason; any
other is a missed area, and the estimate says so (Dholera: 29.99 sqm measured, never estimated)."""

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.estimate import library as lib
from app.estimate import mix as mixes
from app.estimate.models import Estimate, EstimateArea, EstimateLine, MaterialRequest, MixDesign
from app.masters.models import Product, System
from app.measure import geom
from app.measure.models import MeasureArea
from app.takeoff.models import CadArea, CadFile

D = Decimal
ZERO = D(0)


class Refused(ValueError):
    pass


# --- the site's measured areas --------------------------------------------------------------------


@dataclass
class Measured:
    key: str  # measure:12, takeoff:40
    source: str
    ref_id: int
    code: str | None
    name: str
    floor_sqm: Decimal
    periphery_m: Decimal
    outline: list | None = None


def measured(db: Session, site_id: int) -> list[Measured]:
    """Every area measured on the site's drawings: Measure and bill's, and the takeoff's accepted."""
    out = [Measured(f"measure:{a.id}", "measure", a.id, a.code, a.name, D(a.area_sqm), D(a.periphery_m), a.outline)
           for a in db.scalars(select(MeasureArea).where(MeasureArea.site_id == site_id).order_by(MeasureArea.code))]  # fmt: skip
    q = select(CadArea).join(CadFile, CadFile.id == CadArea.cad_file_id).where(CadFile.site_id == site_id, CadArea.status == "accepted").order_by(CadArea.id)
    for a in db.scalars(q):
        floor = a.traced_area_sqm if a.traced_area_sqm is not None else a.label_area_sqm
        if floor is None:
            continue
        per = a.traced_perimeter_m if a.traced_perimeter_m is not None else (2 * (D(a.label_w_m) + D(a.label_l_m)) if a.label_w_m and a.label_l_m else ZERO)
        out.append(Measured(f"takeoff:{a.id}", "takeoff", a.id, None, a.name, D(floor), D(per)))
    return out


def _inside(inner: list, outer: list) -> bool:
    a, b = geom.polygon(inner), geom.polygon(outer)
    return a.area < b.area and b.buffer(1e-6).contains(a)


def _key(a: EstimateArea) -> str | None:
    if a.measure_area_id:
        return f"measure:{a.measure_area_id}"
    if a.cad_area_id:
        return f"takeoff:{a.cad_area_id}"
    return None


def areas_of(db: Session, est: Estimate) -> list[EstimateArea]:
    return list(db.scalars(select(EstimateArea).where(EstimateArea.estimate_id == est.id).order_by(EstimateArea.sort_order, EstimateArea.id)))


def add_measured(db: Session, est: Estimate, keys: list[str] | None = None) -> list[EstimateArea]:
    """Put measured areas into the estimate's area set (all not yet in it, or those keyed): an area
    inside another of the set (or of those added) becomes that one's Misc cut-out."""
    if est.site_id is None:
        raise Refused("A tender's estimate takes its areas typed in (no site drawing yet)")
    have = {k for k in (_key(a) for a in areas_of(db, est)) if k}
    found = [m for m in measured(db, est.site_id) if m.key not in have and (keys is None or m.key in keys)]
    if keys is not None and len(found) != len(set(keys) - have):
        raise Refused("That area is not measured on this site, or is in the estimate already")
    current = areas_of(db, est)
    order = max((a.sort_order for a in current), default=0)
    by_measure = {a.measure_area_id: a for a in current if a.measure_area_id and a.parent_id is None}
    outlines = {m.ref_id: m.outline for m in measured(db, est.site_id) if m.source == "measure"}
    made: list[EstimateArea] = []
    # outer areas first, so a cut-out finds its parent among the new ones too
    found.sort(key=lambda m: -m.floor_sqm)
    for m in found:
        order += 1
        parent = None
        if m.source == "measure" and m.outline:
            hosts = [(pid, outlines[pid]) for pid in by_measure if pid != m.ref_id and outlines.get(pid)]
            inside = [pid for pid, o in hosts if _inside(m.outline, o)]
            if inside:  # the smallest host holds it
                parent = min((by_measure[pid] for pid in inside), key=lambda a: D(a.floor_sqm))
        if parent is not None:
            a = EstimateArea(estimate_id=est.id, source="misc", measure_area_id=m.ref_id, parent_id=parent.id, sort_order=order, code=m.code,
                             name=f"Misc: {m.name} (cut out of {parent.code or parent.name})", floor_sqm=m.floor_sqm, periphery_m=m.periphery_m,
                             use_floor=False, use_upturn=True)  # fmt: skip
            parent.deduction_sqm = D(parent.deduction_sqm) + m.floor_sqm
        else:
            a = EstimateArea(estimate_id=est.id, source=m.source, measure_area_id=m.ref_id if m.source == "measure" else None,
                             cad_area_id=m.ref_id if m.source == "takeoff" else None, sort_order=order, code=m.code, name=m.name,
                             floor_sqm=m.floor_sqm, periphery_m=m.periphery_m)  # fmt: skip
        db.add(a)
        db.flush()
        if a.parent_id is None and a.measure_area_id:
            by_measure[a.measure_area_id] = a
            if m.outline:
                _take_cut_outs(db, a, m, outlines, current + made)
        made.append(a)
    return made


def _take_cut_outs(db: Session, host: EstimateArea, m: Measured, outlines: dict, areas: list[EstimateArea]) -> None:
    """A host added after its cut-outs (the shaft first, the terrace later): an area already in the
    set and wholly inside the new host becomes its Misc cut-out, as if it had come after it. An area
    already cut out of a larger host moves to this smaller one."""
    by_id = {x.id: x for x in areas}
    hosts = {x.parent_id for x in areas if x.parent_id}
    for x in areas:
        if x is host or x.id in hosts or not x.measure_area_id or not outlines.get(x.measure_area_id):
            continue
        old = by_id.get(x.parent_id) if x.parent_id else None
        if x.parent_id and (old is None or D(old.floor_sqm) <= m.floor_sqm):
            continue  # cut out of a smaller host already
        if not _inside(outlines[x.measure_area_id], m.outline):
            continue
        if old is not None:
            old.deduction_sqm = D(old.deduction_sqm) - D(x.floor_sqm)
            x.name = re.sub(r"^Misc: (.*) \(cut out of .*\)$", r"\1", x.name)
        x.source, x.parent_id, x.use_floor, x.use_upturn = "misc", host.id, False, True
        x.name = f"Misc: {x.name} (cut out of {host.code or host.name})"
        host.deduction_sqm = D(host.deduction_sqm) + D(x.floor_sqm)
    db.flush()


def exclude(db: Session, est: Estimate, key: str, reason: str) -> EstimateArea:
    """Leave a measured area out of the estimate, with the reason (it is no longer a missed area)."""
    if not (reason or "").strip():
        raise Refused("Say why the area is left out")
    a = next((x for x in areas_of(db, est) if _key(x) == key), None)
    if a is None:
        m = next((x for x in measured(db, est.site_id) if x.key == key), None) if est.site_id else None
        if m is None:
            raise Refused("That area is not measured on this site")
        a = EstimateArea(estimate_id=est.id, source=m.source, measure_area_id=m.ref_id if m.source == "measure" else None,
                         cad_area_id=m.ref_id if m.source == "takeoff" else None, code=m.code, name=m.name, floor_sqm=m.floor_sqm, periphery_m=m.periphery_m,
                         sort_order=max((x.sort_order for x in areas_of(db, est)), default=0) + 1)  # fmt: skip
        db.add(a)
    a.included, a.excluded_reason = False, reason.strip()
    db.flush()
    return a


def missed(db: Session, est: Estimate) -> list[Measured]:
    """Measured areas neither in the estimate nor excluded with a reason."""
    if est.site_id is None:
        return []
    have = {k for k in (_key(a) for a in areas_of(db, est)) if k}
    return [m for m in measured(db, est.site_id) if m.key not in have]


# --- the lines ------------------------------------------------------------------------------------


@dataclass
class Cov:
    per_sqm: Decimal  # the product's unit per sqm
    shown: str  # "1.8 kg/sqm (1.8–2, TDS)", or the mix's working
    coverage_id: int | None = None
    mix: str | None = None


def coverage(db: Session, ln: EstimateLine) -> Cov | None:
    if ln.mix_design_id:
        mx = db.get(MixDesign, ln.mix_design_id)
        part = mixes.part_for(db, mx, ln.product_id, ln.thickness_mm) if mx else None
        if part is None:
            return None
        shown = f"{lib.n(part.per_sqft, mx.round_sqft or 4)} {part.unit}/sqft" if part.unit == "kg" else f"{lib.n(part.per_sqm, 4)} {part.unit}/sqm"
        return Cov(part.per_sqm, f"{shown} ({mx.name} at {lib.n(ln.thickness_mm or mx.thickness_mm, 1)} mm: {part.how})", None, mx.name)
    c = lib.coverage_for(db, ln.product_id, ln.system_id)
    if c is None:
        return None
    return Cov(lib.per_sqm(c.value, c.unit), lib.label(c), c.id)


def upturn_m(db: Session, est: Estimate, a: EstimateArea, ln: EstimateLine) -> Decimal:
    if a.upturn_mm is not None:
        return D(a.upturn_mm) / 1000
    s = db.get(System, ln.system_id) if ln.system_id else None
    return D(s.upturn_mm if s is not None else est.upturn_mm) / 1000


@dataclass
class Row:
    area_id: int
    code: str | None
    name: str
    measure_area_id: int | None
    floor_sqm: Decimal  # the floor counted (less cut-outs)
    upturn_sqm: Decimal  # periphery × upturn
    base_sqm: Decimal
    qty: Decimal | None
    formula: str


@dataclass
class LineOut:
    line: EstimateLine
    product: Product
    system: str | None
    cov: Cov | None
    wastage: Decimal
    rows: list[Row] = field(default_factory=list)
    qty: Decimal | None = None
    packs: lib.Packs | None = None


def line_areas(db: Session, est: Estimate, ln: EstimateLine, areas: list[EstimateArea] | None = None) -> list[EstimateArea]:
    areas = areas if areas is not None else areas_of(db, est)
    chosen = [a for a in areas if a.included]
    if ln.area_ids:
        want = set(ln.area_ids)
        chosen = [a for a in chosen if a.id in want]
    return chosen


def work_line(db: Session, est: Estimate, ln: EstimateLine, areas: list[EstimateArea] | None = None) -> LineOut:
    p = db.get(Product, ln.product_id)
    cov = coverage(db, ln)
    w = lib.wastage(p)
    out = LineOut(ln, p, lib.system_name(db, ln.system_id), cov, w)
    total = ZERO
    for a in line_areas(db, est, ln, areas):
        floor = D(a.floor_sqm) - D(a.deduction_sqm) if a.use_floor and ln.part in ("both", "floor") else ZERO
        up_h = upturn_m(db, est, a, ln)
        up = D(a.periphery_m) * up_h if a.use_upturn and ln.part in ("both", "upturn") else ZERO
        base = floor + up
        if not base:
            continue
        bits = []
        if floor:
            bits.append(f"{lib.n(a.floor_sqm)}{f' − {lib.n(a.deduction_sqm)}' if D(a.deduction_sqm) and a.use_floor else ''}")
        if up:
            bits.append(f"{lib.n(a.periphery_m)} m × {lib.n(up_h, 3)} m")
        qty = base * cov.per_sqm * (1 + w / 100) if cov else None
        formula = f"({' + '.join(bits)}) = {lib.n(base)} sqm"
        if cov:
            formula += f" × {lib.n(cov.per_sqm, 4)} {p.unit}/sqm × (1 + {lib.n(w, 2)}%) = {lib.n(qty)} {p.unit}"
        out.rows.append(Row(a.id, a.code, a.name, a.measure_area_id, floor, up, base, qty, formula))
        if qty is not None:
            total += qty
    if cov:
        out.qty = total
        out.packs = lib.packs(total, p)
    return out


def lines_of(db: Session, est: Estimate) -> list[EstimateLine]:
    return list(db.scalars(select(EstimateLine).where(EstimateLine.estimate_id == est.id).order_by(EstimateLine.sort_order, EstimateLine.id)))


def live_worked(db: Session, est: Estimate) -> list[LineOut]:
    """The lines worked out from today's library."""
    areas = areas_of(db, est)
    return [work_line(db, est, ln, areas) for ln in lines_of(db, est)]


def worked(db: Session, est: Estimate) -> list[LineOut]:
    """The figures of this estimate: as issued once it is issued, else from today's library."""
    return _thaw(db, est) if est.snapshot else live_worked(db, est)


# --- issued figures stay as issued --------------------------------------------------------------


@dataclass
class FrozenProduct:
    """A material as it was named when the estimate was issued (what the lines need of a Product)."""

    id: int
    name: str
    unit: str


def _txt(v) -> str | None:
    return None if v is None else str(v)


def _dec(v) -> Decimal | None:
    return None if v is None else D(v)


def freeze(db: Session, est: Estimate) -> dict:
    """Every figure the library gave this estimate, at full precision, for Issue to keep."""
    lines = []
    for lo in live_worked(db, est):
        lines.append({"line_id": lo.line.id, "product_id": lo.product.id, "product": lo.product.name, "unit": lo.product.unit, "system": lo.system, "wastage": _txt(lo.wastage), "qty": _txt(lo.qty),
                      "cov": {"per_sqm": _txt(lo.cov.per_sqm), "shown": lo.cov.shown, "coverage_id": lo.cov.coverage_id, "mix": lo.cov.mix} if lo.cov else None,
                      "packs": {"count": lo.packs.count, "size": _txt(lo.packs.size), "unit": lo.packs.unit, "text": lo.packs.text} if lo.packs else None,
                      "rows": [{"area_id": r.area_id, "code": r.code, "name": r.name, "measure_area_id": r.measure_area_id, "floor_sqm": _txt(r.floor_sqm), "upturn_sqm": _txt(r.upturn_sqm),
                                "base_sqm": _txt(r.base_sqm), "qty": _txt(r.qty), "formula": r.formula} for r in lo.rows]})  # fmt: skip
    return {"lines": lines, "summary": [{**row, "qty": _txt(row["qty"])} for row in _live_summary(db, est)]}


def _thaw(db: Session, est: Estimate) -> list[LineOut]:
    by_id = {ln.id: ln for ln in lines_of(db, est)}
    out = []
    for s in est.snapshot["lines"]:
        c, p = s["cov"], s["packs"]
        out.append(LineOut(by_id[s["line_id"]], FrozenProduct(s["product_id"], s["product"], s["unit"]), s["system"],
                           Cov(D(c["per_sqm"]), c["shown"], c["coverage_id"], c["mix"]) if c else None, D(s["wastage"]),
                           [Row(r["area_id"], r["code"], r["name"], r["measure_area_id"], D(r["floor_sqm"]), D(r["upturn_sqm"]), D(r["base_sqm"]), _dec(r["qty"]), r["formula"]) for r in s["rows"]],
                           _dec(s["qty"]), lib.Packs(p["count"], D(p["size"]), p["unit"], p["text"]) if p else None))  # fmt: skip
    return out


def next_version(db: Session, est: Estimate) -> Estimate | None:
    return db.scalar(select(Estimate).where(Estimate.revises_id == est.id))


def library_changes(db: Session, est: Estimate) -> list[dict]:
    """Where today's library would give an issued estimate other figures: each line, as issued and now."""
    if not est.snapshot:
        return []
    now = {lo.line.id: lo for lo in live_worked(db, est)}
    out = []
    for lo in worked(db, est):
        cur = now.get(lo.line.id)
        if cur is None:
            continue
        was_cov, now_cov = lo.cov.per_sqm if lo.cov else None, cur.cov.per_sqm if cur.cov else None
        was_pack, now_pack = lo.packs.text if lo.packs else None, cur.packs.text if cur.packs else None
        if (was_cov, lo.wastage, lo.qty, was_pack) == (now_cov, cur.wastage, cur.qty, now_pack):
            continue
        out.append({"product": lo.product.name, "unit": lo.product.unit, "issued_qty": lo.qty, "library_qty": cur.qty, "issued_packs": was_pack, "library_packs": now_pack,
                    "issued_coverage": lo.cov.shown if lo.cov else None, "library_coverage": cur.cov.shown if cur.cov else None})  # fmt: skip
    return out


def versions_back(db: Session, est: Estimate) -> list[int]:
    """This estimate's id and those of the versions before it."""
    ids = [est.id]
    cur = est
    while cur.revises_id is not None and cur.revises_id not in ids:
        cur = db.get(Estimate, cur.revises_id)
        if cur is None:
            break
        ids.append(cur.id)
    return ids


def area_back(db: Session, area: EstimateArea) -> list[int]:
    """This area's id and the same area's in the versions before."""
    ids = [area.id]
    cur = area
    while cur.copied_from_id is not None and cur.copied_from_id not in ids:
        cur = db.get(EstimateArea, cur.copied_from_id)
        if cur is None:
            break
        ids.append(cur.id)
    return ids


def revise(db: Session, est: Estimate, user_id) -> Estimate:
    """The next version: a draft with this one's areas and lines, on today's library. This version
    stays as issued; it goes on being the site's estimate until the new one is issued."""
    if est.status != "issued":
        raise Refused(f"{est.code} is still a draft: change it directly")
    later = next_version(db, est)
    if later is not None:
        raise Refused(f"{est.code} has a next version already: {later.code}")
    version = est.version + 1
    new = Estimate(code=f"{est.code.split('-V')[0]}-V{version}", site_id=est.site_id, tender_id=est.tender_id, title=est.title, upturn_mm=est.upturn_mm, note=est.note,
                   is_demo=est.is_demo, version=version, revises_id=est.id, created_by=user_id)  # fmt: skip
    db.add(new)
    db.flush()
    skip = {"id", "estimate_id", "parent_id", "copied_from_id"}
    made: dict[int, EstimateArea] = {}
    olds = areas_of(db, est)
    for a in olds:
        fields = {c.key: getattr(a, c.key) for c in EstimateArea.__mapper__.column_attrs if c.key not in skip}
        made[a.id] = EstimateArea(estimate_id=new.id, copied_from_id=a.id, **fields)
        db.add(made[a.id])
    db.flush()
    for a in olds:
        if a.parent_id:
            made[a.id].parent_id = made[a.parent_id].id
    for ln in lines_of(db, est):
        fields = {c.key: getattr(ln, c.key) for c in EstimateLine.__mapper__.column_attrs if c.key not in {"id", "estimate_id", "area_ids"}}
        ids = [made[i].id for i in ln.area_ids if i in made] if ln.area_ids else ln.area_ids
        db.add(EstimateLine(estimate_id=new.id, area_ids=ids, **fields))
    db.flush()
    return new


def summary(db: Session, est: Estimate) -> list[dict]:
    """Per material: the total of its lines, its packs (rounded up once, on the total); as issued
    once the estimate is issued."""
    if est.snapshot:
        return [{**row, "qty": D(row["qty"])} for row in est.snapshot["summary"]]
    return _live_summary(db, est)


def _live_summary(db: Session, est: Estimate) -> list[dict]:
    by: dict[int, dict] = {}
    for lo in live_worked(db, est):
        row = by.setdefault(lo.product.id, {"product_id": lo.product.id, "product": lo.product.name, "unit": lo.product.unit, "qty": ZERO, "complete": True})
        if lo.qty is None:
            row["complete"] = False
        else:
            row["qty"] += lo.qty
    for row in by.values():
        pk = lib.packs(row["qty"], db.get(Product, row["product_id"]))
        row["packs"] = pk.text if pk else None
        row["pack_count"] = pk.count if pk else None
    return list(by.values())


# --- what the site was sent and used, against the estimate -----------------------------------------


def usage(db: Session, site_id: int, product_id: int, until: datetime | None = None) -> dict:
    """Sent to the site's store (received, transferred in, opening), returned (transferred out),
    still in stock; used = sent − returned − stock (as the RA 16 reconciliation)."""
    from app.material.models import StockLedger, Store  # noqa: PLC0415

    store = db.scalar(select(Store).where(Store.site_id == site_id))
    sent = back = stock = ZERO
    if store is not None:
        q = select(StockLedger.ref_type, func.coalesce(func.sum(StockLedger.qty), 0)).where(StockLedger.store_id == store.id, StockLedger.product_id == product_id)
        if until is not None:
            q = q.where(StockLedger.at <= until)
        got = {k: D(v) for k, v in db.execute(q.group_by(StockLedger.ref_type))}
        sent = got.get("transfer_in", ZERO) + got.get("grn", ZERO) + got.get("opening", ZERO)
        back = -got.get("transfer_out", ZERO)
        stock = sum(got.values(), ZERO)
    return {"sent": sent, "returned": back, "stock": stock, "used": sent - back - stock, "store": store is not None}


def balance(db: Session, est: Estimate) -> list[dict]:
    """Per material: needed (the estimate), asked for by the site, sent, used, left (needed − used)."""
    out = []
    for row in summary(db, est):
        asked = D(db.scalar(select(func.coalesce(func.sum(func.coalesce(MaterialRequest.approved_qty, MaterialRequest.qty)), 0)).where(
            MaterialRequest.estimate_id.in_(versions_back(db, est)), MaterialRequest.product_id == row["product_id"], MaterialRequest.status != "rejected")) or 0)  # fmt: skip
        u = usage(db, est.site_id, row["product_id"]) if est.site_id else {"sent": ZERO, "returned": ZERO, "stock": ZERO, "used": ZERO}
        out.append({**row, "requested": asked, "sent": u["sent"], "returned": u["returned"], "stock": u["stock"], "used": u["used"], "left": row["qty"] - u["used"]})
    return out


def until_end(day) -> datetime:
    return datetime.combine(day, time.max).astimezone()
