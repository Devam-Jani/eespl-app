# ruff: noqa: E501  (patterns and offer wording read better unwrapped)
"""Seeding the method library from our offers (.docx in our format): per item "TECHNICAL
SPECIFICATION ... FOR <element> ... USING <brand> SYSTEM", stage headings in bold capitals,
numbered steps under them, options as "OPTION: n -" titles or stage headings separated by "OR",
"(Client's scope)" marks, then the budgetary offer tables and the terms.

Each option becomes one system of the library (the shared stages plus its own). While seeding,
copy-paste errors are fixed and each fix is listed (where, before, after, why): spelling
(METHEDOLOGY, HORIZINTAL), repeated words ("on on", "@ @"), "over the Roof" on items that are not
roofs. Where two offers say different things for one system (mesh 40 vs 45 GSM, 1.4 vs 1.2 kg,
2 vs 3 coats) or a value looks copied from another product (the same coverage for a primer and a
PU), the value stays and is marked "to confirm"; nothing is invented. Products get the values of
their data sheet when one is found (TDS_<name>.pdf among the company files)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.methodology import datasheet, vocab
from app.methodology.models import TO_CONFIRM, MethodProduct, MethodSystem

TYPOS: list[tuple[str, str, str]] = [
    (r"\bMETHEDOLOGY\b", "METHODOLOGY", "spelling"),
    (r"\bHORIZINTAL\b", "HORIZONTAL", "spelling"),
    (r"\b(on) on\b", r"\1", "repeated word"),
    (r"@\s*@", "@", "repeated @"),
    (r"\bloos particles\b", "loose particles", "spelling"),
    (r"\bAl low\b", "Allow", "broken word"),
    (r"\bwest water\b", "waste water", "wrong word"),
    (r"\blying (\d+\s*GSM)", r"laying \1", "wrong word"),
]
ROOF_COPY = re.compile(r"(entirely\s+)?over the Roof\b", re.I)
# one product written two ways in our offers
ALIASES = {"BRONCO HYBRID PU": "BRONCO CEMSHIELD HYBRID PU"}

TOOLS = [
    ("double seam welding machine", r"double\s*seam\s*welding"),
    ("hot air gun", r"hot\s*air\s*gun"),
    ("hot air welding", r"hot\s*air\s*welding"),
    ("spatula", r"spatula"),
    ("brush", r"\bbrush\b"),
    ("roller", r"\broller\b"),
    ("trowel", r"trowel"),
    ("wire brush", r"wire[- ]?brush"),
    ("chisel", r"chisel|chipping"),
    ("grinder", r"grind"),
    ("air blower / jet", r"air\s*jet|blower"),
]
CLIENT_SCOPE = re.compile(
    r"\(?\s*(?:main\s+)?(?:client'?s?|clients?|civil\s+contractor'?s?|main\s+civil\s+contractors?['’]?)\s*(?:in\s+)?scope\s*\)?|\((?:client|civil)[^)]*scope\)",
    re.I,
)
IF_REQUIRED = re.compile(r"\(\s*if\s+required\s*\)", re.I)
BRONCO = re.compile(
    r"BRONCO®?\s+((?:[A-Z0-9][A-Z0-9.]*(?![a-z]))(?:[ \t]+(?:[A-Z0-9][A-Z0-9.]*(?![a-z])))*)"
)
GENERIC_PRODUCTS = [
    (r"(\d+(?:\.\d+)?)\s*mm[^.]{0,30}?hdpe\s*membrane|hdpe\s*membrane", "HDPE membrane"),
    (r"(\d+)\s*gsm[^.]{0,20}?(?:geo[- ]?textile|separation\s*felt)", "Geotextile"),
    (
        r"(\d+)\s*gsm[^.]{0,30}?(?:fib(?:er|re)\s*glass|glass\s*fib(?:er|re))\s*mesh",
        "Glass fibre mesh",
    ),
    (r"dimple(?:d)?\s*(?:protection\s*)?board", "Dimple protection board"),
    (r"drainage\s*board|draincell", "Drainage board"),
]
STAGE_WORDS = re.compile(
    r"PREPARATION|TREATMENT|PACKING|COATING|MEMBRANE|TERMINATION|PROTECTION|COVING|CURING|LAYER|PATCHING|SLOPE|JOINT",
    re.I,
)
DEFAULT_CONDITIONS = {
    "hdpe": "Pre-applied: laid on the PCC below the raft or on the shuttering of confined walls; accepts a damp PCC.",
    "sbs": "Unconfined walls with open excavation: needs a dry surface for the primer and backfilling after the protection.",
    "coal_tar_epoxy": "Soil-side faces below ground; not for potable water.",
    "acrylic_cementitious": "Wet areas, sunken slabs, tanks and pools: brushed on a damp substrate, covered by screed, plaster or tiles.",
    "pu_hybrid": "Exposed horizontals (terrace, drive way): needs a dry substrate; protected by screed.",
    "pu": "Exposed horizontals, planters and gardens: needs a dry substrate and a primer; covered by screed or soil.",
    "crystalline": "Concrete surfaces, positive or negative side; damp substrate.",
}
FAMILY_OF = {"hdpe": ["hdpe"], "sbs": ["sbs_membrane", "app_membrane"], "coal_tar_epoxy": ["epoxy", "bituminous"],
             "acrylic_cementitious": ["acrylic"], "pu": ["pu"], "pu_hybrid": ["pu", "polyurea"], "crystalline": ["crystalline"]}  # fmt: skip
# what a library element is called in the knowledge library (area types of Prompt 24)
AREA_OF = {"tank": ["oht", "ug_tank"], "ug_tank": ["ug_tank"], "oht": ["oht"], "planter": ["planter"], "terrace": ["terrace"],
           "sunken": ["sunken"], "balcony": ["balcony"], "toilet": ["toilet", "sunken"], "raft": ["raft"], "retaining_wall": ["retaining_wall"],
           "swimming_pool": ["swimming_pool"], "podium": ["podium"], "lift_pit": ["lift_pit"]}  # fmt: skip


@dataclass
class Fix:
    where: str
    before: str
    after: str
    why: str

    def as_dict(self) -> dict:
        return {"where": self.where, "before": self.before, "after": self.after, "why": self.why}


@dataclass
class Stage:
    heading: str
    option: str | None = None
    steps: list[dict] = field(default_factory=list)


@dataclass
class Item:
    no: str
    title: str
    option: str | None
    elements: list[str]
    brand: str | None
    stages: list[Stage] = field(default_factory=list)
    budget: list[dict] = field(default_factory=list)


@dataclass
class Offer:
    name: str
    items: list[Item]
    fixes: list[Fix]
    measurement: str | None


def _blocks(doc):
    """Paragraphs and tables in the order they come."""
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _bold(p: Paragraph) -> bool:
    style = (p.style.name if p.style is not None else "") or ""
    if style.lower().startswith(("heading", "title")):
        return True
    runs = [r for r in p.runs if r.text.strip()]
    return bool(runs) and sum(len(r.text) for r in runs if r.bold) >= 0.6 * sum(
        len(r.text) for r in runs
    )


def _is_stage(text: str, bold: bool) -> bool:
    t = text.strip().rstrip(":").strip()
    if (
        not t
        or len(t) > 90
        or t.upper() == "OR"
        or "SPECIFICATION" in t.upper()
        or t.upper().startswith("ITEM")
    ):
        return False
    letters = [c for c in t if c.isalpha()]
    upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.85
    return bool(upper and (bold or STAGE_WORDS.search(t)))


def _excerpt(before: str, after: str) -> tuple[str, str]:
    """The words around the change, not the whole step."""
    i = next(
        (k for k, (a, b) in enumerate(zip(before, after, strict=False)) if a != b),
        min(len(before), len(after)),
    )
    lo = before.rfind(" ", 0, max(0, i - 25)) + 1
    tail = len(before) - i
    return before[lo : i + 30].strip(), after[lo : len(after) - tail + 30].strip()


def fix_text(text: str, where: str, elements: list[str], fixes: list[Fix]) -> str:
    out = text
    for pat, rep, why in TYPOS:
        new = re.sub(pat, rep, out, flags=re.I if why != "spelling" else 0)
        if new != out:
            fixes.append(Fix(where, *_excerpt(vocab.clean(out), vocab.clean(new)), why))
            out = new
    if "terrace" not in elements and ROOF_COPY.search(out):
        new = ROOF_COPY.sub(lambda m: (m.group(1) or "") + "over the surface", out)
        fixes.append(
            Fix(
                where,
                *_excerpt(vocab.clean(out), vocab.clean(new)),
                '"over the Roof" copied onto an item that is not a roof',
            )
        )
        out = new
    return out


def products_in(text: str) -> list[str]:
    names = []
    for m in BRONCO.finditer(text):
        name = "BRONCO " + re.sub(r"\s+", " ", m.group(1)).strip(" .")
        name = re.sub(r"\s+(?:IN|AT|OF|AS|ON|TO|BY|WITH)$", "", name)
        names.append(ALIASES.get(name, name))
    for pat, label in GENERIC_PRODUCTS:
        m = re.search(pat, text, re.I)
        if m:
            size = m.group(1) if m.groups() and m.group(1) else None
            unit = "mm" if "HDPE" in label else "GSM"
            names.append(f"{label} {size} {unit}" if size else label)
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def step_of(text: str) -> dict:
    """A step with what it says: products, coats, consumption, waiting time, tools, scope."""
    t = vocab.clean(text)
    step: dict[str, Any] = {
        "text": t,
        "products": products_in(t),
        "scope": "ours",
        "to_confirm": [],
    }
    step["product"] = step["products"][0] if step["products"] else None
    if CLIENT_SCOPE.search(t):
        step["scope"] = "client"
    if IF_REQUIRED.search(t):
        step["if_required"] = True
    m = re.search(r"\b(\d)(?:st|nd|rd|th)\b[^.]{0,20}?coat", t, re.I) or re.search(
        r"\b(single|one)\s+coat", t, re.I
    )
    if m:
        step["coat_no"] = 1 if m.group(1).lower() in ("single", "one") else int(m.group(1))
    m = re.search(
        r"consumption of material is\s*([\d.]+)\s*kg(?:\s*in\s*(\d)\s*-?\s*coat)?", t, re.I
    )
    if m:
        step["consumption"], step["unit"] = m.group(1), "kg/m²"
        if m.group(2):
            step["coats"] = int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*kg\s*/\s*m2)", t, re.I)
    if m and "consumption" not in step:
        step["consumption"], step["unit"] = m.group(1), "kg/m²"
    m = re.search(r"coverage of\s*([\d.\s–-]+sq\.?\s*m\w*\.?\s*per\s*kg)", t, re.I)
    if m:
        step["coverage"] = vocab.clean(m.group(1))
    m = re.search(r"@\s*([\d.]+\s*(?:ml|kg|%)[^,.;]{0,40})", t, re.I)
    if m and "consumption" not in step:
        step["dosage"] = vocab.clean(m.group(1))
    m = re.search(
        r"(?:allow(?:ed)?\s+(?:to\s+)?dry[^.]*?for(?:\s+a\s+minimum\s+of)?|within)\s*((?:a\s+minimum\s+of\s+)?[\d\s.–-]+(?:to\s*\d+\s*)?(?:hrs?|hours|days))",
        t,
        re.I,
    )
    if m:
        step["wait"] = vocab.clean(m.group(1))
    m = re.search(
        r"((?:air|water)\s+curing[^.]*?(?:for|at\s+least)\s*(?:at\s+least\s*)?[\d\s–-]+(?:to\s*\d+\s*)?(?:hrs?|hours|days)(?:\s*minimum)?)",
        t,
        re.I,
    )
    if m:
        step["wait"] = vocab.clean(m.group(1))
    tools = [name for name, pat in TOOLS if re.search(pat, t, re.I)]
    if tools:
        step["tools"] = tools
    return step


def parse_offer(path: Path, name: str | None = None) -> Offer:
    doc = Document(str(path))
    name = name or path.stem
    items: list[Item] = []
    fixes: list[Fix] = []
    measurement = None
    cur: Item | None = None
    stage: Stage | None = None
    pending_no: str | None = None
    budget_for: list[Item] | None = None
    budget_n = 0
    in_terms = False
    or_next = False
    for blk in _blocks(doc):
        if isinstance(blk, Table):
            if budget_for is not None:
                for r in blk.rows[1:]:
                    cells = [vocab.clean(c.text) for c in r.cells]
                    if len(cells) >= 3 and cells[1]:
                        for it in budget_for:
                            it.budget.append(
                                {
                                    "sr": cells[0],
                                    "description": cells[1],
                                    "uom": cells[2],
                                    "rate": cells[-1],
                                }
                            )
                budget_for = None
            continue
        raw = blk.text or ""
        text = vocab.clean(raw)
        if not text:
            continue
        up = text.upper()
        if "TERMS AND CONDITIONS" in up:
            in_terms, cur, stage = True, None, None
            continue
        if in_terms:
            if re.search(r"measurement\s+shall\s+be", text, re.I):
                measurement = text
            continue
        if "BUDGETARY OFFER" in up:
            cur, stage = None, None
            m = re.search(r"ITEM\s*NO\.?\s*[:\-–]?\s*(\d+)", up)
            n = m.group(1) if m else ""
            if not m:  # "BUDGETARY OFFER FOR ...": the items in their order
                nos = list(dict.fromkeys(i.no for i in items))
                n = nos[budget_n] if budget_n < len(nos) else n
            budget_n += 1
            budget_for = [i for i in items if i.no == n] or None
            continue
        if re.fullmatch(r"ITEM\s*NO\.?\s*[:\-–]?\s*(\d+)\s*:?", up):
            pending_no = re.search(r"(\d+)", up).group(1)
            continue
        if re.search(r"TECHNICAL\s+SPECIFICATION.*\bFOR\b", up):
            m = re.search(r"ITEM\s*NO\.?\s*[:\-–]?\s*(\d+)", up)
            no = m.group(1) if m else (pending_no or str(len({i.no for i in items}) + 1))
            pending_no = None
            mo = re.search(r"OPTION\s*:?\s*(\d+)", up)
            title = re.sub(
                r"^.*?TECHNICAL\s+SPECIFICATION\s*(?:&\s*METH\w*\s*)?FOR\s*", "", up
            ).strip(" :")
            where = f"{name}: item {no}" + (f" option {mo.group(1)}" if mo else "") + " title"
            fix_text(text, where, ["terrace"], fixes)  # the title's own spelling (METHEDOLOGY)
            elements = vocab.elements_in(
                re.split(r"\bUSING\b|\bBY\b", title)[0]
            ) or vocab.elements_in(title)
            mb = re.search(
                r"\b(BRONCO|FOSROC|PIDILITE|SIKA|BASF|ARDEX|ASIAN PAINTS|CHOWGULE|CHRYSO)\b", up
            )
            brand = mb.group(1).title() if mb else None
            cur = Item(
                no=no,
                title=title.title(),
                option=mo.group(1) if mo else None,
                elements=elements,
                brand=brand,
            )
            items.append(cur)
            stage, or_next = None, False
            continue
        if cur is None:
            continue
        if up in ("OR", "==OR=="):
            or_next = True
            continue
        if text.lower().startswith("image of"):
            continue
        if _is_stage(text, _bold(blk)):
            heading = re.sub(r"^OPTION\s*:?\s*\d+\s*[-–:]\s*", "", up).strip(" :")
            mo = re.search(r"^OPTION\s*:?\s*(\d+)", up)
            opt = mo.group(1) if mo else None
            if or_next and opt is None and stage is not None:
                opt = str(int(stage.option or "1") + 1)
                if stage.option is None:
                    stage.option = "1"
            where = f"{name}: item {cur.no} stage {heading}"
            heading = fix_text(heading, where, cur.elements, fixes)
            stage = Stage(heading=heading, option=opt)
            cur.stages.append(stage)
            or_next = False
            continue
        if stage is None:
            stage = Stage(heading="GENERAL")
            cur.stages.append(stage)
        where = (
            f"{name}: item {cur.no}"
            + (f" option {cur.option}" if cur.option else "")
            + f", {stage.heading.lower()}, step {len(stage.steps) + 1}"
        )
        stage.steps.append(step_of(fix_text(text, where, cur.elements, fixes)))
    brands = [i.brand for i in items if i.brand]
    for (
        it
    ) in items:  # "USING HDPE PREFORMED MEMBRANE": the offer's brand (by Using BRONCO Products)
        it.brand = it.brand or (max(set(brands), key=brands.count) if brands else None)
        it.stages = [s for s in it.stages if s.steps]
    return Offer(name=name, items=items, fixes=fixes, measurement=measurement)


# --- from the parsed offer to systems ------------------------------------------------------------


def _paths(item: Item) -> list[tuple[str | None, list[Stage]]]:
    """One path per option: the shared stages (no option) plus the option's own."""
    opts = sorted({s.option for s in item.stages if s.option})
    if not opts:
        return [(item.option, item.stages)]
    out = []
    for o in opts:
        out.append(
            (
                o if not item.option else f"{item.option}.{o}",
                [s for s in item.stages if s.option in (None, o)],
            )
        )
    return out


