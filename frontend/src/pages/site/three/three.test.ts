import { describe, expect, it } from "vitest";
import { categoryOf, legendCounts, rollupColor, STATUS_COLORS, workColor } from "./colors";
import type { NodeStatus } from "./colors";
import { FLOOR_H, layout, overlaps } from "./layout";
import type { Box, LayoutNode } from "./layout";
import { headerLines, legendText, wrapRows } from "./snapshot";

let next = 1;
function node(kind: string, name: string, parent: number | null, extra: Partial<LayoutNode> = {}): LayoutNode {
  return { id: next++, parent_id: parent, kind, name, level_no: null, area_sqm: null, sort_order: next, ...extra };
}

/** B1, G, 1–4, 2 flats per floor, 2 toilets + 1 kitchen per flat, terrace (the M3 demo). */
function tower(name: string): LayoutNode[] {
  const t = node("tower", name, null);
  const out = [t];
  for (const level of [-1, 0, 1, 2, 3, 4]) {
    const f = node(level < 0 ? "basement" : "floor", level < 0 ? "B1" : level === 0 ? "G" : `Floor ${level}`, t.id, { level_no: level });
    out.push(f);
    if (level < 0) continue;
    for (let i = 1; i <= 2; i++) {
      const flat = node("flat", `${level}0${i}`, f.id);
      out.push(flat, node("toilet", "Toilet 1", flat.id), node("toilet", "Toilet 2", flat.id), node("kitchen", "Kitchen", flat.id));
    }
  }
  out.push(node("terrace", "Terrace", t.id));
  return out;
}

function status(p: Omit<Partial<NodeStatus>, "counts"> & { counts?: Partial<NodeStatus["counts"]> } = {}): NodeStatus {
  const counts = { not_started: 0, in_progress: 0, done: 0, certified: 0, blocked: 0, ...p.counts };
  return {
    percent: 0,
    tasks: Object.values(counts).reduce((a, b) => a + b, 0),
    current_step: null,
    next_step: null,
    is_late: false,
    waiting_certification: false,
    has_scope: true,
    template_ids: [],
    ...p,
    counts,
  };
}

describe("layout", () => {
  it("gives one box per node for the demo tower", () => {
    const nodes = tower("T1");
    const boxes = layout(nodes);
    // tower 1 + B1 + G..4 (5) + 10 flats + 30 rooms + terrace = 48
    expect(nodes.length).toBe(48);
    expect(boxes.length).toBe(48);
    expect(new Set(boxes.map((b) => b.node_id)).size).toBe(48);
    const count = (role: string) => boxes.filter((b) => b.role === role).length;
    expect([count("group"), count("floor"), count("flat"), count("room"), count("slab")]).toEqual([1, 6, 10, 30, 1]);
  });

  it("stacks floors without overlap, basements below the ground", () => {
    const floors = layout(tower("T1"))
      .filter((b) => b.role === "floor")
      .sort((a, b) => a.level! - b.level!);
    for (let i = 1; i < floors.length; i++) {
      expect(overlaps(floors[i - 1], floors[i])).toBe(false);
      expect(floors[i].y - floors[i - 1].y).toBeCloseTo(FLOOR_H);
    }
    const b1 = floors[0];
    expect(b1.kind).toBe("basement");
    expect(b1.y + b1.h / 2).toBeLessThanOrEqual(0);
    expect(b1.below).toBe(true);
    expect(floors[1].y - floors[1].h / 2).toBeGreaterThanOrEqual(0);
  });

  it("keeps rooms inside their flat and flats inside their floor", () => {
    const boxes = layout(tower("T1"));
    const inside = (a: Box, b: Box) => Math.abs(a.x - b.x) + a.w / 2 <= b.w / 2 + 1e-6 && Math.abs(a.z - b.z) + a.d / 2 <= b.d / 2 + 1e-6;
    const byFloor = new Map(boxes.filter((b) => b.role === "floor").map((b) => [b.node_id, b]));
    const flats = boxes.filter((b) => b.role === "flat");
    for (const f of flats) expect(inside(f, byFloor.get(f.floor_id!)!)).toBe(true);
    for (let i = 0; i < flats.length; i++) for (let j = i + 1; j < flats.length; j++) expect(overlaps(flats[i], flats[j])).toBe(false);
    const rooms = boxes.filter((b) => b.role === "room");
    for (const r of rooms) expect(flats.some((f) => f.floor_id === r.floor_id && inside(r, f))).toBe(true);
  });

  it("puts two towers side by side without overlap", () => {
    const boxes = layout([...tower("T1"), ...tower("T2")]);
    const towers = boxes.filter((b) => b.role === "group");
    expect(towers).toHaveLength(2);
    expect(overlaps(towers[0], towers[1])).toBe(false);
    expect(towers[1].x).toBeGreaterThan(towers[0].x);
    const solid = boxes.filter((b) => b.role === "floor" || b.role === "slab");
    for (const a of solid.filter((b) => b.tower_id === towers[0].node_id))
      for (const b of solid.filter((x) => x.tower_id === towers[1].node_id)) expect(overlaps(a, b)).toBe(false);
  });

  it("places tanks, pits, raft and walls", () => {
    const nodes = tower("T1");
    const t = nodes[0].id;
    const terrace = nodes.find((n) => n.kind === "terrace")!;
    nodes.push(node("oh_tank", "OHT 1", terrace.id), node("lift_pit", "Lift pit 1", t), node("ug_tank", "UG tank", t), node("raft", "Raft", t), node("retaining_wall", "RW", t));
    const boxes = layout(nodes);
    const get = (kind: string) => boxes.filter((b) => b.kind === kind);
    const slab = get("terrace")[0];
    expect(get("oh_tank")[0].y - get("oh_tank")[0].h / 2).toBeCloseTo(slab.y + slab.h / 2);
    for (const kind of ["lift_pit", "ug_tank", "raft"]) {
      const b = get(kind)[0];
      expect(b.below).toBe(true);
      expect(b.y + b.h / 2).toBeLessThanOrEqual(0.001);
    }
    expect(get("raft")[0].y).toBeLessThan(get("basement")[0].y);
    expect(get("retaining_wall")).toHaveLength(4);
    const group = boxes.find((b) => b.role === "group")!;
    expect(get("lift_pit")[0].x).toBeGreaterThan(get("floor")[0].x + get("floor")[0].w / 2);
    expect(group.w).toBeGreaterThan(get("floor")[0].w);
  });
});

