# ruff: noqa: E501  (the patterns read better unwrapped)
"""Reading a product data sheet (TDS): its text per page and the facts in it, each with the page
and the sentence it came from. A data sheet is mostly a table, so a label and its value are often
on two lines: each line is read together with the next one (a fact is kept where it starts).

Facts: chemistry, use, consumption (per sqm or per rmt; the sheet's own words kept), coats,
DFT / thickness, pack, density, solids, primer required, UV / exposed, potable, and property values
(elongation, tensile, adhesion, Shore A, crack bridging, vapour permeability) with their standard.
Nothing is guessed: a figure the text does not give is not a fact."""

import io
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from app.spec import vocab
from app.spec.vocab import KGCM2_TO_NMM2, SQFT_PER_SQM, D, dec

MIN_TEXT = 80  # fewer characters than this in the whole PDF: a scanned page, "needs reading"

_N = r"(\d+(?:[.,]\d+)?)"
_RANGE = rf"{_N}(?:\s*(?:-|–|—|to|~)\s*{_N})?"
_AMT = r"(kgs?|kilo\s*grams?|ltrs?|litres?|liters?|lt|l|gms?|grams?|g|ml)"
_SQM = r"(?:sq\.?\s*m(?:tr|eter|etre)?s?\.?|sqm|m2|m²|square\s*met(?:er|re)s?)"
_SQFT = r"(?:sq\.?\s*ft\.?|sqft|sft|ft2|ft²|square\s*f(?:ee|oo)t)"
_AREA = rf"({_SQM}|{_SQFT})"
_RUN = r"(rmt|r\.?m\.?|running\s*met(?:er|re)s?|rm\b|lm\b|linear\s*met(?:er|re)s?|meters?\b|metres?\b|m\b)"
_PER = r"\s*(?:/|per|for\s*(?:every\s*)?(?:one\s*|1\s*)?)\s*"

