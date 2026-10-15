/**
 * The browser's part of field tracking, between Start day and End day only:
 * - a location point every 2 minutes and on each move of more than 100 m (watchPosition);
 * - points are queued in this browser (localStorage) and sent in batches, in time order; a batch
 *   that fails (offline) stays queued and is sent when the browser is back online; the server
 *   stores a point once, so a batch sent twice is not counted twice.
 * The web cannot track with the screen off or the browser closed: the route has gaps then (the
 * Android app will track in the background, through the same endpoint).
 */

export type QueuedPoint = { at: string; lat: number; lng: number; accuracy: number | null };

const EARTH_M = 6371008.8;

export function metres(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const r = Math.PI / 180;
  const dp = (lat2 - lat1) * r;
  const dl = (lng2 - lng1) * r;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Keep this reading? The first one, then every `everyS` seconds or a move over `moveM` metres. */
export function shouldKeep(last: QueuedPoint | null, next: QueuedPoint, everyS: number, moveM: number): boolean {
  if (!last) return true;
  const secs = (Date.parse(next.at) - Date.parse(last.at)) / 1000;
  if (secs <= 0) return false;
  return secs >= everyS || metres(last.lat, last.lng, next.lat, next.lng) > moveM;
}

/** A small store interface (localStorage in the browser, a map in tests). */
export type Store = { get(key: string): string | null; set(key: string, value: string): void };

export const browserStore: Store = {
  get(key) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // storage blocked: points are sent at once and lost when offline
    }
  },
};

export class PointQueue {
  constructor(
    private store: Store,
    private key: string,
  ) {}

  all(): QueuedPoint[] {
    try {
      const v = JSON.parse(this.store.get(this.key) ?? "[]");
      return Array.isArray(v) ? v : [];
    } catch {
      return [];
    }
  }

  add(p: QueuedPoint) {
    const list = this.all();
    if (list.some((x) => x.at === p.at)) return;
    list.push(p);
    list.sort((a, b) => a.at.localeCompare(b.at));
    this.store.set(this.key, JSON.stringify(list.slice(-2000)));
  }

  /** Send everything queued, oldest first, in batches; what was sent leaves the queue. */
  async flush(send: (batch: QueuedPoint[], id: string) => Promise<void>, size = 200): Promise<number> {
    let sent = 0;
    for (;;) {
      const list = this.all();
      if (!list.length) return sent;
      const batch = list.slice(0, size);
      const id = `${batch[0].at}_${batch.length}`;
      await send(batch, id); // throws when offline: the batch stays queued
      const rest = this.all().filter((p) => !batch.some((b) => b.at === p.at));
      this.store.set(this.key, JSON.stringify(rest));
      sent += batch.length;
    }
  }
}

/** Google Maps directions to the pin: a plain link opened on the phone, no key. */
export function mapsLink(lat: number, lng: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lng.toFixed(6)}`;
}
