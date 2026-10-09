# ruff: noqa: E501  (HTML, patterns and offer wording read better unwrapped)
"""One document model of a quotation, used for the Word file, the PDF and the live preview, so
all three always say the same thing.

Layout follows the sample offer: the cover letter; "ITEM NO: n - TECHNICAL SPECIFICATION ..." per
item (option blocks separated by "OR"), numbered steps per stage section; "ITEM NO: n - BUDGETARY
OFFER FOR ..." tables (Sr, description, UoM, rate; with quantities also qty and amount); the
general terms and conditions; "Our esteemed clients".
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.masters.models import CompanyProfile
from app.quotations import service as svc
from app.quotations.markup import fill, placeholders_in
from app.quotations.models import TC_GROUP_LABELS, UOM_LABELS, Letterhead, Quotation

CLIENT_SCOPE = "==Client's Scope=="


def fmt_money(v: Decimal | None) -> str:
    """Indian grouping, 2 decimals: 1,25,000.00."""
    if v is None:
        return ""
    v = Decimal(v).quantize(Decimal("0.01"))
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}{whole}.{frac}"


def fmt_qty(v) -> str:
    if v is None:
        return ""
    s = f"{Decimal(v):.3f}".rstrip("0").rstrip(".")
    return s


def fmt_area(v: Decimal | None) -> str:
    if v is None:
        return ""
    return fmt_money(v)[:-3]  # whole numbers: 10,85,000


@dataclass
class Step:
    number: int
    text: str  # markup


@dataclass
class Section:
    heading: str
    steps: list[Step]
    or_before: bool = False


@dataclass
class SpecOut:
    heading: str
    sections: list[Section]
    images: list[dict]
    or_before: bool = False
    subtitle: str = ""


@dataclass
class Row:
    sr: str
    description: str  # markup
    uom: str
    rate: str  # "625.00" or the client's scope mark
    client_scope: bool = False
    qty: str = ""
    amount: str = ""


@dataclass
class BudgetOut:
    heading: str
    rows: list[Row]
    subtotal: str = ""


@dataclass
class TermGroup:
    heading: str | None
    clauses: list[tuple[int, str]]  # (number, markup with "- " sub-points)


@dataclass
class Doc:
    code: str
    revision: int
    footer: str
    company_name: str
    logo: Path | None
    header_image: Path | None
    footer_image: Path | None
    watermark: Path | None
    preprinted: bool
    header_text: str
    footer_text: str
    primary: str
    accent: str
    opening: list[str]
    subject: str
    body: list[str]
    signatory_firm: str
    signatory_line: str
    enclosures: list[str]
    specs: list[tuple[int, list[SpecOut]]] = field(default_factory=list)
    budgets: list[BudgetOut] = field(default_factory=list)
    show_amounts: bool = False
    total: str = ""
    total_note: str = ""
    terms: list[TermGroup] = field(default_factory=list)
    references_title: str = ""
    references: list[dict] = field(default_factory=list)


def _media(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(app_settings.media_dir) / rel
    return p if p.exists() else None


def _labelled(options: set[str]) -> bool:
    return len(options) > 1


def spec_outs(item, n: int) -> list[SpecOut]:
    offered = svc.offered(item)
    blocks = [s for s in item.specs if svc.is_offered(item, s.get("option_label"))]
    block_opts = {str(s["option_label"]) for s in blocks if s.get("option_label")}
    out = []
    for b in blocks:
        opt = b.get("option_label")
        prefix = f"OPTION: {opt} - " if opt and _labelled(block_opts) else ""
        lead = (b.get("heading_prefix") or "TECHNICAL SPECIFICATION FOR").strip()
        lead = lead if lead.upper().endswith(" FOR") else f"{lead} FOR"
        heading = f"{prefix}ITEM NO: {n} - {lead} {b['title'].upper()}"
        sections, number = [], 0
        secs = [
            s
            for s in b.get("sections") or []
            if s.get("option") is None or str(s["option"]) in offered
        ]
        sec_opts = {str(s["option"]) for s in secs if s.get("option")}
        prev_opt = None
        for s in secs:
            steps = []
            for st in s.get("steps") or []:
                number += 1
                text = st.get("text", "")
                if st.get("client_scope"):
                    text += " ==(Client's scope)=="
                if st.get("if_required"):
                    text += " ==(If required)=="
                steps.append(Step(number, text))
            o = s.get("option")
            label = f"OPTION: {o} - " if o and _labelled(sec_opts) else ""
            sections.append(
                Section(
                    heading=f"{label}{(s.get('heading') or '').upper()}",
                    steps=steps,
                    or_before=bool(
                        o and prev_opt and str(o) != str(prev_opt) and _labelled(sec_opts)
                    ),
                )
            )
            prev_opt = o if o else None
        images = [{**i, "file": _media(i.get("path"))} for i in b.get("images") or []]
        out.append(
            SpecOut(
                heading,
                sections,
                [i for i in images if i["file"]],
                or_before=bool(prefix and out),
                subtitle=(b.get("subtitle") or "").upper(),
            )
        )
    return out


def budget_out(item, n: int, show_amounts: bool) -> BudgetOut:
    lines = [ln for ln in item.lines if svc.is_offered(item, ln.option)]
    line_opts = {ln.option for ln in lines if ln.option}
    rows, counter, last_group = [], 0, None
    for ln in lines:
        if ln.option and _labelled(line_opts):
            if last_group != "options":
                counter += 1
            sr, last_group = f"Opt.{ln.option}.", "options"
        elif ln.if_required or ln.client_scope:
            sr, last_group = "", None
        else:
            counter += 1
            sr, last_group = f"{counter}.", None
        text = ln.description
        if ln.if_required and "if required" not in text.lower():
            text += " ==(If required)=="
        amount = svc.line_amount(ln)
        rows.append(
            Row(
                sr=sr,
                description=text,
                uom=UOM_LABELS.get(ln.uom, ln.uom.upper()),
                rate=CLIENT_SCOPE if ln.client_scope else fmt_money(ln.rate) or "On request",
                client_scope=ln.client_scope,
                qty=fmt_qty(ln.qty) if show_amounts else "",
                amount=fmt_money(amount) if show_amounts and amount is not None else "",
            )
        )
    return BudgetOut(
        heading=f"ITEM NO: {n} - BUDGETARY OFFER FOR {item.budget_title.upper()}:", rows=rows
    )


def term_groups(terms: list[dict], applicator: str) -> list[TermGroup]:
    """Clauses numbered right through; a group of two or more clauses gets its heading, a single
    clause carries its own bold label."""
    groups: list[tuple[str, list[str]]] = []
    for t in terms:
        cat = t.get("category") or ""
        if groups and groups[-1][0] == cat:
            groups[-1][1].append(t["text"])
        else:
            groups.append((cat, [t["text"]]))
    out, n = [], 0
    for cat, texts in groups:
        clauses = []
        for text in texts:
            n += 1
            clauses.append((n, fill(text, {"applicator": applicator})))
        label = TC_GROUP_LABELS.get(cat, cat.replace("_", " ").capitalize())
        out.append(TermGroup(label.upper() if len(texts) > 1 and cat else None, clauses))
    return out


def fill_lines(text: str, values: dict[str, str]) -> list[str]:
    """The letter lines with their placeholders filled; a line whose placeholders are all empty
    (no city, no attention) is dropped instead of printed blank."""
    out = []
    for line in (text or "").split("\n"):
        names = placeholders_in(line)
        if names and not any(str(values.get(n) or "").strip() for n in names):
            continue
        out.append(fill(line, values))
    return out


def build(db: Session, q: Quotation, preprinted: bool | None = None) -> Doc:
    head = db.get(Letterhead, q.letterhead_id) if q.letterhead_id else None
    profile = db.get(CompanyProfile, 1)
    applicator = (
        (profile.legal_name or profile.trade_name) if profile else None
    ) or "Ethios Enviro Solutions Pvt. Ltd."
    values = svc.placeholder_values(db, q, head)
    company = head.company_name if head else applicator
    doc = Doc(
        code=q.code,
        revision=q.revision,
        footer=f"{q.code} R{q.revision}",
        company_name=company,
        logo=_media(head.logo_path) if head else _media(profile.logo_path if profile else None),
        header_image=_media(head.header_image_path) if head else None,
        footer_image=_media(head.footer_image_path) if head else None,
        watermark=_media(head.watermark_path) if head else None,
        preprinted=bool(head and head.preprinted) if preprinted is None else preprinted,
        header_text=(head.header_text if head else "") or "",
        footer_text=(head.footer_text if head else "") or "",
        primary=head.primary_color if head else "#0F6E5A",
        accent=head.accent_color if head else "#E69F00",
        opening=fill_lines(q.opening, values),
        subject=fill(q.subject, values),
        body=fill_lines(q.body, values),
        signatory_firm=(head.signatory_firm if head else f"For {applicator.upper()}"),
        signatory_line=" | ".join(x for x in (values["salesperson"], values["designation"]) if x),
        enclosures=[e for e in q.enclosures.split("\n") if e.strip()],
        show_amounts=q.show_amounts,
    )
    for n, item in enumerate(q.items, 1):
        doc.specs.append((n, spec_outs(item, n)))
    t = svc.totals(q)
    by_item = {x["item_id"]: x["total"] for x in t["items"]}
    for n, item in enumerate(q.items, 1):
        b = budget_out(item, n, q.show_amounts)
        if q.show_amounts and by_item.get(item.id):
            b.subtotal = fmt_money(by_item[item.id])
        doc.budgets.append(b)
    if q.show_amounts:
        doc.total = fmt_money(t["total"])
        notes = ["Excludes GST, “if required” and client's scope items."]
        if t["option_note"]:
            notes.insert(0, "Where options are offered, the total takes the first option.")
        doc.total_note = " ".join(notes)
    doc.terms = term_groups(q.terms or [], applicator.upper())
    doc.references_title = q.references_title or "Our Esteemed Clients for Waterproofing Projects"
    doc.references = [
        {
            **r,
            "area_text": f"{fmt_area(Decimal(str(r['area_value'])))} {r.get('area_unit') or ''}".strip()
            if r.get("area_value") not in (None, "")
            else "",
        }
        for r in q.references or []
        if r.get("include", True)
    ]
    return doc


def letterhead_options(db: Session) -> list[Letterhead]:
    return list(
        db.scalars(select(Letterhead).where(Letterhead.is_active).order_by(Letterhead.name))
    )
