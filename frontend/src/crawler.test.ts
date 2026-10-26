import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { extraPages, followsTabs, longestGap, sleptDuring } = require("../../tools/crawler/pages.cjs") as {
  extraPages: (pathname: string, values: string[]) => string[];
  followsTabs: (pathname: string) => boolean;
  longestGap: (ticks: number[]) => number;
  sleptDuring: (o: { ms: number; monoMs?: number; maxGapMs?: number; errors?: string[]; sinceWakeMs?: number; slowMs?: number }) => string | null;
};

describe("the nightly crawl", () => {
  it("follows a site's More sections and Open pages, the Measure and bill page among them", () => {
    expect(followsTabs("/sites/12")).toBe(true);
    expect(followsTabs("/sites")).toBe(false);
    const pages = extraPages("/sites/12", ["", "overview", "visits", "/sites/12/measure", "/sites/12/takeoff", "visits"]);
    expect(pages).toEqual(["/sites/12?tab=overview", "/sites/12?tab=visits", "/sites/12/measure", "/sites/12/takeoff"]);
  });

  it("opens a page again when the PC slept, not when the page was slow", () => {
    // the heartbeat ticks a second apart; a sleep leaves a long gap
    expect(longestGap([0, 1000, 2000, 3000])).toBe(1000);
    expect(longestGap([0, 1000, 1015000, 1016000])).toBe(1014000);
    expect(longestGap([5])).toBe(0);
    // the /payroll of 1014 s: the heartbeat stood still, the clock jumped, the network was suspended
    expect(sleptDuring({ ms: 1014534, maxGapMs: 1014000 })).toMatch(/stood still for 1014 s/);
    expect(sleptDuring({ ms: 1014534, monoMs: 900 })).toMatch(/clock jumped/);
    expect(sleptDuring({ ms: 900, errors: ["net::ERR_NETWORK_IO_SUSPENDED GET /api/notifications"] })).toMatch(/suspended/);
    expect(sleptDuring({ ms: 1014534 })).toMatch(/longer than a page open can take/);
    // the slow pages just after waking (/tally 6.0 s, /site-profit 5.4 s) are opened again once awake
    expect(sleptDuring({ ms: 6040, sinceWakeMs: 20000 })).toMatch(/just after the PC woke/);
    // a page that is just slow, or a fast one: reported as it is
    expect(sleptDuring({ ms: 6040, monoMs: 6035, maxGapMs: 1100, sinceWakeMs: 600000 })).toBeNull();
    expect(sleptDuring({ ms: 6040 })).toBeNull();
    expect(sleptDuring({ ms: 800, sinceWakeMs: 1000, errors: ["net::ERR_FAILED GET /api/x"] })).toBeNull();
  });

  it("the site page offers Measure and bill under Open (so the crawl finds it)", () => {
    const src = readFileSync(new URL("./pages/SiteDetail.tsx", import.meta.url), "utf8");
    expect(src).toMatch(/\["Measure and bill", `\/sites\/\$\{site\.id\}\/measure`/);
  });
});
