import { Fragment, useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, matchPath, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, inr } from "../format";
import { MENU } from "../menu";
import { Button, Card, Field, FilePicker } from "../ui/components";

const when = (v: string | null | undefined) =>
  v
    ? new Date(v).toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const size = (b: number | null | undefined) => {
  if (b === null || b === undefined) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
};

function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (path) api<T>(path).then(setData, (e) => setError(errorText(e)));
  }, [path]);
  useEffect(load, [load]);
  return { data, setData, error, setError, load };
}

// --- set a password from a one-time link (no login) -----------------------------------------------

export function SetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [who, setWho] = useState<{ full_name: string; email: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  useEffect(() => {
    api<{ full_name: string; email: string }>(`/api/auth/password-link/${token}`).then(setWho, (e) => setError(errorText(e)));
  }, [token]);
  useEffect(() => {
    if (!pw) return setHint(null);
    const t = setTimeout(
      () =>
        void api<{ problem: string | null }>("/api/auth/password-check", {
          method: "POST",
          json: { password: pw },
        }).then(
          (r) => setHint(r.problem),
          () => undefined,
        ),
      300,
    );
    return () => clearTimeout(t);
  }, [pw]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) return setError("The two passwords are not the same");
    try {
      await api(`/api/auth/password-link/${token}`, {
        method: "POST",
        json: { password: pw },
      });
      navigate("/login", { replace: true, state: { from: "/" } });
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <div className="login-page">
      <form className="login-card" onSubmit={(e) => void submit(e)}>
        <div className="login-brand">
          <span className="brand-mark">E</span>
          <div>
            <h1>Set your password</h1>
            {who && (
              <p className="muted">
                {who.full_name} · {who.email}
              </p>
            )}
          </div>
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        {who && (
          <>
            <Field label="New password (at least 10 characters, not a common one)">
              <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required minLength={10} autoFocus />
            </Field>
            {hint && <p className="small text-warn">{hint}</p>}
            <Field label="Again">
              <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required />
            </Field>
            <Button type="submit" variant="primary" block disabled={!!hint || !pw}>
              Set the password
            </Button>
          </>
        )}
      </form>
    </div>
  );
}

// --- my account: password and two-step sign-in ---------------------------------------------------------

export function Account() {
  const { me, logout } = useAuth();
  const two = useLoad<{
    enabled: boolean;
    enabled_at: string | null;
    required: boolean;
    offered: boolean;
  }>("/api/auth/two-step");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pw, setPw] = useState({ current: "", next: "", again: "" });
  const [setup, setSetup] = useState<{
    ticket: string;
    secret: string;
    qr: string;
  } | null>(null);
  const [code, setCode] = useState("");
  const run = async (p: Promise<unknown>, ok: string) => {
    setError(null);
    setMsg(null);
    try {
      await p;
      setMsg(ok);
      two.load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    }
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>My account</h1>
          <p className="muted">
            {me?.user.full_name} · {me?.user.email}
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="grid-2">
        <Card
          as="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (pw.next !== pw.again) return setError("The two new passwords are not the same");
            void run(
              api("/api/auth/password", {
                method: "POST",
                json: { current: pw.current, new: pw.next },
              }),
              "Password changed: sign in again with the new one",
            ).then((ok) => {
              if (ok) setTimeout(() => void logout(), 1500);
            });
          }}
        >
          <h2 className="section-title">Change my password</h2>
          <p className="small muted">At least 10 characters, not a common password, not your name or email. Every session of yours ends (sign in again everywhere).</p>
          <Field label="Current password">
            <input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
          </Field>
          <Field label="New password">
            <input type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required minLength={10} />
          </Field>
          <Field label="New password again">
            <input type="password" autoComplete="new-password" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} required />
          </Field>
          <Button type="submit" variant="primary">Change the password</Button>
        </Card>
        <Card as="div">
          <h2 className="section-title">Two-step sign-in</h2>
          {two.data && (
            <>
              <p className="small">
                {two.data.enabled ? (
                  <>
                    <span className="badge badge-ok">on</span> since {when(two.data.enabled_at)}: after your password, the code from your authenticator app.
                  </>
                ) : (
                  <>
                    <span className="badge badge-muted">off</span>{" "}
                    {two.data.required ? "Your role needs it: you will set it up at your next sign-in." : "Add a code from an authenticator app to your sign-in."}
                  </>
                )}
              </p>
              {!two.data.enabled && !setup && (
                <Button
                  onClick={() =>
                    void api<{ ticket: string; secret: string; qr: string }>("/api/auth/two-step/start", { method: "POST" }).then(setSetup, (e) => setError(errorText(e)))
                  }
                >
                  Set it up
                </Button>
              )}
              {setup && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(
                      api("/api/auth/two-step/confirm", {
                        method: "POST",
                        json: { ticket: setup.ticket, code },
                      }),
                      "Two-step sign-in is on",
                    ).then((ok) => ok && (setSetup(null), setCode("")));
                  }}
                >
                  <p className="small">Scan with Google or Microsoft Authenticator, then type the code it shows.</p>
                  <img className="qr" alt="QR code for the authenticator app" src={`data:image/svg+xml;base64,${btoa(setup.qr)}`} />
                  <p className="small muted">
                    Key: <code className="secret">{setup.secret}</code>
                  </p>
                  <div className="inline-form">
                    <Field label="6-digit code" bare>
                      <input inputMode="numeric" placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} required />
                    </Field>
                    <Button type="submit" variant="primary">Turn it on</Button>
                  </div>
                </form>
              )}
              {two.data.enabled && !two.data.required && (
                <form
                  className="inline-form top-gap"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run(
                      api("/api/auth/two-step/off", {
                        method: "POST",
                        json: { code },
                      }),
                      "Two-step sign-in is off",
                    ).then((ok) => ok && setCode(""));
                  }}
                >
                  <Field label="code to turn it off" bare>
                    <input inputMode="numeric" placeholder="code to turn it off" value={code} onChange={(e) => setCode(e.target.value)} required />
                  </Field>
                  <Button type="submit">Turn it off</Button>
                </form>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  );
}

