# ruff: noqa: E501  (messages read better unwrapped)
"""The methodology of a BOQ: per main item its element and quantities, the conditions read from
the drawings and the BOQ text (toilet area from "TOILET 1480 X 2135", sunk depth, tank area and
depth, open or covered refuge; the water table by hand), the client's rule for that element and
condition, our system with the reason and the other options, and the compliance check against
the client's standard (green / red with the gap / to confirm). A make the client does not list is
red with two choices: an approved make, or keep ours and ask for its approval before the bid
(TPT). The estimator edits steps with a reason; each version is kept."""

import math
import re
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.methodology import vocab
from app.methodology.models import (
    TO_CONFIRM,
    ClientStandard,
    Methodology,
    MethodologyItem,
    MethodologyVersion,
    MethodProduct,
    MethodSystem,
    MethodSystemChange,
    PreBidQuery,
    StandardContradiction,
    StandardRule,
)

SMALL_TOILET_SQM = 4.5
# where our library has no system for the element itself, the ones that suit it
SUITS = {
    "toilet": ["toilet", "sunken", "balcony"],
    "balcony": ["balcony", "sunken"],
    "refuge": ["terrace", "balcony", "sunken"],
    "podium": ["podium", "terrace", "planter"],
    "oht": ["oht", "ug_tank"],
    "ug_tank": ["ug_tank", "oht"],
    "stp": ["stp", "ug_tank", "retaining_wall"],
    "lift_pit": ["lift_pit", "retaining_wall"],
    "footing": ["footing", "raft"],
    "kitchen": ["sunken", "balcony"],
}
CONDITION_LABEL = {"area_sqm": "Area", "exposure": "Open to sky / covered", "confined": "Confined", "water_table": "Water table",
                   "toilet_kind": "Sunken / underslung", "corrosive": "Corrosive soil", "face": "Face", "location": "Location"}  # fmt: skip
INFORMATIONAL = {"part"}


def new_code(db: Session) -> str:
    year = date.today().year
    n = (
        db.scalar(
            select(func.count())
            .select_from(Methodology)
            .where(Methodology.code.like(f"MS-{year}-%"))
        )
        or 0
    )
    while True:
        n += 1
        code = f"MS-{year}-{n:04d}"
        if not db.scalar(select(Methodology.id).where(Methodology.code == code)):
            return code


# --- conditions from the drawings and the BOQ text ------------------------------------------------


def places_from_texts(texts: list[list], unit_m: float | None, source: str) -> list[dict]:
    """Rooms with their size labels and the notes near them, and the tanks from the notes:
    [{name, element, label, area_sqm, sunk_m, depth_m, capacity_l, source}]."""
    from app.takeoff import service as takeoff

    cands, _loose = takeoff.find_areas(texts, unit_m, set(), 3.0, None, None)
    out = []
    for c in cands:
        el = vocab.element_of(c["name"])
        if not el:
            continue
        size = c.get("size")
        out.append({"name": c["name"], "element": el, "label": vocab.clean(c["label_text"]), "area_sqm": round(size.area_sqm, 2) if size else None,
                    "sunk_m": c.get("sunk_m"), "source": source})  # fmt: skip
    for t in texts:
        out += tanks_from_note(vocab.clean(str(t[4]).replace("\\P", " | ")), source)
    return out


def tanks_from_note(text: str, source: str) -> list[dict]:
    """ "DOM WATER U.G. TANK-1A | AREA - 65.88 SQ MTR | 3.0M DEPTH | +0.3m FREE BOARD" and
    "DOMESTIC WATER TANK | CAP: 12,500 LTRS | HEIGHT : 1.9+0.3M F.B." -> a tank with its numbers."""
    t = text.upper()
    if "TANK" not in t:
        return []
    el = vocab.element_of(t)
    if el not in ("ug_tank", "oht", "stp", "tank"):
        el = "oht" if re.search(r"FLUSHING|DOMESTIC|FIRE", t) and "U.G" not in t else el
    area = re.search(r"AREA\s*-?\s*:?\s*([\d.]+)\s*SQ", t)
    depth = re.search(r"([\d.]+)\s*M\s*DEPTH|DEPTH\s*:?\s*([\d.]+)\s*M|HEIGHT\s*:?\s*([\d.]+)", t)
    cap = re.search(r"([\d,]+)\s*LTR|CAP\s*:?\s*([\d,]+)", t)
    fb = re.search(r"\+\s*([\d.]+)\s*M\s*(?:FREE\s*BOARD|F\.?\s*B)", t)
    if not (area or depth or cap):
        return []
    d = float(next(g for g in depth.groups() if g)) if depth else None
    capacity = float((next(g for g in cap.groups() if g)).replace(",", "")) if cap else None
    a = (
        float(area.group(1))
        if area
        else (round(capacity / 1000 / d, 2) if capacity and d else None)
    )
    name = re.split(r"\|", text)[0].strip()
    if re.match(r"^[\d,]+\s*LTR", name.upper()):
        name = text.split("|")[1].strip() if "|" in text else name
    return [{"name": name, "element": el or "tank", "label": text, "area_sqm": a, "depth_m": d, "capacity_l": capacity, "source": source, "freeboard_m": float(fb.group(1)) if fb else 0.0,
             "area_from": "the note" if area else ("capacity ÷ height" if a else None)}]  # fmt: skip


