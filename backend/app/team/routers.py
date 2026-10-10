# ruff: noqa: E501  (endpoint texts read better unwrapped)
"""Team roles and workspaces: My work, per-person grants, enquiry allocation, decisions on won
jobs, site visits, the site status board and allocation list, material plans, the measurement
book, client bill tracking, the labour bill check, negotiations, the closure scorecard, tender
bidders and the send checklist."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.auth.deps import CurrentPrincipal, require_any_permission, require_permission
from app.db import DbSession
from app.execution.common import names, pdf_response, record, save_upload, send_file
from app.material import service as material
from app.models import User
from app.sites.models import Site
from app.team import mywork
from app.team import service as team
from app.team.models import (
    BOARD_COLUMNS,
    GRANTABLE,
    MEASURE_SOURCES,
    JobAssignment,
    Measurement,
    Negotiation,
    SiteVisit,
    TenderBidder,
    UserGrant,
    board_label,
)
from app.timefmt import label

router = APIRouter(prefix="/api/team", tags=["team"])


def _scope_sites(db, scope: str, principal) -> list[int] | None:
    return None if scope == "all" else sorted(material.site_ids(db, principal))


def _site(db, site_id: int, scope: str, principal) -> Site:
    site = db.get(Site, site_id)
    allowed = _scope_sites(db, scope, principal)
    if site is None or (allowed is not None and site.id not in allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


# --- My work -------------------------------------------------------------------------------------


@router.get("/my-work")
def my_work(db: DbSession, principal: CurrentPrincipal) -> dict:
    return jsonable_encoder(mywork.build(db, principal))


# --- settings and grants -------------------------------------------------------------------------


class SettingsIn(BaseModel):
    billing_day: int | None = Field(None, ge=1, le=28)
    award_followup_days: int | None = Field(None, ge=7, le=365)
    closure_target_percent: Decimal | None = Field(None, ge=0, le=100)
    allocation_recipients: list[uuid.UUID] | None = None


def _settings_out(db) -> dict:
    s = team.settings(db)
    return jsonable_encoder(
        {
            "billing_day": s.billing_day,
            "award_followup_days": s.award_followup_days,
            "closure_target_percent": s.closure_target_percent,
            "allocation_recipients": s.allocation_recipients or [],
            "allocation_sent_at": s.allocation_sent_at,
        }
    )


@router.get("/settings")
def get_settings(db: DbSession, _: CurrentPrincipal) -> dict:
    return _settings_out(db)


@router.put("/settings")
def put_settings(
    body: SettingsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_any_permission("planning.edit", "settings.company"))],
) -> dict:
    s = team.settings(db)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(s, k, v)
    record(
        db, request, principal, "team.settings", "team_settings", 1, after=jsonable_encoder(data)
    )
    db.commit()
    return _settings_out(db)


@router.get("/grants")
def list_grants(
    db: DbSession, _: Annotated[str, Depends(require_permission("grants.manage"))]
) -> list[dict]:
    rows = db.execute(
        select(UserGrant, User.full_name).join(User, User.id == UserGrant.user_id)
    ).all()
    return jsonable_encoder(
        [
            {
                "user_id": g.user_id,
                "name": n,
                "permission": g.permission_code,
                "granted_at": g.granted_at,
            }
            for g, n in rows
        ]
    )


class GrantsIn(BaseModel):
    codes: list[str]


@router.put("/users/{uid}/grants")
def set_grants(
    uid: uuid.UUID,
    body: GrantsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("grants.manage"))],
) -> dict:
    """The director allows one person costs and margins (tender.margin) or deciding won jobs
    (jobs.assign), on top of their roles."""
    if db.get(User, uid) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    bad = sorted(set(body.codes) - set(GRANTABLE))
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Cannot be granted per person: {', '.join(bad)}"
        )
    before = sorted(db.scalars(select(UserGrant.permission_code).where(UserGrant.user_id == uid)))
    db.execute(delete(UserGrant).where(UserGrant.user_id == uid))
    for code in sorted(set(body.codes)):
        db.add(UserGrant(user_id=uid, permission_code=code, granted_by=principal.user.id))
    record(
        db,
        request,
        principal,
        "user.grants",
        "user",
        str(uid),
        before={"grants": before},
        after={"grants": sorted(set(body.codes))},
    )
    db.commit()
    return {"user_id": str(uid), "codes": sorted(set(body.codes))}


# --- enquiries: the unassigned queue -------------------------------------------------------------

Allocate = Annotated[str, Depends(require_permission("leads.allocate"))]


class EnquiryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=30)
    company: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=100)
    requirement: str | None = None


@router.post("/enquiries", status_code=status.HTTP_201_CREATED)
def create_enquiry(
    body: EnquiryIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Allocate
) -> dict:
    """An enquiry that came to planning directly: a lead with no salesperson yet."""
    from app.crm.models import Lead, LeadActivity  # noqa: PLC0415
    from app.crm.routers import next_code  # noqa: PLC0415

    lead = Lead(code=next_code(db), created_by=principal.user.id, owner_id=None, status="new")
    lead.contact_name = body.name
    for k in ("phone", "company", "city", "requirement"):
        if getattr(body, k) is not None:
            setattr(lead, k, getattr(body, k))
    db.add(lead)
    db.flush()
    db.add(
        LeadActivity(
            lead_id=lead.id,
            type="note",
            text="Enquiry received by planning (not allocated)",
            by=principal.user.id,
        )
    )
    record(db, request, principal, "lead.create", "lead", lead.id, after={"unassigned": True})
    db.commit()
    return {"id": lead.id, "code": lead.code}


@router.get("/enquiries")
def unassigned(db: DbSession, _: Allocate) -> list[dict]:
    from app.crm.models import Lead  # noqa: PLC0415

    rows = db.scalars(
        select(Lead)
        .where(
            Lead.owner_id.is_(None),
            Lead.status.notin_(("won", "lost", "junk")),
            Lead.is_demo.is_(False),
        )
        .order_by(Lead.id)
    ).all()
    return jsonable_encoder(
        [
            {
                "id": x.id,
                "code": x.code,
                "name": x.contact_name,
                "company": x.company,
                "city": x.city,
                "phone": x.phone,
                "requirement": x.requirement,
                "created_at": x.created_at,
                "age_days": mywork._age(x.created_at),
            }
            for x in rows
        ]
    )


class AllocateIn(BaseModel):
    owner_id: uuid.UUID


@router.post("/enquiries/{lead_id}/allocate")
def allocate(
    lead_id: int,
    body: AllocateIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Allocate,
) -> dict:
    from app.crm.models import Lead, LeadActivity  # noqa: PLC0415
    from app.portal.service import notify  # noqa: PLC0415

    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enquiry not found")
    owner = db.get(User, body.owner_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick an active salesperson")
    lead.owner_id = owner.id
    db.add(
        LeadActivity(
            lead_id=lead.id,
            type="note",
            text=f"Allocated to {owner.full_name} by planning",
            by=principal.user.id,
        )
    )
    notify(
        db,
        [owner.id],
        "lead_allocated",
        f"New enquiry {lead.code} {lead.contact_name}: contact the client",
        link=f"/leads/{lead.id}",
    )
    record(
        db, request, principal, "lead.allocate", "lead", lead.id, after={"owner": owner.full_name}
    )
    db.commit()
    return {"id": lead.id, "owner": owner.full_name}


# --- won jobs: who handles them ------------------------------------------------------------------


def _can_assign(principal) -> None:
    if "jobs.assign" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The director decides who handles a won job")


def _assignment_out(db, a: JobAssignment) -> dict:
    who = names(db, [a.salesperson_id, a.engineer_id, a.decided_by])
    site = db.get(Site, a.site_id) if a.site_id else None
    return jsonable_encoder(
        {
            "id": a.id,
            "title": a.title,
            "status": a.status,
            "quotation_id": a.quotation_id,
            "tender_id": a.tender_id,
            "site_id": a.site_id,
            "site": f"{site.code} · {site.name}" if site else None,
            "salesperson_id": a.salesperson_id,
            "salesperson": who.get(a.salesperson_id),
            "engineer_id": a.engineer_id,
            "engineer": who.get(a.engineer_id),
            "decided_by": who.get(a.decided_by),
            "decided_at": a.decided_at,
            "first_visit_logged": a.first_visit_id is not None,
            "created_at": a.created_at,
        }
    )


@router.get("/assignments")
def assignments(
    db: DbSession,
    _: Annotated[str, Depends(require_any_permission("jobs.assign", "planning.view"))],
    state: str = "pending",
) -> list[dict]:
    q = select(JobAssignment).order_by(JobAssignment.id.desc())
    if state in ("pending", "done"):
        q = q.where(JobAssignment.status == state)
    return [_assignment_out(db, a) for a in db.scalars(q.limit(300))]


@router.get("/assignments/{aid}")
def assignment(
    aid: int,
    db: DbSession,
    _: Annotated[str, Depends(require_any_permission("jobs.assign", "planning.view"))],
) -> dict:
    a = db.get(JobAssignment, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return _assignment_out(db, a)


class DecideIn(BaseModel):
    salesperson_id: uuid.UUID
    engineer_id: uuid.UUID


@router.post("/assignments/{aid}/decide")
def decide(
    aid: int, body: DecideIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    _can_assign(principal)
    a = db.get(JobAssignment, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    team.decide(db, a, body.salesperson_id, body.engineer_id, principal.user.id)
    record(
        db,
        request,
        principal,
        "job.assign",
        "job_assignment",
        a.id,
        after={
            "site": a.site_id,
            "salesperson": str(a.salesperson_id),
            "engineer": str(a.engineer_id),
        },
    )
    db.commit()
    return _assignment_out(db, a)


@router.get("/people")
def people(db: DbSession, _: CurrentPrincipal, role: str | None = None) -> list[dict]:
    """Active staff (optionally with one role) for the pickers."""
    from app.models import Role, UserRole  # noqa: PLC0415

    q = select(User).where(User.is_active).order_by(User.full_name)
    if role:
        q = q.where(
            User.id.in_(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.code == role)
            )
        )
    return [{"id": str(u.id), "name": u.full_name, "job_title": u.job_title} for u in db.scalars(q)]


# --- site visits ---------------------------------------------------------------------------------

VisitScope = Annotated[str, Depends(require_permission("sitevisit.log"))]


def _visit_out(db, v: SiteVisit) -> dict:
    who = names(db, [v.user_id])
    return jsonable_encoder(
        {
            "id": v.id,
            "site_id": v.site_id,
            "lead_id": v.lead_id,
            "by": who.get(v.user_id),
            "visited_on": v.visited_on,
            "notes": v.notes,
            "gps": {"lat": v.lat, "lng": v.lng, "accuracy_m": v.accuracy_m}
            if v.lat is not None
            else None,
            "photos": len(v.photos or []),
            "first_after_win": v.first_after_win,
        }
    )


@router.post("/site-visits", status_code=status.HTTP_201_CREATED)
async def log_visit(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: VisitScope,
    notes: Annotated[str, Form(min_length=3)],
    visited_on: Annotated[date | None, Form()] = None,
    site_id: Annotated[int | None, Form()] = None,
    lead_id: Annotated[int | None, Form()] = None,
    lat: Annotated[Decimal | None, Form()] = None,
    lng: Annotated[Decimal | None, Form()] = None,
    accuracy: Annotated[Decimal | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    if not site_id and not lead_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A visit is to a site or a lead")
    if site_id:
        site = db.get(Site, site_id)
        if site is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
        if scope != "all" and site_id not in material.site_ids(db, principal):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your site")
    paths = []
    for f in photos or []:
        rel, _name = await save_upload(f, f"visits/{site_id or 'lead'}")
        paths.append(rel)
    v = SiteVisit(
        site_id=site_id,
        lead_id=lead_id,
        user_id=principal.user.id,
        visited_on=visited_on or mywork.today(),
        notes=notes.strip(),
        lat=lat,
        lng=lng,
        accuracy_m=accuracy,
        photos=paths,
    )
    db.add(v)
    db.flush()
    if site_id:
        a = db.scalar(
            select(JobAssignment).where(
                JobAssignment.site_id == site_id,
                JobAssignment.salesperson_id == principal.user.id,
                JobAssignment.status == "done",
                JobAssignment.first_visit_id.is_(None),
            )
        )
        if a is not None:
            a.first_visit_id, v.first_after_win = v.id, True
    record(
        db,
        request,
        principal,
        "site_visit.log",
        "site_visit",
        v.id,
        after={"site": site_id, "lead": lead_id},
    )
    db.commit()
    return _visit_out(db, v)


@router.get("/site-visits")
def visits(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: VisitScope,
    site_id: int | None = None,
    lead_id: int | None = None,
) -> list[dict]:
    q = select(SiteVisit).order_by(SiteVisit.visited_on.desc(), SiteVisit.id.desc())
    if site_id:
        q = q.where(SiteVisit.site_id == site_id)
    if lead_id:
        q = q.where(SiteVisit.lead_id == lead_id)
    if scope == "own":
        q = q.where(SiteVisit.user_id == principal.user.id)
    return [_visit_out(db, v) for v in db.scalars(q.limit(200))]


@router.get("/site-visits/{vid}/photos/{n}")
def visit_photo(vid: int, n: int, db: DbSession, _: VisitScope):
    v = db.get(SiteVisit, vid)
    if v is None or n >= len(v.photos or []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return send_file(v.photos[n])


# --- the site status board -----------------------------------------------------------------------

BoardView = Annotated[str, Depends(require_any_permission("planning.view", "site.view"))]


@router.get("/board")
def board(db: DbSession, principal: CurrentPrincipal, scope: BoardView) -> dict:
    allowed = (
        None
        if "planning.view" in principal.permissions
        else _scope_sites(db, principal.permissions.get("site.view", "own"), principal)
    )
    rows = team.board_rows(db, allowed)
    return jsonable_encoder(
        {
            "columns": [{"key": c, "label": board_label(c)} for c in BOARD_COLUMNS],
            "sites": rows,
            "missing": [
                r for r in rows if r["column"] is None and r["status"] in ("planned", "active")
            ],
        }
    )


class MoveIn(BaseModel):
    column: str


@router.post("/board/{site_id}")
def move(
    site_id: int, body: MoveIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Planning moves any site; a site engineer moves their own (from the phone)."""
    if body.column not in BOARD_COLUMNS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown column")
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    if "planning.edit" not in principal.permissions and not material.covers_site(
        db, principal.permissions.get("site.update"), principal, site.id, site.created_by
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only planning or the site's engineer moves it"
        )
    before = site.board_status
    site.board_status, site.board_updated_at, site.board_updated_by = (
        body.column,
        team.now(),
        principal.user.id,
    )
    record(
        db,
        request,
        principal,
        "site.board",
        "site",
        site.id,
        before={"column": before},
        after={"column": body.column},
    )
    db.commit()
    return {"id": site.id, "column": site.board_status}


