import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fetchObjectUrl, queryString } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { Grn, MaterialLookups, Po } from "../../material/types";
import type { Page } from "../../types";
import { Pager } from "../Clients";
import { shortDate } from "../Tenders";
import { ProductSelect, StatusBadge, today, UnitSelect, useMaterialLookups } from "./common";

export default function Grns() {
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<Page<Grn> | null>(null);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Grn | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Grn>>(`/api/material/grns${queryString({ status, offset, limit: 50 })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [status, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const id = params.get("open");
    if (id) api<Grn>(`/api/material/grns/${id}`).then(setOpen, (err) => setError(errorText(err)));
  }, [params]);

  return (
    <>
      <div className="page-header">
        <h1>Goods receipts (GRN)</h1>
        <div className="page-actions">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {["draft", "submitted", "approved", "rejected"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {can("grn.edit") && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New GRN
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <GrnTable grns={page?.items ?? []} onOpen={setOpen} />
      {page && <Pager page={page} onOffset={setOffset} />}
      {open && (
        <GrnView
          grn={open}
          onClose={() => {
            setOpen(null);
            if (params.get("open")) setParams({});
          }}
          onChange={async (g) => (setOpen(g), await load())}
        />
      )}
      {creating && lookups && (
        <GrnForm
          lookups={lookups}
          onClose={() => setCreating(false)}
          onSaved={async (g) => {
            setCreating(false);
            await load();
            setOpen(g);
          }}
        />
      )}
    </>
  );
}

export function GrnTable({ grns, onOpen }: { grns: Grn[]; onOpen: (g: Grn) => void }) {
  return (
    <div className="card table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>GRN</th>
            <th>Date</th>
            <th>PO</th>
            <th>Vendor</th>
            <th>Store</th>
            <th>Invoice</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {grns.map((g) => (
            <tr key={g.id} className="clickable" onClick={() => onOpen(g)}>
              <td>
                <code>{g.code}</code>
              </td>
              <td className="nowrap">{shortDate(g.received_at)}</td>
              <td>{g.po_code ?? <span className="muted">direct</span>}</td>
              <td>{g.vendor_name}</td>
              <td>{g.store_name}</td>
              <td>{g.invoice_no ?? "—"}</td>
              <td>
                <StatusBadge status={g.status} />
                {g.status === "submitted" && g.levels_required > 1 && (
                  <span className="muted small">
                    {" "}
                    {g.approvals}/{g.levels_required}
                  </span>
                )}
              </td>
            </tr>
          ))}
          {grns.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">
                No goods receipts.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

type Line = {
  po_line_id: number | null;
  product_id: number | "";
  unit: string;
  label: string;
  pending: string | null;
  received_qty: string;
  rejected_qty: string;
  reason: string;
  rate: string;
};

/** Mobile-friendly: a card per item with big number fields; photos are added after saving. */
export function GrnForm({
  lookups,
  po: givenPo,
  storeId,
  onClose,
  onSaved,
}: {
  lookups: MaterialLookups;
  po?: Po;
  storeId?: number;
  onClose: () => void;
  onSaved: (g: Grn) => void | Promise<void>;
}) {
  const [po, setPo] = useState<Po | null>(givenPo ?? null);
  const [openPos, setOpenPos] = useState<Po[]>([]);
  const [direct, setDirect] = useState(false);
  const [head, setHead] = useState({
    vendor_id: "" as number | "",
    store_id: storeId ?? givenPo?.store_id ?? ("" as number | ""),
    challan_no: "",
    invoice_no: "",
    invoice_date: "",
    invoice_amount: "",
    vehicle_no: "",
    received_at: today(),
    remark: "",
  });
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (givenPo) return;
    api<Page<Po>>("/api/material/pos?status=approved,sent,partly_received&limit=200").then(
      (p) => setOpenPos(storeId ? p.items.filter((x) => x.store_id === storeId) : p.items),
      () => setOpenPos([]),
    );
  }, [givenPo, storeId]);

  useEffect(() => {
    if (!po) return;
    setHead((h) => ({ ...h, store_id: storeId ?? po.store_id }));
    setLines(
      po.lines
        .filter((l) => Number(l.qty) > Number(l.received_qty))
        .map((l) => {
          const pending = String(Number(l.qty) - Number(l.received_qty));
          return { po_line_id: l.id, product_id: l.product_id, unit: l.unit, label: l.product_name, pending, received_qty: pending, rejected_qty: "0", reason: "", rate: "" };
        }),
    );
  }, [po, storeId]);

  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  async function submit(e: FormEvent, sub: boolean) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const body = {
      po_id: direct ? null : po?.id,
      vendor_id: direct ? head.vendor_id : null,
      store_id: head.store_id || null,
      challan_no: head.challan_no || null,
      invoice_no: head.invoice_no || null,
      invoice_date: head.invoice_date || null,
      invoice_amount: head.invoice_amount || null,
      vehicle_no: head.vehicle_no || null,
      received_at: head.received_at,
      remark: head.remark || null,
      submit: sub,
      lines: lines
        .filter((l) => Number(l.received_qty) > 0)
        .map((l) => ({
          po_line_id: l.po_line_id,
          product_id: direct ? l.product_id : null,
          unit: direct ? l.unit : null,
          received_qty: l.received_qty,
          rejected_qty: l.rejected_qty || "0",
          reason: l.reason || null,
          rate: direct ? l.rate : null,
        })),
    };
    try {
      await onSaved(await api<Grn>("/api/material/grns", { method: "POST", json: body }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof head) => (e: { target: { value: string } }) => setHead({ ...head, [k]: e.target.value });

  return (
    <Modal title={po ? `Receive against ${po.code}` : "New GRN"} onClose={onClose} wide>
      <form onSubmit={(e) => void submit(e, true)}>
        {error && <div className="alert alert-error">{error}</div>}
        {!givenPo && (
          <div className="grid-2">
            <label className="field">
              <span>Against</span>
              <select
                value={direct ? "direct" : (po?.id ?? "")}
                onChange={(e) => {
                  if (e.target.value === "direct") {
                    setDirect(true);
                    setPo(null);
                    setLines([{ po_line_id: null, product_id: "", unit: "", label: "", pending: null, received_qty: "", rejected_qty: "0", reason: "", rate: "" }]);
                  } else {
                    setDirect(false);
                    setPo(openPos.find((p) => p.id === Number(e.target.value)) ?? null);
                  }
                }}
              >
                <option value="">— pick a PO —</option>
                {openPos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · {p.vendor_name} · {p.store_name}
                  </option>
                ))}
                <option value="direct">Direct purchase (no PO)</option>
              </select>
            </label>
            {direct && (
              <label className="field">
                <span>Vendor *</span>
                <select required value={head.vendor_id} onChange={(e) => setHead({ ...head, vendor_id: Number(e.target.value) || "" })}>
                  <option value="">— vendor —</option>
                  {lookups.vendors.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}
        <div className="grid-2">
          <label className="field">
            <span>Received into *</span>
            <select required value={head.store_id} onChange={(e) => setHead({ ...head, store_id: Number(e.target.value) })}>
              <option value="">—</option>
              {lookups.stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Received on</span>
            <input type="date" value={head.received_at} onChange={set("received_at")} />
          </label>
          <label className="field">
            <span>Challan no</span>
            <input value={head.challan_no} onChange={set("challan_no")} />
          </label>
          <label className="field">
            <span>Vehicle no</span>
            <input value={head.vehicle_no} onChange={set("vehicle_no")} placeholder="GJ01AB1234" />
          </label>
          <label className="field">
            <span>Invoice no</span>
            <input value={head.invoice_no} onChange={set("invoice_no")} />
          </label>
          <label className="field">
            <span>Invoice date</span>
            <input type="date" value={head.invoice_date} onChange={set("invoice_date")} />
          </label>
          <label className="field">
            <span>Invoice amount (₹)</span>
            <input inputMode="decimal" value={head.invoice_amount} onChange={set("invoice_amount")} />
          </label>
          <label className="field">
            <span>Remark</span>
            <input value={head.remark} onChange={set("remark")} />
          </label>
        </div>
        <h2 className="section-title">Material</h2>
        <div className="line-cards">
          {lines.map((l, i) => (
            <div key={i} className="line-card">
              {direct ? (
                <div className="line-row">
                  <label className="field grow">
                    <span>Product</span>
                    <ProductSelect products={lookups.products} value={l.product_id} onChange={(p) => setLine(i, { product_id: p?.id ?? "", unit: p?.unit ?? "" })} />
                  </label>
                  <label className="field">
                    <span>Unit</span>
                    <UnitSelect units={lookups.units} value={l.unit || lookups.units[0]} onChange={(u) => setLine(i, { unit: u })} />
                  </label>
                  <label className="field">
                    <span>Rate (net)</span>
                    <input className="input-num" inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} />
                  </label>
                </div>
              ) : (
                <strong>
                  {l.label}{" "}
                  <span className="muted small">
                    pending {num(l.pending)} {l.unit}
                  </span>
                </strong>
              )}
              <div className="line-row">
                <label className="field">
                  <span>Received</span>
                  <input inputMode="decimal" value={l.received_qty} onChange={(e) => setLine(i, { received_qty: e.target.value })} />
                </label>
                <label className="field">
                  <span>Rejected</span>
                  <input inputMode="decimal" value={l.rejected_qty} onChange={(e) => setLine(i, { rejected_qty: e.target.value })} />
                </label>
                <div className="field">
                  <span>Accepted</span>
                  <b className="accepted">{num(Math.max(0, Number(l.received_qty || 0) - Number(l.rejected_qty || 0)))}</b>
                </div>
              </div>
              {Number(l.rejected_qty) > 0 && (
                <label className="field">
                  <span>Reason for rejection *</span>
                  <input required value={l.reason} onChange={(e) => setLine(i, { reason: e.target.value })} />
                </label>
              )}
            </div>
          ))}
          {!po && !direct && <p className="muted">Pick the PO the material came against.</p>}
        </div>
        {direct && (
          <button
            type="button"
            className="btn btn-small top-gap"
            onClick={() =>
              setLines((ls) => [...ls, { po_line_id: null, product_id: "", unit: "", label: "", pending: null, received_qty: "", rejected_qty: "0", reason: "", rate: "" }])
            }
          >
            + Item
          </button>
        )}
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn" disabled={busy || lines.length === 0} onClick={(e) => void submit(e, false)}>
            Save draft
          </button>
          <button className="btn btn-primary" disabled={busy || lines.length === 0}>
            Submit for approval
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Photo({ grn, id, name }: { grn: number; id: number; name: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    void fetchObjectUrl(`/api/material/grns/${grn}/photos/${id}`).then((x) => setUrl((u = x)));
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [grn, id]);
  if (!url) return <span className="muted small">{name}</span>;
  return name.toLowerCase().endsWith(".pdf") ? (
    <a href={url} target="_blank" rel="noreferrer">
      {name}
    </a>
  ) : (
    <a href={url} target="_blank" rel="noreferrer">
      <img src={url} alt={name} />
    </a>
  );
}

export function GrnView({ grn, onClose, onChange }: { grn: Grn; onClose: () => void; onChange: (g: Grn) => void | Promise<void> }) {
  const { can } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("material");

  async function act(path: string, json?: unknown) {
    setError(null);
    try {
      await onChange(await api<Grn>(`/api/material/grns/${grn.id}/${path}`, { method: "POST", json }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function upload(files: FileList | null) {
    if (!files) return;
    setError(null);
    try {
      let latest = grn;
      for (const f of Array.from(files)) {
        const form = new FormData();
        form.append("file", f);
        form.append("kind", kind);
        latest = await api<Grn>(`/api/material/grns/${grn.id}/photos`, { method: "POST", form });
      }
      await onChange(latest);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`${grn.code} · ${grn.vendor_name}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p>
        <StatusBadge status={grn.status} />{" "}
        <span className="muted small">
          {grn.po_code ? `against ${grn.po_code}` : "direct purchase"} · into {grn.store_name} · {shortDate(grn.received_at)}
          {grn.levels_required > 1 && ` · approvals ${grn.approvals}/${grn.levels_required}`}
        </span>
      </p>
      <p className="small">
        Challan {grn.challan_no ?? "—"} · invoice {grn.invoice_no ?? "—"} {grn.invoice_date && `(${shortDate(grn.invoice_date)})`} {grn.invoice_amount && inr(grn.invoice_amount)} ·
        vehicle {grn.vehicle_no ?? "—"}
      </p>
      {grn.reject_reason && <div className="alert alert-warn">Rejected: {grn.reject_reason}</div>}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Pending</th>
              <th className="num">Received</th>
              <th className="num">Accepted</th>
              <th className="num">Rejected</th>
              <th className="num">Rate</th>
              <th className="num">Landed / {"base unit"}</th>
            </tr>
          </thead>
          <tbody>
            {grn.lines.map((l) => (
              <tr key={l.id}>
                <td>
                  {l.product_name}
                  {l.reason && <div className="small text-warn">{l.reason}</div>}
                </td>
                <td className="num">{num(l.ordered_qty)}</td>
                <td className="num">
                  {num(l.received_qty)} {l.unit}
                </td>
                <td className="num">{num(l.accepted_qty)}</td>
                <td className="num">{num(l.rejected_qty)}</td>
                <td className="num">{inr(l.rate)}</td>
                <td className="num">{l.landed_rate ? `${inr(l.landed_rate)} / ${l.base_unit}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2 className="section-title top-gap">Photos</h2>
      <div className="photo-strip">
        {grn.photos.map((p) => (
          <figure key={p.id}>
            <Photo grn={grn.id} id={p.id} name={p.filename} />
            <figcaption className="small muted">{p.kind}</figcaption>
          </figure>
        ))}
        {grn.photos.length === 0 && <span className="muted small">No photos yet.</span>}
      </div>
      {grn.status !== "approved" && can("grn.edit") && (
        <div className="inline-form top-gap">
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Photo of">
            <option value="material">Material</option>
            <option value="challan">Challan</option>
            <option value="invoice">Invoice</option>
          </select>
          <input type="file" accept="image/*,.pdf" capture="environment" multiple onChange={(e) => void upload(e.target.files)} />
        </div>
      )}
      <div className="form-actions">
        {grn.status === "draft" && grn.can_edit && (
          <button className="btn" onClick={() => void act("submit")}>
            Submit
          </button>
        )}
        {["draft", "submitted"].includes(grn.status) && can("grn.approve") && (
          <button
            className="btn btn-danger"
            onClick={() => {
              const reason = prompt("Why is the GRN rejected?");
              if (reason) void act("reject", { reason });
            }}
          >
            Reject
          </button>
        )}
        {grn.can_approve && (
          <button className="btn btn-primary" onClick={() => void act("approve")}>
            {grn.levels_required > grn.approvals + 1 ? "Approve (level 1)" : "Approve: put in stock"}
          </button>
        )}
      </div>
    </Modal>
  );
}
