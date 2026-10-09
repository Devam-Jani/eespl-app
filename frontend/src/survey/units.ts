// Sizes are stored in metres; people type them in metres or feet-inches.

export const M_PER_FT = 0.3048;
export type Unit = "m" | "ftin";

/** One length: 3.2 | 3.2m | 10' | 10'6 | 10' 6" | 10ft 6in | 6" -> metres (null if unreadable). */
export function parseLength(text: string, unit: Unit = "m"): number | null {
  const t = text.trim().toLowerCase().replace(/[’′]/g, "'").replace(/[”″]/g, '"').replace(/''/g, '"');
  if (!t) return null;
  const ftin = /^(?:(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot))?\s*(?:(\d+(?:\.\d+)?)\s*(?:"|in|inch|inches)?)?$/.exec(t);
  const hasFeetMark = /'|ft|feet|foot/.test(t);
  const hasInchMark = /"|in\b|inch/.test(t);
  if (hasFeetMark || (hasInchMark && unit === "ftin") || (hasInchMark && !t.includes("m"))) {
    if (!ftin || (ftin[1] === undefined && ftin[2] === undefined)) return null;
    const feet = Number(ftin[1] ?? 0);
    const inches = Number(ftin[2] ?? 0);
    if (inches >= 12 && ftin[1] !== undefined) return null;
    return round(feet * M_PER_FT + inches * 0.0254);
  }
  const m = /^(\d+(?:\.\d+)?)\s*(m|mm|cm)?$/.exec(t);
  if (!m) return null;
  const v = Number(m[1]);
  if (m[2] === "mm") return round(v / 1000);
  if (m[2] === "cm") return round(v / 100);
  return unit === "ftin" && !m[2] ? round(v * M_PER_FT) : round(v);
}

/** "10'6 x 7'3", "3.2 x 2.21", "3.2*2.21", "10' 6\" by 7' 3\"" -> [length, width] in metres. */
export function parseSize(text: string, unit: Unit = "m"): [number, number] | null {
  const parts = text.split(/\s*(?:x|×|\*|by)\s*/i).filter(Boolean);
  if (parts.length !== 2) return null;
  const a = parseLength(parts[0], unit);
  const b = parseLength(parts[1], unit);
  return a !== null && b !== null ? [a, b] : null;
}

export function round(v: number, places = 3): number {
  const f = 10 ** places;
  return Math.round(v * f) / f;
}

/** 3.2004 -> "10' 6"" (to the nearest inch) or "3.20 m". */
export function formatLength(m: number | string | null | undefined, unit: Unit): string {
  if (m === null || m === undefined || m === "") return "—";
  const v = Number(m);
  if (unit === "m") return `${v.toFixed(2)} m`;
  let totalIn = Math.round(v / 0.0254);
  const feet = Math.floor(totalIn / 12);
  totalIn -= feet * 12;
  return `${feet}' ${totalIn}"`;
}

export function formatArea(sqm: number | string | null | undefined, unit: Unit): string {
  if (sqm === null || sqm === undefined || sqm === "") return "—";
  const v = Number(sqm);
  return unit === "m" ? `${v.toFixed(2)} sqm` : `${(v / (M_PER_FT * M_PER_FT)).toFixed(1)} sqft`;
}
