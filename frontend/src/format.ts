import { ApiError } from "./api";

const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** ₹1,23,456.00 (Indian digit grouping, always two decimals). Blank values show as an em dash.
 * The one way a page shows an amount of money: src/moneyformat.test.ts fails on any other. */
export function inr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? rupees.format(n) : "—";
}

/** Compact Indian money for tiles: ₹29.49 Cr, ₹7.89 L, ₹72,228 (exact figures elsewhere). */
export function inrCompact(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const v = Number(value);
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`;
}

/** Shorter still for the labels on a chart: ₹1.2 Cr, ₹3.5 L, ₹13 k, ₹950. */
export function inrChart(v: number): string {
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(a >= 1e8 ? 0 : 1)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e6 ? 0 : 1)} L`;
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(0)} k`;
  return `${sign}₹${a.toFixed(0)}`;
}

/** A plain number with Indian grouping and up to `digits` decimals (trailing zeros dropped). */
export function num(value: string | number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-IN", { maximumFractionDigits: digits }) : "—";
}

/** Why a tender or lead was lost (the pick-list on the server). */
export const LOST_REASONS: Record<string, string> = {
  price: "Price",
  competitor: "Competitor",
  timing: "Timing",
  spec: "Specification",
  relationship: "Relationship",
  other: "Other",
  main_job_lost: "Main job lost by the contractor",
};

/** What a page shows for an error: nothing when the helper card shows it already (a wrong entry
 * beside its fields, a failure on our side with its request id), so an error is shown once. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError && err.shownByHelper) return "";
  return err instanceof Error ? err.message : String(err);
}

/** An error from a button with no place on the page for it (a download): said once. */
export function showError(err: unknown): void {
  const text = errorText(err);
  if (text) window.alert(text);
}

/** Copies to the clipboard; false when the browser gave no clipboard (a plain http address) or refused. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
