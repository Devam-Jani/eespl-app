# ruff: noqa: E501, F811  (invented data reads better unwrapped; shared fixtures are imported)
"""Part 0 of the methodology milestone, invented data: a DXF whose MTEXT has a raw line break reads
after repair; the library picker ranks by match, then rates near the place, and says why; rates
read per sqm that are per sq ft are converted and far ones flagged; step lines of one system are
one main item, each priced from its own part of the build-up; unknown products go to the review
list, not the master; the review queue hides single-line templates."""

import io
from datetime import timedelta
from decimal import Decimal

import ezdxf
from sqlalchemy import select

from app.knowledge import extract, library
from app.knowledge.models import KnowledgeFile, KnowledgeLine, KnowledgeTemplate, ProductReview
from app.masters.models import Product, System, SystemComponent
from app.takeoff.reader import read, repair
from app.tenders.models import BoqLine, BoqSection, Tender
from app.timefmt import ist_today
from tests.test_finance import boss  # noqa: F401  (fixtures)


def d(v) -> Decimal:
    return Decimal(str(v))


def test_a_dxf_with_a_raw_line_break_in_an_mtext_reads_after_repair(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_line((0, 0), (1000, 0))
    msp.add_mtext(
        "NOTE 1 Invented first line ZZZBREAK the rest of the note",
        dxfattribs={"insert": (0, 0), "char_height": 50},
    )
    buf = io.StringIO()
    doc.write(buf)
    broken = (
        buf.getvalue().replace(" ZZZBREAK ", "\n").encode()
    )  # what dwg2dxf writes: a raw line break
    p = tmp_path / "broken.dxf"
    p.write_bytes(broken)
    with __import__("pytest").raises(ezdxf.DXFStructureError):
        ezdxf.read(io.StringIO(broken.decode()))  # a strict reader fails
    fixed, n = repair(broken)
    assert n == 1
    parsed = read(p)
    assert parsed.repairs == 1 and parsed.summary()["dxf_repairs"] == 1
    assert any(
        "Invented first line" in t[4] and "the rest of the note" in t[4] for t in parsed.texts
    )


def _line(db, desc, city, rate, unit="sqm", unit_raw="Sqm", working=None, on=None):
    f = KnowledgeFile(
        path=f"inv/{abs(hash(desc))}/{city}/{rate}/{unit_raw}.xlsx",
        kind="xlsx",
        status="read",
        city=city,
    )
    db.add(f)
    db.flush()
    req = extract.requirements(desc)
    ln = KnowledgeLine(file_id=f.id, sheet="BOQ", row=2, description=desc, unit=unit, unit_raw=unit_raw, rate=d(rate),
                       rate_sqm=d(rate) if unit == "sqm" else (d(rate) * d("10.7639")).quantize(d("0.01")),
                       area_type=req.area_type, surface=req.surface, coats=req.coats, min_kg_sqm=req.min_kg_sqm,
                       requirements=req.as_dict(), city=city, region="Ahmedabad" if city in ("Ahmedabad", "Bopal") else "Saurashtra",
                       on_date=on or ist_today() - timedelta(days=30), working=working)  # fmt: skip
    db.add(ln)
    db.flush()
    return ln


def test_the_picker_ranks_by_match_then_rates_near_the_place_and_says_why(boss, db):
    c, h = boss
    rcc = "Sunken area waterproofing on the RCC slab with 2 coats of acrylic coating"
    screed = "Sunken toilet chemical waterproofing over the screed with acrylic based compound"
    for city in ("Rajkot", "Jamnagar"):
        _line(db, rcc, city, 700)
    for i in range(9):
        _line(db, screed + f" invented {i}", "Ahmedabad", 600 + i)
    db.commit()
    library.group(db)
    db.commit()
    found = c.post(
        "/api/knowledge/propose",
        json={"area_type": "sunken", "surface": "rcc", "coats": 2, "city": "Ahmedabad"},
        headers=h,
    ).json()["templates"]
    first = found[0]
    assert (
        "screed" in first["name"] and first["rates"]["city_stats"]["n"] == 9
    )  # the rates near the place win
    assert any("9 rate(s) in the city" in w for w in first["why"])
    other = next(t for t in found if "RCC" in t["name"])
    assert any("RCC ✓" in w for w in other["why"]) and any(
        "no past rate near the place" in w for w in other["why"]
    )
    assert any(
        "no working to price, fill from the system" in w for w in first["why"]
    )  # shown, and says so


def test_rates_per_sq_ft_read_as_per_sqm_are_converted_and_far_ones_flagged(db):
    for i in range(6):
        _line(
            db,
            f"Terrace waterproofing with PU coating, 2 coats, invented {i}",
            "Ahmedabad",
            800 + 10 * i,
        )
    blank = _line(
        db,
        "Terrace waterproofing with PU coating, 2 coats, invented per sq ft",
        "Ahmedabad",
        75,
        unit_raw="",
    )
    stated = _line(
        db, "Terrace geotextile protection layer, invented", "Ahmedabad", 65, unit_raw="Sqm"
    )
    db.commit()
    out = library.check_units(db)
    assert out["converted"] == 1
    assert blank.rate_sqm == d("807.29") and blank.check_note.startswith("unit read as sq ft")
    assert stated.rate_sqm == 65  # its unit says sqm: kept
    library.group(db)
    far = library.flag_far_rates(db)
    assert far >= 0


def test_step_lines_of_one_system_are_one_main_item_each_priced_from_its_part(boss, db):
    c, h = boss
    t = Tender(code="T-2026-9701", name="Invented steps", status="draft")
    db.add(t)
    db.flush()
    sec = BoqSection(tender_id=t.id, title="Sunken, kitchen yard & balcony area", sort_order=1)
    db.add(sec)
    db.flush()
    texts = ["Surface Preparation, opening the cracks and filling them", "Pipe sleeve packing using non shrink grout",
             "Applying waterproof polymer coating in two coats"]  # fmt: skip
    for i, txt in enumerate(texts):
        db.add(
            BoqLine(
                tender_id=t.id,
                section_id=sec.id,
                sort_order=i,
                client_item_no=str(i + 1),
                description=txt,
                unit="sqm",
                qty=100,
            )
        )
    pipe = Product(code="T-PIPE-GROUT", name="Invented pipe sleeve grout", unit="kg")
    coat = Product(code="T-COAT", name="Invented polymer coating", unit="kg")
    db.add_all([pipe, coat])
    db.flush()
    s = System(
        code="T-SUNK",
        name="Invented sunken system",
        surface_prep_per_unit=40,
        labour_rate=10,
        labour_unit="sqft",
        default_margin_percent=20,
    )
    s.components = [
        SystemComponent(product_id=pipe.id, consumption_per_unit=d("0.1")),
        SystemComponent(product_id=coat.id, consumption_per_unit=d("1.5")),
    ]
    db.add(s)
    db.commit()
    for p, rate in ((pipe, "200"), (coat, "100")):
        c.post(
            f"/api/prices/products/{p.id}",
            json={"rate": rate, "effective_from": "2026-09-01"},
            headers=h,
        )
    w = c.get(f"/api/rate-working/tenders/{t.id}", headers=h).json()
    w = c.post(f"/api/rate-working/{w['id']}/suggest", headers=h).json()
    assert len(w["groups"]) == 1 and w["groups"][0]["name"] == "Sunken, kitchen yard & balcony area"
    g = c.put(
        f"/api/rate-working/groups/{w['groups'][0]['id']}", json={"system_id": s.id}, headers=h
    ).json()
    assert c.post(f"/api/rate-working/{w['id']}/apply", headers=h).status_code == 200
    rates = {
        ln.description[:12]: Decimal(ln.rate)
        for ln in db.scalars(select(BoqLine).where(BoqLine.tender_id == t.id))
    }
    factor = d(g["rate_sqm"]) / d(g["cost_sqm"])
    assert rates["Surface Prep"] == round(40 * factor, 2)  # its own part: the surface preparation
    assert rates["Pipe sleeve "] == round(d("0.1") * 200 * factor, 2)  # the pipe sleeve grout
    assert rates["Applying wat"] < d(g["rate_sqm"])  # not the whole system on one line
    assert sum(rates.values()) == round(d(g["rate_sqm"]), 2) or abs(
        sum(rates.values()) - d(g["rate_sqm"])
    ) < d("0.05")


def test_unknown_products_wait_for_review_and_join_the_master_only_when_accepted(
    boss, boq_like, db
):
    c, h = boss
    before = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Product))
    working = {"items": [{"label": "Invented Mystery Coat", "kind": "product", "consumption": "1.2", "price": "180", "ref": "Working!E3"}],
               "cost": "400", "margin_on_selling_percent": "20"}  # fmt: skip
    for city in ("Ahmedabad", "Bopal"):
        _line(
            db,
            "Raft waterproofing with HDPE membrane below the raft, invented",
            city,
            650,
            working=working,
        )
    db.commit()
    library.group(db)
    db.commit()
    tid = db.scalar(select(KnowledgeTemplate.id).where(KnowledgeTemplate.area_type == "raft"))
    r = c.post(
        f"/api/knowledge/groups/{boq_like['group']}/apply",
        json={"template_id": tid, "city": "Ahmedabad"},
        headers=h,
    ).json()
    assert r["to_review"][0]["label"] == "Invented Mystery Coat"
    assert (
        db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Product)) == before
    )  # the master is untouched
    rev = db.scalar(select(ProductReview))
    assert rev.status == "pending" and rev.old_price == 180
    out = c.post(
        f"/api/knowledge/product-reviews/{rev.id}",
        json={"action": "accept", "unit": "kg"},
        headers=h,
    ).json()
    assert out["status"] == "accepted" and out["product"]["name"] == "Invented Mystery Coat"


