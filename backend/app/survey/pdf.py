# ruff: noqa: E501  (HTML templates read better unwrapped)
"""Survey PDFs in the EESPL format, and the printable marker sheet for the measuring camera."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution.common import media
from app.execution.pdf import CSS, _doc, _img, e
from app.masters.models import ProductPrice
from app.survey import service as svc
from app.survey.models import CAMERA_METHODS, AreaType, Survey
from app.tenders.export import company, inr

# ARUCO_MIP_36h12 codes 0 to 3: the dictionary js-aruco2 detects by default. 36 bits, row by
# row over a 6 x 6 grid; a 1 is a white cell. The marker is that grid inside a one-cell black
# border (8 x 8 cells). Ids 0 and 1 are the A4 pair (150 mm across the black square), ids 2 and
# 3 the A3 pair (250 mm): the app tells the size from the ids.
MARKER_CODES = {0: 0xD2B63A09D, 1: 0x6001134E5, 2: 0x1206FBE72, 3: 0xFF8AD6CB4}
MARKER_MM = 150
SHEETS = {
    # ids, black square mm, white quiet zone in cells, page
    "a4": ((0, 1), 150, 1.0, "A4", 210, 297),
    "a3": ((2, 3), 250, 0.5, "A3", 297, 420),
}


def marker_bits(marker_id: int) -> list[list[int]]:
    bits = format(MARKER_CODES[marker_id], "036b")
    return [[int(bits[r * 6 + c]) for c in range(6)] for r in range(6)]


def marker_svg(marker_id: int, mm: int = MARKER_MM, quiet: float = 1.0) -> str:
    """The marker, exactly `mm` across the black square, with its white quiet zone."""
    q = quiet
    cells = "".join(
        f'<rect x="{c + 1 + q}" y="{r + 1 + q}" width="1.002" height="1.002" fill="#fff"/>'
        for r, row in enumerate(marker_bits(marker_id))
        for c, bit in enumerate(row)
        if bit
    )
    cell = mm / 8
    n = 8 + 2 * q
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{cell * n}mm" height="{cell * n}mm" viewBox="0 0 {n} {n}">'
        f'<rect x="0" y="0" width="{n}" height="{n}" fill="#fff"/><rect x="{q}" y="{q}" width="8" height="8" fill="#000"/>{cells}</svg>'
    )


def ruler_svg() -> str:
    ticks = "".join(
        f'<line x1="{i}" y1="0" x2="{i}" y2="{6 if i % 10 == 0 else 3}" stroke="#000" stroke-width="0.2"/>'
        for i in range(0, 101)
    )
    labels = "".join(
        f'<text x="{i}" y="10" font-size="3" text-anchor="middle">{i // 10}</text>'
        for i in range(0, 101, 10)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="104mm" height="12mm" viewBox="-2 -1 104 12">'
        f'<line x1="0" y1="0" x2="100" y2="0" stroke="#000" stroke-width="0.3"/>{ticks}{labels}</svg>'
    )


def marker_sheet(db: Session, size: str = "a4") -> bytes:
    """Two pages, one marker each: A4 with 150 mm markers, or A3 with 250 mm markers (frames
    about 2.5 m across at the 10 % limit). Two markers never fit on one page with their margins,
    and the pages may be laid at any spacing: the app works out where the second one lies."""
    from weasyprint import HTML

    ids, mm, quiet, page, page_w, page_h = SHEETS[size]
    c = company(db)
    pages = []
    for n, marker_id in enumerate(ids, start=1):
        pages.append(f"""<section class="sheet">
<div class="top"><b>{e(c.name)}</b> · measuring camera marker {n} of 2 ({page}, {mm} mm)</div>
<div class="warn">PRINT AT 100% (ACTUAL SIZE). DO NOT SCALE OR "FIT TO PAGE".</div>
<div class="marker">{marker_svg(marker_id, mm, quiet)}</div>
<div class="check">The black square must measure exactly {mm} mm. Print check: the ruler below must measure exactly 100 mm (0 to 10 cm).</div>
<div class="ruler">{ruler_svg()}</div>
<div class="how">Lay both sheets flat on the surface you measure, a little apart, at any angle, fully in the photo. Keep them clean and uncreased.</div>
</section>""")
    css = (
        f"""@page {{ size: {page}; margin: 0; }} .sheet {{ width: {page_w}mm; height: {page_h}mm; }}
"""
        + """body { margin: 0; font-family: "DejaVu Sans", sans-serif; }
.sheet { page-break-after: always; text-align: center; box-sizing: border-box; padding-top: 14mm; }
.sheet:last-child { page-break-after: auto; } .top { font-size: 10pt; } .warn { font-size: 11pt; font-weight: bold; margin: 5mm 0 6mm; }
.marker { display: flex; justify-content: center; } .marker svg { display: block; }
.check { font-size: 9pt; margin: 6mm 20mm 3mm; } .ruler { display: flex; justify-content: center; } .how { font-size: 9pt; margin: 6mm 20mm; color: #444; }"""
    )
    return HTML(
        string=f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(pages)}</body></html>"
    ).write_pdf()


def size_text(a) -> str:
    if a.shape == "rect":
        return f"{Decimal(a.length_m or 0):.2f} × {Decimal(a.width_m or 0):.2f} m"
    if a.shape == "polygon":
        return f"polygon, {len(a.polygon_m or [])} corners"
    return f"{Decimal(a.direct_area_sqm or 0):.2f} sqm"


def method_text(a) -> str:
    if a.method in CAMERA_METHODS:
        return f"camera measured ({'AR' if a.method == 'ar' else 'marker photo'})"
    return a.method


