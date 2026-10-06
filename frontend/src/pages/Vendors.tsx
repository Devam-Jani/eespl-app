import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText, inr } from "../format";
import type { BankAccount, Contact, Page, Product, Vendor } from "../types";
import { Pager } from "./Clients";

const TYPES: Record<string, string> = {
  material_supplier: "Material supplier",
  labour_contractor: "Labour contractor",
  subcontractor: "Subcontractor",
  transporter: "Transporter",
  other: "Other",
};
const PAGE_SIZE = 25;

export default function Vendors() {
  const { can } = useAuth();
  const canEdit = can("vendors.edit");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", type: "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Vendor> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Vendor | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Vendor>>(`/api/vendors${queryString({ ...filters, limit: PAGE_SIZE, offset })}`));
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
        <h1>Vendors</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search name, city or GSTIN" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select
            value={filters.type}
            onChange={(e) => {
              setOffset(0);
              setFilters((f) => ({ ...f, type: e.target.value }));
            }}
          >
            <option value="">All types</option>
            {Object.entries(TYPES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <ExportButton path={`/api/vendors/export${queryString(filters)}`} />
          {canEdit && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add vendor
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>City</th>
              <th>GSTIN</th>
              <th>Primary contact</th>
              <th className="num">Products</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((v) => {
              const contact = v.contacts.find((c) => c.is_primary) ?? v.contacts[0];
              return (
                <tr key={v.id} className={`clickable ${v.is_active ? "" : "row-muted"}`} onClick={() => setOpen(v.id)}>
                  <td>{v.name}</td>
                  <td>{TYPES[v.type] ?? v.type}</td>
                  <td>{[v.city, v.state].filter(Boolean).join(", ") || "—"}</td>
                  <td>
                    <code>{v.gstin ?? "—"}</code>
                  </td>
                  <td>
                    {contact ? (
                      <>
                        {contact.name} <span className="muted small">{contact.phone ?? contact.email ?? ""}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num">{v.products.length}</td>
                  <td>
                    <span className={`badge ${v.is_active ? "badge-ok" : "badge-muted"}`}>{v.is_active ? "Active" : "Inactive"}</span>
                  </td>
                </tr>
              );
            })}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No vendors found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}

      {editing && (
        <VendorForm
          vendor={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async (v) => {
            setEditing(null);
            await load();
            setOpen(v.id);
          }}
        />
      )}
      {open !== null && (
        <VendorPanel
          vendorId={open}
          onEdit={(v) => {
            setOpen(null);
            setEditing(v);
          }}
          onClose={() => {
            setOpen(null);
            void load();
          }}
        />
      )}
    </>
  );
}

const EMPTY_CONTACT: Contact = { name: "", designation: null, phone: null, email: null, is_primary: false };

function VendorForm({
  vendor,
  onClose,
  onSaved,
}: {
  vendor: Vendor | null;
  onClose: () => void;
  onSaved: (v: Vendor) => Promise<void>;
}) {
  const [form, setForm] = useState({
    name: vendor?.name ?? "",
    type: vendor?.type ?? "material_supplier",
    gstin: vendor?.gstin ?? "",
    pan: vendor?.pan ?? "",
    address: vendor?.address ?? "",
    city: vendor?.city ?? "",
    state: vendor?.state ?? "",
    payment_terms_days: vendor?.payment_terms_days?.toString() ?? "",
    notes: vendor?.notes ?? "",
    is_active: vendor?.is_active ?? true,
  });
  const [contacts, setContacts] = useState<Contact[]>(
    vendor?.contacts.length ? vendor.contacts : [{ ...EMPTY_CONTACT, is_primary: true }],
  );
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function setContact(i: number, patch: Partial<Contact>) {
    setContacts((cs) =>
      cs.map((c, j) =>
        patch.is_primary ? (j === i ? { ...c, ...patch } : { ...c, is_primary: false }) : j === i ? { ...c, ...patch } : c,
      ),
    );
  }

  async function remove() {
    if (!vendor || !confirm(`Delete vendor "${vendor.name}" with its contacts and bank accounts?`)) return;
    try {
      await api(`/api/vendors/${vendor.id}`, { method: "DELETE" });
      onClose();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = {
      ...form,
      gstin: form.gstin || null,
      pan: form.pan || null,
      payment_terms_days: form.payment_terms_days === "" ? null : Number(form.payment_terms_days),
      contacts: contacts
        .filter((c) => c.name.trim())
        .map((c) => ({ name: c.name, designation: c.designation || null, phone: c.phone || null, email: c.email || null, is_primary: c.is_primary })),
    };
    try {
      const saved = vendor
        ? await api<Vendor>(`/api/vendors/${vendor.id}`, { method: "PATCH", json: body })
        : await api<Vendor>("/api/vendors", { method: "POST", json: body });
      await onSaved(saved);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={vendor ? `Edit ${vendor.name}` : "Add vendor"} onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Name</span>
            <input value={form.name} onChange={set("name")} required autoFocus />
          </label>
          <label className="field">
            <span>Type</span>
            <select value={form.type} onChange={set("type")}>
              {Object.entries(TYPES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>GSTIN</span>
            <input value={form.gstin} onChange={set("gstin")} maxLength={15} />
          </label>
          <label className="field">
            <span>PAN</span>
            <input value={form.pan} onChange={set("pan")} maxLength={10} />
          </label>
          <label className="field">
            <span>City</span>
            <input value={form.city} onChange={set("city")} />
          </label>
          <label className="field">
            <span>State</span>
            <input value={form.state} onChange={set("state")} />
          </label>
          <label className="field">
            <span>Payment terms (days)</span>
            <input type="number" min="0" value={form.payment_terms_days} onChange={set("payment_terms_days")} />
          </label>
        </div>
        <label className="field">
          <span>Address</span>
          <textarea rows={2} value={form.address} onChange={set("address")} />
        </label>
        <label className="field">
          <span>Notes</span>
          <textarea rows={2} value={form.notes} onChange={set("notes")} />
        </label>
        <label className="check">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
          Active
        </label>
        <h3 className="section-title">Contacts</h3>
        <table className="table compact">
          <thead>
            <tr>
              <th>Name</th>
              <th>Designation</th>
              <th>Phone</th>
              <th>Email</th>
              <th>Primary</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {contacts.map((c, i) => (
              <tr key={i}>
                <td>
                  <input value={c.name} onChange={(e) => setContact(i, { name: e.target.value })} />
                </td>
                <td>
                  <input value={c.designation ?? ""} onChange={(e) => setContact(i, { designation: e.target.value })} />
                </td>
                <td>
                  <input value={c.phone ?? ""} onChange={(e) => setContact(i, { phone: e.target.value })} />
                </td>
                <td>
                  <input type="email" value={c.email ?? ""} onChange={(e) => setContact(i, { email: e.target.value })} />
                </td>
                <td className="center-cell">
                  <input type="radio" name="primary" checked={c.is_primary} onChange={() => setContact(i, { is_primary: true })} />
                </td>
                <td>
                  <button type="button" className="btn btn-small" onClick={() => setContacts((cs) => cs.filter((_, j) => j !== i))}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="btn btn-small" onClick={() => setContacts((cs) => [...cs, { ...EMPTY_CONTACT }])}>
          + Add contact
        </button>
        <div className="form-actions">
          {vendor && (
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

function VendorPanel({ vendorId, onEdit, onClose }: { vendorId: number; onEdit: (v: Vendor) => void; onClose: () => void }) {
  const { can } = useAuth();
  const canEdit = can("vendors.edit");
  const canBank = can("settings.company", "finance.view");
  const [vendor, setVendor] = useState<Vendor | null>(null);
  const [tab, setTab] = useState<"bank" | "products">("products");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setVendor(await api<Vendor>(`/api/vendors/${vendorId}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [vendorId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!vendor) {
    return (
      <Modal title="Vendor" onClose={onClose} wide>
        {error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}
      </Modal>
    );
  }

  return (
    <Modal title={vendor.name} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="item-summary">
        <span>{TYPES[vendor.type] ?? vendor.type}</span>
        {vendor.gstin && (
          <span>
            GSTIN <code>{vendor.gstin}</code>
          </span>
        )}
        {vendor.payment_terms_days !== null && <span>Pays in {vendor.payment_terms_days} days</span>}
        <span className="muted">{[vendor.city, vendor.state].filter(Boolean).join(", ")}</span>
        {canEdit && (
          <button className="btn btn-small push-right" onClick={() => onEdit(vendor)}>
            Edit details
          </button>
        )}
      </div>
      {vendor.contacts.length > 0 && (
        <p className="small">
          {vendor.contacts.map((c) => (
            <span key={c.id} className="chip">
              {c.name} {c.phone ?? ""} {c.email ?? ""}
            </span>
          ))}
        </p>
      )}
      <div className="tabs top-gap">
        <button className={`tab ${tab === "products" ? "active" : ""}`} onClick={() => setTab("products")}>
          Products supplied ({vendor.products.length})
        </button>
        <button className={`tab ${tab === "bank" ? "active" : ""}`} onClick={() => setTab("bank")}>
          Bank accounts ({vendor.bank_accounts.length})
        </button>
      </div>
      <div className="top-gap">
        {tab === "products" ? (
          <SuppliedProducts vendor={vendor} canEdit={canEdit} onSaved={setVendor} onError={setError} />
        ) : (
          <BankAccounts vendor={vendor} canEdit={canEdit && canBank} onSaved={setVendor} onError={setError} />
        )}
      </div>
    </Modal>
  );
}

function BankAccounts({
  vendor,
  canEdit,
  onSaved,
  onError,
}: {
  vendor: Vendor;
  canEdit: boolean;
  onSaved: (v: Vendor) => void;
  onError: (e: string | null) => void;
}) {
  const empty = { account_name: vendor.name, account_number: "", ifsc: "", bank: "", branch: "", is_primary: false };
  const [form, setForm] = useState<typeof empty | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    onError(null);
    try {
      const path = editingId ? `/api/vendors/${vendor.id}/bank-accounts/${editingId}` : `/api/vendors/${vendor.id}/bank-accounts`;
      onSaved(await api<Vendor>(path, { method: editingId ? "PUT" : "POST", json: { ...form, bank: form.bank || null, branch: form.branch || null } }));
      setForm(null);
      setEditingId(null);
    } catch (err) {
      onError(errorText(err));
    }
  }

  async function remove(account: BankAccount) {
    if (!confirm(`Remove the ${account.bank ?? ""} account?`)) return;
    try {
      onSaved(await api<Vendor>(`/api/vendors/${vendor.id}/bank-accounts/${account.id}`, { method: "DELETE" }));
    } catch (err) {
      onError(errorText(err));
    }
  }

  return (
    <>
      <table className="table compact">
        <thead>
          <tr>
            <th>Account name</th>
            <th>Account number</th>
            <th>IFSC</th>
            <th>Bank / branch</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {vendor.bank_accounts.map((b) => (
            <tr key={b.id}>
              <td>
                {b.account_name} {b.is_primary && <span className="badge badge-ok">primary</span>}
              </td>
              <td>{b.masked ? <span className="muted" title="Needs settings.company or finance.view">hidden</span> : <code>{b.account_number}</code>}</td>
              <td>{b.masked ? <span className="muted">hidden</span> : <code>{b.ifsc}</code>}</td>
              <td>{[b.bank, b.branch].filter(Boolean).join(", ") || "—"}</td>
              <td className="row-actions">
                {canEdit && (
                  <>
                    <button
                      className="btn btn-small"
                      onClick={() => {
                        setEditingId(b.id);
                        setForm({
                          account_name: b.account_name,
                          account_number: b.account_number ?? "",
                          ifsc: b.ifsc ?? "",
                          bank: b.bank ?? "",
                          branch: b.branch ?? "",
                          is_primary: b.is_primary,
                        });
                      }}
                    >
                      Edit
                    </button>
                    <button className="btn btn-small btn-danger" onClick={() => void remove(b)}>
                      Remove
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
          {vendor.bank_accounts.length === 0 && (
            <tr>
              <td colSpan={5} className="empty">
                No bank accounts.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {!canEdit && <p className="muted small">Bank details can be added by someone with access to company or finance settings.</p>}
      {canEdit && !form && (
        <button className="btn btn-small" onClick={() => setForm(empty)}>
          + Add bank account
        </button>
      )}
      {form && (
        <form className="inline-form" onSubmit={save}>
          <div className="grid-4">
            <label className="field">
              <span>Account name</span>
              <input value={form.account_name} onChange={(e) => setForm({ ...form, account_name: e.target.value })} required />
            </label>
            <label className="field">
              <span>Account number</span>
              <input value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} required />
            </label>
            <label className="field">
              <span>IFSC</span>
              <input value={form.ifsc} maxLength={11} onChange={(e) => setForm({ ...form, ifsc: e.target.value })} required />
            </label>
            <label className="field">
              <span>Bank</span>
              <input value={form.bank} onChange={(e) => setForm({ ...form, bank: e.target.value })} />
            </label>
          </div>
          <label className="check">
            <input type="checkbox" checked={form.is_primary} onChange={(e) => setForm({ ...form, is_primary: e.target.checked })} />
            Primary account
          </label>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setForm(null)}>
              Cancel
            </button>
            <button className="btn btn-primary">Save</button>
          </div>
        </form>
      )}
    </>
  );
}

type SuppliedRow = { product_id: number; last_rate: string; lead_time_days: string };

function SuppliedProducts({
  vendor,
  canEdit,
  onSaved,
  onError,
}: {
  vendor: Vendor;
  canEdit: boolean;
  onSaved: (v: Vendor) => void;
  onError: (e: string | null) => void;
}) {
  const [rows, setRows] = useState<SuppliedRow[]>(
    vendor.products.map((p) => ({ product_id: p.product_id, last_rate: p.last_rate ?? "", lead_time_days: p.lead_time_days?.toString() ?? "" })),
  );
  const [products, setProducts] = useState<Product[]>([]);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) return;
    api<Page<Product>>("/api/products?limit=500&active=true").then((p) => setProducts(p.items), () => setProducts([]));
  }, [editing]);

  async function save() {
    onError(null);
    try {
      onSaved(
        await api<Vendor>(`/api/vendors/${vendor.id}/products`, {
          method: "PUT",
          json: rows
            .filter((r) => r.product_id)
            .map((r) => ({
              product_id: r.product_id,
              last_rate: r.last_rate === "" ? null : r.last_rate,
              lead_time_days: r.lead_time_days === "" ? null : Number(r.lead_time_days),
            })),
        }),
      );
      setEditing(false);
    } catch (err) {
      onError(errorText(err));
    }
  }

  if (!editing) {
    return (
      <>
        <table className="table compact">
          <thead>
            <tr>
              <th>Product</th>
              <th>Unit</th>
              <th className="num">Last rate</th>
              <th className="num">Lead time</th>
            </tr>
          </thead>
          <tbody>
            {vendor.products.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.product_name} <span className="muted small">{p.product_code}</span>
                </td>
                <td>{p.unit}</td>
                <td className="num">{inr(p.last_rate)}</td>
                <td className="num">{p.lead_time_days !== null ? `${p.lead_time_days} days` : "—"}</td>
              </tr>
            ))}
            {vendor.products.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  No products linked yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {canEdit && (
          <button className="btn btn-small" onClick={() => setEditing(true)}>
            Edit products supplied
          </button>
        )}
      </>
    );
  }

  const setRow = (i: number, patch: Partial<SuppliedRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <>
      <table className="table compact">
        <thead>
          <tr>
            <th>Product</th>
            <th className="num">Last rate (₹)</th>
            <th className="num">Lead time (days)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>
                <select value={r.product_id} onChange={(e) => setRow(i, { product_id: Number(e.target.value) })}>
                  <option value={0}>Choose a product…</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — {p.unit}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input className="input-num" type="number" step="0.01" min="0" value={r.last_rate} onChange={(e) => setRow(i, { last_rate: e.target.value })} />
              </td>
              <td>
                <input className="input-num" type="number" min="0" value={r.lead_time_days} onChange={(e) => setRow(i, { lead_time_days: e.target.value })} />
              </td>
              <td>
                <button className="btn btn-small" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="form-actions">
        <button className="btn btn-small push-left" onClick={() => setRows((rs) => [...rs, { product_id: 0, last_rate: "", lead_time_days: "" }])}>
          + Add product
        </button>
        <button className="btn" onClick={() => setEditing(false)}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={() => void save()}>
          Save
        </button>
      </div>
    </>
  );
}
