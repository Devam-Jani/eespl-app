# ruff: noqa: E501  (the patterns read better unwrapped)
"""A BOQ line read into key points ("chips"): area, system type, the steps in order, coats, DFT or
thickness, kg per sqm, mesh, upturn, protection thickness, property minimums with their standard,
the make named and whether an equivalent is allowed, potable / UV, pond test, warranty, unit and
qty. Rules first (the knowledge library's area, brand and warranty words, the data sheet reader's
number patterns); each chip keeps the words it came from (start, end in the description) so the
page can highlight them. A chip from the AI is "suggested" until a person confirms it."""

import hashlib
import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge import extract
from app.spec import tds, vocab
from app.spec.vocab import D, dec

STEP_ORDER = ["surface_prep", "primer", "coat", "mesh", "protection", "joint", "pipe", "test"]
STEP_WORDS = {
    "surface_prep": r"surface\s*prep\w*|cleaning|grinding|chipping|hacking|wire\s*brush\w*",
    "primer": r"primer|priming",
    "mesh": r"\bmesh\b|\bfabric\b|reinforc\w*\s*(?:cloth|fib(?:re|er)|scrim)|glass\s*fib(?:re|er)\s*(?:cloth|tissue)|\bscrim\b",
    "protection": r"protect\w*\s*(?:screed|plaster|layer|board|course)|\bscreed\b|\bpcc\b|brick\s*bat|\bbbc\b|\btil(?:e|es|ing)\b|geo\s*-?\s*textile",
    "joint": r"coving|fillet|\bvata\b|\bjoints?\b",
    "pipe": r"\bpipes?\b|outlets?|spouts?|khurra|rain\s*water",
    "test": r"pond(?:ing)?\s*test|flood\s*test|water\s*(?:tightness\s*)?test|spray\s*test",
}
STEP_LABEL = {"surface_prep": "surface preparation", "primer": "primer", "mesh": "mesh", "protection": "protection",
              "joint": "joint / coving", "pipe": "pipe / outlet treatment", "test": "pond test"}  # fmt: skip
# brand names in the master that are ordinary words (a BOM's "Standard", "SC" rows)
NOT_BRANDS = {"standard", "approved", "other", "others", "general", "local", "any", "best", "make", "brand", "same",
              "equivalent", "reputed", "manufacturer", "company", "generic", "regular", "normal", "white", "black"}  # fmt: skip
EQUIVALENT = re.compile(
    r"or\s*equiv\w*|equivalent|approved\s*make|or\s*equal|or\s*similar|as\s*approved|approved\s*brand",
    re.I,
)
ONE_K = re.compile(
    r"single\s*(?:component|pack|part)|one\s*(?:component|pack|part)|\b1\s*-?\s*k\b|mono\s*component",
    re.I,
)
TWO_K = re.compile(
    r"two\s*(?:component|pack|part)|\b2\s*-?\s*k\b|double\s*component|bi\s*-?\s*component", re.I
)
UPTURN = re.compile(
    r"up\s*-?\s*turn\w*[^0-9.]{0,25}(\d+)\s*mm|(\d+)\s*mm\s*(?:high\s*|height\s*)?(?:up\s*-?\s*turn|on\s*(?:the\s*)?(?:vertical|walls?|parapets?))|up\s*to\s*(\d+)\s*mm\s*(?:height|high)",
    re.I,
)
PROTECT_MM = re.compile(
    r"(\d+(?:\.\d+)?)\s*mm\s*(?:thk\.?|thick\w*)?\s*(?:protect\w*|screed|pcc|plaster|cement\s*mortar|c\.?m\.?\s)|(?:protect\w*\s*screed|screed|pcc|protection)[^0-9.]{0,30}(\d+(?:\.\d+)?)\s*mm",
    re.I,
)
POND = re.compile(r"pond(?:ing)?\s*test|flood\s*test|water\s*(?:tightness\s*)?test", re.I)
HOURS = re.compile(r"(\d+)\s*(?:hours|hrs?|h)\b", re.I)
DEPTH = re.compile(
    r"(\d+)\s*mm\s*(?:of\s*)?(?:water\s*depth|depth|water)|water\s*depth\s*(?:of\s*)?(\d+)\s*mm",
    re.I,
)
POTABLE = re.compile(r"potable|drinking\s*water|nsf\s*61|wras", re.I)
UV = re.compile(
    r"uv\s*-?\s*(?:resistant|stable|resistance|exposed)|exposed\s*to\s*(?:sun|uv|weather)|exposed\s*(?:roof|terrace|condition)|\buv\b",
    re.I,
)
WARRANTY = re.compile(
    r"(\d+)\s*(?:years?|yrs?)\.?\s*(?:of\s*)?(?:warranty|guarantee)|(?:warranty|guarantee)\s*(?:of|for|period)?\s*(?:of\s*)?(\d+)\s*(?:years?|yrs?)",
    re.I,
)
MIN_WORDS = re.compile(r"min(?:imum)?\.?|at\s*least|not\s*less\s*than|@", re.I)


