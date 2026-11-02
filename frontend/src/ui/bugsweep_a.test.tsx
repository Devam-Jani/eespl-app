import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { readJson } from "../pages/finance/Reports";
import { hasRight } from "../portal/Portal";
import { hourLabel } from "../process/Pages";

// Bug sweep, group A (data/sop/bugs-found-writing-the-sops.md: admin 7, settings 1-8, mywork 1-10)
const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");

describe("client portal buttons follow the client role (admin 7)", () => {
  it("hasRight: no roles set means everything, loading means not yet, else the right itself", () => {
    expect(hasRight(null, "bill.certify")).toBe(true);
    expect(hasRight(undefined, "bill.certify")).toBe(false);
    expect(hasRight(["progress.view"], "snag.raise")).toBe(false);
    expect(hasRight(["progress.view", "snag.raise"], "snag.raise")).toBe(true);
  });
  it("Acknowledge / Sign off, Certify / Reject and the snag buttons are gated by the right the API checks", () => {
    const p = src("../portal/Portal.tsx");
    expect(p).toContain('canSign={hasRight(rights, "inspection.sign")}');
    expect(p).toContain('canCertify={hasRight(rights, "bill.certify")}');
    expect(p).toContain('canRaise={hasRight(rights, "snag.raise")}');
    expect(p).toContain('b.status === "submitted" && !readOnly && canCertify');
    expect(p).toContain('i.client_signoff === "waiting" && !readOnly && canSign');
    expect(p).toContain("const readOnly = preview || !canRaise;");
  });
});

describe("settings", () => {
  it("1: the empty default person is sent as null (the API refuses an empty string)", () => {
    expect(src("../process/Pages.tsx")).toContain("[role]: e.target.value || null");
  });
  it("2: invalid JSON in a Finance box is reported and blocks Save", () => {
    expect(readJson("TDS by vendor type", '{"a": 1}')).toEqual({ value: { a: 1 } });
    const bad = readJson("TDS by vendor type", "{a: 1");
    expect("error" in bad && bad.error.startsWith("TDS by vendor type: this is not valid JSON")).toBe(true);
    const r = src("../pages/finance/Reports.tsx");
    expect(r).not.toContain("JSON.parse(e.target.value)");
    expect(r).toContain("const firstBad = Object.values(bad)[0];");
  });
  it("3 and 5: refused changes show in a red box, never in the green Saved box", () => {
    for (const f of ["../team/Pages.tsx", "../sitecontrol/Pages.tsx", "../quotations/LibraryPages.tsx"]) {
      expect(src(f)).not.toMatch(/\(e\) => setMsg\(errorText\(e\)\)|setMsg\(errorText\(e\)\);/);
    }
    const team = src("../team/Pages.tsx");
    expect(team).toMatch(/await api\(`\/api\/team\/users\/\$\{uid\}\/grants`[\s\S]{0,300}catch \(e\)/);
    const kylas = src("../pages/settings/KylasSettings.tsx");
    expect(kylas).toContain('test.ok ? "alert-ok" : "alert-error"');
  });
  it("4: a refused checklist Save shows its error inside the modal", () => {
    const e = src("../pages/execution/Pages.tsx");
    expect(e).toContain("setFormError(errorText(err));");
    expect(e).toContain('{formError && <div className="alert alert-error">{formError}</div>}');
  });
  it("6: a refused rate stays in the form", () => {
    const a = src("../field/Admin.tsx");
    expect(a).toContain("async function run(p: Promise<unknown>): Promise<boolean>");
    expect(a).toContain('(ok) => ok && setRate({ rate_per_km: "", valid_from: "", vehicle: "bike" })');
  });
  it("7 and 8: planning (planning.edit) edits Stage templates and Checklist templates, as the API allows", () => {
    expect(src("../pages/settings/StageTemplates.tsx")).toContain('can("site.edit") || can("planning.edit")');
    expect(src("../pages/execution/Pages.tsx")).toContain('me?.permissions["inspection.edit"] === "all" || !!me?.permissions["planning.edit"]');
  });
});

describe("my work", () => {
  it("1: Approvals shows the API's total, not the sum of every key (which counted it twice)", () => {
    const l = src("../components/Layout.tsx");
    expect(l).toContain('const approvals = counts["/my-work"] ?? 0;');
    expect(l).not.toContain("Object.values(counts).reduce");
  });
  it("2: a pressed notification turns read on the page at once", () => {
    expect(src("../process/Pages.tsx")).toContain("x.id === n.id ? { ...x, read: true } : x");
  });
  it("3 and 4: a refused email choice shows an error; the summary hour is the set one", () => {
    expect(hourLabel(9)).toBe("9:00 am");
    expect(hourLabel(0)).toBe("12:00 am");
    expect(hourLabel(12)).toBe("12:00 pm");
    expect(hourLabel(18)).toBe("6:00 pm");
    const p = src("../process/Pages.tsx");
    expect(p).not.toContain("(9:00)");
    expect(p).not.toContain("at 9:00 am");
  });
  it("5: a refused claim day edit keeps the row open", () => {
    expect(src("../field/Claims.tsx")).toContain(".then((ok) => ok && setEdit(null))");
  });
  it("6: the day map hides Use road / tracked km once the claim no longer follows it", () => {
    expect(src("../field/Maps.tsx")).toContain("day.basis_locked ?");
  });
  it("7 and 8: the rejection reason shows, and the advance has a Date and a Remark", () => {
    const p = src("../pages/finance/PettyCash.tsx");
    expect(p).toContain("Why: {e.reject_reason}");
    expect(p).toContain('<Field label="Remark">');
    expect(p).toContain("on_date: form.on_date || null");
  });
  it("9: the phone tab My day opens the check-in page (My work keeps its own name)", () => {
    const l = src("../components/Layout.tsx");
    expect(l).toContain('to={can("field.track") ? "/field" : "/my-work"}');
    expect(l).toContain('{can("field.track") ? "My day" : "My work"}');
  });
});
