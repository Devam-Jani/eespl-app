# ruff: noqa: E501  (the queries and rows read better unwrapped)
"""Reading the BOQ folder into the library, and grouping the lines into specification templates.

- run(): every Excel and PDF file under data/boq-knowledge/files/ is read (app.knowledge.reader)
  and its lines stored with their file, sheet and row; the historic import's lines (Prompt 15-17)
  whose files are not in the folder are added too (no working: the consolidated workbook kept only
  the client lines). The reading report is kept on the settings row.
- group(): lines with the same unit, area type, surface, requirements (coats, kg per sqm, DFT) and
  system family go to one template when their words are close (Jaccard on the description's words,
  the matching the rate library already uses), else they start a new one. A template's lines,
  names, descriptions and steps edited by hand are kept when the library is grouped again.
- consumption(): the products of the traced workings that match a product of the master become
  rows of the consumption table (source "old BOQ"), per surface and requirement, with how many
  BOQs used them.
"""

import re
import statistics
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.knowledge import extract
from app.knowledge.models import KnowledgeFile, KnowledgeLine, KnowledgeSettings, KnowledgeTemplate
from app.knowledge.reader import read_file

READABLE = (".xlsx", ".xlsm", ".xls", ".pdf")
JOIN_AT = 0.2
STOP = set(
    "the and of to in for with at by on as is be or a an all any per including include etc shall should will be providing applying supplying laying fixing doing work works area areas".split()
)
SURFACE_LABEL = {
    "rcc": "RCC",
    "brick": "brick",
    "plaster": "plaster",
    "screed": "screed",
    "old_tiles": "old tiles",
    "metal": "metal",
}


def root() -> Path:
    return Path(app_settings.data_dir) / "boq-knowledge" / "files"


def settings(db: Session) -> KnowledgeSettings:
    s = db.get(KnowledgeSettings, 1)
    if s is None:
        s = KnowledgeSettings(id=1, regions=dict(extract.DEFAULT_REGIONS))
        db.add(s)
        db.flush()
    return s


def words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def unit_family(unit: str | None) -> str | None:
    if unit in ("sqm", "sqft", "sft"):
        return "sqm"
    return unit


# --- reading ---------------------------------------------------------------------------------------


def _store(db: Session, facts, regions) -> KnowledgeFile:
    f = db.scalar(select(KnowledgeFile).where(KnowledgeFile.path == facts.path))
    if f is None:
        f = KnowledgeFile(path=facts.path, kind=facts.kind, status=facts.status)
        db.add(f)
        db.flush()
    else:
        db.execute(
            delete(KnowledgeLine).where(
                KnowledgeLine.file_id == f.id, KnowledgeLine.source == "file"
            )
        )
    for k in (
        "kind",
        "size",
        "status",
        "error",
        "sheets",
        "folder",
        "city",
        "region",
        "place_source",
        "on_date",
        "date_source",
        "is_eespl",
    ):
        setattr(f, k, getattr(facts, k))
    f.lines = len(facts.lines)
    f.lines_with_working = sum(1 for ln in facts.lines if ln.get("working"))
    f.read_at = func.now()
    for ln in facts.lines:
        r = ln["requirements"]
        db.add(KnowledgeLine(
            file_id=f.id, source="file", sheet=ln["sheet"], row=ln["row"], item_no=(ln["item_no"] or None) and str(ln["item_no"])[:50],
            parent_item=ln["parent_item"], description=ln["description"] or "", unit=(ln["unit"] or None) and ln["unit"][:20],
            unit_raw=(ln["unit_raw"] or None) and str(ln["unit_raw"])[:50], qty=ln["qty"], qty_note=ln["qty_note"], rate=ln["rate"],
            rate_sqm=ln["rate_sqm"], product_make=ln["product_make"], remarks=ln["remarks"], area_type=r["area_type"],
            surface=r["surface"], coats=r["coats"], min_kg_sqm=r["min_kg_sqm"], dft_mm=r["dft_mm"], requirements=r,
            working=ln["working"], cost_sqm=ln["cost_sqm"], margin_percent=ln["margin_percent"], city=facts.city,
            region=facts.region, on_date=facts.on_date, folder=facts.folder, to_check=ln["to_check"], check_note=ln["check_note"],
        ))  # fmt: skip
    return f