def text_hash(description: str, unit: str | None) -> str:
    return hashlib.sha256(f"{description}\x00{unit or ''}".encode()).hexdigest()


def _chip(kind: str, label: str, value: dict, spans: list[tuple[int, int]], text: str) -> dict:
    spans = sorted(s for s in spans if s)
    return {
        "kind": kind,
        "label": label,
        "value": value,
        "spans": [list(s) for s in spans],
        "words": " … ".join(text[s:e] for s, e in spans)[:200],
        "source": "rule",
        "confirmed": True,
    }


def _n(v: Decimal | None) -> str:
    return "" if v is None else f"{v.normalize():f}"


def known_brands(db: Session | None) -> list[str]:
    """Every brand the app knows: the product master's, the work items' options, the data sheets'."""
    names = {b for b, _p in extract.BRANDS}
    if db is not None:
        from app.masters.models import Product, SystemOption  # noqa: PLC0415
        from app.spec.models import TdsDoc  # noqa: PLC0415

        for col in (Product.brand, SystemOption.brand, TdsDoc.brand):
            names |= {b for b in db.scalars(select(col).distinct()) if b}
    return sorted(names, key=len, reverse=True)


def _brand_pattern(brand: str) -> str | None:
    """The words a brand is named by in a line; None for a name that is an ordinary word ("Standard",
    "Approved"): a line saying "of standard make" names no brand."""
    known = dict(extract.BRANDS)
    if brand in known:
        return known[brand]
    first = re.split(r"[\s/.()]+", brand.strip())[0]
    if len(first) < 3 or first.lower() in NOT_BRANDS:
        return None
    return rf"\b{re.escape(first)}\b"


# where a line names its area and system first: "TANK WATERPROOFING : ...", "Water Proofing
# Treatment on Terrace Area ..."
HEAD = 140
# areas that are a location's word as often as the area itself: used only when nothing else is said
WEAK_AREAS = {"floor", "crack", "pipe_outlet", "expansion_joint", "construction_joint"}
EXTRA_AREAS = [
    ("oht", r"\b(?:water\s*)?tanks?\b"),
    ("expansion_joint", r"expansion\s*j(?:oin)?t\.?"),
    ("construction_joint", r"construction\s*j(?:oin)?t\.?|cold\s*joint"),
]


