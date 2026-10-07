# ruff: noqa: E501  (HTML templates read better unwrapped)
"""PDFs in the EESPL format: daily progress report, work order, inspection, minutes of meeting."""

import base64
import html
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.execution.common import media
from app.execution.models import Dpr, Inspection, WorkOrder
from app.masters.models import TcTemplate
from app.sites.models import Site
from app.tenders.export import company, inr

CSS = """
@page { size: A4; margin: 12mm 11mm 14mm;
  @bottom-center { content: "Page " counter(page) " of " counter(pages); font-family: "DejaVu Sans";
    font-size: 7.5pt; color: #555; } }
body { font-family: "DejaVu Sans", sans-serif; font-size: 8.5pt; color: #111; }
.head { display: flex; gap: 12px; align-items: center; border-bottom: 1.5px solid #2f6f4f; padding-bottom: 6px; }
.head img { height: 44px; }
.head h1 { font-size: 13pt; margin: 0; }
.title { text-align: center; font-size: 12pt; font-weight: bold; letter-spacing: 1px; margin: 8px 0 6px; }
.meta { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 24px; margin-bottom: 8px; }
h2 { font-size: 9.5pt; margin: 10px 0 4px; color: #2f6f4f; }
table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group; }
th { background: #dce6e0; text-align: left; }
th, td { border: 0.6px solid #999; padding: 3px 4px; vertical-align: top; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr { page-break-inside: avoid; }
.pre { white-space: pre-line; }
.muted { color: #555; }
.pass { color: #1d7a3d; font-weight: bold; } .fail { color: #b00000; font-weight: bold; }
.photos { display: flex; flex-wrap: wrap; gap: 6px; }
.photos figure { margin: 0; width: 31%; page-break-inside: avoid; }
.photos img { width: 100%; max-height: 150px; object-fit: cover; border: 0.6px solid #999; }
.photos figcaption { font-size: 7pt; color: #555; }
.sign { margin-top: 24px; display: flex; justify-content: space-between; page-break-inside: avoid; }
.sign .line { margin-top: 30px; }
.sign img { height: 50px; display: block; }
.totals { width: 50%; margin-left: auto; margin-top: 6px; }
.totals td { border: none; padding: 2px 4px; }
.tc { display: flex; gap: 6px; margin-bottom: 2px; }
"""

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _img(path: Path | None, alt: str = "") -> str:
    if path is None or not path.exists() or path.suffix.lower() not in IMAGE_TYPES:
        return ""
    data = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:{IMAGE_TYPES[path.suffix.lower()]};base64,{data}" alt="{e(alt)}">'


def _photos(items: list[tuple[str, str]]) -> str:
    """[(relative path, caption)] -> a grid of the images (PDFs and HEIC are listed by name)."""
    figs = []
    for rel, caption in items:
        img = _img(media(rel), caption)
        figs.append(f"<figure>{img or ''}<figcaption>{e(caption)}</figcaption></figure>")
    return (
        f'<div class="photos">{"".join(figs)}</div>' if figs else '<p class="muted">No photos.</p>'
    )


def _doc(db: Session, title: str, body: str) -> bytes:
    from weasyprint import HTML

    c = company(db)
    logo = _img(c.logo) if c.logo else ""
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="head">{logo}<div><h1>{e(c.name)}</h1><div>{e(c.address)}</div>
<div>{e(f"GSTIN: {c.gstin}" if c.gstin else "")}</div></div></div>
<div class="title">{e(title)}</div>{body}</body></html>"""
    return HTML(string=page).write_pdf()


def _site_line(site: Site) -> str:
    return ", ".join(p for p in (site.name, site.city) if p)


# --- DPR -----------------------------------------------------------------------------------------


def dpr(db: Session, site: Site, out: dict, d: Dpr) -> bytes:
    a = out["auto"]
    lab = a["labour"]
    tasks = (
        "".join(
            f"<tr><td>{e(t['where'])}</td><td>{e(t['name'])}</td><td>{e(t['status'].replace('_', ' '))}</td>"
            f"<td class='num'>{t['percent']:.0f}%</td></tr>"
            for t in a["tasks"]
        )
        or "<tr><td colspan='4' class='muted'>No task updates.</td></tr>"
    )
    mat = "".join(
        f"<tr><td>In</td><td>{e(r['code'])}</td><td>{e(r['from'])}</td><td>{e(r['items'])}</td></tr>"
        for r in a["received"]
    )
    mat += "".join(
        f"<tr><td>{'Issued' if r['kind'] == 'issue' else 'Returned'}</td><td>{e(r['code'])}</td>"
        f"<td>{e(r['for'] or 'site')}</td><td>{e(r['items'])}</td></tr>"
        for r in a["issued"]
    )
    mat = mat or "<tr><td colspan='4' class='muted'>No material movement.</td></tr>"
    trades = ", ".join(f"{k} {v}" for k, v in sorted(lab["by_trade"].items())) or "—"
    equip = "".join(
        f"<tr><td>{e(u['asset'])}</td><td class='num'>{e(u['quantity'])} {e(u['basis'])}(s)</td>"
        f"<td>{e(u['operator'] or '')}</td></tr>"
        for u in a["equipment"]
    )
    equip = equip or "<tr><td colspan='3' class='muted'>No equipment used.</td></tr>"
    photos = [(p.stored_path, p.caption or p.filename) for p in d.photos]
    task_photos = []
    from app.sites.models import TaskPhoto

    for t in a["tasks"]:
        for p in t["photos"]:
            tp = db.get(TaskPhoto, p["id"])
            if tp:
                task_photos.append((tp.stored_path, f"{t['where']} · {t['name']}"))
    body = f"""
