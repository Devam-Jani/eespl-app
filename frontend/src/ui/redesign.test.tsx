// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "../api";
import { flush, sendOrKeep, type QueuedReport, type ReportStore } from "../field/reportQueue";
import { placesToday, sendLabel } from "../field/TodayReport";
import { pageFor, STEPS } from "../help/HowItWorks";
import { formatKpi } from "../home/Home";
import type { SiteTask } from "../types";
import { ApiError } from "../api";
import { localHits } from "./CommandPalette";
import { applyTheme, rememberLocally, storedTheme, useTheme } from "./theme";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  setAccessToken(null);
});

const canOf = (perms: string[]) => (...codes: string[]) => codes.some((c) => perms.includes(c));

describe("the theme, per person", () => {
  it("each person's choice is their own, and the last person's shows before sign-in", () => {
    rememberLocally("u1", "light");
    rememberLocally("u2", "dark");
    expect(storedTheme("u1")).toBe("light");
    expect(storedTheme("u2")).toBe("dark");
    expect(storedTheme(null)).toBe("dark"); // the last to choose was u2
    rememberLocally("u1", "light");
    expect(storedTheme(null)).toBe("light");
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("choosing saves it for the person on the server and applies it at once", async () => {
    const calls: { url: string; body: string }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      calls.push({ url, body: String(init.body) });
      return new Response(JSON.stringify({ theme: "light" }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    setAccessToken("t");
    let choose: (t: "dark" | "light") => void = () => {};
    function T() {
      const [, set] = useTheme("u9", null);
      choose = set;
      return null;
    }
    render(<T />);
    await act(async () => choose("light"));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(calls).toEqual([{ url: "/api/auth/theme", body: JSON.stringify({ theme: "light" }) }]);
    expect(storedTheme("u9")).toBe("light");
  });

  it("the saved choice wins over this browser's copy", () => {
    rememberLocally("u3", "dark");
    function T() {
      useTheme("u3", "light");
      return null;
    }
    render(<T />);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("search anywhere: pages and actions", () => {
  it("only the pages and actions the role may open", () => {
    const engineer = canOf(["site.view", "dpr.view", "dpr.edit", "site.update"]);
    const titles = localHits("report", engineer).map((h) => h.title);
    expect(titles).toContain("New daily report");
    expect(localHits("indent", engineer).map((h) => h.title)).not.toContain("Raise indent");
    expect(localHits("quotation", engineer)).toEqual([]);
    const sales = canOf(["leads.view", "leads.edit", "quotation.view", "quotation.edit"]);
    expect(localHits("quotation", sales).map((h) => h.title)).toEqual(["New quotation", "Quotations"]);
    expect(localHits("users", sales)).toEqual([]);
    expect(localHits("", sales)).toEqual([]);
  });
});

describe("today's report on the phone", () => {
  const task = (id: number, node: number, order: number, status: SiteTask["status"], start: string | null, path = "Tower A › Floor 5 › Gents toilet (east)"): SiteTask =>
    ({ id, node_id: node, sort_order: order, status, planned_start: start, name: `Step ${order}`, node_path: path, area_scope_id: 7 }) as unknown as SiteTask;

  it("the places due today and their current step", () => {
    const places = placesToday(
      [
        task(1, 10, 1, "done", "2026-10-01"),
        task(2, 10, 2, "in_progress", "2026-10-20"),
        task(3, 10, 3, "not_started", "2026-10-30"),
        task(4, 11, 1, "not_started", "2026-11-05", "Tower A › Floor 6 › Ladies toilet"),
        task(5, 12, 1, "done", "2026-10-01", "Tower A › Floor 5 › Terrace"),
      ],
      "2026-10-23",
    );
    expect(places).toHaveLength(1); // floor 6 not due yet, the terrace finished
    expect(places[0]).toMatchObject({ node_id: 10, name: "Gents toilet (east)", floor: "Floor 5", at: 2 });
    expect(places[0].current?.id).toBe(2);
  });

  it("the send button says what is missing until the report is complete", () => {
    expect(sendLabel(null, "", "", 0, true)).toEqual({ ready: false, label: "Choose the work done to send" });
    expect(sendLabel("done", "19", "14", 1, true)).toEqual({ ready: false, label: "Fix the length to send" });
    expect(sendLabel("done", "20", "2", 0, true)).toEqual({ ready: false, label: "Add a photo to send" });
    expect(sendLabel("done", "20", "2", 1, true)).toEqual({ ready: true, label: "Send today's report" });
    expect(sendLabel("none", "", "", 0, true).ready).toBe(true); // no work: nothing to measure or photograph
  });

  it("without signal it is kept on the phone and sent, oldest first, when the signal is back", async () => {
    const rows = new Map<string, QueuedReport>();
    const store: ReportStore = {
      all: async () => [...rows.values()].sort((a, b) => a.at - b.at),
      put: async (r) => void rows.set(r.id, r),
      remove: async (id) => void rows.delete(id),
    };
    const report = (id: string, at: number): QueuedReport => ({ id, site_id: 1, day: "2026-10-23", at, photos: [], submit: false, line: { description: id, qty: 6.147, unit: "m", node_id: 10, area_scope_id: 7 } });
    const offline = async () => {
      throw new ApiError(0, "The server could not be reached.");
    };
    expect(await sendOrKeep(report("b", 2), store, offline)).toBe("kept");
    expect(await sendOrKeep(report("a", 1), store, offline)).toBe("kept");
    expect(await flush(store, offline)).toEqual({ sent: 0, left: 2 });
    const sent: string[] = [];
    expect(await flush(store, async (r) => void sent.push(r.id))).toEqual({ sent: 2, left: 0 });
    expect(sent).toEqual(["a", "b"]);
    // a refusal (not a lost connection) is said, not kept silently
    await expect(sendOrKeep(report("c", 3), store, async () => Promise.reject(new ApiError(422, "Quantity must be 0 or more.")))).rejects.toThrow("Quantity");
  });
});

describe("how the app works", () => {
  it("each step opens its page for the roles that may open it", () => {
    const sales = canOf(["leads.view", "leads.edit", "quotation.view", "tender.view", "wo.edit", "closeout.payments", "site.view"]);
    expect(pageFor(STEPS[0].to, sales)).toBe("/leads");
    expect(pageFor(STEPS[3].to, sales)).toBe("/sales/work-orders"); // sales' own copy of the work orders
    expect(pageFor(STEPS[6].to, sales)).toBeNull(); // the measurement book is billing's
    const engineer = canOf(["site.view", "dpr.view", "dpr.edit"]);
    expect(pageFor(STEPS[5].to, engineer)).toBe("/daily-reports");
    expect(pageFor(STEPS[7].to, engineer)).toBeNull();
    expect(STEPS.map((s) => s.n)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });
});

describe("the dashboard's numbers", () => {
  it("money, percent, counts and 'n of m'", () => {
    expect(formatKpi({ value: 48200000, unit: "inr" })).toBe("₹4.82 Cr");
    expect(formatKpi({ value: 3860000, unit: "inr" })).toBe("₹38.60 L");
    expect(formatKpi({ value: 18, of: 23, unit: "of" })).toBe("18 of 23");
    expect(formatKpi({ value: 62.4, unit: "pct" })).toBe("62%");
    expect(formatKpi({ value: null, unit: "count" })).toBe("—");
  });
});
