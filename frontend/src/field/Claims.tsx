import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, inr } from "../format";
import { AuthImage, km } from "./common";
import type { Flag } from "./common";
import { Button, buttonClass, Field } from "../ui/components";

type ClaimDay = {
  id: number;
  day_id: number | null;
  on_date: string;
  stops: string;
  km_basis: string;
  km: number;
  estimated: boolean;
  rate_per_km: number;
  amount: number;
  flags: Flag[];
  edited_km_from: number | null;
  edit_reason: string | null;
  edited_by: string | null;
};
type Claim = {
  id: number;
  user_id: string;
  person: string;
  month: string;
  status: string;
  km: number;
  days_amount: number;
  extras_amount: number;
  total: number;
  flagged_days: number;
  manager: string | null;
  manager_approved_by: string | null;
  manager_approved_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  payroll_month: string | null;
  locked: boolean;
  days: ClaimDay[];
  extras: { id: number; on_date: string; kind: string; amount: number; note: string | null }[];
  can_add_extras: boolean;
  can_manager_approve: boolean;
  can_approve: boolean;
};

const STATUS: Record<string, string> = { draft: "this month so far", ready: "with the manager", manager_approved: "with accounts", approved: "approved (locked)" };

function thisMonth(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
}

export function Claims() {
  const { can } = useAuth();
  const [month, setMonth] = useState("");
  const [rows, setRows] = useState<Claim[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Claim[]>(`/api/field/claims${month ? `?month=${month}` : ""}`).then(setRows, (e) => setError(errorText(e))), [month]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Travel claims</h1>
          <p className="muted">Built from each day&apos;s km and the rate per km on that date; ready on the 1st; the manager approves the days, then accounts approve the month.</p>
        </div>
        <div className="page-actions">
          <Field label="Month" bare>
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
          </Field>
          <Button
            onClick={async () => {
              try {
                await api("/api/field/claims/build", { method: "POST", json: { month: thisMonth() } });
                void load();
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            My claim this month so far
          </Button>
          {can("field.claims") && month && (
            <Button onClick={() => void downloadFile(`/api/field/claims-export.xlsx?month=${month}`)}>
              ⤓ Excel ({month})
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table">
        <thead>
          <tr>
            <th>Person</th>
            <th>Month</th>
            <th>Status</th>
            <th className="num">Km</th>
            <th className="num">Total</th>
            <th className="num">Flagged days</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`/field/claims/${c.id}`}>{c.person}</Link>
              </td>
              <td>{c.month}</td>
              <td>{STATUS[c.status] ?? c.status}</td>
              <td className="num">{km(c.km)}</td>
              <td className="num">{inr(c.total)}</td>
              <td className={`num ${c.flagged_days ? "text-danger" : ""}`}>{c.flagged_days}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="muted">
                No claims.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}

export function ClaimDetail() {
  const { id } = useParams();
  const [c, setC] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ id: number; km: string; reason: string } | null>(null);
  const [extra, setExtra] = useState({ on_date: "", kind: "toll", amount: "", note: "" });
  const [bill, setBill] = useState<File | null>(null);
  const load = useCallback(() => api<Claim>(`/api/field/claims/${id}`).then(setC, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(p: Promise<unknown>): Promise<boolean> {
    setError(null);
    try {
      await p;
      await load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    }
  }
  if (!c) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <p className="breadcrumb">
        <Link to="/field/claims">Travel claims</Link> / {c.person} / {c.month}
      </p>
      <div className="page-header">
        <div>
          <h1>
            Travel claim: {c.person}, {c.month} <span className={`badge ${c.locked ? "badge-ok" : "badge-muted"}`}>{STATUS[c.status] ?? c.status}</span>
          </h1>
          <p className="muted">
            {km(c.km)} · days {inr(c.days_amount)} + tolls and parking {inr(c.extras_amount)} = <b>{inr(c.total)}</b>
            {c.flagged_days > 0 && <span className="text-danger"> · {c.flagged_days} flagged day(s)</span>}
            {c.manager && ` · manager ${c.manager}`}
            {c.manager_approved_by && ` · approved by ${c.manager_approved_by}`}
            {c.approved_by && ` · accounts: ${c.approved_by}, paid with payroll ${c.payroll_month}`}
          </p>
        </div>
        <div className="page-actions">
          <Button onClick={() => void downloadFile(`/api/field/claims/${c.id}/export.xlsx`)}>
            ⤓ Excel
          </Button>
          {c.can_manager_approve && (
            <Button variant="primary" onClick={() => void run(api(`/api/field/claims/${c.id}/manager-approve`, { method: "POST" }))}>
              Approve the days
            </Button>
          )}
          {c.can_approve && (
            <Button variant="primary" onClick={() => void run(api(`/api/field/claims/${c.id}/approve`, { method: "POST" }))}>
              Approve the month (accounts)
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Date</th>
            <th>Stops</th>
            <th>Km</th>
            <th className="num">₹/km</th>
            <th className="num">Amount</th>
            <th>Flags</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {c.days.map((d) => (
            <tr key={d.id} className={d.flags.length ? "row-warn" : ""}>
              <td>{new Date(d.on_date).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" })}</td>
              <td className="small">{d.day_id ? <Link to={`/field/days/${d.day_id}?claim=${c.id}`}>{d.stops || "the day"}</Link> : d.stops}</td>
              <td>
                {km(d.km)} <span className="small muted">{d.km_basis === "route" ? "road" : "tracked"}</span>
                {d.estimated && <span className="text-danger small"> est.</span>}
                {d.edited_km_from !== null && (
                  <div className="small">
                    was {km(d.edited_km_from)}: {d.edit_reason} ({d.edited_by})
                  </div>
                )}
              </td>
              <td className="num">{inr(d.rate_per_km)}</td>
              <td className="num">{inr(d.amount)}</td>
              <td className="small text-danger">{d.flags.map((f) => f.text).join("; ")}</td>
              <td>
                {c.can_manager_approve &&
                  (edit?.id === d.id ? (
                    <span className="inline-form">
                      <Field label="Km" bare>
                        <input className="input-small" value={edit.km} onChange={(e) => setEdit({ ...edit, km: e.target.value })} aria-label="Km" />
                      </Field>
                      <Field label="Reason" bare>
                        <input value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} placeholder="Reason" />
                      </Field>
                      <Button
                        variant="primary" size="small"
                        onClick={() =>
                          void run(api(`/api/field/claims/${c.id}/days/${d.id}`, { method: "PUT", json: { km: edit.km, reason: edit.reason } })).then((ok) => ok && setEdit(null))
                        }
                      >
                        Save
                      </Button>
                    </span>
                  ) : (
                    <Button variant="ghost" size="small" onClick={() => setEdit({ id: d.id, km: String(d.km), reason: "" })}>
                      Edit
                    </Button>
                  ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Tolls, parking and other costs</h3>
      <table className="table compact">
        <tbody>
          {c.extras.map((x) => (
            <tr key={x.id}>
              <td>{x.on_date}</td>
              <td>{x.kind}</td>
              <td>{x.note}</td>
              <td className="num">{inr(x.amount)}</td>
              <td>
                <AuthImage path={`/api/field/claims/${c.id}/extras/${x.id}/bill`} alt="Bill" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {c.can_add_extras && (
        <div className="form-row">
          <Field label="Date" bare>
            <input type="date" value={extra.on_date} onChange={(e) => setExtra({ ...extra, on_date: e.target.value })} aria-label="Date" />
          </Field>
          <Field label="Kind" bare>
            <select value={extra.kind} onChange={(e) => setExtra({ ...extra, kind: e.target.value })} aria-label="Kind">
              <option value="toll">Toll</option>
              <option value="parking">Parking</option>
              <option value="other">Other</option>
            </select>
          </Field>
          <Field label="Amount" bare>
            <input className="input-small" value={extra.amount} onChange={(e) => setExtra({ ...extra, amount: e.target.value })} placeholder="₹" aria-label="Amount" />
          </Field>
          <Field label="Note" bare>
            <input value={extra.note} onChange={(e) => setExtra({ ...extra, note: e.target.value })} placeholder="Note" />
          </Field>
          <label className={buttonClass({ size: "small" })}>
            {bill ? "Bill photo ✓" : "Bill photo"}
            <input type="file" accept="image/*,application/pdf" capture="environment" hidden onChange={(e) => setBill(e.target.files?.[0] ?? null)} />
          </label>
          <Button
            variant="primary" size="small"
            disabled={!extra.on_date || !extra.amount || !bill}
            onClick={() => {
              const form = new FormData();
              Object.entries(extra).forEach(([k, v]) => v && form.append(k, v));
              form.append("bill", bill!);
              void run(api(`/api/field/claims/${c.id}/extras`, { method: "POST", form })).then(() => {
                setExtra({ on_date: "", kind: "toll", amount: "", note: "" });
                setBill(null);
              });
            }}
          >
            Add
          </Button>
        </div>
      )}
    </>
  );
}
