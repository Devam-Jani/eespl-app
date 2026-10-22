// Fetch wrapper: keeps the access token in memory, refreshes it silently on a 401
// (the refresh token lives in an httpOnly cookie), and reports a lost session.

export type Scope = "all" | "assigned" | "own";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
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

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((d: { loc?: unknown[]; msg: string }) => {
          const field = d.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return res.statusText || `HTTP ${res.status}`;
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; form?: FormData };

export async function api<T>(path: string, options: Options = {}, retry = true): Promise<T> {
  const { json, form, ...init } = options;
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined")
    headers.set("X-Device", deviceKind(window.innerWidth, navigator.userAgent));

  const res = await fetch(path, {
    ...init,
    headers,
    body: json !== undefined ? JSON.stringify(json) : form,
    credentials: "same-origin",
  });

  if (res.status === 401 && retry && !path.startsWith("/api/auth/login")) {
    if (await refreshAccessToken()) return api<T>(path, options, false);
    onSessionLost();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
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
