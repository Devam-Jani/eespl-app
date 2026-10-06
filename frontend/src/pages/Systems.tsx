import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText, inr } from "../format";
import type { Page, System } from "../types";
import { Pager } from "./Clients";
import { useUnits } from "./Products";

const PAGE_SIZE = 25;

export default function Systems() {
  const { can } = useAuth();
  const canEdit = can("library.edit") && can("tender.margin");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<System> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<System>>(`/api/systems${queryString({ q: search, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [search, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Systems</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setSearch(q);
            }}
          >
            <input className="search" placeholder="Search code or name" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New system
            </button>
          )}
        </div>
      </div>
      <p className="muted">Rate build-up recipes, one per waterproofing system. Rates use today's product prices.</p>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Products</th>
              <th className="num">Rate</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((s) => (
              <tr key={s.id} className={s.is_active ? "" : "row-muted"}>
                <td>
                  <code>{s.code}</code>
                </td>
                <td>
                  <Link to={`/systems/${s.id}`}>{s.name}</Link>
                </td>
                <td className="muted small">{s.components.map((c) => c.product_name).join(", ") || "—"}</td>
                <td className="num nowrap">
                  {s.rate ? (
                    <>
                      <strong>{inr(s.rate)}</strong> <span className="muted small">/ {s.unit}</span>
                    </>
                  ) : (
                    <span className="muted small" title={s.rate_error ?? ""}>
                      not priced
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  No systems yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}
      {creating && <NewSystem onClose={() => setCreating(false)} />}
    </>
  );
}

function NewSystem({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const units = useUnits();
  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    unit: "sqm",
    surface_prep_per_unit: "0",
    labour_rate: "0",
    labour_unit: "sqm",
    default_margin_percent: "30",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const s = await api<System>("/api/systems", { method: "POST", json: { ...form, description: form.description || null } });
      navigate(`/systems/${s.id}`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title="New system" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Code</span>
            <input value={form.code} onChange={set("code")} required autoFocus />
          </label>
          <label className="field">
            <span>Unit</span>
            <select value={form.unit} onChange={set("unit")}>
              {units.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.code}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Name</span>
          <input value={form.name} onChange={set("name")} required />
        </label>
        <label className="field">
          <span>Description</span>
          <textarea rows={2} value={form.description} onChange={set("description")} />
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Surface prep (₹ / unit)</span>
            <input type="number" step="0.01" min="0" value={form.surface_prep_per_unit} onChange={set("surface_prep_per_unit")} />
          </label>
          <label className="field">
            <span>Default margin %</span>
            <input type="number" step="0.01" min="0" value={form.default_margin_percent} onChange={set("default_margin_percent")} />
          </label>
          <label className="field">
            <span>Labour rate (₹)</span>
            <input type="number" step="0.01" min="0" value={form.labour_rate} onChange={set("labour_rate")} />
          </label>
          <label className="field">
            <span>Labour per</span>
            <select value={form.labour_unit} onChange={set("labour_unit")}>
              <option value="sqm">sqm</option>
              <option value="sqft">sqft</option>
            </select>
          </label>
        </div>
        <p className="muted small">Add products and consumption on the next screen.</p>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Create</button>
        </div>
      </form>
    </Modal>
  );
}
