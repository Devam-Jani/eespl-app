# ruff: noqa: E501  (the row dicts read better unwrapped)
"""From the drawing to the quotation and its rate working, every quantity traceable to the drawing.

1. The drawing's mapped areas (the takeoff: a place and an area type confirmed by a person) give
   their quantities by one rule set (estimate.rules): the floor less its cut-outs, the upturn as
   periphery × height (the area's own, else its type's, else the system's, else the default), a
   sunken area's side walls, a vertical item's wall area (length × the storey height).
2. A run groups them by area type; each type's key points (spec.keypoints: the area, sunk or
   exposed, the client's spec line when attached) rank every brand's option (spec.suggest), its
   default system pre-ticked. An area not mapped, or a type with nothing picked, blocks the run
   until picked or left out with a reason.
3. Make: a draft quotation (items = area types, lines = the picks with the drawing's quantities),
   its rate working built from the picks (costing.working: consumption, wastage, prices with
   freight, labour, margin on the selling price), and the working's rates sent to the lines. A run
   on a newer revision makes the next revision of that quotation and says what changed per line.
4. The review grid: every cell (qty, consumption, price, freight, wastage, labour, margin)
   editable, marked "changed by user" with who and when, and back to the calculated figure.
Nothing is sent to a client here."""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.costing import working
from app.costing.models import RateGroup, RateGroupLine, RateGroupProduct
from app.drawquote.models import (
    DrawQuote,
    DrawQuoteEdit,
    DrawQuoteExclusion,
    DrawQuoteItem,
    DrawQuotePick,
    QuoteLineArea,
)
from app.estimate import rules
from app.masters.models import Product, System, SystemOption
from app.quotations.models import Quotation, QuotationItem, QuotationLine
from app.spec import keypoints, suggest
from app.takeoff.models import CadArea, CadFile

D = Decimal
ZERO = D(0)
SQFT_PER_SQM = rules.SQFT_PER_SQM
QTY = D("0.001")
MAPPED = ("mapped", "accepted")
# the upturn when nothing else says it: exposed and wet areas turn up 300 mm; a raft, a pit's
# floor or a wall does not
DEFAULT_UPTURN_MM = {"terrace": 300, "podium": 300, "balcony": 300, "kitchen": 300, "toilet": 300, "planter": 300, "oh_tank": 0, "ug_tank": 0,
                     "lift_pit": 0, "raft": 0, "retaining_wall": 0, "swimming_pool": 0, "sump": 0}  # fmt: skip
WALL_KINDS = {"retaining_wall"}  # quoted as a wall: length × the storey height
KIND_WORDS = [("retaining_wall", r"RETAINING|BASEMENT\s*WALL|R\.?W\b"), ("raft", r"RAFT"), ("lift_pit", r"LIFT\s*(PIT|WELL)"), ("sump", r"SUMP|STP"),
              ("ug_tank", r"U\.?G\.?\s*TANK|UNDERGROUND"), ("oh_tank", r"O\.?H\.?W?\.?T|OVERHEAD|WATER\s*TANK"), ("podium", r"PODIUM"), ("planter", r"PLANTER"),
              ("terrace", r"TERRACE|ROOF"), ("toilet", r"TOILET|BATH|W\.?C\b|WASH"), ("kitchen", r"KITCHEN"), ("balcony", r"BALCONY|VERANDAH"),
              ("swimming_pool", r"POOL")]  # fmt: skip


