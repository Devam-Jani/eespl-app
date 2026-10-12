# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Team roles review and the director meeting (12 Oct): the site receiver, the client's
certification recorded by staff, the Kylas quotation stage, systems offered per area type, and
daily report places moving progress and ready to bill. Invented data only."""

import json
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.crm import kylas_client, kylas_poll
from app.crm.models import Lead
from app.db import SessionLocal
from app.main import app
from app.masters.models import System
from app.models import User
from app.quotations.models import Quotation
from app.sitecontrol.models import DeliveryNote, ReadyToBill
from app.sites.models import AreaScope, SiteMember
from app.survey.models import AreaType
from tests.conftest import login
from tests.test_crm import FakeKylas, configure, kylas  # noqa: F401  (fixtures)
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)
from tests.test_material import approved_po, godown, masters, site, stock, store_of  # noqa: F401
from tests.test_sitecontrol import media, send  # noqa: F401


def person(make_user, db, email, *roles, site_id=None, role_on_site="viewer"):
    u = make_user(email, *roles, name=f"Invented {email.split('@')[0]}")
    if site_id:
        db.add(SiteMember(site_id=site_id, user_id=u.id, role_on_site=role_on_site))
        db.commit()
    c = TestClient(app)
    return c, login(c, email), u


# --- the site receiver ---------------------------------------------------------------------------


def test_a_site_receiver_confirms_deliveries_on_its_own_sites_and_sees_nothing_else(
    boss, masters, make_user, db
):
    c, h = boss
    products, vendors = masters
    sites = [site(c, h), site(c, h, name="Invented Second Site")]
    for s in sites:
        po = approved_po(
            c,
            h,
            vendors[0],
            store_of(c, h, s["id"])["id"],
            [{"product_id": products["T-PU"], "qty": "4", "rate": "300"}],
        )
        send(c, h, po["id"])
    rc, rh, _ = person(
        make_user,
        db,
        "receiver@example.com",
        "site_receiver",
        site_id=sites[0]["id"],
        role_on_site="receiver",
    )
    rows = rc.get("/api/sitecontrol/deliveries", headers=rh).json()
    assert [r["site_id"] for r in rows] == [sites[0]["id"]]
    mine = db.scalar(select(DeliveryNote).where(DeliveryNote.site_id == sites[0]["id"]))
    other = db.scalar(select(DeliveryNote).where(DeliveryNote.site_id == sites[1]["id"]))
    assert rc.get(f"/api/sitecontrol/deliveries/{other.id}", headers=rh).status_code == 404
    for path in (
        "/api/sites",
        "/api/material/pos",
        "/api/finance/invoices",
        "/api/leads",
        "/api/team/board",
    ):
        assert rc.get(path, headers=rh).status_code == 403, path
    photos = {
        "photo_goods": ("g.jpg", b"\xff\xd8\xff" + b"0" * 64, "image/jpeg"),
        "photo_challan": ("c.jpg", b"\xff\xd8\xff" + b"0" * 64, "image/jpeg"),
    }
    lines = json.dumps([{"line_id": ln.id, "received": str(ln.qty)} for ln in mine.lines])
    r = rc.post(
        f"/api/sitecontrol/deliveries/{mine.id}/confirm",
        data={"lines": lines},
        files=photos,
        headers=rh,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    sections = rc.get("/api/team/my-work", headers=rh).json()["sections"]
    assert [s["role"] for s in sections] == ["site_receiver"]


# --- the client's certification recorded by staff -------------------------------------------------


def _sent_ra(c, h, world):
    k = contract(c, h, world)
    ra = c.post(f"/api/finance/contracts/{k['id']}/ra-bills", json={}, headers=h).json()
    assert c.post(f"/api/finance/ra-bills/{ra['id']}/submit", headers=h).status_code == 200
    return ra


def test_billing_or_the_salesperson_records_the_clients_certification(boss, world, make_user, db):
    c, h = boss
    ra = _sent_ra(c, h, world)
    pu = next(x for x in ra["lines"] if x["description"] == "PU coating")
    other, oh, _ = person(make_user, db, "someone@example.com", "estimator")
    data = {
        "approved_by": "Invented PMC, Mr. Desai",
        "on_date": "2026-10-11",
        "amount": "30000",
        "lines": json.dumps([{"contract_line_id": pu["contract_line_id"], "certified_qty": "60"}]),
    }
    doc = {"file": ("signed.pdf", b"%PDF-1.4 invented signed copy", "application/pdf")}
    assert (
        other.post(
            f"/api/team/ra-bills/{ra['id']}/client-certification", data=data, files=doc, headers=oh
        ).status_code
        == 403
    )
    s, sh, _ = person(
        make_user, db, "sales@example.com", "sales", site_id=world["site"], role_on_site="sales"
    )
    r = s.post(
        f"/api/team/ra-bills/{ra['id']}/client-certification", data=data, files=doc, headers=sh
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["status"] == "certified"
        and r.json()["via"] == "staff"
        and r.json()["approved_by"].startswith("Invented PMC")
    )
    got = c.get(f"/api/team/ra-bills/{ra['id']}/client-certification/document", headers=h)
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    row = next(x for x in c.get("/api/team/bill-tracking", headers=h).json() if x["id"] == ra["id"])
    assert (
        row["certified_on"] == "2026-10-11"
        and row["has_document"]
        and row["certified_via"] == "staff"
    )


# --- Kylas: the quotation stage -------------------------------------------------------------------


def test_the_kylas_quotation_stage_gives_a_make_quotation_item_and_no_quotation(
    boss, kylas, make_user, db
):
    c, h = boss
    configure(c, h, quotation_stage_id=4401)
    s, sh, su = person(make_user, db, "sales@example.com", "sales")
    p, ph, _ = person(make_user, db, "plan@example.com", "planning")
    for code, kid, owner in (("L-T-71", 71, su.id), ("L-T-72", 72, None)):
        db.add(
            Lead(
                code=code,
                contact_name=f"Invented {code}",
                phone="+919000000071",
                kylas_lead_id=kid,
                kylas_sync_status="synced",
                owner_id=owner,
            )
        )
    db.commit()
    kylas.leads = {
        71: {"id": 71, "forecastingType": "OPEN", "pipelineStage": {"id": 4401}},
        72: {"id": 72, "forecastingType": "OPEN", "pipelineStage": 4401},
    }
    with SessionLocal() as sdb:
        report = kylas_poll.run(sdb, kylas_client.client())
    assert report.quotation_requested == 2
    mine = [
        i
        for sec in s.get("/api/team/my-work", headers=sh).json()["sections"]
        for i in sec["items"]
        if i["source"] == "make_quotation"
    ]
    plans = [
        i
        for sec in p.get("/api/team/my-work", headers=ph).json()["sections"]
        for i in sec["items"]
        if i["source"] == "make_quotation"
    ]
    assert [i["title"] for i in mine] == ["L-T-71 Invented L-T-71"] and [
        i["title"] for i in plans
    ] == ["L-T-72 Invented L-T-72"]
    assert db.scalar(select(func.count()).select_from(Quotation)) == 0  # never made by the poll


# --- systems per area type ------------------------------------------------------------------------


def test_the_area_type_system_is_a_suggestion_among_suitable_ones_and_the_client_choice_is_kept(
    boss, world, db
):
    c, h = boss
    systems = [
        System(code=f"INV-S{i}", name=name, unit="sqm", labour_rate=40)
        for i, name in enumerate(
            (
                "Invented Samgard",
                "Invented Samgard Plus",
                "Invented Ultra Flex",
                "Invented Hybrid PU",
            )
        )
    ]
    db.add_all(systems)
    db.flush()
    at = AreaType(
        name="Invented sunken",
        default_system_id=systems[1].id,
        suitable_system_ids=[systems[0].id, systems[2].id, systems[3].id],
        created_by=db.scalar(select(User.id).where(User.email == "boss@example.com")),
    )
    db.add(at)
    db.commit()
    r = c.get(
        f"/api/team/system-choices?area_type_id={at.id}&client_id={world['client']}", headers=h
    ).json()
    assert r["suggested_id"] == systems[1].id
    assert [o["name"] for o in r["options"]] == [
        "Invented Samgard Plus",
        "Invented Samgard",
        "Invented Ultra Flex",
        "Invented Hybrid PU",
    ]
    c.post(
        "/api/team/system-choices",
        json={"client_id": world["client"], "area_type_id": at.id, "system_id": systems[2].id},
        headers=h,
    )
    r = c.get(
        f"/api/team/system-choices?area_type_id={at.id}&client_id={world['client']}", headers=h
    ).json()
    assert (
        r["suggested_id"] == systems[2].id
        and next(o for o in r["options"] if o["last_choice"])["name"] == "Invented Ultra Flex"
    )


# --- daily report places move progress and ready to bill ------------------------------------------


def test_an_approved_daily_report_line_moves_progress_and_makes_ready_to_bill(boss, world, db):
    c, h = boss
    contract(c, h, world)
    scope = db.get(AreaScope, world["scopes"][0])  # 60 sqm of PU coating on the terrace
    url = f"/api/execution/sites/{world['site']}/dprs/{date.today().isoformat()}"
    body = {
        "work_done": "Invented PU coating",
        "lines": [
            {
                "description": "PU coating",
                "qty": "60",
                "unit": "sqm",
                "labour_count": 6,
                "node_id": scope.node_id,
                "area_scope_id": scope.id,
            }
        ],
        "submit": True,
    }
    d = c.put(url, json=body, headers=h).json()
    assert db.scalar(select(ReadyToBill).where(ReadyToBill.area_scope_id == scope.id)) is None
    r = c.post(f"/api/execution/dprs/{d['id']}/acknowledge", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["applied"] and r.json()["lines"][0]["area_scope_id"] == scope.id
    db.expire_all()
    scope = db.get(AreaScope, scope.id)
    assert Decimal(scope.dpr_done_qty) == 60 and Decimal(scope.progress_percent) == 100
    item = db.scalar(select(ReadyToBill).where(ReadyToBill.area_scope_id == scope.id))
    assert item is not None and Decimal(item.qty) == 60
