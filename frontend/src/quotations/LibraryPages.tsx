// Settings › Quotation library: letterheads, letter templates, specification blocks, offer lines,
// offer items and references; each with a list, an editor, a preview and its version history
// (restore any version). Plus the quotation settings (follow-up days, closure targets, the Word
// template). Changing the library needs quotation.template.edit; old quotations keep their copy.
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";
import { loadLookups, MarkupField, plain, SectionsEditor, useLookups } from "./common";
import type { Lookups, Section } from "./common";
import { ART } from "../ui/tokens";
import { Button, Card, Field, FilePicker } from "../ui/components";

type Kind = "letterhead" | "letter" | "spec" | "line" | "item" | "reference" | "preset";
type Row = Record<string, unknown> & { id: number; version: number; needs_check: boolean; is_active: boolean; updated_at: string };
type Version = { version: number; action: string; note: string | null; by: string | null; at: string; data: Record<string, unknown> };

const TABS: { kind: Kind | "settings"; label: string }[] = [
  { kind: "preset", label: "Presets" },
  { kind: "item", label: "Offer items" },
  { kind: "spec", label: "Specifications" },
  { kind: "line", label: "Offer lines" },
  { kind: "letter", label: "Letters" },
  { kind: "letterhead", label: "Letterheads" },
  { kind: "reference", label: "References" },
  { kind: "settings", label: "Settings" },
];

function title(kind: Kind, r: Row): string {
  const v = (k: string) => String(r[k] ?? "");
  if (kind === "spec") return `${r.option_label ? `Opt.${v("option_label")} · ` : ""}${v("title")}`;
  if (kind === "line") return plain(v("description")).slice(0, 90);
  if (kind === "reference") return `${v("client_name")} · ${v("project")}`;
  if (kind === "preset") return `${v("name")} (${Array.isArray(r.items) ? r.items.length : 0} areas)`;
  return v("name");
}

export function QuotationLibrary() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Kind | "settings") ?? "item";
  return (
    <>
      <div className="page-header">
        <h1>Quotation library</h1>
        <p className="muted small">The text and rates offers are built from. Every change keeps a version; quotations already made keep their own copy.</p>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.kind} className={`tab ${tab === t.kind ? "active" : ""}`} onClick={() => setParams({ tab: t.kind })}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "settings" ? <SettingsPanel /> : <KindPanel key={tab} kind={tab} />}
    </>
  );
}

function KindPanel({ kind }: { kind: Kind }) {
  const { can } = useAuth();
  const edit = can("quotation.template.edit");
  const lookups = useLookups();
  const [rows, setRows] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [onlyCheck, setOnlyCheck] = useState(false);
  const [sel, setSel] = useState<Row | "new" | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    const qs = new URLSearchParams({ q });
    if (onlyCheck) qs.set("needs_check", "true");
    api<Row[]>(`/api/quotations/library/${kind}?${qs}`).then(setRows, (e) => setError(errorText(e)));
  }, [kind, q, onlyCheck]);
  useEffect(load, [load]);
  return (
    <div className="lib-layout">
      <Card as="div" className="lib-list">
        <div className="inline-form">
          <Field label="Search" bare>
            <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          <label className="check small">
            <input type="checkbox" checked={onlyCheck} onChange={(e) => setOnlyCheck(e.target.checked)} /> To check
          </label>
        </div>
        {edit && (
          <Button variant="primary" size="small" onClick={() => setSel("new")}>
            + New
          </Button>
        )}
        {kind === "reference" && edit && (
          <Button
            size="small"
            onClick={() =>
              void api<{ added: number }>("/api/quotations/library/reference/from-sites", { method: "POST" }).then(
                (r) => (setError(`${r.added} reference(s) added from completed sites`), load()),
                (e) => setError(errorText(e)),
              )
            }
          >
            Add from completed sites
          </Button>
        )}
        {error && <p className="small muted">{error}</p>}
        <ul className="lib-rows">
          {rows.map((r) => (
            <li key={r.id}>
              <button className={`outline-row ${sel !== "new" && sel?.id === r.id ? "on" : ""}`} onClick={() => setSel(r)}>
                {title(kind, r)} <span className="muted small">v{r.version}</span>
                {r.needs_check && <span className="badge badge-warn">imported, check</span>}
                {r.area_type_missing === true && <span className="badge badge-warn">area type missing</span>}
                {Array.isArray(r.checks) && r.checks.length > 0 && (
                  <span className="badge badge-orange" title={(r.checks as string[]).join("\n")}>
                    {r.checks.length} check{r.checks.length > 1 ? "s" : ""}
                  </span>
                )}
              </button>
            </li>
          ))}
          {rows.length === 0 && <li className="muted small">Nothing here yet.</li>}
        </ul>
      </Card>
      <div className="lib-detail">
        {sel && lookups ? (
          <Editor
            key={sel === "new" ? "new" : `${sel.id}-${sel.version}`}
            kind={kind}
            row={sel === "new" ? null : sel}
            lookups={lookups}
            edit={edit}
            onSaved={(r) => {
              setSel(r);
              load();
              void loadLookups(true);
            }}
          />
        ) : (
          <p className="muted">Pick a row to see it, its preview and its versions.</p>
        )}
      </div>
    </div>
  );
}

