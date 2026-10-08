import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { MENU } from "../menu";
import Bell from "./Bell";

export default function Layout() {
  const { me, can, logout } = useAuth();
  const visible = MENU.filter((item) => can(...item.perms) && (item.all ?? []).every((c) => can(c)));
  const sections = ["Modules", "Analytics", "Masters", "Settings", "Administration"] as const;

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
