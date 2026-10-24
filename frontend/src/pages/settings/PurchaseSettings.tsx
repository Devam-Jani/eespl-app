import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr } from "../../format";
import type { MaterialLookups, PurchaseSettings as Settings } from "../../material/types";
import { refreshLookups } from "../material/common";
import { Button, Card, Field } from "../../ui/components";

export default function PurchaseSettings() {
  const { can } = useAuth();
  const canEdit = can("settings.company");
  const [form, setForm] = useState<Settings | null>(null);
  const [templates, setTemplates] = useState<{ id: number; name: string }[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Settings>("/api/material/settings").then(setForm, (err) => setError(errorText(err)));
    api<MaterialLookups>("/api/material/lookups").then(
      (l) => setTemplates(l.tc_templates),
      () => setTemplates([]),
    );
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    try {
      setForm(await api<Settings>("/api/material/settings", { method: "PUT", json: form }));
      refreshLookups();
      setMessage("Saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!form) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  return (
    <>
      <h1>Purchase settings</h1>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      <Card as="form" onSubmit={submit}>
        <fieldset disabled={!canEdit}>
          <div className="grid-2">
            <Field label="PO approval limit (₹)">
              <input inputMode="decimal" value={form.po_approval_limit} onChange={(e) => setForm({ ...form, po_approval_limit: e.target.value })} />
              <small className="muted">Up to {inr(form.po_approval_limit)} the buyer approves their own PO; above it a PO approver must.</small>
            </Field>
            <Field label="GRN approvals">
              <select value={form.grn_approval_levels} onChange={(e) => setForm({ ...form, grn_approval_levels: Number(e.target.value) })}>
                <option value={1}>One approval</option>
                <option value={2}>Two approvals (by two people)</option>
              </select>
            </Field>
            <Field label="PO terms &amp; conditions template">
              <select value={form.po_tc_template_id ?? ""} onChange={(e) => setForm({ ...form, po_tc_template_id: Number(e.target.value) || null })}>
                <option value="">Built-in purchase terms</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <label className="check">
              <input type="checkbox" checked={form.allow_negative_stock} onChange={(e) => setForm({ ...form, allow_negative_stock: e.target.checked })} /> Allow stock to go below
              zero
            </label>
          </div>
          {canEdit && (
            <div className="form-actions">
              <Button type="submit" variant="primary">Save</Button>
            </div>
          )}
        </fieldset>
      </Card>
    </>
  );
}
