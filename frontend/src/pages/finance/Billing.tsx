import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { AgeingRow, Contract, FinanceLookups, Invoice, RaBill, Receipt } from "../../finance/types";
import { shortDate } from "../Tenders";

const RA_BADGE: Record<string, string> = { draft: "badge-muted", submitted: "badge-info", certified: "badge-ok", invoiced: "badge-ok", cancelled: "badge-danger" };

export function useFinanceLookups() {
  const [l, setL] = useState<FinanceLookups | null>(null);
  useEffect(() => {
    api<FinanceLookups>("/api/finance/lookups").then(setL, () => setL(null));
  }, []);
  return l;
}

const pdf = (path: string, onError: (e: string) => void) => void downloadFile(path).catch((err) => onError(errorText(err)));

/** A site's contract, RA bills and invoices (also the site page's Finance tab). */
export function SiteBilling({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const edit = can("billing.edit");
  const [contract, setContract] = useState<Contract | null | undefined>(undefined);
  const [bills, setBills] = useState<RaBill[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [open, setOpen] = useState<RaBill | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setContract(await api<Contract | null>(`/api/finance/sites/${siteId}/contract`));
      setBills(await api<RaBill[]>(`/api/finance/ra-bills?site_id=${siteId}`));
      setInvoices(await api<Invoice[]>(`/api/finance/invoices?site_id=${siteId}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [siteId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run<T>(p: Promise<T>): Promise<T | null> {
    setError(null);
    try {
      const r = await p;
      await load();
      return r;
    } catch (err) {
      setError(errorText(err));
      return null;
    }
  }

  if (contract === undefined) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {!contract ? (
        <div className="card">
          <p>No client contract yet.</p>
          {edit && (
            <button className="btn btn-primary" onClick={() => void run(api(`/api/finance/sites/${siteId}/contract`, { method: "POST", json: {} }))}>
              Make the contract from the won tender
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="tiles">
            <div className="tile">
              <div className="tile-title">Contract value</div>
              <b>{inr(contract.contract_value)}</b>
              <div className="small muted">
                {contract.client_name} · GST {num(contract.gst_percent)}% · SAC {contract.sac}
              </div>
            </div>
            <div className="tile">
              <div className="tile-title">Terms</div>
              <div className="small">
                Retention {num(contract.retention_percent)}% · TDS {num(contract.tds_percent)}%
                {Number(contract.gst_tds_percent) ? ` · GST TDS ${num(contract.gst_tds_percent)}%` : ""}
              </div>
              <div className="small">
                Advance {inr(contract.advance_amount)} (left {inr(contract.advance_left)}) at {num(contract.advance_recovery_percent)}% a bill
              </div>
            </div>
          </div>
          <div className="page-actions top-gap">
            {edit && (
              <button
                className="btn btn-primary"
                onClick={() => void run(api<RaBill>(`/api/finance/contracts/${contract.id}/ra-bills`, { method: "POST", json: {} })).then((b) => b && setOpen(b))}
              >
                New RA bill (from progress)
              </button>
            )}
            {edit && <ExtraItem contract={contract} onSaved={load} />}
          </div>
          <div className="card table-wrap top-gap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>RA bill</th>
                  <th>Period to</th>
                  <th className="num">Submitted</th>
                  <th className="num">Certified</th>
                  <th className="num">Net</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {bills.map((b) => (
                  <tr key={b.id} className="clickable" onClick={() => setOpen(b)}>
                    <td>
                      <code>{b.code}</code>
                    </td>
                    <td>{shortDate(b.period_to)}</td>
                    <td className="num">{inr(b.gross)}</td>
                    <td className="num">{b.certified_gross ? inr(b.certified_gross) : "—"}</td>
                    <td className="num">{inr(b.net)}</td>
                    <td>
                      <span className={`badge ${RA_BADGE[b.status]}`}>{b.status}</span> {b.invoice_number && <span className="small">{b.invoice_number}</span>}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <button className="btn btn-small" onClick={() => pdf(`/api/finance/ra-bills/${b.id}/pdf`, setError)}>
                        PDF
                      </button>
                    </td>
                  </tr>
                ))}
                {bills.length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      No RA bills yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <h2 className="section-title top-gap">Invoices</h2>
          <InvoiceTable invoices={invoices} onChange={load} />
        </>
      )}
      {open && <RaEditor bill={open} onClose={() => setOpen(null)} onChange={async (b) => (await load(), setOpen(b))} />}
    </>
  );
}

function ExtraItem({ contract, onSaved }: { contract: Contract; onSaved: () => Promise<void> }) {
  const [openForm, setOpenForm] = useState(false);
  const [form, setForm] = useState({ description: "", unit: "sqm", qty: "", rate: "" });
  const [error, setError] = useState<string | null>(null);
  const { can } = useAuth();
  const pending = contract.lines.filter((l) => l.is_extra && !l.approved);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/finance/contracts/${contract.id}/extra-items`, { method: "POST", json: form });
      setOpenForm(false);
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <>
      <button className="btn" onClick={() => setOpenForm(true)}>
        Extra item
      </button>
      {pending.length > 0 &&
        can("billing.approve") &&
        pending.map((l) => (
          <button key={l.id} className="btn btn-small" onClick={() => void api(`/api/finance/contract-lines/${l.id}/approve`, { method: "POST" }).then(onSaved)}>
            Approve extra: {l.description.slice(0, 30)}
          </button>
        ))}
      {openForm && (
        <Modal title="Extra item beyond the BOQ" onClose={() => setOpenForm(false)}>
          <form onSubmit={submit}>
            {error && <div className="alert alert-error">{error}</div>}
            <p className="small muted">An extra item is billable once approved (billing.approve).</p>
            <label className="field">
              <span>Description</span>
              <input required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <div className="grid-2">
              <label className="field">
                <span>Unit</span>
                <input required value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
              </label>
              <label className="field">
                <span>Qty</span>
                <input required inputMode="decimal" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
              </label>
              <label className="field">
                <span>Rate</span>
                <input required inputMode="decimal" value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} />
              </label>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary">Add</button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function RaEditor({ bill, onClose, onChange }: { bill: RaBill; onClose: () => void; onChange: (b: RaBill) => Promise<void> }) {
  const { can } = useAuth();
  const edit = can("billing.edit");
  const [qty, setQty] = useState<Record<number, string>>(Object.fromEntries(bill.lines.map((l) => [l.contract_line_id, bill.status === "submitted" ? l.qty : l.qty])));
  const [cert, setCert] = useState<Record<number, string>>(Object.fromEntries(bill.lines.map((l) => [l.contract_line_id, l.certified_qty ?? l.qty])));
  const [other, setOther] = useState({ amount: bill.other_deduction, remark: bill.other_deduction_remark ?? "", by: bill.certified_by_client ?? "" });
  const [error, setError] = useState<string | null>(null);

  async function call(path: string, method: string, json?: unknown) {
    setError(null);
    try {
      await onChange(await api<RaBill>(`/api/finance/ra-bills/${bill.id}${path}`, { method, json }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const draft = bill.status === "draft";
  const certifying = bill.status === "submitted";
  return (
    <Modal title={`${bill.code} · ${bill.client_name ?? ""}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p>
        <span className={`badge ${RA_BADGE[bill.status]}`}>{bill.status}</span> <span className="small muted">period to {shortDate(bill.period_to)}</span>
      </p>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">BOQ</th>
              <th className="num">Previous</th>
              <th className="num">Suggested</th>
              <th className="num">This bill</th>
              <th className="num">Certified</th>
              <th className="num">Cumulative</th>
              <th className="num">Rate</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {bill.lines.map((l) => (
              <tr key={l.id}>
                <td>
                  {l.item_no && <b>{l.item_no} </b>}
                  {l.description.slice(0, 70)} {l.is_extra && <span className="badge badge-warn">extra</span>}
                </td>
                <td className="num">
                  {num(l.boq_qty)} {l.unit}
                </td>
                <td className="num">{num(l.previous_qty)}</td>
                <td className="num muted">{num(l.suggested_qty)}</td>
                <td className="num">
                  {draft && edit ? (
                    <input
                      className="input-num"
                      inputMode="decimal"
                      value={qty[l.contract_line_id] ?? ""}
                      onChange={(e) => setQty({ ...qty, [l.contract_line_id]: e.target.value })}
                    />
                  ) : (
                    num(l.qty)
                  )}
                </td>
                <td className="num">
                  {certifying && edit ? (
                    <input
                      className="input-num"
                      inputMode="decimal"
                      value={cert[l.contract_line_id] ?? ""}
                      onChange={(e) => setCert({ ...cert, [l.contract_line_id]: e.target.value })}
                    />
                  ) : l.certified_qty !== null ? (
                    num(l.certified_qty)
                  ) : (
                    "—"
                  )}
                </td>
                <td className="num">{num(l.cumulative_qty)}</td>
                <td className="num">{inr(l.rate)}</td>
                <td className="num">{inr(l.certified_amount ?? l.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <table className="totals po-totals">
        <tbody>
          <tr>
            <td>Gross (submitted)</td>
            <td className="num">{inr(bill.gross)}</td>
          </tr>
          {bill.certified_gross && (
            <tr>
              <td>Gross (certified)</td>
              <td className="num">{inr(bill.certified_gross)}</td>
            </tr>
          )}
          <tr>
            <td>Retention {num(bill.retention_percent)}%</td>
            <td className="num">-{inr(bill.retention)}</td>
          </tr>
          <tr>
            <td>Advance recovery</td>
            <td className="num">-{inr(bill.advance_recovery)}</td>
          </tr>
          <tr>
            <td>Other {bill.other_deduction_remark ? `(${bill.other_deduction_remark})` : ""}</td>
            <td className="num">-{inr(bill.other_deduction)}</td>
          </tr>
          <tr className="grand">
            <td>Net</td>
            <td className="num">{inr(bill.net)}</td>
          </tr>
        </tbody>
      </table>
      {(draft || certifying) && edit && (
        <div className="grid-2">
          <label className="field">
            <span>Other deduction (₹)</span>
            <input inputMode="decimal" value={other.amount} onChange={(e) => setOther({ ...other, amount: e.target.value })} />
          </label>
          <label className="field">
            <span>Reason</span>
            <input value={other.remark} onChange={(e) => setOther({ ...other, remark: e.target.value })} />
          </label>
          {certifying && (
            <label className="field">
              <span>Certified by (client)</span>
              <input value={other.by} onChange={(e) => setOther({ ...other, by: e.target.value })} />
            </label>
          )}
        </div>
      )}
      <div className="form-actions">
        <button className="btn" onClick={() => pdf(`/api/finance/ra-bills/${bill.id}/pdf`, setError)}>
          PDF
        </button>
        {draft && edit && (
          <>
            <button
              className="btn"
              onClick={() =>
                void call("", "PUT", {
                  lines: Object.entries(qty).map(([k, v]) => ({ contract_line_id: Number(k), qty: v || "0" })),
                  other_deduction: other.amount || "0",
                  other_deduction_remark: other.remark || null,
                })
              }
            >
              Save
            </button>
            <button className="btn btn-primary" onClick={() => void call("/submit", "POST")}>
              Submit to client
            </button>
          </>
        )}
        {certifying && edit && (
          <button
            className="btn btn-primary"
            onClick={() =>
              void call("/certify", "POST", {
                lines: Object.entries(cert).map(([k, v]) => ({ contract_line_id: Number(k), certified_qty: v || "0" })),
                certified_by_client: other.by || null,
                other_deduction: other.amount || "0",
                other_deduction_remark: other.remark || null,
              })
            }
          >
            Record certification
          </button>
        )}
        {bill.status === "certified" && edit && (
          <button className="btn btn-primary" onClick={() => void call("/invoice", "POST", {})}>
            Raise tax invoice
          </button>
        )}
        {["draft", "submitted", "certified"].includes(bill.status) && edit && (
          <button className="btn btn-danger" onClick={() => confirm(`Cancel ${bill.code}? It keeps its number.`) && void call("/cancel", "POST")}>
            Cancel bill
          </button>
        )}
      </div>
    </Modal>
  );
}

export function InvoiceTable({ invoices, onChange }: { invoices: Invoice[]; onChange: () => Promise<void> }) {
  const { can } = useAuth();
  const [error, setError] = useState<string | null>(null);
  async function creditNote(inv: Invoice) {
    const amount = prompt(`Credit note on ${inv.number}: taxable amount (₹)?`);
    if (!amount) return;
    const reason = prompt("Reason?");
    if (!reason) return;
    try {
      await api(`/api/finance/invoices/${inv.id}/credit-note`, { method: "POST", json: { taxable: amount, reason } });
      await onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div className="card table-wrap">
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Number</th>
            <th>Date</th>
            <th>Client</th>
            <th className="num">Taxable</th>
            <th className="num">GST</th>
            <th className="num">Total</th>
            <th className="num">Outstanding</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {invoices.map((i) => (
            <tr key={i.id} className={i.kind === "credit_note" ? "row-muted" : ""}>
              <td className="nowrap">
                <code>{i.number}</code> {i.kind === "credit_note" && <span className="badge badge-warn">credit note</span>}
              </td>
              <td className="nowrap">{shortDate(i.invoice_date)}</td>
              <td>
                {i.client_name} {i.site_code && <span className="muted small">{i.site_code}</span>}
              </td>
              <td className="num">{inr(i.taxable)}</td>
              <td className="num small">{i.interstate ? `IGST ${inr(i.igst)}` : `C+S ${inr(Number(i.cgst) + Number(i.sgst))}`}</td>
              <td className="num">{inr(i.total)}</td>
              <td className="num">
                {i.outstanding !== null ? inr(i.outstanding) : ""}
                {i.retention_held && Number(i.retention_held) > 0 && <div className="small muted">retention {inr(i.retention_held)}</div>}
              </td>
              <td className="nowrap">
                <button className="btn btn-small" onClick={() => pdf(`/api/finance/invoices/${i.id}/pdf`, setError)}>
                  PDF
                </button>
                {i.kind === "invoice" && can("billing.approve") && (
                  <button className="btn btn-small" onClick={() => void creditNote(i)}>
                    Credit note
                  </button>
                )}
              </td>
            </tr>
          ))}
          {invoices.length === 0 && (
            <tr>
              <td colSpan={8} className="empty">
                No invoices.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ReceiptForm({ lookups, onClose, onSaved }: { lookups: FinanceLookups; onClose: () => void; onSaved: () => void }) {
  const [clientId, setClientId] = useState<number | "">("");
  const [open, setOpen] = useState<Invoice[]>([]);
  const [form, setForm] = useState({
    mode: "neft",
    ref_no: "",
    bank_account_id: "",
    amount: "",
    tds_amount: "",
    gst_tds_amount: "",
    write_off: "",
    write_off_reason: "",
    is_advance: false,
  });
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!clientId) return;
    api<Invoice[]>(`/api/finance/invoices?client_id=${clientId}`).then(
      (l) => setOpen(l.filter((i) => i.kind === "invoice" && Number(i.outstanding) > 0)),
      () => setOpen([]),
    );
  }, [clientId]);

  const settled = ["amount", "tds_amount", "gst_tds_amount", "write_off"].reduce((s, k) => s + Number(form[k as keyof typeof form] || 0), 0);
  const allocated = Object.values(alloc).reduce((s, v) => s + Number(v || 0), 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const json = {
      client_id: clientId,
      ...form,
      bank_account_id: form.bank_account_id ? Number(form.bank_account_id) : null,
      amount: form.amount || "0",
      tds_amount: form.tds_amount || "0",
      gst_tds_amount: form.gst_tds_amount || "0",
      write_off: form.write_off || "0",
      write_off_reason: form.write_off_reason || null,
      allocations: form.is_advance
        ? []
        : Object.entries(alloc)
            .filter(([, v]) => Number(v) > 0)
            .map(([k, v]) => ({ invoice_id: Number(k), amount: v })),
    };
    try {
      await api("/api/finance/receipts", { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <Modal title="Receipt from a client" onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-4">
          <label className="field">
            <span>Client *</span>
            <select required value={clientId} onChange={(e) => setClientId(Number(e.target.value) || "")}>
              <option value="">—</option>
              {lookups.clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Mode</span>
            <select value={form.mode} onChange={set("mode")}>
              {["neft", "rtgs", "cheque", "upi", "cash"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Ref / UTR / cheque no</span>
            <input value={form.ref_no} onChange={set("ref_no")} />
          </label>
          <label className="field">
            <span>Into bank</span>
            <select value={form.bank_account_id} onChange={set("bank_account_id")}>
              <option value="">—</option>
              {lookups.banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Received (₹)</span>
            <input inputMode="decimal" value={form.amount} onChange={set("amount")} />
          </label>
          <label className="field">
            <span>Client TDS, income tax (₹)</span>
            <input inputMode="decimal" value={form.tds_amount} onChange={set("tds_amount")} />
          </label>
          <label className="field">
            <span>GST TDS (₹)</span>
            <input inputMode="decimal" value={form.gst_tds_amount} onChange={set("gst_tds_amount")} />
          </label>
          <label className="field">
            <span>Short payment / write-off (₹)</span>
            <input inputMode="decimal" value={form.write_off} onChange={set("write_off")} />
          </label>
        </div>
        {Number(form.write_off) > 0 && (
          <label className="field">
            <span>Reason for the write-off *</span>
            <input required value={form.write_off_reason} onChange={set("write_off_reason")} />
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={form.is_advance} onChange={(e) => setForm({ ...form, is_advance: e.target.checked })} /> Mobilisation advance (not against invoices)
        </label>
        {!form.is_advance && (
          <table className="table compact top-gap">
            <thead>
              <tr>
                <th>Invoice</th>
                <th className="num">Outstanding</th>
                <th className="num">Due now</th>
                <th className="num">Settle</th>
              </tr>
            </thead>
            <tbody>
              {open.map((i) => (
                <tr key={i.id}>
                  <td>
                    {i.number} <span className="muted small">{shortDate(i.invoice_date)}</span>
                  </td>
                  <td className="num">{inr(i.outstanding)}</td>
                  <td className="num">{inr(i.due)}</td>
                  <td className="num">
                    <input className="input-num" inputMode="decimal" value={alloc[i.id] ?? ""} onChange={(e) => setAlloc({ ...alloc, [i.id]: e.target.value })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="right small">
          Received + TDS + GST TDS + write-off = <b>{inr(settled)}</b>
          {!form.is_advance && <> · spread over invoices {inr(allocated)}</>}
        </p>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!form.is_advance && Math.abs(settled - allocated) > 0.004}>
            Save receipt
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Billing() {
  const { can } = useAuth();
  const lookups = useFinanceLookups();
  const [tab, setTab] = useState<"sites" | "invoices" | "receipts" | "ageing">("sites");
  const [siteId, setSiteId] = useState<number | "">("");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [ageing, setAgeing] = useState<{ rows: AgeingRow[]; totals: Record<string, string> } | null>(null);
  const [receiving, setReceiving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      if (tab === "invoices") setInvoices(await api<Invoice[]>("/api/finance/invoices"));
      if (tab === "receipts") setReceipts(await api<Receipt[]>("/api/finance/receipts"));
      if (tab === "ageing") setAgeing(await api("/api/finance/ageing"));
    } catch (err) {
      setError(errorText(err));
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <h1>Client billing</h1>
        <div className="page-actions">
          <div className="tabs">
            {(
              [
                ["sites", "RA bills by site"],
                ["invoices", "Invoices"],
                ["receipts", "Receipts"],
                ["ageing", "Ageing"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {l}
              </button>
            ))}
          </div>
          {can("billing.edit") && (
            <button className="btn btn-primary" onClick={() => setReceiving(true)}>
              New receipt
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "sites" && lookups && (
        <>
          <select value={siteId} onChange={(e) => setSiteId(Number(e.target.value) || "")} aria-label="Site">
            <option value="">Pick a site…</option>
            {lookups.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} {s.name}
              </option>
            ))}
          </select>
          <div className="top-gap">{siteId && <SiteBilling key={siteId} siteId={siteId} />}</div>
        </>
      )}
      {tab === "invoices" && <InvoiceTable invoices={invoices} onChange={load} />}
      {tab === "receipts" && (
        <div className="card table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Number</th>
                <th>Date</th>
                <th>Client</th>
                <th>Mode</th>
                <th className="num">Received</th>
                <th className="num">TDS</th>
                <th className="num">GST TDS</th>
                <th>Against</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((r) => (
                <tr key={r.id}>
                  <td>
                    <code>{r.number}</code> {r.is_advance && <span className="badge badge-info">advance</span>}{" "}
                    {r.is_retention && <span className="badge badge-info">retention</span>}
                  </td>
                  <td>{shortDate(r.on_date)}</td>
                  <td>{r.client_name}</td>
                  <td>
                    {r.mode} {r.ref_no}
                  </td>
                  <td className="num">{inr(r.amount)}</td>
                  <td className="num">{inr(r.tds_amount)}</td>
                  <td className="num">{inr(r.gst_tds_amount)}</td>
                  <td className="small">{r.allocations.map((a) => `${a.number} ${inr(a.amount)}`).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "ageing" && ageing && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Client</th>
                {["0-30", "31-60", "61-90", "90+"].map((b) => (
                  <th key={b} className="num">
                    {b} days
                  </th>
                ))}
                <th className="num">Due</th>
                <th className="num">Retention held</th>
              </tr>
            </thead>
            <tbody>
              {ageing.rows.map((r) => (
                <tr key={r.client_id}>
                  <td>{r.client_name}</td>
                  {(["0-30", "31-60", "61-90", "90+"] as const).map((b) => (
                    <td key={b} className={`num ${b === "90+" && Number(r[b]) > 0 ? "text-danger" : ""}`}>
                      {inr(r[b])}
                    </td>
                  ))}
                  <td className="num">
                    <b>{inr(r.due)}</b>
                  </td>
                  <td className="num">{inr(r.retention_held)}</td>
                </tr>
              ))}
              <tr className="grand">
                <td>Total</td>
                {["0-30", "31-60", "61-90", "90+", "due", "retention_held"].map((k) => (
                  <td key={k} className="num">
                    {inr(ageing.totals[k])}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {receiving && lookups && <ReceiptForm lookups={lookups} onClose={() => setReceiving(false)} onSaved={() => (setReceiving(false), void load())} />}
    </>
  );
}