def read_drawing(path: Path, source: str | None = None) -> dict:
    """A DWG or DXF read for its labels (the takeoff reader, with the line-break repair)."""
    from app.takeoff import reader

    p = path
    tmp = None
    if path.suffix.lower() == ".dwg":
        import tempfile

        from app.takeoff import dwg

        tmp = Path(tempfile.mkdtemp()) / (path.stem + ".dxf")
        dwg.to_dxf(path, tmp)
        p = tmp
    parsed = reader.read(p)
    unit_m = parsed.unit_m if getattr(parsed, "unit_m", None) else 0.001
    places = places_from_texts(parsed.texts, unit_m, source or path.name)
    return {
        "file": path.name,
        "texts": len(parsed.texts),
        "repairs": parsed.repairs,
        "places": places,
    }


def conditions_from_text(text: str) -> dict:
    """What the BOQ text says about the conditions."""
    t = (text or "").lower()
    c: dict[str, Any] = {}
    if re.search(r"open\s*to\s*sky|exposed", t):
        c["exposure"] = {"value": "open", "source": "BOQ text"}
    elif re.search(r"\bcovered\b", t):
        c["exposure"] = {"value": "covered", "source": "BOQ text"}
    if "underslung" in t:
        c["toilet_kind"] = {"value": "underslung", "source": "BOQ text"}
    elif re.search(r"sunk|sunken", t):
        c["toilet_kind"] = {"value": "sunken", "source": "BOQ text"}
    if re.search(r"\bunconfined\b|open\s*excavation", t):
        c["confined"] = {"value": False, "source": "BOQ text"}
    elif re.search(r"\bconfined\b", t):
        c["confined"] = {"value": True, "source": "BOQ text"}
    if re.search(r"internal|inside|negative\s*side", t):
        c["face"] = {"value": "inner", "source": "BOQ text"}
    return c


def set_places(item: MethodologyItem, places: list[dict]) -> None:
    """The item's places and what they say: area (each place, the toilet split at 4.5 sqm), sunk
    depth (a sunk toilet), tank area and depth."""
    item.places = places
    cond = dict(item.conditions or {})
    areas = [p["area_sqm"] for p in places if p.get("area_sqm")]
    if areas and item.element == "toilet":
        biggest = max(areas)
        lab = next(p["label"] for p in places if p.get("area_sqm") == biggest)
        cond["area_sqm"] = {
            "value": biggest,
            "source": f"largest of {len(areas)} labelled: {lab} = {biggest:.2f} sqm",
        }
    sunk = [p["sunk_m"] for p in places if p.get("sunk_m")]
    if sunk:
        cond["sunk_depth_mm"] = {"value": round(float(max(sunk)) * 1000), "source": "drawing note"}
        cond.setdefault("toilet_kind", {"value": "sunken", "source": "sunk depth on the drawing"})
    tanks = [p for p in places if p.get("depth_m")]
    if tanks:
        cond["tank_area_sqm"] = {
            "value": tanks[0].get("area_sqm"),
            "source": tanks[0]["label"][:120],
        }
        cond["tank_depth_m"] = {"value": tanks[0]["depth_m"], "source": tanks[0]["label"][:120]}
        if tanks[0].get("area_sqm"):
            per = 4 * math.sqrt(float(tanks[0]["area_sqm"]))
            cond["tank_perimeter_m"] = {
                "value": round(per, 2),
                "assumed": True,
                "source": "square plan assumed: to confirm (enter the real perimeter)",
            }
            cond["tank_freeboard_m"] = {
                "value": tanks[0].get("freeboard_m") or 0.0,
                "source": tanks[0]["label"][:120],
            }
    item.conditions = cond


def tank_qty(
    area: float, depth: float, freeboard: float, perimeter: float | None = None
) -> tuple[Decimal, str, bool]:
    """The inside surface of a tank: the base and the walls (perimeter × wet height). Without
    the real perimeter the plan is taken as square, and the area is to confirm."""
    assumed = perimeter is None
    per = perimeter if perimeter is not None else 4 * math.sqrt(area)
    walls = per * (depth + freeboard)
    note = (
        f"base {area:.2f} sqm + walls {walls:.2f} sqm ({per:.2f} m × {depth + freeboard:.1f} m"
        + (", square plan assumed: to confirm)" if assumed else ", perimeter given)")
    )
    return Decimal(str(round(area + walls, 3))), note, assumed


def set_perimeter(
    db: Session, item: MethodologyItem, perimeter: float, user_name: str, reason: str
) -> Decimal:
    """The real perimeter of a tank: its area again, on the item and its BOQ line, no longer to
    confirm."""
    from app.tenders.models import BoqLine

    c = dict(item.conditions or {})
    area, depth = _value(c, "tank_area_sqm"), _value(c, "tank_depth_m")
    if not area or not depth:
        raise ValueError("The tank's plan area and depth are not known")
    qty, note, _assumed = tank_qty(
        float(area), float(depth), float(_value(c, "tank_freeboard_m") or 0), perimeter
    )
    c["tank_perimeter_m"] = {
        "value": perimeter,
        "assumed": False,
        "source": f"by hand ({user_name}): {reason}",
    }
    item.conditions = c
    item.qty = qty
    for lid in item.boq_line_ids or []:
        line = db.get(BoqLine, lid)
        if line is not None and len(item.boq_line_ids) == 1:
            line.qty = qty
            line.client_remarks = f"{note}; {reason}"
    return qty


