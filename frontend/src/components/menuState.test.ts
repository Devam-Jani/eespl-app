import { describe, expect, it } from "vitest";
import { initialMenuOpen, isPhone } from "./menuState";

describe("the side menu on a phone", () => {
  it("is closed by default at 360 px", () => {
    expect(isPhone(360)).toBe(true);
    expect(initialMenuOpen(360)).toBe(false);
  });
  it("stays open on a desktop", () => {
    expect(initialMenuOpen(1600)).toBe(true);
  });
});
