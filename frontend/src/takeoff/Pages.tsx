// AutoCAD takeoff: the site's DWG drawings read in the app, shown with pan, zoom, layers and a
// text search; the areas found on them (room labels with sizes, waterproofing notes), traced with
// snapping, mapped to the site's places and accepted into the survey and the measurement book.
// For a 1600 px screen and a tablet (not a phone).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ReadProgress } from "./ReadProgress";
import { decodeGeometry, useGlPlan } from "./glplan";
import type { Geo as PlanGeo, GeoV2 } from "./glplan";
import { useAuth } from "../auth";
import { errorText, num } from "../format";
import { ART } from "../ui/tokens";
import { Button, Card, Field } from "../ui/components";

type Layer = { name: string; count: number; color: number; off: boolean; frozen: boolean; role: string | null };
type CadFile = {
  id: number;
  revision_id: number;
  drawing: string;
  rev: string;
  filename: string;
  status: "queued" | "reading" | "ready" | "failed";
  error: string | null;
  progress: string | null;
  progress_at: string | null;
  version: string | null;
  units_code: number | null;
  unit_name: string | null;
  unit_m: number | null;
  architect: string | null;
  layers: Layer[];
  counts: Record<string, number>;
  texts: number | null;
  dimensions: number | null;
  inserts: number | null;
  layouts: string[];
  size_labels: number | null;
  waterproofing_notes: number | null;
  candidates: number | null;
  loose_notes: { text: string; x: number; y: number }[];
  // the counts two ways: every text read (blocks and attributes too) and the mapped layers only
  count_sets?: {
    all: { texts: number; text_entities: number; size_labels: number; notes: number };
    mapped: { texts: number; size_labels: number; notes: number; hidden_layers: number };
  } | null;
  plan_titles?: string[];
  sheet_unknown?: number | null;
  sheet_guessed?: number | null;
  warnings: number;
  dxf_repairs?: number;
  changes?: {
    previous: number | null;
    added: Brief[];
    removed: Brief[];
    resized: (Brief & { previous_area_sqm: string })[];
  } | null;
};
type Brief = { id: number; name: string; plan: string | null; size: string | null; label_area_sqm: string | null };
type Area = {
  id: number;
  name: string;
  size_text: string | null;
  size_kind: string | null;
  label_area_sqm: string | null;
  label_w_m: string | null;
  label_l_m: string | null;
  x: number;
  y: number;
  plan: string | null;
  plan_guessed?: boolean;
  notes: { text: string; distance_m?: number }[];
  sunk_m: string | null;
  raise_m: string | null;
  outline: number[][] | null;
  traced_area_sqm: string | null;
  traced_perimeter_m: string | null;
  side_wall_sqm: string | null;
  label_trace_diff_percent: number | null;
  label_trace_flagged: boolean;
  area_sqm: string | null;
  node_id: number | null;
  place: string | null;
  area_type_id: number | null;
  area_type: string | null;
  system: string | null;
  status: "candidate" | "mapped" | "accepted" | "ignored";
  copied_from_id: number | null;
  floor_label: string | null;
  change: string | null;
  survey_area_id: number | null;
  measurement_id: number | null;
  side_measurement_id: number | null;
  accepted_by: string | null;
  survey_check: { survey_sqm: string; autocad_sqm: string; diff_percent: string; flagged: boolean; methods: string[] } | null;
  group_ids?: number[]; // the same name without a size, found again on this sheet
  count?: number;
};
type Geo = PlanGeo;
type DrawingRow = { drawing_id: number; title: string; revisions: { revision_id: number; rev: string; filename: string; file: CadFile | null }[] };
type SiteNode = { id: number; parent_id: number | null; kind: string; name: string; path: string };

// AutoCAD colour index, the common ones; the rest drawn in grey
const ACI: Record<number, string> = { 1: ART.aci1, 2: ART.aci2, 3: ART.aci3, 4: ART.aci4, 5: ART.aci5, 6: ART.aci6, 7: ART.aci7, 8: ART.aci8, 9: ART.aci9 };
const ROLES = ["walls", "rooms", "dimensions", "text", "hide"];

