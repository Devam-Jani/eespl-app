from fastapi import APIRouter, Depends, Request, status
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
    ClauseOut,
    ClauseUpdate,
    OrderIn,
    Page,
    TemplateIn,
    TemplateOut,
    TemplateSummary,
    TemplateUpdate,
)

router = APIRouter(prefix="/api/tc", tags=["terms and conditions"])

view = [Depends(require_permission("library.view"))]
edit = [Depends(require_permission("library.edit"))]


# --- clauses ---


@router.get("/clauses", dependencies=view)
def list_clauses(
    db: DbSession,
    q: Search = None,
    category: str | None = None,
    active: bool | None = None,
    limit: Limit = 500,
    offset: Offset = 0,
) -> Page[ClauseOut]:
    query = select(TcClause)
    if q:
        query = query.where(TcClause.text.ilike(like(q)))
    if category:
        query = query.where(TcClause.category == category)
    if active is not None:
        query = query.where(TcClause.is_active == active)
    query = query.order_by(TcClause.category, TcClause.sort_order, TcClause.id)
    rows, total = paginate(db, query, limit, offset)
    return Page(
        items=[ClauseOut.model_validate(c) for c in rows], total=total, limit=limit, offset=offset
    )


@router.post("/clauses", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_clause(
    body: ClauseIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> ClauseOut:
    fields = body.model_dump()
    if fields["sort_order"] is None:
        fields["sort_order"] = (db.scalar(select(func.max(TcClause.sort_order))) or 0) + 1
    clause = TcClause(**fields, created_by=principal.user.id)
    db.add(clause)
    db.flush()
    audit.record(db, "tc_clause.create", "tc_clause", clause.id, user_id=principal.user.id,
                 after=audit.model_snapshot(clause), ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return ClauseOut.model_validate(clause)


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
    return [ClauseOut.model_validate(clauses[i]) for i in body.ids]


@router.patch("/clauses/{clause_id}", dependencies=edit)
def update_clause(
    clause_id: int,
    body: ClauseUpdate,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ClauseOut:
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    before = audit.model_snapshot(clause)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(clause, field, value)
    db.flush()
    after = audit.model_snapshot(clause)
    if after != before:
        audit.record(db, "tc_clause.update", "tc_clause", clause.id, user_id=principal.user.id,
                     before=before, after=after, ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    return ClauseOut.model_validate(clause)


@router.delete("/clauses/{clause_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=edit)
def delete_clause(
    clause_id: int, request: Request, db: DbSession, principal: CurrentPrincipal
) -> None:
    clause = get_or_404(db, TcClause, clause_id, "Clause")
    audit.record(db, "tc_clause.delete", "tc_clause", clause.id, user_id=principal.user.id,
                 before=audit.model_snapshot(clause), ip=audit.client_ip(request))  # fmt: skip
    db.delete(clause)
    db.commit()


# --- templates ---


def _template_out(template: TcTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        is_default=template.is_default,
        clauses=[ClauseOut.model_validate(tc.clause) for tc in template.clauses],
    )


def _template_snapshot(template: TcTemplate) -> dict:
    return {
        "name": template.name,
        "is_default": template.is_default,
        "clause_ids": [tc.clause_id for tc in template.clauses],
    }


def _template_clauses(
    db: Session, clause_ids: list[int], principal: CurrentPrincipal
) -> list[TcTemplateClause]:
    if len(set(clause_ids)) != len(clause_ids):
        raise unprocessable("A clause can appear only once in a template")
    found = set(db.scalars(select(TcClause.id).where(TcClause.id.in_(clause_ids))))
    if found != set(clause_ids):
        raise unprocessable(f"Unknown clause ids: {sorted(set(clause_ids) - found)}")
    return [
        TcTemplateClause(clause_id=cid, sort_order=i, created_by=principal.user.id)
        for i, cid in enumerate(clause_ids, start=1)
    ]


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
    return _template_out(get_or_404(db, TcTemplate, template_id, "Template"))


@router.post("/templates", status_code=status.HTTP_201_CREATED, dependencies=edit)
def create_template(
    body: TemplateIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> TemplateOut:
    if _name_taken(db, body.name):
        raise conflict("A template with this name already exists")
    if body.is_default:
        _clear_default(db)
    template = TcTemplate(
        name=body.name.strip(),
        is_default=body.is_default,
        created_by=principal.user.id,
        clauses=_template_clauses(db, body.clause_ids, principal),
    )
    db.add(template)
    db.flush()
    audit.record(db, "tc_template.create", "tc_template", template.id,
                 user_id=principal.user.id, after=_template_snapshot(template),
                 ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(template)
    return _template_out(template)


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
        template.clauses = []
        db.flush()
        template.clauses = _template_clauses(db, body.clause_ids, principal)
    db.flush()
    after = _template_snapshot(template)
    if after != before:
        audit.record(db, "tc_template.update", "tc_template", template.id,
                     user_id=principal.user.id, before=before, after=after,
                     ip=audit.client_ip(request))  # fmt: skip
    db.commit()
    db.refresh(template)
    return _template_out(template)


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