def split_toilets(db: Session, m: Methodology, item: MethodologyItem) -> list[MethodologyItem]:
    """Toilets on both sides of 4.5 sqm: two items (the small and the large system)."""
    if item.element != "toilet":
        return [item]
    small = [p for p in item.places if p.get("area_sqm") and p["area_sqm"] < SMALL_TOILET_SQM]
    large = [p for p in item.places if p.get("area_sqm") and p["area_sqm"] >= SMALL_TOILET_SQM]
    if not (small and large):
        return [item]
    total = sum(p["area_sqm"] for p in small + large)
    other = MethodologyItem(methodology_id=m.id, sort_order=item.sort_order, rate_group_id=item.rate_group_id, boq_line_ids=item.boq_line_ids,
                            name=f"{item.name} (≥ {SMALL_TOILET_SQM} sqm)", element="toilet", unit=item.unit, conditions=dict(item.conditions))  # fmt: skip
    if item.qty:
        other.qty = (
            Decimal(item.qty) * Decimal(str(sum(p["area_sqm"] for p in large) / total))
        ).quantize(Decimal("0.001"))
        item.qty = Decimal(item.qty) - other.qty
    item.name = f"{item.name} (< {SMALL_TOILET_SQM} sqm)"
    db.add(other)
    set_places(item, small)
    set_places(other, large)
    return [item, other]


# --- the client's rule ----------------------------------------------------------------------------


def _value(cond: dict, key: str):
    v = cond.get(key)
    return v.get("value") if isinstance(v, dict) else v


def _fits(rule_cond: dict, item_cond: dict) -> tuple[bool, list[str]]:
    """Does the item meet the rule's condition? (False, []) when it does not; (True, missing)
    when it does as far as known, with the keys nobody has read yet."""
    missing = []
    for k, want in (rule_cond or {}).items():
        if k in INFORMATIONAL:
            continue
        have = _value(item_cond, k)
        if have is None:
            missing.append(k)
            continue
        if isinstance(want, dict):
            x = float(have)
            if "lt" in want and not x < want["lt"]:
                return False, []
            if "gte" in want and not x >= want["gte"]:
                return False, []
        elif have != want:
            return False, []
    return True, missing


def choose_rule(
    std: ClientStandard | None, item: MethodologyItem
) -> tuple[StandardRule | None, str, list[str]]:
    """The client's rule for the item: the one whose condition it meets (most specific first).
    Returns the rule, a note, and the conditions still to confirm."""
    if std is None:
        return None, "no client standard linked", []
    rules = [r for r in std.rules if r.element == item.element]
    if not rules:
        return (
            None,
            f"the standard has no rule for {vocab.ELEMENT_LABEL.get(item.element or '', item.element)}",
            [],
        )
    fits = []
    for r in rules:
        ok, missing = _fits(r.condition, item.conditions or {})
        if ok:
            fits.append(
                (
                    len(missing),
                    -len([k for k in r.condition if k not in INFORMATIONAL]),
                    r.id,
                    r,
                    missing,
                )
            )
    if not fits:
        return None, "no rule's condition fits what is known of the item", []
    fits.sort(key=lambda x: (x[0], x[1], x[2]))
    _n, _k, _id, rule, missing = fits[0]
    # the same system whichever way the unknown goes: nothing to confirm for the choice
    same = {r.system_type for _a, _b, _c, r, mi in fits if mi}
    if missing and len(same | {rule.system_type}) == 1:
        missing = []
    doc = rule.document
    ref = (
        f"{doc.sop_no or doc.file_name} rev {doc.revision} p.{rule.page}"
        if doc
        else f"p.{rule.page}"
    )
    note = f"{ref}: {rule.condition_label or rule.element_label}"
    return rule, note, missing


def required_types(rule: StandardRule) -> list[tuple[str, str]]:
    """The system types the rule asks for, with where: "PU on the floor and acrylic
    cementitious on walls" -> [(floor, pu), (walls, acrylic_cementitious)]."""
    text = vocab.clean(rule.system_text)
    out = []
    for part in re.split(
        r"\band\b(?=[^.]*?(?:coating|\bcoat\b|membrane|cementitious|polyurethane))", text
    ):
        t = vocab.system_type_of(part)
        if not t:
            continue
        walls = re.search(r"\bwalls?\b|vertical", part, re.I)
        floor = re.search(r"\bfloors?\b|horizontal", part, re.I)
        where = "walls" if walls and not floor else "floor" if floor and not walls else ""
        if (where, t) not in out:
            out.append((where, t))
    if not out and rule.system_type:
        out.append(("", rule.system_type))
    return out


# --- our system ------------------------------------------------------------------------------------


