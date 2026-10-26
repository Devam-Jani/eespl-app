# ruff: noqa: E501
"""A site's bills as a register, their revisions, the old Excel register and project folder read
back, and each bill's material check.

- Revisions: a bill is kept as R0, R1 ... as it was made (its lines and totals), from the app or
  from an old file ("Not for invoice", "revised"); one is the one sent to the client. The
  difference between revisions is shown line by line.
- The old register (the billing team's Excel) is read as written (its remarks, which name people,
  are not kept); the project folder's bill files are read for their RA number, dates, version and
  totals. Findings: numbers missing, a number used for two bills (or one bill under two numbers),
  a bill dated before a lower number, a date in another year than its folder, bills missing from
  the old register.
- The app's register: each RA bill of the site, its proforma or tax invoice number, date, basic,
  GST, total and what was received.
- Material check: what the bills up to this one need (their quantities x each item's system: the
  product's coverage) against what the site used (sent to its store, less what came back, less
  what is still there).
"""

import re
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.finance import service as svc
from app.finance.models import ClientContract, RaBill, ReceiptAllocation, TaxInvoice
from app.measure import excel, geom
from app.measure.models import BillRevision, RegisterImport

D = Decimal
_RA = re.compile(r"\bR\s*-?\s*A\s*-?\s*(\d{1,3})(?!\d)", re.I)
_DATE = re.compile(r"(\d{1,2})[ .\-_/]{1,3}(\d{1,2})[ .\-_/]{1,3}(\d{4})")
_NOISE = re.compile(r"\b(the|zown|zone|vaghpur|vagpur|waghpur|villa|final|revised|new|not|for|invoice|performa|proforma|drawing|only|drg|siddhraj|date|dated|slip|as|per)\b", re.I)


# --- revisions ----------------------------------------------------------------------------------


def snapshot(db: Session, b: RaBill) -> tuple[list[dict], D, D, D]:
    """The bill's lines and totals as they are now (this bill's quantities and amounts)."""
    from app.measure import bill as mb  # noqa: PLC0415

    if b.proforma_no:
        p = mb.proforma(db, b)
        lines = [{"item_no": ln["item_no"], "description": ln["description"][:120], "unit": ln["unit"], "qty": str(ln["this"]), "rate": str(ln["rate"]), "amount": str(ln["amount"])} for ln in p["lines"]]
        return lines, D(p["tax"]["taxable"]), D(p["tax"]["cgst"]) + D(p["tax"]["sgst"]) + D(p["tax"]["igst"]), D(p["tax"]["total"])
    c = db.get(ClientContract, b.contract_id)
    cl = {x.id: x for x in c.lines}
    lines = [{"item_no": cl[ln.contract_line_id].item_no, "description": cl[ln.contract_line_id].description[:120], "unit": cl[ln.contract_line_id].unit,
              "qty": str(ln.certified_qty if ln.certified_qty is not None else ln.qty), "rate": str(ln.rate), "amount": str(ln.certified_amount if ln.certified_amount is not None else ln.amount)}
             for ln in b.lines]  # fmt: skip
    basic = D(b.certified_gross if b.certified_gross is not None else b.gross)
    gst = svc.money(basic * D("0.18"))
    return lines, basic, gst, (basic + gst).quantize(D(1), ROUND_HALF_UP)


def add_revision(db: Session, b: RaBill, *, label: str | None, source: str | None, made_on: date | None, user_id=None,
                 lines: list[dict] | None = None, basic: D | None = None, gst: D | None = None, total: D | None = None) -> BillRevision:  # fmt: skip
    """A new revision of the bill: R0 first, never renumbered. Without lines given, the bill as it is now."""
    if lines is None:
        lines, basic, gst, total = snapshot(db, b)
    n = db.scalar(select(func.max(BillRevision.rev_no)).where(BillRevision.ra_bill_id == b.id))
    r = BillRevision(ra_bill_id=b.id, rev_no=0 if n is None else n + 1, label=label, source=source, made_on=made_on, lines=lines,
                     basic=basic or D(0), gst=gst or D(0), total=total or D(0), created_by=user_id)  # fmt: skip
    db.add(r)
    db.flush()
    return r


def mark_sent(db: Session, b: RaBill, rev: BillRevision) -> None:
    """The revision sent to the client: only one per bill."""
    for other in db.scalars(select(BillRevision).where(BillRevision.ra_bill_id == b.id, BillRevision.sent.is_(True))):
        other.sent = False
    db.flush()
    rev.sent = True
    db.flush()


