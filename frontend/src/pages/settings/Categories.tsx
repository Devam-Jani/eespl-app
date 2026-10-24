import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import ExportButton from "../../components/ExportButton";
import { Modal } from "../../ui/Overlay";
import { errorText } from "../../format";
import type { Category, Page } from "../../types";
import { Button, Card, Field } from "../../ui/components";

type Kind = "work" | "material";

export default function Categories() {
  const [kind, setKind] = useState<Kind>("work");
  const [rows, setRows] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Category | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await api<Page<Category>>(`/api/categories?kind=${kind}&limit=500`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const names = Object.fromEntries(rows.map((c) => [c.id, c.name]));

  return (
    <>
      <div className="page-header">
        <h1>Categories</h1>
        <div className="page-actions">
          <div className="tabs">
            <button className={`tab ${kind === "work" ? "active" : ""}`} onClick={() => setKind("work")}>
              Work
            </button>
            <button className={`tab ${kind === "material" ? "active" : ""}`} onClick={() => setKind("material")}>
              Material
            </button>
          </div>
          <ExportButton path={`/api/categories/export?kind=${kind}`} />
          <Button variant="primary" onClick={() => setEditing("new")}>
            Add category
          </Button>
        </div>
      </div>
      <p className="muted">
        {kind === "work" ? "Where on site the work is (used on tasks, work orders and issues)." : "What kind of product it is (used on products)."}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div" className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Parent</th>
              <th className="num">Order</th>
              {kind === "material" && <th className="num">Products</th>}
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className={c.is_active ? "" : "row-muted"}>
                <td>{c.name}</td>
                <td>{c.parent_id ? names[c.parent_id] : "—"}</td>
                <td className="num">{c.sort_order}</td>
                {kind === "material" && <td className="num">{c.product_count}</td>}
                <td>{c.is_active ? <span className="badge badge-ok">Active</span> : <span className="badge badge-muted">Inactive</span>}</td>
                <td className="row-actions">
                  <Button size="small" onClick={() => setEditing(c)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {editing && (
        <CategoryForm
          kind={kind}
          category={editing === "new" ? null : editing}
          parents={rows.filter((c) => editing === "new" || c.id !== editing.id)}
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

function CategoryForm({
  kind,
  category,
  parents,
  onClose,
  onSaved,
}: {
  kind: Kind;
  category: Category | null;
  parents: Category[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState({
    name: category?.name ?? "",
    parent_id: category?.parent_id?.toString() ?? "",
    sort_order: category?.sort_order?.toString() ?? "0",
    is_active: category?.is_active ?? true,
  });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = { ...form, parent_id: form.parent_id ? Number(form.parent_id) : null, sort_order: Number(form.sort_order) };
    try {
      if (category) await api(`/api/categories/${category.id}`, { method: "PATCH", json: body });
      else await api("/api/categories", { method: "POST", json: { ...body, kind } });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!category || !confirm(`Delete "${category.name}"?`)) return;
    try {
      await api(`/api/categories/${category.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={category ? `Edit ${category.name}` : `Add ${kind} category`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Name">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus />
        </Field>
        <div className="grid-2">
          <Field label="Parent (optional)">
            <select value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}>
              <option value="">—</option>
              {parents.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Order">
            <input type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} />
          </Field>
        </div>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Active
        </label>
        <div className="form-actions">
          {category && (
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
