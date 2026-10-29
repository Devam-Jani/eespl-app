import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, inrCompact, showError } from "../format";
import { BarChart, FunnelChart, HBarChart, LineChart, PALETTE, ScatterChart } from "./charts";
import type { Row } from "./charts";
import type { Column, Drill, Table } from "./ui";
import { asOf, DataTable, drillHref, ExportButton, FilterBar, fmtValue, useData, useFilters } from "./ui";
import { Button, Card, Field } from "../ui/components";

type PageData = { as_of: string | null; tables: Record<string, Table>; summary?: Record<string, number | null>; cost_shown?: boolean; salary_included?: boolean };

function Header({ title, page, note }: { title: string; page: string; note?: string }) {
  const { qs } = useFilters();
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {note && <p className="muted small">{note}</p>}
      </div>
      <div className="page-actions">
        <ExportButton path={`/api/analytics/${page}?format=xlsx${qs ? `&${qs}` : ""}`} />
      </div>
    </div>
  );
}

function usePage(page: string) {
  const { qs } = useFilters();
  return useData<PageData>(`/api/analytics/pages/${page}${qs ? `?${qs}` : ""}`);
}

function ChartCard({ title, children, extra }: { title: string; children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <Card className="chart-card">
      <div className="toolbar">
        <h2 className="section-title">{title}</h2>
        {extra}
      </div>
      {children}
    </Card>
  );
}

function Loading({ error }: { error: string | null }) {
  return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
}

// --- sites ---------------------------------------------------------------------------------------

export function SitesAnalytics() {
  const { data, error } = usePage("sites");
  const { demo } = useFilters();
  const navigate = useNavigate();
  return (
    <>
      <Header title="Sites analytics" page="pages/sites" note="Progress against time, forecast end dates, where work gets stuck, snags." />
      <FilterBar show={["region", "salesperson", "client_type", "site_status"]} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <p className="muted small">
            {data.summary?.sites} sites · {data.summary?.delayed} delayed · {data.summary?.open_snags} open snags · snags take {data.summary?.avg_close_days ?? "—"} days to close
            on average · {asOf(data.as_of)}
          </p>
          <div className="analytics-grid">
            <ChartCard title={data.tables.scatter.title}>
              <ScatterChart
                rows={data.tables.scatter.rows as Row[]}
                x="elapsed"
                y="progress"
                label="code"
                flag="delayed"
                threshold={Number(data.summary?.threshold ?? 15)}
                onClick={(r) => navigate(String(r.link))}
              />
            </ChartCard>
            <ChartCard title={data.tables.bottlenecks.title}>
              <HBarChart
                rows={data.tables.bottlenecks.rows as Row[]}
                label="step"
                value="avg_days"
                fmt={(v) => `${v.toFixed(0)} d`}
                color={PALETTE[1]}
                note={(r) => `· ${r.open} open on ${r.sites} site(s)`}
                onClick={(r) => navigate(drillHref(r.drill as Drill, demo))}
              />
            </ChartCard>
          </div>
          <ChartCard title={data.tables.forecast.title}>
            <DataTable table={data.tables.forecast} demo={demo} limit={15} />
          </ChartCard>
          <ChartCard title={data.tables.snags.title}>
            <DataTable table={data.tables.snags} demo={demo} limit={10} />
          </ChartCard>
        </>
      )}
    </>
  );
}

// --- finance -------------------------------------------------------------------------------------

