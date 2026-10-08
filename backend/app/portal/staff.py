"""Staff side of the portal: per-site portal settings and client users (/api/portal-admin), the
snag list across sites (/api/snags), comment threads with internal notes (/api/comments) and
the in-app notifications of everyone, staff or client (/api/notifications).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, update

from app.auth.deps import CurrentPrincipal, Principal
from app.auth.router import revoke_all_refresh_tokens
from app.db import DbSession
from app.execution.common import names, record, save_upload, send_file
from app.execution.models import Inspection
from app.execution.service import site_for
from app.masters.models import Client, CompanyProfile
from app.material import service as material
from app.models import Role, User
from app.portal import service as svc
from app.portal.models import (
    SECTIONS,
    ClientUser,
    ClientUserSite,
    Comment,
    Notification,
    PortalInvite,
    SiteDocument,
    SitePortal,
    Snag,
    SnagPhoto,
)
from app.portal.routers import comment_out, entity_site, snag_out
from app.sites.models import Drawing, Site, SiteNode, Task, TaskPhoto

router = APIRouter(prefix="/api/portal-admin", tags=["portal-admin"])
snags_router = APIRouter(prefix="/api/snags", tags=["snags"])
comments_router = APIRouter(prefix="/api/comments", tags=["comments"])
notes_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _staff(db, principal: Principal) -> None:
    """Client logins never reach staff endpoints."""
    if svc.is_client_user(db, principal.user.id):
        raise svc.forbidden("Staff only")


def _manage(db, principal: Principal, site_id: int) -> Site:
    _staff(db, principal)
    scope = principal.permissions.get("portal.manage")
    if scope is None:
        raise svc.forbidden("Missing permission: portal.manage")
    site = db.get(Site, site_id)
    if site is None or not material.covers_site(db, scope, principal, site.id):
        raise svc.not_found("Site not found")
    return site


# --- per-site settings ---------------------------------------------------------------------------


def _users_out(db, site: Site) -> list[dict]:
    """Client users of this site's client, and whether they have this site."""
    if site.client_id is None:
        return []
    rows = db.scalars(
        select(User)
        .join(ClientUser, ClientUser.user_id == User.id)
        .where(ClientUser.client_id == site.client_id)
        .order_by(User.full_name)
    ).all()
    given = set(db.scalars(select(ClientUserSite.user_id).where(ClientUserSite.site_id == site.id)))
    out = []
    for u in rows:
        inv = db.scalar(
            select(PortalInvite)
            .where(PortalInvite.user_id == u.id)
            .order_by(PortalInvite.id.desc())
            .limit(1)
        )
        out.append(
            {
                "id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "is_active": u.is_active,
                "has_password": u.has_password,
                "last_login_at": u.last_login_at,
                "has_site": u.id in given,
                "invite": {
                    "expires_at": inv.expires_at,
                    "used": inv.used_at is not None,
                    "expired": inv.expires_at < svc.now(),
                }
                if inv
                else None,
            }
        )
    return out


def _settings_out(db, site: Site) -> dict:
    sp = db.get(SitePortal, site.id)
    client = db.get(Client, site.client_id) if site.client_id else None
    return {
        "site_id": site.id,
        "code": site.code,
        "client_id": site.client_id,
        "client_name": client.name if client else None,
        "visible": bool(sp and sp.visible),
        "sections": svc.sections(db, site.id),
        "users": _users_out(db, site),
    }


class SettingsIn(BaseModel):
    visible: bool
    sections: dict[str, bool] = {}


