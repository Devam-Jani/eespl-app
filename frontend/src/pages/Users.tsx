import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import Modal from "../components/Modal";
import { canGrant } from "../scopes";
import type { Role, User } from "../types";

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; user: User }
  | { kind: "password"; user: User }
  | null;

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function Users() {
  const { me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try {
      const [u, r] = await Promise.all([api<User[]>("/api/users"), api<Role[]>("/api/roles")]);
      setUsers(u);
      setRoles(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleActive(user: User) {
    setError(null);
    try {
      if (user.is_active) {
        if (!confirm(`Deactivate ${user.full_name}? They will be signed out and unable to log in.`)) return;
        await api(`/api/users/${user.id}/deactivate`, { method: "POST" });
        setNotice(`${user.full_name} deactivated.`);
      } else {
        await api(`/api/users/${user.id}`, { method: "PATCH", json: { is_active: true } });
        setNotice(`${user.full_name} reactivated.`);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const q = filter.trim().toLowerCase();
  const shown = q
    ? users.filter((u) => u.full_name.toLowerCase().includes(q) || (u.email ?? "").includes(q))
    : users;

  return (
    <>
      <div className="page-header">
        <h1>Users</h1>
        <div className="page-actions">
          <input
            className="search"
            placeholder="Search name or email"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <ExportButton path="/api/users/export" />
          <button className="btn btn-primary" onClick={() => setDialog({ kind: "create" })}>
            Add user
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Roles</th>
              <th>Status</th>
              <th>Last login</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((u) => {
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id} className={u.is_active ? "" : "row-muted"}>
                  <td>{u.full_name}</td>
                  <td>
                    {u.email ?? <span className="muted">no email</span>}
                    {u.job_title && <div className="muted small">{u.job_title}</div>}
                  </td>
                  <td>{u.phone || "—"}</td>
                  <td>
                    {u.roles.map((r) => (
                      <span key={r.id} className="chip">
                        {r.name}
                      </span>
                    ))}
                  </td>
                  <td>
                    {!u.is_active && !u.has_password ? (
                      <span className="badge badge-warn" title="Imported or invited: add an email and a password, then activate">
                        Not set up
                      </span>
                    ) : !u.is_active ? (
                      <span className="badge badge-muted">Inactive</span>
                    ) : locked ? (
                      <span className="badge badge-warn">Locked</span>
                    ) : (
                      <span className="badge badge-ok">Active</span>
                    )}
                  </td>
                  <td className="nowrap">{formatDate(u.last_login_at)}</td>
                  <td className="row-actions">
                    <button className="btn btn-small" onClick={() => setDialog({ kind: "edit", user: u })}>
                      Edit
                    </button>
                    <button
                      className="btn btn-small"
                      onClick={() => setDialog({ kind: "password", user: u })}
                    >
                      Reset password
                    </button>
                    {u.id !== me?.user.id && (
                      <button className="btn btn-small" onClick={() => void toggleActive(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {shown.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {(dialog?.kind === "create" || dialog?.kind === "edit") && (
        <UserForm
          user={dialog.kind === "edit" ? dialog.user : null}
          roles={roles}
          onClose={() => setDialog(null)}
          onSaved={async (message) => {
            setDialog(null);
            setNotice(message);
            await load();
          }}
        />
      )}
      {dialog?.kind === "password" && (
        <PasswordForm
          user={dialog.user}
          onClose={() => setDialog(null)}
          onSaved={(message) => {
            setDialog(null);
            setNotice(message);
            void load();
          }}
        />
      )}
    </>
  );
}

function UserForm({
  user,
  roles,
  onClose,
  onSaved,
}: {
  user: User | null;
  roles: Role[];
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}) {
  const { me } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [kylasUserId, setKylasUserId] = useState(user?.kylas_user_id?.toString() ?? "");
  const canKylas = !!me && "admin.settings" in me.permissions;
  const [password, setPassword] = useState("");
  const [roleIds, setRoleIds] = useState<number[]>(user?.roles.map((r) => r.id) ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggleRole(id: number) {
    setRoleIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (user) {
        await api(`/api/users/${user.id}`, {
          method: "PATCH",
          json: {
            email,
            full_name: fullName,
            phone: phone || null,
            ...(canKylas ? { kylas_user_id: kylasUserId ? Number(kylasUserId) : null } : {}),
          },
        });
        const before = [...user.roles.map((r) => r.id)].sort().join();
        if ([...roleIds].sort().join() !== before) {
          await api(`/api/users/${user.id}/roles`, { method: "PUT", json: { role_ids: roleIds } });
        }
        await onSaved(`${fullName} updated.`);
      } else {
        await api("/api/users", {
          method: "POST",
          json: { email, full_name: fullName, phone: phone || null, password, role_ids: roleIds },
        });
        await onSaved(`${fullName} added.`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? `Edit ${user.full_name}` : "Add user"} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Full name</span>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          <span>Phone</span>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        {user && canKylas && (
          <label className="field">
            <span>Kylas user id (owner of the Kylas leads this person enters)</span>
            <input value={kylasUserId} inputMode="numeric" onChange={(e) => setKylasUserId(e.target.value.replace(/\D/g, ""))} placeholder="see python -m app.cli kylas-discover" />
          </label>
        )}
        {!user && (
          <label className="field">
            <span>Password (at least 10 characters)</span>
            <input
              type="password"
              autoComplete="new-password"
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
        )}
        <fieldset className="field">
          <span>Roles</span>
          <div className="checks">
            {roles.map((r) => {
              const allowed = !!me && canGrant(me.permissions, r.permissions);
              return (
                <label
                  key={r.id}
                  className={`check ${allowed ? "" : "disabled"}`}
                  title={allowed ? r.description ?? "" : "This role has permissions you do not hold"}
                >
                  <input
                    type="checkbox"
                    checked={roleIds.includes(r.id)}
                    disabled={!allowed && !roleIds.includes(r.id)}
                    onChange={() => toggleRole(r.id)}
                  />
                  {r.name}
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PasswordForm({
  user,
  onClose,
  onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/api/users/${user.id}/reset-password`, { method: "POST", json: { password } });
      onSaved(`Password reset for ${user.full_name}. They have been signed out everywhere.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Reset password: ${user.full_name}`} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>New password (at least 10 characters)</span>
          <input
            type="password"
            autoComplete="new-password"
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label className="field">
          <span>Repeat password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Reset password"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
