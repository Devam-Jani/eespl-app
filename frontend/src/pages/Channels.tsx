import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { Channel, ChannelType, Page } from "../types";
import { Pager } from "./Clients";

const TYPES: Record<ChannelType, string> = {
  salesperson: "Salesperson",
  partner: "Applicator partner",
  manufacturer: "Manufacturer route",
  other: "Other",
};
const PAGE_SIZE = 50;

/** Who brings tenders: the rate library's folders are channels, not end clients. */
export default function Channels() {
  const { can } = useAuth();
  const canEdit = can("clients.edit");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", type: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Channel> | null>(null);
  const [editing, setEditing] = useState<Channel | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Channel>>(`/api/channels${queryString({ ...filters, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Channels</h1>
          <p className="muted">Who brought a tender: a salesperson, an applicator partner or a manufacturer route. Not the end client.</p>
        </div>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search channels" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select
            value={filters.type}
            onChange={(e) => {
              setOffset(0);
              setFilters((f) => ({ ...f, type: e.target.value }));
            }}
          >
            <option value="">All types</option>
            {Object.entries(TYPES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <ExportButton path={`/api/channels/export${queryString(filters)}`} />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add channel
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th className="num">Rate library lines</th>
              <th className="num">Tenders</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((c) => (
              <tr key={c.id} className={`${canEdit ? "clickable" : ""} ${c.is_active ? "" : "row-muted"}`} onClick={() => canEdit && setEditing(c)}>
                <td>
                  {c.name}
                  {c.notes && <div className="muted small">{c.notes}</div>}
                </td>
                <td>{TYPES[c.type] ?? c.type}</td>
                <td className="num">{c.library_lines}</td>
                <td className="num">{c.tenders}</td>
                <td>
                  <span className={`badge ${c.is_active ? "badge-ok" : "badge-muted"}`}>{c.is_active ? "Active" : "Inactive"}</span>
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No channels found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}
      {editing && (
        <ChannelForm
          channel={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </>
  );
}

function ChannelForm({ channel, onClose, onSaved }: { channel: Channel | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: channel?.name ?? "",
    type: channel?.type ?? "other",
    notes: channel?.notes ?? "",
    is_active: channel?.is_active ?? true,
  });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = { ...form, notes: form.notes || null };
    try {
      if (channel) await api(`/api/channels/${channel.id}`, { method: "PATCH", json: body });
      else await api("/api/channels", { method: "POST", json: body });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!channel || !confirm(`Delete the channel "${channel.name}"?`)) return;
    try {
      await api(`/api/channels/${channel.id}`, { method: "DELETE" });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={channel ? `Edit ${channel.name}` : "New channel"} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Name *</span>
          <input required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} autoFocus />
        </label>
        <label className="field">
          <span>Type</span>
          <select value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as ChannelType }))}>
            {Object.entries(TYPES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Notes</span>
          <textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
        </label>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active
        </label>
        <div className="form-actions">
          {channel && (
            <button type="button" className="btn btn-danger push-left" onClick={() => void remove()}>
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
