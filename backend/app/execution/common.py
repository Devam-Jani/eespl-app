"""Helpers shared by the execution routers."""

import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal
from app.config import settings
from app.execution.service import unprocessable
from app.models import User

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
PHOTO_MAX = 15 * 1024 * 1024


def optional(code: str):
    def dep(principal: CurrentPrincipal) -> str | None:
        return principal.permissions.get(code)

    dep.__name__ = f"optional_scope[{code}]"
    return dep


def Maybe(code: str):  # noqa: N802
    return Annotated[str | None, Depends(optional(code))]


def record(db, request: Request, principal, action, entity, ident, before=None, after=None):
    audit.record(
        db,
        action,
        entity,
        ident,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def media(rel: str) -> Path:
    return Path(settings.media_dir) / rel


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ ()-]+", "_", Path(name).name)[:150] or "file"


# CAD drawings: stored and downloaded as they are, never opened or rendered
CAD_TYPES = frozenset({".dwg", ".dxf"})


async def save_upload(
    file: UploadFile, folder: str, extra: frozenset[str] = frozenset()
) -> tuple[str, str]:
    """Store an uploaded photo / PDF (or one of the `extra` types) under the media volume;
    (relative path, file name)."""
    name = safe_name(file.filename or "photo.jpg")
    if Path(name).suffix.lower() not in PHOTO_TYPES | extra:
        kinds = "a photo (.jpg, .png, .webp, .heic) or a PDF"
        if extra:
            kinds += " or " + ", ".join(sorted(extra))
        raise unprocessable(f"Upload {kinds}")
    data = await file.read(PHOTO_MAX + 1)
    if len(data) > PHOTO_MAX:
        raise unprocessable("The file is larger than 15 MB")
    if not data:
        raise unprocessable("The file is empty")
    rel = str(Path(folder) / f"{uuid.uuid4().hex}__{name}")
    media(rel).parent.mkdir(parents=True, exist_ok=True)
    media(rel).write_bytes(data)
    return rel, name


def send_file(rel: str | None, filename: str | None = None) -> FileResponse:
    from fastapi import HTTPException, status

    if not rel or not media(rel).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(media(rel), filename=filename or Path(rel).name.split("__", 1)[-1])


def pdf_response(data: bytes, name: str) -> Response:
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )


def names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())
