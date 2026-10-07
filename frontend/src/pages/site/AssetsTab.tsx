import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import Modal from "../../components/Modal";
import { errorText, inr, num } from "../../format";
import type { AssetOut, Usage } from "../../execution/types";
import type { MaterialLookups } from "../../material/types";
import type { Site } from "../../types";
import { useMaterialLookups } from "../material/common";
import { shortDate } from "../Tenders";
import { localToday } from "./DprTab";

const STATUS_BADGE: Record<string, string> = { available: "badge-ok", at_site: "badge-info", repair: "badge-warn", lost: "badge-danger", disposed: "badge-muted" };

export function AssetTable({ assets, onMove, onUsage }: { assets: AssetOut[]; onMove?: (a: AssetOut) => void; onUsage?: (a: AssetOut) => void }) {
  return (
    <div className="card table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>Code</th>
            <th>Asset</th>
            <th>Where</th>
            <th>Status</th>
            <th className="num">Rate</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.id}>
              <td>
                <code>{a.code}</code>
              </td>
              <td>
                {a.name}{" "}
                <span className="muted small">{[a.category, a.make, a.model, a.ownership === "hired" ? `hired from ${a.vendor_name}` : ""].filter(Boolean).join(" · ")}</span>
              </td>
              <td>
                {a.location}
                {a.days_here !== null && <span className={`small ${a.overdue ? "text-danger" : "muted"}`}> · {a.days_here} d</span>}
              </td>
              <td>
                <span className={`badge ${STATUS_BADGE[a.status]}`}>{a.status.replace("_", " ")}</span>
              </td>
              <td className="num small">
                {a.rate_per_day && `${inr(a.rate_per_day)}/day`} {a.rate_per_hour && `${inr(a.rate_per_hour)}/h`}
              </td>
              <td className="nowrap">
                {onMove && (
                  <button className="btn btn-small" onClick={() => onMove(a)}>
                    Move
                  </button>
                )}
                {onUsage && a.site_id && a.category !== "tool" && (
                  <button className="btn btn-small" onClick={() => onUsage(a)}>
                    Log use
                  </button>
                )}
              </td>
            </tr>
          ))}
          {assets.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                No assets here.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Issue to a site or return to a store, with an optional photo (multipart). */
export function MoveForm({
  asset,
  lookups,
  toSiteId,
  onClose,
  onSaved,
}: {
  asset: AssetOut;
  lookups: MaterialLookups;
  toSiteId?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [target, setTarget] = useState(asset.site_id ? `store:${lookups.stores.find((s) => s.kind === "godown")?.id ?? ""}` : toSiteId ? `site:${toSiteId}` : "");
  const [form, setForm] = useState({ on_date: localToday(), condition: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const [kind, id] = target.split(":");
    const body = new FormData();
    body.append(kind === "site" ? "to_site_id" : "to_store_id", id);
    body.append("on_date", form.on_date);
    if (form.condition) body.append("condition", form.condition);
    if (photo) body.append("photo", photo);
    try {
      await api(`/api/execution/assets/${asset.id}/move`, { method: "POST", form: body });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Modal title={`Move ${asset.code} ${asset.name}`} onClose={onClose}>
      <form onSubmit={submit} className="daily">
        {error && <div className="alert alert-error">{error}</div>}
        <p className="small muted">Now: {asset.location}</p>
        <label className="field">
          <span>To *</span>
          <select required className="tap-input" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">—</option>
            <optgroup label="Return to a store">
              {lookups.stores
                .filter((s) => s.kind === "godown")
                .map((s) => (
                  <option key={s.id} value={`store:${s.id}`}>
                    {s.name}
                  </option>
                ))}
            </optgroup>
            <optgroup label="Issue to a site">
              {lookups.sites.map((s) => (
                <option key={s.id} value={`site:${s.id}`}>
                  {s.code} {s.name}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label className="field">
          <span>Date</span>
          <input type="date" className="tap-input" value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} />
        </label>
        <label className="field">
          <span>Condition</span>
          <input className="tap-input" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })} placeholder="Good / needs service…" />
        </label>
        <label className={`btn tap-wide ${photo ? "btn-primary" : ""}`}>
          📷 {photo ? photo.name : "Photo"}
          <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </label>
        <div className="daily-actions">
          <button type="button" className="btn tap-wide" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary tap-wide">Move</button>
        </div>
      </form>
    </Modal>
  );
}

export function UsageForm({ asset, onClose, onSaved }: { asset: AssetOut; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    on_date: localToday(),
    basis: asset.rate_per_day ? "day" : "hour",
    quantity: "1",
    rate: "",
    fuel_litres: "",
    fuel_cost: "",
    operator: "",
  });
  const [error, setError] = useState<string | null>(null);
  const rate = Number(form.rate || (form.basis === "day" ? asset.rate_per_day : asset.rate_per_hour) || 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/api/execution/equipment-usage", {
        method: "POST",
        json: {
          asset_id: asset.id,
          site_id: asset.site_id,
          ...form,
          rate: form.rate || null,
          fuel_litres: form.fuel_litres || "0",
          fuel_cost: form.fuel_cost || "0",
          operator: form.operator || null,
        },
      });
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title={`Use of ${asset.code} ${asset.name}`} onClose={onClose}>
      <form onSubmit={submit} className="daily">
        {error && <div className="alert alert-error">{error}</div>}
        <div className="grid-2">
          <label className="field">
            <span>Date</span>
            <input type="date" className="tap-input" value={form.on_date} onChange={set("on_date")} />
          </label>
          <div className="field">
            <span>By</span>
            <div className="tap-group">
              {(["day", "hour"] as const).map((b) => (
                <button key={b} type="button" className={`tap ${form.basis === b ? "on" : ""}`} onClick={() => setForm({ ...form, basis: b })}>
                  {b === "day" ? "Days" : "Hours"}
                </button>
              ))}
            </div>
          </div>
          <label className="field">
            <span>{form.basis === "day" ? "Days" : "Hours"} *</span>
            <input required className="tap-input" inputMode="decimal" value={form.quantity} onChange={set("quantity")} />
          </label>
          <label className="field">
            <span>Rate (blank: {inr(form.basis === "day" ? asset.rate_per_day : asset.rate_per_hour)})</span>
            <input className="tap-input" inputMode="decimal" value={form.rate} onChange={set("rate")} />
          </label>
          <label className="field">
            <span>Fuel (litres)</span>
            <input className="tap-input" inputMode="decimal" value={form.fuel_litres} onChange={set("fuel_litres")} />
          </label>
          <label className="field">
            <span>Fuel cost (₹)</span>
            <input className="tap-input" inputMode="decimal" value={form.fuel_cost} onChange={set("fuel_cost")} />
          </label>
          <label className="field">
            <span>Operator</span>
            <input className="tap-input" value={form.operator} onChange={set("operator")} />
          </label>
        </div>
        <p className="right">
          Cost <b>{inr(Number(form.quantity || 0) * rate + Number(form.fuel_cost || 0))}</b>
        </p>
        <div className="daily-actions">
          <button type="button" className="btn tap-wide" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary tap-wide">Save</button>
        </div>
      </form>
    </Modal>
  );
}

