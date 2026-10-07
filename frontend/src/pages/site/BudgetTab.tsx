import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr, num } from "../../format";
import type { Budget } from "../../execution/types";
import type { Site } from "../../types";

const HEAD: Record<string, [string, string]> = {
  material: ["Material", "site issues less returns, plus transfer shortages"],
  labour: ["Labour", "muster roll wage due, own labour"],
  subcontract: ["Subcontract", "verified measurements × WO rate"],
  equipment: ["Equipment", "usage × rate, plus fuel"],
  freight: ["Freight", "PO freight as GRNs arrive, transfers, bills"],
  other: ["Other", "costs entered by hand"],
};

/** Budget vs actual, cost only (client billing is M5). Red above 90 % used. */
export default function BudgetTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const [b, setB] = useState<Budget | null>(null);
  const [edit, setEdit] = useState<Record<string, string> | null>(null);
  const [cost, setCost] = useState({ head: "other", amount: "", description: "" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api<Budget>(`/api/execution/sites/${site.id}/budget`).then(setB, (err) => setError(errorText(err))), [site.id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function run(p: Promise<Budget>) {
    setError(null);
    try {
      setB(await p);
      setEdit(null);
    } catch (err) {
      setError(errorText(err));
    }
  }

  function save() {
    if (!edit) return;
    const heads = Object.fromEntries(Object.entries(edit).map(([k, v]) => [k, v === "" ? null : v]));
    void run(api<Budget>(`/api/execution/sites/${site.id}/budget`, { method: "PUT", json: { heads } }));
  }

  function addCost(e: FormEvent) {
    e.preventDefault();
    void run(api<Budget>(`/api/execution/sites/${site.id}/costs`, { method: "POST", json: cost })).then(() => setCost({ head: "other", amount: "", description: "" }));
  }

  if (!b) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {b.cost_hidden && <div className="alert alert-warn">The budget from the tender's cost is hidden: it needs the tender margin permission.</div>}
      <div className="card table-wrap">
        <table className="table budget">
          <thead>
            <tr>
              <th>Head</th>
              <th className="num">Budget</th>
              <th className="num">Actual so far</th>
              <th className="num">Variance</th>
              <th className="num">% used</th>
            </tr>
          </thead>
          <tbody>
            {b.rows.map((r) => (
              <tr key={r.head} className={r.warn ? "row-over" : ""}>
                <td>
                  {HEAD[r.head][0]}
                  <div className="small muted">{HEAD[r.head][1]}</div>
                </td>
                <td className="num">
                  {edit ? (
                    <input
                      className="input-num"
                      inputMode="decimal"
                      value={edit[r.head] ?? ""}
                      onChange={(e) => setEdit({ ...edit, [r.head]: e.target.value })}
                      aria-label={`${r.head} budget`}
                    />
                  ) : r.hidden ? (
                    <span className="muted">hidden</span>
                  ) : (
                    <>
                      {inr(r.budget)}
                      {r.source === "tender" && <div className="small muted">{r.saved ? "from tender" : "tender (not saved)"}</div>}
                    </>
                  )}
                </td>
                <td className="num">{inr(r.actual)}</td>
                <td className={`num ${r.variance !== null && Number(r.variance) < 0 ? "text-danger" : ""}`}>{r.variance === null ? "—" : inr(r.variance)}</td>
                <td className="num">
                  {r.percent_used === null ? (
                    "—"
                  ) : (
                    <span className={r.warn ? "text-danger" : ""}>
                      <b>{num(r.percent_used, 1)}%</b>
                    </span>
                  )}
                  {r.percent_used !== null && (
                    <div className="progress small-bar">
                      <div className={`progress-fill ${r.warn ? "over" : ""}`} style={{ width: `${Math.min(100, Number(r.percent_used))}%` }} />
                    </div>
                  )}
                </td>
              </tr>
            ))}
            <tr className="grand">
              <td>Total</td>
              <td className="num">{inr(b.total_budget)}</td>
              <td className="num">{inr(b.total_actual)}</td>
              <td className="num">{b.total_budget === null ? "—" : inr(Number(b.total_budget) - Number(b.total_actual))}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      {b.can_edit && (
        <div className="page-actions top-gap">
          {edit ? (
            <>
              <button className="btn" onClick={() => setEdit(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={save}>
                Save budget
              </button>
            </>
          ) : (
            <button className="btn" onClick={() => setEdit(Object.fromEntries(b.rows.map((r) => [r.head, r.saved && !r.hidden ? (r.budget ?? "") : ""])))}>
              Set budget
            </button>
          )}
          {b.tender_suggestion && can("tender.margin") && (
            <button className="btn" onClick={() => void run(api<Budget>(`/api/execution/sites/${site.id}/budget/from-tender`, { method: "POST" }))}>
              Budget from the tender ({inr(Number(b.tender_suggestion.material ?? 0) + Number(b.tender_suggestion.labour ?? 0))})
            </button>
          )}
        </div>
      )}
      {b.can_edit && (
        <form className="card top-gap inline-form wrap" onSubmit={addCost}>
          <b>Add a cost</b>
          <select value={cost.head} onChange={(e) => setCost({ ...cost, head: e.target.value })}>
            {Object.entries(HEAD).map(([k, [l]]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          <input required className="input-num" inputMode="decimal" placeholder="₹" value={cost.amount} onChange={(e) => setCost({ ...cost, amount: e.target.value })} />
          <input required placeholder="What for" value={cost.description} onChange={(e) => setCost({ ...cost, description: e.target.value })} />
          <button className="btn btn-primary">Add</button>
        </form>
      )}
      <p className="muted small top-gap">Cost side only: client billing and margin come with M5.</p>
    </>
  );
}