def _read_one(args):
    base, path, regions = args
    try:
        return read_file(Path(base), Path(path), regions)
    except Exception as exc:  # noqa: BLE001  (a worker never dies on a file)
        from app.knowledge.reader import FileFacts  # noqa: PLC0415

        rel = Path(path).relative_to(base).as_posix()
        return FileFacts(
            path=rel,
            kind=Path(path).suffix.lower().lstrip("."),
            size=0,
            status="failed",
            error=f"{type(exc).__name__}: {exc}"[:300],
        )


def run(
    db: Session, again: bool = False, limit: int | None = None, workers: int = 8, log=print
) -> dict:
    """Read every file under data/boq-knowledge/files/ (read only), then group and count. Files
    are read in parallel (reading is pure; storing is here, one file at a time)."""
    from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415

    s = settings(db)
    regions = s.regions or extract.DEFAULT_REGIONS
    base = root()
    paths = sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in READABLE and not p.name.startswith("~$")
    )
    if limit:
        paths = paths[:limit]
    known = {f.path: f for f in db.scalars(select(KnowledgeFile))}
    todo = []
    for p in paths:
        old = known.get(p.relative_to(base).as_posix())
        if (
            old is not None
            and not again
            and old.size == p.stat().st_size
            and old.status != "failed"
        ):
            continue
        todo.append((str(base), str(p), regions))
    t0 = time.time()
    log(f"reading {len(todo)} of {len(paths)} files with {workers} workers")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, facts in enumerate(pool.map(_read_one, todo, chunksize=4), 1):
            _store(db, facts, regions)
            db.commit()
            if i % 100 == 0:
                log(f"  {i}/{len(todo)} files, {round(time.time() - t0)} s")
    historic(db, regions)
    db.execute(
        text("UPDATE knowledge_lines SET working = NULL WHERE working = 'null'::jsonb")
    )  # rows stored before none_as_null
    db.commit()
    units = check_units(db)
    made = group(db)
    far = flag_far_rates(db)
    rows = consumption(db)
    report = reading_report(db) | {"templates_made": made, "units_converted": units["converted"], "far_rates_flagged": far, "consumption_rows": rows, "seconds": round(time.time() - t0),
                                   "source_folder": str(base)}  # fmt: skip
    s.last_run = report
    s.source_folder = str(base)
    db.commit()
    return report


def historic(db: Session, regions) -> int:
    """The historic import's lines (Prompt 15-17) whose file is not in the folder: added as lines
    of a "historic" file (the client line only; the consolidated workbook kept no working)."""
    from app.masters.models import LibraryLine  # noqa: PLC0415

    # rebuilt each time: a file read since is no longer historic
    old = list(db.scalars(select(KnowledgeFile.id).where(KnowledgeFile.path.like("historic:%"))))
    if old:
        db.execute(delete(KnowledgeLine).where(KnowledgeLine.file_id.in_(old)))
        db.execute(delete(KnowledgeFile).where(KnowledgeFile.id.in_(old)))
        db.flush()
    paths = [
        f.path.lower()
        for f in db.scalars(
            select(KnowledgeFile).where(
                ~KnowledgeFile.path.like("historic:%"), KnowledgeFile.status == "read"
            )
        )
    ]
    tails = {"/".join(p.split("/")[-2:]) for p in paths} | {p.split("/")[-1] for p in paths}
    by_file: dict[str, list] = defaultdict(list)
    for ln in db.scalars(
        select(LibraryLine).where(
            LibraryLine.is_excluded.is_(False), LibraryLine.is_competitor.is_(False)
        )
    ):
        tail2 = "/".join(ln.file.lower().split("/")[-2:])
        if tail2 in tails or ln.file.lower().split("/")[-1] in tails:
            continue
        by_file[ln.file].append(ln)
    n = 0
    for file, lines in by_file.items():
        path = f"historic:{file}"[:2000]
        f = db.scalar(select(KnowledgeFile).where(KnowledgeFile.path == path))
        if f is None:
            f = KnowledgeFile(path=path, kind="lib", status="read")
            db.add(f)
            db.flush()
        db.execute(delete(KnowledgeLine).where(KnowledgeLine.file_id == f.id))
        parts = file.split("/")
        f.folder = parts[0] if len(parts) > 1 else None
        f.city, f.region, f.place_source = extract.place(
            [("folder", " ".join(parts[:-1])), ("file name", parts[-1])], regions
        )
        f.on_date, f.date_source = extract.file_date(parts[-1], " ".join(parts[:-1]), [], None)
        f.lines, f.lines_with_working, f.is_eespl = (
            len(lines),
            0,
            parts[-1].upper().startswith("EESPL"),
        )
        context = extract.requirements(parts[-1])
        from app.knowledge.reader import _facts_of_line  # noqa: PLC0415

        for ln in lines:
            row = {"parent_item": ln.parent_item, "description": ln.description, "remarks": ln.remarks, "product_make": ln.product_make,
                   "unit": ln.unit, "unit_raw": ln.unit_raw, "rate": ln.rate, "working": None}  # fmt: skip
            _facts_of_line(row, context)
            r = row["requirements"]
            db.add(KnowledgeLine(
                file_id=f.id, source="file", sheet=ln.sheet, row=ln.row, item_no=ln.item_no, parent_item=ln.parent_item,
                description=ln.description, unit=row["unit"], unit_raw=ln.unit_raw, qty=ln.qty, qty_note=ln.qty_note, rate=row["rate"],
                rate_sqm=row["rate_sqm"], product_make=ln.product_make, remarks=ln.remarks, area_type=r["area_type"], surface=r["surface"],
                coats=r["coats"], min_kg_sqm=r["min_kg_sqm"], dft_mm=r["dft_mm"], requirements=r, city=f.city, region=f.region,
                on_date=f.on_date, folder=f.folder, to_check=row["to_check"], check_note=row["check_note"],
            ))  # fmt: skip
            n += 1
    return n


