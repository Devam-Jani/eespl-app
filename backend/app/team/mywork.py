# ruff: noqa: E501  (item texts read better unwrapped)
"""My work: each role's to-do list, built from what the app already knows. Every row has the item,
why it is waiting, its age and one action. A person with two roles sees both lists; nothing from a
role they do not hold."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.sites.models import Site, SiteMember, SiteNode
from app.team import service as team
from app.team.models import JobAssignment
from app.timefmt import IST

Item = dict


def today() -> date:
    return datetime.now(IST).date()


def _age(at) -> int | None:
    if at is None:
        return None
    d = at.astimezone(IST).date() if isinstance(at, datetime) else at
    return max(0, (today() - d).days)


def item(
    source: str,
    key: str,
    title: str,
    why: str,
    link: str,
    action: str,
    at=None,
    severity: str = "normal",
    menu: str | None = None,
) -> Item:
    return {
        "source": source,
        "key": f"{source}:{key}",
        "title": title,
        "why": why,
        "age_days": _age(at),
        "link": link,
        "action": action,
        "severity": severity,
        "menu": menu or link.split("?")[0].rsplit("/", 1)[0]
        if link.count("/") > 1
        else (menu or link.split("?")[0]),
    }


def my_sites(db: Session, user_id: uuid.UUID) -> list[int]:
    """Sites where the person is the in-charge or a member (the site roles' scope)."""
    return list(
        db.scalars(
            select(Site.id).where(
                Site.status != "closed",
                or_(
                    Site.site_incharge_id == user_id,
                    Site.id.in_(select(SiteMember.site_id).where(SiteMember.user_id == user_id)),
                ),
            )
        )
    )


# --- director ------------------------------------------------------------------------------------


def director(db: Session, p: Principal) -> list[Item]:
    from app.analytics.models import Alert, WeeklyReport  # noqa: PLC0415
    from app.finance.models import SubconBill, VendorBill  # noqa: PLC0415
    from app.material.models import PoLine, PurchaseOrder  # noqa: PLC0415

    out = []
    for a in db.scalars(select(JobAssignment).where(JobAssignment.status == "pending")):
        out.append(
            item(
                "assign",
                str(a.id),
                f"Won: {a.title}",
                "Pick the salesperson and the site engineer",
                f"/assignments/{a.id}",
                "Assign",
                a.created_at,
                "warn",
                "/my-work",
            )
        )
    for b in db.scalars(
        select(SubconBill).where(
            SubconBill.status == "draft",
            SubconBill.productivity_status == "low",
            SubconBill.productivity_override_at.is_(None),
        )
    ):
        out.append(
            item(
                "labour_override",
                str(b.id),
                f"Labour bill {b.number}",
                f"Productivity low ({(b.productivity or {}).get('actual')} against {(b.productivity or {}).get('expected')} sqm per man-day): approve or not",
                "/payables?tab=subcon",
                "Decide",
                b.created_at,
                "warn",
                "/payables",
            )
        )
    for po in db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.status == "pending_approval",
            PurchaseOrder.id.in_(select(PoLine.po_id).where(PoLine.rate_reason.is_not(None))),
        )
    ):
        out.append(
            item(
                "rate_override",
                str(po.id),
                f"PO {po.code}",
                "A rate above the vendor's contract, with a reason: approve or not",
                f"/purchase-orders/{po.id}",
                "Review",
                po.created_at,
                "warn",
                "/purchase-orders",
            )
        )
    for b in db.scalars(
        select(VendorBill).where(VendorBill.released_at.is_(None), VendorBill.status == "draft")
    ):
        if b.blocked_reasons:
            out.append(
                item(
                    "blocked_bill",
                    str(b.id),
                    f"Vendor bill {b.number}",
                    "Blocked by the three-way match: release with a reason or wait",
                    "/payables",
                    "Review",
                    b.created_at,
                    "danger",
                    "/payables",
                )
            )
    late = today() - timedelta(days=14)
    for s in db.scalars(
        select(Site).where(
            Site.status.in_(("planned", "active")),
            Site.target_date.is_not(None),
            Site.target_date < late,
            Site.progress_percent < 100,
            Site.is_demo.is_(False),
        )
    ):
        out.append(
            item(
                "late_site",
                str(s.id),
                f"{s.code} {s.name}",
                f"More than 2 weeks late (target {s.target_date:%d %b}), {Decimal(s.progress_percent):.0f}% done",
                f"/sites/{s.id}",
                "Open site",
                s.target_date,
                "danger",
                "/sites",
            )
        )
    for a in db.scalars(
        select(Alert).where(
            Alert.rule == "budget_head", Alert.closed_at.is_(None), Alert.acknowledged_at.is_(None)
        )
    ):
        out.append(
            item(
                "margin",
                str(a.id),
                a.title,
                "Margin alert: a budget head is over",
                a.link or "/alerts",
                "Open",
                a.created_at,
                "warn",
                "/alerts",
            )
        )
    wr = db.scalar(select(WeeklyReport).order_by(WeeklyReport.week_start.desc()).limit(1))
    if wr is not None and _age(wr.generated_at) is not None and _age(wr.generated_at) <= 7:
        out.append(
            item(
                "monday",
                str(wr.id),
                f"Monday summary, week of {wr.week_start:%d %b}",
                "The week's figures for the director",
                "/analytics/reports",
                "Read",
                wr.generated_at,
                "normal",
                "/my-work",
            )
        )
    return out


