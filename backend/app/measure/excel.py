# ruff: noqa: E501  (cell layouts read better unwrapped)
"""The measurement sheet as Excel, with live formulas (Qty = No × L × H, Total = ROUND(Qty × 10.7639, 3)
for sqft, the abstract per item by SUMIF), and reading old Excel sheets and proformas back.

`evaluate` works out the formulas this file writes (and the usual ones in old sheets: + - * / ^,
ROUND, SQRT, SUM, SUMIF, cell references): the tests check the workbook's totals against the app's,
and an old file saved without its calculated values can still be read."""

import io
import re
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.measure import geom
from app.measure.models import MeasureLine

HEAD = ["Sr / WO item", "Particulars", "No", "Length (m)", "Width (m)", "Height / Depth (m)", "Qty", "Total qty", "Unit"]
FIRST = 7  # the first line's row
DASH = "–"


def _f(v) -> float | None:
    return None if v is None else float(Decimal(v))


def _qty_formula(r: int, ln: MeasureLine) -> str | float:
    sign = "-" if ln.kind == "deduction" else ""
    if ln.part == "walls" and ln.height_m is not None and ln.width_m is None:
        return f"={sign}C{r}*D{r}*F{r}"
    if ln.part == "tops":
        return f"={sign}C{r}*D{r}*E{r}"
    if ln.part == "count":
        return f"=C{r}"
    if ln.part == "walls" and ln.length_m is not None:
        return f"={sign}C{r}*D{r}"
    return _f(ln.qty)  # an outline's own area (or a slope face, written below with its formula)


def _total_formula(r: int, unit: str | None) -> str:
    u = (unit or "").strip().lower()
    if u == "sqft":
        return f"=ROUND(G{r}*$K$3,3)"
    if u == "rft":
        return f"=ROUND(G{r}/0.3048,3)"
    return f"=ROUND(G{r},3)"


