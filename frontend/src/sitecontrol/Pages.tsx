// Site control (9 Oct meeting): deliveries confirmed at site, rate contracts, ready to bill,
// new areas, labour productivity, consumption variance and their settings.
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";

const fmt = (d: string | null | undefined, time = true) =>
  d
    ? new Date(d).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", ...(time ? { hour: "2-digit", minute: "2-digit" } : {}) })
    : "—";
const n = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits });
const money = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "—" : `₹ ${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type SiteOpt = { id: number; code: string; name: string };
function useSites(): SiteOpt[] {
  const [sites, setSites] = useState<SiteOpt[]>([]);
  useEffect(() => {
    void api<{ items: SiteOpt[] }>("/api/sites?limit=200").then(
      (r) => setSites(r.items),
      () => setSites([]),
    );
  }, []);
  return sites;
}

function Thumb({ path, alt }: { path: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    void fetchObjectUrl(path).then((u) => !gone && setUrl(u));
    return () => {
      gone = true;
    };
  }, [path]);
  return url ? (
    <a href={url} target="_blank" rel="noreferrer">
      <img className="thumb" src={url} alt={alt} />
    </a>
  ) : null;
}

// --- deliveries ----------------------------------------------------------------------------------

type DnRow = {
  id: number;
  code: string;
  kind: "po" | "transfer";
  site_id: number;
  site: string;
  vendor: string | null;
  status: "dispatched" | "confirmed" | "short" | "cancelled";
  expected_at: string;
  expected_label: string;
  confirmed_at: string | null;
  receiver_name: string | null;
  unlisted_receiver: boolean;
  age_hours: number | null;
  discrepancies: number;
  items: number;
  drop_photo: boolean;
};

const DN_BADGE: Record<string, string> = { dispatched: "badge-info", confirmed: "badge-ok", short: "badge-danger", cancelled: "badge-muted" };

export function Deliveries() {
  const [params, setParams] = useSearchParams();
  const sites = useSites();
  const [rows, setRows] = useState<DnRow[] | null>(null);
  const [error, setError] = useState("");
  const site = params.get("site") ?? "";
  const state = params.get("state") ?? "";
  useEffect(() => {
    const q = new URLSearchParams();
    if (site) q.set("site_id", site);
    if (state) q.set("state", state);
    api<DnRow[]>(`/api/sitecontrol/deliveries?${q}`).then(setRows, (e) => setError(errorText(e)));
  }, [site, state]);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const open = rows?.filter((r) => r.status === "dispatched").length ?? 0;
  const [testLink, setTestLink] = useState(false);
  useEffect(() => {
    void api<{ test_link: boolean }>("/api/sitecontrol/link-status").then(
      (r) => setTestLink(r.test_link),
      () => setTestLink(false),
    );
  }, []);
  return (
    <>
      <div className="page-header">
        <h1>Deliveries at site</h1>
        <div className="page-actions">
          <select value={site} onChange={(e) => set("site", e.target.value)} aria-label="Site">
            <option value="">All sites</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {testLink && (
        <div className="alert alert-warn">
          Test links: the app address (PUBLIC_BASE_URL) is still this PC, so receipt links and QR codes open only on the office PC. Do not send these delivery notes to site until
          it is set to the public address.
        </div>
      )}
      <p className="muted small">
        Every dispatch to a site is counted there: the receipt link on the delivery note (QR) opens its items, two photos, the receiver's name. Stock follows the count.
      </p>
      <div className="tabs" role="tablist">
        {[
          ["", "All"],
          ["unconfirmed", `Not confirmed${open ? ` (${open})` : ""}`],
          ["short", "Short / damaged"],
          ["confirmed", "Confirmed"],
        ].map(([k, label]) => (
          <button key={k} className={`tab ${state === k ? "active" : ""}`} onClick={() => set("state", k)}>
            {label}
          </button>
        ))}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">No deliveries here.</p>
      ) : (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Delivery</th>
                <th>Site</th>
                <th>From</th>
                <th>Expected</th>
                <th>Status</th>
                <th className="num">Not confirmed for</th>
                <th>Received by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.status === "dispatched" && (r.age_hours ?? 0) > 24 ? "row-overdue" : undefined}>
                  <td>
                    <Link to={`/deliveries/${r.id}`}>{r.code}</Link> <span className="muted small">{r.items} item(s)</span>
                  </td>
                  <td>{r.site}</td>
                  <td className="small">{r.kind === "po" ? r.vendor : "Godown transfer"}</td>
                  <td className="small">{r.expected_label}</td>
                  <td>
                    <span className={`badge ${DN_BADGE[r.status]}`}>{r.status === "dispatched" ? "not confirmed" : r.status}</span>
                    {r.discrepancies > 0 && <span className="badge badge-danger">{r.discrepancies} discrepancy</span>}
                    {r.drop_photo && <span className="badge badge-muted">drop-off photo</span>}
                  </td>
                  <td className={`num ${(r.age_hours ?? 0) > 48 ? "text-danger" : ""}`}>
                    {r.age_hours !== null ? (r.age_hours > 0 ? `${Math.round(r.age_hours)} h` : "due") : ""}
                  </td>
                  <td className="small">
                    {r.receiver_name ?? "—"} {r.unlisted_receiver && <span className="badge badge-warn">unlisted receiver</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

type DnDetail = DnRow & {
  vehicle_no: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  receiver_phone: string | null;
  gps: { lat: string; lng: string; accuracy_m: string | null } | null;
  photos: ("goods" | "challan" | "drop")[];
  drop_photo_at: string | null;
  lines: { id: number; product: string; qty: string; unit: string; packs: string | null; pack_unit: string | null; received_qty: string | null; damaged_qty: string | null }[];
  discrepancies: { kind: string; qty: string; unit: string; product: string; debit_note_id: number | null }[];
  debit_notes: { id: number; code: string; status: string; amount: string; lines: { product: string; kind: string; qty: string; unit: string; rate: string; amount: string }[] }[];
  grn_id: number | null;
  can_confirm: boolean;
};

export function DeliveryDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [d, setD] = useState<DnDetail | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [edit, setEdit] = useState(false);
  const load = useCallback(() => api<DnDetail>(`/api/sitecontrol/deliveries/${id}`).then(setD, (e) => setError(errorText(e))), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (error && !d) return <div className="alert alert-error">{error}</div>;
  if (!d) return <p className="muted">Loading…</p>;
  const store = can("store.edit", "po.edit");
  async function drop(file: File) {
    const form = new FormData();
    form.append("photo", file);
    try {
      setD(await api<DnDetail>(`/api/sitecontrol/deliveries/${id}/drop-photo`, { method: "POST", form }));
      setMsg("The driver's drop-off photo is attached: proof of drop-off, not of quantity.");
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="breadcrumb">
        <Link to="/deliveries">Deliveries</Link>
      </div>
      <div className="page-header">
        <div>
          <h1>
            {d.code} <span className={`badge ${DN_BADGE[d.status]}`}>{d.status === "dispatched" ? "not confirmed" : d.status}</span>
          </h1>
          <p className="muted small">
            {d.site} · {d.kind === "po" ? `PO delivery from ${d.vendor}` : "godown transfer"} · expected {d.expected_label}
            {d.age_hours !== null && d.age_hours > 0 && <b className="text-danger"> · {Math.round(d.age_hours)} h not confirmed</b>}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-small" onClick={() => void downloadFile(`/api/sitecontrol/deliveries/${d.id}/pdf`).catch((e) => setError(errorText(e)))}>
            ⤓ Delivery note (QR)
          </button>
          {store && d.status === "dispatched" && (
            <>
              <button className="btn btn-small" onClick={() => setEdit(true)}>
                Driver / vehicle
              </button>
              <label className="btn btn-small btn-ghost">
                Driver's drop-off photo
                <input type="file" accept="image/*" hidden onChange={(e) => e.target.files?.[0] && void drop(e.target.files[0])} />
              </label>
            </>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="grid-2">
        <div className="card">
          <h2 className="section-title">Items</h2>
          <table className="table compact">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Sent</th>
                <th className="num">Received</th>
                <th className="num">Damaged</th>
              </tr>
            </thead>
            <tbody>
              {d.lines.map((l) => (
                <tr key={l.id} className={l.received_qty !== null && Number(l.received_qty) < Number(l.qty) ? "row-overdue" : undefined}>
                  <td>{l.product}</td>
                  <td className="num">
                    {n(l.qty, 3)} {l.unit}
                    {l.packs && (
                      <div className="muted small">
                        {n(l.packs)} {l.pack_unit}
                      </div>
                    )}
                  </td>
                  <td className="num">{l.received_qty !== null ? n(l.received_qty, 3) : "—"}</td>
                  <td className="num">{l.damaged_qty !== null ? n(l.damaged_qty, 3) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.discrepancies.length > 0 && (
            <>
              <h3 className="section-title top-gap">Discrepancies</h3>
              {d.discrepancies.map((x, i) => (
                <p key={i} className="small">
                  <span className="badge badge-danger">{x.kind}</span> {n(x.qty, 3)} {x.unit} {x.product}
                </p>
              ))}
            </>
          )}
          {d.debit_notes.map((dn) => (
            <div key={dn.id} className="debit-note">
              <b>{dn.code}</b> <span className="badge badge-warn">{dn.status}</span> debit note draft against the vendor: {money(dn.amount)}
              <ul className="small">
                {dn.lines.map((l, i) => (
                  <li key={i}>
                    {l.product}: {l.qty} {l.unit} {l.kind} × ₹{l.rate} = ₹{l.amount}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="card">
          <h2 className="section-title">Receipt</h2>
          {d.confirmed_at ? (
            <p>
              Confirmed by <b>{d.receiver_name}</b> {d.receiver_phone && `(${d.receiver_phone})`} on {fmt(d.confirmed_at)}{" "}
              {d.unlisted_receiver && <span className="badge badge-warn">unlisted receiver: review</span>}
            </p>
          ) : (
            <p className="muted">Not confirmed yet. The supervisor (or the site's named receiver) scans the QR on the delivery note.</p>
          )}
          {d.gps && (
            <p className="small">
              GPS {d.gps.lat}, {d.gps.lng} {d.gps.accuracy_m && `(±${n(d.gps.accuracy_m, 0)} m)`}
            </p>
          )}
          <div className="thumbs">
            {d.photos.map((p) => (
              <figure key={p}>
                <Thumb path={`/api/sitecontrol/deliveries/${d.id}/photo/${p}`} alt={p} />
                <figcaption className="small">
                  {p === "goods" ? "Material as unloaded" : p === "challan" ? "Signed challan" : `Driver's drop-off (${fmt(d.drop_photo_at)})`}
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="small muted">
            Vehicle {d.vehicle_no ?? "—"} · driver {d.driver_name ?? "—"} {d.driver_phone ?? ""}
          </p>
          {d.can_confirm && <ConfirmForm d={d} onDone={(x) => (setD(x), setMsg("Confirmed: stock now follows your count."))} />}
        </div>
      </div>
      {edit && (
        <EditDriver
          d={d}
          onClose={() => setEdit(false)}
          onSaved={(x) => (setD(x), setEdit(false), setMsg("Printed again with a new receipt link: the old link no longer works."))}
        />
      )}
    </>
  );
}

