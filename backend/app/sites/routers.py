"""Sites: register, members, structure (with the tower preset), BOQ-to-areas scope, tasks and
progress, drawings, and the stage templates.

Permissions: site.view / site.edit / site.update with their scope (all | assigned: a member or
the in-charge | own). A site outside the caller's view scope is a 404. Changing the structure,
the scope or certifying a hold point needs site.edit; posting task progress needs site.update;
approving drawings needs drawings.approve.
"""

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.config import settings
from app.db import DbSession
from app.execution.common import save_upload, send_file
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Category, Channel, Client, System
from app.masters.routers.common import Limit, Offset, Search, like, paginate, unprocessable
from app.masters.schemas import Page
from app.material import service as material
from app.models import User
from app.sites import builder, model3d, service, work
from app.sites.models import (
    AreaScope,
    Drawing,
    DrawingRevision,
    Site,
    SiteMember,
    SiteNode,
    StageTemplate,
    StageTemplateStep,
    Task,
    TaskPhoto,
)
from app.sites.schemas import (
    AssignIn,
    DecisionIn,
    DrawingOut,
    FromTenderIn,
    GenerateOut,
    MemberOut,
    MembersIn,
    NodeIn,
    NodeOut,
    NodeUpdate,
    PhotoOut,
    RevisionOut,
    ScopeLineOut,
    ScopeOut,
    ScopeOverview,
    ScopeUpdate,
    SiteIn,
    SiteOut,
    SiteUpdate,
    StepOut,
    TaskOut,
    TaskUpdate,
    TemplateIn,
    TemplateOut,
)
from app.tenders.models import BoqLine, Tender
from app.tenders.service import covers as tender_covers

router = APIRouter(prefix="/api/sites", tags=["sites"])
templates_router = APIRouter(prefix="/api/stage-templates", tags=["sites"])

ViewScope = Annotated[str, Depends(require_permission("site.view"))]
EditScope = Annotated[str, Depends(require_permission("site.edit"))]


def optional_scope(code: str):
    def dep(principal: CurrentPrincipal) -> str | None:
        return principal.permissions.get(code)

    return dep


MaybeEdit = Annotated[str | None, Depends(optional_scope("site.edit"))]
MaybeUpdate = Annotated[str | None, Depends(optional_scope("site.update"))]

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
PHOTO_MAX = 15 * 1024 * 1024
DRAWING_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".dwg"}
DRAWING_MAX = 50 * 1024 * 1024


def _record(db, request, principal, action, site, before=None, after=None):
    audit.record(
        db,
        action,
        "site",
        site.id,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def _editable(db, site_id, view, edit, principal) -> Site:
    site = service.get_visible(db, site_id, view, principal)
    service.check(site, edit, principal, "change the site")
    return site


def _late(target: date | None, done: bool) -> bool:
    return bool(target and target < date.today() and not done)


def _site_out(db: Session, site: Site) -> SiteOut:
    tender_code = (
        db.scalar(select(Tender.code).where(Tender.id == site.tender_id))
        if (site.tender_id)
        else None
    )
    return SiteOut(
        id=site.id,
        code=site.code,
        name=site.name,
        client_id=site.client_id,
        client_name=site.client.name if site.client else None,
        channel_id=site.channel_id,
        channel_name=site.channel.name if site.channel else None,
        tender_id=site.tender_id,
        tender_code=tender_code,
        address=site.address,
        city=site.city,
        state=site.state,
        lat=site.lat,
        lng=site.lng,
        start_date=site.start_date,
        target_date=site.target_date,
        late=_late(site.target_date, site.status in ("completed", "closed")),
        status=site.status,
        site_incharge_id=site.site_incharge_id,
        incharge_name=site.incharge.full_name if site.incharge else None,
        notes=site.notes,
        source=site.source,
        source_ref=site.source_ref,
        progress_percent=site.progress_percent,
        members=[
            MemberOut(user_id=m.user_id, full_name=m.user.full_name, role_on_site=m.role_on_site)
            for m in site.members
        ],
        created_at=site.created_at,
    )


def _check_refs(db: Session, client_id, channel_id, incharge_id) -> None:
    if client_id is not None and db.get(Client, client_id) is None:
        raise unprocessable("Unknown client")
    if channel_id is not None and db.get(Channel, channel_id) is None:
        raise unprocessable("Unknown channel")
    if incharge_id is not None and db.get(User, incharge_id) is None:
        raise unprocessable("Unknown user for the site in-charge")


# --- register ------------------------------------------------------------------------------------


def _list_query(scope, principal, q, status_, client_id, channel_id, incharge_id, late, source):
    query = select(Site).where(service.scope_condition(scope, principal))
    if q:
        p = like(q)
        query = query.outerjoin(Client, Client.id == Site.client_id).where(
            or_(Site.name.ilike(p), Site.code.ilike(p), Site.city.ilike(p), Client.name.ilike(p))
        )
    if status_:
        query = query.where(Site.status == status_)
    if client_id:
        query = query.where(Site.client_id == client_id)
    if channel_id:
        query = query.where(Site.channel_id == channel_id)
    if incharge_id:
        query = query.where(Site.site_incharge_id == incharge_id)
    if source:
        query = query.where(Site.source == source)
    if late:
        query = query.where(
            Site.target_date < date.today(), Site.status.not_in(("completed", "closed"))
        )
    return query.order_by(Site.created_at.desc(), Site.id.desc())


@router.get("")
def list_sites(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    client_id: int | None = None,
    channel_id: int | None = None,
    incharge_id: uuid.UUID | None = None,
    late: bool = False,
    source: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[SiteOut]:
    query = _list_query(
        scope, principal, q, status, client_id, channel_id, incharge_id, late, source
    )
    rows, total = paginate(db, query, limit, offset)
    return Page(items=[_site_out(db, s) for s in rows], total=total, limit=limit, offset=offset)


@router.get("/export")
def export_sites(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    client_id: int | None = None,
    channel_id: int | None = None,
    incharge_id: uuid.UUID | None = None,
    late: bool = False,
    source: str | None = None,
):
    query = _list_query(
        scope, principal, q, status, client_id, channel_id, incharge_id, late, source
    ).limit(EXPORT_ROW_LIMIT)
    sites = [_site_out(db, s) for s in db.scalars(query)]
    return xlsx_response(
        "sites",
        [
            "Code",
            "Name",
            "Client",
            "Channel",
            "Tender",
            "City",
            "Status",
            "Progress %",
            "In-charge",
            "Start",
            "Target",
            "Late",
            "Source",
        ],
        [
            [
                s.code,
                s.name,
                s.client_name,
                s.channel_name,
                s.tender_code,
                s.city,
                s.status,
                s.progress_percent,
                s.incharge_name,
                s.start_date,
                s.target_date,
                s.late,
                s.source,
            ]
            for s in sites
        ],
    )


@router.get("/lookups")
def lookups(db: DbSession, _: ViewScope) -> dict[str, list[dict]]:
    """Choices for the site forms: clients, channels, people, stage templates."""
    return {
        "clients": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(Client.id, Client.name).where(Client.is_active).order_by(Client.name)
            )
        ],
        "channels": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(Channel.id, Channel.name).where(Channel.is_active).order_by(Channel.name)
            )
        ],
        "users": [
            {"id": str(i), "full_name": n}
            for i, n in db.execute(
                select(User.id, User.full_name).where(User.is_active).order_by(User.full_name)
            )
        ],
        "templates": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(StageTemplate.id, StageTemplate.name)
                .where(StageTemplate.is_active)
                .order_by(StageTemplate.id)
            )
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_site(
    body: SiteIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: EditScope
) -> SiteOut:
    _check_refs(db, body.client_id, body.channel_id, body.site_incharge_id)
    site = Site(
        code=service.next_code(db, body.start_date),
        **body.model_dump(),
        created_by=principal.user.id,
    )
    db.add(site)
    db.flush()
    material.site_store(db, site, principal.user.id)
    _record(db, request, principal, "site.create", site, after=audit.model_snapshot(site))
    db.commit()
    db.refresh(site)
    return _site_out(db, site)


