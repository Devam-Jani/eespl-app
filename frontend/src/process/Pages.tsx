// The process chain in the app: notifications with filters, a site's Process tab, the director's
// escalated list, Settings > Process rules and each person's channels per rule.
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { DoneButton } from "../components/DoneButton";
import { errorText } from "../format";
import { Button, buttonClass, Card, Field } from "../ui/components";

type Note = {
  id: number;
  title: string;
  lines: string[];
  link: string | null;
  site_id: number | null;
  rule: string | null;
  action: string | null;
  needs_action: boolean;
  escalated: boolean;
  note: string | null;
  read: boolean;
  created_label: string;
  waiting_hours: number | null;
  closed_label: string | null;
  closed_by: string | null;
  closed_reason: string | null;
  email: string | null;
};

const DelaysCard = lazy(() => import("../schedule/Pages").then((m) => ({ default: m.DelaysCard })));
const CostingSettingsCard = lazy(() => import("../costing/Pages").then((m) => ({ default: m.CostingSettingsCard })));

const waited = (h: number | null) => (h === null ? "" : h >= 48 ? `${Math.floor(h / 24)} d` : `${h} h`);

export function Notifications() {
  const [params, setParams] = useSearchParams();
  const filter = params.get("filter") ?? "all";
  const navigate = useNavigate();
  const [data, setData] = useState<{ items: Note[]; counts: { unread: number; act: number; escalated: number } } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<typeof data>(`/api/process/notifications?filter=${filter}`).then(setData, (e) => setError(errorText(e))), [filter]);
  useEffect(() => {
    void load();
  }, [load]);
  async function open(n: Note) {
    if (!n.read) await api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => undefined);
    if (n.link) navigate(n.link);
  }
  return (
    <>
      <div className="page-header">
        <h1>Notifications</h1>
        <div className="page-actions">
          <Link className={buttonClass({ variant: "ghost", size: "small" })} to="/my-notifications">
            My email choices
          </Link>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {[
          ["all", "All"],
          ["act", `Mine to act${data ? ` (${data.counts.act})` : ""}`],
          ["info", "Information"],
          ["escalated", `Escalated${data && data.counts.escalated ? ` (${data.counts.escalated})` : ""}`],
        ].map(([k, l]) => (
          <button key={k} className={`tab ${filter === k ? "active" : ""}`} onClick={() => setParams({ filter: k })}>
            {l}
          </button>
        ))}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div">
        {!data ? (
          <p className="muted">Loading…</p>
        ) : data.items.length === 0 ? (
          <p className="empty">Nothing here.</p>
        ) : (
          <ul className="note-list">
            {data.items.map((n) => (
              <li key={n.id} className={`note-row ${n.read ? "" : "unread"} ${n.escalated ? "sev-danger" : n.needs_action && !n.closed_label ? "sev-warn" : ""}`}>
                <button className="note-open" onClick={() => void open(n)}>
                  <b>{n.title}</b>
                  {n.lines.map((l) => (
                    <span key={l} className="note-line">
                      {l}
                    </span>
                  ))}
                  <span className="small muted">
                    {n.created_label}
                    {n.escalated && " · escalated"}
                    {n.note && ` · ${n.note}`}
                    {n.email && ` · email ${n.email}`}
                    {n.closed_label
                      ? ` · done ${n.closed_label}${n.closed_by ? ` by ${n.closed_by}` : ""}${n.closed_reason ? `: ${n.closed_reason}` : ""}`
                      : n.waiting_hours !== null
                        ? ` · waiting ${waited(n.waiting_hours)}`
                        : ""}
                  </span>
                </button>
                {n.needs_action && !n.closed_label ? (
                  <span className="note-actions">
                    <Button variant="primary" size="small" onClick={() => void open(n)}>
                      {n.action ?? "Open"}
                    </Button>
                    <DoneButton id={n.id} action={n.action} onDone={() => void load()} />
                  </span>
                ) : (
                  <span className="badge badge-muted">{n.needs_action ? "done" : "info"}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

// --- a site's Process tab -------------------------------------------------------------------------

type Step = {
  code: string;
  number: number;
  title: string;
  state: "done" | "waiting" | "not_reached";
  times: number;
  last_by: string | null;
  last_label: string | null;
  waiting_on: string | null;
  waiting_hours: number | null;
  escalated: boolean;
  reasons: { by: string | null; at: string; reason: string }[];
};

export function ProcessTab({ siteId }: { siteId: number }) {
  const [t, setT] = useState<{ site: string; current: string | null; steps: Step[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<typeof t>(`/api/process/sites/${siteId}/timeline`).then(setT, (e) => setError(errorText(e)));
  }, [siteId]);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!t) return <p className="muted">Loading…</p>;
  return (
    <Card as="div">
      <h2 className="section-title">Process: enquiry to payment</h2>
      <p className="small muted">Each step, who did it and when; the current step is highlighted with how long it has been waiting.</p>
      <ol className="timeline">
        {t.steps.map((s) => (
          <li key={s.code} className={`tl-step tl-${s.state} ${t.current === s.code ? "tl-current" : ""} ${s.escalated ? "tl-escalated" : ""}`}>
            <span className="tl-dot" aria-hidden />
            <div>
              <b>
                {s.number % 1 === 0 ? s.number : s.number.toFixed(1)}. {s.title}
              </b>
              <div className="small">
                {s.state === "not_reached" ? (
                  <span className="muted">not reached yet</span>
                ) : (
                  <>
                    {s.last_label && (
                      <span>
                        {s.last_by ?? "the app"} · {s.last_label}
                        {s.times > 1 ? ` (${s.times} times)` : ""}
                      </span>
                    )}
                    {s.state === "waiting" && (
                      <span className={s.escalated ? "text-danger" : "text-warn"}>
                        {" "}
                        · waiting on {s.waiting_on} for {waited(s.waiting_hours)}
                        {s.escalated && " · escalated"}
                      </span>
                    )}
                  </>
                )}
              </div>
              {s.reasons.map((r, i) => (
                <div key={i} className="small tl-reason">
                  Closed without the action by {r.by ?? "—"} on {r.at}: “{r.reason}”
                </div>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

// --- the director's escalated list ----------------------------------------------------------------

type Esc = {
  id: number;
  step: string;
  title: string;
  site: string | null;
  site_id: number | null;
  waiting_on: string;
  since_label: string;
  waiting_hours: number;
  level: number;
  link: string | null;
};

export function Escalated() {
  const [rows, setRows] = useState<Esc[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Esc[]>("/api/process/escalated").then(setRows, (e) => setError(errorText(e)));
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Escalated</h1>
      </div>
      <p className="muted small">Every escalated item across sites, oldest first. Each closes by itself when the action is done.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <Suspense fallback={null}>
        <DelaysCard />
      </Suspense>
      <Card as="div" className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Waiting</th>
              <th>Item</th>
              <th>Site</th>
              <th>Step</th>
              <th>Waiting on</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.id} className="row-overdue">
                <td className="nowrap">
                  <b>{waited(r.waiting_hours)}</b>
                  <div className="small muted">since {r.since_label}</div>
                </td>
                <td>{r.title}</td>
                <td className="small">{r.site_id ? <Link to={`/sites/${r.site_id}?tab=process`}>{r.site}</Link> : "—"}</td>
                <td className="small">
                  {r.step}
                  {r.level > 1 && <span className="badge badge-danger">level {r.level}</span>}
                </td>
                <td className="small">{r.waiting_on}</td>
                <td>
                  {r.link && (
                    <Link className={buttonClass({ size: "small" })} to={r.link}>
                      Open
                    </Link>
                  )}
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Nothing escalated.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- Settings > Process rules ---------------------------------------------------------------------

type Recipient = { role: string; message: string; action?: string; info?: boolean; when?: string };
type Rule = {
  code: string;
  number: number;
  event: string;
  title: string;
  recipients: Recipient[];
  escalations: { after_hours: number; to: string[] }[];
  info_only: boolean;
  email: boolean;
  is_active: boolean;
};
type PSettings = { default_users: Record<string, string>; wastage: Record<string, { min: number; max: number }>; summary_hour: number; stage_bill_days: number | null };

export function ProcessRules() {
  const { can } = useAuth();
  const edit = can("process.rules");
  const [data, setData] = useState<{ rules: Rule[]; roles: string[] } | null>(null);
  const [s, setS] = useState<PSettings | null>(null);
  const [people, setPeople] = useState<{ id: string; name: string }[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => {
    void api<{ rules: Rule[]; roles: string[] }>("/api/process/rules").then(setData, (e) => setError(errorText(e)));
    void api<PSettings>("/api/process/settings").then(setS);
  }, []);
  useEffect(() => {
    load();
    void api<{ id: string; name: string }[]>("/api/team/people").then(setPeople, () => setPeople([]));
  }, [load]);
  async function put(code: string, body: Partial<Rule>) {
    try {
      await api(`/api/process/rules/${code}`, { method: "PUT", json: body });
      setMsg("Saved (logged).");
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function saveSettings(next: PSettings) {
    try {
      setS(await api<PSettings>("/api/process/settings", { method: "PUT", json: next }));
      setMsg("Saved (logged).");
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!data || !s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <div className="page-header">
        <h1>Process rules</h1>
      </div>
      <p className="muted small">
        When one team finishes its step the next person is told, in the app and by email (our staff only), and chased if nothing happens. Information-only rules never escalate.
      </p>
      {msg && <div className="alert alert-ok">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      <Suspense fallback={null}>
        <CostingSettingsCard />
      </Suspense>
      <Card as="div" className="settings-card">
        <h2 className="section-title">Defaults</h2>
        <div className="form-grid two">
          {["planning", "billing", "accounts", "store_purchase", "estimator", "salesperson", "site_engineer", "supervisor"].map((role) => (
            <Field label={<>Default {role.replace(/_/g, " ")} (a site with nobody in the role)</>} key={role}>
              <select
                disabled={!edit}
                value={s.default_users[role] ?? ""}
                onChange={(e) => void saveSettings({ ...s, default_users: { ...s.default_users, [role]: e.target.value } })}
              >
                <option value="">{role === "planning" ? "The office admin" : "Everyone holding the role"}</option>
                {people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
          ))}
          <Field label="Stage bill limit (days): the director is told after">
            <input
              type="number"
              min={1}
              disabled={!edit}
              defaultValue={s.stage_bill_days ?? 7}
              onBlur={(e) => void saveSettings({ ...s, stage_bill_days: Number(e.target.value) })}
            />
          </Field>
          <Field label="Daily summary email at (hour, IST)">
            <input
              type="number"
              min={0}
              max={23}
              disabled={!edit}
              defaultValue={s.summary_hour}
              onBlur={(e) => void saveSettings({ ...s, summary_hour: Number(e.target.value) })}
            />
          </Field>
        </div>
        <h3 className="section-title top-gap">Wastage per application (material plans)</h3>
        <div className="wastage-grid">
          {Object.entries(s.wastage).map(([app, w]) => (
            <div key={app} className="inline-form">
              <span className="grow">{app}</span>
              <Field label={`${app} min`} bare>
                <input
                  className="input-num"
                  disabled={!edit}
                  defaultValue={w.min}
                  aria-label={`${app} min`}
                  onBlur={(e) => void saveSettings({ ...s, wastage: { ...s.wastage, [app]: { ...w, min: Number(e.target.value) } } })}
                />
              </Field>
              –
              <Field label={`${app} max`} bare>
                <input
                  className="input-num"
                  disabled={!edit}
                  defaultValue={w.max}
                  aria-label={`${app} max`}
                  onBlur={(e) => void saveSettings({ ...s, wastage: { ...s.wastage, [app]: { ...w, max: Number(e.target.value) } } })}
                />
              </Field>
              %
            </div>
          ))}
          {edit && (
            <Button
              size="small"
              onClick={() => {
                const name = prompt("Application (a word found in the place's name, e.g. podium)");
                if (name) void saveSettings({ ...s, wastage: { ...s.wastage, [name.trim().toLowerCase()]: { min: 5, max: 7 } } });
              }}
            >
              + Application
            </Button>
          )}
        </div>
      </Card>
      <Card as="div" className="table-wrap top-gap">
        <table className="table rules-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Event</th>
              <th>Who is told: the message</th>
              <th>Escalation</th>
              <th>Email</th>
              <th>On</th>
            </tr>
          </thead>
          <tbody>
            {data.rules.map((r) => (
              <tr key={r.code} className={r.is_active ? undefined : "row-muted"}>
                <td>{r.number % 1 === 0 ? r.number : r.number.toFixed(1)}</td>
                <td>
                  <b>{r.title}</b>
                  <div className="small muted">{r.event}</div>
                </td>
                <td className="small">
                  {r.recipients.map((x, i) => (
                    <div key={i} className="rule-recipient">
                      <span className="badge badge-info">{x.role.replace(/_/g, " ")}</span>
                      {x.info ? <span className="badge badge-muted">information</span> : x.action && <span className="badge badge-ok">{x.action}</span>}
                      {x.when && <span className="badge badge-warn">if {x.when}</span>} {x.message}
                    </div>
                  ))}
                  {edit && (
                    <Field label={`Add a recipient to ${r.title}`} bare>
                      <select
                        className="small"
                        value=""
                        aria-label={`Add a recipient to ${r.title}`}
                        onChange={(e) => e.target.value && void put(r.code, { recipients: [...r.recipients, { ...r.recipients[0], role: e.target.value }] })}
                      >
                        <option value="">+ another recipient…</option>
                        {data.roles.map((role) => (
                          <option key={role} value={role}>
                            {role.replace(/_/g, " ")}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                </td>
                <td className="small">
                  {r.info_only ? (
                    <span className="muted">information: never</span>
                  ) : r.escalations.length === 0 ? (
                    "none"
                  ) : (
                    r.escalations.map((e, i) => (
                      <div key={i}>
                        after{" "}
                        {edit ? (
                          <Field label={`${r.title} escalation hours`} bare>
                            <input
                              className="input-num"
                              defaultValue={e.after_hours}
                              aria-label={`${r.title} escalation hours`}
                              onBlur={(ev) =>
                                Number(ev.target.value) !== e.after_hours &&
                                void put(r.code, { escalations: r.escalations.map((x, j) => (j === i ? { ...x, after_hours: Number(ev.target.value) } : x)) })
                              }
                            />
                          </Field>
                        ) : (
                          e.after_hours
                        )}{" "}
                        h → {e.to.join(", ").replace(/_/g, " ")}
                      </div>
                    ))
                  )}
                </td>
                <td>
                  <input type="checkbox" disabled={!edit} checked={r.email} onChange={(e) => void put(r.code, { email: e.target.checked })} aria-label={`Email for ${r.title}`} />
                </td>
                <td>
                  <input type="checkbox" disabled={!edit} checked={r.is_active} onChange={(e) => void put(r.code, { is_active: e.target.checked })} aria-label={`${r.title} on`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- my channels per rule -------------------------------------------------------------------------

export function MyNotificationSettings() {
  const [rows, setRows] = useState<{ code: string; number: number; title: string; mode: string; default: string }[] | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    void api<typeof rows>("/api/process/preferences").then(setRows);
  }, []);
  async function set(code: string, mode: string) {
    await api("/api/process/preferences", { method: "PUT", json: { modes: { [code]: mode } } });
    setRows((rs) => rs?.map((r) => (r.code === code ? { ...r, mode } : r)) ?? null);
    setMsg("Saved.");
  }
  return (
    <>
      <div className="page-header">
        <h1>My notifications</h1>
      </div>
      <p className="muted small">Per step: in the app only, in the app and by email, or in one summary email at 9:00 am. Escalations always come by email.</p>
      {msg && <div className="alert alert-ok">{msg}</div>}
      <Card as="div" className="table-wrap">
        <table className="table compact">
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.code}>
                <td>{r.number % 1 === 0 ? r.number : r.number.toFixed(1)}</td>
                <td>{r.title}</td>
                <td>
                  <Field label={r.title} bare>
                    <select value={r.mode} onChange={(e) => void set(r.code, e.target.value)} aria-label={r.title}>
                      <option value="app">App only{r.default === "app" ? " (default)" : ""}</option>
                      <option value="email">App and email{r.default === "email" ? " (default)" : ""}</option>
                      <option value="summary">Daily summary email (9:00)</option>
                    </select>
                  </Field>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
