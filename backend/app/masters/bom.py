# ruff: noqa: E501  (the checks' messages read better unwrapped)
"""The company BOM: the consumption of each product per one unit of a work item, one recipe per
brand.

The file (one sheet): a work-item row whose name ends with its unit ("JOINT FILLING (20X10MM)_RFT",
"_SQFT", "_SQMT", "_RMT"), then its products in square brackets: col A "[ ACME BONDCOAT - 20 KG ]",
col B the consumption per one unit of the work item, col C the product's unit,
cols I-J the last purchase price and its date (may be empty). "[ PROCESS FOR PROJECT ]" and
"Rate Per" rows are skipped: there is no labour in the file. A work item with no unit in its name
(grouting, a pipe sleeve, a tie rod) is read per nos (a point) and flagged.

Most work items come twice, once per brand (Bronco, Chryso): those are brand options of one
system, not duplicates. A system is one work item per sqm or per rmt: a recipe per sq ft or per rft
is converted once (× 10.7639, × 3.2808) and keeps its figure and unit as the file gave them; where
a brand has both, the sqm (rmt) recipe is used and the sq ft (rft) one only checked against it.

Products are matched by name to the product master (its name or aliases, with or without the pack
in the name: "ACME FLEXCOAT-12 KG" is "ACME FLEXCOAT"). A name not found is listed,
never dropped: the import can create it, or its line is left out and its system marked to confirm
with the name in its note.

A sheet, mesh or tape's figure already has its overlap (mesh 1.05, HDPE 1.15 per sqm): its
component is marked "wastage included" and no wastage is added again; any other product takes the
application's wastage from Settings as before.

The preview's checks warn, never block: the sq ft and sqm recipes of one item more than 3 % apart
after conversion, two brands' figures for the same role more than 3× apart, a sheet or mesh over
0.2 per sq ft, a work item with no unit, an epoxy or PU item with no resin, a product twice in one
recipe."""

import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.masters.models import Product, System, SystemComponent, SystemOption
from app.masters.units import DEFAULT_ALIASES, normalise_unit

D = Decimal
SQFT_PER_SQM = D("10.7639")
RFT_PER_RMT = D("3.2808")
# the unit at the end of a work item's name: (as written, the system's unit, × this to it)
SUFFIX = {"SQFT": ("sqft", "sqm", SQFT_PER_SQM), "SQMT": ("sqm", "sqm", D(1)), "RFT": ("rft", "rmt", RFT_PER_RMT), "RMT": ("rmt", "rmt", D(1))}
UNIT_LABEL = {"sqft": "sq ft", "sqm": "sqm", "rft": "rft", "rmt": "rmt", "nos": "nos"}
SKIP_PRODUCTS = ("PROCESS FOR PROJECT",)
# words a product's name starts with that are not its maker: "[ FIBER GLASS MESH ]", "[ SDS CHISEL ]"
NOT_A_BRAND = {"FIBER", "FIBRE", "SDS", "NON", "BACKER", "PVC", "GI", "EPXOY", "EPOXY", "NODULAR", "BLACK", "DOUBLE", "SS", "S",
               "MASKING", "BITUMEN", "HYDRO", "GHASAI", "APP", "CEMENT", "SAND", "PU", "HDPE", "GEOTEXTILE", "WHITE", "GREY", "BRICK"}  # fmt: skip
SHEET_UNITS = {"sqm", "sqft"}  # a sheet, a mesh, a membrane, a geotextile
WASTAGE_INCLUDED_UNITS = SHEET_UNITS | {"rmt", "rft"}  # and a tape or a backer rod with its overlap
UNIT_GAP = D("0.03")  # sq ft against sqm: more than 3 % apart
BRAND_RATIO = D(3)  # two brands' figures for the same role
SHEET_MAX_PER_SQFT = D("0.2")
RESIN_ITEM = re.compile(r"\b(EPOXY|PU|POLYURETHANE)\b")
RESIN_PRODUCT = re.compile(r"EPOXY|EPXOY|\bEP\b|-EP\b|\bPU\b|THANE|URETHANE|\bCTE\b")  # CTE: coal tar epoxy
_PACK = re.compile(r"\s*-\s*(\d+(?:\.\d+)?)(?:\s*X\s*\d+(?:\.\d+)?)?\s*(KGS?|LTRS?|LT|L|MTRS?|M)\s*$")
_FOOTER = re.compile(r"^page\s*-?\s*\d+\s+of\s+\d+$", re.I)


