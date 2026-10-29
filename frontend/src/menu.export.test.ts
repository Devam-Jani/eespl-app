import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { MENU } from "./menu";
import { DETAIL_ROUTES, PUBLIC_ROUTES } from "./routes";

// The roles report (Settings > Roles report, a PDF for the director) and the role SOPs list each
// role's pages from the backend's copy of this menu and of the other routes. UPDATE_MENU=1 npm test
// writes them; otherwise the copies must match.
const FILE = resolve(__dirname, "../../backend/app/ops/menu.json");
const ROUTES = resolve(__dirname, "../../backend/app/ops/routes.json");
const ROUTES_COPY = { detail: DETAIL_ROUTES, public: PUBLIC_ROUTES };
const COPY = MENU.map((i) => ({
  to: i.to,
  label: i.label,
  section: i.section,
  perms: i.perms,
  ...(i.view ? { view: i.view } : {}),
  ...(i.all ? { all: i.all } : {}),
  ...(i.none ? { none: i.none } : {}),
}));

describe("the roles report's menu", () => {
  it("is the app's menu", () => {
    if (process.env.UPDATE_MENU) writeFileSync(FILE, JSON.stringify(COPY, null, 1) + "\n");
    expect(JSON.parse(readFileSync(FILE, "utf8"))).toEqual(COPY);
  });

  it("and its other routes are the app's", () => {
    if (process.env.UPDATE_MENU) writeFileSync(ROUTES, JSON.stringify(ROUTES_COPY, null, 1) + "\n");
    expect(JSON.parse(readFileSync(ROUTES, "utf8"))).toEqual(ROUTES_COPY);
  });
});
