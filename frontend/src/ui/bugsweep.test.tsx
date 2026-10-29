// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { inviteText, userStatus } from "../pages/Users";
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

describe("the invite status on Users (Prompt 39, Part 5)", () => {
  it("says queued, sent with the time, or failed with the reason", () => {
    expect(inviteText({ kind: "invite", status: "queued", at: null, error: null })).toBe("Invite queued");
    expect(inviteText({ kind: "invite", status: "sent", at: "2026-10-29T06:00:00Z", error: null })).toMatch(/^Invite sent 29\/10\/2026, 11:30/);
    expect(inviteText({ kind: "reset", status: "failed", at: null, error: "SMTP refused the login" })).toBe("Reset link failed: SMTP refused the login");
  });
});
