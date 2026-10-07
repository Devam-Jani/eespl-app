"""Daily progress reports: one per site per day; the day's activity is pulled in automatically.

dpr.view sees the reports of the sites in its scope; dpr.edit writes and submits them;
acknowledging (the office has read it) needs dpr.edit with scope all.
"""

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import pdf
from app.execution import service as svc
from app.execution.common import names, pdf_response, record, save_upload, send_file
from app.execution.models import Dpr, DprPhoto
from app.material import service as material
from app.sites.models import Site

router = APIRouter(prefix="/api/execution", tags=["execution"])
DprView = Annotated[str, Depends(require_permission("dpr.view"))]


class DprIn(BaseModel):
    weather: str | None = Field(default=None, max_length=60)
    work_done: str | None = None
    hindrances: str | None = None
    next_day_plan: str | None = None
    submit: bool = False


class DprOut(BaseModel):
    id: int | None
    site_id: int
    site_code: str
    site_name: str
    on_date: date
    weather: str | None
    work_done: str | None
    hindrances: str | None
    next_day_plan: str | None
    status: Literal["new", "draft", "submitted", "acknowledged"]
    submitted_by_name: str | None
    submitted_at: str | None
    acknowledged_by_name: str | None
    auto: dict
    photos: list[dict]
    can_edit: bool
    can_acknowledge: bool


def _out(db, site: Site, day: date, d: Dpr | None, principal) -> DprOut:
    edit = principal.permissions.get("dpr.edit")
    can_edit = material.covers_site(db, edit, principal, site.id, site.created_by) and (
        d is None or d.status == "draft"
    )
    who = names(db, [d.submitted_by, d.acknowledged_by] if d else [])
    return DprOut(
        id=d.id if d else None,
        site_id=site.id,
        site_code=site.code,
        site_name=site.name,
        on_date=day,
        weather=d.weather if d else None,
        work_done=d.work_done if d else None,
        hindrances=d.hindrances if d else None,
        next_day_plan=d.next_day_plan if d else None,
        status=d.status if d else "new",
        submitted_by_name=who.get(d.submitted_by) if d else None,
        submitted_at=d.submitted_at.isoformat() if d and d.submitted_at else None,
        acknowledged_by_name=who.get(d.acknowledged_by) if d else None,
        # frozen at submission; live while a draft
        auto=d.auto if d and d.status != "draft" and d.auto else svc.day_activity(db, site.id, day),
        photos=[{"id": p.id, "filename": p.filename, "caption": p.caption} for p in d.photos]
        if d
        else [],
        can_edit=can_edit,
        can_acknowledge=bool(d and d.status == "submitted" and edit == "all"),
    )


def _get(db, site_id, day) -> Dpr | None:
    return db.scalar(select(Dpr).where(Dpr.site_id == site_id, Dpr.on_date == day))


