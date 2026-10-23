import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Group } from "../menu";
import { groupOf, visibleGroups } from "../menu";
import {
  GoLiveBanner,
  HelpButton,
  TrainingBanner,
  useMode,
} from "../ops/Pages";
import { HelperCard, PageErrorBoundary } from "../helper/Helper";
import Bell from "./Bell";
import { initialMenuOpen, isPhone, loadOpenGroups, saveOpenGroups } from "./menuState";

export default function Layout() {
  const { me, can, logout } = useAuth();
  const groups = visibleGroups(can);
  const mode = useMode();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(() => initialMenuOpen(window.innerWidth));
  // each user's open groups are remembered (in this browser); the current page's group is open
  const userId = me?.user.id ?? "";
  const [open, setOpen] = useState<Record<string, boolean>>(() => loadOpenGroups(userId));
  useEffect(() => setOpen(loadOpenGroups(userId)), [userId]);
  const here = groupOf(location.pathname);
  // a group the user opened or closed stays so; otherwise My work and the current page's group are open
  const isOpen = (g: Group) => open[g] ?? (g === here || g === "My work");
  const toggle = (g: Group) => {
    const next = { ...open, [g]: !isOpen(g) };
    setOpen(next);
    saveOpenGroups(userId, next);
  };
  // on a phone the menu (a drawer) closes again after picking a page
  useEffect(() => {
    if (isPhone(window.innerWidth)) setMenuOpen(false);
  }, [location.pathname]);
  // My work counts on the menu (refreshed on every page change)
  const [counts, setCounts] = useState<Record<string, number>>({});
  const countedAt = useRef(0);
  useEffect(() => {
    if (!me) return;
    if (location.pathname !== "/my-work" && Date.now() - countedAt.current < 15_000) return;
    countedAt.current = Date.now();
    void api<{ counts: Record<string, number> }>("/api/team/my-work").then(
      (r) => setCounts(r.counts),
      () => setCounts({}),
    );
  }, [me, location.pathname]);

  return (
    <div className="shell">
      {menuOpen && <div className="drawer-backdrop" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
      <aside className={`sidebar ${menuOpen ? "menu-open" : "menu-closed"}`}>
        <NavLink to="/" className="brand">
          <span className="brand-mark">E</span> EESPL
        </NavLink>
        {/* on a phone the role is here, not in the header (the name stays there, on one line) */}
        <div className="menu-user">
          <strong>{me?.user.full_name}</strong>
          <span>{me?.roles.map((r) => r.name).join(", ") || "No role"}</span>
        </div>
        {mode && !mode.training && mode.training_url && (
          <a className="training-link" href={mode.training_url}>
            Practise in the training company
          </a>
        )}
        <nav>
          {groups.map(({ group, items }) => {
            const opened = isOpen(group);
            const total = items.reduce((n, i) => n + (counts[i.to] ?? 0), 0);
            return (
              <div key={group} className={`nav-section ${opened ? "open" : "shut"}`}>
                <button type="button" className="nav-heading nav-toggle" aria-expanded={opened} onClick={() => toggle(group)}>
                  <span>{group}</span>
                  {!opened && total > 0 && <span className="nav-count">{total}</span>}
                  <span className="nav-caret" aria-hidden="true">
                    {opened ? "▾" : "▸"}
                  </span>
                </button>
                {opened &&
                  items.map((item) => (
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
          <HelpButton />
          <Bell allLink="/notifications" />
          <button className="btn btn-ghost" onClick={() => void logout()}>
            Sign out
          </button>
        </header>
        <TrainingBanner mode={mode} />
        <GoLiveBanner />
        <main className="content">
          <PageErrorBoundary key={location.pathname}>
            <Outlet />
          </PageErrorBoundary>
          <HelperCard />
        </main>
      </div>
    </div>
  );
}
