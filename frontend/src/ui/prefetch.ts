// Page changes feel instant: each page's code is fetched when its menu item is hovered or focused
// (lazyPage keeps the import so it can start early); the router keeps the old page on screen while
// the new one loads (BrowserRouter's v7_startTransition).
import type { ComponentType, LazyExoticComponent, ReactElement } from "react";
import { lazy } from "react";

type Preloadable = LazyExoticComponent<ComponentType<object>> & { preload?: () => Promise<unknown> };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyPage<T extends ComponentType<any>>(factory: () => Promise<{ default: T }>): LazyExoticComponent<T> & { preload: () => Promise<unknown> } {
  const C = lazy(factory) as LazyExoticComponent<T> & { preload: () => Promise<unknown> };
  C.preload = factory;
  return C;
}

const pages = new Map<string, () => Promise<unknown>>();
const started = new Set<string>();

/** The pages by menu path (App.tsx registers them once). */
export function registerPages(map: Record<string, ReactElement>): void {
  for (const [path, el] of Object.entries(map)) {
    const pre = (el.type as Preloadable).preload;
    if (pre) pages.set(path, pre);
  }
}

export function registerPage(path: string, preload: () => Promise<unknown>): void {
  pages.set(path, preload);
}

/** Start loading a page's code (once). */
export function prefetch(path: string): void {
  if (started.has(path)) return;
  const pre = pages.get(path) ?? pages.get(path.split("?")[0]);
  if (!pre) return;
  started.add(path);
  void pre().catch(() => started.delete(path));
}
