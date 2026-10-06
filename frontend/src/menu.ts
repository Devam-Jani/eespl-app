export type MenuItem = {
  to: string;
  label: string;
  /** Shown when the user holds any of these permissions. */
  perms: string[];
  section: "Modules" | "Administration";
};

export const MENU: MenuItem[] = [
  { to: "/dashboard", label: "Dashboard", perms: ["dashboard.view"], section: "Modules" },
  { to: "/library", label: "Library", perms: ["library.view", "library.edit"], section: "Modules" },
  { to: "/tenders", label: "Tenders", perms: ["tender.view", "tender.edit"], section: "Modules" },
  { to: "/sites", label: "Sites", perms: ["site.view", "site.edit", "site.update"], section: "Modules" },
  {
    to: "/indents",
    label: "Indents",
    perms: ["indent.raise", "indent.approve", "indent.dispatch", "indent.receive"],
    section: "Modules",
  },
  { to: "/attendance", label: "Attendance", perms: ["attendance.manage"], section: "Modules" },
  { to: "/petty-cash", label: "Petty cash", perms: ["pettycash.manage"], section: "Modules" },
  { to: "/finance", label: "Finance", perms: ["finance.view", "finance.edit"], section: "Modules" },
  { to: "/admin/users", label: "Users", perms: ["admin.users"], section: "Administration" },
  { to: "/admin/roles", label: "Roles & permissions", perms: ["admin.roles"], section: "Administration" },
  { to: "/admin/audit", label: "Audit log", perms: ["audit.view"], section: "Administration" },
];
