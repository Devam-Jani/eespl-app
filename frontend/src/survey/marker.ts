// Marker photo maths. Two printed ArUco markers (ARUCO_MIP_36h12 ids 0 and 1, exactly 150 mm
// across the black square) lie flat on the surface. Each detected marker gives a homography from
// that plane (mm) to the photo (px); the user taps the area's corners on the photo and we map
// them back to the plane. The two markers must agree on the scale within 2 %.

export const MARKER_MM = 150;
export const MIN_MARKER_SHARE = 0.1; // of the frame width
export const MAX_SCALE_DISAGREEMENT = 0.02;

export type Pt = { x: number; y: number };
export type Detected = { id: number; corners: Pt[] };
export type H = number[]; // 3x3, row major

/** Solve A x = b (n x n) by Gaussian elimination with partial pivoting. */
function solve(A: number[][], b: number[]): number[] {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    if (Math.abs(M[c][c]) < 1e-12) throw new Error("singular");
    for (let r = c + 1; r < n; r++) {
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
    }
  }
  const x = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) {
    let s = M[r][n];
    for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k];
    x[r] = s / M[r][r];
  }
  return x;
}

/** Homography from src to dst points (4 or more pairs; least squares, h33 = 1). */
export function homography(src: Pt[], dst: Pt[]): H {
  const ata = Array.from({ length: 8 }, () => new Array(8).fill(0));
  const atb = new Array(8).fill(0);
  const add = (row: number[], v: number) => {
    for (let i = 0; i < 8; i++) {
      atb[i] += row[i] * v;
      for (let j = 0; j < 8; j++) ata[i][j] += row[i] * row[j];
    }
  };
  src.forEach((s, i) => {
    const d = dst[i];
    add([s.x, s.y, 1, 0, 0, 0, -d.x * s.x, -d.x * s.y], d.x);
    add([0, 0, 0, s.x, s.y, 1, -d.y * s.x, -d.y * s.y], d.y);
  });
  return [...solve(ata, atb), 1];
}

export function apply(h: H, p: Pt): Pt {
  const w = h[6] * p.x + h[7] * p.y + h[8];
  return { x: (h[0] * p.x + h[1] * p.y + h[2]) / w, y: (h[3] * p.x + h[4] * p.y + h[5]) / w };
}

export function invert(h: H): H {
  const [a, b, c, d, e, f, g, i, k] = h;
  const A = e * k - f * i;
  const B = -(d * k - f * g);
  const C = d * i - e * g;
  const det = a * A + b * B + c * C;
  const inv = [A, -(b * k - c * i), b * f - c * e, B, a * k - c * g, -(a * f - c * d), C, -(a * i - b * g), a * e - b * d];
  return inv.map((v) => v / det);
}

export function polygonArea(pts: Pt[]): number {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    s += a.x * b.y - b.x * a.y;
  }
  return Math.abs(s) / 2;
}

export function sides(pts: Pt[]): number[] {
  return pts.map((a, i) => {
    const b = pts[(i + 1) % pts.length];
    return Math.hypot(b.x - a.x, b.y - a.y);
  });
}

/** The marker's own plane: its four corners in mm, in the detector's corner order. */
const PLANE: Pt[] = [
  { x: 0, y: 0 },
  { x: MARKER_MM, y: 0 },
  { x: MARKER_MM, y: MARKER_MM },
  { x: 0, y: MARKER_MM },
];

export type Calibration =
  { ok: true; toPlane: H[]; joint: H; markers: Detected[]; scaleDisagreement: number; widths: number[] } | { ok: false; reason: string; markers: Detected[] };

