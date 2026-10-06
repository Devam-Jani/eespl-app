import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, queryString } from "../../api";
import ExportButton from "../../components/ExportButton";
import { errorText } from "../../format";
import type { Page, Tag, TagModule } from "../../types";

const MODULES: Record<TagModule, string> = {
  material: "Material",
  petty_spend: "Petty spend",
  work_order: "Work order",
  issue: "Issue",
};

export default function Tags() {
  const [module, setModule] = useState<TagModule>("material");
  const [showArchived, setShowArchived] = useState(false);
  const [rows, setRows] = useState<Tag[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const params = { module, archived: showArchived ? undefined : "false", limit: 500 };
      setRows((await api<Page<Tag>>(`/api/tags${queryString(params)}`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [module, showArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/tags", { method: "POST", json: { module, name } });
      setName("");
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function act(tag: Tag, method: "PATCH" | "DELETE", json?: object) {
    setError(null);
    if (method === "DELETE" && !confirm(`Delete the tag "${tag.name}"?`)) return;
    try {
      await api(`/api/tags/${tag.id}`, { method, json });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function rename(tag: Tag) {
    const next = prompt("Rename tag", tag.name);
    if (next && next.trim() !== tag.name) await act(tag, "PATCH", { name: next.trim() });
  }

  return (
    <>
      <div className="page-header">
        <h1>Tags</h1>
        <div className="page-actions">
          <div className="tabs">
            {(Object.keys(MODULES) as TagModule[]).map((m) => (
              <button key={m} className={`tab ${module === m ? "active" : ""}`} onClick={() => setModule(m)}>
                {MODULES[m]}
              </button>
            ))}
          </div>
          <ExportButton path={`/api/tags/export?module=${module}`} />
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <form className="card toolbar" onSubmit={add}>
        <input className="grow" placeholder={`New ${MODULES[module].toLowerCase()} tag`} value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="btn btn-primary">Add tag</button>
        <label className="check">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      </form>
      <div className="card">
        <div className="tag-cloud">
          {rows.map((t) => (
            <span key={t.id} className={`tag-pill ${t.is_archived ? "archived" : ""}`}>
              <button className="link" onClick={() => void rename(t)} title="Rename">
                {t.name}
              </button>
              <button
                className="tag-action"
                title={t.is_archived ? "Restore" : "Archive"}
                onClick={() => void act(t, "PATCH", { is_archived: !t.is_archived })}
              >
                {t.is_archived ? "↺" : "⌫"}
              </button>
              <button className="tag-action" title="Delete" onClick={() => void act(t, "DELETE")}>
                ×
              </button>
            </span>
          ))}
          {rows.length === 0 && <p className="muted">No tags yet.</p>}
        </div>
      </div>
    </>
  );
}
