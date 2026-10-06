"""Applying a permission's scope to records.

all       every record
own       only records the caller created (created_by)
assigned  only sites/tenders the caller is assigned to; the assignment tables arrive in M3,
          so until then 'assigned' matches nothing on tables without assignments.
"""

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, false, true

from app.auth.deps import Principal


def scope_filter(scope: str, principal: Principal, created_by_column) -> ColumnElement[bool]:
    """A WHERE condition limiting a query to the records the scope allows."""
    if scope == "all":
        return true()
    if scope == "own":
        return created_by_column == principal.user.id
    return false()


def check_scope(scope: str, principal: Principal, created_by, action: str = "change") -> None:
    """Raise 403 unless the scope covers a record created by `created_by`."""
    if scope == "all":
        return
    if scope == "own" and created_by == principal.user.id:
        return
    detail = (
        f"You can only {action} records you created"
        if scope == "own"
        else f"You can only {action} records assigned to you"
    )
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
