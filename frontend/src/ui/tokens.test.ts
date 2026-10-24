import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contrastPairs, cssText, THEMES } from "./tokens";

const FILE = resolve(__dirname, "tokens.css");

describe("the design tokens", () => {
  it("tokens.css is written from tokens.ts (UPDATE_TOKENS=1 rewrites it)", () => {
    if (process.env.UPDATE_TOKENS) writeFileSync(FILE, cssText());
    expect(readFileSync(FILE, "utf8").replace(/\r\n/g, "\n")).toBe(cssText());
  });

  for (const theme of ["dark", "light"] as const) {
    it(`every text colour in the ${theme} theme passes WCAG AA`, () => {
      const low = contrastPairs(THEMES[theme]).filter((c) => c.ratio < c.min);
      expect(low, low.map((c) => `${c.pair}: ${c.ratio} < ${c.min}`).join("\n")).toEqual([]);
    });
  }
});
