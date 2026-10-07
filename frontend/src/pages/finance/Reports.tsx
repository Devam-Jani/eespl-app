import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, downloadFile, queryString } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr, num } from "../../format";
import type { Profit } from "../../finance/types";

const COST_LABEL: Record<string, string> = {
  material: "Material",
  labour: "Labour",
  subcontract: "Subcontract",
  equipment: "Equipment",
  freight: "Freight",
  other: "Other",
  petty_cash: "Petty cash",
  staff_salary: "Staff salary",
};

export function ProfitCard({ p }: { p: Profit }) {
  return (
    <div className="split">
      <div className="card">
        <h2 className="section-title">Billing</h2>
        <table className="table compact">
          <tbody>
            {(
              [
                ["Billed (net of GST)", p.billed],
                ["Certified", p.certified],
                ["Received (incl. client TDS)", p.received],
                ["Advance received", p.advance_received],
                ["Retention held", p.retention_held],
                ["Contract value", p.contract_value],
              ] as [string, string | null][]
            ).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td className="num">{inr(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2 className="section-title">Cost to date</h2>
        <table className="table compact">
          <tbody>
            {Object.entries(p.cost).map(([k, v]) => (
              <tr key={k}>
                <td>{COST_LABEL[k] ?? k}</td>
                <td className="num">{inr(v)}</td>
              </tr>
            ))}
            <tr className="grand">
              <td>Total cost</td>
              <td className="num">{inr(p.cost_total)}</td>
            </tr>
            <tr className={p.over_cost ? "row-over" : ""}>
              <td>
                <b>Gross profit</b>
              </td>
              <td className={`num ${Number(p.gross_profit) < 0 ? "text-danger" : ""}`}>
                <b>{inr(p.gross_profit)}</b> {p.margin_percent !== null && `(${num(p.margin_percent, 1)}%)`}
              </td>
            </tr>
            <tr>
              <td>Projected (contract value − budget at completion)</td>
              <td className="num">
                {inr(p.projected_profit)} {p.projected_margin_percent !== null && `(${num(p.projected_margin_percent, 1)}%)`}
              </td>
            </tr>
          </tbody>
        </table>
        {p.salary_hidden && <p className="small muted">Staff salary is left out (needs the payroll permission).</p>}
        {p.over_cost && <p className="text-danger small">Cost to date is more than what is billed.</p>}
      </div>
    </div>
  );
}

export default function SiteProfit() {
  const [rows, setRows] = useState<Profit[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Profit[]>("/api/finance/profit").then(setRows, (err) => setError(errorText(err)));
  }, []);
  return (
    <>
      <h1>Site profit</h1>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Site</th>
              <th className="num">Billed</th>
              <th className="num">Received</th>
              <th className="num">Retention</th>
              <th className="num">Cost to date</th>
              <th className="num">Gross profit</th>
              <th className="num">Margin</th>
              <th className="num">Projected margin</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.site_id} className={p.over_cost ? "row-over" : ""}>
                <td>
                  <Link to={`/sites/${p.site_id}?tab=finance`}>{p.site_code}</Link> <span className="muted small">{p.site_name.slice(0, 50)}</span>
                </td>
                <td className="num">{inr(p.billed)}</td>
                <td className="num">{inr(p.received)}</td>
                <td className="num">{inr(p.retention_held)}</td>
                <td className="num">{inr(p.cost_total)}</td>
                <td className={`num ${Number(p.gross_profit) < 0 ? "text-danger" : ""}`}>{inr(p.gross_profit)}</td>
                <td className="num">{p.margin_percent === null ? "—" : `${num(p.margin_percent, 1)}%`}</td>
                <td className="num">{p.projected_margin_percent === null ? "—" : `${num(p.projected_margin_percent, 1)}%`}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  No billing or cost yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Preview = {
  count: number;
  vouchers: { type: string; number: string; date: string; party: string | null; balanced: boolean; entries: { ledger: string; debit: string | null; credit: string | null }[] }[];
};

export function Tally() {
  const first = new Date();
  first.setDate(1);
  const [range, setRange] = useState({ date_from: first.toISOString().slice(0, 10), date_to: new Date().toISOString().slice(0, 10), include_exported: false });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ledgers, setLedgers] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = queryString({ date_from: range.date_from, date_to: range.date_to, include_exported: range.include_exported ? "true" : undefined });

  const load = useCallback(async () => {
    try {
      setPreview(await api<Preview>(`/api/finance/tally/preview${q}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [q]);
  useEffect(() => {
    void load();
    api<{ ledgers: Record<string, unknown> }>("/api/finance/tally/settings").then(
      (s) => setLedgers(s.ledgers),
      () => setLedgers(null),
    );
  }, [load]);

  async function exportXml() {
    setError(null);
    try {
      await downloadFile(`/api/finance/tally/export${q}`, true, "POST");
      setMessage(`Exported ${preview?.count ?? 0} voucher(s); they are marked exported.`);
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function saveLedgers(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/finance/tally/settings", { method: "PUT", json: { ledgers } });
      setMessage("Ledger names saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <h1>Tally export</h1>
      <p className="muted small">Download only: the XML is imported in TallyPrime (Gateway › Import › Vouchers). Nothing is sent anywhere.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      <div className="card inline-form wrap">
        <input type="date" value={range.date_from} onChange={(e) => setRange({ ...range, date_from: e.target.value })} aria-label="From" />
        <input type="date" value={range.date_to} onChange={(e) => setRange({ ...range, date_to: e.target.value })} aria-label="To" />
        <label className="check">
          <input type="checkbox" checked={range.include_exported} onChange={(e) => setRange({ ...range, include_exported: e.target.checked })} /> include exported
        </label>
        <button className="btn btn-primary" disabled={!preview?.count} onClick={() => void exportXml()}>
          Export {preview?.count ?? 0} voucher(s) as XML
        </button>
        <button className="btn" onClick={() => void downloadFile(`/api/finance/tally/day-book${q}`)}>
          Day book (Excel)
        </button>
      </div>
      <div className="card table-wrap top-gap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Number</th>
              <th>Ledger</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {preview?.vouchers.flatMap((v) =>
              v.entries.map((e, i) => (
                <tr key={`${v.type}-${v.number}-${i}`} className={i === 0 ? "row-current" : ""}>
                  <td>{i === 0 ? v.date : ""}</td>
                  <td>{i === 0 ? v.type : ""}</td>
                  <td>{i === 0 ? v.number : ""}</td>
                  <td>{e.ledger}</td>
                  <td className="num">{e.debit ? inr(e.debit) : ""}</td>
                  <td className="num">{e.credit ? inr(e.credit) : ""}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      {ledgers && (
        <form className="card top-gap" onSubmit={saveLedgers}>
          <h2 className="section-title">Ledger names in Tally</h2>
          <div className="grid-4">
            {Object.entries(ledgers)
              .filter(([, v]) => typeof v === "string")
              .map(([k, v]) => (
                <label key={k} className="field">
                  <span>{k.replace(/_/g, " ")}</span>
                  <input value={v as string} onChange={(e) => setLedgers({ ...ledgers, [k]: e.target.value })} />
                </label>
              ))}
          </div>
          <p className="small muted">Clients and vendors map to party ledgers of the same name.</p>
          <div className="form-actions">
            <button className="btn btn-primary">Save ledger names</button>
          </div>
        </form>
      )}
    </>
  );
}

export function FinanceSettings() {
  const { can } = useAuth();
  const [s, setS] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    api<Record<string, unknown>>("/api/finance/settings").then(setS, (err) => setError(errorText(err)));
  }, []);
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      setS(await api("/api/finance/settings", { method: "PUT", json: s }));
      setMessage("Saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }
  if (!s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const field = (k: string, label: string) => (
    <label className="field">
      <span>{label}</span>
      <input value={String(s[k] ?? "")} onChange={(e) => setS({ ...s, [k]: e.target.value })} disabled={!can("settings.company")} />
    </label>
  );
  return (
    <>
      <h1>Finance settings</h1>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      <form className="card" onSubmit={save}>
        <div className="grid-4">
          {field("invoice_prefix", `Invoice prefix (e.g. ${String(s.invoice_example)})`)}
          {field("works_sac", "Works contract SAC")}
          {field("match_tolerance_percent", "Three-way match tolerance %")}
          {field("payment_approval_limit", "Payment approval limit (₹)")}
          {field("expense_photo_limit", "Bill photo required above (₹)")}
          {field("pf_percent", "PF %")}
          {field("pf_wage_cap", "PF wage cap (₹)")}
          {field("esi_threshold", "ESI threshold (₹ gross)")}
          {field("esi_employee_percent", "ESI employee %")}
          {field("esi_employer_percent", "ESI employer %")}
        </div>
        <label className="field">
          <span>TDS by vendor type (JSON)</span>
          <textarea rows={4} defaultValue={JSON.stringify(s.tds_rules, null, 1)} onBlur={(e) => setS({ ...s, tds_rules: JSON.parse(e.target.value) })} />
        </label>
        <label className="field">
          <span>Professional tax slabs (JSON; default Gujarat)</span>
          <textarea rows={3} defaultValue={JSON.stringify(s.pt_slabs)} onBlur={(e) => setS({ ...s, pt_slabs: JSON.parse(e.target.value) })} />
        </label>
        {can("settings.company") && (
          <div className="form-actions">
            <button className="btn btn-primary">Save</button>
          </div>
        )}
      </form>
    </>
  );
}
