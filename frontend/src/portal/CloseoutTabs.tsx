import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { errorText } from "../format";
import { day, usePortal } from "./Portal";

type Change = { id: number; field: string; old: string | null; new: string; remark: string | null; by: string; at: string; status: string; reply: string | null };
type Line = {
  id: number;
  description: string;
  place: string | null;
  length_m: string | null;
  breadth_m: string | null;
  perimeter_m: string | null;
  height_m: string | null;
  deductions_sqm: string | null;
  qty: string;
  unit: string;
  status: string;
  approved_name: string | null;
  approved_at: string | null;
  recorded_by_staff: boolean;
  changes: Change[];
};
const FIELD: Record<string, string> = {
  length_m: "Length (m)",
  breadth_m: "Breadth (m)",
  perimeter_m: "Perimeter (m)",
  height_m: "Height (m)",
  deductions_sqm: "Deductions (sqm)",
  qty: "Qty",
};

const n = (v: string | null) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 3 }));

/** The client's billing role: approve each measurement line, or correct a value with a remark. */
export function MeasurementsTab({ siteId }: { siteId: number }) {
  const { get, readOnly } = usePortal();
  const [rows, setRows] = useState<Line[] | null>(null);
  const [editing, setEditing] = useState<{ id: number; field: string; value: string; remark: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => get<Line[]>(`/api/portal/sites/${siteId}/measurements`).then(setRows, (e) => setError(errorText(e))), [get, siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  async function act(p: Promise<unknown>) {
    setError(null);
    try {
      await p;
      setEditing(null);
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!rows) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  if (!rows.length) return <p className="muted">No measurements sent to you yet.</p>;
  return (
    <div className="m-cards">
      {error && <div className="alert alert-error">{error}</div>}
      {rows.map((m) => {
        const pending = m.changes.some((c) => c.status === "pending");
        return (
          <div key={m.id} className="card m-card">
            <div className="m-head">
              <b>{m.place ?? "—"}</b>
              <span className={`badge ${m.status === "approved" ? "badge-ok" : pending ? "badge-warn" : "badge-info"}`}>
                {m.status === "approved" ? "approved" : pending ? "correction sent" : "to approve"}
              </span>
            </div>
            <div className="small muted">{m.description}</div>
            <div className="m-sizes">
              {(["length_m", "breadth_m", "perimeter_m", "height_m", "deductions_sqm"] as const)
                .filter((k) => m[k] !== null)
                .map((k) => (
                  <div key={k}>
                    <span className="muted small">{FIELD[k]}</span>
                    <div>{n(m[k])}</div>
                  </div>
                ))}
              <div>
                <span className="muted small">Qty</span>
                <div>
                  <b>
                    {n(m.qty)} {m.unit}
                  </b>
                </div>
              </div>
            </div>
            {m.changes.map((c) => (
              <div key={c.id} className="m-change small">
                {FIELD[c.field] ?? c.field}: <s>{n(c.old)}</s> → <b>{n(c.new)}</b> by {c.by},{" "}
                {new Date(c.at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                {c.remark && <div className="muted">“{c.remark}”</div>}
                <div>{c.status === "pending" ? "waiting for the applicator" : c.status === "accepted" ? "accepted by the applicator" : `disputed: ${c.reply ?? ""}`}</div>
              </div>
            ))}
            {m.status === "approved" && (
              <div className="small muted">
                Approved by {m.approved_name}
                {m.recorded_by_staff ? " (recorded by the applicator from the signed sheet)" : ""} {m.approved_at ? day(m.approved_at) : ""}
              </div>
            )}
            {m.status === "sent" && !readOnly && !pending && editing?.id !== m.id && (
              <div className="m-actions">
                <button className="btn btn-primary tap" onClick={() => void act(api(`/api/portal/sites/${siteId}/measurements/${m.id}/approve`, { method: "POST" }))}>
                  Approve
                </button>
                <button className="btn tap" onClick={() => setEditing({ id: m.id, field: m.length_m !== null ? "length_m" : "qty", value: "", remark: "" })}>
                  Correct
                </button>
              </div>
            )}
            {editing?.id === m.id && (
              <form
                className="m-edit"
                onSubmit={(e) => {
                  e.preventDefault();
                  void act(
                    api(`/api/portal/sites/${siteId}/measurements/${m.id}/correct`, {
                      method: "POST",
                      json: { field: editing.field, new_value: editing.value, remark: editing.remark || null },
                    }),
                  );
                }}
              >
                <select className="tap-input" value={editing.field} onChange={(e) => setEditing({ ...editing, field: e.target.value })} aria-label="Value to correct">
                  {Object.keys(FIELD)
                    .filter((k) => k === "qty" || m[k as keyof Line] !== null)
                    .map((k) => (
                      <option key={k} value={k}>
                        {FIELD[k]}
                      </option>
                    ))}
                </select>
                <input
                  className="tap-input"
                  inputMode="decimal"
                  placeholder="Correct value"
                  value={editing.value}
                  onChange={(e) => setEditing({ ...editing, value: e.target.value })}
                  required
                />
                <input className="tap-input" placeholder="Remark (what you measured)" value={editing.remark} onChange={(e) => setEditing({ ...editing, remark: e.target.value })} />
                <div className="m-actions">
                  <button className="btn btn-primary tap">Send the correction</button>
                  <button type="button" className="btn tap" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        );
      })}
    </div>
  );
}

type Place = {
  node_id: number;
  name: string;
  kind: string;
  parent_id: number | null;
  promised_on: string | null;
  promised_by: string | null;
  status: string | null;
  received_on: string | null;
};

/** The client's planning role: the date each place will be handed over. */
export function HandoverTab({ siteId, canEdit }: { siteId: number; canEdit: boolean }) {
  const { get, readOnly } = usePortal();
  const [rows, setRows] = useState<Place[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => get<Place[]>(`/api/portal/sites/${siteId}/handover`).then(setRows, (e) => setError(errorText(e))), [get, siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  async function promise(p: Place, value: string) {
    setError(null);
    try {
      await api(`/api/portal/sites/${siteId}/nodes/${p.node_id}/handover-promise`, { method: "PUT", json: { promised_on: value } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!rows) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <div className="table-wrap">
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table">
        <thead>
          <tr>
            <th>Place</th>
            <th>Handover promised</th>
            <th>Handed over</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.node_id}>
              <td>{p.name}</td>
              <td>
                {canEdit && !readOnly && p.status !== "received" ? (
                  <input type="date" defaultValue={p.promised_on ?? ""} onBlur={(e) => e.target.value && e.target.value !== p.promised_on && void promise(p, e.target.value)} />
                ) : (
                  day(p.promised_on)
                )}
                {p.promised_by && <div className="small muted">{p.promised_by}</div>}
              </td>
              <td>{p.status === "received" ? day(p.received_on) : <span className="muted">not yet</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Overdue = { id: number; code: string; invoice: string | null; invoice_date: string | null; outstanding: string; due_on: string; overdue_days: number; at: string };

/** The client's accounts and project manager: bills past their due date. */
export function OverdueList({ siteId }: { siteId: number }) {
  const { get } = usePortal();
  const [rows, setRows] = useState<Overdue[]>([]);
  useEffect(() => {
    get<Overdue[]>(`/api/portal/sites/${siteId}/overdue`).then(setRows, () => setRows([]));
  }, [get, siteId]);
  if (!rows.length) return null;
  return (
    <div className="card alert-warn top-gap">
      <h3 className="section-title">Overdue</h3>
      {rows.map((b) => (
        <div key={b.id}>
          <b>{b.code}</b> {b.invoice ? `(invoice ${b.invoice} of ${day(b.invoice_date)})` : ""}: ₹ {Number(b.outstanding).toLocaleString("en-IN")} was due on {day(b.due_on)},{" "}
          <b>{b.overdue_days} days overdue</b>. <span className="muted small">With you at: {b.at}</span>
        </div>
      ))}
    </div>
  );
}
