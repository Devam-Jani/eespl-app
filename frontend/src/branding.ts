// The product's name and tag line and the company line, from the backend's one place (app/branding.py,
// sent with GET /api/ops/mode): a rename there changes the sidebar, the login page and the browser tab.
// The last answer is kept in the browser so the next visit paints the name at once.
import { useEffect, useState } from "react";
import { api } from "./api";

export type Branding = { product_name: string; product_tag: string; company_line: string; app_title: string };

const KEY = "eespl.branding";

function cached(): Branding | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Branding) : null;
  } catch {
    return null;
  }
}

let shared: Branding | null = cached();
let pending: Promise<Branding | null> | null = null;

function load(): Promise<Branding | null> {
  pending ??= api<Partial<Branding>>("/api/ops/mode").then(
    (m) => {
      if (!m.product_name) return shared;
      shared = { product_name: m.product_name, product_tag: m.product_tag ?? "", company_line: m.company_line ?? "", app_title: m.app_title ?? m.product_name };
      try {
        localStorage.setItem(KEY, JSON.stringify(shared));
      } catch {
        /* private window: fine, it is fetched again next time */
      }
      return shared;
    },
    () => shared,
  );
  return pending;
}

export function useBranding(): Branding | null {
  const [b, setB] = useState<Branding | null>(shared);
  useEffect(() => {
    let live = true;
    void load().then((x) => live && setB(x));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (b) document.title = b.product_name;
  }, [b]);
  return b;
}