@router.post("/from-tender", status_code=status.HTTP_201_CREATED)
def create_from_tender(
    body: FromTenderIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: EditScope,
) -> SiteOut:
    """A won tender becomes a site: its client, channel and BOQ (the priced lines are assigned
    to areas on the Scope tab)."""
    tender = db.get(Tender, body.tender_id)
    tender_scope = principal.permissions.get("tender.view")
    if tender is None or tender_scope is None or not tender_covers(tender_scope, principal, tender):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tender not found")
    if tender.status != "won":
        raise HTTPException(status.HTTP_409_CONFLICT, "Mark the tender won first")
    existing = db.scalar(select(Site).where(Site.tender_id == tender.id))
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{existing.code} was already made from " f"{tender.code}"
        )
    _check_refs(db, None, None, body.site_incharge_id)
    fields = body.model_dump(exclude={"tender_id", "name"})
    site = Site(
        code=service.next_code(db, body.start_date),
        name=body.name or tender.name,
        client_id=tender.client_id,
        channel_id=tender.channel_id,
        tender_id=tender.id,
        city=fields.pop("city") or tender.site_city,
        state=fields.pop("state") or tender.site_state,
        status="active" if body.start_date and body.start_date <= date.today() else "planned",
        created_by=principal.user.id,
        **fields,
    )
    db.add(site)
    db.flush()
    material.site_store(db, site, principal.user.id)
    _record(
        db,
        request,
        principal,
        "site.create",
        site,
        after={**audit.model_snapshot(site), "from_tender": tender.code},
    )
    db.commit()
    db.refresh(site)
    return _site_out(db, site)


@router.get("/{site_id}")
def get_site(site_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope) -> SiteOut:
    return _site_out(db, service.get_visible(db, site_id, scope, principal))