def main_product(stages: list[Stage]) -> str | None:
    from collections import Counter

    c: Counter = Counter()
    for s in stages:
        if re.search(r"COATING|MEMBRANE", s.heading):
            for st in s.steps:
                if st.get("product") and "PRIMER" not in st["product"]:
                    # a waterproofing product (a type we know) weighs more than a tape or fabric
                    c[st["product"]] += 2 if vocab.system_type_of(st["product"]) else 1
    if not c:
        for s in stages:
            for st in s.steps:
                if st.get("product"):
                    c[st["product"]] += 1
    return c.most_common(1)[0][0] if c else None


def _system_type(main: str | None, stages: list[Stage]) -> str | None:
    t = vocab.system_type_of(main or "")
    if t:
        return t
    for s in stages:
        if re.search(r"COATING|MEMBRANE", s.heading):
            for st in s.steps:
                t = vocab.system_type_of(st["text"])
                if t:
                    return t
    return None


def _checklist(stages: list[Stage]) -> list[dict]:
    """Yes / No per stage: the stage done as written, and each step with a number checked."""
    out = []
    for s in stages:
        items = [f"Is the {s.heading.lower()} done as per the steps?"]
        for st in s.steps:
            if st["scope"] == "client":
                continue
            m = re.search(
                r"(overlap|lap|thickness|termination|coverage|consumption|gsm|curing)[^.]{0,60}?\d+[^.]{0,30}",
                st["text"],
                re.I,
            )
            if m:
                items.append(f"Checked: {vocab.clean(m.group(0))}?")
        out.append({"stage": s.heading, "items": items})
    return out


