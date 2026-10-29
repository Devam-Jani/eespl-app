# ruff: noqa: E501  (the rows read better unwrapped)
"""Using the library: past rates by place, margins carried, products and consumption per surface,
the templates proposed for a new main item, filling a rate working from one, the gap to the past,
matching an imported client BOQ, and learning from a won BOQ."""

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge import extract
from app.knowledge.library import _product_index, jaccard, match_product, settings, words
from app.knowledge.models import KnowledgeFile, KnowledgeLine, KnowledgeTemplate, ProductReview
from app.timefmt import ist_today

SQFT = Decimal("10.7639")
NOT_PRODUCT = re.compile(r"margin|profit|overhead|total|gst|\btax\b|contingenc", re.I)


def money(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), ROUND_HALF_UP)


def region_of(db: Session, city: str | None) -> str | None:
    if not city:
        return None
    regions = settings(db).regions or extract.DEFAULT_REGIONS
    for region, cities in regions.items():
        if any(c.lower() == city.lower() for c in cities):
            return region
    found = extract.place([("city", city)], regions)
    return found[1]


def members(db: Session, t: KnowledgeTemplate) -> list[KnowledgeLine]:
    return list(
        db.scalars(
            select(KnowledgeLine).where(
                KnowledgeLine.template_id == t.id, KnowledgeLine.hidden.is_(False)
            )
        )
    )


def _rate(t: KnowledgeTemplate, ln: KnowledgeLine) -> Decimal | None:
    return ln.rate_sqm if t.unit == "sqm" else ln.rate


def _stats(rows: list[dict]) -> dict | None:
    rates = [Decimal(r["rate"]) for r in rows]
    if not rates:
        return None
    dated = sorted((r for r in rows if r["on_date"]), key=lambda r: r["on_date"], reverse=True)
    latest = dated[0] if dated else rows[0]
    return {
        "n": len(rates),
        "min": money(min(rates)),
        "median": money(statistics.median(rates)),
        "max": money(max(rates)),
        "latest": latest,
    }


def rates(
    db: Session, t: KnowledgeTemplate, city: str | None = None, with_cost: bool = False
) -> dict:
    """Past selling rates: the same city first, then the same region, then all; each row with its
    place, date (flagged when older than the set months), client folder, quantity, and (cost
    users) cost and margin."""
    s = settings(db)
    old_before = ist_today() - timedelta(days=int(30.4 * (s.old_after_months or 12)))
    region = region_of(db, city)
    files = {}
    rows = []
    for ln in members(db, t):
        r = _rate(t, ln)
        if r is None or ln.qty_note == "NQ":
            continue
        if ln.file_id not in files:
            files[ln.file_id] = db.get(KnowledgeFile, ln.file_id) if ln.file_id else None
        f = files[ln.file_id]
        row = {
            "line_id": ln.id, "rate": money(r), "city": ln.city, "region": ln.region, "on_date": ln.on_date,
            "old": bool(ln.on_date and ln.on_date < old_before), "folder": ln.folder, "qty": ln.qty, "qty_note": ln.qty_note,
            "file": f.path if f else ("won BOQ" if ln.source == "won" else None), "sheet": ln.sheet, "row": ln.row,
            "source": ln.source, "to_check": ln.to_check,
        }  # fmt: skip
        if with_cost:
            row["cost"] = money(ln.cost_sqm) if ln.cost_sqm is not None else None
            row["margin_percent"] = ln.margin_percent
        rows.append(row)
    rows.sort(key=lambda r: (r["on_date"] or date(1900, 1, 1)), reverse=True)
    near_city = [r for r in rows if city and r["city"] and r["city"].lower() == city.lower()]
    near_region = [r for r in rows if region and r["region"] == region]
    return {
        "unit": t.unit,
        "city": city,
        "region": region,
        "old_after_months": s.old_after_months,
        "city_stats": _stats(near_city),
        "region_stats": _stats(near_region),
        "all_stats": _stats(rows),
        "rows": rows[:300],
    }


