# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Site control: delivery receipts at site, the three-way match, rate contracts, ready to bill,
new areas, the labour check and consumption variance. Invented data only."""

import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import inspect, select

from app.analytics import alerts
from app.analytics.models import Alert
from app.config import settings
from app.execution.models import Attendance, Labour
from app.finance.models import SubconBill
from app.masters.models import Product, System, SystemComponent, Vendor
from app.material.models import Grn, Transfer
from app.models import User
from app.portal.models import Notification
from app.sitecontrol import ratelimit
from app.sitecontrol.deliveries import hash_token
from app.sitecontrol.models import (
    DebitNote,
    DeliveryNote,
    Discrepancy,
    NewAreaRequest,
    ProductivityNorm,
    RateContract,
    ReadyToBill,
)
from app.sites import work
from app.sites.models import AreaScope, Site, SiteNode, Task
from app.tenders.models import BoqLine
from tests.test_finance import contract, world  # noqa: F401  (fixtures)
from tests.test_material import approved_po, godown, masters, site, stock, store_of  # noqa: F401


def D(x) -> Decimal:
    return Decimal(str(x))


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    ratelimit.reset()
    return tmp_path


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


def jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 110, 100)).save(buf, "JPEG")
    return buf.getvalue()


def photos():
    return {
        "photo_goods": ("goods.jpg", jpg(), "image/jpeg"),
        "photo_challan": ("challan.jpg", jpg(), "image/jpeg"),
    }


def raw_token(db, dn_id: int) -> str:
    """The receipt link from the site's in-app outbox (the delivery keeps only the hash)."""
    dn = db.get(DeliveryNote, dn_id)
    for n in db.scalars(
        select(Notification).where(Notification.kind == "delivery").order_by(Notification.id.desc())
    ):
        raw = n.link.rsplit("/", 1)[-1]
        if hash_token(raw) == dn.token_hash:
            return raw
    raise AssertionError("no link in the outbox")


def keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(keys(v) for v in obj)) if obj else set()
    return set()


@pytest.fixture
def po_site(boss, masters, db):
    """A site (with its store and a named receiver) and an approved PO going straight to it:
    10 kg of the crystalline powder at ₹100 and 4 ltr of PU at ₹300."""
    client, h = boss
    products, vendors = masters
    s = site(client, h)
    store = store_of(client, h, s["id"])
    st = db.get(Site, s["id"])
    st.receiver_name, st.receiver_phone = "Invented Labour Leader", "+91 98250 00001"
    db.commit()
    po = approved_po(
        client,
        h,
        vendors[0],
        store["id"],
        [
            {"product_id": products["T-CRYS"], "qty": "10", "rate": "100"},
            {"product_id": products["T-PU"], "qty": "4", "rate": "300"},
        ],
    )
    return {"site": s, "store": store, "po": po, "products": products, "vendors": vendors}


def send(client, h, po_id):
    r = client.post(f"/api/material/pos/{po_id}/send", headers=h)
    assert r.status_code == 200, r.text


# --- delivery receipt ----------------------------------------------------------------------------


def test_receipt_link_shows_only_its_delivery_and_never_rates(boss, po_site, db, client):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    assert dn.code.startswith("DN-") and dn.kind == "po" and len(dn.lines) == 2
    raw = raw_token(db, dn.id)
    # only the hash is kept: no column of the delivery holds the raw token
    row = {a.key: getattr(dn, a.key) for a in inspect(dn).mapper.column_attrs}
    assert dn.token_hash == hash_token(raw) and raw not in json.dumps(row, default=str)
    assert len(raw) >= 32  # 192 bits, url-safe
    view = client.get(f"/api/receipt/{raw}")  # no login
    assert view.status_code == 200
    body = view.json()
    assert {"rate", "amount", "value", "total", "landed_rate", "price"}.isdisjoint(keys(body))
    assert [i["product"] for i in body["items"]] == ["Test crystalline powder", "Test PU coating"]
    # counts are never pre-filled with what was dispatched
    assert all("received" not in i and "received_qty" not in i for i in body["items"])
    assert client.get("/api/receipt/not-a-real-token-xxxxxxxxxxxxxxxxxx").status_code == 404
    # a link never opens another delivery
    other = approved_po(
        c,
        h,
        po_site["vendors"][0],
        po_site["store"]["id"],
        [{"product_id": po_site["products"]["T-MESH"], "qty": "5", "rate": "20"}],
    )
    send(c, h, other["id"])
    assert [i["product"] for i in client.get(f"/api/receipt/{raw}").json()["items"]] == [
        "Test crystalline powder",
        "Test PU coating",
    ]