def export(sheet, site, lines: list[MeasureLine], cumulative: list[dict], areas: dict, slope: dict, company: str) -> bytes:
    """The billing team's layout: the area's header line, then its lines; deductions negative with
    their reason; the abstract per work-order item (previous, this bill, up to date)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet.code[:31]
    bold = Font(bold=True)
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws["A1"], ws["A1"].font = company, Font(bold=True, size=13)
    ws["A2"], ws["A2"].font = "MEASUREMENT SHEET", bold
    ws["A3"] = f"Site: {site.code} {site.name}"
    ws["D3"] = f"Sheet {sheet.code} · measured on {sheet.measured_on:%d-%m-%Y}"
    ws["J3"], ws["K3"], ws["L3"] = "1 sqm =", float(geom.SQFT_PER_SQM), "sqft"
    ws["J3"].font = ws["K3"].font = bold
    ws["A4"] = "Quantities from the drawing at full precision; each line's total rounded to 3 decimals (half up, never truncated)."
    for i, h in enumerate(HEAD, start=1):
        c = ws.cell(row=6, column=i, value=h)
        c.font, c.border = bold, box
        c.fill = PatternFill("solid", fgColor="DDE7E1")
    ws.cell(row=6, column=10, value="item key").font = Font(color="999999")
    r = FIRST
    for ln in lines:
        if ln.kind == "area":
            ws.cell(row=r, column=2, value=ln.particulars).font = bold
            r += 1
            continue
        ws.cell(row=r, column=1, value=ln.item_no)
        text = ln.particulars + (f" — {ln.reason}" if ln.kind == "deduction" and ln.reason else "")
        ws.cell(row=r, column=2, value=text).alignment = Alignment(wrap_text=True, vertical="top")
        if ln.kind == "not_done":
            ws.cell(row=r, column=7, value=DASH)
            ws.cell(row=r, column=8, value=DASH)
        else:
            ws.cell(row=r, column=3, value=_f(ln.no))
            ws.cell(row=r, column=4, value=_f(ln.length_m))
            ws.cell(row=r, column=5, value=_f(ln.width_m))
            ws.cell(row=r, column=6, value=_f(ln.height_m))
            q = _qty_formula(r, ln)
            if ln.part == "slope" and ln.area_id in slope:
                plan, rise, run = slope[ln.area_id]
                q = f"={plan!r}*SQRT({rise!r}^2+{run!r}^2)/{run!r}"
            ws.cell(row=r, column=7, value=q)
            ws.cell(row=r, column=8, value=_total_formula(r, ln.unit))
        ws.cell(row=r, column=9, value=ln.unit)
        ws.cell(row=r, column=10, value=f"wo:{ln.wo_line_id}" if ln.wo_line_id else None).font = Font(color="999999")
        for col in range(3, 9):
            ws.cell(row=r, column=col).number_format = "0.000" if col == 8 else "0.0000"
        r += 1
    last = r - 1
    r += 1
    ws.cell(row=r, column=1, value="Abstract").font = bold
    r += 1
    for i, h in enumerate(["WO item", "Description", "Unit", "Previous", "This bill", "Up to date", "WO qty", "Rate", "This bill ₹"], start=1):
        c = ws.cell(row=r, column=i, value=h)
        c.font, c.border = bold, box
    r += 1
    abstract_first = r
    for row in cumulative:
        ws.cell(row=r, column=1, value=row["item_no"])
        ws.cell(row=r, column=2, value=(row["description"] or "")[:200]).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=3, value=row["unit"])
        ws.cell(row=r, column=4, value=_f(row["previous"]))
        ws.cell(row=r, column=5, value=f'=SUMIF($J${FIRST}:$J${max(last, FIRST)},"wo:{row["wo_line_id"]}",$H${FIRST}:$H${max(last, FIRST)})')
        ws.cell(row=r, column=6, value=f"=D{r}+E{r}")
        ws.cell(row=r, column=7, value=_f(row["wo_qty"]))
        ws.cell(row=r, column=8, value=_f(row["rate"]))
        ws.cell(row=r, column=9, value=f"=ROUND(E{r}*H{r},2)")
        for col in (4, 5, 6, 7):
            ws.cell(row=r, column=col).number_format = "0.000"
        ws.cell(row=r, column=9).number_format = "#,##0.00"
        r += 1
    ws.cell(row=r, column=8, value="Basic").font = bold
    ws.cell(row=r, column=9, value=f"=SUM(I{abstract_first}:I{r - 1})").font = bold
    ws.cell(row=r, column=9).number_format = "#,##0.00"
    for col, w in zip("ABCDEFGHIJKL", (12, 60, 7, 11, 10, 13, 12, 12, 8, 10, 9, 6), strict=True):
        ws.column_dimensions[col].width = w
    ws.column_dimensions["J"].hidden = True
    ws.freeze_panes = "C7"
    ws.print_title_rows = "6:6"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- formulas ------------------------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)|("(?:[^"]|"")*")|(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)|([A-Z]+(?=\())|(\*\*|[-+*/^(),:<>=&]))')


def _col(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def _ref(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", s)
    return int(m.group(2)), _col(m.group(1))


class _Eval:
    def __init__(self, ws):
        self.ws, self.cache, self.busy = ws, {}, set()

    def cell(self, row: int, col: int):
        k = (row, col)
        if k in self.cache:
            return self.cache[k]
        if k in self.busy:
            raise ValueError("circular reference")
        v = self.ws.cell(row=row, column=col).value
        if isinstance(v, str) and v.startswith("="):
            self.busy.add(k)
            v = self.formula(v[1:])
            self.busy.discard(k)
        self.cache[k] = v
        return v

    def num(self, v) -> float:
        if v is None or v == "":
            return 0.0
        if isinstance(v, int | float):
            return float(v)
        try:
            return float(str(v).replace(",", ""))
        except ValueError:
            return 0.0

    def formula(self, text: str):
        saved = getattr(self, "toks", None), getattr(self, "i", 0)  # a cell it refers to has its own
        self.toks = [next(t for t in m.groups() if t is not None) for m in _TOKEN.finditer(text) if m.group(0).strip()]
        self.i = 0
        try:
            return self.expr()
        finally:
            self.toks, self.i = saved

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            w = self.term()
            v = self.num(v) + self.num(w) if op == "+" else self.num(v) - self.num(w)
        return v

    def term(self):
        v = self.power()
        while self.peek() in ("*", "/"):
            op = self.take()
            w = self.power()
            v = self.num(v) * self.num(w) if op == "*" else self.num(v) / self.num(w)
        return v

    def power(self):
        v = self.unary()
        while self.peek() == "^":
            self.take()
            v = self.num(v) ** self.num(self.unary())
        return v

    def unary(self):
        if self.peek() == "-":
            self.take()
            return -self.num(self.unary())
        if self.peek() == "+":
            self.take()
            return self.num(self.unary())
        return self.atom()

    def atom(self):
        t = self.take()
        if t == "(":
            v = self.expr()
            self.take()
            return v
        if t[0].isdigit():
            return float(t)
        if t.startswith('"'):
            return t[1:-1].replace('""', '"')
        if self.peek() == "(" and re.fullmatch(r"[A-Z]+", t):
            self.take()
            args = []
            while self.peek() != ")":
                args.append(self.arg())
                if self.peek() == ",":
                    self.take()
            self.take()
            return self.call(t, args)
        if ":" in t:
            return self.range(t)
        return self.cell(*_ref(t))

    def arg(self):
        t = self.peek()
        if t and ":" in t and re.fullmatch(r"\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+", t):
            self.take()
            return self.range(t)
        return self.expr()

    def range(self, t: str) -> list:
        a, b = t.split(":")
        (r1, c1), (r2, c2) = _ref(a), _ref(b)
        return [self.cell(r, c) for r in range(min(r1, r2), max(r1, r2) + 1) for c in range(min(c1, c2), max(c1, c2) + 1)]

    def call(self, name: str, args: list):
        if name == "ROUND":
            x, n = self.num(args[0]), int(self.num(args[1]))
            q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding="ROUND_HALF_UP")
            return float(q)
        if name == "SQRT":
            return self.num(args[0]) ** 0.5
        if name == "SUM":
            return sum(self.num(v) for a in args for v in (a if isinstance(a, list) else [a]) if not isinstance(v, str) or v.strip())
        if name == "SUMIF":
            keys, crit, vals = args[0], args[1], args[2] if len(args) > 2 else args[0]
            return sum(self.num(v) for k, v in zip(keys, vals, strict=False) if k == crit)
        if name == "ABS":
            return abs(self.num(args[0]))
        raise ValueError(f"{name} is not read")


def evaluate(ws, row: int, col: int):
    """A cell's value, its formula worked out (the cells it refers to as well)."""
    return _Eval(ws).cell(row, col)