export function FinanceAnalytics() {
  const { data, error } = usePage("finance");
  const { demo } = useFilters();
  const navigate = useNavigate();
  return (
    <>
      <Header title="Finance analytics" page="pages/finance" note="Billing, money in and cost by month; the next 8 weeks of cash; DSO; who owes what." />
      <FilterBar show={["dates"]} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <ChartCard title={data.tables.monthly.title} extra={<span className="muted small">{asOf(data.as_of)}</span>}>
            <BarChart
              rows={data.tables.monthly.rows as Row[]}
              x="label"
              series={[
                { key: "billed", label: "Billed (net of GST)", color: PALETTE[0] },
                { key: "received", label: "Received", color: PALETTE[2] },
                ...(data.cost_shown ? [{ key: "cost", label: "Cost", color: PALETTE[3], kind: "line" as const }] : []),
              ]}
              onClick={(r) => navigate(drillHref(r.drill as Drill, demo))}
            />
          </ChartCard>
          <div className="analytics-grid">
            <ChartCard title={data.tables.cashflow.title}>
              <BarChart
                rows={data.tables.cashflow.rows as Row[]}
                x="label"
                series={[
                  { key: "receipts", label: "Expected receipts", color: PALETTE[2] },
                  { key: "payments", label: "Supplier payments", color: PALETTE[3] },
                ]}
                height={230}
              />
              <p className="muted small">{data.tables.cashflow.note}</p>
            </ChartCard>
            <ChartCard title={data.tables.dso.title}>
              <LineChart rows={data.tables.dso.rows as Row[]} x="label" series={[{ key: "dso", label: "DSO (days)", color: PALETTE[4] }]} />
              <p className="muted small">{data.tables.dso.note}</p>
            </ChartCard>
          </div>
          <ChartCard title={data.tables.clients.title}>
            <HBarChart rows={(data.tables.clients.rows as Row[]).slice(0, 12)} label="client" value="outstanding" onClick={(r) => navigate(drillHref(r.drill as Drill, demo))} />
            <DataTable table={data.tables.clients} demo={demo} limit={10} />
          </ChartCard>
        </>
      )}
    </>
  );
}

// --- profitability -------------------------------------------------------------------------------

export function ProfitabilityAnalytics() {
  const { data, error } = usePage("profitability");
  const { demo } = useFilters();
  return (
    <>
      <Header title="Profitability" page="pages/profitability" note="Margin = (billed − cost) / billed, before GST. Needs tender.margin." />
      <FilterBar show={["region", "salesperson", "client_type", "site_status"]} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          {!data.salary_included && <div className="alert alert-warn">Staff salary is not included in cost (needs payroll.view).</div>}
          <div className="analytics-grid">
            {(["clients", "systems", "salespeople"] as const).map((k) => (
              <ChartCard key={k} title={data.tables[k].title}>
                <HBarChart
                  rows={(data.tables[k].rows as Row[]).slice(0, 10)}
                  label="key"
                  value="margin"
                  fmt={(v) => `${v.toFixed(1)}%`}
                  color={PALETTE[2]}
                  note={(r) => `on ${fmtValue(r.billed, "inr")}`}
                />
              </ChartCard>
            ))}
          </div>
          <ChartCard title={data.tables.sites.title}>
            <DataTable table={data.tables.sites} demo={demo} limit={15} />
          </ChartCard>
          <ChartCard title={data.tables.quoted_vs_actual.title}>
            <BarChart
              rows={(data.tables.quoted_vs_actual.rows as Row[]).slice(0, 20)}
              x="code"
              series={[
                { key: "quoted_margin", label: "Quoted margin %", color: PALETTE[5] },
                { key: "actual_margin", label: "Actual margin %", color: PALETTE[3] },
              ]}
              fmt={(v) => `${v.toFixed(0)}%`}
            />
            <DataTable table={data.tables.quoted_vs_actual} demo={demo} limit={10} />
          </ChartCard>
        </>
      )}
    </>
  );
}

// --- purchase ------------------------------------------------------------------------------------

