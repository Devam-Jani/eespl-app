import { useEffect, useState } from "react";
import { api } from "../api";
import { Modal } from "../ui/Overlay";
import { errorText, inr } from "../format";

export type Stats = { n: number; min: string; median: string; max: string; latest: { rate: string; on_date: string | null; city: string | null } } | null;
export type Brief = {
  id: number;
  name: string;
  area_type: string | null;
  area_label: string | null;
  surface: string | null;
  coats: number | null;
  min_kg_sqm: string | null;
  dft_mm: string | null;
  families: string[];
  unit: string | null;
  description: string;
  steps: string[];
  steps_source: string | null;
  lines: number;
  boqs: number;
  median_rate: string | null;
  latest_on: string | null;
  hidden: boolean;
  reviewed: boolean;
  to_check: boolean;
};
export type ProductRow = {
  label: string;
  product_id: number | null;
  boqs: number;
  consumption: string | null;
  consumption_from: string | null;
  consumption_by_surface: Record<string, { n: number; median: string }>;
  price_median: string | null;
  freight_median: string | null;
  freight_near: string | null;
};
export type Proposal = Brief & {
  why?: string[];
  workings?: number;
  score: number;
  confidence: number;
  rates: { city: string | null; region: string | null; city_stats: Stats; region_stats: Stats; all_stats: Stats; unit: string | null };
  products?: { products: ProductRow[]; labour_sqft: string | null; surface_prep_sqm: string | null; workings: number };
  margins?: { all: { n: number; min: number; median: number; max: number } | null; usual?: string };
};
export type Options = { areas: { key: string; label: string }[]; surfaces: { key: string; label: string }[]; brands: string[] };
export type Gap = { median: string | null; where: string; rate: string | null; diff_percent: string | null; flagged: boolean; reasons: string[]; limit: string };

export function NearRates({ r }: { r: Proposal["rates"] }) {
  const row = (label: string, s: Stats) =>
    s ? (
      <tr>
        <td>{label}</td>
        <td className="num">{inr(s.min)}</td>
        <td className="num">
          <b>{inr(s.median)}</b>
        </td>
        <td className="num">
          {inr(s.latest.rate)} <span className="small muted">{s.latest.on_date ?? ""}</span>
        </td>
        <td className="num small muted">{s.n}</td>
      </tr>
    ) : (
      <tr>
        <td>{label}</td>
        <td colSpan={4} className="muted small">
          none
        </td>
      </tr>
    );
  return (
    <table className="table compact">
      <thead>
        <tr>
          <th>Past rates (per {r.unit ?? "sqm"})</th>
          <th className="num">Min</th>
          <th className="num">Median</th>
          <th className="num">Latest</th>
          <th className="num">Lines</th>
        </tr>
      </thead>
      <tbody>
        {r.city && row(`In ${r.city}`, r.city_stats)}
        {r.region && row(`In the ${r.region} region`, r.region_stats)}
        {row("All", r.all_stats)}
      </tbody>
    </table>
  );
}