class BomFormatError(ValueError):
    pass


def norm(name: str) -> str:
    """A product's name for matching: capitals, one space, quotes and dashes alike."""
    t = name.upper().replace("’", "'").replace("''", '"').replace("“", '"').replace("”", '"')
    t = re.sub(r"\s*-\s*", " - ", t)
    return " ".join(t.split())


def without_pack(name: str) -> str:
    """"ACME BONDCOAT - 20 KG" -> "ACME BONDCOAT" (the pack is not part of the name)."""
    return _PACK.sub("", name).strip()


def pack_of(name: str) -> tuple[Decimal, str] | None:
    """The pack in a name: "- 20 KG" -> (20, kg)."""
    m = _PACK.search(name)
    if not m or "X" in m.group(0).upper():
        return None
    unit = normalise_unit(m.group(2))
    return (D(m.group(1)), unit) if unit else None


def brand_word(name: str) -> str | None:
    w = (name.split() or [""])[0].upper()
    if not w or w in NOT_A_BRAND or not re.search(r"[A-Z]", w):
        return None
    return w.title() if w.isalpha() and len(w) > 4 else w


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return D(str(v).strip())
    except InvalidOperation:
        return None


def q(v: Decimal, places: int = 4) -> Decimal:
    return D(v).quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def n(v: Decimal | None, places: int = 4) -> str:
    if v is None:
        return "—"
    return f"{q(v, places).normalize():f}"


# --- reading the file -----------------------------------------------------------------------------


@dataclass
class Line:
    row: int
    raw: str  # as in the file, without the brackets
    qty: Decimal
    unit_raw: str | None
    unit: str | None  # the unit code (kg, sqm, rmt, nos ...)
    last_price: Decimal | None = None
    last_date: date | None = None
    product_id: int | None = None
    product_name: str | None = None
    matched_by: str | None = None  # name, alias, without the pack

    @property
    def key(self) -> str:
        return norm(self.raw)

    @property
    def kind(self) -> str:
        """The role a product plays, for comparing two brands: a material by weight or volume, a
        sheet, a length (tape), a count (nozzle, chisel)."""
        if self.unit in SHEET_UNITS:
            return "sheet"
        if self.unit in ("rmt", "rft"):
            return "length"
        if self.unit == "nos" or self.unit is None:
            return "count"
        return "material"


@dataclass
class Recipe:
    row: int
    raw: str
    name: str  # without the unit suffix
    item_unit: str  # sqft, sqm, rft, rmt, nos
    unit: str  # the system's: sqm, rmt, nos
    factor: Decimal  # × the file's figure = per the system's unit
    unit_in_name: bool
    unit_col: str | None
    lines: list[Line] = field(default_factory=list)
    brand: str = "Standard"
    skipped: list[tuple[int, str]] = field(default_factory=list)  # labour rows: (row, name)

    @property
    def key(self) -> tuple[str, str]:
        return (norm(self.name), self.unit)

    @property
    def native(self) -> bool:
        return self.item_unit == self.unit