describe("colours", () => {
  it("maps task states to categories", () => {
    expect(categoryOf(status({ counts: { done: 2, certified: 1 } }))).toBe("done");
    expect(categoryOf(status({ counts: { done: 1, not_started: 2 } }))).toBe("progress");
    expect(categoryOf(status({ counts: { in_progress: 1, not_started: 3 } }))).toBe("progress");
    expect(categoryOf(status({ counts: { done: 2, not_started: 1 }, waiting_certification: true }))).toBe("hold");
    expect(categoryOf(status({ counts: { blocked: 1, done: 3 }, waiting_certification: true }))).toBe("blocked");
    expect(categoryOf(status({ counts: { not_started: 4 } }))).toBe("not_started");
    expect(categoryOf(status({ has_scope: true }))).toBe("not_started"); // scope, tasks not generated
    expect(categoryOf(status({ has_scope: false }))).toBe("none");
  });

  it("colours a late task by its state (the outline marks it late)", () => {
    const late = status({ counts: { in_progress: 1 }, is_late: true });
    expect(workColor(late, false).color).toBe(STATUS_COLORS.progress);
    expect(legendCounts([{ status: late, countable: true }]).late).toBe(1);
  });

  it("tints a parent by its rolled-up %", () => {
    const parent = status({ has_scope: false, percent: 50 });
    const c = workColor(parent, true);
    expect(c.category).toBe("rollup");
    expect(rollupColor(0)).toBe("#dfe3e6");
    expect(rollupColor(100)).toBe(STATUS_COLORS.done);
    expect(c.color).toBe(rollupColor(50));
    expect(workColor(status({ has_scope: false }), false)).toEqual({ color: STATUS_COLORS.none, category: "none", ghost: true });
  });

  it("counts the legend", () => {
    const counts = legendCounts([
      { status: status({ counts: { done: 1 } }), countable: true },
      { status: status({ counts: { blocked: 1 } }), countable: true },
      { status: status({ has_scope: false }), countable: true },
      { status: status({ has_scope: false }), countable: false },
    ]);
    expect(counts).toMatchObject({ done: 1, blocked: 1, none: 1, progress: 0 });
  });
});

describe("Save image layout", () => {
  it("puts the site, code, date and overall % in the header", () => {
    const [title, sub] = headerLines({ siteName: "Shela", siteCode: "S-2026-0001", percent: 41.6, date: new Date(2026, 9, 7) });
    expect(title).toBe("Shela (S-2026-0001)");
    expect(sub).toContain("2026");
    expect(sub).toContain("Oct");
    expect(sub).toContain("overall 42% done");
  });

  it("wraps the legend into rows that fit", () => {
    expect(wrapRows([100, 100, 100], 1000, 10)).toEqual([[0, 1, 2]]);
    expect(wrapRows([100, 100, 100], 215, 10)).toEqual([[0, 1], [2]]);
    expect(wrapRows([300, 50], 200, 10)).toEqual([[0], [1]]); // a too-wide item still gets its own row
    expect(wrapRows([], 200, 10)).toEqual([]);
  });

  it("shows each legend count", () => {
    expect(legendText({ label: "Done / certified", color: STATUS_COLORS.done, count: 12 })).toBe("Done / certified (12)");
  });
});
