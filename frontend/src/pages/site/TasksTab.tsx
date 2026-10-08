import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fetchObjectUrl, queryString } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, num } from "../../format";
import type { Site, SiteTask } from "../../types";
import { shortDate } from "../Tenders";

const STATUS: Record<string, [string, string]> = {
  not_started: ["badge-muted", "Not started"],
  in_progress: ["badge-info", "In progress"],
  done: ["badge-warn", "Done"],
  certified: ["badge-ok", "Certified"],
  blocked: ["badge-danger", "Blocked"],
};
const DAY = 86_400_000;

export default function TasksTab({ site, onChange }: { site: Site; onChange: () => void }) {
  const { can } = useAuth();
  const canUpdate = can("site.update", "site.edit");
  const canEdit = can("site.edit");
  const [tasks, setTasks] = useState<SiteTask[]>([]);
  const [filter, setFilter] = useState("");
  const [view, setView] = useState<"list" | "gantt">("list");
  const [open, setOpen] = useState<SiteTask | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTasks(await api<SiteTask[]>(`/api/sites/${site.id}/tasks${queryString({ filter })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id, filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => {
    const out: [string, SiteTask[]][] = [];
    for (const t of tasks) {
      const key = t.node_path ?? "Site";
      const last = out[out.length - 1];
      if (last && last[0] === key) last[1].push(t);
      else out.push([key, [t]]);
    }
    return out;
  }, [tasks]);

  return (
    <div className="card">
      <div className="toolbar">
        <h2 className="section-title">Tasks ({tasks.length})</h2>
        <div className="page-actions">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All tasks</option>
            <option value="late">Late</option>
            <option value="blocked">Blocked</option>
            <option value="pending_certification">Waiting for certification</option>
          </select>
          <div className="tabs">
            <button className={`tab ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
              List
            </button>
            <button className={`tab ${view === "gantt" ? "active" : ""}`} onClick={() => setView("gantt")}>
              Gantt
            </button>
          </div>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tasks.length === 0 && <p className="empty">No tasks. Assign the BOQ to areas on the Scope tab, then "Generate tasks".</p>}
      {view === "list" ? (
        <table className="table compact">
          <thead>
            <tr>
              <th>Step</th>
              <th className="num">Weight</th>
              <th>Planned</th>
              <th>Actual</th>
              <th>Status</th>
              <th>Assignee</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([path, list]) => (
              <GroupRows key={path} path={path} list={list} onOpen={setOpen} />
            ))}
          </tbody>
        </table>
      ) : (
        <Gantt groups={groups} onOpen={setOpen} />
      )}
      {open && (
        <TaskDialog
          site={site}
          task={open}
          canUpdate={canUpdate}
          canEdit={canEdit}
          onClose={() => setOpen(null)}
          onSaved={(t) => {
            setOpen(t);
            void load();
            onChange();
          }}
        />
      )}
    </div>
  );
}

function GroupRows({ path, list, onOpen }: { path: string; list: SiteTask[]; onOpen: (t: SiteTask) => void }) {
  return (
    <>
      <tr className="boq-section">
        <td colSpan={6}>
          <strong>{path}</strong>
        </td>
      </tr>
      {list.map((t) => (
        <tr key={t.id} className="clickable" onClick={() => onOpen(t)}>
          <td>
            {t.name} {t.hold_point && <span className="badge badge-orange">hold point</span>}
            {t.needs_inspection && <span className="badge badge-muted">checklist</span>}
          </td>
          <td className="num">{t.weight_percent ? `${num(t.weight_percent, 1)}%` : "—"}</td>
          <td className={`nowrap ${t.late ? "text-danger" : ""}`}>
            {shortDate(t.planned_start)} – {shortDate(t.planned_end)}
          </td>
          <td className="nowrap muted">{t.actual_start ? `${shortDate(t.actual_start)} – ${t.actual_end ? shortDate(t.actual_end) : "…"}` : "—"}</td>
          <td>
            <span className={`badge ${STATUS[t.status][0]}`}>{STATUS[t.status][1]}</span>
          </td>
          <td>{t.assignee_name ?? "—"}</td>
        </tr>
      ))}
    </>
  );
}

