import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { FinanceLookups, Payment, SubconBill, VendorBill } from "../../finance/types";
import { shortDate } from "../Tenders";
import { useFinanceLookups } from "./Billing";

type Vendor = { id: number; name: string; type: string; gstin: string | null };
type GrnRow = {
  id: number;
  code: string;
  received_at: string;
  invoice_no: string | null;
  lines: { id: number; product_name: string; unit: string; accepted_qty: string; rate: string }[];
};
type Due = { id: number; number: string; vendor_id: number; vendor_name: string; bill_no: string; due_date: string; outstanding: string; overdue: boolean };
type WoRow = { id: number; code: string; site_code: string; subcontractor_name: string; status: string };

const BADGE: Record<string, string> = {
  draft: "badge-muted",
  approved: "badge-info",
  partly_paid: "badge-warn",
  paid: "badge-ok",
  cancelled: "badge-danger",
  pending_approval: "badge-warn",
};

function BillForm({ vendors, onClose, onSaved }: { vendors: Vendor[]; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    vendor_id: "" as number | "",
    kind: "material",
    bill_no: "",
    bill_date: new Date().toISOString().slice(0, 10),
    due_date: "",
    tds_percent: "",
    remark: "",
  });
  const [grns, setGrns] = useState<GrnRow[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [over, setOver] = useState<Record<number, { qty?: string; rate?: string }>>({});
  const [direct, setDirect] = useState([{ description: "", qty: "1", rate: "", gst_percent: "18" }]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!form.vendor_id) return;
    api<GrnRow[]>(`/api/finance/vendors/${form.vendor_id}/unbilled-grns`).then(setGrns, () => setGrns([]));
  }, [form.vendor_id]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const fromGrn = form.kind === "material" && picked.length > 0;
    const json = {
      ...form,
      due_date: form.due_date || null,
      tds_percent: form.tds_percent || null,
      remark: form.remark || null,
      grn_ids: fromGrn ? picked : [],
      grn_lines: fromGrn
        ? Object.entries(over)
            .filter(([, v]) => v.qty || v.rate)
            .map(([k, v]) => ({ grn_line_id: Number(k), qty: v.qty || null, rate: v.rate || null }))
        : [],
      lines: fromGrn ? [] : direct.filter((l) => l.description && l.rate),
    };
    try {
      await api("/api/finance/vendor-bills", { method: "POST", json });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title="Vendor bill" onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-4">
          <label className="field">
            <span>Vendor *</span>
            <select required value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: Number(e.target.value) || "" })}>
              <option value="">—</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.type.replace("_", " ")})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Kind</span>
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="material">Material (from GRNs)</option>
              <option value="service">Service</option>
              <option value="freight">Transporter freight</option>
            </select>
          </label>
          <label className="field">
            <span>Vendor's bill no *</span>
            <input required value={form.bill_no} onChange={(e) => setForm({ ...form, bill_no: e.target.value })} />
          </label>
          <label className="field">
            <span>Bill date *</span>
            <input type="date" required value={form.bill_date} onChange={(e) => setForm({ ...form, bill_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Due (blank: payment terms)</span>
            <input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
          </label>
          <label className="field">
            <span>TDS % (blank: by vendor type)</span>
            <input inputMode="decimal" value={form.tds_percent} onChange={(e) => setForm({ ...form, tds_percent: e.target.value })} />
          </label>
        </div>
        {form.kind === "material" ? (
          <>
            <h2 className="section-title">GRNs not billed yet</h2>
            {grns.length === 0 && <p className="muted">None for this vendor.</p>}
            {grns.map((g) => (
              <div key={g.id} className="line-card top-gap">
                <label className="check">
                  <input type="checkbox" checked={picked.includes(g.id)} onChange={() => setPicked((p) => (p.includes(g.id) ? p.filter((x) => x !== g.id) : [...p, g.id]))} />{" "}
                  <b>{g.code}</b> · {shortDate(g.received_at)} {g.invoice_no && `· invoice ${g.invoice_no}`}
                </label>
                {picked.includes(g.id) && (
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>Item</th>
                        <th className="num">Accepted</th>
                        <th className="num">Billed qty</th>
                        <th className="num">PO rate</th>
                        <th className="num">Billed rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.lines.map((l) => (
                        <tr key={l.id}>
                          <td>{l.product_name}</td>
                          <td className="num">
                            {num(l.accepted_qty)} {l.unit}
                          </td>
                          <td className="num">
                            <input
                              className="input-num"
                              placeholder={num(l.accepted_qty)}
                              value={over[l.id]?.qty ?? ""}
                              onChange={(e) => setOver({ ...over, [l.id]: { ...over[l.id], qty: e.target.value } })}
                            />
                          </td>
                          <td className="num">{inr(l.rate)}</td>
                          <td className="num">
                            <input
                              className="input-num"
                              placeholder={num(l.rate)}
                              value={over[l.id]?.rate ?? ""}
                              onChange={(e) => setOver({ ...over, [l.id]: { ...over[l.id], rate: e.target.value } })}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
            <p className="small muted">Leave billed qty / rate blank when they match. Differences over the tolerance are flagged and must be accepted to approve.</p>
          </>
        ) : (
          <>
            <h2 className="section-title">Lines</h2>
            {direct.map((l, i) => (
              <div key={i} className="line-row">
                <input
                  className="grow"
                  placeholder="Description"
                  value={l.description}
                  onChange={(e) => setDirect((d) => d.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                />
                <input className="input-num" placeholder="Qty" value={l.qty} onChange={(e) => setDirect((d) => d.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} />
                <input
                  className="input-num"
                  placeholder="Rate"
                  value={l.rate}
                  onChange={(e) => setDirect((d) => d.map((x, j) => (j === i ? { ...x, rate: e.target.value } : x)))}
                />
                <input
                  className="input-num"
                  placeholder="GST %"
                  value={l.gst_percent}
                  onChange={(e) => setDirect((d) => d.map((x, j) => (j === i ? { ...x, gst_percent: e.target.value } : x)))}
                />
              </div>
            ))}
            <button type="button" className="btn btn-small top-gap" onClick={() => setDirect((d) => [...d, { description: "", qty: "1", rate: "", gst_percent: "18" }])}>
              + Line
            </button>
          </>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Save bill</button>
        </div>
      </form>
    </Modal>
  );
}

function PayForm({ bills, lookups, onClose, onSaved }: { bills: VendorBill[]; lookups: FinanceLookups; onClose: () => void; onSaved: () => void }) {
  const payable = bills.filter((b) => ["approved", "partly_paid"].includes(b.status) && Number(b.outstanding) > 0);
  const vendors = [...new Map(payable.map((b) => [b.vendor_id, b.vendor_name])).entries()];
  const [vendorId, setVendorId] = useState<number | "">(vendors[0]?.[0] ?? "");
  const [form, setForm] = useState({ mode: "neft", ref_no: "", bank_account_id: "", on_date: new Date().toISOString().slice(0, 10) });
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/finance/payments", {
        method: "POST",
        json: {
          vendor_id: vendorId,
          ...form,
          ref_no: form.ref_no || null,
          bank_account_id: form.bank_account_id ? Number(form.bank_account_id) : null,
          allocations: Object.entries(alloc)
            .filter(([, v]) => Number(v) > 0)
            .map(([k, v]) => ({ vendor_bill_id: Number(k), amount: v })),
        },
      });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="Payment" onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-4">
          <label className="field">
            <span>Vendor</span>
            <select value={vendorId} onChange={(e) => setVendorId(Number(e.target.value) || "")}>
              {vendors.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Mode</span>
            <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              {["neft", "rtgs", "cheque", "upi", "cash"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Ref</span>
            <input value={form.ref_no} onChange={(e) => setForm({ ...form, ref_no: e.target.value })} />
          </label>
          <label className="field">
            <span>From bank</span>
            <select value={form.bank_account_id} onChange={(e) => setForm({ ...form, bank_account_id: e.target.value })}>
              <option value="">—</option>
              {lookups.banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <table className="table compact">
          <tbody>
            {payable
              .filter((b) => b.vendor_id === vendorId)
              .map((b) => (
                <tr key={b.id}>
                  <td>
                    {b.number}{" "}
                    <span className="muted small">
                      bill {b.bill_no}, due {shortDate(b.due_date)}
                    </span>
                  </td>
                  <td className="num">{inr(b.outstanding)}</td>
                  <td className="num">
                    <input className="input-num" inputMode="decimal" placeholder="pay" value={alloc[b.id] ?? ""} onChange={(e) => setAlloc({ ...alloc, [b.id]: e.target.value })} />
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary">Pay</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Payables() {
  const { can } = useAuth();
  const lookups = useFinanceLookups();
  const edit = can("payables.edit");
  const [tab, setTab] = useState<"bills" | "payments" | "due" | "ageing" | "subcon">("bills");
  const [bills, setBills] = useState<VendorBill[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [due, setDue] = useState<Due[]>([]);
  const [ageing, setAgeing] = useState<{ rows: Record<string, string | number>[]; totals: Record<string, string> } | null>(null);
  const [subcon, setSubcon] = useState<SubconBill[]>([]);
  const [wos, setWos] = useState<WoRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [dialog, setDialog] = useState<null | "bill" | "pay">(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBills(await api<VendorBill[]>("/api/finance/vendor-bills"));
      if (tab === "payments") setPayments(await api<Payment[]>("/api/finance/payments"));
      if (tab === "due") setDue(await api<Due[]>("/api/finance/payables/due"));
      if (tab === "ageing") setAgeing(await api("/api/finance/payables/ageing"));
      if (tab === "subcon") {
        setSubcon(await api<SubconBill[]>("/api/finance/subcon-bills"));
        setWos(await api<WoRow[]>("/api/execution/work-orders").catch(() => []));
      }
    } catch (err) {
      setError(errorText(err));
    }
  }, [tab]);

  useEffect(() => {
    void load();
    api<{ items: Vendor[] }>("/api/vendors?limit=500").then(
      (p) => setVendors(p.items),
      () => setVendors([]),
    );
  }, [load]);

  async function act(path: string, json?: unknown) {
    setError(null);
    try {
      await api(path, { method: "POST", json });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Payables</h1>
        <div className="page-actions">
          <div className="tabs">
            {(
              [
                ["bills", "Vendor bills"],
                ["payments", "Payments"],
                ["due", "Due this week"],
                ["ageing", "Ageing"],
                ["subcon", "Subcontractor bills"],
              ] as const
            ).map(([k, l]) => (
              <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {l}
              </button>
            ))}
          </div>
          {edit && (
            <>
              <button className="btn" onClick={() => setDialog("bill")}>
                New bill
              </button>
              <button className="btn btn-primary" onClick={() => setDialog("pay")}>
                Pay
              </button>
            </>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {tab === "bills" && (
        <div className="card table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Number</th>
                <th>Vendor / bill</th>
                <th className="num">Total</th>
                <th className="num">TDS</th>
                <th className="num">Payable</th>
                <th className="num">Outstanding</th>
                <th>Due</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr key={b.id}>
                  <td>
                    <code>{b.number}</code> <span className="muted small">{b.kind}</span>
                  </td>
                  <td>
                    {b.vendor_name} <span className="muted small">#{b.bill_no}</span>
                    {b.grns.length > 0 && <div className="small muted">{b.grns.join(", ")}</div>}
                    {b.match_issues.map((m, i) => (
                      <div key={i} className="small text-warn">
                        ⚠ {m.message}
                      </div>
                    ))}
                    {b.blocked_reasons.length > 0 && (
                      <div className={`match-block ${b.blocked ? "" : "released"}`}>
                        {b.blocked_reasons.map((m, i) => (
                          <div key={i} className={`small ${b.blocked ? "text-danger" : "muted"}`}>
                            ⛔ {m.message}
                          </div>
                        ))}
                        {b.released_at && (
                          <div className="small muted">
                            Released by {b.released_by} on {shortDate(b.released_at)}: {b.release_reason}
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="num">{inr(b.total)}</td>
                  <td className="num">
                    {inr(b.tds_amount)} <span className="small muted">{b.tds_section}</span>
                  </td>
                  <td className="num">{inr(b.payable)}</td>
                  <td className="num">{inr(b.outstanding)}</td>
                  <td className="nowrap">{shortDate(b.due_date)}</td>
                  <td>
                    <span className={`badge ${BADGE[b.status]}`}>{b.status.replace("_", " ")}</span>
                    {b.blocked && <span className="badge badge-danger">blocked: 3-way match</span>}
                  </td>
                  <td className="nowrap">
                    {b.blocked && can("delivery.escalate") && (
                      <button
                        className="btn btn-small"
                        onClick={() => {
                          const reason = prompt("Release this bill for approval despite the match: why?");
                          if (reason && reason.trim().length >= 5) void act(`/api/sitecontrol/vendor-bills/${b.id}/release`, { reason: reason.trim() });
                        }}
                      >
                        Release
                      </button>
                    )}
                    {b.status === "draft" && edit && !b.blocked && (
                      <button
                        className="btn btn-small"
                        onClick={() =>
                          void act(`/api/finance/vendor-bills/${b.id}/approve`, {
                            accept_differences: b.match_issues.length > 0 && confirm("Accept the differences flagged on this bill?"),
                          })
                        }
                      >
                        Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "payments" && (
        <div className="card table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Number</th>
                <th>Date</th>
                <th>Vendor</th>
                <th>Mode</th>
                <th className="num">Amount</th>
                <th>Bills</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id}>
                  <td>
                    <code>{p.number}</code>
                  </td>
                  <td>{shortDate(p.on_date)}</td>
                  <td>{p.vendor_name}</td>
                  <td>
                    {p.mode} {p.ref_no}
                  </td>
                  <td className="num">{inr(p.amount)}</td>
                  <td className="small">{p.allocations.map((a) => a.number).join(", ")}</td>
                  <td>
                    <span className={`badge ${BADGE[p.status]}`}>{p.status.replace("_", " ")}</span>{" "}
                    {p.status === "pending_approval" && can("payables.approve") && (
                      <button className="btn btn-small btn-primary" onClick={() => void act(`/api/finance/payments/${p.id}/approve`)}>
                        Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "due" && (
        <div className="card table-wrap">
          <table className="table compact">
            <tbody>
              {due.map((d) => (
                <tr key={d.id}>
                  <td className={d.overdue ? "text-danger" : ""}>{shortDate(d.due_date)}</td>
                  <td>{d.vendor_name}</td>
                  <td>
                    {d.number} <span className="muted small">#{d.bill_no}</span>
                  </td>
                  <td className="num">{inr(d.outstanding)}</td>
                </tr>
              ))}
              {due.length === 0 && (
                <tr>
                  <td className="empty">Nothing due this week.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {tab === "ageing" && ageing && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th className="num">Not due</th>
                {["0-30", "31-60", "61-90", "90+"].map((b) => (
                  <th key={b} className="num">
                    {b} days late
                  </th>
                ))}
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {ageing.rows.map((r) => (
                <tr key={String(r.vendor_id)}>
                  <td>{String(r.vendor_name)}</td>
                  {["not_due", "0-30", "31-60", "61-90", "90+", "total"].map((k) => (
                    <td key={k} className="num">
                      {inr(String(r[k]))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "subcon" && (
        <>
          {edit && (
            <div className="page-actions">
              {wos
                .filter((w) => ["active", "completed"].includes(w.status))
                .map((w) => (
                  <button key={w.id} className="btn btn-small" onClick={() => void act(`/api/finance/work-orders/${w.id}/subcon-bills`, {})}>
                    Bill {w.code} ({w.subcontractor_name})
                  </button>
                ))}
            </div>
          )}
          <div className="card table-wrap top-gap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>Number</th>
                  <th>WO</th>
                  <th className="num">Gross</th>
                  <th className="num">Retention</th>
                  <th className="num">TDS</th>
                  <th className="num">Material</th>
                  <th className="num">GST</th>
                  <th className="num">Net</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {subcon.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <code>{b.number}</code>
                    </td>
                    <td>
                      {b.wo_code} <span className="muted small">{b.subcontractor_name}</span>
                    </td>
                    <td className="num">{inr(b.gross)}</td>
                    <td className="num">{inr(b.retention)}</td>
                    <td className="num">{inr(b.tds)}</td>
                    <td className="num">{inr(b.material_recovery)}</td>
                    <td className="num">{inr(b.gst)}</td>
                    <td className="num">
                      <b>{inr(b.net)}</b>
                    </td>
                    <td>
                      <span className={`badge ${BADGE[b.status]}`}>{b.status}</span> {b.vendor_bill_number}{" "}
                      {b.productivity_status === "low" && (
                        <span className={`badge ${b.productivity_override_note ? "badge-muted" : "badge-danger"}`} title={b.productivity_override_note ?? undefined}>
                          productivity low: {b.productivity?.actual} / {b.productivity?.expected} sqm per man-day{b.productivity_override_note ? " (overridden)" : ""}
                        </span>
                      )}
                      {b.productivity_status === "to_be_set" && <span className="badge badge-muted">productivity norm to be set</span>}
                      {b.status === "draft" && b.productivity_status === "low" && !b.productivity_override_note && can("labourcheck.override") && (
                        <button
                          className="btn btn-small"
                          onClick={() => {
                            const note = prompt("Override the labour check: note");
                            if (note && note.trim().length >= 5) void act(`/api/sitecontrol/subcon-bills/${b.id}/override`, { note: note.trim() });
                          }}
                        >
                          Override
                        </button>
                      )}{" "}
                      {b.status === "draft" && edit && (
                        <button className="btn btn-small btn-primary" onClick={() => void act(`/api/finance/subcon-bills/${b.id}/approve`)}>
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {dialog === "bill" && <BillForm vendors={vendors} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), void load())} />}
      {dialog === "pay" && lookups && <PayForm bills={bills} lookups={lookups} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), void load())} />}
    </>
  );
}
