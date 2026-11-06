// Make quotation from drawing (Prompt 39): for the super admin, planning and the estimator. Pick the
// drawing revision and the client; the drawing's mapped areas give each area type its quantity
// (floor less cut-outs, upturn, sunk side walls, wall area), its key points rank every brand's
// option (the default system pre-ticked), the user ticks what to quote. Areas not mapped, or a type
// with nothing picked, block the button until picked or left out with a reason. Making it writes a
// draft quotation and its rate working (nothing is sent); the review grid's every cell can be
// changed ("changed by user", back to calculated); a line lights its areas in 2D and 3D.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { errorText, inr, num } from "../../format";
import type { Building, P } from "../../xray/geometry";
import type { XNode } from "../../xray/XrayView";
import { Button, buttonClass, Card, Field } from "../../ui/components";

const XrayView = lazy(() => import("../../xray/XrayView"));

type FileRow = { cad_file_id: number; drawing: string | null; rev_no: number | null; areas: number; mapped: number };
type RunRow = { id: number; cad_file_id: number; status: string; quotation_id: number | null; created_at: string };
type Site = { site: { id: number; name: string; client_id: number | null }; files: FileRow[]; runs: RunRow[] };
type Area = { id: number; key: string; name: string; floor: string | null; floor_sqm: string; cutout_sqm: string; periphery_m: string; upturn_m: string; upturn_from: string; sunk_m: string; wall_sqm: string; total_sqm: string; formula: string; outline: P[] | null; holes: P[][] };
type Check = { state: string; label: string; note: string; point: string };
type Option = { system_id: number | null; option_id: number | null; product_id: number | null; system: string | null; product: string | null; brand: string | null; kind: string; checks: Check[]; meets_all: boolean; picked: boolean; cost: { rate: string | null; unit: string } | null };
type Pick = { id: number; system_id: number | null; option_id: number | null; product_id: number | null; consumption: string | null; label: string };
type Item = { id: number; name: string; spec_text: string | null; excluded_reason: string | null; total_sqm: string; areas: Area[]; options: Option[]; gaps: string[]; picks: Pick[]; chips: { kind: string; label: string }[] };
type Cell = { kind: string; ref: number; value: string | null; changed: boolean; calculated: string | null; by: string | null; at: string | null };
type GridRow = { item: string; pick_id: number; label: string; brand: string | null; line_id: number; unit: string; option: string | null; qty: Cell; rate: string | null; rate_sqm?: string | null; wastage: Cell; labour?: Cell; margin?: Cell; products: { id: number; product: string; unit: string; consumption: Cell; price?: Cell; freight?: Cell }[] };
type Change = { line_id: number | null; item: string; line: string; old_qty: string | null; new_qty: string | null; areas: { added?: string[]; removed?: string[]; resized?: string[] } };
type Run = { id: number; site_id: number; cad_file_id: number; client_id: number | null; unit: string; status: string; quotation_id: number | null; changes: Change[] | null; items: Item[]; open_areas: { id: number; name: string; plan: string | null }[]; excluded: { cad_area_id: number; name: string; reason: string }[]; blockers: string[]; can_cost: boolean; grid?: GridRow[] };
type Client = { id: number; name: string };
type LineAreas = { areas: { key: string; name: string; node_id: number | null; outline: P[] | null; holes: P[][] }[] };
type Model = { nodes: XNode[]; building?: Building | null };

const STATE: Record<string, string> = { yes: "✓", no: "✗", not_stated: "?", approval: "!", equivalent: "≈" };