def read(data: bytes) -> list[Recipe]:
    """The work items and their products, in the file's order."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001  (openpyxl raises many kinds for a file that is not a workbook)
        raise BomFormatError(f"The file could not be read as a workbook: {exc}") from None
    ws = wb.worksheets[0]
    recipes: list[Recipe] = []
    cur: Recipe | None = None
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        cells = list(row) + [None] * 10
        a = " ".join(str(cells[0]).split()) if cells[0] is not None else ""
        if not a or a.lower() == "itemname" or _FOOTER.match(a) or a.lower().startswith("rate per"):
            continue
        if a.startswith("["):
            raw = a.strip("[] ").strip()
            if any(s in raw.upper() for s in SKIP_PRODUCTS):
                continue
            if cur is None:
                raise BomFormatError(f"Row {i}: a product before any work item")
            if "LABOUR" in raw.upper():  # labour comes from the labour rate card, never the BOM
                cur.skipped.append((i, raw))
                continue
            qty = _dec(cells[1])
            if qty is None:
                raise BomFormatError(f"Row {i}: {raw} has no consumption in column B")
            unit_raw = str(cells[2]).strip() if cells[2] is not None else None
            last = cells[9]
            cur.lines.append(Line(i, " ".join(raw.split()), qty, unit_raw, normalise_unit(unit_raw, DEFAULT_ALIASES) if unit_raw else None,
                                  _dec(cells[8]), last.date() if isinstance(last, datetime) else last if isinstance(last, date) else None))  # fmt: skip
            continue
        m = re.match(r"^(.*?)\s*_\s*(SQFT|SQMT|RFT|RMT)\s*$", a, re.I)
        col_c = str(cells[2]).strip() if cells[2] is not None else None
        if m:
            item_unit, unit, factor = SUFFIX[m.group(2).upper()]
            cur = Recipe(i, a, m.group(1).strip(), item_unit, unit, factor, True, col_c)
        else:  # no unit in the name: per nos (a point), flagged
            cur = Recipe(i, a, a, "nos", "nos", D(1), False, col_c)
        recipes.append(cur)
    if not recipes:
        raise BomFormatError("No work items found: a work item's name ends with _SQFT, _SQMT, _RFT or _RMT, its products follow in [ ]")
    for r in recipes:
        r.brand = _brand(r)
    return recipes


def _brand(r: Recipe) -> str:
    """The recipe's maker: the first word of its products that names one (most of them)."""
    words = Counter(w for w in (brand_word(ln.raw) for ln in r.lines) if w)
    if not words:
        return "Standard"
    first = next(w for w in (brand_word(ln.raw) for ln in r.lines) if w)
    best = max(words.values())
    return first if words[first] == best else words.most_common(1)[0][0]


# --- the product master ---------------------------------------------------------------------------


def match_products(db: Session, recipes: list[Recipe]) -> None:
    """Each line's product from the master: its name, an alias, its code, or the name without the
    pack ("- 20 KG")."""
    index: dict[str, tuple[Product, str]] = {}
    products = list(db.scalars(select(Product).order_by(Product.is_active.desc(), Product.id)))
    for how in ("name", "alias", "code"):
        for p in products:
            names = {"name": [p.name], "alias": p.aliases or [], "code": [p.code]}[how]
            for nm in names:
                if nm:
                    index.setdefault(norm(nm), (p, how))
    for p in products:
        index.setdefault(norm(without_pack(p.name)), (p, "name without the pack"))
    for r in recipes:
        for ln in r.lines:
            hit = index.get(ln.key)
            if hit is None:
                hit = index.get(norm(without_pack(ln.raw)))
                if hit is not None:
                    hit = (hit[0], "name without the pack")
            if hit is not None:
                ln.product_id, ln.product_name, ln.matched_by = hit[0].id, hit[0].name, hit[1]


# --- the plan: systems and their brand options ----------------------------------------------------


@dataclass
class PlannedOption:
    brand: str
    recipe: Recipe
    others: list[Recipe] = field(default_factory=list)  # the brand's other recipes, checked only


@dataclass
class PlannedSystem:
    name: str
    unit: str
    options: list[PlannedOption] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    existing_id: int | None = None


def plan(recipes: list[Recipe]) -> list[PlannedSystem]:
    """One system per work item and unit (sqm or rmt), one option per brand: the brand's sqm (rmt)
    recipe when it has one, else its sq ft (rft) one converted."""
    systems: dict[tuple[str, str], PlannedSystem] = {}
    by_key: dict[tuple[str, str], list[Recipe]] = {}
    for r in recipes:
        if r.lines:  # a work item with no products (or labour only) makes no system: warned
            by_key.setdefault(r.key, []).append(r)
    for key, rs in by_key.items():
        first_native = next((r for r in rs if r.native), rs[0])
        s = systems[key] = PlannedSystem(first_native.name, first_native.unit)
        brands: dict[str, list[Recipe]] = {}
        for r in rs:
            brands.setdefault(r.brand, []).append(r)
        for brand, mine in brands.items():
            natives = [r for r in mine if r.native]
            smalls = [r for r in mine if not r.native]
            # a brand's sqm (rmt) recipes are its options, its sq ft (rft) ones checked against the
            # first; with none in sqm, each sq ft recipe is an option, converted
            for i, used in enumerate(natives or smalls):
                label = brand if i == 0 else f"{brand} ({i + 1})"
                s.options.append(PlannedOption(label, used, smalls if natives and i == 0 else []))
    return list(systems.values())


