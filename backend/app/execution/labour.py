"""Labour master, daily attendance (quick mark), the monthly muster roll and staff check-in.

labour.view / labour.edit by the site the worker is posted to (assigned = the caller's sites).
A worker has one attendance row per day, so nobody is present at two sites on the same day.
"""

from datetime import date, time
from decimal import Decimal
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
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.execution import service as svc
from app.execution.common import record, save_upload
from app.execution.models import Attendance, Labour, StaffAttendance
from app.export import xlsx_response
from app.masters.models import Vendor
from app.material import service as material
from app.sites.models import Site

router = APIRouter(prefix="/api/execution", tags=["execution"])
LabourView = Annotated[str, Depends(require_permission("labour.view"))]

Trade = Literal["applicator", "helper", "mason", "supervisor", "other"]


class LabourIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    trade: Trade = "helper"
    type: Literal["own", "subcontractor"] = "own"
    subcontractor_id: int | None = None
    site_id: int | None = None
    daily_wage: Decimal = Field(default=Decimal(0), ge=0)
    ot_rate_per_hour: Decimal = Field(default=Decimal(0), ge=0)
    # Anything typed here is cut to its last 4 digits before it is stored (or logged).
    aadhaar: str | None = Field(default=None, max_length=20)
    is_active: bool = True

    @field_validator("aadhaar")
    @classmethod
    def last4(cls, v: str | None) -> str | None:
        return svc.aadhaar_last4(v) if v else None


class LabourOut(BaseModel):
    id: int
    name: str
    phone: str | None
    trade: str
    type: str
    subcontractor_id: int | None
    subcontractor_name: str | None
    site_id: int | None
    site_code: str | None
    daily_wage: Decimal
    ot_rate_per_hour: Decimal
    aadhaar_last4: str | None
    is_active: bool


def _labour_out(db, w: Labour) -> LabourOut:
    code = db.scalar(select(Site.code).where(Site.id == w.site_id)) if w.site_id else None
    return LabourOut(
        id=w.id,
        name=w.name,
        phone=w.phone,
        trade=w.trade,
        type=w.type,
        subcontractor_id=w.subcontractor_id,
        subcontractor_name=w.subcontractor.name if w.subcontractor else None,
        site_id=w.site_id,
        site_code=code,
        daily_wage=w.daily_wage,
        ot_rate_per_hour=w.ot_rate_per_hour,
        aadhaar_last4=w.aadhaar_last4,
        is_active=w.is_active,
    )


def _labour_cond(scope, principal):
    return material.by_site(scope, principal, Labour.site_id, Labour.created_by)


def _check_labour(db, body: LabourIn, principal):
    if body.type == "subcontractor":
        v = db.get(Vendor, body.subcontractor_id) if body.subcontractor_id else None
        if v is None or v.type != "subcontractor":
            raise svc.unprocessable("Pick the subcontractor this worker comes from")
    elif body.subcontractor_id:
        raise svc.unprocessable("Own labour has no subcontractor")
    edit = svc.need(principal, "labour.edit")
    if body.site_id:
        svc.site_for(db, body.site_id, principal, "labour.view", "labour.edit")
    elif edit != "all":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Post the worker to one of your sites")


@router.get("/labour")
def list_labour(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: LabourView,
    site_id: int | None = None,
    q: str | None = None,
    type: str | None = None,
    active: bool | None = True,
) -> list[LabourOut]:
    query = select(Labour).where(_labour_cond(scope, principal))
    if site_id is not None:
        query = query.where(Labour.site_id == site_id)
    if q:
        query = query.where(or_(Labour.name.ilike(f"%{q}%"), Labour.phone.ilike(f"%{q}%")))
    if type:
        query = query.where(Labour.type == type)
    if active is not None:
        query = query.where(Labour.is_active == active)
    return [_labour_out(db, w) for w in db.scalars(query.order_by(Labour.name).limit(1000))]


