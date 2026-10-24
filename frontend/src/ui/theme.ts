// The look: dark by default, light for printing and bright sites. Chosen in the user menu and
// remembered for the person (on their user, so on every device; this browser keeps a copy per
// user so the first paint is already right).
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ThemeName } from "./tokens";

const KEY = "eespl.theme";

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

/** The theme this browser remembers for a user (the last user before sign-in). */
export function storedTheme(userId: string | null): ThemeName {
  const s = storage();
  const id = userId ?? s?.getItem(`${KEY}.last`) ?? "";
  const v = s?.getItem(`${KEY}.${id}`);
  return v === "light" ? "light" : "dark";
}

export function applyTheme(theme: ThemeName): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  window.dispatchEvent(new CustomEvent("eespl-theme", { detail: theme }));
}

export function rememberLocally(userId: string, theme: ThemeName): void {
  const s = storage();
  s?.setItem(`${KEY}.${userId}`, theme);
  s?.setItem(`${KEY}.last`, userId);
}

/** The signed-in person's theme: their saved choice (else this browser's copy), and a setter
 * that applies it at once and saves it for them. */
export function useTheme(userId: string | null, saved: ThemeName | null | undefined): [ThemeName, (t: ThemeName) => void] {
  const [theme, setTheme] = useState<ThemeName>(() => saved ?? storedTheme(userId));
  useEffect(() => {
    const t = saved ?? storedTheme(userId);
    setTheme(t);
    applyTheme(t);
    if (userId) rememberLocally(userId, t);
  }, [userId, saved]);
  const choose = useCallback(
    (t: ThemeName) => {
      setTheme(t);
      applyTheme(t);
      if (userId) {
        rememberLocally(userId, t);
        void api("/api/auth/theme", { method: "PUT", json: { theme: t } }).catch(() => {});
      }
    },
    [userId],
  );
  return [theme, choose];
}

/** The theme in effect now (for the 3D viewer and charts that paint with token values). */
export function currentTheme(): ThemeName {
  return typeof document !== "undefined" && document.documentElement.dataset.theme === "light" ? "light" : "dark";
}