def revisions(db: Session, b: RaBill) -> list[dict]:
    """Each revision with what changed from the one before it, line by line and in total."""
    out, before = [], None
    for r in db.scalars(select(BillRevision).where(BillRevision.ra_bill_id == b.id).order_by(BillRevision.rev_no)):
        changes = []
        if before is not None:
            old = {(ln.get("item_no") or ln.get("description")): ln for ln in before.lines}
            new = {(ln.get("item_no") or ln.get("description")): ln for ln in r.lines}
            for k in sorted(set(old) | set(new), key=str):
                o, n = old.get(k), new.get(k)
                oq, nq = D(o["qty"]) if o else D(0), D(n["qty"]) if n else D(0)
                oa, na = D(o["amount"]) if o else D(0), D(n["amount"]) if n else D(0)
                if oq != nq or oa != na:
                    changes.append({"item": k, "qty_before": oq, "qty_now": nq, "amount_before": oa, "amount_now": na, "amount_change": na - oa})
        out.append({"id": r.id, "rev": f"R{r.rev_no}", "label": r.label, "source": r.source, "made_on": r.made_on, "basic": r.basic, "gst": r.gst, "total": r.total, "sent": r.sent,
                    "lines": r.lines, "changes": changes, "basic_change": (r.basic - before.basic) if before is not None else None})  # fmt: skip
        before = r
    return out


# --- the project folder and the old register ------------------------------------------------------


def _date(text: str) -> date | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def subject(name: str) -> str:
    """What a bill is for, from its file name ("R.WALL PART 2", "FOREST SWIMMING POOL - A")."""
    s = Path(name).stem.upper()
    s = re.sub(r"\(\s*\d+[A-Z]?\s*\)", " ", s)  # the file's serial in its folder: (1), (4a)
    s = _RA.sub(" ", s)
    s = _DATE.sub(" ", s)
    s = re.sub(r"\(S[_\-]\S+\)", " ", s)  # the tax invoice reference (S_0117_11.06.2026)
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9.+ ]", " ", s)
    s = re.sub(r"\b\d+\b", lambda m: m.group(0) if m.group(0) in ("1", "2", "3") else " ", s)  # "PART 2" keeps its number
    return re.sub(r"\s+", " ", s).strip(" .")


def _workbook_date(data: bytes) -> date | None:
    """The bill's own date as written in it ("Invoice Date : 15.09.2026")."""
    import io  # noqa: PLC0415

    from openpyxl import load_workbook  # noqa: PLC0415

    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:  # noqa: BLE001
        return None
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=15):
            for c in row:
                v = c.value
                if isinstance(v, str) and re.search(r"(invoice|bill)\s+date", v, re.I):
                    d = _date(v)
                    if d:
                        return d
    return None


def scan(folder: Path) -> list[dict]:
    """Every bill file in the project folder: its RA number (from its name, else its folder's),
    the date in its name, its own date inside, its version (not for invoice, revised, final), what
    it is for, and its totals."""
    out = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith("~$") or p.suffix.lower() not in (".xlsx", ".pdf", ".dwg", ".jpeg", ".jpg"):
            continue
        rel = p.relative_to(folder).as_posix()
        own = _RA.search(p.name)
        parent = _RA.search(p.parent.name)
        not_for = bool(re.search(r"not\s*for\s*invoice", rel, re.I))
        version = "not for invoice" if not_for else "new revised" if re.search(r"new\s+revised", p.name, re.I) else "revised" if re.search(r"revised", p.name, re.I) else "final" if re.search(r"final", p.name, re.I) else None
        row = {"file": rel, "kind": p.suffix.lower().lstrip("."), "ra": int(own.group(1)) if own else None, "folder_ra": int(parent.group(1)) if parent else None,
               "name_date": _date(p.name) or _date(p.parent.name), "version": version, "subject": subject(p.name), "fy": next((x for x in rel.split("/") if x.upper().startswith("FROM ")), None)}  # fmt: skip
        if p.suffix.lower() == ".xlsx":
            data = p.read_bytes()
            try:
                pro = excel.read_proforma(data)
                row["basic"] = svc.money(pro["basic"]) if pro["basic"] is not None else None
                row["grand"] = svc.money(pro["grand"]) if pro["grand"] is not None else None
            except ValueError:
                row["basic"] = row["grand"] = None
            row["bill_date"] = _workbook_date(data)
        out.append(row)
    return out


