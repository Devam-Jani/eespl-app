import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setAccessToken } from "../api";
import { pickLabel } from "./Helper";
import { browserName, crashReport, firstInAWhile, pagePath, reportForFailure, scrubText, send } from "./report";

const qty = { field: "qty", label: "Line 2: Quantity", plain: "Quantity must be 0 or more.", fix: "Type a number of 0 or more (not a negative one)." };

describe("what the helper reports", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setAccessToken(null);
  });

  it("a wrong entry is reported with its fields' rules, never what was typed", () => {
    const e = new ApiError(422, "Quantity must be 0 or more.", "abcd1234abcd1234", [qty], "POST /api/bills/7/lines");
    const r = reportForFailure(e, "/bills/7");
    expect(r).toMatchObject({ kind: "mistake", page: "/bills/7", status_code: 422, request_id: "abcd1234abcd1234", error: "Quantity must be 0 or more." });
    expect(r).not.toHaveProperty("values");
    expect(JSON.stringify(r)).not.toContain("-5");
  });

  it("a failure on our side is an error with its request id; a refusal the page explains is not reported", () => {
    expect(reportForFailure(new ApiError(500, "Something went wrong", "r1r2r3r4r5", [], "GET /api/sites"), "/sites")).toMatchObject({ kind: "error", status_code: 500, request_id: "r1r2r3r4r5" });
    expect(reportForFailure(new ApiError(0, "The server could not be reached.", "x1x2x3x4x5"), "/sites")?.kind).toBe("error");
    for (const s of [400, 401, 403, 404, 409]) expect(reportForFailure(new ApiError(s, "no"), "/sites")).toBeNull();
    // never about the reporting itself (no loop)
    expect(reportForFailure(new ApiError(500, "x", null, [], "POST /api/me/issues"), "/sites")).toBeNull();
  });

  it("no token, password or key leaves the browser", () => {
    const jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U";
    const out = scrubText(`Bearer ${jwt} password=hunter22 api_key: sk-abcdefghijklmnop token=${jwt}`)!;
    expect(out).not.toContain("hunter22");
    expect(out).not.toContain("sk-abcdefghijklmnop");
    expect(out).not.toContain("eyJhbGci");
    const crash = crashReport(new Error(`fetch failed with Authorization: Bearer ${jwt}`), "/sites", 'pressed "Save"');
    expect(JSON.stringify(crash)).not.toContain("eyJhbGci");
    expect(crash.action).toBe('pressed "Save"');
  });

  it("the page goes without its query string (it can carry values or a token)", () => {
    expect(pagePath("https://app.example/sites/471/takeoff?file=12&token=abc#x")).toBe("/sites/471/takeoff");
    expect(pagePath("/portal/invite/xyz?email=a@b.c")).toBe("/portal/invite/xyz");
  });

  it("the same problem within a minute is sent once", () => {
    const r = { kind: "error" as const, page: "/x", error: "boom", status_code: 500 };
    expect(firstInAWhile(r, 1_000)).toBe(true);
    expect(firstInAWhile(r, 30_000)).toBe(false);
    expect(firstInAWhile(r, 62_000)).toBe(true);
  });

  it("the browser is named short", () => {
    expect(browserName("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")).toBe("Chrome 130 · Windows");
    expect(browserName("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36 EdgA/129 Edg/129.0")).toBe("Edge 129 · Android");
  });

  it("send() posts no form values unless the user agreed, and nothing when signed out", async () => {
    const calls: { url: string; body: string; headers: Headers }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      calls.push({ url, body: String(init.body), headers: new Headers(init.headers) });
      return new Response(JSON.stringify({ issue_id: 3, event_id: 9, status: "new", request_id: null }), { status: 201, headers: { "Content-Type": "application/json" } });
    });
    expect(await send({ kind: "report", page: "/a", words: "x" }, true)).toBeNull(); // signed out
    expect(calls).toHaveLength(0);
    setAccessToken("t");
    await send({ kind: "report", page: "/a", words: "it broke", values: { Quantity: "-5" } }, true);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/me/issues");
    expect(calls[0].body).not.toContain("-5");
    expect(calls[0].headers.get("X-Request-ID")).toMatch(/^[0-9a-f]{16}$/);
    await send({ kind: "report", page: "/a", words: "it broke", include_values: true, values: { Quantity: "-5" } }, true);
    expect(calls[1].body).toContain("-5");
  });

  it("a 422 becomes the plain message and the fields; a request carries an id the server echoes", async () => {
    setAccessToken("t");
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ detail: [{ loc: ["body", "qty"], msg: `${qty.plain} ${qty.fix}`, type: "greater_than_equal", ...qty }] }), {
          status: 422,
          headers: { "Content-Type": "application/json", "X-Request-ID": "feedfeedfeedfeed" },
        }),
    );
    const err = await api("/api/x", { method: "POST", json: { qty: -5 } }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.message).toBe("Quantity must be 0 or more. Type a number of 0 or more (not a negative one).");
    expect(e.fields).toEqual([qty]);
    expect(e.requestId).toBe("feedfeedfeedfeed");
    expect(e.action).toBe("POST /api/x");
  });
});

describe("the wrong field is found by its label", () => {
  it("by the same words, by the field's name, or by a label that starts with them", () => {
    const labels = ["Site", "Contact name *", "Phone (mobile) *", "Quantity", "Expected value (₹)"];
    expect(pickLabel(labels, { field: "contact_name", label: "Contact name", plain: "", fix: "" })).toBe(1);
    expect(pickLabel(labels, qty)).toBe(3);
    expect(pickLabel(labels, { field: "phone", label: "Phone", plain: "", fix: "" })).toBe(2);
    expect(pickLabel(labels, { field: "expected_value", label: "Expected value", plain: "", fix: "" })).toBe(4);
    expect(pickLabel(labels, { field: "gstin", label: "GSTIN", plain: "", fix: "" })).toBe(-1);
  });
});
