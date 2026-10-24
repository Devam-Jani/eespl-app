import { useCallback, useEffect, useState } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText } from "../../format";
import type { Checklist, InspectionOut } from "../../execution/types";
import type { Site, SiteTask } from "../../types";
import { shortDate } from "../Tenders";
import { localToday } from "./DprTab";
import SignaturePad from "./SignaturePad";
import { Button, buttonClass, Card, Field } from "../../ui/components";

const RESULT: Record<string, [string, string]> = {
  pass: ["badge-ok", "Pass"],
  fail: ["badge-danger", "Fail"],
  pass_with_remarks: ["badge-warn", "Pass with remarks"],
};

export default function InspectionsTab({ site, onChange }: { site: Site; onChange?: () => void }) {
  const { can } = useAuth();
  const [list, setList] = useState<InspectionOut[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => api<InspectionOut[]>(`/api/execution/inspections?site_id=${site.id}`).then(setList, (err) => setError(errorText(err))), [site.id]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {can("inspection.edit") && (
        <Button variant="primary" className="tap-wide-sm" onClick={() => setCreating(true)}>
          New inspection
        </Button>
      )}
      <Card as="div" className="table-wrap top-gap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Date</th>
              <th>Checklist</th>
              <th>Step / place</th>
              <th>Result</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((i) => (
              <tr key={i.id}>
                <td>
                  <code>{i.code}</code>
                </td>
                <td className="nowrap">{shortDate(i.on_date)}</td>
                <td>{i.template_name}</td>
                <td>
                  {i.task_name ?? i.node_name ?? "—"} {i.task_status === "certified" && <span className="badge badge-ok">certified</span>}
                </td>
                <td>
                  <span className={`badge ${RESULT[i.result][0]}`}>{RESULT[i.result][1]}</span>
                </td>
                <td>
                  <Button size="small" onClick={() => void downloadFile(`/api/execution/inspections/${i.id}/pdf`).catch((err) => setError(errorText(err)))}>
                    PDF
                  </Button>
                  {i.client_signoff === "waiting" && <span className="badge badge-warn">waiting for client</span>}
                  {i.client_signoff === "signed" && <span className="badge badge-ok">client signed: {i.client_signed_name}</span>}
                  {i.client_signoff === "none" && can("inspection.edit") && (
                    <Button
                      variant="ghost" size="small"
                      onClick={() =>
                        void api(`/api/portal-admin/inspections/${i.id}/request-signoff`, { method: "POST" }).then(
                          () => void load(),
                          (err) => setError(errorText(err)),
                        )
                      }
                    >
                      Ask client to sign
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {list.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No inspections yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
      {creating && (
        <InspectionForm
          site={site}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            void load();
            onChange?.();
          }}
        />
      )}
    </>
  );
}

/** Mobile-friendly checklist: big Pass / Fail / n/a buttons, camera for photo items, signature. */
export function InspectionForm({ site, onClose, onSaved }: { site: Site; onClose: () => void; onSaved: () => void }) {
  const { can } = useAuth();
  const [checklists, setChecklists] = useState<Checklist[]>([]);
  const [tasks, setTasks] = useState<SiteTask[]>([]);
  const [templateId, setTemplateId] = useState<number | "">("");
  const [taskId, setTaskId] = useState<number | "">("");
  const [values, setValues] = useState<Record<number, string>>({});
  const [files, setFiles] = useState<Record<number, File>>({});
  const [extra, setExtra] = useState<File[]>([]);
  const [form, setForm] = useState({ on_date: localToday(), remark: "", client_rep: "", result: "" });
  const [signature, setSignature] = useState<string | null>(null);
  const [certify, setCertify] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Checklist[]>("/api/execution/checklists").then(
      (l) => setChecklists(l.filter((c) => c.is_active)),
      () => setChecklists([]),
    );
    api<SiteTask[]>(`/api/sites/${site.id}/tasks`).then(setTasks, () => setTasks([]));
  }, [site.id]);

  const holdTasks = tasks.filter((t) => t.hold_point);
  const task = tasks.find((t) => t.id === taskId);
  const template = checklists.find((c) => c.id === templateId);
  const failed = template?.items.some((i) => i.type === "pass_fail" && values[i.id] === "fail");

  function pickTask(id: number | "") {
    setTaskId(id);
    const t = tasks.find((x) => x.id === id);
    if (t?.checklist_template_id) setTemplateId(t.checklist_template_id);
  }

  async function submit() {
    if (!template) return;
    setBusy(true);
    setError(null);
    const data = {
      site_id: site.id,
      template_id: template.id,
      task_id: taskId || null,
      on_date: form.on_date,
      answers: template.items.filter((i) => i.type !== "photo").map((i) => ({ item_id: i.id, value: values[i.id] ?? null })),
      result: form.result || null,
      remark: form.remark || null,
      client_rep: form.client_rep || null,
      signature,
      certify: !!task && task.hold_point && certify,
    };
    const body = new FormData();
    body.append("data", JSON.stringify(data));
    for (const [id, f] of Object.entries(files)) body.append(`item_${id}`, f);
    for (const f of extra) body.append("photo", f);
    try {
      await api<InspectionOut>("/api/execution/inspections", { method: "POST", form: body });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Inspection" onClose={onClose} wide>
      <div className="daily">
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Step (hold point)">
          <select className="tap-input" value={taskId} onChange={(e) => pickTask(Number(e.target.value) || "")}>
            <option value="">— none: a general inspection —</option>
            {holdTasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.node_path ? `${t.node_path} · ` : ""}
                {t.name} ({t.status.replace("_", " ")})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Checklist *">
          <select className="tap-input" value={templateId} onChange={(e) => setTemplateId(Number(e.target.value) || "")}>
            <option value="">—</option>
            {checklists.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        {template?.items.map((item) => (
          <div key={item.id} className="check-item">
            <div>
              {item.text}
              {item.required && <span className="text-danger"> *</span>}
            </div>
            {item.type === "pass_fail" && (
              <div className="tap-group">
                {(["pass", "fail", "na"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    className={`tap mark-${v === "pass" ? "present" : v === "fail" ? "absent" : "half_day"} ${values[item.id] === v ? "on" : ""}`}
                    onClick={() => setValues({ ...values, [item.id]: v })}
                  >
                    {v === "na" ? "n/a" : v === "pass" ? "Pass" : "Fail"}
                  </button>
                ))}
              </div>
            )}
            {item.type === "number" && (
              <Field label={item.text} bare>
                <input className="tap-input" inputMode="decimal" value={values[item.id] ?? ""} onChange={(e) => setValues({ ...values, [item.id]: e.target.value })} />
              </Field>
            )}
            {item.type === "text" && (
              <Field label={item.text} bare>
                <input className="tap-input" value={values[item.id] ?? ""} onChange={(e) => setValues({ ...values, [item.id]: e.target.value })} />
              </Field>
            )}
            {item.type === "photo" && (
              <label className={buttonClass({ variant: files[item.id] ? "primary" : "secondary", className: "tap-wide" })}>
                📷 {files[item.id] ? files[item.id].name : "Take photo"}
                <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => e.target.files?.[0] && setFiles({ ...files, [item.id]: e.target.files[0] })} />
              </label>
            )}
          </div>
        ))}
        {template && (
          <>
            <label className={buttonClass({ className: "tap-wide top-gap" })}>
              📷 More photos {extra.length ? `(${extra.length})` : ""}
              <input type="file" accept="image/*" capture="environment" multiple hidden onChange={(e) => setExtra(Array.from(e.target.files ?? []))} />
            </label>
            <div className="grid-2 top-gap">
              <Field label="Result">
                <select className="tap-input" value={failed ? "fail" : form.result} disabled={failed} onChange={(e) => setForm({ ...form, result: e.target.value })}>
                  <option value="">{failed ? "Fail" : "Pass (from the answers)"}</option>
                  <option value="pass_with_remarks">Pass with remarks</option>
                  <option value="fail">Fail</option>
                </select>
              </Field>
              <Field label="Date">
                <input type="date" className="tap-input" value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} />
              </Field>
            </div>
            <Field label="Remarks">
              <textarea rows={2} value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
            </Field>
            <Field label="Client representative">
              <input className="tap-input" value={form.client_rep} onChange={(e) => setForm({ ...form, client_rep: e.target.value })} placeholder="Name" />
            </Field>
            <Field as="div" label="Signature (client representative)">
              <SignaturePad onChange={setSignature} />
            </Field>
            {task?.hold_point && can("site.edit") && (
              <label className="check">
                <input type="checkbox" checked={certify} onChange={(e) => setCertify(e.target.checked)} /> Certify the hold point "{task.name}" if it passes
              </label>
            )}
          </>
        )}
        <div className="daily-actions">
          <Button className="tap-wide" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" className="tap-wide" disabled={busy || !template} onClick={() => void submit()}>
            Save inspection
          </Button>
        </div>
      </div>
    </Modal>
  );
}