// --- Settings > Security ---------------------------------------------------------------------------------

type Sec = {
  totp_required: boolean;
  totp_roles: string[];
  idle_hours_phone: number;
  idle_hours_desktop: number;
  min_password_length: number;
  lock_after: number;
  lock_minutes: number;
  admin_unlock_after_lockouts: number;
};

export function SecuritySettings() {
  const { data, setData, error, setError } = useLoad<Sec>("/api/admin/security");
  const roles = useLoad<{ code: string; name: string }[]>("/api/roles");
  const [saved, setSaved] = useState(false);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const save = (patch: Partial<Sec>) => {
    setSaved(false);
    api<Sec>("/api/admin/security", { method: "PUT", json: patch }).then(
      (r) => (setData(r), setSaved(true)),
      (e) => setError(errorText(e)),
    );
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Security</h1>
          <p className="muted">Sign-in rules for everyone. Every change is in the audit log.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {saved && <div className="alert alert-ok">Saved</div>}
      <div className="grid-2">
        <Card as="div">
          <h2 className="section-title">Two-step sign-in</h2>
          <label className="check">
            <input type="checkbox" checked={data.totp_required} onChange={(e) => save({ totp_required: e.target.checked })} /> Required for these roles (they set it up at their
            next sign-in)
          </label>
          <div className="role-ticks">
            {(roles.data ?? [])
              .filter((r) => r.code !== "client")
              .map((r) => (
                <label key={r.code} className="check">
                  <input
                    type="checkbox"
                    checked={data.totp_roles.includes(r.code)}
                    onChange={(e) =>
                      save({
                        totp_roles: e.target.checked ? [...data.totp_roles, r.code] : data.totp_roles.filter((x) => x !== r.code),
                      })
                    }
                  />{" "}
                  {r.name}
                </label>
              ))}
          </div>
          <p className="small muted">The office admin resets a person's two-step sign-in in Users when a phone is lost.</p>
        </Card>
        <Card as="div">
          <h2 className="section-title">Sessions and passwords</h2>
          <Field label="End a session after this many hours unused on a phone">
            <input type="number" min={1} max={72} defaultValue={data.idle_hours_phone} onBlur={(e) => save({ idle_hours_phone: Number(e.target.value) })} />
          </Field>
          <Field label="…on a desktop">
            <input type="number" min={1} max={72} defaultValue={data.idle_hours_desktop} onBlur={(e) => save({ idle_hours_desktop: Number(e.target.value) })} />
          </Field>
          <p className="small muted">
            Passwords: at least {data.min_password_length} characters, not a common one. {data.lock_after} wrong passwords lock the sign-in for {data.lock_minutes} minutes; the{" "}
            {data.admin_unlock_after_lockouts}
            rd lock in a row waits for the office admin (Users &gt; Unlock). A password change ends every session.
          </p>
        </Card>
      </div>
    </>
  );
}