<div class="meta"><div><b>Site:</b> {e(site.code)} · {e(_site_line(site))}</div><div><b>Date:</b> {d.on_date:%d-%m-%Y}</div>
<div><b>Weather:</b> {e(d.weather or "—")}</div><div><b>Status:</b> {e(d.status)}
{f" · by {e(out['submitted_by_name'])}" if out.get("submitted_by_name") else ""}</div></div>
<h2>Work done</h2><div class="pre">{e(d.work_done or "—")}</div>
<h2>Progress of tasks</h2><table><thead><tr><th>Where</th><th>Step</th><th>Status</th><th class="num">Done</th></tr></thead>
<tbody>{tasks}</tbody></table>
<h2>Labour</h2><div>Present {lab["present"]} · half day {lab["half_day"]} · absent {lab["absent"]} · {e(trades)}</div>
<h2>Material</h2><table><thead><tr><th></th><th>Ref</th><th>From / for</th><th>Items</th></tr></thead><tbody>{mat}</tbody></table>
<h2>Equipment</h2><table><thead><tr><th>Asset</th><th class="num">Used</th><th>Operator</th></tr></thead><tbody>{equip}</tbody></table>
<h2>Hindrances</h2><div class="pre">{e(d.hindrances or "None")}</div>
<h2>Plan for the next day</h2><div class="pre">{e(d.next_day_plan or "—")}</div>
<h2>Photos</h2>{_photos(photos + task_photos[:9])}
<div class="sign"><div><b>Site supervisor</b><div class="line">{e(out.get("submitted_by_name") or "")}</div></div>
<div><b>For {e(company(db).name)}</b><div class="line">Project manager</div></div></div>"""
    return _doc(db, "DAILY PROGRESS REPORT", body)


# --- work order ----------------------------------------------------------------------------------


def work_order(db: Session, wo: WorkOrder, out: dict) -> bytes:
    site = db.get(Site, wo.site_id)
    v = wo.subcontractor
    rows = "".join(
        f"<tr><td>{n}</td><td class='pre'>{e(ln['description'])}</td><td class='num'>{Decimal(ln['qty']).normalize():f}</td>"
        f"<td>{e(ln['unit'])}</td><td class='num'>{e(inr(ln['rate']))}</td><td class='num'>{e(inr(ln['amount']))}</td>"
        f"<td class='num'>{Decimal(ln['verified']).normalize():f}</td></tr>"
        for n, ln in enumerate(out["lines"], start=1)
    )
    terms = []
    if wo.tc_template_id:
        t = db.get(TcTemplate, wo.tc_template_id)
        terms = [c.clause.text for c in t.clauses] if t else []
    terms = terms or [
        "Work as per the drawings, the specification and the instructions of the EESPL site in-charge.",
        "Measurements are joint and are paid only when verified by EESPL.",
        f"Retention of {Decimal(wo.retention_percent).normalize():f}% is held from each bill and released after the "
        "defects liability period.",
        f"TDS at {Decimal(wo.tds_percent).normalize():f}% is deducted as per law.",
        "The subcontractor is responsible for the safety, wages and statutory dues of their workers.",
        "Material is supplied by "
        + ("EESPL" if wo.material_by == "eespl" else "the subcontractor")
        + ".",
    ]
    tc = "".join(
        f'<div class="tc"><span>{n}.</span><span>{e(t)}</span></div>'
        for n, t in enumerate(terms, start=1)
    )
    body = f"""
