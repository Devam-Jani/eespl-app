import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { errorText, inr } from "../format";
import { dist, locate, time } from "./common";
import type { MapSettings, MySite } from "./common";
import MapView from "./MapView";
import { Button, buttonClass, Card, Field } from "../ui/components";

type Gang = {
  id: number;
  site_id: number;
  site: string;
  contractor: string;
  on_date: string;
  headcount: number;
  workers: string[];
  in_at: string;
  out_at: string | null;
  hours: number | null;
  in_outside: boolean;
  in_distance_m: number | null;
  in_reason: string | null;
};
type Contractor = { id: number; name: string; workers: { id: number; name: string; trade: string }[] };

/** The supervisor checks a labour gang in and out of a site: the contractor, names or a headcount,
 * one group photo, location and time (inside the site's circle, else flagged with a reason).
 * Labour carry no phone and are never tracked. */
export function GangCheckIn() {
  const [data, setData] = useState<{ visits: Gang[]; contractors: Contractor[]; sites: MySite[] } | null>(null);
  const [siteId, setSiteId] = useState("");
  const [contractorId, setContractorId] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  const [headcount, setHeadcount] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [needReason, setNeedReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<{ visits: Gang[]; contractors: Contractor[]; sites: MySite[] }>("/api/field/gangs").then(setData, (e) => setError(errorText(e))), []);
  useEffect(() => {
    void load();
  }, [load]);
  const contractor = data?.contractors.find((c) => String(c.id) === contractorId);
  async function checkIn() {
    setBusy(true);
    setError(null);
    try {
      const at = await locate();
      const form = new FormData();
      form.append("site_id", siteId);
      form.append("contractor_id", contractorId);
      form.append("lat", String(at.lat));
      form.append("lng", String(at.lng));
      form.append("accuracy", String(at.accuracy));
      if (picked.length) form.append("labour_ids", picked.join(","));
      else form.append("headcount", headcount);
      if (reason.trim()) form.append("reason", reason.trim());
      form.append("photo", photo!);
      await api("/api/field/gangs/in", { method: "POST", form });
      setPicked([]);
      setHeadcount("");
      setPhoto(null);
      setReason("");
      setNeedReason(null);
      await load();
    } catch (e) {
      const text = errorText(e);
      if (text.includes("give the reason")) setNeedReason(text);
      else setError(text);
    } finally {
      setBusy(false);
    }
  }
  async function checkOut(g: Gang, why?: string) {
    try {
      const at = await locate();
      const form = new FormData();
      form.append("lat", String(at.lat));
      form.append("lng", String(at.lng));
      form.append("accuracy", String(at.accuracy));
      if (why) form.append("reason", why);
      await api(`/api/field/gangs/${g.id}/out`, { method: "POST", form });
      await load();
    } catch (e) {
      const text = errorText(e);
      const r = text.includes("give the reason") ? window.prompt(`${text}\n\nThe reason:`) : null;
      if (r?.trim()) await checkOut(g, r.trim());
      else setError(text);
    }
  }
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <div className="field-phone">
      <h1>Gang check-in</h1>
      {error && <div className="alert alert-error">{error}</div>}
      <Card as="div">
        <Field label="Site">
          <select className="tap-input" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">— the site —</option>
            {data.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Labour contractor">
          <select
            className="tap-input"
            value={contractorId}
            onChange={(e) => {
              setContractorId(e.target.value);
              setPicked([]);
            }}
          >
            <option value="">— the gang —</option>
            {data.contractors.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.workers.length})
              </option>
            ))}
          </select>
        </Field>
        {contractor && (
          <>
            <div className="small muted">Tick who is here, or give the headcount:</div>
            <div className="chip-list">
              {contractor.workers.map((w) => (
                <label key={w.id} className="chip">
                  <input type="checkbox" checked={picked.includes(w.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, w.id] : picked.filter((x) => x !== w.id))} />{" "}
                  {w.name}
                </label>
              ))}
            </div>
            {!picked.length && (
              <Field label="Headcount" bare>
                <input className="tap-input" inputMode="numeric" value={headcount} onChange={(e) => setHeadcount(e.target.value)} placeholder="Headcount" aria-label="Headcount" />
              </Field>
            )}
          </>
        )}
        <label className={buttonClass({ block: true, className: "tap" })}>
          {photo ? "Group photo taken: retake" : "Group photo"}
          <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </label>
        {needReason && (
          <div className="alert alert-warn">
            {needReason}
            <Field label="Why outside the site circle?" bare>
              <textarea className="tap-input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why outside the site circle?" />
            </Field>
          </div>
        )}
        <Button
          variant="primary" block className="tap"
          disabled={busy || !siteId || !contractorId || !photo || (!picked.length && !headcount) || (!!needReason && !reason.trim())}
          onClick={() => void checkIn()}
        >
          {busy ? "Getting your location…" : `Check in ${picked.length || headcount || ""} at the site`}
        </Button>
      </Card>
      <h3>Today</h3>
      {data.visits.map((g) => (
        <Card key={g.id} as="div">
          <b>{g.contractor}</b> at {g.site}: {g.headcount} people {g.workers.length ? `(${g.workers.join(", ")})` : ""}
          <div className="small">
            in {time(g.in_at)} {g.out_at ? `· out ${time(g.out_at)} · ${g.hours} h each` : ""}
            {g.in_outside && (
              <span className="text-danger">
                {" "}
                · {dist(g.in_distance_m)} from the pin: {g.in_reason}
              </span>
            )}
          </div>
          {!g.out_at && (
            <Button size="small" className="tap" onClick={() => void checkOut(g)}>
              Check the gang out
            </Button>
          )}
        </Card>
      ))}
    </div>
  );
}

