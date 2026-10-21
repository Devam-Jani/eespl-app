# ruff: noqa: E501
"""A won BOQ's methodology into the site: per item a stage template (the stages as steps; the
stages the client holds become hold points that the office certifies before the next step can
start), the checklist as the inspection form of its stage, the pond tests as test records with
the hours the standard asks (photos and the result on site), and the sampling as material tests
that a delivery of the product makes due."""

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution.models import ChecklistItem, ChecklistTemplate
from app.methodology import vocab
from app.methodology.models import (
    MaterialTest,
    Methodology,
    MethodologyItem,
    MethodProduct,
    MethodSystem,
    PondTest,
    PreBidQuery,
    StandardRule,
)
from app.sites.models import StageTemplate, StageTemplateStep

COVERS = re.compile(r"PROTECTION|SEPARATION|SCREED|SLOPE|BACK\s*FILL|PLASTER", re.I)


def _wait_hours(text: str | None) -> float:
    """ "3 to 4 hrs" -> 4, "air curing for 48 hours" -> 48, "at least 3 days" -> 72."""
    if not text:
        return 0.0
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return 0.0
    return max(nums) * (24 if re.search(r"day", text, re.I) else 1)


def stage_days(stage: dict) -> int:
    """A stage's days: half a day of work per step of ours, plus its waiting and curing time
    (the testing stage: the hours its tests need); at least one."""
    steps = [x for x in stage["steps"] if x.get("scope") != "client"] or stage["steps"]
    hours = sum(_wait_hours(x.get("wait")) for x in steps)
    return max(1, round(len(steps) * 0.5 + hours / 24))


def _weights(days: list[int]) -> list[Decimal]:
    from app.sites.work import weights_by_days

    return weights_by_days(days)


def _checklist(db: Session, name: str, stage: dict) -> ChecklistTemplate:
    name = name[:200]
    t = db.scalar(select(ChecklistTemplate).where(ChecklistTemplate.name == name))
    if t is None:
        t = ChecklistTemplate(name=name)
        db.add(t)
        db.flush()
        for i, q in enumerate(stage["items"]):
            db.add(
                ChecklistItem(
                    template_id=t.id, sort_order=i, text=q[:2000], type="pass_fail", required=True
                )
            )
        db.flush()
    return t


def _stems(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]{4,}", text.lower())} - {
        "waterproofing",
        "area",
        "application",
    }


def _match(heading: str, checklist: list[dict], used: set[str]) -> dict | None:
    words = _stems(heading)
    best, score = None, 0
    for c in checklist:
        if c["stage"] in used:
            continue
        s = len(words & _stems(c["stage"]))
        if s > score:
            best, score = c, s
    return best


def stage_template(db: Session, m: Methodology, it: MethodologyItem, user_id=None) -> StageTemplate:
    """The item's stages as a stage template (made once; the same item gives the same template)."""
    if it.stage_template_id:
        t = db.get(StageTemplate, it.stage_template_id)
        if t:
            return t
    rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
    system = db.get(MethodSystem, it.system_id) if it.system_id else None
    checklist = (
        (rule.checklist if rule and rule.checklist else None)
        or (system.checklist if system else [])
        or []
    )
    stages = [s for s in it.stages if s["steps"]]
    name = f"{m.code} · {it.name}"[:190] + f" #{it.id}"  # one per item, never another item's
    t = db.scalar(select(StageTemplate).where(StageTemplate.name == name))
    if t is None:
        words = " ".join(
            {
                vocab.ELEMENT_LABEL.get(it.element or "", ""),
                it.name,
                *(s["heading"].lower() for s in stages[:3]),
            }
        )
        t = StageTemplate(
            name=name,
            system_id=system.master_system_id if system else None,
            keywords=words[:2000],
            created_by=user_id,
        )
        db.add(t)
        db.flush()
        main_i = (
            max(
                range(len(stages)),
                key=lambda i: (bool(re.search(r"COATING|MEMBRANE", stages[i]["heading"])), -i),
            )
            if stages
            else -1
        )
        used = set()
        days_all = [stage_days(s) for s in stages]
        for i, (s, w, days) in enumerate(zip(stages, _weights(days_all), days_all, strict=True)):
            nxt = stages[i + 1]["heading"] if i + 1 < len(stages) else ""
            hold = bool(COVERS.search(nxt)) or s["heading"] == "TESTING"
            c = _match(s["heading"], checklist, used)
            free = [x for x in checklist if x["stage"] not in used]
            if c is None and i == main_i and free:
                c = max(free, key=lambda x: len(x["items"]))
            tpl = None
            if c is not None:
                used.add(c["stage"])
                tpl = _checklist(db, f"{m.code} {it.name} — {c['stage']}", c)
            db.add(StageTemplateStep(template_id=t.id, sort_order=i + 1, name=s["heading"].title()[:200], weight_percent=w, needs_photo=True,
                                     needs_inspection=tpl is not None or hold, hold_point=hold, checklist_template_id=tpl.id if tpl else None, typical_days=days))  # fmt: skip
        db.flush()
        db.refresh(t)
    it.stage_template_id = t.id
    return t