# --- planning ------------------------------------------------------------------------------------


def planning(db: Session, p: Principal) -> list[Item]:
    from app.crm.models import Lead  # noqa: PLC0415
    from app.material.models import Indent  # noqa: PLC0415
    from app.sitecontrol import service as sc  # noqa: PLC0415
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import DeliveryNote, NewAreaRequest  # noqa: PLC0415
    from app.tenders.models import Tender, TenderRevision  # noqa: PLC0415

    out = []
    for lead in db.scalars(
        select(Lead).where(
            Lead.owner_id.is_(None), Lead.status.in_(("new", "contacted")), Lead.is_demo.is_(False)
        )
    ):
        out.append(
            item(
                "unassigned_lead",
                str(lead.id),
                f"Enquiry {lead.code}: {lead.contact_name}",
                "Not allocated to a salesperson",
                f"/enquiries?lead={lead.id}",
                "Allocate",
                lead.created_at,
                "warn",
                "/enquiries",
            )
        )
    for a in db.scalars(select(JobAssignment).where(JobAssignment.status == "pending")):
        out.append(
            item(
                "won_unassigned",
                str(a.id),
                f"Won: {a.title}",
                "No salesperson or site engineer yet (the director decides)",
                f"/assignments/{a.id}",
                "Open",
                a.created_at,
                "warn",
                "/my-work",
            )
        )
    for r in db.scalars(select(NewAreaRequest).where(NewAreaRequest.status == "pending")):
        out.append(
            item(
                "new_area",
                str(r.id),
                f"New area: {r.name}",
                "Asked for from site; approve or move the work",
                "/new-areas",
                "Decide",
                r.requested_at,
                "normal",
                "/new-areas",
            )
        )
    hours = sc_settings(db).escalate_second_hours
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    for dn in db.scalars(
        select(DeliveryNote).where(
            DeliveryNote.status == "dispatched",
            DeliveryNote.confirmed_at.is_(None),
            DeliveryNote.expected_at < cutoff,
        )
    ):
        out.append(
            item(
                "dn_48h",
                str(dn.id),
                f"Delivery {dn.code}",
                f"Not confirmed {hours} h after it was expected",
                f"/deliveries/{dn.id}",
                "Chase",
                dn.expected_at,
                "danger",
                "/deliveries",
            )
        )
    for s in db.scalars(
        select(Site).where(Site.status.in_(("planned", "active")), Site.is_demo.is_(False))
    ):
        ready = db.scalars(
            select(SiteNode).where(SiteNode.site_id == s.id, SiteNode.front_ready)
        ).all()
        if ready:
            since = min((n.front_ready_at for n in ready if n.front_ready_at), default=None)
            has_indent = db.scalar(
                select(Indent.id)
                .where(Indent.site_id == s.id, *([Indent.created_at >= since] if since else []))
                .limit(1)
            )
            if not has_indent:
                out.append(
                    item(
                        "front_no_indent",
                        str(s.id),
                        f"{s.code} {s.name}",
                        f"{len(ready)} work front(s) ready without an indent",
                        f"/sites/{s.id}/material-plan",
                        "Plan material",
                        since,
                        "warn",
                        "/planning/board",
                    )
                )
        flags = sum(1 for r in sc.consumption(db, s.id) if r["flag"])
        if flags:
            out.append(
                item(
                    "consumption",
                    str(s.id),
                    f"{s.code} {s.name}",
                    f"{flags} consumption variance flag(s)",
                    f"/consumption?site={s.id}",
                    "Review",
                    None,
                    "warn",
                    "/consumption",
                )
            )
        if s.board_status is None:
            out.append(
                item(
                    "board_missing",
                    str(s.id),
                    f"{s.code} {s.name}",
                    "Missing from the site status board",
                    "/planning/board",
                    "Place it",
                    s.created_at,
                    "normal",
                    "/planning/board",
                )
            )
    days = team.settings(db).award_followup_days
    for t in db.scalars(
        select(Tender).where(Tender.status == "submitted", Tender.is_demo.is_(False))
    ):
        submitted = db.scalar(
            select(func.max(TenderRevision.submitted_at)).where(TenderRevision.tender_id == t.id)
        )
        last = t.award_followup_at or submitted
        if last is not None and _age(last) >= days:
            out.append(
                item(
                    "award_followup",
                    str(t.id),
                    f"Tender {t.code}: {t.name}",
                    f"Awaiting award; no follow-up for {_age(last)} days",
                    f"/tenders/{t.id}?tab=award",
                    "Follow up",
                    last,
                    "warn",
                    "/tenders",
                )
            )
    return out


