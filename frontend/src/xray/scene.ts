// The X-ray building in three.js. Per floor type one set of geometries (slab, its edges, the outer
// shell, walls, columns, beams, cores) shared by every floor of that type (each floor a group
// pointing at the same buffers: one upload, one draw call per material per floor); per floor one
// merged mesh of its rooms with a colour per vertex, so a new date only rewrites colours.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Category } from "../pages/site/three/colors";
import { LATE_COLOR, STATUS_COLORS } from "../pages/site/three/colors";
import type { Building, P, XFloor, XRoom, XType } from "./geometry";
import type { IfcElement } from "./ifc";
import { bounds, centroid, explodeOffset, polygonArea, roomSolid, stairSteps } from "./geometry";

export type Mode = "xray" | "status" | "real";
export type Preset = "reset" | "top" | "front" | "iso";
export type RoomState = { category: Exclude<Category, "rollup">; late: boolean };
export type Label = { text: string; sub: string; x: number; y: number; nodeId: number };

const BEAM_D = 0.45;
const BEAM_W = 0.23;
const RAIL_H = 0.9;

type RoomSpan = { room: XRoom; start: number; count: number; lineStart: number; lineCount: number; volStart: number; volCount: number };
type FloorParts = { floor: XFloor; index: number; group: THREE.Group; rooms: THREE.Mesh | null; roomLines: THREE.LineSegments | null; volume: THREE.Mesh | null; late: THREE.LineSegments; spans: RoomSpan[] };

const PALETTE: Record<Mode, { bg: string; fog: number; line: string; lineOpacity: number; shell: string; face: string; faceOpacity: number; slab: string; glass: string; roomOpacity: number }> = {
  xray: { bg: "#03070d", fog: 0.0065, line: "#5fb8ff", lineOpacity: 0.3, shell: "#bfe7ff", face: "#1d5c8f", faceOpacity: 0.05, slab: "#1d5c8f", glass: "#1d5c8f", roomOpacity: 0.78 },
  status: { bg: "#f3f5f6", fog: 0, line: "#8f989e", lineOpacity: 0.55, shell: "#5d676d", face: "#d9dee1", faceOpacity: 0.28, slab: "#e3e6e8", glass: "#d9dee1", roomOpacity: 1 },
  real: { bg: "#dfe8ef", fog: 0.002, line: "#6e6a63", lineOpacity: 0.35, shell: "#55524c", face: "#a9c9dc", faceOpacity: 0.3, slab: "#bdb8ae", glass: "#9fc6dc", roomOpacity: 1 },
};

const v3 = (x: number, y: number, h: number) => new THREE.Vector3(x, h, -y);

function shapeOf(pts: P[]): THREE.Shape {
  const s = new THREE.Shape();
  pts.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  s.closePath();
  return s;
}

/** A plan outline extruded between two heights, lying flat (plan y becomes -Z). */
function prism(pts: P[], bottom: number, height: number): THREE.BufferGeometry {
  const g = new THREE.ExtrudeGeometry(shapeOf(pts), { depth: height, bevelEnabled: false });
  g.rotateX(-Math.PI / 2);
  g.translate(0, bottom, 0);
  return g;
}

function box(x: number, y: number, w: number, d: number, bottom: number, h: number): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(x, bottom + h / 2, -y);
  return g;
}

function segmentsGeometry(points: number[]): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  return g;
}

function merged(list: THREE.BufferGeometry[]): THREE.BufferGeometry | null {
  const clean = list.filter((g) => g.getAttribute("position")?.count).map((g) => (g.index ? g.toNonIndexed() : g));
  for (const g of clean) for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal") g.deleteAttribute(name);
  return clean.length ? mergeGeometries(clean, false) : null;
}

export const MAX_MERGED_FLOORS = 64;

/** A floor's copy of a floor type's geometry: lifted to its level, each vertex marked with the
 *  floor (the shader moves it in the explode view and hides it in a cutaway). */
export function floorCopy(geo: THREE.BufferGeometry, y: number, floorIndex: number, keepNormals: boolean): THREE.BufferGeometry {
  const c = geo.index ? geo.toNonIndexed() : geo.clone();
  for (const name of Object.keys(c.attributes)) if (name !== "position" && !(keepNormals && name === "normal")) c.deleteAttribute(name);
  if (keepNormals && !c.getAttribute("normal")) c.computeVertexNormals();
  c.translate(0, y, 0);
  c.setAttribute("aFloor", new THREE.Float32BufferAttribute(new Float32Array(c.getAttribute("position").count).fill(floorIndex), 1));
  return c;
}

/** The floors of one material merged into one object: one draw call for the whole building. */
export function mergeFloors(parts: THREE.BufferGeometry[]): THREE.BufferGeometry | null {
  return parts.length ? mergeGeometries(parts, false) : null;
}