def handover(db: Session, m: Methodology, site_id: int | None, user_id=None) -> dict:
    """Stage templates for every item; with a site, its pond tests and material tests too
    (made once: a second handover adds only what is missing)."""
    out = {
        "stage_templates": 0,
        "hold_points": 0,
        "checklists": 0,
        "pond_tests": 0,
        "material_tests": 0,
    }
    products: dict[str, tuple] = {}
    for it in m.items:
        t = stage_template(db, m, it, user_id)
        out["stage_templates"] += 1
        out["hold_points"] += sum(1 for s in t.steps if s.hold_point)
        out["checklists"] += sum(1 for s in t.steps if s.checklist_template_id)
        if site_id is None:
            continue
        rule = db.get(StandardRule, it.rule_id) if it.rule_id else None
        system = db.get(MethodSystem, it.system_id) if it.system_id else None
        tests = (rule.tests if rule else []) or [
            {"kind": x.get("kind"), "hours": x.get("hours"), "text": x["name"]}
            for x in (system.tests if system else [])
        ]
        have = {
            (p.methodology_item_id, p.kind, p.required_hours)
            for p in db.scalars(select(PondTest).where(PondTest.site_id == site_id))
        }
        for x in tests:
            if x.get("kind") not in ("pre_pond", "pond", "fill"):
                continue
            hours = x.get("hours")
            if not hours:
                continue
            if (it.id, x["kind"], hours) in have:
                continue
            label = {"pre_pond": "Pre-pond test", "pond": "Pond test", "fill": "Fill test"}[
                x["kind"]
            ]
            db.add(PondTest(site_id=site_id, methodology_item_id=it.id, stage_template_id=t.id, name=f"{it.name}: {label} {hours} h", kind=x["kind"], required_hours=hours,
                            depth_mm=x.get("depth_mm"), reference=x.get("text", "")[:500] or None, created_by=user_id))  # fmt: skip
            out["pond_tests"] += 1
        sampling = next(
            (x["text"] for x in (rule.tests if rule else []) if x.get("kind") == "sampling"), None
        )
        for s in it.stages:
            if not re.search(r"COATING|MEMBRANE", s["heading"]):
                continue
            for x in s["steps"]:
                pname = x.get("product")
                if pname and pname not in products:
                    products[pname] = (it, [], sampling)
                if pname and rule is not None and rule not in products[pname][1]:
                    products[pname][1].append(rule)
    # one row per product on the site (a product in several items is sampled once)
    if site_id is not None:
        known = {
            mt.product_name
            for mt in db.scalars(select(MaterialTest).where(MaterialTest.site_id == site_id))
        }
        queries = list(
            db.scalars(
                select(PreBidQuery).where(
                    PreBidQuery.methodology_id == m.id, PreBidQuery.kind == "contradiction"
                )
            )
        )
        for pname, (it, rules, sampling) in products.items():
            if pname in known:
                continue
            mp = db.scalar(select(MethodProduct).where(MethodProduct.name == pname))
            specs = product_specs(rules, pname, mp.kind if mp else None, queries)
            db.add(MaterialTest(site_id=site_id, methodology_item_id=it.id, product_name=pname, product_id=mp.product_id if mp else None, tests=specs,
                                frequency=sampling or "on every delivery: the manufacturer's test certificate, cross-checked with the specification", status="planned", created_by=user_id))  # fmt: skip
            out["material_tests"] += 1
    if site_id is not None:
        m.site_id = site_id
    db.flush()
    return out


