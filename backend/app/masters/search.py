"""Rate library search: full-text rank combined with trigram word similarity.

1. Words. Each significant query word becomes a group of tsquery terms: the word itself
   (stemmed; prefix-matched when it has 5+ letters, so "crystal" finds "crystalline") plus a
   few trade synonyms ("bathroom" also matches "toilet", "app" also "atactic"). Filler words
   ("based", "type", "and"...) are dropped.
2. Typos. A word that matches nothing anywhere in the library ("sleeeve") is treated as a
   possible misspelling: it is matched by trigram word similarity instead (>= 0.6), and items
   close to it are added as candidates through the trigram index.
3. Candidates. Items matching any word in full text (GIN on search_vector), best first by how
   many words they match, plus the typo candidates. Only items that are not merged into another
   item, not excluded and not competitor rates, unless the caller asks for those.
4. Score. coverage = share of query words the item matches. Then
       score = coverage² × (0.55 + 0.20 × similarity + 0.15 × popularity + 0.10 × text rank)
   similarity = word_similarity(query, description); popularity = log(1 + BOQs), full at 20
   BOQs; text rank = ts_rank_cd normalised by document length. Squaring coverage makes items
   that only mention one of the words in passing fall well below the ones about all of them.
5. Relevance cut (first page only): keep results scoring at least 35% of the top score, but
   at least 10 when there are 10. "Show more" (offset > 0, or cut=False) pages through the
   full ranking without the cut.
"""

import math
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

BASE_WEIGHT = 0.55
TRGM_WEIGHT = 0.20
POPULARITY_WEIGHT = 0.15
TEXT_WEIGHT = 0.10
POPULAR_BOQ_COUNT = 20
PREFIX_MIN_LENGTH = 5
TYPO_MIN_LENGTH = 4
TYPO_SIMILARITY = 0.6
CUT_RATIO = 0.35
CUT_MINIMUM = 10

STOPWORDS = frozenset(
    # common English words plus BOQ filler that says nothing about the item ("PU based", "X type")
    "a an and as at by for from in into of on or per the to with based type".split()
)

# Words that mean the same thing in EESPL's BOQs. Each word in a group also matches the others.
SYNONYM_GROUPS = [
    {"bathroom", "bathrooms", "bath", "toilet", "toilets", "washroom", "wc"},
    {"app", "atactic"},
    {"pu", "polyurethane"},
    {"sbs", "styrene"},
    {"hdpe", "polyethylene"},
    {"terrace", "roof"},
    {"sump", "tank"},
]
SYNONYMS = {word: group for group in SYNONYM_GROUPS for word in group}

ITEM_COLUMNS = """
    i.id, i.description, i.unit, i.unit_raw, i.boq_count,
    i.latest_rate, i.min_rate, i.median_rate, i.max_rate,
    i.latest_channel, i.product_make, i.needs_check, i.check_note,
    i.is_excluded, i.excluded_reason, i.is_competitor
"""
FILTERS = """
    i.merged_into_id IS NULL
    AND (CAST(:unit AS text) IS NULL OR i.unit = :unit)
    AND (:include_flagged OR NOT i.is_excluded)
    AND (:include_competitor OR NOT i.is_competitor)
"""


@dataclass
class SearchResult:
    items: list[dict[str, Any]]
    has_more: bool
    cut_applied: bool


def query_words(query: str) -> list[str]:
    return [
        w for w in dict.fromkeys(re.findall(r"[a-z0-9]+", query.lower())) if w not in STOPWORDS
    ]


def tsquery_group(word: str) -> str:
    """'bathroom' -> 'bath | bathroom | ... | toilet:* | ...' (safe for to_tsquery)."""
    variants = sorted(SYNONYMS.get(word, {word}))
    return " | ".join(f"{v}:*" if len(v) >= PREFIX_MIN_LENGTH else v for v in variants)


def _typo_words(db: Session, words: list[str], groups: list[str]) -> set[int]:
    """Indexes of words that match nothing anywhere in the library (likely misspellings)."""
    checks = ", ".join(
        f"EXISTS (SELECT 1 FROM library_items WHERE search_vector @@ to_tsquery('english', :g{n}))"
        for n in range(len(groups))
    )
    found = db.execute(text(f"SELECT {checks}"), {f"g{n}": g for n, g in enumerate(groups)}).one()
    return {
        n
        for n, (word, hit) in enumerate(zip(words, found, strict=True))
        if not hit and len(word) >= TYPO_MIN_LENGTH and not word.isdigit()
    }


