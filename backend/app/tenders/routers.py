"""Tender register, BOQ editor, client BOQ import and auto-pricing.

Permissions: tender.view / tender.edit with their scope (all | assigned: owner or member |
own: created by the caller); a tender outside the caller's view scope is a 404. Cost data only
goes to callers with tender.margin (see schemas.py).
"""

import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, Principal, require_permission
from app.config import settings
from app.db import DbSession
from app.export import EXPORT_ROW_LIMIT, xlsx_response
from app.masters.models import Channel, Client, LibraryItem, System, TcClause, TcTemplate
from app.masters.rate import MissingPriceError, system_rate
from app.masters.routers.common import Limit, Offset, Search, like, paginate, unprocessable
from app.masters.schemas import Page
from app.masters.units import load_aliases, normalise_unit
from app.models import User
from app.tenders import boq_import, export, pricing, revisions
from app.tenders.models import (
    BoqImport,
    BoqLine,
    BoqLineCandidate,
    BoqSection,
    Tender,
    TenderMember,
    TenderRevision,
    TenderTc,
)
from app.tenders.pdf_import import ScannedPdfError
from app.tenders.schemas import (
    AcceptIn,
    BoqOut,
    CandidateCostOut,
    CandidateOut,
    ColumnGuess,
    CompareOut,
    ImportConfirmIn,
    ImportPreviewIn,
    ImportPreviewOut,
    ImportReportOut,
    LineCostOut,
    LineDetailCostOut,
    LineDetailOut,
    LineIds,
    LineIn,
    LineOut,
    LinesUpdate,
    MarginIn,
    MemberOut,
    RateHistoryCostOut,
    RateHistoryOut,
    RevisionOut,
    SectionIn,
    SectionOut,
    SectionUpdate,
    SheetOut,
    SubmitIn,
    SuggestOut,
    TenderCostOut,
    TenderIn,
    TenderOut,
    TenderTcIn,
    TenderTcOut,
    TenderUpdate,
    TotalsCostOut,
    TotalsOut,
    UseCandidateIn,
)
from app.tenders.service import (
    check_edit,
    clause_text,
    copy_template,
    get_visible,
    next_code,
    scope_condition,
)

router = APIRouter(prefix="/api/tenders", tags=["tenders"])

ViewScope = Annotated[str, Depends(require_permission("tender.view"))]
EditScope = Annotated[str, Depends(require_permission("tender.edit"))]

UPLOAD_MAX_BYTES = 20 * 1024 * 1024
UPLOAD_TYPES = (".xlsx", ".xlsm", ".xls", ".csv", ".pdf")
SORT_STEP = 10


def can_cost(principal: Principal) -> bool:
    return "tender.margin" in principal.permissions


def _record(db, request, principal, action, tender, before=None, after=None):
    audit.record(
        db,
        action,
        "tender",
        tender.id,
        user_id=principal.user.id,
        before=before,
        after=after,
        ip=audit.client_ip(request),
    )


def _editable(db, tender_id, view, edit, principal, request: Request | None = None) -> Tender:
    """The tender, if the caller may change it. Pass the request when the call changes the BOQ
    or the T&C: if the current revision was submitted, the change starts the next revision."""
    tender = get_visible(db, tender_id, view, principal)
    check_edit(tender, edit, principal)
    if request is not None:
        started = revisions.start_next_if_frozen(db, tender)
        if started:
            _record(
                db,
                request,
                principal,
                "tender.revision.start",
                tender,
                before={"revision": revisions.label(started[0]), "status": "submitted"},
                after={"revision": revisions.label(started[1]), "status": tender.status},
            )
    return tender


# --- shapes ------------------------------------------------------------------------------------


def _tender_out(db: Session, tender: Tender, with_cost: bool) -> TenderOut:
    data = dict(
        id=tender.id,
        code=tender.code,
        name=tender.name,
        client_id=tender.client_id,
        client_name=tender.client.name if tender.client else None,
        channel_id=tender.channel_id,
        channel_name=tender.channel.name if tender.channel else None,
        site_name=tender.site_name,
        site_city=tender.site_city,
        site_state=tender.site_state,
        received_on=tender.received_on,
        due_on=tender.due_on,
        overdue=bool(tender.due_on and tender.due_on < date.today() and tender.status == "draft"),
        owner_id=tender.owner_id,
        owner_name=tender.owner.full_name if tender.owner else None,
        members=[MemberOut(user_id=m.user_id, full_name=m.user.full_name) for m in tender.members],
        status=tender.status,
        lost_reason=tender.lost_reason,
        lost_to=tender.lost_to,
        quoted_total=tender.quoted_total,
        tc_template_id=tender.tc_template_id,
        notes=tender.notes,
        created_at=tender.created_at,
        revision=tender.revision,
        revision_label=revisions.revision_label(db, tender),
        submitted_revisions=revisions.submitted_count(db, tender),
        site_id=db.scalar(text("SELECT id FROM sites WHERE tender_id = :t"), {"t": tender.id}),
    )
    if not with_cost:
        return TenderOut(**data)
    totals = pricing.tender_totals(db, tender)
    return TenderCostOut(**data, cost_total=totals.cost_total, margin_amount=totals.margin_total)


_PUBLIC_LINE = list(LineOut.model_fields)
_COST_LINE = list(LineCostOut.model_fields)


def _line_out(line: BoqLine, with_cost: bool) -> LineOut:
    if with_cost:
        return LineCostOut(**{f: getattr(line, f) for f in _COST_LINE})
    return LineOut(**{f: getattr(line, f) for f in _PUBLIC_LINE})