# --- reading old sheets --------------------------------------------------------------------------

_HEADS = {
    "item": ("sr / wo item", "wo item", "item no", "item", "sr no", "sr. no", "sr", "s no", "s.no", "sl no"),
    "particulars": ("particulars", "description", "details"),
    "no": ("no", "nos", "no."),
    "length": ("length", "length (m)", "l"),
    "width": ("width", "width (m)", "breadth", "b", "w"),
    "height": ("height / depth (m)", "height/depth", "height", "depth", "h"),
    "qty": ("qty", "quantity"),
    "total": ("total qty", "total quantity", "total"),
    "unit": ("unit",),
    "rate": ("rate",),
    "amount": ("amount", "amount (rs)", "amount ₹", "this bill ₹"),
    "previous": ("previous", "previous qty"),
    "this": ("this bill", "this bill qty", "present"),
    "upto": ("up to date", "upto date", "cumulative", "total up to date"),
}


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _header(ws, need: tuple[str, ...]) -> tuple[int, dict[str, int]] | None:
    for r in range(1, min(ws.max_row, 40) + 1):
        cols: dict[str, int] = {}
        for c in range(1, min(ws.max_column, 30) + 1):
            h = _norm(ws.cell(row=r, column=c).value)
            for key, names in _HEADS.items():
                if h in names and key not in cols:
                    cols[key] = c
        if all(k in cols for k in need):
            return r, cols
    return None


def _value(ev: _Eval, ws, r: int, c: int | None):
    if c is None:
        return None
    v = ws.cell(row=r, column=c).value
    if isinstance(v, str) and v.startswith("="):
        try:
            v = ev.cell(r, c)
        except Exception:  # noqa: BLE001
            return None
    return v


