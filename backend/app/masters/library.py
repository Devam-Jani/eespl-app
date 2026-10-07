"""Rate library rules: which rows are not real BOQ items, which rates are other bidders',
how item statistics are kept, and merging duplicate items.

Statistics
- An item starts with the statistics the source sheet gave it (kept in `source_stats`).
- They are recomputed from the item's lines only when that changes the answer: when some of
  its lines are excluded or competitor rates, or when other items have been merged into it.
  Items that are themselves excluded or competitor keep the sheet's figures: they are shown
  only on request, with their flag, and never as a suggested rate.
  Recomputed stats use only valid lines (not excluded, not competitor, with a rate):
  boq_count = distinct files, min / median / max of their rates, and latest = the rate in the
  item's latest source file (if that line is valid).
- Otherwise the sheet's numbers stand, which keeps them identical to what EESPL computed
  (including lines the importer could not link to the item).

Merging keeps both rows: the duplicate gets `merged_into_id` and drops out of search, and its
lines count towards the target. Unmerging clears the pointer and recomputes both.
"""

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.masters.models import LibraryItem, LibraryLine

WORKING_ROW = re.compile(r"^\s*(margin|working|sub[\s-]*total|total)\b", re.IGNORECASE)
COMPETITOR_NOTE = re.compile(r"comparative|other\s+bidders?", re.IGNORECASE)
ONE_RUPEE = Decimal(1)
RATE_PLACES = Decimal("0.0001")
STAT_FIELDS = (
    "boq_count",
    "latest_rate",
    "min_rate",
    "median_rate",
    "max_rate",
    "latest_channel",
    "latest_source_file",
)

REASON_WORKING_ROW = "working / margin / total row, not a BOQ item"
REASON_BELOW_ONE = "rate below ₹1"


def exclusion_reason(*texts: str | None, rate: Decimal | None) -> str | None:
    """Why a row should be hidden from search, or None. `texts` are its description (and,
    for a line, its parent item): a row whose text starts with Margin / Working / Total /
    Sub total comes from a working column, not the BOQ."""
    if any(t and WORKING_ROW.match(t) for t in texts):
        return REASON_WORKING_ROW
    if rate is not None and rate < ONE_RUPEE:
        return REASON_BELOW_ONE
    return None


def is_competitor_note(note: str | None) -> bool:
    return bool(note and COMPETITOR_NOTE.search(note))


