from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.auth.deps import CurrentPrincipal, require_permission
from app.db import DbSession
from app.masters.models import TcClause, TcTemplate, TcTemplateClause
from app.masters.routers.common import (
    Limit,
    Offset,
    Search,
    conflict,
    get_or_404,
    like,
    paginate,
    unprocessable,
)
from app.masters.schemas import (
    ClauseIn,
    ClauseMergeIn,
    ClauseOut,
    ClauseUpdate,
    ClauseVariant,
    HideIn,
    OrderIn,
    Page,
    TemplateIn,
    TemplateOut,
    TemplateSummary,
    TemplateUpdate,
)
from app.masters.tc import (
    TcRuleError,
    hide_clause,
    merge_clause,
    recompute_usage,
    set_template_clause_ids,
    unhide_clause,
    unmerge_clause,
)

router = APIRouter(prefix="/api/tc", tags=["terms and conditions"])

view = [Depends(require_permission("library.view"))]
edit = [Depends(require_permission("library.edit"))]


# --- clauses ---


def _clause_out(db: Session, clauses: list[TcClause]) -> list[ClauseOut]:
    """Clauses with the texts of the variants merged into them."""
    variants: dict[int, list[TcClause]] = defaultdict(list)
    ids = [c.id for c in clauses]
    if ids:
        for v in db.scalars(
            select(TcClause)
            .where(TcClause.merged_into_id.in_(ids))
            .order_by(TcClause.own_usage_count.desc(), TcClause.id)
        ):
            variants[v.merged_into_id].append(v)
    out = []
    for c in clauses:
        item = ClauseOut.model_validate(c)
        item.variants = [ClauseVariant.model_validate(v) for v in variants[c.id]]
        item.variant_count = len(item.variants)
        out.append(item)
    return out


