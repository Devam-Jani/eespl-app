// @vitest-environment jsdom
// Each shared component in each of its states.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button, EmptyState, Field, KpiCard, Legend, NavItem, ProgressBar, Skeleton, StatusChip, Tabs } from "./components";
import { checkFtIn, FtInInput } from "./FtIn";
import { MonthBars } from "./MonthBars";
import { Drawer, Modal, ToastProvider, useToast } from "./Overlay";
import { Table } from "./Table";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Button", () => {
  it("has the four variants, and is busy and not pressable while loading or disabled", () => {
    const click = vi.fn();
    render(
      <>
        <Button variant="primary" onClick={click}>
          Primary
        </Button>
        <Button variant="danger">Danger</Button>
        <Button variant="ghost">Ghost</Button>
        <Button loading onClick={click}>
          Loading
        </Button>
        <Button disabled onClick={click}>
          Off
        </Button>
      </>,
    );
    expect(screen.getByText("Primary").className).toContain("btn-primary");
    expect(screen.getByText("Danger").className).toContain("btn-danger");
    expect(screen.getByText("Ghost").className).toContain("btn-ghost");
    const loading = screen.getByText("Loading");
    expect(loading.getAttribute("aria-busy")).toBe("true");
    expect((loading as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(loading);
    fireEvent.click(screen.getByText("Off"));
    expect(click).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Primary"));
    expect(click).toHaveBeenCalledOnce();
    expect(screen.getByText("Primary").getAttribute("type")).toBe("button");
  });
});

describe("StatusChip, Legend, ProgressBar", () => {
  it("shows each status in its colour and name", () => {
    render(
      <>
        <StatusChip status="hold" />
        <StatusChip status="block">Late 9 days</StatusChip>
        <Legend counts={{ done: 15, prog: 12 }} />
      </>,
    );
    expect(screen.getByText("Hold point", { selector: ".chip" }).className).toBe("chip chip-hold");
    expect(screen.getByText("Late 9 days").className).toBe("chip chip-block");
    expect(screen.getByText("Done 15")).toBeTruthy();
    expect(screen.getByText("In progress 12")).toBeTruthy();
    expect(screen.getByText("Not started")).toBeTruthy(); // no count: the name only
  });
  it("keeps progress between 0 and 100", () => {
    render(
      <>
        <ProgressBar value={140} label="over" />
        <ProgressBar value={-5} label="under" status="block" />
      </>,
    );
    expect(screen.getByLabelText("over").getAttribute("aria-valuenow")).toBe("100");
    expect(screen.getByLabelText("under").getAttribute("aria-valuenow")).toBe("0");
    expect(screen.getByLabelText("under").className).toContain("progress-block");
  });
});

describe("KpiCard and NavItem", () => {
  it("a KPI card that switches the chart is a pressed button; without a chart it is a plain card", () => {
    const pick = vi.fn();
    render(
      <>
        <KpiCard label="Order book" value="₹4.82 Cr" note="won ₹36 L" active onClick={pick} />
        <KpiCard label="Sites on track" value="18 of 23" />
      </>,
    );
    const b = screen.getByRole("button", { name: /Order book/ });
    expect(b.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(b);
    expect(pick).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Sites on track/ })).toBeNull();
  });
  it("a nav item is active on its page and shows its count", () => {
    render(
      <MemoryRouter initialEntries={["/my-work"]}>
        <NavItem to="/my-work" label="Approvals" count={3} />
        <NavItem to="/alerts" label="Alerts" />
      </MemoryRouter>,
    );
    expect(screen.getByText("Approvals").closest("a")?.className).toContain("active");
    expect(screen.getByLabelText("3 waiting")).toBeTruthy();
    expect(screen.getByText("Alerts").closest("a")?.className).not.toContain("active");
  });
});

describe("Tabs", () => {
  it("selects by click and by the arrow keys, and is a select on a phone", () => {
    const on = vi.fn();
    render(
      <Tabs
        value="a"
        onChange={on}
        tabs={[
          { key: "a", label: "Overview" },
          { key: "b", label: "3D building" },
        ]}
      />,
    );
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "3D building" }));
    expect(on).toHaveBeenLastCalledWith("b");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowLeft" });
    expect(on).toHaveBeenLastCalledWith("b");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "b" } });
    expect(on).toHaveBeenLastCalledWith("b");
  });
});

