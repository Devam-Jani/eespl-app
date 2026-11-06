// One work item in the consumption master: its areas and type, each brand option's BOM (consumption
// per unit and per sq ft / rft, wastage or "wastage included", coats, the product's TDS range and a
// warning outside it), a formulation (mix design) worked from thickness, and for those who see cost
// each product's price with "update rate", the material cost, labour and selling rate. Every change
// asks why and is kept in the history below.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText, inr, num } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, Card, Field, buttonClass } from "../ui/components";
import { useVocab } from "./ConsumptionMaster";

type Row = {
  component_id: number;
  product_id: number;
  product: string;
  brand: string | null;
  unit: string;
  step: string;
  per_unit: string | null;
  per_unit_label: string;
  per_small: string | null;
  small_label: string | null;
  wastage_percent: string;
  wastage_included: boolean;
  coats: number | null;
  tds_range: { lo: string; hi: string; unit: string; text: string; page: number | null; per_coat: boolean } | null;
  outside_tds: boolean;
  has_tds: boolean;
  price?: { rate: string; unit: string; date: string; basis: string; source: string } | null;
  price_per_unit?: string | null;
};
type Option = {
  id: number | null;
  brand: string | null;
  is_default: boolean;
  source: string | null;
  mix_design_id: number | null;
  mix_thickness_mm: string | null;
  rows: Row[];
  warnings: string[];
  cost: { material: string; labour: string; cost: string; margin_percent: string; rate: string | null; rate_small: string | null; unit: string; error?: string } | null;
};
type Item = {
  id: number;
  name: string;
  unit: string;
  areas: string[];
  areas_set: boolean;
  type: string | null;
  type_set: boolean;
  labour_rate: string | null;
  labour_unit: string;
  default_margin_percent: string | null;
  options: Option[];
  history: { id: number; what: string; field: string; old: string | null; new: string | null; reason: string | null; at: string; by: string | null }[];
  mix_designs: { id: number; code: string; name: string; thickness_mm: string }[];
  can_edit: boolean;
  can_cost: boolean;
};
type ProductHit = { id: number; name: string; brand: string | null; unit: string };

