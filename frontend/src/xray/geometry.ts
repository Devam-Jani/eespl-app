// The X-ray building's maths, pure (tested without WebGL): plan outlines in metres (x east,
// y north) raised into floors, rooms, columns, beams and stairs. three.js takes x as X, y as -Z,
// and the height as Y.
import type { Category, NodeStatus } from "../pages/site/three/colors";
import { categoryOf } from "../pages/site/three/colors";

export type P = [number, number];
export type XFloor = { level: number; node_id: number | null; name: string; type: string | null; elevation_m: number; height_m: number };
export type XCore = { kind: "stair" | "lift"; outline: P[]; risers: number | null };
export type XType = { name: string; outline: P[]; area_sqm: number; walls: number[][]; columns: number[][]; beams: number[][]; cores: XCore[] };
export type XRoom = {
  node_id: number;
  key: string | null;
  level: number;
  kind: string;
  name: string;
  label: string | null;
  outline: P[];
  area_sqm: number | null;
  sunk_m: number;
  raise_m: number;
  wp_height_m: number | null;
};
export type Building = {
  version: number;
  schematic: false;
  settings: { floor_height_m: number; slab_m: number; plinth_m: number; riser_m: number; bloom: "auto" | "on" | "off"; ifc: boolean };
  levels: { source: "section" | "default"; note: string | null };
  floors: XFloor[];
  types: Record<string, XType>;
  rooms: XRoom[];
  ifc_links: Record<string, number>;
  ifc?: { url: string; filename: string | null; rev_no: number | null; size_mb: number | null; max_mb: number } | null;
  source?: { cad_file_id: number | null; note: string | null; changes: unknown; by: string | null; at: string | null };
};
/** [name, planned_start, planned_end, actual_start, actual_end, status, hold_point, certified_on] */
export type TimelineRow = [string, string | null, string | null, string | null, string | null, string, boolean, string | null];

/** Shoelace area of a plan outline (square metres). */
export function polygonArea(pts: P[]): number {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i === 0 ? pts.length - 1 : i - 1];
    const [x2, y2] = pts[i];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

export function bounds(pts: P[]): { minX: number; minY: number; maxX: number; maxY: number } {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) };
}

