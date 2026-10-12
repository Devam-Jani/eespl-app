# ruff: noqa: E501  (event data reads better unwrapped)
"""Where each step of the chain writes its event. The calls sit in the code that does the step;
the timed events (follow-ups due, the monthly RA day, consumption) come from the worker's clock."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.process.engine import emit
from app.timefmt import IST, label


def _n(v) -> str:
    if v is None:
        return "—"
    return f"{Decimal(v).normalize():f}"


def _money(v) -> str:
    from app.tenders.export import inr  # noqa: PLC0415

    return inr(Decimal(v or 0).quantize(Decimal(1)))[:-3]  # ₹12,34,567


# --- enquiry, quotation, negotiation, win ---------------------------------------------------------


def enquiry_unassigned(db: Session, lead, actor_id) -> None:
    emit(
        db,
        "enquiry_unassigned",
        subject=f"lead:{lead.id}",
        actor_id=actor_id,
        data={
            "lead": lead.code,
            "lead_id": lead.id,
            "name": lead.contact_name,
            "city": lead.city or "",
            "phone": lead.phone or "",
        },
    )


def lead_allocated(db: Session, lead, actor_id) -> None:
    emit(
        db,
        "lead_allocated",
        subject=f"lead:{lead.id}",
        actor_id=actor_id,
        dedupe=f"lead_allocated:{lead.id}:{lead.owner_id}",
        data={
            "lead": lead.code,
            "lead_id": lead.id,
            "name": lead.contact_name,
            "city": lead.city or "",
            "phone": lead.phone or "",
            "requirement": (lead.requirement or "")[:120],
            "salesperson_id": lead.owner_id,
        },
    )


def kylas_quotation(db: Session, lead) -> None:
    emit(
        db,
        "kylas_quotation",
        subject=f"lead:{lead.id}",
        data={
            "lead": lead.code,
            "lead_id": lead.id,
            "name": lead.contact_name,
            "salesperson_id": lead.owner_id,
        },
    )


def quotation_created(db: Session, q, actor_id) -> None:
    if q.lead_id:
        emit(
            db,
            "quotation_created",
            subject=f"lead:{q.lead_id}",
            actor_id=actor_id,
            dedupe=f"quotation_created:{q.id}",
            data={"quotation": q.code},
        )


def send_blocked(
    principal, what: str, subject: str, link: str, missing: list[str], site_id: int | None = None
) -> None:
    """Sending was refused: its own transaction (the request rolls back)."""
    from app.db import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        emit(
            db,
            "send_blocked",
            subject=subject,
            site_id=site_id,
            actor_id=principal.user.id,
            dedupe=f"send_blocked:{subject}:{';'.join(missing)}",
            data={
                "what": what,
                "missing": "; ".join(missing),
                "link": link,
                "author_id": principal.user.id,
            },
        )
        db.commit()


def quotation_sent(db: Session, q, actor_id) -> None:
    emit(
        db,
        "quotation_sent",
        subject=f"quotation:{q.code}",
        site_id=q.site_id,
        actor_id=actor_id,
        dedupe=f"quotation_sent:{q.id}",
        data={
            "quotation": f"{q.code} R{q.revision}",
            "quotation_id": q.id,
            "client": q.client_firm,
            "salesperson_id": q.salesperson_id,
        },
    )


def quotation_revised(db: Session, old, new, actor_id) -> None:
    emit(
        db,
        "quotation_revised",
        subject=f"quotation:{old.code}",
        site_id=old.site_id,
        actor_id=actor_id,
        dedupe=f"quotation_revised:{new.id}",
        data={"quotation": f"{new.code} R{new.revision}"},
    )


def followup_done(db: Session, f, actor_id) -> None:
    emit(db, "followup_done", subject=f"followup:{f.id}", actor_id=actor_id, data={})


def negotiation_logged(db: Session, n, actor_id) -> None:
    from app.quotations.models import Quotation  # noqa: PLC0415
    from app.tenders.models import Tender  # noqa: PLC0415

    if n.quotation_id:
        q = db.get(Quotation, n.quotation_id)
        subject, what, link, site, sp = (
            f"quotation:{q.code}",
            f"{q.code} R{q.revision} ({q.client_firm})",
            f"/quotations/{q.id}",
            q.site_id,
            q.salesperson_id,
        )
    else:
        t = db.get(Tender, n.tender_id)
        subject, what, link, site, sp = (
            f"tender:{t.id}",
            f"{t.code} {t.name}",
            f"/tenders/{t.id}?tab=award",
            None,
            t.owner_id,
        )
    emit(
        db,
        "negotiation_logged",
        subject=subject,
        site_id=site,
        actor_id=actor_id,
        dedupe=f"negotiation:{n.id}",
        data={"what": what, "asked": n.asked[:120], "link": link, "salesperson_id": sp},
    )


def tender_submitted(db: Session, t, actor_id) -> None:
    from app.sites.models import Site  # noqa: PLC0415

    site = db.scalar(select(Site.id).where(Site.tender_id == t.id))
    emit(
        db,
        "tender_submitted",
        subject=f"tender:{t.id}",
        site_id=site,
        actor_id=actor_id,
        dedupe=f"tender_submitted:{t.id}:{t.revision}",
        data={"tender": f"{t.code} {t.name}", "tender_id": t.id, "salesperson_id": t.owner_id},
    )


def job_won(db: Session, a) -> None:
    emit(
        db,
        "job_won",
        subject=f"assignment:{a.id}",
        site_id=a.site_id,
        data={"title": a.title, "assignment_id": a.id, "salesperson_id": a.salesperson_id},
    )


def job_assigned(db: Session, a, actor_id) -> None:
    emit(
        db,
        "job_assigned",
        subject=f"assignment:{a.id}",
        site_id=a.site_id,
        actor_id=actor_id,
        data={"site_id": a.site_id, "salesperson_id": a.salesperson_id},
    )
    # the to-dos of the team are about the site (closed by the visit and by the survey)
    from app.portal.models import Notification  # noqa: PLC0415
    from app.process.models import ProcessEvent  # noqa: PLC0415

    ev = db.scalar(
        select(ProcessEvent).where(ProcessEvent.dedupe_key == f"job_assigned:assignment:{a.id}")
    )
    if ev is not None:
        for n in db.scalars(select(Notification).where(Notification.event_id == ev.id)):
            n.subject = f"site:{a.site_id}"
        ev.subject = f"site:{a.site_id}"
        db.flush()


def site_visit_logged(db: Session, v, actor_id) -> None:
    if v.site_id:
        emit(
            db,
            "site_visit_logged",
            subject=f"site:{v.site_id}",
            site_id=v.site_id,
            actor_id=actor_id,
            dedupe=f"site_visit:{v.id}",
            data={},
        )


def survey_done(db: Session, survey, actor_id) -> None:
    if survey.site_id:
        emit(
            db,
            "survey_done",
            subject=f"site:{survey.site_id}",
            site_id=survey.site_id,
            actor_id=actor_id,
            dedupe=f"survey_done:{survey.id}:{survey.status}",
            data={},
        )


# --- work front, material, delivery ---------------------------------------------------------------


def front_ready(db: Session, node, actor_id) -> None:
    from app.process.engine import wastage_for  # noqa: PLC0415
    from app.sitecontrol.service import node_label  # noqa: PLC0415
    from app.sites.models import AreaScope  # noqa: PLC0415

    place = node_label(db, node)
    qty = (
        db.scalar(
            select(func.coalesce(func.sum(AreaScope.qty), 0)).where(AreaScope.node_id == node.id)
        )
        or 0
    )
    unit = db.scalar(select(AreaScope.unit).where(AreaScope.node_id == node.id).limit(1)) or "sqm"
    w = wastage_for(db, f"{place} {node.kind}")
    wastage = f"{w[0]} {w[1]['min']}-{w[1]['max']}%" if w else "from the system"
    emit(
        db,
        "front_ready",
        subject=f"node:{node.id}",
        site_id=node.site_id,
        actor_id=actor_id,
        dedupe=f"front_ready:{node.id}:{label(node.front_ready_at)}",
        data={"area": place, "node_id": node.id, "qty": _n(qty), "unit": unit, "wastage": wastage},
    )


def indent_created(db: Session, ind, node_ids: list[int], actor_id) -> None:
    for nid in node_ids:
        emit(
            db,
            "indent_created",
            subject=f"node:{nid}",
            site_id=ind.site_id,
            actor_id=actor_id,
            dedupe=f"indent_created:{ind.id}:{nid}",
            data={"indent": ind.code},
        )


def indent_approved(db: Session, ind, actor_id) -> None:
    emit(
        db,
        "indent_approved",
        subject=f"indent:{ind.id}",
        site_id=ind.site_id,
        actor_id=actor_id,
        data={"indent": ind.code, "indent_id": ind.id},
    )


def po_created(db: Session, po, indent_ids: list[int], actor_id) -> None:
    for iid in indent_ids:
        emit(
            db,
            "po_created",
            subject=f"indent:{iid}",
            actor_id=actor_id,
            dedupe=f"po_created:{po.id}:{iid}",
            data={"po": po.code},
        )


def dn_created(db: Session, dn) -> None:
    from app.masters.models import Product  # noqa: PLC0415

    items = ", ".join(
        f"{db.get(Product, ln.product_id).name} {_n(ln.qty)} {ln.unit}" for ln in dn.lines
    )[:160]
    emit(
        db,
        "dn_created",
        subject=f"dn:{dn.id}",
        site_id=dn.site_id,
        data={
            "dn": dn.code,
            "dn_id": dn.id,
            "items": items,
            "expected": label(dn.expected_at, "%d %b %H:%M"),
        },
    )


def delivery_confirmed(db: Session, dn, actor_id) -> None:
    emit(
        db,
        "delivery_confirmed",
        subject=f"dn:{dn.id}",
        site_id=dn.site_id,
        actor_id=actor_id,
        data={"dn": dn.code, "dn_id": dn.id},
    )


# --- daily reports ---------------------------------------------------------------------------------


def dpr_submitted(db: Session, d, actor_id) -> None:
    from app.execution.models import Dpr, DprLine  # noqa: PLC0415
    from app.sitecontrol.models import NewAreaRequest  # noqa: PLC0415
    from app.sitecontrol.service import node_label  # noqa: PLC0415
    from app.sites.models import Site, SiteNode  # noqa: PLC0415

    emit(
        db,
        "dpr_submitted",
        subject=f"dpr:{d.id}",
        site_id=d.site_id,
        actor_id=actor_id,
        dedupe=f"dpr_submitted:{d.id}:{label(d.submitted_at)}",
        data={"date": f"{d.on_date:%d %b}", "day": d.on_date.isoformat()},
    )
    site = db.get(Site, d.site_id)
    for ln in d.lines:
        if ln.node_id:
            earlier = db.scalar(
                select(func.count())
                .select_from(DprLine)
                .join(Dpr, Dpr.id == DprLine.dpr_id)
                .where(DprLine.node_id == ln.node_id, Dpr.id != d.id, Dpr.status != "draft")
            )
            if not earlier:
                place = node_label(db, db.get(SiteNode, ln.node_id))
                ev = emit(
                    db,
                    "first_dpr_on_area",
                    subject=f"node:{ln.node_id}",
                    site_id=d.site_id,
                    actor_id=actor_id,
                    dedupe=f"first_dpr:{ln.node_id}",
                    data={"area": place},
                )
                if ev is not None and site is not None and site.board_status in (None, "upcoming"):
                    site.board_status, site.board_updated_at = "ongoing", datetime.now(UTC)
        if ln.new_area_id:
            r = db.get(NewAreaRequest, ln.new_area_id)
            if r is not None and r.status == "pending":
                emit(
                    db,
                    "dpr_new_area",
                    subject=f"new_area:{r.id}",
                    site_id=d.site_id,
                    actor_id=actor_id,
                    data={"area": r.name},
                )


def dpr_reviewed(db: Session, d, actor_id) -> None:
    emit(
        db,
        "dpr_reviewed",
        subject=f"dpr:{d.id}",
        site_id=d.site_id,
        actor_id=actor_id,
        dedupe=f"dpr_reviewed:{d.id}:{d.status}:{label(d.acknowledged_at or d.returned_at)}",
        data={"status": d.status},
    )


def new_area_decided(db: Session, r, actor_id) -> None:
    emit(
        db,
        "new_area_decided",
        subject=f"new_area:{r.id}",
        site_id=r.site_id,
        actor_id=actor_id,
        data={"status": r.status},
    )


# --- stage done, bills, payment -------------------------------------------------------------------


def _boq_unit(db: Session, boq_line_id) -> str:
    from app.tenders.models import BoqLine  # noqa: PLC0415

    b = db.get(BoqLine, boq_line_id) if boq_line_id else None
    return (b.unit if b else None) or "sqm"


def stage_done(db: Session, item) -> None:
    from app.sitecontrol.service import node_label  # noqa: PLC0415
    from app.sites.models import AreaScope, SiteNode, StageTemplate  # noqa: PLC0415

    st = db.get(StageTemplate, item.stage_template_id) if item.stage_template_id else None
    emit(
        db,
        "stage_done",
        subject=f"ready:{item.id}",
        site_id=item.site_id,
        data={
            "ready_id": item.id,
            "area": node_label(db, db.get(SiteNode, item.node_id)),
            "stage": st.name if st else "the stage",
            "qty": _n(item.qty),
            "unit": item.unit or _boq_unit(db, item.boq_line_id),
            "date": label(item.created_at or datetime.now(UTC), "%d %b %Y"),
        },
    )
    # the last stage of the site: the final bill
    left = db.scalar(
        select(func.count()).where(
            AreaScope.site_id == item.site_id, AreaScope.progress_percent < 100
        )
    )
    if not left:
        from app.sites.models import Site  # noqa: PLC0415

        site = db.get(Site, item.site_id)
        if site is not None:
            site.board_status, site.board_updated_at = "completed_to_bill", datetime.now(UTC)
        emit(
            db,
            "last_stage_done",
            subject=f"site:{item.site_id}",
            site_id=item.site_id,
            dedupe=f"last_stage_done:{item.site_id}",
            data={},
        )


def bill_sent(db: Session, ra, actor_id) -> None:
    from app.sitecontrol.models import ReadyToBill  # noqa: PLC0415

    emit(
        db,
        "bill_sent",
        subject=f"ra:{ra.id}",
        site_id=ra.site_id,
        actor_id=actor_id,
        data={"bill": ra.code, "amount": _money(ra.net or ra.gross)},
    )
    for item in db.scalars(select(ReadyToBill).where(ReadyToBill.ra_bill_id == ra.id)):
        emit(
            db,
            "stage_billed",
            subject=f"ready:{item.id}",
            site_id=ra.site_id,
            actor_id=actor_id,
            data={"bill": ra.code},
        )
    emit(
        db,
        "site_billed",
        subject=f"site:{ra.site_id}",
        site_id=ra.site_id,
        actor_id=actor_id,
        dedupe=f"site_billed:{ra.id}",
        data={"bill": ra.code},
    )


def bill_certified(db: Session, ra, actor_id) -> None:
    emit(
        db,
        "bill_certified",
        subject=f"ra:{ra.id}",
        site_id=ra.site_id,
        actor_id=actor_id,
        dedupe=f"bill_certified:{ra.id}:{label(ra.certified_at)}",
        data={"bill": ra.code},
    )
    billed = sum((Decimal(ln.qty) * Decimal(ln.rate) for ln in ra.lines), Decimal(0))
    certified = sum(
        (
            Decimal(ln.certified_qty if ln.certified_qty is not None else ln.qty) * Decimal(ln.rate)
            for ln in ra.lines
        ),
        Decimal(0),
    )
    if certified < billed:
        emit(
            db,
            "cert_differs",
            subject=f"ra:{ra.id}",
            site_id=ra.site_id,
            actor_id=actor_id,
            dedupe=f"cert_differs:{ra.id}:{label(ra.certified_at)}",
            data={"bill": ra.code, "certified": _money(certified), "billed": _money(billed)},
        )


def diff_reason_given(db: Session, ra_id: int, site_id: int, actor_id) -> None:
    emit(
        db,
        "diff_reason_given",
        subject=f"ra:{ra_id}",
        site_id=site_id,
        actor_id=actor_id,
        dedupe=f"diff_reason:{ra_id}:{datetime.now(UTC).timestamp()}",
        data={},
    )


def payment_received(db: Session, receipt, site_id: int | None, client: str) -> None:
    emit(
        db,
        "payment_received",
        subject=f"receipt:{receipt.id}",
        site_id=site_id,
        data={"client": client, "amount": _money(receipt.amount)},
    )


def labour_bill_entered(db: Session, b) -> None:
    from app.execution.models import WorkOrder  # noqa: PLC0415

    wo = db.get(WorkOrder, b.wo_id)
    p = b.productivity or {}
    check = (
        f"{_n(p.get('actual'))} against {_n(p.get('expected'))} sqm per man-day"
        if p.get("expected") and p.get("actual") is not None
        else f"no man-days recorded; {_n(p.get('expected'))} sqm per man-day expected"
        if p.get("expected")
        else (b.productivity_status or "no check").replace("_", " ")
    )
    emit(
        db,
        "labour_bill_entered",
        subject=f"subcon:{b.id}",
        site_id=wo.site_id,
        data={
            "bill": b.number,
            "contractor": wo.subcontractor.name,
            "check": check,
            "flagged": b.productivity_status == "low",
        },
    )


def labour_checked(db: Session, b, actor_id) -> None:
    emit(db, "labour_checked", subject=f"subcon:{b.id}", actor_id=actor_id, data={})


def labour_decided(db: Session, b, actor_id) -> None:
    emit(db, "labour_decided", subject=f"subcon:{b.id}", actor_id=actor_id, data={})


# --- the clock ------------------------------------------------------------------------------------


def timed_events(db: Session, at: datetime) -> int:
    """Follow-ups due (the quotation schedule), the monthly RA day per ongoing site with
    measured work not billed, and the week's consumption flags per site."""
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import ClientContract, ContractLine, RaBill  # noqa: PLC0415
    from app.quotations.models import Quotation, QuotationFollowUp  # noqa: PLC0415
    from app.sitecontrol import service as sc  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415
    from app.team.service import book_total  # noqa: PLC0415
    from app.team.service import settings as team_settings  # noqa: PLC0415

    day = at.astimezone(IST).date()
    n = 0
    for f, q in db.execute(
        select(QuotationFollowUp, Quotation)
        .join(Quotation, Quotation.id == QuotationFollowUp.quotation_id)
        .where(QuotationFollowUp.status == "open", QuotationFollowUp.due_on <= day)
    ).all():
        n += bool(
            emit(
                db,
                "followup_due",
                subject=f"followup:{f.id}",
                site_id=q.site_id,
                at=at,
                data={
                    "quotation": f"{q.code} R{q.revision}",
                    "quotation_id": q.id,
                    "client": q.client_firm,
                    "day": f.day,
                    "salesperson_id": f.salesperson_id or q.salesperson_id,
                },
            )
        )
    if day.day >= team_settings(db).billing_day:
        month_start = datetime(day.year, day.month, 1, tzinfo=IST)
        for c in db.scalars(select(ClientContract)):
            site = db.get(Site, c.site_id)
            if (
                site is None
                or site.is_demo
                or (site.status != "active" and site.board_status != "ongoing")
            ):
                continue
            unbilled = sum(
                (
                    max(Decimal(0), book_total(db, cl.id) - fsvc.billed_before(db, cl.id, None))
                    for cl in db.scalars(
                        select(ContractLine).where(ContractLine.contract_id == c.id)
                    )
                ),
                Decimal(0),
            )
            if unbilled > 0 and not db.scalar(
                select(RaBill.id)
                .where(RaBill.contract_id == c.id, RaBill.created_at >= month_start)
                .limit(1)
            ):
                n += bool(
                    emit(
                        db,
                        "monthly_ra_due",
                        subject=f"site:{site.id}",
                        site_id=site.id,
                        at=at,
                        dedupe=f"monthly_ra_due:{site.id}:{day:%Y-%m}",
                        data={},
                    )
                )
    week = f"{at.isocalendar().year}-W{at.isocalendar().week:02d}"
    for site in db.scalars(select(Site).where(Site.status == "active", Site.is_demo.is_(False))):
        flags = sum(1 for r in sc.consumption(db, site.id) if r["flag"])
        if flags:
            n += bool(
                emit(
                    db,
                    "consumption_high",
                    subject=f"consumption:{site.id}",
                    site_id=site.id,
                    at=at,
                    dedupe=f"consumption_high:{site.id}:{week}",
                    data={"flags": flags},
                )
            )
    return n