def _search_sql(group_count: int, typos: set[int]) -> str:
    def matched(n: int) -> str:
        ft = f"i.search_vector @@ to_tsquery('english', :g{n})"
        if n in typos:
            return f"({ft} OR word_similarity(:w{n}, i.description) >= {TYPO_SIMILARITY})::int"
        return f"({ft})::int"

    ft_matched = " + ".join(
        f"(i.search_vector @@ to_tsquery('english', :g{n}))::int" for n in range(group_count)
    )
    fuzzy = (
        f"""
        UNION
        (SELECT i.id FROM library_items i
         WHERE ({" OR ".join(f":w{n} <% i.description" for n in sorted(typos))}) AND {FILTERS}
         LIMIT :pool)
        """
        if typos
        else ""
    )
    return f"""
        WITH candidates AS (
            (SELECT i.id FROM library_items i
             WHERE i.search_vector @@ to_tsquery('english', :any_group) AND {FILTERS}
             ORDER BY {ft_matched} DESC,
                      ts_rank_cd(i.search_vector, to_tsquery('english', :any_group), 1 | 32) DESC,
                      i.boq_count DESC
             LIMIT :pool)
            {fuzzy}
        )
        SELECT {ITEM_COLUMNS},
               {" + ".join(matched(n) for n in range(group_count))} AS matched,
               ts_rank_cd(i.search_vector, to_tsquery('english', :any_group), 1 | 32)
                   AS text_rank,
               word_similarity(:query, i.description) AS similarity
        FROM candidates c
        JOIN library_items i ON i.id = c.id
    """


BROWSE_SQL = text(
    f"""
    SELECT {ITEM_COLUMNS}, 0 AS matched, 0.0 AS text_rank, 0.0 AS similarity
    FROM library_items i
    WHERE {FILTERS}
    ORDER BY i.boq_count DESC, i.id
    LIMIT :limit OFFSET :offset
    """
)


def score(row: dict[str, Any], word_count: int) -> float:
    coverage = row["matched"] / word_count if word_count else 0.0
    popularity = min(1.0, math.log1p(row["boq_count"]) / math.log1p(POPULAR_BOQ_COUNT))
    return coverage**2 * (
        BASE_WEIGHT
        + TRGM_WEIGHT * float(row["similarity"])
        + POPULARITY_WEIGHT * popularity
        + TEXT_WEIGHT * float(row["text_rank"])
    )


def relevance_cut(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Results scoring at least CUT_RATIO of the best one; never fewer than CUT_MINIMUM."""
    if not ranked:
        return []
    floor = ranked[0]["score"] * CUT_RATIO
    kept = [r for r in ranked if r["score"] >= floor]
    if len(kept) < CUT_MINIMUM:
        kept = ranked[:CUT_MINIMUM]
    return kept[:limit]


def search_library(
    db: Session,
    query: str,
    unit: str | None = None,
    limit: int = 25,
    offset: int = 0,
    include_flagged: bool = False,
    include_competitor: bool = False,
    cut: bool = True,
) -> SearchResult:
    query = " ".join(query.split())
    words = query_words(query)
    filters = {
        "unit": unit,
        "include_flagged": include_flagged,
        "include_competitor": include_competitor,
    }
    if not words:
        rows = db.execute(BROWSE_SQL, {**filters, "limit": limit + 1, "offset": offset}).mappings()
        rows = [{**r, "score": 0.0} for r in rows]
        return SearchResult(rows[:limit], has_more=len(rows) > limit, cut_applied=False)

    groups = [tsquery_group(w) for w in words]
    typos = _typo_words(db, words, groups)
    params: dict[str, Any] = {
        **filters,
        **{f"g{n}": g for n, g in enumerate(groups)},
        **{f"w{n}": words[n] for n in typos},
        "any_group": " | ".join(f"({g})" for g in groups),
        "query": query,
        "pool": max(200, (offset + limit) * 2),
    }
    if typos:
        db.execute(
            text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
            {"t": str(TYPO_SIMILARITY)},
        )
    rows = db.execute(text(_search_sql(len(groups), typos)), params).mappings()
    ranked = [dict(r) for r in rows]
    for r in ranked:
        r["score"] = score(r, len(groups))
    ranked.sort(key=lambda r: (-r["score"], -r["boq_count"], r["id"]))

    if cut and offset == 0:
        page = relevance_cut(ranked, limit)
        return SearchResult(page, has_more=len(ranked) > len(page), cut_applied=True)
    page = ranked[offset : offset + limit]
    return SearchResult(page, has_more=len(ranked) > offset + limit, cut_applied=False)
