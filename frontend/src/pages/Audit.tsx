import { Fragment, useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, queryString } from "../api";
import ExportButton from "../components/ExportButton";
import type { AuditEntry } from "../types";

const PAGE_SIZE = 50;

type Filters = { user: string; entity: string; action: string; date_from: string; date_to: string };
const EMPTY: Filters = { user: "", entity: "", action: "", date_from: "", date_to: "" };

export default function Audit() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api<{ items: AuditEntry[]; total: number }>(
        `/api/audit${queryString({ ...filters, limit: PAGE_SIZE, offset })}`,
      );
      setItems(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  function apply(e: FormEvent) {
    e.preventDefault();
    setOffset(0);
    setFilters(form);
  }

  function field(key: keyof Filters) {
    return {
      value: form[key],
      onChange: (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value })),
    };
  }

  return (
    <>
      <div className="page-header">
        <h1>Audit log</h1>
        <ExportButton path={`/api/audit/export${queryString({ ...filters })}`} />
      </div>
      <form className="card filters" onSubmit={apply}>
        <label className="field">
          <span>User (email)</span>
          <input placeholder="e.g. admin@" {...field("user")} />
        </label>
        <label className="field">
          <span>Entity</span>
          <select {...field("entity")}>
            <option value="">Any</option>
            <option value="user">User</option>
            <option value="role">Role</option>
          </select>
        </label>
        <label className="field">
          <span>Action</span>
          <select {...field("action")}>
            <option value="">Any</option>
            <option value="auth">auth.* (logins)</option>
            <option value="auth.login_failed">auth.login_failed</option>
            <option value="auth.lockout">auth.lockout</option>
            <option value="user">user.*</option>
            <option value="role">role.*</option>
          </select>
        </label>
        <label className="field">
          <span>From</span>
          <input type="date" {...field("date_from")} />
        </label>
        <label className="field">
          <span>To</span>
          <input type="date" {...field("date_to")} />
        </label>
        <div className="filter-actions">
          <button className="btn btn-primary">Apply</button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setForm(EMPTY);
              setFilters(EMPTY);
              setOffset(0);
            }}
          >
            Clear
          </button>
        </div>
      </form>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>User</th>
              <th>Action</th>
              <th>Entity</th>
              <th>IP</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <Fragment key={a.id}>
                <tr>
                  <td className="nowrap">{new Date(a.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
                  <td>{a.user_email ?? <span className="muted">—</span>}</td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td>
                    {a.entity}
                    {a.entity_id && <span className="muted small"> {a.entity_id.slice(0, 8)}</span>}
                  </td>
                  <td>{a.ip ?? "—"}</td>
                  <td>
                    {(a.before || a.after) && (
                      <button className="btn btn-small" onClick={() => setOpen(open === a.id ? null : a.id)}>
                        {open === a.id ? "Hide" : "Details"}
                      </button>
                    )}
                  </td>
                </tr>
                {open === a.id && (
                  <tr className="detail-row">
                    <td colSpan={6}>
                      <div className="diff">
                        <div>
                          <div className="muted small">Before</div>
                          <pre>{a.before ? JSON.stringify(a.before, null, 2) : "—"}</pre>
                        </div>
                        <div>
                          <div className="muted small">After</div>
                          <pre>{a.after ? JSON.stringify(a.after, null, 2) : "—"}</pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {items.length === 0 && !loading && (
              <tr>
                <td colSpan={6} className="empty">
                  No entries match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted">
          {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of {total}
        </span>
        <button className="btn btn-small" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>
          Previous
        </button>
        <button
          className="btn btn-small"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>
    </>
  );
}