def test_photos_required_shortage_debit_note_grn_and_second_submit(
    boss, po_site, db, client, login_as
):
    c, h = boss
    store_user, _sh = login_as("store_purchase", email="store@example.com")
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    raw = raw_token(db, dn.id)
    crys, pu = dn.lines
    counts = json.dumps(
        [
            {"line_id": crys.id, "received": 8, "damaged": 1},
            {"line_id": pu.id, "received": 4, "damaged": 0},
        ]
    )
    r = client.post(
        f"/api/receipt/{raw}",
        data={"name": "Unknown Helper", "phone": "9000000000", "lines": counts},
    )
    assert r.status_code == 422 and "photos" in r.json()["detail"]
    r = client.post(
        f"/api/receipt/{raw}",
        data={"name": "Unknown Helper", "lines": json.dumps([{"line_id": crys.id, "received": 8}])},
        files=photos(),
    )
    assert r.status_code == 422  # every item must be counted
    r = client.post(
        f"/api/receipt/{raw}",
        data={
            "name": "Unknown Helper",
            "phone": "9000000000",
            "lines": counts,
            "lat": "23.0225",
            "lng": "72.5714",
        },
        files=photos(),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    dn = db.get(DeliveryNote, dn.id)
    assert (
        dn.status == "short"
        and dn.unlisted_receiver
        and dn.photo_goods
        and dn.photo_challan
        and dn.lat is not None
    )
    # the GRN posts what was counted: 8 came, 1 damaged -> 7 kg in stock; the PU in full
    g = db.get(Grn, dn.grn_id)
    assert g.status == "approved" and [
        (ln.received_qty, ln.accepted_qty, ln.rejected_qty) for ln in g.lines
    ] == [(D(8), D(7), D(1)), (D(4), D(4), D(0))]
    st = stock(c, h, po_site["store"]["id"])
    assert st[po_site["products"]["T-CRYS"]][0] == D(7) and st[po_site["products"]["T-PU"]][0] == D(
        4
    )
    kinds = {(d.kind, d.qty) for d in db.scalars(select(Discrepancy))}
    assert kinds == {("short", D(2)), ("damaged", D(1))}
    note = db.scalar(select(DebitNote))
    assert (
        note.status == "draft" and note.amount == D(300) and note.vendor_id == po_site["vendors"][0]
    )  # 3 kg x ₹100
    store_id = db.scalar(select(User.id).where(User.email == "store@example.com"))
    assert db.scalar(
        select(Notification).where(
            Notification.kind == "delivery_discrepancy", Notification.user_id == store_id
        )
    )
    again = client.post(
        f"/api/receipt/{raw}", data={"name": "Someone", "lines": counts}, files=photos()
    )
    assert again.status_code == 409
    view = client.get(f"/api/receipt/{raw}").json()
    assert view["confirmed"] and view["confirmed_by"] == "Unknown Helper"


def test_named_receiver_is_listed_and_the_transfer_completes_with_the_count(
    boss, masters, db, client
):
    c, h = boss
    products, _v = masters
    s = site(c, h)
    st = db.get(Site, s["id"])
    st.receiver_name = "Invented Applicator"
    db.commit()
    gd = godown(c, h)
    c.post(
        f"/api/material/stores/{gd['id']}/adjust",
        json={
            "product_id": products["T-PU"],
            "qty": "50",
            "rate": "250",
            "kind": "opening",
            "note": "Opening",
        },
        headers=h,
    )
    store = store_of(c, h, s["id"])
    r = c.post(
        "/api/material/transfers",
        json={
            "from_store_id": gd["id"],
            "to_store_id": store["id"],
            "vehicle_no": "GJ01AB1234",
            "lines": [{"product_id": products["T-PU"], "qty": "20"}],
            "dispatch": True,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    dn = db.scalar(select(DeliveryNote))
    assert dn.kind == "transfer" and dn.vehicle_no == "GJ01AB1234"
    raw = raw_token(db, dn.id)
    line = dn.lines[0]
    r = client.post(
        f"/api/receipt/{raw}",
        data={
            "name": "invented applicator",
            "lines": json.dumps([{"line_id": line.id, "received": 20}]),
        },
        files=photos(),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    dn = db.get(DeliveryNote, dn.id)
    assert dn.status == "confirmed" and not dn.unlisted_receiver
    t = db.get(Transfer, dn.transfer_id)
    assert t.status == "received" and t.lines[0].qty_received == D(20)
    assert stock(c, h, store["id"])[products["T-PU"]][0] == D(20)


def test_expired_link_rate_limit_and_drop_off_photo(boss, po_site, db, client):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    raw = raw_token(db, dn.id)
    r = c.post(
        f"/api/sitecontrol/deliveries/{dn.id}/drop-photo",
        files={"photo": ("drop.jpg", jpg(), "image/jpeg")},
        headers=h,
    )
    assert (
        r.status_code == 200 and "drop" in r.json()["photos"] and r.json()["status"] == "dispatched"
    )
    dn.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/receipt/{raw}").status_code == 410
    ratelimit.reset()
    codes = [client.get("/api/receipt/xxxxxxxxxxxxxxxxxxxxxxxx").status_code for _ in range(61)]
    assert codes[0] == 404 and codes[-1] == 429


def test_escalation_after_24_and_48_hours(boss, po_site, db, login_as):
    c, h = boss
    office, _oh = login_as("office_admin", email="office@example.com")
    sup = db.scalar(select(User).where(User.email == "boss@example.com"))
    st = db.get(Site, po_site["site"]["id"])
    st.site_incharge_id = sup.id
    db.commit()
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    frozen = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    dn.expected_at = frozen - timedelta(hours=25)
    db.commit()
    alerts.run(db, frozen)
    db.commit()
    rules = {a.rule for a in db.scalars(select(Alert))}
    assert "dn_unconfirmed" in rules and "dn_escalated" not in rules
    alerts.run(db, frozen + timedelta(hours=24))  # 49 h after it was expected
    db.commit()
    esc = db.scalar(select(Alert).where(Alert.rule == "dn_escalated"))
    assert esc is not None and dn.code in esc.title
    office_id = db.scalar(select(User.id).where(User.email == "office@example.com"))
    assert db.scalar(
        select(Notification).where(
            Notification.kind == "alert:dn_escalated", Notification.user_id == office_id
        )
    )


# --- the three-way match -------------------------------------------------------------------------


def test_over_quantity_and_over_rate_block_until_released(boss, po_site, db, client, login_as):
    c, h = boss
    send(c, h, po_site["po"]["id"])
    dn = db.scalar(select(DeliveryNote))
    raw = raw_token(db, dn.id)
    crys, pu = dn.lines
    client.post(
        f"/api/receipt/{raw}",
        data={
            "name": "Invented Labour Leader",
            "lines": json.dumps(
                [{"line_id": crys.id, "received": 8}, {"line_id": pu.id, "received": 4}]
            ),
        },
        files=photos(),
    )
    db.expire_all()
    g = db.get(Grn, db.get(DeliveryNote, dn.id).grn_id)
    by_product = {ln.product_id: ln for ln in g.lines}
    r = c.post(
        "/api/finance/vendor-bills",
        json={
            "vendor_id": po_site["vendors"][0],
            "bill_no": "INV-1",
            "bill_date": date.today().isoformat(),
            "grn_ids": [g.id],
            "grn_lines": [
                {
                    "grn_line_id": by_product[po_site["products"]["T-CRYS"]].id,
                    "qty": "10",
                },  # 8 counted
                {
                    "grn_line_id": by_product[po_site["products"]["T-PU"]].id,
                    "rate": "330",
                },  # PO ₹300
            ],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["blocked"] and {x["kind"] for x in bill["blocked_reasons"]} == {"qty", "rate"}
    assert (
        "billed 10" in bill["blocked_reasons"][0]["message"]
        and "confirmed received 8" in bill["blocked_reasons"][0]["message"]
    )
    assert (
        c.post(
            f"/api/finance/vendor-bills/{bill['id']}/approve",
            json={"accept_differences": True},
            headers=h,
        ).status_code
        == 409
    )
    acc, ah = login_as("accounts", email="accounts@example.com")
    assert (
        acc.post(
            f"/api/sitecontrol/vendor-bills/{bill['id']}/release",
            json={"reason": "x" * 5},
            headers=ah,
        ).status_code
        == 403
    )
    r = c.post(
        f"/api/sitecontrol/vendor-bills/{bill['id']}/release",
        json={"reason": "Invented: two bags came the next day, counted"},
        headers=h,
    )
    assert r.status_code == 200
    r = c.post(
        f"/api/finance/vendor-bills/{bill['id']}/approve",
        json={"accept_differences": True},
        headers=h,
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "approved"
        and r.json()["release_reason"].startswith("Invented")
    )
    from app.models import AuditLog  # noqa: PLC0415

    assert db.scalar(select(AuditLog).where(AuditLog.action == "vendor_bill.release"))
    rep = c.get("/api/sitecontrol/reports/match", headers=h).json()
    assert rep["blocked"][0]["bill"] == bill["number"] and rep["blocked"][0]["released"]


# --- rate contracts ------------------------------------------------------------------------------


def test_rate_contract_fills_po_rate_needs_a_reason_above_one_per_date_and_expiry_alert(
    boss, masters, db
):
    c, h = boss
    products, vendors = masters
    s = site(c, h)
    store = store_of(c, h, s["id"])
    body = {
        "vendor_id": vendors[0],
        "product_id": products["T-PU"],
        "rate": "300",
        "valid_from": date.today().isoformat(),
        "valid_till": (date.today() + timedelta(days=10)).isoformat(),
        "agreed_by": "Invented Purchase Head",
    }
    r = c.post("/api/sitecontrol/rate-contracts", json=body, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert (
        c.post(
            "/api/sitecontrol/rate-contracts", json={**body, "rate": "310"}, headers=h
        ).status_code
        == 409
    )  # one per date
    r = c.post(
        "/api/material/pos",
        json={
            "vendor_id": vendors[0],
            "store_id": store["id"],
            "lines": [{"product_id": products["T-PU"], "qty": "5"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    line = r.json()["lines"][0]
    assert (
        D(line["rate"]) == D(300)
        and D(line["contract_rate"]) == D(300)
        and line["above_contract_percent"] is None
    )
    r = c.post(
        "/api/material/pos",
        json={
            "vendor_id": vendors[0],
            "store_id": store["id"],
            "lines": [{"product_id": products["T-PU"], "qty": "5", "rate": "330"}],
        },
        headers=h,
    )
    assert r.status_code == 422 and "above agreed rate by 10.0%" in r.json()["detail"]
    r = c.post(
        "/api/material/pos",
        json={
            "vendor_id": vendors[0],
            "store_id": store["id"],
            "lines": [
                {
                    "product_id": products["T-PU"],
                    "qty": "5",
                    "rate": "330",
                    "rate_reason": "Invented: urgent small lot",
                }
            ],
        },
        headers=h,
    )
    assert r.status_code == 201
    line = r.json()["lines"][0]
    assert D(line["above_contract_percent"]) == D("10.0") and line["rate_reason"].startswith(
        "Invented"
    )
    r = c.put(
        f"/api/sitecontrol/rate-contracts/{cid}",
        json={"rate": "295", "notes": "Invented: renegotiated"},
        headers=h,
    )
    assert r.json()["version"] == 2
    assert [
        v["version"]
        for v in c.get(f"/api/sitecontrol/rate-contracts/{cid}/versions", headers=h).json()
    ] == [2, 1]
    alerts.run(db)
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "contract_expiring"))


# --- stage done, bill it -------------------------------------------------------------------------


def test_last_task_done_makes_ready_to_bill_and_raises_the_ra_bill(boss, world, db):
    c, h = boss
    contract(c, h, world)
    site = db.get(Site, world["site"])
    work.generate_tasks(db, site, None)
    db.commit()
    scope = db.get(AreaScope, world["scopes"][0])  # 60 sqm of PU coating
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
            .order_by(Task.id)
        )
    )
    last = next(t for t in reversed(tasks) if t.step and not t.step.hold_point)
    last.step.needs_photo = False  # (test data) the last step is marked done without a photo
    for t in tasks:
        if t.id != last.id:
            t.status = "certified"
    db.commit()
    assert db.scalar(select(ReadyToBill)) is None
    r = c.patch(f"/api/sites/{site.id}/tasks/{last.id}", json={"status": "done"}, headers=h)
    assert r.status_code == 200, r.text
    item = db.scalar(select(ReadyToBill))
    assert (
        item is not None
        and item.qty == D(60)
        and item.contract_line_id is not None
        and item.status == "open"
    )
    rows = c.get("/api/sitecontrol/ready-to-bill", headers=h).json()
    assert len(rows) == 1 and D(rows[0]["value"]) == D(30000)  # 60 sqm x ₹500
    item.created_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()
    alerts.run(db)
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "ready_not_billed"))
    r = c.post("/api/sitecontrol/ready-to-bill/raise", json={"site_id": site.id}, headers=h)
    assert r.status_code == 200, r.text
    ra = c.get(f"/api/finance/ra-bills/{r.json()['ra_bill_id']}", headers=h).json()
    pu = next(ln for ln in ra["lines"] if "PU coating" in ln["description"])
    assert D(pu["qty"]) == D(60)
    db.expire_all()
    assert db.get(ReadyToBill, item.id).status == "billed"


# --- new areas -----------------------------------------------------------------------------------


def test_new_area_booking_approval_and_rejection(boss, world, db):
    c, h = boss
    products = {}
    p = Product(code="NA-P", name="Invented sealant", unit="kg")
    db.add(p)
    db.commit()
    products["p"] = p.id
    site_id = world["site"]
    st = c.get("/api/material/stores", params={"site_id": site_id}, headers=h).json()[0]["id"]
    c.post(
        f"/api/material/stores/{st}/adjust",
        json={"product_id": p.id, "qty": "50", "rate": "100", "kind": "opening", "note": "Opening"},
        headers=h,
    )
    r = c.post(
        "/api/material/issues",
        json={"site_id": site_id, "lines": [{"product_id": p.id, "qty": "2"}]},
        headers=h,
    )
    assert r.status_code == 422 and "ask for a new area" in r.json()["detail"]
    r = c.post(
        "/api/sitecontrol/new-areas",
        data={"site_id": str(site_id), "name": "Invented lift machine room", "approx_sqm": "18"},
        files={"photo": ("p.jpg", jpg(), "image/jpeg")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    area = r.json()
    r = c.post(
        "/api/material/issues",
        json={
            "site_id": site_id,
            "new_area_id": area["id"],
            "lines": [{"product_id": p.id, "qty": "2"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert (
        c.get(f"/api/sitecontrol/sites/{site_id}/flags", headers=h).json()["pending_new_areas"] == 1
    )
    r = c.post(f"/api/sitecontrol/new-areas/{area['id']}/approve", json={}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    node = db.get(SiteNode, r.json()["node_id"])
    assert node.name == "Invented lift machine room" and node.site_id == site_id
    from app.material.models import SiteIssue  # noqa: PLC0415

    assert (
        db.scalar(select(SiteIssue).where(SiteIssue.new_area_id == area["id"])).node_id == node.id
    )
    # a second one is rejected: its booked material moves to the area planning picks
    r2 = c.post(
        "/api/sitecontrol/new-areas",
        data={"site_id": str(site_id), "name": "Invented duplicate"},
        files={"photo": ("p.jpg", jpg(), "image/jpeg")},
        headers=h,
    ).json()
    c.post(
        "/api/material/issues",
        json={
            "site_id": site_id,
            "new_area_id": r2["id"],
            "lines": [{"product_id": p.id, "qty": "1"}],
        },
        headers=h,
    )
    terrace = db.scalar(
        select(SiteNode).where(SiteNode.site_id == site_id, SiteNode.name == "Terrace")
    )
    r = c.post(
        f"/api/sitecontrol/new-areas/{r2['id']}/reject",
        json={"move_to_node_id": terrace.id, "note": "Invented: it is the terrace"},
        headers=h,
    )
    assert r.json()["status"] == "rejected"
    db.expire_all()
    moved = db.scalar(select(SiteIssue).where(SiteIssue.node_id == terrace.id))
    assert moved is not None and moved.new_area_id is None
    assert db.get(NewAreaRequest, r2["id"]).moved_to_node_id == terrace.id


# --- labour productivity -------------------------------------------------------------------------


def _subcon_bill(c, h, db, w, sqm: str, people: int) -> dict:
    sub = db.scalar(select(Vendor).where(Vendor.name == "Invented Applicators"))
    if sub is None:
        sub = Vendor(name="Invented Applicators", type="subcontractor", pan="ABCPD9999Z")
        db.add(sub)
        db.commit()
    wo = c.post(
        "/api/execution/work-orders",
        json={
            "site_id": w["site"],
            "subcontractor_id": sub.id,
            "material_by": "subcontractor",
            "lines": [
                {
                    "description": "Coating labour",
                    "unit": "sqm",
                    "qty": "100",
                    "rate": "50",
                    "area_scope_id": w["scopes"][0],
                    "boq_line_id": db.get(AreaScope, w["scopes"][0]).boq_line_id,
                }
            ],
        },
        headers=h,
    ).json()
    c.post(f"/api/execution/work-orders/{wo['id']}/approve", headers=h)
    wo = c.post(
        f"/api/execution/work-orders/{wo['id']}/lines/{wo['lines'][0]['id']}/measurements",
        json={"qty": sqm},
        headers=h,
    ).json()
    c.post(
        f"/api/execution/measurements/{wo['lines'][0]['measurements'][-1]['id']}/verify", headers=h
    )
    for i in range(people):
        lab = Labour(
            name=f"Invented worker {i}",
            type="subcontractor",
            subcontractor_id=sub.id,
            site_id=w["site"],
        )
        db.add(lab)
        db.flush()
        db.add(
            Attendance(labour_id=lab.id, site_id=w["site"], on_date=date.today(), status="present")
        )
    db.commit()
    r = c.post(f"/api/finance/work-orders/{wo['id']}/subcon-bills", json={}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_labour_check_to_be_set_low_and_override(boss, world, db, login_as):
    c, h = boss
    boq = db.get(BoqLine, db.get(AreaScope, world["scopes"][0]).boq_line_id)
    system = System(code="LC-SYS", name="Invented PU coating system", unit="sqm", labour_rate=40)
    db.add(system)
    db.flush()
    boq.system_id = system.id
    db.commit()
    first = _subcon_bill(c, h, db, world, "60", 10)
    assert (
        db.get(SubconBill, first["id"]).productivity_status == "to_be_set"
    )  # no expected figure yet
    db.add(ProductivityNorm(system_id=system.id, sqm_per_manday=10))
    db.commit()
    bill = _subcon_bill(c, h, db, world, "60", 10)  # 60 sqm by 20 man-days today = 3 per man-day
    b = db.get(SubconBill, bill["id"])
    assert b.productivity_status == "low" and D(b.productivity["expected"]) == 10
    assert c.post(f"/api/finance/subcon-bills/{bill['id']}/approve", headers=h).status_code == 409
    off, oh = login_as("office_admin", email="office@example.com")
    assert (
        off.post(
            f"/api/sitecontrol/subcon-bills/{bill['id']}/override",
            json={"note": "Invented: rain day"},
            headers=oh,
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/api/sitecontrol/subcon-bills/{bill['id']}/override", json={"note": ""}, headers=h
        ).status_code
        == 422
    )
    r = c.post(
        f"/api/sitecontrol/subcon-bills/{bill['id']}/override",
        json={"note": "Invented: rain stopped work at noon"},
        headers=h,
    )
    assert r.status_code == 200
    assert c.post(f"/api/finance/subcon-bills/{bill['id']}/approve", headers=h).status_code == 200
    rep = c.get("/api/sitecontrol/reports/productivity", headers=h).json()
    assert rep[0]["status"] == "low" and D(rep[0]["expected"]) == 10
    assert (
        c.get("/api/sitecontrol/reports/productivity?format=xlsx", headers=h).content[:2] == b"PK"
    )


# --- consumption variance ------------------------------------------------------------------------


def test_consumption_variance_and_the_learned_median(boss, world, db):
    c, h = boss
    p = Product(code="CV-PU", name="Invented PU", unit="kg")
    system = System(code="CV-SYS", name="Invented terrace system", unit="sqm", labour_rate=40)
    db.add_all([p, system])
    db.flush()
    db.add(
        SystemComponent(
            system_id=system.id, product_id=p.id, consumption_per_unit=D("1.5"), wastage_percent=0
        )
    )
    for sid in world["scopes"][:2]:
        db.get(BoqLine, db.get(AreaScope, sid).boq_line_id).system_id = system.id
    db.commit()
    done = db.get(AreaScope, world["scopes"][1])  # 40 sqm, 100 % done
    done.unit = "sqm"
    db.get(AreaScope, world["scopes"][0]).unit = "sqm"
    db.commit()
    st = c.get("/api/material/stores", params={"site_id": world["site"]}, headers=h).json()[0]["id"]
    c.post(
        f"/api/material/stores/{st}/adjust",
        json={
            "product_id": p.id,
            "qty": "200",
            "rate": "300",
            "kind": "opening",
            "note": "Opening",
        },
        headers=h,
    )
    r = c.post(
        "/api/material/issues",
        json={
            "site_id": world["site"],
            "area_scope_id": done.id,
            "lines": [{"product_id": p.id, "qty": "120"}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    rep = c.get(f"/api/sitecontrol/reports/consumption?site_id={world['site']}", headers=h).json()
    row = next(x for x in rep["rows"] if x["product"] == "Invented PU")
    # done: 60 sqm x 50 % + 40 sqm = 70 sqm; expected 70 x 1.5 = 105 kg; issued 120 -> +14.3 %
    assert (
        D(row["sqm_done"]) == D(70)
        and D(row["expected"]) == D(105)
        and D(row["variance_percent"]) == D("14.3")
        and not row["flag"]
    )
    c.post(
        "/api/material/issues",
        json={
            "site_id": world["site"],
            "area_scope_id": done.id,
            "lines": [{"product_id": p.id, "qty": "15"}],
        },
        headers=h,
    )
    row = next(
        x
        for x in c.get(
            f"/api/sitecontrol/reports/consumption?site_id={world['site']}", headers=h
        ).json()["rows"]
        if x["product"] == "Invented PU"
    )
    assert D(row["variance_percent"]) == D("28.6") and row["flag"]  # 135 against 105: outside ±15 %
    learned = c.get(f"/api/sitecontrol/learned?system_id={system.id}", headers=h).json()
    assert (
        learned[0]["areas"] == 1
        and D(learned[0]["site_average"]) == D("3.3750")
        and D(learned[0]["master"]) == D("1.5")
    )  # 135 kg / 40 sqm
    assert db.get(SystemComponent, db.scalar(select(SystemComponent.id))).consumption_per_unit == D(
        "1.5"
    )  # the master is not changed
    alerts.run(db)
    db.commit()
    assert db.scalar(select(Alert).where(Alert.rule == "consumption_var"))


def test_client_gets_403(login_as):
    cl, ch = login_as("client", email="customer@example.com")
    for path in (
        "/api/sitecontrol/deliveries",
        "/api/sitecontrol/rate-contracts",
        "/api/sitecontrol/ready-to-bill",
        "/api/sitecontrol/new-areas",
    ):
        assert cl.get(path, headers=ch).status_code == 403, path
    assert RateContract and Site  # imported models used above


def test_delivery_note_quantities_keep_their_zeros():
    from app.sitecontrol.pdf import qty  # noqa: PLC0415

    assert [qty(D(x)) for x in ("360", "360.000", "250.500", "0.250", "18")] == [
        "360",
        "360",
        "250.5",
        "0.25",
        "18",
    ]
