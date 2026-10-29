// Search anywhere (Ctrl+K or "/"): pages and actions the role may open (from the menu and the
// permissions), and sites, bills, quotations and people by role from the server (scoped there).
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { MENU, type MenuItem } from "../menu";
import { Icon } from "./components";
import { prefetch } from "./prefetch";

type Hit = { id: string; group: string; title: string; note?: string; to: string };
type Can = (...perms: string[]) => boolean;

/** The actions a role may start from anywhere (each opens the page where it is done). */
export const ACTIONS: { title: string; to: string; perms: string[] }[] = [
  { title: "New daily report", to: "/daily-reports?new=1", perms: ["dpr.edit", "dpr.create"] },
  { title: "Raise indent", to: "/indents?new=1", perms: ["indent.create"] },
  { title: "New lead", to: "/leads?new=1", perms: ["leads.edit"] },
  { title: "New quotation", to: "/quotations?new=1", perms: ["quotation.edit"] },
  { title: "New site survey", to: "/surveys?new=1", perms: ["survey.edit"] },
  { title: "Raise a snag", to: "/snags?new=1", perms: ["site.update", "closeout.site"] },
  { title: "Add petty cash expense", to: "/petty-cash?new=1", perms: ["expense.create"] },
  { title: "New purchase order", to: "/purchase-orders/new", perms: ["po.edit"] },
  { title: "Check in for the day", to: "/field", perms: ["field.track"] },
  { title: "Report a problem", to: "/my-reports", perms: [] },
  { title: "How the app works", to: "/help/how-it-works", perms: [] },
  { title: "How to: my role's SOP", to: "/help/sop", perms: [] },
];

function shows(item: MenuItem, can: Can): boolean {
  return can(...(item.view ?? item.perms)) && (!item.all || can(...item.all)) && (!item.none || !can(...item.none));
}

/** What a role finds without asking the server: its pages and its actions. */
export function localHits(query: string, can: Can): Hit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const words = q.split(/\s+/);
  const match = (s: string) => words.every((w) => s.toLowerCase().includes(w));
  const pages = MENU.filter((i) => shows(i, can) && match(`${i.label} ${i.section}`)).map((i) => ({ id: `p${i.to}`, group: "Pages", title: i.label, note: i.section, to: i.to }));
  const actions = ACTIONS.filter((a) => (a.perms.length === 0 || can(...a.perms)) && match(a.title)).map((a) => ({ id: `a${a.to}`, group: "Actions", title: a.title, to: a.to }));
  return [...actions, ...pages].slice(0, 12);
}

const GROUPS: Record<string, string> = { sites: "Sites", bills: "Bills", quotations: "Quotations", people: "People by role" };

export function CommandPalette({ can, onClose }: { can: Can; onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState<Hit[]>([]);
  const [at, setAt] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    setAt(0);
    if (q.trim().length < 2) {
      setRemote([]);
      return;
    }
    const t = window.setTimeout(() => {
      api<Record<string, { id: number | string; title: string; note?: string; to: string }[]>>(`/api/search?q=${encodeURIComponent(q.trim())}`).then(
        (r) => setRemote(Object.entries(r).flatMap(([k, rows]) => rows.map((x) => ({ id: `${k}${x.id}`, group: GROUPS[k] ?? k, title: x.title, note: x.note, to: x.to })))),
        () => setRemote([]),
      );
    }, 180);
    return () => window.clearTimeout(t);
  }, [q]);
  const hits = useMemo(() => [...localHits(q, can), ...remote], [q, can, remote]);
  const go = (h: Hit) => {
    onClose();
    navigate(h.to);
  };
  useEffect(() => {
    if (hits[at]) prefetch(hits[at].to);
  }, [hits, at]);

  let last = "";
  return (
    <div className="modal-backdrop palette-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search sites, bills, people, or type an action…"
            aria-label="Search"
            role="combobox"
            aria-expanded={hits.length > 0}
            aria-controls="palette-list"
            aria-activedescendant={hits[at] ? `ph-${hits[at].id}` : undefined}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setAt((i) => Math.min(hits.length - 1, i + 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setAt((i) => Math.max(0, i - 1));
              }
              if (e.key === "Enter" && hits[at]) go(hits[at]);
            }}
          />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" className="palette-list">
          {q.trim() === "" && <li className="palette-hint">Type a site, a bill number, a quotation, a role, or what you want to do.</li>}
          {q.trim() !== "" && hits.length === 0 && <li className="palette-hint">Nothing found for "{q}".</li>}
          {hits.map((h, i) => {
            const head = h.group !== last ? h.group : null;
            last = h.group;
            return (
              <li key={h.id} role="presentation">
                {head && <div className="palette-group">{head}</div>}
                <div id={`ph-${h.id}`} role="option" aria-selected={i === at} className="palette-hit" onMouseEnter={() => setAt(i)} onMouseDown={(e) => (e.preventDefault(), go(h))}>
                  <span>{h.title}</span>
                  {h.note && <span className="muted small">{h.note}</span>}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
