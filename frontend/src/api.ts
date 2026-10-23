// Fetch wrapper: keeps the access token in memory, refreshes it silently on a 401
// (the refresh token lives in an httpOnly cookie), and reports a lost session.

export type Scope = "all" | "assigned" | "own";

/** A wrong entry, field by field, in plain words (the API's 422: app/issues/fields.py). */
export type FieldProblem = { field: string | null; label: string; plain: string; fix: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The server's id for the request (X-Request-ID), to find it in the issue log. */
    public requestId: string | null = null,
    public fields: FieldProblem[] = [],
    /** "POST /api/leads" (no query string: it may carry values). */
    public action: string | null = null,
  ) {
    super(message);
  }
}

/** Told of every failed request (the helper card listens): never the request's body. */
type FailureListener = (e: ApiError) => void;
const failureListeners = new Set<FailureListener>();
export function onApiFailure(fn: FailureListener): () => void {
  failureListeners.add(fn);
  return () => failureListeners.delete(fn);
}
function failed(e: ApiError): ApiError {
  for (const fn of failureListeners) {
    try {
      fn(e);
    } catch {
      // a listener's own trouble never hides the page's error
    }
  }
  return e;
}

function requestIdFor(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  return c && "randomUUID" in c ? c.randomUUID().replace(/-/g, "").slice(0, 16) : Math.random().toString(16).slice(2, 18).padEnd(16, "0");
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
}

/** Signed in (the helper only reports for a signed-in user). */
export function hasSession(): boolean {
  return accessToken !== null;
}

export function setSessionLostHandler(handler: () => void) {
  onSessionLost = handler;
}

// The session ends after inactivity (Settings > Security: 12 hours on a phone, 8 on a desktop):
// the app tells the server, on each refresh, how long ago the person last used it (a background
// poll is not use).
let lastActivity = Date.now();
if (typeof window !== "undefined") {
  for (const ev of ["pointerdown", "keydown", "touchstart", "wheel"]) {
    window.addEventListener(ev, () => (lastActivity = Date.now()), {
      passive: true,
      capture: true,
    });
  }
}

export function deviceKind(width: number, agent: string): "phone" | "desktop" {
  return width <= 760 || /Mobi|Android|iPhone/.test(agent)
    ? "phone"
    : "desktop";
}

function sessionHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return {
    "X-Idle-Seconds": String(
      Math.max(0, Math.floor((Date.now() - lastActivity) / 1000)),
    ),
    "X-Device": deviceKind(window.innerWidth, navigator.userAgent),
  };
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshAccessToken(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin", headers: sessionHeaders() })
      .then(async (res) => {
        if (!res.ok) {
          accessToken = null;
          return false;
        }
        accessToken = (await res.json()).access_token;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

type Detail = { loc?: unknown[]; msg: string; field?: string | null; label?: string; plain?: string; fix?: string };

/** The plain message and, for a wrong entry, each field's problem. */
export async function readError(res: Response): Promise<{ message: string; fields: FieldProblem[] }> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return { message: body.detail, fields: [] };
    if (Array.isArray(body.detail)) {
      const details = body.detail as Detail[];
      const fields = details
        .filter((d) => d.plain)
        .map((d) => ({ field: d.field ?? null, label: d.label ?? "", plain: d.plain ?? d.msg, fix: d.fix ?? "" }));
      const message = details
        .map((d) => {
          if (d.plain) return d.msg;
          const field = d.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join(" ");
      return { message, fields };
    }
  } catch {
    // not JSON
  }
  if (res.status >= 500) return { message: "Something went wrong on our side. It is recorded: try again, or report what you were doing.", fields: [] };
  return { message: res.statusText || `HTTP ${res.status}`, fields: [] };
}

async function errorMessage(res: Response): Promise<string> {
  return (await readError(res)).message;
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; form?: FormData };

const inFlight = new Map<string, Promise<unknown>>();

export async function api<T>(path: string, options: Options = {}, retry = true): Promise<T> {
  const shareable = (options.method ?? "GET") === "GET" && options.json === undefined && !options.form && !options.headers && retry;
  if (shareable) {
    const pending = inFlight.get(path);
    if (pending) return pending as Promise<T>;
    const p = apiOnce<T>(path, options, retry).finally(() => inFlight.delete(path));
    inFlight.set(path, p);
    return p;
  }
  return apiOnce<T>(path, options, retry);
}

async function apiOnce<T>(path: string, options: Options, retry: boolean): Promise<T> {
  const { json, form, ...init } = options;
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined")
    headers.set("X-Device", deviceKind(window.innerWidth, navigator.userAgent));
  const rid = requestIdFor();
  headers.set("X-Request-ID", rid);
  const action = `${(init.method ?? "GET").toUpperCase()} ${path.split("?")[0]}`;

  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers,
      body: json !== undefined ? JSON.stringify(json) : form,
      credentials: "same-origin",
    });
  } catch {
    // no answer at all (offline, the server restarting)
    throw failed(new ApiError(0, "The server could not be reached. Check the connection and try again.", rid, [], action));
  }

  if (res.status === 401 && retry && !path.startsWith("/api/auth/login")) {
    if (await refreshAccessToken()) return api<T>(path, options, false);
    onSessionLost();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  if (!res.ok) {
    const { message, fields } = await readError(res);
    throw failed(new ApiError(res.status, message, res.headers.get("X-Request-ID") ?? rid, fields, action));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function queryString(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Download a file from the API (with the same silent refresh) and save it in the browser. */
export async function downloadFile(path: string, retry = true, method: "GET" | "POST" = "GET", extra?: Record<string, string>): Promise<void> {
  const headers = new Headers(extra);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(path, { method, headers, credentials: "same-origin" });
  if (res.status === 401 && retry) {
    if (await refreshAccessToken()) return downloadFile(path, false, method, extra);
    onSessionLost();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "export.xlsx";
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** An object URL for a protected image (an <img src> cannot send the Bearer token). */
export async function fetchObjectUrl(path: string, retry = true, extra?: Record<string, string>): Promise<string | null> {
  const headers = new Headers(extra);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(path, { headers, credentials: "same-origin" });
  if (res.status === 401 && retry && (await refreshAccessToken())) return fetchObjectUrl(path, false, extra);
  if (!res.ok) return null;
  return URL.createObjectURL(await res.blob());
}
