import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

type Note = { id: number; kind: string; title: string; link: string | null; site_id: number | null; read: boolean; created_at: string };

const POLL_MS = 60_000;

/** The in-app notifications (both the staff app and the client portal). */
export default function Bell() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ unread: number; items: Note[] }>({ unread: 0, items: [] });
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(() => api<{ unread: number; items: Note[] }>("/api/notifications").then(setData, () => undefined), []);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  async function go(n: Note) {
    if (!n.read) await api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => undefined);
    setOpen(false);
    void load();
    if (n.link) navigate(n.link);
  }

  return (
    <div className="bell" ref={box}>
      <button className="btn btn-ghost bell-button" aria-label={`Notifications (${data.unread} unread)`} onClick={() => setOpen(!open)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {data.unread > 0 && <span className="bell-count">{data.unread > 99 ? "99+" : data.unread}</span>}
      </button>
      {open && (
        <div className="bell-panel">
          <div className="toolbar">
            <strong>Notifications</strong>
            {data.unread > 0 && (
              <button className="btn btn-small btn-ghost" onClick={() => void api("/api/notifications/read-all", { method: "POST" }).then(load)}>
                Mark all read
              </button>
            )}
          </div>
          {data.items.length === 0 && <p className="muted small">Nothing yet.</p>}
          {data.items.map((n) => (
            <button key={n.id} className={`bell-item ${n.read ? "" : "unread"}`} onClick={() => void go(n)}>
              <span>{n.title}</span>
              <span className="muted small">{new Date(n.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata",  day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
