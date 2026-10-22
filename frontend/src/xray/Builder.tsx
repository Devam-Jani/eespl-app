// Building the 3D model from the AutoCAD drawing: per typical plan its outline (proposed from
// the walls, traced with the takeoff's snapping), the floors it is for, its columns (found, then
// confirmed by a click), stair and lift cores and beams; the heights from the section or the
// defaults; saved as a new version. Billing, planning, the office admin, the director, and the
// site engineer on their own sites.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";

type Pt = [number, number];
type Core = { kind: "stair" | "lift"; outline: Pt[]; risers: number | null };
type FType = { key: string; name: string; plan: string; title_xy: Pt | null; region: number[] | null; floors: number[]; outline: Pt[]; columns: number[][]; columns_confirmed: boolean; beams: number[][]; cores: Core[]; shift: Pt; shift_fixed?: boolean; walls?: boolean };
type Settings = { floor_height_m: number; slab_m: number; plinth_m: number; column_min_m: number; column_max_m: number; beams_on_walls: boolean; riser_m: number; bloom: "auto" | "on" | "off"; tower_id: number | null; ifc: boolean; ifc_max_mb: number };
type Data = { settings: Settings; levels: { source: string; note: string; floor_height_m: number | null }; floor_types: FType[]; floors: { level: number; node_id: number; name: string; type: string | null; height_m: number | null }[]; ifc_links: Record<string, number> };
type Out = {
  site_id: number;
  can_edit: boolean;
  model: null | { version: number; cad_file_id: number | null; data: Data; note: string | null; changes: Changes | null; by: string | null; at: string; unit_m: number | null; floors: { level: number; name: string; elevation_m: number; height_m: number; type: string | null }[] };
  drawings: { cad_file_id: number; title: string; rev_no: string; unit_m: number | null; newer: boolean }[];
  plans: { title: string; xy: Pt; floors: number[]; region: number[] }[];
  site_floors: { node_id: number; name: string; level: number | null }[];
};
type Changes = { plans_kept: string[]; plans_missing: string[]; columns: Record<string, { kept: number; added: number; removed: number }>; rooms: { kept: number; added: string[]; resized: string[]; removed: string[] } };
type Geo = { extents: [number, number, number, number] | null; unit_m: number | null; layers: { name: string; role: string | null; color: number }[]; geometry: Record<string, { s: number[] }> };
type Tool = "none" | "outline" | "columns" | "stair" | "lift" | "beam";

/** "2,3,5-9" -> [2, 3, 5, 6, 7, 8, 9]; "G" or "0" is the ground floor. */
export function parseFloors(text: string): number[] {
  const out = new Set<number>();
  for (const part of text.split(/[,\s]+/).filter(Boolean)) {
    const p = part.toUpperCase().replace(/^G$/, "0");
    const m = /^(-?\d+)\s*(?:-|TO)\s*(-?\d+)$/.exec(p);
    if (m) for (let i = Number(m[1]); i <= Number(m[2]); i++) out.add(i);
    else if (/^-?\d+$/.test(p)) out.add(Number(p));
  }
  return [...out].sort((a, b) => a - b);
}

export function floorsText(levels: number[]): string {
  const s = [...levels].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < s.length; i++) {
    let j = i;
    while (j + 1 < s.length && s[j + 1] === s[j] + 1) j++;
    out.push(j > i + 1 ? `${s[i]}-${s[j]}` : j === i + 1 ? `${s[i]},${s[j]}` : `${s[i]}`);
    i = j;
  }
  return out.join(",");
}

