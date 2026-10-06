from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import or_, select

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.auth.scope import check_scope, scope_filter
from app.db import DbSession
from app.masters.models import Client, ClientContact
from app.masters.routers.common import Limit, Offset, Search, get_or_404, like, paginate
from app.masters.schemas import ClientIn, ClientOut, ClientUpdate, ContactIn, Page

router = APIRouter(prefix="/api/clients", tags=["clients"])

ViewScope = Annotated[str, Depends(require_permission("clients.view"))]
EditScope = Annotated[str, Depends(require_permission("clients.edit"))]


def _contacts(items: list[ContactIn], principal: CurrentPrincipal) -> list[ClientContact]:
    return [ClientContact(**c.model_dump(), created_by=principal.user.id) for c in items]


@router.get("")
def list_clients(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ClientOut]:
    query = select(Client).where(scope_filter(scope, principal, Client.created_by))
    if q:
        pattern = like(q)
        query = query.where(
            or_(Client.name.ilike(pattern), Client.city.ilike(pattern), Client.gstin.ilike(pattern))
        )
    if active is not None:
        query = query.where(Client.is_active == active)
    rows, total = paginate(db, query.order_by(Client.name, Client.id), limit, offset)
    return Page(
        items=[ClientOut.model_validate(c) for c in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{client_id}")
def get_client(
    client_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> ClientOut:
    client = get_or_404(db, Client, client_id, "Client")
    check_scope(scope, principal, client.created_by, "view")
    return ClientOut.model_validate(client)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: EditScope
) -> ClientOut:
    # Any edit scope may create; the new client is the caller's own.
    client = Client(
        **body.model_dump(exclude={"contacts"}),
        created_by=principal.user.id,
        contacts=_contacts(body.contacts, principal),
    )
    db.add(client)
    db.flush()
    audit.record(
        db,
        "client.create",
        "client",
        client.id,
        user_id=principal.user.id,
        after=audit.model_snapshot(client, "contacts"),
        ip=audit.client_ip(request),
    )
    db.commit()
    return ClientOut.model_validate(client)


@router.patch("/{client_id}")
def update_client(
    client_id: int,
    body: ClientUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: EditScope,
) -> ClientOut:
    client = get_or_404(db, Client, client_id, "Client")
    check_scope(scope, principal, client.created_by)
    before = audit.model_snapshot(client, "contacts")
    changes = body.model_dump(exclude_unset=True, exclude={"contacts"})
    for field, value in changes.items():
        if field in ("name", "type", "is_active") and value is None:
            continue
        setattr(client, field, value)
    if body.contacts is not None:
        client.contacts = _contacts(body.contacts, principal)
    db.flush()
    after = audit.model_snapshot(client, "contacts")
    if after != before:
        audit.record(
            db,
            "client.update",
            "client",
            client.id,
            user_id=principal.user.id,
            before=before,
            after=after,
            ip=audit.client_ip(request),
        )
    db.commit()
    db.refresh(client)
    return ClientOut.model_validate(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: EditScope
) -> None:
    client = get_or_404(db, Client, client_id, "Client")
    check_scope(scope, principal, client.created_by, "delete")
    audit.record(
        db,
        "client.delete",
        "client",
        client.id,
        user_id=principal.user.id,
        before=audit.model_snapshot(client, "contacts"),
        ip=audit.client_ip(request),
    )
    db.delete(client)
    db.commit()
