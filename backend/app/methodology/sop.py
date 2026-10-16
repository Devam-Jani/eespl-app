# ruff: noqa: E501  (patterns read better unwrapped)
"""Importing a client's waterproofing standard from its SOP PDFs and summary sheet (Godrej: 24
SOPs in two formats and 1_Waterproofing.xlsx). One rule per element and condition, each linked to
the SOP number, revision and page it came from.

Old format (GPL-WP-RAFT-001 Rev 0, 2020): a header table (SOP No., Rev No., Date), "Element :",
"Condition:" (numbered), "Options Evaluated" (Recommended Yes/No with the reason), "Recommended
System for all regions:", "Proposed Recommended Makes" (vendors by system; "approved as per
TPT" / "not approved" in the cell), the method statement, material specification tables
(property, standard, expected value), the sampling plan, a Yes/No checklist per stage, the BOQ
description and the mode of measurement.

New format (GPL-QUALITY-SOP-WATERPROOFING-006 I01 R00, 2025-26): "1.1 Approved System" with one
"1.1.n <condition>" per case (Small Toilet less than 4.5 m2 ...), performance criteria tables,
delivery and storage, tools, manpower, the procedure (8.x, where the pond tests are), EHS and
QA/QC. The checklist and hold points come from the procedure's headings.

A rule is "to check" when something needed was not read (element, system, condition) or the
summary sheet names another system. Two values for one thing in a document (elongation 150 % in
the approved system, 120 % in the table) are kept as contradictions for the pre-bid sheet."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.methodology import vocab
from app.methodology.models import (
    ClientStandard,
    StandardContradiction,
    StandardDocument,
    StandardRule,
)

VENDORS = {"BASF": "BASF", "FOSROC": "Fosroc", "PIDILITE": "Pidilite", "ARDEX": "Ardex", "ASIAN PAINTS": "Asian Paints",
           "SIKA": "Sika", "CHOWGULE": "Chowgule", "MAPEI": "Mapei", "BRONCO": "Bronco", "CHRYSO": "Chryso"}  # fmt: skip
OLD_SOP = re.compile(r"SOP\s*No\.?\s*:\s*(GPL[-\w\s]*?)\s*(?:STANDARD|Rev|$)", re.I)
NEW_SOP = re.compile(
    r"([A-Z]{2,6}\s*-\s*QUALITY\s*-\s*SOP\s*-\s*[A-Z]+\s*-\s*0\s*\d+\s*\d*)\s*\|\s*Issue\s*(\d+)\s*\(([^)]+)\)\s*\|\s*Rev\s*(\d+)",
    re.I,
)


@dataclass
class Page:
    n: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    aboves: list[str] = field(default_factory=list)  # the line just above each table (its material)


@dataclass
class RuleIn:
    element: str | None
    element_label: str
    condition_label: str | None
    condition: dict
    system_text: str
    page: int | None
    confidence: str = "high"
    notes: list[str] = field(default_factory=list)


@dataclass
class Read:
    file_name: str
    fmt: str
    sop_no: str | None
    revision: str | None
    issue_date: str | None
    title: str | None
    pages: int
    element: str | None
    rules: list[RuleIn]
    makes: list[dict]
    specs: list[dict]
    tests: list[dict]
    hold_points: list[dict]
    checklist: list[dict]
    options: list[dict]
    guarantee_years: int | None
    boq_wording: str | None
    measurement: str | None
    contradictions: list[dict]


def read_pages(path: Path) -> list[Page]:
    import pdfplumber

    out = []
    with pdfplumber.open(str(path)) as pdf:
        for i, p in enumerate(pdf.pages, 1):
            tables, aboves = [], []
            try:
                for t in p.find_tables():
                    tables.append([[vocab.clean(c) for c in row] for row in t.extract()])
                    top = t.bbox[1]
                    above = (
                        p.crop((0, max(0, top - 40), p.width, top)).extract_text()
                        if top > 2
                        else ""
                    )
                    lines = [vocab.clean(x) for x in (above or "").splitlines() if vocab.clean(x)]
                    aboves.append(lines[-1] if lines else "")
            except Exception:  # noqa: BLE001  (a page whose tables do not read: its text still does)
                tables, aboves = [], []
            out.append(Page(i, p.extract_text() or "", tables, aboves))
    return out


def _find(pages: list[Page], pat: str, flags=re.I | re.S) -> tuple[re.Match | None, int | None]:
    rx = re.compile(pat, flags)
    for p in pages:
        m = rx.search(p.text)
        if m:
            return m, p.n
    return None, None


def _until(text: str, start: int, stops: str) -> str:
    rest = text[start:]
    m = re.search(stops, rest, re.I)
    return vocab.clean(rest[: m.start()] if m else rest)


# --- conditions ---------------------------------------------------------------------------------


def condition_of(label: str, context: str = "") -> dict:
    """What a condition says, as values a BOQ item can be checked against."""
    t = f"{label} {context}".lower()
    own = (label or "").lower()
    c: dict[str, Any] = {}
    m = re.search(
        r"(less|lower|smaller|more|greater|bigger|larger)\s*than\s*(\d+(?:\.\d+)?)\s*(?:m2|m²|sq\.?\s*m)",
        own,
    ) or re.search(r"([<>])\s*(\d+(?:\.\d+)?)\s*(?:m2|m²|sq\.?\s*m)", own)
    if m:
        lo = m.group(1) in ("less", "lower", "smaller", "<")
        c["area_sqm"] = {"lt": float(m.group(2))} if lo else {"gte": float(m.group(2))}
    if re.search(r"open\s*to\s*sky", own):
        c["exposure"] = "open"
    elif re.search(r"\bcovered\b", own):
        c["exposure"] = "covered"
    if re.search(r"\bunconfined\b", own):
        c["confined"] = False
    elif re.search(r"\bconfined\b", own):
        c["confined"] = True
    if re.search(
        r"water\s*table\s*(?:is\s*)?above|with\s*(?:the\s*)?water\s*-?\s*table", t
    ) and not re.search(r"below\s*and\s*above|above\s*and\s*below|with\s*and\s*without", t):
        c["water_table"] = "above"
    elif re.search(
        r"without\s*(?:the\s*)?water\s*-?\s*table|water\s*table\s*below", t
    ) and not re.search(r"below\s*and\s*above|with\s*and\s*without", t):
        c["water_table"] = "below"
    if re.search(r"underslung", t):
        c["toilet_kind"] = "underslung"
    elif re.search(r"\bsunken\b|\bsunk\b", t) and "toilet" in t:
        c["toilet_kind"] = "sunken"
    if re.search(r"corrosive", t):
        c["corrosive"] = True
    if re.search(r"outer\s*face|positive\s*side", label.lower()):
        c["face"] = "outer"
    elif re.search(r"negative\s*side|internal\s*side|inner\s*face|inside", label.lower()):
        c["face"] = "inner"
    m = re.search(r"(base\s*slab|side\s*wall)", label.lower())
    if m:
        c["part"] = m.group(1)
    for loc in ("basement", "podium"):
        if re.search(loc, context.lower()) and "swimming" in t:
            c["location"] = loc
    return c


def _conditions_old(pages: list[Page]) -> list[tuple[str, int]]:
    out = []
    for p in pages[:3]:
        for m in re.finditer(
            r"Condition\s*:\s*(.+?)(?=•\s*Options|\n\s*•|Options\s*Evaluated|Recommended|$)",
            p.text,
            re.I | re.S,
        ):
            block = m.group(1)
            parts = re.split(r"(?:^|\s)(\d{1,2})\s*\.\s+", " " + block.replace("\n", " "))
            if len(parts) > 2:
                for i in range(1, len(parts) - 1, 2):
                    label = vocab.clean(parts[i + 1]).strip(" .")
                    if label:
                        out.append((label, p.n))
            elif vocab.clean(block):
                out.append((vocab.clean(block).strip(" ."), p.n))
    seen, uniq = set(), []
    for label, n in out:
        if label.lower() not in seen:
            seen.add(label.lower())
            uniq.append((label, n))
    return uniq


# --- tables -------------------------------------------------------------------------------------


def makes_from(pages: list[Page]) -> list[dict]:
    """Proposed recommended makes: per system row, per vendor, the product and its status."""
    out = []
    for p in pages:
        for t in p.tables:
            head_i = next(
                (i for i, r in enumerate(t) if sum(1 for c in r if c.upper() in VENDORS) >= 3), None
            )
            if head_i is None:
                continue
            vendors = [VENDORS.get(c.upper()) for c in t[head_i]]
            for r in t[head_i + 1 :]:
                system = vocab.clean(re.sub(r"^\d+\.\s*", "", r[0] or ""))
                for v, cell in zip(vendors, r, strict=False):
                    if not v or not cell:
                        continue
                    low = cell.lower()
                    if "not approved" in low or (
                        "doesn" in low and "approved" in low and "tpt" not in low
                    ):
                        status = "not_approved"
                    elif "tpt" in low:
                        status = "tpt"
                    else:
                        status = "approved"
                    product = vocab.clean(re.sub(r"\(.*", "", cell)) or cell
                    note = vocab.clean(m.group(0)) if (m := re.search(r"\(.*\)?", cell)) else None
                    out.append(
                        {
                            "system": system,
                            "brand": v,
                            "product": product,
                            "status": status,
                            "note": note,
                            "page": p.n,
                        }
                    )
    return out


def options_from(pages: list[Page]) -> list[dict]:
    out = []
    for p in pages[:4]:
        for t in p.tables:
            rec = next((r for r in t if r and r[0].lower().startswith("recommended")), None)
            why = next((r for r in t if r and r[0].lower().startswith("reason")), None)
            if rec is None or why is None:
                continue
            head = t[0]
            for i in range(1, len(head)):
                if head[i]:
                    out.append(
                        {
                            "option": head[i],
                            "recommended": (rec[i] if i < len(rec) else "").lower().startswith("y"),
                            "reason": why[i] if i < len(why) else "",
                            "page": p.n,
                        }
                    )
    return out


def _caption_materials(text: str) -> list[str]:
    return [
        vocab.clean(m.group(1))
        for m in re.finditer(r"Table\s*\d+\s*:\s*Performance\s*Criteria\s*for\s*(.+)", text, re.I)
    ]


def specs_from(pages: list[Page]) -> list[dict]:
    """Minimum specifications from the tables: rows (property, standard, expected) or the
    transposed kind (Parameter / Reference standard / Minimum acceptable value)."""
    out = []
    for p in pages:
        captions = _caption_materials(p.text)
        k = 0
        for ti, t in enumerate(p.tables):
            if not t or len(t[0]) < 2:
                continue
            if any(r and r[0].lower().startswith(("recommended", "reason")) for r in t):
                continue  # the options evaluated
            above = p.aboves[ti] if ti < len(p.aboves) else ""
            above_material = (
                above
                if vocab.system_type_of(above) and not vocab.standard_of(above) and len(above) < 90
                else None
            )
            first = [r[0].lower() if r else "" for r in t]
            pi = next((i for i, x in enumerate(first) if x.startswith("parameter")), None)
            if pi is not None and pi != 0:
                pi = None
            vi = next(
                (i for i, x in enumerate(first) if re.search(r"minimum|acceptable|expected", x)),
                None,
            )
            si = next((i for i, x in enumerate(first) if "standard" in x), None)
            if pi is not None and vi is not None:
                material = captions[k] if k < len(captions) else above_material
                k += 1
                for j in range(1, len(t[pi])):
                    prop = vocab.property_of(t[pi][j])
                    req = t[vi][j] if j < len(t[vi]) else ""
                    if prop and req:
                        lim = vocab.limit_of(req, prop)
                        out.append(
                            _spec(
                                prop,
                                t[pi][j],
                                t[si][j] if si is not None and j < len(t[si]) else None,
                                req,
                                lim,
                                p.n,
                                material,
                                f"p{p.n} t{ti}",
                            )
                        )
                continue
            header = " ".join(t[0]).lower()
            if not re.search(r"expected|minimum|acceptable|proposed", header):
                continue  # a sample test certificate, the BOQ table ...
            material = above_material
            if "material" in header or "locations" in header:
                material = captions[k] if k < len(captions) else material
                k += 1
            for r in t[1:]:
                cell_material = _material_col(r)
                if cell_material:
                    material = cell_material
                cells = [c for c in r if c]
                if len(cells) < 2:
                    continue
                prop_cell = next(
                    (
                        c
                        for c in cells
                        if vocab.property_of(c)
                        and not vocab.standard_of(c)
                        and not re.match(r"^\s*(min|max|>|<|\d)", c, re.I)
                    ),
                    None,
                )
                if not prop_cell:
                    continue
                prop = vocab.property_of(prop_cell)
                std = next((vocab.standard_of(c) for c in cells if vocab.standard_of(c)), None)
                req = next(
                    (
                        c
                        for c in cells
                        if c is not prop_cell
                        and not vocab.standard_of(c)
                        and vocab.limit_of(c, prop)
                    ),
                    None,
                )
                if prop and req and prop not in ("pot_life", "coverage"):
                    if any(
                        material and s["property"] == prop and s.get("material") == material
                        for s in out
                    ):
                        continue
                    out.append(
                        _spec(
                            prop,
                            prop_cell,
                            std,
                            req,
                            vocab.limit_of(req, prop),
                            p.n,
                            material,
                            f"p{p.n} t{ti}",
                        )
                    )
    # one per property, standard and value (the receipt table repeats the specification table)
    seen, uniq = set(), []
    for s in out:
        key = (s["property"], s.get("num"), s.get("material"))
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


def _material_col(row: list[str]) -> str | None:
    for c in row:
        if c and vocab.system_type_of(c) and not vocab.property_of(c):
            return c
    return None


def _spec(prop, label, std, req, lim, page, material, source=None) -> dict:
    return {"source": source, "property": prop, "label": vocab.PROPERTY_LABEL.get(prop, label), "standard": std, "required": vocab.clean(req),
            "op": lim.op if lim else None, "num": lim.num if lim else None, "hi": lim.hi if lim else None, "unit": lim.unit if lim else "",
            "page": page, "material": material, "system_type": vocab.system_type_of(material or "")}  # fmt: skip


# --- tests, checklist, hold points ----------------------------------------------------------------


def tests_from(pages: list[Page]) -> list[dict]:
    out = []
    for p in pages:
        sentences = re.split(r"(?<=[.?])\s+|\n\s*•", p.text.replace("\n", " \n"))
        for s in sentences:
            s1 = vocab.clean(s)
            if (
                not re.search(r"pond|flood|fill\s*the\s*tank|leak\s*test", s1, re.I)
                or len(s1) > 260
            ):
                continue
            h = vocab.hours_in(s1)
            if not h or s1.endswith("?"):
                continue
            if re.search(r"pre[\s-]*pond", s1, re.I):
                kind = "pre_pond"
            elif re.search(r"fill\s*the\s*tank|tank\s*completely", s1, re.I):
                kind = "fill"
            else:
                kind = "pond"
            depth = re.search(r"(\d+)\s*mm\s*of\s*water", s1, re.I)
            out.append(
                {
                    "kind": kind,
                    "hours": h,
                    "depth_mm": int(depth.group(1)) if depth else None,
                    "text": s1,
                    "page": p.n,
                }
            )
        m = re.search(r"Sampling\s*Frequency\s*(.+?)(?:Mode\s*of\s*testing|$)", p.text, re.I | re.S)
        if m:
            out.append(
                {
                    "kind": "sampling",
                    "hours": None,
                    "text": vocab.clean(m.group(1))[:300],
                    "page": p.n,
                }
            )
    seen, uniq = set(), []
    for t in out:
        k = (t["kind"], t["hours"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def checklist_old(pages: list[Page]) -> list[dict]:
    start = next((i for i, p in enumerate(pages) if re.search(r"Check\s*List", p.text, re.I)), None)
    if start is None:
        return []
    stages: list[dict] = []
    buf = ""
    for p in pages[start:]:
        text = p.text
        if p is pages[start]:
            text = text[re.search(r"Check\s*List", text, re.I).end() :]
        if re.search(r"BOQ\s*Description", text, re.I):
            text = text[: re.search(r"BOQ\s*Description", text, re.I).start()]
        for line in text.splitlines():
            ln = vocab.clean(line)
            if (
                not ln
                or re.match(
                    r"^(GODREJ|STANDARD OPERATING|\d+\s*\|\s*Page|Description\s*Yes|SOP No|Rev No|Date:)",
                    ln,
                    re.I,
                )
                or ln.isupper()
            ):
                continue
            m = re.match(r"^(\d)\.\s+(.+)$", ln)
            if m and not ln.endswith("?") and len(ln) < 70:
                stages.append({"stage": m.group(2).strip(), "items": [], "page": p.n})
                buf = ""
                continue
            if not stages:
                continue
            buf = f"{buf} {ln}".strip()
            if "?" in buf:
                stages[-1]["items"].append(buf[: buf.rfind("?") + 1])
                buf = ""
    return [s for s in stages if s["items"]]


def procedure_new(pages: list[Page]) -> list[tuple[str, str, int]]:
    """The procedure's numbered headings (8.1 Surface Preparation, 8.2 1st Post-Ponding Water Test)."""
    out = []
    started = False
    for p in pages:
        for line in p.text.splitlines():
            ln = vocab.clean(line)
            m = re.match(r"^(8(?:\.\d+){1,2})\s+([A-Z1-9][^.]{3,90})$", ln)
            if ln.startswith("8. Procedure") and not re.search(r"\.{4}", ln):
                started = True
            if started and m and not re.search(r"\.{4}", ln):
                out.append((m.group(1), m.group(2).strip(), p.n))
            if started and re.match(r"^9\.\s+Environment", ln):
                return out
    return out


