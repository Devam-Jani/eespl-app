# ruff: noqa: E501
"""The estimate as the planning team lays it out: a sheet per material (its areas, each with floor,
periphery × upturn, coverage, wastage, quantity), then the materials per area, then the summary
(material, quantity, unit, packs), signed "Planning". The PDF carries the same tables. Figures are
the app's own (the same numbers as the page), at 3 decimals; packs are rounded up on the total."""

import io
from datetime import date
from decimal import Decimal
from html import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.estimate import library as lib
from app.estimate import service as svc
from app.estimate.models import Estimate

D = Decimal
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="DDEBE7")
WARN = PatternFill("solid", fgColor="FFF4D6")


def _q(v: Decimal | None) -> float | None:
    return float(D(v).quantize(D("0.001"))) if v is not None else None


def _title(lo: svc.LineOut) -> str:
    t = lo.product.name + (f" ({lo.system})" if lo.system else "")
    if lo.line.mix_design_id and lo.line.thickness_mm:
        t += f", {lib.n(lo.line.thickness_mm, 1)} mm"
    return t


def _sheet_name(text: str, used: set[str]) -> str:
    base = "".join(ch for ch in text if ch not in "[]:*?/\\")[:28] or "Material"
    name, i = base, 2
    while name.lower() in used:
        name = f"{base[:26]} {i}"
        i += 1
    used.add(name.lower())
    return name