function ConfirmForm({ d, onDone }: { d: DnDetail; onDone: (x: DnDetail) => void }) {
  const [counts, setCounts] = useState<Record<number, { received: string; damaged: string }>>({});
  const [goods, setGoods] = useState<File | null>(null);
  const [challan, setChallan] = useState<File | null>(null);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    const form = new FormData();
    form.append("lines", JSON.stringify(d.lines.map((l) => ({ line_id: l.id, received: counts[l.id]?.received ?? "", damaged: counts[l.id]?.damaged || 0 }))));
    if (goods) form.append("photo_goods", goods);
    if (challan) form.append("photo_challan", challan);
    try {
      onDone(await api<DnDetail>(`/api/sitecontrol/deliveries/${d.id}/confirm`, { method: "POST", form }));
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <form className="confirm-form" onSubmit={(e) => void submit(e)}>
      <h3 className="section-title">Confirm (count it yourself)</h3>
      {d.lines.map((l) => (
        <div key={l.id} className="inline-form">
          <span className="grow">{l.product}</span>
          <input
            placeholder="received"
            inputMode="decimal"
            value={counts[l.id]?.received ?? ""}
            onChange={(e) => setCounts({ ...counts, [l.id]: { received: e.target.value, damaged: counts[l.id]?.damaged ?? "" } })}
          />
          <input
            placeholder="damaged"
            inputMode="decimal"
            value={counts[l.id]?.damaged ?? ""}
            onChange={(e) => setCounts({ ...counts, [l.id]: { received: counts[l.id]?.received ?? "", damaged: e.target.value } })}
          />
          <span className="small muted">{l.unit}</span>
        </div>
      ))}
      <label className="field">
        <span>Photo: material as unloaded</span>
        <input type="file" accept="image/*" capture="environment" onChange={(e) => setGoods(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>Photo: signed challan</span>
        <input type="file" accept="image/*" capture="environment" onChange={(e) => setChallan(e.target.files?.[0] ?? null)} />
      </label>
      {error && <div className="alert alert-error">{error}</div>}
      <button className="btn btn-primary">Confirm delivery</button>
    </form>
  );
}

function EditDriver({ d, onClose, onSaved }: { d: DnDetail; onClose: () => void; onSaved: (x: DnDetail) => void }) {
  const [f, setF] = useState({ vehicle_no: d.vehicle_no ?? "", driver_name: d.driver_name ?? "", driver_phone: d.driver_phone ?? "", expected_at: d.expected_at.slice(0, 16) });
  const [error, setError] = useState("");
  return (
    <Modal title={`${d.code}: driver and vehicle`} onClose={onClose}>
      <div className="form-grid two">
        {(["vehicle_no", "driver_name", "driver_phone"] as const).map((k) => (
          <label key={k} className="field">
            <span>{k.replace("_", " ")}</span>
            <input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
          </label>
        ))}
        <label className="field">
          <span>Expected at site</span>
          <input type="datetime-local" value={f.expected_at} onChange={(e) => setF({ ...f, expected_at: e.target.value })} />
        </label>
      </div>
      <p className="small muted">The note is printed again with a new receipt link; the old one stops working.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          onClick={() =>
            void api<DnDetail>(`/api/sitecontrol/deliveries/${d.id}`, { method: "PUT", json: { ...f, expected_at: new Date(f.expected_at).toISOString() } }).then(onSaved, (e) =>
              setError(errorText(e)),
            )
          }
        >
          Save and print again
        </button>
      </div>
    </Modal>
  );
}

// --- rate contracts ------------------------------------------------------------------------------

type Contract = {
  id: number;
  vendor_id: number;
  vendor: string;
  product_id: number;
  product: string;
  unit: string;
  rate: string;
  freight_terms: string | null;
  valid_from: string;
  valid_till: string;
  agreed_by: string | null;
  notes: string | null;
  attachment: boolean;
  is_active: boolean;
  version: number;
  expires_in_days: number;
};

export function RateContracts() {
  const { can } = useAuth();
  const editor = can("ratecontract.edit");
  const [rows, setRows] = useState<Contract[] | null>(null);
  const [current, setCurrent] = useState(true);
  const [editing, setEditing] = useState<Contract | "new" | null>(null);
  const [versions, setVersions] = useState<Contract | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<Contract[]>(`/api/sitecontrol/rate-contracts${current ? "?current=true" : ""}`).then(setRows, (e) => setError(errorText(e))), [current]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <h1>Rate contracts</h1>
        <div className="page-actions">
          <label className="check">
            <input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} /> In force today
          </label>
          {editor && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              New contract
            </button>
          )}
        </div>
      </div>
      <p className="muted small">
        The rate agreed with each vendor per product (per base unit). New PO lines take it; a higher rate needs a reason. Accounts sees the agreed rate on every PO.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">No rate contracts yet.</p>
      ) : (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Product</th>
                <th className="num">Rate</th>
                <th>Valid</th>
                <th>Freight</th>
                <th>Agreed by</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className={c.is_active ? undefined : "muted"}>
                  <td>{c.vendor}</td>
                  <td>{c.product}</td>
                  <td className="num">
                    {money(c.rate)} <span className="muted small">/ {c.unit}</span>
                  </td>
                  <td className="small">
                    {fmt(c.valid_from, false)} – {fmt(c.valid_till, false)}{" "}
                    {c.expires_in_days >= 0 && c.expires_in_days <= 15 && <span className="badge badge-warn">ends in {c.expires_in_days} d</span>}
                  </td>
                  <td className="small">{c.freight_terms ?? "—"}</td>
                  <td className="small">{c.agreed_by ?? "—"}</td>
                  <td>
                    {editor && (
                      <button className="btn btn-small btn-ghost" onClick={() => setEditing(c)}>
                        Edit
                      </button>
                    )}
                    <button className="btn btn-small btn-ghost" onClick={() => setVersions(c)}>
                      v{c.version}
                    </button>
                    {c.attachment && (
                      <button className="btn btn-small btn-ghost" onClick={() => void downloadFile(`/api/sitecontrol/rate-contracts/${c.id}/attachment`)}>
                        ⤓ quote
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <ContractForm c={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => (setEditing(null), void load())} />}
      {versions && <ContractVersions c={versions} onClose={() => setVersions(null)} />}
    </>
  );
}

