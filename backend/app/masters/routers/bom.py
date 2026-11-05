"""Import the company BOM (Settings > Products > Import BOM): the super admin and planning
(bom.import). The file is read twice: a preview first (the systems, their brand options and
components, the products not in the master and the checks' warnings), then the import of the same
file with the names to create and the default brand chosen. The file itself is never kept."""

import json
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution.common import record
from app.masters import bom

router = APIRouter(prefix="/api/bom", tags=["company BOM"])
Import = Annotated[str, Depends(require_permission("bom.import"))]
MAX_BYTES = 10 * 1024 * 1024
EXACT = {Decimal: str}  # the figures as the file gave them, never floats


async def _data(file: UploadFile) -> bytes:
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The BOM file is over 10 MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is empty")
    return data


@router.post("/preview")
async def preview(
    db: DbSession, principal: CurrentPrincipal, _: Import, file: Annotated[UploadFile, File()]
) -> dict:
    """What the import would write, and what to check first (warnings never block)."""
    data = await _data(file)
    try:
        out = bom.preview(db, data)
    except bom.BomFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    db.rollback()
    return jsonable_encoder(out, custom_encoder=EXACT)


@router.post("/import")
async def import_bom(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Import,
    file: Annotated[UploadFile, File()],
    create: Annotated[str, Form()] = "[]",  # JSON: the names (as in the file) to create as products
    default_brand: Annotated[str | None, Form()] = None,
) -> dict:
    data = await _data(file)
    try:
        names = json.loads(create or "[]")
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            raise ValueError
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "create: a list of product names"
        ) from None
    try:
        out = bom.save(db, data, principal.user.id, names, default_brand or None)
    except bom.BomFormatError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    after = {"file": file.filename, **out["counts"], "default_brand": default_brand}
    record(db, request, principal, "bom.import", "system", None, after=after)
    db.commit()
    return jsonable_encoder(out, custom_encoder=EXACT)
