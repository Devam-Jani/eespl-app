// Settings > Consumption master (Prompt 39a): every work item with its unit, the areas it fits, its
// type and its brand options (from the company BOM and added here). Search by name, brand, product
// or area. Super admin and planning change it (consumption.edit); others read it.
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, Card, Field } from "../ui/components";

export type Vocab = { types: { key: string; label: string }[]; areas: { key: string; label: string }[] };
type Item = {
  id: number;
  code: string;
  name: string;
  unit: string;
  is_active: boolean;
  areas: string[];
  areas_set: boolean;
  type: string | null;
  options: { id: number | null; brand: string | null; is_default: boolean; warnings: string[]; rows: unknown[] }[];
};

export function useVocab(): Vocab | null {
  const [v, setV] = useState<Vocab | null>(null);
  useEffect(() => {
    api<Vocab>("/api/spec/vocab").then(setV, () => setV(null));
  }, []);
  return v;
}

export const UNITS = ["sqm", "sqft", "rmt", "rft", "nos"];

function AddItem({ vocab, onClose }: { vocab: Vocab | null; onClose: () => void }) {
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", unit: "sqm", spec_type: "", areas: [] as string[] });
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      const r = await api<{ id: number }>("/api/spec/master", { method: "POST", json: { name: form.name, unit: form.unit, spec_type: form.spec_type || null, area_keys: form.areas } });
      nav(`/consumption-master/${r.id}`);
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Modal title="Add a work item" onClose={onClose}>
      {error && <div className="alert alert-error">{error}</div>}
      <Field label="Name">
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Unit">
        <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>
          {UNITS.map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
      </Field>
      <Field label="System type">
        <select value={form.spec_type} onChange={(e) => setForm({ ...form, spec_type: e.target.value })}>
          <option value="">Read from the name</option>
          {(vocab?.types ?? []).map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>
      <fieldset className="small">
        <legend>Areas it fits</legend>
        {(vocab?.areas ?? []).map((a) => (
          <label key={a.key} style={{ marginRight: 12 }}>
            <input
              type="checkbox"
              checked={form.areas.includes(a.key)}
              onChange={(e) => setForm({ ...form, areas: e.target.checked ? [...form.areas, a.key] : form.areas.filter((x) => x !== a.key) })}
            />{" "}
            {a.label}
          </label>
        ))}
      </fieldset>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={() => void save()} disabled={form.name.trim().length < 2}>
          Add
        </Button>
      </div>
    </Modal>
  );
}

export default function ConsumptionMaster() {
  const vocab = useVocab();
  const [items, setItems] = useState<Item[] | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", area: "" });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (filters.q) p.set("q", filters.q);
    if (filters.area) p.set("area", filters.area);
    api<{ items: Item[]; can_edit: boolean }>(`/api/spec/master?${p.toString()}`).then(
      (r) => {
        setItems(r.items);
        setCanEdit(r.can_edit);
      },
      (e) => setError(errorText(e)),
    );
  }, [filters]);
  useEffect(load, [load]);
  const areaLabel = (k: string) => vocab?.areas.find((a) => a.key === k)?.label ?? k;
  const typeLabel = (k: string | null) => (k ? (vocab?.types.find((t) => t.key === k)?.label ?? k) : "—");

  return (
    <>
      <div className="page-header">
        <h1>Consumption master</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <Field label="Search name, brand, product or area" bare>
              <input className="search" placeholder="Search name, brand, product or area" value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
          </form>
          <Field label="Area" bare>
            <select value={filters.area} onChange={(e) => setFilters((f) => ({ ...f, area: e.target.value }))}>
              <option value="">All areas</option>
              {(vocab?.areas ?? []).map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </Field>
          {canEdit && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add work item
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Work item</th>
                <th>Unit</th>
                <th>Areas</th>
                <th>Type</th>
                <th>Brand options</th>
              </tr>
            </thead>
            <tbody>
              {(items ?? []).map((it) => {
                const warn = it.options.reduce((n, o) => n + o.warnings.length, 0);
                return (
                  <tr key={it.id} className={it.is_active ? "" : "muted"}>
                    <td>
                      <Link to={`/consumption-master/${it.id}`}>{it.name}</Link>
                      {warn > 0 && <span className="small text-warn"> {warn} outside TDS</span>}
                    </td>
                    <td>{it.unit}</td>
                    <td className="small">
                      {it.areas.map(areaLabel).join(", ") || <span className="muted">not set</span>}
                      {!it.areas_set && it.areas.length > 0 && <span className="muted"> (read from the name)</span>}
                    </td>
                    <td className="small">{typeLabel(it.type)}</td>
                    <td className="small">{it.options.map((o) => (o.brand ? `${o.brand}${o.is_default ? " (default)" : ""}` : "one recipe")).join(", ")}</td>
                  </tr>
                );
              })}
              {items && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No work item matches.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
      {adding && <AddItem vocab={vocab} onClose={() => setAdding(false)} />}
    </>
  );
}