def _candidate_out(c: BoqLineCandidate, with_cost: bool) -> CandidateOut:
    base = dict(id=c.id, rank=c.rank, rate=c.rate, score=c.score, reason=c.reason)
    history = c.details or None
    if with_cost:
        return CandidateCostOut(
            **base,
            source=c.source,
            ref_id=c.ref_id,
            cost_rate=c.cost_rate,
            margin_percent=c.margin_percent,
            details=RateHistoryCostOut(**history) if history else None,
        )
    public = (
        {k: v for k, v in history.items() if k in RateHistoryOut.model_fields} if history else None
    )
    return CandidateOut(**base, details=RateHistoryOut(**public) if public else None)


def _boq(db: Session, tender: Tender, with_cost: bool) -> BoqOut:
    totals = pricing.tender_totals(db, tender)
    sections = db.scalars(
        select(BoqSection).where(BoqSection.tender_id == tender.id).order_by(BoqSection.sort_order)
    )
    lines = db.scalars(
        select(BoqLine)
        .where(BoqLine.tender_id == tender.id)
        .order_by(BoqLine.sort_order, BoqLine.id)
    )
    base = dict(
        subtotal=totals.subtotal,
        gst_percent=totals.gst_percent,
        gst=totals.gst,
        grand_total=totals.grand_total,
        counts=totals.counts,
    )
    return BoqOut(
        sections=[
            SectionOut(
                id=s.id,
                title=s.title,
                note=s.note,
                sort_order=s.sort_order,
                total=totals.sections.get(s.id, Decimal(0)),
            )
            for s in sections
        ],
        lines=[_line_out(ln, with_cost) for ln in lines],
        totals=TotalsCostOut(
            **base, cost_total=totals.cost_total, margin_amount=totals.margin_total
        )
        if with_cost
        else TotalsOut(**base),
    )


def _snapshot(tender: Tender) -> dict:
    data = audit.model_snapshot(tender)
    data["member_ids"] = sorted(str(m.user_id) for m in tender.members)
    return data


# --- register ------------------------------------------------------------------------------------


def _list_query(scope, principal, q, status_, owner_id, client_id, channel_id=None):
    query = select(Tender).where(scope_condition(scope, principal))
    if q:
        pattern = like(q)
        query = (
            query.outerjoin(Client, Client.id == Tender.client_id)
            .outerjoin(Channel, Channel.id == Tender.channel_id)
            .where(
                or_(
                    Tender.name.ilike(pattern),
                    Tender.code.ilike(pattern),
                    Client.name.ilike(pattern),
                    Channel.name.ilike(pattern),
                    Tender.site_name.ilike(pattern),
                )
            )
        )
    if status_:
        query = query.where(Tender.status == status_)
    if owner_id:
        query = query.where(Tender.owner_id == owner_id)
    if client_id:
        query = query.where(Tender.client_id == client_id)
    if channel_id:
        query = query.where(Tender.channel_id == channel_id)
    return query.order_by(Tender.created_at.desc(), Tender.id.desc())


