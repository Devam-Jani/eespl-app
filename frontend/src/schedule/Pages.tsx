// The schedule on a site: the project's material plan with the lots called off against it, the
// handover dates per place (promised by the client, confirmed by the supervisor) with the target
// finish and the two delays, and the director's view of the delays across sites.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, num } from "../format";
import { shortDate } from "../pages/Tenders";
import { Button, Card, Field } from "../ui/components";

type PlanRow = {
  product_id: number;
  product: string;
  unit: string;
  planned: string;
  computed: string;
  fixed: boolean;
  note: string | null;
  called_off: string;
  pending: string;
  delivered: string;
  issued: string;
  balance: string;
  limit: string;
};
type Lot = {
  id: number;
  code: string;
  status: "approved" | "pending" | "rejected";
  over_plan: boolean;
  reason: string | null;
  days: number | null;
  need_by: string | null;
  places: string[];
  lines: { product_id: number; product: string; unit: string; qty: string }[];
  called_by: string | null;
  called_at: string;
  decided_by: string | null;
  decision_note: string | null;
  indent_id: number | null;
  indent: string | null;
};
type Plan = { site_id: number; tolerance_percent: string; products: PlanRow[]; lots: Lot[] };

export function PlanLots({ siteId }: { siteId: number }) {
  const { can } = useAuth();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [qty, setQty] = useState<Record<number, string>>({});
  const [days, setDays] = useState("4");
  const [reason, setReason] = useState("");
  const load = useCallback(() => api<Plan>(`/api/schedule/sites/${siteId}/plan`).then(setPlan, (e) => setError(errorText(e))), [siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  async function fix() {
    try {
      setPlan(await api<Plan>(`/api/schedule/sites/${siteId}/plan/fix`, { method: "POST", json: {} }));
      setNotice("The plan is fixed at the computed quantities.");
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function callOff() {
    setError("");
    const lines = Object.entries(qty)
      .filter(([, v]) => Number(v) > 0)
      .map(([pid, v]) => ({ product_id: Number(pid), qty: v }));
    try {
      const lot = await api<Lot>(`/api/schedule/sites/${siteId}/lots`, { method: "POST", json: { lines, days: Number(days) || null, reason: reason || null } });
      setNotice(lot.status === "pending" ? `${lot.code} is over the plan: waiting for planning.` : `${lot.code} called off: indent ${lot.indent}.`);
      setQty({});
      setReason("");
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function decide(lot: Lot, approve: boolean) {
    const note = approve ? "" : (window.prompt("Why is it rejected?") ?? "");
    if (!approve && !note.trim()) return;
    try {
      await api(`/api/schedule/lots/${lot.id}/decide`, { method: "POST", json: { approve, note: note || null } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!plan) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const canCall = can("indent.create");
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-ok">{notice}</div>}
      <Card
        as="div"
        title="Material planned for the whole project"
        actions={
          can("planning.edit") &&
          !plan.products.some((p) => p.fixed) && (
            <Button size="small" onClick={() => void fix()}>
              Fix the plan
            </Button>
          )
        }
      >
        <p className="small muted">
          The whole site's quantity per product (BOQ and survey quantities with consumption and wastage). The site calls off lots for the ready work fronts; a call-off past the
          balance plus {num(plan.tolerance_percent)} % waits for planning.
        </p>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Planned</th>
                <th className="num">Called off</th>
                <th className="num">Waiting</th>
                <th className="num">Delivered</th>
                <th className="num">Issued</th>
                <th className="num">Balance</th>
                {canCall && <th className="num">Call off now</th>}
              </tr>
            </thead>
            <tbody>
              {plan.products.map((p) => (
                <tr key={p.product_id} className={Number(p.balance) < 0 ? "row-warn" : ""}>
                  <td>
                    {p.product}
                    {p.note && <div className="small muted">{p.note}</div>}
                  </td>
                  <td className="num">
                    {num(p.planned, 3)} {p.unit}
                  </td>
                  <td className="num">{num(p.called_off, 3)}</td>
                  <td className="num">{Number(p.pending) ? num(p.pending, 3) : "—"}</td>
                  <td className="num">{num(p.delivered, 3)}</td>
                  <td className="num">{num(p.issued, 3)}</td>
                  <td className={`num ${Number(p.balance) < 0 ? "text-danger" : ""}`}>{num(p.balance, 3)}</td>
                  {canCall && (
                    <td className="num">
                      <Field label={`Call off ${p.product}`} bare>
                        <input
                          className="input-num"
                          inputMode="decimal"
                          value={qty[p.product_id] ?? ""}
                          onChange={(e) => setQty({ ...qty, [p.product_id]: e.target.value })}
                          aria-label={`Call off ${p.product}`}
                        />
                      </Field>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canCall && (
          <div className="form-row top-gap">
            <Field label="For the next (days)">
              <input className="input-num" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} />
            </Field>
            <Field label="Reason (needed past the plan)" className="grow">
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button variant="primary" disabled={!Object.values(qty).some((v) => Number(v) > 0)} onClick={() => void callOff()}>
              Call off the lot
            </Button>
          </div>
        )}
      </Card>
      <Card as="div" className="top-gap">
        <h2 className="section-title">Lots</h2>
        {plan.lots.length === 0 ? (
          <p className="empty">No lots yet.</p>
        ) : (
          <table className="table compact">
            <thead>
              <tr>
                <th>Lot</th>
                <th>Products</th>
                <th>For</th>
                <th>Called by</th>
                <th>Status</th>
                <th>Indent</th>
              </tr>
            </thead>
            <tbody>
              {plan.lots.map((l) => (
                <tr key={l.id} className={l.status === "pending" ? "row-warn" : ""}>
                  <td>
                    <b>{l.code}</b>
                  </td>
                  <td>
                    {l.lines.map((x) => (
                      <div key={x.product_id}>
                        {x.product}: {num(x.qty, 3)} {x.unit}
                      </div>
                    ))}
                    {l.reason && <div className="small muted">Reason: {l.reason}</div>}
                  </td>
                  <td className="small">
                    {l.days ? `next ${l.days} days` : ""}
                    {l.places.length > 0 && <div>{l.places.join(", ")}</div>}
                  </td>
                  <td className="small">
                    {l.called_by}
                    <div className="muted">{shortDate(l.called_at.slice(0, 10))}</div>
                  </td>
                  <td>
                    <span className={`badge ${l.status === "approved" ? "badge-ok" : l.status === "pending" ? "badge-warn" : "badge-muted"}`}>
                      {l.status === "pending" ? "over the plan: waiting for planning" : l.status}
                    </span>
                    {l.decided_by && <div className="small muted">by {l.decided_by}</div>}
                    {l.status === "pending" && can("planning.edit") && (
                      <div className="top-gap-small">
                        <Button variant="primary" size="small" onClick={() => void decide(l, true)}>
                          Approve
                        </Button>{" "}
                        <Button size="small" onClick={() => void decide(l, false)}>
                          Reject
                        </Button>
                      </div>
                    )}
                  </td>
                  <td>{l.indent_id ? <Link to={`/indents?open=${l.indent_id}`}>{l.indent}</Link> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

// --- handover dates and the target finish ---------------------------------------------------------

type Area = {
  node_id: number;
  place: string;
  promised_on: string | null;
  promised_by: string | null;
  client_says_on: string | null;
  status: string | null;
  received_on: string | null;
  stage_days: number | null;
  target_finish: string | null;
  finished_on: string | null;
  client_delay_days: number | null;
  our_delay_days: number | null;
  overdue_handover: boolean;
  overdue_finish: boolean;
  client_promised_on?: string | null;
  client_promised_by?: string | null;
  moved_to?: string | null;
  moved_because?: string | null;
  moved_by?: string | null;
};
type Handover = { site: string; areas: Area[]; client_delay_days: number; our_delay_days: number; can_promise: boolean; can_confirm: boolean };

export function HandoverTab({ siteId }: { siteId: number }) {
  const [h, setH] = useState<Handover | null>(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<{ node: number; promised_on: string; promised_by: string; client_says_on: string } | null>(null);
  const load = useCallback(() => api<Handover>(`/api/schedule/sites/${siteId}/handover`).then(setH, (e) => setError(errorText(e))), [siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  async function savePromise() {
    if (!edit) return;
    try {
      await api(`/api/schedule/sites/${siteId}/nodes/${edit.node}/promise`, {
        method: "PUT",
        json: { promised_on: edit.promised_on, promised_by: edit.promised_by, client_says_on: edit.client_says_on || null },
      });
      setEdit(null);
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  const { can } = useAuth();
  const [moving, setMoving] = useState<{ node: number; place: string; to: string; reason: string } | null>(null);
  async function move() {
    if (!moving) return;
    try {
      await api(`/api/closeout/sites/${siteId}/nodes/${moving.node}/handover-move`, { method: "POST", json: { promised_on: moving.to, reason: moving.reason } });
      setMoving(null);
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function confirm(a: Area, received: boolean) {
    const on = received ? (window.prompt("Received on (YYYY-MM-DD)", new Date().toISOString().slice(0, 10)) ?? "") : "";
    if (received && !on) return;
    try {
      await api(`/api/schedule/sites/${siteId}/nodes/${a.node_id}/handover`, { method: "POST", json: { received, on_date: on || null } });
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!h) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  return (
    <Card as="div">
      <h2 className="section-title">Handover and the schedule</h2>
      <p className="small muted">
        The engineer enters the date the client promised (and who promised it). Only the supervisor's confirmation starts the clock: target finish = the real handover + the stage
        days. Client delay: handed over later than promised. Our delay: finished later than the target.
      </p>
      <div className="stat-row">
        <span className={`stat ${h.client_delay_days ? "stat-warn" : ""}`}>
          Client delay <b>{h.client_delay_days} d</b>
        </span>
        <span className={`stat ${h.our_delay_days ? "stat-danger" : ""}`}>
          Our delay <b>{h.our_delay_days} d</b>
        </span>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>Place</th>
              <th>Promised by the client</th>
              <th>Handover (supervisor)</th>
              <th className="num">Stage days</th>
              <th>Target finish</th>
              <th>Finished</th>
              <th className="num">Client delay</th>
              <th className="num">Our delay</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {h.areas.map((a) => (
              <tr key={a.node_id} className={a.overdue_finish ? "row-danger" : a.overdue_handover ? "row-warn" : ""}>
                <td>
                  <b>{a.place}</b>
                </td>
                <td className="small">
                  {a.promised_on ? (
                    <>
                      {shortDate(a.promised_on)}
                      {a.moved_to ? (
                        <div className="muted">
                          moved by {a.moved_by} because {a.moved_because}
                          {a.client_promised_on && (
                            <>
                              {" "}
                              · the client promised <b>{shortDate(a.client_promised_on)}</b>
                            </>
                          )}
                        </div>
                      ) : (
                        <div className="muted">{a.promised_by}</div>
                      )}
                      {a.client_says_on && <div className="muted">client says handed over {shortDate(a.client_says_on)} (not counted)</div>}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="small">
                  {a.received_on ? (
                    <span className="badge badge-ok">received {shortDate(a.received_on)}</span>
                  ) : a.status === "not_received" ? (
                    <span className="badge badge-warn">not received yet</span>
                  ) : a.promised_on ? (
                    <span className="badge badge-muted">awaited</span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="num">{a.stage_days ?? "—"}</td>
                <td>{a.target_finish ? shortDate(a.target_finish) : <span className="muted small">starts at the handover</span>}</td>
                <td>{a.finished_on ? shortDate(a.finished_on) : "—"}</td>
                <td className={`num ${a.client_delay_days ? "text-warn" : ""}`}>{a.client_delay_days === null ? "—" : `${a.client_delay_days} d`}</td>
                <td className={`num ${a.our_delay_days ? "text-danger" : ""}`}>{a.our_delay_days === null ? "—" : `${a.our_delay_days} d`}</td>
                <td className="nowrap">
                  {h.can_promise && (
                    <Button
                      variant="ghost" size="small"
                      onClick={() => setEdit({ node: a.node_id, promised_on: a.promised_on ?? "", promised_by: a.promised_by ?? "", client_says_on: a.client_says_on ?? "" })}
                    >
                      Promised date
                    </Button>
                  )}
                  {can("closeout.site") && !a.received_on && a.promised_on && (
                    <Button variant="ghost" size="small" onClick={() => setMoving({ node: a.node_id, place: a.place, to: a.promised_on ?? "", reason: "" })}>
                      Move the date
                    </Button>
                  )}
                  {h.can_confirm && !a.received_on && (
                    <>
                      <Button variant="primary" size="small" onClick={() => void confirm(a, true)}>
                        Received
                      </Button>
                      <Button size="small" onClick={() => void confirm(a, false)}>
                        Not yet
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {moving && (
        <div className="form-row top-gap">
          <span className="small">
            <b>{moving.place}</b>: moved to
          </span>
          <Field label="New date">
            <input type="date" value={moving.to} onChange={(e) => setMoving({ ...moving, to: e.target.value })} />
          </Field>
          <Field label="Because (the client sees it)" className="grow">
            <input value={moving.reason} onChange={(e) => setMoving({ ...moving, reason: e.target.value })} />
          </Field>
          <Button variant="primary" disabled={!moving.to || moving.reason.trim().length < 3} onClick={() => void move()}>
            Move
          </Button>
          <Button variant="ghost" onClick={() => setMoving(null)}>
            Cancel
          </Button>
        </div>
      )}
      {edit && (
        <div className="form-row top-gap">
          <Field label="Promised handover">
            <input type="date" value={edit.promised_on} onChange={(e) => setEdit({ ...edit, promised_on: e.target.value })} />
          </Field>
          <Field label="Who promised it" className="grow">
            <input value={edit.promised_by} onChange={(e) => setEdit({ ...edit, promised_by: e.target.value })} />
          </Field>
          <Field label="Client says handed over (does not count)">
            <input type="date" value={edit.client_says_on} onChange={(e) => setEdit({ ...edit, client_says_on: e.target.value })} />
          </Field>
          <Button variant="primary" disabled={!edit.promised_on || edit.promised_by.trim().length < 2} onClick={() => void savePromise()}>
            Save
          </Button>
          <Button variant="ghost" onClick={() => setEdit(null)}>
            Cancel
          </Button>
        </div>
      )}
    </Card>
  );
}

// --- the director's view: delays across sites -----------------------------------------------------

type Delays = {
  sites: { site_id: number; site: string; client_delay_days: number; our_delay_days: number; late_by_client: number; late_by_us: number; areas: Area[] }[];
  client_delay_days: number;
  our_delay_days: number;
};

export function DelaysCard() {
  const [d, setD] = useState<Delays | null>(null);
  useEffect(() => {
    api<Delays>("/api/schedule/delays").then(setD, () => setD(null));
  }, []);
  if (!d || d.sites.length === 0) return null;
  return (
    <Card as="div">
      <h2 className="section-title">Delays: the client's and ours</h2>
      <div className="stat-row">
        <span className="stat stat-warn">
          Client delay <b>{d.client_delay_days} d</b>
        </span>
        <span className="stat stat-danger">
          Our delay <b>{d.our_delay_days} d</b>
        </span>
      </div>
      <table className="table compact">
        <thead>
          <tr>
            <th>Site</th>
            <th className="num">Client delay</th>
            <th className="num">Our delay</th>
            <th>Late places</th>
          </tr>
        </thead>
        <tbody>
          {d.sites.map((s) => (
            <tr key={s.site_id}>
              <td>
                <Link to={`/sites/${s.site_id}?tab=handover`}>{s.site}</Link>
              </td>
              <td className="num">{s.client_delay_days} d</td>
              <td className={`num ${s.our_delay_days ? "text-danger" : ""}`}>{s.our_delay_days} d</td>
              <td className="small">
                {s.areas.map((a) => (
                  <div key={a.node_id}>
                    {a.place}: {a.client_delay_days ? `client ${a.client_delay_days} d` : ""}
                    {a.client_delay_days && a.our_delay_days ? ", " : ""}
                    {a.our_delay_days ? `ours ${a.our_delay_days} d` : ""}
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
