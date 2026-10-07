"""Client BOQs that arrive as PDF: turned into the same rows an Excel sheet gives, so the one
parser (boq_import.parse) applies unchanged.

Library: pdfplumber. It is pure Python (pdfminer.six underneath), so it runs in the API image
without Java (tabula) or Ghostscript/OpenCV (camelot), and it exposes every table cell's
bounding box, which is what merged-cell handling below needs.

How a PDF becomes rows:
1. Each page's ruled tables are found (falling back to text alignment when a PDF has no ruling
   at all). Text is read with a 1 pt character gap so tightly set words stay apart.
2. The BOQ table is the one with the best header (same header detection as Excel). On later
   pages, a table with the same number of columns at the same x-positions (±8 pt) continues it;
   other tables are ignored, except a terms & conditions table, which is kept so the parser's
   T&C cut-off still applies.
3. Merged cells: a cell that spans several rows (an item's S.No / unit / qty / rate printed in
   the middle of a long description) turns the rows it covers into one row: the description
   paragraphs are joined, the other columns take the spanning cell's text. This is what an
   Excel merged cell gives: one value for the block.
4. Page breaks: a continuation table's repeated title/header rows are dropped. Values printed in
   a repeated header row (an item cut by the page break, with its figures centred across the
   break) are carried into that item. A block at the bottom of a page whose figures are not on
   that page (no S.No / unit / qty / rate cell) is joined to the first block of the next page.

Scanned PDFs (no text layer) are refused: OCR is not supported yet.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_PAGES = 60
MIN_TEXT_CHARS = 30  # fewer characters than this in the whole file: no text layer
X_TOLERANCE = 1
SAME_COLUMN_PT = 8


class ScannedPdfError(ValueError):
    pass


@dataclass
class LogicalRow:
    cells: list[Any]
    first_page: int
    last_page: int
    open: bool = False  # the item's figures are not in this block (cut by a page break)


@dataclass
class _Table:
    page: int
    top: float
    texts: list[list[Any]]
    geometry: list[list[tuple | None]]  # per row, per column: cell bbox or None
    row_boxes: list[tuple[float, float]]  # per row: (top, bottom)
    col_x: list[float]

    @property
    def ncols(self) -> int:
        return len(self.col_x)


@dataclass
class PdfRows:
    rows: list[list[Any]]
    pages: list[tuple[int, int]]  # per row: first and last page it came from
    page_count: int
    tables: int = 0
    notes: list[str] = field(default_factory=list)


def _norm(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _table(page_no: int, table: Any) -> _Table | None:
    texts = table.extract(x_tolerance=X_TOLERANCE)
    if not texts or not texts[0]:
        return None
    ncols = max(len(r) for r in texts)
    texts = [list(r) + [None] * (ncols - len(r)) for r in texts]
    geometry = [list(r.cells) + [None] * (ncols - len(r.cells)) for r in table.rows]
    lefts: list[float] = []
    for c in range(ncols):
        xs = [row[c][0] for row in geometry if row[c] is not None]
        lefts.append(min(xs) if xs else (lefts[-1] if lefts else table.bbox[0]))
    return _Table(
        page_no, table.bbox[1], texts, geometry, [(r.bbox[1], r.bbox[3]) for r in table.rows], lefts
    )


def _read_tables(path: Path) -> tuple[list[_Table], int]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        count = len(pdf.pages)
        if count > MAX_PAGES:
            from app.tenders.boq_import import BoqFormatError

            raise BoqFormatError(f"The PDF has {count} pages; at most {MAX_PAGES} can be imported")
        chars = sum(len(p.chars) for p in pdf.pages)
        if chars < MIN_TEXT_CHARS:
            raise ScannedPdfError("Scanned PDF, OCR not supported yet")
        tables: list[_Table] = []
        for strategy in ({}, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
            for page_no, page in enumerate(pdf.pages, start=1):
                found = (
                    page.find_tables(table_settings=strategy) if strategy else page.find_tables()
                )
                for t in sorted(found, key=lambda t: t.bbox[1]):
                    parsed = _table(page_no, t)
                    if parsed:
                        tables.append(parsed)
            if tables:
                break
    return tables, count


def _same_layout(a: _Table, b: _Table) -> bool:
    return a.ncols == b.ncols and all(
        abs(x - y) <= SAME_COLUMN_PT for x, y in zip(a.col_x, b.col_x, strict=True)
    )


def _blocks(t: _Table, desc_col: int, key_cols: list[int]) -> list[LogicalRow]:
    """Rows covered by one multi-row cell become one row (see the module docstring)."""
    out: list[LogicalRow] = []
    n = len(t.texts)
    anchors = [c for c in range(t.ncols) if c != desc_col]
    i = 0
    while i < n:
        bottom = t.row_boxes[i][1]
        for c in anchors:
            cell = t.geometry[i][c]
            if cell is not None:
                bottom = max(bottom, cell[3])
        j = i
        while j + 1 < n and t.row_boxes[j + 1][0] < bottom - 1:
            j += 1
        cells: list[Any] = []
        for c in range(t.ncols):
            values = [t.texts[k][c] for k in range(i, j + 1)]
            if c == desc_col:
                parts = [" ".join(str(v).split()) for v in values if v not in (None, "")]
                cells.append(" ".join(parts) if parts else values[0])
            else:
                cells.append(next((v for v in values if v not in (None, "")), values[0]))
        is_open = bool(key_cols) and all(t.geometry[i][c] is None for c in key_cols)
        is_open = is_open and any(v not in (None, "") for v in cells)
        row = LogicalRow(cells, t.page, t.page, is_open)
        if is_open and out and out[-1].open:
            _merge_into(out[-1], row, desc_col)  # rows of one cut block (no figures on the page)
            out[-1].open = True
        else:
            out.append(row)
        i = j + 1
    return out


def _header_match(row: list[Any], head: list[Any]) -> tuple[bool, list[Any]]:
    """Is `row` a repeat of the header-area row `head`? Returns (match, leftover values)."""
    if [_norm(v) for v in row] == [_norm(v) for v in head]:
        return True, [None] * len(row)
    wanted = [(c, _norm(v)) for c, v in enumerate(head) if _norm(v)]
    if not wanted:
        return False, []
    hits = sum(1 for c, h in wanted if c < len(row) and h in _norm(row[c]))
    if hits < max(1, round(0.6 * len(wanted))):
        return False, []
    leftover: list[Any] = []
    for c, value in enumerate(row):
        h = _norm(head[c]) if c < len(head) else ""
        lines = [ln for ln in str(value or "").split("\n") if ln.strip()]
        rest = [ln for ln in lines if not (h and _norm(ln) and _norm(ln) in h)]
        leftover.append(" ".join(rest) if rest else None)
    return True, leftover


def _merge_into(target: LogicalRow, other: LogicalRow, desc_col: int) -> None:
    for c, value in enumerate(other.cells):
        if value in (None, ""):
            continue
        if c == desc_col:
            mine = target.cells[c]
            target.cells[c] = f"{mine} {value}" if mine not in (None, "") else value
        elif target.cells[c] in (None, ""):
            target.cells[c] = value
    target.last_page = max(target.last_page, other.last_page)
    target.open = target.open and other.open


def read_pdf(path: str | Path) -> PdfRows:
    from app.tenders.boq_import import TC_MARKER, BoqFormatError, detect_header

    tables, count = _read_tables(Path(path))
    if not tables:
        raise BoqFormatError("No table was found in the PDF")

    # the BOQ table: the best header among the tables
    scored = [(detect_header(t.texts), t) for t in tables]
    (h_index, columns, score), first = max(scored, key=lambda s: (s[0][2], -s[1].page, -s[1].top))
    if score <= 0:
        raise BoqFormatError("No BOQ table (description and unit / quantity columns) was found")
    desc_col = columns["description"]["column"]
    key_cols = [columns[f]["column"] for f in ("item_no", "unit", "qty", "rate") if f in columns]
    head_rows = first.texts[: h_index + 1]

    rows: list[LogicalRow] = []
    used = 0
    started = False
    for t in tables:
        if t is first:
            started = True
            rows.extend(_blocks(t, desc_col, key_cols))
            used += 1
            continue
        if not started or t.page < first.page:
            continue
        if _same_layout(t, first):
            blocks = _blocks(t, desc_col, key_cols)
            carry: list[Any] | None = None
            while blocks:
                match, leftover = False, []
                for head in head_rows:
                    match, leftover = _header_match(blocks[0].cells, head)
                    if match:
                        break
                if not match:
                    break
                blocks.pop(0)
                if any(v not in (None, "") for v in leftover):
                    carry = leftover
            if rows and rows[-1].open:
                if carry:
                    _merge_into(rows[-1], LogicalRow(carry, t.page, t.page), desc_col)
                if blocks:
                    _merge_into(rows[-1], blocks.pop(0), desc_col)
            elif carry and rows:
                _merge_into(rows[-1], LogicalRow(carry, t.page, t.page), desc_col)
            rows.extend(blocks)
            used += 1
        elif any(isinstance(v, str) and TC_MARKER.search(v) for r in t.texts for v in r):
            # a separate terms & conditions table: kept so the T&C cut-off applies
            for r in t.texts:
                cells = (list(r) + [None] * first.ncols)[: first.ncols]
                rows.append(LogicalRow(cells, t.page, t.page))
            used += 1
    return PdfRows(
        rows=[r.cells for r in rows],
        pages=[(r.first_page, r.last_page) for r in rows],
        page_count=count,
        tables=used,
    )
