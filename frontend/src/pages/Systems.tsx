import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import { Modal } from "../ui/Overlay";
import { errorText, inr } from "../format";
import type { Page, System } from "../types";
import { Pager } from "./Clients";
import { useUnits } from "./Products";
import { Button, Card, Field } from "../ui/components";

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
            <Field label="Search code or name" bare>
              <input className="search" placeholder="Search code or name" value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
          </form>
          <ExportButton path={`/api/systems/export${queryString({ q: search })}`} />
          {canEdit && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              New system
            </Button>
          )}
        </div>
      </div>
      <p className="muted">Rate build-up recipes, one per waterproofing system. Rates use today's product prices.</p>
      {error && <div className="alert alert-error">{error}</div>}

      <Card as="div" className="table-wrap">
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
      </Card>
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
          <Field label="Code">
            <input value={form.code} onChange={set("code")} required autoFocus />
          </Field>
          <Field label="Unit">
            <select value={form.unit} onChange={set("unit")}>
              {units.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.code}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Name">
          <input value={form.name} onChange={set("name")} required />
        </Field>
        <Field label="Description">
          <textarea rows={2} value={form.description} onChange={set("description")} />
        </Field>
        <div className="grid-2">
          <Field label="Surface prep (₹ / unit)">
            <input type="number" step="0.01" min="0" value={form.surface_prep_per_unit} onChange={set("surface_prep_per_unit")} />
          </Field>
          <Field label="Default margin %">
            <input type="number" step="0.01" min="0" value={form.default_margin_percent} onChange={set("default_margin_percent")} />
          </Field>
          <Field label="Labour rate (₹)">
            <input type="number" step="0.01" min="0" value={form.labour_rate} onChange={set("labour_rate")} />
          </Field>
          <Field label="Labour per">
            <select value={form.labour_unit} onChange={set("labour_unit")}>
              <option value="sqm">sqm</option>
              <option value="sqft">sqft</option>
            </select>
          </Field>
        </div>
        <p className="muted small">Add products and consumption on the next screen.</p>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">Create</Button>
        </div>
      </form>
    </Modal>
  );
}
