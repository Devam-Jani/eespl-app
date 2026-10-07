"""CRM leads (with the Kylas push status), and Settings > Integrations > Kylas.

Permissions: leads.view / leads.edit with scope all or own (own = owner or creator). A lead
outside the caller's view scope is a 404. Kylas settings and users' Kylas ids need
admin.settings (super_admin).
"""

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import ColumnElement, false, or_, select, text, true
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.config import settings
from app.crm import kylas_client, kylas_push
from app.crm.models import CLOSED_STATUSES, Lead, LeadActivity
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Category, Channel, Client, CompanyProfile, System
from app.masters.routers.common import Limit, Offset, Search, like, paginate, unprocessable
from app.masters.schemas import Page
from app.models import User
from app.tenders.models import Tender, TenderMember
from app.tenders.service import copy_template
from app.tenders.service import next_code as next_tender_code

router = APIRouter(prefix="/api/leads", tags=["crm"])
settings_router = APIRouter(prefix="/api/settings/kylas", tags=["crm"])

ViewScope = Annotated[str, Depends(require_permission("leads.view"))]
EditScope = Annotated[str, Depends(require_permission("leads.edit"))]
AdminSettings = [Depends(require_permission("admin.settings"))]

LeadStatus = Literal["new", "contacted", "site_visit", "quoted", "won", "lost", "junk"]
LeadSource = Literal["website", "call", "referral", "channel", "walk_in", "exhibition", "other"]


def normalise_phone(value: str | None) -> str | None:
    """Indian numbers as +91XXXXXXXXXX; anything else as typed (digits and a leading +)."""
    if not value or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    raise ValueError("Enter a 10-digit mobile number (or +91 followed by 10 digits)")


# --- schemas -------------------------------------------------------------------------------------


class LeadFields(BaseModel):
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    channel_id: int | None = None
    client_id: int | None = None
    requirement: str | None = None
    system_id: int | None = None
    work_category_id: int | None = None
    est_area_sqm: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    est_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    owner_id: uuid.UUID | None = None
    next_follow_up: date | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class LeadIn(LeadFields):
    contact_name: str = Field(min_length=1, max_length=200)
    # required: Kylas finds a lead by phone after a timeout; without one it could be pushed twice
    phone: str = Field(min_length=1)
    lead_source: LeadSource = "other"

    _phone = field_validator("phone")(normalise_phone)


class LeadUpdate(LeadFields):
    contact_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    lead_source: LeadSource | None = None
    status: LeadStatus | None = None

    _phone = field_validator("phone")(normalise_phone)

    @field_validator("phone")
    @classmethod
    def _keep_phone(cls, v):
        if v is None:
            raise ValueError("A lead needs a phone number")
        return v


class ActivityIn(BaseModel):
    type: Literal["note", "call", "visit"] = "note"
    text: str = Field(min_length=1, max_length=5000)


class ActivityOut(BaseModel):
    id: int
    type: str
    text: str
    at: str
    by_name: str | None


class DuplicateOut(BaseModel):
    id: int
    code: str
    contact_name: str
    status: str


class LeadOut(BaseModel):
    id: int
    code: str
    contact_name: str
    phone: str | None
    email: str | None
    company: str | None
    city: str | None
    state: str | None
    lead_source: str
    channel_id: int | None
    channel_name: str | None
    client_id: int | None
    client_name: str | None
    requirement: str | None
    system_id: int | None
    work_category_id: int | None
    est_area_sqm: Decimal | None
    est_value: Decimal | None
    status: str
    owner_id: uuid.UUID | None
    owner_name: str | None
    created_by_name: str | None
    next_follow_up: date | None
    follow_up_due: bool
    tender_id: int | None
    tender_code: str | None
    kylas_lead_id: int | None
    kylas_sync_status: str
    kylas_last_error: str | None
    kylas_synced_at: str | None
    kylas_forecasting: str | None
    kylas_converted_at: str | None
    kylas_won_at: str | None
    created_at: str
    duplicates: list[DuplicateOut] = []


