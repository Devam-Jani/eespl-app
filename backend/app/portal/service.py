"""Portal scoping and notifications.

A client sees a site only when all three hold, checked in SQL on every portal request:
  - the site's client is one of the user's clients (client_users),
  - the site is switched on for the portal (site_portal.visible),
  - the user was given the site (client_user_sites).
Anything else is a 404, whatever the id. A section switched off for the site is a 404 too.

Staff with portal.manage can "preview as client": GET requests with the X-Preview-As header run
the same portal code as that client user (read-only; never for a site outside the staff
member's own portal.manage scope).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentPrincipal, Principal
from app.db import DbSession
from app.material import service as material
from app.models import User
from app.portal.models import (
    SECTIONS,
    ClientUser,
    ClientUserSite,
    Notification,
    NotificationOutbox,
    SitePortal,
)
from app.sites.models import Site, SiteMember


@dataclass
class PortalCtx:
    user: User  # the client user whose view this is
    staff: Principal | None  # set when a staff member previews
    principal: Principal

    @property
    def preview(self) -> bool:
        return self.staff is not None


def not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def forbidden(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, msg)


def is_client_user(db: Session, user_id) -> bool:
    return db.scalar(select(exists().where(ClientUser.user_id == user_id))) or False


def portal_ctx(request: Request, db: DbSession, principal: CurrentPrincipal) -> PortalCtx:
    """The client whose portal this request is for. 403 without portal.view (staff without a
    client login), except a staff preview."""
    preview_as = request.headers.get("X-Preview-As")
    if preview_as:
        if principal.permissions.get("portal.manage") is None:
            raise forbidden("Previewing the portal needs portal.manage")
        if request.method != "GET":
            raise forbidden("The preview is read-only")
        try:
            uid = uuid.UUID(preview_as)
        except ValueError as exc:
            raise not_found("Client user not found") from exc
        user = db.get(User, uid)
        if user is None or not is_client_user(db, uid):
            raise not_found("Client user not found")
        return PortalCtx(user=user, staff=principal, principal=principal)
    if principal.permissions.get("portal.view") is None:
        raise forbidden("Missing permission: portal.view")
    if not is_client_user(db, principal.user.id):
        raise forbidden("Not a client login")
    return PortalCtx(user=principal.user, staff=None, principal=principal)


def visible_sites(user_id):
    """The site ids a client user may see (the three conditions)."""
    theirs = select(ClientUser.client_id).where(ClientUser.user_id == user_id)
    given = select(ClientUserSite.site_id).where(ClientUserSite.user_id == user_id)
    shown = select(SitePortal.site_id).where(SitePortal.visible)
    return select(Site.id).where(Site.client_id.in_(theirs), Site.id.in_(given), Site.id.in_(shown))


def sections(db: Session, site_id: int) -> dict[str, bool]:
    sp = db.get(SitePortal, site_id)
    chosen = (sp.sections if sp else None) or {}
    return {s: bool(chosen.get(s, True)) for s in SECTIONS}


def portal_site(db: Session, ctx: PortalCtx, site_id: int, section: str | None = None) -> Site:
    """The site, or 404 when this client may not see it (or the section is off)."""
    ok = db.scalar(visible_sites(ctx.user.id).where(Site.id == site_id)) is not None
    site = db.get(Site, site_id) if ok else None
    if site is None:
        raise not_found("Site not found")
    if ctx.preview and not material.covers_site(
        db, ctx.staff.permissions.get("portal.manage"), ctx.staff, site.id
    ):
        raise not_found("Site not found")
    if section and not sections(db, site.id).get(section, True):
        raise not_found("Not shown for this site")
    return site


def need(ctx: PortalCtx, code: str) -> None:
    if ctx.preview:
        raise forbidden("The preview is read-only")
    if ctx.principal.permissions.get(code) is None:
        raise forbidden(f"Missing permission: {code}")


# --- invites -------------------------------------------------------------------------------------


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


# --- notifications -------------------------------------------------------------------------------


def notify(
    db: Session,
    user_ids,
    kind: str,
    title: str,
    link: str | None = None,
    site_id: int | None = None,
    skip=None,
) -> int:
    """One in-app notification per user (and its in_app outbox row, delivered at once)."""
    n = 0
    for uid in dict.fromkeys(u for u in user_ids if u and u != skip):
        note = Notification(user_id=uid, site_id=site_id, kind=kind, title=title[:300], link=link)
        db.add(note)
        db.flush()
        db.add(
            NotificationOutbox(
                notification_id=note.id, channel="in_app", status="sent", sent_at=now()
            )
        )
        n += 1
    return n


def client_users_of(db: Session, site_id: int, section: str | None = None) -> list:
    """Active client users who can see the site (and the section)."""
    if section and not sections(db, site_id).get(section, True):
        return []
    site = db.get(Site, site_id)
    if site is None:
        return []
    rows = db.scalars(
        select(User.id)
        .join(ClientUserSite, ClientUserSite.user_id == User.id)
        .join(ClientUser, ClientUser.user_id == User.id)
        .where(
            ClientUserSite.site_id == site_id,
            ClientUser.client_id == site.client_id,
            User.is_active,
        )
    ).all()
    sp = db.get(SitePortal, site_id)
    return list(dict.fromkeys(rows)) if sp and sp.visible else []


def staff_of(db: Session, site_id: int) -> list:
    """The site's in-charge and members (not client users)."""
    site = db.get(Site, site_id)
    if site is None:
        return []
    ids = [
        site.site_incharge_id,
        *db.scalars(select(SiteMember.user_id).where(SiteMember.site_id == site_id)),
    ]
    clients = set(db.scalars(select(ClientUser.user_id)))
    return [u for u in dict.fromkeys(ids) if u and u not in clients]


def active_staff(db: Session, site_id: int) -> list[User]:
    """Active staff on the site (in-charge and members): who a snag can be assigned to."""
    ids = staff_of(db, site_id)
    if not ids:
        return []
    return list(
        db.scalars(select(User).where(User.id.in_(ids), User.is_active).order_by(User.full_name))
    )


def tell_clients(
    db: Session, site_id: int, section: str, kind: str, title: str, link: str | None = None
) -> int:
    return notify(db, client_users_of(db, site_id, section), kind, title, link, site_id)


def tell_staff(
    db: Session, site_id: int, kind: str, title: str, link: str | None = None, skip=None
) -> int:
    return notify(db, staff_of(db, site_id), kind, title, link, site_id, skip=skip)
