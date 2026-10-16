# ruff: noqa: E501  (patterns read better unwrapped)
"""Words shared by the method library, the client standards and the BOQ methodology: the
elements (raft, toilet, terrace ...), the system types (2K PU, acrylic cementitious, HDPE ...),
the properties of a data sheet or a specification (elongation, DFT ...) and reading a value with
its limit ("min. 120%", ">300 %", "1.5 mm DFT") out of a sentence."""

import re
from dataclasses import dataclass

# (key, label, pattern); the more specific first
ELEMENTS: list[tuple[str, str, str]] = [
    ("pressure_relief", "Pressure release pipe & rock anchor", r"pressure\s*release|rock\s*anchor"),
    ("pile_head", "Pile head", r"pile\s*head"),
    ("pipe_penetration", "Pipe penetration", r"pipe\s*penetration"),
    ("construction_joint", "Construction joint", r"construction\s*joint"),
    ("tie_rod", "Tie rod holes", r"tie\s*rod"),
    ("expansion_joint", "Expansion joint", r"expansion\s*joint"),
    ("lift_pit", "Lift pit", r"lift\s*pit|elevator\s*pit"),
    ("stp", "Sewage treatment tank", r"sewage|\bstp\b|\betp\b|effluent"),
    ("swimming_pool", "Swimming pool", r"swimming|\bpool\b|water\s*body"),
    (
        "oht",
        "Overhead water tank",
        r"over\s*-?\s*head\s*(water\s*)?tank|\bo\.?\s*h\.?\s*w\.?\s*t\b|\bohwt\b|\boht\b",
    ),
    (
        "ug_tank",
        "Underground water tank",
        r"under\s*-?\s*ground\s*(water\s*)?tank|\bu\.?\s*g\.?\s*(w\.?\s*)?t(ank)?\b|\bugwt\b|\bsump\b|u\.g\.\s*tank",
    ),
    ("retaining_wall", "Retaining wall", r"retaining\s*wall|basement\s*wall"),
    ("footing", "Isolated footing", r"footing"),
    ("raft", "Raft", r"\braft\b"),
    ("refuge", "Refuge / service floor", r"refuge|service\s*floor|fire\s*check"),
    ("toilet", "Toilet", r"toilet|bath\s*room|\bwc\b|w\.c\.|wet\s*area"),
    ("balcony", "Balcony & utility", r"balcon|utility|\bwash\b|kitchen\s*yard|sit\s*out"),
    ("sunken", "Sunken area", r"sunk(en)?\b"),
    ("podium", "Podium", r"podium"),
    ("planter", "Garden & planter", r"planter|garden|landscape"),
    ("terrace", "Terrace", r"terrace|\broof\b|drive\s*way"),
    ("tank", "Water tank", r"\btank\b"),
]
ELEMENT_LABEL = {k: label for k, label, _p in ELEMENTS}
_ELEMENT_RE = [(k, re.compile(p, re.I)) for k, _l, p in ELEMENTS]


def element_of(text: str | None) -> str | None:
    for key, rx in _ELEMENT_RE:
        if rx.search(text or ""):
            return key
    return None


def elements_in(text: str | None) -> list[str]:
    """Every element a title names ("Sunken, kitchen yard & balcony" -> sunken, balcony)."""
    return [k for k, rx in _ELEMENT_RE if rx.search(text or "")]


# the main waterproofing layer: what the client's rule asks for and what our system is
SYSTEM_TYPES: list[tuple[str, str, str]] = [
    ("hdpe", "Pre-applied HDPE membrane", r"\bhdpe\b"),
    (
        "sbs",
        "SBS modified bitumen membrane",
        r"\bsbs\b|modified\s*bitumen|bituminous\s*membrane|app\s*membrane",
    ),
    ("tpo", "TPO / TPE membrane", r"\btpo\b|\btpe\b"),
    ("coal_tar_epoxy", "Coal tar epoxy coating", r"coal\s*-?\s*tar|\bcte\b"),
    ("pu_hybrid", "Hybrid polyurea", r"polyurea"),
    ("pu", "Polyurethane (PU) coating", r"poly\s*-?\s*urethane|\bpu\b|ultrashield"),
    ("crystalline", "Crystalline coating", r"crystal"),
    ("epoxy", "Epoxy coating / mortar", r"epoxy"),
    (
        "polymer_mortar",
        "Polymer modified mortar",
        r"polymer\s*modified[^.]{0,40}mortar|shrinkage\s*compensated",
    ),
    (
        "acrylic_cementitious",
        "Acrylic (elastomeric) cementitious coating",
        r"(acrylic|elastomeric|polymer\s*modified)[^.]{0,40}cementitious|cementitious[^.]{0,30}(acrylic|elastomeric)|cemguard|two\s*component\s*acrylic|2\s*k\s*elastomeric",
    ),
    ("cementitious", "Cementitious coating", r"cementitious"),
    ("sealant", "Sealant", r"sealant|polysulphide|rubber\s*based"),
]
SYSTEM_LABEL = {k: label for k, label, _p in SYSTEM_TYPES}
_SYSTEM_RE = [(k, re.compile(p, re.I)) for k, _l, p in SYSTEM_TYPES]
# the types that satisfy a required one (2K PU is met by a hybrid PU; a hybrid polyurea by a PU)
SATISFIES = {
    "pu": {"pu", "pu_hybrid"},
    "pu_hybrid": {"pu_hybrid", "pu"},
    "acrylic_cementitious": {"acrylic_cementitious"},
    "cementitious": {"cementitious", "acrylic_cementitious"},
}