export function TakeoffPage() {
  const { id } = useParams();
  const siteId = Number(id);
  const { can } = useAuth();
  const canEdit = can("takeoff.edit");
  const [params, setParams] = useSearchParams();
  const [drawings, setDrawings] = useState<DrawingRow[] | null>(null);
  const [error, setError] = useState("");
  const fileId = params.get("file") ? Number(params.get("file")) : null;
  const tab = params.get("tab") ?? "areas";
  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v === null) next.delete(k);
    else next.set(k, v);
    setParams(next, { replace: true });
  };
  const loadDrawings = useCallback(() => api<DrawingRow[]>(`/api/takeoff/sites/${siteId}/drawings`).then(setDrawings, (e) => setError(errorText(e))), [siteId]);
  useEffect(() => {
    void loadDrawings();
  }, [loadDrawings]);
  // the first read file when none is chosen
  useEffect(() => {
    if (fileId || !drawings) return;
    for (const d of drawings) for (const r of d.revisions) if (r.file?.status === "ready") return setParam("file", String(r.file.id));
  }, [drawings, fileId]); // eslint-disable-line react-hooks/exhaustive-deps
  // a new read of the open file starts its workspace again (it shows the read's progress)
  const [reads, setReads] = useState(0);
  async function read(revisionId: number) {
    const architect = window.prompt("Architect (their layer mapping is saved and reused)", "") ?? "";
    try {
      const f = await api<CadFile>(`/api/takeoff/revisions/${revisionId}/read`, { method: "POST", json: { architect: architect || null } });
      setReads((n) => n + 1);
      setParam("file", String(f.id));
      void loadDrawings();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <div className="takeoff">
      <p className="breadcrumb">
        <Link to="/sites">Sites</Link> / <Link to={`/sites/${siteId}`}>Site</Link> / AutoCAD takeoff
      </p>
      <div className="page-header">
        <h1>AutoCAD takeoff</h1>
        <p className="small muted">
          Room labels with sizes and waterproofing notes are read from the drawing; trace what has no label, map each area to the site and accept it into the survey and the
          measurement book. Walls in these drawings are loose lines, so no outline is drawn on its own.
        </p>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="takeoff-files">
        {drawings?.length === 0 && (
          <p className="empty">
            No AutoCAD drawings on this site yet: add the .dwg (or .dxf) in the site's <Link to={`/sites/${siteId}?tab=drawings`}>Drawings</Link>.
          </p>
        )}
        {drawings?.map((d) =>
          d.revisions.map((r) => (
            <div key={r.revision_id} className={`takeoff-file ${r.file && r.file.id === fileId ? "active" : ""}`}>
              <b>
                {d.title} {r.rev}
              </b>
              <span className="small muted">{r.filename}</span>
              {r.file ? (
                <>
                  <span className={`badge ${r.file.status === "ready" ? "badge-ok" : r.file.status === "failed" ? "badge-danger" : "badge-warn"}`}>{r.file.status}</span>
                  {r.file.status === "ready" && (
                    <Button size="small" onClick={() => setParam("file", String(r.file!.id))}>
                      Open
                    </Button>
                  )}
                  {r.file.status === "failed" && <span className="small text-danger">{r.file.error}</span>}
                  {canEdit && r.file.status !== "reading" && r.file.status !== "queued" && (
                    <Button variant="ghost" size="small" onClick={() => void read(r.revision_id)}>
                      Read again
                    </Button>
                  )}
                </>
              ) : (
                canEdit && (
                  <Button variant="primary" size="small" onClick={() => void read(r.revision_id)}>
                    Read the drawing
                  </Button>
                )
              )}
            </div>
          )),
        )}
      </div>
      {fileId && (
        <Workspace
          key={`${fileId}-${reads}`}
          fileId={fileId}
          siteId={siteId}
          tab={tab}
          setTab={(t) => setParam("tab", t)}
          onError={setError}
          areaParam={params.get("area")}
          setArea={(a) => setParam("area", a)}
          reloadList={loadDrawings}
        />
      )}
    </div>
  );
}

