// The drawing on screen. The server sends it compact (version 2: only the shown layers, 1 mm
// steps, polylines); decodeGeometry turns it back into lines per layer. GlPlan draws those lines
// with WebGL: uploaded once, so a pan or a zoom is one uniform and a few draw calls instead of
// every line again; zoomed far out it draws a coarse copy (only the lines longer than about half a
// pixel). Texts and what the user traces stay on a 2D canvas above.
import { useEffect, useRef } from "react";

export type GeoV2 = {
  v: 2;
  unit_m: number | null;
  extents: [number, number, number, number] | null;
  origin: [number, number];
  q: number;
  layers: { name: string; color: number; role: string | null }[];
  g: Record<string, number[][]>;
  t: [number, number, number, string, string][];
};
export type Geo = {
  extents: [number, number, number, number] | null;
  unit_m: number | null;
  layers: { name: string; color: number; role: string | null; off: boolean; frozen: boolean; count: number }[];
  geometry: Record<string, { s: Float64Array | number[] }>;
  texts: [number, number, number, string, string, boolean?][];
};

/** Version 2 back to lines per layer (drawing units), or an older payload as it is. */
export function decodeGeometry(raw: GeoV2 | Geo): Geo {
  if ((raw as GeoV2).v !== 2) return raw as Geo;
  const g = raw as GeoV2;
  const [ox, oy] = g.origin;
  const q = g.q;
  const geometry: Geo["geometry"] = {};
  for (const [layer, polylines] of Object.entries(g.g)) {
    let n = 0;
    for (const pl of polylines) n += pl.length / 2 - 1;
    const s = new Float64Array(n * 4);
    let k = 0;
    for (const pl of polylines) {
      let x = pl[0];
      let y = pl[1];
      for (let i = 2; i < pl.length; i += 2) {
        const nx = x + pl[i];
        const ny = y + pl[i + 1];
        s[k++] = ox + x * q;
        s[k++] = oy + y * q;
        s[k++] = ox + nx * q;
        s[k++] = oy + ny * q;
        x = nx;
        y = ny;
      }
    }
    geometry[layer] = { s };
  }
  return {
    extents: g.extents,
    unit_m: g.unit_m,
    layers: g.layers.map((l) => ({ ...l, off: false, frozen: false, count: (geometry[l.name]?.s.length ?? 0) / 4 })),
    geometry,
    texts: g.t.map(([x, y, h, layer, text]) => [ox + x * q, oy + y * q, h * q, layer, text]),
  };
}

// AutoCAD colour index, the common ones; the rest in grey
const ACI: Record<number, [number, number, number]> = { 1: [0.84, 0.15, 0.16], 2: [0.72, 0.63, 0], 3: [0.17, 0.63, 0.17], 4: [0.09, 0.64, 0.72], 5: [0.12, 0.31, 0.85], 6: [0.76, 0.09, 0.76], 7: [0.2, 0.2, 0.2], 8: [0.53, 0.53, 0.53], 9: [0.73, 0.73, 0.73] };
export const aciRgb = (c: number): [number, number, number] => ACI[Math.abs(c)] ?? [0.6, 0.6, 0.6];

type LayerBuf = { name: string; color: [number, number, number]; full: [number, number]; coarse: [number, number] };
export type View = { cx: number; cy: number; scale: number };

const VS = `attribute vec2 p; uniform vec2 c; uniform vec2 k; void main(){ gl_Position = vec4((p - c) * k, 0.0, 1.0); }`;
const FS = `precision mediump float; uniform vec3 col; void main(){ gl_FragColor = vec4(col, 1.0); }`;

/** The lines of a drawing in a WebGL buffer (relative to the drawing's corner: float precision). */
export class GlPlan {
  private gl: WebGLRenderingContext;
  private prog: WebGLProgram;
  private buf: WebGLBuffer;
  private layers: LayerBuf[] = [];
  private ox: number;
  private oy: number;
  private coarseMin: number;

