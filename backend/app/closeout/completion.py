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


def _ancestors(db: Session, node_id: int | None) -> list[int]:
    out, seen = [], set()
    while node_id and node_id not in seen:
        seen.add(node_id)
        out.append(node_id)
        n = db.get(SiteNode, node_id)
        node_id = n.parent_id if n else None
    return out


def system_of(db: Session, cl, node_id: int | None):
    """The line's system: the work order line's (its quotation line, else the BOQ line it came
    from), else the area's stage template. (system, where it came from) or (None, None)."""
    from app.closeout.models import ClientWorkOrderLine  # noqa: PLC0415
    from app.masters.models import System  # noqa: PLC0415
    from app.quotations.models import QuotationLine  # noqa: PLC0415
    from app.sites.models import AreaScope, StageTemplate  # noqa: PLC0415
    from app.tenders.models import BoqLine  # noqa: PLC0415

    wl = db.get(ClientWorkOrderLine, cl.wo_line_id) if cl is not None and cl.wo_line_id else None
    ql = db.get(QuotationLine, wl.quotation_line_id) if wl is not None and wl.quotation_line_id else None
    if ql is not None and ql.system_id:
        return db.get(System, ql.system_id), "work order line"
    bl = db.get(BoqLine, cl.boq_line_id) if cl is not None and cl.boq_line_id else None
    if bl is not None and bl.system_id:
        return db.get(System, bl.system_id), "work order line" if wl else "contract line"
    for nid in _ancestors(db, node_id):
        for sc in db.scalars(select(AreaScope).where(AreaScope.node_id == nid).order_by(AreaScope.id)):
            if bl is not None and sc.boq_line_id and sc.boq_line_id != bl.id:
                continue
            tpl = db.get(StageTemplate, sc.stage_template_id)
            if tpl is not None and tpl.system_id:
                return db.get(System, tpl.system_id), f"stage template {tpl.name}"
    return None, None


def stage_dates(db: Session, node_id: int | None, boq_line_id: int | None) -> tuple[date | None, date | None]:
    """The area's real stage dates: the first stage's start to the last stage's end (its tasks,
    else the stage dates on its inspections)."""
    from app.execution.models import Inspection  # noqa: PLC0415
    from app.sites.models import AreaScope, Task  # noqa: PLC0415

    if not node_id:
        return None, None
    q = select(AreaScope.id).where(AreaScope.node_id == node_id)
    scopes = list(db.scalars(q.where(AreaScope.boq_line_id == boq_line_id))) if boq_line_id else []
    scopes = scopes or list(db.scalars(q))
    starts, ends = [], []
    for t in db.scalars(select(Task).where(Task.area_scope_id.in_(scopes or [0]), Task.parent_task_id.is_(None))):
        i = db.scalars(select(Inspection).where(Inspection.task_id == t.id).order_by(Inspection.id.desc())).first()
        s = t.actual_start or (i.stage_started_on if i else None)
        e = t.actual_end or (i.stage_ended_on if i else None)
        if s:
            starts.append(s)
        if e:
            ends.append(e)
    return (min(starts) if starts else None), (max(ends) if ends else None)


