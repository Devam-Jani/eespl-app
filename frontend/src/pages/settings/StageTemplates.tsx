import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText } from "../../format";
import type { StageTemplate, TemplateStep } from "../../types";

const EMPTY_STEP: TemplateStep = { name: "", weight_percent: "0", needs_photo: true, needs_inspection: false, hold_point: false, typical_days: 1 };

/** The steps of each kind of work, their weights (must add up to 100), flags and typical days. */
export default function StageTemplates() {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const [templates, setTemplates] = useState<StageTemplate[]>([]);
  const [selected, setSelected] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<StageTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    try {
      setTemplates(await api<StageTemplate[]>("/api/stage-templates"));
    } catch (err) {
      setError(errorText(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (selected === "new")
      setDraft({ id: 0, name: "", system_id: null, system_name: null, work_category_id: null, work_category_name: null, keywords: "", is_active: true, steps: [{ ...EMPTY_STEP, weight_percent: "100" }], total_days: 1 });
    else setDraft(templates.find((t) => t.id === selected) ?? null);
  }, [selected, templates]);

  const total = draft?.steps.reduce((s, x) => s + Number(x.weight_percent || 0), 0) ?? 0;

  function setStep(i: number, patch: Partial<TemplateStep>) {
    setDraft((d) => (d ? { ...d, steps: d.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : d));
  }

  function move(i: number, to: number) {
    setDraft((d) => {
      if (!d || to < 0 || to >= d.steps.length) return d;
      const steps = [...d.steps];
      const [x] = steps.splice(i, 1);
      steps.splice(to, 0, x);
      return { ...d, steps };
    });
  }

  async function save() {
    if (!draft) return;
    setError(null);
    setNotice(null);
    const body = {
      name: draft.name,
      system_id: draft.system_id,
      work_category_id: draft.work_category_id,
      keywords: draft.keywords,
      is_active: draft.is_active,
      steps: draft.steps.map((s) => ({ ...s, typical_days: Number(s.typical_days) })),
    };
    try {
      const saved =
        selected === "new"
          ? await api<StageTemplate>("/api/stage-templates", { method: "POST", json: body })
          : await api<StageTemplate>(`/api/stage-templates/${draft.id}`, { method: "PUT", json: body });
      await load();
      setSelected(saved.id);
      setNotice("Template saved.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Stage templates</h1>
        {canEdit && (
          <button className="btn btn-primary" onClick={() => setSelected("new")}>
            New template
          </button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      <div className="split split-narrow">
        <div className="card">
          <ul className="plain-list">
            {templates.map((t) => (
              <li key={t.id} className={`pick ${selected === t.id ? "active" : ""}`} onClick={() => setSelected(t.id)}>
                <strong>{t.name}</strong>
                <div className="muted small">
                  {t.steps.length} steps · {t.total_days} days{t.work_category_name ? ` · ${t.work_category_name}` : ""}
                  {!t.is_active && " · inactive"}
                </div>
              </li>
            ))}
          </ul>
        </div>
        {draft && (
          <div className="card">
            <div className="grid-2">
              <label className="field">
                <span>Name</span>
                <input disabled={!canEdit} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </label>
              <label className="field">
                <span>Keywords (suggest this template for BOQ lines with these words)</span>
                <input disabled={!canEdit} value={draft.keywords ?? ""} onChange={(e) => setDraft({ ...draft, keywords: e.target.value })} />
              </label>
            </div>
            <p className="muted small">
              Work category: {draft.work_category_name ?? "—"} · system: {draft.system_name ?? "—"}
            </p>
            <table className="table compact">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Step</th>
                  <th className="num">Weight %</th>
                  <th>Photo</th>
                  <th>Checklist</th>
                  <th>Hold point</th>
                  <th className="num">Days</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {draft.steps.map((s, i) => (
                  <tr key={s.id ?? `n${i}`}>
                    <td>{i + 1}</td>
                    <td>
                      <input disabled={!canEdit} value={s.name} onChange={(e) => setStep(i, { name: e.target.value })} />
                    </td>
                    <td className="num">
                      <input className="input-num" disabled={!canEdit} value={s.weight_percent} onChange={(e) => setStep(i, { weight_percent: e.target.value })} />
                    </td>
                    <td className="center">
                      <input type="checkbox" disabled={!canEdit} checked={s.needs_photo} onChange={(e) => setStep(i, { needs_photo: e.target.checked })} />
                    </td>
                    <td className="center">
                      <input type="checkbox" disabled={!canEdit} checked={s.needs_inspection} onChange={(e) => setStep(i, { needs_inspection: e.target.checked })} />
                    </td>
                    <td className="center">
                      <input type="checkbox" disabled={!canEdit} checked={s.hold_point} onChange={(e) => setStep(i, { hold_point: e.target.checked })} />
                    </td>
                    <td className="num">
                      <input className="input-num" type="number" min={1} disabled={!canEdit} value={s.typical_days} onChange={(e) => setStep(i, { typical_days: Number(e.target.value) || 1 })} />
                    </td>
                    {canEdit && (
                      <td className="row-actions nowrap">
                        <button className="btn btn-small btn-ghost" onClick={() => move(i, i - 1)}>
                          ↑
                        </button>
                        <button className="btn btn-small btn-ghost" onClick={() => move(i, i + 1)}>
                          ↓
                        </button>
                        <button className="btn btn-small btn-ghost" onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, j) => j !== i) })}>
                          ×
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className={total === 100 ? "muted small" : "text-danger small"}>Weights add up to {total}% {total === 100 ? "✓" : "(must be 100)"}</p>
            {canEdit && (
              <div className="form-actions">
                <button className="btn" onClick={() => setDraft({ ...draft, steps: [...draft.steps, { ...EMPTY_STEP }] })}>
                  Add step
                </button>
                <label className="check">
                  <input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })} /> Active
                </label>
                <button className="btn btn-primary" disabled={total !== 100 || !draft.name} onClick={() => void save()}>
                  Save template
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