def checklist_new(heads: list[tuple[str, str, int]]) -> list[dict]:
    out: dict[str, dict] = {}
    for num, title, page in heads:
        top = ".".join(num.split(".")[:2])
        if num == top:
            out[top] = {"stage": f"{num} {title}", "items": [], "page": page, "derived": True}
        elif top in out:
            out[top]["items"].append(f"{title}: done as per SOP §{num} and inspected?")
    for v in out.values():
        if not v["items"]:
            v["items"].append(
                f"{v['stage'].split(' ', 1)[1]}: done as per SOP §{v['stage'].split(' ')[0]} and inspected?"
            )
    return list(out.values())


def hold_points_from(
    checklist: list[dict], tests: list[dict], heads: list[tuple[str, str, int]]
) -> list[dict]:
    out = []
    for a, b in zip(checklist, checklist[1:], strict=False):
        out.append(
            {
                "stage": a["stage"],
                "text": f"{a['stage']} checklist signed before {b['stage'].lower()}",
                "page": a.get("page"),
            }
        )
    for num, title, page in heads:
        if re.search(r"pond|mock|inspection|test", title, re.I):
            out.append(
                {
                    "stage": f"{num} {title}",
                    "text": f"{title} passed and recorded before the next stage (SOP §{num})",
                    "page": page,
                }
            )
    for t in tests:
        if t["kind"] in ("pond", "pre_pond", "fill") and not heads:
            label = {"pre_pond": "Pre-pond test", "pond": "Pond test", "fill": "Fill test"}[
                t["kind"]
            ]
            out.append(
                {
                    "stage": label,
                    "text": f"{label} for {t['hours']} h passed before the next stage",
                    "page": t["page"],
                }
            )
    return out


