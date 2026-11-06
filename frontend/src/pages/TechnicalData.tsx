// Settings > Products > Technical data (Prompt 39a): every product data sheet (TDS) kept, with the
// facts read from it (chemistry, uses, consumption per sqm or rmt, coats, DFT, pack, primer, UV,
// potable, property values with their standard), each with its page and sentence. Importing a
// folder (super admin, planning) previews first: brand from the folder, matched to the product
// master or a new product, scanned sheets "needs reading", duplicates merged; then Save.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, num } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, Card, Field, buttonClass } from "../ui/components";

type Fact = {
  id: number;
  kind: string;
  key: string | null;
  lo: string | null;
  hi: string | null;
  unit: string | null;
  text: string | null;
  standard: string | null;
  page: number | null;
  sentence: string | null;
  per_coat: boolean;
  coats: number | null;
  source: "rule" | "ai" | "manual";
  checked_at: string | null;
  checked_by_name?: string | null;
  original?: Record<string, unknown> | null;
};
type Doc = {
  id: number;
  import_id: number | null;
  brand: string | null;
  product_name: string;
  file_name: string;
  rel_path: string | null;
  status: string;
  needs_reading: boolean;
  read_error: string | null;
  product_id: number | null;
  product: string | null;
  match: "matched" | "create" | "skip";
  duplicate_of_id: number | null;
  replaces_id: number | null;
  imported_at: string;
  fact_count: number;
  kinds: string[];
  facts?: Fact[];
  ai_enabled?: boolean;
};
type List = { docs: Doc[]; brands: string[]; ai_enabled: boolean; open_import_id: number | null };
type Counts = Record<string, number | Record<string, number>>;
type ImportView = { id: number; status: string; counts: Counts; docs: Doc[] };

const KINDS = ["chemistry", "use", "consumption", "coats", "dft", "thickness", "pack", "density", "solids", "primer", "uv", "potable", "property"];
const BATCH = 8;

function value(f: Pick<Fact, "lo" | "hi" | "unit" | "key" | "text">): string {
  if (f.lo === null) return f.key ?? f.text ?? "";
  const lo = num(f.lo, 4);
  const hi = f.hi !== null && f.hi !== f.lo ? `–${num(f.hi, 4)}` : "";
  return `${lo}${hi} ${f.unit ?? ""}`.trim();
}

function FactRow({ f, canEdit, onChange }: { f: Fact; canEdit: boolean; onChange: () => void }) {
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState({ key: f.key ?? "", lo: f.lo ?? "", hi: f.hi ?? "", unit: f.unit ?? "", standard: f.standard ?? "" });
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await api(`/api/spec/tds/facts/${f.id}`, {
        method: "PATCH",
        json: { ...f, key: form.key || null, lo: form.lo || null, hi: form.hi || null, unit: form.unit || null, standard: form.standard || null },
      });
      setEdit(false);
      onChange();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <tr>
      <td>{f.kind}</td>
      {edit ? (
        <td colSpan={3}>
          {error && <div className="alert alert-error">{error}</div>}
          {(["key", "lo", "hi", "unit", "standard"] as const).map((k) => (
            <Field key={k} label={k} inline className="small">
              <input size={8} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </Field>
          ))}
          <Button size="small" onClick={() => void save()}>
            Save
          </Button>
          <Button size="small" variant="ghost" onClick={() => setEdit(false)}>
            Cancel
          </Button>
        </td>
      ) : (
        <>
          <td>
            {f.kind === "property" || f.kind === "consumption" ? `${f.key ?? ""} ` : ""}
            <b>{value(f)}</b>
            {f.per_coat && <span className="muted"> per coat</span>}
            {f.coats ? <span className="muted"> · {f.coats} coats</span> : null}
            {f.standard && <span className="muted"> · {f.standard}</span>}
          </td>
          <td className="small muted">
            {f.page ? `p. ${f.page}: ` : ""}
            {f.sentence}
          </td>
          <td className="small">
            {f.source === "ai" ? "AI, confirmed" : f.source === "manual" ? "typed" : "read"}
            {f.checked_at && (
              <div className="muted">
                checked by {f.checked_by_name ?? "—"}, {new Date(f.checked_at).toLocaleDateString("en-IN")}
                {f.original ? ` (read as ${value(f.original as Fact)})` : ""}
              </div>
            )}
          </td>
        </>
      )}
      {canEdit && !edit && (
        <td className="nowrap">
          <Button size="small" variant="ghost" aria-label={`Edit ${f.kind}`} onClick={() => setEdit(true)}>
            ✎
          </Button>
          <Button size="small" variant="ghost" aria-label={`Delete ${f.kind}`} onClick={() => void api(`/api/spec/tds/facts/${f.id}`, { method: "DELETE" }).then(onChange)}>
            ×
          </Button>
        </td>
      )}
    </tr>
  );
}