def _fy_years(fy: str | None) -> tuple[int, int] | None:
    m = re.search(r"(\d{4}).*?(\d{4})", fy or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def findings(files: list[dict], register_rows: list[dict] | None = None) -> list[dict]:
    """What the folder (and the old register) show about the bills' numbering and records."""
    out: list[dict] = []
    bills = [f for f in files if f["kind"] == "xlsx" and (f["ra"] is not None or f["folder_ra"] is not None) and f["version"] != "not for invoice"]
    nums = sorted({f["ra"] if f["ra"] is not None else f["folder_ra"] for f in bills})
    if nums:
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        for n in missing:
            out.append({"kind": "missing", "ra": n, "text": f"RA {n} is missing: no bill file has that number (RA {n - 1} and RA {n + 1} are there)"})
    for f in files:
        if f["ra"] is not None and f["folder_ra"] is not None and f["ra"] != f["folder_ra"]:
            out.append({"kind": "clash", "ra": f["folder_ra"], "text": f"In the RA {f['folder_ra']} folder, '{Path(f['file']).name}' is numbered RA {f['ra']}"})
    by_subject: dict[str, set[int]] = {}
    for f in files:
        n = f["ra"] if f["ra"] is not None else f["folder_ra"]
        if n is not None and len(f["subject"].split()) >= 2:
            by_subject.setdefault(f["subject"], set()).add(n)
    # one bill under two numbers: the same subject, or one inside the other ("SWIMMING POOL A" in
    # "FOREST SWIMMING POOL A")
    seen: set[tuple] = set()
    for a, na in sorted(by_subject.items()):
        for b, nb in sorted(by_subject.items()):
            if a <= b and (a == b or f" {a} " in f" {b} " or f" {b} " in f" {a} "):
                ns = sorted(na | nb)
                key = (min(a, b, key=len), tuple(ns))
                if len(ns) > 1 and key not in seen:
                    seen.add(key)
                    out.append({"kind": "clash", "ra": ns[0], "text": f"'{key[0]}' is under {' and '.join(f'RA {n}' for n in ns)}"})
    dated = sorted(((f["ra"] if f["ra"] is not None else f["folder_ra"], f.get("bill_date") or f["name_date"], f["file"]) for f in bills if (f.get("bill_date") or f["name_date"])), key=lambda x: x[0])
    for i, (n, d, _name) in enumerate(dated):
        later_lower = [(m, e) for m, e, _ in dated[:i] if m < n and e > d]
        if later_lower:
            lows = sorted({m for m, _ in later_lower})
            out.append({"kind": "order", "ra": n, "text": f"RA {n} is dated {d:%d.%m.%Y}, before RA {', '.join(map(str, lows))} (dated later)"})
    for f in bills:
        yrs = _fy_years(f["fy"])
        d = f.get("bill_date")
        if yrs and d and not (date(yrs[0], 4, 1) <= d <= date(yrs[1], 3, 31)):
            n = f["ra"] if f["ra"] is not None else f["folder_ra"]
            out.append({"kind": "year", "ra": n, "text": f"RA {n} is dated {d:%d.%m.%Y} inside, but it is in the folder {f['fy']}"})
        if d and f["name_date"] and d != f["name_date"]:
            n = f["ra"] if f["ra"] is not None else f["folder_ra"]
            out.append({"kind": "date", "ra": n, "text": f"RA {n}: its name says {f['name_date']:%d.%m.%Y}, its own date is {d:%d.%m.%Y}"})
    if register_rows is not None:
        matched = {r.get("ra") for r in register_rows if r.get("ra") is not None}
        # a register row with no bill of the same basic: the bill of the same date, another version
        for r in register_rows:
            if r.get("ra") is None and r.get("date"):
                when = r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))
                same = [f for f in bills if (f.get("bill_date") or f["name_date"]) == when]
                for f in same:
                    n = f["ra"] if f["ra"] is not None else f["folder_ra"]
                    out.append({"kind": "register", "ra": n, "text": f"The old register lists '{r['description']}' of {when:%d.%m.%Y} at {r['basic']}; RA {n} of that date says {f.get('basic')} (another version)"})
        absent = [n for n in nums if n not in matched]
        if absent:
            out.append({"kind": "register", "ra": None, "text": f"Missing from the old register: {', '.join(f'RA {n}' for n in absent)}"})
    return out