def reading_report(db: Session) -> dict:
    files = db.execute(
        select(KnowledgeFile.status, KnowledgeFile.kind, func.count()).group_by(
            KnowledgeFile.status, KnowledgeFile.kind
        )
    ).all()
    by_status: Counter = Counter()
    by_kind: Counter = Counter()
    for st, kind, n in files:
        by_status[st] += n
        by_kind[kind] += n
    q = select(func.count()).select_from(KnowledgeLine).where(KnowledgeLine.source == "file")
    lines = db.scalar(q) or 0
    failed = [
        {"path": f.path, "error": f.error}
        for f in db.scalars(
            select(KnowledgeFile)
            .where(KnowledgeFile.status == "failed")
            .order_by(KnowledgeFile.path)
        )
    ]
    return {
        "files": sum(by_status.values()), "files_by_status": dict(by_status), "files_by_kind": dict(by_kind),
        "lines": lines,
        "lines_with_working": db.scalar(q.where(KnowledgeLine.working.is_not(None))) or 0,
        "lines_with_place": db.scalar(q.where(KnowledgeLine.city.is_not(None))) or 0,
        "lines_with_date": db.scalar(q.where(KnowledgeLine.on_date.is_not(None))) or 0,
        "lines_with_area": db.scalar(q.where(KnowledgeLine.area_type.is_not(None))) or 0,
        "lines_qro": db.scalar(q.where(KnowledgeLine.qty_note == "QRO")) or 0,
        "lines_nq": db.scalar(q.where(KnowledgeLine.qty_note == "NQ")) or 0,
        "lines_to_check": db.scalar(q.where(KnowledgeLine.to_check.is_(True))) or 0,
        "failed": failed[:300],
        "scanned": [f.path for f in db.scalars(select(KnowledgeFile).where(KnowledgeFile.status == "scanned").order_by(KnowledgeFile.path))][:500],
    }  # fmt: skip


# --- templates -------------------------------------------------------------------------------------


def line_key(ln: KnowledgeLine) -> str | None:
    """unit | area | surface | coats | kg | dft | families: None for a line that is not
    waterproofing (no area type and no system family)."""
    fams = [f for f in (ln.requirements or {}).get("families", [])][:1]  # the main family
    if not ln.area_type and not fams:
        return None
    u = unit_family(ln.unit)
    if not u:
        return None
    kg = f"{Decimal(ln.min_kg_sqm).normalize():f}" if ln.min_kg_sqm else ""
    dft = ""  # a DFT stays on the line: too rare to split templates on
    return "|".join(
        [
            u,
            ln.area_type or "",
            ln.surface or "",
            str(ln.coats or ""),
            kg,
            dft,
            "+".join(sorted(fams)),
        ]
    )[:200]