/** Check the detected markers and build the image -> plane mappings. */
export function calibrate(found: Detected[], frameWidth: number): Calibration {
  const ours = [0, 1].map((id) => found.find((m) => m.id === id)).filter((m): m is Detected => !!m);
  if (ours.length === 0) return { ok: false, reason: "No marker found: lay both sheets flat and keep them fully in the photo.", markers: found };
  if (ours.length === 1) return { ok: false, reason: "Only one marker found: both sheets must be in the photo.", markers: ours };
  const widths = ours.map((m) => (Math.max(...m.corners.map((c) => c.x)) - Math.min(...m.corners.map((c) => c.x))) / frameWidth);
  if (widths.some((w) => w < MIN_MARKER_SHARE))
    return { ok: false, reason: `Move closer: a marker is only ${Math.round(Math.min(...widths) * 100)}% of the photo width (needs 10%).`, markers: ours };
  const H = ours.map((m) => homography(PLANE, m.corners)); // plane -> image
  const toPlane = H.map(invert);
  // marker 1 measured in marker 0's plane must come out 150 mm a side (and the other way round)
  const scale = (from: number, to: number) => {
    const pts = ours[to].corners.map((c) => apply(toPlane[from], c));
    const s = sides(pts);
    return s.reduce((a, b) => a + b, 0) / s.length / MARKER_MM;
  };
  const disagreement = Math.max(Math.abs(scale(0, 1) - 1), Math.abs(scale(1, 0) - 1));
  if (disagreement > MAX_SCALE_DISAGREEMENT)
    return {
      ok: false,
      reason: `The two markers disagree on scale by ${(disagreement * 100).toFixed(1)}% (more than 2%): flatten the sheets and take the photo again.`,
      markers: ours,
    };
  return { ok: true, toPlane, joint: jointFit(ours), markers: ours, scaleDisagreement: disagreement, widths };
}

/** One plane homography from both markers' eight corners: marker 1's place on the floor is not
 * known, so it is estimated (rotation and offset, size fixed at 150 mm) in turn with the
 * homography. The two markers' wider spread pins the perspective far better than either alone. */
export function jointFit(ours: Detected[]): H {
  let h = invert(homography(PLANE, ours[0].corners)); // image -> marker 0's plane
  for (let iter = 0; iter < 8; iter++) {
    const seen = ours[1].corners.map((c) => apply(h, c));
    const placed = rigidFit(PLANE, seen); // marker 1's square, as close as possible to where H puts it
    const toImage = homography([...PLANE, ...placed], [...ours[0].corners, ...ours[1].corners]);
    h = invert(toImage);
  }
  return h;
}

/** The 150 mm square, rotated and moved (no scaling) to best fit the given four points. */
function rigidFit(square: Pt[], target: Pt[]): Pt[] {
  const cs = mean(square);
  const ct = mean(target);
  let num = 0;
  let den = 0;
  square.forEach((p, i) => {
    const a = { x: p.x - cs.x, y: p.y - cs.y };
    const b = { x: target[i].x - ct.x, y: target[i].y - ct.y };
    num += a.x * b.y - a.y * b.x;
    den += a.x * b.x + a.y * b.y;
  });
  const t = Math.atan2(num, den);
  return square.map((p) => {
    const a = { x: p.x - cs.x, y: p.y - cs.y };
    return { x: ct.x + a.x * Math.cos(t) - a.y * Math.sin(t), y: ct.y + a.x * Math.sin(t) + a.y * Math.cos(t) };
  });
}

function mean(pts: Pt[]): Pt {
  return { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length };
}

/** Subpixel corners: along each edge of the detected square, find where the brightness crosses
 * half-way between the black border and the white paper (each profile averaged over three
 * parallel lines, which tames sensor noise), fit a line to those points (twice, dropping
 * outliers), then intersect neighbouring edges. */
export function refineCorners(gray: (x: number, y: number) => number, corners: Pt[]): Pt[] {
  const STEP = 0.25;
  const REACH = 5;
  const lines = corners.map((a, i) => {
    const b = corners[(i + 1) % 4];
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const u = { x: (b.x - a.x) / len, y: (b.y - a.y) / len };
    const n = { x: -u.y, y: u.x };
    const pts: Pt[] = [];
    const samples = Math.max(10, Math.floor(len / 2));
    for (let k = 2; k < samples - 1; k++) {
      const t = k / samples;
      const c = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      const prof: number[] = [];
      for (let d = -REACH; d <= REACH + 1e-9; d += STEP) {
        let s = 0;
        for (const o of [-1, 0, 1]) s += gray(c.x + n.x * d + u.x * o, c.y + n.y * d + u.y * o);
        prof.push(s / 3);
      }
      const lo = Math.min(...prof);
      const hi = Math.max(...prof);
      if (hi - lo < 40) continue;
      const mid = (lo + hi) / 2;
      // the crossing nearest the middle of the profile
      let at: number | null = null;
      for (let j = 0; j < prof.length - 1; j++) {
        if ((prof[j] - mid) * (prof[j + 1] - mid) <= 0 && prof[j] !== prof[j + 1]) {
          const d = -REACH + (j + (mid - prof[j]) / (prof[j + 1] - prof[j])) * STEP;
          if (at === null || Math.abs(d) < Math.abs(at)) at = d;
        }
      }
      if (at !== null) pts.push({ x: c.x + n.x * at, y: c.y + n.y * at });
    }
    if (pts.length < 3) return fitLine([a, b]);
    const first = fitLine(pts);
    const res = pts.map((p) => Math.abs((p.x - first.p.x) * -first.d.y + (p.y - first.p.y) * first.d.x));
    const sorted = [...res].sort((x, y) => x - y);
    const cut = Math.max(0.5, 2.5 * sorted[Math.floor(sorted.length / 2)]);
    const kept = pts.filter((_, j) => res[j] <= cut);
    return fitLine(kept.length >= 3 ? kept : pts);
  });
  return corners.map((c, i) => intersect(lines[(i + 3) % 4], lines[i]) ?? c);
}

