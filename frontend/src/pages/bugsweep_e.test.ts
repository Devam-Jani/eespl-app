import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { weeklyNotice } from "../analytics/Pages";
import { payablesTab, tooShort } from "./finance/Payables";
import { indentLinkIntent } from "./material/Indents";
import { issuePlace } from "./material/Stores";

const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");

describe("stores", () => {
  it("Cancel indent follows the API's can_cancel (creator or indent approver, up to approved)", () => {
    const page = src("./material/Indents.tsx");
    expect(page).toContain("{indent.can_cancel && (");
    expect(page).not.toContain("(indent.can_edit || indent.can_approve)");
  });

  it("?open=<id> opens an indent and ?new=1 (Raise indent) opens the New indent form", () => {
    expect(indentLinkIntent(new URLSearchParams("open=7"))).toEqual({ openId: "7", create: false });
    expect(indentLinkIntent(new URLSearchParams("new=1"))).toEqual({ openId: null, create: true });
    expect(src("../ui/CommandPalette.tsx")).toContain("/indents?new=1");
  });

  it("old /indents/<id> links redirect, and new links use ?open=", () => {
    expect(src("../App.tsx")).toContain('<Route path="/indents/:id" element={<OldIndentRedirect />} />');
    expect(src("../team/Pages.tsx")).toContain("navigate(`/indents?open=${r.id}`)");
  });

  it("Add godown and Adjust / opening need store.edit at scope all", () => {
    const page = src("./material/Stores.tsx");
    expect(page).toContain('const allStores = me?.permissions["store.edit"] === "all";');
    expect(page).toContain('const adjust = me?.permissions["store.edit"] === "all";');
    expect(page).toMatch(/\{allStores && \(\s*<Button onClick=\{\(\) => setAdding\(true\)\}>/);
  });

  it("general site use sends the picked area as node_id / new_area_id", () => {
    expect(issuePlace("n:12")).toEqual({ node_id: 12, new_area_id: null });
    expect(issuePlace("a:5")).toEqual({ node_id: null, new_area_id: 5 });
    expect(issuePlace("")).toEqual({ node_id: null, new_area_id: null });
    expect(src("./material/Stores.tsx")).toContain('<Field label="Area used on">');
  });

  it("the freight Year filter also filters the Entries list", () => {
    expect(src("./material/Freight.tsx")).toMatch(/\/api\/material\/freight\$\{queryString\(\{ site_id: siteId, year:/);
  });

  it("a deleted vendor leaves the list (it reloads)", () => {
    const page = src("./Vendors.tsx");
    expect(page).toContain("await onDeleted();");
  });

  it("a refused call log keeps the form open", () => {
    expect(src("../closeout/Pages.tsx")).toContain("if (saved === undefined) return;");
  });

  it("Release / Override say when the reason is too short; Approve's Cancel aborts", () => {
    expect(tooShort("ok", 3, "reason")).toBe("The reason is too short: write at least 3 characters.");
    expect(tooShort(" fine ", 3, "reason")).toBeNull();
    expect(tooShort("four", 5, "note")).toContain("at least 5");
    const page = src("./finance/Payables.tsx");
    expect(page).toContain('if (flagged && !confirm("Accept the differences flagged on this bill?")) return;');
  });

  it("?tab=subcon opens Subcontractor bills", () => {
    expect(payablesTab("subcon")).toBe("subcon");
    expect(payablesTab(null)).toBe("bills");
    expect(payablesTab("nonsense")).toBe("bills");
  });

  it("Day book and Payslip downloads show their errors", () => {
    expect(src("./finance/Reports.tsx")).toContain("downloadFile(`/api/finance/tally/day-book${q}`).catch((err) => setError(errorText(err)))");
    expect(src("./finance/Payroll.tsx")).toContain("downloadFile(`/api/finance/payslips/${p.id}/pdf`).catch((err) => setError(errorText(err)))");
  });
});

describe("sales", () => {
  it("Send the rates to the lines only for tender.margin", () => {
    expect(src("../quotations/QuotationPages.tsx")).toContain('canSend={!!q.can_edit && can("tender.margin")}');
    expect(src("./TenderDetail.tsx")).toContain('canSend={canEdit && draft && can("tender.margin")}');
  });

  it("the civil contractors list reads the clients page's items", () => {
    expect(src("../closeout/Pages.tsx")).toContain("setClients(r?.items ?? [])");
  });

  it("a Kanban drop on Lost opens the lost-reason dialog", () => {
    const page = src("./Leads.tsx");
    expect(page).toContain('if (status === "lost" && !lost) return setLosing(lead);');
    expect(page).toContain("<LeadLostDialog");
  });

  it("follow-up Done shows its error; Log and New revision need the edit right", () => {
    const q = src("../quotations/QuotationPages.tsx");
    expect(q).toContain(".catch((err) => setError(errorText(err)));");
    expect(q).toContain('q.is_latest && q.status !== "won" && q.can_edit && (');
    expect(q).toContain("canLog={!!q.can_edit}");
    expect(src("../team/Pages.tsx")).toContain("{mayLog && (");
  });

  it("Mark final: add to the library needs knowledge.edit", () => {
    expect(src("../costing/Pages.tsx")).toMatch(/\{can\("knowledge\.edit"\) && \(\s*<Button[\s\S]{0,900}Mark final: add to the library/);
  });
});

describe("analytics", () => {
  it("Use the corrected text is for library.edit (tc.edit does not exist)", () => {
    const page = src("../estimate/Checks.tsx");
    expect(page).toContain('can("library.edit") &&');
    expect(page).not.toContain("tc.edit");
  });

  it("File this week's now says when the week is already filed", () => {
    expect(weeklyNotice({ created: false })).toBe("This week's summary is already filed: it is in the list below.");
    expect(weeklyNotice({ created: true })).toContain("is filed");
  });

  it("Consumption variance has Mark reviewed; Merge this into it shows its error", () => {
    expect(src("../sitecontrol/Pages.tsx")).toContain("/api/sitecontrol/reports/consumption/reviewed?site_id=");
    expect(src("../knowledge/Pages.tsx")).toMatch(/\/merge`[\s\S]{0,200}\(e\) => setError\(errorText\(e\)\)/);
  });
});
