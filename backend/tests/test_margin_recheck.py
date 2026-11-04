"""margin-recheck lists the lines whose rate changes with the margin on the selling price, and with
--apply makes tender lines suggested (never a submitted revision)."""

from decimal import Decimal as D

from app.cli import margin_recheck as mrc
from app.tenders.models import BoqLine, Tender


def test_it_lists_then_suggests_and_leaves_other_lines(db):
    t = Tender(code="T-MR-1", name="Invented tender", status="draft")
    won = Tender(code="T-MR-2", name="Invented won tender", status="won")
    db.add_all([t, won])
    db.flush()
    old = BoqLine(
        tender_id=t.id,
        description="Invented membrane",
        unit="sqm",
        qty=D(10),
        source="system",
        cost_rate=D(320),
        margin_percent=D(20),
        rate=D(384),
        status="priced",
    )
    ok = BoqLine(
        tender_id=t.id,
        description="Already right",
        unit="sqm",
        qty=D(1),
        source="system",
        cost_rate=D(100),
        margin_percent=D(25),
        rate=D("133.33"),
        status="priced",
    )
    manual = BoqLine(
        tender_id=t.id,
        description="Typed rate",
        unit="sqm",
        qty=D(1),
        source="manual",
        rate=D(50),
        status="priced",
    )
    closed = BoqLine(
        tender_id=won.id,
        description="On a won tender",
        unit="sqm",
        qty=D(1),
        source="system",
        cost_rate=D(320),
        margin_percent=D(20),
        rate=D(384),
        status="priced",
    )
    db.add_all([old, ok, manual, closed])
    db.commit()
    changes = mrc.find(db)
    assert [(c.line_id, c.old, c.new, c.diff) for c in changes] == [
        (old.id, D(384), D("400.00"), D("16.00"))
    ]
    assert "lines whose rate would change: 1" in mrc.report(changes)
    db.refresh(old)
    assert old.rate == D(384) and old.status == "priced"  # nothing changes without --apply
    assert mrc.apply(db, changes)["tender_lines_suggested"] == 1
    db.commit()
    db.refresh(old)
    assert (old.rate, old.status, old.amount) == (D("400.00"), "suggested", D("4000.00"))
    db.refresh(closed)
    assert closed.rate == D(384)