export function PurchaseAnalytics() {
  const { data, error } = usePage("purchase");
  const { demo } = useFilters();
  const [product, setProduct] = useState(0);
  return (
    <>
      <Header title="Purchase analytics" page="pages/purchase" note="Spend from approved POs (before GST); price trend of the top products; freight against material used." />
      <FilterBar show={["dates", "region", "site_status"]} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <div className="analytics-grid">
            <ChartCard title={data.tables.vendors.title}>
              <HBarChart rows={(data.tables.vendors.rows as Row[]).slice(0, 12)} label="vendor" value="spend" />
            </ChartCard>
            <ChartCard title={data.tables.categories.title}>
              <HBarChart rows={data.tables.categories.rows as Row[]} label="category" value="spend" color={PALETTE[1]} />
            </ChartCard>
          </div>
          <ChartCard
            title={data.tables.prices.title}
            extra={
              <Field label="Product" bare>
                <select value={product} onChange={(e) => setProduct(Number(e.target.value))} aria-label="Product">
                  {(data.tables.prices.rows as Row[]).map((r, i) => (
                    <option key={i} value={i}>
                      {String(r.product)}
                    </option>
                  ))}
                </select>
              </Field>
            }
          >
            {data.tables.prices.rows[product] ? (
              <LineChart
                rows={data.tables.prices.columns.slice(3).map((c: Column) => ({ label: c.label, rate: data.tables.prices.rows[product][c.key] }))}
                x="label"
                series={[{ key: "rate", label: `₹ per ${String(data.tables.prices.rows[product].unit)}`, color: PALETTE[0] }]}
                fmt={inrCompact}
              />
            ) : (
              <p className="muted">No POs in this range.</p>
            )}
          </ChartCard>
          <ChartCard title={data.tables.freight.title}>
            <DataTable table={data.tables.freight} demo={demo} limit={12} />
          </ChartCard>
        </>
      )}
    </>
  );
}

// --- labour --------------------------------------------------------------------------------------

export function LabourAnalytics() {
  const { data, error } = usePage("labour");
  const { demo } = useFilters();
  return (
    <>
      <Header title="Labour analytics" page="pages/labour" note="From the muster roll (attendance) and measured progress." />
      <FilterBar show={["dates", "region", "site_status"]} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <ChartCard title={data.tables.monthly.title}>
            <BarChart rows={data.tables.monthly.rows as Row[]} x="label" series={[{ key: "man_days", label: "Man-days", color: PALETTE[0] }]} fmt={(v) => v.toFixed(0)} />
          </ChartCard>
          <div className="analytics-grid">
            <ChartCard title={data.tables.attendance.title}>
              <HBarChart rows={data.tables.attendance.rows as Row[]} label="code" value="rate" fmt={(v) => `${v.toFixed(1)}%`} scale={100} color={PALETTE[2]} />
            </ChartCard>
            <ChartCard title={data.tables.per_sqm.title}>
              <HBarChart rows={(data.tables.per_sqm.rows as Row[]).slice(0, 15)} label="code" value="per_sqm" fmt={inrCompact} color={PALETTE[1]} />
              <p className="muted small">{data.tables.per_sqm.note}</p>
            </ChartCard>
          </div>
          <ChartCard title={data.tables.man_days.title}>
            <DataTable table={data.tables.man_days} demo={demo} limit={15} />
          </ChartCard>
        </>
      )}
    </>
  );
}

// --- strategy ------------------------------------------------------------------------------------

type Step = { step: string; label: string; count: number; value: string; conversion: number | null };
type Funnel = {
  basis: string;
  total: { steps: Step[]; lost: { count: number; value: string }; win_rate: number | null };
  groups: { key: string; steps: Step[]; win_rate: number | null }[];
};
type Segment = { key: string; won: number; lost: number; win_rate: number | null; won_value: string };
type WinLoss = {
  basis: string;
  decided: number;
  won: number;
  win_rate: number | null;
  segments: Record<string, Segment[]>;
  lost_reasons: { reason: string; tenders: number; value: string; leads: number }[];
  competitors: { name: string; count: number }[];
};
type Pricing = { systems: { system: string; won: { lines: number; median_ratio: number | null }; lost: { lines: number; median_ratio: number | null } }[]; note: string };
type Repeat = {
  billed_total: string;
  billed_repeat: string;
  repeat_share: number | null;
  repeat_clients: number;
  top: { client_id: number; name: string; billed: string; repeat: boolean; drill: Drill }[];
  quiet: { client_id: number; name: string; type: string; last_enquiry: string | null; sites: number; billed: string }[];
};
type Historic = Record<string, number | string>;