class Blocked(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# --- the areas and their quantities ---------------------------------------------------------------


def kind_of(name: str | None) -> str | None:
    import re  # noqa: PLC0415

    for k, pat in KIND_WORDS:
        if re.search(pat, (name or "").upper()):
            return k
    return None


@dataclass
class AreaRow:
    area: CadArea
    floor: str | None
    qty: rules.AreaQty
    upturn_from: str
    kind: str | None

    @property
    def total_sqm(self) -> Decimal:
        return self.qty.total_sqm

    def formula(self) -> str:
        return self.qty.formula(f"{self.area.name}{f' ({self.floor})' if self.floor else ''}")


def storey_height(db: Session, site_id: int, level: int | None) -> Decimal:
    """The height of a floor from the building model's levels (the drawing, typed, or the 3.0 m
    default)."""
    from app.building import service as building  # noqa: PLC0415

    m = building.current(db, site_id)
    if m is not None:
        for f in building.elevations(m.data or {}):
            if f.get("level") == level or (level is None and f.get("level", 1) < 0):
                return D(str(f["height_m"]))
    return D("3.0")


def area_row(db: Session, cad: CadFile, a: CadArea, system: System | None = None) -> AreaRow:
    from app.survey.models import AreaType  # noqa: PLC0415
    from app.takeoff import service as takeoff  # noqa: PLC0415

    at = db.get(AreaType, a.area_type_id) if a.area_type_id else None
    kind = kind_of(at.name if at else None) or kind_of(a.name)
    _tower, floor, number = takeoff.floor_of(db, a.node_id)
    floor = floor or a.floor_label or a.plan
    floor_sqm = takeoff.area_sqm(a) or ZERO
    per = a.traced_perimeter_m
    if per is None and a.label_w_m and a.label_l_m:
        per = 2 * (D(a.label_w_m) + D(a.label_l_m))
    per = D(per or 0) + D(a.holes_perimeter_m or 0)
    sunk = D(a.sunk_m or 0)
    if kind in WALL_KINDS:  # a wall drawn as its plan outline: its length is half the outline's run
        length = D(a.label_l_m) if a.label_l_m else (D(a.traced_perimeter_m or 0) / 2)
        q = rules.area_quantity(
            0, 0, wall_length_m=length, wall_height_m=storey_height(db, cad.site_id, number)
        )
        return AreaRow(a, floor, q, "a wall: its height", kind)
    up_m, up_from = rules.upturn_height(a.upturn_mm, at.default_upturn_mm if at else None, system.upturn_mm if system else None,
                                        DEFAULT_UPTURN_MM.get(kind or "", 0), sunk)  # fmt: skip
    q = rules.area_quantity(floor_sqm, per, cutout_sqm=a.holes_sqm or 0, upturn_m=up_m, sunk_m=sunk)
    return AreaRow(a, floor, q, up_from, kind)


def mapped_areas(db: Session, cad: CadFile) -> list[CadArea]:
    return list(
        db.scalars(
            select(CadArea)
            .where(
                CadArea.cad_file_id == cad.id,
                CadArea.status.in_(MAPPED),
                CadArea.area_type_id.is_not(None),
            )
            .order_by(CadArea.id)
        )
    )


def open_areas(db: Session, run: DrawQuote) -> list[CadArea]:
    """The drawing's areas neither mapped (a place and an area type) nor left out: each blocks the
    run until a person maps it or leaves it out with a reason."""
    out = set(
        db.scalars(
            select(DrawQuoteExclusion.cad_area_id).where(DrawQuoteExclusion.run_id == run.id)
        )
    )
    return [a for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == run.cad_file_id).order_by(CadArea.id))
            if a.id not in out and a.status not in ("ignored",) and not (a.status in MAPPED and a.area_type_id)]  # fmt: skip


def excluded_ids(db: Session, run: DrawQuote) -> set[int]:
    return set(
        db.scalars(
            select(DrawQuoteExclusion.cad_area_id).where(DrawQuoteExclusion.run_id == run.id)
        )
    )


def item_areas(db: Session, run: DrawQuote, item: DrawQuoteItem) -> list[CadArea]:
    cad = db.get(CadFile, run.cad_file_id)
    out = excluded_ids(db, run)
    return [
        a for a in mapped_areas(db, cad) if a.area_type_id == item.area_type_id and a.id not in out
    ]


def item_rows(
    db: Session, run: DrawQuote, item: DrawQuoteItem, system: System | None = None
) -> list[AreaRow]:
    cad = db.get(CadFile, run.cad_file_id)
    return [area_row(db, cad, a, system) for a in item_areas(db, run, item)]


# --- the run ---------------------------------------------------------------------------------------


