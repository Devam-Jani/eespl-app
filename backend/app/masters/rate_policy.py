"""Which past rate to suggest for a library item: the rate policies, and the leave-one-BOQ-out
backtest that compares them on the rate library.

An item's history is its priced lines (one per BOQ row) from the library, without competitor
and excluded lines. The library sheet has no BOQ dates and no city/state, so:
- "latest" uses an order of BOQ files rebuilt from the sheet itself: every item names its
  latest source file, which is newer than the item's other files. Those pairs give an order of
  all files (see file_order); an item's own "latest source file" always wins.
- "median of the last 12 months" and "same city/state median" cannot be computed and are not
  offered (they are listed in UNAVAILABLE with the reason).
"""

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import LibraryItem, LibraryLine

CENT = Decimal("0.01")

POLICIES: dict[str, str] = {
    "latest": "Latest rate",
    "median": "Median of all BOQs",
    "client_last": "Same client's last rate, else the median",
    "trimmed_mean": "Trimmed mean (top and bottom 10% dropped)",
    "client_median": "Same client's median, else the median",
    "lower_latest_median": "Lower of latest and median",
}
UNAVAILABLE: dict[str, str] = {
    "median_12_months": "Median of the last 12 months: the library has no BOQ dates",
    "location_median": "Same city/state median: the library has no city or state",
}
DEFAULT_POLICY = "median"  # replaced by the backtest winner in company settings


@dataclass(frozen=True)
class Obs:
    """One past priced line of an item."""

    rate: Decimal
    file: str
    client: str | None
    order: int = 0  # position of the file in the rebuilt BOQ order; higher = later


@dataclass
class Choice:
    rate: Decimal
    policy: str  # the policy that produced the rate (a fallback names itself)
    sources: list[Obs] = field(default_factory=list)


def client_key(name: str | None) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", (name or "").lower())) - {
        "ltd",
        "pvt",
        "limited",
        "private",
        "the",
        "and",
    }


def same_client(a: str | None, b: str | None) -> bool:
    """Client folder vs client name: equal words, or one name's words inside the other's."""
    ka, kb = client_key(a), client_key(b)
    return bool(ka and kb) and (ka <= kb or kb <= ka)


def _median(values: list[Decimal]) -> Decimal:
    return Decimal(statistics.median(sorted(values)))


def _latest(pool: list[Obs], preferred_file: str | None = None) -> list[Obs]:
    """The lines of the latest BOQ file in the pool (the item's own latest file wins)."""
    if preferred_file:
        own = [o for o in pool if o.file == preferred_file]
        if own:
            return own
    top = max(o.order for o in pool)
    newest = [o for o in pool if o.order == top]
    top_file = min(o.file for o in newest)  # same order: stable choice
    return [o for o in newest if o.file == top_file]


def trimmed_mean(values: list[Decimal], share: Decimal = Decimal("0.1")) -> Decimal:
    ordered = sorted(values)
    k = int(len(ordered) * share)
    kept = ordered[k : len(ordered) - k] or ordered
    return sum(kept, Decimal(0)) / len(kept)


def choose(
    policy: str, pool: list[Obs], client: str | None = None, preferred_file: str | None = None
) -> Choice | None:
    """The suggested rate for one item under `policy`, rounded to paise (half up)."""
    if not pool:
        return None
    rates = [o.rate for o in pool]

    def done(rate: Decimal, used: str, sources: list[Obs]) -> Choice:
        return Choice(rate.quantize(CENT, rounding=ROUND_HALF_UP), used, sources)

    if policy == "latest":
        lines = _latest(pool, preferred_file)
        return done(_median([o.rate for o in lines]), "latest", lines)
    if policy == "median":
        return done(_median(rates), "median", pool)
    if policy == "trimmed_mean":
        return done(trimmed_mean(rates), "trimmed_mean", pool)
    if policy == "lower_latest_median":
        lines = _latest(pool, preferred_file)
        latest = _median([o.rate for o in lines])
        median = _median(rates)
        return done(latest, "latest", lines) if latest <= median else done(median, "median", pool)
    if policy in ("client_last", "client_median"):
        own = [o for o in pool if same_client(o.client, client)] if client else []
        if not own:
            return done(_median(rates), "median", pool)
        if policy == "client_last":
            lines = _latest(own, preferred_file)
            return done(_median([o.rate for o in lines]), "client_last", lines)
        return done(_median([o.rate for o in own]), "client_median", own)
    raise ValueError(f"Unknown rate policy {policy!r}")


# --- BOQ order and item histories from the library ----------------------------------------------


def _same_file(line_file: str, source_file: str | None) -> bool:
    return bool(source_file) and (line_file == source_file or line_file.endswith(f"/{source_file}"))


