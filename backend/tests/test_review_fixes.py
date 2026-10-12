# ruff: noqa: F811  (shared fixtures are imported)
"""Site control review fixes: one delivery time everywhere (Indian time), the test-link warning,
product aliases and gsm per layer in the consistency check, places on daily report lines, and the
director releasing a blocked vendor bill. Invented data only."""

import json
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import settings
from app.execution.models import Dpr
from app.masters.models import Product
from app.quotations.checks import alias_map, check
from app.sitecontrol import pdf
from app.sitecontrol.models import DeliveryNote, NewAreaRequest
from app.sites.models import SiteNode
from app.timefmt import label
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)
from tests.test_material import approved_po, godown, masters, site, stock, store_of  # noqa: F401
from tests.test_sitecontrol import jpg, media, photos, po_site, raw_token, send  # noqa: F401

# --- one time everywhere --------------------------------------------------------------------------


def test_a_delivery_shows_the_same_indian_time_on_the_receipt_page_the_list_and_the_pdf(
    boss, po_site, db, client
):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    dn.expected_at = datetime(2026, 10, 9, 12, 31, tzinfo=UTC)  # 18:01 in India
    db.commit()
    raw = raw_token(db, dn.id)
    page = client.get(f"/api/receipt/{raw}").json()["expected_label"]
    row = c.get("/api/sitecontrol/deliveries", headers=h).json()[0]["expected_label"]
    detail = c.get(f"/api/sitecontrol/deliveries/{dn.id}", headers=h).json()["expected_label"]
    html = pdf.html(db, dn, raw)
    assert page == row == detail == label(dn.expected_at) == "09 Oct 2026, 18:01"
    assert "09 Oct 2026, 18:01" in html and "12:31" not in html


def test_a_po_delivery_date_means_noon_in_india(boss, masters, db):
    c, h = boss
    products, vendors = masters
    s = site(c, h)
    store = store_of(c, h, s["id"])
    po = approved_po(
        c,
        h,
        vendors[0],
        store["id"],
        [{"product_id": products["T-PU"], "qty": "4", "rate": "300"}],
        expected_delivery="2026-10-12",
    )
    send(c, h, po["id"])
    dn = db.scalar(select(DeliveryNote))
    assert label(dn.expected_at) == "12 Oct 2026, 12:00"


# --- the test link warning -----------------------------------------------------------------------


def test_localhost_links_are_marked_as_test_links(boss, po_site, db, monkeypatch):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    raw = raw_token(db, dn.id)
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5174")
    assert c.get("/api/sitecontrol/link-status", headers=h).json() == {"test_link": True}
    assert "Test link, works only on the office PC" in pdf.html(db, dn, raw)
    monkeypatch.setattr(settings, "public_base_url", "https://app.invented-eespl.example")
    assert c.get("/api/sitecontrol/link-status", headers=h).json() == {"test_link": False}
    assert "Test link" not in pdf.html(db, dn, raw)


# --- the consistency check -----------------------------------------------------------------------

SPEC = [
    {
        "sections": [
            {
                "steps": [
                    {"text": "Apply **BRONCO HYBRID PU** in 2 coats."},
                    {"text": "Lay 45 gsm glass fibre mesh as reinforcement between the coats."},
                    {"text": "Spread a 120 gsm geotextile separation layer over the coating."},
                ]
            }
        ]
    }
]
OFFER = [
    "Supply and apply **BRONCO CEMSHIELD HYBRID PU** in 3 coats with 40 gsm reinforcement mesh."
]


def test_aliases_make_one_product_and_gsm_is_compared_within_its_layer(db):
    db.add(
        Product(
            code="INV-HPU",
            name="BRONCO HYBRID PU",
            unit="kg",
            aliases=["BRONCO CEMSHIELD HYBRID PU"],
        )
    )
    db.commit()
    warn = check(SPEC, OFFER, alias_map(db))
    assert not any("HYBRID PU" in w for w in warn)  # one product under two names
    assert "Different gsm (mesh): specification 45 gsm, budgetary offer 40 gsm" in warn
    assert not any("120" in w for w in warn)  # the separation layer is not the mesh
    assert "Different coat count: specification 2 coats, budgetary offer 3 coats" in warn
    # without the alias the two names are still flagged
    assert any("CEMSHIELD" in w for w in check(SPEC, OFFER, {}))


