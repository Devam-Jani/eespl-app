# ruff: noqa: E501  (wording and patterns read better unwrapped)
"""The client's work order, checked against our accepted quotation before we sign it: every line
missing or added, a changed quantity, rate or unit, a product discontinued in our master, scope
our T&C put on the client that the work order puts on us (or the reverse), and payment, retention,
advance, penalty and time terms that differ from ours. Each deviation is accepted or sent back
(a to-do for the salesperson with the text to send); the work order is accepted only when none is
open, and then it is locked."""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout.common import locked, now, unprocessable
from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine, WoDeviation
from app.masters.models import Product
from app.quotations.models import Quotation, QuotationLine

# what a T&C clause or a work order puts on someone, by topic
SCOPE_TOPICS: list[tuple[str, str]] = [
    ("material lifting and shifting", r"lift(ing)?\b|shift(ing)?\b|hoist"),
    ("water", r"\bwater\b(?!\s*proof)"),
    ("electricity / power", r"electric|power"),
    ("storage with lock", r"\bstore\b|storage|godown"),
    ("scaffolding", r"scaffold"),
    ("accommodation for workers", r"accommodation|labour\s*camp"),
    ("cement, sand and brick bats", r"cement|sand|brick\s*bat"),
    ("debris and muck removal", r"debris|muck|bailing"),
]
BASIS_WORDS = [
    ("certification", r"certif"),
    ("final_bill", r"final\s*bill"),
    ("invoice", r"invoice|bill|submission|r\.?\s*a\.?"),
]
WORD = re.compile(r"[a-z0-9]{3,}")
STOP = {
    "the",
    "and",
    "with",
    "for",
    "providing",
    "applying",
    "laying",
    "including",
    "area",
    "areas",
    "work",
    "works",
    "waterproofing",
    "water",
    "proofing",
    "treatment",
}


def topics_of(text: str) -> set[str]:
    return {name for name, pat in SCOPE_TOPICS if re.search(pat, text or "", re.I)}


def guard(wo: ClientWorkOrder) -> None:
    if wo.status == "accepted":
        raise locked(f"Work order {wo.code} (accepted)")


# --- reading the file -----------------------------------------------------------------------------


def _num(v) -> Decimal | None:
    if v is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return Decimal(s) if s not in ("", ".", "-") else None
    except InvalidOperation:
        return None


def _header(cells: list[str]) -> dict[str, int] | None:
    low = [str(c or "").strip().lower() for c in cells]
    col = {}
    for i, c in enumerate(low):
        if "desc" in c or c in ("item", "particulars", "work description"):
            col.setdefault("description", i)
        elif c.startswith(("qty", "quantity")):
            col.setdefault("qty", i)
        elif c.startswith(("unit", "uom")):
            col.setdefault("unit", i)
        elif c.startswith("rate"):
            col.setdefault("rate", i)
        elif c.startswith(("sr", "s.no", "item no", "no")):
            col.setdefault("item_no", i)
    return col if "description" in col and ("qty" in col or "rate" in col) else None


def _cell(cells: list[str], col: dict[str, int], key: str) -> str | None:
    return cells[col[key]] if key in col and col[key] < len(cells) else None


def rows_to_lines(rows: list[list]) -> list[dict]:
    col, out = None, []
    for r in rows:
        cells = ["" if c is None else str(c).strip() for c in r]
        if col is None:
            col = _header(cells)
            continue
        desc = cells[col["description"]] if col["description"] < len(cells) else ""
        if not desc or len(desc) < 3:
            continue
        out.append({"item_no": _cell(cells, col, "item_no"), "description": desc, "unit": _cell(cells, col, "unit"),
                    "qty": _num(_cell(cells, col, "qty")), "rate": _num(_cell(cells, col, "rate"))})  # fmt: skip
    return out


