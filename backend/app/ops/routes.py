# ruff: noqa: E501
"""The health page, the go-live settings banner, and the backups and storage page."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.ops import service as svc

router = APIRouter(tags=["operations"])
Ops = Annotated[str, Depends(require_permission("system.ops"))]
Company = Annotated[str, Depends(require_permission("settings.company"))]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/api/health/full")
def health_full(db: DbSession) -> JSONResponse:
    """For the server's monitor and the /health page: the database, the worker, our OSRM and the
    last backup. States only, never a setting or a secret."""
    out = svc.health(db)
    return JSONResponse(status_code=200 if out["status"] == "ok" else 503, content=jsonable_encoder(out))


@router.get("/api/ops/go-live-checks")
def go_live_checks(db: DbSession, _: Company) -> dict:
    from app.config import settings  # noqa: PLC0415

    return {"missing": [] if settings.training_mode else svc.go_live_checks(db)}  # the training company never goes live


@router.get("/api/ops/backups")
def backups(db: DbSession, _: Ops) -> dict:
    return jsonable_encoder({"backup": svc.backup_status(db), "media": svc.media_report(), "health": svc.health(db)})


# --- users for go-live from the Excel template ---------------------------------------------------------

UsersAdmin = Annotated[str, Depends(require_permission("admin.users"))]


@router.get("/api/ops/user-import/template.xlsx")
def user_template(db: DbSession, _: UsersAdmin) -> Response:
    from app.ops import users_import  # noqa: PLC0415

    return Response(users_import.template(db), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="users-template.xlsx"'})


async def _rows(db, file: UploadFile):
    from app.ops import users_import  # noqa: PLC0415

    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is larger than 5 MB")
    try:
        return users_import.read(db, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/api/ops/user-import/check")
async def user_check(db: DbSession, _: UsersAdmin, file: Annotated[UploadFile, File()]) -> dict:
    """Every row checked; nothing saved."""
    rows = await _rows(db, file)
    return jsonable_encoder({"rows": [r.out() for r in rows], "new": sum(1 for r in rows if not r.errors and not r.exists),
                             "already": sum(1 for r in rows if r.exists and not r.errors), "errors": sum(1 for r in rows if r.errors)})  # fmt: skip


@router.post("/api/ops/user-import/save")
async def user_save(request: Request, db: DbSession, principal: CurrentPrincipal, _: UsersAdmin, file: Annotated[UploadFile, File()]) -> dict:
    """The new users, only when no row has an error; each with a one-time link (shown once)."""
    from app import audit  # noqa: PLC0415
    from app.ops import users_import  # noqa: PLC0415

    rows = await _rows(db, file)
    errors = [r.out() for r in rows if r.errors]
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"message": f"{len(errors)} row(s) have errors: nothing saved", "rows": errors})
    out = users_import.save(db, rows, principal.user.id)
    audit.record(db, "user.import", "user", None, user_id=principal.user.id, after={"new": sum(1 for x in out if x["status"] == "new"), "already": sum(1 for x in out if x["status"] != "new")},
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return {"users": out}


# --- Settings > Roles report (who sees what, for the director's sign-off) -------------------------------


@router.get("/api/ops/roles-report")
def roles_report(db: DbSession, _: Ops) -> dict:
    from app.ops import roles_report as rr  # noqa: PLC0415

    return {"roles": rr.report(db), "never": [label for label, _codes in rr.NEVER]}


@router.get("/api/ops/roles-report.pdf")
def roles_report_pdf(db: DbSession, _: Ops) -> Response:
    from app.ops import roles_report as rr  # noqa: PLC0415

    return Response(rr.pdf(db), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="roles-report.pdf"'})


# --- help: the "?" of each page --------------------------------------------------------------------------

HelpEdit = Annotated[str, Depends(require_permission("help.edit"))]


def _help_for(db, page: str, roles: list[str]) -> dict | None:
    from sqlalchemy import select  # noqa: PLC0415

    from app.ops.help import DEFAULTS  # noqa: PLC0415
    from app.ops.models import HelpText  # noqa: PLC0415

    rows = {r.role: r for r in db.scalars(select(HelpText).where(HelpText.page == page))}
    for role in [*roles, ""]:
        if role in rows:
            r = rows[role]
            return {"page": page, "role": role, "title": r.title, "steps": r.steps, "edited": True, "updated_by": r.updated_by}
        if role in DEFAULTS.get(page, {}):
            title, steps = DEFAULTS[page][role]
            return {"page": page, "role": role, "title": title, "steps": steps, "edited": False}
    return None


@router.get("/api/help")
def help_page(page: str, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The how-to of this page for the person's role (their role's own, else everyone's)."""
    return {"help": _help_for(db, page, [r.code for r in principal.user.roles])}


