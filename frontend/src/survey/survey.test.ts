import { describe, expect, it } from "vitest";
import { calibrate, detectMarkers, homography, invert, measure, apply, polygonArea } from "./marker";
import { project, render } from "./synthetic";
import type { Camera, PlacedMarker } from "./synthetic";
import { formatLength, parseLength, parseSize } from "./units";

describe("typed sizes", () => {
  it("reads feet-inches and metres", () => {
    expect(parseSize("10'6 x 7'3")).toEqual([3.2, 2.21]); // 126" = 3.2004 m, 87" = 2.2098 m
    expect(parseSize(`10' 6" x 7' 3"`)).toEqual([3.2, 2.21]);
    expect(parseSize("3.2 x 2.21")).toEqual([3.2, 2.21]);
    expect(parseSize("3.2×2.21")).toEqual([3.2, 2.21]);
    expect(parseSize("320cm by 221 cm")).toEqual([3.2, 2.21]);
    expect(parseSize("10ft 6in x 7ft 3in")).toEqual([3.2, 2.21]);
    expect(parseSize("10' x 8'")).toEqual([3.048, 2.438]);
    expect(parseSize("10 x 8", "ftin")).toEqual([3.048, 2.438]); // bare numbers are feet for a feet user
    expect(parseSize("3.2")).toBeNull();
    expect(parseSize("ten x 2")).toBeNull();
    expect(parseLength("10'14")).toBeNull(); // 14 inches is not a valid inch part
  });
  it("shows feet-inches to the nearest inch", () => {
    expect(formatLength(3.2004, "ftin")).toBe(`10' 6"`);
    expect(formatLength(3.2004, "m")).toBe("3.20 m");
  });
});

describe("homography", () => {
  it("maps four points exactly and inverts", () => {
    const src = [
      { x: 0, y: 0 },
      { x: 150, y: 0 },
      { x: 150, y: 150 },
      { x: 0, y: 150 },
    ];
    const dst = [
      { x: 100, y: 200 },
      { x: 330, y: 190 },
      { x: 360, y: 400 },
      { x: 90, y: 420 },
    ];
    const h = homography(src, dst);
    src.forEach((p, i) => {
      const q = apply(h, p);
      expect(q.x).toBeCloseTo(dst[i].x, 6);
      expect(q.y).toBeCloseTo(dst[i].y, 6);
      const back = apply(invert(h), q);
      expect(back.x).toBeCloseTo(p.x, 6);
    });
    expect(polygonArea(src)).toBe(22500);
  });
});

async function dictionary(): Promise<Record<number, string>> {
  const mod = (await import("js-aruco2")) as unknown as { AR?: { Dictionary: new (n: string) => { codeList: string[] } } };
  const AR = mod.AR ?? (mod as unknown as { default: { AR: never } }).default.AR;
  const d = new (AR as { Dictionary: new (n: string) => { codeList: string[] } }).Dictionary("ARUCO_MIP_36h12");
  return { 0: d.codeList[0], 1: d.codeList[1] };
}

// a camera 0.6 m above the floor, 1.5 m before the area, looking 15 degrees down
const CAM: Camera = { width: 1280, height: 960, hfovDeg: 90, pos: [1500, -1500, 600], pitchDeg: 15 };
const RECT = { x: 0, y: 0, w: 3000, h: 2000 }; // 3.00 m x 2.00 m
const MARKERS: PlacedMarker[] = [
  { id: 0, x: 1000, y: -900, size: 150 },
  { id: 1, x: 1850, y: -900, size: 150 },
];

