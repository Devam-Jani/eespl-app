# ruff: noqa: E501  (HTML, patterns and offer wording read better unwrapped)
"""Import a hand-made techno-commercial offer (.docx) into the quotation libraries, once:

    python -m app.cli import-offer data/samples/offer-ladani.docx

Reads the document in order: the cover letter (-> a letter template with {placeholders}, the
letterhead with its logo and signatory), the technical specification items (-> spec blocks with
stage sections and numbered steps, images with captions), the budgetary offer tables (-> offer
lines with UoM and rate, Opt.1 / Opt.2 rows, "if required", "client's scope"), the general terms
(-> T&C clauses in their groups and a T&C template for the letterhead) and "Our esteemed
clients" (-> references). Every row is marked "imported, check". Known typos are fixed and
listed.
"""

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.masters.models import TcClause, TcTemplate, TcTemplateClause
from app.quotations import library as lib
from app.quotations.markup import normalize, plain
from app.quotations.models import (
    STAGES,
    Letterhead,
    LetterTemplate,
    LibraryVersion,
    OfferItem,
    OfferItemLine,
    OfferItemSpec,
    OfferLine,
    OfferPreset,
    Reference,
    SpecBlock,
)
from app.survey.models import AreaType

W_P, W_TBL = qn("w:p"), qn("w:tbl")
ACRONYMS = {
    "HDPE",
    "PU",
    "RCC",
    "PCC",
    "BRONCO",
    "GSM",
    "PVC",
    "EBA",
    "PMC",
    "OH",
    "UG",
    "CTE",
    "HB",
    "NSPG",
}
UOM_MAP = {
    "SQMT": "sqm",
    "SQM": "sqm",
    "SQFT": "sqft",
    "RFT": "rft",
    "RMT": "rmt",
    "NOS": "nos",
    "NO": "nos",
    "KG": "kg",
    "LTR": "ltr",
    "LS": "ls",
}
# (wrong, right, applies to: None = everywhere, else item numbers)
TYPOS: list[tuple[str, str, tuple[int, ...] | None]] = [
    ("METHEDOLOGY", "METHODOLOGY", None),
    ("HORIZINTAL", "HORIZONTAL", None),
    (" on on ", " on ", None),
    ("Al low", "Allow", None),
    ("CEMSHEILD", "CEMSHIELD", None),
    ("loos particles", "loose particles", None),
    ("Tie rode hole", "Tie rod hole", None),
    ("filing the same", "filling the same", None),
    ("west water", "waste water", None),
]
# whole words / patterns (label, pattern, replacement)
REGEX_TYPOS: list[tuple[str, str, str]] = [
    ("lying -> laying", r"\blying\b", "laying"),
    ("temping -> tamping", r"\btemping\b", "tamping"),
    ("@ @ -> @", r"@(\s*(?:\*\*|==)?\s*)@", r"\1@"),
]
ROOF_FIX_WORDS = ("tank", "wall", "pool", "sunken")  # "over the Roof" there: "over the surface"
# the system an item uses, from the products in its specification (first match wins); items of
# an area type that already has an item are named "<area> - <system>"
SYSTEM_LABELS = [
    ("SBS", "SBS self-adhesive membrane"),
    ("HDPE", "HDPE membrane"),
    ("CTE", "coal tar epoxy"),
    ("HYBRID PU", "hybrid PU coating"),
    ("ULTRASHIELD PU", "PU coating"),
    ("CEMCRYSTAL", "crystalline + elastomeric coating"),
    ("CEMGUARD PLUS", "elastomeric coating"),
    ("CEMGUARD", "cementitious coating"),
]
AREA_KEYWORDS = [
    ("raft", "Raft"),
    ("retaining", "Basement retaining wall"),
    ("garden", "Podium / planter"),
    ("planter", "Podium / planter"),
    ("pool", "Swimming pool"),
    ("terrace", "Terrace"),
    ("sunken", "Sunken slab"),
]
M = r"(?:\*\*|==)*"  # markup markers that may sit around or inside the brackets
CLIENT_SCOPE = re.compile(
    r"[ \t]*"
    + M
    + r"[ \t]*\([ \t]*"
    + M
    + r"[ \t]*Client[’'`]?s?[ \t]+scope[ \t]*"
    + M
    + r"[ \t]*\)[ \t]*"
    + M
    + r"(?=[ \t]*\.?[ \t]*$)",
    re.I | re.M,
)
S = r"[ \t]*"  # spaces only: a newline is a paragraph break and stays
IF_REQUIRED = re.compile(rf"{S}{M}{S}\({S}{M}{S}If required{S}\)?{S}(:?){S}{M}{S}\)?", re.I)
# the T&C groups this offer uses, as the T&C library's category codes
TC_CODES = {
    "Client's obligations": "client_scope",
    "Force majeure": "force_majeure",
    "Taxes": "taxes",
    "Validity": "validity",
    "Applicator": "applicator",
    "Terms of payment": "payment",
}


