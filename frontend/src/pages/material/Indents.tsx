import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, queryString } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, num } from "../../format";
import type { Indent, MaterialLookups, Rfq } from "../../material/types";
import type { Page } from "../../types";
import { Pager } from "../Clients";
import { shortDate } from "../Tenders";
import { ProductSelect, StatusBadge, UnitSelect, useMaterialLookups } from "./common";

const STATUSES = ["draft", "submitted", "approved", "partly_ordered", "ordered", "closed", "rejected", "cancelled"];
const ORDERABLE = ["approved", "partly_ordered"];

export default function Indents() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const lookups = useMaterialLookups();
  const [page, setPage] = useState<Page<Indent> | null>(null);
  const [filters, setFilters] = useState({ status: "", site_id: "" });
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<Indent | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [rfqFor, setRfqFor] = useState<number[] | null>(null);

  const load = useCallback(async () => {
    try {
      setPage(await api<Page<Indent>>(`/api/material/indents${queryString({ ...filters, offset, limit: 50 })}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [filters, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  return (
    <>
      <div className="page-header">
        <h1>Material indents</h1>
        <div className="page-actions">
          <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          {lookups && (
            <select value={filters.site_id} onChange={(e) => setFilters((f) => ({ ...f, site_id: e.target.value }))}>
              <option value="">All sites</option>
              {lookups.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          )}
          {can("po.edit") && picked.length > 0 && (
            <>
              <button className="btn" onClick={() => setRfqFor(picked)}>
                Create RFQ ({picked.length})
              </button>
              <button className="btn" onClick={() => navigate(`/purchase-orders/new?indents=${picked.join(",")}`)}>
                Create PO
              </button>
            </>
          )}
          {can("indent.create") && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              New indent
            </button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <IndentTable indents={page?.items ?? []} onOpen={setOpen} picked={can("po.edit") ? picked : undefined} onPick={toggle} />
      {page && <Pager page={page} onOffset={setOffset} />}
      {creating && lookups && (
        <IndentForm
          lookups={lookups}
          onClose={() => setCreating(false)}
          onSaved={async (i) => {
            setCreating(false);
            await load();
            setOpen(i);
          }}
        />
      )}
      {open && lookups && <IndentView indent={open} lookups={lookups} onClose={() => setOpen(null)} onChange={async (i) => (setOpen(i), await load())} />}
      {rfqFor && lookups && <RfqDialog indentIds={rfqFor} lookups={lookups} onClose={() => setRfqFor(null)} onDone={(r) => navigate(`/rfqs/${r.id}`)} />}
    </>
  );
}

export function IndentTable({
  indents,
  onOpen,
  picked,
  onPick,
  hideSite,
}: {
  indents: Indent[];
  onOpen: (i: Indent) => void;
  picked?: number[];
  onPick?: (id: number) => void;
  hideSite?: boolean;
}) {
  return (
    <div className="card table-wrap">
      <table className="table">
        <thead>
          <tr>
            {picked && <th />}
            <th>Code</th>
            {!hideSite && <th>Site</th>}
            <th>Items</th>
            <th>Required by</th>
            <th>Status</th>
            <th>Raised by</th>
          </tr>
        </thead>
        <tbody>
          {indents.map((i) => (
            <tr key={i.id} className="clickable" onClick={() => onOpen(i)}>
              {picked && (
                <td onClick={(e) => e.stopPropagation()}>
                  {ORDERABLE.includes(i.status) && <input type="checkbox" checked={picked.includes(i.id)} onChange={() => onPick?.(i.id)} aria-label={`Pick ${i.code}`} />}
                </td>
              )}
              <td className="nowrap">
                <code>{i.code}</code> {i.priority === "urgent" && <span className="badge badge-danger">Urgent</span>}
              </td>
              {!hideSite && (
                <td>
                  {i.site_code} <span className="muted small">{i.site_name}</span>
                </td>
              )}
              <td className="small">{i.lines.map((l) => l.product_name ?? l.free_text).join(", ")}</td>
              <td className="nowrap">{shortDate(i.required_by)}</td>
              <td>
                <StatusBadge status={i.status} />
              </td>
              <td>{i.created_by_name ?? "—"}</td>
            </tr>
          ))}
          {indents.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">
                No indents.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

type LineForm = { product_id: number | ""; free_text: string; qty: string; unit: string; remark: string; manual: boolean };
const blankLine = (): LineForm => ({ product_id: "", free_text: "", qty: "", unit: "", remark: "", manual: false });

/** Mobile-friendly: each line is a small card; works one-handed on a phone. */
export function IndentForm({
  lookups,
  indent,
  siteId,
  onClose,
  onSaved,
}: {
  lookups: MaterialLookups;
  indent?: Indent;
  siteId?: number;
  onClose: () => void;
  onSaved: (i: Indent) => void | Promise<void>;
}) {
  const [form, setForm] = useState({
    site_id: indent?.site_id ?? siteId ?? lookups.sites[0]?.id ?? "",
    required_by: indent?.required_by ?? "",
    priority: indent?.priority ?? "normal",
    remark: indent?.remark ?? "",
  });
  const [lines, setLines] = useState<LineForm[]>(
    indent?.lines.map((l) => ({
      product_id: l.product_id ?? "",
      free_text: l.free_text ?? "",
      qty: l.qty,
      unit: l.unit,
      remark: l.remark ?? "",
      manual: l.product_id === null,
    })) ?? [blankLine()],
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const setLine = (i: number, patch: Partial<LineForm>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  async function save(e: FormEvent, submit: boolean) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const body = {
      ...form,
      required_by: form.required_by || null,
      remark: form.remark || null,
      submit,
      lines: lines
        .filter((l) => l.qty && (l.product_id || l.free_text.trim()))
        .map((l) => ({
          product_id: l.manual ? null : l.product_id || null,
          free_text: l.manual ? l.free_text : null,
          qty: l.qty,
          unit: l.unit || null,
          remark: l.remark || null,
        })),
    };
    try {
      const saved = indent
        ? await api<Indent>(`/api/material/indents/${indent.id}`, { method: "PUT", json: body })
        : await api<Indent>("/api/material/indents", { method: "POST", json: body });
      await onSaved(saved);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={indent ? `Edit ${indent.code}` : "New indent"} onClose={onClose} wide>
      <form onSubmit={(e) => void save(e, true)}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Site *</span>
            <select required disabled={!!indent || !!siteId} value={form.site_id} onChange={(e) => setForm({ ...form, site_id: Number(e.target.value) })}>
              {lookups.sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.code} {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Required by</span>
            <input type="date" value={form.required_by} onChange={(e) => setForm({ ...form, required_by: e.target.value })} />
          </label>
          <label className="field">
            <span>Priority</span>
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as "normal" | "urgent" })}>
              <option value="normal">Normal</option>
              <option value="urgent">Urgent</option>
            </select>
          </label>
          <label className="field">
            <span>Remark</span>
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </label>
        </div>
        <h2 className="section-title">Material</h2>
        <div className="line-cards">
          {lines.map((l, i) => (
            <div key={i} className="line-card">
              {l.manual ? (
                <label className="field">
                  <span>Material (not in the product list)</span>
                  <input value={l.free_text} onChange={(e) => setLine(i, { free_text: e.target.value })} placeholder="Describe it" />
                </label>
              ) : (
                <label className="field">
                  <span>Product</span>
                  <ProductSelect products={lookups.products} value={l.product_id} onChange={(p) => setLine(i, { product_id: p?.id ?? "", unit: p?.unit ?? "" })} />
                </label>
              )}
              <div className="line-row">
                <label className="field">
                  <span>Qty</span>
                  <input inputMode="decimal" value={l.qty} onChange={(e) => setLine(i, { qty: e.target.value })} />
                </label>
                <label className="field">
                  <span>Unit</span>
                  <UnitSelect
                    units={lookups.units}
                    value={l.unit || lookups.products.find((p) => p.id === l.product_id)?.unit || lookups.units[0]}
                    onChange={(u) => setLine(i, { unit: u })}
                  />
                </label>
                <button type="button" className="btn btn-ghost btn-icon" aria-label="Remove line" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                  ×
                </button>
              </div>
              <label className="check small">
                <input type="checkbox" checked={l.manual} onChange={(e) => setLine(i, { manual: e.target.checked, product_id: "" })} /> Not in the product list (flagged for the
                buyer)
              </label>
            </div>
          ))}
        </div>
        <button type="button" className="btn btn-small top-gap" onClick={() => setLines((ls) => [...ls, blankLine()])}>
          + Add material
        </button>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn" disabled={busy} onClick={(e) => void save(e, false)}>
            Save draft
          </button>
          <button className="btn btn-primary" disabled={busy}>
            Submit for approval
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function IndentView({
  indent,
  lookups,
  onClose,
  onChange,
}: {
  indent: Indent;
  lookups: MaterialLookups;
  onClose: () => void;
  onChange: (i: Indent) => void | Promise<void>;
}) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  async function act(path: string, json?: unknown) {
    setError(null);
    try {
      await onChange(await api<Indent>(`/api/material/indents/${indent.id}/${path}`, { method: "POST", json }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (editing) return <IndentForm lookups={lookups} indent={indent} onClose={() => setEditing(false)} onSaved={async (i) => (setEditing(false), await onChange(i))} />;

  return (
    <Modal title={`${indent.code} · ${indent.site_code}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p>
        <StatusBadge status={indent.status} /> {indent.priority === "urgent" && <span className="badge badge-danger">Urgent</span>}{" "}
        <span className="muted small">
          raised by {indent.created_by_name ?? "—"} · required by {shortDate(indent.required_by)}
        </span>
      </p>
      {indent.reject_reason && <div className="alert alert-warn">Rejected: {indent.reject_reason}</div>}
      {indent.remark && <p className="pre-line">{indent.remark}</p>}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Material</th>
              <th className="num">Asked</th>
              <th className="num">In stock unit</th>
              <th className="num">Ordered</th>
              <th className="num">Received</th>
            </tr>
          </thead>
          <tbody>
            {indent.lines.map((l) => (
              <tr key={l.id} className={l.product_id ? "" : "row-flagged"}>
                <td>
                  {l.product_name ?? (
                    <>
                      {l.free_text} <span className="badge badge-warn">Not in master</span>
                    </>
                  )}
                </td>
                <td className="num">
                  {num(l.qty)} {l.unit}
                </td>
                <td className="num">
                  {num(l.base_qty)} {l.base_unit}
                </td>
                <td className="num">{num(l.ordered_qty)}</td>
                <td className="num">{num(l.received_qty)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="form-actions">
        {indent.can_edit && (
          <button className="btn" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {indent.status === "draft" && indent.can_edit && (
          <button className="btn" onClick={() => void act("submit")}>
            Submit
          </button>
        )}
        {["draft", "submitted", "approved"].includes(indent.status) && (indent.can_edit || indent.can_approve) && (
          <button className="btn btn-danger" onClick={() => confirm(`Cancel ${indent.code}?`) && void act("cancel")}>
            Cancel indent
          </button>
        )}
        {indent.can_approve && (
          <>
            <button
              className="btn btn-danger"
              onClick={() => {
                const reason = prompt("Why is it rejected?");
                if (reason) void act("reject", { reason });
              }}
            >
              Reject
            </button>
            <button className="btn btn-primary" onClick={() => void act("approve")}>
              Approve
            </button>
          </>
        )}
        {ORDERABLE.includes(indent.status) && can("po.edit") && (
          <button className="btn btn-primary" onClick={() => navigate(`/purchase-orders/new?indents=${indent.id}`)}>
            Create PO
          </button>
        )}
      </div>
    </Modal>
  );
}

export function RfqDialog({ indentIds, lookups, onClose, onDone }: { indentIds: number[]; lookups: MaterialLookups; onClose: () => void; onDone: (r: Rfq) => void }) {
  const [vendorIds, setVendorIds] = useState<number[]>([]);
  const [due, setDue] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      onDone(await api<Rfq>("/api/material/rfqs", { method: "POST", json: { indent_ids: indentIds, vendor_ids: vendorIds, due_date: due || null } }));
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title="Request for quotation" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <p className="muted small">The RFQ asks for what the {indentIds.length} indent(s) still need. Pick the vendors to ask.</p>
        <div className="pick-list">
          {lookups.vendors.map((v) => (
            <label key={v.id} className="check">
              <input
                type="checkbox"
                checked={vendorIds.includes(v.id)}
                onChange={() => setVendorIds((ids) => (ids.includes(v.id) ? ids.filter((x) => x !== v.id) : [...ids, v.id]))}
              />{" "}
              {v.name} <span className="muted small">{v.state ?? ""}</span>
            </label>
          ))}
        </div>
        <label className="field">
          <span>Quotes due by</span>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={vendorIds.length === 0}>
            Create RFQ
          </button>
        </div>
      </form>
    </Modal>
  );
}