@router.patch("/{site_id}")
def update_site(
    site_id: int,
    body: SiteUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> SiteOut:
    site = _editable(db, site_id, view, edit, principal)
    changes = body.model_dump(exclude_unset=True)
    _check_refs(
        db, changes.get("client_id"), changes.get("channel_id"), changes.get("site_incharge_id")
    )
    before = audit.model_snapshot(site)
    for field, value in changes.items():
        if field in ("name", "status") and value is None:
            continue
        setattr(site, field, value)
    db.flush()
    after = audit.model_snapshot(site)
    if after != before:
        _record(db, request, principal, "site.update", site, before, after)
    db.commit()
    db.refresh(site)
    return _site_out(db, site)


@router.put("/{site_id}/members")
def set_members(
    site_id: int,
    body: MembersIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> SiteOut:
    site = _editable(db, site_id, view, edit, principal)
    ids = [m.user_id for m in body.members]
    if len(set(ids)) != len(ids):
        raise unprocessable("A person is listed twice")
    found = set(db.scalars(select(User.id).where(User.id.in_(ids)))) if ids else set()
    if found != set(ids):
        raise unprocessable("Unknown user id")
    before = sorted((str(m.user_id), m.role_on_site) for m in site.members)
    site.members = []
    db.flush()
    site.members = [
        SiteMember(user_id=m.user_id, role_on_site=m.role_on_site, created_by=principal.user.id)
        for m in body.members
    ]
    db.flush()
    after = sorted((str(m.user_id), m.role_on_site) for m in body.members)
    _record(db, request, principal, "site.members", site, {"members": before}, {"members": after})
    db.commit()
    db.refresh(site)
    return _site_out(db, site)


# --- structure -----------------------------------------------------------------------------------


def _nodes_out(db: Session, site: Site) -> list[NodeOut]:
    all_nodes = service.nodes(db, site.id)
    paths = service.path_names(all_nodes)
    ordered = [n for n in service.descendants(all_nodes, None)]
    who = {n.front_ready_by for n in ordered if n.front_ready_by}
    names = (
        dict(db.execute(select(User.id, User.full_name).where(User.id.in_(who))).all())
        if who
        else {}
    )
    return [
        NodeOut(
            id=n.id,
            parent_id=n.parent_id,
            kind=n.kind,
            name=n.name,
            path=paths[n.id],
            sort_order=n.sort_order,
            level_no=n.level_no,
            area_sqm=n.area_sqm,
            meta=n.meta,
            progress_percent=n.progress_percent,
            front_ready=n.front_ready,
            front_ready_by_name=names.get(n.front_ready_by),
            front_ready_at=n.front_ready_at,
            front_ready_photo=bool(n.front_ready_photo),
        )
        for n in ordered
    ]


@router.post("/{site_id}/nodes/{node_id}/front-ready")
async def set_front_ready(
    site_id: int,
    node_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
    ready: Annotated[bool, Form()] = True,
    photo: Annotated[UploadFile | None, File()] = None,
) -> list[NodeOut]:
    """ "Work front ready": the place is open for our work (the supervisor, from the phone, with
    an optional photo). Indent drafts from a survey order for ready places by default."""
    site = _updater(db, site_id, view, update, edit, principal)
    node = _node(db, site, node_id)
    before = {"front_ready": node.front_ready}
    node.front_ready = ready
    node.front_ready_by = principal.user.id if ready else None
    node.front_ready_at = datetime.now(UTC) if ready else None
    if ready and photo is not None and photo.filename:
        rel, _name = await save_upload(photo, f"sites/{site.id}/fronts")
        node.front_ready_photo = rel
    elif not ready:
        node.front_ready_photo = None
    _record(
        db,
        request,
        principal,
        "site.node.front_ready",
        site,
        before,
        {"node": node.id, "front_ready": ready},
    )
    db.commit()
    return _nodes_out(db, site)


@router.get("/{site_id}/nodes/{node_id}/front-ready/photo")
def front_ready_photo(
    site_id: int, node_id: int, db: DbSession, principal: CurrentPrincipal, view: ViewScope
):
    site = service.get_visible(db, site_id, view, principal)
    node = _node(db, site, node_id)
    if not node.front_ready_photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No photo")
    return send_file(node.front_ready_photo, f"front-{node.id}.jpg")


@router.get("/{site_id}/model")
def site_model(
    site_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
) -> Response:
    """Every node with its work status, for the 3D view. Send If-None-Match with the last
    ETag (the payload's `version`) and an unchanged site answers 304 with no body."""
    site = service.get_visible(db, site_id, scope, principal)
    tag = model3d.version(db, site.id)
    etag = f'"{tag}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    payload = model3d.build(db, site.id)
    payload["version"] = tag
    payload["site_progress"] = float(site.progress_percent or 0)
    return JSONResponse(payload, headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.get("/{site_id}/nodes")
def list_nodes(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> list[NodeOut]:
    return _nodes_out(db, service.get_visible(db, site_id, scope, principal))


def _node(db: Session, site: Site, node_id: int | None) -> SiteNode | None:
    if node_id is None:
        return None
    node = db.get(SiteNode, node_id)
    if node is None or node.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return node


@router.post("/{site_id}/nodes", status_code=status.HTTP_201_CREATED)
def add_node(
    site_id: int,
    body: NodeIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> list[NodeOut]:
    site = _editable(db, site_id, view, edit, principal)
    _node(db, site, body.parent_id)
    if body.sort_order is None:
        current = db.scalar(
            select(func.max(SiteNode.sort_order)).where(
                SiteNode.site_id == site.id,
                SiteNode.parent_id.is_(None)
                if body.parent_id is None
                else SiteNode.parent_id == body.parent_id,
            )
        )
        body.sort_order = (current if current is not None else -1) + 1
    node = SiteNode(site_id=site.id, created_by=principal.user.id, **body.model_dump())
    db.add(node)
    db.flush()
    _record(
        db,
        request,
        principal,
        "site.node.create",
        site,
        after={"node_id": node.id, "kind": node.kind, "name": node.name},
    )
    db.commit()
    return _nodes_out(db, site)


@router.patch("/{site_id}/nodes/{node_id}")
def update_node(
    site_id: int,
    node_id: int,
    body: NodeUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> list[NodeOut]:
    site = _editable(db, site_id, view, edit, principal)
    node = _node(db, site, node_id)
    changes = body.model_dump(exclude_unset=True)
    if "parent_id" in changes and changes["parent_id"] is not None:
        _node(db, site, changes["parent_id"])
        under = {n.id for n in service.descendants(service.nodes(db, site.id), node.id)}
        if changes["parent_id"] == node.id or changes["parent_id"] in under:
            raise unprocessable("A node cannot move under itself")
    before = audit.model_snapshot(node)
    for field, value in changes.items():
        if field in ("kind", "name", "sort_order") and value is None:
            continue
        setattr(node, field, value)
    db.flush()
    _record(db, request, principal, "site.node.update", site, before, audit.model_snapshot(node))
    if "parent_id" in changes:
        work.refresh_site(db, site)
    db.commit()
    return _nodes_out(db, site)


def _started(db: Session, node_ids: list[int]) -> int:
    if not node_ids:
        return 0
    return (
        db.scalar(
            select(func.count()).where(Task.node_id.in_(node_ids), Task.status != "not_started")
        )
        or 0
    )


@router.delete("/{site_id}/nodes/{node_id}")
def delete_node(
    site_id: int,
    node_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> list[NodeOut]:
    """Deletes the node and everything under it (with their scopes and tasks), unless work has
    started there."""
    site = _editable(db, site_id, view, edit, principal)
    node = _node(db, site, node_id)
    under = [node.id] + [n.id for n in service.descendants(service.nodes(db, site.id), node.id)]
    started = _started(db, under)
    if started:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{started} tasks under {node.name} have started; they stay"
        )
    _record(
        db,
        request,
        principal,
        "site.node.delete",
        site,
        before={"node_id": node.id, "name": node.name, "nodes": len(under)},
    )
    db.delete(node)
    db.flush()
    work.refresh_site(db, site)
    db.commit()
    return _nodes_out(db, site)


@router.post("/{site_id}/builder/tower/preview")
def tower_preview(
    site_id: int,
    body: builder.TowerPreset,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
) -> dict[str, int]:
    """How many nodes of each kind the preset would make (nothing is saved)."""
    service.get_visible(db, site_id, scope, principal)
    return builder.preview(body)


@router.post("/{site_id}/builder/tower", status_code=status.HTTP_201_CREATED)
def add_tower(
    site_id: int,
    body: builder.TowerPreset,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> list[NodeOut]:
    site = _editable(db, site_id, view, edit, principal)
    _node(db, site, body.parent_id)
    siblings = db.scalar(
        select(func.count()).where(
            SiteNode.site_id == site.id,
            SiteNode.parent_id.is_(None)
            if body.parent_id is None
            else SiteNode.parent_id == body.parent_id,
        )
    )
    made = builder.create(db, site.id, body, principal.user.id, siblings or 0)
    _record(
        db,
        request,
        principal,
        "site.builder.tower",
        site,
        after={"preset": body.model_dump(mode="json"), "nodes": made},
    )
    db.commit()
    return _nodes_out(db, site)


@router.get("/{site_id}/nodes/select")
def select_nodes(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    kind: str,
    under: int | None = None,
) -> list[int]:
    """Shortcut for "all toilets in T1": the ids of the nodes of a kind under a node."""
    site = service.get_visible(db, site_id, scope, principal)
    _node(db, site, under)
    all_nodes = service.nodes(db, site.id)
    return [n.id for n in service.descendants(all_nodes, under) if n.kind == kind]


# --- scope ---------------------------------------------------------------------------------------


def _templates(db: Session) -> list[StageTemplate]:
    return list(db.scalars(select(StageTemplate).order_by(StageTemplate.id)))


def _scopes_out(db: Session, site: Site) -> list[ScopeOut]:
    paths = service.path_names(service.nodes(db, site.id))
    names = {t.id: t.name for t in _templates(db)}
    counts = {
        sid: (n, started)
        for sid, n, started in db.execute(
            select(
                Task.area_scope_id, func.count(), func.count().filter(Task.status != "not_started")
            )
            .where(Task.site_id == site.id)
            .group_by(Task.area_scope_id)
        )
    }
    scopes = db.scalars(
        select(AreaScope).where(AreaScope.site_id == site.id).order_by(AreaScope.id)
    )
    return [
        ScopeOut(
            id=s.id,
            node_id=s.node_id,
            node_path=paths.get(s.node_id, "?"),
            boq_line_id=s.boq_line_id,
            stage_template_id=s.stage_template_id,
            stage_template_name=names.get(s.stage_template_id, "?"),
            qty=s.qty,
            unit=s.unit,
            progress_percent=s.progress_percent,
            tasks=counts.get(s.id, (0, 0))[0],
            started=counts.get(s.id, (0, 0))[1],
        )
        for s in scopes
    ]


def _lines(db: Session, site: Site) -> list[BoqLine]:
    if not site.tender_id:
        return []
    return list(
        db.scalars(
            select(BoqLine)
            .where(BoqLine.tender_id == site.tender_id, BoqLine.status == "priced")
            .order_by(BoqLine.sort_order, BoqLine.id)
        )
    )


@router.get("/{site_id}/scope")
def get_scope(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> ScopeOverview:
    """The tender's priced BOQ lines with their areas, suggested template and the qty check."""
    site = service.get_visible(db, site_id, scope, principal)
    lines = _lines(db, site)
    checks = work.qty_check(db, site, lines)
    templates = _templates(db)
    scopes = _scopes_out(db, site)
    by_line: dict[int, list[ScopeOut]] = {}
    for s in scopes:
        if s.boq_line_id is not None:
            by_line.setdefault(s.boq_line_id, []).append(s)
    line_ids = {ln.id for ln in lines}
    out = []
    for ln in lines:
        t = work.suggest_template(ln, templates)
        c = checks[ln.id]
        out.append(
            ScopeLineOut(
                boq_line_id=ln.id,
                item_no=ln.client_item_no,
                description=ln.description,
                unit=ln.unit,
                boq_qty=ln.qty,
                qty_note=ln.qty_note,
                suggested_template_id=t.id if t else None,
                assigned=c["assigned"],
                difference=c["difference"],
                state=c["state"],
                scopes=by_line.get(ln.id, []),
            )
        )
    others = [s for s in scopes if s.boq_line_id is None or s.boq_line_id not in line_ids]
    return ScopeOverview(lines=out, other_scopes=others)


def _drop_scopes(db: Session, scopes: list[AreaScope]) -> None:
    ids = [s.id for s in scopes]
    started = (
        db.scalar(
            select(func.count()).where(Task.area_scope_id.in_(ids), Task.status != "not_started")
        )
        if ids
        else 0
    )
    if started:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{started} tasks of this assignment have started; it cannot be "
            "replaced. Change the quantities instead.",
        )
    for s in scopes:
        db.delete(s)
    db.flush()


@router.post("/{site_id}/scope/assign")
def assign(
    site_id: int,
    body: AssignIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> ScopeOverview:
    """Put a BOQ line's work on the picked nodes. Its qty is split over them (by area_sqm when
    every node has one, otherwise equally)."""
    site = _editable(db, site_id, view, edit, principal)
    template = db.get(StageTemplate, body.stage_template_id)
    if template is None:
        raise unprocessable("Unknown stage template")
    picked = [_node(db, site, i) for i in dict.fromkeys(body.node_ids)]
    line = None
    if body.boq_line_id is not None:
        line = db.get(BoqLine, body.boq_line_id)
        if line is None or line.tender_id != site.tender_id:
            raise unprocessable("That BOQ line is not from this site's tender")
        total = body.qty if body.qty is not None else line.qty
        unit = line.unit
    else:
        total, unit = body.qty, body.unit
    if total is None:
        raise unprocessable("This line has no quantity (QRO); give the quantity to split")
    previous = list(
        db.scalars(
            select(AreaScope).where(
                AreaScope.site_id == site.id, AreaScope.boq_line_id == body.boq_line_id
            )
        )
    )
    if line is not None and previous and body.replace:
        _drop_scopes(db, previous)
        total_left = total
    elif line is not None and previous:
        # add to what is there: only the part not yet assigned
        total_left = total - sum((s.qty for s in previous), Decimal(0))
        if body.qty is not None:
            total_left = body.qty
        if total_left <= 0:
            raise unprocessable("The whole quantity is already assigned; replace it instead")
    else:
        total_left = total
    for node, qty in zip(picked, work.split_qty(Decimal(total_left), picked), strict=True):
        db.add(
            AreaScope(
                site_id=site.id,
                node_id=node.id,
                boq_line_id=body.boq_line_id,
                stage_template_id=template.id,
                qty=qty,
                unit=unit,
                created_by=principal.user.id,
            )
        )
    db.flush()
    work.refresh_site(db, site)
    _record(
        db,
        request,
        principal,
        "site.scope.assign",
        site,
        after={
            "boq_line_id": body.boq_line_id,
            "template": template.name,
            "nodes": [n.id for n in picked],
            "qty": total_left,
            "replace": body.replace,
        },
    )
    db.commit()
    return get_scope(site.id, db, principal, view)


def _scope(db: Session, site: Site, scope_id: int) -> AreaScope:
    s = db.get(AreaScope, scope_id)
    if s is None or s.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scope not found")
    return s


@router.patch("/{site_id}/scopes/{scope_id}")
def update_scope(
    site_id: int,
    scope_id: int,
    body: ScopeUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> ScopeOverview:
    site = _editable(db, site_id, view, edit, principal)
    s = _scope(db, site, scope_id)
    before = {"qty": s.qty, "stage_template_id": s.stage_template_id}
    if body.stage_template_id is not None and body.stage_template_id != s.stage_template_id:
        if db.scalar(select(func.count()).where(Task.area_scope_id == s.id)):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Tasks exist for this scope; its template cannot change"
            )
        if db.get(StageTemplate, body.stage_template_id) is None:
            raise unprocessable("Unknown stage template")
        s.stage_template_id = body.stage_template_id
    if body.qty is not None:
        s.qty = body.qty
    db.flush()
    work.refresh_site(db, site)
    _record(
        db,
        request,
        principal,
        "site.scope.update",
        site,
        before,
        {"qty": s.qty, "stage_template_id": s.stage_template_id},
    )
    db.commit()
    return get_scope(site.id, db, principal, view)


@router.delete("/{site_id}/scopes/{scope_id}")
def delete_scope(
    site_id: int,
    scope_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> ScopeOverview:
    site = _editable(db, site_id, view, edit, principal)
    s = _scope(db, site, scope_id)
    _record(
        db,
        request,
        principal,
        "site.scope.delete",
        site,
        before={"scope_id": s.id, "node_id": s.node_id, "qty": s.qty},
    )
    _drop_scopes(db, [s])
    work.refresh_site(db, site)
    db.commit()
    return get_scope(site.id, db, principal, view)


# --- tasks ---------------------------------------------------------------------------------------


def _task_out(t: Task, paths: dict[int, str]) -> TaskOut:
    step = t.step
    return TaskOut(
        id=t.id,
        node_id=t.node_id,
        node_path=paths.get(t.node_id) if t.node_id else None,
        area_scope_id=t.area_scope_id,
        step_id=t.step_id,
        name=t.name,
        sort_order=t.sort_order,
        planned_start=t.planned_start,
        planned_end=t.planned_end,
        actual_start=t.actual_start,
        actual_end=t.actual_end,
        status=t.status,
        late=_late(t.planned_end, t.status in ("done", "certified")),
        assignee_id=t.assignee_id,
        assignee_name=t.assignee.full_name if t.assignee else None,
        progress_percent=t.progress_percent,
        parent_task_id=t.parent_task_id,
        depends_on=list(t.depends_on or []),
        weight_percent=step.weight_percent if step else None,
        needs_photo=bool(step and step.needs_photo),
        needs_inspection=bool(step and step.needs_inspection),
        hold_point=bool(step and step.hold_point),
        checklist_template_id=step.checklist_template_id if step else None,
        remark=t.remark,
        inspection=t.inspection,
        certified_at=t.certified_at,
        photos=[
            PhotoOut(
                id=p.id,
                filename=p.filename,
                uploaded_at=p.created_at,
                share_with_client=p.share_with_client,
            )
            for p in t.photos
        ],
    )


@router.post("/{site_id}/tasks/generate")
def generate(
    site_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> GenerateOut:
    """One task per (scope × step); only missing ones are added."""
    site = _editable(db, site_id, view, edit, principal)
    result = work.generate_tasks(db, site, principal.user.id)
    total = db.scalar(select(func.count()).where(Task.site_id == site.id)) or 0
    end = db.scalar(select(func.max(Task.planned_end)).where(Task.site_id == site.id))
    _record(db, request, principal, "site.tasks.generate", site, after={**result, "tasks": total})
    db.commit()
    return GenerateOut(**result, tasks=total, planned_end=end)


@router.get("/{site_id}/tasks")
def list_tasks(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    filter: Annotated[str | None, Query(pattern="^(late|blocked|pending_certification)$")] = None,
    node_id: int | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[TaskOut]:
    site = service.get_visible(db, site_id, scope, principal)
    all_nodes = service.nodes(db, site.id)
    paths = service.path_names(all_nodes)
    query = select(Task).where(Task.site_id == site.id)
    if node_id is not None:
        under = [node_id] + [n.id for n in service.descendants(all_nodes, node_id)]
        query = query.where(Task.node_id.in_(under))
    if status_:
        query = query.where(Task.status == status_)
    if filter == "late":
        query = query.where(
            Task.planned_end < date.today(), Task.status.not_in(("done", "certified"))
        )
    elif filter == "blocked":
        query = query.where(Task.status == "blocked")
    elif filter == "pending_certification":
        query = query.join(StageTemplateStep, StageTemplateStep.id == Task.step_id).where(
            StageTemplateStep.hold_point, Task.status == "done"
        )
    order = {n.id: i for i, n in enumerate(service.descendants(all_nodes, None))}
    tasks = sorted(
        db.scalars(query),
        key=lambda t: (order.get(t.node_id, 10**9), t.area_scope_id or 0, t.sort_order, t.id),
    )
    return [_task_out(t, paths) for t in tasks]


def _task(db: Session, site: Site, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if t is None or t.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return t


def _check_stage_checklists(db: Session, task: Task) -> None:
    """The stage is done when its last step is: the engineer completes the quality checklist of
    every checklist step in it first (a certified step already passed its inspection)."""
    if not task.area_scope_id:
        return
    from app.execution.inspections import passed_inspection  # noqa: PLC0415
    from app.execution.models import ChecklistTemplate  # noqa: PLC0415

    steps = db.scalars(
        select(Task).where(Task.area_scope_id == task.area_scope_id, Task.parent_task_id.is_(None))
    ).all()
    if any(t.id != task.id and t.status not in ("done", "certified") for t in steps):
        return  # not the last step: the stage is not done yet
    for t in steps:
        if t.status == "certified" or not (t.step and t.step.checklist_template_id):
            continue
        if not passed_inspection(db, t):
            tpl = db.get(ChecklistTemplate, t.step.checklist_template_id)
            raise unprocessable(
                f"Complete the quality checklist '{tpl.name if tpl else 'checklist'}' for "
                f"'{t.name}' before the stage is marked done"
            )


def _check_predecessors(db: Session, task: Task) -> None:
    for dep_id in task.depends_on or []:
        dep = db.get(Task, dep_id)
        if dep is None:
            continue
        if dep.step and dep.step.hold_point and dep.status != "certified":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{dep.name}' is a hold point: the office must certify it "
                "before the next step starts",
            )
        if dep.status not in ("done", "certified"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"'{dep.name}' is not done yet")


def _updater(db, site_id, view, update, edit, principal) -> Site:
    site = service.get_visible(db, site_id, view, principal)
    if not (
        (update and service.covers(update, principal, site))
        or (edit and service.covers(edit, principal, site))
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot post progress on this site")
    return site


@router.patch("/{site_id}/tasks/{task_id}")
def update_task(
    site_id: int,
    task_id: int,
    body: TaskUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
) -> TaskOut:
    """Post progress: status, % done, inspection checklist, remark. Done needs a photo when the
    step asks for one, and every inspection item passed when it has a checklist. A certified
    task can only be changed by the office (site.edit)."""
    site = _updater(db, site_id, view, update, edit, principal)
    task = _task(db, site, task_id)
    if task.status == "certified" and not (edit and service.covers(edit, principal, site)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This step is certified")
    before = {
        "status": task.status,
        "progress_percent": task.progress_percent,
        "remark": task.remark,
    }
    changes = body.model_dump(exclude_unset=True)
    if "inspection" in changes:
        task.inspection = [i.model_dump() for i in body.inspection or []]
    for field in ("remark", "assignee_id", "planned_start", "planned_end"):
        if field in changes:
            setattr(task, field, changes[field])
    if body.progress_percent is not None:
        task.progress_percent = body.progress_percent
    new = body.status
    if new and new != task.status:
        if new in ("in_progress", "done"):
            _check_predecessors(db, task)
        step = task.step
        if new == "done":
            if step and step.needs_photo and not task.photos:
                raise unprocessable("Add a photo before marking this step done")
            if step and step.needs_inspection:
                items = task.inspection or []
                if not items or not all(i.get("passed") for i in items):
                    raise unprocessable("Every inspection item must pass before this step is done")
            _check_stage_checklists(db, task)
            task.progress_percent = Decimal(100)
            task.actual_end = date.today()
        if new in ("in_progress", "done") and task.actual_start is None:
            task.actual_start = date.today()
        if new in ("not_started", "in_progress", "blocked"):
            task.actual_end = None
            task.certified_at = task.certified_by = None
        task.status = new
    db.flush()
    if task.area_scope_id:
        work.refresh_scope(db, db.get(AreaScope, task.area_scope_id))
    _record(
        db,
        request,
        principal,
        "site.task.update",
        site,
        {"task_id": task.id, **before},
        {
            "task_id": task.id,
            "status": task.status,
            "progress_percent": task.progress_percent,
            "remark": task.remark,
        },
    )
    db.commit()
    db.refresh(task)
    return _task_out(task, service.path_names(service.nodes(db, site.id)))


@router.post("/{site_id}/tasks/{task_id}/certify")
def certify_task(
    site_id: int,
    task_id: int,
    body: DecisionIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: MaybeEdit,
) -> TaskOut:
    """The office certifies a finished hold-point step (ponding test ...): only then does it
    count in progress and may the next step start."""
    site = _editable(db, site_id, view, edit, principal)
    task = _task(db, site, task_id)
    if not (task.step and task.step.hold_point):
        raise unprocessable("Only hold-point steps are certified")
    if task.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "The step must be done first")
    from app.execution.inspections import passed_inspection

    if not passed_inspection(db, task):
        raise unprocessable(
            "This hold point needs a passed inspection with its checklist first (Inspections tab)"
        )
    task.status = "certified"
    task.certified_by = principal.user.id
    task.certified_at = datetime.now(UTC)
    if body.remark:
        task.remark = f"{task.remark}\n{body.remark}" if task.remark else body.remark
    db.flush()
    if task.area_scope_id:
        work.refresh_scope(db, db.get(AreaScope, task.area_scope_id))
    _record(
        db,
        request,
        principal,
        "site.task.certify",
        site,
        after={"task_id": task.id, "name": task.name, "remark": body.remark},
    )
    db.commit()
    db.refresh(task)
    return _task_out(task, service.path_names(service.nodes(db, site.id)))


def _media(*parts: str) -> Path:
    return Path(settings.media_dir).joinpath(*parts)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ ()-]+", "_", Path(name).name)[:150] or "file"


@router.post("/{site_id}/tasks/{task_id}/photos", status_code=status.HTTP_201_CREATED)
async def add_photo(
    site_id: int,
    task_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
    file: Annotated[UploadFile, File(description="A photo (jpg, png, webp, heic), up to 15 MB")],
) -> TaskOut:
    site = _updater(db, site_id, view, update, edit, principal)
    task = _task(db, site, task_id)
    name = _safe(file.filename or "photo.jpg")
    if Path(name).suffix.lower() not in PHOTO_TYPES:
        raise unprocessable("Upload a photo (.jpg, .png, .webp or .heic)")
    data = await file.read(PHOTO_MAX + 1)
    if len(data) > PHOTO_MAX:
        raise unprocessable("The photo is larger than 15 MB")
    rel = Path("sites") / str(site.id) / "tasks" / str(task.id) / f"{uuid.uuid4().hex}__{name}"
    _media(str(rel)).parent.mkdir(parents=True, exist_ok=True)
    _media(str(rel)).write_bytes(data)
    db.add(
        TaskPhoto(
            task_id=task.id, stored_path=str(rel), filename=name, created_by=principal.user.id
        )
    )
    _record(
        db, request, principal, "site.task.photo", site, after={"task_id": task.id, "file": name}
    )
    db.commit()
    db.refresh(task)
    return _task_out(task, service.path_names(service.nodes(db, site.id)))


@router.get("/{site_id}/tasks/{task_id}/photos/{photo_id}")
def get_photo(
    site_id: int,
    task_id: int,
    photo_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
) -> FileResponse:
    site = service.get_visible(db, site_id, scope, principal)
    task = _task(db, site, task_id)
    photo = next((p for p in task.photos if p.id == photo_id), None)
    if photo is None or not _media(photo.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return FileResponse(_media(photo.stored_path), filename=photo.filename)


# --- drawings ------------------------------------------------------------------------------------


def _rev_out(r: DrawingRevision) -> RevisionOut:
    return RevisionOut(
        id=r.id,
        rev=r.rev,
        filename=r.filename,
        size_bytes=r.size_bytes,
        status=r.status,
        uploaded_by_name=r.uploader.full_name if r.uploader else None,
        uploaded_at=r.created_at,
        approved_by_name=r.approver.full_name if r.approver else None,
        approved_at=r.approved_at,
        remark=r.remark,
    )


def _drawing_out(d: Drawing, paths: dict[int, str]) -> DrawingOut:
    revs = sorted(d.revisions, key=lambda r: r.rev_no)
    approved = [r for r in revs if r.status == "approved"]
    return DrawingOut(
        id=d.id,
        title=d.title,
        discipline=d.discipline,
        node_id=d.node_id,
        node_path=paths.get(d.node_id) if d.node_id else None,
        latest_approved=_rev_out(approved[-1]) if approved else None,
        latest=_rev_out(revs[-1]) if revs else None,
        revisions=[_rev_out(r) for r in reversed(revs)],
        share_with_client=d.share_with_client,
    )


def _drawings(db: Session, site: Site) -> list[DrawingOut]:
    paths = service.path_names(service.nodes(db, site.id))
    out = [
        _drawing_out(d, paths)
        for d in db.scalars(select(Drawing).where(Drawing.site_id == site.id).order_by(Drawing.id))
    ]
    # drawings with an approved revision first, most recently approved first
    return sorted(
        out,
        key=lambda d: (
            d.latest_approved is None,
            -(
                d.latest_approved.approved_at.timestamp()
                if d.latest_approved and d.latest_approved.approved_at
                else 0
            ),
            d.title.lower(),
        ),
    )


@router.get("/{site_id}/drawings")
def list_drawings(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> list[DrawingOut]:
    return _drawings(db, service.get_visible(db, site_id, scope, principal))


async def _store_revision(
    site: Site, drawing: Drawing, rev_no: int, file: UploadFile, user_id
) -> DrawingRevision:
    name = _safe(file.filename or "drawing.pdf")
    if Path(name).suffix.lower() not in DRAWING_TYPES:
        raise unprocessable("Upload a drawing as PDF, PNG, JPG or DWG")
    data = await file.read(DRAWING_MAX + 1)
    if len(data) > DRAWING_MAX:
        raise unprocessable("The drawing is larger than 50 MB")
    rel = Path("sites") / str(site.id) / "drawings" / str(drawing.id) / f"R{rev_no}__{name}"
    _media(str(rel)).parent.mkdir(parents=True, exist_ok=True)
    _media(str(rel)).write_bytes(data)
    return DrawingRevision(
        drawing_id=drawing.id,
        rev_no=rev_no,
        stored_path=str(rel),
        filename=name,
        size_bytes=len(data),
        uploaded_by=user_id,
        created_by=user_id,
    )


@router.post("/{site_id}/drawings", status_code=status.HTTP_201_CREATED)
async def add_drawing(
    site_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
    title: Annotated[str, Form(min_length=1, max_length=300)],
    file: Annotated[UploadFile, File(description="PDF, PNG, JPG or DWG, up to 50 MB")],
    discipline: Annotated[str, Form(pattern="^(architectural|structural|waterproofing|other)$")] = (
        "waterproofing"
    ),
    node_id: Annotated[int | None, Form()] = None,
) -> list[DrawingOut]:
    """A new drawing with its first revision, R0 (draft)."""
    site = _updater(db, site_id, view, update, edit, principal)
    _node(db, site, node_id)
    drawing = Drawing(
        site_id=site.id,
        node_id=node_id,
        title=title.strip(),
        discipline=discipline,
        created_by=principal.user.id,
    )
    db.add(drawing)
    db.flush()
    db.add(await _store_revision(site, drawing, 0, file, principal.user.id))
    _record(
        db,
        request,
        principal,
        "site.drawing.create",
        site,
        after={"drawing_id": drawing.id, "title": drawing.title, "rev": "R0"},
    )
    db.commit()
    return _drawings(db, site)


def _drawing(db: Session, site: Site, drawing_id: int) -> Drawing:
    d = db.get(Drawing, drawing_id)
    if d is None or d.site_id != site.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drawing not found")
    return d


@router.post("/{site_id}/drawings/{drawing_id}/revisions", status_code=status.HTTP_201_CREATED)
async def add_revision(
    site_id: int,
    drawing_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
    file: Annotated[UploadFile, File(description="PDF, PNG, JPG or DWG, up to 50 MB")],
) -> list[DrawingOut]:
    """The next revision (R1, R2 ...) as a draft; earlier ones stay as they were."""
    site = _updater(db, site_id, view, update, edit, principal)
    drawing = _drawing(db, site, drawing_id)
    rev_no = max((r.rev_no for r in drawing.revisions), default=-1) + 1
    db.add(await _store_revision(site, drawing, rev_no, file, principal.user.id))
    _record(
        db,
        request,
        principal,
        "site.drawing.revision",
        site,
        after={"drawing_id": drawing.id, "rev": f"R{rev_no}"},
    )
    db.commit()
    db.expire_all()
    return _drawings(db, site)


def _revision(drawing: Drawing, revision_id: int) -> DrawingRevision:
    r = next((r for r in drawing.revisions if r.id == revision_id), None)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    return r


@router.post("/{site_id}/drawings/{drawing_id}/revisions/{revision_id}/submit")
def submit_revision(
    site_id: int,
    drawing_id: int,
    revision_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    update: MaybeUpdate,
    edit: MaybeEdit,
) -> list[DrawingOut]:
    site = _updater(db, site_id, view, update, edit, principal)
    rev = _revision(_drawing(db, site, drawing_id), revision_id)
    if rev.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{rev.rev} is already {rev.status}")
    rev.status = "submitted"
    _record(
        db,
        request,
        principal,
        "site.drawing.submit",
        site,
        after={"drawing_id": drawing_id, "rev": rev.rev},
    )
    db.commit()
    return _drawings(db, site)


def _decide(
    db,
    request,
    principal,
    site_id,
    drawing_id,
    revision_id,
    view,
    approve: bool,
    remark: str | None,
) -> list[DrawingOut]:
    site = service.get_visible(db, site_id, view, principal)
    drawing = _drawing(db, site, drawing_id)
    rev = _revision(drawing, revision_id)
    if rev.status not in ("draft", "submitted"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{rev.rev} is already {rev.status}")
    if not approve and not (remark or "").strip():
        raise unprocessable("Give a remark when rejecting a drawing")
    rev.status = "approved" if approve else "rejected"
    rev.approved_by = principal.user.id
    rev.approved_at = datetime.now(UTC)
    rev.remark = (remark or "").strip() or None
    if approve:
        latest = max(
            [r for r in drawing.revisions if r.status == "approved"], key=lambda r: r.rev_no
        )
        drawing.current_revision_id = latest.id
    _record(
        db,
        request,
        principal,
        f"site.drawing.{rev.status}",
        site,
        after={"drawing_id": drawing.id, "rev": rev.rev, "remark": rev.remark},
    )
    db.commit()
    return _drawings(db, site)


Approver = Depends(require_permission("drawings.approve"))


@router.post(
    "/{site_id}/drawings/{drawing_id}/revisions/{revision_id}/approve", dependencies=[Approver]
)
def approve_revision(
    site_id: int,
    drawing_id: int,
    revision_id: int,
    body: DecisionIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
) -> list[DrawingOut]:
    return _decide(
        db, request, principal, site_id, drawing_id, revision_id, view, True, body.remark
    )


@router.post(
    "/{site_id}/drawings/{drawing_id}/revisions/{revision_id}/reject", dependencies=[Approver]
)
def reject_revision(
    site_id: int,
    drawing_id: int,
    revision_id: int,
    body: DecisionIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
) -> list[DrawingOut]:
    return _decide(
        db, request, principal, site_id, drawing_id, revision_id, view, False, body.remark
    )


@router.get("/{site_id}/drawings/{drawing_id}/revisions/{revision_id}/file")
def drawing_file(
    site_id: int,
    drawing_id: int,
    revision_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
) -> FileResponse:
    site = service.get_visible(db, site_id, scope, principal)
    rev = _revision(_drawing(db, site, drawing_id), revision_id)
    if not _media(rev.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(_media(rev.stored_path), filename=f"{rev.rev}_{rev.filename}")


# --- stage templates -----------------------------------------------------------------------------


def _template_out(db: Session, t: StageTemplate) -> TemplateOut:
    system = db.get(System, t.system_id) if t.system_id else None
    category = db.get(Category, t.work_category_id) if t.work_category_id else None
    return TemplateOut(
        id=t.id,
        name=t.name,
        system_id=t.system_id,
        system_name=system.name if system else None,
        work_category_id=t.work_category_id,
        work_category_name=category.name if category else None,
        keywords=t.keywords,
        is_active=t.is_active,
        steps=[
            StepOut(
                id=s.id,
                sort_order=s.sort_order,
                name=s.name,
                weight_percent=s.weight_percent,
                needs_photo=s.needs_photo,
                needs_inspection=s.needs_inspection,
                hold_point=s.hold_point,
                typical_days=s.typical_days,
                checklist_template_id=s.checklist_template_id,
            )
            for s in t.steps
        ],
        total_days=sum(s.typical_days for s in t.steps),
    )


@templates_router.get("")
def list_templates(db: DbSession, _: ViewScope) -> list[TemplateOut]:
    return [_template_out(db, t) for t in _templates(db)]


def _save_template(db: Session, t: StageTemplate, body: TemplateIn, user_id) -> None:
    clash = db.scalar(
        select(StageTemplate.id).where(
            func.lower(StageTemplate.name) == body.name.strip().lower(), StageTemplate.id != t.id
        )
    )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A template named {body.name!r} exists")
    if body.system_id and db.get(System, body.system_id) is None:
        raise unprocessable("Unknown system")
    if body.work_category_id and db.get(Category, body.work_category_id) is None:
        raise unprocessable("Unknown work category")
    t.name, t.system_id, t.work_category_id = (
        body.name.strip(),
        body.system_id,
        body.work_category_id,
    )
    t.keywords, t.is_active = body.keywords, body.is_active
    keep = {s.id: s for s in t.steps}
    wanted = {s.id for s in body.steps if s.id}
    for step_id, step in keep.items():
        if step_id not in wanted:
            if db.scalar(select(func.count()).where(Task.step_id == step_id)):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"'{step.name}' has tasks on sites; keep it (set its weight "
                    "to 0) instead of removing it",
                )
            t.steps.remove(step)
    db.flush()
    for order, s in enumerate(body.steps, start=1):
        step = keep.get(s.id) if s.id else None
        if s.id and step is None:
            raise unprocessable(f"Step {s.id} is not part of this template")
        if step is None:
            step = StageTemplateStep(created_by=user_id)
            t.steps.append(step)
        step.sort_order = order
        for field in (
            "name",
            "weight_percent",
            "needs_photo",
            "needs_inspection",
            "hold_point",
            "typical_days",
            "checklist_template_id",
        ):
            setattr(step, field, getattr(s, field))
    db.flush()


@templates_router.post("", status_code=status.HTTP_201_CREATED)
def create_template(
    body: TemplateIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: EditScope
) -> TemplateOut:
    t = StageTemplate(name=body.name.strip(), created_by=principal.user.id)
    db.add(t)
    db.flush()
    _save_template(db, t, body, principal.user.id)
    audit.record(
        db,
        "stage_template.create",
        "stage_template",
        t.id,
        user_id=principal.user.id,
        after=body.model_dump(mode="json"),
        ip=audit.client_ip(request),
    )
    db.commit()
    db.refresh(t)
    return _template_out(db, t)


@templates_router.put("/{template_id}")
def update_template(
    template_id: int,
    body: TemplateIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: EditScope,
) -> TemplateOut:
    """Replace the template's steps (weights must add up to 100). Steps with tasks on sites
    are kept (their weights change everywhere); new steps only reach a site on its next
    Generate tasks."""
    t = db.get(StageTemplate, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    before = _template_out(db, t).model_dump(mode="json")
    _save_template(db, t, body, principal.user.id)
    db.refresh(t)
    after = _template_out(db, t).model_dump(mode="json")
    audit.record(
        db,
        "stage_template.update",
        "stage_template",
        t.id,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )
    db.commit()
    return _template_out(db, t)