def read_file(path: Path) -> tuple[list[dict], str]:
    """The lines (when the file has a table) and the text (for the terms)."""
    text, lines = "", []
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            lines = lines or rows_to_lines(rows)
            text += "\n".join(" ".join(str(c) for c in r if c is not None) for r in rows) + "\n"
    elif path.suffix.lower() == ".pdf":
        import pdfplumber  # noqa: PLC0415

        with pdfplumber.open(str(path)) as pdf:
            rows = []
            for p in pdf.pages:
                text += (p.extract_text() or "") + "\n"
                for t in p.extract_tables() or []:
                    rows += t
            lines = rows_to_lines(rows)
    return lines, text


def terms_from_text(text: str) -> dict:
    """The payment term, retention, advance, penalty, time limit and scope the work order states."""
    t = re.sub(r"\s+", " ", text or "")
    out: dict = {}
    m = re.search(r"payment[^.]{0,120}?(\d{1,3})\s*days", t, re.I)
    if m:
        out["payment_days"] = int(m.group(1))
        span = t[max(0, m.start() - 20) : m.end() + 80]
        out["payment_basis"] = next(
            (b for b, p in BASIS_WORDS if re.search(p, span, re.I)), "invoice"
        )
    m = re.search(
        r"retention[^.]{0,40}?(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*retention", t, re.I
    )
    if m:
        out["retention_percent"] = Decimal(m.group(1) or m.group(2))
    m = re.search(r"advance[^.]{0,40}?(\d+(?:\.\d+)?)\s*%", t, re.I)
    if m:
        out["advance_percent"] = Decimal(m.group(1))
    m = re.search(r"(penalty|liquidated damages|\bLD\b)[^.]{0,160}", t, re.I)
    if m:
        out["penalty"] = m.group(0).strip()
    m = re.search(r"(?:complete|completion)[^.]{0,60}?within\s*(\d+)\s*days", t, re.I)
    if m:
        out["time_limit_days"] = int(m.group(1))
    m = re.search(r"guarantee[^.]{0,40}?(\d+)\s*years?", t, re.I)
    if m:
        out["guarantee_years"] = int(m.group(1))
    us = re.findall(
        r"([^.;]{0,120}?)\s*(?:shall be (?:provided|arranged|done) by (?:the )?(?:contractor|applicator|vendor)|in (?:the )?contractor'?s scope)",
        t,
        re.I,
    )
    out["scope_on_us"] = sorted({x for s in us for x in topics_of(s)})
    them = re.findall(
        r"([^.;]{0,120}?)\s*(?:shall be (?:provided|arranged) by (?:the )?(?:client|owner|company)|free of (?:cost|charge))",
        t,
        re.I,
    )
    out["scope_on_client"] = sorted({x for s in them for x in topics_of(s)})
    return out


def set_lines(db: Session, wo: ClientWorkOrder, rows: list[dict], source: str) -> None:
    guard(wo)
    wo.lines = []
    db.flush()
    for i, r in enumerate(rows):
        wo.lines.append(ClientWorkOrderLine(sort_order=i, item_no=(r.get("item_no") or None), description=r["description"], unit=r.get("unit"),
                                            qty=r.get("qty"), rate=r.get("rate"), product_id=r.get("product_id"), quotation_line_id=r.get("quotation_line_id")))  # fmt: skip
    wo.lines_from = source
    db.flush()


def copy_from_quotation(db: Session, wo: ClientWorkOrder) -> None:
    q = db.get(Quotation, wo.quotation_id) if wo.quotation_id else None
    if q is None:
        raise unprocessable("Link the accepted quotation first")
    rows = [{"description": ln.description, "unit": ln.uom, "qty": ln.qty, "rate": ln.rate, "quotation_line_id": ln.id}
            for it in q.items for ln in it.lines if not ln.client_scope]  # fmt: skip
    set_lines(db, wo, rows, "quotation")


# --- comparing ------------------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    return set(WORD.findall((text or "").lower())) - STOP


