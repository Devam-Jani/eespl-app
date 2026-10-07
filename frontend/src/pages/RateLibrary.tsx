import { useCallback, useEffect, useState } from "react";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText, inr, num } from "../format";
import type { LibraryHit, LibraryItemDetail, LibraryLine, LibrarySearch } from "../types";
import { useUnits } from "./Products";

const PAGE_SIZE = 25;

type Filters = { q: string; unit: string; includeFlagged: boolean; includeCompetitor: boolean };

function searchUrl(f: Filters, offset = 0) {
  return `/api/library/search${queryString({
    q: f.q,
    unit: f.unit,
    limit: PAGE_SIZE,
    offset,
    include_flagged: f.includeFlagged ? "true" : undefined,
    include_competitor: f.includeCompetitor ? "true" : undefined,
  })}`;
}

/** Check note, "Other bidder" and "Hidden" flags: always beside the rates, never in the unit column. */
export function RateBadges({ item }: { item: Pick<LibraryHit, "is_competitor" | "is_excluded" | "excluded_reason" | "check_note"> }) {
  return (
    <span className="badges">
      {item.is_competitor && (
        <span className="badge badge-danger" title="Rate from another contractor's comparative sheet, not EESPL's">
          Other bidder
        </span>
      )}
      {item.is_excluded && (
        <span className="badge badge-muted" title={item.excluded_reason ?? ""}>
          Hidden{item.excluded_reason ? `: ${item.excluded_reason}` : ""}
        </span>
      )}
      {item.check_note && !item.is_competitor && <span className="badge badge-warn">{item.check_note}</span>}
    </span>
  );
}

