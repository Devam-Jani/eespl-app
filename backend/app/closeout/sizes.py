# ruff: noqa: E501  (messages read better unwrapped)
"""Sizes as site teams take them: metres, or feet and inches off a tape ("20 ft" corrected to
"19 ft 5 in"). Stored in metres; the typed text is kept beside it so the sheet and the client's
correction show both ("19 ft 5 in = 5.918 m"). And the unit a measurement line is in: the
accepted work order's (running length for rmt, L x B for sqm)."""

import re
from decimal import ROUND_HALF_UP, Decimal

from app.closeout.common import unprocessable

FT = Decimal("0.3048")
INCH = Decimal("0.0254")
Q3 = Decimal("0.001")
SQFT_PER_SQM = Decimal("10.7639")
LENGTH_FIELDS = ("length_m", "breadth_m", "perimeter_m", "height_m")

_METRES = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:m|mt|mtr|metres?|meters?)?\s*$", re.I)
_IMPERIAL = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)?)\s*(?:ft|feet|foot|')\s*)?(?:(\d+(?:\.\d+)?)\s*(?:in|inch|inches|\"|'')\s*)?$",
    re.I,
)

# units a line can be in, by how it is measured
LINEAR = {"rmt": Decimal(1), "rft": 1 / FT}  # running length: metres -> the unit
AREA = {"sqm": Decimal(1), "sqft": SQFT_PER_SQM}  # L x B (or perimeter x height) in sqm -> unit
ALIASES = {"sqmt": "sqm", "m2": "sqm", "sqmtr": "sqm", "sft": "sqft", "rm": "rmt", "rmtr": "rmt", "runningmetre": "rmt",
           "runningmeter": "rmt", "no": "nos", "cumt": "cum", "m3": "cum"}  # fmt: skip


def unit_code(u: str | None) -> str:
    u = (u or "").strip().lower().replace(".", "").replace(" ", "")
    return ALIASES.get(u, u)


def parse_length(value) -> tuple[Decimal | None, str | None]:
    """'5.918', '5.918 m', '19 ft 5 in', "19' 5\"", '19.5 ft', '7 in' -> (metres, the typed text
    when it was not metres)."""
    if value is None or value == "":
        return None, None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).quantize(Q3, ROUND_HALF_UP), None
    text = str(value).strip()
    m = _METRES.match(text)
    if m:
        return Decimal(m.group(1)).quantize(Q3, ROUND_HALF_UP), None
    m = _IMPERIAL.match(text)
    if m and (m.group(1) or m.group(2)):
        feet, inches = Decimal(m.group(1) or 0), Decimal(m.group(2) or 0)
        metres = (feet * FT + inches * INCH).quantize(Q3, ROUND_HALF_UP)
        return metres, feet_text(feet, inches)
    raise unprocessable(f"'{text}' is not a size: write it in metres (5.918) or feet and inches (19 ft 5 in)")


def feet_text(feet: Decimal, inches: Decimal) -> str:
    feet, inches = feet.normalize(), inches.normalize()
    parts = ([f"{feet:f} ft"] if feet else []) + ([f"{inches:f} in"] if inches else [])
    return " ".join(parts) or "0 ft"


def shown(metres, typed: str | None) -> str:
    """'19 ft 5 in = 5.918 m', or '5.918 m'."""
    if metres is None:
        return ""
    m = f"{Decimal(metres).quantize(Q3, ROUND_HALF_UP)} m"
    return f"{typed} = {m}" if typed else m


def normalise(data: dict) -> dict:
    """The size fields in metres, with what was typed in feet and inches kept in "entered"."""
    entered = dict(data.get("entered") or {})
    for f in LENGTH_FIELDS:
        if f not in data:
            continue
        metres, typed = parse_length(data[f])
        data[f] = metres
        if typed:
            entered[f] = typed
        else:
            entered.pop(f, None)
    data["entered"] = entered or None
    return data


def check_unit(line_unit: str, data: dict, what: str, source: str | None) -> str:
    """The measurement's unit is the line's: a different one is refused with the reason, and the
    sizes must fit it (running length for rmt, L x B or perimeter x height for sqm)."""
    unit = unit_code(line_unit) or "sqm"
    given = unit_code(data.get("unit"))
    who = f"The work order {source}" if source else "The contract"
    if given and given != unit:
        raise unprocessable(f"{who} measures '{what[:60]}' per {unit}: a measurement in {given} is refused ({_how(unit)})")
    if unit in LINEAR and data.get("breadth_m") is not None:
        raise unprocessable(f"{who} measures '{what[:60]}' per {unit}: {_how(unit)}, not L x B")
    if unit in AREA and data.get("length_m") is not None and data.get("breadth_m") is None and data.get("height_m") is None:
        raise unprocessable(f"'{what[:60]}' is per {unit}: {_how(unit)}")
    return unit


def _how(unit: str) -> str:
    if unit in LINEAR:
        return "give the running length (or the perimeter)"
    if unit in AREA:
        return "give L x B, or perimeter x height"
    return f"give the quantity in {unit}"


def qty_in(unit: str, length, breadth, perimeter, height, deductions, typed_qty) -> Decimal:
    """The quantity in the line's unit from the sizes (metres), less deductions (in the unit)."""
    unit = unit_code(unit) or "sqm"
    d = Decimal(deductions or 0)
    if unit in LINEAR:
        run = length if length is not None else perimeter
        if run is None:
            return Decimal(typed_qty or 0)
        q = Decimal(run) * LINEAR[unit]
    elif unit in AREA:
        if length is not None and breadth is not None:
            q = Decimal(length) * Decimal(breadth) * AREA[unit]
        elif perimeter is not None and height is not None:
            q = Decimal(perimeter) * Decimal(height) * AREA[unit]
        else:
            return Decimal(typed_qty or 0)
    else:
        return Decimal(typed_qty or 0)
    return max(Decimal(0), q - d).quantize(Q3, ROUND_HALF_UP)
