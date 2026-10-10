import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { MENU } from "../menu";
import Bell from "./Bell";

export default function Layout() {
  const { me, can, logout } = useAuth();
  const visible = MENU.filter((item) => can(...item.perms) && (item.all ?? []).every((c) => can(c)));
  const sections = ["Modules", "Analytics", "Masters", "Settings", "Administration"] as const;
  // My work counts on the menu (refreshed on every page change)
  const location = useLocation();
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!me) return;
    void api<{ counts: Record<string, number> }>("/api/team/my-work").then(
      (r) => setCounts(r.counts),
      () => setCounts({}),
    );
  }, [me, location.pathname]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">E</span> EESPL
        </NavLink>
        <nav>
          {sections.map((section) => {
            const items = visible.filter((i) => i.section === section);
            if (items.length === 0) return null;
            return (
              <div key={section} className="nav-section">
                <div className="nav-heading">{section}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} className="nav-link">
                    {item.label}
                    {counts[item.to] ? <span className="nav-count">{counts[item.to]}</span> : null}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-user">
            <strong>{me?.user.full_name}</strong>
            <span className="muted">{me?.roles.map((r) => r.name).join(", ") || "No role"}</span>
          </div>
          <Bell />
          <button className="btn btn-ghost" onClick={() => void logout()}>
            Sign out
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