def candidates(db: Session, element: str | None, brand: str | None = None) -> list[MethodSystem]:
    els = SUITS.get(element or "", [element])
    rows = [
        s
        for s in db.scalars(
            select(MethodSystem).where(MethodSystem.is_active).order_by(MethodSystem.id)
        )
        if set(s.elements or []) & set(els)
    ]
    if brand:
        rows = [s for s in rows if (s.brand or "").lower() == brand.lower()] or rows
    order = {e: i for i, e in enumerate(els)}
    return sorted(rows, key=lambda s: min(order.get(e, 99) for e in s.elements or [""]))


def _system_types(s: MethodSystem) -> set[str]:
    out = {s.system_type} if s.system_type else set()
    for st in s.stages:
        if re.search(r"COATING|MEMBRANE", st["heading"]):
            for x in st["steps"]:
                t = vocab.system_type_of(x.get("product") or "")
                if t:
                    out.add(t)
    return out


def propose(
    db: Session,
    item: MethodologyItem,
    rule: StandardRule | None,
    brand: str | None,
    std: ClientStandard | None = None,
) -> tuple[MethodSystem | None, list[MethodSystem], str]:
    """Our system for the item: of the library systems that suit the element, the one that meets
    the client's rule best (the required types first, then the fewest gaps and values to confirm
    in the compliance check); the next best of another kind is Option 2."""
    cands = candidates(db, item.element, brand)
    if not cands:
        return (
            None,
            [],
            f"no system in our library suits {vocab.ELEMENT_LABEL.get(item.element or '', item.element)}: add one",
        )
    need = [t for _w, t in required_types(rule)] if rule else []
    trial: dict[int, dict] = {}

    def score(s: MethodSystem) -> tuple:
        types = _system_types(s)
        meets = sum(1 for t in need if any(vocab.satisfies(x, t) for x in types))
        own = 1 if item.element in (s.elements or []) else 0
        if s.id not in trial:
            probe = SimpleNamespace(
                stages=stages_for(s, rule, item),
                conditions=item.conditions or {},
                rule_note=item.rule_note,
            )
            trial[s.id] = (
                check(db, probe, std, rule, s)
                if rule
                else {"red": 0, "confirm": len(s.to_confirm or [])}
            )
        c = trial[s.id]
        return (-meets, c["red"], c["confirm"], -own, s.id)

    ranked = sorted(cands, key=score)
    best = ranked[0]
    meets = -score(best)[0]
    others = [s for s in ranked[1:] if s.system_type != best.system_type][:1] or ranked[1:2]
    parts = []
    if rule:
        req = " + ".join(
            f"{vocab.SYSTEM_LABEL.get(t, t)}{' on ' + w if w else ''}"
            for w, t in required_types(rule)
        )
        parts.append(f"the client asks for {req}")
    parts.append(
        f"{best.name} is {vocab.SYSTEM_LABEL.get(best.system_type or '', best.system_type or 'our system')}"
    )
    if need and meets < len(need):
        parts.append(
            f"it covers {meets} of the {len(need)} required types: the rest is a gap below"
        )
    if best.conditions:
        parts.append(best.conditions[0]["text"].rstrip(".").lower())
    if len(ranked) > 1:
        b = trial.get(best.id) or {}
        alts = ", ".join(
            f"{s.name} ({(trial.get(s.id) or {}).get('red', 0)} gaps)" for s in ranked[1:3]
        )
        parts.append(
            f"{b.get('red', 0)} gap(s) and {b.get('confirm', 0)} value(s) to confirm against the client's standard, the fewest of our systems for it; over {alts}"
        )
    return best, others, "; ".join(parts) + "."


def stages_for(
    system: MethodSystem, rule: StandardRule | None, item: MethodologyItem
) -> list[dict]:
    """Our steps, plus the client's tests as steps of their own stage where ours do not have them."""
    stages = [dict(s, steps=[dict(x) for x in s["steps"]]) for s in system.stages]
    if rule:
        tests = [
            t for t in rule.tests if t["kind"] in ("pre_pond", "pond", "fill") and t.get("hours")
        ]
        if tests:
            steps = []
            for t in tests:
                label = {"pre_pond": "Pre-pond test", "pond": "Pond test", "fill": "Fill test"}[
                    t["kind"]
                ]
                depth = f" with {t['depth_mm']} mm of water" if t.get("depth_mm") else ""
                steps.append({"text": f"{label}{depth} for {t['hours']} hours; record the levels and photos; repair any leak and repeat.", "products": [], "product": None,
                              "scope": "ours", "wait": f"{t['hours']} hours", "to_confirm": [], "client_ref": _ref(rule, t.get("page"))})  # fmt: skip
            # tested on the coating, before anything covers it
            at = next(
                (
                    i + 1
                    for i in range(len(stages) - 1, -1, -1)
                    if re.search(r"COATING|MEMBRANE", stages[i]["heading"])
                ),
                len(stages),
            )
            stages.insert(at, {"heading": "TESTING", "option": None, "steps": steps})
    return stages


def _ref(rule: StandardRule | None, page: int | None = None) -> str | None:
    if rule is None:
        return None
    d = rule.document
    return f"{(d.sop_no or d.file_name) if d else 'SOP'} rev {d.revision if d else ''} p.{page or rule.page}".replace(
        "rev  ", ""
    )


# --- compliance --------------------------------------------------------------------------------------


