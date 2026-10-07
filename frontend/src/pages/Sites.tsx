import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { Page, Site, SiteLookups } from "../types";
import { Pager } from "./Clients";
import { shortDate } from "./Tenders";

export const SITE_STATUSES: Record<string, string> = {
  planned: "Planned",
  active: "Active",
  on_hold: "On hold",
  completed: "Completed",
  closed: "Closed",
};
const STATUS_BADGE: Record<string, string> = {
  planned: "badge-muted",
  active: "badge-info",
  on_hold: "badge-warn",
  completed: "badge-ok",
  closed: "badge-muted",
};
const PAGE_SIZE = 25;

export function SiteStatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? ""}`}>{SITE_STATUSES[status] ?? status}</span>;
}

export function ProgressBar({ value }: { value: string | number }) {
  const n = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <span className="progress" title={`${n.toFixed(1)}%`}>
      <span className="progress-fill" style={{ width: `${n}%` }} />
      <span className="progress-label">{n.toFixed(0)}%</span>
    </span>
  );
}

export default function Sites() {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", status: "", client_id: "", channel_id: "", incharge_id: "", source: "", late: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Site> | null>(null);
  const [lookups, setLookups] = useState<SiteLookups | null>(null);
  // margin % per site (only returned with tender.margin)
  const [margins, setMargins] = useState<Record<string, { margin_percent: string | null; over_cost: boolean }>>({});
  const showMargin = can("tender.margin") && can("billing.view");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Site>>(`/api/sites${queryString({ ...filters, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api<SiteLookups>("/api/sites/lookups").then(setLookups, () => setLookups(null));
  }, []);

  useEffect(() => {
    if (showMargin) api<typeof margins>("/api/finance/site-margins").then(setMargins, () => setMargins({}));
  }, [showMargin]);

  const setFilter = (key: keyof typeof filters) => (e: { target: { value: string } }) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  };

  return (
    <>
      <div className="page-header">
        <h1>Sites</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search code, name, client or city" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select value={filters.status} onChange={setFilter("status")}>
            <option value="">All statuses</option>
            {Object.entries(SITE_STATUSES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
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
              <select value={filters.incharge_id} onChange={setFilter("incharge_id")}>
                <option value="">Any in-charge</option>
                {lookups.users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </>
          )}
          <select value={filters.source} onChange={setFilter("source")}>
            <option value="">App + Powerplay</option>
            <option value="app">Made in the app</option>
            <option value="powerplay">Past (Powerplay)</option>
          </select>
          <label className="check">
            <input
              type="checkbox"
              checked={filters.late === "true"}
              onChange={(e) => {
                setOffset(0);
                setFilters((f) => ({ ...f, late: e.target.checked ? "true" : "" }));
              }}
            />{" "}
            Late
          </label>
          <ExportButton path={`/api/sites/export${queryString(filters)}`} />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New site
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
              <th>Status</th>
              <th>Progress</th>
              {showMargin && <th className="num">Margin %</th>}
              <th>In-charge</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => navigate(`/sites/${s.id}`)}>
                <td className="nowrap">
                  <code>{s.code}</code>
                </td>
                <td>
                  {s.name}
                  {s.city && <span className="muted small"> · {s.city}</span>}
                  {s.source === "powerplay" && <span className="badge badge-muted">Powerplay</span>}
                </td>
                <td>{s.client_name ?? "—"}</td>
                <td>{s.channel_name ?? "—"}</td>
                <td>
                  <SiteStatusBadge status={s.status} />
                </td>
                <td>
                  <ProgressBar value={s.progress_percent} />
                </td>
                {showMargin && (
                  <td className={`num ${margins[s.id]?.over_cost ? "text-danger" : ""}`} title={margins[s.id]?.over_cost ? "Cost to date is more than billed" : undefined}>
                    {margins[s.id]?.margin_percent != null ? `${margins[s.id].margin_percent}%` : "—"}
                    {margins[s.id]?.over_cost && " ⚠"}
                  </td>
                )}
                <td>{s.incharge_name ?? "—"}</td>
                <td className={`nowrap ${s.late ? "text-danger" : ""}`} title={s.late ? "Past the target date" : undefined}>
                  {shortDate(s.target_date)}
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={showMargin ? 9 : 8} className="empty">
                  No sites found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}
      {creating && lookups && (
        <SiteForm lookups={lookups} site={null} onClose={() => setCreating(false)} onSaved={(s) => navigate(`/sites/${s.id}`)} />
      )}
    </>
  );
}

export function SiteForm({
  lookups,
  site,
  onClose,
  onSaved,
}: {
  lookups: SiteLookups;
  site: Site | null;
  onClose: () => void;
  onSaved: (s: Site) => void;
}) {
  const [form, setForm] = useState({
    name: site?.name ?? "",
    client_id: site?.client_id?.toString() ?? "",
    channel_id: site?.channel_id?.toString() ?? "",
    address: site?.address ?? "",
    city: site?.city ?? "",
    state: site?.state ?? "",
    start_date: site?.start_date ?? "",
    target_date: site?.target_date ?? "",
    status: site?.status ?? "planned",
    site_incharge_id: site?.site_incharge_id ?? "",
    lat: site?.lat ?? "",
    lng: site?.lng ?? "",
    notes: site?.notes ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    for (const k of ["client_id", "channel_id"]) body[k] = body[k] ? Number(body[k]) : null;
    try {
      onSaved(
        site
          ? await api<Site>(`/api/sites/${site.id}`, { method: "PATCH", json: body })
          : await api<Site>("/api/sites", { method: "POST", json: body }),
      );
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={site ? `Edit ${site.code}` : "New site"} onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Name *</span>
            <input required value={form.name} onChange={set("name")} autoFocus />
          </label>
          <label className="field">
            <span>Status</span>
            <select value={form.status} onChange={set("status")}>
              {Object.entries(SITE_STATUSES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Client</span>
            <select value={form.client_id} onChange={set("client_id")}>
              <option value="">— unknown —</option>
              {lookups.clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Channel</span>
            <select value={form.channel_id} onChange={set("channel_id")}>
              <option value="">— direct —</option>
              {lookups.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Site in-charge</span>
            <select value={form.site_incharge_id} onChange={set("site_incharge_id")}>
              <option value="">—</option>
              {lookups.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>City</span>
            <input value={form.city} onChange={set("city")} />
          </label>
          <label className="field">
            <span>Start date</span>
            <input type="date" value={form.start_date} onChange={set("start_date")} />
          </label>
          <label className="field">
            <span>Target date</span>
            <input type="date" value={form.target_date} onChange={set("target_date")} />
          </label>
          <label className="field">
            <span>State</span>
            <input value={form.state} onChange={set("state")} />
          </label>
          <label className="field">
            <span>Latitude / longitude</span>
            <span className="inline-form">
              <input value={form.lat} onChange={set("lat")} placeholder="23.0225" />
              <input value={form.lng} onChange={set("lng")} placeholder="72.5714" />
            </span>
          </label>
        </div>
        <label className="field">
          <span>Address</span>
          <textarea rows={2} value={form.address} onChange={set("address")} />
        </label>
        <label className="field">
          <span>Notes</span>
          <textarea rows={2} value={form.notes} onChange={set("notes")} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">{site ? "Save" : "Create site"}</button>
        </div>
      </form>
    </Modal>
  );
}
