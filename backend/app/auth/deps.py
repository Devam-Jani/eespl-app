from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.rbac import effective_permissions, widest
from app.auth.security import decode_access_token
from app.db import DbSession
from app.models import User

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    permissions: dict[str, str]  # {permission code: scope}


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


# A client login (only client portal permissions) may call these and nothing else.
CLIENT_PATHS = ("/api/portal/", "/api/auth/", "/api/notifications")


def is_client_login(permissions: dict[str, str]) -> bool:
    return bool(permissions) and all(
        c.startswith("portal.") and c != "portal.manage" for c in permissions
    )


def get_principal(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise _unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token")
    # Permissions are read from the database on every request, so role changes apply at once.
    permissions = effective_permissions(user.roles)
    # what the director allowed this person on top of their roles (costs, deciding won jobs)
    from app.team.models import UserGrant  # noqa: PLC0415

    for code in db.scalars(select(UserGrant.permission_code).where(UserGrant.user_id == user.id)):
        permissions[code] = "all"
    if is_client_login(permissions) and not request.url.path.startswith(CLIENT_PATHS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Client logins can only use the portal")
    return Principal(user=user, permissions=permissions)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_permission(code: str) -> Callable[[Principal], str]:
    """Dependency factory: returns the caller's scope for `code` ('all'|'assigned'|'own'),
    or raises 403.

        @router.get("/x")
        def x(scope: Annotated[str, Depends(require_permission("tender.view"))]): ...
    """

    def dependency(principal: CurrentPrincipal) -> str:
        scope = principal.permissions.get(code)
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {code}")
        return scope

    dependency.__name__ = f"require_permission[{code}]"
    return dependency


def require_any_permission(*codes: str) -> Callable[[Principal], str]:
    """Like require_permission, but any one of `codes` is enough; returns the widest scope."""

    def dependency(principal: CurrentPrincipal) -> str:
        scope: str | None = None
        for code in codes:
            scope = widest(scope, principal.permissions.get(code))
        if scope is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Missing permission: one of {', '.join(codes)}"
            )
        return scope

    dependency.__name__ = f"require_any_permission[{','.join(codes)}]"
    return dependency
