# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Site surveys (/api/surveys): areas measured by laser, by hand, AR or the marker photo; product
quantities; BOQ lines, indent drafts, PDF and Excel; the camera pilot report; area types and
survey settings; AI photo suggestions.

survey.view / survey.edit carry the scope (all, assigned: the caller's sites, own: their leads
and tenders); survey.approve approves; survey.ai asks the AI. Rates and costs need tender.margin.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.crm.models import Lead
from app.db import DbSession
from app.execution.common import names, pdf_response, record, save_upload, send_file
from app.execution.service import site_for
from app.masters.models import Product, System
from app.material import service as material
from app.material.models import Indent, IndentLine
from app.models import User
from app.sites.models import Site, SiteNode
from app.survey import ai
from app.survey import pdf as survey_pdf
from app.survey import service as svc
from app.survey.models import (
    CAMERA_METHODS,
    AiCall,
    AreaType,
    Survey,
    SurveyArea,
    SurveyBoqLink,
    SurveyPhoto,
)
from app.tenders import pricing
from app.tenders.models import BoqLine, Tender
from app.tenders.service import check_edit
from app.tenders.service import get_visible as tender_visible

router = APIRouter(prefix="/api/surveys", tags=["survey"])
View = Annotated[str, Depends(require_permission("survey.view"))]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOCKED = ("approved",)


def _edit(db, survey: Survey, principal) -> None:
    scope = principal.permissions.get("survey.edit")
    if (
        scope is None
        or db.scalar(svc.visible_q(scope, principal).where(Survey.id == survey.id)) is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this survey")
    if survey.status in LOCKED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{survey.code} is approved: reopen it to change it"
        )


def _parent(db, s: Survey) -> dict:
    if s.site_id:
        site = db.get(Site, s.site_id)
        return {
            "kind": "site",
            "id": site.id,
            "code": site.code,
            "name": site.name,
            "link": f"/sites/{site.id}",
        }
    if s.tender_id:
        t = db.get(Tender, s.tender_id)
        return {
            "kind": "tender",
            "id": t.id,
            "code": t.code,
            "name": t.name,
            "link": f"/tenders/{t.id}",
        }
    lead = db.get(Lead, s.lead_id)
    return {
        "kind": "lead",
        "id": lead.id,
        "code": lead.code,
        "name": lead.contact_name,
        "link": f"/leads/{lead.id}",
    }


def _photo_out(p: SurveyPhoto) -> dict:
    return {
        "id": p.id,
        "filename": p.filename,
        "has_overlay": bool(p.overlay_path),
        "mode": p.mode,
        "taken_at": p.taken_at,
        "marker_found": p.marker_found,
        "width": p.width_px,
        "height": p.height_px,
    }


def _area_out(a: SurveyArea, types: dict, mismatch_limit: Decimal) -> dict:
    mm = svc.mismatch_percent(a)
    return {
        **{
            k: getattr(a, k)
            for k in (
                "id",
                "node_id",
                "tower",
                "floor_label",
                "floor_no",
                "name",
                "area_type_id",
                "shape",
                "length_m",
                "width_m",
                "polygon_m",
                "direct_area_sqm",
                "deductions_sqm",
                "perimeter_m",
                "perimeter_manual",
                "upturn_mm",
                "wall_height_m",
                "sunk_depth_mm",
                "count",
                "system_id",
                "wastage_override_percent",
                "method",
                "accuracy_note",
                "remarks",
                "camera_method",
                "camera_floor_sqm",
                "floor_area_sqm",
                "upturn_area_sqm",
                "wall_area_sqm",
                "sunk_area_sqm",
                "treated_area_sqm",
                "ai_suggestion",
            )
        },
        "area_type": types.get(a.area_type_id),
        "camera_measured": a.method in CAMERA_METHODS,
        "mismatch_percent": mm,
        "mismatch_flag": mm is not None and mm > mismatch_limit,
        "photos": [_photo_out(p) for p in a.photos],
    }


def _totals(s: Survey, types: dict) -> dict:
    by_type: dict[str, Decimal] = {}
    by_floor: dict[str, Decimal] = {}
    for a in s.areas:
        t = types.get(a.area_type_id) or "No type"
        by_type[t] = by_type.get(t, Decimal(0)) + Decimal(a.treated_area_sqm)
        f = " ".join(x for x in (a.tower, a.floor_label) if x) or "No floor"
        by_floor[f] = by_floor.get(f, Decimal(0)) + Decimal(a.treated_area_sqm)
    return {"treated": sum(by_type.values(), Decimal(0)), "by_type": by_type, "by_floor": by_floor}


def _out(db, s: Survey, principal) -> dict:
    types = {t.id: t.name for t in db.scalars(select(AreaType))}
    st = svc.settings(db)
    who = names(db, [s.surveyed_by, s.approved_by, s.created_by])
    edit_scope = principal.permissions.get("survey.edit")
    can_edit = (
        edit_scope is not None
        and db.scalar(svc.visible_q(edit_scope, principal).where(Survey.id == s.id)) is not None
    )
    return jsonable_encoder(
        {
            **{
                k: getattr(s, k)
                for k in (
                    "id",
                    "code",
                    "title",
                    "surveyed_on",
                    "status",
                    "submitted_at",
                    "approved_at",
                    "notes",
                    "lead_id",
                    "tender_id",
                    "site_id",
                )
            },
            "parent": _parent(db, s),
            "surveyed_by": str(s.surveyed_by) if s.surveyed_by else None,
            "surveyed_by_name": who.get(s.surveyed_by),
            "approved_by_name": who.get(s.approved_by),
            "areas": [_area_out(a, types, Decimal(st.mismatch_percent)) for a in s.areas],
            "totals": _totals(s, types),
            "can_edit": can_edit and s.status not in LOCKED,
            "can_approve": "survey.approve" in principal.permissions,
            "ai_available": ai.available(db) and "survey.ai" in principal.permissions,
            "photo_required": st.photo_required,
        }
    )


