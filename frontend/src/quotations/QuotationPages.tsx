// Quotations: the list, a new quotation (from a lead, a client or blank) and the editor: the
// outline on the left, the live preview in the centre, the selected block's fields on the right.
// On a phone the editor is a read-only preview with "Share PDF".
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import { loadLookups, MarkupField, money, plain, SectionsEditor, STATUS_BADGE, useLookups } from "./common";
import type { Lookups, QItem, QLine, Quotation, Ref, SpecCopy, Term } from "./common";

type Row = {
  id: number;
  code: string;
  revision: number;
  client_firm: string;
  project: string;
  client_city: string | null;
  status: string;
  quote_date: string;
  valid_until: string;
  salesperson: string | null;
  items: number;
  total: string | null;
  lead_id: number | null;
};

const fmtDate = (d: string | null | undefined) => (d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—");

function usePhone(): boolean {
  const q = "(max-width: 760px)";
  const [phone, setPhone] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setPhone(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return phone;
}

// --- the list ------------------------------------------------------------------------------------

export function QuotationsList() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(params.get("new") === "1");
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  useEffect(() => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (q) qs.set("q", q);
    if (params.get("lead_id")) qs.set("lead_id", params.get("lead_id")!);
    api<Row[]>(`/api/quotations?${qs}`).then(setRows, (e) => setError(errorText(e)));
  }, [status, q, params]);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  return (
    <>
      <div className="page-header">
        <h1>Quotations</h1>
        <div className="page-actions">
          <form onSubmit={(e) => e.preventDefault()}>
            <input className="search" placeholder="Search code, client or project" defaultValue={q} onChange={(e) => set("q", e.target.value)} />
          </form>
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All statuses</option>
            {["draft", "sent", "negotiation", "won", "lost", "expired"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {can("quotation.edit") && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New quotation
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">No quotations yet. About 90 % of the work starts here: make one from a lead, a client or blank.</p>
      ) : (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Quotation</th>
                <th>Client · project</th>
                <th>Status</th>
                <th>Date</th>
                <th>Valid until</th>
                <th>Salesperson</th>
                <th className="num">Items</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/quotations/${r.id}`}>
                      {r.code} R{r.revision}
                    </Link>
                  </td>
                  <td>
                    {r.client_firm} <span className="muted small">· {r.project}</span>
                  </td>
                  <td>
                    <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                  </td>
                  <td>{fmtDate(r.quote_date)}</td>
                  <td>{fmtDate(r.valid_until)}</td>
                  <td>{r.salesperson ?? "—"}</td>
                  <td className="num">{r.items}</td>
                  <td className="num">{r.total ? `₹ ${money(r.total)}` : "rates only"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewQuotation leadId={params.get("lead_id")} clientId={params.get("client_id")} onClose={() => setCreating(false)} />}
    </>
  );
}

// --- a new quotation -----------------------------------------------------------------------------

function NewQuotation({ leadId, clientId, onClose }: { leadId: string | null; clientId: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const lookups = useLookups();
  const [from, setFrom] = useState<"lead" | "client" | "blank">(leadId ? "lead" : clientId ? "client" : "blank");
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<{ id: number; label: string }[]>([]);
  const [parent, setParent] = useState<string>(leadId ?? clientId ?? "");
  const [form, setForm] = useState({ client_firm: "", client_city: "", attention: "", project: "", letterhead_id: "" });
  const [picked, setPicked] = useState<Record<number, string[] | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (from === "blank") return;
    const path = from === "lead" ? "/api/leads" : "/api/clients";
    const t = setTimeout(() => {
      api<{ items: { id: number; code?: string; name?: string; contact_name?: string; company?: string | null }[] }>(`${path}?limit=25&q=${encodeURIComponent(search)}`).then(
        (r) => setOptions(r.items.map((x) => ({ id: x.id, label: from === "lead" ? `${x.code} · ${x.company || x.contact_name}` : (x.name ?? "") }))),
        () => setOptions([]),
      );
    }, 200);
    return () => clearTimeout(t);
  }, [from, search]);
  useEffect(() => {
    if (lookups && !form.letterhead_id && lookups.default_letterhead_id) setForm((f) => ({ ...f, letterhead_id: String(lookups.default_letterhead_id) }));
  }, [lookups, form.letterhead_id]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const items = Object.entries(picked)
        .filter(([, v]) => v !== null)
        .map(([id, opts]) => ({ offer_item_id: Number(id), options: opts ?? [] }));
      const q = await api<Quotation>("/api/quotations", {
        method: "POST",
        json: {
          ...(from === "lead" && parent ? { lead_id: Number(parent) } : {}),
          ...(from === "client" && parent ? { client_id: Number(parent) } : {}),
          client_firm: form.client_firm || undefined,
          client_city: form.client_city || undefined,
          attention: form.attention || undefined,
          project: form.project || undefined,
          letterhead_id: form.letterhead_id ? Number(form.letterhead_id) : undefined,
          items,
        },
      });
      navigate(`/quotations/${q.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  const toggle = (id: number, all: string[]) => setPicked((p) => ({ ...p, [id]: p[id] === undefined || p[id] === null ? all : null }));
  return (
    <Modal title="New quotation" onClose={onClose} wide>
      <form onSubmit={(e) => void submit(e)}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="tabs" role="tablist">
          {(["lead", "client", "blank"] as const).map((k) => (
            <button key={k} type="button" className={`tab ${from === k ? "active" : ""}`} onClick={() => (setFrom(k), setParent(""))}>
              {k === "lead" ? "From a lead" : k === "client" ? "From a client" : "Blank"}
            </button>
          ))}
        </div>
        {from !== "blank" && (
          <div className="form-grid">
            <label className="field">
              <span>Search {from === "lead" ? "leads" : "clients"}</span>
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or code" />
            </label>
            <label className="field">
              <span>{from === "lead" ? "Lead" : "Client"}</span>
              <select value={parent} onChange={(e) => setParent(e.target.value)} required>
                <option value="">Choose…</option>
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
                {parent && !options.some((o) => String(o.id) === parent) && <option value={parent}>#{parent}</option>}
              </select>
            </label>
          </div>
        )}
        <div className="form-grid">
          <label className="field">
            <span>Client firm {from !== "blank" && <em className="muted">(empty: from the {from})</em>}</span>
            <input value={form.client_firm} onChange={(e) => setForm({ ...form, client_firm: e.target.value })} required={from === "blank"} />
          </label>
          <label className="field">
            <span>Project</span>
            <input value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} required={from === "blank"} />
          </label>
          <label className="field">
            <span>City</span>
            <input value={form.client_city} onChange={(e) => setForm({ ...form, client_city: e.target.value })} />
          </label>
          <label className="field">
            <span>Kind attention</span>
            <input value={form.attention} onChange={(e) => setForm({ ...form, attention: e.target.value })} />
          </label>
          <label className="field">
            <span>Letterhead</span>
            <select value={form.letterhead_id} onChange={(e) => setForm({ ...form, letterhead_id: e.target.value })}>
              {lookups?.letterheads.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name} — {h.company_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <h3 className="section-title">Areas to offer</h3>
        <div className="item-picker">
          {lookups?.offer_items.map((it) => {
            const sel = picked[it.id];
            return (
              <div key={it.id} className={`item-pick ${sel ? "on" : ""}`}>
                <label className="check">
                  <input type="checkbox" checked={!!sel} onChange={() => toggle(it.id, it.option_labels)} /> <b>{it.name}</b>
                  {it.needs_check && <span className="badge badge-warn">imported, check</span>}
                </label>
                {sel && it.option_labels.length > 1 && (
                  <div className="small">
                    Offer options:{" "}
                    {it.option_labels.map((o) => (
                      <label key={o} className="check inline">
                        <input
                          type="checkbox"
                          checked={sel.includes(o)}
                          onChange={(e) => setPicked((p) => ({ ...p, [it.id]: e.target.checked ? [...sel, o].sort() : sel.filter((x) => x !== o) }))}
                        />{" "}
                        Opt.{o}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {lookups && lookups.offer_items.length === 0 && <p className="muted">The library has no offer items yet (Settings › Quotation library).</p>}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "Building…" : "Build the quotation"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- the editor ----------------------------------------------------------------------------------

type Sel = { kind: "letter" } | { kind: "item"; id: number } | { kind: "terms" } | { kind: "refs" } | { kind: "follow" };

export function QuotationEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const phone = usePhone();
  const lookups = useLookups();
  const [q, setQ] = useState<Quotation | null>(null);
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [sel, setSel] = useState<Sel>({ kind: "letter" });
  const [dialog, setDialog] = useState<null | "won" | "lost" | "diff" | "survey" | "add">(null);
  const refreshPreview = useCallback(() => {
    api<{ html: string }>(`/api/quotations/${id}/preview`).then(
      (r) => setHtml(r.html),
      (e) => setError(errorText(e)),
    );
  }, [id]);
  useEffect(() => {
    setQ(null);
    api<Quotation>(`/api/quotations/${id}`).then(setQ, (e) => setError(errorText(e)));
    refreshPreview();
  }, [id, refreshPreview]);
  const apply = useCallback(
    async (path: string, json?: unknown, method = "POST", done?: string) => {
      setError("");
      try {
        const r = await api<Quotation & { result?: Record<string, string>; saved_back?: { kind: string; version: number } }>(path, { method, json });
        setQ(r);
        refreshPreview();
        if (r.saved_back) setNote(`Saved into the library as version ${r.saved_back.version} (older quotations keep their copy).`);
        else if (done) setNote(done);
        return r;
      } catch (e) {
        setError(errorText(e));
        return null;
      }
    },
    [refreshPreview],
  );
  if (error && !q) return <div className="alert alert-error">{error}</div>;
  if (!q || !lookups) return <p className="muted">Loading…</p>;
  const base = `/api/quotations/${q.id}`;
  const header = (
    <div className="page-header q-header">
      <div>
        <div className="breadcrumb">
          <Link to="/quotations">Quotations</Link>
          {q.lead_id && (
            <>
              {" "}
              / <Link to={`/leads/${q.lead_id}`}>{q.lead_code}</Link>
            </>
          )}
        </div>
        <h1>
          {q.code} <span className="muted">R{q.revision}</span> <span className={`badge ${STATUS_BADGE[q.status]}`}>{q.status}</span>
        </h1>
        <p className="muted small">
          {q.client_firm} · {q.project} · {fmtDate(q.quote_date)} · valid until {fmtDate(q.valid_until)} · {q.letterhead_name ?? "no letterhead"} · {q.salesperson_name ?? "—"}
          {q.lost_reason && ` · lost: ${q.lost_reason}${q.lost_note ? ` (${q.lost_note})` : ""}`}
          {q.site_id && (
            <>
              {" "}
              · <Link to={`/sites/${q.site_id}`}>site</Link>
            </>
          )}
        </p>
      </div>
      {q.revisions.length > 1 && (
        <select className="rev-select" value={q.id} onChange={(e) => navigate(`/quotations/${e.target.value}`)} aria-label="Revision">
          {q.revisions.map((r) => (
            <option key={r.id} value={r.id}>
              R{r.revision} · {r.status}
            </option>
          ))}
        </select>
      )}
    </div>
  );
  if (phone) return <PhoneView q={q} html={html} header={header} />;
  return (
    <>
      {header}
      <div className="q-actions">
        <button className="btn btn-small" onClick={() => void downloadFile(`${base}/docx`).catch((e) => setError(errorText(e)))}>
          ⤓ Word
        </button>
        <button className="btn btn-small" onClick={() => void downloadFile(`${base}/pdf`).catch((e) => setError(errorText(e)))}>
          ⤓ PDF
        </button>
        {q.can_send && (
          <button
            className="btn btn-small"
            onClick={() => void apply(`${base}/issue`, undefined, "POST", "Issued: the Word and PDF files are kept with this revision and attached to the lead.")}
          >
            Issue files
          </button>
        )}
        {q.can_send && q.is_latest && ["draft", "negotiation"].includes(q.status) && (
          <button className="btn btn-small btn-primary" onClick={() => void apply(`${base}/status`, { status: "sent" }, "POST", "Sent: follow-ups are scheduled.")}>
            Mark sent
          </button>
        )}
        {q.can_edit && q.status === "sent" && (
          <button className="btn btn-small" onClick={() => void apply(`${base}/status`, { status: "negotiation" })}>
            Negotiation
          </button>
        )}
        {q.can_send && q.is_latest && ["draft", "sent", "negotiation"].includes(q.status) && (
          <>
            <button className="btn btn-small" onClick={() => setDialog("won")}>
              Won
            </button>
            <button className="btn btn-small" onClick={() => setDialog("lost")}>
              Lost
            </button>
          </>
        )}
        {q.is_latest && q.status !== "won" && (
          <button
            className="btn btn-small"
            onClick={() =>
              void api<Quotation>(`${base}/revision`, { method: "POST" }).then(
                (r) => navigate(`/quotations/${r.id}`),
                (e) => setError(errorText(e)),
              )
            }
          >
            New revision
          </button>
        )}
        {q.previous_id && (
          <button className="btn btn-small" onClick={() => setDialog("diff")}>
            Changes from R{q.revision - 1}
          </button>
        )}
        {q.can_edit && (
          <>
            <button className="btn btn-small btn-ghost" onClick={() => setDialog("survey")}>
              Quantities from a survey
            </button>
            <button className="btn btn-small btn-ghost" onClick={() => void apply(`${base}/refill-rates`, undefined, "POST", "Rates filled again (typed rates stay).")}>
              Refill rates
            </button>
          </>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {note && (
        <div className="alert alert-ok" onClick={() => setNote("")}>
          {note}
        </div>
      )}
      <div className="q-editor">
        <nav className="q-outline card" aria-label="Outline">
          <button className={`outline-row ${sel.kind === "letter" ? "on" : ""}`} onClick={() => setSel({ kind: "letter" })}>
            Cover letter
          </button>
          <div className="outline-group">Items</div>
          {q.items.map((it, i) => (
            <button key={it.id} className={`outline-row ${sel.kind === "item" && sel.id === it.id ? "on" : ""}`} onClick={() => setSel({ kind: "item", id: it.id })}>
              <span className="muted">{i + 1}.</span> {it.name}
              {it.option_labels.length > 1 && <span className="muted small"> · {(it.options.length ? it.options : it.option_labels).map((o) => `Opt.${o}`).join(", ")}</span>}
            </button>
          ))}
          {q.can_edit && (
            <button className="outline-row add" onClick={() => setDialog("add")}>
              + Add an area
            </button>
          )}
          <button className={`outline-row ${sel.kind === "terms" ? "on" : ""}`} onClick={() => setSel({ kind: "terms" })}>
            Terms &amp; conditions <span className="muted small">({q.terms.length})</span>
          </button>
          <button className={`outline-row ${sel.kind === "refs" ? "on" : ""}`} onClick={() => setSel({ kind: "refs" })}>
            References <span className="muted small">({q.references.filter((r) => r.include).length})</span>
          </button>
          <button className={`outline-row ${sel.kind === "follow" ? "on" : ""}`} onClick={() => setSel({ kind: "follow" })}>
            Follow-ups &amp; files
          </button>
          {q.show_amounts && (
            <div className="outline-total">
              Total <b>₹ {money(q.total)}</b>
              {q.total_option_note && <span className="muted small"> (first option)</span>}
            </div>
          )}
        </nav>
        <section className="q-preview card" aria-label="Preview">
          <iframe title="Quotation preview" srcDoc={html} sandbox="" />
        </section>
        <aside className="q-panel card">
          {sel.kind === "letter" && <LetterPanel q={q} lookups={lookups} apply={apply} />}
          {sel.kind === "item" && q.items.find((i) => i.id === sel.id) && (
            <ItemPanel key={sel.id} q={q} item={q.items.find((i) => i.id === sel.id)!} lookups={lookups} apply={apply} onRemoved={() => setSel({ kind: "letter" })} />
          )}
          {sel.kind === "terms" && <TermsPanel q={q} lookups={lookups} apply={apply} />}
          {sel.kind === "refs" && <RefsPanel q={q} apply={apply} />}
          {sel.kind === "follow" && <FollowPanel q={q} apply={apply} />}
        </aside>
      </div>
      {dialog === "won" && <WonDialog q={q} onClose={() => setDialog(null)} apply={apply} />}
      {dialog === "lost" && <LostDialog q={q} lookups={lookups} onClose={() => setDialog(null)} apply={apply} />}
      {dialog === "diff" && <DiffDialog q={q} onClose={() => setDialog(null)} />}
      {dialog === "survey" && <SurveyDialog q={q} onClose={() => setDialog(null)} apply={apply} />}
      {dialog === "add" && <AddItemDialog q={q} lookups={lookups} onClose={() => setDialog(null)} apply={apply} />}
    </>
  );
}

type Apply = (path: string, json?: unknown, method?: string, done?: string) => Promise<(Quotation & { result?: Record<string, string> }) | null>;

function PhoneView({ q, html, header }: { q: Quotation; html: string; header: React.ReactNode }) {
  const [msg, setMsg] = useState("");
  async function share() {
    const url = await fetchObjectUrl(`/api/quotations/${q.id}/pdf`);
    if (!url) return setMsg("Could not make the PDF.");
    const blob = await (await fetch(url)).blob();
    const file = new File([blob], `${q.code}-R${q.revision}.pdf`, { type: "application/pdf" });
    const nav = navigator as Navigator & { canShare?: (d: { files: File[] }) => boolean };
    if (nav.canShare?.({ files: [file] })) {
      await nav.share({ files: [file], title: `${q.code} R${q.revision}`, text: `${q.client_firm}: ${q.project}` }).catch(() => undefined);
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      a.click();
      setMsg("This browser cannot share files: the PDF was downloaded instead.");
    }
  }
  return (
    <div className="q-phone">
      {header}
      <div className="q-phone-actions">
        <button className="btn btn-primary" onClick={() => void share()}>
          Share PDF
        </button>
        <button className="btn" onClick={() => void downloadFile(`/api/quotations/${q.id}/pdf`)}>
          ⤓ PDF
        </button>
      </div>
      {msg && <p className="muted small">{msg}</p>}
      <p className="muted small">Read-only on a phone: edit the quotation on a laptop.</p>
      <div className="q-phone-preview card">
        <iframe title="Quotation preview" srcDoc={html} sandbox="" />
      </div>
    </div>
  );
}

// --- the right-hand panels -----------------------------------------------------------------------

function LetterPanel({ q, lookups, apply }: { q: Quotation; lookups: Lookups; apply: Apply }) {
  const [f, setF] = useState(() => ({
    client_firm: q.client_firm,
    client_city: q.client_city ?? "",
    client_state: q.client_state ?? "",
    attention: q.attention ?? "",
    project: q.project,
    brand: q.brand ?? "",
    areas_list: q.areas_list ?? "",
    quote_date: q.quote_date,
    validity_days: String(q.validity_days),
    letterhead_id: q.letterhead_id ? String(q.letterhead_id) : "",
    salesperson_id: q.salesperson_id ?? "",
    signatory_name: q.signatory_name ?? "",
    signatory_designation: q.signatory_designation ?? "",
    show_amounts: q.show_amounts,
    opening: q.opening,
    subject: q.subject,
    body: q.body,
    enclosures: q.enclosures,
  }));
  const ro = !q.can_edit;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void apply(
          `/api/quotations/${q.id}`,
          {
            ...f,
            validity_days: Number(f.validity_days),
            letterhead_id: f.letterhead_id ? Number(f.letterhead_id) : null,
            salesperson_id: f.salesperson_id || undefined,
            areas_list: f.areas_list || null,
            signatory_name: f.signatory_name || null,
            signatory_designation: f.signatory_designation || null,
          },
          "PUT",
          "Saved for this quotation only (the library is unchanged).",
        );
      }}
    >
      <h2 className="section-title">Cover letter</h2>
      <div className="form-grid two">
        <label className="field">
          <span>Client firm</span>
          <input value={f.client_firm} onChange={set("client_firm")} disabled={ro} />
        </label>
        <label className="field">
          <span>City</span>
          <input value={f.client_city} onChange={set("client_city")} disabled={ro} />
        </label>
        <label className="field">
          <span>Kind attention</span>
          <input value={f.attention} onChange={set("attention")} disabled={ro} />
        </label>
        <label className="field">
          <span>Project</span>
          <input value={f.project} onChange={set("project")} disabled={ro} />
        </label>
        <label className="field">
          <span>Brand</span>
          <input value={f.brand} onChange={set("brand")} disabled={ro} />
        </label>
        <label className="field">
          <span>Areas list</span>
          <input value={f.areas_list} placeholder={q.areas_list_auto} onChange={set("areas_list")} disabled={ro} />
        </label>
        <label className="field">
          <span>Date</span>
          <input type="date" value={f.quote_date} onChange={set("quote_date")} disabled={ro} />
        </label>
        <label className="field">
          <span>Valid for (days)</span>
          <input type="number" min={1} max={365} value={f.validity_days} onChange={set("validity_days")} disabled={ro} />
        </label>
        <label className="field">
          <span>Letterhead</span>
          <select value={f.letterhead_id} onChange={set("letterhead_id")} disabled={ro}>
            {lookups.letterheads.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Salesperson</span>
          <select value={f.salesperson_id} onChange={set("salesperson_id")} disabled={ro}>
            <option value="">—</option>
            {lookups.salespeople.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Signatory name</span>
          <input value={f.signatory_name} placeholder="the salesperson" onChange={set("signatory_name")} disabled={ro} />
        </label>
        <label className="field">
          <span>Designation</span>
          <input value={f.signatory_designation} placeholder="their job title" onChange={set("signatory_designation")} disabled={ro} />
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={f.show_amounts} onChange={(e) => setF({ ...f, show_amounts: e.target.checked })} disabled={ro} /> Show quantities, amounts and a total
      </label>
      <MarkupField label="Opening" value={f.opening} onChange={(v) => setF({ ...f, opening: v })} rows={4} placeholders={lookups.placeholders} disabled={ro} />
      <MarkupField label="Subject" value={f.subject} onChange={(v) => setF({ ...f, subject: v })} rows={1} placeholders={lookups.placeholders} disabled={ro} />
      <MarkupField label="Body" value={f.body} onChange={(v) => setF({ ...f, body: v })} rows={7} placeholders={lookups.placeholders} disabled={ro} />
      <MarkupField label="Enclosures (one per line)" value={f.enclosures} onChange={(v) => setF({ ...f, enclosures: v })} rows={2} disabled={ro} />
      <div className="panel-actions">
        {!ro && <button className="btn btn-primary">Save</button>}
        {q.can_template_edit && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void apply(`/api/quotations/${q.id}/save-back`, { kind: "letter" })}
            title="Write this letter into its library template as a new version"
          >
            Save back to library
          </button>
        )}
      </div>
    </form>
  );
}

function ItemPanel({ q, item, lookups, apply, onRemoved }: { q: Quotation; item: QItem; lookups: Lookups; apply: Apply; onRemoved: () => void }) {
  const ro = !q.can_edit;
  const [head, setHead] = useState({ name: item.name, budget_title: item.budget_title });
  const [specs, setSpecs] = useState<SpecCopy[]>(item.specs);
  const [adding, setAdding] = useState(false);
  useEffect(() => setSpecs(item.specs), [item.specs]);
  const base = `/api/quotations/${q.id}`;
  const offered = item.options.length ? item.options : item.option_labels;
  return (
    <div>
      <h2 className="section-title">{item.name}</h2>
      <div className="form-grid two">
        <label className="field">
          <span>Area name</span>
          <input value={head.name} onChange={(e) => setHead({ ...head, name: e.target.value })} disabled={ro} />
        </label>
        <label className="field">
          <span>Budgetary offer title</span>
          <input value={head.budget_title} onChange={(e) => setHead({ ...head, budget_title: e.target.value })} disabled={ro} />
        </label>
      </div>
      {item.option_labels.length > 1 && (
        <div className="field">
          <span>Options offered</span>
          <div>
            {item.option_labels.map((o) => (
              <label key={o} className="check inline">
                <input
                  type="checkbox"
                  checked={offered.includes(o)}
                  disabled={ro}
                  onChange={(e) => {
                    const next = e.target.checked ? [...offered, o].sort() : offered.filter((x) => x !== o);
                    if (next.length) void apply(`${base}/items/${item.id}`, { options: next }, "PUT");
                  }}
                />{" "}
                Opt.{o}
              </label>
            ))}
          </div>
        </div>
      )}
      {!ro && (
        <div className="panel-actions">
          <button className="btn btn-small" onClick={() => void apply(`${base}/items/${item.id}`, head, "PUT", "Saved for this quotation only.")}>
            Save names
          </button>
          {q.can_template_edit && item.offer_item_id && (
            <button className="btn btn-small btn-ghost" onClick={() => void apply(`${base}/save-back`, { kind: "item", item_id: item.id })}>
              Save names back to library
            </button>
          )}
          <button
            className="btn btn-small btn-ghost danger"
            onClick={() => {
              if (window.confirm(`Remove ${item.name} from this quotation?`)) void apply(`${base}/items/${item.id}`, undefined, "DELETE").then(onRemoved);
            }}
          >
            Remove area
          </button>
        </div>
      )}
      <h3 className="section-title top-gap">Technical specification</h3>
      {specs.map((s, i) => (
        <details key={i} className="spec-box" open={specs.length === 1}>
          <summary>
            {s.option_label ? `Option ${s.option_label}: ` : ""}
            {s.title} {s.version ? <span className="muted small">library v{s.version}</span> : null}
          </summary>
          <label className="field">
            <span>Title</span>
            <input value={s.title} onChange={(e) => setSpecs(specs.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} disabled={ro} />
          </label>
          <SectionsEditor sections={s.sections} stages={lookups.stages} disabled={ro} onChange={(sections) => setSpecs(specs.map((x, j) => (j === i ? { ...x, sections } : x)))} />
          {!ro && (
            <div className="panel-actions">
              <button
                className="btn btn-small btn-primary"
                onClick={() => void apply(`${base}/items/${item.id}`, { specs }, "PUT", "Saved for this quotation only (the library is unchanged).")}
              >
                Save specification
              </button>
              {q.can_template_edit && s.spec_block_id && (
                <button className="btn btn-small btn-ghost" onClick={() => void apply(`${base}/save-back`, { kind: "spec", item_id: item.id, spec_index: i })}>
                  Save back to library
                </button>
              )}
            </div>
          )}
        </details>
      ))}
      <h3 className="section-title top-gap">Budgetary offer</h3>
      {item.lines.map((ln) => (
        <LineEditor key={`${ln.id}-${ln.rate}-${ln.qty}`} q={q} line={ln} lookups={lookups} apply={apply} />
      ))}
      {!ro &&
        (adding ? (
          <AddLine q={q} item={item} lookups={lookups} apply={apply} onDone={() => setAdding(false)} />
        ) : (
          <button className="btn btn-small" onClick={() => setAdding(true)}>
            + Line
          </button>
        ))}
      {item.total && q.show_amounts && <p className="small top-gap">Item total ₹ {money(item.total)}</p>}
    </div>
  );
}

function LineEditor({ q, line, lookups, apply }: { q: Quotation; line: QLine; lookups: Lookups; apply: Apply }) {
  const ro = !q.can_edit;
  const [f, setF] = useState({
    description: line.description,
    uom: line.uom,
    rate: line.rate ?? "",
    qty: line.qty ?? "",
    if_required: line.if_required,
    client_scope: line.client_scope,
  });
  const [open, setOpen] = useState(false);
  const url = `/api/quotations/${q.id}/lines/${line.id}`;
  const dirty =
    f.description !== line.description || f.uom !== line.uom || f.qty !== (line.qty ?? "") || f.if_required !== line.if_required || f.client_scope !== line.client_scope;
  return (
    <div className={`line-box ${line.offered ? "" : "not-offered"}`}>
      <div className="line-head" onClick={() => setOpen(!open)}>
        <span className="line-opt">{line.option ? `Opt.${line.option}` : line.if_required ? "if req." : ""}</span>
        <span className="line-text">{plain(line.description).slice(0, 90)}</span>
        <span className="line-rate">{line.client_scope ? "Client's scope" : `${money(line.rate)} / ${lookups.uoms.find((u) => u.code === line.uom)?.label ?? line.uom}`}</span>
      </div>
      {line.rate_note && (
        <div className="muted small">
          {line.overridden ? "Typed here" : line.rate_note}
          {q.can_margin &&
            line.cost_rate &&
            ` · cost ${money(line.cost_rate)}${line.margin_percent ? ` · margin ${Number(line.margin_percent).toFixed(1)} %` : ""}${line.margin_amount ? ` (₹ ${money(line.margin_amount)})` : ""}`}
        </div>
      )}
      {open && (
        <div className="line-body">
          {!line.offered && <p className="muted small">This option is not offered (tick it under Options offered).</p>}
          <MarkupField label="Description" value={f.description} onChange={(v) => setF({ ...f, description: v })} rows={4} disabled={ro} />
          <div className="form-grid four">
            <label className="field">
              <span>UoM</span>
              <select value={f.uom} onChange={(e) => setF({ ...f, uom: e.target.value })} disabled={ro}>
                {lookups.uoms.map((u) => (
                  <option key={u.code} value={u.code}>
                    {u.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Rate (₹)</span>
              <input inputMode="decimal" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} disabled={ro || f.client_scope} />
            </label>
            <label className="field">
              <span>Qty</span>
              <input inputMode="decimal" value={f.qty} placeholder="rate only" onChange={(e) => setF({ ...f, qty: e.target.value })} disabled={ro} />
            </label>
            <div className="field">
              <span>Amount</span>
              <span className="num">{line.amount ? `₹ ${money(line.amount)}` : "—"}</span>
            </div>
          </div>
          <label className="check inline">
            <input type="checkbox" checked={f.if_required} onChange={(e) => setF({ ...f, if_required: e.target.checked })} disabled={ro} /> If required
          </label>
          <label className="check inline">
            <input type="checkbox" checked={f.client_scope} onChange={(e) => setF({ ...f, client_scope: e.target.checked })} disabled={ro} /> Client's scope
          </label>
          {!ro && (
            <div className="panel-actions">
              <button
                className="btn btn-small btn-primary"
                onClick={() => {
                  const body: Record<string, unknown> = {};
                  if (dirty)
                    Object.assign(body, { description: f.description, uom: f.uom, qty: f.qty === "" ? null : f.qty, if_required: f.if_required, client_scope: f.client_scope });
                  if (f.rate !== (line.rate ?? "")) body.rate = f.rate === "" ? null : f.rate;
                  void apply(url, body, "PUT", "Saved for this quotation only.");
                }}
              >
                Save line
              </button>
              {line.overridden && (
                <button className="btn btn-small btn-ghost" onClick={() => void apply(url, { rate: null }, "PUT", "Rate filled again from its source.")}>
                  Use the filled rate
                </button>
              )}
              {q.can_template_edit && (
                <button className="btn btn-small btn-ghost" onClick={() => void apply(`/api/quotations/${q.id}/save-back`, { kind: "line", line_id: line.id })}>
                  Save back to library
                </button>
              )}
              <button className="btn btn-small btn-ghost danger" onClick={() => void apply(url, undefined, "DELETE")}>
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AddLine({ q, item, lookups, apply, onDone }: { q: Quotation; item: QItem; lookups: Lookups; apply: Apply; onDone: () => void }) {
  const [lines, setLines] = useState<{ id: number; description: string; uom: string; default_rate: string | null }[]>([]);
  const [search, setSearch] = useState("");
  const [blank, setBlank] = useState({ description: "", uom: "sqft", rate: "", option: "" });
  useEffect(() => {
    void api<typeof lines>(`/api/quotations/library/line?q=${encodeURIComponent(search)}`).then((r) => setLines(r.slice(0, 30)));
  }, [search]);
  const base = `/api/quotations/${q.id}/items/${item.id}/lines`;
  return (
    <div className="add-line card">
      <label className="field">
        <span>From the library</span>
        <input placeholder="Search offer lines" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      <div className="lib-pick">
        {lines.map((l) => (
          <button key={l.id} className="btn btn-small btn-ghost" onClick={() => void apply(base, { offer_line_id: l.id }).then(onDone)}>
            {plain(l.description).slice(0, 70)} <span className="muted">· {l.uom}</span>
          </button>
        ))}
      </div>
      <MarkupField label="Or a new line (this quotation only)" value={blank.description} onChange={(v) => setBlank({ ...blank, description: v })} rows={2} />
      <div className="inline-form">
        <select value={blank.uom} onChange={(e) => setBlank({ ...blank, uom: e.target.value })}>
          {lookups.uoms.map((u) => (
            <option key={u.code} value={u.code}>
              {u.label}
            </option>
          ))}
        </select>
        <input placeholder="Rate (empty: Suggest)" value={blank.rate} onChange={(e) => setBlank({ ...blank, rate: e.target.value })} />
        <input placeholder="Option" className="option-input" value={blank.option} onChange={(e) => setBlank({ ...blank, option: e.target.value })} />
        <button
          className="btn btn-small btn-primary"
          disabled={!blank.description.trim()}
          onClick={() => void apply(base, { description: blank.description, uom: blank.uom, rate: blank.rate || null, option: blank.option || null }).then(onDone)}
        >
          Add
        </button>
        <button className="btn btn-small" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function TermsPanel({ q, lookups, apply }: { q: Quotation; lookups: Lookups; apply: Apply }) {
  const ro = !q.can_edit;
  const [terms, setTerms] = useState<Term[]>(q.terms);
  const [picking, setPicking] = useState(false);
  const [library, setLibrary] = useState<{ id: number; category: string; text: string }[]>([]);
  useEffect(() => {
    if (picking) void api<typeof library>("/api/quotations/tc-clauses").then(setLibrary);
  }, [picking]);
  const label = (c: string) => lookups.tc_groups[c] ?? c.replace("_", " ");
  const move = (i: number, d: number) => {
    const next = [...terms];
    const [t] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, t);
    setTerms(next);
  };
  return (
    <div>
      <h2 className="section-title">Terms &amp; conditions</h2>
      <p className="muted small">Numbered right through; a group with two or more clauses prints its heading. Changes here stay in this quotation.</p>
      {terms.map((t, i) => (
        <div key={i} className="term-row">
          <div className="inline-form">
            <span className="step-n">{i + 1}.</span>
            <select value={t.category} onChange={(e) => setTerms(terms.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)))} disabled={ro}>
              {[...new Set([...Object.keys(lookups.tc_groups), t.category])].map((c) => (
                <option key={c} value={c}>
                  {label(c)}
                </option>
              ))}
            </select>
            {!ro && (
              <>
                <button className="btn btn-small btn-ghost" onClick={() => move(i, -1)} aria-label="Up">
                  ↑
                </button>
                <button className="btn btn-small btn-ghost" onClick={() => move(i, 1)} aria-label="Down">
                  ↓
                </button>
                <button className="btn btn-small btn-ghost" onClick={() => setTerms(terms.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </>
            )}
          </div>
          <MarkupField
            label=""
            value={t.text}
            onChange={(v) => setTerms(terms.map((x, j) => (j === i ? { ...x, text: v } : x)))}
            rows={3}
            disabled={ro}
            hint={'Lines starting with "- " print as a), b), c).'}
          />
        </div>
      ))}
      {!ro && (
        <div className="panel-actions">
          <button className="btn btn-primary" onClick={() => void apply(`/api/quotations/${q.id}`, { terms }, "PUT", "Saved for this quotation only.")}>
            Save terms
          </button>
          <button className="btn btn-ghost" onClick={() => setPicking(!picking)}>
            + From the T&amp;C library
          </button>
        </div>
      )}
      {picking && (
        <div className="lib-pick tall">
          {library.map((c) => (
            <button key={c.id} className="btn btn-small btn-ghost" onClick={() => setTerms([...terms, { category: c.category, text: c.text, clause_id: c.id }])}>
              <span className="badge badge-muted">{label(c.category)}</span> {plain(c.text).slice(0, 110)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RefsPanel({ q, apply }: { q: Quotation; apply: Apply }) {
  const ro = !q.can_edit;
  const [rows, setRows] = useState<Ref[]>(q.references);
  const [title, setTitle] = useState(q.references_title ?? "");
  const [state, setState] = useState(q.client_state ?? "");
  const [areaType, setAreaType] = useState("");
  const lookups = useLookups();
  const move = (i: number, d: number) => {
    const next = [...rows];
    const [t] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + d)), 0, t);
    setRows(next);
  };
  async function reload() {
    const qs = new URLSearchParams();
    if (state) qs.set("state", state);
    if (areaType) qs.set("area_type_id", areaType);
    const lib = await api<Ref[]>(`/api/quotations/library/reference?${qs}`);
    setRows(lib.map((r) => ({ ...r, include: r.include ?? true })));
    if (state) setTitle(`Our Esteemed Clients for Waterproofing Projects in ${state}`);
  }
  return (
    <div>
      <h2 className="section-title">Our esteemed clients</h2>
      <label className="field">
        <span>Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={ro} />
      </label>
      {!ro && (
        <div className="inline-form">
          <input placeholder="State (e.g. Gujarat)" value={state} onChange={(e) => setState(e.target.value)} />
          <select value={areaType} onChange={(e) => setAreaType(e.target.value)}>
            <option value="">Any area type</option>
            {lookups?.area_types.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <button className="btn btn-small" onClick={() => void reload()}>
            Load from the library
          </button>
        </div>
      )}
      <div className="ref-rows">
        {rows.map((r, i) => (
          <div key={i} className={`ref-row ${r.include ? "" : "excluded"}`}>
            <label className="check">
              <input type="checkbox" checked={r.include} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, include: e.target.checked } : x)))} disabled={ro} />
              <b>{r.client_name}</b>
            </label>
            <span className="muted small">
              {r.project} · {r.application} · {r.area_value ? `${Number(r.area_value).toLocaleString("en-IN")} ${r.area_unit ?? ""}` : "—"}
            </span>
            {!ro && (
              <span>
                <button className="btn btn-small btn-ghost" onClick={() => move(i, -1)} aria-label="Up">
                  ↑
                </button>
                <button className="btn btn-small btn-ghost" onClick={() => move(i, 1)} aria-label="Down">
                  ↓
                </button>
              </span>
            )}
          </div>
        ))}
      </div>
      {!ro && (
        <button
          className="btn btn-primary top-gap"
          onClick={() => void apply(`/api/quotations/${q.id}`, { references: rows, references_title: title }, "PUT", "Saved for this quotation only.")}
        >
          Save references
        </button>
      )}
    </div>
  );
}

function FollowPanel({ q, apply }: { q: Quotation; apply: Apply }) {
  const [busy, setBusy] = useState(0);
  async function done(id: number) {
    const note = window.prompt("What did the client say? (optional)") ?? undefined;
    setBusy(id);
    await api(`/api/quotations/followups/${id}/done`, { method: "POST", json: { note } }).catch(() => undefined);
    await apply(`/api/quotations/${q.id}`, undefined, "GET");
    setBusy(0);
  }
  return (
    <div>
      <h2 className="section-title">Follow-ups</h2>
      {q.followups.length === 0 ? (
        <p className="muted small">Follow-ups are scheduled when the quotation is sent (days 2, 7, 15 and 30).</p>
      ) : (
        <table className="table compact">
          <tbody>
            {q.followups.map((f) => (
              <tr key={f.id} className={f.overdue ? "row-overdue" : undefined}>
                <td>{fmtDate(f.due_on)}</td>
                <td className="small">
                  day {f.day} · {f.code}
                </td>
                <td>
                  <span className={`badge ${f.status === "open" ? (f.overdue ? "badge-danger" : "badge-info") : "badge-muted"}`}>{f.overdue ? "overdue" : f.status}</span>
                </td>
                <td>
                  {f.status === "open" && (
                    <button className="btn btn-small" disabled={busy === f.id} onClick={() => void done(f.id)}>
                      Done
                    </button>
                  )}
                  {f.note && <span className="muted small"> {f.note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2 className="section-title top-gap">Issued files</h2>
      {q.files.length === 0 ? (
        <p className="muted small">Nothing issued for R{q.revision} yet.</p>
      ) : (
        <ul className="file-list">
          {q.files.map((f) => (
            <li key={f.id}>
              <button className="btn btn-small btn-ghost" onClick={() => void downloadFile(`/api/quotations/files/${f.id}`)}>
                ⤓ {f.file_name}
              </button>{" "}
              <span className="muted small">
                {(f.size_bytes / 1024).toFixed(0)} KB · {new Date(f.created_at).toLocaleString("en-IN")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- dialogs -------------------------------------------------------------------------------------

function WonDialog({ q, onClose, apply }: { q: Quotation; onClose: () => void; apply: Apply }) {
  const multi = q.items.filter((i) => (i.options.length ? i.options : i.option_labels).length > 1);
  const [choices, setChoices] = useState<Record<number, string>>(() => Object.fromEntries(multi.map((i) => [i.id, (i.options.length ? i.options : i.option_labels)[0]])));
  const [sites, setSites] = useState<{ id: number; code: string; name: string }[]>([]);
  const [site, setSite] = useState("");
  const [result, setResult] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    void api<{ items: { id: number; code: string; name: string }[] }>("/api/sites?limit=100").then(
      (r) => setSites(r.items),
      () => setSites([]),
    );
  }, []);
  return (
    <Modal title={`${q.code} R${q.revision} won`} onClose={onClose}>
      {result ? (
        <>
          <p>
            Tender (order) <b>{result.tender_code}</b> holds the quotation's lines; site <b>{result.site_code}</b> is ready for execution and billing.
          </p>
          <div className="modal-actions">
            <Link className="btn btn-primary" to={`/sites/${result.site_id}`}>
              Open the site
            </Link>
            <button className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </>
      ) : (
        <>
          {multi.map((i) => (
            <label key={i.id} className="field">
              <span>{i.name}: the client chose</span>
              <select value={choices[i.id]} onChange={(e) => setChoices({ ...choices, [i.id]: e.target.value })}>
                {(i.options.length ? i.options : i.option_labels).map((o) => (
                  <option key={o} value={o}>
                    Opt.{o}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label className="field">
            <span>Site</span>
            <select value={site} onChange={(e) => setSite(e.target.value)}>
              <option value="">Make a new site</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>
                  Link {s.code} · {s.name}
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">Follow-ups stop; the lead is marked won.</p>
          <div className="modal-actions">
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={() =>
                void apply(`/api/quotations/${q.id}/status`, { status: "won", choices, site_id: site ? Number(site) : null }).then((r) => r?.result && setResult(r.result))
              }
            >
              Mark won
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

function LostDialog({ q, lookups, onClose, apply }: { q: Quotation; lookups: Lookups; onClose: () => void; apply: Apply }) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  return (
    <Modal title={`${q.code} R${q.revision} lost`} onClose={onClose}>
      <label className="field">
        <span>Why was it lost?</span>
        <select value={reason} onChange={(e) => setReason(e.target.value)} required>
          <option value="">Choose…</option>
          {lookups.lost_reasons.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Note (who won it, at what rate…)</span>
        <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!reason}
          onClick={() => void apply(`/api/quotations/${q.id}/status`, { status: "lost", lost_reason: reason, lost_note: note || null }).then((r) => r && onClose())}
        >
          Mark lost
        </button>
      </div>
    </Modal>
  );
}

type Diff = {
  from: string;
  to: string;
  changed: {
    item: string;
    line: string;
    option: string | null;
    uom: string;
    old_rate?: string;
    new_rate?: string;
    rate_change_percent?: string;
    old_qty?: string;
    new_qty?: string;
    text_changed?: boolean;
  }[];
  added: { item: string; line: string; rate: string | null }[];
  removed: { item: string; line: string; rate: string | null }[];
  items_added: string[];
  items_removed: string[];
  total_from: string;
  total_to: string;
};

function DiffDialog({ q, onClose }: { q: Quotation; onClose: () => void }) {
  const [d, setD] = useState<Diff | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Diff>(`/api/quotations/${q.id}/diff`).then(setD, (e) => setError(errorText(e)));
  }, [q.id]);
  return (
    <Modal title={d ? `Changes from ${d.from} to ${d.to}` : "Changes"} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      {d && (
        <>
          {d.changed.length === 0 && d.added.length === 0 && d.removed.length === 0 && <p className="muted">No line changed.</p>}
          {d.changed.length > 0 && (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Line</th>
                  <th className="num">{d.from}</th>
                  <th className="num">{d.to}</th>
                  <th className="num">Change</th>
                </tr>
              </thead>
              <tbody>
                {d.changed.map((c, i) => (
                  <tr key={i}>
                    <td>{c.item}</td>
                    <td className="small">
                      {c.option ? `Opt.${c.option} · ` : ""}
                      {c.line}
                      {c.text_changed && <span className="badge badge-muted">text changed</span>}
                      {c.new_qty !== undefined && (
                        <span className="muted">
                          {" "}
                          · qty {c.old_qty ?? "—"} → {c.new_qty ?? "—"}
                        </span>
                      )}
                    </td>
                    <td className="num">{c.old_rate !== undefined ? money(c.old_rate) : ""}</td>
                    <td className="num">{c.new_rate !== undefined ? money(c.new_rate) : ""}</td>
                    <td className={`num ${Number(c.rate_change_percent ?? 0) < 0 ? "text-danger" : ""}`}>
                      {c.rate_change_percent !== undefined ? `${Number(c.rate_change_percent).toFixed(1)} %` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {[...d.added.map((a) => ({ ...a, kind: "added" })), ...d.removed.map((a) => ({ ...a, kind: "removed" }))].map((a, i) => (
            <p key={i} className="small">
              <span className={`badge ${a.kind === "added" ? "badge-ok" : "badge-danger"}`}>{a.kind}</span> {a.item}: {a.line} {a.rate ? `· ${money(a.rate)}` : ""}
            </p>
          ))}
          {(d.items_added.length > 0 || d.items_removed.length > 0) && (
            <p className="small">
              {d.items_added.length > 0 && `Areas added: ${d.items_added.join(", ")}. `}
              {d.items_removed.length > 0 && `Areas removed: ${d.items_removed.join(", ")}.`}
            </p>
          )}
          {(Number(d.total_from) > 0 || Number(d.total_to) > 0) && (
            <p className="small">
              Total {d.from} ₹ {money(d.total_from)} → {d.to} ₹ {money(d.total_to)}
            </p>
          )}
        </>
      )}
    </Modal>
  );
}

function SurveyDialog({ q, onClose, apply }: { q: Quotation; onClose: () => void; apply: Apply }) {
  const [surveys, setSurveys] = useState<{ id: number; code: string; title: string | null; status: string }[] | null>(null);
  const [pick, setPick] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const qs = q.lead_id ? `?lead_id=${q.lead_id}` : "";
    api<typeof surveys>(`/api/surveys${qs}`).then(
      (r) => setSurveys(r ?? []),
      () => setSurveys([]),
    );
  }, [q.lead_id]);
  return (
    <Modal title="Quantities from a site survey" onClose={onClose}>
      <p className="muted small">Each area's treated sqm (by its area type) goes on its sqm and sqft lines; R FT and NOS lines stay as they are.</p>
      <select value={pick} onChange={(e) => setPick(e.target.value)}>
        <option value="">Choose a survey…</option>
        {surveys?.map((s) => (
          <option key={s.id} value={s.id}>
            {s.code} · {s.title ?? ""} ({s.status})
          </option>
        ))}
      </select>
      {msg && <p className="small">{msg}</p>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Close
        </button>
        <button
          className="btn btn-primary"
          disabled={!pick}
          onClick={() =>
            void apply(`/api/quotations/${q.id}/survey-quantities`, { survey_id: Number(pick) }).then((r) => {
              const fill = (r as unknown as { survey_fill?: { lines_filled: number; items_without_match: number } })?.survey_fill;
              if (fill) setMsg(`${fill.lines_filled} line(s) filled; ${fill.items_without_match} area(s) had no matching area type.`);
            })
          }
        >
          Fill quantities
        </button>
      </div>
    </Modal>
  );
}

function AddItemDialog({ q, lookups, onClose, apply }: { q: Quotation; lookups: Lookups; onClose: () => void; apply: Apply }) {
  const [pick, setPick] = useState("");
  const item = useMemo(() => lookups.offer_items.find((i) => String(i.id) === pick), [pick, lookups]);
  const [opts, setOpts] = useState<string[]>([]);
  useEffect(() => setOpts(item?.option_labels ?? []), [item]);
  return (
    <Modal title="Add an area" onClose={onClose}>
      <select value={pick} onChange={(e) => setPick(e.target.value)}>
        <option value="">Choose an offer item…</option>
        {lookups.offer_items.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
      </select>
      {item && item.option_labels.length > 1 && (
        <div className="top-gap">
          {item.option_labels.map((o) => (
            <label key={o} className="check inline">
              <input type="checkbox" checked={opts.includes(o)} onChange={(e) => setOpts(e.target.checked ? [...opts, o].sort() : opts.filter((x) => x !== o))} /> Opt.{o}
            </label>
          ))}
        </div>
      )}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!pick}
          onClick={() => void apply(`/api/quotations/${q.id}/items`, { offer_item_id: Number(pick), options: opts }).then((r) => r && onClose())}
        >
          Add
        </button>
      </div>
    </Modal>
  );
}

export function refreshLookups() {
  void loadLookups(true);
}