def _hold_points(stages: list[Stage], elements: list[str]) -> list[dict]:
    """Inspect before the work is covered: before protection / backfilling / screed / tiling."""
    out = []
    for i, s in enumerate(stages):
        if i and re.search(r"PROTECTION|SEPARATION|BACK\s*FILL|SLOPE|SCREED", s.heading):
            prev = stages[i - 1].heading.lower()
            out.append(
                {
                    "stage": stages[i - 1].heading,
                    "text": f"Inspect the {prev} and sign it before the {s.heading.lower()} covers it",
                }
            )
            break
    if not out and stages:
        out.append(
            {
                "stage": stages[-1].heading,
                "text": "Inspect and sign the finished work before it is handed over",
            }
        )
    return out


def _tests(stages: list[Stage], elements: list[str]) -> list[dict]:
    flat = " ".join(st["text"] for s in stages for st in s.steps)
    out = []
    if set(elements) & {
        "terrace",
        "sunken",
        "toilet",
        "balcony",
        "planter",
        "podium",
        "refuge",
    } or re.search(r"pond", flat, re.I):
        out.append(
            {
                "name": "Pond test before the protection layer",
                "kind": "pond",
                "hours": None,
                "to_confirm": "hours: from the client's standard or to confirm",
            }
        )
    if set(elements) & {"tank", "oht", "ug_tank", "swimming_pool", "stp"}:
        out.append(
            {
                "name": "Fill test of the tank / pool",
                "kind": "fill",
                "hours": None,
                "to_confirm": "hours: from the client's standard or to confirm",
            }
        )
    if re.search(r"COATING", " ".join(s.heading for s in stages)):
        out.append(
            {"name": "Wet film thickness check per coat (gauge)", "kind": "dft", "hours": None}
        )
    return out