# --- the checks -----------------------------------------------------------------------------------


def _w(kind: str, s: PlannedSystem, message: str, rows: list[int], brand: str | None = None) -> dict:
    return {"kind": kind, "system": s.name, "unit": s.unit, "brand": brand, "rows": rows, "message": message}


def _pair(a: list[Line], b: list[Line]) -> list[tuple[Line, Line]]:
    """The same product in both, then by role in order (the first material with the first ...)."""
    pairs, left_a, left_b = [], list(a), list(b)
    for x in list(left_a):
        y = next((y for y in left_b if y.key == x.key), None)
        if y is not None:
            pairs.append((x, y))
            left_a.remove(x)
            left_b.remove(y)
    for kind in ("material", "sheet", "length", "count"):  # the main material with the main one
        mine = sorted((x for x in left_a if x.kind == kind), key=lambda x: -x.qty)
        theirs = sorted((y for y in left_b if y.kind == kind), key=lambda y: -y.qty)
        pairs.extend(zip(mine, theirs, strict=False))
    return pairs


def checks(systems: list[PlannedSystem], recipes: list[Recipe]) -> list[dict]:
    out: list[dict] = []
    for r in recipes:  # what the file itself says of a work item
        s = PlannedSystem(r.name, r.unit)
        if not r.unit_in_name:
            out.append(_w("no_unit", s, f"{r.raw} (row {r.row}) has no unit in its name: read per nos (a point)" + (f"; column C says {r.unit_col}" if r.unit_col else ""), [r.row], r.brand))
        for row, raw in r.skipped:
            out.append(_w("labour_skipped", s, f"{r.raw}: {raw} (row {row}) is labour: left out (labour comes from the labour rate card)", [row], r.brand))
        if not r.lines:
            out.append(_w("no_products", s, f"{r.raw} (row {r.row}) has no products under it: no system made", [r.row], r.brand))
    for s in systems:
        for o in s.options:
            r = o.recipe
            # the same product twice in one recipe
            for key, count in Counter(ln.key for ln in r.lines).items():
                if count > 1:
                    rows = [ln.row for ln in r.lines if ln.key == key]
                    out.append(_w("repeated", s, f"{o.brand}: {key} is {count} times in {r.raw} (rows {', '.join(map(str, rows))})", rows, o.brand))
            # the sq ft (rft) recipe against the sqm (rmt) one
            for other in o.others:
                if other.native == r.native:
                    continue
                small, big = (other, r) if not other.native else (r, other)
                for x, y in _pair(small.lines, big.lines):
                    conv = x.qty * small.factor
                    if y.qty and abs(conv - y.qty) / y.qty > UNIT_GAP:
                        out.append(_w("unit_gap", s, f"{o.brand}, {s.name}: {x.raw} {n(x.qty)} per {UNIT_LABEL[small.item_unit]} (row {x.row}) is {n(conv)} per {s.unit}, "
                                                      f"against {n(y.qty)} per {s.unit} in the {s.unit} item (row {y.row}): {n(abs(conv - y.qty) / y.qty * 100, 0)} % apart", [x.row, y.row], o.brand))  # fmt: skip
            # a sheet or mesh above 0.2 per sq ft (the overlap is already in 1.05 per sqm)
            for rec in [r, *o.others]:
                if rec.unit != "sqm":
                    continue
                for ln in rec.lines:
                    if ln.kind != "sheet":
                        continue
                    # sqm of sheet per sq ft of the work (a sheet kept per sq ft ÷ 10.7639 first)
                    sheet_sqm = ln.qty / SQFT_PER_SQM if ln.unit == "sqft" else ln.qty
                    per_sqft = sheet_sqm if rec.item_unit == "sqft" else sheet_sqm / SQFT_PER_SQM
                    if per_sqft > SHEET_MAX_PER_SQFT:
                        out.append(_w("sheet_high", s, f"{o.brand}, {rec.raw}: {ln.raw} {n(ln.qty)} {ln.unit_raw or ''} per {UNIT_LABEL[rec.item_unit]} (row {ln.row}) is {n(per_sqft)} sqm per sq ft of the work, above {SHEET_MAX_PER_SQFT}", [ln.row], o.brand))  # fmt: skip
            # an epoxy or PU item whose products have no resin
            if RESIN_ITEM.search(norm(s.name)) and r.lines and not any(RESIN_PRODUCT.search(ln.key) for ln in r.lines if "NOZZLE" not in ln.key):
                out.append(_w("no_resin", s, f"{o.brand}, {r.raw} (row {r.row}): an epoxy or PU item with no epoxy or PU product ({', '.join(ln.raw for ln in r.lines)})", [r.row], o.brand))
        # two brands for the same role, more than 3× apart
        if len(s.options) > 1:
            base = s.options[0]
            for o in s.options[1:]:
                for x, y in _pair(base.recipe.lines, o.recipe.lines):
                    a, b = x.qty * base.recipe.factor, y.qty * o.recipe.factor
                    if a > 0 and b > 0 and max(a, b) / min(a, b) > BRAND_RATIO:
                        out.append(_w("brand_ratio", s, f"{s.name} per {s.unit}: {base.brand} {x.raw} {n(a)} (row {x.row}) against {o.brand} {y.raw} {n(b)} (row {y.row}): {n(max(a, b) / min(a, b), 1)}×", [x.row, y.row], o.brand))  # fmt: skip
        # one brand with two recipes in the same unit
        seen = Counter((o.recipe.brand, rec.item_unit) for o in s.options for rec in [o.recipe, *o.others])
        for (brand, unit), count in seen.items():
            if count > 1:
                rows = [rec.row for o in s.options for rec in [o.recipe, *o.others] if rec.brand == brand and rec.item_unit == unit]
                out.append(_w("two_recipes", s, f"{brand} has {count} recipes for {s.name} per {UNIT_LABEL[unit]} (rows {', '.join(map(str, rows))})", rows, brand))
    return out