export function UsageTable({ rows, showSite }: { rows: Usage[]; showSite?: boolean }) {
  return (
    <div className="card table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>Date</th>
            {showSite && <th>Site</th>}
            <th>Asset</th>
            <th className="num">Used</th>
            <th className="num">Fuel</th>
            <th>Operator</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id}>
              <td className="nowrap">{shortDate(u.on_date)}</td>
              {showSite && <td>{u.site_code}</td>}
              <td>{u.asset}</td>
              <td className="num">
                {num(u.quantity)} {u.basis}(s) × {inr(u.rate)}
              </td>
              <td className="num">{Number(u.fuel_litres) ? `${num(u.fuel_litres)} L ${inr(u.fuel_cost)}` : "—"}</td>
              <td>{u.operator ?? ""}</td>
              <td className="num">{inr(u.amount)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={showSite ? 7 : 6} className="empty">
                No equipment use logged.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function AssetsTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const lookups = useMaterialLookups();
  const [assets, setAssets] = useState<AssetOut[]>([]);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [moving, setMoving] = useState<AssetOut | null>(null);
  const [logging, setLogging] = useState<AssetOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const edit = can("asset.edit");

  const load = useCallback(async () => {
    try {
      setAssets(await api<AssetOut[]>(`/api/execution/assets?site_id=${site.id}`));
      setUsage(await api<Usage[]>(`/api/execution/equipment-usage?site_id=${site.id}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const done = async () => {
    setMoving(null);
    setLogging(null);
    await load();
  };
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      <h2 className="section-title">At this site</h2>
      <AssetTable assets={assets} onMove={edit ? setMoving : undefined} onUsage={edit ? setLogging : undefined} />
      <h2 className="section-title top-gap">Equipment use (last 90 days) · {inr(usage.reduce((s, u) => s + Number(u.amount), 0))}</h2>
      <UsageTable rows={usage} />
      {moving && lookups && <MoveForm asset={moving} lookups={lookups} onClose={() => setMoving(null)} onSaved={() => void done()} />}
      {logging && <UsageForm asset={logging} onClose={() => setLogging(null)} onSaved={() => void done()} />}
    </>
  );
}