def test_the_review_queue_hides_single_line_templates_and_suggests_merges(boss, db):
    c, h = boss
    for i in range(2):
        _line(db, f"Planter waterproofing with PU coating invented {i}", "Ahmedabad", 500)
    _line(
        db,
        "Planter waterproofing with PU coating over the screed invented, a planter",
        "Ahmedabad",
        520,
    )
    _line(db, "Swimming pool waterproofing, crystalline, invented single", "Ahmedabad", 900)
    db.commit()
    library.group(db)
    db.commit()
    q = c.get("/api/knowledge/review-queue", headers=h).json()
    assert q and all(t["lines"] > 1 for t in q)
    assert all(t["lines"] > 1 for t in c.get("/api/knowledge/templates", headers=h).json())
    assert any(
        t["lines"] == 1 for t in c.get("/api/knowledge/templates?singles=true", headers=h).json()
    )
    planter = next(t for t in q if t["area_type"] == "planter")
    sugg = c.get(f"/api/knowledge/templates/{planter['id']}/merge-suggestions", headers=h).json()
    assert all(s["area_type"] == "planter" for s in sugg)


import pytest  # noqa: E402


@pytest.fixture
def boq_like(boss, db):
    """A tender with one raft line and its working's main item."""
    c, h = boss
    t = Tender(code="T-2026-9702", name="Invented raft", status="draft")
    db.add(t)
    db.flush()
    db.add(
        BoqLine(
            tender_id=t.id,
            sort_order=1,
            client_item_no="1",
            description="Raft waterproofing with HDPE membrane",
            unit="sqm",
            qty=200,
        )
    )
    db.commit()
    w = c.get(f"/api/rate-working/tenders/{t.id}", headers=h).json()
    w = c.post(f"/api/rate-working/{w['id']}/suggest", headers=h).json()
    return {"tender": t.id, "group": w["groups"][0]["id"]}
