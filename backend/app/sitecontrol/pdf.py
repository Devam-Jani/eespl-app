# ruff: noqa: E501  (HTML reads better unwrapped)
"""The delivery note PDF the driver carries (EESPL format): items in packs and base units (no
rates), the site, the expected time, the named receiver, a QR code and the short receipt link."""

import base64
from decimal import Decimal
from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.masters.models import Product
from app.sitecontrol.models import DeliveryNote
from app.sites.models import Site
from app.tenders.export import company


def qr_svg(text: str, size: int = 160) -> str:
    """A QR code as SVG (reportlab's encoder, no extra library)."""
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    w = QrCodeWidget(text, barLevel="M")
    x0, y0, x1, y1 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    return renderSVG.drawToString(d)


def qty(v) -> str:
    """360.000 -> "360", 2.500 -> "2.5" (a whole number keeps its own zeros)."""
    return f"{Decimal(v).normalize():f}"


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def html(db: Session, dn: DeliveryNote, raw: str) -> str:
    from app.sitecontrol.deliveries import receipt_url, vendor_name  # noqa: PLC0415

    c = company(db)
    site = db.get(Site, dn.site_id)
    url = receipt_url(raw)
    logo = ""
    if c.logo:
        logo = f'<img class="logo" src="data:image/{c.logo.suffix.lstrip(".")};base64,{base64.b64encode(c.logo.read_bytes()).decode()}" alt="">'
    rows = "".join(
        f"<tr><td>{i}</td><td>{escape(db.get(Product, ln.product_id).name)}</td>"
        f'<td class="num">{qty(ln.packs) + " " + escape(ln.pack_unit or "") if ln.packs is not None else "—"}</td>'
        f'<td class="num">{qty(ln.qty)} {escape(ln.unit)}</td><td class="count"></td></tr>'
        for i, ln in enumerate(dn.lines, 1)
    )
    receiver = escape(site.receiver_name or "—") + (
        f" ({escape(site.receiver_phone)})" if site.receiver_phone else ""
    )
    source = (
        f"PO delivery from {escape(vendor_name(db, dn) or '')}"
        if dn.kind == "po"
        else "From the godown"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 14mm 14mm 16mm; @bottom-right {{ content: "{escape(dn.code)} · Page " counter(page) " of " counter(pages); font-size: 8pt; color: #555; }} }}
body {{ font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10pt; color: #111; }}
.head {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #0F6E5A; padding-bottom: 6px; }}
.logo {{ max-height: 16mm; max-width: 60mm; }}
.company {{ font-weight: bold; color: #0F6E5A; font-size: 12pt; }}
h1 {{ font-size: 15pt; margin: 10px 0 2px; }}
.grid {{ display: flex; gap: 14px; margin-top: 8px; }}
.facts {{ flex: 1; }} .facts p {{ margin: 2px 0; }}
.qr {{ width: 52mm; text-align: center; border: 1px solid #ccc; padding: 6px; }}
.qr img {{ width: 44mm; height: 44mm; }}
.link {{ font-size: 7.5pt; word-break: break-all; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
th, td {{ border: 1px solid #777; padding: 5px; }} th {{ background: #eef3f1; text-align: left; }}
td.num {{ text-align: right; white-space: nowrap; }} td.count {{ width: 30mm; }}
.how {{ margin-top: 10px; font-size: 9pt; border: 1px dashed #999; padding: 6px; }}
.sign {{ margin-top: 18px; display: flex; justify-content: space-between; }}
.small {{ font-size: 8pt; color: #555; }}
</style></head><body>
<div class="head"><div>{logo}</div><div class="company">{escape(c.name)}</div></div>
<h1>Delivery note {escape(dn.code)}</h1>
<div class="grid"><div class="facts">
<p><b>Site:</b> {escape(site.name)} ({escape(site.code)}){" · " + escape(site.city) if site.city else ""}</p>
<p><b>{source}</b>{f" · PO {escape(str(dn.po_id))}" if dn.po_id else ""}</p>
<p><b>Expected at site:</b> {dn.expected_at:%d %b %Y, %H:%M}</p>
<p><b>Vehicle:</b> {escape(dn.vehicle_no or "—")} · <b>Driver:</b> {escape(dn.driver_name or "—")} {escape(dn.driver_phone or "")}</p>
<p><b>Who may receive when the supervisor is away:</b> {receiver}</p>
</div><div class="qr"><img src="{_data_uri(qr_svg(url))}" alt="QR"><div class="link">{escape(url)}</div>
<div class="small">Scan at site to count and confirm</div></div></div>
<table><thead><tr><th>#</th><th>Item</th><th>Packs</th><th>Quantity</th><th>Counted at site</th></tr></thead><tbody>{rows}</tbody></table>
<div class="how"><b>At site:</b> scan the QR code, count every item as it is unloaded, note anything damaged, and take two photos (the material as unloaded, and this signed note).
<br>સાઇટ પર: QR સ્કેન કરો, દરેક વસ્તુ ગણો, બે ફોટા લો. · साइट पर: QR स्कैन करें, हर वस्तु गिनें, दो फ़ोटो लें.</div>
<div class="sign"><div>Driver: ____________________</div><div>Received by (name, sign): ____________________</div></div>
<p class="small">The receipt link works until this delivery is confirmed or for 7 days. It shows only this delivery's items and counts.</p>
</body></html>"""


def render(db: Session, dn: DeliveryNote, raw: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html(db, dn, raw)).write_pdf()


def save(db: Session, dn: DeliveryNote, raw: str) -> str:
    """Kept with the delivery (the raw token exists only in this file and the outbox)."""
    rel = f"deliveries/{dn.code}.pdf"
    p = Path(app_settings.media_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(render(db, dn, raw))
    return rel
