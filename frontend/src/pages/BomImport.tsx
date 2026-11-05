// Import the company BOM (Settings > Products > Import BOM): the super admin and planning. The file
// is previewed first: the systems it makes or updates, each with its brand options (Bronco,
// Chryso) and their products, the names not in the product master (create them or leave their
// lines out) and the checks' warnings, which never block. Then the same file is imported.
import { useState } from "react";
import { api } from "../api";
import { errorText } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, Field, FilePicker } from "../ui/components";

type Component = {
  row: number;
  name: string;
  product: string | null;
  unit: string | null;
  consumption: string;
  original: { consumption: string; per: string } | null;
  wastage_included: boolean;
};
type Option = { brand: string; row: number; item: string; per: string; converted: boolean; components: Component[] };
type PlannedSystem = { name: string; unit: string; existing_id: number | null; options: Option[] };
type Warning = { kind: string; system: string; unit: string; brand: string | null; rows: number[]; message: string };
type Unmatched = { name: string; rows: number[]; unit: string | null; create_as: string; pack: { size: string; unit: string } | null; last_price: string | null; in_options: number };
type Preview = {
  counts: Record<string, number>;
  systems: PlannedSystem[];
  warnings: Warning[];
  unmatched: Unmatched[];
  brands: string[];
};
type Result = { counts: Record<string, number>; left_out: { name: string; rows: number[] }[] };

const KIND: Record<string, string> = {
  unit_gap: "sq ft against sqm",
  brand_ratio: "brands far apart",
  sheet_high: "sheet or mesh high",
  no_unit: "no unit",
  no_resin: "no resin",
  repeated: "product repeated",
  two_recipes: "two recipes",
  labour_skipped: "labour left out",
  no_products: "no products",
};
const PER: Record<string, string> = { sqft: "sq ft", sqm: "sqm", rft: "rft", rmt: "rmt", nos: "nos" };