function Gantt({ groups, onOpen }: { groups: [string, SiteTask[]][]; onOpen: (t: SiteTask) => void }) {
  const all = groups.flatMap(([, l]) => l);
  const dates = all.flatMap((t) => [t.planned_start, t.planned_end, t.actual_start, t.actual_end]).filter(Boolean) as string[];
  if (!dates.length) return <p className="muted">No dates to draw.</p>;
  const min = Math.min(...dates.map((d) => Date.parse(d)));
  const max = Math.max(...dates.map((d) => Date.parse(d)), Date.now());
  const span = Math.max(1, (max - min) / DAY + 1);
  const pos = (d: string) => ((Date.parse(d) - min) / DAY / span) * 100;
  const width = (a: string, b: string) => Math.max(0.6, (((Date.parse(b) - Date.parse(a)) / DAY + 1) / span) * 100);
  const today = ((Date.now() - min) / DAY / span) * 100;
  return (
    <div className="gantt">
      <div className="gantt-head muted small">
        <span>{new Date(min).toLocaleDateString("en-IN")}</span>
        <span>{new Date(max).toLocaleDateString("en-IN")}</span>
      </div>
      {groups.map(([path, list]) => (
        <div key={path}>
          <div className="gantt-group">{path}</div>
          {list.map((t) => (
            <div key={t.id} className="gantt-row clickable" onClick={() => onOpen(t)} title={`${t.name}: ${t.status}`}>
              <span className="gantt-label">{t.name}</span>
              <span className="gantt-track">
                {today >= 0 && today <= 100 && <span className="gantt-today" style={{ left: `${today}%` }} />}
                {t.planned_start && t.planned_end && (
                  <span className={`gantt-bar planned ${t.late ? "late" : ""}`} style={{ left: `${pos(t.planned_start)}%`, width: `${width(t.planned_start, t.planned_end)}%` }} />
                )}
                {t.actual_start && (
                  <span
                    className={`gantt-bar actual ${t.status}`}
                    style={{ left: `${pos(t.actual_start)}%`, width: `${width(t.actual_start, t.actual_end ?? new Date().toISOString().slice(0, 10))}%` }}
                  />
                )}
              </span>
            </div>
          ))}
        </div>
      ))}
      <p className="muted small">Grey: planned · coloured: actual · red line: today.</p>
    </div>
  );
}

