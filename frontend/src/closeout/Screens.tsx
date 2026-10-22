import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";
import type { Tracked } from "../team/Pages";
import { CertifyForm } from "../team/Pages";

const d = (v: string | null | undefined) =>
  v ? new Date(v.length === 10 ? `${v}T00:00:00` : v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const num = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits });
const inr = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹ ${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;

function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!path) return;
    api<T>(path).then(setData, (e) => setError(errorText(e)));
  }, [path]);
  useEffect(load, [load]);
  return { data, setData, error, setError, load };
}

async function run<T>(p: Promise<T>, setError: (e: string | null) => void): Promise<T | undefined> {
  setError(null);
  try {
    return await p;
  } catch (e) {
    setError(errorText(e));
  }
}

// --- Settings > Client roles ----------------------------------------------------------------------

type RoleDef = { code: string; label: string; rights: string[]; default_rights: string[] };
type Roles = { rights: string[]; right_labels: Record<string, string>; roles: RoleDef[] };

/** The default rights of each client role, as a grid of ticks; a change applies to new invites (and is logged). */
export function ClientRolesSettings() {
  const { data, setData, error, setError } = useLoad<Roles>("/api/closeout/client-roles");
  const [saving, setSaving] = useState<string | null>(null);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const save = async (r: RoleDef, rights: string[]) => {
    setSaving(r.code);
    const out = await run(api<Roles>(`/api/closeout/client-roles/${r.code}`, { method: "PUT", json: { rights } }), setError);
    if (out) setData(out);
    setSaving(null);
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Client roles</h1>
          <p className="muted">
            What each role of the client's people may see and do in the portal. The ticks are the defaults given at an invite; every change is in the audit log.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table role-grid">
          <thead>
            <tr>
              <th>Right</th>
              {data.roles.map((r) => (
                <th key={r.code} className="center">
                  {r.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rights.map((right) => (
              <tr key={right}>
                <td>
                  {data.right_labels[right] ?? right}
                  <div className="small muted">{right}</div>
                </td>
                {data.roles.map((r) => {
                  const on = r.rights.includes(right);
                  const changed = on !== r.default_rights.includes(right);
                  return (
                    <td key={r.code} className={`center ${changed ? "changed" : ""}`}>
                      <input
                        type="checkbox"
                        aria-label={`${r.label}: ${right}`}
                        checked={on}
                        disabled={saving === r.code}
                        onChange={() => void save(r, on ? r.rights.filter((x) => x !== right) : [...r.rights, right])}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td />
              {data.roles.map((r) => (
                <td key={r.code} className="center">
                  <button
                    className="btn btn-small"
                    disabled={r.rights.slice().sort().join() === r.default_rights.slice().sort().join()}
                    onClick={() => void run(api<Roles>(`/api/closeout/client-roles/${r.code}/reset`, { method: "POST" }), setError).then((x) => x && setData(x))}
                  >
                    Reset to default
                  </button>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <p className="small muted">A tick that differs from the default is shaded.</p>
      </div>
    </>
  );
}

// --- the measurement book: entry on site (works at 360 px) ------------------------------------------

type Place = { id: number; parent_id: number | null; kind: string; name: string; path: string };
type CadArea = { id: number; name: string; node_id: number | null; area_sqm: string | null; perimeter_m: string | null };
type BookLine = { id: number; description: string; unit: string; rate: string | null; source: string | null; how: string };
type MLine = {
  id: number;
  description: string;
  place: string | null;
  qty: string;
  unit: string;
  status: string;
  approved_name: string | null;
  recorded_by_staff: boolean;
  zone_reason: string | null;
  billed_in: string | null;
  photos: number;
  shown?: Record<string, string>;
  changes: { id: number; field: string; old_shown?: string; new_shown?: string; remark: string | null; by: string; at: string; status: string }[];
};
type Form = { places: Place[]; cad_areas: CadArea[]; lines: BookLine[]; needs_approval: boolean; site: string };
export type Size = { mode: "m" | "ft"; m: string; ft: string; inch: string };
const emptySize = (): Size => ({ mode: "m", m: "", ft: "", inch: "" });
export const sizeOut = (s: Size) => (s.mode === "m" ? s.m.trim() : [s.ft.trim() ? `${s.ft.trim()} ft` : "", s.inch.trim() ? `${s.inch.trim()} in` : ""].filter(Boolean).join(" "));
const FT = 0.3048;
const IN = 0.0254;
/** The size in metres (for the live quantity); NaN when empty. */
export function metres(s: Size): number {
  if (s.mode === "m") return s.m.trim() ? Number(s.m) : NaN;
  if (!s.ft.trim() && !s.inch.trim()) return NaN;
  return Number(s.ft || 0) * FT + Number(s.inch || 0) * IN;
}

/** The line's quantity in its unit from the sizes as typed (running length for rmt, L x B or perimeter x height for sqm). */
export function lineQty(how: "lb" | "ph" | "run", a: Size, b: Size, ded: string, unit: string): number | null {
  const x = metres(a);
  const y = metres(b);
  let q = NaN;
  if (how === "run") q = x;
  else if (!Number.isNaN(x) && !Number.isNaN(y)) q = x * y;
  if (unit === "sqft") q *= 10.7639;
  if (unit === "rft") q /= FT;
  return Number.isNaN(q) ? null : Math.max(0, q - Number(ded || 0));
}

function SizeInput({ label, value, onChange }: { label: string; value: Size; onChange: (s: Size) => void }) {
  return (
    <div className="size-input">
      <div className="size-head">
        <span>{label}</span>
        <div className="seg seg-small" role="group" aria-label={`${label} unit`}>
          <button type="button" className={value.mode === "m" ? "on" : ""} onClick={() => onChange({ ...value, mode: "m" })}>
            m
          </button>
          <button type="button" className={value.mode === "ft" ? "on" : ""} onClick={() => onChange({ ...value, mode: "ft" })}>
            ft + in
          </button>
        </div>
      </div>
      {value.mode === "m" ? (
        <input
          className="tap-input"
          inputMode="decimal"
          placeholder="metres"
          value={value.m}
          onChange={(e) => onChange({ ...value, m: e.target.value })}
          aria-label={`${label} in metres`}
        />
      ) : (
        <div className="ft-in">
          <input
            className="tap-input"
            inputMode="numeric"
            placeholder="ft"
            value={value.ft}
            onChange={(e) => onChange({ ...value, ft: e.target.value })}
            aria-label={`${label} feet`}
          />
          <input
            className="tap-input"
            inputMode="decimal"
            placeholder="in"
            value={value.inch}
            onChange={(e) => onChange({ ...value, inch: e.target.value })}
            aria-label={`${label} inches`}
          />
        </div>
      )}
      {value.mode === "ft" && !Number.isNaN(metres(value)) && <div className="small muted">= {metres(value).toFixed(3)} m</div>}
    </div>
  );
}

/** Our billing team on site: pick the place (or the drawing's area), the line (its unit is the work order's), the sizes in m or ft + in, deductions, photos; then send sets to the client. */
export function MeasureEntry() {
  const { id } = useParams();
  const form = useLoad<Form>(`/api/closeout/sites/${id}/measure-form`);
  const book = useLoad<{ needs_approval: boolean; lines: MLine[] }>(`/api/closeout/sites/${id}/measurements`);
  const [error, setError] = useState<string | null>(null);
  const [placeId, setPlaceId] = useState("");
  const [cadId, setCadId] = useState("");
  const [lineId, setLineId] = useState("");
  const [how, setHow] = useState<"lb" | "ph" | "run">("lb");
  const [a, setA] = useState<Size>(emptySize());
  const [b, setB] = useState<Size>(emptySize());
  const [ded, setDed] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sel, setSel] = useState<number[]>([]);
  const [saved, setSaved] = useState<string | null>(null);
  const places = useMemo(() => form.data?.places ?? [], [form.data]);
  const kids = useMemo(() => {
    const k: Record<string, Place[]> = {};
    places.forEach((p) => (k[String(p.parent_id)] = [...(k[String(p.parent_id)] ?? []), p]));
    return k;
  }, [places]);
  const line = form.data?.lines.find((l) => String(l.id) === lineId);
  const unit = line?.unit ?? "sqm";
  const linear = unit === "rmt" || unit === "rft";
  useEffect(() => {
    if (linear) setHow("run");
    else if (how === "run") setHow("lb");
  }, [linear, how]);
  const qty = useMemo(() => lineQty(how, a, b, ded, unit), [a, b, ded, how, unit]);
  if (!form.data) return form.error ? <div className="alert alert-error">{form.error}</div> : <p className="muted">Loading…</p>;
  const pathOf = (pid: string) => places.find((p) => String(p.id) === pid)?.path ?? "";
  const levels: Place[][] = [];
  let cur: string | null = "null";
  const chosen: string[] = [];
  // the place picker: tower, then floor or flat, then the area (each level a select)
  const chain = placeId ? pathIds(places, Number(placeId)) : [];
  for (let i = 0; i < 4; i++) {
    const opts: Place[] = kids[cur ?? "null"] ?? [];
    if (!opts.length) break;
    levels.push(opts);
    const pick: number | undefined = chain[i];
    if (pick === undefined) break;
    chosen.push(String(pick));
    cur = String(pick);
  }
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaved(null);
    const body: Record<string, unknown> = {
      description: `${pathOf(placeId)}${note ? ` — ${note}` : ""}` || line?.description || "Measurement",
      contract_line_id: line ? line.id : null,
      node_id: placeId ? Number(placeId) : null,
      cad_area_id: cadId ? Number(cadId) : null,
      deductions_sqm: ded || null,
      zone_reason: reason || null,
      note: note || null,
    };
    if (how === "run") body.length_m = sizeOut(a);
    else if (how === "lb") Object.assign(body, { length_m: sizeOut(a), breadth_m: sizeOut(b) });
    else Object.assign(body, { perimeter_m: sizeOut(a), height_m: sizeOut(b) });
    const m = await run(api<MLine & { warning?: string }>(`/api/closeout/sites/${id}/measurements`, { method: "POST", json: body }), setError);
    if (!m) return;
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      await run(api(`/api/closeout/measurements/${m.id}/photos`, { method: "POST", form: fd }), setError);
    }
    setSaved(`Saved: ${m.place ?? ""} ${num(m.qty, 3)} ${m.unit}${m.warning ? ` (${m.warning})` : ""}`);
    setA(emptySize());
    setB(emptySize());
    setDed("");
    setFiles([]);
    setReason("");
    book.load();
  };
  const toSend = (book.data?.lines ?? []).filter((m) => m.status === "draft" || m.status === "disputed");
  return (
    <div className="measure-page">
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>{form.data.site}</Link> / measurement book
          </p>
          <h1>Measure</h1>
          <p className="muted small">
            {form.data.needs_approval ? "Each line goes to the client for approval; bills take only approved lines." : "Lines are approved when written on this site."}
          </p>
        </div>
      </div>
      {(error || form.error) && <div className="alert alert-error">{error || form.error}</div>}
      {saved && <div className="alert alert-ok">{saved}</div>}
      <form className="card measure-form" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span>Item (its unit is the work order's)</span>
          <select className="tap-input" value={lineId} onChange={(e) => setLineId(e.target.value)} required>
            <option value="">Pick the item…</option>
            {form.data.lines.map((l) => (
              <option key={l.id} value={l.id}>
                {l.description.slice(0, 60)} · per {l.unit}
              </option>
            ))}
          </select>
          {line && <span className="small muted">{line.how}</span>}
        </label>
        <div className="place-pick">
          {levels.map((opts, i) => (
            <label key={i} className="field">
              <span>{["Tower / block", "Floor or flat", "Flat or area", "Area"][i]}</span>
              <select
                className="tap-input"
                value={chosen[i] ?? ""}
                onChange={(e) => {
                  setPlaceId(e.target.value || (i > 0 ? (chosen[i - 1] ?? "") : ""));
                  setCadId("");
                }}
              >
                <option value="">—</option>
                {opts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        {form.data.cad_areas.length > 0 && (
          <label className="field">
            <span>Or the drawing's area</span>
            <select
              className="tap-input"
              value={cadId}
              onChange={(e) => {
                setCadId(e.target.value);
                const ca = form.data?.cad_areas.find((x) => String(x.id) === e.target.value);
                if (ca?.node_id) setPlaceId(String(ca.node_id));
              }}
            >
              <option value="">—</option>
              {form.data.cad_areas.map((ca) => (
                <option key={ca.id} value={ca.id}>
                  {ca.name}
                  {ca.area_sqm ? ` · ${num(ca.area_sqm, 2)} sqm on the drawing` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {!linear && (
          <div className="seg" role="group" aria-label="How it is measured">
            <button type="button" className={how === "lb" ? "on" : ""} onClick={() => setHow("lb")}>
              L × B
            </button>
            <button type="button" className={how === "ph" ? "on" : ""} onClick={() => setHow("ph")}>
              Perimeter × height
            </button>
          </div>
        )}
        <div className="size-grid">
          <SizeInput label={how === "run" ? "Running length" : how === "lb" ? "Length" : "Perimeter"} value={a} onChange={setA} />
          {how !== "run" && <SizeInput label={how === "lb" ? "Breadth" : "Height"} value={b} onChange={setB} />}
        </div>
        <label className="field">
          <span>Deductions ({linear ? "m" : "sqm"})</span>
          <input className="tap-input" inputMode="decimal" value={ded} onChange={(e) => setDed(e.target.value)} placeholder="0" />
        </label>
        <div className="qty-now">
          Quantity: <b>{qty === null ? "—" : `${qty.toFixed(3)} ${unit}`}</b>
        </div>
        <label className="field">
          <span>Note (optional)</span>
          <input className="tap-input" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <label className="field">
          <span>Reason, if this place is outside our RFI zones</span>
          <input className="tap-input" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <label className="btn tap">
          Photos ({files.length})
          <input type="file" accept="image/*" capture="environment" multiple hidden onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </label>
        <button className="btn btn-primary tap" disabled={!lineId || qty === null}>
          Save the line
        </button>
      </form>
      <div className="card top-gap">
        <div className="bill-head">
          <h2 className="section-title">Lines ({book.data?.lines.length ?? 0})</h2>
          <div className="page-actions">
            <button
              className="btn btn-primary"
              disabled={!sel.length}
              onClick={() => void run(api(`/api/closeout/sites/${id}/measurement-sets`, { method: "POST", json: { ids: sel } }), setError).then(() => (setSel([]), book.load()))}
            >
              Send {sel.length || ""} to the client
            </button>
            <button className="btn" onClick={() => setSel(toSend.map((m) => m.id))} disabled={!toSend.length}>
              Pick all unsent
            </button>
            <button className="btn" onClick={() => void downloadFile(`/api/closeout/sites/${id}/measurement-sheet.xlsx`)}>
              Excel
            </button>
            <button className="btn" onClick={() => void downloadFile(`/api/closeout/sites/${id}/measurement-sheet.pdf`)}>
              PDF
            </button>
          </div>
        </div>
        <div className="m-cards">
          {(book.data?.lines ?? []).map((m) => (
            <div key={m.id} className="m-card m-row">
              <div className="m-head">
                <label className="m-pick">
                  {(m.status === "draft" || m.status === "disputed") && (
                    <input type="checkbox" checked={sel.includes(m.id)} onChange={(e) => setSel(e.target.checked ? [...sel, m.id] : sel.filter((x) => x !== m.id))} />
                  )}
                  <b>{m.place}</b>
                </label>
                <span className={`badge ${m.status === "approved" ? "badge-ok" : m.status === "sent" ? "badge-info" : m.status === "disputed" ? "badge-warn" : "badge-muted"}`}>
                  {m.status}
                </span>
              </div>
              <div className="small muted">{m.description}</div>
              <div className="small">
                {Object.values(m.shown ?? {}).join(" × ")} → <b>{num(m.qty, 3)}</b> {m.unit} {m.photos ? `· ${m.photos} photo(s)` : ""}
              </div>
              {m.zone_reason && <div className="small text-danger">outside our zones: {m.zone_reason}</div>}
              {m.changes.map((c) => (
                <div key={c.id} className="m-change small">
                  {c.field.replace("_m", "")}: <s>{c.old_shown}</s> → <b>{c.new_shown}</b> by {c.by} ({c.status}){c.remark ? ` “${c.remark}”` : ""}
                </div>
              ))}
              {m.approved_name && (
                <div className="small muted">
                  approved by {m.approved_name}
                  {m.recorded_by_staff ? " (recorded by staff)" : ""}
                  {m.billed_in ? ` · billed in ${m.billed_in}` : ""}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function pathIds(places: Place[], idv: number): number[] {
  const out: number[] = [];
  let cur = places.find((p) => p.id === idv);
  while (cur) {
    out.unshift(cur.id);
    const parent: number | null = cur.parent_id;
    cur = parent === null ? undefined : places.find((p) => p.id === parent);
  }
  return out;
}

// --- the quality checklist: per area, each stage's dates and signs ----------------------------------

type Stage = {
  stage: string;
  task_id: number;
  status: string;
  started_on: string | null;
  ended_on: string | null;
  inspection_id: number | null;
  our_sign: string | null;
  result: string | null;
  client_sign: string | null;
  client_signoff: string | null;
  recorded_by_staff: boolean;
};
type QArea = { node_id: number; path: string; stages: Stage[] };

/** On the site's stages: per area, each stage's start and end, our sign and the client's (in the app, or recorded by staff with the signed copy). */
export function QualityChecklist({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const { data, error, setError, load } = useLoad<{ areas: QArea[] }>(`/api/closeout/sites/${siteId}/quality`);
  const [open, setOpen] = useState<number | null>(null);
  const edit = can("closeout.site");
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const sign = (s: Stage) => {
    const started = window.prompt("Stage started on (YYYY-MM-DD)", s.started_on ?? "");
    if (started === null) return;
    const ended = window.prompt("Stage ended on (YYYY-MM-DD)", s.ended_on ?? new Date().toISOString().slice(0, 10));
    if (ended === null) return;
    void run(api(`/api/closeout/tasks/${s.task_id}/quality-sign`, { method: "POST", json: { started_on: started || null, ended_on: ended || null } }), setError).then(load);
  };
  const clientCopy = (s: Stage, f: File | undefined) => {
    if (!f || !s.inspection_id) return;
    const name = window.prompt("Who signed for the client (name and designation)?");
    if (!name) return;
    const fd = new FormData();
    fd.append("signed_name", name);
    fd.append("file", f);
    void run(api(`/api/closeout/inspections/${s.inspection_id}/client-sign-record`, { method: "POST", form: fd }), setError).then(load);
  };
  return (
    <div className="card top-gap">
      <h2 className="section-title">Quality checklist</h2>
      <p className="small muted">
        Per area: each stage's start and end, our sign and the client's. The client signs in the portal, or our staff record the signed paper with its copy.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Area / stage</th>
            <th>Started</th>
            <th>Ended</th>
            <th>Our sign</th>
            <th>Client's sign</th>
          </tr>
        </thead>
        <tbody>
          {data.areas.map((a) => {
            const signed = a.stages.filter((s) => s.our_sign).length;
            const client = a.stages.filter((s) => s.client_sign).length;
            return (
              <Fragment key={a.node_id}>
                <tr className="clickable group-row" onClick={() => setOpen(open === a.node_id ? null : a.node_id)}>
                  <td>
                    <b>{a.path}</b>
                  </td>
                  <td colSpan={2} className="small muted">
                    {a.stages.length} stages
                  </td>
                  <td className="small">
                    {signed}/{a.stages.length}
                  </td>
                  <td className="small">
                    {client}/{a.stages.length}
                  </td>
                </tr>
                {(open === a.node_id || data.areas.length <= 3) &&
                  a.stages.map((s) => (
                    <tr key={s.task_id}>
                      <td className="indent">{s.stage}</td>
                      <td>{d(s.started_on)}</td>
                      <td>{d(s.ended_on)}</td>
                      <td className="small">
                        {s.our_sign ? (
                          <span className="badge badge-ok">✓ {s.our_sign}</span>
                        ) : edit ? (
                          <button className="btn btn-small" onClick={() => sign(s)}>
                            Sign (with dates)
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="small">
                        {s.client_sign ? (
                          <span className="badge badge-ok">
                            ✓ {s.client_sign}
                            {s.recorded_by_staff ? " (recorded by staff)" : " (in the app)"}
                          </span>
                        ) : s.inspection_id && edit ? (
                          <label className="btn btn-small">
                            Record the signed copy
                            <input type="file" hidden accept="image/*,.pdf" onChange={(e) => clientCopy(s, e.target.files?.[0])} />
                          </label>
                        ) : (
                          <span className="muted">{s.inspection_id ? "waiting for the client" : "after our sign"}</span>
                        )}
                      </td>
                    </tr>
                  ))}
              </Fragment>
            );
          })}
          {!data.areas.length && (
            <tr>
              <td colSpan={5} className="muted">
                No stages on this site yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// --- material reconciliation ---------------------------------------------------------------------------

type ReconRow = {
  product_id: number;
  product: string;
  unit: string;
  issued: string;
  returned: string;
  net_used: string;
  needed: string;
  difference: string;
  state: string;
  to_godown: string;
  note: string | null;
  basis: string[];
};
type Recon = {
  site: string;
  period: string;
  periods: { key: string; label: string }[];
  rows: ReconRow[];
  godown: string;
  widths: { contract_line_id: number; description: string; unit: string; width_m: string | null }[];
};

export function Reconciliation() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const { can } = useAuth();
  const { data, error, setError, load } = useLoad<Recon>(`/api/closeout/sites/${id}/reconciliation${period ? `?period=${period}` : ""}`);
  const [done, setDone] = useState<string | null>(null);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const width = (w: Recon["widths"][number]) => {
    const v = window.prompt(`Width of "${w.description.slice(0, 60)}" in metres (measured per ${w.unit}; the consumption is per sqm)`, w.width_m ?? "");
    if (v) void run(api(`/api/closeout/contract-lines/${w.contract_line_id}/width`, { method: "PUT", json: { width_m: v } }), setError).then(load);
  };
  const ret = (r: ReconRow) => {
    const q = window.prompt(`Return to ${data.godown}: quantity of ${r.product} (${r.unit})`, String(Number(r.difference)));
    if (!q) return;
    void run(api<{ transfer: string }>(`/api/closeout/sites/${id}/reconciliation/return`, { method: "POST", json: { product_id: r.product_id, qty: q } }), setError).then((x) => {
      if (x) setDone(`Transfer ${x.transfer} made to ${data.godown}`);
      load();
    });
  };
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>{data.site}</Link> / material reconciliation
          </p>
          <h1>Material reconciliation</h1>
          <p className="muted">
            Product by product: issued to the work, returned from it, the net used, what the approved quantity needs (× the system's consumption and wastage), and the excess or
            short of the net used.
          </p>
        </div>
        <div className="page-actions">
          <select value={period} onChange={(e) => setParams(e.target.value ? { period: e.target.value } : {}, { replace: true })} aria-label="Bill period">
            <option value="">The whole site</option>
            {data.periods.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => void downloadFile(`/api/closeout/sites/${id}/reconciliation.xlsx${period ? `?period=${period}` : ""}`)}>
            Excel
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {done && <div className="alert alert-ok">{done}</div>}
      {data.widths.length > 0 && (
        <div className="card top-gap-small">
          <h2 className="section-title">Lines measured per running metre</h2>
          <p className="small muted">Their system's consumption is per sqm: give each line's width once (running length × width = the area that needs material).</p>
          {data.widths.map((w) => (
            <div key={w.contract_line_id} className="inline-form small">
              <span className="grow">
                {w.description} · per {w.unit} · width {w.width_m ? `${num(w.width_m, 3)} m` : <b className="text-warn">not given</b>}
              </span>
              {can("closeout.billing") && (
                <button className="btn btn-small" onClick={() => width(w)}>
                  {w.width_m ? "Change the width" : "Give the width"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Product</th>
              <th className="num">Issued (gross)</th>
              <th className="num">Returned</th>
              <th className="num">Net used</th>
              <th className="num">Needed</th>
              <th className="num">Excess / short</th>
              <th>Needed from</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.product_id}>
                <td>{r.product}</td>
                <td className="num">
                  {num(r.issued, 3)} {r.unit}
                </td>
                <td className="num">
                  {num(r.returned, 3)}
                  {Number(r.to_godown) > 0 && <div className="small muted">{num(r.to_godown, 3)} sent to the godown</div>}
                </td>
                <td className="num">{num(r.net_used, 3)}</td>
                <td className="num">{r.state === "to check" ? "—" : num(r.needed, 3)}</td>
                <td className="num">
                  <span className={`badge ${r.state === "excess" ? "badge-warn" : r.state === "short" ? "badge-danger" : r.state === "to check" ? "badge-info" : "badge-ok"}`}>
                    {r.state === "to check" ? (r.note ?? "to check") : r.state === "even" ? "even" : `${r.state} ${num(Math.abs(Number(r.difference)), 3)}`}
                  </span>
                </td>
                <td className="small muted">{r.basis.join("; ")}</td>
                <td>
                  {r.state === "excess" && can("store.edit") && (
                    <button className="btn btn-small" onClick={() => ret(r)}>
                      Return to godown
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!data.rows.length && (
              <tr>
                <td colSpan={7} className="muted">
                  Nothing issued or needed yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- labour claims against the approved measurement -----------------------------------------------------

type Claim = {
  id: number;
  contractor: string;
  area: string | null;
  claimed: string;
  approved: string;
  excess_claim: string;
  unit: string | null;
  period: string | null;
  zone: { name: string; ours: boolean; other: string | null } | null;
  photos: number;
  claim_photos: number;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  decided_by: string | null;
  director: string | null;
  pays: string;
  note: string | null;
};

export function LabourClaims() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data, error, setError, load } = useLoad<Claim[]>(`/api/closeout/sites/${id}/labour-claims`);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const decide = (c: Claim, decision: "approved" | "claimed") => {
    const reason = window.prompt(decision === "claimed" ? "Why pay the claimed area (the director approves it)?" : "Note (optional)", "") ?? null;
    if (reason === null || (decision === "claimed" && !reason.trim())) return;
    void run(api(`/api/closeout/labour-claims/${c.id}/decide`, { method: "POST", json: { decision, reason } }), setError).then(load);
  };
  const director = (c: Claim, approve: boolean) => {
    const reason = window.prompt(approve ? "Approved because" : "Refused because", "");
    if (reason === null) return;
    void run(api(`/api/closeout/labour-claims/${c.id}/director`, { method: "POST", json: { approve, reason } }), setError).then(load);
  };
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>Site</Link> / labour claims
          </p>
          <h1>Labour claims</h1>
          <p className="muted">
            The contractor's claimed area against the approved measurement of each area, with the RFI zone and the photos. Paying more than approved needs the director.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Contractor</th>
              <th>Area</th>
              <th className="num">Claimed</th>
              <th className="num">Approved</th>
              <th className="num">Above approved</th>
              <th>RFI zone</th>
              <th>Photos</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id}>
                <td>
                  {c.contractor}
                  <div className="small muted">{c.period}</div>
                </td>
                <td>{c.area}</td>
                <td className="num">
                  {num(c.claimed, 3)} {c.unit}
                </td>
                <td className="num">{num(c.approved, 3)}</td>
                <td className="num">
                  {Number(c.excess_claim) > 0 ? (
                    <span className="badge badge-warn">
                      +{num(c.excess_claim, 3)} ({num((Number(c.excess_claim) / Math.max(Number(c.approved), 0.001)) * 100, 1)} %)
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="small">{c.zone ? (c.zone.ours ? `ours · ${c.zone.name}` : `${c.zone.other ?? "another applicator"}`) : "—"}</td>
                <td className="small">
                  {c.photos} measured · {c.claim_photos} claimed
                </td>
                <td className="small">
                  {c.status === "open" && can("closeout.billing") && (
                    <>
                      <button className="btn btn-small btn-primary" onClick={() => decide(c, "approved")}>
                        Pay approved
                      </button>{" "}
                      {Number(c.excess_claim) > 0 && (
                        <button className="btn btn-small" onClick={() => decide(c, "claimed")}>
                          Pay claimed…
                        </button>
                      )}
                    </>
                  )}
                  {c.status === "director" && (
                    <>
                      <span className="badge badge-warn">waiting for the director</span>
                      <div>{c.decision_reason}</div>
                      {can("closeout.claim_approve") && (
                        <div className="top-gap-small">
                          <button className="btn btn-small btn-primary" onClick={() => director(c, true)}>
                            Approve
                          </button>{" "}
                          <button className="btn btn-small" onClick={() => director(c, false)}>
                            Refuse
                          </button>
                        </div>
                      )}
                    </>
                  )}
                  {c.status === "decided" && (
                    <>
                      <span className="badge badge-ok">
                        pays {num(c.pays, 3)} {c.unit} ({c.decision === "claimed" ? "claimed" : "approved"})
                      </span>
                      <div className="muted">
                        {c.decided_by}
                        {c.director ? `, approved by ${c.director}` : ""}
                        {c.decision_reason ? `: ${c.decision_reason}` : ""}
                      </div>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!data.length && (
              <tr>
                <td colSpan={8} className="muted">
                  No claims yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- one place for a bill's story ------------------------------------------------------------------------

type BillRow = {
  id: number;
  code: string;
  site: string;
  site_id: number;
  status: string;
  invoice: string | null;
  outstanding: string;
  due_on: string | null;
  overdue_days: number;
  at: string;
};
type Story = {
  bill: BillRow & {
    invoice_date: string | null;
    due_how: string;
    steps: { step: string; label: string; on: string; by: string | null; file: string | null; days: number }[];
    cycle: { submit_from_day: number; submit_to_day: number; ho_from_day: number; ho_to_day: number; payment_days: number } | null;
    followups: { at: string; spoke_to: string; said: string; promised_on: string | null }[];
  };
  quantities: {
    lines: {
      line_id: number;
      description: string;
      unit: string;
      rate: string;
      billed_qty: string;
      certified_qty: string | null;
      difference: string | null;
      reason: string | null;
      billed: string;
      certified: string | null;
    }[];
    billed: string;
    certified: string | null;
    difference: string | null;
    certified_by: string | null;
    certified_on: string | null;
  };
  payment: {
    invoice: string | null;
    total: string | null;
    received: string;
    outstanding: string;
    receipts: { number: string; on_date: string; amount: string; ref: string | null }[];
  };
};
const STEPS: [string, string][] = [
  ["prepared", "Prepared"],
  ["submitted_site", "Submitted at site"],
  ["signed_pm", "Signed by the client's PM"],
  ["sent_ho", "Sent to head office"],
  ["with_accounts", "With the client's accounts"],
  ["paid", "Paid"],
];

/** Every RA bill, each opening its one page. */
export function Bills() {
  const [params] = useSearchParams();
  const { data, error } = useLoad<BillRow[]>(`/api/closeout/bills${params.get("site") ? `?site_id=${params.get("site")}` : ""}`);
  const [q, setQ] = useState("");
  const rows = (data ?? []).filter((b) => !q || `${b.code} ${b.site} ${b.invoice ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Bills</h1>
          <p className="muted">Each RA bill's story on one page: quantities (billed, certified), its steps at the client, and the payment.</p>
        </div>
        <div className="page-actions">
          <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search bills" />
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Bill</th>
              <th>Site</th>
              <th>With the client at</th>
              <th className="num">Outstanding</th>
              <th>Due</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                <td>
                  <Link to={`/bills/${b.id}`}>{b.code}</Link>
                  <div className="small muted">{b.invoice}</div>
                </td>
                <td className="small">{b.site}</td>
                <td className="small">{b.at}</td>
                <td className="num">{inr(b.outstanding)}</td>
                <td className="small">
                  {d(b.due_on)} {b.overdue_days > 0 && <span className="badge badge-danger">{b.overdue_days} d overdue</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function BillPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "quantities" | "steps" | "payment") || "quantities";
  const { data, error, setError, load } = useLoad<Story>(`/api/closeout/bills/${id}/story`);
  const [fu, setFu] = useState({ spoke_to: "", said: "", promised_on: "" });
  // the client's certification (recorded for them) and the reasons for a difference: billing's
  const [tracked, setTracked] = useState<Tracked | null>(null);
  const [certifying, setCertifying] = useState(false);
  const siteId = data?.bill.site_id;
  const loadTracked = useCallback(() => {
    if (!siteId || !can("billing.view")) return;
    api<Tracked[]>(`/api/team/bill-tracking?site_id=${siteId}`).then(
      (r) => setTracked(r.find((x) => String(x.id) === id) ?? null),
      () => setTracked(null),
    );
  }, [siteId, id, can]);
  useEffect(loadTracked, [loadTracked]);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const b = data.bill;
  const reason = (lineId: number) => {
    const r = window.prompt("Why does the certified quantity differ from the billed one?");
    if (r) void run(api(`/api/team/ra-lines/${lineId}/reason`, { method: "PUT", json: { reason: r } }), setError).then(load);
  };
  const addStep = (step: string, f?: File) => {
    const form = new FormData();
    form.append("step", step);
    form.append("on_date", new Date().toISOString().slice(0, 10));
    if (f) form.append("file", f);
    void run(api(`/api/closeout/bills/${b.id}/steps`, { method: "POST", form }), setError).then(load);
  };
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to="/bills">Bills</Link> / {b.site}
          </p>
          <h1>
            {b.code} {b.overdue_days > 0 && <span className="badge badge-danger">{b.overdue_days} days overdue</span>}
          </h1>
          <p className="muted">
            {b.invoice ? `Invoice ${b.invoice} of ${d(b.invoice_date)}` : "Not invoiced yet"} · due {d(b.due_on)} ({b.due_how}) · with the client at: <b>{b.at}</b>
          </p>
        </div>
      </div>
      <div className="tabs">
        {(
          [
            ["quantities", "Quantities"],
            ["steps", "Steps at the client"],
            ["payment", "Payment"],
          ] as const
        ).map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setParams({ tab: k }, { replace: true })}>
            {label}
          </button>
        ))}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "quantities" && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Rate</th>
                <th className="num">Billed</th>
                <th className="num">Certified</th>
                <th className="num">Difference</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.quantities.lines.map((l, i) => (
                <tr key={i}>
                  <td className="small">{l.description}</td>
                  <td className="num">
                    {inr(l.rate)} / {l.unit}
                  </td>
                  <td className="num">
                    {num(l.billed_qty, 3)} {l.unit}
                    <div className="small muted">{inr(l.billed)}</div>
                  </td>
                  <td className="num">
                    {l.certified_qty === null ? "—" : `${num(l.certified_qty, 3)} ${l.unit}`}
                    <div className="small muted">{l.certified === null ? "" : inr(l.certified)}</div>
                  </td>
                  <td className={`num ${l.difference && Number(l.difference) < 0 ? "text-danger" : ""}`}>{l.difference === null ? "—" : num(l.difference, 3)}</td>
                  <td className="small">
                    {l.reason ?? ""}
                    {!l.reason && l.difference !== null && Number(l.difference) !== 0 && can("billing.edit") && (
                      <button className="btn btn-small btn-ghost" onClick={() => reason(l.line_id)}>
                        Give the reason
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              <tr className="total-row">
                <td colSpan={2}>
                  <b>Total</b>
                  {data.quantities.certified_by && (
                    <div className="small muted">
                      certified by {data.quantities.certified_by} on {d(data.quantities.certified_on)}
                    </div>
                  )}
                </td>
                <td className="num">
                  <b>{inr(data.quantities.billed)}</b>
                </td>
                <td className="num">
                  <b>{inr(data.quantities.certified)}</b>
                </td>
                <td className="num">{inr(data.quantities.difference)}</td>
                <td>
                  {tracked?.has_document && (
                    <button className="btn btn-small btn-ghost" onClick={() => void downloadFile(`/api/team/ra-bills/${tracked.id}/client-certification/document`)}>
                      The client's copy
                    </button>
                  )}
                  {tracked && ["submitted", "certified_by_client"].includes(tracked.status) && can("billing.edit") && (
                    <button className="btn btn-small" onClick={() => setCertifying(true)}>
                      Record certification
                    </button>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
          {certifying && tracked && <CertifyForm bill={tracked} onClose={() => setCertifying(false)} onSaved={() => (setCertifying(false), load(), loadTracked())} />}
        </div>
      )}
      {tab === "steps" && (
        <div className="card">
          {b.cycle && (
            <p className="small muted">
              Client's cycle: bills reach the site {b.cycle.submit_from_day}–{b.cycle.submit_to_day} · head office {b.cycle.ho_from_day}–{b.cycle.ho_to_day} · paid{" "}
              {b.cycle.payment_days} days after
            </p>
          )}
          <div className="bill-steps">
            {STEPS.map(([k, label]) => {
              const s = b.steps.find((x) => x.step === k);
              return (
                <div key={k} className={`bill-step ${s ? "done" : ""}`}>
                  <div className="small">
                    <b>{label}</b>
                  </div>
                  {s ? (
                    <div className="small">
                      {d(s.on)}
                      {s.by ? ` · ${s.by}` : ""}
                      {s.file ? " · signed copy" : ""}
                      <div className="muted">{s.days} day(s) here</div>
                    </div>
                  ) : can("closeout.billing") ? (
                    k === "signed_pm" ? (
                      <label className="btn btn-small">
                        Upload the signed copy
                        <input type="file" hidden accept="image/*,.pdf" onChange={(e) => addStep(k, e.target.files?.[0])} />
                      </label>
                    ) : (
                      <button className="btn btn-small" onClick={() => addStep(k)}>
                        Mark today
                      </button>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      )}
      {tab === "payment" && (
        <div className="grid-2">
          <div className="card">
            <h2 className="section-title">Due and received</h2>
            <p>
              Due <b>{d(b.due_on)}</b> <span className="small muted">({b.due_how})</span>
            </p>
            <p>
              Invoice total {inr(data.payment.total)} · received {inr(data.payment.received)} · outstanding <b>{inr(data.payment.outstanding)}</b>
            </p>
            <table className="table compact">
              <thead>
                <tr>
                  <th>Receipt</th>
                  <th>Date</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {data.payment.receipts.map((r) => (
                  <tr key={r.number}>
                    <td>
                      {r.number}
                      <div className="small muted">{r.ref}</div>
                    </td>
                    <td>{d(r.on_date)}</td>
                    <td className="num">{inr(r.amount)}</td>
                  </tr>
                ))}
                {!data.payment.receipts.length && (
                  <tr>
                    <td colSpan={3} className="muted">
                      Nothing received yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h2 className="section-title">Follow-ups</h2>
            {b.followups.map((f, i) => (
              <div key={i} className="small followup">
                <b>{d(f.at)}</b> {f.spoke_to}: “{f.said}”{f.promised_on ? ` · promised ${d(f.promised_on)}` : ""}
              </div>
            ))}
            {!b.followups.length && <p className="muted small">No call logged yet.</p>}
            {can("closeout.payments") && (
              <form
                className="top-gap"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(api(`/api/closeout/bills/${b.id}/followups`, { method: "POST", json: { ...fu, promised_on: fu.promised_on || null } }), setError).then(() => {
                    setFu({ spoke_to: "", said: "", promised_on: "" });
                    load();
                  });
                }}
              >
                <div className="inline-form">
                  <input placeholder="Who you spoke to" value={fu.spoke_to} onChange={(e) => setFu({ ...fu, spoke_to: e.target.value })} required />
                  <input className="grow" placeholder="What was said" value={fu.said} onChange={(e) => setFu({ ...fu, said: e.target.value })} required />
                  <input type="date" value={fu.promised_on} onChange={(e) => setFu({ ...fu, promised_on: e.target.value })} aria-label="Promised date" />
                  <button className="btn btn-primary">Log the call</button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/** The old bill pages' links: /bill-tracking and /billing/tracking?bill=… open the bill page. */
export function OldBillRedirect() {
  const [params] = useSearchParams();
  return <Navigate to={oldBillTarget(params)} replace />;
}

/** Where an old bill link goes: a bill to its page (its steps), a site to its bills. */
export function oldBillTarget(params: URLSearchParams): string {
  const bill = params.get("bill");
  const site = params.get("site");
  return bill ? `/bills/${bill}?tab=steps` : site ? `/bills?site=${site}` : "/bills";
}

/** Billing checklist: pick the site (the checklist is per site and tower). */
export function ChecklistSites() {
  const { data, error } = useLoad<{ items: { id: number; code: string; name: string }[] }>("/api/sites?limit=200");
  return (
    <>
      <div className="page-header">
        <h1>Billing checklist</h1>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <ul className="site-list">
          {(data?.items ?? []).map((s) => (
            <li key={s.id}>
              <Link to={`/sites/${s.id}/billing-checklist`}>
                {s.code} · {s.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