def template_name(key: str) -> str:
    u, area, surface, coats, kg, dft, fams = key.split("|")
    bits = [extract.AREA_LABEL.get(area, "Waterproofing") if area else "Waterproofing"]
    if surface:
        bits.append(SURFACE_LABEL.get(surface, surface))
    sys_ = " + ".join(extract.FAMILY_LABEL.get(f, f) for f in fams.split("+") if f)
    if coats or sys_:
        bits.append(" ".join(x for x in [f"{coats} coats" if coats else "", sys_] if x))
    if kg:
        bits.append(f"{kg} kg/sqm")
    if dft:
        bits.append(f"{dft} mm DFT")
    if u != "sqm":
        bits.append(f"per {u}")
    return ", ".join(bits)[:200]


def best_description(lines: list[KnowledgeLine]) -> str:
    """The best-written client text: from our own offers first, then the fullest (not over long)."""

    def score(ln):
        d = ln.description or ""
        return (bool(ln.rate), 300 <= len(d) <= 1500, min(len(d), 1500))

    return max(lines, key=score).description if lines else ""


def steps_for(db: Session, area: str | None, fams: list[str]) -> tuple[list[str], str | None]:
    """The method statement from the stage template whose keywords fit best."""
    from app.sites.models import StageTemplate  # noqa: PLC0415

    want = (
        {area or ""}
        | set(fams)
        | set((extract.AREA_LABEL.get(area or "", "") or "").lower().split())
    )
    want |= {
        "pu" if "pu" in fams else "",
        "crystalline" if "crystalline" in fams else "",
        "membrane" if any("membrane" in f for f in fams) else "",
    }
    best, score = None, 0
    for t in db.scalars(select(StageTemplate).where(StageTemplate.is_active.is_(True))):
        if (t.name or "").startswith("DEMO"):
            continue
        kw = set((t.keywords or "").lower().split()) | set(
            re.findall(r"[a-z]+", (t.name or "").lower())
        )
        s = len(kw & {w for w in want if w})
        if s > score:
            best, score = t, s
    if best is None:
        return [], None
    return [
        s.name for s in sorted(best.steps, key=lambda s: s.sort_order)
    ], f"stage template {best.name}"


def regroup(db: Session) -> int:
    """Group the library again from scratch: every template not reviewed by hand is rebuilt (a
    reviewed one keeps its name, words, steps and lines)."""
    keep = list(
        db.scalars(select(KnowledgeTemplate.id).where(KnowledgeTemplate.reviewed.is_(True)))
    )
    lines = KnowledgeLine.__table__
    if keep:
        db.execute(lines.update().where(~lines.c.template_id.in_(keep)).values(template_id=None))
        db.execute(delete(KnowledgeTemplate).where(~KnowledgeTemplate.id.in_(keep)))
    else:
        db.execute(lines.update().values(template_id=None))
        db.execute(delete(KnowledgeTemplate))
    db.flush()
    return group(db)


def group(db: Session) -> int:
    """Put every waterproofing line into a template (new ones made); returns how many were made."""
    templates = list(db.scalars(select(KnowledgeTemplate)))
    by_key: dict[str, list[KnowledgeTemplate]] = defaultdict(list)
    for t in templates:
        if t.merged_into_id is None:
            by_key[t.key].append(t)
    reps: dict[int, set[str]] = {t.id: words(t.description) for t in templates}
    made = 0
    lines = list(
        db.scalars(
            select(KnowledgeLine).where(KnowledgeLine.hidden.is_(False)).order_by(KnowledgeLine.id)
        )
    )
    members: dict[int, list[KnowledgeLine]] = defaultdict(list)
    active = {t.id: t for t in templates}
    for ln in lines:
        placed = active.get(ln.template_id) if ln.template_id else None
        while placed is not None and placed.merged_into_id:  # a merged template's lines follow it
            placed = active.get(placed.merged_into_id)
        if placed is not None and not placed.hidden:
            ln.template_id = placed.id  # kept across groupings (a move by hand included)
            members[placed.id].append(ln)
            continue
        key = line_key(ln)
        if key is None:
            ln.template_id = None
            continue
        w = words(ln.description)
        cands = by_key.get(key, [])
        best = max(cands, key=lambda t: jaccard(w, reps[t.id]), default=None)
        if best is not None and (
            jaccard(w, reps[best.id]) >= JOIN_AT
            or len(cands) == 1
            and jaccard(w, reps[best.id]) >= JOIN_AT / 2
        ):
            ln.template_id = best.id
        else:
            u, area, surface, coats, kg, dft, fams = key.split("|")
            t = KnowledgeTemplate(key=key, name=template_name(key), area_type=area or None, surface=surface or None,
                                  coats=int(coats) if coats else None, min_kg_sqm=Decimal(kg) if kg else None,
                                  dft_mm=Decimal(dft) if dft else None, families=[f for f in fams.split("+") if f], unit=u,
                                  description=ln.description)  # fmt: skip
            db.add(t)
            db.flush()
            by_key[key].append(t)
            reps[t.id] = w
            ln.template_id = t.id
            made += 1
        members[ln.template_id].append(ln)
    for t in db.scalars(
        select(KnowledgeTemplate).where(KnowledgeTemplate.merged_into_id.is_(None))
    ):
        mine = members.get(t.id, [])
        if not t.reviewed:  # an edited template keeps its own words and steps
            t.description = best_description(mine) or t.description
            t.steps, t.steps_source = steps_for(db, t.area_type, t.families or [])
        refresh(t, mine)
    db.flush()
    return made


