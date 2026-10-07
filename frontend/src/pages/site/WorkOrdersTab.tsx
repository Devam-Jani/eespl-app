import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { Subcontractor, WorkOrder, WoLine } from "../../execution/types";
import type { Site } from "../../types";
import { shortDate } from "../Tenders";
import { localToday } from "./DprTab";

const STATUS_BADGE: Record<string, string> = { draft: "badge-muted", approved: "badge-info", active: "badge-warn", completed: "badge-ok", closed: "badge-muted" };
const M_BADGE: Record<string, string> = { recorded: "badge-info", pending_approval: "badge-warn", verified: "badge-ok", rejected: "badge-danger" };

export function WoStatus({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? "badge-muted"}`}>{status}</span>;
}

export default function WorkOrdersTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const [wos, setWos] = useState<WorkOrder[]>([]);
  const [open, setOpen] = useState<WorkOrder | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await api<WorkOrder[]>(`/api/execution/work-orders?site_id=${site.id}`);
      setWos(list);
      setOpen((o) => (o ? (list.find((w) => w.id === o.id) ?? null) : null));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {can("subcon.edit") && (
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New work order
        </button>
      )}
      <div className="card table-wrap top-gap">
        <table className="table">
          <thead>
            <tr>
              <th>WO</th>
              <th>Subcontractor</th>
              <th className="num">Value</th>
              <th className="num">Billable to date</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {wos.map((w) => (
              <tr key={w.id} className="clickable" onClick={() => setOpen(w)}>
                <td>
                  <code>{w.code}</code>
                </td>
                <td>{w.subcontractor_name}</td>
                <td className="num">{inr(w.amount)}</td>
                <td className="num">{inr(w.billable_to_date)}</td>
                <td>
                  <WoStatus status={w.status} />
                  {w.lines.some((l) => l.measurements.some((m) => m.status === "pending_approval")) && <span className="badge badge-warn">over-measure</span>}
                </td>
              </tr>
            ))}
            {wos.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No work orders.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {creating && <WoForm site={site} onClose={() => setCreating(false)} onSaved={async (w) => (setCreating(false), await load(), setOpen(w))} />}
      {open && <WoView wo={open} site={site} onClose={() => setOpen(null)} onChange={async () => await load()} />}
    </>
  );
}

type LineForm = { id?: number; description: string; unit: string; qty: string; rate: string };

function WoForm({ site, wo, onClose, onSaved }: { site: Site; wo?: WorkOrder; onClose: () => void; onSaved: (w: WorkOrder) => void }) {
  const [subs, setSubs] = useState<Subcontractor[]>([]);
  const [templates, setTemplates] = useState<{ id: number; name: string }[]>([]);
  const [form, setForm] = useState({
    subcontractor_id: wo?.subcontractor_id ?? ("" as number | ""),
    material_by: wo?.material_by ?? "eespl",
    retention_percent: wo?.retention_percent ?? "5",
    tds_percent: wo?.tds_percent ?? "",
    start_date: wo?.start_date ?? "",
    end_date: wo?.end_date ?? "",
    tc_template_id: wo?.tc_template_id ?? ("" as number | ""),
    remark: wo?.remark ?? "",
  });
  const [lines, setLines] = useState<LineForm[]>(
    wo?.lines.map((l) => ({ id: l.id, description: l.description, unit: l.unit, qty: l.qty, rate: l.rate })) ?? [{ description: "", unit: "sqm", qty: "", rate: "" }],
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Subcontractor[]>("/api/execution/subcontractors").then(setSubs, () => setSubs([]));
    api<{ tc_templates: { id: number; name: string }[] }>("/api/material/lookups").then(
      (l) => setTemplates(l.tc_templates),
      () => setTemplates([]),
    );
  }, []);

  const sub = subs.find((s) => s.id === form.subcontractor_id);
  const total = lines.reduce((s, l) => s + Number(l.qty || 0) * Number(l.rate || 0), 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const json = {
      ...form,
      site_id: site.id,
      tds_percent: form.tds_percent || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      tc_template_id: form.tc_template_id || null,
      remark: form.remark || null,
      lines,
    };
    try {
      onSaved(await api<WorkOrder>(wo ? `/api/execution/work-orders/${wo.id}` : "/api/execution/work-orders", { method: wo ? "PUT" : "POST", json }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const setLine = (i: number, patch: Partial<LineForm>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <Modal title={wo ? `Edit ${wo.code}` : "New work order"} onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Subcontractor *</span>
            <select required value={form.subcontractor_id} onChange={(e) => setForm({ ...form, subcontractor_id: Number(e.target.value) || "" })}>
              <option value="">—</option>
              {subs.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {sub && (
              <small className="muted">
                PAN {sub.pan ?? "—"} · GSTIN {sub.gstin ?? "—"} · bank {sub.bank ?? "—"} · default TDS {num(sub.tds_percent)}%
              </small>
            )}
          </label>
          <label className="field">
            <span>Material by</span>
            <select value={form.material_by} onChange={(e) => setForm({ ...form, material_by: e.target.value as "eespl" | "subcontractor" })}>
              <option value="eespl">EESPL</option>
              <option value="subcontractor">Subcontractor</option>
            </select>
          </label>
          <label className="field">
            <span>Retention %</span>
            <input inputMode="decimal" value={form.retention_percent} onChange={(e) => setForm({ ...form, retention_percent: e.target.value })} />
          </label>
          <label className="field">
            <span>TDS % (blank: by PAN type)</span>
            <input inputMode="decimal" value={form.tds_percent} onChange={(e) => setForm({ ...form, tds_percent: e.target.value })} />
          </label>
          <label className="field">
            <span>Start</span>
            <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </label>
          <label className="field">
            <span>End</span>
            <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Terms (T&amp;C template)</span>
            <select value={form.tc_template_id} onChange={(e) => setForm({ ...form, tc_template_id: Number(e.target.value) || "" })}>
              <option value="">Built-in work order terms</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Remark</span>
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </label>
        </div>
        <h2 className="section-title">Scope</h2>
        <div className="line-cards">
          {lines.map((l, i) => (
            <div key={i} className="line-card">
              <label className="field">
                <span>Description</span>
                <input required value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} />
              </label>
              <div className="line-row">
                <label className="field">
                  <span>Unit</span>
                  <input required value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} />
                </label>
                <label className="field">
                  <span>Qty</span>
                  <input required inputMode="decimal" value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} />
                </label>
                <label className="field">
                  <span>Rate</span>
                  <input required inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} />
                </label>
                <div className="field">
                  <span>Amount</span>
                  <b className="accepted">{inr(Number(l.qty || 0) * Number(l.rate || 0))}</b>
                </div>
                <button type="button" className="btn btn-ghost btn-icon" aria-label="Remove line" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="btn btn-small top-gap" onClick={() => setLines((ls) => [...ls, { description: "", unit: "sqm", qty: "", rate: "" }])}>
          + Line
        </button>
        <p className="right">
          Work order value <b>{inr(total)}</b> · retention {inr((total * Number(form.retention_percent || 0)) / 100)}
        </p>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save draft</button>
        </div>
      </form>
    </Modal>
  );
}

function WoView({ wo, site, onClose, onChange }: { wo: WorkOrder; site: Site; onClose: () => void; onChange: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [measuring, setMeasuring] = useState<WoLine | null>(null);
  const [editing, setEditing] = useState(false);

  async function act(path: string) {
    setError(null);
    try {
      await api(`/api/execution/${path}`, { method: "POST" });
      await onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (editing) return <WoForm site={site} wo={wo} onClose={() => setEditing(false)} onSaved={async () => (setEditing(false), await onChange())} />;
  return (
    <Modal title={`${wo.code} · ${wo.subcontractor_name}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      {warning && <div className="alert alert-warn">{warning}</div>}
      <p>
        <WoStatus status={wo.status} /> <span className="muted small">material by {wo.material_by === "eespl" ? "EESPL" : "the subcontractor"}</span>
      </p>
      <div className="tiles">
        <div className="tile">
          <div className="tile-title">Value</div>
          <b>{inr(wo.amount)}</b>
          <div className="small muted">
            retention {num(wo.retention_percent)}% {inr(wo.retention)} · TDS {num(wo.tds_percent)}% {inr(wo.tds)}
          </div>
        </div>
        <div className="tile">
          <div className="tile-title">Billable to date</div>
          <b>{inr(wo.billable_to_date)}</b>
          <div className="small muted">
            less retention {inr(wo.retention_to_date)} · TDS {inr(wo.tds_to_date)} (RA bills: M5)
          </div>
        </div>
      </div>
      {wo.lines.map((l) => (
        <div key={l.id} className="card top-gap">
          <div className="toolbar">
            <div>
              <b>{l.description}</b>
              <div className="small muted">
                {num(l.qty)} {l.unit} × {inr(l.rate)} = {inr(l.amount)} · measured {num(l.measured)} · verified {num(l.verified)}
                {l.over && <span className="text-danger"> · over the WO qty</span>}
              </div>
            </div>
            {wo.can_measure && (
              <button className="btn btn-small btn-primary" onClick={() => setMeasuring(l)}>
                + Measurement
              </button>
            )}
          </div>
          {l.measurements.length > 0 && (
            <table className="table compact">
              <tbody>
                {l.measurements.map((m) => (
                  <tr key={m.id}>
                    <td className="nowrap">{shortDate(m.on_date)}</td>
                    <td className="num">
                      {num(m.qty)} {l.unit}
                    </td>
                    <td>
                      <span className={`badge ${M_BADGE[m.status]}`}>{m.status.replace("_", " ")}</span>{" "}
                      {m.verified_by_name && <span className="small muted">by {m.verified_by_name}</span>}
                    </td>
                    <td className="small">{m.remark ?? ""}</td>
                    <td className="nowrap">
                      {m.status === "recorded" && wo.can_change_status && (
                        <button className="btn btn-small" onClick={() => void act(`measurements/${m.id}/verify`)}>
                          Verify
                        </button>
                      )}
                      {m.status === "pending_approval" && wo.can_approve && (
                        <>
                          <button className="btn btn-small btn-primary" onClick={() => void act(`measurements/${m.id}/approve`)}>
                            Approve
                          </button>
                          <button className="btn btn-small btn-danger" onClick={() => void act(`measurements/${m.id}/reject`)}>
                            Reject
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
      <div className="form-actions">
        <button className="btn" onClick={() => void downloadFile(`/api/execution/work-orders/${wo.id}/pdf`).catch((err) => setError(errorText(err)))}>
          PDF
        </button>
        {wo.can_edit && (
          <button className="btn" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {wo.status === "draft" && wo.can_approve && (
          <button className="btn btn-primary" onClick={() => void act(`work-orders/${wo.id}/approve`)}>
            Approve
          </button>
        )}
        {wo.status === "active" && wo.can_change_status && (
          <button className="btn" onClick={() => void act(`work-orders/${wo.id}/complete`)}>
            Mark completed
          </button>
        )}
        {wo.status === "completed" && wo.can_change_status && (
          <button className="btn" onClick={() => void act(`work-orders/${wo.id}/close`)}>
            Close
          </button>
        )}
      </div>
      {measuring && (
        <MeasureForm
          wo={wo}
          line={measuring}
          onClose={() => setMeasuring(null)}
          onSaved={async (w) => {
            setMeasuring(null);
            setWarning(w.warning ?? null);
            await onChange();
          }}
        />
      )}
    </Modal>
  );
}

function MeasureForm({ wo, line, onClose, onSaved }: { wo: WorkOrder; line: WoLine; onClose: () => void; onSaved: (w: WorkOrder) => Promise<void> }) {
  const [form, setForm] = useState({ on_date: localToday(), qty: "", remark: "" });
  const [files, setFiles] = useState<FileList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const after = Number(line.measured) + Number(form.qty || 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const w = await api<WorkOrder>(`/api/execution/work-orders/${wo.id}/lines/${line.id}/measurements`, { method: "POST", json: { ...form, remark: form.remark || null } });
      const m = w.lines.find((l) => l.id === line.id)?.measurements.at(-1);
      for (const f of Array.from(files ?? [])) {
        const body = new FormData();
        body.append("file", f);
        if (m) await api(`/api/execution/measurements/${m.id}/photos`, { method: "POST", form: body });
      }
      await onSaved(w);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`Measure: ${line.description}`} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Date</span>
            <input type="date" className="tap-input" value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Qty done ({line.unit}) *</span>
            <input required className="tap-input" inputMode="decimal" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
          </label>
        </div>
        {after > Number(line.qty) && (
          <div className="alert alert-warn">
            This takes the line to {num(after)} {line.unit}, beyond the WO qty of {num(line.qty)}: it will need approval.
          </div>
        )}
        <label className="field">
          <span>Remark</span>
          <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
        </label>
        <label className="btn tap-wide">
          📷 Photos {files?.length ? `(${files.length})` : ""}
          <input type="file" accept="image/*" capture="environment" multiple hidden onChange={(e) => setFiles(e.target.files)} />
        </label>
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
