# ruff: noqa: E501  (the build-up rows and queries read better unwrapped)
"""The rate working sheet of a BOQ (a tender's revision or a quotation).

Grouping: the client's lines become main items. The app suggests the groups (the same system, or
close item text, using the rate library matching the BOQ already has: a line's system, its best
system candidate, else its words), and the user moves lines between groups (a 40-line client BOQ
becomes 3 main items).

Each main item is worked per sqm, the same way by everyone:

    material  = Σ consumption × (price + freight) × (1 + wastage of the application)
    cost      = material + surface preparation + labour (₹ per sq ft × 10.7639 per sqm)
    rate      = cost × (1 + margin %)              per sqm, and ÷ 10.7639 per sq ft

(app.masters.rate.build_rate, Decimal throughout, only the rate rounded). Consumption defaults from
the system and needs a reason when changed; the price comes from the master price list, freight
from its own history; the application's wastage (raft 5-7 %, footing 12-15 %, the upper figure)
from Settings > Process rules. Cushions are visible lines: the labour in the rate against what the
gang is paid, the freight used against the actual. The worked rate flows to every client line in
the group (sqm or sq ft), and is compared with the rate library's median (flagged past 15 %).

Costs and margins are for tender.margin only; sales sees the groups and the rates.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.costing import prices
from app.costing.models import (
    LabourRateCard,
    RateGroup,
    RateGroupLine,
    RateGroupProduct,
    RateWorking,
)
from app.masters.models import LibraryItem, Product, System
from app.masters.rate import SQFT_PER_SQM, ComponentInput, build_rate
from app.masters.search import STOPWORDS

CENT = Decimal("0.01")
AREA_UNITS = {"sqm", "sqft", "sft"}
JOIN_AT = 0.34  # word overlap (Jaccard) for two lines to be one main item


def money(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


# --- the client's lines --------------------------------------------------------------------------


def client_lines(db: Session, w: RateWorking) -> list[dict]:
    """The BOQ's lines in order: {key, kind, id, item_no, description, unit, qty, rate,
    system_id, library_item_id}. key is "b<id>" (tender) or "q<id>" (quotation)."""
    if w.tender_id:
        from app.tenders.models import BoqLine, BoqSection  # noqa: PLC0415

        rows = db.execute(
            select(BoqLine, BoqSection.sort_order)
            .outerjoin(BoqSection, BoqSection.id == BoqLine.section_id)
            .where(BoqLine.tender_id == w.tender_id)
            .order_by(BoqSection.sort_order.nulls_first(), BoqLine.sort_order, BoqLine.id)
        ).all()
        return [
            {
                "key": f"b{ln.id}",
                "kind": "boq",
                "id": ln.id,
                "item_no": ln.client_item_no,
                "description": ln.description,
                "unit": ln.unit or ln.unit_raw,
                "qty": ln.qty,
                "rate": ln.rate,
                "system_id": ln.system_id,
                "library_item_id": ln.library_item_id,
                "status": ln.status,
            }
            for ln, _s in rows
        ]
    from app.quotations.models import QuotationItem, QuotationLine  # noqa: PLC0415

    rows = db.execute(
        select(QuotationLine, QuotationItem)
        .join(QuotationItem, QuotationItem.id == QuotationLine.item_id)
        .where(QuotationItem.quotation_id == w.quotation_id)
        .order_by(QuotationItem.sort_order, QuotationItem.id, QuotationLine.sort_order, QuotationLine.id)
    ).all()  # fmt: skip
    return [
        {
            "key": f"q{ln.id}",
            "kind": "quotation",
            "id": ln.id,
            "item_no": item.name,
            "description": ln.description,
            "unit": ln.uom,
            "qty": ln.qty,
            "rate": ln.rate,
            "system_id": ln.system_id,
            "library_item_id": ln.library_item_id,
            "status": None,
        }
        for ln, item in rows
    ]


def _line_key(gl: RateGroupLine) -> str:
    return f"b{gl.boq_line_id}" if gl.boq_line_id else f"q{gl.quotation_line_id}"


def _group_line(key: str) -> RateGroupLine:
    kind, ident = key[0], int(key[1:])
    return RateGroupLine(
        boq_line_id=ident if kind == "b" else None,
        quotation_line_id=ident if kind == "q" else None,
    )


# --- the working of a BOQ: per tender revision or quotation, copied to the next ------------------


def for_tender(db: Session, tender, user_id=None) -> RateWorking:
    """The working of the revision being worked on; a new revision starts as a copy of the last
    one, and the earlier revisions' workings are kept as they were (locked)."""
    rev = tender.revision
    w = db.scalar(
        select(RateWorking).where(RateWorking.tender_id == tender.id, RateWorking.rev_no == rev)
    )
    for old in db.scalars(
        select(RateWorking).where(RateWorking.tender_id == tender.id, RateWorking.rev_no < rev)
    ):
        old.locked = True
    if w is not None:
        return w
    w = RateWorking(tender_id=tender.id, rev_no=rev, created_by=user_id)
    db.add(w)
    db.flush()
    prev = db.scalar(
        select(RateWorking)
        .where(RateWorking.tender_id == tender.id, RateWorking.rev_no < rev)
        .order_by(RateWorking.rev_no.desc())
        .limit(1)
    )
    if prev is not None:
        copy(db, prev, w, {})  # the BOQ lines carry over between revisions
    return w


