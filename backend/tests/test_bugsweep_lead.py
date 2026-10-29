# ruff: noqa: E501
"""Prompt 39, Part 3 (lead): the X-ray DEMO site's RA bill 01 gets lines and real amounts from the
DEMO seed (it showed ₹0.00), with totals = the sum of the lines, and a rerun adds nothing."""

from decimal import Decimal

from sqlalchemy import select

from app.building import demo as xray
from app.finance.models import RaBill
from app.sites.models import AreaScope, Site, SiteNode, StageTemplate


def test_the_xray_demo_bill_gets_lines_and_amounts(db):
    site = Site(code="DEMO-X-T", name="DEMO X-ray test", city="Ahmedabad", state="Gujarat", status="active", is_demo=True)
    db.add(site)
    db.flush()
    toilet = db.scalar(select(StageTemplate).where(StageTemplate.name == "Toilet / wet area (coating)"))
    assert toilet is not None
    for i, pct in enumerate((100, 100, 40)):
        n = SiteNode(site_id=site.id, kind="toilet", name=f"Toilet {i}", sort_order=i)
        db.add(n)
        db.flush()
        db.add(AreaScope(site_id=site.id, node_id=n.id, stage_template_id=toilet.id, qty=Decimal("6"), unit="sqm", progress_percent=Decimal(pct)))
    db.commit()
    out = xray.billing(db, site.id)
    assert out["lines"] == 1 and out["measurements_added"] == 2, out
    b = db.scalar(select(RaBill).where(RaBill.site_id == site.id))
    assert b.code == "RA-DEMO-X-T-01" and b.status == "draft"
    assert sum(ln.amount for ln in b.lines) == b.gross == Decimal("6240.00")  # 2 finished x 6 sqm x ₹520
    assert b.net == Decimal("5928.00")  # less 5 % retention
    again = xray.billing(db, site.id)
    assert again["measurements_added"] == 0 and again["gross"] == "6240.00"


def test_a_reserved_email_domain_gets_a_plain_message(login_as, db):
    """Found in the server's issue log: Add user with an @...invalid address showed the validator's
    own English ("special-use or reserved name")."""
    from tests.conftest import role_id

    c, h = login_as("super_admin", email="sa-mail@example.com")
    r = c.post("/api/users", json={"email": "someone@site.invalid", "full_name": "X", "role_ids": [role_id(db, "sales")]}, headers=h)
    assert r.status_code == 422
    shown = r.json()["detail"][0]["msg"]  # what the page shows ("raw" keeps the validator's text)
    assert "cannot receive email" in shown and "special-use" not in shown


def test_every_role_has_a_quick_start_of_its_main_pages(db):
    """Prompt 39, Part 6: a short quick start per role (first login, the daily card, the main tasks,
    one picture each) next to the full SOP; 10-15 pages for a role with 5 or more main pages."""
    from app.ops import sop

    for role in sop.role_docs():
        if role == sop.INDEX:
            continue
        pages = sop.quick_pages(role)
        assert 1 <= len(pages) <= sop.QUICK_MAX and set(pages) <= sop.included(role), role
        assert not set(pages) & sop.QUICK_SKIP
    data, n = sop.quick_pdf(db, "site_engineer", None)
    assert data.startswith(b"%PDF") and 10 <= n <= 15
    text = sop.quick_html(db, "site_engineer", None)
    assert "Your daily card" in text and "Task 1:" in text and "ERP" not in text
