"""T&C library rules: duplicate keys, which rows are not real clauses, merging and hiding.

Invariants (enforced here, used by the API and by `python -m app.cli.clean_tc`):
- A clause is either active or hidden (with a reason), and may be merged into a master.
- usage_count of a master = its own_usage_count + the own_usage_count of its variants, so
  unmerging restores the exact original counts.
- A template never holds a hidden or merged clause: merging swaps in the master (dropping
  the duplicate), hiding removes the clause from templates.
- Anything a person does to a clause (hide, unhide, merge, unmerge, edit, mark reviewed) sets
  `curated`; the cleanup never overrides a curated clause, so it can be re-run safely.
"""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.masters.models import TcClause, TcTemplate, TcTemplateClause

HIDDEN_REASONS = ("not_a_clause", "client_checklist", "project_specific", "manual")
REVIEW_NOTE_LOST_NUMBER = "leading number lost in import, please correct"

# --- duplicate key -------------------------------------------------------------------------

_SPELLING = [
    (r"\blabor\b", "labour"),
    (r"\baggree\b", "agree"),
    (r"\bconsiderd\b", "considered"),
    (r"\beraction\b", "erection"),
    (r"\bclient scope\b", "client"),
]


def clause_key(text: str) -> str:
    """Key under which spelling, spacing and punctuation variants of a clause collide.

    Wording that changes scope (e.g. "expansion joints, grouting" vs "expansion joints")
    stays different on purpose.
    """
    t = unicodedata.normalize("NFKC", text).lower()
    t = " ".join(t.split())
    for pattern, replacement in _SPELLING:
        t = re.sub(pattern, replacement, t)
    t = re.sub(r"\s+([;,.:)])", r"\1", t)  # "joints ;" -> "joints;", "bat , etc" -> "bat, etc"
    t = re.sub(r"\(\s+", "(", t)
    return t.rstrip(" .,;:!)")


# --- classification ------------------------------------------------------------------------

_VERB = re.compile(r"\b(shall|will|should|be|is|are|provided|done)\b", re.I)
_HEADER = re.compile(r"\bsr\.?\s*no\b|\bdescription\b|\bremarks\b|\(?\byes or no\b\)?", re.I)
_NOT_CLAUSE_START = re.compile(r"^\s*(prepared by\b|note\s+approve\s+make\b)", re.I)
_BOQ_FRAGMENT = re.compile(r"^\s*(\d+(\.\d+)?\s*mm\b|x\s*\d)", re.I)
_RUPEE_PER_METRE = re.compile(r"\brs\.?\s*[\d,]+(\.\d+)?.*\b(r/mt|/\s*mt)\b", re.I)
_CHECKLIST_END = re.compile(
    r"\s(aggree only for waterproofing scope|aggree|agree|not applicable|in civil contractor scope)"
    r"\s*\.?$",
    re.I,
)
_CONTRACTOR_THEN_CLAUSE = re.compile(
    r"will be in contractor'?s? scope\b.*\b(shall|will|should) be\b", re.I
)
_PSP = re.compile(r"\bPSP\b")
_MONTH_YY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*['’]\s*\d{2}\b", re.I
)
_RATE_PER_UNIT = re.compile(r"\d[\d,]*(\.\d+)?\s*(rs\.?\s*)?(/|per)\s*(bag|tonne?|ton)\b", re.I)
_PERCENT_OF_BILL = re.compile(r"\d+(\.\d+)?\s*%\s*of\s*(the\s*)?bill value", re.I)
_LOST_NUMBER = re.compile(r"^\s*(%|0mm|x\s)", re.I)


def _words(text: str) -> list[str]:
    return [w for w in text.split() if re.search(r"[a-z0-9]", w, re.I)]


