"""Importers for the historical rate library (xlsx) and the T&C clause library (json).

Both are idempotent: rows are upserted on a natural key taken from the source, so running an
import twice leaves the same rows (and the same ids) behind.

Rate library keys
- library_items.source_key = sha1(normalised description | unit as written in the sheet).
  ("Rate library" has no two rows with the same description and unit.)
- library_lines.source_key = sha1(file | sheet | row), the line's position in its BOQ.
- Lines link to items by match_key = sha1(normalised description | normalised unit), trying the
  line's own description first and then "<parent item> — <description>", which is how the
  "Rate library" sheet names sub-items. Lines with no matching item keep library_item_id NULL.

Rules (app.masters.library)
- Items and lines whose text starts with Margin / Working / Total / Sub total, or whose rate is
  below ₹1, are marked is_excluded with a reason (not deleted).
- Items and lines whose check note mentions "comparative" or "other bidders" are marked
  is_competitor.
- Decisions made by a person win over the rules: a re-import keeps a manually changed unit and
  a manual hide/unhide, and never touches merges.
- Item statistics are then recomputed where flagged lines or merges change them.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit
from app.masters.library import exclusion_reason, is_competitor_note, recompute_stats, source_stats
from app.masters.models import LibraryItem, LibraryLine, TcClause, TcTemplate, TcTemplateClause
from app.masters.units import load_aliases, normalise_unit

RATE_LIBRARY_SHEET = "Rate library"
ALL_LINES_SHEET = "All lines"
ITEM_COLUMNS = {
    "description": "Description",
    "unit": "Unit",
    "boq_count": "No. of BOQs",
    "latest_rate": "Latest rate (₹)",
    "min_rate": "Min",
    "median_rate": "Median",
    "max_rate": "Max",
    "latest_client": "Latest client folder",
    "latest_source_file": "Latest source file",
    "product_make": "Product / make",
    "remarks": "Remarks",
    "from_eespl_file": "From EESPL-priced file",
    "check": "Check",
}
LINE_COLUMNS = {
    "client_folder": "Client folder",
    "file": "File",
    "sheet": "Sheet",
    "row": "Row",
    "item_no": "Item No",
    "parent_item": "Parent item",
    "description": "Description",
    "unit_raw": "Unit (as written)",
    "unit": "Unit",
    "qty": "Qty",
    "qty_note": "Qty note",
    "rate": "Rate (₹)",
    "product_make": "Product / make",
    "remarks": "Remarks",
    "from_eespl_file": "EESPL file",
    "check": "Check",
}
BLANK_UNIT = "(blank)"
SUB_ITEM_SEPARATOR = " — "
BATCH = 1000


class ImportFormatError(ValueError):
    pass


@dataclass
class Skipped:
    sheet: str
    row: int
    reason: str


@dataclass
class LibraryImportResult:
    items_in_file: int = 0
    items_inserted: int = 0
    items_updated: int = 0
    items_deleted: int = 0
    lines_in_file: int = 0
    lines_inserted: int = 0
    lines_updated: int = 0
    lines_deleted: int = 0
    lines_linked: int = 0
    lines_linked_via_parent: int = 0
    lines_unlinked: int = 0
    ambiguous_match_keys: int = 0
    items_excluded: dict[str, int] = field(default_factory=dict)  # reason -> count
    items_competitor: int = 0
    items_stats_from_lines: int = 0
    lines_excluded: int = 0
    lines_competitor: int = 0
    unrecognised_units: dict[str, int] = field(default_factory=dict)
    skipped: list[Skipped] = field(default_factory=list)


# --- value helpers ---


def normalise_text(text: str) -> str:
    """Key form of a description: Unicode-normalised, lower-case, single-spaced."""
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def _sha1(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()


def _text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _decimal(value: Any) -> Decimal | None:
    """A number from a cell, or None. Floats go through str() so 0.1 stays 0.1."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


def _unit_raw(value: Any) -> str | None:
    raw = _text(value, 50)
    return None if raw == BLANK_UNIT else raw


