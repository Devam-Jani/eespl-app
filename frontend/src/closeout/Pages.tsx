import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";

const d = (v: string | null | undefined) =>
  v ? new Date(v.length === 10 ? `${v}T00:00:00` : v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const num = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits });

function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!path) return;
    api<T>(path).then(setData, (e) => setError(errorText(e)));
  }, [path]);
  useEffect(load, [load]);
  return { data, setData, error, setError, load };
}

async function run<T>(p: Promise<T>, setError: (e: string | null) => void): Promise<T | undefined> {
  setError(null);
  try {
    return await p;
  } catch (e) {
    setError(errorText(e));
  }
}

// --- 1. the tender's civil contractors -----------------------------------------------------------

type Customer = {
  id: number;
  client_id: number;
  client: string;
  main_status: string;
  main_label: string;
  quotation: { id: number; code: string; revision: number; status: string; lost_reason: string | null; total: string } | null;
};
type Customers = { tender_id: number; status: string; main_contractor: string | null; customers: Customer[] };

/** On the tender: the civil contractors we quoted it to, each with its own quotation, and who won the main job. */
export function TenderCustomers({ tenderId }: { tenderId: number }) {
  const { can } = useAuth();
  const { data, setData, error, setError } = useLoad<Customers>(`/api/closeout/tenders/${tenderId}/customers`);
  const [clients, setClients] = useState<{ id: number; name: string }[]>([]);
  const [pick, setPick] = useState("");
  useEffect(() => {
    if (can("tender.edit"))
      api<{ id: number; name: string }[]>("/api/clients?limit=500").then(
        (r) => setClients(Array.isArray(r) ? r : []),
        () => setClients([]),
      );
  }, [can]);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : null;
  const edit = can("tender.edit") && !data.main_contractor;
  return (
    <div className="card top-gap">
      <h2 className="section-title">Quoted to (civil contractors bidding for the main job)</h2>
      {error && <div className="alert alert-error">{error}</div>}
      {data.main_contractor && (
        <p>
          Main contract won by <b>{data.main_contractor}</b>: our applicator stage (bidders L1/L2/L3, negotiation) runs with them.
        </p>
      )}
      <table className="table compact">
        <thead>
          <tr>
            <th>Civil contractor</th>
            <th>Our quotation</th>
            <th className="num">Total</th>
            <th>Main job</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.customers.map((c) => (
            <tr key={c.id}>
              <td>{c.client}</td>
              <td>
                {c.quotation ? (
                  <Link to={`/quotations/${c.quotation.id}`}>
                    {c.quotation.code} R{c.quotation.revision}
                  </Link>
                ) : (
                  "—"
                )}{" "}
                <span className="small muted">{c.quotation?.status}</span>
              </td>
              <td className="num">₹ {num(c.quotation?.total, 0)}</td>
              <td>
                <span className={`badge ${c.main_status === "won" ? "badge-ok" : c.main_status === "lost" ? "badge-muted" : "badge-info"}`}>{c.main_label}</span>
                {c.main_status === "lost" && <div className="small muted">not counted as our loss</div>}
              </td>
              <td>
                {edit && (
                  <button
                    className="btn btn-small"
                    onClick={() =>
                      void run(api<Customers>(`/api/closeout/tenders/${tenderId}/customers/${c.id}/main-won`, { method: "POST" }), setError).then((r) => r && setData(r))
                    }
                  >
                    Won the main contract
                  </button>
                )}
              </td>
            </tr>
          ))}
          {!data.customers.length && (
            <tr>
              <td colSpan={5} className="muted">
                Quoted to one customer only (the tender's client).
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {edit && (
        <form
          className="inline-form top-gap"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (!pick) return;
            void run(api<Customers>(`/api/closeout/tenders/${tenderId}/customers`, { method: "POST", json: { client_id: Number(pick) } }), setError).then((r) => {
              if (r) {
                setData(r);
                setPick("");
              }
            });
          }}
        >
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Civil contractor">
            <option value="">Add a civil contractor…</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button className="btn">Quote it to them too</button>
        </form>
      )}
    </div>
  );
}

