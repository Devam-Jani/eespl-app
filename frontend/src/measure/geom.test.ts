import { describe, expect, it } from "vitest";
import { bbox, flatten, levelOf, outlinePath } from "./geom";
import type { Pt } from "./geom";

describe("outlines on screen", () => {
  it("draws a bulge as an SVG arc with its radius, y turned up the right way", () => {
    const circle: Pt[] = [
      [0, 0, 1],
      [4, 0, 1],
    ];
    expect(outlinePath(circle)).toBe("M0 0 A2 2 0 0 0 4 0 A2 2 0 0 0 0 0 Z");
    const square: Pt[] = [
      [0, 0, 0],
      [2, 0, 0],
      [2, 2, 0],
      [0, 2, 0],
    ];
    expect(outlinePath(square)).toBe("M0 0 L2 0 L2 -2 L0 -2 L0 0 Z");
  });

  it("flattens an arc onto its circle (the 3D and the drawing's extent)", () => {
    const pts = flatten([[0, 0, 1], [4, 0, 1]] as Pt[], 64);
    for (const [x, y] of pts) expect(Math.hypot(x - 2, y)).toBeCloseTo(2, 9);
    const [x1, y1, x2, y2] = bbox(pts);
    expect(x1).toBeCloseTo(0, 6);
    expect(x2).toBeCloseTo(4, 6);
    expect(y1).toBeCloseTo(-2, 2); // counter-clockwise from the left: down first
    expect(y2).toBeCloseTo(2, 2);
  });
});

describe("levels on a section", () => {
  it("reads a level with its sign, in mm, and leaves a plain dimension alone", () => {
    expect(levelOf("+1800")).toBe(1800);
    expect(levelOf("-900")).toBe(-900);
    expect(levelOf("+1.800")).toBe(1800);
    expect(levelOf("FFL +600")).toBe(600);
    expect(levelOf("1051")).toBeNull();
    expect(levelOf("SECTION Y-Y")).toBeNull();
  });
});