@router.post("/labour", status_code=status.HTTP_201_CREATED)
def create_labour(
    body: LabourIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> LabourOut:
    _check_labour(db, body, principal)
    w = Labour(
        **body.model_dump(exclude={"aadhaar"}),
        aadhaar_last4=body.aadhaar,
        created_by=principal.user.id,
    )
    db.add(w)
    db.flush()
    # the audit row carries only the last 4 digits (the model holds nothing else)
    record(
        db,
        request,
        principal,
        "labour.create",
        "labour",
        w.id,
        after=body.model_dump(mode="json", exclude={"aadhaar"})
        | {"aadhaar_last4": w.aadhaar_last4},
    )
    db.commit()
    db.refresh(w)
    return _labour_out(db, w)


@router.put("/labour/{labour_id}")
def update_labour(
    labour_id: int,
    body: LabourIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: LabourView,
) -> LabourOut:
    w = db.get(Labour, labour_id)
    if w is None or not material.covers_site(db, scope, principal, w.site_id, w.created_by):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Worker not found")
    _check_labour(db, body, principal)
    data = body.model_dump(exclude={"aadhaar"})
    for k, v in data.items():
        setattr(w, k, v)
    if body.aadhaar:
        w.aadhaar_last4 = body.aadhaar
    record(
        db,
        request,
        principal,
        "labour.update",
        "labour",
        w.id,
        after=data | {"aadhaar_last4": w.aadhaar_last4},
    )
    db.commit()
    db.refresh(w)
    return _labour_out(db, w)


# --- attendance ----------------------------------------------------------------------------------


class Mark(BaseModel):
    labour_id: int
    status: Literal["present", "half_day", "absent"]
    in_time: time | None = None
    out_time: time | None = None
    ot_hours: Decimal = Field(default=Decimal(0), ge=0, le=16)


class MarksIn(BaseModel):
    marks: list[Mark] = Field(min_length=1)
    lat: Decimal | None = None
    lng: Decimal | None = None


def _day_sheet(db, site: Site, day: date) -> dict:
    marks = {
        a.labour_id: a
        for a in db.scalars(
            select(Attendance).where(Attendance.site_id == site.id, Attendance.on_date == day)
        )
    }
    posted = list(db.scalars(select(Labour).where(Labour.site_id == site.id, Labour.is_active)))
    elsewhere = dict(
        db.execute(
            select(Attendance.labour_id, Site.code)
            .join(Site, Site.id == Attendance.site_id)
            .where(
                Attendance.on_date == day,
                Attendance.site_id != site.id,
                Attendance.labour_id.in_([w.id for w in posted] or [0]),
            )
        ).all()
    )
    workers = {w.id: w for w in posted}
    for a in marks.values():
        workers.setdefault(a.labour_id, a.labour)
    rows = []
    for w in sorted(workers.values(), key=lambda x: (x.type, x.name)):
        a = marks.get(w.id)
        rows.append(
            {
                "labour_id": w.id,
                "name": w.name,
                "trade": w.trade,
                "type": w.type,
                "subcontractor_name": w.subcontractor.name if w.subcontractor else None,
                "status": a.status if a else None,
                "ot_hours": str(a.ot_hours) if a else "0",
                "in_time": a.in_time.isoformat() if a and a.in_time else None,
                "out_time": a.out_time.isoformat() if a and a.out_time else None,
                "elsewhere": elsewhere.get(w.id),
                "photo": bool(a and a.photo_path),
            }
        )
    counts = {
        s: sum(1 for r in rows if r["status"] == s) for s in ("present", "half_day", "absent")
    }
    return {
        "site_id": site.id,
        "site_code": site.code,
        "day": day,
        "rows": rows,
        "counts": counts,
        "unmarked": sum(1 for r in rows if r["status"] is None and not r["elsewhere"]),
    }


@router.get("/sites/{site_id}/attendance/{day}")
def day_sheet(
    site_id: int, day: date, db: DbSession, principal: CurrentPrincipal, _: LabourView
) -> dict:
    site = svc.site_for(db, site_id, principal, "labour.view")
    return _day_sheet(db, site, day)


@router.put("/sites/{site_id}/attendance/{day}")
def mark(
    site_id: int,
    day: date,
    body: MarksIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: LabourView,
) -> dict:
    """Mark (or correct) attendance. A worker already marked at another site that day is a 422."""
    site = svc.site_for(db, site_id, principal, "labour.view", "labour.edit")
    if day > svc.today():
        raise svc.unprocessable("Attendance cannot be marked for a future day")
    for m in body.marks:
        w = db.get(Labour, m.labour_id)
        if w is None:
            raise svc.unprocessable(f"Worker {m.labour_id} not found")
        a = db.scalar(
            select(Attendance).where(Attendance.labour_id == w.id, Attendance.on_date == day)
        )
        if a is not None and a.site_id != site.id:
            other = db.get(Site, a.site_id)
            raise svc.unprocessable(f"{w.name} is already marked at {other.code} on {day:%d %b %Y}")
        if a is None:
            a = Attendance(
                labour_id=w.id,
                site_id=site.id,
                on_date=day,
                status=m.status,
                created_by=principal.user.id,
            )
            db.add(a)
        if m.status == "absent" and m.ot_hours:
            raise svc.unprocessable(f"{w.name}: no overtime on an absent day")
        a.status, a.in_time, a.out_time, a.ot_hours = m.status, m.in_time, m.out_time, m.ot_hours
        a.daily_wage, a.ot_rate_per_hour = w.daily_wage, w.ot_rate_per_hour
        a.marked_by, a.lat, a.lng = principal.user.id, body.lat, body.lng
    db.flush()
    record(
        db,
        request,
        principal,
        "attendance.mark",
        "site",
        site.id,
        after={"day": str(day), "marks": [m.model_dump(mode="json") for m in body.marks]},
    )
    db.commit()
    return _day_sheet(db, site, day)


@router.post("/sites/{site_id}/attendance/{day}/photo")
async def attendance_photo(
    site_id: int,
    day: date,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: LabourView,
    file: Annotated[UploadFile, File()],
    labour_id: Annotated[int | None, Form()] = None,
) -> dict:
    """A selfie (one worker) or a group photo (everyone marked that day)."""
    site = svc.site_for(db, site_id, principal, "labour.view", "labour.edit")
    q = select(Attendance).where(Attendance.site_id == site.id, Attendance.on_date == day)
    if labour_id:
        q = q.where(Attendance.labour_id == labour_id)
    rows = list(db.scalars(q))
    if not rows:
        raise svc.unprocessable("Mark the attendance first")
    rel, name = await save_upload(file, f"attendance/{site.id}/{day}")
    for a in rows:
        a.photo_path = rel
    record(
        db,
        request,
        principal,
        "attendance.photo",
        "site",
        site.id,
        after={"day": str(day), "file": name},
    )
    db.commit()
    return _day_sheet(db, site, day)


@router.get("/attendance/today")
def all_sites_today(
    db: DbSession, principal: CurrentPrincipal, scope: LabourView, day: date | None = None
) -> dict:
    """Every active site in scope: workers posted, marked present / half day / absent."""
    day = day or svc.today()
    sites = db.scalars(
        select(Site)
        .where(
            Site.status.in_(("active", "planned")),
            material.by_site(scope, principal, Site.id, Site.created_by),
        )
        .order_by(Site.code)
    )
    out = []
    for s in sites:
        posted = db.scalar(select(func.count()).where(Labour.site_id == s.id, Labour.is_active))
        counts = dict(
            db.execute(
                select(Attendance.status, func.count())
                .where(Attendance.site_id == s.id, Attendance.on_date == day)
                .group_by(Attendance.status)
            ).all()
        )
        if not posted and not counts:
            continue
        out.append(
            {
                "site_id": s.id,
                "code": s.code,
                "name": s.name,
                "posted": posted,
                "present": counts.get("present", 0),
                "half_day": counts.get("half_day", 0),
                "absent": counts.get("absent", 0),
            }
        )
    return {"day": day, "sites": out}


# --- muster roll ---------------------------------------------------------------------------------

Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]


