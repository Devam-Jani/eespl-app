import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText, inr } from "../../format";
import type { FreightReportRow, FreightRow, MaterialLookups } from "../../material/types";
import type { Page } from "../../types";
import { shortDate } from "../Tenders";
import { today, useMaterialLookups } from "./common";
import { Button, Card, Field } from "../../ui/components";

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
      setEntries((await api<Page<FreightRow>>(`/api/material/freight${queryString({ site_id: siteId, year: /^\d{4}$/.test(year) ? year : "", limit: 200 })}`)).items);
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
            <Field label="Site" bare>
              <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
                <option value="">All sites</option>
                {lookups.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} {s.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Year" bare>
            <input className="input-num" value={year} onChange={(e) => setYear(e.target.value)} aria-label="Year" />
          </Field>
          {can("po.edit", "store.edit") && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add transporter bill
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div" className="table-wrap">
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
      </Card>
      <h2 className="section-title top-gap">Entries</h2>
      <Card as="div" className="table-wrap">
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
      </Card>
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
          <Field label="Charge to site *">
            <select required value={form.site_id} onChange={set("site_id")}>
              <option value="">—</option>
              {lookups.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Direction">
            <select value={form.direction} onChange={set("direction")}>
              {Object.entries(DIRECTION).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Date">
            <input type="date" value={form.on_date} onChange={set("on_date")} />
          </Field>
          <Field label="Amount (₹) *">
            <input required inputMode="decimal" value={form.amount} onChange={set("amount")} />
          </Field>
          <Field label="GST %">
            <input inputMode="decimal" value={form.gst_percent} onChange={set("gst_percent")} />
          </Field>
          <Field label="Bill no">
            <input value={form.bill_no} onChange={set("bill_no")} />
          </Field>
          <Field label="Transporter">
            <input value={form.transporter} onChange={set("transporter")} />
          </Field>
          <Field label="Vehicle no">
            <input value={form.vehicle_no} onChange={set("vehicle_no")} />
          </Field>
        </div>
        <Field label="Remark">
          <input value={form.remark} onChange={set("remark")} />
        </Field>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">Save</Button>
        </div>
      </form>
    </Modal>
  );
}