/** The run's areas in plan (drawing units), the ones behind the picked line lit. */
function Plan({ items, lit }: { items: Item[]; lit: Set<string> }) {
  const areas = items.flatMap((i) => i.areas).filter((a) => a.outline && a.outline.length > 2);
  if (!areas.length) return <p className="muted small">No traced outlines to draw.</p>;
  const pts = areas.flatMap((a) => a.outline as P[]);
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = (x1 - x0 + y1 - y0) * 0.03;
  const d = (poly: P[]) => poly.map((p, i) => `${i ? "L" : "M"}${p[0]},${-p[1]}`).join(" ") + "Z";
  return (
    <svg className="dq-plan" viewBox={`${x0 - pad} ${-y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`} role="img" aria-label="The areas on the drawing">
      {areas.map((a) => (
        <g key={a.id} className={lit.has(a.key) ? "lit" : ""}>
          <path d={d(a.outline as P[])} />
          {(a.holes ?? []).map((h, i) => (
            <path key={i} className="hole" d={d(h)} />
          ))}
          <title>{a.formula}</title>
        </g>
      ))}
    </svg>
  );
}

function CellEdit({ cell, label, run, onRun, can }: { cell: Cell | undefined; label: string; run: Run; onRun: (r: Run) => void; can: boolean }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!cell) return null;
  const send = async (value: string | null) => {
    try {
      onRun(await api<Run>(`/api/drawquote/runs/${run.id}/cells`, { method: "PUT", json: { kind: cell.kind, ref: cell.ref, value } }));
      setV("");
      setErr(null);
    } catch (e) {
      setErr(errorText(e));
    }
  };
  return (
    <span className={cell.changed ? "dq-cell changed" : "dq-cell"} title={cell.changed ? `changed by user${cell.by ? ` (${cell.by})` : ""}${cell.at ? `, ${new Date(cell.at).toLocaleString("en-IN")}` : ""}; calculated ${cell.calculated}` : "calculated"}>
      {can ? (
        <Field label={label} bare>
          <input size={7} value={v || (cell.value ?? "")} onChange={(e) => setV(e.target.value)} onBlur={() => v && v !== cell.value && void send(v)} />
        </Field>
      ) : (
        num(cell.value, 4)
      )}
      {cell.changed && (
        <>
          <em className="small"> changed by user</em>
          {can && (
            <Button size="small" variant="ghost" onClick={() => void send(null)}>
              back to calculated
            </Button>
          )}
        </>
      )}
      {err && <div className="small text-warn">{err}</div>}
    </span>
  );
}

