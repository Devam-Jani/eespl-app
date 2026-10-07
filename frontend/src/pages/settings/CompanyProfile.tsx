import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, fetchObjectUrl } from "../../api";
import { errorText } from "../../format";
import type { CompanyProfile as Profile } from "../../types";

const FIELDS: { key: keyof Profile; label: string; hint?: string; type?: string }[] = [
  { key: "legal_name", label: "Legal name" },
  { key: "trade_name", label: "Trade name" },
  { key: "pan", label: "PAN", hint: "AAPFU0939F" },
  { key: "tan", label: "TAN", hint: "AHMA12345B" },
  { key: "cin", label: "CIN", hint: "U74999GJ2019PTC123456" },
  { key: "tds_percent", label: "TDS %", type: "number" },
  { key: "default_gst_percent", label: "Default GST %", type: "number" },
  {
    key: "pricing_threshold",
    label: "Auto-pricing threshold (0–1)",
    hint: "0.55",
    type: "number",
  },
  { key: "email", label: "Email", type: "email" },
  { key: "phone", label: "Phone" },
  { key: "website", label: "Website" },
];

export default function CompanyProfile() {
  const [form, setForm] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState<Profile | null>(null);
  const [logo, setLogo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback(async (p: Profile) => {
    setProfile(p);
    setForm(Object.fromEntries(FIELDS.map((f) => [f.key, (p[f.key] as string | null) ?? ""])));
    setLogo(p.has_logo ? await fetchObjectUrl(`/api/settings/company/logo?v=${encodeURIComponent(p.updated_at)}`) : null);
  }, []);

  useEffect(() => {
    api<Profile>("/api/settings/company").then(apply, (err) => setError(errorText(err)));
  }, [apply]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    try {
      await apply(await api<Profile>("/api/settings/company", { method: "PATCH", json: body }));
      setNotice("Company profile saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function upload(file: File) {
    setError(null);
    const data = new FormData();
    data.append("file", file);
    try {
      await apply(await api<Profile>("/api/settings/company/logo", { method: "POST", form: data }));
      setNotice("Logo uploaded.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeLogo() {
    if (!confirm("Remove the logo?")) return;
    try {
      await api("/api/settings/company/logo", { method: "DELETE" });
      await apply(await api<Profile>("/api/settings/company"));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Company profile</h1>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      <div className="split">
        <form className="card form" onSubmit={save}>
          <div className="grid-2">
            {FIELDS.map((f) => (
              <label key={f.key} className="field">
                <span>{f.label}</span>
                <input
                  type={f.type ?? "text"}
                  step={f.type === "number" ? "0.01" : undefined}
                  placeholder={f.hint}
                  value={form[f.key] ?? ""}
                  onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={!profile}>
              Save
            </button>
          </div>
        </form>
        <div className="card">
          <h2 className="section-title">Logo</h2>
          {logo ? <img src={logo} alt="Company logo" className="logo-preview" /> : <p className="muted">No logo yet.</p>}
          <label className="field top-gap">
            <span>Upload PNG, JPEG or WebP (up to 2 MB)</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
          </label>
          {logo && (
            <button className="btn btn-small btn-danger" onClick={() => void removeLogo()}>
              Remove logo
            </button>
          )}
        </div>
      </div>
    </>
  );
}
