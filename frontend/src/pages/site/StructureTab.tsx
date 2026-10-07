import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText } from "../../format";
import type { Site, SiteNode } from "../../types";
import { ProgressBar } from "../Sites";

export const NODE_KINDS = [
  "tower", "wing", "basement", "floor", "flat", "toilet", "kitchen", "balcony", "terrace", "podium",
  "lift_pit", "ug_tank", "oh_tank", "retaining_wall", "raft", "stp", "swimming_pool", "other",
];

export function useNodes(siteId: number) {
  const [nodes, setNodes] = useState<SiteNode[]>([]);
  const load = useCallback(async () => setNodes(await api<SiteNode[]>(`/api/sites/${siteId}/nodes`)), [siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  return { nodes, setNodes, load };
}

export function depthOf(nodes: SiteNode[]): Map<number, number> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = new Map<number, number>();
  const get = (n: SiteNode): number => {
    if (depth.has(n.id)) return depth.get(n.id)!;
    const d = n.parent_id && byId.get(n.parent_id) ? get(byId.get(n.parent_id)!) + 1 : 0;
    depth.set(n.id, d);
    return d;
  };
  nodes.forEach(get);
  return depth;
}

export default function StructureTab({ site, onChange }: { site: Site; onChange: () => void }) {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const { nodes, setNodes } = useNodes(site.id);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState<{ parent: SiteNode | null } | null>(null);
  const [tower, setTower] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const depth = useMemo(() => depthOf(nodes), [nodes]);
  const hasKids = useMemo(() => new Set(nodes.map((n) => n.parent_id).filter((x): x is number => x !== null)), [nodes]);
  const hidden = useMemo(() => {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const out = new Set<number>();
    for (const n of nodes) {
      let p = n.parent_id;
      while (p) {
        if (collapsed.has(p)) {
          out.add(n.id);
          break;
        }
        p = byId.get(p)?.parent_id ?? null;
      }
    }
    return out;
  }, [nodes, collapsed]);

  async function act(promise: Promise<SiteNode[]>) {
    setError(null);
    try {
      setNodes(await promise);
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function edit(n: SiteNode) {
    const name = prompt("Name", n.name);
    if (name === null) return;
    const area = prompt("Area (sqm), blank for none", n.area_sqm ?? "");
    if (area === null) return;
    await act(api<SiteNode[]>(`/api/sites/${site.id}/nodes/${n.id}`, { method: "PATCH", json: { name, area_sqm: area.trim() || null } }));
  }

  async function remove(n: SiteNode) {
    if (!confirm(`Delete ${n.path} and everything under it?`)) return;
    await act(api<SiteNode[]>(`/api/sites/${site.id}/nodes/${n.id}`, { method: "DELETE" }));
  }

  const counts = nodes.reduce<Record<string, number>>((acc, n) => ({ ...acc, [n.kind]: (acc[n.kind] ?? 0) + 1 }), {});

  return (
    <div className="card">
      <div className="toolbar">
        <div>
          <h2 className="section-title">Structure ({nodes.length} places)</h2>
          <span className="muted small">
            {Object.entries(counts)
              .map(([k, v]) => `${v} ${k.replace("_", " ")}`)
              .join(" · ")}
          </span>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={() => setCollapsed(new Set(nodes.filter((n) => hasKids.has(n.id)).map((n) => n.id)))}>
            Collapse all
          </button>
          <button className="btn btn-ghost" onClick={() => setCollapsed(new Set())}>
            Expand all
          </button>
          {canEdit && (
            <>
              <button className="btn" onClick={() => setAdding({ parent: null })}>
                Add place
              </button>
              <button className="btn btn-primary" onClick={() => setTower(true)}>
                Add tower…
              </button>
            </>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {nodes.length === 0 && <p className="empty">No structure yet. "Add tower…" builds a whole tower in one go.</p>}
      <table className="table compact tree">
        <tbody>
          {nodes
            .filter((n) => !hidden.has(n.id))
            .map((n) => (
              <tr key={n.id}>
                <td style={{ paddingLeft: `${0.5 + (depth.get(n.id) ?? 0) * 1.25}rem` }}>
                  {hasKids.has(n.id) ? (
                    <button
                      className="btn btn-small btn-ghost tree-toggle"
                      onClick={() =>
                        setCollapsed((c) => {
                          const next = new Set(c);
                          if (next.has(n.id)) next.delete(n.id);
                          else next.add(n.id);
                          return next;
                        })
                      }
                    >
                      {collapsed.has(n.id) ? "▸" : "▾"}
                    </button>
                  ) : (
                    <span className="tree-toggle" />
                  )}
                  <strong>{n.name}</strong> <span className="muted small">{n.kind.replace("_", " ")}</span>
                  {n.area_sqm && <span className="muted small"> · {n.area_sqm} sqm</span>}
                </td>
                <td style={{ width: "9rem" }}>
                  <ProgressBar value={n.progress_percent} />
                </td>
                {canEdit && (
                  <td className="row-actions nowrap">
                    <button className="btn btn-small btn-ghost" onClick={() => setAdding({ parent: n })}>
                      + Child
                    </button>
                    <button className="btn btn-small btn-ghost" onClick={() => void edit(n)}>
                      Edit
                    </button>
                    <button className="btn btn-small btn-ghost" onClick={() => void remove(n)}>
                      Delete
                    </button>
                  </td>
                )}
              </tr>
            ))}
        </tbody>
      </table>
      {adding && (
        <AddNode
          parent={adding.parent}
          onClose={() => setAdding(null)}
          onSave={async (body) => {
            await act(api<SiteNode[]>(`/api/sites/${site.id}/nodes`, { method: "POST", json: { ...body, parent_id: adding.parent?.id ?? null } }));
            setAdding(null);
          }}
        />
      )}
      {tower && (
        <TowerDialog
          siteId={site.id}
          nodes={nodes}
          onClose={() => setTower(false)}
          onCreated={(list) => {
            setNodes(list);
            setTower(false);
            onChange();
          }}
        />
      )}
    </div>
  );
}

function AddNode({ parent, onClose, onSave }: { parent: SiteNode | null; onClose: () => void; onSave: (b: Record<string, unknown>) => Promise<void> }) {
  const [form, setForm] = useState({ kind: "other", name: "", area_sqm: "", level_no: "" });
  function submit(e: FormEvent) {
    e.preventDefault();
    void onSave({ kind: form.kind, name: form.name, area_sqm: form.area_sqm || null, level_no: form.level_no === "" ? null : Number(form.level_no) });
  }
  return (
    <Modal title={parent ? `Add under ${parent.path}` : "Add a place"} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="grid-2">
          <label className="field">
            <span>Kind</span>
            <select value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}>
              {NODE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Name *</span>
            <input required autoFocus value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="field">
            <span>Area (sqm)</span>
            <input value={form.area_sqm} onChange={(e) => setForm((f) => ({ ...f, area_sqm: e.target.value }))} />
          </label>
          <label className="field">
            <span>Level (B2 = -2, G = 0)</span>
            <input type="number" value={form.level_no} onChange={(e) => setForm((f) => ({ ...f, level_no: e.target.value }))} />
          </label>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Add</button>
        </div>
      </form>
    </Modal>
  );
}

const DEFAULT_TOWER = {
  name: "T1",
  parent_id: "",
  basements: 1,
  ground: true,
  upper_floors: 4,
  flats_per_floor: 2,
  flats_from: "G",
  toilet: 2,
  kitchen: 1,
  balcony: 0,
  terrace: true,
  oh_tanks: 0,
  lift_pits: 0,
  ug_tanks: 0,
};

function TowerDialog({ siteId, nodes, onClose, onCreated }: { siteId: number; nodes: SiteNode[]; onClose: () => void; onCreated: (n: SiteNode[]) => void }) {
  const [form, setForm] = useState(DEFAULT_TOWER);
  const [preview, setPreview] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const body = useMemo(
    () => ({
      name: form.name,
      parent_id: form.parent_id ? Number(form.parent_id) : null,
      basements: form.basements,
      ground: form.ground,
      upper_floors: form.upper_floors,
      flats_per_floor: form.flats_per_floor,
      flats_from: form.flats_from,
      rooms_per_flat: { toilet: form.toilet, kitchen: form.kitchen, balcony: form.balcony },
      terrace: form.terrace,
      oh_tanks: form.oh_tanks,
      lift_pits: form.lift_pits,
      ug_tanks: form.ug_tanks,
    }),
    [form],
  );

  useEffect(() => {
    const t = setTimeout(() => {
      api<Record<string, number>>(`/api/sites/${siteId}/builder/tower/preview`, { method: "POST", json: body }).then(
        (p) => {
          setPreview(p);
          setError(null);
        },
        (err) => setError(errorText(err)),
      );
    }, 250);
    return () => clearTimeout(t);
  }, [siteId, body]);

  async function create() {
    try {
      onCreated(await api<SiteNode[]>(`/api/sites/${siteId}/builder/tower`, { method: "POST", json: body }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const num = (key: keyof typeof form) => (
    <input type="number" min={0} value={form[key] as number} onChange={(e) => setForm((f) => ({ ...f, [key]: Number(e.target.value) || 0 }))} />
  );

  return (
    <Modal title="Add a tower" onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="grid-4">
        <label className="field">
          <span>Tower name</span>
          <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </label>
        <label className="field">
          <span>Under</span>
          <select value={form.parent_id} onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}>
            <option value="">The site</option>
            {nodes
              .filter((n) => ["wing", "podium", "other"].includes(n.kind))
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.path}
                </option>
              ))}
          </select>
        </label>
        <label className="field">
          <span>Basements (B1…)</span>
          {num("basements")}
        </label>
        <label className="field">
          <span>Floors above G</span>
          {num("upper_floors")}
        </label>
        <label className="check">
          <input type="checkbox" checked={form.ground} onChange={(e) => setForm((f) => ({ ...f, ground: e.target.checked }))} /> Ground floor (G)
        </label>
        <label className="field">
          <span>Flats per floor</span>
          {num("flats_per_floor")}
        </label>
        <label className="field">
          <span>Flats from</span>
          <select value={form.flats_from} onChange={(e) => setForm((f) => ({ ...f, flats_from: e.target.value }))}>
            <option value="G">G and above</option>
            <option value="1">Floor 1 and above</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={form.terrace} onChange={(e) => setForm((f) => ({ ...f, terrace: e.target.checked }))} /> Terrace on top
        </label>
        <label className="field">
          <span>Toilets per flat</span>
          {num("toilet")}
        </label>
        <label className="field">
          <span>Kitchens per flat</span>
          {num("kitchen")}
        </label>
        <label className="field">
          <span>Balconies per flat</span>
          {num("balcony")}
        </label>
        <label className="field">
          <span>OH tanks (on terrace)</span>
          {num("oh_tanks")}
        </label>
        <label className="field">
          <span>Lift pits</span>
          {num("lift_pits")}
        </label>
        <label className="field">
          <span>UG tanks</span>
          {num("ug_tanks")}
        </label>
      </div>
      {preview && (
        <div className="alert alert-ok">
          <strong>{preview.total} places</strong> will be made:{" "}
          {Object.entries(preview)
            .filter(([k]) => k !== "total")
            .map(([k, v]) => `${v} ${k.replace("_", " ")}`)
            .join(" · ")}
        </div>
      )}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={!preview} onClick={() => void create()}>
          Create {preview?.total ?? ""} places
        </button>
      </div>
    </Modal>
  );
}
