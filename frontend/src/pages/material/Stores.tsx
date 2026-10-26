import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, queryString } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText, inr, num } from "../../format";
import type { Issue, LedgerRow, MaterialLookups, StockRow, StoreRow, Transfer } from "../../material/types";
import type { Page } from "../../types";
import { shortDate } from "../Tenders";
import { dateTime, ProductSelect, StatusBadge, today, UnitSelect, useMaterialLookups } from "./common";
import { Button, buttonClass, Card, Field } from "../../ui/components";

export default function Stores() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const load = useCallback(() => api<StoreRow[]>("/api/material/stores").then(setStores, (err) => setError(errorText(err))), []);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/material/stores", { method: "POST", json: { name } });
      setAdding(false);
      setName("");
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Stores &amp; stock</h1>
        <div className="page-actions">
          <Link className={buttonClass()} to="/transfers">
            Transfers
          </Link>
          {can("store.edit") && (
            <Button onClick={() => setAdding(true)}>
              Add godown
            </Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div" className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Store</th>
              <th>Kind</th>
              <th className="num">Items in stock</th>
              <th className="num">Stock value</th>
            </tr>
          </thead>
          <tbody>
            {stores.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => navigate(`/stores/${s.id}`)}>
                <td>{s.name}</td>
                <td>{s.kind === "godown" ? "Godown" : "Site store"}</td>
                <td className="num">{s.items}</td>
                <td className="num">{inr(s.value)}</td>
              </tr>
            ))}
            {stores.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">
                  No stores you can see.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
      {adding && (
        <Modal title="Add a godown" onClose={() => setAdding(false)}>
          <form onSubmit={add}>
            <Field label="Name">
              <input required autoFocus value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <div className="form-actions">
              <Button type="submit" variant="primary">Add</Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

export function StockTable({ rows }: { rows: StockRow[] }) {
  return (
    <Card as="div" className="table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>Product</th>
            <th className="num">Stock</th>
            <th className="num">Avg rate (landed)</th>
            <th className="num">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.product_id} className={Number(r.qty) < 0 ? "row-flagged" : ""}>
              <td>
                {r.product_name} <span className="muted small">{r.product_code}</span>
              </td>
              <td className="num">
                {num(r.qty, 3)} {r.unit}
              </td>
              <td className="num">{inr(r.avg_rate)}</td>
              <td className="num">{inr(r.value)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="empty">
                Nothing in stock.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

const REF_LABEL: Record<string, string> = {
  grn: "GRN",
  transfer_out: "Transfer out",
  transfer_in: "Transfer in",
  issue: "Issued to site",
  return: "Returned",
  adjust: "Adjustment",
  opening: "Opening",
};

export function StoreDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [store, setStore] = useState<StoreRow | null>(null);
  const [tab, setTab] = useState<"stock" | "ledger" | "transfers" | "issues">("stock");
  const [stock, setStock] = useState<StockRow[]>([]);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [productId, setProductId] = useState<number | "">("");
  const [dialog, setDialog] = useState<null | "transfer" | "issue" | "return" | "adjust">(null);
  const [receiving, setReceiving] = useState<Transfer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await api<StoreRow[]>("/api/material/stores");
      const s = all.find((x) => x.id === Number(id)) ?? null;
      setStore(s);
      if (!s) return setError("Store not found");
      setStock(await api<StockRow[]>(`/api/material/stores/${id}/stock`));
      setLedger(await api<LedgerRow[]>(`/api/material/stores/${id}/ledger${queryString({ product_id: productId || undefined })}`));
      setTransfers((await api<Page<Transfer>>(`/api/material/transfers?store_id=${id}&limit=100`)).items);
      setIssues((await api<Page<Issue>>(`/api/material/issues?store_id=${id}&limit=100`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [id, productId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!store) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const edit = can("store.edit");

  return (
    <>
      <p className="breadcrumb">
        <Link to="/stores">Stores</Link> / {store.name}
      </p>
      <div className="page-header">
        <div>
          <h1>{store.name}</h1>
          <p className="muted">
            {store.kind === "godown" ? "Godown" : "Site store"} · stock value {inr(store.value)}
            {store.site_id && (
              <>
                {" · "}
                <Link to={`/sites/${store.site_id}`}>{store.site_code}</Link>
              </>
            )}
          </p>
        </div>
        {edit && lookups && (
          <div className="page-actions">
            <Button onClick={() => setDialog("transfer")}>
              Transfer out
            </Button>
            {store.site_id && (
              <>
                <Button onClick={() => setDialog("issue")}>
                  Issue to work
                </Button>
                <Button onClick={() => setDialog("return")}>
                  Return to store
                </Button>
              </>
            )}
            <Button onClick={() => setDialog("adjust")}>
              Adjust / opening
            </Button>
          </div>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="tabs tabs-inline">
        {(["stock", "ledger", "transfers", "issues"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "issues" ? "Issues & returns" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="top-gap">
        {tab === "stock" && <StockTable rows={stock} />}
        {tab === "ledger" && (
          <>
            {lookups && (
              <div className="toolbar">
                <ProductSelect products={lookups.products} value={productId} onChange={(p) => setProductId(p?.id ?? "")} />
              </div>
            )}
            <Card as="div" className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Product</th>
                    <th>Movement</th>
                    <th>Ref</th>
                    <th className="num">Qty</th>
                    <th className="num">Rate</th>
                    <th className="num">Value</th>
                    <th className="num">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{dateTime(r.at)}</td>
                      <td>{r.product_name}</td>
                      <td>{REF_LABEL[r.ref_type] ?? r.ref_type}</td>
                      <td>
                        <code>{r.ref_code ?? ""}</code> <span className="muted small">{r.note && r.note !== r.ref_code ? r.note : ""}</span>
                      </td>
                      <td className={`num ${Number(r.qty) < 0 ? "text-danger" : ""}`}>
                        {num(r.qty, 3)} {r.unit}
                      </td>
                      <td className="num">{inr(r.rate)}</td>
                      <td className="num">{inr(r.value)}</td>
                      <td className="num">{num(r.balance, 3)}</td>
                    </tr>
                  ))}
                  {ledger.length === 0 && (
                    <tr>
                      <td colSpan={8} className="empty">
                        No movements.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>
          </>
        )}
        {tab === "transfers" && <TransferTable transfers={transfers} onReceive={setReceiving} onChanged={load} />}
        {tab === "issues" && <IssueTable issues={issues} />}
      </div>
      {lookups && dialog === "transfer" && (
        <TransferForm lookups={lookups} fromStoreId={store.id} onClose={() => setDialog(null)} onSaved={async () => (setDialog(null), await load())} />
      )}
      {lookups && (dialog === "issue" || dialog === "return") && store.site_id && (
        <IssueForm
          lookups={lookups}
          kind={dialog}
          siteId={store.site_id}
          storeId={store.id}
          onClose={() => setDialog(null)}
          onSaved={async () => (setDialog(null), await load())}
        />
      )}
      {lookups && dialog === "adjust" && <AdjustForm lookups={lookups} storeId={store.id} onClose={() => setDialog(null)} onSaved={async () => (setDialog(null), await load())} />}
      {receiving && <ReceiveForm transfer={receiving} onClose={() => setReceiving(null)} onSaved={async () => (setReceiving(null), await load())} />}
    </>
  );
}

export function TransferTable({ transfers, onReceive, onChanged }: { transfers: Transfer[]; onReceive: (t: Transfer) => void; onChanged?: () => void | Promise<void> }) {
  const [error, setError] = useState<string | null>(null);
  async function dispatch(t: Transfer) {
    setError(null);
    try {
      await api(`/api/material/transfers/${t.id}/dispatch`, { method: "POST" });
      await onChanged?.();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Card as="div" className="table-wrap">
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Code</th>
            <th>From → to</th>
            <th>Items</th>
            <th className="num">Freight</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {transfers.map((t) => (
            <tr key={t.id}>
              <td>
                <code>{t.code}</code>
                <div className="small muted">{dateTime(t.dispatched_at ?? t.created_at)}</div>
              </td>
              <td>
                {t.from_store_name} → {t.to_store_name}
              </td>
              <td className="small">
                {t.lines.map((l) => (
                  <div key={l.id}>
                    {l.product_name}: {num(l.qty_sent, 3)} {l.unit}
                    {Number(l.shortage_qty) > 0 && (
                      <span className="text-danger">
                        {" "}
                        (short {num(l.shortage_qty, 3)}: {l.shortage_reason})
                      </span>
                    )}
                  </div>
                ))}
              </td>
              <td className="num">{inr(t.freight_amount)}</td>
              <td>
                <StatusBadge status={t.status} />
              </td>
              <td>
                {t.can_dispatch && onChanged && (
                  <Button size="small" onClick={() => void dispatch(t)}>
                    Dispatch
                  </Button>
                )}
                {t.can_receive && (
                  <Button variant="primary" size="small" onClick={() => onReceive(t)}>
                    Receive
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {transfers.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                No transfers.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

export function IssueTable({ issues }: { issues: Issue[] }) {
  return (
    <Card as="div" className="table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>Code</th>
            <th>Date</th>
            <th>Kind</th>
            <th>For</th>
            <th>Items</th>
            <th className="num">Value</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((i) => (
            <tr key={i.id}>
              <td>
                <code>{i.code}</code>
              </td>
              <td className="nowrap">{shortDate(i.issued_on)}</td>
              <td>{i.kind === "issue" ? "Issue" : "Return"}</td>
              <td>{i.task_name ?? "—"}</td>
              <td className="small">{i.lines.map((l) => `${l.product_name} ${num(l.qty, 3)} ${l.unit}`).join(", ")}</td>
              <td className="num">{inr(i.lines.reduce((s, l) => s + Number(l.value), 0))}</td>
            </tr>
          ))}
          {issues.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                No issues or returns.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

type QtyLine = { product_id: number | ""; qty: string; unit: string };

function QtyLines({ lookups, lines, setLines }: { lookups: MaterialLookups; lines: QtyLine[]; setLines: (f: (l: QtyLine[]) => QtyLine[]) => void }) {
  const set = (i: number, patch: Partial<QtyLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <>
      <div className="line-cards">
        {lines.map((l, i) => (
          <div key={i} className="line-card">
            <ProductSelect label="Product" products={lookups.products} value={l.product_id} onChange={(p) => set(i, { product_id: p?.id ?? "", unit: p?.unit ?? "" })} />
            <div className="line-row">
              <Field label="Qty">
                <input inputMode="decimal" value={l.qty} onChange={(e) => set(i, { qty: e.target.value })} />
              </Field>
              <UnitSelect label="Unit" units={lookups.units} value={l.unit || lookups.units[0]} onChange={(u) => set(i, { unit: u })} />
              <Button type="button" variant="ghost" icon aria-label="Remove line" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>
                ×
              </Button>
            </div>
          </div>
        ))}
      </div>
      <Button type="button" size="small" className="top-gap" onClick={() => setLines((ls) => [...ls, { product_id: "", qty: "", unit: "" }])}>
        + Item
      </Button>
    </>
  );
}

const cleanLines = (lines: QtyLine[]) => lines.filter((l) => l.product_id && Number(l.qty) > 0).map((l) => ({ product_id: l.product_id, qty: l.qty, unit: l.unit || null }));

export function TransferForm({
  lookups,
  fromStoreId,
  toStoreId,
  onClose,
  onSaved,
}: {
  lookups: MaterialLookups;
  fromStoreId?: number;
  toStoreId?: number;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const godown = lookups.stores.find((s) => s.kind === "godown");
  const [form, setForm] = useState({
    from_store_id: fromStoreId ?? godown?.id ?? ("" as number | ""),
    to_store_id: toStoreId ?? ("" as number | ""),
    vehicle_no: "",
    transporter: "",
    freight_amount: "",
    remark: "",
  });
  // from a site's tab it is a request (the godown dispatches it); from a store it goes now
  const [dispatchNow, setDispatchNow] = useState(!toStoreId);
  const [lines, setLines] = useState<QtyLine[]>([{ product_id: "", qty: "", unit: "" }]);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/material/transfers", {
        method: "POST",
        json: {
          ...form,
          freight_amount: form.freight_amount || "0",
          vehicle_no: form.vehicle_no || null,
          transporter: form.transporter || null,
          remark: form.remark || null,
          dispatch: dispatchNow,
          lines: cleanLines(lines),
        },
      });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const store = (k: "from_store_id" | "to_store_id", label: string) => (
    <Field label={<>{label} *</>}>
      <select required value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })}>
        <option value="">—</option>
        {lookups.stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <Modal title="Transfer material" onClose={onClose} wide>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          {store("from_store_id", "From")}
          {store("to_store_id", "To")}
          <Field label="Transporter">
            <input value={form.transporter} onChange={(e) => setForm({ ...form, transporter: e.target.value })} />
          </Field>
          <Field label="Vehicle no">
            <input value={form.vehicle_no} onChange={(e) => setForm({ ...form, vehicle_no: e.target.value })} />
          </Field>
          <Field label="Freight (₹, charged to the receiving site)">
            <input inputMode="decimal" value={form.freight_amount} onChange={(e) => setForm({ ...form, freight_amount: e.target.value })} />
          </Field>
          <Field label="Remark">
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </Field>
        </div>
        <QtyLines lookups={lookups} lines={lines} setLines={setLines} />
        <label className="check top-gap">
          <input type="checkbox" checked={dispatchNow} onChange={(e) => setDispatchNow(e.target.checked)} /> Dispatch now (stock leaves the sending store)
        </label>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">{dispatchNow ? "Dispatch" : "Save request"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function ReceiveForm({ transfer, onClose, onSaved }: { transfer: Transfer; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [rows, setRows] = useState(transfer.lines.map((l) => ({ line_id: l.id, qty_received: l.qty_sent, shortage_reason: "" })));
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(`/api/material/transfers/${transfer.id}/receive`, { method: "POST", json: { lines: rows.map((r) => ({ ...r, shortage_reason: r.shortage_reason || null })) } });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`Receive ${transfer.code} at ${transfer.to_store_name}`} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="line-cards">
          {transfer.lines.map((l, i) => {
            const short = Number(l.qty_sent) - Number(rows[i].qty_received || 0);
            return (
              <div key={l.id} className="line-card">
                <strong>
                  {l.product_name}{" "}
                  <span className="muted small">
                    sent {num(l.qty_sent, 3)} {l.unit}
                  </span>
                </strong>
                <Field label="Received">
                  <input
                    inputMode="decimal"
                    value={rows[i].qty_received}
                    onChange={(e) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, qty_received: e.target.value } : r)))}
                  />
                </Field>
                {short > 0 && (
                  <Field label={<>Short by {num(short, 3)}: reason *</>}>
                    <input
                      required
                      value={rows[i].shortage_reason}
                      onChange={(e) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, shortage_reason: e.target.value } : r)))}
                    />
                  </Field>
                )}
              </div>
            );
          })}
        </div>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">Receive</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Mobile-friendly issue / return form for the site. */
export function IssueForm({
  lookups,
  kind,
  siteId,
  storeId,
  onClose,
  onSaved,
}: {
  lookups: MaterialLookups;
  kind: "issue" | "return";
  siteId: number;
  storeId?: number;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [tasks, setTasks] = useState<{ id: number; name: string; node_path: string | null }[]>([]);
  const [form, setForm] = useState({ task_id: "" as number | "", issued_on: today(), remark: "" });
  const [lines, setLines] = useState<QtyLine[]>([{ product_id: "", qty: "", unit: "" }]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ id: number; name: string; node_path: string | null }[]>(`/api/sites/${siteId}/tasks`).then(setTasks, () => setTasks([]));
  }, [siteId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/material/issues", {
        method: "POST",
        json: { kind, site_id: siteId, store_id: storeId ?? null, task_id: form.task_id || null, issued_on: form.issued_on, remark: form.remark || null, lines: cleanLines(lines) },
      });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={kind === "issue" ? "Issue material to work" : "Return unused material to the store"} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        {kind === "issue" && (
          <Field label="For task">
            <select value={form.task_id} onChange={(e) => setForm({ ...form, task_id: Number(e.target.value) || "" })}>
              <option value="">— general site use —</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.node_path ? `${t.node_path} · ` : ""}
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="grid-2">
          <Field label="Date">
            <input type="date" value={form.issued_on} onChange={(e) => setForm({ ...form, issued_on: e.target.value })} />
          </Field>
          <Field label="Remark">
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </Field>
        </div>
        <QtyLines lookups={lookups} lines={lines} setLines={setLines} />
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">{kind === "issue" ? "Issue" : "Return"}</Button>
        </div>
      </form>
    </Modal>
  );
}

function AdjustForm({ lookups, storeId, onClose, onSaved }: { lookups: MaterialLookups; storeId: number; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [form, setForm] = useState({ product_id: "" as number | "", qty: "", rate: "", kind: "adjust", note: "" });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/material/stores/${storeId}/adjust`, { method: "POST", json: { ...form, rate: form.rate || null } });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="Opening stock or count correction" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <ProductSelect label="Product" required products={lookups.products} value={form.product_id} onChange={(p) => setForm({ ...form, product_id: p?.id ?? "" })} />
        <div className="grid-2">
          <Field label="Kind">
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="opening">Opening stock</option>
              <option value="adjust">Count correction</option>
            </select>
          </Field>
          <Field label="Qty (+ in / − out, in the product's unit)">
            <input required inputMode="decimal" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
          </Field>
          <Field label="Rate (for stock added)">
            <input inputMode="decimal" value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} />
          </Field>
          <Field label="Note *">
            <input required value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Field>
        </div>
        <div className="form-actions">
          <Button type="submit" variant="primary">Save</Button>
        </div>
      </form>
    </Modal>
  );
}

export function Transfers() {
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [page, setPage] = useState<Page<Transfer> | null>(null);
  const [creating, setCreating] = useState(false);
  const [receiving, setReceiving] = useState<Transfer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Page<Transfer>>("/api/material/transfers?limit=200").then(setPage, (err) => setError(errorText(err))), []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <h1>Transfers</h1>
        {can("store.edit") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            New transfer
          </Button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <TransferTable transfers={page?.items ?? []} onReceive={setReceiving} onChanged={load} />
      {creating && lookups && <TransferForm lookups={lookups} onClose={() => setCreating(false)} onSaved={async () => (setCreating(false), await load())} />}
      {receiving && <ReceiveForm transfer={receiving} onClose={() => setReceiving(null)} onSaved={async () => (setReceiving(null), await load())} />}
    </>
  );
}