def read_register(data: bytes) -> list[dict]:
    """The billing team's register (Excel): each bill's description, status (tax invoice or
    proforma), date, invoice number, basic and total with tax. Remarks are not kept (they name
    people)."""
    import io  # noqa: PLC0415

    from openpyxl import load_workbook  # noqa: PLC0415

    wb = load_workbook(io.BytesIO(data), data_only=True)
    rows = []
    for ws in wb.worksheets:
        cols: dict[str, int] = {}
        for r in range(1, ws.max_row + 1):
            vals = [ws.cell(r, c).value for c in range(1, min(ws.max_column, 12) + 1)]
            heads = [str(v or "").strip().lower() for v in vals]
            if "description" in heads and any(h.startswith("basic") for h in heads):
                cols = {h: i + 1 for i, h in enumerate(heads) if h}
                continue
            if not cols:
                continue
            desc = ws.cell(r, cols.get("description", 2)).value
            basic = ws.cell(r, next((i for h, i in cols.items() if h.startswith("basic")), 6)).value
            if not desc or not isinstance(basic, int | float):
                continue
            total = ws.cell(r, next((i for h, i in cols.items() if h.startswith("tax amount")), 8)).value
            when = ws.cell(r, cols.get("date", 4)).value
            rows.append({"description": str(desc).strip(), "status": str(ws.cell(r, cols.get("status", 3)).value or "").strip(),
                         "date": when.date() if isinstance(when, datetime) else _date(str(when or "")), "invoice_no": str(ws.cell(r, cols.get("invoice no.", 5)).value or "").strip() or None,
                         "basic": svc.money(D(repr(basic))), "total": svc.money(D(repr(total))) if isinstance(total, int | float) else None})  # fmt: skip
    return rows


def match_register(rows: list[dict], files: list[dict]) -> list[dict]:
    """Each register row's RA number: the bill file with the same basic (to the rupee)."""
    finals = [f for f in files if f["kind"] == "xlsx" and f.get("basic") is not None and f["version"] != "not for invoice"]
    for r in rows:
        hit = next((f for f in finals if abs(D(f["basic"]) - D(r["basic"])) <= 1), None)
        r["ra"] = (hit["ra"] if hit["ra"] is not None else hit["folder_ra"]) if hit else None
        r["file"] = hit["file"] if hit else None
    return rows


def import_folder(db: Session, site, folder: Path, register_file: Path | None, user_id=None) -> RegisterImport:
    files = scan(folder)
    rows = match_register(read_register(register_file.read_bytes()), files) if register_file else []
    found = findings(files, rows if register_file else None)

    def plain(v):
        return v.isoformat() if isinstance(v, date) else str(v) if isinstance(v, Decimal) else v

    imp = RegisterImport(site_id=site.id, source=folder.name, rows=[{k: plain(v) for k, v in r.items()} for r in rows],
                         files=[{k: plain(v) for k, v in f.items()} for f in files], findings=found, created_by=user_id)  # fmt: skip
    db.add(imp)
    db.flush()
    return imp


# --- the app's register ---------------------------------------------------------------------------


def old_number(text: str | None) -> int | None:
    """The RA number in an old file's name or a slip's key ("RA 16", "R A - 16", "RA-16")."""
    m = re.search(r"\bR\s*\.?\s*A\s*[-.]?\s*(\d+)\b", text or "", re.I)
    return int(m.group(1)) if m else None


def site_register(db: Session, site_id: int, q: str | None = None) -> dict:
    """Each RA bill of the site in order, with its proforma or tax invoice, date, totals, what was
    received, its revisions, its number in the old files when the app numbered it otherwise; the
    old register beside it. q: only the bills whose number (the app's or the old one) has it."""
    out = []
    old = db.scalar(select(RegisterImport).where(RegisterImport.site_id == site_id).order_by(RegisterImport.id.desc()).limit(1))
    old_by_ra = {r.get("ra"): r for r in (old.rows if old else []) if r.get("ra") is not None}
    want = old_number(q) if q else None
    for b in db.scalars(select(RaBill).where(RaBill.site_id == site_id).order_by(RaBill.seq)):
        if q and not (q.lower() in b.code.lower() or (b.old_no and q.lower() in b.old_no.lower()) or (want is not None and (b.seq == want or old_number(b.old_no) == want))):
            continue
        inv = db.scalar(select(TaxInvoice).where(TaxInvoice.ra_bill_id == b.id))
        basic = D(inv.taxable) if inv else D(b.certified_gross if b.certified_gross is not None else b.gross)
        gst = (D(inv.cgst) + D(inv.sgst) + D(inv.igst)) if inv else svc.money(basic * D("0.18"))
        total = D(inv.total) if inv else (basic + gst).quantize(D(1), ROUND_HALF_UP)
        paid = D(db.scalar(select(func.coalesce(func.sum(ReceiptAllocation.amount), 0)).where(ReceiptAllocation.invoice_id == inv.id)) or 0) if inv else D(0)
        reg = old_by_ra.get(b.seq)
        revs = list(db.scalars(select(BillRevision).where(BillRevision.ra_bill_id == b.id).order_by(BillRevision.rev_no)))
        out.append({"id": b.id, "ra": b.seq, "code": b.code, "status": b.status, "imported": b.imported, "kind": "tax invoice" if inv else ("proforma" if b.proforma_no else (reg or {}).get("status") or "bill"),
                    "number": inv.number if inv else b.proforma_no or (reg or {}).get("invoice_no"), "date": (inv.invoice_date if inv else b.proforma_on or b.period_to),
                    "basic": basic, "gst": gst, "total": total, "paid": paid, "in_old_register": reg is not None, "revisions": len(revs), "sent_revision": next((f"R{r.rev_no}" for r in revs if r.sent), None),
                    "old_no": b.old_no, "was": f"was {b.old_no} in the old files" if b.old_no else None})  # fmt: skip
    return {"bills": out, "old": old.rows if old else [], "findings": old.findings if old else [], "source": old.source if old else None}


