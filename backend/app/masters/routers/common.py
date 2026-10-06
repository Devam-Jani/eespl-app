from typing import Annotated, Any

from fastapi import HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

Search = Annotated[str | None, Query(max_length=200, description="Search text")]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def get_or_404(db: Session, model, ident: Any, label: str):
    obj = db.get(model, ident)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return obj


def paginate(db: Session, query: Select, limit: int, offset: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = list(db.scalars(query.limit(limit).offset(offset)))
    return rows, total


def like(text: str) -> str:
    escaped = text.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


def unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)
