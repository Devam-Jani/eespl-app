# ruff: noqa: E501  (HTML, patterns and offer wording read better unwrapped)
"""The quotation as HTML: the live preview in the editor and, through WeasyPrint, the PDF.

Page rules the hand-made offers break today: an item heading stays with its table or first step
(break-after: avoid), table header rows repeat on every page (thead), rows never split across
pages, and the "OR" between options stays with the option it introduces.
"""

import base64
import mimetypes
from html import escape
from pathlib import Path

from app.quotations.markup import inline_html, to_html
from app.quotations.render import Doc


def _img(path: Path | None) -> str:
    if not path:
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _clause(text: str) -> str:
    """A clause: paragraphs, with "- " lines as lettered sub-points."""
    out, subs = [], []
    for line in text.split("\n"):
        if line.startswith("- "):
            subs.append(f"<li>{inline_html(line[2:])}</li>")
            continue
        if subs:
            out.append(f'<ol class="sub" type="a">{"".join(subs)}</ol>')
            subs = []
        out.append(f"<p>{inline_html(line)}</p>")
    if subs:
        out.append(f'<ol class="sub" type="a">{"".join(subs)}</ol>')
    return "".join(out)


def band_mm(path: Path | None) -> float:
    """The height of a full-width (210 mm) band image, mm."""
    if not path:
        return 0.0
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as im:
        w, h = im.size
    return round(210 * h / w, 1) if w else 0.0


def _ratio(path: Path | None) -> float:
    """height / width of an image."""
    if not path:
        return 1.0
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as im:
        w, h = im.size
    return h / w if w else 1.0


def image_letterhead(doc: Doc) -> bool:
    return bool(doc.header_image or doc.footer_image)


def css(doc: Doc, for_pdf: bool) -> str:
    box = 'font-family: "DejaVu Sans", Arial, sans-serif; color: #555; vertical-align: top; padding-top: 3mm;'
    if image_letterhead(doc):
        # bands across the page: the text keeps clear of them; on pre-printed paper the space stays blank
        top, bottom = band_mm(doc.header_image) + 6, band_mm(doc.footer_image) + 12
        margins = f"{top}mm 16mm {bottom}mm 16mm"
        letterhead_box = ""
        # fixed boxes repeat on every page; they sit in the text area, so they are pulled out to
        # the page edges by the margins
        bg = ""
        wm = 150
        mark_top = 148.5 - top - wm * _ratio(doc.watermark) / 2 if doc.watermark else 0
        extra_css = f"""
.lh-fixed {{ position: fixed; left: -16mm; width: 210mm; }}
.lh-fixed img {{ display: block; width: 100%; }}
.lh-top {{ top: -{top}mm; }}
.lh-bottom {{ bottom: -{bottom}mm; }}
.lh-mark {{ top: {mark_top:.1f}mm; left: {(210 - wm) / 2 - 16:.1f}mm; width: {wm}mm; z-index: -1; }}
"""
    else:
        margins = "34mm 16mm 22mm 16mm"
        bg = ""
        extra_css = ""
        letterhead_box = (
            "" if doc.preprinted else "@top-center { content: element(letterhead); width: 100%; }"
        )
    page = (
        f"""
@page {{
  size: A4; margin: {margins}; {bg}
  {letterhead_box}
  @bottom-left {{ {box} content: "{escape(doc.footer)}"; font-size: 8pt; }}
  @bottom-center {{ {box} content: "{escape(doc.footer_text.replace(chr(10), " "))}"; font-size: 7.5pt; }}
  @bottom-right {{ {box} content: "Page " counter(page) " of " counter(pages); font-size: 8pt; }}
}}
.letterhead {{ position: running(letterhead); }}
{extra_css}"""
        if for_pdf
        else """
body { max-width: 190mm; margin: 0 auto; padding: 12px 18px 40px; background: #fff; }
.letterhead { border-bottom: 2px solid var(--primary); margin-bottom: 14px; }
.page-break { border-top: 1px dashed #bbb; margin: 22px 0 10px; }
img.band { display: block; width: calc(100% + 36px); margin: -12px -18px 12px; }
.footer-note + img.band { margin: 8px -18px -40px; }
.footer-note { color: #666; font-size: 8pt; text-align: right; border-top: 1px solid #ddd; margin-top: 30px; padding-top: 4px; }
"""
    )
    return (
        page
        + f"""
:root {{ --primary: {doc.primary}; --accent: {doc.accent}; }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; font-size: 9.5pt; line-height: 1.35; color: #111; }}
.letterhead {{ display: flex; align-items: center; gap: 12px; padding-bottom: 4px; border-bottom: 2px solid {doc.primary}; }}
.letterhead img {{ max-height: 20mm; max-width: 70mm; }}
.letterhead .lh-name {{ font-weight: bold; font-size: 12pt; color: {doc.primary}; }}
.letterhead .lh-text {{ font-size: 8pt; color: #444; white-space: pre-line; }}
p {{ margin: 0 0 5px; }}
.subject {{ font-weight: bold; margin: 10px 0; }}
.sign {{ margin-top: 14px; }}
.page-break {{ break-before: page; }}
h2.item {{ font-size: 10pt; margin: 14px 0 6px; color: #111; break-after: avoid; page-break-after: avoid; }}
p.subtitle {{ font-weight: bold; margin: -2px 0 6px; break-after: avoid; }}
h3.stage {{ font-size: 9.5pt; margin: 8px 0 3px; break-after: avoid; page-break-after: avoid; }}
p.or {{ font-weight: bold; text-align: center; margin: 8px 0; break-after: avoid; page-break-after: avoid; }}
/* numbers printed as text: the same in the browser preview and the PDF, never restarting */
.nitem {{ display: flex; gap: 6px; margin: 0 0 3px 6px; break-inside: avoid; page-break-inside: avoid; }}
.nitem .n {{ flex: none; min-width: 20px; text-align: right; }}
.nitem .t {{ flex: 1; }}
.nitem .t p {{ margin: 0; }}
.nitem.clause {{ margin-bottom: 5px; }}
figure {{ margin: 8px 0; text-align: center; break-inside: avoid; }}
figure img {{ max-width: 120mm; max-height: 80mm; }}
figcaption {{ font-weight: bold; font-size: 9pt; }}
mark {{ background: #fff3a0; }}
table {{ width: 100%; border-collapse: collapse; margin: 0 0 10px; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; page-break-inside: avoid; }}
th, td {{ border: 1px solid #666; padding: 4px 5px; vertical-align: top; }}
th {{ background: #eef3f1; text-align: left; }}
td.sr {{ width: 11mm; white-space: nowrap; }}
td.uom {{ width: 17mm; white-space: nowrap; }}
td.num, th.num {{ text-align: right; white-space: nowrap; }}
td p {{ margin: 0 0 3px; }}
td.scope {{ text-align: center; font-weight: bold; }}
tr.subtotal td {{ font-weight: bold; background: #f6f6f6; }}
.total {{ font-weight: bold; font-size: 10.5pt; text-align: right; margin: 8px 0 2px; }}
.total-note {{ font-size: 8pt; color: #444; text-align: right; }}
h2.terms {{ font-size: 10.5pt; margin: 12px 0 6px; break-after: avoid; }}
h3.term-group {{ font-size: 9.5pt; margin: 8px 0 3px; break-after: avoid; }}
ol.sub {{ margin: 2px 0 2px 16px; }}
"""
    )