def near_median(db: Session, t: KnowledgeTemplate, city: str | None) -> tuple[Decimal | None, str]:
    r = rates(db, t, city)
    for k, label in (
        ("city_stats", f"in {city}"),
        ("region_stats", f"in {r['region']}"),
        ("all_stats", "everywhere"),
    ):
        if r[k]:
            return r[k]["median"], label
    return None, "no past rate"


def margins(db: Session, t: KnowledgeTemplate) -> dict:
    """The margin we actually carried (on the selling price), from the workings: overall and by
    client / channel (the BOQ folder)."""
    lines = [ln for ln in members(db, t) if ln.margin_percent is not None]
    by: dict[str, list[Decimal]] = defaultdict(list)
    for ln in lines:
        by[ln.folder or "unknown"].append(Decimal(ln.margin_percent))

    def st(v):
        return (
            {
                "n": len(v),
                "min": round(min(v), 1),
                "median": round(statistics.median(v), 1),
                "max": round(max(v), 1),
            }
            if v
            else None
        )

    allm = [Decimal(ln.margin_percent) for ln in lines]
    out = {
        "all": st(allm),
        "by_client": {k: st(v) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))[:12]},
    }
    if allm:
        q = sorted(allm)
        lo, hi = q[len(q) // 4], q[(3 * len(q)) // 4]
        out["usual"] = f"usual {round(lo)} to {round(hi)} %" if lo != hi else f"usual {round(lo)} %"
    return out


def products(
    db: Session, t: KnowledgeTemplate, surface: str | None = None, city: str | None = None
) -> dict:
    """What the workings of this template used: products (matched to the master when they can be),
    consumption per surface (the surface asked first), price and freight, most used first; labour
    per sq ft and surface preparation."""
    index = _product_index(db)
    region = region_of(db, city)
    items: dict[str, dict] = {}
    labour, prep = [], []
    for ln in members(db, t):
        w = ln.working or {}
        if not w:
            continue
        if w.get("labour_sqft"):
            labour.append(Decimal(w["labour_sqft"]))
        if w.get("surface_prep_sqm"):
            prep.append(Decimal(w["surface_prep_sqm"]))
        for it in w.get("items", []):
            if (
                it.get("kind") != "product"
                or it.get("after_margin")
                or NOT_PRODUCT.search(it.get("label") or "")
            ):
                continue
            label = (it.get("label") or "").strip()
            pid = match_product(index, label)
            key = f"p{pid}" if pid else label.lower()
            e = items.setdefault(
                key,
                {
                    "label": label,
                    "product_id": pid,
                    "boqs": set(),
                    "by_surface": defaultdict(list),
                    "price": [],
                    "freight": [],
                    "freight_near": [],
                },
            )
            e["boqs"].add(ln.file_id)
            if it.get("consumption") and Decimal(it["consumption"]) > 0:
                e["by_surface"][ln.surface or "any"].append(Decimal(it["consumption"]))
            if it.get("price"):
                e["price"].append(Decimal(it["price"]))
            if it.get("freight"):
                e["freight"].append(Decimal(it["freight"]))
                if city and (
                    (ln.city or "").lower() == city.lower() or (region and ln.region == region)
                ):
                    e["freight_near"].append(Decimal(it["freight"]))
    out = []
    for e in sorted(items.values(), key=lambda e: -len(e["boqs"])):
        bys = {
            k: {"n": len(v), "median": Decimal(statistics.median(v)).quantize(Decimal("0.001"))}
            for k, v in e["by_surface"].items()
        }
        pick = (
            bys.get(surface or "")
            or bys.get("any")
            or (max(bys.values(), key=lambda x: x["n"]) if bys else None)
        )
        out.append({
            "label": e["label"], "product_id": e["product_id"], "boqs": len(e["boqs"]), "consumption_by_surface": bys,
            "consumption": pick["median"] if pick else None,
            "consumption_from": (f"old BOQ: {len(e['boqs'])} BOQ(s), {'on ' + surface if surface and surface in bys else 'all surfaces'}") if pick else None,
            "price_median": money(statistics.median(e["price"])) if e["price"] else None,
            "freight_median": money(statistics.median(e["freight"])) if e["freight"] else None,
            "freight_near": money(statistics.median(e["freight_near"])) if e["freight_near"] else None,
        })  # fmt: skip
    return {
        "products": out[:15],
        "labour_sqft": money(statistics.median(labour)) if labour else None,
        "surface_prep_sqm": money(statistics.median(prep)) if prep else None,
        "workings": sum(1 for ln in members(db, t) if ln.working),
    }


# --- proposing templates for a new main item ----------------------------------------------------------


SURFACE_NAME = {
    "rcc": "RCC",
    "brick": "brick",
    "plaster": "plaster",
    "screed": "screed",
    "old_tiles": "old tiles",
    "metal": "metal",
}


def score(t: KnowledgeTemplate, area, surface, coats, kg, dft, protection, brand, text_words,
          city_lines: int, region_lines: int) -> tuple[float, list[str]]:  # fmt: skip
    """How well the template fits, and why: the area must be the one asked; then the surface and
    the client's requirements; then the past rates near the place (the city, then the region)
    and the number of BOQs it comes from. -1: not this area."""
    why: list[str] = []
    s = 0.0
    if area:
        if t.area_type != area:
            return -1, ["another area"]
        why.append(f"area {extract.AREA_LABEL.get(area, area)} ✓")
    if surface:
        if t.surface == surface:
            s += 6
            why.append(f"surface {SURFACE_NAME.get(surface, surface)} ✓")
        elif t.surface:
            why.append(
                f"surface {SURFACE_NAME.get(t.surface, t.surface)} (asked {SURFACE_NAME.get(surface, surface)})"
            )
    if coats:
        if t.coats == coats:
            s += 10
            why.append(f"{coats} coats ✓")
        elif t.coats:
            s -= 4
            why.append(f"{t.coats} coats (asked {coats})")
    if kg:
        if t.min_kg_sqm and Decimal(t.min_kg_sqm) == Decimal(kg):
            s += 10
            why.append(f"{kg} kg/sqm ✓")
        elif t.min_kg_sqm and abs(Decimal(t.min_kg_sqm) - Decimal(kg)) <= Decimal("0.3"):
            s += 4
            why.append(f"{t.min_kg_sqm.normalize():f} kg/sqm, close to {kg}")
    if dft and t.dft_mm and Decimal(t.dft_mm) == Decimal(dft):
        s += 10
        why.append(f"{dft} mm DFT ✓")
    desc = (t.description or "").lower()
    if protection and protection in desc:
        s += 3
        why.append(f"{protection} protection ✓")
    if brand and brand.split()[0].lower() in desc:
        s += 4
        why.append(f"{brand} ✓")
    if text_words:
        sim = jaccard(text_words, words(t.description))
        s += 20 * sim
        if sim >= 0.3:
            why.append(f"words {round(100 * sim)} % alike")
    near = min(24, 4 * city_lines) + min(12, 1.5 * region_lines)
    s += near
    if city_lines or region_lines:
        why.append(f"{city_lines} rate(s) in the city, {region_lines} in the region")
    else:
        why.append("no past rate near the place")
    s += min(16, 4 * math.log1p(t.files_count or 0))
    why.append(f"{t.files_count} BOQ(s)")
    return s, why


def propose(db: Session, area=None, surface=None, coats=None, kg=None, dft=None, protection=None, brand=None, city=None,
            unit="sqm", text=None, limit=6, with_cost=False) -> list[dict]:  # fmt: skip
    """The templates that fit what was picked, best first (how well they match, then the rates near
    the place and the number of BOQs), each with why it ranks there, its products and consumption
    for that surface, its steps, and the past rates near the place (margins for cost users). A
    template without workings still shows: its rates and products are useful."""
    q = select(KnowledgeTemplate).where(
        KnowledgeTemplate.hidden.is_(False),
        KnowledgeTemplate.merged_into_id.is_(None),
        KnowledgeTemplate.lines_count > 0,
    )
    if unit:
        q = q.where(KnowledgeTemplate.unit == ("sqm" if unit in ("sqm", "sqft", "sft") else unit))
    if area:
        q = q.where(KnowledgeTemplate.area_type == area)
    tw = words(text) if text else set()
    region = region_of(db, city)
    city_count: Counter = Counter()
    region_count: Counter = Counter()
    if city:
        for tid, lcity, lregion in db.execute(select(KnowledgeLine.template_id, KnowledgeLine.city, KnowledgeLine.region).where(
                KnowledgeLine.template_id.is_not(None), (KnowledgeLine.city.ilike(city)) | (KnowledgeLine.region == region))):  # fmt: skip
            if lcity and lcity.lower() == city.lower():
                city_count[tid] += 1
            elif region and lregion == region:
                region_count[tid] += 1
    cand = []
    for t in db.scalars(q):
        sc, why = score(
            t,
            area,
            surface,
            int(coats) if coats else None,
            kg,
            dft,
            protection,
            brand,
            tw,
            city_count[t.id],
            region_count[t.id],
        )
        if sc >= 0:
            cand.append((sc, why, t))
    cand.sort(key=lambda x: -x[0])
    out = []
    best = cand[0][0] if cand else 1
    for sc, why, t in cand[:limit]:
        r = rates(db, t, city, with_cost)
        workings = (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeLine)
                .where(KnowledgeLine.template_id == t.id, KnowledgeLine.working.is_not(None))
            )
            or 0
        )
        if not workings:
            why.append("no working to price, fill from the system")
        item = template_brief(t) | {
            "score": round(sc, 1), "why": why, "workings": workings,
            "confidence": round(min(100.0, 100 * sc / max(best, 1)) if best > 0 else 0, 0),
            "rates": {k: r[k] for k in ("city", "region", "city_stats", "region_stats", "all_stats", "unit")},
        }  # fmt: skip
        if with_cost:
            item["products"] = products(db, t, surface, city)
            item["margins"] = margins(db, t)
        out.append(item)
    return out


