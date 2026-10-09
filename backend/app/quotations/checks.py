# ruff: noqa: E501  (patterns read better unwrapped)
"""Consistency of an item's technical specification with its budgetary offer lines: warnings,
never blocks. Products named (bold, in capitals) on one side and not the other; a different gsm,
coat count or consumption (kg per m2) between the two.

The bungalow sample shows why: the terrace spec says 45 gsm mesh and 2 coats while its offer
line says 40 gsm and 3 coats; the garden primer covers 5-6 sqm per kg in the spec (0.17-0.20
kg/m2) but the offer line says 0.25 kg/m2.
"""

import re
from decimal import Decimal

BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
# a product name: two or more words in capitals ("BRONCO CEMREPAIR PMC", "BRONCO CEMGROUT 60")
PRODUCT = re.compile(
    r"\b[A-Z][A-Z®]{2,}\b(?:[ \t]+(?:[A-Z][A-Z0-9®]*\b|\d+\b(?![ \t]*(?:mm|kg|gsm|ply)\b)|\([A-Z]+\)))+"
)
NOT_PRODUCT = {"GSM", "RCC", "PCC", "IPS", "MM", "SQ", "FT", "MT"}
GSM = re.compile(r"(\d+(?:\.\d+)?)\s*gsm\b", re.I)
WORDS = {"one": 1, "single": 1, "two": 2, "three": 3, "four": 4}
COATS = re.compile(
    r"\b(\d+|one|single|two|three|four)\s+coats?\b|\b(\d)(?:st|nd|rd|th)\b[^.;]{0,30}?\bcoat", re.I
)
KG_M2 = re.compile(r"(\d+(?:\.\d+)?)\s*kg\s*(?:/|per)\s*(?:m2|m²|sqm|sq\.?\s*m(?:tr)?\.?)", re.I)
COVERAGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[-–]|to)\s*(\d+(?:\.\d+)?)\s*sq\.?\s*m(?:tr|eter|etre)?s?\.?\s*per\s*kg",
    re.I,
)
OVERALL = re.compile(r"consumption of material is\s*(\d+(?:\.\d+)?)\s*kg", re.I)


def products(text: str) -> set[str]:
    out = set()
    # bold runs split only by a space are one name ("**BRONCO CEMCRYSTAL** **PLUS**")
    joined = re.sub(r"\*\*(\s+)\*\*", r"\1", text or "")
    for seg in BOLD.findall(joined):
        for part in seg.split("/"):
            for m in PRODUCT.findall(part):
                name = re.sub(r"\s+", " ", m.replace("®", "")).strip()
                if len(name.split()) >= 2 and name.split()[0] not in NOT_PRODUCT:
                    out.add(name)
    return out


def gsm(text: str) -> set[Decimal]:
    return {Decimal(x) for x in GSM.findall(text or "")}


def coats(text: str) -> int | None:
    best = None
    for word, ordinal in COATS.findall(text or ""):
        n = int(ordinal) if ordinal else (int(word) if word.isdigit() else WORDS.get(word.lower()))
        if n and n < 10:
            best = max(best or 0, n)
    return best


def consumption(text: str) -> list[tuple[Decimal, Decimal]]:
    """kg per m2 figures as (low, high) ranges: "1.5 kg / m2", "coverage of 5 - 6 sq. mtr. per
    Kg" (0.17 - 0.20), "overall consumption of material is 1.5 kg"."""
    text = text or ""
    out = [(Decimal(x), Decimal(x)) for x in KG_M2.findall(text)]
    out += [(Decimal(x), Decimal(x)) for x in OVERALL.findall(text)]
    for a, b in COVERAGE.findall(text):
        lo, hi = sorted((Decimal(a), Decimal(b)))
        out.append(((1 / hi).quantize(Decimal("0.01")), (1 / lo).quantize(Decimal("0.01"))))
    return out


def _matches(r: tuple[Decimal, Decimal], others: list[tuple[Decimal, Decimal]]) -> bool:
    lo, hi = r
    return any(lo * Decimal("0.9") <= ohi and olo <= hi * Decimal("1.1") for olo, ohi in others)


def _fmt(r: tuple[Decimal, Decimal]) -> str:
    lo, hi = r
    return f"{lo.normalize():f}" if lo == hi else f"{lo.normalize():f}–{hi.normalize():f}"


def spec_text(specs: list[dict]) -> str:
    return "\n".join(
        st.get("text", "")
        for s in specs
        for sec in s.get("sections") or []
        for st in sec.get("steps") or []
    )


def check(specs: list[dict], lines: list[str]) -> list[str]:
    """Warnings for one item: its specs (the JSON copies) against its offer line texts."""
    spec = spec_text(specs)
    offer = "\n".join(lines)
    if not spec.strip() or not offer.strip():
        return []
    warn = []
    sp, op = products(spec), products(offer)
    for p in sorted(op - sp):
        warn.append(f"{p} is in the budgetary offer but not in the specification")
    for p in sorted(sp - op):
        warn.append(f"{p} is in the specification but not in the budgetary offer")
    sg, og = gsm(spec), gsm(offer)
    if sg and og and sg != og:
        only_s, only_o = sorted(sg - og), sorted(og - sg)
        if only_s or only_o:
            warn.append(
                "Different gsm: specification "
                + ", ".join(f"{g.normalize():f}" for g in sorted(sg))
                + " gsm, budgetary offer "
                + ", ".join(f"{g.normalize():f}" for g in sorted(og))
                + " gsm"
            )
    sc, oc = coats(spec), coats(offer)
    if sc and oc and sc != oc:
        warn.append(f"Different coat count: specification {sc} coats, budgetary offer {oc} coats")
    skg, okg = consumption(spec), consumption(offer)
    if skg and okg:
        odd_o = [r for r in okg if not _matches(r, skg)]
        odd_s = [r for r in skg if not _matches(r, okg)]
        if odd_o or odd_s:
            warn.append(
                "Different consumption: specification "
                + ", ".join(_fmt(r) for r in skg)
                + " kg/m2, budgetary offer "
                + ", ".join(_fmt(r) for r in okg)
                + " kg/m2"
            )
    return warn


def quotation_checks(q) -> dict[int, list[str]]:
    """{quotation item id: warnings} over the offered specs and lines."""
    from app.quotations import (
        service as svc,  # noqa: PLC0415  (service imports this module's callers)
    )

    out = {}
    for item in q.items:
        specs = [s for s in item.specs if svc.is_offered(item, s.get("option_label"))]
        lines = [ln.description for ln in item.lines if svc.is_offered(item, ln.option)]
        w = check(specs, lines)
        if w:
            out[item.id] = w
    return out


def library_item_checks(item) -> list[str]:
    specs = [{"sections": s.spec.sections or []} for s in item.specs]
    return check(specs, [ln.line.description for ln in item.lines])
