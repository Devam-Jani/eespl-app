import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api, ApiError, fetchObjectUrl } from "../../api";
import { useAuth } from "../../auth";
import { errorText } from "../../format";
import type { Site, SiteTask } from "../../types";
import { shortDate } from "../Tenders";
import { CATEGORY_LABEL, LATE_COLOR, legendCounts, realisticColor, STATUS_COLORS, workColor } from "./three/colors";
import type { Category, NodeStatus } from "./three/colors";
import { layout } from "./three/layout";
import { composeSnapshot } from "./three/snapshot";
import type { SnapLabel } from "./three/snapshot";
import type { Box, LayoutNode } from "./three/layout";
import { TaskDialog } from "./TasksTab";

type ModelNode = LayoutNode & { status: NodeStatus };
type Model = { site_id: number; version: string; site_progress: number; nodes: ModelNode[]; templates?: { id: number; name: string }[] };
/** Client portal: the model comes from the portal API, read-only (no task panel). */
export type PortalMode = { modelPath: string; headers?: Record<string, string> };
type Hover = { x: number; y: number; node: ModelNode } | null;
type SurveyMap = {
  nodes: Record<string, "measured" | "camera">;
  products: Record<string, { product_id: number; name: string; unit: string; qty: number }[]>;
  unplaced_areas: number;
  ready?: number[];
};
const SURVEY_COLORS = { measured: "#009E73", camera: "#E69F00", none: "#d9dedb" } as const;
const READY_COLOR = "#0072B2"; // "work front ready": a blue outline in the survey mode
const SURVEY_LEGEND = [
  { key: "measured", label: "Measured (laser / by hand)" },
  { key: "camera", label: "Camera only" },
  { key: "none", label: "Not measured" },
] as const;

const POLL_MS = 60_000;
const GROUP_KINDS = new Set(["tower", "wing", "floor", "basement"]);
const CATEGORIES: Exclude<Category, "rollup">[] = ["done", "progress", "hold", "blocked", "not_started", "none"];

