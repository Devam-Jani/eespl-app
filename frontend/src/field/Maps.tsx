import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";
import { AuthImage, dist, Flags, km, locate, time, useGeoBlocked } from "./common";
import type { Day, MapSettings } from "./common";
import MapView from "./MapView";
import type { MapCircle, MapLine, MapPin } from "./MapView";
import { mapsLink } from "./tracker";
import { ART } from "../ui/tokens";
import { Button, buttonClass, Card, Field } from "../ui/components";

/** A person's day: tracked points as a line, stops as numbered pins (times in and out, the
 * selfie), the road route between the stops, km per leg and the total, flags in red. */
export function DayMap() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const claim = params.get("claim");
  const [day, setDay] = useState<Day | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const load = useCallback(() => api<Day>(`/api/field/days/${id}${claim ? `?claim=${claim}` : ""}`).then(setDay, (e) => setError(errorText(e))), [id, claim]);
  useEffect(() => {
    void load();
  }, [load]);
  const { pins, lines } = useMemo(() => {
    if (!day) return { pins: [] as MapPin[], lines: [] as MapLine[] };
    const pins: MapPin[] = [];
    if (day.home) pins.push({ lat: day.home[0], lng: day.home[1], label: "⌂", kind: "home", title: "Home" });
    if (day.start && !day.home) pins.push({ lat: day.start[0], lng: day.start[1], label: "S", kind: "start", title: `Start ${time(day.started_at)}` });
    day.stops.forEach((s) =>
      pins.push({
        lat: s.in_lat,
        lng: s.in_lng,
        label: String(s.seq),
        kind: s.in_outside || s.out_outside ? "flag" : "stop",
        title: `${s.seq}. ${s.name} ${time(s.in_at)}–${time(s.out_at)}`,
        popup: `<b>${s.seq}. ${escape(s.name)}</b><br>in ${time(s.in_at)} · out ${time(s.out_at)}${s.minutes !== null ? ` · ${s.minutes} min` : ""}${s.in_outside ? `<br><span style="color:${ART.mapFlag}">${Math.round(s.in_distance_m ?? 0)} m from the pin: ${escape(s.in_reason ?? "")}</span>` : ""}`,
      }),
    );
    // the tracked line, broken where no point came for over 10 minutes (a gap is shown as a gap)
    const segments: [number, number][][] = [];
    let prev: number | null = null;
    for (const p of (day.points ?? []).filter((x) => x[4])) {
      const t = Date.parse(p[2]);
      if (prev === null || t - prev > 10 * 60000) segments.push([]);
      segments[segments.length - 1].push([p[0], p[1]]);
      prev = t;
    }
    const lines: MapLine[] = [];
    if (day.road) lines.push({ points: day.road, color: ART.mapRoad, weight: 9 });
    for (const seg of segments) if (seg.length > 1) lines.push({ points: seg, color: ART.mapRoute, weight: 3 });
    return { pins, lines };
  }, [day]);
  if (!day) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const s: MapSettings = day.settings!;
  return (
    <>
      <p className="breadcrumb">
        <Link to="/field">My day</Link> / {day.person} / {new Date(day.on_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
      </p>
      <div className="page-header">
        <div>
          <h1>
            {day.person}: {new Date(day.on_date).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" })}
          </h1>
          <p className="muted">
            {time(day.started_at)} – {day.ended_at ? time(day.ended_at) : "open"}
            {day.auto_ended && " (ended by itself)"} · road km <b>{km(day.route_km)}</b>
            {day.route_estimated && " estimated"} · tracked km <b>{km(day.tracked_km)}</b> · claim uses <b>{day.km_basis === "route" ? "road km" : "tracked km"}</b> ({km(day.km)})
            {day.km_basis_reason && <span className="small"> because: {day.km_basis_reason}</span>}
          </p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="field-day-grid">
        <div>
          <MapView tileUrl={s.tile_url} attribution={s.tile_attribution} pins={pins} lines={lines} height={520} />
          <p className="small muted">
            Blue: the tracked points ({day.points_good} of {day.points_total} used{day.points_deleted ? "; the raw points are deleted after 90 days" : ""}). Grey band: the road
            route between the stops (our own map server). A break in the blue line: no location came then. Red pins: a check-in outside the site&apos;s circle.
          </p>
        </div>
        <div>
          <h3>Flags</h3>
          <Flags flags={day.flags} />
          <h3>Legs</h3>
          <table className="table compact">
            <tbody>
              {day.legs.map((l, i) => (
                <tr key={i}>
                  <td>
                    {l.from} → {l.to}
                  </td>
                  <td className="num">
                    {km(l.km)}
                    {l.estimated && <span className="text-danger small"> est.</span>}
                  </td>
                  <td className="num small muted">{l.minutes !== null ? `${Math.round(l.minutes)} min` : ""}</td>
                </tr>
              ))}
              <tr>
                <td>
                  <b>Total by road</b>
                </td>
                <td className="num">
                  <b>{km(day.route_km)}</b>
                </td>
                <td />
              </tr>
            </tbody>
          </table>
          <h3>Stops</h3>
          <ol className="stop-list">
            {day.stops.map((st) => (
              <li key={st.id}>
                <div>
                  <b>{st.name}</b> {time(st.in_at)}–{time(st.out_at)} {st.minutes !== null && <span className="muted small">{st.minutes} min</span>}
                </div>
                {st.in_outside && (
                  <div className="text-danger small">
                    {dist(st.in_distance_m)} from the pin: {st.in_reason}
                  </div>
                )}
                {st.has_selfie && <AuthImage path={`/api/field/stops/${st.id}/selfie${claim ? `?claim=${claim}` : ""}`} alt={`Selfie at ${st.name}`} />}
              </li>
            ))}
          </ol>
          {day.can_choose_basis && day.ended_at && (
            <Card as="div">
              <h3>Km for the claim</h3>
              {day.basis_locked ? (
                <p className="muted small">{day.basis_locked}.</p>
              ) : (
                <>
                  <Field label="Reason (for tracked km: a detour the stops don't show)" bare>
                    <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (for tracked km: a detour the stops don't show)" />
                  </Field>
                  <div className="form-row">
                    {(["route", "tracked"] as const).map((b) => (
                      <Button
                        key={b}
                        size="small"
                        variant={day.km_basis === b ? "primary" : "secondary"}
                        onClick={async () => {
                          try {
                            await api(`/api/field/days/${day.id}/basis`, { method: "PUT", json: { basis: b, reason: reason || null } });
                            void load();
                          } catch (e) {
                            setError(errorText(e));
                          }
                        }}
                      >
                        Use {b === "route" ? "road" : "tracked"} km
                      </Button>
                    ))}
                  </div>
                </>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function escape(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

type Person = {
  user_id: string;
  name: string;
  started: boolean;
  ended: boolean;
  day_id: number | null;
  last: [number, number] | null;
  last_at: string | null;
  at_stop: string | null;
  flags: number;
  km: number | null;
};

/** The team map: everyone's latest location today with the time of the last point, and who has
 * not started the day. */
export function TeamMap() {
  const [data, setData] = useState<{ people: Person[]; settings: MapSettings } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const load = () => api<{ people: Person[]; settings: MapSettings }>("/api/field/team").then(setData, (e) => setError(errorText(e)));
    void load();
    const t = window.setInterval(() => void load(), 120000);
    return () => window.clearInterval(t);
  }, []);
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const pins: MapPin[] = data.people
    .filter((p) => p.last)
    .map((p) => ({
      lat: p.last![0],
      lng: p.last![1],
      label: initials(p.name),
      kind: "person",
      title: `${p.name} · ${time(p.last_at)}`,
      popup: `<b>${escape(p.name)}</b><br>last at ${time(p.last_at)}${p.at_stop ? `<br>at ${escape(p.at_stop)}` : ""}`,
    }));
  const notStarted = data.people.filter((p) => !p.started);
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Team map</h1>
          <p className="muted">Today&apos;s latest location of each person, and who has not started the day. Every view is logged.</p>
        </div>
      </div>
      <div className="field-day-grid">
        <MapView tileUrl={data.settings.tile_url} attribution={data.settings.tile_attribution} pins={pins} height={540} />
        <div>
          <table className="table compact">
            <thead>
              <tr>
                <th>Person</th>
                <th>Last point</th>
                <th>Now</th>
              </tr>
            </thead>
            <tbody>
              {data.people
                .filter((p) => p.started)
                .map((p) => (
                  <tr key={p.user_id}>
                    <td>{p.day_id ? <Link to={`/field/days/${p.day_id}`}>{p.name}</Link> : p.name}</td>
                    <td>{time(p.last_at)}</td>
                    <td className="small">
                      {p.ended ? "day ended" : p.at_stop ? `at ${p.at_stop}` : "on the way"}
                      {p.flags > 0 && <span className="text-danger"> · {p.flags} flag(s)</span>}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <h3>Not started today ({notStarted.length})</h3>
          <ul className="small">
            {notStarted.map((p) => (
              <li key={p.user_id}>{p.name}</li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

function initials(name: string): string {
  return name
    .replace(/^DEMO\s+/, "")
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

type Visits = {
  site: { id: number; name: string; lat: string | null; lng: string | null; radius_m: number; maps_link: string | null };
  visits: { person: string; on_date: string; in_at: string; out_at: string | null; minutes: number | null; outside: boolean }[];
  gangs: { id: number; contractor: string; headcount: number; on_date: string; in_at: string; out_at: string | null; hours: number | null; outside: boolean }[];
};

/** On a site: its pin and circle (planning or the site engineer set it: on the map, or "use my
 * location" standing at the site), "Go to site", and who checked in, when and for how long. */
export function SiteLocationTab({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const [v, setV] = useState<Visits | null>(null);
  const [settings, setSettings] = useState<MapSettings | null>(null);
  const [picked, setPicked] = useState<[number, number] | null>(null);
  const [radius, setRadius] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const geoBlocked = useGeoBlocked();
  const load = useCallback(() => {
    api<Visits>(`/api/field/sites/${siteId}/visits`).then(setV, (e) => setMsg(errorText(e)));
    api<MapSettings>("/api/field/map-settings").then(setSettings, (e) => setMsg(errorText(e)));
  }, [siteId]);
  useEffect(() => {
    load();
  }, [load]);
  if (!v || !settings) return msg ? <div className="alert alert-error">{msg}</div> : <p className="muted">Loading…</p>;
  const pin = v.site.lat !== null ? ([Number(v.site.lat), Number(v.site.lng)] as [number, number]) : null;
  const circles: MapCircle[] = pin ? [{ lat: pin[0], lng: pin[1], radius: v.site.radius_m }] : [];
  const canPin = can("site.location");
  return (
    <div className="field-day-grid">
      <div>
        {!pin && <div className="alert alert-warn">Location missing: pin the site so check-ins can be checked.</div>}
        <MapView
          tileUrl={settings.tile_url}
          attribution={settings.tile_attribution}
          pins={pin ? [{ lat: pin[0], lng: pin[1], label: "S", kind: "site", title: v.site.name }] : []}
          circles={circles}
          picked={picked}
          onPick={canPin ? (lat, lng) => setPicked([lat, lng]) : undefined}
          height={380}
        />
        {canPin && (
          <div className="form-row top-gap-small">
            {/* it says at once that it is looking (a fix can take seconds), and why it cannot when it cannot */}
            <Button
              size="small"
              disabled={!!geoBlocked || locating}
              title={geoBlocked ?? undefined}
              onClick={() => {
                setLocating(true);
                setMsg("Finding your location…");
                void locate()
                  .then(
                    (f) => {
                      setPicked([f.lat, f.lng]);
                      setMsg(`Your location (within ${f.accuracy} m) is picked: save the pin to keep it.`);
                    },
                    (e) => setMsg(errorText(e)),
                  )
                  .finally(() => setLocating(false));
              }}
            >
              {locating ? "Finding…" : "Use my location"}
            </Button>
            <Field label="Radius in metres" bare>
              <input className="input-small" value={radius} onChange={(e) => setRadius(e.target.value)} placeholder={`radius ${v.site.radius_m} m`} aria-label="Radius in metres" />
            </Field>
            <Button
              variant="primary" size="small"
              disabled={!picked && !radius}
              onClick={async () => {
                const at = picked ?? pin;
                if (!at) return setMsg("Pick the place on the map first");
                try {
                  await api(`/api/field/sites/${siteId}/location`, { method: "PUT", json: { lat: at[0], lng: at[1], ...(radius ? { radius_m: Number(radius) } : {}) } }); // empty: keep the site's radius
                  setPicked(null);
                  setMsg("Saved (the change is logged).");
                  load();
                } catch (e) {
                  setMsg(errorText(e));
                }
              }}
            >
              Save the pin
            </Button>
          </div>
        )}
        {canPin && geoBlocked && <p className="small muted">Use my location: {geoBlocked}.</p>}
        {msg && <p className="small">{msg}</p>}
        {pin && (
          <a className={buttonClass({ variant: "primary", className: "top-gap-small" })} href={mapsLink(pin[0], pin[1])} target="_blank" rel="noreferrer">
            Go to site (Google Maps)
          </a>
        )}
      </div>
      <div>
        <h3>Who checked in (30 days)</h3>
        <table className="table compact">
          <thead>
            <tr>
              <th>Person</th>
              <th>Date</th>
              <th>In – out</th>
              <th className="num">Time on site</th>
            </tr>
          </thead>
          <tbody>
            {v.visits.map((x, i) => (
              <tr key={i} className={x.outside ? "row-warn" : ""}>
                <td>{x.person}</td>
                <td>{new Date(x.on_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</td>
                <td>
                  {time(x.in_at)} – {time(x.out_at)}
                </td>
                <td className="num">{x.minutes !== null ? `${Math.floor(x.minutes / 60)} h ${x.minutes % 60} min` : "on site"}</td>
              </tr>
            ))}
            {!v.visits.length && (
              <tr>
                <td colSpan={4} className="muted">
                  Nobody checked in yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <h3>Labour gangs</h3>
        <table className="table compact">
          <tbody>
            {v.gangs.map((g) => (
              <tr key={g.id} className={g.outside ? "row-warn" : ""}>
                <td>{g.contractor}</td>
                <td>{g.headcount} people</td>
                <td>
                  {new Date(g.on_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} {time(g.in_at)}–{time(g.out_at)}
                </td>
                <td className="num">{g.hours !== null ? `${g.hours} h` : "on site"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
