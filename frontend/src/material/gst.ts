/**
 * Live PO totals, the same rules as the server (app/material/service.py compute_totals):
 * discount before tax; tax = taxable x GST % on lines and charges; CGST + SGST (half each) within
 * the state, IGST across states; the grand total is rounded to the rupee. Work in paise so the
 * sums do not drift.
 */

export type LineInput = { qty: string | number; rate: string | number; discount_percent?: string | number; gst_percent?: string | number };
export type ChargeInput = { amount: string | number; gst_percent?: string | number; add_to_cost?: boolean };

export type Totals = {
  lineAmounts: number[];
  subtotal: number;
  discount: number;
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  charges: number;
  roundOff: number;
  grandTotal: number;
};

const n = (v: string | number | undefined) => {
  const x = typeof v === "number" ? v : Number(v ?? 0);
  return Number.isFinite(x) ? x : 0;
};

/** Round half up to paise (the server's ROUND_HALF_UP). */
export const paise = (x: number) => Math.sign(x) * Math.round(Math.abs(x) * 100 + 1e-7);

export function poTotals(lines: LineInput[], charges: ChargeInput[], interstate: boolean): Totals {
  let gross = 0; // paise
  let taxable = 0;
  let tax = 0; // exact, rounded once at the end like the server
  const lineAmounts: number[] = [];
  for (const ln of lines) {
    const g = n(ln.qty) * n(ln.rate);
    const amount = paise(g * (1 - n(ln.discount_percent) / 100));
    lineAmounts.push(amount / 100);
    gross += g * 100;
    taxable += amount;
    tax += (amount * n(ln.gst_percent)) / 100;
  }
  let chargePaise = 0;
  for (const c of charges) {
    const a = paise(n(c.amount));
    chargePaise += a;
    tax += (a * n(c.gst_percent)) / 100;
  }
  const subtotal = paise(gross / 100);
  const taxPaise = Math.sign(tax) * Math.round(Math.abs(tax) + 1e-7);
  const cgst = interstate ? 0 : Math.sign(taxPaise) * Math.round(Math.abs(taxPaise) / 2 + 1e-7);
  const sgst = interstate ? 0 : taxPaise - cgst;
  const before = taxable + chargePaise + taxPaise;
  const grand = Math.round(before / 100) * 100;
  return {
    lineAmounts,
    subtotal: subtotal / 100,
    discount: (subtotal - taxable) / 100,
    taxable: taxable / 100,
    cgst: cgst / 100,
    sgst: sgst / 100,
    igst: interstate ? taxPaise / 100 : 0,
    charges: chargePaise / 100,
    roundOff: (grand - before) / 100,
    grandTotal: grand / 100,
  };
}

/** Inter-state when the two GSTINs' state codes (first 2 digits) differ, else by state name. */
export function isInterstate(vendor: { gstin: string | null; state: string | null } | undefined, ours: { gstin: string; state: string } | undefined): boolean {
  if (!vendor || !ours) return false;
  if (vendor.gstin && ours.gstin) return vendor.gstin.slice(0, 2) !== ours.gstin.slice(0, 2);
  if (vendor.state && ours.state) return vendor.state.trim().toLowerCase() !== ours.state.trim().toLowerCase();
  return false;
}

export const STATUS_BADGE: Record<string, string> = {
  draft: "badge-muted",
  submitted: "badge-info",
  sent: "badge-info",
  pending_approval: "badge-warn",
  approved: "badge-ok",
  partly_ordered: "badge-orange",
  ordered: "badge-ok",
  partly_received: "badge-orange",
  received: "badge-ok",
  dispatched: "badge-info",
  closed: "badge-muted",
  rejected: "badge-danger",
  cancelled: "badge-danger",
};

export const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