def source_stats(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy of the sheet's statistics for an item row."""
    return {k: (str(row[k]) if isinstance(row[k], Decimal) else row[k]) for k in STAT_FIELDS}


def _from_source(stats: dict[str, Any] | None) -> dict[str, Any]:
    stats = stats or {}
    out: dict[str, Any] = {}
    for k in STAT_FIELDS:
        v = stats.get(k)
        out[k] = Decimal(v) if v is not None and k.endswith("_rate") else v
    out["boq_count"] = int(stats.get("boq_count") or 0)
    return out


@dataclass
class _Line:
    rate: Decimal | None
    file: str
    channel: str | None
    valid: bool
    flagged: bool


def _same_file(line_file: str, source_file: str | None) -> bool:
    return bool(source_file) and (line_file == source_file or line_file.endswith(f"/{source_file}"))


def _stats_from_lines(lines: list[_Line], latest_source_file: str | None) -> dict[str, Any]:
    valid = [ln for ln in lines if ln.valid]
    rates = sorted(ln.rate for ln in valid)
    latest = next((ln for ln in valid if _same_file(ln.file, latest_source_file)), None)
    q = lambda v: v.quantize(RATE_PLACES) if v is not None else None  # noqa: E731
    return {
        "boq_count": len({ln.file for ln in valid}),
        "min_rate": q(rates[0]) if rates else None,
        "median_rate": q(statistics.median(rates)) if rates else None,
        "max_rate": q(rates[-1]) if rates else None,
        "latest_rate": q(latest.rate) if latest else None,
        "latest_channel": latest.channel if latest else None,
        "latest_source_file": latest_source_file if latest else None,
    }


def recompute_stats(db: Session, item_ids: list[int] | None = None) -> int:
    """Bring the statistics of the given items (default: all) up to date. Returns how many
    items now use statistics recomputed from their lines."""
    items = db.execute(
        select(
            LibraryItem.id,
            LibraryItem.merged_into_id,
            LibraryItem.source_stats,
            LibraryItem.is_excluded,
            LibraryItem.is_competitor,
        ).where(LibraryItem.id.in_(item_ids) if item_ids is not None else True)
    ).all()
    if not items:
        return 0
    scope = {i.id for i in items}
    children: dict[int, list[int]] = defaultdict(list)
    for child_id, parent_id in db.execute(
        select(LibraryItem.id, LibraryItem.merged_into_id).where(
            LibraryItem.merged_into_id.in_(scope) if item_ids is not None
            else LibraryItem.merged_into_id.is_not(None)
        )
    ):  # fmt: skip
        children[parent_id].append(child_id)

    owner: dict[int, int] = {}  # line's own item -> item whose stats it counts towards
    for item in items:
        if item.merged_into_id is None:
            owner[item.id] = item.id
            for child in children.get(item.id, []):
                owner[child] = item.id

    lines: dict[int, list[_Line]] = defaultdict(list)
    if owner:
        for item_id, rate, file, channel, excluded, competitor in db.execute(
            select(
                LibraryLine.library_item_id,
                LibraryLine.rate,
                LibraryLine.file,
                LibraryLine.channel,
                LibraryLine.is_excluded,
                LibraryLine.is_competitor,
            ).where(LibraryLine.library_item_id.in_(owner.keys()))
        ):
            lines[owner[item_id]].append(
                _Line(
                    rate,
                    file,
                    channel,
                    valid=not (excluded or competitor) and rate is not None,
                    flagged=excluded or competitor,
                )  # fmt: skip
            )

    updates = []
    recomputed = 0
    for item in items:
        sheet = _from_source(item.source_stats)
        own_lines = lines.get(item.id, [])
        use_lines = item.merged_into_id is None and (
            item.id in children
            or (
                not (item.is_excluded or item.is_competitor) and any(ln.flagged for ln in own_lines)
            )
        )
        stats = _stats_from_lines(own_lines, sheet["latest_source_file"]) if use_lines else sheet
        recomputed += use_lines
        updates.append({"id": item.id, **stats, "stats_from_lines": use_lines})
    for start in range(0, len(updates), 1000):
        db.execute(update(LibraryItem), updates[start : start + 1000])
    return recomputed


class MergeError(ValueError):
    pass


def merge(db: Session, source: LibraryItem, target: LibraryItem) -> list[int]:
    """Merge `source` into `target`. Items already merged into `source` move to `target`
    too. Returns the ids now merged into target because of this call."""
    if source.id == target.id:
        raise MergeError("An item cannot be merged into itself")
    if source.merged_into_id is not None:
        raise MergeError("This item is already merged into another item")
    if target.merged_into_id is not None:
        raise MergeError("The target item is itself merged; merge into the item it points to")
    moved = list(db.scalars(select(LibraryItem.id).where(LibraryItem.merged_into_id == source.id)))
    if moved:
        db.execute(
            update(LibraryItem).where(LibraryItem.id.in_(moved)).values(merged_into_id=target.id)
        )
    source.merged_into_id = target.id
    source.merged_at = func.now()
    db.flush()
    recompute_stats(db, [source.id, target.id, *moved])
    return [source.id, *moved]


def unmerge(db: Session, item: LibraryItem) -> int:
    """Undo a merge: the item becomes a search result again with its own lines and stats."""
    if item.merged_into_id is None:
        raise MergeError("This item is not merged")
    target_id = item.merged_into_id
    item.merged_into_id = None
    item.merged_at = None
    db.flush()
    recompute_stats(db, [item.id, target_id])
    return target_id


def link_channels(db: Session) -> int:
    """Every library folder (a channel: salesperson, partner, manufacturer) gets a channels row,
    and library lines point at it. Returns how many lines were linked."""
    db.execute(
        text(
            "INSERT INTO channels (name) SELECT DISTINCT channel FROM library_lines "
            "WHERE channel IS NOT NULL AND btrim(channel) <> '' ON CONFLICT (name) DO NOTHING"
        )
    )
    return db.execute(
        text(
            "UPDATE library_lines l SET channel_id = c.id FROM channels c "
            "WHERE c.name = l.channel AND l.channel_id IS DISTINCT FROM c.id"
        )
    ).rowcount