def _allocation_rows(db) -> list[list]:
    rows = []
    for r in team.board_rows(db, None):
        if r["column"] is None:
            continue
        rows.append(
            [
                board_label(r["column"]),
                r["code"],
                r["name"],
                r["salesperson"] or "",
                r["site_engineer"] or "",
                r["supervisor"] or "",
                label(r["last_update"], "%d %b %Y") if r["last_update"] else "",
            ]
        )
    order = {board_label(c): i for i, c in enumerate(BOARD_COLUMNS)}
    return sorted(rows, key=lambda x: (order.get(x[0], 9), x[1]))


ALLOC_HEADS = [
    "Status",
    "Site",
    "Name",
    "Salesperson",
    "Site engineer",
    "Supervisor",
    "Last update",
]


@router.get("/allocation-list")
def allocation_list(
    db: DbSession,
    _: Annotated[str, Depends(require_permission("planning.view"))],
    format: str = "pdf",
):
    rows = _allocation_rows(db)
    if format == "xlsx":
        from app.sitecontrol.routers import _book  # noqa: PLC0415

        return _book("site-allocation-list", [("Site allocation", ALLOC_HEADS, rows)])
    from html import escape  # noqa: PLC0415

    from weasyprint import HTML  # noqa: PLC0415

    from app.tenders.export import company  # noqa: PLC0415

    c = company(db)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r) + "</tr>" for r in rows
    )
    html = f"""<html><head><style>
@page {{ size: A4 landscape; margin: 12mm; @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; }} }}
body {{ font-family: 'DejaVu Sans', sans-serif; font-size: 9pt; }}
h1 {{ font-size: 14pt; margin: 0 0 2mm; color: #0F6B5C; }}
table {{ width: 100%; border-collapse: collapse; }} th, td {{ border: 1px solid #bbb; padding: 3px 5px; text-align: left; }}
th {{ background: #e8f0ee; }}
</style></head><body><h1>{escape(c.name or "EESPL")}: site allocation list</h1>
<p>As of {label(team.now())}</p>
<table><thead><tr>{"".join(f"<th>{h}</th>" for h in ALLOC_HEADS)}</tr></thead><tbody>{body}</tbody></table></body></html>"""
    return pdf_response(
        HTML(string=html).write_pdf(), f"site-allocation-list-{date.today():%Y%m%d}"
    )


