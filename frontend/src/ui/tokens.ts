// The design tokens: the one place colours live (EESPL UI v1 in Figma). tokens.css is written from
// this file (UPDATE_TOKENS=1 npx vitest run src/ui/tokens.test.ts) and checked equal by that test;
// pages use the CSS variables, the 3D viewer and charts use these values. No hex colour anywhere
// else (src/ui/nohex.test.ts).

export type ThemeName = "dark" | "light";

const dark = {
  bg: "#0B1220",
  panel: "#0E1729",
  surface: "#111B30",
  "surface-2": "#121D33",
  raised: "#18304A",
  border: "#1E2B45",
  "border-2": "#24344F",
  text: "#E6EDF7",
  muted: "#9FB0CC",
  soft: "#C9D5EA",
  primary: "#19C39C",
  "on-primary": "#04201A",
  "primary-ink": "#19C39C",
  accent: "#5CC8FF",
  "accent-ink": "#5CC8FF",
  stage: "#070F1D",
  // work status: the fill (chips at 18%, bars, legend, 3D rooms) and the ink (text on the chip)
  done: "#3FC68A",
  prog: "#F5A524",
  hold: "#A78BFA",
  block: "#F26D6D",
  idle: "#5B6B86",
  "done-ink": "#3FC68A",
  "prog-ink": "#F5A524",
  "hold-ink": "#A78BFA",
  "block-ink": "#FF9A9A",
  "idle-ink": "#C9D5EA",
  shade: "#000000",
  white: "#FFFFFF",
};

export type Palette = typeof dark;

// light: for printing and bright sites; the same roles, darker inks so text keeps AA on white
const light: Palette = {
  bg: "#F3F6FA",
  panel: "#FFFFFF",
  surface: "#FFFFFF",
  "surface-2": "#F5F8FC",
  raised: "#E4ECF6",
  border: "#D8E1EC",
  "border-2": "#C4D0DF",
  text: "#0E1729",
  muted: "#4A5873",
  soft: "#2A3852",
  primary: "#19C39C",
  "on-primary": "#04201A",
  "primary-ink": "#087A60",
  accent: "#2B9BDB",
  "accent-ink": "#0A649E",
  stage: "#E8EEF6",
  done: "#3FC68A",
  prog: "#F5A524",
  hold: "#A78BFA",
  block: "#F26D6D",
  idle: "#8A98B0",
  "done-ink": "#17734B",
  "prog-ink": "#8A5300",
  "hold-ink": "#5B3CC4",
  "block-ink": "#B42323",
  "idle-ink": "#3D4A61",
  shade: "#0E1729",
  white: "#FFFFFF",
};

export const THEMES: Record<ThemeName, Palette> = { dark, light };

/** The five work states, the same in chips, tables, charts, the legend and the 3D. */
export const STATUSES = ["done", "prog", "hold", "block", "idle"] as const;
export type Status = (typeof STATUSES)[number];
export const STATUS_LABEL: Record<Status, string> = { done: "Done", prog: "In progress", hold: "Hold point", block: "Blocked", idle: "Not started" };

/** Sizes on a 4 px grid; radii from the design (12 inputs and buttons, 14-16 small cards, 20 main cards). */
export const SIZES = {
  "space-1": "4px",
  "space-2": "8px",
  "space-3": "12px",
  "space-4": "16px",
  "space-5": "20px",
  "space-6": "24px",
  "space-8": "32px",
  "r-input": "12px",
  "r-small": "14px",
  "r-card-sm": "16px",
  "r-card": "20px",
  "r-pill": "999px",
  touch: "44px",
  sidebar: "248px",
  "font-text": '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  "font-display": '"Space Grotesk", "Inter", system-ui, sans-serif',
  ease: "cubic-bezier(0.2, 0.8, 0.2, 1)",
  "t-fast": "150ms",
  "t-med": "220ms",
  // the sticky top bar's height: what sticks or scrolls to the top of the page stops below it
  header: "68px",
  // the layers, low to high. Modals and drawers render on <body> (ui/Overlay.tsx), so a page's own
  // stacking never puts them under the top bar.
  "z-header": "50",
  "z-tabs": "80",
  "z-scrim": "90",
  "z-sidebar": "100",
  "z-menu": "300",
  "z-modal": "1000",
  "z-drawer": "1001",
  "z-helper": "1200",
  "z-toast": "1300",
  "z-skip": "2000",
};

/** A token as a number for three.js (0xRRGGBB). */
export function hex(name: keyof Palette, theme: ThemeName = "dark"): number {
  return parseInt(THEMES[theme][name].slice(1), 16);
}

function block(p: Palette): string {
  return Object.entries(p)
    .map(([k, v]) => `  --${k}: ${v};`)
    .join("\n");
}

/** tokens.css: dark by default, light on [data-theme="light"] and when printing. */
export function cssText(): string {
  const sizes = Object.entries(SIZES)
    .map(([k, v]) => `  --${k}: ${v};`)
    .join("\n");
  return [
    "/* Written from src/ui/tokens.ts (UPDATE_TOKENS=1 npx vitest run src/ui/tokens.test.ts). Do not edit by hand. */",
    `:root {\n${block(dark)}\n${sizes}\n  color-scheme: dark;\n}`,
    `:root[data-theme="light"] {\n${block(light)}\n  color-scheme: light;\n}`,
    `@media print {\n  :root {\n${block(light).replace(/^/gm, "  ")}\n    color-scheme: light;\n  }\n}`,
    "",
  ].join("\n\n");
}

// --- contrast (WCAG 2.1) ----------------------------------------------------------------------------

function rgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** `top` at `alpha` over `under` (a chip: the status colour at 18% behind its text). */
export function over(top: string, alpha: number, under: string): string {
  const a = rgb(top);
  const b = rgb(under);
  const m = a.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)));
  return `#${m.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

function luminance(h: string): number {
  const [r, g, b] = rgb(h).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** Every pair the app draws text with, and the AA minimum it needs (4.5 text, 3 large text and
 * the edges of controls). */
export function contrastPairs(p: Palette): { pair: string; ratio: number; min: number }[] {
  const out: { pair: string; ratio: number; min: number }[] = [];
  const add = (fg: keyof Palette | string, bg: keyof Palette | string, min = 4.5, fgHex?: string, bgHex?: string) => {
    const f = fgHex ?? p[fg as keyof Palette];
    const b = bgHex ?? p[bg as keyof Palette];
    out.push({ pair: `${fg} on ${bg}`, ratio: Math.round(contrast(f, b) * 100) / 100, min });
  };
  for (const bg of ["bg", "panel", "surface", "surface-2"] as const) {
    for (const fg of ["text", "soft", "muted", "primary-ink", "accent-ink", "block-ink"] as const) add(fg, bg);
  }
  add("text", "raised");
  add("soft", "raised");
  add("on-primary", "primary");
  add("text", "stage");
  add("muted", "stage");
  for (const s of STATUSES) {
    const chip = over(p[s], 0.18, p.surface);
    add(`${s}-ink`, `${s} chip`, 4.5, p[`${s}-ink` as keyof Palette], chip);
  }
  add("border-2", "surface", 1.0); // decoration only: listed, no minimum
  return out;
}

// --- colours that are not the app's look ---------------------------------------------------------
// Drawings and pictures on white paper (saved images, the AutoCAD canvas without WebGL, the
// signature), maps, charts, the camera's overlays and the 3D viewers' materials. They live here so
// no hex colour is anywhere else; the work states always come from the status tokens above.

/** Chart series: Okabe-Ito, safe for colour-blind readers. */
export const CHART = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"];

export const ART = {
  // paper (saved pictures, the signature, printouts drawn in the browser)
  paper: "#FFFFFF",
  ink: "#14231C",
  inkSoft: "#4A5A52",
  inkMuted: "#9AA3A0",
  inkBrand: "#2F6F4F",
  inkLate: "#B00000",
  // maps
  mapRoute: "#1F6FEB",
  mapRoad: "#9CA3AF",
  mapPlace: "#2F6F4F",
  mapFlag: "#B42318",
  // AutoCAD drawing colours (index 1-9) and the takeoff's marks
  aci1: "#D62728",
  aci2: "#B8A000",
  aci3: "#2CA02C",
  aci4: "#17A2B8",
  aci5: "#1F4FD8",
  aci6: "#C218C2",
  aci7: "#333333",
  aci8: "#888888",
  aci9: "#BBBBBB",
  drawLine: "#999999",
  drawText: "#555555",
  drawGrid: "#9AA2A6",
  drawAccepted: "#0F6B5C",
  drawMapped: "#1F4FD8",
  drawOpen: "#E69F00",
  drawOutline: "#0B84C6",
  drawCore: "#8E5CC8",
  drawBeam: "#E67E22",
  // the camera and AR overlays (on a live picture)
  camGood: "#009E73",
  camWarn: "#E69F00",
  camBad: "#D55E00",
  camLight: "#FFFFFF",
  camDark: "#111111",
  camShade: "#444444",
  // the schematic 3D (the site's places as boxes) and the survey colouring
  sceneBg: "#F3F5F4",
  sceneSky: "#FFFFFF",
  sceneGroundLight: "#B8B4AA",
  sceneGround: "#D3DCCF",
  sceneGroundReal: "#A9B994",
  sceneUnknown: "#CCCCCC",
  surveyNone: "#D9DEDB",
  ready: "#0072B2",
  rollupEmpty: "#DFE3E6",
  notOurs: "#EEF1F3",
  late: "#FF5A5A",
  // letterhead defaults (offers and PDFs keep their own white layout)
  letterheadPrimary: "#0F6E5A",
  letterheadAccent: "#E69F00",
};

/** The 3D viewer's three looks: X-ray from the dark tokens (stage, cyan edges with a soft glow),
 * Status light for printing, Realistic concrete and glass. */
export const VIEWER = {
  xray: { bg: dark.stage, line: dark.accent, shell: "#BFE7FF", face: "#1D5C8F", slab: "#1D5C8F", glass: "#1D5C8F", cut: dark.accent, selected: "#FFFFFF" },
  status: { bg: "#F3F5F6", line: "#8F989E", shell: "#5D676D", face: "#D9DEE1", slab: "#E3E6E8", glass: "#D9DEE1", cut: "#C8CFD3", selected: "#0E1729" },
  real: { bg: "#DFE8EF", line: "#6E6A63", shell: "#55524C", face: "#A9C9DC", slab: "#BDB8AE", glass: "#9FC6DC", cut: "#BDB8AE", selected: "#FFFFFF" },
};

/** The places' materials in the realistic 3D (by kind). */
export const MATERIALS: Record<string, string> = {
  floor: "#B3AEA5",
  basement: "#8F8A82",
  flat: "#B9765A",
  toilet: "#E3DDD0",
  kitchen: "#D6CDB8",
  balcony: "#C4BDB0",
  terrace: "#9A958C",
  oh_tank: "#7D8A93",
  ug_tank: "#6E7B84",
  raft: "#7A756D",
  retaining_wall: "#8A847B",
  podium: "#A39E95",
  swimming_pool: "#5AA3C9",
  stp: "#7D8A93",
  lift_pit: "#6F6A63",
  other: "#A0A0A0",
};

/** A colour as a number for three.js. */
export function num(h: string): number {
  return parseInt(h.slice(1), 16);
}