def our_value(db: Session, system: MethodSystem, prop: str, stages: list[dict]) -> dict | None:
    v = (system.specs or {}).get(prop)
    if v and v.get("num") is not None:
        return v
    # the main product's data sheet
    names = [
        x.get("product")
        for s in stages
        if re.search(r"COATING|MEMBRANE", s["heading"])
        for x in s["steps"]
        if x.get("product")
    ]
    for n in names:
        p = db.scalar(select(MethodProduct).where(MethodProduct.name == n))
        if p and (p.values or {}).get(prop, {}).get("num") is not None:
            return {**p.values[prop], "source": f"{n} data sheet"}
    if prop == "mesh_gsm":
        for s in stages:
            for x in s["steps"]:
                m = re.search(r"(\d+)\s*gsm[^.]{0,40}(?:mesh|fabric|non[- ]woven)", x["text"], re.I)
                if m and not re.search(
                    r"separation|slip|120\s*gsm|150\s*gsm|corner|tape", x["text"], re.I
                ):
                    return {
                        "value": f"{m.group(1)} GSM",
                        "num": float(m.group(1)),
                        "unit": "GSM",
                        "source": "our steps",
                    }
    if prop == "dft":  # a membrane's thickness is its DFT
        t = (system.specs or {}).get("thickness")
        if t and t.get("num") is not None and system.system_type in ("hdpe", "sbs", "tpo"):
            return t
    return None


def check(
    db: Session,
    item: MethodologyItem,
    std: ClientStandard | None,
    rule: StandardRule | None,
    system: MethodSystem | None,
) -> dict:
    """Green / red with the gap / to confirm, per requirement of the client's rule."""
    rows: list[dict] = []
    stages = item.stages or (system.stages if system else [])
    if system is None:
        rows.append(
            {
                "topic": "System",
                "required": "a system for the element",
                "ours": "none",
                "status": "red",
                "gap": "no system chosen",
            }
        )
    for k in (
        item.conditions.get("_missing", [])
        if isinstance(item.conditions.get("_missing"), list)
        else []
    ):
        rows.append(
            {
                "topic": f"Condition: {CONDITION_LABEL.get(k, k)}",
                "required": "known",
                "ours": TO_CONFIRM,
                "status": "confirm",
                "gap": "read it from the drawings or ask",
            }
        )
    if rule is None:
        rows.append(
            {
                "topic": "Client rule",
                "required": "a rule for the element and condition",
                "ours": item.rule_note or "",
                "status": "confirm",
                "gap": item.rule_note,
            }
        )
    if rule is not None and system is not None:
        ref = _ref(rule)
        types = _system_types(system)
        for where, t in required_types(rule):
            ok = any(vocab.satisfies(x, t) for x in types)
            rows.append({"topic": "System type" + (f" ({where})" if where else ""), "required": vocab.SYSTEM_LABEL.get(t, t), "ours": ", ".join(vocab.SYSTEM_LABEL.get(x, x) for x in sorted(types)) or "—",
                         "status": "green" if ok else "red", "gap": None if ok else f"add {vocab.SYSTEM_LABEL.get(t, t).lower()}{' on the ' + where if where else ''} or change the system", "ref": ref})  # fmt: skip
        seen = set()
        for sp in rule.min_specs:
            if (
                sp.get("num") is None
                or sp.get("op") not in ("min", "eq", "range")
                or sp["property"] in seen
            ):
                continue
            if sp.get("system_type") and not any(
                vocab.satisfies(x, sp["system_type"]) or vocab.satisfies(sp["system_type"], x)
                for x in types
            ):
                continue
            # the client's table for our very type when there is one; where the client says two
            # things for it, the stricter one
            same = [
                x
                for x in rule.min_specs
                if x["property"] == sp["property"]
                and x.get("num") is not None
                and x.get("op") in ("min", "eq", "range")
            ]
            fams = {vocab.family(t) for t in types}
            exact = (
                [x for x in same if vocab.family(x.get("system_type")) in fams]
                or [x for x in same if x.get("system_type") in (sp.get("system_type"), None)]
                or [sp]
            )
            sp = (
                max(exact, key=lambda x: x["num"])
                if sp["property"] in vocab.HIGHER_IS_BETTER
                else exact[0]
            )
            seen.add(sp["property"])
            ours = our_value(db, system, sp["property"], stages)
            req = f"{sp['required']}" + (f" ({sp['standard']})" if sp.get("standard") else "")
            row = {
                "topic": vocab.PROPERTY_LABEL.get(sp["property"], sp["property"]),
                "property": sp["property"],
                "required": req,
                "standard": sp.get("standard"),
                "ref": _ref(rule, sp.get("page")),
            }
            if ours is None and sp["property"] == "mesh_gsm":
                row.update(
                    ours="no mesh in our steps",
                    status="red",
                    gap=f"add a {_n(float(sp['num']))} GSM glass fibre mesh between the coats",
                )
            elif ours is None:
                row.update(
                    ours=TO_CONFIRM, status="confirm", gap="no value in our data sheet or steps"
                )
            else:
                n, want = float(ours["num"]), float(sp["num"])
                good = (
                    n >= want
                    if sp["property"] in vocab.HIGHER_IS_BETTER or sp["op"] == "min"
                    else n <= want
                    if sp["op"] == "max"
                    else abs(n - want) < 1e-9
                )
                gap = (
                    None
                    if good
                    else f"{_n(want - n)} {sp.get('unit') or ours.get('unit') or ''} short ({_n(n)} vs {_n(want)})".replace(
                        "  ", " "
                    )
                )
                row.update(
                    ours=f"{ours['value']}"
                    + (f" — {ours.get('source')}" if ours.get("source") else ""),
                    status="green" if good else "red",
                    gap=gap,
                )
            rows.append(row)
        # makes
        brand = system.brand
        approved = [b.lower() for b in (std.approved_makes if std else [])]
        if brand and approved and brand.lower() not in approved:
            alts = sorted(
                {
                    f"{mk['brand']} {mk['product']}"
                    + (" (approved as per TPT)" if mk["status"] == "tpt" else "")
                    for mk in rule.makes
                    if mk["status"] in ("approved", "tpt")
                }
            )
            main = _main_product(system)
            alts_note = None
            if not alts:
                alts, alts_note = other_sop_makes(std, rule, types)
            rows.append({"topic": "Make", "required": "one of " + ", ".join(std.approved_makes), "ours": f"{brand} ({main or system.name})", "status": "red",
                         "gap": f"{brand} is not on the approved list", "ref": ref,
                         "choices": [{"key": "approved", "label": "Use an approved make", "options": alts[:8], "note": alts_note},
                                     {"key": "keep", "label": f"Keep {brand} and ask before the bid", "query": f"Request approval of {main or brand} ({brand}) as an equivalent make (TPT)"}]})  # fmt: skip
        elif brand:
            rows.append(
                {
                    "topic": "Make",
                    "required": ", ".join(std.approved_makes) if std else "",
                    "ours": brand,
                    "status": "green",
                    "gap": None,
                }
            )
        # tests and hold points: ours take the client's
        for t in rule.tests:
            if t["kind"] in ("pre_pond", "pond", "fill") and t.get("hours"):
                label = {"pre_pond": "Pre-pond test", "pond": "Pond test", "fill": "Fill test"}[
                    t["kind"]
                ]
                has = any(f"{t['hours']} hours" in x["text"] for s in stages for x in s["steps"])
                rows.append({"topic": label, "required": f"{t['hours']} h", "ours": f"{t['hours']} h in our testing stage" if has else "not in our steps", "status": "green" if has else "red",
                             "gap": None if has else f"add the {label.lower()} for {t['hours']} h", "ref": _ref(rule, t.get("page"))})  # fmt: skip
        # guarantee
        want = rule.guarantee_years or (std.guarantee_years if std else None)
        if want:
            have = system.guarantee_years
            rows.append({"topic": "Guarantee", "required": f"{want} years", "ours": f"{have} years" if have else TO_CONFIRM,
                         "status": "confirm" if have is None else ("green" if have >= want else "red"), "gap": None if have and have >= want else ("not in our library" if have is None else f"{want - have} years short")})  # fmt: skip
    per = (item.conditions or {}).get("tank_perimeter_m")
    if isinstance(per, dict) and per.get("assumed"):
        rows.append({"topic": "Tank wall area", "required": "the real perimeter", "ours": f"{per['value']} m from a square plan", "status": "confirm",
                     "gap": "square plan assumed: enter the real perimeter to recalculate the area"})  # fmt: skip
    counts = Counter(r["status"] for r in rows)
    return {
        "rows": rows,
        "green": counts["green"],
        "red": counts["red"],
        "confirm": counts["confirm"],
        "checked_at": datetime.now(UTC).isoformat(),
    }


