import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, inr, num } from "../format";
import type { Page, Product, RateBreakdown, System } from "../types";
import { useLearned } from "../sitecontrol/learned";
import { Button, Card, Field } from "../ui/components";

// consumption or coats left blank: "to confirm" (never guessed); the note says where figures come from
type Row = { product_id: number; consumption_per_unit: string; wastage_percent: string; coats: string; to_confirm: boolean; note: string; wastage_included: boolean };
const PER: Record<string, string> = { sqft: "sq ft", rft: "rft", sqm: "sqm", rmt: "rmt", nos: "nos" };
type Settings = {
  surface_prep_per_unit: string;
  labour_rate: string;
  labour_unit: string;
  default_margin_percent: string;
};

export default function SystemDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const seesCost = can("tender.margin");
  const canEdit = seesCost && can("library.edit");
  const [system, setSystem] = useState<System | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // the brand option shown and edited (a system with options); blank: the default one
  const [optionId, setOptionId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setSystem(await api<System>(`/api/systems/${id}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!system) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const options = system.options ?? [];
  const shown = options.find((o) => o.id === optionId) ?? options.find((o) => o.is_default) ?? options[0] ?? null;
  const makeDefault = async (id: number) => {
    setError(null);
    try {
      setSystem(await api<System>(`/api/systems/${system.id}/options/${id}/default`, { method: "PUT" }));
      setNotice("Default brand option set: workings, offer lines and estimates take it when none is chosen.");
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <>
      <p className="breadcrumb">
        <Link to="/systems">Systems</Link> / <code>{system.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>{system.name}</h1>
          {system.description && <p className="muted">{system.description}</p>}
          {system.to_confirm && <span className="badge badge-warn">To confirm</span>}
          {system.note && <p className="small muted">{system.note}</p>}
        </div>
        <div className="rate-badge">
          <span className="muted small">Selling rate</span>
          <strong>{system.rate ? inr(system.rate) : "—"}</strong>
          <span className="muted small">per {system.unit}</span>
        </div>
      </div>
      {system.rate_error && <div className="alert alert-warn">{system.rate_error}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}

      {options.length > 0 && (
        <Card as="div">
          <h2 className="section-title">Brand options</h2>
          <p className="small muted">The same work item with each brand's products{system.source === "company_bom" ? " (the company BOM)" : ""}. The rate working, the quotation and the estimate choose one; the default is used when none is chosen.</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }} aria-label="Brand options">
            {options.map((o) => (
              <Button key={o.id} variant={shown?.id === o.id ? "primary" : "ghost"} size="small" onClick={() => setOptionId(o.id)} aria-pressed={shown?.id === o.id}>
                {o.brand}
                {o.is_default ? " (default)" : ""} · {o.rate ? inr(o.rate) : "no rate"}
              </Button>
            ))}
          </div>
          {shown && (
            <p className="small muted top-gap">
              {shown.source_ref ? `From ${shown.source_ref}. ` : ""}
              {shown.rate_error ?? ""}
              {canEdit && !shown.is_default && (
                <Button size="small" onClick={() => void makeDefault(shown.id)}>
                  Make {shown.brand} the default
                </Button>
              )}
            </p>
          )}
        </Card>
      )}

      {!seesCost ? (
        <Card as="div">
          <h2 className="section-title">Products used</h2>
          <ul className="plain-list">
            {system.components.map((c) => (
              <li key={c.product_id}>
                {c.product_name} {c.brand && <span className="muted">({c.brand})</span>}
              </li>
            ))}
            {options.length > 0 && <li className="muted small">The default brand option&apos;s products.</li>}
          </ul>
        </Card>
      ) : (
        <CostView
          // remount after a save (or another brand option) so the form starts from what the server stored
          key={`${shown?.id ?? 0}:${JSON.stringify(system.cost)}`}
          optionId={shown?.id ?? null}
          system={system}
          canEdit={canEdit}
          onSaved={async (msg) => {
            setNotice(msg);
            await load();
          }}
          onError={setError}
        />
      )}
    </>
  );
}

function CostView({
  system,
  optionId,
  canEdit,
  onSaved,
  onError,
}: {
  system: System;
  optionId: number | null;
  canEdit: boolean;
  onSaved: (msg: string) => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const cost = system.cost!;
  // a system with brand options: the shown option's components only (each option is saved on its own)
  const mine = optionId === null ? cost.components : cost.components.filter((c) => c.option_id === optionId);
  const toRow = (c: (typeof cost.components)[number]): Row => ({
    product_id: c.product_id,
    consumption_per_unit: c.consumption_per_unit ?? "",
    wastage_percent: c.wastage_percent,
    coats: c.coats === null ? "" : String(c.coats),
    to_confirm: c.to_confirm,
    note: c.note ?? "",
    wastage_included: !!c.wastage_included,
  });
  const [rows, setRows] = useState<Row[]>(mine.map(toRow));
  const [settings, setSettings] = useState<Settings>({
    surface_prep_per_unit: cost.surface_prep_per_unit,
    labour_rate: cost.labour_rate,
    labour_unit: cost.labour_unit,
    default_margin_percent: cost.default_margin_percent,
  });
  const [products, setProducts] = useState<Product[]>([]);
  const [margin, setMargin] = useState(cost.default_margin_percent);
  const [breakdown, setBreakdown] = useState<RateBreakdown | null>(null);
  const [calcError, setCalcError] = useState<string | null>(null);
  const learned = useLearned(system.id);
  const siteAverage = (productId: number) => learned.find((l) => l.product_id === productId);

  useEffect(() => {
    if (!canEdit) return;
    api<Page<Product>>("/api/products?limit=500&active=true").then(
      (p) => setProducts(p.items),
      () => setProducts([]),
    );
  }, [canEdit]);

  // Live calculator: recompute on the server (Decimal arithmetic) as the margin changes.
  useEffect(() => {
    const value = margin.trim();
    if (value === "" || Number(value) < 0) return;
    const timer = setTimeout(() => {
      api<RateBreakdown>(`/api/systems/${system.id}/rate?margin=${encodeURIComponent(value)}${optionId ? `&option_id=${optionId}` : ""}`).then(
        (b) => {
          setBreakdown(b);
          setCalcError(null);
        },
        (err) => {
          setBreakdown(null);
          setCalcError(errorText(err));
        },
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [margin, system.id, system.rate, optionId]);

  const productName = (id: number) => cost.components.find((c) => c.product_id === id)?.product_name ?? products.find((p) => p.id === id)?.name ?? `#${id}`;

  const dirty =
    JSON.stringify(rows) !== JSON.stringify(mine.map(toRow)) ||
    settings.surface_prep_per_unit !== cost.surface_prep_per_unit ||
    settings.labour_rate !== cost.labour_rate ||
    settings.labour_unit !== cost.labour_unit ||
    settings.default_margin_percent !== cost.default_margin_percent;

  async function save() {
    onError(null);
    try {
      await api(`/api/systems/${system.id}`, {
        method: "PATCH",
        json: {
          ...settings,
          option_id: optionId,
          components: rows
            .filter((r) => r.product_id)
            .map((r) => ({
              product_id: r.product_id,
              consumption_per_unit: r.consumption_per_unit.trim() === "" ? null : r.consumption_per_unit,
              wastage_percent: r.wastage_percent,
              coats: r.coats.trim() === "" ? null : Number(r.coats),
              to_confirm: r.to_confirm || r.consumption_per_unit.trim() === "",
              note: r.note.trim() || null,
              wastage_included: r.wastage_included,
            })),
        },
      });
      await onSaved("System saved.");
    } catch (err) {
      onError(errorText(err));
    }
  }

  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const setSetting = (key: keyof Settings) => (e: { target: { value: string } }) => setSettings((s) => ({ ...s, [key]: e.target.value }));

  return (
    <div className="split">
      <Card as="div">
        <h2 className="section-title">Build-up</h2>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Consumption / {system.unit}</th>
                <th className="num">Coats</th>
                <th className="num">Wastage %</th>
                <th className="num" title="Median actual consumption over completed areas (sites)">
                  Site average
                </th>
                {canEdit && <th />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    {canEdit ? (
                      <Field label="Product" bare>
                        <select value={r.product_id} onChange={(e) => setRow(i, { product_id: Number(e.target.value) })}>
                          <option value={0}>Choose a product…</option>
                          {products.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name} {p.brand ? `(${p.brand})` : ""} — {p.unit}
                            </option>
                          ))}
                        </select>
                      </Field>
                    ) : (
                      productName(r.product_id)
                    )}
                    {r.note && <div className="small muted">{r.note}</div>}
                    {mine[i]?.source === "company_bom" && (
                      <div className="small muted">
                        Company BOM
                        {mine[i].original_consumption && mine[i].original_unit && mine[i].original_unit !== system.unit
                          ? `: ${num(mine[i].original_consumption!)} per ${PER[mine[i].original_unit!] ?? mine[i].original_unit} in the file`
                          : ""}
                      </div>
                    )}
                  </td>
                  <td className="num">
                    {canEdit ? (
                      <Field label="to confirm" bare>
                        <input
                          className="input-num"
                          type="number"
                          step="0.0001"
                          min="0"
                          value={r.consumption_per_unit}
                          placeholder="to confirm"
                          onChange={(e) => setRow(i, { consumption_per_unit: e.target.value })}
                        />
                      </Field>
                    ) : r.consumption_per_unit === "" ? (
                      <span className="badge badge-warn">to confirm</span>
                    ) : (
                      num(r.consumption_per_unit)
                    )}
                  </td>
                  <td className="num">
                    {canEdit ? (
                      <Field label="to confirm" bare>
                        <input className="input-num" type="number" step="1" min="1" value={r.coats} placeholder="to confirm" onChange={(e) => setRow(i, { coats: e.target.value })} />
                      </Field>
                    ) : r.coats === "" ? (
                      <span className="muted">to confirm</span>
                    ) : (
                      r.coats
                    )}
                  </td>
                  <td className="num">
                    {canEdit ? (
                      <Field label="Wastage %" bare>
                        <input className="input-num" type="number" step="0.01" min="0" value={r.wastage_percent} onChange={(e) => setRow(i, { wastage_percent: e.target.value })} disabled={r.wastage_included} />
                      </Field>
                    ) : (
                      !r.wastage_included && num(r.wastage_percent, 2)
                    )}
                    <label className="small muted" title="The figure already has its wastage (a sheet's or mesh's overlap): none is added">
                      <input type="checkbox" checked={r.wastage_included} disabled={!canEdit} onChange={(e) => setRow(i, { wastage_included: e.target.checked })} /> included
                    </label>
                  </td>
                  <td className="num muted">
                    {siteAverage(r.product_id) ? <span title={`${siteAverage(r.product_id)!.areas} completed area(s)`}>{num(siteAverage(r.product_id)!.site_average)}</span> : "—"}
                  </td>
                  {canEdit && (
                    <td>
                      <Button size="small" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} aria-label="Remove">
                        ×
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit && (
          <Button
            size="small"
            onClick={() => setRows((rs) => [...rs, { product_id: 0, consumption_per_unit: "", wastage_percent: "0", coats: "", to_confirm: true, note: "", wastage_included: false }])}
          >
            + Add product
          </Button>
        )}

        <div className="grid-2 top-gap">
          <Field label={<>Surface prep (₹ / {system.unit})</>}>
            <input type="number" step="0.01" min="0" value={settings.surface_prep_per_unit} onChange={setSetting("surface_prep_per_unit")} disabled={!canEdit} />
          </Field>
          <Field label="Default margin %">
            <input type="number" step="0.01" min="0" value={settings.default_margin_percent} onChange={setSetting("default_margin_percent")} disabled={!canEdit} />
          </Field>
          <Field label="Labour rate (₹)">
            <input type="number" step="0.01" min="0" value={settings.labour_rate} onChange={setSetting("labour_rate")} disabled={!canEdit} />
          </Field>
          <Field label="Labour per">
            <select value={settings.labour_unit} onChange={setSetting("labour_unit")} disabled={!canEdit}>
              <option value="sqm">sqm</option>
              <option value="sqft">sqft</option>
              {!["sqm", "sqft"].includes(system.unit) && <option value={system.unit}>{system.unit}</option>}
            </select>
          </Field>
        </div>
        {canEdit && (
          <div className="form-actions">
            <Button variant="primary" disabled={!dirty} onClick={() => void save()}>
              Save system
            </Button>
          </div>
        )}
      </Card>

      <Card as="div" className="calculator">
        <h2 className="section-title">Rate calculator</h2>
        <Field label="Margin %">
          <input type="number" step="0.5" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
        </Field>
        {dirty && <p className="muted small">Save the system to include unsaved changes in the calculation.</p>}
        {calcError && <div className="alert alert-warn">{calcError}</div>}
        {breakdown && (
          <>
            <table className="table compact">
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Qty incl. wastage</th>
                  <th className="num">Landed rate</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {breakdown.components.map((c, i) => (
                  <tr key={i}>
                    <td>{c.product_name}</td>
                    <td className="num">
                      {num(c.quantity_with_wastage)} {c.unit}
                    </td>
                    <td className="num" title={`purchase ${inr(c.purchase_rate)} + freight ${inr(c.freight_per_unit)}`}>
                      {inr(c.landed_rate)}
                    </td>
                    <td className="num">{inr(c.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <dl className="totals">
              <dt>Materials</dt>
              <dd>{inr(breakdown.material_cost)}</dd>
              <dt>Surface preparation</dt>
              <dd>{inr(breakdown.surface_prep)}</dd>
              <dt>
                Labour{" "}
                {breakdown.labour_unit !== breakdown.unit && (
                  <span className="muted small">
                    ({inr(breakdown.labour_rate)}/{breakdown.labour_unit})
                  </span>
                )}
              </dt>
              <dd>{inr(breakdown.labour_per_unit)}</dd>
              <dt className="subtotal">Cost</dt>
              <dd className="subtotal">{inr(breakdown.base_cost)}</dd>
              <dt>Margin {num(breakdown.margin_percent, 2)}%</dt>
              <dd>{inr(breakdown.margin_amount)}</dd>
              <dt className="grand">Rate / {breakdown.unit}</dt>
              <dd className="grand">{inr(breakdown.rate)}</dd>
            </dl>
          </>
        )}
      </Card>
    </div>
  );
}
