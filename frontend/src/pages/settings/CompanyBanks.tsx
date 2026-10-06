import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import ExportButton from "../../components/ExportButton";
import Modal from "../../components/Modal";
import { errorText } from "../../format";
import type { CompanyBank } from "../../types";

export default function CompanyBanks() {
  const { can } = useAuth();
  const canEdit = can("settings.company");
  const [rows, setRows] = useState<CompanyBank[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<CompanyBank | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api<CompanyBank[]>("/api/settings/bank-accounts"));
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Bank accounts</h1>
        <div className="page-actions">
          <ExportButton path="/api/settings/bank-accounts/export" />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add account
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Account name</th>
              <th>Account number</th>
              <th>IFSC</th>
              <th>Bank / branch</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                <td>
                  {b.account_name} {b.is_default && <span className="badge badge-ok">default</span>}
                </td>
                <td>
                  <code>{b.account_number}</code>
                </td>
                <td>
                  <code>{b.ifsc}</code>
                </td>
                <td>{[b.bank, b.branch].filter(Boolean).join(", ") || "—"}</td>
                <td className="row-actions">
                  {canEdit && (
                    <button className="btn btn-small" onClick={() => setEditing(b)}>
                      Edit
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No bank accounts yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {editing && (
        <BankForm
          account={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await load();
          }}
        />
      )}
    </>
  );
}

function BankForm({ account, onClose, onSaved }: { account: CompanyBank | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({
    account_name: account?.account_name ?? "",
    account_number: account?.account_number ?? "",
    ifsc: account?.ifsc ?? "",
    bank: account?.bank ?? "",
    branch: account?.branch ?? "",
    is_default: account?.is_default ?? false,
  });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      if (account) {
        // number and IFSC are fixed once saved; add a new account instead
        await api(`/api/settings/bank-accounts/${account.id}`, {
          method: "PATCH",
          json: { account_name: form.account_name, bank: form.bank || null, branch: form.branch || null, is_default: form.is_default },
        });
      } else {
        await api("/api/settings/bank-accounts", { method: "POST", json: { ...form, bank: form.bank || null, branch: form.branch || null } });
      }
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!account || !confirm(`Delete the account ending ${account.account_number.slice(-4)}?`)) return;
    try {
      await api(`/api/settings/bank-accounts/${account.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={account ? "Edit bank account" : "Add bank account"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Account name</span>
          <input value={form.account_name} onChange={(e) => setForm({ ...form, account_name: e.target.value })} required />
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Account number</span>
            <input value={form.account_number} disabled={!!account} onChange={(e) => setForm({ ...form, account_number: e.target.value })} required />
          </label>
          <label className="field">
            <span>IFSC</span>
            <input value={form.ifsc} maxLength={11} disabled={!!account} onChange={(e) => setForm({ ...form, ifsc: e.target.value })} required />
          </label>
          <label className="field">
            <span>Bank</span>
            <input value={form.bank} onChange={(e) => setForm({ ...form, bank: e.target.value })} />
          </label>
          <label className="field">
            <span>Branch</span>
            <input value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} />
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          Default account (printed on bills)
        </label>
        <div className="form-actions">
          {account && (
            <button type="button" className="btn btn-danger push-left" onClick={() => void remove()}>
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
