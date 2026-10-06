import { useEffect, useState } from "react";
import { api, queryString } from "../api";
import Modal from "../components/Modal";
import { errorText, inr, num } from "../format";
import type { LibraryHit, LibraryLine } from "../types";
import { useUnits } from "./Products";

export default function RateLibrary() {
  const units = useUnits();
  const [q, setQ] = useState("");
  const [unit, setUnit] = useState("");
  const [hits, setHits] = useState<LibraryHit[]>([]);
  const [took, setTook] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<LibraryHit | null>(null);

  // Search as you type (debounced).
  useEffect(() => {
    const timer = setTimeout(() => {
      api<{ items: LibraryHit[]; took_ms: number }>(`/api/library/search${queryString({ q, unit, limit: 50 })}`).then(
        (r) => {
          setHits(r.items);
          setTook(r.took_ms);
          setError(null);
        },
        (err) => setError(errorText(err)),
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [q, unit]);

  return (
    <>
      <div className="page-header">
        <h1>Rate library</h1>
      </div>
      <div className="card filters">
        <label className="field grow">
          <span>Search past BOQ items</span>
          <input
            autoFocus
            placeholder="e.g. app based membrane, crystalline, pvc pipe sealing"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Unit</span>
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="">Any</option>
            {units.map((u) => (
              <option key={u.code} value={u.code}>
                {u.code}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {took !== null && (
        <p className="muted small">
          {hits.length} result{hits.length === 1 ? "" : "s"} {q ? `for “${q}”` : "(most quoted items)"} · {took} ms
        </p>
      )}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Description</th>
              <th>Unit</th>
              <th className="num">Latest</th>
              <th className="num">Min</th>
              <th className="num">Median</th>
              <th className="num">Max</th>
              <th className="num">BOQs</th>
              <th>Latest client</th>
            </tr>
          </thead>
          <tbody>
            {hits.map((h) => (
              <tr key={h.id} className="clickable" onClick={() => setOpen(h)}>
                <td className="desc-cell">
                  <div className="clamp">{h.description}</div>
                  {h.needs_check && <span className="badge badge-warn">{h.check_note}</span>}
                </td>
                <td>{h.unit ?? <span className="muted">{h.unit_raw ?? "—"}</span>}</td>
                <td className="num nowrap">
                  <strong>{inr(h.latest_rate)}</strong>
                </td>
                <td className="num nowrap">{inr(h.min_rate)}</td>
                <td className="num nowrap">{inr(h.median_rate)}</td>
                <td className="num nowrap">{inr(h.max_rate)}</td>
                <td className="num">{h.boq_count}</td>
                <td>{h.latest_client ?? "—"}</td>
              </tr>
            ))}
            {hits.length === 0 && took !== null && (
              <tr>
                <td colSpan={8} className="empty">
                  Nothing matches. Try fewer or different words.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {open && <SourceLines item={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function SourceLines({ item, onClose }: { item: LibraryHit; onClose: () => void }) {
  const [lines, setLines] = useState<LibraryLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<LibraryLine[]>(`/api/library/items/${item.id}/lines`).then(setLines, (err) => setError(errorText(err)));
  }, [item.id]);

  return (
    <Modal title="Source lines" onClose={onClose} wide>
      <p className="item-desc">{item.description}</p>
      <p className="muted small">
        {item.unit ?? item.unit_raw ?? "no unit"} · latest {inr(item.latest_rate)} · median {inr(item.median_rate)} · in{" "}
        {item.boq_count} BOQ{item.boq_count === 1 ? "" : "s"}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Client</th>
              <th>File</th>
              <th>Item</th>
              <th>Unit</th>
              <th className="num">Qty</th>
              <th className="num">Rate</th>
              <th>Make</th>
            </tr>
          </thead>
          <tbody>
            {lines?.map((l) => (
              <tr key={l.id}>
                <td>
                  {l.client_folder ?? "—"}
                  {!l.from_eespl_file && <span className="badge badge-muted" title="Not an EESPL-priced file">other</span>}
                </td>
                <td className="small" title={l.file}>
                  {l.file.split("/").pop()}
                  <span className="muted">
                    {" "}
                    {l.sheet} r{l.row}
                  </span>
                </td>
                <td>{l.item_no ?? ""}</td>
                <td>{l.unit_raw ?? "—"}</td>
                <td className="num">{l.qty !== null ? num(l.qty, 3) : <span className="muted">{l.qty_note ?? "—"}</span>}</td>
                <td className="num nowrap">{inr(l.rate)}</td>
                <td>{l.product_make ?? ""}</td>
              </tr>
            ))}
            {lines?.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No source lines linked to this item.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