def chips_for(db: Session, item: DrawQuoteItem, rows: list[AreaRow]) -> list[dict]:
    """The area type's key points: its name, sunk or exposed, and the client's spec line."""
    sunk = max((r.qty.sunk_m for r in rows), default=ZERO)
    kinds = {r.kind for r in rows}
    words = [f"{item.name} waterproofing"]
    if sunk:
        words.append(f"{int(sunk * 1000)} mm sunk")
    if kinds & {"terrace", "podium"}:
        words.append("exposed")
    if item.spec_text:
        words.append(item.spec_text)
    text = ". ".join(words)
    unit = "sqm"
    return keypoints.parse(
        text, unit, sum((r.total_sqm for r in rows), ZERO), keypoints.known_brands(db)
    )


def start(
    db: Session, site_id: int, cad: CadFile, client_id: int | None, unit: str, user_id
) -> DrawQuote:
    """A run on the drawing revision: one item per area type mapped on it, each with its default
    system's default brand option pre-ticked; a later run takes the earlier run's picks."""
    from app.survey.models import AreaType  # noqa: PLC0415

    prev = db.scalar(
        select(DrawQuote)
        .where(DrawQuote.site_id == site_id, DrawQuote.status == "made")
        .order_by(DrawQuote.id.desc())
        .limit(1)
    )
    run = DrawQuote(site_id=site_id, cad_file_id=cad.id, client_id=client_id or (prev.client_id if prev else None), unit=unit,
                    previous_id=prev.id if prev else None, created_by=user_id)  # fmt: skip
    db.add(run)
    db.flush()
    seen: list[int] = []
    for a in mapped_areas(db, cad):
        if a.area_type_id not in seen:
            seen.append(a.area_type_id)
    before = {i.area_type_id: i for i in (prev.items if prev else [])}
    for n, tid in enumerate(seen):
        at = db.get(AreaType, tid)
        item = DrawQuoteItem(run_id=run.id, area_type_id=tid, name=at.name, sort_order=n)
        old = before.get(tid)
        if old is not None:
            item.spec_text = old.spec_text
            item.picks = [
                DrawQuotePick(
                    system_id=p.system_id,
                    option_id=p.option_id,
                    product_id=p.product_id,
                    consumption=p.consumption,
                    sort_order=p.sort_order,
                )
                for p in old.picks
            ]
        elif at.default_system_id:
            s = db.get(System, at.default_system_id)
            o = s.default_option() if s else None
            if s is not None:
                item.picks = [DrawQuotePick(system_id=s.id, option_id=o.id if o else None)]
        run.items.append(item)
    db.flush()
    return run


def blockers(db: Session, run: DrawQuote) -> list[str]:
    out = [
        f"{a.name}{f' ({a.plan})' if a.plan else ''} is not mapped: map it to a place and an area type, or leave it out with a reason"
        for a in open_areas(db, run)
    ]
    for item in run.items:
        if item.excluded_reason:
            continue
        if not item.picks:
            out.append(
                f"{item.name}: pick a system or a product, or leave the area type out with a reason"
            )
        for p in item.picks:
            if p.product_id and p.consumption is None:
                out.append(
                    f"{item.name}: give the consumption of {db.get(Product, p.product_id).name}"
                )
    return out


def pick_label(db: Session, p: DrawQuotePick) -> tuple[str, str | None]:
    """(the line's words, the brand)."""
    if p.system_id:
        s = db.get(System, p.system_id)
        o = db.get(SystemOption, p.option_id) if p.option_id else s.default_option()
        rows = suggest.bom_rows(s, o.id if o else None, {})
        steps = "; ".join(
            f"{suggest.STEP_LABEL.get(r['step'], r['step'])}: {r['product']}" for r in rows
        )
        return f"{s.name}{f' ({o.brand})' if o else ''}" + (f". {steps}" if steps else ""), (
            o.brand if o else None
        )
    pr = db.get(Product, p.product_id)
    return pr.name, pr.brand


# --- make the quotation ------------------------------------------------------------------------------


@dataclass
class Made:
    quotation: Quotation
    changes: list[dict] = field(default_factory=list)


def _line_qty(run: DrawQuote, total_sqm: Decimal) -> Decimal:
    return (total_sqm * SQFT_PER_SQM if run.unit == "sqft" else total_sqm).quantize(QTY)