def pick_area(text: str, unit: str) -> tuple[str | None, tuple[int, int] | None]:
    """The line's area: a line per nos about pipes and outlets is that; a line per rmt about a
    joint is that joint; else the area named first (the knowledge library's areas and the data
    sheet uses), a weak one (floor, crack, outlet, joint) only when nothing else is named."""
    found: dict[str, tuple[int, int]] = {}
    pats = (
        [(k, p) for k, _l, p in extract.AREA_TYPES] + [(k, p) for k, p in vocab.USES] + EXTRA_AREAS
    )
    for key, pat in pats:
        m = re.search(pat, text, re.I)
        if m and (key not in found or m.start() < found[key][0]):
            found[key] = m.span()
    if unit in ("nos", "no", "each") and "pipe_outlet" in found:
        return "pipe_outlet", found["pipe_outlet"]
    if unit in ("rmt", "rft", "m"):
        joints = [k for k in ("expansion_joint", "construction_joint") if k in found]
        if joints:
            k = min(joints, key=lambda j: found[j][0])
            return k, found[k]
    strong = {k: s for k, s in found.items() if k not in WEAK_AREAS}
    pool = strong or {k: s for k, s in found.items() if k != "floor"} or found
    if not pool:
        return None, None
    k = min(pool, key=lambda j: pool[j][0])
    return k, pool[k]


def system_label(t: str, text: str) -> tuple[str, list[str]]:
    variant = []
    if ONE_K.search(text):
        variant.append("1K")
    elif TWO_K.search(text):
        variant.append("2K")
    low = text.lower()
    if "flashing" in low:
        variant.append("flashing")
    elif re.search(r"liquid", low) and re.search(r"membrane|coating", low):
        variant.append("liquid membrane")
    elif re.search(r"membrane", low) and "membrane" not in vocab.TYPE_LABEL[t]:
        variant.append("membrane")
    if re.search(STEP_WORDS["mesh"], low):
        variant.append("with mesh")
    return " ".join([vocab.TYPE_LABEL[t].split(" / ")[0], *variant]), variant


