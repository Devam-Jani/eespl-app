// The daily report on a phone without signal: a report that could not be sent is kept on the
// phone (IndexedDB: its line and its photos) and sent, oldest first, when the signal is back (the
// browser's "online" event, the page opening, or a retry). A report that the server refuses (not a
// lost connection) stays too, with the reason, for the person to see; nothing is dropped silently.
import { api, ApiError } from "../api";

export type QueuedLine = { description: string; qty: number | null; unit: string | null; node_id: number | null; area_scope_id: number | null };
export type QueuedReport = { id: string; site_id: number; day: string; line: QueuedLine; photos: Blob[]; submit: boolean; at: number; error?: string };

/** Where queued reports live (IndexedDB in the browser; a Map in tests). */
export interface ReportStore {
  all(): Promise<QueuedReport[]>;
  put(r: QueuedReport): Promise<void>;
  remove(id: string): Promise<void>;
}

const DB = "eespl-reports";
const STORE = "queue";

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return idb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const r = fn(db.transaction(STORE, mode).objectStore(STORE));
        r.onsuccess = () => resolve(r.result);
        r.onerror = () => reject(r.error);
      }),
  );
}

export const browserStore: ReportStore = {
  all: () => tx<QueuedReport[]>("readonly", (s) => s.getAll() as IDBRequest<QueuedReport[]>).then((rows) => rows.sort((a, b) => a.at - b.at)),
  put: (r) => tx("readwrite", (s) => s.put(r)).then(() => undefined),
  remove: (id) => tx("readwrite", (s) => s.delete(id)).then(() => undefined),
};

/** A lost connection (keep it for later), not a refusal (say why). */
export function isOffline(e: unknown): boolean {
  return (e instanceof ApiError && e.status === 0) || (typeof navigator !== "undefined" && navigator.onLine === false);
}

type Dpr = { lines: (QueuedLine & { id?: number })[]; status: string };

/** Sends one report: today's lines with this one added (or replacing the same place's line), then
 * its photos. */
export async function sendReport(r: QueuedReport): Promise<void> {
  const base = `/api/execution/sites/${r.site_id}/dprs/${r.day}`;
  const now = await api<Dpr>(base);
  const keep = (now.lines ?? [])
    .filter((l) => !(r.line.node_id !== null && l.node_id === r.line.node_id && l.area_scope_id === r.line.area_scope_id))
    .map(({ description, qty, unit, node_id, area_scope_id }) => ({ description, qty, unit, node_id, area_scope_id }));
  await api(base, { method: "PUT", json: { lines: [...keep, r.line], submit: r.submit } });
  for (const p of r.photos) {
    const form = new FormData();
    form.append("file", p, "site-photo.jpg");
    form.append("caption", r.line.description.slice(0, 300));
    await api(`${base}/photos`, { method: "POST", form });
  }
}

/** Send now, or keep it on the phone when there is no signal. */
export async function sendOrKeep(r: QueuedReport, store: ReportStore = browserStore, send = sendReport): Promise<"sent" | "kept"> {
  try {
    await send(r);
    return "sent";
  } catch (e) {
    if (!isOffline(e)) throw e;
    await store.put(r);
    return "kept";
  }
}

/** Everything kept, oldest first; stops at the first lost connection. Returns how many went. */
export async function flush(store: ReportStore = browserStore, send = sendReport): Promise<{ sent: number; left: number }> {
  const rows = await store.all();
  let sent = 0;
  for (const r of rows) {
    try {
      await send(r);
      await store.remove(r.id);
      sent += 1;
    } catch (e) {
      if (isOffline(e)) break;
      await store.put({ ...r, error: e instanceof Error ? e.message : String(e) }); // refused: kept with the reason
    }
  }
  const left = (await store.all()).length;
  return { sent, left };
}
