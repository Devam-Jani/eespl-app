import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, inr } from "../format";
import { NearRates } from "./Picker";
import type { Brief, Proposal, ProductRow } from "./Picker";

type Report = {
  last_run: Record<string, unknown>;
  live: {
    files: number;
    files_by_status: Record<string, number>;
    files_by_kind: Record<string, number>;
    lines: number;
    lines_with_working: number;
    lines_with_place: number;
    lines_with_date: number;
    lines_with_area: number;
    lines_qro: number;
    lines_nq: number;
    lines_to_check: number;
    failed: { path: string; error: string }[];
    scanned: string[];
  };
  templates: number;
  top: Brief[];
  source_folder: string | null;
};

/** The library: the reading report and the templates. */
export function KnowledgeHome() {
  const [r, setR] = useState<Report | null>(null);
  const [rows, setRows] = useState<Brief[]>([]);
  const [params, setParams] = useSearchParams();
  const [areas, setAreas] = useState<{ key: string; label: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const q = params.get("q") ?? "";
  const area = params.get("area") ?? "";
  useEffect(() => {
    api<Report>("/api/knowledge/report").then(setR, (e) => setError(errorText(e)));
    api<{ areas: { key: string; label: string }[] }>("/api/knowledge/options").then(
      (o) => setAreas(o.areas),
      () => undefined,
    );
  }, []);
  useEffect(() => {
    api<Brief[]>(`/api/knowledge/templates?limit=300${q ? `&q=${encodeURIComponent(q)}` : ""}${area ? `&area=${area}` : ""}`).then(setRows, (e) => setError(errorText(e)));
  }, [q, area]);
  const setP = (k: string, v: string) => {
    const n = new URLSearchParams(params);
    if (v) n.set(k, v);
    else n.delete(k);
    setParams(n, { replace: true });
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>BOQ knowledge</h1>
          <p className="muted">
            What our old BOQs say: the client lines, the build-ups in their workings, the place and the date, grouped into specification templates a new BOQ starts from.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {r && (
        <div className="card">
          <h2 className="section-title">Reading report</h2>
          <div className="stat-row">
            <Stat label="Files read" value={r.live.files_by_status.read ?? 0} />
            <Stat label="Failed" value={r.live.files_by_status.failed ?? 0} warn />
            <Stat label="Scanned, not read" value={r.live.files_by_status.scanned ?? 0} />
            <Stat label="Not a BOQ" value={r.live.files_by_status.not_boq ?? 0} />
            <Stat label="Lines found" value={r.live.lines} />
            <Stat label="With a working" value={r.live.lines_with_working} />
            <Stat label="With a place" value={r.live.lines_with_place} />
            <Stat label="With a date" value={r.live.lines_with_date} />
            <Stat label="Templates" value={r.templates} />
          </div>
          <p className="small muted">
            Files by type:{" "}
            {Object.entries(r.live.files_by_kind)
              .map(([k, v]) => `${k === "lib" ? "historic import" : k} ${v}`)
              .join(", ")}{" "}
            · QRO {r.live.lines_qro} · NQ {r.live.lines_nq} · to check {r.live.lines_to_check} · read from {r.source_folder ?? "—"} (copies of the originals; the originals are
            never changed)
          </p>
          {r.live.failed.length > 0 && (
            <details>
              <summary className="small">{r.live.failed.length} files failed, with the reason</summary>
              <table className="table compact">
                <tbody>
                  {r.live.failed.map((f) => (
                    <tr key={f.path}>
                      <td className="small">{f.path}</td>
                      <td className="small text-danger">{f.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {r.live.scanned.length > 0 && (
            <details>
              <summary className="small">{r.live.scanned.length} scanned PDFs, not read (no OCR yet)</summary>
              <ul className="small">
                {r.live.scanned.slice(0, 200).map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <div className="card top-gap">
        <div className="form-row">
          <input value={q} onChange={(e) => setP("q", e.target.value)} placeholder="Search templates (sunken toilet, crystalline, PU…)" aria-label="Search" />
          <select value={area} onChange={(e) => setP("area", e.target.value)} aria-label="Area">
            <option value="">All areas</option>
            {areas.map((a) => (
              <option key={a.key} value={a.key}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
        <table className="table compact">
          <thead>
            <tr>
              <th>Template</th>
              <th className="num">BOQs</th>
              <th className="num">Lines</th>
              <th className="num">Median rate</th>
              <th>Latest</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td>
                  <Link to={`/knowledge/templates/${t.id}`}>{t.name}</Link> {t.to_check && <span className="badge badge-warn">to check</span>}
                  {t.reviewed && <span className="badge badge-ok">reviewed</span>}
                  <div className="small muted">{t.description.slice(0, 140)}…</div>
                </td>
                <td className="num">{t.boqs}</td>
                <td className="num">{t.lines}</td>
                <td className="num">
                  {inr(t.median_rate)}
                  <span className="small muted"> /{t.unit}</span>
                </td>
                <td className="small">{t.latest_on ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Stat({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className={`stat ${warn && value ? "text-danger" : ""}`}>
      <div className="stat-value">{value.toLocaleString("en-IN")}</div>
      <div className="stat-label small muted">{label}</div>
    </div>
  );
}

type Row = {
  line_id: number;
  rate: string;
  city: string | null;
  region: string | null;
  on_date: string | null;
  old: boolean;
  folder: string | null;
  qty: string | null;
  qty_note: string | null;
  file: string | null;
  sheet: string | null;
  row: number | null;
  cost?: string | null;
  margin_percent?: string | null;
  to_check: boolean;
};
type Template = Brief & {
  rates: Proposal["rates"] & { rows: Row[]; old_after_months: number };
  products?: { products: ProductRow[]; labour_sqft: string | null; surface_prep_sqm: string | null; workings: number };
  margins?: {
    all: { n: number; min: number; median: number; max: number } | null;
    usual?: string;
    by_client: Record<string, { n: number; median: number; min: number; max: number } | null>;
  };
  can_edit: boolean;
  sees_cost: boolean;
  fixes: { field: string; old: string | null; new: string | null; reason: string; at: string }[];
};

/** One template: the standard description and the method statement, the products and consumption per
 * surface, every past rate by location (city, region, all; old ones flagged), and the margins. */
export function TemplatePage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [city, setCity] = useState("Ahmedabad");
  const [t, setT] = useState<Template | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ name: string; description: string; steps: string } | null>(null);
  const [fix, setFix] = useState<{ line: number; field: string; value: string; reason: string } | null>(null);
  const [mergeInto, setMergeInto] = useState("");
  const load = useCallback(() => api<Template>(`/api/knowledge/templates/${id}?city=${encodeURIComponent(city)}`).then(setT, (e) => setError(errorText(e))), [id, city]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(p: Promise<unknown>) {
    setError(null);
    try {
      await p;
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!t) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <p className="breadcrumb">
        <Link to="/knowledge">BOQ knowledge</Link> / template {t.id}
      </p>
      <div className="page-header">
        <div>
          <h1>
            {t.name} {t.hidden && <span className="badge badge-muted">hidden</span>} {t.to_check && <span className="badge badge-warn">to check</span>}
          </h1>
          <p className="muted">
            {t.boqs} BOQ(s), {t.lines} line(s) · per {t.unit} {t.margins?.usual && <b>· margin {t.margins.usual} here</b>}
          </p>
        </div>
        {t.can_edit && (
          <div className="page-actions">
            <button className="btn" onClick={() => setEdit({ name: t.name, description: t.description, steps: t.steps.join("\n") })}>
              Edit
            </button>
            <button className="btn" onClick={() => void run(api(`/api/knowledge/templates/${t.id}`, { method: "PUT", json: { hidden: !t.hidden } }))}>
              {t.hidden ? "Show" : "Hide"}
            </button>
            <span className="inline-form">
              <input className="input-small" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)} placeholder="template no." aria-label="Merge into" />
              <button
                className="btn btn-small"
                disabled={!mergeInto}
                onClick={() => void run(api(`/api/knowledge/templates/${t.id}/merge`, { method: "POST", json: { into_id: Number(mergeInto) } }))}
              >
                Merge into
              </button>
            </span>
          </div>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {edit && (
        <div className="card">
          <label className="field">
            <span>Name</span>
            <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          </label>
          <label className="field">
            <span>Standard description (the client text)</span>
            <textarea rows={6} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
          </label>
          <label className="field">
            <span>Method statement (one step a line)</span>
            <textarea rows={6} value={edit.steps} onChange={(e) => setEdit({ ...edit, steps: e.target.value })} />
          </label>
          <button
            className="btn btn-primary"
            onClick={() =>
              void run(
                api(`/api/knowledge/templates/${t.id}`, {
                  method: "PUT",
                  json: {
                    name: edit.name,
                    description: edit.description,
                    steps: edit.steps
                      .split("\n")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  },
                }),
              ).then(() => setEdit(null))
            }
          >
            Save
          </button>
        </div>
      )}
      <div className="grid-2">
        <div className="card">
          <h3>Standard description</h3>
          <p className="small">{t.description}</p>
          <h3>Method statement</h3>
          {t.steps.length ? (
            <ol className="small">
              {t.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          ) : (
            <p className="small muted">No steps yet.</p>
          )}
          {t.steps_source && <p className="small muted">From the {t.steps_source}.</p>}
          {t.products && (
            <>
              <h3>Products and consumption (from {t.products.workings} working(s))</h3>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Consumption per surface</th>
                    <th className="num">Price</th>
                    <th className="num">Freight</th>
                    <th className="num">BOQs</th>
                  </tr>
                </thead>
                <tbody>
                  {t.products.products.map((p) => (
                    <tr key={p.label}>
                      <td>
                        {p.label}
                        {!p.product_id && <div className="small text-warn">not in the product master</div>}
                      </td>
                      <td className="small">
                        {Object.entries(p.consumption_by_surface)
                          .map(([s, v]) => `${s === "any" ? "any surface" : s}: ${v.median} (${v.n})`)
                          .join(" · ")}
                      </td>
                      <td className="num">{inr(p.price_median)}</td>
                      <td className="num">{inr(p.freight_median)}</td>
                      <td className="num">{p.boqs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">
                Labour {t.products.labour_sqft ? `₹${t.products.labour_sqft} per sq ft` : "—"} · surface preparation{" "}
                {t.products.surface_prep_sqm ? `₹${t.products.surface_prep_sqm} per sqm` : "—"}
              </p>
            </>
          )}
          {t.margins?.all && (
            <>
              <h3>Margin carried (on the selling price)</h3>
              <p className="small">
                {t.margins.all.n} working(s): {t.margins.all.min} to {t.margins.all.max} %, median {t.margins.all.median} %.
              </p>
              <table className="table compact">
                <tbody>
                  {Object.entries(t.margins.by_client).map(([k, v]) =>
                    v ? (
                      <tr key={k}>
                        <td className="small">{k}</td>
                        <td className="num small">
                          {v.median} % ({v.n})
                        </td>
                      </tr>
                    ) : null,
                  )}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div className="card">
          <div className="form-row">
            <h3>Past rates by location</h3>
            <input value={city} onChange={(e) => setCity(e.target.value)} aria-label="Location" placeholder="City" />
          </div>
          <NearRates r={t.rates} />
          <p className="small muted">Older than {t.rates.old_after_months} months: marked old.</p>
          <table className="table compact">
            <thead>
              <tr>
                <th>Date</th>
                <th>Place</th>
                <th className="num">Rate</th>
                {t.sees_cost && <th className="num">Cost</th>}
                {t.sees_cost && <th className="num">Margin</th>}
                <th>From</th>
                {t.can_edit && <th />}
              </tr>
            </thead>
            <tbody>
              {t.rates.rows.slice(0, 80).map((r) => (
                <tr key={r.line_id} className={r.to_check ? "row-warn" : ""}>
                  <td className="small">
                    {r.on_date ?? "—"} {r.old && <span className="badge badge-muted">old</span>}
                  </td>
                  <td className="small">{[r.city, r.region].filter(Boolean).join(", ") || "—"}</td>
                  <td className="num">
                    {inr(r.rate)} {r.qty_note && <span className="small muted">{r.qty_note}</span>}
                  </td>
                  {t.sees_cost && <td className="num">{inr(r.cost ?? null)}</td>}
                  {t.sees_cost && <td className="num">{r.margin_percent ? `${r.margin_percent} %` : "—"}</td>}
                  <td className="small muted" title={r.file ?? ""}>
                    {(r.file ?? "").split("/").slice(-1)[0]} · {r.sheet} · row {r.row}
                  </td>
                  {t.can_edit && (
                    <td>
                      <button className="btn btn-small btn-ghost" onClick={() => setFix({ line: r.line_id, field: "rate", value: r.rate, reason: "" })}>
                        Fix
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {fix && (
            <div className="form-row">
              <select value={fix.field} onChange={(e) => setFix({ ...fix, field: e.target.value })} aria-label="Field">
                {["rate", "city", "on_date", "surface", "coats", "min_kg_sqm", "template_id", "hidden"].map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
              <input value={fix.value} onChange={(e) => setFix({ ...fix, value: e.target.value })} aria-label="Value" />
              <input value={fix.reason} onChange={(e) => setFix({ ...fix, reason: e.target.value })} placeholder="Reason (required)" aria-label="Reason" />
              <button
                className="btn btn-small btn-primary"
                disabled={fix.reason.trim().length < 5}
                onClick={() =>
                  void run(
                    api(`/api/knowledge/lines/${fix.line}`, {
                      method: "PUT",
                      json: { field: fix.field, value: fix.field === "hidden" ? fix.value === "true" : fix.value || null, reason: fix.reason },
                    }),
                  ).then(() => setFix(null))
                }
              >
                Save the fix
              </button>
            </div>
          )}
          {t.fixes.length > 0 && (
            <details>
              <summary className="small">{t.fixes.length} change(s) by hand</summary>
              <ul className="small">
                {t.fixes.map((f, i) => (
                  <li key={i}>
                    {f.field}: {f.old ?? "—"} → {f.new ?? "—"} ({f.reason})
                  </li>
                ))}
              </ul>
            </details>
          )}
          {!can("knowledge.cost") && <p className="small muted">Costs and margins are for the estimator, planning and the director.</p>}
        </div>
      </div>
    </>
  );
}

type MatchRow = {
  match_id: number;
  line_id: number;
  description: string;
  unit: string | null;
  template: Brief | null;
  confidence: string | null;
  status: string;
  median_near: string | null;
  median_where: string | null;
};

/** An imported client BOQ (the client's own Excel): each line matched to a template, with a
 * confidence, to accept or change. */
export function MatchPage() {
  const { id } = useParams();
  const [d, setD] = useState<{ tender: { code: string; name: string }; city: string | null; lines: MatchRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<typeof d>(`/api/knowledge/match/tenders/${id}`).then(setD, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!d) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Matching…</p>;
  const set = (m: MatchRow, status: string, template_id: number | null) =>
    api(`/api/knowledge/match/${m.match_id}`, { method: "PUT", json: { status, template_id } }).then(load, (e) => setError(errorText(e)));
  return (
    <>
      <p className="breadcrumb">
        <Link to="/knowledge">BOQ knowledge</Link> / {d.tender.code}
      </p>
      <div className="page-header">
        <div>
          <h1>Client BOQ matched to the library: {d.tender.name}</h1>
          <p className="muted">Each line with the template that fits best and how sure the match is{d.city ? `; past rates near ${d.city}` : ""}. Accept it or pick another.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Client line</th>
            <th>Template</th>
            <th className="num">Confidence</th>
            <th className="num">Median near</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {d.lines.map((m) => (
            <tr key={m.match_id} className={m.status === "accepted" ? "row-ok" : Number(m.confidence) < 50 ? "row-warn" : ""}>
              <td className="small">
                {m.description.slice(0, 160)}
                {m.description.length > 160 ? "…" : ""} <span className="muted">({m.unit})</span>
              </td>
              <td className="small">{m.template ? <Link to={`/knowledge/templates/${m.template.id}`}>{m.template.name}</Link> : <span className="muted">no template</span>}</td>
              <td className="num">
                <span className={`badge ${Number(m.confidence) >= 70 ? "badge-ok" : Number(m.confidence) >= 50 ? "badge-muted" : "badge-warn"}`}>{m.confidence ?? 0} %</span>
              </td>
              <td className="num small">
                {inr(m.median_near)} <span className="muted">{m.median_where}</span>
              </td>
              <td>
                {m.status === "accepted" ? (
                  <span className="badge badge-ok">accepted</span>
                ) : (
                  <>
                    {m.template && (
                      <button className="btn btn-small" onClick={() => void set(m, "accepted", m.template!.id)}>
                        Accept
                      </button>
                    )}
                    <button
                      className="btn btn-small btn-ghost"
                      onClick={() => {
                        const v = window.prompt("Template number (blank: none)");
                        if (v === null) return;
                        void set(m, v.trim() ? "changed" : "none", v.trim() ? Number(v) : null);
                      }}
                    >
                      Change
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
