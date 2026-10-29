// The close-out entry screens that were missing: a new client work order and its structured terms,
// our answer to the client's measurement corrections (and the client's paper approval, the site's
// approval switch), and a labour contractor's claim with its photos.
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, DateField, Field, FilePicker, Select } from "../ui/components";

const upload = (path: string, f: File, extra: Record<string, string> = {}) => {
  const form = new FormData();
  form.append("file", f);
  Object.entries(extra).forEach(([k, v]) => form.append(k, v));
  return api(path, { method: "POST", form });
};

// --- the client work order ------------------------------------------------------------------------

/** The work-order list a breadcrumb goes back to: the Billing page, or the Sales one for a role without billing. */
export function woListPath(hasBilling: boolean): string {
  return hasBilling ? "/work-orders" : "/sales/work-orders";
}

type WonQ = { id: number; code: string; revision: number; client_firm: string | null; project: string | null };

/** New work order: against a won quotation, with the client's reference and (optionally) the client's file, read at once. */
export function NewWorkOrder({ tenderId, siteId }: { tenderId?: number; siteId?: number }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [quotes, setQuotes] = useState<WonQ[] | null>(null);
  const [qid, setQid] = useState("");
  const [ref, setRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open && quotes === null) api<WonQ[]>("/api/quotations?status=won").then(setQuotes, (e) => (setQuotes([]), setError(errorText(e))));
  }, [open, quotes]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const wo = await api<{ id: number }>("/api/closeout/work-orders", {
        method: "POST",
        json: { quotation_id: Number(qid), client_ref: ref.trim() || null, tender_id: tenderId ?? null, site_id: siteId ?? null },
      });
      if (file) {
        try {
          await upload(`/api/closeout/work-orders/${wo.id}/file`, file);
        } catch (err) {
          // the work order is made: open it and say the file was not read
          navigate(`/work-orders/${wo.id}?file_error=${encodeURIComponent(errorText(err))}`);
          return;
        }
      }
      navigate(`/work-orders/${wo.id}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        New work order
      </Button>
      {open && (
        <Modal title="New client work order" onClose={() => setOpen(false)}>
          <form onSubmit={(e) => void submit(e)}>
            {error && <div className="alert alert-error">{error}</div>}
            <p className="small muted">Entered against our won quotation. The client's file (PDF or Excel) fills the lines and the terms it states; you can also copy our lines later.</p>
            <Field label="Our won quotation">
              <select required value={qid} onChange={(e) => setQid(e.target.value)}>
                <option value="">{quotes === null ? "Loading…" : quotes.length ? "Pick the quotation…" : "No won quotation"}</option>
                {(quotes ?? []).map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.code} R{q.revision} · {q.client_firm ?? ""} {q.project ? `· ${q.project}` : ""}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Client's work order number">
              <input value={ref} maxLength={100} onChange={(e) => setRef(e.target.value)} placeholder="e.g. WO/2026/117" />
            </Field>
            <Field label="The client's work order file (optional)" as="div">
              <FilePicker label="Choose the PDF or Excel" accept=".pdf,.xlsx,.xlsm" onFiles={(f) => setFile(f[0] ?? null)} />
            </Field>
            <div className="form-actions">
              <Button variant="primary" type="submit" disabled={busy || !qid}>
                {busy ? "Saving…" : "Make the work order"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

export type TermsForm = {
  client_ref: string;
  payment_basis: string;
  payment_days: string;
  retention_percent: string;
  retention_release: string;
  advance_percent: string;
  guarantee_years: string;
  time_limit_days: string;
  penalty: string;
  scope_on_us: string;
  scope_on_client: string;
};
type Terms = Record<string, string | number | string[] | null>;

const txt = (v: unknown) => (v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : String(v));

/** The form's starting values from the work order's terms. */
export function termsForm(clientRef: string | null, t: Terms): TermsForm {
  return {
    client_ref: clientRef ?? "",
    payment_basis: txt(t.payment_basis),
    payment_days: txt(t.payment_days),
    retention_percent: txt(t.retention_percent),
    retention_release: txt(t.retention_release),
    advance_percent: txt(t.advance_percent),
    guarantee_years: txt(t.guarantee_years),
    time_limit_days: txt(t.time_limit_days),
    penalty: txt(t.penalty),
    scope_on_us: txt(t.scope_on_us),
    scope_on_client: txt(t.scope_on_client),
  };
}

/** What PUT /work-orders/{id} takes: empty boxes clear the term, whole numbers stay whole, percentages go as text (Decimal on the server), scope lists split on commas. */
export function termsBody(f: TermsForm): Record<string, string | number | string[] | null> {
  const s = (v: string) => v.trim() || null;
  const int = (v: string) => (v.trim() ? Math.round(Number(v)) : null);
  const list = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
  return {
    client_ref: s(f.client_ref),
    payment_basis: s(f.payment_basis),
    payment_days: int(f.payment_days),
    retention_percent: s(f.retention_percent),
    retention_release: s(f.retention_release),
    advance_percent: s(f.advance_percent),
    guarantee_years: int(f.guarantee_years),
    time_limit_days: int(f.time_limit_days),
    penalty: s(f.penalty),
    scope_on_us: list(f.scope_on_us),
    scope_on_client: list(f.scope_on_client),
  };
}

/** Edit terms: the work order's payment days and basis, retention, advance, guarantee, time limit, penalty and scope, typed in. */
export function WorkOrderTerms<T>({ woId, clientRef, terms, onSaved }: { woId: number; clientRef: string | null; terms: Terms; onSaved: (wo: T) => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<TermsForm>(() => termsForm(clientRef, terms));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof TermsForm) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api<T>(`/api/closeout/work-orders/${woId}`, { method: "PUT", json: termsBody(f) }));
      setOpen(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button size="small" onClick={() => (setF(termsForm(clientRef, terms)), setOpen(true))}>
        Edit terms
      </Button>
      {open && (
        <Modal title="The work order's terms" onClose={() => setOpen(false)} wide>
          <form onSubmit={(e) => void submit(e)}>
            {error && <div className="alert alert-error">{error}</div>}
            <p className="small muted">As the client's work order states them. Compare with our offer again after a change.</p>
            <Field label="Client's work order number">
              <input value={f.client_ref} maxLength={100} onChange={set("client_ref")} />
            </Field>
            <div className="grid-2">
              <Field label="Payment within (days)">
                <input inputMode="numeric" value={f.payment_days} onChange={set("payment_days")} />
              </Field>
              <Select
                label="Counted from"
                value={f.payment_basis}
                onChange={(v) => setF({ ...f, payment_basis: v })}
                options={[
                  { value: "", label: "—" },
                  { value: "invoice", label: "the invoice" },
                  { value: "certification", label: "the certification" },
                  { value: "final_bill", label: "the final bill" },
                ]}
              />
              <Field label="Retention (%)">
                <input inputMode="decimal" value={f.retention_percent} onChange={set("retention_percent")} />
              </Field>
              <Field label="Retention released">
                <input value={f.retention_release} onChange={set("retention_release")} placeholder="e.g. after the guarantee period" />
              </Field>
              <Field label="Advance (%)">
                <input inputMode="decimal" value={f.advance_percent} onChange={set("advance_percent")} />
              </Field>
              <Field label="Guarantee (years)">
                <input inputMode="numeric" value={f.guarantee_years} onChange={set("guarantee_years")} />
              </Field>
              <Field label="Time limit (days)">
                <input inputMode="numeric" value={f.time_limit_days} onChange={set("time_limit_days")} />
              </Field>
              <Field label="Penalty">
                <input value={f.penalty} onChange={set("penalty")} placeholder="e.g. 0.5 % a week, at most 5 %" />
              </Field>
            </div>
            <Field label="On us (comma between items)">
              <input value={f.scope_on_us} onChange={set("scope_on_us")} placeholder="e.g. material lifting and shifting" />
            </Field>
            <Field label="On the client (comma between items)">
              <input value={f.scope_on_client} onChange={set("scope_on_client")} placeholder="e.g. water, electricity" />
            </Field>
            <div className="form-actions">
              <Button variant="primary" type="submit" disabled={busy}>
                Save the terms
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

// --- the client's corrections and approvals in the measurement book -------------------------------

type Change = { id: number; status: string };

/** Accept (the line takes the client's value) or Dispute (with our reason: the line goes back to the client) a pending correction. */
export function ChangeAnswer({ change, onDone, onError }: { change: Change; onDone: () => void; onError: (e: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  if (change.status !== "pending") return null;
  const answer = async (accept: boolean) => {
    let reply: string | null = null;
    if (!accept) {
      reply = window.prompt("Why we dispute the correction (the client sees it)", "");
      if (reply === null || !reply.trim()) return;
    }
    setBusy(true);
    onError(null);
    try {
      await api(`/api/closeout/measurement-changes/${change.id}/answer`, { method: "POST", json: { accept, reply } });
      onDone();
    } catch (e) {
      onError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="m-change-actions">
      {" "}
      <Button size="small" variant="primary" disabled={busy} onClick={() => void answer(true)}>
        Accept
      </Button>{" "}
      <Button size="small" disabled={busy} onClick={() => void answer(false)}>
        Dispute…
      </Button>
    </span>
  );
}

/** The client signed the paper sheet: record who approved it, the date and the signed copy (the line is approved and locked). */
export function RecordApproval({ lineId, onDone }: { lineId: number; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [on, setOn] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return setError("Upload the signed sheet (photo or scan)");
    setBusy(true);
    setError(null);
    try {
      await upload(`/api/closeout/measurements/${lineId}/record-approval`, file, on ? { approved_name: name.trim(), on_date: on } : { approved_name: name.trim() });
      setOpen(false);
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        Record the client's signed sheet
      </Button>
      {open && (
        <Modal title="The client approved it on paper" onClose={() => setOpen(false)}>
          <form onSubmit={(e) => void submit(e)}>
            {error && <div className="alert alert-error">{error}</div>}
            <p className="small muted">The line is approved as signed and locked. It shows "recorded by staff".</p>
            <Field label="Approved by (the client's person)">
              <input required minLength={2} maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <DateField label="Signed on (empty: today)" value={on} onChange={setOn} />
            <Field label="The signed sheet" as="div">
              <FilePicker label="Photo or scan" accept="image/*,.pdf" onFiles={(f) => setFile(f[0] ?? null)} />
            </Field>
            <div className="form-actions">
              <Button variant="primary" type="submit" disabled={busy || name.trim().length < 2 || !file}>
                Record the approval
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

/** The site's switch: the client approves each line, or lines are approved when written. */
export function ApprovalSwitch({ siteId, needs, onDone, onError }: { siteId: string | number; needs: boolean; onDone: () => void; onError: (e: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  const flip = async () => {
    const ask = needs
      ? "Lines written from now on are approved at once (lines already sent stay with the client). Switch the client's approval off?"
      : "Lines written from now on go to the client for approval. Switch the client's approval on?";
    if (!window.confirm(ask)) return;
    setBusy(true);
    onError(null);
    try {
      await api(`/api/closeout/sites/${siteId}/measurement-approval`, { method: "PUT", json: { needs_approval: !needs } });
      onDone();
    } catch (e) {
      onError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button size="small" disabled={busy} onClick={() => void flip()}>
      {needs ? "Client approval: on (switch off)" : "Client approval: off (switch on)"}
    </Button>
  );
}

// --- labour claims ----------------------------------------------------------------------------------

type Place = { id: number; path: string };
type Item = { id: number; description: string; unit: string };

/** The id of the claim just made: the claims come back in id order, the new one last. */
export function newestId(rows: { id: number }[]): number | null {
  return rows.length ? Math.max(...rows.map((r) => r.id)) : null;
}

/** Enter a claim: the contractor's claimed quantity for an area (and item), the month, a note and photos. */
export function LabourClaimForm({ siteId, onSaved }: { siteId: string | number; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<{ places: Place[]; lines: Item[] } | null>(null);
  const [f, setF] = useState({ contractor: "", node_id: "", contract_line_id: "", claimed_qty: "", unit: "sqm", period: new Date().toISOString().slice(0, 7), note: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open && !opts) api<{ places: Place[]; lines: Item[] }>(`/api/closeout/sites/${siteId}/measure-form`).then(setOpts, (e) => (setOpts({ places: [], lines: [] }), setError(errorText(e))));
  }, [open, opts, siteId]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const rows = await api<{ id: number }[]>(`/api/closeout/sites/${siteId}/labour-claims`, {
        method: "POST",
        json: {
          contractor: f.contractor.trim(),
          node_id: f.node_id ? Number(f.node_id) : null,
          contract_line_id: f.contract_line_id ? Number(f.contract_line_id) : null,
          claimed_qty: f.claimed_qty.trim(),
          unit: f.unit.trim() || null,
          period: f.period || null,
          note: f.note.trim() || null,
        },
      });
      const cid = newestId(rows);
      for (const file of cid ? files : []) await upload(`/api/closeout/labour-claims/${cid}/photos`, file);
      setOpen(false);
      setF({ ...f, contractor: "", node_id: "", contract_line_id: "", claimed_qty: "", note: "" });
      setFiles([]);
      onSaved();
    } catch (err) {
      setError(errorText(err));
      onSaved();
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        Enter a claim
      </Button>
      {open && (
        <Modal title="A labour contractor's claim" onClose={() => setOpen(false)}>
          <form onSubmit={(e) => void submit(e)}>
            {error && <div className="alert alert-error">{error}</div>}
            <p className="small muted">The claimed quantity is checked against the approved measurement of the area. Paying more than approved needs the director.</p>
            <Field label="Contractor">
              <input required minLength={2} maxLength={200} value={f.contractor} onChange={(e) => setF({ ...f, contractor: e.target.value })} />
            </Field>
            <Field label="Area (empty: the whole site)">
              <select value={f.node_id} onChange={(e) => setF({ ...f, node_id: e.target.value })}>
                <option value="">The whole site</option>
                {(opts?.places ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.path}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Item (empty: every item)">
              <select
                value={f.contract_line_id}
                onChange={(e) => {
                  const ln = opts?.lines.find((l) => String(l.id) === e.target.value);
                  setF({ ...f, contract_line_id: e.target.value, unit: ln?.unit ?? f.unit });
                }}
              >
                <option value="">Every item</option>
                {(opts?.lines ?? []).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.description.slice(0, 60)} · per {l.unit}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid-2">
              <Field label="Claimed quantity">
                <input required inputMode="decimal" value={f.claimed_qty} onChange={(e) => setF({ ...f, claimed_qty: e.target.value })} />
              </Field>
              <Field label="Unit">
                <input value={f.unit} maxLength={20} onChange={(e) => setF({ ...f, unit: e.target.value })} />
              </Field>
              <Field label="Month">
                <input type="month" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })} />
              </Field>
            </div>
            <Field label="Note (optional)">
              <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
            </Field>
            <Field label="Photos of the claimed work (optional)" as="div">
              <FilePicker label="Choose photos" accept="image/*,.pdf" multiple onFiles={setFiles} />
            </Field>
            <div className="form-actions">
              <Button variant="primary" type="submit" disabled={busy || f.contractor.trim().length < 2 || !f.claimed_qty.trim()}>
                Save the claim
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

/** Add photos to an open claim (each uploaded at once). */
export function ClaimPhotos({ claimId, onDone, onError }: { claimId: number; onDone: () => void; onError: (e: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  const add = async (files: File[]) => {
    setBusy(true);
    onError(null);
    try {
      for (const f of files) await upload(`/api/closeout/labour-claims/${claimId}/photos`, f);
    } catch (e) {
      onError(errorText(e));
    } finally {
      setBusy(false);
      onDone();
    }
  };
  return <FilePicker size="small" label={busy ? "Uploading…" : "Add photos"} accept="image/*,.pdf" multiple disabled={busy} showChosen={false} onFiles={(f) => void add(f)} />;
}
