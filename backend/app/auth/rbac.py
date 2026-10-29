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


# Who may manage whom (Prompt 39, Part 0). Super admin > director > office admin > everyone else.
# Nobody gets a set-password link for, resets, unlocks or edits a person whose rank is the same
# as theirs or above; only a super admin manages a super admin. Handing out roles: a ranked role
# only below your own rank (the office admin may add office admins but never a director or super
# admin), and no role that carries an admin/system permission you do not hold yourself.
ROLE_RANK = {SUPER_ADMIN_ROLE_CODE: 3, "director": 2, "office_admin": 1}
SENSITIVE_PREFIXES = ("admin.", "system.", "audit.")


def rank(roles: Iterable[Role]) -> int:
    return max((ROLE_RANK.get(r.code, 0) for r in roles), default=0)


def _sensitive_missing(holder: Mapping[str, str], granted: Mapping[str, str]) -> list[str]:
    return [c for c in ungrantable(holder, granted) if c.startswith(SENSITIVE_PREFIXES)]


def assign_refusal(
    holder_roles: Iterable[Role], holder: Mapping[str, str], roles: Iterable[Role]
) -> str | None:
    """Why these roles may not be handed out by this person (None: they may)."""
    holder_roles, roles = list(holder_roles), list(roles)
    mine = rank(holder_roles)
    if mine == ROLE_RANK[SUPER_ADMIN_ROLE_CODE]:
        return None
    above = [
        r.name for r in roles if ROLE_RANK.get(r.code, 0) > mine or r.code == SUPER_ADMIN_ROLE_CODE
    ]
    if above:
        return f"You cannot assign a role above your own: {', '.join(above)}"
    missing = _sensitive_missing(holder, effective_permissions(roles))
    if missing:
        return (
            f"You cannot assign roles that grant permissions you do not hold: {', '.join(missing)}"
        )
    return None


def manage_refusal(
    holder_roles: Iterable[Role], holder: Mapping[str, str], target_roles: Iterable[Role]
) -> str | None:
    """Why this person may not manage the target (link, reset, unlock, two-step, edit, roles)."""
    holder_roles, target_roles = list(holder_roles), list(target_roles)
    mine, theirs = rank(holder_roles), rank(target_roles)
    if mine == ROLE_RANK[SUPER_ADMIN_ROLE_CODE]:
        return None
    if theirs and theirs >= mine:
        return "You cannot manage a user whose role is the same as yours or above"
    if _sensitive_missing(holder, effective_permissions(target_roles)):
        return "You cannot manage a user who has permissions you do not hold"
    return None
