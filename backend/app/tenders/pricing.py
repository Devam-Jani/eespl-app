"""Pricing a tender's BOQ: amounts, totals, margins and automatic rate suggestions.

Money rule (same as the rate build-up): Decimal throughout, ROUND_HALF_UP to 2 places only on
the final figure (a line's rate when it comes from cost × margin, its amount, the GST).

Suggest (for every line that is unpriced or only suggested; priced and not-quoted lines are never
touched), candidates from two places, each scored 0..1:

- Systems. The system's name is matched against the line's description the way the rate library
  matches a query: coverage = share of the name's words (with trade synonyms, prefix match for 5+
  letters) found among the line's stemmed words, similarity = word_similarity(name, line).
  score = coverage² × (0.6 + 0.4 × similarity). Rate = the system's build-up at its own margin.
- Rate library. The existing library search (excluded and competitor items left out) is run
  with a short query made from the line (its title, or its first 14 significant words); each hit
  is re-scored against the whole description:
  score = 0.5 × search score + 0.5 × similarity(line description, item description).
  Rate = the company's rate policy (app.masters.rate_policy, chosen by backtest) applied to the
  item's past lines; each library candidate carries that history in `details`.

Both need the line's unit: the same unit, or one convert() can reach (the rate is converted).
The top three candidates are kept per line; the best becomes the suggestion only if its score
reaches the threshold (company setting, default 0.55).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.masters.conversions import ConversionError, Rule, convert_with
from app.masters.models import CompanyProfile, System, UnitConversion
from app.masters.rate import MissingPriceError, system_rate
from app.masters.rate_policy import POLICIES, History, Obs, choose, load_histories, same_channel
from app.masters.search import STOPWORDS, SYNONYMS, search_library
from app.tenders.models import BoqLine, BoqLineCandidate, BoqSection, Tender

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
DEFAULT_THRESHOLD = Decimal("0.55")
MAX_CANDIDATES = 3
QUERY_WORDS = 14
LIBRARY_POOL = 15


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --- amounts, margins, totals ------------------------------------------------------------------


def line_amount(line: BoqLine) -> Decimal | None:
    """qty × rate; none for QRO / NQ lines or lines without a quantity or rate."""
    if line.qty_note or line.qty is None or line.rate is None:
        return None
    return money(line.qty * line.rate)


def refresh_amount(line: BoqLine) -> None:
    line.amount = line_amount(line)


def rate_from_margin(cost_rate: Decimal, margin_percent: Decimal) -> Decimal:
    return money(cost_rate * (1 + margin_percent / HUNDRED))


def apply_margin(line: BoqLine, margin_percent: Decimal) -> bool:
    """Re-price a system-priced line at a new margin. Library and manual lines have no cost, so
    the margin does not apply to them (returns False)."""
    if line.source != "system" or line.cost_rate is None:
        return False
    line.margin_percent = margin_percent
    line.rate = rate_from_margin(line.cost_rate, margin_percent)
    refresh_amount(line)
    return True


@dataclass
class Totals:
    sections: dict[int | None, Decimal]
    subtotal: Decimal
    gst_percent: Decimal
    gst: Decimal
    grand_total: Decimal
    # cost of the lines that have one (system-priced) and their amount minus that cost;
    # None when no line is system-priced. tender.margin only.
    cost_total: Decimal | None
    margin_total: Decimal | None
    counts: dict[str, int]


def tender_totals(db: Session, tender: Tender) -> Totals:
    lines = db.scalars(select(BoqLine).where(BoqLine.tender_id == tender.id)).all()
    profile = db.get(CompanyProfile, 1)
    gst_percent = profile.default_gst_percent if profile else Decimal(18)
    sections: dict[int | None, Decimal] = {}
    subtotal = Decimal(0)
    cost_total = Decimal(0)
    margin_total = Decimal(0)
    costed = 0
    counts = {s: 0 for s in ("unpriced", "suggested", "priced", "not_quoted")}
    counts.update(qro=0, nq=0)
    for ln in lines:
        counts[ln.status] += 1
        if ln.qty_note == "QRO":
            counts["qro"] += 1
        if ln.qty_note == "NQ":
            counts["nq"] += 1
        if ln.amount is not None:  # QRO / NQ lines have no amount: excluded from totals
            sections[ln.section_id] = sections.get(ln.section_id, Decimal(0)) + ln.amount
            subtotal += ln.amount
            if ln.cost_rate is not None and ln.qty is not None:
                cost = ln.qty * ln.cost_rate
                costed += 1
                cost_total += cost
                margin_total += ln.amount - cost
    gst = money(subtotal * gst_percent / HUNDRED)
    return Totals(
        sections,
        subtotal,
        gst_percent,
        gst,
        subtotal + gst,
        money(cost_total) if costed else None,
        money(margin_total) if costed else None,
        counts,
    )


def refresh_tender_total(db: Session, tender: Tender) -> Totals:
    db.flush()
    totals = tender_totals(db, tender)
    tender.quoted_total = totals.subtotal
    return totals


# --- suggestions -------------------------------------------------------------------------------


@dataclass
class Candidate:
    source: str  # "system" | "library"
    ref_id: int
    rate: Decimal
    cost_rate: Decimal | None
    margin_percent: Decimal | None
    score: float
    reason: str
    details: dict[str, Any] | None = None


@dataclass
class SuggestResult:
    lines_considered: int = 0
    suggested: int = 0
    left_unpriced: int = 0
    skipped_priced: int = 0
    threshold: Decimal = DEFAULT_THRESHOLD


@dataclass
class PolicyContext:
    """What a library rate needs: the policy, the tender's channel and the item histories."""

    policy: str
    channel: str | None
    histories: dict[int, History] = field(default_factory=dict)


