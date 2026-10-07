/**
 * Colour rules for the 3D view (pure; unit-tested in colors.test.ts).
 *
 * Work status, per node from its own tasks:
 *   any blocked                         -> blocked (red)
 *   a hold point done, not certified    -> hold (purple)
 *   every task done or certified        -> done (green)
 *   some started or done                -> progress (amber)
 *   tasks, none started                 -> not_started (light grey)
 *   no tasks: a scope but no tasks yet  -> not_started; nothing at all -> none (very light, see-through)
 * Late (a planned end passed, not done) is drawn as a red outline on top of the colour.
 * A parent (floor, tower) without its own tasks but with work below it is tinted by its rolled-up %
 * (light grey -> green) and labelled with the %.
 */

export type NodeStatus = {
  percent: number;
  counts: { not_started: number; in_progress: number; done: number; certified: number; blocked: number };
  tasks: number;
  current_step: string | null;
  next_step: string | null;
  is_late: boolean;
  waiting_certification: boolean;
  has_scope: boolean;
  template_ids: number[];
};

export type Category = "done" | "progress" | "hold" | "blocked" | "not_started" | "none" | "rollup";

export const CATEGORY_LABEL: Record<Category, string> = {
  done: "Done / certified",
  progress: "In progress",
  hold: "Waiting at a hold point",
  blocked: "Blocked",
  not_started: "Not started (scheduled)",
  none: "No work here",
  rollup: "Rolled-up %",
};

export const STATUS_COLORS: Record<Exclude<Category, "rollup">, string> = {
  done: "#3f9a5c",
  progress: "#f0a531",
  hold: "#8e5cc8",
  blocked: "#d64545",
  not_started: "#c9ced3",
  none: "#eef1f3",
};
export const LATE_COLOR = "#d00000";

export function categoryOf(s: NodeStatus): Exclude<Category, "rollup"> {
  if (s.tasks === 0) return s.has_scope ? "not_started" : "none";
  const c = s.counts;
  if (c.blocked > 0) return "blocked";
  if (s.waiting_certification) return "hold";
  if (c.done + c.certified === s.tasks) return "done";
  if (c.in_progress > 0 || c.done + c.certified > 0) return "progress";
  return "not_started";
}

function hex(n: number): string {
  return Math.round(Math.max(0, Math.min(255, n)))
    .toString(16)
    .padStart(2, "0");
}

function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `#${pa.map((v, i) => hex(v + (pb[i] - v) * t)).join("")}`;
}

/** A parent's tint: light grey at 0 %, green at 100 %. */
export function rollupColor(percent: number): string {
  return mix("#dfe3e6", STATUS_COLORS.done, Math.max(0, Math.min(100, percent)) / 100);
}

/** The work-status colour of a node, and whether it is see-through. */
export function workColor(s: NodeStatus, hasWorkBelow: boolean): { color: string; category: Category; ghost: boolean } {
  const category = categoryOf(s);
  if (category === "none" && hasWorkBelow) return { color: rollupColor(s.percent), category: "rollup", ghost: false };
  return { color: STATUS_COLORS[category], category, ghost: category === "none" };
}

/** Concrete / brick tones by kind, for client presentations. */
export const REALISTIC: Record<string, string> = {
  floor: "#b3aea5",
  basement: "#8f8a82",
  flat: "#b9765a",
  toilet: "#e3ddd0",
  kitchen: "#d6cdb8",
  balcony: "#c4bdb0",
  terrace: "#9a958c",
  oh_tank: "#7d8a93",
  ug_tank: "#6e7b84",
  raft: "#7a756d",
  retaining_wall: "#8a847b",
  podium: "#a39e95",
  swimming_pool: "#5aa3c9",
  stp: "#7d8a93",
  lift_pit: "#6f6a63",
  other: "#a0a0a0",
};

export function realisticColor(kind: string): string {
  return REALISTIC[kind] ?? REALISTIC.other;
}

/** Legend counts: every place that has work (own tasks or scope) or is a room / flat / element. */
export function legendCounts(statuses: { status: NodeStatus; countable: boolean }[]): Record<string, number> {
  const out: Record<string, number> = { done: 0, progress: 0, hold: 0, blocked: 0, not_started: 0, none: 0, late: 0 };
  for (const { status, countable } of statuses) {
    if (!countable) continue;
    out[categoryOf(status)] += 1;
    if (status.is_late) out.late += 1;
  }
  return out;
}
