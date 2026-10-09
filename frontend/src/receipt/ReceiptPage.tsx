// The delivery receipt page: opened from the QR code / short link on the delivery note, with no
// login. Count each item (counts start empty, never the sent quantity), note damage, take two
// photos, give your name; submitted once. Light on purpose: a cheap phone on a slow connection.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { S } from "./strings";
import type { Key } from "./strings";

type Item = { line_id: number; product: string; qty: string; unit: string; packs: string | null; pack_unit: string | null };
type View = {
  code: string;
  site: string;
  expected_at: string;
  vehicle_no: string | null;
  receiver_named: string | null;
  status: string;
  confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  items: Item[];
};
type Count = { received: string; damaged: string };

function L({ k, strong }: { k: Key; strong?: boolean }) {
  const [en, gu, hi] = S[k];
  return (
    <span className="tri">
      {strong ? <b>{en}</b> : en}
      <span className="tri-sub">
        {gu} · {hi}
      </span>
    </span>
  );
}

function num(v: string): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function trim(v: string | null): string {
  if (v === null) return "";
  return String(Number(v));
}

/** + / − with a large number box; empty until someone counts. */
function Counter({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const step = (d: number) => onChange(String(Math.max(0, num(value) + d)));
  return (
    <div className="counter" role="group" aria-label={label}>
      <button type="button" onClick={() => step(-1)} aria-label={`${label} minus`}>
        −
      </button>
      <input inputMode="decimal" value={value} placeholder="?" onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))} aria-label={label} />
      <button type="button" onClick={() => step(1)} aria-label={`${label} plus`}>
        +
      </button>
    </div>
  );
}

function PhotoStep({ k, file, onFile }: { k: Key; file: File | null; onFile: (f: File) => void }) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  return (
    <label className={`photo-step ${file ? "has" : ""}`}>
      <L k={k} strong />
      {url ? <img src={url} alt="" /> : <span className="photo-icon">📷</span>}
      <span className="photo-btn">{file ? S.retake[0] : S.takePhoto[0]}</span>
      <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
    </label>
  );
}

export default function ReceiptPage() {
  const { token } = useParams();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [counts, setCounts] = useState<Record<number, Count>>({});
  const [goods, setGoods] = useState<File | null>(null);
  const [challan, setChallan] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [gps, setGps] = useState<GeolocationCoordinates | null>(null);
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState(false);
  const [justDone, setJustDone] = useState(false);
  useEffect(() => {
    fetch(`/api/receipt/${token}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject((await r.json().catch(() => ({}))).detail ?? r.statusText)))
      .then(setView, (e) => setError(String(e)));
    navigator.geolocation?.getCurrentPosition(
      (p) => setGps(p.coords),
      () => undefined,
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }, [token]);
  const set = (id: number, c: Partial<Count>) => setCounts((all) => ({ ...all, [id]: { ...(all[id] ?? { received: "", damaged: "" }), ...c } }));
  const complete = view?.items.every((i) => counts[i.line_id]?.received !== undefined && counts[i.line_id].received !== "") && goods && challan && name.trim();
  const short = view?.items.some((i) => counts[i.line_id]?.received !== undefined && counts[i.line_id].received !== "" && num(counts[i.line_id].received) < num(i.qty));
  async function submit() {
    if (!view || !complete) {
      setMissing(true);
      return;
    }
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("name", name.trim());
    if (phone.trim()) form.append("phone", phone.trim());
    form.append("lines", JSON.stringify(view.items.map((i) => ({ line_id: i.line_id, received: counts[i.line_id].received, damaged: counts[i.line_id].damaged || 0 }))));
    form.append("photo_goods", goods!);
    form.append("photo_challan", challan!);
    if (gps) {
      form.append("lat", String(gps.latitude.toFixed(6)));
      form.append("lng", String(gps.longitude.toFixed(6)));
      form.append("accuracy", String(Math.round(gps.accuracy)));
    }
    const r = await fetch(`/api/receipt/${token}`, { method: "POST", body: form }).catch(() => null);
    setBusy(false);
    if (!r) return setError("No connection: try again");
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return setError(String(body.detail ?? r.statusText));
    setJustDone(true);
    setView(body);
  }
  if (error && !view)
    return (
      <main className="receipt">
        <p className="receipt-error">{error}</p>
      </main>
    );
  if (!view)
    return (
      <main className="receipt">
        <p>…</p>
      </main>
    );
  return (
    <main className="receipt">
      <header>
        <L k="title" strong />
        <h1>{view.code}</h1>
        <p className="site">{view.site}</p>
        <p className="small">
          {S.expected[0]}: {new Date(view.expected_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
          {view.vehicle_no && ` · ${S.vehicle[0]}: ${view.vehicle_no}`}
        </p>
        {view.receiver_named && (
          <p className="small">
            {S.named[0]}: <b>{view.receiver_named}</b>
          </p>
        )}
      </header>
      {view.confirmed ? (
        <section className="receipt-done">
          <p className="big">✓</p>
          <p>
            {justDone ? <L k="done" strong /> : <L k="already" />} <b>{view.confirmed_by}</b>
          </p>
          <p className="small">{view.confirmed_at && new Date(view.confirmed_at).toLocaleString("en-IN")}</p>
        </section>
      ) : (
        <>
          <section>
            <h2>
              <L k="step1" strong />
            </h2>
            {view.items.map((i) => {
              const c = counts[i.line_id];
              return (
                <div key={i.line_id} className={`receipt-item ${c?.received ? "counted" : ""}`}>
                  <div className="item-name">{i.product}</div>
                  <div className="small">
                    {S.sent[0]}: {i.packs ? `${trim(i.packs)} ${i.pack_unit} = ` : ""}
                    {trim(i.qty)} {i.unit}
                  </div>
                  <div className="count-row">
                    <span className="count-label">
                      <L k="received" /> ({i.unit})
                    </span>
                    <Counter value={c?.received ?? ""} onChange={(v) => set(i.line_id, { received: v })} label={`${i.product} ${S.received[0]}`} />
                  </div>
                  <div className="count-row">
                    <span className="count-label">
                      <L k="damaged" />
                    </span>
                    <Counter value={c?.damaged ?? ""} onChange={(v) => set(i.line_id, { damaged: v })} label={`${i.product} ${S.damaged[0]}`} />
                  </div>
                  {!c?.received && <div className="small muted">{S.notCounted[0]}</div>}
                </div>
              );
            })}
            {short && <p className="receipt-warn">{S.short[0]}</p>}
          </section>
          <section>
            <h2>
              <L k="step2" strong />
            </h2>
            <div className="photo-steps">
              <PhotoStep k="photoGoods" file={goods} onFile={setGoods} />
              <PhotoStep k="photoChallan" file={challan} onFile={setChallan} />
            </div>
          </section>
          <section>
            <h2>
              <L k="step3" strong />
            </h2>
            <label className="receipt-field">
              <L k="name" />
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
            <label className="receipt-field">
              <L k="phone" />
              <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="tel" />
            </label>
            <p className="small muted">{S.location[0]}</p>
          </section>
          {missing && !complete && <p className="receipt-warn">{S.missing[0]}</p>}
          {error && <p className="receipt-error">{error}</p>}
          <button className="receipt-submit" disabled={busy} onClick={() => void submit()}>
            {busy ? S.sending[0] : <L k="confirm" strong />}
          </button>
        </>
      )}
    </main>
  );
}
