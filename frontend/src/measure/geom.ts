// The drawing's outlines on screen: arcs as SVG arcs (exact, from the bulge), y turned up the
// right way, and the same outline in short chords for the 3D view.

export type Pt = [number, number, number]; // x, y (metres), the bulge of the segment that leaves it

/** An SVG path of a closed outline; the drawing's y goes up, the screen's down. */
export function outlinePath(o: Pt[]): string {
  if (o.length < 2) return "";
  let d = `M${o[0][0]} ${-o[0][1]}`;
  for (let i = 0; i < o.length; i++) {
    const p = o[i];
    const q = o[(i + 1) % o.length];
    const b = p[2] || 0;
    if (!b) {
      d += ` L${q[0]} ${-q[1]}`;
      continue;
    }
    const theta = 4 * Math.atan(b);
    const chord = Math.hypot(q[0] - p[0], q[1] - p[1]);
    const r = chord / (2 * Math.abs(Math.sin(theta / 2)));
    // y turned over, on a screen whose y runs down: counter-clockwise still looks counter-clockwise,
    // which is SVG's sweep 0
    d += ` A${r} ${r} 0 ${Math.abs(theta) > Math.PI ? 1 : 0} ${b > 0 ? 0 : 1} ${q[0]} ${-q[1]}`;
  }
  return d + " Z";
}

/** The outline in chords (each arc in up to `perArc` pieces), drawing coordinates. */
export function flatten(o: Pt[], perArc = 48): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < o.length; i++) {
    const p = o[i];
    const q = o[(i + 1) % o.length];
    out.push([p[0], p[1]]);
    const b = p[2] || 0;
    if (!b) continue;
    const theta = 4 * Math.atan(b);
    const dx = q[0] - p[0];
    const dy = q[1] - p[1];
    const chord = Math.hypot(dx, dy);
    const r = chord / (2 * Math.abs(Math.sin(theta / 2)));
    const off = chord / 2 / Math.tan(theta / 2);
    const cx = (p[0] + q[0]) / 2 - (dy / chord) * off;
    const cy = (p[1] + q[1]) / 2 + (dx / chord) * off;
    const a0 = Math.atan2(p[1] - cy, p[0] - cx);
    const n = Math.max(2, Math.ceil((perArc * Math.abs(theta)) / (2 * Math.PI)));
    for (let k = 1; k < n; k++) out.push([cx + r * Math.cos(a0 + (theta * k) / n), cy + r * Math.sin(a0 + (theta * k) / n)]);
  }
  return out;
}

export function bbox(points: [number, number][]): [number, number, number, number] {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity; // prettier-ignore
  for (const [x, y] of points) {
    x1 = Math.min(x1, x);
    y1 = Math.min(y1, y);
    x2 = Math.max(x2, x);
    y2 = Math.max(y2, y);
  }
  return [x1, y1, x2, y2];
}

/** A level as written on a section (+1800, -600, +1.800 in metres, ± 0.00): millimetres, or null. */
export function levelOf(text: string): number | null {
  const m = text.replace("±", "+").match(/(^|[^\w.])([+-])?\s*(\d+(?:\.\d+)?)(\s*mm|\s*m)?(?![\w.])/);
  if (!m || !m[2]) return null; // a level carries its sign: a plain number is a dimension
  let v = Number(m[3]);
  if (m[4]?.trim() === "m" || (!m[4] && m[3].includes("."))) v *= 1000;
  return m[2] === "-" ? -v : v;
}