@router.get("")
def list_tenders(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    client_id: int | None = None,
    channel_id: int | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[TenderOut | TenderCostOut]:
    rows, total = paginate(
        db,
        _list_query(scope, principal, q, status, owner_id, client_id, channel_id),
        limit,
        offset,
    )
    with_cost = can_cost(principal)
    return Page(
        items=[_tender_out(db, t, with_cost) for t in rows], total=total, limit=limit, offset=offset
    )


@router.get("/export")
def export_tenders(
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    q: Search = None,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    client_id: int | None = None,
    channel_id: int | None = None,
):
    with_cost = can_cost(principal)
    query = _list_query(scope, principal, q, status, owner_id, client_id, channel_id).limit(
        EXPORT_ROW_LIMIT
    )
    tenders = [_tender_out(db, t, with_cost) for t in db.scalars(query)]
    columns = [
        "Code",
        "Name",
        "Client",
        "Channel",
        "Site",
        "City",
        "Received",
        "Due",
        "Owner",
        "Status",
        "Quoted total",
        "Lost reason",
        "Lost to",
    ]
    if with_cost:
        columns += ["Cost total", "Margin"]
    rows = []
    for t in tenders:
        row = [
            t.code,
            t.name,
            t.client_name,
            t.channel_name,
            t.site_name,
            t.site_city,
            t.received_on,
            t.due_on,
            t.owner_name,
            t.status,
            t.quoted_total,
            t.lost_reason,
            t.lost_to,
        ]
        if with_cost:
            row += [t.cost_total, t.margin_amount]
        rows.append(row)
    return xlsx_response("tenders", columns, rows)


def _check_users(db: Session, ids: list[uuid.UUID]) -> None:
    found = set(db.scalars(select(User.id).where(User.id.in_(ids)))) if ids else set()
    if found != set(ids):
        raise unprocessable("Unknown user id")


@router.get("/lookups")
def lookups(db: DbSession, _: EditScope) -> dict[str, list[dict[str, Any]]]:
    """Choices for the tender form (clients, channels, people, T&C templates) for anyone who
    may create tenders, without needing the client or user admin permissions."""
    clients = db.execute(
        select(Client.id, Client.name).where(Client.is_active).order_by(Client.name)
    ).all()
    channels = db.execute(
        select(Channel.id, Channel.name, Channel.type)
        .where(Channel.is_active)
        .order_by(Channel.name)
    ).all()
    users = db.execute(
        select(User.id, User.full_name).where(User.is_active).order_by(User.full_name)
    ).all()
    templates = db.execute(
        select(TcTemplate.id, TcTemplate.name, TcTemplate.is_default).order_by(TcTemplate.name)
    ).all()
    return {
        "clients": [{"id": c.id, "name": c.name} for c in clients],
        "channels": [{"id": c.id, "name": c.name, "type": c.type} for c in channels],
        "users": [{"id": str(u.id), "full_name": u.full_name} for u in users],
        "tc_templates": [
            {"id": t.id, "name": t.name, "is_default": t.is_default} for t in templates
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tender(
    body: TenderIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: EditScope
) -> TenderOut | TenderCostOut:
    if body.client_id is not None and db.get(Client, body.client_id) is None:
        raise unprocessable("Unknown client")
    if body.channel_id is not None and db.get(Channel, body.channel_id) is None:
        raise unprocessable("Unknown channel")
    owner = body.owner_id or principal.user.id
    _check_users(db, [owner, *body.member_ids])
    tender = Tender(
        code=next_code(db, body.received_on),
        **body.model_dump(exclude={"owner_id", "member_ids", "tc_template_id"}),
        owner_id=owner,
        created_by=principal.user.id,
        members=[
            TenderMember(user_id=uid, created_by=principal.user.id)
            for uid in dict.fromkeys(body.member_ids)
        ],
    )
    db.add(tender)
    db.flush()
    copy_template(db, tender, body.tc_template_id, principal.user.id)
    db.flush()
    _record(db, request, principal, "tender.create", tender, after=_snapshot(tender))
    db.commit()
    db.refresh(tender)
    return _tender_out(db, tender, can_cost(principal))


@router.get("/{tender_id}")
def get_tender(
    tender_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> TenderOut | TenderCostOut:
    return _tender_out(db, get_visible(db, tender_id, scope, principal), can_cost(principal))


@router.patch("/{tender_id}")
def update_tender(
    tender_id: int,
    body: TenderUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> TenderOut | TenderCostOut:
    tender = _editable(db, tender_id, view, edit, principal)
    before = _snapshot(tender)
    changes = body.model_dump(exclude_unset=True, exclude={"member_ids"})
    if changes.get("client_id") is not None and db.get(Client, changes["client_id"]) is None:
        raise unprocessable("Unknown client")
    if changes.get("channel_id") is not None and db.get(Channel, changes["channel_id"]) is None:
        raise unprocessable("Unknown channel")
    client_after = changes.get("client_id", tender.client_id)
    channel_after = changes.get("channel_id", tender.channel_id)
    if client_after is None and channel_after is None:
        raise unprocessable("A tender needs a client, a channel, or both")
    if changes.get("owner_id"):
        _check_users(db, [changes["owner_id"]])
    submitting = body.status == "submitted" and tender.status != "submitted"
    for field, value in changes.items():
        if field in ("name", "status") and value is None:
            continue
        if field == "status" and submitting:
            continue  # below, through revisions.submit
        setattr(tender, field, value)
    if body.status in ("draft", "submitted"):
        tender.lost_reason = tender.lost_to = None
    if body.member_ids is not None:
        _check_users(db, body.member_ids)
        tender.members = []
        db.flush()
        tender.members = [
            TenderMember(user_id=uid, created_by=principal.user.id)
            for uid in dict.fromkeys(body.member_ids)
        ]
    db.flush()
    if submitting:
        revision = revisions.submit(db, tender, principal.user.id, None)
        _record(
            db,
            request,
            principal,
            "tender.submit",
            tender,
            after={"revision": revisions.label(revision.rev_no)},
        )
    after = _snapshot(tender)
    if after != before:
        action = "tender.status" if before["status"] != after["status"] else "tender.update"
        _record(db, request, principal, action, tender, before, after)
    db.commit()
    db.refresh(tender)
    return _tender_out(db, tender, can_cost(principal))


# --- BOQ grid ------------------------------------------------------------------------------------


@router.get("/{tender_id}/boq")
def get_boq(tender_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope) -> BoqOut:
    return _boq(db, get_visible(db, tender_id, scope, principal), can_cost(principal))


def _next_sort(db: Session, tender: Tender) -> int:
    current = db.scalar(select(func.max(BoqLine.sort_order)).where(BoqLine.tender_id == tender.id))
    return (current or 0) + SORT_STEP


@router.post("/{tender_id}/sections", status_code=status.HTTP_201_CREATED)
def add_section(
    tender_id: int,
    body: SectionIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    if body.sort_order is None:
        current = db.scalar(
            select(func.max(BoqSection.sort_order)).where(BoqSection.tender_id == tender.id)
        )
        body.sort_order = (current or 0) + SORT_STEP
    section = BoqSection(
        tender_id=tender.id,
        title=body.title.strip(),
        note=(body.note or "").strip() or None,
        sort_order=body.sort_order,
        created_by=principal.user.id,
    )
    db.add(section)
    db.flush()
    _record(
        db,
        request,
        principal,
        "tender.section.create",
        tender,
        after={"section_id": section.id, "title": section.title},
    )
    db.commit()
    return _boq(db, tender, can_cost(principal))


def _section(db: Session, tender: Tender, section_id: int) -> BoqSection:
    section = db.get(BoqSection, section_id)
    if section is None or section.tender_id != tender.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return section


@router.patch("/{tender_id}/sections/{section_id}")
def update_section(
    tender_id: int,
    section_id: int,
    body: SectionUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    section = _section(db, tender, section_id)
    before = {"title": section.title, "note": section.note, "sort_order": section.sort_order}
    if body.title is not None:
        section.title = body.title.strip()
    if "note" in body.model_fields_set:
        section.note = (body.note or "").strip() or None
    if body.sort_order is not None:
        section.sort_order = body.sort_order
    _record(
        db,
        request,
        principal,
        "tender.section.update",
        tender,
        before,
        {"title": section.title, "note": section.note, "sort_order": section.sort_order},
    )
    db.commit()
    return _boq(db, tender, can_cost(principal))


@router.delete("/{tender_id}/sections/{section_id}")
def delete_section(
    tender_id: int,
    section_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    """Removes the heading; its lines stay, without a section."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    section = _section(db, tender, section_id)
    _record(
        db,
        request,
        principal,
        "tender.section.delete",
        tender,
        before={"section_id": section.id, "title": section.title},
    )
    db.delete(section)
    db.commit()
    return _boq(db, tender, can_cost(principal))


@router.post("/{tender_id}/lines", status_code=status.HTTP_201_CREATED)
def add_line(
    tender_id: int,
    body: LineIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    if body.section_id is not None:
        _section(db, tender, body.section_id)
    if body.after_line_id is not None:
        after = _line(db, tender, body.after_line_id)
        sort_order = after.sort_order + 1
        db.execute(
            BoqLine.__table__.update()
            .where(BoqLine.tender_id == tender.id, BoqLine.sort_order >= sort_order)
            .values(sort_order=BoqLine.sort_order + SORT_STEP)
        )
    else:
        sort_order = _next_sort(db, tender)
    unit = normalise_unit(body.unit, load_aliases(db)) if body.unit else None
    line = BoqLine(
        tender_id=tender.id,
        section_id=body.section_id,
        sort_order=sort_order,
        client_item_no=body.client_item_no,
        description=body.description.strip(),
        unit=unit,
        unit_raw=body.unit,
        qty=body.qty,
        qty_note=body.qty_note,
        our_remarks=body.our_remarks,
        our_product=body.our_product,
        status="not_quoted" if body.qty_note == "NQ" else "unpriced",
        created_by=principal.user.id,
    )
    db.add(line)
    db.flush()
    _record(
        db,
        request,
        principal,
        "tender.line.create",
        tender,
        after={"line_id": line.id, "description": line.description[:200]},
    )
    db.commit()
    return _boq(db, tender, can_cost(principal))


def _line(db: Session, tender: Tender, line_id: int) -> BoqLine:
    line = db.get(BoqLine, line_id)
    if line is None or line.tender_id != tender.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
    return line


_AUDITED = (
    "section_id",
    "sort_order",
    "client_item_no",
    "description",
    "unit",
    "qty",
    "qty_note",
    "client_product",
    "client_remarks",
    "our_remarks",
    "our_product",
    "rate",
    "margin_percent",
    "status",
    "source",
)


def _line_state(line: BoqLine) -> dict:
    return {f: getattr(line, f) for f in _AUDITED}


@router.patch("/{tender_id}/lines")
def update_lines(
    tender_id: int,
    body: LinesUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    """Save edits to many lines at once: one request, one audit row.

    rate: typed rate -> manual price, status priced; rate null -> unpriced.
    margin_percent: only for system-priced lines (rate recalculated from cost).
    status not_quoted / unpriced: mark a line NQ, or bring it back."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    if "margin_percent" in str(body.model_fields_set) or any(
        "margin_percent" in u.model_fields_set for u in body.lines
    ):
        if not can_cost(principal):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: tender.margin")
    aliases = load_aliases(db)
    changes: dict[int, dict] = {}
    for update in body.lines:
        line = _line(db, tender, update.id)
        before = _line_state(line)
        fields = update.model_dump(exclude_unset=True, exclude={"id"})
        if "section_id" in fields and fields["section_id"] is not None:
            _section(db, tender, fields["section_id"])
        for name in (
            "section_id",
            "sort_order",
            "client_item_no",
            "client_product",
            "client_remarks",
            "our_remarks",
            "our_product",
        ):
            if name in fields and (fields[name] is not None or name != "sort_order"):
                setattr(line, name, fields[name])
        if fields.get("description"):
            line.description = fields["description"].strip()
        if "unit" in fields:
            line.unit_raw = fields["unit"]
            line.unit = normalise_unit(fields["unit"], aliases) if fields["unit"] else None
        if "qty" in fields:
            line.qty = fields["qty"]
        if "qty_note" in fields:
            line.qty_note = fields["qty_note"]
            if line.qty_note == "NQ":
                pricing.clear_pricing(line)
                line.status = "not_quoted"
        if fields.get("status") == "not_quoted":
            pricing.clear_pricing(line)
            line.qty_note, line.status = "NQ", "not_quoted"
        elif fields.get("status") == "unpriced":
            if line.qty_note == "NQ":
                line.qty_note = None
            pricing.clear_pricing(line)
        if "rate" in fields:
            if fields["rate"] is None:
                pricing.clear_pricing(line)
            elif line.status == "not_quoted":
                raise unprocessable(f"Line {line.id} is not quoted; set it back to unpriced first")
            else:
                line.rate = fields["rate"]
                line.source, line.margin_percent, line.status = "manual", None, "priced"
                line.system_id = None if line.cost_rate is None else line.system_id
        if fields.get("margin_percent") is not None:
            if not pricing.apply_margin(line, fields["margin_percent"]):
                raise unprocessable(f"Line {line.id}: a margin applies only to system-priced lines")
        pricing.refresh_amount(line)
        after = _line_state(line)
        diff = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
        if diff:
            changes[line.id] = diff
    if changes:
        pricing.refresh_tender_total(db, tender)
        _record(
            db,
            request,
            principal,
            "tender.lines.update",
            tender,
            after={"lines": len(changes), "changes": changes},
        )
    db.commit()
    return _boq(db, tender, can_cost(principal))


@router.post("/{tender_id}/lines/delete")
def delete_lines(
    tender_id: int,
    body: LineIds,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    lines = [_line(db, tender, i) for i in dict.fromkeys(body.line_ids)]
    _record(
        db,
        request,
        principal,
        "tender.lines.delete",
        tender,
        before={
            "lines": [
                {
                    "id": ln.id,
                    "item_no": ln.client_item_no,
                    "description": ln.description[:200],
                    "rate": ln.rate,
                }
                for ln in lines
            ]
        },
    )
    for line in lines:
        db.delete(line)
    pricing.refresh_tender_total(db, tender)
    db.commit()
    return _boq(db, tender, can_cost(principal))


@router.get("/{tender_id}/lines/{line_id}")
def line_detail(
    tender_id: int, line_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> LineDetailOut | LineDetailCostOut:
    """The row side panel: candidates, and with tender.margin the library min/median/max and the
    system build-up."""
    tender = get_visible(db, tender_id, scope, principal)
    line = _line(db, tender, line_id)
    with_cost = can_cost(principal)
    base = dict(
        line=_line_out(line, with_cost),
        candidates=[_candidate_out(c, with_cost) for c in line.candidates],
    )
    if not with_cost:
        return LineDetailOut(**base)
    library_ids = {c.ref_id for c in line.candidates if c.source == "library"}
    if line.library_item_id:
        library_ids.add(line.library_item_id)
    stats = (
        [
            {
                "library_item_id": i.id,
                "description": i.description[:300],
                "unit": i.unit,
                "boq_count": i.boq_count,
                "latest_rate": i.latest_rate,
                "min_rate": i.min_rate,
                "median_rate": i.median_rate,
                "max_rate": i.max_rate,
                "latest_channel": i.latest_channel,
            }
            for i in db.scalars(select(LibraryItem).where(LibraryItem.id.in_(library_ids)))
        ]
        if library_ids
        else []
    )
    breakdown = None
    system_id = line.system_id or next(
        (c.ref_id for c in line.candidates if c.source == "system"), None
    )
    if system_id and (system := db.get(System, system_id)):
        try:
            b = system_rate(db, system, line.margin_percent if line.system_id else None)
            breakdown = {
                "system_id": system.id,
                "code": system.code,
                "name": system.name,
                "unit": b.unit,
                "components": [
                    {
                        "product": c.product_name,
                        "qty": c.quantity_with_wastage,
                        "landed_rate": c.landed_rate,
                        "cost": c.cost,
                    }
                    for c in b.components
                ],
                "material_cost": b.material_cost,
                "surface_prep": b.surface_prep,
                "labour_per_unit": b.labour_per_unit,
                "base_cost": b.base_cost,
                "margin_percent": b.margin_percent,
                "rate": b.rate,
            }
        except MissingPriceError as exc:
            breakdown = {"system_id": system.id, "name": system.name, "error": str(exc)}
    return LineDetailCostOut(**base, library_stats=stats, system_breakdown=breakdown)


@router.post("/{tender_id}/lines/{line_id}/use-candidate")
def use_candidate(
    tender_id: int,
    line_id: int,
    body: UseCandidateIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    line = _line(db, tender, line_id)
    candidate = next((c for c in line.candidates if c.id == body.candidate_id), None)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    if line.status == "not_quoted":
        raise unprocessable("This line is not quoted")
    before = _line_state(line)
    pricing.use_candidate(line, candidate, status="priced")
    pricing.refresh_tender_total(db, tender)
    _record(
        db,
        request,
        principal,
        "tender.lines.update",
        tender,
        after={
            "lines": 1,
            "changes": {
                line.id: {"used_candidate": candidate.id, "rate": [before["rate"], line.rate]}
            },
        },
    )
    db.commit()
    return _boq(db, tender, can_cost(principal))


# --- pricing -------------------------------------------------------------------------------------


@router.post("/{tender_id}/boq/suggest")
def suggest(
    tender_id: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> SuggestOut:
    tender = _editable(db, tender_id, view, edit, principal, request)
    result = pricing.suggest(db, tender, user_id=principal.user.id)
    _record(db, request, principal, "tender.boq.suggest", tender, after=vars(result))
    db.commit()
    return SuggestOut(**vars(result))


@router.post("/{tender_id}/boq/accept")
def accept(
    tender_id: int,
    body: AcceptIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    """Accept suggestions: the given lines, or every suggestion scoring at least min_score."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    query = select(BoqLine).where(BoqLine.tender_id == tender.id, BoqLine.status == "suggested")
    if body.line_ids:
        query = query.where(BoqLine.id.in_(body.line_ids))
    if body.min_score is not None:
        query = query.where(BoqLine.suggestion_score >= body.min_score)
    accepted = []
    for line in db.scalars(query):
        line.status = "priced"
        accepted.append(line.id)
    if accepted:
        _record(
            db,
            request,
            principal,
            "tender.boq.accept",
            tender,
            after={"lines": len(accepted), "line_ids": accepted, "min_score": body.min_score},
        )
    db.commit()
    return _boq(db, tender, can_cost(principal))


@router.post("/{tender_id}/boq/margin", dependencies=[Depends(require_permission("tender.margin"))])
def apply_margin(
    tender_id: int,
    body: MarginIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> BoqOut:
    """Set one margin on every system-priced line (or the given lines). Library and manual lines
    have no cost and are left alone."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    query = select(BoqLine).where(BoqLine.tender_id == tender.id, BoqLine.source == "system")
    if body.line_ids:
        query = query.where(BoqLine.id.in_(body.line_ids))
    changed = [ln.id for ln in db.scalars(query) if pricing.apply_margin(ln, body.margin_percent)]
    pricing.refresh_tender_total(db, tender)
    _record(
        db,
        request,
        principal,
        "tender.boq.margin",
        tender,
        after={"margin_percent": body.margin_percent, "lines": len(changed)},
    )
    db.commit()
    return _boq(db, tender, can_cost(principal))


# --- client BOQ import ---------------------------------------------------------------------------


def _upload_dir(tender: Tender) -> Path:
    return Path(settings.media_dir) / "tenders" / str(tender.id) / "uploads"


def _find_upload(tender: Tender, upload_id: str) -> Path:
    matches = list(_upload_dir(tender).glob(f"{upload_id}__*"))
    if not matches:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found; upload the file again")
    return matches[0]


def _original_name(path: Path) -> str:
    return path.name.split("__", 1)[1]


def _pages(grid: dict, sheet: str) -> list[tuple[int, int]] | None:
    return getattr(grid, "pages", {}).get(sheet)


def _preview(
    db: Session,
    tender: Tender,
    path: Path,
    sheet: str | None,
    header_row: int | None,
    column_map: dict[str, int | None] | None,
) -> ImportPreviewOut:
    try:
        grid = boq_import.read_grid(path)
    except (boq_import.BoqFormatError, ScannedPdfError) as exc:
        raise unprocessable(str(exc)) from exc
    except Exception as exc:  # a corrupt or unreadable spreadsheet or PDF
        raise unprocessable(f"Could not read the file: {exc}") from exc
    sheets = boq_import.choose_sheet(grid)
    if not sheets:
        raise unprocessable("The file has no visible sheets")
    chosen = next((s for s in sheets if s["name"] == sheet), None) if sheet else sheets[0]
    if chosen is None:
        raise unprocessable(f"No sheet named {sheet!r}")
    rows = grid[chosen["name"]]
    header_row = header_row or chosen["header_row"]
    if header_row > len(rows):
        raise unprocessable("The header row is past the end of the sheet")
    header_values = rows[header_row - 1]
    guesses = boq_import.header_guess(rows, header_row - 1)
    if column_map is not None:
        cols = {f: c for f, c in column_map.items() if c is not None and f in boq_import.FIELDS}
        guesses = {
            f: {
                "column": c,
                "letter": boq_import.column_letter(c),
                "header": str(header_values[c]).strip()
                if c < len(header_values) and header_values[c] is not None
                else "",
                "confidence": 1.0,
                "alternatives": [],
            }
            for f, c in cols.items()
        }
    cols = {f: g["column"] for f, g in guesses.items()}
    try:
        parsed = boq_import.parse(rows, header_row, cols, load_aliases(db))
    except boq_import.BoqFormatError as exc:
        raise unprocessable(str(exc)) from exc
    existing = db.scalar(select(func.count()).where(BoqLine.tender_id == tender.id))
    return ImportPreviewOut(
        upload_id=path.name.split("__")[0],
        filename=_original_name(path),
        sheets=[
            SheetOut(name=s["name"], header_row=s["header_row"], score=s["score"]) for s in sheets
        ],
        sheet=chosen["name"],
        header_row=header_row,
        header=[
            {"column": i, "letter": boq_import.column_letter(i), "text": str(v).strip()}
            for i, v in enumerate(header_values)
            if v not in (None, "")
        ],
        column_map={f: ColumnGuess(**g) for f, g in guesses.items()},
        rows=boq_import.preview_rows(parsed, pages=_pages(grid, chosen["name"])),
        counts=parsed.counts(),
        page_count=getattr(grid, "page_count", None),
        existing_lines=existing,
    )


@router.post("/{tender_id}/boq/import")
async def upload_boq(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
    file: Annotated[
        UploadFile, File(description=".xlsx, .xls, .csv or a text PDF (60 pages), up to 20 MB")
    ],
) -> ImportPreviewOut:
    """Upload a client BOQ and get a preview with guessed settings. Nothing is saved to the BOQ
    until /boq/import/confirm."""
    tender = _editable(db, tender_id, view, edit, principal)
    name = Path(file.filename or "boq.xlsx").name
    if Path(name).suffix.lower() not in UPLOAD_TYPES:
        raise unprocessable("Upload an .xlsx, .xls, .csv or .pdf file")
    data = await file.read(UPLOAD_MAX_BYTES + 1)
    if len(data) > UPLOAD_MAX_BYTES:
        raise unprocessable("The file is larger than 20 MB")
    folder = _upload_dir(tender)
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", name)[:150]
    path = folder / f"{uuid.uuid4().hex}__{safe}"
    path.write_bytes(data)
    return _preview(db, tender, path, None, None, None)


@router.post("/{tender_id}/boq/import/preview")
def preview_boq(
    tender_id: int,
    body: ImportPreviewIn,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> ImportPreviewOut:
    """Re-read the uploaded file with another sheet, header row or column map."""
    tender = _editable(db, tender_id, view, edit, principal)
    return _preview(
        db,
        tender,
        _find_upload(tender, body.upload_id),
        body.sheet,
        body.header_row,
        body.column_map,
    )


def _key(item_no: str | None, description: str) -> tuple[str, str]:
    return ((item_no or "").strip().lower(), " ".join(description.lower().split()))


_KEPT = (
    "source",
    "system_id",
    "library_item_id",
    "cost_rate",
    "margin_percent",
    "rate",
    "suggestion_score",
    "our_remarks",
    "our_product",
    "status",
)


@router.post("/{tender_id}/boq/import/confirm")
def confirm_boq(
    tender_id: int,
    body: ImportConfirmIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> ImportReportOut:
    """Write the parsed sections and lines. A tender that already has lines needs replace=true;
    priced rates are then kept for lines whose (item no, description) match."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    path = _find_upload(tender, body.upload_id)
    existing = list(db.scalars(select(BoqLine).where(BoqLine.tender_id == tender.id)))
    if existing and not body.replace:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This tender already has {len(existing)} BOQ lines; import again with replace",
        )
    try:
        grid = boq_import.read_grid(path)
    except (boq_import.BoqFormatError, ScannedPdfError) as exc:
        raise unprocessable(str(exc)) from exc
    if body.sheet not in grid:
        raise unprocessable(f"No sheet named {body.sheet!r}")
    cols = {f: c for f, c in body.column_map.items() if c is not None and f in boq_import.FIELDS}
    try:
        parsed = boq_import.parse(grid[body.sheet], body.header_row, cols, load_aliases(db))
    except boq_import.BoqFormatError as exc:
        raise unprocessable(str(exc)) from exc
    pages = _pages(grid, body.sheet)

    kept: dict[tuple[str, str], dict[str, Any]] = {
        _key(ln.client_item_no, ln.description): {f: getattr(ln, f) for f in _KEPT}
        for ln in existing
        if ln.status == "priced"
    }
    for line in existing:
        db.delete(line)
    for section in db.scalars(select(BoqSection).where(BoqSection.tender_id == tender.id)):
        db.delete(section)
    db.flush()

    section_ids: dict[int, int] = {}
    order = 0
    kept_count = 0
    for kind, index in parsed.order:
        order += SORT_STEP
        if kind == "section":
            s = BoqSection(
                tender_id=tender.id,
                title=parsed.sections[index].title,
                note=parsed.sections[index].note,
                sort_order=order,
                created_by=principal.user.id,
            )
            db.add(s)
            db.flush()
            section_ids[index] = s.id
            continue
        p = parsed.lines[index]
        line = BoqLine(
            tender_id=tender.id,
            section_id=section_ids.get(p.section) if p.section is not None else None,
            sort_order=order,
            client_item_no=p.item_no,
            description=p.description,
            unit=p.unit,
            unit_raw=p.unit_raw,
            qty=p.qty,
            qty_note=p.qty_note,
            client_product=p.client_product,
            client_remarks=p.client_remarks,
            client_file_rate=p.client_file_rate,
            our_remarks=p.our_remarks,
            status=p.status,
            source_row=p.source_row,
            client_material_rate=p.client_material_rate,
            client_application_rate=p.client_application_rate,
            source_page=min(pages[r - 1][0] for r in p.rows) if pages else None,
            source_page_to=max(pages[r - 1][1] for r in p.rows) if pages else None,
            created_by=principal.user.id,
        )
        previous = kept.get(_key(p.item_no, p.description))
        if previous and line.status != "not_quoted":
            for f, v in previous.items():
                if v is not None or f in ("source", "rate"):
                    setattr(line, f, v)
            kept_count += 1
        pricing.refresh_amount(line)
        db.add(line)
    db.flush()
    counts = parsed.counts()
    record = BoqImport(
        tender_id=tender.id,
        filename=_original_name(path),
        stored_path=str(path.relative_to(settings.media_dir)),
        sheet=body.sheet,
        header_row=body.header_row,
        column_map=cols,
        row_count=len(grid[body.sheet]),
        report={**counts, "skipped_rows": parsed.skipped[:500], "kept_prices": kept_count},
        created_by=principal.user.id,
    )
    db.add(record)
    pricing.refresh_tender_total(db, tender)
    db.flush()
    _record(
        db,
        request,
        principal,
        "tender.boq.import",
        tender,
        before={"lines": len(existing)} if existing else None,
        after={
            "import_id": record.id,
            "file": record.filename,
            "sheet": body.sheet,
            **{k: counts[k] for k in ("lines", "sections", "qro", "nq", "skipped")},
            "kept_prices": kept_count,
        },
    )
    db.commit()
    return ImportReportOut(
        import_id=record.id,
        lines=counts["lines"],
        sections=counts["sections"],
        qro=counts["qro"],
        nq=counts["nq"],
        skipped=counts["skipped"],
        skipped_by_reason=counts["skipped_by_reason"],
        unrecognised_units=counts["unrecognised_units"],
        kept_prices=kept_count,
    )


# --- T&C -----------------------------------------------------------------------------------------


def _tc_out(db: Session, tender: Tender) -> list[TenderTcOut]:
    rows = db.execute(
        select(TenderTc, TcClause)
        .outerjoin(TcClause, TcClause.id == TenderTc.clause_id)
        .where(TenderTc.tender_id == tender.id)
        .order_by(TenderTc.sort_order, TenderTc.id)
    ).all()
    return [
        TenderTcOut(
            id=t.id,
            clause_id=t.clause_id,
            category=c.category if c else None,
            text=clause_text(c, t.text_override),
            text_override=t.text_override,
            sort_order=t.sort_order,
        )
        for t, c in rows
    ]


@router.get("/{tender_id}/tc")
def get_tc(
    tender_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> list[TenderTcOut]:
    return _tc_out(db, get_visible(db, tender_id, scope, principal))


@router.put("/{tender_id}/tc")
def set_tc(
    tender_id: int,
    body: TenderTcIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> list[TenderTcOut]:
    """Replace the tender's T&C list (order as sent). Text edits stay on this tender only; the
    library clause is never changed."""
    tender = _editable(db, tender_id, view, edit, principal, request)
    ids = [i.clause_id for i in body.items if i.clause_id is not None]
    clauses = (
        {c.id: c for c in db.scalars(select(TcClause).where(TcClause.id.in_(ids)))} if ids else {}
    )
    for cid in ids:
        clause = clauses.get(cid)
        if clause is None or clause.status != "active" or clause.merged_into_id is not None:
            raise unprocessable(f"Clause {cid} is not an active library clause")
    before = [{"clause_id": t.clause_id, "text": t.text} for t in _tc_out(db, tender)]
    for row in db.scalars(select(TenderTc).where(TenderTc.tender_id == tender.id)):
        db.delete(row)
    db.flush()
    for i, item in enumerate(body.items, start=1):
        override = (item.text_override or "").strip() or None
        if override and item.clause_id and override == clauses[item.clause_id].text:
            override = None
        db.add(
            TenderTc(
                tender_id=tender.id,
                clause_id=item.clause_id,
                sort_order=i,
                text_override=override,
                created_by=principal.user.id,
            )
        )
    db.flush()
    after = [{"clause_id": t.clause_id, "text": t.text} for t in _tc_out(db, tender)]
    if after != before:
        _record(
            db, request, principal, "tender.tc.update", tender, {"items": before}, {"items": after}
        )
    db.commit()
    return _tc_out(db, tender)


# --- revisions -----------------------------------------------------------------------------------


@router.post("/{tender_id}/submit")
def submit_tender(
    tender_id: int,
    body: SubmitIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    view: ViewScope,
    edit: EditScope,
) -> TenderOut | TenderCostOut:
    """Freeze the current revision (R0, R1 ...) and mark the tender submitted."""
    tender = _editable(db, tender_id, view, edit, principal)
    before = tender.status
    revision = revisions.submit(db, tender, principal.user.id, body.note)
    _record(
        db,
        request,
        principal,
        "tender.submit",
        tender,
        before={"status": before},
        after={
            "status": tender.status,
            "revision": revisions.label(revision.rev_no),
            "note": revision.note,
        },
    )
    db.commit()
    db.refresh(tender)
    return _tender_out(db, tender, can_cost(principal))


def _revision_out(rev: TenderRevision) -> RevisionOut:
    totals = rev.snapshot["totals"]
    return RevisionOut(
        rev_no=rev.rev_no,
        label=revisions.label(rev.rev_no),
        submitted_at=rev.submitted_at,
        submitted_by_name=rev.submitter.full_name if rev.submitter else None,
        note=rev.note,
        subtotal=Decimal(totals["subtotal"]),
        grand_total=Decimal(totals["grand_total"]),
        lines=len(rev.snapshot["lines"]),
    )


@router.get("/{tender_id}/revisions")
def list_revisions(
    tender_id: int, db: DbSession, principal: CurrentPrincipal, scope: ViewScope
) -> list[RevisionOut]:
    tender = get_visible(db, tender_id, scope, principal)
    rows = db.scalars(
        select(TenderRevision)
        .where(TenderRevision.tender_id == tender.id)
        .order_by(TenderRevision.rev_no)
    )
    return [_revision_out(r) for r in rows]


def _side(db: Session, tender: Tender, which: str) -> dict:
    if which == "current":
        snap = revisions.build_snapshot(db, tender)
        snap["label"] = revisions.revision_label(db, tender)
        return snap
    try:
        rev_no = int(which.upper().lstrip("R"))
    except ValueError as exc:
        raise unprocessable("Choose a revision number (0, 1 ...) or 'current'") from exc
    return revisions.get_revision(db, tender, rev_no).snapshot


@router.get("/{tender_id}/revisions/compare")
def compare_revisions(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    a: str = "0",
    b: str = "current",
) -> CompareOut:
    """Rate and amount per line between two revisions (a number, or 'current' for the draft)."""
    tender = get_visible(db, tender_id, scope, principal)
    return CompareOut(**revisions.compare(_side(db, tender, a), _side(db, tender, b)))


# --- exports -------------------------------------------------------------------------------------


def _download(content: bytes, media_type: str, filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.get("/{tender_id}/export.xlsx")
def export_xlsx(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    rev: Annotated[
        int | None, Query(ge=0, description="A submitted revision; default: current")
    ] = None,
) -> Response:
    """EESPL's BOQ as Excel (selling rates only, never cost or margin)."""
    doc = export.document(db, get_visible(db, tender_id, scope, principal), rev)
    return _download(export.xlsx(doc), export.XLSX_TYPE, f"{export.file_stem(doc)}.xlsx")


@router.get("/{tender_id}/export.pdf")
def export_pdf(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    rev: Annotated[
        int | None, Query(ge=0, description="A submitted revision; default: current")
    ] = None,
) -> Response:
    """EESPL's BOQ as PDF, A4 landscape (selling rates only)."""
    doc = export.document(db, get_visible(db, tender_id, scope, principal), rev)
    return _download(export.pdf(doc), "application/pdf", f"{export.file_stem(doc)}.pdf")


@router.get("/{tender_id}/export/client")
def export_client_format(
    tender_id: int,
    db: DbSession,
    principal: CurrentPrincipal,
    scope: ViewScope,
    rev: Annotated[
        int | None, Query(ge=0, description="A submitted revision; default: current")
    ] = None,
) -> Response:
    """Our rates written into the client's own uploaded sheet (saved as a new file). 409 when
    the original was not .xlsx or had no rate column mapped."""
    tender = get_visible(db, tender_id, scope, principal)
    doc = export.document(db, tender, rev)
    data, name, counts = export.client_format(db, tender, doc)
    response = _download(data, export.XLSX_TYPE, name)
    response.headers["X-Rates-Written"] = str(counts["rates"])
    response.headers["X-Lines-Skipped"] = str(counts["skipped"])
    return response
