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
import { decodeGeometry, useGlPlan } from "../takeoff/glplan";
import type { Geo as PlanGeo, GeoV2 } from "../takeoff/glplan";
import { ReadProgress } from "../takeoff/ReadProgress";
import { ART, THEMES } from "../ui/tokens";
import { Button, buttonClass, Card, Field } from "../ui/components";

type Pt = [number, number];
type Core = { kind: "stair" | "lift"; outline: Pt[]; risers: number | null };
type FType = { key: string; name: string; plan: string; title_xy: Pt | null; region: number[] | null; floors: number[]; outline: Pt[]; columns: number[][]; columns_confirmed: boolean; beams: number[][]; cores: Core[]; shift: Pt; shift_fixed?: boolean; walls?: boolean };
type Settings = { floor_height_m: number; slab_m: number; plinth_m: number; column_min_m: number; column_max_m: number; beams_on_walls: boolean; riser_m: number; bloom: "auto" | "on" | "off"; tower_id: number | null; ifc: boolean; ifc_max_mb: number };
type Data = { settings: Settings; levels: { source: string; note: string; floor_height_m: number | null }; floor_types: FType[]; floors: { level: number; node_id: number; name: string; type: string | null; height_m: number | null; elevation_m?: number | null; level_by_hand?: boolean }[]; ifc_links: Record<string, number> };
type Out = {
  site_id: number;
  can_edit: boolean;
  model: null | { version: number; cad_file_id: number | null; data: Data; note: string | null; changes: Changes | null; by: string | null; at: string; unit_m: number | null; floors: { level: number; name: string; elevation_m: number; height_m: number; type: string | null; level_source: "hand" | "section" | "default"; level_flag: string | null }[]; unmatched_levels: number[] };
  drawings: { cad_file_id: number; title: string; rev_no: string; unit_m: number | null; newer: boolean }[];
  revisions: DrawingRev[];
  model_drawing: DrawingRev | null;
  can_read: boolean;
  plans: { title: string; xy: Pt; floors: number[]; region: number[] }[];
  site_floors: { node_id: number; name: string; level: number | null }[];
};
type DrawingRev = { revision_id: number; title: string; rev_no: number | string; filename: string | null; cad_file_id: number | null; state: "not read" | "queued" | "reading" | "ready" | "failed" | "missing"; progress: string | null; progress_at: string | null; error: string | null };
const STATE_TEXT: Record<DrawingRev["state"], string> = {
  "not read": "This drawing has not been read yet.",
  queued: "Waiting to be read.",
  reading: "Being read.",
  ready: "Read.",
  failed: "The drawing could not be read.",
  missing: "The drawing was read, but its lines are no longer on the server: read it again.",
};

