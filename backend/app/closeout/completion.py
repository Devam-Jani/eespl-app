# ruff: noqa: E501  (HTML and wording read better unwrapped)
"""The work completion certificate (WCC) and the guarantee.

When some or all of our areas are done and billed, billing or the site team makes the WCC on our
letterhead: the site and client, our areas (from the zones and the measurement book) with their
approved quantities, the system and products, the dates, and the guarantee (the work order's or
the quotation's years) from the completion date. The marked plan shows our areas highlighted, the
rest greyed, with names and quantities. Signed by the client in the app, or a signed copy is
uploaded: then it is locked forever, and a change is an addendum. The guarantee bond is made from
the same data. The guarantee register lists every guarantee; a leakage complaint links to it and
the exact area. The past projects list serves pre-qualification and brand approval."""

from datetime import date
from decimal import Decimal
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.common import locked, next_code, now, unprocessable
from app.closeout.models import RfiZone, SiteIssueLog, WorkCompletion
from app.sites.models import Site, SiteNode
from app.team.models import Measurement


def guard(w: WorkCompletion) -> None:
    if w.status == "signed":
        raise locked(
            f"Work completion {w.code} (signed{' by ' + w.signed_name if w.signed_name else ''})"
        )


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def guarantee_years(db: Session, site: Site) -> tuple[int | None, str | None]:
    """The work order's years, else the won quotation's, else the tender's."""
    from app.closeout.billing import work_order_of  # noqa: PLC0415
    from app.quotations.models import Quotation  # noqa: PLC0415
    from app.tenders.models import Tender  # noqa: PLC0415

    wo = work_order_of(db, site.id)
    if wo and wo.guarantee_years:
        return wo.guarantee_years, f"work order {wo.client_ref or wo.code}"
    q = db.scalars(
        select(Quotation)
        .where(Quotation.site_id == site.id, Quotation.status == "won")
        .order_by(Quotation.id.desc())
    ).first()
    if q is None and site.tender_id:
        q = db.scalars(
            select(Quotation)
            .where(Quotation.tender_id == site.tender_id, Quotation.status == "won")
            .order_by(Quotation.id.desc())
        ).first()
    if q and q.guarantee_years:
        return q.guarantee_years, f"quotation {q.code} R{q.revision}"
    t = db.get(Tender, site.tender_id) if site.tender_id else None
    if t and t.guarantee_years:
        return t.guarantee_years, f"tender {t.code}"
    return None, None


def _path(db: Session, node_id: int | None) -> str:
    names, seen = [], set()
    while node_id and node_id not in seen:
        seen.add(node_id)
        n = db.get(SiteNode, node_id)
        if n is None:
            break
        names.append(n.name)
        node_id = n.parent_id
    return " / ".join(reversed(names))


def _with_children(db: Session, site_id: int, node_ids: list[int]) -> list[int]:
    """The chosen places and every place under them (a flat brings its toilet and balcony)."""
    kids: dict[int | None, list[int]] = {}
    for nid, parent in db.execute(select(SiteNode.id, SiteNode.parent_id).where(SiteNode.site_id == site_id)):
        kids.setdefault(parent, []).append(nid)
    out, todo = set(), list(node_ids)
    while todo:
        n = todo.pop()
        if n not in out:
            out.add(n)
            todo.extend(kids.get(n, []))
    return sorted(out)


def areas_of(
    db: Session, site: Site, node_ids: list[int] | None = None
) -> tuple[list[dict], list[str], list[str], date | None]:
    """Our areas with their approved quantity (per place and item), the systems and products used,
    and the first date of the work."""
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.masters.models import Product, System, SystemComponent  # noqa: PLC0415
    from app.tenders.models import BoqLine  # noqa: PLC0415

    q = select(Measurement).where(Measurement.site_id == site.id, Measurement.status == "approved")
    if node_ids:
        q = q.where(Measurement.node_id.in_(_with_children(db, site.id, node_ids)))
    groups: dict[tuple, dict] = {}
    systems, products, first = [], [], None
    for m in db.scalars(q.order_by(Measurement.measured_on, Measurement.id)):
        cl = db.get(ContractLine, m.contract_line_id) if m.contract_line_id else None
        item = cl.description if cl else m.description
        key = (m.node_id, item, m.unit)
        g = groups.setdefault(key, {"node_id": m.node_id, "area": _path(db, m.node_id) or m.description, "item": item[:200], "qty": Decimal(0), "unit": m.unit or "sqm",
                                    "from": m.measured_on, "to": m.measured_on, "system": None})  # fmt: skip
        g["qty"] += Decimal(m.qty)
        g["to"] = max(g["to"], m.measured_on)
        first = min(first, m.measured_on) if first else m.measured_on
        bl = db.get(BoqLine, cl.boq_line_id) if cl and cl.boq_line_id else None
        sysm = db.get(System, bl.system_id) if bl and bl.system_id else None
        if sysm:
            g["system"] = sysm.name
            if sysm.name not in systems:
                systems.append(sysm.name)
            for c in db.scalars(
                select(SystemComponent).where(SystemComponent.system_id == sysm.id)
            ):
                p = db.get(Product, c.product_id)
                if p and p.name not in products:
                    products.append(p.name)
    out = [
        {**g, "qty": str(g["qty"]), "from": g["from"].isoformat(), "to": g["to"].isoformat()}
        for g in groups.values()
    ]
    return out, systems, products, first


