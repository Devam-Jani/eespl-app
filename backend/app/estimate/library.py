# ruff: noqa: E501
"""The product consumption library: one coverage per product per system, read by the BOQ spec
check, the method statement check, the estimate, the site's material request, the margin check
and the bill's material check. A figure written in a BOQ or a method statement outside the
library's min and max is a warning before it is saved or sent.

Juno is why: its method statement said 1.2-1.5 kg/sqm for Ultrathane, the BOQ 1.8-1.9 and the
estimate 1.8. One library, and a check on what is written, keeps the three from drifting."""

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimate.models import Coverage
from app.masters.models import Product, System

D = Decimal
SQFT_PER_SQM = D("10.7639")
SOURCE_LABELS = {"tds": "data sheet (TDS)", "boq_spec": "BOQ spec", "method_statement": "method statement", "site_trial": "site trial", "to_confirm": "to confirm"}


def n(v: Decimal | int | None, places: int = 3) -> str:
    """A figure as people write it: up to `places` decimals, no trailing zeros."""
    if v is None:
        return "—"
    q = D(v).quantize(D(1).scaleb(-places), ROUND_HALF_UP)
    return f"{q.normalize():f}"


def grouped(v: Decimal | int, places: int = 0) -> str:
    """Indian grouping for quantities (8,349; 1,08,450)."""
    q = D(v).quantize(D(1).scaleb(-places), ROUND_HALF_UP)
    sign, s = ("-" if q < 0 else ""), f"{abs(q):f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    frac = frac.rstrip("0")
    return f"{sign}{whole}{'.' + frac if frac else ''}"


def per_sqm(value: Decimal, unit: str) -> Decimal:
    """The coverage as the product's own unit per sqm (kg, L or sqm of fabric per sqm)."""
    v = D(value)
    if unit in ("sqm/kg", "sqm/L"):
        return D(1) / v
    if unit == "kg/sqft":
        return v * SQFT_PER_SQM
    return v


def in_unit(value_per_sqm: Decimal, unit: str) -> Decimal:
    """A per-sqm figure written in the coverage's unit (to compare with what a spec says)."""
    if unit in ("sqm/kg", "sqm/L"):
        return D(1) / value_per_sqm
    if unit == "kg/sqft":
        return value_per_sqm / SQFT_PER_SQM
    return value_per_sqm


def coverage_for(db: Session, product_id: int, system_id: int | None) -> Coverage | None:
    """The system's own row, else the product's (system blank)."""
    if system_id is not None:
        c = db.scalar(select(Coverage).where(Coverage.product_id == product_id, Coverage.system_id == system_id))
        if c is not None:
            return c
    return db.scalar(select(Coverage).where(Coverage.product_id == product_id, Coverage.system_id.is_(None)))


def label(c: Coverage) -> str:
    rng = f" ({n(c.min_value)}–{n(c.max_value)})" if c.min_value is not None and c.max_value is not None else ""
    return f"{n(c.value, 4)} {c.unit}{rng}, {SOURCE_LABELS.get(c.source, c.source)}"


@dataclass
class Packs:
    count: int
    size: Decimal
    unit: str  # bag, drum, roll
    text: str


def packs(qty: Decimal, p: Product) -> Packs | None:
    """The quantity in the product's packs, always rounded up, the pack size beside the count."""
    if not p.pack_size or D(p.pack_size) <= 0:
        return None
    count = math.ceil(D(qty) / D(p.pack_size))
    kind = p.pack_unit or "pack"
    return Packs(count, D(p.pack_size), kind, f"{grouped(count)} {kind}{'s' if count != 1 else ''} of {n(p.pack_size)} {p.unit}")


def wastage(p: Product) -> Decimal:
    return D(p.wastage_percent or 0)


# --- what a BOQ or a method statement says --------------------------------------------------------

_NUM = r"(\d+(?:\.\d+)?)"
_RANGE = rf"{_NUM}(?:\s*(?:-|–|—|to)\s*{_NUM})?"
_PER_AREA = r"(?:sq\.?\s*m(?:tr|eter|etre)?s?\.?|m2|m²|sqm|sq\.?\s*ft\.?|sqft|ft2|ft²)"
FIGURE = re.compile(
    rf"{_RANGE}\s*(kgs?|kilograms?|ltrs?|litres?|liters?|l)\s*(?:/|per)\s*({_PER_AREA})|{_RANGE}\s*({_PER_AREA})\s*(?:/|per)\s*(kgs?|ltrs?|litres?|liters?|l)\b",
    re.I,
)
_SENTENCE = re.compile(r"(?<!\d)[.;\n](?!\d)")