function Workspace({
  fileId,
  siteId,
  tab,
  setTab,
  onError,
  areaParam,
  setArea,
  reloadList,
}: {
  fileId: number;
  siteId: number;
  tab: string;
  setTab: (t: string) => void;
  onError: (e: string) => void;
  areaParam: string | null;
  setArea: (a: string | null) => void;
  reloadList: () => void;
}) {
  const { can } = useAuth();
  const canEdit = can("takeoff.edit");
  const [file, setFile] = useState<CadFile | null>(null);
  const [geo, setGeo] = useState<Geo | null>(null);
  const [areas, setAreas] = useState<Area[]>([]);
  const [show, setShow] = useState("waterproofing");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const [trace, setTrace] = useState<{ areaId: number | null; points: [number, number][]; snaps: string[] } | null>(null);
  const [proposed, setProposed] = useState<[number, number][] | null>(null);
  const [nodes, setNodes] = useState<SiteNode[]>([]);
  const [types, setTypes] = useState<{ id: number; name: string }[]>([]);
  const selected = areas.find((a) => String(a.id) === areaParam) ?? null;

  const loadFile = useCallback(() => api<CadFile>(`/api/takeoff/files/${fileId}`).then(setFile, (e) => onError(errorText(e))), [fileId, onError]);
  const loadAreas = useCallback(
    () =>
      api<{ areas: Area[] }>(`/api/takeoff/files/${fileId}/areas?show=${show}`).then(
        (r) => setAreas(r.areas),
        (e) => onError(errorText(e)),
      ),
    [fileId, show, onError],
  );
  useEffect(() => {
    void loadFile();
  }, [loadFile]);
  // poll while it is being read
  useEffect(() => {
    if (!file || (file.status !== "queued" && file.status !== "reading")) return;
    const t = setTimeout(() => {
      void loadFile();
      reloadList();
    }, 1500);
    return () => clearTimeout(t);
  }, [file, loadFile, reloadList]);
  useEffect(() => {
    if (file?.status !== "ready") return;
    void loadAreas();
    api<GeoV2 | Geo>(`/api/takeoff/files/${fileId}/geometry`).then(
      (raw) => {
        setGeo(decodeGeometry(raw));
        setHidden(new Set(file.layers.filter((l) => l.role === "hide" || l.off || l.frozen).map((l) => l.name)));
      },
      (e) => onError(errorText(e)),
    );
    api<SiteNode[]>(`/api/sites/${siteId}/nodes`).then(setNodes, () => setNodes([]));
    api<{ id: number; name: string }[]>("/api/takeoff/area-types").then(setTypes, () => setTypes([]));
  }, [file?.status, fileId, siteId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (selected) setFocus([selected.x, selected.y]);
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => {
    const q = search.trim().toUpperCase();
    if (!geo || q.length < 2) return [];
    return geo.texts.filter((t) => t[4].toUpperCase().includes(q)).slice(0, 40);
  }, [geo, search]);

  async function clickWorld(x: number, y: number, radius: number) {
    if (proposed) return;
    if (trace) {
      const prev = trace.points[trace.points.length - 1];
      try {
        const s = await api<{ x: number; y: number; kind: string }>(`/api/takeoff/files/${fileId}/snap`, { method: "POST", json: { x, y, radius, previous: prev ?? null } });
        setTrace({ ...trace, points: [...trace.points, [s.x, s.y]], snaps: [...trace.snaps, s.kind] });
      } catch (e) {
        onError(errorText(e));
      }
    }
  }
  async function proposeAt(x: number, y: number) {
    try {
      const r = await api<{ outline: number[][]; area_sqm: number }>(`/api/takeoff/files/${fileId}/propose`, { method: "POST", json: { x, y } });
      setProposed(r.outline.map((p) => [p[0], p[1]] as [number, number]));
    } catch (e) {
      onError(errorText(e));
    }
  }
  async function finishTrace(points: [number, number][]) {
    if (!trace) return;
    try {
      if (trace.areaId) {
        await api(`/api/takeoff/areas/${trace.areaId}/trace`, { method: "POST", json: { points } });
      } else {
        const name = window.prompt("Name of the area (for example TERRACE, LADIES TOILET)") ?? "";
        if (!name) return;
        const a = await api<Area>(`/api/takeoff/files/${fileId}/areas`, { method: "POST", json: { name, points } });
        setArea(String(a.id));
      }
      setTrace(null);
      setProposed(null);
      void loadAreas();
    } catch (e) {
      onError(errorText(e));
    }
  }
  async function saveArea(a: Area, patch: Record<string, unknown>) {
    try {
      await api(`/api/takeoff/areas/${a.id}`, { method: "PUT", json: patch });
      void loadAreas();
    } catch (e) {
      onError(errorText(e));
    }
  }
  async function accept(a: Area, book: boolean) {
    try {
      await api(`/api/takeoff/areas/${a.id}/accept`, { method: "POST", json: { survey: true, measurement_book: book } });
      void loadAreas();
    } catch (e) {
      onError(errorText(e));
    }
  }

  if (!file) return <p className="muted">Loading…</p>;
  if (file.status === "queued" || file.status === "reading") return <ReadProgress filename={file.filename} progress={file.progress} since={file.progress_at} />;
  if (file.status === "failed") return <div className="alert alert-error">{file.error}</div>;
  const traceOutline = trace ? trace.points : null;
  return (
    <div className="takeoff-work">
      <div className="takeoff-facts small">
        <b>
          {file.drawing} {file.rev}
        </b>{" "}
        · {file.version} · units <b>{file.unit_name}</b>
        {file.unit_m === null && <span className="text-danger"> (unitless: set the unit before tracing)</span>} · {file.layers.length} layers · {file.dimensions} dimensions
        {file.sheet_unknown ? <span className="text-warn"> · {file.sheet_unknown} areas on an unknown sheet</span> : null}
        {file.sheet_guessed ? <span className="text-warn"> · {file.sheet_guessed} sheets guessed (no frame): confirm them</span> : null}
        <CountSets file={file} />
        {file.architect && <> · layers of {file.architect}</>}
        {file.warnings > 0 && <span className="muted"> · {file.warnings} converter warnings</span>}
        {(file.dxf_repairs ?? 0) > 0 && <span className="muted"> · {file.dxf_repairs} broken text line(s) repaired in the DXF</span>}
      </div>
      <div className="takeoff-grid">
        <div className="takeoff-canvas-wrap">
          <div className="takeoff-toolbar">
            <Field label="Search the texts" bare>
              <input placeholder="Search the texts…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search the texts" />
            </Field>
            {canEdit && !trace && (
              <Button size="small" onClick={() => setTrace({ areaId: selected?.id ?? null, points: [], snaps: [] })}>
                {selected ? `Trace ${selected.name.slice(0, 24)}` : "Trace a new area"}
              </Button>
            )}
            {trace && (
              <>
                <span className="small">
                  Click the corners ({trace.points.length}){trace.snaps.length > 0 && ` · last snapped to ${trace.snaps[trace.snaps.length - 1]}`}; or click inside the room for an
                  outline from the walls:
                </span>
                <Button
                  size="small"
                  onClick={() => setTrace({ ...trace, points: trace.points.slice(0, -1), snaps: trace.snaps.slice(0, -1) })}
                  disabled={!trace.points.length}
                >
                  Undo corner
                </Button>
                <Button variant="primary" size="small" disabled={trace.points.length < 3} onClick={() => void finishTrace(trace.points)}>
                  Finish
                </Button>
                <Button variant="ghost" size="small" onClick={() => (setTrace(null), setProposed(null))}>
                  Cancel
                </Button>
              </>
            )}
            {proposed && (
              <>
                <Button variant="primary" size="small" onClick={() => void finishTrace(proposed)}>
                  Use this outline
                </Button>
                <Button
                  size="small"
                  onClick={() => (setTrace({ areaId: trace?.areaId ?? null, points: proposed, snaps: proposed.map(() => "wall") }), setProposed(null))}
                >
                  Correct its corners
                </Button>
              </>
            )}
          </div>
          {matches.length > 0 && (
            <ul className="takeoff-search">
              {matches.map((t, i) => (
                <li key={i}>
                  <button className="link-button" onClick={() => setFocus([t[0], t[1]])}>
                    {t[4].slice(0, 60)}
                  </button>{" "}
                  <span className="muted small">{t[3]}</span>
                </li>
              ))}
            </ul>
          )}
          {geo ? (
            <DrawingCanvas
              geo={geo}
              hidden={hidden}
              areas={areas}
              selected={selected}
              focus={focus}
              tracePoints={traceOutline}
              proposed={proposed}
              onClick={(x, y, r) => void clickWorld(x, y, r)}
              onDoubleClick={(x, y) => (trace ? void proposeAt(x, y) : undefined)}
              onPickArea={(a) => setArea(String(a.id))}
            />
          ) : (
            <p className="muted">Drawing the plan…</p>
          )}
        </div>
        <div className="takeoff-side">
          <div className="tabs tabs-inline">
            {[
              ["areas", `Areas (${areas.length})`],
              ["layers", "Layers"],
              ["changes", "Changes"],
              ["quantities", "Quantities"],
            ].map(([k, l]) => (
              <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {l}
              </button>
            ))}
          </div>
          {tab === "areas" && (
            <AreasPanel
              file={file}
              areas={areas}
              show={show}
              setShow={setShow}
              selected={selected}
              setArea={setArea}
              nodes={nodes}
              types={types}
              canEdit={canEdit}
              onSave={saveArea}
              onAccept={accept}
              onReload={loadAreas}
              onError={onError}
            />
          )}
          {tab === "layers" && geo && (
            <LayersPanel
              file={file}
              hidden={hidden}
              setHidden={setHidden}
              canEdit={canEdit}
              onSaved={() => {
                void loadFile();
                void loadAreas();
              }}
              onError={onError}
            />
          )}
          {tab === "changes" && <ChangesPanel file={file} />}
          {tab === "quantities" && <QuantitiesPanel siteId={siteId} />}
        </div>
      </div>
    </div>
  );
}

// --- the canvas -----------------------------------------------------------------------------------

function DrawingCanvas({
  geo,
  hidden,
  areas,
  selected,
  focus,
  tracePoints,
  proposed,
  onClick,
  onDoubleClick,
  onPickArea,
}: {
  geo: Geo;
  hidden: Set<string>;
  areas: Area[];
  selected: Area | null;
  focus: [number, number] | null;
  tracePoints: [number, number][] | null;
  proposed: [number, number][] | null;
  onClick: (x: number, y: number, radius: number) => void;
  onDoubleClick: (x: number, y: number) => void;
  onPickArea: (a: Area) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState(() => {
    const e = geo.extents ?? [0, 0, 1000, 1000];
    return { cx: (e[0] + e[2]) / 2, cy: (e[1] + e[3]) / 2, scale: 0 };
  });
  const glOk = useGlPlan(glRef, geo, view, hidden);
  const drag = useRef<{ x: number; y: number; cx: number; cy: number; moved: boolean } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<number | null>(null);

  // fit the drawing on first draw
  useEffect(() => {
    const c = ref.current;
    if (!c || view.scale) return;
    const e = geo.extents ?? [0, 0, 1000, 1000];
    const scale = Math.min(c.clientWidth / Math.max(1, e[2] - e[0]), c.clientHeight / Math.max(1, e[3] - e[1])) * 0.95;
    setView((v) => ({ ...v, scale }));
  }, [geo, view.scale]);
  // centre on a searched text or a picked area, zoomed in
  useEffect(() => {
    if (!focus || !ref.current) return;
    const unit = geo.unit_m ?? 0.001;
    const want = ref.current.clientWidth / (25 / unit); // about 25 m across
    setView({ cx: focus[0], cy: focus[1], scale: want });
  }, [focus, geo.unit_m]);

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
    const minX = cx - w / 2 / scale;
    const maxX = cx + w / 2 / scale;
    const minY = cy - h / 2 / scale;
    const maxY = cy + h / 2 / scale;
    const colors = new Map(geo.layers.map((l) => [l.name, l.color]));
    ctx.lineWidth = 1;
    if (!glOk.current) {
      ctx.fillStyle = ART.paper; // no WebGL here: the lines on this canvas
      ctx.fillRect(0, 0, w, h);
    }
    for (const [layer, g] of glOk.current ? [] : Object.entries(geo.geometry)) {
      if (hidden.has(layer)) continue;
      ctx.strokeStyle = ACI[Math.abs(colors.get(layer) ?? 7)] ?? ART.drawLine;
      ctx.beginPath();
      const s = g.s;
      for (let i = 0; i < s.length; i += 4) {
        const x1 = s[i],
          y1 = s[i + 1],
          x2 = s[i + 2],
          y2 = s[i + 3];
        if ((x1 < minX && x2 < minX) || (x1 > maxX && x2 > maxX) || (y1 < minY && y2 < minY) || (y1 > maxY && y2 > maxY)) continue;
        ctx.moveTo(X(x1), Y(y1));
        ctx.lineTo(X(x2), Y(y2));
      }
      ctx.stroke();
    }
    // texts when they are big enough to read
    ctx.fillStyle = ART.drawText;
    for (const [x, y, th, layer, text] of geo.texts) {
      if (hidden.has(layer) || x < minX || x > maxX || y < minY || y > maxY) continue;
      const px = (th || 0) * scale;
      if (px < 6) continue;
      ctx.font = `${Math.min(px, 28)}px sans-serif`;
      text.split("\n").forEach((ln, i) => ctx.fillText(ln, X(x), Y(y) + i * Math.min(px, 28) * 1.2));
    }
    // traced outlines and the areas' labels
    for (const a of areas) {
      const sel = selected?.id === a.id;
      if (a.outline && a.outline.length > 2) {
        ctx.beginPath();
        a.outline.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1]))));
        ctx.closePath();
        ctx.fillStyle = a.label_trace_flagged ? "rgba(214,39,40,0.18)" : a.status === "accepted" ? "rgba(15,107,92,0.22)" : "rgba(31,79,216,0.15)";
        ctx.fill();
        ctx.strokeStyle = sel ? ART.aci1 : ART.drawAccepted;
        ctx.lineWidth = sel ? 3 : 2;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
      ctx.beginPath();
      ctx.arc(X(a.x), Y(a.y), sel ? 7 : 5, 0, Math.PI * 2);
      ctx.fillStyle = a.status === "accepted" ? ART.drawAccepted : a.status === "mapped" ? ART.drawMapped : ART.drawOpen;
      ctx.fill();
    }
    const poly = (pts: [number, number][], color: string, closed: boolean) => {
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1]))));
      if (closed) ctx.closePath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.lineWidth = 1;
      for (const p of pts) {
        ctx.fillStyle = color;
        ctx.fillRect(X(p[0]) - 4, Y(p[1]) - 4, 8, 8);
      }
    };
    if (proposed) poly(proposed, ART.aci6, true);
    if (tracePoints && tracePoints.length) poly(tracePoints, ART.aci1, tracePoints.length > 2);
  }, [geo, hidden, areas, selected, view, tracePoints, proposed, glOk]);
  useEffect(() => {
    const id = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(id);
  }, [draw]);
  useEffect(() => {
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [draw]);

  const toWorld = (clientX: number, clientY: number) => {
    const r = ref.current!.getBoundingClientRect();
    return [(clientX - r.left - r.width / 2) / view.scale + view.cx, view.cy - (clientY - r.top - r.height / 2) / view.scale] as [number, number];
  };
  function down(e: ReactPointerEvent) {
    (e.target as Element).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = Math.hypot(a.x - b.x, a.y - b.y);
    }
    drag.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false };
  }
  function move(e: ReactPointerEvent) {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      setView((v) => ({ ...v, scale: v.scale * (d / pinch.current!) }));
      pinch.current = d;
      return;
    }
    const s = drag.current;
    if (!s) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) s.moved = true;
    if (s.moved) setView((v) => ({ ...v, cx: s.cx - dx / v.scale, cy: s.cy + dy / v.scale }));
  }
  function up(e: ReactPointerEvent) {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    const s = drag.current;
    drag.current = null;
    if (!s || s.moved) return;
    const [x, y] = toWorld(e.clientX, e.clientY);
    // a click on an area's marker picks it; otherwise it is a corner when tracing
    const hit = areas.find((a) => Math.hypot((a.x - x) * view.scale, (a.y - y) * view.scale) < 9);
    if (hit && !tracePoints) onPickArea(hit);
    else onClick(x, y, 12 / view.scale);
  }
  function wheel(e: ReactWheelEvent) {
    const [x, y] = toWorld(e.clientX, e.clientY);
    const f = e.deltaY < 0 ? 1.25 : 0.8;
    setView((v) => ({ scale: v.scale * f, cx: x - (x - v.cx) / f, cy: y - (y - v.cy) / f }));
  }
  return (
    <div className="takeoff-canvas">
      <canvas ref={glRef} className="plan-gl" aria-hidden="true" />
      <canvas
        ref={ref}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onWheel={wheel}
        onDoubleClick={(e) => onDoubleClick(...toWorld(e.clientX, e.clientY))}
        aria-label="The drawing"
      />
      <div className="takeoff-zoom">
        <Button size="small" onClick={() => setView((v) => ({ ...v, scale: v.scale * 1.5 }))} aria-label="Zoom in">
          +
        </Button>
        <Button size="small" onClick={() => setView((v) => ({ ...v, scale: v.scale / 1.5 }))} aria-label="Zoom out">
          −
        </Button>
        <Button size="small" onClick={() => setView((v) => ({ ...v, scale: 0 }))}>
          Fit
        </Button>
      </div>
    </div>
  );
}

