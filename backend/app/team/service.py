# ruff: noqa: E501  (queries read better unwrapped)
"""Team roles and workspaces: who decides a won job, the send checklist, the site status board,
the measurement book, material plans, client bill tracking and the closure scorecard."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.masters.models import Product
from app.models import Role, RolePermission, User, UserRole
from app.sites.models import AreaScope, Site, SiteMember, SiteNode, Task
from app.team.models import JobAssignment, Measurement, TeamSettings, UserGrant
from app.tenders.models import BoqLine, Tender, TenderTc

ZERO = Decimal(0)


def now() -> datetime:
    return datetime.now(UTC)


def settings(db: Session) -> TeamSettings:
    s = db.get(TeamSettings, 1)
    if s is None:
        s = TeamSettings(id=1)
        db.add(s)
        db.flush()
    return s


def holders(db: Session, code: str) -> list[uuid.UUID]:
    """Active users holding a permission through a role or a grant."""
    by_role = (
        select(UserRole.user_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(RolePermission.permission_code == code)
    )
    by_grant = select(UserGrant.user_id).where(UserGrant.permission_code == code)
    return list(
        db.scalars(
            select(User.id).where(User.is_active, or_(User.id.in_(by_role), User.id.in_(by_grant)))
        )
    )


def role_users(db: Session, *codes: str) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code.in_(codes), User.is_active)
            .distinct()
        )
    )


# --- who handles a won job -----------------------------------------------------------------------


def on_win(db: Session, tender: Tender, site: Site | None, user_id, quotation=None) -> None:
    """A won quotation or tender: a decision for the director (or planning, when allowed) to pick
    its salesperson and site engineer. One per tender."""
    from app.portal.service import notify  # noqa: PLC0415

    if db.scalar(select(JobAssignment.id).where(JobAssignment.tender_id == tender.id)):
        return
    lead_id = quotation.lead_id if quotation is not None else None
    a = JobAssignment(
        title=(quotation.project if quotation is not None else tender.name)[:300],
        quotation_id=quotation.id if quotation is not None else None,
        tender_id=tender.id,
        lead_id=lead_id,
        site_id=site.id if site else None,
        salesperson_id=(quotation.salesperson_id if quotation is not None else None)
        or tender.owner_id,
    )
    db.add(a)
    db.flush()
    notify(
        db,
        holders(db, "jobs.assign"),
        "job_won",
        f"Won: {a.title}. Pick the salesperson and the site engineer",
        link="/my-work",
        site_id=a.site_id,
    )


def decide(db: Session, a: JobAssignment, salesperson_id, engineer_id, user_id) -> JobAssignment:
    """The site is made or linked, both become its members (the engineer as in-charge), it goes on
    the status board as upcoming, and the salesperson gets the first site visit to do."""
    from app.material import service as material  # noqa: PLC0415
    from app.portal.service import notify  # noqa: PLC0415
    from app.sites import service as site_service  # noqa: PLC0415

    if a.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already decided")
    for uid in (salesperson_id, engineer_id):
        if db.get(User, uid) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown user")
    tender = db.get(Tender, a.tender_id) if a.tender_id else None
    site = db.get(Site, a.site_id) if a.site_id else None
    if site is None and tender is not None:
        site = db.scalar(select(Site).where(Site.tender_id == tender.id))
    if site is None:
        site = Site(
            code=site_service.next_code(db),
            name=(tender.site_name or tender.name) if tender else a.title,
            client_id=tender.client_id if tender else None,
            tender_id=tender.id if tender else None,
            city=tender.site_city if tender else None,
            state=tender.site_state if tender else None,
            status="planned",
            created_by=user_id,
        )
        db.add(site)
        db.flush()
        material.site_store(db, site, user_id)
    site.site_incharge_id = engineer_id
    for uid, role in ((salesperson_id, "sales"), (engineer_id, "incharge")):
        m = db.scalar(
            select(SiteMember).where(SiteMember.site_id == site.id, SiteMember.user_id == uid)
        )
        if m is None:
            db.add(SiteMember(site_id=site.id, user_id=uid, role_on_site=role, created_by=user_id))
    if site.board_status is None:
        site.board_status, site.board_updated_at, site.board_updated_by = "upcoming", now(), user_id
    if tender is not None:
        tender.owner_id = salesperson_id
    if a.quotation_id:
        from app.quotations.models import Quotation  # noqa: PLC0415

        q = db.get(Quotation, a.quotation_id)
        if q is not None:
            q.salesperson_id = salesperson_id
            q.site_id = q.site_id or site.id
    a.site_id = site.id
    a.salesperson_id, a.engineer_id = salesperson_id, engineer_id
    a.status, a.decided_by, a.decided_at = "done", user_id, now()
    db.flush()
    notify(
        db,
        [salesperson_id],
        "first_visit",
        f"{site.code} {site.name} is yours: log the first site visit",
        link=f"/sites/{site.id}?visit=1",
        site_id=site.id,
    )
    notify(
        db,
        [engineer_id],
        "site_assigned",
        f"You are the site engineer of {site.code} {site.name}",
        link=f"/sites/{site.id}",
        site_id=site.id,
    )
    return a


# --- the send checklist --------------------------------------------------------------------------

OUR_SCOPE = ("our_scope", "applicator")


def tender_send_check(db: Session, tender: Tender) -> list[str]:
    """Every quoted line has a product and its manufacturer, the guarantee years are filled, and
    our scope and the client's scope come from the T&C library."""
    from app.masters.models import TcClause  # noqa: PLC0415

    missing = []
    lines = db.scalars(
        select(BoqLine).where(BoqLine.tender_id == tender.id, BoqLine.status != "not_quoted")
    ).all()
    no_product = [ln for ln in lines if not (ln.our_product or "").strip()]
    no_make = [ln for ln in lines if not (ln.manufacturer or "").strip()]
    if no_product:
        missing.append(f"{len(no_product)} line(s) without our product")
    if no_make:
        missing.append(f"{len(no_make)} line(s) without the manufacturer")
    if not tender.guarantee_years:
        missing.append("Guarantee years not filled")
    cats = set(
        db.scalars(
            select(TcClause.category)
            .join(TenderTc, TenderTc.clause_id == TcClause.id)
            .where(TenderTc.tender_id == tender.id)
        )
    )
    if not cats & set(OUR_SCOPE):
        missing.append("Our scope not attached from the T&C library")
    if "client_scope" not in cats:
        missing.append("The client's scope not attached from the T&C library")
    return missing