PER_AREA = re.compile(rf"{_RANGE}\s*{_AMT}\.?{_PER}(?:1\s*)?{_AREA}", re.I)
COVERAGE = re.compile(rf"{_RANGE}\s*{_AREA}{_PER}(?:1\s*)?{_AMT}\b", re.I)
PER_MM = re.compile(
    rf"{_RANGE}\s*{_AMT}\s*(?:/|per)\s*(?:mm\s*(?:/|per)\s*{_AREA}|{_AREA}\s*(?:/|per)\s*mm)", re.I
)
PER_RUN = re.compile(rf"{_RANGE}\s*{_AMT}{_PER}(?:1\s*)?{_RUN}", re.I)
RUN_PER = re.compile(rf"{_RANGE}\s*{_RUN}{_PER}(?:1\s*)?{_AMT}\b", re.I)
PACK_COVER = re.compile(
    rf"(?:coverage|covers?)\s*(?:per|/)\s*(?:pack|kit|set|bag|drum|pail)[^0-9\n]{{0,25}}?(?:@\s*\d+(?:\.\d+)?\s*mm\s*\*?\s*)?{_RANGE}\s*{_AREA}",
    re.I,
)
COATS = re.compile(r"\b(one|single|two|double|three|four|1|2|3|4)\s*(?:\(\w+\)\s*)?coats?\b", re.I)
DFT = re.compile(
    rf"{_RANGE}\s*(mm|microns?|µm|μm|mic)\s*(?:thick\w*\s*)?\(?\s*(?:dft|d\.f\.t|dry\s*film)|(?:dft|d\.f\.t\.?|dry\s*film\s*thickness)[^0-9\n]{{0,20}}{_RANGE}\s*(mm|microns?|µm|μm|mic)",
    re.I,
)
THICK = re.compile(rf"thickness[^0-9\n]{{0,25}}{_RANGE}\s*(mm|microns?|µm|μm)", re.I)
PACK = re.compile(
    rf"{_N}\s*(kgs?|ltrs?|litres?|liters?|l|lt)\b\.?\s*(?:pack|pail|bucket|drum|bag|can|kit|set|tin|carton|container|jar|unit)s?",
    re.I,
)
PACK_LINE = re.compile(r"pack(ag|ing)|supplied\s*in|available\s*in|pack\s*size", re.I)
DENSITY = re.compile(
    rf"(?:density|specific\s*gravity|sp\.?\s*gr)\w*\s*[,(:]?\s*(kg/m3|kg/m³|g/cc|g/cm3|kg/l)?\)?[^0-9\n]{{0,35}}{_N}\s*(?:±\s*[\d.]+\s*)?(g/cc|g/cm3|g/cm³|gm/cc|gm/ml|g/ml|kg/l|kg/ltr|kg/lit|kg/m3|kg/m³)?",
    re.I,
)
SOLIDS = re.compile(rf"solids?\s*(?:content|by\s*(?:volume|weight))?[^0-9\n]{{0,25}}{_N}\s*%", re.I)
PRIMER = re.compile(
    r"(apply|use)\w*\s*(a\s*|the\s*)?(coat\s*of\s*)?[\w®\s-]{0,30}primer|primer\s*(is\s*)?(required|recommended|must)|prime\s*the\s*surface|primed\s*with",
    re.I,
)
UV_YES = re.compile(
    r"uv\s*-?\s*(resistant|stable|resistance|stability)|can\s*be\s*left\s*exposed|exposed\s*(roof|terrace|condition|applications?|areas?)|resistant\s*to\s*uv",
    re.I,
)
UV_NO = re.compile(
    r"not\s*(be\s*)?(uv|suitable\s*for\s*exposed|resistant\s*to\s*uv)|non\s*-?\s*exposed|(must|should|to)\s*be\s*protected|requires?\s*(a\s*)?protection|not\s*for\s*exposed|without\s*uv",
    re.I,
)
POTABLE = re.compile(
    r"potable|drinking\s*water|nsf\s*/?\s*(ansi\s*)?61|wras|bs\s*6920|is\s*10500", re.I
)
NOT_TDS = re.compile(r"^(msds|sds)\b|safety\s*data", re.I)
# what comes after a property's name but is not its value: a test age, a temperature, a thickness
NOISE = re.compile(
    r"@?\s*\d+(?:\.\d+)?\s*(?:days?|d\b|hrs?|hours?|°\s*c|deg\w*|mm\b|micron\w*)|\(\s*\d+\s*(?:days?|d)\s*\)|@\s*\d+\s*%",
    re.I,
)
# unit words between a property and its value ("N/mm2" is not the value 2)
UNITS = re.compile(
    r"(?:k?n|kg)\s*/\s*(?:mm|cm|m)\s*[2²]?|mpa|kpa|n\s*/\s*(?:5\s*cm|50\s*mm)|g(?:ms?)?\s*/\s*m\s*[2²]|m\s*[2²]",
    re.I,
)
COMPARATOR = r"(>=|≥|>|min(?:imum)?\.?|more\s*than|above|<=|≤|<|max(?:imum)?\.?)?"
VALUE = re.compile(
    rf"{COMPARATOR}\s*:?\s*(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:[.,]\d+)?))?", re.I
)
# a value before the property's name needs a comparator and the property's own unit
BEFORE = {
    "elongation": r"(?:>|≥|min\.?|minimum)\s*(\d+(?:\.\d+)?)\s*%\s*$",
    "tensile": r"(?:>|≥|min\.?|minimum)\s*(\d+(?:\.\d+)?)\s*(?:n\s*/\s*mm\s*[2²]|mpa)\s*$",
    "adhesion": r"(?:>|≥|min\.?|minimum)\s*(\d+(?:\.\d+)?)\s*(?:n\s*/\s*mm\s*[2²]|mpa)\s*$",
    "crack_bridging": r"(?:>|≥|min\.?|minimum)\s*(\d+(?:\.\d+)?)\s*mm\s*$",
}
PLAUSIBLE = {
    "elongation": D(2000),
    "tensile": D(100),
    "adhesion": D(100),
    "shore_a": D(100),
    "crack_bridging": D(50),
}
WORD_N = {"one": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4}