def systems_from(offer: Offer) -> list[dict]:
    out = []
    for it in offer.items:
        paths = _paths(it)
        siblings = [o for x in offer.items if x.no == it.no and x is not it for o, _s in _paths(x)]
        for opt, stages in paths:
            main = main_product(stages)
            stype = _system_type(main, stages)
            els = []
            for e in it.elements:
                els += {"tank": ["oht", "ug_tank"]}.get(e, [e])
            out.append({
                "item": it, "option": opt, "stages": stages, "main": main, "type": stype, "elements": els,
                "others": [o for o, _s in paths if o != opt] + siblings, "budget": it.budget,
            })  # fmt: skip
    return out


def _stage_dicts(stages: list[Stage]) -> list[dict]:
    return [
        {"heading": s.heading, "option": None, "steps": [dict(st) for st in s.steps]}
        for s in stages
    ]


def _code(db: Session, element: str, stype: str | None) -> str:
    base = f"{element}-{stype or 'system'}".upper().replace("_", "-")[:32]
    n = (
        db.scalar(
            select(func.count()).select_from(MethodSystem).where(MethodSystem.code.like(base + "%"))
        )
        or 0
    )
    return f"{base}-{n + 1}"


def _compare(a: MethodSystem, b_stages: list[dict], a_src: str, b_src: str) -> list[dict]:
    """Where two offers differ for one system: mesh GSM, kg, coats, the mesh before or after the
    first coat. Each difference is a value to confirm."""

    def facts(stages: list[dict]) -> dict:
        steps = [st for s in stages for st in s["steps"]]
        main = None
        f: dict[str, Any] = {}
        for st in steps:
            if (
                st.get("product")
                and vocab.system_type_of(st["product"])
                and "PRIMER" not in st["product"]
            ):
                main = main or st["product"]
        mesh = [
            st["text"]
            for st in steps
            if re.search(r"gsm[^.]{0,40}(mesh|geo|fabric|non[- ]woven)", st["text"], re.I)
            and not re.search(
                r"separation|slip|over the coated|drainage|120\s*gsm|150\s*gsm", st["text"], re.I
            )
        ]
        if mesh:
            f["mesh"] = (
                ", ".join(sorted(set(re.findall(r"(\d+)\s*gsm", " ".join(mesh), re.I)))) + " GSM"
            )
        kg = [st.get("consumption") for st in steps if st.get("consumption")]
        if kg:
            f["kg"] = kg[0] + " kg/m²"
        if main:
            apps = [i for i, st in enumerate(steps) if st.get("product") == main]
            f["coats"] = str(len(apps))
            stated = [st.get("coats") for st in steps if st.get("coats")]
            if stated and stated[0] != len(apps):
                f["coats_note"] = (
                    f"{len(apps)} applications of {main} (the primer is the same product, diluted) but the text says {stated[0]}-coat"
                )
            mesh_i = next((i for i, st in enumerate(steps) if st["text"] in mesh), None)
            if mesh_i is not None and apps:
                after = [i for i in apps if i < mesh_i]
                f["mesh_order"] = (
                    "mesh after the 1st coat" if len(after) >= 2 else "mesh before the 1st coat"
                )
        return f

    fa, fb = facts(a.stages), facts(b_stages)
    out = []
    for key, label in (
        ("mesh", "Mesh / fabric reinforcement"),
        ("kg", "Consumption"),
        ("coats", "Coats"),
        ("mesh_order", "When the mesh is laid"),
    ):
        if key in fa and key in fb and fa[key] != fb[key]:
            out.append(
                {
                    "field": key,
                    "label": label,
                    "note": f"{a_src}: {fa[key]}; {b_src}: {fb[key]}",
                    "value": TO_CONFIRM,
                }
            )
    for f, src in ((fa, a_src), (fb, b_src)):
        if f.get("coats_note"):
            out.append(
                {
                    "field": "coats",
                    "label": "Coats",
                    "note": f"{src}: {f['coats_note']}",
                    "value": TO_CONFIRM,
                }
            )
    return out