def _number(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return Decimal(repr(float(v))) if isinstance(v, float) else Decimal(v)
    s = str(v).replace(",", "").replace("₹", "").strip()
    try:
        return Decimal(s) if s and s not in ("-", DASH) else None
    except ArithmeticError:
        return None


def _item_no(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _workbooks(data: bytes):
    """The calculated values where the file has them; the formulas to work out where not."""
    return load_workbook(io.BytesIO(data), data_only=True), load_workbook(io.BytesIO(data))


def read_sheet(data: bytes) -> dict:
    """An old measurement sheet: the total per work-order item (the lines under each item, the
    area headers and the total rows not added), and every row with a number that could not be
    placed."""
    try:
        values, formulas = _workbooks(data)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("This is not an Excel workbook (.xlsx) that can be read") from exc
    items: dict[str, dict] = {}
    skipped: list[str] = []
    assumed: list[str] = []  # a line with no item number, counted under the item above it
    for name in values.sheetnames:
        ws, wf = values[name], formulas[name]
        found = _header(ws, ("particulars", "qty"))
        if not found:
            skipped.append(f"Sheet '{name}': no header row with Particulars and Qty")
            continue
        hr, cols = found
        ev = _Eval(wf)
        current = None
        for r in range(hr + 1, ws.max_row + 1):
            part = str(ws.cell(row=r, column=cols["particulars"]).value or "").strip()
            first = _norm(ws.cell(row=r, column=1).value)
            if first.startswith(("abstract", "summary")) or _norm(part).startswith(("abstract", "summary")):
                break  # the abstract repeats the totals: not added again
            item = _item_no(ws.cell(row=r, column=cols["item"]).value) if "item" in cols else None
            total = None
            for key in ("total", "qty"):
                v = ws.cell(row=r, column=cols[key]).value if key in cols else None
                if v is None and key in cols:
                    v = _value(ev, wf, r, cols[key])
                total = _number(v)
                if total is not None or (isinstance(v, str) and v.strip() in ("-", DASH)):
                    break
            numbers = [x for x in (total,) if x is not None]
            if _norm(part).startswith(("total", "sub total", "subtotal", "grand total", "net total")):
                continue
            if not numbers:
                if part and not item:
                    current = None  # an area's header: the item comes with its lines
                elif item:
                    current = item
                continue
            if not item and current:
                assumed.append(f"Sheet '{name}' row {r}: no item number, counted under item {current} (the line above): {part[:50]}")
            item = item or current
            if not item:
                skipped.append(f"Sheet '{name}' row {r}: {total} with no work-order item ({part[:60] or 'no particulars'})")
                continue
            current = item
            unit = str(ws.cell(row=r, column=cols["unit"]).value or "").strip() if "unit" in cols else ""
            row = items.setdefault(item, {"item_no": item, "description": part, "unit": unit, "qty": Decimal(0), "rows": 0})
            row["qty"] += total
            row["rows"] += 1
            row["unit"] = row["unit"] or unit
    return {"items": items, "skipped": skipped, "assumed": assumed}


def read_proforma(data: bytes) -> dict:
    """An old proforma: per item its quantity (up to date where the bill shows it, else this
    bill's), rate and amount; the basic and the grand total as printed."""
    try:
        values, formulas = _workbooks(data)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("This is not an Excel workbook (.xlsx) that can be read") from exc
    items: dict[str, dict] = {}
    skipped: list[str] = []
    basic = grand = None
    for name in values.sheetnames:
        ws, wf = values[name], formulas[name]
        found = _header(ws, ("rate", "amount"))
        if not found:
            continue
        hr, cols = found
        ev = _Eval(wf)
        qcol = cols.get("upto") or cols.get("qty") or cols.get("this")
        for r in range(hr + 1, ws.max_row + 1):
            label = " ".join(_norm(ws.cell(row=r, column=c).value) for c in range(1, min(ws.max_column, 12) + 1))
            amount = _number(_value(ev, wf, r, cols["amount"]))
            if amount is None:
                # a total printed in the last number of its row
                nums = [_number(_value(ev, wf, r, c)) for c in range(1, min(ws.max_column, 14) + 1)]
                nums = [n for n in nums if n is not None]
                amount = nums[-1] if nums else None
            if "grand total" in label or "total amount" in label or "invoice total" in label:
                grand = amount if amount is not None else grand
                continue
            if any(w in label for w in ("basic", "taxable", "sub total", "subtotal")) or re.search(r"(^| )total( |$)", label):
                basic = amount if amount is not None and basic is None else basic
                continue
            if any(w in label for w in ("cgst", "sgst", "igst", "round off", "round-off", "gst")):
                continue
            item = _item_no(ws.cell(row=r, column=cols["item"]).value) if "item" in cols else None
            qty = _number(_value(ev, wf, r, qcol)) if qcol else None
            rate = _number(_value(ev, wf, r, cols["rate"]))
            if item and qty is not None and rate is not None:
                desc = str(ws.cell(row=r, column=cols["particulars"]).value or "").strip() if "particulars" in cols else ""
                unit = str(ws.cell(row=r, column=cols["unit"]).value or "").strip() if "unit" in cols else ""
                items[item] = {"item_no": item, "description": desc, "unit": unit, "qty": qty, "rate": rate, "amount": amount}
            elif amount is not None or qty is not None:
                raw = " ".join(str(v) for c in range(1, min(ws.max_column, 12) + 1) if (v := ws.cell(row=r, column=c).value) is not None)
                skipped.append(f"Sheet '{name}' row {r}: {raw[:80]} (no item number, or no quantity and rate)")
    return {"items": items, "basic": basic, "grand": grand, "skipped": skipped}


def match(items: dict[str, dict], wo_lines) -> tuple[dict[int, dict], list[str]]:
    """The read items to work-order lines: by item number, else by the start of the description."""
    by_no = {_norm(w.item_no): w for w in wo_lines if w.item_no}
    out: dict[int, dict] = {}
    skipped = []
    for key, it in items.items():
        w = by_no.get(_norm(key)) or by_no.get(_norm(key).rstrip(".0") if _norm(key).endswith(".0") else "")
        if w is None and it.get("description"):
            d = _norm(it["description"])[:25]
            w = next((x for x in wo_lines if d and _norm(x.description).startswith(d)), None)
        if w is None:
            skipped.append(f"Item {key} ({(it.get('description') or '')[:50]}): not on the work order")
            continue
        if w.id in out:
            out[w.id]["qty"] += it["qty"]
        else:
            out[w.id] = dict(it)
    return out, skipped
