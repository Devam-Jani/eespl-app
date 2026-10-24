import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import ExportButton from "../../components/ExportButton";
import { Modal } from "../../ui/Overlay";
import { errorText } from "../../format";
import type { Gstin } from "../../types";
import { Button, Card, Field } from "../../ui/components";

export default function GstinAddresses() {
  const [rows, setRows] = useState<Gstin[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Gstin | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api<Gstin[]>("/api/settings/gstins"));
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
        <h1>GSTIN addresses</h1>
        <div className="page-actions">
          <ExportButton path="/api/settings/gstins/export" />
          <Button variant="primary" onClick={() => setEditing("new")}>
            Add GSTIN
          </Button>
        </div>
      </div>
      <p className="muted">One row per GST registration. The default is used on bills and purchase orders unless another is chosen.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div" className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>GSTIN</th>
              <th>State</th>
              <th>Address</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.id}>
                <td>
                  <code>{g.gstin}</code> {g.is_default && <span className="badge badge-ok">default</span>}
                </td>
                <td>{g.state}</td>
                <td className="pre-line">{g.address}</td>
                <td className="row-actions">
                  <Button size="small" onClick={() => setEditing(g)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  No GSTINs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
      {editing && (
        <GstinForm
          gstin={editing === "new" ? null : editing}
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

function GstinForm({ gstin, onClose, onSaved }: { gstin: Gstin | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({
    gstin: gstin?.gstin ?? "",
    state: gstin?.state ?? "",
    address: gstin?.address ?? "",
    is_default: gstin?.is_default ?? false,
  });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      if (gstin) {
        await api(`/api/settings/gstins/${gstin.id}`, {
          method: "PATCH",
          json: { state: form.state, address: form.address, is_default: form.is_default },
        });
      } else {
        await api("/api/settings/gstins", { method: "POST", json: form });
      }
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!gstin || !confirm(`Delete ${gstin.gstin}?`)) return;
    try {
      await api(`/api/settings/gstins/${gstin.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={gstin ? `Edit ${gstin.gstin}` : "Add GSTIN"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="GSTIN">
          <input value={form.gstin} maxLength={15} disabled={!!gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value })} required />
        </Field>
        <Field label="State">
          <input value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })} required />
        </Field>
        <Field label="Address">
          <textarea rows={3} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} required />
        </Field>
        <label className="check">
          <input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          Default address
        </label>
        <div className="form-actions">
          {gstin && (
            <Button type="button" variant="danger" className="push-left" onClick={() => void remove()}>
              Delete
            </Button>
          )}
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">Save</Button>
        </div>
      </form>
    </Modal>
  );
}
