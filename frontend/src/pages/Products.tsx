import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText, inr, num } from "../format";
import type { Page, Price, Product, Unit } from "../types";
import { Pager } from "./Clients";

export const CATEGORIES = ["membrane", "coating", "chemical", "admixture", "sealant", "waterstop", "accessory", "other"];
const PAGE_SIZE = 25;

export function useUnits(): Unit[] {
  const [units, setUnits] = useState<Unit[]>([]);
  useEffect(() => {
    api<Unit[]>("/api/units").then(setUnits, () => setUnits([]));
  }, []);
  return units;
}

export default function Products() {
  const { can } = useAuth();
  const seesCost = can("tender.margin");
  const canEdit = can("library.edit");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", category: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Product> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [pricing, setPricing] = useState<Product | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Product>>(`/api/products${queryString({ ...filters, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Products</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search code, name or brand" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select
            value={filters.category}
            onChange={(e) => {
              setOffset(0);
              setFilters((f) => ({ ...f, category: e.target.value }));
            }}
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add product
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Brand</th>
              <th>Category</th>
              <th>Unit</th>
              <th className="num">Pack</th>
              <th className="num">GST %</th>
              {seesCost && <th className="num">Purchase rate</th>}
              {seesCost && <th className="num">Freight</th>}
              <th />
            </tr>
          </thead>
          <tbody>
            {page?.items.map((p) => {
              const price = p.cost?.current_price;
              return (
                <tr key={p.id} className={p.is_active ? "" : "row-muted"}>
                  <td>
                    <code>{p.code}</code>
                  </td>
                  <td>{p.name}</td>
                  <td>{p.brand ?? "—"}</td>
                  <td className="capitalize">{p.category}</td>
                  <td>{p.unit}</td>
                  <td className="num">{num(p.pack_size, 3)}</td>
                  <td className="num">{num(p.gst_percent, 2)}</td>
                  {seesCost && <td className="num">{price ? inr(price.purchase_rate) : <span className="muted">no price</span>}</td>}
                  {seesCost && <td className="num">{price ? inr(price.freight_per_unit) : "—"}</td>}
                  <td className="row-actions">
                    {seesCost && (
                      <button className="btn btn-small" onClick={() => setPricing(p)}>
                        Prices
                      </button>
                    )}
                    {canEdit && (
                      <button className="btn btn-small" onClick={() => setEditing(p)}>
                        Edit
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={10} className="empty">
                  No products found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}

      {editing && (
        <ProductForm
          product={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await load();
          }}
        />
      )}
      {pricing && (
        <PriceHistory
          product={pricing}
          canAdd={canEdit}
          onClose={() => {
            setPricing(null);
            void load();
          }}
        />
      )}
    </>
  );
}

function ProductForm({
  product,
  onClose,
  onSaved,
}: {
  product: Product | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const units = useUnits();
  const [form, setForm] = useState({
    code: product?.code ?? "",
    name: product?.name ?? "",
    brand: product?.brand ?? "",
    category: product?.category ?? "coating",
    unit: product?.unit ?? "kg",
    pack_size: product?.pack_size ?? "",
    gst_percent: product?.gst_percent ?? "18",
    is_active: product?.is_active ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = { ...form, brand: form.brand || null, pack_size: form.pack_size || null };
    try {
      if (product) await api(`/api/products/${product.id}`, { method: "PATCH", json: body });
      else await api("/api/products", { method: "POST", json: body });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!product || !confirm(`Delete ${product.name}?`)) return;
    try {
      await api(`/api/products/${product.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={product ? `Edit ${product.name}` : "Add product"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Code</span>
            <input value={form.code} onChange={set("code")} required autoFocus />
          </label>
          <label className="field">
            <span>Brand</span>
            <input value={form.brand} onChange={set("brand")} />
          </label>
        </div>
        <label className="field">
          <span>Name</span>
          <input value={form.name} onChange={set("name")} required />
        </label>
        <div className="grid-2">
          <label className="field">
            <span>Category</span>
            <select value={form.category} onChange={set("category")}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Unit</span>
            <select value={form.unit} onChange={set("unit")}>
              {units.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.code} — {u.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Pack size</span>
            <input type="number" step="0.001" min="0" value={form.pack_size} onChange={set("pack_size")} />
          </label>
          <label className="field">
            <span>GST %</span>
            <input type="number" step="0.01" min="0" value={form.gst_percent} onChange={set("gst_percent")} required />
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
          Active
        </label>
        <div className="form-actions">
          {product && (
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

function PriceHistory({ product, canAdd, onClose }: { product: Product; canAdd: boolean; onClose: () => void }) {
  const [prices, setPrices] = useState<Price[]>([]);
  const [form, setForm] = useState({
    purchase_rate: "",
    freight_per_unit: "0",
    effective_from: new Date().toISOString().slice(0, 10),
    note: "",
  });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPrices(await api<Price[]>(`/api/products/${product.id}/prices`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [product.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const today = new Date().toISOString().slice(0, 10);
  const currentId = prices.find((p) => p.effective_from <= today)?.id;

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(`/api/products/${product.id}/prices`, {
        method: "POST",
        json: { ...form, note: form.note || null },
      });
      setForm((f) => ({ ...f, purchase_rate: "", note: "" }));
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`Prices: ${product.name}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="muted small">
        Prices are never edited. A new price takes effect from its date; the current price is the latest one dated today or
        earlier.
      </p>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Effective from</th>
              <th className="num">Purchase rate / {product.unit}</th>
              <th className="num">Freight / {product.unit}</th>
              <th className="num">Landed</th>
              <th>Note</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {prices.map((p) => (
              <tr key={p.id} className={p.id === currentId ? "row-current" : ""}>
                <td>{new Date(p.effective_from).toLocaleDateString("en-IN")}</td>
                <td className="num">{inr(p.purchase_rate)}</td>
                <td className="num">{inr(p.freight_per_unit)}</td>
                <td className="num">{inr(Number(p.purchase_rate) + Number(p.freight_per_unit))}</td>
                <td>{p.note ?? ""}</td>
                <td>
                  {p.id === currentId && <span className="badge badge-ok">Current</span>}
                  {p.effective_from > today && <span className="badge badge-warn">Future</span>}
                </td>
              </tr>
            ))}
            {prices.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No prices yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canAdd && (
        <form className="inline-form" onSubmit={add}>
          <h3 className="section-title">Add new price</h3>
          <div className="grid-4">
            <label className="field">
              <span>Purchase rate (₹)</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.purchase_rate}
                onChange={(e) => setForm((f) => ({ ...f, purchase_rate: e.target.value }))}
                required
              />
            </label>
            <label className="field">
              <span>Freight / unit (₹)</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.freight_per_unit}
                onChange={(e) => setForm((f) => ({ ...f, freight_per_unit: e.target.value }))}
              />
            </label>
            <label className="field">
              <span>Effective from</span>
              <input
                type="date"
                value={form.effective_from}
                onChange={(e) => setForm((f) => ({ ...f, effective_from: e.target.value }))}
                required
              />
            </label>
            <label className="field">
              <span>Note</span>
              <input value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
            </label>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary">Add price</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