@dataclass
class Para:
    text: str  # markup
    plain: str
    numbered: bool
    num_id: str | None
    images: list[tuple[bytes, str]]
    all_bold: bool


@dataclass
class Result:
    counts: dict[str, int] = field(default_factory=dict)
    fixes: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --- reading the document ------------------------------------------------------------------------


def _markup(p: Paragraph) -> tuple[str, bool]:
    """Runs -> markup (adjacent runs with the same look merged; blank bold runs dropped)."""
    parts: list[tuple[str, bool, bool]] = []
    for r in p.runs:
        t = r.text
        if not t:
            continue
        bold = bool(r.bold)
        hl = r.font.highlight_color is not None
        if not t.strip():
            bold = hl = False  # a space never carries bold / highlight markers
        if parts and parts[-1][1] == bold and parts[-1][2] == hl:
            parts[-1] = (parts[-1][0] + t, bold, hl)
        else:
            parts.append((t, bold, hl))
    out = []
    for t, bold, hl in parts:
        lead = t[: len(t) - len(t.lstrip())]
        trail = t[len(t.rstrip()) :]
        core = t.strip()
        if hl:
            core = f"=={core}=="
        if bold:
            core = f"**{core}**"
        out.append(lead + core + trail)
    text = re.sub(r"[ \t]+", " ", "".join(out)).strip()
    letters = [(t, b) for t, b, _ in parts if t.strip()]
    return text, bool(letters) and all(b for _, b in letters)


def _images(p: Paragraph, part) -> list[tuple[bytes, str]]:
    found = []
    for blip in p._p.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if rid and rid in part.related_parts:
            img = part.related_parts[rid]
            ext = Path(img.partname).suffix.lstrip(".") or "png"
            found.append((img.blob, ext))
    return found


def read(path: Path):
    d = Document(str(path))
    items: list[Any] = []
    for el in d.element.body:
        if el.tag == W_P:
            p = Paragraph(el, d)
            text, all_bold = _markup(p)
            num = el.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
            num_id = None
            if num is not None and num.find(qn("w:numId")) is not None:
                num_id = num.find(qn("w:numId")).get(qn("w:val"))
            items.append(
                Para(text, plain(text), num is not None, num_id, _images(p, d.part), all_bold)
            )
        elif el.tag == W_TBL:
            rows = []
            for tr in el.findall(qn("w:tr")):
                cells = []
                for tc in tr.findall(qn("w:tc")):
                    paras = [_markup(Paragraph(pe, d))[0] for pe in tc.findall(qn("w:p"))]
                    cells.append([x for x in paras if plain(x)])
                rows.append(cells)
            items.append(rows)
    return items, letterhead_images(d)


VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
EMU_PER_MM = 36000


def letterhead_images(d) -> dict[str, tuple[bytes, str]]:
    """The images of the Word header and footer, by role: a VML picture behind the text is the
    watermark; a header picture at least 150 mm wide is the header band (else the logo); a footer
    picture is the footer band. Every header (first, even, default) is looked at once."""
    found: dict[str, tuple[bytes, str]] = {}
    seen: set[str] = set()
    parts = []
    for sec in d.sections:
        for hdr, kind in (
            (sec.first_page_header, "header"),
            (sec.even_page_header, "header"),
            (sec.header, "header"),
            (sec.first_page_footer, "footer"),
            (sec.even_page_footer, "footer"),
            (sec.footer, "footer"),
        ):
            if hdr.is_linked_to_previous and hdr is not sec.header and hdr is not sec.footer:
                continue
            try:
                parts.append((hdr.part, hdr._element, kind))
            except Exception:  # noqa: BLE001,S112  a missing header part is simply skipped
                continue
    for part, el, kind in parts:
        if part.partname in seen:
            continue
        seen.add(part.partname)

        def blob(rid, part=part):
            img = part.related_parts.get(rid)
            return (
                (img.blob, Path(img.partname).suffix.lstrip(".") or "png")
                if img is not None
                else None
            )

        for v in el.iter(VML_IMAGEDATA):
            b = blob(v.get(qn("r:id")))
            if b and "watermark" not in found:
                found["watermark"] = b
        for drawing in el.iter(qn("w:drawing")):
            ext = next(drawing.iter(qn("wp:extent")), None)
            blip = next(drawing.iter(qn("a:blip")), None)
            b = blob(blip.get(qn("r:embed"))) if blip is not None else None
            if not b:
                continue
            width_mm = int(ext.get("cx")) / EMU_PER_MM if ext is not None else 0
            role = "footer" if kind == "footer" else ("header" if width_mm >= 150 else "logo")
            found.setdefault(role, b)
    return found


