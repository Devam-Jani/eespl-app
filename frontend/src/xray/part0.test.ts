import * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { XFloor, XRoom, XType } from "./geometry";
import { labelSize, placeLabels } from "./labels";
import { roomsGeometry, typeGeometry } from "./scene";
import { roomsFirstByDefault, showsSectionLine } from "./views";

const floor: XFloor = { level: 5, node_id: 5, name: "Floor 5", type: "t", elevation_m: 21.869, height_m: 3.962 };
const room = (name: string, kind: string, x: number): XRoom => ({ node_id: x, key: null, level: 5, kind, name, label: null, outline: [[x, 0], [x + 3, 0], [x + 3, 2], [x, 2]], area_sqm: 6, sunk_m: 0, raise_m: 0, wp_height_m: 0.3 }); // prettier-ignore

describe("the X-ray review (Part 0)", () => {
  it("gives an opened floor its slab face and outline, and keeps its columns", () => {
    const t: XType = { name: "Typical", outline: [[0, 0], [40, 0], [40, 18], [0, 18]], area_sqm: 720, walls: [[0, 9, 40, 9]], columns: [[0, 0, 0.45, 0.45], [40, 18, 0.45, 0.45]], beams: [], cores: [] }; // prettier-ignore
    const g = typeGeometry(t, 3.962, 0.15, 0.15);
    const face = new THREE.Box3().setFromBufferAttribute(g.cutFace.getAttribute("position") as THREE.BufferAttribute);
    expect(face.max.x - face.min.x).toBeCloseTo(40, 6); // the whole floor, not loose wall pieces
    expect(face.max.z - face.min.z).toBeCloseTo(18, 6);
    expect(face.max.y).toBeCloseTo(0.005, 6); // on the slab, under the rooms
    expect(g.cols?.getAttribute("position").count).toBeGreaterThan(0);
    expect(g.shell.getAttribute("instanceStart").count).toBe(4 * 3); // the outline at floor and ceiling, and its corners
  });

  it("does not raise a terrace as a volume (it would fill the top of the building)", () => {
    const rg = roomsGeometry([room("Terrace", "terrace", 0), room("Gents toilet", "toilet", 10)], floor, 0.15)!;
    const [terrace, toilet] = rg.spans;
    const pos = rg.volume.getAttribute("position") as THREE.BufferAttribute;
    const height = (s: typeof terrace) => {
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = s.volStart; i < s.volStart + s.volCount; i++) [lo, hi] = [Math.min(lo, pos.getY(i)), Math.max(hi, pos.getY(i))];
      return hi - lo;
    };
    expect(height(terrace)).toBeLessThan(0.05);
    expect(height(toilet)).toBeGreaterThan(3);
  });

  it("moves colliding labels apart and hides what still collides (shown on hover)", () => {
    // the west toilets: two labels a few pixels apart, as in the review's cutaway
    const raw = [
      { text: "Gents toilet (west)", sub: "8.13 sqm", x: 400, y: 300, nodeId: 1 },
      { text: "Ladies toilet (west)", sub: "6.68 sqm", x: 430, y: 306, nodeId: 2 },
      { text: "Gents toilet (east)", sub: "12.31 sqm", x: 800, y: 300, nodeId: 3 },
    ];
    for (const font of [12, 10]) {
      const placed = placeLabels(raw, font, { width: font === 10 ? 318 * 3 : 1290, height: 680 });
      const shown = placed.filter((p) => !p.hidden);
      for (let i = 0; i < shown.length; i++)
        for (let j = i + 1; j < shown.length; j++) {
          const [a, b] = [shown[i], shown[j]];
          const apart = Math.abs(a.x - b.x) * 2 >= a.w + b.w || Math.abs(a.y + a.dy - (b.y + b.dy)) * 2 >= a.h + b.h;
          expect(apart).toBe(true);
        }
      expect(shown.length).toBe(3); // a step up or down was enough
      expect(placed.find((p) => p.nodeId === 2)!.dy).not.toBe(0);
    }
    expect(labelSize(raw[0], 10).h).toBeGreaterThanOrEqual(25); // two readable lines at 360 px
  });

  it("opens the client's view with the rooms first, and shows the section line to staff only", () => {
    expect(roomsFirstByDefault(true)).toBe(true);
    expect(roomsFirstByDefault(false)).toBe(false);
    expect(showsSectionLine(true, false)).toBe(false);
    expect(showsSectionLine(false, false)).toBe(true);
  });
});
