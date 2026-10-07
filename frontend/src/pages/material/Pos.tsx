import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile, queryString } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr, num } from "../../format";
import { isInterstate, poTotals } from "../../material/gst";
import type { ChargeKind, Grn, Indent, MaterialLookups, Po } from "../../material/types";
import type { Page } from "../../types";
import { Pager } from "../Clients";
import { shortDate } from "../Tenders";
import { GrnForm } from "./Grns";
import { ProductSelect, StatusBadge, today, UnitSelect, useMaterialLookups } from "./common";

const STATUSES = ["draft", "pending_approval", "approved", "sent", "partly_received", "received", "closed", "cancelled"];

export default function Pos() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [page, setPage] = useState<Page<Po> | null>(null);
  const [filters, setFilters] = useState({ status: "", q: "" });
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Page<Po>>(`/api/material/pos${queryString({ ...filters, offset, limit: 50 })}`).then(setPage, (err) => setError(errorText(err)));
  }, [filters, offset]);

  return (
    <>
      <div className="page-header">
        <h1>Purchase orders</h1>
        <div className="page-actions">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters((f) => ({ ...f, q }));
            }}
          >
            <input className="search" placeholder="Search PO no or vendor" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          {can("po.edit") && (
            <button className="btn btn-primary" onClick={() => navigate("/purchase-orders/new")}>
              New PO
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>PO no</th>
              <th>Date</th>
              <th>Vendor</th>
              <th>Deliver to</th>
              <th className="num">Grand total</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((p) => (
              <tr key={p.id} className="clickable" onClick={() => navigate(`/purchase-orders/${p.id}`)}>
                <td className="nowrap">
                  <code>{p.code}</code>
                </td>
                <td className="nowrap">{shortDate(p.po_date)}</td>
                <td>{p.vendor_name}</td>
                <td>{p.store_name}</td>
                <td className="num">{inr(p.grand_total)}</td>
                <td>
                  <StatusBadge status={p.status} />
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No purchase orders.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {page && <Pager page={page} onOffset={setOffset} />}
    </>
  );
}

type Line = { indent_line_id: number | null; product_id: number | ""; qty: string; unit: string; rate: string; discount_percent: string; gst_percent: string };
type Charge = { kind: ChargeKind; description: string; amount: string; gst_percent: string; add_to_cost: boolean };

type PoHead = { vendor_id: number | ""; store_id: number | ""; from_gstin_id: number | ""; po_date: string; expected_delivery: string; payment_terms: string; remark: string };

const CHARGE_KINDS: ChargeKind[] = ["freight", "loading", "unloading", "packing", "other"];

export function PoForm({ po, lookups, onSaved, onCancel }: { po?: Po; lookups: MaterialLookups; onSaved: (p: Po) => void; onCancel: () => void }) {
  const [params] = useSearchParams();
  const defaultGstin = lookups.gstins.find((g) => g.is_default) ?? lookups.gstins[0];
  const [form, setForm] = useState<PoHead>({
    vendor_id: po?.vendor_id ?? ("" as number | ""),
    store_id: po?.store_id ?? lookups.stores.find((s) => s.kind === "godown")?.id ?? ("" as number | ""),
    from_gstin_id: po?.from_gstin_id ?? defaultGstin?.id ?? ("" as number | ""),
    po_date: po?.po_date ?? today(),
    expected_delivery: po?.expected_delivery ?? "",
    payment_terms: po?.payment_terms ?? "",
    remark: po?.remark ?? "",
  });
  const [indentIds, setIndentIds] = useState<number[]>(po?.indent_ids ?? []);
  const [lines, setLines] = useState<Line[]>(po?.lines.map((l) => ({ ...l, discount_percent: l.discount_percent, gst_percent: l.gst_percent })) ?? []);
  const [charges, setCharges] = useState<Charge[]>(po?.charges.map((c) => ({ ...c, description: c.description ?? "" })) ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // a new PO from indents: their outstanding product lines
  useEffect(() => {
    const ids = params.get("indents");
    if (po || !ids) return;
    void (async () => {
      const indents = await Promise.all(ids.split(",").map((i) => api<Indent>(`/api/material/indents/${i}`)));
      setIndentIds(indents.map((i) => i.id));
      if (indents.length === 1) {
        const store = lookups.stores.find((s) => s.id === indents[0].store_id);
        if (store) setForm((f) => ({ ...f, store_id: store.id }));
      }
      setLines(
        indents.flatMap((i) =>
          i.lines
            .filter((l) => l.product_id && Number(l.base_qty) > Number(l.ordered_qty))
            .map((l) => {
              const p = lookups.products.find((x) => x.id === l.product_id);
              return {
                indent_line_id: l.id,
                product_id: l.product_id as number,
                qty: String(Number(l.base_qty) - Number(l.ordered_qty)),
                unit: l.base_unit ?? p?.unit ?? "",
                rate: "",
                discount_percent: "0",
                gst_percent: p?.gst_percent ?? "18",
              };
            }),
        ),
      );
    })().catch((err) => setError(errorText(err)));
  }, [params, po, lookups]);

  const vendor = lookups.vendors.find((v) => v.id === form.vendor_id);
  const gstin = lookups.gstins.find((g) => g.id === form.from_gstin_id);
  const interstate = isInterstate(vendor, gstin);
  const totals = useMemo(() => poTotals(lines, charges, interstate), [lines, charges, interstate]);
  const limit = Number(lookups.settings.po_approval_limit);

  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const setCharge = (i: number, patch: Partial<Charge>) => setCharges((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      ...form,
      from_gstin_id: form.from_gstin_id || null,
      expected_delivery: form.expected_delivery || null,
      payment_terms: form.payment_terms || null,
      remark: form.remark || null,
      indent_ids: indentIds,
      lines: lines.map((l) => ({ ...l, unit: l.unit || null })),
      charges: charges.map((c) => ({ ...c, description: c.description || null })),
    };
    try {
      onSaved(po ? await api<Po>(`/api/material/pos/${po.id}`, { method: "PUT", json: body }) : await api<Po>("/api/material/pos", { method: "POST", json: body }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card">
        <div className="grid-4">
          <label className="field">
            <span>Vendor *</span>
            <select required value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: Number(e.target.value) || "" })}>
              <option value="">— vendor —</option>
              {lookups.vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Deliver to *</span>
            <select required value={form.store_id} onChange={(e) => setForm({ ...form, store_id: Number(e.target.value) })}>
              {lookups.stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Bill from (our GSTIN)</span>
            <select value={form.from_gstin_id} onChange={(e) => setForm({ ...form, from_gstin_id: Number(e.target.value) || "" })}>
              <option value="">—</option>
              {lookups.gstins.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.gstin} ({g.state})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>PO date</span>
            <input type="date" value={form.po_date} disabled={!!po} onChange={(e) => setForm({ ...form, po_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Expected delivery</span>
            <input type="date" value={form.expected_delivery} onChange={(e) => setForm({ ...form, expected_delivery: e.target.value })} />
          </label>
          <label className="field">
            <span>Payment terms</span>
            <input value={form.payment_terms} onChange={(e) => setForm({ ...form, payment_terms: e.target.value })} placeholder="e.g. 30 days from the invoice" />
          </label>
          <label className="field" style={{ gridColumn: "span 2" }}>
            <span>Remark</span>
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </label>
        </div>
        <p className="small muted">
          {vendor ? (interstate ? "Inter-state supply: IGST" : "Intra-state supply: CGST + SGST") : "Pick the vendor to see the GST split."}
          {indentIds.length > 0 && ` · for ${indentIds.length} indent(s)`}
        </p>
      </div>
      <div className="card top-gap table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Product</th>
              <th className="num">Qty</th>
              <th>Unit</th>
              <th className="num">Rate</th>
              <th className="num">Disc %</th>
              <th className="num">GST %</th>
              <th className="num">Taxable</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td>
                  <ProductSelect
                    required
                    products={lookups.products}
                    value={l.product_id}
                    onChange={(p) => setLine(i, { product_id: p?.id ?? "", unit: p?.unit ?? "", gst_percent: p?.gst_percent ?? "18", indent_line_id: null })}
                  />
                </td>
                <td>
                  <input className="input-num" required inputMode="decimal" value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} />
                </td>
                <td>
                  <UnitSelect units={lookups.units} value={l.unit} onChange={(u) => setLine(i, { unit: u })} />
                </td>
                <td>
                  <input className="input-num" required inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} />
                </td>
                <td>
                  <input className="input-num" inputMode="decimal" value={l.discount_percent} onChange={(e) => setLine(i, { discount_percent: e.target.value })} />
                </td>
                <td>
                  <input className="input-num" inputMode="decimal" value={l.gst_percent} onChange={(e) => setLine(i, { gst_percent: e.target.value })} />
                </td>
                <td className="num">{inr(totals.lineAmounts[i])}</td>
                <td>
                  <button type="button" className="btn btn-ghost btn-icon" aria-label="Remove" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => setLines((ls) => [...ls, { indent_line_id: null, product_id: "", qty: "", unit: "", rate: "", discount_percent: "0", gst_percent: "18" }])}
        >
          + Line
        </button>
        <h2 className="section-title top-gap">Charges</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Description</th>
              <th className="num">Amount</th>
              <th className="num">GST %</th>
              <th>Add to material cost</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {charges.map((c, i) => (
              <tr key={i}>
                <td>
                  <select value={c.kind} onChange={(e) => setCharge(i, { kind: e.target.value as ChargeKind })}>
                    {CHARGE_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input value={c.description} onChange={(e) => setCharge(i, { description: e.target.value })} />
                </td>
                <td>
                  <input className="input-num" inputMode="decimal" value={c.amount} onChange={(e) => setCharge(i, { amount: e.target.value })} />
                </td>
                <td>
                  <input className="input-num" inputMode="decimal" value={c.gst_percent} onChange={(e) => setCharge(i, { gst_percent: e.target.value })} />
                </td>
                <td>
                  <input type="checkbox" checked={c.add_to_cost} onChange={(e) => setCharge(i, { add_to_cost: e.target.checked })} aria-label="Add to material cost" />
                </td>
                <td>
                  <button type="button" className="btn btn-ghost btn-icon" aria-label="Remove" onClick={() => setCharges((cs) => cs.filter((_, j) => j !== i))}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => setCharges((cs) => [...cs, { kind: "freight", description: "Freight", amount: "", gst_percent: "18", add_to_cost: true }])}
        >
          + Charge
        </button>
        <TotalsBox
          t={{
            subtotal: totals.subtotal,
            discount: totals.discount,
            taxable: totals.taxable,
            charges: totals.charges,
            cgst: totals.cgst,
            sgst: totals.sgst,
            igst: totals.igst,
            roundOff: totals.roundOff,
            grand: totals.grandTotal,
          }}
          interstate={interstate}
        />
        <p className="small muted right">
          {totals.grandTotal > limit
            ? `Above the approval limit (${inr(limit)}): it will need a PO approver.`
            : `Within the approval limit (${inr(limit)}): you can approve it yourself.`}
        </p>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={busy || lines.length === 0}>
          {po ? "Save" : "Create draft PO"}
        </button>
      </div>
    </form>
  );
}

type T = {
  subtotal: number | string;
  discount: number | string;
  taxable: number | string;
  charges: number | string;
  cgst: number | string;
  sgst: number | string;
  igst: number | string;
  roundOff: number | string;
  grand: number | string;
};

export function TotalsBox({ t, interstate }: { t: T; interstate: boolean }) {
  return (
    <table className="totals po-totals">
      <tbody>
        <tr>
          <td>Sub total</td>
          <td className="num">{inr(t.subtotal)}</td>
        </tr>
        {Number(t.discount) !== 0 && (
          <tr>
            <td>Less discount</td>
            <td className="num">-{inr(t.discount)}</td>
          </tr>
        )}
        <tr>
          <td>Taxable value</td>
          <td className="num">{inr(t.taxable)}</td>
        </tr>
        <tr>
          <td>Charges</td>
          <td className="num">{inr(t.charges)}</td>
        </tr>
        {interstate ? (
          <tr>
            <td>IGST</td>
            <td className="num">{inr(t.igst)}</td>
          </tr>
        ) : (
          <>
            <tr>
              <td>CGST</td>
              <td className="num">{inr(t.cgst)}</td>
            </tr>
            <tr>
              <td>SGST</td>
              <td className="num">{inr(t.sgst)}</td>
            </tr>
          </>
        )}
        <tr>
          <td>Round off</td>
          <td className="num">{inr(t.roundOff)}</td>
        </tr>
        <tr className="grand">
          <td>Grand total</td>
          <td className="num">{inr(t.grand)}</td>
        </tr>
      </tbody>
    </table>
  );
}

export function NewPo() {
  const navigate = useNavigate();
  const lookups = useMaterialLookups();
  if (!lookups) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="breadcrumb">
        <Link to="/purchase-orders">Purchase orders</Link> / new
      </p>
      <h1>New purchase order</h1>
      <PoForm lookups={lookups} onSaved={(p) => navigate(`/purchase-orders/${p.id}`)} onCancel={() => navigate(-1)} />
    </>
  );
}

export function PoDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [po, setPo] = useState<Po | null>(null);
  const [grns, setGrns] = useState<Grn[]>([]);
  const [editing, setEditing] = useState(false);
  const [receiving, setReceiving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPo(await api<Po>(`/api/material/pos/${id}`));
      if (can("grn.view")) setGrns((await api<Page<Grn>>(`/api/material/grns?po_id=${id}`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [id, can]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(path: string, json?: unknown) {
    setError(null);
    try {
      setPo(await api<Po>(`/api/material/pos/${id}/${path}`, { method: "POST", json }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!po || !lookups) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  if (editing) return <PoForm po={po} lookups={lookups} onSaved={(p) => (setPo(p), setEditing(false))} onCancel={() => setEditing(false)} />;
  const editable = can("po.edit");
  const receivable = ["approved", "sent", "partly_received"].includes(po.status) && can("grn.edit");

  return (
    <>
      <p className="breadcrumb">
        <Link to="/purchase-orders">Purchase orders</Link> / <code>{po.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {po.code} <StatusBadge status={po.status} />
          </h1>
          <p className="muted">
            {po.vendor_name} {po.vendor_gstin && `(${po.vendor_gstin})`} → {po.store_name} · {shortDate(po.po_date)} · {po.interstate ? "IGST" : "CGST + SGST"}
            {po.rfq_id && (
              <>
                {" · "}
                <Link to={`/rfqs/${po.rfq_id}`}>RFQ</Link>
              </>
            )}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => void downloadFile(`/api/material/pos/${po.id}/pdf`).catch((err) => setError(errorText(err)))}>
            PDF
          </button>
          {po.can_edit && (
            <button className="btn" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {po.status === "draft" && editable && (
            <button className="btn btn-primary" onClick={() => void act("submit")}>
              {po.needs_approver ? "Send for approval" : "Approve"}
            </button>
          )}
          {po.can_approve && (
            <>
              <button
                className="btn btn-danger"
                onClick={() => {
                  const reason = prompt("Send back to draft: why?");
                  if (reason) void act("reject", { reason });
                }}
              >
                Send back
              </button>
              <button className="btn btn-primary" onClick={() => void act("approve")}>
                Approve
              </button>
            </>
          )}
          {po.status === "approved" && editable && (
            <button className="btn btn-primary" onClick={() => void act("send")}>
              Mark sent
            </button>
          )}
          {receivable && (
            <button className="btn btn-primary" onClick={() => setReceiving(true)}>
              Receive (GRN)
            </button>
          )}
          {editable && ["partly_received", "sent", "approved"].includes(po.status) && po.lines.some((l) => Number(l.received_qty) > 0) && (
            <button
              className="btn"
              onClick={() => {
                const reason = prompt("Short-close: why will the rest not come?");
                if (reason) void act("close", { reason });
              }}
            >
              Short-close
            </button>
          )}
          {editable && !["partly_received", "received", "closed", "cancelled"].includes(po.status) && (
            <button
              className="btn btn-danger"
              onClick={() => {
                const reason = prompt(`Cancel ${po.code}: why?`);
                if (reason) void act("cancel", { reason });
              }}
            >
              Cancel PO
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {po.status === "pending_approval" && (
        <div className="alert alert-warn">
          {inr(po.grand_total)} is above the approval limit of {inr(po.approval_limit)}: a PO approver must approve it.
        </div>
      )}
      <div className="card table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>#</th>
              <th>Item</th>
              <th className="num">Qty</th>
              <th className="num">Rate</th>
              <th className="num">Disc</th>
              <th className="num">Taxable</th>
              <th className="num">GST</th>
              <th className="num">Received</th>
            </tr>
          </thead>
          <tbody>
            {po.lines.map((l, i) => (
              <tr key={l.id}>
                <td>{i + 1}</td>
                <td>
                  {l.product_name} <span className="muted small">{l.product_code}</span>
                </td>
                <td className="num nowrap">
                  {num(l.qty)} {l.unit}
                </td>
                <td className="num">{inr(l.rate)}</td>
                <td className="num">{num(l.discount_percent)}%</td>
                <td className="num">{inr(l.amount)}</td>
                <td className="num">{num(l.gst_percent)}%</td>
                <td className="num">{num(l.received_qty)}</td>
              </tr>
            ))}
            {po.charges.map((c) => (
              <tr key={`c${c.id}`} className="row-muted">
                <td />
                <td>
                  {c.description ?? c.kind}{" "}
                  <span className="muted small">
                    ({c.kind}
                    {c.add_to_cost ? ", in material cost" : ""})
                  </span>
                </td>
                <td colSpan={3} />
                <td className="num">{inr(c.amount)}</td>
                <td className="num">{num(c.gst_percent)}%</td>
                <td />
              </tr>
            ))}
          </tbody>
        </table>
        <TotalsBox
          t={{
            subtotal: po.subtotal,
            discount: po.discount_total,
            taxable: po.taxable,
            charges: po.charges_total,
            cgst: po.cgst,
            sgst: po.sgst,
            igst: po.igst,
            roundOff: po.round_off,
            grand: po.grand_total,
          }}
          interstate={po.interstate}
        />
      </div>
      <dl className="detail-list top-gap">
        <div>
          <dt>Payment terms</dt>
          <dd>{po.payment_terms ?? "—"}</dd>
        </div>
        <div>
          <dt>Expected delivery</dt>
          <dd>{shortDate(po.expected_delivery)}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{po.created_by_name ?? "—"}</dd>
        </div>
        <div>
          <dt>Approved</dt>
          <dd>{po.approved_by_name ?? "—"}</dd>
        </div>
        {po.remark && (
          <div>
            <dt>Remark</dt>
            <dd className="pre-line">{po.remark}</dd>
          </div>
        )}
      </dl>
      {grns.length > 0 && (
        <>
          <h2 className="section-title top-gap">Goods received</h2>
          <ul className="plain-list">
            {grns.map((g) => (
              <li key={g.id}>
                <Link to={`/grns?open=${g.id}`}>{g.code}</Link> · {shortDate(g.received_at)} · <StatusBadge status={g.status} />
              </li>
            ))}
          </ul>
        </>
      )}
      {receiving && (
        <GrnForm
          lookups={lookups}
          po={po}
          onClose={() => setReceiving(false)}
          onSaved={async () => {
            setReceiving(false);
            await load();
          }}
        />
      )}
    </>
  );
}
