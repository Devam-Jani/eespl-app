import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText, inr } from "../format";
import type { Clause, Page, Tender, TenderLookups, TenderStatus, TenderTc } from "../types";
import BoqTab from "./tender/BoqTab";
import { shortDate, StatusBadge, TenderForm } from "./Tenders";

type Tab = "details" | "boq" | "terms";

export default function TenderDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const canEdit = can("tender.edit");
  const [tender, setTender] = useState<Tender | null>(null);
  const [tab, setTab] = useState<Tab>("boq");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTender(await api<Tender>(`/api/tenders/${id}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!tender) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  return (
    <>
      <p className="breadcrumb">
        <Link to="/tenders">Tenders</Link> / <code>{tender.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {tender.name} <StatusBadge status={tender.status} />
          </h1>
          <p className="muted">
            {tender.client_name}
            {tender.site_city ? ` · ${tender.site_city}` : ""} · due{" "}
            <span className={tender.overdue ? "text-danger" : ""}>{shortDate(tender.due_on)}</span>
          </p>
        </div>
        <div className="rate-badge">
          <span className="muted small">Quoted total (excl. GST)</span>
          <strong>{inr(tender.quoted_total)}</strong>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="tabs tabs-inline">
        {(
          [
            ["details", "Details"],
            ["boq", "BOQ"],
            ["terms", "Terms"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button key={key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      <div className="top-gap">
        {tab === "details" && <DetailsTab tender={tender} canEdit={canEdit} onChange={setTender} />}
        {tab === "boq" && <BoqTab tender={tender} canEdit={canEdit} onTotalChange={load} />}
        {tab === "terms" && <TermsTab tender={tender} canEdit={canEdit} />}
      </div>
    </>
  );
}

// --- details ---------------------------------------------------------------------------------------

function DetailsTab({ tender, canEdit, onChange }: { tender: Tender; canEdit: boolean; onChange: (t: Tender) => void }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState(false);
  const [lookups, setLookups] = useState<TenderLookups | null>(null);
  const [closing, setClosing] = useState<TenderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (canEdit) api<TenderLookups>("/api/tenders/lookups").then(setLookups, () => setLookups(null));
  }, [canEdit]);

  async function setStatus(status: TenderStatus, extra: Record<string, string | null> = {}) {
    setError(null);
    try {
      onChange(await api<Tender>(`/api/tenders/${tender.id}`, { method: "PATCH", json: { status, ...extra } }));
      setClosing(null);
    } catch (err) {
      setError(errorText(err));
    }
  }

  const rows: [string, string][] = [
    ["Code", tender.code],
    ["Client", tender.client_name],
    ["Site", [tender.site_name, tender.site_city, tender.site_state].filter(Boolean).join(", ") || "—"],
    ["Received on", shortDate(tender.received_on)],
    ["Due on", shortDate(tender.due_on)],
    ["Owner", tender.owner_name ?? "—"],
    ["Team", tender.members.map((m) => m.full_name).join(", ") || "—"],
    ["Quoted total", inr(tender.quoted_total)],
  ];
  if (tender.cost_total !== undefined) {
    rows.push(["Cost of system-priced lines", inr(tender.cost_total)], ["Margin on them", inr(tender.margin_amount)]);
  }
  if (tender.lost_reason || tender.lost_to) {
    rows.push(["Reason", tender.lost_reason ?? "—"], ["Competitor", tender.lost_to ?? "—"]);
  }
  rows.push(["Notes", tender.notes ?? "—"]);

  return (
    <div className="card">
      {error && <div className="alert alert-error">{error}</div>}
      <div className="toolbar">
        <h2 className="section-title">Tender details</h2>
        {canEdit && (
          <div className="page-actions">
            {tender.status === "draft" && (
              <button className="btn" onClick={() => void setStatus("submitted")}>
                Mark submitted
              </button>
            )}
            {(["won", "lost", "dropped"] as TenderStatus[]).map((s) => (
              <button key={s} className="btn" disabled={tender.status === s} onClick={() => setClosing(s)}>
                {s === "won" ? "Won" : s === "lost" ? "Lost" : "Dropped"}
              </button>
            ))}
            {tender.status !== "draft" && (
              <button className="btn btn-ghost" onClick={() => void setStatus("draft")}>
                Back to draft
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
      <dl className="detail-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="pre-line">{v}</dd>
          </div>
        ))}
      </dl>
      {can("tender.margin") || <p className="muted small">Cost and margin figures need the tender margin permission.</p>}
      {editing && lookups && (
        <TenderForm
          lookups={lookups}
          tender={tender}
          onClose={() => setEditing(false)}
          onSaved={(t) => {
            setEditing(false);
            onChange(t);
          }}
        />
      )}
      {closing && (
        <CloseTenderModal
          status={closing}
          tender={tender}
          onClose={() => setClosing(null)}
          onSave={(reason, competitor) => setStatus(closing, { lost_reason: reason, lost_to: competitor })}
        />
      )}
    </div>
  );
}

function CloseTenderModal({
  status,
  tender,
  onClose,
  onSave,
}: {
  status: TenderStatus;
  tender: Tender;
  onClose: () => void;
  onSave: (reason: string | null, competitor: string | null) => Promise<void>;
}) {
  const [reason, setReason] = useState(tender.lost_reason ?? "");
  const [competitor, setCompetitor] = useState(tender.lost_to ?? "");
  const label = status === "won" ? "Won" : status === "lost" ? "Lost" : "Dropped";
  const needsReason = status !== "won";

  function submit(e: FormEvent) {
    e.preventDefault();
    void onSave(reason.trim() || null, competitor.trim() || null);
  }

  return (
    <Modal title={`Mark ${tender.code} as ${label.toLowerCase()}`} onClose={onClose}>
      <form onSubmit={submit}>
        <label className="field">
          <span>Reason{needsReason ? " *" : ""}</span>
          <textarea
            rows={3}
            required={needsReason}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={status === "won" ? "Why we won (price, relationship, spec…)" : "Price, spec, timing…"}
            autoFocus
          />
        </label>
        <label className="field">
          <span>{status === "won" ? "Main competitor" : status === "lost" ? "Lost to (competitor)" : "Competitor (if known)"}</span>
          <input value={competitor} onChange={(e) => setCompetitor(e.target.value)} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Mark {label.toLowerCase()}</button>
        </div>
      </form>
    </Modal>
  );
}

// --- terms -----------------------------------------------------------------------------------------

type TermRow = { key: string; clause_id: number | null; library_text: string | null; text: string; category: string | null };

function toRows(items: TenderTc[]): TermRow[] {
  return items.map((t) => ({
    key: `t${t.id}`,
    clause_id: t.clause_id,
    library_text: t.clause_id && !t.text_override ? t.text : null, // null: edited, library text not at hand
    text: t.text,
    category: t.category,
  }));
}

function TermsTab({ tender, canEdit }: { tender: Tender; canEdit: boolean }) {
  const [rows, setRows] = useState<TermRow[]>([]);
  const [saved, setSaved] = useState<string>("[]");
  const [dragging, setDragging] = useState<number | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Clause[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const items = await api<TenderTc[]>(`/api/tenders/${tender.id}/tc`);
      const r = toRows(items);
      setRows(r);
      setSaved(JSON.stringify(r.map((x) => [x.clause_id, x.text])));
    } catch (err) {
      setError(errorText(err));
    }
  }, [tender.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = JSON.stringify(rows.map((x) => [x.clause_id, x.text])) !== saved;

  async function save() {
    setError(null);
    setNotice(null);
    try {
      const items = await api<TenderTc[]>(`/api/tenders/${tender.id}/tc`, {
        method: "PUT",
        json: {
          items: rows.map((r) => ({
            clause_id: r.clause_id,
            text_override: r.clause_id && r.library_text === r.text ? null : r.text,
          })),
        },
      });
      const r = toRows(items);
      setRows(r);
      setSaved(JSON.stringify(r.map((x) => [x.clause_id, x.text])));
      setNotice("Terms saved for this tender. The T&C library is unchanged.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function find(e: FormEvent) {
    e.preventDefault();
    try {
      const page = await api<Page<Clause>>(`/api/tc/clauses${queryString({ q: search, limit: 20 })}`);
      setResults(page.items);
    } catch (err) {
      setError(errorText(err));
    }
  }

  function move(from: number, to: number) {
    setRows((rs) => {
      const next = [...rs];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
  }

  const used = new Set(rows.map((r) => r.clause_id));

  return (
    <div className="split">
      <div className="card">
        <div className="toolbar">
          <h2 className="section-title">Terms & conditions ({rows.length})</h2>
          {canEdit && (
            <div className="page-actions">
              <button
                className="btn"
                onClick={() => {
                  const key = `n${Date.now()}`;
                  setRows((rs) => [...rs, { key, clause_id: null, library_text: null, text: "", category: null }]);
                  setEditing(key);
                }}
              >
                Add own clause
              </button>
              <button className="btn btn-primary" disabled={!dirty} onClick={() => void save()}>
                Save terms
              </button>
            </div>
          )}
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        {notice && <div className="alert alert-ok">{notice}</div>}
        {rows.length === 0 && <p className="empty">No terms yet. Add clauses from the library on the right.</p>}
        <ol className="clause-list numbered">
          {rows.map((r, i) => (
            <li
              key={r.key}
              draggable={canEdit && editing !== r.key}
              onDragStart={() => setDragging(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragging !== null && dragging !== i) move(dragging, i);
                setDragging(null);
              }}
              className={dragging === i ? "dragging" : ""}
            >
              <div className="clause-text">
                {canEdit && <span className="drag-handle" title="Drag to reorder">⋮⋮</span>}
                {editing === r.key ? (
                  <textarea
                    rows={3}
                    autoFocus
                    value={r.text}
                    onChange={(e) => setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, text: e.target.value } : x)))}
                    onBlur={() => setEditing(null)}
                  />
                ) : (
                  <span className="pre-line">{r.text || <em className="muted">(empty)</em>}</span>
                )}
                {r.category && <span className="badge badge-muted">{r.category}</span>}
                {r.clause_id && (r.library_text === null || r.text !== r.library_text) && (
                  <span className="badge badge-info">edited for this tender</span>
                )}
                {!r.clause_id && <span className="badge badge-orange">own text</span>}
              </div>
              {canEdit && (
                <div className="clause-actions">
                  <button className="btn btn-small btn-ghost" onClick={() => setEditing(r.key)}>
                    Edit
                  </button>
                  <button className="btn btn-small btn-ghost" disabled={i === 0} onClick={() => move(i, i - 1)} aria-label="Move up">
                    ↑
                  </button>
                  <button className="btn btn-small btn-ghost" disabled={i === rows.length - 1} onClick={() => move(i, i + 1)} aria-label="Move down">
                    ↓
                  </button>
                  <button className="btn btn-small btn-ghost" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                    Remove
                  </button>
                </div>
              )}
            </li>
          ))}
        </ol>
      </div>
      {canEdit && (
        <div className="card">
          <h2 className="section-title">Add from the library</h2>
          <form onSubmit={find} className="inline-form">
            <input className="search grow" placeholder="Search clauses" value={search} onChange={(e) => setSearch(e.target.value)} />
            <button className="btn">Search</button>
          </form>
          <ul className="plain-list top-gap">
            {results.map((c) => (
              <li key={c.id} className="pick">
                <span className="pre-line">{c.text}</span>
                <button
                  className="btn btn-small"
                  disabled={used.has(c.id)}
                  onClick={() =>
                    setRows((rs) => [...rs, { key: `c${c.id}`, clause_id: c.id, library_text: c.text, text: c.text, category: c.category }])
                  }
                >
                  {used.has(c.id) ? "Added" : "Add"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