function DocWindow({ id, canEdit, onClose }: { id: number; canEdit: boolean; onClose: () => void }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [proposed, setProposed] = useState<(Omit<Fact, "id"> & { take: boolean })[]>([]);
  const [add, setAdd] = useState({ kind: "property", key: "", lo: "", hi: "", unit: "", standard: "", page: "", sentence: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Doc>(`/api/spec/tds/docs/${id}`).then(setDoc, (e) => setError(errorText(e)));
  }, [id]);
  useEffect(load, [load]);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (!doc) return <Modal title="Data sheet" onClose={onClose}>{error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}</Modal>;
  return (
    <Modal title={`${doc.brand ?? "—"}: ${doc.product_name}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p className="small">
        {doc.file_name} · {doc.product ? <>product <b>{doc.product}</b></> : "no product in the master"} · imported {new Date(doc.imported_at).toLocaleDateString("en-IN")}{" "}
        <Button size="small" onClick={() => void downloadFile(`/api/spec/tds/docs/${doc.id}/file`)}>
          Download the PDF
        </Button>
      </p>
      {doc.needs_reading && (
        <div className="alert alert-warn small">
          A scanned sheet: no text to read. Type its facts below{doc.ai_enabled ? ", or read it with the AI and confirm what it finds" : ""}.
          {doc.ai_enabled && canEdit && (
            <Button size="small" disabled={busy} onClick={() => void run(async () => setProposed((await api<{ proposed: Omit<Fact, "id">[] }>(`/api/spec/tds/docs/${doc.id}/ai-read`, { method: "POST" })).proposed.map((p) => ({ ...p, take: true }))))}>
              Read with AI
            </Button>
          )}
        </div>
      )}
      {proposed.length > 0 && (
        <>
          <h3 className="section-title">The AI read (nothing is kept until you save)</h3>
          <table className="table small">
            <tbody>
              {proposed.map((p, i) => (
                <tr key={i}>
                  <td>
                    <input type="checkbox" aria-label="Keep this fact" checked={p.take} onChange={(e) => setProposed(proposed.map((x, j) => (j === i ? { ...x, take: e.target.checked } : x)))} />
                  </td>
                  <td>{p.kind}</td>
                  <td>
                    {p.key} <b>{value(p)}</b> {p.standard}
                  </td>
                  <td className="muted">{p.sentence}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api(`/api/spec/tds/docs/${doc.id}/facts`, { method: "POST", json: proposed.filter((p) => p.take).map((p) => ({ ...p, take: undefined, source: "ai" })) });
                setProposed([]);
                load();
              })
            }
          >
            Save the ticked facts
          </Button>
        </>
      )}
      <div className="table-wrap top-gap">
        <table className="table small">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Value</th>
              <th>Where</th>
              <th>Read / checked</th>
              {canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {(doc.facts ?? []).map((f) => (
              <FactRow key={f.id} f={f} canEdit={canEdit} onChange={load} />
            ))}
            {(doc.facts ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No facts yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="form-row top-gap">
          <Field label="Kind">
            <select value={add.kind} onChange={(e) => setAdd({ ...add, kind: e.target.value })}>
              {KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </Field>
          {(["key", "lo", "hi", "unit", "standard", "page", "sentence"] as const).map((k) => (
            <Field key={k} label={k}>
              <input value={add[k]} onChange={(e) => setAdd({ ...add, [k]: e.target.value })} />
            </Field>
          ))}
          <Button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api(`/api/spec/tds/docs/${doc.id}/facts`, {
                  method: "POST",
                  json: [{ kind: add.kind, key: add.key || null, lo: add.lo || null, hi: add.hi || null, unit: add.unit || null, standard: add.standard || null, page: add.page ? Number(add.page) : null, sentence: add.sentence || null }],
                });
                setAdd({ ...add, key: "", lo: "", hi: "", unit: "", standard: "", sentence: "" });
                load();
              })
            }
          >
            Add the fact
          </Button>
        </div>
      )}
    </Modal>
  );
}

function ImportWindow({ resume, onClose, onDone }: { resume: number | null; onClose: () => void; onDone: () => void }) {
  const [view, setView] = useState<ImportView | null>(null);
  const [progress, setProgress] = useState<{ done: number; all: number } | null>(null);
  const [create, setCreate] = useState<Set<number>>(new Set());
  const [replace, setReplace] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, number> | null>(null);
  const load = useCallback(async (id: number) => {
    const v = await api<ImportView>(`/api/spec/tds/imports/${id}`);
    setView(v);
    setCreate(new Set(v.docs.filter((d) => d.status === "preview" && d.match === "create").map((d) => d.id)));
  }, []);
  useEffect(() => {
    if (resume) void load(resume).catch((e) => setError(errorText(e)));
  }, [resume, load]);

  const upload = async (files: File[]) => {
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) return setError("No PDF in that folder");
    setBusy(true);
    setError(null);
    try {
      const id = view?.id ?? (await api<{ id: number }>("/api/spec/tds/imports", { method: "POST" })).id;
      for (let i = 0; i < pdfs.length; i += BATCH) {
        const part = pdfs.slice(i, i + BATCH);
        const form = new FormData();
        part.forEach((f) => form.append("files", f));
        form.append("paths", JSON.stringify(part.map((f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name)));
        await api(`/api/spec/tds/imports/${id}/files`, { method: "POST", form });
        setProgress({ done: Math.min(i + BATCH, pdfs.length), all: pdfs.length });
      }
      await load(id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!view) return;
    setBusy(true);
    try {
      setResult(await api<Record<string, number>>(`/api/spec/tds/imports/${view.id}/save`, { method: "POST", json: { create: [...create], replace: [...replace] } }));
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const drop = async () => {
    if (!view) return onClose();
    await api(`/api/spec/tds/imports/${view.id}/discard`, { method: "POST" }).catch(() => undefined);
    onClose();
  };
  const n = view?.counts;
  const facts = (n?.facts ?? {}) as Record<string, number>;
  const toggle = (set: Set<number>, id: number, on: boolean) => {
    const s = new Set(set);
    if (on) s.add(id);
    else s.delete(id);
    return s;
  };

  return (
    <Modal title="Import data sheets (TDS)" onClose={onClose} wide>
      <p className="small muted">
        Choose the folder of data sheets: one folder per brand (Technical Data Sheet / Bronco / …). Each PDF is read and shown here first; nothing is kept until you save. A
        sheet for a product that already has one replaces it only where you tick it.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {result ? (
        <div className="alert alert-ok">
          Saved {result.saved} sheets, {result.products_created} new products, {result.replaced} replaced{result.kept_older ? `, ${result.kept_older} older sheets kept` : ""}.
        </div>
      ) : (
        <div className="form-actions" style={{ justifyContent: "flex-start" }}>
          <Field as="div" label="" bare>
          <label className={buttonClass({})}>
            {view ? "Add another folder" : "Choose the folder"}
            <input
              type="file"
              multiple
              hidden
              accept=".pdf"
              {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
              disabled={busy}
              onChange={(e) => void upload(Array.from(e.target.files ?? []))}
            />
          </label>
          </Field>
          {progress && busy && (
            <span className="small">
              Reading {progress.done} of {progress.all}…
            </span>
          )}
        </div>
      )}
      {view && n && (
        <>
          <p>
            {String(n.files)} files: <b>{String(n.products_read)}</b> sheets read ({String(n.with_facts)} with facts, {String(n.needs_reading)} scanned "needs reading",{" "}
            {String(n.read_errors)} unreadable), {String(n.duplicates)} duplicates merged, {String(n.skipped)} safety sheets left out. {String(n.matched)} matched to the product
            master, {String(n.to_create)} not in it, {String(n.replaces_saved)} replace a saved sheet. Facts: {Object.entries(facts).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}.
          </p>
          <div className="table-wrap" style={{ maxHeight: 360, overflow: "auto" }}>
            <table className="table small">
              <thead>
                <tr>
                  <th>Brand</th>
                  <th>Product</th>
                  <th>Facts</th>
                  <th>Product master</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {view.docs.map((d) => (
                  <tr key={d.id} className={d.status !== "preview" ? "muted" : ""}>
                    <td>{d.brand ?? "—"}</td>
                    <td title={d.rel_path ?? d.file_name}>{d.product_name}</td>
                    <td>{d.fact_count ? `${d.fact_count} (${d.kinds.join(", ")})` : "—"}</td>
                    <td>
                      {d.status !== "preview" ? (
                        "—"
                      ) : d.match === "matched" ? (
                        d.product
                      ) : (
                        <label>
                          <input type="checkbox" checked={create.has(d.id)} disabled={!!result} onChange={(e) => setCreate(toggle(create, d.id, e.target.checked))} /> create the product
                        </label>
                      )}
                    </td>
                    <td>
                      {d.status === "duplicate" ? "duplicate, merged" : d.status === "skipped" ? d.read_error : d.needs_reading ? "needs reading" : d.read_error ?? "read"}
                      {d.replaces_id && d.status === "preview" && (
                        <label className="small">
                          {" "}
                          <input type="checkbox" checked={replace.has(d.id)} disabled={!!result} onChange={(e) => setReplace(toggle(replace, d.id, e.target.checked))} /> replace the saved sheet
                        </label>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!result && view.status === "preview" && (
            <div className="form-actions">
              <Button variant="ghost" disabled={busy} onClick={() => void drop()}>
                Drop this import
              </Button>
              <Button variant="primary" disabled={busy} onClick={() => void save()}>
                Save
              </Button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

export default function TechnicalData() {
  const { can } = useAuth();
  const canImport = can("tds.import");
  const [list, setList] = useState<List | null>(null);
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", brand: "", needs: false });
  const [open, setOpen] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (filters.q) p.set("q", filters.q);
    if (filters.brand) p.set("brand", filters.brand);
    if (filters.needs) p.set("needs_reading", "true");
    api<List>(`/api/spec/tds/docs?${p.toString()}`).then(setList, (e) => setError(errorText(e)));
  }, [filters]);
  useEffect(load, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Technical data (TDS)</h1>
        <div className="page-actions">
          <Link to="/products" className={buttonClass({ variant: "ghost" })}>
            ← Products
          </Link>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <Field label="Search product, file or brand" bare>
              <input className="search" placeholder="Search product, file or brand" value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
          </form>
          <Field label="Brand" bare>
            <select value={filters.brand} onChange={(e) => setFilters((f) => ({ ...f, brand: e.target.value }))}>
              <option value="">All brands</option>
              {(list?.brands ?? []).map((b) => (
                <option key={b}>{b}</option>
              ))}
            </select>
          </Field>
          <label className="small">
            <input type="checkbox" checked={filters.needs} onChange={(e) => setFilters((f) => ({ ...f, needs: e.target.checked }))} /> Needs reading
          </label>
          {canImport && (
            <Button variant="primary" onClick={() => setImporting(true)}>
              {list?.open_import_id ? "Import (one waiting to save)" : "Import TDS folder"}
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Product (as in the sheet)</th>
                <th>Product master</th>
                <th>Facts</th>
                <th>Imported</th>
              </tr>
            </thead>
            <tbody>
              {(list?.docs ?? []).map((d) => (
                <tr key={d.id} className="clickable" onClick={() => setOpen(d.id)}>
                  <td>{d.brand ?? "—"}</td>
                  <td>
                    {d.product_name}
                    {d.needs_reading && <span className="small text-warn"> needs reading</span>}
                  </td>
                  <td>{d.product ?? <span className="muted">none</span>}</td>
                  <td className="small">{d.fact_count ? `${d.fact_count}: ${d.kinds.join(", ")}` : "—"}</td>
                  <td className="small muted">{new Date(d.imported_at).toLocaleDateString("en-IN")}</td>
                </tr>
              ))}
              {list && list.docs.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No data sheets{filters.q || filters.brand || filters.needs ? " match" : " yet"}.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
      {open !== null && <DocWindow id={open} canEdit={canImport} onClose={() => { setOpen(null); load(); }} />}
      {importing && <ImportWindow resume={list?.open_import_id ?? null} onClose={() => { setImporting(false); load(); }} onDone={load} />}
    </>
  );
}
