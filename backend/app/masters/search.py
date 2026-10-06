"""Rate library search: full-text rank combined with trigram word similarity.

1. Full text (GIN on search_vector, a few ms). Each query word becomes a group of tsquery terms:
   the word itself (stemmed; prefix-matched when it has 5+ letters, so "crystal" finds
   "crystalline") plus a few trade synonyms ("bathroom" also matches "toilet", "app" also
   "atactic"). Items matching any group are candidates; the best `POOL` by coverage
   (how many groups matched) and ts_rank_cd go on to step 2.
2. Trigram: word_similarity(query, description) is computed for those candidates only; it is
   too slow to run over every long description in the library.
3. score = 0.5 × coverage + 0.2 × text rank + 0.15 × word similarity + 0.15 × popularity,
   where text rank is ts_rank_cd normalised by document length (so a long specification that
   mentions every word in passing does not beat a short item that is about them) and
   popularity = log(1 + BOQs the item was priced in), capped at 20 BOQs.
4. Typo fallback: if full text finds fewer than `limit` items, the trigram index
   (ix_library_items_description_trgm, `<%`) adds the closest spellings.
"""

import math
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

COVERAGE_WEIGHT = 0.5
TEXT_WEIGHT = 0.2
TRGM_WEIGHT = 0.15
POPULARITY_WEIGHT = 0.15
POPULAR_BOQ_COUNT = 20  # items priced in this many BOQs get the full popularity boost
PREFIX_MIN_LENGTH = 5
FALLBACK_SIMILARITY = 0.6

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
    i.latest_client, i.product_make, i.needs_check, i.check_note
"""
UNIT_FILTER = "(CAST(:unit AS text) IS NULL OR i.unit = :unit)"


def query_groups(query: str) -> list[str]:
    """'Bathroom waterproofing' -> ["bath | bathroom | ... | toilet", "waterproofing:*"]."""
    groups = []
    for word in dict.fromkeys(re.findall(r"[a-z0-9]+", query.lower())):
        if word in STOPWORDS:
            continue
        variants = sorted(SYNONYMS.get(word, {word}))
        groups.append(" | ".join(f"{v}:*" if len(v) >= PREFIX_MIN_LENGTH else v for v in variants))
    return groups


def _fulltext_sql(group_count: int) -> str:
    matched = " + ".join(
        f"(i.search_vector @@ to_tsquery('english', :g{n}))::int" for n in range(group_count)
    )
    return f"""
        WITH candidates AS (
            SELECT i.id,
                   {matched} AS matched,
                   ts_rank_cd(i.search_vector, to_tsquery('english', :any_group), 1 | 32)
                       AS text_rank
            FROM library_items i
            WHERE i.search_vector @@ to_tsquery('english', :any_group)
              AND {UNIT_FILTER}
            ORDER BY matched DESC, text_rank DESC, i.boq_count DESC
            LIMIT :pool
        )
        SELECT {ITEM_COLUMNS},
               c.matched, c.text_rank,
               word_similarity(:query, i.description) AS similarity
        FROM candidates c
        JOIN library_items i ON i.id = c.id
    """


FALLBACK_SQL = text(
    f"""
    SELECT {ITEM_COLUMNS},
           0 AS matched, 0.0 AS text_rank,
           word_similarity(:query, i.description) AS similarity
    FROM library_items i
    WHERE :query <% i.description
      AND {UNIT_FILTER}
      AND NOT (i.id = ANY(:exclude))
    ORDER BY similarity DESC, i.boq_count DESC
    LIMIT :limit
    """
)

BROWSE_SQL = text(
    f"""
    SELECT {ITEM_COLUMNS}, 0 AS matched, 0.0 AS text_rank, 0.0 AS similarity
    FROM library_items i
    WHERE {UNIT_FILTER}
    ORDER BY i.boq_count DESC, i.id
    LIMIT :limit
    """
)


def _score(row: dict[str, Any], group_count: int) -> float:
    coverage = row["matched"] / group_count if group_count else 0.0
    return (
        COVERAGE_WEIGHT * coverage
        + TEXT_WEIGHT * float(row["text_rank"])
        + TRGM_WEIGHT * float(row["similarity"])
        + POPULARITY_WEIGHT * min(1.0, math.log1p(row["boq_count"]) / math.log1p(POPULAR_BOQ_COUNT))
    )


def search_library(db: Session, query: str, unit: str | None, limit: int) -> list[dict[str, Any]]:
    """Best `limit` library items for `query`, optionally only those in `unit`."""
    query = " ".join(query.split())
    groups = query_groups(query)
    if not groups:
        rows = db.execute(BROWSE_SQL, {"unit": unit, "limit": limit}).mappings().all()
        return [{**r, "score": 0.0} for r in rows]

    params: dict[str, Any] = {f"g{n}": g for n, g in enumerate(groups)}
    params.update(
        any_group=" | ".join(f"({g})" for g in groups),
        query=query,
        unit=unit,
        pool=max(limit * 5, 100),
    )
    rows = [dict(r) for r in db.execute(text(_fulltext_sql(len(groups))), params).mappings()]

    if len(rows) < limit:
        db.execute(
            text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
            {"t": str(FALLBACK_SIMILARITY)},
        )
        rows += [
            dict(r)
            for r in db.execute(
                FALLBACK_SQL,
                {
                    "query": query,
                    "unit": unit,
                    "exclude": [r["id"] for r in rows],
                    "limit": limit - len(rows),
                },
            ).mappings()
        ]

    for r in rows:
        r["score"] = _score(r, len(groups))
    rows.sort(key=lambda r: (-r["score"], -r["boq_count"], r["id"]))
    return rows[:limit]
