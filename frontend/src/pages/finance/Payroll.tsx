import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText, inr, num } from "../../format";
import type { PayrollRun } from "../../finance/types";
import type { SiteLookups } from "../../types";
import { useFinanceLookups } from "./Billing";
import { Button, Card, Field } from "../../ui/components";

type Structure = {
  id: number;
  user_id: string;
  user_name: string;
  effective_from: string;
  basic: string;
  hra: string;
  other_allowance: string;
  pf: boolean;
  esi: boolean;
  monthly_ctc: string;
};
type Wage = {
  id: number;
  name: string;
  trade: string;
  period_from: string;
  period_to: string;
  days: string;
  ot_hours: string;
  wage_due: string;
  advances_recovered: string;
  net: string;
  status: string;
};

export default function Payroll() {
  const { can } = useAuth();
  const lookups = useFinanceLookups();
  const salaries = can("payroll.view");
  const [tab, setTab] = useState<"runs" | "salaries" | "wages">(salaries ? "runs" : "wages");
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [structures, setStructures] = useState<Structure[]>([]);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [lop, setLop] = useState<Record<string, string>>({});
  const [adding, setAdding] = useState(false);
  const [wageSite, setWageSite] = useState<number | "">("");
  const [wages, setWages] = useState<Wage[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      if (salaries) {
        setRuns(await api<PayrollRun[]>("/api/finance/payroll"));
        setStructures(await api<Structure[]>("/api/finance/salary-structures"));
      }
      if (wageSite) setWages(await api<Wage[]>(`/api/finance/labour-wages?site_id=${wageSite}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [salaries, wageSite]);
  useEffect(() => {
    void load();
  }, [load]);

  async function run<T>(p: Promise<T>) {
    setError(null);
    try {
      await p;
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const people = [...new Map(structures.map((s) => [s.user_id, s.user_name])).entries()];
  return (
    <>
      <div className="page-header">
        <h1>Payroll</h1>
        <div className="tabs">
          {salaries && (
            <>
              <button className={`tab ${tab === "runs" ? "active" : ""}`} onClick={() => setTab("runs")}>
                Monthly runs
              </button>
              <button className={`tab ${tab === "salaries" ? "active" : ""}`} onClick={() => setTab("salaries")}>
                Salaries
              </button>
            </>
          )}
          <button className={`tab ${tab === "wages" ? "active" : ""}`} onClick={() => setTab("wages")}>
            Labour wages
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "runs" && salaries && (
        <>
          {can("payroll.edit") && (
            <Card as="div" className="inline-form wrap">
              <Field label="Month" bare>
                <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
              </Field>
              {people.map(([id, name]) => (
                <Field key={id} label={`${name} LOP`} inline className="small">
                  <input
                    className="input-num"
                    inputMode="decimal"
                    value={lop[id] ?? ""}
                    onChange={(e) => setLop({ ...lop, [id]: e.target.value })}
                    aria-label={`${name} loss of pay days`}
                  />
                </Field>
              ))}
              <Button
                variant="primary"
                onClick={() =>
                  void run(
                    api("/api/finance/payroll", {
                      method: "POST",
                      json: { month, adjustments: Object.entries(lop).map(([user_id, v]) => ({ user_id, lop_days: v || "0" })) },
                    }),
                  )
                }
              >
                Compute {month}
              </Button>
            </Card>
          )}
          {runs.map((r) => (
            <Card key={r.id} as="div" className="top-gap table-wrap">
              <div className="toolbar">
                <b>
                  {r.month} <span className={`badge ${r.status === "locked" ? "badge-ok" : "badge-warn"}`}>{r.status === "locked" ? "paid, locked" : "draft"}</span>
                </b>
                {r.status === "draft" && can("payroll.edit") && (
                  <Button
                    variant="primary" size="small"
                    onClick={() => {
                      const ref = prompt(`Paid ${inr(r.totals.net)} for ${r.month}: bank reference?`);
                      if (ref !== null) void run(api(`/api/finance/payroll/${r.id}/lock`, { method: "POST", json: { mode: "neft", ref_no: ref || null } }));
                    }}
                  >
                    Mark paid and lock
                  </Button>
                )}
              </div>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th className="num">Days paid</th>
                    <th className="num">Gross</th>
                    <th className="num">PF</th>
                    <th className="num">ESI</th>
                    <th className="num">PT</th>
                    <th className="num">Advance</th>
                    <th className="num">Net</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {r.payslips.map((p) => (
                    <tr key={p.id}>
                      <td>
                        {p.user_name} <span className="small muted">worked {p.worked_days}</span>
                      </td>
                      <td className="num">
                        {num(p.paid_days)}/{p.days_in_month}
                      </td>
                      <td className="num">{inr(p.gross)}</td>
                      <td className="num">{inr(p.pf_employee)}</td>
                      <td className="num">{inr(p.esi_employee)}</td>
                      <td className="num">{inr(p.pt)}</td>
                      <td className="num">{inr(p.advance_recovery)}</td>
                      <td className="num">
                        <b>{inr(p.net)}</b>
                      </td>
                      <td>
                        <Button size="small" onClick={() => void downloadFile(`/api/finance/payslips/${p.id}/pdf`)}>
                          Payslip
                        </Button>
                      </td>
                    </tr>
                  ))}
                  <tr className="grand">
                    <td colSpan={2}>Total</td>
                    {["gross", "pf_employee", "esi_employee", "pt", "advance_recovery", "net"].map((k) => (
                      <td key={k} className="num">
                        {inr(r.totals[k])}
                      </td>
                    ))}
                    <td />
                  </tr>
                </tbody>
              </table>
            </Card>
          ))}
        </>
      )}
      {tab === "salaries" && salaries && (
        <>
          {can("payroll.edit") && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Set a salary
            </Button>
          )}
          <Card as="div" className="table-wrap top-gap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>From</th>
                  <th className="num">Basic</th>
                  <th className="num">HRA</th>
                  <th className="num">Other</th>
                  <th>PF / ESI</th>
                  <th className="num">Monthly CTC</th>
                </tr>
              </thead>
              <tbody>
                {structures.map((s) => (
                  <tr key={s.id}>
                    <td>{s.user_name}</td>
                    <td>{s.effective_from}</td>
                    <td className="num">{inr(s.basic)}</td>
                    <td className="num">{inr(s.hra)}</td>
                    <td className="num">{inr(s.other_allowance)}</td>
                    <td>
                      {s.pf ? "PF" : ""} {s.esi ? "ESI" : ""}
                    </td>
                    <td className="num">{inr(s.monthly_ctc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
      {tab === "wages" && lookups && (
        <>
          <Card as="div" className="inline-form wrap">
            <Field label="Site" bare>
              <select value={wageSite} onChange={(e) => setWageSite(Number(e.target.value) || "")} aria-label="Site">
                <option value="">Site…</option>
                {lookups.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {wageSite && can("payables.edit") && <WagePeriod siteId={wageSite} onDone={load} />}
          </Card>
          <Card as="div" className="table-wrap top-gap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Period</th>
                  <th className="num">Days</th>
                  <th className="num">OT h</th>
                  <th className="num">Wage due</th>
                  <th className="num">Advances</th>
                  <th className="num">Net</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {wages.map((w) => (
                  <tr key={w.id}>
                    <td>
                      {w.name} <span className="muted small">{w.trade}</span>
                    </td>
                    <td className="small">
                      {w.period_from} – {w.period_to}
                    </td>
                    <td className="num">{num(w.days)}</td>
                    <td className="num">{num(w.ot_hours)}</td>
                    <td className="num">{inr(w.wage_due)}</td>
                    <td className="num">{inr(w.advances_recovered)}</td>
                    <td className="num">
                      <b>{inr(w.net)}</b>
                    </td>
                    <td>
                      {w.status === "paid" ? (
                        <span className="badge badge-ok">paid</span>
                      ) : (
                        can("payables.edit") && (
                          <Button size="small" onClick={() => void run(api(`/api/finance/labour-wages/${w.id}/paid`, { method: "POST", json: { mode: "cash" } }))}>
                            Mark paid
                          </Button>
                        )
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
      {adding && <SalaryForm onClose={() => setAdding(false)} onSaved={() => (setAdding(false), void load())} />}
    </>
  );
}

function WagePeriod({ siteId, onDone }: { siteId: number; onDone: () => Promise<void> }) {
  const [p, setP] = useState({ period_from: "", period_to: "" });
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Field label="From" bare>
        <input type="date" value={p.period_from} onChange={(e) => setP({ ...p, period_from: e.target.value })} aria-label="From" />
      </Field>
      <Field label="To" bare>
        <input type="date" value={p.period_to} onChange={(e) => setP({ ...p, period_to: e.target.value })} aria-label="To" />
      </Field>
      <Button
        variant="primary"
        disabled={!p.period_from || !p.period_to}
        onClick={() =>
          void api("/api/finance/labour-wages", { method: "POST", json: { site_id: siteId, ...p } })
            .then(onDone)
            .catch((err) => setError(errorText(err)))
        }
      >
        Make wages from the muster roll
      </Button>
      {error && <span className="text-danger small">{error}</span>}
    </>
  );
}

function SalaryForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [users, setUsers] = useState<SiteLookups["users"]>([]);
  const [form, setForm] = useState({ user_id: "", effective_from: new Date().toISOString().slice(0, 8) + "01", basic: "", hra: "", other_allowance: "", pf: true, esi: true });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<SiteLookups>("/api/sites/lookups").then(
      (l) => setUsers(l.users),
      () => setUsers([]),
    );
  }, []);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/finance/salary-structures", { method: "POST", json: { ...form, hra: form.hra || "0", other_allowance: form.other_allowance || "0" } });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title="Salary structure" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <Field label="Person *">
            <select required value={form.user_id} onChange={set("user_id")}>
              <option value="">—</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="From">
            <input type="date" value={form.effective_from} onChange={set("effective_from")} />
          </Field>
          <Field label="Basic (₹ a month) *">
            <input required inputMode="decimal" value={form.basic} onChange={set("basic")} />
          </Field>
          <Field label="HRA">
            <input inputMode="decimal" value={form.hra} onChange={set("hra")} />
          </Field>
          <Field label="Other allowances">
            <input inputMode="decimal" value={form.other_allowance} onChange={set("other_allowance")} />
          </Field>
          <Field as="div" label="">
            <label className="check">
              <input type="checkbox" checked={form.pf} onChange={(e) => setForm({ ...form, pf: e.target.checked })} /> PF
            </label>
            <label className="check">
              <input type="checkbox" checked={form.esi} onChange={(e) => setForm({ ...form, esi: e.target.checked })} /> ESI (below the threshold)
            </label>
          </Field>
        </div>
        <div className="form-actions">
          <Button type="submit" variant="primary">Save</Button>
        </div>
      </form>
    </Modal>
  );
}
