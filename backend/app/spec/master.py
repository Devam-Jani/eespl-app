# ruff: noqa: E501  (the change rows read better unwrapped)
"""The consumption master: every work item (system) with its unit, the areas it fits, its type and
its brand options, each option's BOM beside its products' data-sheet ranges, today's prices, the
material cost, labour and selling rate at the default margin. Every change is kept (who, when, the
old and new value, why); an issued estimate and a sent quotation keep the figures they used (the
estimate's snapshot, the working locked on submit)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.costing import prices
from app.masters.bom import _code, norm
from app.masters.models import Product, System, SystemComponent, SystemOption
from app.spec import suggest, vocab
from app.spec.models import ConsumptionChange

FIELDS = ("consumption_per_unit", "wastage_percent", "wastage_included", "coats")


class MasterError(ValueError):
    pass


def _s(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return f"{v.normalize():f}"
    return str(v)


def change(
    db: Session,
    system: System,
    what: str,
    field: str,
    old,
    new,
    reason: str | None,
    user_id,
    option_id=None,
    component_id=None,
) -> None:
    if _s(old) == _s(new):
        return
    db.add(ConsumptionChange(system_id=system.id, option_id=option_id, component_id=component_id, what=what[:200], field=field,
                             old=_s(old), new=_s(new), reason=(reason or "").strip()[:500] or None, changed_by=user_id))  # fmt: skip


def _matches(db: Session, s: System, q: str) -> bool:
    q = q.lower().strip()
    if not q:
        return True
    hay = [s.name, s.description or "", *(o.brand for o in s.options), *(c.product.name for c in s.components),
           *(c.product.brand or "" for c in s.components), *(vocab.USE_LABEL.get(a, a) for a in suggest.system_areas(db, s))]  # fmt: skip
    return all(any(w in h.lower() for h in hay) for w in q.split())


def items(
    db: Session,
    q: str = "",
    area: str | None = None,
    with_cost: bool = False,
    system_id: int | None = None,
) -> list[dict]:
    stmt = select(System).order_by(System.name)
    if system_id:
        stmt = stmt.where(System.id == system_id)
    systems = [s for s in db.scalars(stmt) if _matches(db, s, q)]
    pids = {c.product_id for s in systems for c in s.components}
    facts = suggest.facts_by_product(db, pids)
    cur = prices.current_many(db, list(pids)) if with_cost else {}
    out = []
    for s in systems:
        areas = suggest.system_areas(db, s)
        if area and area not in areas:
            continue
        options = []
        for o in s.options or [None]:
            oid = o.id if o else None
            rows = suggest.bom_rows(s, oid, facts)
            if with_cost:
                for r in rows:
                    p = cur.get(r["product_id"])
                    r["price"] = prices.price_out(db, p)
                    r["price_per_unit"] = prices.base_price(db, p)[0] if p else None
            options.append({
                "id": oid, "brand": o.brand if o else None, "is_default": bool(o and o.is_default), "source": o.source if o else None,
                "mix_design_id": o.mix_design_id if o else None, "mix_thickness_mm": o.mix_thickness_mm if o else None,
                "rows": rows, "warnings": [f"{r['product']}: BOM {vocab.q(r['per_unit'], 3)} per {r['per_unit_label']} is outside the TDS {vocab.q(r['tds_range']['lo'], 3)}–{vocab.q(r['tds_range']['hi'], 3)}"
                                           for r in rows if r["outside_tds"]],
                "cost": suggest._cost(db, s, oid) if with_cost else None,
            })  # fmt: skip
        out.append({
            "id": s.id, "code": s.code, "name": s.name, "unit": s.unit, "is_active": s.is_active, "source": s.source,
            "areas": sorted(areas), "areas_set": bool(s.area_keys), "type": suggest.system_type(s, s.recipe(), facts), "type_set": bool(s.spec_type),
            "labour_rate": s.labour_rate if with_cost else None, "labour_unit": s.labour_unit, "default_margin_percent": s.default_margin_percent if with_cost else None,
            "options": options,
        })  # fmt: skip
    return out


def history(db: Session, system_id: int) -> list[ConsumptionChange]:
    return list(
        db.scalars(
            select(ConsumptionChange)
            .where(ConsumptionChange.system_id == system_id)
            .order_by(ConsumptionChange.changed_at.desc(), ConsumptionChange.id.desc())
        )
    )


def add_item(
    db: Session, name: str, unit: str, areas: list[str], spec_type: str | None, user_id
) -> System:
    name = " ".join(name.split())
    if not name:
        raise MasterError("Give the work item a name")
    if db.scalar(select(System.id).where(System.name == name, System.unit == unit)):
        raise MasterError(f"{name} per {unit} is already a work item")
    s = System(code=_code(db, "CM", f"{norm(name)}|{unit}", System), name=name, unit=unit, area_keys=areas, spec_type=spec_type,
               labour_unit=unit if unit in ("sqm", "sqft", "rmt", "rft", "nos") else "sqm", created_by=user_id)  # fmt: skip
    db.add(s)
    db.flush()
    change(db, s, s.name, "created", None, f"per {unit}", None, user_id)
    return s


def set_item(db: Session, s: System, data: dict, reason: str | None, user_id) -> None:
    for field in (
        "name",
        "area_keys",
        "spec_type",
        "labour_rate",
        "labour_unit",
        "default_margin_percent",
        "is_active",
    ):
        if field in data:
            old = getattr(s, field)
            new = data[field]
            if field == "area_keys":
                unknown = set(new) - set(vocab.USE_LABEL)
                if unknown:
                    raise MasterError(f"Unknown area: {', '.join(sorted(unknown))}")
                old, new = ", ".join(sorted(old or [])), sorted(new)
                change(db, s, s.name, field, old, ", ".join(new), reason, user_id)
                s.area_keys = new
                continue
            if field == "spec_type" and new and new not in vocab.TYPE_LABEL:
                raise MasterError("Unknown system type")
            change(db, s, s.name, field, old, new, reason, user_id)
            setattr(s, field, new)
    db.flush()


def _option(s: System, option_id: int | None) -> SystemOption | None:
    if option_id is None:
        return None
    o = next((x for x in s.options if x.id == option_id), None)
    if o is None:
        raise MasterError("That brand option is not one of the work item's")
    return o


def add_option(db: Session, s: System, brand: str, user_id) -> SystemOption:
    brand = " ".join(brand.split())
    if not brand:
        raise MasterError("Name the brand")
    if any(o.brand.lower() == brand.lower() for o in s.options):
        raise MasterError(f"{brand} is already an option of {s.name}")
    o = SystemOption(
        system_id=s.id,
        brand=brand,
        is_default=not s.options,
        sort_order=len(s.options),
        source="manual",
        created_by=user_id,
    )
    s.options.append(o)
    db.flush()
    change(db, s, f"{brand}", "option added", None, brand, None, user_id, option_id=o.id)
    return o


def copy_option(
    db: Session, s: System, option_id: int, brand: str, swaps: dict[int, int], user_id
) -> SystemOption:
    """The option copied to another brand, each product swapped for that brand's where given."""
    src = _option(s, option_id)
    o = add_option(db, s, brand, user_id)
    for c in [c for c in s.components if c.option_id == src.id]:
        pid = swaps.get(c.product_id, c.product_id)
        if db.get(Product, pid) is None:
            raise MasterError("Unknown product to swap in")
        s.components.append(SystemComponent(system_id=s.id, product_id=pid, consumption_per_unit=c.consumption_per_unit, wastage_percent=c.wastage_percent,
                                            coats=c.coats, option_id=o.id, wastage_included=c.wastage_included, note=f"copied from {src.brand}",
                                            created_by=user_id))  # fmt: skip
    db.flush()
    change(
        db,
        s,
        brand,
        "option copied",
        src.brand,
        brand,
        f"{len(swaps)} product(s) swapped" if swaps else None,
        user_id,
        option_id=o.id,
    )
    return o