def make(
    db: Session,
    site: Site,
    completion_date: date,
    years: int | None,
    node_ids: list[int] | None,
    note: str | None,
    user,
    addendum_of: WorkCompletion | None = None,
    demo: bool = False,
) -> WorkCompletion:
    areas, systems, products, first = areas_of(db, site, node_ids)
    if not areas:
        raise unprocessable(
            "No approved measurement on these areas: the certificate takes only approved quantities"
        )
    found, source = guarantee_years(db, site)
    if years is None:
        years = found
        if years is None:
            raise unprocessable(
                "Give the guarantee years: neither the work order nor the quotation has them"
            )
    else:
        source = "typed" if years != found else source
    from app.closeout.billing import work_order_of  # noqa: PLC0415

    wo = work_order_of(db, site.id)
    w = WorkCompletion(code=next_code(db, WorkCompletion, "WCC"), site_id=site.id, client_id=site.client_id, work_order_id=wo.id if wo else None,
                       addendum_of_id=addendum_of.id if addendum_of else None, completion_date=completion_date, started_on=first,
                       guarantee_years=years, guarantee_from=source, guarantee_expiry=add_years(completion_date, years),
                       areas=areas, systems=systems, products=products, note=note, status="draft", created_by=user.id if user else None, is_demo=demo)  # fmt: skip
    db.add(w)
    db.flush()
    return w


def sign(
    db: Session,
    w: WorkCompletion,
    name: str,
    user_id,
    recorded_by_staff: bool,
    copy_path: str | None,
) -> None:
    guard(w)
    if recorded_by_staff and not copy_path:
        raise unprocessable("Upload the signed copy")
    w.status, w.signed_at, w.signed_name, w.signed_by_user = "signed", now(), name, user_id
    w.recorded_by_staff, w.signed_copy_path = recorded_by_staff, copy_path


def addendum(
    db: Session,
    w: WorkCompletion,
    completion_date: date,
    node_ids: list[int] | None,
    note: str,
    user,
) -> WorkCompletion:
    if w.status != "signed":
        raise unprocessable("Change the draft itself; an addendum is for a signed certificate")
    if not (note or "").strip():
        raise unprocessable("Say what the addendum changes")
    site = db.get(Site, w.site_id)
    return make(
        db,
        site,
        completion_date,
        w.guarantee_years,
        node_ids,
        note,
        user,
        addendum_of=w,
        demo=w.is_demo,
    )


# --- the marked plan -----------------------------------------------------------------------------


