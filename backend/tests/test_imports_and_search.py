from pathlib import Path

from sqlalchemy import func, select

from app.masters.importers import import_library, import_tc
from app.masters.models import LibraryItem, LibraryLine, TcClause, TcTemplate

FIXTURES = Path(__file__).parent / "fixtures"
WORKBOOK = FIXTURES / "rate_library_sample.xlsx"
CLAUSES = FIXTURES / "tc_clauses_sample.json"


def _counts(db):
    return (
        db.scalar(select(func.count()).select_from(LibraryItem)),
        db.scalar(select(func.count()).select_from(LibraryLine)),
        db.scalar(
            select(func.count())
            .select_from(LibraryLine)
            .where(LibraryLine.library_item_id.is_(None))
        ),
    )


def test_library_import_is_idempotent(db):
    first = import_library(db, WORKBOOK)
    assert (first.items_in_file, first.lines_in_file) == (10, 12)
    assert (first.items_inserted, first.lines_inserted) == (10, 12)
    assert first.lines_linked == 11
    assert first.lines_linked_via_parent == 2
    assert first.lines_unlinked == 1
    assert sorted(s.reason for s in first.skipped) == ["blank description", "duplicate of row 2"]
    counts = _counts(db)
    ids = sorted(db.scalars(select(LibraryItem.id)))
    line_links = dict(db.execute(select(LibraryLine.source_key, LibraryLine.library_item_id)).all())

    second = import_library(db, WORKBOOK)
    assert (second.items_inserted, second.items_updated, second.items_deleted) == (0, 10, 0)
    assert (second.lines_inserted, second.lines_updated, second.lines_deleted) == (0, 12, 0)
    assert _counts(db) == counts == (10, 12, 1)
    assert sorted(db.scalars(select(LibraryItem.id))) == ids
    assert dict(db.execute(select(LibraryLine.source_key, LibraryLine.library_item_id)).all()) == (
        line_links
    )


def test_library_import_normalises_and_links(db):
    import_library(db, WORKBOOK)
    items = {i.description[:20]: i for i in db.scalars(select(LibraryItem))}
    toilet = items["Toilet sunken slab w"]
    assert (toilet.unit, toilet.unit_raw) == ("sqm", "Sq.Mt")
    assert items["Mobilisation and dem"].unit is None
    crystal = items["Integral crystalline"]
    assert crystal.needs_check and crystal.check_note == "rates vary more than 2x"
    assert str(crystal.latest_rate) == "210.5000"

    lines = {(ln.file, ln.row): ln for ln in db.scalars(select(LibraryLine))}
    assert lines[("CLIENT C/c.xlsx", 5)].library_item_id == items["Providing and applyin"[:20]].id
    pipe = lines[("CLIENT B/b.xlsx", 22)]
    assert pipe.library_item_id is not None and pipe.qty is None and pipe.qty_note == "QRO"
    nq = lines[("CLIENT A/a.xlsx", 11)]
    assert nq.qty is None and nq.qty_note == "NQ"
    assert lines[("CLIENT C/c.xlsx", 9)].library_item_id == toilet.id  # Sqmt line -> Sq.Mt item
    assert lines[("CLIENT D/d.xlsx", 3)].library_item_id is None
    assert lines[("CLIENT C/c.xlsx", 5)].unit == "sqm"


def test_search_ranks_the_expected_item_first(login_as, db):
    import_library(db, WORKBOOK)
    client, headers = login_as("sales")  # library.view is enough

    def top(q, **params):
        r = client.get("/api/library/search", params={"q": q, **params}, headers=headers)
        assert r.status_code == 200, r.text
        return [i["description"] for i in r.json()["items"]]

    assert top("pvc pipe sealing")[0].startswith("Sealing / packing the joint around the PVC pipe")
    assert top("app membrane")[0].startswith("Providing and applying APP modified bitumen")
    assert top("crystaline admixture")[0].startswith("Integral crystalline admixture")  # typo
    assert top("bathroom waterproofing")[0].startswith("Toilet sunken slab")  # synonym
    assert top("waterproofing", unit="Sq.m") == [top("bathroom waterproofing")[0]]
    assert top("membrane", unit="kg") == []

    hit = client.get("/api/library/search", params={"q": "app membrane"}, headers=headers).json()
    first = hit["items"][0]
    # The APP item has another bidder's ₹999 line, so its stats are recomputed without it
    # from its two EESPL lines (the sheet said 6 BOQs, 380-480).
    assert first["boq_count"] == 2
    assert (first["latest_rate"], first["min_rate"], first["median_rate"], first["max_rate"]) == (
        "450.0000",
        "380.0000",
        "415.0000",
        "450.0000",
    )
    assert first["suggested_rate"] == "450.0000"
    assert hit["took_ms"] >= 0

    lines = client.get(f"/api/library/items/{first['id']}/lines", headers=headers).json()
    assert {(ln["channel"], ln["rate"], ln["is_competitor"]) for ln in lines} == {
        ("CLIENT A", "450.0000", False),
        ("CLIENT C", "380.0000", False),
        ("CLIENT E", "999.0000", True),
    }


def test_library_needs_library_view(login_as):
    client, headers = login_as("client")
    assert client.get("/api/library/search", params={"q": "x"}, headers=headers).status_code == 403


def test_tc_import_is_idempotent_and_builds_default_template(db):
    first = import_tc(db, CLAUSES)
    assert (first.clauses_in_file, first.clauses_inserted) == (3, 3)
    assert sorted(s.reason for s in first.skipped) == ["duplicate clause text", "missing text"]
    assert first.template_created and first.template_clauses == 2

    template = db.scalar(select(TcTemplate))
    assert template.name == "EESPL Standard" and template.is_default
    assert [tc.clause.category for tc in template.clauses] == ["validity", "taxes"]

    second = import_tc(db, CLAUSES)
    assert (second.clauses_inserted, second.clauses_updated) == (0, 3)
    assert not second.template_created
    assert db.scalar(select(func.count()).select_from(TcClause)) == 3
    assert db.scalar(select(func.count()).select_from(TcTemplate)) == 1
