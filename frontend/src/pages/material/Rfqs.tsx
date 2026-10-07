import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText, inr, num } from "../../format";
import type { Po, Rfq } from "../../material/types";
import type { Page } from "../../types";
import { shortDate } from "../Tenders";
import { StatusBadge, useMaterialLookups } from "./common";

export default function Rfqs() {
  const navigate = useNavigate();
  const [page, setPage] = useState<Page<Rfq> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Page<Rfq>>("/api/material/rfqs?limit=100").then(setPage, (err) => setError(errorText(err)));
  }, []);

  return (
    <>
      <div className="page-header">
        <h1>Requests for quotation</h1>
        <p className="muted small">Start an RFQ from approved indents (Indents › pick › Create RFQ).</p>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Indents</th>
              <th>Vendors</th>
              <th>Lines</th>
              <th>Due</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {page?.items.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/rfqs/${r.id}`)}>
                <td>
                  <code>{r.code}</code>
                </td>
                <td>{r.indent_codes.join(", ")}</td>
                <td>{r.vendors.map((v) => v.name).join(", ")}</td>
                <td>{r.lines.length}</td>
                <td>{shortDate(r.due_date)}</td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
              </tr>
            ))}
            {page?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No RFQs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

type Cell = { rate: string; gst_percent: string; freight: string };

/** The comparison grid: a row per item, a column per vendor. The lowest landed rate (rate + its
 * share of the vendor's freight) is marked and picked unless you choose another with a reason. */
export function RfqDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const canEdit = can("po.edit");
  const [rfq, setRfq] = useState<Rfq | null>(null);
  const [cells, setCells] = useState<Record<string, Cell>>({});
  const [freight, setFreight] = useState<Record<number, string>>({});
  const [storeId, setStoreId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);

  const show = useCallback((r: Rfq) => {
    setRfq(r);
    const c: Record<string, Cell> = {};
    for (const ln of r.lines) for (const q of ln.quotes) c[`${ln.id}:${q.vendor_id}`] = { rate: q.rate, gst_percent: q.gst_percent, freight: q.freight };
    setCells(c);
    setFreight(Object.fromEntries(r.vendors.map((v) => [v.vendor_id, v.freight])));
  }, []);

  useEffect(() => {
    api<Rfq>(`/api/material/rfqs/${id}`).then(show, (err) => setError(errorText(err)));
  }, [id, show]);

  async function run<T>(p: Promise<T>): Promise<T | null> {
    setError(null);
    try {
      return await p;
    } catch (err) {
      setError(errorText(err));
      return null;
    }
  }

  async function saveQuotes() {
    if (!rfq) return;
    const quotes = Object.entries(cells)
      .filter(([, c]) => c.rate !== "")
      .map(([key, c]) => {
        const [line, vendor] = key.split(":").map(Number);
        return { rfq_line_id: line, vendor_id: vendor, rate: c.rate, gst_percent: c.gst_percent || "18", freight: c.freight || "0" };
      });
    const vendor_freight = Object.entries(freight).map(([v, f]) => ({ vendor_id: Number(v), freight: f || "0" }));
    const r = await run(api<Rfq>(`/api/material/rfqs/${rfq.id}/quotes`, { method: "PUT", json: { quotes, vendor_freight } }));
    if (r) show(r);
  }

  async function choose(lineId: number, vendorId: number, lowest: boolean) {
    if (!rfq) return;
    let reason: string | null = null;
    if (!lowest) {
      reason = prompt("This is not the lowest landed rate. Why this vendor?");
      if (!reason) return;
    }
    const r = await run(api<Rfq>(`/api/material/rfqs/${rfq.id}/choose`, { method: "POST", json: [{ rfq_line_id: lineId, vendor_id: vendorId, reason }] }));
    if (r) show(r);
  }

  async function makePos() {
    if (!rfq) return;
    const q = storeId ? `?store_id=${storeId}` : "";
    const pos = await run(api<Po[]>(`/api/material/rfqs/${rfq.id}/po${q}`, { method: "POST" }));
    if (pos?.length) navigate(pos.length === 1 ? `/purchase-orders/${pos[0].id}` : "/purchase-orders");
  }

  if (!rfq) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const open = canEdit && !["closed", "cancelled"].includes(rfq.status);
  const set = (key: string, patch: Partial<Cell>) => setCells((c) => ({ ...c, [key]: { ...(c[key] ?? { rate: "", gst_percent: "18", freight: "0" }), ...patch } }));

  return (
    <>
      <p className="breadcrumb">
        <Link to="/rfqs">RFQs</Link> / <code>{rfq.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {rfq.code} <StatusBadge status={rfq.status} />
          </h1>
          <p className="muted">
            For {rfq.indent_codes.join(", ")} · due {shortDate(rfq.due_date)}
            {rfq.po_ids.length > 0 && (
              <>
                {" · POs "}
                {rfq.po_ids.map((p) => (
                  <Link key={p} to={`/purchase-orders/${p}`} className="push-right">
                    #{p}
                  </Link>
                ))}
              </>
            )}
          </p>
        </div>
        {open && (
          <div className="page-actions">
            <button className="btn" onClick={() => void saveQuotes()}>
              Save quotes
            </button>
            {lookups && (
              <select value={storeId} onChange={(e) => setStoreId(e.target.value ? Number(e.target.value) : "")} aria-label="Deliver to">
                <option value="">Deliver to: the indent's store</option>
                {lookups.stores.map((s) => (
                  <option key={s.id} value={s.id}>
                    Deliver to: {s.name}
                  </option>
                ))}
              </select>
            )}
            <button className="btn btn-primary" onClick={() => void makePos()}>
              Make PO(s) from the picks
            </button>
          </div>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="card table-wrap">
        <table className="table compare">
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Qty</th>
              {rfq.vendors.map((v) => (
                <th key={v.vendor_id}>
                  {v.name}
                  <div className="small muted">
                    Freight (total){" "}
                    {open ? (
                      <input className="input-num" value={freight[v.vendor_id] ?? ""} onChange={(e) => setFreight((f) => ({ ...f, [v.vendor_id]: e.target.value }))} />
                    ) : (
                      inr(v.freight)
                    )}
                  </div>
                  <div className="small">Landed total {inr(v.total)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rfq.lines.map((ln) => {
              const chosen = ln.chosen_vendor_id ?? ln.quotes.find((q) => q.lowest)?.vendor_id;
              return (
                <tr key={ln.id}>
                  <td>
                    {ln.product_name}
                    {ln.choice_reason && <div className="small text-warn">Picked over the lowest: {ln.choice_reason}</div>}
                  </td>
                  <td className="num nowrap">
                    {num(ln.qty)} {ln.unit}
                  </td>
                  {rfq.vendors.map((v) => {
                    const key = `${ln.id}:${v.vendor_id}`;
                    const q = ln.quotes.find((x) => x.vendor_id === v.vendor_id);
                    const c = cells[key];
                    return (
                      <td key={v.vendor_id} className={q?.lowest ? "cell-best" : ""}>
                        {open ? (
                          <div className="quote-inputs">
                            <input
                              className="input-num"
                              placeholder="rate"
                              value={c?.rate ?? ""}
                              onChange={(e) => set(key, { rate: e.target.value })}
                              aria-label={`${v.name} rate`}
                            />
                            <input
                              className="input-num"
                              placeholder="GST %"
                              value={c?.gst_percent ?? "18"}
                              onChange={(e) => set(key, { gst_percent: e.target.value })}
                              aria-label={`${v.name} GST`}
                            />
                          </div>
                        ) : (
                          q && <div>{inr(q.rate)}</div>
                        )}
                        {q && (
                          <label className="small check">
                            {open && <input type="radio" name={`pick-${ln.id}`} checked={chosen === v.vendor_id} onChange={() => void choose(ln.id, v.vendor_id, q.lowest)} />}
                            landed {inr(q.landed_rate)}
                            {q.lowest && <span className="badge badge-ok">lowest</span>}
                            {!open && chosen === v.vendor_id && <span className="badge badge-info">picked</span>}
                          </label>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">Landed rate = rate + the line's share of the vendor's freight (shared by value). Save the quotes to see it.</p>
    </>
  );
}
