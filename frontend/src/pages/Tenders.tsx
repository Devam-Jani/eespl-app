import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText, inr } from "../format";
import type { Page, Tender, TenderLookups } from "../types";
import { Pager } from "./Clients";

export const TENDER_STATUSES: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted",
  won: "Won",
  lost: "Lost",
  dropped: "Dropped",
};
const STATUS_BADGE: Record<string, string> = {
  draft: "badge-muted",
  submitted: "badge-info",
  won: "badge-ok",
  lost: "badge-danger",
  dropped: "badge-warn",
};
const PAGE_SIZE = 25;

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? ""}`}>{TENDER_STATUSES[status] ?? status}</span>;
}

export function shortDate(value: string | null): string {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function Tenders() {
  const { can } = useAuth();
  const canEdit = can("tender.edit");
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", status: "", owner_id: "", client_id: "", channel_id: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Tender> | null>(null);
  const [lookups, setLookups] = useState<TenderLookups | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Tender>>(`/api/tenders${queryString({ ...filters, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (canEdit) api<TenderLookups>("/api/tenders/lookups").then(setLookups, () => setLookups(null));
  }, [canEdit]);

  const setFilter = (key: keyof typeof filters) => (e: { target: { value: string } }) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  };

  return (
    <>
      <div className="page-header">
        <h1>Tenders</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search code, name, client or site" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select value={filters.status} onChange={setFilter("status")}>
            <option value="">All statuses</option>
            {Object.entries(TENDER_STATUSES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          {lookups && (
            <>
              <select value={filters.client_id} onChange={setFilter("client_id")}>
                <option value="">All clients</option>
                {lookups.clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <select value={filters.channel_id} onChange={setFilter("channel_id")}>
                <option value="">All channels</option>
                {lookups.channels.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <select value={filters.owner_id} onChange={setFilter("owner_id")}>
                <option value="">All owners</option>
                {lookups.users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </>
          )}
          <ExportButton path={`/api/tenders/export${queryString(filters)}`} />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New tender
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Client</th>
              <th>Channel</th>
              <th>Due</th>
              <th>Owner</th>
              <th>Status</th>
              <th className="num">Quoted total</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((t) => (
              <tr key={t.id} className="clickable" onClick={() => navigate(`/tenders/${t.id}`)}>
                <td className="nowrap">
                  <code>{t.code}</code>
                </td>
                <td>
                  {t.name}
                  {t.site_city && <span className="muted small"> · {t.site_city}</span>}
                </td>
                <td>{t.client_name ?? "—"}</td>
                <td>{t.channel_name ?? "—"}</td>
                <td className={`nowrap ${t.overdue ? "text-danger" : ""}`} title={t.overdue ? "Overdue and not submitted" : undefined}>
                  {shortDate(t.due_on)}
                </td>
                <td>{t.owner_name ?? "—"}</td>
                <td>
                  <StatusBadge status={t.status} />
                </td>
                <td className="num">{inr(t.quoted_total)}</td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  No tenders found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}

      {creating && lookups && (
        <TenderForm
          lookups={lookups}
          tender={null}
          onClose={() => setCreating(false)}
          onSaved={(t) => navigate(`/tenders/${t.id}`)}
        />
      )}
    </>
  );
}

export function TenderForm({
  lookups,
  tender,
  onClose,
  onSaved,
}: {
  lookups: TenderLookups;
  tender: Tender | null;
  onClose: () => void;
  onSaved: (t: Tender) => void;
}) {
  const { me } = useAuth();
  const [form, setForm] = useState({
    name: tender?.name ?? "",
    client_id: tender?.client_id?.toString() ?? "",
    channel_id: tender?.channel_id?.toString() ?? "",
    site_name: tender?.site_name ?? "",
    site_city: tender?.site_city ?? "",
    site_state: tender?.site_state ?? "",
    received_on: tender?.received_on ?? new Date().toISOString().slice(0, 10),
    due_on: tender?.due_on ?? "",
    owner_id: tender?.owner_id ?? me?.user.id ?? "",
    tc_template_id: tender?.tc_template_id?.toString() ?? lookups.tc_templates.find((t) => t.is_default)?.id.toString() ?? "",
    notes: tender?.notes ?? "",
  });
  const [members, setMembers] = useState<string[]>(tender?.members.map((m) => m.user_id) ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.client_id && !form.channel_id) {
      setError("Choose the client, the channel, or both");
      return;
    }
    setBusy(true);
    const body: Record<string, unknown> = {
      name: form.name.trim(),
      client_id: form.client_id ? Number(form.client_id) : null,
      channel_id: form.channel_id ? Number(form.channel_id) : null,
      site_name: form.site_name || null,
      site_city: form.site_city || null,
      site_state: form.site_state || null,
      received_on: form.received_on || null,
      due_on: form.due_on || null,
      owner_id: form.owner_id || null,
      member_ids: members,
      notes: form.notes || null,
    };
    if (!tender) body.tc_template_id = form.tc_template_id ? Number(form.tc_template_id) : null;
    try {
      const saved = tender
        ? await api<Tender>(`/api/tenders/${tender.id}`, { method: "PATCH", json: body })
        : await api<Tender>("/api/tenders", { method: "POST", json: body });
      onSaved(saved);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={tender ? `Edit ${tender.code}` : "New tender"} onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Name *</span>
            <input required value={form.name} onChange={set("name")} autoFocus />
          </label>
          <label className="field">
            <span>Client (end client, e.g. Adani Realty)</span>
            <select value={form.client_id} onChange={set("client_id")}>
              <option value="">— not known yet —</option>
              {lookups.clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Channel (who brought it)</span>
            <select value={form.channel_id} onChange={set("channel_id")}>
              <option value="">— direct —</option>
              {lookups.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.type})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Site name</span>
            <input value={form.site_name} onChange={set("site_name")} />
          </label>
          <label className="field">
            <span>City</span>
            <input value={form.site_city} onChange={set("site_city")} />
          </label>
          <label className="field">
            <span>State</span>
            <input value={form.site_state} onChange={set("site_state")} />
          </label>
          <label className="field">
            <span>Owner</span>
            <select value={form.owner_id} onChange={set("owner_id")}>
              {lookups.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Received on</span>
            <input type="date" value={form.received_on} onChange={set("received_on")} />
          </label>
          <label className="field">
            <span>Due on</span>
            <input type="date" value={form.due_on} onChange={set("due_on")} />
          </label>
          {!tender && (
            <label className="field">
              <span>T&C template</span>
              <select value={form.tc_template_id} onChange={set("tc_template_id")}>
                <option value="">None</option>
                {lookups.tc_templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.is_default ? " (default)" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>Team members</span>
            <select
              multiple
              value={members}
              onChange={(e) => setMembers(Array.from(e.target.selectedOptions).map((o) => o.value))}
              size={4}
            >
              {lookups.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Notes</span>
          <textarea rows={3} value={form.notes} onChange={set("notes")} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {tender ? "Save" : "Create tender"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
