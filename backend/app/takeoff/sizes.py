"""Reading sizes and waterproofing notes out of drawing texts.

Room labels often carry their size: LADIES TOILET 10'6"X7'3", TERRACE 75'3¼"X13'6", KITCHEN
3000X2400, BALCONY 3.0 x 2.4 M. Sizes are read in feet and inches (fractions as ¼ ½ ¾ ⅛ or 1/2),
in millimetres and in metres, with or without spaces. The drawing's own unit does not matter for
a label: the label says its unit (feet-inches marks, MM, M; whole numbers of 100 and more are mm).

Notes such as CHEMICAL WATER PROOFING, 600 MM SUNK, 6" SUNK + 6" RAISE are recognised by their
words, and a sunk depth or a raise is read from them.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

FRACTIONS = {"¼": 0.25, "½": 0.5, "¾": 0.75, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}
FRAC = "".join(FRACTIONS)
INCH_M = 0.0254
FOOT_M = 0.3048
X = r"\s*[xX×*]\s*"

# 10'6"  75'3¼"  10'-6"  10' 6 1/2"  10'  (feet then optional inches)
FT_IN = (
    # the inch mark may be typed as a single quote too (7'0'X7'8½" in a real drawing)
    rf"(\d+)\s*(?:'|’|′)\s*-?\s*(?:(\d+)\s*([{FRAC}]|\s+\d+/\d+|/\d+)?\s*(?:\"|”|″|''|'|’)?)?"
)
FT_IN_SIZE = re.compile(FT_IN + X + FT_IN)
MM_SIZE = re.compile(r"(?<![\d.])(\d{3,5})" + X + r"(\d{3,5})(?![\d.])\s*(?:mm|MM)?")
M_SIZE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d{1,3})?)" + X + r"(\d{1,3}(?:\.\d{1,3})?)\s*(?:m|M|mtr|MTR)\b"
)

WATERPROOF_WORDS = (
    "WATER PROOFING", "WATERPROOFING", "WATER-PROOFING", "CHEMICAL", "SUNKEN", "SUNK", "RAISE",
    "TERRACE", "TOILET", "BATH", "KITCHEN", "BALCONY", "OHT", "UG TANK", "UGT", "LIFT PIT",
    "RAFT", "PLANTER", "POOL", "W.C", "WC", "WASH",
)  # fmt: skip
DEPTH = re.compile(
    r"(\d+(?:\.\d+)?)\s*(MM|CM|M|\"|”|INCH(?:ES)?|''|'|FT|FEET)?\s*(SUNK(?:EN)?|DEEP|DEPTH|DROP|RAISE[D]?)",
    re.IGNORECASE,
)
UNIT_M = {"MM": 0.001, "CM": 0.01, "M": 1.0, '"': INCH_M, "”": INCH_M, "INCH": INCH_M,
          "INCHES": INCH_M, "''": INCH_M, "'": FOOT_M, "FT": FOOT_M, "FEET": FOOT_M}  # fmt: skip


@dataclass
class Size:
    width_m: float
    length_m: float
    kind: str  # ft-in, mm, m
    text: str  # the size as written

    @property
    def area_sqm(self) -> float:
        return self.width_m * self.length_m


def _inches(whole: str | None, frac: str | None) -> float:
    v = float(whole or 0)
    f = (frac or "").strip()
    if f in FRACTIONS:
        v += FRACTIONS[f]
    elif f.startswith("/") and whole:  # 3/4" written as 3 then /4: a fraction alone
        v = float(whole) / float(f[1:])
    elif "/" in f:
        a, b = f.split("/")
        v += float(a) / float(b)
    return v


def _ft_in(feet: str, inch: str | None, frac: str | None) -> float:
    return float(feet) * FOOT_M + _inches(inch, frac) * INCH_M


def parse_size(text: str) -> Size | None:
    """The first size in the text, in metres; None when the text has no size."""
    t = (text or "").replace("\u00a0", " ")
    m = FT_IN_SIZE.search(t)
    if m:
        a = _ft_in(m.group(1), m.group(2), m.group(3))
        b = _ft_in(m.group(4), m.group(5), m.group(6))
        return Size(a, b, "ft-in", m.group(0).strip())
    m = M_SIZE.search(t)
    if m:
        return Size(float(m.group(1)), float(m.group(2)), "m", m.group(0).strip())
    m = MM_SIZE.search(t)
    if m:
        return Size(float(m.group(1)) / 1000, float(m.group(2)) / 1000, "mm", m.group(0).strip())
    return None


def label_name(text: str, size: Size | None) -> str:
    """The room's name: the label without its size."""
    t = " ".join((text or "").split())
    if size:
        t = t.replace(size.text, " ")
    t = re.sub(r"[\s:\-–,(]+$", "", re.sub(r"^[\s:\-–,)]+", "", t))
    return " ".join(t.split())


def is_waterproofing_note(text: str) -> bool:
    up = " ".join((text or "").upper().split())
    return any(re.search(rf"(?<![A-Z]){re.escape(w)}(?![A-Z])", up) for w in WATERPROOF_WORDS)


@dataclass
class Depths:
    sunk_m: float | None = None
    raise_m: float | None = None


def depths(text: str) -> Depths:
    """600 MM SUNK -> sunk 0.6 m; 6" SUNK + 6" RAISE -> sunk and raise 0.1524 m each."""
    out = Depths()
    for m in DEPTH.finditer(text or ""):
        unit = (m.group(2) or "MM").upper()
        value = float(m.group(1)) * UNIT_M.get(unit, 0.001)
        if m.group(3).upper().startswith("RAISE"):
            out.raise_m = value
        else:
            out.sunk_m = value
    return out


def dec(v: float, places: str = "0.001") -> Decimal:
    return Decimal(str(v)).quantize(Decimal(places))