def template_brief(t: KnowledgeTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "area_type": t.area_type, "area_label": extract.AREA_LABEL.get(t.area_type or "", None),
        "surface": t.surface, "coats": t.coats, "min_kg_sqm": t.min_kg_sqm, "dft_mm": t.dft_mm, "families": t.families,
        "unit": t.unit, "description": t.description, "steps": t.steps, "steps_source": t.steps_source, "lines": t.lines_count,
        "boqs": t.files_count, "median_rate": t.median_rate, "latest_on": t.latest_on, "hidden": t.hidden, "reviewed": t.reviewed,
        "to_check": t.to_check,
    }  # fmt: skip


# --- filling a rate working from a template ----------------------------------------------------------


def fill_group(db: Session, g, t: KnowledgeTemplate, city: str | None, surface: str | None = None, coats: int | None = None,
               kg=None, dft=None, user_id=None) -> dict:  # fmt: skip
    """The main item's working from the template: products and consumption (source "old BOQ"),
    today's prices from the master price list, the freight our workings near the place used (else
    the master's), labour from the rate card (else the template's), surface preparation, and the
    margin we carried. Then the gap to the median we sold at near the place."""
    from app.costing import prices, working  # noqa: PLC0415
    from app.costing.models import RateWorking  # noqa: PLC0415

    p = products(db, t, surface or t.surface, city)
    g.surface = surface or t.surface
    g.coats = coats or t.coats
    g.req_min_kg_sqm = Decimal(str(kg)) if kg else t.min_kg_sqm
    g.req_dft_mm = Decimal(str(dft)) if dft else t.dft_mm
    g.note = f"From the library: {t.name} (template {t.id})"[:2000]
    g.products = []
    missing, added = [], []
    for i, it in enumerate(x for x in p["products"] if x["consumption"] is not None):
        if not it["product_id"]:
            # not in the product master: on the list of products to review (planning decides)
            r = to_review(db, it, t)
            added.append(
                {"label": it["label"], "review_id": r.id, "old_price": it.get("price_median")}
            )
            missing.append(it["label"])
            continue
        prod = working.new_product(
            db,
            it["product_id"],
            it["consumption"],
            i,
            f"old BOQ: {t.name}, {it['consumption_from']}"[:300],
        )
        if prod.price is None and it["price_median"]:
            # in the master without a price yet: the price our old workings used, to check
            from app.costing import prices  # noqa: PLC0415

            rec = prices.record_price(db, it["product_id"], Decimal(it["price_median"]), source="manual", user_id=user_id,
                                      ref=f"knowledge template {t.id}", note=f"The price our old BOQ workings used (template {t.name}); check it")  # fmt: skip
            prod.price, prod.price_id = Decimal(it["price_median"]), rec.id if rec else None
        if it["freight_near"] is not None:
            prod.freight_used = it["freight_near"]
        elif prod.freight_used in (None, 0) and it["freight_median"] is not None:
            prod.freight_used = it["freight_median"]
        g.products.append(prod)
    if p["surface_prep_sqm"] is not None:
        g.surface_prep = p["surface_prep_sqm"]
    if g.labour_rate_card_id:
        working.labour_from_card(db, g)
    elif p["labour_sqft"] is not None:
        g.labour_used_sqft = p["labour_sqft"]
    m = margins(db, t)
    w = db.get(RateWorking, g.working_id)
    basis = working.margin_basis(db, w)
    if m["all"]:
        sell = Decimal(str(m["all"]["median"]))
        g.margin_percent = (
            sell if basis == "selling" else (sell / (100 - sell) * 100).quantize(Decimal("0.01"))
        )
    db.flush()
    result = working.work(db, g)
    gap = gap_to_past(db, t, g, city, result)
    _ = prices  # today's prices come from new_product (the master price list)
    return {
        "result": result,
        "gap": gap,
        "missing_products": missing,
        "added_products": added,
        "margins": m,
        "products": p,
    }