# --- settings, area types, preferences (before /{id}) --------------------------------------------


class SettingsIn(BaseModel):
    photo_required: bool
    camera_billing_allowed: bool
    mismatch_percent: Decimal = Field(ge=0, le=50)
    ai_enabled: bool
    ai_model: str = Field(min_length=1, max_length=60)
    ai_monthly_cap_inr: Decimal = Field(ge=0)
    ai_usd_per_mtok_in: Decimal = Field(ge=0)
    ai_usd_per_mtok_out: Decimal = Field(ge=0)
    ai_inr_per_usd: Decimal = Field(gt=0)


def _settings_out(db) -> dict:
    s = svc.settings(db)
    return jsonable_encoder(
        {
            **{k: getattr(s, k) for k in SettingsIn.model_fields},
            "ai_key_present": ai.key_present(),
            "ai_month_spend_inr": ai.month_spend(db),
        }
    )


@router.get("/settings")
def get_settings(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    return _settings_out(db)


@router.put("/settings")
def put_settings(
    body: SettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    if not ({"admin.settings", "settings.company"} & set(principal.permissions)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: settings.company")
    s = svc.settings(db)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "survey.settings",
        "survey_settings",
        1,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _settings_out(db)


class AreaTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_system_id: int | None = None
    default_upturn_mm: Decimal = Field(default=Decimal(0), ge=0, le=3000)
    default_wastage_percent: Decimal | None = Field(default=None, ge=0, le=100)
    includes_walls: bool = False
    needs_sunk_depth: bool = False
    sort_order: int = 0
    is_active: bool = True
    confirmed: bool = False


def _type_out(t: AreaType) -> dict:
    return {"id": t.id, **{k: getattr(t, k) for k in AreaTypeIn.model_fields}}


@router.get("/area-types")
def area_types(db: DbSession, principal: CurrentPrincipal, _: View) -> list[dict]:
    return jsonable_encoder(
        [
            _type_out(t)
            for t in db.scalars(select(AreaType).order_by(AreaType.sort_order, AreaType.name))
        ]
    )


def _types_edit(principal) -> None:
    if not ({"settings.company", "admin.settings", "survey.approve"} & set(principal.permissions)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: settings.company")


@router.post("/area-types", status_code=status.HTTP_201_CREATED)
def add_area_type(
    body: AreaTypeIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    _types_edit(principal)
    t = AreaType(**body.model_dump(), created_by=principal.user.id)
    db.add(t)
    db.flush()
    record(
        db,
        request,
        principal,
        "survey.area_type.create",
        "area_type",
        t.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return jsonable_encoder(_type_out(t))


@router.put("/area-types/{tid}")
def put_area_type(
    tid: int,
    body: AreaTypeIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: View,
) -> dict:
    _types_edit(principal)
    t = db.get(AreaType, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area type not found")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    record(
        db,
        request,
        principal,
        "survey.area_type.update",
        "area_type",
        t.id,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return jsonable_encoder(_type_out(t))


class UnitIn(BaseModel):
    unit: Literal["m", "ftin"]


@router.put("/me/unit")
def set_unit(body: UnitIn, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    user = db.get(User, principal.user.id)
    user.measure_unit = body.unit
    db.commit()
    return {"unit": user.measure_unit}


@router.get("/lookups")
def lookups(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """What the entry screen needs: area types, active systems (names only), the user's unit."""
    user = db.get(User, principal.user.id)
    return jsonable_encoder(
        {
            "area_types": [
                _type_out(t)
                for t in db.scalars(
                    select(AreaType).where(AreaType.is_active).order_by(AreaType.sort_order)
                )
            ],
            "systems": [
                {"id": s.id, "name": s.name, "unit": s.unit}
                for s in db.scalars(select(System).where(System.is_active).order_by(System.name))
            ],
            "unit": user.measure_unit,
        }
    )


@router.get("/marker-sheet.pdf")
def marker_sheet(
    db: DbSession, principal: CurrentPrincipal, _: View, size: Literal["a4", "a3"] = "a4"
):
    """A4: two 150 mm markers. A3: two 250 mm markers, to frame about 2.5 m across."""
    return pdf_response(
        survey_pdf.marker_sheet(db, size), f"EESPL-measuring-markers-{size.upper()}"
    )


# --- pilot report (camera vs laser) --------------------------------------------------------------


@router.get("/pilot")
def pilot(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    format: Literal["json", "xlsx"] = "json",
):
    """Every area with both a camera value and a laser / manual value: the difference per mode."""
    surveys = svc.visible_q(scope, principal).subquery()
    rows = []
    for a, code in db.execute(
        select(SurveyArea, surveys.c.code)
        .join(surveys, surveys.c.id == SurveyArea.survey_id)
        .where(SurveyArea.camera_floor_sqm.is_not(None), SurveyArea.method.not_in(CAMERA_METHODS))
    ):
        mm = svc.mismatch_percent(a)
        if mm is None:
            continue
        laser = Decimal(a.floor_area_sqm) + Decimal(a.deductions_sqm or 0)
        signed = (Decimal(a.camera_floor_sqm) - laser) / laser * 100
        rows.append(
            {
                "survey": code,
                "area_id": a.id,
                "area": a.name,
                "mode": a.camera_method,
                "camera_sqm": a.camera_floor_sqm,
                "laser_sqm": svc.q3(laser),
                "laser_method": a.method,
                "difference_percent": signed.quantize(Decimal("0.1")),
                "abs_percent": mm,
            }
        )
    summary = []
    for mode in CAMERA_METHODS:
        xs = [r["abs_percent"] for r in rows if r["mode"] == mode]
        if xs:
            summary.append(
                {
                    "mode": mode,
                    "areas": len(xs),
                    "average_percent": (sum(xs) / len(xs)).quantize(Decimal("0.1")),
                    "worst_percent": max(xs),
                }
            )
    if format == "xlsx":
        from app.analytics.reports import xlsx_book

        cols = [
            {"key": k, "label": label}
            for k, label in (
                ("survey", "Survey"),
                ("area", "Area"),
                ("mode", "Camera mode"),
                ("camera_sqm", "Camera sqm"),
                ("laser_sqm", "Laser / manual sqm"),
                ("laser_method", "Laser method"),
                ("difference_percent", "Difference %"),
            )
        ]
        scols = [
            {"key": k, "label": label}
            for k, label in (
                ("mode", "Mode"),
                ("areas", "Areas"),
                ("average_percent", "Average %"),
                ("worst_percent", "Worst %"),
            )
        ]
        data = xlsx_book(
            [("Areas", cols, rows), ("Summary", scols, summary)],
            "Floor area by the camera vs by laser / hand, same area.",
        )
        return Response(
            data,
            media_type=XLSX,
            headers={"Content-Disposition": 'attachment; filename="camera-pilot.xlsx"'},
        )
    return jsonable_encoder(
        {"rows": rows, "summary": summary, "limit_percent": svc.settings(db).mismatch_percent}
    )


# --- 3D view: approved surveys of a site ---------------------------------------------------------


@router.get("/site-map/{site_id}")
def site_map(site_id: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    """Per site node: measured (laser / manual), camera only, or not measured; and product totals
    per node (approved surveys only). The 3D view rolls them up to floors and towers."""
    site = site_for(db, site_id, principal, "site.view")
    areas = list(
        db.scalars(
            select(SurveyArea)
            .join(Survey, Survey.id == SurveyArea.survey_id)
            .where(Survey.site_id == site.id, Survey.status == "approved")
        )
    )
    state: dict[int, str] = {}
    for a in areas:
        if a.node_id is None:
            continue
        mark = "camera" if a.method in CAMERA_METHODS else "measured"
        if state.get(a.node_id) != "measured":
            state[a.node_id] = mark
    c = svc.consumption(db, areas)
    products = {
        p.id: p for p in db.scalars(select(Product).where(Product.id.in_(list(c.products) or [0])))
    }
    by_node = {
        str(nid): [
            {
                "product_id": pid,
                "name": products[pid].name,
                "unit": products[pid].unit,
                "qty": svc.q3(q),
            }
            for pid, q in prods.items()
            if pid in products
        ]
        for nid, prods in c.by_node.items()
    }
    return jsonable_encoder(
        {
            "site_id": site.id,
            "nodes": {str(k): v for k, v in state.items()},
            "products": by_node,
            "unplaced_areas": sum(1 for a in areas if a.node_id is None),
        }
    )


# --- surveys -------------------------------------------------------------------------------------


class SurveyIn(BaseModel):
    lead_id: int | None = None
    tender_id: int | None = None
    site_id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    surveyed_on: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _one(self):
        if sum(x is not None for x in (self.lead_id, self.tender_id, self.site_id)) != 1:
            raise ValueError("A survey belongs to one lead, tender or site")
        return self


class SurveyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    surveyed_on: date | None = None
    notes: str | None = None


@router.get("")
def list_surveys(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    lead_id: int | None = None,
    tender_id: int | None = None,
    site_id: int | None = None,
) -> list[dict]:
    q = svc.visible_q(scope, principal)
    for col, v in (
        (Survey.lead_id, lead_id),
        (Survey.tender_id, tender_id),
        (Survey.site_id, site_id),
    ):
        if v is not None:
            q = q.where(col == v)
    out = []
    for s in db.scalars(q.order_by(Survey.id.desc()).limit(500)):
        out.append(
            {
                "id": s.id,
                "code": s.code,
                "title": s.title,
                "status": s.status,
                "surveyed_on": s.surveyed_on,
                "parent": _parent(db, s),
                "areas": len(s.areas),
                "treated": sum((Decimal(a.treated_area_sqm) for a in s.areas), Decimal(0)),
            }
        )
    return jsonable_encoder(out)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_survey(
    body: SurveyIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: View
) -> dict:
    scope = principal.permissions.get("survey.edit")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.edit")
    me = principal.user.id
    # all: anything; otherwise the caller's own sites (in-charge / member), tenders and leads
    if body.site_id is not None:
        site = db.get(Site, body.site_id)
        if site is None or (
            scope != "all" and not material.covers_site(db, "assigned", principal, site.id)
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    elif body.tender_id is not None:
        t = db.get(Tender, body.tender_id)
        if t is None or (
            scope != "all" and t.owner_id != me and me not in {m.user_id for m in t.members}
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tender not found")
    else:
        lead = db.get(Lead, body.lead_id)
        if lead is None or (scope != "all" and lead.owner_id != me):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    s = Survey(
        code=material.next_code(db, "SUR"), **body.model_dump(), surveyed_by=me, created_by=me
    )
    if s.surveyed_on is None:
        s.surveyed_on = date.today()
    db.add(s)
    db.flush()
    record(
        db, request, principal, "survey.create", "survey", s.id, after=body.model_dump(mode="json")
    )
    db.commit()
    return _out(db, s, principal)


@router.get("/{sid}")
def get_survey(sid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    return _out(db, svc.get_visible(db, sid, scope, principal), principal)


@router.put("/{sid}")
def update_survey(
    sid: int,
    body: SurveyUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    s = svc.get_visible(db, sid, scope, principal)
    _edit(db, s, principal)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "title" and v is None:
            continue
        setattr(s, k, v)
    record(
        db,
        request,
        principal,
        "survey.update",
        "survey",
        s.id,
        after=body.model_dump(mode="json", exclude_unset=True),
    )
    db.commit()
    return _out(db, s, principal)


@router.post("/{sid}/submit")
def submit(
    sid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    s = svc.get_visible(db, sid, scope, principal)
    _edit(db, s, principal)
    if s.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}")
    if not s.areas:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one area")
    if svc.settings(db).photo_required:
        missing = [a.name for a in s.areas if not a.photos]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Every area needs a photo first: {', '.join(missing[:6])}{' …' if len(missing) > 6 else ''}",
            )
    from app.analytics.common import now

    s.status, s.submitted_at = "submitted", now()
    record(db, request, principal, "survey.submit", "survey", s.id)
    db.commit()
    return _out(db, s, principal)


@router.post("/{sid}/approve")
def approve(
    sid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    if "survey.approve" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.approve")
    s = svc.get_visible(db, sid, scope, principal)
    if s.status != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is {s.status}; submit it first")
    from app.analytics.common import now

    s.status, s.approved_by, s.approved_at = "approved", principal.user.id, now()
    record(db, request, principal, "survey.approve", "survey", s.id)
    db.commit()
    return _out(db, s, principal)


@router.post("/{sid}/reopen")
def reopen(
    sid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    s = svc.get_visible(db, sid, scope, principal)
    if s.status == "approved" and "survey.approve" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.approve")
    if s.status == "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{s.code} is a draft")
    s.status, s.approved_by, s.approved_at = "draft", None, None
    record(db, request, principal, "survey.reopen", "survey", s.id)
    db.commit()
    return _out(db, s, principal)


# --- areas ---------------------------------------------------------------------------------------


class AreaIn(BaseModel):
    node_id: int | None = None
    tower: str | None = Field(default=None, max_length=60)
    floor_label: str | None = Field(default=None, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    area_type_id: int | None = None
    shape: Literal["rect", "polygon", "direct"] = "rect"
    length_m: Decimal | None = Field(default=None, ge=0, le=1000)
    width_m: Decimal | None = Field(default=None, ge=0, le=1000)
    polygon_m: list[list[float]] | None = None
    direct_area_sqm: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    deductions_sqm: Decimal = Field(default=Decimal(0), ge=0)
    perimeter_m: Decimal | None = Field(default=None, ge=0, le=100_000)
    perimeter_manual: bool = False
    upturn_mm: Decimal | None = Field(default=None, ge=0, le=3000)  # None: the area type's default
    wall_height_m: Decimal | None = Field(default=None, ge=0, le=100)
    sunk_depth_mm: Decimal | None = Field(default=None, ge=0, le=3000)
    count: int = Field(default=1, ge=1, le=10000)
    system_id: int | None = None
    wastage_override_percent: Decimal | None = Field(default=None, ge=0, le=100)
    method: Literal["laser", "manual", "cad", "label"] = "manual"
    accuracy_note: str | None = Field(default=None, max_length=300)
    remarks: str | None = None

    @model_validator(mode="after")
    def _size(self):
        if self.shape == "rect" and (self.length_m is None or self.width_m is None):
            raise ValueError("Give the length and the width")
        if self.shape == "polygon" and (
            not self.polygon_m
            or len(self.polygon_m) < 3
            or any(len(p) != 2 for p in self.polygon_m)
        ):
            raise ValueError("A polygon needs at least three [x, y] corners in metres")
        if self.shape == "direct" and self.direct_area_sqm is None:
            raise ValueError("Give the area")
        return self


def _apply(db, a: SurveyArea, body: AreaIn, survey: Survey) -> None:
    data = body.model_dump()
    t = db.get(AreaType, body.area_type_id) if body.area_type_id else None
    if body.area_type_id and t is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown area type")
    if body.system_id and db.get(System, body.system_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown system")
    if body.node_id is not None:
        node = db.get(SiteNode, body.node_id)
        if node is None or node.site_id != survey.site_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That place is not on this survey's site"
            )
    if data["upturn_mm"] is None:
        data["upturn_mm"] = t.default_upturn_mm if t else Decimal(0)
    for k, v in data.items():
        setattr(a, k, v)
    a.floor_no = svc.floor_number(a.floor_label)
    svc.compute(a, t)


@router.post("/{sid}/areas", status_code=status.HTTP_201_CREATED)
def add_area(
    sid: int,
    body: AreaIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    s = svc.get_visible(db, sid, scope, principal)
    _edit(db, s, principal)
    a = SurveyArea(survey_id=s.id, created_by=principal.user.id, sort_order=len(s.areas))
    _apply(db, a, body, s)
    db.add(a)
    db.flush()
    record(
        db,
        request,
        principal,
        "survey.area.create",
        "survey",
        s.id,
        after={"area": a.id, "name": a.name},
    )
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


def _area(db, aid: int, scope, principal) -> tuple[Survey, SurveyArea]:
    a = db.get(SurveyArea, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Area not found")
    return svc.get_visible(db, a.survey_id, scope, principal), a


@router.put("/areas/{aid}")
def put_area(
    aid: int,
    body: AreaIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    _apply(db, a, body, s)
    record(db, request, principal, "survey.area.update", "survey", s.id, after={"area": a.id})
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


@router.delete("/areas/{aid}")
def delete_area(
    aid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    db.delete(a)
    record(db, request, principal, "survey.area.delete", "survey", s.id, after={"area": aid})
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


COPY_FIELDS = (
    "tower",
    "floor_label",
    "node_id",
    "name",
    "area_type_id",
    "shape",
    "length_m",
    "width_m",
    "polygon_m",
    "direct_area_sqm",
    "deductions_sqm",
    "perimeter_m",
    "perimeter_manual",
    "upturn_mm",
    "wall_height_m",
    "sunk_depth_mm",
    "count",
    "system_id",
    "wastage_override_percent",
    "method",
    "accuracy_note",
    "remarks",
)


def _copy(db, a: SurveyArea, user_id, **changes) -> SurveyArea:
    b = SurveyArea(
        survey_id=a.survey_id,
        created_by=user_id,
        sort_order=a.sort_order + 1,
        **{k: getattr(a, k) for k in COPY_FIELDS},
    )
    for k, v in changes.items():
        setattr(b, k, v)
    if b.method in CAMERA_METHODS:  # a copy is not a camera measurement of its own
        b.method = "manual"
    b.floor_no = svc.floor_number(b.floor_label)
    svc.compute(b, db.get(AreaType, b.area_type_id) if b.area_type_id else None)
    db.add(b)
    return b


@router.post("/areas/{aid}/copy", status_code=status.HTTP_201_CREATED)
def copy_area(
    aid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    _copy(db, a, principal.user.id, name=f"{a.name} (copy)")
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


class RepeatIn(BaseModel):
    floor_from: int = Field(ge=-10, le=200)
    floor_to: int = Field(ge=-10, le=200)
    label: str = Field(default="Floor {n}", max_length=40)  # {n} is the floor number


@router.post("/areas/{aid}/repeat", status_code=status.HTTP_201_CREATED)
def repeat_area(
    aid: int,
    body: RepeatIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """The same area on a typical floor, repeated on floors N to M (named "Floor 2" ...); on a
    site, each copy goes on that tower's floor node with the same name when there is one."""
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    if body.floor_to < body.floor_from or body.floor_to - body.floor_from > 100:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Give a floor range of at most 100 floors"
        )
    floors: dict[str, int] = {}
    if s.site_id:
        parent = db.get(SiteNode, a.node_id) if a.node_id else None
        tower_id = parent.parent_id if parent is not None and parent.kind != "tower" else None
        for n in db.scalars(
            select(SiteNode).where(
                SiteNode.site_id == s.site_id,
                SiteNode.kind == "floor",
                SiteNode.parent_id == tower_id,
            )
        ):
            floors[n.name.strip().lower()] = n.id
    made = 0
    for n in range(body.floor_from, body.floor_to + 1):
        label = body.label.replace("{n}", str(n))
        if label == a.floor_label:
            continue
        base = (
            a.name.replace(a.floor_label or "\0", label)
            if a.floor_label and a.floor_label in a.name
            else a.name
        )
        _copy(
            db,
            a,
            principal.user.id,
            floor_label=label,
            name=base,
            node_id=floors.get(label.lower()),
        )
        made += 1
    record(
        db,
        request,
        principal,
        "survey.area.repeat",
        "survey",
        s.id,
        after={"area": a.id, "copies": made},
    )
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


class CameraIn(BaseModel):
    method: Literal["ar", "marker"]
    polygon_m: list[list[float]] = Field(min_length=3)
    wall_height_m: Decimal | None = Field(default=None, ge=0, le=100)
    accuracy_note: str | None = Field(default=None, max_length=300)


@router.post("/areas/{aid}/camera")
def camera_measure(
    aid: int,
    body: CameraIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """A camera measurement (AR or marker photo). Kept as the camera value; it becomes the size
    used only while the area has no laser or manual size."""
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    floor = svc.shoelace(body.polygon_m)
    a.camera_method, a.camera_polygon_m, a.camera_floor_sqm = (
        body.method,
        body.polygon_m,
        svc.q3(floor),
    )
    has_laser = a.method in ("laser", "manual", "cad") and (
        Decimal(a.floor_area_sqm or 0) > 0 or Decimal(a.wall_area_sqm or 0) > 0
    )
    if not has_laser:
        a.shape, a.polygon_m, a.method, a.perimeter_manual = (
            "polygon",
            body.polygon_m,
            body.method,
            False,
        )
        if body.wall_height_m is not None:
            a.wall_height_m = body.wall_height_m
        if body.accuracy_note:
            a.accuracy_note = body.accuracy_note
    svc.compute(a, db.get(AreaType, a.area_type_id) if a.area_type_id else None)
    record(
        db,
        request,
        principal,
        "survey.area.camera",
        "survey",
        s.id,
        after={"area": a.id, "method": body.method, "sqm": str(floor)},
    )
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


# --- photos --------------------------------------------------------------------------------------


@router.post("/areas/{aid}/photos", status_code=status.HTTP_201_CREATED)
async def add_photo(
    aid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
    file: Annotated[UploadFile, File()],
    overlay: Annotated[UploadFile | None, File()] = None,
    taken_at: Annotated[str | None, Form()] = None,
    lat: Annotated[Decimal | None, Form()] = None,
    lng: Annotated[Decimal | None, Form()] = None,
    gps_accuracy_m: Annotated[Decimal | None, Form()] = None,
    device: Annotated[str | None, Form(max_length=200)] = None,
    browser: Annotated[str | None, Form(max_length=300)] = None,
    tilt_beta: Annotated[Decimal | None, Form()] = None,
    tilt_gamma: Annotated[Decimal | None, Form()] = None,
    zoom: Annotated[Decimal | None, Form()] = None,
    width_px: Annotated[int | None, Form()] = None,
    height_px: Annotated[int | None, Form()] = None,
    mode: Annotated[str | None, Form(max_length=10)] = None,
    marker_found: Annotated[bool | None, Form()] = None,
    blur_score: Annotated[Decimal | None, Form()] = None,
    brightness: Annotated[Decimal | None, Form()] = None,
) -> dict:
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    rel, name = await save_upload(file, f"surveys/{s.id}/{a.id}")
    over = None
    if overlay is not None and overlay.filename:
        over, _ = await save_upload(overlay, f"surveys/{s.id}/{a.id}")
    from datetime import datetime

    when = None
    if taken_at:
        try:
            when = datetime.fromisoformat(taken_at.replace("Z", "+00:00"))
        except ValueError:
            when = None
    a.photos.append(
        SurveyPhoto(
            stored_path=rel,
            filename=name,
            overlay_path=over,
            taken_at=when,
            lat=lat,
            lng=lng,
            gps_accuracy_m=gps_accuracy_m,
            device=device,
            browser=browser,
            tilt_beta=tilt_beta,
            tilt_gamma=tilt_gamma,
            zoom=zoom,
            width_px=width_px,
            height_px=height_px,
            mode=mode,
            marker_found=marker_found,
            blur_score=blur_score,
            brightness=brightness,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "survey.photo",
        "survey",
        s.id,
        after={"area": a.id, "file": name, "mode": mode},
    )
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


@router.get("/photos/{pid}")
def photo_file(
    pid: int, db: DbSession, principal: CurrentPrincipal, scope: View, overlay: bool = False
):
    p = db.get(SurveyPhoto, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    _area(db, p.survey_area_id, scope, principal)
    return send_file(p.overlay_path if overlay and p.overlay_path else p.stored_path, p.filename)


@router.delete("/photos/{pid}")
def delete_photo(
    pid: int, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    p = db.get(SurveyPhoto, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    s, _a = _area(db, p.survey_area_id, scope, principal)
    _edit(db, s, principal)
    db.delete(p)
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


# --- AI suggestion -------------------------------------------------------------------------------


class SuggestIn(BaseModel):
    photo_id: int


@router.post("/areas/{aid}/suggest")
def suggest(
    aid: int,
    body: SuggestIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    if "survey.ai" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.ai")
    s, a = _area(db, aid, scope, principal)
    _edit(db, s, principal)
    photo = next((p for p in a.photos if p.id == body.photo_id), None)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    call = ai.suggest(db, a, photo, principal.user.id)
    record(
        db,
        request,
        principal,
        "survey.ai.suggest",
        "survey",
        s.id,
        after={
            "area": a.id,
            "call": call.id,
            "status": call.status,
            "cost_inr": str(call.cost_inr),
        },
    )
    db.commit()
    if call.status != "ok":
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The AI service did not answer; try again later"
        )
    return jsonable_encoder(
        {
            "call_id": call.id,
            "suggestion": call.suggestion,
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "cost_inr": call.cost_inr,
            "model": call.model,
        }
    )


class AcceptIn(BaseModel):
    area_type: bool = False
    system: bool = False
    notes: bool = False


@router.post("/ai/{call_id}/accept")
def accept_suggestion(
    call_id: int,
    body: AcceptIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """Take the parts of a suggestion the user accepts (sizes are never touched)."""
    call = db.get(AiCall, call_id)
    if call is None or call.survey_area_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    s, a = _area(db, call.survey_area_id, scope, principal)
    _edit(db, s, principal)
    sug = call.suggestion or {}
    if body.area_type and sug.get("area_type_id"):
        a.area_type_id = sug["area_type_id"]
    if body.system and sug.get("system_id"):
        a.system_id = sug["system_id"]
    if body.notes and sug.get("condition_notes"):
        a.remarks = ((a.remarks + "\n") if a.remarks else "") + f"AI: {sug['condition_notes']}"
    call.accepted = body.model_dump()
    svc.compute(a, db.get(AreaType, a.area_type_id) if a.area_type_id else None)
    record(
        db,
        request,
        principal,
        "survey.ai.accept",
        "survey",
        s.id,
        after={"call": call.id, **body.model_dump()},
    )
    db.commit()
    db.refresh(s)
    return _out(db, s, principal)


@router.get("/ai/usage")
def ai_usage(db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    if "survey.ai" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.ai")
    calls = db.scalars(select(AiCall).order_by(AiCall.id.desc()).limit(200)).all()
    return jsonable_encoder(
        {
            "month_spend_inr": ai.month_spend(db),
            "cap_inr": svc.settings(db).ai_monthly_cap_inr,
            "calls": [
                {
                    k: getattr(c, k)
                    for k in (
                        "id",
                        "survey_area_id",
                        "model",
                        "status",
                        "input_tokens",
                        "output_tokens",
                        "cost_inr",
                        "created_at",
                        "error",
                    )
                }
                for c in calls
            ],
        }
    )


# --- consumption and outputs ---------------------------------------------------------------------


def _floor_key(k: tuple) -> str:
    return " ".join(x for x in (k[0], k[2]) if x) or "No floor"


@router.get("/{sid}/consumption")
def consumption(sid: int, db: DbSession, principal: CurrentPrincipal, scope: View) -> dict:
    s = svc.get_visible(db, sid, scope, principal)
    c = svc.consumption(db, list(s.areas))
    total = svc.packs(db, c.products)
    info = {r["product_id"]: r for r in total}

    def lines(prods):
        return [
            {
                "product_id": pid,
                "name": info[pid]["name"],
                "unit": info[pid]["unit"],
                "qty": svc.q3(q),
            }
            for pid, q in sorted(prods.items(), key=lambda kv: info.get(kv[0], {}).get("name", ""))
            if pid in info
        ]

    return jsonable_encoder(
        {
            "products": total,
            "by_floor": [
                {"key": _floor_key(k), "tower": k[0], "floor": k[2], "products": lines(v)}
                for k, v in sorted(c.by_floor.items())
            ],
            "by_tower": [
                {"tower": k or "No tower", "products": lines(v)}
                for k, v in sorted(c.by_tower.items())
            ],
            "areas": c.areas,
            "no_system": c.no_system,
            "no_system_count": len(c.no_system),
        }
    )


class BoqIn(BaseModel):
    tender_id: int | None = None
    split_by_area_type: bool = False


def _target_tender(db, s: Survey, tender_id: int | None) -> int | None:
    if tender_id:
        return tender_id
    if s.tender_id:
        return s.tender_id
    if s.lead_id:
        return db.scalar(select(Lead.tender_id).where(Lead.id == s.lead_id))
    if s.site_id:
        return db.scalar(select(Site.tender_id).where(Site.id == s.site_id))
    return None


@router.post("/{sid}/boq")
def create_boq_lines(
    sid: int, body: BoqIn, request: Request, db: DbSession, principal: CurrentPrincipal, scope: View
) -> dict:
    """One BOQ line per system (and per area type when split) with the summed treated sqm,
    priced by the tender's Suggest; each line remembers the survey areas it came from."""
    s = svc.get_visible(db, sid, scope, principal)
    if principal.permissions.get("survey.edit") is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: survey.edit")
    tid = _target_tender(db, s, body.tender_id)
    if tid is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the tender for the BOQ lines"
        )
    view, edit = principal.permissions.get("tender.view"), principal.permissions.get("tender.edit")
    if view is None or edit is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: tender.edit")
    tender = tender_visible(db, tid, view, principal)
    check_edit(tender, edit, principal)
    types = {t.id: t for t in db.scalars(select(AreaType))}
    systems = {x.id: x for x in db.scalars(select(System))}
    groups: dict[tuple, list[SurveyArea]] = {}
    for a in s.areas:
        sys_id = svc.area_system_id(a, types.get(a.area_type_id))
        if sys_id is None or not Decimal(a.treated_area_sqm):
            continue
        key = (sys_id, a.area_type_id if body.split_by_area_type else None)
        groups.setdefault(key, []).append(a)
    if not groups:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No area has a system yet")
    order = (
        db.scalar(select(func.max(BoqLine.sort_order)).where(BoqLine.tender_id == tender.id)) or 0
    ) + 10
    made = []
    for (sys_id, type_id), areas in sorted(
        groups.items(), key=lambda kv: (systems[kv[0][0]].name, kv[0][1] or 0)
    ):
        where = (
            types[type_id].name
            if type_id
            else ", ".join(
                sorted({types[a.area_type_id].name for a in areas if a.area_type_id in types})
            )
            or "survey areas"
        )
        qty = svc.q3(sum((Decimal(a.treated_area_sqm) for a in areas), Decimal(0)))
        line = BoqLine(
            tender_id=tender.id,
            sort_order=order,
            description=f"{systems[sys_id].name} to {where} (survey {s.code})",
            unit="sqm",
            unit_raw="sqm",
            qty=qty,
            system_id=sys_id,
            status="unpriced",
            created_by=principal.user.id,
        )
        db.add(line)
        db.flush()
        for a in areas:
            db.add(SurveyBoqLink(boq_line_id=line.id, survey_area_id=a.id))
        made.append(line)
        order += 10
    result = pricing.suggest(db, tender, lines=made, user_id=principal.user.id)
    for line, (sys_id, _t) in zip(
        made, sorted(groups, key=lambda k: (systems[k[0]].name, k[1] or 0)), strict=True
    ):
        if line.system_id is None:  # left unpriced: still remember which system it is for
            line.system_id = sys_id
    record(
        db,
        request,
        principal,
        "survey.boq",
        "survey",
        s.id,
        after={"tender": tender.code, "lines": [ln.id for ln in made]},
    )
    db.commit()
    return {
        "tender_id": tender.id,
        "tender_code": tender.code,
        "lines": len(made),
        "suggested": result.suggested,
        "left_unpriced": result.left_unpriced,
    }


class IndentFromSurvey(BaseModel):
    site_id: int | None = None
    floors: list[str] | None = None  # floor keys ("T1 Floor 2"); none: the whole survey
    required_by: date | None = None


@router.post("/{sid}/indent", status_code=status.HTTP_201_CREATED)
def create_indent(
    sid: int,
    body: IndentFromSurvey,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: View,
) -> dict:
    """A draft indent with the product totals (whole packs) of the chosen floors."""
    s = svc.get_visible(db, sid, scope, principal)
    site_id = (
        body.site_id
        or s.site_id
        or (
            db.scalar(select(Site.id).where(Site.tender_id == s.tender_id)) if s.tender_id else None
        )
    )
    if site_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the site for the indent")
    iscope = principal.permissions.get("indent.create")
    site = db.get(Site, site_id)
    if (
        iscope is None
        or site is None
        or not material.covers_site(db, iscope, principal, site.id, site.created_by)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: indent.create on that site"
        )
    areas = [
        a
        for a in s.areas
        if body.floors is None
        or (" ".join(x for x in (a.tower, a.floor_label) if x) or "No floor") in body.floors
    ]
    c = svc.consumption(db, areas)
    rows = [r for r in svc.packs(db, c.products) if r["qty"] > 0]
    if not rows:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No product quantities on those floors (pick systems first)",
        )
    store = material.site_store(db, site, principal.user.id)
    floors = ", ".join(body.floors) if body.floors else "all floors"
    ind = Indent(
        code=material.next_code(db, "IND"),
        site_id=site.id,
        store_id=store.id,
        required_by=body.required_by,
        status="draft",
        remark=f"From survey {s.code} ({floors})",
        created_by=principal.user.id,
    )
    for r in rows:
        qty = r["pack_qty"] if r["pack_qty"] is not None else r["qty"]
        ind.lines.append(
            IndentLine(
                product_id=r["product_id"],
                qty=qty,
                unit=r["unit"],
                base_qty=qty,
                created_by=principal.user.id,
                remark=f"{r['packs']} × {r['pack_size']:g} {r['unit']}" if r["packs"] else None,
            )
        )
    db.add(ind)
    db.flush()
    record(
        db,
        request,
        principal,
        "survey.indent",
        "survey",
        s.id,
        after={"indent": ind.code, "floors": body.floors},
    )
    db.commit()
    return {"indent_id": ind.id, "code": ind.code, "lines": len(rows)}


@router.get("/{sid}/pdf")
def pdf(
    sid: int, db: DbSession, principal: CurrentPrincipal, scope: View, include_rates: bool = False
):
    s = svc.get_visible(db, sid, scope, principal)
    rates = include_rates and "tender.margin" in principal.permissions
    p = _parent(db, s)
    return pdf_response(
        survey_pdf.survey_pdf(db, s, f"{p['kind']} {p['code']} {p['name']}", rates),
        f"Survey-{s.code}",
    )


@router.get("/{sid}/xlsx")
def xlsx(sid: int, db: DbSession, principal: CurrentPrincipal, scope: View):
    from app.analytics.reports import xlsx_book

    s = svc.get_visible(db, sid, scope, principal)
    types = {t.id: t.name for t in db.scalars(select(AreaType))}
    systems = {x.id: x.name for x in db.scalars(select(System))}
    area_rows = [
        {
            "tower": a.tower,
            "floor": a.floor_label,
            "name": a.name,
            "type": types.get(a.area_type_id),
            "shape": a.shape,
            "length_m": a.length_m,
            "width_m": a.width_m,
            "direct": a.direct_area_sqm,
            "deductions": a.deductions_sqm,
            "perimeter": a.perimeter_m,
            "upturn_mm": a.upturn_mm,
            "wall_h": a.wall_height_m,
            "sunk_mm": a.sunk_depth_mm,
            "count": a.count,
            "floor_sqm": a.floor_area_sqm,
            "treated": a.treated_area_sqm,
            "method": a.method,
            "camera_sqm": a.camera_floor_sqm,
            "system": systems.get(a.system_id),
            "remarks": a.remarks,
        }
        for a in s.areas
    ]
    cols = [
        {"key": k, "label": label}
        for k, label in (
            ("tower", "Tower"),
            ("floor", "Floor"),
            ("name", "Area"),
            ("type", "Area type"),
            ("shape", "Shape"),
            ("length_m", "Length m"),
            ("width_m", "Width m"),
            ("direct", "Area typed sqm"),
            ("deductions", "Deductions sqm"),
            ("perimeter", "Perimeter m"),
            ("upturn_mm", "Upturn mm"),
            ("wall_h", "Wall height m"),
            ("sunk_mm", "Sunk depth mm"),
            ("count", "Count"),
            ("floor_sqm", "Floor sqm (each)"),
            ("treated", "Treated sqm (x count)"),
            ("method", "Method"),
            ("camera_sqm", "Camera sqm"),
            ("system", "System (own)"),
            ("remarks", "Remarks"),
        )
    ]
    c = svc.consumption(db, list(s.areas))
    total = svc.packs(db, c.products)
    info = {r["product_id"]: r for r in total}
    floor_rows = [
        {
            "floor": _floor_key(k),
            "product": info[pid]["name"],
            "unit": info[pid]["unit"],
            "qty": svc.q3(q),
        }
        for k, prods in sorted(c.by_floor.items())
        for pid, q in prods.items()
        if pid in info
    ]
    pcols = [
        {"key": k, "label": label}
        for k, label in (
            ("name", "Product"),
            ("unit", "Unit"),
            ("qty", "Quantity"),
            ("packs", "Packs"),
            ("pack_size", "Pack size"),
            ("pack_unit", "Pack"),
            ("pack_qty", "Quantity in packs"),
        )
    ]
    fcols = [
        {"key": k, "label": label}
        for k, label in (
            ("floor", "Floor"),
            ("product", "Product"),
            ("unit", "Unit"),
            ("qty", "Quantity"),
        )
    ]
    data = xlsx_book(
        [("Areas", cols, area_rows), ("Products", pcols, total), ("By floor", fcols, floor_rows)],
        f"Survey {s.code}: {s.title}. Packs rounded up on the survey total only.",
    )
    return Response(
        data,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="Survey-{s.code}.xlsx"'},
    )


__all__ = ["uuid"]