def _sim(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def _unit(u: str | None) -> str:
    u = (u or "").strip().lower().replace(".", "").replace(" ", "")
    return {
        "sqmt": "sqm",
        "m2": "sqm",
        "sqmtr": "sqm",
        "sft": "sqft",
        "rm": "rmt",
        "rmtr": "rmt",
        "no": "nos",
        "cumt": "cum",
        "m3": "cum",
    }.get(u, u)


def our_terms(q: Quotation) -> dict:
    """Our offer's terms, read from its T&C clauses."""
    terms = q.terms or []
    pay = " ".join(t.get("text", "") for t in terms if t.get("category") == "payment")
    allt = " ".join(t.get("text", "") for t in terms)
    out: dict = {
        "client_scope": sorted(
            {
                x
                for t in terms
                if t.get("category") == "client_scope"
                for x in topics_of(t.get("text", ""))
            }
        )
    }
    days = [int(d) for d in re.findall(r"(\d{1,3})\s*\(?[a-z ]*\)?\s*days", pay, re.I)]
    if days:
        out["payment_days"] = max(days)
        out["payment_basis"] = next(
            (b for b, p in BASIS_WORDS if re.search(p, pay, re.I)), "invoice"
        )
    m = re.search(r"retention[^.]{0,40}?(\d+(?:\.\d+)?)\s*%", allt, re.I)
    out["retention_percent"] = Decimal(m.group(1)) if m else Decimal(0)
    m = re.search(r"advance[^.]{0,40}?(\d+(?:\.\d+)?)\s*%", allt, re.I)
    out["advance_percent"] = Decimal(m.group(1)) if m else Decimal(0)
    out["penalty"] = bool(re.search(r"penalty|liquidated", allt, re.I))
    out["guarantee_years"] = q.guarantee_years
    return out


def compare(db: Session, wo: ClientWorkOrder) -> list[WoDeviation]:
    """The deviations again (a resolved one stays resolved when it is still there)."""
    guard(wo)
    q = db.get(Quotation, wo.quotation_id) if wo.quotation_id else None
    if q is None:
        raise unprocessable("Link the accepted quotation first")
    old = {(d.kind, d.topic): d for d in wo.deviations}
    found: list[dict] = []
    ours = [ln for it in q.items for ln in it.lines if not ln.client_scope]
    used: set[int] = set()
    matched: dict[int, QuotationLine] = {}
    for wl in wo.lines:
        best = None
        if wl.quotation_line_id:
            best = next((ln for ln in ours if ln.id == wl.quotation_line_id), None)
        if best is None:
            cands = sorted(
                ((_sim(wl.description, ln.description), ln) for ln in ours if ln.id not in used),
                key=lambda x: -x[0],
            )
            best = cands[0][1] if cands and cands[0][0] >= 0.3 else None
        if best is None:
            found.append(
                {
                    "kind": "added",
                    "topic": f"Added: {wl.description[:120]}",
                    "theirs": f"{wl.qty or ''} {wl.unit or ''} @ {wl.rate or ''}",
                    "wo_line_id": wl.id,
                }
            )
            continue
        used.add(best.id)
        matched[wl.id] = best
        wl.quotation_line_id = best.id
        tag = best.description[:80]
        if _unit(wl.unit) and _unit(best.uom) and _unit(wl.unit) != _unit(best.uom):
            found.append(
                {
                    "kind": "unit",
                    "topic": f"Unit changed: {tag}",
                    "ours": f"per {best.uom}",
                    "theirs": f"per {wl.unit}",
                    "wo_line_id": wl.id,
                    "quotation_line_id": best.id,
                }
            )
        if (
            wl.qty is not None
            and best.qty is not None
            and abs(Decimal(wl.qty) - Decimal(best.qty))
            > max(Decimal("0.001"), Decimal(best.qty) * Decimal("0.005"))
        ):
            found.append(
                {
                    "kind": "qty",
                    "topic": f"Quantity changed: {tag}",
                    "ours": f"{best.qty} {best.uom}",
                    "theirs": f"{wl.qty} {wl.unit or ''}",
                    "wo_line_id": wl.id,
                    "quotation_line_id": best.id,
                }
            )
        if wl.rate is not None and best.rate is not None and Decimal(wl.rate) != Decimal(best.rate):
            found.append(
                {
                    "kind": "rate",
                    "topic": f"Rate changed: {tag}",
                    "ours": f"{best.rate}",
                    "theirs": f"{wl.rate}",
                    "wo_line_id": wl.id,
                    "quotation_line_id": best.id,
                }
            )
    for ln in ours:
        if ln.id not in used and not ln.if_required:
            found.append(
                {
                    "kind": "missing",
                    "topic": f"Missing: {ln.description[:120]}",
                    "ours": f"{ln.qty or ''} {ln.uom} @ {ln.rate or ''}",
                    "quotation_line_id": ln.id,
                }
            )
    # products discontinued in our master, named in a line or set on it
    gone = list(db.scalars(select(Product).where(Product.discontinued_on.is_not(None))))
    for wl in wo.lines:
        text = f"{wl.description} {matched[wl.id].description if wl.id in matched else ''}".lower()
        for p in gone:
            if wl.product_id == p.id or (p.name and p.name.lower() in text):
                found.append({"kind": "discontinued", "topic": f"Discontinued product: {p.name}", "ours": f"{p.name} discontinued on {p.discontinued_on:%d.%m.%Y}",
                              "theirs": wl.description[:160], "wo_line_id": wl.id})  # fmt: skip
    # scope: what our T&C put on the client that the work order puts on us, and the reverse
    t = our_terms(q)
    for topic in sorted(set(wo.scope_on_us or []) & set(t["client_scope"])):
        found.append(
            {
                "kind": "scope",
                "topic": f"Scope: {topic}",
                "ours": "client's obligation in our T&C",
                "theirs": "on us in the work order",
            }
        )
    offered = " ".join(ln.description for ln in ours)
    for topic in sorted(set(wo.scope_on_client or []) - set(t["client_scope"])):
        if topic in topics_of(offered):
            found.append(
                {
                    "kind": "scope",
                    "topic": f"Scope: {topic}",
                    "ours": "in our offer (on us)",
                    "theirs": "on the client in the work order",
                }
            )
    # the payment and other terms
    if wo.payment_days is not None and (
        wo.payment_days != t.get("payment_days")
        or (wo.payment_basis or "invoice") != t.get("payment_basis", "invoice")
    ):
        found.append({"kind": "payment", "topic": "Payment term", "ours": f"{t.get('payment_days', '—')} days after the {t.get('payment_basis', 'invoice').replace('_', ' ')}",
                      "theirs": f"{wo.payment_days} days after the {(wo.payment_basis or 'invoice').replace('_', ' ')}"})  # fmt: skip
    if wo.retention_percent is not None and Decimal(wo.retention_percent) != t["retention_percent"]:
        found.append(
            {
                "kind": "retention",
                "topic": "Retention",
                "ours": f"{t['retention_percent']} %",
                "theirs": f"{wo.retention_percent} %"
                + (f", released {wo.retention_release}" if wo.retention_release else ""),
            }
        )
    if wo.advance_percent is not None and Decimal(wo.advance_percent) != t["advance_percent"]:
        found.append(
            {
                "kind": "advance",
                "topic": "Advance",
                "ours": f"{t['advance_percent']} %",
                "theirs": f"{wo.advance_percent} %",
            }
        )
    if wo.penalty and not t["penalty"]:
        found.append(
            {
                "kind": "penalty",
                "topic": "Penalty",
                "ours": "no penalty in our terms",
                "theirs": wo.penalty[:300],
            }
        )
    if wo.time_limit_days:
        found.append(
            {
                "kind": "time",
                "topic": "Time limit",
                "ours": "not in our offer",
                "theirs": f"complete within {wo.time_limit_days} days",
            }
        )
    keep = []
    for f in found:
        d = old.pop((f["kind"], f["topic"]), None)
        if d is None:
            d = WoDeviation(work_order_id=wo.id, **f)
            db.add(d)
        else:
            d.ours, d.theirs = f.get("ours"), f.get("theirs")
        keep.append(d)
    for d in old.values():
        db.delete(d)
    db.flush()
    db.refresh(wo)
    return keep


def resolve(
    db: Session,
    wo: ClientWorkOrder,
    dev: WoDeviation,
    action: str,
    note: str,
    amend_text: str | None,
    user,
) -> None:
    """Accept it, or ask the client to amend: a to-do for the salesperson with the text."""
    guard(wo)
    if action not in ("accept", "amend"):
        raise unprocessable("Accept it or ask the client to amend it")
    if not (note or "").strip():
        raise unprocessable("Write a note")
    dev.status = "accepted" if action == "accept" else "amend"
    dev.note = note
    dev.resolved_by, dev.resolved_at = user.id, now()
    if action == "amend":
        text = (
            amend_text
            or f"Please amend the work order {wo.client_ref or wo.code}: {dev.topic}. Our offer: {dev.ours or '—'}; the work order: {dev.theirs or '—'}."
        )
        dev.amend_text = text
        from app.process import engine  # noqa: PLC0415

        q = db.get(Quotation, wo.quotation_id) if wo.quotation_id else None
        engine.emit(db, "wo_amend", subject=f"wodev:{dev.id}", site_id=wo.site_id, actor_id=user.id,
                    data={"wo": wo.code, "wo_id": wo.id, "topic": dev.topic, "text": text, "salesperson_id": q.salesperson_id if q else None})  # fmt: skip
    db.flush()


def accept(db: Session, wo: ClientWorkOrder, user) -> None:
    guard(wo)
    open_ = [d for d in wo.deviations if d.status == "open"]
    if open_:
        raise unprocessable(
            f"{len(open_)} deviation(s) still open: accept each or ask the client to amend it"
        )
    if not wo.lines:
        raise unprocessable("The work order has no lines")
    wo.status, wo.accepted_by, wo.accepted_at = "accepted", user.id, now()
    db.flush()
    apply_to_contract(db, wo)


def apply_to_contract(db: Session, wo: ClientWorkOrder) -> int:
    """The accepted work order rules what follows: each of its lines gives the site's contract
    line (matched by the quotation line, else by the wording) its unit, rate and quantity, so
    the measurement book, the RA bills and the certificate use them."""
    from app.closeout.sizes import unit_code  # noqa: PLC0415
    from app.finance.models import ClientContract  # noqa: PLC0415

    if wo.status != "accepted" or not wo.site_id:
        return 0
    c = db.scalar(select(ClientContract).where(ClientContract.site_id == wo.site_id))
    if c is None:
        return 0
    free = [cl for cl in c.lines if cl.wo_line_id is None or cl.wo_line_id in {wl.id for wl in wo.lines}]
    n = 0
    for wl in wo.lines:
        ql = db.get(QuotationLine, wl.quotation_line_id) if wl.quotation_line_id else None
        cands = sorted(((max(_sim(wl.description, cl.description), _sim(ql.description, cl.description) if ql else 0.0), cl) for cl in free), key=lambda x: -x[0])
        if not cands or cands[0][0] < 0.3:
            continue
        cl = cands[0][1]
        free.remove(cl)
        cl.wo_line_id = wl.id
        if wl.unit:
            cl.unit = unit_code(wl.unit)
        if wl.rate is not None:
            cl.rate = wl.rate
        if wl.qty is not None:
            cl.qty = wl.qty
        n += 1
    db.flush()
    return n