export function TaskDialog({
  site,
  task,
  canUpdate,
  canEdit,
  onClose,
  onSaved,
}: {
  site: Site;
  task: SiteTask;
  canUpdate: boolean;
  canEdit: boolean;
  onClose: () => void;
  onSaved: (t: SiteTask) => void;
}) {
  const [status, setStatus] = useState<SiteTask["status"]>(task.status === "certified" ? "done" : task.status);
  const [progress, setProgress] = useState(task.progress_percent);
  const [remark, setRemark] = useState(task.remark ?? "");
  const [items, setItems] = useState(task.inspection ?? []);
  const [photos, setPhotos] = useState<Record<number, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  const base = `/api/sites/${site.id}/tasks/${task.id}`;
  const locked = task.status === "certified" && !canEdit;

  useEffect(() => {
    let alive = true;
    for (const p of task.photos) {
      void fetchObjectUrl(`${base}/photos/${p.id}`).then((url) => alive && setPhotos((m) => ({ ...m, [p.id]: url })));
    }
    return () => {
      alive = false;
    };
  }, [task.photos, base]);

  async function save() {
    setError(null);
    try {
      const body: Record<string, unknown> = { remark: remark || null, inspection: items, progress_percent: progress };
      if (status !== task.status && !(task.status === "certified" && status === "done")) body.status = status;
      onSaved(await api<SiteTask>(base, { method: "PATCH", json: body }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    try {
      onSaved(await api<SiteTask>(`${base}/photos`, { method: "POST", form }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function certify() {
    const r = prompt("Certification remark (optional)", "");
    if (r === null) return;
    try {
      onSaved(await api<SiteTask>(`${base}/certify`, { method: "POST", json: { remark: r || null } }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`${task.node_path ?? ""} · ${task.name}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="muted small">
        Planned {shortDate(task.planned_start)} – {shortDate(task.planned_end)} · weight {task.weight_percent ? `${num(task.weight_percent, 1)}%` : "—"}
        {task.hold_point && " · hold point: the office certifies it before the next step"}
        {task.certified_at && ` · certified ${new Date(task.certified_at).toLocaleString("en-IN")}`}
      </p>
      <div className="grid-2">
        <label className="field">
          <span>Status</span>
          <select value={status} disabled={!canUpdate || locked} onChange={(e) => setStatus(e.target.value as SiteTask["status"])}>
            <option value="not_started">Not started</option>
            <option value="in_progress">In progress</option>
            <option value="done">Done</option>
            <option value="blocked">Blocked</option>
          </select>
        </label>
        <label className="field">
          <span>% done</span>
          <input type="number" min={0} max={100} disabled={!canUpdate || locked} value={progress} onChange={(e) => setProgress(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Remark</span>
        <textarea rows={2} disabled={!canUpdate || locked} value={remark} onChange={(e) => setRemark(e.target.value)} />
      </label>
      {(task.needs_inspection || items.length > 0) && (
        <>
          <h3 className="section-title">Inspection checklist</h3>
          {items.map((it, i) => (
            <div key={i} className="inline-form">
              <input
                className="grow"
                value={it.item}
                disabled={!canUpdate || locked}
                onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, item: e.target.value } : x)))}
              />
              <select
                value={it.passed === null ? "" : it.passed ? "pass" : "fail"}
                disabled={!canUpdate || locked}
                onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, passed: e.target.value === "" ? null : e.target.value === "pass" } : x)))}
              >
                <option value="">—</option>
                <option value="pass">Pass</option>
                <option value="fail">Fail</option>
              </select>
              <button className="btn btn-small btn-ghost" disabled={!canUpdate || locked} onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
          {canUpdate && !locked && (
            <button className="btn btn-small" onClick={() => setItems((xs) => [...xs, { item: "", passed: null }])}>
              Add check
            </button>
          )}
        </>
      )}
      <h3 className="section-title top-gap">Photos {task.needs_photo && <span className="badge badge-info">required to finish</span>}</h3>
      <div className="photo-strip">
        {task.photos.map((p) => (
          <figure key={p.id} className="photo-share">
            {photos[p.id] ? <img src={photos[p.id]!} alt={p.filename} /> : <span className="muted small">{p.filename}</span>}
            {canUpdate && <ShareTick path={`/api/portal-admin/task-photos/${p.id}/share`} shared={!!p.share_with_client} />}
          </figure>
        ))}
        {task.photos.length === 0 && <span className="muted small">No photos yet.</span>}
      </div>
      {canUpdate && !locked && <input type="file" accept="image/*" capture="environment" onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />}
      <div className="form-actions">
        {canEdit && task.hold_point && task.status === "done" && (
          <button className="btn push-left" onClick={() => void certify()}>
            Certify hold point
          </button>
        )}
        <button className="btn" onClick={onClose}>
          Close
        </button>
        {canUpdate && !locked && (
          <button className="btn btn-primary" onClick={() => void save()}>
            Save
          </button>
        )}
      </div>
    </Modal>
  );
}

/** "Share with client" tick for a photo or drawing (shown in the client portal when ticked). */
export function ShareTick({ path, shared }: { path: string; shared: boolean }) {
  const [on, setOn] = useState(shared);
  const [busy, setBusy] = useState(false);
  async function toggle(next: boolean) {
    setBusy(true);
    try {
      const r = await api<{ share_with_client: boolean }>(path, { method: "PUT", json: { share: next } });
      setOn(r.share_with_client);
    } catch (err) {
      alert(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <label className="check small" title="Show in the client portal">
      <input type="checkbox" checked={on} disabled={busy} onChange={(e) => void toggle(e.target.checked)} /> Share with client
    </label>
  );
}
