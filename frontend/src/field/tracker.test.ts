import { describe, expect, it } from "vitest";
import { mapsLink, metres, PointQueue, shouldKeep } from "./tracker";
import type { QueuedPoint, Store } from "./tracker";

function memory(): Store {
  const m = new Map<string, string>();
  return { get: (k) => m.get(k) ?? null, set: (k, v) => void m.set(k, v) };
}

const p = (min: number, northM = 0): QueuedPoint => ({ at: new Date(Date.UTC(2026, 9, 6, 4, min)).toISOString(), lat: 23.03 + northM / 111195, lng: 72.5, accuracy: 10 });

describe("the browser tracker", () => {
  it("keeps a point every 2 minutes or on a move over 100 m", () => {
    expect(shouldKeep(null, p(0), 120, 100)).toBe(true);
    expect(shouldKeep(p(0), p(1, 50), 120, 100)).toBe(false);
    expect(shouldKeep(p(0), p(1, 150), 120, 100)).toBe(true);
    expect(shouldKeep(p(0), p(2, 0), 120, 100)).toBe(true);
    expect(Math.round(metres(23.03, 72.5, 23.03 + 1000 / 111195, 72.5))).toBe(1000);
  });

  it("queues points offline and sends them in time order when back online, once", async () => {
    const q = new PointQueue(memory(), "k");
    q.add(p(4));
    q.add(p(2));
    q.add(p(2)); // the same reading twice: queued once
    let online = false;
    const sent: string[][] = [];
    const send = async (batch: QueuedPoint[]) => {
      if (!online) throw new Error("offline");
      sent.push(batch.map((x) => x.at));
    };
    await expect(q.flush(send)).rejects.toThrow("offline");
    expect(q.all()).toHaveLength(2); // still queued
    q.add(p(6));
    online = true;
    expect(await q.flush(send, 2)).toBe(3);
    expect(sent).toEqual([[p(2).at, p(4).at], [p(6).at]]);
    expect(q.all()).toEqual([]);
  });

  it("builds the Google Maps link with the pin and no key", () => {
    expect(mapsLink(23, 72.46)).toBe("https://www.google.com/maps/dir/?api=1&destination=23.000000,72.460000");
  });
});
