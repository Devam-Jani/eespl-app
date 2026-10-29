// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { userStatus } from "../pages/Users";
import { CopyButton } from "./components";

afterEach(cleanup);

describe("Users (Prompt 39, Part 0)", () => {
  it("shows an imported or invited person without a password as Not set up, even when active", () => {
    expect(userStatus({ is_active: true, has_password: false, locked_until: null })).toBe("not_set_up");
    expect(userStatus({ is_active: false, has_password: false, locked_until: null })).toBe("not_set_up");
    expect(userStatus({ is_active: false, has_password: true, locked_until: null })).toBe("inactive");
    expect(userStatus({ is_active: true, has_password: true, locked_until: null, locked_by_failures: true })).toBe("locked");
    expect(userStatus({ is_active: true, has_password: true, locked_until: null })).toBe("active");
  });
});

describe("CopyButton", () => {
  it("says Copied only when the clipboard took it, and Copy it by hand otherwise", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    render(<CopyButton text="https://x/set-password/abc" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByRole("button", { name: "Copy it by hand" })).toBeTruthy();
    cleanup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<CopyButton text="https://x/set-password/abc" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith("https://x/set-password/abc");
  });
});