def plan_svg(db: Session, site: Site, w: WorkCompletion, width: int = 760) -> str:
    """Our areas highlighted, the rest greyed, names and quantities on them: the site's drawing
    (its traced areas) where there is one, else the site's structure as a plan (towers, flats,
    their areas)."""
    ours = {a["node_id"]: a for a in w.areas if a.get("node_id")}
    drawing = _drawing_svg(db, site, ours, width)
    if drawing:
        return drawing
    kids: dict[int | None, list[SiteNode]] = {}
    for n in db.scalars(
        select(SiteNode)
        .where(SiteNode.site_id == site.id)
        .order_by(SiteNode.sort_order, SiteNode.id)
    ):
        kids.setdefault(n.parent_id, []).append(n)
    others = {
        z.node_id: z
        for z in db.scalars(
            select(RfiZone).where(RfiZone.site_id == site.id, RfiZone.ours.is_(False))
        )
    }

    def flats_of(n: SiteNode) -> list[SiteNode]:
        out, todo = [], list(kids.get(n.id, []))
        while todo:
            x = todo.pop(0)
            if x.kind == "flat":
                out.append(x)
            else:
                todo = kids.get(x.id, []) + todo
        return out

    towers = [n for n in kids.get(None, []) if n.kind in ("tower", "wing", "basement")] or kids.get(
        None, []
    )
    cell_w, cell_h, pad = 132, 46, 10
    parts, y = [], 30
    for t in towers:
        flats = flats_of(t)
        if not flats:
            continue
        parts.append(f'<text x="{pad}" y="{y}" class="t">{escape(t.name)}</text>')
        y += 10
        for f in flats:
            areas = kids.get(f.id, [])
            parts.append(f'<text x="{pad}" y="{y + 28}" class="f">{escape(f.name)}</text>')
            for i, a in enumerate(areas):
                x = 110 + i * (cell_w + 6)
                mine = ours.get(a.id)
                fill, stroke = ("#1f8a5b", "#0f5c3b") if mine else ("#d9dcdf", "#b7bbbf")
                txt = "#ffffff" if mine else "#5f6368"
                parts.append(
                    f'<rect x="{x}" y="{y + 6}" width="{cell_w}" height="{cell_h}" rx="4" fill="{fill}" stroke="{stroke}"/>'
                )
                parts.append(
                    f'<text x="{x + 6}" y="{y + 24}" fill="{txt}" class="a">{escape(a.name[:18])}</text>'
                )
                sub = (
                    f"{Decimal(mine['qty']):.2f} {mine['unit']}"
                    if mine
                    else (
                        "other applicator"
                        if a.id in others or f.id in others
                        else "not in this WCC"
                    )
                )
                parts.append(
                    f'<text x="{x + 6}" y="{y + 40}" fill="{txt}" class="q">{escape(sub)}</text>'
                )
            y += cell_h + 10
        y += 16
    height = max(y + 30, 120)
    legend = (f'<rect x="{pad}" y="{height - 22}" width="14" height="10" fill="#1f8a5b"/><text x="{pad + 20}" y="{height - 13}" class="l">our areas (approved quantity)</text>'
              f'<rect x="{pad + 280}" y="{height - 22}" width="14" height="10" fill="#d9dcdf"/><text x="{pad + 300}" y="{height - 13}" class="l">not ours / not in this certificate</text>')  # fmt: skip
    css = "<style>.t{font:700 13px sans-serif;fill:#222}.f{font:600 11px sans-serif;fill:#333}.a{font:600 10px sans-serif}.q{font:9px sans-serif}.l{font:10px sans-serif;fill:#333}</style>"
    w_total = max(
        width,
        110
        + max((len(kids.get(f.id, [])) for t in towers for f in flats_of(t)), default=1)
        * (cell_w + 6)
        + pad,
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w_total} {height}" width="100%">{css}{"".join(parts)}{legend}</svg>'


