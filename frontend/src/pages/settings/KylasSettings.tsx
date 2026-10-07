import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { errorText } from "../../format";
import type { KylasSettings } from "../../types";

/** Settings > Integrations > Kylas (super_admin). The API key is set in .env only: this page
 * shows whether it is set, never the key. */
export default function KylasSettingsPage() {
  const [data, setData] = useState<KylasSettings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [test, setTest] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function apply(s: KylasSettings) {
    setData(s);
    setForm({
      source_id: s.source_id?.toString() ?? "",
      owner_rule: s.owner_rule,
      default_owner_id: s.default_owner_id?.toString() ?? "",
      deal_pipeline_id: s.deal_pipeline_id?.toString() ?? "",
      won_stage_id: s.won_stage_id?.toString() ?? "",
      lead_code_field: s.lead_code_field,
      category_field: s.category_field,
      junk_reasons: s.junk_reasons.join("\n"),
    });
  }

  useEffect(() => {
    api<KylasSettings>("/api/settings/kylas").then(apply, (err) => setError(errorText(err)));
  }, []);

  const num = (v: string) => (v.trim() ? Number(v) : null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      apply(
        await api<KylasSettings>("/api/settings/kylas", {
          method: "PUT",
          json: {
            source_id: num(form.source_id),
            owner_rule: form.owner_rule,
            default_owner_id: num(form.default_owner_id),
            deal_pipeline_id: num(form.deal_pipeline_id),
            won_stage_id: num(form.won_stage_id),
            lead_code_field: form.lead_code_field,
            category_field: form.category_field,
            junk_reasons: form.junk_reasons.split("\n").map((r) => r.trim()).filter(Boolean),
          },
        }),
      );
      setNotice("Kylas settings saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function testConnection() {
    setTest("Testing…");
    try {
      const r = await api<{ ok: boolean; message: string }>("/api/settings/kylas/test", { method: "POST" });
      setTest(`${r.ok ? "✓" : "✗"} ${r.message}`);
    } catch (err) {
      setTest(errorText(err));
    }
  }

  const field = (key: string, label: string, hint?: string) => (
    <label className="field">
      <span>{label}</span>
      <input value={form[key] ?? ""} onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))} placeholder={hint} />
    </label>
  );

  return (
    <>
      <div className="page-header">
        <h1>Integrations › Kylas</h1>
        <button className="btn" onClick={() => void testConnection()}>
          Test connection
        </button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      {test && <div className="alert alert-ok">{test}</div>}
      {data && (
        <div className="split">
          <form className="card" onSubmit={save}>
            <div className={`alert ${data.active ? "alert-ok" : "alert-warn"}`}>
              {data.active ? "Kylas sync is on: new leads are pushed, outcomes are polled." : `Kylas sync is off: ${data.inactive_reason}.`}
            </div>
            <div className="grid-2">
              {field("source_id", "Lead source id (the \"EESPL App\" source)", "empty = push off")}
              <label className="field">
                <span>Owner rule</span>
                <select value={form.owner_rule} onChange={(e) => setForm((f) => ({ ...f, owner_rule: e.target.value }))}>
                  <option value="creator">The Kylas user of whoever entered the lead, else the default owner</option>
                  <option value="default">Always the default owner</option>
                </select>
              </label>
              {field("default_owner_id", "Default owner (Kylas user id)")}
              {field("deal_pipeline_id", "Deal pipeline id (optional)", "empty = deal poll off")}
              {field("won_stage_id", "Won stage id (optional)", "empty = deal poll off")}
              {field("lead_code_field", "Custom field for our lead code")}
              {field("category_field", "Custom field for the category")}
            </div>
            <label className="field">
              <span>Junk reasons (one per line; a lead closed in Kylas with one of these becomes junk)</span>
              <textarea rows={4} value={form.junk_reasons ?? ""} onChange={(e) => setForm((f) => ({ ...f, junk_reasons: e.target.value }))} />
            </label>
            <div className="form-actions">
              <button className="btn btn-primary">Save</button>
            </div>
          </form>
          <div className="card">
            <h2 className="section-title">Environment</h2>
            <dl className="totals">
              <dt>KYLAS_ENABLED</dt>
              <dd>{data.enabled_in_env ? "true" : "false"}</dd>
              <dt>API key</dt>
              <dd>{data.api_key}</dd>
              <dt>Base URL</dt>
              <dd>{data.base_url}</dd>
            </dl>
            <p className="muted small">The key is pasted into the server&apos;s .env file only. It is never stored in the database or shown here.</p>
            <h2 className="section-title top-gap">Leads by Kylas status</h2>
            <dl className="totals">
              {Object.entries(data.queue).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </span>
              ))}
            </dl>
            <p className="muted small">Ids for these fields: run python -m app.cli kylas-discover on the server.</p>
          </div>
        </div>
      )}
    </>
  );
}
