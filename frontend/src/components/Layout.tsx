// The app shell (EESPL UI v1): on a desktop the 248 px sidebar (My work: Dashboard, Approvals with
// its count, Alerts; Company: the role's own menu) with the training company at the bottom, and a
// header with the page's section, search (Ctrl+K), the bell and the person's menu (theme, account,
// reports, sign out). A tablet folds the sidebar to icons; on a phone site roles get bottom tabs
// (My day, Sites, Materials, Me) and everyone else the menu in a drawer.
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { PageErrorBoundary } from "../helper/Helper";
import type { Group } from "../menu";
import { groupOf, MENU, visibleGroups } from "../menu";
import { GoLiveBanner, HelpButton, TrainingBanner, useMode } from "../ops/Pages";
import { HowToLink } from "../help/HowTo";
import { Button, Icon, initials, NavItem } from "../ui/components";
import { GROUP_ICON, NavIcon, PAGE_ICON } from "../ui/navIcons";
import { prefetch } from "../ui/prefetch";
import { useTheme } from "../ui/theme";
import Bell from "./Bell";
import { isPhone, loadOpenGroups, saveOpenGroups } from "./menuState";

// search loads when first opened (or when the pointer comes near it)
const loadPalette = () => import("../ui/CommandPalette");
const CommandPalette = lazy(() => loadPalette().then((m) => ({ default: m.CommandPalette })));

const SITE_ROLES = ["site_engineer", "site_supervisor", "site_receiver"];
const OFFICE_ROLES = ["director", "office_admin", "super_admin", "planning", "billing", "accounts", "sales", "estimator", "store_purchase"];
const DASHBOARD = ["dashboard.company", "dashboard.sales", "dashboard.site", "dashboard.finance", "dashboard.purchase"];
// My work's own pages are in the top section; the rest of the old My work group stays under it
const TOP = new Set(["/my-work", "/dashboard", "/alerts", "/notifications", "/my-notifications", "/account", "/my-reports"]);

/** A site role (and no office role): the phone gets bottom tabs. */
export function isSiteRole(codes: string[]): boolean {
  return codes.some((c) => SITE_ROLES.includes(c)) && !codes.some((c) => OFFICE_ROLES.includes(c));
}

function useWidth(): number {
  const [w, setW] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1440));
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return w;
}

/** A text field has the focus (the phone's keyboard is up): the bottom tabs step aside. */
function useTyping() {
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    const on = () => {
      const el = document.activeElement;
      setTyping(el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && !NOT_TYPED.has(el.type)));
    };
    const off = () => setTimeout(on, 0); // the next field's focusin comes after: no flicker between fields
    document.addEventListener("focusin", on);
    document.addEventListener("focusout", off);
    return () => {
      document.removeEventListener("focusin", on);
      document.removeEventListener("focusout", off);
    };
  }, []);
  return typing;
}
const NOT_TYPED = new Set(["checkbox", "radio", "button", "submit", "reset", "file", "range", "color", "image", "hidden"]);