export function centroid(pts: P[]): P {
  const b = bounds(pts);
  return [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
}

/** A floor's slab: the plan outline, its top at the floor's level, slab_m thick. */
export function slabOf(outline: P[], floor: XFloor, slab_m: number): { area: number; top: number; bottom: number } {
  return { area: polygonArea(outline), top: floor.elevation_m, bottom: floor.elevation_m - slab_m };
}

/** A room raised on its floor: its floor drops by the sunk depth; the waterproofing goes up its
 *  walls by the band height from that floor (none: a 50 mm skirting so the room still reads). */
export function roomSolid(room: XRoom, floor: XFloor): { bottom: number; top: number; band: number; area: number } {
  const bottom = floor.elevation_m - (room.sunk_m || 0);
  const band = room.wp_height_m != null ? Math.min(room.wp_height_m, floor.height_m) : 0.05;
  return { bottom, top: bottom + band + (room.sunk_m || 0), band, area: polygonArea(room.outline) };
}

/** The floors of the building, bottom up, each with the type it is built from. */
export function floorsOfType(b: Pick<Building, "floors">, typeKey: string): XFloor[] {
  return b.floors.filter((f) => f.type === typeKey).sort((a, c) => a.level - c.level);
}

/** Every column on every floor: a floor of a type repeats that type's columns, from its slab
 *  bottom up to the next floor's slab. */
export function columnsPerFloor(b: Pick<Building, "floors" | "types">): { level: number; x: number; y: number; w: number; d: number; bottom: number; height: number }[] {
  const out: { level: number; x: number; y: number; w: number; d: number; bottom: number; height: number }[] = [];
  for (const f of b.floors) {
    const t = f.type ? b.types[f.type] : undefined;
    if (!t) continue;
    for (const [x, y, w, d] of t.columns) out.push({ level: f.level, x, y, w, d, bottom: f.elevation_m, height: f.height_m });
  }
  return out;
}

export type Step = { x: number; y: number; w: number; d: number; bottom: number; h: number };

/** The steps of a dog-leg stair in its core, for one floor: risers from the floor height (default
 *  floor height / riser_m, rounded, even), two flights side by side along the core's long side,
 *  the landing at half height. Plan rectangle of each step, its bottom and rise. */
export function stairSteps(core: P[], floorHeight: number, riserM = 0.15, risers: number | null = null): Step[] {
  const b = bounds(core);
  const along = b.maxX - b.minX >= b.maxY - b.minY ? "x" : "y";
  const long = along === "x" ? b.maxX - b.minX : b.maxY - b.minY;
  const wide = along === "x" ? b.maxY - b.minY : b.maxX - b.minX;
  let n = risers ?? Math.round(floorHeight / riserM);
  if (n % 2) n += 1;
  const rise = floorHeight / n;
  const perFlight = n / 2;
  const landing = Math.min(1.2, long * 0.25);
  const tread = (long - landing) / perFlight;
  const half = wide / 2;
  const out: Step[] = [];
  for (let i = 0; i < n; i++) {
    const second = i >= perFlight;
    const k = second ? i - perFlight : i;
    // first flight goes away along the long side, second comes back on the other half
    const s = second ? long - landing - (k + 1) * tread : k * tread;
    const offsetWide = second ? half : 0;
    const box =
      along === "x"
        ? { x: b.minX + s + tread / 2, y: b.minY + offsetWide + half / 2, w: tread, d: half }
        : { x: b.minX + offsetWide + half / 2, y: b.minY + s + tread / 2, w: half, d: tread };
    out.push({ ...box, bottom: i * rise, h: rise });
  }
  return out;
}

/** How far a floor moves up in the explode view: its index times the gap. */
export function explodeOffset(index: number, amount: number, gap = 4): number {
  return index * gap * amount;
}

const DONE = new Set(["done", "certified"]);

/** The status of a place on a past date, from its tasks' stored dates (no forecast: dates after
 *  today are today). Today itself is the live status (categoryOf of the node). */
export function statusAt(timeline: TimelineRow[], on: string, today: string, live?: NodeStatus): { category: Exclude<Category, "rollup">; late: boolean; percent: number } {
  if (on >= today && live) return { category: categoryOf(live), late: live.is_late, percent: live.percent };
  if (!timeline.length) return { category: live?.has_scope ? "not_started" : "none", late: false, percent: 0 };
  let done = 0;
  let started = 0;
  let hold = false;
  let late = false;
  for (const [, , plannedEnd, actualStart, actualEnd, status, holdPoint, certified] of timeline) {
    const finished = !!actualEnd && actualEnd <= on && DONE.has(status);
    if (finished) done += 1;
    else if (actualStart && actualStart <= on) started += 1;
    if (finished && holdPoint && (!certified || certified > on)) hold = true;
    if (!finished && plannedEnd && plannedEnd < on) late = true;
  }
  const percent = Math.round((done / timeline.length) * 100);
  if (hold) return { category: "hold", late, percent };
  if (done === timeline.length) return { category: "done", late: false, percent };
  if (done || started) return { category: "progress", late, percent };
  return { category: "not_started", late, percent };
}

/** The first and last dates the replay can show: the earliest task start up to today. */
export function replayRange(timelines: TimelineRow[][], today: string): [string, string] {
  let first = today;
  for (const tl of timelines)
    for (const t of tl) {
      for (const d of [t[1], t[3]]) if (d && d < first) first = d;
    }
  return [first, today];
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/** Whether to glow: the setting, else on unless the device looks weak (few cores, a phone). */
export function bloomOn(setting: "auto" | "on" | "off", cores: number, phone: boolean): boolean {
  if (setting !== "auto") return setting === "on";
  return cores > 4 && !phone;
}
