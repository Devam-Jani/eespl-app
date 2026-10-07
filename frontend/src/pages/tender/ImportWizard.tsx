import { useState } from "react";
import { api } from "../../api";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { ImportPreview, ImportReport } from "../../types";

const FIELDS: [string, string][] = [
  ["item_no", "Item no"],
  ["description", "Description *"],
  ["description2", "Second description column"],
  ["unit", "Unit"],
  ["qty", "Quantity"],
  ["qty2", "Second quantity column (added to the quantity)"],
  ["rate", "Client's rate (kept for reference only)"],
  ["material_rate", "Client's material rate (reference)"],
  ["application_rate", "Client's application rate (reference)"],
  ["amount", "Amount (not imported)"],
  ["product", "Client's make / product"],
  ["remarks", "Client's remarks"],
  ["our_remarks", "Our remarks"],
];

type Step = "upload" | "map" | "done";

export default function ImportWizard({ tenderId, onClose, onImported }: { tenderId: number; onClose: () => void; onImported: () => Promise<void> }) {
  const [step, setStep] = useState<Step>("upload");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [replace, setReplace] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setError(null);
    if (file.size > 20 * 1024 * 1024) {
      setError("The file is larger than 20 MB");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    setBusy(true);
    try {
      setPreview(await api<ImportPreview>(`/api/tenders/${tenderId}/boq/import`, { method: "POST", form }));
      setStep("map");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function refresh(sheet: string, headerRow: number, columnMap: Record<string, number | null> | null) {
    if (!preview) return;
    setError(null);
    setBusy(true);
    try {
      setPreview(
        await api<ImportPreview>(`/api/tenders/${tenderId}/boq/import/preview`, {
          method: "POST",
          json: { upload_id: preview.upload_id, sheet, header_row: headerRow, column_map: columnMap },
        }),
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function currentMap(): Record<string, number | null> {
    return Object.fromEntries(Object.entries(preview?.column_map ?? {}).map(([f, g]) => [f, g.column]));
  }

  async function confirmImport() {
    if (!preview) return;
    setError(null);
    setBusy(true);
    try {
      setReport(
        await api<ImportReport>(`/api/tenders/${tenderId}/boq/import/confirm`, {
          method: "POST",
          json: {
            upload_id: preview.upload_id,
            sheet: preview.sheet,
            header_row: preview.header_row,
            column_map: currentMap(),
            replace,
          },
        }),
      );
      setStep("done");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Import client BOQ" onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}

      {step === "upload" && (
        <div>
          <p>Choose the client's BOQ (.xlsx, .xls, .csv, or a PDF with a text layer up to 60 pages; at most 20 MB). You will see how it reads before anything is saved.</p>
          <input type="file" accept=".xlsx,.xlsm,.xls,.csv,.pdf" disabled={busy} onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
          {busy && <p className="muted">Reading the file…</p>}
        </div>
      )}

      {step === "map" && preview && (
        <div className="import-map">
          <div className="grid-4">
            <label className="field">
              <span>Sheet</span>
              <select
                value={preview.sheet}
                disabled={busy}
                onChange={(e) => {
                  const s = preview.sheets.find((x) => x.name === e.target.value);
                  if (s) void refresh(s.name, s.header_row, null);
                }}
              >
                {preview.sheets.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Header row</span>
              <input
                type="number"
                min={1}
                value={preview.header_row}
                disabled={busy}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (n >= 1) void refresh(preview.sheet, n, null);
                }}
              />
            </label>
            <div className="field">
              <span>File</span>
              <span className="muted small">
                {preview.filename}
                {preview.page_count ? ` · ${preview.page_count} pages` : ""}
              </span>
            </div>
          </div>

          <h3 className="section-title">Columns</h3>
          <div className="grid-2 column-map">
            {FIELDS.map(([field, label]) => {
              const guess = preview.column_map[field];
              return (
                <label key={field} className="field">
                  <span>
                    {label}{" "}
                    {guess && guess.confidence < 1 && (
                      <span className={`badge ${guess.confidence >= 0.9 ? "badge-ok" : guess.confidence >= 0.7 ? "badge-info" : "badge-warn"}`}>
                        guessed {Math.round(guess.confidence * 100)}%
                        {guess.alternatives.length ? ` · also ${guess.alternatives.join(", ")}` : ""}
                      </span>
                    )}
                  </span>
                  <select
                    value={guess ? String(guess.column) : ""}
                    disabled={busy}
                    onChange={(e) => {
                      const map = currentMap();
                      const v = e.target.value === "" ? null : Number(e.target.value);
                      for (const [f, c] of Object.entries(map)) if (v !== null && c === v) map[f] = null;
                      map[field] = v;
                      void refresh(preview.sheet, preview.header_row, map);
                    }}
                  >
                    <option value="">— not in this file —</option>
                    {preview.header.map((h) => (
                      <option key={h.column} value={h.column}>
                        {h.letter}: {h.text.slice(0, 50)}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>

          <p className="top-gap">
            <strong>{preview.counts.lines}</strong> lines in <strong>{preview.counts.sections}</strong> sections ·{" "}
            {preview.counts.qro} QRO · {preview.counts.nq} NQ · {preview.counts.skipped} rows skipped
            {Object.keys(preview.counts.skipped_by_reason).length > 0 && (
              <span className="muted">
                {" "}
                ({Object.entries(preview.counts.skipped_by_reason)
                  .map(([k, v]) => `${v} ${k}`)
                  .join(", ")})
              </span>
            )}
            {Object.keys(preview.counts.unrecognised_units).length > 0 && (
              <span className="text-warn">
                {" "}
                · units not recognised: {Object.entries(preview.counts.unrecognised_units)
                  .map(([k, v]) => `${k} (${v})`)
                  .join(", ")}
              </span>
            )}
          </p>

          <div className="table-wrap preview-table">
            <table className="table compact">
              <thead>
                <tr>
                  <th>{preview.page_count ? "Page" : "Rows"}</th>
                  <th>Item</th>
                  <th>Description</th>
                  <th>Unit</th>
                  <th className="num">Qty</th>
                  <th className="num">Client rate</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) =>
                  r.type === "section" ? (
                    <tr key={i} className="boq-section">
                      <td className="muted small nowrap">{(r.page as string) ?? (r.rows as number[]).join(", ")}</td>
                      <td colSpan={5}>
                        <strong>{String(r.title)}</strong>
                      </td>
                    </tr>
                  ) : (
                    <tr key={i} className={r.status === "not_quoted" ? "row-muted" : ""}>
                      <td className="muted small nowrap">{(r.page as string) ?? (r.rows as number[]).join(", ")}</td>
                      <td>{(r.item_no as string) ?? ""}</td>
                      <td>
                        <span className="clamp" title={String(r.description)}>
                          {String(r.description)}
                        </span>
                      </td>
                      <td>{(r.unit as string) ?? <span className="text-warn">{(r.unit_raw as string) ?? "—"}</span>}</td>
                      <td className="num">{r.qty_note ? <span className="badge badge-info">{String(r.qty_note)}</span> : num(r.qty as string, 3)}</td>
                      <td className="num">{inr(r.client_file_rate as string | null)}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <p className="muted small">The first 30 rows as they will be imported.</p>

          {preview.existing_lines > 0 && (
            <label className="check alert alert-warn">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              This tender already has {preview.existing_lines} lines. Replace them (priced rates are kept where the item no and description match).
            </label>
          )}
          <div className="form-actions">
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              disabled={busy || !preview.column_map.description || (preview.existing_lines > 0 && !replace)}
              onClick={() => void confirmImport()}
            >
              Import {preview.counts.lines} lines
            </button>
          </div>
        </div>
      )}

      {step === "done" && report && (
        <div>
          <div className="alert alert-ok">
            Imported {report.lines} lines in {report.sections} sections.
            {report.kept_prices > 0 && ` Kept ${report.kept_prices} priced rates.`}
          </div>
          <dl className="totals">
            <dt>QRO (rate only)</dt>
            <dd>{report.qro}</dd>
            <dt>NQ (not quoted)</dt>
            <dd>{report.nq}</dd>
            <dt>Rows skipped</dt>
            <dd>{report.skipped}</dd>
            {Object.entries(report.skipped_by_reason).map(([k, v]) => (
              <span key={k} style={{ display: "contents" }}>
                <dt className="small">· {k}</dt>
                <dd className="small">{v}</dd>
              </span>
            ))}
            <dt>Units not recognised</dt>
            <dd>
              {Object.entries(report.unrecognised_units)
                .map(([k, v]) => `${k} (${v})`)
                .join(", ") || "none"}
            </dd>
          </dl>
          <div className="form-actions">
            <button className="btn btn-primary" onClick={() => void onImported()}>
              Done
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
