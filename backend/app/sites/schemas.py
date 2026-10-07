import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SiteStatus = Literal["planned", "active", "on_hold", "completed", "closed"]
MemberRole = Literal["incharge", "supervisor", "sales", "office", "viewer"]
NodeKind = Literal[
    "tower",
    "wing",
    "basement",
    "floor",
    "flat",
    "toilet",
    "kitchen",
    "balcony",
    "terrace",
    "podium",
    "lift_pit",
    "ug_tank",
    "oh_tank",
    "retaining_wall",
    "raft",
    "stp",
    "swimming_pool",
    "other",
]
Discipline = Literal["architectural", "structural", "waterproofing", "other"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    role_on_site: str


class SiteOut(BaseModel):
    id: int
    code: str
    name: str
    client_id: int | None
    client_name: str | None
    channel_id: int | None
    channel_name: str | None
    tender_id: int | None
    tender_code: str | None
    address: str | None
    city: str | None
    state: str | None
    lat: Decimal | None
    lng: Decimal | None
    start_date: date | None
    target_date: date | None
    late: bool
    status: str
    site_incharge_id: uuid.UUID | None
    incharge_name: str | None
    notes: str | None
    source: str
    source_ref: str | None
    progress_percent: Decimal
    members: list[MemberOut]
    created_at: datetime


class SiteFields(BaseModel):
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    lat: Decimal | None = Field(default=None, ge=-90, le=90)
    lng: Decimal | None = Field(default=None, ge=-180, le=180)
    start_date: date | None = None
    target_date: date | None = None
    site_incharge_id: uuid.UUID | None = None
    notes: str | None = None


class SiteIn(SiteFields):
    name: str = Field(min_length=1, max_length=300)
    client_id: int | None = None
    channel_id: int | None = None
    status: SiteStatus = "planned"


class SiteUpdate(SiteFields):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    client_id: int | None = None
    channel_id: int | None = None
    status: SiteStatus | None = None


class FromTenderIn(SiteFields):
    tender_id: int
    name: str | None = Field(default=None, max_length=300)  # default: the tender's name


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role_on_site: MemberRole = "viewer"


class MembersIn(BaseModel):
    members: list[MemberIn]


# --- structure ---


class NodeOut(BaseModel):
    id: int
    parent_id: int | None
    kind: str
    name: str
    path: str
    sort_order: int
    level_no: int | None
    area_sqm: Decimal | None
    meta: dict[str, Any] | None
    progress_percent: Decimal


class NodeIn(BaseModel):
    parent_id: int | None = None
    kind: NodeKind
    name: str = Field(min_length=1, max_length=200)
    level_no: int | None = None
    area_sqm: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    sort_order: int | None = None
    meta: dict[str, Any] | None = None


class NodeUpdate(BaseModel):
    parent_id: int | None = None
    kind: NodeKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    level_no: int | None = None
    area_sqm: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    sort_order: int | None = None
    meta: dict[str, Any] | None = None


# --- stage templates ---


class StepIn(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    weight_percent: Decimal = Field(ge=0, le=100, max_digits=6, decimal_places=2)
    needs_photo: bool = True
    needs_inspection: bool = False
    hold_point: bool = False
    typical_days: int = Field(default=1, ge=1, le=365)
    checklist_template_id: int | None = None  # a hold point then needs a passed inspection


class StepOut(StepIn):
    id: int
    sort_order: int


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    system_id: int | None = None
    work_category_id: int | None = None
    keywords: str | None = None
    is_active: bool = True
    steps: list[StepIn] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def _weights(cls, steps: list[StepIn]) -> list[StepIn]:
        total = sum(s.weight_percent for s in steps)
        if total != 100:
            raise ValueError(f"Step weights must add up to 100 (they add up to {total})")
        return steps


class TemplateOut(BaseModel):
    id: int
    name: str
    system_id: int | None
    system_name: str | None
    work_category_id: int | None
    work_category_name: str | None
    keywords: str | None
    is_active: bool
    steps: list[StepOut]
    total_days: int


# --- scope ---


class ScopeOut(BaseModel):
    id: int
    node_id: int
    node_path: str
    boq_line_id: int | None
    stage_template_id: int
    stage_template_name: str
    qty: Decimal
    unit: str | None
    progress_percent: Decimal
    tasks: int
    started: int


class ScopeLineOut(BaseModel):
    boq_line_id: int
    item_no: str | None
    description: str
    unit: str | None
    boq_qty: Decimal | None
    qty_note: str | None
    suggested_template_id: int | None
    assigned: Decimal
    difference: Decimal
    state: Literal["ok", "under", "over", "no_qty"]
    scopes: list[ScopeOut]


class ScopeOverview(BaseModel):
    lines: list[ScopeLineOut]
    other_scopes: list[ScopeOut]  # scopes not tied to a BOQ line


class AssignIn(BaseModel):
    boq_line_id: int | None = None
    node_ids: list[int] = Field(min_length=1)
    stage_template_id: int
    qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)  # no line
    unit: str | None = None
    replace: bool = False  # replace this line's earlier assignment (not started ones)


class ScopeUpdate(BaseModel):
    qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    stage_template_id: int | None = None


# --- tasks ---


class InspectionItem(BaseModel):
    item: str = Field(min_length=1, max_length=300)
    passed: bool | None = None


class PhotoOut(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime


class TaskOut(BaseModel):
    id: int
    node_id: int | None
    node_path: str | None
    area_scope_id: int | None
    step_id: int | None
    name: str
    sort_order: int
    planned_start: date | None
    planned_end: date | None
    actual_start: date | None
    actual_end: date | None
    status: str
    late: bool
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    progress_percent: Decimal
    parent_task_id: int | None
    depends_on: list[int]
    weight_percent: Decimal | None
    needs_photo: bool
    needs_inspection: bool
    hold_point: bool
    checklist_template_id: int | None = None
    remark: str | None
    inspection: list[InspectionItem] | None
    certified_at: datetime | None
    photos: list[PhotoOut]


class TaskUpdate(BaseModel):
    status: Literal["not_started", "in_progress", "done", "blocked"] | None = None
    progress_percent: Decimal | None = Field(default=None, ge=0, le=100)
    remark: str | None = None
    inspection: list[InspectionItem] | None = None
    assignee_id: uuid.UUID | None = None
    planned_start: date | None = None
    planned_end: date | None = None


class GenerateOut(BaseModel):
    added: int
    kept: int
    tasks: int
    planned_end: date | None


# --- drawings ---


class RevisionOut(BaseModel):
    id: int
    rev: str
    filename: str
    size_bytes: int
    status: str
    uploaded_by_name: str | None
    uploaded_at: datetime
    approved_by_name: str | None
    approved_at: datetime | None
    remark: str | None


class DrawingOut(BaseModel):
    id: int
    title: str
    discipline: str
    node_id: int | None
    node_path: str | None
    latest_approved: RevisionOut | None
    latest: RevisionOut | None
    revisions: list[RevisionOut]


class DecisionIn(BaseModel):
    remark: str | None = Field(default=None, max_length=2000)
