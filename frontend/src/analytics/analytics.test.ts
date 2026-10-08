import { describe, expect, it } from "vitest";
import { compact } from "./charts";
import { drillHref, fmtValue } from "./ui";

describe("compact money labels", () => {
  it("uses lakh and crore", () => {
    expect(compact(950)).toBe("₹950");
    expect(compact(12_500)).toBe("₹13 k");
    expect(compact(345_000)).toBe("₹3.5 L");
    expect(compact(12_000_000)).toBe("₹1.2 Cr");
    expect(compact(-450_000)).toBe("-₹4.5 L");
  });
});

describe("tile values", () => {
  it("formats by unit", () => {
    expect(fmtValue(14.666, "pct")).toBe("14.7%");
    expect(fmtValue(null, "inr")).toBe("—");
    expect(fmtValue("past_planned_end", "text")).toBe("past planned end");
  });
});

describe("drill-down links", () => {
  it("carry the tile's filter and the demo switch", () => {
    expect(drillHref({ kind: "invoices", filter: "overdue", days: 60 }, false)).toBe("/drill?kind=invoices&filter=overdue&days=60");
    expect(drillHref({ kind: "sites", filter: "delayed" }, true)).toBe("/drill?kind=sites&filter=delayed&demo=1");
  });
});