def hidden_reason_for(text: str) -> str | None:
    """'not_a_clause' | 'client_checklist' | 'project_specific' | None (a real clause)."""
    words = _words(text)
    if (
        (len(words) < 5 and not _VERB.search(text))
        or (len(words) < 8 and _HEADER.search(text))
        or _NOT_CLAUSE_START.match(text)
        or _BOQ_FRAGMENT.match(text)
        or _RUPEE_PER_METRE.search(text)
    ):
        return "not_a_clause"
    if _CHECKLIST_END.search(text) or _CONTRACTOR_THEN_CLAUSE.search(text):
        return "client_checklist"
    if (
        _PSP.search(text)
        or _MONTH_YY.search(text)
        or _RATE_PER_UNIT.search(text)
        or _PERCENT_OF_BILL.search(text)
    ):
        return "project_specific"
    return None


def needs_review_note(text: str) -> str | None:
    """Clauses whose leading number was stripped on import ("5 % Retention" -> "% Retention")."""
    return REVIEW_NOTE_LOST_NUMBER if _LOST_NUMBER.match(text) else None


# --- invariants ----------------------------------------------------------------------------


class TcRuleError(ValueError):
    pass


def recompute_usage(db: Session, master_ids: list[int]) -> None:
    """usage_count = own count + variants' own counts, for the given clauses."""
    if not master_ids:
        return
    sums = dict(
        db.execute(
            select(TcClause.merged_into_id, func.sum(TcClause.own_usage_count))
            .where(TcClause.merged_into_id.in_(master_ids))
            .group_by(TcClause.merged_into_id)
        ).all()
    )
    for clause in db.scalars(select(TcClause).where(TcClause.id.in_(master_ids))):
        clause.usage_count = clause.own_usage_count + int(sums.get(clause.id) or 0)
    db.flush()


def _replace_in_templates(db: Session, old_id: int, new_id: int | None) -> int:
    """Swap (or with new_id=None, remove) a clause in every template, without duplicates and
    keeping the order. Returns the number of templates changed."""
    changed = 0
    templates = db.scalars(
        select(TcTemplate).where(
            TcTemplate.id.in_(
                select(TcTemplateClause.template_id).where(TcTemplateClause.clause_id == old_id)
            )
        )
    ).all()
    for template in templates:
        ids = [tc.clause_id for tc in template.clauses]
        new_ids: list[int] = []
        for cid in ids:
            cid = new_id if cid == old_id else cid
            if cid is not None and cid not in new_ids:
                new_ids.append(cid)
        set_template_clause_ids(db, template, new_ids, check=False)
        changed += 1
    return changed


def set_template_clause_ids(
    db: Session, template: TcTemplate, clause_ids: list[int], *, check: bool = True,
    created_by=None,
) -> None:  # fmt: skip
    """Replace a template's clauses (in this order). Refuses hidden or merged clauses."""
    if len(set(clause_ids)) != len(clause_ids):
        raise TcRuleError("A clause can appear only once in a template")
    clauses = {c.id: c for c in db.scalars(select(TcClause).where(TcClause.id.in_(clause_ids)))}
    missing = sorted(set(clause_ids) - clauses.keys())
    if missing:
        raise TcRuleError(f"Unknown clause ids: {missing}")
    if check:
        bad = [
            cid
            for cid in clause_ids
            if clauses[cid].status != "active" or clauses[cid].merged_into_id is not None
        ]
        if bad:
            raise TcRuleError(f"Hidden or merged clauses cannot be in a template: {bad}")
    template.clauses = []
    db.flush()
    template.clauses = [
        TcTemplateClause(clause_id=cid, sort_order=i, created_by=created_by)
        for i, cid in enumerate(clause_ids, start=1)
    ]
    db.flush()


def merge_clause(db: Session, variant: TcClause, master: TcClause) -> list[int]:
    """Merge `variant` into `master`. Variants of `variant` move to `master` too. Templates
    holding the variant get the master instead. Returns the ids now merged into master."""
    if variant.id == master.id:
        raise TcRuleError("A clause cannot be merged into itself")
    if variant.merged_into_id is not None:
        raise TcRuleError("This clause is already merged into another clause")
    if master.merged_into_id is not None:
        raise TcRuleError("The target clause is itself merged; merge into its master")
    moved = list(db.scalars(select(TcClause.id).where(TcClause.merged_into_id == variant.id)))
    if moved:
        db.execute(update(TcClause).where(TcClause.id.in_(moved)).values(merged_into_id=master.id))
    variant.merged_into_id = master.id
    variant.usage_count = variant.own_usage_count
    db.flush()
    _replace_in_templates(db, variant.id, master.id)
    recompute_usage(db, [master.id])
    return [variant.id, *moved]


