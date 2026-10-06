import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import type { Clause, HiddenReason, Page, Template, TemplateSummary } from "../types";

function move<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

const HIDDEN_LABELS: Record<HiddenReason, string> = {
  not_a_clause: "Not a clause",
  client_checklist: "Client checklist answer",
  project_specific: "Project-specific",
  manual: "Hidden by hand",
};

export default function TcLibrary() {
  const [tab, setTab] = useState<"clauses" | "templates">("clauses");
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Hidden clauses come too, so the page can count and toggle them without another request.
  const loadClauses = useCallback(async () => {
    try {
      setClauses((await api<Page<Clause>>("/api/tc/clauses?limit=500&include_hidden=true")).items);
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
        <Templates clauses={clauses.filter((c) => c.status === "active")} onError={setError} />
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
  const [merging, setMerging] = useState<Clause | null>(null);
  const [hiding, setHiding] = useState<Clause | null>(null);
  const [filter, setFilter] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [openVariants, setOpenVariants] = useState<number | null>(null);

  const hiddenCount = clauses.filter((c) => c.status === "hidden").length;
  const reviewCount = clauses.filter((c) => c.needs_review && (showHidden || c.status === "active")).length;

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const map = new Map<string, Clause[]>();
    for (const c of clauses) {
      if (c.status === "hidden" && !showHidden) continue;
      if (reviewOnly && !c.needs_review) continue;
      if (q && !c.text.toLowerCase().includes(q) && !c.variants.some((v) => v.text.toLowerCase().includes(q))) continue;
      map.set(c.category, [...(map.get(c.category) ?? []), c]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [clauses, filter, showHidden, reviewOnly]);

  async function act(path: string, json?: object) {
    onError(null);
    try {
      await api(`/api/tc/clauses/${path}`, { method: "POST", json });
      await reload();
    } catch (err) {
      onError(errorText(err));
    }
  }

  async function reorder(list: Clause[], index: number, delta: number) {
    const active = list.filter((c) => c.status === "active");
    const from = active.indexOf(list[index]);
    const next = move(active, from, delta);
    if (from < 0 || next === active) return;
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
        <div className="page-actions">
          <input className="search" placeholder="Filter clauses" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button className={`chip-toggle ${reviewOnly ? "on" : ""}`} onClick={() => setReviewOnly((v) => !v)}>
            Needs review ({reviewCount})
          </button>
          <label className="check">
            <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} />
            Show hidden ({hiddenCount})
          </label>
        </div>
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
            {list.map((c, i) => {
              const hidden = c.status === "hidden";
              return (
                <li key={c.id} className={hidden ? "row-muted" : ""}>
                  <div className="clause-text">
                    {c.text}
                    <div className="muted small clause-meta">
                      used in {c.usage_count} BOQ{c.usage_count === 1 ? "" : "s"}
                      {c.default_include && <span className="badge badge-ok">default</span>}
                      {c.variant_count > 0 && (
                        <button
                          className="badge badge-info as-button"
                          onClick={() => setOpenVariants(openVariants === c.id ? null : c.id)}
                          title="Other wordings of this clause, kept to match client BOQs"
                        >
                          {c.variant_count} variant{c.variant_count === 1 ? "" : "s"}
                        </button>
                      )}
                      {hidden && c.hidden_reason && (
                        <span className="badge badge-muted">{HIDDEN_LABELS[c.hidden_reason]}</span>
                      )}
                      {c.needs_review && (
                        <span className="badge badge-orange" title={c.review_note ?? ""}>
                          Needs review{c.review_note ? `: ${c.review_note}` : ""}
                        </span>
                      )}
                    </div>
                    {openVariants === c.id && (
                      <ul className="variant-list">
                        {c.variants.map((v) => (
                          <li key={v.id}>
                            <span>
                              {v.text} <span className="muted small">({v.own_usage_count})</span>
                            </span>
                            {canEdit && (
                              <button className="btn btn-small" onClick={() => void act(`${v.id}/unmerge`)}>
                                Unmerge
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  {canEdit && (
                    <div className="clause-actions">
                      {!hidden && (
                        <>
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
                        </>
                      )}
                      <button className="btn btn-small" onClick={() => setEditing(c)}>
                        Edit
                      </button>
                      <RowMenu
                        items={[
                          hidden
                            ? { label: "Unhide", run: () => void act(`${c.id}/unhide`) }
                            : { label: "Hide…", run: () => setHiding(c) },
                          { label: "Merge into…", run: () => setMerging(c) },
                          ...(c.needs_review ? [{ label: "Mark reviewed", run: () => void act(`${c.id}/reviewed`) }] : []),
                        ]}
                      />
                    </div>
                  )}
                </li>
              );
            })}
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
      {hiding && (
        <HideDialog
          clause={hiding}
          onClose={() => setHiding(null)}
          onHide={async (reason) => {
            setHiding(null);
            await act(`${hiding.id}/hide`, { reason });
          }}
        />
      )}
      {merging && (
        <MergeDialog
          clause={merging}
          candidates={clauses.filter((c) => c.id !== merging.id && c.status === "active")}
          onClose={() => setMerging(null)}
          onMerge={async (target) => {
            setMerging(null);
            await act(`${merging.id}/merge`, { into_id: target.id });
          }}
        />
      )}
    </>
  );
}

function RowMenu({ items }: { items: { label: string; run: () => void }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="row-menu" onMouseLeave={() => setOpen(false)}>
      <button className="btn btn-small" onClick={() => setOpen((o) => !o)} aria-label="More actions">
        ⋯
      </button>
      {open && (
        <div className="row-menu-items">
          {items.map((item) => (
            <button
              key={item.label}
              onClick={() => {
                setOpen(false);
                item.run();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function HideDialog({
  clause,
  onClose,
  onHide,
}: {
  clause: Clause;
  onClose: () => void;
  onHide: (reason: HiddenReason) => Promise<void>;
}) {
  const [reason, setReason] = useState<HiddenReason>("manual");
  return (
    <Modal title="Hide clause" onClose={onClose}>
      <p className="item-desc">{clause.text}</p>
      <label className="field">
        <span>Reason</span>
        <select value={reason} onChange={(e) => setReason(e.target.value as HiddenReason)}>
          {(Object.keys(HIDDEN_LABELS) as HiddenReason[]).map((r) => (
            <option key={r} value={r}>
              {HIDDEN_LABELS[r]}
            </option>
          ))}
        </select>
      </label>
      <p className="muted small">Hidden clauses are also taken out of every template. You can unhide later.</p>
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={() => void onHide(reason)}>
          Hide
        </button>
      </div>
    </Modal>
  );
}

function MergeDialog({
  clause,
  candidates,
  onClose,
  onMerge,
}: {
  clause: Clause;
  candidates: Clause[];
  onClose: () => void;
  onMerge: (target: Clause) => Promise<void>;
}) {
  const [q, setQ] = useState(clause.text.split(/\s+/).slice(0, 4).join(" "));
  const shown = candidates.filter((c) => c.text.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 30);
  return (
    <Modal title="Merge into…" onClose={onClose} wide>
      <p className="item-desc">{clause.text}</p>
      <p className="muted small">
        Choose the clause to keep (the master). This wording is kept as a variant, its usage count is added to the master, and
        templates that hold it get the master instead. You can unmerge later.
      </p>
      <input className="full" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <ul className="pick-list top-gap">
        {shown.map((c) => (
          <li key={c.id}>
            <button
              className="pick"
              onClick={() => {
                if (confirm("Merge into this clause?")) void onMerge(c);
              }}
            >
              <span>{c.text}</span>
              <span className="muted small capitalize">
                {c.category.replace(/_/g, " ")} · used in {c.usage_count}
              </span>
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="muted">No matching clauses.</li>}
      </ul>
    </Modal>
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
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = { text, category, default_include: defaultInclude };
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
        {clause?.needs_review && (
          <div className="alert alert-warn">
            {clause.review_note ?? "Needs review"}. Correct the text and save to clear this.
          </div>
        )}
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
  const available = clauses.filter((c) => !ids.includes(c.id));

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
