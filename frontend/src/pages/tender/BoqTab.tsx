import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr, num } from "../../format";
import { RATE_POLICIES } from "../../types";
import type { Boq, BoqLine, LineDetail, RateHistory, SuggestResult, Tender } from "../../types";
import ImportWizard from "./ImportWizard";
import { useLearned } from "../../sitecontrol/learned";

type Col = {
  key: string;
  label: string;
  editable: (line: BoqLine) => boolean;
  num?: boolean;
  cost?: boolean;
  muted?: boolean;
  width?: string;
};

const STATUS_LABEL: Record<string, string> = {
  unpriced: "Unpriced",
  suggested: "Suggested",
  priced: "Priced",
  not_quoted: "NQ",
};
const STATUS_BADGE: Record<string, string> = {
  unpriced: "badge-muted",
  suggested: "badge-warn",
  priced: "badge-ok",
  not_quoted: "badge-danger",
};

type Row = { kind: "section"; id: number; title: string; note: string | null; total: string } | { kind: "line"; line: BoqLine };

/** Text shown (and edited) in a cell. */
function cellText(line: BoqLine, key: string): string {
  switch (key) {
    case "client_item_no":
      return line.client_item_no ?? "";
    case "description":
      return line.description;
    case "unit":
      return line.unit ?? line.unit_raw ?? "";
    case "qty":
      return line.qty_note === "QRO" ? "QRO" : line.qty_note === "NQ" ? "NQ" : line.qty ? num(line.qty, 3) : "";
    case "rate":
      return line.rate ?? "";
    case "amount":
      return line.amount ?? "";
    case "our_remarks":
      return line.our_remarks ?? "";
    case "our_product":
      return line.our_product ?? "";
    case "manufacturer":
      return line.manufacturer ?? "";
    case "client_remarks":
      return line.client_remarks ?? "";
    case "cost_rate":
      return line.cost_rate ?? "";
    case "margin_percent":
      return line.source === "system" ? (line.margin_percent ?? "") : "—";
    case "source":
      return line.source ?? "";
    default:
      return "";
  }
}

/** The PATCH body for one edited cell. */
function cellUpdate(line: BoqLine, key: string, raw: string): Record<string, unknown> | string {
  const value = raw.trim();
  const number = (v: string) => v.replace(/[,₹\s]/g, "");
  switch (key) {
    case "client_item_no":
      return { client_item_no: value || null };
    case "description":
      return value ? { description: value } : "The description cannot be empty";
    case "unit":
      return { unit: value || null };
    case "qty": {
      const upper = value.toUpperCase();
      if (["QRO", "RO", "RATE ONLY"].includes(upper)) return { qty: null, qty_note: "QRO" };
      if (["NQ", "NOT QUOTED"].includes(upper)) return { status: "not_quoted" };
      if (!value) return { qty: null, qty_note: null };
      const n = number(value);
      if (!/^\d+(\.\d{0,3})?$/.test(n)) return "Quantity: a number with up to 3 decimals, QRO or NQ";
      return line.qty_note === "NQ" ? { status: "unpriced", qty: n } : { qty: n, qty_note: null };
    }
    case "rate": {
      if (!value) return { rate: null };
      const n = number(value);
      if (!/^\d+(\.\d{0,2})?$/.test(n)) return "Rate: a number with up to 2 decimals";
      return { rate: n };
    }
    case "margin_percent": {
      const n = number(value.replace("%", ""));
      if (!/^\d+(\.\d{0,2})?$/.test(n)) return "Margin: a percentage, e.g. 25";
      return { margin_percent: n };
    }
    case "our_remarks":
      return { our_remarks: value || null };
    case "our_product":
      return { our_product: value || null };
    case "manufacturer":
      return { manufacturer: value || null };
    default:
      return "This cell cannot be edited";
  }
}