def html(doc: Doc, for_pdf: bool = True) -> str:
    logo = _img(doc.logo)
    if image_letterhead(doc):
        # the PDF repeats the bands and the watermark on every page; the preview shows the bands
        # at its top and end
        parts = []
        if for_pdf and not doc.preprinted:
            for cls, path in (
                ("lh-mark", doc.watermark),
                ("lh-top", doc.header_image),
                ("lh-bottom", doc.footer_image),
            ):
                if path:
                    parts.append(
                        f'<div class="lh-fixed {cls}"><img src="{_img(path)}" alt=""></div>'
                    )
        if not for_pdf and doc.header_image and not doc.preprinted:
            parts.append(f'<img class="band" src="{_img(doc.header_image)}" alt="">')
    elif doc.preprinted:
        parts = []
    else:
        parts = [
            '<div class="letterhead">',
            f'<img src="{logo}" alt="">' if logo else "",
            f'<div><div class="lh-name">{escape(doc.company_name)}</div>'
            f'<div class="lh-text">{escape(doc.header_text)}</div></div></div>',
        ]
    # the cover letter (a library preview of one block has none)
    has_letter = bool(doc.subject.strip() or "".join(doc.body).strip())
    if has_letter:
        parts += [f"<p>{inline_html(p) or '&nbsp;'}</p>" for p in doc.opening]
        parts.append(f'<p class="subject">{inline_html(doc.subject)}</p>')
        parts += [f"<p>{inline_html(p) or '&nbsp;'}</p>" for p in doc.body]
        parts.append(
            f'<div class="sign"><p><b>{escape(doc.signatory_firm)}</b></p><p><b>{escape(doc.signatory_line)}</b></p></div>'
        )
    if has_letter and doc.enclosures:
        parts.append(
            "<p>Encl.:</p><ol>"
            + "".join(f"<li>{inline_html(e)}</li>" for e in doc.enclosures)
            + "</ol>"
        )
    # technical specifications
    first = has_letter
    for _n, specs in doc.specs:
        for s in specs:
            if first:
                parts.append('<div class="page-break"></div>')
                first = False
            if s.or_before:
                parts.append('<p class="or"><mark>OR</mark></p>')
            parts.append(f'<h2 class="item">{escape(s.heading)}</h2>')
            if s.subtitle:
                parts.append(f'<p class="subtitle">{escape(s.subtitle)}</p>')
            for sec in s.sections:
                if sec.or_before:
                    parts.append('<p class="or"><mark>OR</mark></p>')
                if sec.heading:
                    parts.append(f'<h3 class="stage">{escape(sec.heading)}:</h3>')
                if sec.steps:
                    parts += [
                        f'<div class="nitem"><span class="n">{st.number}.</span><div class="t">{to_html(st.text)}</div></div>'
                        for st in sec.steps
                    ]
            for im in s.images:
                parts.append(
                    f'<figure><img src="{_img(im["file"])}" alt=""><figcaption>{escape(im.get("caption") or "")}</figcaption></figure>'
                )
    # budgetary offer (on a new page when something comes before it)
    specs_printed = any(specs for _, specs in doc.specs)
    if (has_letter or specs_printed) and any(b.rows for b in doc.budgets):
        parts.append('<div class="page-break"></div>')
    amounts = doc.show_amounts
    for b in doc.budgets:
        parts.append(f'<h2 class="item">{escape(b.heading)}</h2>')
        head = "<tr><th>Sr No.</th><th>Item Description</th><th>UoM</th>"
        head += (
            '<th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th></tr>'
            if amounts
            else '<th class="num">Rate</th></tr>'
        )
        parts.append(f"<table><thead>{head}</thead><tbody>")
        for r in b.rows:
            if r.client_scope:
                span = 4 if amounts else 2
                parts.append(
                    f'<tr><td class="sr">{escape(r.sr)}</td><td>{to_html(r.description)}</td>'
                    f'<td class="scope" colspan="{span}">{inline_html(r.rate)}</td></tr>'
                )
                continue
            cells = f'<td class="sr">{escape(r.sr)}</td><td>{to_html(r.description)}</td><td class="uom">{escape(r.uom)}</td>'
            if amounts:
                cells += f'<td class="num">{escape(r.qty)}</td><td class="num">{escape(r.rate)}</td><td class="num">{escape(r.amount)}</td>'
            else:
                cells += f'<td class="num">{escape(r.rate)}</td>'
            parts.append(f"<tr>{cells}</tr>")
        if amounts and b.subtotal:
            parts.append(
                f'<tr class="subtotal"><td colspan="5">Item total</td><td class="num">{escape(b.subtotal)}</td></tr>'
            )
        parts.append("</tbody></table>")
    if amounts and doc.total:
        parts.append(
            f'<p class="total">Total (excluding GST): ₹ {escape(doc.total)}</p><p class="total-note">{escape(doc.total_note)}</p>'
        )
    # terms and conditions
    if doc.terms:
        parts.append('<h2 class="terms">GENERAL TERMS AND CONDITIONS</h2>')
        for g in doc.terms:
            if g.heading:
                parts.append(f'<h3 class="term-group">{escape(g.heading)}</h3>')
            parts += [
                f'<div class="nitem clause"><span class="n">{n}.</span><div class="t">{_clause(t)}</div></div>'
                for n, t in g.clauses
            ]
    # references
    if doc.references:
        parts.append(f'<h2 class="item">{escape(doc.references_title)}</h2>')
        parts.append(
            "<table><thead><tr><th>Sr. No.</th><th>Client Name</th><th>Project</th><th>Application Method &amp; Area</th>"
            '<th class="num">Area Covered</th></tr></thead><tbody>'
        )
        for i, r in enumerate(doc.references, 1):
            parts.append(
                f'<tr><td class="sr">{i}</td><td>{escape(r.get("client_name") or "")}</td><td>{escape(r.get("project") or "")}</td>'
                f'<td>{escape(r.get("application") or "")}</td><td class="num">{escape(r["area_text"])}</td></tr>'
            )
        parts.append("</tbody></table>")
    if not for_pdf:
        parts.append(f'<div class="footer-note">{escape(doc.footer)}</div>')
        if image_letterhead(doc) and doc.footer_image and not doc.preprinted:
            parts.append(f'<img class="band" src="{_img(doc.footer_image)}" alt="">')
    title = f"{doc.code} R{doc.revision}"
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
        f"<style>{css(doc, for_pdf)}</style></head><body>{''.join(parts)}</body></html>"
    )


def pdf(doc: Doc) -> bytes:
    from weasyprint import HTML

    return HTML(string=html(doc, for_pdf=True)).write_pdf()
