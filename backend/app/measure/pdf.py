# ruff: noqa: E501  (HTML templates read better unwrapped)
"""The measurement sheet and the proforma invoice as PDFs."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.execution.pdf import _doc, e
from app.material.po_pdf import in_words
from app.measure import geom
from app.tenders.export import inr

CSS = """<style>@page { size: A4 landscape; }
td.desc { width: 40%; } tr.area td { font-weight: bold; background: #eef3ef; }
tr.ded td { color: #9b2c2c; } .why { font-size: 7pt; color: #555; } .num { text-align: right; }
.box { border: 0.6px solid #999; padding: 5px 6px; } .meta { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.meta h3 { margin: 0 0 3px; font-size: 8pt; color: #2f6f4f; text-transform: uppercase; } .warn { color: #9b2c2c; }</style>"""


def _n(v, places: int = 4) -> str:
    if v is None or v == "":
        return ""
    q = Decimal(v).quantize(Decimal(1).scaleb(-places))
    return f"{q:f}"


def sheet(db: Session, out: dict) -> bytes:
    rows = []
    for ln in out["lines"]:
        if ln["kind"] == "area":
            rows.append(f"<tr class='area'><td></td><td colspan='8'>{e(ln['particulars'])}</td></tr>")
            continue
        if ln["kind"] == "not_done":
            rows.append(f"<tr><td>{e(ln.get('item_no') or '')}</td><td class='desc'>{e(ln['particulars'])}</td><td colspan='5'></td><td class='num'>–</td><td>{e(ln.get('unit') or '')}</td></tr>")
            continue
        why = f"<div class='why'>{e(ln.get('reason') or ln.get('formula') or '')}</div>"
        rows.append(f"<tr class='{'ded' if ln['kind'] == 'deduction' else ''}'><td>{e(ln.get('item_no') or '')}</td><td class='desc'>{e(ln['particulars'])}{why}</td>"
                    f"<td class='num'>{_n(ln.get('no'), 0)}</td><td class='num'>{_n(ln.get('length_m'), 3)}</td><td class='num'>{_n(ln.get('width_m'), 3)}</td>"
                    f"<td class='num'>{_n(ln.get('height_m'), 3)}</td><td class='num'>{_n(ln.get('qty'))}</td><td class='num'>{_n(ln.get('total'), 3)}</td><td>{e(ln.get('unit') or '')}</td></tr>")  # fmt: skip
    ab = "".join(
        f"<tr><td>{e(r['item_no'] or '')}</td><td class='desc'>{e((r['description'] or '')[:160])}</td><td>{e(r['unit'] or '')}</td><td class='num'>{_n(r['previous'], 3)}</td>"
        f"<td class='num'>{_n(r['drawing'], 3)}</td><td class='num'>{_n(r['approved'], 3) if r.get('approved') is not None else '—'}</td>"
        f"<td class='num'><b>{_n(r['this'], 3)}</b></td><td class='num'>{_n(r['upto'], 3)}</td><td class='num'>{_n(r['wo_qty'], 3)}</td></tr>"
        + (f"<tr><td></td><td colspan='8' class='why'>{e(r['note'])}</td></tr>" if r.get("note") else "")
        for r in out["cumulative"]
    )
    body = f"""{CSS}<div class="meta"><div class="box"><h3>Sheet</h3><b>{e(out["code"])}</b><br>Measured on {out["measured_on"]:%d-%m-%Y}<br>Status: {e(out["status"])}</div>
<div class="box"><h3>Site</h3>{e(out["site_code"])} · {e(out["site_name"])}</div>
<div class="box"><h3>Units</h3>1 sqm = {geom.SQFT_PER_SQM} sqft · sizes in metres · each total rounded to 3 decimals</div></div>
<table><thead><tr><th>Sr / WO item</th><th>Particulars</th><th class="num">No</th><th class="num">Length</th><th class="num">Width</th><th class="num">Height / Depth</th>
<th class="num">Qty</th><th class="num">Total qty</th><th>Unit</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<h3>Abstract</h3><table><thead><tr><th>WO item</th><th>Description</th><th>Unit</th><th class="num">Previous</th><th class="num">On the drawing</th><th class="num">Approved by the client</th><th class="num">This bill</th><th class="num">Up to date</th><th class="num">WO qty</th></tr></thead>
<tbody>{ab}</tbody></table>
<div class="sign"><div><b>Measured by</b><div class="line">Billing</div></div><div><b>Checked by the client</b><div class="line"></div></div></div>"""
    return _doc(db, "MEASUREMENT SHEET", body)


def proforma(db: Session, p: dict) -> bytes:
    t = p["tax"]
    b = p["buyer"]
    rows = "".join(
        f"<tr><td>{e(ln['item_no'] or n)}</td><td class='desc'>{e(ln['description'])}</td><td>{e(ln['sac'] or '')}</td><td>{e(ln['unit'])}</td>"
        f"<td class='num'>{_n(ln['previous'], 3)}</td><td class='num'>{_n(ln['this'], 3)}</td><td class='num'>{_n(ln['cumulative'], 3)}</td>"
        f"<td class='num'>{e(inr(ln['rate']))}</td><td class='num'>{e(inr(ln['amount']))}</td></tr>"
        for n, ln in enumerate(p["lines"], start=1)
    )
    taxes = (f"<tr><td>IGST {_n(t['igst_percent'], 0)}%</td><td class='num'>{e(inr(t['igst']))}</td></tr>" if t["interstate"]
             else f"<tr><td>CGST {_n(t['cgst_percent'], 1)}%</td><td class='num'>{e(inr(t['cgst']))}</td></tr><tr><td>SGST {_n(t['sgst_percent'], 1)}%</td><td class='num'>{e(inr(t['sgst']))}</td></tr>")  # fmt: skip
    warn = "".join(f"<p class='warn'>{e(w)}</p>" for w in p["warnings"])
    body = f"""{CSS}<div class="meta"><div class="box"><h3>Proforma</h3><b>{e(p["proforma_no"])}</b><br>Date {p["proforma_on"]:%d-%m-%Y}<br>{e(p["code"])}</div>
<div class="box"><h3>Buyer</h3><b>{e(b["name"] or "")}</b><br>{e(b["address"] or "")}<br>{e(", ".join(x for x in (b["city"], b["state"]) if x))}<br>GSTIN {e(b["gstin"] or "—")}</div>
<div class="box"><h3>Order / site</h3>{e(p["order"]["text"])}<br>{e(p["site"]["code"])} · {e(p["site"]["name"])}<br>Our GSTIN {e(t["our_gstin"] or "—")}</div></div>{warn}
<table><thead><tr><th>Item</th><th>Description</th><th>SAC</th><th>Unit</th><th class="num">Previous</th><th class="num">This bill</th><th class="num">Cumulative</th>
<th class="num">Rate</th><th class="num">Amount</th></tr></thead><tbody>{rows}</tbody></table>
<table class="totals"><tr><td>Basic (taxable)</td><td class="num">{e(inr(t["taxable"]))}</td></tr>{taxes}
<tr><td>Round off</td><td class="num">{e(inr(t["round_off"]))}</td></tr><tr><td><b>Grand total</b></td><td class="num"><b>{e(inr(t["total"]))}</b></td></tr></table>
<p><i>{e(in_words(t["total"]))}</i></p>"""
    return _doc(db, "PROFORMA INVOICE", body)
