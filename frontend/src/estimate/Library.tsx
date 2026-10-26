// The product consumption library: per product its wastage and pack, and its coverages (per system
// or any system) with the range, the source and the document behind it; the mix designs worked at
// any thickness; and every change made to either.
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../api";
import { errorText, num, showError } from "../format";
import { Button, Card, EmptyState, Field, FilePicker, PageSkeleton, Tabs } from "../ui/components";
import { Modal } from "../ui/Overlay";
import { E, MIX_KINDS, useLibrary, when } from "./common";
import type { Coverage, LibProduct, Library, Mix, MixComponent } from "./common";
import "./estimate.css";

export default function MaterialLibrary() {
  const [tab, setTab] = useState("products");
  const [lib, reload, error] = useLibrary();
  return (
    <>
      <div className="page-header">
        <h1>Material library</h1>
      </div>
      <p className="muted">
        What a sqm takes of each product: the figure every estimate, request and margin check reads. A product with no coverage here makes them say they are not complete.
      </p>
      <Tabs
        tabs={[
          { key: "products", label: "Products", count: lib?.products.length },
          { key: "mixes", label: "Mix designs" },
          { key: "changes", label: "Changes" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "products" && (lib ? <Products lib={lib} reload={reload} /> : !error && <PageSkeleton />)}
      {tab === "mixes" && lib && <Mixes lib={lib} />}
      {tab === "changes" && <Changes />}
    </>
  );
}

// --- products and coverages ------------------------------------------------------------------------

function Products({ lib, reload }: { lib: Library; reload: () => void }) {
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const shown = lib.products.filter((p) => !q || `${p.name} ${p.code} ${p.brand ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="toolbar">
        <Field label="Find a product" bare>
          <input className="search" type="search" placeholder="Find a product" value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        {lib.can_edit && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            Add a coverage
          </Button>
        )}
      </div>
      {shown.length === 0 && <EmptyState title={q ? "No product matches" : "No coverage in the library yet"} hint={lib.can_edit ? "Add a coverage for a product: its value, range and source." : undefined} />}
      {shown.map((p) => (
        <ProductCard key={p.id} p={p} lib={lib} reload={reload} />
      ))}
      {adding && <CoverageForm lib={lib} onClose={() => setAdding(false)} onSaved={reload} />}
    </>
  );
}

function ProductCard({ p, lib, reload }: { p: LibProduct; lib: Library; reload: () => void }) {
  const [editing, setEditing] = useState(false);
  const [cov, setCov] = useState<Coverage | "new" | null>(null);
  const [error, setError] = useState("");
  const remove = async (c: Coverage) => {
    if (!window.confirm(`Delete the coverage ${c.label}${c.system ? ` in ${c.system}` : ""}?`)) return;
    try {
      await api(`${E}/coverages/${c.id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setError(errorText(err));
    }
  };
  const upload = async (c: Coverage, file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      await api(`${E}/coverages/${c.id}/doc`, { method: "POST", form });
      reload();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <Card
      title={
        <>
          {p.name} <span className="muted small">{[p.code, p.brand].filter(Boolean).join(" · ")}</span>
        </>
      }
      actions={
        lib.can_edit && (
          <>
            <Button size="small" onClick={() => setEditing(true)}>
              Wastage and pack
            </Button>
            <Button size="small" onClick={() => setCov("new")}>
              Add coverage
            </Button>
          </>
        )
      }
    >
      <p className="small">
        Wastage <strong>{num(p.wastage_percent ?? 0, 2)}%</strong> · Pack {p.pack_size ? <strong>{`${num(p.pack_size)} ${p.unit}${p.pack_unit ? ` ${p.pack_unit}` : ""}`}</strong> : <span className="muted">not set (quantity only)</span>} · Unit {p.unit}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>System</th>
              <th className="num">Value used</th>
              <th className="num">Min – max</th>
              <th>Unit</th>
              <th className="num">Per sqm</th>
              <th>Source</th>
              <th>Document</th>
              {lib.can_edit && <th />}
            </tr>
          </thead>
          <tbody>
            {p.coverages.map((c) => (
              <tr key={c.id}>
                <td>{c.system ?? <span className="muted">any system</span>}</td>
                <td className="num">
                  <strong>{num(c.value)}</strong>
                </td>
                <td className="num">{c.min_value || c.max_value ? `${num(c.min_value)} – ${num(c.max_value)}` : "—"}</td>
                <td>{c.unit}</td>
                <td className="num">
                  {num(c.per_sqm)} {p.unit}
                </td>
                <td>
                  <span className={`badge ${c.source === "to_confirm" ? "badge-warn" : "badge-muted"}`}>{c.source_label}</span>
                  {c.note && <div className="small muted">{c.note}</div>}
                </td>
                <td>
                  {c.has_doc ? (
                    <Button size="small" variant="ghost" onClick={() => void downloadFile(`${E}/coverages/${c.id}/doc`).catch(showError)}>
                      {c.doc_name ?? "Download"}
                    </Button>
                  ) : (
                    <span className="muted">—</span>
                  )}
                  {lib.can_edit && (
                    <Field as="div" label={c.has_doc ? "Replace the document" : "Attach a document"} className="small">
                      <FilePicker label="Choose the document" size="small" accept=".docx,.xlsx,.xls" onFiles={(fs) => void upload(c, fs[0])} />
                    </Field>
                  )}
                </td>
                {lib.can_edit && (
                  <td>
                    <div className="row-actions">
                      <Button size="small" onClick={() => setCov(c)}>
                        Edit
                      </Button>
                      <Button size="small" variant="danger" onClick={() => void remove(c)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <ProductForm p={p} onClose={() => setEditing(false)} onSaved={reload} />}
      {cov && <CoverageForm lib={lib} product={p} coverage={cov === "new" ? undefined : cov} onClose={() => setCov(null)} onSaved={reload} />}
    </Card>
  );
}

function ProductForm({ p, onClose, onSaved }: { p: LibProduct; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ wastage_percent: p.wastage_percent ?? "0", pack_size: p.pack_size ?? "", pack_unit: p.pack_unit ?? "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`${E}/products/${p.id}`, { method: "PUT", json: { wastage_percent: f.wastage_percent || "0", pack_size: f.pack_size || null, pack_unit: f.pack_unit || null } });
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`${p.name}: wastage and pack`} onClose={onClose}>
      <form onSubmit={save}>
        <div className="grid-2">
          <Field label="Wastage %">
            <input type="number" min="0" max="100" step="any" required value={f.wastage_percent} onChange={(e) => setF({ ...f, wastage_percent: e.target.value })} />
          </Field>
          <Field label={`Pack size (${p.unit})`} hint="Empty: the quantity is not put in packs">
            <input type="number" min="0" step="any" value={f.pack_size} onChange={(e) => setF({ ...f, pack_size: e.target.value })} />
          </Field>
          <Field label="Pack" hint="bag, drum, pail, roll">
            <input value={f.pack_unit} maxLength={20} onChange={(e) => setF({ ...f, pack_unit: e.target.value })} />
          </Field>
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

type ProductHit = { id: number; code: string; name: string; unit: string };

function CoverageForm({ lib, product, coverage, onClose, onSaved }: { lib: Library; product?: LibProduct; coverage?: Coverage; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    product_id: product?.id ?? 0,
    system_id: coverage?.system_id ? String(coverage.system_id) : "",
    value: coverage?.value ?? "",
    min_value: coverage?.min_value ?? "",
    max_value: coverage?.max_value ?? "",
    unit: coverage?.unit ?? "kg/sqm",
    source: coverage?.source ?? "to_confirm",
    note: coverage?.note ?? "",
  });
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<ProductHit[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (product || q.trim().length < 2) return setHits([]);
    const t = window.setTimeout(() => {
      api<{ items: ProductHit[] }>(`/api/products?q=${encodeURIComponent(q.trim())}&limit=20`).then(
        (r) => setHits(r.items),
        () => setHits([]),
      );
    }, 250);
    return () => window.clearTimeout(t);
  }, [q, product]);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!f.product_id) return setError("Choose the product");
    setBusy(true);
    const json = {
      product_id: f.product_id,
      system_id: f.system_id ? Number(f.system_id) : null,
      value: f.value,
      min_value: f.min_value || null,
      max_value: f.max_value || null,
      unit: f.unit,
      source: f.source,
      note: f.note || null,
    };
    try {
      await api(coverage ? `${E}/coverages/${coverage.id}` : `${E}/coverages`, { method: coverage ? "PUT" : "POST", json });
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={coverage ? `Change the coverage of ${product?.name}` : product ? `A coverage for ${product.name}` : "Add a coverage"} onClose={onClose}>
      <form onSubmit={save}>
        {!product && (
          <>
            <Field label="Product" hint="Type two letters of its name or code">
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a product" />
            </Field>
            {hits.length > 0 && (
              <Field label="Pick it">
                <select value={f.product_id || ""} onChange={(e) => setF({ ...f, product_id: Number(e.target.value) })}>
                  <option value="">— product —</option>
                  {hits.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.name} ({h.code}, {h.unit})
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </>
        )}
        <div className="grid-2">
          <Field label="System" hint="Any system: used where the product has no coverage for the line's own system">
            <select value={f.system_id} onChange={(e) => setF({ ...f, system_id: e.target.value })}>
              <option value="">Any system</option>
              {lib.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Unit">
            <select value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}>
              {lib.units.map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </Field>
          <Field label="Value used">
            <input type="number" min="0" step="any" required value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />
          </Field>
          <Field label="Source">
            <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
              {lib.sources.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Min" hint="The data sheet's lowest">
            <input type="number" min="0" step="any" value={f.min_value} onChange={(e) => setF({ ...f, min_value: e.target.value })} />
          </Field>
          <Field label="Max" hint="and highest">
            <input type="number" min="0" step="any" value={f.max_value} onChange={(e) => setF({ ...f, max_value: e.target.value })} />
          </Field>
        </div>
        <Field label="Note">
          <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        </Field>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// --- mix designs ---------------------------------------------------------------------------------

function Mixes({ lib }: { lib: Library }) {
  const [mixes, setMixes] = useState<Mix[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Mix | "new" | null>(null);
  const load = () => api<Mix[]>(`${E}/mixes`).then(setMixes, (e) => setError(errorText(e)));
  useEffect(() => {
    void load();
  }, []);
  if (!mixes) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton />;
  return (
    <>
      {lib.can_edit && (
        <div className="toolbar">
          <Button variant="primary" onClick={() => setEditing("new")}>
            New mix design
          </Button>
        </div>
      )}
      {mixes.length === 0 && <EmptyState title="No mix design yet" hint="Nodular concrete, plaster, brick bat: what a sqm takes at a thickness." />}
      {mixes.map((m) => (
        <MixCard key={m.id} mix={m} canEdit={lib.can_edit} onEdit={() => setEditing(m)} />
      ))}
      {editing && <MixForm mix={editing === "new" ? undefined : editing} lib={lib} onClose={() => setEditing(null)} onSaved={() => void load()} />}
    </>
  );
}

function MixCard({ mix, canEdit, onEdit }: { mix: Mix; canEdit: boolean; onEdit: () => void }) {
  const [mm, setMm] = useState(String(Number(mix.thickness_mm)));
  const [at, setAt] = useState<Mix>(mix);
  const [error, setError] = useState("");
  useEffect(() => setAt(mix), [mix]);
  useEffect(() => {
    if (!(Number(mm) > 0) || Number(mm) === Number(at.at_mm)) return;
    const t = window.setTimeout(() => {
      api<Mix>(`${E}/mixes/${mix.id}?thickness_mm=${encodeURIComponent(mm)}`).then(
        (r) => (setAt(r), setError("")),
        (e) => setError(errorText(e)),
      );
    }, 250);
    return () => window.clearTimeout(t);
  }, [mm, mix.id, at.at_mm]);
  return (
    <Card
      title={
        <>
          {mix.name} <span className="muted small">{[mix.code, MIX_KINDS[mix.kind]].join(" · ")}</span>
        </>
      }
      actions={
        canEdit && (
          <Button size="small" onClick={onEdit}>
            Edit
          </Button>
        )
      }
    >
      <p className="small muted">
        Dry volume factor {num(mix.dry_volume_factor)} · parts {mix.components.map((c) => `${c.role} ${num(c.parts)}`).join(" : ")} · cement bag {num(mix.cement_bag_kg)} kg
        {mix.admixture_per_bag ? ` · admixture ${num(mix.admixture_per_bag)} per bag` : ""}
        {mix.round_sqft !== null ? ` · kg/sqft rounded to ${mix.round_sqft} decimals` : ""}
        {mix.note ? ` · ${mix.note}` : ""}
      </p>
      <Field label="Thickness (mm)" inline>
        <input type="number" min="1" step="any" value={mm} onChange={(e) => setMm(e.target.value)} />
      </Field>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Product</th>
              <th className="num">Per sqm</th>
              <th className="num">Per sqft</th>
              <th>How</th>
            </tr>
          </thead>
          <tbody>
            {at.parts.map((p, i) => (
              <tr key={i}>
                <td>{p.role}</td>
                <td>{p.product ?? <span className="muted">no product</span>}</td>
                <td className="num">
                  <strong>{num(p.per_sqm, 3)}</strong> {p.unit}
                </td>
                <td className="num">
                  {num(p.per_sqft, 4)} {p.unit}
                </td>
                <td className="small">{p.how}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function MixForm({ mix, lib, onClose, onSaved }: { mix?: Mix; lib: Library; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    code: mix?.code ?? "",
    name: mix?.name ?? "",
    kind: mix?.kind ?? "nodular",
    thickness_mm: mix?.thickness_mm ?? "",
    dry_volume_factor: mix?.dry_volume_factor ?? "1.27",
    admixture_product_id: mix?.admixture_product_id ? String(mix.admixture_product_id) : "",
    admixture_per_bag: mix?.admixture_per_bag ?? "",
    cement_bag_kg: mix?.cement_bag_kg ?? "50",
    round_sqft: mix?.round_sqft === null || mix?.round_sqft === undefined ? "" : String(mix.round_sqft),
    source: mix?.source ?? "to_confirm",
    note: mix?.note ?? "",
  });
  const [comps, setComps] = useState<MixComponent[]>(mix?.components ?? [{ role: "cement", product_id: null, parts: 1, density: 1440 }]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const setComp = (i: number, patch: Partial<MixComponent>) => setComps(comps.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const json = {
      ...f,
      admixture_product_id: f.admixture_product_id ? Number(f.admixture_product_id) : null,
      admixture_per_bag: f.admixture_per_bag || null,
      round_sqft: f.round_sqft === "" ? null : Number(f.round_sqft),
      note: f.note || null,
      components: comps,
    };
    try {
      await api(mix ? `${E}/mixes/${mix.id}` : `${E}/mixes`, { method: mix ? "PUT" : "POST", json });
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={mix ? `Edit ${mix.name}` : "New mix design"} onClose={onClose} wide>
      <form onSubmit={save}>
        <div className="grid-4">
          <Field label="Code">
            <input required maxLength={40} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
          </Field>
          <Field label="Name">
            <input required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </Field>
          <Field label="Kind">
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              {Object.entries(MIX_KINDS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Thickness (mm)">
            <input type="number" min="0" step="any" required value={f.thickness_mm} onChange={(e) => setF({ ...f, thickness_mm: e.target.value })} />
          </Field>
          <Field label="Dry volume factor">
            <input type="number" min="0" step="any" required value={f.dry_volume_factor} onChange={(e) => setF({ ...f, dry_volume_factor: e.target.value })} />
          </Field>
          <Field label="Cement bag (kg)">
            <input type="number" min="0" step="any" required value={f.cement_bag_kg} onChange={(e) => setF({ ...f, cement_bag_kg: e.target.value })} />
          </Field>
          <Field label="Round kg/sqft to" hint="decimals, as the planning sheet; empty: not rounded">
            <input type="number" min="0" max="4" value={f.round_sqft} onChange={(e) => setF({ ...f, round_sqft: e.target.value })} />
          </Field>
          <Field label="Source">
            <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
              {lib.sources.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <h3>Components</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Product</th>
                <th className="num">Parts</th>
                <th className="num">Bulk density (kg/m³)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {comps.map((c, i) => (
                <tr key={i}>
                  <td>
                    <Field label="Role" bare>
                      <input required value={c.role} onChange={(e) => setComp(i, { role: e.target.value })} />
                    </Field>
                  </td>
                  <td>
                    <Field label="Product" bare>
                      <select value={c.product_id ?? ""} onChange={(e) => setComp(i, { product_id: e.target.value ? Number(e.target.value) : null })}>
                        <option value="">— none —</option>
                        {lib.products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                  </td>
                  <td>
                    <Field label="Parts" bare>
                      <input type="number" min="0" step="any" required value={c.parts} onChange={(e) => setComp(i, { parts: Number(e.target.value) })} />
                    </Field>
                  </td>
                  <td>
                    <Field label="Bulk density" bare>
                      <input type="number" min="0" step="any" required value={c.density} onChange={(e) => setComp(i, { density: Number(e.target.value) })} />
                    </Field>
                  </td>
                  <td>
                    <Button size="small" variant="ghost" icon aria-label="Remove the component" onClick={() => setComps(comps.filter((_, j) => j !== i))}>
                      ×
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button size="small" onClick={() => setComps([...comps, { role: "", product_id: null, parts: 1, density: 1600 }])}>
          Add a component
        </Button>
        <p className="small muted">The cement component's role must be "cement" for the admixture to be dosed per bag.</p>
        <div className="grid-2">
          <Field label="Admixture">
            <select value={f.admixture_product_id} onChange={(e) => setF({ ...f, admixture_product_id: e.target.value })}>
              <option value="">— none —</option>
              {lib.products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Admixture per cement bag" hint="L or kg per bag">
            <input type="number" min="0" step="any" value={f.admixture_per_bag} onChange={(e) => setF({ ...f, admixture_per_bag: e.target.value })} />
          </Field>
        </div>
        <Field label="Note">
          <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        </Field>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// --- changes ------------------------------------------------------------------------------------

type Change = { id: number; at: string; action: string; entity: string; entity_id: number; before: unknown; after: unknown };

const ACTIONS: Record<string, string> = {
  "coverage.create": "Coverage added",
  "coverage.update": "Coverage changed",
  "coverage.delete": "Coverage deleted",
  "coverage.document": "Document attached",
  "coverage.product": "Wastage or pack changed",
  "mix.create": "Mix design added",
  "mix.update": "Mix design changed",
};

const SKIP = new Set(["id", "created_by", "created_at", "updated_at", "doc_path"]);

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** What changed: each field whose value differs, before → after (all of them for an add or delete). */
function diff(before: unknown, after: unknown): { key: string; was: string; now: string }[] {
  const b = (before && typeof before === "object" ? before : {}) as Record<string, unknown>;
  const a = (after && typeof after === "object" ? after : {}) as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((k) => !SKIP.has(k));
  return keys.map((k) => ({ key: k, was: show(b[k]), now: show(a[k]) })).filter((r) => r.was !== r.now);
}

function Changes() {
  const [rows, setRows] = useState<Change[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Change[]>(`${E}/library/changes`).then(setRows, (e) => setError(errorText(e)));
  }, []);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!rows) return <PageSkeleton />;
  if (rows.length === 0) return <EmptyState title="No change yet" />;
  return (
    <Card>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>What</th>
              <th>Before → after</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{when(r.at)}</td>
                <td>
                  {ACTIONS[r.action] ?? r.action}
                  <div className="small muted">
                    {r.entity.replace("_", " ")} {r.entity_id}
                  </div>
                </td>
                <td className="small">
                  {diff(r.before, r.after).map((d) => (
                    <div key={d.key}>
                      <span className="muted">{d.key.replace(/_/g, " ")}:</span> {d.was} → <strong>{d.now}</strong>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