export default function BuildingBuilder() {
  const { id } = useParams();
  const siteId = Number(id);
  const [out, setOut] = useState<Out | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [geo, setGeo] = useState<Geo | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("none");
  const [trace, setTrace] = useState<Pt[]>([]);
  const [beamFrom, setBeamFrom] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(() => {
    api<Out>(`/api/sites/${siteId}/building`).then(
      (o) => {
        setOut(o);
        setData(o.model ? structuredClone(o.model.data) : null);
        setDirty(false);
        setSel((s) => s ?? o.model?.data.floor_types.find((t) => !t.outline.length)?.key ?? o.model?.data.floor_types[0]?.key ?? null);
      },
      (e) => setError(errorText(e)),
    );
  }, [siteId]);
  useEffect(load, [load]);
  const fileId = out?.model?.cad_file_id ?? null;
  useEffect(() => {
    if (fileId) api<Geo>(`/api/takeoff/files/${fileId}/geometry`).then(setGeo, (e) => setError(errorText(e)));
  }, [fileId]);

  const type = data?.floor_types.find((t) => t.key === sel) ?? null;
  const unit = out?.model?.unit_m ?? geo?.unit_m ?? 0.001;
  const update = (fn: (d: Data) => void) => {
    setData((d) => {
      if (!d) return d;
      const n = structuredClone(d);
      fn(n);
      return n;
    });
    setDirty(true);
  };
  const updType = (fn: (t: FType) => void) => update((d) => fn(d.floor_types.find((t) => t.key === sel)!));

  async function run<T>(f: () => Promise<T>, done?: string): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await f();
      if (done) setMsg(done);
      return r;
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function start(cadFileId: number) {
    const o = await run(() => api<Out>(`/api/sites/${siteId}/building/from-drawing`, { method: "POST", json: { cad_file_id: cadFileId } }), "Model made from the drawing");
    if (o) {
      setOut(o);
      setData(o.model ? structuredClone(o.model.data) : null);
      setDirty(false);
    }
  }
  async function save() {
    if (!data) return;
    const o = await run(() => api<Out>(`/api/sites/${siteId}/building`, { method: "PUT", json: { data, note: null } }), "Saved as a new version");
    if (o) {
      setOut(o);
      setData(structuredClone(o.model!.data));
      setDirty(false);
    }
  }
  async function uploadIfc(file: File) {
    const form = new FormData();
    form.append("file", file);
    const o = await run(() => api<Out>(`/api/sites/${siteId}/building/ifc`, { method: "POST", form }), `BIM file ${file.name} kept with the site's drawings`);
    if (o) {
      setOut(o);
      setData(o.model ? structuredClone(o.model.data) : null);
      setDirty(false);
    }
  }
  const ifcInput = out?.can_edit ? (
    <label className="field">
      <span>The client's BIM file (IFC)</span>
      <input type="file" accept=".ifc" disabled={busy} onChange={(e) => e.target.files?.[0] && void uploadIfc(e.target.files[0])} />
    </label>
  ) : null;

  async function propose() {
    if (!type) return;
    const r = await run(() => api<{ outline: Pt[] }>(`/api/sites/${siteId}/building/propose-outline`, { method: "POST", json: { key: type.key } }));
    if (r?.outline.length) {
      updType((t) => (t.outline = r.outline));
      setMsg(`Outline proposed from the walls: ${r.outline.length} corners, ${(area(r.outline) * unit * unit).toFixed(0)} sqm. Check it against the plan and trace again where it is off.`);
    } else if (r) setError("No closed outline in the walls of this plan: trace it.");
  }
  async function findColumns() {
    if (!type) return;
    const r = await run(() => api<{ columns: number[][]; limits_m: number[] }>(`/api/sites/${siteId}/building/detect-columns`, { method: "POST", json: { key: type.key, outline: type.outline } }));
    if (r) {
      updType((t) => {
        t.columns = r.columns;
        t.columns_confirmed = false;
      });
      setTool("columns");
      setMsg(`${r.columns.length} column(s) found (closed shapes of ${r.limits_m[0] * 1000}-${r.limits_m[1] * 1000} mm on the column layers). Click one to remove it, click the plan to add one, then confirm.`);
    }
  }

  async function onPlanClick(x: number, y: number, radius: number) {
    if (!type || !fileId) return;
    if (tool === "columns") {
      const hit = type.columns.findIndex((c) => Math.abs(c[0] - x) <= c[2] / 2 + radius && Math.abs(c[1] - y) <= c[3] / 2 + radius);
      updType((t) => {
        if (hit >= 0) t.columns.splice(hit, 1);
        else {
          const sizes = t.columns.map((c) => [c[2], c[3]]);
          const [w, d] = sizes.length ? sizes[Math.floor(sizes.length / 2)] : [0.45 / unit, 0.45 / unit];
          t.columns.push([x, y, w, d]);
        }
        t.columns_confirmed = false;
      });
      return;
    }
    if (tool === "beam") {
      const hit = type.columns.findIndex((c) => Math.abs(c[0] - x) <= c[2] / 2 + radius && Math.abs(c[1] - y) <= c[3] / 2 + radius);
      if (hit < 0) return;
      if (beamFrom == null) setBeamFrom(hit);
      else {
        if (beamFrom !== hit) updType((t) => t.beams.push([beamFrom, hit]));
        setBeamFrom(null);
      }
      return;
    }
    if (tool === "outline" || tool === "stair" || tool === "lift") {
      const prev = trace.length ? trace[trace.length - 1] : null;
      const s = await api<{ x: number; y: number }>(`/api/takeoff/files/${fileId}/snap`, { method: "POST", json: { x, y, radius, previous: prev } }).catch(() => ({ x, y }));
      setTrace((t) => [...t, [s.x, s.y]]);
    }
  }
  function finishTrace() {
    if (trace.length < 3) return setError("At least 3 corners");
    if (tool === "outline") updType((t) => (t.outline = trace));
    else if (tool === "stair" || tool === "lift") updType((t) => t.cores.push({ kind: tool, outline: trace, risers: null }));
    setTrace([]);
    setTool("none");
  }

  if (error && !out) return <div className="alert alert-error">{error}</div>;
  if (!out) return <p className="muted">Loading…</p>;
  const newer = out.drawings.find((d) => d.newer);
  return (
    <div className="builder">
      <div className="page-header">
        <div>
          <h1>The building from the drawing</h1>
          <p className="muted">
            Each typical plan once: its outline, the floors it is for, its columns and cores. The rooms are the areas traced and mapped in the <Link to={`/sites/${siteId}/takeoff`}>AutoCAD takeoff</Link>; they rise on their floors with their sunk depth.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to={`/sites/${siteId}?tab=3d`}>
            See it in 3D
          </Link>
          {data && out.can_edit && (
            <button className="btn btn-primary" disabled={busy || !dirty} onClick={() => void save()}>
              Save{out.model ? ` (version ${out.model.version + 1})` : ""}
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-ok">{msg}</div>}
      {!out.model && (
        <div className="card">
          <h2>Start from a drawing</h2>
          {out.drawings.length === 0 ? (
            <p>
              No drawing read for this site yet: upload it and read it in the <Link to={`/sites/${siteId}/takeoff`}>AutoCAD takeoff</Link> first.
            </p>
          ) : (
            out.drawings.map((d) => (
              <p key={d.cad_file_id}>
                {d.title} (rev {d.rev_no}){" "}
                {out.can_edit && (
                  <button className="btn btn-small btn-primary" disabled={busy} onClick={() => void start(d.cad_file_id)}>
                    Build from this drawing
                  </button>
                )}
              </p>
            ))
          )}
          <p className="small muted">Or, when the client gave a BIM model, its IFC file (it is shown as it is; planning links its spaces to our places once):</p>
          {ifcInput}
        </div>
      )}
      {newer && out.can_edit && (
        <div className="alert alert-warn">
          A newer revision is read: {newer.title} rev {newer.rev_no}.{" "}
          <button className="btn btn-small" disabled={busy} onClick={() => void start(newer.cad_file_id)}>
            Move the model onto it
          </button>{" "}
          (what still matches is kept; the changes are listed)
        </div>
      )}
      {out.model?.changes && <ChangesNote changes={out.model.changes} />}
      {data && (
        <div className="builder-grid">
          <div className="card builder-side">
            <h2>Floor types</h2>
            <p className="small muted">One per typical plan. The floors come from the plan's title where it names them; correct them here.</p>
            {data.floor_types.map((t) => (
              <button key={t.key} className={`builder-type${t.key === sel ? " active" : ""}`} onClick={() => (setSel(t.key), setTool("none"), setTrace([]))}>
                <b>{t.name}</b>
                <span className="small">
                  floors {floorsText(t.floors) || "—"} · {t.outline.length ? `outline ${(area(t.outline) * unit * unit).toFixed(0)} sqm` : "no outline"} · {t.columns.length} col{t.columns_confirmed ? " ✓" : ""} · {t.cores.length} core(s)
                </span>
              </button>
            ))}
            {out.can_edit && out.plans.some((p) => !data.floor_types.some((t) => t.plan === p.title)) && (
              <select
                value=""
                aria-label="Add a floor type from a plan"
                onChange={(e) => {
                  const p = out.plans.find((x) => x.title === e.target.value);
                  if (!p) return;
                  const key = `${p.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 36)}-${data.floor_types.length}`;
                  update((d) => d.floor_types.push({ key, name: p.title, plan: p.title, title_xy: p.xy, region: p.region, floors: p.floors, outline: [], columns: [], columns_confirmed: false, beams: [], cores: [], shift: [0, 0] }));
                  setSel(key);
                }}
              >
                <option value="">+ Add a floor type from a plan…</option>
                {out.plans
                  .filter((p) => !data.floor_types.some((t) => t.plan === p.title))
                  .map((p) => (
                    <option key={p.title} value={p.title}>
                      {p.title}
                    </option>
                  ))}
              </select>
            )}
            {type && out.can_edit && (
              <div className="builder-steps">
                <div className="builder-row">
                  <label className="check">
                    <input type="checkbox" checked={type.walls !== false} onChange={(e) => updType((t) => (t.walls = e.target.checked))} /> Walls (off for a roof or a terrace)
                  </label>
                  <button
                    className="btn btn-small"
                    onClick={() => {
                      if (!confirm(`Remove the floor type ${type.name}? (its floors fall back to the reference plan)`)) return;
                      update((d) => (d.floor_types = d.floor_types.filter((t) => t.key !== type.key)));
                      setSel(null);
                    }}
                  >
                    Remove this floor type
                  </button>
                </div>
                <label className="field">
                  <span>Floors this plan is for</span>
                  <input defaultValue={floorsText(type.floors)} key={type.key} onBlur={(e) => updType((t) => (t.floors = parseFloors(e.target.value)))} placeholder="3-12, or 2,3,5" />
                </label>
                <div className="builder-row">
                  <b>1. Outline</b>
                  <button className="btn btn-small" disabled={busy || !type.region} onClick={() => void propose()}>
                    Propose from the walls
                  </button>
                  <button className={`btn btn-small${tool === "outline" ? " active" : ""}`} onClick={() => (setTool("outline"), setTrace([]))}>
                    Trace
                  </button>
                </div>
                <div className="builder-row">
                  <b>2. Columns</b>
                  <button className="btn btn-small" disabled={busy || !type.outline.length} onClick={() => void findColumns()}>
                    Find columns
                  </button>
                  <button className={`btn btn-small${tool === "columns" ? " active" : ""}`} disabled={!type.outline.length} onClick={() => setTool("columns")}>
                    Add / remove
                  </button>
                  <button className="btn btn-small" disabled={!type.columns.length || type.columns_confirmed} onClick={() => (updType((t) => (t.columns_confirmed = true)), setTool("none"))}>
                    {type.columns_confirmed ? "Confirmed" : "Confirm"}
                  </button>
                </div>
                <div className="builder-row">
                  <b>3. Cores</b>
                  <button className={`btn btn-small${tool === "stair" ? " active" : ""}`} onClick={() => (setTool("stair"), setTrace([]))}>
                    Trace a stair
                  </button>
                  <button className={`btn btn-small${tool === "lift" ? " active" : ""}`} onClick={() => (setTool("lift"), setTrace([]))}>
                    Trace a lift
                  </button>
                </div>
                {type.cores.map((c, i) => (
                  <div key={i} className="builder-row small">
                    {c.kind === "stair" ? "Stair" : "Lift"} {i + 1}
                    {c.kind === "stair" && (
                      <input
                        type="number"
                        min={10}
                        max={40}
                        placeholder="risers (auto)"
                        value={c.risers ?? ""}
                        onChange={(e) => updType((t) => (t.cores[i].risers = e.target.value ? Number(e.target.value) : null))}
                        aria-label="Risers"
                        style={{ width: "7em" }}
                      />
                    )}
                    <button className="btn btn-small" onClick={() => updType((t) => t.cores.splice(i, 1))}>
                      Remove
                    </button>
                  </div>
                ))}
                <div className="builder-row">
                  <b>4. Beams</b>
                  <button className={`btn btn-small${tool === "beam" ? " active" : ""}`} disabled={type.columns.length < 2} onClick={() => (setTool("beam"), setBeamFrom(null))}>
                    Pick two columns
                  </button>
                  <span className="small">{type.beams.length} beam(s)</span>
                  {type.beams.length > 0 && (
                    <button className="btn btn-small" onClick={() => updType((t) => (t.beams = []))}>
                      Clear
                    </button>
                  )}
                </div>
                {(tool === "outline" || tool === "stair" || tool === "lift") && (
                  <div className="builder-row">
                    <span className="small">{trace.length} corner(s): click the plan (it snaps to the walls)</span>
                    <button className="btn btn-small btn-primary" disabled={trace.length < 3} onClick={finishTrace}>
                      Finish
                    </button>
                    <button className="btn btn-small" onClick={() => setTrace((t) => t.slice(0, -1))}>
                      Undo
                    </button>
                  </div>
                )}
              </div>
            )}
            <h2>Heights</h2>
            <p className="small muted">{data.levels.note}</p>
            <div className="builder-settings">
              {(
                [
                  ["floor_height_m", "Floor to floor (m)"],
                  ["slab_m", "Slab (m)"],
                  ["plinth_m", "Plinth (m)"],
                  ["riser_m", "Stair riser (m)"],
                  ["column_min_m", "Column from (m)"],
                  ["column_max_m", "Column up to (m)"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="field">
                  <span>{label}</span>
                  <input type="number" step="0.001" value={data.settings[k]} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings[k] = Number(e.target.value)))} />
                </label>
              ))}
              <label className="check">
                <input type="checkbox" checked={data.settings.beams_on_walls} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.beams_on_walls = e.target.checked))} /> Beams along the column lines
              </label>
              <label className="check">
                <input type="checkbox" checked={data.settings.ifc} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.ifc = e.target.checked))} /> Show the client's BIM file (IFC)
              </label>
              <label className="field">
                <span>BIM file limit for a laptop (MB)</span>
                <input type="number" min={10} max={600} value={data.settings.ifc_max_mb} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.ifc_max_mb = Number(e.target.value)))} />
              </label>
              <div style={{ gridColumn: "1 / -1" }}>{ifcInput}</div>
              <label className="field">
                <span>Glow</span>
                <select value={data.settings.bloom} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.bloom = e.target.value as Settings["bloom"]))}>
                  <option value="auto">Auto (off on weak devices)</option>
                  <option value="on">Always on</option>
                  <option value="off">Off</option>
                </select>
              </label>
            </div>
            <h2>Floors</h2>
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Floor</th>
                  <th>Type</th>
                  <th className="num">Height (m)</th>
                  <th className="num">Level (m)</th>
                </tr>
              </thead>
              <tbody>
                {[...data.floors]
                  .sort((a, b) => b.level - a.level)
                  .map((f) => {
                    const t = data.floor_types.find((x) => x.floors.includes(f.level));
                    const el = out.model?.floors.find((x) => x.level === f.level);
                    return (
                      <tr key={f.node_id}>
                        <td>{f.name}</td>
                        <td className="small">{t?.name ?? <span className="muted">— (the reference plan)</span>}</td>
                        <td className="num">
                          <input
                            type="number"
                            step="0.001"
                            style={{ width: "6em" }}
                            placeholder={String(data.settings.floor_height_m)}
                            value={f.height_m ?? ""}
                            disabled={!out.can_edit}
                            onChange={(e) => update((d) => (d.floors.find((x) => x.node_id === f.node_id)!.height_m = e.target.value ? Number(e.target.value) : null))}
                            aria-label={`Height of ${f.name}`}
                          />
                        </td>
                        <td className="num small">{el ? el.elevation_m.toFixed(3) : "—"}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
          <div className="card builder-plan">
            {geo && type ? (
              <PlanCanvas geo={geo} type={type} trace={trace} tool={tool} beamFrom={beamFrom} onClick={(x, y, r) => void onPlanClick(x, y, r)} />
            ) : (
              <p className="muted">Loading the drawing…</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function area(pts: Pt[]): number {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i === 0 ? pts.length - 1 : i - 1];
    const [x2, y2] = pts[i];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

function ChangesNote({ changes }: { changes: Changes }) {
  const cols = Object.entries(changes.columns ?? {});
  return (
    <div className="card">
      <h2>What the new drawing revision changed</h2>
      <p className="small">
        Plans kept: {changes.plans_kept.length}
        {changes.plans_missing.length ? `; not found again (check them): ${changes.plans_missing.join(", ")}` : ""}.
      </p>
      {cols.map(([k, c]) => (
        <p key={k} className="small">
          {k}: columns kept {c.kept}, new {c.added}, gone {c.removed}
        </p>
      ))}
      <p className="small">
        Rooms kept {changes.rooms.kept}
        {changes.rooms.added.length ? `; new: ${changes.rooms.added.join(", ")}` : ""}
        {changes.rooms.resized.length ? `; resized: ${changes.rooms.resized.join(", ")}` : ""}
        {changes.rooms.removed.length ? `; gone: ${changes.rooms.removed.join(", ")}` : ""}.
      </p>
    </div>
  );
}

/** The plan with the outline, columns, cores and beams over it: pan, zoom, click. */
function PlanCanvas({ geo, type, trace, tool, beamFrom, onClick }: { geo: Geo; type: FType; trace: Pt[]; tool: Tool; beamFrom: number | null; onClick: (x: number, y: number, radius: number) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const fitTo = useMemo(() => {
    const r = type.outline.length ? boundsOf(type.outline, 0.08) : type.region ? (type.region as [number, number, number, number]) : (geo.extents ?? [0, 0, 1000, 1000]);
    return r;
  }, [type.key, type.region, geo.extents]); // eslint-disable-line react-hooks/exhaustive-deps
  const [view, setView] = useState({ cx: 0, cy: 0, scale: 0 });
  const drag = useRef<{ x: number; y: number; cx: number; cy: number; moved: boolean } | null>(null);
  useEffect(() => setView({ cx: 0, cy: 0, scale: 0 }), [fitTo]);
  useEffect(() => {
    const c = ref.current;
    if (!c || view.scale) return;
    const [x1, y1, x2, y2] = fitTo;
    const scale = Math.min(c.clientWidth / Math.max(1, x2 - x1), c.clientHeight / Math.max(1, y2 - y1)) * 0.92;
    setView({ cx: (x1 + x2) / 2, cy: (y1 + y2) / 2, scale });
  }, [fitTo, view.scale]);
  const hidden = useMemo(() => new Set(geo.layers.filter((l) => l.role === "hide" || /FUR|HATCH|ELE|PHE|FFTG|DIM|TITLE/i.test(l.name)).map((l) => l.name)), [geo.layers]);

  const draw = useCallback(() => {
    const c = ref.current;
    if (!c || !view.scale) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth;
    const h = c.clientHeight;
    if (c.width !== w * dpr) c.width = w * dpr;
    if (c.height !== h * dpr) c.height = h * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, w, h);
    const { cx, cy, scale } = view;
    const X = (x: number) => (x - cx) * scale + w / 2;
    const Y = (y: number) => h / 2 - (y - cy) * scale;
    const [minX, maxX, minY, maxY] = [cx - w / 2 / scale, cx + w / 2 / scale, cy - h / 2 / scale, cy + h / 2 / scale];
    ctx.strokeStyle = "#9aa2a6";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const [layer, g] of Object.entries(geo.geometry)) {
      if (hidden.has(layer)) continue;
      const s = g.s;
      for (let i = 0; i < s.length; i += 4) {
        if ((s[i] < minX && s[i + 2] < minX) || (s[i] > maxX && s[i + 2] > maxX) || (s[i + 1] < minY && s[i + 3] < minY) || (s[i + 1] > maxY && s[i + 3] > maxY)) continue;
        ctx.moveTo(X(s[i]), Y(s[i + 1]));
        ctx.lineTo(X(s[i + 2]), Y(s[i + 3]));
      }
    }
    ctx.stroke();
    const poly = (pts: Pt[], stroke: string, fill: string | null, closed = true, width = 2.5) => {
      if (!pts.length) return;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1]))));
      if (closed) ctx.closePath();
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
    };
    poly(type.outline, "#0b84c6", "rgba(11,132,198,0.08)");
    type.cores.forEach((c) => poly(c.outline, "#8e5cc8", "rgba(142,92,200,0.18)"));
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#e67e22";
    for (const [i, j] of type.beams) {
      const a = type.columns[i];
      const b = type.columns[j];
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.moveTo(X(a[0]), Y(a[1]));
      ctx.lineTo(X(b[0]), Y(b[1]));
      ctx.stroke();
    }
    type.columns.forEach(([x, y, cw, cd], i) => {
      ctx.fillStyle = i === beamFrom ? "#d64545" : type.columns_confirmed ? "#2e8b57" : "#f0a531";
      ctx.fillRect(X(x - cw / 2), Y(y + cd / 2), Math.max(4, cw * scale), Math.max(4, cd * scale));
    });
    if (trace.length) {
      ctx.setLineDash([6, 4]);
      poly(trace, "#d62728", null, false, 2);
      ctx.setLineDash([]);
      for (const p of trace) {
        ctx.fillStyle = "#d62728";
        ctx.fillRect(X(p[0]) - 4, Y(p[1]) - 4, 8, 8);
      }
    }
  }, [geo, hidden, view, type, trace, beamFrom]);
  useEffect(() => {
    const id = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(id);
  }, [draw]);

  const toWorld = (clientX: number, clientY: number): Pt => {
    const r = ref.current!.getBoundingClientRect();
    return [(clientX - r.left - r.width / 2) / view.scale + view.cx, view.cy - (clientY - r.top - r.height / 2) / view.scale];
  };
  function down(e: ReactPointerEvent) {
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false };
  }
  function move(e: ReactPointerEvent) {
    const s = drag.current;
    if (!s) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) s.moved = true;
    if (s.moved) setView((v) => ({ ...v, cx: s.cx - dx / v.scale, cy: s.cy + dy / v.scale }));
  }
  function up(e: ReactPointerEvent) {
    const s = drag.current;
    drag.current = null;
    if (!s || s.moved || tool === "none") return;
    const [x, y] = toWorld(e.clientX, e.clientY);
    onClick(x, y, 12 / view.scale);
  }
  function wheel(e: ReactWheelEvent) {
    const [x, y] = toWorld(e.clientX, e.clientY);
    const f = e.deltaY < 0 ? 1.25 : 0.8;
    setView((v) => ({ scale: v.scale * f, cx: x - (x - v.cx) / f, cy: y - (y - v.cy) / f }));
  }
  return (
    <div className="takeoff-canvas builder-canvas">
      <canvas ref={ref} onPointerDown={down} onPointerMove={move} onPointerUp={up} onWheel={wheel} aria-label="The plan" style={{ cursor: tool === "none" ? "grab" : "crosshair" }} />
      <div className="takeoff-zoom">
        <button className="btn btn-small" onClick={() => setView((v) => ({ ...v, scale: v.scale * 1.5 }))} aria-label="Zoom in">
          +
        </button>
        <button className="btn btn-small" onClick={() => setView((v) => ({ ...v, scale: v.scale / 1.5 }))} aria-label="Zoom out">
          −
        </button>
        <button className="btn btn-small" onClick={() => setView({ cx: 0, cy: 0, scale: 0 })}>
          Fit
        </button>
      </div>
    </div>
  );
}

function boundsOf(pts: Pt[], pad: number): [number, number, number, number] {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x1, x2, y1, y2] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const px = (x2 - x1) * pad;
  const py = (y2 - y1) * pad;
  return [x1 - px, y1 - py, x2 + px, y2 + py];
}
