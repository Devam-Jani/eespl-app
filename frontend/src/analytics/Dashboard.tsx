import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";
import { MENU } from "../menu";
import { HBarChart, PALETTE } from "./charts";
import type { Drill, Tile } from "./ui";
import { asOf, DataTable, drillHref, ExportButton, fmtValue, KpiTile, useData, useFilters } from "./ui";

type Home = { dashboards: { key: string; title: string; scope: string }[]; demo_available: boolean; as_of: string | null; can_export: boolean };
type Section = { key: string; title: string; tiles: Tile[] };
type Management = {
  as_of: string | null;
  sections: Section[];
  margin: { tiles: Tile[]; lowest: { site_id: number; code: string | null; margin: number | null; billed: string; cost: string }[]; salary_included: boolean } | null;
};
type Alert = { id: number; rule_label: string; title: string; link: string | null; severity: string; created_at: string };

/** The page after login: the dashboards the user's roles give, the first one open. */
export default function Dashboard() {
  const { data: home, error, reload } = useData<Home>("/api/dashboard");
  const [params, setParams] = useSearchParams();
  const { demo, set } = useFilters();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!home) return <p className="muted">Loading…</p>;
  if (home.dashboards.length === 0) return <Modules />;
  const view = params.get("view") ?? home.dashboards[0].key;
  const current = home.dashboards.find((d) => d.key === view) ?? home.dashboards[0];

  async function refresh() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ as_of: string }>("/api/dashboard/refresh", { method: "POST" });
      setMsg(`Refreshed ${asOf(r.as_of)}.`);
      reload();
    } catch (err) {
      setMsg(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  const q = demo ? "?demo=true" : "";
  return (
    <>
      <div className="page-header">
        <div>
          <h1>{current.title}</h1>
          <p className="muted small">
            Summary tables {asOf(home.as_of)} · the worker refreshes them every night
            {demo && <span className="badge badge-warn"> DEMO company: invented data</span>}
          </p>
        </div>
        <div className="page-actions">
          {home.demo_available && (
            <label className={`check demo-switch ${demo ? "on" : ""}`}>
              <input type="checkbox" checked={demo} onChange={(e) => set("demo", e.target.checked ? "1" : "")} /> Demo company
            </label>
          )}
          <button className="btn btn-small" disabled={busy} onClick={() => void refresh()}>
            {busy ? "Refreshing…" : "↻ Refresh"}
          </button>
          <ExportButton path={`/api/dashboard/${current.key}/xlsx${q}`} />
          {current.key === "company" && home.can_export && (
            <button className="btn btn-small btn-ghost" onClick={() => void downloadFile(`/api/analytics/pdf/management${q}`).catch((err) => alert(errorText(err)))}>
              ⤓ PDF summary
            </button>
          )}
        </div>
      </div>
      {msg && <div className="alert alert-ok">{msg}</div>}
      {home.dashboards.length > 1 && (
        <div className="tabs tabs-inline dash-tabs">
          {home.dashboards.map((d) => (
            <button
              key={d.key}
              className={`tab ${d.key === current.key ? "active" : ""}`}
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("view", d.key);
                setParams(next, { replace: true });
              }}
            >
              {d.title}
            </button>
          ))}
        </div>
      )}
      <div className="top-gap">
        {current.key === "company" && <ManagementView demo={demo} />}
        {current.key === "sales" && <SalesView demo={demo} />}
        {current.key === "site" && <SiteView demo={demo} />}
        {current.key === "finance" && <AccountsView demo={demo} />}
        {current.key === "purchase" && <PurchaseView demo={demo} />}
      </div>
    </>
  );
}

function Tiles({ tiles, demo }: { tiles: Tile[]; demo: boolean }) {
  return (
    <div className="kpi-grid">
      {tiles.map((t) => (
        <KpiTile key={t.key} tile={t} demo={demo} />
      ))}
    </div>
  );
}