def product_specs(
    rules: list[StandardRule], pname: str, kind: str | None, queries: list
) -> list[dict]:
    """The client's specs for this product's own material: a mesh gets the mesh weight, a coating
    the coating's values (not the membrane's or the PU's). Where the SOP says two things, the
    stricter one, with the pre-bid query that asks which applies."""
    if not rules:
        return []
    ptype = vocab.system_type_of(pname)
    rows = [
        {**x, "_doc": r.document_id}
        for r in rules
        for x in r.min_specs
        if x.get("num") is not None and x.get("op") in ("min", "eq", "range")
    ]
    if kind == "mesh" or re.search(r"mesh|geo[- ]?textile|fabric", pname, re.I):
        rows = [x for x in rows if x["property"] == "mesh_gsm"]
    elif ptype:
        mine = [
            x
            for x in rows
            if x["property"] != "mesh_gsm"
            and vocab.family(x.get("system_type")) == vocab.family(ptype)
        ]
        untyped = [x for x in rows if x["property"] != "mesh_gsm" and not x.get("system_type")]
        rows = mine or (
            untyped if any(vocab.satisfies(ptype, r.system_type) for r in rules) else []
        )
    else:
        rows = []
    out: dict[str, dict] = {}
    for x in rows:
        prop = x["property"]
        got = out.get(prop)
        if got is None:
            out[prop] = {
                "property": x["label"],
                "standard": vocab.standard_of(x.get("standard") or ""),
                "required": x["required"],
                "num": x["num"],
                "page": x.get("page"),
                "_doc": x["_doc"],
            }
            continue
        if float(x["num"]) == float(got["num"]):
            continue
        stricter = (
            x if (float(x["num"]) > float(got["num"])) == (prop in vocab.HIGHER_IS_BETTER) else None
        )
        other = got["required"] if stricter else x["required"]
        if stricter:
            got.update(
                required=x["required"],
                num=x["num"],
                standard=vocab.standard_of(x.get("standard") or "") or got["standard"],
                page=x.get("page"),
            )
        notes = got.setdefault("notes", [])
        if x["_doc"] != got["_doc"]:
            if other not in " ".join(notes):
                notes.append(f"another SOP asks {other}: the stricter is used")
            continue
        q = next(
            (
                q
                for q in queries
                if q.text.lower().startswith(vocab.PROPERTY_LABEL.get(prop, prop).lower())
            ),
            None,
        )
        notes.insert(
            0,
            f"the SOP also says {other}: the stricter is used"
            + (f"; pre-bid query #{q.id}" if q else ""),
        )
        if q:
            got["prebid_query_id"] = q.id
    for r in out.values():
        if r.get("notes"):
            r["note"] = "; ".join(dict.fromkeys(r.pop("notes")))
    return [{k: v for k, v in r.items() if k not in ("num", "_doc")} for r in out.values()]


def on_delivery(db: Session, grn) -> int:
    """A delivery (GRN) of a product with a planned test at its site: that test is due."""
    from app.material.models import Store

    store = db.get(Store, grn.store_id)
    site_id = getattr(store, "site_id", None)
    if not site_id:
        return 0
    product_ids = {ln.product_id for ln in grn.lines if ln.accepted_qty and ln.accepted_qty > 0}
    n = 0
    for mt in db.scalars(
        select(MaterialTest).where(
            MaterialTest.site_id == site_id,
            MaterialTest.product_id.in_(product_ids or {0}),
            MaterialTest.status == "planned",
        )
    ):
        db.add(MaterialTest(site_id=site_id, methodology_item_id=mt.methodology_item_id, product_name=mt.product_name, product_id=mt.product_id, tests=mt.tests,
                            frequency=mt.frequency, grn_id=grn.id, status="due", reference=f"{grn.code} received {grn.received_at:%d.%m.%Y}" if grn.received_at else grn.code))  # fmt: skip
        n += 1
    return n


def on_win(db: Session, tender, site_id: int | None, user_id=None) -> dict | None:
    """The tender is won: its latest methodology goes to the site."""
    m = db.scalars(
        select(Methodology)
        .where(Methodology.tender_id == tender.id)
        .order_by(Methodology.revision.desc(), Methodology.id.desc())
    ).first()
    if m is None:
        return None
    return handover(db, m, site_id, user_id)


def share_latest(db: Session, tender, site_id: int, user_id=None) -> None:
    from app.methodology import export

    m = db.scalars(
        select(Methodology)
        .where(Methodology.tender_id == tender.id)
        .order_by(Methodology.revision.desc(), Methodology.id.desc())
    ).first()
    if m is not None:
        export.share_with_client(db, m, site_id, user_id)


def on_win_quotation(db: Session, q, tender, site, user_id=None) -> dict | None:
    """The quotation is won: its methodology (or its tender's) goes to the site, and the
    client's copy is shared with the client in the portal."""
    from app.methodology import export

    m = db.scalars(
        select(Methodology).where(Methodology.quotation_id == q.id).order_by(Methodology.id.desc())
    ).first()
    if m is None and tender is not None:
        m = db.scalars(
            select(Methodology)
            .where(Methodology.tender_id == tender.id)
            .order_by(Methodology.id.desc())
        ).first()
    if m is None:
        return None
    if tender is not None and m.tender_id is None:
        m.tender_id = tender.id
    out = handover(db, m, site.id if site else None, user_id)
    if site is not None:
        export.share_with_client(db, m, site.id, user_id)
    return out


def pond_hours(p: PondTest) -> float | None:
    if p.started_at and p.ended_at:
        return round((p.ended_at - p.started_at).total_seconds() / 3600, 1)
    return None
