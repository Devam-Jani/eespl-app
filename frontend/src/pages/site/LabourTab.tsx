import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText, inr, num, showError } from "../../format";
import type { AttendanceStatus, DaySheet, MusterRow, Subcontractor, Worker } from "../../execution/types";
import type { Site } from "../../types";
import { localToday } from "./DprTab";
import { Button, buttonClass, Card, Field } from "../../ui/components";

const MARKS: [AttendanceStatus, string][] = [
  ["present", "P"],
  ["half_day", "½"],
  ["absent", "A"],
];
export const TRADES = ["applicator", "helper", "mason", "supervisor", "other"];

// hours: a gang paid by attendance (the month's bill splits by site)
type Draft = Record<number, { status: AttendanceStatus | null; ot_hours: string; hours?: string }>;

/** Quick mark: one tap per worker (P / ½ / A), "all present", then Save. Built for a phone. */
export function QuickMark({ site, onSaved, onAddWorker }: { site: Site; onSaved?: () => void; onAddWorker?: () => void }) {
  const { can } = useAuth();
  const [day, setDay] = useState(localToday());
  const [sheet, setSheet] = useState<DaySheet | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canEdit = can("labour.edit") || can("attendance.manage"); // marking: either, on the site (the server checks which sites)

  const show = (s: DaySheet) => {
    setSheet(s);
    setDraft(Object.fromEntries(s.rows.map((r) => [r.labour_id, { status: r.status, ot_hours: Number(r.ot_hours) ? r.ot_hours : "", hours: r.hours ?? "" }])));
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      show(await api<DaySheet>(`/api/execution/sites/${site.id}/attendance/${day}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id, day]);

  useEffect(() => {
    void load();
  }, [load]);

  function where(): Promise<{ lat?: number; lng?: number }> {
    return new Promise((resolve) => {
      if (!navigator.geolocation) return resolve({});
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: Number(p.coords.latitude.toFixed(6)), lng: Number(p.coords.longitude.toFixed(6)) }),
        () => resolve({}),
        { timeout: 4000, maximumAge: 600000 },
      );
    });
  }

  async function save() {
    const marks = Object.entries(draft)
      .filter(([, d]) => d.status)
      .map(([id, d]) => ({
        labour_id: Number(id),
        status: d.status,
        ot_hours: d.status === "absent" ? "0" : d.ot_hours || "0",
        hours: d.status !== "absent" && d.hours ? d.hours : null,
      }));
    if (!marks.length) return;
    setBusy(true);
    setError(null);
    try {
      show(await api<DaySheet>(`/api/execution/sites/${site.id}/attendance/${day}`, { method: "PUT", json: { marks, ...(await where()) } }));
      setMessage(`Saved ${marks.length} mark(s).`);
      onSaved?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function photo(files: FileList | null) {
    if (!files?.length) return;
    const form = new FormData();
    form.append("file", files[0]);
    try {
      show(await api<DaySheet>(`/api/execution/sites/${site.id}/attendance/${day}/photo`, { method: "POST", form }));
      setMessage("Group photo added.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  const rows = sheet?.rows ?? [];
  const set = (id: number, patch: Partial<Draft[number]>) => setDraft((d) => ({ ...d, [id]: { ...d[id], ...patch } }));
  const marked = Object.values(draft).filter((d) => d.status).length;

  return (
    <div className="daily">
      <div className="daily-head">
        <Field label="Day" bare>
          <input type="date" className="tap-input" value={day} max={localToday()} onChange={(e) => setDay(e.target.value)} aria-label="Day" />
        </Field>
        {sheet && (
          <span className="small">
            P {sheet.counts.present} · ½ {sheet.counts.half_day} · A {sheet.counts.absent}
          </span>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      {canEdit && rows.length > 0 && (
        <Button
          className="tap-wide"
          onClick={() =>
            setDraft((d) => Object.fromEntries(rows.map((r) => [r.labour_id, r.elsewhere ? d[r.labour_id] : { ...d[r.labour_id], status: "present" as AttendanceStatus }])))
          }
        >
          ✓ Mark all present
        </Button>
      )}
      <ul className="mark-list with-sticky-bar">
        {rows.map((r) => {
          const d = draft[r.labour_id] ?? { status: null, ot_hours: "" };
          return (
            <li key={r.labour_id} className={`mark-row ${d.status ?? "unmarked"}`}>
              <div className="mark-who">
                <b>{r.name}</b>
                <span className="small muted">
                  {r.trade}
                  {r.subcontractor_name ? ` · ${r.subcontractor_name}` : ""}
                </span>
                {r.elsewhere && <span className="small text-danger">Marked at {r.elsewhere}</span>}
              </div>
              <div className="mark-buttons" role="group" aria-label={`Attendance of ${r.name}`}>
                {MARKS.map(([status, label]) => (
                  <button
                    key={status}
                    type="button"
                    disabled={!canEdit || !!r.elsewhere}
                    className={`tap mark-${status} ${d.status === status ? "on" : ""}`}
                    aria-pressed={d.status === status}
                    aria-label={`${r.name}: ${status.replace("_", " ")}`}
                    onClick={() => set(r.labour_id, { status })}
                  >
                    {label}
                  </button>
                ))}
                {d.status && d.status !== "absent" && r.type === "subcontractor" && (
                  <Field label="Hours here" inline className="ot-field">
                    <input
                      className="tap-input ot"
                      inputMode="decimal"
                      placeholder="8"
                      aria-label={`${r.name}: hours on this site`}
                      disabled={!canEdit}
                      value={d.hours ?? ""}
                      onChange={(e) => set(r.labour_id, { hours: e.target.value })}
                    />
                  </Field>
                )}
                {d.status && d.status !== "absent" && (
                  <Field label="OT hrs" inline className="ot-field">
                    <input
                      className="tap-input ot"
                      inputMode="decimal"
                      placeholder="OT h"
                      aria-label={`${r.name}: overtime hours`}
                      disabled={!canEdit}
                      value={d.ot_hours}
                      onChange={(e) => set(r.labour_id, { ot_hours: e.target.value })}
                    />
                  </Field>
                )}
              </div>
            </li>
          );
        })}
        {sheet && rows.length === 0 && (
          <li className="muted">
            No workers posted to this site.{" "}
            {onAddWorker && can("labour.edit") && (
              <Button size="small" onClick={onAddWorker}>
                Add worker
              </Button>
            )}
          </li>
        )}
      </ul>
      {canEdit && rows.length > 0 && (
        <div className="daily-actions sticky-actions">
          <label className={buttonClass({ className: "tap-wide" })}>
            📷 Group photo
            <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => void photo(e.target.files)} />
          </label>
          <Button variant="primary" className="tap-wide" disabled={busy || !marked} onClick={() => void save()}>
            Save attendance ({marked})
          </Button>
        </div>
      )}
    </div>
  );
}

export function WorkerForm({ worker, siteId, onClose, onSaved }: { worker?: Worker; siteId?: number | null; onClose: () => void; onSaved: () => void }) {
  const [subs, setSubs] = useState<Subcontractor[]>([]);
  const [form, setForm] = useState({
    name: worker?.name ?? "",
    phone: worker?.phone ?? "",
    trade: worker?.trade ?? "helper",
    type: worker?.type ?? "own",
    subcontractor_id: worker?.subcontractor_id ?? ("" as number | ""),
    site_id: worker?.site_id ?? siteId ?? ("" as number | ""),
    daily_wage: worker?.daily_wage ?? "",
    ot_rate_per_hour: worker?.ot_rate_per_hour ?? "",
    aadhaar: "",
    is_active: worker?.is_active ?? true,
  });
  const [error, setError] = useState<string | null>(null);

  // the Labour page has no site of its own: pick one of the caller's sites (a site supervisor must)
  const [sites, setSites] = useState<{ id: number; code: string; name: string }[]>([]);
  useEffect(() => {
    api<Subcontractor[]>("/api/execution/subcontractors").then(setSubs, () => setSubs([]));
    if (siteId === undefined) api<{ id: number; code: string; name: string }[]>("/api/execution/labour/sites").then(setSites, () => setSites([]));
  }, [siteId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const json = {
      ...form,
      phone: form.phone || null,
      subcontractor_id: form.type === "subcontractor" ? form.subcontractor_id || null : null,
      site_id: form.site_id || null,
      daily_wage: form.daily_wage || "0",
      ot_rate_per_hour: form.ot_rate_per_hour || "0",
      aadhaar: form.aadhaar || null,
    };
    try {
      await api(worker ? `/api/execution/labour/${worker.id}` : "/api/execution/labour", { method: worker ? "PUT" : "POST", json });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title={worker ? `Edit ${worker.name}` : "Add a worker"} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <Field label="Name *">
            <input required value={form.name} onChange={set("name")} />
          </Field>
          <Field label="Phone">
            <input inputMode="tel" value={form.phone} onChange={set("phone")} />
          </Field>
          <Field label="Trade">
            <select value={form.trade} onChange={set("trade")}>
              {TRADES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Type">
            <select value={form.type} onChange={set("type")}>
              <option value="own">Own labour</option>
              <option value="subcontractor">From a subcontractor</option>
            </select>
          </Field>
          {form.type === "subcontractor" && (
            <Field label="Subcontractor *">
              <select required value={form.subcontractor_id} onChange={(e) => setForm({ ...form, subcontractor_id: Number(e.target.value) || "" })}>
                <option value="">—</option>
                {subs.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {siteId === undefined && (
            <Field label="Posted at" hint="The sites you can post a worker to">
              <select value={form.site_id} onChange={(e) => setForm({ ...form, site_id: Number(e.target.value) || "" })}>
                <option value="">— not posted —</option>
                {worker?.site_id && !sites.some((s) => s.id === worker.site_id) && <option value={worker.site_id}>{worker.site_code ?? `Site ${worker.site_id}`}</option>}
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} {s.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Daily wage (₹)">
            <input inputMode="decimal" value={form.daily_wage} onChange={set("daily_wage")} />
          </Field>
          <Field label="OT rate per hour (₹)">
            <input inputMode="decimal" value={form.ot_rate_per_hour} onChange={set("ot_rate_per_hour")} />
          </Field>
          <Field label={<>Aadhaar (last 4 digits{worker?.aadhaar_last4 ? `; now ••••${worker.aadhaar_last4}` : ""})</>}>
            <input inputMode="numeric" maxLength={14} value={form.aadhaar} onChange={set("aadhaar")} placeholder="Only the last 4 are kept" autoComplete="off" />
          </Field>
        </div>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">Save</Button>
        </div>
      </form>
    </Modal>
  );
}

export function MusterTable({ siteId }: { siteId?: number }) {
  const now = localToday().slice(0, 7);
  const [month, setMonth] = useState(now);
  const [data, setData] = useState<{ rows: MusterRow[]; wage_due: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = `month=${month}${siteId ? `&site_id=${siteId}` : ""}`;

  useEffect(() => {
    api<{ rows: MusterRow[]; wage_due: string }>(`/api/execution/muster?${q}`).then(setData, (err) => setError(errorText(err)));
  }, [q]);

  return (
    <>
      <div className="toolbar">
        <Field label="Month" bare>
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
        </Field>
        <Button onClick={() => void downloadFile(`/api/execution/muster/export?${q}`).catch((err) => setError(errorText(err)))}>
          Excel
        </Button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div" className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              {!siteId && <th>Site</th>}
              <th>Worker</th>
              <th className="num">Days</th>
              <th className="num">Half days</th>
              <th className="num">OT h</th>
              <th className="num">Wage</th>
              <th className="num">Due</th>
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((r) => (
              <tr key={`${r.labour_id}-${r.site_id}`}>
                {!siteId && <td>{r.site_code}</td>}
                <td>
                  {r.name} <span className="muted small">{r.type === "own" ? r.trade : "subcontractor"}</span>
                </td>
                <td className="num">{num(r.days)}</td>
                <td className="num">{r.half_days}</td>
                <td className="num">{num(r.ot_hours)}</td>
                <td className="num">{inr(r.daily_wage)}</td>
                <td className="num">{inr(r.wage_due)}</td>
              </tr>
            ))}
            {data && (
              <tr className="grand">
                <td colSpan={siteId ? 5 : 6}>Wage due</td>
                <td className="num">
                  <b>{inr(data.wage_due)}</b>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </>
  );
}

export default function LabourTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [view, setView] = useState<"mark" | "workers" | "muster">("mark");
  const [editing, setEditing] = useState<Worker | null | "new">(null);
  const [key, setKey] = useState(0);

  const load = useCallback(() => api<Worker[]>(`/api/execution/labour?site_id=${site.id}`).then(setWorkers, () => setWorkers([])), [site.id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function checkIn(out: boolean) {
    try {
      await api(out ? "/api/execution/check-out" : `/api/execution/sites/${site.id}/check-in`, { method: "POST", json: out ? undefined : {} });
      alert(out ? "Checked out." : `Checked in at ${site.code}.`);
    } catch (err) {
      showError(err);
    }
  }

  return (
    <>
      <div className="tabs tabs-inline wrap-row">
        {(
          [
            ["mark", "Quick mark"],
            ["workers", `Workers (${workers.length})`],
            ["muster", "Muster roll"],
          ] as const
        ).map(([k, l]) => (
          <button key={k} className={`tab ${view === k ? "active" : ""}`} onClick={() => setView(k)}>
            {l}
          </button>
        ))}
        <span className="push-right" />
        <Button size="small" onClick={() => void checkIn(false)}>
          Staff check-in
        </Button>
        <Button size="small" onClick={() => void checkIn(true)}>
          Check-out
        </Button>
      </div>
      <div className="top-gap">
        {view === "mark" && <QuickMark key={key} site={site} onAddWorker={() => setEditing("new")} />}
        {view === "workers" && (
          <>
            {can("labour.edit") && (
              <Button variant="primary" onClick={() => setEditing("new")}>
                Add worker
              </Button>
            )}
            <Card as="div" className="table-wrap top-gap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trade</th>
                    <th>Type</th>
                    <th className="num">Wage / OT</th>
                    <th>Aadhaar</th>
                  </tr>
                </thead>
                <tbody>
                  {workers.map((w) => (
                    <tr key={w.id} className={can("labour.edit") ? "clickable" : ""} onClick={() => can("labour.edit") && setEditing(w)}>
                      <td>
                        {w.name} <span className="muted small">{w.phone ?? ""}</span>
                      </td>
                      <td>{w.trade}</td>
                      <td>{w.type === "own" ? "Own" : w.subcontractor_name}</td>
                      <td className="num">
                        {inr(w.daily_wage)} / {inr(w.ot_rate_per_hour)}
                      </td>
                      <td>{w.aadhaar_last4 ? `••••${w.aadhaar_last4}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}
        {view === "muster" && <MusterTable siteId={site.id} />}
      </div>
      {editing && (
        <WorkerForm
          worker={editing === "new" ? undefined : editing}
          siteId={site.id}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setKey((k) => k + 1);
            void load();
          }}
        />
      )}
    </>
  );
}
