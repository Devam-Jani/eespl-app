import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { errorText, inr, num } from "../format";
import type { Page, Product, RateBreakdown, System } from "../types";

type Row = { product_id: number; consumption_per_unit: string; wastage_percent: string };
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

  return (
    <>
      <p className="breadcrumb">
        <Link to="/systems">Systems</Link> / <code>{system.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>{system.name}</h1>
          {system.description && <p className="muted">{system.description}</p>}
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

      {!seesCost ? (
        <div className="card">
          <h2 className="section-title">Products used</h2>
          <ul className="plain-list">
            {system.components.map((c) => (
              <li key={c.product_id}>
                {c.product_name} {c.brand && <span className="muted">({c.brand})</span>}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <CostView
          // remount after a save so the form starts from what the server stored
          key={JSON.stringify(system.cost)}
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
  canEdit,
  onSaved,
  onError,
}: {
  system: System;
  canEdit: boolean;
  onSaved: (msg: string) => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const cost = system.cost!;
  const [rows, setRows] = useState<Row[]>(
    cost.components.map((c) => ({
      product_id: c.product_id,
      consumption_per_unit: c.consumption_per_unit,
      wastage_percent: c.wastage_percent,
    })),
  );
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
      api<RateBreakdown>(`/api/systems/${system.id}/rate?margin=${encodeURIComponent(value)}`).then(
        (b) => {
          setBreakdown(b);
          setCalcError(null);
        },
        (err) => {
          setBreakdown(null);
          setCalcError(err instanceof ApiError ? err.message : String(err));
        },
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [margin, system.id, system.rate]);

  const productName = (id: number) =>
    cost.components.find((c) => c.product_id === id)?.product_name ?? products.find((p) => p.id === id)?.name ?? `#${id}`;

  const dirty =
    JSON.stringify(rows) !==
      JSON.stringify(
        cost.components.map((c) => ({
          product_id: c.product_id,
          consumption_per_unit: c.consumption_per_unit,
          wastage_percent: c.wastage_percent,
        })),
      ) ||
    settings.surface_prep_per_unit !== cost.surface_prep_per_unit ||
    settings.labour_rate !== cost.labour_rate ||
    settings.labour_unit !== cost.labour_unit ||
    settings.default_margin_percent !== cost.default_margin_percent;

  async function save() {
    onError(null);
    try {
      await api(`/api/systems/${system.id}`, {
        method: "PATCH",
        json: { ...settings, components: rows.filter((r) => r.product_id) },
      });
      await onSaved("System saved.");
    } catch (err) {
      onError(errorText(err));
    }
  }

  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const setSetting = (key: keyof Settings) => (e: { target: { value: string } }) =>
    setSettings((s) => ({ ...s, [key]: e.target.value }));

  return (
    <div className="split">
      <div className="card">
        <h2 className="section-title">Build-up</h2>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Consumption / {system.unit}</th>
                <th className="num">Wastage %</th>
                {canEdit && <th />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    {canEdit ? (
                      <select value={r.product_id} onChange={(e) => setRow(i, { product_id: Number(e.target.value) })}>
                        <option value={0}>Choose a product…</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} {p.brand ? `(${p.brand})` : ""} — {p.unit}
                          </option>
                        ))}
                      </select>
                    ) : (
                      productName(r.product_id)
                    )}
                  </td>
                  <td className="num">
                    {canEdit ? (
                      <input
                        className="input-num"
                        type="number"
                        step="0.0001"
                        min="0"
                        value={r.consumption_per_unit}
                        onChange={(e) => setRow(i, { consumption_per_unit: e.target.value })}
                      />
                    ) : (
                      num(r.consumption_per_unit)
                    )}
                  </td>
                  <td className="num">
                    {canEdit ? (
                      <input
                        className="input-num"
                        type="number"
                        step="0.01"
                        min="0"
                        value={r.wastage_percent}
                        onChange={(e) => setRow(i, { wastage_percent: e.target.value })}
                      />
                    ) : (
                      num(r.wastage_percent, 2)
                    )}
                  </td>
                  {canEdit && (
                    <td>
                      <button className="btn btn-small" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} aria-label="Remove">
                        ×
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit && (
          <button
            className="btn btn-small"
            onClick={() => setRows((rs) => [...rs, { product_id: 0, consumption_per_unit: "1", wastage_percent: "0" }])}
          >
            + Add product
          </button>
        )}

        <div className="grid-2 top-gap">
          <label className="field">
            <span>Surface prep (₹ / {system.unit})</span>
            <input type="number" step="0.01" min="0" value={settings.surface_prep_per_unit} onChange={setSetting("surface_prep_per_unit")} disabled={!canEdit} />
          </label>
          <label className="field">
            <span>Default margin %</span>
            <input type="number" step="0.01" min="0" value={settings.default_margin_percent} onChange={setSetting("default_margin_percent")} disabled={!canEdit} />
          </label>
          <label className="field">
            <span>Labour rate (₹)</span>
            <input type="number" step="0.01" min="0" value={settings.labour_rate} onChange={setSetting("labour_rate")} disabled={!canEdit} />
          </label>
          <label className="field">
            <span>Labour per</span>
            <select value={settings.labour_unit} onChange={setSetting("labour_unit")} disabled={!canEdit}>
              <option value="sqm">sqm</option>
              <option value="sqft">sqft</option>
            </select>
          </label>
        </div>
        {canEdit && (
          <div className="form-actions">
            <button className="btn btn-primary" disabled={!dirty} onClick={() => void save()}>
              Save system
            </button>
          </div>
        )}
      </div>

      <div className="card calculator">
        <h2 className="section-title">Rate calculator</h2>
        <label className="field">
          <span>Margin %</span>
          <input type="number" step="0.5" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
        </label>
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
      </div>
    </div>
  );
}
