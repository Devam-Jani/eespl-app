import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";

type Step = {
  text: string;
  product?: string | null;
  consumption?: string | null;
  unit?: string | null;
  coats?: number | null;
  coat_no?: number | null;
  wait?: string | null;
  tools?: string[];
  scope?: "ours" | "client";
  to_confirm?: string[];
  client_ref?: string | null;
};
type Stage = { heading: string; option?: string | null; steps: Step[] };
type SystemBrief = {
  id: number;
  code: string;
  name: string;
  brand: string | null;
  system_type: string | null;
  system_type_label: string | null;
  elements: string[];
  element_labels: string[];
  version: number;
  to_confirm: number;
  steps: number;
  sources: { offer: string; item: string; option: string | null }[];
  is_demo: boolean;
};
type Value = { value: string; num?: number | null; unit?: string; standard?: string | null; source?: string; all?: string[] };
type Product = {
  id?: number;
  name: string;
  brand?: string | null;
  kind?: string | null;
  values: Record<string, Value>;
  standards?: string[];
  datasheet: string | null;
  missing?: string[];
};
type SystemDetail = SystemBrief & {
  conditions: { text: string; source?: string }[];
  why: string | null;
  competing: { option: string; why_not: string }[];
  stages: Stage[];
  hold_points: { stage: string; text: string }[];
  tests: { name: string; kind: string; hours: number | null; to_confirm?: string }[];
  checklist: { stage: string; items: string[] }[];
  guarantee_years: number | null;
  boq_description: string | null;
  measurement_rule: string | null;
  specs: Record<string, Value>;
  to_confirm_list: { field: string; label: string; note: string; value: string }[];
  fixes: { where: string; before: string; after: string; why: string }[];
  templates: { id: number; name: string; lines: number; median_rate: string | null }[];
  products: Product[];
  changes: { version: number; reason: string; changes: { field: string }[]; at: string }[];
};
type StandardBrief = { id: number; name: string; client_name: string | null; rules: number; to_check: number; approved_makes: string[]; guarantee_years: number | null };
type Spec = { property: string; label: string; standard: string | null; required: string; page: number; material: string | null };
type Make = { system: string; brand: string; product: string; status: "approved" | "tpt" | "not_approved"; note: string | null; page: number };
type Rule = {
  id: number;
  element: string;
  element_label: string;
  condition_label: string | null;
  condition: Record<string, unknown>;
  system_type: string | null;
  system_type_label: string | null;
  system_text: string | null;
  required_types: { where: string; type: string; label: string }[];
  min_specs: Spec[];
  makes: Make[];
  tests: { kind: string; hours: number | null; text: string; page: number }[];
  hold_points: { stage: string; text: string }[];
  checklist: { stage: string; items: string[] }[];
  guarantee_years: number | null;
  page: number | null;
  confidence: string;
  status: "ok" | "to_check";
  check_note: string | null;
  sop: { id: number; sop_no: string | null; revision: string | null; date: string | null; file: string; format: string } | null;
};
type StandardDetail = {
  id: number;
  name: string;
  client_name: string | null;
  source: string | null;
  approved_makes: string[];
  guarantee_years: number | null;
  report: { sops: number; read: number; rules: number; to_check: number; contradictions: number; formats: Record<string, number>; xlsx_rows: number };
  documents: {
    id: number;
    sop_no: string | null;
    revision: string | null;
    date: string | null;
    title: string | null;
    file: string;
    format: string;
    pages: number;
    element: string | null;
    rules: number;
  }[];
  rules: Rule[];
  contradictions: { id: number; topic: string; values: { value: string; page: number; text: string }[]; sop_no: string | null; file: string | null }[];
};
type Check = {
  topic: string;
  required: string;
  ours?: string;
  status: "green" | "red" | "confirm";
  gap?: string | null;
  ref?: string | null;
  choices?: { key: string; label: string; options?: string[]; query?: string; note?: string | null }[];
  choice?: string;
};
type Item = {
  id: number;
  name: string;
  element: string | null;
  element_label: string | null;
  qty: string | null;
  unit: string | null;
  places: { name: string; label: string; area_sqm: number | null; source: string }[];
  conditions: Record<string, { value: unknown; source: string }>;
  missing: string[];
  system: SystemBrief | null;
  options: SystemBrief[];
  reason: string | null;
  stages: Stage[];
  edits: { at: string; by: string | null; reason: string; stage: string; version: number }[];
  rule: Rule | { id: number; condition_label: string | null } | null;
  rule_note: string | null;
  make_choice: string | null;
  compliance?: { rows: Check[]; green: number; red: number; confirm: number };
};
type Prebid = { id: number; item_id: number | null; kind: string; text: string; reference: string | null; status: "open" | "sent" | "answered"; answer: string | null };
type MethodologyOut = {
  id: number;
  code: string;
  title: string;
  tender_id: number | null;
  quotation_id: number | null;
  standard_id: number | null;
  site_id: number | null;
  brand: string | null;
  revision: number;
  version: number;
  is_demo: boolean;
  items: Item[];
  files: { id: number; kind: string; audience: string; file_name: string; version: number; revision: number }[];
  compliance?: { green: number; red: number; confirm: number };
  prebid?: Prebid[];
};

