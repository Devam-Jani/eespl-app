"""Channels: who brought a tender (salesperson, applicator partner, manufacturer route). The
rate library's folders are channels; the same-channel rate policy matches on them."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Channel, LibraryLine
from app.masters.routers.common import Limit, Offset, Search, get_or_404, like, paginate
from app.masters.schemas import ChannelIn, ChannelOut, ChannelUpdate, Page
from app.tenders.models import Tender

router = APIRouter(prefix="/api/channels", tags=["channels"])

view = [Depends(require_permission("clients.view"))]
edit = [Depends(require_permission("clients.edit"))]


def _query(q: str | None, type_: str | None, active: bool | None):
    query = select(Channel)
    if q:
        query = query.where(Channel.name.ilike(like(q)))
    if type_:
        query = query.where(Channel.type == type_)
    if active is not None:
        query = query.where(Channel.is_active == active)
    return query.order_by(Channel.name)


def _out(db, channels: list[Channel]) -> list[ChannelOut]:
    ids = [c.id for c in channels]
    lines = dict(
        db.execute(
            select(LibraryLine.channel_id, func.count())
            .where(LibraryLine.channel_id.in_(ids))
            .group_by(LibraryLine.channel_id)
        ).all()
    )
    tenders = dict(
        db.execute(
            select(Tender.channel_id, func.count())
            .where(Tender.channel_id.in_(ids))
            .group_by(Tender.channel_id)
        ).all()
    )
    return [
        ChannelOut.model_validate(c).model_copy(
            update={"library_lines": lines.get(c.id, 0), "tenders": tenders.get(c.id, 0)}
        )
        for c in channels
    ]


@router.get("", dependencies=view)
def list_channels(
    db: DbSession,
    q: Search = None,
    type: str | None = None,
    active: bool | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[ChannelOut]:
    rows, total = paginate(db, _query(q, type, active), limit, offset)
    return Page(items=_out(db, rows), total=total, limit=limit, offset=offset)


@router.get("/export", dependencies=view)
def export_channels(
    db: DbSession, q: Search = None, type: str | None = None, active: bool | None = None
):
    rows = _out(db, list(db.scalars(_query(q, type, active).limit(EXPORT_ROW_LIMIT))))
    return xlsx_response(
        "channels",
        ["Name", "Type", "Active", "Library lines", "Tenders", "Notes"],
        [[c.name, c.type, c.is_active, c.library_lines, c.tenders, c.notes] for c in rows],
    )


def _unique(db, name: str, exclude: int | None = None) -> None:
    query = select(Channel.id).where(func.lower(Channel.name) == name.strip().lower())
    if exclude:
        query = query.where(Channel.id != exclude)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A channel named {name!r} already exists")


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_channel(
    body: ChannelIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ChannelOut:
    _unique(db, body.name)
    channel = Channel(**body.model_dump(), created_by=principal.user.id)
    channel.name = channel.name.strip()
    db.add(channel)
    db.flush()
    audit.record(
        db,
        "channel.create",
        "channel",
        channel.id,
        user_id=principal.user.id,
        after=audit.model_snapshot(channel),
        ip=audit.client_ip(request),
    )
    db.commit()
    return _out(db, [channel])[0]


@router.patch("/{channel_id}", dependencies=edit)
def update_channel(
    channel_id: int,
    body: ChannelUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ChannelOut:
    channel = get_or_404(db, Channel, channel_id, "Channel")
    before = audit.model_snapshot(channel)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name"):
        _unique(db, changes["name"], channel.id)
        changes["name"] = changes["name"].strip()
    for field, value in changes.items():
        if value is not None or field == "notes":
            setattr(channel, field, value)
    db.flush()
    after = audit.model_snapshot(channel)
    if after != before:
        audit.record(
            db,
            "channel.update",
            "channel",
            channel.id,
            user_id=principal.user.id,
            before=before,
            after=after,
            ip=audit.client_ip(request),
        )
    db.commit()
    return _out(db, [channel])[0]


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit)
def delete_channel(
    channel_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    channel = get_or_404(db, Channel, channel_id, "Channel")
    used = _out(db, [channel])[0]
    if used.tenders or used.library_lines:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{channel.name} is used by {used.tenders} tenders and {used.library_lines} rate "
            "library lines; set it inactive instead",
        )
    audit.record(
        db,
        "channel.delete",
        "channel",
        channel.id,
        user_id=principal.user.id,
        before=audit.model_snapshot(channel),
        ip=audit.client_ip(request),
    )
    db.delete(channel)
    db.commit()