type Line = { p: Pt; d: Pt };

function fitLine(pts: Pt[]): Line {
  const m = mean(pts);
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (const p of pts) {
    sxx += (p.x - m.x) ** 2;
    sxy += (p.x - m.x) * (p.y - m.y);
    syy += (p.y - m.y) ** 2;
  }
  const angle = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  return { p: m, d: { x: Math.cos(angle), y: Math.sin(angle) } };
}

function intersect(a: Line, b: Line): Pt | null {
  const det = a.d.x * b.d.y - a.d.y * b.d.x;
  if (Math.abs(det) < 1e-9) return null;
  const t = ((b.p.x - a.p.x) * b.d.y - (b.p.y - a.p.y) * b.d.x) / det;
  return { x: a.p.x + a.d.x * t, y: a.p.y + a.d.y * t };
}

export type Measurement = { polygonM: [number, number][]; sidesM: number[]; areaSqm: number; spread: number };

/** Tapped corners (px) -> the area in the markers' plane: each marker's estimate, averaged. */
export function measure(cal: Extract<Calibration, { ok: true }>, taps: Pt[]): Measurement {
  // the joint fit is the measurement; each marker alone gives the spread (a check)
  const est = [cal.joint, ...cal.toPlane].map((h) => taps.map((t) => apply(h, t)));
  const areas = est.map((pts) => polygonArea(pts) / 1e6);
  const first = est[0];
  const origin = first[0];
  const polygonM = first.map((p) => [Math.round(p.x - origin.x) / 1000, Math.round(p.y - origin.y) / 1000] as [number, number]);
  const sidesM = sides(first).map((s) => s / 1000);
  const areaSqm = areas[0];
  return { polygonM, sidesM, areaSqm, spread: Math.abs(areas[1] - areas[2]) / areaSqm };
}

/** Detect the markers in an image (js-aruco2 is loaded only when the camera needs it). */
export async function detectMarkers(image: { width: number; height: number; data: Uint8ClampedArray }): Promise<Detected[]> {
  const mod = (await import("js-aruco2")) as unknown as { AR?: AR; default?: { AR: AR } };
  const AR = (mod.AR ?? mod.default?.AR) as AR;
  const detector = new AR.Detector({ dictionaryName: "ARUCO_MIP_36h12" });
  const { width, height, data } = image;
  const lum = (x: number, y: number) => {
    const i = (Math.min(height - 1, Math.max(0, Math.round(y))) * width + Math.min(width - 1, Math.max(0, Math.round(x)))) * 4;
    return 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  };
  // bilinear brightness for the subpixel edge search
  // continuous coordinates (as the taps): pixel i covers i..i+1, so its centre is at i + 0.5
  const gray = (cx: number, cy: number) => {
    const x = cx - 0.5;
    const y = cy - 0.5;
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    const fx = x - x0;
    const fy = y - y0;
    return (lum(x0, y0) * (1 - fx) + lum(x0 + 1, y0) * fx) * (1 - fy) + (lum(x0, y0 + 1) * (1 - fx) + lum(x0 + 1, y0 + 1) * fx) * fy;
  };
  return detector.detect(image).map((m) => ({
    id: m.id,
    corners: refineCorners(
      gray,
      m.corners.map((c) => ({ x: c.x, y: c.y })),
    ),
  }));
}

type AR = { Detector: new (cfg: { dictionaryName: string }) => { detect: (img: unknown) => { id: number; corners: Pt[] }[] } };

/** The distance between two tapped points on the plane, metres (the joint fit). */
export function lengthM(cal: Extract<Calibration, { ok: true }>, a: Pt, b: Pt): number {
  const p = apply(cal.joint, a);
  const q = apply(cal.joint, b);
  return Math.hypot(q.x - p.x, q.y - p.y) / 1000;
}