# --- contradictions -----------------------------------------------------------------------------


FAMILY = {"cementitious": "acrylic_cementitious"}


def contradictions_from(
    pages: list[Page], specs: list[dict], system_specs: list[dict], element: str | None
) -> list[dict]:
    out = []
    # the same property for the same material with two required values
    by: dict[tuple, list[dict]] = defaultdict(list)
    for s in specs + system_specs:
        if s.get("num") is None or not s.get("system_type") or s.get("op") not in ("min", "eq"):
            continue
        by[(s["property"], FAMILY.get(s["system_type"], s["system_type"]))].append(s)
    for (prop, mat), rows in by.items():
        nums = {r["num"] for r in rows}
        sources = {r.get("source") or r.get("where") for r in rows}
        if len(nums) > 1 and len(sources) > 1:
            label = vocab.PROPERTY_LABEL.get(prop, prop)
            out.append({"topic": f"{label}{' of the ' + vocab.SYSTEM_LABEL.get(mat, mat).lower() if mat != 'any' else ''}",
                        "values": [{"value": r["required"], "page": r["page"], "text": r.get("where") or f"{r.get('material') or 'specification table'}"} for r in rows]})  # fmt: skip
    # termination height on the wall, DFT in microns, overlap between sheets
    pats = [
        (
            "Termination of the PU coat on the wall",
            r"(?:pu|polyurethane)[^.]{0,80}?terminate\s*on\s*the\s*wall\s*at\s*(\d+)\s*mm|coat\s*will\s*terminate\s*on\s*the\s*wall\s*at\s*(\d+)\s*mm",
            "mm",
        ),
        (
            "Dry film thickness of the coal tar epoxy",
            r"dry\s*film\s*thickness\s*(?:of\s*)?(\d+)\s*micron|average\s*dry\s*film\s*thickness\s*(\d+)\s*micron|min\.?\s*(\d+)\s*microns",
            "µ",
        ),
        (
            "Overlap of the membrane",
            r"overlap\s*of\s*(\d+\s*-?\s*\d*)\s*mm\s*between|overlap\s*between[^.]{0,60}?minimum\s*(\d+)\s*mm",
            "mm",
        ),
    ]
    for topic, pat, unit in pats:
        found = []
        for p in pages:
            flat = vocab.clean(p.text)
            for m in re.finditer(pat, flat, re.I):
                v = next(g for g in m.groups() if g)
                v = re.sub(r"\s+", "", v)
                if topic.startswith("Dry film") and (
                    not re.search(
                        r"coal\s*tar|epoxy", flat[max(0, m.start() - 300) : m.end() + 200], re.I
                    )
                    or re.search(
                        r"primer",
                        re.split(r"[.?]", flat[max(0, m.start() - 300) : m.start()])[-1],
                        re.I,
                    )
                ):
                    continue
                if topic.startswith("Termination") and not re.search(
                    r"polyurethane|\bpu\b", flat[max(0, m.start() - 250) : m.end()], re.I
                ):
                    continue
                found.append(
                    {
                        "value": f"{v} {unit}",
                        "page": p.n,
                        "text": flat[max(0, m.start() - 60) : m.end() + 40],
                    }
                )
        if len({f["value"] for f in found}) > 1:
            out.append({"topic": topic, "values": found})
    return out


