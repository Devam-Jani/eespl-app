# ruff: noqa: E501  (the word lists read better unwrapped)
"""The words one vocabulary for a data sheet (TDS), a BOQ line and a work item: the chemistry or
system type, the use area, the property values with their standard, and the unit conversions
(1 sqm = 10.7639 sq ft, 1 rmt = 3.2808 rft). Area keys are the knowledge library's
(knowledge.extract.AREA_TYPES) plus the few a spec needs on its own (pipe outlet, crack, tunnel)."""

import re
from decimal import Decimal

from app.knowledge.extract import AREA_LABEL

D = Decimal
SQFT_PER_SQM = D("10.7639")
RFT_PER_RMT = D("3.2808")
KGCM2_TO_NMM2 = D("0.0980665")

# (key, label, pattern): the chemistry of a product, the system type of a line or a work item.
# The narrow ones first: "PU primer" is a primer, "polyurea" is not PU.
TYPES: list[tuple[str, str, str]] = [
    ("primer", "primer", r"\bprimer\b"),
    (
        "mesh",
        "mesh / fabric",
        r"\bmesh\b|\bfabric\b|fibre\s*glass\s*cloth|fiber\s*glass\s*cloth|scrim",
    ),
    ("tape", "tape / band", r"\btape\b|\bband\b|joint\s*band|sealing\s*band"),
    ("geotextile", "geotextile", r"geo\s*-?\s*textile"),
    ("swellable", "swellable strip", r"swell|hydrophilic|water\s*bar|waterstop|water\s*stop"),
    ("polyurea", "polyurea", r"poly\s*-?\s*urea"),
    ("polysulphide", "polysulphide", r"poly\s*-?\s*sul(ph|f)ide"),
    ("silicone", "silicone", r"silicone"),
    ("ms_polymer", "MS polymer", r"\bms\s*polymer|silyl\s*modified|hybrid\s*polymer"),
    ("injection", "injection resin", r"inject"),
    (
        "admixture",
        "admixture",
        r"admixture|integral\s*water\s*proof|plasticiser|plasticizer|\bdosage\b.*cement",
    ),
    (
        "repair_mortar",
        "repair mortar",
        r"repair\s*mortar|micro\s*-?\s*concrete|\bgrout\b|polymer\s*modified\s*mortar",
    ),
    ("sbr_latex", "SBR latex", r"\bsbr\b|styrene\s*butadiene|latex"),
    ("crystalline", "crystalline", r"crystal"),
    ("hdpe", "HDPE", r"\bhdpe\b|high\s*density\s*poly\s*ethylene|pre\s*-?\s*applied"),
    ("pvc_tpo", "PVC / TPO", r"\bpvc\b|\btpo\b"),
    ("bituminous_app", "bituminous APP membrane", r"\bapp\b|atactic|torch"),
    (
        "bituminous_sbs",
        "bituminous SBS membrane",
        r"\bsbs\b|styrene\s*butadiene\s*styrene|self\s*-?\s*adhesive\s*(bitumen\s*)?membrane",
    ),
    ("bituminous", "bituminous", r"bitumin|bitumen"),
    ("epoxy", "epoxy", r"epoxy|epxoy"),
    ("pu", "PU", r"\bpu\b|polyurethane|poly\s*urethane|\bpur\b"),
    ("acrylic", "acrylic", r"acrylic|elastomeric"),
    (
        "cementitious",
        "cementitious",
        r"cementitious|cement\s*based|polymer\s*modified|polymer\s*cement|flexible\s*cement|\b2\s*k\b.*cement|two\s*component\s*cement",
    ),
    ("sealant", "sealant", r"sealant|joint\s*seal"),
    # a liquid membrane named by its system or brand ("COELASTIC EVO of KEMPER", "polyester resin
    # base flexible membrane"): last, so a sheet naming PU and a liquid membrane is PU
    (
        "liquid_membrane",
        "liquid membrane",
        r"kemper\w*|coelastic|triflex|polyester\s*resin"
        r"|liquid\s*applied\s*(?:[a-z]+\s+){0,2}membrane|liquid\s*(?:waterproofing\s*)?membrane",
    ),
]
TYPE_LABEL = {k: label for k, label, _p in TYPES}
# the layer types: they are steps of a system, never the system itself
LAYER_TYPES = {"primer", "mesh", "tape", "geotextile"}