def _product(
    db: Session, name: str, brand: str | None, data_root: Path | None, report: dict
) -> MethodProduct:
    p = db.scalar(select(MethodProduct).where(MethodProduct.name == name))
    if p is not None:
        return p
    from app.masters.models import Product

    master = db.scalar(
        select(Product).where(
            func.upper(Product.name).in_(
                [name.upper()] + [k for k, v in ALIASES.items() if v == name]
            )
        )
    )
    kind = None
    low = name.lower()
    for k, pat in (("primer", "primer"), ("membrane", "membrane|sbs|hdpe"), ("mortar", "repair|pmc"), ("grout", "grout"), ("admixture", "cemkrete"),
                   ("mesh", "mesh|geotextile|proseal|tape"), ("board", "board"), ("epoxy", "eba|poxy"), ("coating", "cemguard|ultrashield|hybrid|crystal|pu\\b")):  # fmt: skip
        if re.search(pat, low):
            kind = k
            break
    p = MethodProduct(
        name=name,
        brand=brand if name.upper().startswith("BRONCO") else None,
        kind=kind,
        product_id=master.id if master else None,
        values={},
        standards=[],
    )
    tds = datasheet.find_tds(name, data_root) if brand else None
    if tds:
        values, standards = datasheet.read_values(datasheet.text_of(tds), source=tds.name)
        p.values, p.standards = values, standards
        root = Path(app_settings.data_dir)
        p.datasheet_path = (
            str(tds.relative_to(root)) if str(tds).startswith(str(root)) else str(tds)
        )
        p.datasheet_name = tds.name
        p.source = f"data sheet {tds.name}"
        report["datasheets"] += 1
    db.add(p)
    db.flush()
    report["products"] += 1
    return p