def for_quotation(db: Session, q, user_id=None) -> RateWorking:
    """A quotation's working; a revision (a new quotation row) copies its predecessor's, its lines
    matched in order."""
    w = db.scalar(select(RateWorking).where(RateWorking.quotation_id == q.id))
    if w is not None:
        return w
    w = RateWorking(quotation_id=q.id, rev_no=q.revision or 0, created_by=user_id)
    db.add(w)
    db.flush()
    prev = (
        db.scalar(select(RateWorking).where(RateWorking.quotation_id == q.previous_id))
        if q.previous_id
        else None
    )
    if prev is not None:
        prev.locked = True
        old = [x["key"] for x in client_lines(db, prev)]
        new = [x["key"] for x in client_lines(db, w)]
        copy(db, prev, w, dict(zip(old, new, strict=False)))
    return w


def copy(db: Session, src: RateWorking, dst: RateWorking, line_map: dict[str, str]) -> None:
    dst.copied_from_id = src.id
    for g in src.groups:
        ng = RateGroup(
            working_id=dst.id,
            **{c: getattr(g, c) for c in GROUP_FIELDS},
            created_by=g.created_by,
        )
        ng.products = [
            RateGroupProduct(**{c: getattr(p, c) for c in PRODUCT_FIELDS}) for p in g.products
        ]
        ng.lines = [
            _group_line(line_map.get(_line_key(gl), _line_key(gl)))
            for gl in g.lines
            if not line_map or _line_key(gl) in line_map
        ]
        db.add(ng)
    db.flush()


GROUP_FIELDS = (
    "sort_order", "name", "system_id", "application", "coats", "wastage_percent", "surface_prep",
    "labour_rate_card_id", "labour_used_sqft", "labour_paid_sqft", "margin_percent", "cost_sqm",
    "rate_sqm", "rate_sqft", "library_median_sqm", "note",
)  # fmt: skip
PRODUCT_FIELDS = (
    "product_id", "sort_order", "consumption", "default_consumption", "consumption_reason",
    "price", "price_id", "freight_used", "freight_actual",
)  # fmt: skip


# --- suggesting the groups -----------------------------------------------------------------------


