# ruff: noqa: E501  (the check rows read better unwrapped)
"""Every option that meets a line's key points, of every brand: the consumption master's work
items and their brand options (each with its BOM), and data-sheet products with no BOM yet.

Ranking: the make the line names first; the same system type and use area; every property minimum
met (a product with no value for it is "not stated in TDS", ranked after those that meet it,
never hidden); the consumption at least the line's kg per sqm or the DFT it asks (DFT converted
with the data sheet's density, solids or kg per mm; otherwise flagged); then past use on our
quotations and won tenders; then price.

Picking an option builds the line's main item in the rate working from that brand option
(costing.working: init_from_system, pick_consumption, work): no second engine. The client's
minimum still wins over the BOM figure there."""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.costing import working
from app.costing.models import RateGroup, RateGroupLine, RateWorking
from app.masters.models import Product, System, SystemComponent, SystemOption
from app.masters.rate import MissingPriceError, system_rate
from app.spec import keypoints, tds, vocab
from app.spec.models import SpecPick, SpecPoints, TdsDoc, TdsFact
from app.spec.vocab import RFT_PER_RMT, SQFT_PER_SQM, D

MAX_OPTIONS = 12
MAX_PRODUCTS = 6
YES, NO, NOT_STATED = "yes", "no", "not_stated"


# --- the line --------------------------------------------------------------------------------------


def line_of(db: Session, kind: str, line_id: int):
    from app.quotations.models import QuotationLine  # noqa: PLC0415
    from app.tenders.models import BoqLine  # noqa: PLC0415

    return db.get(BoqLine if kind == "boq" else QuotationLine, line_id)


def line_unit(line) -> str | None:
    return getattr(line, "unit", None) or getattr(line, "uom", None)


def points(
    db: Session, kind: str, line, brands: list[str] | None = None
) -> tuple[list[dict], bool]:
    """The line's chips: as a person left them while the description is unchanged, else read
    again from the words. (chips, kept)"""
    unit = line_unit(line)
    h = keypoints.text_hash(line.description, unit)
    row = stored(db, kind, line.id)
    if row is not None and row.text_hash == h:
        return row.chips, True
    return keypoints.parse(
        line.description,
        unit,
        line.qty,
        brands if brands is not None else keypoints.known_brands(db),
    ), False


def stored(db: Session, kind: str, line_id: int) -> SpecPoints | None:
    col = SpecPoints.boq_line_id if kind == "boq" else SpecPoints.quotation_line_id
    return db.scalar(select(SpecPoints).where(col == line_id))


# --- what the master and the data sheets say -----------------------------------------------------


