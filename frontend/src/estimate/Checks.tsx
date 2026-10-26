// The checks before a BOQ, a quotation or a method statement is sent: coverage written outside the
// library's range, T&C wording that gives free-issue materials away; and the margin check of a rate
// working against the BOQ rate (material share of the rate, margin on the selling price).
import { Fragment, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { errorText, inr, num } from "../format";
import { Button, Card, EmptyState, Field } from "../ui/components";
import { E } from "./common";
import type { Checks as ChecksOut, Finding } from "./common";
import "./estimate.css";

type Of = { tenderId?: number; quotationId?: number; methodologyId?: number };

function query({ tenderId, quotationId, methodologyId }: Of): string {
  if (tenderId) return `tender_id=${tenderId}`;
  if (quotationId) return `quotation_id=${quotationId}`;
  return `methodology_id=${methodologyId}`;
}

/** One T&C finding: the clause as written, and as it should read. */
function TermFinding({ f, action }: { f: Finding; action?: React.ReactNode }) {
  return (
    <div className="alert alert-warn">
      <strong>{f.warning}</strong>
      <div className="small">
        <span className="muted">Says:</span> {f.text}
      </div>
      <div className="small">
        <span className="muted">Should read:</span> <strong>{f.corrected}</strong>
      </div>
      {action}
    </div>
  );
}

/** The coverage and T&C checks of a tender, a quotation or a method statement. `quiet`: nothing shown when all is right. */
export function Checks({ quiet, ...of }: Of & { quiet?: boolean }) {
  const [out, setOut] = useState<ChecksOut | null>(null);
  const [error, setError] = useState("");
  const q = query(of);
  useEffect(() => {
    api<ChecksOut>(`${E}/checks?${q}`).then(setOut, (e) => setError(errorText(e)));
  }, [q]);
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!out) return null;
  const none = out.coverage.length === 0 && out.terms.length === 0;
  if (none && quiet) return null;
  return (
    <Card title="Checks before it is sent" size="small">
      {none && <div className="alert alert-ok">No coverage outside the material library and no T&C wording to correct.</div>}
      {out.coverage.length > 0 && (
        <div className="alert alert-warn">
          <strong>Coverage outside the material library ({out.coverage.length})</strong>
          <ul>
            {out.coverage.map((w, i) => (
              <li key={i}>{w.warning}</li>
            ))}
          </ul>
        </div>
      )}
      {out.terms.map((f, i) => (
        <TermFinding key={i} f={f} />
      ))}
    </Card>
  );
}