def _rows(ws, columns: dict[str, str], sheet: str) -> Iterator[tuple[int, dict[str, Any]]]:
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
    missing = [title for title in columns.values() if title not in header]
    if missing:
        raise ImportFormatError(f'Sheet "{sheet}" is missing columns: {", ".join(missing)}')
    index = {key: header.index(title) for key, title in columns.items()}
    for number, values in enumerate(rows, start=2):
        if values is None or all(v is None for v in values):
            continue
        yield number, {key: values[i] if i < len(values) else None for key, i in index.items()}


def _upsert(db: Session, model, rows: list[dict[str, Any]], keep: dict | None = None) -> None:
    """Insert or update on source_key. `keep` maps column -> condition on the existing row
    under which its current value is kept (manual edits that a re-import must not undo)."""
    keep = keep or {}
    table = model.__table__
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        stmt = insert(model)
        update_cols = {
            col: case((keep[col], table.c[col]), else_=stmt.excluded[col])
            if col in keep
            else stmt.excluded[col]
            for col in batch[0]
            if col != "source_key"
        }
        update_cols["updated_at"] = func.now()
        db.execute(
            stmt.on_conflict_do_update(index_elements=["source_key"], set_=update_cols), batch
        )


def _delete_stale(db: Session, model, stale: Iterable[str]) -> None:
    stale = list(stale)
    for start in range(0, len(stale), BATCH):
        db.execute(delete(model).where(model.source_key.in_(stale[start : start + BATCH])))


# --- rate library ---


