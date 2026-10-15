import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import { dist, Flags, km, locate, STOP_KINDS, time } from "./common";
import type { Day, Fix, MapSettings, MySite } from "./common";
import MapView from "./MapView";
import type { MapPin } from "./MapView";
import { browserStore, mapsLink, PointQueue, shouldKeep } from "./tracker";
import type { QueuedPoint } from "./tracker";

type Me = {
  consent: {
    version: string;
    given: boolean;
    given_at: string | null;
    asked_again: boolean;
    earlier_version: string | null;
    tracked: boolean;
    text: Record<"what" | "why" | "who" | "kept" | "where", string>;
  };
  profile: {
    tracked: boolean;
    reimbursable: boolean;
    vehicle: string | null;
    home_status: string;
    home: [number, number] | null;
    pending: [number, number] | null;
    manager: string | null;
  };
  settings: MapSettings;
  day: Day | null;
  sites: MySite[];
};

/** The tracker: runs only while the day is open and this page is open. */
function useTracker(active: boolean, userKey: string, settings: MapSettings | null) {
  const queue = useMemo(() => new PointQueue(browserStore, `field-points-${userKey}`), [userKey]);
  const [queued, setQueued] = useState(queue.all().length);
  const [lastSent, setLastSent] = useState<string | null>(null);
  const [lastFix, setLastFix] = useState<QueuedPoint | null>(null);
  const last = useRef<QueuedPoint | null>(null);

  const flush = useCallback(async () => {
    try {
      const n = await queue.flush(async (batch, id) => {
        await api("/api/field/points", { method: "POST", json: { source: "web", batch: id, points: batch } });
      });
      if (n) setLastSent(new Date().toISOString());
    } catch {
      // offline: the points stay queued and go when the browser is back online
    }
    setQueued(queue.all().length);
  }, [queue]);

  useEffect(() => {
    if (!active || !settings || !navigator.geolocation) return;
    const take = (p: GeolocationPosition) => {
      const point: QueuedPoint = { at: new Date(p.timestamp).toISOString(), lat: p.coords.latitude, lng: p.coords.longitude, accuracy: Math.round(p.coords.accuracy) };
      setLastFix(point);
      if (!shouldKeep(last.current, point, settings.point_every_s, settings.point_move_m)) return;
      last.current = point;
      queue.add(point);
      setQueued(queue.all().length);
    };
    const watch = navigator.geolocation.watchPosition(take, () => undefined, { enableHighAccuracy: true, maximumAge: 15000, timeout: 60000 });
    // a reading every 2 minutes even when standing still
    const tick = window.setInterval(
      () => navigator.geolocation.getCurrentPosition(take, () => undefined, { enableHighAccuracy: true, maximumAge: 0, timeout: 60000 }),
      settings.point_every_s * 1000,
    );
    const send = window.setInterval(() => void flush(), 60000);
    const online = () => void flush();
    window.addEventListener("online", online);
    return () => {
      navigator.geolocation.clearWatch(watch);
      window.clearInterval(tick);
      window.clearInterval(send);
      window.removeEventListener("online", online);
    };
  }, [active, settings, queue, flush]);

  return { queued, lastSent, lastFix, flush };
}