def _muster(db, principal, scope, month, site_id, labour_id):
    if site_id is not None:
        svc.site_for(db, site_id, principal, "labour.view")
    start, end = svc.month_range(month)
    rows = svc.muster(db, start, end, site_id, labour_id)
    if scope != "all":
        ids = set(db.scalars(material.assigned_sites(principal)))
        rows = [r for r in rows if r["site_id"] in ids]
    codes = dict(db.execute(select(Site.id, Site.code)).all())
    for r in rows:
        r["site_code"] = codes.get(r["site_id"])
    return rows, end.day


@router.get("/muster")
def muster_roll(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: LabourView,
    month: Month,
    site_id: int | None = None,
    labour_id: int | None = None,
) -> dict:
    rows, _ = _muster(db, principal, scope, month, site_id, labour_id)
    total = sum((r["wage_due"] for r in rows), Decimal(0))
    return {"month": month, "rows": rows, "wage_due": total}


@router.get("/muster/export")
def muster_export(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: LabourView,
    month: Month,
    site_id: int | None = None,
    labour_id: int | None = None,
):
    rows, days = _muster(db, principal, scope, month, site_id, labour_id)
    cols = [
        "Site",
        "Worker",
        "Trade",
        "Type",
        *[str(d) for d in range(1, days + 1)],
        "Days",
        "Half days",
        "OT hours",
        "Daily wage",
        "Wage due",
    ]
    data = [
        [
            r["site_code"],
            r["name"],
            r["trade"],
            r["type"],
            *[r["marks"].get(d, "") for d in range(1, days + 1)],
            r["days"],
            r["half_days"],
            r["ot_hours"],
            r["daily_wage"],
            r["wage_due"],
        ]
        for r in rows
    ]
    return xlsx_response(f"muster-roll-{month}", cols, data, f"Muster roll {month}")


