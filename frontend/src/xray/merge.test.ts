import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { floorCopy, MAX_MERGED_FLOORS, mergeFloors } from "./scene";

describe("the building's structure in one object per material", () => {
  it("lifts each floor's copy to its level and marks its vertices with the floor", () => {
    const box = new THREE.BoxGeometry(2, 1, 2);
    const copies = [0, 1, 2].map((i) => floorCopy(box, 0.45 + i * 3, i, true));
    const all = mergeFloors(copies)!;
    const floor = all.getAttribute("aFloor") as THREE.BufferAttribute;
    const pos = all.getAttribute("position") as THREE.BufferAttribute;
    expect(floor.count).toBe(pos.count);
    expect(new Set(Array.from(floor.array))).toEqual(new Set([0, 1, 2]));
    const ys = (f: number) => Array.from({ length: pos.count }, (_, i) => i).filter((i) => floor.getX(i) === f).map((i) => pos.getY(i));
    expect(Math.min(...ys(2))).toBeCloseTo(0.45 + 6 - 0.5, 6); // floor 2's copy sits at its level
    expect(all.getAttribute("normal")).toBeTruthy(); // lit in the realistic view
  });

  it("keeps lines without normals and merges nothing into nothing", () => {
    const lines = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0], 3));
    const c = floorCopy(lines, 3, 4, false);
    expect(c.getAttribute("normal")).toBeUndefined();
    expect(c.getAttribute("aFloor").getX(0)).toBe(4);
    expect(mergeFloors([])).toBeNull();
    expect(MAX_MERGED_FLOORS).toBeGreaterThanOrEqual(64);
  });
});