def refresh(t: KnowledgeTemplate, lines: list[KnowledgeLine]) -> None:
    rates = [
        Decimal(ln.rate_sqm if t.unit == "sqm" else ln.rate)
        for ln in lines
        if (ln.rate_sqm if t.unit == "sqm" else ln.rate)
    ]
    t.lines_count = len(lines)
    t.files_count = len({ln.file_id for ln in lines})
    t.median_rate = Decimal(statistics.median(rates)).quantize(Decimal("0.01")) if rates else None
    dates = [ln.on_date for ln in lines if ln.on_date]
    t.latest_on = max(dates) if dates else None
    t.to_check = bool(lines) and sum(1 for ln in lines if ln.to_check) * 2 > len(lines)


# --- consumption from the workings -------------------------------------------------------------------


def _product_index(db: Session):
    from app.masters.models import Product  # noqa: PLC0415

    out = []
    for p in db.scalars(select(Product)):
        names = {p.name.lower()} | {a.lower() for a in (p.aliases or [])}
        if p.code:
            names.add(p.code.lower())
        # workings name the product without its brand: "cemguard plus" for BRONCO CEMGUARD PLUS
        for n in list(names):
            parts = n.split()
            if len(parts) >= 2 and len(" ".join(parts[1:])) >= 6:
                names.add(" ".join(parts[1:]))
        out.append((p.id, {n for n in names if len(n) >= 4}))
    return out


def match_product(index, label: str) -> int | None:
    low = (label or "").lower().strip()
    if len(low) < 4:
        return None
    best, size = None, 0
    for pid, names in index:
        for n in names:
            if (
                n in low and len(n) > size
            ):  # the product named in the label (not "primer" in a name)
                best, size = pid, len(n)
    return best


def consumption(db: Session) -> int:
    """The workings' products (matched to the product master) as consumption rows: per product,
    surface and requirement, the consumption most BOQs used, and how many."""
    from app.costing.models import ProductConsumption  # noqa: PLC0415

    index = _product_index(db)
    seen: dict[tuple, Counter] = defaultdict(Counter)
    refs: dict[tuple, str] = {}
    for ln in db.scalars(select(KnowledgeLine).where(KnowledgeLine.working.is_not(None))):
        for item in (ln.working or {}).get("items", []):
            if (
                item.get("kind") != "product"
                or not item.get("consumption")
                or re.search(r"margin|profit|overhead|total", item.get("label") or "", re.I)
            ):
                continue
            pid = match_product(index, item.get("label", ""))
            if pid is None:
                continue
            c = Decimal(item["consumption"])
            if not Decimal("0.01") <= c <= Decimal("20"):
                continue
            key = (pid, ln.surface or "any", ln.coats, ln.min_kg_sqm, ln.dft_mm)
            seen[key][c.quantize(Decimal("0.001"))] += 1
            f = db.get(KnowledgeFile, ln.file_id) if ln.file_id else None
            refs.setdefault(key, f"{f.path if f else 'won BOQ'} · {item.get('ref')}")
    db.execute(delete(ProductConsumption).where(ProductConsumption.source == "old_boq"))
    n = 0
    for (pid, surface, coats, kg, dft), counts in seen.items():
        value, used = counts.most_common(1)[0]
        total = sum(counts.values())
        db.add(ProductConsumption(product_id=pid, surface=surface, coats=coats, min_kg_sqm=kg, dft_mm=dft, consumption=value,
                                  source="old_boq", used_count=total,
                                  source_ref=f"{total} old BOQ working(s), {used} at this figure; e.g. {refs[(pid, surface, coats, kg, dft)]}"[:2000],
                                  to_check=len(counts) > 2))  # fmt: skip
        n += 1
    db.flush()
    return n