def _description(
    db: Session, run: DrawQuote, item: DrawQuoteItem, p: DrawQuotePick, total_sqm: Decimal
) -> str:
    words, _brand = pick_label(db, p)
    both = f"{rules.n(total_sqm)} sqm = {rules.n(total_sqm * SQFT_PER_SQM, 1)} sq ft"
    return f"{item.name}: {words}\nQuantity from the drawing: {both} (see the annexure)."


def _trace(db: Session, line: QuotationLine, run: DrawQuote, rows: list[AreaRow]) -> None:
    for x in list(
        db.scalars(select(QuoteLineArea).where(QuoteLineArea.quotation_line_id == line.id))
    ):
        db.delete(x)
    for r in rows:
        q = r.qty
        db.add(QuoteLineArea(quotation_line_id=line.id, cad_area_id=r.area.id, cad_file_id=run.cad_file_id, area_key=r.area.key, area_name=r.area.name[:200],
                             floor=(r.floor or None) and r.floor[:200], floor_sqm=q.floor_sqm, cutout_sqm=q.cutout_sqm, periphery_m=q.periphery_m,
                             upturn_m=q.upturn_m, upturn_from=r.upturn_from[:40], sunk_m=q.sunk_m, wall_length_m=q.wall_length_m, wall_height_m=q.wall_height_m,
                             total_sqm=q.total_sqm.quantize(QTY), formula=r.formula()[:2000]))  # fmt: skip


def _group_for(
    db: Session, w, line: QuotationLine, item: DrawQuoteItem, p: DrawQuotePick, user_id
) -> RateGroup:
    """The line's main item in the rate working, built from the pick (or the one copied from the
    previous revision's working)."""
    g = db.get(RateGroup, p.group_id) if p.group_id else None
    if g is not None and g.working_id == w.id:
        return g
    have = db.scalar(
        select(RateGroupLine)
        .join(RateGroup)
        .where(RateGroupLine.quotation_line_id == line.id, RateGroup.working_id == w.id)
    )
    if have is not None:
        return db.get(RateGroup, have.group_id)
    g = RateGroup(
        working_id=w.id,
        sort_order=max((x.sort_order for x in w.groups), default=0) + 1,
        name=f"{item.name}"[:200],
        created_by=user_id,
    )
    g.lines = [RateGroupLine(quotation_line_id=line.id)]
    db.add(g)
    db.flush()
    if p.system_id:
        g.system_id, g.system_option_id = p.system_id, p.option_id
        try:
            working.init_from_system(db, g, f"{item.name} {item.spec_text or ''}")
        except working.WorkingUnitError as exc:  # a work item per nos: said on the main item
            g.note = str(exc)
    else:
        g.products = [
            working.new_product(
                db, p.product_id, p.consumption, 0, "typed for the drawing's quotation"
            )
        ]
    return g