def suggest_match(db: Session, name: str) -> int | None:
    """The existing product whose name is closest (words alike), when close enough."""
    from app.masters.models import Product  # noqa: PLC0415

    w = words(name)
    best, sim = None, 0.0
    for p in db.scalars(select(Product).where(Product.is_active.is_(True))):
        s = jaccard(w, words(" ".join([p.name, *(p.aliases or [])])))
        if s > sim:
            best, sim = p.id, s
    return best if sim >= 0.3 else None


def to_review(db: Session, it: dict, t: KnowledgeTemplate) -> ProductReview:
    """A product a template's workings used that the master does not have: put on the list of
    products to review (never straight into the master)."""
    label = " ".join((it.get("label") or "").split())[:200]
    r = db.scalar(
        select(ProductReview).where(
            func.lower(ProductReview.name) == label.lower(), ProductReview.status == "pending"
        )
    )
    if r is None:
        r = ProductReview(name=label, unit=None, old_price=it.get("price_median"), template_id=t.id,
                          source=f"{it.get('boqs', 0)} old BOQ working(s) of template {t.name}"[:2000],
                          suggested_product_id=suggest_match(db, label))  # fmt: skip
        db.add(r)
        db.flush()
    return r


def accept_review(db: Session, r, name: str | None, unit: str, user_id) -> int:
    """Planning accepts it: a product of the master, with the old price as its first price (to
    check). Returns the product id."""
    import re  # noqa: PLC0415

    from app.costing import prices  # noqa: PLC0415
    from app.masters.models import Product  # noqa: PLC0415

    label = (name or r.name).strip()
    code = ("BOQ-" + re.sub(r"[^A-Z0-9]+", "-", label.upper()).strip("-"))[:50]
    p = db.scalar(select(Product).where(Product.code == code))
    if p is None:
        p = Product(
            code=code,
            name=label[:200],
            unit=unit,
            aliases=[r.name.lower()[:200]],
            created_by=user_id,
        )
        db.add(p)
        db.flush()
    if r.old_price and prices.current(db, p.id) is None:
        prices.record_price(db, p.id, Decimal(r.old_price), source="manual", user_id=user_id, ref=f"product review {r.id}",
                            note=f"The price our old BOQ workings used ({r.source}); check it")  # fmt: skip
    return p.id