# --- the material check ---------------------------------------------------------------------------


def material_check(db: Session, b: RaBill) -> dict:
    """What the bills up to this one need of each product (their sqm x the item's system coverage)
    against what the site used by the bill's date (sent to its store, less returned, less still
    there): the variance, as the billing team's reconciliation sheet."""
    from app.closeout.models import ClientWorkOrderLine  # noqa: PLC0415
    from app.finance.models import ContractLine, RaBillLine  # noqa: PLC0415
    from app.masters.models import Product, SystemComponent  # noqa: PLC0415
    from app.material.models import StockLedger, Store  # noqa: PLC0415

    bills = list(db.scalars(select(RaBill).where(RaBill.site_id == b.site_id, RaBill.seq <= b.seq, RaBill.status != "cancelled")))
    need: dict[int, dict] = {}
    for bb in bills:
        for ln in db.scalars(select(RaBillLine).where(RaBillLine.ra_bill_id == bb.id)):
            cl = db.get(ContractLine, ln.contract_line_id)
            w = db.get(ClientWorkOrderLine, cl.wo_line_id) if cl and cl.wo_line_id else None
            if w is None or w.system_id is None:
                continue
            q = D(ln.certified_qty if ln.certified_qty is not None else ln.qty)
            if not q:
                continue
            u = (w.unit or "").lower()
            sqm = q / geom.SQFT_PER_SQM if u == "sqft" else q if u == "sqm" else None
            if sqm is None:
                continue
            for comp in db.scalars(select(SystemComponent).where(SystemComponent.system_id == w.system_id)):
                if comp.consumption_per_unit is None:
                    continue
                row = need.setdefault(comp.product_id, {"needed": D(0), "from": []})
                row["needed"] += sqm * D(comp.consumption_per_unit)
                row["from"].append(f"{bb.code} item {w.item_no}: {svc.money(sqm)} sqm × {D(comp.consumption_per_unit).normalize():f}")
    store = db.scalar(select(Store).where(Store.site_id == b.site_id))
    until = datetime.combine(b.proforma_on or b.period_to, time.max).astimezone()
    rows = []
    for pid, row in need.items():
        p = db.get(Product, pid)
        sent = back = stock = D(0)
        if store is not None:
            q = select(StockLedger.ref_type, func.coalesce(func.sum(StockLedger.qty), 0)).where(StockLedger.store_id == store.id, StockLedger.product_id == pid, StockLedger.at <= until).group_by(StockLedger.ref_type)
            got = {k: D(v) for k, v in db.execute(q)}
            sent = got.get("transfer_in", D(0)) + got.get("grn", D(0)) + got.get("opening", D(0))
            back = -got.get("transfer_out", D(0))
            stock = sum(got.values(), D(0))
        used = sent - back - stock
        needed = row["needed"].quantize(D("0.01"))
        rows.append({"product": p.name if p else str(pid), "unit": p.unit if p else None, "needed": needed, "sent": sent, "returned": back, "site_stock": stock, "used": used,
                     "variance": used - needed, "variance_percent": ((used - needed) / needed * 100).quantize(D("0.1")) if needed else None, "from": row["from"]})  # fmt: skip
    return {"bill": b.code, "until": (b.proforma_on or b.period_to), "rows": rows, "store": store.name if store else None,
            "note": None if store else "The site has no store: what was used is not known"}