WARN_ABOVE_MEDIAN = Decimal("0.15")
MAX_SOURCES = 12


def rate_policy(db: Session) -> str:
    profile = db.get(CompanyProfile, 1)
    policy = profile.rate_policy if profile else None
    return policy if policy in POLICIES else "channel_median"


def _s(value: Decimal | None) -> str | None:
    return str(money(Decimal(value))) if value is not None else None


def library_rate(hit: dict[str, Any], ctx: PolicyContext) -> tuple[Decimal, dict[str, Any]] | None:
    """The rate for a library item under the policy, and the history behind it. Items whose
    lines are not in the library (only summary statistics) fall back to those statistics."""
    history = ctx.histories.get(hit["id"])
    pool = history.lines if history else []
    if pool:
        choice = choose(ctx.policy, pool, ctx.channel, history.latest_file)
        rates = sorted(o.rate for o in pool)
        latest = choose("latest", pool, None, history.latest_file)
        median = choose("median", pool)
        own = [o for o in pool if ctx.channel and same_channel(o.channel, ctx.channel)]
        channel_last = choose("latest", own, None, history.latest_file) if own else None
        rate = choice.rate
        sources: list[Obs] = sorted(choice.sources, key=lambda o: -o.order)
        details = {
            "policy": ctx.policy,
            "used": choice.policy,
            "latest_rate": _s(latest.rate),
            "median_rate": _s(median.rate),
            "min_rate": _s(rates[0]),
            "max_rate": _s(rates[-1]),
            "n_boqs": len({o.file for o in pool}),
            "channel_last_rate": _s(channel_last.rate) if channel_last else None,
            "sources": [
                {
                    "channel": o.channel,
                    "file": o.file.rsplit("/", 1)[-1],
                    "date": None,
                    "rate": _s(o.rate),
                }
                for o in sources[:MAX_SOURCES]
            ],
            "sources_total": len(sources),
        }
    else:
        base = hit["median_rate"] if ctx.policy != "latest" else hit["latest_rate"]
        base = base if base is not None else (hit["latest_rate"] or hit["median_rate"])
        if base is None:
            return None
        rate = money(Decimal(base))
        details = {
            "policy": ctx.policy,
            "used": "median" if base == hit["median_rate"] else "latest",
            "latest_rate": _s(hit["latest_rate"]),
            "median_rate": _s(hit["median_rate"]),
            "min_rate": _s(hit.get("min_rate")),
            "max_rate": _s(hit.get("max_rate")),
            "n_boqs": hit["boq_count"],
            "channel_last_rate": None,
            "sources": [],
            "sources_total": 0,
        }
    median = Decimal(details["median_rate"]) if details["median_rate"] else None
    above = (rate - median) / median if median else None
    details["above_median_percent"] = str(round(above * 100, 1)) if above is not None else None
    details["warning"] = bool(above is not None and above > WARN_ABOVE_MEDIAN)
    return rate, details


