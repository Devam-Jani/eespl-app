import { describe, expect, it } from "vitest";
import { changeSide } from "./Estimates";

describe("Library changed since issue", () => {
  it("says each side of a change, and when the library no longer covers the material", () => {
    expect(changeSide("12.5", "kg", "1 drum of 20 kg")).toBe("12.5 kg (1 drum of 20 kg)");
    expect(changeSide("12.5", "kg", null)).toBe("12.5 kg");
    expect(changeSide(null, "kg", null)).toBe("not in the library");
  });
});
