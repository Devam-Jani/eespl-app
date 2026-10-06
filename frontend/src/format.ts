const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** ₹1,23,456.00 (Indian digit grouping). Blank values show as an em dash. */
export function inr(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? rupees.format(n) : "—";
}

/** A plain number with Indian grouping and up to `digits` decimals (trailing zeros dropped). */
export function num(value: string | number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("en-IN", { maximumFractionDigits: digits })
    : "—";
}

export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
