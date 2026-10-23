// What the helper sends to the issue log book when something goes wrong: the page (its path, never
// the query string), the role (the server knows it), the last button pressed (its label), the
// error, the request id and the browser. Never what was typed (only with the user's consent, from
// "Report this"), never a token, password or key.
import { api, ApiError, hasSession } from "../api";

export type ReportKind = "error" | "mistake" | "report";
export type Report = {
  kind: ReportKind;
  page: string;
  action?: string | null;
  error?: string | null;
  status_code?: number | null;
  request_id?: string | null;
  browser?: string | null;
  stack?: string | null;
  words?: string | null;
  include_values?: boolean;
  values?: Record<string, string> | null;
};

const SECRETS: [RegExp, string][] = [
  [/eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}/g, "[token]"],
  [/bearer\s+[\w.\-~+/=]{8,}/gi, "Bearer [token]"],
  [/(password|passwd|pwd|secret|api[_-]?key|token)(\s*[=:]\s*)\S+/gi, "$1$2[hidden]"],
  [/\bsk-[\w-]{12,}/g, "[key]"],
  [/\b[A-Za-z0-9+/_-]{40,}={0,2}/g, "[long value]"],
];
/** A field whose value is never sent, even with consent. */
export const SECRET_FIELD = /pass|token|secret|key|otp|pin\b|cvv|card|two.?step/i;

export function scrubText(text: string | null | undefined, limit = 4000): string | null {
  if (!text) return null;
  let out = text;
  for (const [pat, rep] of SECRETS) out = out.replace(pat, rep);
  return out.slice(0, limit);
}

/** The page, without its query string or hash (they can carry what was typed or a token). */
export function pagePath(href: string): string {
  try {
    return new URL(href, "http://x").pathname.slice(0, 300);
  } catch {
    return href.split(/[?#]/)[0].slice(0, 300);
  }
}

/** "Chrome 130 · Windows" (not the full user agent). */
export function browserName(ua: string): string {
  const known: [string, RegExp][] = [
    ["Edge", /Edg\/(\d+)/],
    ["Firefox", /Firefox\/(\d+)/],
    ["Chrome", /Chrome\/(\d+)/],
    ["Safari", /Version\/(\d+).*Safari/],
  ];
  const hit = known.map(([name, re]) => [name, re.exec(ua)?.[1]] as const).find(([, v]) => v);
  const b = hit ? `${hit[0]} ${hit[1]}` : "Other browser";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${b} · ${os}` : b;
}

/** What a failed request becomes in the log book: a wrong entry the helper guided, a failure on
 * our side, or nothing (a refusal the page explains itself: 400, 401, 403, 404, 409). */
export function reportForFailure(e: ApiError, page: string): Report | null {
  if (e.action?.includes("/api/me/issues") || e.action?.includes("/api/me/helper")) return null; // never about itself
  if (e.status === 422 && e.fields.length) {
    // the fields and their rules, never what was typed
    return { kind: "mistake", page, action: e.action, status_code: 422, request_id: e.requestId, error: e.fields.map((f) => f.plain).join(" ") };
  }
  if (e.status >= 500 || e.status === 0) {
    return { kind: "error", page, action: e.action, status_code: e.status || null, request_id: e.requestId, error: scrubText(e.message) };
  }
  return null;
}

export function crashReport(err: unknown, page: string, action: string | null): Report {
  const e = err instanceof Error ? err : new Error(typeof err === "string" ? err : "Unknown error");
  return { kind: "error", page, action, error: scrubText(`${e.name}: ${e.message}`), stack: scrubText(e.stack ?? null, 20000) };
}

// the same problem again within a minute is not sent again (a loop, a re-render)
const sentAt = new Map<string, number>();
export function firstInAWhile(r: Report, now = Date.now(), within = 60_000): boolean {
  const key = [r.kind, r.page, r.status_code ?? "", (r.error ?? "").slice(0, 200)].join("|");
  const last = sentAt.get(key);
  if (last !== undefined && now - last < within) return false;
  sentAt.set(key, now);
  return true;
}

/** The label of the last button or link pressed (never a field's value). */
let lastAction: string | null = null;
export function trackActions(): () => void {
  const onClick = (ev: MouseEvent) => {
    const el = (ev.target as Element | null)?.closest?.("button, a, [role=button], [role=tab]");
    if (!el) return;
    const label = (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
    if (label) lastAction = `pressed "${label}"`;
  };
  window.addEventListener("click", onClick, { capture: true });
  return () => window.removeEventListener("click", onClick, { capture: true });
}
export function currentAction(): string | null {
  return lastAction;
}

export type Recorded = { issue_id: number; event_id: number; status: string; request_id: string | null };

/** Sends one report (signed in only; a failure to report is silent). */
export async function send(r: Report, force = false): Promise<Recorded | null> {
  if (!hasSession() || (!force && !firstInAWhile(r))) return null;
  const body: Report = { ...r, browser: r.browser ?? (typeof navigator !== "undefined" ? browserName(navigator.userAgent) : null) };
  if (!body.include_values) delete body.values;
  try {
    return await api<Recorded>("/api/me/issues", { method: "POST", json: body });
  } catch {
    return null;
  }
}

/** What the user typed on the open form, only for "Report this" with their consent: each field's
 * label and value, never a password, a hidden field or a field that looks secret. */
export function formValues(root: ParentNode = document): Record<string, string> {
  const out: Record<string, string> = {};
  const scope = root.querySelector(".modal") ?? root;
  scope.querySelectorAll<HTMLLabelElement>("label.field").forEach((l) => {
    const input = l.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea");
    const name = (l.querySelector("span")?.textContent ?? "").replace(/\*/g, "").trim();
    if (!input || !name || Object.keys(out).length >= 40) return;
    const type = input instanceof HTMLInputElement ? input.type : "";
    if (["password", "hidden", "file"].includes(type) || SECRET_FIELD.test(name) || SECRET_FIELD.test(input.name ?? "")) return;
    out[name.slice(0, 80)] = scrubText(input.value, 300) ?? "";
  });
  return out;
}
