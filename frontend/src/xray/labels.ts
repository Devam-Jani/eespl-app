// Room labels that do not cover each other: each label keeps its place when it is free, else moves
// up or down a step or two (a short leader shows where it belongs); one that still collides is
// hidden and shows on hover. Pure (tested without a browser).

export type RawLabel = { text: string; sub: string; x: number; y: number; nodeId?: number };
export type Placed = RawLabel & { dy: number; hidden: boolean; w: number; h: number };

/** A label's box at a font size (CSS px): the longer of its two lines, two lines high. */
export function labelSize(l: RawLabel, fontPx: number): { w: number; h: number } {
  const chars = Math.max(l.text.length, l.sub.length);
  return { w: Math.ceil(chars * fontPx * 0.56) + 8, h: Math.ceil(fontPx * 2.3) + 4 };
}

const overlaps = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) =>
  Math.abs(a.x - b.x) * 2 < a.w + b.w && Math.abs(a.y - b.y) * 2 < a.h + b.h;

export function placeLabels(labels: RawLabel[], fontPx: number, view: { width: number; height: number }): Placed[] {
  const placed: Placed[] = [];
  const order = [...labels].sort((a, b) => a.y - b.y || a.x - b.x);
  for (const l of order) {
    const { w, h } = labelSize(l, fontPx);
    const tries = [0, -(h + 2), h + 2, -2 * (h + 2), 2 * (h + 2)];
    let done: Placed | null = null;
    for (const dy of tries) {
      const box = { x: l.x, y: l.y + dy, w, h };
      const inside = box.y - h / 2 >= 0 && box.y + h / 2 <= view.height && box.x - w / 2 >= -w / 4 && box.x + w / 2 <= view.width + w / 4;
      if (inside && !placed.some((p) => !p.hidden && overlaps(box, { x: p.x, y: p.y + p.dy, w: p.w, h: p.h }))) {
        done = { ...l, dy, hidden: false, w, h };
        break;
      }
    }
    placed.push(done ?? { ...l, dy: 0, hidden: true, w, h });
  }
  return placed;
}