// --- 2. work orders ------------------------------------------------------------------------------

type Deviation = { id: number; kind: string; topic: string; ours: string | null; theirs: string | null; status: string; note: string | null; amend_text: string | null };
type WO = {
  id: number;
  code: string;
  client_ref: string | null;
  tender_id: number | null;
  site_id: number | null;
  quotation: { id: number; code: string; revision: number } | null;
  file_name: string | null;
  lines_from: string | null;
  status: string;
  locked: boolean;
  accepted_at: string | null;
  terms: Record<string, string | number | string[] | null>;
  lines: { id: number; item_no: string | null; description: string; unit: string | null; qty: string | null; rate: string | null }[];
  deviations: Deviation[];
  open: number;
};
const KIND: Record<string, string> = {
  missing: "Item missing",
  added: "Item added",
  qty: "Quantity",
  rate: "Rate",
  unit: "Unit",
  discontinued: "Discontinued product",
  scope: "Scope",
  payment: "Payment term",
  retention: "Retention",
  advance: "Advance",
  penalty: "Penalty",
  time: "Time limit",
};

export function WorkOrders() {
  const [params] = useSearchParams();
  const q = params.get("tender") ? `?tender_id=${params.get("tender")}` : params.get("site") ? `?site_id=${params.get("site")}` : "";
  const { data, error } = useLoad<WO[]>(`/api/closeout/work-orders${q}`);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Client work orders</h1>
          <p className="muted">Each work order checked against our accepted quotation before we sign it.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <table className="table compact">
          <thead>
            <tr>
              <th>Work order</th>
              <th>Client's ref</th>
              <th>Quotation</th>
              <th className="num">Open deviations</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((w) => (
              <tr key={w.id}>
                <td>
                  <Link to={`/work-orders/${w.id}`}>{w.code}</Link>
                </td>
                <td>{w.client_ref}</td>
                <td>{w.quotation ? `${w.quotation.code} R${w.quotation.revision}` : "—"}</td>
                <td className="num">{w.open}</td>
                <td>{w.locked ? <span className="badge badge-ok">accepted · locked</span> : <span className="badge badge-warn">checking</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function WorkOrderPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: wo, setData, error, setError } = useLoad<WO>(`/api/closeout/work-orders/${id}`);
  const [busy, setBusy] = useState(false);
  const act = async (p: Promise<WO>) => {
    setBusy(true);
    const r = await run(p, setError);
    if (r) setData(r);
    setBusy(false);
  };
  if (!wo) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const edit = can("wo.edit") && !wo.locked;
  const resolve = (dv: Deviation, action: "accept" | "amend") => {
    const note = window.prompt(action === "accept" ? "Why we accept it" : "What to ask the client (note)", action === "accept" ? "Accepted" : "");
    if (!note) return;
    void act(api<WO>(`/api/closeout/work-orders/${wo.id}/deviations/${dv.id}`, { method: "POST", json: { action, note } }));
  };
  const upload = (f: File | undefined) => {
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    void act(api<WO>(`/api/closeout/work-orders/${wo.id}/file`, { method: "POST", form }));
  };
  const t = wo.terms;
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to="/work-orders">Work orders</Link> / <code>{wo.code}</code>
          </p>
          <h1>
            Work order {wo.client_ref ?? wo.code} {wo.locked ? <span className="badge badge-ok">accepted · locked</span> : <span className="badge badge-warn">checking</span>}
          </h1>
          <p className="muted">
            Against our quotation {wo.quotation ? `${wo.quotation.code} R${wo.quotation.revision}` : "—"} · lines{" "}
            {wo.lines_from === "file" ? `read from ${wo.file_name}` : (wo.lines_from ?? "not yet")}
          </p>
        </div>
        <div className="page-actions">
          {edit && (
            <>
              <label className="btn">
                Upload the work order (PDF / Excel)
                <input type="file" hidden accept=".pdf,.xlsx,.xlsm" onChange={(e) => upload(e.target.files?.[0])} />
              </label>
              <button className="btn" disabled={busy} onClick={() => void act(api<WO>(`/api/closeout/work-orders/${wo.id}/copy-quotation`, { method: "POST" }))}>
                Copy lines from our quotation
              </button>
              <button className="btn" disabled={busy} onClick={() => void act(api<WO>(`/api/closeout/work-orders/${wo.id}/compare`, { method: "POST" }))}>
                Compare with our offer
              </button>
              <button
                className="btn btn-primary"
                disabled={busy || wo.open > 0}
                title={wo.open ? "Resolve every deviation first" : ""}
                onClick={() => void act(api<WO>(`/api/closeout/work-orders/${wo.id}/accept`, { method: "POST" }))}
              >
                Work order accepted
              </button>
            </>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <h2 className="section-title">
          Deviations from our offer ({wo.deviations.length}, {wo.open} open)
        </h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Kind</th>
              <th>What</th>
              <th>Our offer</th>
              <th>The work order</th>
              <th>Resolution</th>
            </tr>
          </thead>
          <tbody>
            {wo.deviations.map((dv) => (
              <tr key={dv.id}>
                <td>
                  <span className={`badge ${dv.status === "open" ? "badge-danger" : dv.status === "amend" ? "badge-warn" : "badge-ok"}`}>{KIND[dv.kind] ?? dv.kind}</span>
                </td>
                <td className="small">{dv.topic}</td>
                <td className="small">{dv.ours}</td>
                <td className="small">{dv.theirs}</td>
                <td className="small">
                  {dv.status === "open" && edit ? (
                    <>
                      <button className="btn btn-small" onClick={() => resolve(dv, "accept")}>
                        Accept
                      </button>{" "}
                      <button className="btn btn-small" onClick={() => resolve(dv, "amend")}>
                        Ask the client to amend
                      </button>
                    </>
                  ) : (
                    <>
                      <b>{dv.status === "amend" ? "asked to amend" : dv.status}</b> {dv.note}
                      {dv.amend_text && <div className="muted">To send: {dv.amend_text}</div>}
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!wo.deviations.length && (
              <tr>
                <td colSpan={5} className="muted">
                  Not compared yet, or no deviation.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="grid-2 top-gap">
        <div className="card">
          <h2 className="section-title">Payment and terms (structured)</h2>
          <p className="small">
            Payment: <b>{t.payment_days ?? "—"} days</b> after the {String(t.payment_basis ?? "invoice").replace("_", " ")} · retention {num(t.retention_percent as string)} %
            {t.retention_release ? ` (released ${t.retention_release})` : ""} · advance {num(t.advance_percent as string)} % · guarantee {t.guarantee_years ?? "—"} years
          </p>
          <p className="small">Penalty: {(t.penalty as string) || "—"}</p>
          <p className="small">Time limit: {t.time_limit_days ? `${t.time_limit_days} days` : "—"}</p>
          <p className="small">
            On us in the work order: {((t.scope_on_us as string[]) ?? []).join(", ") || "—"} · on the client: {((t.scope_on_client as string[]) ?? []).join(", ") || "—"}
          </p>
        </div>
        <div className="card">
          <h2 className="section-title">Lines ({wo.lines.length})</h2>
          <table className="table compact">
            <tbody>
              {wo.lines.map((l) => (
                <tr key={l.id}>
                  <td className="small">{l.description}</td>
                  <td className="small">{l.unit}</td>
                  <td className="num small">{num(l.qty)}</td>
                  <td className="num small">{num(l.rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

// --- 5-6. measurements, zones, billing checklist -------------------------------------------------

type Zone = {
  id: number;
  name: string;
  node_id: number | null;
  place: string | null;
  ours: boolean;
  other_applicator: string | null;
  signed_at: string | null;
  signed_name: string | null;
  recorded_by_staff: boolean;
};
type ZNode = { id: number; parent_id: number | null; kind: string; name: string; path: string };

/** RFI zones marked on the site: handed to us (green) or to another applicator (grey), and the client's signature. */
export function SiteZones() {
  const { id } = useParams();
  const { data, error } = useLoad<{ zones: Zone[]; nodes: ZNode[] }>(`/api/closeout/sites/${id}/zones`);
  const plan = useMemo(() => {
    if (!data) return null;
    const kids: Record<string, ZNode[]> = {};
    data.nodes.forEach((n) => (kids[String(n.parent_id)] = [...(kids[String(n.parent_id)] ?? []), n]));
    const zoneOf = (n: ZNode | undefined): Zone | undefined => {
      let cur = n;
      while (cur) {
        const z = data.zones.find((x) => x.node_id === cur!.id);
        if (z) return z;
        cur = data.nodes.find((x) => x.id === cur!.parent_id);
      }
      return undefined;
    };
    return { kids, zoneOf };
  }, [data]);
  if (!data || !plan) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const towers = (plan.kids["null"] ?? []).filter((n) => n.kind === "tower" || n.kind === "wing");
  const flatsOf = (t: ZNode): ZNode[] => {
    const out: ZNode[] = [];
    const walk = (n: ZNode) => (plan.kids[String(n.id)] ?? []).forEach((c) => (c.kind === "flat" ? out.push(c) : walk(c)));
    walk(t);
    return out;
  };
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>Site</Link> / RFI zones
          </p>
          <h1>RFI zones</h1>
          <p className="muted">Which zones the client handed to us, which went to another applicator. Measurements and bills outside our zones need a reason.</p>
        </div>
      </div>
      <div className="card">
        {towers.map((t) => (
          <div key={t.id} className="zone-tower">
            <h3 className="section-title">{t.name}</h3>
            <div className="zone-grid">
              {flatsOf(t).map((f) => {
                const z = plan.zoneOf(f);
                return (
                  <div key={f.id} className={`zone-flat ${z ? (z.ours ? "ours" : "theirs") : "unmarked"}`}>
                    <b>{f.name}</b>
                    <div className="small">{z ? (z.ours ? `ours · ${z.name}` : `${z.other_applicator}`) : "not marked"}</div>
                    <div className="zone-areas">
                      {(plan.kids[String(f.id)] ?? []).map((a) => (
                        <span key={a.id}>{a.name}</span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        <div className="small muted top-gap">
          <span className="zone-key ours" /> ours <span className="zone-key theirs" /> another applicator <span className="zone-key unmarked" /> not marked
        </div>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Zones and RFI signatures</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Zone</th>
              <th>Place</th>
              <th>Handed to</th>
              <th>RFI signed</th>
            </tr>
          </thead>
          <tbody>
            {data.zones.map((z) => (
              <tr key={z.id}>
                <td>{z.name}</td>
                <td>{z.place}</td>
                <td>{z.ours ? <span className="badge badge-ok">us</span> : <span className="badge badge-muted">{z.other_applicator}</span>}</td>
                <td className="small">{z.signed_at ? `${z.signed_name}, ${d(z.signed_at)}${z.recorded_by_staff ? " (recorded by staff)" : " (in the portal)"}` : "not yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Cell = { node_id: number; status: string; label: string; bill?: string | null };
type Checklist = {
  tower: string;
  towers: { id: number; name: string }[];
  tower_id: number;
  months: string[];
  columns: string[];
  rows: { flat_id: number; flat: string; cells: Record<string, Cell> }[];
  counts: Record<string, number>;
};
const CELL_CLASS: Record<string, string> = {
  not_ours: "c-not",
  waiting_handover: "c-wait",
  to_start: "c-wait",
  in_progress: "c-prog",
  done: "c-done",
  measured: "c-meas",
  approved: "c-appr",
  billed: "c-bill",
};

export function BillingChecklist() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const q = new URLSearchParams();
  if (params.get("tower")) q.set("tower_id", params.get("tower")!);
  if (params.get("month")) q.set("month", params.get("month")!);
  const { data, error } = useLoad<Checklist>(`/api/closeout/sites/${id}/billing-checklist?${q}`);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(params);
    if (v) n.set(k, v);
    else n.delete(k);
    setParams(n, { replace: true });
  };
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>Site</Link> / billing checklist
          </p>
          <h1>Billing checklist — {data.tower}</h1>
          <p className="muted">Filled from the RFI zones, the handover, the stages, the measurement book and the bills: nothing typed here.</p>
        </div>
        <div className="page-actions">
          <select value={String(data.tower_id)} onChange={(e) => set("tower", e.target.value)} aria-label="Tower">
            {data.towers.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <select value={params.get("month") ?? ""} onChange={(e) => set("month", e.target.value)} aria-label="Bill month">
            <option value="">All bills</option>
            {data.months.map((m) => (
              <option key={m} value={m}>
                billed in {m}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => void downloadFile(`/api/closeout/sites/${id}/billing-checklist.xlsx?${q}`)}>
            Excel
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <div className="stat-row">
          {Object.entries(data.counts).map(([k, v]) => (
            <div key={k} className="stat">
              <div className="stat-value">{v}</div>
              <div className="stat-label small muted">{k.replace(/_/g, " ")}</div>
            </div>
          ))}
        </div>
        <table className="table checklist-grid">
          <thead>
            <tr>
              <th>Flat</th>
              {data.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.flat_id}>
                <td>
                  <b>{r.flat}</b>
                </td>
                {data.columns.map((c) => {
                  const cell = r.cells[c];
                  return (
                    <td key={c} className={cell ? CELL_CLASS[cell.status] : ""}>
                      {cell?.label ?? ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- 7-8. bill tracking and payments ----------------------------------------------------------------

type Bill = {
  id: number;
  code: string;
  site: string;
  site_id: number;
  status: string;
  invoice: string | null;
  invoice_date: string | null;
  outstanding: string;
  due_on: string | null;
  due_how: string;
  overdue_days: number;
  at: string;
  steps: { step: string; label: string; on: string; by: string | null; file: string | null; days: number }[];
  followups: { at: string; spoke_to: string; said: string; promised_on: string | null }[];
  cycle: { submit_from_day: number; submit_to_day: number; ho_from_day: number; ho_to_day: number; payment_days: number } | null;
};
export function Payments() {
  const { can } = useAuth();
  const { data, error, setError, load } = useLoad<Bill[]>("/api/closeout/bills?overdue=true");
  const [form, setForm] = useState<{ id: number; spoke_to: string; said: string; promised_on: string } | null>(null);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Payment follow-up</h1>
          <p className="muted">
            Bills past their due date (the invoice or certification date plus the work order's term). Each call logged; the promised date becomes the next reminder.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <table className="table compact">
          <thead>
            <tr>
              <th>Bill</th>
              <th>Site</th>
              <th className="num">Outstanding</th>
              <th>Due</th>
              <th className="num">Overdue</th>
              <th>With the client at</th>
              <th>Follow-ups</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((b) => (
              <tr key={b.id}>
                <td>
                  <Link to={`/bills/${b.id}?tab=payment`}>{b.code}</Link>
                  <div className="small muted">{b.invoice}</div>
                </td>
                <td className="small">{b.site}</td>
                <td className="num">₹ {num(b.outstanding)}</td>
                <td className="small">
                  {d(b.due_on)}
                  <div className="muted">{b.due_how}</div>
                </td>
                <td className="num">
                  <span className={`badge ${b.overdue_days >= 30 ? "badge-danger" : "badge-warn"}`}>{b.overdue_days} days</span>
                </td>
                <td className="small">{b.at}</td>
                <td className="small">
                  {b.followups.map((f, i) => (
                    <div key={i}>
                      {d(f.at)}: {f.spoke_to} — “{f.said}”{f.promised_on ? `, promised ${d(f.promised_on)}` : ""}
                    </div>
                  ))}
                  {can("closeout.payments") && (
                    <button className="btn btn-small" onClick={() => setForm({ id: b.id, spoke_to: "", said: "", promised_on: "" })}>
                      Log a call
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {data && !data.length && (
              <tr>
                <td colSpan={7} className="muted">
                  Nothing overdue.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {form && (
        <form
          className="card top-gap"
          onSubmit={(e) => {
            e.preventDefault();
            void run(
              api(`/api/closeout/bills/${form.id}/followups`, { method: "POST", json: { spoke_to: form.spoke_to, said: form.said, promised_on: form.promised_on || null } }),
              setError,
            ).then(() => {
              setForm(null);
              load();
            });
          }}
        >
          <div className="inline-form">
            <input placeholder="Who you spoke to" value={form.spoke_to} onChange={(e) => setForm({ ...form, spoke_to: e.target.value })} required />
            <input className="grow" placeholder="What was said" value={form.said} onChange={(e) => setForm({ ...form, said: e.target.value })} required />
            <input type="date" value={form.promised_on} onChange={(e) => setForm({ ...form, promised_on: e.target.value })} aria-label="Promised date" />
            <button className="btn btn-primary">Save</button>
          </div>
        </form>
      )}
    </>
  );
}

// --- 9. work completion and guarantees ----------------------------------------------------------------

type Wcc = {
  id: number;
  code: string;
  completion_date: string;
  guarantee_years: number;
  guarantee_expiry: string;
  status: string;
  signed_name: string | null;
  areas: { area: string; qty: string; unit: string }[];
  addendum_of_id: number | null;
};

export function SiteWorkCompletions() {
  const { id } = useParams();
  const { data, error, setError, load } = useLoad<Wcc[]>(`/api/closeout/sites/${id}/work-completions`);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>Site</Link> / work completion
          </p>
          <h1>Work completion certificates</h1>
        </div>
        <div className="page-actions">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Completion date" />
          <button
            className="btn btn-primary"
            onClick={() => void run(api(`/api/closeout/sites/${id}/work-completions`, { method: "POST", json: { completion_date: date } }), setError).then(load)}
          >
            Make the certificate
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <table className="table compact">
          <thead>
            <tr>
              <th>Certificate</th>
              <th>Completed</th>
              <th>Areas</th>
              <th>Guarantee</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((w) => (
              <tr key={w.id}>
                <td>
                  {w.code}
                  {w.addendum_of_id && <div className="small muted">addendum</div>}
                </td>
                <td>{d(w.completion_date)}</td>
                <td className="small">{w.areas.map((a) => `${a.area.split(" / ").slice(-2).join(" / ")}: ${num(a.qty)} ${a.unit}`).join("; ")}</td>
                <td>
                  {w.guarantee_years} years, to {d(w.guarantee_expiry)}
                </td>
                <td>{w.status === "signed" ? <span className="badge badge-ok">signed by {w.signed_name} · locked</span> : <span className="badge badge-warn">draft</span>}</td>
                <td>
                  <button className="btn btn-small" onClick={() => void downloadFile(`/api/closeout/work-completions/${w.id}/pdf`)}>
                    PDF
                  </button>{" "}
                  <button className="btn btn-small" onClick={() => void downloadFile(`/api/closeout/work-completions/${w.id}/bond.pdf`)}>
                    Guarantee bond
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Guarantee = {
  id: number;
  code: string;
  site: string;
  client: string;
  areas: string[];
  products: string[];
  start: string;
  expiry: string;
  years: number;
  active: boolean;
  has_complaints: boolean;
  addendum_of: number | null;
};

export function Guarantees() {
  const { data, error } = useLoad<Guarantee[]>("/api/closeout/guarantees");
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Guarantee register</h1>
          <p className="muted">
            Every signed work completion: what we guarantee, where, with which products, until when. A leakage complaint links to the guarantee and the exact area.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => void downloadFile("/api/closeout/past-projects.xlsx")}>
            Past projects (Excel)
          </button>
          <button className="btn" onClick={() => void downloadFile("/api/closeout/past-projects.pdf")}>
            Past projects (PDF)
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <table className="table compact">
          <thead>
            <tr>
              <th>Certificate</th>
              <th>Site</th>
              <th>Client</th>
              <th>Areas</th>
              <th>Products</th>
              <th>From</th>
              <th>Until</th>
              <th>Complaints</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((g) => (
              <tr key={g.id}>
                <td>
                  {g.code}
                  {g.addendum_of && <div className="small muted">addendum</div>}
                </td>
                <td className="small">{g.site}</td>
                <td className="small">{g.client}</td>
                <td className="small">{g.areas.join("; ")}</td>
                <td className="small">{g.products.join(", ")}</td>
                <td>{d(g.start)}</td>
                <td>
                  {d(g.expiry)} <span className={`badge ${g.active ? "badge-ok" : "badge-muted"}`}>{g.active ? `${g.years} y, active` : "expired"}</span>
                </td>
                <td>{g.has_complaints ? <Link to="/issues?category=leakage">leakage logged</Link> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- 10. the issue log ---------------------------------------------------------------------------------

type Issue = {
  id: number;
  code: string;
  site: string | null;
  category: string;
  category_label: string;
  title: string;
  description: string | null;
  raised_by: string | null;
  assigned_to: string | null;
  due_on: string | null;
  status: string;
  overdue: boolean;
  snag_id: number | null;
  work_completion_id: number | null;
  comments: { by: string; body: string; at: string }[];
};

export function Issues() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const site = params.get("site");
  const { data, error, setError, load } = useLoad<Issue[]>(`/api/closeout/issues${site ? `?site_id=${site}` : ""}`);
  const [open, setOpen] = useState<number | null>(Number(params.get("open")) || null);
  const [text, setText] = useState("");
  const rows = (data ?? []).filter((i) => !params.get("category") || i.category === params.get("category"));
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Issue log</h1>
          <p className="muted">Per site, members from the site allocation. "Share with the client" makes it a portal snag.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <table className="table compact">
          <thead>
            <tr>
              <th>Issue</th>
              <th>Site</th>
              <th>Category</th>
              <th>Raised by</th>
              <th>With</th>
              <th>Due</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <Fragment key={i.id}>
                <tr className="clickable" onClick={() => setOpen(open === i.id ? null : i.id)}>
                  <td>
                    <b>{i.code}</b> {i.title}
                  </td>
                  <td className="small">{i.site}</td>
                  <td>
                    <span className={`badge ${i.category === "leakage" ? "badge-danger" : i.category.startsWith("material") ? "badge-warn" : "badge-info"}`}>
                      {i.category_label}
                    </span>
                  </td>
                  <td className="small">{i.raised_by ?? "the system"}</td>
                  <td className="small">{i.assigned_to ?? "—"}</td>
                  <td className={i.overdue ? "text-danger" : ""}>{d(i.due_on)}</td>
                  <td>
                    {i.status}
                    {i.snag_id && <div className="small muted">shared with the client</div>}
                    {i.work_completion_id && <div className="small muted">linked to the guarantee</div>}
                  </td>
                </tr>
                {open === i.id && (
                  <tr>
                    <td colSpan={7}>
                      {i.description && <p className="small">{i.description}</p>}
                      {i.comments.map((c, k) => (
                        <div key={k} className="small">
                          <b>{c.by}</b> {d(c.at)}: {c.body}
                        </div>
                      ))}
                      {can("issues.edit") && (
                        <div className="inline-form top-gap">
                          <input className="grow" placeholder="Comment" value={text} onChange={(e) => setText(e.target.value)} />
                          <button
                            className="btn btn-small"
                            onClick={() =>
                              void run(api(`/api/closeout/issues/${i.id}/comments`, { method: "POST", json: { body: text } }), setError).then(() => (setText(""), load()))
                            }
                          >
                            Comment
                          </button>
                          {!i.snag_id && (
                            <button className="btn btn-small" onClick={() => void run(api(`/api/closeout/issues/${i.id}/share`, { method: "POST" }), setError).then(load)}>
                              Share with the client
                            </button>
                          )}
                          {i.status !== "resolved" && (
                            <button
                              className="btn btn-small"
                              onClick={() => void run(api(`/api/closeout/issues/${i.id}`, { method: "PUT", json: { status: "resolved" } }), setError).then(load)}
                            >
                              Resolved
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