def areas_of(
    db: Session, site: Site, node_ids: list[int] | None = None
) -> tuple[list[dict], list[str], list[str], date | None]:
    """Our areas with their approved quantity in the line's unit (the work order's), the system
    and products of each line, and the real stage dates of each area."""
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.masters.models import Product, SystemComponent  # noqa: PLC0415

    q = select(Measurement).where(Measurement.site_id == site.id, Measurement.status == "approved")
    if node_ids:
        q = q.where(Measurement.node_id.in_(_with_children(db, site.id, node_ids)))
    groups: dict[tuple, dict] = {}
    systems, products, first = [], [], None
    for m in db.scalars(q.order_by(Measurement.measured_on, Measurement.id)):
        cl = db.get(ContractLine, m.contract_line_id) if m.contract_line_id else None
        item = cl.description if cl else m.description
        unit = (cl.unit if cl else None) or m.unit or "sqm"
        key = (m.node_id, item, unit)
        g = groups.get(key)
        if g is None:
            sysm, sys_from = system_of(db, cl, m.node_id)
            prods = []
            if sysm is not None:
                for c in db.scalars(select(SystemComponent).where(SystemComponent.system_id == sysm.id).order_by(SystemComponent.id)):
                    p = db.get(Product, c.product_id)
                    if p and p.name not in prods:
                        prods.append(p.name)
            start, end = stage_dates(db, m.node_id, cl.boq_line_id if cl else None)
            g = groups[key] = {"node_id": m.node_id, "area": _path(db, m.node_id) or m.description, "item": item[:200], "qty": Decimal(0), "unit": unit,
                               "system": sysm.name if sysm else None, "system_from": sys_from, "products": prods,
                               "from": start, "to": end, "dates_from": "stages" if start and end else None, "_m_from": m.measured_on, "_m_to": m.measured_on}  # fmt: skip
        g["qty"] += Decimal(m.qty)
        g["_m_from"], g["_m_to"] = min(g["_m_from"], m.measured_on), max(g["_m_to"], m.measured_on)
    out = []
    for g in groups.values():
        if g["dates_from"] is None:  # no stage dates kept: the measurement dates, said so
            g["from"], g["to"], g["dates_from"] = g["_m_from"], g["_m_to"], "measurement book"
        first = min(first, g["from"]) if first else g["from"]
        if g["system"] and g["system"] not in systems:
            systems.append(g["system"])
        products += [p for p in g["products"] if p not in products]
        out.append({**{k: v for k, v in g.items() if not k.startswith("_")}, "qty": str(g["qty"]), "from": g["from"].isoformat(), "to": g["to"].isoformat()})
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
    missing = [f"{a['area']} ({a['item'][:50]})" for a in areas if not a["system"]]
    if missing:
        raise unprocessable(
            "No system for " + "; ".join(missing[:5]) + ": give the work order line a system (its quotation line) or the area a stage template with one"
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


def qty_text(qty, unit: str) -> str:
    """The approved quantity as stored (7.015, not 7.02), the same in the table and on the plan."""
    return f"{Decimal(qty):,.3f} {unit}"


def _d(v) -> str:
    return date.fromisoformat(v).strftime("%d.%m.%Y") if isinstance(v, str) else v.strftime("%d.%m.%Y")


def plan_svg(db: Session, site: Site, w: WorkCompletion, width: int = 760) -> str:
    """Our areas highlighted, the rest greyed, names and quantities on them: the site's drawing
    (its traced areas) where there is one, else the site's structure as a plan (towers, flats,
    their areas)."""
    ours: dict[int, dict] = {}
    for a in w.areas:
        if a.get("node_id"):
            ours.setdefault(a["node_id"], {"qty": []})["qty"].append(qty_text(a["qty"], a["unit"]))
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
    parts, y = [f'<text x="{pad}" y="14" class="l">Schematic: the site has no drawing with these areas traced; places as listed on the site</text>'], 40
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
                    " + ".join(mine["qty"])
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
        .where(CadFile.site_id == site.id, CadFile.status == "ready")
        .order_by(CadFile.id.desc())
    ).first()
    if f is None:
        return None
    every = [a for a in db.scalars(select(CadArea).where(CadArea.cad_file_id == f.id)) if a.outline]
    mine_areas = [a for a in every if a.node_id in ours]
    if not mine_areas:  # the drawing does not have these areas traced: the schematic instead
        return None
    from app.sites.models import Drawing, DrawingRevision  # noqa: PLC0415

    dr, rev = db.get(Drawing, f.drawing_id), db.get(DrawingRevision, f.revision_id)
    # the part of the drawing around our areas (a margin of a fifth each side), not the whole floor
    xs = [p[0] for a in mine_areas for p in a.outline]
    ys = [p[1] for a in mine_areas for p in a.outline]
    mx, my = (max(xs) - min(xs)) * 0.2 + 1, (max(ys) - min(ys)) * 0.2 + 1
    box = (min(xs) - mx, max(xs) + mx, min(ys) - my, max(ys) + my)
    areas = [a for a in every if any(box[0] <= p[0] <= box[1] and box[2] <= p[1] <= box[3] for p in a.outline)
             or (box[0] <= sum(p[0] for p in a.outline) / len(a.outline) <= box[1] and box[2] <= sum(p[1] for p in a.outline) / len(a.outline) <= box[3])]  # fmt: skip
    xs = [p[0] for a in areas for p in a.outline]
    ys = [p[1] for a in areas for p in a.outline]
    minx, maxx, miny, maxy = max(min(xs), box[0]), min(max(xs), box[1]), max(min(ys), box[2]), min(max(ys), box[3])
    sx = (width - 20) / max(maxx - minx, 1)
    top = 24
    h = int((maxy - miny) * sx) + 20
    title = f"{dr.title if dr else 'Drawing'}{f' R{rev.rev_no}' if rev else ''}: our areas in green, with the approved quantities"
    parts = [f'<text x="10" y="14" style="font:600 10px sans-serif;fill:#333">{escape(title)}</text>',
             f'<clipPath id="plan"><rect x="0" y="0" width="{width}" height="{h}"/></clipPath><g transform="translate(0 {top})" clip-path="url(#plan)">']  # fmt: skip
    for a in areas:
        mine = ours.get(a.node_id) if a.node_id else None
        pts = " ".join(
            f"{10 + (p[0] - minx) * sx:.1f},{10 + (maxy - p[1]) * sx:.1f}" for p in a.outline
        )
        parts.append(
            f'<polygon points="{pts}" fill="{"#1f8a5b" if mine else "#eceff1"}" stroke="#555" stroke-width="0.8"/>'
        )
        cx = 10 + (sum(p[0] for p in a.outline) / len(a.outline) - minx) * sx
        cy = 10 + (maxy - sum(p[1] for p in a.outline) / len(a.outline)) * sx
        color = "#ffffff" if mine else "#555"
        lines_ = [a.name] + ([" + ".join(mine["qty"])] if mine else [])
        for k, txt in enumerate(lines_):
            parts.append(f'<text x="{cx:.1f}" y="{cy + (k - (len(lines_) - 1) / 2) * 11 + 3:.1f}" text-anchor="middle" font-family="sans-serif" '
                         f'font-size="8" font-weight="{600 if mine else 400}" fill="{color}">{escape(txt[:28])}</text>')  # fmt: skip
    parts.append("</g>")
    y = h + top + 6
    parts.append(f'<rect x="10" y="{y}" width="14" height="10" fill="#1f8a5b"/><text x="30" y="{y + 9}" style="font:10px sans-serif;fill:#333">our areas (approved quantity)</text>'
                 f'<rect x="290" y="{y}" width="14" height="10" fill="#eceff1" stroke="#555" stroke-width="0.5"/><text x="310" y="{y + 9}" style="font:10px sans-serif;fill:#333">not ours / not in this certificate</text>')  # fmt: skip
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {y + 16}" width="100%">{"".join(parts)}</svg>'