def file_order(
    files_by_item: dict[int, set[str]], latest_by_item: dict[int, str]
) -> dict[str, int]:
    """Order all BOQ files from "file X is an item's latest, so it is newer than the item's other
    files". Topological order on those pairs; a cycle is broken at the file with the fewest
    unresolved "older" files. Returns {file: position}, higher = later."""
    newer_than: dict[str, set[str]] = defaultdict(set)  # file -> files it is newer than
    files: set[str] = set()
    for item, item_files in files_by_item.items():
        files |= item_files
        latest = latest_by_item.get(item)
        if latest:
            newer_than[latest] |= item_files - {latest}
    # indegree = how many files must come before (older files not yet placed)
    remaining = {f: set(newer_than.get(f, ())) for f in files}
    order: dict[str, int] = {}
    position = 0
    while remaining:
        ready = sorted(f for f, older in remaining.items() if not older)
        if not ready:  # a cycle: take the file with the fewest open "older" files
            ready = [min(remaining, key=lambda f: (len(remaining[f]), f))]
        for f in ready:
            order[f] = position
            position += 1
            del remaining[f]
        for older in remaining.values():
            older.difference_update(ready)
    return order


@dataclass
class History:
    item_id: int
    unit: str | None
    latest_file: str | None
    lines: list[Obs]


def _root(item_id: int, parent: dict[int, int | None]) -> int:
    seen = set()
    while parent.get(item_id) and item_id not in seen:
        seen.add(item_id)
        item_id = parent[item_id]  # type: ignore[assignment]
    return item_id


def load_histories(db: Session, item_ids: Iterable[int] | None = None) -> dict[int, History]:
    """Item histories (merged duplicates counted in their master). With item_ids, only those
    masters; the file order is always built from the whole library."""
    items = db.execute(
        select(
            LibraryItem.id,
            LibraryItem.merged_into_id,
            LibraryItem.unit,
            LibraryItem.latest_source_file,
        )
    ).all()
    parent = {i.id: i.merged_into_id for i in items}
    latest_src = {i.id: i.latest_source_file for i in items}
    unit = {i.id: i.unit for i in items}
    rows = db.execute(
        select(
            LibraryLine.library_item_id,
            LibraryLine.rate,
            LibraryLine.file,
            LibraryLine.client_folder,
        ).where(
            LibraryLine.rate.is_not(None),
            LibraryLine.library_item_id.is_not(None),
            ~LibraryLine.is_competitor,
            ~LibraryLine.is_excluded,
        )
    ).all()
    files_by_item: dict[int, set[str]] = defaultdict(set)
    raw: dict[int, list[tuple[Decimal, str, str | None]]] = defaultdict(list)
    for item_id, rate, file, client in rows:
        root = _root(item_id, parent)
        files_by_item[root].add(file)
        raw[root].append((rate, file, client))
    latest_file: dict[int, str] = {}
    for root, item_files in files_by_item.items():
        src = latest_src.get(root)
        match = next((f for f in sorted(item_files) if _same_file(f, src)), None)
        if match:
            latest_file[root] = match
    order = file_order(files_by_item, latest_file)
    wanted = set(item_ids) if item_ids is not None else None
    return {
        root: History(
            root,
            unit.get(root),
            latest_file.get(root),
            [Obs(r, f, c, order.get(f, 0)) for r, f, c in obs],
        )
        for root, obs in raw.items()
        if wanted is None or root in wanted
    }


# --- backtest -----------------------------------------------------------------------------------


@dataclass
class Score:
    policy: str
    lines: int = 0
    covered: int = 0
    within5: int = 0
    within10: int = 0
    within20: int = 0
    above10: int = 0
    errors: list[Decimal] = field(default_factory=list)

    def add(self, suggested: Decimal | None, actual: Decimal) -> None:
        self.lines += 1
        if suggested is None:
            return
        self.covered += 1
        err = (suggested - actual) / actual * 100
        self.errors.append(abs(err))
        self.within5 += abs(err) <= 5
        self.within10 += abs(err) <= 10
        self.within20 += abs(err) <= 20
        self.above10 += err > 10

    def row(self) -> dict[str, float | int | str]:
        pct = lambda n: round(100 * n / self.covered, 1) if self.covered else 0.0  # noqa: E731
        return {
            "policy": self.policy,
            "within_5": pct(self.within5),
            "within_10": pct(self.within10),
            "within_20": pct(self.within20),
            "median_abs_error": round(float(statistics.median(self.errors)), 1)
            if self.errors
            else 0.0,
            "above_by_10": pct(self.above10),
            "coverage": round(100 * self.covered / self.lines, 1) if self.lines else 0.0,
            "lines": self.lines,
        }


def backtest(
    histories: dict[int, History], policies: Iterable[str] = tuple(POLICIES), unlinked: int = 0
) -> list[dict]:
    """Leave-one-BOQ-out: every line is suggested from its item's lines in *other* BOQ files.
    `unlinked` lines (no library item) count as lines without a suggestion."""
    scores = {p: Score(p) for p in policies}
    for h in histories.values():
        for target in h.lines:
            if target.rate <= 0:
                continue
            pool = [o for o in h.lines if o.file != target.file]
            preferred = h.latest_file if h.latest_file != target.file else None
            for p, s in scores.items():
                c = choose(p, pool, target.client, preferred)
                s.add(c.rate if c else None, target.rate)
    for s in scores.values():
        s.lines += unlinked
    return [s.row() for s in scores.values()]


def winner(rows: list[dict]) -> str:
    """Most lines within ±10%; ties go to fewer over-quotes (suggesting high loses tenders)."""
    return max(rows, key=lambda r: (r["within_10"], -r["above_by_10"], -r["median_abs_error"]))[
        "policy"
    ]