def threshold(db: Session) -> Decimal:
    profile = db.get(CompanyProfile, 1)
    return profile.pricing_threshold if profile else DEFAULT_THRESHOLD


def _words(text_: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text_.lower()) if w not in STOPWORDS]


def condensed_query(description: str) -> str:
    """The line's title if it has one ("TITLE — details"), else its first 14 significant words."""
    title = description.split(" — ")[0]
    words = _words(title)
    if 2 <= len(words) <= QUERY_WORDS:
        return " ".join(words)
    return " ".join(_words(description)[:QUERY_WORDS])


def search_queries(description: str) -> list[str]:
    """Library searches for one line: its title, and for "Parent — item" lines the item's own
    text too (a sub-item's words matter more than its section's)."""
    queries = [condensed_query(description)]
    parts = description.split(" — ")
    if len(parts) > 1:
        queries.append(" ".join(_words(parts[-1])[:QUERY_WORDS]))
    return [q for q in dict.fromkeys(queries) if q]


def _lexemes(db: Session, texts: list[str]) -> list[set[str]]:
    rows = db.execute(
        text("SELECT strip(to_tsvector('english', t))::text FROM unnest(CAST(:t AS text[])) t"),
        {"t": texts},
    ).scalars()
    return [set(re.findall(r"'([^']+)'", r or "")) for r in rows]


def _unit_factor(
    rules: list[Rule], line_unit: str | None, other_unit: str | None
) -> Decimal | None:
    """Multiplier turning a rate per `other_unit` into a rate per `line_unit`."""
    if line_unit is None or other_unit is None:
        return Decimal(1) if line_unit == other_unit else None
    if line_unit == other_unit:
        return Decimal(1)
    try:
        # rate per line unit = rate per other unit × (how many other units in one line unit)
        return convert_with(rules, Decimal(1), line_unit, other_unit)
    except ConversionError:
        return None


class _SystemMatcher:
    """Matches system names against line descriptions."""

    def __init__(self, db: Session, systems: list[System], rules: list[Rule]):
        self.db = db
        self.rules = rules
        self.systems = []
        for system in systems:
            try:
                b = system_rate(db, system)
            except MissingPriceError:
                continue  # no current price: cannot be offered
            words = list(dict.fromkeys(_words(system.name)))
            if not words:
                continue
            groups = [sorted(SYNONYMS.get(w, {w})) for w in words]
            self.systems.append((system, b, groups))
        variants = sorted({v for _, _, gs in self.systems for g in gs for v in g})
        stems = _lexemes(db, variants) if variants else []
        self.stem = {v: (next(iter(s)) if s else v) for v, s in zip(variants, stems, strict=True)}

    def candidates(self, line: BoqLine, line_lexemes: set[str]) -> list[Candidate]:
        if not self.systems:
            return []
        names = [s.name for s, _, _ in self.systems]
        similarity = (
            self.db.execute(
                text("SELECT word_similarity(n, :line) FROM unnest(CAST(:n AS text[])) n"),
                {"n": names, "line": line.description},
            )
            .scalars()
            .all()
        )
        out = []
        for (system, b, groups), sim in zip(self.systems, similarity, strict=True):
            matched = 0
            for group in groups:
                for v in group:
                    stem = self.stem.get(v, v)
                    if stem in line_lexemes or (
                        len(v) >= 5 and any(lx.startswith(stem) for lx in line_lexemes)
                    ):
                        matched += 1
                        break
            coverage = matched / len(groups)
            score = coverage**2 * (0.6 + 0.4 * float(sim))
            if score <= 0:
                continue
            factor = _unit_factor(self.rules, line.unit, system.unit)
            if factor is None:
                continue
            out.append(
                Candidate(
                    source="system",
                    ref_id=system.id,
                    rate=money(b.rate * factor),
                    cost_rate=money(b.base_cost * factor),
                    margin_percent=b.margin_percent,
                    score=round(score, 4),
                    reason=f"System {system.code} “{system.name}”, {matched}/{len(groups)} words",
                )
            )
        return out