type Changes = { plans_kept: string[]; plans_missing: string[]; columns: Record<string, { kept: number; added: number; removed: number }>; rooms: { kept: number; added: string[]; resized: string[]; removed: string[] } };
type Geo = PlanGeo;
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
  const [geoError, setGeoError] = useState<string | null>(null);
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
  const drawingReady = out?.model_drawing?.state === "ready";
  useEffect(() => {
    setGeoError(null);
    if (fileId && drawingReady)
      api<GeoV2 | Geo>(`/api/takeoff/files/${fileId}/geometry`).then(
        (raw) => setGeo(decodeGeometry(raw)),
        (e) => setGeoError(errorText(e)), // never a page stuck on loading: the reason instead
      );
  }, [fileId, drawingReady]);
  // a drawing being read: its stage, polled
  const reading = !!out && [out.model_drawing, ...out.revisions].some((r) => r && (r.state === "queued" || r.state === "reading"));
  useEffect(() => {
    if (!reading) return;
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, [reading, out, load]);
  async function readDrawing(revisionId: number) {
    await run(() => api(`/api/takeoff/revisions/${revisionId}/read`, { method: "POST", json: { architect: null } }), "Queued: the drawing is being read");
    load();
  }

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
    <Field label="The client's BIM file (IFC)">
      <input type="file" accept=".ifc" disabled={busy} onChange={(e) => e.target.files?.[0] && void uploadIfc(e.target.files[0])} />
    </Field>
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
          <Link className={buttonClass()} to={`/sites/${siteId}?tab=3d`}>
            See it in 3D
          </Link>
          {data && out.can_edit && (
            <Button variant="primary" disabled={busy || !dirty} onClick={() => void save()}>
              Save{out.model ? ` (version ${out.model.version + 1})` : ""}
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-ok">{msg}</div>}
      {!out.model && (
        <Card as="div">
          <h2>Start from a drawing</h2>
          {out.revisions
            .filter((r) => r.state !== "ready")
            .map((r) => (
              <DrawingStateCard key={r.revision_id} rev={r} canRead={out.can_read} busy={busy} onRead={(id) => void readDrawing(id)} />
            ))}
          {out.drawings.length === 0 ? (
            <p>
              {out.revisions.length
                ? "Read the drawing first (above); then build from it."
                : "No AutoCAD drawing on this site yet: upload it in the site's Drawings, then read it here or in the AutoCAD takeoff."}{" "}
              <Link to={`/sites/${siteId}/takeoff`}>AutoCAD takeoff</Link>
            </p>
          ) : (
            out.drawings.map((d) => (
              <p key={d.cad_file_id}>
                {d.title} (rev {d.rev_no}){" "}
                {out.can_edit && (
                  <Button variant="primary" size="small" disabled={busy} onClick={() => void start(d.cad_file_id)}>
                    Build from this drawing
                  </Button>
                )}
              </p>
            ))
          )}
          <p className="small muted">Or, when the client gave a BIM model, its IFC file (it is shown as it is; planning links its spaces to our places once):</p>
          {ifcInput}
        </Card>
      )}
      {newer && out.can_edit && (
        <div className="alert alert-warn">
          A newer revision is read: {newer.title} rev {newer.rev_no}.{" "}
          <Button size="small" disabled={busy} onClick={() => void start(newer.cad_file_id)}>
            Move the model onto it
          </Button>{" "}
          (what still matches is kept; the changes are listed)
        </div>
      )}
      {out.model?.changes && <ChangesNote changes={out.model.changes} />}
      {data && (
        <div className="builder-grid">
          <Card as="div" className="builder-side">
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
              <Field label="Add a floor type from a plan" bare>
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
              </Field>
            )}
            {type && out.can_edit && (
              <div className="builder-steps">
                <div className="builder-row">
                  <label className="check">
                    <input type="checkbox" checked={type.walls !== false} onChange={(e) => updType((t) => (t.walls = e.target.checked))} /> Walls (off for a roof or a terrace)
                  </label>
                  <Button
                    size="small"
                    onClick={() => {
                      if (!confirm(`Remove the floor type ${type.name}? (its floors fall back to the reference plan)`)) return;
                      update((d) => (d.floor_types = d.floor_types.filter((t) => t.key !== type.key)));
                      setSel(null);
                    }}
                  >
                    Remove this floor type
                  </Button>
                </div>
                <Field label="Floors this plan is for">
                  <input defaultValue={floorsText(type.floors)} key={type.key} onBlur={(e) => updType((t) => (t.floors = parseFloors(e.target.value)))} placeholder="3-12, or 2,3,5" />
                </Field>
                <div className="builder-row">
                  <b>1. Outline</b>
                  <Button size="small" disabled={busy || !type.region} onClick={() => void propose()}>
                    Propose from the walls
                  </Button>
                  <Button size="small" className={tool === "outline" ? "active" : ""} onClick={() => (setTool("outline"), setTrace([]))}>
                    Trace
                  </Button>
                </div>
                <div className="builder-row">
                  <b>2. Columns</b>
                  <Button size="small" disabled={busy || !type.outline.length} onClick={() => void findColumns()}>
                    Find columns
                  </Button>
                  <Button size="small" className={tool === "columns" ? "active" : ""} disabled={!type.outline.length} onClick={() => setTool("columns")}>
                    Add / remove
                  </Button>
                  <Button size="small" disabled={!type.columns.length || type.columns_confirmed} onClick={() => (updType((t) => (t.columns_confirmed = true)), setTool("none"))}>
                    {type.columns_confirmed ? "Confirmed" : "Confirm"}
                  </Button>
                </div>
                <div className="builder-row small">
                  Column sizes from
                  <Field label="Smallest column side (m)" bare>
                    <input type="number" step="0.05" min={0.1} max={1} style={{ width: "4.5em" }} value={data.settings.column_min_m} onChange={(e) => update((d) => (d.settings.column_min_m = Number(e.target.value)))} aria-label="Smallest column side (m)" />
                  </Field>
                  to
                  <Field label="Largest column side (m)" bare>
                    <input type="number" step="0.05" min={0.2} max={2} style={{ width: "4.5em" }} value={data.settings.column_max_m} onChange={(e) => update((d) => (d.settings.column_max_m = Number(e.target.value)))} aria-label="Largest column side (m)" />
                  </Field>
                  m (this site's setting: save, then find again)
                </div>
                <div className="builder-row">
                  <b>3. Cores</b>
                  <Button size="small" className={tool === "stair" ? "active" : ""} onClick={() => (setTool("stair"), setTrace([]))}>
                    Trace a stair
                  </Button>
                  <Button size="small" className={tool === "lift" ? "active" : ""} onClick={() => (setTool("lift"), setTrace([]))}>
                    Trace a lift
                  </Button>
                </div>
                {type.cores.map((c, i) => (
                  <div key={i} className="builder-row small">
                    {c.kind === "stair" ? "Stair" : "Lift"} {i + 1}
                    {c.kind === "stair" && (
                      <Field label="Risers" bare>
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
                      </Field>
                    )}
                    <Button size="small" onClick={() => updType((t) => t.cores.splice(i, 1))}>
                      Remove
                    </Button>
                  </div>
                ))}
                <div className="builder-row">
                  <b>4. Beams</b>
                  <Button size="small" className={tool === "beam" ? "active" : ""} disabled={type.columns.length < 2} onClick={() => (setTool("beam"), setBeamFrom(null))}>
                    Pick two columns
                  </Button>
                  <span className="small">{type.beams.length} beam(s)</span>
                  {type.beams.length > 0 && (
                    <Button size="small" onClick={() => updType((t) => (t.beams = []))}>
                      Clear
                    </Button>
                  )}
                </div>
                {(tool === "outline" || tool === "stair" || tool === "lift") && (
                  <div className="builder-row">
                    <span className="small">{trace.length} corner(s): click the plan (it snaps to the walls)</span>
                    <Button variant="primary" size="small" disabled={trace.length < 3} onClick={finishTrace}>
                      Finish
                    </Button>
                    <Button size="small" onClick={() => setTrace((t) => t.slice(0, -1))}>
                      Undo
                    </Button>
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
                <Field label={label} key={k}>
                  <input type="number" step="0.001" value={data.settings[k]} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings[k] = Number(e.target.value)))} />
                </Field>
              ))}
              <label className="check">
                <input type="checkbox" checked={data.settings.beams_on_walls} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.beams_on_walls = e.target.checked))} /> Beams along the column lines
              </label>
              <label className="check">
                <input type="checkbox" checked={data.settings.ifc} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.ifc = e.target.checked))} /> Show the client's BIM file (IFC)
              </label>
              <Field label="BIM file limit for a laptop (MB)">
                <input type="number" min={10} max={600} value={data.settings.ifc_max_mb} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.ifc_max_mb = Number(e.target.value)))} />
              </Field>
              <div style={{ gridColumn: "1 / -1" }}>{ifcInput}</div>
              <Field label="Glow">
                <select value={data.settings.bloom} disabled={!out.can_edit} onChange={(e) => update((d) => (d.settings.bloom = e.target.value as Settings["bloom"]))}>
                  <option value="auto">Auto (off on weak devices)</option>
                  <option value="on">Always on</option>
                  <option value="off">Off</option>
                </select>
              </Field>
            </div>
            <h2>Floors</h2>
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Floor</th>
                  <th>Type</th>
                  <th className="num">Level (m)</th>
                  <th className="num">Height (m)</th>
                </tr>
              </thead>
              <tbody>
                {[...data.floors]
                  .sort((a, b) => b.level - a.level)
                  .map((f) => {
                    const t = data.floor_types.find((x) => x.floors.includes(f.level));
                    const el = out.model?.floors.find((x) => x.level === f.level);
                    const src = f.level_by_hand ? "hand" : el?.level_source;
                    return (
                      <tr key={f.node_id} className={el?.level_flag ? "row-warn" : undefined}>
                        <td>
                          {f.name}
                          {el?.level_flag && <div className="small text-warn">{el.level_flag}</div>}
                        </td>
                        <td className="small">{t?.name ?? <span className="muted">— (the reference plan)</span>}</td>
                        <td className="num">
                          <Field label={`Level of ${f.name}`} bare>
                            <input
                              type="number"
                              step="0.001"
                              style={{ width: "6.5em" }}
                              value={f.level_by_hand ? (f.elevation_m ?? "") : (el?.elevation_m ?? "")}
                              disabled={!out.can_edit}
                              onChange={(e) =>
                                update((d) => {
                                  const x = d.floors.find((y) => y.node_id === f.node_id)!;
                                  x.elevation_m = e.target.value === "" ? null : Number(e.target.value);
                                  x.level_by_hand = e.target.value !== "";
                                })
                              }
                              aria-label={`Level of ${f.name}`}
                            />
                          </Field>
                          <div className="small muted">{src === "section" ? "from the section" : src === "hand" ? "typed" : "default"}</div>
                        </td>
                        <td className="num">
                          <Field label={`Height of ${f.name}`} bare>
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
                          </Field>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            {(out.model?.unmatched_levels.length ?? 0) > 0 && (
              <p className="small text-warn">
                Section levels no floor uses: {out.model!.unmatched_levels.map((v) => `${v >= 0 ? "+" : ""}${v.toFixed(3)}`).join(", ")} m (basements, a tank or a roof room the site structure has not got). Add the floor to the structure, or leave them.
              </p>
            )}
          </Card>
          <Card as="div" className="builder-plan">
            {out.model_drawing && out.model_drawing.state !== "ready" ? (
              <DrawingStateCard rev={out.model_drawing} canRead={out.can_read} busy={busy} onRead={(id) => void readDrawing(id)} />
            ) : geoError ? (
              <div className="alert alert-error">
                The drawing could not be shown: {geoError}
                {out.can_read && out.model_drawing && (
                  <div>
                    <Button size="small" disabled={busy} onClick={() => void readDrawing(out.model_drawing!.revision_id)}>
                      Read the drawing again
                    </Button>
                  </div>
                )}
              </div>
            ) : geo && type ? (
              <PlanCanvas geo={geo} type={type} trace={trace} tool={tool} beamFrom={beamFrom} onClick={(x, y, r) => void onPlanClick(x, y, r)} />
            ) : !type ? (
              <p className="muted">Pick a floor type on the left.</p>
            ) : (
              <p className="muted">Loading the drawing…</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

/** A drawing that is not ready: its state, its stage while it is read, the reason when it failed,
 *  and "Read the drawing" for those who may read drawings. */
function DrawingStateCard({ rev, canRead, busy, onRead }: { rev: DrawingRev; canRead: boolean; busy: boolean; onRead: (revisionId: number) => void }) {
  if (rev.state === "queued" || rev.state === "reading") return <ReadProgress filename={rev.filename} progress={rev.progress} since={rev.progress_at} />;
  return (
    <div className={`alert ${rev.state === "failed" || rev.state === "missing" ? "alert-error" : "alert-warn"} drawing-state`}>
      <b>
        {rev.title} (R{rev.rev_no})
      </b>{" "}
      {STATE_TEXT[rev.state]}
      {rev.error && <div className="small">{rev.error}</div>}
      {canRead ? (
        <div>
          <Button variant="primary" size="small" disabled={busy} onClick={() => onRead(rev.revision_id)}>
            {rev.state === "not read" ? "Read the drawing" : "Read the drawing again"}
          </Button>
        </div>
      ) : (
        <div className="small">Ask billing or planning to read it.</div>
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
    <Card as="div">
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
    </Card>
  );
}

/** The plan with the outline, columns, cores and beams over it: pan, zoom, click. */
function PlanCanvas({ geo, type, trace, tool, beamFrom, onClick }: { geo: Geo; type: FType; trace: Pt[]; tool: Tool; beamFrom: number | null; onClick: (x: number, y: number, radius: number) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
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
  const glOk = useGlPlan(glRef, geo, view, hidden);

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
    ctx.clearRect(0, 0, w, h);
    const { cx, cy, scale } = view;
    const X = (x: number) => (x - cx) * scale + w / 2;
    const Y = (y: number) => h / 2 - (y - cy) * scale;
    const [minX, maxX, minY, maxY] = [cx - w / 2 / scale, cx + w / 2 / scale, cy - h / 2 / scale, cy + h / 2 / scale];
    ctx.strokeStyle = ART.drawGrid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (!glOk.current) {
      ctx.fillStyle = ART.paper; // no WebGL here: the lines on this canvas
      ctx.fillRect(0, 0, w, h);
    }
    for (const [layer, g] of glOk.current ? [] : Object.entries(geo.geometry)) {
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
    poly(type.outline, ART.drawOutline, "rgba(11,132,198,0.08)");
    type.cores.forEach((c) => poly(c.outline, ART.drawCore, "rgba(142,92,200,0.18)"));
    ctx.lineWidth = 3;
    ctx.strokeStyle = ART.drawBeam;
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
      ctx.fillStyle = i === beamFrom ? THEMES.dark.block : type.columns_confirmed ? THEMES.dark.done : THEMES.dark.prog;
      ctx.fillRect(X(x - cw / 2), Y(y + cd / 2), Math.max(4, cw * scale), Math.max(4, cd * scale));
    });
    if (trace.length) {
      ctx.setLineDash([6, 4]);
      poly(trace, ART.aci1, null, false, 2);
      ctx.setLineDash([]);
      for (const p of trace) {
        ctx.fillStyle = ART.aci1;
        ctx.fillRect(X(p[0]) - 4, Y(p[1]) - 4, 8, 8);
      }
    }
  }, [geo, hidden, view, type, trace, beamFrom, glOk]);
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
      <canvas ref={glRef} className="plan-gl" aria-hidden="true" />
      <canvas ref={ref} onPointerDown={down} onPointerMove={move} onPointerUp={up} onWheel={wheel} aria-label="The plan" style={{ cursor: tool === "none" ? "grab" : "crosshair" }} />
      <div className="takeoff-zoom">
        <Button size="small" onClick={() => setView((v) => ({ ...v, scale: v.scale * 1.5 }))} aria-label="Zoom in">
          +
        </Button>
        <Button size="small" onClick={() => setView((v) => ({ ...v, scale: v.scale / 1.5 }))} aria-label="Zoom out">
          −
        </Button>
        <Button size="small" onClick={() => setView({ cx: 0, cy: 0, scale: 0 })}>
          Fit
        </Button>
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