def quotation_send_check(q) -> list[str]:
    missing = []
    if not q.guarantee_years:
        missing.append("Guarantee years not filled")
    cats = {t.get("category") for t in q.terms or []}
    if not cats & set(OUR_SCOPE):
        missing.append("Our scope not attached from the T&C library")
    if "client_scope" not in cats:
        missing.append("The client's scope not attached from the T&C library")
    return missing


def enforce_send_check(
    db: Session, principal: Principal, missing: list[str], override_reason: str | None, what: str
) -> dict | None:
    """Missing items block sending; the director (sendcheck.override) can send anyway with a
    reason, which is logged. Returns the override record for the audit log."""
    if not missing:
        return None
    reason = (override_reason or "").strip()
    if not reason:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{what} cannot be sent yet: " + "; ".join(missing),
        )
    if "sendcheck.override" not in principal.permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the director can send past the checklist"
        )
    if len(reason) < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the reason")
    return {"override": reason, "missing": missing}


# --- the site status board -----------------------------------------------------------------------


def site_people(db: Session, site: Site) -> dict:
    members = db.execute(
        select(SiteMember.role_on_site, User.full_name)
        .join(User, User.id == SiteMember.user_id)
        .where(SiteMember.site_id == site.id)
    ).all()
    by = defaultdict(list)
    for role, name in members:
        by[role].append(name)
    engineer = db.get(User, site.site_incharge_id) if site.site_incharge_id else None
    return {
        "salesperson": ", ".join(by["sales"]) or None,
        "site_engineer": engineer.full_name if engineer else (", ".join(by["incharge"]) or None),
        "supervisor": ", ".join(by["supervisor"]) or None,
    }


def last_update(db: Session, site: Site) -> datetime | None:
    from app.execution.models import Dpr  # noqa: PLC0415

    dates = [
        site.board_updated_at,
        db.scalar(select(func.max(Dpr.updated_at)).where(Dpr.site_id == site.id)),
        db.scalar(select(func.max(Task.updated_at)).where(Task.site_id == site.id)),
    ]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def board_rows(db: Session, site_ids: list[int] | None) -> list[dict]:
    q = select(Site).where(Site.status != "closed", Site.is_demo.is_(False)).order_by(Site.code)
    if site_ids is not None:
        q = q.where(Site.id.in_(site_ids or [-1]))
    out = []
    for s in db.scalars(q):
        out.append(
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "status": s.status,
                "column": s.board_status,
                "progress_percent": s.progress_percent,
                "last_update": last_update(db, s),
                **site_people(db, s),
            }
        )
    return out


