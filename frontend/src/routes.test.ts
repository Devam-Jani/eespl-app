import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { MENU } from "./menu";
import { DETAIL_ROUTES, PUBLIC_ROUTES, REDIRECTS } from "./routes";

// App.tsx's routes are the menu's pages and routes.ts's lists: a new page goes in one of them, so the
// SOPs' check (backend tests/test_sops.py) sees it.
const APP = readFileSync(resolve(__dirname, "App.tsx"), "utf8");
const NESTED: Record<string, string> = { "sites/:id": "/portal/sites/:id", reports: "/portal/reports", sop: "/portal/sop" };

describe("the app's routes", () => {
  it("are all listed", () => {
    const paths = [...APP.matchAll(/path="([^"]+)"/g), ...APP.matchAll(/\["(\/[^"]+)", /g)].map((m) => NESTED[m[1]] ?? m[1]);
    const known = new Set([...MENU.map((i) => i.to), ...DETAIL_ROUTES.map((r) => r.path), ...PUBLIC_ROUTES, ...REDIRECTS, "*", "/dev/ui"]);
    expect(paths.filter((p) => !known.has(p))).toEqual([]);
  });

  it("guard each detail page with routes.ts", () => {
    for (const r of DETAIL_ROUTES.filter((x) => !x.path.startsWith("/portal"))) {
      expect(APP, r.path).toContain(`routePerms("${r.path}")`);
    }
  });
});
