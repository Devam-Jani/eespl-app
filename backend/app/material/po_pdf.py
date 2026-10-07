"""The purchase order PDF (EESPL letterhead, GST split, charges, amount in words, PO T&C)."""

import base64
import html
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import CompanyGstin, CompanyProfile, TcTemplate
from app.material.models import Indent, PoIndent, PurchaseOrder, Store
from app.sites.models import Site
from app.tenders.export import company, inr

# Used when Settings > Purchase has no PO T&C template.
DEFAULT_TERMS = [
    "Please quote this PO number on the challan, invoice and every correspondence.",
    "Material must match the brand, grade and specification ordered; anything else will be "
    "rejected and returned at the supplier's cost.",
    "Each consignment must carry the delivery challan, tax invoice and test certificate / "
    "batch details.",
    "Quantities are as accepted at our store or site after inspection; rejected material is to "
    "be collected within 7 days.",
    "Payment as per the payment terms above, from the date of receipt of a correct invoice "
    "and the material.",
    "Delivery by the expected delivery date; delays must be informed in advance.",
    "Subject to Ahmedabad jurisdiction.",
]

CSS = """
@page { size: A4; margin: 12mm 11mm 14mm;
  @bottom-center { content: "Page " counter(page) " of " counter(pages); font-family: "DejaVu Sans";
    font-size: 7.5pt; color: #555; } }
body { font-family: "DejaVu Sans", sans-serif; font-size: 8.3pt; color: #111; }
.head { display: flex; gap: 12px; align-items: center; border-bottom: 1.5px solid #2f6f4f;
  padding-bottom: 6px; }
.head img { height: 44px; }
.head h1 { font-size: 13pt; margin: 0; }
.title { text-align: center; font-size: 12pt; font-weight: bold; letter-spacing: 1px;
  margin: 8px 0 6px; }
.boxes { display: flex; gap: 8px; margin-bottom: 8px; }
.box { flex: 1; border: 0.6px solid #999; padding: 5px 6px; }
.box h3 { margin: 0 0 3px; font-size: 8pt; color: #2f6f4f; text-transform: uppercase; }
table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group; }
th { background: #dce6e0; }
th, td { border: 0.6px solid #999; padding: 3px 4px; vertical-align: top; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr { page-break-inside: avoid; }
.totals { margin-top: 6px; width: 52%; margin-left: auto; }
.totals td { border: none; padding: 2px 4px; }
.totals .grand td { font-size: 10pt; font-weight: bold; border-top: 1px solid #333; }
.words { margin-top: 4px; font-style: italic; }
h2 { font-size: 9.5pt; margin: 12px 0 4px; }
.tc { display: flex; gap: 6px; margin-bottom: 2px; page-break-inside: avoid; }
.tc .no { min-width: 16px; text-align: right; }
.sign { margin-top: 26px; display: flex; justify-content: space-between;
  page-break-inside: avoid; }
.sign .line { margin-top: 34px; }
"""

ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _two(n: int) -> str:
    return ONES[n] if n < 20 else (TENS[n // 10] + (f" {ONES[n % 10]}" if n % 10 else ""))


def _three(n: int) -> str:
    h, rest = divmod(n, 100)
    out = f"{ONES[h]} Hundred" if h else ""
    if rest:
        out = f"{out} {_two(rest)}".strip()
    return out


def in_words(amount: Decimal) -> str:
    """12,34,567.50 -> "Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven and
    Fifty Paise Only" (Indian system)."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    rupees, paise = int(amount), int((amount - int(amount)) * 100)
    if rupees == 0:
        words = "Zero"
    else:
        parts = []
        crore, rupees = divmod(rupees, 10_000_000)
        lakh, rupees = divmod(rupees, 100_000)
        thousand, rupees = divmod(rupees, 1000)
        if crore:
            parts.append(f"{_three(crore) if crore < 1000 else in_words(Decimal(crore))} Crore")
        if lakh:
            parts.append(f"{_two(lakh)} Lakh")
        if thousand:
            parts.append(f"{_two(thousand)} Thousand")
        if rupees:
            parts.append(_three(rupees))
        words = " ".join(parts)
    tail = f" and {_two(paise)} Paise" if paise else ""
    return f"Rupees {words}{tail} Only"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _num(v: Decimal, places: int = 3) -> str:
    v = Decimal(v)
    return f"{v.normalize():f}" if v == v.to_integral() else f"{v:.{places}f}".rstrip("0")


def terms(db: Session) -> list[str]:
    profile = db.get(CompanyProfile, 1)
    template = (
        db.get(TcTemplate, profile.po_tc_template_id)
        if profile and profile.po_tc_template_id
        else None
    )
    if template is None:
        return DEFAULT_TERMS
    return [tc.clause.text for tc in template.clauses]


def html_document(db: Session, po: PurchaseOrder) -> str:
    c = company(db)
    gstin = db.get(CompanyGstin, po.from_gstin_id) if po.from_gstin_id else None
    store = db.get(Store, po.store_id)
    site = db.get(Site, store.site_id) if store.site_id else None
    indent_codes = list(
        db.scalars(
            select(Indent.code)
            .join(PoIndent, PoIndent.indent_id == Indent.id)
            .where(PoIndent.po_id == po.id)
            .order_by(Indent.code)
        )
    )
    v = po.vendor
    logo = ""
    if c.logo:
        mime = "image/png" if c.logo.suffix.lower() == ".png" else "image/jpeg"
        logo = f'<img src="data:{mime};base64,{base64.b64encode(c.logo.read_bytes()).decode()}">'
    rows = []
    for i, ln in enumerate(po.lines, start=1):
        tax = Decimal(ln.amount) * Decimal(ln.gst_percent) / 100
        rows.append(
            f"<tr><td>{i}</td><td>{_e(ln.product.name)}<br><small>{_e(ln.product.code)}"
            f"</small></td><td class='num'>{_e(_num(ln.qty))}</td><td>{_e(ln.unit)}</td>"
            f"<td class='num'>{_e(inr(ln.rate))}</td>"
            f"<td class='num'>{_e(_num(ln.discount_percent, 2))}%</td>"
            f"<td class='num'>{_e(inr(ln.amount))}</td>"
            f"<td class='num'>{_e(_num(ln.gst_percent, 2))}%</td>"
            f"<td class='num'>{_e(inr(Decimal(ln.amount) + tax))}</td></tr>"
        )

    def charge_label(ch) -> str:
        text = ch.description or ch.kind.title()
        return text if text.casefold() == ch.kind else f"{text} ({ch.kind})"

    charges = "".join(
        f"<tr><td colspan='6'>{_e(charge_label(ch))}</td>"
        f"<td class='num'>{_e(inr(ch.amount))}</td><td class='num'>{_e(_num(ch.gst_percent, 2))}%"
        f"</td><td class='num'>{_e(inr(Decimal(ch.amount) * (1 + Decimal(ch.gst_percent) / 100)))}"
        "</td></tr>"
        for ch in po.charges
    )
    if po.interstate:
        tax_rows = f"<tr><td>IGST</td><td class='num'>{_e(inr(po.igst))}</td></tr>"
    else:
        tax_rows = (
            f"<tr><td>CGST</td><td class='num'>{_e(inr(po.cgst))}</td></tr>"
            f"<tr><td>SGST</td><td class='num'>{_e(inr(po.sgst))}</td></tr>"
        )
    discount = (
        f"<tr><td>Less discount</td><td class='num'>-{_e(inr(po.discount_total))}</td>" "</tr>"
        if po.discount_total
        else ""
    )
    tc = "".join(
        f'<div class="tc"><span class="no">{i}.</span><span>{_e(t)}</span></div>'
        for i, t in enumerate(terms(db), start=1)
    )
    deliver = ", ".join(
        p
        for p in (
            store.name,
            store.address or (site.address if site else None),
            site.city if site else None,
        )
        if p
    )
    vendor_addr = ", ".join(p for p in (v.address, v.city, v.state) if p)
    if gstin:
        our_gstin = f"GSTIN: {gstin.gstin} ({gstin.state})"
    else:
        our_gstin = f"GSTIN: {c.gstin}" if c.gstin else ""
    expected = f"{po.expected_delivery:%d-%m-%Y}" if po.expected_delivery else "—"
    site_line = f"<br><b>Site:</b> {_e(site.code)} {_e(site.name)}" if site else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="head">{logo}<div><h1>{_e(c.name)}</h1>
<div>{_e(gstin.address if gstin else c.address)}</div>
<div>{_e(our_gstin)}</div></div></div>
<div class="title">PURCHASE ORDER</div>
<div class="boxes">
<div class="box"><h3>Supplier</h3><b>{_e(v.name)}</b><br>{_e(vendor_addr)}<br>
{_e(f"GSTIN: {v.gstin}" if v.gstin else "GSTIN: unregistered")}</div>
<div class="box"><h3>Order</h3><b>PO no:</b> {_e(po.code)}<br>
<b>Date:</b> {po.po_date:%d-%m-%Y}<br>
<b>Expected delivery:</b> {_e(expected)}<br>
<b>Indent:</b> {_e(", ".join(indent_codes) or "—")}<br>
<b>Supply:</b> {"Inter-state (IGST)" if po.interstate else "Intra-state (CGST + SGST)"}</div>
<div class="box"><h3>Deliver to</h3>{_e(deliver)}{site_line}</div>
</div>
<table><thead><tr><th>#</th><th>Item</th><th class="num">Qty</th><th>Unit</th>
<th class="num">Rate</th><th class="num">Disc</th><th class="num">Taxable</th>
<th class="num">GST</th><th class="num">Amount</th></tr></thead>
<tbody>{"".join(rows)}{charges}</tbody></table>
<table class="totals">
<tr><td>Sub total</td><td class="num">{_e(inr(po.subtotal))}</td></tr>{discount}
<tr><td>Taxable value</td><td class="num">{_e(inr(po.taxable))}</td></tr>
<tr><td>Charges</td><td class="num">{_e(inr(po.charges_total))}</td></tr>{tax_rows}
<tr><td>Round off</td><td class="num">{_e(inr(po.round_off))}</td></tr>
<tr class="grand"><td>Grand total</td><td class="num">{_e(inr(po.grand_total))}</td></tr>
</table>
<div class="words">{_e(in_words(po.grand_total))}</div>
<h2>Payment terms</h2><div>{_e(po.payment_terms or "As agreed")}</div>
{f"<h2>Remarks</h2><div>{_e(po.remark)}</div>" if po.remark else ""}
<h2>Terms &amp; Conditions</h2>{tc}
<div class="sign">
<div><b>Supplier's acceptance</b><div class="line">Signature &amp; stamp</div></div>
<div><b>For {_e(c.name)}</b><div class="line">Authorised signatory</div></div></div>
</body></html>"""


def pdf(db: Session, po: PurchaseOrder) -> bytes:
    from weasyprint import HTML

    return HTML(string=html_document(db, po)).write_pdf()
