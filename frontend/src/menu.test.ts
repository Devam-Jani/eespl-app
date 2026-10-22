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

  it("shows each role only the groups its job needs (the go-live review)", () => {
    // reviewed per job: site roles see My work and Site; billing sees Site and Billing; stores
    // see Stores; nothing for a client login (the portal)
    const expected: Record<string, string[]> = {
      accounts: ["My work", "Billing", "Accounts", "Analytics", "Settings"],
      billing: ["My work", "Site", "Billing"],
      client: [],
      director: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
      estimator: ["My work", "Sales", "Site", "Masters"],
      office_admin: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
      planning: ["My work", "Sales", "Planning", "Site", "Billing", "Analytics", "Masters", "Settings"],
      sales: ["My work", "Sales", "Site", "Masters"],
      site_engineer: ["My work", "Site"],
      site_receiver: ["My work", "Site"],
      site_supervisor: ["My work", "Site"],
      store_purchase: ["My work", "Stores", "Analytics", "Masters"],
      super_admin: ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"],
    };
    expect(Object.keys(expected).sort()).toEqual(Object.keys(ROLES).sort());
    Object.entries(expected).forEach(([role, groups]) => expect(groupsFor(role), role).toEqual(groups));
  });

  it("keeps the pages of other jobs out of each menu, while links still open them", () => {
    const pages = (role: string) => visibleGroups((...c) => c.some((x) => ROLES[role].includes(x))).flatMap((g) => g.items.map((i) => i.to));
    expect(pages("billing")).not.toContain("/clients");
    expect(pages("billing")).not.toContain("/quotations");
    expect(pages("accounts")).not.toContain("/settings/stage-templates");
    expect(pages("site_engineer")).not.toContain("/measurements");
    expect(pages("site_engineer")).toContain("/petty-cash");
    expect(pages("store_purchase")).toContain("/grns");
    const clients = MENU.find((i) => i.to === "/clients");
    expect((clients?.view ?? clients?.perms ?? []).some((c) => ROLES.billing.includes(c))).toBe(true); // a billing user may still open it
  });

  it("only office admin and the director (and the super admin) see Settings > Client roles", () => {
    const who = Object.keys(ROLES).filter((r) => visibleGroups((...c) => c.some((x) => ROLES[r].includes(x))).some((g) => g.items.some((i) => i.to === "/settings/client-roles")));
    expect(who.sort()).toEqual(["director", "office_admin", "super_admin"]);
  });

  it("gives sales its clients' bills read-only under Sales, and nobody else (Part 0 of the X-ray prompt)", () => {
    const holders = (to: string) => Object.keys(ROLES).filter((r) => visibleGroups((...c) => c.some((x) => ROLES[r].includes(x))).some((g) => g.items.some((i) => i.to === to)));
    expect(holders("/sales/bills")).toEqual(["sales"]);
    expect(holders("/sales/work-orders")).toEqual(["sales"]);
    expect(holders("/bills")).not.toContain("sales");
    expect(groupOf("/sales/bills")).toBe("Sales");
  });

  it("finds the group of the page open", () => {
    expect(groupOf("/bills")).toBe("Billing");
    expect(groupOf("/billing/payments")).toBe("Accounts");
    expect(groupOf("/issues")).toBe("Site");
    expect(groupOf("/nowhere")).toBeNull();
  });
});
