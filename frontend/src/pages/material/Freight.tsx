import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr } from "../../format";
import type { FreightReportRow, FreightRow, MaterialLookups } from "../../material/types";
import type { Page } from "../../types";
import { shortDate } from "../Tenders";
import { today, useMaterialLookups } from "./common";

const DIRECTION: Record<string, string> = { inbound: "Inbound (vendor → us)", godown_to_site: "Godown → site", other: "Other" };
const SOURCE: Record<string, string> = { po: "PO charge", transfer: "Transfer", bill: "Transporter bill" };

/** Freight per site and month: on POs (inbound), on transfers (godown to site) and loose bills. */
export default function Freight() {
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [siteId, setSiteId] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [report, setReport] = useState<FreightReportRow[]>([]);
  const [entries, setEntries] = useState<FreightRow[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await api<FreightReportRow[]>(`/api/material/freight/report${queryString({ site_id: siteId, year })}`));
      setEntries((await api<Page<FreightRow>>(`/api/material/freight${queryString({ site_id: siteId, limit: 200 })}`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [siteId, year]);

  useEffect(() => {
    void load();
  }, [load]);

  const total = report.reduce((s, r) => s + Number(r.total), 0);

  return (
    <>
      <div className="page-header">
        <h1>Site freight</h1>
        <div className="page-actions">
          {lookups && (
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              <option value="">All sites</option>
              {lookups.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          )}
          <input className="input-num" value={year} onChange={(e) => setYear(e.target.value)} aria-label="Year" />
          {can("po.edit", "store.edit") && (
            <button className="btn btn-primary" onClick={() => setAdding(true)}>
              Add transporter bill
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Site</th>
              <th>Month</th>
              <th className="num">Inbound</th>
              <th className="num">Godown → site</th>
              <th className="num">Other</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {report.map((r) => (
              <tr key={`${r.site_id}-${r.month}`}>
                <td>{r.site_code ? `${r.site_code} ${r.site_name}` : <span className="muted">no site (godown)</span>}</td>
                <td>{r.month}</td>
                <td className="num">{inr(r.inbound)}</td>
                <td className="num">{inr(r.godown_to_site)}</td>
                <td className="num">{inr(r.other)}</td>
                <td className="num">
                  <b>{inr(r.total)}</b>
                </td>
              </tr>
            ))}
            {report.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty">
                  No freight recorded.
                </td>
              </tr>
            ) : (
              <tr className="grand">
                <td colSpan={5}>Total</td>
                <td className="num">
                  <b>{inr(total)}</b>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h2 className="section-title top-gap">Entries</h2>
      <div className="card table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Date</th>
              <th>Site</th>
              <th>Source</th>
              <th>Direction</th>
              <th>Transporter</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((f) => (
              <tr key={f.id}>
                <td className="nowrap">{shortDate(f.on_date)}</td>
                <td>{f.site_code ?? "—"}</td>
                <td>
                  {SOURCE[f.source]} <code>{f.ref_code ?? ""}</code>
                </td>
                <td>{DIRECTION[f.direction]}</td>
                <td>{f.transporter ?? "—"}</td>
                <td className="num">{inr(f.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && lookups && <BillForm lookups={lookups} onClose={() => setAdding(false)} onSaved={async () => (setAdding(false), await load())} />}
    </>
  );
}

function BillForm({ lookups, onClose, onSaved }: { lookups: MaterialLookups; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [form, setForm] = useState({ site_id: "", direction: "inbound", on_date: today(), amount: "", gst_percent: "0", transporter: "", vehicle_no: "", bill_no: "", remark: "" });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const json = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
      await api("/api/material/freight", { method: "POST", json });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title="Transporter bill" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Charge to site *</span>
            <select required value={form.site_id} onChange={set("site_id")}>
              <option value="">—</option>
              {lookups.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Direction</span>
            <select value={form.direction} onChange={set("direction")}>
              {Object.entries(DIRECTION).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Date</span>
            <input type="date" value={form.on_date} onChange={set("on_date")} />
          </label>
          <label className="field">
            <span>Amount (₹) *</span>
            <input required inputMode="decimal" value={form.amount} onChange={set("amount")} />
          </label>
          <label className="field">
            <span>GST %</span>
            <input inputMode="decimal" value={form.gst_percent} onChange={set("gst_percent")} />
          </label>
          <label className="field">
            <span>Bill no</span>
            <input value={form.bill_no} onChange={set("bill_no")} />
          </label>
          <label className="field">
            <span>Transporter</span>
            <input value={form.transporter} onChange={set("transporter")} />
          </label>
          <label className="field">
            <span>Vehicle no</span>
            <input value={form.vehicle_no} onChange={set("vehicle_no")} />
          </label>
        </div>
        <label className="field">
          <span>Remark</span>
          <input value={form.remark} onChange={set("remark")} />
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
