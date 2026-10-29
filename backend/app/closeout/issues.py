# ruff: noqa: E501
"""The issue log per site: material late, short or damaged, a product discontinued, a bill not
accepted, over-billed or at the wrong rate, quality, leakage, payment, access or handover, a
subcontractor dispute. Members come from the site's allocation (salesperson, site engineer,
planning, billing; accounts on a payment issue). Shared with the client, an issue becomes a portal
snag. A leakage links to the guarantee and the exact area. Marking a product discontinued raises
an issue on every open methodology and site that uses it; the methodology's next version without
the product closes it."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.common import next_code, now, unprocessable
from app.closeout.models import ISSUE_CATEGORIES, ISSUE_STATUSES, IssueComment, SiteIssueLog

CATEGORY_LABEL = {
    "material_not_arrived": "Material not arrived",
    "material_short": "Material short",
    "material_damaged": "Material damaged",
    "product_discontinued": "Product discontinued",
    "billing_not_accepted": "Bill not accepted",
    "billing_over_billed": "Over-billed",
    "billing_wrong_rate": "Wrong rate",
    "quality": "Quality",
    "leakage": "Leakage",
    "payment": "Payment",
    "site_access": "Site access or handover",
    "subcontractor": "Subcontractor dispute",
    "other": "Other",
}


def _around(db: Session, node_id: int) -> set[int]:
    """The place, every place in it (a flat's toilet) and above it (the toilet's flat, tower)."""
    from app.closeout.completion import _with_children  # noqa: PLC0415
    from app.sites.models import SiteNode  # noqa: PLC0415

    n = db.get(SiteNode, node_id)
    near = set(_with_children(db, n.site_id, [node_id])) if n else {node_id}
    while n is not None and n.parent_id:
        near.add(n.parent_id)
        n = db.get(SiteNode, n.parent_id)
    return near


def guarantee_of(db: Session, site_id: int, node_id: int) -> int | None:
    """The latest signed guarantee covering this place (or the place it is in)."""
    from app.closeout.models import WorkCompletion  # noqa: PLC0415

    near = _around(db, node_id)
    for w in db.scalars(select(WorkCompletion).where(WorkCompletion.site_id == site_id, WorkCompletion.status == "signed").order_by(WorkCompletion.id.desc())):
        if any(a.get("node_id") in near for a in w.areas):
            return w.id
    return None


def raise_issue(db: Session, *, site_id: int | None, category: str, title: str, user_id=None, description: str | None = None, assigned_to=None,
                due_on: date | None = None, methodology_id: int | None = None, node_id: int | None = None, work_completion_id: int | None = None,
                product_id: int | None = None, ra_bill_id: int | None = None, demo: bool = False) -> SiteIssueLog:  # fmt: skip
    if category not in ISSUE_CATEGORIES:
        raise unprocessable(f"Category is one of {', '.join(ISSUE_CATEGORIES)}")
    if category == "leakage" and not work_completion_id and node_id and site_id:
        work_completion_id = guarantee_of(db, site_id, node_id)
        if work_completion_id is None:
            description = ((description or "") + "\nNot under any of our signed guarantees on this site: check whether it is our work.").strip()
    if category == "leakage" and work_completion_id:
        from app.closeout.models import WorkCompletion  # noqa: PLC0415

        w = db.get(WorkCompletion, work_completion_id)
        if w is None or (site_id and w.site_id != site_id):
            raise unprocessable("That guarantee is not of this site")
        if node_id and not any(a.get("node_id") in _around(db, node_id) for a in w.areas):
            raise unprocessable("That area is not in the guarantee: not our work")
    i = SiteIssueLog(code=next_code(db, SiteIssueLog, "ISU"), site_id=site_id, methodology_id=methodology_id, category=category, title=title[:300],
                     description=description, raised_by=user_id, assigned_to=assigned_to, due_on=due_on, node_id=node_id,
                     work_completion_id=work_completion_id, product_id=product_id, ra_bill_id=ra_bill_id, status="open", created_by=user_id, is_demo=demo)  # fmt: skip
    db.add(i)
    db.flush()
    from app.process import engine  # noqa: PLC0415

    engine.emit(db, "issue_raised", subject=f"issue:{i.id}", site_id=site_id, actor_id=user_id,
                data={"issue": i.code, "issue_id": i.id, "title": i.title, "category": CATEGORY_LABEL[category], "person_id": assigned_to})  # fmt: skip
    return i


def set_status(db: Session, i: SiteIssueLog, status: str) -> None:
    if status not in ISSUE_STATUSES:
        raise unprocessable(f"Status is one of {', '.join(ISSUE_STATUSES)}")
    if status == i.status:
        return  # no second "resolved" event
    if i.status == "closed" and status == "resolved":
        raise unprocessable(f"{i.code} is closed")
    i.status = status
    i.resolved_at = now() if status in ("resolved", "closed") else None
    if status in ("resolved", "closed"):
        from app.process import engine  # noqa: PLC0415

        engine.emit(
            db, "issue_resolved", subject=f"issue:{i.id}", site_id=i.site_id, data={"issue": i.code}
        )


def comment(db: Session, i: SiteIssueLog, body: str, user_id) -> IssueComment:
    if not (body or "").strip():
        raise unprocessable("Write the comment")
    c = IssueComment(issue_id=i.id, author_id=user_id, body=body)
    db.add(c)
    db.flush()
    return c


def share(db: Session, i: SiteIssueLog, user_id) -> int:
    """The issue as a portal snag (the client sees and answers it there)."""
    from app.material import service as material  # noqa: PLC0415
    from app.portal import service as portal  # noqa: PLC0415
    from app.portal.models import Snag  # noqa: PLC0415

    if i.site_id is None:
        raise unprocessable("Only a site's issue can be shared with the client")
    if i.snag_id:
        return i.snag_id
    s = Snag(code=material.next_code(db, "SNG"), site_id=i.site_id, node_id=i.node_id, title=i.title, description=i.description, raised_by_side="staff",
             status="open", assigned_to=i.assigned_to, due_date=i.due_on, created_by=user_id)  # fmt: skip
    db.add(s)
    db.flush()
    i.snag_id = s.id
    portal.tell_clients(
        db,
        i.site_id,
        "snags",
        "snag_raised",
        f"{s.code}: {s.title}",
        f"/portal/sites/{i.site_id}?tab=snags",
    )
    return s.id


def timed_events(db: Session, at) -> int:
    """An issue past its due date and not resolved: the person who has it (then the director)."""
    from app.closeout.common import IST  # noqa: PLC0415
    from app.process import engine  # noqa: PLC0415

    day = at.astimezone(IST).date()
    n = 0
    for i in db.scalars(
        select(SiteIssueLog).where(
            SiteIssueLog.status.in_(("open", "in_progress")), SiteIssueLog.due_on < day
        )
    ):
        n += bool(engine.emit(db, "issue_overdue", subject=f"issue_late:{i.id}:{i.due_on}", site_id=i.site_id, at=at,
                              data={"issue": i.code, "issue_id": i.id, "title": i.title, "due": i.due_on.strftime("%d.%m.%Y"), "person_id": i.assigned_to}))  # fmt: skip
    return n


# --- a product discontinued --------------------------------------------------------------------------


def _uses(m, name: str) -> bool:
    n = (name or "").lower()
    return any(
        n and n in (x.get("product") or "").lower() or n in (x.get("text") or "").lower()
        for it in m.items
        for s in it.stages
        for x in s["steps"]
    )


def product_discontinued(db: Session, product, user_id=None) -> list[SiteIssueLog]:
    """An issue on every open methodology and site using the product: a new method statement and
    the client's approval are needed."""
    from app.finance.models import ClientContract, ContractLine  # noqa: PLC0415
    from app.masters.models import SystemComponent  # noqa: PLC0415
    from app.methodology.models import Methodology  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415
    from app.tenders.models import BoqLine  # noqa: PLC0415

    made = []
    title = f"{product.name} discontinued: new method statement and client approval needed"
    done_m, done_s = set(), set()
    for m in db.scalars(select(Methodology)):
        site = db.get(Site, m.site_id) if m.site_id else None
        if site is not None and site.status in ("completed", "closed"):
            continue
        if not _uses(m, product.name):
            continue
        if db.scalar(
            select(SiteIssueLog.id).where(
                SiteIssueLog.methodology_id == m.id,
                SiteIssueLog.product_id == product.id,
                SiteIssueLog.status.in_(("open", "in_progress")),
            )
        ):
            continue
        made.append(raise_issue(db, site_id=m.site_id, methodology_id=m.id, category="product_discontinued", title=title, user_id=user_id, product_id=product.id,
                                description=f"Methodology {m.code} uses {product.name}. Revise it with another product and send it to the client for approval.", demo=m.is_demo))  # fmt: skip
        done_m.add(m.id)
        if m.site_id:
            done_s.add(m.site_id)
    systems = set(
        db.scalars(
            select(SystemComponent.system_id).where(SystemComponent.product_id == product.id)
        )
    )
    if systems:
        rows = db.execute(
            select(ClientContract.site_id).join(ContractLine, ContractLine.contract_id == ClientContract.id).join(BoqLine, BoqLine.id == ContractLine.boq_line_id)
            .where(BoqLine.system_id.in_(systems))
        ).all()  # fmt: skip
        for (site_id,) in rows:
            site = db.get(Site, site_id)
            if site_id in done_s or site is None or site.status in ("completed", "closed"):
                continue
            done_s.add(site_id)
            made.append(raise_issue(db, site_id=site_id, category="product_discontinued", title=title, user_id=user_id, product_id=product.id,
                                    description=f"The site's system uses {product.name}. A new method statement and the client's approval are needed.", demo=site.is_demo))  # fmt: skip
    return made


def methodology_saved(db: Session, m) -> int:
    """A new version of the methodology without the product closes its discontinued-product
    issues."""
    from app.masters.models import Product  # noqa: PLC0415

    n = 0
    for i in db.scalars(
        select(SiteIssueLog).where(
            SiteIssueLog.methodology_id == m.id,
            SiteIssueLog.category == "product_discontinued",
            SiteIssueLog.status.in_(("open", "in_progress")),
        )
    ):
        p = db.get(Product, i.product_id) if i.product_id else None
        if p is not None and not _uses(m, p.name):
            i.status, i.resolved_at = "resolved", now()
            db.add(
                IssueComment(
                    issue_id=i.id,
                    body=f"Closed by methodology {m.code} version {m.version}: {p.name} no longer used.",
                )
            )
            n += 1
    return n