type Person = {
  user_id: string;
  name: string;
  job_title: string | null;
  roles: string[];
  is_demo: boolean;
  tracked: boolean;
  reimbursable: boolean;
  vehicle: string;
  manager_id: string | null;
  manager: string | null;
  weekly_off: number | null;
  home_status: string;
  home: [number, number] | null;
  pending: [number, number] | null;
  consent_given_at: string | null;
  rates: { id: number; vehicle: string; rate_per_km: number; valid_from: string; valid_to: string | null }[];
  rate_today: number | null;
};

/** Settings › Field tracking (office_admin): per person tracked, eligible for travel
 * reimbursement (office employees only; labour never), vehicle, manager, the rate per km with
 * its dates (history kept), the home location (approve or not); and the general settings. */
export function FieldSettings() {
  const [people, setPeople] = useState<Person[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [rate, setRate] = useState({ rate_per_km: "", valid_from: "", vehicle: "bike" });
  const [s, setS] = useState<Record<string, string | number> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Person[]>("/api/field/admin/people").then(setPeople, (e) => setError(errorText(e)));
    api<Record<string, string | number>>("/api/field/admin/settings").then(setS, () => undefined);
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  async function run(p: Promise<unknown>): Promise<boolean> {
    setError(null);
    try {
      await p;
      load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    }
  }
  const put = (p: Person, json: Record<string, unknown>) => void run(api(`/api/field/admin/people/${p.user_id}`, { method: "PUT", json }));
  const tiles: MapSettings | null = s ? ({ tile_url: String(s.tile_url), tile_attribution: String(s.tile_attribution) } as MapSettings) : null;
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Field tracking</h1>
          <p className="muted">Who is tracked (Start day to End day only, with their consent), who is paid travel per km, and their home. Labour are never tracked.</p>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <thead>
          <tr>
            <th>Person</th>
            <th>Tracked</th>
            <th>Travel per km</th>
            <th>Vehicle</th>
            <th>Manager</th>
            <th>Weekly off</th>
            <th className="num">Rate today</th>
            <th>Home</th>
            <th>Consent</th>
          </tr>
        </thead>
        <tbody>
          {people.map((p) => (
            <Fragment key={p.user_id}>
              <tr className={open === p.user_id ? "row-selected" : ""}>
                <td>
                  <button className="link-button" onClick={() => setOpen(open === p.user_id ? null : p.user_id)}>
                    {p.name}
                  </button>
                  <div className="small muted">{p.job_title}</div>
                </td>
                <td>
                  <input type="checkbox" checked={p.tracked} onChange={(e) => put(p, { tracked: e.target.checked })} aria-label="Tracked" />
                </td>
                <td>
                  <input type="checkbox" checked={p.reimbursable} onChange={(e) => put(p, { reimbursable: e.target.checked })} aria-label="Eligible for travel reimbursement" />
                </td>
                <td>
                  <Field label="Vehicle" bare>
                    <select value={p.vehicle} onChange={(e) => put(p, { vehicle: e.target.value })} aria-label="Vehicle">
                      <option value="bike">Bike</option>
                      <option value="car">Car</option>
                      <option value="other">Other</option>
                    </select>
                  </Field>
                </td>
                <td>
                  <Field label="Manager" bare>
                    <select value={p.manager_id ?? ""} onChange={(e) => put(p, { manager_id: e.target.value || null })} aria-label="Manager">
                      <option value="">—</option>
                      {people
                        .filter((m) => m.user_id !== p.user_id)
                        .map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                </td>
                <td>
                  <Field label="Weekly off" bare>
                    <select value={p.weekly_off ?? ""} onChange={(e) => put(p, { weekly_off: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Weekly off">
                      <option value="">none</option>
                      {DAYS.map((d, i) => (
                        <option key={d} value={i}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </Field>
                </td>
                <td className="num">{p.rate_today !== null ? `${inr(p.rate_today)}/km` : "—"}</td>
                <td className={p.home_status === "pending" || p.pending ? "text-warn" : ""}>
                  {p.pending ? "to approve" : p.home_status === "approved" ? "approved" : p.home_status}
                </td>
                <td className="small">{p.consent_given_at ? new Date(p.consent_given_at).toLocaleDateString("en-IN") : "not given"}</td>
              </tr>
              {open === p.user_id && (
                <tr>
                  <td colSpan={9}>
                    <div className="field-day-grid">
                      <div>
                        <h3>Rate per km</h3>
                        <table className="table compact">
                          <tbody>
                            {p.rates.map((r) => (
                              <tr key={r.id}>
                                <td>{r.vehicle}</td>
                                <td className="num">{inr(r.rate_per_km)}/km</td>
                                <td>
                                  from {r.valid_from} {r.valid_to ? `to ${r.valid_to}` : "(in force)"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="form-row">
                          <Field label="Vehicle" bare>
                            <select value={rate.vehicle} onChange={(e) => setRate({ ...rate, vehicle: e.target.value })} aria-label="Vehicle">
                              <option value="bike">Bike</option>
                              <option value="car">Car</option>
                              <option value="other">Other</option>
                            </select>
                          </Field>
                          <Field label="Rate per km" bare>
                            <input
                              className="input-small"
                              value={rate.rate_per_km}
                              onChange={(e) => setRate({ ...rate, rate_per_km: e.target.value })}
                              placeholder="₹ per km"
                              aria-label="Rate per km"
                            />
                          </Field>
                          <Field label="Valid from" bare>
                            <input type="date" value={rate.valid_from} onChange={(e) => setRate({ ...rate, valid_from: e.target.value })} aria-label="Valid from" />
                          </Field>
                          <Button
                            variant="primary" size="small"
                            disabled={!rate.rate_per_km || !rate.valid_from}
                            onClick={() =>
                              void run(api(`/api/field/admin/people/${p.user_id}/rates`, { method: "POST", json: rate })).then(
                                (ok) => ok && setRate({ rate_per_km: "", valid_from: "", vehicle: "bike" }), // a refused rate stays to be corrected
                              )
                            }
                          >
                            Add the rate
                          </Button>
                        </div>
                      </div>
                      <div>
                        <h3>Home location</h3>
                        {tiles && (
                          <MapView
                            tileUrl={tiles.tile_url}
                            attribution={tiles.tile_attribution}
                            pins={[
                              ...(p.home ? [{ lat: p.home[0], lng: p.home[1], label: "⌂", kind: "home" as const, title: "Approved home" }] : []),
                              ...(p.pending ? [{ lat: p.pending[0], lng: p.pending[1], label: "?", kind: "flag" as const, title: "Asked for" }] : []),
                            ]}
                            height={220}
                          />
                        )}
                        {p.pending && (
                          <div className="form-row">
                            <span className="small">Asked for {p.home ? "a change of home" : "a home"}.</span>
                            <Button
                              variant="primary" size="small"
                              onClick={() => void run(api(`/api/field/admin/people/${p.user_id}/home`, { method: "POST", json: { approve: true } }))}
                            >
                              Approve
                            </Button>
                            <Button
                              size="small"
                              onClick={() => void run(api(`/api/field/admin/people/${p.user_id}/home`, { method: "POST", json: { approve: false } }))}
                            >
                              Not approved
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      <Holidays />
      {s && (
        <Card as="div" className="top-gap">
          <h3>General</h3>
          <div className="form-grid">
            {(
              [
                ["consent_version", "Consent version (a new one asks everyone again)"],
                ["auto_end_at", "Day ends by itself at (IST)"],
                ["site_radius_m", "Site circle (m)"],
                ["home_flag_m", "Start / end flagged beyond home (m)"],
                ["gap_minutes", "Gap flagged after (min)"],
                ["raw_days", "Raw points kept (days)"],
                ["summary_years", "Day summaries and claims kept (years)"],
                ["tile_url", "Map tiles URL"],
                ["tile_attribution", "Map credit"],
              ] as [string, string][]
            ).map(([k, label]) => (
              <Field label={label} key={k}>
                <input value={String(s[k] ?? "").slice(0, k === "auto_end_at" ? 5 : 300)} onChange={(e) => setS({ ...s, [k]: e.target.value })} />
              </Field>
            ))}
          </div>
          <Button
            variant="primary"
            onClick={() => {
              const json: Record<string, unknown> = {};
              for (const k of ["consent_version", "tile_url", "tile_attribution"]) json[k] = s[k];
              json.auto_end_at = String(s.auto_end_at).slice(0, 5);
              for (const k of ["site_radius_m", "home_flag_m", "gap_minutes", "raw_days", "summary_years"]) json[k] = Number(s[k]);
              void run(api("/api/field/admin/settings", { method: "PUT", json }));
            }}
          >
            Save
          </Button>
        </Card>
      )}
    </>
  );
}

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** The company holidays: a day started on one is flagged for the manager, not blocked. */
function Holidays() {
  const [rows, setRows] = useState<{ id: number; on_date: string; name: string }[]>([]);
  const [form, setForm] = useState({ on_date: "", name: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<typeof rows>("/api/field/admin/holidays").then(setRows, (e) => setError(errorText(e)));
  }, []);
  return (
    <Card as="div" className="top-gap">
      <h3>Company holidays</h3>
      <p className="small muted">A day started on a holiday or on the person&apos;s weekly off is flagged for the manager (never blocked).</p>
      {error && <div className="alert alert-error">{error}</div>}
      <table className="table compact">
        <tbody>
          {rows.map((h) => (
            <tr key={h.id}>
              <td>{new Date(h.on_date).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}</td>
              <td>{h.name}</td>
              <td>
                <Button
                  variant="ghost" size="small"
                  onClick={() => api<typeof rows>(`/api/field/admin/holidays/${h.id}`, { method: "DELETE" }).then(setRows, (e) => setError(errorText(e)))}
                >
                  Remove
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="form-row">
        <Field label="Date" bare>
          <input type="date" value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} aria-label="Date" />
        </Field>
        <Field label="Holiday" bare>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Diwali" aria-label="Holiday" />
        </Field>
        <Button
          variant="primary" size="small"
          disabled={!form.on_date || !form.name.trim()}
          onClick={() =>
            api<typeof rows>("/api/field/admin/holidays", { method: "POST", json: form }).then(
              (r) => {
                setRows(r);
                setForm({ on_date: "", name: "" });
              },
              (e) => setError(errorText(e)),
            )
          }
        >
          Add
        </Button>
      </div>
    </Card>
  );
}
