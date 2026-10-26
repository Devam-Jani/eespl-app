// Material estimates: one area set from the site's measured drawing (every measured area in it or
// excluded with a reason), and per material line: area × coverage × (1 + wastage) = quantity → packs,
// per area and in total; then what the site asked for, was sent and used against it.
import { Fragment, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText, num, showError } from "../format";
import { Button, Card, EmptyState, Field, FilePicker, PageSkeleton } from "../ui/components";
import { Modal } from "../ui/Overlay";
import { Table } from "../ui/Table";
import { E, PARTS, useLibrary } from "./common";
import type { Library, Mix } from "./common";
import "./estimate.css";

type Row = { id: number; code: string; title: string; status: string; site: string | null; site_id: number | null; missed: number };

type Area = {
  id: number;
  source: string;
  measure_area_id: number | null;
  cad_area_id: number | null;
  parent_id: number | null;
  code: string | null;
  name: string;
  floor_sqm: string;
  deduction_sqm: string;
  periphery_m: string;
  upturn_mm: string | null;
  use_floor: boolean;
  use_upturn: boolean;
  included: boolean;
  excluded_reason: string | null;
};

type LineRow = { area_id: number; code: string | null; name: string; measure_area_id: number | null; floor_sqm: string; upturn_sqm: string; base_sqm: string; qty: string | null; formula: string };

type Line = {
  id: number;
  product_id: number;
  product: string;
  unit: string;
  system_id: number | null;
  system: string | null;
  mix_design_id: number | null;
  thickness_mm: string | null;
  part: string;
  area_ids: number[] | null;
  note: string | null;
  coverage: string | null;
  coverage_id: number | null;
  per_sqm: string | null;
  wastage_percent: string;
  qty: string | null;
  packs: string | null;
  pack_count: number | null;
  pack_size: string | null;
  complete: boolean;
  rows: LineRow[];
};

type Missed = { key: string; source: string; code: string | null; name: string; floor_sqm: string; periphery_m: string };

type Estimate = {
  id: number;
  code: string;
  title: string;
  status: string;
  site_id: number | null;
  upturn_mm: string;
  note: string | null;
  site: { id: number; code: string; name: string } | null;
  issued_at: string | null;
  areas: Area[];
  lines: Line[];
  missed: Missed[];
  warnings: string[];
  can_edit: boolean;
};

type Balance = { product_id: number; product: string; unit: string; qty: string; complete: boolean; packs: string | null; requested: string; sent: string; returned: string; stock: string; used: string; left: string };

type SiteOpt = { id: number; code: string; name: string };

const STATUS_BADGE: Record<string, string> = { draft: "badge-warn", issued: "badge-ok" };

// --- the list ------------------------------------------------------------------------------------

export function EstimatesList() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    api<Row[]>(`${E}/estimates`).then(setRows, (e) => setError(errorText(e)));
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Material estimates</h1>
        {can("estimate.edit") && (
          <div className="page-actions">
            <Button variant="primary" onClick={() => setCreating(true)}>
              New estimate
            </Button>
          </div>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows && !error && <PageSkeleton />}
      {rows && (
        <Card>
          <Table
            rows={rows}
            rowKey={(r) => r.id}
            onOpen={(r) => navigate(`/estimates/${r.id}`)}
            cards
            label="Material estimates"
            filters={[
              { key: "all", label: "All", test: () => true },
              { key: "draft", label: "Draft", test: (r) => r.status === "draft" },
              { key: "missed", label: "Missed areas", test: (r) => r.missed > 0 },
            ]}
            empty={{ title: "No estimate yet", hint: "Make one from a site's measured drawing: every measured area comes in." }}
            columns={[
              { key: "code", label: "Estimate", render: (r) => <strong>{r.code}</strong>, sort: (r) => r.code },
              { key: "title", label: "Title", render: (r) => r.title, sort: (r) => r.title },
              { key: "site", label: "Site", render: (r) => r.site ?? "—", sort: (r) => r.site },
              { key: "status", label: "Status", render: (r) => <span className={`badge ${STATUS_BADGE[r.status] ?? "badge-muted"}`}>{r.status}</span> },
              {
                key: "missed",
                label: "Missed areas",
                num: true,
                render: (r) => (r.missed ? <span className="badge badge-danger">{r.missed}</span> : "—"),
                sort: (r) => r.missed,
              },
            ]}
          />
        </Card>
      )}
      {creating && <NewEstimate onClose={() => setCreating(false)} onMade={(e) => navigate(`/estimates/${e.id}`)} />}
    </>
  );
}