def _area_is_sqft(text: str) -> bool:
    return "ft" in text.lower()


def figures(text: str) -> list[tuple[int, Decimal, Decimal, str]]:
    """Each coverage written in the text: (where, low, high, unit as kg/sqm, L/sqm, sqm/kg ...)."""
    out = []
    for m in FIGURE.finditer(text):
        if m.group(1):
            lo, hi = D(m.group(1)), D(m.group(2) or m.group(1))
            amount = "L" if m.group(3).lower().startswith("l") else "kg"
            unit = f"{amount}/sqft" if _area_is_sqft(m.group(4)) else f"{amount}/sqm"
        else:
            lo, hi = D(m.group(5)), D(m.group(6) or m.group(5))
            amount = "L" if m.group(8).lower().startswith("l") else "kg"
            unit = f"sqm/{amount}"
            if _area_is_sqft(m.group(7)):  # sqft per kg: as sqm per kg
                lo, hi = lo / SQFT_PER_SQM, hi / SQFT_PER_SQM
        out.append((m.start(), min(lo, hi), max(lo, hi), unit))
    return out


def _names(db: Session) -> list[tuple[str, Product]]:
    out = []
    for p in db.scalars(select(Product).where(Product.is_active.is_(True))):
        if not db.scalar(select(Coverage.id).where(Coverage.product_id == p.id).limit(1)):
            continue
        for name in {p.name, *(p.aliases or [])}:
            if name and len(name) >= 4:
                out.append((name, p))
    return sorted(out, key=lambda t: -len(t[0]))  # "Ultrathane Logic Foam" before "Ultrathane"


def _to_unit(lo: Decimal, hi: Decimal, unit: str, target: str) -> tuple[Decimal, Decimal] | None:
    """A written range in the library row's unit (kg/sqft to kg/sqm, sqm/kg to kg/sqm ...)."""
    if unit == target:
        return lo, hi
    if _amount(unit) != _amount(target):  # kg against litres: not comparable
        return None
    x, y = in_unit(per_sqm(lo, unit), target), in_unit(per_sqm(hi, unit), target)
    return min(x, y), max(x, y)


def _amount(unit: str) -> str:
    """What the coverage measures the product in: kg, L or sqm (of a fabric)."""
    a, b = unit.split("/")
    return b if a == "sqm" and b != "sqm" else a


def check_text(db: Session, text: str, system_id: int | None = None, where: str = "") -> list[dict]:
    """Each product named with a coverage outside the library's min and max (a figure with no
    product named before it in the same sentence is not judged)."""
    if not text:
        return []
    names = _names(db)
    out = []
    start = 0
    for sentence in [*_SENTENCE.split(text)]:
        offset = text.find(sentence, start)
        start = max(start, offset)
        found = figures(sentence)
        if not found:
            continue
        low = sentence.lower()
        taken: list[tuple[int, int]] = []
        hits = []
        for name, p in names:
            for m in re.finditer(rf"(?<![\w]){re.escape(name.lower())}(?![\w])", low):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                hits.append((m.start(), p))
        hits.sort(key=lambda t: t[0])
        for pos, lo, hi, unit in found:
            before = [p for at, p in hits if at < pos]
            if not before:
                continue
            p = before[-1]
            c = coverage_for(db, p.id, system_id)
            if c is None:
                continue
            got = _to_unit(lo, hi, unit, c.unit)
            if got is None:
                continue
            a, b = got
            lib_lo = D(c.min_value) if c.min_value is not None else D(c.value)
            lib_hi = D(c.max_value) if c.max_value is not None else D(c.value)
            if a < lib_lo - D("0.00005") or b > lib_hi + D("0.00005"):
                written = f"{n(lo)}–{n(hi)}" if lo != hi else n(lo)
                out.append({"product": p.name, "product_id": p.id, "where": where, "written": f"{written} {unit}",
                            "library": label(c), "coverage_id": c.id, "text": sentence.strip()[:300],
                            "warning": f"{where + ': ' if where else ''}{p.name} at {written} {unit} is outside the library's {n(lib_lo, 4)}–{n(lib_hi, 4)} {c.unit} ({SOURCE_LABELS.get(c.source, c.source)})"})  # fmt: skip
    return out


def system_name(db: Session, system_id: int | None) -> str | None:
    s = db.get(System, system_id) if system_id else None
    return s.name if s else None