@dataclass
class Fact:
    kind: str  # chemistry, use, consumption, coats, dft, thickness, pack, density, solids, primer, uv, potable, property
    key: str | None = None  # the chemistry or use key, the property, the consumption's unit
    lo: Decimal | None = None
    hi: Decimal | None = None
    unit: str | None = None
    text: str = ""  # the value as read ("1.5 - 2 kg per sq. m")
    standard: str | None = None
    page: int | None = None
    sentence: str = ""
    per_coat: bool = False
    coats: int | None = None

    def out(self) -> dict:
        d = asdict(self)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


@dataclass
class Sheet:
    pages: list[str] = field(default_factory=list)
    title: str | None = None
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    @property
    def scanned(self) -> bool:
        return not self.error and len(re.sub(r"\s", "", self.text)) < MIN_TEXT


def clean(text: str) -> str:
    """Text as a PDF gives it, fit to keep: the "fi" ligature some sheets give as a NUL byte
    ("waterproo<NUL>ng") is "fi" again, any other NUL is dropped, and the "\u0178" bullet glyph is a
    space."""
    text = re.sub(r"(?<=[A-Za-z])\x00(?=[A-Za-z])", "fi", text)
    return text.replace("\x00", "").replace("\u0178", " ")


def read_pdf(data: bytes) -> Sheet:
    """The text of each page (pypdf); a broken file is a Sheet with its error."""
    from pypdf import PdfReader  # noqa: PLC0415

    try:
        r = PdfReader(io.BytesIO(data))
        pages = [clean(p.extract_text() or "") for p in r.pages]
        title = None
        try:
            title = (r.metadata or {}).get("/Title")
        except Exception:  # noqa: BLE001
            title = None
        return Sheet(pages=pages, title=str(title) if title else None)
    except Exception as exc:  # noqa: BLE001
        return Sheet(error=f"The PDF could not be read ({type(exc).__name__})")


# --- the product's name and brand ----------------------------------------------------------------

_CODE = re.compile(r"^[\d,\s]+\s*[-–_]\s*|^\d{3,}\s+")
_SHEET_WORD = re.compile(
    r"\b(tds|pds|mtc|msds|sds|technical\s*data\s*sheet|product\s*data\s*sheet|data\s*sheet|datasheet|final|latest|new|updated|edited|rev\.?\s*\d+|r\d+|v\d+|india\d*|en|copy)\b",
    re.I,
)
CONTAINER = re.compile(
    r"technical\s*data|product\s*tds|^tds$|onedrive|^final$|^latest|^old|^edited|^new\s*folder",
    re.I,
)


def product_name(file_name: str, brand: str | None = None) -> str:
    """ "TDS_BRONCO HYDROSWELL (1).pdf" -> "BRONCO HYDROSWELL"; "0009 - 3 Mangoes Paint" -> "3 Mangoes Paint"."""
    stem = Path(file_name).stem
    s = re.sub(r"\(\s*\d+\s*\)", " ", stem)
    s = s.replace("_", " ")
    if "-" in s and " " not in s.strip():  # pds-sikatherm-foam-755spf
        s = s.replace("-", " ")
    s = _CODE.sub("", s.strip())
    s = _SHEET_WORD.sub(" ", s)
    s = re.sub(r"[«»®™]", " ", s)
    s = re.sub(r"\s*[-–,]\s*$|^\s*[-–,]\s*", "", " ".join(s.split()))
    s = " ".join(s.split()).strip(" -–,.")
    if s.islower():
        s = s.title()
    return s or stem