def merge_review(db: Session, r, product_id: int) -> None:
    """It is a product we have: its name becomes an alias, so the workings find it next time."""
    from app.masters.models import Product  # noqa: PLC0415

    p = db.get(Product, product_id)
    if p is None:
        raise ValueError("Unknown product")
    if r.name.lower() not in [a.lower() for a in (p.aliases or [])]:
        p.aliases = [*(p.aliases or []), r.name.lower()[:200]]


def gap_to_past(
    db: Session, t: KnowledgeTemplate, g, city: str | None, result: dict | None = None
) -> dict:
    """The worked rate today against the median we sold at for this template near the place,
    flagged past the setting (15 %), with the likely reason."""
    from app.costing import prices  # noqa: PLC0415

    median, where = near_median(db, t, city)
    rate = g.rate_sqm if t.unit == "sqm" else g.rate_sqm
    limit = Decimal(prices.settings(db).library_diff_flag_percent)
    if median is None or rate is None:
        return {
            "median": median,
            "where": where,
            "rate": rate,
            "diff_percent": None,
            "flagged": False,
            "reasons": [],
            "limit": limit,
        }
    diff = ((Decimal(rate) - median) / median * 100).quantize(Decimal("0.1"))
    reasons = []
    lines = [ln for ln in members(db, t) if ln.margin_percent is not None]
    if lines:
        past_m = Decimal(statistics.median([Decimal(ln.margin_percent) for ln in lines]))
        from app.costing.models import RateWorking  # noqa: PLC0415
        from app.costing.working import margin_basis  # noqa: PLC0415

        now_m = Decimal(g.margin_percent or 0)
        if margin_basis(db, db.get(RateWorking, g.working_id)) == "cost":
            now_m = now_m / (100 + now_m) * 100
        if abs(now_m - past_m) >= 2:
            reasons.append(
                f"different margin: {round(now_m, 1)} % now against {round(past_m, 1)} % carried before"
            )
        costs = [Decimal(ln.cost_sqm) for ln in lines if ln.cost_sqm]
        if costs and g.cost_sqm:
            past_c = Decimal(statistics.median(costs))
            if past_c and abs(Decimal(g.cost_sqm) - past_c) / past_c > Decimal("0.08"):
                reasons.append(
                    f"cost {money(g.cost_sqm)} per sqm now against {money(past_c)} before (price change or different consumption)"
                )
    p = products(db, t, g.surface, city)
    past = {x["product_id"]: x for x in p["products"] if x["product_id"]}
    for prod in g.products:
        x = past.get(prod.product_id)
        if (
            x
            and x["consumption"]
            and prod.consumption
            and abs(Decimal(prod.consumption) - Decimal(x["consumption"]))
            / Decimal(x["consumption"])
            > Decimal("0.1")
        ):
            reasons.append(
                f"different consumption: {prod.consumption} against {x['consumption']} in the old BOQs"
            )
        if (
            x
            and x["price_median"]
            and prod.price
            and abs(Decimal(prod.price) - Decimal(x["price_median"])) / Decimal(x["price_median"])
            > Decimal("0.1")
        ):
            reasons.append(
                f"price change: {x['label']} ₹{prod.price} now against ₹{x['price_median']} in the old workings"
            )
    if abs(diff) > limit and not reasons:
        reasons.append(
            "the old BOQs near here had a different scope or market rate (no working to compare)"
        )
    return {
        "median": median,
        "where": where,
        "rate": money(rate),
        "diff_percent": diff,
        "flagged": abs(diff) > limit,
        "reasons": reasons[:6],
        "limit": limit,
    }