def parse(
    text: str, unit: str | None = None, qty: Decimal | None = None, brands: list[str] | None = None
) -> list[dict]:
    """The key points of one line's description (and its unit and qty)."""
    text = text or ""
    low = text.lower()
    chips: list[dict] = []
    u = (unit or "").lower()

    area, aspan = pick_area(text, u)
    if area:
        use = vocab.AREA_TO_USE.get(area, area) or area
        chips.append(
            _chip(
                "area", vocab.USE_LABEL.get(area, area), {"area": area, "use": use}, [aspan], text
            )
        )

    # system type: the type the line names first and most (its head weighs more), never a layer
    t = vocab.main_type(text, head=HEAD)
    tspan = None
    if t:
        m = re.search(dict((k, p) for k, _l, p in vocab.TYPES)[t], text, re.I)
        tspan = m.span() if m else None
        label, variant = system_label(t, text)
        spans = [tspan] + [
            x.span()
            for x in (
                ONE_K.search(text),
                TWO_K.search(text),
                re.search(r"flashing|liquid", text, re.I),
            )
            if x
        ]
        chips.append(_chip("system", label, {"type": t, "variant": variant}, spans, text))

    # coats
    coats = None
    m = tds.COATS.search(text)
    if m:
        w = m.group(1).lower()
        coats = tds.WORD_N.get(w) or int(w)
        chips.append(_chip("coats", f"{coats} coats", {"coats": coats}, [m.span()], text))

    # steps in order
    found = {}
    for kind, pat in STEP_WORDS.items():
        m = re.search(pat, text, re.I)
        if m:
            found[kind] = m.span()
    if area == "pipe_outlet":
        found.pop("pipe", None)
    if (
        "protection" in found
        and re.search(r"(?:over|on\s*top\s*of|below|under)\s*(?:the\s*)?(?:existing\s*)?til", low)
        and not re.search(r"protect", low)
    ):
        found.pop("protection")  # "over the existing tiles": the surface, not a protection
    steps: list[dict] = []
    short = vocab.TYPE_LABEL[t].split(" / ")[0].split(" ")[0] if t else "coating"
    n = coats or (1 if t else 0)
    for kind in STEP_ORDER:
        if kind == "coat":
            for i in range(1, n + 1):
                steps.append(
                    {"step": "coat", "label": f"{short} coat {i}" if n > 1 else f"{short} coat"}
                )
                if i == 1 and "mesh" in found and n > 1:
                    steps.append({"step": "mesh", "label": "mesh"})
            continue
        if kind == "mesh":
            if "mesh" in found and n <= 1:
                steps.append({"step": "mesh", "label": "mesh"})
            continue
        if kind in found:
            steps.append({"step": kind, "label": STEP_LABEL[kind]})
    if steps:
        chips.append(
            _chip(
                "steps",
                " → ".join(s["label"] for s in steps),
                {"steps": steps},
                list(found.values()),
                text,
            )
        )

    # DFT, thickness, kg per sqm
    m = tds.DFT.search(text)
    if m:
        f = tds._single("dft", m)
        chips.append(
            _chip(
                "dft",
                f"DFT {_n(f.lo)}{'–' + _n(f.hi) if f.hi != f.lo else ''} mm",
                {"lo": str(f.lo), "hi": str(f.hi)},
                [m.span()],
                text,
            )
        )
    else:
        # the first thickness the line gives ("1.2mm thick HDPE ..., overlaps of 0.8 mm thickness")
        hits = [
            x
            for x in (
                tds.THICK.search(text),
                re.search(r"(\d+(?:\.\d+)?)\s*(mm)\s*thick", text, re.I),
            )
            if x
        ]
        m = min(hits, key=lambda x: x.start()) if hits else None
        if m and not PROTECT_MM.match(text, m.start()):
            g = m.groups()
            lo, hi = tds._rng(g[0], g[1] if len(g) > 2 else None)
            chips.append(
                _chip(
                    "thickness",
                    f"thickness {_n(lo)}{'–' + _n(hi) if hi != lo else ''} mm",
                    {"lo": str(lo), "hi": str(hi)},
                    [m.span()],
                    text,
                )
            )
    for m in tds.PER_AREA.finditer(text):
        if re.search(
            r"primer|priming|bond\s*coat|bonding", text[max(0, m.start() - 60) : m.start()], re.I
        ):
            continue  # the primer's coverage, not the system's minimum
        lo, hi = tds._rng(m.group(1), m.group(2))
        v, amt = tds._amount(lo, m.group(3))
        f = vocab.SQFT_PER_SQM if tds._is_sqft(m.group(4)) else D(1)
        v = v * f
        before = text[max(0, m.start() - 25) : m.start()]
        chips.append(
            _chip(
                "kg_sqm",
                f"min {_n(vocab.q(v, 3))} {amt}/sqm",
                {
                    "min": str(vocab.q(v, 4)),
                    "unit": f"{amt}/sqm",
                    "said_min": bool(MIN_WORDS.search(before)),
                },
                [m.span()],
                text,
            )
        )
        break

    # mesh, upturn, protection thickness
    m = re.search(
        rf"(?:[A-Za-z]+\s+){{0,2}}(?:{STEP_WORDS['mesh']})(?:\s*(?:of\s*)?\d+\s*gsm)?", text, re.I
    )
    if m:
        chips.append(
            _chip(
                "mesh",
                " ".join(m.group(0).split())[:60],
                {"text": m.group(0).strip()},
                [m.span()],
                text,
            )
        )
    m = UPTURN.search(text)
    if m:
        v = next(x for x in m.groups() if x)
        chips.append(_chip("upturn", f"upturn {v} mm", {"mm": v}, [m.span()], text))
    m = PROTECT_MM.search(text)
    if m:
        v = m.group(1) or m.group(2)
        chips.append(_chip("protection", f"protection {v} mm", {"mm": v}, [m.span()], text))

    # property minimums with their standard
    for f in tds.properties(text):
        if f.unit == "N/5 cm":
            continue
        s = text.find(f.text[:20]) if f.text else -1
        span = (s, s + len(f.text)) if s >= 0 else None
        label = f"{vocab.PROPERTY_LABEL[f.key]} ≥ {_n(f.lo)}{' ' + f.unit if f.unit else ''}" + (
            f" ({f.standard})" if f.standard else ""
        )
        if f.key == "shore_a":
            label = f"Shore A {_n(f.lo)}" + (f" ({f.standard})" if f.standard else "")
        chips.append(
            _chip(
                "property",
                label,
                {"property": f.key, "min": str(f.lo), "unit": f.unit, "standard": f.standard},
                [span],
                text,
            )
        )

    # the make named, and whether an equivalent is allowed
    named, mspans = [], []
    for b in brands if brands is not None else known_brands(None):
        pat = _brand_pattern(b)
        mm = re.search(pat, text, re.I) if pat else None
        if mm and not any(mm.start() < e and s < mm.end() for s, e in mspans):
            named.append(b)
            mspans.append(mm.span())
    eq = EQUIVALENT.search(text)
    if named:
        label = f"make: {', '.join(named)}" + (" or equivalent" if eq else " (no equivalent named)")
        chips.append(
            _chip(
                "make",
                label,
                {"brands": named, "equivalent": bool(eq)},
                mspans + ([eq.span()] if eq else []),
                text,
            )
        )
    else:
        chips.append(
            _chip(
                "make",
                "make not named (any brand)",
                {"brands": [], "equivalent": True},
                [eq.span()] if eq else [],
                text,
            )
        )

    # potable, UV, pond test, warranty
    m = POTABLE.search(text)
    if m:
        chips.append(_chip("potable", "potable water", {"potable": True}, [m.span()], text))
    m = UV.search(text)
    if m:
        chips.append(_chip("uv", "UV / exposed", {"uv": True}, [m.span()], text))
    m = POND.search(text)
    if m:
        h = HOURS.search(text, m.start())
        d = DEPTH.search(text)
        hours = int(h.group(1)) if h and h.start() - m.end() < 120 else None
        depth = (d.group(1) or d.group(2)) if d else None
        label = (
            "pond test" + (f" {hours} h" if hours else "") + (f" at {depth} mm" if depth else "")
        )
        chips.append(
            _chip(
                "pond_test",
                label,
                {"hours": hours, "depth_mm": depth},
                [m.span(), h.span() if h and hours else None, d.span() if d else None],
                text,
            )
        )
    m = WARRANTY.search(text)
    if m:
        y = int(m.group(1) or m.group(2))
        chips.append(_chip("warranty", f"warranty {y} years", {"years": y}, [m.span()], text))
    if unit:
        chips.append(
            _chip(
                "unit",
                f"{unit}" + (f" × {_n(Decimal(qty))}" if qty is not None else ""),
                {"unit": unit, "qty": str(qty) if qty is not None else None},
                [],
                text,
            )
        )
    return chips


