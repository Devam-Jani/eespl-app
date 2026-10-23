// The issue log book (Settings > Issue log: the director, the office admin, the super admin) and each
// user's own reports (staff under My work, clients in the portal).
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, queryString } from "../api";
import { useAuth } from "../auth";
import ExportButton from "../components/ExportButton";
import { errorText } from "../format";
import { pagePath, send } from "./report";

export const STATUS_LABEL: Record<string, string> = {
  new: "New",
  guided: "User mistake, guided",
  bug: "Bug",
  fixing: "Being fixed",
  fixed: "Fixed",
  wont_fix: "Will not fix",
};
export const KIND_LABEL: Record<string, string> = { error: "Error", mistake: "Wrong entry", report: "User's report", nightly: "Nightly check" };

type Issue = {
  id: number;
  kind: string;
  status: string;
  title: string;
  page: string | null;
  roles: string[];
  error: string | null;
  status_code: number | null;
  found_by: string;
  first_seen: string;
  last_seen: string;
  count: number;
  cause: string | null;
  fix: string | null;
  pr_url: string | null;
  commit: string | null;
  fixed_at: string | null;
  released_at: string | null;
};
type Event = {
  id: number;
  at: string;
  role: string | null;
  client: boolean;
  page: string | null;
  action: string | null;
  request_id: string | null;
  browser: string | null;
  status_code: number | null;
  words: string | null;
  values: Record<string, string> | null;
  found_by: string;
};
type IssueFull = Issue & { stack: string | null; events: Event[]; answers: { at: string; role: string | null; question: string; answer: string; model: string }[] };
type Weekly = { from: string; to: string; new_issues: number; times_happened: number; fixed: number; released: number; open_bugs: number; top_pages: { page: string; times: number }[] };

