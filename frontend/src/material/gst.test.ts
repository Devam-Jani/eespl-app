import { describe, expect, it } from "vitest";
import { isInterstate, poTotals } from "./gst";

const LINES = [
  { qty: "10", rate: "1000", discount_percent: "10", gst_percent: "18" },
  { qty: "3", rate: "333.33", gst_percent: "12" },
];
const FREIGHT = [{ amount: "500", gst_percent: "18" }];

describe("poTotals (matches the server's test_gst_* cases)", () => {
  it("intra-state: discount before tax, CGST + SGST, round off", () => {
    const t = poTotals(LINES, FREIGHT, false);
    expect(t.lineAmounts).toEqual([9000, 999.99]);
    expect(t.subtotal).toBe(10999.99);
    expect(t.discount).toBe(1000);
    expect(t.taxable).toBe(9999.99);
    expect([t.cgst, t.sgst, t.igst]).toEqual([915, 915, 0]);
    expect(t.charges).toBe(500);
    expect(t.grandTotal).toBe(12330);
    expect(t.roundOff).toBe(0.01);
  });

  it("inter-state: all IGST", () => {
    const t = poTotals(LINES, FREIGHT, true);
    expect([t.cgst, t.sgst, t.igst]).toEqual([0, 0, 1830]);
    expect(t.grandTotal).toBe(12330);
  });

  it("empty inputs give zeros", () => {
    expect(poTotals([], [], false).grandTotal).toBe(0);
  });
});

describe("isInterstate", () => {
  const ours = { gstin: "24AAACE1234A1Z1", state: "Gujarat" };
  it("compares the GSTIN state codes", () => {
    expect(isInterstate({ gstin: "24ABCDE1234F1Z5", state: null }, ours)).toBe(false);
    expect(isInterstate({ gstin: "27ABCDE1234F1Z5", state: null }, ours)).toBe(true);
  });
  it("falls back to the state name, then intra-state", () => {
    expect(isInterstate({ gstin: null, state: "maharashtra" }, ours)).toBe(true);
    expect(isInterstate({ gstin: null, state: null }, ours)).toBe(false);
  });
});