def brand_of(rel_path: str) -> str | None:
    """The brand is the folder: the first one under the containers ("Technical Data Sheet
    (Product TDS)/Bronco/..." -> "Bronco"); "Other_TDS" has none (read from the text)."""
    parts = [p for p in Path(rel_path).parts[:-1] if not CONTAINER.search(p)]
    if not parts:
        return None
    b = parts[0].strip()
    return None if re.match(r"other", b, re.I) else b


# --- the facts -----------------------------------------------------------------------------------


def _lines(sheet: Sheet) -> list[tuple[int, str, str]]:
    """(page, the line, the line and the next one)."""
    out = []
    for pno, page in enumerate(sheet.pages, start=1):
        rows = [" ".join(x.split()) for x in page.splitlines()]
        rows = [x for x in rows if x]
        for i, row in enumerate(rows):
            nxt = rows[i + 1] if i + 1 < len(rows) else ""
            out.append((pno, row, f"{row} {nxt}".strip()))
    return out


def _amount(v: Decimal, unit: str) -> tuple[Decimal, str]:
    """grams -> kg, ml -> L."""
    u = unit.lower().replace(" ", "")
    if u in ("g", "gm", "gms", "gram", "grams"):
        return v / 1000, "kg"
    if u == "ml":
        return v / 1000, "L"
    return v, ("kg" if u.startswith("k") else "L")


def _is_sqft(area: str) -> bool:
    return bool(re.match(_SQFT, area, re.I))


def _rng(a, b) -> tuple[Decimal, Decimal]:
    lo, hi = dec(a), dec(b) if b else None
    hi = hi if hi is not None else lo
    return (lo, hi) if lo <= hi else (hi, lo)


def consumption(window: str) -> list[Fact]:
    """Every consumption in a sentence, per sqm (or per rmt, or per sqm per mm). "coverage 23 to
    25 sft/kg" -> 0.43-0.47 kg/sqm; "80-100 gram per sqm" -> 0.08-0.1 kg/sqm."""
    out: list[Fact] = []
    taken: list[tuple[int, int]] = []

    def free(m) -> bool:
        return not any(m.start() < e and s < m.end() for s, e in taken)

    def add(m, f: Fact) -> None:
        taken.append((m.start(), m.end()))
        f.text = m.group(0).strip()
        out.append(f)

    for m in PER_MM.finditer(window):
        lo, hi = _rng(m.group(1), m.group(2))
        v_lo, u = _amount(lo, m.group(3))
        v_hi, _ = _amount(hi, m.group(3))
        area = m.group(4) or m.group(5)
        f = SQFT_PER_SQM if _is_sqft(area) else D(1)
        add(
            m,
            Fact(
                "consumption", key=f"{u}/sqm/mm", lo=v_lo * f, hi=v_hi * f, unit=f"{u}/sqm per mm"
            ),
        )
    for m in PER_AREA.finditer(window):
        if not free(m):
            continue
        lo, hi = _rng(m.group(1), m.group(2))
        v_lo, u = _amount(lo, m.group(3))
        v_hi, _ = _amount(hi, m.group(3))
        f = SQFT_PER_SQM if _is_sqft(m.group(4)) else D(1)
        add(m, Fact("consumption", key=f"{u}/sqm", lo=v_lo * f, hi=v_hi * f, unit=f"{u}/sqm"))
    for m in COVERAGE.finditer(window):
        if not free(m):
            continue
        lo, hi = _rng(m.group(1), m.group(2))
        if not lo or not hi:
            continue
        one, u = _amount(D(1), m.group(4))
        area_f = SQFT_PER_SQM if _is_sqft(m.group(3)) else D(1)
        # cover in sqm per one unit of material: its inverse is the material per sqm (the
        # largest coverage gives the least material)
        add(
            m,
            Fact(
                "consumption",
                key=f"{u}/sqm",
                lo=area_f * one / hi,
                hi=area_f * one / lo,
                unit=f"{u}/sqm",
            ),
        )
    for m in PER_RUN.finditer(window):
        if not free(m):
            continue
        lo, hi = _rng(m.group(1), m.group(2))
        v_lo, u = _amount(lo, m.group(3))
        v_hi, _ = _amount(hi, m.group(3))
        add(m, Fact("consumption", key=f"{u}/rmt", lo=v_lo, hi=v_hi, unit=f"{u}/rmt"))
    for m in RUN_PER.finditer(window):
        if not free(m):
            continue
        lo, hi = _rng(m.group(1), m.group(2))
        if not lo or not hi:
            continue
        one, u = _amount(D(1), m.group(4))
        add(m, Fact("consumption", key=f"{u}/rmt", lo=one / hi, hi=one / lo, unit=f"{u}/rmt"))
    for m in PACK_COVER.finditer(window):
        if not free(m):
            continue
        lo, hi = _rng(m.group(1), m.group(2))
        f = D(1) / SQFT_PER_SQM if _is_sqft(m.group(3)) else D(1)
        add(m, Fact("consumption", key="sqm/pack", lo=lo * f, hi=hi * f, unit="sqm per pack"))
    low = window.lower()
    c = COATS.search(window)
    for f in out:
        f.per_coat = bool(re.search(r"per\s*coat|each\s*coat|/\s*coat", low))
        if c:
            w = c.group(1).lower()
            f.coats = WORD_N.get(w) or int(w)
    return out