def workbook(db: Session, est: Estimate, site_name: str | None) -> bytes:
    lines = svc.worked(db, est)
    areas = [a for a in svc.areas_of(db, est) if a.included]
    missed = svc.missed(db, est)
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for lo in lines:
        ws = wb.create_sheet(_sheet_name(lo.product.name, used))
        ws.append([f"{est.code} {est.title}" + (f": {site_name}" if site_name else "")])
        ws.append([_title(lo)])
        ws.append([f"Coverage {lo.cov.shown if lo.cov else 'NOT IN THE LIBRARY'}; wastage {lib.n(lo.wastage, 2)}% (on every line, not inside the coverage)"])
        ws.append([])
        ws.append(["Area", "Floor (sqm)", "Periphery (m)", "Upturn (sqm)", "Area counted (sqm)", f"Coverage ({lo.product.unit}/sqm)", "Wastage %", f"Quantity ({lo.product.unit})", "Working"])
        for c in ws[5]:
            c.font, c.fill = BOLD, HEAD
        for r in lo.rows:
            a = next((x for x in areas if x.id == r.area_id), None)
            ws.append([f"{r.code + ' ' if r.code else ''}{r.name}", _q(r.floor_sqm), _q(a.periphery_m) if a else None, _q(r.upturn_sqm), _q(r.base_sqm),
                       float(D(lo.cov.per_sqm).quantize(D("0.0001"))) if lo.cov else None, float(lo.wastage), _q(r.qty), r.formula])  # fmt: skip
        ws.append(["Total", _q(sum((r.floor_sqm for r in lo.rows), D(0))), None, _q(sum((r.upturn_sqm for r in lo.rows), D(0))), _q(sum((r.base_sqm for r in lo.rows), D(0))),
                   None, None, _q(lo.qty), lo.packs.text if lo.packs else ""])  # fmt: skip
        for c in ws[ws.max_row]:
            c.font = BOLD
        _widths(ws, [34, 12, 13, 12, 16, 16, 10, 16, 70])
    ws = wb.create_sheet("Per area")
    ws.append([f"{est.code}: materials per area"])
    ws.append(["Area", "Included", *[_title(lo) for lo in lines]])
    for c in ws[2]:
        c.font, c.fill = BOLD, HEAD
        c.alignment = Alignment(wrap_text=True)
    for a in svc.areas_of(db, est):
        vals = []
        for lo in lines:
            r = next((x for x in lo.rows if x.area_id == a.id), None)
            vals.append(_q(r.qty) if r else None)
        ws.append([f"{a.code + ' ' if a.code else ''}{a.name}", "yes" if a.included else f"no: {a.excluded_reason}", *vals])
    _widths(ws, [40, 22, *[18] * len(lines)])
    ws = wb.create_sheet("Summary")
    ws.append([f"{est.code} {est.title}" + (f": {site_name}" if site_name else "")])
    ws.append([f"Material estimate, {date.today():%d.%m.%Y}"])
    ws.append([])
    ws.append(["Material", "Quantity", "Unit", "Packs"])
    for c in ws[4]:
        c.font, c.fill = BOLD, HEAD
    for row in svc.summary(db, est):
        ws.append([row["product"] + ("" if row["complete"] else " (no coverage: not complete)"), _q(row["qty"]), row["unit"], row["packs"] or ""])
    ws.append([])
    if missed:
        ws.append([f"Warning: {len(missed)} measured area(s) not in this estimate and not excluded: " + "; ".join(f"{m.name} {lib.n(m.floor_sqm)} sqm" for m in missed)])
        ws.cell(ws.max_row, 1).fill = WARN
    ws.append([])
    ws.append(["Prepared by: Planning"])
    ws.cell(ws.max_row, 1).font = BOLD
    _widths(ws, [46, 14, 8, 26])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def html(db: Session, est: Estimate, site_name: str | None) -> str:
    lines = svc.worked(db, est)
    missed = svc.missed(db, est)
    parts = [f"""<html><head><meta charset="utf-8"><style>
@page {{ size: A4 landscape; margin: 12mm; @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #666; }} }}
body {{ font-family: DejaVu Sans, sans-serif; font-size: 8.5pt; color: #1c2b28; }} h1 {{ font-size: 14pt; margin: 0 0 2px; }}
h2 {{ font-size: 11pt; margin: 12px 0 3px; border-bottom: 2px solid #0f6b5c; page-break-after: avoid; }} .muted {{ color: #64736f; }}
table {{ width: 100%; border-collapse: collapse; }} th {{ background: #ddebe7; text-align: left; padding: 3px 4px; }}
td {{ border-bottom: 1px solid #e1e6e4; padding: 2px 4px; vertical-align: top; }} td.n {{ text-align: right; white-space: nowrap; }}
tr.total td {{ font-weight: bold; border-top: 1px solid #1c2b28; }} .warn {{ background: #fff4d6; padding: 4px 6px; margin: 6px 0; }}
</style></head><body><h1>{escape(est.code)} {escape(est.title)}</h1>
<p class="muted">{escape(site_name or '')} · Material estimate, {date.today():%d.%m.%Y} · quantities = area × coverage × (1 + wastage), packs rounded up</p>"""]
    if missed:
        parts.append(f'<div class="warn"><b>{len(missed)} measured area(s) not in this estimate and not excluded:</b> ' + escape("; ".join(f"{m.name} {lib.n(m.floor_sqm)} sqm" for m in missed)) + "</div>")
    for lo in lines:
        parts.append(f"<h2>{escape(_title(lo))}</h2><p class='muted'>Coverage {escape(lo.cov.shown if lo.cov else 'not in the library')}; wastage {lib.n(lo.wastage, 2)}%</p>")
        parts.append("<table><tr><th>Area</th><th>Floor sqm</th><th>Upturn sqm</th><th>Counted sqm</th><th>Quantity</th><th>Working</th></tr>")
        for r in lo.rows:
            parts.append(f"<tr><td>{escape((r.code + ' ' if r.code else '') + r.name)}</td><td class='n'>{lib.n(r.floor_sqm)}</td><td class='n'>{lib.n(r.upturn_sqm)}</td>"
                         f"<td class='n'>{lib.n(r.base_sqm)}</td><td class='n'>{lib.n(r.qty) if r.qty is not None else '—'} {escape(lo.product.unit)}</td><td class='muted'>{escape(r.formula)}</td></tr>")  # fmt: skip
        parts.append(f"<tr class='total'><td>Total</td><td></td><td></td><td></td><td class='n'>{lib.n(lo.qty) if lo.qty is not None else '—'} {escape(lo.product.unit)}</td>"
                     f"<td>{escape(lo.packs.text if lo.packs else '')}</td></tr></table>")  # fmt: skip
    parts.append("<h2>Summary</h2><table><tr><th>Material</th><th>Quantity</th><th>Unit</th><th>Packs</th></tr>")
    for row in svc.summary(db, est):
        parts.append(f"<tr><td>{escape(row['product'])}{'' if row['complete'] else ' (no coverage: not complete)'}</td><td class='n'>{lib.grouped(row['qty'], 3)}</td>"
                     f"<td>{escape(row['unit'])}</td><td>{escape(row['packs'] or '')}</td></tr>")  # fmt: skip
    parts.append("</table><p style='margin-top:24px'><b>Prepared by: Planning</b></p></body></html>")
    return "".join(parts)


def pdf(db: Session, est: Estimate, site_name: str | None) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415

    return HTML(string=html(db, est, site_name)).write_pdf()