class LeadDetail(LeadOut):
    activities: list[ActivityOut]


class KylasSettingsOut(BaseModel):
    enabled_in_env: bool
    api_key: str  # "set" / "not set": never the key itself
    base_url: str
    active: bool
    inactive_reason: str | None
    source_id: int | None
    owner_rule: str
    default_owner_id: int | None
    deal_pipeline_id: int | None
    won_stage_id: int | None
    lead_code_field: str
    category_field: str
    junk_reasons: list[str]
    queue: dict[str, int]


class KylasSettingsIn(BaseModel):
    source_id: int | None = Field(default=None, gt=0)
    owner_rule: Literal["creator", "default"] = "creator"
    default_owner_id: int | None = Field(default=None, gt=0)
    deal_pipeline_id: int | None = Field(default=None, gt=0)
    won_stage_id: int | None = Field(default=None, gt=0)
    lead_code_field: str = Field(default="cfInquiryType", pattern=r"^[A-Za-z][A-Za-z0-9_]{1,59}$")
    category_field: str = Field(
        default="cfCustomerCategrory", pattern=r"^[A-Za-z][A-Za-z0-9_]{1,59}$"
    )
    junk_reasons: list[str] = Field(
        default_factory=lambda: ["Wrong number", "False enquiry", "Duplicate"], max_length=30
    )


# --- access --------------------------------------------------------------------------------------


def scope_condition(scope: str, principal: Principal) -> ColumnElement[bool]:
    if scope == "all":
        return true()
    if scope in ("own", "assigned"):
        return or_(Lead.owner_id == principal.user.id, Lead.created_by == principal.user.id)
    return false()


def covers(scope: str | None, principal: Principal, lead: Lead) -> bool:
    if scope == "all":
        return True
    if scope in ("own", "assigned"):
        return principal.user.id in (lead.owner_id, lead.created_by)
    return False


def _visible(db: Session, lead_id: int, scope: str, principal: Principal) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or not covers(scope, principal, lead):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


