import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import { Modal } from "../ui/Overlay";
import { canGrant } from "../scopes";
import type { Role, User } from "../types";
import { copyText, errorText } from "../format";
import { Button, Card, Field } from "../ui/components";

type Dialog = { kind: "create" } | { kind: "edit"; user: User } | { kind: "password"; user: User } | null;

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "—";
}

/** The Status column: anyone who never set a password is "Not set up" (imported or invited), active or not. */
export function userStatus(u: Pick<User, "is_active" | "has_password" | "locked_by_failures" | "locked_until">): "not_set_up" | "inactive" | "locked" | "active" {
  if (!u.has_password) return "not_set_up";
  if (!u.is_active) return "inactive";
  return u.locked_by_failures || (u.locked_until && new Date(u.locked_until) > new Date()) ? "locked" : "active";
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
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(path: string, done: string) {
    try {
      await api(path, { method: "POST" });
      setNotice(done);
      void load();
    } catch (err) {
      setNotice(errorText(err));
    }
  }
  async function passwordLink(u: { id: string; full_name: string }) {
    try {
      const r = await api<{ link: string; expires_in_days: number }>(
        `/api/admin/users/${u.id}/password-link`,
        { method: "POST" },
      );
      const url = window.location.origin + r.link;
      const copied = await copyText(url);
      setNotice(
        `One-time link for ${u.full_name} (${copied ? "copied" : "copy it from here"}; works once, ${r.expires_in_days} days): ${url}`,
      );
    } catch (err) {
      setNotice(errorText(err));
    }
  }
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
      setError(errorText(err));
    }
  }

  const q = filter.trim().toLowerCase();
  const shown = q ? users.filter((u) => u.full_name.toLowerCase().includes(q) || (u.email ?? "").includes(q)) : users;

  return (
    <>
      <div className="page-header">
        <h1>Users</h1>
        <div className="page-actions">
          <Field label="Search name or email" bare>
            <input className="search" placeholder="Search name or email" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </Field>
          <ExportButton path="/api/users/export" />
          <Button variant="primary" onClick={() => setDialog({ kind: "create" })}>
            Add user
          </Button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok link-notice">{notice}</div>}

      <Card as="div" className="table-wrap">
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
              const locked = u.locked_by_failures || (u.locked_until && new Date(u.locked_until) > new Date());
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
                    {userStatus(u) === "not_set_up" ? (
                      <span className="badge badge-warn" title="Imported or invited: they have not set a password yet (send a set-password link)">
                        Not set up
                      </span>
                    ) : !u.is_active ? (
                      <span className="badge badge-muted">Inactive</span>
                    ) : locked ? (
                      <span className="badge badge-warn">
                        {u.locked_by_failures
                          ? "Locked: unlock"
                          : "Locked 15 min"}
                      </span>
                    ) : (
                      <span className="badge badge-ok">Active</span>
                    )}
                  </td>
                  <td className="nowrap">{formatDate(u.last_login_at)}</td>
                  <td className="row-actions">
                    {u.can_manage === false ? (
                      <span className="muted small" title="Only a higher role manages this person">
                        Managed by a higher role
                      </span>
                    ) : (
                    <>
                    <Button size="small" onClick={() => setDialog({ kind: "edit", user: u })}>
                      Edit
                    </Button>
                    <Button size="small" onClick={() => setDialog({ kind: "password", user: u })}>
                      Reset password
                    </Button>
                    <Button
                      size="small"
                      onClick={() => void passwordLink(u)}
                      title="A one-time link for the person to set their own password"
                    >
                      Set-password link
                    </Button>
                    {locked && (
                      <Button
                        size="small"
                        onClick={() =>
                          void act(
                            `/api/admin/users/${u.id}/unlock`,
                            `${u.full_name} unlocked`,
                          )
                        }
                      >
                        Unlock
                      </Button>
                    )}
                    {u.totp_enabled_at && (
                      <Button
                        size="small"
                        onClick={() =>
                          confirm(
                            `Turn two-step sign-in off for ${u.full_name} (a lost phone)?`,
                          ) &&
                          void act(
                            `/api/admin/users/${u.id}/two-step-reset`,
                            `Two-step sign-in reset for ${u.full_name}`,
                          )
                        }
                      >
                        Reset two-step
                      </Button>
                    )}
                    {u.id !== me?.user.id && (
                      <Button size="small" onClick={() => void toggleActive(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    )}
                    </>
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
      </Card>

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

function UserForm({ user, roles, onClose, onSaved }: { user: User | null; roles: Role[]; onClose: () => void; onSaved: (message: string) => Promise<void> }) {
  const { me } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [jobTitle, setJobTitle] = useState(user?.job_title ?? "");
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
            job_title: jobTitle || null,
            ...(canKylas ? { kylas_user_id: kylasUserId ? Number(kylasUserId) : null } : {}),
          },
        });
        const before = [...user.roles.map((r) => r.id)].sort().join();
        if ([...roleIds].sort().join() !== before) {
          await api(`/api/users/${user.id}/roles`, { method: "PUT", json: { role_ids: roleIds } });
        }
        await onSaved(`${fullName} updated.`);
      } else {
        const created = await api<{ id: string }>("/api/users", {
          method: "POST",
          json: { email, full_name: fullName, phone: phone || null, password, role_ids: roleIds },
        });
        if (jobTitle) await api(`/api/users/${created.id}`, { method: "PATCH", json: { job_title: jobTitle } });
        await onSaved(`${fullName} added.`);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={user ? `Edit ${user.full_name}` : "Add user"} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Full name">
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus />
        </Field>
        <Field label="Email">
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Phone">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="Job title (printed on letters and bills, e.g. Assistant Manager Billing)">
          <input value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} maxLength={100} />
        </Field>
        {user && canKylas && (
          <Field label="Kylas user id (owner of the Kylas leads this person enters)">
            <input value={kylasUserId} inputMode="numeric" onChange={(e) => setKylasUserId(e.target.value.replace(/\D/g, ""))} placeholder="see python -m app.cli kylas-discover" />
          </Field>
        )}
        {!user && (
          <Field label="Password (at least 10 characters)">
            <input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
        )}
        <Field as="fieldset" label="Roles">
          <div className="checks">
            {roles.map((r) => {
              const allowed = r.can_assign ?? (!!me && canGrant(me.permissions, r.permissions));
              return (
                <label key={r.id} className={`check ${allowed ? "" : "disabled"}`} title={allowed ? (r.description ?? "") : "Only a higher role can give this role"}>
                  <input type="checkbox" checked={roleIds.includes(r.id)} disabled={!allowed && !roleIds.includes(r.id)} onChange={() => toggleRole(r.id)} />
                  {r.name}
                </label>
              );
            })}
          </div>
        </Field>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function PasswordForm({ user, onClose, onSaved }: { user: User; onClose: () => void; onSaved: (message: string) => void }) {
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
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Reset password: ${user.full_name}`} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="New password (at least 10 characters)">
          <input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </Field>
        <Field label="Repeat password">
          <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
        </Field>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Saving…" : "Reset password"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