def words(text: str) -> set[str]:
    found = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {w for w in found if w not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _family(unit: str | None) -> str:
    u = (unit or "").lower()
    return "area" if u in AREA_UNITS else (u or "?")


def _best_system(db: Session, line: dict) -> int | None:
    if line["system_id"]:
        return line["system_id"]
    if line["kind"] != "boq":
        return None
    from app.tenders.models import BoqLineCandidate  # noqa: PLC0415

    return db.scalar(
        select(BoqLineCandidate.ref_id)
        .where(BoqLineCandidate.line_id == line["id"], BoqLineCandidate.source == "system")
        .order_by(BoqLineCandidate.score.desc())
        .limit(1)
    )


def suggest(db: Session, w: RateWorking, user_id=None) -> list[RateGroup]:
    """Group the lines not in a group yet: by system (the line's or its best system candidate),
    else by close item text (and the same kind of unit). New groups get the system's build-up."""
    grouped = {_line_key(gl) for g in w.groups for gl in g.lines}
    clusters: list[dict] = []
    for line in client_lines(db, w):
        if line["key"] in grouped:
            continue
        sid = _best_system(db, line)
        fam = _family(line["unit"])
        tokens = words(line["description"])
        target = None
        for c in clusters:
            if c["family"] != fam:
                continue
            if sid and c["system_id"] == sid:
                target = c
                break
            if (not sid or not c["system_id"]) and _jaccard(tokens, c["tokens"]) >= JOIN_AT:
                target = c
                break
        if target is None:
            target = {"system_id": sid, "family": fam, "tokens": tokens, "lines": []}
            clusters.append(target)
        target["lines"].append(line)
        target["system_id"] = target["system_id"] or sid
    made = []
    start = max((g.sort_order for g in w.groups), default=0)
    for i, c in enumerate(clusters, start=1):
        system = db.get(System, c["system_id"]) if c["system_id"] else None
        g = RateGroup(
            working_id=w.id,
            sort_order=start + i,
            name=system.name if system else _name_from(c["lines"]),
            system_id=system.id if system else None,
            created_by=user_id,
        )
        g.lines = [_group_line(x["key"]) for x in c["lines"]]
        db.add(g)
        db.flush()
        init_from_system(db, g, " ".join(x["description"] for x in c["lines"][:3]))
        made.append(g)
    db.flush()
    db.refresh(w)
    return made


def _name_from(lines: list[dict]) -> str:
    # up to the first colon, semicolon or bracket, or a comma or full stop that ends a phrase
    # ("1.5 mm" stays whole)
    text = re.split(r"[:;(]|[.,]\s", lines[0]["description"] or "Main item", maxsplit=1)[0]
    return " ".join(text.split())[:80] or "Main item"


def init_from_system(db: Session, g: RateGroup, context: str = "") -> None:
    """The system's build-up as the starting point: its products and consumption, today's prices
    and freight, its surface preparation, labour and margin, and the application's wastage."""
    from app.process.engine import wastage_for  # noqa: PLC0415

    system = db.get(System, g.system_id) if g.system_id else None
    app_w = wastage_for(db, f"{g.name} {context}")
    g.application = app_w[0] if app_w else None
    if app_w:
        g.wastage_percent = Decimal(str(app_w[1]["max"]))
    elif system:
        g.wastage_percent = max(
            (Decimal(c.wastage_percent or 0) for c in system.components), default=Decimal(0)
        )
    if system is None:
        return
    g.surface_prep = Decimal(system.surface_prep_per_unit or 0)
    labour = Decimal(system.labour_rate or 0)
    g.labour_used_sqft = money(labour / SQFT_PER_SQM if system.labour_unit == "sqm" else labour)
    g.margin_percent = Decimal(system.default_margin_percent or 0)
    g.coats = max((c.coats for c in system.components if c.coats), default=None)
    g.products = []
    for i, c in enumerate(system.components):
        g.products.append(new_product(db, c.product_id, c.consumption_per_unit, i))


def new_product(db: Session, product_id: int, consumption, sort: int = 0) -> RateGroupProduct:
    cur = prices.current(db, product_id)
    f = prices.freight_for(db, product_id)
    freight = f.per_unit if f else (cur.freight_per_unit if cur else Decimal(0))
    return RateGroupProduct(
        product_id=product_id,
        sort_order=sort,
        consumption=consumption,
        default_consumption=consumption,
        price=cur.purchase_rate if cur else None,
        price_id=cur.id if cur else None,
        freight_used=freight or Decimal(0),
    )


# --- working a main item -------------------------------------------------------------------------


def work(db: Session, g: RateGroup) -> dict:
    """The rate per sqm and sq ft, its build-up lines, the cushions and the flags. Stores the
    result on the group."""
    errors = []
    comps = []
    for p in g.products:
        product = db.get(Product, p.product_id)
        if p.consumption is None:
            errors.append(f"{product.name}: consumption to confirm")
            continue
        if p.price is None:
            errors.append(f"{product.name}: no price in the master price list")
            continue
        comps.append(
            ComponentInput(
                product_id=product.id,
                product_name=product.name,
                unit=product.unit,
                consumption_per_unit=Decimal(p.consumption),
                wastage_percent=Decimal(g.wastage_percent or 0),
                purchase_rate=Decimal(p.price),
                freight_per_unit=Decimal(p.freight_used or 0),
            )
        )
    if errors or not g.products:
        if not g.products:
            errors.append("No products: choose the system or add products")
        g.cost_sqm = g.rate_sqm = g.rate_sqft = None
        return {"errors": errors, "rate_sqm": None, "rate_sqft": None, "rows": [], "cushions": []}
    br = build_rate(
        unit="sqm",
        components=comps,
        surface_prep=Decimal(g.surface_prep or 0),
        labour_rate=Decimal(g.labour_used_sqft or 0),
        labour_unit="sqft",
        margin_percent=Decimal(g.margin_percent or 0),
    )
    g.cost_sqm = br.base_cost
    g.rate_sqm = br.rate
    g.rate_sqft = money((br.base_cost + br.margin_amount) / SQFT_PER_SQM)
    rows = [{"item": "Surface preparation", "coverage": None, "cost_of_material": None,
             "per_sqm": money(br.surface_prep), "ref": None}]  # fmt: skip
    cushions = []
    for c, p in zip(
        br.components,
        [x for x in g.products if x.consumption is not None and x.price is not None],
        strict=True,
    ):
        rows.append({
            "item": c.product_name, "product_id": c.product_id, "unit": c.unit,
            "consumption": p.consumption, "coverage": c.quantity_with_wastage,
            "price": c.purchase_rate, "freight": c.freight_per_unit,
            "cost_of_material": c.landed_rate, "per_sqm": money(c.cost),
            "ref": "price list",
        })  # fmt: skip
        if p.freight_actual is not None and Decimal(p.freight_actual) != Decimal(
            p.freight_used or 0
        ):
            cushions.append({
                "what": f"Freight on {c.product_name}",
                "used": p.freight_used, "actual": p.freight_actual,
                "per_sqm": money((Decimal(p.freight_used or 0) - Decimal(p.freight_actual)) * c.quantity_with_wastage),
            })  # fmt: skip
    rows.append({"item": "Labour", "coverage": None, "cost_of_material": money(br.labour_per_unit),
                 "per_sqm": money(br.labour_per_unit),
                 "ref": f"₹{g.labour_used_sqft} per sq ft × {SQFT_PER_SQM}"})  # fmt: skip
    if g.labour_paid_sqft is not None and Decimal(g.labour_paid_sqft) != Decimal(
        g.labour_used_sqft or 0
    ):
        cushions.append({
            "what": "Labour", "used": g.labour_used_sqft, "actual": g.labour_paid_sqft,
            "per_sqm": money((Decimal(g.labour_used_sqft or 0) - Decimal(g.labour_paid_sqft)) * SQFT_PER_SQM),
        })  # fmt: skip
    median_sqm = library_median(db, g)
    g.library_median_sqm = median_sqm
    limit = Decimal(prices.settings(db).library_diff_flag_percent)
    diff = (
        ((br.rate - median_sqm) / median_sqm * 100).quantize(Decimal("0.1")) if median_sqm else None
    )
    return {
        "errors": [],
        "rows": rows,
        "material_sqm": money(br.material_cost),
        "cost_sqm": money(br.base_cost),
        "margin_sqm": money(br.margin_amount),
        "rate_sqm": br.rate,
        "rate_sqft": g.rate_sqft,
        "cushions": cushions,
        "cushion_sqm": money(sum((Decimal(c["per_sqm"]) for c in cushions), Decimal(0))),
        "library_median_sqm": median_sqm,
        "library_diff_percent": diff,
        "library_flagged": diff is not None and abs(diff) > limit,
        "library_limit_percent": limit,
    }  # fmt: skip


def library_median(db: Session, g: RateGroup) -> Decimal | None:
    """The rate library's median for the group's lines (their matched items, else their best
    library candidates), per sqm."""
    from app.tenders.models import BoqLine, BoqLineCandidate  # noqa: PLC0415

    item_ids = set()
    for gl in g.lines:
        if gl.boq_line_id:
            ln = db.get(BoqLine, gl.boq_line_id)
            lib = ln.library_item_id if ln else None
            lib = lib or db.scalar(
                select(BoqLineCandidate.ref_id)
                .where(BoqLineCandidate.line_id == gl.boq_line_id, BoqLineCandidate.source == "library")
                .order_by(BoqLineCandidate.score.desc())
                .limit(1)
            )  # fmt: skip
        else:
            from app.quotations.models import QuotationLine  # noqa: PLC0415

            ql = db.get(QuotationLine, gl.quotation_line_id)
            lib = ql.library_item_id if ql else None
        if lib:
            item_ids.add(lib)
    rates = []
    for item in db.scalars(select(LibraryItem).where(LibraryItem.id.in_(item_ids or {-1}))):
        if item.median_rate is None:
            continue
        unit = (item.unit or "").lower()
        if unit == "sqm":
            rates.append(Decimal(item.median_rate))
        elif unit in ("sqft", "sft"):
            rates.append(Decimal(item.median_rate) * SQFT_PER_SQM)
    return money(Decimal(median(rates))) if rates else None


def labour_from_card(db: Session, g: RateGroup) -> None:
    """The gang's piece rate (what we pay) from the labour rate card, per sq ft."""
    card = db.get(LabourRateCard, g.labour_rate_card_id) if g.labour_rate_card_id else None
    if card is None:
        return
    rate = Decimal(card.rate)
    g.labour_paid_sqft = money(rate / SQFT_PER_SQM if card.unit == "sqm" else rate)


# --- the rate to the client's lines --------------------------------------------------------------


def apply_rates(db: Session, w: RateWorking) -> dict:
    """Every client line in a worked group gets the group's rate (sqm or sq ft); a line in another
    unit is left for a person (reported)."""
    applied, skipped = 0, []
    tender_lines = []
    for g in w.groups:
        if g.rate_sqm is None:
            continue
        cost_sqm = Decimal(g.cost_sqm or 0)
        for gl in g.lines:
            if gl.boq_line_id:
                from app.tenders.models import BoqLine  # noqa: PLC0415

                ln = db.get(BoqLine, gl.boq_line_id)
                unit = (ln.unit or ln.unit_raw or "").lower()
            else:
                from app.quotations.models import QuotationLine  # noqa: PLC0415

                ln = db.get(QuotationLine, gl.quotation_line_id)
                unit = (ln.uom or "").lower()
            if unit == "sqm":
                rate, cost = Decimal(g.rate_sqm), cost_sqm
            elif unit in ("sqft", "sft"):
                rate, cost = Decimal(g.rate_sqft), cost_sqm / SQFT_PER_SQM
            else:
                skipped.append({"line": gl.boq_line_id or gl.quotation_line_id, "unit": unit})
                continue
            ln.rate, ln.cost_rate, ln.margin_percent = (
                rate,
                cost.quantize(Decimal("0.0001")),
                g.margin_percent,
            )
            if gl.boq_line_id:
                ln.source, ln.status = "working", "priced"
                tender_lines.append(ln)
                from app.tenders.pricing import refresh_amount  # noqa: PLC0415

                refresh_amount(ln)
            else:
                ln.rate_source, ln.overridden = "working", True
            applied += 1
    if tender_lines and w.tender_id:
        from app.tenders.models import Tender  # noqa: PLC0415
        from app.tenders.pricing import refresh_tender_total  # noqa: PLC0415

        refresh_tender_total(db, db.get(Tender, w.tender_id))
    db.flush()
    return {"applied": applied, "skipped": skipped}