def properties(window: str) -> list[Fact]:
    """The property values of a sentence: "Elongation at break > 400 % as per ASTM D-412"."""
    out = []
    hits = []
    for key, _label, _unit, pat in vocab.PROPERTIES:
        for m in re.finditer(pat, window, re.I):
            hits.append((m.start(), m.end(), key))
    hits.sort()
    seen = set()
    for i, (s, e, key) in enumerate(hits):
        if key in seen:
            continue
        end = hits[i + 1][0] if i + 1 < len(hits) else len(window)
        seg = window[e:end]
        if key == "tensile" and re.match(r"\s*adhesion", seg, re.I):
            continue
        before = BEFORE.get(key)
        prev_end = hits[i - 1][1] if i else 0
        b = re.search(before, window[max(prev_end, s - 30) : s], re.I) if before else None
        if b and not re.match(r"\s*[:=]?\s*(?:>|≥|min|\d)", seg, re.I):
            # "> 200 % Elongation": the value comes first (a comparator and the property's unit)
            v = dec(b.group(1))
            if v is not None and v <= PLAUSIBLE.get(key, D(10**6)):
                seen.add(key)
                out.append(Fact("property", key=key, lo=v, unit=vocab.PROPERTY_UNIT[key], standard=vocab.standard_of(seg[:60]),
                                text=window[max(prev_end, s - 30) : min(end, s + 60)].strip()))  # fmt: skip
                continue
        standard = vocab.standard_of(seg)
        bare = vocab.STANDARD.sub(" ", seg)
        bare = NOISE.sub(" ", bare)
        hint = re.search(r"kpa|kg\s*/\s*cm|n\s*/\s*(?:5\s*cm|50\s*mm)", bare[:80], re.I)
        bare = UNITS.sub(" ", bare)
        m = VALUE.search(bare)
        if not m or m.start() > 60:
            continue
        lo = dec(m.group(2))
        hi = dec(m.group(3)) if m.group(3) else None
        unit = vocab.PROPERTY_UNIT[key]
        h = hint.group(0).lower().replace(" ", "") if hint else ""
        if key in ("tensile", "adhesion"):
            if h == "kpa":
                lo = lo / 1000
                hi = hi / 1000 if hi is not None else None
            elif h.startswith("kg"):
                lo = lo * KGCM2_TO_NMM2
                hi = hi * KGCM2_TO_NMM2 if hi is not None else None
            elif h.startswith("n"):
                unit = "N/5 cm"  # a sheet's strength per width: not comparable with N/mm²
        if lo is None or lo > PLAUSIBLE.get(key, D(10**6)):
            continue  # a year, a code or a test count read as the value
        seen.add(key)
        out.append(Fact("property", key=key, lo=lo, hi=hi, unit=unit, standard=standard,
                        text=window[s:min(end, s + 120)].strip()))  # fmt: skip
    return out