def make(db: Session, run: DrawQuote, principal) -> Made:
    """The draft quotation (or the next revision of the earlier run's), its rate working, the
    drawing's quantities on its lines with the areas behind them, the working's rates on them."""
    if run.status == "made":
        raise Blocked(
            [
                "This run has made its quotation already: start a new run for a new revision of the drawing"
            ]
        )
    reasons = blockers(db, run)
    if reasons:
        raise Blocked(reasons)
    prev = db.get(DrawQuote, run.previous_id) if run.previous_id else None
    prev_q = db.get(Quotation, prev.quotation_id) if prev and prev.quotation_id else None
    if (
        prev_q is not None and not prev_q.is_latest
    ):  # a revision made since by hand: from the latest
        prev_q = db.scalar(
            select(Quotation).where(Quotation.code == prev_q.code, Quotation.is_latest.is_(True))
        )
    old_lines: dict[
        tuple, QuotationLine
    ] = {}  # the previous run's pick -> its line in the new revision
    old_rows: dict[int, dict[str, Decimal]] = {}
    if prev_q is not None:
        from app.quotations import service as qsvc  # noqa: PLC0415

        q = qsvc.copy_quotation(db, prev_q, principal.user.id)
        by_old = {}
        for oi, ni in zip(prev_q.items, q.items, strict=False):
            for ol, nl in zip(oi.lines, ni.lines, strict=False):
                by_old[ol.id] = nl
        for item in prev.items:
            for p in item.picks:
                if p.quotation_line_id in by_old:
                    old_lines[(item.area_type_id, p.system_id, p.option_id, p.product_id)] = by_old[
                        p.quotation_line_id
                    ]
                    old_rows[by_old[p.quotation_line_id].id] = {
                        r.area_key: D(r.total_sqm)
                        for r in db.scalars(
                            select(QuoteLineArea).where(
                                QuoteLineArea.quotation_line_id == p.quotation_line_id
                            )
                        )
                    }
    else:
        from app.quotations.routers import QuotationIn, quotation_shell  # noqa: PLC0415
        from app.sites.models import Site  # noqa: PLC0415

        site = db.get(Site, run.site_id)
        q, _preset = quotation_shell(
            db,
            QuotationIn(
                client_id=run.client_id or getattr(site, "client_id", None), project=site.name
            ),
            principal,
        )
        q.site_id = site.id
        db.flush()
    w = working.for_quotation(db, q, principal.user.id)
    items_by_type = {i.area_type_id: i for i in q.items if i.area_type_id}
    changes: list[dict] = []
    kept_lines: set[int] = set()
    for n, item in enumerate(run.items):
        if item.excluded_reason:
            continue
        qi = items_by_type.get(item.area_type_id)
        if qi is None:
            qi = QuotationItem(
                quotation_id=q.id,
                sort_order=len(q.items) + n,
                name=item.name[:200],
                budget_title=item.name,
                area_type_id=item.area_type_id,
                options=[],
            )
            q.items.append(qi)
            db.flush()
        item.quotation_item_id = qi.id
        several = len(item.picks) > 1
        for k, p in enumerate(item.picks):
            system = db.get(System, p.system_id) if p.system_id else None
            rows = item_rows(db, run, item, system)
            total = sum((r.total_sqm for r in rows), ZERO)
            line = old_lines.get((item.area_type_id, p.system_id, p.option_id, p.product_id))
            old_qty = line.qty if line is not None else None
            if line is None:
                line = QuotationLine(item_id=qi.id, sort_order=k, description="", uom=run.unit)
                qi.lines.append(line)
                db.flush()
            line.option = str(k + 1) if several else None
            line.description = _description(db, run, item, p, total)
            line.uom, line.qty = run.unit, _line_qty(run, total)
            line.system_id, line.system_option_id = p.system_id, p.option_id
            p.quotation_line_id = line.id
            kept_lines.add(line.id)
            g = _group_for(db, w, line, item, p, principal.user.id)
            p.group_id = g.id
            working.work(db, g)
            if g.rate_sqm is not None:  # a price missing: no rate yet (the send checks say so)
                working.apply_line(
                    db,
                    g,
                    next(x for x in g.lines if x.quotation_line_id == line.id),
                    working.step_shares(db, w, g),
                )
            new_rows = {r.area.key: r.total_sqm.quantize(QTY) for r in rows}
            _trace(db, line, run, rows)
            if prev_q is not None:
                before = old_rows.get(line.id, {})
                areas = {"added": sorted(set(new_rows) - set(before)), "removed": sorted(set(before) - set(new_rows)),
                         "resized": sorted(k2 for k2 in set(new_rows) & set(before) if new_rows[k2] != before[k2])}  # fmt: skip
                if old_qty is None or D(old_qty) != line.qty or any(areas.values()):
                    changes.append(
                        {
                            "line_id": line.id,
                            "item": item.name,
                            "line": line.description.split("\n")[0][:120],
                            "old_qty": old_qty,
                            "new_qty": line.qty,
                            "areas": areas,
                        }
                    )
    if prev_q is not None:  # lines whose area type or pick is no longer quoted
        for qi in q.items:
            for ln in list(qi.lines):
                if ln.id not in kept_lines:
                    changes.append(
                        {
                            "line_id": None,
                            "item": qi.name,
                            "line": ln.description.split("\n")[0][:120],
                            "old_qty": ln.qty,
                            "new_qty": None,
                            "areas": {},
                        }
                    )
                    qi.lines.remove(ln)
    # kept as JSON: the quantities as text
    stored = [
        {
            **ch,
            "old_qty": None if ch["old_qty"] is None else str(ch["old_qty"]),
            "new_qty": None if ch["new_qty"] is None else str(ch["new_qty"]),
        }
        for ch in changes
    ]
    run.status, run.quotation_id, run.changes = "made", q.id, stored
    q.notes = (
        (q.notes or "") + f"\nMade from the drawing (run {run.id}, drawing file {run.cad_file_id})."
    ).strip()
    db.flush()
    return Made(q, changes)