# --- staff check-in ------------------------------------------------------------------------------


class GeoIn(BaseModel):
    lat: Decimal | None = None
    lng: Decimal | None = None


def _staff_out(db, s: StaffAttendance) -> dict:
    return {
        "id": s.id,
        "site_id": s.site_id,
        "site_code": db.get(Site, s.site_id).code,
        "on_date": s.on_date,
        "check_in_at": s.check_in_at,
        "check_out_at": s.check_out_at,
    }


@router.post("/sites/{site_id}/check-in", status_code=status.HTTP_201_CREATED)
def check_in(
    site_id: int, body: GeoIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Staff (any user who can see the site) check in at a site; one open check-in at a time."""
    site = svc.site_for(db, site_id, principal, "site.view")
    open_ = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.user_id == principal.user.id, StaffAttendance.check_out_at.is_(None)
        )
    )
    if open_ is not None:
        raise svc.conflict(f"Check out of {db.get(Site, open_.site_id).code} first")
    s = StaffAttendance(
        user_id=principal.user.id,
        site_id=site.id,
        on_date=svc.today(),
        check_in_at=svc.now(),
        lat=body.lat,
        lng=body.lng,
    )
    db.add(s)
    db.flush()
    record(db, request, principal, "staff.check_in", "site", site.id)
    db.commit()
    return _staff_out(db, s)


@router.post("/check-out")
def check_out(request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    s = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.user_id == principal.user.id, StaffAttendance.check_out_at.is_(None)
        )
    )
    if s is None:
        raise svc.conflict("You are not checked in")
    s.check_out_at = svc.now()
    record(db, request, principal, "staff.check_out", "site", s.site_id)
    db.commit()
    return _staff_out(db, s)


@router.get("/staff-attendance")
def staff_attendance(
    db: DbSession, principal: CurrentPrincipal, month: Month | None = None, mine: bool = True
) -> list[dict]:
    """Your own check-ins; everyone's needs labour.view with scope all."""
    q = select(StaffAttendance)
    if mine or principal.permissions.get("labour.view") != "all":
        q = q.where(StaffAttendance.user_id == principal.user.id)
    if month:
        start, end = svc.month_range(month)
        q = q.where(StaffAttendance.on_date >= start, StaffAttendance.on_date <= end)
    return [
        _staff_out(db, s)
        for s in db.scalars(q.order_by(StaffAttendance.check_in_at.desc()).limit(200))
    ]
