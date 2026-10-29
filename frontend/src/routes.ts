// Every page outside the menu, with who may open it (the guard in App.tsx; any of these). The role
// SOPs (docs/sop) must cover each one for the roles that open it: the backend checks that against
// its copy, backend/app/ops/routes.json (UPDATE_MENU=1 npm test writes it; routes.test.ts keeps
// this list equal to App.tsx).

const DASHBOARDS = ["dashboard.company", "dashboard.sales", "dashboard.site", "dashboard.finance", "dashboard.purchase"];
export const STAFF_ANY = ["dashboard.view", "site.view", "leads.view", "tender.view", "billing.view", "payables.view", "po.view", "admin.users", "store.view", "delivery.view"];

export type PageRoute = { path: string; perms: string[] };

export const DETAIL_ROUTES: PageRoute[] = [
  { path: "/drill", perms: DASHBOARDS },
  { path: "/dashboard/details", perms: DASHBOARDS },
  { path: "/surveys/pilot", perms: ["survey.view"] },
  { path: "/surveys/:id", perms: ["survey.view"] },
  { path: "/deliveries/:id", perms: ["delivery.view"] },
  { path: "/sites/:id", perms: ["site.view"] },
  { path: "/sites/:id/new-area", perms: ["site.update", "site.edit"] },
  { path: "/sites/:id/fronts", perms: ["site.view"] },
  { path: "/sites/:id/takeoff", perms: ["takeoff.view"] },
  { path: "/sites/:id/measure", perms: ["billing.view"] },
  { path: "/sites/:id/building", perms: ["building.edit", "site.view"] },
  { path: "/sites/:id/methodology", perms: ["methodology.site"] },
  { path: "/sites/:id/material-plan", perms: ["planning.view", "indent.view"] },
  { path: "/sites/:id/measurements", perms: ["closeout.billing"] },
  { path: "/sites/:id/reconciliation", perms: ["closeout.billing"] },
  { path: "/sites/:id/labour-claims", perms: ["closeout.billing", "closeout.claim_approve"] },
  { path: "/sites/:id/zones", perms: ["closeout.site", "closeout.billing"] },
  { path: "/sites/:id/billing-checklist", perms: ["closeout.billing"] },
  { path: "/sites/:id/work-completions", perms: ["closeout.billing"] },
  { path: "/quotations/:id", perms: ["quotation.view"] },
  { path: "/quotations/:id/working", perms: ["quotation.view"] },
  { path: "/systems/:id", perms: ["library.view"] },
  { path: "/tenders/:id", perms: ["tender.view"] },
  { path: "/leads/:id", perms: ["leads.view"] },
  { path: "/rfqs/:id", perms: ["po.view"] },
  { path: "/prices/:id", perms: ["tender.margin"] },
  { path: "/field/days/:id", perms: ["field.track", "field.claims"] },
  { path: "/field/claims/:id", perms: ["field.track", "field.claims"] },
  { path: "/knowledge/templates/:id", perms: ["knowledge.view"] },
  { path: "/knowledge/match/tender/:id", perms: ["knowledge.view"] },
  { path: "/methodology/systems/:id", perms: ["methodology.view"] },
  { path: "/methodology/standards/:id", perms: ["methodology.view"] },
  { path: "/methodology/m/:id", perms: ["methodology.view"] },
  { path: "/assignments/:id", perms: ["jobs.assign", "planning.view"] },
  { path: "/my-site/:id", perms: ["site.view"] },
  { path: "/my-site/:id/report", perms: ["dpr.edit"] },
  { path: "/my-site/:id/material", perms: ["material_request.create"] },
  { path: "/estimates/:id", perms: ["estimate.view"] },
  { path: "/estimates/:id/drawing", perms: ["estimate.view"] },
  { path: "/help/how-it-works", perms: STAFF_ANY },
  { path: "/help/sop", perms: STAFF_ANY },
  { path: "/purchase-orders/new", perms: ["po.edit"] },
  { path: "/purchase-orders/:id", perms: ["po.view"] },
  { path: "/stores/:id", perms: ["store.view"] },
  { path: "/work-orders/:id", perms: ["wo.view"] },
  { path: "/bills/:id", perms: ["billing.view", "closeout.billing", "closeout.payments"] },
  { path: "/settings/issue-log/:id", perms: ["issuelog.view"] },
  // the client's portal (its own sites)
  { path: "/portal", perms: ["portal.view"] },
  { path: "/portal/sites/:id", perms: ["portal.view"] },
  { path: "/portal/reports", perms: ["portal.view"] },
  { path: "/portal/sop", perms: ["portal.view"] },
];

/** Open without a login (the first-login section of every SOP covers them). */
export const PUBLIC_ROUTES = ["/login", "/set-password/:token", "/portal/invite/:token", "/r/:token"];

/** Old links that only move on to a page above. */
export const REDIRECTS = ["/bill-tracking", "/billing/tracking"];

export function routePerms(path: string): string[] {
  const hit = DETAIL_ROUTES.find((r) => r.path === path);
  if (!hit) throw new Error(`No permissions for ${path} in routes.ts`);
  return hit.perms;
}
