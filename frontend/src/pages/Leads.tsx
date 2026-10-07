import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText, inr } from "../format";
import type { KylasSync, Lead, LeadDetail, LeadDuplicate, LeadLookups, Page } from "../types";
import { Pager } from "./Clients";
import { shortDate } from "./Tenders";

export const LEAD_STATUSES: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  site_visit: "Site visit",
  quoted: "Quoted",
  won: "Won",
  lost: "Lost",
  junk: "Junk",
};
export const LEAD_SOURCES: Record<string, string> = {
  website: "Website",
  call: "Call",
  referral: "Referral",
  channel: "Channel",
  walk_in: "Walk-in",
  exhibition: "Exhibition",
  other: "Other",
};
const STATUS_BADGE: Record<string, string> = {
  new: "badge-info",
  contacted: "badge-muted",
  site_visit: "badge-muted",
  quoted: "badge-warn",
  won: "badge-ok",
  lost: "badge-danger",
  junk: "badge-danger",
};
const SYNC: Record<KylasSync, [string, string]> = {
  disabled: ["badge-muted", "Kylas off"],
  pending: ["badge-warn", "Kylas pending"],
  synced: ["badge-ok", "In Kylas"],
  failed: ["badge-danger", "Kylas failed"],
};
const PAGE_SIZE = 50;