@router.post("/allocation-list/send")
def send_allocation(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("planning.edit"))],
) -> dict:
    """To the recipients in the settings, through the in-app outbox (nothing is emailed)."""
    from app.portal.service import notify  # noqa: PLC0415

    s = team.settings(db)
    if not s.allocation_recipients:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Choose who receives the allocation list (settings)"
        )
    n = notify(
        db,
        s.allocation_recipients,
        "allocation_list",
        f"Site allocation list of {label(team.now(), '%d %b %Y')}",
        link="/planning/board?download=1",
    )
    s.allocation_sent_at = team.now()
    record(
        db, request, principal, "allocation_list.send", "team_settings", 1, after={"recipients": n}
    )
    db.commit()
    return {"sent_to": n}


# --- material plan -------------------------------------------------------------------------------


@router.get("/material-plan/{site_id}")
def material_plan(
    site_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_any_permission("planning.view", "indent.view"))],
    by: str = "stage",
) -> dict:
    site = _site(
        db, site_id, "all" if "planning.view" in principal.permissions else scope, principal
    )
    return jsonable_encoder(team.material_plan(db, site, "month" if by == "month" else "stage"))


class PlanIndentIn(BaseModel):
    lines: list[dict] = Field(min_length=1)  # [{product_id, qty}]
    submit: bool = True