# --- preview and import ---------------------------------------------------------------------------


def _existing(db: Session, s: PlannedSystem) -> System | None:
    return db.scalar(select(System).where(func.upper(System.name) == norm(s.name), System.unit == s.unit).order_by(System.id).limit(1))


def _per_unit(ln: Line, rec: Recipe) -> Decimal:
    return ln.qty * rec.factor


def _line_out(ln: Line, rec: Recipe) -> dict:
    return {"row": ln.row, "name": ln.raw, "product_id": ln.product_id, "product": ln.product_name, "matched_by": ln.matched_by,
            "unit": ln.unit, "unit_raw": ln.unit_raw, "consumption": q(_per_unit(ln, rec)),
            "original": {"consumption": ln.qty, "per": rec.item_unit} if not rec.native else None,
            "wastage_included": ln.unit in WASTAGE_INCLUDED_UNITS, "last_price": ln.last_price, "last_price_date": ln.last_date}  # fmt: skip


def unmatched(recipes: list[Recipe], systems: list[PlannedSystem] | None = None) -> list[dict]:
    """Each product name not in the master, with where it is used and what creating it would make."""
    used = {id(o.recipe) for s in systems for o in s.options} if systems else None
    found: dict[str, dict] = {}
    for r in recipes:
        for ln in r.lines:
            if ln.product_id is not None:
                continue
            u = found.setdefault(ln.key, {"name": ln.raw, "rows": [], "unit": ln.unit, "unit_raw": ln.unit_raw, "brand": brand_word(ln.raw),
                                          "create_as": without_pack(ln.raw), "pack": None, "last_price": None, "last_price_date": None, "in_options": 0})  # fmt: skip
            u["rows"].append(ln.row)
            if used is None or id(r) in used:
                u["in_options"] += 1
            pk = pack_of(ln.raw)
            if pk and pk[1] == ln.unit:
                u["pack"] = {"size": pk[0], "unit": pk[1]}
            if ln.last_price is not None and (u["last_price_date"] is None or (ln.last_date and ln.last_date > u["last_price_date"])):
                u["last_price"], u["last_price_date"] = ln.last_price, ln.last_date
    return sorted(found.values(), key=lambda u: u["name"])


