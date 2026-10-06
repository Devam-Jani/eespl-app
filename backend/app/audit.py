import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import AuditLog, Role, User

_NOT_AUDITED = {"created_at", "updated_at", "search_vector", "password_hash"}


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def record(
    db: Session,
    action: str,
    entity: str,
    entity_id: Any = None,
    *,
    user_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Add an audit row to the session; it is committed with the change it describes."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            before=jsonable_encoder(before) if before is not None else None,
            after=jsonable_encoder(after) if after is not None else None,
            ip=ip,
        )
    )


def user_snapshot(user: User) -> dict[str, Any]:
    """Audit view of a user. Never includes the password hash."""
    return {
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": user.is_active,
        "roles": [r.code for r in user.roles],
    }


def role_snapshot(role: Role) -> dict[str, Any]:
    return {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "permissions": {rp.permission_code: rp.scope for rp in role.permissions},
    }


def model_snapshot(obj: Any, *relations: str) -> dict[str, Any]:
    """Audit view of any mapped object: its column values, plus the named one-to-many
    relations as lists of their column values."""
    mapper = inspect(obj).mapper
    data = {
        attr.key: getattr(obj, attr.key)
        for attr in mapper.column_attrs
        if attr.key not in _NOT_AUDITED
    }
    for name in relations:
        data[name] = [model_snapshot(child) for child in getattr(obj, name)]
    return data