function ManagementView({ demo }: { demo: boolean }) {
  const navigate = useNavigate();
  const { data, error } = useData<Management>(`/api/dashboard/company${demo ? "?demo=true" : ""}`);
  const { data: alerts } = useData<{ alerts: Alert[] }>("/api/analytics/alerts");
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="dash-grid">
      <div className="dash-main">
        {data.sections.map((s) => (
          <section key={s.key} className="dash-section">
            <h2 className="section-title">{s.title}</h2>
            <Tiles tiles={s.tiles} demo={demo} />
          </section>
        ))}
        {data.margin && (
          <section className="dash-section">
            <h2 className="section-title">Margin</h2>
            <Tiles tiles={data.margin.tiles} demo={demo} />
            <h3 className="small muted top-gap">The five sites with the lowest margin</h3>
            <HBarChart
              rows={data.margin.lowest.map((r) => ({ ...r, label: r.code ?? `#${r.site_id}` }))}
              label="label"
              value="margin"
              fmt={(v) => `${v.toFixed(1)}%`}
              color={PALETTE[3]}
              note={(r) => `on ${fmtValue(r.billed, "inr")} billed`}
              onClick={(r) => navigate(`/sites/${r.site_id}`)}
            />
          </section>
        )}
      </div>
      <aside className="dash-side card">
        <div className="toolbar">
          <h2 className="section-title">Alerts</h2>
          <Link to="/alerts" className="small">
            All alerts →
          </Link>
        </div>
        {(alerts?.alerts ?? []).slice(0, 10).map((a) => (
          <Link key={a.id} to={a.link ?? "/alerts"} className={`alert-row sev-${a.severity}`}>
            <span className="small muted">{a.rule_label}</span>
            <span>{a.title}</span>
          </Link>
        ))}
        {alerts && alerts.alerts.length === 0 && <p className="muted small">No open alerts.</p>}
      </aside>
    </div>
  );
}

type FollowUp = { id: number; quotation_id: number; code: string; client_firm: string; project: string; day: number; due_on: string; overdue: boolean; salesperson: string | null };
type Sales = { scope: string; pipeline: { stage: string; kind: string; count: number; value: string }[]; tiles: Tile[]; quotation_followups: FollowUp[] };

function SalesView({ demo }: { demo: boolean }) {
  const navigate = useNavigate();
  const { data, error } = useData<Sales>(`/api/dashboard/sales${demo ? "?demo=true" : ""}`);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <Tiles tiles={data.tiles} demo={demo} />
      {!demo && <QuotationFollowUps rows={data.quotation_followups ?? []} mine={data.scope === "own"} />}
      <section className="dash-section card top-gap">
        <div className="toolbar">
          <h2 className="section-title">{data.scope === "own" ? "My pipeline" : "Pipeline"} by stage</h2>
          <Link to={`/analytics/strategy${demo ? "?demo=1" : ""}`} className="small">
            Funnel and win / loss →
          </Link>
        </div>
        <HBarChart
          rows={data.pipeline.map((p) => ({ ...p, label: p.stage.replace("_", " ") }))}
          label="label"
          value="value"
          note={(r) => `· ${r.count} ${r.kind === "lead" ? "lead(s)" : "tender(s)"}`}
          onClick={(r) =>
            navigate(
              drillHref(
                r.kind === "lead"
                  ? { kind: "leads", filter: "status", status: String(r.stage) }
                  : { kind: "tenders", filter: "status", status: String(r.stage).replace("tender ", "") },
                demo,
              ),
            )
          }
        />
      </section>
    </>
  );
}