// --- the areas ------------------------------------------------------------------------------------

/** The counts both ways, each with what it means, so they match what people compare them with. */
function CountSets({ file }: { file: CadFile }) {
  const c = file.count_sets;
  if (!c)
    return (
      <>
        {" "}
        · {file.texts} texts · {file.size_labels} size labels · {file.waterproofing_notes} waterproofing notes
      </>
    );
  return (
    <div className="count-sets">
      <div title="Every text read: texts and multi-line texts, the texts inside blocks and the block attributes, on every layer">
        <b>All texts:</b> {num(c.all.texts, 0)} ({num(c.all.text_entities, 0)} texts and multi-line texts in the drawing itself, the rest inside blocks or block attributes) ·{" "}
        {c.all.size_labels} size labels · {c.all.notes} waterproofing notes, on every layer
      </div>
      <div title="The texts on the layers shown by the layer mapping, outside blocks: what the area list is built from">
        <b>On the mapped layers:</b> {num(c.mapped.texts, 0)} texts · {c.mapped.size_labels} size labels · {c.mapped.notes} waterproofing notes
        {c.mapped.hidden_layers > 0 ? ` (${c.mapped.hidden_layers} layers hidden)` : " (no layer hidden yet)"}
      </div>
    </div>
  );
}

function AreasPanel({
  file,
  areas,
  show,
  setShow,
  selected,
  setArea,
  nodes,
  types,
  canEdit,
  onSave,
  onAccept,
  onReload,
  onError,
}: {
  file: CadFile;
  areas: Area[];
  show: string;
  setShow: (s: string) => void;
  selected: Area | null;
  setArea: (a: string | null) => void;
  nodes: SiteNode[];
  types: { id: number; name: string }[];
  canEdit: boolean;
  onSave: (a: Area, patch: Record<string, unknown>) => Promise<void>;
  onAccept: (a: Area, book: boolean) => Promise<void>;
  onReload: () => void;
  onError: (e: string) => void;
}) {
  const { can } = useAuth();
  const [copy, setCopy] = useState<{ source: string; targets: Set<string> } | null>(null);
  const floors = nodes.filter((n) => n.kind === "floor" || n.kind === "basement");
  // the area picked on the drawing: its row in view
  useEffect(() => {
    if (selected) document.getElementById(`area-row-${selected.id}`)?.scrollIntoView({ block: "center" });
  }, [selected]);
  async function doCopy() {
    if (!copy) return;
    const ids = areas
      .filter((a) => a.node_id && nodes.find((n) => n.id === a.node_id)?.path.startsWith(nodes.find((n) => String(n.id) === copy.source)?.path ?? "~"))
      .map((a) => a.id);
    try {
      await api(`/api/takeoff/files/${file.id}/copy-floors`, {
        method: "POST",
        json: { area_ids: ids, source_floor_id: Number(copy.source), target_floor_ids: [...copy.targets].map(Number) },
      });
      setCopy(null);
      onReload();
    } catch (e) {
      onError(errorText(e));
    }
  }
  return (
    <div className="takeoff-areas">
      <div className="form-row">
        <Field label="Show" bare>
          <select value={show} onChange={(e) => setShow(e.target.value)} aria-label="Show">
            <option value="waterproofing">Areas we waterproof</option>
            <option value="all">Every labelled area</option>
          </select>
        </Field>
        {canEdit && floors.length > 1 && (
          <Button size="small" onClick={() => setCopy({ source: String(floors[0].id), targets: new Set() })}>
            Same as a floor for other floors…
          </Button>
        )}
      </div>
      {copy && (
        <Card as="div" className="top-gap-small">
          <Field label="Same as">
            <select value={copy.source} onChange={(e) => setCopy({ ...copy, source: e.target.value })}>
              {floors.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.path}
                </option>
              ))}
            </select>
          </Field>
          <div className="small">for floors:</div>
          <div className="chip-list">
            {floors
              .filter((f) => String(f.id) !== copy.source)
              .map((f) => (
                <label key={f.id} className="chip">
                  <input
                    type="checkbox"
                    checked={copy.targets.has(String(f.id))}
                    onChange={(e) => {
                      const t = new Set(copy.targets);
                      if (e.target.checked) t.add(String(f.id));
                      else t.delete(String(f.id));
                      setCopy({ ...copy, targets: t });
                    }}
                  />{" "}
                  {f.name}
                </label>
              ))}
          </div>
          <Button variant="primary" size="small" disabled={!copy.targets.size} onClick={() => void doCopy()}>
            Copy the mapped areas
          </Button>{" "}
          <Button variant="ghost" size="small" onClick={() => setCopy(null)}>
            Cancel
          </Button>
        </Card>
      )}
      <table className="table compact takeoff-table">
        <thead>
          <tr>
            <th>Area</th>
            <th className="num">Label</th>
            <th className="num">Traced</th>
            <th>Place and type</th>
          </tr>
        </thead>
        <tbody>
          {areas.map((a) => (
            <tr
              key={a.id}
              id={`area-row-${a.id}`}
              className={`${selected?.id === a.id ? "row-selected" : ""} ${a.label_trace_flagged || a.survey_check?.flagged ? "row-warn" : ""}`}
              onClick={() => setArea(String(a.id))}
            >
              <td>
                <b>{a.name}</b>
                {a.floor_label && <span className="badge badge-muted"> {a.floor_label}</span>}
                {a.change && <span className="badge badge-warn"> {a.change}</span>}
                {a.plan && a.plan_guessed ? (
                  <div className="small" onClick={(e) => e.stopPropagation()}>
                    <span className="muted">{a.plan}</span> <span className="badge badge-warn">sheet guessed</span>{" "}
                    {canEdit && a.status !== "accepted" && (
                      <>
                        <Button variant="ghost" size="small" onClick={() => void onSave(a, { plan: a.plan })}>
                          Confirm
                        </Button>
                        <Field label="Sheet" bare>
                          <select value="" onChange={(e) => e.target.value && void onSave(a, { plan: e.target.value })} aria-label="Sheet">
                            <option value="">— another sheet —</option>
                            {(file.plan_titles ?? []).map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </>
                    )}
                  </div>
                ) : a.plan ? (
                  <div className="small muted">{a.plan}</div>
                ) : (
                  <div className="small" onClick={(e) => e.stopPropagation()}>
                    <span className="badge badge-warn">sheet unknown</span>{" "}
                    {canEdit && a.status !== "accepted" && (file.plan_titles ?? []).length > 0 && (
                      <Field label="Sheet" bare>
                        <select value="" onChange={(e) => e.target.value && void onSave(a, { plan: e.target.value })} aria-label="Sheet">
                          <option value="">— pick the sheet —</option>
                          {(file.plan_titles ?? []).map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </Field>
                    )}
                  </div>
                )}
                {(a.count ?? 1) > 1 && <div className="small muted">found {a.count} times on this sheet without a size</div>}
                {a.notes.map((n, i) => (
                  <div key={i} className="small note-tag">
                    {n.text}
                  </div>
                ))}
                {a.sunk_m && (
                  <div className="small">
                    sunk {num(Number(a.sunk_m) * 1000, 0)} mm{a.side_wall_sqm && <> · side walls {num(a.side_wall_sqm, 2)} sqm</>}
                  </div>
                )}
              </td>
              <td className="num">
                {a.size_text ? (
                  <>
                    <span className="small">{a.size_text}</span>
                    <div>{num(a.label_area_sqm, 2)} sqm</div>
                  </>
                ) : (
                  <span className="muted small">no size</span>
                )}
              </td>
              <td className="num">
                {a.traced_area_sqm ? (
                  <>
                    {num(a.traced_area_sqm, 2)} sqm
                    {a.label_trace_diff_percent !== null && (
                      <div className={`small ${a.label_trace_flagged ? "text-danger" : "muted"}`}>
                        {a.label_trace_diff_percent} % {a.label_trace_flagged ? "off the label: check" : "from the label"}
                      </div>
                    )}
                  </>
                ) : (
                  <span className="muted small">—</span>
                )}
                {a.survey_check && (
                  <div className={`small ${a.survey_check.flagged ? "text-danger" : "muted"}`}>
                    survey ({a.survey_check.methods.join(", ")}) {num(a.survey_check.survey_sqm, 2)} sqm: {a.survey_check.diff_percent} %
                  </div>
                )}
              </td>
              <td onClick={(e) => e.stopPropagation()}>
                {a.status === "accepted" ? (
                  <>
                    <span className="badge badge-ok">accepted</span>
                    <div className="small">{a.place}</div>
                    <div className="small muted">
                      {a.area_type}
                      {a.survey_area_id ? " · survey" : ""}
                      {a.measurement_id ? " · measurement book" : ""}
                    </div>
                  </>
                ) : (
                  <>
                    <Field label="Place" bare>
                      <select
                        value={a.node_id ?? ""}
                        disabled={!canEdit}
                        onChange={(e) => void onSave(a, { node_id: e.target.value ? Number(e.target.value) : null })}
                        aria-label="Place"
                      >
                        <option value="">— place on the site —</option>
                        {nodes.map((n) => (
                          <option key={n.id} value={n.id}>
                            {n.path}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Area type" bare>
                      <select
                        value={a.area_type_id ?? ""}
                        disabled={!canEdit}
                        onChange={(e) => void onSave(a, { area_type_id: e.target.value ? Number(e.target.value) : null })}
                        aria-label="Area type"
                      >
                        <option value="">— area type —</option>
                        {types.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    {canEdit && (
                      <div className="takeoff-actions">
                        <Button size="small" disabled={!a.node_id || !a.area_sqm} onClick={() => void onAccept(a, false)}>
                          To the survey
                        </Button>
                        {can("measurement.edit") && (
                          <Button variant="primary" size="small" disabled={!a.node_id || !a.area_sqm} onClick={() => void onAccept(a, true)}>
                            Survey + measurement book
                          </Button>
                        )}
                        <Button
                          variant="ghost" size="small"
                          onClick={async () => {
                            const patch = { status: a.status === "ignored" ? "candidate" : "ignored" };
                            for (const id of a.group_ids ?? [a.id]) await onSave({ ...a, id }, patch);
                          }}
                        >
                          {a.status === "ignored" ? "Bring back" : (a.count ?? 1) > 1 ? `Leave out all ${a.count}` : "Leave out"}
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {file.loose_notes.length > 0 && (
        <details className="top-gap-small">
          <summary className="small">{file.loose_notes.length} waterproofing notes not near any area</summary>
          <ul className="small">
            {file.loose_notes.slice(0, 50).map((n, i) => (
              <li key={i}>{n.text}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function LayersPanel({
  file,
  hidden,
  setHidden,
  canEdit,
  onSaved,
  onError,
}: {
  file: CadFile;
  hidden: Set<string>;
  setHidden: (h: Set<string>) => void;
  canEdit: boolean;
  onSaved: () => void;
  onError: (e: string) => void;
}) {
  const [architect, setArchitect] = useState(file.architect ?? "");
  const [roles, setRoles] = useState<Record<string, string>>(Object.fromEntries(file.layers.filter((l) => l.role).map((l) => [l.name, l.role!])));
  async function save() {
    try {
      await api(`/api/takeoff/files/${file.id}/layer-map`, { method: "PUT", json: { architect, roles } });
      onSaved();
    } catch (e) {
      onError(errorText(e));
    }
  }
  return (
    <div>
      <p className="small muted">Which layers are walls, rooms, dimensions, text, and which to hide (furniture, electrical, hatch): saved for the architect and reused.</p>
      <div className="form-row">
        <Field label="Architect" bare>
          <input value={architect} placeholder="Architect" onChange={(e) => setArchitect(e.target.value)} aria-label="Architect" />
        </Field>
        {canEdit && (
          <Button variant="primary" size="small" disabled={architect.trim().length < 2} onClick={() => void save()}>
            Save the mapping
          </Button>
        )}
      </div>
      <table className="table compact">
        <thead>
          <tr>
            <th>Show</th>
            <th>Layer</th>
            <th className="num">Entities</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {file.layers.map((l) => (
            <tr key={l.name}>
              <td>
                <input
                  type="checkbox"
                  checked={!hidden.has(l.name)}
                  onChange={(e) => {
                    const h = new Set(hidden);
                    if (e.target.checked) h.delete(l.name);
                    else h.add(l.name);
                    setHidden(h);
                  }}
                  aria-label={`Show ${l.name}`}
                />
              </td>
              <td>
                <span className="layer-swatch paint" style={{ "--swatch": ACI[Math.abs(l.color)] ?? ART.drawLine } as CSSProperties} /> {l.name}
              </td>
              <td className="num">{l.count}</td>
              <td>
                <Field label={`Role of ${l.name}`} bare>
                  <select value={roles[l.name] ?? ""} disabled={!canEdit} onChange={(e) => setRoles({ ...roles, [l.name]: e.target.value })} aria-label={`Role of ${l.name}`}>
                    <option value="">—</option>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </Field>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChangesPanel({ file }: { file: CadFile }) {
  const c = file.changes;
  if (!c || c.previous === null) return <p className="small muted">The first read revision of this drawing: nothing to compare with.</p>;
  return (
    <div className="small">
      <p>Against the last revision (its mapping is kept):</p>
      <h4>Added ({c.added.length})</h4>
      <ul>
        {c.added.map((a) => (
          <li key={a.id}>
            {a.name} {a.size} <span className="muted">{a.plan}</span>
          </li>
        ))}
      </ul>
      <h4>Resized ({c.resized.length})</h4>
      <ul>
        {c.resized.map((a) => (
          <li key={a.id}>
            {a.name}: {num(a.previous_area_sqm, 2)} → {num(a.label_area_sqm, 2)} sqm <span className="muted">{a.plan}</span>
          </li>
        ))}
      </ul>
      <h4>Removed ({c.removed.length})</h4>
      <ul>
        {c.removed.map((a) => (
          <li key={a.id}>
            {a.name} {a.size} <span className="muted">{a.plan}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function QuantitiesPanel({ siteId }: { siteId: number }) {
  const [q, setQ] = useState<{
    by_floor: { name: string; sqm: string }[];
    by_system: { name: string; sqm: string }[];
    by_area_type: { name: string; sqm: string }[];
    areas: number;
  } | null>(null);
  useEffect(() => {
    api<typeof q>(`/api/takeoff/sites/${siteId}/quantities`).then(setQ, () => setQ(null));
  }, [siteId]);
  if (!q) return <p className="muted">Loading…</p>;
  const block = (title: string, rows: { name: string; sqm: string }[]) => (
    <>
      <h4>{title}</h4>
      <table className="table compact">
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td className="num">{num(r.sqm, 2)} sqm</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
  return (
    <div>
      <p className="small muted">{q.areas} accepted AutoCAD areas: they feed the survey's material, the material plan (places without a BOQ item) and the 3D view.</p>
      {block("Per floor", q.by_floor)}
      {block("Per system", q.by_system)}
      {block("Per area type", q.by_area_type)}
    </div>
  );
}
