# ruff: noqa: E501
"""The margin check against the BOQ rate: per BOQ line, the material cost per unit (the library's
coverage × (1 + wastage) × the product's price from the rate library, freight included), the
labour if the working has it, and the margin on the selling price (as agreed: (rate − cost) ÷
rate). Material alone over the director's share of the rate (70% unless set) is a warning: on Juno
item iv the client sheet's figures put material at about 91% of ₹1,072/sqm.

Products the client supplies free of cost (cement, sand ...) are left out of our cost and printed in
the T&C. A product with no coverage in the library is listed: the check never looks complete when
it is not."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.costing import prices
from app.costing.models import RateGroup, RateGroupLine, RateWorking
from app.estimate import library as lib
from app.masters.models import Product
from app.tenders.export import inr

D = Decimal
ZERO = D(0)


def _money(v: Decimal) -> Decimal:
    return D(v).quantize(D("0.01"), ROUND_HALF_UP)


def _per_sqm(rate: Decimal | None, unit: str | None) -> Decimal | None:
    if rate is None:
        return None
    u = (unit or "sqm").lower().replace(".", "").replace(" ", "")
    if u in ("sqft", "sft", "ft2"):
        return D(rate) * lib.SQFT_PER_SQM
    if u in ("sqm", "sqmt", "m2", "smt"):
        return D(rate)
    return None  # a rate per No or per rmt is not compared per sqm


def material_sqm(db: Session, g: RateGroup, free: set[int]) -> dict:
    """The group's material per sqm from the library: each product's coverage × (1 + wastage) ×
    (price + freight); free-issue products out; products with no coverage or no price listed."""
    rows, missing, no_price, free_rows = [], [], [], []
    total = ZERO
    for gp in g.products:
        p = db.get(Product, gp.product_id)
        if gp.product_id in free:
            free_rows.append(p.name)
            continue
        c = lib.coverage_for(db, gp.product_id, g.system_id)
        if c is None:
            missing.append(p.name)
            continue
        pr = prices.current(db, gp.product_id)
        if pr is None:
            no_price.append(p.name)
            continue
        q = lib.per_sqm(c.value, c.unit)
        w = lib.wastage(p)
        unit_price = D(pr.purchase_rate) + D(pr.freight_per_unit or 0)
        cost = q * (1 + w / 100) * unit_price
        total += cost
        rows.append({"product_id": p.id, "product": p.name, "coverage": lib.label(c), "per_sqm": q, "wastage_percent": w, "price": unit_price, "cost_sqm": _money(cost),
                     "how": f"{lib.n(q, 4)} {p.unit}/sqm × (1 + {lib.n(w, 2)}%) × {inr(unit_price)}"})  # fmt: skip
    return {"total": _money(total), "rows": rows, "no_coverage": missing, "no_price": no_price, "free_issue": free_rows}


def check(db: Session, w: RateWorking) -> dict:
    s = prices.settings(db)
    share_limit = D(s.material_share_warn_percent or 70)
    free = set(w.free_issue_product_ids or [])
    out = []
    for g in w.groups:
        mat = material_sqm(db, g, free)
        labour = D(g.labour_used_sqft) * lib.SQFT_PER_SQM if g.labour_used_sqft else None
        prep = D(g.surface_prep or 0)
        lines = list(db.scalars(select(RateGroupLine).where(RateGroupLine.group_id == g.id)))
        targets = []
        for gl in lines:
            if gl.boq_line_id:
                from app.tenders.models import BoqLine  # noqa: PLC0415

                b = db.get(BoqLine, gl.boq_line_id)
                targets.append((b.client_item_no or str(b.id), b.description, b.unit or b.unit_raw, b.rate))
            elif gl.quotation_line_id:
                from app.quotations.models import QuotationLine  # noqa: PLC0415

                ql = db.get(QuotationLine, gl.quotation_line_id)
                targets.append((str(ql.sort_order + 1), ql.description, ql.uom, ql.rate))
        if not targets:
            targets.append((g.name, g.name, "sqm", g.rate_sqm))
        for item, desc, unit, rate in targets:
            rate_sqm = _per_sqm(rate, unit) if rate is not None else (D(g.rate_sqm) if g.rate_sqm is not None else None)
            row = {"group_id": g.id, "group": g.name, "item": item, "description": (desc or "")[:200], "unit": unit, "rate": rate, "rate_sqm": _money(rate_sqm) if rate_sqm is not None else None,
                   "material_sqm": mat["total"], "labour_sqm": _money(labour) if labour is not None else None, "surface_prep_sqm": _money(prep), "materials": mat["rows"],
                   "no_coverage": mat["no_coverage"], "no_price": mat["no_price"], "free_issue": mat["free_issue"], "warnings": []}  # fmt: skip
            if rate_sqm is None or rate_sqm <= 0:
                row["warnings"].append("No rate per sqm to compare with")
            else:
                cost = mat["total"] + (labour or ZERO) + prep
                row["cost_sqm"] = _money(cost)
                row["material_share_percent"] = (mat["total"] / rate_sqm * 100).quantize(D("0.1"), ROUND_HALF_UP)
                row["margin_percent"] = ((rate_sqm - cost) / rate_sqm * 100).quantize(D("0.1"), ROUND_HALF_UP)
                if row["material_share_percent"] > share_limit:
                    row["warnings"].append(f"Material alone is {lib.n(row['material_share_percent'], 1)}% of the rate {inr(rate_sqm)}/sqm (over {lib.n(share_limit, 1)}%)")
                if labour is None:
                    row["warnings"].append("No labour estimate in the working: the margin is before labour")
            if mat["no_coverage"]:
                row["warnings"].append(f"No coverage in the library for {', '.join(mat['no_coverage'])}: material is not complete")
            if mat["no_price"]:
                row["warnings"].append(f"No price for {', '.join(mat['no_price'])}: material is not complete")
            out.append(row)
    return {"working_id": w.id, "share_limit_percent": share_limit, "basis": "selling", "lines": out,
            "free_issue": [db.get(Product, pid).name for pid in sorted(free) if db.get(Product, pid)]}  # fmt: skip
