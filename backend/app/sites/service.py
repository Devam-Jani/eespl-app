"""Site access (scopes), numbering and the structure tree."""

from collections import defaultdict
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, false, or_, select, text, true
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.sites.models import Site, SiteMember, SiteNode


def scope_condition(scope: str, principal: Principal) -> ColumnElement[bool]:
    """all: every site; assigned: the caller is a site member or the site in-charge;
    own: the caller created it."""
    uid = principal.user.id
    if scope == "all":
        return true()
    if scope == "assigned":
        members = select(SiteMember.site_id).where(SiteMember.user_id == uid)
        return or_(Site.site_incharge_id == uid, Site.id.in_(members))
    if scope == "own":
        return Site.created_by == uid
    return false()


def covers(scope: str, principal: Principal, site: Site) -> bool:
    uid = principal.user.id
    if scope == "all":
        return True
    if scope == "assigned":
        return site.site_incharge_id == uid or any(m.user_id == uid for m in site.members)
    if scope == "own":
        return site.created_by == uid
    return False


def get_visible(db: Session, site_id: int, view_scope: str, principal: Principal) -> Site:
    """The site, or 404 when it does not exist *or* the caller may not see it."""
    site = db.get(Site, site_id)
    if site is None or not covers(view_scope, principal, site):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


def check(site: Site, scope: str | None, principal: Principal, what: str) -> None:
    if scope is None or not covers(scope, principal, site):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You cannot {what} on this site")


def next_code(db: Session, on: date | None = None) -> str:
    """S-2026-0001 ... per year, from one atomic statement."""
    year = (on or date.today()).year
    value = db.execute(
        text(
            "INSERT INTO site_sequences (year, last_value) VALUES (:y, 1) "
            "ON CONFLICT (year) DO UPDATE SET last_value = site_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"y": year},
    ).scalar_one()
    return f"S-{year}-{value:04d}"


# --- tree ----------------------------------------------------------------------------------------


def nodes(db: Session, site_id: int) -> list[SiteNode]:
    return list(
        db.scalars(
            select(SiteNode)
            .where(SiteNode.site_id == site_id)
            .order_by(SiteNode.parent_id.nulls_first(), SiteNode.sort_order, SiteNode.id)
        )
    )


def children_map(all_nodes: list[SiteNode]) -> dict[int | None, list[SiteNode]]:
    out: dict[int | None, list[SiteNode]] = defaultdict(list)
    for n in all_nodes:
        out[n.parent_id].append(n)
    return out


def descendants(all_nodes: list[SiteNode], root_id: int | None) -> list[SiteNode]:
    """Every node under root_id (not root itself); the whole tree when root_id is None."""
    kids = children_map(all_nodes)
    out: list[SiteNode] = []
    stack = list(reversed(kids.get(root_id, [])))
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(reversed(kids.get(n.id, [])))
    return out


def path_names(all_nodes: list[SiteNode]) -> dict[int, str]:
    """{node id: "T1 › Floor 3 › 301 › Toilet 1"}."""
    by_id = {n.id: n for n in all_nodes}
    cache: dict[int, str] = {}

    def path(n: SiteNode) -> str:
        if n.id not in cache:
            parent = by_id.get(n.parent_id) if n.parent_id else None
            cache[n.id] = f"{path(parent)} › {n.name}" if parent else n.name
        return cache[n.id]

    return {n.id: path(n) for n in all_nodes}


def ancestors(all_nodes: list[SiteNode], node_id: int) -> list[int]:
    """node_id and every node above it, nearest first."""
    by_id = {n.id: n for n in all_nodes}
    out = []
    current = by_id.get(node_id)
    while current is not None:
        out.append(current.id)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return out
