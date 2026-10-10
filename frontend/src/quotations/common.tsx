// Shared pieces of the quotation editor and the quotation library: types, the markup text field
// (**bold** product names, ==highlight== notes, {placeholders}) and the stage / steps editor.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export type Step = { text: string; client_scope: boolean; if_required: boolean };
export type Section = { heading: string; option: string | null; steps: Step[] };
export type SpecCopy = {
  spec_block_id: number | null;
  version?: number;
  title: string;
  heading_prefix: string;
  option_label: string | null;
  sections: Section[];
  images: { path: string; caption: string }[];
};
export type QLine = {
  id: number;
  offer_line_id: number | null;
  library_version: number | null;
  sort_order: number;
  option: string | null;
  offered: boolean;
  description: string;
  uom: string;
  rate: string | null;
  rate_source: string | null;
  rate_note: string | null;
  overridden: boolean;
  qty: string | null;
  amount: string | null;
  if_required: boolean;
  client_scope: boolean;
  cost_rate?: string | null;
  margin_percent?: string | null;
  margin_amount?: string | null;
};
export type QItem = {
  id: number;
  checks: string[];
  offer_item_id: number | null;
  sort_order: number;
  name: string;
  budget_title: string;
  area_type_id: number | null;
  options: string[];
  option_labels: string[];
  specs: SpecCopy[];
  lines: QLine[];
  total: string | null;
};
export type Term = { category: string; text: string; clause_id?: number | null };
export type Ref = {
  id?: number;
  client_name: string;
  project: string;
  application: string;
  area_value: string | number | null;
  area_unit: string | null;
  state: string | null;
  include: boolean;
  sort_order?: number;
};
export type FollowUp = { id: number; day: number; due_on: string; overdue: boolean; status: string; note: string | null; code: string };
export type QFile = {
  id: number;
  kind: "docx" | "pdf";
  file_name: string;
  size_bytes: number;
  created_at: string;
  replaced: boolean;
  replaced_at: string | null;
  by: string | null;
};
export type Quotation = {
  id: number;
  code: string;
  revision: number;
  is_latest: boolean;
  previous_id: number | null;
  lead_id: number | null;
  lead_code: string | null;
  client_id: number | null;
  survey_id: number | null;
  tender_id: number | null;
  site_id: number | null;
  letterhead_id: number | null;
  letterhead_name: string | null;
  salesperson_id: string | null;
  salesperson_name: string | null;
  client_firm: string;
  client_city: string | null;
  client_state: string | null;
  attention: string | null;
  project: string;
  brand: string | null;
  areas_list: string | null;
  areas_list_auto: string;
  quote_date: string;
  valid_until: string;
  validity_days: number;
  guarantee_years?: number | null;
  status: "draft" | "sent" | "negotiation" | "won" | "lost" | "expired";
  lost_reason: string | null;
  lost_note: string | null;
  show_amounts: boolean;
  letter_template_id: number | null;
  opening: string;
  subject: string;
  body: string;
  enclosures: string;
  signatory_name: string | null;
  signatory_designation: string | null;
  terms: Term[];
  references: Ref[];
  references_title: string | null;
  notes: string | null;
  items: QItem[];
  total: string;
  total_option_note: boolean;
  revisions: { id: number; revision: number; status: string; quote_date: string }[];
  files: QFile[];
  followups: FollowUp[];
  can_edit: boolean;
  can_send: boolean;
  can_template_edit: boolean;
  can_margin: boolean;
};
export type Lookups = {
  letterheads: { id: number; name: string; company_name: string }[];
  letters: { id: number; name: string }[];
  offer_items: { id: number; name: string; area_type_id: number | null; option_labels: string[]; needs_check: boolean; lines: number; specs: number }[];
  presets: { id: number; name: string; items: number }[];
  lost_reasons: string[];
  uoms: { code: string; label: string }[];
  rate_sources: string[];
  stages: string[];
  placeholders: string[];
  tc_groups: Record<string, string>;
  salespeople: { id: string; full_name: string; job_title: string | null }[];
  area_types: { id: number; name: string }[];
  default_validity_days: number;
  default_letterhead_id: number | null;
  me: string;
};

