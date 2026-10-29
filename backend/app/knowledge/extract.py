# ruff: noqa: E501  (the word lists read better unwrapped)
"""What a BOQ line says, read from its words: the area type, the surface, the client's
requirements (coats, minimum thickness, kg per sqm, DFT, protection, warranty, brand), the
system family; and where and when the BOQ was (the place from the folder and file name or the
sheet's text, the date from the file name, the sheet, or the file's own date)."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.timefmt import ist_today

# (key, label, pattern): the first that matches wins, so the narrow ones come first
AREA_TYPES: list[tuple[str, str, str]] = [
    ("expansion_joint", "Expansion joint", r"expansion\s*joint|\bEJ\b|construction\s*joint"),
    ("sunken", "Sunken area", r"sunk(en)?\b|sunken\s*slab"),
    (
        "toilet",
        "Toilet / bathroom",
        r"toilet|bath\s*room|\bwc\b|w\.c\.|wash\s*room|wet\s*area|shower",
    ),
    ("kitchen", "Kitchen", r"kitchen|pantry"),
    ("balcony", "Balcony", r"balcon|verandah|sit\s*out"),
    ("swimming_pool", "Swimming pool", r"swimming|\bpool\b|water\s*body|fountain"),
    (
        "oht",
        "Overhead water tank",
        r"over\s*head\s*(water\s*)?tank|\bo\.?h\.?w?\.?t\b|overhead\s*tank",
    ),
    (
        "ug_tank",
        "Underground water tank",
        r"under\s*ground\s*(water\s*)?(tank|sump)|\bu\.?g\.?\s*(w\.?\s*)?t(ank)?\b|\bsump\b|fire\s*tank|\bstp\b|\betp\b",
    ),
    ("lift_pit", "Lift pit", r"lift\s*(pit|well)|elevator\s*pit"),
    ("planter", "Planter", r"planter|landscape|flower\s*bed"),
    ("podium", "Podium", r"podium"),
    ("raft", "Raft", r"\braft\b|foundation\s*slab|below\s*raft|pcc\s*bed"),
    (
        "retaining_wall",
        "Retaining wall",
        r"retaining\s*wall|basement\s*wall|\bR\.?W\b|diaphragm\s*wall|shear\s*wall\s*external",
    ),
    ("basement", "Basement", r"basement"),
    ("terrace", "Terrace / roof", r"terrace|\broof|roof\s*slab|chajja|canopy|parapet"),
    (
        "external_wall",
        "External wall",
        r"external\s*wall|facade|fa[cç]ade|elevation|exterior\s*wall",
    ),
    ("floor", "Floor coating", r"floor(ing)?\b|epoxy\s*floor|pu\s*floor|car\s*park|parking"),
]
AREA_LABEL = {k: label for k, label, _p in AREA_TYPES}
SURFACES: list[tuple[str, str]] = [
    (
        "old_tiles",
        r"(old|existing)\s*til(e|es|ing)|over\s*(the\s*)?(existing\s*)?til|china\s*mosaic",
    ),
    ("metal", r"metal|steel|\bms\b|g\.?i\.?\s*sheet|roof\s*sheet|tin\s*shed|sheet\s*roof"),
    ("screed", r"screed|ips\b|brick\s*bat|\bbbcc\b|\bpcc\b"),
    ("plaster", r"plaster"),
    ("brick", r"brick\s*(wall|work|masonry)|\bmasonry|block\s*work|aac\s*block"),
    ("rcc", r"\brcc\b|r\.c\.c|concrete|slab\b|raft|wall\s*surface"),
]
FAMILIES: list[tuple[str, str]] = [
    # a layer that names the line on its own (a geotextile over the coating is a geotextile line)
    ("geotextile", r"geo\s*-?\s*textile"),
    ("brick_bat_coba", r"brick\s*bat|\bbbc\b|\bbbcc\b"),
    ("china_mosaic", r"china\s*mosaic"),
    ("crystalline", r"crystal"),
    ("pu", r"\bpu\b|polyurethane|poly\s*urethane"),
    ("polyurea", r"polyurea"),
    ("acrylic", r"acrylic|elastomeric"),
    (
        "cementitious",
        r"cementitious|polymer\s*modified|2\s*k\s*cement|two\s*component\s*cement|flexible\s*cement",
    ),
    ("app_membrane", r"\bapp\b|torch|bitumen\s*membrane|modified\s*bitumen"),
    ("sbs_membrane", r"\bsbs\b"),
    ("hdpe", r"hdpe|pre[\s-]*applied"),
    ("pvc_tpo", r"\bpvc\b|\btpo\b"),
    ("bituminous", r"bitumin|bituminous"),
    ("epoxy", r"epoxy"),
    ("injection", r"injection|grout"),
    ("liquid_membrane", r"liquid\s*(applied\s*)?membrane"),
    ("swellable", r"swell|hydrophilic|water\s*bar|waterstop"),
]
FAMILY_LABEL = {
    "crystalline": "crystalline", "pu": "PU", "polyurea": "polyurea", "acrylic": "acrylic", "cementitious": "cementitious",
    "app_membrane": "APP membrane", "sbs_membrane": "SBS membrane", "hdpe": "HDPE", "pvc_tpo": "PVC / TPO", "bituminous": "bituminous",
    "epoxy": "epoxy", "injection": "injection", "liquid_membrane": "liquid membrane", "swellable": "swellable / water bar",
    "geotextile": "geotextile", "brick_bat_coba": "brick bat coba", "china_mosaic": "china mosaic",
}  # fmt: skip
BRANDS: list[tuple[str, str]] = [
    ("Dr. Fixit / Pidilite", r"dr\.?\s*fixit|pidilite"), ("Sika", r"\bsika"), ("Fosroc", r"fosroc"),
    ("BASF / Master Builders", r"\bbasf\b|master\s*(seal|builders)"), ("Asian Paints", r"\basian\b|smartcare"),
    ("Bronco", r"bronco"), ("Technonicol", r"technonicol|tn\b"), ("Tikidan", r"tikidan"), ("Chryso", r"chryso"),
    ("Mapei", r"mapei"), ("Ardex", r"ardex"), ("Xypex", r"xypex"), ("Kryton", r"kryton"), ("Penetron", r"penetron"),
    ("Berger", r"berger"), ("Nerolac", r"nerolac"), ("Arcon", r"\barcon\b"), ("Choksey", r"choksey"), ("Armourcrete", r"armourcrete"),
]  # fmt: skip
WORDS_N = {"one": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4}

# the default regions (Settings: the list is editable): city / area -> region
DEFAULT_REGIONS: dict[str, list[str]] = {
    "Ahmedabad": ["Ahmedabad", "Amdavad", "Shela", "Bopal", "Gota", "Sanand", "SG Highway", "S.G. Highway", "Vastrapur", "Thaltej", "Bodakdev", "Prahlad Nagar",
                  "Satellite", "Vasna", "Naroda", "Bapunagar", "Chandkheda", "Motera", "Sola", "Science City", "Changodar", "Gandhinagar", "GIFT City", "Gift City",
                  "Kalol", "Kadi", "Bavla", "Dholera", "Sabarmati", "Maninagar", "Odhav", "Vatva", "Narol", "Ambli", "Shilaj", "Sargasan", "Koba", "Adalaj"],
    "Saurashtra": ["Rajkot", "Jamnagar", "Bhavnagar", "Junagadh", "Porbandar", "Morbi", "Dwarka", "Gondal", "Amreli", "Surendranagar", "Reliance Jamnagar", "Emerald"],
    "Kutch": ["Bhuj", "Gandhidham", "Mundra", "Kandla", "Anjar", "Kutch"],
    "North Gujarat": ["Mehsana", "Palanpur", "Patan", "Himmatnagar", "Vithlapur", "Becharaji", "Unjha", "Visnagar", "Modasa"],
    "Central Gujarat": ["Vadodara", "Baroda", "Anand", "Nadiad", "Halol", "Kevadia", "Ekta Nagar", "Godhra", "Dahod", "Kheda", "Savli"],
    "South Gujarat": ["Surat", "Vapi", "Valsad", "Navsari", "Bharuch", "Ankleshwar", "Dahej", "Silvassa", "Daman", "Hazira"],
    "Mumbai": ["Mumbai", "Navi Mumbai", "Thane", "Karjat", "Panvel", "Lonavala", "Andheri", "Powai", "Worli"],
    "Rest of Maharashtra": ["Pune", "Nashik", "Aurangabad", "Jalna", "Nagpur"],
    "Rajasthan": ["Udaipur", "Jaipur", "Jodhpur", "Kota", "Ajmer"],
    "North India": ["Delhi", "New Delhi", "Gurgaon", "Gurugram", "Noida", "Faridabad", "Chandigarh", "Lucknow"],
    "Outside India": ["Abu Dhabi", "Dubai", "KSA", "Riyadh", "Saudi", "Oman", "Muscat", "Qatar", "Doha", "Sharjah"],
}  # fmt: skip


def _num(s: str) -> Decimal | None:
    s = s.strip().lower()
    if s in WORDS_N:
        return Decimal(WORDS_N[s])
    try:
        return Decimal(s)
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Requirements:
    area_type: str | None = None
    surface: str | None = None
    coats: int | None = None
    min_kg_sqm: Decimal | None = None
    dft_mm: Decimal | None = None
    thickness_mm: Decimal | None = None
    protection: str | None = None
    warranty_years: int | None = None
    brands: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


def requirements(*texts: str | None) -> Requirements:
    """Read what the client asks from the description, the parent item, the remarks and the make."""
    t = " ".join(x for x in texts if x)
    low = t.lower()
    r = Requirements()
    for key, _label, pat in AREA_TYPES:
        if re.search(pat, low, re.I):
            r.area_type = key
            break
    # what goes on top (a protection screed, tiles over it) is not the surface treated
    bare = re.sub(
        r"protect\w*\s*(screed|plaster|layer)|screed\s*(over|on\s*top)|(tiles?|tiling)\s*(over|on\s*top)",
        " ",
        low,
    )
    for key, pat in SURFACES:
        if re.search(pat, bare, re.I):
            r.surface = key
            break
    m = re.search(
        r"\b(\d|one|single|two|double|three|four)\s*(\(\w+\)\s*)?(nos\.?\s*)?(of\s*)?coats?\b", low
    )
    if m:
        n = _num(m.group(1))
        r.coats = int(n) if n is not None else None
    m = re.search(
        r"(?:min(?:imum)?\.?\s*(?:of\s*)?)?(\d+(?:\.\d+)?)\s*(?:kg|kgs)\s*(?:/|per)\s*(?:sq\.?\s*m(?:tr|t)?|sqm|m2|m²|sq\.?\s*meter)",
        low,
    )
    if m:
        r.min_kg_sqm = Decimal(m.group(1))
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(mm|micron|microns|µm|μ)\s*(?:thick\w*\s*)?\(?\s*d\.?\s*f\.?\s*t", low
    ) or re.search(
        r"d\.?\s*f\.?\s*t\.?\s*(?:of\s*)?(?:min(?:imum)?\.?\s*)?(\d+(?:\.\d+)?)\s*(mm|micron|microns|µm|μ)",
        low,
    )
    if m:
        v = Decimal(m.group(1))
        r.dft_mm = v / 1000 if m.group(2).startswith(("mic", "µ", "μ")) else v
    m = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*(?:thick|thk|thickness)", low) or re.search(
        r"(?:thickness|thk)\.?\s*(?:of\s*)?(?:min(?:imum)?\.?\s*)?(\d+(?:\.\d+)?)\s*mm", low
    )
    if m:
        r.thickness_mm = Decimal(m.group(1))
    if re.search(r"protection\s*screed|protective\s*screed|screed\s*(over|on\s*top)", low):
        r.protection = "screed"
    elif re.search(r"protection\s*(board|layer)|geo\s*textile|geotextile", low):
        r.protection = "board"
    elif re.search(r"\btil(e|es|ing)\s*(over|on\s*top|finish)|china\s*mosaic|ipt\s*tile", low):
        r.protection = "tile"
    m = re.search(
        r"(\d+)\s*(?:years?|yrs?)\.?\s*(?:of\s*)?(?:warranty|guarantee)|(?:warranty|guarantee)\s*(?:of|for|period)?\s*(\d+)\s*(?:years?|yrs?)",
        low,
    )
    if m:
        r.warranty_years = int(m.group(1) or m.group(2))
    r.brands = [b for b, pat in BRANDS if re.search(pat, low, re.I)]
    r.families = [f for f, pat in FAMILIES if re.search(pat, low, re.I)]
    return r


# --- place and date --------------------------------------------------------------------------------


def city_index(regions: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    """(pattern, city, region), longest names first (Navi Mumbai before Mumbai)."""
    out = []
    for region, cities in regions.items():
        for c in cities:
            out.append(
                (
                    r"(?<![a-z])" + re.escape(c.lower()).replace(r"\ ", r"[\s._-]*") + r"(?![a-z])",
                    c,
                    region,
                )
            )
    return sorted(out, key=lambda x: -len(x[1]))


def place(
    texts: list[str], regions: dict[str, list[str]]
) -> tuple[str | None, str | None, str | None]:
    """(city, region, where it was found) from the texts in order (folder and file name first)."""
    idx = city_index(regions)
    for label, text in texts:
        low = (text or "").lower()
        for pat, city, region in idx:
            if re.search(pat, low):
                return city, region, label
    return None, None, None


DATE_PATTERNS = [
    (r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)", "dmy"),
    (r"(?<!\d)(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?!\d)", "ymd"),
    (r"(?<!\d)(2[0-9])(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)", "yymmdd"),  # 250301
    (r"(?<!\d)([0-2]\d|3[01])(0[1-9]|1[0-2])(2\d)(?!\d)", "ddmmyy"),  # 270324
    (r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](2\d)(?!\d)", "dmy2"),
]


def find_date(text: str | None) -> date | None:
    for pat, kind in DATE_PATTERNS:
        for m in re.finditer(pat, text or ""):
            a, b, c = m.groups()
            try:
                if kind == "dmy":
                    d = date(int(c), int(b), int(a))
                elif kind == "ymd":
                    d = date(int(a), int(b), int(c))
                elif kind == "yymmdd":
                    d = date(2000 + int(a), int(b), int(c))
                else:
                    d = date(2000 + int(c), int(b), int(a))
            except ValueError:
                continue
            if date(2015, 1, 1) <= d <= ist_today():  # 270324 is 27-03-24, not 2027
                return d
    return None


def file_date(
    name: str, folders: str, cells: list[str], saved: datetime | None
) -> tuple[date | None, str | None]:
    """The file name, the folders, a date written on the sheet, else the workbook's saved date
    (never the file's timestamp: the copies came out of one zip on one day)."""
    for text, source in ((name, "file name"), (folders, "folder name")):
        d = find_date(text)
        if d:
            return d, source
    for c in cells:
        if re.search(r"date|dt\.", c or "", re.I):
            d = find_date(c)
            if d:
                return d, "written on the sheet"
    if saved and date(2015, 1, 1) <= saved.date() <= date(2027, 12, 31):
        return saved.date(), "the workbook's saved date"
    return None, None