# --- one document ---------------------------------------------------------------------------------


def read_sop(path: Path) -> Read:
    pages = read_pages(path)
    first = pages[0].text if pages else ""
    all_text = "\n".join(p.text for p in pages)
    m_new = NEW_SOP.search(all_text[:6000])
    if m_new:
        fmt = "new"
        sop_no = re.sub(r"\s+", "", m_new.group(1))
        sop_no = re.sub(r"-0(\d)(\d)$", r"-0\1\2", sop_no)
        revision, issue_date = f"I{m_new.group(2)} R{m_new.group(4)}", m_new.group(3)
        tl = [vocab.clean(x) for x in first.splitlines() if vocab.clean(x)]
        i = next((k for k, x in enumerate(tl) if "STANDARD OPERATING PROCEDURE" in x.upper()), -1)
        title_lines = []
        for x in tl[i + 1 :]:
            if re.match(r"^[A-Z]{2,6}\s*-\s*QUALITY", x.upper()):
                break
            title_lines.append(x)
        title = vocab.clean(" ".join(title_lines)).replace(" -", " - ")
    else:
        fmt = "old"
        head = [c for t in (pages[0].tables if pages else []) for r in t for c in r if c]
        cells = " | ".join(head)
        m = re.search(r"SOP\s*No\.?\s*:\s*([^|]+)", cells, re.I) or re.search(
            r"SOP\s*No\.?\s*:\s*(\S+)", first, re.I
        )
        sop_no = re.sub(r"\s+", "", m.group(1)) if m else None
        if sop_no and sop_no.endswith("-"):  # "GPL-WP-" with the rest on the next line
            m2 = re.search(r"SOP\s*No\.?\s*:\s*GPL-WP-\s*\n?.*?\n\s*([A-Z]+-?\d+)", first, re.I)
            sop_no = sop_no + m2.group(1) if m2 else sop_no
        m = re.search(r"Rev\s*No\.?\s*:\s*(\w+)", cells + " " + first, re.I)
        revision = m.group(1) if m else None
        m = re.search(r"Date\s*:\s*([\d\-./]+)", cells + " " + first, re.I)
        issue_date = m.group(1) if m else None
        title = next(
            (
                c
                for c in head
                if re.search(r"WATERPROOFING|DETAILS|HOLES|JOINTS", c, re.I)
                and "PROCEDURE" not in c.upper()
                and "SOP" not in c.upper()
            ),
            None,
        )
        if not title:
            m = re.search(r"STANDARD OPERATING PROCEDURE.*?\n\s*(.+?)\s*Date", first, re.I | re.S)
            title = vocab.clean(m.group(1)) if m else path.stem
    stem = re.sub(r"^\d+(?:\.\d+)?_", "", path.stem)
    m_el, el_page = _find(pages[:3], r"Element\s*:\s*([^\n]*)")
    element_text = vocab.clean(m_el.group(1)) if m_el else ""
    tail = re.split(r"\s-\s|\s-(?=[A-Z])", title or "")[-1]
    element = (
        vocab.element_of(element_text)
        or vocab.element_of(tail)
        or vocab.element_of(title or "")
        or vocab.element_of(stem)
    )
    if element == "tank":
        element = vocab.element_of(stem) or element
    element_label = element_text.strip(" .") or (title or stem).title()

    rules: list[RuleIn] = []
    if fmt == "old":
        m_sys = None
        sys_text, sys_page = "", None
        for p in pages:
            for m in re.finditer(r"Recommended\s+system[^:\n]*:\s*", p.text, re.I):
                if re.search(r"Sketch|Makes", p.text[max(0, m.start() - 30) : m.start()], re.I):
                    continue
                t = _until(
                    p.text,
                    m.end(),
                    r"Sketch|Proposed\s+Recommended|Options\s+Evaluated|•\s*Element|•\s*Condition|\n\s*\n\s*\n",
                )
                if len(t) > 8:
                    m_sys, sys_text, sys_page = m, t, p.n
                    break
            if m_sys:
                break
        if not sys_text:
            rec = [o for o in options_from(pages) if o["recommended"]]
            if rec:
                sys_text, sys_page = rec[0]["option"], rec[0]["page"]
        conds = _conditions_old(pages)
        ctx = f"{stem} {title or ''}"
        if not conds:
            label = None
            for w in (
                "with watertable",
                "with water table",
                "without water table",
                "confined",
                "unconfined",
                "basement",
                "podium",
            ):
                if w in stem.lower():
                    label = stem.replace("_", " ")
                    break
            conds = [(label, el_page)] if label else [(None, el_page)]
        for label, n in conds:
            cond = condition_of(label or "", ctx)
            r = RuleIn(element, element_label, label, cond, sys_text, sys_page or n)
            if not element or not sys_text:
                r.confidence = "low"
                r.notes.append("the element or the recommended system was not read")
            elif not vocab.system_type_of(sys_text):
                r.confidence = "low"
                r.notes.append("the system type was not recognised")
            rules.append(r)
        # "on positive side ... and <system> from negative side": the inside face as its own rule
        m = re.search(r"(?:from|on)\s+(?:the\s+)?(?:negative|internal)\s+side", sys_text, re.I)
        pos = re.search(r"positive\s+side(?:\s*\([^)]*\))?\s*(?:and|,)\s*", sys_text, re.I)
        inner = sys_text[pos.end() : m.start()] if m and pos and pos.end() < m.start() else ""
        if (
            inner
            and vocab.system_type_of(inner)
            and element in ("ug_tank", "stp", "lift_pit", "swimming_pool")
        ):
            r = RuleIn(
                element,
                element_label,
                "Inner face (negative side)",
                {"face": "inner"},
                vocab.clean(inner),
                sys_page,
                "low",
                ['split from the recommended system\'s "negative side" part'],
            )
            rules.append(r)
            for x in rules[:-1]:
                x.condition.setdefault("face", "outer")
    else:
        sec = None
        for p in pages[:6]:
            m = re.search(
                r"1\.1\s+Approved\s+Systems?\s*\n(.+?)(?=\n\s*2\.\s+Responsibility|$)",
                p.text,
                re.I | re.S,
            )
            if m:
                sec = (m.group(1), p.n)
                break
        if sec:
            text, n = sec
            subs = list(re.finditer(r"1\.1\.\d+\s+(.+)", text))
            if subs:
                for i, s in enumerate(subs):
                    body = text[s.end() : subs[i + 1].start() if i + 1 < len(subs) else len(text)]
                    body = re.split(r"Note\s*:", body)[0]
                    bullets = [
                        vocab.clean(b) for b in re.split(r"\n\s*•", "\n" + body) if vocab.clean(b)
                    ]
                    system = next(
                        (b for b in bullets if not re.match(r"for\s+detailed", b, re.I)), ""
                    )
                    label = vocab.clean(s.group(1))
                    rules.append(
                        RuleIn(
                            element,
                            element_label,
                            label,
                            condition_of(label, title or ""),
                            system,
                            n,
                        )
                    )
            else:
                body = re.split(r"For\s+detailed|Note\s*:", text)[0]
                rules.append(
                    RuleIn(
                        element,
                        element_label,
                        None,
                        condition_of("", title or ""),
                        vocab.clean(body),
                        n,
                    )
                )
        if not rules:
            rules.append(
                RuleIn(
                    element,
                    element_label,
                    None,
                    {},
                    "",
                    None,
                    "low",
                    ["the approved system was not read"],
                )
            )
        for r in rules:
            if not r.system_text or not vocab.system_type_of(r.system_text):
                r.confidence = "low"
                r.notes.append("the system type was not recognised")

    makes = makes_from(pages)
    specs = specs_from(pages)
    tests = tests_from(pages)
    heads = procedure_new(pages) if fmt == "new" else []
    checklist = checklist_old(pages) if fmt == "old" else checklist_new(heads)
    hold = hold_points_from(checklist, tests, heads)
    options = options_from(pages) if fmt == "old" else []
    m = re.search(r"guarantee[^.]{0,200}?period\s*of\s*(\d+)\s*years", vocab.clean(all_text), re.I)
    guarantee = int(m.group(1)) if m else None
    boq = None
    m = re.search(
        r"BOQ\s*Description\s*:?\s*(?:Description\s*Unit)?(.+?)(?:Mode\s*of\s*measurement|$)",
        all_text,
        re.I | re.S,
    )
    if m:
        boq = vocab.clean(
            re.sub(r"GODREJ PROPERTIES LIMITED.*?\d+\s*\|\s*Page", " ", m.group(1), flags=re.S)
        )[:4000]
    m = re.search(
        r"Mode\s*of\s*measurement\s*:?\s*(.+?)(?:\n\s*\n|\bM2\b|\bRmt\b|\bNos\b|$)",
        all_text,
        re.I | re.S,
    )
    measurement = vocab.clean(m.group(1)) if m else None
    system_specs = []
    for r in rules:
        for prop, lim in vocab.specs_in(r.system_text).items():
            system_specs.append({"property": prop, "label": vocab.PROPERTY_LABEL.get(prop, prop), "standard": None, "required": lim.text(), "op": lim.op, "num": lim.num, "hi": None,
                                 "unit": lim.unit, "page": r.page, "material": r.condition_label or "approved system", "system_type": _type_near(r.system_text, prop), "where": f"approved system ({r.condition_label or 'all'})"})  # fmt: skip
    contra = contradictions_from(pages, specs, system_specs, element)
    return Read(
        path.name,
        fmt,
        sop_no,
        revision,
        issue_date,
        title,
        len(pages),
        element,
        rules,
        makes,
        specs + system_specs,
        tests,
        hold,
        checklist,
        options,
        guarantee,
        boq,
        measurement,
        contra,
    )