def test_product_aliases_are_editable(boss):
    c, h = boss
    r = c.post(
        "/api/products",
        json={"code": "INV-A", "name": "Invented Coat", "unit": "kg", "aliases": [" Inv Coat X "]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["aliases"] == ["Inv Coat X"]
    r = c.patch(f"/api/products/{r.json()['id']}", json={"aliases": ["Inv Coat Y"]}, headers=h)
    assert r.status_code == 200, r.text and r.json()["aliases"] == ["Inv Coat Y"]


# --- daily report places -------------------------------------------------------------------------


def test_daily_report_lines_carry_a_place(boss, world, db):
    c, h = boss
    site_id = world["site"]
    terrace = db.scalar(select(SiteNode).where(SiteNode.site_id == site_id))
    day = date.today().isoformat()
    url = f"/api/execution/sites/{site_id}/dprs/{day}"
    r = c.put(
        url,
        json={"work_done": "Invented coating", "lines": [{"description": "Primer", "qty": "20"}]},
        headers=h,
    )
    assert r.status_code == 422 and "area" in r.json()["detail"]  # a site with a list needs a place
    r = c.put(
        url,
        json={
            "work_done": "Invented coating",
            "lines": [
                {"description": "Primer coat", "qty": "20", "unit": "sqm", "node_id": terrace.id}
            ],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["node_id"] == terrace.id and line["place"] == "Terrace"
    # a new area asked for from site, then rejected: the line moves to the place planning picks
    area = c.post(
        "/api/sitecontrol/new-areas",
        data={"site_id": str(site_id), "name": "Invented shaft"},
        files={"photo": ("p.jpg", jpg(), "image/jpeg")},
        headers=h,
    ).json()
    r = c.put(
        url,
        json={
            "work_done": "Invented coating",
            "lines": [{"description": "Shaft primer", "new_area_id": area["id"]}],
        },
        headers=h,
    )
    assert r.status_code == 200 and "new area" in r.json()["lines"][0]["place"]
    c.post(
        f"/api/sitecontrol/new-areas/{area['id']}/reject",
        json={"move_to_node_id": terrace.id},
        headers=h,
    )
    db.expire_all()
    d = db.scalar(select(Dpr))
    assert d.lines[0].node_id == terrace.id and d.lines[0].new_area_id is None
    assert db.get(NewAreaRequest, area["id"]).status == "rejected"
    # an old report without lines keeps a blank place
    assert c.get(url, headers=h).json()["lines"][0]["place"] == "Terrace"


# --- the director releases a blocked bill --------------------------------------------------------


def test_the_director_releases_a_blocked_bill(boss, po_site, db, client, login_as):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    crys, pu = dn.lines
    client.post(
        f"/api/receipt/{raw_token(db, dn.id)}",
        data={
            "name": "Invented Labour Leader",
            "lines": json.dumps(
                [{"line_id": crys.id, "received": 8}, {"line_id": pu.id, "received": 4}]
            ),
        },
        files=photos(),
    )
    db.expire_all()
    from app.material.models import Grn  # noqa: PLC0415

    g = db.get(Grn, db.get(DeliveryNote, dn.id).grn_id)
    line = next(ln for ln in g.lines if ln.product_id == po_site["products"]["T-CRYS"])
    bill = c.post(
        "/api/finance/vendor-bills",
        json={
            "vendor_id": po_site["vendors"][0],
            "bill_no": "INV-D1",
            "bill_date": date.today().isoformat(),
            "grn_ids": [g.id],
            "grn_lines": [{"grn_line_id": line.id, "qty": "10"}],
        },
        headers=h,
    ).json()
    assert bill["blocked"]
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert (
        acc.post(
            f"/api/sitecontrol/vendor-bills/{bill['id']}/release",
            json={"reason": "Invented reason"},
            headers=ah,
        ).status_code
        == 403
    )  # accounts waits for the director
    d, dh = login_as("director", email="director@example.com")
    r = d.post(
        f"/api/sitecontrol/vendor-bills/{bill['id']}/release",
        json={"reason": "Invented: the two bags came the next day"},
        headers=dh,
    )
    assert r.status_code == 200 and r.json()["released_at"]