# --- the review grid -------------------------------------------------------------------------------


def _edits(db: Session, run: DrawQuote) -> dict[tuple[str, int], DrawQuoteEdit]:
    return {
        (e.kind, e.ref_id): e
        for e in db.scalars(select(DrawQuoteEdit).where(DrawQuoteEdit.run_id == run.id))
    }


def grid(db: Session, run: DrawQuote) -> list[dict]:
    """Per area type and pick: the line's quantity, and per product its consumption, price,
    freight, wastage; the main item's labour and margin; the line's rate; which cells a person
    changed (who, when, the calculated figure)."""
    from app.models import User  # noqa: PLC0415

    edits = _edits(db, run)

    def cell(kind: str, ref: int, value) -> dict:
        e = edits.get((kind, ref))
        who = db.get(User, e.by) if e and e.by else None
        return {"kind": kind, "ref": ref, "value": value, "changed": e is not None, "calculated": e.calculated if e else None,
                "by": who.full_name if who else None, "at": e.at if e else None}  # fmt: skip

    out = []
    for item in run.items:
        for p in item.picks:
            line = db.get(QuotationLine, p.quotation_line_id) if p.quotation_line_id else None
            g = db.get(RateGroup, p.group_id) if p.group_id else None
            if line is None or g is None:
                continue
            label, brand = pick_label(db, p)
            out.append({
                "item": item.name, "pick_id": p.id, "label": label.split(". ")[0], "brand": brand, "line_id": line.id, "unit": line.uom, "option": line.option,
                "qty": cell("qty", line.id, line.qty), "rate": line.rate, "group_id": g.id, "rate_sqm": g.rate_sqm, "cost_sqm": g.cost_sqm,
                "wastage": cell("wastage", g.id, g.wastage_percent), "labour": cell("labour", g.id, g.labour_used_sqft), "margin": cell("margin", g.id, g.margin_percent),
                "products": [{"id": rp.id, "product": rp.product.name, "unit": rp.product.unit, "consumption": cell("consumption", rp.id, rp.consumption),
                              "price": cell("price", rp.id, rp.price), "freight": cell("freight", rp.id, rp.freight_used), "source": rp.consumption_source}
                             for rp in g.products],
            })  # fmt: skip
    return out


def _target(db: Session, kind: str, ref: int):
    if kind == "qty":
        return db.get(QuotationLine, ref), "qty"
    if kind in ("consumption", "price", "freight"):
        return db.get(RateGroupProduct, ref), {
            "consumption": "consumption",
            "price": "price",
            "freight": "freight_used",
        }[kind]
    return db.get(RateGroup, ref), {
        "wastage": "wastage_percent",
        "labour": "labour_used_sqft",
        "margin": "margin_percent",
    }[kind]


def _belongs(db: Session, run: DrawQuote, kind: str, obj) -> bool:
    lines = {p.quotation_line_id for i in run.items for p in i.picks}
    groups = {p.group_id for i in run.items for p in i.picks}
    if kind == "qty":
        return obj.id in lines
    if kind in ("consumption", "price", "freight"):
        return obj.group_id in groups
    return obj.id in groups