  constructor(
    readonly canvas: HTMLCanvasElement,
    geo: Geo,
  ) {
    const gl = canvas.getContext("webgl", { antialias: true, preserveDrawingBuffer: false });
    if (!gl) throw new Error("no WebGL");
    this.gl = gl;
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    this.prog = gl.createProgram()!;
    gl.attachShader(this.prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(this.prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(this.prog);
    const e = geo.extents ?? [0, 0, 1000, 1000];
    this.ox = e[0];
    this.oy = e[1];
    this.coarseMin = Math.hypot(e[2] - e[0], e[3] - e[1]) / 4000;
    // one buffer: per layer its full lines, then its coarse copy
    let total = 0;
    for (const g of Object.values(geo.geometry)) total += g.s.length * 2;
    const data = new Float32Array(total);
    let at = 0;
    const colors = new Map(geo.layers.map((l) => [l.name, l.color]));
    for (const [name, g] of Object.entries(geo.geometry)) {
      const s = g.s;
      const start = at / 2;
      for (let i = 0; i < s.length; i++) data[at++] = s[i] - (i % 2 === 0 ? this.ox : this.oy);
      const full: [number, number] = [start, s.length / 2];
      const cStart = at / 2;
      for (let i = 0; i < s.length; i += 4) {
        if (Math.hypot(s[i + 2] - s[i], s[i + 3] - s[i + 1]) < this.coarseMin) continue;
        data[at++] = s[i] - this.ox;
        data[at++] = s[i + 1] - this.oy;
        data[at++] = s[i + 2] - this.ox;
        data[at++] = s[i + 3] - this.oy;
      }
      this.layers.push({ name, color: aciRgb(colors.get(name) ?? 7), full, coarse: [cStart, at / 2 - cStart] });
    }
    this.buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, data.subarray(0, at), gl.STATIC_DRAW);
  }

  draw(view: View, hidden: Set<string>): void {
    const gl = this.gl;
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth;
    const h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    gl.viewport(0, 0, c.width, c.height);
    gl.clearColor(1, 1, 1, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (!view.scale) return;
    gl.useProgram(this.prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    const p = gl.getAttribLocation(this.prog, "p");
    gl.enableVertexAttribArray(p);
    gl.vertexAttribPointer(p, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(gl.getUniformLocation(this.prog, "c"), view.cx - this.ox, view.cy - this.oy);
    gl.uniform2f(gl.getUniformLocation(this.prog, "k"), (view.scale * 2) / w, (view.scale * 2) / h);
    const colLoc = gl.getUniformLocation(this.prog, "col");
    const coarse = this.coarseMin * view.scale < 0.5; // far out: the short lines are under half a pixel
    for (const l of this.layers) {
      if (hidden.has(l.name)) continue;
      const [start, count] = coarse ? l.coarse : l.full;
      if (!count) continue;
      gl.uniform3f(colLoc, l.color[0], l.color[1], l.color[2]);
      gl.drawArrays(gl.LINES, start, count);
    }
  }

  dispose(): void {
    this.gl.deleteBuffer(this.buf);
    this.gl.deleteProgram(this.prog);
  }
}

/** Draws the drawing's lines on a WebGL canvas for the given view; false when WebGL is not there
 *  (the 2D canvas then draws the lines itself). */
export function useGlPlan(canvas: React.RefObject<HTMLCanvasElement>, geo: Geo | null, view: View, hidden: Set<string>): React.MutableRefObject<boolean> {
  const plan = useRef<GlPlan | null>(null);
  const ok = useRef(true);
  useEffect(() => {
    if (!canvas.current || !geo) return;
    try {
      plan.current = new GlPlan(canvas.current, geo);
      ok.current = true;
    } catch {
      ok.current = false;
    }
    return () => {
      plan.current?.dispose();
      plan.current = null;
    };
  }, [canvas, geo]);
  useEffect(() => {
    const id = requestAnimationFrame(() => plan.current?.draw(view, hidden));
    return () => cancelAnimationFrame(id);
  }, [view, hidden, geo]);
  return ok;
}