def _consumption(db: Session, master_id: int | None) -> tuple[str, str] | None:
    """The consumption most used in our old BOQs (the Prompt 24 consumption table)."""
    if not master_id:
        return None
    from app.costing.models import ProductConsumption
    from app.costing.working import readable_source

    row = db.scalars(
        select(ProductConsumption)
        .where(ProductConsumption.product_id == master_id)
        .order_by(ProductConsumption.used_count.desc())
    ).first()
    return (
        (
            f"{row.consumption.normalize():f}",
            f"{readable_source(row.source)}, used {row.used_count}×",
        )
        if row
        else None
    )


def _templates(db: Session, elements: list[str], stype: str | None) -> list[int]:
    from app.knowledge.models import KnowledgeTemplate

    areas = sorted({a for e in elements for a in AREA_OF.get(e, [e])})
    q = select(KnowledgeTemplate).where(
        KnowledgeTemplate.area_type.in_(areas),
        KnowledgeTemplate.hidden.is_(False),
        KnowledgeTemplate.merged_into_id.is_(None),
    )
    fams = FAMILY_OF.get(stype or "", [])
    rows = [
        t
        for t in db.scalars(q.order_by(KnowledgeTemplate.lines_count.desc()).limit(200))
        if not fams or set(t.families or []) & set(fams)
    ]
    return [t.id for t in rows[:3]]


