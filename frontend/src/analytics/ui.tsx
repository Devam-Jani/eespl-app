import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, inr, inrCompact } from "../format";

export type Drill = Record<string, string | number> & { kind: string };
export type Tile = {
  key: string;
  label: string;
  value: number | string | null;
  unit: "inr" | "count" | "pct" | "text";
  prev: number | string | null;
  prev_label: string | null;
  drill: Drill | null;
  as_of: string | null;
  note: string | null;
};
export type Column = { key: string; label: string; unit: string };
export type Table = { title: string; columns: Column[]; rows: Record<string, unknown>[]; note: string | null };

const FILTER_KEYS = ["date_from", "date_to", "region", "salesperson", "client_type", "site_status", "demo"] as const;

export function fmtValue(value: unknown, unit: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (unit === "inr") return inr(value as string);
  if (unit === "pct") return `${Number(value).toFixed(1)}%`;
  if (unit === "count") return Number(value).toLocaleString("en-IN");
  if (unit === "num" || unit === "qty") return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  if (unit === "date") return new Date(`${String(value).slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  if (unit === "bool") return value ? "yes" : "";
  return String(value).replace(/_/g, " ");
}

export function asOf(value: string | null | undefined): string {
  if (!value) return "not refreshed yet";
  return `as of ${new Date(value).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`;
}

/** The filters live in the URL, so a filtered view can be shared and the back button works. */
export function useFilters() {
  const [params, setParams] = useSearchParams();
  const values = useMemo(() => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<(typeof FILTER_KEYS)[number], string>, [params]);
  const qs = useMemo(() => {
    const q = new URLSearchParams();
    for (const k of FILTER_KEYS) if (values[k]) q.set(k, k === "demo" ? "true" : values[k]);
    return q.toString();
  }, [values]);
  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }
  return { values, qs, set, demo: values.demo === "1" || values.demo === "true" };
}

export function drillHref(drill: Drill | Record<string, unknown>, demo: boolean, extra = ""): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(drill)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  if (demo) q.set("demo", "1");
  return `/drill?${q.toString()}${extra}`;
}

export function ExportButton({ path, label = "Excel" }: { path: string; label?: string }) {
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);
  if (!can("reports.export")) return null;
  return (
    <button
      className="btn btn-small btn-ghost"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void downloadFile(path)
          .catch((err) => alert(errorText(err)))
          .finally(() => setBusy(false));
      }}
    >
      {busy ? "…" : `⤓ ${label}`}
    </button>
  );
}

export function change(t: Tile): ReactNode {
  if (t.prev === null || t.prev === undefined || !["inr", "count", "pct"].includes(t.unit)) return null;
  const diff = Number(t.value ?? 0) - Number(t.prev ?? 0);
  const arrow = diff > 0 ? "▲" : diff < 0 ? "▼" : "=";
  return (
    <span className="tile-change" title={`Previous: ${fmtValue(t.prev, t.unit)}`}>
      {arrow} {t.unit === "inr" ? inrCompact(Math.abs(diff)) : fmtValue(Math.abs(diff), t.unit)} vs {t.prev_label}
    </span>
  );
}

export function KpiTile({ tile, demo }: { tile: Tile; demo: boolean }) {
  const href = tile.drill ? drillHref(tile.drill, demo) : null;
  const body = (
    <>
      <span className="kpi-label">{tile.label}</span>
      <span className="kpi-value" title={tile.unit === "inr" ? fmtValue(tile.value, "inr") : undefined}>
        {tile.unit === "inr" ? inrCompact(tile.value as number) : fmtValue(tile.value, tile.unit)}
      </span>
      {change(tile)}
      {tile.note && <span className="muted small">{tile.note}</span>}
      {tile.as_of && <span className="kpi-asof">{asOf(tile.as_of)}</span>}
    </>
  );
  return (
    <div className="kpi">
      {href ? (
        <Link to={href} className="kpi-link" title="Open the records behind this number">
          {body}
        </Link>
      ) : (
        <div className="kpi-link">{body}</div>
      )}
      {tile.drill && (
        <span className="kpi-export">
          <ExportButton path={`/api${drillHref(tile.drill, demo, "&format=xlsx").replace("/drill?", "/analytics/drill?")}`} label="" />
        </span>
      )}
    </div>
  );
}

export function DataTable({ table, demo, limit }: { table: Table; demo: boolean; limit?: number }) {
  const [all, setAll] = useState(false);
  const rows = limit && !all ? table.rows.slice(0, limit) : table.rows;
  return (
    <div className="table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            {table.columns.map((c) => (
              <th key={c.key} className={["inr", "pct", "count", "num", "qty"].includes(c.unit) ? "num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {table.columns.map((c, j) => {
                const v = fmtValue(r[c.key], c.unit);
                const link = j === 0 ? (r.drill ? drillHref(r.drill as Drill, demo) : (r.link as string | undefined)) : undefined;
                return (
                  <td key={c.key} className={["inr", "pct", "count", "num", "qty"].includes(c.unit) ? "num" : undefined}>
                    {link ? <Link to={link}>{v}</Link> : v}
                  </td>
                );
              })}
            </tr>
          ))}
          {table.rows.length === 0 && (
            <tr>
              <td colSpan={table.columns.length} className="empty">
                Nothing in this range.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {limit && table.rows.length > limit && (
        <button className="btn btn-small btn-ghost" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${table.rows.length}`}
        </button>
      )}
      {table.note && <p className="muted small">{table.note}</p>}
    </div>
  );
}