@router.post("/material-plan/{site_id}/indent", status_code=status.HTTP_201_CREATED)
def plan_indent(
    site_id: int,
    body: PlanIndentIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("indent.create"))],
) -> dict:
    """ "Create indent" from the plan: the products and quantities picked there."""
    from app.material.routers import create_indent  # noqa: PLC0415
    from app.material.schemas import IndentIn, IndentLineIn  # noqa: PLC0415

    lines = [
        IndentLineIn(product_id=int(x["product_id"]), qty=Decimal(str(x["qty"])))
        for x in body.lines
        if Decimal(str(x.get("qty") or 0)) > 0
    ]
    if not lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to indent")
    out = create_indent(
        IndentIn(site_id=site_id, lines=lines, submit=body.submit, remark="From the material plan"),
        request,
        db,
        principal,
        scope,
    )
    return {"id": out.id, "code": out.code}


# --- the measurement book ------------------------------------------------------------------------

MeasureView = Annotated[str, Depends(require_permission("measurement.view"))]
MeasureEdit = Annotated[str, Depends(require_permission("measurement.edit"))]


def _measure_out(db, m: Measurement) -> dict:
    from app.sitecontrol.service import node_label  # noqa: PLC0415
    from app.sites.models import SiteNode  # noqa: PLC0415

    who = names(db, [m.measured_by])
    return jsonable_encoder(
        {
            "id": m.id,
            "site_id": m.site_id,
            "contract_line_id": m.contract_line_id,
            "place": node_label(db, db.get(SiteNode, m.node_id)) if m.node_id else None,
            "description": m.description,
            "qty": m.qty,
            "unit": m.unit,
            "source": m.source,
            "measured_on": m.measured_on,
            "measured_by": who.get(m.measured_by),
            "note": m.note,
        }
    )