def import_library(db: Session, path: str | Path) -> LibraryImportResult:
    result = LibraryImportResult()
    aliases = load_aliases(db)
    unrecognised: dict[str, int] = {}

    def unit_of(raw: str | None) -> str | None:
        code = normalise_unit(raw, aliases)
        if raw and code is None:
            unrecognised[raw] = unrecognised.get(raw, 0) + 1
        return code

    wb = load_workbook(path, read_only=True, data_only=True)
    for sheet in (RATE_LIBRARY_SHEET, ALL_LINES_SHEET):
        if sheet not in wb.sheetnames:
            raise ImportFormatError(f'Workbook has no "{sheet}" sheet')

    # Items
    items: dict[str, dict[str, Any]] = {}
    item_rows: dict[str, int] = {}
    for number, r in _rows(wb[RATE_LIBRARY_SHEET], ITEM_COLUMNS, RATE_LIBRARY_SHEET):
        description = _text(r["description"])
        if description is None:
            result.skipped.append(Skipped(RATE_LIBRARY_SHEET, number, "blank description"))
            continue
        unit_raw = _unit_raw(r["unit"])
        unit = unit_of(unit_raw)
        key = normalise_text(description)
        source_key = _sha1(key, unit_raw or "")
        if source_key in items:
            result.skipped.append(
                Skipped(RATE_LIBRARY_SHEET, number, f"duplicate of row {item_rows[source_key]}")
            )
            continue
        check = _text(r["check"], 200)
        boq_count = _decimal(r["boq_count"])
        latest_rate = _decimal(r["latest_rate"])
        reason = exclusion_reason(description, rate=latest_rate)
        items[source_key] = {
            "source_key": source_key,
            "match_key": _sha1(key, unit or ""),
            "description": description,
            "unit": unit,
            "unit_raw": unit_raw,
            "boq_count": int(boq_count) if boq_count is not None else 0,
            "latest_rate": _decimal(r["latest_rate"]),
            "min_rate": _decimal(r["min_rate"]),
            "median_rate": _decimal(r["median_rate"]),
            "max_rate": _decimal(r["max_rate"]),
            "latest_client": _text(r["latest_client"], 200),
            "latest_source_file": _text(r["latest_source_file"]),
            "product_make": _text(r["product_make"]),
            "remarks": _text(r["remarks"]),
            "from_eespl_file": _yes(r["from_eespl_file"]),
            "needs_check": check is not None,
            "check_note": check,
            "is_excluded": reason is not None,
            "excluded_reason": reason,
            "exclusion_source": "rule" if reason else None,
            "is_competitor": is_competitor_note(check),
        }
        items[source_key]["source_stats"] = source_stats(items[source_key])
        item_rows[source_key] = number

    existing = set(db.scalars(select(LibraryItem.source_key)))
    result.items_in_file = len(items)
    result.items_inserted = len(items.keys() - existing)
    result.items_updated = len(items.keys() & existing)
    result.items_deleted = len(existing - items.keys())
    if items:
        manual = LibraryItem.__table__.c.exclusion_source == "manual"
        _upsert(
            db,
            LibraryItem,
            list(items.values()),
            keep={
                "unit": LibraryItem.__table__.c.unit_manual,
                "is_excluded": manual,
                "excluded_reason": manual,
                "exclusion_source": manual,
            },
        )

    # match_key -> item id; when several items share a key, the one in most BOQs wins.
    by_match: dict[str, tuple[int, int]] = {}
    collisions = 0
    for source_key, item_id, match_key, boq_count in db.execute(
        select(LibraryItem.source_key, LibraryItem.id, LibraryItem.match_key, LibraryItem.boq_count)
    ):
        if source_key not in items:  # stale, deleted below
            continue
        if match_key in by_match:
            collisions += 1
            if boq_count <= by_match[match_key][1]:
                continue
        by_match[match_key] = (item_id, boq_count)
    result.ambiguous_match_keys = collisions

    # Lines
    lines: dict[str, dict[str, Any]] = {}
    line_rows: dict[str, int] = {}
    for number, r in _rows(wb[ALL_LINES_SHEET], LINE_COLUMNS, ALL_LINES_SHEET):
        description = _text(r["description"])
        file = _text(r["file"])
        if description is None:
            result.skipped.append(Skipped(ALL_LINES_SHEET, number, "blank description"))
            continue
        if file is None:
            result.skipped.append(Skipped(ALL_LINES_SHEET, number, "blank file"))
            continue
        sheet = _text(r["sheet"], 200)
        row = _decimal(r["row"])
        source_key = _sha1(file, sheet or "", str(row) if row is not None else f"line{number}")
        if source_key in lines:
            result.skipped.append(
                Skipped(ALL_LINES_SHEET, number, f"duplicate of row {line_rows[source_key]}")
            )
            continue

        unit_raw = _text(r["unit_raw"], 50)
        unit = unit_of(_unit_raw(r["unit"])) or normalise_unit(unit_raw, aliases)
        parent = _text(r["parent_item"])
        item_id = None
        candidates = [description] + (
            [f"{parent}{SUB_ITEM_SEPARATOR}{description}"] if parent else []
        )
        for i, candidate in enumerate(candidates):
            hit = by_match.get(_sha1(normalise_text(candidate), unit or ""))
            if hit:
                item_id = hit[0]
                result.lines_linked += 1
                result.lines_linked_via_parent += i
                break

        qty_value = r["qty"]
        qty = _decimal(qty_value)
        qty_note = _text(r["qty_note"], 50)
        if qty is None and qty_value is not None and qty_note is None:
            qty_note = _text(qty_value, 50)  # "QRO", "NQ" written in the qty column
        check = _text(r["check"], 200)
        rate = _decimal(r["rate"])
        reason = exclusion_reason(description, parent, rate=rate)
        lines[source_key] = {
            "source_key": source_key,
            "library_item_id": item_id,
            "client_folder": _text(r["client_folder"], 200),
            "file": file,
            "sheet": sheet,
            "row": int(row) if row is not None else None,
            "item_no": _text(r["item_no"], 50),
            "parent_item": parent,
            "description": description,
            "unit_raw": unit_raw,
            "unit": unit,
            "qty": qty,
            "qty_note": qty_note,
            "rate": rate,
            "product_make": _text(r["product_make"]),
            "remarks": _text(r["remarks"]),
            "from_eespl_file": _yes(r["from_eespl_file"]),
            "needs_check": check is not None,
            "check_note": check,
            "is_excluded": reason is not None,
            "excluded_reason": reason,
            "is_competitor": is_competitor_note(check),
        }
        line_rows[source_key] = number
    wb.close()

    existing = set(db.scalars(select(LibraryLine.source_key)))
    result.lines_in_file = len(lines)
    result.lines_inserted = len(lines.keys() - existing)
    result.lines_updated = len(lines.keys() & existing)
    result.lines_deleted = len(existing - lines.keys())
    result.lines_unlinked = len(lines) - result.lines_linked
    _delete_stale(db, LibraryLine, existing - lines.keys())
    if lines:
        _upsert(db, LibraryLine, list(lines.values()))
    _delete_stale(db, LibraryItem, set(db.scalars(select(LibraryItem.source_key))) - items.keys())
    result.unrecognised_units = dict(sorted(unrecognised.items(), key=lambda kv: -kv[1]))

    result.items_stats_from_lines = recompute_stats(db)
    result.items_excluded = dict(
        db.execute(
            select(LibraryItem.excluded_reason, func.count())
            .where(LibraryItem.is_excluded)
            .group_by(LibraryItem.excluded_reason)
        ).all()
    )
    result.items_competitor = db.scalar(select(func.count()).where(LibraryItem.is_competitor))
    result.lines_excluded = sum(1 for ln in lines.values() if ln["is_excluded"])
    result.lines_competitor = sum(1 for ln in lines.values() if ln["is_competitor"])

    audit.record(
        db,
        "library.import",
        "library",
        None,
        after={
            "file": Path(path).name,
            "items": result.items_in_file,
            "lines": result.lines_in_file,
            "lines_unlinked": result.lines_unlinked,
            "items_excluded": sum(result.items_excluded.values()),
            "items_competitor": result.items_competitor,
            "skipped": len(result.skipped),
        },
    )
    db.commit()
    return result


