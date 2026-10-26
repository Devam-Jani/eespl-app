// Bills from site slips, the site's bill register, a bill's revisions and its material check.
// A slip is the client's notebook page (photo or PDF) in feet and inches, signed and dated by their
// person on site: its lines are entered as written, mapped to the order's items; what is not
// mapped or not billed stays listed. The register lists every RA bill in order beside the old
// Excel register; revisions keep each version of a bill, one sent to the client.
import { useCallback, useEffect, useState } from "react";
import { api, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import { errorText, inr, num } from "../format";
import { Button, Card, EmptyState, Field } from "../ui/components";
import { Modal } from "../ui/Overlay";

type ItemRef = { wo_line_id: number; item_no: string | null; description: string; unit: string | null };
export type SlipInfo = {
  name: string | null; on: string | null; signed_by: string | null; signed_on: string | null; has_file: boolean;
  unbilled: { line_id: number; particulars: string; typed: Record<string, string | null> | null; why: string; variation: { id: number; status: string } | null }[];
  variations?: Variation[];
}; // prettier-ignore
export type Variation = {
  id: number; sheet_id: number; line_id: number | null; particulars: string; description: string; unit: string; rate: string; status: string;
  decided_at: string | null; decision_note: string | null; wo_line_id: number | null; ra_bill_id: number | null; site?: string; site_id?: number; sheet_code?: string | null;
}; // prettier-ignore

/** Billing proposes a new item or variation for a slip line no work-order item covers. */
function AskVariation({ sheetId, line, onClose, onDone }: { sheetId: number; line: SlipInfo["unbilled"][number]; onClose: () => void; onDone: (s: unknown) => void }) {
  const [description, setDescription] = useState(line.particulars);
  const [unit, setUnit] = useState("nos");
  const [rate, setRate] = useState("");
  const [err, setErr] = useState("");
  async function save() {
    try {
      onDone(await api(`/api/measure/sheets/${sheetId}/slip-lines/${line.line_id}/variation`, { method: "POST", json: { description, unit, rate } }));
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title="Ask for a new item / variation" onClose={onClose}>
      <p className="muted">
        &ldquo;{line.particulars}&rdquo; has no work-order item. The director approves the new item; it then joins the work order as a variation, the line is billed
        with this sheet and goes to the client with the bill. Until then it stays listed as unbilled.
      </p>
      <Field label="Description of the new item">
        <input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Unit" hint="nos, rft, rmt, sqft or sqm: the slip line is worked out in it">
        <input value={unit} onChange={(e) => setUnit(e.target.value)} />
      </Field>
      <Field label="Rate (₹ per unit)">
        <input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
      </Field>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={!description.trim() || !unit.trim() || !(Number(rate) > 0)}>
          Send to the director
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

/** A new bill from a slip: its file, its date, who signed it (their role) and when. */
export function SlipNew({ siteId, onClose, onDone }: { siteId: number; onClose: () => void; onDone: (id: number) => Promise<void> }) {
  const today = new Date().toISOString().slice(0, 10);
  const [file, setFile] = useState<File | null>(null);
  const [slipOn, setSlipOn] = useState(today);
  const [signedBy, setSignedBy] = useState("Client's site engineer");
  const [signedOn, setSignedOn] = useState(today);
  const [on, setOn] = useState(today);
  const [title, setTitle] = useState("");
  const [err, setErr] = useState("");
  async function save() {
    const form = new FormData();
    form.set("measured_on", on);
    form.set("signed_by", signedBy);
    form.set("signed_on", signedOn);
    form.set("slip_on", slipOn);
    if (title) form.set("title", title);
    if (file) form.set("file", file);
    try {
      const s = await api<{ id: number }>(`/api/measure/sites/${siteId}/slips`, { method: "POST", form });
      await onDone(s.id);
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title="Bill from a site slip" onClose={onClose}>
      <p className="muted">The client's slip (notebook page) as a photo or PDF; its lines are entered next, as written.</p>
      <Field label="The slip (photo or PDF)">
        <input type="file" accept="image/*,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Field label="What it is for">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Staff quarters: bituminous belt tape" />
      </Field>
      <Field label="Date on the slip">
        <input type="date" value={slipOn} onChange={(e) => setSlipOn(e.target.value)} />
      </Field>
      <Field label="Signed by (their role)" hint="A role, never a name: the client's site engineer, project manager …">
        <input value={signedBy} onChange={(e) => setSignedBy(e.target.value)} />
      </Field>
      <Field label="Signed on">
        <input type="date" value={signedOn} onChange={(e) => setSignedOn(e.target.value)} />
      </Field>
      <Field label="Measured on (the sheet's date)">
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={!signedBy.trim()}>
          Start the slip bill
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

/** The slip beside its lines: the picture, who signed it, a line entered as written, what is not billed. */
export function SlipPanel({ sheetId, slip, items, draft, onChanged }: { sheetId: number; slip: SlipInfo; items: ItemRef[]; draft: boolean; onChanged: (s: unknown) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [pdf, setPdf] = useState(false);
  const [p, setP] = useState("");
  const [no, setNo] = useState("1");
  const [length, setLength] = useState("");
  const [width, setWidth] = useState("");
  const [item, setItem] = useState<number | "">("");
  const [billed, setBilled] = useState(true);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [asking, setAsking] = useState<SlipInfo["unbilled"][number] | null>(null);
  const { can } = useAuth();
  useEffect(() => {
    if (!slip.has_file) return;
    let gone = false;
    let made: string | null = null;
    setPdf((slip.name ?? "").toLowerCase().endsWith(".pdf"));
    void fetchObjectUrl(`/api/measure/sheets/${sheetId}/slip`).then((u) => {
      made = u;
      if (!gone) setUrl(u);
    });
    return () => {
      gone = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [sheetId, slip.has_file, slip.name]);
  async function add() {
    try {
      const out = await api(`/api/measure/sheets/${sheetId}/slip-lines`, {
        method: "POST",
        json: { particulars: p, no, length: length || null, width: width || null, wo_line_id: item === "" ? null : item, billed, reason: billed ? null : reason || null },
      });
      setP("");
      setLength("");
      setWidth("");
      setNo("1");
      setErr("");
      onChanged(out);
    } catch (e) {
      setErr(errorText(e));
    }
  }
  const unit = items.find((i) => i.wo_line_id === item)?.unit ?? "";
  return (
    <div className="m-slip">
      <div className="m-slip-pic">
        {url && !pdf && <img src={url} alt={`The slip of ${slip.on ?? ""}, as scanned`} />}
        {url && pdf && <iframe src={url} title="The slip, as scanned" />}
        {!slip.has_file && <EmptyState title="No slip attached" hint="Attach the slip's photo or PDF: it is the client's signed approval." />}
        <p className="m-why">
          Slip of {slip.on ?? "—"} · signed by {slip.signed_by ?? "—"} on {slip.signed_on ?? "—"}
          {slip.name && (
            <>
              {" · "}
              <button type="button" className="link-button" onClick={() => downloadFile(`/api/measure/sheets/${sheetId}/slip`)}>
                {slip.name}
              </button>
            </>
          )}
        </p>
      </div>
      <div className="m-slip-form">
        {draft && (
          <>
            <h3>A line, as written on the slip</h3>
            <Field label="What">
              <input value={p} onChange={(e) => setP(e.target.value)} placeholder="Front side vertical" />
            </Field>
            <div className="m-slip-sizes">
              <Field label="No">
                <input inputMode="decimal" value={no} onChange={(e) => setNo(e.target.value)} />
              </Field>
              <Field label="Length" hint={`16'0", 116'9", or 13.83 ft`}>
                <input value={length} onChange={(e) => setLength(e.target.value)} />
              </Field>
              <Field label="Width / height">
                <input value={width} onChange={(e) => setWidth(e.target.value)} />
              </Field>
            </div>
            <Field label="Work-order item" hint={unit ? `Worked out in ${unit} (feet to metres with 3.2808)` : "No item: the line stays listed, not billed"}>
              <select value={item} onChange={(e) => setItem(e.target.value ? Number(e.target.value) : "")}>
                <option value="">— not mapped to an item —</option>
                {items.map((i) => (
                  <option key={i.wo_line_id} value={i.wo_line_id}>
                    {i.item_no} {i.description.slice(0, 60)} ({i.unit})
                  </option>
                ))}
              </select>
            </Field>
            <label className="check">
              <input type="checkbox" checked={billed} onChange={(e) => setBilled(e.target.checked)} /> Bill this line
            </label>
            {!billed && (
              <Field label="Why it is left out">
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
            )}
            {err && <div className="alert alert-error">{err}</div>}
            <Button variant="primary" type="button" onClick={add} disabled={!p.trim()}>
              Add the line
            </Button>
          </>
        )}
        <h3>On the slip, not billed ({slip.unbilled.length})</h3>
        {slip.unbilled.length ? (
          <ul className="m-skipped">
            {slip.unbilled.map((u) => (
              <li key={u.line_id}>
                {u.particulars}
                {u.typed?.no ? ` (${u.typed.no}${u.typed.length ? ` × ${u.typed.length}` : ""}${u.typed.width ? ` × ${u.typed.width}` : ""})` : ""}: {u.why}
                {u.why.startsWith("not mapped") && (!u.variation || u.variation.status === "rejected") && can("variation.request") && (
                  <>
                    {" "}
                    <Button size="small" variant="secondary" type="button" onClick={() => setAsking(u)}>
                      Ask for a new item / variation
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Every line of the slip is billed.</p>
        )}
        {(slip.variations ?? []).length > 0 && (
          <>
            <h3>Variations asked</h3>
            <ul className="m-skipped">
              {(slip.variations ?? []).map((v) => (
                <li key={v.id}>
                  <span className={`chip chip-${v.status === "approved" ? "done" : v.status === "rejected" ? "block" : "hold"}`}>{v.status}</span> {v.description}, {v.unit} at{" "}
                  {inr(v.rate)}
                  {v.decision_note ? `: ${v.decision_note}` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      {asking && (
        <AskVariation
          sheetId={sheetId}
          line={asking}
          onClose={() => setAsking(null)}
          onDone={(s) => {
            setAsking(null);
            onChanged(s);
          }}
        />
      )}
    </div>
  );
}

/** The director's list of variations asked from slips: approve (it joins the work order) or not, with why. */
export function VariationsPage() {
  const [rows, setRows] = useState<Variation[] | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const { can } = useAuth();
  const load = useCallback(() => api<Variation[]>("/api/measure/variations").then(setRows, (e) => setErr(errorText(e))), []);
  useEffect(() => void load(), [load]);
  async function decide(v: Variation, approve: boolean) {
    try {
      const out = await api<{ done: string[] }>(`/api/measure/variations/${v.id}/decide`, { method: "POST", json: { approve, note: notes[v.id] || null } });
      setMsg(out.done.join(". "));
      setErr("");
      await load();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <div className="page">
      <div className="page-head">
        <h1>Variations</h1>
      </div>
      <p className="muted">Slip lines no work-order item covers, proposed by billing as a new item. Approved, they join the work order and are billed with their sheet.</p>
      {msg && <div className="alert alert-success">{msg}</div>}
      {err && <div className="alert alert-error">{err}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No variations asked" hint="Billing asks for one from a slip line that has no work-order item." />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Site / sheet</th>
                <th>On the slip</th>
                <th>Proposed item</th>
                <th className="num">Rate</th>
                <th>Status</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.id}>
                  <td>
                    {v.site}
                    <div className="muted small">{v.sheet_code}</div>
                  </td>
                  <td>{v.particulars}</td>
                  <td>
                    {v.description} ({v.unit})
                  </td>
                  <td className="num">{inr(v.rate)}</td>
                  <td>
                    <span className={`chip chip-${v.status === "approved" ? "done" : v.status === "rejected" ? "block" : "hold"}`}>{v.status}</span>
                  </td>
                  <td>
                    {v.status === "proposed" && can("variation.approve") ? (
                      <div className="row-actions">
                        <Field label="Note" bare>
                          <input value={notes[v.id] ?? ""} onChange={(e) => setNotes({ ...notes, [v.id]: e.target.value })} placeholder="Why not, if not" />
                        </Field>
                        <Button size="small" variant="primary" type="button" onClick={() => decide(v, true)}>
                          Approve
                        </Button>
                        <Button size="small" variant="danger" type="button" onClick={() => decide(v, false)}>
                          Not approved
                        </Button>
                      </div>
                    ) : (
                      <span className="muted">{v.decision_note ?? (v.decided_at ? `decided ${v.decided_at.slice(0, 10)}` : "waiting for the director")}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type RegBill = {
  id: number; ra: number; code: string; status: string; imported: boolean; kind: string; number: string | null; date: string | null;
  basic: string; gst: string; total: string; paid: string; in_old_register: boolean; revisions: number; sent_revision: string | null;
  old_no: string | null; was: string | null;
}; // prettier-ignore
type Register = { bills: RegBill[]; old: { ra: number | null; description: string; status: string; date: string | null; invoice_no: string | null; basic: string; total: string | null }[]; findings: { kind: string; text: string }[]; source: string | null };

/** A sheet, a bill or the register opens below the drawing: the page brings it up once it is there,
 * its head below the sticky top bar (the page's scroll-padding-top), so it is never read under the bar. */
export function useShown(id: string, ready: boolean) {
  useEffect(() => {
    if (ready) document.getElementById(id)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [id, ready]);
}

const FINDING: Record<string, string> = { missing: "Number missing", clash: "Number clash", order: "Out of order", year: "Wrong year", date: "Date differs", register: "Old register" };

/** The site's bills in order beside the old register, and what was found. */
export function RegisterView({ siteId, onOpen, onClose }: { siteId: number; onOpen: (billId: number) => void; onClose: () => void }) {
  const [r, setR] = useState<Register | null>(null);
  useShown("m-register", true);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback(
    () => api<Register>(`/api/measure/sites/${siteId}/register${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`).then(setR, (e) => setErr(errorText(e))),
    [siteId, q],
  );
  useEffect(() => void load(), [load]);
  async function upload(f: File) {
    const form = new FormData();
    form.set("file", f);
    try {
      setR(await api<Register>(`/api/measure/sites/${siteId}/register`, { method: "POST", form }));
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Card
      id="m-register"
      title="The site's bill register"
      actions={
        <div className="row-actions">
          <Field label="Find a bill" bare>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="RA 16 (the app's or the old number)" />
          </Field>
          <Field label="Read an old register (Excel)" bare>
            <input type="file" accept=".xlsx" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </Field>
          <Button size="small" variant="ghost" type="button" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      {err && <div className="alert alert-error">{err}</div>}
      {!r ? (
        <p className="muted">Loading the register…</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table compact">
              <thead>
                <tr>
                  <th>RA</th>
                  <th>Bill</th>
                  <th>Proforma / tax invoice</th>
                  <th>Date</th>
                  <th className="num">Basic</th>
                  <th className="num">GST</th>
                  <th className="num">Total</th>
                  <th className="num">Received</th>
                  <th>Old register</th>
                  <th>Revisions</th>
                </tr>
              </thead>
              <tbody>
                {r.bills.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <b>RA {b.ra}</b>
                      {b.was && <div className="muted small">{b.was}</div>}
                    </td>
                    <td>
                      <button type="button" className="link-button" onClick={() => onOpen(b.id)}>
                        {b.code}
                      </button>{" "}
                      {b.imported ? <span className="chip chip-idle">imported</span> : <span className="chip chip-prog">{b.status}</span>}
                    </td>
                    <td>
                      {b.kind} {b.number ?? "—"}
                    </td>
                    <td>{b.date ?? "—"}</td>
                    <td className="num">{inr(b.basic)}</td>
                    <td className="num">{inr(b.gst)}</td>
                    <td className="num">{inr(b.total)}</td>
                    <td className="num">{inr(b.paid)}</td>
                    <td>{b.in_old_register ? <span className="chip chip-done">listed</span> : <span className="chip chip-hold">missing</span>}</td>
                    <td>
                      {b.revisions} {b.sent_revision && <span className="muted">({b.sent_revision} sent)</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>What was found{r.source ? ` in ${r.source}` : ""}</h3>
          {r.findings.length ? (
            <ul className="m-findings">
              {r.findings.map((f, i) => (
                <li key={i}>
                  <span className={`chip chip-${f.kind === "missing" || f.kind === "clash" ? "block" : "hold"}`}>{FINDING[f.kind] ?? f.kind}</span> {f.text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Nothing: read an old register to compare.</p>
          )}
          {r.old.length > 0 && (
            <>
              <h3>The old register, as written</h3>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>RA</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Date</th>
                    <th>Invoice</th>
                    <th className="num">Basic</th>
                    <th className="num">With tax</th>
                  </tr>
                </thead>
                <tbody>
                  {r.old.map((o, i) => (
                    <tr key={i}>
                      <td>{o.ra === null ? "?" : `RA ${o.ra}`}</td>
                      <td>{o.description}</td>
                      <td>{o.status}</td>
                      <td>{o.date ?? "—"}</td>
                      <td>{o.invoice_no ?? "—"}</td>
                      <td className="num">{inr(o.basic)}</td>
                      <td className="num">{o.total ? inr(o.total) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </Card>
  );
}

type Revision = {
  id: number; rev: string; label: string | null; source: string | null; made_on: string | null; basic: string; gst: string; total: string; sent: boolean;
  changes: { item: string; qty_before: string; qty_now: string; amount_before: string; amount_now: string; amount_change: string }[]; basic_change: string | null;
}; // prettier-ignore

/** The bill's revisions: each version as it was made, the one sent, what changed between them. */
export function Revisions({ billId, canEdit }: { billId: number; canEdit: boolean }) {
  const [revs, setRevs] = useState<Revision[] | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Revision[]>(`/api/measure/bills/${billId}/revisions`).then(setRevs, (e) => setErr(errorText(e))), [billId]);
  useEffect(() => void load(), [load]);
  async function act(path: string, json?: unknown) {
    try {
      setRevs(await api<Revision[]>(path, { method: "POST", json }));
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <div className="m-revisions">
      <h3>Revisions</h3>
      {err && <div className="alert alert-error">{err}</div>}
      {revs && !revs.length && <p className="muted">None kept yet.</p>}
      {revs && revs.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Rev</th>
              <th>Version</th>
              <th>Date</th>
              <th className="num">Basic</th>
              <th className="num">Change</th>
              <th className="num">Total</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {revs.map((r) => (
              <tr key={r.id}>
                <td>
                  <b>{r.rev}</b> {r.sent && <span className="chip chip-done">sent to the client</span>}
                </td>
                <td>
                  {r.label ?? "—"}
                  {r.changes.length > 0 && (
                    <div className="m-why">
                      {r.changes
                        .slice(0, 4)
                        .map((c) => `item ${c.item}: ${num(c.qty_before, 3)} → ${num(c.qty_now, 3)} (${inr(c.amount_change)})`)
                        .join("; ")}
                    </div>
                  )}
                </td>
                <td>{r.made_on ?? "—"}</td>
                <td className="num">{inr(r.basic)}</td>
                <td className="num">{r.basic_change === null ? "—" : inr(r.basic_change)}</td>
                <td className="num">{inr(r.total)}</td>
                <td>
                  {canEdit && !r.sent && (
                    <Button size="small" variant="ghost" type="button" onClick={() => act(`/api/measure/bills/${billId}/revisions/${r.id}/sent`)}>
                      Mark sent
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <Button size="small" type="button" onClick={() => act(`/api/measure/bills/${billId}/revisions`, { label: "kept from the app" })}>
          Keep the bill as it is now as a revision
        </Button>
      )}
    </div>
  );
}

type Material = {
  bill: string; until: string; store: string | null; note: string | null;
  rows: { product: string; unit: string | null; needed: string; sent: string; returned: string; site_stock: string; used: string; variance: string; variance_percent: string | null; from: string[] }[];
}; // prettier-ignore

/** Needed (the bills' quantities x coverage) against used (sent, less returned, less still on site). */
export function MaterialCheck({ billId }: { billId: number }) {
  const [m, setM] = useState<Material | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Material>(`/api/measure/bills/${billId}/material`).then(setM, (e) => setErr(errorText(e)));
  }, [billId]);
  return (
    <div className="m-material">
      <h3>Material check</h3>
      {err && <div className="alert alert-error">{err}</div>}
      {m?.note && <p className="muted">{m.note}</p>}
      {m && !m.rows.length && <p className="muted">No item on the bills up to this one says what it is made of (its system).</p>}
      {m && m.rows.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Product</th>
              <th className="num">Needed</th>
              <th className="num">Sent to site</th>
              <th className="num">Returned</th>
              <th className="num">On site</th>
              <th className="num">Used</th>
              <th className="num">Variance</th>
            </tr>
          </thead>
          <tbody>
            {m.rows.map((r) => (
              <tr key={r.product}>
                <td>
                  {r.product}
                  <div className="m-why">{r.from.join("; ")}</div>
                </td>
                <td className="num">
                  {num(r.needed, 2)} {r.unit}
                </td>
                <td className="num">{num(r.sent, 2)}</td>
                <td className="num">{num(r.returned, 2)}</td>
                <td className="num">{num(r.site_stock, 2)}</td>
                <td className="num">
                  <b>{num(r.used, 2)}</b>
                </td>
                <td className={`num ${Number(r.variance) > 0 ? "m-over" : ""}`}>
                  {num(r.variance, 2)} {r.variance_percent !== null && `(${num(r.variance_percent, 1)}%)`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {m && <p className="m-why">Up to {m.until}; {m.store ?? "no site store"}. Needed = the bills' sqm × each product's coverage in the item's system.</p>}
    </div>
  );
}