def _visible(db, dpr_id, principal) -> tuple[Dpr, Site]:
    d = db.get(Dpr, dpr_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DPR not found")
    return d, svc.site_for(db, d.site_id, principal, "dpr.view")


@router.get("/dprs")
def list_dprs(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DprView,
    site_id: int | None = None,
    days: Annotated[int, Query(ge=1, le=366)] = 31,
) -> list[dict]:
    q = (
        select(Dpr, Site.code, Site.name)
        .join(Site, Site.id == Dpr.site_id)
        .where(material.by_site(scope, principal, Dpr.site_id, Dpr.created_by))
        .where(Dpr.on_date >= svc.today() - timedelta(days=days))
    )
    if site_id is not None:
        q = q.where(Dpr.site_id == site_id)
    who = {}
    rows = db.execute(q.order_by(Dpr.on_date.desc(), Site.code)).all()
    who = names(db, [d.submitted_by for d, _, _ in rows])
    return [
        {
            "id": d.id,
            "site_id": d.site_id,
            "site_code": c,
            "site_name": n,
            "on_date": d.on_date,
            "status": d.status,
            "weather": d.weather,
            "submitted_by_name": who.get(d.submitted_by),
            "photos": len(d.photos),
        }
        for d, c, n in rows
    ]


@router.get("/dprs/missing")
def missing(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: DprView,
    day: date | None = None,
) -> dict:
    """Active sites with no DPR for the day, once it is past 8 pm (default: today, else
    yesterday before 8 pm)."""
    if day is None:
        local_now = svc.datetime.now(svc.IST)
        day = (
            local_now.date()
            if local_now.time() >= svc.DPR_DUE
            else local_now.date() - timedelta(days=1)
        )
    ids = None if scope == "all" else list(db.scalars(material.assigned_sites(principal)))
    sites = svc.missing_dprs(db, day, ids)
    return {
        "day": day,
        "count": len(sites),
        "sites": [{"id": s.id, "code": s.code, "name": s.name} for s in sites],
    }


@router.get("/sites/{site_id}/dprs/{day}")
def get_dpr(
    site_id: int, day: date, db: DbSession, principal: CurrentPrincipal, _: DprView
) -> DprOut:
    site = svc.site_for(db, site_id, principal, "dpr.view")
    return _out(db, site, day, _get(db, site.id, day), principal)


@router.put("/sites/{site_id}/dprs/{day}")
def save_dpr(
    site_id: int,
    day: date,
    body: DprIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: DprView,
) -> DprOut:
    site = svc.site_for(db, site_id, principal, "dpr.view", "dpr.edit")
    if day > svc.today():
        raise svc.unprocessable("A DPR cannot be written for a future day")
    d = _get(db, site.id, day)
    if d is None:
        d = Dpr(site_id=site.id, on_date=day, created_by=principal.user.id)
        db.add(d)
    elif d.status != "draft":
        raise svc.conflict(f"The DPR of {day:%d %b} is already {d.status}")
    for k in ("weather", "work_done", "hindrances", "next_day_plan"):
        setattr(d, k, getattr(body, k))
    if body.submit:
        if not (body.work_done or "").strip():
            raise svc.unprocessable("Write the work done before submitting")
        d.status, d.submitted_by, d.submitted_at = "submitted", principal.user.id, svc.now()
        d.auto = svc.day_activity(db, site.id, day)
    db.flush()
    record(
        db,
        request,
        principal,
        "dpr.submit" if body.submit else "dpr.save",
        "dpr",
        d.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(d)
    return _out(db, site, day, d, principal)


@router.post("/dprs/{dpr_id}/acknowledge")
def acknowledge(
    dpr_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: DprView
) -> DprOut:
    d, site = _visible(db, dpr_id, principal)
    if principal.permissions.get("dpr.edit") != "all":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The office acknowledges DPRs")
    if d.status != "submitted":
        raise svc.conflict(f"The DPR is {d.status}")
    d.status, d.acknowledged_by, d.acknowledged_at = "acknowledged", principal.user.id, svc.now()
    record(db, request, principal, "dpr.acknowledge", "dpr", d.id)
    db.commit()
    return _out(db, site, d.on_date, d, principal)


@router.post("/sites/{site_id}/dprs/{day}/photos", status_code=status.HTTP_201_CREATED)
async def add_photo(
    site_id: int,
    day: date,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: DprView,
    file: Annotated[UploadFile, File()],
    caption: Annotated[str | None, Form(max_length=300)] = None,
) -> DprOut:
    site = svc.site_for(db, site_id, principal, "dpr.view", "dpr.edit")
    d = _get(db, site.id, day)
    if d is None:
        d = Dpr(site_id=site.id, on_date=day, created_by=principal.user.id)
        db.add(d)
        db.flush()
    elif d.status != "draft":
        raise svc.conflict("The DPR is already submitted")
    rel, name = await save_upload(file, f"dprs/{d.id}")
    d.photos.append(
        DprPhoto(stored_path=rel, filename=name, caption=caption, created_by=principal.user.id)
    )
    record(db, request, principal, "dpr.photo", "dpr", d.id, after={"file": name})
    db.commit()
    db.refresh(d)
    return _out(db, site, day, d, principal)


@router.get("/dprs/{dpr_id}/photos/{photo_id}")
def get_photo(dpr_id: int, photo_id: int, db: DbSession, principal: CurrentPrincipal, _: DprView):
    d, _site = _visible(db, dpr_id, principal)
    p = next((x for x in d.photos if x.id == photo_id), None)
    return send_file(p.stored_path if p else None, p.filename if p else None)


@router.get("/dprs/{dpr_id}/pdf")
def dpr_pdf(dpr_id: int, db: DbSession, principal: CurrentPrincipal, _: DprView):
    d, site = _visible(db, dpr_id, principal)
    out = _out(db, site, d.on_date, d, principal)
    return pdf_response(
        pdf.dpr(db, site, out.model_dump(mode="json"), d), f"DPR-{site.code}-{d.on_date}"
    )