def survey_pdf(db: Session, s: Survey, parent: str, include_rates: bool) -> bytes:
    types = {t.id: t.name for t in db.scalars(select(AreaType))}
    rows, thumbs = [], []
    for a in s.areas:
        extra = []
        if Decimal(a.upturn_area_sqm):
            extra.append(f"upturn {Decimal(a.upturn_mm):.0f} mm")
        if Decimal(a.wall_area_sqm):
            extra.append(f"walls {Decimal(a.wall_height_m or 0):.2f} m")
        if Decimal(a.sunk_area_sqm):
            extra.append(f"sunk {Decimal(a.sunk_depth_mm or 0):.0f} mm")
        rows.append(
            f"<tr><td>{e(a.tower or '')} {e(a.floor_label or '')}</td><td>{e(a.name)}</td><td>{e(types.get(a.area_type_id, ''))}</td>"
            f"<td>{e(size_text(a))}{' − ' + format(Decimal(a.deductions_sqm), '.2f') + ' sqm' if Decimal(a.deductions_sqm or 0) else ''}</td>"
            f"<td>{e(', '.join(extra))}</td><td class='num'>{a.count}</td><td class='num'>{Decimal(a.treated_area_sqm):,.2f}</td><td>{e(method_text(a))}</td></tr>"
        )
        for p in a.photos[:1]:
            img = _img(media(p.overlay_path or p.stored_path), a.name)
            if img:
                thumbs.append(f"<figure>{img}<figcaption>{e(a.name)}</figcaption></figure>")
    c = svc.consumption(db, list(s.areas))
    total = svc.packs(db, c.products)
    rates = {}
    if include_rates:
        for pid in c.products:
            price = db.scalar(
                select(ProductPrice)
                .where(ProductPrice.product_id == pid)
                .order_by(ProductPrice.effective_from.desc())
                .limit(1)
            )
            if price:
                rates[pid] = Decimal(price.purchase_rate) + Decimal(price.freight_per_unit or 0)
    names = {r["product_id"]: r for r in total}
    floor_blocks = []
    for (tower, _n, label), prods in sorted(c.by_floor.items()):
        lines = "".join(
            f"<tr><td>{e(names[pid]['name'])}</td><td class='num'>{svc.q3(q):,.3f} {e(names[pid]['unit'])}</td></tr>"
            for pid, q in sorted(prods.items(), key=lambda kv: names.get(kv[0], {}).get("name", ""))
            if pid in names
        )
        floor_blocks.append(
            f"<div class='floor'><h3>{e(tower)} {e(label) or '(no floor)'}</h3><table><tbody>{lines}</tbody></table></div>"
        )
    total_rows = "".join(
        f"<tr><td>{e(r['name'])}</td><td class='num'>{r['qty']:,.3f} {e(r['unit'])}</td>"
        f"<td class='num'>{f'{r['packs']} × {r['pack_size']:g} {e(r['unit'])} {e(r['pack_unit'] or 'pack')}' if r['packs'] is not None else '—'}</td>"
        + (
            f"<td class='num'>{inr(rates[r['product_id']])}</td><td class='num'>{inr((r['pack_qty'] or r['qty']) * rates[r['product_id']])}</td>"
            if include_rates and r["product_id"] in rates
            else ("<td></td><td></td>" if include_rates else "")
        )
        + "</tr>"
        for r in total
    )
    rate_head = "<th class='num'>Rate</th><th class='num'>Amount</th>" if include_rates else ""
    no_sys = (
        f"<p class='muted'>{len(c.no_system)} area(s) have no system yet and are not in the product totals.</p>"
        if c.no_system
        else ""
    )
    treated = sum((Decimal(a.treated_area_sqm) for a in s.areas), Decimal(0))
    body = f"""
<div class="meta"><div><b>Survey:</b> {e(s.code)} · {e(s.title)}</div><div><b>For:</b> {e(parent)}</div>
<div><b>Surveyed on:</b> {s.surveyed_on.strftime('%d %b %Y') if s.surveyed_on else '—'}</div><div><b>Status:</b> {e(s.status)} · treated area {treated:,.2f} sqm</div></div>
<h2>Areas</h2><table><thead><tr><th>Where</th><th>Area</th><th>Type</th><th>Size</th><th>Sides</th><th class='num'>Count</th><th class='num'>Treated sqm</th><th>Method</th></tr></thead>
<tbody>{''.join(rows) or "<tr><td colspan='8' class='muted'>No areas.</td></tr>"}</tbody></table>
{('<h2>Photos</h2><div class="photos">' + ''.join(thumbs[:24]) + '</div>') if thumbs else ''}
<h2>Products, whole survey</h2>{no_sys}<table><thead><tr><th>Product</th><th class='num'>Quantity</th><th class='num'>Packs</th>{rate_head}</tr></thead><tbody>{total_rows or "<tr><td colspan='3' class='muted'>No products: pick a system for the areas.</td></tr>"}</tbody></table>
<p class="muted">Packs are rounded up on the survey total only, never per area. Wastage: the area's own, else its area type's, else the system's.</p>
<h2>Products by floor</h2><div class="floors">{''.join(floor_blocks)}</div>"""
    style = "<style>.floors { display: flex; flex-wrap: wrap; gap: 6px; } .floor { width: 32%; } .floor h3 { font-size: 8.5pt; margin: 4px 0 2px; }</style>"
    return _doc(db, "SITE SURVEY", style + body)


__all__ = ["CSS"]