def facts_by_product(db: Session, product_ids) -> dict[int, list[dict]]:
    ids = {i for i in product_ids if i}
    out: dict[int, list[dict]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = db.execute(
        select(TdsFact, TdsDoc.id, TdsDoc.file_name)
        .join(TdsDoc, TdsDoc.id == TdsFact.doc_id)
        .where(TdsFact.product_id.in_(ids), TdsDoc.status == "saved")
    ).all()
    for f, doc_id, name in rows:
        out[f.product_id].append(fact_out(f) | {"doc_id": doc_id, "doc_name": name})
    return out


def fact_out(f: TdsFact) -> dict:
    return {
        "id": f.id, "kind": f.kind, "key": f.key, "lo": f.lo, "hi": f.hi, "unit": f.unit, "text": f.text,
        "standard": f.standard, "page": f.page, "sentence": f.sentence, "per_coat": f.per_coat, "coats": f.coats,
        "source": f.source, "checked_by": f.checked_by, "checked_at": f.checked_at,
    }  # fmt: skip


def product_type(p: Product, fs: list[dict]) -> str | None:
    """The product's chemistry: its data sheet's (the first one read from its name), else its name."""
    chem = [f["key"] for f in fs if f["kind"] == "chemistry"]
    return chem[0] if chem else vocab.first_type(p.name)


def step_of_product(p: Product, fs: list[dict]) -> str:
    t = product_type(p, fs)
    if t in ("primer", "mesh", "geotextile"):
        return t if t != "geotextile" else "protection"
    if t == "tape":
        return "joint"
    found = working.step_of(p.name)
    if found in ("protection", "filling"):
        return "protection"
    if found in ("coving", "termination"):
        return "joint"
    return "coat"


STEP_LABEL = {
    "primer": "primer",
    "mesh": "mesh",
    "coat": "coat",
    "protection": "protection",
    "joint": "joint / coving",
}


@dataclass
class Opt:
    kind: str  # option (a work item's brand option, with its BOM) or product (a data sheet only)
    system: System | None = None
    option: SystemOption | None = None
    product: Product | None = None
    brand: str | None = None
    type: str | None = None
    areas: set[str] = field(default_factory=set)
    rows: list[dict] = field(default_factory=list)  # the BOM per step
    main: list[int] = field(default_factory=list)  # the products that are the system (not a layer)
    checks: list[dict] = field(default_factory=list)
    past: int = 0
    cost: dict | None = None
    key: tuple = ()


def system_areas(db: Session, s: System) -> set[str]:
    """The use areas a work item fits: as set in the consumption master, else read from its name
    and description and the survey's area types that list it."""
    if s.area_keys:
        return set(s.area_keys)
    from app.survey.models import AreaType  # noqa: PLC0415

    found = set(vocab.uses_in(f"{s.name} {s.description or ''}"))
    for a in db.scalars(
        select(AreaType).where(
            or_(AreaType.default_system_id == s.id, AreaType.suitable_system_ids.any(s.id))
        )
    ):
        found |= set(vocab.uses_in(a.name))
    return found


def system_type(
    s: System, recipe: list[SystemComponent], facts: dict[int, list[dict]]
) -> str | None:
    if s.spec_type:
        return s.spec_type
    t = vocab.main_type(f"{s.name} {s.description or ''}")
    if t:
        return t
    types = [product_type(c.product, facts.get(c.product_id, [])) for c in recipe]
    types = [x for x in types if x and x not in vocab.LAYER_TYPES]
    return max(set(types), key=types.count) if types else None


def _per_unit_factor(s: System) -> Decimal:
    return SQFT_PER_SQM if s.unit == "sqft" else RFT_PER_RMT if s.unit == "rft" else D(1)


def bom_rows(s: System, option_id: int | None, facts: dict[int, list[dict]]) -> list[dict]:
    f = _per_unit_factor(s)
    big = "sqm" if s.unit in ("sqm", "sqft") else "rmt" if s.unit in ("rmt", "rft") else s.unit
    small = {"sqm": ("sq ft", SQFT_PER_SQM), "rmt": ("rft", RFT_PER_RMT)}.get(big)
    rows = []
    for c in s.recipe(option_id):
        fs = facts.get(c.product_id, [])
        per = Decimal(c.consumption_per_unit) * f if c.consumption_per_unit is not None else None
        rng = tds_range(fs, big, c.coats)
        rows.append({
            "component_id": c.id, "product_id": c.product_id, "product": c.product.name, "brand": c.product.brand, "unit": c.product.unit,
            "step": step_of_product(c.product, fs), "type": product_type(c.product, fs),
            "per_unit": per, "per_unit_label": big, "per_small": (per / small[1]) if per is not None and small else None, "small_label": small[0] if small else None,
            "wastage_percent": c.wastage_percent, "wastage_included": c.wastage_included, "coats": c.coats,
            "tds_range": rng, "outside_tds": outside(per, rng), "has_tds": bool(fs),
            "doc_id": next((x["doc_id"] for x in fs), None),
        })  # fmt: skip
    order = {"primer": 0, "coat": 1, "mesh": 2, "protection": 3, "joint": 4}
    rows.sort(key=lambda r: order.get(r["step"], 9))
    return rows


def tds_range(fs: list[dict], per: str, coats: int | None) -> dict | None:
    """The data sheet's consumption for this product per sqm (or per rmt), all coats when the
    sheet gives it per coat. None: the sheet gives none."""
    for f in fs:
        if f["kind"] != "consumption" or not f.get("key") or not f["key"].endswith(f"/{per}"):
            continue
        lo, hi = D(f["lo"]), D(f["hi"] or f["lo"])
        n = coats or f.get("coats") or 1
        if f.get("per_coat") and n > 1:
            lo, hi = lo * n, hi * n
        return {
            "lo": lo,
            "hi": hi,
            "unit": f["key"],
            "text": f["text"],
            "page": f.get("page"),
            "per_coat": f.get("per_coat"),
        }
    return None


def outside(per: Decimal | None, rng: dict | None) -> bool:
    if per is None or not rng:
        return False
    # 5 % either side: a sheet's round figures against the BOM's exact ones
    return per < rng["lo"] * D("0.95") or per > rng["hi"] * D("1.05")


def past_use(db: Session) -> dict[tuple[int, int | None], int]:
    """How often each work item and brand option was used on our quotations and won tenders."""
    from app.quotations.models import Quotation  # noqa: PLC0415
    from app.tenders.models import Tender  # noqa: PLC0415

    q = (
        select(RateGroup.system_id, RateGroup.system_option_id, func.count())
        .join(RateWorking, RateWorking.id == RateGroup.working_id)
        .outerjoin(Tender, Tender.id == RateWorking.tender_id)
        .outerjoin(Quotation, Quotation.id == RateWorking.quotation_id)
        .where(
            RateGroup.system_id.is_not(None),
            or_(Tender.status == "won", Quotation.status.in_(("sent", "negotiation", "won"))),
        )
        .group_by(RateGroup.system_id, RateGroup.system_option_id)
    )
    return {(s, o): n for s, o, n in db.execute(q)}


# --- checking an option against the line --------------------------------------------------------


def _best(fs: list[dict], prop: str) -> dict | None:
    vals = [f for f in fs if f["kind"] == "property" and f["key"] == prop and f.get("lo") is not None
            and f.get("unit") != "N/5 cm"]  # fmt: skip
    return max(vals, key=lambda f: D(f["lo"])) if vals else None


def _n(v) -> str:
    return "" if v is None else f"{D(v).normalize():f}"


def evaluate(o: Opt, a: dict, facts: dict[int, list[dict]]) -> None:
    main_facts = [f for pid in o.main for f in facts.get(pid, [])]
    checks = []
    if a.get("type"):
        ok = vocab.same_family(a["type"], o.type)
        checks.append({"point": "system", "label": f"system {vocab.TYPE_LABEL.get(a['type'], a['type'])}",
                       "state": YES if ok else (NOT_STATED if not o.type else NO), "note": vocab.TYPE_LABEL.get(o.type or "", "type not known")})  # fmt: skip
    if a.get("use"):
        state = YES if a["use"] in o.areas else (NOT_STATED if not o.areas else NO)
        checks.append({"point": "area", "label": vocab.USE_LABEL.get(a["use"], a["use"]), "state": state,
                       "note": ", ".join(vocab.USE_LABEL.get(x, x) for x in sorted(o.areas)) or "areas not set"})  # fmt: skip
    for prop, want in a.get("props", {}).items():
        label = f"{vocab.PROPERTY_LABEL[prop]} ≥ {_n(want['min'])}{' ' + want['unit'] if want.get('unit') else ''}"
        got = _best(main_facts, prop)
        if got is None:
            checks.append(
                {
                    "point": f"prop:{prop}",
                    "label": label,
                    "state": NOT_STATED,
                    "note": "not stated in TDS",
                }
            )
            continue
        v = D(got["lo"])
        ok = want["min"] is None or v >= want["min"]
        note = f"TDS {_n(v)}{' ' + got['unit'] if got.get('unit') else ''}" + (
            f" ({got['standard']})" if got.get("standard") else ""
        )
        if want.get("standard") and got.get("standard") and want["standard"] != got["standard"]:
            note += f"; the line asks {want['standard']}"
        checks.append(
            {"point": f"prop:{prop}", "label": label, "state": YES if ok else NO, "note": note}
        )
    main_rows = [
        r
        for r in o.rows
        if r["product_id"] in o.main and r["per_unit"] is not None and r["unit"] in ("kg", "L")
    ]
    have = max((r["per_unit"] for r in main_rows), default=None)
    if a.get("kg_sqm"):
        label = f"min {_n(a['kg_sqm'])} kg/sqm"
        if o.kind == "product" or have is None:
            rng = tds_range(main_facts, "sqm", a.get("coats"))
            state = NOT_STATED if not rng else (YES if rng["hi"] >= a["kg_sqm"] else NO)
            note = (
                f"TDS {_n(rng['lo'])}–{_n(rng['hi'])} kg/sqm"
                if rng
                else "no consumption in the BOM or TDS"
            )
        else:
            state = YES if have >= a["kg_sqm"] else NO
            note = f"BOM {_n(vocab.q(have, 3))} kg/sqm" + (
                ""
                if state == YES
                else f": below the line's minimum, the working uses {_n(a['kg_sqm'])}"
            )
        checks.append({"point": "kg_sqm", "label": label, "state": state, "note": note})
    if a.get("dft"):
        lo = a["dft"][0]
        label = f"DFT {_n(lo)} mm"
        need, how = tds.kg_per_sqm_for_dft(lo, main_facts)
        if need is None:
            checks.append({"point": "dft", "label": label, "state": NOT_STATED, "note": how})
        elif have is None:
            checks.append(
                {
                    "point": "dft",
                    "label": label,
                    "state": NOT_STATED,
                    "note": f"needs {_n(vocab.q(need, 3))} kg/sqm ({how}); no BOM figure",
                }
            )
        else:
            ok = have >= need * D("0.98")
            checks.append({"point": "dft", "label": label, "state": YES if ok else NO,
                           "note": f"needs {_n(vocab.q(need, 3))} kg/sqm ({how}); BOM {_n(vocab.q(have, 3))}"})  # fmt: skip
    if a.get("coats") and o.kind == "option":
        c = max((r["coats"] or 0 for r in o.rows if r["product_id"] in o.main), default=0) or None
        checks.append({"point": "coats", "label": f"{a['coats']} coats", "state": NOT_STATED if c is None else (YES if c >= a["coats"] else NO),
                       "note": f"BOM {c} coats" if c else "coats not in the BOM"})  # fmt: skip
    if a.get("brands"):
        named = any(_same_brand(o.brand, b) for b in a["brands"])
        checks.append({"point": "make", "label": f"make {', '.join(a['brands'])}",
                       "state": YES if named else ("equivalent" if a.get("equivalent") else "approval"),
                       "note": "the make named" if named else ("an equivalent (allowed)" if a.get("equivalent") else "needs client approval")})  # fmt: skip
    for k, word in (("potable", "potable"), ("uv", "UV / exposed")):
        if a.get(k):
            f = next((x for x in main_facts if x["kind"] == k), None)
            state = NOT_STATED if f is None else (YES if f["key"] == "yes" else NO)
            checks.append(
                {
                    "point": k,
                    "label": word,
                    "state": state,
                    "note": f["text"] if f else "not stated in TDS",
                }
            )
    o.checks = checks


def _same_brand(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x, y = a.lower(), b.lower()
    first = lambda s: s.replace(".", " ").split()[0]  # noqa: E731
    return x == y or first(x) == first(y) or first(x) in y or first(y) in x


def rank_key(o: Opt, a: dict) -> tuple:
    by = {c["point"]: c["state"] for c in o.checks}
    props = [s for p, s in by.items() if p.startswith("prop:")]
    usage = [by.get("kg_sqm"), by.get("dft"), by.get("coats")]
    price = o.cost["rate"] if o.cost and o.cost.get("rate") is not None else D(10**9)
    return (
        1 if by.get("make") == YES else 0,
        {YES: 2, NOT_STATED: 1}.get(by.get("system"), 0 if a.get("type") else 1),
        {YES: 2, NOT_STATED: 1}.get(by.get("area"), 0 if a.get("use") else 1),
        -props.count(NO),
        -props.count(NOT_STATED),
        -usage.count(NO),
        -usage.count(NOT_STATED),
        1 if o.kind == "option" else 0,
        o.past,
        -price,
    )


def _cost(db: Session, s: System, option_id: int | None) -> dict:
    try:
        rb = system_rate(db, s, option_id=option_id)
    except MissingPriceError as exc:
        return {"error": str(exc), "rate": None}
    small = SQFT_PER_SQM if s.unit == "sqm" else RFT_PER_RMT if s.unit == "rmt" else None
    return {"material": rb.material_cost, "labour": rb.labour_per_unit, "surface_prep": rb.surface_prep, "cost": rb.base_cost,
            "margin_percent": rb.margin_percent, "rate": rb.rate, "rate_small": (rb.rate / small) if small else None, "unit": s.unit}  # fmt: skip


def suggest(db: Session, chips: list[dict], with_cost: bool) -> dict:
    a = keypoints.asks(chips)
    systems = list(db.scalars(select(System).where(System.is_active.is_(True))))
    pids = {c.product_id for s in systems for c in s.components}
    pool_types = {a["type"]} if a.get("type") else set()
    tds_products = (
        list(
            db.scalars(
                select(Product).where(
                    Product.id.in_(select(TdsFact.product_id).where(TdsFact.kind == "chemistry"))
                )
            )
        )
        if pool_types
        else []
    )
    facts = facts_by_product(db, pids | {p.id for p in tds_products})
    used = past_use(db)
    opts: list[Opt] = []
    for s in systems:
        areas = system_areas(db, s)
        options = s.options or [None]
        for o in options:
            recipe = s.recipe(o.id if o else None)
            if not recipe:
                continue
            t = system_type(s, recipe, facts)
            rows = bom_rows(s, o.id if o else None, facts)
            main = [r["product_id"] for r in rows if r["step"] == "coat"] or [
                r["product_id"] for r in rows
            ]
            brand = (
                o.brand if o else next((c.product.brand for c in recipe if c.product.brand), None)
            )
            opts.append(Opt("option", system=s, option=o, brand=brand, type=t, areas=areas, rows=rows, main=main,
                            past=used.get((s.id, o.id if o else None), 0) + (used.get((s.id, None), 0) if o and o.is_default else 0)))  # fmt: skip
    in_bom = {r["product_id"] for o in opts for r in o.rows}
    for p in tds_products:
        fs = facts.get(p.id, [])
        t = product_type(p, fs)
        if p.id in in_bom or not vocab.same_family(a.get("type"), t):
            continue
        opts.append(Opt("product", product=p, brand=p.brand, type=t, areas={f["key"] for f in fs if f["kind"] == "use"}, main=[p.id],
                        rows=[{"product_id": p.id, "product": p.name, "brand": p.brand, "unit": p.unit, "step": "coat", "type": t, "per_unit": None,
                               "tds_range": tds_range(fs, "sqm", a.get("coats")), "has_tds": True, "doc_id": next((x["doc_id"] for x in fs), None)}]))  # fmt: skip
    for o in opts:
        evaluate(o, a, facts)

    # only what fits the line: its type (or, with none named, its area); everything when it says neither
    def fits(o: Opt) -> bool:
        by = {c["point"]: c["state"] for c in o.checks}
        if a.get("type"):
            return by.get("system") == YES
        if a.get("use"):
            return by.get("area") == YES
        return True

    pool = [o for o in opts if fits(o)]
    if with_cost:
        for o in pool:
            if o.kind == "option":
                o.cost = _cost(db, o.system, o.option.id if o.option else None)
    for o in pool:
        o.key = rank_key(o, a)
    pool.sort(key=lambda o: o.key, reverse=True)
    shown = [o for o in pool if o.kind == "option"][:MAX_OPTIONS] + [
        o for o in pool if o.kind == "product"
    ][:MAX_PRODUCTS]
    shown.sort(key=lambda o: o.key, reverse=True)
    return {
        "asks": _asks_out(a),
        "options": [opt_out(o, with_cost) for o in shown],
        "gaps": gaps(pool, a),
        "considered": len(opts),
    }


def gaps(pool: list[Opt], a: dict) -> list[str]:
    """The key points no option meets (none at all, or not one of those shown)."""
    out = []
    points = {}
    for o in pool:
        for c in o.checks:
            points.setdefault(c["point"], (c["label"], []))[1].append(c["state"])
    for point, (label, states) in points.items():
        if point == "make":
            continue
        if YES not in states:
            out.append(
                f"No option meets {label}"
                + (": the TDS do not state it" if set(states) == {NOT_STATED} else "")
            )
    if not pool:
        what = vocab.TYPE_LABEL.get(a.get("type") or "", None) or vocab.USE_LABEL.get(
            a.get("use") or "", None
        )
        out.append(
            f"No work item or data sheet fits {what}" if what else "No work item fits the line"
        )
    return out


def _asks_out(a: dict) -> dict:
    return {
        k: ([str(x) if isinstance(x, Decimal) else x for x in v] if isinstance(v, tuple) else v)
        for k, v in a.items()
    }


def opt_out(o: Opt, with_cost: bool) -> dict:
    rows = o.rows if with_cost else [{k: v for k, v in r.items()} for r in o.rows]
    return {
        "kind": o.kind,
        "system_id": o.system.id if o.system else None,
        "system": o.system.name if o.system else None,
        "unit": o.system.unit if o.system else None,
        "option_id": o.option.id if o.option else None,
        "product_id": o.product.id if o.product else None,
        "product": o.product.name if o.product else None,
        "brand": o.brand,
        "type": vocab.TYPE_LABEL.get(o.type or "", None),
        "rows": rows,
        "checks": o.checks,
        "meets_all": all(c["state"] in (YES, "equivalent") for c in o.checks),
        "past_use": o.past,
        "cost": o.cost if with_cost else None,
        "steps": [
            {"step": STEP_LABEL.get(r["step"], r["step"]), "product": r["product"]} for r in o.rows
        ],
    }


# --- the pick -------------------------------------------------------------------------------------


class PickError(ValueError):
    pass


def working_of(db: Session, kind: str, line, user_id=None) -> RateWorking:
    if kind == "boq":
        from app.tenders.models import Tender  # noqa: PLC0415

        return working.for_tender(db, db.get(Tender, line.tender_id), user_id)
    from app.quotations.models import Quotation, QuotationItem  # noqa: PLC0415

    item = db.get(QuotationItem, line.item_id)
    return working.for_quotation(db, db.get(Quotation, item.quotation_id), user_id)


def group_of(db: Session, w: RateWorking, kind: str, line_id: int) -> RateGroup | None:
    col = RateGroupLine.boq_line_id if kind == "boq" else RateGroupLine.quotation_line_id
    gl = db.scalar(
        select(RateGroupLine).join(RateGroup).where(col == line_id, RateGroup.working_id == w.id)
    )
    return db.get(RateGroup, gl.group_id) if gl else None


def picks_of(db: Session, kind: str, line_id: int) -> list[SpecPick]:
    col = SpecPick.boq_line_id if kind == "boq" else SpecPick.quotation_line_id
    return list(db.scalars(select(SpecPick).where(col == line_id).order_by(SpecPick.rank)))


def pick(
    db: Session,
    kind: str,
    line,
    system_id: int,
    option_id: int | None,
    rank: int,
    chips: list[dict],
    user_id=None,
) -> SpecPick:
    """Tick an option for the line. Rank 1 builds the line's main item in the rate working from it
    (the line's own main item; a line that shared one with others gets its own); rank 2 is kept as
    the alternate."""
    s = db.get(System, system_id)
    if s is None:
        raise PickError("Unknown work item")
    if option_id is not None and option_id not in {o.id for o in s.options}:
        raise PickError("That brand option is not one of the work item's")
    for old in picks_of(db, kind, line.id):
        if old.rank == rank:
            db.delete(old)
    db.flush()
    p = SpecPick(rank=rank, system_id=s.id, option_id=option_id, picked_by=user_id,
                 **({"boq_line_id": line.id} if kind == "boq" else {"quotation_line_id": line.id}))  # fmt: skip
    db.add(p)
    if rank == 2:
        db.flush()
        return p
    w = working_of(db, kind, line, user_id)
    if w.locked:
        raise PickError(
            f"R{w.rev_no} was submitted: its working is kept as it was; work on the new revision"
        )
    g = group_of(db, w, kind, line.id)
    key = f"{'b' if kind == 'boq' else 'q'}{line.id}"
    if g is not None and len(g.lines) > 1:
        for gl in list(g.lines):
            if (gl.boq_line_id if kind == "boq" else gl.quotation_line_id) == line.id:
                g.lines.remove(gl)
        g = None
    if g is None:
        g = RateGroup(working_id=w.id, sort_order=max((x.sort_order for x in w.groups), default=0) + 1,
                      name=working._name_from([{"description": line.description}]), created_by=user_id)  # fmt: skip
        g.lines = [working._group_line(key)]
        db.add(g)
    a = keypoints.asks(chips)
    g.system_id, g.system_option_id = s.id, option_id
    g.req_min_kg_sqm = a.get("kg_sqm")
    g.req_dft_mm = a["dft"][0] if a.get("dft") else None
    g.coats = a.get("coats")
    db.flush()
    try:
        working.init_from_system(db, g, line.description[:400])
        g.req_min_kg_sqm, g.req_dft_mm = a.get("kg_sqm"), (a["dft"][0] if a.get("dft") else None)
        g.coats = a.get("coats") or g.coats
        working.work(db, g)
    except working.WorkingUnitError as exc:  # a work item per nos: kept, said on the main item
        g.note = str(exc)
    p.group_id = g.id
    # the line names what it gets (the exports print the brand and products per step, as today)
    option = db.get(SystemOption, option_id) if option_id else s.default_option()
    words = "; ".join(
        f"{STEP_LABEL.get(r['step'], r['step'])}: {r['product']}"
        for r in bom_rows(s, option.id if option else None, {})
    )
    if kind == "boq":
        line.system_id = s.id
        line.manufacturer = (option.brand if option else line.manufacturer) or None
        line.our_product = words[:2000] or line.our_product
    else:
        line.system_id, line.system_option_id = s.id, option.id if option else None
    db.flush()
    return p


def sub_lines(db: Session, kind: str, line) -> dict | None:
    """The picked option's steps for the line: each product's consumption per unit and its
    quantity for the line's qty; a figure a person changed says so and can go back."""
    first = next((p for p in picks_of(db, kind, line.id) if p.rank == 1), None)
    if first is None or first.group_id is None:
        return None
    g = db.get(RateGroup, first.group_id)
    if g is None:
        return None
    facts = facts_by_product(db, [p.product_id for p in g.products])
    unit = (line_unit(line) or "").lower()
    qty = Decimal(line.qty) if line.qty is not None else None
    if qty is not None:
        if g.unit == "sqm" and unit in ("sqft", "sft"):
            qty = qty / SQFT_PER_SQM
        elif g.unit == "rmt" and unit == "rft":
            qty = qty / RFT_PER_RMT
    out = []
    for p in g.products:
        prod = p.product
        w = (
            D(0)
            if p.wastage_included
            else Decimal(
                p.wastage_percent if p.wastage_percent is not None else g.wastage_percent or 0
            )
        )
        q = (
            (Decimal(p.consumption) * qty * (1 + w / 100))
            if (p.consumption is not None and qty is not None)
            else None
        )
        out.append({
            "id": p.id, "product_id": p.product_id, "product": prod.name, "unit": prod.unit,
            "step": STEP_LABEL.get(step_of_product(prod, facts.get(p.product_id, [])), "coat"),
            "consumption": p.consumption, "default_consumption": p.default_consumption, "source": p.consumption_source,
            "wastage_percent": w, "qty": vocab.q(q, 3) if q is not None else None,
            "changed": p.default_consumption is not None and p.consumption != p.default_consumption,
        })  # fmt: skip
    return {"group_id": g.id, "unit": g.unit, "line_qty": line.qty, "qty_in_unit": vocab.q(qty, 3) if qty is not None else None,
            "rows": out, "rate": g.rate_sqm, "note": g.note}  # fmt: skip


def set_sub_line(
    db: Session, rgp_id: int, consumption: Decimal | None, reason: str | None
) -> RateGroup:
    """A step's consumption changed by a person (blank: back to the calculated one)."""
    from app.costing.models import RateGroupProduct  # noqa: PLC0415

    p = db.get(RateGroupProduct, rgp_id)
    if p is None:
        raise PickError("Step not found")
    if consumption is None:
        p.consumption, p.consumption_reason = p.default_consumption, None
    else:
        p.consumption = consumption
        p.consumption_reason = (
            (reason or "changed by user")[:300] if p.consumption != p.default_consumption else None
        )
    g = db.get(RateGroup, p.group_id)
    db.flush()
    working.work(db, g)
    return g