# --- an imported client BOQ: each line matched to a template --------------------------------------------


def match_text(
    db: Session, description: str, unit: str | None, city: str | None
) -> tuple[KnowledgeTemplate | None, Decimal]:
    req = extract.requirements(description)
    head = extract.requirements(description.split(".")[0])
    area = head.area_type or req.area_type
    found = propose(db, area=area, surface=req.surface, coats=req.coats, kg=req.min_kg_sqm, dft=req.dft_mm, protection=req.protection,
                    brand=req.brands[0] if req.brands else None, city=city, unit=(unit or "sqm").lower(), text=description, limit=3)  # fmt: skip
    if not found:
        return None, Decimal(0)
    top = found[0]
    t = db.get(KnowledgeTemplate, top["id"])
    sim = jaccard(words(description), words(t.description))
    conf = Decimal(
        str(
            min(
                99,
                round(
                    40 * (1 if area else 0.5)
                    + 60 * sim
                    + (5 if req.surface and t.surface == req.surface else 0)
                ),
            )
        )
    )
    return t, conf


# --- learning from a won (or final) BOQ ---------------------------------------------------------------


def learn(db: Session, w, city: str | None, on: date | None = None) -> int:
    """A won BOQ's workings become new evidence: a line per worked main item, with place and date."""
    from app.costing import working  # noqa: PLC0415
    from app.masters.models import Product  # noqa: PLC0415

    on = on or ist_today()
    db.query(KnowledgeLine).filter(
        KnowledgeLine.source == "won",
        (KnowledgeLine.tender_id == w.tender_id)
        if w.tender_id
        else (KnowledgeLine.quotation_id == w.quotation_id),
    ).delete(synchronize_session=False)
    lines = {x["key"]: x for x in working.client_lines(db, w)}
    n = 0
    for g in w.groups:
        if g.rate_sqm is None:
            continue
        mine = [lines[working._line_key(gl)] for gl in g.lines if working._line_key(gl) in lines]
        desc = max((x["description"] or "" for x in mine), key=len, default=g.name)
        req = extract.requirements(g.name, desc)
        result = working.work(db, g)
        items = [{"label": db.get(Product, p.product_id).name, "kind": "product", "consumption": str(p.consumption), "price": str(p.price),
                  "freight": str(p.freight_used), "amount": None, "ref": f"working {w.id}"} for p in g.products if p.consumption is not None]  # fmt: skip
        margin = Decimal(result.get("margin_sqm") or 0)
        sell = (
            (margin / Decimal(g.rate_sqm) * 100).quantize(Decimal("0.01")) if g.rate_sqm else None
        )
        db.add(KnowledgeLine(
            source="won", tender_id=w.tender_id, quotation_id=w.quotation_id, sheet=f"rate working {w.id}", description=desc or g.name,
            unit="sqm", rate=g.rate_sqm, rate_sqm=g.rate_sqm, area_type=req.area_type, surface=g.surface or req.surface,
            coats=g.coats or req.coats, min_kg_sqm=g.req_min_kg_sqm or req.min_kg_sqm, dft_mm=g.req_dft_mm or req.dft_mm,
            requirements=req.as_dict(), cost_sqm=g.cost_sqm, margin_percent=sell, city=city, region=None, on_date=on,
            working={"items": items, "cost": str(g.cost_sqm), "margin_on_selling_percent": str(sell) if sell is not None else None,
                     "labour_sqft": str(g.labour_used_sqft), "surface_prep_sqm": str(g.surface_prep), "rate": str(g.rate_sqm)},
        ))  # fmt: skip
        n += 1
    db.flush()
    for ln in db.scalars(
        select(KnowledgeLine).where(
            KnowledgeLine.source == "won",
            KnowledgeLine.region.is_(None),
            KnowledgeLine.city.is_not(None),
        )
    ):
        ln.region = region_of(db, ln.city)
    from app.knowledge.library import group  # noqa: PLC0415

    group(db)
    return n