type FloorUniforms = { uOff: { value: Float32Array }; uVis: { value: Float32Array } };

/** The per-floor offset (explode) and visibility (cutaway) applied in the vertex shader. */
function hookFloors(mat: THREE.Material, u: FloorUniforms): void {
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uOff = u.uOff;
    shader.uniforms.uVis = u.uVis;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\nattribute float aFloor;\nuniform float uOff[${MAX_MERGED_FLOORS}];\nuniform float uVis[${MAX_MERGED_FLOORS}];`)
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nint fl = int(aFloor + 0.5);\ntransformed.y += uOff[fl];\nif (uVis[fl] < 0.5) transformed = vec3(0.0, -1.0e6, 0.0);");
  };
  mat.customProgramCacheKey = () => "floors";
}

type TypeGeo = { slab: THREE.BufferGeometry; cutFace: THREE.BufferGeometry; slabEdges: THREE.BufferGeometry; shell: LineSegmentsGeometry; walls: THREE.BufferGeometry | null; wallFaces: THREE.BufferGeometry | null; cols: THREE.BufferGeometry | null; colEdges: THREE.BufferGeometry | null; detail: THREE.BufferGeometry | null; detailEdges: THREE.BufferGeometry | null; height: number };

/** The shared geometry of one floor type, at a given storey height (local: slab top at 0). */
export function typeGeometry(t: XType, height: number, slab: number, riser: number): TypeGeo {
  const slabG = prism(t.outline, -slab, slab);
  const slabEdges = new THREE.EdgesGeometry(slabG, 20);
  // the outer shell: the outline at floor and ceiling, and its corners up the storey (thicker lines)
  const shell: number[] = [];
  t.outline.forEach(([x, y], i) => {
    const [x2, y2] = t.outline[(i + 1) % t.outline.length];
    shell.push(x, 0, -y, x2, 0, -y2, x, height - slab, -y, x2, height - slab, -y2, x, -slab, -y, x, height - slab, -y);
  });
  const shellG = new LineSegmentsGeometry().setPositions(shell);
  // walls: thin lines at floor and ceiling height, faint faces between
  const wl: number[] = [];
  const wf: number[] = [];
  const top = height - slab;
  for (const [x1, y1, x2, y2] of t.walls) {
    wl.push(x1, 0, -y1, x2, 0, -y2, x1, top, -y1, x2, top, -y2);
    wf.push(x1, 0, -y1, x2, 0, -y2, x2, top, -y2, x1, 0, -y1, x2, top, -y2, x1, top, -y1);
  }
  const walls = wl.length ? segmentsGeometry(wl) : null;
  const wallFaces = wf.length ? segmentsGeometry(wf) : null;
  wallFaces?.computeVertexNormals();
  const colList = t.columns.map(([x, y, w, d]) => box(x, y, w, d, 0, top));
  const cols = merged(colList);
  const colEdges = merged(colList.map((g) => new THREE.EdgesGeometry(g)));
  // beams under the slab above, between the columns picked (or on the column lines)
  const detail: THREE.BufferGeometry[] = [];
  const detailLines: THREE.BufferGeometry[] = [];
  for (const [i, j] of t.beams) {
    const a = t.columns[i];
    const b = t.columns[j];
    if (!a || !b) continue;
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const g = new THREE.BoxGeometry(len, BEAM_D, BEAM_W);
    g.rotateY(Math.atan2(b[1] - a[1], b[0] - a[0]));
    g.translate((a[0] + b[0]) / 2, top - BEAM_D / 2, -(a[1] + b[1]) / 2);
    detail.push(g);
    detailLines.push(new THREE.EdgesGeometry(g));
  }
  // cores: a lift shaft as its box of lines; a stair as its steps with a railing line
  for (const c of t.cores) {
    if (c.outline.length < 3) continue;
    if (c.kind === "lift") {
      const b = bounds(c.outline);
      const g = box((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, b.maxX - b.minX, b.maxY - b.minY, 0, height);
      detailLines.push(new THREE.EdgesGeometry(g));
      continue;
    }
    const steps = stairSteps(c.outline, height, riser, c.risers);
    const rail: number[] = [];
    steps.forEach((s, k) => {
      const g = box(s.x, s.y, s.w, s.d, s.bottom, s.h);
      detail.push(g);
      detailLines.push(new THREE.EdgesGeometry(g));
      if (k) {
        const p = steps[k - 1];
        rail.push(p.x, p.bottom + p.h + RAIL_H, -p.y, s.x, s.bottom + s.h + RAIL_H, -s.y);
      }
    });
    detailLines.push(segmentsGeometry(rail));
  }
  const cutFace = new THREE.ShapeGeometry(shapeOf(t.outline));
  cutFace.rotateX(-Math.PI / 2);
  cutFace.translate(0, 0.005, 0);
  return {
    slab: slabG,
    cutFace,
    slabEdges,
    shell: shellG,
    walls,
    wallFaces,
    cols,
    colEdges,
    detail: merged(detail),
    detailEdges: merged(detailLines),
    height,
  };
}

/** One floor's rooms in one geometry: each room's floor (dropped by its sunk depth) and the band
 *  of waterproofing up its walls, with a colour per vertex; the spans say which vertices are whose. */
export function roomsGeometry(rooms: XRoom[], floor: XFloor, slab: number): { mesh: THREE.BufferGeometry; lines: THREE.BufferGeometry; volume: THREE.BufferGeometry; spans: RoomSpan[] } | null {
  const parts: THREE.BufferGeometry[] = [];
  const vols: THREE.BufferGeometry[] = [];
  const lineParts: number[] = [];
  const spans: RoomSpan[] = [];
  let at = 0;
  let volAt = 0;
  for (const room of rooms) {
    if (room.outline.length < 3) continue;
    const s = roomSolid(room, floor);
    const local = s.bottom - floor.elevation_m;
    const base = prism(room.outline, local, 0.06).toNonIndexed();
    const band: number[] = [];
    const ln: number[] = [];
    room.outline.forEach(([x1, y1], i) => {
      const [x2, y2] = room.outline[(i + 1) % room.outline.length];
      const lo = local;
      const hi = local + (room.sunk_m || 0) + s.band;
      band.push(x1, lo, -y1, x2, lo, -y2, x2, hi, -y2, x1, lo, -y1, x2, hi, -y2, x1, hi, -y1);
      ln.push(x1, lo + 0.07, -y1, x2, lo + 0.07, -y2, x1, hi, -y1, x2, hi, -y2, x1, lo, -y1, x1, hi, -y1);
    });
    base.deleteAttribute("uv");
    base.deleteAttribute("normal");
    const g = mergeGeometries([base, segmentsGeometry(band)]);
    const count = g.getAttribute("position").count;
    parts.push(g);
    // the room's faint volume up to the ceiling: stacked rooms read as columns of colour (not a
    // terrace: it would fill the top of the building; it shows as its outline with a light fill)
    const vol = prism(room.outline, local, room.kind === "terrace" ? 0.01 : Math.max(0.2, floor.height_m - slab - local)).toNonIndexed();
    vol.deleteAttribute("uv");
    vol.deleteAttribute("normal");
    const volCount = vol.getAttribute("position").count;
    vols.push(vol);
    spans.push({ room, start: at, count, lineStart: lineParts.length / 3, lineCount: ln.length / 3, volStart: volAt, volCount });
    lineParts.push(...ln);
    at += count;
    volAt += volCount;
  }
  if (!parts.length) return null;
  const mesh = mergeGeometries(parts, false);
  mesh.computeVertexNormals();
  mesh.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(mesh.getAttribute("position").count * 3), 3));
  const lines = segmentsGeometry(lineParts);
  lines.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(lineParts.length), 3));
  const volume = mergeGeometries(vols, false);
  volume.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(volume.getAttribute("position").count * 3), 3));
  return { mesh, lines, volume, spans };
}

export class XrayScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  private composer: EffectComposer | null = null;
  private bloomPass: UnrealBloomPass | null = null;
  private floors: FloorParts[] = [];
  private mats: Record<string, THREE.Material> = {};
  private shellMat: LineMaterial;
  private sun: THREE.DirectionalLight;
  private ambient: THREE.AmbientLight;
  private frame = 0;
  private tween: { from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3]; t0: number; ms: number } | null = null;
  private explode = { now: 0, want: 0 };
  private cut: number | null = null;
  private center = new THREE.Vector3();
  private size = 10;
  private ray = new THREE.Raycaster();
  private states = new Map<number, RoomState>();
  private fps = { frames: 0, since: performance.now(), value: 0, slow: 0 };
  private ifcGroup: THREE.Group | null = null;
  private floorU: FloorUniforms = { uOff: { value: new Float32Array(MAX_MERGED_FLOORS) }, uVis: { value: new Float32Array(MAX_MERGED_FLOORS).fill(1) } };
  private merged: THREE.Object3D[] = []; // the building's structure, one object per material
  private preset: Preset = "iso";
  private touched = false; // the user moved the camera: a resize keeps their view
  private ifcLinked: { el: IfcElement; mesh: THREE.Mesh }[] = [];
  private ifcPickables: THREE.Mesh[] = [];
  mode: Mode = "xray";
  roomsFirst = false; // the shell dims, the rooms glow stronger (the client portal's default)
  bloom = false;
  autoBloom = true;
  onFrame: ((labels: Label[], fps: number) => void) | null = null;

  constructor(
    readonly canvas: HTMLCanvasElement,
    readonly building: Building,
    opts: { mode?: Mode; bloom?: boolean; autoTurn?: boolean },
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.autoRotateSpeed = 0.6;
    this.controls.autoRotate = !!opts.autoTurn;
    canvas.addEventListener("pointerdown", () => (this.controls.autoRotate = false), { once: true });
    for (const ev of ["pointerdown", "wheel"]) canvas.addEventListener(ev, () => (this.touched = true), { once: true, passive: true });
    this.shellMat = new LineMaterial({ color: 0xffffff, linewidth: 2, transparent: true, opacity: 0.9 });
    this.ambient = new THREE.AmbientLight(0xffffff, 0.7);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.2);
    this.scene.add(this.ambient, this.sun);
    this.build();
    this.setMode(opts.mode ?? "xray");
    this.setBloom(opts.bloom ?? false, true);
    this.resize();
    this.view("iso", false);
    this.loop();
  }

  private build(): void {
    const b = this.building;
    const slab = b.settings.slab_m;
    const byType = new Map<string, TypeGeo>();
    const sorted = [...b.floors].sort((a, c) => a.level - c.level);
    const roomsBy = new Map<number, XRoom[]>();
    for (const r of b.rooms) roomsBy.set(r.level, [...(roomsBy.get(r.level) ?? []), r]);
    const m = (k: string, mat: THREE.Material) => (this.mats[k] = mat);
    m("line", new THREE.LineBasicMaterial({ transparent: true, depthWrite: false }));
    m("face", new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }));
    m("slab", new THREE.MeshStandardMaterial({ transparent: true, roughness: 0.9, side: THREE.DoubleSide }));
    m("glass", new THREE.MeshStandardMaterial({ transparent: true, roughness: 0.15, metalness: 0.1, side: THREE.DoubleSide, depthWrite: false }));
    m("solid", new THREE.MeshStandardMaterial({ roughness: 0.85 }));
    m("rooms", new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, side: THREE.DoubleSide }));
    m("roomLines", new THREE.LineBasicMaterial({ vertexColors: true }));
    m("volume", new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.2, depthWrite: false, side: THREE.DoubleSide }));
    m("late", new THREE.LineBasicMaterial({ color: LATE_COLOR }));
    m("cutFace", new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.14, depthWrite: false, side: THREE.DoubleSide }));
    let all: THREE.Box3 | null = null;
    const merge = sorted.length <= MAX_MERGED_FLOORS;
    const parts: Record<"line" | "slab" | "glass" | "face", THREE.BufferGeometry[]> = { line: [], slab: [], glass: [], face: [] };
    sorted.forEach((f, index) => {
      const t = f.type ? b.types[f.type] : undefined;
      const group = new THREE.Group();
      group.position.y = f.elevation_m;
      group.userData.level = f.level;
      if (t && t.outline.length > 2) {
        const key = `${f.type}@${f.height_m.toFixed(3)}`;
        let g = byType.get(key);
        if (!g) {
          g = typeGeometry(t, f.height_m, slab, b.settings.riser_m);
          byType.set(key, g);
        }
        const add = (obj: THREE.Object3D, role: string) => {
          obj.userData.role = role;
          group.add(obj);
        };
        const cut = new THREE.Mesh(g.cutFace, this.mats.cutFace);
        cut.visible = false; // the floor's face, shown when the floor is opened (cutaway)
        add(cut, "cutface");
        const shell = new LineSegments2(g.shell, this.shellMat);
        add(shell, "shell");
        if (merge) {
          // the slab, walls, columns, beams and cores: into the building's merged objects
          const y = f.elevation_m;
          parts.slab.push(floorCopy(g.slab, y, index, true));
          for (const l of [g.slabEdges, g.walls, g.colEdges, g.detailEdges]) if (l) parts.line.push(floorCopy(l, y, index, false));
          if (g.wallFaces) parts.glass.push(floorCopy(g.wallFaces, y, index, true));
          for (const m2 of [g.cols, g.detail]) if (m2) parts.face.push(floorCopy(m2, y, index, true));
        } else {
          add(new THREE.Mesh(g.slab, this.mats.slab), "slab");
          add(new THREE.LineSegments(g.slabEdges, this.mats.line), "line");
          if (g.walls) add(new THREE.LineSegments(g.walls, this.mats.line), "line");
          if (g.wallFaces) add(new THREE.Mesh(g.wallFaces, this.mats.glass), "glass");
          if (g.cols) add(new THREE.Mesh(g.cols, this.mats.face), "column");
          if (g.colEdges) add(new THREE.LineSegments(g.colEdges, this.mats.line), "line");
          if (g.detail) add(new THREE.Mesh(g.detail, this.mats.face), "column");
          if (g.detailEdges) add(new THREE.LineSegments(g.detailEdges, this.mats.line), "line");
        }
      }
      const rg = roomsGeometry(roomsBy.get(f.level) ?? [], f, slab);
      let rooms: THREE.Mesh | null = null;
      let roomLines: THREE.LineSegments | null = null;
      let volume: THREE.Mesh | null = null;
      if (rg) {
        rooms = new THREE.Mesh(rg.mesh, this.mats.rooms);
        rooms.userData.role = "rooms";
        roomLines = new THREE.LineSegments(rg.lines, this.mats.roomLines);
        roomLines.userData.role = "roomLines";
        volume = new THREE.Mesh(rg.volume, this.mats.volume);
        volume.userData.role = "volume";
        group.add(rooms, roomLines, volume);
      }
      const late = new THREE.LineSegments(new THREE.BufferGeometry(), this.mats.late);
      late.userData.role = "late";
      group.add(late);
      this.scene.add(group);
      this.floors.push({ floor: f, index, group, rooms, roomLines, volume, late, spans: rg?.spans ?? [] });
      group.updateMatrixWorld(true);
      const bb = new THREE.Box3().setFromObject(group);
      if (!bb.isEmpty()) all = all ? all.union(bb) : bb;
    });
    if (merge) {
      for (const k of ["line", "slab", "glass", "face"] as const) {
        hookFloors(this.mats[k], this.floorU);
        const geo = mergeFloors(parts[k]);
        if (!geo) continue;
        const obj = k === "line" ? new THREE.LineSegments(geo, this.mats.line) : new THREE.Mesh(geo, this.mats[k]);
        obj.userData.role = k === "face" ? "column" : k;
        obj.frustumCulled = false; // its floors move apart in the explode view
        this.scene.add(obj);
        this.merged.push(obj);
        const bb = new THREE.Box3().setFromObject(obj);
        if (!bb.isEmpty()) all = all ? all.union(bb) : bb;
      }
    }
    const box3 = all ?? new THREE.Box3(new THREE.Vector3(-10, 0, -10), new THREE.Vector3(10, 10, 10));
    box3.getCenter(this.center);
    this.size = box3.getSize(new THREE.Vector3()).length();
    this.sun.position.set(this.center.x + this.size, this.center.y + this.size, this.center.z + this.size * 0.6);
    this.sun.target.position.copy(this.center);
    this.scene.add(this.sun.target);
    const sc = this.sun.shadow.camera as THREE.OrthographicCamera;
    sc.left = sc.bottom = -this.size;
    sc.right = sc.top = this.size;
    sc.far = this.size * 4;
    this.sun.shadow.mapSize.set(2048, 2048);
  }

  /** The look: X-ray (dark, fine bright lines, see-through), Status (light, solid colours) or
   *  Realistic (concrete and glass, soft shadows). */
  setMode(mode: Mode): void {
    this.mode = mode;
    const p = PALETTE[mode];
    this.scene.background = new THREE.Color(p.bg);
    this.scene.fog = p.fog ? new THREE.FogExp2(p.bg, p.fog * (60 / Math.max(this.size, 30))) : null;
    const line = this.mats.line as THREE.LineBasicMaterial;
    line.color.set(p.line);
    line.opacity = p.lineOpacity * (this.roomsFirst ? 0.4 : 1);
    line.blending = mode === "xray" ? THREE.AdditiveBlending : THREE.NormalBlending;
    this.shellMat.color.set(p.shell);
    this.shellMat.opacity = (mode === "xray" ? 0.55 : 0.8) * (this.roomsFirst ? 0.4 : 1);
    const cutFace = this.mats.cutFace as THREE.MeshBasicMaterial;
    cutFace.color.set(mode === "xray" ? "#5fb8ff" : mode === "status" ? "#c8cfd3" : p.slab);
    cutFace.opacity = mode === "xray" ? 0.14 : 0.35;
    const face = this.mats.face as THREE.MeshBasicMaterial;
    face.color.set(mode === "real" ? p.slab : p.face);
    face.opacity = mode === "real" ? 0.95 : p.faceOpacity * 2;
    const slab = this.mats.slab as THREE.MeshStandardMaterial;
    slab.color.set(p.slab);
    slab.opacity = mode === "real" ? 1 : mode === "status" ? 0.16 : 0.06;
    slab.depthWrite = mode === "real";
    const glass = this.mats.glass as THREE.MeshStandardMaterial;
    glass.color.set(p.glass);
    glass.opacity = mode === "real" ? 0.32 : mode === "status" ? 0.06 : 0.035;
    const rooms = this.mats.rooms as THREE.MeshBasicMaterial;
    rooms.opacity = p.roomOpacity;
    const volume = this.mats.volume as THREE.MeshBasicMaterial;
    volume.opacity = (mode === "xray" ? 0.36 : mode === "status" ? 0.55 : 0.12) * (this.roomsFirst ? 1.5 : 1);
    rooms.transparent = p.roomOpacity < 1;
    rooms.depthWrite = p.roomOpacity >= 1;
    this.ambient.intensity = mode === "real" ? 0.55 : 0.9;
    this.sun.intensity = mode === "real" ? 1.6 : 0.8;
    this.renderer.shadowMap.enabled = mode === "real";
    this.sun.castShadow = mode === "real";
    const shade = (o: THREE.Object3D) => {
      if (o instanceof THREE.Mesh) {
        o.castShadow = mode === "real" && o.userData.role !== "glass";
        o.receiveShadow = mode === "real";
      }
    };
    for (const f of this.floors) f.group.traverse(shade);
    for (const o of this.merged) shade(o);
    for (const k of Object.keys(this.mats)) this.mats[k].needsUpdate = true;
    this.paint();
    if (this.bloomPass) this.bloomPass.enabled = this.bloom && mode === "xray";
  }

  setRoomsFirst(on: boolean): void {
    this.roomsFirst = on;
    this.setMode(this.mode);
  }

  /** The glow on the edges (X-ray only); weak devices turn it off by themselves. */
  setBloom(on: boolean, auto = this.autoBloom): void {
    this.bloom = on;
    this.autoBloom = auto;
    if (on && !this.composer) {
      this.composer = new EffectComposer(this.renderer);
      this.composer.addPass(new RenderPass(this.scene, this.camera));
      this.bloomPass = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.5, 0.35, 0.25);
      this.composer.addPass(this.bloomPass);
      this.composer.addPass(new OutputPass());
      this.resize();
    }
    if (this.bloomPass) this.bloomPass.enabled = on && this.mode === "xray";
  }

  /** The status of each room (by its node), painted into the room colours. */
  setStates(states: Map<number, RoomState>, links?: Record<string, number>): void {
    this.states = states;
    this.paint();
    if (links) this.paintIfc(links);
  }

  private paint(): void {
    const c = new THREE.Color();
    const bright = this.mode === "xray" ? 1.25 : 1;
    for (const f of this.floors) {
      if (!f.rooms || !f.roomLines) continue;
      const col = f.rooms.geometry.getAttribute("color") as THREE.BufferAttribute;
      const vcol = f.volume?.geometry.getAttribute("color") as THREE.BufferAttribute | undefined;
      const lcol = f.roomLines.geometry.getAttribute("color") as THREE.BufferAttribute;
      const late: number[] = [];
      for (const s of f.spans) {
        const st = this.states.get(s.room.node_id) ?? { category: "not_started", late: false };
        c.set(STATUS_COLORS[st.category]);
        // in the dark view the greys would glow white: not started stays dim, no scope dimmer
        if (this.mode === "xray" && st.category === "not_started") c.multiplyScalar(0.4);
        if (this.mode === "xray" && st.category === "none") c.multiplyScalar(0.2);
        if (s.room.kind === "terrace") c.multiplyScalar(this.mode === "xray" ? 0.3 : 0.75); // a light fill: its outline carries the colour
        for (let i = s.start; i < s.start + s.count; i++) col.setXYZ(i, c.r, c.g, c.b);
        if (vcol) for (let i = s.volStart; i < s.volStart + s.volCount; i++) vcol.setXYZ(i, c.r, c.g, c.b);
        const lc = (s.room.kind === "terrace" ? new THREE.Color(STATUS_COLORS[st.category]) : c.clone()).multiplyScalar(bright * (this.roomsFirst ? 1.3 : 1));
        for (let i = s.lineStart; i < s.lineStart + s.lineCount; i++) lcol.setXYZ(i, lc.r, lc.g, lc.b);
        if (st.late) {
          const lines = f.roomLines.geometry.getAttribute("position") as THREE.BufferAttribute;
          for (let i = s.lineStart; i < s.lineStart + s.lineCount; i++) late.push(lines.getX(i), lines.getY(i) + 0.02, lines.getZ(i));
        }
      }
      col.needsUpdate = true;
      lcol.needsUpdate = true;
      if (vcol) vcol.needsUpdate = true;
      f.late.geometry.dispose();
      f.late.geometry = segmentsGeometry(late);
    }
  }

  /** The client's BIM file instead of (or with) the drawing's building: unlinked elements as
   *  faint faces with edges (one merged mesh), linked ones in their place's status colour. */
  setIfc(elements: IfcElement[] | null, links: Record<string, number> = {}): void {
    if (this.ifcGroup) {
      this.scene.remove(this.ifcGroup);
      this.ifcGroup.traverse((o) => (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) && o.geometry.dispose());
      this.ifcGroup = null;
    }
    this.ifcLinked = [];
    this.ifcPickables = [];
    for (const f of this.floors) f.group.visible = !elements;
    for (const o of this.merged) o.visible = !elements;
    if (!elements) return;
    const ifcGlass = (this.mats.glass as THREE.MeshStandardMaterial).clone(); // without the floors' shader hook
    const ifcLine = (this.mats.line as THREE.LineBasicMaterial).clone();
    ifcGlass.onBeforeCompile = ifcLine.onBeforeCompile = () => undefined;
    const g = new THREE.Group();
    const loose: THREE.BufferGeometry[] = [];
    for (const el of elements) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(el.positions, 3));
      geo.setIndex(new THREE.BufferAttribute(el.indices, 1));
      geo.computeVertexNormals();
      if (links[String(el.expressID)] != null) {
        const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85, side: THREE.DoubleSide }));
        mesh.userData.el = el;
        g.add(mesh);
        this.ifcLinked.push({ el, mesh });
        this.ifcPickables.push(mesh);
      } else {
        const mesh = new THREE.Mesh(geo, ifcGlass);
        mesh.userData.el = el;
        this.ifcPickables.push(mesh);
        mesh.visible = false; // picked only; drawn merged below
        g.add(mesh);
        loose.push(geo.clone());
      }
    }
    const all = merged(loose);
    if (all) {
      g.add(new THREE.Mesh(all, ifcGlass));
      g.add(new THREE.LineSegments(new THREE.EdgesGeometry(all, 25), ifcLine));
    }
    this.ifcGroup = g;
    this.scene.add(g);
    const box = new THREE.Box3().setFromObject(g);
    if (!box.isEmpty()) {
      box.getCenter(this.center);
      this.size = box.getSize(new THREE.Vector3()).length();
    }
    this.paintIfc(links);
    this.view("iso");
  }

  paintIfc(links: Record<string, number>): void {
    for (const { el, mesh } of this.ifcLinked) {
      const st = this.states.get(links[String(el.expressID)]);
      (mesh.material as THREE.MeshBasicMaterial).color.set(STATUS_COLORS[st?.category ?? "not_started"]);
    }
  }

  /** The IFC element under the pointer (express id), if any. */
  pickIfc(clientX: number, clientY: number): IfcElement | null {
    if (!this.ifcPickables.length) return null;
    const r = this.canvas.getBoundingClientRect();
    this.ray.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), this.camera);
    const hits = this.ray.intersectObjects(this.ifcPickables.map((m) => Object.assign(m, { visible: true })), false);
    for (const m of this.ifcPickables) if (!this.ifcLinked.some((l) => l.mesh === m)) m.visible = false;
    return (hits[0]?.object.userData.el as IfcElement) ?? null;
  }

  /** Floor cutaway: the other floors are hidden and the camera looks down on this one. */
  setCutaway(level: number | null): void {
    this.cut = level;
    // the opened floor alone (the floors above hidden, and the ones below, seen through, too)
    for (const f of this.floors) {
      f.group.visible = level == null || f.floor.level === level;
      if (f.index < MAX_MERGED_FLOORS) this.floorU.uVis.value[f.index] = f.group.visible ? 1 : 0;
      f.group.traverse((o) => o.userData.role === "cutface" && (o.visible = level != null && f.floor.level === level));
    }
    if (level == null) return;
    const f = this.floors.find((x) => x.floor.level === level);
    if (!f) return;
    // from above, on the whole floor (its outline, face and columns read as a floor), fitted to
    // the screen's width and height
    const y = f.group.position.y;
    const t = f.floor.type ? this.building.types[f.floor.type] : undefined;
    const pts = t?.outline.length ? t.outline : f.spans.flatMap((s) => s.room.outline);
    const b = pts.length ? bounds(pts) : null;
    const target = b ? v3((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, y) : new THREE.Vector3(this.center.x, y, this.center.z);
    const fov = (this.camera.fov * Math.PI) / 360;
    const wide = b ? (b.maxX - b.minX) / Math.max(0.3, this.camera.aspect) : this.size;
    const deep = b ? b.maxY - b.minY : this.size;
    const span = (Math.max(wide, deep) * 0.6) / Math.tan(fov) + 5;
    this.moveTo(new THREE.Vector3(target.x, y + span, target.z + span * 0.08), target);
  }

  setExplode(on: boolean): void {
    if ((on ? 1 : 0) === this.explode.want) return; // nothing to do (off at the start)
    this.explode.want = on ? 1 : 0;
    // the spread building is taller: the camera steps back to fit it (and its centre rises)
    const gap = Math.max(3, this.size / 25);
    const rise = on ? ((this.floors.length - 1) * gap) / 2 : 0;
    const c = this.center.clone().add(new THREE.Vector3(0, rise, 0));
    this.moveTo(this.isoFrom(c, on ? 1.4 : 1), c);
  }

  /** The iso camera position for a centre: further back on a narrow (upright) screen. */
  private isoFrom(c: THREE.Vector3, scale = 1): THREE.Vector3 {
    const d = this.size * 0.82 * scale * Math.max(1, Math.pow(1 / this.camera.aspect, 1.6));
    return new THREE.Vector3(c.x + d * 0.75, c.y + d * 0.55, c.z + d * 0.85);
  }

  /** Reset, Top, Front, Iso: an eased move of the camera. */
  view(preset: Preset, animate = true): void {
    this.preset = preset;
    const d = this.size * 0.82 * Math.max(1, Math.pow(1 / this.camera.aspect, 1.6)); // a phone held upright: further back
    const c = this.center;
    const pos =
      preset === "top"
        ? new THREE.Vector3(c.x, c.y + d * 1.2, c.z + 0.01)
        : preset === "front"
          ? new THREE.Vector3(c.x, c.y, c.z + d * 1.15)
          : this.isoFrom(c);
    if (animate) this.moveTo(pos, c.clone());
    else {
      this.camera.position.copy(pos);
      this.controls.target.copy(c);
      this.controls.update();
    }
  }

  private moveTo(pos: THREE.Vector3, target: THREE.Vector3): void {
    this.tween = { from: [this.camera.position.clone(), this.controls.target.clone()], to: [pos, target], t0: performance.now(), ms: 700 };
  }

  /** The room under the pointer (client coordinates), if any. */
  pick(clientX: number, clientY: number): XRoom | null {
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(ndc, this.camera);
    const meshes = this.floors.filter((f) => f.rooms && f.group.visible).map((f) => f.rooms!);
    const hit = this.ray.intersectObjects(meshes, false)[0];
    if (!hit || hit.faceIndex == null) return null;
    const f = this.floors.find((x) => x.rooms === hit.object)!;
    const v = hit.faceIndex * 3;
    return f.spans.find((s) => v >= s.start && v < s.start + s.count)?.room ?? null;
  }

  resize(): void {
    const w = this.canvas.clientWidth || 800;
    const h = this.canvas.clientHeight || 600;
    this.renderer.setSize(w, h, false);
    const was = this.camera.aspect;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    // laid out after it was made (a tab, a phone): frame the building again until the user moves it
    if (!this.touched && this.cut == null && Math.abs(was - this.camera.aspect) > 0.05) this.view(this.preset, false);
    this.shellMat.resolution.set(w, h);
    this.composer?.setSize(w, h);
    this.bloomPass?.setSize(w / 2, h / 2);
  }

  private labels(): Label[] {
    if (this.cut == null) return [];
    const f = this.floors.find((x) => x.floor.level === this.cut);
    if (!f) return [];
    const r = this.canvas.getBoundingClientRect();
    const out: Label[] = [];
    for (const s of f.spans) {
      const [x, y] = centroid(s.room.outline);
      const p = v3(x, y, f.group.position.y + 0.3).project(this.camera);
      if (p.z > 1) continue;
      const area = s.room.area_sqm ?? polygonArea(s.room.outline);
      out.push({ text: s.room.name, sub: `${area.toFixed(2)} sqm`, x: ((p.x + 1) / 2) * r.width, y: ((1 - p.y) / 2) * r.height, nodeId: s.room.node_id });
    }
    return out;
  }

  private loop = (): void => {
    this.frame = requestAnimationFrame(this.loop);
    const now = performance.now();
    if (this.tween) {
      const k = Math.min(1, (now - this.tween.t0) / this.tween.ms);
      const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
      this.camera.position.lerpVectors(this.tween.from[0], this.tween.to[0], e);
      this.controls.target.lerpVectors(this.tween.from[1], this.tween.to[1], e);
      if (k >= 1) this.tween = null;
    }
    if (Math.abs(this.explode.now - this.explode.want) > 1e-3) {
      this.explode.now += (this.explode.want - this.explode.now) * 0.12;
      for (const f of this.floors) {
        const off = explodeOffset(f.index, this.explode.now, Math.max(3, this.size / 25));
        f.group.position.y = f.floor.elevation_m + off;
        if (f.index < MAX_MERGED_FLOORS) this.floorU.uOff.value[f.index] = off;
      }
    }
    this.controls.update();
    if (this.composer && this.bloomPass?.enabled) this.composer.render();
    else this.renderer.render(this.scene, this.camera);
    // frames per second; a device that cannot keep 30 with the glow on loses the glow
    this.fps.frames += 1;
    if (now - this.fps.since >= 1000) {
      this.fps.value = (this.fps.frames * 1000) / (now - this.fps.since);
      this.fps.frames = 0;
      this.fps.since = now;
      this.fps.slow = this.fps.value < 30 ? this.fps.slow + 1 : 0;
      if (this.autoBloom && this.bloom && this.fps.slow >= 3) this.setBloom(false, true);
      (window as unknown as { __xrayFps?: number }).__xrayFps = this.fps.value;
    }
    this.onFrame?.(this.labels(), this.fps.value);
  };

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.controls.dispose();
    this.scene.traverse((o) => {
      if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) o.geometry.dispose();
    });
    for (const m of Object.values(this.mats)) m.dispose();
    this.shellMat.dispose();
    this.composer?.dispose();
    this.renderer.dispose();
  }
}