# --- billing -------------------------------------------------------------------------------------


def billing(db: Session, p: Principal) -> list[Item]:
    from app.finance.models import ClientContract, ContractLine, RaBill, SubconBill  # noqa: PLC0415
    from app.sitecontrol.models import ReadyToBill  # noqa: PLC0415
    from app.survey.models import Survey, SurveyArea  # noqa: PLC0415

    out = []
    for r in db.scalars(select(ReadyToBill).where(ReadyToBill.status == "open")):
        age = _age(r.created_at)
        out.append(
            item(
                "ready",
                str(r.id),
                "Ready to bill",
                f"A finished stage, {Decimal(r.qty):f} {r.unit or ''} not billed",
                "/ready-to-bill",
                "Bill it",
                r.created_at,
                "danger" if age and age > 7 else "normal",
                "/ready-to-bill",
            )
        )
    s = team.settings(db)
    t = today()
    if t.day >= s.billing_day:
        month_start = t.replace(day=1)
        for c in db.scalars(select(ClientContract)):
            site = db.get(Site, c.site_id)
            if site is None or site.status != "active" and site.board_status != "ongoing":
                continue
            unbilled = Decimal(0)
            from app.finance import service as fsvc  # noqa: PLC0415

            for cl in db.scalars(select(ContractLine).where(ContractLine.contract_id == c.id)):
                unbilled += max(
                    Decimal(0), team.book_total(db, cl.id) - fsvc.billed_before(db, cl.id, None)
                )
            if unbilled <= 0:
                continue
            this_month = db.scalar(
                select(RaBill.id)
                .where(
                    RaBill.contract_id == c.id,
                    RaBill.created_at
                    >= datetime(month_start.year, month_start.month, 1, tzinfo=IST),
                )
                .limit(1)
            )
            if not this_month:
                out.append(
                    item(
                        "ra_due",
                        str(site.id),
                        f"{site.code} {site.name}",
                        f"Monthly RA bill due (the {s.billing_day}th): measured work not billed",
                        f"/sites/{site.id}?tab=finance",
                        "Raise RA bill",
                        None,
                        "warn",
                        "/billing",
                    )
                )
    for b in db.scalars(select(RaBill).where(RaBill.status == "submitted")):
        out.append(
            item(
                "ra_uncertified",
                str(b.id),
                f"RA bill {b.code}",
                "Sent, not certified by the client",
                f"/bill-tracking?site={b.site_id}",
                "Chase",
                b.submitted_at or b.created_at,
                "normal",
                "/bill-tracking",
            )
        )
    for b in db.scalars(
        select(SubconBill).where(
            SubconBill.status == "draft", SubconBill.billing_checked_at.is_(None)
        )
    ):
        flag = b.productivity_status
        out.append(
            item(
                "labour_check",
                str(b.id),
                f"Labour bill {b.number}",
                "Check it against the work done"
                + (" (productivity low: the director decides)" if flag == "low" else ""),
                "/labour-check",
                "Check",
                b.created_at,
                "warn" if flag == "low" else "normal",
                "/labour-check",
            )
        )
    for area, sv in db.execute(
        select(SurveyArea, Survey)
        .join(Survey, Survey.id == SurveyArea.survey_id)
        .where(SurveyArea.method.in_(("ar", "marker")), Survey.site_id.is_not(None))
    ).all():
        out.append(
            item(
                "camera_area",
                str(area.id),
                f"{area.name}",
                "Camera-measured: needs a laser value before billing",
                f"/surveys/{sv.id}",
                "Measure",
                area.created_at if hasattr(area, "created_at") else None,
                "normal",
                "/surveys",
            )
        )
    return out


