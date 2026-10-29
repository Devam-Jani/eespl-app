import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.auth.account import end_links
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.auth.passwords import set_password
from app.auth.rbac import (
    CLIENT_ROLE_CODE,
    assign_refusal,
    client_forbidden,
    effective_permissions,
    manage_refusal,
)
from app.auth.router import revoke_all_refresh_tokens
from app.db import DbSession
from app.export import xlsx_response
from app.models import Role, User
from app.schemas import PasswordResetIn, RoleIdsIn, UserCreate, UserOut, UserUpdate

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_permission("admin.users"))],
)


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _resolve_roles(db: Session, role_ids: list[int]) -> list[Role]:
    ids = set(role_ids)
    roles = list(db.scalars(select(Role).where(Role.id.in_(ids)).order_by(Role.id))) if ids else []
    if len(roles) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown role id")
    return roles


def check_role_set(roles: list[Role]) -> None:
    """Data rule: anyone holding the client role may never hold the forbidden permissions."""
    if any(r.code == CLIENT_ROLE_CODE for r in roles):
        forbidden = client_forbidden(effective_permissions(roles))
        if forbidden:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Client users cannot have: {', '.join(forbidden)}",
            )


def check_can_assign(principal: Principal, roles: list[Role]) -> None:
    refusal = assign_refusal(principal.user.roles, principal.permissions, roles)
    if refusal:
        raise HTTPException(status.HTTP_403_FORBIDDEN, refusal)
    check_role_set(roles)


def check_can_manage(principal: Principal, target: User) -> None:
    # Managing someone with the same power or more (e.g. getting a set-password link for them)
    # would be a way to take over their account (rbac.manage_refusal).
    refusal = manage_refusal(principal.user.roles, principal.permissions, target.roles)
    if refusal:
        raise HTTPException(status.HTTP_403_FORBIDDEN, refusal)


def _email_taken(db: Session, email: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(func.count()).select_from(User).where(User.email == email)
    if exclude is not None:
        query = query.where(User.id != exclude)
    return db.scalar(query) > 0


@router.get("")
def list_users(db: DbSession, principal: CurrentPrincipal) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.full_name, User.email))
    out = []
    for u in users:
        o = UserOut.model_validate(u)
        o.can_manage = manage_refusal(principal.user.roles, principal.permissions, u.roles) is None
        out.append(o)
    return out


@router.get("/export")
def export_users(db: DbSession):
    users = db.scalars(select(User).order_by(User.full_name, User.email))
    return xlsx_response(
        "users",
        ["Name", "Email", "Phone", "Job title", "Roles", "Active", "Has password", "Last login"],
        [[u.full_name, u.email, u.phone, u.job_title, [r.name for r in u.roles], u.is_active,
          u.has_password, u.last_login_at] for u in users],
    )  # fmt: skip


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate, request: Request, db: DbSession, principal: CurrentPrincipal
) -> UserOut:
    roles = _resolve_roles(db, body.role_ids)
    check_can_assign(principal, roles)
    if _email_taken(db, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    user = User(
        email=body.email,
        full_name=body.full_name.strip(),
        phone=body.phone,
        roles=roles,
    )
    set_password(
        db, user, body.password
    )  # the same rules as Reset password (not common, not the name)
    db.add(user)
    db.flush()
    audit.record(
        db,
        "user.create",
        "user",
        user.id,
        user_id=principal.user.id,
        after=audit.user_snapshot(user),
        ip=audit.client_ip(request),
    )
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> UserOut:
    user = _get_user(db, user_id)
    check_can_manage(principal, user)
    changes = body.model_dump(exclude_unset=True)
    if "kylas_user_id" in changes and "admin.settings" not in principal.permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: admin.settings (Kylas user id)"
        )
    if changes.get("is_active") is True and not user.is_active:
        email = changes.get("email", user.email)
        if not email or user.password_hash is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Set an email and a password before activating this user",
            )
    if changes.get("is_active") is False and user.id == principal.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate yourself")
    if "email" in changes and _email_taken(db, changes["email"], exclude=user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    for field in ("email", "full_name"):
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be empty")

    before = audit.user_snapshot(user)
    for field, value in changes.items():
        setattr(user, field, value.strip() if field == "full_name" else value)
    if changes.get("is_active") is False:
        revoke_all_refresh_tokens(db, user)
        end_links(db, user)
    after = audit.user_snapshot(user)
    if after != before:
        audit.record(
            db,
            "user.update",
            "user",
            user.id,
            user_id=principal.user.id,
            before=before,
            after=after,
            ip=audit.client_ip(request),
        )
    db.commit()
    return UserOut.model_validate(user)


@router.post("/{user_id}/deactivate")
def deactivate_user(
    user_id: uuid.UUID, request: Request, db: DbSession, principal: CurrentPrincipal
) -> UserOut:
    user = _get_user(db, user_id)
    check_can_manage(principal, user)
    if user.id == principal.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate yourself")
    if user.is_active:
        before = audit.user_snapshot(user)
        user.is_active = False
        revoke_all_refresh_tokens(db, user)
        end_links(db, user)
        audit.record(
            db,
            "user.deactivate",
            "user",
            user.id,
            user_id=principal.user.id,
            before=before,
            after=audit.user_snapshot(user),
            ip=audit.client_ip(request),
        )
        db.commit()
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    body: PasswordResetIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> None:
    user = _get_user(db, user_id)
    check_can_manage(principal, user)
    set_password(db, user, body.password)
    audit.record(
        db,
        "user.password_reset",
        "user",
        user.id,
        user_id=principal.user.id,
        ip=audit.client_ip(request),
    )
    db.commit()


@router.put("/{user_id}/roles")
def set_user_roles(
    user_id: uuid.UUID,
    body: RoleIdsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> UserOut:
    user = _get_user(db, user_id)
    check_can_manage(principal, user)
    roles = _resolve_roles(db, body.role_ids)
    check_can_assign(principal, roles)
    before = audit.user_snapshot(user)
    user.roles = roles
    after = audit.user_snapshot(user)
    if after != before:
        audit.record(
            db,
            "user.roles_set",
            "user",
            user.id,
            user_id=principal.user.id,
            before={"roles": before["roles"]},
            after={"roles": after["roles"]},
            ip=audit.client_ip(request),
        )
    db.commit()
    return UserOut.model_validate(user)