def system_type_of(text: str | None) -> str | None:
    """The system the text names first ("2 mm SBS membrane laminated on an HDPE film" is SBS;
    "1.5 mm 2K PU on the floor and acrylic cementitious on walls" is PU); coal tar wins where it
    is named in a product's name (BRONCO CEMGUARD CTE is a coal tar epoxy, not a Cemguard acrylic)."""
    t = text or ""
    if len(t) < 60 and re.search(r"coal\s*-?\s*tar|\bcte\b", t, re.I):
        return "coal_tar_epoxy"
    best: tuple[int, int, str] | None = None
    for i, (key, rx) in enumerate(_SYSTEM_RE):
        m = rx.search(t)
        if m and (best is None or (m.start(), i) < best[:2]):
            best = (m.start(), i, key)
    return best[2] if best else None


def family(t: str | None) -> str | None:
    """A plain "cementitious" in a client's text is the acrylic (elastomeric) kind."""
    return {"cementitious": "acrylic_cementitious"}.get(t or "", t)


def satisfies(ours: str | None, required: str | None) -> bool:
    if not required:
        return True
    return bool(ours) and ours in SATISFIES.get(required, {required})


# properties of a data sheet / a minimum specification
PROPERTIES: list[tuple[str, str, str, str]] = [
    # key, label, unit, pattern
    ("elongation", "Elongation", "%", r"elongation"),
    ("tensile", "Tensile strength", "MPa", r"tensile"),
    ("peel_adhesion", "Peel adhesion", "N/m", r"peel\s*adhesion"),
    ("adhesion", "Adhesion (pull-off)", "MPa", r"adhesion|pull\s*off|bond\s*strength"),
    ("crack_bridging", "Crack bridging", "mm", r"crack\s*(bridging|accommodation)"),
    ("dft", "Dry film thickness (DFT)", "mm", r"\bdft\b|dry\s*film\s*thickness|film\s*thickness"),
    ("thickness", "Thickness", "mm", r"thickness|\bthick\b"),
    ("consumption", "Consumption", "kg/m²", r"consumption|kg\s*/\s*m|kg\s*per\s*sq"),
    ("mesh_gsm", "Mesh / fabric", "GSM", r"\bgsm\b"),
    ("puncture", "Puncture resistance", "N", r"puncture"),
    ("hydrostatic", "Resistance to hydrostatic pressure", "m", r"hydrostatic"),
    ("solid_content", "Solid content", "%", r"solid\s*content|solids"),
    ("hardness", "Hardness (Shore A)", "", r"hardness|shore"),
    ("water_vapour", "Water vapour transmission", "g/m²/hr", r"vapou?r"),
    ("root_resistance", "Root resistance", "", r"root\s*resist"),
    ("pot_life", "Pot life", "", r"pot\s*life"),
    ("coverage", "Coverage", "", r"coverage"),
    ("abrasion", "Abrasion resistance", "", r"abrasion"),
    ("compressive", "Compressive strength", "MPa", r"compressive"),
]
PROPERTY_LABEL = {k: label for k, label, _u, _p in PROPERTIES}
PROPERTY_UNIT = {k: u for k, _l, u, _p in PROPERTIES}
_PROP_RE = [(k, re.compile(p, re.I)) for k, _l, _u, p in PROPERTIES]
# a bigger number is better for these; DFT and thickness count as minimums too
HIGHER_IS_BETTER = {"elongation", "tensile", "peel_adhesion", "adhesion", "crack_bridging", "dft",
                    "thickness", "consumption", "mesh_gsm", "puncture", "hydrostatic", "solid_content", "compressive"}  # fmt: skip

STANDARD_RE = re.compile(
    r"\b(ASTM\s*[A-Z]\s*-?\s*\d+|IS\s*:?\s*\d{3,5}|EN\s*\d{3,5}|BS\s*\d{3,5}(?:[-–]\d+)?)", re.I
)


def property_of(text: str | None) -> str | None:
    for key, rx in _PROP_RE:
        if rx.search(text or ""):
            return key
    return None


def standard_of(text: str | None) -> str | None:
    m = STANDARD_RE.search(text or "")
    return (
        re.sub(r"\s+", " ", m.group(1))
        .upper()
        .replace("ASTM D ", "ASTM D")
        .replace("ASTMD", "ASTM D")
        if m
        else None
    )


