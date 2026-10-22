import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { IfcAPI } from "web-ifc";
import { STATUS_COLORS } from "../pages/site/three/colors";
import { ifcColor, parseIfc, tooBig } from "./ifc";

describe("a BIM (IFC) file", () => {
  it("loads a small invented file, and a linked element takes its place's status colour", async () => {
    const api = new IfcAPI();
    await api.Init(undefined, true);
    const els = parseIfc(api, new Uint8Array(readFileSync(resolve(__dirname, "testdata/invented-small.ifc"))));
    const slab = els.find((e) => e.type === "IFCSLAB");
    const space = els.find((e) => e.type === "IFCSPACE");
    expect(slab?.name).toBe("Slab floor 3");
    expect(space?.name).toBe("T1");
    expect(slab!.indices.length).toBeGreaterThanOrEqual(36); // a box: 12 triangles
    // the slab is 12 x 8 m, 0.15 thick (Y up)
    const xs = [...slab!.positions].filter((_, i) => i % 3 === 0);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(12, 3);
    // planning links the toilet space to place 501, which is done; the slab stays unlinked
    const states = new Map([[501, { category: "done" as const }]]);
    const links = { [String(space!.expressID)]: 501 };
    expect(ifcColor(space!, links, states)).toBe(STATUS_COLORS.done);
    expect(ifcColor(slab!, links, states)).toBeNull();
  });

  it("says plainly when a file is too big for an office laptop", () => {
    expect(tooBig(149 * 1024 * 1024, 150)).toBe(false);
    expect(tooBig(151 * 1024 * 1024, 150)).toBe(true);
  });
});
