from fastapi import APIRouter
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal
from app.db import DbSession
from app.models import Permission
from app.schemas import PermissionOut

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@router.get("")
def list_permissions(db: DbSession, _: CurrentPrincipal) -> list[PermissionOut]:
    perms = db.scalars(select(Permission).order_by(Permission.module, Permission.code))
    return [PermissionOut.model_validate(p) for p in perms]