# --- accounts ------------------------------------------------------------------------------------


def accounts(db: Session, p: Principal) -> list[Item]:
    from app.analytics.models import InvoiceSummary  # noqa: PLC0415
    from app.finance.models import PayrollRun, VendorBill  # noqa: PLC0415

    out = []
    for b in db.scalars(
        select(VendorBill).where(VendorBill.released_at.is_(None), VendorBill.status == "draft")
    ):
        if b.blocked_reasons:
            out.append(
                item(
                    "blocked_bill",
                    str(b.id),
                    f"Vendor bill {b.number}",
                    "Blocked by the three-way match: waiting for the director",
                    "/payables",
                    "Open",
                    b.created_at,
                    "warn",
                    "/payables",
                )
            )
    t = today()
    for inv in db.scalars(
        select(InvoiceSummary).where(
            InvoiceSummary.is_demo.is_(False),
            InvoiceSummary.outstanding > 0,
            InvoiceSummary.due_date.is_not(None),
            InvoiceSummary.due_date <= t + timedelta(days=7),
        )
    ):
        overdue = inv.due_date < t
        out.append(
            item(
                "receipt_due",
                str(inv.invoice_id),
                f"Invoice #{inv.invoice_id}",
                f"₹{Decimal(inv.outstanding):,.0f} {'overdue since' if overdue else 'due on'} {inv.due_date:%d %b}",
                "/receivables",
                "Collect",
                inv.due_date,
                "danger" if overdue else "normal",
                "/receivables",
            )
        )
    nxt = (t.replace(day=1) + timedelta(days=32)).replace(day=1)
    for day, what in ((7, "TDS deposit"), (11, "GSTR-1"), (20, "GSTR-3B")):
        due = t.replace(day=day) if t.day <= day else nxt.replace(day=day)
        if (due - t).days <= 7:
            out.append(
                item(
                    "statutory",
                    f"{what}:{due}",
                    f"{what} due {due:%d %b}",
                    "Statutory due date",
                    "/finance/reports",
                    "Prepare",
                    None,
                    "warn" if (due - t).days <= 3 else "normal",
                    "/finance/reports",
                )
            )
    month = t.strftime("%Y-%m")
    run = db.scalar(select(PayrollRun).where(PayrollRun.month == month))
    if t.day >= 25 and (run is None or run.status == "draft"):
        out.append(
            item(
                "payroll",
                month,
                f"Payroll {t:%b %Y}",
                "Not run yet" if run is None else "Still a draft",
                "/payroll",
                "Run payroll",
                None,
                "warn",
                "/payroll",
            )
        )
    return out


# --- sales ---------------------------------------------------------------------------------------


