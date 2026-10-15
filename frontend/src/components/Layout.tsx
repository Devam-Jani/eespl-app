import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { MENU } from "../menu";
import Bell from "./Bell";
import { initialMenuOpen, isPhone } from "./menuState";

export default function Layout() {
  const { me, can, logout } = useAuth();
  const visible = MENU.filter((item) => can(...item.perms) && (item.all ?? []).every((c) => can(c)));
  const sections = ["Modules", "Analytics", "Masters", "Settings", "Administration"] as const;
  // My work counts on the menu (refreshed on every page change)
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(() => initialMenuOpen(window.innerWidth));
  // on a phone the menu closes again after picking a page
  useEffect(() => {
    if (isPhone(window.innerWidth)) setMenuOpen(false);
  }, [location.pathname]);
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
      <aside className={`sidebar ${menuOpen ? "menu-open" : "menu-closed"}`}>
        <NavLink to="/" className="brand">
          <span className="brand-mark">E</span> EESPL
        </NavLink>
        {/* on a phone the role is here, not in the header (the name stays there, on one line) */}
        <div className="menu-user">
          <strong>{me?.user.full_name}</strong>
          <span>{me?.roles.map((r) => r.name).join(", ") || "No role"}</span>
        </div>
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
          <button className="btn btn-ghost menu-toggle" aria-expanded={menuOpen} aria-label="Menu" onClick={() => setMenuOpen(!menuOpen)}>
            ☰ Menu
          </button>
          <div className="topbar-user">
            <strong title={me?.user.full_name}>{me?.user.full_name}</strong>
            <span className="muted topbar-role">{me?.roles.map((r) => r.name).join(", ") || "No role"}</span>
          </div>
          <Bell allLink="/notifications" />
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
