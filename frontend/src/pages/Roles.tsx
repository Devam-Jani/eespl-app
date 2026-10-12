import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api";
import type { Scope } from "../api";
import Modal from "../components/Modal";
import { SCOPES } from "../scopes";
import type { Permission, Role } from "../types";

type Grid = Record<number, Record<string, Scope>>;

function sameGrants(a: Record<string, Scope>, b: Record<string, Scope>) {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k]);
}

export default function Roles() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [draft, setDraft] = useState<Grid>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, p] = await Promise.all([api<Role[]>("/api/roles"), api<Permission[]>("/api/permissions")]);
      setRoles(r);
      setPermissions(p);
      setDraft(Object.fromEntries(r.map((role) => [role.id, { ...role.permissions }])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const modules = useMemo(() => {
    const groups = new Map<string, Permission[]>();
    for (const p of permissions) groups.set(p.module, [...(groups.get(p.module) ?? []), p]);
    return [...groups.entries()];
  }, [permissions]);

  function setCell(roleId: number, code: string, value: Scope | "") {
    setDraft((d) => {
      const next = { ...d[roleId] };
      if (value) next[code] = value;
      else delete next[code];
      return { ...d, [roleId]: next };
    });
  }

  async function save(role: Role) {
    setSaving(role.id);
    setError(null);
    setNotice(null);
    try {
      await api(`/api/roles/${role.id}/permissions`, {
        method: "PUT",
        json: { permissions: draft[role.id] },
      });
      setNotice(`Permissions for ${role.name} saved.`);
      await load();
    } catch (err) {
      setError(`${role.name}: ${err instanceof ApiError ? err.message : String(err)}`);
    } finally {
      setSaving(null);
    }
  }

  async function remove(role: Role) {
    const users = role.user_count ? ` It is assigned to ${role.user_count} user(s), who will lose it.` : "";
    if (!confirm(`Delete the role "${role.name}"?${users}`)) return;
    setError(null);
    try {
      await api(`/api/roles/${role.id}`, { method: "DELETE" });
      setNotice(`Role ${role.name} deleted.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Roles &amp; permissions</h1>
        <div className="page-actions">
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            New role
          </button>
        </div>
      </div>
      <p className="muted">
        Scope: <strong>all</strong> = every record, <strong>assigned</strong> = only sites/tenders the user is assigned to, <strong>own</strong> = only records the user created. A
        user with several roles gets the widest scope.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}

      <div className="card table-wrap">
        <table className="table grid">
          <thead>
            <tr>
              <th className="sticky-col">Permission</th>
              {roles.map((r) => (
                <th key={r.id} className="role-col" title={r.description ?? ""}>
                  <div className="role-head">
                    <span>
                      {r.is_system && (
                        <span className="lock" title="System role: cannot be deleted" aria-label="System role">
                          🔒
                        </span>
                      )}
                      {r.name}
                    </span>
                    <span className="muted small">
                      {r.code} · {r.user_count} user{r.user_count === 1 ? "" : "s"}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modules.map(([module, perms]) => (
              <Fragment key={module}>
                <tr className="group-row">
                  <td className="sticky-col">{module}</td>
                  <td colSpan={roles.length} />
                </tr>
                {perms.map((p) => (
                  <tr key={p.code}>
                    <td className="sticky-col" title={p.description ?? ""}>
                      <code>{p.code}</code>
                      {p.description && <div className="perm-desc">{p.description}</div>}
                    </td>
                    {roles.map((r) => {
                      const value = draft[r.id]?.[p.code] ?? "";
                      // the director can be given more, never less (super_admin is locked)
                      const floor = r.code === "director" ? r.permissions[p.code] : undefined;
                      const rank = { own: 1, assigned: 2, all: 3 } as Record<string, number>;
                      return (
                        <td key={r.id} className="cell">
                          <select
                            className={`scope scope-${value || "none"}`}
                            value={value}
                            disabled={r.permissions_locked}
                            onChange={(e) => setCell(r.id, p.code, e.target.value as Scope | "")}
                            aria-label={`${r.name}: ${p.code}`}
                          >
                            <option value="" disabled={!!floor}>
                              —
                            </option>
                            {SCOPES.map((s) => (
                              <option key={s} value={s} disabled={!!floor && rank[s] < rank[floor]}>
                                {s}
                              </option>
                            ))}
                          </select>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="sticky-col" />
              {roles.map((r) => {
                const dirty = !!draft[r.id] && !sameGrants(draft[r.id], r.permissions);
                return (
                  <td key={r.id} className="cell">
                    {r.permissions_locked ? (
                      <span className="muted small">Always all</span>
                    ) : r.code === "director" && !dirty ? (
                      <span className="muted small">Can be added to, never reduced</span>
                    ) : (
                      <div className="col-actions">
                        <button className="btn btn-small btn-primary" disabled={!dirty || saving === r.id} onClick={() => void save(r)}>
                          {saving === r.id ? "Saving…" : "Save"}
                        </button>
                        {dirty && (
                          <button className="btn btn-small" onClick={() => setDraft((d) => ({ ...d, [r.id]: { ...r.permissions } }))}>
                            Undo
                          </button>
                        )}
                        {!r.is_system && (
                          <button className="btn btn-small btn-danger" onClick={() => void remove(r)}>
                            Delete
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>

      {creating && (
        <NewRole
          onClose={() => setCreating(false)}
          onCreated={async (role) => {
            setCreating(false);
            setNotice(`Role ${role.name} created. Set its permissions in the grid, then save.`);
            await load();
          }}
        />
      )}
    </>
  );
}

function NewRole({ onClose, onCreated }: { onClose: () => void; onCreated: (role: Role) => Promise<void> }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const role = await api<Role>("/api/roles", {
        method: "POST",
        json: { code, name, description: description || null },
      });
      await onCreated(role);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <Modal title="New role" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Name</span>
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setCode(
                e.target.value
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, "_")
                  .replace(/^_+|_+$/g, ""),
              );
            }}
            required
            autoFocus
          />
        </label>
        <label className="field">
          <span>Code (lowercase letters, digits and _)</span>
          <input value={code} onChange={(e) => setCode(e.target.value)} pattern="[a-z][a-z0-9_]{1,49}" required />
        </label>
        <label className="field">
          <span>Description</span>
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Create role</button>
        </div>
      </form>
    </Modal>
  );
}