def _drawing_svg(db: Session, site: Site, ours: dict, width: int) -> str | None:
    from app.takeoff.models import CadArea, CadFile  # noqa: PLC0415

    f = db.scalars(
        select(CadFile)
        .where(CadFile.site_id == site.id, CadFile.status == "read")
        .order_by(CadFile.id.desc())
    ).first()
    if f is None:
        return None
    areas = [a for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == f.id)) if a.outline]
    if not areas:
        return None
    xs = [p[0] for a in areas for p in a.outline]
    ys = [p[1] for a in areas for p in a.outline]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 20) / max(maxx - minx, 1)
    h = int((maxy - miny) * sx) + 20
    parts = []
    for a in areas:
        mine = ours.get(a.node_id) if a.node_id else None
        pts = " ".join(
            f"{10 + (p[0] - minx) * sx:.1f},{10 + (maxy - p[1]) * sx:.1f}" for p in a.outline
        )
        parts.append(
            f'<polygon points="{pts}" fill="{"#1f8a5b" if mine else "#d9dcdf"}" stroke="#555" stroke-width="0.6"/>'
        )
        cx = 10 + (sum(p[0] for p in a.outline) / len(a.outline) - minx) * sx
        cy = 10 + (maxy - sum(p[1] for p in a.outline) / len(a.outline)) * sx
        label = f"{a.name} {Decimal(mine['qty']):.2f}" if mine else a.name
        parts.append(
            f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" style="font:9px sans-serif">{escape(label[:30])}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="100%">{"".join(parts)}</svg>'


# --- the documents -------------------------------------------------------------------------------

CSS = """
table.wcc{width:100%;border-collapse:collapse;font-size:9.5pt}table.wcc td,table.wcc th{border:1px solid #999;padding:4px}
table.wcc th{background:#eef3f1;text-align:left}td.num{text-align:right}.sig{margin-top:28px;display:flex;justify-content:space-between}
.plan{border:1px solid #ccc;padding:6px;margin:8px 0}.small{font-size:8.5pt;color:#555}h2.c{text-align:center;letter-spacing:1px}
"""


def _page(db: Session, code: str, body: str) -> str:
    from app.masters.models import CompanyProfile  # noqa: PLC0415
    from app.quotations import html_out  # noqa: PLC0415
    from app.quotations.models import Letterhead  # noqa: PLC0415
    from app.quotations.render import Doc, _media  # noqa: PLC0415

    head = db.scalars(
        select(Letterhead).where(Letterhead.is_active).order_by(Letterhead.id)
    ).first()
    profile = db.get(CompanyProfile, 1)
    name = (
        (profile.legal_name or profile.trade_name) if profile else None
    ) or "Ethios Enviro Solutions Pvt. Ltd."
    doc = Doc(code=code, revision=0, footer=code, company_name=head.company_name if head else name,
              logo=_media(head.logo_path) if head else _media(profile.logo_path if profile else None),
              header_image=_media(head.header_image_path) if head else None, footer_image=_media(head.footer_image_path) if head else None,
              watermark=_media(head.watermark_path) if head else None, preprinted=bool(head and head.preprinted),
              header_text=(head.header_text if head else "") or "", footer_text=(head.footer_text if head else "") or "",
              primary=head.primary_color if head else "#0F6E5A", accent=head.accent_color if head else "#E69F00",
              opening=[], subject="", body=[], signatory_firm=(head.signatory_firm if head else f"For {name.upper()}"), signatory_line="", enclosures=[])  # fmt: skip
    page = html_out.html(doc, for_pdf=True).replace("</style>", CSS + "</style>", 1)
    return page.replace("</body>", body + "</body>", 1)


def html(db: Session, w: WorkCompletion) -> str:
    from app.masters.models import Client  # noqa: PLC0415

    site = db.get(Site, w.site_id)
    client = db.get(Client, w.client_id) if w.client_id else None
    rows = "".join(f'<tr><td>{i}</td><td>{escape(a["area"])}</td><td>{escape(a["item"])}</td><td class="num">{Decimal(a["qty"]):,.2f}</td><td>{escape(a["unit"])}</td>'
                   f'<td>{escape(a.get("system") or "—")}</td><td>{a["from"]} to {a["to"]}</td></tr>' for i, a in enumerate(w.areas, 1))  # fmt: skip
    base = db.get(WorkCompletion, w.addendum_of_id) if w.addendum_of_id else None
    signed = (
        (
            f"Signed by {escape(w.signed_name or '')} on {w.signed_at:%d.%m.%Y}"
            + (
                " (signed copy recorded by our staff)"
                if w.recorded_by_staff
                else " (in the client portal)"
            )
        )
        if w.status == "signed"
        else "Client's signature: ____________________"
    )
    body = f"""
<h2 class="c">WORK COMPLETION CERTIFICATE{' — ADDENDUM TO ' + escape(base.code) if base else ''}</h2>
<p><b>Certificate:</b> {w.code} &nbsp; <b>Date of completion:</b> {w.completion_date:%d.%m.%Y}{' &nbsp; <b>Work started:</b> ' + w.started_on.strftime('%d.%m.%Y') if w.started_on else ''}</p>
<p><b>Site:</b> {escape(site.code)} {escape(site.name)}{', ' + escape(site.city) if site.city else ''} &nbsp; <b>Client:</b> {escape(client.name if client else '—')}</p>
<p>This is to certify that the waterproofing works listed below were carried out by us at the above site and completed on {w.completion_date:%d.%m.%Y}. The quantities are the ones approved by the client in the measurement book.</p>
<table class="wcc"><thead><tr><th>#</th><th>Area</th><th>Item</th><th>Qty</th><th>Unit</th><th>System</th><th>Dates</th></tr></thead><tbody>{rows}</tbody></table>
<p><b>Systems:</b> {escape(', '.join(w.systems) or '—')}<br><b>Products:</b> {escape(', '.join(w.products) or '—')}</p>
<p><b>Guarantee:</b> {w.guarantee_years} years from {w.completion_date:%d.%m.%Y} to {w.guarantee_expiry:%d.%m.%Y}{' (' + escape(w.guarantee_from) + ')' if w.guarantee_from else ''}.</p>
{('<p><b>Note:</b> ' + escape(w.note) + '</p>') if w.note else ''}
<h3>MARKED PLAN</h3><div class="plan">{plan_svg(db, site, w)}</div>
<div class="sig"><div>For the applicator<br><br>____________________</div><div>{signed}</div></div>
"""
    return _page(db, w.code, body)


def bond_html(db: Session, w: WorkCompletion) -> str:
    from app.masters.models import Client  # noqa: PLC0415

    site = db.get(Site, w.site_id)
    client = db.get(Client, w.client_id) if w.client_id else None
    total = {}
    for a in w.areas:
        total[a["unit"]] = total.get(a["unit"], Decimal(0)) + Decimal(a["qty"])
    qty = ", ".join(f"{v:,.2f} {k}" for k, v in total.items())
    body = f"""
<h2 class="c">GUARANTEE BOND</h2>
<p>Reference: {w.code} &nbsp; Date: {w.completion_date:%d.%m.%Y}</p>
<p>To: {escape(client.name if client else 'the client')}<br>Site: {escape(site.code)} {escape(site.name)}{', ' + escape(site.city) if site.city else ''}</p>
<p>We guarantee the waterproofing works carried out by us at the above site ({escape(qty)}, as listed in the work completion certificate {w.code}) against leakage
for a period of <b>{w.guarantee_years} years</b> from {w.completion_date:%d.%m.%Y} to {w.guarantee_expiry:%d.%m.%Y}, provided the treated areas are not disturbed by
others (chasing, drilling, re-tiling, new fixtures) and are used as intended.</p>
<p>Systems: {escape(', '.join(w.systems) or '—')}. Products: {escape(', '.join(w.products) or '—')}.</p>
<p>Any leakage in these areas reported within the guarantee period will be inspected within 7 days and, when it is due to our work, rectified at our cost.</p>
<div class="sig"><div>For the applicator<br><br>____________________<br>Authorised signatory</div></div>
"""
    return _page(db, f"{w.code} bond", body)


def pdf(html_text: str) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415

    return HTML(string=html_text).write_pdf()


# --- the register and past projects ---------------------------------------------------------------


def register(db: Session, site_ids=None, today: date | None = None) -> list[dict]:
    from app.masters.models import Client  # noqa: PLC0415

    q = (
        select(WorkCompletion)
        .where(WorkCompletion.status == "signed")
        .order_by(WorkCompletion.guarantee_expiry)
    )
    if site_ids is not None:
        q = q.where(WorkCompletion.site_id.in_(site_ids))
    out = []
    for w in db.scalars(q):
        site = db.get(Site, w.site_id)
        client = db.get(Client, w.client_id) if w.client_id else None
        issues = (
            db.scalar(
                select(SiteIssueLog.id).where(SiteIssueLog.work_completion_id == w.id).limit(1)
            )
            is not None
        )
        out.append({"id": w.id, "code": w.code, "addendum_of": w.addendum_of_id, "site_id": w.site_id, "site": f"{site.code} {site.name}" if site else None,
                    "client": client.name if client else None, "areas": [f"{a['area']}: {Decimal(a['qty']):.2f} {a['unit']}" for a in w.areas],
                    "products": w.products, "systems": w.systems, "start": w.completion_date, "expiry": w.guarantee_expiry, "years": w.guarantee_years,
                    "active": (today or date.today()) <= w.guarantee_expiry, "has_complaints": issues, "is_demo": w.is_demo})  # fmt: skip
    return out


def past_projects(db: Session) -> list[dict]:
    from app.masters.models import Client  # noqa: PLC0415

    out = []
    for w in db.scalars(
        select(WorkCompletion)
        .where(WorkCompletion.status == "signed", WorkCompletion.addendum_of_id.is_(None))
        .order_by(WorkCompletion.completion_date.desc())
    ):
        site = db.get(Site, w.site_id)
        client = db.get(Client, w.client_id) if w.client_id else None
        total: dict[str, Decimal] = {}
        for x in [
            w,
            *db.scalars(
                select(WorkCompletion).where(
                    WorkCompletion.addendum_of_id == w.id, WorkCompletion.status == "signed"
                )
            ),
        ]:
            for a in x.areas:
                total[a["unit"]] = total.get(a["unit"], Decimal(0)) + Decimal(a["qty"])
        out.append({"client": client.name if client else "", "site": site.name if site else "", "city": site.city if site else "", "systems": ", ".join(w.systems),
                    "quantities": ", ".join(f"{v:,.2f} {k}" for k, v in total.items()), "completion": w.completion_date, "guarantee_years": w.guarantee_years, "is_demo": w.is_demo})  # fmt: skip
    return out
