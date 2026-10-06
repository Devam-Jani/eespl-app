import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { Clause, Page, Template, TemplateSummary } from "../types";

function move<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export default function TcLibrary() {
  const [tab, setTab] = useState<"clauses" | "templates">("clauses");
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadClauses = useCallback(async () => {
    try {
      setClauses((await api<Page<Clause>>("/api/tc/clauses?limit=500")).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    void loadClauses();
  }, [loadClauses]);

  return (
    <>
      <div className="page-header">
        <h1>T&amp;C library</h1>
        <div className="tabs">
          <button className={`tab ${tab === "clauses" ? "active" : ""}`} onClick={() => setTab("clauses")}>
            Clauses
          </button>
          <button className={`tab ${tab === "templates" ? "active" : ""}`} onClick={() => setTab("templates")}>
            Templates
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "clauses" ? (
        <Clauses clauses={clauses} reload={loadClauses} onError={setError} />
      ) : (
        <Templates clauses={clauses} onError={setError} />
      )}
    </>
  );
}

function Clauses({
  clauses,
  reload,
  onError,
}: {
  clauses: Clause[];
  reload: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const { can } = useAuth();
  const canEdit = can("library.edit");
  const [editing, setEditing] = useState<Clause | "new" | null>(null);
  const [filter, setFilter] = useState("");

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const map = new Map<string, Clause[]>();
    for (const c of clauses) {
      if (q && !c.text.toLowerCase().includes(q)) continue;
      map.set(c.category, [...(map.get(c.category) ?? []), c]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [clauses, filter]);

  async function reorder(list: Clause[], index: number, delta: number) {
    const next = move(list, index, delta);
    if (next === list) return;
    try {
      await api("/api/tc/clauses/order", { method: "PUT", json: { ids: next.map((c) => c.id) } });
      await reload();
    } catch (err) {
      onError(errorText(err));
    }
  }

  return (
    <>
      <div className="toolbar">
        <input className="search" placeholder="Filter clauses" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {canEdit && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            Add clause
          </button>
        )}
      </div>
      {groups.map(([category, list]) => (
        <div key={category} className="card clause-group">
          <h2 className="section-title capitalize">
            {category.replace(/_/g, " ")} <span className="muted small">({list.length})</span>
          </h2>
          <ol className="clause-list">
            {list.map((c, i) => (
              <li key={c.id} className={c.is_active ? "" : "row-muted"}>
                <div className="clause-text">
                  {c.text}
                  <div className="muted small">
                    used in {c.usage_count} BOQ{c.usage_count === 1 ? "" : "s"}
                    {c.default_include && <span className="badge badge-ok">default</span>}
                    {!c.is_active && <span className="badge badge-muted">inactive</span>}
                  </div>
                </div>
                {canEdit && (
                  <div className="clause-actions">
                    <button className="btn btn-small" disabled={i === 0} onClick={() => void reorder(list, i, -1)} aria-label="Move up">
                      ↑
                    </button>
                    <button
                      className="btn btn-small"
                      disabled={i === list.length - 1}
                      onClick={() => void reorder(list, i, 1)}
                      aria-label="Move down"
                    >
                      ↓
                    </button>
                    <button className="btn btn-small" onClick={() => setEditing(c)}>
                      Edit
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
      {groups.length === 0 && <div className="card empty">No clauses.</div>}
      {editing && (
        <ClauseForm
          clause={editing === "new" ? null : editing}
          categories={[...new Set(clauses.map((c) => c.category))].sort()}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await reload();
          }}
        />
      )}
    </>
  );
}

function ClauseForm({
  clause,
  categories,
  onClose,
  onSaved,
}: {
  clause: Clause | null;
  categories: string[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [text, setText] = useState(clause?.text ?? "");
  const [category, setCategory] = useState(clause?.category ?? categories[0] ?? "general");
  const [defaultInclude, setDefaultInclude] = useState(clause?.default_include ?? false);
  const [active, setActive] = useState(clause?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = { text, category, default_include: defaultInclude, is_active: active };
    try {
      if (clause) await api(`/api/tc/clauses/${clause.id}`, { method: "PATCH", json: body });
      else await api("/api/tc/clauses", { method: "POST", json: body });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!clause || !confirm("Delete this clause? It is also removed from every template.")) return;
    try {
      await api(`/api/tc/clauses/${clause.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={clause ? "Edit clause" : "Add clause"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Text</span>
          <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} required autoFocus />
        </label>
        <label className="field">
          <span>Category</span>
          <input list="tc-categories" value={category} onChange={(e) => setCategory(e.target.value)} required />
          <datalist id="tc-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
        <label className="check">
          <input type="checkbox" checked={defaultInclude} onChange={(e) => setDefaultInclude(e.target.checked)} />
          Include by default
        </label>
        <label className="check">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active
        </label>
        <div className="form-actions">
          {clause && (
            <button type="button" className="btn btn-danger push-left" onClick={() => void remove()}>
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}

function Templates({ clauses, onError }: { clauses: Clause[]; onError: (e: string | null) => void }) {
  const { can } = useAuth();
  const canEdit = can("library.edit");
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selected, setSelected] = useState<Template | null>(null);
  const [adding, setAdding] = useState("");

  const loadList = useCallback(async () => {
    const list = await api<TemplateSummary[]>("/api/tc/templates");
    setTemplates(list);
    return list;
  }, []);

  const open = useCallback(
    async (id: number) => {
      try {
        setSelected(await api<Template>(`/api/tc/templates/${id}`));
      } catch (err) {
        onError(errorText(err));
      }
    },
    [onError],
  );

  useEffect(() => {
    loadList().then(
      (list) => {
        if (list.length) void open(list[0].id);
      },
      (err) => onError(errorText(err)),
    );
  }, [loadList, open, onError]);

  async function patch(body: object) {
    if (!selected) return;
    try {
      setSelected(await api<Template>(`/api/tc/templates/${selected.id}`, { method: "PATCH", json: body }));
      await loadList();
    } catch (err) {
      onError(errorText(err));
    }
  }

  async function create() {
    const name = prompt("Name of the new template");
    if (!name) return;
    try {
      const t = await api<Template>("/api/tc/templates", { method: "POST", json: { name } });
      await loadList();
      setSelected(t);
    } catch (err) {
      onError(errorText(err));
    }
  }

  async function remove() {
    if (!selected || !confirm(`Delete the template "${selected.name}"? The clauses themselves are kept.`)) return;
    try {
      await api(`/api/tc/templates/${selected.id}`, { method: "DELETE" });
      const list = await loadList();
      setSelected(null);
      if (list.length) void open(list[0].id);
    } catch (err) {
      onError(errorText(err));
    }
  }

  const ids = selected?.clauses.map((c) => c.id) ?? [];
  const available = clauses.filter((c) => c.is_active && !ids.includes(c.id));

  return (
    <div className="split split-narrow">
      <div className="card">
        <div className="toolbar">
          <h2 className="section-title">Templates</h2>
          {canEdit && (
            <button className="btn btn-small btn-primary" onClick={() => void create()}>
              New
            </button>
          )}
        </div>
        <ul className="pick-list">
          {templates.map((t) => (
            <li key={t.id}>
              <button className={`pick ${selected?.id === t.id ? "active" : ""}`} onClick={() => void open(t.id)}>
                <span>{t.name}</span>
                <span className="muted small">
                  {t.clause_count} clauses {t.is_default && <span className="badge badge-ok">default</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="card">
        {!selected ? (
          <p className="muted">Choose a template.</p>
        ) : (
          <>
            <div className="toolbar">
              <h2 className="section-title">
                {selected.name} {selected.is_default && <span className="badge badge-ok">default</span>}
              </h2>
              {canEdit && (
                <div className="page-actions">
                  <button
                    className="btn btn-small"
                    onClick={() => {
                      const name = prompt("Rename template", selected.name);
                      if (name && name !== selected.name) void patch({ name });
                    }}
                  >
                    Rename
                  </button>
                  {!selected.is_default && (
                    <button className="btn btn-small" onClick={() => void patch({ is_default: true })}>
                      Make default
                    </button>
                  )}
                  <button className="btn btn-small btn-danger" onClick={() => void remove()}>
                    Delete
                  </button>
                </div>
              )}
            </div>
            <ol className="clause-list numbered">
              {selected.clauses.map((c, i) => (
                <li key={c.id}>
                  <div className="clause-text">
                    {c.text}
                    <div className="muted small capitalize">{c.category.replace(/_/g, " ")}</div>
                  </div>
                  {canEdit && (
                    <div className="clause-actions">
                      <button
                        className="btn btn-small"
                        disabled={i === 0}
                        onClick={() => void patch({ clause_ids: move(ids, i, -1) })}
                        aria-label="Move up"
                      >
                        ↑
                      </button>
                      <button
                        className="btn btn-small"
                        disabled={i === ids.length - 1}
                        onClick={() => void patch({ clause_ids: move(ids, i, 1) })}
                        aria-label="Move down"
                      >
                        ↓
                      </button>
                      <button
                        className="btn btn-small"
                        onClick={() => void patch({ clause_ids: ids.filter((x) => x !== c.id) })}
                        aria-label="Remove from template"
                      >
                        ×
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            {selected.clauses.length === 0 && <p className="muted">No clauses in this template yet.</p>}
            {canEdit && (
              <div className="toolbar top-gap">
                <select value={adding} onChange={(e) => setAdding(e.target.value)} className="grow">
                  <option value="">Add a clause…</option>
                  {available.map((c) => (
                    <option key={c.id} value={c.id}>
                      [{c.category}] {c.text.length > 110 ? `${c.text.slice(0, 110)}…` : c.text}
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn-small btn-primary"
                  disabled={!adding}
                  onClick={() => {
                    void patch({ clause_ids: [...ids, Number(adding)] });
                    setAdding("");
                  }}
                >
                  Add
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