def set_component(
    db: Session, s: System, c: SystemComponent, data: dict, reason: str | None, user_id
) -> None:
    """Consumption (per the work item's unit), wastage, "wastage included", coats; each change kept."""
    if not reason or len(reason.strip()) < 3:
        raise MasterError("Say why the figure changes (it is kept with the change)")
    brand = db.get(SystemOption, c.option_id).brand if c.option_id else "every option"
    for field in FIELDS:
        if field in data:
            v = data[field]
            if (
                field in ("consumption_per_unit", "wastage_percent")
                and v is not None
                and Decimal(str(v)) < 0
            ):
                raise MasterError("A figure cannot be below 0")
            change(
                db,
                s,
                f"{brand}: {c.product.name}",
                field,
                getattr(c, field),
                v,
                reason,
                user_id,
                option_id=c.option_id,
                component_id=c.id,
            )
            setattr(c, field, v)
            if (
                field == "consumption_per_unit"
            ):  # still the company's figure: its history says who changed it
                c.to_confirm = v is None
    db.flush()


def add_component(
    db: Session,
    s: System,
    option_id: int | None,
    product_id: int,
    consumption,
    coats,
    wastage,
    user_id,
) -> SystemComponent:
    o = _option(s, option_id)
    p = db.get(Product, product_id)
    if p is None:
        raise MasterError("Unknown product")
    c = SystemComponent(system_id=s.id, product_id=p.id, consumption_per_unit=consumption, coats=coats, wastage_percent=wastage or 0,
                        option_id=o.id if o else None, to_confirm=consumption is None, created_by=user_id)  # fmt: skip
    s.components.append(c)
    db.flush()
    change(
        db,
        s,
        f"{o.brand if o else 'every option'}: {p.name}",
        "product added",
        None,
        consumption,
        None,
        user_id,
        option_id=c.option_id,
        component_id=c.id,
    )
    return c