type Options = { regions: string[]; salespeople: { id: string; name: string }[]; client_types: string[]; site_statuses: string[] };

export function FilterBar({ show = ["dates", "region", "salesperson", "client_type", "site_status"], demoToggle = true }: { show?: string[]; demoToggle?: boolean }) {
  const { values, set, demo } = useFilters();
  const { can } = useAuth();
  const [opts, setOpts] = useState<Options | null>(null);
  const [demoAvailable, setDemoAvailable] = useState(false);
  useEffect(() => {
    api<Options>(`/api/analytics/filters${demo ? "?demo=true" : ""}`).then(setOpts, () => setOpts(null));
  }, [demo]);
  useEffect(() => {
    api<{ demo_available: boolean }>("/api/dashboard").then(
      (r) => setDemoAvailable(r.demo_available),
      () => undefined,
    );
  }, []);
  return (
    <div className="filters analytics-filters">
      {show.includes("dates") && (
        <>
          <label className="small">
            From <input type="date" value={values.date_from} onChange={(e) => set("date_from", e.target.value)} />
          </label>
          <label className="small">
            To <input type="date" value={values.date_to} onChange={(e) => set("date_to", e.target.value)} />
          </label>
        </>
      )}
      {show.includes("region") && opts && opts.regions.length > 0 && (
        <select aria-label="Region" value={values.region} onChange={(e) => set("region", e.target.value)}>
          <option value="">All regions</option>
          {opts.regions.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      )}
      {show.includes("salesperson") && opts && opts.salespeople.length > 0 && (
        <select aria-label="Salesperson" value={values.salesperson} onChange={(e) => set("salesperson", e.target.value)}>
          <option value="">All salespeople</option>
          {opts.salespeople.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      {show.includes("client_type") && opts && (
        <select aria-label="Client type" value={values.client_type} onChange={(e) => set("client_type", e.target.value)}>
          <option value="">All client types</option>
          {opts.client_types.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      )}
      {show.includes("site_status") && opts && (
        <select aria-label="Site status" value={values.site_status} onChange={(e) => set("site_status", e.target.value)}>
          <option value="">Open sites</option>
          {opts.site_statuses.map((t) => (
            <option key={t} value={t}>
              {t.replace("_", " ")}
            </option>
          ))}
        </select>
      )}
      {demoToggle && can("dashboard.company") && (demoAvailable || demo) && (
        <label className={`check demo-switch ${demo ? "on" : ""}`}>
          <input type="checkbox" checked={demo} onChange={(e) => set("demo", e.target.checked ? "1" : "")} /> Demo company (invented data)
        </label>
      )}
    </div>
  );
}

export function useData<T>(path: string | null): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setError(null);
    api<T>(path).then(
      (d) => alive && setData(d),
      (err) => alive && setError(errorText(err)),
    );
    return () => {
      alive = false;
    };
  }, [path, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}
