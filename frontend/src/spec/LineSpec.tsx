// A BOQ line's key points and every brand's option that meets them (Prompt 39a). Opened from a tender
// BOQ line and a quotation line. The key points are chips under the description, each showing the
// words it came from; a person edits them (an AI chip is "suggested" until confirmed). The options
// stand side by side: brand, products per step, the BOM per unit and per sq ft, a tick / cross /
// "not stated" per key point, and for those who see cost the material, labour and selling rate. A
// tick builds the line's main item in the rate working from that option; its steps are listed with
// their quantities and can be changed (and set back).
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, downloadFile } from "../api";
import { errorText, inr, num } from "../format";
import { Modal } from "../ui/Overlay";
import { Button, Field } from "../ui/components";

export type Chip = {
  kind: string;
  label: string;
  value: Record<string, unknown>;
  spans: number[][];
  words: string;
  source: "rule" | "ai" | "user";
  confirmed: boolean;
};
type Pick = { rank: number; system_id: number; option_id: number | null; group_id: number | null };
type Points = { line_id: number; description: string; unit: string | null; qty: string | null; chips: Chip[]; kept: boolean; picks: Pick[]; ai_enabled: boolean };
type Check = { point: string; label: string; state: "yes" | "no" | "not_stated" | "approval" | "equivalent"; note: string };
type Row = { product: string; step: string; unit: string; per_unit: string | null; per_unit_label: string | null; per_small: string | null; small_label: string | null; tds_range: { lo: string; hi: string; unit: string } | null; outside_tds?: boolean; doc_id: number | null; wastage_included?: boolean };
type Option = {
  kind: "option" | "product";
  system_id: number | null;
  system: string | null;
  option_id: number | null;
  product: string | null;
  brand: string | null;
  type: string | null;
  rows: Row[];
  checks: Check[];
  meets_all: boolean;
  past_use: number;
  cost: { material: string; labour: string; rate: string | null; rate_small: string | null; unit: string; error?: string } | null;
};
type Options = { options: Option[]; gaps: string[]; considered: number; can_pick: boolean };
type SubRow = { id: number; product: string; unit: string; step: string; consumption: string | null; default_consumption: string | null; source: string | null; wastage_percent: string; qty: string | null; changed: boolean };
type RateChange = { old: string | null; new: string; unit: string; applied: boolean; ask: boolean };
type Subs = { group_id: number; unit: string; line_qty: string | null; qty_in_unit: string | null; rows: SubRow[]; rate?: string | null; note: string | null } | null;

const MARK: Record<Check["state"], string> = { yes: "✓", no: "✗", not_stated: "?", approval: "!", equivalent: "≈" };
const MARK_TITLE: Record<Check["state"], string> = { yes: "meets it", no: "does not meet it", not_stated: "not stated in TDS", approval: "needs client approval", equivalent: "an equivalent (allowed)" };
const KIND_LABEL: Record<string, string> = {
  area: "Area", system: "System", steps: "Steps", coats: "Coats", dft: "DFT", thickness: "Thickness", kg_sqm: "Kg per sqm", mesh: "Mesh",
  upturn: "Upturn", protection: "Protection", property: "Property", make: "Make", potable: "Potable", uv: "UV", pond_test: "Pond test", warranty: "Warranty", unit: "Unit",
};

/** The description with the words of every chip (or only the one pointed at) highlighted. */
function Highlighted({ text, chips, focus }: { text: string; chips: Chip[]; focus: number | null }) {
  const spans = (focus === null ? chips : [chips[focus]]).flatMap((c) => c?.spans ?? []).filter((s) => s.length === 2 && s[0] >= 0 && s[1] > s[0]);
  spans.sort((a, b) => a[0] - b[0]);
  const parts: { t: string; on: boolean }[] = [];
  let at = 0;
  for (const [s, e] of spans) {
    if (s < at) continue;
    if (s > at) parts.push({ t: text.slice(at, s), on: false });
    parts.push({ t: text.slice(s, e), on: true });
    at = e;
  }
  if (at < text.length) parts.push({ t: text.slice(at), on: false });
  return (
    <p className="pre-line small spec-text">
      {parts.map((p, i) => (p.on ? <mark key={i}>{p.t}</mark> : <Fragment key={i}>{p.t}</Fragment>))}
    </p>
  );
}