def remove_component(
    db: Session, s: System, c: SystemComponent, reason: str | None, user_id
) -> None:
    brand = db.get(SystemOption, c.option_id).brand if c.option_id else "every option"
    change(
        db,
        s,
        f"{brand}: {c.product.name}",
        "product removed",
        c.consumption_per_unit,
        None,
        reason,
        user_id,
        option_id=c.option_id,
    )
    s.components.remove(c)
    db.flush()


def attach_mix(
    db: Session, s: System, option_id: int | None, mix_id: int | None, thickness, user_id
) -> None:
    """A formulation (a waterproof screed): each of the mix's products is a component of the option
    with its consumption worked from the mix at this thickness (estimate.mix)."""
    from app.estimate import mix as mixes  # noqa: PLC0415
    from app.estimate.models import MixDesign  # noqa: PLC0415

    o = _option(s, option_id)
    if o is None:
        raise MasterError("Attach a formulation to a brand option")
    if mix_id is None:
        change(db, s, o.brand, "formulation", o.mix_design_id, None, None, user_id, option_id=o.id)
        o.mix_design_id = o.mix_thickness_mm = None
        db.flush()
        return
    mix = db.get(MixDesign, mix_id)
    if mix is None:
        raise MasterError("Unknown mix design")
    if s.unit not in ("sqm", "sqft"):
        raise MasterError(
            "A formulation is worked per area: the work item must be per sqm or sq ft"
        )
    t = Decimal(str(thickness)) if thickness is not None else Decimal(mix.thickness_mm)
    change(
        db,
        s,
        o.brand,
        "formulation",
        o.mix_design_id and f"{o.mix_design_id} @ {_s(o.mix_thickness_mm)} mm",
        f"{mix.code} @ {_s(t)} mm",
        None,
        user_id,
        option_id=o.id,
    )
    o.mix_design_id, o.mix_thickness_mm = mix.id, t
    mine = {c.product_id: c for c in s.components if c.option_id == o.id}
    for part in mixes.parts(db, mix, t):
        if part.product_id is None:
            continue
        per = part.per_sqm if s.unit == "sqm" else part.per_sqft
        c = mine.get(part.product_id)
        note = f"formulation {mix.code} at {_s(t)} mm: {part.how}"[:500]
        if c is None:
            c = SystemComponent(
                system_id=s.id,
                product_id=part.product_id,
                consumption_per_unit=vocab.q(per, 4),
                option_id=o.id,
                note=note,
                created_by=user_id,
            )
            s.components.append(c)
        else:
            change(
                db,
                s,
                f"{o.brand}: {c.product.name}",
                "consumption_per_unit",
                c.consumption_per_unit,
                vocab.q(per, 4),
                f"formulation at {_s(t)} mm",
                user_id,
                option_id=o.id,
                component_id=c.id,
            )
            c.consumption_per_unit, c.note = vocab.q(per, 4), note
    db.flush()