# --- the measurement book ------------------------------------------------------------------------


def book_total(db: Session, contract_line_id: int) -> Decimal:
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(Measurement.qty), 0)).where(
                Measurement.contract_line_id == contract_line_id
            )
        )
    )


def book_from_ready(db: Session, ready, user_id=None) -> Measurement | None:
    """A finished stage goes into the book with its source (the survey's method, camera when the
    sizes came only from the camera)."""
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.survey.models import SurveyArea  # noqa: PLC0415

    if not ready.contract_line_id or db.scalar(
        select(Measurement.id).where(Measurement.ready_id == ready.id)
    ):
        return None
    cl = db.get(ContractLine, ready.contract_line_id)
    source = "camera" if ready.camera_only else "manual"
    area = db.scalar(select(SurveyArea).where(SurveyArea.node_id == ready.node_id).limit(1))
    if area is not None and not ready.camera_only:
        source = {"laser": "laser", "ar": "camera", "marker": "camera", "cad": "autocad"}.get(
            area.method, "manual"
        )
    m = Measurement(
        site_id=ready.site_id,
        contract_line_id=ready.contract_line_id,
        node_id=ready.node_id,
        survey_area_id=area.id if area else None,
        ready_id=ready.id,
        description=(cl.description if cl else "Stage done")[:500],
        qty=ready.qty,
        unit=ready.unit,
        source=source,
        measured_on=date.today(),
        measured_by=user_id,
        note="Stage done (ready to bill)",
        created_by=user_id,
    )
    db.add(m)
    db.flush()
    return m


# --- material plan -------------------------------------------------------------------------------


def material_plan(db: Session, site: Site, by: str = "stage") -> dict:
    """Per stage (BOQ item) or month: the planned quantity of each product from the survey
    quantities (area scopes) and the system's consumption, and what of it is on ready work
    fronts; per product: indented, delivered, issued, the balance and what to indent."""
    from app.material.models import (
        Indent,
        IndentLine,
        SiteIssue,
        SiteIssueLine,
        StockLedger,
        Store,  # noqa: PLC0415
    )
    from app.sitecontrol.service import _expected_per_sqm  # noqa: PLC0415

    groups: dict[str, dict] = {}
    totals: dict[int, dict] = {}
    for sc, boq in db.execute(
        select(AreaScope, BoqLine)
        .join(BoqLine, BoqLine.id == AreaScope.boq_line_id)
        .where(AreaScope.site_id == site.id)
    ).all():
        if not boq.system_id:
            continue
        node = db.get(SiteNode, sc.node_id)
        ready = bool(node and node.front_ready)
        if by == "month":
            start = db.scalar(
                select(func.min(Task.planned_start)).where(Task.area_scope_id == sc.id)
            )
            key = start.strftime("%Y-%m") if start else "unscheduled"
            label = start.strftime("%b %Y") if start else "Not scheduled"
        else:
            key, label = f"boq{boq.id}", (boq.client_item_no or "") + " " + boq.description[:80]
        g = groups.setdefault(key, {"key": key, "label": label.strip(), "rows": {}})
        for product_id, per in _expected_per_sqm(db, boq.system_id).items():
            qty = Decimal(sc.qty) * per
            r = g["rows"].setdefault(product_id, {"planned": ZERO, "ready": ZERO})
            r["planned"] += qty
            t = totals.setdefault(product_id, {"planned": ZERO, "ready": ZERO})
            t["planned"] += qty
            if ready:
                r["ready"] += qty
                t["ready"] += qty
    store_ids = list(db.scalars(select(Store.id).where(Store.site_id == site.id)))
    indented = dict(
        db.execute(
            select(IndentLine.product_id, func.sum(IndentLine.base_qty))
            .join(Indent, Indent.id == IndentLine.indent_id)
            .where(Indent.site_id == site.id, Indent.status.notin_(("cancelled", "rejected")))
            .group_by(IndentLine.product_id)
        ).all()
    )
    delivered = dict(
        db.execute(
            select(StockLedger.product_id, func.sum(StockLedger.qty))
            .where(
                StockLedger.store_id.in_(store_ids or [-1]),
                StockLedger.ref_type.in_(("grn", "transfer_in")),
            )
            .group_by(StockLedger.product_id)
        ).all()
    )
    issued: dict[int, Decimal] = defaultdict(Decimal)
    for kind, product_id, qty in db.execute(
        select(SiteIssue.kind, SiteIssueLine.product_id, SiteIssueLine.qty)
        .join(SiteIssueLine, SiteIssueLine.issue_id == SiteIssue.id)
        .where(SiteIssue.site_id == site.id)
    ):
        issued[product_id] += Decimal(qty) * (-1 if kind == "return" else 1)

    def q3(v) -> Decimal:
        return Decimal(v or 0).quantize(Decimal("0.001"))

    products = []
    for pid in sorted(set(totals) | set(indented) | set(issued), key=lambda p: p or 0):
        if pid is None:
            continue
        p = db.get(Product, pid)
        t = totals.get(pid, {"planned": ZERO, "ready": ZERO})
        ind = Decimal(indented.get(pid) or 0)
        products.append(
            {
                "product_id": pid,
                "product": p.name,
                "unit": p.unit,
                "planned": q3(t["planned"]),
                "ready": q3(t["ready"]),
                "indented": q3(ind),
                "delivered": q3(delivered.get(pid)),
                "issued": q3(issued.get(pid)),
                "balance": q3(t["planned"] - Decimal(issued.get(pid) or 0)),
                "to_indent": q3(max(ZERO, t["ready"] - ind)),
            }
        )
    out_groups = []
    for g in sorted(groups.values(), key=lambda x: x["key"]):
        out_groups.append(
            {
                "key": g["key"],
                "label": g["label"],
                "rows": [
                    {
                        "product_id": pid,
                        "product": db.get(Product, pid).name,
                        "unit": db.get(Product, pid).unit,
                        "planned": q3(r["planned"]),
                        "ready": q3(r["ready"]),
                    }
                    for pid, r in g["rows"].items()
                ],
            }
        )
    return {"site_id": site.id, "by": by, "groups": out_groups, "products": products}


