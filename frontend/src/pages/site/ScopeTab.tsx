import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, num } from "../../format";
import type { AreaScope, ScopeLine, ScopeOverview, Site, SiteLookups, SiteNode } from "../../types";
import { ProgressBar } from "../Sites";
import { NODE_KINDS, depthOf, useNodes } from "./StructureTab";

const STATE: Record<string, [string, string]> = {
  ok: ["badge-ok", "Fully assigned"],
  under: ["badge-warn", "Under-assigned"],
  over: ["badge-danger", "Over-assigned"],
  no_qty: ["badge-muted", "No BOQ qty (QRO)"],
};

export default function ScopeTab({ site, onChange }: { site: Site; onChange: () => void }) {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const [data, setData] = useState<ScopeOverview | null>(null);
  const [lookups, setLookups] = useState<SiteLookups | null>(null);
  const [assigning, setAssigning] = useState<ScopeLine | null>(null);
  const { nodes } = useNodes(site.id);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<ScopeOverview>(`/api/sites/${site.id}/scope`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id]);

  useEffect(() => {
    void load();
    api<SiteLookups>("/api/sites/lookups").then(setLookups, () => setLookups(null));
  }, [load]);

  async function run(p: Promise<ScopeOverview>) {
    setError(null);
    try {
      setData(await p);
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function generate() {
    setError(null);
    try {
      const r = await api<{ added: number; kept: number; tasks: number; planned_end: string | null }>(`/api/sites/${site.id}/tasks/generate`, { method: "POST" });
      setNotice(`${r.added} tasks added, ${r.kept} kept; ${r.tasks} tasks in all, planned to finish ${r.planned_end ?? "—"}.`);
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  return (
    <div className="card">
      <div className="toolbar">
        <div>
          <h2 className="section-title">What we do where</h2>
          <span className="muted small">
            {site.tender_code ? `The priced lines of ${site.tender_code}` : "This site has no tender: add scopes per place."} · {nodes.length} places
          </span>
        </div>
        {canEdit && (
          <button className="btn btn-primary" onClick={() => void generate()}>
            Generate tasks
          </button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      {data.lines.length === 0 && <p className="empty">No priced BOQ lines.</p>}
      {data.lines.map((ln) => (
        <div key={ln.boq_line_id} className="scope-line">
          <div className="toolbar">
            <div className="grow">
              <strong>{ln.item_no ?? ""}</strong> <span className="clamp" title={ln.description}>{ln.description}</span>
              <div className="muted small">
                BOQ {ln.boq_qty ? `${num(ln.boq_qty, 3)} ${ln.unit ?? ""}` : (ln.qty_note ?? "—")} · assigned {num(ln.assigned, 3)}
                {ln.state !== "ok" && ln.state !== "no_qty" && ` (${Number(ln.difference) > 0 ? "+" : ""}${num(ln.difference, 3)})`}{" "}
                <span className={`badge ${STATE[ln.state][0]}`}>{STATE[ln.state][1]}</span>
              </div>
            </div>
            {canEdit && (
              <button className="btn btn-small" disabled={!nodes.length} onClick={() => setAssigning(ln)}>
                Assign to areas
              </button>
            )}
          </div>
          {ln.scopes.length > 0 && <ScopeTable scopes={ln.scopes} canEdit={canEdit} siteId={site.id} onDone={run} />}
        </div>
      ))}
      {data.other_scopes.length > 0 && (
        <>
          <h3 className="section-title top-gap">Other scopes</h3>
          <ScopeTable scopes={data.other_scopes} canEdit={canEdit} siteId={site.id} onDone={run} />
        </>
      )}
      {assigning && lookups && (
        <AssignDialog
          site={site}
          line={assigning}
          nodes={nodes}
          templates={lookups.templates}
          onClose={() => setAssigning(null)}
          onSaved={(d) => {
            setData(d);
            setAssigning(null);
            onChange();
          }}
        />
      )}
    </div>
  );
}

function ScopeTable({ scopes, canEdit, siteId, onDone }: { scopes: AreaScope[]; canEdit: boolean; siteId: number; onDone: (p: Promise<ScopeOverview>) => Promise<void> }) {
  return (
    <table className="table compact">
      <thead>
        <tr>
          <th>Place</th>
          <th>Stage template</th>
          <th className="num">Qty</th>
          <th>Tasks</th>
          <th>Progress</th>
          {canEdit && <th />}
        </tr>
      </thead>
      <tbody>
        {scopes.map((s) => (
          <tr key={s.id}>
            <td>{s.node_path}</td>
            <td>{s.stage_template_name}</td>
            <td className="num">
              {num(s.qty, 3)} {s.unit ?? ""}
            </td>
            <td className="muted small">
              {s.tasks} ({s.started} started)
            </td>
            <td style={{ width: "8rem" }}>
              <ProgressBar value={s.progress_percent} />
            </td>
            {canEdit && (
              <td className="row-actions nowrap">
                <button
                  className="btn btn-small btn-ghost"
                  onClick={() => {
                    const qty = prompt("Quantity", s.qty);
                    if (qty) void onDone(api<ScopeOverview>(`/api/sites/${siteId}/scopes/${s.id}`, { method: "PATCH", json: { qty } }));
                  }}
                >
                  Qty
                </button>
                <button
                  className="btn btn-small btn-ghost"
                  disabled={s.started > 0}
                  onClick={() => confirm(`Remove ${s.node_path}?`) && void onDone(api<ScopeOverview>(`/api/sites/${siteId}/scopes/${s.id}`, { method: "DELETE" }))}
                >
                  Remove
                </button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AssignDialog({
  site,
  line,
  nodes,
  templates,
  onClose,
  onSaved,
}: {
  site: Site;
  line: ScopeLine;
  nodes: SiteNode[];
  templates: { id: number; name: string }[];
  onClose: () => void;
  onSaved: (d: ScopeOverview) => void;
}) {
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [template, setTemplate] = useState(String(line.suggested_template_id ?? templates[0]?.id ?? ""));
  const [replace, setReplace] = useState(line.scopes.length > 0);
  const [qty, setQty] = useState("");
  const [under, setUnder] = useState("");
  const [kind, setKind] = useState("toilet");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const depth = useMemo(() => depthOf(nodes), [nodes]);

  async function shortcut() {
    try {
      const ids = await api<number[]>(`/api/sites/${site.id}/nodes/select?kind=${kind}${under ? `&under=${under}` : ""}`);
      setPicked((p) => new Set([...p, ...ids]));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function save() {
    setError(null);
    try {
      onSaved(
        await api<ScopeOverview>(`/api/sites/${site.id}/scope/assign`, {
          method: "POST",
          json: { boq_line_id: line.boq_line_id, node_ids: [...picked], stage_template_id: Number(template), replace, qty: qty || null },
        }),
      );
    } catch (err) {
      setError(errorText(err));
    }
  }

  const pickedNodes = nodes.filter((n) => picked.has(n.id));
  const allHaveArea = pickedNodes.length > 0 && pickedNodes.every((n) => n.area_sqm && Number(n.area_sqm) > 0);
  const shown = nodes.filter((n) => !filter || n.path.toLowerCase().includes(filter.toLowerCase()));

  return (
    <Modal title={`Assign ${line.item_no ?? "line"} to areas`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="small clamp">{line.description}</p>
      <div className="grid-2">
        <label className="field">
          <span>Stage template {String(line.suggested_template_id) === template && <span className="badge badge-info">suggested</span>}</span>
          <select value={template} onChange={(e) => setTemplate(e.target.value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Quantity to split {line.boq_qty ? `(default: BOQ ${num(line.boq_qty, 3)} ${line.unit ?? ""})` : "(required: QRO line)"}</span>
          <input value={qty} onChange={(e) => setQty(e.target.value)} placeholder={line.boq_qty ?? ""} />
        </label>
      </div>
      <div className="inline-form">
        <span className="muted">Add all</span>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {NODE_KINDS.map((k) => (
            <option key={k} value={k}>
              {k.replace("_", " ")}s
            </option>
          ))}
        </select>
        <span className="muted">in</span>
        <select value={under} onChange={(e) => setUnder(e.target.value)}>
          <option value="">the whole site</option>
          {nodes
            .filter((n) => ["tower", "wing", "floor", "basement", "podium"].includes(n.kind))
            .map((n) => (
              <option key={n.id} value={n.id}>
                {n.path}
              </option>
            ))}
        </select>
        <button className="btn btn-small" onClick={() => void shortcut()}>
          Add
        </button>
        <button className="btn btn-small btn-ghost" onClick={() => setPicked(new Set())}>
          Clear
        </button>
        <input className="search grow" placeholder="Filter places" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="tree-pick top-gap">
        {shown.map((n) => (
          <label key={n.id} className="check" style={{ paddingLeft: `${(depth.get(n.id) ?? 0) * 1.1}rem` }}>
            <input
              type="checkbox"
              checked={picked.has(n.id)}
              onChange={(e) =>
                setPicked((p) => {
                  const next = new Set(p);
                  if (e.target.checked) next.add(n.id);
                  else next.delete(n.id);
                  return next;
                })
              }
            />{" "}
            {n.name} <span className="muted small">{n.kind.replace("_", " ")}{n.area_sqm ? ` · ${n.area_sqm} sqm` : ""}</span>
          </label>
        ))}
      </div>
      <p className="muted small">
        {picked.size} places picked · the quantity is split {allHaveArea ? "by their area" : "equally (not every picked place has an area)"}.
      </p>
      {line.scopes.length > 0 && (
        <label className="check">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace this line&apos;s current assignment (only possible while no task has started)
        </label>
      )}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={!picked.size || !template} onClick={() => void save()}>
          Assign to {picked.size} places
        </button>
      </div>
    </Modal>
  );
}