def facts(sheet: Sheet, name: str) -> list[Fact]:
    """Every fact the text gives, each once (the first place it is said)."""
    out: list[Fact] = []
    text = sheet.text
    head = text[:1500]
    # chemistry: the product's own name first, then what the top of the sheet says it is
    chem = [t for t in vocab.types_in(name)]
    lead = vocab.main_type(head)
    for t in chem + ([lead] if lead and lead not in chem else []):
        out.append(
            Fact(
                "chemistry",
                key=t,
                text=vocab.TYPE_LABEL[t],
                sentence=name if t in chem else _sentence(head, vocab.TYPES, t),
                page=1,
            )
        )
    counts: dict[str, int] = {}
    for key, pat in vocab.USES:
        counts[key] = len(re.findall(pat, text, re.I))
    for key, n in counts.items():
        if n and (key != "pipe_outlet" or n >= 2) and (key != "crack" or n >= 2):
            m = re.search(dict(vocab.USES)[key], text, re.I)
            out.append(
                Fact(
                    "use",
                    key=key,
                    text=vocab.USE_LABEL.get(key, key),
                    sentence=_around(text, m.start()),
                    page=_page(sheet, m.start()),
                )
            )
    done: set[tuple] = set()
    for pno, row, window in _lines(sheet):
        for f in consumption(window):
            sig = ("consumption", f.key, f.lo, f.hi)
            if sig in done or not row_has(row, f.text):
                continue
            done.add(sig)
            f.page, f.sentence = pno, window[:300]
            out.append(f)
        for f in properties(window):
            if ("property", f.key) in done or not re.search(
                dict((k, p) for k, _l, _u, p in vocab.PROPERTIES)[f.key], row, re.I
            ):
                continue
            done.add(("property", f.key))
            f.page, f.sentence = pno, window[:300]
            out.append(f)
        single = [
            ("coats", COATS), ("dft", DFT), ("thickness", THICK), ("density", DENSITY), ("solids", SOLIDS),
        ]  # fmt: skip
        for kind, pat in single:
            if kind in done:
                continue
            m = pat.search(row)
            if not m:
                continue
            f = _single(kind, m)
            if f is None:
                continue
            done.add(kind)
            f.page, f.sentence = pno, window[:300]
            out.append(f)
        if PACK_LINE.search(row) or PACK.search(row):
            for m in (
                PACK.finditer(window)
                if PACK.search(window)
                else re.finditer(rf"{_N}\s*(kgs?|ltrs?|litres?|liters?|lt|l)\b", window, re.I)
            ):
                v, u = _amount(dec(m.group(1)), m.group(2))
                sig = ("pack", v, u)
                if sig in done or not v or v > 1000:
                    continue
                done.add(sig)
                out.append(
                    Fact(
                        "pack",
                        key=u,
                        lo=v,
                        hi=v,
                        unit=u,
                        text=m.group(0).strip(),
                        page=pno,
                        sentence=window[:300],
                    )
                )
        for kind, pat, value in (
            ("primer", PRIMER, None),
            ("uv", UV_NO, "no"),
            ("uv", UV_YES, "yes"),
            ("potable", POTABLE, "yes"),
        ):
            if kind in done:
                continue
            m = pat.search(row)
            if m and not (kind == "primer" and "primer" in chem):
                done.add(kind)
                out.append(
                    Fact(
                        kind,
                        key=value or "yes",
                        text=m.group(0).strip(),
                        page=pno,
                        sentence=window[:300],
                    )
                )
    return out