# --- T&C clauses ---


@dataclass
class TcImportResult:
    clauses_in_file: int = 0
    clauses_inserted: int = 0
    clauses_updated: int = 0
    template_created: bool = False
    template_clauses: int = 0
    skipped: list[Skipped] = field(default_factory=list)


DEFAULT_TEMPLATE_NAME = "EESPL Standard"


def _clause_key(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def import_tc(db: Session, path: str | Path) -> TcImportResult:
    """Insert clauses that are new; for existing ones only refresh usage_count, so wording,
    category and order edited in the app are kept. Creates the default "EESPL Standard"
    template from the default_include clauses if it does not exist yet."""
    result = TcImportResult()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ImportFormatError("Expected a JSON list of clauses")

    existing = {_clause_key(c.text): c for c in db.scalars(select(TcClause))}
    seen: set[str] = set()
    for number, raw in enumerate(data, start=1):
        text = _text(raw.get("text")) if isinstance(raw, dict) else None
        if text is None:
            result.skipped.append(Skipped("json", number, "missing text"))
            continue
        key = _clause_key(text)
        if key in seen:
            result.skipped.append(Skipped("json", number, "duplicate clause text"))
            continue
        seen.add(key)
        result.clauses_in_file += 1
        usage = int(raw.get("usage_count") or 0)
        clause = existing.get(key)
        if clause is not None:
            clause.usage_count = usage
            result.clauses_updated += 1
            continue
        clause = TcClause(
            text=text,
            category=_text(raw.get("category"), 50) or "general",
            usage_count=usage,
            default_include=bool(raw.get("default_include")),
            sort_order=int(raw.get("sort_order") or 0),
        )
        db.add(clause)
        existing[key] = clause
        result.clauses_inserted += 1
    db.flush()

    template = db.scalar(select(TcTemplate).where(TcTemplate.name == DEFAULT_TEMPLATE_NAME))
    if template is None:
        has_default = db.scalar(select(func.count()).where(TcTemplate.is_default)) > 0
        defaults = sorted(
            (c for c in existing.values() if c.default_include and c.is_active),
            key=lambda c: (c.sort_order, c.id),
        )
        template = TcTemplate(
            name=DEFAULT_TEMPLATE_NAME,
            is_default=not has_default,
            clauses=[
                TcTemplateClause(clause_id=c.id, sort_order=i)
                for i, c in enumerate(defaults, start=1)
            ],
        )
        db.add(template)
        result.template_created = True
    db.flush()
    result.template_clauses = len(template.clauses)

    audit.record(
        db,
        "tc.import",
        "tc_clause",
        None,
        after={
            "file": Path(path).name,
            "clauses": result.clauses_in_file,
            "inserted": result.clauses_inserted,
            "template_created": result.template_created,
        },
    )
    db.commit()
    return result
