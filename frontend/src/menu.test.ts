import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { GROUPS, groupOf, MENU, visibleGroups } from "./menu";

// each role's grants, kept equal to the backend's permission matrix by its own test
const ROLES: Record<string, string[]> = JSON.parse(readFileSync(resolve(__dirname, "../../backend/tests/role_permissions.json"), "utf8"));
const groupsFor = (role: string) => visibleGroups((...codes) => codes.some((c) => ROLES[role].includes(c))).map((g) => g.group);

describe("the menu by group", () => {
  it("puts every page in one of the groups", () => {
    MENU.forEach((i) => expect(GROUPS).toContain(i.section));
    expect(new Set(MENU.map((i) => i.to)).size).toBe(MENU.length);
  });

  it("shows each role only its own groups", () => {
    // what each role may open, from its grants (no Billing for the supervisor, the estimator, stores;
    // no Stores for billing; nothing for a client login, which uses the portal)
    const expected: Record<string, string[]> = {
      accounts: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      billing: ["My work", "Sales", "Planning", "Site", "Billing", "Accounts", "Analytics", "Masters", "Settings"],
      client: [],
      director: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
      estimator: ["My work", "Sales", "Planning", "Site", "Accounts", "Analytics", "Masters", "Settings"],
      office_admin: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
      planning: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      sales: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      site_engineer: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      site_receiver: ["My work", "Site", "Settings"],
      site_supervisor: ["My work", "Sales", "Planning", "Site", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      store_purchase: ["My work", "Sales", "Planning", "Site", "Stores", "Accounts", "Analytics", "Masters", "Settings"],
      super_admin: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
    };
    expect(Object.keys(expected).sort()).toEqual(Object.keys(ROLES).sort());
    Object.entries(expected).forEach(([role, groups]) => expect(groupsFor(role), role).toEqual(groups));
  });

  it("only office admin and the director (and the super admin) see Settings > Client roles", () => {
    const who = Object.keys(ROLES).filter((r) => visibleGroups((...c) => c.some((x) => ROLES[r].includes(x))).some((g) => g.items.some((i) => i.to === "/settings/client-roles")));
    expect(who.sort()).toEqual(["director", "office_admin", "super_admin"]);
  });

  it("finds the group of the page open", () => {
    expect(groupOf("/bills")).toBe("Billing");
    expect(groupOf("/billing/payments")).toBe("Accounts");
    expect(groupOf("/issues")).toBe("Site");
    expect(groupOf("/nowhere")).toBeNull();
  });
});
