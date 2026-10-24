import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { extraPages, followsTabs } = require("../../tools/crawler/pages.cjs") as {
  extraPages: (pathname: string, values: string[]) => string[];
  followsTabs: (pathname: string) => boolean;
};

describe("the nightly crawl", () => {
  it("follows a site's More sections and Open pages, the Measure and bill page among them", () => {
    expect(followsTabs("/sites/12")).toBe(true);
    expect(followsTabs("/sites")).toBe(false);
    const pages = extraPages("/sites/12", ["", "overview", "visits", "/sites/12/measure", "/sites/12/takeoff", "visits"]);
    expect(pages).toEqual(["/sites/12?tab=overview", "/sites/12?tab=visits", "/sites/12/measure", "/sites/12/takeoff"]);
  });

  it("the site page offers Measure and bill under Open (so the crawl finds it)", () => {
    const src = readFileSync(new URL("./pages/SiteDetail.tsx", import.meta.url), "utf8");
    expect(src).toMatch(/\["Measure and bill", `\/sites\/\$\{site\.id\}\/measure`/);
  });
});
