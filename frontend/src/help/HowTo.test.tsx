// @vitest-environment jsdom
// "How to" opens the page's own section of the role SOP: the menu page as it is, a detail page by its
// route pattern (the backend maps it to the page section that covers it, tests/test_sops.py).
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { HowToLink, routeKey } from "./HowTo";

afterEach(cleanup);

function linkAt(path: string, base?: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <HowToLink base={base} />
    </MemoryRouter>,
  );
  return screen.queryByRole("link", { name: "How to" });
}

describe("How to", () => {
  it("knows the page: a menu page, or a detail page's pattern", () => {
    expect(routeKey("/daily-reports")).toBe("/daily-reports");
    expect(routeKey("/my-site/12/report")).toBe("/my-site/:id/report");
    expect(routeKey("/sites/7/takeoff")).toBe("/sites/:id/takeoff");
    expect(routeKey("/nowhere")).toBeNull();
  });

  it("links to that page's section of the person's SOP", () => {
    expect(linkAt("/my-site/12/report")?.getAttribute("href")).toBe("/help/sop?page=%2Fmy-site%2F%3Aid%2Freport");
  });

  it("opens the client's SOP in the portal, and hides on the SOP itself", () => {
    expect(linkAt("/portal/sites/3", "/portal/sop")?.getAttribute("href")).toBe("/portal/sop?page=%2Fportal%2Fsites%2F%3Aid");
    cleanup();
    expect(linkAt("/help/sop")).toBeNull();
  });
});
