// Rate working, the master price list and labour paid back to back (the director's review, 12 Oct).
// The rate working groups the client's lines into main items and works each one per sqm the same
// way for everyone; costs, cushions and margins are for tender.margin only.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { LastPrice } from "../components/LastPrice";
import { NewBill, NewCard } from "./LabourForms";
import { errorText, inr, num } from "../format";
import { shortDate } from "../pages/Tenders";
import { GapNote, LibraryPicker } from "../knowledge/Picker";
import type { Gap } from "../knowledge/Picker";
import { Button, buttonClass, Card, Field } from "../ui/components";

type Line = { key: string; kind: string; id: number; item_no: string | null; description: string; unit: string | null; qty: string | null; rate: string | null };
type Product = {
  id: number;
  product_id: number;
  product: string;
  unit: string;
  consumption: string | null;
  default_consumption: string | null;
  consumption_changed: boolean;
  consumption_reason: string | null;
  consumption_source?: string | null;
  price: string | null;
  price_info: { id: number; rate: string; date: string; by: string | null; source: string } | null;
  freight_used: string;
  freight_actual: string | null;
};
type Row = { item: string; consumption?: string; coverage: string | null; price?: string; freight?: string; cost_of_material: string | null; per_sqm: string; ref: string | null };
type Group = {
  id: number;
  name: string;
  system_id: number | null;
  system: string | null;
  system_to_confirm: boolean;
  lines: Line[];
  unit_note: string[];
  rate_sqm: string | null;
  rate_sqft: string | null;
  errors: string[];
  library_flagged: boolean;
  library_diff_percent: string | null;
  library_median_sqm: string | null;
  coats: number | null;
  application: string | null;
  surface?: string | null;
  req_min_kg_sqm?: string | null;
  req_dft_mm?: string | null;
  // cost data (tender.margin)
  wastage_percent?: string;
  wastage_source?: string | null;
  applications?: { name: string; min: number; max: number }[];
  system_coats?: { product: string; coats: number | null; to_confirm: boolean }[];
  margin_basis?: "cost" | "selling";
  margin_basis_label?: string;
  surface_prep?: string;
  labour_rate_card_id?: number | null;
  labour_rate_card?: string | null;
  labour_used_sqft?: string;
  labour_paid_sqft?: string | null;
  margin_percent?: string;
  note?: string | null;
  products?: Product[];
  rows?: Row[];
  material_sqm?: string;
  cost_sqm?: string;
  margin_sqm?: string;
  cushions?: { what: string; used: string; actual: string; per_sqm: string }[];
  cushion_sqm?: string;
  library_limit_percent?: string;
};
type Working = {
  id: number;
  tender_id: number | null;
  quotation_id: number | null;
  rev_no: number;
  locked: boolean;
  can_edit: boolean;
  sees_cost: boolean;
  margin_basis: "cost" | "selling";
  margin_basis_label: string;
  margin_basis_note?: string | null;
  line_count: number;
  groups: Group[];
  ungrouped: Line[];
};
type SystemLite = { id: number; code: string; name: string };
type Card = { id: number; contractor: string; job: string; unit: string; rate: string; in_force: boolean };