def _type_near(text: str, prop: str) -> str | None:
    """The system type a value in the system text belongs to ("... polyurethane on the floor and
    acrylic cementitious coating with min. 150% elongation" -> elongation: acrylic cementitious)."""
    t = vocab.clean(text)
    pats = {
        "elongation": r"elongation",
        "consumption": r"kg\s*/\s*m",
        "dft": r"dft|dry\s*film",
        "mesh_gsm": r"gsm",
        "thickness": r"thick",
    }
    m = re.search(pats.get(prop, prop), t, re.I)
    if not m:
        return vocab.system_type_of(t)
    best, best_d = None, 10**9
    for key, rx in vocab._SYSTEM_RE:
        for mm in rx.finditer(t):
            d = abs(mm.start() - m.start())
            if d < best_d:
                best, best_d = key, d
    return best


# --- the summary sheet ----------------------------------------------------------------------------


def read_xlsx(path: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        head = None
        for r in ws.iter_rows(values_only=True):
            cells = [vocab.clean(str(c)) if c is not None else "" for c in r]
            if head is None:
                if any(c.lower() == "element" for c in cells):
                    head = cells
                continue
            ei = next(i for i, c in enumerate(head) if c.lower() == "element")
            si = next((i for i, c in enumerate(head) if "system" in c.lower()), len(cells) - 1)
            if ei < len(cells) and cells[ei]:
                el = cells[ei]
                out.append(
                    {
                        "element_text": el,
                        "element": vocab.element_of(el),
                        "condition": condition_of(el, el),
                        "system": cells[si] if si < len(cells) else "",
                        "row": len(out) + 1,
                    }
                )
    return out


# --- into the database ----------------------------------------------------------------------------


def import_standard(
    db: Session,
    folder: Path,
    name: str,
    client_name: str | None = None,
    client_id: int | None = None,
    demo: bool = False,
) -> ClientStandard:
    """Read every SOP PDF and summary sheet in the folder (and below) into the standard (made or
    replaced): documents, rules, contradictions, and the import report."""
    std = db.scalar(select(ClientStandard).where(ClientStandard.name == name))
    if std is None:
        std = ClientStandard(name=name, client_name=client_name, client_id=client_id, is_demo=demo)
        db.add(std)
        db.flush()
    else:
        db.execute(delete(StandardContradiction).where(StandardContradiction.standard_id == std.id))
        db.execute(delete(StandardRule).where(StandardRule.standard_id == std.id))
        db.execute(delete(StandardDocument).where(StandardDocument.standard_id == std.id))
        db.flush()
    std.source = str(folder.name)
    pdfs = sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".pdf")
    sheets = sorted(
        p for p in folder.rglob("*") if p.suffix.lower() == ".xlsx" and not p.name.startswith("~$")
    )
    report: dict[str, Any] = {
        "sops": len(pdfs),
        "read": 0,
        "failed": [],
        "rules": 0,
        "to_check": 0,
        "contradictions": 0,
        "formats": Counter(),
        "makes": [],
        "xlsx_rows": 0,
        "per_sop": [],
    }
    vendors: Counter = Counter()
    guarantees: Counter = Counter()
    made: list[StandardRule] = []
    for pdf in pdfs:
        try:
            rd = read_sop(pdf)
        except Exception as e:  # noqa: BLE001  (one unreadable SOP does not stop the rest)
            report["failed"].append({"file": pdf.name, "error": str(e)[:200]})
            continue
        report["read"] += 1
        report["formats"][rd.fmt] += 1
        doc = StandardDocument(
            standard_id=std.id,
            sop_no=rd.sop_no,
            revision=rd.revision,
            issue_date=rd.issue_date,
            title=rd.title,
            file_name=rd.file_name,
            fmt=rd.fmt,
            pages=rd.pages,
            element=rd.element,
        )
        db.add(doc)
        db.flush()
        for mk in rd.makes:
            vendors[mk["brand"]] += 1
        if rd.guarantee_years:
            guarantees[rd.guarantee_years] += 1
        for r in rd.rules:
            stype = vocab.system_type_of(r.system_text)
            parts_types = {stype} | {
                t
                for t in (_type_near(r.system_text, p) for p in ("elongation", "consumption"))
                if t
            }
            rule_specs = [
                s
                for s in rd.specs
                if not s.get("system_type")
                or s.get("system_type") in parts_types
                or vocab.satisfies(s.get("system_type"), stype)
            ]
            if r.condition_label and any(s.get("where") for s in rule_specs):
                rule_specs = [
                    s
                    for s in rule_specs
                    if not s.get("where") or (r.condition_label or "all") in s["where"]
                ]
            row = StandardRule(
                standard_id=std.id, document_id=doc.id, element=r.element or "unknown", element_label=r.element_label, condition_label=r.condition_label,
                condition=r.condition, system_type=stype, system_text=r.system_text, min_specs=rule_specs,
                makes=[m for m in rd.makes if _make_fits(m, stype)], tests=rd.tests, hold_points=rd.hold_points, checklist=rd.checklist,
                options_evaluated=rd.options, guarantee_years=rd.guarantee_years, boq_wording=rd.boq_wording, measurement=rd.measurement,
                page=r.page, confidence=r.confidence, status="to_check" if r.confidence == "low" else "ok", check_note="; ".join(r.notes) or None,
            )  # fmt: skip
            db.add(row)
            made.append(row)
        for c in rd.contradictions:
            db.add(
                StandardContradiction(
                    standard_id=std.id,
                    document_id=doc.id,
                    element=rd.element,
                    topic=c["topic"],
                    values=c["values"],
                    note=None,
                )
            )
            report["contradictions"] += 1
        report["per_sop"].append(
            {
                "file": rd.file_name,
                "sop_no": rd.sop_no,
                "revision": rd.revision,
                "format": rd.fmt,
                "pages": rd.pages,
                "element": rd.element,
                "rules": len(rd.rules),
                "contradictions": len(rd.contradictions),
            }
        )
    for sheet in sheets:
        rows = read_xlsx(sheet)
        report["xlsx_rows"] += len(rows)
        doc = StandardDocument(
            standard_id=std.id,
            sop_no=None,
            revision=None,
            title="Summary sheet",
            file_name=sheet.name,
            fmt="xlsx",
            pages=1,
        )
        db.add(doc)
        db.flush()
        for x in rows:
            _cross_check(made, x, sheet.name)
    std.approved_makes = [v for v, _n in vendors.most_common() if v != "Bronco"] if vendors else []
    std.guarantee_years = guarantees.most_common(1)[0][0] if guarantees else None
    db.flush()
    report["rules"] = len(made)
    report["to_check"] = sum(1 for r in made if r.status == "to_check")
    report["formats"] = dict(report["formats"])
    report["makes"] = std.approved_makes
    report["guarantee_years"] = std.guarantee_years
    std.report = report
    return std