def other_sop_makes(
    std: ClientStandard | None, rule: StandardRule, types: set[str]
) -> tuple[list[str], str]:
    """A SOP without a makes table (the new-format toilet, balcony and terrace SOPs): the same
    client's approved products for the same material from its other SOPs, marked where from."""
    fams = {vocab.family(t) for t in types}
    out: dict[str, str] = {}
    for r in std.rules if std else []:
        if r.id == rule.id:
            continue
        for mk in r.makes:
            if mk["status"] not in ("approved", "tpt"):
                continue
            if vocab.family(vocab.system_type_of(mk.get("system") or "")) not in fams:
                continue
            label = f"{mk['brand']} {mk['product']}" + (
                " (approved as per TPT)" if mk["status"] == "tpt" else ""
            )
            sop = r.document.sop_no if r.document else "another SOP"
            out.setdefault(label, f"from SOP {sop}")
    if not out:
        kinds = (
            ", ".join(sorted(vocab.SYSTEM_LABEL.get(t, t).lower() for t in types))
            or "this material"
        )
        return (
            [],
            f"this SOP lists no makes, and no other SOP of the client approves a product for {kinds}",
        )
    return (
        [f"{k} — {v}" for k, v in sorted(out.items())],
        "this SOP lists no makes: products the client approves for the same material in its other SOPs",
    )


def _n(v: float) -> str:
    return f"{v:g}"


def _main_product(s: MethodSystem) -> str | None:
    from app.methodology.seed import Stage, main_product

    return main_product([Stage(x["heading"], None, x["steps"]) for x in s.stages])


# --- building -----------------------------------------------------------------------------------------


