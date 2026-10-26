# ruff: noqa: E501
"""Mix designs: what a sqm of nodular concrete, cement-sand plaster or brick bat needs.

Per component: thickness (m) × dry-volume factor × its parts ÷ all parts × its bulk density
(kg/m³). The admixture is dosed per bag of cement (0.5 L polymer per 50 kg bag; Technomix WL
200 ml per bag): cement kg ÷ bag kg × dose. When the planning sheet rounds the kg per sqft (to 2
decimals: 3.52 kg/sqft of nodular and of cement at 165 mm, 2.77 at 130 mm), so does the mix
(round_sqft), and the per-sqm figure is that rounded figure × 10.7639, so the site's request
shows the same numbers as the planning sheet."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.estimate.library import SQFT_PER_SQM, n
from app.estimate.models import MixDesign
from app.masters.models import Product

D = Decimal


@dataclass
class Part:
    role: str
    product_id: int | None
    product: str | None
    unit: str  # kg, L
    per_sqm: Decimal
    per_sqft: Decimal
    how: str


def parts(db: Session, mix: MixDesign, thickness_mm: Decimal | None = None) -> list[Part]:
    t = D(thickness_mm if thickness_mm is not None else mix.thickness_mm)
    comps = mix.components or []
    total = sum((D(str(c.get("parts") or 0)) for c in comps), D(0))
    out: list[Part] = []
    cement_sqm = None
    for c in comps:
        share = D(str(c.get("parts") or 0))
        if not share or not total:
            continue
        density = D(str(c.get("density") or 0))
        raw = t / 1000 * D(mix.dry_volume_factor) * share / total * density
        per_sqft = raw / SQFT_PER_SQM
        if mix.round_sqft is not None:
            per_sqft = per_sqft.quantize(D(1).scaleb(-mix.round_sqft), ROUND_HALF_UP)
            raw = per_sqft * SQFT_PER_SQM
        p = db.get(Product, c["product_id"]) if c.get("product_id") else None
        how = f"{n(t, 1)} mm × {n(mix.dry_volume_factor, 4)} × {n(share)}/{n(total)} × {n(density)} kg/m³"
        if mix.round_sqft is not None:
            how += f" = {n(per_sqft, mix.round_sqft)} kg/sqft"
        part = Part(c.get("role") or (p.name if p else "?"), p.id if p else None, p.name if p else None, "kg", raw, per_sqft, how)
        if part.role == "cement":
            cement_sqm = raw
        out.append(part)
    if mix.admixture_product_id and mix.admixture_per_bag and cement_sqm:
        p = db.get(Product, mix.admixture_product_id)
        dose = D(mix.admixture_per_bag)
        q = cement_sqm / D(mix.cement_bag_kg) * dose
        unit = p.unit if p else "L"
        out.append(Part("admixture", p.id if p else None, p.name if p else None, unit, q, q / SQFT_PER_SQM,
                        f"cement {n(cement_sqm)} kg/sqm ÷ {n(mix.cement_bag_kg)} kg bag × {n(dose, 4)} {unit} per bag"))
    return out


def part_for(db: Session, mix: MixDesign, product_id: int, thickness_mm: Decimal | None) -> Part | None:
    return next((p for p in parts(db, mix, thickness_mm) if p.product_id == product_id), None)
