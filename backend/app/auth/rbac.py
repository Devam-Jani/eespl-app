"""Permission arithmetic and the business rules about who may hold which permissions.

Endpoints never check role names for authorisation; they use require_permission(). The role
codes below are only used for data rules on the roles themselves (the client restriction and
the fixed super_admin grant).
"""

from collections.abc import Iterable, Mapping

from app.models import Role

SCOPE_RANK = {"own": 1, "assigned": 2, "all": 3}

SUPER_ADMIN_ROLE_CODE = "super_admin"
CLIENT_ROLE_CODE = "client"
CLIENT_FORBIDDEN_CODES = frozenset({"tender.margin", "finance.edit"})
# roles whose permissions can be added to in the grid but never reduced (super_admin is locked)
FLOOR_ROLES = frozenset({"director", SUPER_ADMIN_ROLE_CODE})


def widest(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if SCOPE_RANK[a] >= SCOPE_RANK[b] else b


def effective_permissions(roles: Iterable[Role]) -> dict[str, str]:
    """Union of the roles' permissions, keeping the widest scope for each code."""
    result: dict[str, str] = {}
    for role in roles:
        for rp in role.permissions:
            result[rp.permission_code] = widest(result.get(rp.permission_code), rp.scope)
    return dict(sorted(result.items()))


def ungrantable(holder: Mapping[str, str], granted: Mapping[str, str]) -> list[str]:
    """Codes in `granted` that `holder` lacks, or holds with a narrower scope.

    Used to stop privilege escalation: nobody can hand out (or manage someone with)
    more than they have themselves.
    """
    return sorted(
        code
        for code, scope in granted.items()
        if code not in holder or SCOPE_RANK[holder[code]] < SCOPE_RANK[scope]
    )


def client_forbidden(codes: Iterable[str]) -> list[str]:
    return sorted(c for c in codes if c in CLIENT_FORBIDDEN_CODES or c.startswith("admin."))


def permissions_locked(role: Role) -> bool:
    """super_admin always holds every permission; its grid cannot be edited."""
    return role.code == SUPER_ADMIN_ROLE_CODE