export default function RateLibrary() {
  const units = useUnits();
  const [filters, setFilters] = useState<Filters>({ q: "", unit: "", includeFlagged: false, includeCompetitor: false });
  const [result, setResult] = useState<LibrarySearch | null>(null);
  const [hits, setHits] = useState<LibraryHit[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Search as you type (debounced). A new search starts from the first page.
  useEffect(() => {
    const timer = setTimeout(() => {
      api<LibrarySearch>(searchUrl(filters)).then(
        (r) => {
          setResult(r);
          setHits(r.items);
          setError(null);
        },
        (err) => setError(errorText(err)),
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [filters, reloadKey]);

  async function showMore() {
    if (!result) return;
    setLoadingMore(true);
    try {
      const r = await api<LibrarySearch>(searchUrl(filters, result.next_offset));
      setResult(r);
      setHits((h) => [...h, ...r.items.filter((i) => !h.some((x) => x.id === i.id))]);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoadingMore(false);
    }
  }

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));

  return (
    <>
      <div className="page-header">
        <h1>Rate library</h1>
        <ExportButton
          label="Export results"
          path={`/api/library/search/export${queryString({
            q: filters.q,
            unit: filters.unit,
            include_flagged: filters.includeFlagged ? "true" : undefined,
            include_competitor: filters.includeCompetitor ? "true" : undefined,
          })}`}
        />
      </div>
      <div className="card filters">
        <label className="field grow">
          <span>Search past BOQ items</span>
          <input
            autoFocus
            placeholder="e.g. app based membrane, crystalline, pvc pipe sealing"
            value={filters.q}
            onChange={(e) => set("q", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Unit</span>
          <select value={filters.unit} onChange={(e) => set("unit", e.target.value)}>
            <option value="">Any</option>
            {units.map((u) => (
              <option key={u.code} value={u.code}>
                {u.code}
              </option>
            ))}
          </select>
        </label>
        <div className="toggles">
          <label className="check" title="Working / margin rows, rates below ₹1 and items hidden by hand">
            <input type="checkbox" checked={filters.includeFlagged} onChange={(e) => set("includeFlagged", e.target.checked)} />
            Include flagged
          </label>
          <label className="check" title="Other contractors' rates from comparative sheets">
            <input
              type="checkbox"
              checked={filters.includeCompetitor}
              onChange={(e) => set("includeCompetitor", e.target.checked)}
            />
            Include competitor rates
          </label>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {result && (
        <p className="muted small">
          {hits.length} result{hits.length === 1 ? "" : "s"} {filters.q ? `for “${filters.q}”` : "(most quoted items)"} ·{" "}
          {result.took_ms} ms
          {result.cut_applied && result.has_more && " · showing the closest matches"}
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
              <th />
              <th className="num">BOQs</th>
              <th>Latest channel</th>
            </tr>
          </thead>
          <tbody>
            {hits.map((h) => {
              const flagged = h.is_competitor || h.is_excluded;
              return (
                <tr key={h.id} className={`clickable ${flagged ? "row-flagged" : ""}`} onClick={() => setOpen(h.id)}>
                  <td className="desc-cell">
                    <div className="clamp">{h.description}</div>
                  </td>
                  <td title={h.unit_raw ? `as written: ${h.unit_raw}` : ""}>{h.unit ?? "—"}</td>
                  <td className="num nowrap">{h.suggested_rate ? <strong>{inr(h.latest_rate)}</strong> : inr(h.latest_rate)}</td>
                  <td className="num nowrap">{inr(h.min_rate)}</td>
                  <td className="num nowrap">{inr(h.median_rate)}</td>
                  <td className="num nowrap">{inr(h.max_rate)}</td>
                  <td>
                    <RateBadges item={h} />
                  </td>
                  <td className="num">{h.boq_count}</td>
                  <td>{h.latest_channel ?? "—"}</td>
                </tr>
              );
            })}
            {hits.length === 0 && result && (
              <tr>
                <td colSpan={9} className="empty">
                  Nothing matches. Try fewer or different words.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {result?.has_more && (
        <div className="pager">
          <button className="btn" disabled={loadingMore} onClick={() => void showMore()}>
            {loadingMore ? "Loading…" : "Show more"}
          </button>
        </div>
      )}
      {open !== null && (
        <ItemPanel
          itemId={open}
          onOpen={setOpen}
          onClose={() => setOpen(null)}
          onChanged={() => setReloadKey((k) => k + 1)}
        />
      )}
    </>
  );
}

function ItemPanel({
  itemId,
  onOpen,
  onClose,
  onChanged,
}: {
  itemId: number;
  onOpen: (id: number) => void;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { can } = useAuth();
  const canEdit = can("library.edit");
  const units = useUnits();
  const [item, setItem] = useState<LibraryItemDetail | null>(null);
  const [lines, setLines] = useState<LibraryLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);

  const load = useCallback(async () => {
    try {
      const [i, l] = await Promise.all([
        api<LibraryItemDetail>(`/api/library/items/${itemId}`),
        api<LibraryLine[]>(`/api/library/items/${itemId}/lines`),
      ]);
      setItem(i);
      setLines(l);
    } catch (err) {
      setError(errorText(err));
    }
  }, [itemId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(path: string, method: "PATCH" | "POST", json?: object) {
    setError(null);
    try {
      await api(`/api/library/items/${path}`, { method, json });
      await load();
      onChanged();
    } catch (err) {
      setError(errorText(err));
    }
  }

  function hide() {
    const reason = prompt("Why should this item be hidden from search?", "duplicate / not a BOQ item");
    if (reason && reason.trim()) void act(`${itemId}`, "PATCH", { is_excluded: true, excluded_reason: reason.trim() });
  }

  if (!item) {
    return (
      <Modal title="Library item" onClose={onClose} wide>
        {error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}
      </Modal>
    );
  }

  return (
    <Modal title="Library item" onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="item-desc">{item.description}</p>
      <div className="item-summary">
        <span>
          Unit <strong>{item.unit ?? "—"}</strong>
          {item.unit_raw && <span className="muted small"> (as written: {item.unit_raw})</span>}
        </span>
        <span>
          {item.suggested_rate ? "Suggested" : "Latest"} <strong>{inr(item.suggested_rate ?? item.latest_rate)}</strong>
        </span>
        <span>
          Min–max {inr(item.min_rate)} – {inr(item.max_rate)} · median {inr(item.median_rate)}
        </span>
        <span>
          in {item.boq_count} BOQ{item.boq_count === 1 ? "" : "s"}
        </span>
        <RateBadges item={item} />
      </div>
      {item.stats_from_lines && (
        <p className="muted small">Figures recomputed from EESPL's own lines below (other bidders' and flagged lines left out).</p>
      )}
      {item.merged_into && (
        <div className="alert alert-warn">
          Merged into{" "}
          <button className="link" onClick={() => onOpen(item.merged_into!.id)}>
            {item.merged_into.description.slice(0, 90)}
          </button>{" "}
          ({item.merged_into.unit ?? "—"}). It no longer appears in search.
        </div>
      )}
      {item.merged_items.length > 0 && (
        <div className="merged-list">
          <span className="muted small">Merged into this item:</span>
          {item.merged_items.map((m) => (
            <div key={m.id} className="merged-row">
              <span className="small">
                {m.description.slice(0, 100)} <span className="muted">({m.unit ?? "—"})</span>
              </span>
              {canEdit && (
                <button className="btn btn-small" onClick={() => void act(`${m.id}/unmerge`, "POST")}>
                  Unmerge
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {canEdit && !item.merged_into && (
        <div className="toolbar item-actions">
          {item.is_excluded ? (
            <button className="btn btn-small" onClick={() => void act(`${itemId}`, "PATCH", { is_excluded: false })}>
              Show in search again
            </button>
          ) : (
            <button className="btn btn-small" onClick={hide}>
              Hide from search
            </button>
          )}
          <label className="inline">
            Change unit
            <select
              value={item.unit ?? ""}
              onChange={(e) => e.target.value && void act(`${itemId}`, "PATCH", { unit: e.target.value })}
            >
              <option value="">—</option>
              {units.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.code}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-small" onClick={() => setMerging(true)}>
            Merge into…
          </button>
        </div>
      )}
      {canEdit && item.merged_into && (
        <div className="toolbar item-actions">
          <button className="btn btn-small" onClick={() => void act(`${itemId}/unmerge`, "POST")}>
            Unmerge
          </button>
        </div>
      )}

      <h3 className="section-title">Source lines</h3>
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
              <th />
            </tr>
          </thead>
          <tbody>
            {lines?.map((l) => (
              <tr key={l.id} className={l.is_competitor || l.is_excluded ? "row-flagged" : ""}>
                <td>
                  {l.channel ?? "—"}
                  {!l.from_eespl_file && (
                    <span className="badge badge-muted" title="Not an EESPL-priced file">
                      other file
                    </span>
                  )}
                </td>
                <td className="small" title={l.file}>
                  {l.file.split("/").pop()}
                  <span className="muted">
                    {" "}
                    {l.sheet} r{l.row}
                  </span>
                  {l.library_item_id !== itemId && <span className="badge badge-muted">merged</span>}
                </td>
                <td>{l.item_no ?? ""}</td>
                <td>{l.unit_raw ?? "—"}</td>
                <td className="num">{l.qty !== null ? num(l.qty, 3) : <span className="muted">{l.qty_note ?? "—"}</span>}</td>
                <td className="num nowrap">{inr(l.rate)}</td>
                <td>
                  <RateBadges item={l} />
                </td>
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
      {merging && (
        <MergePicker
          item={item}
          onClose={() => setMerging(false)}
          onPick={async (target) => {
            if (!confirm(`Merge this item into “${target.description.slice(0, 80)}” (${target.unit ?? "—"})? You can unmerge later.`))
              return;
            setMerging(false);
            setError(null);
            try {
              await api(`/api/library/items/${itemId}/merge`, { method: "POST", json: { into_id: target.id } });
              onChanged();
              onOpen(target.id);
            } catch (err) {
              setError(errorText(err));
            }
          }}
        />
      )}
    </Modal>
  );
}

function MergePicker({
  item,
  onClose,
  onPick,
}: {
  item: LibraryItemDetail;
  onClose: () => void;
  onPick: (target: LibraryHit) => void;
}) {
  const [q, setQ] = useState(item.description.split(/\s+/).slice(0, 6).join(" "));
  const [hits, setHits] = useState<LibraryHit[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => {
      api<LibrarySearch>(`/api/library/search${queryString({ q, limit: 20, include_flagged: "true" })}`).then(
        (r) => setHits(r.items.filter((h) => h.id !== item.id)),
        () => setHits([]),
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [q, item.id]);

  return (
    <Modal title="Merge into…" onClose={onClose} wide>
      <p className="muted small">
        Choose the item to keep. This item's lines will count towards it and this item leaves search. Nothing is deleted.
      </p>
      <input className="full" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <div className="table-wrap top-gap">
        <table className="table compact">
          <tbody>
            {hits.map((h) => (
              <tr key={h.id} className="clickable" onClick={() => onPick(h)}>
                <td className="desc-cell">
                  <div className="clamp">{h.description}</div>
                </td>
                <td>{h.unit ?? "—"}</td>
                <td className="num nowrap">{inr(h.latest_rate)}</td>
                <td className="num">{h.boq_count} BOQs</td>
              </tr>
            ))}
            {hits.length === 0 && (
              <tr>
                <td className="empty">No matching items.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