# (key, pattern): the use areas a data sheet names and a BOQ line is for, narrow ones first
USES: list[tuple[str, str]] = [
    ("pipe_outlet", r"pipe|outlet|spout|khurra|rain\s*water|down\s*take|flashing"),
    ("expansion_joint", r"expansion\s*joint|movement\s*joint|\bEJ\b"),
    ("construction_joint", r"construction\s*joint|cold\s*joint"),
    ("crack", r"\bcracks?\b(?!\s*-?\s*bridg)"),  # "crack bridging" is a property, not the area
    ("tunnel", r"tunnel|metro|culvert"),
    ("swimming_pool", r"swimming|\bpools?\b"),
    (
        "oht",
        r"water\s*tank|potable|drinking\s*water|over\s*head\s*(water\s*)?tank|\bo\.?h\.?w?\.?t\b",
    ),
    ("ug_tank", r"\bsump|\bstp\b|\betp\b|sewage|under\s*ground\s*(water\s*)?tank"),
    ("lift_pit", r"lift\s*(pit|well)|elevator\s*pit"),
    ("planter", r"planter|landscape|green\s*roof|flower\s*bed"),
    ("podium", r"podium"),
    ("toilet", r"toilet|bath\s*room|\bwc\b|wash\s*room|wet\s*area|shower|kitchen|sunken"),
    (
        "basement",
        r"basement|raft|retaining\s*wall|foundation|below\s*ground|substructure|sub\s*-?\s*structure",
    ),
    ("terrace", r"terrace|\broofs?\b|roof\s*slab|\broofing|deck\s*slab|chajja|canopy|balcon"),
    ("external_wall", r"external\s*wall|facade|fa[cç]ade|exterior\s*wall|elevation"),
]
USE_LABEL = {
    **AREA_LABEL,
    "pipe_outlet": "Pipe / outlet", "expansion_joint": "Expansion joint", "construction_joint": "Construction joint",
    "crack": "Crack", "tunnel": "Tunnel", "oht": "Water tank (potable)", "ug_tank": "Sump / STP",
    "toilet": "Toilet / wet area", "basement": "Basement / raft / retaining wall", "terrace": "Terrace / roof",
}  # fmt: skip
# a line's area (the knowledge library's keys) to the use a data sheet names
AREA_TO_USE = {"raft": "basement", "retaining_wall": "basement", "sunken": "toilet", "kitchen": "toilet",
               "balcony": "terrace", "floor": None}  # fmt: skip

# (key, label, unit shown, pattern of the property's name)
PROPERTIES: list[tuple[str, str, str, str]] = [
    ("elongation", "elongation", "%", r"elongation"),
    ("tensile", "tensile strength", "N/mm²", r"tensile(?!\s*adhesion)"),
    ("adhesion", "adhesion", "N/mm²", r"adhesion|pull\s*-?\s*off|bond\s*strength"),
    ("shore_a", "Shore A hardness", "", r"shore\s*[‘'\"]?\s*a\b[’'\"]?|hardness"),
    ("crack_bridging", "crack bridging", "mm", r"crack\s*-?\s*bridg"),
    ("wvp", "water vapour permeability", "", r"vapou?r\s*(permeab|transmission|diffusion)"),
]
PROPERTY_LABEL = {k: label for k, label, _u, _p in PROPERTIES}
PROPERTY_UNIT = {k: u for k, _l, u, _p in PROPERTIES}
STANDARD = re.compile(
    r"\b(ASTM|IS|EN|BS|DIN|ISO)\s*[:\-]?\s*([A-Z]?\s*[-]?\s*\d{2,5}(?:[-:]\d+)*(?:\s*\(\s*part\s*\d+\s*\))?)(?:\s*[-–:,]\s*(?:19|20)\d{2}\b|\s*[-–:]\s*\d{2}\b)?",
    re.I,
)


def standard_of(text: str) -> str | None:
    """ "as per ASTM D-412" -> "ASTM D412"."""
    m = STANDARD.search(text)
    if not m:
        return None
    code = (
        re.sub(r"[\s\-]+", "", m.group(2).upper())
        if re.match(r"[A-Z]", m.group(2).strip(), re.I)
        else m.group(2).strip()
    )
    return f"{m.group(1).upper()} {code}"


def first_type(text: str, skip_layers: bool = False) -> str | None:
    low = (text or "").lower()
    for key, _label, pat in TYPES:
        if skip_layers and key in LAYER_TYPES:
            continue
        if re.search(pat, low):
            return key
    return None


def main_type(text: str, head: int = 0) -> str | None:
    """The type a text says most often (a system's, never a layer's: a paint sheet that says
    "primer" twice is not a primer). With `head`, the type named first, within the first `head`
    characters, counts three more ("two component PU based ..., grout around the outlets" is PU)."""
    low = (text or "").lower()
    counts, first = [], None
    for i, (k, _l, pat) in enumerate(TYPES):
        if k in LAYER_TYPES:
            continue
        m = re.search(pat, low)
        counts.append([len(re.findall(pat, low)), -i, k])
        if m and m.start() < head and (first is None or m.start() < first[0]):
            first = (m.start(), k)
    if first:
        next(c for c in counts if c[2] == first[1])[0] += 3
    best = max(counts)
    return best[2] if best[0] else None


def types_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [k for k, _l, pat in TYPES if re.search(pat, low)]


def uses_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [k for k, pat in USES if re.search(pat, low)]


# a line asking a "liquid membrane" takes any of these
FAMILY = {"liquid_membrane": {"pu", "polyurea", "acrylic", "bituminous", "liquid_membrane"}}


def same_family(a: str | None, b: str | None) -> bool:
    """A bituminous SBS membrane is bituminous; PU is PU; a liquid membrane is PU, polyurea,
    acrylic or bituminous."""
    if not a or not b:
        return False
    if b in FAMILY.get(a, ()) or a in FAMILY.get(b, ()):
        return True
    return a == b or a.startswith(b) or b.startswith(a)


def dec(s) -> Decimal | None:
    try:
        return D(str(s).replace(",", ".").strip())
    except Exception:  # noqa: BLE001
        return None


def q(v: Decimal | None, places: int = 4) -> Decimal | None:
    return None if v is None else v.quantize(D(1).scaleb(-places))
