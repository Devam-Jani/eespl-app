"""Unit normalisation for everything that comes in from BOQs.

BOQs spell units dozens of ways ("Sq.m.", "SQMT", "Smt", "M2", "sq .mt"...). normalise_unit()
reduces a spelling to a lookup key (lower-case, letters and digits only, no "per" prefix, no
bracketed notes) and looks that up in the alias table. Anything it cannot place returns None
rather than a guess: "RO" (rate only), "Nos OR Sq Ft", "CM" (cm or cum?) and so on.

The canonical aliases live in the `units` table (seeded by migration 0005, editable later);
DEFAULT_UNITS below is the same list, used when no database aliases are passed in.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

# code: (name, aliases). Aliases are written as people write them; they are keyed on load.
# fmt: off
DEFAULT_UNITS: dict[str, tuple[str, list[str]]] = {
    "sqm": ("Square metre", [
        "sqm", "sq.m", "sq m", "sq.mt", "sqmt", "sq mtr", "sqmtr", "sq meter", "sq metre",
        "square metre", "square meter", "m2", "m²", "smt", "sm", "sqmts", "sqmtrs", "sq.mts"]),
    "sqft": ("Square foot", [
        "sqft", "sq.ft", "sq ft", "sft", "sqf", "sq feet", "square feet", "square foot", "ft2",
        "sq.fts", "sqfts"]),
    "rmt": ("Running metre", [
        "rmt", "rm", "r.mt", "rmtr", "rn.mtr", "running metre", "running meter", "rmts", "m",
        "mtr", "mtrs", "meter", "meters", "metre", "metres", "lm", "rm.", "r mt", "rn mt"]),
    "rft": ("Running foot", ["rft", "r ft", "r.ft", "running feet", "running foot", "rfeet"]),
    "cum": ("Cubic metre", [
        "cum", "cu.m", "cu m", "cumt", "cumtr", "cu mt", "cubic metre", "cubic meter", "m3",
        "m³", "cmt"]),
    "cft": ("Cubic foot", ["cft", "cu ft", "cu.ft", "cubic feet", "ft3"]),
    "kg": ("Kilogram", ["kg", "kgs", "kilogram", "kilograms", "kilo"]),
    "ltr": ("Litre", ["ltr", "ltrs", "litre", "litres", "liter", "liters", "lit", "l"]),
    "nos": ("Number", [
        "nos", "no", "no.", "nos.", "number", "numbers", "each", "ea", "ea.", "nr", "pcs", "pc",
        "piece", "pieces", "pt", "point", "points", "sausage"]),
    "set": ("Set", ["set", "sets"]),
    "roll": ("Roll", ["roll", "rolls"]),
    "ls": ("Lump sum", ["ls", "l.s", "lumpsum", "lump sum", "lumpsump", "job", "adhoc", "adhok"]),
}
# fmt: on


def unit_key(text: str) -> str:
    """Reduce a unit spelling to letters and digits: 'Sq. Mt.' -> 'sqmt', 'Per NO' -> 'no'."""
    t = text.replace("Ǫ", "Q").replace("ǫ", "q")  # 'SǪM' appears in real BOQs
    t = t.replace("²", "2").replace("³", "3")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"\(.*?\)", " ", t.lower())  # 'sqm (RO)' -> 'sqm'
    t = re.sub(r"^\s*per\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def build_alias_map(units: Iterable[tuple[str, Iterable[str]]]) -> dict[str, str]:
    """{key: code} from (code, aliases) pairs; the code itself is always an alias."""
    result: dict[str, str] = {}
    for code, aliases in units:
        for alias in [code, *aliases]:
            key = unit_key(alias)
            if key:
                result[key] = code
    return result


DEFAULT_ALIASES = build_alias_map((code, aliases) for code, (_, aliases) in DEFAULT_UNITS.items())


def normalise_unit(text: object, aliases: Mapping[str, str] | None = None) -> str | None:
    """Return the unit code for a BOQ unit spelling, or None if it is blank or unrecognised."""
    if text is None:
        return None
    key = unit_key(str(text))
    if not key:
        return None
    return (aliases if aliases is not None else DEFAULT_ALIASES).get(key)


def load_aliases(db: Session) -> dict[str, str]:
    """The alias map as currently stored in the units table."""
    from app.masters.models import Unit

    return build_alias_map(db.execute(select(Unit.code, Unit.aliases)).tuples())
