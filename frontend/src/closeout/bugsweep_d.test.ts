import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { raBillPath } from "../pages/finance/Billing";
import { newestId, termsBody, termsForm, woListPath } from "./Entry";

const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");

describe("raise RA bill and the client billing page", () => {
  it("lands on Client billing with the site picked and the new bill open (no /billing/ra route)", () => {
    expect(raBillPath(12, 345)).toBe("/billing?site=12&ra=345");
    const ready = src("../sitecontrol/Pages.tsx");
    expect(ready).toContain("navigate(raBillPath(siteId, r.ra_bill_id))");
    expect(ready).not.toContain("/billing/ra/");
  });

  it("says who is told about work not billed (billing, the salesperson, then the director)", () => {
    const ready = src("../sitecontrol/Pages.tsx");
    expect(ready).toContain("the director is alerted");
    expect(ready).not.toContain("billing and the site in-charge");
  });

  it("names where a new RA bill's quantities come from", () => {
    const billing = src("../pages/finance/Billing.tsx");
    expect(billing).toContain("New RA bill (from the approved measurements)");
    expect(billing).not.toContain("(from progress)");
  });
});

describe("client work orders", () => {
  it("go back to the list in the person's own menu", () => {
    expect(woListPath(true)).toBe("/work-orders");
    expect(woListPath(false)).toBe("/sales/work-orders");
  });

  it("send the typed terms as the API takes them", () => {
    const f = termsForm("WO/7", { payment_days: 45, payment_basis: "certification", retention_percent: "5.00", scope_on_us: ["material lifting and shifting"], penalty: null });
    expect(f.payment_days).toBe("45");
    expect(f.scope_on_us).toBe("material lifting and shifting");
    const body = termsBody({ ...f, guarantee_years: "10", scope_on_client: "water, electricity ,", advance_percent: "" });
    expect(body).toMatchObject({
      client_ref: "WO/7",
      payment_days: 45,
      payment_basis: "certification",
      retention_percent: "5.00",
      advance_percent: null,
      guarantee_years: 10,
      penalty: null,
      scope_on_client: ["water", "electricity"],
    });
  });

  it("the list has a New work order button for wo.edit, and the guarantee export is only for closeout.billing", () => {
    const pages = src("./Pages.tsx");
    expect(pages).toMatch(/can\("wo\.edit"\) && \(\s*<div className="page-actions">\s*<NewWorkOrder/);
    expect(pages).toMatch(/can\("closeout\.billing"\) && \(\s*<div className="page-actions">\s*<Button onClick=\{\(\) => void downloadFile\("\/api\/closeout\/past-projects\.xlsx"\)/);
  });
});

describe("labour claims", () => {
  it("photos go to the claim just made (the newest)", () => {
    expect(newestId([{ id: 3 }, { id: 9 }, { id: 5 }])).toBe(9);
    expect(newestId([])).toBeNull();
  });
});