const DIMS: [string, string][] = [
  ["", "Total"],
  ["month", "Month"],
  ["salesperson", "Salesperson"],
  ["client_type", "Client type"],
  ["source", "Source"],
  ["region", "Region"],
];

export function StrategyAnalytics() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "funnel";
  const { can } = useAuth();
  const tabs = [["funnel", "Tender funnel"], ["winloss", "Win / loss"], ["pricing", "Pricing position"], ...(can("dashboard.company") ? [["repeat", "Repeat clients"]] : [])];
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Strategy</h1>
          <p className="muted small">To win more sites: where tenders drop out, why we lose, how our prices sit, who to call.</p>
        </div>
      </div>
      <div className="tabs tabs-inline dash-tabs">
        {tabs.map(([k, l]) => (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("tab", k);
              setParams(next, { replace: true });
            }}
          >
            {l}
          </button>
        ))}
      </div>
      <FilterBar show={["dates", "region", "salesperson", "client_type"]} />
      {tab === "funnel" && <FunnelTab />}
      {tab === "winloss" && <WinLossTab />}
      {tab === "pricing" && <PricingTab />}
      {tab === "repeat" && <RepeatTab />}
      <HistoricNote />
    </>
  );
}

function FunnelTab() {
  const { qs, demo } = useFilters();
  const [params, setParams] = useSearchParams();
  const dim = params.get("by") ?? "";
  const { data, error } = useData<Funnel>(`/api/analytics/strategy/funnel?${qs}${dim ? `&group_by=${dim}` : ""}`);
  const navigate = useNavigate();
  const open = (step: string, extra: Record<string, string> = {}) => {
    const status = step === "won" ? { status: "won" } : step === "submitted" ? { submitted: "True" } : {};
    navigate(drillHref({ kind: step === "leads" ? "leads" : "tenders", filter: "segment", ...status, ...extra }, demo));
  };
  if (!data) return <Loading error={error} />;
  return (
    <>
      <div className="analytics-grid">
        <ChartCard title="Leads → tenders → submitted → won" extra={<ExportButton path={`/api/analytics/strategy/funnel?format=xlsx&${qs}${dim ? `&group_by=${dim}` : ""}`} />}>
          <FunnelChart steps={data.total.steps.map((s) => ({ ...s, value: Number(s.value) }))} onClick={(s) => open(s)} />
          <p className="small">
            Lost: <b>{data.total.lost.count}</b> ({fmtValue(data.total.lost.value, "inr")}) · win rate <b>{fmtValue(data.total.win_rate, "pct")}</b> (won ÷ won + lost)
          </p>
          <p className="muted small basis">{data.basis}</p>
        </ChartCard>
        <ChartCard
          title="By segment"
          extra={
            <Field label="Segment" bare>
              <select
                value={dim}
                onChange={(e) => {
                  const next = new URLSearchParams(params);
                  if (e.target.value) next.set("by", e.target.value);
                  else next.delete("by");
                  setParams(next, { replace: true });
                }}
              >
                {DIMS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          }
        >
          {dim ? (
            <div className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>{DIMS.find((d) => d[0] === dim)?.[1]}</th>
                    <th className="num">Leads</th>
                    <th className="num">Tenders</th>
                    <th className="num">Submitted</th>
                    <th className="num">Won</th>
                    <th className="num">Win rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.groups.map((g) => (
                    <tr key={g.key}>
                      <td>{g.key}</td>
                      {g.steps.map((s) => (
                        <td key={s.step} className="num">
                          <button className="as-button" onClick={() => open(s.step, { [dim]: g.key })}>
                            {s.count}
                          </button>
                          {s.conversion !== null && <span className="muted small"> {s.conversion}%</span>}
                        </td>
                      ))}
                      <td className="num">{fmtValue(g.win_rate, "pct")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">Pick a segment: month, salesperson, client type, source or region.</p>
          )}
        </ChartCard>
      </div>
    </>
  );
}

const SEG_LABEL: Record<string, string> = { client_type: "Client type", band: "Project size", system: "Waterproofing system", region: "Region", salesperson: "Salesperson" };

function WinLossTab() {
  const { qs, demo } = useFilters();
  const { data, error } = useData<WinLoss>(`/api/analytics/strategy/winloss?${qs}`);
  const navigate = useNavigate();
  if (!data) return <Loading error={error} />;
  return (
    <>
      <p className="small">
        {data.decided} tenders decided in the range · {data.won} won · win rate <b>{fmtValue(data.win_rate, "pct")}</b>
        <span className="push-left">
          <ExportButton path={`/api/analytics/strategy/winloss?format=xlsx&${qs}`} />
        </span>
      </p>
      <p className="muted small basis">{data.basis}</p>
      <div className="analytics-grid">
        {Object.entries(data.segments).map(([dim, rows]) => (
          <ChartCard key={dim} title={`Win rate by ${SEG_LABEL[dim]?.toLowerCase() ?? dim}`}>
            <HBarChart
              rows={rows as unknown as Row[]}
              label="key"
              value="win_rate"
              fmt={(v) => `${v.toFixed(0)}%`}
              scale={100}
              color={PALETTE[2]}
              note={(r) => `${r.won} won / ${r.lost} lost`}
              onClick={(r) => navigate(drillHref({ kind: "tenders", filter: "segment", [dim]: String(r.key) }, demo, "&decided=1"))}
            />
          </ChartCard>
        ))}
        <ChartCard title="Why we lose">
          <HBarChart
            rows={data.lost_reasons.filter((r) => r.tenders || r.leads) as unknown as Row[]}
            label="reason"
            value="tenders"
            fmt={(v) => `${v.toFixed(0)}`}
            color={PALETTE[3]}
            note={(r) => `tenders (${fmtValue(r.value, "inr")}) · ${r.leads} leads`}
            onClick={(r) => navigate(drillHref({ kind: "tenders", filter: "segment", status: "lost", lost_reason: String(r.reason) }, demo, "&decided=1"))}
          />
          {data.competitors.length > 0 && <p className="small top-gap">Lost to: {data.competitors.map((c) => `${c.name} (${c.count})`).join(", ")}</p>}
        </ChartCard>
      </div>
    </>
  );
}

function PricingTab() {
  const { qs } = useFilters();
  const { data, error } = useData<Pricing>(`/api/analytics/strategy/pricing?${qs}`);
  if (!data) return <Loading error={error} />;
  const rows = data.systems.map((s) => ({ system: s.system, won: s.won.median_ratio, lost: s.lost.median_ratio, n: `${s.won.lines} / ${s.lost.lines}` }));
  return (
    <ChartCard title="Our quoted rate ÷ rate-library median, won vs lost" extra={<ExportButton path={`/api/analytics/strategy/pricing?format=xlsx&${qs}`} />}>
      <BarChart
        rows={rows}
        x="system"
        series={[
          { key: "won", label: "Won tenders", color: PALETTE[2] },
          { key: "lost", label: "Lost tenders", color: PALETTE[3] },
        ]}
        fmt={(v) => v.toFixed(2)}
      />
      <p className="muted small">
        {data.note} Above 1.00: we quoted above the median. Lines counted (won / lost): {rows.map((r) => `${r.system} ${r.n}`).join(" · ")}.
      </p>
    </ChartCard>
  );
}

function RepeatTab() {
  const { qs, demo } = useFilters();
  const { data, error } = useData<Repeat>(`/api/analytics/strategy/repeat?${qs}`);
  const navigate = useNavigate();
  if (!data) return <Loading error={error} />;
  return (
    <>
      <p className="small">
        Billed in the range: <b>{fmtValue(data.billed_total, "inr")}</b>, of which repeat clients (two or more sites or won tenders): <b>{fmtValue(data.billed_repeat, "inr")}</b> ={" "}
        <b>{fmtValue(data.repeat_share, "pct")}</b> · {data.repeat_clients} repeat clients
        <span className="push-left">
          <ExportButton path={`/api/analytics/strategy/repeat?format=xlsx&${qs}`} />
        </span>
      </p>
      <div className="analytics-grid">
        <ChartCard title="Top 10 clients by billed value">
          <HBarChart
            rows={data.top.map((t) => ({ ...t, label: `${t.name}${t.repeat ? " ↻" : ""}` })) as unknown as Row[]}
            label="label"
            value="billed"
            onClick={(r) => navigate(drillHref(r.drill as Drill, demo))}
          />
          <p className="muted small">↻ repeat client</p>
        </ChartCard>
        <ChartCard title="No enquiry in 12 months: worth a call">
          <DataTable
            demo={demo}
            limit={12}
            table={{
              title: "",
              note: "Past customers (a site or a won tender) with no lead or tender in the last 12 months.",
              columns: [
                { key: "name", label: "Client", unit: "text" },
                { key: "type", label: "Type", unit: "text" },
                { key: "sites", label: "Sites", unit: "count" },
                { key: "last_enquiry", label: "Last enquiry", unit: "date" },
              ],
              rows: data.quiet,
            }}
          />
        </ChartCard>
      </div>
    </>
  );
}

function HistoricNote() {
  const { data } = useData<Historic>("/api/analytics/strategy/historic");
  if (!data) return null;
  return (
    <p className="muted small top-gap">
      Historic data in the app: {data.powerplay_sites} imported Powerplay sites (labelled historic; progress and dates, no billing), {data.library_lines} rate-library lines from{" "}
      {data.library_files} past BOQ files ({data.library_items_with_median} items with a median rate, used by the pricing position), {data.tenders} tenders ({data.tenders_decided}{" "}
      won or lost). {String(data.note)}
    </p>
  );
}

// --- drill-down ----------------------------------------------------------------------------------

export function DrillPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const q = params.toString();
  const { data, error } = useData<{ title: string; columns: Column[]; rows: Record<string, unknown>[]; total: number }>(`/api/analytics/drill?${q}`);
  const demo = params.get("demo") === "1" || params.get("demo") === "true";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="breadcrumb">
            <button className="as-button" onClick={() => navigate(-1)}>
              ← Back
            </button>
          </p>
          <h1>{data?.title ?? "Records"}</h1>
          {data && (
            <p className="muted small">
              {data.total} record(s){demo && <span className="badge badge-warn"> DEMO company</span>}
            </p>
          )}
        </div>
        <div className="page-actions">
          <ExportButton path={`/api/analytics/drill?${q}&format=xlsx`} />
        </div>
      </div>
      {!data ? <Loading error={error} /> : <DataTable table={{ title: data.title, columns: data.columns, rows: data.rows, note: null }} demo={demo} />}
    </>
  );
}

// --- alerts --------------------------------------------------------------------------------------

type AlertRow = {
  id: number;
  rule: string;
  rule_label: string;
  title: string;
  link: string | null;
  severity: string;
  day: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
};

export function AlertsPage() {
  const [rule, setRule] = useState("");
  const [state, setState] = useState("open");
  const { data, error, reload } = useData<{ alerts: AlertRow[]; rules: Record<string, string>; run_at: string | null }>(
    `/api/analytics/alerts?state=${state}${rule ? `&rule=${rule}` : ""}`,
  );
  const { can } = useAuth();
  const [msg, setMsg] = useState<string | null>(null);
  async function ack(id: number) {
    try {
      await api(`/api/analytics/alerts/${id}/ack`, { method: "POST" });
      reload();
    } catch (err) {
      setMsg(errorText(err));
    }
  }
  async function runNow() {
    try {
      const r = await api<{ raised: Record<string, number> }>("/api/analytics/alerts/run", { method: "POST" });
      setMsg(`Checked: ${Object.values(r.raised).reduce((a, b) => a + b, 0)} new alert(s).`);
      reload();
    } catch (err) {
      setMsg(errorText(err));
    }
  }
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Alerts</h1>
          <p className="muted small">
            Checked every hour by the worker{data?.run_at ? `; last ${asOf(data.run_at).replace("as of ", "")}` : ""}. Each item once a day; acknowledged items rest for a week.
          </p>
        </div>
        {can("dashboard.company") && (
          <div className="page-actions">
            <Button size="small" onClick={() => void runNow()}>
              Check now
            </Button>
          </div>
        )}
      </div>
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="filters">
        <Field label="State" bare>
          <select value={state} onChange={(e) => setState(e.target.value)} aria-label="State">
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="all">All</option>
          </select>
        </Field>
        <Field label="Rule" bare>
          <select value={rule} onChange={(e) => setRule(e.target.value)} aria-label="Rule">
            <option value="">All rules</option>
            {Object.entries(data?.rules ?? {}).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {!data ? (
        <Loading error={error} />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {data.alerts.map((a) => (
                <tr key={a.id} className={`sev-${a.severity}`}>
                  <td className="nowrap small">{fmtValue(a.day, "date")}</td>
                  <td>
                    <div className="small muted">{a.rule_label}</div>
                    {a.link ? <Link to={a.link}>{a.title}</Link> : a.title}
                  </td>
                  <td className="row-actions">
                    {a.acknowledged_at ? (
                      <span className="small muted">acknowledged by {a.acknowledged_by}</span>
                    ) : (
                      <Button size="small" onClick={() => void ack(a.id)}>
                        Acknowledge
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {data.alerts.length === 0 && (
                <tr>
                  <td className="empty">No alerts.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// --- reports -------------------------------------------------------------------------------------

/** What "File this week's now" says: filed, or already filed this week (the API files once a week). */
export function weeklyNotice(r: { created: boolean }): string {
  return r.created ? "This week's summary is filed: it is at the top of the list." : "This week's summary is already filed: it is in the list below.";
}

export function ReportsPage() {
  const { data, error, reload } =
    useData<{ id: number; week_start: string; generated_at: string; tiles: { label: string; value: unknown; unit: string }[] }[]>("/api/analytics/reports");
  const { data: sites } = useData<{ items: { id: number; code: string; name: string }[] }>("/api/sites?limit=500&status=active");
  const [site, setSite] = useState("");
  const { can } = useAuth();
  const [notice, setNotice] = useState("");
  const dl = (path: string) => void downloadFile(path).catch((err) => showError(err));
  const fileNow = () =>
    void api<{ created: boolean }>("/api/analytics/reports/weekly", { method: "POST" }).then((r) => {
      setNotice(weeklyNotice(r));
      reload();
    }, (err) => showError(err));
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p className="muted small">The management summary is filed every Monday at 8 am (IST) and announced in the bell. No email yet.</p>
        </div>
        <div className="page-actions">
          <Button size="small" onClick={fileNow}>
            File this week's now
          </Button>
        </div>
      </div>
      {notice && <div className="alert alert-ok">{notice}</div>}
      {can("reports.export") && (
        <Card as="div">
          <h2 className="section-title">Download</h2>
          <div className="inline-form">
            <Button size="small" onClick={() => dl("/api/analytics/pdf/management")}>
              Management summary (PDF)
            </Button>
            <Button size="small" onClick={() => dl("/api/analytics/pdf/receivables")}>
              Receivables (PDF)
            </Button>
            <Button size="small" onClick={() => dl("/api/analytics/pdf/pipeline")}>
              Sales pipeline (PDF)
            </Button>
            <Field label="Site" bare>
              <select value={site} onChange={(e) => setSite(e.target.value)} aria-label="Site">
                <option value="">Site status report for…</option>
                {(sites?.items ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {site && (
              <Button variant="primary" size="small" onClick={() => dl(`/api/analytics/pdf/site/${site}`)}>
                Site status (PDF, no costs)
              </Button>
            )}
          </div>
        </Card>
      )}
      <h2 className="section-title top-gap">Weekly management summaries</h2>
      {!data ? (
        <Loading error={error} />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">Week of {fmtValue(r.week_start, "date")}</td>
                  <td className="small muted">{r.tiles.map((t) => `${t.label}: ${fmtValue(t.value, t.unit)}`).join(" · ")}</td>
                  <td>
                    <Button size="small" onClick={() => dl(`/api/analytics/reports/${r.id}/pdf`)}>
                      PDF
                    </Button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td className="empty">None filed yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