/** Quotation follow-ups (days 2, 7, 15, 30 after sending), due this week or overdue. */
function QuotationFollowUps({ rows, mine }: { rows: FollowUp[]; mine: boolean }) {
  const overdue = rows.filter((r) => r.overdue).length;
  return (
    <section className="dash-section card top-gap followups">
      <div className="toolbar">
        <h2 className="section-title">
          {mine ? "My quotation follow-ups" : "Quotation follow-ups"} <span className="muted small">due this week{overdue ? ` · ${overdue} overdue` : ""}</span>
        </h2>
        <Link to="/quotations?followups=1" className="small">
          All quotations →
        </Link>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No follow-ups due this week.</p>
      ) : (
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Due</th>
                <th>Quotation</th>
                <th>Client · project</th>
                <th>Call</th>
                {!mine && <th>Salesperson</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.overdue ? "row-overdue" : undefined}>
                  <td>
                    {new Date(r.due_on).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} {r.overdue && <span className="badge badge-danger">overdue</span>}
                  </td>
                  <td>
                    <Link to={`/quotations/${r.quotation_id}`}>{r.code}</Link>
                  </td>
                  <td>
                    {r.client_firm} <span className="muted small">· {r.project}</span>
                  </td>
                  <td className="small">day {r.day} after sending</td>
                  {!mine && <td className="small">{r.salesperson ?? "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type SiteTodo = { key: string; label: string; done: boolean; value: number | string; link: string };

function SiteView({ demo }: { demo: boolean }) {
  const { data, error } = useData<{ sites: { site_id: number; code: string; name: string; progress: string; todos: SiteTodo[] }[] }>(
    `/api/dashboard/site${demo ? "?demo=true" : ""}`,
  );
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  if (data.sites.length === 0) return <p className="empty">No active sites assigned to you.</p>;
  return (
    <div className="site-todo-grid">
      {data.sites.map((s) => (
        <div key={s.site_id} className="card">
          <div className="toolbar">
            <Link to={`/sites/${s.site_id}`}>
              <strong>{s.code}</strong> {s.name}
            </Link>
            <span className="muted small">{Number(s.progress).toFixed(0)}% done</span>
          </div>
          <ul className="todo-list">
            {s.todos.map((t) => (
              <li key={t.key} className={t.done ? "done" : "todo"}>
                <Link to={t.link}>
                  <span className="todo-mark">{t.done ? "✓" : "!"}</span> {t.label}
                  <span className="muted small"> {String(t.value)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function AccountsView({ demo }: { demo: boolean }) {
  const navigate = useNavigate();
  const { data, error } = useData<{ as_of: string | null; ageing: { bucket: string; amount: string; drill: Drill }[]; tiles: Tile[] }>(
    `/api/dashboard/finance${demo ? "?demo=true" : ""}`,
  );
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <Tiles tiles={data.tiles} demo={demo} />
      <section className="dash-section card top-gap">
        <div className="toolbar">
          <h2 className="section-title">Receivables ageing (due part, retention excluded)</h2>
          <span className="muted small">{asOf(data.as_of)}</span>
        </div>
        <HBarChart
          rows={data.ageing.map((a) => ({ ...a, label: `${a.bucket} days` }))}
          label="label"
          value="amount"
          color={PALETTE[1]}
          onClick={(r) => navigate(drillHref(r.drill as Drill, demo))}
        />
        <p className="small">
          <Link to={`/analytics/finance${demo ? "?demo=1" : ""}`}>Cash flow, DSO and outstanding by client →</Link>
        </p>
      </section>
    </>
  );
}

function PurchaseView({ demo }: { demo: boolean }) {
  const { data, error } = useData<{
    tiles: Tile[];
    pos: { id: number; code: string; vendor: string; expected: string | null; late: boolean; link: string }[];
    low_stock: { code: string; name: string; unit: string; stock: string; reorder_level: string }[];
  }>(`/api/dashboard/purchase${demo ? "?demo=true" : ""}`);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <Tiles tiles={data.tiles} demo={demo} />
      <div className="split top-gap">
        <section className="card">
          <h2 className="section-title">POs awaiting delivery</h2>
          <ul className="plain-list">
            {data.pos.map((p) => (
              <li key={p.id} className={p.late ? "late" : undefined}>
                <Link to={p.link}>{p.code}</Link> {p.vendor} · expected {fmtValue(p.expected, "date")} {p.late && <span className="badge badge-danger">late</span>}
              </li>
            ))}
            {data.pos.length === 0 && <li className="muted">None.</li>}
          </ul>
        </section>
        <section className="card">
          <h2 className="section-title">Below reorder level</h2>
          <DataTable
            demo={demo}
            table={{
              title: "",
              note: null,
              columns: [
                { key: "name", label: "Product", unit: "text" },
                { key: "stock", label: "Stock", unit: "qty" },
                { key: "reorder_level", label: "Reorder level", unit: "qty" },
                { key: "unit", label: "Unit", unit: "text" },
              ],
              rows: data.low_stock,
            }}
          />
        </section>
      </div>
    </>
  );
}

function Modules() {
  const { me, can } = useAuth();
  const modules = MENU.filter((m) => can(...m.perms) && (m.all ?? []).every((c) => can(c)));
  return (
    <>
      <h1>Welcome, {me?.user.full_name.split(" ")[0]}</h1>
      {modules.length === 0 ? (
        <p className="muted">Your account has no modules yet. Ask an administrator to assign a role.</p>
      ) : (
        <div className="tiles">
          {modules.map((m) => (
            <Link key={m.to} to={m.to} className="tile">
              <span className="tile-title">{m.label}</span>
              <span className="muted">{m.section}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