/** The 3D tab: the site's block model coloured by work status (or realistic tones). */
export default function Site3DTab({
  site,
  onChange,
  onOpenStructure,
  portal,
}: {
  site: Pick<Site, "id" | "code" | "name" | "progress_percent">;
  onChange: () => void;
  onOpenStructure?: () => void;
  portal?: PortalMode;
}) {
  const { can } = useAuth();
  const canUpdate = can("site.update", "site.edit");
  const canEdit = can("site.edit");
  const [model, setModel] = useState<Model | null>(null);
  const [mode, setMode] = useState<"work" | "real" | "survey">("work");
  const [surveyMap, setSurveyMap] = useState<SurveyMap | null>(null);
  const canSurvey = !portal && can("survey.view");
  const [cutaway, setCutaway] = useState<number | null>(null);
  const [maxLevel, setMaxLevel] = useState<number | null>(null);
  const [below, setBelow] = useState(false);
  const [templateFilter, setTemplateFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [templates, setTemplates] = useState<{ id: number; name: string }[]>([]);
  const [hover, setHover] = useState<Hover>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mount = useRef<HTMLDivElement>(null);
  const labelsEl = useRef<HTMLDivElement>(null);
  const three = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    content: THREE.Group;
    ground: THREE.Mesh;
    pickables: { mesh: THREE.InstancedMesh; boxes: Box[] }[];
    labels: { el: HTMLDivElement; pos: THREE.Vector3 }[];
    render: () => void;
  } | null>(null);
  const framed = useRef(false);

  // --- data ---

  const load = useCallback(
    async (version?: string) => {
      try {
        const next = portal
          ? await api<Model>(portal.modelPath, { headers: portal.headers })
          : await api<Model>(`/api/sites/${site.id}/model`, version ? { headers: { "If-None-Match": `"${version}"` } } : {});
        setModel((m) => (m && m.version === next.version ? m : next));
        if (next.templates) setTemplates(next.templates);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 304)) setError(errorText(err));
      }
    },
    [site.id, portal],
  );

  useEffect(() => {
    void load();
    if (!portal) api<{ id: number; name: string }[]>("/api/stage-templates").then(setTemplates, () => setTemplates([]));
  }, [load, portal]);

  useEffect(() => {
    if (mode !== "survey" || !canSurvey) return;
    api<SurveyMap>(`/api/surveys/site-map/${site.id}`).then(setSurveyMap, (err) => setError(errorText(err)));
  }, [mode, canSurvey, site.id]);

  useEffect(() => {
    const t = setInterval(() => void load(model?.version), POLL_MS);
    return () => clearInterval(t);
  }, [load, model?.version]);

  const nodes = useMemo(() => model?.nodes ?? [], [model]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const boxes = useMemo(() => layout(nodes), [nodes]);
  const workBelow = useMemo(() => {
    const kids = new Map<number | null, ModelNode[]>();
    for (const n of nodes) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n]);
    const memo = new Map<number, boolean>();
    const walk = (n: ModelNode): boolean => {
      if (memo.has(n.id)) return memo.get(n.id)!;
      const v = n.status.has_scope || (kids.get(n.id) ?? []).some(walk);
      memo.set(n.id, v);
      return v;
    };
    nodes.forEach(walk);
    return memo;
  }, [nodes]);
  const lateBelow = useMemo(() => {
    const out = new Set<number>();
    for (const n of nodes) {
      if (!n.status.is_late) continue;
      for (let p: ModelNode | undefined = n; p; p = p.parent_id !== null ? byId.get(p.parent_id) : undefined) out.add(p.id);
    }
    return out;
  }, [nodes, byId]);
  const levels = useMemo(() => [...new Set(boxes.filter((b) => b.role === "floor").map((b) => b.level!))].sort((a, b) => a - b), [boxes]);
  const usedTemplates = useMemo(() => {
    const ids = new Set(nodes.flatMap((n) => n.status.template_ids));
    return templates.filter((t) => ids.has(t.id));
  }, [nodes, templates]);
  // places that carry work themselves or hold nothing else (a flat is counted through its rooms)
  const legend = useMemo(() => {
    const parents = new Set(nodes.map((n) => n.parent_id));
    return legendCounts(nodes.map((n) => ({ status: n.status, countable: !GROUP_KINDS.has(n.kind) && (n.status.has_scope || !parents.has(n.id)) })));
  }, [nodes]);

  // --- scene (once) ---

  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f3f5f4");
    const camera = new THREE.PerspectiveCamera(45, el.clientWidth / el.clientHeight, 0.5, 5000);
    camera.position.set(60, 50, 80);
    const controls = new OrbitControls(camera, renderer.domElement);
    scene.add(new THREE.HemisphereLight("#ffffff", "#b8b4aa", 1.7));
    const sun = new THREE.DirectionalLight("#ffffff", 1.6);
    sun.position.set(80, 140, 60);
    scene.add(sun);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshStandardMaterial({ color: "#d3dccf", roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    scene.add(ground);
    const content = new THREE.Group();
    scene.add(content);
    const v = new THREE.Vector3();
    const render = () => {
      renderer.render(scene, camera);
      const w = el.clientWidth;
      const h = el.clientHeight;
      for (const label of three.current?.labels ?? []) {
        v.copy(label.pos).project(camera);
        const visible = v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
        label.el.style.display = visible ? "block" : "none";
        if (visible) label.el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -100%)`;
      }
    };
    controls.addEventListener("change", render);
    three.current = { renderer, scene, camera, controls, content, ground, pickables: [], labels: [], render };
    const resize = new ResizeObserver(() => {
      renderer.setSize(el.clientWidth, el.clientHeight);
      camera.aspect = el.clientWidth / Math.max(1, el.clientHeight);
      camera.updateProjectionMatrix();
      render();
    });
    resize.observe(el);
    return () => {
      resize.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      three.current = null;
    };
  }, []);

  // --- what is drawn, and how ---

  const visible = useCallback(
    (b: Box): boolean => {
      if (b.role === "group") return false;
      if (b.below && !below) return false;
      if (maxLevel !== null && b.level !== null && b.level > maxLevel) return false;
      const cut = cutaway !== null ? boxes.find((x) => x.node_id === cutaway && x.role === "floor") : undefined;
      if (b.role === "flat" || b.role === "room") return !!cut && b.floor_id === cut.node_id;
      if (cut && b.tower_id === cut.tower_id) {
        if (b.node_id === cut.node_id) return false;
        if (b.level !== null && b.level > cut.level!) return false;
      }
      return true;
    },
    [below, maxLevel, cutaway, boxes],
  );

  // survey state per node: its own areas, else rolled up from the places inside it
  const surveyState = useMemo(() => {
    const out = new Map<number, "measured" | "camera" | "none">();
    if (!surveyMap || !model) return out;
    const kids = new Map<number, number[]>();
    for (const n of model.nodes) if (n.parent_id !== null) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n.id]);
    const walk = (id: number): "measured" | "camera" | "none" => {
      if (out.has(id)) return out.get(id)!;
      const own = surveyMap.nodes[String(id)];
      const below = (kids.get(id) ?? []).map(walk);
      const all = [own, ...below].filter(Boolean);
      const v = all.includes("measured") ? "measured" : all.includes("camera") ? "camera" : "none";
      out.set(id, v);
      return v;
    };
    model.nodes.forEach((n) => walk(n.id));
    return out;
  }, [surveyMap, model]);
  const readySet = useMemo(() => new Set(surveyMap?.ready ?? []), [surveyMap]);
  const surveyCounts = useMemo(() => {
    const c = { measured: 0, camera: 0, none: 0 };
    for (const n of model?.nodes ?? []) if (!GROUP_KINDS.has(n.kind)) c[surveyState.get(n.id) ?? "none"] += 1;
    return c;
  }, [surveyState, model]);

  const look = useCallback(
    (b: Box): { color: string; ghost: boolean; late: boolean } => {
      const n = byId.get(b.node_id);
      if (!n) return { color: "#cccccc", ghost: false, late: false };
      if (mode === "survey") {
        const st = surveyState.get(n.id) ?? "none";
        return { color: SURVEY_COLORS[st], ghost: st === "none" && b.role === "flat", late: readySet.has(n.id) };
      }
      const leaf = b.role !== "floor" && b.role !== "group";
      const filteredOut =
        leaf && ((templateFilter && !n.status.template_ids.includes(Number(templateFilter))) || (statusFilter && workColor(n.status, false).category !== statusFilter));
      if (mode === "real") return { color: realisticColor(b.kind), ghost: b.role === "flat" || !!filteredOut, late: false };
      if (filteredOut) return { color: STATUS_COLORS.none, ghost: true, late: false };
      const c = workColor(n.status, workBelow.get(n.id) ?? false);
      return { color: c.color, ghost: c.ghost || b.role === "flat", late: n.status.is_late };
    },
    [byId, mode, templateFilter, statusFilter, workBelow, surveyState, readySet],
  );

  useEffect(() => {
    const t = three.current;
    if (!t || !model) return;
    // clear the previous build
    for (const child of [...t.content.children]) {
      t.content.remove(child);
      if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments) {
        child.geometry.dispose();
        (child.material as THREE.Material).dispose();
      }
    }
    labelsEl.current?.replaceChildren();
    const shown = boxes.filter(visible);
    const solid: Box[] = [];
    const ghost: Box[] = [];
    const late: Box[] = [];
    const styles = new Map<Box, { color: string }>();
    for (const b of shown) {
      const s = look(b);
      styles.set(b, s);
      (s.ghost ? ghost : solid).push(b);
      if (s.late) late.push(b);
    }
    const unit = new THREE.BoxGeometry(1, 1, 1);
    const matrix = new THREE.Matrix4();
    const quat = new THREE.Quaternion();
    const color = new THREE.Color();
    const make = (list: Box[], material: THREE.Material) => {
      if (!list.length) return null;
      const mesh = new THREE.InstancedMesh(unit.clone(), material, list.length);
      list.forEach((b, i) => {
        matrix.compose(new THREE.Vector3(b.x, b.y, b.z), quat, new THREE.Vector3(b.w, b.h, b.d));
        mesh.setMatrixAt(i, matrix);
        mesh.setColorAt(i, color.set(styles.get(b)!.color));
      });
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      t.content.add(mesh);
      return mesh;
    };
    const pickables: { mesh: THREE.InstancedMesh; boxes: Box[] }[] = [];
    const solidMesh = make(solid, new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0 }));
    if (solidMesh) pickables.push({ mesh: solidMesh, boxes: solid });
    const ghostMesh = make(ghost, new THREE.MeshStandardMaterial({ transparent: true, opacity: 0.22, depthWrite: false, roughness: 1 }));
    if (ghostMesh) pickables.push({ mesh: ghostMesh, boxes: ghost });
    unit.dispose();
    // late: red outlines
    if (late.length) {
      const pts: number[] = [];
      for (const b of late) {
        const [x0, x1, y0, y1, z0, z1] = [b.x - b.w / 2, b.x + b.w / 2, b.y - b.h / 2, b.y + b.h / 2, b.z - b.d / 2, b.z + b.d / 2];
        const c = [
          [x0, y0, z0],
          [x1, y0, z0],
          [x1, y0, z1],
          [x0, y0, z1],
          [x0, y1, z0],
          [x1, y1, z0],
          [x1, y1, z1],
          [x0, y1, z1],
        ];
        for (const [a, e] of [
          [0, 1],
          [1, 2],
          [2, 3],
          [3, 0],
          [4, 5],
          [5, 6],
          [6, 7],
          [7, 4],
          [0, 4],
          [1, 5],
          [2, 6],
          [3, 7],
        ])
          pts.push(...c[a], ...c[e]);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      t.content.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: mode === "survey" ? READY_COLOR : LATE_COLOR })));
    }
    // ground under everything, hidden when looking below it
    const all = new THREE.Box3();
    for (const b of boxes.filter((x) => x.role !== "group"))
      all.expandByPoint(new THREE.Vector3(b.x - b.w / 2, 0, b.z - b.d / 2)).expandByPoint(new THREE.Vector3(b.x + b.w / 2, 0, b.z + b.d / 2));
    const size = all.isEmpty() ? new THREE.Vector3(40, 0, 40) : all.getSize(new THREE.Vector3());
    const centre = all.isEmpty() ? new THREE.Vector3() : all.getCenter(new THREE.Vector3());
    t.ground.scale.set(size.x + 40, size.z + 40, 1);
    t.ground.position.set(centre.x, -0.02, centre.z);
    (t.ground.material as THREE.MeshStandardMaterial).color.set(mode === "real" ? "#a9b994" : "#d3dccf");
    t.ground.visible = !below;
    // labels: towers with their %, floors with theirs (work view)
    const labels: { el: HTMLDivElement; pos: THREE.Vector3 }[] = [];
    const addLabel = (text: string, pos: THREE.Vector3, cls: string) => {
      const div = document.createElement("div");
      div.className = `label3d ${cls}`;
      div.textContent = text;
      labelsEl.current?.appendChild(div);
      labels.push({ el: div, pos });
    };
    for (const b of boxes.filter((x) => x.role === "group" && x.kind === "tower")) {
      const n = byId.get(b.node_id);
      const top = Math.max(...shown.filter((x) => x.tower_id === b.node_id).map((x) => x.y + x.h / 2), 0);
      addLabel(`${n?.name ?? ""} · ${Math.round(n?.status.percent ?? 0)}%`, new THREE.Vector3(b.x, top + 2, 0), "label-tower");
    }
    if (mode === "work" && cutaway === null) {
      const floors = shown.filter((b) => b.role === "floor");
      if (floors.length <= 80) {
        for (const b of floors) {
          const n = byId.get(b.node_id);
          if (n && workBelow.get(n.id)) {
            const late = lateBelow.has(n.id);
            addLabel(
              `${n.name} ${Math.round(n.status.percent)}%${late ? " · late" : ""}`,
              new THREE.Vector3(b.x + b.w / 2 + 0.3, b.y + 0.4, b.z + b.d / 2),
              late ? "label-floor label-late" : "label-floor",
            );
          }
        }
      }
    }
    t.pickables = pickables;
    t.labels = labels;
    if (!framed.current && shown.length) {
      framed.current = true;
      view("reset");
    }
    t.render();
    // view() only reads refs; rebuild when the drawing inputs change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, boxes, visible, look, below, mode, cutaway, byId, workBelow, lateBelow]);

  // --- camera ---

  function view(kind: "reset" | "top" | "front") {
    const t = three.current;
    if (!t) return;
    const box = new THREE.Box3();
    for (const b of boxes.filter(visible))
      box.expandByPoint(new THREE.Vector3(b.x - b.w / 2, b.y - b.h / 2, b.z - b.d / 2)).expandByPoint(new THREE.Vector3(b.x + b.w / 2, b.y + b.h / 2, b.z + b.d / 2));
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(10, box.getSize(new THREE.Vector3()).length() / 2);
    const d = r / Math.sin((t.camera.fov * Math.PI) / 360);
    const dir = kind === "top" ? new THREE.Vector3(0, 1, 0.001) : kind === "front" ? new THREE.Vector3(0, 0.15, 1) : new THREE.Vector3(0.75, 0.55, 1);
    t.camera.position.copy(c).add(dir.normalize().multiplyScalar(d * 1.05));
    t.camera.near = d / 100;
    t.camera.far = d * 10;
    t.camera.updateProjectionMatrix();
    t.controls.target.copy(c);
    t.controls.update();
    t.render();
  }

  // --- picking ---

  const pick = useCallback((e: { clientX: number; clientY: number }): Box | null => {
    const t = three.current;
    const el = mount.current;
    if (!t || !el) return null;
    const rect = el.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1), t.camera);
    const hits = ray.intersectObjects(
      t.pickables.map((p) => p.mesh),
      false,
    );
    // a room inside a see-through flat wins over the flat
    const found = hits
      .map((h) => {
        const p = t.pickables.find((x) => x.mesh === h.object);
        return p && h.instanceId !== undefined ? { box: p.boxes[h.instanceId], dist: h.distance } : null;
      })
      .filter((x): x is { box: Box; dist: number } => !!x);
    return (found.find((f) => f.box.role === "room") ?? found[0])?.box ?? null;
  }, []);

  const downAt = useRef<{ x: number; y: number } | null>(null);
  const hoverFrame = useRef(0);
  useEffect(() => () => cancelAnimationFrame(hoverFrame.current), []);

  function onMove(e: React.PointerEvent) {
    const { clientX, clientY } = e;
    cancelAnimationFrame(hoverFrame.current);
    hoverFrame.current = requestAnimationFrame(() => {
      if (!mount.current) return; // the tab was closed meanwhile
      const b = pick({ clientX, clientY });
      const rect = mount.current.getBoundingClientRect();
      const n = b ? byId.get(b.node_id) : undefined;
      setHover(n ? { x: clientX - rect.left, y: clientY - rect.top, node: n } : null);
    });
  }

  function onClick(e: React.PointerEvent) {
    const start = downAt.current;
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 5) return; // a drag
    const b = pick(e);
    if (!b) return;
    if (b.role === "floor") {
      setCutaway(b.node_id);
      setSelected(null);
    } else setSelected(b.node_id);
  }

  /** A PNG on white: header (site, code, date, overall %), the view, its labels and the legend. */
  function saveImage() {
    const t = three.current;
    if (!t || !nodes.length) return;
    t.render();
    const source = t.renderer.domElement;
    const w = source.clientWidth || source.width;
    const h = source.clientHeight || source.height;
    const v = new THREE.Vector3();
    const labels: SnapLabel[] = [];
    for (const l of t.labels) {
      v.copy(l.pos).project(t.camera);
      if (!(v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05)) continue;
      labels.push({
        text: l.el.textContent ?? "",
        x: ((v.x + 1) / 2) * w,
        y: ((1 - v.y) / 2) * h,
        tower: l.el.classList.contains("label-tower"),
        late: l.el.classList.contains("label-late"),
      });
    }
    const legendItems =
      mode === "work"
        ? [
            ...CATEGORIES.map((c) => ({ label: CATEGORY_LABEL[c], color: STATUS_COLORS[c], count: legend[c], ghost: c === "none" })),
            { label: "Late", color: LATE_COLOR, count: legend.late, outline: true },
          ]
        : mode === "survey"
          ? SURVEY_LEGEND.map((l) => ({ label: l.label, color: SURVEY_COLORS[l.key], count: surveyCounts[l.key], ghost: l.key === "none" }))
          : [];
    const out = composeSnapshot(source, source.width / w, {
      siteName: site.name,
      siteCode: site.code,
      percent: model?.site_progress ?? Number(site.progress_percent),
      date: new Date(),
      labels,
      legend: legendItems,
      note:
        mode === "work"
          ? "Floors and towers: rolled-up % (grey → green)"
          : mode === "survey"
            ? "Survey: approved surveys only"
            : "Realistic tones: concrete floors, brick flats, tiled wet areas.",
    });
    const link = document.createElement("a");
    link.href = out.toDataURL("image/png");
    link.download = `${site.code}-3d-${new Date().toISOString().slice(0, 10)}.png`;
    link.click();
  }

  const cutNode = cutaway !== null ? byId.get(cutaway) : undefined;
  const hasBelow = boxes.some((b) => b.below);

  return (
    <div className="split-3d">
      <div className="card">
        <div className="toolbar">
          <div className="page-actions">
            <div className="tabs">
              <button className={`tab ${mode === "work" ? "active" : ""}`} onClick={() => setMode("work")}>
                Work status
              </button>
              <button className={`tab ${mode === "real" ? "active" : ""}`} onClick={() => setMode("real")}>
                Realistic
              </button>
              {canSurvey && (
                <button className={`tab ${mode === "survey" ? "active" : ""}`} onClick={() => setMode("survey")}>
                  Survey
                </button>
              )}
            </div>
            <button className="btn btn-small" onClick={() => view("reset")}>
              Reset view
            </button>
            <button className="btn btn-small" onClick={() => view("top")}>
              Top
            </button>
            <button className="btn btn-small" onClick={() => view("front")}>
              Front
            </button>
            {hasBelow && (
              <label className="check">
                <input type="checkbox" checked={below} onChange={(e) => setBelow(e.target.checked)} /> Below ground
              </label>
            )}
            {levels.length > 1 && (
              <label className="check" title="Show floors up to">
                Floors up to{" "}
                <input
                  type="range"
                  min={levels[0]}
                  max={levels[levels.length - 1]}
                  value={maxLevel ?? levels[levels.length - 1]}
                  onChange={(e) => setMaxLevel(Number(e.target.value) >= levels[levels.length - 1] ? null : Number(e.target.value))}
                />{" "}
                <strong>{maxLevel === null ? "all" : maxLevel === 0 ? "G" : maxLevel < 0 ? `B${-maxLevel}` : maxLevel}</strong>
              </label>
            )}
            <select aria-label="Open floor" value={cutaway ?? ""} onChange={(e) => setCutaway(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Open floor…</option>
              {boxes
                .filter((b) => b.role === "floor")
                .sort((a, b) => (a.tower_id ?? 0) - (b.tower_id ?? 0) || b.level! - a.level!)
                .map((b) => (
                  <option key={b.node_id} value={b.node_id}>
                    {byId.get(b.tower_id ?? -1)?.name ?? ""} {byId.get(b.node_id)?.name}
                  </option>
                ))}
            </select>
            <select value={templateFilter} onChange={(e) => setTemplateFilter(e.target.value)}>
              <option value="">All work</option>
              {usedTemplates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              {CATEGORIES.filter((c) => c !== "none").map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </option>
              ))}
            </select>
            <button className="btn btn-small" onClick={saveImage} disabled={!nodes.length} title={nodes.length ? undefined : "Add a structure first"}>
              Save image
            </button>
          </div>
          {cutNode && (
            <span className="inline-form">
              <span className="badge badge-info">Cutaway: {cutNode.name}</span>
              <button className="btn btn-small btn-ghost" onClick={() => setCutaway(null)}>
                Show all floors
              </button>
            </span>
          )}
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        <div
          className="viewport3d"
          ref={mount}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          onPointerDown={(e) => (downAt.current = { x: e.clientX, y: e.clientY })}
          onPointerUp={onClick}
        >
          <div className="labels3d" ref={labelsEl} />
          {hover && (
            <div className="tooltip3d" style={{ left: hover.x + 14, top: hover.y + 14 }}>
              <strong>{hover.node.name}</strong> <span className="muted">{hover.node.kind.replace("_", " ")}</span>
              <div>{Math.round(hover.node.status.percent)}% done</div>
              {hover.node.status.current_step && <div>Now: {hover.node.status.current_step}</div>}
              {hover.node.status.next_step && <div>Next: {hover.node.status.next_step}</div>}
              {hover.node.status.waiting_certification && <div>Waiting for certification</div>}
              {hover.node.status.is_late && <div className="text-danger">Late</div>}
            </div>
          )}
          {mode === "survey" && (
            <div className="legend3d-overlay" aria-label="Survey colours">
              {SURVEY_LEGEND.map((l) => (
                <span key={l.key} className="legend-item">
                  <span className="swatch" style={{ background: SURVEY_COLORS[l.key] }} /> {l.label}
                </span>
              ))}
              <span className="legend-item">
                <span className="swatch outline" style={{ borderColor: READY_COLOR }} /> Work front ready ({readySet.size})
              </span>
            </div>
          )}
          {!nodes.length && model && (
            <div className="empty3d">
              <div className="empty3d-box">
                <p>No structure yet. Add a tower in the Structure tab.</p>
                {onOpenStructure && (
                  <button className="btn btn-primary" onClick={onOpenStructure}>
                    Go to the Structure tab
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="legend3d">
          {mode === "survey" ? (
            <>
              <span className="legend-item">
                <span className="swatch" style={{ background: SURVEY_COLORS.measured }} /> Measured (laser / by hand)
              </span>
              <span className="legend-item">
                <span className="swatch" style={{ background: SURVEY_COLORS.camera }} /> Measured by camera only
              </span>
              <span className="legend-item">
                <span className="swatch" style={{ background: SURVEY_COLORS.none }} /> Not measured
              </span>
              <span className="legend-item muted">
                Approved surveys only{surveyMap?.unplaced_areas ? ` · ${surveyMap.unplaced_areas} area(s) not placed on the structure` : ""}
              </span>
            </>
          ) : mode === "work" ? (
            <>
              {CATEGORIES.map((c) => (
                <span key={c} className="legend-item">
                  <span className={`swatch ${c === "none" ? "swatch-ghost" : ""}`} style={{ background: STATUS_COLORS[c] }} /> {CATEGORY_LABEL[c]} ({legend[c]})
                </span>
              ))}
              <span className="legend-item">
                <span className="swatch swatch-late" /> Late ({legend.late})
              </span>
              <span className="legend-item muted">Floors and towers: rolled-up % (grey → green)</span>
            </>
          ) : (
            <span className="muted">Realistic tones: concrete floors, brick flats, tiled wet areas.</span>
          )}
          <span className="push-right muted small">
            {portal ? "Click a floor to open it · drag to turn" : "Click a floor to open it · click a room for its steps · updates every minute"}
          </span>
        </div>
      </div>
      {mode === "survey" && surveyMap && (
        <SurveyPanel
          map={surveyMap}
          nodes={model?.nodes ?? []}
          focus={selected ?? cutaway}
          name={byId.get(selected ?? cutaway ?? -1)?.name}
          onClose={() => {
            setSelected(null);
            setCutaway(null);
          }}
        />
      )}
      {!portal && mode !== "survey" && selected !== null && byId.get(selected) && (
        <NodePanel
          site={site as Site}
          node={byId.get(selected)!}
          canUpdate={canUpdate}
          canEdit={canEdit}
          onClose={() => setSelected(null)}
          onChanged={() => {
            void load();
            onChange();
          }}
        />
      )}
    </div>
  );
}

const STEP_BADGE: Record<string, string> = {
  not_started: "badge-muted",
  in_progress: "badge-info",
  done: "badge-warn",
  certified: "badge-ok",
  blocked: "badge-danger",
};

function NodePanel({
  site,
  node,
  canUpdate,
  canEdit,
  onClose,
  onChanged,
}: {
  site: Site;
  node: ModelNode;
  canUpdate: boolean;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tasks, setTasks] = useState<SiteTask[]>([]);
  const [scopeNames, setScopeNames] = useState<Map<number, string>>(new Map());
  const [photos, setPhotos] = useState<{ key: string; url: string | null; name: string }[]>([]);
  const [open, setOpen] = useState<SiteTask | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api<SiteTask[]>(`/api/sites/${site.id}/tasks?node_id=${node.id}`);
      setTasks(list); // the place and everything inside it (a flat shows its rooms)
      const scope = await api<{ lines: { scopes: { id: number; stage_template_name: string }[] }[]; other_scopes: { id: number; stage_template_name: string }[] }>(
        `/api/sites/${site.id}/scope`,
      );
      setScopeNames(new Map([...scope.lines.flatMap((l) => l.scopes), ...scope.other_scopes].map((s) => [s.id, s.stage_template_name])));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id, node.id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let alive = true;
    const last = tasks
      .flatMap((t) => t.photos.map((p) => ({ task: t.id, ...p })))
      .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
      .slice(0, 3);
    Promise.all(last.map(async (p) => ({ key: `${p.task}-${p.id}`, name: p.filename, url: await fetchObjectUrl(`/api/sites/${site.id}/tasks/${p.task}/photos/${p.id}`) }))).then(
      (list) => alive && setPhotos(list),
    );
    return () => {
      alive = false;
    };
  }, [tasks, site.id]);

  const groups = useMemo(() => {
    const out = new Map<number | null, SiteTask[]>();
    for (const t of tasks) out.set(t.area_scope_id, [...(out.get(t.area_scope_id) ?? []), t]);
    return [...out.entries()].map(([scopeId, list]) => ({ scopeId, list, where: list[0]?.node_path?.split(" › ").pop() ?? "" }));
  }, [tasks]);

  return (
    <aside className="card panel3d">
      <div className="toolbar">
        <div>
          <h2 className="section-title">{node.name}</h2>
          <span className="muted small">
            {node.kind.replace("_", " ")} · {Math.round(node.status.percent)}% done
          </span>
        </div>
        <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {photos.length > 0 && <div className="photo-strip">{photos.map((p) => (p.url ? <img key={p.key} src={p.url} alt={p.name} /> : null))}</div>}
      {groups.length === 0 && <p className="muted">No work scheduled here.</p>}
      {groups.map(({ scopeId, list, where }) => (
        <div key={scopeId ?? 0} className="top-gap">
          <strong className="small">
            {list[0]?.node_id !== node.id && `${where}: `}
            {(scopeId && scopeNames.get(scopeId)) || "Tasks"}
          </strong>
          <table className="table compact">
            <tbody>
              {list.map((t) => (
                <tr key={t.id}>
                  <td>
                    {t.name} {t.hold_point && <span className="badge badge-orange">hold</span>}
                    <div className={`muted small ${t.late ? "text-danger" : ""}`}>
                      {shortDate(t.planned_start)} – {shortDate(t.planned_end)}
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${STEP_BADGE[t.status]}`}>{t.status.replace("_", " ")}</span>
                  </td>
                  <td>
                    {canUpdate && (
                      <button className="btn btn-small" onClick={() => setOpen(t)}>
                        Update task
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {open && (
        <TaskDialog
          site={site}
          task={open}
          canUpdate={canUpdate}
          canEdit={canEdit}
          onClose={() => setOpen(null)}
          onSaved={(t) => {
            setOpen(t);
            void load();
            onChanged();
          }}
        />
      )}
    </aside>
  );
}

const STOREY_KINDS = new Set(["floor", "basement", "terrace", "podium"]);

/** Survey mode: product totals for the chosen tower / floor (or the whole site), floor by floor. */
function SurveyPanel({ map, nodes, focus, name, onClose }: { map: SurveyMap; nodes: ModelNode[]; focus: number | null; name?: string; onClose: () => void }) {
  const kids = new Map<number, number[]>();
  for (const n of nodes) if (n.parent_id !== null) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n.id]);
  const byIdLocal = new Map(nodes.map((n) => [n.id, n]));
  const subtree = (id: number): number[] => [id, ...(kids.get(id) ?? []).flatMap(subtree)];
  const scope = focus !== null ? subtree(focus) : nodes.map((n) => n.id);
  // one group per storey (floor, basement, terrace, podium); anything outside a storey goes under "Elsewhere"
  const storey = (id: number) => STOREY_KINDS.has(byIdLocal.get(id)?.kind ?? "");
  const inside = (id: number): boolean => {
    const p = byIdLocal.get(id)?.parent_id ?? null;
    return p !== null && (storey(p) || inside(p));
  };
  const floors = scope.filter((id) => storey(id) && !inside(id));
  const covered = new Set(floors.flatMap(subtree));
  const rest = scope.filter((id) => !covered.has(id));
  const keys = floors.length ? [...floors, ...(rest.some((id) => map.products[String(id)]?.length) ? [-2] : [])] : [focus ?? -1];
  const groups = keys.map((fid) => {
    const ids = fid === -1 ? scope : fid === -2 ? rest : subtree(fid);
    const sum = new Map<number, { name: string; unit: string; qty: number }>();
    for (const id of ids)
      for (const p of map.products[String(id)] ?? []) {
        const cur = sum.get(p.product_id) ?? { name: p.name, unit: p.unit, qty: 0 };
        cur.qty += Number(p.qty);
        sum.set(p.product_id, cur);
      }
    const label =
      fid === -1 ? "Whole site" : fid === -2 ? "Elsewhere" : `${byIdLocal.get(byIdLocal.get(fid)?.parent_id ?? -1)?.name ?? ""} ${byIdLocal.get(fid)?.name ?? ""}`.trim();
    return { id: fid, name: label, products: [...sum.values()].sort((a, b) => a.name.localeCompare(b.name)) };
  });
  return (
    <aside className="card node-panel survey-panel">
      <div className="toolbar">
        <h2 className="section-title">Products · {name ?? "whole site"}</h2>
        {focus !== null && (
          <button className="btn btn-small btn-ghost" onClick={onClose}>
            Whole site
          </button>
        )}
      </div>
      {groups.every((g) => g.products.length === 0) && <p className="muted small">No approved survey quantities here yet.</p>}
      {groups
        .filter((g) => g.products.length)
        .map((g) => (
          <div key={g.id} className="top-gap">
            <strong className="small">{g.name}</strong>
            <table className="table compact">
              <tbody>
                {g.products.map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td className="num">
                      {p.qty.toFixed(2)} {p.unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      <p className="muted small">Exact quantities; whole packs are rounded on the survey or indent total.</p>
    </aside>
  );
}
