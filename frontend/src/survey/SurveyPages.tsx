import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { SiteNode } from "../types";
import { formatArea, formatLength, parseLength, parseSize } from "./units";
import type { Unit } from "./units";

const Camera = lazy(() => import("./Camera"));

export type Photo = { id: number; filename: string; has_overlay: boolean; mode: string | null; marker_found: boolean | null };
export type Area = {
  id: number;
  node_id: number | null;
  tower: string | null;
  floor_label: string | null;
  name: string;
  area_type_id: number | null;
  area_type: string | null;
  shape: "rect" | "polygon" | "direct";
  length_m: string | null;
  width_m: string | null;
  polygon_m: number[][] | null;
  direct_area_sqm: string | null;
  deductions_sqm: string;
  perimeter_m: string | null;
  perimeter_manual: boolean;
  upturn_mm: string;
  wall_height_m: string | null;
  sunk_depth_mm: string | null;
  count: number;
  system_id: number | null;
  wastage_override_percent: string | null;
  method: string;
  accuracy_note: string | null;
  remarks: string | null;
  camera_method: string | null;
  camera_floor_sqm: string | null;
  floor_area_sqm: string;
  treated_area_sqm: string;
  camera_measured: boolean;
  mismatch_percent: string | null;
  mismatch_flag: boolean;
  ai_suggestion: {
    call_id: number;
    area_type?: string;
    area_type_id?: number | null;
    system?: string;
    system_id?: number | null;
    condition_notes?: string;
    confidence?: string;
  } | null;
  photos: Photo[];
};
export type Survey = {
  id: number;
  code: string;
  title: string;
  surveyed_on: string | null;
  status: "draft" | "submitted" | "approved";
  notes: string | null;
  lead_id: number | null;
  tender_id: number | null;
  site_id: number | null;
  parent: { kind: string; id: number; code: string; name: string; link: string };
  surveyed_by_name: string | null;
  approved_by_name: string | null;
  areas: Area[];
  totals: { treated: string; by_type: Record<string, string>; by_floor: Record<string, string> };
  can_edit: boolean;
  can_approve: boolean;
  ai_available: boolean;
  photo_required: boolean;
};
type AreaType = {
  id: number;
  name: string;
  default_system_id: number | null;
  default_upturn_mm: string;
  default_wastage_percent: string | null;
  includes_walls: boolean;
  needs_sunk_depth: boolean;
  sort_order: number;
  is_active: boolean;
  confirmed: boolean;
};
type Lookups = { area_types: AreaType[]; systems: { id: number; name: string; unit: string }[]; unit: Unit };

const STATUS_BADGE: Record<string, string> = { draft: "badge-muted", submitted: "badge-info", approved: "badge-ok" };

// --- list ----------------------------------------------------------------------------------------