@router.get("/measurements")
def measurements(
    site_id: int, db: DbSession, principal: CurrentPrincipal, scope: MeasureView
) -> dict:
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import ClientContract, ContractLine  # noqa: PLC0415

    site = _site(db, site_id, scope, principal)
    rows = [
        _measure_out(db, m)
        for m in db.scalars(
            select(Measurement)
            .where(Measurement.site_id == site.id)
            .order_by(Measurement.measured_on.desc(), Measurement.id.desc())
        )
    ]
    lines = []
    c = db.scalar(select(ClientContract).where(ClientContract.site_id == site.id))
    if c is not None:
        for cl in db.scalars(
            select(ContractLine).where(ContractLine.contract_id == c.id).order_by(ContractLine.id)
        ):
            measured = team.book_total(db, cl.id)
            billed = fsvc.billed_before(db, cl.id, None)
            lines.append(
                {
                    "id": cl.id,
                    "item_no": cl.item_no,
                    "description": cl.description[:120],
                    "unit": cl.unit,
                    "contract_qty": cl.qty,
                    "measured": measured,
                    "billed": billed,
                    "to_bill": max(Decimal(0), measured - billed),
                }
            )
    return jsonable_encoder(
        {"site_id": site.id, "entries": rows, "lines": lines, "sources": MEASURE_SOURCES}
    )


class MeasureIn(BaseModel):
    site_id: int
    contract_line_id: int
    qty: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    source: str
    measured_on: date | None = None
    measured_by: uuid.UUID | None = None
    node_id: int | None = None
    survey_area_id: int | None = None
    note: str | None = None


@router.post("/measurements", status_code=status.HTTP_201_CREATED)
def add_measurement(
    body: MeasureIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: MeasureEdit,
) -> dict:
    from app.finance.models import ClientContract, ContractLine  # noqa: PLC0415

    site = _site(db, body.site_id, scope, principal)
    if body.source not in MEASURE_SOURCES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown source")
    cl = db.get(ContractLine, body.contract_line_id)
    c = db.get(ClientContract, cl.contract_id) if cl else None
    if cl is None or c is None or c.site_id != site.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That contract line is not on this site"
        )
    m = Measurement(
        site_id=site.id,
        contract_line_id=cl.id,
        node_id=body.node_id,
        survey_area_id=body.survey_area_id,
        description=cl.description[:500],
        qty=body.qty,
        unit=cl.unit,
        source=body.source,
        measured_on=body.measured_on or mywork.today(),
        measured_by=body.measured_by or principal.user.id,
        note=body.note,
        created_by=principal.user.id,
    )
    db.add(m)
    db.flush()
    record(
        db,
        request,
        principal,
        "measurement.add",
        "measurement",
        m.id,
        after={"line": cl.id, "qty": str(body.qty), "source": body.source},
    )
    db.commit()
    return _measure_out(db, m)


# --- client bill tracking ------------------------------------------------------------------------


