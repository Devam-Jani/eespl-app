export type MenuItem = {
  to: string;
  label: string;
  /** Shown when the user holds any of these permissions. */
  perms: string[];
  section: "Modules" | "Masters" | "Settings" | "Administration";
};

export const MENU: MenuItem[] = [
  { to: "/dashboard", label: "Dashboard", perms: ["dashboard.view"], section: "Modules" },
  { to: "/clients", label: "Clients", perms: ["clients.view"], section: "Masters" },
  { to: "/channels", label: "Channels", perms: ["clients.view"], section: "Masters" },
  { to: "/products", label: "Products", perms: ["library.view"], section: "Masters" },
  { to: "/systems", label: "Systems (rate calculator)", perms: ["library.view"], section: "Masters" },
  { to: "/rate-library", label: "Rate library", perms: ["library.view"], section: "Masters" },
  { to: "/tc-library", label: "T&C library", perms: ["library.view"], section: "Masters" },
  { to: "/vendors", label: "Vendors", perms: ["vendors.view"], section: "Masters" },
  { to: "/settings/company", label: "Company profile", perms: ["settings.company"], section: "Settings" },
  { to: "/settings/gstins", label: "GSTIN addresses", perms: ["settings.company"], section: "Settings" },
  { to: "/settings/bank-accounts", label: "Bank accounts", perms: ["settings.company", "finance.view"], section: "Settings" },
  { to: "/settings/categories", label: "Categories", perms: ["library.edit"], section: "Settings" },
  { to: "/settings/tags", label: "Tags", perms: ["library.edit"], section: "Settings" },
  { to: "/settings/units", label: "Units & conversions", perms: ["library.edit"], section: "Settings" },
  { to: "/settings/kylas", label: "Integrations › Kylas", perms: ["admin.settings"], section: "Settings" },
  { to: "/settings/purchase", label: "Purchase", perms: ["settings.company", "po.edit"], section: "Settings" },
  { to: "/settings/stage-templates", label: "Stage templates", perms: ["site.view"], section: "Settings" },
  { to: "/leads", label: "Leads", perms: ["leads.view"], section: "Modules" },
  { to: "/tenders", label: "Tenders", perms: ["tender.view"], section: "Modules" },
  { to: "/sites", label: "Sites", perms: ["site.view"], section: "Modules" },
  { to: "/indents", label: "Indents", perms: ["indent.view", "indent.create", "indent.approve"], section: "Modules" },
  { to: "/rfqs", label: "RFQs", perms: ["po.view"], section: "Modules" },
  { to: "/purchase-orders", label: "Purchase orders", perms: ["po.view"], section: "Modules" },
  { to: "/grns", label: "Goods receipts (GRN)", perms: ["grn.view"], section: "Modules" },
  { to: "/stores", label: "Stores & stock", perms: ["store.view"], section: "Modules" },
  { to: "/transfers", label: "Transfers", perms: ["store.view"], section: "Modules" },
  { to: "/freight", label: "Site freight", perms: ["po.view", "store.view"], section: "Modules" },
  { to: "/attendance", label: "Attendance", perms: ["attendance.manage"], section: "Modules" },
  { to: "/petty-cash", label: "Petty cash", perms: ["pettycash.manage"], section: "Modules" },
  { to: "/finance", label: "Finance", perms: ["finance.view", "finance.edit"], section: "Modules" },
  { to: "/admin/users", label: "Users", perms: ["admin.users"], section: "Administration" },
  { to: "/admin/roles", label: "Roles & permissions", perms: ["admin.roles"], section: "Administration" },
  { to: "/admin/audit", label: "Audit log", perms: ["audit.view"], section: "Administration" },
];