const BLANK: Record<Kind, Record<string, unknown>> = {
  letterhead: {
    name: "",
    company_name: "",
    signatory_firm: "",
    signatory_name: "",
    signatory_designation: "",
    signatory2_name: "",
    signatory2_designation: "",
    certificate_signatory: 1,
    brand: "",
    header_text: "",
    footer_text: "",
    primary_color: ART.letterheadPrimary,
    accent_color: ART.letterheadAccent,
  },
  letter: { name: "", opening: "", subject: "SUB: OFFER FOR {areas_list} WATERPROOFING WORK.", body: "", enclosures: "Technical Specification\nBudgetary Offer" },
  spec: { title: "", heading_prefix: "TECHNICAL SPECIFICATION FOR", option_label: "", area_type_id: null, sections: [] },
  line: { description: "", uom: "sqft", rate_source: "fixed", default_rate: "", if_required: false, client_scope: false },
  item: { name: "", budget_title: "", area_type_id: null, sort_order: 0, specs: [], lines: [] },
  reference: { client_name: "", project: "", application: "", area_value: "", area_unit: "SQFT", state: "", include: true, sort_order: 0 },
  preset: { name: "", letterhead_id: null, letter_template_id: null, tc_template_id: null, items: [], include_references: true },
};

function Editor({ kind, row, lookups, edit, onSaved }: { kind: Kind; row: Row | null; lookups: Lookups; edit: boolean; onSaved: (r: Row) => void }) {
  const [f, setF] = useState<Record<string, unknown>>(() => (row ? { ...row } : { ...BLANK[kind] }));
  const [versions, setVersions] = useState<Version[]>([]);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const ro = !edit;
  useEffect(() => {
    if (!row) return;
    void api<Version[]>(`/api/quotations/library/${kind}/${row.id}/versions`).then(setVersions);
    void api<{ html: string }>(`/api/quotations/library/${kind}/${row.id}/preview`).then((r) => setPreview(r.html));
  }, [kind, row]);
  const v = (k: string) => (f[k] ?? "") as string;
  const set = (k: string, val: unknown) => setF({ ...f, [k]: val });
  const input = (k: string, label: string, type = "text") => (
    <Field label={label}>
      <input type={type} value={v(k)} onChange={(e) => set(k, e.target.value)} disabled={ro} />
    </Field>
  );
  async function save() {
    setError("");
    const body = { ...f };
    for (const k of ["id", "version", "updated_at", "kind", "area_type_name", "created_at", "checks", "area_type_missing", "item_names"]) delete body[k];
    for (const k of ["default_rate", "area_value", "area_type_id", "system_id", "library_item_id", "tc_template_id", "letter_template_id"]) if (body[k] === "") body[k] = null;
    if (kind === "item") {
      body.specs = ((f.specs as { spec_block_id: number }[]) ?? []).map((s) => ({ spec_block_id: s.spec_block_id }));
      body.lines = ((f.lines as { offer_line_id: number; option: string | null }[]) ?? []).map((l) => ({ offer_line_id: l.offer_line_id, option: l.option || null }));
    }
    if (kind === "spec" && body.option_label === "") body.option_label = null;
    try {
      const r = await api<Row>(row ? `/api/quotations/library/${kind}/${row.id}` : `/api/quotations/library/${kind}`, { method: row ? "PUT" : "POST", json: body });
      setMsg(`Saved as version ${r.version}`);
      onSaved(r);
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function restore(version: number) {
    if (!row || !window.confirm(`Restore version ${version}? It becomes a new version; nothing is lost.`)) return;
    try {
      onSaved(await api<Row>(`/api/quotations/library/${kind}/${row.id}/restore/${version}`, { method: "POST" }));
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function upload(path: string, file: File, extra?: Record<string, string>) {
    const form = new FormData();
    form.append("file", file);
    for (const [k, val] of Object.entries(extra ?? {})) form.append(k, val);
    try {
      onSaved(await api<Row>(path, { method: "POST", form }));
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <div className="lib-editor">
      <Card as="div">
        <div className="toolbar">
          <h2 className="section-title">{row ? `${title(kind, row)} · version ${row.version}` : "New"}</h2>
          {row?.needs_check && edit && (
            <Button size="small" onClick={() => set("needs_check", false)}>
              Mark checked
            </Button>
          )}
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        {msg && <div className="alert alert-ok">{msg}</div>}
        {kind === "letterhead" && (
          <>
            <div className="form-grid two">
              {input("name", "Name (EESPL, Bronco …)")}
              {input("company_name", "Company name")}
              {input("signatory_firm", "Signatory firm line (For … PVT. LTD.)")}
              {input("brand", "Brand ({brand})")}
              {input("signatory_name", "Default signatory")}
              {input("signatory_designation", "Designation (printed under the name)")}
              {input("signatory2_name", "Second signatory (optional)")}
              {input("signatory2_designation", "Second signatory's designation")}
              <Field label="Signs the certificates (work completion, guarantee)">
                <select value={String(v("certificate_signatory") || 1)} onChange={(e) => set("certificate_signatory", Number(e.target.value))} disabled={ro}>
                  <option value="1">The default signatory</option>
                  <option value="2">The second signatory</option>
                </select>
              </Field>
              {input("primary_color", "Colour", "color")}
              {input("accent_color", "Accent colour", "color")}
              {input("references_state", "References from state")}
              <Field label="Letter template">
                <select value={v("letter_template_id")} onChange={(e) => set("letter_template_id", e.target.value ? Number(e.target.value) : null)} disabled={ro}>
                  <option value="">—</option>
                  {lookups.letters.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <MarkupField label="Header text" value={v("header_text")} onChange={(x) => set("header_text", x)} rows={2} disabled={ro} />
            <MarkupField label="Footer text" value={v("footer_text")} onChange={(x) => set("footer_text", x)} rows={2} disabled={ro} />
            <label className="check">
              <input type="checkbox" checked={!!f.preprinted} onChange={(e) => set("preprinted", e.target.checked)} disabled={ro} /> Pre-printed paper: leave the header and footer
              space blank (for printing on letterhead stationery)
            </label>
            {row &&
              (["logo", "header", "footer", "watermark"] as const).map((slot) => {
                const key = { logo: "logo_path", header: "header_image_path", footer: "footer_image_path", watermark: "watermark_path" }[slot];
                return (
                  <Field as="div" label={{ logo: "Logo", header: "Header band (full width)", footer: "Footer band (full width)", watermark: "Watermark (made faint)" }[slot]} key={slot}>
                    <Logo path={v(key)} />
                    {edit && (
                      <FilePicker
                        label="Choose the image"
                        accept="image/*"
                        onFiles={(fs) => fs[0] && void upload(`/api/quotations/library/letterhead/${row.id}/logo?slot=${slot}`, fs[0])}
                      />
                    )}
                  </Field>
                );
              })}
            <p className="muted small">The default T&amp;C set for this letterhead is a T&amp;C template (Masters › T&amp;C library); the applicator clause always names EESPL.</p>
          </>
        )}
        {kind === "letter" && (
          <>
            {input("name", "Name")}
            <MarkupField label="Opening" value={v("opening")} onChange={(x) => set("opening", x)} rows={5} placeholders={lookups.placeholders} disabled={ro} />
            <MarkupField label="Subject" value={v("subject")} onChange={(x) => set("subject", x)} rows={1} placeholders={lookups.placeholders} disabled={ro} />
            <MarkupField
              label="Body"
              value={v("body")}
              onChange={(x) => set("body", x)}
              rows={8}
              placeholders={lookups.placeholders}
              disabled={ro}
              hint="Unknown {placeholders} are refused on save."
            />
            <MarkupField label="Enclosures (one per line)" value={v("enclosures")} onChange={(x) => set("enclosures", x)} rows={2} disabled={ro} />
          </>
        )}
        {kind === "spec" && (
          <>
            <div className="form-grid two">
              {input("title", "Title (prints in capitals)")}
              {input("heading_prefix", "Heading prefix")}
              {input("option_label", "Option (empty: always)")}
              <Field label="Area type">
                <select value={v("area_type_id")} onChange={(e) => set("area_type_id", e.target.value ? Number(e.target.value) : null)} disabled={ro}>
                  <option value="">—</option>
                  {lookups.area_types.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <SectionsEditor sections={(f.sections as Section[]) ?? []} onChange={(s) => set("sections", s)} stages={lookups.stages} disabled={ro} />
            {((f.images as { path: string; caption: string }[]) ?? []).map((im, i) => (
              <figure key={i} className="lib-image">
                <Logo path={im.path} />
                <figcaption>{im.caption}</figcaption>
              </figure>
            ))}
            {row && edit && <ImageUpload onUpload={(file, caption) => void upload(`/api/quotations/library/spec/${row.id}/images`, file, { caption })} />}
          </>
        )}
        {kind === "line" && (
          <>
            <MarkupField label="Description" value={v("description")} onChange={(x) => set("description", x)} rows={5} disabled={ro} />
            <div className="form-grid four">
              <Field label="UoM">
                <select value={v("uom")} onChange={(e) => set("uom", e.target.value)} disabled={ro}>
                  {lookups.uoms.map((u) => (
                    <option key={u.code} value={u.code}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Rate from">
                <select value={v("rate_source")} onChange={(e) => set("rate_source", e.target.value)} disabled={ro}>
                  <option value="fixed">Fixed rate</option>
                  <option value="system">System build-up</option>
                  <option value="library">Rate library</option>
                </select>
              </Field>
              {input("default_rate", "Default rate (₹)")}
              {v("rate_source") === "system" && input("system_id", "System id")}
              {v("rate_source") === "library" && input("library_item_id", "Rate library item id")}
            </div>
            <label className="check inline">
              <input type="checkbox" checked={!!f.if_required} onChange={(e) => set("if_required", e.target.checked)} disabled={ro} /> If required
            </label>
            <label className="check inline">
              <input type="checkbox" checked={!!f.client_scope} onChange={(e) => set("client_scope", e.target.checked)} disabled={ro} /> Client's scope (prints in the rate column)
            </label>
          </>
        )}
        {kind === "item" && Array.isArray(f.checks) && (f.checks as string[]).length > 0 && (
          <div className="alert alert-warn checks">
            <b>Specification and budgetary offer do not agree</b> (warnings, not blocks):
            <ul>
              {(f.checks as string[]).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {kind === "item" && <ItemEditor f={f} set={set} lookups={lookups} ro={ro} />}
        {kind === "preset" && <PresetEditor f={f} set={set} lookups={lookups} ro={ro} />}
        {kind === "reference" && (
          <div className="form-grid two">
            {input("client_name", "Client")}
            {input("project", "Project")}
            {input("application", "Application method & area")}
            {input("state", "State")}
            {input("area_value", "Area covered")}
            {input("area_unit", "Unit (SQFT, SQMT, RMT)")}
            {input("sort_order", "Order", "number")}
            <label className="check">
              <input type="checkbox" checked={!!f.include} onChange={(e) => set("include", e.target.checked)} disabled={ro} /> Include in new quotations
            </label>
          </div>
        )}
        {edit && (
          <div className="panel-actions">
            <Button variant="primary" onClick={() => void save()}>
              {row ? "Save (new version)" : "Create"}
            </Button>
            {row && (
              <label className="check small">
                <input type="checkbox" checked={!!f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> Active
              </label>
            )}
          </div>
        )}
      </Card>
      {row && (
        <div className="lib-side">
          <Card as="div">
            <h3 className="section-title">Preview</h3>
            <iframe className="lib-preview" title="Preview" srcDoc={preview} sandbox="" />
          </Card>
          <Card as="div" className="versions">
            <h3 className="section-title">Version history</h3>
            <table className="table compact">
              <tbody>
                {versions.map((ver) => (
                  <tr key={ver.version}>
                    <td>v{ver.version}</td>
                    <td className="small">
                      {ver.action.replace("_", " ")}
                      {ver.note && <span className="muted"> · {ver.note}</span>}
                    </td>
                    <td className="small">
                      {ver.by ?? "import"} ·{" "}
                      {new Date(ver.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td>
                      {edit && ver.version !== row.version && (
                        <Button variant="ghost" size="small" onClick={() => void restore(ver.version)}>
                          Restore
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );
}

function ItemEditor({ f, set, lookups, ro }: { f: Record<string, unknown>; set: (k: string, v: unknown) => void; lookups: Lookups; ro: boolean }) {
  const specs = (f.specs as { spec_block_id: number; title?: string; option_label?: string | null }[]) ?? [];
  const lines = (f.lines as { offer_line_id: number; option: string | null; description?: string; uom?: string; default_rate?: string | null }[]) ?? [];
  const [allSpecs, setAllSpecs] = useState<Row[]>([]);
  const [allLines, setAllLines] = useState<Row[]>([]);
  useEffect(() => {
    void api<Row[]>("/api/quotations/library/spec").then(setAllSpecs);
    void api<Row[]>("/api/quotations/library/line").then(setAllLines);
  }, []);
  const v = (k: string) => (f[k] ?? "") as string;
  return (
    <>
      <div className="form-grid two">
        <Field label="Name">
          <input value={v("name")} onChange={(e) => set("name", e.target.value)} disabled={ro} />
        </Field>
        <Field label="Budgetary offer title">
          <input value={v("budget_title")} onChange={(e) => set("budget_title", e.target.value)} disabled={ro} />
        </Field>
        <Field label="Area type">
          <select value={v("area_type_id")} onChange={(e) => set("area_type_id", e.target.value ? Number(e.target.value) : null)} disabled={ro}>
            <option value="">—</option>
            {lookups.area_types.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Order">
          <input type="number" value={v("sort_order")} onChange={(e) => set("sort_order", Number(e.target.value))} disabled={ro} />
        </Field>
      </div>
      <h3 className="section-title">Specification blocks (options)</h3>
      {specs.map((s, i) => (
        <div key={i} className="inline-form">
          <span>
            {s.option_label ? `Opt.${s.option_label} · ` : ""}
            {s.title ?? `#${s.spec_block_id}`}
          </span>
          {!ro && (
            <Button
              variant="ghost" size="small"
              onClick={() =>
                set(
                  "specs",
                  specs.filter((_, j) => j !== i),
                )
              }
            >
              Remove
            </Button>
          )}
        </div>
      ))}
      {!ro && (
        <Field label="Add a spec" bare>
          <select
            value=""
            onChange={(e) => {
              const s = allSpecs.find((x) => String(x.id) === e.target.value);
              if (s) set("specs", [...specs, { spec_block_id: s.id, title: String(s.title), option_label: (s.option_label as string) ?? null }]);
            }}
          >
            <option value="">+ Add a specification block…</option>
            {allSpecs.map((s) => (
              <option key={s.id} value={s.id}>
                {title("spec", s)}
              </option>
            ))}
          </select>
        </Field>
      )}
      <h3 className="section-title top-gap">Offer lines</h3>
      {lines.map((l, i) => (
        <div key={i} className="inline-form">
          <Field label="Opt." bare>
            <input
              className="option-input"
              value={l.option ?? ""}
              placeholder="Opt."
              onChange={(e) =>
                set(
                  "lines",
                  lines.map((x, j) => (j === i ? { ...x, option: e.target.value || null } : x)),
                )
              }
              disabled={ro}
            />
          </Field>
          <span className="small">{plain(l.description ?? `#${l.offer_line_id}`).slice(0, 80)}</span>
          {!ro && (
            <Button
              variant="ghost" size="small"
              onClick={() =>
                set(
                  "lines",
                  lines.filter((_, j) => j !== i),
                )
              }
            >
              Remove
            </Button>
          )}
        </div>
      ))}
      {!ro && (
        <Field label="Add a line" bare>
          <select
            value=""
            onChange={(e) => {
              const l = allLines.find((x) => String(x.id) === e.target.value);
              if (l) set("lines", [...lines, { offer_line_id: l.id, option: null, description: String(l.description) }]);
            }}
          >
            <option value="">+ Add an offer line…</option>
            {allLines.map((l) => (
              <option key={l.id} value={l.id}>
                {title("line", l)}
              </option>
            ))}
          </select>
        </Field>
      )}
    </>
  );
}

function Logo({ path }: { path: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let gone = false;
    void fetchObjectUrl(`/api/quotations/media?path=${encodeURIComponent(path)}`).then((u) => !gone && setUrl(u));
    return () => {
      gone = true;
    };
  }, [path]);
  return url ? <img className="lib-logo" src={url} alt="" /> : null;
}

function ImageUpload({ onUpload }: { onUpload: (file: File, caption: string) => void }) {
  const [caption, setCaption] = useState("");
  return (
    <div className="inline-form">
      <Field label="Caption" bare>
        <input placeholder="Caption" value={caption} onChange={(e) => setCaption(e.target.value)} />
      </Field>
      <FilePicker label="Choose the image" accept="image/*" onFiles={(fs) => fs[0] && onUpload(fs[0], caption)} />
    </div>
  );
}

type Settings = {
  default_validity_days: number;
  followup_days: number[];
  closure_target_percent: string;
  closure_targets: Record<string, string>;
  default_letterhead_id: number | null;
  word_template: string;
};

function SettingsPanel() {
  const { can } = useAuth();
  const edit = can("quotation.template.edit");
  const lookups = useLookups();
  const [s, setS] = useState<Settings | null>(null);
  const [days, setDays] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    void api<Settings>("/api/quotations/settings").then((r) => (setS(r), setDays(r.followup_days.join(", "))));
  }, []);
  if (!s || !lookups) return <p className="muted">Loading…</p>;
  async function save() {
    try {
      const r = await api<Settings>("/api/quotations/settings", {
        method: "PUT",
        json: {
          default_validity_days: s!.default_validity_days,
          followup_days: days.split(/[ ,]+/).filter(Boolean).map(Number),
          closure_target_percent: s!.closure_target_percent,
          closure_targets: s!.closure_targets,
          default_letterhead_id: s!.default_letterhead_id,
        },
      });
      setS(r);
      setError("");
      setMsg("Saved.");
    } catch (e) {
      setMsg("");
      setError(errorText(e));
    }
  }
  async function uploadTemplate(file: File) {
    const form = new FormData();
    form.append("file", file);
    try {
      setS(await api<Settings>("/api/quotations/settings/word-template", { method: "POST", form }));
      setError("");
      setMsg("The new Word template is used for every quotation from now on.");
    } catch (e) {
      setMsg("");
      setError(errorText(e));
    }
  }
  return (
    <Card as="div" className="settings-card">
      {msg && <div className="alert alert-ok">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-grid two">
        <Field label="Validity (days, default)">
          <input type="number" value={s.default_validity_days} onChange={(e) => setS({ ...s, default_validity_days: Number(e.target.value) })} disabled={!edit} />
        </Field>
        <Field label="Follow-up days after sending">
          <input value={days} onChange={(e) => setDays(e.target.value)} disabled={!edit} />
        </Field>
        <Field label="Closure target (%), everyone">
          <input type="number" value={s.closure_target_percent} onChange={(e) => setS({ ...s, closure_target_percent: e.target.value })} disabled={!edit} />
        </Field>
        <Field label="Default letterhead">
          <select value={s.default_letterhead_id ?? ""} onChange={(e) => setS({ ...s, default_letterhead_id: e.target.value ? Number(e.target.value) : null })} disabled={!edit}>
            {lookups.letterheads.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <h3 className="section-title">Closure target per salesperson</h3>
      <div className="form-grid four">
        {lookups.salespeople.map((p) => (
          <Field label={p.full_name} key={p.id}>
            <input
              type="number"
              placeholder={String(Number(s.closure_target_percent))}
              value={s.closure_targets[p.id] ?? ""}
              onChange={(e) => {
                const next = { ...s.closure_targets };
                if (e.target.value) next[p.id] = e.target.value;
                else delete next[p.id];
                setS({ ...s, closure_targets: next });
              }}
              disabled={!edit}
            />
          </Field>
        ))}
      </div>
      {edit && (
        <Button variant="primary" onClick={() => void save()}>
          Save settings
        </Button>
      )}
      <h3 className="section-title top-gap">Word template</h3>
      <p className="small muted">
        Using the {s.word_template} template. Download it, restyle the “Offer …” styles in Word (fonts, sizes, colours, spacing) and upload it back; the content still comes from
        the quotation.
      </p>
      <div className="inline-form">
        <Button size="small" onClick={() => void downloadFile("/api/quotations/settings/word-template")}>
          ⤓ Template
        </Button>
        {edit && <FilePicker label="Upload a Word template" size="small" accept=".docx" onFiles={(fs) => fs[0] && void uploadTemplate(fs[0])} />}
        {edit && s.word_template === "uploaded" && (
          <Button variant="ghost" size="small" onClick={() => void api<Settings>("/api/quotations/settings/word-template", { method: "DELETE" }).then(setS)}>
            Back to the built-in one
          </Button>
        )}
      </div>
    </Card>
  );
}

function PresetEditor({ f, set, lookups, ro }: { f: Record<string, unknown>; set: (k: string, v: unknown) => void; lookups: Lookups; ro: boolean }) {
  const items = (f.items as { offer_item_id: number; options: string[] }[]) ?? [];
  const name = (id: number) => lookups.offer_items.find((i) => i.id === id)?.name ?? `#${id}`;
  const move = (i: number, d: number) => {
    const next = [...items];
    const [x] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, x);
    set("items", next);
  };
  const v = (k: string) => (f[k] ?? "") as string;
  return (
    <>
      <div className="form-grid two">
        <Field label="Name">
          <input value={v("name")} onChange={(e) => set("name", e.target.value)} disabled={ro} placeholder="Bungalow - EESPL" />
        </Field>
        <Field label="Letterhead">
          <select value={v("letterhead_id")} onChange={(e) => set("letterhead_id", e.target.value ? Number(e.target.value) : null)} disabled={ro}>
            <option value="">—</option>
            {lookups.letterheads.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Letter template">
          <select value={v("letter_template_id")} onChange={(e) => set("letter_template_id", e.target.value ? Number(e.target.value) : null)} disabled={ro}>
            <option value="">The letterhead's</option>
            {lookups.letters.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="T&amp;C template id (empty: the letterhead's)">
          <input value={v("tc_template_id")} onChange={(e) => set("tc_template_id", e.target.value ? Number(e.target.value) : null)} disabled={ro} />
        </Field>
      </div>
      <label className="check">
        <input type="checkbox" checked={!!f.include_references} onChange={(e) => set("include_references", e.target.checked)} disabled={ro} /> Include "Our esteemed clients"
      </label>
      <h3 className="section-title top-gap">Areas, in order</h3>
      {items.map((it, i) => (
        <div key={i} className="inline-form">
          <span>
            {i + 1}. {name(it.offer_item_id)}
            {it.options?.length ? ` · Opt.${it.options.join(", ")}` : ""}
          </span>
          {!ro && (
            <>
              <Button variant="ghost" size="small" onClick={() => move(i, -1)} aria-label="Up">
                ↑
              </Button>
              <Button variant="ghost" size="small" onClick={() => move(i, 1)} aria-label="Down">
                ↓
              </Button>
              <Button
                variant="ghost" size="small"
                onClick={() =>
                  set(
                    "items",
                    items.filter((_, j) => j !== i),
                  )
                }
              >
                Remove
              </Button>
            </>
          )}
        </div>
      ))}
      {!ro && (
        <Field label="Add an area" bare>
          <select value="" onChange={(e) => e.target.value && set("items", [...items, { offer_item_id: Number(e.target.value), options: [] }])}>
            <option value="">+ Add an area…</option>
            {lookups.offer_items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        </Field>
      )}
    </>
  );
}