function ProductSearch({ label, onPick }: { label: string; onPick: (p: ProductHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<ProductHit[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) return setHits([]);
    const t = setTimeout(() => {
      api<{ items: ProductHit[] }>(`/api/products?q=${encodeURIComponent(q)}&limit=12`).then((r) => setHits(r.items), () => setHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div>
      <Field label={label}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type 2 letters of the product" />
      </Field>
      {hits.map((p) => (
        <Button key={p.id} size="small" variant="ghost" onClick={() => { onPick(p); setQ(""); setHits([]); }}>
          {p.name} {p.brand ? `(${p.brand})` : ""} · {p.unit}
        </Button>
      ))}
    </div>
  );
}

function EditRow({ item, row, onClose, onSaved }: { item: Item; row: Row; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ consumption_per_unit: row.per_unit ?? "", wastage_percent: row.wastage_percent ?? "0", wastage_included: row.wastage_included, coats: row.coats ? String(row.coats) : "", reason: "" });
  const [error, setError] = useState<string | null>(null);
  const perSmall = row.small_label && form.consumption_per_unit ? Number(form.consumption_per_unit) / (row.small_label === "rft" ? 3.2808 : 10.7639) : null;
  const save = async () => {
    try {
      // the master keeps the figure in the work item's own unit; the page shows per sqm (or rmt)
      const per = item.unit === "sqft" ? Number(form.consumption_per_unit) / 10.7639 : item.unit === "rft" ? Number(form.consumption_per_unit) / 3.2808 : form.consumption_per_unit;
      await api(`/api/spec/master/${item.id}/components/${row.component_id}`, {
        method: "PUT",
        json: {
          consumption_per_unit: form.consumption_per_unit === "" ? null : String(per),
          wastage_percent: form.wastage_percent || "0",
          wastage_included: form.wastage_included,
          coats: form.coats ? Number(form.coats) : null,
          reason: form.reason,
        },
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Modal title={`${row.product}: consumption`} onClose={onClose}>
      {error && <div className="alert alert-error">{error}</div>}
      <Field label={`Consumption per ${row.per_unit_label} (${row.unit})`}>
        <input value={form.consumption_per_unit} onChange={(e) => setForm({ ...form, consumption_per_unit: e.target.value })} />
      </Field>
      {perSmall !== null && Number.isFinite(perSmall) && (
        <p className="small muted">
          = {num(perSmall, 4)} per {row.small_label}
        </p>
      )}
      {row.tds_range && (
        <p className="small muted">
          TDS: {num(row.tds_range.lo, 3)}–{num(row.tds_range.hi, 3)} {row.tds_range.unit}
          {row.tds_range.per_coat ? " (per coat × coats)" : ""} · “{row.tds_range.text}”
        </p>
      )}
      <Field label="Wastage %">
        <input value={form.wastage_percent} disabled={form.wastage_included} onChange={(e) => setForm({ ...form, wastage_percent: e.target.value })} />
      </Field>
      <label className="small">
        <input type="checkbox" checked={form.wastage_included} onChange={(e) => setForm({ ...form, wastage_included: e.target.checked })} /> Wastage included in the figure (a sheet's
        or mesh's overlap)
      </label>
      <Field label="Coats">
        <input value={form.coats} onChange={(e) => setForm({ ...form, coats: e.target.value })} />
      </Field>
      <Field label="Why it changes (kept with the change)">
        <input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
      </Field>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" disabled={form.reason.trim().length < 3} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </Modal>
  );
}

function PriceWindow({ row, onClose, onSaved }: { row: Row; onClose: () => void; onSaved: () => void }) {
  const [rate, setRate] = useState("");
  const [perPack, setPerPack] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title={`Update rate: ${row.product}`} onClose={onClose}>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="small muted">
        Now: {row.price ? `${inr(row.price.rate)} per ${row.price.unit} (${row.price.basis}, ${row.price.date})` : "no price"}. A new price is a new row; a price per pack is converted once to per {row.unit}.
      </p>
      <Field label="Rate ₹">
        <input value={rate} onChange={(e) => setRate(e.target.value)} />
      </Field>
      <label className="small">
        <input type="checkbox" checked={perPack} onChange={(e) => setPerPack(e.target.checked)} /> The rate is per pack (bag, pail)
      </label>
      <div className="form-actions">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!(Number(rate) > 0)}
          onClick={() =>
            void api(`/api/spec/master/products/${row.product_id}/price`, { method: "POST", json: { rate, unit: perPack ? "pack" : null } }).then(onSaved, (e) => setError(errorText(e)))
          }
        >
          Save the rate
        </Button>
      </div>
    </Modal>
  );
}

export default function ConsumptionItem() {
  const { id } = useParams();
  const vocab = useVocab();
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editRow, setEditRow] = useState<Row | null>(null);
  const [priceRow, setPriceRow] = useState<Row | null>(null);
  const [brand, setBrand] = useState("");
  const [copy, setCopy] = useState<{ from: Option; brand: string; swaps: Record<number, ProductHit> } | null>(null);
  const [addTo, setAddTo] = useState<number | null>(null);
  const [mix, setMix] = useState<Record<number, { id: string; t: string }>>({});
  const [areasReason, setAreasReason] = useState("");
  const load = useCallback(() => {
    api<Item>(`/api/spec/master/${id}`).then(setItem, (e) => setError(errorText(e)));
  }, [id]);
  useEffect(load, [load]);
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(errorText(e));
    }
  };
  if (!item) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const edit = item.can_edit;
  const areaLabel = (k: string) => vocab?.areas.find((a) => a.key === k)?.label ?? k;

  return (
    <>
      <div className="page-header">
        <h1>
          {item.name} <span className="muted small">per {item.unit}</span>
        </h1>
        <div className="page-actions">
          <Link to="/consumption-master" className={buttonClass({ variant: "ghost" })}>
            ← Consumption master
          </Link>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card title="Areas and type">
        <p className="small">
          Areas: {item.areas.map(areaLabel).join(", ") || "not set"}
          {!item.areas_set && item.areas.length > 0 && <span className="muted"> (read from the name; tick them to set them)</span>}. Type:{" "}
          {item.type ? (vocab?.types.find((t) => t.key === item.type)?.label ?? item.type) : "not known"}
          {!item.type_set && item.type && <span className="muted"> (read from the name and products)</span>}.
          {item.can_cost && item.labour_rate !== null && (
            <>
              {" "}
              Labour {inr(item.labour_rate)} per {item.labour_unit}; default margin {num(item.default_margin_percent, 2)} % on the selling price.
            </>
          )}
        </p>
        {edit && vocab && (
          <>
            <div className="small">
              {vocab.areas.map((a) => (
                <label key={a.key} style={{ marginRight: 12 }}>
                  <input
                    type="checkbox"
                    checked={item.areas.includes(a.key)}
                    onChange={(e) =>
                      void act(() =>
                        api(`/api/spec/master/${item.id}`, {
                          method: "PATCH",
                          json: { area_keys: e.target.checked ? [...item.areas, a.key] : item.areas.filter((x) => x !== a.key), reason: areasReason || null },
                        }),
                      )
                    }
                  />{" "}
                  {a.label}
                </label>
              ))}
            </div>
            <div className="form-row">
              <Field label="System type">
                <select value={item.type_set ? (item.type ?? "") : ""} onChange={(e) => void act(() => api(`/api/spec/master/${item.id}`, { method: "PATCH", json: { spec_type: e.target.value || null, reason: areasReason || null } }))}>
                  <option value="">Read from the name and products</option>
                  {vocab.types.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Why (kept with the change)">
                <input value={areasReason} onChange={(e) => setAreasReason(e.target.value)} />
              </Field>
            </div>
          </>
        )}
      </Card>

      {item.options.map((o) => (
        <Card key={o.id ?? 0} title={`${o.brand ?? "One recipe"}${o.is_default ? " (default)" : ""}${o.source === "company_bom" ? " · company BOM" : ""}`}>
          {o.warnings.map((w) => (
            <div key={w} className="alert alert-warn small">
              {w}
            </div>
          ))}
          <div className="table-wrap">
            <table className="table small">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Product</th>
                  <th className="num">Per {item.unit === "sqft" ? "sqm" : item.unit === "rft" ? "rmt" : item.unit}</th>
                  <th className="num">Per sq ft / rft</th>
                  <th className="num">Wastage</th>
                  <th className="num">Coats</th>
                  <th>TDS range</th>
                  {item.can_cost && <th className="num">Price</th>}
                  {edit && <th />}
                </tr>
              </thead>
              <tbody>
                {o.rows.map((r) => (
                  <tr key={r.component_id}>
                    <td>{r.step}</td>
                    <td>
                      {r.product} <span className="muted">{r.unit}</span>
                    </td>
                    <td className="num">{num(r.per_unit, 4)}</td>
                    <td className="num">{num(r.per_small, 4)}</td>
                    <td className="num">{r.wastage_included ? "included" : `${num(r.wastage_percent, 2)} %`}</td>
                    <td className="num">{r.coats ?? "—"}</td>
                    <td className={r.outside_tds ? "text-warn" : "muted"}>
                      {r.tds_range ? `${num(r.tds_range.lo, 3)}–${num(r.tds_range.hi, 3)} ${r.tds_range.unit}` : r.has_tds ? "no consumption in TDS" : "no TDS"}
                      {r.outside_tds && " ⚠"}
                    </td>
                    {item.can_cost && (
                      <td className="num nowrap">
                        {r.price ? (
                          <span title={`${r.price.basis}, ${r.price.date}`}>
                            {inr(r.price_per_unit)} /{r.unit}
                            <div className="muted">{r.price.source}</div>
                          </span>
                        ) : (
                          <span className="text-warn">no price</span>
                        )}
                        {edit && (
                          <Button size="small" variant="ghost" onClick={() => setPriceRow(r)}>
                            update rate
                          </Button>
                        )}
                      </td>
                    )}
                    {edit && (
                      <td className="nowrap">
                        <Button size="small" variant="ghost" aria-label={`Edit ${r.product}`} onClick={() => setEditRow(r)}>
                          ✎
                        </Button>
                        <Button
                          size="small"
                          variant="ghost"
                          aria-label={`Remove ${r.product}`}
                          onClick={() => {
                            const why = window.prompt(`Remove ${r.product}: why?`);
                            if (why) void act(() => api(`/api/spec/master/${item.id}/components/${r.component_id}?reason=${encodeURIComponent(why)}`, { method: "DELETE" }));
                          }}
                        >
                          ×
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {o.cost && (
            <p className="small">
              {o.cost.error ? (
                <span className="text-warn">{o.cost.error}</span>
              ) : (
                <>
                  Material {inr(o.cost.material)}, labour {inr(o.cost.labour)}, cost {inr(o.cost.cost)} per {o.cost.unit} → selling rate <b>{inr(o.cost.rate)}</b> at {num(o.cost.margin_percent, 2)} %
                  {o.cost.rate_small ? ` (${inr(o.cost.rate_small)} per ${o.cost.unit === "rmt" ? "rft" : "sq ft"})` : ""}, today's prices.
                </>
              )}
            </p>
          )}
          {edit && o.id !== null && (
            <div className="form-row">
              <Button size="small" onClick={() => setAddTo(o.id)}>
                Add a product
              </Button>
              <Button size="small" onClick={() => setCopy({ from: o, brand: "", swaps: {} })}>
                Copy to another brand
              </Button>
              <Field label="Formulation (mix design)">
                <select value={mix[o.id]?.id ?? (o.mix_design_id ? String(o.mix_design_id) : "")} onChange={(e) => setMix({ ...mix, [o.id as number]: { id: e.target.value, t: mix[o.id as number]?.t ?? o.mix_thickness_mm ?? "" } })}>
                  <option value="">None</option>
                  {item.mix_designs.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.code}: {m.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Thickness mm">
                <input size={6} value={mix[o.id]?.t ?? o.mix_thickness_mm ?? ""} onChange={(e) => setMix({ ...mix, [o.id as number]: { id: mix[o.id as number]?.id ?? String(o.mix_design_id ?? ""), t: e.target.value } })} />
              </Field>
              <Button
                size="small"
                onClick={() => {
                  const m = mix[o.id as number];
                  void act(() => api(`/api/spec/master/${item.id}/options/${o.id}/mix`, { method: "PUT", json: { mix_design_id: m?.id ? Number(m.id) : null, thickness_mm: m?.t || null } }));
                }}
              >
                Work it out
              </Button>
            </div>
          )}
          {addTo === o.id && o.id !== null && (
            <ProductSearch
              label="The product to add"
              onPick={(p) => {
                setAddTo(null);
                void act(() => api(`/api/spec/master/${item.id}/components`, { method: "POST", json: { option_id: o.id, product_id: p.id } }));
              }}
            />
          )}
        </Card>
      ))}
      {edit && (
        <Card title="Add a brand option">
          <div className="form-row">
            <Field label="Brand">
              <input value={brand} onChange={(e) => setBrand(e.target.value)} />
            </Field>
            <Button disabled={!brand.trim()} onClick={() => void act(async () => { await api(`/api/spec/master/${item.id}/options`, { method: "POST", json: { brand } }); setBrand(""); })}>
              Add
            </Button>
          </div>
        </Card>
      )}

      <Card title="Changes">
        <div className="table-wrap">
          <table className="table small">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
                <th>Old</th>
                <th>New</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {item.history.map((h) => (
                <tr key={h.id}>
                  <td className="nowrap">{new Date(h.at).toLocaleString("en-IN")}</td>
                  <td>{h.by ?? "—"}</td>
                  <td>
                    {h.what} · {h.field.replace(/_/g, " ")}
                  </td>
                  <td>{h.old ?? "—"}</td>
                  <td>{h.new ?? "—"}</td>
                  <td>{h.reason ?? "—"}</td>
                </tr>
              ))}
              {item.history.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    No change yet. Issued estimates and sent quotations keep the figures they used.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {editRow && <EditRow item={item} row={editRow} onClose={() => setEditRow(null)} onSaved={() => { setEditRow(null); load(); }} />}
      {priceRow && <PriceWindow row={priceRow} onClose={() => setPriceRow(null)} onSaved={() => { setPriceRow(null); load(); }} />}
      {copy && (
        <Modal title={`Copy ${copy.from.brand ?? "the recipe"} to another brand`} onClose={() => setCopy(null)}>
          <Field label="The other brand">
            <input value={copy.brand} onChange={(e) => setCopy({ ...copy, brand: e.target.value })} />
          </Field>
          {copy.from.rows.map((r) => (
            <div key={r.product_id} className="small">
              {r.product} → {copy.swaps[r.product_id] ? <b>{copy.swaps[r.product_id].name}</b> : <span className="muted">kept</span>}
              <ProductSearch label={`Swap ${r.product} for`} onPick={(p) => setCopy({ ...copy, swaps: { ...copy.swaps, [r.product_id]: p } })} />
            </div>
          ))}
          <div className="form-actions">
            <Button variant="ghost" onClick={() => setCopy(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!copy.brand.trim()}
              onClick={() =>
                void act(async () => {
                  await api(`/api/spec/master/${item.id}/options/${copy.from.id}/copy`, {
                    method: "POST",
                    json: { brand: copy.brand, swaps: Object.fromEntries(Object.entries(copy.swaps).map(([k, v]) => [k, v.id])) },
                  });
                  setCopy(null);
                })
              }
            >
              Copy
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
