import { useCallback, useEffect, useState } from "react";
import { api, queryString } from "../../api";
import { errorText, inr } from "../../format";
import type { Revision, RevisionCompare, Tender } from "../../types";

function Delta({ value }: { value: string | null }) {
  if (value === null) return <>—</>;
  const n = Number(value);
  if (n === 0) return <span className="muted">0</span>;
  return <span className={n > 0 ? "delta-up" : "delta-down"}>{(n > 0 ? "+" : "−") + inr(Math.abs(n))}</span>;
}

const CHANGE_BADGE: Record<string, string> = {
  added: "badge-info",
  removed: "badge-danger",
  changed: "badge-warn",
  same: "badge-muted",
};

export default function RevisionsTab({ tender, revisions }: { tender: Tender; revisions: Revision[] }) {
  const options = [...revisions.map((r) => ({ value: String(r.rev_no), label: r.label })), { value: "current", label: `Current (${tender.revision_label})` }];
  const [a, setA] = useState(revisions.length ? String(revisions[0].rev_no) : "current");
  const [b, setB] = useState("current");
  const [result, setResult] = useState<RevisionCompare | null>(null);
  const [onlyChanged, setOnlyChanged] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setResult(await api<RevisionCompare>(`/api/tenders/${tender.id}/revisions/compare${queryString({ a, b })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [tender.id, a, b]);

  useEffect(() => {
    if (revisions.length) void load();
  }, [load, revisions.length]);

  return (
    <div className="split split-narrow">
      <div className="card">
        <h2 className="section-title">Submitted revisions</h2>
        {revisions.length === 0 && <p className="muted">Nothing submitted yet. “Submit {tender.revision_label.split(" ")[0]}” freezes the BOQ as it is.</p>}
        <table className="table compact revision-list">
          <tbody>
            {revisions.map((r) => (
              <tr key={r.rev_no}>
                <td>
                  <strong>{r.label}</strong>
                  <div className="muted small">
                    {new Date(r.submitted_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata",  dateStyle: "medium", timeStyle: "short" })}
                    {r.submitted_by_name ? ` · ${r.submitted_by_name}` : ""}
                  </div>
                  {r.note && <div className="small pre-line">{r.note}</div>}
                </td>
                <td className="num">
                  {inr(r.subtotal)}
                  <div className="muted small">{r.lines} lines</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <div className="toolbar">
          <h2 className="section-title">Compare</h2>
          <span className="inline-form">
            <select value={a} onChange={(e) => setA(e.target.value)} aria-label="From revision">
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            →
            <select value={b} onChange={(e) => setB(e.target.value)} aria-label="To revision">
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <label className="check">
              <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> Only changes
            </label>
          </span>
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        {result && (
          <>
            <dl className="totals">
              <dt>
                Total excl. GST {result.a} → {result.b}
              </dt>
              <dd>
                {inr(result.subtotal_a)} → {inr(result.subtotal_b)} (<Delta value={result.subtotal_delta} />)
              </dd>
              <dt>Total with GST</dt>
              <dd>
                {inr(result.grand_total_a)} → {inr(result.grand_total_b)} (<Delta value={result.grand_total_delta} />)
              </dd>
            </dl>
            <div className="table-wrap top-gap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Description</th>
                    <th>Change</th>
                    <th className="num">Rate {result.a}</th>
                    <th className="num">Rate {result.b}</th>
                    <th className="num">Δ rate</th>
                    <th className="num">Amount {result.a}</th>
                    <th className="num">Amount {result.b}</th>
                    <th className="num">Δ amount</th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines
                    .filter((l) => !onlyChanged || l.change !== "same")
                    .map((l, i) => (
                      <tr key={i}>
                        <td>{l.item_no ?? ""}</td>
                        <td>
                          <span className="clamp" title={l.description}>
                            {l.description}
                          </span>
                        </td>
                        <td>
                          <span className={`badge ${CHANGE_BADGE[l.change]}`}>{l.change}</span>
                        </td>
                        <td className="num">{inr(l.rate_a)}</td>
                        <td className="num">{inr(l.rate_b)}</td>
                        <td className="num">
                          <Delta value={l.rate_delta} />
                        </td>
                        <td className="num">{inr(l.amount_a)}</td>
                        <td className="num">{inr(l.amount_b)}</td>
                        <td className="num">
                          <Delta value={l.amount_delta} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