@router.get("/sites/{site_id}")
def get_settings(site_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    return _settings_out(db, _manage(db, principal, site_id))


@router.put("/sites/{site_id}")
def put_settings(
    site_id: int, body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    site = _manage(db, principal, site_id)
    bad = set(body.sections) - set(SECTIONS)
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown sections: {', '.join(sorted(bad))}"
        )
    sp = db.get(SitePortal, site.id) or SitePortal(site_id=site.id, created_by=principal.user.id)
    sp.visible, sp.sections = body.visible, {s: bool(body.sections.get(s, True)) for s in SECTIONS}
    db.add(sp)
    record(db, request, principal, "portal.settings", "site", site.id, after=body.model_dump())
    db.commit()
    return _settings_out(db, site)


# --- client users and invites --------------------------------------------------------------------


class InviteIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    client_id: int
    site_ids: list[int] = Field(min_length=1)


def _invite_link(db, user: User, by) -> dict:
    db.execute(
        update(PortalInvite)
        .where(
            PortalInvite.user_id == user.id,
            PortalInvite.used_at.is_(None),
            PortalInvite.revoked_at.is_(None),
        )
        .values(revoked_at=svc.now())
    )
    raw, hashed = svc.new_token()
    days = (
        db.get(CompanyProfile, 1).portal_invite_days if db.get(CompanyProfile, 1) else None
    ) or 7
    inv = PortalInvite(
        user_id=user.id,
        token_hash=hashed,
        expires_at=svc.now() + timedelta(days=days),
        created_by=by,
    )
    db.add(inv)
    db.flush()
    # shown once to the staff member, who sends it; only the hash is stored
    return {"user_id": str(user.id), "link": f"/portal/invite/{raw}", "expires_at": inv.expires_at}


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def invite(body: InviteIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Create (or re-invite) a client contact. No email or SMS is sent: the one-time link is
    returned for staff to send themselves."""
    sites = [_manage(db, principal, sid) for sid in dict.fromkeys(body.site_ids)]
    if any(s.client_id != body.client_id for s in sites):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Every site must belong to that client"
        )
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and not svc.is_client_user(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "That email belongs to a staff login")
    if user is None:
        role = db.scalar(select(Role).where(Role.code == "client"))
        user = User(
            email=email,
            full_name=body.full_name.strip(),
            phone=body.phone,
            roles=[role],
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.full_name, user.phone = body.full_name.strip(), body.phone or user.phone
    if db.get(ClientUser, (user.id, body.client_id)) is None:
        db.add(ClientUser(user_id=user.id, client_id=body.client_id))
    for s in sites:
        if db.get(ClientUserSite, (user.id, s.id)) is None:
            db.add(ClientUserSite(user_id=user.id, site_id=s.id))
    out = _invite_link(db, user, principal.user.id)
    record(
        db,
        request,
        principal,
        "portal.invite",
        "user",
        user.id,
        after={"email": email, "client_id": body.client_id, "sites": [s.code for s in sites]},
    )
    db.commit()
    return out


def _client_user(db, principal, uid: uuid.UUID) -> User:
    """A client user of a client whose site the caller manages."""
    _staff(db, principal)
    scope = principal.permissions.get("portal.manage")
    if scope is None:
        raise svc.forbidden("Missing permission: portal.manage")
    user = db.get(User, uid)
    if user is None or not svc.is_client_user(db, uid):
        raise svc.not_found("Client user not found")
    clients = select(ClientUser.client_id).where(ClientUser.user_id == uid)
    sites = db.scalars(select(Site.id).where(Site.client_id.in_(clients))).all()
    if not any(material.covers_site(db, scope, principal, s) for s in sites):
        raise svc.not_found("Client user not found")
    return user


@router.post("/users/{uid}/reinvite", status_code=status.HTTP_201_CREATED)
def reinvite(uid: uuid.UUID, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    user = _client_user(db, principal, uid)
    out = _invite_link(db, user, principal.user.id)
    record(db, request, principal, "portal.reinvite", "user", user.id)
    db.commit()
    return out


class ActiveIn(BaseModel):
    is_active: bool


@router.put("/users/{uid}/active")
def set_active(
    uid: uuid.UUID, body: ActiveIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Disabling ends the client's sessions at once (every request re-checks is_active, and
    their refresh tokens and open invites are revoked)."""
    user = _client_user(db, principal, uid)
    user.is_active = body.is_active
    if not body.is_active:
        revoke_all_refresh_tokens(db, user)
        db.execute(
            update(PortalInvite)
            .where(
                PortalInvite.user_id == user.id,
                PortalInvite.used_at.is_(None),
                PortalInvite.revoked_at.is_(None),
            )
            .values(revoked_at=svc.now())
        )
    record(
        db,
        request,
        principal,
        "portal.user.enable" if body.is_active else "portal.user.disable",
        "user",
        user.id,
    )
    db.commit()
    return {"id": str(user.id), "is_active": user.is_active}


class UserSitesIn(BaseModel):
    site_id: int
    has_site: bool


@router.put("/users/{uid}/sites")
def set_user_site(
    uid: uuid.UUID, body: UserSitesIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    user = _client_user(db, principal, uid)
    site = _manage(db, principal, body.site_id)
    if db.get(ClientUser, (user.id, site.client_id)) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That site belongs to another client"
        )
    if body.has_site and db.get(ClientUserSite, (user.id, site.id)) is None:
        db.add(ClientUserSite(user_id=user.id, site_id=site.id))
    if not body.has_site:
        db.execute(
            delete(ClientUserSite).where(
                ClientUserSite.user_id == user.id, ClientUserSite.site_id == site.id
            )
        )
    record(db, request, principal, "portal.user.sites", "user", user.id, after=body.model_dump())
    db.commit()
    return _settings_out(db, site)


# --- share with client ---------------------------------------------------------------------------


class ShareIn(BaseModel):
    share: bool


def _can_share(db, principal, site_id) -> Site:
    """Supervisors (site.update on the site) or office (portal.manage) tick share-with-client."""
    _staff(db, principal)
    site = db.get(Site, site_id)
    ok = site is not None and (
        material.covers_site(
            db, principal.permissions.get("site.update"), principal, site.id, site.created_by
        )
        or material.covers_site(db, principal.permissions.get("portal.manage"), principal, site.id)
    )
    if not ok:
        raise svc.not_found("Not found")
    return site


@router.put("/task-photos/{pid}/share")
def share_photo(
    pid: int, body: ShareIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    p = db.get(TaskPhoto, pid)
    task = db.get(Task, p.task_id) if p else None
    if p is None:
        raise svc.not_found("Photo not found")
    _can_share(db, principal, task.site_id)
    p.share_with_client = body.share
    record(
        db, request, principal, "portal.share.photo", "task_photo", p.id, after=body.model_dump()
    )
    db.commit()
    return {"id": p.id, "share_with_client": p.share_with_client}


@router.put("/drawings/{did}/share")
def share_drawing(
    did: int, body: ShareIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    d = db.get(Drawing, did)
    if d is None:
        raise svc.not_found("Drawing not found")
    _can_share(db, principal, d.site_id)
    d.share_with_client = body.share
    record(db, request, principal, "portal.share.drawing", "drawing", d.id, after=body.model_dump())
    db.commit()
    return {"id": d.id, "share_with_client": d.share_with_client}


# --- site documents (staff side) -----------------------------------------------------------------


def _doc_out(db, d: SiteDocument) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "kind": d.kind,
        "source": d.source,
        "filename": d.filename,
        "share_with_client": d.share_with_client,
        "remark": d.remark,
        "created_at": d.created_at,
        "by": names(db, [d.created_by]).get(d.created_by),
    }


@router.get("/sites/{site_id}/documents")
def list_documents(site_id: int, db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    _staff(db, principal)
    site = site_for(db, site_id, principal, "site.view")
    return [
        _doc_out(db, d)
        for d in db.scalars(
            select(SiteDocument)
            .where(SiteDocument.site_id == site.id)
            .order_by(SiteDocument.id.desc())
        )
    ]


@router.post("/sites/{site_id}/documents", status_code=status.HTTP_201_CREATED)
async def add_document(
    site_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    kind: Annotated[str, Form(pattern="^(drawing|document)$")] = "document",
    share_with_client: Annotated[bool, Form()] = False,
) -> dict:
    site = _can_share(db, principal, site_id)
    rel, name = await save_upload(file, f"portal/documents/{site.id}")
    d = SiteDocument(
        site_id=site.id,
        title=title,
        kind=kind,
        source="staff",
        stored_path=rel,
        filename=name,
        share_with_client=share_with_client,
        created_by=principal.user.id,
    )
    db.add(d)
    db.flush()
    record(
        db,
        request,
        principal,
        "portal.document.upload",
        "site_document",
        d.id,
        after={"file": name},
    )
    if share_with_client:
        svc.tell_clients(
            db,
            site.id,
            "documents",
            "document_shared",
            f"New document: {title}",
            f"/portal/sites/{site.id}?tab=documents",
        )
    db.commit()
    return _doc_out(db, d)


@router.put("/documents/{doc_id}/share")
def share_document(
    doc_id: int, body: ShareIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    d = db.get(SiteDocument, doc_id)
    if d is None or d.source != "staff":
        raise svc.not_found("Document not found")
    site = _can_share(db, principal, d.site_id)
    d.share_with_client = body.share
    record(
        db,
        request,
        principal,
        "portal.share.document",
        "site_document",
        d.id,
        after=body.model_dump(),
    )
    if body.share:
        svc.tell_clients(
            db,
            site.id,
            "documents",
            "document_shared",
            f"New document: {d.title}",
            f"/portal/sites/{site.id}?tab=documents",
        )
    db.commit()
    return _doc_out(db, d)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: DbSession, principal: CurrentPrincipal):
    _staff(db, principal)
    d = db.get(SiteDocument, doc_id)
    if d is None:
        raise svc.not_found("Document not found")
    site_for(db, d.site_id, principal, "site.view")
    return send_file(d.stored_path, d.filename)


# --- inspection client sign-off ------------------------------------------------------------------


@router.post("/inspections/{iid}/request-signoff")
def request_signoff(iid: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Put an inspection in the client's queue for an on-screen signature."""
    _staff(db, principal)
    i = db.get(Inspection, iid)
    if i is None:
        raise svc.not_found("Inspection not found")
    site_for(db, i.site_id, principal, "inspection.view", "inspection.edit")
    if i.client_signoff == "signed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{i.code} is already signed by the client")
    i.client_signoff = "waiting"
    record(db, request, principal, "portal.inspection.request_signoff", "inspection", i.id)
    svc.tell_clients(
        db,
        i.site_id,
        "inspections",
        "inspection_signoff",
        f"{i.code} is waiting for your sign-off",
        f"/portal/sites/{i.site_id}?tab=inspections",
    )
    db.commit()
    return {"id": i.id, "client_signoff": i.client_signoff}


# --- snags (all sites) ---------------------------------------------------------------------------


def _snag_view(db, principal, s: Snag | None) -> Snag:
    _staff(db, principal)
    if s is None:
        raise svc.not_found("Snag not found")
    site_for(db, s.site_id, principal, "site.view")
    return s


def _snag_edit(db, principal, s: Snag | None) -> Snag:
    s = _snag_view(db, principal, s)
    site_for(db, s.site_id, principal, "site.view", "site.update")
    return s


@snags_router.get("")
def list_snags(
    db: DbSession,
    principal: CurrentPrincipal,
    site_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    side: Literal["client", "staff"] | None = None,
    assigned_to: uuid.UUID | None = None,
    open_only: bool = False,
) -> list[dict]:
    _staff(db, principal)
    scope = principal.permissions.get("site.view")
    if scope is None:
        raise svc.forbidden("Missing permission: site.view")
    q = (
        select(Snag)
        .join(Site, Site.id == Snag.site_id)
        .where(material.by_site(scope, principal, Snag.site_id, Site.created_by))
    )
    if site_id is not None:
        q = q.where(Snag.site_id == site_id)
    if status_:
        q = q.where(Snag.status == status_)
    if open_only:
        q = q.where(Snag.status.in_(("open", "in_progress", "fixed")))
    if side:
        q = q.where(Snag.raised_by_side == side)
    if assigned_to:
        q = q.where(Snag.assigned_to == assigned_to)
    codes = dict(db.execute(select(Site.id, Site.code)).all())
    return [
        {**snag_out(db, s, client=False), "site_code": codes.get(s.site_id)}
        for s in db.scalars(q.order_by(Snag.id.desc()).limit(1000))
    ]


@snags_router.get("/{sid}")
def get_snag(sid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    return snag_out(db, _snag_view(db, principal, db.get(Snag, sid)), client=False)


@snags_router.post("", status_code=status.HTTP_201_CREATED)
async def create_snag(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    site_id: Annotated[int, Form()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    description: Annotated[str | None, Form()] = None,
    node_id: Annotated[int | None, Form()] = None,
    area: Annotated[str | None, Form(max_length=200)] = None,
    assigned_to: Annotated[uuid.UUID | None, Form()] = None,
    due_date: Annotated[date | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    _staff(db, principal)
    site = site_for(db, site_id, principal, "site.view", "site.update")
    if node_id is not None:
        n = db.get(SiteNode, node_id)
        if n is None or n.site_id != site.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That place is not on this site"
            )
    s = Snag(
        code=material.next_code(db, "SNG"),
        site_id=site.id,
        node_id=node_id,
        area=area,
        title=title,
        description=description,
        raised_by_side="staff",
        assigned_to=assigned_to,
        due_date=due_date,
        created_by=principal.user.id,
    )
    db.add(s)
    db.flush()
    for f in photos or []:
        if f.filename:
            rel, name = await save_upload(f, f"snags/{s.id}")
            s.photos.append(
                SnagPhoto(
                    kind="before", stored_path=rel, filename=name, created_by=principal.user.id
                )
            )
    record(db, request, principal, "snag.create", "snag", s.id, after={"title": title})
    svc.tell_clients(
        db,
        site.id,
        "snags",
        "snag_raised",
        f"{s.code}: {title[:80]}",
        f"/portal/sites/{site.id}?tab=snags",
    )
    db.commit()
    db.refresh(s)
    return snag_out(db, s, client=False)


class SnagPatch(BaseModel):
    status: Literal["open", "in_progress", "fixed", "verified", "closed"] | None = None
    assigned_to: uuid.UUID | None = None
    due_date: date | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None


# staff moves; a client-raised snag is verified (or reopened) by the client
STAFF_MOVES = {
    "open": {"in_progress", "fixed"},
    "in_progress": {"open", "fixed"},
    "fixed": {"in_progress"},
    "verified": {"closed"},
    "closed": set(),
}


@snags_router.patch("/{sid}")
def patch_snag(
    sid: int, body: SnagPatch, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    s = _snag_edit(db, principal, db.get(Snag, sid))
    changes = body.model_dump(exclude_unset=True)
    new = changes.pop("status", None)
    if new and new != s.status:
        allowed = set(STAFF_MOVES[s.status])
        if s.raised_by_side == "staff" and s.status == "fixed":
            allowed |= {"verified"}
        if new not in allowed:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{s.code} cannot go from {s.status} to {new}"
            )
        if new == "fixed" and not any(p.kind == "after" for p in s.photos):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Attach an 'after' photo before marking it fixed",
            )
        s.status = new
        if new == "fixed":
            s.fixed_at = svc.now()
        if new == "verified":
            s.verified_at = svc.now()
    for k, v in changes.items():
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "snag.update",
        "snag",
        s.id,
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    if new == "fixed":
        title = f"{s.code} is fixed: please check and verify"
    else:
        title = f"{s.code} updated: {s.status.replace('_', ' ')}"
    svc.tell_clients(
        db, s.site_id, "snags", "snag_updated", title, f"/portal/sites/{s.site_id}?tab=snags"
    )
    if body.assigned_to and body.assigned_to != principal.user.id:
        svc.notify(
            db,
            [body.assigned_to],
            "snag_assigned",
            f"{s.code} assigned to you: {s.title[:80]}",
            f"/snags?open={s.id}",
            s.site_id,
        )
    db.commit()
    return snag_out(db, s, client=False)


@snags_router.post("/{sid}/photos", status_code=status.HTTP_201_CREATED)
async def snag_after_photo(
    sid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form(pattern="^(before|after)$")] = "after",
) -> dict:
    s = _snag_edit(db, principal, db.get(Snag, sid))
    rel, name = await save_upload(file, f"snags/{s.id}")
    s.photos.append(
        SnagPhoto(kind=kind, stored_path=rel, filename=name, created_by=principal.user.id)
    )
    record(db, request, principal, "snag.photo", "snag", s.id, after={"kind": kind, "file": name})
    db.commit()
    db.refresh(s)
    return snag_out(db, s, client=False)


@snags_router.get("/{sid}/photos/{pid}")
def snag_photo(sid: int, pid: int, db: DbSession, principal: CurrentPrincipal):
    s = _snag_view(db, principal, db.get(Snag, sid))
    p = next((x for x in s.photos if x.id == pid), None)
    return send_file(p.stored_path if p else None, p.filename if p else None)


# --- comments ------------------------------------------------------------------------------------


class StaffCommentIn(BaseModel):
    entity_type: Literal["dpr", "inspection", "snag", "ra_bill"]
    entity_id: int
    body: str = Field(min_length=1, max_length=4000)
    internal: bool = False  # staff-only note, never shown in the portal


VIEW_OF = {
    "dpr": "dpr.view",
    "inspection": "inspection.view",
    "snag": "site.view",
    "ra_bill": "billing.view",
}


def _staff_thread(db, principal, entity_type, entity_id) -> int:
    _staff(db, principal)
    found = entity_site(db, entity_type, entity_id, client=False)
    if found is None:
        raise svc.not_found("Not found")
    return site_for(db, found[0], principal, VIEW_OF[entity_type]).id


@comments_router.get("")
def staff_comments(
    entity_type: str, entity_id: int, db: DbSession, principal: CurrentPrincipal
) -> list[dict]:
    if entity_type not in VIEW_OF:
        raise svc.not_found("Not found")
    _staff_thread(db, principal, entity_type, entity_id)
    rows = list(
        db.scalars(
            select(Comment)
            .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
            .order_by(Comment.id)
        )
    )
    who = names(db, [c.author_id for c in rows])
    return [comment_out(db, c, who) for c in rows]


@comments_router.post("", status_code=status.HTTP_201_CREATED)
def staff_comment(
    body: StaffCommentIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    site_id = _staff_thread(db, principal, body.entity_type, body.entity_id)
    c = Comment(
        site_id=site_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        body=body.body,
        internal=body.internal,
        author_id=principal.user.id,
        author_side="staff",
    )
    db.add(c)
    db.flush()
    record(
        db,
        request,
        principal,
        "comment.internal" if body.internal else "comment",
        body.entity_type,
        body.entity_id,
    )
    if not body.internal and entity_site(db, body.entity_type, body.entity_id, client=True):
        section = entity_site(db, body.entity_type, body.entity_id, client=True)[1]
        svc.tell_clients(
            db,
            site_id,
            section,
            "comment",
            f"EESPL commented: {body.body[:80]}",
            f"/portal/sites/{site_id}?tab={section}",
        )
    svc.tell_staff(
        db,
        site_id,
        "comment",
        f"{principal.user.full_name}: {body.body[:80]}",
        f"/sites/{site_id}",
        skip=principal.user.id,
    )
    db.commit()
    return comment_out(db, c, names(db, [c.author_id]))


# --- notifications (both sides) ------------------------------------------------------------------


@notes_router.get("")
def my_notifications(db: DbSession, principal: CurrentPrincipal, unread: bool = False) -> dict:
    q = select(Notification).where(Notification.user_id == principal.user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    rows = db.scalars(q.order_by(Notification.id.desc()).limit(100)).all()
    count = db.scalar(
        select(func.count()).where(
            Notification.user_id == principal.user.id, Notification.read_at.is_(None)
        )
    )
    return {
        "unread": count,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "link": n.link,
                "site_id": n.site_id,
                "read": n.read_at is not None,
                "created_at": n.created_at,
            }
            for n in rows
        ],
    }


@notes_router.post("/{nid}/read")
def read_one(nid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    n = db.get(Notification, nid)
    if n is None or n.user_id != principal.user.id:
        raise svc.not_found("Notification not found")
    n.read_at = n.read_at or svc.now()
    db.commit()
    return {"id": n.id, "read": True}


@notes_router.post("/read-all")
def read_all(db: DbSession, principal: CurrentPrincipal) -> dict:
    db.execute(
        update(Notification)
        .where(Notification.user_id == principal.user.id, Notification.read_at.is_(None))
        .values(read_at=svc.now())
    )
    db.commit()
    return {"ok": True}