function ChipEdit({ chip, onSave, onCancel }: { chip: Chip; onSave: (c: Chip) => void; onCancel: () => void }) {
  const [label, setLabel] = useState(chip.label);
  const numeric = Object.entries(chip.value ?? {}).filter(([, v]) => typeof v === "string" || typeof v === "number") as [string, string | number][];
  const [vals, setVals] = useState<Record<string, string>>(Object.fromEntries(numeric.map(([k, v]) => [k, String(v)])));
  return (
    <span className="spec-chip editing">
      <Field label="The key point" bare>
        <input value={label} onChange={(e) => setLabel(e.target.value)} />
      </Field>
      {Object.keys(vals).map((k) => (
        <Field key={k} label={k.replace("_", " ")} inline className="small">
          <input size={6} value={vals[k]} onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} />
        </Field>
      ))}
      <Button size="small" onClick={() => onSave({ ...chip, label, value: { ...chip.value, ...vals }, source: chip.source === "ai" ? "ai" : "user", confirmed: true })}>
        Save
      </Button>
      <Button size="small" variant="ghost" onClick={onCancel}>
        Cancel
      </Button>
    </span>
  );
}

export default function LineSpec({ kind, lineId, canEdit, onClose, onPicked }: { kind: "boq" | "quotation"; lineId: number; canEdit: boolean; onClose: () => void; onPicked?: () => void }) {
  const base = `/api/spec/lines/${kind}/${lineId}`;
  const [points, setPoints] = useState<Points | null>(null);
  const [opts, setOpts] = useState<Options | null>(null);
  const [subs, setSubs] = useState<Subs>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [note, setNote] = useState<string | null>(null);

  const loadOptions = useCallback(() => {
    api<Options>(`${base}/options`).then(setOpts, (e) => setError(errorText(e)));
    api<{ sub_lines: Subs }>(`${base}/sub-lines`).then((r) => setSubs(r.sub_lines), () => setSubs(null));
  }, [base]);
  useEffect(() => {
    api<Points>(`${base}/points`).then(setPoints, (e) => setError(errorText(e)));
    loadOptions();
  }, [base, loadOptions]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const saveChips = (chips: Chip[]) =>
    run(async () => {
      setPoints(await api<Points>(`${base}/points`, { method: "PUT", json: { chips } }));
      setEditing(null);
      setAdding(false);
      loadOptions();
    });
  // a line with no rate gets the picked option's selling rate at once; one with a rate is asked
  // first, old against new ("Rates to the lines" on the rate working stays as it is)
  const pick = (o: Option, rank: number) =>
    run(async () => {
      const r = await api<Points & { sub_lines: Subs; rate: RateChange | null }>(`${base}/pick`, { method: "POST", json: { system_id: o.system_id, option_id: o.option_id, rank } });
      setPoints(r);
      if (rank === 1) setSubs(r.sub_lines);
      if (r.rate?.applied) setNote(`The line's rate is now ${inr(r.rate.new)} per ${r.rate.unit}.`);
      else if (r.rate?.ask) {
        const yes = window.confirm(`The line's rate is ${inr(r.rate.old)} per ${r.rate.unit}; the picked option gives ${inr(r.rate.new)}. Change the line's rate to ${inr(r.rate.new)}?`);
        if (yes) {
          await api(`${base}/apply-rate`, { method: "POST" });
          setNote(`The line's rate changed from ${inr(r.rate.old)} to ${inr(r.rate.new)} per ${r.rate.unit}.`);
        } else setNote(`The line keeps its rate of ${inr(r.rate.old)}; the rate working has the picked option.`);
      } else setNote(null);
      onPicked?.();
    });
  const setSub = (id: number, consumption: string | null) =>
    run(async () => {
      const r = await api<{ sub_lines: Subs }>(`${base}/sub-lines/${id}`, { method: "PUT", json: { consumption } });
      setSubs(r.sub_lines);
      setTyped((t) => ({ ...t, [id]: "" }));
      onPicked?.();
    });

  const first = points?.picks.find((p) => p.rank === 1);
  const second = points?.picks.find((p) => p.rank === 2);
  const isPick = (o: Option, p?: Pick) => !!p && p.system_id === o.system_id && (p.option_id ?? null) === (o.option_id ?? null);

  return (
    <Modal title="Key points and options" onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      {!points && <p className="muted">Reading the line…</p>}
      {points && (
        <>
          <Highlighted text={points.description} chips={points.chips} focus={focus} />
          <div className="spec-chips" aria-label="Key points">
            {points.chips.map((c, i) =>
              editing === i ? (
                <ChipEdit key={i} chip={c} onCancel={() => setEditing(null)} onSave={(n) => void saveChips(points.chips.map((x, j) => (j === i ? n : x)))} />
              ) : (
                <span
                  key={i}
                  className={`spec-chip${c.source === "ai" && !c.confirmed ? " suggested" : ""}${c.source === "user" ? " typed" : ""}`}
                  onMouseEnter={() => setFocus(i)}
                  onMouseLeave={() => setFocus(null)}
                  title={c.words ? `From: ${c.words}` : "Not in the words"}
                >
                  <b>{KIND_LABEL[c.kind] ?? c.kind}:</b> {c.label}
                  {c.source === "ai" && !c.confirmed && <em className="small"> suggested by AI</em>}
                  {c.source === "user" && <em className="small"> changed by user</em>}
                  {canEdit && (
                    <>
                      {c.source === "ai" && !c.confirmed && (
                        <Button size="small" variant="ghost" onClick={() => void saveChips(points.chips.map((x, j) => (j === i ? { ...x, confirmed: true } : x)))}>
                          Confirm
                        </Button>
                      )}
                      <Button size="small" variant="ghost" aria-label={`Edit ${c.label}`} onClick={() => setEditing(i)}>
                        ✎
                      </Button>
                      <Button size="small" variant="ghost" aria-label={`Remove ${c.label}`} onClick={() => void saveChips(points.chips.filter((_, j) => j !== i))}>
                        ×
                      </Button>
                    </>
                  )}
                </span>
              ),
            )}
            {canEdit && adding && (
              <ChipEdit
                chip={{ kind: "property", label: "", value: {}, spans: [], words: "", source: "user", confirmed: true }}
                onCancel={() => setAdding(false)}
                onSave={(n) => void saveChips([...points.chips, n])}
              />
            )}
          </div>
          {canEdit && (
            <div className="form-actions" style={{ justifyContent: "flex-start" }}>
              <Button size="small" onClick={() => setAdding(true)} disabled={busy}>
                Add a key point
              </Button>
              {points.kept && (
                <Button size="small" variant="ghost" disabled={busy} onClick={() => void run(async () => { setPoints(await api<Points>(`${base}/points/reset`, { method: "POST" })); loadOptions(); })}>
                  Back to the words
                </Button>
              )}
              {points.ai_enabled && (
                <Button size="small" variant="ghost" disabled={busy} onClick={() => void run(async () => { setPoints(await api<Points>(`${base}/points/ai`, { method: "POST" })); })}>
                  Ask the AI what the rules missed
                </Button>
              )}
            </div>
          )}
        </>
      )}

      <h3 className="section-title top-gap">Options of every brand</h3>
      {!opts && <p className="muted small">Ranking the options…</p>}
      {opts && opts.gaps.length > 0 && (
        <div className="alert alert-warn small">
          {opts.gaps.map((g) => (
            <div key={g}>{g}</div>
          ))}
          {opts.options.length > 0 && <div>The closest options are shown with the gap marked ✗.</div>}
        </div>
      )}
      {opts && opts.options.length === 0 && <p className="muted small">No work item in the consumption master fits this line.</p>}
      {opts && opts.options.length > 0 && (
        <div className="spec-options">
          {opts.options.map((o, i) => (
            <div key={i} className={`spec-option${o.meets_all ? " meets" : ""}${isPick(o, first) ? " picked" : ""}`}>
              <div className="toolbar">
                <b>{o.brand ?? "—"}</b>
                <span className="muted small">{o.kind === "product" ? "TDS only, no BOM yet" : o.system}</span>
              </div>
              {o.type && <div className="small muted">{o.type}{o.past_use ? ` · used ${o.past_use}×` : ""}</div>}
              <table className="table compact small">
                <tbody>
                  {o.rows.map((r, j) => (
                    <tr key={j}>
                      <td className="muted">{r.step}</td>
                      <td>
                        {r.product}
                        {r.doc_id && (
                          <Button size="small" variant="ghost" aria-label={`TDS of ${r.product}`} onClick={() => void downloadFile(`/api/spec/tds/docs/${r.doc_id}/file`)}>
                            TDS
                          </Button>
                        )}
                        {r.outside_tds && <span className="small text-warn"> outside TDS</span>}
                      </td>
                      <td className="num nowrap">
                        {r.per_unit !== null ? `${num(r.per_unit, 3)} /${r.per_unit_label}` : r.tds_range ? `TDS ${num(r.tds_range.lo, 2)}–${num(r.tds_range.hi, 2)}` : "—"}
                        {r.per_small !== null && <div className="muted">{num(r.per_small, 4)} /{r.small_label}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="spec-checks small">
                {o.checks.map((c) => (
                  <li key={c.point} className={`spec-${c.state}`} title={MARK_TITLE[c.state]}>
                    <span aria-label={MARK_TITLE[c.state]}>{MARK[c.state]}</span> {c.label} <span className="muted">· {c.note}</span>
                  </li>
                ))}
              </ul>
              {o.cost && (
                <dl className="totals small">
                  {o.cost.error ? (
                    <>
                      <dt>Rate</dt>
                      <dd className="text-warn">{o.cost.error}</dd>
                    </>
                  ) : (
                    <>
                      <dt>Material / labour</dt>
                      <dd>
                        {inr(o.cost.material)} / {inr(o.cost.labour)} per {o.cost.unit}
                      </dd>
                      <dt>Selling rate</dt>
                      <dd>
                        <b>{inr(o.cost.rate)}</b> per {o.cost.unit}
                        {o.cost.rate_small && <span className="muted"> ({inr(o.cost.rate_small)} per {o.cost.unit === "rmt" ? "rft" : "sq ft"})</span>}
                      </dd>
                    </>
                  )}
                </dl>
              )}
              {opts.can_pick && canEdit && o.kind === "option" && (
                <div className="form-actions" style={{ justifyContent: "flex-start" }}>
                  <Button size="small" variant={isPick(o, first) ? "primary" : "secondary"} disabled={busy} onClick={() => void pick(o, 1)}>
                    {isPick(o, first) ? "Picked ✓" : "Pick"}
                  </Button>
                  <Button size="small" variant="ghost" disabled={busy || isPick(o, first)} onClick={() => void pick(o, 2)}>
                    {isPick(o, second) ? "Alternate ✓" : "As alternate"}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {note && <div className="alert alert-ok small top-gap">{note}</div>}
      {subs && (
        <>
          <h3 className="section-title top-gap">The picked option's steps</h3>
          <p className="small muted">
            For the line's {num(subs.line_qty, 3)} ({num(subs.qty_in_unit, 3)} {subs.unit}); the rate working's main item is built from it.{subs.note ? ` ${subs.note}` : ""}
            {subs.rate ? ` Rate ${inr(subs.rate)} per ${subs.unit}.` : ""}
          </p>
          <div className="table-wrap">
            <table className="table small">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Product</th>
                  <th className="num">Per {subs.unit}</th>
                  <th className="num">Wastage %</th>
                  <th className="num">Qty</th>
                  <th>Where from</th>
                  {opts?.can_pick && canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {subs.rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.step}</td>
                    <td>{r.product}</td>
                    <td className="num">
                      {opts?.can_pick && canEdit ? (
                        <Field label={`Consumption of ${r.product}`} bare>
                          <input
                            size={7}
                            value={typed[r.id] || (r.consumption ?? "")}
                            onChange={(e) => setTyped((t) => ({ ...t, [r.id]: e.target.value }))}
                            onBlur={() => typed[r.id] && typed[r.id] !== r.consumption && void setSub(r.id, typed[r.id])}
                          />
                        </Field>
                      ) : (
                        num(r.consumption, 4)
                      )}
                      {r.changed && <div className="small text-warn">changed by user (was {num(r.default_consumption, 4)})</div>}
                    </td>
                    <td className="num">{num(r.wastage_percent, 2)}</td>
                    <td className="num nowrap">
                      {num(r.qty, 3)} {r.unit}
                    </td>
                    <td className="small muted">{r.source}</td>
                    {opts?.can_pick && canEdit && (
                      <td>
                        {r.changed && (
                          <Button size="small" variant="ghost" disabled={busy} onClick={() => void setSub(r.id, null)}>
                            Back to calculated
                          </Button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}
