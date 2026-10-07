/**
 * Block model of a site from its node tree: pure maths, no WebGL (unit-tested in layout.test.ts).
 *
 * Units are metres; y is up, the ground (G) is at y = 0.
 * - Towers (also towers inside a wing) stand side by side along x, in sort_order, TOWER_GAP apart.
 * - A tower's floors and basements stack by level_no (B2 = -2 … G = 0 … 14), one FLOOR_H each;
 *   basements are below the ground. Floors without level_no are numbered in order.
 * - Inside a floor its children (flats, or rooms directly on the floor) sit in a square-ish grid;
 *   a flat is sized from area_sqm (a square of that area) or a default. All floors of a tower share
 *   the largest floor's footprint.
 * - Inside a flat its rooms (toilet, kitchen, balcony…) stand in a row along the flat's front, sized
 *   from area_sqm or a default per kind, shrunk to fit.
 * - On top: the terrace slab, with its OH tanks standing on it. Beside the tower (+x side): lift
 *   pits, UG tank and STP below the ground, a swimming pool sunk into it. Under the lowest
 *   basement: the raft. Around the basements: thin retaining walls (4 boxes for one node). A podium is
 *   a wide slab at the ground around the tower.
 * - Site-level places (not under a tower) follow the towers in a row; a site-level raft, podium or
 *   retaining wall spans all the towers.
 * Every node gets exactly one box, except a retaining wall (4); towers and wings are invisible
 * "group" boxes enclosing what they hold (used for labels and hovering).
 */

export type LayoutNode = {
  id: number;
  parent_id: number | null;
  kind: string;
  name: string;
  level_no: number | null;
  area_sqm: number | null;
  sort_order: number;
};

export type Role = "group" | "floor" | "flat" | "room" | "slab" | "element";

export type Box = {
  node_id: number;
  kind: string;
  role: Role;
  /** centre */
  x: number;
  y: number;
  z: number;
  /** size along x, y, z */
  w: number;
  h: number;
  d: number;
  level: number | null;
  tower_id: number | null;
  floor_id: number | null;
  /** below the ground: shown with "Below ground" */
  below: boolean;
};

export const FLOOR_H = 3.2;
export const TOWER_GAP = 8;
const GAP = 0.6;
const FLAT_DEFAULT = 8;
const FLOOR_DEFAULT: [number, number] = [16, 12];
const ROOM_DEFAULT: Record<string, [number, number]> = {
  toilet: [2.2, 1.8],
  kitchen: [3, 2.4],
  balcony: [3, 1.4],
};
const ELEMENT_SIZE: Record<string, [number, number, number]> = {
  lift_pit: [2.5, 2.5, 2.5],
  ug_tank: [6, 3, 4],
  oh_tank: [3, 2.4, 3],
  stp: [5, 2.5, 4],
  swimming_pool: [8, 1.5, 4],
  other: [3, 2.5, 3],
};
const FLOOR_KINDS = new Set(["floor", "basement"]);
const BELOW_KINDS = new Set(["lift_pit", "ug_tank", "stp", "raft", "retaining_wall"]);

function side(area: number | null, fallback: number): number {
  return area && area > 0 ? Math.max(1, Math.sqrt(area)) : fallback;
}

function roomSize(n: LayoutNode): [number, number] {
  if (n.area_sqm && n.area_sqm > 0) {
    const s = Math.sqrt(n.area_sqm);
    return [s, s];
  }
  return ROOM_DEFAULT[n.kind] ?? [2.5, 2.5];
}

function grid(n: number): [number, number] {
  const cols = Math.max(1, Math.ceil(Math.sqrt(n)));
  return [cols, Math.max(1, Math.ceil(n / cols))];
}

