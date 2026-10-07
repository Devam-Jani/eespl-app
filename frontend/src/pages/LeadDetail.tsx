import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, inr } from "../format";
import type { LeadDetail as Detail, LeadLookups } from "../types";
import { KylasBadge, LEAD_SOURCES, LEAD_STATUSES, LeadForm, LeadStatusBadge } from "./Leads";
import { shortDate } from "./Tenders";

const ACTIVITY_ICON: Record<string, string> = { note: "✎", call: "☎", visit: "⌂", status_change: "→", kylas: "K" };

export default function LeadDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const canEdit = can("leads.edit");
  const [lead, setLead] = useState<Detail | null>(null);
  const [lookups, setLookups] = useState<LeadLookups | null>(null);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState({ type: "note", text: "" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLead(await api<Detail>(`/api/leads/${id}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
    api<LeadLookups>("/api/leads/lookups").then(setLookups, () => setLookups(null));
  }, [load]);

  async function run(p: Promise<Detail>) {
    setError(null);
    try {
      setLead(await p);
    } catch (err) {
      setError(errorText(err));
    }
  }

  function addNote(e: FormEvent) {
    e.preventDefault();
    if (!lead || !note.text.trim()) return;
    void run(api<Detail>(`/api/leads/${lead.id}/activities`, { method: "POST", json: note })).then(() => setNote({ type: "note", text: "" }));
  }

  if (!lead) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  const rows: [string, string][] = [
    ["Phone", lead.phone ?? "—"],
    ["Email", lead.email ?? "—"],
    ["Company", lead.company ?? "—"],
    ["City / state", [lead.city, lead.state].filter(Boolean).join(", ") || "—"],
    ["Source", LEAD_SOURCES[lead.lead_source] ?? lead.lead_source],
    ["Channel", lead.channel_name ?? "—"],
    ["Client", lead.client_name ?? "—"],
    ["Owner", lead.owner_name ?? "—"],
    ["Entered by", lead.created_by_name ?? "—"],
    ["Est. area", lead.est_area_sqm ? `${lead.est_area_sqm} sqm` : "—"],
    ["Est. value", lead.est_value ? inr(lead.est_value) : "—"],
    ["Next follow-up", shortDate(lead.next_follow_up)],
    ["Requirement", lead.requirement ?? "—"],
  ];

  return (
    <>
      <p className="breadcrumb">
        <Link to="/leads">Leads</Link> / <code>{lead.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {lead.contact_name} <LeadStatusBadge status={lead.status} /> <KylasBadge status={lead.kylas_sync_status} phone={lead.phone} />
          </h1>
          <p className="muted">
            {lead.company ?? ""} {lead.city ? `· ${lead.city}` : ""}
            {lead.tender_code && (
              <>
                {" · tender "}
                <Link to={`/tenders/${lead.tender_id}`}>{lead.tender_code}</Link>
              </>
            )}
          </p>
        </div>
        {canEdit && (
          <div className="page-actions">
            <select value={lead.status} onChange={(e) => void run(api<Detail>(`/api/leads/${lead.id}`, { method: "PATCH", json: { status: e.target.value } }))}>
              {Object.entries(LEAD_STATUSES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            {!lead.tender_id && can("tender.edit") && (
              <button className="btn" onClick={() => confirm("Create a tender from this lead?") && void run(api<Detail>(`/api/leads/${lead.id}/convert`, { method: "POST" }))}>
                Convert to tender
              </button>
            )}
            {lookups && (
              <button className="btn btn-primary" onClick={() => setEditing(true)}>
                Edit
              </button>
            )}
          </div>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {lead.duplicates.length > 0 && (
        <div className="alert alert-warn">
          Same phone as{" "}
          {lead.duplicates.map((d, i) => (
            <span key={d.id}>
              {i > 0 && ", "}
              <Link to={`/leads/${d.id}`}>{d.code}</Link> ({d.contact_name})
            </span>
          ))}
          .
        </div>
      )}
      <div className="split">
        <div className="card">
          <dl className="detail-list">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd className="pre-line">{v}</dd>
              </div>
            ))}
          </dl>
          <h2 className="section-title top-gap">Kylas</h2>
          <p className="small">
            <KylasBadge status={lead.kylas_sync_status} phone={lead.phone} />
            {lead.kylas_lead_id && <> Kylas lead {lead.kylas_lead_id}</>}
            {lead.kylas_forecasting && <> · {lead.kylas_forecasting}</>}
            {lead.kylas_synced_at && <> · sent {new Date(lead.kylas_synced_at).toLocaleString("en-IN")}</>}
          </p>
          {lead.kylas_last_error && <p className="small text-danger">{lead.kylas_last_error}</p>}
          {canEdit && !lead.kylas_lead_id && lead.phone && (lead.kylas_sync_status === "failed" || lead.kylas_sync_status === "disabled") && (
            <button className="btn btn-small" onClick={() => void run(api<Detail>(`/api/leads/${lead.id}/kylas/retry`, { method: "POST" }))}>
              Retry
            </button>
          )}
          <p className="muted small">The lead is created in Kylas once. Later edits stay in EESPL; Kylas outcomes (lost, junk, won) come back every few minutes.</p>
        </div>
        <div className="card">
          <h2 className="section-title">Activity</h2>
          {canEdit && (
            <form onSubmit={addNote} className="inline-form">
              <select value={note.type} onChange={(e) => setNote((n) => ({ ...n, type: e.target.value }))}>
                <option value="note">Note</option>
                <option value="call">Call</option>
                <option value="visit">Visit</option>
              </select>
              <input className="grow" value={note.text} onChange={(e) => setNote((n) => ({ ...n, text: e.target.value }))} placeholder="What happened?" />
              <button className="btn btn-primary">Add</button>
            </form>
          )}
          <ul className="timeline">
            {lead.activities.map((a) => (
              <li key={a.id} className={`timeline-${a.type}`}>
                <span className="timeline-icon">{ACTIVITY_ICON[a.type] ?? "•"}</span>
                <div>
                  <div className="pre-line">{a.text}</div>
                  <div className="muted small">
                    {new Date(a.at).toLocaleString("en-IN")} {a.by_name ? `· ${a.by_name}` : a.type === "kylas" ? "· Kylas" : ""}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {editing && lookups && (
        <LeadForm
          lookups={lookups}
          lead={lead}
          onClose={() => setEditing(false)}
          onSaved={(l) => {
            setEditing(false);
            setLead(l);
          }}
        />
      )}
    </>
  );
}
