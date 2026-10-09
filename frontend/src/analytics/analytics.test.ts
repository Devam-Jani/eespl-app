import { describe, expect, it } from "vitest";
import { compact, placeLabels } from "./charts";
import { inrCompact } from "../format";
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

describe("scatter labels", () => {
  it("never overlap and stay inside the chart", () => {
    const pts = [
      { x: 350, y: 20, text: "DEMO-S-041" },
      { x: 352, y: 24, text: "DEMO-S-019" },
      { x: 120, y: 200, text: "DEMO-S-046" },
      { x: 124, y: 203, text: "DEMO-S-035" },
      { x: 126, y: 199, text: "DEMO-S-025" },
    ];
    const spots = placeLabels(pts, 360, 360);
    const boxes = spots.flatMap((s, i) => {
      if (!s) return [];
      const w = pts[i].text.length * 5.6;
      const x0 = s.anchor === "start" ? s.x : s.anchor === "end" ? s.x - w : s.x - w / 2;
      return [{ x0, x1: x0 + w, y0: s.y - 9, y1: s.y + 2 }];
    });
    for (const b of boxes) expect(b.x0 >= 2 && b.x1 <= 358).toBe(true);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        expect(a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0).toBe(false);
      }
    expect(spots[0]?.anchor).toBe("end"); // no room on the right edge
  });
});

describe("compact money", () => {
  it("shows crore, lakh or rupees", () => {
    expect(inrCompact(294909829.72)).toBe("₹29.49 Cr");
    expect(inrCompact(789420)).toBe("₹7.89 L");
    expect(inrCompact(72228.4)).toBe("₹72,228");
  });
});