def sales(db: Session, p: Principal) -> list[Item]:
    from app.crm.models import Lead  # noqa: PLC0415
    from app.quotations.models import Quotation, QuotationFollowUp  # noqa: PLC0415

    me = p.user.id
    out = []
    t = today()
    for f, q in db.execute(
        select(QuotationFollowUp, Quotation)
        .join(Quotation, Quotation.id == QuotationFollowUp.quotation_id)
        .where(
            QuotationFollowUp.salesperson_id == me,
            QuotationFollowUp.status == "open",
            QuotationFollowUp.due_on <= t,
        )
    ).all():
        out.append(
            item(
                "followup",
                str(f.id),
                f"{q.code} {q.client_firm}",
                "Follow-up due today"
                if f.due_on == t
                else f"Follow-up overdue since {f.due_on:%d %b}",
                f"/quotations/{q.id}",
                "Follow up",
                f.due_on,
                "danger" if f.due_on < t else "normal",
                "/quotations",
            )
        )
    for lead in db.scalars(
        select(Lead).where(
            Lead.owner_id == me,
            Lead.status.notin_(("won", "lost", "junk")),
            Lead.next_follow_up.is_not(None),
            Lead.next_follow_up <= t,
        )
    ):
        out.append(
            item(
                "lead_followup",
                str(lead.id),
                f"{lead.code} {lead.contact_name}",
                f"Lead follow-up {'due today' if lead.next_follow_up == t else 'overdue'}",
                f"/leads/{lead.id}",
                "Follow up",
                lead.next_follow_up,
                "normal",
                "/leads",
            )
        )
    for lead in db.scalars(select(Lead).where(Lead.owner_id == me, Lead.status == "new")):
        out.append(
            item(
                "lead_new",
                str(lead.id),
                f"{lead.code} {lead.contact_name}",
                "New enquiry allocated to you: contact the client",
                f"/leads/{lead.id}",
                "Call",
                lead.created_at,
                "normal",
                "/leads",
            )
        )
    for q in db.scalars(
        select(Quotation).where(
            Quotation.salesperson_id == me,
            Quotation.is_latest,
            Quotation.status.in_(("sent", "negotiation")),
        )
    ):
        left = (q.quote_date + timedelta(days=q.validity_days) - t).days
        if 0 <= left <= 5:
            out.append(
                item(
                    "expiring",
                    str(q.id),
                    f"{q.code} {q.client_firm}",
                    f"Expires in {left} day(s)",
                    f"/quotations/{q.id}",
                    "Extend or close",
                    q.sent_at,
                    "warn",
                    "/quotations",
                )
            )
        if q.status == "negotiation":
            out.append(
                item(
                    "negotiation",
                    str(q.id),
                    f"{q.code} {q.client_firm}",
                    "Negotiation open",
                    f"/quotations/{q.id}?tab=negotiation",
                    "Log / revise",
                    q.sent_at,
                    "normal",
                    "/quotations",
                )
            )
    for a in db.scalars(
        select(JobAssignment).where(
            JobAssignment.salesperson_id == me,
            JobAssignment.status == "done",
            JobAssignment.first_visit_id.is_(None),
        )
    ):
        out.append(
            item(
                "first_visit",
                str(a.id),
                a.title,
                "New project: the first site visit is not logged",
                f"/sites/{a.site_id}?visit=1",
                "Log visit",
                a.decided_at,
                "warn",
                "/sites",
            )
        )
    card = team.scorecard(db, [me])
    if card and card[0]["closure_percent"] is not None and not card[0]["on_target"]:
        c = card[0]
        out.append(
            item(
                "closure",
                "me",
                "Closure rate",
                f"{c['closure_percent']}% against the {c['target_percent']}% target ({c['won']} won of {c['won'] + c['lost']})",
                "/scorecard",
                "See scorecard",
                None,
                "normal",
                "/scorecard",
            )
        )
    return out


# --- estimator -----------------------------------------------------------------------------------