# --- the documents -------------------------------------------------------------------------------

CSS = """
table.wcc{width:100%;border-collapse:collapse;font-size:9.5pt}table.wcc td,table.wcc th{border:1px solid #999;padding:4px}
table.wcc th{background:#eef3f1;text-align:left}td.num{text-align:right}.sig{margin-top:28px;display:flex;justify-content:space-between}
.plan{border:1px solid #ccc;padding:6px;margin:8px 0}table.sigs{width:100%;margin-top:22px;font-size:10pt}table.sigs td{width:50%;vertical-align:top;padding-right:20px}
.space{height:46px}.small{font-size:8.5pt;color:#555}h2.c{text-align:center;letter-spacing:1px}
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
    rows = "".join(f'<tr><td>{i}</td><td>{escape(a["area"])}</td><td>{escape(a["item"])}</td><td class="num">{Decimal(a["qty"]):,.3f}</td><td>{escape(a["unit"])}</td>'
                   f'<td>{escape(a.get("system") or "—")}<div class="small">{escape(", ".join(a.get("products") or []))}</div></td>'
                   f'<td>{_d(a["from"])} to {_d(a["to"])}<div class="small">{escape(a.get("dates_from") or "")}</div></td></tr>' for i, a in enumerate(w.areas, 1))  # fmt: skip
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
        else ""
    )
    firm, sig_name, sig_role = signatory(db)
    body = f"""