# --- helpers -------------------------------------------------------------------------------------


def sentence(text: str) -> str:
    """ "RAFT TREATMENT WATERPROOFING USING HDPE" -> "Raft treatment waterproofing using HDPE"."""
    words = []
    for w in text.split():
        core = re.sub(r"[^A-Za-z]", "", w)
        words.append(w if core.upper() in ACRONYMS or any(c.isdigit() for c in w) else w.lower())
    s = " ".join(words)
    return s[:1].upper() + s[1:]


class Fixer:
    def __init__(self, result: Result):
        self.result = result

    def __call__(self, text: str, item_no: int | None = None, item_name: str = "") -> str:
        for wrong, right, only in TYPOS:
            if only is not None and item_no not in only:
                continue
            n = text.count(wrong)
            if n:
                text = text.replace(wrong, right)
                self.note(f"{wrong.strip()} -> {right.strip()}", n)
        for label, pattern, repl in REGEX_TYPOS:
            text, n = re.subn(pattern, repl, text)
            if n:
                self.note(label, n)
        if any(w in item_name.lower() for w in ROOF_FIX_WORDS) and "over the Roof" in text:
            n = text.count("over the Roof")
            text = text.replace("over the Roof", "over the surface")
            self.note("over the Roof -> over the surface (tanks, walls, pools, sunken)", n)
        return text

    def note(self, key: str, n: int = 1) -> None:
        self.result.fixes[key] = self.result.fixes.get(key, 0) + n


def _save_image(blob: bytes, ext: str) -> str:
    rel = f"quotations/library/{uuid.uuid4().hex}.{ext.lower()}"
    p = Path(app_settings.media_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    return rel


def _stage(heading: str) -> str:
    h = re.sub(r"[:\s]+$", "", heading).strip()
    for st in STAGES:
        if h.lower().startswith(st.lower()):
            return st if h.lower() == st.lower() else sentence(h)
    return sentence(h)


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[^\d.]", "", text)) if re.search(r"\d", text) else None
    except InvalidOperation:
        return None


def _flags(text: str) -> tuple[str, bool, bool]:
    """Take "(Client's scope)" (at the end of a step) and "(If required)" out of the text and
    return them as flags; the renderer prints them highlighted again. Markers around or inside
    the brackets go with them; what is left is re-balanced."""
    client = bool(CLIENT_SCOPE.search(text))
    text = CLIENT_SCOPE.sub("", text)
    req = bool(re.search(r"\(\s*(?:\*\*|==)*\s*If required", text, re.I))
    if req:
        text = IF_REQUIRED.sub(r"\1", text)
    return normalize(text).strip(), client, req


SPEC_RE = re.compile(
    r"^(?:OPTION\s*:?\s*(\d+)\s*[-–]?\s*)?ITEM NO[:.]?\s*(\d+)\s*[-–]?\s*(TECHNICAL SPECIFICATION(?:\s*&\s*METH\w+)?)\s+FOR\s+(.*?)[:\s]*$",
    re.I,
)
# the bungalow offer splits the title: "ITEM NO – 1" on its own line, then "TECHNICAL ... FOR ..."
ITEM_ONLY_RE = re.compile(r"^ITEM NO\s*[:.–-]?\s*(\d+)\s*[:.]?$", re.I)
TITLE_RE = re.compile(
    r"^(?:OPTION\s*:?\s*(\d+)\s*[-–]?\s*)?(TECHNICAL SPECIFICATION(?:\s*&\s*METH\w+)?)\s+FOR\s+(.*?)[:\s]*$",
    re.I,
)
BUDGET_RE = re.compile(
    r"^(?:ITEM NO[:.]?\s*(\d+)\s*[-–]?\s*)?BUDGETARY OFFER FOR\s+(.*?)[:\s]*$", re.I
)
OPTION_HEAD = re.compile(r"^OPTION\s*:?\s*(\d+)\s*[-–]?\s*(.*)$", re.I)


def _heading_like(p: Para) -> bool:
    t = p.plain
    if not t or p.numbered or len(t) > 90 or t.lower().startswith("image"):
        return False
    letters = re.sub(r"[^A-Za-z]", "", t)
    return p.all_bold or (letters.isupper() and len(letters) > 3)


# --- the import ----------------------------------------------------------------------------------


def _spec_start(p) -> bool:
    return isinstance(p, Para) and bool(
        SPEC_RE.match(p.plain) or ITEM_ONLY_RE.match(p.plain) or TITLE_RE.match(p.plain)
    )


AREA_SUFFIX = re.compile(r"\s+area$", re.I)
FIRM_RE = re.compile(r"^(firm|client)\s*name\s*:\s*", re.I)


def _opening(lines: list[Para]) -> str:
    """The letter lines before the subject, as a template: the date, the firm (and the bold city
    line under it), the attention line become placeholders; anything else stays as written."""
    out, after_firm = [], False
    for p in lines:
        t = p.plain
        if re.match(r"^date\b", t, re.I):
            out.append("Date: **{date}**")
        elif FIRM_RE.match(t):
            label = t.split(":")[0].strip()
            out.append(f"{label}: **{{client_firm}}**")
            after_firm = True
            continue
        elif after_firm and p.all_bold and ":" not in t:
            out.append("**{client_city}**")
        elif re.match(r"^kind\s+attn", t, re.I):
            out.append("Kind Attn.: **{attention}**")
        elif re.match(r"^dear\b", t, re.I):
            out += ["", t]
        else:
            out.append(p.text)
        after_firm = False
    return "\n".join(out)


def _company_short(db: Session, company: str) -> str:
    """The letterhead name: EESPL for our own company, else the company's first word."""
    from app.masters.models import CompanyProfile  # noqa: PLC0415

    profile = db.get(CompanyProfile, 1)
    ours = {"ethios enviro solutions"} | (
        {re.sub(r"[^a-z ]", "", (profile.legal_name or "").lower()).replace(" pvt ltd", "").strip()}
        if profile and profile.legal_name
        else set()
    )
    key = re.sub(r"[^a-z ]", "", company.lower())
    if any(o and o in key for o in ours):
        return "EESPL"
    return company.split()[0].title() if company else "Imported"


def _faded(blob: bytes, ext: str) -> str:
    """The watermark as the PDF draws it: faint (Word fades it itself; the PDF cannot)."""
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(blob)).convert("RGB")
    img.thumbnail((1400, 1400))
    faint = Image.blend(Image.new("RGB", img.size, (255, 255, 255)), img, 0.12)
    buf = io.BytesIO()
    faint.save(buf, "PNG")
    return _save_image(buf.getvalue(), "png")


