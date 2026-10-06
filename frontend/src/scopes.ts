import type { Scope } from "./api";

export const SCOPES: Scope[] = ["all", "assigned", "own"];
const RANK: Record<Scope, number> = { own: 1, assigned: 2, all: 3 };

/** Mirrors the server rule: you can only hand out what you hold yourself (same or wider scope). */
export function canGrant(mine: Record<string, Scope>, granted: Record<string, Scope>): boolean {
  return Object.entries(granted).every(([code, scope]) => code in mine && RANK[mine[code]] >= RANK[scope]);
}