def estimator(db: Session, p: Principal) -> list[Item]:
    from app.tenders.models import BoqLine, Tender  # noqa: PLC0415

    out = []
    t = today()
    for tender in db.scalars(select(Tender).where(Tender.status == "draft")):
        if tender.due_on and tender.due_on <= t + timedelta(days=7):
            out.append(
                item(
                    "tender_due",
                    str(tender.id),
                    f"{tender.code} {tender.name}",
                    f"Due {'today' if tender.due_on == t else ('on ' + tender.due_on.strftime('%d %b')) if tender.due_on > t else 'overdue since ' + tender.due_on.strftime('%d %b')}",
                    f"/tenders/{tender.id}",
                    "Open",
                    tender.due_on,
                    "danger" if tender.due_on < t else "warn",
                    "/tenders",
                )
            )
        unpriced = db.scalar(
            select(func.count()).where(
                BoqLine.tender_id == tender.id, BoqLine.status.in_(("unpriced", "suggested"))
            )
        )
        if unpriced:
            out.append(
                item(
                    "boq_pricing",
                    str(tender.id),
                    f"{tender.code} {tender.name}",
                    f"{unpriced} BOQ line(s) waiting for pricing",
                    f"/tenders/{tender.id}",
                    "Price",
                    tender.created_at,
                    "normal",
                    "/tenders",
                )
            )
        elif db.scalar(select(func.count()).where(BoqLine.tender_id == tender.id)):
            missing = team.tender_send_check(db, tender)
            if missing:
                out.append(
                    item(
                        "send_check",
                        str(tender.id),
                        f"{tender.code} {tender.name}",
                        "Send checklist: " + "; ".join(missing),
                        f"/tenders/{tender.id}",
                        "Fix",
                        tender.created_at,
                        "warn",
                        "/tenders",
                    )
                )
    return out


# --- site engineer -------------------------------------------------------------------------------


def site_engineer(db: Session, p: Principal) -> list[Item]:
    from app.execution.models import Dpr  # noqa: PLC0415
    from app.material.models import Indent  # noqa: PLC0415
    from app.portal.models import Snag  # noqa: PLC0415
    from app.sites.models import AreaScope, Task  # noqa: PLC0415
    from app.survey.models import Survey  # noqa: PLC0415

    sites = my_sites(db, p.user.id)
    out = []
    for d in db.scalars(
        select(Dpr).where(Dpr.site_id.in_(sites or [-1]), Dpr.status == "submitted")
    ):
        site = db.get(Site, d.site_id)
        out.append(
            item(
                "dpr_approve",
                str(d.id),
                f"Daily report {d.on_date:%d %b}, {site.code}",
                "Submitted by the supervisor: approve or return",
                f"/sites/{site.id}?tab=dpr&day={d.on_date}",
                "Review",
                d.submitted_at,
                "normal",
                "/sites",
            )
        )
    for tk in db.scalars(
        select(Task).where(
            Task.site_id.in_(sites or [-1]),
            Task.status == "in_progress",
            Task.progress_percent >= 100,
        )
    ):
        out.append(
            item(
                "stage_done",
                str(tk.id),
                tk.name,
                "At 100%: mark the stage done (quality checklist first)",
                f"/sites/{tk.site_id}?tab=tasks",
                "Mark done",
                tk.updated_at,
                "normal",
                "/sites",
            )
        )
    for sv in db.scalars(
        select(Survey).where(Survey.site_id.in_(sites or [-1]), Survey.status == "draft")
    ):
        out.append(
            item(
                "survey",
                str(sv.id),
                f"Survey {getattr(sv, 'code', sv.id)}",
                "Not finished",
                f"/surveys/{sv.id}",
                "Finish",
                sv.created_at,
                "normal",
                "/surveys",
            )
        )
    for sid in sites:
        site = db.get(Site, sid)
        if site.board_status != "ongoing" and site.status != "active":
            continue
        not_ready = db.scalar(
            select(func.count(func.distinct(SiteNode.id)))
            .join(AreaScope, AreaScope.node_id == SiteNode.id)
            .where(
                SiteNode.site_id == sid,
                SiteNode.front_ready.is_(False),
                AreaScope.progress_percent == 0,
            )
        )
        if not_ready:
            out.append(
                item(
                    "fronts",
                    str(sid),
                    f"{site.code} {site.name}",
                    f"{not_ready} work front(s) to tick when ready",
                    f"/sites/{sid}/fronts",
                    "Tick fronts",
                    None,
                    "normal",
                    "/sites",
                )
            )
    for sn in db.scalars(
        select(Snag).where(
            Snag.site_id.in_(sites or [-1]), Snag.status.in_(("open", "in_progress"))
        )
    ):
        out.append(
            item(
                "snag",
                str(sn.id),
                sn.title,
                f"Snag {sn.status.replace('_', ' ')}",
                f"/snags?site={sn.site_id}",
                "Resolve",
                sn.created_at,
                "warn",
                "/snags",
            )
        )
    for ind in db.scalars(
        select(Indent).where(
            Indent.site_id.in_(sites or [-1]), Indent.status.in_(("draft", "submitted"))
        )
    ):
        out.append(
            item(
                "indent",
                str(ind.id),
                f"Indent {ind.code}",
                "Draft: submit it" if ind.status == "draft" else "Waiting for approval",
                f"/indents/{ind.id}",
                "Open",
                ind.created_at,
                "normal",
                "/indents",
            )
        )
    return out