def _library_candidates(
    db: Session, line: BoqLine, rules: list[Rule], ctx: PolicyContext
) -> list[Candidate]:
    found: dict[int, dict] = {}
    for query in search_queries(line.description):
        for h in search_library(db, query, unit=None, limit=LIBRARY_POOL, cut=False).items:
            if h["id"] not in found or h["score"] > found[h["id"]]["score"]:
                found[h["id"]] = h
    if not found:
        return []
    hits = list(found.values())
    own_text = line.description.split(" — ")[-1]
    sims = dict(
        db.execute(
            text(
                "SELECT id, greatest(similarity(description, :d), similarity(description, :o)) "
                "FROM library_items WHERE id = ANY(:ids)"
            ),
            {"d": line.description, "o": own_text, "ids": list(found)},
        ).all()
    )
    out = []
    for h in hits:
        if h["is_competitor"] or h["is_excluded"]:
            continue
        factor = _unit_factor(rules, line.unit, h["unit"])
        if factor is None:
            continue  # different unit and no conversion: never offered
        priced = library_rate(h, ctx)
        if priced is None:
            continue
        base, details = priced
        if factor != 1:
            details = {**details, "unit_factor": str(factor)}
        score = 0.5 * float(h["score"]) + 0.5 * float(sims.get(h["id"], 0))
        out.append(
            Candidate(
                source="library",
                ref_id=h["id"],
                rate=money(Decimal(base) * factor),
                cost_rate=None,
                margin_percent=None,
                score=round(score, 4),
                reason=f"Rate library: {POLICIES[details['used']].lower()}, "
                f"{details['n_boqs']} BOQs",
                details=details,
            )
        )
    return out


def suggest(
    db: Session, tender: Tender, lines: Iterable[BoqLine] | None = None, user_id=None
) -> SuggestResult:
    limit = threshold(db)
    result = SuggestResult(threshold=limit)
    rules = [
        Rule(r.from_unit, r.to_unit, r.factor, None)
        for r in db.scalars(select(UnitConversion).where(UnitConversion.product_id.is_(None)))
    ]
    systems = list(db.scalars(select(System).where(System.is_active)))
    matcher = _SystemMatcher(db, systems, rules)
    ctx = PolicyContext(rate_policy(db), tender.channel.name if tender.channel else None)
    ctx.histories = load_histories(db)
    lines = (
        list(lines)
        if lines is not None
        else list(
            db.scalars(
                select(BoqLine).where(BoqLine.tender_id == tender.id).order_by(BoqLine.sort_order)
            )
        )
    )
    todo = [ln for ln in lines if ln.status in ("unpriced", "suggested")]
    result.skipped_priced = sum(1 for ln in lines if ln.status == "priced")
    lexemes = _lexemes(db, [ln.description for ln in todo]) if todo else []
    for line, line_lexemes in zip(todo, lexemes, strict=True):
        result.lines_considered += 1
        found = matcher.candidates(line, line_lexemes) + _library_candidates(db, line, rules, ctx)
        found.sort(key=lambda c: (-c.score, c.source != "system", c.ref_id))
        best = found[:MAX_CANDIDATES]
        line.candidates = [
            BoqLineCandidate(
                rank=i,
                source=c.source,
                ref_id=c.ref_id,
                rate=c.rate,
                cost_rate=c.cost_rate,
                margin_percent=c.margin_percent,
                score=Decimal(str(c.score)),
                reason=c.reason,
                details=c.details,
                created_by=user_id,
            )
            for i, c in enumerate(best, start=1)
        ]
        if best and Decimal(str(best[0].score)) >= limit:
            use_candidate(line, line.candidates[0], status="suggested")
            result.suggested += 1
        else:
            clear_pricing(line)
            result.left_unpriced += 1
    refresh_tender_total(db, tender)
    return result


def use_candidate(line: BoqLine, candidate: BoqLineCandidate, status: str = "priced") -> None:
    line.source = candidate.source
    line.system_id = candidate.ref_id if candidate.source == "system" else None
    line.library_item_id = candidate.ref_id if candidate.source == "library" else None
    line.cost_rate = candidate.cost_rate
    line.margin_percent = candidate.margin_percent
    line.rate = candidate.rate
    line.suggestion_score = candidate.score
    line.status = status
    refresh_amount(line)


def clear_pricing(line: BoqLine) -> None:
    line.source = line.system_id = line.library_item_id = None
    line.cost_rate = line.margin_percent = line.rate = line.amount = None
    line.suggestion_score = None
    line.status = "unpriced"


def section_titles(db: Session, tender: Tender) -> dict[int, str]:
    return dict(
        db.execute(select(BoqSection.id, BoqSection.title).where(BoqSection.tender_id == tender.id))
    )
