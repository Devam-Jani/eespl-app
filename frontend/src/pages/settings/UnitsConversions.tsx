import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../../api";
import ExportButton from "../../components/ExportButton";
import Modal from "../../components/Modal";
import { errorText, num } from "../../format";
import type { Conversion, Page, Product, Unit } from "../../types";

export default function UnitsConversions() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [conversions, setConversions] = useState<Conversion[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [aliasUnit, setAliasUnit] = useState<Unit | null>(null);
  const [form, setForm] = useState({ from_unit: "", to_unit: "", factor: "", product_id: "" });

  const load = useCallback(async () => {
    try {
      const [u, c] = await Promise.all([api<Unit[]>("/api/units"), api<Page<Conversion>>("/api/unit-conversions?limit=500")]);
      setUnits(u);
      setConversions(c.items);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
    api<Page<Product>>("/api/products?limit=500&active=true").then((p) => setProducts(p.items), () => setProducts([]));
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/unit-conversions", {
        method: "POST",
        json: { ...form, product_id: form.product_id ? Number(form.product_id) : null },
      });
      setForm({ from_unit: "", to_unit: "", factor: "", product_id: "" });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function edit(c: Conversion) {
    const factor = prompt(`1 ${c.from_unit} = ? ${c.to_unit}`, c.factor);
    if (!factor || factor === c.factor) return;
    try {
      await api(`/api/unit-conversions/${c.id}`, { method: "PATCH", json: { factor } });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove(c: Conversion) {
    if (!confirm(`Delete ${c.from_unit} → ${c.to_unit}?`)) return;
    try {
      await api(`/api/unit-conversions/${c.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Units &amp; conversions</h1>
        <ExportButton path="/api/unit-conversions/export" />
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="split">
        <div className="card">
          <h2 className="section-title">Conversions</h2>
          <p className="muted small">
            1 <em>from</em> = factor × <em>to</em>. They work both ways and chain. A product-specific conversion (e.g. 1 bag of a
            product = 25 kg) wins over a general one.
          </p>
          <table className="table compact">
            <thead>
              <tr>
                <th>From</th>
                <th>To</th>
                <th className="num">Factor</th>
                <th>Applies to</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {conversions.map((c) => (
                <tr key={c.id}>
                  <td>1 {c.from_unit}</td>
                  <td>{c.to_unit}</td>
                  <td className="num">{num(c.factor, 8)}</td>
                  <td>{c.product_name ?? <span className="muted">all products</span>}</td>
                  <td className="row-actions">
                    <button className="btn btn-small" onClick={() => void edit(c)}>
                      Edit
                    </button>
                    <button className="btn btn-small btn-danger" onClick={() => void remove(c)}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form className="inline-form" onSubmit={add}>
            <h3 className="section-title">Add conversion</h3>
            <div className="grid-4">
              <label className="field">
                <span>1 of</span>
                <select value={form.from_unit} onChange={(e) => setForm({ ...form, from_unit: e.target.value })} required>
                  <option value="">unit…</option>
                  {units.map((u) => (
                    <option key={u.code} value={u.code}>
                      {u.code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>equals</span>
                <input type="number" step="any" min="0" value={form.factor} onChange={(e) => setForm({ ...form, factor: e.target.value })} required />
              </label>
              <label className="field">
                <span>of</span>
                <select value={form.to_unit} onChange={(e) => setForm({ ...form, to_unit: e.target.value })} required>
                  <option value="">unit…</option>
                  {units.map((u) => (
                    <option key={u.code} value={u.code}>
                      {u.code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>For product (optional)</span>
                <select value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
                  <option value="">all products</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary">Add</button>
            </div>
          </form>
          <Converter units={units} products={products} />
        </div>
        <div className="card">
          <h2 className="section-title">Units</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Also written as</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {units.map((u) => (
                <tr key={u.code}>
                  <td>
                    <code>{u.code}</code>
                  </td>
                  <td>{u.name}</td>
                  <td className="small muted">{u.aliases.join(", ")}</td>
                  <td>
                    <button className="btn btn-small" onClick={() => setAliasUnit(u)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            “RO” in a BOQ unit column means rate only: imports store no unit and mark the quantity “QRO”.
          </p>
        </div>
      </div>
      {aliasUnit && (
        <AliasForm
          unit={aliasUnit}
          onClose={() => setAliasUnit(null)}
          onSaved={async () => {
            setAliasUnit(null);
            await load();
          }}
        />
      )}
    </>
  );
}

function Converter({ units, products }: { units: Unit[]; products: Product[] }) {
  const [form, setForm] = useState({ qty: "1", from_unit: "sqm", to_unit: "sqft", product_id: "" });
  const [result, setResult] = useState<string | null>(null);

  async function run(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<{ result: string }>(`/api/units/convert${queryString(form)}`);
      setResult(`${form.qty} ${form.from_unit} = ${num(r.result, 6)} ${form.to_unit}`);
    } catch (err) {
      setResult(errorText(err));
    }
  }

  return (
    <form className="inline-form" onSubmit={run}>
      <h3 className="section-title">Try a conversion</h3>
      <div className="toolbar">
        <input className="input-num" type="number" step="any" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
        <select value={form.from_unit} onChange={(e) => setForm({ ...form, from_unit: e.target.value })}>
          {units.map((u) => (
            <option key={u.code}>{u.code}</option>
          ))}
        </select>
        →
        <select value={form.to_unit} onChange={(e) => setForm({ ...form, to_unit: e.target.value })}>
          {units.map((u) => (
            <option key={u.code}>{u.code}</option>
          ))}
        </select>
        <select value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
          <option value="">any product</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button className="btn btn-small">Convert</button>
      </div>
      {result && <p className="convert-result">{result}</p>}
    </form>
  );
}

function AliasForm({ unit, onClose, onSaved }: { unit: Unit; onClose: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(unit.name);
  const [aliases, setAliases] = useState(unit.aliases.join("\n"));
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/units/${unit.code}`, {
        method: "PATCH",
        json: { name, aliases: aliases.split("\n").map((a) => a.trim()).filter(Boolean) },
      });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`Unit ${unit.code}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="field">
          <span>Also written as (one per line; used by every import)</span>
          <textarea rows={8} value={aliases} onChange={(e) => setAliases(e.target.value)} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