/** The T&C library's clauses that say we supply materials free, each with its corrected text. */
export function TermsLibraryFindings({ onFixed }: { onFixed?: () => void }) {
  const { can } = useAuth();
  const [rows, setRows] = useState<Finding[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  useEffect(() => {
    api<Finding[]>(`${E}/terms/library`).then(setRows, () => setRows([]));
  }, []);
  const fix = async (clauseId: number) => {
    setBusy(clauseId);
    try {
      setRows(await api<Finding[]>(`${E}/terms/fix`, { method: "POST", json: { clause_id: clauseId } }));
      onFixed?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };
  if (!rows || rows.length === 0) return error ? <div className="alert alert-error">{error}</div> : null;
  return (
    <Card title={`Clauses that give free-issue materials away (${rows.length})`} size="small">
      <p className="small muted">The client supplies cement, sand, water and the like free of cost; a clause saying we supply them free gives them away in writing.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {rows.map((f) => (
        <TermFinding
          key={f.clause_id}
          f={f}
          action={
            can("tc.edit") &&
            f.clause_id && (
              <Button size="small" variant="primary" loading={busy === f.clause_id} onClick={() => void fix(f.clause_id!)}>
                Use the corrected text
              </Button>
            )
          }
        />
      ))}
    </Card>
  );
}

// --- the margin check ----------------------------------------------------------------------------

type MarginMaterial = { product: string; coverage: string; per_sqm: string; wastage_percent: string; price: string; cost_sqm: string; how: string };

type MarginLine = {
  group_id: number;
  group: string;
  item: string;
  description: string;
  unit: string | null;
  rate: string | null;
  rate_sqm: string | null;
  material_sqm: string;
  labour_sqm: string | null;
  surface_prep_sqm: string;
  cost_sqm?: string;
  material_share_percent?: string;
  margin_percent?: string;
  materials: MarginMaterial[];
  no_coverage: string[];
  no_price: string[];
  free_issue: string[];
  warnings: string[];
};

type Margin = { working_id: number; share_limit_percent: string; basis: string; lines: MarginLine[]; free_issue: string[]; free_issue_ids: number[]; free_issue_clause: string | null; products?: { id: number; name: string }[] };

type Settings = { material_share_warn_percent: string; can_edit: boolean };

/** Per BOQ line: rate, material, labour, cost per sqm, the material share of the rate and the margin. */
export function MarginCheck({ tenderId, quotationId }: { tenderId?: number; quotationId?: number }) {
  const [m, setM] = useState<Margin | null>(null);
  const [none, setNone] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = tenderId ? `tender_id=${tenderId}` : `quotation_id=${quotationId}`;
  const load = () =>
    api<Margin>(`${E}/margin?${q}`).then(setM, (e) => {
      if (e instanceof ApiError && e.status === 404) setNone(true);
      else setError(errorText(e));
    });
  useEffect(() => {
    void load();
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  if (none) return quotationId ? null : <EmptyState title="No rate working yet" hint="Work the rates (Rate working) and the margin check reads them." />;
  if (error) return <div className="alert alert-error">{error}</div>;
  if (!m) return null;
  const limit = Number(m.share_limit_percent);
  return (
    <Card title="Margin check" actions={<ShareSetting onSaved={() => void load()} />}>
      <p className="small muted">
        Material per sqm from the library: coverage × (1 + wastage) × price (freight in). Margin on the selling price: (rate − cost) ÷ rate. Material over {num(limit, 1)}% of the
        rate is flagged.
      </p>
      {m.lines.length === 0 ? (
        <EmptyState title="No line in the working" />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th style={{ minWidth: 220 }}>Item</th>
                <th className="num">Rate / sqm</th>
                <th className="num">Material / sqm</th>
                <th className="num">Labour / sqm</th>
                <th className="num">Cost / sqm</th>
                <th className="num">Material share</th>
                <th className="num">Margin</th>
                <th>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {m.lines.map((ln, i) => {
                const key = `${ln.group_id}-${ln.item}-${i}`;
                const over = ln.material_share_percent !== undefined && Number(ln.material_share_percent) > limit;
                return (
                  <Fragment key={key}>
                    <tr className={over ? "row-flagged" : undefined}>
                      <td>
                        <strong>{ln.item}</strong> <span className="small">{ln.description}</span>
                        <div className="small muted">{ln.group}</div>
                      </td>
                      <td className="num">{inr(ln.rate_sqm)}</td>
                      <td className="num">
                        <Button size="small" variant="ghost" aria-expanded={open === key} onClick={() => setOpen(open === key ? null : key)}>
                          {inr(ln.material_sqm)}
                        </Button>
                      </td>
                      <td className="num">{inr(ln.labour_sqm)}</td>
                      <td className="num">{inr(ln.cost_sqm)}</td>
                      <td className={`num ${over ? "text-danger" : ""}`}>{ln.material_share_percent !== undefined ? `${num(ln.material_share_percent, 1)}%` : "—"}</td>
                      <td className={`num ${Number(ln.margin_percent) < 0 ? "text-danger" : ""}`}>
                        <strong>{ln.margin_percent !== undefined ? `${num(ln.margin_percent, 1)}%` : "—"}</strong>
                      </td>
                      <td className="small">
                        {ln.warnings.map((w, j) => (
                          <div key={j} className={w.startsWith("Material alone") ? "text-danger" : undefined}>
                            {w}
                          </div>
                        ))}
                      </td>
                    </tr>
                    {open === key && (
                      <tr className="margin-materials">
                        <td colSpan={8}>
                          {ln.materials.length > 0 && (
                            <table className="table">
                              <thead>
                                <tr>
                                  <th>Product</th>
                                  <th>Coverage</th>
                                  <th className="num">Wastage</th>
                                  <th className="num">Price</th>
                                  <th className="num">Cost / sqm</th>
                                  <th>How</th>
                                </tr>
                              </thead>
                              <tbody>
                                {ln.materials.map((x) => (
                                  <tr key={x.product}>
                                    <td>{x.product}</td>
                                    <td className="small">{x.coverage}</td>
                                    <td className="num">{num(x.wastage_percent, 2)}%</td>
                                    <td className="num">{inr(x.price)}</td>
                                    <td className="num">{inr(x.cost_sqm)}</td>
                                    <td className="small">
                                      {num(x.per_sqm, 4)}/sqm × (1 + {num(x.wastage_percent, 2)}%) × {inr(x.price)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                          {ln.free_issue.length > 0 && <p className="small">Free issue (client supplies, not in our cost): {ln.free_issue.join(", ")}</p>}
                          {ln.no_coverage.length > 0 && <p className="small text-danger">No coverage in the library: {ln.no_coverage.join(", ")}</p>}
                          {ln.no_price.length > 0 && <p className="small text-danger">No price: {ln.no_price.join(", ")}</p>}
                          {Number(ln.surface_prep_sqm) > 0 && <p className="small">Surface preparation {inr(ln.surface_prep_sqm)}/sqm is in the cost.</p>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <FreeIssue m={m} tenderId={tenderId} quotationId={quotationId} onSaved={setM} />
    </Card>
  );
}

/** The products the client supplies free: out of our cost, and the T&C clause written for them. */
function FreeIssue({ m, tenderId, quotationId, onSaved }: { m: Margin; tenderId?: number; quotationId?: number; onSaved: (m: Margin) => void }) {
  const [picked, setPicked] = useState<number[]>(m.free_issue_ids);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setPicked(m.free_issue_ids), [m.free_issue_ids]);
  // every product of the working, with a coverage in the library or not
  const choices = m.products ?? [];
  const changed = [...picked].sort().join() !== [...m.free_issue_ids].sort().join();
  const save = async () => {
    setBusy(true);
    try {
      onSaved(await api<Margin>(`${E}/margin/free-issue`, { method: "PUT", json: { tender_id: tenderId ?? null, quotation_id: quotationId ?? null, product_ids: picked } }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card as="div" size="small" title="Free issue (the client supplies)">
      {choices.length === 0 ? (
        <p className="small muted">The working has no products yet.</p>
      ) : (
        <div role="group" aria-label="Supplied by the client free of cost">
          <p className="small muted">Supplied by the client free of cost:</p>
          <div className="est-area-picks">
          {choices.map((p) => (
            <label key={p.id} className="check">
              <input type="checkbox" checked={picked.includes(p.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, p.id] : picked.filter((x) => x !== p.id))} /> {p.name}
            </label>
          ))}
          </div>
        </div>
      )}
      <p className="small">
        <span className="muted">The T&C clause it writes:</span> {m.free_issue_clause ?? <span className="muted">none (no free-issue product)</span>}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {changed && (
        <Button variant="primary" size="small" loading={busy} onClick={() => void save()}>
          Save the free issue and its clause
        </Button>
      )}
    </Card>
  );
}

/** The director's share: material over this % of the rate is flagged. */
function ShareSetting({ onSaved }: { onSaved: () => void }) {
  const [s, setS] = useState<Settings | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api<Settings>(`${E}/margin/settings`).then(
      (r) => (setS(r), setValue(String(Number(r.material_share_warn_percent)))),
      () => setS(null),
    );
  }, []);
  if (!s) return null;
  if (!s.can_edit) return <span className="small muted">Material share limit {num(s.material_share_warn_percent, 1)}% (set by the director)</span>;
  const save = async () => {
    try {
      const r = await api<Settings>(`${E}/margin/settings`, { method: "PUT", json: { material_share_warn_percent: value } });
      setS(r);
      setError("");
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <>
      <Field label="Material share limit %" inline error={error}>
        <input className="input-narrow" type="number" min="1" max="100" step="any" value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      {Number(value) !== Number(s.material_share_warn_percent) && (
        <Button size="small" variant="primary" onClick={() => void save()}>
          Save
        </Button>
      )}
      {error && <span className="small text-danger">{error}</span>}
    </>
  );
}