@router.get("/api/help/all")
def help_all(db: DbSession, _: HelpEdit) -> dict:
    from sqlalchemy import select  # noqa: PLC0415

    from app.ops.help import DEFAULTS  # noqa: PLC0415
    from app.ops.models import HelpText  # noqa: PLC0415

    edited = {(r.page, r.role): r for r in db.scalars(select(HelpText))}
    keys = sorted({(p, role) for p, roles in DEFAULTS.items() for role in roles} | set(edited))
    out = []
    for page, role in keys:
        r = edited.get((page, role))
        d = DEFAULTS.get(page, {}).get(role)
        out.append({"page": page, "role": role, "title": r.title if r else d[0], "steps": r.steps if r else d[1], "edited": r is not None,
                    "updated_by": r.updated_by if r else None, "default": {"title": d[0], "steps": d[1]} if d else None})  # fmt: skip
    return {"pages": out}


class HelpIn(BaseModel):
    page: str = Field(min_length=1, max_length=80)
    role: str = Field(default="", max_length=40)
    title: str = Field(min_length=2, max_length=200)
    steps: list[str] = Field(min_length=3, max_length=6)


@router.put("/api/help")
def help_put(body: HelpIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: HelpEdit) -> dict:
    from sqlalchemy import select  # noqa: PLC0415

    from app import audit  # noqa: PLC0415
    from app.ops.models import HelpText  # noqa: PLC0415

    steps = [s.strip() for s in body.steps if s.strip()]
    if not 3 <= len(steps) <= 6:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give 3 to 6 steps")
    r = db.scalar(select(HelpText).where(HelpText.page == body.page, HelpText.role == body.role))
    if r is None:
        r = HelpText(page=body.page, role=body.role, title=body.title)
        db.add(r)
    r.title, r.steps, r.updated_by = body.title.strip(), steps, principal.user.full_name
    audit.record(db, "help.edit", "help_text", f"{body.page}|{body.role}", user_id=principal.user.id, after={"title": r.title, "steps": steps}, ip=audit.client_ip(request))
    db.commit()
    return {"help": _help_for(db, body.page, [body.role] if body.role else [])}


@router.delete("/api/help")
def help_reset(page: str, request: Request, db: DbSession, principal: CurrentPrincipal, _: HelpEdit, role: str = "") -> dict:
    """Back to the default text."""
    from sqlalchemy import delete  # noqa: PLC0415

    from app import audit  # noqa: PLC0415
    from app.ops.models import HelpText  # noqa: PLC0415

    db.execute(delete(HelpText).where(HelpText.page == page, HelpText.role == role))
    audit.record(db, "help.reset", "help_text", f"{page}|{role}", user_id=principal.user.id, ip=audit.client_ip(request))
    db.commit()
    return {"help": _help_for(db, page, [role] if role else [])}


# --- the real company or the training one ----------------------------------------------------------------


@router.get("/api/ops/mode")
def mode() -> dict:
    """For the banner and the menu's switch: is this the training company, and where the other is."""
    from app.config import settings  # noqa: PLC0415

    return {"training": settings.training_mode, "main_url": settings.main_url or None, "training_url": settings.training_url or None}