<div class="meta"><div><b>WO no:</b> {e(wo.code)}</div><div><b>Date:</b> {wo.created_at:%d-%m-%Y}</div>
<div><b>Subcontractor:</b> {e(v.name)}</div><div><b>PAN:</b> {e(v.pan or "—")} · <b>GSTIN:</b> {e(v.gstin or "—")}</div>
<div><b>Site:</b> {e(site.code)} · {e(_site_line(site))}</div>
<div><b>Period:</b> {e(f"{wo.start_date:%d-%m-%Y}" if wo.start_date else "—")} to {e(f"{wo.end_date:%d-%m-%Y}" if wo.end_date else "—")}</div>
<div><b>Material by:</b> {"EESPL" if wo.material_by == "eespl" else "Subcontractor"}</div><div><b>Status:</b> {e(wo.status)}</div></div>
<table><thead><tr><th>#</th><th>Scope</th><th class="num">Qty</th><th>Unit</th><th class="num">Rate</th>
<th class="num">Amount</th><th class="num">Measured</th></tr></thead><tbody>{rows}</tbody></table>
<table class="totals">
<tr><td>Work order value</td><td class="num"><b>{e(inr(out["amount"]))}</b></td></tr>
<tr><td>Retention {Decimal(wo.retention_percent).normalize():f}%</td><td class="num">{e(inr(out["retention"]))}</td></tr>
<tr><td>TDS {Decimal(wo.tds_percent).normalize():f}%</td><td class="num">{e(inr(out["tds"]))}</td></tr>
<tr><td>Billable to date</td><td class="num">{e(inr(out["billable_to_date"]))}</td></tr></table>
{f'<h2>Remarks</h2><div class="pre">{e(wo.remark)}</div>' if wo.remark else ""}
<h2>Terms &amp; Conditions</h2>{tc}
<div class="sign"><div><b>Accepted by the subcontractor</b><div class="line">Signature &amp; stamp</div></div>
<div><b>For {e(company(db).name)}</b><div class="line">Authorised signatory</div></div></div>"""
    return _doc(db, "WORK ORDER", body)


# --- inspection ----------------------------------------------------------------------------------


def inspection(db: Session, i: Inspection, out: dict) -> bytes:
    site = db.get(Site, i.site_id)

    def value(a):
        v = a["value"]
        if a["type"] == "pass_fail":
            return {
                "pass": "<span class='pass'>Pass</span>",
                "fail": "<span class='fail'>Fail</span>",
                "na": "n/a",
            }.get(v, "—")
        return e(v if v is not None else "—")

    rows = "".join(
        f"<tr><td>{n}</td><td>{e(a['text'])}</td><td>{value(a)}</td></tr>"
        for n, a in enumerate(i.answers, start=1)
    )
    texts = {a["item_id"]: a["text"] for a in i.answers}
    photos = [(p["path"], texts.get(p.get("item_id"), p["filename"])) for p in i.photos]
    result = {"pass": "PASS", "fail": "FAIL", "pass_with_remarks": "PASS WITH REMARKS"}[i.result]
    sig = _img(media(i.signature_path), "signature") if i.signature_path else ""
    body = f"""
<div class="meta"><div><b>Inspection:</b> {e(i.code)} · {e(i.template.name)}</div><div><b>Date:</b> {i.on_date:%d-%m-%Y}</div>
<div><b>Site:</b> {e(site.code)} · {e(_site_line(site))}</div><div><b>Where:</b> {e(out.get("node_name") or "—")}</div>
<div><b>Step:</b> {e(out.get("task_name") or "—")}</div>
<div><b>Result:</b> <span class="{"fail" if i.result == "fail" else "pass"}">{result}</span></div></div>
<table><thead><tr><th>#</th><th>Check</th><th>Observation</th></tr></thead><tbody>{rows}</tbody></table>
{f'<h2>Remarks</h2><div class="pre">{e(i.remark)}</div>' if i.remark else ""}
<h2>Photos</h2>{_photos(photos)}
<div class="sign"><div><b>Inspected by</b><div class="line">{e(out.get("inspected_by_name") or "")}</div></div>
<div><b>Client representative</b>{sig}<div class="line">{e(i.client_rep or "")}</div></div></div>"""
    return _doc(db, "INSPECTION REPORT", body)


# --- MOM -----------------------------------------------------------------------------------------


def mom(db: Session, out: dict) -> bytes:
    site = db.get(Site, out["site_id"])
    pts = (
        "".join(
            f"<tr><td>{n}</td><td class='pre'>{e(p['text'])}</td><td>{e(p['owner'] or '—')}</td>"
            f"<td>{e(p['due_date'].strftime('%d-%m-%Y') if p['due_date'] else '—')}</td><td>{e(p['status'])}</td></tr>"
            for n, p in enumerate(out["points"], start=1)
        )
        or "<tr><td colspan='5' class='muted'>No action points.</td></tr>"
    )
    body = f"""
<div class="meta"><div><b>MOM:</b> {e(out["code"])}</div><div><b>Date:</b> {out["on_date"]:%d-%m-%Y}</div>
<div><b>Site:</b> {e(site.code)} · {e(_site_line(site))}</div><div><b>Venue:</b> {e(out["venue"] or "Site")}</div></div>
<div><b>Subject:</b> {e(out["title"])}</div>
<h2>Attendees</h2><div>{e(", ".join(out["attendees"]) or "—")}</div>
{f'<h2>Discussion</h2><div class="pre">{e(out["notes"])}</div>' if out["notes"] else ""}
<h2>Action points</h2><table><thead><tr><th>#</th><th>Point</th><th>Owner</th><th>Due</th><th>Status</th></tr></thead>
<tbody>{pts}</tbody></table>
<p class="muted">Please write to us within 3 days if anything above is not as agreed; otherwise these minutes stand.</p>
<div class="sign"><div><b>For the client</b><div class="line">Signature</div></div>
<div><b>For {e(company(db).name)}</b><div class="line">Signature</div></div></div>"""
    return _doc(db, "MINUTES OF MEETING", body)