# --- site supervisor -----------------------------------------------------------------------------


def site_supervisor(db: Session, p: Principal) -> list[Item]:
    from app.execution.models import Attendance, Dpr  # noqa: PLC0415
    from app.material.models import SiteIssue, StockLedger, Store  # noqa: PLC0415
    from app.sitecontrol.models import DeliveryNote  # noqa: PLC0415

    sites = my_sites(db, p.user.id)
    t = today()
    out = []
    end_of_day = datetime(t.year, t.month, t.day, 23, 59, tzinfo=IST)
    for sid in sites:
        site = db.get(Site, sid)
        if not db.scalar(
            select(Attendance.id).where(Attendance.site_id == sid, Attendance.on_date == t).limit(1)
        ):
            out.append(
                item(
                    "attendance",
                    str(sid),
                    f"Attendance, {site.code}",
                    "Not marked today",
                    f"/my-site/{sid}?step=attendance",
                    "Mark",
                    None,
                    "warn",
                    "/my-site",
                )
            )
        d = db.scalar(select(Dpr).where(Dpr.site_id == sid, Dpr.on_date == t))
        if d is None or d.status == "draft":
            out.append(
                item(
                    "dpr_today",
                    str(sid),
                    f"Daily report, {site.code}",
                    "Not submitted today",
                    f"/my-site/{sid}?step=work",
                    "Write",
                    None,
                    "normal",
                    "/my-site",
                )
            )
        for r in db.scalars(select(Dpr).where(Dpr.site_id == sid, Dpr.status == "returned")):
            out.append(
                item(
                    "dpr_returned",
                    str(r.id),
                    f"Daily report {r.on_date:%d %b} returned",
                    r.return_comment or "Returned by the site engineer",
                    f"/sites/{sid}?tab=dpr&day={r.on_date}",
                    "Correct",
                    r.returned_at,
                    "danger",
                    "/my-site",
                )
            )
        for dn in db.scalars(
            select(DeliveryNote).where(
                DeliveryNote.site_id == sid,
                DeliveryNote.status == "dispatched",
                DeliveryNote.expected_at <= end_of_day,
            )
        ):
            out.append(
                item(
                    "delivery",
                    str(dn.id),
                    f"Delivery {dn.code}",
                    "Expected today: count it and confirm"
                    if _age(dn.expected_at) == 0
                    else "Not confirmed yet",
                    f"/deliveries/{dn.id}",
                    "Confirm",
                    dn.expected_at,
                    "warn" if _age(dn.expected_at) else "normal",
                    "/deliveries",
                )
            )
        stores = list(db.scalars(select(Store.id).where(Store.site_id == sid)))
        last_in = db.scalar(
            select(func.max(StockLedger.at)).where(
                StockLedger.store_id.in_(stores or [-1]),
                StockLedger.ref_type.in_(("grn", "transfer_in")),
            )
        )
        last_issue = db.scalar(
            select(func.max(SiteIssue.created_at)).where(SiteIssue.site_id == sid)
        )
        if (
            last_in is not None
            and (last_issue is None or last_issue < last_in)
            and _age(last_in) <= 3
        ):
            out.append(
                item(
                    "issue",
                    str(sid),
                    f"Material at {site.code}",
                    "Received and not issued to the areas yet",
                    f"/my-site/{sid}?step=issue",
                    "Issue",
                    last_in,
                    "normal",
                    "/my-site",
                )
            )
    return out