def import_offer(
    db: Session, path: Path, user_id=None, again: bool = False, preset: str | None = None
) -> Result:
    res = Result()
    fix = Fixer(res)
    items, images = read(path)
    i = 0

    # ---- the cover letter
    letter: list[Para] = []
    while i < len(items) and not _spec_start(items[i]):
        if isinstance(items[i], Para) and items[i].plain:
            letter.append(items[i])
        i += 1
    get = {
        "firm": next((p for p in letter if FIRM_RE.match(p.plain)), None),
        "subject": next((p for p in letter if p.plain.upper().startswith("SUB")), None),
        "for": next((p for p in letter if p.plain.startswith("For ")), None),
    }
    firm = FIRM_RE.sub("", get["firm"].plain) if get["firm"] else ""
    sig_firm = (get["for"].plain if get["for"] else "For EESPL").rstrip(" ,")
    company = sig_firm[4:].strip()
    head_name = _company_short(db, company)
    existing = db.scalar(select(Letterhead).where(Letterhead.name == head_name))
    # the seeded EESPL letterhead (no images, never edited) is filled in rather than duplicated
    # (a seeded row has no library version: anything imported or edited has at least one)
    fill_existing = (
        existing is not None
        and not existing.header_image_path
        and not again
        and db.scalar(
            select(LibraryVersion.id)
            .where(LibraryVersion.kind == "letterhead", LibraryVersion.entity_id == existing.id)
            .limit(1)
        )
        is None
    )
    if existing is not None and not fill_existing and not again:
        raise ValueError(
            f"Already imported: the letterhead {head_name} exists (use --again to import another copy)"
        )
    if again:
        head_name = f"{head_name} {uuid.uuid4().hex[:4]}"
    idx_for = letter.index(get["for"]) if get["for"] else len(letter)
    sign = letter[idx_for + 1].plain if idx_for + 1 < len(letter) else ""
    if sign.lower().startswith("encl"):
        sign = ""
    sig_name, _, sig_desig = (x.strip() for x in sign.partition("|"))
    idx_sub = letter.index(get["subject"]) if get["subject"] else 0
    opening = _opening(letter[:idx_sub])
    body_paras = [p.text for p in letter[idx_sub + 1 : idx_for]]
    # the brand: the first word in capitals after "using" ("**BRONCO Products**" -> BRONCO)
    brand_m = re.search(r"using\s+\*\*([A-Za-z]{2,})\b", " ".join(body_paras), re.I)
    brand = brand_m.group(1) if brand_m and brand_m.group(1).isupper() else None
    body = "\n".join(body_paras)
    if brand:
        body = body.replace(brand, "{brand}")
    project_words = [
        w
        for w in re.findall(r"\*\*([^*]+)\*\*", body)
        if firm and w.strip().lower() == firm.lower()
    ]
    for w in project_words:
        body = body.replace(f"**{w}**", "**{project}**")
    subject = (
        get["subject"].text if get["subject"] else "SUB: OFFER FOR {areas_list} WATERPROOFING WORK."
    )
    if "==" in subject:
        subject = re.sub(r"==[^=]+==", "{areas_list}", subject, count=1)
    else:  # no highlighted part: the words between "OFFER FOR" and "WATERPROOFING"
        subject = re.sub(
            r"(OFFER FOR\s+)(.+?)(\s+WATERPROOFING)",
            r"\1{areas_list}\3",
            subject,
            count=1,
            flags=re.I,
        )
    subject = subject.replace("**", "")
    enc_start = next((k for k, p in enumerate(letter) if p.plain.lower().startswith("encl")), None)
    enclosures = (
        "\n".join(p.plain.rstrip(".") for p in letter[enc_start + 1 :])
        if enc_start is not None
        else ""
    )
    lt = LetterTemplate(
        name=f"{head_name} offer letter (imported)",
        opening=opening,
        subject=subject,
        body=body,
        enclosures=enclosures,
        needs_check=True,
        created_by=user_id,
    )
    lib.check_letter(lt.subject, lt.body, lt.opening)
    db.add(lt)
    db.flush()
    lib.save_version(db, lt, "import", user_id, note=f"imported from {path.name}")
    head = existing if fill_existing else Letterhead(name=head_name, created_by=user_id)
    head.company_name = company or head_name
    head.signatory_firm = sig_firm
    head.signatory_name = sig_name or None
    head.signatory_designation = sig_desig or None
    head.brand = brand
    head.letter_template_id = lt.id
    head.needs_check = True
    if "logo" in images:
        head.logo_path = _save_image(*images["logo"])
    if "header" in images:
        head.header_image_path = _save_image(*images["header"])
    if "footer" in images:
        head.footer_image_path = _save_image(*images["footer"])
    if "watermark" in images:
        head.watermark_path = _faded(*images["watermark"])
    if not fill_existing:
        db.add(head)
    db.flush()
    if fill_existing:
        res.notes.append(
            f"The {head_name} letterhead (seeded, no images yet) was filled in from {path.name}"
        )
    res.counts["letterheads"] = 1
    res.counts["letter_templates"] = 1

    # ---- technical specifications
    blocks: dict[int, list[SpecBlock]] = {}
    names: dict[int, str] = {}
    current: SpecBlock | None = None
    item_no = 0
    section: dict | None = None
    pending_images: list[str] = []
    pending_no: int | None = None
    expect_subtitle = False

    def next_para(k: int):
        while k < len(items) and isinstance(items[k], Para) and not items[k].plain:
            k += 1
        return items[k] if k < len(items) and isinstance(items[k], Para) else None

    while i < len(items):
        it = items[i]
        if isinstance(it, Para) and BUDGET_RE.match(it.plain):
            break
        i += 1
        if not isinstance(it, Para):
            continue
        if it.images and current is not None:
            pending_images += [_save_image(b, e) for b, e in it.images]
            continue
        if not it.plain or re.fullmatch(r"OR", it.plain.strip(), re.I):
            continue
        only = ITEM_ONLY_RE.match(it.plain)
        if only:  # "ITEM NO – 1" alone: the title follows on the next line
            pending_no = int(only.group(1))
            continue
        m = SPEC_RE.match(it.plain)
        t = None if m else TITLE_RE.match(it.plain)
        if m or t:
            if m:
                opt, n, prefix, title = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            else:
                opt, prefix, title = t.group(1), t.group(2), t.group(3)
                n = (
                    pending_no
                    if pending_no is not None
                    else (max(blocks, default=0) + (0 if opt and opt != "1" else 1))
                )
            pending_no = None
            expect_subtitle = True
            item_no = n
            title_clean = re.sub(r"\s+", " ", title.replace("–", "-")).strip()
            if n not in names:
                names[n] = sentence(
                    re.split(r"\s+WATERPROOFING", title_clean, flags=re.I)[0].strip(" -")
                )
            current = SpecBlock(
                title=fix(sentence(title_clean), n, names[n]),
                heading_prefix=fix(re.sub(r"\s+", " ", prefix.upper()), n) + " FOR",
                option_label=opt,
                sections=[],
                images=[],
                needs_check=True,
                created_by=user_id,
            )
            blocks.setdefault(n, []).append(current)
            section = None
            continue
        if current is None:
            continue
        if pending_images and it.plain.lower().startswith("image"):
            current.images = current.images + [
                {"path": p, "caption": it.plain} for p in pending_images
            ]
            pending_images = []
            continue
        if _heading_like(it) and expect_subtitle and not current.sections:
            nxt = next_para(i)
            if nxt is not None and _heading_like(nxt) and not ITEM_ONLY_RE.match(nxt.plain):
                # a line under the item title, then the first stage heading: a sub-heading
                current.subtitle = fix(it.plain, item_no, names.get(item_no, ""))
                expect_subtitle = False
                continue
        expect_subtitle = False
        if _heading_like(it):
            hm = OPTION_HEAD.match(it.plain)
            option, heading = (hm.group(1), hm.group(2)) if hm else (None, it.plain)
            heading = fix(heading, item_no, names.get(item_no, ""))
            section = {"heading": _stage(heading), "option": option, "steps": []}
            current.sections = current.sections + [section]
            continue
        text, client, req = _flags(fix(it.text, item_no, names.get(item_no, "")))
        if section is None:
            section = {"heading": "", "option": None, "steps": []}
            current.sections = current.sections + [section]
        if it.numbered or not section["steps"]:
            section["steps"].append({"text": text, "client_scope": client, "if_required": req})
        else:  # a paragraph that continues the step above
            last = section["steps"][-1]
            last["text"] += "\n" + text
            last["client_scope"] = last["client_scope"] or client
            last["if_required"] = last["if_required"] or req
        current.sections = list(current.sections)  # mark the JSON as changed
    if pending_images and current is not None:
        current.images = current.images + [{"path": p, "caption": ""} for p in pending_images]

    # ---- budgetary offer
    budget: dict[int, tuple[str, list[dict]]] = {}
    order = sorted(blocks)  # budget headings without "ITEM NO" follow the items in order
    while i < len(items):
        it = items[i]
        if isinstance(it, Para) and "TERMS AND CONDITIONS" in it.plain.upper():
            break
        i += 1
        if not isinstance(it, Para):
            continue
        m = BUDGET_RE.match(it.plain)
        if not m:
            continue
        if m.group(1):
            n = int(m.group(1))
        else:
            n = (
                order[len(budget)]
                if len(budget) < len(order)
                else max(order + list(budget), default=0) + 1
            )
        title = m.group(2)
        while i < len(items) and not isinstance(items[i], list):
            i += 1
        table = items[i] if i < len(items) else []
        i += 1
        budget[n] = (
            sentence(re.sub(r"\s+", " ", title).strip(" -")),
            _lines(table[1:], fix, n, names.get(n, ""), res),
        )

    # ---- terms and conditions
    clauses: list[tuple[str, str]] = []
    category = "Client's obligations"
    list_id: str | None = None
    while i < len(items):
        it = items[i]
        if isinstance(it, Para) and "esteemed clients" in it.plain.lower():
            break
        i += 1
        if not isinstance(it, Para) or not it.plain:
            continue
        up = it.plain.upper()
        if "GENERAL TERMS AND CONDITIONS" in up:
            continue
        if not it.numbered and "OBLIGATION" in up and len(up) < 40:
            category = "Client's obligations"
            if re.search(r"\bCLIENTS OBLIGATION\b", up):  # printed as "CLIENT'S OBLIGATIONS"
                fix.note("CLIENTS OBLIGATION -> CLIENT'S OBLIGATIONS")
            continue
        if it.numbered and (list_id is None or it.num_id == list_id):
            list_id = list_id or it.num_id
            text = fix(it.text)
            cat = category
            if up.startswith("FORCE MAJEURE"):
                cat = "Force majeure"
            elif up.startswith("TAXES"):
                cat = "Taxes"
            elif up.startswith("VALIDITY"):
                cat = "Validity"
            elif "AUTHORIZED APPLICATOR" in up and "WORK ORDER" in up:
                cat = "Applicator"
                text = re.sub(
                    r"ETHIOS ENVIRO SOLUTIONS PVT\.? LTD\.?", "{applicator}", text, flags=re.I
                )
            elif up.startswith("TERMS OF PAYMENT"):
                cat = "Terms of payment"
            clauses.append((cat, text))
            continue
        if clauses:  # the text under TAXES: / VALIDITY:, or a payment sub-point
            cat, text = clauses[-1]
            line = ("- " if it.numbered else "") + fix(it.text)
            clauses[-1] = (cat, text + "\n" + line)

    # ---- references
    state, title = None, None
    refs: list[Reference] = []
    while i < len(items):
        it = items[i]
        i += 1
        if isinstance(it, Para) and "esteemed clients" in it.plain.lower():
            title = it.plain
            sm = re.search(r"\bin\s+([A-Za-z][A-Za-z ]+)$", it.plain)
            state = sm.group(1).strip() if sm else None
            continue
        if isinstance(it, list) and title:
            for order, row in enumerate(it[1:], 1):
                cells = [" ".join(plain(x) for x in c) for c in row]
                if len(cells) < 5 or not any(cells[1:]):
                    continue
                area = cells[4]
                value = _decimal(area.replace(",", ""))
                unit = re.sub(r"[\d,.\s]", "", area).upper() or None
                refs.append(
                    Reference(
                        client_name=cells[1],
                        project=cells[2],
                        application=" / ".join(plain(x) for x in row[3]),
                        area_value=value,
                        area_unit=unit,
                        state=state,
                        source="imported",
                        sort_order=order,
                        needs_check=True,
                        created_by=user_id,
                    )
                )
            title = None

    # ---- write the libraries
    types = {t.name: t.id for t in db.scalars(select(AreaType))}

    def area_type(name: str) -> int | None:
        for k, t in AREA_KEYWORDS:
            if k in name.lower():
                return types.get(t)
        return None

    def system_label(n: int) -> str | None:
        text = " ".join(
            st["text"] for b in blocks.get(n, []) for s in b.sections for st in s["steps"]
        ).upper()
        return next((label for key, label in SYSTEM_LABELS if key in text), None)

    n_specs = n_lines = n_options = reused_lines = 0
    made_items: list[OfferItem] = []
    for n in sorted(set(blocks) | set(budget)):
        name = names.get(n) or (budget[n][0] if n in budget else f"Item {n}")
        at = area_type(name)
        label = system_label(n)
        if (
            at
            and label
            and db.scalar(
                select(OfferItem.id)
                .where(OfferItem.area_type_id == at, OfferItem.is_active)
                .limit(1)
            )
        ):
            # the same area with another system already in the library: name this one by its system
            name = f"{AREA_SUFFIX.sub('', name)} - {label}"
        item = OfferItem(
            name=name,
            area_type_id=at,
            budget_title=budget[n][0] if n in budget else name,
            sort_order=n * 10,
            needs_check=True,
            created_by=user_id,
        )
        options = set()
        for k, b in enumerate(blocks.get(n, [])):
            b.area_type_id = at
            db.add(b)
            db.flush()
            lib.save_version(db, b, "import", user_id, note=f"imported from {path.name}")
            item.specs.append(OfferItemSpec(spec_block_id=b.id, sort_order=k))
            n_specs += 1
            options |= {b.option_label} if b.option_label else set()
            options |= {s["option"] for s in b.sections if s.get("option")}
        for k, ln in enumerate(budget.get(n, ("", []))[1]):
            # an offer line already in the library with the very same text, UoM and rate is reused
            ol = db.scalar(
                select(OfferLine)
                .where(
                    OfferLine.description == ln["description"],
                    OfferLine.uom == ln["uom"],
                    OfferLine.default_rate.is_not_distinct_from(ln["rate"]),
                    OfferLine.if_required.is_(ln["if_required"]),
                    OfferLine.client_scope.is_(ln["client_scope"]),
                    OfferLine.is_active,
                )
                .limit(1)
            )
            if ol is not None:
                reused_lines += 1
            else:
                ol = OfferLine(
                    description=ln["description"],
                    uom=ln["uom"],
                    rate_source="fixed",
                    default_rate=ln["rate"],
                    if_required=ln["if_required"],
                    client_scope=ln["client_scope"],
                    needs_check=True,
                    created_by=user_id,
                )
                db.add(ol)
                db.flush()
                lib.save_version(db, ol, "import", user_id, note=f"imported from {path.name}")
            item.lines.append(OfferItemLine(offer_line_id=ol.id, option=ln["option"], sort_order=k))
            n_lines += 1
            options |= {ln["option"]} if ln["option"] else set()
        db.add(item)
        db.flush()
        lib.save_version(db, item, "import", user_id, note=f"imported from {path.name}")
        made_items.append(item)
        n_options += len(options)
        if at is None:
            res.notes.append(f"Item {n} “{name}”: no area type matched, pick one in the library")
    res.counts.update(
        items=len(set(blocks) | set(budget)),
        spec_blocks=n_specs,
        options=n_options,
        offer_lines=n_lines,
        offer_lines_reused=reused_lines,
    )

    # T&C: reuse existing clauses with the same text, else add them (marked for review)
    tpl = TcTemplate(name=f"{head_name} techno-commercial offer (imported)", created_by=user_id)
    db.add(tpl)
    db.flush()
    reused_tc = 0
    for order, (cat, text) in enumerate(clauses):
        c = db.scalar(select(TcClause).where(TcClause.text == text).limit(1))
        reused_tc += c is not None
        if c is None:
            c = TcClause(
                text=text,
                category=TC_CODES.get(cat, "general"),
                needs_review=True,
                created_by=user_id,
            )
            db.add(c)
            db.flush()
        db.add(TcTemplateClause(template_id=tpl.id, clause_id=c.id, sort_order=order))
    head.tc_template_id = tpl.id
    head.references_state = state
    lib.save_version(db, head, "import", user_id, note=f"imported from {path.name}")
    res.counts["tc_clauses"] = len(clauses)
    res.counts["tc_clauses_reused"] = reused_tc
    for r in refs:
        db.add(r)
        db.flush()
        lib.save_version(db, r, "import", user_id, note=f"imported from {path.name}")
    res.counts["references"] = len(refs)
    if preset:
        p = OfferPreset(
            name=preset,
            letterhead_id=head.id,
            letter_template_id=lt.id,
            tc_template_id=tpl.id,
            items=[{"offer_item_id": it.id, "options": []} for it in made_items],
            include_references=bool(refs),
            needs_check=True,
            created_by=user_id,
        )
        db.add(p)
        db.flush()
        lib.save_version(db, p, "import", user_id, note=f"imported from {path.name}")
        res.counts["presets"] = 1
    return res