@router.get("/clauses", dependencies=view)
def list_clauses(
    db: DbSession,
    q: Search = None,
    category: str | None = None,
    include_hidden: Annotated[
        bool, Query(description="Also return hidden clauses (with their reason)")
    ] = False,
    needs_review: bool | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> Page[ClauseOut]:
    """Masters only: merged variants come back inside their master (`variants`)."""
    query = select(TcClause).where(TcClause.merged_into_id.is_(None))
    if not include_hidden:
        query = query.where(TcClause.status == "active")
    if q:
        query = query.where(TcClause.text.ilike(like(q)))
    if category:
        query = query.where(TcClause.category == category)
    if needs_review is not None:
        query = query.where(TcClause.needs_review == needs_review)
    query = query.order_by(TcClause.category, TcClause.sort_order, TcClause.id)
    rows, total = paginate(db, query, limit, offset)
    return Page(items=_clause_out(db, rows), total=total, limit=limit, offset=offset)


@router.post("/clauses", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_clause(
    body: ClauseIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    fields = body.model_dump()
    if fields["sort_order"] is None:
        fields["sort_order"] = (db.scalar(select(func.max(TcClause.sort_order))) or 0) + 1
    clause = TcClause(**fields, curated=True, created_by=principal.user.id)
    db.add(clause)
    db.flush()
    audit.record(db, "tc_clause.create", "tc_clause", clause.id, user_id=principal.user.id,
                 after=audit.model_snapshot(clause), ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(clause)
    return _clause_out(db, [clause])[0]


@router.put("/clauses/order", dependencies=edit)
def reorder_clauses(
    body: OrderIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> list[ClauseOut]:
    """Give the listed clauses sort_order 1..n in the order sent (others are untouched)."""
    clauses = {c.id: c for c in db.scalars(select(TcClause).where(TcClause.id.in_(body.ids)))}
    if len(clauses) != len(set(body.ids)):
        raise unprocessable("Unknown clause id")
    before = {i: clauses[i].sort_order for i in body.ids}
    for position, clause_id in enumerate(body.ids, start=1):
        clauses[clause_id].sort_order = position
    audit.record(db, "tc_clause.reorder", "tc_clause", None, user_id=principal.user.id,
                 before={"sort_order": before},
                 after={"sort_order": {i: clauses[i].sort_order for i in body.ids}},
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return _clause_out(db, [clauses[i] for i in body.ids])


def _audited(db: Session, request: Request, principal, clause: TcClause, action: str, change):
    """Run `change`, mark the clause as decided by a person, write audit, commit."""
    before = audit.model_snapshot(clause)
    try:
        change()
    except TcRuleError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    clause.curated = True
    db.flush()
    after = audit.model_snapshot(clause)
    if after != before:
        audit.record(db, action, "tc_clause", clause.id, user_id=principal.user.id,
                     before=before, after=after, ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(clause)
    return _clause_out(db, [clause])[0]


@router.patch("/clauses/{clause_id}", dependencies=edit)
def update_clause(
    clause_id: int,
    body: ClauseUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ClauseOut:
    clause = get_or_404(db, TcClause, clause_id, "Clause")

    def change():
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "text" in changes:
            changes["text"] = changes["text"].strip()
            if changes["text"] != clause.text:
                clause.needs_review = False  # the person has corrected it
                clause.review_note = None
        for field, value in changes.items():
            setattr(clause, field, value)

    return _audited(db, request, principal, clause, "tc_clause.update", change)


@router.post("/clauses/{clause_id}/hide", dependencies=edit)
def hide(
    clause_id: int, body: HideIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    """Hide from the library; the clause also leaves every template."""
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    return _audited(db, request, principal, clause, "tc_clause.hide",
                    lambda: hide_clause(db, clause, body.reason))  # fmt: skip


@router.post("/clauses/{clause_id}/unhide", dependencies=edit)
def unhide(
    clause_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    return _audited(db, request, principal, clause, "tc_clause.unhide",
                    lambda: unhide_clause(clause))  # fmt: skip


@router.post("/clauses/{clause_id}/merge", dependencies=edit)
def merge(
    clause_id: int,
    body: ClauseMergeIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ClauseOut:
    """Merge this clause into another (its master). Templates holding it get the master.
    Returns the master with its variants."""
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    master = get_or_404(db, TcClause, body.into_id, "Target clause")
    _audited(db, request, principal, clause, "tc_clause.merge",
             lambda: merge_clause(db, clause, master))  # fmt: skip
    db.refresh(master)
    return _clause_out(db, [master])[0]


@router.post("/clauses/{clause_id}/unmerge", dependencies=edit)
def unmerge(
    clause_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    return _audited(db, request, principal, clause, "tc_clause.unmerge",
                    lambda: unmerge_clause(db, clause))  # fmt: skip


@router.post("/clauses/{clause_id}/reviewed", dependencies=edit)
def mark_reviewed(
    clause_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    """Clear needs_review (saving a corrected text does this too)."""
    clause = get_or_404(db, TcClause, clause_id, "Clause")

    def change():
        clause.needs_review = False
        clause.review_note = None

    return _audited(db, request, principal, clause, "tc_clause.reviewed", change)


@router.delete("/clauses/{clause_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit)
def delete_clause(
    clause_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    if db.scalar(select(func.count()).where(TcClause.merged_into_id == clause.id)):
        raise conflict("This clause has merged variants; unmerge them first")
    audit.record(db, "tc_clause.delete", "tc_clause", clause.id, user_id=principal.user.id,
                 before=audit.model_snapshot(clause), ip=audit.client_ip(request))  # fmt: skip
    master_id = clause.merged_into_id
    db.delete(clause)
    db.flush()
    if master_id:
        recompute_usage(db, [master_id])
    db.commit()


# --- templates ---


def _template_out(db: Session, template: TcTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        is_default=template.is_default,
        clauses=_clause_out(db, [tc.clause for tc in template.clauses]),
    )


def _template_snapshot(template: TcTemplate) -> dict:
    return {
        "name": template.name,
        "is_default": template.is_default,
        "clause_ids": [tc.clause_id for tc in template.clauses],
    }


def _set_clauses(
    db: Session, template: TcTemplate, clause_ids: list[int], principal: CurrentPrincipal
) -> None:
    try:
        set_template_clause_ids(db, template, clause_ids, created_by=principal.user.id)
    except TcRuleError as exc:
        raise unprocessable(str(exc)) from exc


def _name_taken(db: Session, name: str, exclude: int | None = None) -> bool:
    query = select(func.count()).select_from(TcTemplate).where(TcTemplate.name == name)
    if exclude is not None:
        query = query.where(TcTemplate.id != exclude)
    return db.scalar(query) > 0


def _clear_default(db: Session, keep: int | None = None) -> None:
    query = update(TcTemplate).where(TcTemplate.is_default).values(is_default=False)
    if keep is not None:
        query = query.where(TcTemplate.id != keep)
    db.execute(query)
    db.flush()


@router.get("/templates", dependencies=view)
def list_templates(db: DbSession) -> list[TemplateSummary]:
    counts = dict(
        db.execute(
            select(TcTemplateClause.template_id, func.count()).group_by(
                TcTemplateClause.template_id
            )
        ).all()
    )
    templates = db.scalars(
        select(TcTemplate).order_by(TcTemplate.is_default.desc(), TcTemplate.name)
    )
    return [
        TemplateSummary(
            id=t.id, name=t.name, is_default=t.is_default, clause_count=counts.get(t.id, 0)
        )
        for t in templates
    ]


@router.get("/templates/{template_id}", dependencies=view)
def get_template(template_id: int, db: DbSession) -> TemplateOut:
    return _template_out(db, get_or_404(db, TcTemplate, template_id, "Template"))


@router.post("/templates", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_template(
    body: TemplateIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> TemplateOut:
    if _name_taken(db, body.name):
        raise conflict("A template with this name already exists")
    if body.is_default:
        _clear_default(db)
    template = TcTemplate(
        name=body.name.strip(), is_default=body.is_default, created_by=principal.user.id
    )
    db.add(template)
    db.flush()
    _set_clauses(db, template, body.clause_ids, principal)
    audit.record(db, "tc_template.create", "tc_template", template.id,
                 user_id=principal.user.id, after=_template_snapshot(template),
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(template)
    return _template_out(db, template)


@router.patch("/templates/{template_id}", dependencies=edit)
def update_template(
    template_id: int,
    body: TemplateUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> TemplateOut:
    template = get_or_404(db, TcTemplate, template_id, "Template")
    before = _template_snapshot(template)
    if body.name is not None:
        if _name_taken(db, body.name, exclude=template.id):
            raise conflict("A template with this name already exists")
        template.name = body.name.strip()
    if body.is_default is True:
        _clear_default(db, keep=template.id)
        template.is_default = True
    elif body.is_default is False:
        template.is_default = False
    if body.clause_ids is not None:
        _set_clauses(db, template, body.clause_ids, principal)
    db.flush()
    after = _template_snapshot(template)
    if after != before:
        audit.record(db, "tc_template.update", "tc_template", template.id,
                     user_id=principal.user.id, before=before, after=after,
                     ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(template)
    return _template_out(db, template)


@router.delete(
    "/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit
)
def delete_template(
    template_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    template = get_or_404(db, TcTemplate, template_id, "Template")
    audit.record(db, "tc_template.delete", "tc_template", template.id,
                 user_id=principal.user.id, before=_template_snapshot(template),
                 ip=audit.client_ip(request))  # fmt: skip
    db.delete(template)
    db.commit()
