"""Rate library rules: excluded working rows, competitor rates, the relevance cut, manual
edits that survive re-imports, and merge / unmerge."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.masters.importers import import_library
from app.masters.library import REASON_BELOW_ONE, REASON_WORKING_ROW, exclusion_reason
from app.masters.models import LibraryItem, LibraryLine
from app.masters.search import relevance_cut
from app.models import AuditLog

WORKBOOK = Path(__file__).parent / "fixtures" / "rate_library_sample.xlsx"


def _item(db, prefix, unit="__any__"):
    query = select(LibraryItem).where(LibraryItem.description.startswith(prefix))
    if unit != "__any__":
        query = query.where(LibraryItem.unit == unit)
    return db.scalars(query).one()


@pytest.fixture
def library(db):
    import_library(db, WORKBOOK)
    return db


@pytest.mark.parametrize(
    ("text", "rate", "reason"),
    [
        ("Margin — Pipe sleeve 110 mm", Decimal("0.3"), REASON_WORKING_ROW),
        ("MARGIN — RATE", Decimal("850"), REASON_WORKING_ROW),
        ("Working — Labour", Decimal("120"), REASON_WORKING_ROW),
        ("Sub total", Decimal("5000"), REASON_WORKING_ROW),
        ("Sub-Total of section A", None, REASON_WORKING_ROW),
        ("Total", Decimal("1"), REASON_WORKING_ROW),
        ("Hacking of plaster", Decimal("0.99"), REASON_BELOW_ONE),
        ("Hacking of plaster", Decimal("1"), None),
        ("Totally waterproof coating", Decimal("100"), None),  # 'Total' must be a whole word
        ("Providing margin strips at edges", Decimal("100"), None),  # only at the start
    ],
)
def test_exclusion_rules(text, rate, reason):
    assert exclusion_reason(text, rate=rate) == reason


def test_import_flags_excluded_and_competitor_items_without_deleting(library):
    margin = _item(library, "Margin — Pipe sleeve")
    assert margin.is_excluded and margin.excluded_reason == REASON_WORKING_ROW
    hacking = _item(library, "Hacking and cleaning")
    assert hacking.is_excluded and hacking.excluded_reason == REASON_BELOW_ONE
    competitor = _item(library, "Crystalline coating to water tank")
    assert competitor.is_competitor and not competitor.is_excluded

    lines = {(ln.file, ln.row): ln for ln in library.scalars(select(LibraryLine))}
    assert lines[("CLIENT D/d.xlsx", 20)].is_excluded  # parent item "Margin"
    assert lines[("CLIENT E/e.xlsx", 5)].is_competitor
    assert not lines[("CLIENT A/a.xlsx", 10)].is_excluded


def test_search_hides_flagged_and_competitor_items_by_default(library, login_as):
    client, headers = login_as("sales")

    def search(q, **params):
        r = client.get("/api/library/search", params={"q": q, **params}, headers=headers)
        assert r.status_code == 200, r.text
        return {i["description"]: i for i in r.json()["items"]}

    assert "Margin — Pipe sleeve 110 mm" not in search("pipe sleeve")
    flagged = search("pipe sleeve", include_flagged=True)["Margin — Pipe sleeve 110 mm"]
    assert flagged["is_excluded"] and flagged["suggested_rate"] is None
    assert flagged["excluded_reason"] == REASON_WORKING_ROW

    assert not any(i["is_competitor"] for i in search("crystalline").values())
    shown = search("crystalline", include_competitor=True)
    other = shown["Crystalline coating to water tank walls with two coats"]
    assert other["is_competitor"]
    assert other["suggested_rate"] is None  # never offered as our rate
    assert other["latest_rate"] == "150.0000"  # the figures are still visible, flagged
    assert other["check_note"] == "comparative sheet (may be other bidders)"
    assert other["unit"] == "sqm"


def test_relevance_cut_keeps_the_top_items():
    rows = [{"id": i, "score": s} for i, s in enumerate(
        [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.45, 0.4, 0.35, 0.33, 0.32, 0.31, 0.2, 0.1, 0.05]
    )]  # fmt: skip
    # 35% of 0.9 = 0.315: eleven pass
    assert [r["id"] for r in relevance_cut(rows, 25)] == list(range(11))
    assert len(relevance_cut(rows, 5)) == 5  # still capped by the page size
    # a sharp drop after two strong hits: the minimum of 10 still applies
    steep = [{"id": i, "score": s} for i, s in enumerate([1.0, 0.95] + [0.1] * 13)]
    assert len(relevance_cut(steep, 25)) == 10
    assert relevance_cut(steep[:4], 25) == steep[:4]  # fewer than 10 available: all of them
    assert relevance_cut([], 25) == []


def test_show_more_pages_past_the_cut(library, login_as):
    client, headers = login_as("sales")
    first = client.get(
        "/api/library/search", params={"q": "pipe", "limit": 2}, headers=headers
    ).json()
    assert first["cut_applied"] and len(first["items"]) == 2 and first["has_more"]
    more = client.get(
        "/api/library/search",
        params={"q": "pipe", "limit": 2, "offset": first["next_offset"]},
        headers=headers,
    ).json()
    assert not more["cut_applied"]
    seen = {i["id"] for i in first["items"]}
    assert more["items"] and not seen & {i["id"] for i in more["items"]}


def test_hide_and_change_unit_survive_reimport(library, login_as):
    client, headers = login_as("estimator")
    pipe = _item(library, "Sealing / packing the joint")
    r = client.patch(f"/api/library/items/{pipe.id}", json={"is_excluded": True}, headers=headers)
    assert r.status_code == 422  # a reason is required
    r = client.patch(
        f"/api/library/items/{pipe.id}",
        json={"is_excluded": True, "excluded_reason": "duplicate wording", "unit": "Each"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["unit"], r.json()["unit_raw"], r.json()["unit_manual"]) == ("nos", "Nos", True)
    assert r.json()["exclusion_source"] == "manual"
    assert client.patch(f"/api/library/items/{pipe.id}", json={"unit": "furlong"},
                        headers=headers).status_code == 422  # fmt: skip

    # the margin row was excluded by a rule; show it again by hand
    margin = _item(library, "Margin — Pipe sleeve")
    client.patch(f"/api/library/items/{margin.id}", json={"is_excluded": False}, headers=headers)

    import_library(library, WORKBOOK)
    library.expire_all()
    pipe, margin = library.get(LibraryItem, pipe.id), library.get(LibraryItem, margin.id)
    assert pipe.is_excluded and pipe.excluded_reason == "duplicate wording"
    assert not margin.is_excluded
    assert library.scalar(select(AuditLog).where(AuditLog.action == "library_item.update"))


def test_library_edits_need_library_edit(library, login_as):
    client, headers = login_as("sales")  # library.view only
    item = _item(library, "Toilet sunken slab")
    assert client.patch(f"/api/library/items/{item.id}", json={"unit": "sqm"},
                        headers=headers).status_code == 403  # fmt: skip
    assert client.post(f"/api/library/items/{item.id}/merge", json={"into_id": item.id},
                       headers=headers).status_code == 403  # fmt: skip


def test_merge_moves_lines_recomputes_and_unmerge_restores(library, login_as):
    client, headers = login_as("estimator")
    nos = _item(library, "Treatment around pipe outlet", "nos")
    sqm = _item(library, "Treatment around pipe outlet", "sqm")
    assert (nos.boq_count, nos.min_rate, nos.median_rate, nos.max_rate) == (
        2, Decimal("250"), Decimal("275"), Decimal("300"),
    )  # fmt: skip

    r = client.post(f"/api/library/items/{sqm.id}/merge", json={"into_id": nos.id},
                    headers=headers)  # fmt: skip
    assert r.status_code == 200, r.text
    target = r.json()
    assert [m["id"] for m in target["merged_items"]] == [sqm.id]
    assert target["stats_from_lines"]
    assert (target["boq_count"], target["min_rate"], target["median_rate"], target["max_rate"]) == (
        3, "250.0000", "300.0000", "1087.0000",
    )  # fmt: skip
    lines = client.get(f"/api/library/items/{nos.id}/lines", headers=headers).json()
    assert sorted(ln["rate"] for ln in lines) == ["1087.0000", "250.0000", "300.0000"]

    hits = client.get("/api/library/search", params={"q": "pipe outlet"}, headers=headers).json()
    ids = [h["id"] for h in hits["items"]]
    assert ids[0] == nos.id and sqm.id not in ids  # the merged duplicate left search

    merged = client.get(f"/api/library/items/{sqm.id}", headers=headers).json()
    assert merged["merged_into"]["id"] == nos.id
    assert client.post(f"/api/library/items/{nos.id}/merge", json={"into_id": sqm.id},
                       headers=headers).status_code == 409  # target is itself merged  # fmt: skip

    # re-importing keeps the merge
    import_library(library, WORKBOOK)
    again = client.get(f"/api/library/items/{nos.id}", headers=headers).json()
    assert again["boq_count"] == 3 and again["max_rate"] == "1087.0000"

    r = client.post(f"/api/library/items/{sqm.id}/unmerge", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["merged_into"] is None
    back = client.get(f"/api/library/items/{nos.id}", headers=headers).json()
    assert (back["boq_count"], back["min_rate"], back["median_rate"], back["max_rate"]) == (
        2, "250.0000", "275.0000", "300.0000",
    )  # fmt: skip
    assert not back["stats_from_lines"] and back["merged_items"] == []
    restored = client.get(f"/api/library/items/{sqm.id}", headers=headers).json()
    assert restored["max_rate"] == "1087.0000" and restored["boq_count"] == 1

    audit_rows = library.scalars(
        select(AuditLog).where(AuditLog.entity == "library_item").order_by(AuditLog.id)
    )
    actions = [a.action for a in audit_rows]
    assert actions == ["library_item.merge", "library_item.unmerge"]