function ConsentScreen({ me, onDone }: { me: Me; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = me.consent.text;
  return (
    <div className="card consent-card">
      <h2>Location tracking: your consent</h2>
      {me.consent.asked_again && (
        <p className="alert alert-warn">
          What we record has changed since you agreed (version {me.consent.earlier_version}): please read it again. Version {me.consent.version}.
        </p>
      )}
      <p className="muted small">Under India&apos;s Digital Personal Data Protection Act, 2023, we record your location only with your consent.</p>
      <dl className="consent-list">
        <dt>What is recorded</dt>
        <dd>{t.what}</dd>
        <dt>Why</dt>
        <dd>{t.why}</dd>
        <dt>Who sees it</dt>
        <dd>{t.who}</dd>
        <dt>How long it is kept</dt>
        <dd>{t.kept}</dd>
        <dt>Where it is kept</dt>
        <dd>{t.where}</dd>
      </dl>
      <p className="small">Without consent you can still use the app; nothing is tracked and no travel claim is made. You can withdraw it at any time from this page.</p>
      {error && <div className="alert alert-error">{error}</div>}
      <button
        className="btn btn-primary btn-block tap"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api("/api/field/consent", { method: "POST" });
            onDone();
          } catch (e) {
            setError(errorText(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        I agree (version {me.consent.version})
      </button>
    </div>
  );
}

function CheckIn({ me, fix, onDone, onError }: { me: Me; fix: Fix | null; onDone: () => void; onError: (e: string) => void }) {
  const [kind, setKind] = useState("site");
  const [siteId, setSiteId] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState<string | null>(null);
  const [selfie, setSelfie] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const sites = useMemo(() => {
    const list = me.sites.map((s) => ({ ...s, away: fix && s.lat !== null && s.lng !== null ? distance(fix, s.lat, s.lng) : null }));
    return list.sort((a, b) => (a.away ?? 1e12) - (b.away ?? 1e12));
  }, [me.sites, fix]);
  async function go() {
    setBusy(true);
    try {
      const at = await locate();
      const form = new FormData();
      form.append("kind", kind);
      form.append("lat", String(at.lat));
      form.append("lng", String(at.lng));
      form.append("accuracy", String(at.accuracy));
      if (kind === "site") form.append("site_id", siteId);
      if (note.trim()) form.append("note", note.trim());
      if (reason.trim()) form.append("reason", reason.trim());
      if (selfie) form.append("selfie", selfie);
      await api("/api/field/stops/in", { method: "POST", form });
      setNeedReason(null);
      setReason("");
      setSelfie(null);
      onDone();
    } catch (e) {
      const text = errorText(e);
      if (text.includes("give the reason")) setNeedReason(text);
      else onError(text);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <h3>Check in</h3>
      <div className="chip-list">
        {STOP_KINDS.map(([k, label]) => (
          <button key={k} className={`chip ${kind === k ? "chip-on" : ""}`} onClick={() => setKind(k)}>
            {label}
          </button>
        ))}
      </div>
      {kind === "site" ? (
        <label className="field">
          <span>Site</span>
          <select className="tap-input" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">— choose the site —</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.away !== null ? ` · ${dist(s.away)}` : s.lat === null ? " · no pin" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <label className="field">
          <span>Where{kind === "other" ? " (required)" : ""}</span>
          <input className="tap-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Vendor, godown or office name" />
        </label>
      )}
      {kind === "site" && (
        <label className="btn btn-block tap selfie-btn">
          {selfie ? "Selfie taken: retake" : "Take the selfie (front camera)"}
          <input type="file" accept="image/*" capture="user" hidden onChange={(e) => setSelfie(e.target.files?.[0] ?? null)} />
        </label>
      )}
      {needReason && (
        <div className="alert alert-warn">
          {needReason}
          <textarea className="tap-input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why are you outside the site circle?" />
        </div>
      )}
      <button
        className="btn btn-primary btn-block tap"
        disabled={busy || (kind === "site" && (!siteId || !selfie)) || (kind === "other" && !note.trim()) || (!!needReason && !reason.trim())}
        onClick={() => void go()}
      >
        {busy ? "Getting your location…" : "Check in here"}
      </button>
    </div>
  );
}

function distance(a: Fix, lat: number, lng: number): number {
  const r = Math.PI / 180;
  const x = (lng - a.lng) * r * Math.cos(((lat + a.lat) / 2) * r);
  const y = (lat - a.lat) * r;
  return Math.sqrt(x * x + y * y) * 6371008.8;
}

type Plan = {
  sites: MySite[];
  suggested: boolean;
  road: [number, number][] | null;
  legs: { from: string; to: string; km: number; minutes: number | null; estimated: boolean }[];
  km: number;
  minutes: number;
  home: [number, number] | null;
  missing_location: string[];
};

export function TodaysRoute({ me }: { me: Me }) {
  const pinned = me.sites.filter((s) => s.lat !== null);
  const [chosen, setChosen] = useState<number[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function make(order: number[], keep: boolean) {
    setError(null);
    try {
      const p = await api<Plan>("/api/field/plan", { method: "POST", json: { site_ids: order, keep_order: keep } });
      setPlan(p);
      setChosen(p.sites.map((s) => s.id));
    } catch (e) {
      setError(errorText(e));
    }
  }
  function move(i: number, by: number) {
    const next = [...chosen];
    const [x] = next.splice(i, 1);
    next.splice(i + by, 0, x);
    void make(next, true);
  }
  const pins: MapPin[] = plan
    ? [
        ...(plan.home ? [{ lat: plan.home[0], lng: plan.home[1], label: "⌂", kind: "home" as const, title: "Home" }] : []),
        ...plan.sites.map((s, i) => ({ lat: s.lat!, lng: s.lng!, label: String(i + 1), kind: "site" as const, title: s.name })),
      ]
    : [];
  return (
    <div className="card">
      <h3>Today&apos;s route</h3>
      <p className="small muted">Pick today&apos;s sites: the order is suggested by the shortest road route from home through them; move them to change it.</p>
      <div className="chip-list">
        {pinned.map((s) => (
          <label key={s.id} className="chip">
            <input type="checkbox" checked={chosen.includes(s.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, s.id] : chosen.filter((x) => x !== s.id))} /> {s.name}
          </label>
        ))}
      </div>
      <button className="btn btn-small tap" disabled={!chosen.length} onClick={() => void make(chosen, false)}>
        Suggest the order
      </button>
      {error && <div className="alert alert-error">{error}</div>}
      {plan && (
        <>
          <ol className="route-list">
            {plan.sites.map((s, i) => (
              <li key={s.id}>
                <b>{s.name}</b> <span className="small muted">{plan.legs[i] ? `${km(plan.legs[i].km)} · ${plan.legs[i].minutes ?? "?"} min` : ""}</span>
                <span className="route-actions">
                  <button className="btn btn-small btn-ghost" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Earlier">
                    ↑
                  </button>
                  <button className="btn btn-small btn-ghost" disabled={i === plan.sites.length - 1} onClick={() => move(i, 1)} aria-label="Later">
                    ↓
                  </button>
                  <a className="btn btn-small btn-primary" href={mapsLink(s.lat!, s.lng!)} target="_blank" rel="noreferrer">
                    Go to site
                  </a>
                </span>
              </li>
            ))}
          </ol>
          <p className="small">
            {plan.suggested ? "Suggested order" : "Your order"}: {km(plan.km)} by road, about {plan.minutes} min driving, back home included.
          </p>
          <MapView tileUrl={me.settings.tile_url} attribution={me.settings.tile_attribution} pins={pins} lines={plan.road ? [{ points: plan.road }] : []} height={300} />
        </>
      )}
    </div>
  );
}

function HomeSetter({ me, onDone }: { me: Me; onDone: () => void }) {
  const [picked, setPicked] = useState<[number, number] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const p = me.profile;
  return (
    <details className="card">
      <summary>
        Home location:{" "}
        <b>
          {p.home_status === "approved"
            ? "approved"
            : p.home_status === "pending"
              ? "waiting for the office admin"
              : p.home_status === "rejected"
                ? "not approved, pick again"
                : "not set"}
        </b>
        {p.pending && p.home_status === "approved" ? " (a change is waiting for approval)" : ""}
      </summary>
      <p className="small muted">Your day should start and end at home; the office admin approves the place (a change needs approval again).</p>
      <MapView
        tileUrl={me.settings.tile_url}
        attribution={me.settings.tile_attribution}
        pins={p.home ? [{ lat: p.home[0], lng: p.home[1], label: "⌂", kind: "home", title: "Approved home" }] : []}
        picked={picked ?? p.pending}
        onPick={(lat, lng) => setPicked([lat, lng])}
        height={240}
      />
      <div className="form-row">
        <button
          className="btn btn-small tap"
          onClick={() =>
            void locate().then(
              (f) => setPicked([f.lat, f.lng]),
              (e) => setMsg(errorText(e)),
            )
          }
        >
          Use my location
        </button>
        <button
          className="btn btn-small btn-primary tap"
          disabled={!picked}
          onClick={async () => {
            try {
              await api("/api/field/home", { method: "PUT", json: { lat: picked![0], lng: picked![1] } });
              setMsg("Sent for approval.");
              onDone();
            } catch (e) {
              setMsg(errorText(e));
            }
          }}
        >
          Ask for approval
        </button>
      </div>
      {msg && <p className="small">{msg}</p>}
    </details>
  );
}

export function MyDay() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fix, setFix] = useState<Fix | null>(null);
  const load = useCallback(() => api<Me>("/api/field/me").then(setMe, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  const open = !!me?.day && !me.day.ended_at && me.consent.given;
  const tracker = useTracker(open, me?.day?.user_id ?? "me", me?.settings ?? null);
  useEffect(() => {
    if (tracker.lastFix) setFix({ lat: tracker.lastFix.lat, lng: tracker.lastFix.lng, accuracy: tracker.lastFix.accuracy ?? 0 });
  }, [tracker.lastFix]);

  async function act(path: string, method = "POST") {
    setBusy(true);
    setError(null);
    try {
      const at = await locate();
      setFix(at);
      if (path === "/api/field/day/end") await tracker.flush();
      await api(path, { method, json: { lat: at.lat, lng: at.lng, accuracy: at.accuracy } });
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function checkOut(withSelfie: File | null, reason?: string) {
    setBusy(true);
    setError(null);
    try {
      const at = await locate();
      const form = new FormData();
      form.append("lat", String(at.lat));
      form.append("lng", String(at.lng));
      form.append("accuracy", String(at.accuracy));
      if (reason) form.append("reason", reason);
      if (withSelfie) form.append("selfie", withSelfie);
      await api("/api/field/stops/out", { method: "POST", form });
      await load();
    } catch (e) {
      const text = errorText(e);
      const why = text.includes("give the reason") ? window.prompt(`${text}\n\nThe reason:`) : null;
      if (why?.trim()) await checkOut(withSelfie, why.trim());
      else setError(text);
    } finally {
      setBusy(false);
    }
  }

  if (!me) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  if (!me.profile.tracked)
    return (
      <div className="field-phone">
        <h1>My day</h1>
        <p className="muted">You are not set up for field tracking. The office admin sets who is tracked (Settings › Field tracking).</p>
      </div>
    );
  if (!me.consent.given)
    return (
      <div className="field-phone">
        <h1>My day</h1>
        <ConsentScreen me={me} onDone={() => void load()} />
      </div>
    );
  const day = me.day;
  const current = day?.stops.find((s) => !s.out_at) ?? null;
  return (
    <div className="field-phone">
      <h1>My day</h1>
      {error && <div className="alert alert-error">{error}</div>}
      {!day && (
        <div className="card">
          <p>Start your day when you leave home. Your location is recorded from Start day to End day only (the day ends by itself at {me.settings.auto_end_at}).</p>
          <button className="btn btn-primary btn-block tap btn-big" disabled={busy} onClick={() => void act("/api/field/day/start")}>
            {busy ? "Getting your location…" : "Start day"}
          </button>
        </div>
      )}
      {day && (
        <div className="card">
          <div className="field-status">
            <b>{day.ended_at ? "Day ended" : "Day started"}</b> {time(day.started_at)}
            {day.ended_at && <> – {time(day.ended_at)}</>}
            {day.start_home_m !== null && <span className="small muted"> · started {dist(day.start_home_m)} from home</span>}
          </div>
          {!day.ended_at && (
            <p className="small muted">
              Recording while this page is open: {tracker.queued ? `${tracker.queued} point(s) waiting to be sent` : "all points sent"}
              {tracker.lastSent ? `, last sent ${time(tracker.lastSent)}` : ""}. With the screen off or the browser closed, the browser stops sending your location, so the route
              between stops can have gaps.
            </p>
          )}
          {current && (
            <div className="field-current">
              At <b>{current.name}</b> since {time(current.in_at)}
              {current.in_outside && <span className="text-danger small"> · {dist(current.in_distance_m)} from the pin</span>}
              <label className="btn btn-block tap">
                Check out (selfie)
                <input type="file" accept="image/*" capture="user" hidden onChange={(e) => void checkOut(e.target.files?.[0] ?? null)} />
              </label>
              <button className="btn btn-ghost btn-small" disabled={busy} onClick={() => void checkOut(null)}>
                Check out without a selfie
              </button>
            </div>
          )}
          {day.stops.length > 0 && (
            <ol className="stop-list">
              {day.stops.map((s) => (
                <li key={s.id}>
                  <b>{s.name}</b> {time(s.in_at)}–{s.out_at ? time(s.out_at) : "now"}
                  {s.minutes !== null && <span className="muted small"> · {s.minutes} min</span>}
                  {(s.in_outside || s.out_outside) && <span className="text-danger small"> · outside the circle</span>}
                </li>
              ))}
            </ol>
          )}
          {day.ended_at && (
            <>
              <p>
                Road km <b>{km(day.route_km)}</b>
                {day.route_estimated && " (estimated)"} · tracked km <b>{km(day.tracked_km)}</b> · the claim uses <b>{day.km_basis === "route" ? "road km" : "tracked km"}</b>
              </p>
              <Flags flags={day.flags} />
            </>
          )}
          <Link to={`/field/days/${day.id}`}>The day on the map</Link>
        </div>
      )}
      {day && !day.ended_at && !current && <CheckIn me={me} fix={fix} onDone={() => void load()} onError={setError} />}
      {day && !day.ended_at && !current && (
        <button className="btn btn-block tap" disabled={busy} onClick={() => void act("/api/field/day/end")}>
          End day
        </button>
      )}
      <TodaysRoute me={me} />
      <HomeSetter me={me} onDone={() => void load()} />
      <p className="small muted">
        Consent given {me.consent.given_at ? new Date(me.consent.given_at).toLocaleDateString("en-IN") : ""} (version {me.consent.version}).{" "}
        <button
          className="btn-link"
          onClick={async () => {
            if (!window.confirm("Withdraw your consent? Tracking stops now (an open day ends) and no travel claim is made from here on.")) return;
            await api("/api/field/consent", { method: "DELETE" });
            void load();
          }}
        >
          Withdraw consent
        </button>
        {me.profile.reimbursable && (
          <>
            {" · "}
            <Link to="/field/claims">My travel claims</Link>
          </>
        )}
      </p>
    </div>
  );
}