# --- the closure scorecard -----------------------------------------------------------------------


def scorecard(db: Session, user_ids: list[uuid.UUID] | None = None) -> list[dict]:
    """Per salesperson: quotations sent, won, lost (with reasons), the closure rate against the
    target, and follow-ups done on time."""
    from app.quotations.models import Quotation, QuotationFollowUp  # noqa: PLC0415

    target_default = Decimal(settings(db).closure_target_percent)
    people = user_ids
    if people is None:
        people = list(
            dict.fromkeys(
                [
                    *role_users(db, "sales"),
                    *db.scalars(
                        select(Quotation.salesperson_id)
                        .where(Quotation.salesperson_id.is_not(None))
                        .distinct()
                    ),
                ]
            )
        )
    out = []
    for uid in people:
        u = db.get(User, uid)
        if u is None or (u.is_demo and user_ids is None):
            continue
        qs = db.scalars(
            select(Quotation).where(Quotation.salesperson_id == uid, Quotation.is_latest)
        ).all()
        sent = [
            q
            for q in qs
            if q.sent_at is not None
            or q.status in ("sent", "negotiation", "won", "lost", "expired")
        ]
        won = [q for q in qs if q.status == "won"]
        lost = [q for q in qs if q.status == "lost"]
        reasons: dict[str, int] = defaultdict(int)
        for q in lost:
            reasons[q.lost_reason or "not given"] += 1
        decided = len(won) + len(lost)
        rate = (Decimal(len(won)) * 100 / decided).quantize(Decimal("0.1")) if decided else None
        fus = db.scalars(
            select(QuotationFollowUp).where(QuotationFollowUp.salesperson_id == uid)
        ).all()
        due = [f for f in fus if f.due_on <= date.today() and f.status != "cancelled"]
        on_time = [
            f
            for f in due
            if f.status == "done" and f.done_at is not None and f.done_at.date() <= f.due_on
        ]
        target = (
            Decimal(u.closure_target_percent)
            if u.closure_target_percent is not None
            else target_default
        )
        out.append(
            {
                "user_id": str(uid),
                "name": u.full_name,
                "sent": len(sent),
                "won": len(won),
                "lost": len(lost),
                "lost_reasons": dict(reasons),
                "closure_percent": rate,
                "target_percent": target,
                "on_target": rate is not None and rate >= target,
                "followups_due": len(due),
                "followups_on_time": len(on_time),
            }
        )
    return out
