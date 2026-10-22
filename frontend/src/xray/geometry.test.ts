import { describe, expect, it } from "vitest";
import type { NodeStatus } from "../pages/site/three/colors";
import type { Building, P, TimelineRow, XFloor, XRoom } from "./geometry";
import { addDays, bloomOn, columnsPerFloor, explodeOffset, floorsOfType, polygonArea, replayRange, roomSolid, slabOf, stairSteps, statusAt } from "./geometry";

const floor = (level: number, type: string | null, elevation: number, height = 3): XFloor => ({ level, node_id: level + 100, name: `Floor ${level}`, type, elevation_m: elevation, height_m: height });

describe("the building's geometry", () => {
  it("gives an L-shaped slab its true area (not its bounding box)", () => {
    // 20 x 10 with a 8 x 6 corner cut out: 200 - 48 = 152 sqm
    const L: P[] = [
      [0, 0],
      [20, 0],
      [20, 4],
      [12, 4],
      [12, 10],
      [0, 10],
    ];
    expect(polygonArea(L)).toBeCloseTo(152, 6);
    const s = slabOf(L, floor(3, "t", 9.45), 0.15);
    expect(s.area).toBeCloseTo(152, 6);
    expect(s.top).toBeCloseTo(9.45, 6);
    expect(s.bottom).toBeCloseTo(9.3, 6);
  });

  it("drops a sunken room's floor by its sunk depth below the floor level", () => {
    const room: XRoom = { node_id: 1, key: "a", level: 3, kind: "toilet", name: "Toilet 1", label: "TOILET", outline: [[0, 0], [2, 0], [2, 1.5], [0, 1.5]], area_sqm: 3, sunk_m: 0.2, raise_m: 0, wp_height_m: 0.3 }; // prettier-ignore
    const r = roomSolid(room, floor(3, "t", 9.45));
    expect(r.bottom).toBeCloseTo(9.25, 6); // 9.45 - 0.2
    expect(r.band).toBeCloseTo(0.3, 6);
    expect(r.top).toBeCloseTo(9.25 + 0.3 + 0.2, 6);
    expect(r.area).toBeCloseTo(3, 6);
    // full height in a shower: the band never goes above the floor height
    expect(roomSolid({ ...room, wp_height_m: 9 }, floor(3, "t", 9.45, 3.2)).band).toBeCloseTo(3.2, 6);
  });

  it("repeats a typical floor on floors 3 to 12 with its columns, at their heights", () => {
    const floors: XFloor[] = [floor(0, "ground", 0.45, 4.2), floor(1, "first", 4.65), floor(2, "first", 7.65)];
    for (let level = 3; level <= 12; level++) floors.push(floor(level, "typical", 7.65 + (level - 2) * 3));
    const b: Pick<Building, "floors" | "types"> = {
      floors,
      types: {
        ground: { name: "Ground", outline: [], area_sqm: 0, walls: [], columns: [[0, 0, 0.6, 0.6]], beams: [], cores: [] },
        first: { name: "First", outline: [], area_sqm: 0, walls: [], columns: [[0, 0, 0.45, 0.45], [6, 0, 0.45, 0.45]], beams: [], cores: [] },
        typical: { name: "Typical", outline: [], area_sqm: 0, walls: [], columns: [[0, 0, 0.45, 0.45], [6, 0, 0.45, 0.45], [6, 5, 0.3, 0.6]], beams: [], cores: [] },
      },
    };
    const typical = floorsOfType(b, "typical");
    expect(typical.map((f) => f.level)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(typical[0].elevation_m).toBeCloseTo(10.65, 6);
    expect(typical[9].elevation_m - typical[8].elevation_m).toBeCloseTo(3, 6);
    const cols = columnsPerFloor(b);
    expect(cols.filter((c) => c.level >= 3)).toHaveLength(30); // 3 per typical floor x 10
    expect(cols.filter((c) => c.level === 1)).toHaveLength(2);
    expect(cols.find((c) => c.level === 0)?.height).toBeCloseTo(4.2, 6); // the ground floor's own height
  });

  it("makes a stair's risers from the floor height (default height / 150 mm, an even count)", () => {
    const core: P[] = [[0, 0], [5, 0], [5, 2.4], [0, 2.4]]; // prettier-ignore
    const steps = stairSteps(core, 3.0, 0.15);
    expect(steps).toHaveLength(20); // 3.0 / 0.15
    expect(steps[19].bottom + steps[19].h).toBeCloseTo(3.0, 6); // the last riser reaches the next floor
    expect(steps.every((s) => s.d === 1.2)).toBe(true); // two flights side by side in the 2.4 m core
    expect(stairSteps(core, 3.2, 0.15)).toHaveLength(22); // 21.3 -> 21 -> even 22
    expect(stairSteps(core, 3.0, 0.15, 18)).toHaveLength(18); // risers given by the user
  });

  it("spreads the floors apart in the explode view", () => {
    expect(explodeOffset(0, 1)).toBe(0);
    expect(explodeOffset(5, 1)).toBe(20);
    expect(explodeOffset(5, 0.5)).toBe(10);
  });
});

describe("the status on a past date", () => {
  const live: NodeStatus = { percent: 100, counts: { not_started: 0, in_progress: 0, done: 2, certified: 1, blocked: 0 }, tasks: 3, current_step: null, next_step: null, is_late: false, waiting_certification: false, has_scope: true, template_ids: [1] };
  // surface prep 1-5 Aug, membrane (a hold point, certified 20 Aug) 6-12 Aug, protection screed 21-25 Aug
  const tl: TimelineRow[] = [
    ["Surface prep", "2026-08-01", "2026-08-05", "2026-08-01", "2026-08-05", "done", false, null],
    ["Membrane", "2026-08-06", "2026-08-10", "2026-08-06", "2026-08-12", "certified", true, "2026-08-20"],
    ["Protection screed", "2026-08-21", "2026-08-25", "2026-08-21", "2026-08-25", "done", false, null],
  ];
  const today = "2026-10-22";

  it("matches the stage dates day by day", () => {
    expect(statusAt(tl, "2026-07-30", today, live).category).toBe("not_started");
    expect(statusAt(tl, "2026-08-03", today, live).category).toBe("progress");
    expect(statusAt(tl, "2026-08-11", today, live)).toMatchObject({ category: "progress", late: true }); // membrane due the 10th, done the 12th
    expect(statusAt(tl, "2026-08-15", today, live).category).toBe("hold"); // membrane done, waiting for its certificate
    expect(statusAt(tl, "2026-08-22", today, live).category).toBe("progress");
    expect(statusAt(tl, "2026-08-26", today, live)).toMatchObject({ category: "done", percent: 100 });
  });

  it("shows the live status today, and nothing to do as no scope", () => {
    expect(statusAt(tl, today, today, live).category).toBe("done");
    expect(statusAt([], "2026-08-03", today, { ...live, has_scope: false }).category).toBe("none");
  });

  it("replays from the first task's start up to today, never beyond", () => {
    expect(replayRange([tl, []], today)).toEqual(["2026-08-01", today]);
    expect(addDays("2026-08-30", 3)).toBe("2026-09-02");
  });

  it("glows unless the device is weak, or the setting says so", () => {
    expect(bloomOn("auto", 8, false)).toBe(true);
    expect(bloomOn("auto", 4, false)).toBe(false);
    expect(bloomOn("auto", 8, true)).toBe(false);
    expect(bloomOn("on", 2, true)).toBe(true);
    expect(bloomOn("off", 16, false)).toBe(false);
  });
});
