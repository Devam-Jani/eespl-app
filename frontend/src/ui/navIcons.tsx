// Menu icons for the sidebar (shown alone when it folds to icons on a tablet). Drawn in the style of
// the design's phone-tab icons: 24 px, 1.8 px round strokes, painted in the current colour.
import type { ReactNode } from "react";

const P: Record<string, ReactNode> = {
  dashboard: (
    <>
      <rect x="3.5" y="3.5" width="7" height="9" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
      <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
      <rect x="3.5" y="15.5" width="7" height="5" rx="1.5" />
    </>
  ),
  approvals: (
    <>
      <path d="M9 11.5l2.2 2.2L15.5 9.5" />
      <rect x="4" y="3.5" width="16" height="17" rx="2.5" />
    </>
  ),
  alerts: (
    <>
      <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </>
  ),
  sales: (
    <>
      <path d="M4 19.5l5-6 4 3.5 7-9" />
      <path d="M15.5 8H20v4.5" />
    </>
  ),
  planning: (
    <>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </>
  ),
  site: (
    <>
      <path d="M4 20.5V9l8-5 8 5v11.5" />
      <path d="M9.5 20.5v-6h5v6" />
    </>
  ),
  billing: (
    <>
      <path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2z" />
      <path d="M9 8.5h6M9 12h6" />
    </>
  ),
  stores: (
    <>
      <path d="M3.5 8l8.5-4.5L20.5 8v12.5h-17z" />
      <path d="M8 20.5v-7h8v7" />
    </>
  ),
  accounts: (
    <>
      <rect x="3.5" y="6" width="17" height="13" rx="2.5" />
      <path d="M3.5 10.5h17M7.5 15h3" />
    </>
  ),
  analytics: (
    <>
      <path d="M5 20V12M10 20V6M15 20v-9M20 20V4" />
    </>
  ),
  masters: (
    <>
      <path d="M5 4.5h11.5a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z" />
      <path d="M5 18.5a2 2 0 0 1 2-2h11.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3.5v2.5M12 18v2.5M3.5 12H6M18 12h2.5M6 6l1.8 1.8M16.2 16.2L18 18M6 18l1.8-1.8M16.2 7.8L18 6" />
    </>
  ),
  admin: (
    <>
      <path d="M12 3.5l7.5 3v5.5c0 4.5-3.2 7.5-7.5 8.5-4.3-1-7.5-4-7.5-8.5V6.5z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  day: (
    <>
      <path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" />
      <circle cx="12" cy="10" r="2.3" />
    </>
  ),
  claims: (
    <>
      <path d="M4 16.5h16M5.5 16.5l1.6-5.2a2 2 0 0 1 1.9-1.4h6a2 2 0 0 1 1.9 1.4l1.6 5.2" />
      <circle cx="7.5" cy="18.5" r="1.6" />
      <circle cx="16.5" cy="18.5" r="1.6" />
      <path d="M12 3.5v3M10 5h4" />
    </>
  ),
  gang: (
    <>
      <circle cx="9" cy="8" r="3" />
      <circle cx="17" cy="9" r="2.3" />
      <path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5M14.5 15.2c.8-.5 1.6-.7 2.5-.7 2.2 0 3.7 1.5 4.2 4" />
    </>
  ),
  cash: (
    <>
      <rect x="3.5" y="6.5" width="17" height="12" rx="2.5" />
      <path d="M16 12.5h2M3.5 10h17" />
    </>
  ),
  escalated: (
    <>
      <path d="M12 4l9 15.5H3z" />
      <path d="M12 10v4.5M12 17.2h.01" />
    </>
  ),
  bell: (
    <>
      <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </>
  ),
  account: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6" />
    </>
  ),
  reports: (
    <>
      <path d="M5 4.5h14v12H9l-4 3.5z" />
      <path d="M9 9h6M9 12h4" />
    </>
  ),
  work: (
    <>
      <path d="M4 11.5L12 4l8 7.5" />
      <path d="M6 10v10.5h12V10" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.5a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.6M12 17h.01" />
    </>
  ),
  training: (
    <>
      <path d="M3 9l9-4.5L21 9l-9 4.5z" />
      <path d="M7 11v4.5c1.5 1.5 3 2 5 2s3.5-.5 5-2V11" />
    </>
  ),
};

/** My work's own pages, each with its own icon. */
export const PAGE_ICON: Record<string, string> = {
  "/field": "day",
  "/field/claims": "claims",
  "/field/gangs": "gang",
  "/petty-cash": "cash",
  "/escalated": "escalated",
  "/notifications": "bell",
  "/my-notifications": "bell",
  "/account": "account",
  "/my-reports": "reports",
};

export const GROUP_ICON: Record<string, string> = {
  "My work": "work",
  Sales: "sales",
  Planning: "planning",
  Site: "site",
  Billing: "billing",
  Stores: "stores",
  Accounts: "accounts",
  Analytics: "analytics",
  Masters: "masters",
  Settings: "settings",
  Administration: "admin",
};

export function NavIcon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {P[name] ?? P.work}
    </svg>
  );
}