function NewEstimate({ onClose, onMade }: { onClose: () => void; onMade: (e: Estimate) => void }) {
  const [sites, setSites] = useState<SiteOpt[]>([]);
  const [q, setQ] = useState("");
  const [f, setF] = useState({ site_id: "", title: "", upturn_mm: "300" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => {
      api<{ items: SiteOpt[] }>(`/api/sites?limit=50${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ""}`).then(
        (r) => setSites(r.items),
        () => setSites([]),
      );
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      onMade(await api<Estimate>(`${E}/estimates`, { method: "POST", json: { site_id: Number(f.site_id), title: f.title, upturn_mm: f.upturn_mm || "300" } }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="New material estimate" onClose={onClose}>
      <form onSubmit={save}>
        <Field label="Find the site">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code or name" />
        </Field>
        <Field label="Site" hint="Its measured areas (Measure and bill) all come into the estimate">
          <select required value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })}>
            <option value="">— site —</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input required maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Terrace waterproofing" />
        </Field>
        <Field label="Upturn (mm)" hint="On the walls round each area, unless an area or the line's system says otherwise">
          <input type="number" min="0" max="3000" step="any" value={f.upturn_mm} onChange={(e) => setF({ ...f, upturn_mm: e.target.value })} />
        </Field>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>
            Make the estimate
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// --- one estimate --------------------------------------------------------------------------------

export function EstimatePage() {
  const { id } = useParams();
  const [est, setEst] = useState<Estimate | null>(null);
  const [balance, setBalance] = useState<Balance[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [excluding, setExcluding] = useState<{ key?: string; area?: Area; name: string } | null>(null);
  const [line, setLine] = useState<Line | "new" | null>(null);
  const [imported, setImported] = useState<ImportOut | null>(null);
  const [lib] = useLibrary();
  const [mixes, setMixes] = useState<Mix[]>([]);
  useEffect(() => {
    api<Estimate>(`${E}/estimates/${id}`).then(setEst, (e) => setError(errorText(e)));
    api<Mix[]>(`${E}/mixes`).then(setMixes, () => setMixes([]));
  }, [id]);
  useEffect(() => {
    if (est) api<Balance[]>(`${E}/estimates/${est.id}/balance`).then(setBalance, () => setBalance(null));
  }, [est]);

  /** a change to the estimate: the API answers the whole estimate again */
  const act = async (what: string, path: string, json?: unknown, method = "POST") => {
    setBusy(what);
    setError("");
    try {
      setEst(await api<Estimate>(`${E}/estimates/${id}${path}`, { method, json }));
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      setBusy("");
    }
  };
  const putArea = (a: Area, patch: Partial<Area>) => {
    const b = { ...a, ...patch };
    return act(`area${a.id}`, `/areas/${a.id}`, { upturn_mm: b.upturn_mm === "" ? null : b.upturn_mm, use_floor: b.use_floor, use_upturn: b.use_upturn, included: b.included, excluded_reason: b.excluded_reason }, "PUT");
  };
  const sheetInput = useRef<HTMLInputElement>(null);
  const importSheet = async (file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setBusy("import");
    try {
      setImported(await api<ImportOut>(`${E}/estimates/${id}/import`, { method: "POST", form }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy("");
    }
  };

  if (!est) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton label="Loading the estimate" />;
  const edit = est.can_edit;
  const byId = new Map(est.areas.map((a) => [a.id, a]));
  // the areas in order, each Misc area under its parent
  const tops = est.areas.filter((a) => !a.parent_id || !byId.has(a.parent_id));
  const ordered = tops.flatMap((a) => [a, ...est.areas.filter((c) => c.parent_id === a.id)]);
  const measureLink = (measureAreaId: number | null, text: string) =>
    measureAreaId && est.site_id ? (
      <Link to={`/estimates/${est.id}/drawing?area=${measureAreaId}`} title="Show it on the drawing">
        {text}
      </Link>
    ) : (
      text
    );

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/estimates" className="muted">
            ← Material estimates
          </Link>
          <h1>
            {est.code} · {est.title}
          </h1>
          <p className="muted small">
            {est.site ? (
              <Link to={`/sites/${est.site.id}`}>
                {est.site.code} {est.site.name}
              </Link>
            ) : (
              "No site"
            )}{" "}
            · upturn {num(est.upturn_mm)} mm · <span className={`badge ${STATUS_BADGE[est.status] ?? "badge-muted"}`}>{est.status}</span>
          </p>
        </div>
        <div className="page-actions">
          <Button onClick={() => void downloadFile(`${E}/estimates/${est.id}/excel`).catch(showError)}>Excel</Button>
          <Button onClick={() => void downloadFile(`${E}/estimates/${est.id}/pdf`).catch(showError)}>PDF</Button>
          <FilePicker
            showChosen={false}
            label={busy === "import" ? "Reading…" : "Read an old planning sheet"}
            variant="ghost"
            accept=".xlsx,.xlsm"
            inputRef={sheetInput}
            onFiles={(fs) => {
              if (fs[0]) void importSheet(fs[0]);
              if (sheetInput.current) sheetInput.current.value = "";
            }}
          />
          {edit && (
            <Button variant="primary" loading={busy === "issue"} onClick={() => void act("issue", "/issue")}>
              Issue
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {est.warnings.length > 0 && (
        <div className={`alert ${est.missed.length ? "alert-error" : "alert-warn"}`} role="alert">
          {est.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}
      {est.missed.length > 0 && (
        <Card title="Measured areas not in the estimate" size="small">
          <p className="small muted">Every measured area is estimated or left out with a reason. The estimate cannot be issued until each one is.</p>
          <ul className="est-missed">
            {est.missed.map((m) => (
              <li key={m.key}>
                <div>
                  <strong>
                    {m.code ? `${m.code} ` : ""}
                    {m.name}
                  </strong>{" "}
                  {num(m.floor_sqm, 2)} sqm · {num(m.periphery_m, 2)} m
                  <div className="small muted">{m.source === "takeoff" ? "from the AutoCAD takeoff" : "measured on the drawing"}</div>
                </div>
                {edit && (
                  <div className="row-actions">
                    <Button size="small" variant="primary" loading={busy === m.key} onClick={() => void act(m.key, "/areas", { keys: [m.key] })}>
                      Add to the estimate
                    </Button>
                    <Button size="small" onClick={() => setExcluding({ key: m.key, name: m.name })}>
                      Exclude…
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Areas" actions={<span className="small muted">{est.areas.filter((a) => a.included).length} in · {est.areas.filter((a) => !a.included).length} excluded</span>}>
        {est.areas.length === 0 ? (
          <EmptyState title="No area yet" hint="Measure the site's drawing (Measure and bill): its areas come in here." />
        ) : (
          <div className="table-wrap">
            <table className="table est-areas">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Area</th>
                  <th className="num">Floor (sqm)</th>
                  <th className="num">Cut-outs (sqm)</th>
                  <th className="num">Periphery (m)</th>
                  <th className="num">Upturn (mm)</th>
                  <th>Floor</th>
                  <th>Upturn</th>
                  <th>In the estimate</th>
                </tr>
              </thead>
              <tbody>
                {ordered.map((a) => (
                  <tr key={a.id} className={a.included ? undefined : "row-muted"}>
                    <td>{a.code ?? "—"}</td>
                    <td>
                      {a.parent_id ? <span className="muted">↳ </span> : null}
                      {measureLink(a.measure_area_id, a.name)}
                    </td>
                    <td className="num">{num(a.floor_sqm, 2)}</td>
                    <td className="num">{Number(a.deduction_sqm) ? `−${num(a.deduction_sqm, 2)}` : "—"}</td>
                    <td className="num">{num(a.periphery_m, 2)}</td>
                    <td className="num">
                      {edit ? (
                        <Field label={`Upturn of ${a.name} (mm)`} bare>
                          <input
                            className="input-narrow"
                            type="number"
                            min="0"
                            max="3000"
                            step="any"
                            placeholder={num(est.upturn_mm)}
                            defaultValue={a.upturn_mm ?? ""}
                            onBlur={(e) => e.target.value !== (a.upturn_mm ?? "") && void putArea(a, { upturn_mm: e.target.value })}
                          />
                        </Field>
                      ) : (
                        num(a.upturn_mm ?? est.upturn_mm)
                      )}
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`Use the floor of ${a.name}`} checked={a.use_floor} disabled={!edit} onChange={(e) => void putArea(a, { use_floor: e.target.checked })} />
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`Use the upturn of ${a.name}`} checked={a.use_upturn} disabled={!edit} onChange={(e) => void putArea(a, { use_upturn: e.target.checked })} />
                    </td>
                    <td>
                      {a.included ? (
                        edit ? (
                          <Button size="small" variant="ghost" onClick={() => setExcluding({ area: a, name: a.name })}>
                            Exclude…
                          </Button>
                        ) : (
                          "Yes"
                        )
                      ) : (
                        <>
                          <span className="badge badge-muted">Excluded</span> <span className="small">{a.excluded_reason}</span>
                          {edit && (
                            <Button size="small" variant="ghost" onClick={() => void putArea(a, { included: true, excluded_reason: null })}>
                              Put back
                            </Button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Materials"
        actions={
          edit && (
            <Button variant="primary" size="small" onClick={() => setLine("new")}>
              Add a material
            </Button>
          )
        }
      >
        {est.lines.length === 0 ? (
          <EmptyState title="No material yet" hint={edit ? "Add a material from the library: its coverage and wastage work out the quantity." : undefined} />
        ) : (
          est.lines.map((ln) => <LineView key={ln.id} ln={ln} edit={edit} onEdit={() => setLine(ln)} onDelete={() => window.confirm(`Delete ${ln.product}?`) && void act(`del${ln.id}`, `/lines/${ln.id}`, undefined, "DELETE")} measureLink={measureLink} />)
        )}
      </Card>

      <Card title="Summary and balance">
        {balance && balance.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Material</th>
                  <th>Unit</th>
                  <th className="num">Needed</th>
                  <th>Packs</th>
                  <th className="num">Requested</th>
                  <th className="num">Sent</th>
                  <th className="num">Used</th>
                  <th className="num">Left</th>
                </tr>
              </thead>
              <tbody>
                {balance.map((b) => (
                  <tr key={b.product_id}>
                    <td>
                      {b.product}
                      {!b.complete && <span className="badge badge-danger">not complete</span>}
                    </td>
                    <td>{b.unit}</td>
                    <td className="num">
                      <strong>{num(b.qty, 2)}</strong>
                    </td>
                    <td>{b.packs ?? "—"}</td>
                    <td className="num">{num(b.requested, 2)}</td>
                    <td className="num">{num(b.sent, 2)}</td>
                    <td className="num">{num(b.used, 2)}</td>
                    <td className={`num ${Number(b.left) < 0 ? "text-danger" : ""}`}>{num(b.left, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Nothing worked out yet" />
        )}
        <p className="small muted">Used = sent to the site's store − returned − still in stock. Left = needed − used.</p>
      </Card>

      {excluding && (
        <ExcludeForm
          name={excluding.name}
          onClose={() => setExcluding(null)}
          onSave={(reason) =>
            excluding.key ? act("exclude", "/exclude", { key: excluding.key, reason }) : putArea(excluding.area!, { included: false, excluded_reason: reason })
          }
        />
      )}
      {line && lib && (
        <LineForm
          est={est}
          lib={lib}
          mixes={mixes}
          line={line === "new" ? undefined : line}
          onClose={() => setLine(null)}
          onSave={(json) => (line === "new" ? act("line", "/lines", json) : act("line", `/lines/${line.id}`, json, "PUT"))}
        />
      )}
      {imported && <ImportResult out={imported} onClose={() => setImported(null)} />}
    </>
  );
}

function LineView({ ln, edit, onEdit, onDelete, measureLink }: { ln: Line; edit: boolean; onEdit: () => void; onDelete: () => void; measureLink: (id: number | null, text: string) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const base = ln.rows.reduce((s, r) => s + Number(r.base_sqm), 0);
  return (
    <Card
      as="article"
      size="small"
      className="est-line"
      title={
        <>
          {ln.product} <span className="small muted">{[ln.system ?? "any system", PARTS[ln.part], ln.area_ids ? `${ln.area_ids.length} chosen area(s)` : "all areas"].join(" · ")}</span>
        </>
      }
      actions={
        edit && (
          <>
            <Button size="small" onClick={onEdit}>
              Edit
            </Button>
            <Button size="small" variant="danger" onClick={onDelete}>
              Delete
            </Button>
          </>
        )
      }
    >
      {ln.complete ? (
        <p className="est-formula">
          {num(base, 2)} sqm × <span title="coverage">{ln.coverage}</span> × (1 + <strong>{num(ln.wastage_percent, 2)}%</strong> wastage) ={" "}
          <strong>
            {num(ln.qty, 2)} {ln.unit}
          </strong>
          {ln.packs && (
            <>
              {" "}
              → <strong>{ln.packs}</strong>
              {ln.pack_size && <span className="muted"> ({num(ln.pack_size)} {ln.unit} each)</span>}
            </>
          )}
        </p>
      ) : (
        <div className="alert alert-error">No coverage in the library for {ln.product}: the quantity is not worked out. Add it in the Material library.</div>
      )}
      {ln.note && <p className="small muted">{ln.note}</p>}
      <Button size="small" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} the {ln.rows.length} area(s)
      </Button>
      {open && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Area</th>
                <th className="num">Floor</th>
                <th className="num">Upturn</th>
                <th className="num">Quantity</th>
                <th>Working</th>
              </tr>
            </thead>
            <tbody>
              {ln.rows.map((r) => (
                <tr key={r.area_id}>
                  <td>{measureLink(r.measure_area_id, `${r.code ? `${r.code} ` : ""}${r.name}`)}</td>
                  <td className="num">{num(r.floor_sqm, 2)}</td>
                  <td className="num">{num(r.upturn_sqm, 2)}</td>
                  <td className="num">{num(r.qty, 2)}</td>
                  <td className="small">{r.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ExcludeForm({ name, onClose, onSave }: { name: string; onClose: () => void; onSave: (reason: string) => Promise<boolean> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    if (await onSave(reason.trim())) onClose();
    setBusy(false);
  };
  return (
    <Modal title={`Leave out ${name}`} onClose={onClose}>
      <form onSubmit={save}>
        <Field label="Why it is left out" hint="Kept with the estimate: e.g. the client's own scope, not in this work order">
          <textarea required minLength={3} maxLength={500} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy}>
            Exclude
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function LineForm({ est, lib, mixes, line, onClose, onSave }: { est: Estimate; lib: Library; mixes: Mix[]; line?: Line; onClose: () => void; onSave: (json: unknown) => Promise<boolean> }) {
  const [f, setF] = useState({
    product_id: line ? String(line.product_id) : "",
    system_id: line?.system_id ? String(line.system_id) : "",
    mix_design_id: line?.mix_design_id ? String(line.mix_design_id) : "",
    thickness_mm: line?.thickness_mm ?? "",
    part: line?.part ?? "both",
    note: line?.note ?? "",
  });
  const [chosen, setChosen] = useState<number[] | null>(line?.area_ids ?? null);
  const [busy, setBusy] = useState(false);
  const mix = mixes.find((m) => String(m.id) === f.mix_design_id);
  // the mixes the product is a component of (the admixture included)
  const productMixes = mixes.filter((m) => m.parts.some((p) => String(p.product_id) === f.product_id));
  const product = lib.products.find((p) => String(p.id) === f.product_id);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const ok = await onSave({
      product_id: Number(f.product_id),
      system_id: f.system_id ? Number(f.system_id) : null,
      mix_design_id: f.mix_design_id ? Number(f.mix_design_id) : null,
      thickness_mm: f.mix_design_id && f.thickness_mm ? f.thickness_mm : null,
      part: f.part,
      area_ids: chosen && chosen.length ? chosen : null,
      note: f.note || null,
    });
    setBusy(false);
    if (ok) onClose();
  };
  const included = est.areas.filter((a) => a.included);
  return (
    <Modal title={line ? `Edit ${line.product}` : "Add a material"} onClose={onClose} wide>
      <form onSubmit={save}>
        <div className="grid-2">
          <Field label="Material" hint={product ? `${product.coverages.map((c) => `${c.system ?? "any system"}: ${c.label}`).join("; ")} · wastage ${num(product.wastage_percent ?? 0, 2)}%` : "From the library"}>
            <select required value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value, mix_design_id: "" })}>
              <option value="">— material —</option>
              {lib.products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.unit})
                </option>
              ))}
            </select>
          </Field>
          <Field label="System" hint="The coverage for that system, else the product's any-system one">
            <select value={f.system_id} onChange={(e) => setF({ ...f, system_id: e.target.value })}>
              <option value="">Any system</option>
              {lib.systems.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.upturn_mm ? ` (upturn ${num(s.upturn_mm)} mm)` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Mix design" hint={productMixes.length ? "The quantity from the mix at the thickness, not the library's coverage" : "The material is in no mix design"}>
            <select value={f.mix_design_id} disabled={!productMixes.length} onChange={(e) => setF({ ...f, mix_design_id: e.target.value })}>
              <option value="">— none —</option>
              {productMixes.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({num(m.thickness_mm)} mm)
                </option>
              ))}
            </select>
          </Field>
          {mix && (
            <Field label="Thickness (mm)">
              <input type="number" min="0" max="1000" step="any" placeholder={num(mix.thickness_mm)} value={f.thickness_mm} onChange={(e) => setF({ ...f, thickness_mm: e.target.value })} />
            </Field>
          )}
          <Field label="Where it goes">
            <select value={f.part} onChange={(e) => setF({ ...f, part: e.target.value })}>
              {Object.entries(PARTS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Note">
            <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
          </Field>
        </div>
        <div role="group" aria-label="Areas" className="top-gap">
          <p className="small muted">Areas</p>
          <label className="check">
            <input type="radio" name="areas" checked={chosen === null} onChange={() => setChosen(null)} /> All the areas in the estimate
          </label>
          <label className="check">
            <input type="radio" name="areas" checked={chosen !== null} onChange={() => setChosen([])} /> Chosen areas
          </label>
          {chosen !== null && (
            <div className="est-area-picks">
              {included.map((a) => (
                <label key={a.id} className="check">
                  <input type="checkbox" checked={chosen.includes(a.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, a.id] : chosen.filter((x) => x !== a.id))} /> {a.code ? `${a.code} ` : ""}
                  {a.name} <span className="muted">({num(a.floor_sqm, 2)} sqm)</span>
                </label>
              ))}
            </div>
          )}
        </div>
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

// --- an old planning sheet, read against the drawing and the library --------------------------------

type ImportOut = {
  file: string;
  findings: string[];
  sheets: {
    name: string;
    areas: { cell: string; label: string; value: string; measured: string; diff: string }[];
    coverages: { cell: string; product: string; value: string; library: string; library_unit: string; differs: boolean }[];
    typed_as_text: { cell: string; text: string }[];
  }[];
};

function ImportResult({ out, onClose }: { out: ImportOut; onClose: () => void }) {
  return (
    <Modal title={`What ${out.file} says`} onClose={onClose} wide>
      {out.findings.length ? (
        <div className="alert alert-warn">
          <strong>{out.findings.length} finding(s)</strong>
          <ul>
            {out.findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="alert alert-ok">Nothing found against the drawing or the library.</div>
      )}
      {out.sheets.map((s) => (
        <Fragment key={s.name}>
          <h3>{s.name}</h3>
          {s.areas.length + s.coverages.length + s.typed_as_text.length === 0 && <p className="muted small">No area, coverage or figure typed as text found.</p>}
          {s.areas.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Cell</th>
                    <th>Area in the sheet</th>
                    <th className="num">Sheet (sqm)</th>
                    <th className="num">Drawing (sqm)</th>
                    <th className="num">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {s.areas.map((a, i) => (
                    <tr key={i} className={Math.abs(Number(a.diff)) >= 0.01 ? "row-flagged" : undefined}>
                      <td>{a.cell}</td>
                      <td>{a.label}</td>
                      <td className="num">{num(a.value, 2)}</td>
                      <td className="num">{num(a.measured, 2)}</td>
                      <td className="num">{num(a.diff, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {s.coverages.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Cell</th>
                    <th>Product</th>
                    <th className="num">Sheet</th>
                    <th className="num">Library</th>
                  </tr>
                </thead>
                <tbody>
                  {s.coverages.map((c, i) => (
                    <tr key={i} className={c.differs ? "row-flagged" : undefined}>
                      <td>{c.cell}</td>
                      <td>{c.product}</td>
                      <td className="num">{num(c.value)}</td>
                      <td className="num">
                        {num(c.library)} {c.library_unit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {s.typed_as_text.length > 0 && (
            <p className="small">
              Typed as text (no total adds them): {s.typed_as_text.map((t) => `${t.cell} '${t.text}'`).join(", ")}
            </p>
          )}
        </Fragment>
      ))}
    </Modal>
  );
}