<h2 class="c">WORK COMPLETION CERTIFICATE{' — ADDENDUM TO ' + escape(base.code) if base else ''}</h2>
<p><b>Certificate:</b> {w.code} &nbsp; <b>Date of completion:</b> {w.completion_date:%d.%m.%Y}{' &nbsp; <b>Work started:</b> ' + w.started_on.strftime('%d.%m.%Y') if w.started_on else ''}</p>
<p><b>Site:</b> {escape(site.code)} {escape(site.name)}{', ' + escape(site.city) if site.city else ''} &nbsp; <b>Client:</b> {escape(client.name if client else '—')}</p>
<p>This is to certify that the waterproofing works listed below were carried out by us at the above site and completed on {w.completion_date:%d.%m.%Y}. The quantities are the ones approved by the client in the measurement book.</p>
<table class="wcc"><thead><tr><th>#</th><th>Area</th><th>Item</th><th>Qty</th><th>Unit</th><th>System and products</th><th>Dates</th></tr></thead><tbody>{rows}</tbody></table>
<p><b>Systems:</b> {escape(', '.join(w.systems) or '—')}<br><b>Products:</b> {escape(', '.join(w.products) or '—')}</p>
<p><b>Guarantee:</b> {w.guarantee_years} years from {w.completion_date:%d.%m.%Y} to {w.guarantee_expiry:%d.%m.%Y}{' (' + escape(w.guarantee_from) + ')' if w.guarantee_from else ''}.</p>
{('<p><b>Note:</b> ' + escape(w.note) + '</p>') if w.note else ''}
<h3>MARKED PLAN</h3><div class="plan">{plan_svg(db, site, w)}</div>
<table class="sigs"><tr>
<td><b>{escape(firm)}</b><div class="space"></div>____________________<br>{escape(sig_name or '')}<br>{escape(sig_role)}<br>Date: {w.completion_date:%d.%m.%Y}</td>
<td><b>For {escape(client.name if client else 'the client')}</b><div class="space"></div>____________________<br>Name: ____________________<br>Designation: ______________<br>Date: ____________________
{('<div class="small">' + signed + '</div>') if signed else ''}</td></tr></table>
"""
    return _page(db, w.code, body)


def signatory(db: Session) -> tuple[str, str | None, str]:
    """Our signatory from the letterhead (Settings > Quotation library > Letterheads): the firm
    line, and the name and designation of the signatory chosen for certificates (the first or the
    second). No designation entered: a line to write it on, never a made-up one."""
    from app.quotations.models import Letterhead  # noqa: PLC0415

    head = db.scalars(select(Letterhead).where(Letterhead.is_active).order_by(Letterhead.id)).first()
    firm = (head.signatory_firm if head else None) or "For the applicator"
    if head is None:
        return firm, None, "Designation: ______________"
    second = head.certificate_signatory == 2 and bool(head.signatory2_name)
    name = head.signatory2_name if second else head.signatory_name
    role = head.signatory2_designation if second else head.signatory_designation
    return firm, name, role or "Designation: ______________"


def bond_html(db: Session, w: WorkCompletion) -> str:
    from app.masters.models import Client  # noqa: PLC0415

    site = db.get(Site, w.site_id)
    client = db.get(Client, w.client_id) if w.client_id else None
    total = {}
    for a in w.areas:
        total[a["unit"]] = total.get(a["unit"], Decimal(0)) + Decimal(a["qty"])
    qty = ", ".join(f"{v:,.3f} {k}" for k, v in total.items())
    body = f"""
<h2 class="c">GUARANTEE BOND</h2>
<p>Reference: {w.code} &nbsp; Date: {w.completion_date:%d.%m.%Y}</p>
<p>To: {escape(client.name if client else 'the client')}<br>Site: {escape(site.code)} {escape(site.name)}{', ' + escape(site.city) if site.city else ''}</p>
<p>We guarantee the waterproofing works carried out by us at the above site ({escape(qty)}, as listed in the work completion certificate {w.code}) against leakage
for a period of <b>{w.guarantee_years} years</b> from {w.completion_date:%d.%m.%Y} to {w.guarantee_expiry:%d.%m.%Y}, provided the treated areas are not disturbed by
others (chasing, drilling, re-tiling, new fixtures) and are used as intended.</p>
<p>Systems: {escape(', '.join(w.systems) or '—')}. Products: {escape(', '.join(w.products) or '—')}.</p>
<p>Any leakage in these areas reported within the guarantee period will be inspected within 7 days and, when it is due to our work, rectified at our cost.</p>
<div class="sig"><div>{escape(signatory(db)[0])}<div class="space"></div>____________________<br>{escape(signatory(db)[1] or '')}<br>{escape(signatory(db)[2])}</div></div>
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
                    "client": client.name if client else None, "areas": [f"{a['area']}: {qty_text(a['qty'], a['unit'])}" for a in w.areas],
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
                    "quantities": ", ".join(f"{v:,.3f} {k}" for k, v in total.items()), "completion": w.completion_date, "guarantee_years": w.guarantee_years, "is_demo": w.is_demo})  # fmt: skip
    return out
