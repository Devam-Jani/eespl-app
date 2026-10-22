import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { MENU } from "./menu";

// The roles report (Settings > Roles report, a PDF for the director) lists each role's pages from
// the backend's copy of this menu. UPDATE_MENU=1 npm test writes it; otherwise the two must match.
const FILE = resolve(__dirname, "../../backend/app/ops/menu.json");
const COPY = MENU.map((i) => ({
  to: i.to,
  label: i.label,
  section: i.section,
  perms: i.perms,
  ...(i.all ? { all: i.all } : {}),
}));

describe("the roles report's menu", () => {
  it("is the app's menu", () => {
    if (process.env.UPDATE_MENU) writeFileSync(FILE, JSON.stringify(COPY, null, 1) + "\n");
    expect(JSON.parse(readFileSync(FILE, "utf8"))).toEqual(COPY);
  });
});