def seed(
    db: Session, paths: list[Path], user_id=None, data_root: Path | None = None, demo: bool = False
) -> dict:
    """Read the offers and add their systems to the library (a system already seeded from an
    earlier offer gets the later one as a second source and the differences to confirm)."""
    report: dict[str, Any] = {
        "offers": [],
        "items": 0,
        "options": 0,
        "systems": 0,
        "merged": 0,
        "steps": 0,
        "products": 0,
        "datasheets": 0,
        "fixes": [],
        "to_confirm": [],
    }
    for path in paths:
        label = _offer_label(path)
        offer = parse_offer(path, label)
        report["offers"].append(
            {
                "file": path.name,
                "items": len({i.no for i in offer.items}),
                "options": len(systems_from(offer)),
            }
        )
        report["items"] += len({i.no for i in offer.items})
        report["fixes"] += [f.as_dict() for f in offer.fixes]
        for sd in systems_from(offer):
            it: Item = sd["item"]
            report["options"] += 1
            stages = _stage_dicts(sd["stages"])
            report["steps"] += sum(len(s["steps"]) for s in stages)
            source = {
                "file": path.name,
                "offer": label,
                "item": it.no,
                "option": sd["option"],
                "title": it.title,
            }
            element = sd["elements"][0] if sd["elements"] else "general"
            existing = _same(db, sd["elements"], sd["main"])
            if existing is not None:
                diffs = _compare(
                    existing,
                    stages,
                    existing.sources[0]["offer"] if existing.sources else "earlier offer",
                    label,
                )
                existing.sources = existing.sources + [source]
                existing.to_confirm = existing.to_confirm + diffs
                report["to_confirm"] += [{"system": existing.code, **d} for d in diffs]
                report["merged"] += 1
                continue
            # products, with their data sheets and consumption
            for s in stages:
                for st in s["steps"]:
                    for pname in st.get("products") or []:
                        mp = _product(db, pname, it.brand, data_root, report)
                        if (
                            pname == st.get("product")
                            and not st.get("consumption")
                            and mp.kind in ("coating", "membrane")
                        ):
                            c = _consumption(db, mp.product_id)
                            if c:
                                st["consumption"], st["unit"], st["consumption_source"] = (
                                    c[0],
                                    "kg/m²",
                                    c[1],
                                )
                        if pname == st.get("product") and st.get("coverage"):
                            tds_cov = (mp.values.get("coverage") or {}).get("value")
                            if (
                                mp.kind == "primer"
                                and tds_cov
                                and not _same_coverage(st["coverage"], tds_cov)
                            ):
                                note = f"coverage \"{st['coverage']}\" (as written for the Hybrid PU) but the data sheet says \"{tds_cov}\""
                                st["to_confirm"].append(note)
                                report["fixes"].append(
                                    Fix(
                                        f"{label}: item {it.no}, {s['heading'].lower()}",
                                        st["coverage"],
                                        tds_cov,
                                        "primer coverage copied from another product: the data sheet's value",
                                    ).as_dict()
                                )
                                st["text"] = st["text"].replace(st["coverage"], tds_cov)
                                st["coverage"] = tds_cov
                            elif mp.kind == "primer" and not tds_cov:
                                st["to_confirm"].append(
                                    f"coverage \"{st['coverage']}\": no data sheet value to check it against"
                                )
            main = sd["main"]
            stype = sd["type"]
            sysd = MethodSystem(
                code=_code(db, element, stype),
                name=f"{_short_title(it.title)} — {(main or vocab.SYSTEM_LABEL.get(stype or '', 'system')).title()}",
                brand=it.brand,
                system_type=stype,
                elements=sd["elements"],
                conditions=[{"text": DEFAULT_CONDITIONS[stype], "source": "EESPL default (edit)"}]
                if stype in DEFAULT_CONDITIONS
                else [],
                why=None,
                competing=[{"option": o, "why_not": TO_CONFIRM} for o in sd["others"]],
                stages=stages,
                hold_points=_hold_points(sd["stages"], sd["elements"]),
                tests=_tests(sd["stages"], sd["elements"]),
                checklist=_checklist(sd["stages"]),
                guarantee_years=None,
                boq_description=_boq_text(sd["budget"], sd["option"]),
                measurement_rule=_measure(sd["budget"], offer.measurement),
                specs=_specs(db, main, stages),
                to_confirm=[
                    {
                        "field": "guarantee_years",
                        "label": "Guarantee",
                        "note": "not in the offer",
                        "value": TO_CONFIRM,
                    },
                    {
                        "field": "why",
                        "label": "Why we pick it",
                        "note": "not in the offer",
                        "value": TO_CONFIRM,
                    },
                ],  # fmt: skip
                fixes=[
                    f.as_dict() for f in offer.fixes if f.where.startswith(f"{label}: item {it.no}")
                ],
                sources=[source],
                template_ids=_templates(db, sd["elements"], stype),
                master_system_id=None,
                created_by=user_id,
                is_demo=demo,
            )
            for s in stages:
                for st in s["steps"]:
                    for note in st.get("to_confirm") or []:
                        sysd.to_confirm = sysd.to_confirm + [
                            {
                                "field": "step",
                                "label": s["heading"].title(),
                                "note": note,
                                "value": TO_CONFIRM,
                            }
                        ]
            db.add(sysd)
            db.flush()
            report["systems"] += 1
        db.flush()
    report["fixes"] = _dedupe(report["fixes"])
    return report