def set_cell(
    db: Session, run: DrawQuote, kind: str, ref: int, value: Decimal | None, user_id
) -> None:
    """A cell changed by a person (value None: back to the calculated figure), and what follows:
    the main item worked again, its rate on the line."""
    obj, attr = _target(db, kind, ref)
    if obj is None or not _belongs(db, run, kind, obj):
        raise ValueError("That cell is not part of this quotation")
    if value is not None and value < 0:
        raise ValueError("A figure cannot be below 0")
    if kind == "margin" and value is not None and value >= 100:
        raise ValueError("A margin on the selling price must be below 100 %")
    e = db.scalar(
        select(DrawQuoteEdit).where(
            DrawQuoteEdit.run_id == run.id, DrawQuoteEdit.kind == kind, DrawQuoteEdit.ref_id == ref
        )
    )
    if value is None:
        if e is None:
            return
        restored = D(e.calculated) if e.calculated not in (None, "None") else None
        setattr(obj, attr, restored)
        db.delete(e)
    else:
        if e is None:
            e = DrawQuoteEdit(
                run_id=run.id, kind=kind, ref_id=ref, calculated=str(getattr(obj, attr))
            )
            db.add(e)
        e.value, e.by = str(value), user_id
        from datetime import UTC, datetime  # noqa: PLC0415

        e.at = datetime.now(UTC)
        setattr(obj, attr, value)
        if (
            kind == "consumption"
            and obj.default_consumption is not None
            and value != obj.default_consumption
        ):
            obj.consumption_reason = "changed by user in the drawing's quotation"
    db.flush()
    groups = (
        [obj]
        if kind in ("wastage", "labour", "margin")
        else ([db.get(RateGroup, obj.group_id)] if kind != "qty" else [])
    )
    if kind == "qty":
        return
    for g in groups:
        working.work(db, g)
        w = db.get(working.RateWorking, g.working_id)
        for gl in g.lines if g.rate_sqm is not None else []:
            working.apply_line(db, g, gl, working.step_shares(db, w, g))
    db.flush()


def line_areas(db: Session, line_id: int) -> list[QuoteLineArea]:
    return list(
        db.scalars(
            select(QuoteLineArea)
            .where(QuoteLineArea.quotation_line_id == line_id)
            .order_by(QuoteLineArea.id)
        )
    )


# --- check against the drawing ----------------------------------------------------------------------


def check(db: Session, cad: CadFile) -> dict:
    """Nothing silently left out: per plan, the plan's floor area (the building model's outline
    for it, else the largest closed shape on that plan) against the sum of the mapped areas on it;
    the closed shapes on the drawing that are no area's outline or cut-out; the labels not mapped."""
    from app.building import service as building  # noqa: PLC0415
    from app.takeoff import geometry  # noqa: PLC0415
    from app.takeoff import service as takeoff  # noqa: PLC0415

    u = float(cad.unit_m or 0.001)
    areas = list(db.scalars(select(CadArea).where(CadArea.cad_file_id == cad.id)))
    used = []
    for a in areas:
        if a.outline:
            used.append(a.outline)
        used.extend(a.holes or [])
    used_keys = {tuple(map(tuple, p)) for p in used}
    shapes = takeoff._shapes(cad)
    unused = [p for p in shapes if tuple(map(tuple, p)) not in used_keys]
    m = building.current(db, cad.site_id)
    outlines = (
        {t.get("plan"): t.get("outline") for t in ((m.data or {}).get("floor_types") or [])}
        if m
        else {}
    )
    plans: dict[str, dict] = {}
    for a in areas:
        p = plans.setdefault(
            a.plan or "(no plan)",
            {
                "plan": a.plan or "(no plan)",
                "mapped_sqm": ZERO,
                "areas": 0,
                "mapped": 0,
                "plan_sqm": None,
                "plan_from": None,
            },
        )
        p["areas"] += 1
        if a.status in MAPPED and a.area_type_id:
            p["mapped"] += 1
            p["mapped_sqm"] += takeoff.area_sqm(a) or ZERO
    for name, p in plans.items():
        o = outlines.get(name)
        if o:
            p["plan_sqm"], p["plan_from"] = (
                D(str(round(geometry.area([tuple(x) for x in o]) * u * u, 2))),
                "the building model's outline",
            )
    big = sorted(unused, key=lambda p: -geometry.area([tuple(x) for x in p]))
    return {
        "plans": [p | {"mapped_sqm": p["mapped_sqm"].quantize(D("0.01"))} for p in plans.values()],
        "unmapped_labels": [
            {"id": a.id, "name": a.name, "plan": a.plan, "status": a.status}
            for a in areas
            if not (a.status in MAPPED and a.area_type_id) and a.status != "ignored"
        ],
        "closed_unused": [
            {"sqm": round(geometry.area([tuple(x) for x in p]) * u * u, 2), "points": len(p)}
            for p in big[:50]
        ],
        "closed_unused_count": len(unused),
    }