const STATUS: Record<string, [string, string]> = { green: ["Complies", "badge-ok"], red: ["Gap", "badge-danger"], confirm: ["To confirm", "badge-warn"] };
const PROPS: Record<string, string> = {
  elongation: "Elongation",
  tensile: "Tensile strength",
  adhesion: "Adhesion (pull-off)",
  peel_adhesion: "Peel adhesion",
  crack_bridging: "Crack bridging",
  dft: "DFT",
  thickness: "Thickness",
  coverage: "Coverage",
  pot_life: "Pot life",
  solid_content: "Solid content",
  hardness: "Hardness",
  hydrostatic: "Hydrostatic",
  consumption: "Consumption",
};

function Badge({ s }: { s: string }) {
  const [label, cls] = STATUS[s] ?? [s, "badge-muted"];
  return <span className={`badge ${cls}`}>{label}</span>;
}

function Steps({ stages, edit }: { stages: Stage[]; edit?: (stage: number, step: number) => void }) {
  let n = 0;
  return (
    <>
      {stages.map((s, si) => (
        <div key={`${s.heading}-${si}`} className="top-gap">
          <h3 className="section-title">{s.heading}</h3>
          <table className="table compact">
            <tbody>
              {s.steps.map((st, i) => {
                n += 1;
                return (
                  <tr key={i}>
                    <td className="num">{n}.</td>
                    <td>
                      {st.text}
                      {st.scope === "client" && <span className="badge badge-muted"> client&apos;s scope</span>}
                      {(st.to_confirm ?? []).map((t) => (
                        <div key={t} className="small text-danger">
                          to confirm: {t}
                        </div>
                      ))}
                      {st.client_ref && <div className="small muted">client: {st.client_ref}</div>}
                    </td>
                    <td className="small">{st.product ?? ""}</td>
                    <td className="small">{st.consumption ? `${st.consumption} ${st.unit ?? ""}` : ""}</td>
                    <td className="small">{st.wait ?? ""}</td>
                    <td className="small">{(st.tools ?? []).join(", ")}</td>
                    {edit && (
                      <td>
                        <button className="btn btn-small" onClick={() => edit(si, i)}>
                          Edit
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}

/** The method library, the client standards and the methodologies. */
export function MethodologyHome() {
  const { can } = useAuth();
  const [systems, setSystems] = useState<SystemBrief[]>([]);
  const [standards, setStandards] = useState<StandardBrief[]>([]);
  const [ms, setMs] = useState<{ id: number; code: string; title: string; items: number; version: number; compliance?: { green: number; red: number; confirm: number } }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const tender = params.get("tender");
  useEffect(() => {
    api<SystemBrief[]>("/api/methodology/systems").then(setSystems, (e) => setError(errorText(e)));
    api<StandardBrief[]>("/api/methodology/standards").then(setStandards, () => undefined);
    api<typeof ms>(`/api/methodology/methodologies${tender ? `?tender_id=${tender}` : ""}`).then(setMs, () => undefined);
  }, [tender]);
  const [building, setBuilding] = useState(false);
  const [std, setStd] = useState<string>("");
  const build = async () => {
    if (!tender) return;
    setBuilding(true);
    try {
      const m = await api<MethodologyOut>("/api/methodology/methodologies", {
        method: "POST",
        json: { tender_id: Number(tender), standard_id: std ? Number(std) : null, brand: "Bronco" },
      });
      window.location.href = `/methodology/m/${m.id}`;
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBuilding(false);
    }
  };
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Methodology builder</h1>
          <p className="muted">Our method library (from our offers), the client standards read from their SOPs, and the methodology of each BOQ checked against its standard.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tender && can("methodology.edit") && (
        <div className="card">
          <h2 className="section-title">Build the methodology of tender #{tender}</h2>
          <div className="form-row">
            <select value={std} onChange={(e) => setStd(e.target.value)} aria-label="Client standard">
              <option value="">The tender&apos;s client standard</option>
              {standards.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <button className="btn btn-primary" disabled={building} onClick={build}>
              {building ? "Building…" : "Build"}
            </button>
          </div>
        </div>
      )}
      <div className="card top-gap">
        <h2 className="section-title">Methodologies</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Code</th>
              <th>Title</th>
              <th className="num">Items</th>
              <th className="num">Version</th>
              <th>Compliance</th>
            </tr>
          </thead>
          <tbody>
            {ms.map((m) => (
              <tr key={m.id}>
                <td>
                  <Link to={`/methodology/m/${m.id}`}>{m.code}</Link>
                </td>
                <td>{m.title}</td>
                <td className="num">{m.items}</td>
                <td className="num">v{m.version}</td>
                <td className="small">{m.compliance ? `${m.compliance.green} complies · ${m.compliance.red} gaps · ${m.compliance.confirm} to confirm` : ""}</td>
              </tr>
            ))}
            {!ms.length && (
              <tr>
                <td colSpan={5} className="muted">
                  None yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Client standards</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Standard</th>
              <th className="num">Rules</th>
              <th className="num">To check</th>
              <th>Approved makes</th>
              <th className="num">Guarantee</th>
            </tr>
          </thead>
          <tbody>
            {standards.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/methodology/standards/${s.id}`}>{s.name}</Link>
                </td>
                <td className="num">{s.rules}</td>
                <td className="num">{s.to_check}</td>
                <td className="small">{s.approved_makes.join(", ")}</td>
                <td className="num">{s.guarantee_years ? `${s.guarantee_years} y` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Method library</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Code</th>
              <th>System</th>
              <th>Type</th>
              <th>Suits</th>
              <th className="num">Steps</th>
              <th className="num">To confirm</th>
              <th>From</th>
              <th className="num">v</th>
            </tr>
          </thead>
          <tbody>
            {systems.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/methodology/systems/${s.id}`}>{s.code}</Link>
                </td>
                <td>{s.name}</td>
                <td className="small">{s.system_type_label}</td>
                <td className="small">{s.element_labels.join(", ")}</td>
                <td className="num">{s.steps}</td>
                <td className="num">{s.to_confirm || ""}</td>
                <td className="small">{s.sources.map((x) => `${x.offer} item ${x.item}${x.option ? ` opt ${x.option}` : ""}`).join("; ")}</td>
                <td className="num">{s.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** One system of our library: where it suits, the steps, the products' data sheets, what to confirm. */
export function SystemPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [s, setS] = useState<SystemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [field, setField] = useState("guarantee_years");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const load = useCallback(() => api<SystemDetail>(`/api/methodology/systems/${id}`).then(setS, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    load();
  }, [load]);
  const save = async () => {
    try {
      const v = field === "guarantee_years" ? Number(value) : value;
      setS(await api<SystemDetail>(`/api/methodology/systems/${id}`, { method: "PUT", json: { change: { [field]: v }, reason } }));
      setValue("");
      setReason("");
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  };
  if (!s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to="/methodology">Methodology</Link> / <code>{s.code}</code> · v{s.version}
          </p>
          <h1>{s.name}</h1>
          <p className="muted">
            {s.brand} · {s.system_type_label} · suits {s.element_labels.join(", ")} · from{" "}
            {s.sources.map((x) => `${x.offer} item ${x.item}${x.option ? ` option ${x.option}` : ""}`).join("; ")}
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="grid-2">
        <div className="card">
          <h2 className="section-title">Where it suits and why</h2>
          {s.conditions.map((c) => (
            <p key={c.text} className="small">
              {c.text} <span className="muted">({c.source})</span>
            </p>
          ))}
          <p className="small">
            <b>Why we pick it:</b> {s.why ?? <span className="text-danger">to confirm</span>}
          </p>
          {s.competing.length > 0 && (
            <p className="small">Competing options in the same offer: {s.competing.map((c) => `option ${c.option} (why not: ${c.why_not})`).join("; ")}</p>
          )}
          <p className="small">
            <b>Guarantee:</b> {s.guarantee_years ? `${s.guarantee_years} years` : <span className="text-danger">to confirm</span>} · <b>BOQ text:</b> {s.boq_description ?? "—"}
          </p>
          <p className="small">
            <b>Measurement:</b> {s.measurement_rule ?? "—"}
          </p>
        </div>
        <div className="card">
          <h2 className="section-title">To confirm ({s.to_confirm_list.length})</h2>
          <ul className="small">
            {s.to_confirm_list.map((c, i) => (
              <li key={i}>
                <b>{c.label}:</b> {c.note}
              </li>
            ))}
          </ul>
          {s.fixes.length > 0 && (
            <details>
              <summary className="small">{s.fixes.length} copy-paste errors fixed while seeding</summary>
              <ul className="small">
                {s.fixes.map((f, i) => (
                  <li key={i}>
                    {f.where}: “{f.before}” → “{f.after}” ({f.why})
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Stages and steps</h2>
        <Steps stages={s.stages} />
      </div>
      <div className="grid-2 top-gap">
        <div className="card">
          <h2 className="section-title">Hold points and tests</h2>
          <ul className="small">
            {s.hold_points.map((h) => (
              <li key={h.text}>Hold point: {h.text}</li>
            ))}
            {s.tests.map((t) => (
              <li key={t.name}>
                {t.name}
                {t.hours ? ` — ${t.hours} h` : t.to_confirm ? <span className="text-danger"> — {t.to_confirm}</span> : ""}
              </li>
            ))}
          </ul>
          <h2 className="section-title">Checklist</h2>
          {s.checklist.map((c) => (
            <div key={c.stage} className="small">
              <b>{c.stage}</b>
              <ul>
                {c.items.map((q) => (
                  <li key={q}>{q} ☐ Yes ☐ No</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="card">
          <h2 className="section-title">Products and their data sheets</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th>Data sheet values</th>
                <th>Data sheet</th>
              </tr>
            </thead>
            <tbody>
              {s.products.map((p) => (
                <tr key={p.name}>
                  <td className="small">{p.name}</td>
                  <td className="small">
                    {Object.entries(p.values).map(([k, v]) => (
                      <div key={k}>
                        {PROPS[k] ?? k}: {v.value}
                        {v.standard ? ` (${v.standard})` : ""}
                      </div>
                    ))}
                    {(p.missing ?? []).length > 0 && <div className="text-danger">to confirm: {(p.missing ?? []).map((k) => PROPS[k] ?? k).join(", ")}</div>}
                  </td>
                  <td className="small">
                    {p.datasheet && p.id ? (
                      <button className="link-button" onClick={() => downloadFile(`/api/methodology/products/${p.id}/datasheet`)}>
                        {p.datasheet}
                      </button>
                    ) : (
                      <span className="muted">none</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.templates.length > 0 && (
            <p className="small">
              Rates:{" "}
              {s.templates.map((t) => (
                <Link key={t.id} to={`/knowledge/templates/${t.id}`}>
                  {t.name} ({t.lines} lines{t.median_rate ? `, median ₹${t.median_rate}` : ""}){" "}
                </Link>
              ))}
            </p>
          )}
        </div>
      </div>
      {can("methodology.edit") && (
        <div className="card top-gap">
          <h2 className="section-title">Change (with the reason; a new version)</h2>
          <div className="form-row">
            <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Field">
              <option value="guarantee_years">Guarantee (years)</option>
              <option value="why">Why we pick it</option>
              <option value="boq_description">BOQ text</option>
              <option value="measurement_rule">Measurement rule</option>
            </select>
            <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="New value" aria-label="Value" />
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why it changes" aria-label="Reason" />
            <button className="btn btn-primary" disabled={!value || reason.length < 3} onClick={save}>
              Save
            </button>
          </div>
          <ul className="small">
            {s.changes.map((c) => (
              <li key={c.version}>
                v{c.version}: {c.changes.map((x) => x.field).join(", ")} — {c.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

/** A client standard: the SOPs read, one rule per element and condition with its SOP link, the contradictions. */
export function StandardPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [s, setS] = useState<StandardDetail | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<StandardDetail>(`/api/methodology/standards/${id}`).then(setS, (e) => setError(errorText(e)));
  }, [id]);
  if (!s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const r = s.report;
  const sopLink = (doc: Rule["sop"], page: number | null) =>
    doc ? (
      can("methodology.compliance") ? (
        <button className="link-button" onClick={() => downloadFile(`/api/methodology/documents/${doc.id}/file`)}>
          {doc.sop_no ?? doc.file} rev {doc.revision} p.{page}
        </button>
      ) : (
        `${doc.sop_no ?? doc.file} rev ${doc.revision} p.${page}`
      )
    ) : (
      "—"
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to="/methodology">Methodology</Link> / client standard
          </p>
          <h1>{s.name}</h1>
          <p className="muted">
            {s.client_name} · from {s.source} · approved makes {s.approved_makes.join(", ")} · guarantee {s.guarantee_years ?? "—"} years
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value">
              {r.read}/{r.sops}
            </div>
            <div className="stat-label small muted">SOPs read</div>
          </div>
          <div className="stat">
            <div className="stat-value">{r.rules}</div>
            <div className="stat-label small muted">Rules</div>
          </div>
          <div className="stat text-danger">
            <div className="stat-value">{r.to_check}</div>
            <div className="stat-label small muted">To check</div>
          </div>
          <div className="stat">
            <div className="stat-value">{r.contradictions}</div>
            <div className="stat-label small muted">Contradictions</div>
          </div>
          <div className="stat">
            <div className="stat-value">
              {Object.entries(r.formats)
                .map(([k, v]) => `${v} ${k}`)
                .join(" · ")}
            </div>
            <div className="stat-label small muted">Formats</div>
          </div>
        </div>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Rules (one per element and condition)</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Element</th>
              <th>Condition</th>
              <th>Required system</th>
              <th>SOP</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {s.rules.map((rule) => (
              <Fragment key={rule.id}>
                <tr onClick={() => setOpen(open === rule.id ? null : rule.id)} className="clickable">
                  <td>{rule.element_label}</td>
                  <td className="small">{rule.condition_label ?? "all"}</td>
                  <td className="small">
                    <b>{rule.required_types.map((t) => `${t.label}${t.where ? ` (${t.where})` : ""}`).join(" + ")}</b>
                    <div className="muted">{(rule.system_text ?? "").slice(0, 140)}</div>
                  </td>
                  <td className="small">{sopLink(rule.sop, rule.page)}</td>
                  <td>
                    {rule.status === "to_check" ? <span className="badge badge-warn">to check</span> : <span className="badge badge-ok">ok</span>}
                    {rule.check_note && <div className="small muted">{rule.check_note.slice(0, 160)}</div>}
                  </td>
                </tr>
                {open === rule.id && (
                  <tr>
                    <td colSpan={5}>
                      <div className="grid-2 small">
                        <div>
                          <b>Minimum specs</b>
                          <ul>
                            {rule.min_specs.map((sp, i) => (
                              <li key={i}>
                                {sp.label}: {sp.required} {sp.standard ? `(${sp.standard})` : ""} {sp.material ? `— ${sp.material}` : ""} p.{sp.page}
                              </li>
                            ))}
                          </ul>
                          <b>Tests and hold points</b>
                          <ul>
                            {rule.tests.map((t, i) => (
                              <li key={i}>
                                {t.kind.replace("_", " ")} {t.hours ? `${t.hours} h` : ""} — {t.text.slice(0, 120)} p.{t.page}
                              </li>
                            ))}
                            {rule.hold_points.map((h, i) => (
                              <li key={`h${i}`}>Hold: {h.text}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <b>Makes</b>
                          <ul>
                            {rule.makes.map((m, i) => (
                              <li key={i}>
                                {m.brand} {m.product}: {m.status === "tpt" ? "approved as per TPT" : m.status.replace("_", " ")}
                              </li>
                            ))}
                          </ul>
                          <b>Checklist</b>
                          <ul>
                            {rule.checklist.map((c) => (
                              <li key={c.stage}>
                                {c.stage}: {c.items.length} items
                              </li>
                            ))}
                          </ul>
                          <b>Guarantee:</b> {rule.guarantee_years ?? s.guarantee_years ?? "—"} years
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Contradictions (for the pre-bid queries)</h2>
        <table className="table compact">
          <tbody>
            {s.contradictions.map((c) => (
              <tr key={c.id}>
                <td>{c.topic}</td>
                <td className="small">{c.sop_no}</td>
                <td className="small">{c.values.map((v) => `${v.value} (p.${v.page})`).join(" vs ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Documents read</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>SOP</th>
              <th>Rev</th>
              <th>Date</th>
              <th>Format</th>
              <th className="num">Pages</th>
              <th className="num">Rules</th>
              <th>File</th>
            </tr>
          </thead>
          <tbody>
            {s.documents.map((d) => (
              <tr key={d.id}>
                <td className="small">{d.sop_no ?? d.title}</td>
                <td className="small">{d.revision}</td>
                <td className="small">{d.date}</td>
                <td className="small">{d.format}</td>
                <td className="num">{d.pages}</td>
                <td className="num">{d.rules}</td>
                <td className="small">{d.file}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function fmt(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/** The methodology of a BOQ: per item the conditions, the client's rule, our system and why, the compliance, the steps. */
export function MethodologyPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [m, setM] = useState<MethodologyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();
  const only = params.get("show");
  const load = useCallback(() => api<MethodologyOut>(`/api/methodology/methodologies/${id}`).then(setM, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    load();
  }, [load]);
  const act = async (fn: () => Promise<MethodologyOut | unknown>) => {
    setBusy(true);
    try {
      const out = await fn();
      if (out && typeof out === "object" && "items" in (out as MethodologyOut)) setM(out as MethodologyOut);
      else await load();
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const editStep = (item: Item) => (stage: number, step: number) => {
    const text = window.prompt("The step", item.stages[stage].steps[step].text);
    if (text === null) return;
    const reason = window.prompt("Why it changes");
    if (!reason) return;
    act(() => api(`/api/methodology/items/${item.id}/steps`, { method: "POST", json: { stage, step, text, reason } }));
  };
  const perimeter = (item: Item) => {
    const v = window.prompt("The tank's real perimeter (m)");
    if (!v) return;
    const reason = window.prompt("Where it comes from");
    if (!reason) return;
    act(() => api(`/api/methodology/items/${item.id}/perimeter`, { method: "PUT", json: { perimeter_m: Number(v), reason } }));
  };
  const choose = (item: Item, choice: "approved" | "keep") => {
    const reason = choice === "keep" ? "Keep our make and ask the client to approve it before the bid (TPT)" : "Use a make on the client's approved list";
    act(() => api(`/api/methodology/items/${item.id}/make`, { method: "PUT", json: { choice, reason } }));
  };
  if (!m) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const showItems = !only || only === "items" || only === "compliance";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to="/methodology">Methodology</Link> / <code>{m.code}</code> · R{m.revision} · v{m.version}
            {m.tender_id && (
              <>
                {" · "}
                <Link to={`/tenders/${m.tender_id}`}>tender</Link>
              </>
            )}
          </p>
          <h1>{m.title}</h1>
          {m.compliance && (
            <p>
              <span className="badge badge-ok">{m.compliance.green} complies</span> <span className="badge badge-danger">{m.compliance.red} gaps</span>{" "}
              <span className="badge badge-warn">{m.compliance.confirm} to confirm</span>
            </p>
          )}
        </div>
        <div className="page-actions">
          <button className="btn" disabled={busy} onClick={() => act(() => api(`/api/methodology/methodologies/${m.id}/export`, { method: "POST", json: { audience: "client" } }))}>
            Export for the client (Word + PDF)
          </button>
          {can("methodology.compliance") && (
            <button
              className="btn"
              disabled={busy}
              onClick={() => act(() => api(`/api/methodology/methodologies/${m.id}/export`, { method: "POST", json: { audience: "internal" } }))}
            >
              Export internal
            </button>
          )}
          {can("methodology.compliance") && (
            <button className="btn" disabled={busy} onClick={() => act(() => api(`/api/methodology/methodologies/${m.id}/recheck`, { method: "POST" }))}>
              Check again
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {m.files.length > 0 && !only && (
        <div className="card">
          <h2 className="section-title">Files</h2>
          <p className="small">
            {m.files.map((f) => (
              <button key={f.id} className="link-button" onClick={() => downloadFile(`/api/methodology/files/${f.id}`)}>
                {f.file_name} ({f.audience}){" "}
              </button>
            ))}
          </p>
        </div>
      )}
      {showItems &&
        m.items.map((it, n) => (
          <div key={it.id} className="card top-gap">
            <h2 className="section-title">
              Item {n + 1}: {it.name}{" "}
              <span className="muted small">
                ({it.element_label}
                {it.qty ? ` · ${Number(it.qty).toLocaleString("en-IN")} ${it.unit ?? ""}` : ""})
              </span>
            </h2>
            {only !== "compliance" && (
              <div className="grid-2 small">
                <div>
                  <b>Conditions</b>
                  <ul>
                    {Object.entries(it.conditions).map(([k, v]) => (
                      <li key={k}>
                        {k.replace(/_/g, " ")}: <b>{fmt(v.value)}</b> <span className="muted">— {v.source}</span>
                      </li>
                    ))}
                    {it.missing.map((k) => (
                      <li key={k} className="text-danger">
                        {k.replace(/_/g, " ")}: to confirm
                      </li>
                    ))}
                    {it.places.length > 0 && <li>{it.places.length} place(s) from the drawings</li>}
                  </ul>
                  {it.rule_note && (
                    <p>
                      <b>Client rule:</b> {it.rule_note}
                    </p>
                  )}
                </div>
                <div>
                  <b>Our system (Option 1):</b> {it.system ? <Link to={`/methodology/systems/${it.system.id}`}>{it.system.name}</Link> : <span className="text-danger">none</span>}
                  <p>{it.reason}</p>
                  {it.options.length > 0 && (
                    <p>
                      <b>OR Option 2:</b>{" "}
                      {it.options.map((o) => (
                        <Link key={o.id} to={`/methodology/systems/${o.id}`}>
                          {o.name}
                        </Link>
                      ))}
                    </p>
                  )}
                </div>
              </div>
            )}
            {it.compliance && (
              <>
                <h3 className="section-title">
                  Compliance: {it.compliance.green} complies · {it.compliance.red} gaps · {it.compliance.confirm} to confirm
                </h3>
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Requirement</th>
                      <th>Client</th>
                      <th>Ours</th>
                      <th>Status</th>
                      <th>Gap / choice</th>
                    </tr>
                  </thead>
                  <tbody>
                    {it.compliance.rows.map((r, i) => (
                      <tr key={i}>
                        <td className="small">{r.topic}</td>
                        <td className="small">
                          {r.required}
                          {r.ref && <div className="muted">{r.ref}</div>}
                        </td>
                        <td className="small">{r.ours}</td>
                        <td>
                          <Badge s={r.status} />
                        </td>
                        <td className="small">
                          {r.gap}
                          {r.choices && (
                            <div>
                              {r.choices.map((c) => (
                                <div key={c.key}>
                                  <button
                                    className={`btn btn-small ${it.make_choice === c.key ? "btn-primary" : ""}`}
                                    disabled={busy || !can("methodology.edit")}
                                    onClick={() => choose(it, c.key as "approved" | "keep")}
                                  >
                                    {c.label}
                                  </button>{" "}
                                  <span className="muted">
                                    {c.options ? c.options.slice(0, 4).join("; ") : c.query}
                                    {c.note && <div className="small">{c.note}</div>}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {it.conditions.tank_perimeter_m && can("methodology.edit") && (
              <p className="small">
                Tank perimeter: {fmt(it.conditions.tank_perimeter_m.value)} m <span className="muted">({it.conditions.tank_perimeter_m.source})</span>{" "}
                <button className="btn btn-small" disabled={busy} onClick={() => perimeter(it)}>
                  Enter the real perimeter
                </button>
              </p>
            )}
            {only !== "compliance" && <Steps stages={it.stages} edit={can("methodology.edit") ? editStep(it) : undefined} />}
            {only !== "compliance" && it.edits.length > 0 && (
              <p className="small muted">Edits: {it.edits.map((e) => `v${e.version} ${e.stage.toLowerCase()}: ${e.reason}`).join("; ")}</p>
            )}
          </div>
        ))}
      {m.prebid && (!only || only === "prebid") && (
        <div className="card top-gap">
          <h2 className="section-title">Pre-bid queries ({m.prebid.length})</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>#</th>
                <th>Query</th>
                <th>Reference</th>
                <th>Kind</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {m.prebid.map((q, i) => (
                <tr key={q.id}>
                  <td className="num">{i + 1}</td>
                  <td className="small">{q.text}</td>
                  <td className="small">{q.reference}</td>
                  <td className="small">{q.kind}</td>
                  <td>
                    <select
                      value={q.status}
                      aria-label="Status"
                      disabled={busy}
                      onChange={(e) => act(() => api(`/api/methodology/prebid/${q.id}`, { method: "PUT", json: { status: e.target.value, answer: q.answer } }))}
                    >
                      <option value="open">open</option>
                      <option value="sent">sent</option>
                      <option value="answered">answered</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

type SiteOut = {
  site_id: number;
  methodology: { id: number; code: string; title: string } | null;
  items: {
    id: number;
    name: string;
    system: string | null;
    stage_template: { id: number; name: string; steps: { name: string; hold_point: boolean; checklist_template_id: number | null; weight: string }[] } | null;
  }[];
  pond_tests: { id: number; name: string; kind: string; required_hours: number; hours: number | null; result: string; photos: unknown[]; reference: string | null }[];
  material_tests: {
    id: number;
    product_name: string;
    tests: {
      property: string;
      standard: string | null;
      required: string;
      source?: string;
      page?: number | null;
      also?: { required: string; source: string }[];
      prebid_query_id?: number;
      note?: string;
    }[];
    frequency: string | null;
    status: string;
    reference: string | null;
  }[];
};

/** The site's methodology: the stage template per item (hold points block the next stage), the pond tests and the material tests. */
export function SiteMethodology() {
  const { id } = useParams();
  const [s, setS] = useState<SiteOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<SiteOut>(`/api/methodology/sites/${id}`).then(setS, (e) => setError(errorText(e)));
  }, [id]);
  if (!s) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      <div className="page-header">
        <div>
          <p className="small muted">
            <Link to={`/sites/${id}`}>Site</Link> / methodology
          </p>
          <h1>Methodology on site {s.methodology ? `— ${s.methodology.code}` : ""}</h1>
          <p className="muted">The stages from the won BOQ&apos;s methodology. A hold point must be inspected and certified before the next stage can start.</p>
        </div>
      </div>
      {s.items.map((it) => (
        <div key={it.id} className="card top-gap">
          <h2 className="section-title">
            {it.name} <span className="small muted">{it.system}</span>
          </h2>
          {it.stage_template && (
            <table className="table compact">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Stage</th>
                  <th className="num">Weight</th>
                  <th>Inspection</th>
                  <th>Hold point</th>
                </tr>
              </thead>
              <tbody>
                {it.stage_template.steps.map((st, i) => (
                  <tr key={st.name}>
                    <td className="num">{i + 1}</td>
                    <td>{st.name}</td>
                    <td className="num">{Number(st.weight).toFixed(0)}%</td>
                    <td className="small">{st.checklist_template_id ? "checklist form (Yes / No)" : ""}</td>
                    <td>{st.hold_point ? <span className="badge badge-danger">blocks the next stage until certified</span> : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
      <div className="card top-gap">
        <h2 className="section-title">Pond tests</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Test</th>
              <th className="num">Hours asked</th>
              <th className="num">Hours done</th>
              <th className="num">Photos</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {s.pond_tests.map((p) => (
              <tr key={p.id}>
                <td className="small">{p.name}</td>
                <td className="num">{p.required_hours}</td>
                <td className="num">{p.hours ?? "—"}</td>
                <td className="num">{p.photos.length}</td>
                <td>{p.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card top-gap">
        <h2 className="section-title">Material tests on deliveries</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Product</th>
              <th>Tests</th>
              <th>How often</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {s.material_tests.map((t) => (
              <tr key={t.id}>
                <td className="small">{t.product_name}</td>
                <td className="small">
                  {t.tests.length ? (
                    <table className="spec-lines">
                      <tbody>
                        {t.tests.map((x, i) => (
                          <tr key={i}>
                            <td>{x.property}</td>
                            <td>
                              <b>{x.required}</b>
                              {x.standard ? ` (${x.standard})` : ""}
                            </td>
                            <td className="muted">
                              {x.source ?? (x.page ? `p.${x.page}` : "")}
                              {(x.also ?? []).length > 0 && (
                                <div className="also-asked">
                                  also asked: {(x.also ?? []).map((a) => `${a.required} (${a.source})`).join("; ")}
                                  {x.prebid_query_id ? ` · pre-bid query #${x.prebid_query_id}` : ""}; the stricter is used
                                </div>
                              )}
                              {!x.also && x.note && <div className="also-asked">{x.note}</div>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    "test certificate"
                  )}
                </td>
                <td className="small">{t.frequency}</td>
                <td>{t.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
