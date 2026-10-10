from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.auth.rbac import (
    CLIENT_ROLE_CODE,
    FLOOR_ROLES,
    SCOPE_RANK,
    client_forbidden,
    permissions_locked,
    ungrantable,
)
from app.db import DbSession
from app.models import Permission, Role, RolePermission, User, UserRole
from app.schemas import RoleCreate, RoleOut, RolePermissionsIn, RoleUpdate

router = APIRouter(prefix="/api/roles", tags=["roles"])

manage_roles = [Depends(require_permission("admin.roles"))]


def _role_out(role: Role, user_count: int) -> RoleOut:
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions_locked=permissions_locked(role),
        permissions={rp.permission_code: rp.scope for rp in role.permissions},
        user_count=user_count,
    )


def _user_count(db: Session, role: Role) -> int:
    return db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))


def _get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


def _validate_grants(
    db: Session, principal: CurrentPrincipal, role: Role | None, new: dict[str, str]
) -> None:
    known = set(db.scalars(select(Permission.code)))
    unknown = sorted(set(new) - known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown permissions: {', '.join(unknown)}"
        )

    # Only what is being added or widened needs to be within the caller's own permissions.
    current = {rp.permission_code: rp.scope for rp in role.permissions} if role else {}
    added = {code: scope for code, scope in new.items() if current.get(code) != scope}
    missing = ungrantable(principal.permissions, added)
    if missing:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You cannot grant permissions you do not hold: {', '.join(missing)}",
        )

    if role is None:
        return
    forbidden = client_forbidden(new)
    if forbidden and role.code == CLIENT_ROLE_CODE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"The client role cannot have: {', '.join(forbidden)}",
        )
    if forbidden:
        # A client user who also holds this role would gain the forbidden permissions.
        client_users = db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(UserRole.role_id == role.id)
            .where(User.roles.any(Role.code == CLIENT_ROLE_CODE))
        ).all()
        if client_users:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"This role is held by client users, who cannot have: {', '.join(forbidden)}",
            )


@router.get("", dependencies=[Depends(require_any_permission("admin.roles", "admin.users"))])
def list_roles(db: DbSession) -> list[RoleOut]:
    counts = dict(
        db.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id)).all()
    )
    roles = db.scalars(select(Role).order_by(Role.is_system.desc(), Role.id))
    return [_role_out(r, counts.get(r.id, 0)) for r in roles]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=manage_roles)
def create_role(
    body: RoleCreate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> RoleOut:
    if db.scalar(select(func.count()).select_from(Role).where(Role.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with this code already exists")
    _validate_grants(db, principal, None, body.permissions)
    role = Role(
        code=body.code,
        name=body.name.strip(),
        description=body.description,
        is_system=False,
        permissions=[
            RolePermission(permission_code=code, scope=scope)
            for code, scope in sorted(body.permissions.items())
        ],
    )
    db.add(role)
    db.flush()
    audit.record(
        db,
        "role.create",
        "role",
        role.id,
        user_id=principal.user.id,
        after=audit.role_snapshot(role),
        ip=audit.client_ip(request),
    )
    db.commit()
    return _role_out(role, 0)


@router.patch("/{role_id}", dependencies=manage_roles)
def update_role(
    role_id: int, body: RoleUpdate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> RoleOut:
    role = _get_role(db, role_id)
    before = audit.role_snapshot(role)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        if changes["name"] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be empty")
        role.name = changes["name"].strip()
    if "description" in changes:
        role.description = changes["description"]
    after = audit.role_snapshot(role)
    if after != before:
        audit.record(
            db,
            "role.update",
            "role",
            role.id,
            user_id=principal.user.id,
            before=before,
            after=after,
            ip=audit.client_ip(request),
        )
        db.commit()
    return _role_out(role, _user_count(db, role))


@router.put("/{role_id}/permissions", dependencies=manage_roles)
def set_role_permissions(
    role_id: int,
    body: RolePermissionsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> RoleOut:
    role = _get_role(db, role_id)
    if permissions_locked(role):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This role always has every permission and cannot be edited"
        )
    _validate_grants(db, principal, role, body.permissions)
    if role.code in FLOOR_ROLES:
        current = {rp.permission_code: rp.scope for rp in role.permissions}
        reduced = sorted(
            code
            for code, scope in current.items()
            if code not in body.permissions
            or SCOPE_RANK[body.permissions[code]] < SCOPE_RANK[scope]
        )
        if reduced:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The {role.name} role cannot lose permissions: {', '.join(reduced)}",
            )
    before = audit.role_snapshot(role)
    current = {rp.permission_code: rp for rp in role.permissions}
    for code, rp in current.items():
        if code not in body.permissions:
            role.permissions.remove(rp)
    for code, scope in sorted(body.permissions.items()):
        if code in current:
            current[code].scope = scope
        else:
            role.permissions.append(RolePermission(permission_code=code, scope=scope))
    db.flush()
    after = audit.role_snapshot(role)
    if after != before:
        audit.record(
            db,
            "role.permissions_update",
            "role",
            role.id,
            user_id=principal.user.id,
            before={"permissions": before["permissions"]},
            after={"permissions": after["permissions"]},
            ip=audit.client_ip(request),
        )
    db.commit()
    db.refresh(role)
    return _role_out(role, _user_count(db, role))


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=manage_roles)
def delete_role(role_id: int, request: Request, db: DbSession, principal: CurrentPrincipal) -> None:
    role = _get_role(db, role_id)
    if role.is_system:
        raise HTTPException(status.HTTP_409_CONFLICT, "System roles cannot be deleted")
    audit.record(
        db,
        "role.delete",
        "role",
        role.id,
        user_id=principal.user.id,
        before={**audit.role_snapshot(role), "user_count": _user_count(db, role)},
        ip=audit.client_ip(request),
    )
    db.delete(role)
    db.commit()