describe("Table", () => {
  const rows = [
    { id: 1, name: "B site", late: false, n: 2 },
    { id: 2, name: "A site", late: true, n: 1 },
    { id: 3, name: "C site", late: false, n: 3 },
  ];
  const cols = [
    { key: "name", label: "Site", sort: (r: (typeof rows)[0]) => r.name, render: (r: (typeof rows)[0]) => r.name },
    { key: "n", label: "N", render: (r: (typeof rows)[0]) => String(r.n) },
  ];
  it("sorts, filters with counted chips, pages, and says what to do when empty", () => {
    const open = vi.fn();
    render(
      <Table
        rows={rows}
        columns={cols}
        rowKey={(r) => r.id}
        pageSize={2}
        onOpen={open}
        filters={[
          { key: "all", label: "All", test: () => true },
          { key: "late", label: "Late", test: (r) => r.late },
          { key: "none", label: "Billing due", test: () => false },
        ]}
        empty={{ title: "No site is due for billing", hint: "A site shows here when a finished stage is not billed." }}
      />,
    );
    expect(screen.getByRole("button", { name: "All 3" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Page 1 of 2 · 3 rows")).toBeTruthy();
    fireEvent.click(screen.getByText("Site"));
    expect(screen.getAllByRole("row")[1].textContent).toContain("A site");
    expect(screen.getByText("Site").getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(screen.getByText("Site"));
    expect(screen.getAllByRole("row")[1].textContent).toContain("C site");
    fireEvent.keyDown(screen.getAllByRole("row")[1], { key: "Enter" });
    expect(open).toHaveBeenCalledWith(rows[2]);
    fireEvent.click(screen.getByRole("button", { name: "Late 1" }));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Billing due 0" }));
    expect(screen.getByText("No site is due for billing")).toBeTruthy();
    expect(screen.getByText(/finished stage is not billed/)).toBeTruthy();
  });
});

describe("ft + in", () => {
  it("checks a length and offers the one clear fix", () => {
    expect(checkFtIn("19", "14")).toMatchObject({ ok: false, problem: "Inches must be 0 to 11. Did you mean 20 ft 2 in?", fix: { ft: "20", inch: "2" } });
    expect(checkFtIn("20", "2")).toMatchObject({ ok: true, feet: 20, inches: 2, metres: 6.147 });
    expect(checkFtIn("12'", "6\"")).toMatchObject({ ok: false, fix: { ft: "12", inch: "6" } });
    expect(checkFtIn("", "")).toMatchObject({ ok: false });
    expect(checkFtIn("0", "0")).toMatchObject({ ok: false, problem: "The length cannot be 0." });
  });
  it("shows the message beside the boxes and fixes it in one tap", () => {
    const change = vi.fn();
    render(<FtInInput label="Length" ft="19" inch="14" onChange={change} />);
    expect(screen.getByRole("alert").textContent).toContain("Did you mean 20 ft 2 in?");
    expect(screen.getByLabelText("Length: inches").getAttribute("aria-invalid")).toBe("true");
    fireEvent.click(screen.getByText("Use 20 ft 2 in"));
    expect(change).toHaveBeenCalledWith("20", "2");
  });
  it("a field shows its hint, or its problem in place of the hint", () => {
    render(
      <>
        <Field label="Name" hint="As on the order">
          <input />
        </Field>
        <Field label="Qty" error="Quantity must be 0 or more.">
          <input />
        </Field>
      </>,
    );
    expect(screen.getByText("As on the order")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Quantity must be 0 or more.");
  });
});

describe("Modal, Drawer, Toast", () => {
  it("Escape closes a modal and a drawer", () => {
    const close = vi.fn();
    render(
      <Modal title="Edit" onClose={close}>
        <input aria-label="first" />
      </Modal>,
    );
    expect(document.activeElement?.getAttribute("aria-label")).toBe("first");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalled();
    cleanup();
    const shut = vi.fn();
    render(
      <Drawer title="Details" onClose={shut}>
        x
      </Drawer>,
    );
    expect(screen.getByRole("dialog", { name: "Details" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(shut).toHaveBeenCalled();
  });

  it("a toast's Undo stops the action, and without Undo it runs", () => {
    vi.useFakeTimers();
    const action = vi.fn();
    const undone = vi.fn();
    function Do() {
      const t = useToast();
      return (
        <>
          <button onClick={() => t.later("Approved", action, 6000, undone)}>go</button>
        </>
      );
    }
    render(
      <ToastProvider>
        <Do />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("go"));
    fireEvent.click(screen.getByText("Undo"));
    act(() => void vi.advanceTimersByTime(7000));
    expect(action).not.toHaveBeenCalled();
    expect(undone).toHaveBeenCalled();
    fireEvent.click(screen.getByText("go"));
    act(() => void vi.advanceTimersByTime(7000));
    expect(action).toHaveBeenCalledOnce();
  });
});

describe("Skeleton, EmptyState, MonthBars", () => {
  it("a skeleton is hidden from screen readers; an empty state says what to do", () => {
    const { container } = render(
      <>
        <Skeleton lines={3} />
        <EmptyState title="No bills yet" hint="Raise the first RA bill." />
      </>,
    );
    expect(container.querySelector("[aria-hidden='true']")?.querySelectorAll(".skeleton")).toHaveLength(3);
    expect(screen.getByText("No bills yet")).toBeTruthy();
  });
  it("six months: the latest in full, a month with no record as an empty slot", () => {
    render(
      <MonthBars
        label="Billed"
        format={(v) => `${v} L`}
        points={[
          { month: "Sep", value: null },
          { month: "Oct", value: 38.6 },
        ]}
      />,
    );
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.getByText("38.6 L").closest("li")?.className).toBe("now");
  });
});