def _lines(rows: list[list[list[str]]], fix: Fixer, n: int, name: str, res: Result) -> list[dict]:
    """Budget table rows -> offer lines. A row with no Sr, UoM and rate continues the row above;
    a row whose UoM cell holds two UoMs for "Option 1 ... OR ... Option 2" is split into Opt.1 /
    Opt.2 rows (the duplicated "SQ FTSQ FT")."""
    out: list[dict] = []
    for cells in rows:
        if len(cells) < 3:
            continue
        sr = plain(" ".join(cells[0]))
        desc_paras = [fix(x, n, name) for x in cells[1]]
        uom_cell = [plain(x) for x in cells[2]]
        rate_cell = [plain(x) for x in cells[3]] if len(cells) > 3 else []
        if not sr and not uom_cell and not rate_cell and out:
            out[-1]["description"] += "\n" + "\n".join(desc_paras)
            continue
        client = any("client" in u.lower() for u in uom_cell + rate_cell)
        opt_m = re.match(r"Opt\.?\s*(\d+)", sr, re.I)
        option = opt_m.group(1) if opt_m else None
        if len(uom_cell) > 1 and len(set(uom_cell)) == 1:
            key = f"duplicated UoM {' / '.join(uom_cell)} -> one UoM, split into Opt. rows"
            res.fixes[key] = res.fixes.get(key, 0) + 1
            starts = [
                k for k, p in enumerate(desc_paras) if re.match(r"Option\s*:?\s*\d", plain(p), re.I)
            ]
            if len(starts) >= 2 and len(rate_cell) >= 2:
                common = desc_paras[: starts[0]]
                for j, s in enumerate(starts[:2]):
                    end = starts[j + 1] if j + 1 < len(starts) else len(desc_paras)
                    part = [p for p in desc_paras[s:end] if plain(p).upper() != "OR"]
                    part[0] = re.sub(
                        r"^(\*\*)?(==)?\s*Option\s*:?\s*\d+\s*[-–]?\s*(==)?(\*\*)?\s*",
                        "",
                        part[0],
                        flags=re.I,
                    )
                    text, c2, req = _flags("\n".join(common + part))
                    out.append(
                        {
                            "description": text,
                            "uom": _uom(uom_cell[0]),
                            "rate": _decimal(rate_cell[j]),
                            "option": str(j + 1),
                            "if_required": req,
                            "client_scope": c2,
                        }
                    )
                continue
            uom_cell = uom_cell[:1]
        text, c2, req = _flags("\n".join(desc_paras))
        out.append(
            {
                "description": text,
                "uom": _uom(uom_cell[0]) if uom_cell and not client else "sqft",
                "rate": None if client else _decimal(rate_cell[0] if rate_cell else ""),
                "option": option,
                "if_required": req,
                "client_scope": client or c2,
            }
        )
    return out


def _uom(text: str) -> str:
    key = re.sub(r"[^A-Z]", "", text.upper())
    return UOM_MAP.get(key, "sqft")
