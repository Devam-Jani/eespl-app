import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { AssetOut, Checklist, ChecklistItem, DprRow, Subcontractor, Usage, WorkOrder, Worker } from "../../execution/types";
import { useMaterialLookups } from "../material/common";
import { AssetTable, MoveForm, UsageForm, UsageTable } from "../site/AssetsTab";
import { localToday } from "../site/DprTab";
import { MusterTable, WorkerForm } from "../site/LabourTab";
import { WoStatus } from "../site/WorkOrdersTab";
import { shortDate } from "../Tenders";

type TodayRow = { site_id: number; code: string; name: string; posted: number; present: number; half_day: number; absent: number };

/** Attendance across all sites for a day; each row opens the site's quick mark. */
export function AttendanceToday() {
  const [day, setDay] = useState(localToday());
  const [rows, setRows] = useState<TodayRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"today" | "muster">("today");

  useEffect(() => {
    api<{ sites: TodayRow[] }>(`/api/execution/attendance/today?day=${day}`).then(
      (r) => setRows(r.sites),
      (err) => setError(errorText(err)),
    );
  }, [day]);

  const tot = rows.reduce((s, r) => ({ posted: s.posted + r.posted, present: s.present + r.present, half: s.half + r.half_day, absent: s.absent + r.absent }), {
    posted: 0,
    present: 0,
    half: 0,
    absent: 0,
  });
  return (
    <>
      <div className="page-header">
        <h1>Attendance</h1>
        <div className="page-actions">
          <div className="tabs">
            <button className={`tab ${view === "today" ? "active" : ""}`} onClick={() => setView("today")}>
              By site
            </button>
            <button className={`tab ${view === "muster" ? "active" : ""}`} onClick={() => setView("muster")}>
              Muster roll
            </button>
          </div>
          {view === "today" && <input type="date" value={day} max={localToday()} onChange={(e) => setDay(e.target.value)} aria-label="Day" />}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {view === "muster" ? (
        <MusterTable />
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Site</th>
                <th className="num">Posted</th>
                <th className="num">Present</th>
                <th className="num">Half day</th>
                <th className="num">Absent</th>
                <th className="num">Not marked</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const unmarked = Math.max(0, r.posted - r.present - r.half_day - r.absent);
                return (
                  <tr key={r.site_id}>
                    <td>
                      <Link to={`/sites/${r.site_id}?tab=labour`}>{r.code}</Link> <span className="muted small">{r.name}</span>
                    </td>
                    <td className="num">{r.posted}</td>
                    <td className="num">{r.present}</td>
                    <td className="num">{r.half_day}</td>
                    <td className="num">{r.absent}</td>
                    <td className={`num ${unmarked ? "text-warn" : ""}`}>{unmarked}</td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    No labour at your sites.
                  </td>
                </tr>
              )}
              {rows.length > 0 && (
                <tr className="grand">
                  <td>Total</td>
                  <td className="num">{tot.posted}</td>
                  <td className="num">{tot.present}</td>
                  <td className="num">{tot.half}</td>
                  <td className="num">{tot.absent}</td>
                  <td />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function LabourMaster() {
  const { can } = useAuth();
  const [rows, setRows] = useState<Worker[]>([]);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Worker | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Worker[]>(`/api/execution/labour?active=true${q ? `&q=${encodeURIComponent(q)}` : ""}`).then(setRows, (err) => setError(errorText(err))), [q]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <h1>Labour</h1>
        <div className="page-actions">
          <input className="search" placeholder="Search name or phone" value={q} onChange={(e) => setQ(e.target.value)} />
          {can("labour.edit") && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              Add worker
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Trade</th>
              <th>Type</th>
              <th>Posted at</th>
              <th className="num">Wage</th>
              <th className="num">OT / h</th>
              <th>Aadhaar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((w) => (
              <tr key={w.id} className={can("labour.edit") ? "clickable" : ""} onClick={() => can("labour.edit") && setEditing(w)}>
                <td>
                  {w.name} <span className="muted small">{w.phone ?? ""}</span>
                </td>
                <td>{w.trade}</td>
                <td>{w.type === "own" ? "Own" : w.subcontractor_name}</td>
                <td>{w.site_code ?? "—"}</td>
                <td className="num">{inr(w.daily_wage)}</td>
                <td className="num">{inr(w.ot_rate_per_hour)}</td>
                <td>{w.aadhaar_last4 ? `••••${w.aadhaar_last4}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <WorkerForm worker={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={() => (setEditing(null), void load())} />}
    </>
  );
}

export function Subcontractors() {
  const [subs, setSubs] = useState<Subcontractor[]>([]);
  const [wos, setWos] = useState<WorkOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Subcontractor[]>("/api/execution/subcontractors").then(setSubs, (err) => setError(errorText(err)));
    api<WorkOrder[]>("/api/execution/work-orders").then(setWos, () => setWos([]));
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Subcontractors</h1>
        <p className="muted small">
          Add or edit them in <Link to="/vendors">Vendors</Link> (type: subcontractor).
        </p>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>PAN</th>
              <th>GSTIN</th>
              <th>Bank</th>
              <th className="num">TDS</th>
              <th className="num">Work orders</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.name} <span className="muted small">{s.city ?? ""}</span>
                </td>
                <td>{s.pan ?? "—"}</td>
                <td>{s.gstin ?? "—"}</td>
                <td>{s.bank ?? "—"}</td>
                <td className="num">{num(s.tds_percent)}%</td>
                <td className="num">{s.work_orders}</td>
              </tr>
            ))}
            {subs.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No subcontractors yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h2 className="section-title top-gap">Work orders</h2>
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>WO</th>
              <th>Site</th>
              <th>Subcontractor</th>
              <th className="num">Value</th>
              <th className="num">Billable to date</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {wos.map((w) => (
              <tr key={w.id}>
                <td>
                  <code>{w.code}</code>
                </td>
                <td>
                  <Link to={`/sites/${w.site_id}?tab=workorders`}>{w.site_code}</Link>
                </td>
                <td>{w.subcontractor_name}</td>
                <td className="num">{inr(w.amount)}</td>
                <td className="num">{inr(w.billable_to_date)}</td>
                <td>
                  <WoStatus status={w.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type CostRow = { site_id: number; site_code: string; site_name: string; amount: string; fuel_cost: string; entries: number };

export function Assets() {
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [view, setView] = useState<"all" | "overdue" | "usage">("all");
  const [usage, setUsage] = useState<Usage[]>([]);
  const [cost, setCost] = useState<CostRow[]>([]);
  const [moving, setMoving] = useState<AssetOut | null>(null);
  const [logging, setLogging] = useState<AssetOut | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const edit = can("asset.edit");

  const load = useCallback(async () => {
    try {
      setAssets(await api<AssetOut[]>(`/api/execution/assets${view === "overdue" ? "?overdue=true" : ""}`));
      if (view === "usage") {
        setUsage(await api<Usage[]>("/api/execution/equipment-usage"));
        setCost(await api<CostRow[]>("/api/execution/equipment-cost"));
      }
    } catch (err) {
      setError(errorText(err));
    }
  }, [view]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Tools &amp; equipment</h1>
        <div className="page-actions">
          <div className="tabs">
            {(
              [
                ["all", "Where is everything"],
                ["overdue", "Overdue at sites"],
                ["usage", "Equipment cost"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} className={`tab ${view === k ? "active" : ""}`} onClick={() => setView(k)}>
                {l}
              </button>
            ))}
          </div>
          {edit && (
            <button className="btn btn-primary" onClick={() => setAdding(true)}>
              Add asset
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {view !== "usage" ? (
        <AssetTable assets={assets} onMove={edit ? setMoving : undefined} onUsage={edit ? setLogging : undefined} />
      ) : (
        <>
          <div className="card table-wrap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Site</th>
                  <th className="num">Entries</th>
                  <th className="num">Fuel</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {cost.map((c) => (
                  <tr key={c.site_id}>
                    <td>
                      {c.site_code} <span className="muted small">{c.site_name}</span>
                    </td>
                    <td className="num">{c.entries}</td>
                    <td className="num">{inr(c.fuel_cost)}</td>
                    <td className="num">{inr(c.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2 className="section-title top-gap">Usage (90 days)</h2>
          <UsageTable rows={usage} showSite />
        </>
      )}
      {moving && lookups && <MoveForm asset={moving} lookups={lookups} onClose={() => setMoving(null)} onSaved={() => (setMoving(null), void load())} />}
      {logging && <UsageForm asset={logging} onClose={() => setLogging(null)} onSaved={() => (setLogging(null), void load())} />}
      {adding && <AssetForm onClose={() => setAdding(false)} onSaved={() => (setAdding(false), void load())} />}
    </>
  );
}

function AssetForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const lookups = useMaterialLookups();
  const [form, setForm] = useState({
    name: "",
    category: "tool",
    make: "",
    model: "",
    serial_no: "",
    purchase_date: "",
    purchase_value: "",
    ownership: "own",
    vendor_id: "",
    rate_per_hour: "",
    rate_per_day: "",
  });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const json = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    try {
      await api("/api/execution/assets", { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title="Add an asset" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Name *</span>
            <input required value={form.name} onChange={set("name")} />
          </label>
          <label className="field">
            <span>Category</span>
            <select value={form.category} onChange={set("category")}>
              {["tool", "equipment", "machine", "vehicle"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Make</span>
            <input value={form.make} onChange={set("make")} />
          </label>
          <label className="field">
            <span>Model</span>
            <input value={form.model} onChange={set("model")} />
          </label>
          <label className="field">
            <span>Serial no</span>
            <input value={form.serial_no} onChange={set("serial_no")} />
          </label>
          <label className="field">
            <span>Ownership</span>
            <select value={form.ownership} onChange={set("ownership")}>
              <option value="own">Own</option>
              <option value="hired">Hired</option>
            </select>
          </label>
          {form.ownership === "hired" && (
            <label className="field">
              <span>Hired from *</span>
              <select required value={form.vendor_id} onChange={set("vendor_id")}>
                <option value="">—</option>
                {lookups?.vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>Purchase date</span>
            <input type="date" value={form.purchase_date} onChange={set("purchase_date")} />
          </label>
          <label className="field">
            <span>Purchase value (₹)</span>
            <input inputMode="decimal" value={form.purchase_value} onChange={set("purchase_value")} />
          </label>
          <label className="field">
            <span>Rate per day (₹)</span>
            <input inputMode="decimal" value={form.rate_per_day} onChange={set("rate_per_day")} />
          </label>
          <label className="field">
            <span>Rate per hour (₹)</span>
            <input inputMode="decimal" value={form.rate_per_hour} onChange={set("rate_per_hour")} />
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Add (kept in the godown)</button>
        </div>
      </form>
    </Modal>
  );
}

/** DPRs missing (after 8 pm) and the latest reports, across the caller's sites. */
export function DailyReports() {
  const [missing, setMissing] = useState<{ day: string; count: number; sites: { id: number; code: string; name: string }[] } | null>(null);
  const [rows, setRows] = useState<DprRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<typeof missing>("/api/execution/dprs/missing").then(setMissing, (err) => setError(errorText(err)));
    api<DprRow[]>("/api/execution/dprs?days=14").then(setRows, () => setRows([]));
  }, []);
  return (
    <>
      <h1>Daily progress reports</h1>
      {error && <div className="alert alert-error">{error}</div>}
      {missing && (
        <div className={`alert ${missing.count ? "alert-warn" : "alert-ok"}`}>
          {missing.count ? `${missing.count} active site(s) without a DPR for ${shortDate(missing.day)}:` : `Every active site sent its DPR for ${shortDate(missing.day)}.`}
          {missing.sites.map((s) => (
            <span key={s.id}>
              {" "}
              <Link to={`/sites/${s.id}?tab=dpr`}>{s.code}</Link>
            </span>
          ))}
        </div>
      )}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Site</th>
              <th>Status</th>
              <th>Weather</th>
              <th>By</th>
              <th className="num">Photos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{shortDate(r.on_date)}</td>
                <td>
                  <Link to={`/sites/${r.site_id}?tab=dpr`}>{r.site_code}</Link> <span className="muted small">{r.site_name}</span>
                </td>
                <td>{r.status}</td>
                <td>{r.weather ?? ""}</td>
                <td>{r.submitted_by_name ?? ""}</td>
                <td className="num">{r.photos}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

type ItemForm = { id?: number; text: string; type: ChecklistItem["type"]; required: boolean };

export function Checklists() {
  const { me } = useAuth();
  const canEdit = me?.permissions["inspection.edit"] === "all";
  const [list, setList] = useState<Checklist[]>([]);
  const [editing, setEditing] = useState<{ id?: number; name: string; is_active: boolean; items: ItemForm[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Checklist[]>("/api/execution/checklists").then(setList, (err) => setError(errorText(err))), []);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    try {
      await api(editing.id ? `/api/execution/checklists/${editing.id}` : "/api/execution/checklists", { method: editing.id ? "PUT" : "POST", json: editing });
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const setItem = (i: number, patch: Partial<ItemForm>) => editing && setEditing({ ...editing, items: editing.items.map((it, j) => (j === i ? { ...it, ...patch } : it)) });
  return (
    <>
      <div className="page-header">
        <h1>Checklist templates</h1>
        {canEdit && (
          <button className="btn btn-primary" onClick={() => setEditing({ name: "", is_active: true, items: [{ text: "", type: "pass_fail", required: true }] })}>
            New checklist
          </button>
        )}
      </div>
      <p className="muted small">Pick a checklist on a hold-point step in Settings › Stage templates: the step is then certified only after a passed inspection.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {list.map((c) => (
        <div key={c.id} className="card top-gap">
          <div className="toolbar">
            <b>
              {c.name} {!c.is_active && <span className="badge badge-muted">inactive</span>}
            </b>
            {canEdit && (
              <button className="btn btn-small" onClick={() => setEditing({ ...c, items: c.items.map((i) => ({ ...i })) })}>
                Edit
              </button>
            )}
          </div>
          <ol className="small">
            {c.items.map((i) => (
              <li key={i.id}>
                {i.text}{" "}
                <span className="muted">
                  ({i.type.replace("_", "/")}
                  {i.required ? ", required" : ""})
                </span>
              </li>
            ))}
          </ol>
        </div>
      ))}
      {editing && (
        <Modal title={editing.id ? "Edit checklist" : "New checklist"} onClose={() => setEditing(null)} wide>
          <form onSubmit={save}>
            <label className="field">
              <span>Name</span>
              <input required value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </label>
            {editing.items.map((it, i) => (
              <div key={i} className="line-row">
                <input className="grow" required value={it.text} onChange={(e) => setItem(i, { text: e.target.value })} aria-label="Check" />
                <select value={it.type} onChange={(e) => setItem(i, { type: e.target.value as ItemForm["type"] })}>
                  <option value="pass_fail">pass / fail</option>
                  <option value="number">number</option>
                  <option value="text">text</option>
                  <option value="photo">photo</option>
                </select>
                <label className="check">
                  <input type="checkbox" checked={it.required} onChange={(e) => setItem(i, { required: e.target.checked })} /> required
                </label>
                <button type="button" className="btn btn-ghost btn-icon" onClick={() => setEditing({ ...editing, items: editing.items.filter((_, j) => j !== i) })}>
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-small top-gap"
              onClick={() => setEditing({ ...editing, items: [...editing.items, { text: "", type: "pass_fail", required: true }] })}
            >
              + Item
            </button>
            <label className="check top-gap">
              <input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} /> Active
            </label>
            <div className="form-actions">
              <button className="btn btn-primary">Save</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