def build(
    db: Session,
    m: Methodology,
    groups: list[dict],
    drawings: list[dict] | None = None,
    by_hand: dict | None = None,
) -> Methodology:
    """groups = [{name, rate_group_id, boq_line_ids, qty, unit, text}] (the main items);
    drawings = [{places}] read from the drawings; by_hand = {item name or element: {key: value}}."""
    std = db.get(ClientStandard, m.standard_id) if m.standard_id else None
    places = [p for d in drawings or [] for p in d["places"]]
    for i, g in enumerate(groups):
        el = vocab.element_of(g["name"]) or vocab.element_of(g.get("text") or "")
        item = MethodologyItem(methodology_id=m.id, sort_order=i, rate_group_id=g.get("rate_group_id"), boq_line_ids=g.get("boq_line_ids") or [], name=g["name"], element=el,
                               qty=g.get("qty"), unit=g.get("unit"), conditions=conditions_from_text(f"{g['name']} {g.get('text') or ''}"))  # fmt: skip
        db.add(item)
        db.flush()
        mine = [
            p
            for p in places
            if p["element"] == el or (el == "balcony" and p["element"] == "balcony")
        ]
        if el in ("oht", "ug_tank") and mine:
            mine = mine[:1]
        if mine:
            set_places(item, mine)
        for key in (g["name"], el):
            for k, v in ((by_hand or {}).get(key) or {}).items():
                item.conditions = {**item.conditions, k: {"value": v, "source": "by hand"}}
        for it in split_toilets(db, m, item):
            db.flush()
            choose(db, m, it, std)
    m.version = 1
    db.flush()
    refresh_queries(db, m)
    return m


def choose(db: Session, m: Methodology, item: MethodologyItem, std: ClientStandard | None) -> None:
    rule, note, missing = choose_rule(std, item)
    item.rule_id = rule.id if rule else None
    item.rule_note = note
    conds = {k: v for k, v in (item.conditions or {}).items() if k != "_missing"}
    if missing:
        conds["_missing"] = missing
    item.conditions = conds
    system, others, reason = propose(db, item, rule, m.brand, std)
    item.system_id = system.id if system else None
    item.option_ids = [s.id for s in others]
    item.reason = reason
    item.stages = stages_for(system, rule, item) if system else []
    item.compliance = check(db, item, std, rule, system)


def recheck(db: Session, m: Methodology) -> None:
    std = db.get(ClientStandard, m.standard_id) if m.standard_id else None
    for it in m.items:
        rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
        system = db.get(MethodSystem, it.system_id) if it.system_id else None
        it.compliance = check(db, it, std, rule, system)
        _apply_choice(it)
    refresh_queries(db, m)


def _apply_choice(it: MethodologyItem) -> None:
    """The estimator's choice on a make that is not listed: keep ours (a pre-bid query) or use an
    approved make (the row stays red until the system is changed)."""
    if not it.make_choice:
        return
    for r in it.compliance.get("rows", []):
        if r["topic"] == "Make" and r["status"] == "red":
            r["choice"] = it.make_choice


def refresh_queries(db: Session, m: Methodology) -> list[PreBidQuery]:
    """The pre-bid sheet: the contradictions in the SOPs the items use, the makes to approve, the
    conditions and values to confirm. Answers already given are kept."""
    old = {
        (q.kind, q.text): q
        for q in db.scalars(select(PreBidQuery).where(PreBidQuery.methodology_id == m.id))
    }
    want: list[tuple[str, str, str | None, int | None]] = []
    docs = set()
    for it in m.items:
        rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
        if rule and rule.document_id:
            docs.add(rule.document_id)
        for r in (it.compliance or {}).get("rows", []):
            if r["topic"] == "Make" and r["status"] == "red" and it.make_choice != "approved":
                q = next((c["query"] for c in r.get("choices", []) if c["key"] == "keep"), None)
                if q:
                    want.append(("make", q, r.get("ref"), it.id))
            elif r["status"] == "confirm" and r["topic"].startswith("Condition"):
                want.append(
                    (
                        "condition",
                        f"{it.name}: please confirm {r['topic'].split(': ', 1)[1].lower()}",
                        None,
                        it.id,
                    )
                )
        if rule and rule.status == "to_check":
            want.append(
                (
                    "confirm",
                    f"{it.name}: please confirm the system for {rule.element_label} ({rule.condition_label or 'all'}): {(rule.system_text or '')[:160]}",
                    _ref(rule),
                    it.id,
                )
            )
    for c in db.scalars(
        select(StandardContradiction).where(StandardContradiction.document_id.in_(docs or {0}))
    ):
        vals = "; ".join(dict.fromkeys(f"{v['value']} (p.{v['page']})" for v in c.values))
        d = c.document
        want.append(
            (
                "contradiction",
                f"{c.topic}: the SOP says {vals}. Which applies?",
                f"{d.sop_no or d.file_name} rev {d.revision}" if d else None,
                None,
            )
        )
    keep = []
    seen: dict[tuple[str, str], list] = {}
    for kind, text, ref, item_id in want:  # one query for the same question on several items
        seen.setdefault((kind, text), []).append((ref, item_id))
    want = [
        (
            k,
            t,
            "; ".join(dict.fromkeys(r for r, _i in v if r)) or None,
            v[0][1] if len(v) == 1 else None,
        )
        for (k, t), v in seen.items()
    ]
    for kind, text, ref, item_id in want:
        q = old.pop((kind, text), None)
        if q is None:
            q = PreBidQuery(
                methodology_id=m.id, item_id=item_id, kind=kind, text=text, reference=ref
            )
            db.add(q)
        keep.append(q)
    for q in old.values():
        if q.status == "open":
            db.delete(q)
    db.flush()
    return keep