export default function BoqTab({ tender, canEdit, onTotalChange }: { tender: Tender; canEdit: boolean; onTotalChange: () => void }) {
  const { can } = useAuth();
  const seesCost = can("tender.margin");
  const [boq, setBoq] = useState<Boq | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cursor, setCursor] = useState<{ row: number; col: number }>({ row: 0, col: 1 });
  const [editing, setEditing] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<LineDetail | null>(null);
  const [importing, setImporting] = useState(false);
  const [acceptAbove, setAcceptAbove] = useState("80");
  const [margin, setMargin] = useState("25");
  const [busy, setBusy] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);

  const columns: Col[] = useMemo(() => {
    const editable = () => canEdit;
    const cols: Col[] = [
      { key: "client_item_no", label: "Item no", editable, width: "5.5rem" },
      { key: "description", label: "Description", editable },
      { key: "unit", label: "Unit", editable, width: "5rem" },
      { key: "qty", label: "Qty", editable, num: true, width: "6.5rem" },
      { key: "rate", label: "Rate", editable: (l) => canEdit && l.status !== "not_quoted", num: true, width: "7.5rem" },
      { key: "amount", label: "Amount", editable: () => false, num: true, width: "9rem" },
    ];
    if (seesCost) {
      cols.push(
        { key: "cost_rate", label: "Cost", editable: () => false, num: true, cost: true, width: "7rem" },
        { key: "margin_percent", label: "Margin %", editable: (l) => canEdit && l.source === "system", num: true, cost: true, width: "5.5rem" },
        { key: "source", label: "Source", editable: () => false, cost: true, width: "5.5rem" },
      );
    }
    cols.push(
      { key: "client_remarks", label: "Client remarks", editable: () => false, width: "10rem", muted: true },
      { key: "our_product", label: "Our product", editable, width: "10rem" },
      { key: "manufacturer", label: "Make", editable, width: "7rem" },
      { key: "our_remarks", label: "Our remarks", editable, width: "11rem" },
      { key: "status", label: "Status", editable: () => false, width: "7rem" },
    );
    return cols;
  }, [canEdit, seesCost]);

  const load = useCallback(async () => {
    try {
      setBoq(await api<Boq>(`/api/tenders/${tender.id}/boq`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [tender.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows: Row[] = useMemo(() => {
    if (!boq) return [];
    const out: Row[] = [];
    const bySection = new Map<number | null, BoqLine[]>();
    for (const line of boq.lines) {
      const list = bySection.get(line.section_id) ?? [];
      list.push(line);
      bySection.set(line.section_id, list);
    }
    for (const line of bySection.get(null) ?? []) out.push({ kind: "line", line });
    for (const s of boq.sections) {
      out.push({ kind: "section", id: s.id, title: s.title, note: s.note, total: s.total });
      for (const line of bySection.get(s.id) ?? []) out.push({ kind: "line", line });
    }
    return out;
  }, [boq]);

  const loadDetail = useCallback(
    async (lineId: number) => {
      try {
        setDetail(await api<LineDetail>(`/api/tenders/${tender.id}/lines/${lineId}`));
      } catch (err) {
        setError(errorText(err));
      }
    },
    [tender.id],
  );

  useEffect(() => {
    if (selected === null) setDetail(null);
    else void loadDetail(selected);
  }, [selected, loadDetail]);

  function applyBoq(next: Boq) {
    setBoq(next);
    onTotalChange();
    if (selected !== null) void loadDetail(selected);
  }

  async function run(action: () => Promise<Boq | void>, message?: string) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const next = await action();
      if (next) applyBoq(next);
      if (message) setNotice(message);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveCell(line: BoqLine, key: string, raw: string) {
    if (raw === cellText(line, key)) return;
    const update = cellUpdate(line, key, raw);
    if (typeof update === "string") {
      setError(update);
      return;
    }
    await run(() => api<Boq>(`/api/tenders/${tender.id}/lines`, { method: "PATCH", json: { lines: [{ id: line.id, ...update }] } }));
  }

  // --- keyboard navigation ---

  function focusGrid() {
    gridRef.current?.focus();
  }

  function moveTo(row: number, col: number) {
    const r = Math.max(0, Math.min(rows.length - 1, row));
    const c = Math.max(0, Math.min(columns.length - 1, col));
    setCursor({ row: r, col: c });
    const target = rows[r];
    if (target?.kind === "line") setSelected(target.line.id);
    gridRef.current?.querySelector(`[data-cell="${r}-${c}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function nextEditable(row: number, col: number, step: 1 | -1): { row: number; col: number } | null {
    let r = row;
    let c = col + step;
    while (r >= 0 && r < rows.length) {
      const target = rows[r];
      while (c >= 0 && c < columns.length) {
        if (target.kind === "line" && columns[c].editable(target.line)) return { row: r, col: c };
        c += step;
      }
      r += step;
      c = step === 1 ? 0 : columns.length - 1;
    }
    return null;
  }

  function startEdit(initial?: string) {
    const target = rows[cursor.row];
    if (!target || target.kind !== "line" || !columns[cursor.col].editable(target.line)) return;
    setEditing(initial ?? cellText(target.line, columns[cursor.col].key));
  }

  async function commit(then?: "down" | "next" | "prev") {
    const target = rows[cursor.row];
    const value = editing;
    setEditing(null);
    if (target?.kind === "line" && value !== null) await saveCell(target.line, columns[cursor.col].key, value);
    if (then === "down") moveTo(cursor.row + 1, cursor.col);
    if (then === "next" || then === "prev") {
      const n = nextEditable(cursor.row, cursor.col, then === "next" ? 1 : -1);
      if (n) moveTo(n.row, n.col);
    }
    focusGrid();
  }

  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    if (editing !== null) return; // the editor handles its own keys
    const { row, col } = cursor;
    switch (e.key) {
      case "ArrowDown":
        moveTo(row + 1, col);
        break;
      case "ArrowUp":
        moveTo(row - 1, col);
        break;
      case "ArrowRight":
        moveTo(row, col + 1);
        break;
      case "ArrowLeft":
        moveTo(row, col - 1);
        break;
      case "Tab": {
        const n = nextEditable(row, col, e.shiftKey ? -1 : 1);
        if (n) moveTo(n.row, n.col);
        break;
      }
      case "Enter":
      case "F2":
        startEdit();
        break;
      case "Delete":
      case "Backspace":
        startEdit("");
        break;
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          startEdit(e.key);
          break;
        }
        return;
    }
    e.preventDefault();
  }

  function onEditorKey(e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      setEditing(null);
      focusGrid();
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void commit("down");
    } else if (e.key === "Tab") {
      e.preventDefault();
      void commit(e.shiftKey ? "prev" : "next");
    }
  }

  // --- toolbar actions ---

  const selectedLine = boq?.lines.find((l) => l.id === selected) ?? null;

  async function addLine() {
    const description = prompt("Description of the new line");
    if (!description?.trim()) return;
    await run(() =>
      api<Boq>(`/api/tenders/${tender.id}/lines`, {
        method: "POST",
        json: {
          description,
          section_id: selectedLine?.section_id ?? null,
          after_line_id: selectedLine?.id ?? null,
        },
      }),
    );
  }

  async function addSection() {
    const title = prompt("Section title");
    if (!title?.trim()) return;
    await run(() => api<Boq>(`/api/tenders/${tender.id}/sections`, { method: "POST", json: { title } }));
  }

  async function suggest() {
    await run(async () => {
      const r = await api<SuggestResult>(`/api/tenders/${tender.id}/boq/suggest`, { method: "POST" });
      setNotice(
        `Suggested ${r.suggested} of ${r.lines_considered} lines (score ≥ ${Math.round(Number(r.threshold) * 100)}%); ` +
          `${r.left_unpriced} left unpriced, ${r.skipped_priced} priced lines untouched.`,
      );
      return api<Boq>(`/api/tenders/${tender.id}/boq`);
    });
  }

  async function acceptAll() {
    const pct = Number(acceptAbove);
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
      setError("Enter a percentage between 0 and 100");
      return;
    }
    const count = boq?.lines.filter((l) => l.status === "suggested" && Number(l.suggestion_score ?? 0) * 100 >= pct).length ?? 0;
    if (!confirm(`Accept ${count} suggestion(s) scoring ${pct}% or more?`)) return;
    await run(() => api<Boq>(`/api/tenders/${tender.id}/boq/accept`, { method: "POST", json: { min_score: (pct / 100).toFixed(3) } }), `${count} suggestion(s) accepted.`);
  }

  async function applyMargin() {
    if (!/^\d+(\.\d{1,2})?$/.test(margin)) {
      setError("Margin: a percentage, e.g. 25");
      return;
    }
    if (!confirm(`Set ${margin}% margin on every system-priced line? Library and manual rates are not changed.`)) return;
    await run(
      () => api<Boq>(`/api/tenders/${tender.id}/boq/margin`, { method: "POST", json: { margin_percent: margin } }),
      `Margin ${margin}% applied to the system-priced lines.`,
    );
  }

  if (!boq) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  const counts = boq.totals.counts;
  const suggestedCount = boq.lines.filter((l) => l.status === "suggested").length;

  return (
    <>
      <div className="toolbar">
        <div className="page-actions">
          {canEdit && (
            <>
              <button className="btn" onClick={() => setImporting(true)}>
                ⤒ Import client BOQ
              </button>
              <button className="btn btn-primary" disabled={busy || boq.lines.length === 0} onClick={() => void suggest()}>
                Suggest rates
              </button>
              <span className="inline-form">
                <button className="btn" disabled={busy || suggestedCount === 0} onClick={() => void acceptAll()}>
                  Accept all ≥
                </button>
                <input className="input-num" value={acceptAbove} onChange={(e) => setAcceptAbove(e.target.value)} aria-label="Minimum score %" />
                <span className="muted">%</span>
              </span>
              <button className="btn" disabled={busy} onClick={() => void addLine()}>
                Add line
              </button>
              <button className="btn" disabled={busy} onClick={() => void addSection()}>
                Add section
              </button>
              {seesCost && (
                <span className="inline-form">
                  <button className="btn" disabled={busy} onClick={() => void applyMargin()}>
                    Apply margin
                  </button>
                  <input className="input-num" value={margin} onChange={(e) => setMargin(e.target.value)} aria-label="Margin %" />
                  <span className="muted">%</span>
                </span>
              )}
            </>
          )}
        </div>
        <span className="muted small">
          {counts.lines ?? boq.lines.length} lines · {counts.priced ?? 0} priced · {counts.suggested ?? 0} suggested · {counts.unpriced ?? 0} unpriced · {counts.qro ?? 0} QRO ·{" "}
          {counts.not_quoted ?? 0} NQ
        </span>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}

      <div className={selected !== null ? "boq-layout with-panel" : "boq-layout"}>
        <div className="card boq-card">
          {boq.lines.length === 0 && boq.sections.length === 0 ? (
            <p className="empty">No BOQ yet. Import the client's BOQ or add lines by hand.</p>
          ) : (
            <div className="boq-grid" ref={gridRef} tabIndex={0} onKeyDown={onGridKey} role="grid" aria-label="BOQ">
              <table className="table compact">
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c.key} className={`${c.num ? "num" : ""} ${c.cost ? "cost-col" : ""}`} style={c.width ? { width: c.width } : undefined}>
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, ri) =>
                    r.kind === "section" ? (
                      <tr key={`s${r.id}`} className="boq-section" data-cell={`${ri}-0`}>
                        <td colSpan={columns.length - 1}>
                          <SectionTitle tenderId={tender.id} id={r.id} title={r.title} note={r.note} canEdit={canEdit} onSaved={applyBoq} onError={setError} />
                        </td>
                        <td className="num nowrap">{inr(r.total)}</td>
                      </tr>
                    ) : (
                      <tr key={r.line.id} className={`${r.line.status === "not_quoted" ? "row-muted" : ""} ${selected === r.line.id ? "row-current" : ""}`}>
                        {columns.map((c, ci) => {
                          const active = cursor.row === ri && cursor.col === ci;
                          const isEditing = active && editing !== null;
                          return (
                            <td
                              key={c.key}
                              data-cell={`${ri}-${ci}`}
                              className={`boq-cell ${c.num ? "num" : ""} ${c.cost ? "cost-col" : ""} ${c.muted ? "cell-muted" : ""} ${active ? "cell-active" : ""} ${
                                c.editable(r.line) ? "cell-editable" : ""
                              }`}
                              onMouseDown={() => {
                                if (editing !== null && !isEditing) void commit();
                                setCursor({ row: ri, col: ci });
                                setSelected(r.line.id);
                              }}
                              onDoubleClick={() => startEdit()}
                            >
                              {isEditing ? (
                                c.key === "description" || c.key === "our_remarks" ? (
                                  <textarea
                                    className="cell-editor"
                                    autoFocus
                                    rows={3}
                                    value={editing}
                                    onChange={(e) => setEditing(e.target.value)}
                                    onKeyDown={onEditorKey}
                                    onBlur={() => void commit()}
                                  />
                                ) : (
                                  <input
                                    className="cell-editor"
                                    autoFocus
                                    value={editing}
                                    onChange={(e) => setEditing(e.target.value)}
                                    onKeyDown={onEditorKey}
                                    onBlur={() => void commit()}
                                  />
                                )
                              ) : (
                                <CellView line={r.line} col={c.key} />
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small top-gap">Arrows move · Enter or typing edits · Tab goes to the next cell · Esc cancels. QRO / NQ lines are left out of the totals.</p>
          <dl className="totals boq-totals">
            <dt>Subtotal</dt>
            <dd>{inr(boq.totals.subtotal)}</dd>
            <dt>GST {num(boq.totals.gst_percent, 2)}%</dt>
            <dd>{inr(boq.totals.gst)}</dd>
            <dt className="grand">Total with GST</dt>
            <dd className="grand">{inr(boq.totals.grand_total)}</dd>
            {boq.totals.cost_total !== undefined && (
              <>
                <dt>Cost of system-priced lines</dt>
                <dd>{inr(boq.totals.cost_total)}</dd>
                <dt>Margin on them</dt>
                <dd>{inr(boq.totals.margin_amount)}</dd>
              </>
            )}
          </dl>
        </div>

        {selected !== null && <LinePanel tenderId={tender.id} detail={detail} canEdit={canEdit} onClose={() => setSelected(null)} onChange={applyBoq} run={run} />}
      </div>

      {importing && (
        <ImportWizard
          tenderId={tender.id}
          onClose={() => setImporting(false)}
          onImported={async () => {
            setImporting(false);
            setSelected(null);
            await load();
            onTotalChange();
          }}
        />
      )}
    </>
  );
}

function CellView({ line, col }: { line: BoqLine; col: string }) {
  switch (col) {
    case "description":
      return (
        <span className="clamp" title={line.description}>
          {line.description}
        </span>
      );
    case "client_remarks":
      return line.client_remarks ? (
        <span className="clamp" title={line.client_remarks}>
          {line.client_remarks}
        </span>
      ) : (
        <>—</>
      );
    case "unit":
      return (
        <span title={line.unit_raw && line.unit_raw !== line.unit ? `In the client's file: ${line.unit_raw}` : undefined}>
          {line.unit ?? (line.unit_raw ? <span className="text-warn">{line.unit_raw}</span> : "—")}
        </span>
      );
    case "qty":
      return line.qty_note ? <span className="badge badge-info">{line.qty_note}</span> : <>{line.qty ? num(line.qty, 3) : "—"}</>;
    case "rate":
    case "amount":
    case "cost_rate": {
      const v = cellText(line, col);
      return <>{v ? inr(v) : "—"}</>;
    }
    case "margin_percent":
      return <>{line.source === "system" && line.margin_percent ? `${num(line.margin_percent, 2)}%` : "—"}</>;
    case "source":
      return <span className="muted">{line.source ?? "—"}</span>;
    case "status":
      return (
        <span className={`badge ${STATUS_BADGE[line.status]}`}>
          {STATUS_LABEL[line.status]}
          {line.status === "suggested" && line.suggestion_score ? ` ${Math.round(Number(line.suggestion_score) * 100)}%` : ""}
        </span>
      );
    default:
      return <>{cellText(line, col) || "—"}</>;
  }
}

function SectionTitle({
  tenderId,
  id,
  title,
  note,
  canEdit,
  onSaved,
  onError,
}: {
  tenderId: number;
  id: number;
  title: string;
  note: string | null;
  canEdit: boolean;
  onSaved: (b: Boq) => void;
  onError: (e: string) => void;
}) {
  async function rename() {
    const next = prompt("Section title", title);
    if (!next?.trim() || next === title) return;
    try {
      onSaved(await api<Boq>(`/api/tenders/${tenderId}/sections/${id}`, { method: "PATCH", json: { title: next } }));
    } catch (err) {
      onError(errorText(err));
    }
  }
  async function editNote() {
    const next = prompt("Section note (printed under the heading in the export)", note ?? "");
    if (next === null || next === (note ?? "")) return;
    try {
      onSaved(await api<Boq>(`/api/tenders/${tenderId}/sections/${id}`, { method: "PATCH", json: { note: next } }));
    } catch (err) {
      onError(errorText(err));
    }
  }
  async function remove() {
    if (!confirm(`Remove the heading "${title}"? Its lines stay in the BOQ.`)) return;
    try {
      onSaved(await api<Boq>(`/api/tenders/${tenderId}/sections/${id}`, { method: "DELETE" }));
    } catch (err) {
      onError(errorText(err));
    }
  }
  return (
    <div>
      <span className="section-head">
        <strong>{title}</strong>
        {canEdit && (
          <>
            <button className="btn btn-small btn-ghost" onClick={() => void rename()}>
              Rename
            </button>
            <button className="btn btn-small btn-ghost" onClick={() => void editNote()}>
              {note ? "Edit note" : "Add note"}
            </button>
            <button className="btn btn-small btn-ghost" onClick={() => void remove()}>
              Remove heading
            </button>
          </>
        )}
      </span>
      {note && (
        <details className="section-note">
          <summary>Section note</summary>
          <p className="pre-line small">{note}</p>
        </details>
      )}
    </div>
  );
}

function LinePanel({
  tenderId,
  detail,
  canEdit,
  onClose,
  onChange,
  run,
}: {
  tenderId: number;
  detail: LineDetail | null;
  canEdit: boolean;
  onClose: () => void;
  onChange: (b: Boq) => void;
  run: (action: () => Promise<Boq | void>, message?: string) => Promise<void>;
}) {
  const learned = useLearned(detail?.system_breakdown?.system_id ?? null);
  if (!detail) {
    return (
      <aside className="card boq-panel">
        <p className="muted">Loading…</p>
      </aside>
    );
  }
  const { line, candidates, library_stats: stats, system_breakdown: build } = detail;
  const base = `/api/tenders/${tenderId}/lines`;

  return (
    <aside className="card boq-panel">
      <div className="toolbar">
        <h2 className="section-title">
          {line.client_item_no ? `${line.client_item_no} · ` : ""}
          {STATUS_LABEL[line.status]}
        </h2>
        <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <p className="pre-line small">{line.description}</p>
      <dl className="totals">
        <dt>Unit / qty</dt>
        <dd>
          {line.unit ?? line.unit_raw ?? "—"} · {line.qty_note ?? (line.qty ? num(line.qty, 3) : "—")}
        </dd>
        <dt>Rate in the client's file</dt>
        <dd>{inr(line.client_file_rate)}</dd>
        {(line.client_material_rate || line.client_application_rate) && (
          <>
            <dt>Material / application</dt>
            <dd>
              {inr(line.client_material_rate)} / {inr(line.client_application_rate)}
            </dd>
          </>
        )}
        {line.source_page && (
          <>
            <dt>In the PDF</dt>
            <dd>
              page {line.source_page}
              {line.source_page_to && line.source_page_to !== line.source_page ? `–${line.source_page_to}` : ""}
            </dd>
          </>
        )}
        {line.client_product && (
          <>
            <dt>Client's make</dt>
            <dd>{line.client_product}</dd>
          </>
        )}
        {line.client_remarks && (
          <>
            <dt>Client's remarks</dt>
            <dd>{line.client_remarks}</dd>
          </>
        )}
      </dl>

      <h3 className="section-title top-gap">Candidates</h3>
      {candidates.length === 0 && <p className="muted small">No candidates. Run “Suggest rates”, or type a rate.</p>}
      <ul className="plain-list candidate-list">
        {candidates.map((c) => (
          <li key={c.id} className="candidate">
            <div>
              <strong>{inr(c.rate)}</strong> <span className="badge badge-muted">{Math.round(Number(c.score) * 100)}%</span>
              {c.source && <span className="badge badge-info">{c.source}</span>}
              <div className="muted small">{c.reason}</div>
              {c.cost_rate && (
                <div className="muted small">
                  cost {inr(c.cost_rate)} · margin {num(c.margin_percent, 2)}%
                </div>
              )}
              {c.details && <WhyThisRate rate={c.rate} history={c.details} />}
            </div>
            {canEdit && line.status !== "not_quoted" && (
              <button
                className="btn btn-small"
                onClick={() => void run(() => api<Boq>(`${base}/${line.id}/use-candidate`, { method: "POST", json: { candidate_id: c.id } }), "Rate applied.")}
              >
                Use this
              </button>
            )}
          </li>
        ))}
      </ul>

      {stats && stats.length > 0 && (
        <>
          <h3 className="section-title top-gap">Rate library</h3>
          <table className="table compact">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Min</th>
                <th className="num">Median</th>
                <th className="num">Max</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((s) => (
                <tr key={s.library_item_id}>
                  <td>
                    <span className="clamp small" title={s.description}>
                      {s.description}
                    </span>
                    <span className="muted small">
                      {s.unit ?? "—"} · {s.boq_count} BOQs{s.latest_channel ? ` · last via ${s.latest_channel}` : ""}
                    </span>
                  </td>
                  <td className="num">{inr(s.min_rate)}</td>
                  <td className="num">{inr(s.median_rate)}</td>
                  <td className="num">{inr(s.max_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {build && (
        <>
          <h3 className="section-title top-gap">
            System build-up: {build.code ? <code>{build.code}</code> : null} {build.name}
          </h3>
          {build.error ? (
            <div className="alert alert-warn">{build.error}</div>
          ) : (
            <>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="num">Qty</th>
                    <th className="num">Landed</th>
                    <th className="num">Cost</th>
                    <th className="num" title="Median actual consumption per unit over completed areas">
                      Site average
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {build.components?.map((c, i) => (
                    <tr key={i}>
                      <td>{c.product}</td>
                      <td className="num">{num(c.qty)}</td>
                      <td className="num">{inr(c.landed_rate)}</td>
                      <td className="num">{inr(c.cost)}</td>
                      <td className="num muted">{num(learned.find((l) => l.product === c.product)?.site_average)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <dl className="totals">
                <dt>Materials</dt>
                <dd>{inr(build.material_cost)}</dd>
                <dt>Surface preparation</dt>
                <dd>{inr(build.surface_prep)}</dd>
                <dt>Labour</dt>
                <dd>{inr(build.labour_per_unit)}</dd>
                <dt className="subtotal">Cost per {build.unit}</dt>
                <dd className="subtotal">{inr(build.base_cost)}</dd>
                <dt>Margin {num(build.margin_percent, 2)}%</dt>
                <dd>{inr(build.rate)}</dd>
              </dl>
            </>
          )}
        </>
      )}

      {canEdit && (
        <div className="form-actions">
          {line.status === "not_quoted" ? (
            <button className="btn" onClick={() => void run(() => api<Boq>(base, { method: "PATCH", json: { lines: [{ id: line.id, status: "unpriced" }] } }))}>
              Quote this line
            </button>
          ) : (
            <button className="btn" onClick={() => void run(() => api<Boq>(base, { method: "PATCH", json: { lines: [{ id: line.id, status: "not_quoted" }] } }))}>
              Mark not quoted
            </button>
          )}
          {line.rate && line.status !== "not_quoted" && (
            <button className="btn" onClick={() => void run(() => api<Boq>(base, { method: "PATCH", json: { lines: [{ id: line.id, rate: null }] } }))}>
              Clear rate
            </button>
          )}
          <button
            className="btn btn-danger"
            onClick={() => {
              if (!confirm("Delete this line?")) return;
              onClose();
              void run(() =>
                api<Boq>(`${base}/delete`, { method: "POST", json: { line_ids: [line.id] } }).then((b) => {
                  onChange(b);
                }),
              );
            }}
          >
            Delete line
          </button>
        </div>
      )}
    </aside>
  );
}

function WhyThisRate({ rate, history: h }: { rate: string; history: RateHistory }) {
  return (
    <details className="why-rate" open={h.warning}>
      <summary>
        Why this rate
        {h.warning && (
          <span className="badge badge-danger" title="More than 15% above the median of past BOQs">
            {num(h.above_median_percent, 1)}% above median
          </span>
        )}
      </summary>
      <p className="small">
        Policy: <strong>{RATE_POLICIES[h.policy] ?? h.policy}</strong>
        {h.used !== h.policy && <> — used {RATE_POLICIES[h.used]?.toLowerCase() ?? h.used} (no same-channel rate)</>}
      </p>
      <dl className="totals small">
        <dt>Latest</dt>
        <dd>{inr(h.latest_rate)}</dd>
        <dt>Median</dt>
        <dd>{inr(h.median_rate)}</dd>
        {h.min_rate !== undefined && (
          <>
            <dt>Min / max</dt>
            <dd>
              {inr(h.min_rate)} / {inr(h.max_rate)}
            </dd>
          </>
        )}
        <dt>Same channel's last rate</dt>
        <dd>{inr(h.channel_last_rate)}</dd>
        <dt>BOQs</dt>
        <dd>{h.n_boqs}</dd>
      </dl>
      {h.sources.length > 0 && (
        <table className="table compact small">
          <thead>
            <tr>
              <th>Channel</th>
              <th>BOQ</th>
              <th>Date</th>
              <th className="num">Rate</th>
            </tr>
          </thead>
          <tbody>
            {h.sources.map((s, i) => (
              <tr key={i} className={s.rate === rate ? "row-current" : ""}>
                <td>{s.channel ?? "—"}</td>
                <td>
                  <span className="clamp" title={s.file}>
                    {s.file}
                  </span>
                </td>
                <td className="muted">{s.date ?? "—"}</td>
                <td className="num">{inr(s.rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {h.sources_total > h.sources.length && <p className="muted small">and {h.sources_total - h.sources.length} more. The library has no BOQ dates yet.</p>}
    </details>
  );
}