def _editable(db, lead_id, view, principal) -> Lead:
    lead = _visible(db, lead_id, view, principal)
    if not covers(principal.permissions.get("leads.edit"), principal, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this lead")
    return lead


def _record(db, request, principal, action, lead, before=None, after=None):
    audit.record(
        db,
        action,
        "lead",
        lead.id,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def next_code(db: Session) -> str:
    year = date.today().year
    value = db.execute(
        text(
            "INSERT INTO lead_sequences (year, last_value) VALUES (:y, 1) ON CONFLICT (year) DO "
            "UPDATE SET last_value = lead_sequences.last_value + 1 RETURNING last_value"
        ),
        {"y": year},
    ).scalar_one()
    return f"L-{year}-{value:04d}"


def duplicates(db: Session, phone: str | None, exclude: int | None = None) -> list[DuplicateOut]:
    if not phone:
        return []
    query = select(Lead).where(Lead.phone == phone)
    if exclude:
        query = query.where(Lead.id != exclude)
    return [
        DuplicateOut(id=d.id, code=d.code, contact_name=d.contact_name, status=d.status)
        for d in db.scalars(query.order_by(Lead.id))
    ]


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _out(db: Session, lead: Lead) -> dict:
    tender_code = (
        db.scalar(select(Tender.code).where(Tender.id == lead.tender_id))
        if (lead.tender_id)
        else None
    )
    return dict(
        id=lead.id,
        code=lead.code,
        contact_name=lead.contact_name,
        phone=lead.phone,
        email=lead.email,
        company=lead.company,
        city=lead.city,
        state=lead.state,
        lead_source=lead.lead_source,
        channel_id=lead.channel_id,
        channel_name=lead.channel.name if lead.channel else None,
        client_id=lead.client_id,
        client_name=lead.client.name if lead.client else None,
        requirement=lead.requirement,
        system_id=lead.system_id,
        work_category_id=lead.work_category_id,
        est_area_sqm=lead.est_area_sqm,
        est_value=lead.est_value,
        status=lead.status,
        owner_id=lead.owner_id,
        owner_name=lead.owner.full_name if lead.owner else None,
        created_by_name=lead.creator.full_name if lead.creator else None,
        next_follow_up=lead.next_follow_up,
        follow_up_due=bool(
            lead.next_follow_up
            and lead.next_follow_up <= date.today()
            and lead.status not in CLOSED_STATUSES
        ),
        tender_id=lead.tender_id,
        tender_code=tender_code,
        kylas_lead_id=lead.kylas_lead_id,
        kylas_sync_status=lead.kylas_sync_status,
        kylas_last_error=lead.kylas_last_error,
        kylas_synced_at=_iso(lead.kylas_synced_at),
        kylas_forecasting=lead.kylas_forecasting,
        kylas_converted_at=_iso(lead.kylas_converted_at),
        kylas_won_at=_iso(lead.kylas_won_at),
        created_at=lead.created_at.isoformat(),
    )


def _detail(db: Session, lead: Lead) -> LeadDetail:
    acts = db.scalars(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead.id)
        .order_by(LeadActivity.at.desc(), LeadActivity.id.desc())
    )
    return LeadDetail(
        **_out(db, lead),
        duplicates=duplicates(db, lead.phone, lead.id),
        activities=[
            ActivityOut(
                id=a.id,
                type=a.type,
                text=a.text,
                at=a.at.isoformat(),
                by_name=a.author.full_name if a.author else None,
            )
            for a in acts
        ],
    )


def _check_refs(db: Session, data: dict) -> None:
    for key, model, label in (
        ("channel_id", Channel, "channel"),
        ("client_id", Client, "client"),
        ("system_id", System, "system"),
        ("work_category_id", Category, "work category"),
        ("owner_id", User, "owner"),
    ):
        if data.get(key) is not None and db.get(model, data[key]) is None:
            raise unprocessable(f"Unknown {label}")


# --- list ----------------------------------------------------------------------------------------


def _query(scope, principal, q, status_, owner_id, source, due, sync):
    query = select(Lead).where(scope_condition(scope, principal))
    if q:
        p = like(q)
        query = query.where(
            or_(
                Lead.code.ilike(p),
                Lead.contact_name.ilike(p),
                Lead.company.ilike(p),
                Lead.phone.ilike(p),
                Lead.city.ilike(p),
            )
        )
    if status_:
        query = query.where(Lead.status == status_)
    if owner_id:
        query = query.where(Lead.owner_id == owner_id)
    if source:
        query = query.where(Lead.lead_source == source)
    if sync:
        query = query.where(Lead.kylas_sync_status == sync)
    if due:
        query = query.where(
            Lead.next_follow_up <= date.today(), Lead.status.not_in(CLOSED_STATUSES)
        )
    return query.order_by(Lead.created_at.desc(), Lead.id.desc())


@router.get("")
def list_leads(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    lead_source: str | None = None,
    follow_up_due: bool = False,
    kylas_sync_status: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[LeadOut]:
    query = _query(
        scope, principal, q, status, owner_id, lead_source, follow_up_due, kylas_sync_status
    )
    rows, total = paginate(db, query, limit, offset)
    return Page(
        items=[LeadOut(**_out(db, x)) for x in rows], total=total, limit=limit, offset=offset
    )


@router.get("/export")
def export_leads(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    lead_source: str | None = None,
    follow_up_due: bool = False,
    kylas_sync_status: str | None = None,
):
    query = _query(
        scope, principal, q, status, owner_id, lead_source, follow_up_due, kylas_sync_status
    ).limit(EXPORT_ROW_LIMIT)
    rows = [_out(db, x) for x in db.scalars(query)]
    columns = [
        "Code",
        "Contact",
        "Phone",
        "Email",
        "Company",
        "City",
        "Source",
        "Channel",
        "Client",
        "Status",
        "Owner",
        "Next follow-up",
        "Est. area sqm",
        "Est. value",
        "Tender",
        "Kylas",
        "Created",
    ]
    return xlsx_response(
        "leads",
        columns,
        [
            [
                r["code"],
                r["contact_name"],
                r["phone"],
                r["email"],
                r["company"],
                r["city"],
                r["lead_source"],
                r["channel_name"],
                r["client_name"],
                r["status"],
                r["owner_name"],
                r["next_follow_up"],
                r["est_area_sqm"],
                r["est_value"],
                r["tender_code"],
                r["kylas_sync_status"],
                r["created_at"][:10],
            ]
            for r in rows
        ],
    )


@router.get("/lookups")
def lookups(db: DbSession, _: ViewScope) -> dict[str, list[dict]]:
    return {
        "channels": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(Channel.id, Channel.name).where(Channel.is_active).order_by(Channel.name)
            )
        ],
        "clients": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(Client.id, Client.name).where(Client.is_active).order_by(Client.name)
            )
        ],
        "users": [
            {"id": str(i), "full_name": n}
            for i, n in db.execute(
                select(User.id, User.full_name).where(User.is_active).order_by(User.full_name)
            )
        ],
        "systems": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(System.id, System.name).where(System.is_active).order_by(System.name)
            )
        ],
        "work_categories": [
            {"id": i, "name": n}
            for i, n in db.execute(
                select(Category.id, Category.name)
                .where(Category.kind == "work", Category.is_active)
                .order_by(Category.sort_order, Category.name)
            )
        ],
    }


