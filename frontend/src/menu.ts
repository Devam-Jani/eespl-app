export type MenuItem = {
  to: string;
  label: string;
  /** In the menu of the users holding any of these (the job's permission). */
  perms: string[];
  /** Who may open the page (e.g. by a link from another page): any of these; default perms. */
  view?: string[];
  /** ...and all of these as well (e.g. tender.margin for pages that show cost). */
  all?: string[];
  /** ...and none of these (a page for one job only, e.g. sales' read-only bills). */
  none?: string[];
  section: Group;
};

/** The menu's groups, by what people do; each shows only the pages the role may open. */
export const GROUPS = ["My work", "Sales", "Planning", "Site", "Billing", "Stores", "Accounts", "Analytics", "Masters", "Settings", "Administration"] as const;
export type Group = (typeof GROUPS)[number];

// every staff role holds at least one of these: My work is everyone's home
const STAFF = ["dashboard.view", "site.view", "leads.view", "tender.view", "billing.view", "payables.view", "po.view", "admin.users", "store.view", "delivery.view"];

// Reviewed per job (go-live): a page is in the menu of the roles whose job it is (the permission
// that acts on it), not of every role that may read it through another page. Pinned per role in
// menu.test.ts; the grants themselves stay what the API needs.
export const MENU: MenuItem[] = [
  // my work: everyone's own day
  { to: "/my-work", label: "My work", perms: STAFF, section: "My work" },
  { to: "/notifications", label: "Notifications", perms: STAFF, section: "My work" },
  { to: "/dashboard", label: "Dashboard", perms: ["dashboard.company", "dashboard.sales", "dashboard.site", "dashboard.finance", "dashboard.purchase"], section: "My work" },
  { to: "/alerts", label: "Alerts", perms: ["dashboard.company", "dashboard.sales", "dashboard.site", "dashboard.finance", "dashboard.purchase"], section: "My work" },
  { to: "/field", label: "My day (check-in)", perms: ["field.track"], section: "My work" },
  { to: "/field/claims", label: "Travel claims", perms: ["field.track", "field.claims"], section: "My work" },
  { to: "/field/gangs", label: "Gang check-in", perms: ["field.gang"], section: "My work" },
  { to: "/petty-cash", label: "Petty cash", perms: ["expense.create", "expense.approve"], section: "My work" },
  { to: "/escalated", label: "Escalated (all sites)", perms: ["process.escalations", "process.rules"], section: "My work" },
  { to: "/my-notifications", label: "My notifications", perms: STAFF, section: "My work" },
  { to: "/account", label: "My account", perms: STAFF, section: "My work" },
  // sales
  { to: "/leads", label: "Leads", perms: ["leads.edit"], view: ["leads.view"], section: "Sales" },
  { to: "/quotations", label: "Quotations", perms: ["quotation.edit"], view: ["quotation.view"], section: "Sales" },
  { to: "/tenders", label: "Tenders", perms: ["tender.edit"], view: ["tender.view"], section: "Sales" },
  { to: "/scorecard", label: "Closure scorecard", perms: ["scorecard.view"], all: ["leads.edit"], section: "Sales" },
  // sales follows its own clients' bills and payments, read-only; billing works them in Billing
  { to: "/sales/bills", label: "Bills and payments", perms: ["closeout.payments"], all: ["leads.edit"], none: ["closeout.billing", "billing.edit"], section: "Sales" },
  { to: "/sales/work-orders", label: "Client work orders", perms: ["wo.edit"], all: ["leads.edit"], none: ["closeout.billing"], section: "Sales" },
  // planning
  { to: "/enquiries", label: "Enquiries to allocate", perms: ["leads.allocate"], section: "Planning" },
  { to: "/planning/board", label: "Site status board", perms: ["planning.view"], view: ["planning.view", "site.view"], section: "Planning" },
  { to: "/new-areas", label: "New areas (planning)", perms: ["sitearea.approve"], section: "Planning" },
  // site
  { to: "/sites", label: "Sites", perms: ["site.update", "closeout.billing", "closeout.site", "planning.view"], view: ["site.view"], all: ["site.view"], section: "Site" },
  { to: "/surveys", label: "Site surveys", perms: ["survey.edit"], view: ["survey.view"], section: "Site" },
  { to: "/daily-reports", label: "Daily reports", perms: ["dpr.edit", "dpr.approve"], view: ["dpr.view"], section: "Site" },
  { to: "/attendance", label: "Attendance", perms: ["attendance.manage"], view: ["labour.view"], all: ["site.update"], section: "Site" },
  { to: "/labour", label: "Labour", perms: ["labour.edit"], view: ["labour.view"], section: "Site" },
  { to: "/deliveries", label: "Deliveries at site", perms: ["delivery.confirm"], view: ["delivery.view"], section: "Site" },
  { to: "/snags", label: "Snags", perms: ["site.update", "closeout.site"], view: ["site.view"], all: ["site.view"], section: "Site" },
  { to: "/issues", label: "Issue log", perms: ["site.update", "closeout.site", "closeout.billing", "planning.view"], view: ["issues.view"], all: ["issues.view"], section: "Site" },
  { to: "/field/team", label: "Team map", perms: ["field.team"], view: ["field.track"], section: "Site" },
  // billing
  { to: "/measurements", label: "Measurement book", perms: ["closeout.billing"], view: ["measurement.view"], section: "Billing" },
  {
    to: "/bills",
    label: "Bills",
    perms: ["billing.edit", "closeout.billing"],
    view: ["billing.view", "closeout.billing", "closeout.payments"],
    section: "Billing",
  },
  { to: "/billing", label: "Client billing", perms: ["billing.edit"], view: ["billing.view"], section: "Billing" },
  { to: "/ready-to-bill", label: "Ready to bill", perms: ["billing.edit"], view: ["billing.view"], all: ["closeout.billing"], section: "Billing" },
  { to: "/billing/checklist", label: "Billing checklist", perms: ["closeout.billing"], section: "Billing" },
  { to: "/work-orders", label: "Client work orders", perms: ["wo.view"], all: ["closeout.billing"], section: "Billing" },
  { to: "/guarantees", label: "Guarantee register", perms: ["closeout.billing"], view: ["closeout.billing", "closeout.payments"], section: "Billing" },
  { to: "/labour-check", label: "Labour bill check", perms: ["labourcheck.check"], section: "Billing" },
  { to: "/labour-rates", label: "Labour rates and bills", perms: ["subcon.view"], view: ["subcon.view", "payables.view"], all: ["billing.edit"], section: "Billing" },
  // stores and purchase
  { to: "/indents", label: "Indents", perms: ["indent.approve", "po.edit"], view: ["indent.view", "indent.create", "indent.approve"], section: "Stores" },
  { to: "/rfqs", label: "RFQs", perms: ["po.edit"], view: ["po.view"], section: "Stores" },
  { to: "/purchase-orders", label: "Purchase orders", perms: ["po.edit"], view: ["po.view"], section: "Stores" },
  { to: "/grns", label: "Goods receipts (GRN)", perms: ["grn.approve"], view: ["grn.view"], section: "Stores" },
  { to: "/stores", label: "Stores & stock", perms: ["grn.approve"], view: ["store.view"], section: "Stores" },
  { to: "/transfers", label: "Transfers", perms: ["grn.approve"], view: ["store.view"], section: "Stores" },
  { to: "/freight", label: "Site freight", perms: ["po.edit"], view: ["po.view", "store.view"], section: "Stores" },
  { to: "/rate-contracts", label: "Rate contracts", perms: ["ratecontract.edit"], view: ["ratecontract.view"], section: "Stores" },
  { to: "/assets", label: "Tools & equipment", perms: ["asset.edit"], view: ["asset.view"], section: "Stores" },
  // accounts
  { to: "/billing/payments", label: "Payment follow-up", perms: ["closeout.payments"], all: ["finance.view"], section: "Accounts" },
  { to: "/payables", label: "Payables", perms: ["payables.edit"], view: ["payables.view"], section: "Accounts" },
  { to: "/payroll", label: "Payroll & wages", perms: ["payroll.edit"], view: ["payroll.view", "payables.view"], section: "Accounts" },
  { to: "/site-profit", label: "Site profit", perms: ["tender.margin"], all: ["finance.view"], section: "Accounts" },
  { to: "/tally", label: "Tally export", perms: ["finance.export"], section: "Accounts" },
  // analytics: the company's and finance's views (each role's own dashboard is under My work)
  { to: "/analytics/sites", label: "Sites", perms: ["dashboard.company", "planning.view"], view: ["dashboard.company", "dashboard.site"], section: "Analytics" },
  { to: "/analytics/finance", label: "Finance", perms: ["dashboard.company", "dashboard.finance"], section: "Analytics" },
  { to: "/analytics/profitability", label: "Profitability", perms: ["dashboard.company", "dashboard.finance"], all: ["tender.margin"], section: "Analytics" },
  { to: "/analytics/purchase", label: "Purchase", perms: ["dashboard.company", "dashboard.purchase"], section: "Analytics" },
  { to: "/analytics/labour", label: "Labour", perms: ["dashboard.company", "planning.view"], view: ["dashboard.company", "dashboard.site"], section: "Analytics" },
  { to: "/analytics/strategy", label: "Strategy: win more sites", perms: ["dashboard.company"], view: ["dashboard.company", "dashboard.sales"], section: "Analytics" },
  { to: "/reports/productivity", label: "Labour productivity", perms: ["dashboard.company", "planning.view"], view: ["site.view"], section: "Analytics" },
  { to: "/consumption", label: "Consumption variance", perms: ["dashboard.company", "planning.view"], view: ["site.view"], section: "Analytics" },
  { to: "/reports", label: "Reports", perms: ["dashboard.company"], section: "Analytics" },
  // masters: the people who keep them
  { to: "/clients", label: "Clients", perms: ["clients.edit"], view: ["clients.view"], section: "Masters" },
  { to: "/channels", label: "Channels", perms: ["clients.edit"], view: ["clients.view"], all: ["leads.allocate"], section: "Masters" },
  { to: "/products", label: "Products", perms: ["library.edit"], view: ["library.view"], section: "Masters" },
  { to: "/systems", label: "Systems (rate calculator)", perms: ["library.edit"], view: ["library.view"], section: "Masters" },
  { to: "/rate-library", label: "Rate library", perms: ["library.edit"], view: ["library.view"], section: "Masters" },
  { to: "/knowledge", label: "BOQ knowledge", perms: ["knowledge.edit"], view: ["knowledge.view"], section: "Masters" },
  { to: "/methodology", label: "Methodology builder", perms: ["methodology.edit"], view: ["methodology.view"], section: "Masters" },
  { to: "/tc-library", label: "T&C library", perms: ["library.edit"], view: ["library.view"], section: "Masters" },
  { to: "/vendors", label: "Vendors", perms: ["vendors.edit"], view: ["vendors.view"], section: "Masters" },
  { to: "/subcontractors", label: "Subcontractors", perms: ["subcon.edit"], view: ["subcon.view"], section: "Masters" },
  // settings
  { to: "/settings/company", label: "Company profile", perms: ["settings.company"], section: "Settings" },
  { to: "/settings/gstins", label: "GSTIN addresses", perms: ["settings.company"], section: "Settings" },
  { to: "/settings/bank-accounts", label: "Bank accounts", perms: ["settings.company"], view: ["settings.company", "finance.view"], section: "Settings" },
  { to: "/settings/categories", label: "Categories", perms: ["library.edit"], all: ["settings.company"], section: "Settings" },
  { to: "/settings/tags", label: "Tags", perms: ["library.edit"], all: ["settings.company"], section: "Settings" },
  { to: "/settings/units", label: "Units & conversions", perms: ["library.edit"], all: ["settings.company"], section: "Settings" },
  { to: "/settings/kylas", label: "Integrations: Kylas", perms: ["admin.settings"], section: "Settings" },
  { to: "/settings/purchase", label: "Purchase", perms: ["process.rules"], view: ["settings.company", "po.edit"], section: "Settings" },
  { to: "/settings/stage-templates", label: "Stage templates", perms: ["planning.edit", "process.rules"], view: ["site.view"], section: "Settings" },
  { to: "/settings/checklists", label: "Checklist templates", perms: ["planning.edit", "process.rules"], view: ["inspection.view"], section: "Settings" },
  { to: "/settings/quotation-library", label: "Quotation library", perms: ["quotation.view"], all: ["quotation.template.edit"], section: "Settings" },
  { to: "/settings/site-control", label: "Site control", perms: ["process.rules"], view: ["settings.company"], section: "Settings" },
  { to: "/settings/survey", label: "Site survey", perms: ["survey.view"], all: ["settings.company"], section: "Settings" },
  { to: "/settings/finance", label: "Finance", perms: ["finance.edit"], view: ["billing.view", "payables.view", "payroll.view"], section: "Settings" },
  { to: "/settings/client-roles", label: "Client roles", perms: ["portal.roles"], section: "Settings" },
  {
    to: "/settings/team",
    label: "Team",
    perms: ["planning.edit", "grants.manage", "process.rules"],
    view: ["planning.edit", "settings.company", "grants.manage"],
    section: "Settings",
  },
  { to: "/settings/process", label: "Process rules", perms: ["process.rules"], section: "Settings" },
  { to: "/settings/field", label: "Field tracking", perms: ["field.admin"], section: "Settings" },
  // administration
  { to: "/admin/users", label: "Users", perms: ["admin.users"], section: "Administration" },
  { to: "/admin/roles", label: "Roles & permissions", perms: ["admin.roles"], section: "Administration" },
  { to: "/admin/audit", label: "Audit log", perms: ["audit.view"], section: "Administration" },
  { to: "/admin/user-import", label: "User import", perms: ["admin.users"], section: "Administration" },
  { to: "/admin/backups", label: "Backups and storage", perms: ["system.ops"], section: "Administration" },
  { to: "/settings/security", label: "Security", perms: ["admin.users", "system.ops"], section: "Administration" },
  { to: "/settings/roles-report", label: "Who sees what (roles)", perms: ["system.ops"], section: "Administration" },
  { to: "/settings/help", label: "Help texts", perms: ["help.edit"], section: "Administration" },
];

/** The pages a user may open, by group (groups with none left out). */
export function shows(item: MenuItem, can: (...perms: string[]) => boolean): boolean {
  return can(...item.perms) && (item.all ?? []).every((c) => can(c)) && !(item.none ?? []).some((c) => can(c));
}

export function visibleGroups(can: (...perms: string[]) => boolean): { group: Group; items: MenuItem[] }[] {
  const visible = MENU.filter((item) => shows(item, can));
  return GROUPS.map((group) => ({ group, items: visible.filter((i) => i.section === group) })).filter((g) => g.items.length > 0);
}

/** The group a path belongs to (the longest matching page). */
export function groupOf(path: string): Group | null {
  const hit = MENU.filter((i) => path === i.to || path.startsWith(`${i.to}/`)).sort((a, b) => b.to.length - a.to.length)[0];
  return hit ? hit.section : null;
}
