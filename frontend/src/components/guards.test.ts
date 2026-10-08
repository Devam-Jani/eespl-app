import { describe, expect, it } from "vitest";
import { isClientLogin } from "./Guards";

describe("isClientLogin", () => {
  it("is true only for the client portal permissions", () => {
    expect(isClientLogin({ "portal.view": "own", "portal.snag": "own" })).toBe(true);
    expect(isClientLogin({ "portal.view": "own", "site.view": "all" })).toBe(false);
    expect(isClientLogin({ "portal.manage": "all" })).toBe(false);
    expect(isClientLogin({})).toBe(false);
  });
});
