// Part 0 bug sweep, group B (sites): the pure pieces the fixed screens use, and the source of the
// small fixes (a guard, a caught error, a read query parameter).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { zoneBody } from "../../closeout/Pages";
import { SETTABLE_UNITS, firstClickProposes } from "../../takeoff/Pages";
import { dayFromQuery, localToday } from "./DprTab";
import { DRAWING_ACCEPT } from "./DrawingsTab";
import { addScopeBody } from "./ScopeTab";

const src = (p: string) => readFileSync(resolve(__dirname, "../..", p), "utf8");

describe("site page", () => {
  it("adds a scope to a place without a BOQ line", () => {
    expect(addScopeBody("12", "3", " 25 ", "sqm")).toEqual({ boq_line_id: null, node_ids: [12], stage_template_id: 3, qty: "25", unit: "sqm" });
    expect(addScopeBody("12", "3", "4", " ").unit).toBeNull();
    expect(src("pages/site/ScopeTab.tsx")).toContain("Add a scope");
  });

  it("lets a .dxf be picked as a drawing", () => {
    expect(DRAWING_ACCEPT.split(",")).toEqual(expect.arrayContaining([".dwg", ".dxf", ".pdf"]));
    expect(src("pages/site/DrawingsTab.tsx")).not.toContain('accept=".pdf,.png,.jpg,.jpeg,.dwg"');
  });

  it("confirms Send to planning on the work fronts", () => {
    expect(src("pages/site/WorkFronts.tsx")).toMatch(/get\("asked"\) === "1"/);
  });

  it("opens the DPR tab on the day a link asks for", () => {
    expect(dayFromQuery("2026-10-20")).toBe("2026-10-20");
    expect(dayFromQuery(null)).toBe(localToday());
    expect(dayFromQuery("20-10-2026")).toBe(localToday());
    expect(dayFromQuery("2026-13-45")).toBe(localToday());
  });

  it("certifies a hold point only when it can, and offers Add worker on an empty Quick mark", () => {
    expect(src("pages/site/InspectionsTab.tsx")).toContain('task.status === "done" && can("site.edit")');
    const labour = src("pages/site/LabourTab.tsx");
    expect(labour).not.toContain("Add them below");
    expect(labour).toContain('onAddWorker={() => setEditing("new")}');
  });

  it("guards + New area, catches the receiver save, lists Site visits only with sitevisit.log", () => {
    const strip = src("sitecontrol/Pages.tsx");
    expect(strip).toMatch(/can\("site\.update", "site\.edit"\) && \(\s*<Link[^>]*new-area/);
    expect(strip).toContain("(e) => setSaveError(errorText(e))");
    expect(src("pages/SiteDetail.tsx")).toContain('["visits", "Site visits", can("sitevisit.log")]');
  });

  it("keeps the site's radius when the field is empty", () => {
    const maps = src("field/Maps.tsx");
    expect(maps).not.toContain("radius_m: radius ? Number(radius) : null");
    expect(maps).toContain("...(radius ? { radius_m: Number(radius) } : {})");
  });
});

describe("RFI zones", () => {
  it("sends ours or another applicator", () => {
    expect(zoneBody({ name: " Flat 101 ", node_id: "7", ours: true, other_applicator: "x" })).toEqual({ name: "Flat 101", node_id: 7, ours: true, other_applicator: null });
    expect(zoneBody({ name: "Flat 104", node_id: "", ours: false, other_applicator: " Other Co " })).toEqual({ name: "Flat 104", node_id: null, ours: false, other_applicator: "Other Co" });
  });

  it("has the controls, and the checklist sends towers and wings to Structure", () => {
    const pages = src("closeout/Pages.tsx");
    for (const route of ["/zones`, { method: \"POST\"", "/record-signature`", "method: \"DELETE\""]) expect(pages).toContain(route);
    expect(pages).not.toContain("Add them under");
    expect(pages).toContain("?tab=structure");
  });
});

describe("AutoCAD takeoff", () => {
  it("proposes the outline on a first click inside the room", () => {
    expect(firstClickProposes(0, "none")).toBe(true);
    expect(firstClickProposes(0, "end")).toBe(false);
    expect(firstClickProposes(2, "none")).toBe(false);
    expect(src("takeoff/Pages.tsx")).not.toContain("onDoubleClick");
  });

  it("sets the unit with real units only", () => {
    expect(SETTABLE_UNITS.map(([c]) => c).sort()).toEqual([1, 2, 4, 5, 6]);
    expect(src("takeoff/Pages.tsx")).toContain("/units`, { method: \"PUT\"");
  });
});

describe("status board", () => {
  it("downloads the list from the notification and shows Move to only where allowed", () => {
    const team = src("team/Pages.tsx");
    expect(team).toContain('params.get("download") === "1"');
    expect(team).toContain("{s.can_move && (");
  });
});
