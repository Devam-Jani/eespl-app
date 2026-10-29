// Bug sweep, group C (site work): the phone's daily report (lines only, the last place submits with a
// work done, a refused report is shown and not retried for ever), My site today counts only its own
// site, Material requests opens on the request My work links to, and the small label fixes.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import { requestFilters } from "../estimate/Requests";
import type { MaterialRequest } from "../estimate/common";
import { linkSite, siteItems } from "../team/siteItems";
import { discard, flush, refused, reportBody, retry, type QueuedReport, type ReportStore } from "./reportQueue";

const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");

function memStore(): ReportStore & { rows: Map<string, QueuedReport> } {
  const rows = new Map<string, QueuedReport>();
  return {
    rows,
    all: async () => [...rows.values()].sort((a, b) => a.at - b.at),
    put: async (r) => void rows.set(r.id, r),
    remove: async (id) => void rows.delete(id),
  };
}

const line = (description: string, node_id: number | null = 1) => ({ description, qty: null, unit: null, node_id, area_scope_id: null });
const report = (id: string, at: number, submit = false, error?: string): QueuedReport => ({ id, site_id: 1, day: "2026-10-29", line: line(`Place ${id}`, at), photos: [], submit, at, error });

describe("the phone's report", () => {
  it("sends only the lines (the DPR tab's fields are not blanked) and a work done on the last place", () => {
    const now = { status: "draft", lines: [line("Toilet 1 · Primer: done", 1)], work_done: null };
    const mid = reportBody(now, { ...report("a", 2), line: line("Toilet 2 · Primer: done", 2) });
    expect(Object.keys(mid).sort()).toEqual(["lines"]);
    expect(mid.lines.map((l) => l.description)).toEqual(["Toilet 1 · Primer: done", "Toilet 2 · Primer: done"]);
    const last = reportBody(now, { ...report("b", 2, true), line: line("Toilet 2 · Primer: done", 2) });
    expect(last.work_done).toBe("Toilet 1 · Primer: done\nToilet 2 · Primer: done");
    // typed on the DPR tab already: kept, not replaced
    expect(reportBody({ ...now, work_done: "Typed" }, report("c", 3, true)).work_done).toBeUndefined();
  });

  it("a refused report is shown, not retried on every flush; Try again and Discard", async () => {
    const store = memStore();
    await store.put(report("bad", 1, false, "Write the work done before submitting"));
    await store.put(report("ok", 2));
    const sent: string[] = [];
    expect(await flush(store, async (r) => void sent.push(r.id))).toEqual({ sent: 1, left: 0 });
    expect(sent).toEqual(["ok"]);
    expect((await refused(store)).map((r) => [r.id, r.error])).toEqual([["bad", "Write the work done before submitting"]]);
    expect(await retry((await refused(store))[0], store, async () => Promise.reject(new ApiError(409, "The DPR is already submitted")))).toBe("refused");
    expect((await refused(store))[0].error).toContain("already submitted");
    await discard("bad", store);
    expect(await refused(store)).toEqual([]);
  });
});

describe("My site today", () => {
  it("counts only this site's items", () => {
    expect(linkSite("/my-site/12?step=attendance")).toBe(12);
    expect(linkSite("/snags?site=13")).toBe(13);
    expect(linkSite("/deliveries/5")).toBeNull();
    const items = [
      { key: "attendance:12", link: "/my-site/12?step=attendance", site_id: 12 },
      { key: "delivery:5", link: "/deliveries/5", site_id: 12 },
      { key: "delivery:6", link: "/deliveries/6", site_id: 1 },
      { key: "snag:3", link: "/snags?site=1", site_id: 1 },
      { key: "snag:3", link: "/snags?site=1" }, // the same snag in the engineer's list: once
      { key: "dpr_approve:9", link: "/sites/1?tab=dpr" },
    ];
    expect(siteItems([{ items }], 1).map((i) => i.key)).toEqual(["delivery:6", "snag:3", "dpr_approve:9"]);
  });
});

describe("Material requests", () => {
  it("opens on the request My work's Decide links to", () => {
    const rows = [{ id: 4, status: "indented" }, { id: 7, status: "requested" }] as MaterialRequest[];
    const [first] = requestFilters(7);
    expect(first.key).toBe("picked");
    expect(rows.filter(first.test).map((r) => r.id)).toEqual([7]);
    expect(requestFilters(null)[0].key).toBe("open");
  });

  it("the reason goes only with a request over the estimate", () => {
    expect(src("../estimate/Requests.tsx")).toContain("reason: preview?.over ? f.reason || null : null");
  });
});

describe("labels and errors", () => {
  it("no internal milestone note on the muster roll; the pilot Excel shows its error; Add worker has a site picker", () => {
    const labour = src("../pages/site/LabourTab.tsx");
    expect(labour).not.toContain("payroll is M5");
    expect(labour).toContain("/api/execution/labour/sites");
    expect(labour).toContain('can("attendance.manage")');
    expect(src("../survey/SurveyPages.tsx")).toContain('downloadFile("/api/surveys/pilot?format=xlsx").catch(');
    expect(src("../survey/Camera.tsx")).not.toContain(".catch(() => next)");
  });

  it("Save and print again downloads the new note; the snag window's edit controls need site.update", () => {
    expect(src("../sitecontrol/Pages.tsx")).toMatch(/onSaved=\{\(x\) => \{[\s\S]{0,300}downloadFile\(`\/api\/sitecontrol\/deliveries\/\$\{x\.id\}\/pdf`\)/);
    expect(src("../pages/Snags.tsx")).toContain('s.status !== "closed" && can("site.update")');
  });

  it("the issue log can raise an issue and hides Resolved on a closed one", () => {
    const issues = src("../closeout/Pages.tsx");
    expect(issues).toContain("+ Raise an issue");
    expect(issues).toContain('i.status !== "resolved" && i.status !== "closed"');
    expect(issues).toContain('label="What was done"');
  });
});