// --- backups and storage -----------------------------------------------------------------------------------

type Backups = {
  backup: {
    enabled: boolean;
    last_at: string | null;
    ok: boolean;
    archive: string | null;
    bytes: number | null;
    offsite: string | null;
    kept: number | null;
    removed: string[] | null;
    error: string | null;
    missed: boolean;
    retention: { daily: number; weekly: number; monthly: number };
  };
  media: {
    bytes: number;
    files: number;
    folders: { folder: string; bytes: number; files: number }[];
  };
  health: Record<string, string | string[] | null>;
};

export function BackupsPage() {
  const { data, error } = useLoad<Backups>("/api/ops/backups");
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const b = data.backup;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Backups and storage</h1>
          <p className="muted">
            Every night the database and the photos, drawings and PDFs are saved into one encrypted archive: {b.retention.daily} daily, {b.retention.weekly} weekly and{" "}
            {b.retention.monthly} monthly copies are kept, and copied off the server when a target is set.
          </p>
        </div>
      </div>
      {b.missed && <div className="alert alert-error">The last backup is missing or failed{b.error ? `: ${b.error}` : ""}. The director and the office admin have been told.</div>}
      {!b.enabled && <div className="alert alert-warn">Backups run on the server (the backup container). This copy of the app does not back itself up.</div>}
      <div className="grid-2">
        <Card as="div">
          <h2 className="section-title">The last backup</h2>
          <table className="table compact">
            <tbody>
              <tr>
                <td>When</td>
                <td>
                  <b>{when(b.last_at)}</b> {b.last_at && <span className={`badge ${b.ok ? "badge-ok" : "badge-danger"}`}>{b.ok ? "good" : "failed"}</span>}
                </td>
              </tr>
              <tr>
                <td>Archive</td>
                <td>{b.archive ?? "—"}</td>
              </tr>
              <tr>
                <td>Size</td>
                <td>{size(b.bytes)}</td>
              </tr>
              <tr>
                <td>Kept on the server</td>
                <td>{b.kept ?? "—"} archives</td>
              </tr>
              <tr>
                <td>Off-site copy</td>
                <td>{b.offsite ?? "not set (BACKUP_REMOTE in .env)"}</td>
              </tr>
            </tbody>
          </table>
        </Card>
        <Card as="div">
          <h2 className="section-title">Health</h2>
          <table className="table compact">
            <tbody>
              {(["db", "worker", "osrm", "backup"] as const).map((k) => (
                <tr key={k}>
                  <td>
                    {
                      {
                        db: "Database",
                        worker: "Background worker",
                        osrm: "Road distances (our OSRM)",
                        backup: "Nightly backup",
                      }[k]
                    }
                  </td>
                  <td>
                    <span className={`badge ${data.health[k] === "ok" ? "badge-ok" : data.health[k] ? "badge-danger" : "badge-muted"}`}>
                      {String(data.health[k] ?? "not on this copy")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <Card as="div" className="top-gap">
        <h2 className="section-title">
          Files (photos, drawings, PDFs): {size(data.media.bytes)} in {data.media.files.toLocaleString("en-IN")} files
        </h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Folder</th>
              <th className="num">Files</th>
              <th className="num">Size</th>
            </tr>
          </thead>
          <tbody>
            {data.media.folders.map((f) => (
              <tr key={f.folder}>
                <td>{f.folder}</td>
                <td className="num">{f.files.toLocaleString("en-IN")}</td>
                <td className="num">{size(f.bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- users for go-live from the Excel template ----------------------------------------------------------------

type ImportRow = {
  row: number;
  name: string;
  email: string;
  roles: string[];
  manager: string | null;
  sites: string[];
  tracked: boolean;
  travel: boolean;
  rate: string | null;
  errors: string[];
  status: string;
};

export function UserImport() {
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<{
    rows: ImportRow[];
    new: number;
    already: number;
    errors: number;
  } | null>(null);
  const [made, setMade] = useState<
    | {
        row: number;
        name: string;
        email: string;
        status: string;
        link: string | null;
      }[]
    | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const send = async (path: string) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setError(null);
    try {
      return await api<unknown>(path, { method: "POST", form });
    } catch (e) {
      setError(errorText(e));
    }
  };
  const base = typeof window !== "undefined" ? window.location.origin : "";
  return (
    <>
      <div className="page-header">
        <div>
          <h1>User import</h1>
          <p className="muted">
            Everyone for go-live from one Excel file. Every row is checked first; nothing is saved while a row has an error. Each new person gets a one-time link to set their
            password: copy and send it yourself (the app sends no email).
          </p>
        </div>
        <div className="page-actions">
          <Button onClick={() => void downloadFile("/api/ops/user-import/template.xlsx")}>
            Download the template
          </Button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div">
        <div className="inline-form">
          <FilePicker label="Choose the filled template" accept=".xlsx" onFiles={(fs) => (setFile(fs[0] ?? null), setCheck(null), setMade(null))} />
          <Button disabled={!file} onClick={() => void send("/api/ops/user-import/check").then((r) => r && setCheck(r as typeof check))}>
            Check the file
          </Button>
          <Button
            variant="primary"
            disabled={!check || check.errors > 0 || check.new === 0}
            onClick={() => void send("/api/ops/user-import/save").then((r) => r && setMade((r as { users: typeof made }).users))}
          >
            Save {check ? check.new : ""} new user(s)
          </Button>
        </div>
        {check && (
          <p className="top-gap">
            <span className="badge badge-ok">{check.new} new</span> <span className="badge badge-muted">{check.already} already users</span>{" "}
            <span className={`badge ${check.errors ? "badge-danger" : "badge-ok"}`}>{check.errors} with errors</span>
            {check.errors > 0 && <span className="small text-danger"> Fix the rows below in the file and check it again.</span>}
          </p>
        )}
      </Card>
      {check && !made && (
        <Card as="div" className="top-gap table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Row</th>
                <th>Name</th>
                <th>Email</th>
                <th>Roles</th>
                <th>Manager</th>
                <th>Sites</th>
                <th>Tracked / travel</th>
                <th>Check</th>
              </tr>
            </thead>
            <tbody>
              {check.rows.map((r) => (
                <tr key={r.row} className={r.errors.length ? "row-danger" : ""}>
                  <td>{r.row}</td>
                  <td>{r.name}</td>
                  <td className="small">{r.email}</td>
                  <td className="small">{r.roles.join(", ")}</td>
                  <td className="small">{r.manager}</td>
                  <td className="small">{r.sites.join(", ")}</td>
                  <td className="small">
                    {r.tracked ? "tracked" : "—"} / {r.travel ? (r.rate != null ? `travel ${inr(r.rate)}/km` : "travel") : "—"}
                  </td>
                  <td className="small">
                    {r.errors.length ? (
                      <span className="text-danger">{r.errors.join("; ")}</span>
                    ) : (
                      <span className={`badge ${r.status === "new" ? "badge-ok" : "badge-muted"}`}>{r.status}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {made && (
        <Card as="div" className="top-gap">
          <h2 className="section-title">Saved: the one-time links (shown once)</h2>
          <p className="small muted">Copy each link and send it to the person. It works once, for 7 days.</p>
          <table className="table compact">
            <tbody>
              {made.map((u) => (
                <tr key={u.row}>
                  <td>{u.name}</td>
                  <td className="small">{u.email}</td>
                  <td className="small">{u.link ? <code className="secret">{base + u.link}</code> : <span className="muted">{u.status}</span>}</td>
                  <td>
                    {u.link && (
                      <Button size="small" onClick={() => void navigator.clipboard?.writeText(base + u.link)}>
                        Copy
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}

// --- Settings > Roles report ------------------------------------------------------------------------------------

type RoleRow = {
  code: string;
  name: string;
  pages: Record<string, string[]>;
  actions: Record<string, { code: string; what: string; reach: string }[]>;
  never: string[];
  count: number;
};

export function RolesReport() {
  const { data, error } = useLoad<{ roles: RoleRow[] }>("/api/ops/roles-report");
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Who sees what</h1>
          <p className="muted">Each role's pages and actions in plain words, and what it never sees. Export the PDF for the director to sign before go-live.</p>
        </div>
        <div className="page-actions">
          <Button variant="primary" onClick={() => void downloadFile("/api/ops/roles-report.pdf")}>
            PDF for sign-off
          </Button>
        </div>
      </div>
      <Card as="div" className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Role</th>
              <th>Menu</th>
              <th>Never sees</th>
            </tr>
          </thead>
          <tbody>
            {data.roles.map((r) => (
              <Fragment key={r.code}>
                <tr className="clickable" onClick={() => setOpen(open === r.code ? null : r.code)}>
                  <td>
                    <b>{r.name}</b>
                    <div className="small muted">{r.count} permissions</div>
                  </td>
                  <td className="small">{Object.keys(r.pages).join(" · ") || (r.code === "client" ? "the client portal only" : "—")}</td>
                  <td className="small">{r.never.join("; ") || "—"}</td>
                </tr>
                {open === r.code && (
                  <tr>
                    <td colSpan={3}>
                      <div className="grid-2">
                        <div>
                          <h3 className="section-title">Pages</h3>
                          {Object.entries(r.pages).map(([g, items]) => (
                            <p key={g} className="small">
                              <b>{g}:</b> {items.join(", ")}
                            </p>
                          ))}
                        </div>
                        <div>
                          <h3 className="section-title">May do</h3>
                          {Object.entries(r.actions).map(([m, acts]) => (
                            <div key={m} className="small">
                              {acts.map((a) => (
                                <div key={a.code}>
                                  {a.what} <span className="muted">({a.reach})</span>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- Settings > Help ------------------------------------------------------------------------------------------------

type HelpRow = {
  page: string;
  role: string;
  title: string;
  steps: string[];
  edited: boolean;
  updated_by: string | null;
};

/** The role SOPs (docs/sop): written in the repository, read here; the "How to" of each page opens them. */
function RoleSops() {
  const { data } = useLoad<{ sops: { role: string; title: string; mine: boolean }[] }>("/api/sop");
  if (!data?.sops.length) return null;
  return (
    <Card title="Role SOPs (How to)">
      <p className="small muted">
        The full guide per role, page by page. Each person reads their own role's; the super admin and the director read all of them. The text is kept in the
        repository (docs/sop) with the app's code, so it changes with the pages; the "?" steps below are the short version you edit here.
      </p>
      <ul className="sop-list">
        {data.sops.map((s) => (
          <li key={s.role}>
            <Link to={`/help/sop?role=${encodeURIComponent(s.role)}`}>{s.title}</Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function HelpSettings() {
  const { data, error, setError, load } = useLoad<{ pages: HelpRow[] }>("/api/help/all");
  const [edit, setEdit] = useState<HelpRow | null>(null);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const label = (page: string) => MENU.find((i) => i.to === page)?.label ?? page;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Help</h1>
          <p className="muted">The "?" on each page: 3 to 6 steps, for everyone or for one role. Your text replaces the default; Reset brings the default back.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <RoleSops />
      <Card as="div" className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Page</th>
              <th>For</th>
              <th>How-to</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.pages.map((h) => (
              <tr key={`${h.page}|${h.role}`}>
                <td>
                  {label(h.page)}
                  <div className="small muted">{h.page}</div>
                </td>
                <td className="small">{h.role || "everyone"}</td>
                <td className="small">
                  <b>{h.title}</b> · {h.steps.length} steps {h.edited && <span className="badge badge-info">edited{h.updated_by ? ` by ${h.updated_by}` : ""}</span>}
                </td>
                <td className="nowrap">
                  <Button size="small" onClick={() => setEdit({ ...h, steps: [...h.steps] })}>
                    Edit
                  </Button>{" "}
                  {h.edited && (
                    <Button
                      variant="ghost" size="small"
                      onClick={() =>
                        void api(`/api/help?page=${encodeURIComponent(h.page)}&role=${encodeURIComponent(h.role)}`, { method: "DELETE" }).then(load, (e) => setError(errorText(e)))
                      }
                    >
                      Reset
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {edit && (
        <Card
          as="form" className="top-gap"
          onSubmit={(e) => {
            e.preventDefault();
            void api("/api/help", {
              method: "PUT",
              json: {
                page: edit.page,
                role: edit.role,
                title: edit.title,
                steps: edit.steps.filter((s) => s.trim()),
              },
            }).then(
              () => (setEdit(null), load()),
              (e2) => setError(errorText(e2)),
            );
          }}
        >
          <h2 className="section-title">
            {label(edit.page)} · {edit.role || "everyone"}
          </h2>
          <Field label="Title">
            <input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} required />
          </Field>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Field label={<>Step {i + 1}</>} key={i}>
              <input
                value={edit.steps[i] ?? ""}
                onChange={(e) =>
                  setEdit({
                    ...edit,
                    steps: Object.assign([...edit.steps], {
                      [i]: e.target.value,
                    }),
                  })
                }
                required={i < 3}
              />
            </Field>
          ))}
          <div className="inline-form">
            <Button type="submit" variant="primary">Save</Button>
            <Button type="button" variant="ghost" onClick={() => setEdit(null)}>
              Cancel
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}

// --- in the layout: the go-live banner, the training banner and switch, the page's "?" ------------------------------

/** The roles that set the company up for go-live: only they see what is still missing. */
export const GO_LIVE_ROLES = ["director", "office_admin", "super_admin"];
export function showsGoLive(roleCodes: string[]): boolean {
  return roleCodes.some((r) => GO_LIVE_ROLES.includes(r));
}
const HIDE_KEY = (uid: string) => `eespl.golive.hidden.${uid}`;
const todayKey = () => new Date().toLocaleDateString("en-CA");

export function GoLiveBanner() {
  const { me } = useAuth();
  const roles = me?.roles.map((r) => r.code) ?? [];
  const uid = me?.user.id ?? "";
  const [missing, setMissing] = useState<{ key: string; what: string; where: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(HIDE_KEY(uid)) === todayKey();
    } catch {
      return false;
    }
  });
  const shows = showsGoLive(roles);
  useEffect(() => {
    if (!shows || hidden) return;
    api<{ missing: typeof missing }>("/api/ops/go-live-checks").then(
      (r) => setMissing(r.missing),
      () => setMissing([]),
    );
  }, [shows, hidden]);
  if (!shows || hidden || !missing.length) return null;
  return (
    <div className="golive-banner" role="status">
      <div className="golive-line">
        <b>
          <span className="golive-long">Not set yet for go-live:</span>
          <span className="golive-short">Go-live:</span>
        </b>
        <span className="golive-count">
          {missing.length} {missing.length === 1 ? "setting" : "settings"}
        </span>
        <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide the list" : "Show what's missing"}
        </button>
        <button
          type="button"
          className="link-button golive-hide"
          onClick={() => {
            setHidden(true);
            try {
              window.localStorage.setItem(HIDE_KEY(uid), todayKey());
            } catch {
              // storage blocked: hidden until the page reloads
            }
          }}
        >
          <span className="golive-long">Hide for today</span>
          <span className="golive-short">Hide today</span>
        </button>
      </div>
      {open && (
        <ul className="golive-list">
          {missing.map((m) => (
            <li key={m.key}>
              <Link to={m.where}>{m.what}</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type Mode = {
  training: boolean;
  main_url: string | null;
  training_url: string | null;
};

export function useMode(): Mode | null {
  const [mode, setMode] = useState<Mode | null>(null);
  useEffect(() => {
    api<Mode>("/api/ops/mode").then(setMode, () => setMode(null));
  }, []);
  return mode;
}

export function TrainingBanner({ mode }: { mode: Mode | null }) {
  if (!mode?.training) return null;
  return (
    <div className="training-banner" role="status">
      TRAINING: practice data, rebuilt every night. Nothing here is real or reaches a client.
      {mode.main_url && (
        <a href={mode.main_url} className="training-switch">
          Back to the real app
        </a>
      )}
    </div>
  );
}

/** The "?" of the page open: its how-to for the person's role. */
export function HelpButton() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [help, setHelp] = useState<{
    title: string;
    steps: string[];
    role: string;
  } | null>(null);
  const page = helpPage(location.pathname);
  useEffect(() => {
    setOpen(false);
    setHelp(null);
    if (!page) return;
    api<{ help: { title: string; steps: string[]; role: string } | null }>(`/api/help?page=${encodeURIComponent(page)}`).then(
      (r) => setHelp(r.help),
      () => setHelp(null),
    );
  }, [page]);
  if (!help) return null;
  return (
    <>
      <Button variant="ghost" className="help-button" aria-label="Help for this page" aria-expanded={open} onClick={() => setOpen(!open)}>
        ?
      </Button>
      {open && (
        <div className="help-panel" role="dialog" aria-label="How to use this page">
          <div className="help-head">
            <b>{help.title}</b>
            <Button variant="ghost" size="small" onClick={() => setOpen(false)} aria-label="Close">
              ×
            </Button>
          </div>
          <ol>
            {help.steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {help.role && <p className="small muted">For your role.</p>}
        </div>
      )}
    </>
  );
}

const DETAIL = ["/sites/:id", "/tenders/:id", "/quotations/:id", "/bills/:id", "/work-orders/:id", "/sites/:id/measurements"];

/** The help key of a path: the menu page it is, or the detail page's pattern. */
export function helpPage(path: string): string | null {
  const exact = MENU.find((i) => i.to === path);
  if (exact) return exact.to;
  const detail = DETAIL.find((p) => matchPath(p, path));
  if (detail) return detail === "/sites/:id" || detail === "/sites/:id/measurements" ? (detail === "/sites/:id" ? "/sites" : "/measurements") : detail.replace("/:id", "");
  return null;
}