def row_has(row: str, matched: str) -> bool:
    """The match starts on this row (not only on the next one, where it is read again)."""
    head = matched.split()[0] if matched.split() else matched
    return head in row


def _single(kind: str, m) -> Fact | None:
    g = m.groups()
    if kind == "coats":
        w = g[0].lower()
        return Fact(
            "coats", lo=D(WORD_N.get(w) or int(w)), hi=D(WORD_N.get(w) or int(w)), text=m.group(0)
        )
    if kind in ("dft", "thickness"):
        if kind == "dft":
            a, b, u = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
        else:
            a, b, u = g[0], g[1], g[2]
        lo, hi = _rng(a, b)
        if u.lower().startswith(("mic", "µ", "μ")):
            lo, hi = lo / 1000, hi / 1000
        return Fact(kind, lo=lo, hi=hi, unit="mm", text=m.group(0))
    if kind == "density":
        v = dec(g[1])
        unit = (g[2] or g[0] or "").lower()
        if v is None:
            return None
        if "m3" in unit or "m³" in unit:
            v = v / 1000
        if not (D("0.5") <= v <= D("3.5")):
            return None
        return Fact("density", lo=v, hi=v, unit="kg/L", text=m.group(0))
    if kind == "solids":
        v = dec(g[0])
        return (
            Fact("solids", lo=v, hi=v, unit="%", text=m.group(0)) if v and 5 <= v <= 100 else None
        )
    return None


def _around(text: str, pos: int) -> str:
    s = max(0, text.rfind("\n", 0, pos))
    e = text.find("\n", pos)
    e = e if e > 0 else len(text)
    return " ".join(text[s:e].split())[:300]


def _sentence(text: str, table, key) -> str:
    pat = next(p for k, _l, p in table if k == key)
    m = re.search(pat, text, re.I)
    return _around(text, m.start()) if m else ""


def _page(sheet: Sheet, pos: int) -> int:
    n = 0
    for i, p in enumerate(sheet.pages, start=1):
        n += len(p) + 1
        if pos < n:
            return i
    return 1


def kg_per_sqm_for_dft(dft_mm: Decimal, fs: list[dict]) -> tuple[Decimal | None, str]:
    """A DFT asked for, as kg per sqm from the sheet: its kg/sqm per mm, a consumption given for a
    DFT, or its density and solids. (None, why) when the sheet gives none of them."""
    for f in fs:
        if f["kind"] == "consumption" and f.get("key") == "kg/sqm/mm" and f.get("lo"):
            return D(f["lo"]) * dft_mm, f"{D(f['lo']).normalize():f} kg/sqm per mm (TDS)"
    density = next((D(f["lo"]) for f in fs if f["kind"] == "density" and f.get("lo")), None)
    solids = next((D(f["lo"]) for f in fs if f["kind"] == "solids" and f.get("lo")), None)
    if density:
        kg = dft_mm * density / ((solids / 100) if solids else 1)
        how = f"density {density.normalize():f}" + (
            f", solids {solids.normalize():f} %" if solids else ""
        )
        return kg, how + " (TDS)"
    dft = next((f for f in fs if f["kind"] == "dft" and f.get("lo")), None)
    per = next(
        (f for f in fs if f["kind"] == "consumption" and f.get("key") == "kg/sqm" and f.get("lo")),
        None,
    )
    if dft and per and D(dft["hi"] or dft["lo"]) > 0:
        rate = D(per["lo"]) / D(dft["hi"] or dft["lo"])
        return (
            rate * dft_mm,
            f"{D(per['lo']).normalize():f} kg/sqm for {D(dft['hi'] or dft['lo']).normalize():f} mm DFT (TDS)",
        )
    return None, "the TDS gives no density, solids or kg per mm: DFT not converted"
