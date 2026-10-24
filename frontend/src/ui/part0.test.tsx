// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { showsGoLive } from "../ops/Pages";
import { marginOnPrice, rowWindow } from "../pages/tender/BoqTab";
import { NavIcon, PAGE_ICON } from "./navIcons";
import { Table } from "./Table";

afterEach(cleanup);

describe("the BOQ editor", () => {
  it("shows the margin on the price whenever the cost and the rate are filled", () => {
    expect(marginOnPrice({ rate: "888.82", cost_rate: "711.05", margin_percent: null, source: "manual" })).toBe(20);
    expect(marginOnPrice({ rate: "888.82", cost_rate: null, margin_percent: null, source: "manual" })).toBeNull();
    expect(marginOnPrice({ rate: null, cost_rate: null, margin_percent: "15", source: "system" })).toBe(15);
  });

  it("draws only the rows in view of a 5,000-line BOQ", () => {
    const top = rowWindow(0, 800, 5000);
    expect(top.from).toBe(0);
    expect(top.to - top.from).toBeLessThan(80);
    const deep = rowWindow(44 * 3000, 800, 5000);
    expect(deep.from).toBe(2970);
    expect(deep.to - deep.from).toBeLessThan(100);
    expect(rowWindow(44 * 5000, 800, 5000).to).toBe(5000);
  });
});

describe("the go-live banner", () => {
  it("is for the director, the office admin and the super admin only", () => {
    expect(showsGoLive(["director"])).toBe(true);
    expect(showsGoLive(["office_admin"])).toBe(true);
    expect(showsGoLive(["super_admin"])).toBe(true);
    expect(showsGoLive(["site_engineer"])).toBe(false);
    expect(showsGoLive([])).toBe(false);
  });
});

describe("the sidebar", () => {
  it("gives My day, Travel claims, Gang check-in, Petty cash and Escalated their own icons", () => {
    const pages = ["/field", "/field/claims", "/field/gangs", "/petty-cash", "/escalated"];
    const drawn = pages.map((p) => render(<NavIcon name={PAGE_ICON[p]} />).container.innerHTML);
    expect(new Set(drawn).size).toBe(pages.length);
    expect(drawn.every((h) => h.includes("<path") || h.includes("<circle") || h.includes("<rect"))).toBe(true);
  });
});

describe("the active sites on a phone", () => {
  it("are cards: the name as the title, the other columns as label and value", () => {
    const rows = [{ id: 1, name: "Invented site with a long name", pct: "40%" }];
    const { container } = render(
      <Table
        rows={rows}
        rowKey={(r) => r.id}
        label="Active sites"
        cards
        columns={[
          { key: "name", label: "Site", render: (r) => r.name },
          { key: "pct", label: "Progress", render: (r) => r.pct },
        ]}
      />,
    );
    const card = container.querySelector(".row-cards li");
    expect(card?.textContent).toContain("Invented site with a long name");
    expect(card?.querySelector("dt")?.textContent).toBe("Progress");
    expect(card?.querySelector("dd")?.textContent).toBe("40%");
  });
});
