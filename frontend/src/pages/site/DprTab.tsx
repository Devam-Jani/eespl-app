import { useCallback, useEffect, useState } from "react";
import { api, downloadFile } from "../../api";
import { errorText, inr } from "../../format";
import type { Dpr, DprRow } from "../../execution/types";
import type { Site } from "../../types";
import { shortDate } from "../Tenders";

export const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const WEATHER = ["Sunny", "Cloudy", "Light rain", "Heavy rain", "Hot", "Windy"];
const STATUS_BADGE: Record<string, string> = { new: "badge-muted", draft: "badge-warn", submitted: "badge-info", acknowledged: "badge-ok" };

/** The day's report: what was recorded on site is pulled in; the supervisor adds the story. */
export default function DprTab({ site }: { site: Site }) {
  const [day, setDay] = useState(localToday());
  const [dpr, setDpr] = useState<Dpr | null>(null);
  const [form, setForm] = useState({ weather: "", work_done: "", hindrances: "", next_day_plan: "" });
  const [recent, setRecent] = useState<DprRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [allTasks, setAllTasks] = useState(false);

  const show = (d: Dpr) => {
    setDpr(d);
    setForm({ weather: d.weather ?? "", work_done: d.work_done ?? "", hindrances: d.hindrances ?? "", next_day_plan: d.next_day_plan ?? "" });
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      show(await api<Dpr>(`/api/execution/sites/${site.id}/dprs/${day}`));
      setRecent(await api<DprRow[]>(`/api/execution/dprs?site_id=${site.id}&days=31`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id, day]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(submit: boolean) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      show(await api<Dpr>(`/api/execution/sites/${site.id}/dprs/${day}`, { method: "PUT", json: { ...form, weather: form.weather || null, submit } }));
      setMessage(submit ? "Submitted." : "Saved as draft.");
      setRecent(await api<DprRow[]>(`/api/execution/dprs?site_id=${site.id}&days=31`));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function addPhotos(files: FileList | null) {
    if (!files) return;
    setError(null);
    try {
      for (const f of Array.from(files)) {
        const body = new FormData();
        body.append("file", f);
        show(await api<Dpr>(`/api/execution/sites/${site.id}/dprs/${day}/photos`, { method: "POST", form: body }));
      }
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function acknowledge() {
    if (!dpr?.id) return;
    try {
      show(await api<Dpr>(`/api/execution/dprs/${dpr.id}/acknowledge`, { method: "POST" }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const a = dpr?.auto;
  const edit = dpr?.can_edit ?? false;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="daily">
      <div className="daily-head">
        <input type="date" value={day} max={localToday()} onChange={(e) => setDay(e.target.value)} aria-label="Day" className="tap-input" />
        {dpr && <span className={`badge ${STATUS_BADGE[dpr.status]}`}>{dpr.status === "new" ? "Not started" : dpr.status}</span>}
        {dpr?.id && dpr.status !== "draft" && (
          <button className="btn" onClick={() => void downloadFile(`/api/execution/dprs/${dpr.id}/pdf`).catch((err) => setError(errorText(err)))}>
            PDF
          </button>
        )}
        {dpr?.can_acknowledge && (
          <button className="btn" onClick={() => void acknowledge()}>
            Acknowledge
          </button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      {dpr && a && (
        <>
          <div className="card daily-card">
            <h2 className="section-title">Recorded today</h2>
            <div className="chips">
              <span className="chip">
                Labour: <b>{a.labour.present}</b> present{a.labour.half_day ? `, ${a.labour.half_day} half` : ""}
              </span>
              <span className="chip">Task updates: {a.tasks.length}</span>
              <span className="chip">Material in: {a.received.length}</span>
              <span className="chip">Issued: {a.issued.length}</span>
              <span className="chip">Equipment: {a.equipment.length}</span>
            </div>
            {a.tasks.length > 0 && (
              <ul className="plain-list small top-gap">
                {(allTasks ? a.tasks : a.tasks.slice(0, 5)).map((t) => (
                  <li key={t.id}>
                    {t.where && <span className="muted">{t.where} · </span>}
                    {t.name}: <b>{Math.round(t.percent)}%</b> ({t.status.replace("_", " ")}){t.photos.length > 0 && ` · ${t.photos.length} photo(s)`}
                  </li>
                ))}
                {a.tasks.length > 5 && (
                  <li>
                    <button type="button" className="btn btn-small btn-ghost" onClick={() => setAllTasks(!allTasks)}>
                      {allTasks ? "Show fewer" : `Show all ${a.tasks.length} task updates`}
                    </button>
                  </li>
                )}
              </ul>
            )}
            {(a.received.length > 0 || a.issued.length > 0) && (
              <ul className="plain-list small top-gap">
                {a.received.map((r) => (
                  <li key={r.code}>
                    In <code>{r.code}</code> from {r.from}: {r.items}
                  </li>
                ))}
                {a.issued.map((r) => (
                  <li key={r.code}>
                    {r.kind === "issue" ? "Issued" : "Returned"} <code>{r.code}</code>
                    {r.for ? ` for ${r.for}` : ""}: {r.items} ({inr(r.value)})
                  </li>
                ))}
              </ul>
            )}
            {a.equipment.length > 0 && (
              <ul className="plain-list small top-gap">
                {a.equipment.map((u, i) => (
                  <li key={i}>
                    {u.asset}: {u.quantity} {u.basis}(s){u.operator ? ` · ${u.operator}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="card daily-card top-gap">
            <label className="field">
              <span>Weather</span>
              <div className="tap-group">
                {WEATHER.map((w) => (
                  <button key={w} type="button" disabled={!edit} className={`tap ${form.weather === w ? "on" : ""}`} onClick={() => setForm({ ...form, weather: w })}>
                    {w}
                  </button>
                ))}
              </div>
            </label>
            <label className="field">
              <span>Work done today *</span>
              <textarea rows={4} disabled={!edit} value={form.work_done} onChange={set("work_done")} placeholder="Where, what, how much" />
            </label>
            <label className="field">
              <span>Hindrances</span>
              <textarea rows={2} disabled={!edit} value={form.hindrances} onChange={set("hindrances")} placeholder="Rain, material short, area not handed over…" />
            </label>
            <label className="field">
              <span>Plan for tomorrow</span>
              <textarea rows={2} disabled={!edit} value={form.next_day_plan} onChange={set("next_day_plan")} />
            </label>
            <div className="field">
              <span>Photos ({dpr.photos.length})</span>
              {edit && (
                <label className="btn tap-wide">
                  📷 Take / add photos
                  <input type="file" accept="image/*" capture="environment" multiple hidden onChange={(e) => void addPhotos(e.target.files)} />
                </label>
              )}
              <ul className="plain-list small">
                {dpr.photos.map((p) => (
                  <li key={p.id}>{p.filename}</li>
                ))}
              </ul>
            </div>
            {edit ? (
              <div className="daily-actions">
                <button className="btn tap-wide" disabled={busy} onClick={() => void save(false)}>
                  Save draft
                </button>
                <button className="btn btn-primary tap-wide" disabled={busy || !form.work_done.trim()} onClick={() => void save(true)}>
                  Submit DPR
                </button>
              </div>
            ) : (
              dpr.submitted_by_name && (
                <p className="muted small">
                  Submitted by {dpr.submitted_by_name}
                  {dpr.acknowledged_by_name && ` · acknowledged by ${dpr.acknowledged_by_name}`}
                </p>
              )
            )}
          </div>
        </>
      )}
      <h2 className="section-title top-gap">Last 31 days</h2>
      <div className="card table-wrap">
        <table className="table compact">
          <tbody>
            {recent.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => setDay(r.on_date)}>
                <td className="nowrap">{shortDate(r.on_date)}</td>
                <td>
                  <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                </td>
                <td>{r.weather ?? ""}</td>
                <td className="small muted">{r.submitted_by_name ?? ""}</td>
              </tr>
            ))}
            {recent.length === 0 && (
              <tr>
                <td className="empty">No reports yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