export function layout(nodes: LayoutNode[]): Box[] {
  const byParent = new Map<number | null, LayoutNode[]>();
  for (const n of nodes) {
    const list = byParent.get(n.parent_id) ?? [];
    list.push(n);
    byParent.set(n.parent_id, list);
  }
  for (const list of byParent.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
  const kids = (id: number | null) => byParent.get(id) ?? [];
  const boxes: Box[] = [];
  const add = (b: Omit<Box, "tower_id" | "floor_id" | "level" | "below"> & Partial<Box>) =>
    boxes.push({ tower_id: null, floor_id: null, level: null, below: false, ...b });

  // towers in order (a wing's towers in its place), and the site-level places
  const towers: LayoutNode[] = [];
  const wings: { wing: LayoutNode; towers: LayoutNode[] }[] = [];
  const siteLevel: LayoutNode[] = [];
  for (const root of kids(null)) {
    if (root.kind === "tower") towers.push(root);
    else if (root.kind === "wing") {
      const inside = kids(root.id).filter((k) => k.kind === "tower");
      wings.push({ wing: root, towers: inside });
      towers.push(...inside);
      siteLevel.push(...kids(root.id).filter((k) => k.kind !== "tower"));
    } else siteLevel.push(root);
  }

  let cursor = 0;
  let minLevelAll = 0;
  const extents: { id: number; x0: number; x1: number; d: number }[] = [];

  for (const tower of towers) {
    const children = kids(tower.id);
    const floors = children.filter((c) => FLOOR_KINDS.has(c.kind));
    // levels: level_no, else basements count down to B1 and floors count up from G
    const basements = floors.filter((f) => f.kind === "basement");
    let up = 0;
    const level = new Map<number, number>();
    floors.forEach((f) => {
      if (f.level_no !== null && f.level_no !== undefined) level.set(f.id, f.level_no);
      else if (f.kind === "basement") level.set(f.id, -(basements.length - basements.indexOf(f)));
      else level.set(f.id, up++);
    });
    // footprint: the largest floor's grid of flats / rooms
    let W = 10;
    let D = 8;
    const cells = new Map<number, { cols: number; cw: number; cd: number; items: LayoutNode[] }>();
    for (const f of floors) {
      const items = kids(f.id);
      if (!items.length) {
        const s = f.area_sqm ? side(f.area_sqm, FLOOR_DEFAULT[0]) : null;
        W = Math.max(W, s ?? FLOOR_DEFAULT[0]);
        D = Math.max(D, s ?? FLOOR_DEFAULT[1]);
        continue;
      }
      const sizes = items.map((i) => (i.kind === "flat" ? [side(i.area_sqm, FLAT_DEFAULT), side(i.area_sqm, FLAT_DEFAULT)] : roomSize(i)));
      const cw = Math.max(...sizes.map((s) => s[0]));
      const cd = Math.max(...sizes.map((s) => s[1]));
      const [cols, rows] = grid(items.length);
      cells.set(f.id, { cols, cw, cd, items });
      W = Math.max(W, cols * cw + (cols + 1) * GAP);
      D = Math.max(D, rows * cd + (rows + 1) * GAP);
    }
    const tx = cursor + W / 2;
    const levels = [...level.values()];
    const minLevel = Math.min(0, ...levels);
    const maxLevel = levels.length ? Math.max(...levels) : -1;
    minLevelAll = Math.min(minLevelAll, minLevel);

    for (const f of floors) {
      const lv = level.get(f.id)!;
      add({ node_id: f.id, kind: f.kind, role: "floor", x: tx, y: lv * FLOOR_H + FLOOR_H / 2, z: 0, w: W, h: FLOOR_H - 0.25, d: D, level: lv, tower_id: tower.id, floor_id: f.id, below: lv < 0 });
      const grid_ = cells.get(f.id);
      if (!grid_) continue;
      grid_.items.forEach((item, i) => {
        const col = i % grid_.cols;
        const row = Math.floor(i / grid_.cols);
        const cx = tx - W / 2 + GAP + col * (grid_.cw + GAP) + grid_.cw / 2;
        const cz = -D / 2 + GAP + row * (grid_.cd + GAP) + grid_.cd / 2;
        const base = lv * FLOOR_H + 0.15;
        if (item.kind !== "flat") {
          const [rw, rd] = roomSize(item);
          add({ node_id: item.id, kind: item.kind, role: "room", x: cx, y: base + (FLOOR_H - 1) / 2, z: cz, w: rw, h: FLOOR_H - 1, d: rd, level: lv, tower_id: tower.id, floor_id: f.id, below: lv < 0 });
          return;
        }
        const fw = side(item.area_sqm, FLAT_DEFAULT);
        const fd = fw;
        add({ node_id: item.id, kind: item.kind, role: "flat", x: cx, y: base + (FLOOR_H - 0.6) / 2, z: cz, w: fw, h: FLOOR_H - 0.6, d: fd, level: lv, tower_id: tower.id, floor_id: f.id, below: lv < 0 });
        // rooms in a row along the flat's front, shrunk to fit
        const rooms = kids(item.id);
        if (!rooms.length) return;
        const sizes = rooms.map(roomSize);
        const avail = fw - 0.6 - 0.3 * (rooms.length - 1);
        const total = sizes.reduce((s, r) => s + r[0], 0);
        const k = Math.min(1, avail / total);
        let rx = cx - fw / 2 + 0.3;
        rooms.forEach((room, j) => {
          const rw = sizes[j][0] * k;
          const rd = Math.min(sizes[j][1], fd * 0.45);
          add({ node_id: room.id, kind: room.kind, role: "room", x: rx + rw / 2, y: base + 0.15 + (FLOOR_H - 1) / 2, z: cz - fd / 2 + 0.3 + rd / 2, w: rw, h: FLOOR_H - 1, d: rd, level: lv, tower_id: tower.id, floor_id: f.id, below: lv < 0 });
          rx += rw + 0.3;
        });
      });
    }

    // the rest of the tower's children
    let besideX = cursor + W + 2;
    let besideZ = -D / 2;
    let besideW = 0;
    const beside = (n: LayoutNode, w: number, h: number, d: number, y: number) => {
      if (besideZ + d > D / 2 && besideZ > -D / 2) {
        besideX += besideW + 1;
        besideZ = -D / 2;
        besideW = 0;
      }
      add({ node_id: n.id, kind: n.kind, role: "element", x: besideX + w / 2, y, z: besideZ + d / 2, w, h, d, tower_id: tower.id, below: y + h / 2 <= 0.01 });
      besideZ += d + 1;
      besideW = Math.max(besideW, w);
    };
    const topY = (maxLevel + 1) * FLOOR_H;
    for (const c of children) {
      if (FLOOR_KINDS.has(c.kind)) continue;
      if (c.kind === "terrace") {
        add({ node_id: c.id, kind: c.kind, role: "slab", x: tx, y: topY + 0.2, z: 0, w: W, h: 0.4, d: D, level: maxLevel + 1, tower_id: tower.id });
        kids(c.id).forEach((t, i) => {
          const [w, h, d] = ELEMENT_SIZE[t.kind] ?? ELEMENT_SIZE.other;
          add({ node_id: t.id, kind: t.kind, role: "element", x: tx + W / 2 - w / 2 - 1 - i * (w + 1), y: topY + 0.4 + h / 2, z: -D / 2 + d / 2 + 1, w, h, d, level: maxLevel + 1, tower_id: tower.id });
        });
      } else if (c.kind === "oh_tank") {
        const [w, h, d] = ELEMENT_SIZE.oh_tank;
        add({ node_id: c.id, kind: c.kind, role: "element", x: tx, y: topY + h / 2, z: 0, w, h, d, tower_id: tower.id });
      } else if (c.kind === "raft") {
        add({ node_id: c.id, kind: c.kind, role: "slab", x: tx, y: minLevel * FLOOR_H - 0.4, z: 0, w: W + 2, h: 0.8, d: D + 2, tower_id: tower.id, below: true });
      } else if (c.kind === "retaining_wall") {
        walls(c, tx, W, D, minLevel, tower.id);
      } else if (c.kind === "podium") {
        add({ node_id: c.id, kind: c.kind, role: "slab", x: tx, y: -0.275, z: 0, w: W + 8, h: 0.65, d: D + 8, tower_id: tower.id });
      } else {
        const [w, h, d] = ELEMENT_SIZE[c.kind] ?? ELEMENT_SIZE.other;
        const y = c.kind === "swimming_pool" ? -h / 2 + 0.05 : BELOW_KINDS.has(c.kind) ? minLevel * FLOOR_H + h / 2 - (minLevel < 0 ? 0 : h) : h / 2;
        beside(c, w, h, d, y);
      }
    }
    const right = Math.max(cursor + W, besideZ > -D / 2 || besideW ? besideX + besideW : cursor + W);
    add({ node_id: tower.id, kind: tower.kind, role: "group", x: (cursor + right) / 2, y: ((maxLevel + 2) * FLOOR_H + minLevel * FLOOR_H) / 2, z: 0, w: right - cursor, h: (maxLevel + 2 - minLevel) * FLOOR_H, d: D, level: null, tower_id: tower.id });
    extents.push({ id: tower.id, x0: cursor, x1: right, d: D });
    cursor = right + TOWER_GAP;
  }

  function walls(n: LayoutNode, cx: number, W: number, D: number, minLevel: number, towerId: number | null) {
    const depth = minLevel < 0 ? -minLevel * FLOOR_H : 3;
    const y = minLevel < 0 ? -depth / 2 : depth / 2;
    const t = 0.4;
    const ww = W + 1.6;
    const dd = D + 1.6;
    const common = { node_id: n.id, kind: n.kind, role: "element" as Role, h: depth, y, tower_id: towerId, below: minLevel < 0 };
    add({ ...common, x: cx, z: -dd / 2, w: ww, d: t });
    add({ ...common, x: cx, z: dd / 2, w: ww, d: t });
    add({ ...common, x: cx - ww / 2, z: 0, w: t, d: dd });
    add({ ...common, x: cx + ww / 2, z: 0, w: t, d: dd });
  }

  // site-level places: spanning slabs and walls over all towers, the rest in a row after them
  const x0 = extents.length ? Math.min(...extents.map((e) => e.x0)) : 0;
  const x1 = extents.length ? Math.max(...extents.map((e) => e.x1)) : 10;
  const dMax = extents.length ? Math.max(...extents.map((e) => e.d)) : 10;
  for (const n of siteLevel) {
    if (n.kind === "raft") {
      add({ node_id: n.id, kind: n.kind, role: "slab", x: (x0 + x1) / 2, y: minLevelAll * FLOOR_H - 0.4, z: 0, w: x1 - x0 + 2, h: 0.8, d: dMax + 2, below: true });
    } else if (n.kind === "podium") {
      add({ node_id: n.id, kind: n.kind, role: "slab", x: (x0 + x1) / 2, y: -0.275, z: 0, w: x1 - x0 + 8, h: 0.65, d: dMax + 8 });
    } else if (n.kind === "retaining_wall") {
      walls(n, (x0 + x1) / 2, x1 - x0, dMax, minLevelAll, null);
    } else {
      const [w, h, d] = ELEMENT_SIZE[n.kind] ?? (FLOOR_KINDS.has(n.kind) ? [FLOOR_DEFAULT[0], FLOOR_H - 0.25, FLOOR_DEFAULT[1]] : ELEMENT_SIZE.other);
      const below = BELOW_KINDS.has(n.kind);
      const y = n.kind === "swimming_pool" ? -h / 2 + 0.05 : below ? -h / 2 : h / 2;
      add({ node_id: n.id, kind: n.kind, role: "element", x: cursor + w / 2, y, z: 0, w, h, d, below });
      cursor += w + 3;
    }
  }

  // wings: groups around their towers
  for (const { wing, towers: inside } of wings) {
    const mine = extents.filter((e) => inside.some((t) => t.id === e.id));
    if (!mine.length) continue;
    const a = Math.min(...mine.map((e) => e.x0));
    const b = Math.max(...mine.map((e) => e.x1));
    add({ node_id: wing.id, kind: wing.kind, role: "group", x: (a + b) / 2, y: 0, z: 0, w: b - a, h: 0.1, d: Math.max(...mine.map((e) => e.d)) });
  }
  return boxes;
}

/** Do two boxes overlap (strictly, beyond a touching face)? */
export function overlaps(a: Box, b: Box, eps = 1e-6): boolean {
  return (
    Math.abs(a.x - b.x) * 2 < a.w + b.w - eps &&
    Math.abs(a.y - b.y) * 2 < a.h + b.h - eps &&
    Math.abs(a.z - b.z) * 2 < a.d + b.d - eps
  );
}