def unmerge_clause(db: Session, variant: TcClause) -> int:
    if variant.merged_into_id is None:
        raise TcRuleError("This clause is not merged")
    master_id = variant.merged_into_id
    variant.merged_into_id = None
    variant.curated = True
    master = db.get(TcClause, master_id)
    if master is not None:
        master.curated = True  # keep the cleanup from merging the pair again
    db.flush()
    recompute_usage(db, [master_id, variant.id])
    return master_id


def hide_clause(db: Session, clause: TcClause, reason: str) -> None:
    if reason not in HIDDEN_REASONS:
        raise TcRuleError(f"Reason must be one of: {', '.join(HIDDEN_REASONS)}")
    clause.status = "hidden"
    clause.hidden_reason = reason
    db.flush()
    _replace_in_templates(db, clause.id, None)


def unhide_clause(clause: TcClause) -> None:
    clause.status = "active"
    clause.hidden_reason = None


# --- the cleanup ---------------------------------------------------------------------------


@dataclass
class CleanupSummary:
    groups_merged: int = 0
    clauses_merged: int = 0
    hidden: dict[str, int] = field(default_factory=lambda: dict.fromkeys(HIDDEN_REASONS[:3], 0))
    flagged: int = 0
    active_per_category: dict[str, int] = field(default_factory=dict)
    templates: dict[str, int] = field(default_factory=dict)
    merged_groups: list[tuple[str, list[str]]] = field(default_factory=list)  # master, variants


def clean_tc(db: Session) -> CleanupSummary:
    """Merge duplicates, hide non-clauses, flag lost numbers, fix templates. Idempotent: rows a
    person has already hidden, unhidden or reviewed are left alone; a second run changes
    nothing. The caller commits (or rolls back for a dry run)."""
    summary = CleanupSummary()
    clauses = list(db.scalars(select(TcClause).order_by(TcClause.id)))

    # 1. duplicates among clauses not merged yet
    groups: dict[str, list[TcClause]] = defaultdict(list)
    for c in clauses:
        if c.merged_into_id is None:
            groups[clause_key(c.text)].append(c)
    for members in groups.values():
        if len(members) < 2:
            continue
        master = max(members, key=lambda c: (c.own_usage_count, -c.id))
        variants = [c for c in members if c is not master and not c.curated]
        if not variants:
            continue
        for v in variants:
            merge_clause(db, v, master)
        summary.groups_merged += 1
        summary.clauses_merged += len(variants)
        summary.merged_groups.append((master.text, [v.text for v in variants]))

    # 2-4. hide what is not a reusable clause (rule-based only; manual decisions stand)
    for c in clauses:
        if c.merged_into_id is not None or c.hidden_reason == "manual" or c.curated:
            continue
        reason = hidden_reason_for(c.text)
        if reason and c.status != "hidden":
            hide_clause(db, c, reason)
            summary.hidden[reason] += 1

    # 5. lost leading numbers
    for c in clauses:
        note = needs_review_note(c.text)
        if note and not c.needs_review and not c.curated:
            c.needs_review = True
            c.review_note = note
            summary.flagged += 1
    db.flush()

    # 6. templates: no merged/hidden clauses (merges and hides above already fixed them;
    # this also repairs anything that predates the rules)
    for template in db.scalars(select(TcTemplate)):
        ids: list[int] = []
        for tc in template.clauses:
            clause = tc.clause
            cid = clause.merged_into_id or clause.id
            target = db.get(TcClause, cid)
            if target.status == "active" and cid not in ids:
                ids.append(cid)
        if ids != [tc.clause_id for tc in template.clauses]:
            set_template_clause_ids(db, template, ids)
        summary.templates[template.name] = len(ids)

    summary.active_per_category = dict(
        db.execute(
            select(TcClause.category, func.count())
            .where(TcClause.status == "active", TcClause.merged_into_id.is_(None))
            .group_by(TcClause.category)
            .order_by(TcClause.category)
        ).all()
    )
    return summary