def preview(db: Session, data: bytes) -> dict:
    recipes = read(data)
    match_products(db, recipes)
    systems = plan(recipes)
    for s in systems:
        e = _existing(db, s)
        s.existing_id = e.id if e else None
    warnings = checks(systems, recipes)
    missing = unmatched(recipes, systems)
    lines = [ln for r in recipes for ln in r.lines]
    return {
        "counts": {
            "work_items": len(recipes), "product_rows": len(lines), "products": len({ln.key for ln in lines}),
            "labour_rows_skipped": sum(len(r.skipped) for r in recipes),
            "systems": len(systems), "new_systems": sum(1 for s in systems if s.existing_id is None),
            "updated_systems": sum(1 for s in systems if s.existing_id is not None),
            "options": sum(len(s.options) for s in systems),
            "components": sum(len(o.recipe.lines) for s in systems for o in s.options),
            "matched_components": sum(1 for s in systems for o in s.options for ln in o.recipe.lines if ln.product_id),
            "unmatched_products": len(missing), "no_unit": sum(1 for r in recipes if not r.unit_in_name),
            "converted_options": sum(1 for s in systems for o in s.options if not o.recipe.native),
            "warnings": len(warnings),
        },
        "systems": [
            {"name": s.name, "unit": s.unit, "existing_id": s.existing_id,
             "options": [{"brand": o.brand, "row": o.recipe.row, "item": o.recipe.raw, "per": o.recipe.item_unit,
                          "converted": not o.recipe.native, "checked_against": [x.row for x in o.others],
                          "components": [_line_out(ln, o.recipe) for ln in o.recipe.lines]} for o in s.options]}
            for s in systems
        ],  # fmt: skip
        "warnings": warnings,
        "unmatched": missing,
        "brands": [b for b, _ in Counter(o.brand for s in systems for o in s.options).most_common()],
    }


def _code(db: Session, prefix: str, text: str, model) -> str:
    """A code from the name, unique in the table (BOM-1A2B3C4D)."""
    base = f"{prefix}-{hashlib.sha1(text.encode()).hexdigest()[:8].upper()}"
    code, i = base, 1
    while db.scalar(select(model.id).where(model.code == code)):
        i += 1
        code = f"{base}-{i}"
    return code


def create_products(db: Session, wanted: list[dict], user_id) -> dict[str, Product]:
    """The products asked for, as the preview proposed them (the name without the pack, the file's
    name as an alias, the pack, the brand) with the last purchase price when the file gives one."""
    from app.costing.prices import record_price  # noqa: PLC0415  (costing imports masters)

    made: dict[str, Product] = {}
    for u in wanted:
        unit = u.get("unit") or "nos"
        name = u["create_as"]
        p = Product(code=_code(db, "BOM-P", norm(u["name"]), Product), name=name, brand=u.get("brand"), unit=unit,
                    aliases=[u["name"]] if norm(u["name"]) != norm(name) else [], created_by=user_id)  # fmt: skip
        if u.get("pack"):
            p.pack_size, p.pack_unit = D(str(u["pack"]["size"])), "pack"
        db.add(p)
        db.flush()
        if u.get("last_price") is not None and D(str(u["last_price"])) > 0:
            on = u.get("last_price_date")
            record_price(db, p.id, D(str(u["last_price"])), source="manual", user_id=user_id, ref="Company BOM",
                         on=date.fromisoformat(on) if isinstance(on, str) else on, note="the last purchase price in the company BOM")  # fmt: skip
        made[norm(u["name"])] = p
    return made


