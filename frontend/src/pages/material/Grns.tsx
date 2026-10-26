import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fetchObjectUrl, queryString } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText, inr, num } from "../../format";
import type { Grn, MaterialLookups, Po } from "../../material/types";
import type { Page } from "../../types";
import { Pager } from "../Clients";
import { shortDate } from "../Tenders";
import { ProductSelect, StatusBadge, today, UnitSelect, useMaterialLookups } from "./common";
import { Button, Card, Field, FilePicker } from "../../ui/components";

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
          <Field label="Status" bare>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {["draft", "submitted", "approved", "rejected"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          {can("grn.edit") && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              New GRN
            </Button>
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
    <Card as="div" className="table-wrap">
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
    </Card>
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
            <Field label="Against">
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
            </Field>
            {direct && (
              <Field label="Vendor *">
                <select required value={head.vendor_id} onChange={(e) => setHead({ ...head, vendor_id: Number(e.target.value) || "" })}>
                  <option value="">— vendor —</option>
                  {lookups.vendors.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
        )}
        <div className="grid-2">
          <Field label="Received into *">
            <select required value={head.store_id} onChange={(e) => setHead({ ...head, store_id: Number(e.target.value) })}>
              <option value="">—</option>
              {lookups.stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Received on">
            <input type="date" value={head.received_at} onChange={set("received_at")} />
          </Field>
          <Field label="Challan no">
            <input value={head.challan_no} onChange={set("challan_no")} />
          </Field>
          <Field label="Vehicle no">
            <input value={head.vehicle_no} onChange={set("vehicle_no")} placeholder="GJ01AB1234" />
          </Field>
          <Field label="Invoice no">
            <input value={head.invoice_no} onChange={set("invoice_no")} />
          </Field>
          <Field label="Invoice date">
            <input type="date" value={head.invoice_date} onChange={set("invoice_date")} />
          </Field>
          <Field label="Invoice amount (₹)">
            <input inputMode="decimal" value={head.invoice_amount} onChange={set("invoice_amount")} />
          </Field>
          <Field label="Remark">
            <input value={head.remark} onChange={set("remark")} />
          </Field>
        </div>
        <h2 className="section-title">Material</h2>
        <div className="line-cards">
          {lines.map((l, i) => (
            <div key={i} className="line-card">
              {direct ? (
                <div className="line-row">
                  <ProductSelect label="Product" className="grow" products={lookups.products} value={l.product_id} onChange={(p) => setLine(i, { product_id: p?.id ?? "", unit: p?.unit ?? "" })} />
                  <UnitSelect label="Unit" units={lookups.units} value={l.unit || lookups.units[0]} onChange={(u) => setLine(i, { unit: u })} />
                  <Field label="Rate (net)">
                    <input className="input-num" inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} />
                  </Field>
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
                <Field label="Received">
                  <input inputMode="decimal" value={l.received_qty} onChange={(e) => setLine(i, { received_qty: e.target.value })} />
                </Field>
                <Field label="Rejected">
                  <input inputMode="decimal" value={l.rejected_qty} onChange={(e) => setLine(i, { rejected_qty: e.target.value })} />
                </Field>
                <Field as="div" label="Accepted">
                  <b className="accepted">{num(Math.max(0, Number(l.received_qty || 0) - Number(l.rejected_qty || 0)))}</b>
                </Field>
              </div>
              {Number(l.rejected_qty) > 0 && (
                <Field label="Reason for rejection *">
                  <input required value={l.reason} onChange={(e) => setLine(i, { reason: e.target.value })} />
                </Field>
              )}
            </div>
          ))}
          {!po && !direct && <p className="muted">Pick the PO the material came against.</p>}
        </div>
        {direct && (
          <Button
            type="button"
            size="small" className="top-gap"
            onClick={() =>
              setLines((ls) => [...ls, { po_line_id: null, product_id: "", unit: "", label: "", pending: null, received_qty: "", rejected_qty: "0", reason: "", rate: "" }])
            }
          >
            + Item
          </Button>
        )}
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" disabled={busy || lines.length === 0} onClick={(e) => void submit(e, false)}>
            Save draft
          </Button>
          <Button type="submit" variant="primary" disabled={busy || lines.length === 0}>
            Submit for approval
          </Button>
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

  async function upload(files: File[]) {
    if (!files.length) return;
    setError(null);
    try {
      let latest = grn;
      for (const f of files) {
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
          <Field label="Photo of" bare>
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Photo of">
              <option value="material">Material</option>
              <option value="challan">Challan</option>
              <option value="invoice">Invoice</option>
            </select>
          </Field>
          <FilePicker label="Choose photos" accept="image/*,.pdf" capture="environment" multiple onFiles={(fs) => void upload(fs)} />
        </div>
      )}
      <div className="form-actions">
        {grn.status === "draft" && grn.can_edit && (
          <Button onClick={() => void act("submit")}>
            Submit
          </Button>
        )}
        {["draft", "submitted"].includes(grn.status) && can("grn.approve") && (
          <Button
            variant="danger"
            onClick={() => {
              const reason = prompt("Why is the GRN rejected?");
              if (reason) void act("reject", { reason });
            }}
          >
            Reject
          </Button>
        )}
        {grn.can_approve && (
          <Button variant="primary" onClick={() => void act("approve")}>
            {grn.levels_required > grn.approvals + 1 ? "Approve (level 1)" : "Approve: put in stock"}
          </Button>
        )}
      </div>
    </Modal>
  );
}
