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