def _short_title(title: str) -> str:
    """ "Sunken, Kitchen Yard & Balcony Area Waterproofing Works By Using Bronco System" ->
    "Sunken, Kitchen Yard & Balcony"."""
    t = re.split(r"\s+(?:by\s+)?using\b|\s+by\s+", title, maxsplit=1, flags=re.I)[0]
    t = re.sub(
        r"\s*(?:area\s+)?(?:waterproofing|water\s*proofing)(?:\s+works?)?\s*$", "", t, flags=re.I
    )
    t = re.sub(r"\s+(?:treatment|works?)\s*$", "", t, flags=re.I)
    return t.strip(" -–:") or title


def _offer_label(path: Path) -> str:
    m = re.search(r"@\s*(.+?)(?:\.docx)?$", path.name)
    return vocab.clean(m.group(1)) if m else path.stem


def _same(db: Session, elements: list[str], main: str | None) -> MethodSystem | None:
    if not main:
        return None
    for s in db.scalars(select(MethodSystem).where(MethodSystem.is_active)):
        if (
            s.elements
            and elements
            and s.elements[0] == elements[0]
            and main in {st.get("product") for x in s.stages for st in x["steps"]}
        ):
            if main_product([Stage(x["heading"], None, x["steps"]) for x in s.stages]) == main:
                return s
    return None


def _same_coverage(a: str, b: str) -> bool:
    return re.findall(r"\d+(?:\.\d+)?", a) == re.findall(r"\d+(?:\.\d+)?", b)


def _boq_text(budget: list[dict], option: str | None) -> str | None:
    if not budget:
        return None
    rows = [
        r
        for r in budget
        if option
        and (
            r["sr"].startswith(f"Opt.{option.split('.')[-1]}")
            or r["sr"].startswith(f"Opt {option}")
        )
    ]
    row = rows[0] if rows else budget[0]
    return row["description"]


def _measure(budget: list[dict], terms: str | None) -> str | None:
    uoms = sorted(
        {
            r["uom"].split()[0].upper()
            for r in budget
            if r.get("uom") and "SCOPE" not in r["uom"].upper()
        }
    )
    parts = []
    if uoms:
        parts.append("Per " + " / ".join(uoms) + " as in the budgetary offer")
    if terms:
        parts.append(terms)
    return ". ".join(parts) or None


def _specs(db: Session, main: str | None, stages: list[dict]) -> dict:
    """What the system claims: the main product's data sheet values and the step values."""
    out: dict[str, Any] = {}
    if main:
        mp = db.scalar(select(MethodProduct).where(MethodProduct.name == main))
        for k, v in ((mp.values if mp else {}) or {}).items():
            if v.get("num") is not None:
                out[k] = {
                    "value": v["value"],
                    "num": v["num"],
                    "unit": v.get("unit"),
                    "standard": v.get("standard"),
                    "source": f"{main} data sheet",
                }
    text = " ".join(st["text"] for s in stages for st in s["steps"])
    for k, lim in vocab.specs_in(text).items():
        out.setdefault(
            k,
            {"value": lim.text(), "num": lim.num, "unit": lim.unit, "source": "the method's steps"},
        )
    for s in stages:
        for st in s["steps"]:
            if st.get("product") == main and st.get("consumption") and "consumption" not in out:
                try:
                    num = float(re.findall(r"[\d.]+", st["consumption"])[0])
                    out["consumption"] = {
                        "value": f"{st['consumption']} kg/m²",
                        "num": num,
                        "unit": "kg/m²",
                        "source": st.get("consumption_source") or "the method's steps",
                    }
                except (IndexError, ValueError):
                    pass
    return out


def _dedupe(fixes: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in fixes:
        k = (f["where"], f["before"], f["after"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out