const when = (s: string | null) => (s ? new Date(s).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

export function StatusPill({ status }: { status: string }) {
  return <span className={`badge issue-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function IssueLog() {
  const [rows, setRows] = useState<Issue[] | null>(null);
  const [week, setWeek] = useState<Weekly | null>(null);
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Issue[]>(`/api/issues${queryString({ status, kind, q })}`).then(setRows, (e) => setError(errorText(e)));
  }, [status, kind, q]);
  useEffect(load, [load]);
  useEffect(() => {
    api<Weekly>("/api/issues/weekly").then(setWeek, () => setWeek(null));
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Issue log</h1>
        <ExportButton path="/api/issues/export.xlsx" />
      </div>
      {week && (
        <div className="kpi-grid issue-week" aria-label="This week">
          <div className="kpi kpi-link">
            <span className="kpi-label">New this week</span>
            <b className="kpi-value">{week.new_issues}</b>
          </div>
          <div className="kpi kpi-link">
            <span className="kpi-label">Times something went wrong</span>
            <b className="kpi-value">{week.times_happened}</b>
          </div>
          <div className="kpi kpi-link">
            <span className="kpi-label">Open bugs</span>
            <b className="kpi-value">{week.open_bugs}</b>
          </div>
          <div className="kpi kpi-link">
            <span className="kpi-label">Fixed / released this week</span>
            <b className="kpi-value">
              {week.fixed} / {week.released}
            </b>
          </div>
        </div>
      )}
      <div className="card filters">
        <label className="field">
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(KIND_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Search</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="error, page…" />
        </label>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {rows === null ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted">Nothing in the log book{status || kind || q ? " for this filter" : " yet"}.</p>
      ) : (
        <div className="table-wrap">
          <table className="table issue-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Problem</th>
                <th>Page</th>
                <th>Roles</th>
                <th className="num">Times</th>
                <th>First seen</th>
                <th>Last seen</th>
                <th>Found by</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td>{i.id}</td>
                  <td>
                    <Link to={`/settings/issue-log/${i.id}`}>{i.title}</Link>
                    <div className="muted small">
                      {KIND_LABEL[i.kind] ?? i.kind}
                      {i.status_code ? ` · HTTP ${i.status_code}` : ""}
                      {i.pr_url && (
                        <>
                          {" · "}
                          <a href={i.pr_url} target="_blank" rel="noreferrer">
                            pull request
                          </a>
                        </>
                      )}
                    </div>
                  </td>
                  <td className="mono small">{i.page ?? "—"}</td>
                  <td className="small">{i.roles.join(", ") || "—"}</td>
                  <td className="num">{i.count}</td>
                  <td className="small">{when(i.first_seen)}</td>
                  <td className="small">{when(i.last_seen)}</td>
                  <td className="small">{i.found_by}</td>
                  <td>
                    <StatusPill status={i.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function IssuePage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [issue, setIssue] = useState<IssueFull | null>(null);
  const [form, setForm] = useState({ status: "", cause: "", fix: "", pr_url: "", commit: "", fixed_at: "" });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const load = useCallback(() => {
    api<IssueFull>(`/api/issues/${id}`).then(
      (i) => {
        setIssue(i);
        setForm({ status: i.status, cause: i.cause ?? "", fix: i.fix ?? "", pr_url: i.pr_url ?? "", commit: i.commit ?? "", fixed_at: i.fixed_at ? i.fixed_at.slice(0, 16) : "" });
      },
      (e) => setError(errorText(e)),
    );
  }, [id]);
  useEffect(load, [load]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  async function save() {
    setError(null);
    setSaved(false);
    try {
      await api(`/api/issues/${id}`, { method: "PUT", json: { ...form, fixed_at: form.fixed_at ? new Date(form.fixed_at).toISOString() : null } });
      setSaved(true);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!issue) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const editable = can("issuelog.edit");
  const isBug = ["bug", "fixing", "fixed"].includes(form.status);
  return (
    <>
      <div className="page-header">
        <h1>
          Issue #{issue.id}: {issue.title}
        </h1>
        <StatusPill status={issue.status} />
      </div>
      <p className="muted">
        <Link to="/settings/issue-log">← Issue log</Link> · {KIND_LABEL[issue.kind] ?? issue.kind} on <span className="mono">{issue.page ?? "?"}</span> · seen {issue.count} time(s), first{" "}
        {when(issue.first_seen)}, last {when(issue.last_seen)} · roles {issue.roles.join(", ") || "—"} · found by {issue.found_by}
      </p>
      <div className="grid-2">
        <div className="card">
          <h3>What happened</h3>
          {issue.error && <pre className="issue-error">{issue.error}</pre>}
          {issue.stack && (
            <details>
              <summary>Stack (last lines)</summary>
              <pre className="issue-stack">{issue.stack}</pre>
            </details>
          )}
          {issue.answers.length > 0 && (
            <>
              <h3>The helper's answers</h3>
              {issue.answers.map((a, i) => (
                <div key={i} className="helper-answer">
                  <p className="muted small">
                    {when(a.at)} · {a.role} asked: {a.question}
                  </p>
                  <p>{a.answer}</p>
                </div>
              ))}
            </>
          )}
        </div>
        <div className="card">
          <h3>Status and fix</h3>
          <label className="field">
            <span>Status</span>
            <select value={form.status} onChange={set("status")} disabled={!editable}>
              {Object.entries(STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {isBug && (
            <>
              <label className="field">
                <span>Cause</span>
                <textarea rows={2} value={form.cause} onChange={set("cause")} disabled={!editable} />
              </label>
              <label className="field">
                <span>Fix</span>
                <textarea rows={2} value={form.fix} onChange={set("fix")} disabled={!editable} />
              </label>
              <label className="field">
                <span>Pull request link</span>
                <input value={form.pr_url} onChange={set("pr_url")} disabled={!editable} placeholder="https://github.com/owner/repo/pull/12" />
              </label>
              <label className="field">
                <span>Commit</span>
                <input value={form.commit} onChange={set("commit")} disabled={!editable} placeholder="b89a83c" className="mono" />
              </label>
              <label className="field">
                <span>Fixed at</span>
                <input type="datetime-local" value={form.fixed_at} onChange={set("fixed_at")} disabled={!editable} />
              </label>
              <p className="muted small">
                Released: {issue.released_at ? when(issue.released_at) : "not yet (marked on the deploy that carries the commit)"}
                {issue.pr_url && (
                  <>
                    {" · "}
                    <a href={issue.pr_url} target="_blank" rel="noreferrer">
                      open the pull request
                    </a>
                  </>
                )}
              </p>
            </>
          )}
          {error && <div className="alert alert-error">{error}</div>}
          {saved && <div className="alert alert-ok">Saved.</div>}
          {editable && (
            <button className="btn btn-primary" onClick={() => void save()}>
              Save
            </button>
          )}
        </div>
      </div>
      <h3>Each time ({issue.events.length})</h3>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Role</th>
              <th>Page and action</th>
              <th>Request</th>
              <th>Browser</th>
              <th>The user's words</th>
            </tr>
          </thead>
          <tbody>
            {issue.events.map((e) => (
              <tr key={e.id}>
                <td className="small">{when(e.at)}</td>
                <td className="small">
                  {e.role ?? "—"}
                  {e.client ? " (client)" : ""}
                </td>
                <td className="small">
                  <span className="mono">{e.page ?? "—"}</span>
                  {e.action && <div className="muted">{e.action}</div>}
                </td>
                <td className="mono small">{e.request_id ?? "—"}</td>
                <td className="small">{e.browser ?? "—"}</td>
                <td className="small">
                  {e.words ?? <span className="muted">—</span>}
                  {e.values && (
                    <details>
                      <summary>What they typed (sent with consent)</summary>
                      <ul>
                        {Object.entries(e.values).map(([k, v]) => (
                          <li key={k}>
                            {k}: {v}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Mine = { event_id: number; issue_id: number; at: string; page: string | null; kind: string; title: string; words: string | null; status: string; fixed_at: string | null; released_at: string | null; fix: string | null };

/** The user's own reports and where each stands; "Report a problem" for anything the app did not catch. */
export function MyReports() {
  const [rows, setRows] = useState<Mine[] | null>(null);
  const [words, setWords] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Mine[]>("/api/me/issues").then(setRows, () => setRows([]));
  }, []);
  useEffect(load, [load]);
  async function report() {
    const rec = await send({ kind: "report", page: pagePath(window.location.href), words: words.trim() }, true);
    setNote(rec ? `Thank you: it is in the issue log as #${rec.issue_id}.` : "It could not be sent just now. Try again in a minute.");
    setWords("");
    load();
  }
  return (
    <>
      <div className="page-header">
        <h1>My reports</h1>
      </div>
      <div className="card">
        <label className="field">
          <span>Report a problem</span>
          <textarea rows={3} value={words} onChange={(e) => setWords(e.target.value)} maxLength={2000} placeholder="What were you doing, and what went wrong?" />
        </label>
        <button className="btn btn-primary" disabled={!words.trim()} onClick={() => void report()}>
          Send
        </button>
        {note && <p className="helper-note">{note}</p>}
      </div>
      {rows === null ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted">You have not reported anything. When something goes wrong, the helper card's "Report this" puts it here.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>When</th>
                <th>Problem</th>
                <th>Your words</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.event_id}>
                  <td>{r.issue_id}</td>
                  <td className="small">{when(r.at)}</td>
                  <td>
                    {r.title}
                    <div className="muted small mono">{r.page ?? ""}</div>
                  </td>
                  <td className="small">{r.words ?? "—"}</td>
                  <td>
                    <StatusPill status={r.status} />
                    {r.fix && <div className="small">{r.fix}</div>}
                    {r.released_at && <div className="muted small">Live since {when(r.released_at)}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
