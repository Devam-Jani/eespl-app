import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText } from "../../format";
import type { MomOut, MomPoint } from "../../execution/types";
import type { Site, SiteLookups } from "../../types";
import { shortDate } from "../Tenders";
import { localToday } from "./DprTab";

export default function MomTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const [moms, setMoms] = useState<MomOut[]>([]);
  const [editing, setEditing] = useState<MomOut | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canEdit = can("inspection.edit");

  const load = useCallback(() => api<MomOut[]>(`/api/execution/moms?site_id=${site.id}`).then(setMoms, (err) => setError(errorText(err))), [site.id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function setStatus(p: MomPoint, status: string) {
    try {
      await api(`/api/execution/mom-points/${p.id}`, { method: "PATCH", json: { status } });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {canEdit && (
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          New minutes of meeting
        </button>
      )}
      {moms.map((m) => (
        <div key={m.id} className="card top-gap">
          <div className="toolbar">
            <div>
              <b>{m.title}</b> <code className="small">{m.code}</code>
              <div className="small muted">
                {shortDate(m.on_date)} · {m.venue ?? "Site"} · {m.attendees.join(", ")}
              </div>
            </div>
            <div className="page-actions">
              <button className="btn btn-small" onClick={() => void downloadFile(`/api/execution/moms/${m.id}/pdf`).catch((err) => setError(errorText(err)))}>
                PDF
              </button>
              {canEdit && (
                <button className="btn btn-small" onClick={() => setEditing(m)}>
                  Edit
                </button>
              )}
            </div>
          </div>
          {m.notes && <p className="pre-line small">{m.notes}</p>}
          <ul className="plain-list">
            {m.points.map((p) => (
              <li key={p.id} className="point-row">
                <span className={`badge ${p.status === "open" ? (p.overdue ? "badge-danger" : "badge-warn") : "badge-ok"}`}>{p.status}</span> {p.text}{" "}
                <span className="small muted">
                  {p.owner ?? ""} {p.due_date ? `· due ${shortDate(p.due_date)}` : ""}
                </span>
                {canEdit && p.status === "open" && (
                  <button className="btn btn-small push-right" onClick={() => void setStatus(p, "done")}>
                    Done
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {moms.length === 0 && <p className="muted top-gap">No meetings recorded.</p>}
      {editing && <MomForm site={site} mom={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={async () => (setEditing(null), await load())} />}
    </>
  );
}

type P = { id?: number; text: string; owner_user_id: string; owner_name: string; due_date: string; status: string };

function MomForm({ site, mom, onClose, onSaved }: { site: Site; mom?: MomOut; onClose: () => void; onSaved: () => void }) {
  const [users, setUsers] = useState<SiteLookups["users"]>([]);
  const [form, setForm] = useState({
    on_date: mom?.on_date ?? localToday(),
    title: mom?.title ?? "",
    venue: mom?.venue ?? "",
    notes: mom?.notes ?? "",
    others: mom?.attendee_others.join(", ") ?? "",
  });
  const [attendees, setAttendees] = useState<string[]>(mom?.attendee_user_ids ?? []);
  const [points, setPoints] = useState<P[]>(
    mom?.points.map((p) => ({ id: p.id, text: p.text, owner_user_id: p.owner_user_id ?? "", owner_name: p.owner_name ?? "", due_date: p.due_date ?? "", status: p.status })) ?? [
      { text: "", owner_user_id: "", owner_name: "", due_date: "", status: "open" },
    ],
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<SiteLookups>("/api/sites/lookups").then(
      (l) => setUsers(l.users),
      () => setUsers([]),
    );
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const json = {
      site_id: site.id,
      on_date: form.on_date,
      title: form.title,
      venue: form.venue || null,
      notes: form.notes || null,
      attendee_user_ids: attendees,
      attendee_others: form.others
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      points: points.filter((p) => p.text.trim()).map((p) => ({ ...p, owner_user_id: p.owner_user_id || null, owner_name: p.owner_name || null, due_date: p.due_date || null })),
    };
    try {
      await api(mom ? `/api/execution/moms/${mom.id}` : "/api/execution/moms", { method: mom ? "PUT" : "POST", json });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const setPoint = (i: number, patch: Partial<P>) => setPoints((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <Modal title={mom ? `Edit ${mom.code}` : "Minutes of meeting"} onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Subject *</span>
            <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </label>
          <label className="field">
            <span>Date</span>
            <input type="date" value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Venue</span>
            <input value={form.venue} onChange={(e) => setForm({ ...form, venue: e.target.value })} placeholder="Site office" />
          </label>
          <label className="field">
            <span>Client / others present (comma separated)</span>
            <input value={form.others} onChange={(e) => setForm({ ...form, others: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <span>EESPL attendees</span>
          <div className="pick-list">
            {users.map((u) => (
              <label key={u.id} className="check">
                <input type="checkbox" checked={attendees.includes(u.id)} onChange={() => setAttendees((a) => (a.includes(u.id) ? a.filter((x) => x !== u.id) : [...a, u.id]))} />{" "}
                {u.full_name}
              </label>
            ))}
          </div>
        </div>
        <label className="field">
          <span>Discussion</span>
          <textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
        <h2 className="section-title">Action points</h2>
        <div className="line-cards">
          {points.map((p, i) => (
            <div key={i} className="line-card">
              <label className="field">
                <span>Point</span>
                <input value={p.text} onChange={(e) => setPoint(i, { text: e.target.value })} />
              </label>
              <div className="line-row">
                <label className="field">
                  <span>Owner (EESPL)</span>
                  <select value={p.owner_user_id} onChange={(e) => setPoint(i, { owner_user_id: e.target.value })}>
                    <option value="">—</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>or outside</span>
                  <input value={p.owner_name} onChange={(e) => setPoint(i, { owner_name: e.target.value })} placeholder="Client" />
                </label>
                <label className="field">
                  <span>Due</span>
                  <input type="date" value={p.due_date} onChange={(e) => setPoint(i, { due_date: e.target.value })} />
                </label>
              </div>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="btn btn-small top-gap"
          onClick={() => setPoints((ps) => [...ps, { text: "", owner_user_id: "", owner_name: "", due_date: "", status: "open" }])}
        >
          + Point
        </button>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
