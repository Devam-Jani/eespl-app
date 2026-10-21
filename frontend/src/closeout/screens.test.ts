import { describe, expect, it } from "vitest";
import { sizeText } from "../portal/CloseoutTabs";
import type { Size } from "./Screens";
import { lineQty, metres, oldBillTarget, sizeOut } from "./Screens";

const ft = (f: string, i = ""): Size => ({ mode: "ft", m: "", ft: f, inch: i });
const m = (v: string): Size => ({ mode: "m", m: v, ft: "", inch: "" });

describe("measuring on site", () => {
  it("takes feet and inches, sends them as typed and shows the metres", () => {
    expect(sizeOut(ft("19", "5"))).toBe("19 ft 5 in");
    expect(sizeOut(m("5.918"))).toBe("5.918");
    expect(metres(ft("19", "5")).toFixed(3)).toBe("5.918");
    expect(sizeText("ft", "", "6", "10")).toBe("6 ft 10 in");
  });

  it("works the quantity in the line's unit", () => {
    expect(lineQty("lb", ft("7"), m("1.5"), "", "sqm")?.toFixed(3)).toBe("3.200");
    expect(lineQty("ph", m("7.2"), m("0.3"), "", "sqm")?.toFixed(3)).toBe("2.160");
    expect(lineQty("run", m("3.6"), m(""), "0.15", "rmt")?.toFixed(3)).toBe("3.450");
    expect(lineQty("lb", m("2"), m(""), "", "sqm")).toBeNull();
  });
});

describe("the old bill pages", () => {
  it("open the one bill page", () => {
    expect(oldBillTarget(new URLSearchParams("bill=37"))).toBe("/bills/37?tab=steps");
    expect(oldBillTarget(new URLSearchParams("site=455"))).toBe("/bills?site=455");
    expect(oldBillTarget(new URLSearchParams(""))).toBe("/bills");
  });
});