@router.get("/bill-tracking")
def bill_tracking(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("billing.view"))],
    site_id: int | None = None,
) -> list[dict]:
    """Sent, certified quantity and amount, the difference from billed with its reason, paid.
    Selling amounts only (no costs): the salesperson sees their clients' bills."""
    from app.finance.models import RaBill, RaBillLine, TaxInvoice  # noqa: PLC0415

    allowed = _scope_sites(db, scope, principal)
    q = select(RaBill).where(RaBill.status != "cancelled").order_by(RaBill.id.desc())
    if allowed is not None:
        q = q.where(RaBill.site_id.in_(allowed or [-1]))
    if site_id:
        q = q.where(RaBill.site_id == site_id)
    out = []
    for b in db.scalars(q.limit(300)):
        site = db.get(Site, b.site_id)
        lines = db.scalars(select(RaBillLine).where(RaBillLine.ra_bill_id == b.id)).all()
        billed = sum((Decimal(ln.qty) * Decimal(ln.rate) for ln in lines), Decimal(0))
        certified = (
            sum(
                (Decimal(ln.certified_amount) for ln in lines if ln.certified_amount is not None),
                Decimal(0),
            )
            if any(ln.certified_amount is not None for ln in lines)
            else None
        )
        paid = None
        inv = db.scalar(
            select(TaxInvoice).where(
                TaxInvoice.ra_bill_id == b.id, TaxInvoice.status != "cancelled"
            )
        )
        if inv is not None:
            from app.finance import service as fsvc  # noqa: PLC0415

            paid = Decimal(inv.total) - fsvc.outstanding(db, inv)
        out.append(
            {
                "id": b.id,
                "code": b.code,
                "site_id": b.site_id,
                "site": f"{site.code} · {site.name}",
                "status": b.status,
                "sent_at": b.submitted_at,
                "billed": billed.quantize(Decimal("0.01")),
                "certified": certified.quantize(Decimal("0.01")) if certified is not None else None,
                "difference": (certified - billed).quantize(Decimal("0.01"))
                if certified is not None
                else None,
                "paid": paid.quantize(Decimal("0.01")) if paid is not None else None,
                "lines": [
                    {
                        "id": ln.id,
                        "qty": ln.qty,
                        "certified_qty": ln.certified_qty,
                        "rate": ln.rate,
                        "reason": ln.client_diff_reason,
                    }
                    for ln in lines
                    if ln.certified_qty is not None and Decimal(ln.certified_qty) != Decimal(ln.qty)
                ],
            }
        )
    return jsonable_encoder(out)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.put("/ra-lines/{line_id}/reason")
def diff_reason(
    line_id: int,
    body: ReasonIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("billing.edit"))],
) -> dict:
    from app.finance.models import RaBillLine  # noqa: PLC0415

    ln = db.get(RaBillLine, line_id)
    if ln is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    ln.client_diff_reason = body.reason
    record(
        db,
        request,
        principal,
        "ra_line.diff_reason",
        "ra_bill_line",
        ln.id,
        after={"reason": body.reason},
    )
    db.commit()
    return {"id": ln.id, "reason": ln.client_diff_reason}


# --- the labour bill check -----------------------------------------------------------------------


@router.get("/labour-check")
def labour_check(
    db: DbSession, _: Annotated[str, Depends(require_permission("labourcheck.check"))]
) -> list[dict]:
    from app.execution.models import WorkOrder  # noqa: PLC0415
    from app.finance.models import SubconBill  # noqa: PLC0415

    out = []
    for b in db.scalars(
        select(SubconBill).where(SubconBill.status == "draft").order_by(SubconBill.id)
    ):
        wo = db.get(WorkOrder, b.wo_id)
        site = db.get(Site, wo.site_id)
        who = names(db, [b.billing_checked_by])
        out.append(
            {
                "id": b.id,
                "number": b.number,
                "wo": wo.code,
                "site": f"{site.code} · {site.name}",
                "contractor": wo.subcontractor.name,
                "gross": b.gross,
                "productivity_status": b.productivity_status,
                "productivity": b.productivity,
                "overridden": b.productivity_override_at is not None,
                "checked_by": who.get(b.billing_checked_by),
                "checked_at": b.billing_checked_at,
            }
        )
    return jsonable_encoder(out)