export function GapNote({ gap }: { gap: Gap | null }) {
  if (!gap || gap.median === null) return <p className="small muted">No past rate for this template to compare with.</p>;
  return (
    <div className={gap.flagged ? "alert alert-warn" : "small"}>
      Worked rate {inr(gap.rate)} against the median we sold at {gap.where}, {inr(gap.median)}: {Number(gap.diff_percent) > 0 ? "+" : ""}
      {gap.diff_percent} %{gap.flagged && <b> (more than {Number(gap.limit)} % apart)</b>}
      {gap.reasons.length > 0 && (
        <ul className="small">
          {gap.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "New main item from the library": the area, the surface, what the client asks and the place;
 * the templates that fit, best first; choosing one fills the main item's rate working. */
export function LibraryPicker({ groupId, onApplied, onClose }: { groupId: number; onApplied: (gap: Gap, name: string) => void; onClose: () => void }) {
  const [opts, setOpts] = useState<Options | null>(null);
  const [f, setF] = useState({ area_type: "", surface: "", coats: "", min_kg_sqm: "", dft_mm: "", protection: "", warranty_years: "", brand: "", city: "" });
  const [found, setFound] = useState<Proposal[] | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<Options>("/api/knowledge/options").then(setOpts, (e) => setError(errorText(e)));
    api<Record<string, string | number | null>>(`/api/knowledge/groups/${groupId}/context`).then(
      (c) =>
        setF((x) => ({
          ...x,
          area_type: String(c.area_type ?? ""),
          surface: String(c.surface ?? ""),
          coats: c.coats ? String(c.coats) : "",
          min_kg_sqm: c.min_kg_sqm ? String(c.min_kg_sqm) : "",
          dft_mm: c.dft_mm ? String(c.dft_mm) : "",
          city: String(c.city ?? ""),
        })),
      () => undefined,
    );
  }, [groupId]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const nz = (v: string) => (v.trim() === "" ? null : v);
  async function search() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ templates: Proposal[]; region: string | null }>("/api/knowledge/propose", {
        method: "POST",
        json: {
          area_type: nz(f.area_type),
          surface: nz(f.surface),
          coats: f.coats ? Number(f.coats) : null,
          min_kg_sqm: nz(f.min_kg_sqm),
          dft_mm: nz(f.dft_mm),
          protection: nz(f.protection),
          warranty_years: f.warranty_years ? Number(f.warranty_years) : null,
          brand: nz(f.brand),
          city: nz(f.city),
        },
      });
      setFound(r.templates);
      setRegion(r.region);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function use(t: Proposal) {
    setBusy(true);
    try {
      const r = await api<{ gap: Gap }>(`/api/knowledge/groups/${groupId}/apply`, {
        method: "POST",
        json: { template_id: t.id, city: nz(f.city), surface: nz(f.surface), coats: f.coats ? Number(f.coats) : null, min_kg_sqm: nz(f.min_kg_sqm), dft_mm: nz(f.dft_mm) },
      });
      onApplied(r.gap, t.name);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="New main item from the library" onClose={onClose} wide>
      <div className="library-picker">
        <div className="grid-4">
          <label className="field">
            <span>Area</span>
            <select value={f.area_type} onChange={set("area_type")}>
              <option value="">— any —</option>
              {opts?.areas.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Surface</span>
            <select value={f.surface} onChange={set("surface")}>
              <option value="">— any —</option>
              {opts?.surfaces.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Coats</span>
            <input className="input-num" value={f.coats} onChange={set("coats")} />
          </label>
          <label className="field">
            <span>Min kg/sqm</span>
            <input className="input-num" value={f.min_kg_sqm} onChange={set("min_kg_sqm")} />
          </label>
          <label className="field">
            <span>DFT mm</span>
            <input className="input-num" value={f.dft_mm} onChange={set("dft_mm")} />
          </label>
          <label className="field">
            <span>Protection</span>
            <select value={f.protection} onChange={set("protection")}>
              <option value="">— none —</option>
              <option value="screed">Screed</option>
              <option value="tile">Tile</option>
              <option value="board">Board / geotextile</option>
            </select>
          </label>
          <label className="field">
            <span>Warranty (years)</span>
            <input className="input-num" value={f.warranty_years} onChange={set("warranty_years")} />
          </label>
          <label className="field">
            <span>Brand asked</span>
            <select value={f.brand} onChange={set("brand")}>
              <option value="">— any —</option>
              {opts?.brands.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Site location</span>
            <input value={f.city} onChange={set("city")} placeholder="Ahmedabad" />
          </label>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={() => void search()}>
          Propose templates
        </button>
        {error && <div className="alert alert-error top-gap-small">{error}</div>}
        {found && (
          <div className="top-gap">
            <p className="small muted">
              {found.length} template(s) fit{region ? `; ${f.city} is in ${region}` : ""}. Best first.
            </p>
            {found.map((t) => (
              <div key={t.id} className="card library-proposal">
                <div className="card-head">
                  <div>
                    <b>{t.name}</b> <span className="badge badge-muted">{t.confidence} %</span> {t.to_check && <span className="badge badge-warn">to check</span>}
                    <div className="small muted">
                      {t.boqs} BOQ(s), {t.lines} line(s)
                      {t.margins?.usual ? ` · margin ${t.margins.usual}` : ""}
                    </div>
                  </div>
                  <button className="btn btn-primary btn-small" disabled={busy} onClick={() => void use(t)}>
                    Use this
                  </button>
                </div>
                {t.why && <p className="small muted">Why here: {t.why.join(" · ")}</p>}
                <p className="small">
                  {t.description.slice(0, 420)}
                  {t.description.length > 420 ? "…" : ""}
                </p>
                <div className="grid-2">
                  <div>
                    {t.products && t.products.products.length > 0 ? (
                      <table className="table compact">
                        <thead>
                          <tr>
                            <th>Product (most used first)</th>
                            <th className="num">Consumption</th>
                            <th className="num">BOQs</th>
                          </tr>
                        </thead>
                        <tbody>
                          {t.products.products.slice(0, 6).map((p) => (
                            <tr key={p.label}>
                              <td>
                                {p.label} {!p.product_id && <span className="small text-warn">(not in the product master)</span>}
                              </td>
                              <td className="num" title={p.consumption_from ?? ""}>
                                {p.consumption ?? "—"}
                              </td>
                              <td className="num">{p.boqs}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p className="small muted">{t.products ? "No working build-up in these BOQs." : ""}</p>
                    )}
                    {t.steps.length > 0 && (
                      <p className="small">
                        <b>Steps:</b> {t.steps.join(" › ")}
                      </p>
                    )}
                  </div>
                  <NearRates r={t.rates} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
