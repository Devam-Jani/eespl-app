// Team roles and workspaces: My work (each role's to-do list), enquiries to allocate, won jobs to
// assign, the site status board and allocation list, material plans, the measurement book, client
// bill tracking, the labour bill check, the closure scorecard, the supervisor's day on the phone,
// site visits, negotiations, tender award follow-ups and the team settings.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import { S } from "../receipt/strings";
import type { Key } from "../receipt/strings";

const Dashboard = lazy(() => import("../analytics/Dashboard"));

const TZ = "Asia/Kolkata";
const fmt = (d: string | null | undefined, time = false) =>
  d ? new Date(d).toLocaleString("en-IN", { timeZone: TZ, day: "2-digit", month: "short", year: "numeric", ...(time ? { hour: "2-digit", minute: "2-digit" } : {}) }) : "—";
const n = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits });
const money = (v: string | number | null | undefined) => (v === null || v === undefined ? "—" : `₹ ${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);

type Person = { id: string; name: string; job_title: string | null };
function usePeople(role?: string): Person[] {
  const [rows, setRows] = useState<Person[]>([]);
  useEffect(() => {
    void api<Person[]>(`/api/team/people${role ? `?role=${role}` : ""}`).then(setRows, () => setRows([]));
  }, [role]);
  return rows;
}

type SiteOpt = { id: number; code: string; name: string };
function useSites(): SiteOpt[] {
  const [sites, setSites] = useState<SiteOpt[]>([]);
  useEffect(() => {
    void api<{ items: SiteOpt[] }>("/api/sites?limit=200").then(
      (r) => setSites(r.items),
      () => setSites([]),
    );
  }, []);
  return sites;
}

// --- My work -------------------------------------------------------------------------------------

export type WorkItem = {
  source: string;
  key: string;
  title: string;
  why: string;
  age_days: number | null;
  link: string;
  action: string;
  severity: "normal" | "warn" | "danger";
  menu: string;
};
export type MyWorkData = { sections: { role: string; title: string; items: WorkItem[] }[]; counts: Record<string, number>; total: number };

export function useMyWork(): [MyWorkData | null, () => void] {
  const [data, setData] = useState<MyWorkData | null>(null);
  const load = useCallback(() => {
    void api<MyWorkData>("/api/team/my-work").then(setData, () => setData(null));
  }, []);
  useEffect(load, [load]);
  return [data, load];
}

export function MyWork() {
  const { me } = useAuth();
  const [data, reload] = useMyWork();
  const supervisorOnly = me?.roles.length === 1 && me.roles[0].code === "site_supervisor";
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className={`mywork ${supervisorOnly ? "mywork-phone" : ""}`}>
      <div className="page-header">
        <div>
          <h1>My work</h1>
          <p className="muted small">
            {me?.user.full_name}
            {me?.user.job_title ? ` · ${me.user.job_title}` : ""} · {data.total} waiting
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-small btn-ghost" onClick={reload}>
            ↻ Refresh
          </button>
        </div>
      </div>
      {data.sections.length === 0 && <p className="empty">Nothing waiting for you.</p>}
      {data.sections.map((s) => (
        <section key={s.role} className="card mywork-section">
          <h2 className="section-title">
            {s.title} <span className="badge badge-muted">{s.items.length}</span>
          </h2>
          {s.items.length === 0 ? (
            <p className="muted small">All clear.</p>
          ) : (
            <ul className="mywork-list">
              {s.items.map((i) => (
                <li key={i.key} className={`mywork-item sev-${i.severity}`}>
                  <div className="mywork-text">
                    <b>{i.title}</b>
                    <span className="small">{i.why}</span>
                  </div>
                  <span className={`mywork-age ${i.age_days !== null && i.age_days > 7 ? "text-danger" : "muted"}`}>
                    {i.age_days === null ? "" : i.age_days === 0 ? "today" : `${i.age_days} d`}
                  </span>
                  <Link className="btn btn-small btn-primary mywork-action" to={i.link}>
                    {i.action}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      {!supervisorOnly && (
        <section className="top-gap">
          <Suspense fallback={null}>
            <Dashboard />
          </Suspense>
        </section>
      )}
    </div>
  );
}

// --- enquiries (planning) ------------------------------------------------------------------------

type Enquiry = {
  id: number;
  code: string;
  name: string;
  company: string | null;
  city: string | null;
  phone: string | null;
  requirement: string | null;
  created_at: string;
  age_days: number;
};

export function Enquiries() {
  const [rows, setRows] = useState<Enquiry[] | null>(null);
  const [owner, setOwner] = useState<Record<number, string>>({});
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [params] = useSearchParams();
  const sales = usePeople("sales");
  const load = useCallback(() => api<Enquiry[]>("/api/team/enquiries").then(setRows, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  async function allocate(id: number) {
    try {
      await api(`/api/team/enquiries/${id}/allocate`, { method: "POST", json: { owner_id: owner[id] } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="page-header">
        <h1>Enquiries to allocate</h1>
        <div className="page-actions">
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            New enquiry
          </button>
        </div>
      </div>
      <p className="muted small">Enquiries that came to planning directly. Allocate each to a salesperson; they get it on their to-do.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">No enquiry waiting.</p>
      ) : (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Enquiry</th>
                <th>Requirement</th>
                <th className="num">Waiting</th>
                <th>Salesperson</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={String(r.id) === params.get("lead") ? "row-highlight" : undefined}>
                  <td>
                    <b>{r.name}</b> <span className="muted small">{r.code}</span>
                    <div className="small muted">{[r.company, r.city, r.phone].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="small">{r.requirement ?? "—"}</td>
                  <td className="num">{r.age_days} d</td>
                  <td>
                    <div className="inline-form">
                      <select value={owner[r.id] ?? ""} onChange={(e) => setOwner({ ...owner, [r.id]: e.target.value })} aria-label="Salesperson">
                        <option value="">Choose…</option>
                        {sales.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                      <button className="btn btn-small btn-primary" disabled={!owner[r.id]} onClick={() => void allocate(r.id)}>
                        Allocate
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding && <EnquiryForm onClose={() => setAdding(false)} onSaved={() => (setAdding(false), void load())} />}
    </>
  );
}

function EnquiryForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: "", phone: "", company: "", city: "", requirement: "" });
  const [error, setError] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/team/enquiries", { method: "POST", json: Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null])) });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="New enquiry" onClose={onClose}>
      <form onSubmit={(e) => void save(e)}>
        <div className="form-grid two">
          {(["name", "phone", "company", "city"] as const).map((k) => (
            <label key={k} className="field">
              <span>{k === "name" ? "Contact name *" : k[0].toUpperCase() + k.slice(1)}</span>
              <input value={f[k]} required={k === "name"} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
            </label>
          ))}
        </div>
        <label className="field">
          <span>Requirement</span>
          <textarea rows={3} value={f.requirement} onChange={(e) => setF({ ...f, requirement: e.target.value })} />
        </label>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save to the queue</button>
        </div>
      </form>
    </Modal>
  );
}

// --- won jobs: who handles them ------------------------------------------------------------------

type Assignment = {
  id: number;
  title: string;
  status: string;
  site_id: number | null;
  site: string | null;
  salesperson_id: string | null;
  salesperson: string | null;
  engineer_id: string | null;
  engineer: string | null;
  decided_by: string | null;
  decided_at: string | null;
  first_visit_logged: boolean;
  created_at: string;
};

export function AssignmentPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [a, setA] = useState<Assignment | null>(null);
  const [sp, setSp] = useState("");
  const [eng, setEng] = useState("");
  const [error, setError] = useState("");
  const sales = usePeople("sales");
  const engineers = usePeople("site_engineer");
  useEffect(() => {
    void api<Assignment>(`/api/team/assignments/${id}`).then(
      (x) => (setA(x), setSp(x.salesperson_id ?? ""), setEng(x.engineer_id ?? "")),
      (e) => setError(errorText(e)),
    );
  }, [id]);
  if (!a) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  async function decide() {
    try {
      const r = await api<Assignment>(`/api/team/assignments/${id}/decide`, { method: "POST", json: { salesperson_id: sp, engineer_id: eng } });
      navigate(`/sites/${r.site_id}`);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="breadcrumb">
        <Link to="/my-work">My work</Link>
      </div>
      <h1>Won: {a.title}</h1>
      <p className="muted small">
        Won on {fmt(a.created_at)} {a.site && `· site ${a.site}`}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {a.status === "done" ? (
        <div className="card">
          <p>
            Salesperson <b>{a.salesperson}</b>, site engineer <b>{a.engineer}</b>, decided by {a.decided_by} on {fmt(a.decided_at)}.
          </p>
          <p className="small">{a.first_visit_logged ? "The first site visit is logged." : "The first site visit is not logged yet."}</p>
        </div>
      ) : (
        <div className="card assignment-card">
          <p className="small muted">
            The site is made (or linked), both become its members, it goes on the status board as upcoming, and the salesperson gets the first site visit to do.
          </p>
          <div className="form-grid two">
            <label className="field">
              <span>Salesperson</span>
              <select value={sp} onChange={(e) => setSp(e.target.value)}>
                <option value="">Choose…</option>
                {sales.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Site engineer</span>
              <select value={eng} onChange={(e) => setEng(e.target.value)}>
                <option value="">Choose…</option>
                {engineers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.job_title ? `(${p.job_title})` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {can("jobs.assign") ? (
            <button className="btn btn-primary" disabled={!sp || !eng} onClick={() => void decide()}>
              Assign
            </button>
          ) : (
            <p className="small muted">The director decides (or planning, when the director allows it).</p>
          )}
        </div>
      )}
    </>
  );
}

// --- the site status board -----------------------------------------------------------------------

type BoardSite = {
  id: number;
  code: string;
  name: string;
  status: string;
  column: string | null;
  progress_percent: string;
  last_update: string | null;
  salesperson: string | null;
  site_engineer: string | null;
  supervisor: string | null;
};
type Board = { columns: { key: string; label: string }[]; sites: BoardSite[]; missing: BoardSite[] };

export function StatusBoard() {
  const { can } = useAuth();
  const [b, setB] = useState<Board | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => api<Board>("/api/team/board").then(setB, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  async function move(id: number, column: string) {
    try {
      await api(`/api/team/board/${id}`, { method: "POST", json: { column } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!b) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const card = (s: BoardSite) => (
    <div key={s.id} className="board-card">
      <Link to={`/sites/${s.id}`}>
        <b>{s.code}</b> {s.name}
      </Link>
      <div className="small">
        <span className="muted">Sales</span> {s.salesperson ?? "—"} · <span className="muted">Engineer</span> {s.site_engineer ?? "—"} · <span className="muted">Supervisor</span>{" "}
        {s.supervisor ?? "—"}
      </div>
      <div className="small muted">
        {n(s.progress_percent, 0)}% done · updated {fmt(s.last_update)}
      </div>
      <select className="board-move" value={s.column ?? ""} onChange={(e) => void move(s.id, e.target.value)} aria-label={`Move ${s.code}`}>
        <option value="" disabled>
          Move to…
        </option>
        {b.columns.map((c) => (
          <option key={c.key} value={c.key}>
            {c.label}
          </option>
        ))}
      </select>
    </div>
  );
  return (
    <>
      <div className="page-header">
        <h1>Site status board</h1>
        {can("planning.view") && (
          <div className="page-actions">
            <button className="btn btn-small" onClick={() => void downloadFile("/api/team/allocation-list?format=pdf")}>
              ⤓ Allocation list (PDF)
            </button>
            <button className="btn btn-small" onClick={() => void downloadFile("/api/team/allocation-list?format=xlsx")}>
              ⤓ Excel
            </button>
            {can("planning.edit") && (
              <button
                className="btn btn-small btn-primary"
                onClick={() =>
                  void api<{ sent_to: number }>("/api/team/allocation-list/send", { method: "POST" }).then(
                    (r) => setMsg(`Sent to ${r.sent_to} person(s) in the app.`),
                    (e) => setError(errorText(e)),
                  )
                }
              >
                Send to recipients
              </button>
            )}
          </div>
        )}
      </div>
      <p className="muted small">Every site in three columns. Site engineers move their own sites from the phone, so planning does not have to phone each person.</p>
      {msg && <div className="alert alert-ok">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {b.missing.length > 0 && <div className="alert alert-warn">Not on the board: {b.missing.map((s) => s.code).join(", ")}. Place them in a column.</div>}
      <div className="board">
        {b.columns.map((c) => {
          const list = b.sites.filter((s) => s.column === c.key);
          return (
            <section key={c.key} className="board-col">
              <h2 className="section-title">
                {c.label} <span className="badge badge-muted">{list.length}</span>
              </h2>
              {list.map(card)}
              {list.length === 0 && <p className="muted small">None.</p>}
            </section>
          );
        })}
      </div>
      {b.missing.length > 0 && (
        <section className="top-gap">
          <h2 className="section-title">Not on the board</h2>
          <div className="board-missing">{b.missing.map(card)}</div>
        </section>
      )}
    </>
  );
}

// --- material plan -------------------------------------------------------------------------------

type PlanRow = { product_id: number; product: string; unit: string; planned: string; ready: string };
type Plan = {
  by: string;
  groups: { key: string; label: string; rows: PlanRow[] }[];
  products: (PlanRow & { indented: string; delivered: string; issued: string; balance: string; to_indent: string })[];
};

export function MaterialPlan() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [by, setBy] = useState("stage");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [qty, setQty] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    api<Plan>(`/api/team/material-plan/${id}?by=${by}`).then(
      (p) => (setPlan(p), setQty(Object.fromEntries(p.products.filter((x) => Number(x.to_indent) > 0).map((x) => [x.product_id, String(Number(x.to_indent))])))),
      (e) => setError(errorText(e)),
    );
  }, [id, by]);
  async function indent() {
    try {
      const r = await api<{ id: number; code: string }>(`/api/team/material-plan/${id}/indent`, {
        method: "POST",
        json: { lines: Object.entries(qty).map(([product_id, q]) => ({ product_id: Number(product_id), qty: q })), submit: true },
      });
      navigate(`/indents/${r.id}`);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="breadcrumb">
        <Link to={`/sites/${id}`}>Site</Link> / Material plan
      </div>
      <div className="page-header">
        <h1>Material plan</h1>
        <div className="tabs">
          {[
            ["stage", "By stage"],
            ["month", "By month"],
          ].map(([k, l]) => (
            <button key={k} className={`tab ${by === k ? "active" : ""}`} onClick={() => setBy(k)}>
              {l}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small">
        From the survey quantities and the systems' consumption (with wastage). "Ready" is the part on work fronts marked ready; "to indent" is what of that is not indented yet.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {plan && (
        <>
          <div className="table-wrap card">
            <table className="table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Planned</th>
                  <th className="num">On ready fronts</th>
                  <th className="num">Indented</th>
                  <th className="num">Delivered</th>
                  <th className="num">Issued</th>
                  <th className="num">Balance</th>
                  <th className="num">Indent now</th>
                </tr>
              </thead>
              <tbody>
                {plan.products.map((p) => (
                  <tr key={p.product_id}>
                    <td>{p.product}</td>
                    <td className="num">
                      {n(p.planned, 1)} {p.unit}
                    </td>
                    <td className="num">{n(p.ready, 1)}</td>
                    <td className="num">{n(p.indented, 1)}</td>
                    <td className="num">{n(p.delivered, 1)}</td>
                    <td className="num">{n(p.issued, 1)}</td>
                    <td className="num">{n(p.balance, 1)}</td>
                    <td className="num">
                      <input
                        className="input-num"
                        inputMode="decimal"
                        value={qty[p.product_id] ?? ""}
                        onChange={(e) => setQty({ ...qty, [p.product_id]: e.target.value })}
                        aria-label={`Indent ${p.product}`}
                      />
                    </td>
                  </tr>
                ))}
                {plan.products.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">
                      No area with a system on this site yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {can("indent.create") && (
            <button className="btn btn-primary top-gap" disabled={!Object.values(qty).some((q) => Number(q) > 0)} onClick={() => void indent()}>
              Create indent
            </button>
          )}
          <h2 className="section-title top-gap">{plan.by === "month" ? "By month" : "By stage (BOQ item)"}</h2>
          {plan.groups.map((g) => (
            <div key={g.key} className="card top-gap">
              <h3 className="section-title">{g.label}</h3>
              <table className="table compact">
                <tbody>
                  {g.rows.map((r) => (
                    <tr key={r.product_id}>
                      <td>{r.product}</td>
                      <td className="num">
                        {n(r.planned, 1)} {r.unit}
                      </td>
                      <td className="num muted">{Number(r.ready) > 0 ? `${n(r.ready, 1)} ready` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </>
  );
}

// --- the measurement book ------------------------------------------------------------------------

type Book = {
  entries: {
    id: number;
    place: string | null;
    description: string;
    qty: string;
    unit: string | null;
    source: string;
    measured_on: string;
    measured_by: string | null;
    note: string | null;
  }[];
  lines: { id: number; item_no: string | null; description: string; unit: string | null; contract_qty: string; measured: string; billed: string; to_bill: string }[];
  sources: string[];
};
const SOURCE_LABEL: Record<string, string> = { laser: "Laser", manual: "Manual", camera: "Camera", client_certified: "Client certified", autocad: "AutoCAD" };

export function MeasurementBook() {
  const { can } = useAuth();
  const sites = useSites();
  const [params, setParams] = useSearchParams();
  const site = params.get("site") ?? "";
  const [book, setBook] = useState<Book | null>(null);
  const [f, setF] = useState({ contract_line_id: "", qty: "", source: "laser", measured_on: "", note: "" });
  const [error, setError] = useState("");
  const load = useCallback(() => {
    if (site) api<Book>(`/api/team/measurements?site_id=${site}`).then(setBook, (e) => setError(errorText(e)));
  }, [site]);
  useEffect(load, [load]);
  useEffect(() => {
    if (!site && sites.length) setParams({ site: String(sites[0].id) }, { replace: true });
  }, [site, sites, setParams]);
  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/team/measurements", {
        method: "POST",
        json: { site_id: Number(site), contract_line_id: Number(f.contract_line_id), qty: f.qty, source: f.source, measured_on: f.measured_on || null, note: f.note || null },
      });
      setF({ ...f, qty: "", note: "" });
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <>
      <div className="page-header">
        <h1>Measurement book</h1>
        <div className="page-actions">
          <select value={site} onChange={(e) => setParams({ site: e.target.value })} aria-label="Site">
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="muted small">Every billable quantity with its source, date and who measured it. RA bills take their quantities only from here.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {book && (
        <>
          <div className="table-wrap card">
            <table className="table">
              <thead>
                <tr>
                  <th>Contract line</th>
                  <th className="num">Contract</th>
                  <th className="num">Measured</th>
                  <th className="num">Billed</th>
                  <th className="num">To bill</th>
                </tr>
              </thead>
              <tbody>
                {book.lines.map((l) => (
                  <tr key={l.id}>
                    <td className="small">
                      {l.item_no && <b>{l.item_no} </b>}
                      {l.description}
                    </td>
                    <td className="num">
                      {n(l.contract_qty)} {l.unit}
                    </td>
                    <td className="num">{n(l.measured)}</td>
                    <td className="num">{n(l.billed)}</td>
                    <td className={`num ${Number(l.to_bill) > 0 ? "text-warn" : ""}`}>{n(l.to_bill)}</td>
                  </tr>
                ))}
                {book.lines.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No client contract on this site yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {can("measurement.edit") && book.lines.length > 0 && (
            <form className="card top-gap measure-form" onSubmit={(e) => void add(e)}>
              <h2 className="section-title">Add a measurement</h2>
              <div className="form-grid four">
                <label className="field">
                  <span>Contract line</span>
                  <select required value={f.contract_line_id} onChange={(e) => setF({ ...f, contract_line_id: e.target.value })}>
                    <option value="">Choose…</option>
                    {book.lines.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.item_no ? `${l.item_no} ` : ""}
                        {l.description.slice(0, 60)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Quantity</span>
                  <input required inputMode="decimal" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} />
                </label>
                <label className="field">
                  <span>Source</span>
                  <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
                    {book.sources.map((s) => (
                      <option key={s} value={s}>
                        {SOURCE_LABEL[s] ?? s}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Measured on</span>
                  <input type="date" value={f.measured_on} onChange={(e) => setF({ ...f, measured_on: e.target.value })} />
                </label>
              </div>
              <label className="field">
                <span>Note</span>
                <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
              </label>
              <button className="btn btn-primary">Add to the book</button>
            </form>
          )}
          <h2 className="section-title top-gap">Entries</h2>
          <div className="table-wrap card">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Item</th>
                  <th>Place</th>
                  <th className="num">Qty</th>
                  <th>Source</th>
                  <th>Measured by</th>
                </tr>
              </thead>
              <tbody>
                {book.entries.map((m) => (
                  <tr key={m.id}>
                    <td className="nowrap">{fmt(m.measured_on)}</td>
                    <td className="small">
                      {m.description.slice(0, 70)}
                      {m.note && <div className="muted">{m.note}</div>}
                    </td>
                    <td className="small">{m.place ?? "—"}</td>
                    <td className="num">
                      {n(m.qty, 3)} {m.unit}
                    </td>
                    <td>
                      <span className={`badge ${m.source === "camera" ? "badge-warn" : m.source === "client_certified" ? "badge-ok" : "badge-info"}`}>
                        {SOURCE_LABEL[m.source] ?? m.source}
                      </span>
                    </td>
                    <td className="small">{m.measured_by ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

// --- client bill tracking ------------------------------------------------------------------------

type Tracked = {
  id: number;
  code: string;
  site_id: number;
  site: string;
  status: string;
  sent_at: string | null;
  billed: string;
  certified: string | null;
  difference: string | null;
  paid: string | null;
  lines: { id: number; qty: string; certified_qty: string; rate: string; reason: string | null }[];
};

export function BillTracking() {
  const { can } = useAuth();
  const [rows, setRows] = useState<Tracked[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<Tracked[]>("/api/team/bill-tracking").then(setRows, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  async function reason(lineId: number) {
    const r = prompt("Why does the certified quantity differ from the billed one?");
    if (!r) return;
    try {
      await api(`/api/team/ra-lines/${lineId}/reason`, { method: "PUT", json: { reason: r } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="page-header">
        <h1>Client bill tracking</h1>
      </div>
      <p className="muted small">Each RA bill: sent, certified by the client, the difference from what was billed (with the reason) and paid. Selling amounts only.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Bill</th>
              <th>Site</th>
              <th>Sent</th>
              <th className="num">Billed</th>
              <th className="num">Certified</th>
              <th className="num">Difference</th>
              <th className="num">Paid</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((b) => (
              <tr key={b.id}>
                <td>{b.code}</td>
                <td className="small">{b.site}</td>
                <td className="small">{fmt(b.sent_at)}</td>
                <td className="num">{money(b.billed)}</td>
                <td className="num">{money(b.certified)}</td>
                <td className={`num ${b.difference && Number(b.difference) < 0 ? "text-danger" : ""}`}>
                  {b.difference === null ? "—" : money(b.difference)}
                  {b.lines.map((l) => (
                    <div key={l.id} className="small">
                      {n(l.qty)} → {n(l.certified_qty)}: {l.reason ?? <span className="text-warn">reason?</span>}{" "}
                      {can("billing.edit") && (
                        <button className="btn btn-small btn-ghost" onClick={() => void reason(l.id)}>
                          ✎
                        </button>
                      )}
                    </div>
                  ))}
                </td>
                <td className="num">{money(b.paid)}</td>
                <td>
                  <span className="badge badge-info">{b.status.replace(/_/g, " ")}</span>
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No RA bills yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- the labour bill check -----------------------------------------------------------------------

type LabourBill = {
  id: number;
  number: string;
  wo: string;
  site: string;
  contractor: string;
  gross: string;
  productivity_status: string | null;
  productivity: { actual?: string; expected?: string; mandays?: string; sqm?: string } | null;
  overridden: boolean;
  checked_by: string | null;
  checked_at: string | null;
};

export function LabourCheck() {
  const [rows, setRows] = useState<LabourBill[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<LabourBill[]>("/api/team/labour-check").then(setRows, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <h1>Labour bill check</h1>
      </div>
      <p className="muted small">Check each labour contractor bill against the work done. A bill flagged "productivity low" waits for the director's decision after your check.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Bill</th>
              <th>Site / contractor</th>
              <th className="num">Gross</th>
              <th>Productivity</th>
              <th>Checked</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((b) => (
              <tr key={b.id} className={b.productivity_status === "low" && !b.overridden ? "row-overdue" : undefined}>
                <td>
                  {b.number} <span className="muted small">{b.wo}</span>
                </td>
                <td className="small">
                  {b.site}
                  <div className="muted">{b.contractor}</div>
                </td>
                <td className="num">{money(b.gross)}</td>
                <td className="small">
                  {b.productivity_status === "low" ? (
                    <span className={`badge ${b.overridden ? "badge-muted" : "badge-danger"}`}>
                      low: {b.productivity?.actual} / {b.productivity?.expected} sqm per man-day{b.overridden ? " (director approved)" : " (director decides)"}
                    </span>
                  ) : (
                    <span className="badge badge-muted">{(b.productivity_status ?? "—").replace(/_/g, " ")}</span>
                  )}
                  {b.productivity?.mandays && (
                    <div className="muted">
                      {b.productivity.sqm} sqm by {b.productivity.mandays} man-days
                    </div>
                  )}
                </td>
                <td className="small">
                  {b.checked_at ? (
                    <>
                      ✓ {b.checked_by} · {fmt(b.checked_at)}
                    </>
                  ) : (
                    <button
                      className="btn btn-small btn-primary"
                      onClick={() => void api(`/api/team/labour-check/${b.id}`, { method: "POST" }).then(load, (e) => setError(errorText(e)))}
                    >
                      Mark checked
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No labour bills waiting.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- the closure scorecard -----------------------------------------------------------------------

type Card = {
  user_id: string;
  name: string;
  sent: number;
  won: number;
  lost: number;
  lost_reasons: Record<string, number>;
  closure_percent: string | null;
  target_percent: string;
  on_target: boolean;
  followups_due: number;
  followups_on_time: number;
};

export function Scorecard() {
  const [rows, setRows] = useState<Card[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Card[]>("/api/team/scorecard").then(setRows, (e) => setError(errorText(e)));
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Closure scorecard</h1>
      </div>
      <p className="muted small">
        Quotations sent, won and lost (with reasons), the closure rate against the target, and follow-ups done on time. The director sees everyone; a salesperson sees only
        themselves.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Salesperson</th>
              <th className="num">Sent</th>
              <th className="num">Won</th>
              <th className="num">Lost</th>
              <th>Lost because</th>
              <th className="num">Closure</th>
              <th className="num">Follow-ups on time</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.user_id}>
                <td>{r.name}</td>
                <td className="num">{r.sent}</td>
                <td className="num">{r.won}</td>
                <td className="num">{r.lost}</td>
                <td className="small">
                  {Object.entries(r.lost_reasons)
                    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
                    .join(", ") || "—"}
                </td>
                <td className={`num ${r.closure_percent !== null && !r.on_target ? "text-danger" : ""}`}>
                  {r.closure_percent === null ? "—" : `${n(r.closure_percent, 1)}%`} <span className="muted small">/ {n(r.target_percent, 0)}%</span>
                </td>
                <td className="num">
                  {r.followups_on_time} / {r.followups_due}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- the supervisor's day on the phone -----------------------------------------------------------

function L({ k }: { k: Key }) {
  const [en, gu, hi] = S[k];
  return (
    <span className="tri">
      <b>{en}</b>
      <span className="tri-sub">
        {gu} · {hi}
      </span>
    </span>
  );
}

/** Attendance, deliveries, material issue, work done with photos, snags: in that order, with
 * Gujarati and Hindi next to English (the same strings file as the delivery receipt). */
export function SupervisorDay() {
  const { id } = useParams();
  const [data] = useMyWork();
  const [site, setSite] = useState<{ code: string; name: string } | null>(null);
  useEffect(() => {
    void api<{ code: string; name: string }>(`/api/sites/${id}`).then(setSite, () => setSite(null));
  }, [id]);
  const items = useMemo(
    () => (data?.sections ?? []).flatMap((s) => s.items).filter((i) => i.link.includes(`/${id}`) || i.link.includes(`site=${id}`) || i.source === "delivery"),
    [data, id],
  );
  const pending = (...sources: string[]) => items.filter((i) => sources.includes(i.source));
  const steps: { k: Key; to: string; open: WorkItem[] }[] = [
    { k: "stepAttendance", to: `/sites/${id}?tab=labour`, open: pending("attendance") },
    { k: "stepDeliveries", to: `/deliveries?site=${id}&state=unconfirmed`, open: pending("delivery") },
    { k: "stepIssue", to: `/sites/${id}?tab=material`, open: pending("issue") },
    { k: "stepWork", to: `/sites/${id}?tab=dpr`, open: pending("dpr_today", "dpr_returned") },
    { k: "stepSnags", to: `/snags?site=${id}`, open: pending("snag") },
  ];
  return (
    <div className="supervisor-day">
      <h1>
        <L k="mySite" />
      </h1>
      {site && (
        <p className="muted">
          {site.code} · {site.name}
        </p>
      )}
      {steps.map((s) => (
        <Link key={s.k} to={s.to} className={`day-step ${s.open.length ? "todo" : "ok"}`}>
          <L k={s.k} />
          <span className={`badge ${s.open.length ? "badge-warn" : "badge-ok"}`}>{s.open.length ? `${S.pending[0]} · ${s.open.length}` : S.stepDone[0]}</span>
          {s.open.map((i) => (
            <span key={i.key} className="small day-why">
              {i.title}: {i.why}
            </span>
          ))}
        </Link>
      ))}
    </div>
  );
}

// --- site visits ---------------------------------------------------------------------------------

export function SiteVisitForm({ siteId, leadId, onClose, onSaved }: { siteId?: number; leadId?: number; onClose: () => void; onSaved: () => void }) {
  const [notes, setNotes] = useState("");
  const [day, setDay] = useState(new Date().toLocaleDateString("en-CA", { timeZone: TZ }));
  const [photos, setPhotos] = useState<FileList | null>(null);
  const [gps, setGps] = useState<GeolocationCoordinates | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    navigator.geolocation?.getCurrentPosition(
      (p) => setGps(p.coords),
      () => undefined,
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }, []);
  async function save(e: FormEvent) {
    e.preventDefault();
    const form = new FormData();
    if (siteId) form.append("site_id", String(siteId));
    if (leadId) form.append("lead_id", String(leadId));
    form.append("notes", notes);
    form.append("visited_on", day);
    if (gps) {
      form.append("lat", gps.latitude.toFixed(6));
      form.append("lng", gps.longitude.toFixed(6));
      form.append("accuracy", String(Math.round(gps.accuracy)));
    }
    Array.from(photos ?? []).forEach((f) => form.append("photos", f));
    try {
      await api("/api/team/site-visits", { method: "POST", form });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="Log a site visit" onClose={onClose}>
      <form onSubmit={(e) => void save(e)}>
        <label className="field">
          <span>Date</span>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label className="field">
          <span>Notes (who you met, what was agreed)</span>
          <textarea required rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <label className="field">
          <span>Photos</span>
          <input type="file" accept="image/*" capture="environment" multiple onChange={(e) => setPhotos(e.target.files)} />
        </label>
        <p className="small muted">
          {gps ? `GPS ${gps.latitude.toFixed(5)}, ${gps.longitude.toFixed(5)} (±${Math.round(gps.accuracy)} m)` : "Location is saved when the phone allows it."}
        </p>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save visit</button>
        </div>
      </form>
    </Modal>
  );
}

type Visit = { id: number; by: string | null; visited_on: string; notes: string; gps: { lat: string; lng: string } | null; photos: number; first_after_win: boolean };

export function SiteVisits({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [rows, setRows] = useState<Visit[]>([]);
  const [open, setOpen] = useState(params.get("visit") === "1");
  const load = useCallback(() => {
    void api<Visit[]>(`/api/team/site-visits?site_id=${siteId}`).then(setRows, () => setRows([]));
  }, [siteId]);
  useEffect(load, [load]);
  if (!can("sitevisit.log")) return null;
  return (
    <div className="card top-gap">
      <div className="toolbar">
        <h2 className="section-title">Site visits</h2>
        <button className="btn btn-small btn-primary" onClick={() => setOpen(true)}>
          + Log a visit
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="muted small">No visit logged.</p>
      ) : (
        <ul className="plain-list small">
          {rows.map((v) => (
            <li key={v.id}>
              <b>{fmt(v.visited_on)}</b> {v.by} {v.first_after_win && <span className="badge badge-ok">first visit after the win</span>} · {v.notes}
              {v.photos > 0 && ` · ${v.photos} photo(s)`}
              {v.gps && " · GPS"}
            </li>
          ))}
        </ul>
      )}
      {open && <SiteVisitForm siteId={siteId} onClose={() => setOpen(false)} onSaved={() => (setOpen(false), load())} />}
    </div>
  );
}

// --- negotiations --------------------------------------------------------------------------------

type Neg = { id: number; asked: string; given: string | null; revision: string | null; by: string | null; at: string };

export function NegotiationLog({ quotationId, tenderId, revisions }: { quotationId?: number; tenderId?: number; revisions?: { id: number; label: string }[] }) {
  const [rows, setRows] = useState<Neg[]>([]);
  const [f, setF] = useState({ asked: "", given: "", rev: "" });
  const [error, setError] = useState("");
  const q = quotationId ? `quotation_id=${quotationId}` : `tender_id=${tenderId}`;
  const load = useCallback(() => {
    void api<Neg[]>(`/api/team/negotiations?${q}`).then(setRows, () => setRows([]));
  }, [q]);
  useEffect(load, [load]);
  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/team/negotiations", {
        method: "POST",
        json: {
          quotation_id: quotationId ?? null,
          tender_id: tenderId ?? null,
          asked: f.asked,
          given: f.given || null,
          ...(f.rev ? (quotationId ? { revision_quotation_id: Number(f.rev) } : { tender_revision_id: Number(f.rev) }) : {}),
        },
      });
      setF({ asked: "", given: "", rev: "" });
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div className="negotiation">
      <h3 className="section-title">Negotiation log</h3>
      {rows.length === 0 && <p className="muted small">Nothing logged yet.</p>}
      <ol className="neg-list">
        {rows.map((r) => (
          <li key={r.id}>
            <div>
              <span className="muted small">Client asked:</span> {r.asked}
            </div>
            {r.given && (
              <div>
                <span className="muted small">We gave:</span> {r.given}
              </div>
            )}
            <div className="small muted">
              {r.by} · {fmt(r.at)} {r.revision && <span className="badge badge-info">→ {r.revision}</span>}
            </div>
          </li>
        ))}
      </ol>
      <form onSubmit={(e) => void add(e)} className="neg-form">
        <input required value={f.asked} placeholder='What the client asked ("match X on this item")' onChange={(e) => setF({ ...f, asked: e.target.value })} />
        <input value={f.given} placeholder="What we gave" onChange={(e) => setF({ ...f, given: e.target.value })} />
        {revisions && revisions.length > 0 && (
          <select value={f.rev} onChange={(e) => setF({ ...f, rev: e.target.value })} aria-label="Revision that followed">
            <option value="">Revision that followed…</option>
            {revisions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        )}
        <button className="btn btn-small">Log</button>
      </form>
      {error && <div className="alert alert-error">{error}</div>}
    </div>
  );
}

// --- tenders: awaiting award, bidders, winner, send checklist ------------------------------------

type Award = {
  status: string;
  submitted_at: string | null;
  last_followup_at: string | null;
  followup_days: number;
  winner_lead_id: number | null;
  bidders: { id: number; name: string; rate: string | null; rank: number | null; label: string | null; is_winner: boolean; is_us: boolean; note: string | null }[];
  send_check: string[];
};

export function TenderAward({ tenderId }: { tenderId: number }) {
  const { can } = useAuth();
  const [a, setA] = useState<Award | null>(null);
  const [b, setB] = useState({ name: "", rate: "", rank: "", is_us: false });
  const [win, setWin] = useState<{ id: number; on: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => {
    void api<Award>(`/api/team/tenders/${tenderId}/award`).then(setA, (e) => setError(errorText(e)));
  }, [tenderId]);
  useEffect(load, [load]);
  if (!a) return <p className="muted">Loading…</p>;
  const edit = can("tender.edit");
  async function addBidder(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/team/tenders/${tenderId}/bidders`, { method: "POST", json: { name: b.name, rate: b.rate || null, rank: b.rank ? Number(b.rank) : null, is_us: b.is_us } });
      setB({ name: "", rate: "", rank: "", is_us: false });
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div className="award">
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="card">
        <p>
          <span className="badge badge-info">{a.status}</span> {a.submitted_at && <>submitted {fmt(a.submitted_at)}</>} · last follow-up {fmt(a.last_followup_at)} · a reminder
          every {a.followup_days} days until won or lost
        </p>
        {a.status === "awaiting award" && (
          <button
            className="btn btn-small"
            onClick={() => {
              const note = prompt("What did the client say?");
              if (note) void api(`/api/team/tenders/${tenderId}/award-followup`, { method: "POST", json: { note } }).then(load, (e) => setError(errorText(e)));
            }}
          >
            Log a follow-up
          </button>
        )}
        {a.send_check.length > 0 && (
          <div className="alert alert-warn top-gap">
            <b>Send checklist:</b> {a.send_check.join("; ")}
          </div>
        )}
      </div>
      <div className="card top-gap">
        <h3 className="section-title">Bidders</h3>
        <table className="table compact">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Contractor</th>
              <th className="num">Rate</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {a.bidders.map((x) => (
              <tr key={x.id} className={x.is_winner ? "row-highlight" : undefined}>
                <td>{x.label ?? "—"}</td>
                <td>
                  {x.name} {x.is_us && <span className="badge badge-ok">us</span>} {x.is_winner && <span className="badge badge-danger">won</span>}
                </td>
                <td className="num">{money(x.rate)}</td>
                <td>
                  {edit && !x.is_us && !x.is_winner && (
                    <button className="btn btn-small btn-ghost" onClick={() => setWin({ id: x.id, on: "" })}>
                      They won
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {edit && (
          <form className="inline-form top-gap" onSubmit={(e) => void addBidder(e)}>
            <input required placeholder="Contractor" value={b.name} onChange={(e) => setB({ ...b, name: e.target.value })} />
            <input placeholder="Rate (₹)" inputMode="decimal" value={b.rate} onChange={(e) => setB({ ...b, rate: e.target.value })} />
            <input placeholder="Rank (1 = L1)" inputMode="numeric" value={b.rank} onChange={(e) => setB({ ...b, rank: e.target.value })} />
            <label className="check">
              <input type="checkbox" checked={b.is_us} onChange={(e) => setB({ ...b, is_us: e.target.checked })} /> us
            </label>
            <button className="btn btn-small">Add bidder</button>
          </form>
        )}
        {a.winner_lead_id && (
          <p className="small top-gap">
            Follow-up with the winner: <Link to={`/leads/${a.winner_lead_id}`}>lead</Link>
          </p>
        )}
      </div>
      <div className="card top-gap">
        <NegotiationLog tenderId={tenderId} />
      </div>
      {win && (
        <Modal title="Another contractor won" onClose={() => setWin(null)}>
          <p className="small muted">
            The tender is closed as lost to them, and a lead is opened with the winner to offer our waterproofing, followed up on the date you pick (their waterproofing stage).
          </p>
          <label className="field">
            <span>Follow up on</span>
            <input type="date" value={win.on} onChange={(e) => setWin({ ...win, on: e.target.value })} />
          </label>
          <div className="form-actions">
            <button
              className="btn btn-primary"
              disabled={!win.on}
              onClick={() =>
                void api<{ lead_code: string }>(`/api/team/tenders/${tenderId}/winner`, { method: "POST", json: { bidder_id: win.id, followup_on: win.on } }).then(
                  (r) => (setWin(null), setMsg(`Lead ${r.lead_code} opened with the winner.`), load()),
                  (e) => setError(errorText(e)),
                )
              }
            >
              Record the winner
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// --- team settings and per-person grants ---------------------------------------------------------

type TeamSettingsT = { billing_day: number; award_followup_days: number; closure_target_percent: string; allocation_recipients: string[]; allocation_sent_at: string | null };

export function TeamSettings() {
  const { can } = useAuth();
  const people = usePeople();
  const [s, setS] = useState<TeamSettingsT | null>(null);
  const [grants, setGrants] = useState<{ user_id: string; permission: string }[]>([]);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    void api<TeamSettingsT>("/api/team/settings").then(setS);
    if (can("grants.manage")) void api<{ user_id: string; permission: string }[]>("/api/team/grants").then(setGrants, () => setGrants([]));
  }, [can]);
  if (!s) return <p className="muted">Loading…</p>;
  const has = (uid: string, code: string) => grants.some((g) => g.user_id === uid && g.permission === code);
  async function toggle(uid: string, code: string) {
    const codes = grants.filter((g) => g.user_id === uid).map((g) => g.permission);
    const next = codes.includes(code) ? codes.filter((c) => c !== code) : [...codes, code];
    await api(`/api/team/users/${uid}/grants`, { method: "PUT", json: { codes: next } });
    setGrants([...grants.filter((g) => g.user_id !== uid), ...next.map((c) => ({ user_id: uid, permission: c }))]);
  }
  return (
    <>
      <div className="page-header">
        <h1>Team</h1>
      </div>
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="card settings-card">
        <div className="form-grid two">
          <label className="field">
            <span>Monthly RA bills: billing gets the to-do on day</span>
            <input type="number" min={1} max={28} value={s.billing_day} onChange={(e) => setS({ ...s, billing_day: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Tender awaiting award: remind every (days)</span>
            <input type="number" min={7} value={s.award_followup_days} onChange={(e) => setS({ ...s, award_followup_days: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Closure rate target (%)</span>
            <input inputMode="decimal" value={s.closure_target_percent} onChange={(e) => setS({ ...s, closure_target_percent: e.target.value })} />
          </label>
          <label className="field">
            <span>Site allocation list goes to</span>
            <select
              multiple
              size={5}
              value={s.allocation_recipients}
              onChange={(e) => setS({ ...s, allocation_recipients: Array.from(e.target.selectedOptions).map((o) => o.value) })}
            >
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          className="btn btn-primary"
          onClick={() =>
            void api<TeamSettingsT>("/api/team/settings", { method: "PUT", json: s }).then(
              (r) => (setS(r), setMsg("Saved.")),
              (e) => setMsg(errorText(e)),
            )
          }
        >
          Save
        </button>
      </div>
      {can("grants.manage") && (
        <>
          <h2 className="section-title top-gap">Allowed per person (the director)</h2>
          <p className="muted small">On top of their roles: costs and margins (for example a planner), or deciding who handles a won job.</p>
          <div className="table-wrap card">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Costs and margins</th>
                  <th>Decides won jobs</th>
                </tr>
              </thead>
              <tbody>
                {people.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name} <span className="muted small">{p.job_title}</span>
                    </td>
                    {["tender.margin", "jobs.assign"].map((code) => (
                      <td key={code}>
                        <input type="checkbox" checked={has(p.id, code)} onChange={() => void toggle(p.id, code)} aria-label={`${p.name} ${code}`} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
