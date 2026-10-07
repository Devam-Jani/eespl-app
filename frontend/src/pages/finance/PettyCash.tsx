import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, fetchObjectUrl } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr } from "../../format";
import type { PettyAccount, PettyEntry } from "../../finance/types";
import type { SiteLookups } from "../../types";
import { localToday } from "../site/DprTab";
import { shortDate } from "../Tenders";
import { useFinanceLookups } from "./Billing";

type Category = { id: number; name: string; budget_head: string };

/** Mobile-first expense form: amount, category, site, who was paid, camera for the bill. */
export function ExpenseForm({ onClose, onSaved }: { onClose: () => void; onSaved: (a: PettyAccount) => void }) {
  const lookups = useFinanceLookups();
  const [cats, setCats] = useState<Category[]>([]);
  const [form, setForm] = useState({ amount: "", category_id: "", site_id: "", on_date: localToday(), paid_to: "", mode: "cash", remark: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<Category[]>("/api/finance/expense-categories").then(setCats, () => setCats([]));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body = new FormData();
    for (const [k, v] of Object.entries(form)) if (v) body.append(k, v);
    if (photo) body.append("photo", photo);
    try {
      onSaved(await api<PettyAccount>("/api/finance/petty-cash/expenses", { method: "POST", form: body }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title="Expense" onClose={onClose}>
      <form onSubmit={submit} className="daily">
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Amount (₹) *</span>
          <input required className="tap-input" inputMode="decimal" value={form.amount} onChange={set("amount")} autoFocus />
        </label>
        <div className="field">
          <span>Category *</span>
          <div className="tap-group">
            {cats.map((c) => (
              <button key={c.id} type="button" className={`tap ${form.category_id === String(c.id) ? "on" : ""}`} onClick={() => setForm({ ...form, category_id: String(c.id) })}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span>Site</span>
          <select className="tap-input" value={form.site_id} onChange={set("site_id")}>
            <option value="">— office / none —</option>
            {lookups?.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} {s.name}
              </option>
            ))}
          </select>
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Paid to</span>
            <input className="tap-input" value={form.paid_to} onChange={set("paid_to")} />
          </label>
          <label className="field">
            <span>Date</span>
            <input type="date" className="tap-input" value={form.on_date} max={localToday()} onChange={set("on_date")} />
          </label>
        </div>
        <label className="field">
          <span>Remark</span>
          <input className="tap-input" value={form.remark} onChange={set("remark")} />
        </label>
        <label className={`btn tap-wide ${photo ? "btn-primary" : ""}`}>
          📷 {photo ? photo.name : "Photo of the bill (required above the limit)"}
          <input type="file" accept="image/*,.pdf" capture="environment" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </label>
        <div className="daily-actions">
          <button type="button" className="btn tap-wide" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary tap-wide" disabled={busy || !form.category_id}>
            Submit
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Entries({ acc, canApprove, onChange }: { acc: PettyAccount; canApprove: boolean; onChange: (a: PettyAccount) => void }) {
  const [error, setError] = useState<string | null>(null);
  async function decide(e: PettyEntry, approve: boolean) {
    const reason = approve ? null : prompt("Why is it rejected?");
    if (!approve && !reason) return;
    try {
      onChange(await api<PettyAccount>(`/api/finance/petty-cash/expenses/${e.id}/decide`, { method: "POST", json: { approve, reason } }));
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function photo(e: PettyEntry) {
    const url = await fetchObjectUrl(`/api/finance/petty-cash/expenses/${e.id}/photo`);
    if (url) window.open(url, "_blank");
  }
  return (
    <div className="table-wrap">
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <tbody>
          {acc.entries?.map((e) => (
            <tr key={e.id} className={e.status === "rejected" ? "row-muted" : ""}>
              <td className="nowrap">{shortDate(e.on_date)}</td>
              <td>
                {e.kind === "expense" ? (
                  <>
                    {e.category} {e.site_code && <span className="muted small">{e.site_code}</span>}
                    <div className="small muted">
                      {e.paid_to} {e.remark}
                    </div>
                  </>
                ) : e.kind === "advance" ? (
                  "Advance given"
                ) : (
                  "Cash returned"
                )}
              </td>
              <td className={`num ${e.kind === "advance" ? "" : "text-danger"}`}>
                {e.kind === "advance" ? "+" : "-"}
                {inr(e.amount)}
              </td>
              <td className="nowrap">
                {e.status !== "approved" && <span className={`badge ${e.status === "submitted" ? "badge-warn" : "badge-danger"}`}>{e.status}</span>}
                {e.has_photo && (
                  <button className="btn btn-small btn-ghost" onClick={() => void photo(e)}>
                    bill
                  </button>
                )}
                {canApprove && e.status === "submitted" && (
                  <>
                    <button className="btn btn-small btn-primary" onClick={() => void decide(e, true)}>
                      Approve
                    </button>
                    <button className="btn btn-small" onClick={() => void decide(e, false)}>
                      Reject
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PettyCash() {
  const { can, me } = useAuth();
  const approver = can("expense.approve");
  const [accounts, setAccounts] = useState<PettyAccount[]>([]);
  const [open, setOpen] = useState<PettyAccount | null>(null);
  const [mine, setMine] = useState<PettyAccount | null>(null);
  const [spending, setSpending] = useState(false);
  const [advance, setAdvance] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAccounts(await api<PettyAccount[]>("/api/finance/petty-cash"));
      setMine(await api<PettyAccount | null>("/api/finance/petty-cash/mine"));
    } catch (err) {
      setError(errorText(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function settle(acc: PettyAccount) {
    const amount = prompt(`Cash returned by ${acc.user_name} (balance ${inr(acc.balance)}):`);
    if (!amount) return;
    try {
      setOpen(await api<PettyAccount>(`/api/finance/petty-cash/${acc.id}/settle`, { method: "POST", json: { amount } }));
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Petty cash</h1>
        <div className="page-actions">
          {approver && (
            <button className="btn" onClick={() => setAdvance(true)}>
              Give advance
            </button>
          )}
          {mine && can("expense.create") && (
            <button className="btn btn-primary" onClick={() => setSpending(true)}>
              + Expense
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {mine && (
        <div className="card daily">
          <div className="tiles">
            <div className="tile">
              <div className="tile-title">My balance</div>
              <b>{inr(mine.balance)}</b>
              {Number(mine.pending) > 0 && <div className="small text-warn">{inr(mine.pending)} waiting for approval</div>}
            </div>
          </div>
          <Entries acc={mine} canApprove={false} onChange={setMine} />
        </div>
      )}
      {!mine && <p className="muted">{me ? "No petty cash account yet: it opens with the first advance." : ""}</p>}
      {(approver || accounts.length > 1) && (
        <>
          <h2 className="section-title top-gap">Accounts</h2>
          <div className="card table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Person</th>
                  <th className="num">Advances</th>
                  <th className="num">Spent</th>
                  <th className="num">Returned</th>
                  <th className="num">Waiting</th>
                  <th className="num">Balance</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => void api<PettyAccount>(`/api/finance/petty-cash/${a.id}`).then(setOpen)}>
                    <td>{a.user_name}</td>
                    <td className="num">{inr(a.advances)}</td>
                    <td className="num">{inr(a.expenses)}</td>
                    <td className="num">{inr(a.settlements)}</td>
                    <td className={`num ${Number(a.pending) ? "text-warn" : ""}`}>{inr(a.pending)}</td>
                    <td className="num">
                      <b>{inr(a.balance)}</b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {open && (
        <Modal title={`Petty cash: ${open.user_name}`} onClose={() => setOpen(null)} wide>
          <p>
            Balance <b>{inr(open.balance)}</b> · waiting {inr(open.pending)}
          </p>
          <Entries acc={open} canApprove={approver} onChange={(a) => (setOpen(a), void load())} />
          {approver && (
            <div className="form-actions">
              <button className="btn" onClick={() => void settle(open)}>
                Record cash returned
              </button>
            </div>
          )}
        </Modal>
      )}
      {spending && <ExpenseForm onClose={() => setSpending(false)} onSaved={(a) => (setSpending(false), setMine(a), void load())} />}
      {advance && <AdvanceForm onClose={() => setAdvance(false)} onSaved={() => (setAdvance(false), void load())} />}
    </>
  );
}

function AdvanceForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const lookups = useFinanceLookups();
  const [users, setUsers] = useState<SiteLookups["users"]>([]);
  const [form, setForm] = useState({ user_id: "", amount: "", mode: "cash", bank_account_id: "", remark: "" });
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
      await api("/api/finance/petty-cash/advances", {
        method: "POST",
        json: { ...form, bank_account_id: form.bank_account_id ? Number(form.bank_account_id) : null, remark: form.remark || null },
      });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="Petty cash advance" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>To *</span>
          <select required value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}>
            <option value="">—</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Amount (₹) *</span>
            <input required inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </label>
          <label className="field">
            <span>Mode</span>
            <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              {["cash", "upi", "neft"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          {form.mode !== "cash" && (
            <label className="field">
              <span>From bank</span>
              <select value={form.bank_account_id} onChange={(e) => setForm({ ...form, bank_account_id: e.target.value })}>
                <option value="">—</option>
                {lookups?.banks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="form-actions">
          <button className="btn btn-primary">Give</button>
        </div>
      </form>
    </Modal>
  );
}