@dataclass
class Limit:
    op: str  # min, max, eq, range
    num: float
    hi: float | None = None
    unit: str = ""

    def text(self) -> str:
        u = f" {self.unit}" if self.unit and self.unit != "%" else self.unit
        if self.op == "range" and self.hi is not None:
            return f"{_n(self.num)}–{_n(self.hi)}{u}"
        return {"min": "min. ", "max": "max. ", "eq": ""}[self.op] + f"{_n(self.num)}{u}"


def _n(v: float) -> str:
    return f"{v:g}"


NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(%|mpa|n/mm2|n/mm²|n/m\b|n\b|mm\b|microns?|µ|μ|kg/m2|kg/m²|kg/sqm|kg|gsm|m\b|hrs?|hours?|g/m2/hr)"
_LIMIT_RE = re.compile(
    r"(min(?:imum)?\.?|max(?:imum)?\.?|not\s*less\s*than|at\s*least|>\s*=?|<\s*=?|≥|≤|about|upto|up\s*to)?\s*"
    + NUM
    + r"\s*(?:(?:-|–|to)\s*"
    + NUM
    + r")?\s*"
    + _UNIT
    + "?",
    re.I,
)


def limit_of(text: str | None, prop: str | None = None) -> Limit | None:
    """The first value with its limit in a requirement: "min. 120%" -> min 120 %; ">300 %" ->
    min 300; "300 to 500 microns" -> range 0.3–0.5 mm; "1.5 mm" -> eq 1.5 (a minimum where the
    property is one where more is better)."""
    if not text:
        return None
    for m in _LIMIT_RE.finditer(text):
        word, a, b, unit = m.group(1), m.group(2), m.group(3), (m.group(4) or "").lower()
        if not unit and not word and prop not in ("hardness", "elongation"):
            # a bare number: a section or list number unless it is all there is
            if len(text.strip()) > len(m.group(0).strip()) + 3:
                continue
        num, hi = float(a), float(b) if b else None
        if unit.startswith("micron") or unit in ("µ", "μ"):
            num, hi, unit = num / 1000, (hi / 1000 if hi is not None else None), "mm"
        unit = {"n/mm2": "MPa", "n/mm²": "MPa", "mpa": "MPa", "kg/m2": "kg/m²", "kg/sqm": "kg/m²", "kg/m²": "kg/m²",
                "gsm": "GSM", "n/m": "N/m", "n": "N", "hr": "h", "hrs": "h", "hour": "h", "hours": "h"}.get(unit, unit)  # fmt: skip
        w = (word or "").lower().replace(" ", "")
        if hi is not None:
            op = "range"
        elif w.startswith("min") or w in ("notlessthan", "atleast", ">", ">=", "≥"):
            op = "min"
        elif w.startswith("max") or w in ("<", "<=", "≤", "upto"):
            op = "max"
        else:
            op = "min" if prop in HIGHER_IS_BETTER else "eq"
        return Limit(op, num, hi, unit or PROPERTY_UNIT.get(prop or "", ""))
    return None


def specs_in(text: str) -> dict[str, Limit]:
    """The values a system description states: "minimum elongation of 150%, at a total
    consumption rate of 2 kg/m² and minimum DFT 1 mm, reinforced with a 45 GSM glass fibre mesh"
    -> elongation min 150 %, consumption min 2 kg/m², dft min 1 mm, mesh_gsm 45."""
    out: dict[str, Limit] = {}
    t = re.sub(r"\s+", " ", text or "")
    pats = [
        ("elongation", r"elongation[^.,;%]{0,25}?" + NUM + r"\s*%", "%"),
        ("elongation", NUM + r"\s*%\s*elongation", "%"),
        ("consumption", NUM + r"\s*kg\s*/\s*m", "kg/m²"),
        (
            "dft",
            r"(?:dft|dry\s*film\s*thickness)\s*(?:\(dft\)\s*)?(?:of\s*)?" + NUM + r"\s*mm",
            "mm",
        ),
        ("dft", NUM + r"\s*mm\s*(?:dry\s*film\s*thickness|dft)", "mm"),
        ("mesh_gsm", NUM + r"\s*gsm", "GSM"),
        ("thickness", NUM + r"\s*mm\s*(?:thick|hdpe|sbs|tpo)", "mm"),
        ("thickness", r"(?:hdpe|membrane)\s*\(?" + NUM + r"\s*mm", "mm"),
    ]
    for key, pat, unit in pats:
        if key in out:
            continue
        m = re.search(pat, t, re.I)
        if m:
            out[key] = Limit("min", float(m.group(1)), None, unit)
    return out


def hours_in(text: str) -> int | None:
    t = text or ""
    m = re.search(r"(\d+)\s*days?\s*\(\s*(\d+)\s*h", t, re.I)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+)\s*(?:hours|hrs|hr|h)\b", t, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*days?\b", t, re.I)
    return int(m.group(1)) * 24 if m else None


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()
