// The side menu on a phone (up to 760 px wide) collapses behind a menu button and starts closed,
// so a supervisor opens straight on My work. On wider screens it is always shown.
export const PHONE_MAX_WIDTH = 760;

export function isPhone(width: number): boolean {
  return width <= PHONE_MAX_WIDTH;
}

/** The menu's state when a page opens: closed on a phone, open otherwise. */
export function initialMenuOpen(width: number): boolean {
  return !isPhone(width);
}

const KEY = (userId: string) => `eespl.menu.open.${userId}`;

/** The groups this user opened or closed (remembered in this browser). */
export function loadOpenGroups(userId: string): Record<string, boolean> {
  try {
    const raw = userId ? window.localStorage.getItem(KEY(userId)) : null;
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

export function saveOpenGroups(userId: string, open: Record<string, boolean>): void {
  try {
    if (userId) window.localStorage.setItem(KEY(userId), JSON.stringify(open));
  } catch {
    // private window or storage blocked: the menu still works, it just forgets
  }
}