function ContractForm({ c, onClose, onSaved }: { c: Contract | null; onClose: () => void; onSaved: () => void }) {
  const [vendors, setVendors] = useState<{ id: number; name: string }[]>([]);
  const [products, setProducts] = useState<{ id: number; name: string; unit: string }[]>([]);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    vendor_id: c ? String(c.vendor_id) : "",
    product_id: c ? String(c.product_id) : "",
    rate: c?.rate ?? "",
    valid_from: c?.valid_from ?? today,
    valid_till: c?.valid_till ?? "",
    freight_terms: c?.freight_terms ?? "",
    agreed_by: c?.agreed_by ?? "",
    notes: c?.notes ?? "",
    is_active: c?.is_active ?? true,
  });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void api<{ items: { id: number; name: string }[] }>("/api/vendors?limit=200").then(
      (r) => setVendors(r.items),
      () => setVendors([]),
    );
    void api<{ items: { id: number; name: string; unit: string }[] }>("/api/products?limit=200").then(
      (r) => setProducts(r.items),
      () => setProducts([]),
    );
  }, []);
  async function save() {
    try {
      const body = {
        ...f,
        vendor_id: Number(f.vendor_id),
        product_id: Number(f.product_id),
        rate: f.rate,
        freight_terms: f.freight_terms || null,
        agreed_by: f.agreed_by || null,
        notes: f.notes || null,
      };
      const saved = await api<Contract>(c ? `/api/sitecontrol/rate-contracts/${c.id}` : "/api/sitecontrol/rate-contracts", { method: c ? "PUT" : "POST", json: body });
      if (file) {
        const form = new FormData();
        form.append("file", file);
        await api(`/api/sitecontrol/rate-contracts/${saved.id}/attachment`, { method: "POST", form });
      }
      onSaved();
    } catch (e) {
      setError(errorText(e));
    }
  }
  const unit = products.find((p) => String(p.id) === f.product_id)?.unit;
  return (
    <Modal title={c ? `Rate contract · v${c.version}` : "New rate contract"} onClose={onClose}>
      <div className="form-grid two">
        <label className="field">
          <span>Vendor</span>
          <select value={f.vendor_id} onChange={(e) => setF({ ...f, vendor_id: e.target.value })} disabled={!!c}>
            <option value="">Choose…</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Product</span>
          <select value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value })} disabled={!!c}>
            <option value="">Choose…</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Rate per {unit ?? "base unit"} (₹)</span>
          <input inputMode="decimal" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} />
        </label>
        <label className="field">
          <span>Freight terms</span>
          <input value={f.freight_terms} placeholder="e.g. delivered to site" onChange={(e) => setF({ ...f, freight_terms: e.target.value })} />
        </label>
        <label className="field">
          <span>Valid from</span>
          <input type="date" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} />
        </label>
        <label className="field">
          <span>Valid till</span>
          <input type="date" value={f.valid_till} onChange={(e) => setF({ ...f, valid_till: e.target.value })} />
        </label>
        <label className="field">
          <span>Agreed by</span>
          <input value={f.agreed_by} onChange={(e) => setF({ ...f, agreed_by: e.target.value })} />
        </label>
        <label className="field">
          <span>Vendor's quote (attachment)</span>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </div>
      <label className="field">
        <span>Notes</span>
        <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      </label>
      {c && (
        <label className="check">
          <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active
        </label>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={() => void save()}>
          Save (new version)
        </button>
      </div>
    </Modal>
  );
}