export default function Layout() {
  const { me, can, logout } = useAuth();
  const groups = visibleGroups(can);
  const mode = useMode();
  const location = useLocation();
  const navigate = useNavigate();
  const width = useWidth();
  const phone = isPhone(width);
  const tablet = !phone && width <= 1100;
  const userId = me?.user.id ?? "";
  const roleCodes = me?.roles.map((r) => r.code) ?? [];
  const roleName = me?.roles[0]?.name ?? "Staff";
  const siteRole = isSiteRole(roleCodes);
  const [theme, setTheme] = useTheme(userId || null, me?.user.ui_theme ?? null);

  const [drawer, setDrawer] = useState(false); // phone: the menu; tablet: the folded sidebar opened
  const [meOpen, setMeOpen] = useState(false);
  const [search, setSearch] = useState(false);
  const typing = useTyping();
  const [open, setOpen] = useState<Record<string, boolean>>(() => loadOpenGroups(userId));
  useEffect(() => setOpen(loadOpenGroups(userId)), [userId]);
  const here = groupOf(location.pathname);
  const isOpen = (g: Group) => open[g] ?? g === here;
  const toggle = (g: Group) => {
    const next = { ...open, [g]: !isOpen(g) };
    setOpen(next);
    saveOpenGroups(userId, next);
  };
  useEffect(() => {
    setDrawer(false);
    setMeOpen(false);
  }, [location.pathname]);

  // Ctrl+K (or "/" outside a field) opens search anywhere
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && (e.target.closest("input, textarea, select, [contenteditable]") !== null);
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  // My work counts (refreshed on page changes, at most every 15 s except on My work itself)
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
  const approvals = Object.values(counts).reduce((a, b) => a + b, 0);

  const myWork = groups.find((g) => g.group === "My work")?.items.filter((i) => !TOP.has(i.to)) ?? [];
  const company = groups.filter((g) => g.group !== "My work");
  const title = MENU.find((i) => location.pathname === i.to)?.label ?? here ?? "";
  const folded = tablet && !drawer;

  const sidebar = (
    <aside className={`app-sidebar ${folded ? "folded" : ""} ${phone ? (drawer ? "drawer-open" : "drawer-shut") : ""}`} aria-label="Menu">
      <NavLink to="/" className="app-logo" aria-label="EESPL home">
        <span className="app-mark">E</span>
        {!folded && (
          <span className="app-name">
            <b>EESPL</b>
            <small>Waterproofing ERP</small>
          </span>
        )}
      </NavLink>
      <nav className="app-nav">
        <div className="nav-group">
          {!folded && <p className="nav-heading">My work</p>}
          {can(...DASHBOARD) && <NavItem to="/dashboard" label="Dashboard" icon={<NavIcon name="dashboard" />} onHover={() => prefetch("/dashboard")} />}
          <NavItem to="/my-work" label="Approvals" count={approvals} icon={<NavIcon name="approvals" />} onHover={() => prefetch("/my-work")} />
          {can(...DASHBOARD) ? (
            <NavItem to="/alerts" label="Alerts" icon={<NavIcon name="alerts" />} onHover={() => prefetch("/alerts")} />
          ) : (
            <NavItem to="/notifications" label="Alerts" icon={<NavIcon name="alerts" />} onHover={() => prefetch("/notifications")} />
          )}
          {myWork.map((i) => (
            <NavItem key={i.to} to={i.to} label={i.label} count={counts[i.to]} icon={<NavIcon name={PAGE_ICON[i.to] ?? "work"} />} onHover={() => prefetch(i.to)} />
          ))}
        </div>
        <div className="nav-group">
          {!folded && <p className="nav-heading">Company</p>}
          {company.map(({ group, items }) => {
            const opened = !folded && isOpen(group);
            const total = items.reduce((n, i) => n + (counts[i.to] ?? 0), 0);
            return (
              <div key={group} className={`nav-section ${opened ? "open" : ""} ${here === group ? "here" : ""}`}>
                <button
                  type="button"
                  className="nav-item nav-toggle"
                  aria-expanded={opened}
                  title={folded ? group : undefined}
                  onClick={() => (folded ? (setDrawer(true), setOpen({ ...open, [group]: true })) : toggle(group))}
                  onMouseEnter={() => items[0] && prefetch(items[0].to)}
                >
                  <span className="nav-icon">
                    <NavIcon name={GROUP_ICON[group]} />
                  </span>
                  <span className="nav-label">{group}</span>
                  {!opened && total > 0 && <span className="nav-count">{total}</span>}
                </button>
                {opened && (
                  <div className="nav-sub">
                    {items.map((i) => (
                      <NavItem key={i.to} to={i.to} label={i.label} count={counts[i.to]} onHover={() => prefetch(i.to)} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>
      {mode && !mode.training && mode.training_url && !folded && (
        <a className="app-training" href={mode.training_url}>
          <span>Practise without touching real data</span>
          <b>Open the training company</b>
        </a>
      )}
      {mode && !mode.training && mode.training_url && folded && (
        <a className="nav-item" href={mode.training_url} title="Open the training company" aria-label="Open the training company">
          <span className="nav-icon">
            <NavIcon name="training" />
          </span>
        </a>
      )}
    </aside>
  );

  return (
    <div className={`app ${tablet ? "is-tablet" : ""} ${phone ? "is-phone" : ""} ${phone && siteRole ? "has-tabs" : ""} ${typing ? "typing" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to the page
      </a>
      {(drawer || meOpen) && <div className="app-scrim" onClick={() => (setDrawer(false), setMeOpen(false))} aria-hidden="true" />}
      {(!phone || drawer) && sidebar}
      <div className="app-main">
        <header className="app-header">
          {(phone && !siteRole) || tablet ? (
            <Button variant="ghost" icon aria-label="Menu" aria-expanded={drawer} onClick={() => setDrawer(!drawer)}>
              <span aria-hidden="true">☰</span>
            </Button>
          ) : null}
          <div className="app-title">
            <span className="app-section">{here && here !== title ? here : ""}</span>
            <span className="app-page">{title}</span>
          </div>
          <button type="button" className="app-search" onClick={() => setSearch(true)} onMouseEnter={() => void loadPalette()} onFocus={() => void loadPalette()} aria-label="Search (Ctrl+K)">
            <Icon name="search" />
            <span className="app-search-text">Search sites, bills, people, or type an action…</span>
            <kbd>Ctrl K</kbd>
          </button>
          <HowToLink />
          <HelpButton />
          <Bell allLink="/notifications" />
          <div className="app-me-wrap">
            <button type="button" className="app-me" aria-haspopup="menu" aria-expanded={meOpen} onClick={() => setMeOpen(!meOpen)} title={me?.user.full_name}>
              <span className="app-avatar" aria-hidden="true">
                {initials(me?.user.full_name ?? roleName)}
              </span>
              <span className="app-me-role">{roleName}</span>
            </button>
            {meOpen && (
              <div className="app-menu" role="menu" aria-label="Me">
                <div className="app-menu-head">
                  <b>{me?.user.full_name}</b>
                  <span className="muted small">{me?.roles.map((r) => r.name).join(", ")}</span>
                </div>
                <div className="app-theme" role="group" aria-label="Look">
                  <span className="small muted">Look</span>
                  <button type="button" className="chip" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>
                    Dark
                  </button>
                  <button type="button" className="chip" aria-pressed={theme === "light"} onClick={() => setTheme("light")}>
                    Light
                  </button>
                </div>
                <button role="menuitem" className="app-menu-item" onClick={() => navigate("/account")}>
                  My account
                </button>
                <button role="menuitem" className="app-menu-item" onClick={() => navigate("/my-notifications")}>
                  My notifications
                </button>
                <button role="menuitem" className="app-menu-item" onClick={() => navigate("/my-reports")}>
                  My reports
                </button>
                <button role="menuitem" className="app-menu-item" onClick={() => navigate("/help/how-it-works")}>
                  How the app works
                </button>
                <button role="menuitem" className="app-menu-item" onClick={() => navigate("/help/sop")}>
                  How to (my SOP)
                </button>
                <button role="menuitem" className="app-menu-item" onClick={() => void logout()}>
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <TrainingBanner mode={mode} />
        <GoLiveBanner />
        <main id="main" className="app-content" tabIndex={-1}>
          <PageErrorBoundary key={location.pathname}>
            <Outlet />
          </PageErrorBoundary>
        </main>
      </div>
      {phone && siteRole && (
        <nav className="app-tabs" aria-label="Main">
          <NavLink to="/my-work" className="app-tab">
            <Icon name="day" size={22} />
            My day
          </NavLink>
          <NavLink to="/sites" className="app-tab">
            <Icon name="sites" size={22} />
            Sites
          </NavLink>
          <NavLink to={can("indent.view", "indent.create") ? "/indents" : "/deliveries"} className="app-tab">
            <Icon name="materials" size={22} />
            Materials
          </NavLink>
          <button type="button" className={`app-tab ${drawer ? "active" : ""}`} onClick={() => setDrawer(!drawer)} aria-expanded={drawer}>
            <Icon name="me" size={22} />
            Me
          </button>
        </nav>
      )}
      {search && (
        <Suspense fallback={null}>
          <CommandPalette can={can} onClose={() => setSearch(false)} />
        </Suspense>
      )}
    </div>
  );
}