@router.get("/check-phone")
def check_phone(phone: str, db: DbSession, _: ViewScope) -> list[DuplicateOut]:
    """Leads with this phone already (a warning only: the user may still save)."""
    try:
        normal = normalise_phone(phone)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc
    return duplicates(db, normal)


# --- create / edit -------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def create_lead(
    body: LeadIn,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    principal: CurrentPrincipal,
    _: EditScope,
) -> LeadDetail:
    """Saves the lead and, in the same transaction, queues it for Kylas. Kylas is called after
    the response (and by the worker), never during the save."""
    data = body.model_dump()
    _check_refs(db, data)
    data["owner_id"] = data["owner_id"] or principal.user.id
    lead = Lead(code=next_code(db), created_by=principal.user.id, **data)
    db.add(lead)
    db.flush()
    db.add(
        LeadActivity(
            lead_id=lead.id, type="status_change", text="Lead created (new)", by=principal.user.id
        )
    )
    queued = kylas_push.queue_lead(db, lead)
    _record(db, request, principal, "lead.create", lead, after=audit.model_snapshot(lead))
    db.commit()
    db.refresh(lead)
    if queued:
        background.add_task(kylas_push.push_now, lead.id)
    return _detail(db, lead)


@router.get("/{lead_id}")
def get_lead(
    lead_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> LeadDetail:
    return _detail(db, _visible(db, lead_id, scope, principal))


@router.patch("/{lead_id}")
def update_lead(
    lead_id: int,
    body: LeadUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
) -> LeadDetail:
    """Edits stay in EESPL: they are not pushed to Kylas."""
    lead = _editable(db, lead_id, view, principal)
    changes = body.model_dump(exclude_unset=True)
    _check_refs(db, changes)
    before = audit.model_snapshot(lead)
    old_status = lead.status
    for field, value in changes.items():
        if field in ("contact_name", "lead_source", "status") and value is None:
            continue
        setattr(lead, field, value)
    if lead.status != old_status:
        db.add(
            LeadActivity(
                lead_id=lead.id,
                type="status_change",
                text=f"{old_status} -> {lead.status}",
                by=principal.user.id,
            )
        )
    db.flush()
    after = audit.model_snapshot(lead)
    if after != before:
        _record(db, request, principal, "lead.update", lead, before, after)
    db.commit()
    db.refresh(lead)
    return _detail(db, lead)


@router.post("/{lead_id}/activities", status_code=status.HTTP_201_CREATED)
def add_activity(
    lead_id: int, body: ActivityIn, db: DbSession, principal: CurrentPrincipal, view: ViewScope
) -> LeadDetail:
    lead = _editable(db, lead_id, view, principal)
    db.add(
        LeadActivity(lead_id=lead.id, type=body.type, text=body.text.strip(), by=principal.user.id)
    )
    db.commit()
    return _detail(db, lead)


@router.post("/{lead_id}/convert", status_code=status.HTTP_201_CREATED)
def convert_to_tender(
    lead_id: int, request: Request, db: DbSession, principal: CurrentPrincipal, view: ViewScope
) -> LeadDetail:
    """A tender with the lead's client and channel; the lead links to it."""
    lead = _editable(db, lead_id, view, principal)
    if "tender.edit" not in principal.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: tender.edit")
    if lead.tender_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This lead already has a tender")
    if lead.client_id is None and lead.channel_id is None:
        raise unprocessable("Set the lead's client or channel first (a tender needs one)")
    tender = Tender(
        code=next_tender_code(db),
        name=(lead.company or lead.contact_name)[:300],
        client_id=lead.client_id,
        channel_id=lead.channel_id,
        site_city=lead.city,
        site_state=lead.state,
        received_on=date.today(),
        owner_id=lead.owner_id,
        notes=f"From lead {lead.code}" + (f": {lead.requirement}" if lead.requirement else ""),
        created_by=principal.user.id,
    )
    db.add(tender)
    db.flush()
    if lead.owner_id and lead.owner_id != tender.owner_id:
        db.add(
            TenderMember(tender_id=tender.id, user_id=lead.owner_id, created_by=principal.user.id)
        )
    copy_template(db, tender, None, principal.user.id)
    lead.tender_id = tender.id
    if lead.status in ("new", "contacted", "site_visit"):
        lead.status = "quoted"
    db.add(
        LeadActivity(
            lead_id=lead.id,
            type="status_change",
            text=f"Converted to tender {tender.code}",
            by=principal.user.id,
        )
    )
    _record(db, request, principal, "lead.convert", lead, after={"tender": tender.code})
    db.commit()
    db.refresh(lead)
    return _detail(db, lead)


@router.post("/{lead_id}/kylas/retry")
def retry_kylas(
    lead_id: int,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
) -> LeadDetail:
    lead = _editable(db, lead_id, view, principal)
    if lead.kylas_lead_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This lead is already in Kylas")
    if not lead.phone:
        raise unprocessable(kylas_push.NEEDS_PHONE)
    queued = kylas_push.retry(db, lead)
    _record(db, request, principal, "lead.kylas_retry", lead, after={"queued": queued})
    db.commit()
    if queued:
        background.add_task(kylas_push.push_now, lead.id)
    db.refresh(lead)
    return _detail(db, lead)


# --- Settings > Integrations > Kylas -------------------------------------------------------------


def _settings_out(db: Session) -> KylasSettingsOut:
    p = db.get(CompanyProfile, 1) or CompanyProfile(id=1)
    on, why = kylas_push.enabled(db)
    key = settings.kylas_api_key.get_secret_value() if settings.kylas_api_key else ""
    queue = dict(
        db.execute(
            text("SELECT kylas_sync_status, count(*) FROM leads GROUP BY kylas_sync_status")
        ).all()
    )
    return KylasSettingsOut(
        enabled_in_env=settings.kylas_enabled,
        api_key="set" if key.strip() else "not set",
        base_url=settings.kylas_base_url,
        active=on,
        inactive_reason=why,
        source_id=p.kylas_source_id,
        owner_rule=p.kylas_owner_rule or "creator",
        default_owner_id=p.kylas_default_owner_id,
        deal_pipeline_id=p.kylas_deal_pipeline_id,
        won_stage_id=p.kylas_won_stage_id,
        lead_code_field=p.kylas_lead_code_field or "cfInquiryType",
        category_field=p.kylas_category_field or "cfCustomerCategrory",
        junk_reasons=list(p.kylas_junk_reasons or []),
        queue=queue,
    )


@settings_router.get("", dependencies=AdminSettings)
def get_kylas_settings(db: DbSession) -> KylasSettingsOut:
    return _settings_out(db)


def _check_won_stage(body: KylasSettingsIn) -> None:
    """A won stage needs its deal pipeline, and must be one of that pipeline's stages in Kylas
    (checked live: the deal poll would never match a stage of another pipeline)."""
    if body.won_stage_id is None:
        return
    if body.deal_pipeline_id is None:
        raise unprocessable("Set the deal pipeline id together with the won stage id")
    client = kylas_client.client()
    if not client.is_configured:
        raise unprocessable("The won stage can only be checked with a Kylas API key in .env")
    found = kylas_client.deal_pipelines(client)
    if not found.ok:
        raise unprocessable(f"Could not check the stage with Kylas (HTTP {found.status_code})")
    pipeline = next((p for p in found.items if p["id"] == body.deal_pipeline_id), None)
    if pipeline is None:
        raise unprocessable(f"{body.deal_pipeline_id} is not a deal pipeline in Kylas")
    if body.won_stage_id not in {s["id"] for s in pipeline["stages"]}:
        stages = ", ".join(f"{s['id']} {s['name']}" for s in pipeline["stages"])
        raise unprocessable(
            f"{body.won_stage_id} is not a stage of pipeline {pipeline['id']} "
            f"({pipeline['name']}); its stages are {stages}"
        )


@settings_router.put("", dependencies=AdminSettings)
def set_kylas_settings(
    body: KylasSettingsIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> KylasSettingsOut:
    _check_won_stage(body)
    p = db.get(CompanyProfile, 1)
    if p is None:
        p = CompanyProfile(id=1)
        db.add(p)
    before = {k: v for k, v in audit.model_snapshot(p).items() if k.startswith("kylas_")}
    reasons = [" ".join(r.split())[:100] for r in body.junk_reasons if r and r.strip()]
    p.kylas_source_id, p.kylas_owner_rule = body.source_id, body.owner_rule
    p.kylas_default_owner_id = body.default_owner_id
    p.kylas_deal_pipeline_id, p.kylas_won_stage_id = body.deal_pipeline_id, body.won_stage_id
    p.kylas_lead_code_field, p.kylas_category_field = body.lead_code_field, body.category_field
    p.kylas_junk_reasons = list(dict.fromkeys(reasons))
    db.flush()
    after = {k: v for k, v in audit.model_snapshot(p).items() if k.startswith("kylas_")}
    audit.record(
        db,
        "settings.kylas",
        "company",
        1,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )
    db.commit()
    return _settings_out(db)


@settings_router.post("/test", dependencies=AdminSettings)
def test_connection(db: DbSession) -> dict[str, str | int | bool | None]:
    """One GET (the lead fields, for the source list, read as kylas-discover reads it). Says
    whether Kylas answered and whether the configured source exists; never echoes the key."""
    client = kylas_client.client()
    if not client.is_configured:
        return {"ok": False, "message": "No Kylas API key in .env"}
    found = kylas_client.lead_sources(client)
    if not found.ok:
        return {
            "ok": False,
            "status": found.status_code,
            "message": "Kylas did not accept the API key"
            if found.status_code in (401, 403)
            else (found.error or "No answer")[:200],
        }
    message = f"Connected: {len(found.items)} lead sources"
    p = db.get(CompanyProfile, 1)
    if p is not None and p.kylas_source_id:
        source = next((s for s in found.items if s["id"] == p.kylas_source_id), None)
        if source:
            message += f"; source {p.kylas_source_id} is '{source['name']}'"
        else:
            message += f"; source {p.kylas_source_id} is NOT a Kylas lead source"
    return {"ok": True, "status": found.status_code, "message": message}