function ContractVersions({ c, onClose }: { c: Contract; onClose: () => void }) {
  const [rows, setRows] = useState<{ version: number; data: Record<string, string>; by: string | null; at: string }[]>([]);
  useEffect(() => {
    void api<typeof rows>(`/api/sitecontrol/rate-contracts/${c.id}/versions`).then(setRows);
  }, [c.id]);
  return (
    <Modal title={`${c.vendor} · ${c.product}: versions`} onClose={onClose}>
      <table className="table compact">
        <tbody>
          {rows.map((v) => (
            <tr key={v.version}>
              <td>v{v.version}</td>
              <td>{money(v.data.rate)}</td>
              <td className="small">
                {v.data.valid_from} – {v.data.valid_till}
              </td>
              <td className="small">
                {v.by ?? "—"} · {fmt(v.at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}

// --- ready to bill -------------------------------------------------------------------------------

type Ready = {
  id: number;
  site_id: number;
  site: string;
  node: string | null;
  stage: string | null;
  qty: string;
  unit: string | null;
  survey_qty: string | null;
  camera_only: boolean;
  contract_line: string | null;
  item_no: string | null;
  value: string | null;
  note: string | null;
  status: string;
  created_at: string;
  age_days: number;
  ra_bill_id: number | null;
};

export function ReadyToBill() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Ready[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<Ready[]>("/api/sitecontrol/ready-to-bill").then(setRows, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  const sites = [...new Set(rows?.map((r) => r.site_id) ?? [])];
  async function raise(siteId: number) {
    try {
      const r = await api<{ ra_bill_id: number; code: string }>("/api/sitecontrol/ready-to-bill/raise", { method: "POST", json: { site_id: siteId } });
      navigate(`/billing/ra/${r.ra_bill_id}`);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="page-header">
        <h1>Work done, not billed</h1>
      </div>
      <p className="muted small">
        A stage whose last task is done on a place comes here with its measured quantity and the contract line it maps to. Not billed within 7 days: billing and the site in-charge
        are alerted.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">Nothing finished and unbilled.</p>
      ) : (
        sites.map((sid) => {
          const list = rows.filter((r) => r.site_id === sid);
          const total = list.reduce((s, r) => s + Number(r.value ?? 0), 0);
          return (
            <section key={sid} className="card top-gap">
              <div className="toolbar">
                <h2 className="section-title">
                  {list[0].site} <span className="muted small">· {money(total)}</span>
                </h2>
                {can("billing.edit") && (
                  <button className="btn btn-primary btn-small" onClick={() => void raise(sid)}>
                    Raise RA bill
                  </button>
                )}
              </div>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Place</th>
                    <th>Stage</th>
                    <th>Contract line</th>
                    <th className="num">Qty</th>
                    <th className="num">Survey</th>
                    <th className="num">Value</th>
                    <th className="num">Waiting</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((r) => (
                    <tr key={r.id} className={r.age_days > 7 ? "row-overdue" : undefined}>
                      <td>{r.node}</td>
                      <td className="small">{r.stage}</td>
                      <td className="small">
                        {r.item_no && <b>{r.item_no} </b>}
                        {r.contract_line ?? <span className="text-danger">no contract line</span>}
                        {r.camera_only && <span className="badge badge-warn">camera sizes</span>}
                        {r.note && <div className="muted">{r.note}</div>}
                      </td>
                      <td className="num">
                        {n(r.qty, 3)} {r.unit}
                      </td>
                      <td className="num">{r.survey_qty ? `${n(r.survey_qty)} sqm` : "—"}</td>
                      <td className="num">{money(r.value)}</td>
                      <td className="num">{r.age_days} d</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          );
        })
      )}
    </>
  );
}

// --- new areas -----------------------------------------------------------------------------------

type AreaReq = {
  id: number;
  site_id: number;
  site: string;
  name: string;
  area_type: string | null;
  approx_sqm: string | null;
  parent_node_id: number | null;
  photo: boolean;
  note: string | null;
  status: string;
  requested_by: string | null;
  requested_at: string;
  decided_at: string | null;
  decision_note: string | null;
};
type NodeOpt = { id: number; name: string; path: string; kind: string };

export function NewAreas() {
  const [state, setState] = useState("pending");
  const [rows, setRows] = useState<AreaReq[] | null>(null);
  const [deciding, setDeciding] = useState<{ r: AreaReq; how: "approve" | "reject" } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<AreaReq[]>(`/api/sitecontrol/new-areas?state=${state}`).then(setRows, (e) => setError(errorText(e))), [state]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <div className="page-header">
        <h1>New areas</h1>
      </div>
      <p className="muted small">
        Places not on a site's list, asked for from the phone. Approve to add them to the structure and the survey (then add them to the BOQ / contract and the material plan);
        reject to move the work booked on them to the right place.
      </p>
      <div className="tabs" role="tablist">
        {["pending", "approved", "rejected"].map((s) => (
          <button key={s} className={`tab ${state === s ? "active" : ""}`} onClick={() => setState(s)}>
            {s}
          </button>
        ))}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">None {state}.</p>
      ) : (
        <div className="area-queue">
          {rows.map((r) => (
            <div key={r.id} className="card area-req">
              {r.photo && <Thumb path={`/api/sitecontrol/new-areas/${r.id}/photo`} alt={r.name} />}
              <div className="grow">
                <h3>{r.name}</h3>
                <p className="small">
                  {r.site} · {r.area_type ?? "area type not given"} · {r.approx_sqm ? `about ${n(r.approx_sqm)} sqm` : "size not given"}
                </p>
                <p className="small muted">
                  asked by {r.requested_by ?? "—"} on {fmt(r.requested_at)}
                  {r.note && ` · “${r.note}”`}
                </p>
                {r.decision_note && <p className="small">Decision: {r.decision_note}</p>}
              </div>
              {r.status === "pending" && (
                <div className="panel-actions">
                  <button className="btn btn-primary btn-small" onClick={() => setDeciding({ r, how: "approve" })}>
                    Approve
                  </button>
                  <button className="btn btn-small" onClick={() => setDeciding({ r, how: "reject" })}>
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {deciding && <Decide {...deciding} onClose={() => setDeciding(null)} onDone={() => (setDeciding(null), void load())} />}
    </>
  );
}

function Decide({ r, how, onClose, onDone }: { r: AreaReq; how: "approve" | "reject"; onClose: () => void; onDone: () => void }) {
  const [nodes, setNodes] = useState<NodeOpt[]>([]);
  const [node, setNode] = useState(r.parent_node_id ? String(r.parent_node_id) : "");
  const [note, setNote] = useState("");
  const [kind, setKind] = useState("other");
  const [error, setError] = useState("");
  useEffect(() => {
    void api<NodeOpt[]>(`/api/sites/${r.site_id}/nodes`).then(setNodes);
  }, [r.site_id]);
  async function go() {
    try {
      if (how === "approve") await api(`/api/sitecontrol/new-areas/${r.id}/approve`, { method: "POST", json: { parent_node_id: node ? Number(node) : null, kind } });
      else await api(`/api/sitecontrol/new-areas/${r.id}/reject`, { method: "POST", json: { move_to_node_id: Number(node), note: note || null } });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <Modal title={`${how === "approve" ? "Approve" : "Reject"}: ${r.name}`} onClose={onClose}>
      <label className="field">
        <span>{how === "approve" ? "Add it under" : "Move the booked work to"}</span>
        <select value={node} onChange={(e) => setNode(e.target.value)}>
          <option value="">{how === "approve" ? "the site (top level)" : "Choose a place…"}</option>
          {nodes.map((x) => (
            <option key={x.id} value={x.id}>
              {x.path}
            </option>
          ))}
        </select>
      </label>
      {how === "approve" ? (
        <label className="field">
          <span>Kind of place</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {[
              "other",
              "terrace",
              "toilet",
              "kitchen",
              "balcony",
              "podium",
              "lift_pit",
              "ug_tank",
              "oh_tank",
              "retaining_wall",
              "raft",
              "stp",
              "swimming_pool",
              "flat",
              "floor",
            ].map((k) => (
              <option key={k} value={k}>
                {k.replace("_", " ")}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <label className="field">
          <span>Why</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      )}
      {error && <div className="alert alert-error">{error}</div>}
      <div className="form-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={how === "reject" && !node} onClick={() => void go()}>
          {how === "approve" ? "Approve" : "Reject and move"}
        </button>
      </div>
    </Modal>
  );
}

/** From the phone: ask for a new area (name, area type, approximate size, a photo). */
export function NewAreaForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [types, setTypes] = useState<{ id: number; name: string }[]>([]);
  const [nodes, setNodes] = useState<NodeOpt[]>([]);
  const [f, setF] = useState({ name: "", area_type_id: "", approx_sqm: "", parent_node_id: "", note: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ id: number; name: string }[]>("/api/surveys/area-types").then(setTypes, () => setTypes([]));
    void api<NodeOpt[]>(`/api/sites/${id}/nodes`).then(setNodes, () => setNodes([]));
  }, [id]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!photo) return setError("Take a photo of the place");
    setBusy(true);
    const form = new FormData();
    form.append("site_id", String(id));
    Object.entries(f).forEach(([k, v]) => v && form.append(k, v));
    form.append("photo", photo);
    try {
      await api("/api/sitecontrol/new-areas", { method: "POST", form });
      navigate(`/sites/${id}/fronts?asked=1`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  return (
    <form className="phone-form" onSubmit={(e) => void submit(e)}>
      <div className="breadcrumb">
        <Link to={`/sites/${id}/fronts`}>Work fronts</Link> / New area
      </div>
      <h1>New area</h1>
      <p className="muted small">A place not on the site's list. Planning approves it; you can book work and material on it meanwhile.</p>
      <label className="field">
        <span>Name</span>
        <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
      </label>
      <label className="field">
        <span>Area type</span>
        <select value={f.area_type_id} onChange={(e) => setF({ ...f, area_type_id: e.target.value })}>
          <option value="">—</option>
          {types.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Approximate size (sqm)</span>
        <input inputMode="decimal" value={f.approx_sqm} onChange={(e) => setF({ ...f, approx_sqm: e.target.value })} />
      </label>
      <label className="field">
        <span>Where (under)</span>
        <select value={f.parent_node_id} onChange={(e) => setF({ ...f, parent_node_id: e.target.value })}>
          <option value="">the site</option>
          {nodes.map((x) => (
            <option key={x.id} value={x.id}>
              {x.path}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Photo</span>
        <input type="file" accept="image/*" capture="environment" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>Note</span>
        <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      </label>
      {error && <div className="alert alert-error">{error}</div>}
      <button className="btn btn-primary big-btn" disabled={busy}>
        Send to planning
      </button>
    </form>
  );
}

// --- labour productivity -------------------------------------------------------------------------

type ProdRow = { site: string; contractor: string | null; month: string; mandays: string; sqm: string; actual: string | null; expected: string | null; status: string };

export function Productivity() {
  const { can } = useAuth();
  const [rows, setRows] = useState<ProdRow[] | null>(null);
  const [norms, setNorms] = useState<{ system_id: number; system: string; sqm_per_manday: string | null }[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<ProdRow[]>("/api/sitecontrol/reports/productivity").then(setRows, (e) => setError(errorText(e)));
    void api<typeof norms>("/api/sitecontrol/productivity-norms").then(setNorms);
  }, []);
  useEffect(load, [load]);
  async function setNorm(systemId: number, v: string) {
    try {
      await api("/api/sitecontrol/productivity-norms", { method: "PUT", json: { system_id: systemId, sqm_per_manday: v || null } });
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <>
      <div className="page-header">
        <h1>Labour productivity</h1>
        <div className="page-actions">
          <button className="btn btn-small" onClick={() => void downloadFile("/api/sitecontrol/reports/productivity?format=xlsx")}>
            ⤓ Excel
          </button>
        </div>
      </div>
      <p className="muted small">
        Man-days from attendance against the sqm the contractor's work measured, per site and month. A subcontractor bill more than 20 % below the expected sqm per man-day is
        flagged and needs an override with a note.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Site</th>
              <th>Contractor</th>
              <th>Month</th>
              <th className="num">Man-days</th>
              <th className="num">Sqm done</th>
              <th className="num">Sqm / man-day</th>
              <th className="num">Expected</th>
              <th>Check</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r, i) => (
              <tr key={i} className={r.status === "low" ? "row-overdue" : undefined}>
                <td>{r.site}</td>
                <td>{r.contractor}</td>
                <td>{r.month}</td>
                <td className="num">{n(r.mandays, 1)}</td>
                <td className="num">{n(r.sqm)}</td>
                <td className="num">{n(r.actual)}</td>
                <td className="num">{r.expected ? n(r.expected) : <span className="muted">to be set</span>}</td>
                <td>
                  <span className={`badge ${r.status === "low" ? "badge-danger" : r.status === "ok" ? "badge-ok" : "badge-muted"}`}>
                    {r.status === "low" ? "productivity low" : r.status.replace("_", " ")}
                  </span>
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No measured work yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h2 className="section-title top-gap">Expected sqm per man-day</h2>
      <div className="card norms">
        {norms.map((x) => (
          <div key={x.system_id} className="inline-form">
            <span className="grow">{x.system}</span>
            <input
              className="norm-input"
              defaultValue={x.sqm_per_manday ?? ""}
              placeholder="to be set"
              inputMode="decimal"
              disabled={!can("settings.company")}
              onBlur={(e) => e.target.value !== (x.sqm_per_manday ?? "") && void setNorm(x.system_id, e.target.value)}
            />
          </div>
        ))}
      </div>
    </>
  );
}

// --- consumption variance ------------------------------------------------------------------------

type ConsRow = {
  node: string | null;
  product: string;
  unit: string;
  sqm_done: string;
  issued: string;
  expected: string;
  actual_per_sqm: string | null;
  variance_percent: string | null;
  flag: boolean;
};
type Learned = { system_id: number; system: string | null; product: string; site_average: string; areas: number; master: string | null };

export function Consumption() {
  const [params, setParams] = useSearchParams();
  const sites = useSites();
  const site = params.get("site") ?? "";
  const [data, setData] = useState<{ site: string; tolerance_percent: string; rows: ConsRow[] } | null>(null);
  const [learned, setLearned] = useState<Learned[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!site) return;
    api<typeof data>(`/api/sitecontrol/reports/consumption?site_id=${site}`).then(setData, (e) => setError(errorText(e)));
  }, [site]);
  useEffect(() => {
    void api<Learned[]>("/api/sitecontrol/learned").then(setLearned, () => setLearned([]));
  }, []);
  useEffect(() => {
    if (!site && sites.length) setParams({ site: String(sites[0].id) }, { replace: true });
  }, [site, sites, setParams]);
  return (
    <>
      <div className="page-header">
        <h1>Consumption variance</h1>
        <div className="page-actions">
          <select value={site} onChange={(e) => setParams({ site: e.target.value })} aria-label="Site">
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
              </option>
            ))}
          </select>
          {site && (
            <button className="btn btn-small" onClick={() => void downloadFile(`/api/sitecontrol/reports/consumption?site_id=${site}&format=xlsx`)}>
              ⤓ Excel
            </button>
          )}
        </div>
      </div>
      <p className="muted small">
        Material issued to each place against the treated area done × the system's consumption per sqm (with its wastage). Outside ±{data ? n(data.tolerance_percent, 0) : 15} % is
        flagged; planning gets a weekly alert.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Place</th>
              <th>Product</th>
              <th className="num">Sqm done</th>
              <th className="num">Issued</th>
              <th className="num">Expected</th>
              <th className="num">Per sqm</th>
              <th className="num">Variance</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((r, i) => (
              <tr key={i} className={r.flag ? "row-overdue" : undefined}>
                <td>{r.node}</td>
                <td>{r.product}</td>
                <td className="num">{n(r.sqm_done)}</td>
                <td className="num">
                  {n(r.issued, 3)} {r.unit}
                </td>
                <td className="num">
                  {n(r.expected, 3)} {r.unit}
                </td>
                <td className="num">{n(r.actual_per_sqm, 4)}</td>
                <td className={`num ${r.flag ? "text-danger" : ""}`}>
                  {r.variance_percent !== null ? `${Number(r.variance_percent) > 0 ? "+" : ""}${n(r.variance_percent, 1)} %` : "not in the system"}
                  {r.flag && " ⚑"}
                </td>
              </tr>
            ))}
            {data && data.rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No treated area with a system on this site yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <h2 className="section-title top-gap">Site average (completed areas)</h2>
      <p className="muted small">The median actual consumption per sqm over completed areas, next to the system's figure. It never changes the system by itself.</p>
      <div className="table-wrap card">
        <table className="table compact">
          <thead>
            <tr>
              <th>System</th>
              <th>Product</th>
              <th className="num">System figure</th>
              <th className="num">Site average</th>
              <th className="num">Areas</th>
            </tr>
          </thead>
          <tbody>
            {learned.map((l, i) => (
              <tr key={i}>
                <td>{l.system ?? `#${l.system_id}`}</td>
                <td>{l.product}</td>
                <td className="num">{n(l.master, 4)}</td>
                <td className="num">{n(l.site_average, 4)}</td>
                <td className="num">{l.areas}</td>
              </tr>
            ))}
            {learned.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No completed area with material issued yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- settings ------------------------------------------------------------------------------------

type ScSettings = {
  receipt_link_days: number;
  escalate_first_hours: number;
  escalate_second_hours: number;
  planning_user_id: string | null;
  bill_alert_days: number;
  contract_expiry_days: number;
  productivity_drop_percent: string;
  consumption_tolerance_percent: string;
};

export function SiteControlSettings() {
  const [s, setS] = useState<ScSettings | null>(null);
  const [users, setUsers] = useState<{ id: string; full_name: string }[]>([]);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    void api<ScSettings>("/api/sitecontrol/settings").then(setS);
    void api<{ items: { id: string; full_name: string }[] } | { id: string; full_name: string }[]>("/api/users?limit=200").then(
      (r) => setUsers(Array.isArray(r) ? r : r.items),
      () => setUsers([]),
    );
  }, []);
  if (!s) return <p className="muted">Loading…</p>;
  const field = (k: keyof ScSettings, label: string) => (
    <label className="field">
      <span>{label}</span>
      <input inputMode="decimal" value={String(s[k] ?? "")} onChange={(e) => setS({ ...s, [k]: e.target.value })} />
    </label>
  );
  return (
    <>
      <div className="page-header">
        <h1>Site control</h1>
      </div>
      {msg && <div className="alert alert-ok">{msg}</div>}
      <div className="card settings-card">
        <div className="form-grid two">
          {field("escalate_first_hours", "Delivery not confirmed: alert the site in-charge after (hours)")}
          {field("escalate_second_hours", "Then alert planning after (hours)")}
          <label className="field">
            <span>Planning (who gets the second alert)</span>
            <select value={s.planning_user_id ?? ""} onChange={(e) => setS({ ...s, planning_user_id: e.target.value || null })}>
              <option value="">The office admins</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
          </label>
          {field("receipt_link_days", "Receipt link works for (days)")}
          {field("bill_alert_days", "Work done, not billed: alert after (days)")}
          {field("contract_expiry_days", "Rate contract ending: alert purchase (days before)")}
          {field("productivity_drop_percent", "Labour check: flag below expected by (%)")}
          {field("consumption_tolerance_percent", "Consumption variance: flag outside ± (%)")}
        </div>
        <button
          className="btn btn-primary"
          onClick={() =>
            void api<ScSettings>("/api/sitecontrol/settings", { method: "PUT", json: s }).then(
              (r) => (setS(r), setMsg("Saved.")),
              (e) => setMsg(errorText(e)),
            )
          }
        >
          Save
        </button>
      </div>
    </>
  );
}

// --- on the site page ----------------------------------------------------------------------------

type Flags = { pending_new_areas: number; consumption_flags: number; deliveries_unconfirmed: number; receiver_name: string | null; receiver_phone: string | null };

/** The site's open site-control items, the "New area" button and its named receiver. */
export function SiteControlStrip({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const [f, setF] = useState<Flags | null>(null);
  const [edit, setEdit] = useState(false);
  const [r, setR] = useState({ receiver_name: "", receiver_phone: "" });
  const load = useCallback(() => api<Flags>(`/api/sitecontrol/sites/${siteId}/flags`).then(setF, () => setF(null)), [siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!f) return null;
  return (
    <div className="sc-strip">
      {f.deliveries_unconfirmed > 0 && (
        <Link className="badge badge-warn" to={`/deliveries?site=${siteId}&state=unconfirmed`}>
          {f.deliveries_unconfirmed} delivery not confirmed
        </Link>
      )}
      {f.pending_new_areas > 0 && (
        <Link className="badge badge-info" to="/new-areas">
          {f.pending_new_areas} new area waiting
        </Link>
      )}
      {f.consumption_flags > 0 && (
        <Link className="badge badge-danger" to={`/consumption?site=${siteId}`}>
          {f.consumption_flags} consumption off the system
        </Link>
      )}
      <Link className="btn btn-small btn-ghost" to={`/sites/${siteId}/new-area`}>
        + New area
      </Link>
      <span className="small muted">
        Receiver when the supervisor is away: <b>{f.receiver_name ?? "none named"}</b> {f.receiver_phone ?? ""}
      </span>
      {can("site.edit") && (
        <button className="btn btn-small btn-ghost" onClick={() => (setR({ receiver_name: f.receiver_name ?? "", receiver_phone: f.receiver_phone ?? "" }), setEdit(true))}>
          Change
        </button>
      )}
      {edit && (
        <Modal title="Named receiver" onClose={() => setEdit(false)}>
          <p className="small muted">Who may confirm deliveries when the supervisor is away (labour leader, applicator). Anyone else who confirms is flagged for review.</p>
          <div className="form-grid two">
            <label className="field">
              <span>Name</span>
              <input value={r.receiver_name} onChange={(e) => setR({ ...r, receiver_name: e.target.value })} />
            </label>
            <label className="field">
              <span>Phone</span>
              <input value={r.receiver_phone} onChange={(e) => setR({ ...r, receiver_phone: e.target.value })} />
            </label>
          </div>
          <div className="form-actions">
            <button
              className="btn btn-primary"
              onClick={() => void api(`/api/sitecontrol/sites/${siteId}/receiver`, { method: "PUT", json: r }).then(() => (setEdit(false), void load()))}
            >
              Save
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