# --- edits and versions ---------------------------------------------------------------------------


def snapshot(m: Methodology) -> dict:
    return {"title": m.title, "revision": m.revision, "version": m.version, "items": [
        {"id": it.id, "name": it.name, "element": it.element, "qty": str(it.qty) if it.qty is not None else None, "unit": it.unit, "conditions": it.conditions,
         "rule_id": it.rule_id, "system_id": it.system_id, "option_ids": it.option_ids, "reason": it.reason, "stages": it.stages, "compliance": it.compliance,
         "make_choice": it.make_choice} for it in m.items]}  # fmt: skip


def save_version(db: Session, m: Methodology, reason: str, user_id=None) -> MethodologyVersion:
    v = MethodologyVersion(
        methodology_id=m.id,
        version=m.version,
        revision=m.revision,
        reason=reason,
        snapshot=snapshot(m),
        created_by=user_id,
    )
    db.add(v)
    m.version += 1
    db.flush()
    from app.closeout import issues  # noqa: PLC0415

    issues.methodology_saved(db, m)  # a discontinued product no longer used: its issue closes
    return v


def edit_step(
    db: Session,
    m: Methodology,
    item: MethodologyItem,
    stage: int,
    step: int | None,
    change: dict,
    reason: str,
    user,
) -> None:
    """Change, add or remove a step (with the reason; the version before is kept)."""
    if not (reason or "").strip():
        raise ValueError("Say why the step changes")
    stages = [dict(s, steps=[dict(x) for x in s["steps"]]) for s in item.stages]
    if stage < 0 or stage >= len(stages):
        raise ValueError("No such stage")
    steps = stages[stage]["steps"]
    before = steps[step] if step is not None and 0 <= step < len(steps) else None
    if change.get("remove"):
        if before is None:
            raise ValueError("No such step")
        steps.pop(step)
        after = None
    elif before is None:
        after = {
            "text": change["text"],
            "products": [],
            "product": change.get("product"),
            "scope": change.get("scope") or "ours",
            "to_confirm": [],
        }
        steps.insert(len(steps) if step is None else step, after)
    else:
        after = {
            **before,
            **{
                k: v
                for k, v in change.items()
                if k
                in ("text", "product", "consumption", "unit", "coats", "wait", "tools", "scope")
            },
        }
        steps[step] = after
    save_version(db, m, f"{item.name}: {reason}", user.id if user else None)
    item.stages = stages
    item.edits = (item.edits or []) + [{"at": datetime.now(UTC).isoformat(), "by": user.full_name if user else None, "reason": reason, "stage": stages[stage]["heading"],
                                        "step": step, "before": before, "after": after, "version": m.version}]  # fmt: skip


def to_library(db: Session, item: MethodologyItem, reason: str, user) -> MethodSystem:
    """The item's steps as edited, back into the library system (a new version of it, logged)."""
    s = db.get(MethodSystem, item.system_id)
    if s is None:
        raise ValueError("The item has no library system")
    library_edit(
        db,
        s,
        {
            "stages": [
                {**x, "steps": [y for y in x["steps"] if not y.get("client_ref")]}
                for x in item.stages
                if x["heading"] != "TESTING"
            ]
        },
        reason,
        user,
    )
    return s


LIBRARY_FIELDS = ("name", "brand", "system_type", "elements", "conditions", "why", "competing", "stages", "hold_points", "tests", "checklist",
                  "guarantee_years", "boq_description", "measurement_rule", "specs", "to_confirm", "is_active")  # fmt: skip


def library_edit(
    db: Session, s: MethodSystem, change: dict, reason: str, user
) -> MethodSystemChange:
    if not (reason or "").strip():
        raise ValueError("Say why the system changes")
    before = {k: getattr(s, k) for k in LIBRARY_FIELDS}
    diffs = []
    for k, v in change.items():
        if k not in LIBRARY_FIELDS or v == before.get(k):
            continue
        diffs.append({"field": k, "before": before.get(k), "after": v})
        setattr(s, k, v)
    if not diffs:
        raise ValueError("Nothing changed")
    # a value given where one was to confirm: no longer to confirm
    if "guarantee_years" in change and change["guarantee_years"]:
        s.to_confirm = [x for x in s.to_confirm if x.get("field") != "guarantee_years"]
    if "why" in change and change["why"]:
        s.to_confirm = [x for x in s.to_confirm if x.get("field") != "why"]
    s.version += 1
    row = MethodSystemChange(
        system_id=s.id,
        version=s.version,
        reason=reason,
        changes=_jsonable(diffs),
        before=_jsonable(before),
        changed_by=user.id if user else None,
    )
    db.add(row)
    db.flush()
    return row


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    return v
