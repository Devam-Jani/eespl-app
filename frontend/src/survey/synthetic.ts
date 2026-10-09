// A synthetic photo of a floor: a pinhole camera looking down at the plane z = 0, with the two
// printed markers and a rectangle drawn on it. Used by the tests and to make the fake camera
// video for the screenshots; never in the app itself.
import { homography } from "./marker";
import type { H, Pt } from "./marker";

export type Camera = { width: number; height: number; hfovDeg: number; pos: [number, number, number]; pitchDeg: number; yawDeg?: number };
export type PlacedMarker = { id: number; x: number; y: number; size: number; rotDeg?: number }; // mm, top-left corner on the plane; turned about its centre

/** World (mm, z up) -> image (px) for points on the floor. */
export function project(cam: Camera, p: Pt): Pt {
  const pitch = (cam.pitchDeg * Math.PI) / 180;
  const yaw = ((cam.yawDeg ?? 0) * Math.PI) / 180;
  const f = cam.width / 2 / Math.tan((cam.hfovDeg * Math.PI) / 360);
  const fwd = [Math.sin(yaw) * Math.cos(pitch), Math.cos(yaw) * Math.cos(pitch), -Math.sin(pitch)];
  const right = [Math.cos(yaw), -Math.sin(yaw), 0];
  const down = [fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2], fwd[0] * right[1] - fwd[1] * right[0]];
  const w = [p.x - cam.pos[0], p.y - cam.pos[1], -cam.pos[2]];
  const dot = (a: number[]) => a[0] * w[0] + a[1] * w[1] + a[2] * w[2];
  const z = dot(fwd);
  return { x: cam.width / 2 + (f * dot(right)) / z, y: cam.height / 2 + (f * dot(down)) / z };
}

/** The camera's plane -> image homography (exact, from four plane points). */
export function planeToImage(cam: Camera): H {
  const src = [
    { x: 0, y: 0 },
    { x: 1000, y: 0 },
    { x: 1000, y: 1000 },
    { x: 0, y: 1000 },
  ];
  return homography(
    src,
    src.map((p) => project(cam, p)),
  );
}

function code(dictionary: { codeList: string[] }, id: number): string {
  return dictionary.codeList[id];
}

/** Render the photo (RGBA). `bits[id]` are the 36-bit code strings of the markers. */
export function render(
  cam: Camera,
  markers: PlacedMarker[],
  bits: Record<number, string>,
  rect?: { x: number; y: number; w: number; h: number },
  supersample = 2,
): { width: number; height: number; data: Uint8ClampedArray } {
  const { width, height } = cam;
  const toPlane = invert3(planeToImage(cam));
  const data = new Uint8ClampedArray(width * height * 4);
  const shade = (q: Pt): number => {
    for (const m of markers) {
      const t = ((m.rotDeg ?? 0) * Math.PI) / 180;
      const cx = m.x + m.size / 2;
      const cy = m.y + m.size / 2;
      const r = { x: cx + (q.x - cx) * Math.cos(t) + (q.y - cy) * Math.sin(t), y: cy - (q.x - cx) * Math.sin(t) + (q.y - cy) * Math.cos(t) };
      const u = ((r.x - m.x) / m.size) * 8;
      const v = ((m.y + m.size - r.y) / m.size) * 8; // the printed top row lies away from the camera
      if (u >= -1.2 && u < 9.2 && v >= -1.2 && v < 9.2) {
        if (u < 0 || u >= 8 || v < 0 || v >= 8) return 245; // paper margin
        if (u < 1 || u >= 7 || v < 1 || v >= 7) return 15; // black border
        return bits[m.id][(Math.floor(v) - 1) * 6 + (Math.floor(u) - 1)] === "1" ? 245 : 15;
      }
    }
    if (rect) {
      const near = (a: number, b: number) => Math.abs(a - b) < 18;
      const inX = q.x > rect.x - 18 && q.x < rect.x + rect.w + 18;
      const inY = q.y > rect.y - 18 && q.y < rect.y + rect.h + 18;
      if ((inY && (near(q.x, rect.x) || near(q.x, rect.x + rect.w))) || (inX && (near(q.y, rect.y) || near(q.y, rect.y + rect.h)))) return 70;
    }
    // concrete floor with a little texture
    return 150 + 18 * Math.sin(q.x / 37) * Math.cos(q.y / 53);
  };
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let sum = 0;
      for (let sy = 0; sy < supersample; sy++)
        for (let sx = 0; sx < supersample; sx++) {
          const p = apply3(toPlane, { x: x + (sx + 0.5) / supersample, y: y + (sy + 0.5) / supersample });
          sum += shade(p);
        }
      const g = sum / (supersample * supersample);
      const i = (y * width + x) * 4;
      data[i] = g;
      data[i + 1] = g * 0.98;
      data[i + 2] = g * 0.94;
      data[i + 3] = 255;
    }
  }
  return { width, height, data };
}

function apply3(h: H, p: Pt): Pt {
  const w = h[6] * p.x + h[7] * p.y + h[8];
  return { x: (h[0] * p.x + h[1] * p.y + h[2]) / w, y: (h[3] * p.x + h[4] * p.y + h[5]) / w };
}

function invert3(h: H): H {
  const [a, b, c, d, e, f, g, i, k] = h;
  const A = e * k - f * i;
  const B = -(d * k - f * g);
  const C = d * i - e * g;
  const det = a * A + b * B + c * C;
  return [A, -(b * k - c * i), b * f - c * e, B, a * k - c * g, -(a * f - c * d), C, -(a * i - b * g), a * e - b * d].map((v) => v / det);
}

export { code };
