// @vitest-environment jsdom
// One error, shown once: a failed save is one notice (the helper card, with its request id), a
// wrong entry is said beside its field only, a refusal the page explains is the page's banner only.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { errorText } from "../format";
import { HelperCard } from "./Helper";

function SaveForm() {
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        api("/api/things", { method: "POST", json: { qty: -5 } }).catch((err) => setError(errorText(err)));
      }}
    >
      <label className="field">
        <span>Quantity *</span>
        <input name="qty" defaultValue="-5" />
      </label>
      {error && <div className="alert alert-error">{error}</div>}
      <button type="submit">Save</button>
    </form>
  );
}

function answer(status: number, body: unknown) {
  vi.stubGlobal("fetch", async (url: string) => {
    if (String(url).includes("/api/me/helper")) return new Response(JSON.stringify({ ai: false }), { status: 200 });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Request-ID": "feedfeedfeedfeed" } });
  });
}

async function save() {
  render(
    <MemoryRouter>
      <SaveForm />
      <HelperCard />
    </MemoryRouter>,
  );
  await act(async () => {
    fireEvent.click(screen.getByText("Save"));
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

const count = (re: RegExp) => screen.queryAllByText(re).length;

describe("one error, shown once", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("a failed save shows its message once, with the request id, and no banner", async () => {
    answer(500, { detail: "Something went wrong on our side. It is recorded (request feedfeedfeedfeed): try again." });
    await save();
    expect(count(/Something went wrong on our side/)).toBe(1);
    expect(count(/Reference: feedfeedfeedfeed/)).toBe(1);
    expect(document.querySelectorAll(".alert-error")).toHaveLength(0);
  });

  it("a wrong entry is said beside its field only (the card points to it)", async () => {
    answer(422, {
      detail: [{ loc: ["body", "qty"], field: "qty", label: "Quantity", plain: "Quantity must be 0 or more.", fix: "Type a number of 0 or more.", msg: "Quantity must be 0 or more. Type a number of 0 or more." }],
    });
    await save();
    expect(count(/Quantity must be 0 or more/)).toBe(1);
    expect(document.querySelector("label.field-wrong .field-msg")?.textContent).toBe("Quantity must be 0 or more. Type a number of 0 or more.");
    expect(document.querySelectorAll(".alert-error")).toHaveLength(0);
    expect(screen.getByText(/The marked field needs a change/)).toBeTruthy();
  });

  it("a refusal the page explains is its banner only", async () => {
    answer(409, { detail: "This bill is already approved." });
    await save();
    expect(count(/already approved/)).toBe(1);
    expect(document.querySelector(".helper-card")).toBeNull();
  });
});