# --- rate units ---------------------------------------------------------------------------------------


def check_units(db: Session) -> dict:
    """Our offers often quote per sq ft while the BOQ's unit column says sqm (terrace at ₹65 "per
    sqm" is ₹65 per sq ft). A line read as per sqm is taken as per sq ft (rate × 10.7639) when
    its rate is under a fifth of the usual rate for its area type, the converted rate falls in
    the usual range, and its own unit was blank or its sheet's other lines are per sq ft. Then
    every line still more than 5× away from its template's median is marked "unit to check"."""
    lines = list(
        db.scalars(
            select(KnowledgeLine).where(
                KnowledgeLine.rate_sqm.is_not(None), KnowledgeLine.hidden.is_(False)
            )
        )
    )
    by_area: dict[str, list[Decimal]] = defaultdict(list)
    for ln in lines:
        if ln.area_type and ln.rate_sqm and Decimal(ln.rate_sqm) >= 150:
            by_area[ln.area_type].append(Decimal(ln.rate_sqm))
    usual = {a: Decimal(statistics.median(v)) for a, v in by_area.items() if len(v) >= 5}
    sheet_sqft: dict[tuple, bool] = defaultdict(bool)
    for ln in lines:
        if ln.unit in ("sqft", "sft"):
            sheet_sqft[(ln.file_id, ln.sheet)] = True
    changed = 0
    for ln in lines:
        m = usual.get(ln.area_type or "")
        if not m or ln.unit != "sqm" or (ln.check_note or "").startswith("unit read as sq ft"):
            continue
        r = Decimal(ln.rate_sqm)
        conv = r * Decimal("10.7639")
        blank = not (ln.unit_raw or "").strip()
        if (
            r < m / 5
            and m / Decimal("2.5") <= conv <= m * Decimal("2.5")
            and (blank or sheet_sqft[(ln.file_id, ln.sheet)])
        ):
            ln.rate_sqm = conv.quantize(Decimal("0.01"))
            ln.to_check, ln.check_note = (
                True,
                f"unit read as sq ft: ₹{r} per sq ft is ₹{ln.rate_sqm} per sqm (×10.7639)",
            )
            changed += 1
    db.flush()
    return {"converted": changed, "usual_by_area": {k: str(round(v)) for k, v in usual.items()}}


def flag_far_rates(db: Session) -> int:
    """After grouping: a line more than 5× away from its template's median: "unit to check"."""
    n = 0
    meds = {
        t.id: t.median_rate
        for t in db.scalars(
            select(KnowledgeTemplate).where(KnowledgeTemplate.median_rate.is_not(None))
        )
    }
    for ln in db.scalars(select(KnowledgeLine).where(KnowledgeLine.template_id.is_not(None))):
        med = meds.get(ln.template_id)
        r = ln.rate_sqm if ln.rate_sqm is not None else ln.rate
        if not med or not r or Decimal(r) <= 0:
            continue
        ratio = Decimal(r) / Decimal(med)
        if (ratio > 5 or ratio < Decimal("0.2")) and not (ln.check_note or "").startswith(
            "unit to check"
        ):
            ln.to_check, ln.check_note = (
                True,
                f"unit to check: ₹{r} is {round(ratio, 1)}× the template median ₹{med}",
            )
            n += 1
    db.flush()
    return n


def refresh_families(db: Session) -> int:
    """The system families of every stored line worked again from its words (after the family
    list changed), keeping the area, surface and requirements as read."""
    n = 0
    for ln in db.scalars(select(KnowledgeLine)):
        req = extract.requirements(ln.parent_item, ln.description, ln.remarks, ln.product_make)
        r = dict(ln.requirements or {})
        if r.get("families") != req.families:
            r["families"] = req.families
            ln.requirements = r
            n += 1
    db.flush()
    return n