export function LeadStatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? ""}`}>{LEAD_STATUSES[status] ?? status}</span>;
}

export function KylasBadge({ status }: { status: KylasSync }) {
  return <span className={`badge ${SYNC[status][0]}`}>{SYNC[status][1]}</span>;
}

export default function Leads() {
  const { can } = useAuth();
  const canEdit = can("leads.edit");
  const navigate = useNavigate();
  const [view, setView] = useState<"list" | "kanban">("list");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", status: "", owner_id: "", lead_source: "", follow_up_due: "", kylas_sync_status: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Lead> | null>(null);
  const [lookups, setLookups] = useState<LeadLookups | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const limit = view === "kanban" ? 300 : PAGE_SIZE;
      setPage(await api<Page<Lead>>(`/api/leads${queryString({ ...filters, limit, offset: view === "kanban" ? 0 : offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset, view]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api<LeadLookups>("/api/leads/lookups").then(setLookups, () => setLookups(null));
  }, []);

  const setFilter = (key: keyof typeof filters) => (e: { target: { value: string } }) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  };

  async function move(lead: Lead, status: string) {
    try {
      await api(`/api/leads/${lead.id}`, { method: "PATCH", json: { status } });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Leads</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search code, name, company, phone, city" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select value={filters.status} onChange={setFilter("status")}>
            <option value="">All statuses</option>
            {Object.entries(LEAD_STATUSES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <select value={filters.lead_source} onChange={setFilter("lead_source")}>
            <option value="">All sources</option>
            {Object.entries(LEAD_SOURCES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          {lookups && (
            <select value={filters.owner_id} onChange={setFilter("owner_id")}>
              <option value="">All owners</option>
              {lookups.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          )}
          <select value={filters.kylas_sync_status} onChange={setFilter("kylas_sync_status")}>
            <option value="">Any Kylas status</option>
            {Object.entries(SYNC).map(([v, [, l]]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <label className="check">
            <input
              type="checkbox"
              checked={filters.follow_up_due === "true"}
              onChange={(e) => setFilters((f) => ({ ...f, follow_up_due: e.target.checked ? "true" : "" }))}
            />{" "}
            Follow-up due
          </label>
          <div className="tabs">
            <button className={`tab ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
              List
            </button>
            <button className={`tab ${view === "kanban" ? "active" : ""}`} onClick={() => setView("kanban")}>
              Kanban
            </button>
          </div>
          <ExportButton path={`/api/leads/export${queryString(filters)}`} />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New lead
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {view === "list" ? (
        <>
          <div className="card table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Contact</th>
                  <th>Company / city</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Follow-up</th>
                  <th>Kylas</th>
                </tr>
              </thead>
              <tbody>
                {page?.items.map((l) => (
                  <tr key={l.id} className="clickable" onClick={() => navigate(`/leads/${l.id}`)}>
                    <td className="nowrap">
                      <code>{l.code}</code>
                    </td>
                    <td>
                      {l.contact_name}
                      <div className="muted small">{l.phone ?? ""}</div>
                    </td>
                    <td>
                      {l.company ?? "—"}
                      {l.city && <span className="muted small"> · {l.city}</span>}
                    </td>
                    <td>{LEAD_SOURCES[l.lead_source] ?? l.lead_source}</td>
                    <td>
                      <LeadStatusBadge status={l.status} />
                    </td>
                    <td>{l.owner_name ?? "—"}</td>
                    <td className={`nowrap ${l.follow_up_due ? "text-danger" : ""}`}>{shortDate(l.next_follow_up)}</td>
                    <td>
                      <KylasBadge status={l.kylas_sync_status} />
                    </td>
                  </tr>
                ))}
                {page?.items.length === 0 && (
                  <tr>
                    <td colSpan={8} className="empty">
                      No leads found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {page && <Pager page={page} onOffset={setOffset} />}
        </>
      ) : (
        <div className="kanban">
          {Object.entries(LEAD_STATUSES).map(([status, label]) => {
            const cards = page?.items.filter((l) => l.status === status) ?? [];
            return (
              <div
                key={status}
                className="kanban-col"
                onDragOver={(e) => canEdit && e.preventDefault()}
                onDrop={(e) => {
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  const lead = page?.items.find((l) => l.id === id);
                  if (lead && lead.status !== status) void move(lead, status);
                }}
              >
                <div className="kanban-head">
                  {label} <span className="muted">({cards.length})</span>
                </div>
                {cards.map((l) => (
                  <div
                    key={l.id}
                    className="kanban-card clickable"
                    draggable={canEdit}
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", String(l.id))}
                    onClick={() => navigate(`/leads/${l.id}`)}
                  >
                    <strong>{l.contact_name}</strong>
                    <div className="muted small">
                      {l.company ?? ""} {l.city ? `· ${l.city}` : ""}
                    </div>
                    <div className="small">
                      {l.est_value ? inr(l.est_value) : ""} {l.follow_up_due && <span className="badge badge-danger">follow-up due</span>}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
      {creating && lookups && (
        <LeadForm lookups={lookups} lead={null} onClose={() => setCreating(false)} onSaved={(l) => navigate(`/leads/${l.id}`)} />
      )}
    </>
  );
}

export function LeadForm({
  lookups,
  lead,
  onClose,
  onSaved,
}: {
  lookups: LeadLookups;
  lead: Lead | null;
  onClose: () => void;
  onSaved: (l: LeadDetail) => void;
}) {
  const [form, setForm] = useState({
    contact_name: lead?.contact_name ?? "",
    phone: lead?.phone ?? "",
    email: lead?.email ?? "",
    company: lead?.company ?? "",
    city: lead?.city ?? "",
    state: lead?.state ?? "",
    lead_source: lead?.lead_source ?? "call",
    channel_id: lead?.channel_id?.toString() ?? "",
    client_id: lead?.client_id?.toString() ?? "",
    requirement: lead?.requirement ?? "",
    system_id: lead?.system_id?.toString() ?? "",
    work_category_id: lead?.work_category_id?.toString() ?? "",
    est_area_sqm: lead?.est_area_sqm ?? "",
    est_value: lead?.est_value ?? "",
    owner_id: lead?.owner_id ?? "",
    next_follow_up: lead?.next_follow_up ?? "",
  });
  const [dupes, setDupes] = useState<LeadDuplicate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function checkPhone() {
    if (!form.phone.trim()) return setDupes([]);
    try {
      const found = await api<LeadDuplicate[]>(`/api/leads/check-phone${queryString({ phone: form.phone })}`);
      setDupes(found.filter((d) => d.id !== lead?.id));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    for (const k of ["channel_id", "client_id", "system_id", "work_category_id"]) body[k] = body[k] ? Number(body[k]) : null;
    try {
      onSaved(lead ? await api<LeadDetail>(`/api/leads/${lead.id}`, { method: "PATCH", json: body }) : await api<LeadDetail>("/api/leads", { method: "POST", json: body }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const select = (key: keyof typeof form, items: { id: number | string; name?: string; full_name?: string }[], empty: string) => (
    <select value={form[key]} onChange={set(key)}>
      <option value="">{empty}</option>
      {items.map((x) => (
        <option key={x.id} value={x.id}>
          {x.name ?? x.full_name}
        </option>
      ))}
    </select>
  );

  return (
    <Modal title={lead ? `Edit ${lead.code}` : "New lead"} onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        {lead && lead.kylas_sync_status === "synced" && <div className="alert alert-warn">Edits stay in EESPL: they are not sent to Kylas in this version.</div>}
        <div className="grid-2">
          <label className="field">
            <span>Contact name *</span>
            <input required autoFocus value={form.contact_name} onChange={set("contact_name")} />
          </label>
          <label className="field">
            <span>Phone (mobile)</span>
            <input value={form.phone} onChange={set("phone")} onBlur={() => void checkPhone()} placeholder="98765 43210" />
          </label>
          {dupes.length > 0 && (
            <div className="alert alert-warn" style={{ gridColumn: "1 / -1" }}>
              This phone is already on {dupes.map((d) => `${d.code} (${d.contact_name}, ${LEAD_STATUSES[d.status] ?? d.status})`).join(", ")}. You can still save.
            </div>
          )}
          <label className="field">
            <span>Email</span>
            <input type="email" value={form.email} onChange={set("email")} />
          </label>
          <label className="field">
            <span>Company</span>
            <input value={form.company} onChange={set("company")} />
          </label>
          <label className="field">
            <span>City</span>
            <input value={form.city} onChange={set("city")} />
          </label>
          <label className="field">
            <span>State</span>
            <input value={form.state} onChange={set("state")} />
          </label>
          <label className="field">
            <span>Source</span>
            <select value={form.lead_source} onChange={set("lead_source")}>
              {Object.entries(LEAD_SOURCES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Channel (who brought it)</span>
            {select("channel_id", lookups.channels, "— direct —")}
          </label>
          <label className="field">
            <span>Client (if known)</span>
            {select("client_id", lookups.clients, "—")}
          </label>
          <label className="field">
            <span>Owner</span>
            {select("owner_id", lookups.users, "Me")}
          </label>
          <label className="field">
            <span>Interest: system</span>
            {select("system_id", lookups.systems, "—")}
          </label>
          <label className="field">
            <span>Interest: work category</span>
            {select("work_category_id", lookups.work_categories, "—")}
          </label>
          <label className="field">
            <span>Est. area (sqm)</span>
            <input value={form.est_area_sqm} onChange={set("est_area_sqm")} />
          </label>
          <label className="field">
            <span>Est. value (₹)</span>
            <input value={form.est_value} onChange={set("est_value")} />
          </label>
          <label className="field">
            <span>Next follow-up</span>
            <input type="date" value={form.next_follow_up} onChange={set("next_follow_up")} />
          </label>
        </div>
        <label className="field">
          <span>Requirement</span>
          <textarea rows={3} value={form.requirement} onChange={set("requirement")} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">{lead ? "Save" : "Create lead"}</button>
        </div>
      </form>
    </Modal>
  );
}