@router.post("/labour-check/{bill_id}")
def mark_checked(
    bill_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: Annotated[str, Depends(require_permission("labourcheck.check"))],
) -> dict:
    """Billing checked the bill against the work done; a "productivity low" flag stays for the
    director to decide."""
    from app.finance.models import SubconBill  # noqa: PLC0415

    b = db.get(SubconBill, bill_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    b.billing_checked_by, b.billing_checked_at = principal.user.id, team.now()
    record(
        db,
        request,
        principal,
        "subcon_bill.billing_check",
        "subcon_bill",
        b.id,
        after={"productivity": b.productivity_status},
    )
    db.commit()
    return {
        "id": b.id,
        "checked": True,
        "waiting_for_director": b.productivity_status == "low"
        and b.productivity_override_at is None,
    }


# --- negotiations --------------------------------------------------------------------------------


def _neg_parent(db, principal, quotation_id: int | None, tender_id: int | None, edit: bool) -> None:
    if bool(quotation_id) == bool(tender_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A quotation or a tender")
    if quotation_id:
        from app.quotations import service as qsvc  # noqa: PLC0415

        scope = principal.permissions.get("quotation.edit" if edit else "quotation.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
        qsvc.get_visible(db, quotation_id, scope, principal)
    else:
        from app.tenders.service import get_visible  # noqa: PLC0415

        scope = principal.permissions.get("tender.edit" if edit else "tender.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
        get_visible(db, tender_id, scope, principal)


def _neg_out(db, n: Negotiation) -> dict:
    from app.quotations.models import Quotation  # noqa: PLC0415
    from app.tenders.models import TenderRevision  # noqa: PLC0415

    rq = db.get(Quotation, n.revision_quotation_id) if n.revision_quotation_id else None
    tr = db.get(TenderRevision, n.tender_revision_id) if n.tender_revision_id else None
    return jsonable_encoder(
        {
            "id": n.id,
            "asked": n.asked,
            "given": n.given,
            "revision": f"{rq.code} R{rq.revision}" if rq else (f"R{tr.rev_no}" if tr else None),
            "revision_quotation_id": n.revision_quotation_id,
            "tender_revision_id": n.tender_revision_id,
            "by": names(db, [n.created_by]).get(n.created_by),
            "at": n.created_at,
        }
    )


@router.get("/negotiations")
def negotiations(
    db: DbSession,
    principal: CurrentPrincipal,
    quotation_id: int | None = None,
    tender_id: int | None = None,
) -> list[dict]:
    _neg_parent(db, principal, quotation_id, tender_id, edit=False)
    if quotation_id:
        from app.quotations.models import Quotation  # noqa: PLC0415

        q = db.get(Quotation, quotation_id)
        ids = [quotation_id]
        prev = q.previous_id
        while prev:  # the whole chain of revisions
            ids.append(prev)
            prev = db.get(Quotation, prev).previous_id
        rows = db.scalars(
            select(Negotiation).where(Negotiation.quotation_id.in_(ids)).order_by(Negotiation.id)
        )
    else:
        rows = db.scalars(
            select(Negotiation).where(Negotiation.tender_id == tender_id).order_by(Negotiation.id)
        )
    return [_neg_out(db, n) for n in rows]


class NegIn(BaseModel):
    quotation_id: int | None = None
    tender_id: int | None = None
    asked: str = Field(min_length=2, max_length=2000)
    given: str | None = Field(None, max_length=2000)
    revision_quotation_id: int | None = None
    tender_revision_id: int | None = None


@router.post("/negotiations", status_code=status.HTTP_201_CREATED)
def add_negotiation(
    body: NegIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    _neg_parent(db, principal, body.quotation_id, body.tender_id, edit=True)
    n = Negotiation(**body.model_dump(), created_by=principal.user.id)
    db.add(n)
    db.flush()
    record(db, request, principal, "negotiation.add", "negotiation", n.id, after=body.model_dump())
    db.commit()
    return _neg_out(db, n)


class NegLinkIn(BaseModel):
    given: str | None = None
    revision_quotation_id: int | None = None
    tender_revision_id: int | None = None


@router.patch("/negotiations/{nid}")
def link_negotiation(
    nid: int, body: NegLinkIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    n = db.get(Negotiation, nid)
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _neg_parent(db, principal, n.quotation_id, n.tender_id, edit=True)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(n, k, v)
    record(
        db,
        request,
        principal,
        "negotiation.update",
        "negotiation",
        n.id,
        after=body.model_dump(exclude_unset=True),
    )
    db.commit()
    return _neg_out(db, n)


# --- the closure scorecard -----------------------------------------------------------------------


@router.get("/scorecard")
def scorecard(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: Annotated[str, Depends(require_permission("scorecard.view"))],
) -> list[dict]:
    """The director sees everyone; a salesperson only themselves."""
    return jsonable_encoder(team.scorecard(db, None if scope == "all" else [principal.user.id]))


# --- tenders: bidders, award follow-ups, the send checklist --------------------------------------


def _tender(db, principal, tender_id: int, edit: bool):
    from app.tenders.service import get_visible  # noqa: PLC0415

    scope = principal.permissions.get("tender.edit" if edit else "tender.view")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
    return get_visible(db, tender_id, scope, principal)


def _bidder_out(b: TenderBidder) -> dict:
    return jsonable_encoder(
        {
            "id": b.id,
            "name": b.name,
            "rate": b.rate,
            "rank": b.rank,
            "label": f"L{b.rank}" if b.rank else None,
            "is_winner": b.is_winner,
            "is_us": b.is_us,
            "note": b.note,
        }
    )


@router.get("/tenders/{tender_id}/award")
def award(tender_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    from app.tenders.models import TenderRevision  # noqa: PLC0415

    t = _tender(db, principal, tender_id, edit=False)
    submitted = db.scalar(
        select(TenderRevision.submitted_at)
        .where(TenderRevision.tender_id == t.id)
        .order_by(TenderRevision.rev_no.desc())
        .limit(1)
    )
    s = team.settings(db)
    last = t.award_followup_at or submitted
    return jsonable_encoder(
        {
            "status": "awaiting award" if t.status == "submitted" else t.status,
            "submitted_at": submitted,
            "last_followup_at": t.award_followup_at,
            "next_followup_on": (
                last.astimezone(mywork.IST).date().toordinal() + s.award_followup_days
            )
            if last
            else None,
            "followup_days": s.award_followup_days,
            "winner_lead_id": t.winner_lead_id,
            "bidders": [
                _bidder_out(b)
                for b in db.scalars(
                    select(TenderBidder)
                    .where(TenderBidder.tender_id == t.id)
                    .order_by(TenderBidder.rank.nulls_last(), TenderBidder.id)
                )
            ],
            "send_check": team.tender_send_check(db, t),
        }
    )


class BidderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rate: Decimal | None = Field(None, ge=0)
    rank: int | None = Field(None, ge=1, le=50)
    is_us: bool = False
    note: str | None = None


@router.post("/tenders/{tender_id}/bidders", status_code=status.HTTP_201_CREATED)
def add_bidder(
    tender_id: int, body: BidderIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = _tender(db, principal, tender_id, edit=True)
    b = TenderBidder(tender_id=t.id, **body.model_dump())
    db.add(b)
    db.flush()
    record(
        db,
        request,
        principal,
        "tender.bidder",
        "tender",
        t.id,
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return _bidder_out(b)


@router.delete("/tenders/{tender_id}/bidders/{bid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bidder(tender_id: int, bid: int, db: DbSession, principal: CurrentPrincipal) -> None:
    t = _tender(db, principal, tender_id, edit=True)
    b = db.get(TenderBidder, bid)
    if b is None or b.tender_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    db.delete(b)
    db.commit()


class WinnerIn(BaseModel):
    bidder_id: int
    followup_on: date  # timed to the winner's waterproofing stage
    note: str | None = None


@router.post("/tenders/{tender_id}/winner")
def winner(
    tender_id: int, body: WinnerIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Another contractor won: record them, close the tender as lost to them, and open a lead
    with the winner, followed up on the date picked (their waterproofing stage)."""
    from app.crm.models import Lead, LeadActivity  # noqa: PLC0415
    from app.crm.routers import next_code  # noqa: PLC0415

    t = _tender(db, principal, tender_id, edit=True)
    b = db.get(TenderBidder, body.bidder_id)
    if b is None or b.tender_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bidder not found")
    if b.is_us:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That is us: mark the tender won instead"
        )
    db.execute(
        TenderBidder.__table__.update()
        .where(TenderBidder.tender_id == t.id)
        .values(is_winner=False)
    )
    b.is_winner = True
    if t.status not in ("won",):
        t.status, t.lost_to, t.decided_at = "lost", b.name[:200], team.now()
        t.lost_reason = t.lost_reason or "price"
    lead = Lead(
        code=next_code(db),
        contact_name=b.name,
        company=b.name,
        owner_id=t.owner_id,
        status="new",
        next_follow_up=body.followup_on,
        created_by=principal.user.id,
    )
    lead.requirement = f"Won tender {t.code} ({t.name}): offer our waterproofing to them. {body.note or ''}".strip()
    db.add(lead)
    db.flush()
    db.add(
        LeadActivity(
            lead_id=lead.id,
            type="note",
            text=f"Winner of {t.code}; follow up on {body.followup_on:%d %b %Y}",
            by=principal.user.id,
        )
    )
    t.winner_lead_id = lead.id
    record(
        db,
        request,
        principal,
        "tender.winner",
        "tender",
        t.id,
        after={"winner": b.name, "lead": lead.code, "followup_on": str(body.followup_on)},
    )
    db.commit()
    return {"lead_id": lead.id, "lead_code": lead.code, "winner": b.name}


class FollowupIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


@router.post("/tenders/{tender_id}/award-followup")
def award_followup(
    tender_id: int, body: FollowupIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    t = _tender(db, principal, tender_id, edit=False)
    t.award_followup_at = team.now()
    record(
        db, request, principal, "tender.award_followup", "tender", t.id, after={"note": body.note}
    )
    db.commit()
    return {"id": t.id, "last_followup_at": t.award_followup_at}


@router.get("/send-check")
def send_check(
    db: DbSession,
    principal: CurrentPrincipal,
    tender_id: int | None = None,
    quotation_id: int | None = None,
) -> dict:
    if tender_id:
        return {
            "missing": team.tender_send_check(db, _tender(db, principal, tender_id, edit=False))
        }
    if quotation_id:
        from app.quotations import service as qsvc  # noqa: PLC0415

        scope = principal.permissions.get("quotation.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission")
        return {
            "missing": team.quotation_send_check(
                qsvc.get_visible(db, quotation_id, scope, principal)
            )
        }
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A tender or a quotation")