export function SurveysList() {
  const [params] = useSearchParams();
  const filter = ["lead", "tender", "site"].map((k) => [k, params.get(k)] as const).find(([, v]) => v);
  const q = filter ? `?${filter[0]}_id=${filter[1]}` : "";
  const [rows, setRows] = useState<
    { id: number; code: string; title: string; status: string; surveyed_on: string | null; parent: Survey["parent"]; areas: number; treated: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const { can } = useAuth();
  useEffect(() => {
    api<typeof rows>(`/api/surveys${q}`).then(setRows, (err) => setError(errorText(err)));
  }, [q]);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Site surveys</h1>
          <p className="muted small">Areas measured on site; quantities per area, floor and survey; BOQ lines and indents from them.</p>
        </div>
        <div className="page-actions">
          <Link to="/surveys/pilot" className="btn btn-small btn-ghost">
            Camera pilot
          </Link>
          <button className="btn btn-small btn-ghost" onClick={() => void downloadFile("/api/surveys/marker-sheet.pdf").catch((e) => alert(errorText(e)))}>
            ⤓ Marker sheet A4 (up to 1.5 m)
          </button>
          <button className="btn btn-small btn-ghost" onClick={() => void downloadFile("/api/surveys/marker-sheet.pdf?size=a3").catch((e) => alert(errorText(e)))}>
            ⤓ Marker sheet A3 (up to 2.5 m)
          </button>
          {can("survey.edit") && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New survey
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Survey</th>
              <th>For</th>
              <th>Date</th>
              <th className="num">Areas</th>
              <th className="num">Treated sqm</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/surveys/${s.id}`}>{s.code}</Link>
                  <div className="small muted">{s.title}</div>
                </td>
                <td className="small">
                  {s.parent.kind} <Link to={s.parent.link}>{s.parent.code}</Link>
                </td>
                <td className="nowrap small">{s.surveyed_on ?? "—"}</td>
                <td className="num">{s.areas}</td>
                <td className="num">{Number(s.treated).toFixed(2)}</td>
                <td>
                  <span className={`badge ${STATUS_BADGE[s.status]}`}>{s.status}</span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No surveys yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {creating && <NewSurvey preset={filter ? { [`${filter[0]}_id`]: Number(filter[1]) } : {}} onClose={() => setCreating(false)} />}
    </>
  );
}

/** Start a survey for a lead, tender or site (the parent picked by its code). */
export function NewSurvey({ preset, onClose }: { preset: Record<string, number>; onClose: () => void }) {
  const navigate = useNavigate();
  const [kind, setKind] = useState<"site_id" | "tender_id" | "lead_id">((Object.keys(preset)[0] as "site_id") ?? "site_id");
  const [parentId, setParentId] = useState<string>(Object.values(preset)[0] ? String(Object.values(preset)[0]) : "");
  const [options, setOptions] = useState<{ id: number; label: string }[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const path = kind === "site_id" ? "/api/sites?limit=500" : kind === "tender_id" ? "/api/tenders?limit=500" : "/api/leads?limit=500";
    api<{ items: { id: number; code: string; name?: string; contact_name?: string }[] }>(path).then(
      (r) => setOptions(r.items.map((x) => ({ id: x.id, label: `${x.code} ${x.name ?? x.contact_name ?? ""}` }))),
      () => setOptions([]),
    );
  }, [kind]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const s = await api<Survey>("/api/surveys", { method: "POST", json: { [kind]: Number(parentId), title } });
      navigate(`/surveys/${s.id}`);
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="New site survey" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>For a</span>
          <select value={kind} onChange={(e) => (setKind(e.target.value as typeof kind), setParentId(""))} disabled={Object.keys(preset).length > 0}>
            <option value="site_id">Site</option>
            <option value="tender_id">Tender</option>
            <option value="lead_id">Lead</option>
          </select>
        </label>
        <label className="field">
          <span>Which</span>
          <select value={parentId} onChange={(e) => setParentId(e.target.value)} required>
            <option value="">Choose…</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Title</span>
          <input className="tap-input" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={300} placeholder="e.g. Tower A wet areas" />
        </label>
        <div className="form-actions">
          <button className="btn btn-primary tap-wide">Start</button>
        </div>
      </form>
    </Modal>
  );
}

// --- one survey ----------------------------------------------------------------------------------

export function SurveyDetail() {
  const { id } = useParams();
  const [s, setS] = useState<Survey | null>(null);
  const [lk, setLk] = useState<Lookups | null>(null);
  const [nodes, setNodes] = useState<SiteNode[]>([]);
  const [tab, setTab] = useState<"areas" | "products" | "outputs">("areas");
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Area | "new" | null>(null);
  const [camera, setCamera] = useState<Area | null>(null);
  const [repeat, setRepeat] = useState<Area | null>(null);
  const load = useCallback(() => api<Survey>(`/api/surveys/${id}`).then(setS, (err) => setError(errorText(err))), [id]);
  useEffect(() => {
    void load();
    api<Lookups>("/api/surveys/lookups").then(setLk, (err) => setError(errorText(err)));
  }, [load]);
  useEffect(() => {
    if (s?.site_id) api<SiteNode[]>(`/api/sites/${s.site_id}/nodes`).then(setNodes, () => setNodes([]));
  }, [s?.site_id]);
  async function act(path: string, method = "POST", json?: unknown) {
    setError(null);
    try {
      setS(await api<Survey>(path, { method, json }));
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function setUnit(unit: Unit) {
    await api("/api/surveys/me/unit", { method: "PUT", json: { unit } });
    setLk((l) => (l ? { ...l, unit } : l));
  }
  if (!s || !lk) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const unit = lk.unit;
  const groups = groupAreas(s.areas);
  return (
    <div className="survey-page">
      <p className="breadcrumb">
        <Link to="/surveys">Surveys</Link> / {s.parent.kind} <Link to={s.parent.link}>{s.parent.code}</Link>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {s.code} <span className={`badge ${STATUS_BADGE[s.status]}`}>{s.status}</span>
          </h1>
          <p className="muted small">
            {s.title} · {s.parent.name} · {s.surveyed_on ?? ""} {s.surveyed_by_name ? `· ${s.surveyed_by_name}` : ""}
          </p>
        </div>
        <div className="page-actions">
          <span className="unit-switch">
            {(["m", "ftin"] as Unit[]).map((u) => (
              <button key={u} className={`btn btn-small ${unit === u ? "btn-primary" : "btn-ghost"}`} onClick={() => void setUnit(u)}>
                {u === "m" ? "m" : "ft-in"}
              </button>
            ))}
          </span>
          {s.status === "draft" && s.can_edit && (
            <button className="btn btn-small" onClick={() => void act(`/api/surveys/${s.id}/submit`)}>
              Submit
            </button>
          )}
          {s.status === "submitted" && s.can_approve && (
            <button className="btn btn-small btn-primary" onClick={() => void act(`/api/surveys/${s.id}/approve`)}>
              Approve
            </button>
          )}
          {s.status !== "draft" && (s.can_approve || s.status === "submitted") && (
            <button className="btn btn-small btn-ghost" onClick={() => void act(`/api/surveys/${s.id}/reopen`)}>
              Reopen
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="tabs tabs-inline dash-tabs">
        {(["areas", "products", "outputs"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "areas" ? `Areas (${s.areas.length})` : t === "products" ? "Products" : "BOQ, indent, PDF"}
          </button>
        ))}
      </div>
      {tab === "areas" && (
        <>
          {s.can_edit && (
            <button className="btn btn-primary tap-wide top-gap" onClick={() => setEditing("new")}>
              + Add area
            </button>
          )}
          {groups.map(([floor, areas]) => (
            <section key={floor} className="survey-floor">
              <h3 className="section-title">{floor}</h3>
              {areas.map((a) => (
                <AreaCard
                  key={a.id}
                  surveyId={s.id}
                  a={a}
                  unit={unit}
                  canEdit={s.can_edit}
                  aiAvailable={s.ai_available}
                  photoRequired={s.photo_required}
                  onEdit={() => setEditing(a)}
                  onCamera={() => setCamera(a)}
                  onRepeat={() => setRepeat(a)}
                  onChange={setS}
                  onError={setError}
                />
              ))}
            </section>
          ))}
          {s.areas.length === 0 && <p className="empty">No areas yet: add the first one.</p>}
          <Totals s={s} />
        </>
      )}
      {tab === "products" && <Products survey={s} />}
      {tab === "outputs" && <Outputs survey={s} onError={setError} />}
      {editing && (
        <AreaForm
          survey={s}
          area={editing === "new" ? null : editing}
          lookups={lk}
          nodes={nodes}
          onClose={() => setEditing(null)}
          onSaved={(next, again) => {
            setS(next);
            if (!again) setEditing(null);
          }}
        />
      )}
      {repeat && <RepeatDialog area={repeat} onClose={() => setRepeat(null)} onDone={(next) => (setS(next), setRepeat(null))} />}
      {camera && (
        <Suspense fallback={<div className="camera-screen">Starting the camera…</div>}>
          <Camera area={camera} onClose={() => setCamera(null)} onSaved={(next) => (setS(next), setCamera(null))} />
        </Suspense>
      )}
    </div>
  );
}

function groupAreas(areas: Area[]): [string, Area[]][] {
  const out = new Map<string, Area[]>();
  for (const a of areas) {
    const k = [a.tower, a.floor_label].filter(Boolean).join(" · ") || "No floor";
    out.set(k, [...(out.get(k) ?? []), a]);
  }
  return [...out.entries()];
}

function sizeText(a: Area, unit: Unit): string {
  if (a.shape === "rect") return `${formatLength(a.length_m, unit)} × ${formatLength(a.width_m, unit)}`;
  if (a.shape === "polygon") return `${(a.polygon_m ?? []).length}-corner outline`;
  return formatArea(a.direct_area_sqm, unit);
}

function AreaCard({
  surveyId,
  a,
  unit,
  canEdit,
  aiAvailable,
  photoRequired,
  onEdit,
  onCamera,
  onRepeat,
  onChange,
  onError,
}: {
  surveyId: number;
  a: Area;
  unit: Unit;
  canEdit: boolean;
  aiAvailable: boolean;
  photoRequired: boolean;
  onEdit: () => void;
  onCamera: () => void;
  onRepeat: () => void;
  onChange: (s: Survey) => void;
  onError: (e: string) => void;
}) {
  const [thumb, setThumb] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const first = a.photos[0];
  useEffect(() => {
    if (!first) return;
    let url: string | null = null;
    void fetchObjectUrl(`/api/surveys/photos/${first.id}${first.has_overlay ? "?overlay=true" : ""}`).then((u) => {
      url = u;
      setThumb(u);
    });
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [first]);
  async function run(p: Promise<Survey>) {
    setBusy(true);
    try {
      onChange(await p);
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card area-card">
      <div className="area-main">
        {thumb ? <img src={thumb} alt="" className="area-thumb" /> : <div className={`area-thumb empty ${photoRequired ? "needs" : ""}`}>no photo</div>}
        <div className="area-text">
          <strong>{a.name}</strong>
          <div className="small muted">
            {a.area_type ?? "no type"} · {sizeText(a, unit)}
            {a.count > 1 ? ` · × ${a.count}` : ""}
          </div>
          <div className="small">
            <b>{formatArea(a.treated_area_sqm, unit)}</b> treated
            {a.camera_measured ? (
              <span className="badge badge-warn">camera measured ({a.method === "ar" ? "AR" : "marker"})</span>
            ) : (
              <span className="badge badge-muted">{a.method}</span>
            )}
            {a.mismatch_flag && <span className="badge badge-danger">camera vs laser {a.mismatch_percent}%</span>}
          </div>
          {a.ai_suggestion && <AiSuggestion a={a} onChange={onChange} onError={onError} />}
        </div>
      </div>
      {canEdit && (
        <div className="area-actions">
          <button className="btn btn-small btn-primary" onClick={onCamera}>
            📷 Photo / measure
          </button>
          <button className="btn btn-small" onClick={onEdit}>
            Edit
          </button>
          <button className="btn btn-small btn-ghost" disabled={busy} onClick={() => void run(api<Survey>(`/api/surveys/areas/${a.id}/copy`, { method: "POST" }))}>
            Copy
          </button>
          <button className="btn btn-small btn-ghost" onClick={onRepeat}>
            Repeat on floors
          </button>
          {aiAvailable && first && (
            <button
              className="btn btn-small btn-ghost"
              disabled={busy}
              onClick={() =>
                void run(api(`/api/surveys/areas/${a.id}/suggest`, { method: "POST", json: { photo_id: first.id } }).then(() => api<Survey>(`/api/surveys/${surveyId}`)))
              }
            >
              ✨ Suggest
            </button>
          )}
          <button
            className="btn btn-small btn-ghost"
            disabled={busy}
            onClick={() => confirm(`Delete ${a.name}?`) && void run(api<Survey>(`/api/surveys/areas/${a.id}`, { method: "DELETE" }))}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

function AiSuggestion({ a, onChange, onError }: { a: Area; onChange: (s: Survey) => void; onError: (e: string) => void }) {
  const sug = a.ai_suggestion!;
  const [pick, setPick] = useState({ area_type: !!sug.area_type_id, system: !!sug.system_id, notes: !!sug.condition_notes });
  return (
    <div className="ai-box small">
      <b>AI suggestion</b> ({sug.confidence ?? "?"} confidence; sizes are never changed)
      {sug.area_type && (
        <label className="check">
          <input type="checkbox" checked={pick.area_type} disabled={!sug.area_type_id} onChange={(e) => setPick({ ...pick, area_type: e.target.checked })} /> Type: {sug.area_type}
        </label>
      )}
      {sug.system && (
        <label className="check">
          <input type="checkbox" checked={pick.system} disabled={!sug.system_id} onChange={(e) => setPick({ ...pick, system: e.target.checked })} /> System: {sug.system}
        </label>
      )}
      {sug.condition_notes && (
        <label className="check">
          <input type="checkbox" checked={pick.notes} onChange={(e) => setPick({ ...pick, notes: e.target.checked })} /> Notes: {sug.condition_notes}
        </label>
      )}
      <button
        className="btn btn-small"
        onClick={() => void api<Survey>(`/api/surveys/ai/${sug.call_id}/accept`, { method: "POST", json: pick }).then(onChange, (e) => onError(errorText(e)))}
      >
        Accept ticked
      </button>
    </div>
  );
}

function Totals({ s }: { s: Survey }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`survey-totals ${open ? "open" : ""}`} onClick={() => setOpen(!open)}>
      <div className="toolbar">
        <span>
          Treated area <b>{Number(s.totals.treated).toFixed(2)} sqm</b> · {s.areas.length} areas
        </span>
        <span className="small muted">{open ? "▼" : "▲ by type and floor"}</span>
      </div>
      {open && (
        <div className="totals-grid small">
          <div>
            {Object.entries(s.totals.by_type).map(([k, v]) => (
              <div key={k} className="toolbar">
                <span>{k}</span> <b>{Number(v).toFixed(2)}</b>
              </div>
            ))}
          </div>
          <div>
            {Object.entries(s.totals.by_floor).map(([k, v]) => (
              <div key={k} className="toolbar">
                <span>{k}</span> <b>{Number(v).toFixed(2)}</b>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --- area form -----------------------------------------------------------------------------------

function AreaForm({
  survey,
  area,
  lookups,
  nodes,
  onClose,
  onSaved,
}: {
  survey: Survey;
  area: Area | null;
  lookups: Lookups;
  nodes: SiteNode[];
  onClose: () => void;
  onSaved: (s: Survey, again: boolean) => void;
}) {
  const unit = lookups.unit;
  const last = survey.areas[survey.areas.length - 1];
  const [f, setF] = useState(() => ({
    node_id: area?.node_id ? String(area.node_id) : last && !area ? String(last.node_id ?? "") : "",
    tower: area?.tower ?? (!area ? (last?.tower ?? "") : ""),
    floor_label: area?.floor_label ?? (!area ? (last?.floor_label ?? "") : ""),
    area_type_id: area?.area_type_id ? String(area.area_type_id) : "",
    name: area?.name ?? "",
    shape: area?.shape ?? "rect",
    size: area?.shape === "rect" && area.length_m ? `${area.length_m} x ${area.width_m}` : "",
    direct: area?.direct_area_sqm ?? "",
    perimeter: area?.perimeter_manual || area?.shape === "direct" ? (area?.perimeter_m ?? "") : "",
    deductions: area?.deductions_sqm && Number(area.deductions_sqm) ? area.deductions_sqm : "",
    upturn: area ? area.upturn_mm : "",
    wall: area?.wall_height_m ?? "",
    sunk: area?.sunk_depth_mm ?? "",
    count: String(area?.count ?? 1),
    system_id: area?.system_id ? String(area.system_id) : "",
    wastage: area?.wastage_override_percent ?? "",
    method: area && !area.camera_measured ? area.method : "laser",
    remarks: area?.remarks ?? "",
  }));
  const [error, setError] = useState<string | null>(null);
  const type = lookups.area_types.find((t) => String(t.id) === f.area_type_id);
  const parsed = f.shape === "rect" ? parseSize(f.size, unit) : null;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const floorOptions = useMemo(
    () =>
      nodes.filter(
        (n) => n.kind === "floor" || n.kind === "basement" || n.kind === "terrace" || n.kind === "flat" || n.kind === "toilet" || n.kind === "kitchen" || n.kind === "balcony",
      ),
    [nodes],
  );

  function lengthM(v: string): number | null {
    return v === "" ? null : parseLength(v, unit);
  }
  async function save(again: boolean) {
    setError(null);
    if (f.shape === "rect" && !parsed) return setError(unit === "m" ? "Type the size as length x width, e.g. 3.2 x 2.21" : "Type the size as length x width, e.g. 10'6 x 7'3");
    const node = nodes.find((n) => String(n.id) === f.node_id);
    const body = {
      node_id: f.node_id ? Number(f.node_id) : null,
      tower: f.tower || null,
      floor_label: f.floor_label || (node ? node.name : null),
      name: f.name || [f.floor_label || node?.name, type?.name].filter(Boolean).join(" ") || "Area",
      area_type_id: f.area_type_id ? Number(f.area_type_id) : null,
      shape: f.shape === "polygon" && area?.polygon_m ? "polygon" : f.shape === "polygon" ? "direct" : f.shape,
      length_m: parsed?.[0] ?? null,
      width_m: parsed?.[1] ?? null,
      polygon_m: area?.polygon_m ?? null,
      direct_area_sqm: f.shape === "direct" ? Number(f.direct || 0) * (unit === "ftin" ? 0.09290304 : 1) : null,
      perimeter_m: f.perimeter ? lengthM(f.perimeter) : null,
      perimeter_manual: !!f.perimeter && f.shape !== "direct",
      deductions_sqm: Number(f.deductions || 0) * (unit === "ftin" ? 0.09290304 : 1),
      upturn_mm: f.upturn === "" ? null : Number(f.upturn),
      wall_height_m: f.wall ? lengthM(f.wall) : null,
      sunk_depth_mm: f.sunk === "" ? null : Number(f.sunk),
      count: Number(f.count || 1),
      system_id: f.system_id ? Number(f.system_id) : null,
      wastage_override_percent: f.wastage === "" ? null : Number(f.wastage),
      method: f.method,
      remarks: f.remarks || null,
    };
    try {
      const next = area
        ? await api<Survey>(`/api/surveys/areas/${area.id}`, { method: "PUT", json: body })
        : await api<Survey>(`/api/surveys/${survey.id}/areas`, { method: "POST", json: body });
      onSaved(next, again);
      if (again) setF({ ...f, name: "", size: "", direct: "", deductions: "", remarks: "" });
    } catch (err) {
      setError(errorText(err));
    }
  }
  const systemName = (id: number | null | undefined) => lookups.systems.find((x) => x.id === id)?.name;
  return (
    <Modal title={area ? `Edit ${area.name}` : "Add an area"} onClose={onClose}>
      <form
        className="area-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save(false);
        }}
      >
        {error && <div className="alert alert-error">{error}</div>}
        {survey.site_id && nodes.length > 0 ? (
          <label className="field">
            <span>Place on the site</span>
            <select className="tap-input" value={f.node_id} onChange={set("node_id")}>
              <option value="">Not on the structure</option>
              {floorOptions.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.path}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="row-2">
          <label className="field">
            <span>Tower</span>
            <input className="tap-input" value={f.tower} onChange={set("tower")} placeholder="A" />
          </label>
          <label className="field">
            <span>Floor</span>
            <input className="tap-input" value={f.floor_label} onChange={set("floor_label")} placeholder="Floor 3, G, B1, Terrace" />
          </label>
        </div>
        <label className="field">
          <span>Area type</span>
          <select className="tap-input" value={f.area_type_id} onChange={(e) => setF({ ...f, area_type_id: e.target.value, upturn: area ? f.upturn : "" })}>
            <option value="">Choose…</option>
            {lookups.area_types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.confirmed ? "" : " (to be confirmed)"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Name</span>
          <input className="tap-input" value={f.name} onChange={set("name")} placeholder={[f.floor_label, type?.name].filter(Boolean).join(" ") || "Flat 302 Toilet 1"} />
        </label>
        <div className="tabs tabs-inline">
          {(["rect", "direct"] as const).map((sh) => (
            <button type="button" key={sh} className={`tab ${f.shape === sh ? "active" : ""}`} onClick={() => setF({ ...f, shape: sh })}>
              {sh === "rect" ? "Length × width" : "Area"}
            </button>
          ))}
          {area?.polygon_m && (
            <button type="button" className={`tab ${f.shape === "polygon" ? "active" : ""}`} onClick={() => setF({ ...f, shape: "polygon" })}>
              Camera outline
            </button>
          )}
        </div>
        {f.shape === "rect" && (
          <label className="field">
            <span>Size ({unit === "m" ? "metres: 3.2 x 2.21" : "feet-inches: 10'6 x 7'3"})</span>
            <input className="tap-input size-input" inputMode="text" value={f.size} onChange={set("size")} autoFocus={!area} />
            {f.size && (
              <span className={`small ${parsed ? "muted" : "text-danger"}`}>
                {parsed ? `${parsed[0].toFixed(3)} m × ${parsed[1].toFixed(3)} m = ${(parsed[0] * parsed[1]).toFixed(2)} sqm` : "Not readable yet"}
              </span>
            )}
          </label>
        )}
        {f.shape === "direct" && (
          <div className="row-2">
            <label className="field">
              <span>Area ({unit === "m" ? "sqm" : "sqft"})</span>
              <input className="tap-input" type="number" step="any" min="0" value={f.direct} onChange={set("direct")} required />
            </label>
            <label className="field">
              <span>Perimeter</span>
              <input className="tap-input" value={f.perimeter} onChange={set("perimeter")} placeholder={unit === "m" ? "m" : "ft-in"} />
            </label>
          </div>
        )}
        <div className="row-2">
          <label className="field">
            <span>Upturn (mm)</span>
            <input className="tap-input" type="number" min="0" value={f.upturn} onChange={set("upturn")} placeholder={type ? `${Number(type.default_upturn_mm)} (type)` : "0"} />
          </label>
          <label className="field">
            <span>Count</span>
            <input className="tap-input" type="number" min="1" value={f.count} onChange={set("count")} />
          </label>
        </div>
        <div className="row-2">
          {type?.includes_walls && (
            <label className="field">
              <span>Wall height</span>
              <input className="tap-input" value={f.wall} onChange={set("wall")} placeholder={unit === "m" ? "m" : "ft-in"} />
            </label>
          )}
          {type?.needs_sunk_depth && (
            <label className="field">
              <span>Sunk depth (mm)</span>
              <input className="tap-input" type="number" min="0" value={f.sunk} onChange={set("sunk")} />
            </label>
          )}
          <label className="field">
            <span>Deductions ({unit === "m" ? "sqm" : "sqft"})</span>
            <input className="tap-input" type="number" step="any" min="0" value={f.deductions} onChange={set("deductions")} placeholder="0" />
          </label>
        </div>
        <details>
          <summary className="small">System, wastage, method, remarks</summary>
          <label className="field">
            <span>System</span>
            <select className="tap-input" value={f.system_id} onChange={set("system_id")}>
              <option value="">{systemName(type?.default_system_id) ? `Area type default: ${systemName(type?.default_system_id)}` : "None yet"}</option>
              {lookups.systems.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
          <div className="row-2">
            <label className="field">
              <span>Wastage % (this area)</span>
              <input className="tap-input" type="number" step="any" min="0" value={f.wastage} onChange={set("wastage")} placeholder="from the type / system" />
            </label>
            <label className="field">
              <span>Measured by</span>
              <select className="tap-input" value={f.method} onChange={set("method")}>
                <option value="laser">Laser meter</option>
                <option value="manual">Tape / by hand</option>
                <option value="cad">Drawing (CAD)</option>
                <option value="label">Label / client figure</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>Remarks</span>
            <textarea rows={2} value={f.remarks} onChange={set("remarks")} />
          </label>
        </details>
        <div className="form-actions">
          {!area && (
            <button type="button" className="btn tap-wide" onClick={() => void save(true)}>
              Save and add next
            </button>
          )}
          <button className="btn btn-primary tap-wide">Save</button>
        </div>
      </form>
    </Modal>
  );
}

function RepeatDialog({ area, onClose, onDone }: { area: Area; onClose: () => void; onDone: (s: Survey) => void }) {
  const [from, setFrom] = useState("2");
  const [to, setTo] = useState("14");
  const [label, setLabel] = useState("Floor {n}");
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title={`Repeat ${area.name} on typical floors`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void api<Survey>(`/api/surveys/areas/${area.id}/repeat`, { method: "POST", json: { floor_from: Number(from), floor_to: Number(to), label } }).then(onDone, (err) =>
            setError(errorText(err)),
          );
        }}
      >
        {error && <div className="alert alert-error">{error}</div>}
        <div className="row-2">
          <label className="field">
            <span>From floor</span>
            <input className="tap-input" type="number" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="field">
            <span>To floor</span>
            <input className="tap-input" type="number" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>
        <label className="field">
          <span>Floor name ({"{n}"} = the floor number)</span>
          <input className="tap-input" value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <p className="small muted">Each copy keeps the size and count; on a site it goes on that tower's floor of the same name.</p>
        <div className="form-actions">
          <button className="btn btn-primary tap-wide">Repeat</button>
        </div>
      </form>
    </Modal>
  );
}

// --- products and outputs ------------------------------------------------------------------------

type ProductRow = {
  product_id: number;
  code: string;
  name: string;
  unit: string;
  qty: string;
  pack_size: string | null;
  pack_unit: string | null;
  packs: number | null;
  pack_qty: string | null;
  spare_qty: string | null;
};
type ConsumptionOut = {
  products: ProductRow[];
  by_floor: { key: string; products: { product_id: number; name: string; unit: string; qty: string }[] }[];
  no_system: { id: number; name: string; floor: string | null }[];
  no_system_count: number;
};

function Products({ survey }: { survey: Survey }) {
  const [c, setC] = useState<ConsumptionOut | null>(null);
  useEffect(() => {
    api<ConsumptionOut>(`/api/surveys/${survey.id}/consumption`).then(setC, () => setC(null));
  }, [survey]);
  if (!c) return <p className="muted">Working out quantities…</p>;
  return (
    <div className="products-view">
      {c.no_system_count > 0 && (
        <div className="alert alert-warn">
          {c.no_system_count} area(s) have no system yet and are not counted:{" "}
          {c.no_system
            .slice(0, 6)
            .map((a) => a.name)
            .join(", ")}
          {c.no_system_count > 6 ? " …" : ""}
        </div>
      )}
      <div className="card">
        <h2 className="section-title">Whole survey</h2>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Quantity</th>
                <th className="num">Packs</th>
              </tr>
            </thead>
            <tbody>
              {c.products.map((p) => (
                <tr key={p.product_id}>
                  <td>{p.name}</td>
                  <td className="num">
                    {Number(p.qty).toFixed(2)} {p.unit}
                  </td>
                  <td className="num">
                    {p.packs !== null ? (
                      <>
                        <b>
                          {p.packs} {p.pack_unit ?? "pack"}
                          {p.packs === 1 ? "" : "s"}
                        </b>{" "}
                        <span className="muted small">
                          of {Number(p.pack_size)} {p.unit} ({Number(p.spare_qty).toFixed(2)} {p.unit} spare)
                        </span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
              {c.products.length === 0 && (
                <tr>
                  <td colSpan={3} className="empty">
                    No quantities: pick a system for the areas (or a default system on their area type).
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="small muted">Whole packs only on this total, never per area or floor.</p>
      </div>
      <h2 className="section-title top-gap">By floor</h2>
      <div className="floor-grid">
        {c.by_floor.map((f) => (
          <div key={f.key} className="card">
            <strong>{f.key}</strong>
            <table className="table compact">
              <tbody>
                {f.products.map((p) => (
                  <tr key={p.product_id}>
                    <td>{p.name}</td>
                    <td className="num">
                      {Number(p.qty).toFixed(2)} {p.unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

function Outputs({ survey, onError }: { survey: Survey; onError: (e: string) => void }) {
  const { can } = useAuth();
  const [split, setSplit] = useState(false);
  const [tender, setTender] = useState("");
  const [floors, setFloors] = useState<string[]>([]);
  const [rates, setRates] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const floorKeys = groupAreas(survey.areas).map(([k]) => k.replace(" · ", " "));
  const [notReady, setNotReady] = useState(false);
  const [fronts, setFronts] = useState<Record<string, { areas: number; ready_areas: number }>>({});
  useEffect(() => {
    void api<{ floors: { key: string; areas: number; ready_areas: number }[] }>(`/api/surveys/${survey.id}/fronts`).then(
      (r) => setFronts(Object.fromEntries(r.floors.map((f) => [f.key, f]))),
      () => setFronts({}),
    );
  }, [survey.id]);
  async function boq() {
    try {
      const r = await api<{ tender_id: number; tender_code: string; lines: number; suggested: number }>(`/api/surveys/${survey.id}/boq`, {
        method: "POST",
        json: { tender_id: tender ? Number(tender) : null, split_by_area_type: split },
      });
      setMsg(`${r.lines} BOQ line(s) added to ${r.tender_code}; ${r.suggested} priced by Suggest.`);
    } catch (err) {
      onError(errorText(err));
    }
  }
  async function indent() {
    try {
      const r = await api<{ indent_id: number; code: string; lines: number }>(`/api/surveys/${survey.id}/indent`, {
        method: "POST",
        json: { floors: floors.length ? floors : null, include_not_ready: notReady },
      });
      setMsg(`Draft indent ${r.code} with ${r.lines} product(s).`);
    } catch (err) {
      onError(errorText(err));
    }
  }
  return (
    <div className="outputs">
      {msg && <div className="alert alert-ok">{msg}</div>}
      {can("tender.edit") && (
        <div className="card">
          <h2 className="section-title">Tender BOQ</h2>
          <p className="small muted">One line per system with the summed treated area (sqm), priced by the tender's Suggest. Lines remember the areas they came from.</p>
          <div className="inline-form">
            <input
              className="tap-input"
              placeholder={survey.tender_id ? "this survey's tender" : "Tender id (when not linked)"}
              value={tender}
              onChange={(e) => setTender(e.target.value)}
            />
            <label className="check">
              <input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} /> Split by area type
            </label>
            <button className="btn btn-primary" onClick={() => void boq()}>
              Create BOQ lines
            </button>
          </div>
        </div>
      )}
      {can("indent.create") && (
        <div className="card top-gap">
          <h2 className="section-title">Material indent</h2>
          <p className="small muted">Only places the supervisor marked “work front ready” are ordered, so a block that is not open yet is not ordered early.</p>
          <label className="check">
            <input type="checkbox" checked={notReady} onChange={(e) => setNotReady(e.target.checked)} /> Show not ready (planning: order ahead)
          </label>
          <div className="checks">
            {floorKeys
              .filter((k) => notReady || (fronts[k]?.ready_areas ?? 0) > 0)
              .map((k) => (
                <label key={k} className="check">
                  <input type="checkbox" checked={floors.includes(k)} onChange={(e) => setFloors(e.target.checked ? [...floors, k] : floors.filter((x) => x !== k))} /> {k}{" "}
                  <span className={`badge ${(fronts[k]?.ready_areas ?? 0) > 0 ? "badge-ok" : "badge-muted"}`}>
                    {fronts[k]?.ready_areas ?? 0}/{fronts[k]?.areas ?? 0} ready
                  </span>
                </label>
              ))}
            {!notReady && floorKeys.every((k) => (fronts[k]?.ready_areas ?? 0) === 0) && <p className="muted small">No work front is ready yet.</p>}
          </div>
          <button className="btn btn-primary top-gap" onClick={() => void indent()}>
            Create indent draft {floors.length ? `(${floors.length} floor${floors.length > 1 ? "s" : ""})` : "(all floors)"}
          </button>
        </div>
      )}
      <div className="card top-gap">
        <h2 className="section-title">Reports</h2>
        <div className="inline-form">
          {can("tender.margin") && (
            <label className="check">
              <input type="checkbox" checked={rates} onChange={(e) => setRates(e.target.checked)} /> Include rates
            </label>
          )}
          <button className="btn" onClick={() => void downloadFile(`/api/surveys/${survey.id}/pdf${rates ? "?include_rates=true" : ""}`).catch((e) => onError(errorText(e)))}>
            ⤓ Survey PDF
          </button>
          <button className="btn" onClick={() => void downloadFile(`/api/surveys/${survey.id}/xlsx`).catch((e) => onError(errorText(e)))}>
            ⤓ Excel
          </button>
        </div>
      </div>
    </div>
  );
}

// --- pilot report and settings -------------------------------------------------------------------

export function PilotReport() {
  const [d, setD] = useState<{
    rows: { survey: string; area_id: number; area: string; mode: string; camera_sqm: string; laser_sqm: string; difference_percent: string }[];
    summary: { mode: string; areas: number; average_percent: string; worst_percent: string }[];
    limit_percent: string;
  } | null>(null);
  useEffect(() => {
    api<typeof d>("/api/surveys/pilot").then(setD, () => setD(null));
  }, []);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Camera pilot</h1>
          <p className="muted small">
            Every area measured both by the camera and by laser / hand. Flagged above {d?.limit_percent ?? 3}%. Measure 10 rooms both ways before trusting the camera.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-small" onClick={() => void downloadFile("/api/surveys/pilot?format=xlsx")}>
            ⤓ Excel
          </button>
        </div>
      </div>
      <div className="kpi-grid">
        {(d?.summary ?? []).map((s) => (
          <div key={s.mode} className="kpi">
            <div className="kpi-link">
              <span className="kpi-label">
                {s.mode === "ar" ? "AR measure" : "Marker photo"} · {s.areas} areas
              </span>
              <span className="kpi-value">{s.average_percent}% avg</span>
              <span className="muted small">worst {s.worst_percent}%</span>
            </div>
          </div>
        ))}
      </div>
      <div className="table-wrap top-gap">
        <table className="table">
          <thead>
            <tr>
              <th>Survey</th>
              <th>Area</th>
              <th>Mode</th>
              <th className="num">Camera sqm</th>
              <th className="num">Laser sqm</th>
              <th className="num">Difference</th>
            </tr>
          </thead>
          <tbody>
            {(d?.rows ?? []).map((r) => (
              <tr key={r.area_id} className={Math.abs(Number(r.difference_percent)) > Number(d?.limit_percent ?? 3) ? "sev-high" : undefined}>
                <td>{r.survey}</td>
                <td>{r.area}</td>
                <td>{r.mode}</td>
                <td className="num">{Number(r.camera_sqm).toFixed(2)}</td>
                <td className="num">{Number(r.laser_sqm).toFixed(2)}</td>
                <td className="num">{r.difference_percent}%</td>
              </tr>
            ))}
            {d && d.rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No area has both a camera and a laser size yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Settings = {
  photo_required: boolean;
  camera_billing_allowed: boolean;
  mismatch_percent: string;
  ai_enabled: boolean;
  ai_model: string;
  ai_monthly_cap_inr: string;
  ai_usd_per_mtok_in: string;
  ai_usd_per_mtok_out: string;
  ai_inr_per_usd: string;
  ai_key_present: boolean;
  ai_month_spend_inr: string;
};

export function SurveySettings() {
  const [s, setS] = useState<Settings | null>(null);
  const [types, setTypes] = useState<AreaType[]>([]);
  const [systems, setSystems] = useState<{ id: number; name: string }[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Settings>("/api/surveys/settings").then(setS, (e) => setError(errorText(e)));
    api<AreaType[]>("/api/surveys/area-types").then(setTypes, () => setTypes([]));
    api<Lookups>("/api/surveys/lookups").then(
      (l) => setSystems(l.systems),
      () => setSystems([]),
    );
  }, []);
  useEffect(load, [load]);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!s) return;
    try {
      setS(await api<Settings>("/api/surveys/settings", { method: "PUT", json: s }));
      setMsg("Saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function saveType(t: AreaType) {
    try {
      await api(`/api/surveys/area-types/${t.id}`, { method: "PUT", json: t });
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  if (!s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <h1>Site survey</h1>
      {msg && <div className="alert alert-ok">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      <form className="card" onSubmit={save}>
        <label className="check">
          <input type="checkbox" checked={s.photo_required} onChange={(e) => setS({ ...s, photo_required: e.target.checked })} /> Every area needs a photo before the survey can be
          submitted
        </label>
        <label className="check">
          <input type="checkbox" checked={s.camera_billing_allowed} onChange={(e) => setS({ ...s, camera_billing_allowed: e.target.checked })} /> Camera sizes allowed for billing
          (off: RA bill quantities from camera-only areas need a laser / manual size or the client's certification)
        </label>
        <label className="field">
          <span>Flag camera vs laser differences above (%)</span>
          <input type="number" step="0.1" min="0" value={s.mismatch_percent} onChange={(e) => setS({ ...s, mismatch_percent: e.target.value })} />
        </label>
        <h2 className="section-title top-gap">AI suggestion from the photo</h2>
        {!s.ai_key_present && <p className="small muted">No ANTHROPIC_API_KEY in .env: the Suggest button stays hidden whatever is set here.</p>}
        <label className="check">
          <input type="checkbox" checked={s.ai_enabled} onChange={(e) => setS({ ...s, ai_enabled: e.target.checked })} /> On (management approval needed)
        </label>
        <div className="inline-form">
          <label className="field">
            <span>Model</span>
            <input value={s.ai_model} onChange={(e) => setS({ ...s, ai_model: e.target.value })} />
          </label>
          <label className="field">
            <span>Monthly cap (₹)</span>
            <input type="number" min="0" value={s.ai_monthly_cap_inr} onChange={(e) => setS({ ...s, ai_monthly_cap_inr: e.target.value })} />
          </label>
        </div>
        <p className="small muted">Spent this month: ₹{Number(s.ai_month_spend_inr).toFixed(2)}</p>
        <button className="btn btn-primary">Save settings</button>
      </form>
      <h2 className="section-title top-gap">Area types</h2>
      <p className="small muted">Seeded defaults are "to be confirmed by the team": tick Confirmed once agreed.</p>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Area type</th>
              <th>Default system</th>
              <th className="num">Upturn mm</th>
              <th className="num">Wastage %</th>
              <th>Walls</th>
              <th>Sunk</th>
              <th>Confirmed</th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.id}>
                <td>
                  {t.name}
                  {!t.confirmed && <div className="small text-warn">to be confirmed by the team</div>}
                </td>
                <td>
                  <select value={t.default_system_id ?? ""} onChange={(e) => void saveType({ ...t, default_system_id: e.target.value ? Number(e.target.value) : null })}>
                    <option value="">—</option>
                    {systems.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="num">
                  <input
                    className="input-num"
                    type="number"
                    min="0"
                    defaultValue={Number(t.default_upturn_mm)}
                    onBlur={(e) => void saveType({ ...t, default_upturn_mm: e.target.value })}
                  />
                </td>
                <td className="num">
                  <input
                    className="input-num"
                    type="number"
                    min="0"
                    defaultValue={t.default_wastage_percent ?? ""}
                    placeholder="system"
                    onBlur={(e) => void saveType({ ...t, default_wastage_percent: e.target.value === "" ? null : e.target.value })}
                  />
                </td>
                <td>
                  <input type="checkbox" checked={t.includes_walls} onChange={(e) => void saveType({ ...t, includes_walls: e.target.checked })} />
                </td>
                <td>
                  <input type="checkbox" checked={t.needs_sunk_depth} onChange={(e) => void saveType({ ...t, needs_sunk_depth: e.target.checked })} />
                </td>
                <td>
                  <input type="checkbox" checked={t.confirmed} onChange={(e) => void saveType({ ...t, confirmed: e.target.checked })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