describe("marker photo", () => {
  it("the dictionary is the one printed on the marker sheet", async () => {
    const bits = await dictionary();
    expect(bits[0]).toBe((0xd2b63a09d).toString(2).padStart(36, "0"));
    expect(bits[1]).toBe((0x6001134e5).toString(2).padStart(36, "0"));
  });

  it("measures a 3.00 m x 2.00 m rectangle in perspective within 1% of 6.00 sqm", async () => {
    const bits = await dictionary();
    const img = render(CAM, MARKERS, bits, RECT);
    const found = await detectMarkers(img);
    const cal = calibrate(found, img.width);
    expect(cal.ok, cal.ok ? "" : cal.reason).toBe(true);
    if (!cal.ok) return;
    const taps = [
      { x: 0, y: 0 },
      { x: 3000, y: 0 },
      { x: 3000, y: 2000 },
      { x: 0, y: 2000 },
    ].map((p) => project(CAM, p));
    const m = measure(cal, taps);
    console.log(
      `marker test: area ${m.areaSqm.toFixed(4)} sqm, sides ${m.sidesM.map((s) => s.toFixed(3)).join(" / ")} m, markers ${cal.widths.map((w) => (w * 100).toFixed(1)).join(" / ")}% of the width, scale disagreement ${(cal.scaleDisagreement * 100).toFixed(2)}%`,
    );
    expect(Math.abs(m.areaSqm - 6) / 6).toBeLessThan(0.01);
    expect(Math.abs(m.sidesM[0] - 3)).toBeLessThan(0.03);
    expect(Math.abs(m.sidesM[1] - 2)).toBeLessThan(0.02);
  });

  it("still measures within 1% with sensor-like noise in the photo", async () => {
    const bits = await dictionary();
    const img = render(CAM, MARKERS, bits, RECT);
    let seed = 11;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff) - 0.5;
    for (let i = 0; i < img.data.length; i += 4) {
      const n = rnd() * 16; // like the fake camera video and a phone in daylight
      for (let c = 0; c < 3; c++) img.data[i + c] = Math.max(0, Math.min(255, img.data[i + c] + n));
    }
    const cal = calibrate(await detectMarkers(img), img.width);
    expect(cal.ok, cal.ok ? "" : cal.reason).toBe(true);
    if (!cal.ok) return;
    const m = measure(cal, [{ x: 0, y: 0 }, { x: 3000, y: 0 }, { x: 3000, y: 2000 }, { x: 0, y: 2000 }].map((p) => project(CAM, p)));
    console.log(`marker test with noise: area ${m.areaSqm.toFixed(4)} sqm, scale disagreement ${(cal.scaleDisagreement * 100).toFixed(2)}%`);
    expect(Math.abs(m.areaSqm - 6) / 6).toBeLessThan(0.01);
  });

  it("refuses without markers, with a small marker, and when the markers disagree on scale", async () => {
    const bits = await dictionary();
    const none = render(CAM, [], bits, RECT, 1);
    const r1 = calibrate(await detectMarkers(none), none.width);
    expect(r1.ok).toBe(false);
    if (!r1.ok) expect(r1.reason).toMatch(/No marker found/);
    // 0.6 m further back and a little higher, the markers are 6.7 % of the width: "move closer"
    const far: Camera = { ...CAM, pos: [1500, -2100, 800] };
    const small = render(far, MARKERS, bits, RECT, 2);
    const found = await detectMarkers(small);
    expect(found.length).toBe(2);
    const r2 = calibrate(found, small.width);
    expect(r2.ok).toBe(false);
    if (!r2.ok) expect(r2.reason).toMatch(/Move closer/);
    // a sheet printed at 105 %: 157.5 mm read as 150 mm, so the scales disagree by about 5 %
    const scaled = render(CAM, [MARKERS[0], { ...MARKERS[1], size: 157.5 }], bits, RECT);
    const r3 = calibrate(await detectMarkers(scaled), scaled.width);
    expect(r3.ok).toBe(false);
    if (!r3.ok) expect(r3.reason).toMatch(/disagree on scale/);
    // one marker only
    const one = render(CAM, [MARKERS[0]], bits, RECT);
    const r4 = calibrate(await detectMarkers(one), one.width);
    expect(r4.ok).toBe(false);
    if (!r4.ok) expect(r4.reason).toMatch(/Only one marker/);
  });
});