def asks(chips: list[dict]) -> dict:
    """What the chips ask, for ranking (a person's edits and confirmed AI chips included; an AI
    chip not confirmed yet is left out)."""
    out: dict = {"props": {}, "brands": [], "equivalent": True}
    for c in chips:
        if c.get("source") == "ai" and not c.get("confirmed"):
            continue
        v = c.get("value") or {}
        k = c["kind"]
        if k == "area":
            out["area"], out["use"] = v.get("area"), v.get("use")
        elif k == "system":
            out["type"], out["variant"] = v.get("type"), v.get("variant") or []
        elif k == "coats":
            out["coats"] = v.get("coats")
        elif k == "dft":
            out["dft"] = (dec(v.get("lo")), dec(v.get("hi")))
        elif k == "thickness":
            out["thickness"] = (dec(v.get("lo")), dec(v.get("hi")))
        elif k == "kg_sqm":
            out["kg_sqm"] = dec(v.get("min"))
        elif k == "property" and v.get("property"):
            out["props"][v["property"]] = {
                "min": dec(v.get("min")),
                "unit": v.get("unit"),
                "standard": v.get("standard"),
            }
        elif k == "make":
            out["brands"], out["equivalent"] = v.get("brands") or [], bool(v.get("equivalent"))
        elif k == "steps":
            out["steps"] = [s["step"] for s in v.get("steps", [])]
        elif k in ("potable", "uv"):
            out[k] = True
        elif k == "unit":
            out["unit"], out["qty"] = v.get("unit"), dec(v.get("qty")) if v.get("qty") else None
    return out