def save(db: Session, data: bytes, user_id, create: list[str] | None = None, default_brand: str | None = None) -> dict:
    """Write the file's systems: a new system per work item, or the one with the same name and unit
    updated (its company BOM options replaced; options made by hand kept). Products named in
    `create` are made first; any other name not in the master leaves its line out, said in the
    system's note and the result."""
    recipes = read(data)
    match_products(db, recipes)
    systems = plan(recipes)
    want = {norm(x) for x in (create or [])}
    proposals = [u for u in unmatched(recipes) if norm(u["name"]) in want]
    made = create_products(db, proposals, user_id)
    match_products(db, recipes)
    counts = Counter()
    counts["products_created"] = len(made)
    left_out: dict[str, list[int]] = {}
    for s in systems:
        system = _existing(db, s)
        if system is None:
            system = System(code=_code(db, "BOM", f"{norm(s.name)}|{s.unit}", System), name=s.name, unit=s.unit,
                            labour_rate=0, labour_unit="sqm" if s.unit == "sqm" else s.unit, created_by=user_id)  # fmt: skip
            db.add(system)
            db.flush()
            counts["systems_created"] += 1
        else:
            counts["systems_updated"] += 1
        kept_default = next((o.brand for o in system.options if o.is_default), None)
        gone = [o for o in system.options if o.source == "company_bom"]
        for c in [c for c in system.components if c.option_id in {o.id for o in gone}]:
            system.components.remove(c)
        for o in gone:
            system.options.remove(o)
        loose = [c for c in system.components if c.option_id is None]
        if loose and s.options:  # the recipe from before the BOM: its own option, not mixed in
            before = SystemOption(brand="Before the BOM", source="manual", sort_order=len(s.options) + 1, created_by=user_id)
            system.options.append(before)
            db.flush()
            for c in loose:
                c.option_id = before.id
        db.flush()
        names = {o.brand for o in s.options}
        default = default_brand if default_brand in names else kept_default if kept_default in names else s.options[0].brand if s.options else None
        if default is not None:
            for o in system.options:
                o.is_default = False
            db.flush()
        missing_here = []
        for i, po in enumerate(s.options):
            opt = SystemOption(brand=po.brand, is_default=po.brand == default, sort_order=i, source="company_bom",
                               source_ref=f"{po.recipe.raw}, row {po.recipe.row}", created_by=user_id)  # fmt: skip
            system.options.append(opt)
            db.flush()
            counts["options"] += 1
            for ln in po.recipe.lines:
                if ln.product_id is None:
                    missing_here.append(ln.raw)
                    left_out.setdefault(ln.raw, []).append(ln.row)
                    continue
                product = db.get(Product, ln.product_id)
                per_unit = _per_unit(ln, po.recipe)
                to_confirm, note = False, None
                if ln.unit and product.unit != ln.unit:
                    from app.masters.conversions import ConversionError, convert  # noqa: PLC0415

                    try:
                        per_unit = convert(db, per_unit, ln.unit, product.unit, product.id)
                        note = f"{n(_per_unit(ln, po.recipe))} {ln.unit} in the BOM, {n(per_unit)} {product.unit}"
                    except ConversionError:
                        to_confirm, note = True, f"The BOM gives it per {ln.unit}, the product is per {product.unit}: to confirm"
                system.components.append(SystemComponent(
                    product_id=product.id, option_id=opt.id, consumption_per_unit=q(per_unit), wastage_percent=0,
                    source="company_bom", wastage_included=ln.unit in WASTAGE_INCLUDED_UNITS,
                    original_consumption=ln.qty, original_unit=po.recipe.item_unit, to_confirm=to_confirm, note=note,
                    original_ref=f"[ {ln.raw} ] {n(ln.qty, 6)} {ln.unit_raw or ''} per {UNIT_LABEL[po.recipe.item_unit]}, row {ln.row}",
                    created_by=user_id,
                ))  # fmt: skip
                counts["components"] += 1
        notes = []
        if missing_here:
            notes.append(f"Not in the product master (left out): {', '.join(dict.fromkeys(missing_here))}")
        if any(not o.recipe.unit_in_name for o in s.options):
            notes.append("No unit in the BOM's name: read per nos (a point); check")
        system.source = "company_bom"
        system.to_confirm = bool(notes)
        system.note = "Company BOM. " + " ".join(notes) if notes else "Company BOM"
        db.flush()
    counts["systems"] = len(systems)
    counts["left_out_lines"] = sum(len(v) for v in left_out.values())
    return {"counts": dict(counts), "left_out": [{"name": k, "rows": v} for k, v in sorted(left_out.items())]}
