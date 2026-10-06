import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { Client, Contact, Page } from "../types";

const TYPES = ["builder", "developer", "pmc", "contractor", "government", "other"];
const PAGE_SIZE = 25;

export default function Clients() {
  const { me } = useAuth();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Client> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Client | "new" | null>(null);

  const editScope = me?.permissions["clients.edit"];
  const canEdit = (c: Client) =>
    editScope === "all" || (editScope === "own" && c.created_by === me?.user.id);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Client>>(`/api/clients${queryString({ q: search, limit: PAGE_SIZE, offset })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [search, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(c: Client) {
    if (!confirm(`Delete client "${c.name}" and its contacts?`)) return;
    try {
      await api(`/api/clients/${c.id}`, { method: "DELETE" });
      setNotice(`${c.name} deleted.`);
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Clients</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setSearch(q);
            }}
          >
            <input className="search" placeholder="Search name, city or GSTIN" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <ExportButton path={`/api/clients/export${queryString({ q: search })}`} />
          {editScope && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add client
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>City</th>
              <th>GSTIN</th>
              <th>Primary contact</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {page?.items.map((c) => {
              const primary = c.contacts.find((x) => x.is_primary) ?? c.contacts[0];
              return (
                <tr key={c.id} className={c.is_active ? "" : "row-muted"}>
                  <td>{c.name}</td>
                  <td className="capitalize">{c.type}</td>
                  <td>{[c.city, c.state].filter(Boolean).join(", ") || "—"}</td>
                  <td>
                    <code>{c.gstin ?? "—"}</code>
                  </td>
                  <td>
                    {primary ? (
                      <>
                        {primary.name}
                        <span className="muted small"> {primary.phone ?? primary.email ?? ""}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <span className={`badge ${c.is_active ? "badge-ok" : "badge-muted"}`}>
                      {c.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="row-actions">
                    {canEdit(c) ? (
                      <>
                        <button className="btn btn-small" onClick={() => setEditing(c)}>
                          Edit
                        </button>
                        <button className="btn btn-small btn-danger" onClick={() => void remove(c)}>
                          Delete
                        </button>
                      </>
                    ) : (
                      <button className="btn btn-small" onClick={() => setEditing(c)}>
                        View
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No clients found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}

      {editing && (
        <ClientForm
          client={editing === "new" ? null : editing}
          readOnly={editing !== "new" && !canEdit(editing)}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => {
            setEditing(null);
            setNotice(msg);
            await load();
          }}
        />
      )}
    </>
  );
}

export function Pager<T>({ page, onOffset }: { page: Page<T>; onOffset: (o: number) => void }) {
  const { total, limit, offset } = page;
  return (
    <div className="pager">
      <span className="muted">
        {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + limit, total)}`} of {total}
      </span>
      <button className="btn btn-small" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
        Previous
      </button>
      <button className="btn btn-small" disabled={offset + limit >= total} onClick={() => onOffset(offset + limit)}>
        Next
      </button>
    </div>
  );
}

const EMPTY_CONTACT: Contact = { name: "", designation: null, phone: null, email: null, is_primary: false };

function ClientForm({
  client,
  readOnly,
  onClose,
  onSaved,
}: {
  client: Client | null;
  readOnly: boolean;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}) {
  const [form, setForm] = useState({
    name: client?.name ?? "",
    type: client?.type ?? "builder",
    gstin: client?.gstin ?? "",
    pan: client?.pan ?? "",
    address: client?.address ?? "",
    city: client?.city ?? "",
    state: client?.state ?? "",
    notes: client?.notes ?? "",
    is_active: client?.is_active ?? true,
  });
  const [contacts, setContacts] = useState<Contact[]>(
    client?.contacts.length ? client.contacts : [{ ...EMPTY_CONTACT, is_primary: true }],
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function setContact(i: number, patch: Partial<Contact>) {
    setContacts((cs) =>
      cs.map((c, j) => {
        if (patch.is_primary) return j === i ? { ...c, ...patch } : { ...c, is_primary: false };
        return j === i ? { ...c, ...patch } : c;
      }),
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      ...form,
      gstin: form.gstin || null,
      pan: form.pan || null,
      contacts: contacts
        .filter((c) => c.name.trim())
        .map((c) => ({
          name: c.name,
          designation: c.designation || null,
          phone: c.phone || null,
          email: c.email || null,
          is_primary: c.is_primary,
        })),
    };
    try {
      if (client) await api(`/api/clients/${client.id}`, { method: "PATCH", json: body });
      else await api("/api/clients", { method: "POST", json: body });
      await onSaved(`${form.name} saved.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={client ? client.name : "Add client"} onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <fieldset disabled={readOnly} className="plain">
          <div className="grid-2">
            <label className="field">
              <span>Name</span>
              <input value={form.name} onChange={set("name")} required autoFocus />
            </label>
            <label className="field">
              <span>Type</span>
              <select value={form.type} onChange={set("type")}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t === "pmc" ? "PMC" : t[0].toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>GSTIN</span>
              <input value={form.gstin} onChange={set("gstin")} maxLength={15} placeholder="27AAPFU0939F1ZV" />
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
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
            />
            Active
          </label>

          <h3 className="section-title">Contacts</h3>
          <div className="table-wrap">
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
                      <input
                        type="radio"
                        name="primary"
                        checked={c.is_primary}
                        onChange={() => setContact(i, { is_primary: true })}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => setContacts((cs) => cs.filter((_, j) => j !== i))}
                        aria-label="Remove contact"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="btn btn-small" onClick={() => setContacts((cs) => [...cs, { ...EMPTY_CONTACT }])}>
            + Add contact
          </button>
        </fieldset>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            {readOnly ? "Close" : "Cancel"}
          </button>
          {!readOnly && (
            <button className="btn btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
          )}
        </div>
      </form>
    </Modal>
  );
}