function ItemCard({ run, item, onRun }: { run: Run; item: Item; onRun: (r: Run) => void }) {
  const [spec, setSpec] = useState(item.spec_text ?? "");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ id: number; name: string; unit: string }[]>([]);
  const [consumption, setConsumption] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const picking = run.status === "picking";
  const put = async (body: unknown) => {
    try {
      onRun(await api<Run>(`/api/drawquote/runs/${run.id}/items/${item.id}`, { method: "PUT", json: body }));
      setErr(null);
    } catch (e) {
      setErr(errorText(e));
    }
  };
  const picks = item.picks.map((p) => ({ system_id: p.system_id, option_id: p.option_id, product_id: p.product_id, consumption: p.consumption }));
  const toggle = (o: Option, on: boolean) => {
    const rest = picks.filter((p) => !(p.system_id === o.system_id && p.option_id === o.option_id));
    void put({ picks: on ? [...rest, { system_id: o.system_id, option_id: o.option_id }] : rest });
  };
  useEffect(() => {
    if (q.trim().length < 2) return setHits([]);
    const t = setTimeout(() => api<{ items: { id: number; name: string; unit: string }[] }>(`/api/products?q=${encodeURIComponent(q)}&limit=10`).then((r) => setHits(r.items), () => setHits([])), 250);
    return () => clearTimeout(t);
  }, [q]);
  const sqft = Number(item.total_sqm) * 10.7639;
  return (
    <Card title={`${item.name}: ${num(item.total_sqm, 2)} sqm (${num(sqft, 1)} sq ft)`}>
      {err && <div className="alert alert-error">{err}</div>}
      {item.excluded_reason ? (
        <p className="small">
          Left out: {item.excluded_reason}{" "}
          {picking && (
            <Button size="small" variant="ghost" onClick={() => void put({ excluded_reason: null })}>
              Quote it again
            </Button>
          )}
        </p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table small">
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Floor</th>
                  <th className="num">Floor</th>
                  <th className="num">Cut-outs</th>
                  <th className="num">Upturn</th>
                  <th className="num">Sunk</th>
                  <th className="num">Total sqm</th>
                  <th>How</th>
                </tr>
              </thead>
              <tbody>
                {item.areas.map((a) => (
                  <tr key={a.id}>
                    <td>{a.name}</td>
                    <td>{a.floor ?? "—"}</td>
                    <td className="num">{num(a.floor_sqm, 2)}</td>
                    <td className="num">{Number(a.cutout_sqm) ? num(a.cutout_sqm, 2) : "—"}</td>
                    <td className="num" title={`from ${a.upturn_from}`}>{Number(a.upturn_m) ? `${num(a.upturn_m, 2)} m` : "—"}</td>
                    <td className="num">{Number(a.sunk_m) ? `${num(a.sunk_m, 2)} m` : "—"}</td>
                    <td className="num">
                      <b>{num(a.total_sqm, 2)}</b>
                    </td>
                    <td className="small muted">{a.formula}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">Key points: {item.chips.map((c) => c.label).join(" · ")}</p>
          {picking && (
            <Field label="The client's BOQ or spec line for it (optional: ranks the options by it)">
              <textarea rows={2} value={spec} onChange={(e) => setSpec(e.target.value)} onBlur={() => spec !== (item.spec_text ?? "") && void put({ spec_text: spec })} />
            </Field>
          )}
          {item.gaps.length > 0 && <div className="alert alert-warn small">{item.gaps.join("; ")}</div>}
          <div className="spec-options">
            {item.options
              .filter((o) => o.kind === "option")
              .map((o, i) => (
                <label key={i} className={`spec-option${o.picked ? " picked" : ""}${o.meets_all ? " meets" : ""}`}>
                  <div className="toolbar">
                    <span>
                      <input type="checkbox" checked={o.picked} disabled={!picking} onChange={(e) => toggle(o, e.target.checked)} /> <b>{o.brand ?? "—"}</b>
                    </span>
                    {o.cost?.rate && <span className="small">{inr(o.cost.rate)} / {o.cost.unit}</span>}
                  </div>
                  <div className="small">{o.system}</div>
                  <ul className="spec-checks small">
                    {o.checks.map((c) => (
                      <li key={c.point} className={`spec-${c.state}`}>
                        <span>{STATE[c.state] ?? "?"}</span> {c.label} <span className="muted">· {c.note}</span>
                      </li>
                    ))}
                  </ul>
                </label>
              ))}
          </div>
          {item.picks
            .filter((p) => p.product_id)
            .map((p) => (
              <p key={p.id} className="small">
                Added product: {p.label} at {num(p.consumption, 4)} per sqm{" "}
                {picking && (
                  <Button size="small" variant="ghost" onClick={() => void put({ picks: picks.filter((x) => x.product_id !== p.product_id) })}>
                    remove
                  </Button>
                )}
              </p>
            ))}
          {picking && (
            <div className="form-row">
              <Field label="Add any other product">
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type 2 letters" />
              </Field>
              <Field label="Its consumption per sqm">
                <input size={7} value={consumption} onChange={(e) => setConsumption(e.target.value)} />
              </Field>
              {hits.map((h) => (
                <Button key={h.id} size="small" variant="ghost" disabled={!consumption} onClick={() => { void put({ picks: [...picks, { product_id: h.id, consumption }] }); setQ(""); setConsumption(""); }}>
                  {h.name} ({h.unit})
                </Button>
              ))}
              <Button
                size="small"
                variant="ghost"
                onClick={() => {
                  const why = window.prompt(`Leave ${item.name} out of the quotation: why?`);
                  if (why) void put({ excluded_reason: why });
                }}
              >
                Leave this area type out
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

export default function DrawQuote() {
  const { id } = useParams();
  const siteId = Number(id);
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") ? Number(params.get("run")) : null;
  const [site, setSite] = useState<Site | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [pick, setPick] = useState({ cad_file_id: "", client_id: "", unit: "sqm" });
  const [check, setCheck] = useState<{ plans: { plan: string; areas: number; mapped: number; mapped_sqm: string; plan_sqm: string | null }[]; unmapped_labels: { id: number; name: string; plan: string | null }[]; closed_unused_count: number } | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [lit, setLit] = useState<LineAreas | null>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Site>(`/api/drawquote/sites/${siteId}`).then(
      (s) => {
        setSite(s);
        setPick((p) => ({ ...p, cad_file_id: p.cad_file_id || String(s.files[0]?.cad_file_id ?? ""), client_id: p.client_id || String(s.site.client_id ?? "") }));
      },
      (e) => setError(errorText(e)),
    );
  }, [siteId]);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ items: Client[] }>(`/api/clients?limit=200`).then((r) => setClients(r.items), () => setClients([]));
    api<Model>(`/api/sites/${siteId}/model`).then(setModel, () => setModel(null));
  }, [siteId]);
  useEffect(() => {
    if (runId) api<Run>(`/api/drawquote/runs/${runId}`).then(setRun, (e) => setError(errorText(e)));
    else setRun(null);
  }, [runId]);
  useEffect(() => {
    if (pick.cad_file_id) api<typeof check>(`/api/drawquote/files/${pick.cad_file_id}/check`).then(setCheck, () => setCheck(null));
  }, [pick.cad_file_id]);

  const start = async () => {
    setBusy(true);
    try {
      const r = await api<{ id: number }>(`/api/drawquote/sites/${siteId}/runs`, { method: "POST", json: { cad_file_id: Number(pick.cad_file_id), client_id: pick.client_id ? Number(pick.client_id) : null, unit: pick.unit } });
      setParams({ run: String(r.id) });
      load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const make = async () => {
    if (!run) return;
    setBusy(true);
    try {
      setRun(await api<Run>(`/api/drawquote/runs/${run.id}/make`, { method: "POST" }));
      load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const exclude = async (areaId: number, reason: string | null) => {
    if (!run) return;
    try {
      setRun(await api<Run>(`/api/drawquote/runs/${run.id}/areas/${areaId}/exclude`, { method: "PUT", json: { reason } }));
    } catch (e) {
      setError(errorText(e));
    }
  };
  const showLine = async (lineId: number) => {
    try {
      setLit(await api<LineAreas>(`/api/drawquote/lines/${lineId}/areas`));
    } catch (e) {
      setError(errorText(e));
    }
  };
  const litKeys = useMemo(() => new Set((lit?.areas ?? []).map((a) => a.key)), [lit]);
  const litNode = lit?.areas.find((a) => a.node_id)?.node_id ?? null;

  const picture = async () => {
    if (!model?.building) return;
    const { renderPicture } = await import("../../xray/picture");
    const c = await renderPicture({ building: model.building, nodes: model.nodes }, "real", 1400, 900);
    if (!c) return;
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = `site-${siteId}-3d-cover.png`;
    a.click();
  };

  return (
    <>
      <div className="page-header">
        <h1>Make quotation from drawing{site ? `: ${site.site.name}` : ""}</h1>
        <div className="page-actions">
          <Link to={`/sites/${siteId}?tab=drawings`} className={buttonClass({ variant: "ghost" })}>
            ← Drawings
          </Link>
          {model?.building && (
            <Button onClick={() => void picture()}>3D picture for the cover</Button>
          )}
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      {!run && site && (
        <Card title="The drawing and the client">
          {site.files.length === 0 ? (
            <p className="muted">No drawing of this site has been read for areas yet: read one in the takeoff first.</p>
          ) : (
            <div className="form-row">
              <Field label="Drawing revision">
                <select value={pick.cad_file_id} onChange={(e) => setPick({ ...pick, cad_file_id: e.target.value })}>
                  {site.files.map((f) => (
                    <option key={f.cad_file_id} value={f.cad_file_id}>
                      {f.drawing} R{f.rev_no}: {f.mapped} of {f.areas} areas mapped
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Client">
                <select value={pick.client_id} onChange={(e) => setPick({ ...pick, client_id: e.target.value })}>
                  <option value="">The site's client</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Quote in">
                <select value={pick.unit} onChange={(e) => setPick({ ...pick, unit: e.target.value })}>
                  <option value="sqm">sqm</option>
                  <option value="sqft">sq ft (converted once, × 10.7639)</option>
                </select>
              </Field>
              <Button variant="primary" disabled={busy || !pick.cad_file_id} onClick={() => void start()}>
                Start
              </Button>
            </div>
          )}
          {site.runs.length > 0 && (
            <p className="small">
              Earlier runs:{" "}
              {site.runs.map((r) => (
                <Button key={r.id} size="small" variant="ghost" onClick={() => setParams({ run: String(r.id) })}>
                  #{r.id} {r.status}
                </Button>
              ))}
            </p>
          )}
        </Card>
      )}

      {check && !run && (
        <Card title="Check against the drawing">
          <div className="table-wrap">
            <table className="table small">
              <thead>
                <tr>
                  <th>Plan</th>
                  <th className="num">Areas</th>
                  <th className="num">Mapped</th>
                  <th className="num">Mapped sqm</th>
                  <th className="num">Plan sqm</th>
                </tr>
              </thead>
              <tbody>
                {check.plans.map((p) => (
                  <tr key={p.plan}>
                    <td>{p.plan}</td>
                    <td className="num">{p.areas}</td>
                    <td className="num">{p.mapped}</td>
                    <td className="num">{num(p.mapped_sqm, 2)}</td>
                    <td className="num">{p.plan_sqm ? num(p.plan_sqm, 2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small">
            Labels not mapped: {check.unmapped_labels.map((a) => a.name).join(", ") || "none"}. Closed shapes that are no area and no cut-out: {check.closed_unused_count}.
          </p>
        </Card>
      )}

      {run && (
        <>
          <div className="form-actions" style={{ justifyContent: "flex-start" }}>
            <Button variant="ghost" onClick={() => setParams({})}>
              ← Runs
            </Button>
            {run.status === "picking" ? (
              <Button variant="primary" disabled={busy || run.blockers.length > 0} onClick={() => void make()}>
                Make the quotation
              </Button>
            ) : (
              run.quotation_id && (
                <Link className={buttonClass({ variant: "primary" })} to={`/quotations/${run.quotation_id}`}>
                  Open the draft quotation
                </Link>
              )
            )}
          </div>
          {run.blockers.length > 0 && (
            <div className="alert alert-warn small">
              {run.blockers.map((b) => (
                <div key={b}>{b}</div>
              ))}
            </div>
          )}
          {run.open_areas.length > 0 && run.status === "picking" && (
            <Card title={`Areas not mapped (${run.open_areas.length})`}>
              <p className="small muted">
                Map them in the <Link to={`/sites/${siteId}/takeoff`}>takeoff</Link> (a place and an area type), or leave them out with a reason.
              </p>
              <table className="table small">
                <tbody>
                  {run.open_areas.map((a) => (
                    <tr key={a.id}>
                      <td>{a.name}</td>
                      <td className="muted">{a.plan}</td>
                      <td>
                        <Button
                          size="small"
                          onClick={() => {
                            const why = window.prompt(`Leave ${a.name} out: why?`);
                            if (why) void exclude(a.id, why);
                          }}
                        >
                          Leave out
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          {run.excluded.length > 0 && (
            <p className="small">
              Left out:{" "}
              {run.excluded.map((e) => (
                <span key={e.cad_area_id}>
                  {e.name} ({e.reason}){" "}
                  {run.status === "picking" && (
                    <Button size="small" variant="ghost" onClick={() => void exclude(e.cad_area_id, null)}>
                      take back
                    </Button>
                  )}
                </span>
              ))}
            </p>
          )}
          {run.changes && run.changes.length > 0 && (
            <Card title="What the new drawing revision changed">
              <table className="table small">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Line</th>
                    <th className="num">Old qty</th>
                    <th className="num">New qty</th>
                    <th>Areas</th>
                  </tr>
                </thead>
                <tbody>
                  {run.changes.map((c, i) => (
                    <tr key={i}>
                      <td>{c.item}</td>
                      <td className="small">{c.line}</td>
                      <td className="num">{num(c.old_qty, 3)}</td>
                      <td className="num">{num(c.new_qty, 3)}</td>
                      <td className="small">
                        {[c.areas.added?.length ? `added ${c.areas.added.join(", ")}` : "", c.areas.removed?.length ? `removed ${c.areas.removed.join(", ")}` : "", c.areas.resized?.length ? `resized ${c.areas.resized.join(", ")}` : ""]
                          .filter(Boolean)
                          .join("; ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          {run.items.map((item) => (
            <ItemCard key={item.id} run={run} item={item} onRun={setRun} />
          ))}
          {run.grid && (
            <Card title="Review: quantities, consumption, rates (every cell can be changed)">
              <div className="table-wrap">
                <table className="table small">
                  <thead>
                    <tr>
                      <th>Item / option</th>
                      <th className="num">Qty</th>
                      <th>Product: consumption{run.can_cost ? " · price · freight" : ""}</th>
                      <th className="num">Wastage %</th>
                      {run.can_cost && <th className="num">Labour ₹/sq ft</th>}
                      {run.can_cost && <th className="num">Margin %</th>}
                      <th className="num">Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.grid.map((r) => (
                      <tr key={r.pick_id} className="clickable" onClick={() => void showLine(r.line_id)}>
                        <td>
                          {r.item}
                          {r.option ? ` (option ${r.option})` : ""}
                          <div className="small muted">{r.label}</div>
                        </td>
                        <td className="num" onClick={(e) => e.stopPropagation()}>
                          <CellEdit cell={r.qty} label="Quantity" run={run} onRun={setRun} can />
                          <div className="small muted">{r.unit}</div>
                        </td>
                        <td onClick={(e) => e.stopPropagation()}>
                          {r.products.map((p) => (
                            <div key={p.id} className="small">
                              {p.product}: <CellEdit cell={p.consumption} label={`Consumption of ${p.product}`} run={run} onRun={setRun} can /> {p.unit}/sqm
                              {p.price && (
                                <>
                                  {" "}
                                  · ₹ <CellEdit cell={p.price} label={`Price of ${p.product}`} run={run} onRun={setRun} can={run.can_cost} />
                                </>
                              )}
                              {p.freight && (
                                <>
                                  {" "}
                                  · freight <CellEdit cell={p.freight} label={`Freight of ${p.product}`} run={run} onRun={setRun} can={run.can_cost} />
                                </>
                              )}
                            </div>
                          ))}
                        </td>
                        <td className="num" onClick={(e) => e.stopPropagation()}>
                          <CellEdit cell={r.wastage} label="Wastage" run={run} onRun={setRun} can />
                        </td>
                        {run.can_cost && (
                          <td className="num" onClick={(e) => e.stopPropagation()}>
                            <CellEdit cell={r.labour} label="Labour" run={run} onRun={setRun} can />
                          </td>
                        )}
                        {run.can_cost && (
                          <td className="num" onClick={(e) => e.stopPropagation()}>
                            <CellEdit cell={r.margin} label="Margin" run={run} onRun={setRun} can />
                          </td>
                        )}
                        <td className="num">
                          <b>{inr(r.rate)}</b>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small muted">Click a row to light its areas on the plan and in 3D. The client's files carry no cost and no margin.</p>
            </Card>
          )}
          <div className="dq-views">
            <Card title={lit ? `On the drawing: ${lit.areas.map((a) => a.name).join(", ")}` : "On the drawing"}>
              <Plan items={run.items} lit={litKeys} />
            </Card>
            {model?.building && (
              <Card title="In 3D">
                <Suspense fallback={<div className="skeleton" style={{ height: 360 }} />}>
                  <XrayView site={{ id: siteId, name: site?.site.name ?? "", code: "", progress: 0 }} building={model.building} nodes={model.nodes} compact selected={litNode} />
                </Suspense>
              </Card>
            )}
          </div>
        </>
      )}
    </>
  );
}
