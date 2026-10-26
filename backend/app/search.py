# ruff: noqa: E501
"""Search anywhere (Ctrl+K): sites, RA bills, quotations and people by role, each only as far as
the caller may see it, through the same scope as its own list (a site engineer finds their sites
only; a client login is never here). The actions ("New daily report", "Raise indent") are the
browser's own, filtered by the same permissions."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentPrincipal
from app.auth.rbac import widest
from app.db import DbSession

router = APIRouter(prefix="/api/search", tags=["search"])
LIMIT = 6


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("")
def search(db: DbSession, principal: CurrentPrincipal, q: Annotated[str, Query(min_length=2, max_length=80)]) -> dict:
    perms = principal.permissions
    p = _like(q.strip())
    out: dict[str, list[dict]] = {"sites": [], "bills": [], "quotations": [], "people": []}

    if perms.get("site.view"):
        from app.sites import routers as sites  # noqa: PLC0415

        query = sites._list_query(perms["site.view"], principal, q.strip(), None, None, None, None, False, None)
        for s in db.scalars(query.limit(LIMIT)):
            out["sites"].append({"id": s.id, "title": f"{s.code} {s.name}", "note": s.city or "", "to": f"/sites/{s.id}"})

    bills_scope = widest(perms.get("closeout.billing"), perms.get("closeout.payments"))
    if bills_scope:
        from app.closeout.routes import allowed_sites  # noqa: PLC0415
        from app.finance.models import RaBill  # noqa: PLC0415
        from app.sites.models import Site  # noqa: PLC0415

        query = (
            select(RaBill, Site)
            .join(Site, Site.id == RaBill.site_id)
            .where(RaBill.status != "cancelled", or_(RaBill.code.ilike(p), RaBill.old_no.ilike(p), Site.name.ilike(p), Site.code.ilike(p)))
            .order_by(RaBill.id.desc())
        )
        allowed = allowed_sites(db, bills_scope, principal)
        if allowed is not None:
            query = query.where(RaBill.site_id.in_(allowed or [0]))
        for b, s in db.execute(query.limit(LIMIT)):
            was = f" · was {b.old_no} in the old files" if b.old_no else ""
            out["bills"].append({"id": b.id, "title": f"{b.code}", "note": f"{s.code} {s.name} · {b.status}{was}", "to": f"/bills/{b.id}"})

    if perms.get("quotation.view"):
        from app.quotations import service as qsvc  # noqa: PLC0415
        from app.quotations.models import Quotation  # noqa: PLC0415

        query = qsvc.visible_q(perms["quotation.view"], principal).where(Quotation.is_latest, or_(Quotation.code.ilike(p), Quotation.client_firm.ilike(p)))
        for qu in db.scalars(query.order_by(Quotation.id.desc()).limit(LIMIT)):
            out["quotations"].append({"id": qu.id, "title": qu.code, "note": qu.client_firm, "to": f"/quotations/{qu.id}"})

    if perms.get("admin.users"):
        from app.models import Role, User, UserRole  # noqa: PLC0415

        query = (
            select(Role.code, Role.name, func.count(User.id))
            .join(UserRole, UserRole.role_id == Role.id, isouter=True)
            .join(User, (User.id == UserRole.user_id) & User.is_active, isouter=True)
            .where(or_(Role.name.ilike(p), Role.code.ilike(p)))
            .group_by(Role.code, Role.name)
            .limit(LIMIT)
        )
        for code, name, n in db.execute(query):
            out["people"].append({"id": code, "title": name, "note": f"{n} {'person' if n == 1 else 'people'}", "to": f"/admin/users?role={code}"})
    return out