export function RateWorkingView({ tenderId, quotationId }: { tenderId?: number; quotationId?: number }) {
  const [params, setParams] = useSearchParams();
  const [w, setW] = useState<Working | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const view = params.get("view") ?? "groups";
  const url = tenderId ? `/api/rate-working/tenders/${tenderId}` : `/api/rate-working/quotations/${quotationId}`;
  const load = useCallback(() => api<Working>(url).then(setW, (e) => setError(errorText(e))), [url]);
  useEffect(() => {
    void load();
  }, [load]);
  const go = (v: string) => {
    const next = new URLSearchParams(params);
    next.set("view", v);
    setParams(next, { replace: true });
  };
  async function suggest(fresh: boolean) {
    if (!w) return;
    if (fresh && !window.confirm("Group every line again? The main items and their workings are made afresh.")) return;
    try {
      setW(await api<Working>(`/api/rate-working/${w.id}/suggest${fresh ? "?fresh=true" : ""}`, { method: "POST" }));
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function apply() {
    if (!w) return;
    try {
      const r = await api<{ applied: number; skipped: { line: number; unit: string }[] }>(`/api/rate-working/${w.id}/apply`, { method: "POST" });
      setNotice(`${r.applied} client line(s) priced from the working${r.skipped.length ? `; ${r.skipped.length} in another unit left for you` : ""}.`);
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!w) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const current = w.groups.find((g) => String(g.id) === view);
  return (
    <div className="rate-working">
      <div className="card-head">
        <div>
          <h2 className="section-title">
            Rate working R{w.rev_no} {w.locked && <span className="badge badge-muted">submitted: kept as it was</span>}
          </h2>
          <p className="small muted">
            {w.line_count} client lines in {w.groups.length} main item(s)
            {w.ungrouped.length ? `, ${w.ungrouped.length} not grouped` : ""}. Cost = Σ consumption × (price + freight) × (1 + wastage) + surface preparation + labour (₹/sq ft ×
            10.7639); {w.margin_basis_label}.
          </p>
          {w.margin_basis_note && <p className="small text-warn">{w.margin_basis_note}.</p>}
          {w.can_edit && (
            <Field label="Margin for this working:" inline className="small">
              <select
                value={w.margin_basis}
                onChange={(e) =>
                  void api<Working>(`/api/rate-working/${w.id}/basis`, { method: "PUT", json: { margin_basis: e.target.value } }).then(setW, (err) => setError(errorText(err)))
                }
              >
                <option value="selling">on the selling price</option>
                <option value="cost">on cost</option>
              </select>
            </Field>
          )}
        </div>
        <div className="page-actions">
          {w.can_edit && (
            <>
              <Button size="small" onClick={() => void suggest(w.groups.length > 0)}>
                {w.groups.length ? "Group again" : "Suggest the groups"}
              </Button>
              {w.ungrouped.length > 0 && w.groups.length > 0 && (
                <Button size="small" onClick={() => void suggest(false)}>
                  Group the rest
                </Button>
              )}
              {tenderId && (
                <Link className={buttonClass({ size: "small" })} to={`/knowledge/match/tender/${tenderId}`}>
                  Match the client BOQ to the library
                </Link>
              )}
              <Button
                size="small"
                title="Its workings are added to the BOQ knowledge as new evidence (a won BOQ is added by itself)"
                onClick={() =>
                  void api<{ lines: number }>(`/api/knowledge/learn/workings/${w.id}`, { method: "POST" }).then(
                    (r) => setNotice(`Added to the library: ${r.lines} main item(s).`),
                    (e) => setError(errorText(e)),
                  )
                }
              >
                Mark final: add to the library
              </Button>
              <Button variant="primary" size="small" onClick={() => void apply()}>
                Rates to the lines
              </Button>
            </>
          )}
          {w.sees_cost && (
            <Button variant="ghost" size="small" onClick={() => void downloadFile(`/api/rate-working/${w.id}/export.xlsx`)}>
              Working sheet (Excel)
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      <div className="tabs tabs-inline">
        <button className={`tab ${view === "groups" ? "active" : ""}`} onClick={() => go("groups")}>
          Grouping
        </button>
        {w.groups.map((g) => (
          <button key={g.id} className={`tab ${view === String(g.id) ? "active" : ""}`} onClick={() => go(String(g.id))}>
            {g.name.length > 34 ? `${g.name.slice(0, 32)}…` : g.name} {g.rate_sqm ? <span className="muted small">{inr(g.rate_sqm)}</span> : ""}
          </button>
        ))}
      </div>
      <div className="top-gap">
        {view === "groups" || !current ? (
          <Grouping w={w} onChange={setW} onError={setError} />
        ) : (
          <MainItem key={current.id} w={w} g={current} onSaved={() => void load()} onError={setError} />
        )}
      </div>
    </div>
  );
}

function Grouping({ w, onChange, onError }: { w: Working; onChange: (w: Working) => void; onError: (e: string) => void }) {
  async function move(key: string, to: string) {
    const json =
      to === ""
        ? { line_key: key }
        : to === "new"
          ? { line_key: key, new_group_name: window.prompt("Name of the new main item") ?? "" }
          : { line_key: key, to_group_id: Number(to) };
    if ("new_group_name" in json && !json.new_group_name) return;
    try {
      onChange(await api<Working>(`/api/rate-working/${w.id}/move`, { method: "POST", json }));
    } catch (e) {
      onError(errorText(e));
    }
  }
  const columns: { id: number | null; name: string; rate: string | null; flagged: boolean; lines: Line[] }[] = [
    ...w.groups.map((g) => ({ id: g.id, name: g.name, rate: g.rate_sqm, flagged: g.library_flagged, lines: g.lines })),
    ...(w.ungrouped.length ? [{ id: null, name: "Not grouped", rate: null, flagged: false, lines: w.ungrouped }] : []),
  ];
  if (columns.length === 0) return <p className="empty">No client lines in this BOQ.</p>;
  return (
    <div className="group-board">
      {columns.map((c) => (
        <Card key={c.id ?? "none"} className={`group-col ${c.id === null ? "group-none" : ""}`}>
          <h3>
            {c.name} <span className="badge badge-muted">{c.lines.length}</span>
          </h3>
          {c.rate && (
            <p className="small">
              {inr(c.rate)} / sqm {c.flagged && <span className="badge badge-warn">off the rate library</span>}
            </p>
          )}
          <ul className="group-lines">
            {c.lines.map((ln) => (
              <li key={ln.key}>
                <span className="small">
                  <b>{ln.item_no}</b> {ln.description.length > 90 ? `${ln.description.slice(0, 88)}…` : ln.description}
                  <span className="muted">
                    {" "}
                    · {num(ln.qty, 2)} {ln.unit}
                  </span>
                </span>
                {w.can_edit && (
                  <Field label="Move to" bare>
                    <select value={c.id ?? ""} onChange={(e) => void move(ln.key, e.target.value)} aria-label="Move to">
                      {w.groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          → {g.name.slice(0, 40)}
                        </option>
                      ))}
                      <option value="new">→ a new main item…</option>
                      <option value="">→ not grouped</option>
                    </select>
                  </Field>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

type Form = {
  name: string;
  system_id: string;
  application: string;
  coats: string;
  wastage_percent: string;
  surface_prep: string;
  labour_rate_card_id: string;
  labour_used_sqft: string;
  labour_paid_sqft: string;
  margin_percent: string;
  products: {
    id: number | null;
    product_id: number;
    product: string;
    unit: string;
    consumption: string;
    default_consumption: string | null;
    consumption_reason: string;
    consumption_source: string | null;
    price: string;
    freight_used: string;
    freight_actual: string;
    price_info: Product["price_info"];
  }[];
};

const SURFACES: [string, string][] = [
  ["rcc", "RCC"],
  ["brick", "Brick"],
  ["plaster", "Plaster"],
  ["screed", "Screed"],
  ["old_tiles", "Old tiles"],
  ["metal", "Metal"],
];

function toForm(g: Group): Form {
  return {
    name: g.name,
    system_id: g.system_id ? String(g.system_id) : "",
    application: g.application ?? "",
    coats: g.coats ? String(g.coats) : "",
    wastage_percent: g.wastage_percent ?? "0",
    surface_prep: g.surface_prep ?? "0",
    labour_rate_card_id: g.labour_rate_card_id ? String(g.labour_rate_card_id) : "",
    labour_used_sqft: g.labour_used_sqft ?? "0",
    labour_paid_sqft: g.labour_paid_sqft ?? "",
    margin_percent: g.margin_percent ?? "0",
    products: (g.products ?? []).map((p) => ({
      id: p.id,
      product_id: p.product_id,
      product: p.product,
      unit: p.unit,
      consumption: p.consumption ?? "",
      default_consumption: p.default_consumption,
      consumption_reason: p.consumption_reason ?? "",
      consumption_source: p.consumption_source ?? null,
      price: p.price ?? "",
      freight_used: p.freight_used ?? "0",
      freight_actual: p.freight_actual ?? "",
      price_info: p.price_info,
    })),
  };
}

function MainItem({ w, g, onSaved, onError }: { w: Working; g: Group; onSaved: () => void; onError: (e: string) => void }) {
  const [f, setF] = useState<Form>(toForm(g));
  const [shown, setShown] = useState<Group>(g);
  const { can: canDo } = useAuth();
  const [picking, setPicking] = useState(false);
  const [gap, setGap] = useState<Gap | null>(null);
  const [fromLibrary, setFromLibrary] = useState<string | null>(null);
  useEffect(() => {
    if (!canDo("knowledge.view")) return;
    api<{ gap: Gap | null; template: { name: string } | null }>(`/api/knowledge/groups/${g.id}/gap`).then(
      (r) => {
        setGap(r.gap);
        setFromLibrary(r.template?.name ?? null);
      },
      () => undefined,
    );
  }, [g.id, shown.rate_sqm, canDo]);
  const [systems, setSystems] = useState<SystemLite[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [checks, setChecks] = useState<{ product: string; flagged: boolean; change_percent: string | null }[]>([]);
  const edit = w.can_edit;
  useEffect(() => {
    if (!edit) return;
    api<{ items: SystemLite[] }>("/api/systems?limit=200&active=true").then(
      (r) => setSystems(r.items),
      () => setSystems([]),
    );
    api<Card[]>("/api/labour/rate-cards").then(setCards, () => setCards([]));
  }, [edit]);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const setP = (i: number, patch: Partial<Form["products"][number]>) => setF({ ...f, products: f.products.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  async function save(systemChange = false, only?: Record<string, unknown>) {
    const opt = (v: string) => (v.trim() === "" ? null : v);
    const json = only
      ? only
      : systemChange
        ? { system_id: f.system_id ? Number(f.system_id) : null }
        : {
            name: f.name,
            application: opt(f.application),
            coats: f.coats ? Number(f.coats) : null,
            // sent only when typed here, so a picked application fills it from the settings
            ...(Number(f.wastage_percent) !== Number(shown.wastage_percent ?? 0) ? { wastage_percent: f.wastage_percent } : {}),
            surface_prep: f.surface_prep,
            labour_rate_card_id: f.labour_rate_card_id ? Number(f.labour_rate_card_id) : null,
            labour_used_sqft: f.labour_used_sqft,
            labour_paid_sqft: opt(f.labour_paid_sqft),
            margin_percent: f.margin_percent,
            products: f.products.map((p) => ({
              id: p.id,
              product_id: p.product_id,
              consumption: opt(p.consumption),
              consumption_reason: opt(p.consumption_reason),
              price: opt(p.price),
              freight_used: p.freight_used || "0",
              freight_actual: opt(p.freight_actual),
            })),
          };
    try {
      const out = await api<Group & { price_checks?: typeof checks }>(`/api/rate-working/groups/${g.id}`, { method: "PUT", json });
      setShown(out);
      setF(toForm(out));
      setChecks(out.price_checks ?? []);
      onSaved();
    } catch (e) {
      onError(errorText(e));
    }
  }
  if (!w.sees_cost)
    return (
      <Card as="div">
        <h3>{g.name}</h3>
        <p>
          {g.rate_sqm ? (
            <>
              <b>{inr(g.rate_sqm)}</b> per sqm · <b>{inr(g.rate_sqft)}</b> per sq ft
            </>
          ) : (
            <span className="muted">Not worked yet.</span>
          )}
          {g.system && <span className="muted"> · {g.system}</span>}
        </p>
        <LinesTable lines={g.lines} />
      </Card>
    );
  const s = shown;
  return (
    <div className="working-sheet">
      <Card as="div">
        <div className="grid-3">
          <Field label="Main item">
            <input value={f.name} onChange={set("name")} disabled={!edit} />
          </Field>
          <Field label="System">
            <select
              value={f.system_id}
              onChange={(e) => setF({ ...f, system_id: e.target.value })}
              onBlur={() => f.system_id !== String(s.system_id ?? "") && void save(true)}
              disabled={!edit}
            >
              <option value="">— choose —</option>
              {(systems.length ? systems : s.system_id ? [{ id: s.system_id, code: "", name: s.system ?? "" }] : []).map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
            {s.system_to_confirm && <span className="small text-warn">This system's consumption or coats are still to confirm.</span>}
          </Field>
          <Field label="Application (its wastage comes from the settings)">
            <select
              value={f.application}
              onChange={(e) => {
                setF({ ...f, application: e.target.value });
                void save(false, { application: e.target.value || null });
              }}
              disabled={!edit}
            >
              <option value="">— none —</option>
              {(s.applications ?? []).map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name} ({a.min}–{a.max} %)
                </option>
              ))}
              {f.application && !(s.applications ?? []).some((a) => a.name === f.application) && <option value={f.application}>{f.application}</option>}
            </select>
          </Field>
          <Field label="Surface (picks the consumption)">
            <select value={shown.surface ?? ""} onChange={(e) => void save(false, { surface: e.target.value || null })} disabled={!edit}>
              <option value="">— any —</option>
              {SURFACES.map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Client asks: min kg/sqm · DFT mm">
            <span className="inline-form">
              <input
                className="input-num"
                defaultValue={shown.req_min_kg_sqm ?? ""}
                key={`kg${shown.req_min_kg_sqm}`}
                onBlur={(e) => e.target.value !== (shown.req_min_kg_sqm ?? "") && void save(false, { req_min_kg_sqm: e.target.value || null })}
                disabled={!edit}
                aria-label="Minimum kg per sqm"
              />
              <input
                className="input-num"
                defaultValue={shown.req_dft_mm ?? ""}
                key={`dft${shown.req_dft_mm}`}
                onBlur={(e) => e.target.value !== (shown.req_dft_mm ?? "") && void save(false, { req_dft_mm: e.target.value || null })}
                disabled={!edit}
                aria-label="DFT in mm"
              />
            </span>
          </Field>
          <Field label="Wastage %">
            <input className="input-num" value={f.wastage_percent} onChange={set("wastage_percent")} disabled={!edit} />
            {s.wastage_source && <span className="small muted">from {s.wastage_source}</span>}
          </Field>
          <Field label="Coats">
            <input className="input-num" value={f.coats} onChange={set("coats")} disabled={!edit} />
            {(s.system_coats ?? []).length > 0 && (
              <span className="small muted">system: {(s.system_coats ?? []).map((c) => `${c.product} ${c.coats ? `${c.coats} coats` : "coats to confirm"}`).join("; ")}</span>
            )}
          </Field>
          <Field label="Surface preparation (₹/sqm)">
            <input className="input-num" value={f.surface_prep} onChange={set("surface_prep")} disabled={!edit} />
          </Field>
          <Field label="Labour rate card (what we pay)">
            <select value={f.labour_rate_card_id} onChange={set("labour_rate_card_id")} disabled={!edit}>
              <option value="">—</option>
              {(cards.length
                ? cards
                : s.labour_rate_card_id
                  ? [{ id: s.labour_rate_card_id, contractor: s.labour_rate_card ?? "", job: "", unit: "", rate: "", in_force: true }]
                  : []
              ).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.job ? `${c.contractor}: ${c.job} ${inr(c.rate)}/${c.unit}` : c.contractor}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Labour in the rate (₹/sq ft)">
            <input className="input-num" value={f.labour_used_sqft} onChange={set("labour_used_sqft")} disabled={!edit} />
          </Field>
          <Field label="Labour paid (₹/sq ft)">
            <input className="input-num" value={f.labour_paid_sqft} onChange={set("labour_paid_sqft")} disabled={!edit} />
          </Field>
          <Field label="Margin %">
            <input className="input-num" value={f.margin_percent} onChange={set("margin_percent")} disabled={!edit} />
          </Field>
        </div>
      </Card>
      <Card as="div" className="top-gap">
        <h3>Products (per sqm for this site)</h3>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Consumption</th>
                <th>Reason (when changed)</th>
                <th className="num">Price</th>
                <th className="num">Freight used</th>
                <th className="num">Freight actual</th>
              </tr>
            </thead>
            <tbody>
              {f.products.map((p, i) => {
                const changed = p.default_consumption !== null && p.consumption !== "" && Number(p.consumption) !== Number(p.default_consumption);
                return (
                  <tr key={p.id ?? `n${i}`}>
                    <td>
                      {p.product} <span className="muted small">/{p.unit}</span>
                    </td>
                    <td className="num">
                      <Field label="Consumption" bare>
                        <input className="input-num" value={p.consumption} placeholder="to confirm" onChange={(e) => setP(i, { consumption: e.target.value })} disabled={!edit} />
                      </Field>
                      <div className="small muted" title={p.consumption_source ?? undefined}>
                        {p.default_consumption === null ? "to confirm" : num(p.default_consumption)} from {p.consumption_source ?? "the system"}
                      </div>
                    </td>
                    <td>
                      {changed || p.consumption_reason ? (
                        <Field label="Reason (when changed)" bare>
                          <input value={p.consumption_reason} placeholder="Why, for this site?" onChange={(e) => setP(i, { consumption_reason: e.target.value })} disabled={!edit} />
                        </Field>
                      ) : (
                        <span className="muted small">as the system</span>
                      )}
                    </td>
                    <td className="num">
                      <Field label="Price" bare>
                        <input className="input-num" value={p.price} onChange={(e) => setP(i, { price: e.target.value })} disabled={!edit} />
                      </Field>
                      <div>
                        <LastPrice productId={p.product_id} rate={p.price} excludeId={p.price_info?.id} />
                      </div>
                    </td>
                    <td className="num">
                      <Field label="Freight used" bare>
                        <input className="input-num" value={p.freight_used} onChange={(e) => setP(i, { freight_used: e.target.value })} disabled={!edit} />
                      </Field>
                    </td>
                    <td className="num">
                      <Field label="Freight actual" bare>
                        <input className="input-num" value={p.freight_actual} placeholder="—" onChange={(e) => setP(i, { freight_actual: e.target.value })} disabled={!edit} />
                      </Field>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {checks
          .filter((c) => c.flagged)
          .map((c) => (
            <div key={c.product} className="alert alert-warn">
              {c.product}: the price changes the last one used by {c.change_percent} %.
            </div>
          ))}
        {edit && (
          <Button variant="primary" className="top-gap" onClick={() => void save()}>
            Work the rate
          </Button>
        )}
      </Card>
      <div className="split top-gap">
        <Card as="div">
          <h3>Build-up per sqm</h3>
          {s.errors.length > 0 ? (
            <div className="alert alert-warn">{s.errors.join("; ")}</div>
          ) : (
            <table className="table compact working-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="num">Coverage</th>
                  <th className="num">Cost of material</th>
                  <th className="num">Per sqm</th>
                  <th>Ref</th>
                </tr>
              </thead>
              <tbody>
                {(s.rows ?? []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.item}</td>
                    <td className="num">{r.coverage ? num(r.coverage) : "1"}</td>
                    <td className="num">{r.cost_of_material ? inr(r.cost_of_material) : "—"}</td>
                    <td className="num">{inr(r.per_sqm)}</td>
                    <td className="small muted">{r.ref}</td>
                  </tr>
                ))}
                <tr className="row-total">
                  <td>Cost to company (CTC)</td>
                  <td />
                  <td />
                  <td className="num">{inr(s.cost_sqm)}</td>
                  <td />
                </tr>
                <tr>
                  <td>
                    Margin {num(s.margin_percent)} % {s.margin_basis === "selling" ? "on the selling price" : "on cost"}
                    <div className="small muted">{s.margin_basis_label}</div>
                  </td>
                  <td />
                  <td />
                  <td className="num">{inr(s.margin_sqm)}</td>
                  <td />
                </tr>
                <tr className="row-total">
                  <td>
                    <b>Rate</b>
                  </td>
                  <td />
                  <td />
                  <td className="num">
                    <b>{inr(s.rate_sqm)}</b> / sqm
                  </td>
                  <td>
                    <b>{inr(s.rate_sqft)}</b> / sq ft
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </Card>
        <div>
          <Card as="div">
            <h3>Cushions (visible, not hidden)</h3>
            {(s.cushions ?? []).length === 0 ? (
              <p className="small muted">Enter what the gang is paid and the actual freight to see them.</p>
            ) : (
              <table className="table compact">
                <tbody>
                  {(s.cushions ?? []).map((c) => (
                    <tr key={c.what}>
                      <td>{c.what}</td>
                      <td className="small">
                        used {inr(c.used)} · actual {inr(c.actual)}
                      </td>
                      <td className="num">{inr(c.per_sqm)} / sqm</td>
                    </tr>
                  ))}
                  <tr className="row-total">
                    <td>Total</td>
                    <td />
                    <td className="num">{inr(s.cushion_sqm)} / sqm</td>
                  </tr>
                </tbody>
              </table>
            )}
          </Card>
          {canDo("knowledge.view") && (
            <Card as="div" className={`top-gap ${gap?.flagged ? "card-warn" : ""}`}>
              <h3>Against what we sold at before</h3>
              {fromLibrary && <p className="small muted">From the library: {fromLibrary}</p>}
              {gap ? <GapNote gap={gap} /> : <p className="small muted">Not from the library yet.</p>}
              {edit && (
                <Button size="small" onClick={() => setPicking(true)}>
                  {fromLibrary ? "Pick another template…" : "New main item from the library…"}
                </Button>
              )}
            </Card>
          )}
          {picking && (
            <LibraryPicker
              groupId={g.id}
              onClose={() => setPicking(false)}
              onApplied={(gp, name) => {
                setPicking(false);
                setGap(gp);
                setFromLibrary(name);
                onSaved();
              }}
            />
          )}
          <Card as="div" className={`top-gap ${s.library_flagged ? "card-warn" : ""}`}>
            <h3>Against the rate library</h3>
            {s.library_median_sqm ? (
              <p>
                Median {inr(s.library_median_sqm)} / sqm: this rate is {Number(s.library_diff_percent) > 0 ? "+" : ""}
                {s.library_diff_percent} %{s.library_flagged && <b> (more than {num(s.library_limit_percent)} % off: check it)</b>}
              </p>
            ) : (
              <p className="small muted">No rate library match for these lines.</p>
            )}
          </Card>
        </div>
      </div>
      <Card as="div" className="top-gap">
        <h3>The client's lines in this main item ({s.lines.length})</h3>
        {s.unit_note.length > 0 && <p className="small text-warn">Lines in {s.unit_note.join(", ")} are left for you (the working is per sqm and sq ft).</p>}
        <LinesTable lines={s.lines} />
      </Card>
    </div>
  );
}

function LinesTable({ lines }: { lines: Line[] }) {
  return (
    <table className="table compact">
      <thead>
        <tr>
          <th>Item</th>
          <th>Description</th>
          <th className="num">Qty</th>
          <th>Unit</th>
          <th className="num">Rate</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((ln) => (
          <tr key={ln.key}>
            <td>{ln.item_no}</td>
            <td className="small">{ln.description.length > 120 ? `${ln.description.slice(0, 118)}…` : ln.description}</td>
            <td className="num">{num(ln.qty, 2)}</td>
            <td>{ln.unit}</td>
            <td className="num">{ln.rate ? inr(ln.rate) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function QuotationWorking() {
  const { id } = useParams();
  return (
    <>
      <p className="breadcrumb">
        <Link to="/quotations">Quotations</Link> / <Link to={`/quotations/${id}`}>#{id}</Link> / Rate working
      </p>
      <RateWorkingView quotationId={Number(id)} />
    </>
  );
}

// --- the master price list ------------------------------------------------------------------------

type PriceRow = {
  id: number;
  rate: string;
  unit: string | null;
  freight_per_unit: string;
  date: string;
  source: string;
  ref: string | null;
  vendor: string | null;
  by: string | null;
  note: string | null;
  change_percent: string | null;
  flagged: boolean;
};
type PricePage = {
  product: { id: number; code: string; name: string; unit: string; brand: string | null };
  current: PriceRow | null;
  freight_current: { per_unit: string; date: string; vendor: string | null; store: string | null; by: string | null } | null;
  history: PriceRow[];
  freight: { id: number; per_unit: string; date: string; vendor: string | null; store: string | null; by: string | null; note: string | null }[];
  limit_percent: string;
};
const SOURCES: Record<string, string> = { vendor_quote: "Vendor quote", rate_contract: "Rate contract", po: "PO", manual: "Entered" };

export function ProductPrices() {
  const { id } = useParams();
  const { can } = useAuth();
  const [p, setP] = useState<PricePage | null>(null);
  const [error, setError] = useState("");
  const [rate, setRate] = useState("");
  const [source, setSource] = useState("vendor_quote");
  const [ref, setRef] = useState("");
  const [freight, setFreight] = useState("");
  const load = useCallback(() => api<PricePage>(`/api/prices/products/${id}`).then(setP, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function add() {
    try {
      await api(`/api/prices/products/${id}`, { method: "POST", json: { rate, source, ref: ref || null } });
      setRate("");
      setRef("");
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function addFreight() {
    try {
      await api(`/api/prices/products/${id}/freight`, { method: "POST", json: { per_unit: freight } });
      setFreight("");
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!p) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const canAdd = can("library.edit") && can("tender.margin");
  return (
    <>
      <p className="breadcrumb">
        <Link to="/products">Products</Link> / <code>{p.product.code}</code> / Prices
      </p>
      <div className="page-header">
        <div>
          <h1>{p.product.name}</h1>
          <p className="muted">
            {p.product.brand} · per {p.product.unit}. A change of more than {num(p.limit_percent)} % against the last price used is flagged.
          </p>
        </div>
        <div className="rate-badge">
          <span className="muted small">Current price</span>
          <strong>{p.current ? inr(p.current.rate) : "—"}</strong>
          <span className="muted small">{p.current ? `${shortDate(p.current.date)} · ${p.current.by ?? ""}` : "none yet"}</span>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="split">
        <Card as="div">
          <h2 className="section-title">Price history</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">Price</th>
                <th className="num">Change</th>
                <th>Source</th>
                <th>Entered by</th>
              </tr>
            </thead>
            <tbody>
              {p.history.map((h) => (
                <tr key={h.id} className={h.flagged ? "row-warn" : ""}>
                  <td>{shortDate(h.date)}</td>
                  <td className="num">
                    {inr(h.rate)}
                    <span className="muted small">/{h.unit ?? p.product.unit}</span>
                  </td>
                  <td className={`num ${h.flagged ? "text-danger" : ""}`}>{h.change_percent === null ? "—" : `${Number(h.change_percent) > 0 ? "+" : ""}${h.change_percent} %`}</td>
                  <td className="small">
                    {SOURCES[h.source] ?? h.source} {h.ref}
                    {h.vendor && <div className="muted">{h.vendor}</div>}
                  </td>
                  <td className="small">{h.by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {canAdd && (
            <div className="form-row top-gap">
              <Field label="New price">
                <input className="input-num" value={rate} onChange={(e) => setRate(e.target.value)} />
              </Field>
              <Field label="Source">
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  {Object.entries(SOURCES).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Reference">
                <input value={ref} onChange={(e) => setRef(e.target.value)} />
              </Field>
              <Button variant="primary" disabled={!rate} onClick={() => void add()}>
                Add
              </Button>
              <div className="full">
                <LastPrice productId={p.product.id} rate={rate} />
              </div>
            </div>
          )}
        </Card>
        <Card as="div">
          <h2 className="section-title">Freight per {p.product.unit}</h2>
          <p className="small muted">Per product, or per vendor and godown (the most specific one in force is used).</p>
          <table className="table compact">
            <thead>
              <tr>
                <th>From</th>
                <th className="num">Per unit</th>
                <th>Vendor / godown</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {p.freight.map((f) => (
                <tr key={f.id}>
                  <td>{shortDate(f.date)}</td>
                  <td className="num">{inr(f.per_unit)}</td>
                  <td className="small">{[f.vendor, f.store].filter(Boolean).join(" · ") || "any"}</td>
                  <td className="small">{f.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {canAdd && (
            <div className="form-row top-gap">
              <Field label="Freight per unit">
                <input className="input-num" value={freight} onChange={(e) => setFreight(e.target.value)} />
              </Field>
              <Button disabled={!freight} onClick={() => void addFreight()}>
                Add freight
              </Button>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

// --- labour rate cards and back-to-back bills ------------------------------------------------------

type RateCard = {
  id: number;
  contractor_id: number;
  contractor: string;
  job: string;
  covers: string | null;
  unit: string;
  rate: string;
  rate_max: string | null;
  valid_from: string;
  valid_to: string | null;
  in_force: boolean;
};
type Bill = {
  id: number;
  number: string;
  kind: "piece" | "attendance";
  contractor: string;
  period_from: string;
  period_to: string;
  bill_date: string;
  gross: string;
  tds_section: string | null;
  tds_percent: string;
  tds: string;
  tds_note: string | null;
  net: string;
  status: string;
  made_by: string | null;
  approved_by: string | null;
  lines: { id: number; site: string; description: string; basis: string; qty: string; unit: string; rate: string; amount: string }[];
};
const BASIS: Record<string, string> = { billed: "billed to the client", certified: "certified by the client (less than billed)", hours: "hours from attendance" };

export function LabourRates() {
  const { can } = useAuth();
  const [cards, setCards] = useState<RateCard[]>([]);
  const [bills, setBills] = useState<Bill[]>([]);
  const [error, setError] = useState("");
  const [params] = useSearchParams();
  const [open, setOpen] = useState<number | null>(params.get("bill") ? Number(params.get("bill")) : null);
  const load = useCallback(() => {
    api<RateCard[]>("/api/labour/rate-cards").then(setCards, (e) => setError(errorText(e)));
    if (can("payables.view")) api<Bill[]>("/api/labour/bills").then(setBills, () => setBills([]));
  }, [can]);
  useEffect(() => {
    load();
  }, [load]);
  const byContractor = useMemo(() => {
    const m = new Map<string, RateCard[]>();
    for (const c of cards) m.set(c.contractor, [...(m.get(c.contractor) ?? []), c]);
    return [...m.entries()];
  }, [cards]);
  async function approve(b: Bill) {
    try {
      await api(`/api/labour/bills/${b.id}/approve`, { method: "POST" });
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  const shownBill = bills.find((b) => b.id === open);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Labour rates and bills</h1>
          <p className="muted">
            Labour is paid back to back with what we bill the client: a piece-rate bill takes its quantity from the measurement book (billed, or certified when the client certified
            less); a gang on attendance is billed by its hours on each site.
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {(can("subcon.edit") || can("payables.edit")) && (
        <div className="split">
          {can("subcon.edit") && <NewCard onDone={load} onError={setError} />}
          {can("payables.edit") && <NewBill cards={cards} onDone={(id) => (load(), setOpen(id))} onError={setError} />}
        </div>
      )}
      <Card as="div" className="top-gap">
        <h2 className="section-title">Rate cards</h2>
        {byContractor.length === 0 && <p className="empty">No rate cards yet.</p>}
        {byContractor.map(([name, list]) => (
          <div key={name} className="top-gap-small">
            <h3>{name}</h3>
            <table className="table compact">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Covers</th>
                  <th className="num">Rate</th>
                  <th>Valid</th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className={c.in_force ? "" : "muted"}>
                    <td>
                      <b>{c.job}</b>
                    </td>
                    <td className="small">{c.covers}</td>
                    <td className="num">
                      {inr(c.rate)}
                      {c.rate_max ? ` to ${inr(c.rate_max)}` : ""} / {c.unit}
                    </td>
                    <td className="small">
                      {shortDate(c.valid_from)} to {c.valid_to ? shortDate(c.valid_to) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </Card>
      {can("payables.view") && (
        <Card as="div" className="top-gap">
          <h2 className="section-title">Labour bills</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>Bill</th>
                <th>Contractor</th>
                <th>Kind</th>
                <th>Period</th>
                <th className="num">Gross</th>
                <th className="num">TDS</th>
                <th className="num">Net</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr key={b.id} className={open === b.id ? "row-selected" : ""} onClick={() => setOpen(b.id)}>
                  <td>
                    <button className="link-button">{b.number}</button>
                  </td>
                  <td>{b.contractor}</td>
                  <td>{b.kind === "piece" ? "piece rate" : "attendance"}</td>
                  <td className="small">
                    {shortDate(b.period_from)} to {shortDate(b.period_to)}
                  </td>
                  <td className="num">{inr(b.gross)}</td>
                  <td className="num">{inr(b.tds)}</td>
                  <td className="num">{inr(b.net)}</td>
                  <td>
                    <span className={`badge ${b.status === "approved" ? "badge-ok" : "badge-muted"}`}>{b.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {shownBill && (
        <Card
          as="div"
          className="top-gap"
          title={
            <>
              {shownBill.number}: {shownBill.contractor}
            </>
          }
          actions={
            shownBill.status === "draft" &&
            can("payables.edit") && (
              <Button variant="primary" size="small" onClick={() => void approve(shownBill)}>
                Approve (vendor bill)
              </Button>
            )
          }
        >
          <table className="table compact">
            <thead>
              <tr>
                <th>Site</th>
                <th>Item and job</th>
                <th>Quantity from</th>
                <th className="num">Qty</th>
                <th className="num">Rate</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {shownBill.lines.map((ln) => (
                <tr key={ln.id}>
                  <td>{ln.site}</td>
                  <td className="small">{ln.description}</td>
                  <td className="small">{BASIS[ln.basis] ?? ln.basis}</td>
                  <td className="num">
                    {num(ln.qty, 3)} {ln.unit}
                  </td>
                  <td className="num">{inr(ln.rate)}</td>
                  <td className="num">{inr(ln.amount)}</td>
                </tr>
              ))}
              <tr className="row-total">
                <td colSpan={5}>Gross</td>
                <td className="num">{inr(shownBill.gross)}</td>
              </tr>
              <tr>
                <td colSpan={5}>
                  TDS {shownBill.tds_section ?? ""} {num(shownBill.tds_percent)} %{shownBill.tds_note ? ` (${shownBill.tds_note})` : ""}
                </td>
                <td className="num">− {inr(shownBill.tds)}</td>
              </tr>
              <tr className="row-total">
                <td colSpan={5}>
                  <b>Net payable</b>
                </td>
                <td className="num">
                  <b>{inr(shownBill.net)}</b>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="small muted">
            Made by {shownBill.made_by}
            {shownBill.approved_by ? `, approved by ${shownBill.approved_by}` : ""}. No labour quantity is typed: it comes from the client bills (or attendance).
          </p>
        </Card>
      )}
    </>
  );
}

// --- the site budget: labour per sqm against the rate working ---------------------------------------

export function LabourPerSqm({ siteId }: { siteId: number }) {
  const [d, setD] = useState<{ labour_cost: string; area_sqm: string; per_sqm: string | null; working_per_sqm: string | null; over: boolean } | null>(null);
  useEffect(() => {
    api<typeof d>(`/api/labour/sites/${siteId}/labour-cost`).then(setD, () => setD(null));
  }, [siteId]);
  if (!d) return null;
  return (
    <Card as="div" className={d.over ? "card-warn" : ""}>
      <h2 className="section-title">Labour cost per sqm</h2>
      <p>
        {d.per_sqm ? <b>{inr(d.per_sqm)}</b> : "—"} per sqm paid ({inr(d.labour_cost)} over {num(d.area_sqm, 2)} sqm billed) against{" "}
        {d.working_per_sqm ? <b>{inr(d.working_per_sqm)}</b> : "—"} in the rate working's labour line
        {d.over && <span className="badge badge-warn"> over the working</span>}
      </p>
    </Card>
  );
}

// --- Settings: the flags ---------------------------------------------------------------------------

export function CostingSettingsCard() {
  const [s, setS] = useState<Record<string, string> | null>(null);
  const [saved, setSaved] = useState("");
  useEffect(() => {
    api<Record<string, string>>("/api/prices/settings").then(setS, () => setS(null));
  }, []);
  if (!s) return null;
  const fields: [string, string][] = [
    ["price_change_flag_percent", "Flag a price change of more than (%)"],
    ["library_diff_flag_percent", "Flag a worked rate off the rate library by more than (%)"],
    ["calloff_tolerance_percent", "A call-off past the plan's balance plus (%) needs planning"],
    ["day_hours", "A gang's standard day (hours)"],
  ];
  async function save() {
    try {
      setS(await api<Record<string, string>>("/api/prices/settings", { method: "PUT", json: s }));
      setSaved("Saved (logged).");
    } catch (e) {
      setSaved(errorText(e));
    }
  }
  return (
    <Card as="div" className="top-gap">
      <h2 className="section-title">Prices, rate working and lots</h2>
      <div className="grid-2">
        <Field label="Margin in new rate workings (a saved working keeps its own)">
          <select value={String(s.margin_basis ?? "selling")} onChange={(e) => setS({ ...s, margin_basis: e.target.value })}>
            <option value="cost">on cost: rate = cost × (1 + margin)</option>
            <option value="selling">on the selling price: rate = cost ÷ (1 − margin)</option>
          </select>
        </Field>
        {fields.map(([k, label]) => (
          <Field label={label} key={k}>
            <input className="input-num" value={String(s[k] ?? "")} onChange={(e) => setS({ ...s, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <Button size="small" className="top-gap" onClick={() => void save()}>
        Save
      </Button>
      {saved && <span className="small muted"> {saved}</span>}
    </Card>
  );
}