# --- store and purchase --------------------------------------------------------------------------


def store_purchase(db: Session, p: Principal) -> list[Item]:
    from app.material.models import Indent, PurchaseOrder  # noqa: PLC0415
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import DeliveryNote, RateContract  # noqa: PLC0415

    out = []
    for ind in db.scalars(select(Indent).where(Indent.status.in_(("approved", "partly_ordered")))):
        out.append(
            item(
                "indent_convert",
                str(ind.id),
                f"Indent {ind.code}",
                "Approved: convert to a PO",
                f"/indents/{ind.id}",
                "Make PO",
                ind.approved_at or ind.created_at,
                "normal",
                "/indents",
            )
        )
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "approved")):
        out.append(
            item(
                "po_place",
                str(po.id),
                f"PO {po.code}",
                "Approved: send it to the vendor",
                f"/purchase-orders/{po.id}",
                "Send",
                po.approved_at or po.created_at,
                "normal",
                "/purchase-orders",
            )
        )
    for dn in db.scalars(select(DeliveryNote).where(DeliveryNote.status == "dispatched")):
        out.append(
            item(
                "dn_open",
                str(dn.id),
                f"Delivery {dn.code}",
                "Dispatched, not confirmed at site",
                f"/deliveries/{dn.id}",
                "Chase",
                dn.expected_at,
                "warn" if (_age(dn.expected_at) or 0) >= 1 else "normal",
                "/deliveries",
            )
        )
    days = sc_settings(db).contract_expiry_days
    t = today()
    for c in db.scalars(
        select(RateContract).where(
            RateContract.is_active,
            RateContract.valid_till >= t,
            RateContract.valid_till <= t + timedelta(days=days),
        )
    ):
        out.append(
            item(
                "contract",
                str(c.id),
                f"Rate contract #{c.id}",
                f"Ends {c.valid_till:%d %b}: renew or replace",
                "/rate-contracts",
                "Renew",
                None,
                "warn",
                "/rate-contracts",
            )
        )
    return out


def office_admin(db: Session, p: Principal) -> list[Item]:
    from app.models import User, UserRole  # noqa: PLC0415

    out = []
    for u in db.scalars(
        select(User).where(
            User.is_active, User.is_demo.is_(False), User.id.notin_(select(UserRole.user_id))
        )
    ):
        out.append(
            item(
                "no_role",
                str(u.id),
                u.full_name,
                "Active without a role",
                "/users",
                "Give a role",
                u.created_at,
                "normal",
                "/users",
            )
        )
    return out


SECTIONS: dict[str, tuple[str, Callable[[Session, Principal], list[Item]]]] = {
    "director": ("Director: decisions waiting", director),
    "planning": ("Planning", planning),
    "billing": ("Billing", billing),
    "accounts": ("Accounts", accounts),
    "sales": ("Sales", sales),
    "estimator": ("Estimating", estimator),
    "site_engineer": ("My sites", site_engineer),
    "site_supervisor": ("Today on site", site_supervisor),
    "store_purchase": ("Store and purchase", store_purchase),
    "office_admin": ("Office", office_admin),
}
# the technical owner sees the director's decisions
ALIASES = {"super_admin": "director"}


def build(db: Session, p: Principal) -> dict:
    codes = []
    for r in p.user.roles:
        code = ALIASES.get(r.code, r.code)
        if code in SECTIONS and code not in codes:
            codes.append(code)
    sections = []
    counts: dict[str, int] = {}
    for code in codes:
        title, fn = SECTIONS[code]
        items = fn(db, p)
        items.sort(
            key=lambda i: ({"danger": 0, "warn": 1}.get(i["severity"], 2), -(i["age_days"] or 0))
        )
        sections.append({"role": code, "title": title, "items": items})
        for i in items:
            counts[i["menu"]] = counts.get(i["menu"], 0) + 1
    total = sum(len(s["items"]) for s in sections)
    counts["/my-work"] = total
    return {"sections": sections, "counts": counts, "total": total}