export default function BomImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [create, setCreate] = useState<Set<string>>(new Set());
  const [brand, setBrand] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async <T,>(path: string, extra: Record<string, string> = {}): Promise<T | null> => {
    if (!file) return null;
    const form = new FormData();
    form.append("file", file);
    Object.entries(extra).forEach(([k, v]) => form.append(k, v));
    setBusy(true);
    setError(null);
    try {
      return await api<T>(path, { method: "POST", form });
    } catch (err) {
      setError(errorText(err));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const look = async () => {
    const p = await send<Preview>("/api/bom/preview");
    if (p) {
      setPreview(p);
      setCreate(new Set());
      setResult(null);
    }
  };
  const save = async () => {
    const r = await send<Result>("/api/bom/import", { create: JSON.stringify([...create]), ...(brand ? { default_brand: brand } : {}) });
    if (r) {
      setResult(r);
      onDone();
    }
  };
  const n = preview?.counts;

  return (
    <Modal title="Import the company BOM" onClose={onClose} wide>
      <p className="small muted">
        One sheet: a work item whose name ends with its unit (_SQFT, _SQMT, _RFT, _RMT), its products below in [ ] with the consumption per one unit and the product's unit. Each brand's
        recipe becomes a brand option of the work item's system; per sq ft and per rft are converted to per sqm and per rmt (× 10.7639, × 3.2808), the file's figure kept beside it.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-actions" style={{ justifyContent: "flex-start" }}>
        <FilePicker label="Choose the BOM file (.xlsx)" accept=".xlsx" onFiles={(files) => setFile(files[0] ?? null)} />
        <Button onClick={() => void look()} disabled={!file || busy}>
          {busy && !preview ? "Reading…" : "Preview"}
        </Button>
      </div>

      {preview && n && (
        <>
          <h3>What it writes</h3>
          <p>
            {n.work_items} work items, {n.product_rows} product rows, {n.products} products in the file → <b>{n.systems}</b> systems ({n.new_systems} new, {n.updated_systems} updated),{" "}
            <b>{n.options}</b> brand options, <b>{n.components}</b> components ({n.converted_options} options converted from sq ft or rft). {n.unmatched_products} products are not in
            the product master; {n.labour_rows_skipped ? `${n.labour_rows_skipped} labour rows left out; ` : ""}
            {n.no_unit} work items have no unit (read per nos).
          </p>

          <h3>Checks ({preview.warnings.length})</h3>
          <p className="small muted">Warnings only: the import goes ahead. Rows are the file's.</p>
          <div className="table-wrap" style={{ maxHeight: 260, overflow: "auto" }}>
            <table className="table">
              <tbody>
                {preview.warnings.map((w, i) => (
                  <tr key={i}>
                    <td>
                      <span className="badge badge-warn">{KIND[w.kind] ?? w.kind}</span>
                    </td>
                    <td className="small">{w.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Not in the product master ({preview.unmatched.length})</h3>
          <p className="small muted">Tick to create the product (the name without its pack, the file's name kept as an alias, the last purchase price when the file has it). A name not ticked leaves its lines out; its system is marked to confirm and says which.</p>
          {preview.unmatched.length > 0 && (
            <div className="table-wrap" style={{ maxHeight: 260, overflow: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        aria-label="Create all"
                        checked={create.size === preview.unmatched.length}
                        onChange={(e) => setCreate(e.target.checked ? new Set(preview.unmatched.map((u) => u.name)) : new Set())}
                      />
                    </th>
                    <th>In the file</th>
                    <th>Created as</th>
                    <th>Unit</th>
                    <th className="num">Last price</th>
                    <th>Rows</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.unmatched.map((u) => (
                    <tr key={u.name}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Create ${u.name}`}
                          checked={create.has(u.name)}
                          onChange={(e) => {
                            const next = new Set(create);
                            if (e.target.checked) next.add(u.name);
                            else next.delete(u.name);
                            setCreate(next);
                          }}
                        />
                      </td>
                      <td>{u.name}</td>
                      <td>
                        {u.create_as}
                        {u.pack ? <span className="muted small"> · pack {u.pack.size} {u.pack.unit}</span> : null}
                      </td>
                      <td>{u.unit ?? "nos"}</td>
                      <td className="num">{u.last_price ?? "—"}</td>
                      <td className="small muted">{u.rows.slice(0, 6).join(", ")}{u.rows.length > 6 ? "…" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Systems ({preview.systems.length})</h3>
          <div className="table-wrap" style={{ maxHeight: 320, overflow: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Work item</th>
                  <th>Per</th>
                  <th>Brand options</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {preview.systems.map((s) => {
                  const key = `${s.name}|${s.unit}`;
                  return (
                    <tr key={key}>
                      <td>
                        {s.name} {s.existing_id ? <span className="badge">updates</span> : <span className="badge badge-ok">new</span>}
                        {open === key &&
                          s.options.map((o) => (
                            <div key={o.brand} className="small" style={{ marginTop: 6 }}>
                              <b>{o.brand}</b> (row {o.row}{o.converted ? `, per ${PER[o.per]} converted` : ""}):{" "}
                              {o.components
                                .map(
                                  (c) =>
                                    `${c.product ?? `${c.name} (not in the master)`} ${c.consumption} ${c.unit ?? ""}/${s.unit}${c.original ? ` (${c.original.consumption} per ${PER[c.original.per]})` : ""}${c.wastage_included ? ", wastage included" : ""}`,
                                )
                                .join(" · ")}
                            </div>
                          ))}
                      </td>
                      <td>{s.unit}</td>
                      <td>{s.options.map((o, i) => (i === 0 ? `${o.brand} (default)` : o.brand)).join(", ")}</td>
                      <td>
                        <Button variant="ghost" onClick={() => setOpen(open === key ? null : key)}>
                          {open === key ? "Hide" : "Products"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="form-actions">
            <Field label="Default brand option (where the system has it; else the first in the file)" bare>
              <select value={brand} onChange={(e) => setBrand(e.target.value)} aria-label="Default brand">
                <option value="">The first brand in the file</option>
                {preview.brands.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </Field>
            <Button variant="primary" onClick={() => void save()} disabled={busy || !!result}>
              {busy ? "Importing…" : `Import ${n.systems} systems${create.size ? `, create ${create.size} products` : ""}`}
            </Button>
          </div>
        </>
      )}

      {result && (
        <div className="alert alert-ok">
          Imported: {result.counts.systems_created ?? 0} systems made, {result.counts.systems_updated ?? 0} updated, {result.counts.options ?? 0} brand options,{" "}
          {result.counts.components ?? 0} components, {result.counts.products_created ?? 0} products created.
          {result.left_out.length > 0 && (
            <> {result.counts.left_out_lines} lines left out (not in the product master): {result.left_out.map((x) => x.name).join(", ")}.</>
          )}
        </div>
      )}
    </Modal>
  );
}
