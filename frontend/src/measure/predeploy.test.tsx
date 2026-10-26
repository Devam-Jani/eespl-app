// @vitest-environment jsdom
// From the Prompt 34 review: the slip on a phone (an image as an image, a PDF as a link: a phone's
// browser shows no PDF in a frame), and the shared file picker that replaced the bare "Choose File".
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilePicker } from "../ui/components";
import { SlipPanel } from "./Billing";
import type { SlipInfo } from "./Billing";

vi.mock("../api", () => ({ api: vi.fn(), downloadFile: vi.fn(), fetchObjectUrl: vi.fn(async () => "blob:slip") }));
vi.mock("../auth", () => ({ useAuth: () => ({ can: () => false }) }));
URL.revokeObjectURL = () => undefined; // jsdom has none

afterEach(() => {
  cleanup();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
});

const slip = (name: string): SlipInfo => ({ name, on: "2026-10-20", signed_by: "Client's engineer", signed_on: "2026-10-20", has_file: true, unbilled: [] });

function at(width: number, name: string) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  return render(<SlipPanel sheetId={1} slip={slip(name)} items={[]} draft={false} onChanged={() => undefined} />);
}

describe("the slip", () => {
  it("on a phone: a PDF is a link that opens it, never a frame", async () => {
    const { container } = at(390, "slip 08 06 2026.pdf");
    const link = await screen.findByRole("link", { name: "Open the slip" });
    expect(link.getAttribute("href")).toBe("blob:slip");
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("on a phone: a photo is shown as the image", async () => {
    const { container } = at(390, "slip 21 10 2026.jpeg");
    await waitFor(() => expect(container.querySelector(".m-slip-pic img")?.getAttribute("src")).toBe("blob:slip"));
    expect(screen.queryByRole("link", { name: "Open the slip" })).toBeNull();
  });

  it("on the desktop: the PDF stays in its frame", async () => {
    const { container } = at(1600, "slip.pdf");
    await waitFor(() => expect(container.querySelector(".m-slip-pic iframe")?.getAttribute("src")).toBe("blob:slip"));
  });
});

describe("the file picker", () => {
  it("is a button that names the file chosen, the input inside it", () => {
    const got: File[][] = [];
    const { container } = render(<FilePicker label="Choose the Excel file" accept=".xlsx" onFiles={(f) => got.push(f)} />);
    const input = container.querySelector("label.file-picker input[type=file].sr-only") as HTMLInputElement;
    expect(input.accept).toBe(".xlsx");
    expect(screen.getByText("Choose the Excel file")).toBeTruthy();
    const file = new File(["x"], "register.xlsx");
    fireEvent.change(input, { target: { files: [file] } });
    expect(got).toEqual([[file]]);
    expect(screen.getByText("register.xlsx")).toBeTruthy();
  });

  it("keeps its label when asked (a picker that says Reading…)", () => {
    const { container } = render(<FilePicker label="Reading…" showChosen={false} />);
    fireEvent.change(container.querySelector("input") as HTMLInputElement, { target: { files: [new File(["x"], "old.xlsx")] } });
    expect(screen.getByText("Reading…")).toBeTruthy();
  });
});