export const STATUS_BADGE: Record<string, string> = {
  draft: "badge-muted",
  sent: "badge-info",
  negotiation: "badge-warn",
  won: "badge-ok",
  lost: "badge-danger",
  expired: "badge-muted",
};

let lookupsCache: Promise<Lookups> | null = null;
export function loadLookups(fresh = false): Promise<Lookups> {
  if (!lookupsCache || fresh) lookupsCache = api<Lookups>("/api/quotations/lookups");
  return lookupsCache;
}

export function useLookups(): Lookups | null {
  const [l, setL] = useState<Lookups | null>(null);
  useEffect(() => {
    void loadLookups().then(setL, () => setL(null));
  }, []);
  return l;
}

/** Markup -> plain text (for lists). */
export function plain(text: string): string {
  return (text ?? "")
    .replace(/\*\*|==/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Markup -> React nodes (**bold**, ==highlight==). */
export function Markup({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  let bold = false;
  let mark = false;
  (text ?? "").split(/(\*\*|==)/).forEach((part, i) => {
    if (part === "**") bold = !bold;
    else if (part === "==") mark = !mark;
    else if (part) {
      let node: React.ReactNode = part;
      if (mark) node = <mark key={`m${i}`}>{node}</mark>;
      if (bold) node = <b key={`b${i}`}>{node}</b>;
      out.push(<span key={i}>{node}</span>);
    }
  });
  return <>{out}</>;
}

/** A text area for library / offer text with Bold, Highlight, a product picker (product names
 * come from the products master and print bold) and, for letters, placeholder chips. */
export function MarkupField({
  label,
  value,
  onChange,
  rows = 3,
  placeholders,
  disabled,
  hint,
  compact,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholders?: string[];
  disabled?: boolean;
  hint?: string;
  compact?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [picking, setPicking] = useState(false);
  /** Wrap the selected text in the marks (spaces at its ends stay outside); the wrapped text
   * stays selected. With nothing selected, the word under the cursor is wrapped. */
  function wrap(mark: string) {
    const el = ref.current;
    if (!el) return;
    let { selectionStart: a, selectionEnd: b } = el;
    if (a === b) {
      while (a > 0 && /\S/.test(value[a - 1])) a -= 1;
      while (b < value.length && /\S/.test(value[b])) b += 1;
    }
    while (a < b && /\s/.test(value[a])) a += 1;
    while (b > a && /\s/.test(value[b - 1])) b -= 1;
    if (a === b) return;
    const sel = value.slice(a, b);
    const already = sel.startsWith(mark) && sel.endsWith(mark) && sel.length > 2 * mark.length;
    const next = already ? sel.slice(mark.length, -mark.length) : mark + sel + mark;
    onChange(value.slice(0, a) + next + value.slice(b));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(a, a + next.length);
    });
  }
  function insert(text: string) {
    const el = ref.current;
    const at = el ? el.selectionStart : value.length;
    onChange(value.slice(0, at) + text + value.slice(at));
  }
  return (
    <div className={`field markup-field ${compact ? "compact" : ""}`}>
      {label && <span>{label}</span>}
      {!disabled && (
        <div className="markup-tools">
          {/* onMouseDown: keep the text box's selection while the button is pressed */}
          <button
            type="button"
            className="btn btn-small btn-ghost"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => wrap("**")}
            title="Bold the selected text (product names)"
          >
            <b>B</b>
          </button>
          <button type="button" className="btn btn-small btn-ghost" onMouseDown={(e) => e.preventDefault()} onClick={() => wrap("==")} title="Highlight the selected text (notes)">
            <mark>H</mark>
          </button>
          {!compact && (
            <button type="button" className="btn btn-small btn-ghost" onClick={() => setPicking(!picking)}>
              + Product
            </button>
          )}
          {placeholders?.map((p) => (
            <button key={p} type="button" className="chip" onClick={() => insert(`{${p}}`)}>
              {`{${p}}`}
            </button>
          ))}
        </div>
      )}
      {picking && <ProductPicker onPick={(name) => (insert(`**${name}**`), setPicking(false))} />}
      <textarea ref={ref} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} />
      {/^.*(\*\*|==)/s.test(value) && (
        <div className="markup-preview" aria-label="As it will print">
          <span className="muted small">Prints as:</span>
          {value.split("\n").map((line, i) => (
            <p key={i}>
              <Markup text={line} />
            </p>
          ))}
        </div>
      )}
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}

export function ProductPicker({ onPick }: { onPick: (name: string) => void }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<{ id: number; code: string; name: string }[]>([]);
  useEffect(() => {
    const t = setTimeout(() => void api<typeof rows>(`/api/quotations/products?q=${encodeURIComponent(q)}`).then(setRows, () => setRows([])), 200);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="product-picker">
      <input autoFocus placeholder="Search the products master" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="product-list">
        {rows.map((r) => (
          <button key={r.id} type="button" className="btn btn-small btn-ghost" onClick={() => onPick(r.name)}>
            {r.name} <span className="muted small">{r.code}</span>
          </button>
        ))}
        {rows.length === 0 && <span className="muted small">No product found.</span>}
      </div>
    </div>
  );
}

/** Stage sections, each a numbered list of steps (client's scope / if required ticks). */
export function SectionsEditor({ sections, onChange, stages, disabled }: { sections: Section[]; onChange: (s: Section[]) => void; stages: string[]; disabled?: boolean }) {
  const set = (i: number, s: Partial<Section>) => onChange(sections.map((x, j) => (j === i ? { ...x, ...s } : x)));
  const setStep = (i: number, k: number, st: Partial<Step>) => set(i, { steps: sections[i].steps.map((x, j) => (j === k ? { ...x, ...st } : x)) });
  const move = (i: number, d: number) => {
    const next = [...sections];
    const [s] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, s);
    onChange(next);
  };
  let n = 0;
  return (
    <div className="sections-editor">
      {sections.map((s, i) => (
        <div key={i} className="section-box">
          <div className="inline-form">
            <input list="stage-names" value={s.heading} placeholder="Stage (e.g. Surface preparation)" onChange={(e) => set(i, { heading: e.target.value })} disabled={disabled} />
            <input
              className="option-input"
              value={s.option ?? ""}
              placeholder="Option"
              title="An option number makes this section an alternative (OR)"
              onChange={(e) => set(i, { option: e.target.value || null })}
              disabled={disabled}
            />
            {!disabled && (
              <>
                <button type="button" className="btn btn-small btn-ghost" onClick={() => move(i, -1)} aria-label="Up">
                  ↑
                </button>
                <button type="button" className="btn btn-small btn-ghost" onClick={() => move(i, 1)} aria-label="Down">
                  ↓
                </button>
                <button type="button" className="btn btn-small btn-ghost" onClick={() => onChange(sections.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </>
            )}
          </div>
          {s.steps.map((st, k) => {
            n += 1;
            return (
              <div key={k} className="step-row">
                <span className="step-n">{n}.</span>
                <MarkupField label="" compact rows={2} value={st.text} onChange={(v) => setStep(i, k, { text: v })} disabled={disabled} />
                <div className="step-flags">
                  <label className="check small">
                    <input type="checkbox" checked={st.client_scope} onChange={(e) => setStep(i, k, { client_scope: e.target.checked })} disabled={disabled} /> Client's scope
                  </label>
                  <label className="check small">
                    <input type="checkbox" checked={st.if_required} onChange={(e) => setStep(i, k, { if_required: e.target.checked })} disabled={disabled} /> If required
                  </label>
                  {!disabled && (
                    <button type="button" className="btn btn-small btn-ghost" onClick={() => set(i, { steps: s.steps.filter((_, j) => j !== k) })}>
                      ✕
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {!disabled && (
            <button type="button" className="btn btn-small btn-ghost" onClick={() => set(i, { steps: [...s.steps, { text: "", client_scope: false, if_required: false }] })}>
              + Step
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button
          type="button"
          className="btn btn-small"
          onClick={() => onChange([...sections, { heading: "", option: null, steps: [{ text: "", client_scope: false, if_required: false }] }])}
        >
          + Stage section
        </button>
      )}
      <datalist id="stage-names">
        {stages.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <small className="muted">Steps are numbered right through the block. Product names in **bold**.</small>
    </div>
  );
}

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