def _make_fits(m: dict, stype: str | None) -> bool:
    st = vocab.system_type_of(m.get("system") or "")
    return not st or not stype or st == stype or vocab.satisfies(st, stype)


def _cross_check(rules: list[StandardRule], x: dict, sheet: str) -> None:
    """The summary sheet against the SOP rules: another system there -> the rule is to check."""
    want = vocab.system_type_of(x["system"])
    cands = [r for r in rules if r.element == x["element"]]
    for k, v in x["condition"].items():
        if k in ("area_sqm", "exposure", "confined", "water_table"):
            cands = [r for r in cands if r.condition.get(k) == v] or cands
    for r in cands:
        note = f"{sheet} row {x['row']}: {x['system'][:160]}"
        if (
            want
            and r.system_type
            and not vocab.satisfies(r.system_type, want)
            and not vocab.satisfies(want, r.system_type)
            and r.condition.get("face") != "inner"
        ):
            r.status, r.confidence = "to_check", "low"
            r.check_note = "; ".join(
                filter(
                    None,
                    [
                        r.check_note,
                        f"the summary sheet says {vocab.SYSTEM_LABEL.get(want, want)}: {note}",
                    ],
                )
            )
        elif r.status == "ok":
            r.check_note = "; ".join(filter(None, [r.check_note, f"agrees with {note}"]))
