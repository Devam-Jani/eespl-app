"""Tender API shapes.

Cost data (cost rate, margin, price source and its build-up, library min/median/max) is only for
callers with tender.margin. Those callers get the *Cost* models; everyone else gets the plain
models, in which those fields do not exist at all (not null, not zero: absent).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

TenderStatus = Literal["draft", "submitted", "won", "lost", "dropped"]
# why it was lost (app.tenders.models.LOST_REASONS)
LostReason = Literal["price", "competitor", "timing", "spec", "relationship", "other"]
LineStatus = Literal["unpriced", "suggested", "priced", "not_quoted"]
QtyNote = Literal["QRO", "NQ"]
Percent = Annotated[Decimal, Field(ge=0, lt=1000, max_digits=6, decimal_places=2)]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str


class TenderOut(BaseModel):
    id: int
    code: str
    name: str
    client_id: int | None
    client_name: str | None
    channel_id: int | None
    channel_name: str | None
    site_name: str | None
    site_city: str | None
    site_state: str | None
    received_on: date | None
    due_on: date | None
    overdue: bool
    owner_id: uuid.UUID | None
    owner_name: str | None
    members: list[MemberOut]
    status: str
    lost_reason: str | None
    lost_to: str | None
    lost_note: str | None = None
    decided_at: datetime | None = None
    quoted_total: Decimal
    tc_template_id: int | None
    notes: str | None
    created_at: datetime
    revision: int
    revision_label: str  # "R1", or "R1 (draft)" while it is being edited
    submitted_revisions: int
    site_id: int | None = None  # the site made from this tender once won
    kylas_won_lead: str | None = None  # a lead of this tender won in Kylas: confirm and mark won


class TenderCostOut(TenderOut):
    cost_total: Decimal | None  # None: no system-priced lines
    margin_amount: Decimal | None


class TenderIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    client_id: int | None = None  # the end client (e.g. Adani Realty)
    channel_id: int | None = None  # who brought it: salesperson, partner, manufacturer
    site_name: str | None = Field(default=None, max_length=200)
    site_city: str | None = Field(default=None, max_length=100)
    site_state: str | None = Field(default=None, max_length=100)
    received_on: date | None = None
    due_on: date | None = None
    owner_id: uuid.UUID | None = None  # default: the creator
    member_ids: list[uuid.UUID] = []
    tc_template_id: int | None = None  # default: the default T&C template
    notes: str | None = None

    @model_validator(mode="after")
    def _client_or_channel(self):
        if self.client_id is None and self.channel_id is None:
            raise ValueError("Choose the client, the channel, or both")
        return self


class TenderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    client_id: int | None = None
    channel_id: int | None = None
    site_name: str | None = Field(default=None, max_length=200)
    site_city: str | None = Field(default=None, max_length=100)
    site_state: str | None = Field(default=None, max_length=100)
    received_on: date | None = None
    due_on: date | None = None
    owner_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] | None = None
    status: TenderStatus | None = None
    lost_reason: LostReason | None = None
    lost_to: str | None = Field(default=None, max_length=200)  # the competitor, if known
    lost_note: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _reason(self):
        if self.status in ("lost", "dropped") and not self.lost_reason:
            raise ValueError("Pick why the tender was lost or dropped")
        return self


# --- BOQ ---


class SectionOut(BaseModel):
    id: int
    title: str
    note: str | None
    sort_order: int
    total: Decimal


class LineOut(BaseModel):
    id: int
    section_id: int | None
    sort_order: int
    client_item_no: str | None
    description: str
    unit: str | None
    unit_raw: str | None
    qty: Decimal | None
    qty_note: str | None
    client_product: str | None
    client_remarks: str | None
    client_file_rate: Decimal | None
    client_material_rate: Decimal | None
    client_application_rate: Decimal | None
    source_page: int | None
    source_page_to: int | None
    rate: Decimal | None
    amount: Decimal | None
    our_remarks: str | None
    our_product: str | None
    status: str
    suggestion_score: Decimal | None


class LineCostOut(LineOut):
    source: str | None
    system_id: int | None
    library_item_id: int | None
    cost_rate: Decimal | None
    margin_percent: Decimal | None


class TotalsOut(BaseModel):
    subtotal: Decimal
    gst_percent: Decimal
    gst: Decimal
    grand_total: Decimal
    counts: dict[str, int]


class TotalsCostOut(TotalsOut):
    cost_total: Decimal | None  # None: no system-priced lines
    margin_amount: Decimal | None


class BoqOut(BaseModel):
    sections: list[SectionOut]
    lines: list[LineOut | LineCostOut]
    totals: TotalsOut | TotalsCostOut


class RateSource(BaseModel):
    channel: str | None  # the library folder: a salesperson, partner or manufacturer route
    file: str
    date: date | None  # the library has no BOQ dates yet
    rate: Decimal


class RateHistoryOut(BaseModel):
    """Why a library candidate has its rate: selling-rate history, for anyone with tender.view."""

    policy: str
    used: str
    latest_rate: Decimal | None
    median_rate: Decimal | None
    n_boqs: int
    channel_last_rate: Decimal | None
    sources: list[RateSource]
    sources_total: int
    above_median_percent: Decimal | None
    warning: bool  # more than 15% above the median


class RateHistoryCostOut(RateHistoryOut):
    min_rate: Decimal | None
    max_rate: Decimal | None


class CandidateOut(BaseModel):
    id: int
    rank: int
    rate: Decimal
    score: Decimal
    reason: str
    details: RateHistoryOut | None


class CandidateCostOut(CandidateOut):
    source: str
    ref_id: int
    cost_rate: Decimal | None
    margin_percent: Decimal | None
    details: RateHistoryCostOut | None


class LineDetailOut(BaseModel):
    line: LineOut | LineCostOut
    candidates: list[CandidateOut | CandidateCostOut]


class LineDetailCostOut(LineDetailOut):
    library_stats: list[dict[str, Any]]  # min / median / max per library item involved
    system_breakdown: dict[str, Any] | None


class LineIn(BaseModel):
    section_id: int | None = None
    after_line_id: int | None = None  # insert after this line (default: at the end)
    client_item_no: str | None = Field(default=None, max_length=50)
    description: str = Field(min_length=1)
    unit: str | None = Field(default=None, max_length=50)
    qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    qty_note: QtyNote | None = None
    our_remarks: str | None = None
    our_product: str | None = None


class LineUpdate(BaseModel):
    id: int
    section_id: int | None = None
    sort_order: int | None = None
    client_item_no: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, min_length=1)
    unit: str | None = Field(default=None, max_length=50)
    qty: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    qty_note: QtyNote | None = None
    client_product: str | None = None
    client_remarks: str | None = None
    our_remarks: str | None = None
    our_product: str | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    margin_percent: Percent | None = None
    status: Literal["unpriced", "not_quoted"] | None = None


class LinesUpdate(BaseModel):
    """One request = one save = one audit row, however many lines changed."""

    lines: list[LineUpdate] = Field(min_length=1, max_length=2000)


class LineIds(BaseModel):
    line_ids: list[int] = Field(min_length=1)


class AcceptIn(BaseModel):
    line_ids: list[int] | None = None
    min_score: Decimal | None = Field(default=None, ge=0, le=1)  # "accept all above X"


class UseCandidateIn(BaseModel):
    candidate_id: int


class MarginIn(BaseModel):
    margin_percent: Percent
    line_ids: list[int] | None = None  # default: every system-priced line


class SectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    note: str | None = None
    sort_order: int | None = None


class SectionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = None
    sort_order: int | None = None


class SuggestOut(BaseModel):
    lines_considered: int
    suggested: int
    left_unpriced: int
    skipped_priced: int
    threshold: Decimal


# --- import ---


class ColumnGuess(BaseModel):
    column: int
    letter: str
    header: str
    confidence: float
    alternatives: list[str] = []


class SheetOut(BaseModel):
    name: str
    header_row: int
    score: float


class ImportPreviewOut(BaseModel):
    upload_id: str
    filename: str
    sheets: list[SheetOut]
    sheet: str
    header_row: int
    header: list[dict[str, Any]]  # [{column, letter, text}]
    column_map: dict[str, ColumnGuess]
    rows: list[dict[str, Any]]
    counts: dict[str, Any]
    existing_lines: int
    page_count: int | None = None  # PDF imports


class ImportPreviewIn(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sheet: str
    header_row: int = Field(ge=1, le=1000)
    column_map: dict[str, int | None] | None = None  # None: guess from that header row


class ImportConfirmIn(ImportPreviewIn):
    column_map: dict[str, int | None]
    replace: bool = False


class ImportReportOut(BaseModel):
    import_id: int
    lines: int
    sections: int
    qro: int
    nq: int
    skipped: int
    skipped_by_reason: dict[str, int]
    unrecognised_units: dict[str, int]
    kept_prices: int


# --- T&C ---


class TenderTcOut(BaseModel):
    id: int
    clause_id: int | None
    category: str | None
    text: str
    text_override: str | None
    sort_order: int


class TenderTcItem(BaseModel):
    clause_id: int | None = None
    text_override: str | None = None

    @model_validator(mode="after")
    def _text(self):
        if self.clause_id is None and not (self.text_override or "").strip():
            raise ValueError("Each item needs a library clause or its own text")
        return self


class TenderTcIn(BaseModel):
    items: list[TenderTcItem]


# --- revisions ---


class SubmitIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RevisionOut(BaseModel):
    rev_no: int
    label: str
    submitted_at: datetime
    submitted_by_name: str | None
    note: str | None
    subtotal: Decimal
    grand_total: Decimal
    lines: int


class CompareLine(BaseModel):
    item_no: str | None
    description: str
    change: Literal["added", "removed", "changed", "same"]
    rate_a: Decimal | None
    rate_b: Decimal | None
    rate_delta: Decimal | None
    amount_a: Decimal | None
    amount_b: Decimal | None
    amount_delta: Decimal | None


class CompareOut(BaseModel):
    a: str
    b: str
    lines: list[CompareLine]
    subtotal_a: Decimal
    subtotal_b: Decimal
    subtotal_delta: Decimal
    grand_total_a: Decimal
    grand_total_b: Decimal
    grand_total_delta: Decimal
