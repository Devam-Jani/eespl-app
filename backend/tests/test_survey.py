# ruff: noqa: E501  (fixtures and expectations read better on one line)
"""Site survey: area maths, consumption and packs, BOQ lines and indents, the camera billing gate,
the camera-vs-laser mismatch, AI suggestions (mocked: the real API is never called), access.
Invented data."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.finance.models import ClientContract, ContractLine, RaBill, RaBillLine
from app.main import app
from app.masters.models import Client, Product, System, SystemComponent
from app.material.models import Indent
from app.models import User
from app.sites.models import Site
from app.survey import ai
from app.survey import service as svc
from app.survey.models import AiCall, AreaType, SurveyArea, SurveyBoqLink
from app.survey.pdf import MARKER_CODES, marker_bits
from app.tenders.models import BoqLine, Tender
from tests.conftest import login


def D(x) -> Decimal:
    """Decimal from a JSON number or string (via str, so 4.08 stays 4.08)."""
    return Decimal(str(x))


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SECRET = "sk-ant-INVENTED-test-key-0000"


@pytest.fixture(autouse=True)
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def boss(login_as):
    return login_as("super_admin", email="boss@example.com")


@pytest.fixture
def world(boss, db):
    """Two products (one in 20 kg bags), a PU system (1.5 kg/sqm membrane at 5 % wastage,
    0.2 l/sqm primer at 0 %), area types, a client, a tender and its site."""
    client, h = boss
    membrane = Product(
        code="P-MEM", name="Invented PU membrane", unit="kg", pack_size=20, pack_unit="bag"
    )
    primer = Product(code="P-PRI", name="Invented primer", unit="ltr")
    pu = System(code="SYS-PU", name="Invented PU system", unit="sqm", labour_rate=50)
    db.add_all([membrane, primer, pu])
    db.flush()
    db.add_all(
        [
            SystemComponent(
                system_id=pu.id,
                product_id=membrane.id,
                consumption_per_unit=D("1.5"),
                wastage_percent=5,
            ),
            SystemComponent(
                system_id=pu.id,
                product_id=primer.id,
                consumption_per_unit=D("0.2"),
                wastage_percent=0,
            ),
        ]
    )
    toilet = AreaType(
        name="T Toilet", default_system_id=pu.id, default_upturn_mm=300, created_by=None
    )
    sunk = AreaType(name="T Sunken", default_upturn_mm=300, needs_sunk_depth=True)
    tank = AreaType(name="T Tank", includes_walls=True, default_wastage_percent=10)
    for t in (toilet, sunk, tank):
        t.created_by = db.scalar(select(User.id).where(User.email == "boss@example.com"))
    c = Client(name="Invented Builders", type="builder")
    db.add_all([toilet, sunk, tank, c])
    db.flush()
    t = Tender(code="T-S-1", name="Invented tower", client_id=c.id, status="won")
    db.add(t)
    db.flush()
    site = Site(code="S-S-1", name="Invented site", client_id=c.id, tender_id=t.id, status="active")
    db.add(site)
    db.commit()
    return {
        "membrane": membrane.id,
        "primer": primer.id,
        "pu": pu.id,
        "toilet": toilet.id,
        "sunk": sunk.id,
        "tank": tank.id,
        "tender": t.id,
        "site": site.id,
        "client": c.id,
    }


def new_survey(client, h, **parent):
    r = client.post("/api/surveys", json={"title": "Invented survey", **parent}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def add_area(client, h, sid, **body):
    r = client.post(f"/api/surveys/{sid}/areas", json={"name": "Area", **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["areas"][-1]


# --- area maths ----------------------------------------------------------------------------------


def test_area_maths(boss, world):
    client, h = boss
    s = new_survey(client, h, site_id=world["site"])
    sid = s["id"]
    # rect 3 x 2, 0.5 sqm deducted, 300 mm upturn on the 10 m perimeter, 14 identical toilets
    a = add_area(
        client,
        h,
        sid,
        area_type_id=world["toilet"],
        length_m="3",
        width_m="2",
        deductions_sqm="0.5",
        count=14,
    )
    assert (
        D(a["floor_area_sqm"]),
        D(a["perimeter_m"]),
        D(a["upturn_mm"]),
        D(a["upturn_area_sqm"]),
    ) == (D("5.5"), D(10), D(300), D(3))
    assert D(a["treated_area_sqm"]) == (D("5.5") + 3) * 14
    # polygon (shoelace): an L-shape of 4 x 3 minus a 2 x 1 corner = 10 sqm, perimeter 14 m
    a = add_area(
        client,
        h,
        sid,
        shape="polygon",
        polygon_m=[[0, 0], [4, 0], [4, 3], [2, 3], [2, 2], [0, 2]],
        upturn_mm=0,
    )
    assert (D(a["floor_area_sqm"]), D(a["perimeter_m"])) == (D(10), D(14))
    # sunk sides: perimeter x depth, only for a type that needs it
    a = add_area(
        client, h, sid, area_type_id=world["sunk"], length_m="2", width_m="1.5", sunk_depth_mm=450
    )
    assert (D(a["sunk_area_sqm"]), D(a["upturn_area_sqm"])) == (
        D("3.15"),
        D("2.1"),
    )  # 7 m x 0.45, 7 m x 0.3
    assert D(a["treated_area_sqm"]) == D(3) + D("2.1") + D("3.15")
    # walls: perimeter x wall height for a wall type; the typed perimeter of a direct area
    a = add_area(
        client,
        h,
        sid,
        area_type_id=world["tank"],
        shape="direct",
        direct_area_sqm="12",
        perimeter_m="14",
        wall_height_m="2.5",
    )
    assert (D(a["wall_area_sqm"]), D(a["treated_area_sqm"])) == (D(35), D(47))
    a = add_area(
        client, h, sid, length_m="2", width_m="2", sunk_depth_mm=450, wall_height_m=3, upturn_mm=0
    )  # no type: no sides
    assert D(a["treated_area_sqm"]) == 4
    assert (
        client.post(
            f"/api/surveys/{sid}/areas",
            json={"name": "x", "shape": "polygon", "polygon_m": [[0, 0], [1, 1]]},
            headers=h,
        ).status_code
        == 422
    )
    assert (
        svc.floor_number("B2") == -2
        and svc.floor_number("Ground") == 0
        and svc.floor_number("Floor 14") == 14
    )


# --- consumption ---------------------------------------------------------------------------------


def test_consumption_wastage_precedence_packs_and_no_system(boss, world, db):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    # three 4 sqm areas (2 x 2, no upturn) on the PU system: membrane 4 x 1.5 x 1.05 = 6.3 kg each
    for floor in ("Floor 1", "Floor 2", "Floor 3"):
        add_area(
            client,
            h,
            sid,
            area_type_id=world["toilet"],
            length_m="2",
            width_m="2",
            upturn_mm=0,
            floor_label=floor,
        )
    # an area type wastage (10 %) beats the component's; the area's own (0 %) beats both
    add_area(
        client,
        h,
        sid,
        area_type_id=world["tank"],
        length_m="2",
        width_m="2",
        system_id=world["pu"],
        floor_label="Floor 4",
    )
    add_area(
        client,
        h,
        sid,
        area_type_id=world["tank"],
        length_m="2",
        width_m="2",
        system_id=world["pu"],
        wastage_override_percent=0,
        floor_label="Floor 5",
    )
    add_area(
        client, h, sid, area_type_id=world["sunk"], length_m="9", width_m="9", floor_label="Floor 6"
    )  # no system
    c = client.get(f"/api/surveys/{sid}/consumption", headers=h).json()
    mem = next(p for p in c["products"] if p["product_id"] == world["membrane"])
    pri = next(p for p in c["products"] if p["product_id"] == world["primer"])
    # 3 x 6.3 + 4 x 1.5 x 1.10 (type: 10 % for both products) + 4 x 1.5 x 1.00
    assert D(mem["qty"]) == D("18.9") + D("6.6") + D("6.0")
    assert D(pri["qty"]) == 3 * D("0.8") + D("0.88") + D(
        "0.8"
    )  # primer: 0 % component, 10 % type, 0 % area
    # whole bags only on the survey total: 31.5 kg -> 2 bags of 20 kg (not one bag per area)
    assert (mem["packs"], D(mem["pack_qty"]), D(mem["spare_qty"])) == (2, D(40), D("8.5"))
    assert pri["packs"] is None  # no pack size: no rounding
    assert c["no_system_count"] == 1 and c["no_system"][0]["floor"] == "Floor 6"
    floors = {f["key"]: f for f in c["by_floor"]}
    assert D(floors["Floor 1"]["products"][0]["qty"]) == D("6.3")


def test_boq_lines_and_indent_draft_from_a_survey(boss, world, db):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    for floor in ("Floor 1", "Floor 2"):
        add_area(
            client,
            h,
            sid,
            area_type_id=world["toilet"],
            length_m="2",
            width_m="2",
            upturn_mm=0,
            floor_label=floor,
            method="laser",
        )
    add_area(
        client,
        h,
        sid,
        area_type_id=world["tank"],
        length_m="3",
        width_m="3",
        system_id=world["pu"],
        floor_label="Floor 2",
    )
    add_area(
        client, h, sid, area_type_id=world["sunk"], length_m="1", width_m="1"
    )  # no system: left out
    r = client.post(f"/api/surveys/{sid}/boq", json={"split_by_area_type": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["lines"] == 2 and r.json()["tender_id"] == world["tender"]
    lines = {
        ln.description: ln
        for ln in db.scalars(select(BoqLine).where(BoqLine.tender_id == world["tender"]))
    }
    toilet = next(ln for d, ln in lines.items() if "T Toilet" in d)
    assert (toilet.qty, toilet.unit, toilet.system_id) == (D("8.000"), "sqm", world["pu"])
    assert (
        len(db.scalars(select(SurveyBoqLink).where(SurveyBoqLink.boq_line_id == toilet.id)).all())
        == 2
    )
    one = client.post(
        f"/api/surveys/{sid}/boq", json={"tender_id": world["tender"]}, headers=h
    ).json()
    assert one["lines"] == 1  # not split: one line per system
    r = client.post(f"/api/surveys/{sid}/indent", json={"floors": ["Floor 2"]}, headers=h)
    assert r.status_code == 201, r.text
    ind = db.get(Indent, r.json()["indent_id"])
    # floor 2: 4 sqm x 1.5 x 1.05 + 9 x 1.5 x 1.10 = 6.3 + 14.85 = 21.15 kg -> 2 bags = 40 kg
    mem = next(ln for ln in ind.lines if ln.product_id == world["membrane"])
    assert (ind.status, D(mem.qty), mem.unit) == ("draft", D(40), "kg") and "2 × 20" in mem.remark
    assert client.get(f"/api/surveys/{sid}/pdf", headers=h).content[:4] == b"%PDF"
    assert client.get(f"/api/surveys/{sid}/xlsx", headers=h).content[:2] == b"PK"


# --- camera: billing gate, mismatch, pilot -------------------------------------------------------


def test_camera_only_areas_cannot_be_billed_until_allowed(boss, world, db):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    # not measured yet: a direct area of 0 until the camera measures it
    a = add_area(
        client,
        h,
        sid,
        area_type_id=world["toilet"],
        shape="direct",
        direct_area_sqm="0",
        upturn_mm=0,
    )
    r = client.post(
        f"/api/surveys/areas/{a['id']}/camera",
        json={"method": "marker", "polygon_m": [[0, 0], [3, 0], [3, 2], [0, 2]]},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["areas"][0]["camera_measured"] is True
    assert D(r.json()["areas"][0]["floor_area_sqm"]) == 6
    client.post(f"/api/surveys/{sid}/boq", json={}, headers=h)
    line = db.scalar(select(BoqLine).where(BoqLine.tender_id == world["tender"]))
    c = ClientContract(
        site_id=world["site"],
        tender_id=world["tender"],
        client_id=world["client"],
        contract_value=100000,
    )
    db.add(c)
    db.flush()
    cl = ContractLine(
        contract_id=c.id,
        boq_line_id=line.id,
        description=line.description,
        unit="sqm",
        qty=6,
        rate=500,
    )
    db.add(cl)
    db.flush()
    b = RaBill(
        code="RA-S-1",
        contract_id=c.id,
        site_id=world["site"],
        seq=1,
        period_to=svc_today(),
        status="certified",
        gross=3000,
        certified_gross=3000,
        net=3000,
    )
    db.add(b)
    db.flush()
    db.add(
        RaBillLine(
            ra_bill_id=b.id,
            contract_line_id=cl.id,
            previous_qty=0,
            suggested_qty=6,
            qty=6,
            certified_qty=6,
            rate=500,
            amount=3000,
        )
    )
    db.commit()
    r = client.post(f"/api/finance/ra-bills/{b.id}/invoice", json={}, headers=h)
    assert r.status_code == 409 and "measured only by the camera" in r.text
    # a laser size makes it billable (the camera value stays for the pilot)
    ok = client.put(
        f"/api/surveys/areas/{a['id']}",
        json={
            "name": "Area",
            "area_type_id": world["toilet"],
            "length_m": "3.1",
            "width_m": "2",
            "upturn_mm": 0,
            "method": "laser",
        },
        headers=h,
    ).json()
    area = ok["areas"][0]
    assert (area["method"], D(area["camera_floor_sqm"]), D(area["floor_area_sqm"])) == (
        "laser",
        D(6),
        D("6.2"),
    )
    assert (
        D(area["mismatch_percent"]) == D("3.2") and area["mismatch_flag"] is True
    )  # over the 3 % setting
    assert (
        client.post(f"/api/finance/ra-bills/{b.id}/invoice", json={}, headers=h).status_code == 201
    )
    pilot = client.get("/api/surveys/pilot", headers=h).json()
    assert pilot["rows"][0]["mode"] == "marker" and D(pilot["rows"][0]["difference_percent"]) == D(
        "-3.2"
    )
    assert pilot["summary"][0]["worst_percent"] == "3.2" or D(
        str(pilot["summary"][0]["worst_percent"])
    ) == D("3.2")
    assert (
        client.get("/api/surveys/pilot", params={"format": "xlsx"}, headers=h).content[:2] == b"PK"
    )


def test_billing_gate_passes_with_the_setting_or_the_clients_certification(boss, world, db):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    a = add_area(
        client, h, sid, area_type_id=world["toilet"], length_m="1", width_m="1", upturn_mm=0
    )
    area = db.get(SurveyArea, a["id"])
    area.method = "ar"
    db.commit()
    client.post(f"/api/surveys/{sid}/boq", json={}, headers=h)
    line = db.scalar(select(BoqLine).where(BoqLine.tender_id == world["tender"]))
    c = ClientContract(
        site_id=world["site"],
        tender_id=world["tender"],
        client_id=world["client"],
        contract_value=100000,
    )
    db.add(c)
    db.flush()
    cl = ContractLine(
        contract_id=c.id, boq_line_id=line.id, description="x", unit="sqm", qty=1, rate=500
    )
    db.add(cl)
    db.flush()
    bills = []
    for n, by in ((1, None), (2, "Client PMC")):
        b = RaBill(
            code=f"RA-G-{n}",
            contract_id=c.id,
            site_id=world["site"],
            seq=n,
            period_to=svc_today(),
            status="certified",
            gross=500,
            certified_gross=500,
            net=500,
            certified_by_client=by,
        )
        db.add(b)
        db.flush()
        db.add(
            RaBillLine(
                ra_bill_id=b.id,
                contract_line_id=cl.id,
                previous_qty=0,
                suggested_qty=1,
                qty=1,
                certified_qty=1,
                rate=500,
                amount=500,
            )
        )
        bills.append(b.id)
    db.commit()
    assert (
        client.post(f"/api/finance/ra-bills/{bills[1]}/invoice", json={}, headers=h).status_code
        == 201
    )  # the client certified it
    assert (
        client.post(f"/api/finance/ra-bills/{bills[0]}/invoice", json={}, headers=h).status_code
        == 409
    )
    svc.settings(db).camera_billing_allowed = True
    db.commit()
    assert (
        client.post(f"/api/finance/ra-bills/{bills[0]}/invoice", json={}, headers=h).status_code
        == 201
    )


def svc_today():
    from app.analytics.common import today

    return today()


# --- submit, approve, 3D map ---------------------------------------------------------------------


def test_submit_needs_a_photo_per_area_then_approve_and_3d_map(boss, world, db):
    from app.sites.models import SiteNode

    client, h = boss
    node = SiteNode(site_id=world["site"], kind="floor", name="Floor 1")
    db.add(node)
    db.commit()
    sid = new_survey(client, h, site_id=world["site"])["id"]
    a = add_area(
        client,
        h,
        sid,
        area_type_id=world["toilet"],
        length_m="2",
        width_m="2",
        node_id=node.id,
        method="laser",
    )
    r = client.post(f"/api/surveys/{sid}/submit", headers=h)
    assert r.status_code == 422 and "photo" in r.text
    r = client.post(
        f"/api/surveys/areas/{a['id']}/photos",
        files={"file": ("t.png", PNG, "image/png")},
        data={
            "mode": "laser",
            "tilt_beta": "45",
            "zoom": "1",
            "width_px": "4000",
            "height_px": "3000",
        },
        headers=h,
    )
    assert r.status_code == 201 and r.json()["areas"][0]["photos"][0]["mode"] == "laser"
    assert client.post(f"/api/surveys/{sid}/submit", headers=h).json()["status"] == "submitted"
    assert (
        client.get(f"/api/surveys/site-map/{world['site']}", headers=h).json()["nodes"] == {}
    )  # approved surveys only
    assert client.post(f"/api/surveys/{sid}/approve", headers=h).json()["status"] == "approved"
    m = client.get(f"/api/surveys/site-map/{world['site']}", headers=h).json()
    assert m["nodes"] == {str(node.id): "measured"}
    assert {p["name"] for p in m["products"][str(node.id)]} == {
        "Invented PU membrane",
        "Invented primer",
    }
    assert (
        client.post(
            f"/api/surveys/{sid}/areas",
            json={"name": "late", "length_m": 1, "width_m": 1},
            headers=h,
        ).status_code
        == 409
    )


def test_copy_and_repeat_on_floors(boss, world):
    client, h = boss
    sid = new_survey(client, h, tender_id=world["tender"])["id"]
    a = add_area(
        client,
        h,
        sid,
        name="Floor 1 Toilet 1",
        floor_label="Floor 1",
        area_type_id=world["toilet"],
        length_m="2",
        width_m="1.5",
        count=2,
    )
    r = client.post(
        f"/api/surveys/areas/{a['id']}/repeat", json={"floor_from": 2, "floor_to": 14}, headers=h
    )
    areas = r.json()["areas"]
    assert len(areas) == 14 and {x["floor_label"] for x in areas} == {
        f"Floor {n}" for n in range(1, 15)
    }
    assert any(x["name"] == "Floor 14 Toilet 1" for x in areas)
    assert D(r.json()["totals"]["treated"]) == 14 * D(a["treated_area_sqm"])
    copied = client.post(f"/api/surveys/areas/{a['id']}/copy", headers=h).json()["areas"]
    assert len(copied) == 15


# --- AI ------------------------------------------------------------------------------------------


def test_ai_is_off_by_default_mocked_capped_and_never_shows_the_key(
    boss, world, db, monkeypatch, media
):
    client, h = boss
    sid = new_survey(client, h, site_id=world["site"])["id"]
    a = add_area(client, h, sid, length_m="2", width_m="2")
    from PIL import Image

    img = media / "p.jpg"
    Image.new("RGB", (3200, 2400), (180, 170, 160)).save(img)
    photo = client.post(
        f"/api/surveys/areas/{a['id']}/photos",
        files={"file": ("p.jpg", img.read_bytes(), "image/jpeg")},
        headers=h,
    ).json()
    pid = photo["areas"][0]["photos"][0]["id"]
    assert photo["ai_available"] is False
    assert (
        client.post(
            f"/api/surveys/areas/{a['id']}/suggest", json={"photo_id": pid}, headers=h
        ).status_code
        == 403
    )  # off
    s = svc.settings(db)
    s.ai_enabled = True
    db.commit()
    assert (
        client.get(f"/api/surveys/{sid}", headers=h).json()["ai_available"] is False
    )  # no key in .env
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(SECRET))
    sent = []

    def fake_post(payload):
        sent.append(payload)
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"area_type": "T Toilet", "condition_notes": "hairline cracks, damp corner", '
                    '"system": "Invented PU system", "confidence": "medium"}',
                }
            ],
            "usage": {"input_tokens": 1600, "output_tokens": 120},
        }

    monkeypatch.setattr(ai, "_post", fake_post)
    r = client.post(f"/api/surveys/areas/{a['id']}/suggest", json={"photo_id": pid}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["suggestion"]["area_type_id"] == world["toilet"]
        and body["suggestion"]["system_id"] == world["pu"]
    )
    # 1,600 x $3 + 120 x $15 per million tokens = $0.0066 = ₹0.561 at 85
    assert (body["input_tokens"], D(body["cost_inr"])) == (1600, D("0.5610"))
    payload = sent[0]
    text = payload["messages"][0]["content"][1]["text"]
    assert (
        "Invented PU system" in text and "rate" not in text.lower() and "cost" not in text.lower()
    )
    from base64 import b64decode
    from io import BytesIO

    sent_img = Image.open(
        BytesIO(b64decode(payload["messages"][0]["content"][0]["source"]["data"]))
    )
    assert max(sent_img.size) == 1600  # downscaled
    acc = client.post(
        f"/api/surveys/ai/{body['call_id']}/accept",
        json={"area_type": True, "system": False, "notes": True},
        headers=h,
    ).json()
    area = acc["areas"][0]
    assert (
        area["area_type_id"] == world["toilet"]
        and area["system_id"] is None
        and "hairline cracks" in area["remarks"]
    )
    assert (D(area["length_m"]), D(area["width_m"])) == (2, 2)  # sizes untouched
    call = db.scalar(select(AiCall))
    assert call.accepted == {"area_type": True, "system": False, "notes": True}
    # the month's cap stops further calls
    s.ai_monthly_cap_inr = D("0.5")
    db.commit()
    r = client.post(f"/api/surveys/areas/{a['id']}/suggest", json={"photo_id": pid}, headers=h)
    assert r.status_code == 409 and "cap" in r.text and len(sent) == 1
    # the key never appears anywhere
    for path in (f"/api/surveys/{sid}", "/api/surveys/settings", "/api/surveys/ai/usage"):
        assert SECRET not in client.get(path, headers=h).text
    assert client.get("/api/surveys/settings", headers=h).json()["ai_key_present"] is True


# --- access --------------------------------------------------------------------------------------


def test_scopes_client_403_and_rates_need_tender_margin(
    boss, world, db, make_user, login_as, monkeypatch
):
    from app.crm.models import Lead

    client, h = boss
    mine = make_user("sales-a@example.com", "sales")
    other = make_user("sales-b@example.com", "sales")
    la = Lead(
        code="L-A",
        contact_name="A",
        phone="+919000000001",
        lead_source="call",
        status="new",
        owner_id=mine.id,
    )
    lb = Lead(
        code="L-B",
        contact_name="B",
        phone="+919000000002",
        lead_source="call",
        status="new",
        owner_id=other.id,
    )
    db.add_all([la, lb])
    db.commit()
    ca = TestClient(app)
    ha = login(ca, "sales-a@example.com")
    s_a = new_survey(ca, ha, lead_id=la.id)
    assert (
        ca.post("/api/surveys", json={"title": "x", "lead_id": lb.id}, headers=ha).status_code
        == 404
    )  # not their lead
    s_b = new_survey(client, h, lead_id=lb.id)
    assert [x["id"] for x in ca.get("/api/surveys", headers=ha).json()] == [s_a["id"]]
    assert ca.get(f"/api/surveys/{s_b['id']}", headers=ha).status_code == 404
    assert ca.post(f"/api/surveys/{s_a['id']}/approve", headers=ha).status_code == 403
    cc, hc = login_as("client", email="client@example.com")
    assert cc.get("/api/surveys", headers=hc).status_code == 403
    assert cc.get("/api/surveys/marker-sheet.pdf", headers=hc).status_code == 403
    # rates in the PDF only with tender.margin (sales has none)
    seen = []
    from app.survey import pdf as survey_pdf

    real = survey_pdf.survey_pdf
    monkeypatch.setattr(
        survey_pdf,
        "survey_pdf",
        lambda db, s, parent, include_rates: seen.append(include_rates)
        or real(db, s, parent, include_rates),
    )
    ca.get(f"/api/surveys/{s_a['id']}/pdf", params={"include_rates": "true"}, headers=ha)
    client.get(f"/api/surveys/{s_a['id']}/pdf", params={"include_rates": "true"}, headers=h)
    assert seen == [False, True]
    assert (
        "rate"
        not in str(ca.get(f"/api/surveys/{s_a['id']}/consumption", headers=ha).json()).lower()
    )


def test_marker_sheet_matches_the_detector_dictionary(boss):
    client, h = boss
    r = client.get("/api/surveys/marker-sheet.pdf", headers=h)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    # ARUCO_MIP_36h12 ids 0 and 1 as js-aruco2 lists them; a 1 is a white cell
    assert format(MARKER_CODES[0], "036b") == "".join(str(b) for row in marker_bits(0) for b in row)
    assert marker_bits(0)[0] == [1, 1, 0, 1, 0, 0]  # 0xd2b63a09d starts 1101 0010 ...
    assert MARKER_CODES[1] == 0x6001134E5


def test_a3_marker_sheet_has_two_250_mm_markers_on_a3(boss):
    import io

    import pdfplumber

    client, h = boss
    r = client.get("/api/surveys/marker-sheet.pdf?size=a3", headers=h)
    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        assert len(pdf.pages) == 2
        # A3 portrait: 297 x 420 mm = 841.9 x 1190.6 pt
        assert abs(pdf.pages[0].width - 841.9) < 2 and abs(pdf.pages[0].height - 1190.6) < 2
        text = pdf.pages[0].extract_text()
        assert "250 mm" in text and "A3" in text
    assert MARKER_CODES[2] == 0x1206FBE72 and MARKER_CODES[3] == 0xFF8AD6CB4
    assert client.get("/api/surveys/marker-sheet.pdf?size=a5", headers=h).status_code == 422


def test_raft_and_footing_area_types_are_seeded_unconfirmed(db):
    types = {
        t.name: t
        for t in db.scalars(select(AreaType).where(AreaType.name.in_(["Raft", "Footing"])))
    }
    assert set(types) == {"Raft", "Footing"}
    assert types["Raft"].default_wastage_percent == Decimal("7")
    assert types["Footing"].default_wastage_percent == Decimal("15")
    assert not types["Raft"].confirmed and not types["Footing"].confirmed
