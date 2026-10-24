// The labour page's forms: a contractor's piece rate, and a bill (piece rate from the measurement
// book, or a gang's month from attendance). No labour quantity is typed anywhere.
import { useEffect, useState } from "react";
import { api } from "../api";
import { errorText, inr, num } from "../format";
import { Button, Card, Field } from "../ui/components";

export type RateCardLite = { id: number; contractor_id: number; job: string; unit: string; rate: string; in_force: boolean };
type VendorLite = { id: number; name: string };
type ContractLine = { id: number; item_no: string | null; description: string; unit: string };
type Preview = { lines: { description: string; basis: string; client_qty: string; qty: string; unit: string; rate: string; amount: string }[]; gross: string };

const BASIS: Record<string, string> = { billed: "billed to the client", certified: "certified (less than billed)", hours: "hours" };

function useContractors() {
  const [v, setV] = useState<VendorLite[]>([]);
  useEffect(() => {
    api<{ items: VendorLite[] }>("/api/vendors?type=labour_contractor&limit=200").then(
      (r) => setV(r.items),
      () => setV([]),
    );
  }, []);
  return v;
}

export function NewCard({ onDone, onError }: { onDone: () => void; onError: (e: string) => void }) {
  const contractors = useContractors();
  const [f, setF] = useState({ contractor_id: "", job: "", covers: "", unit: "sqft", rate: "", rate_max: "", valid_from: new Date().toISOString().slice(0, 10), valid_to: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  async function save() {
    try {
      await api("/api/labour/rate-cards", {
        method: "POST",
        json: { ...f, contractor_id: Number(f.contractor_id), rate_max: f.rate_max || null, valid_to: f.valid_to || null, covers: f.covers || null },
      });
      setF({ ...f, job: "", covers: "", rate: "", rate_max: "" });
      onDone();
    } catch (e) {
      onError(errorText(e));
    }
  }
  return (
    <Card as="div">
      <h2 className="section-title">New rate</h2>
      <div className="grid-2">
        <Field label="Labour contractor">
          <select value={f.contractor_id} onChange={set("contractor_id")}>
            <option value="">Choose…</option>
            {contractors.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Job">
          <input value={f.job} placeholder="Coating" onChange={set("job")} />
        </Field>
        <Field label="Covers" className="full">
          <input value={f.covers} placeholder="surface preparation, cleaning, crack and joint treatment, vata, primer and coat" onChange={set("covers")} />
        </Field>
        <Field label="Rate (₹) per">
          <span className="inline">
            <input className="input-num" value={f.rate} onChange={set("rate")} />
            <select value={f.unit} onChange={set("unit")}>
              {["sqft", "sqm", "rmt", "nos", "cum"].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </span>
        </Field>
        <Field label="Up to (a range, optional)">
          <input className="input-num" value={f.rate_max} onChange={set("rate_max")} />
        </Field>
        <Field label="Valid from">
          <input type="date" value={f.valid_from} onChange={set("valid_from")} />
        </Field>
        <Field label="Valid to">
          <input type="date" value={f.valid_to} onChange={set("valid_to")} />
        </Field>
      </div>
      <Button variant="primary" className="top-gap" disabled={!f.contractor_id || !f.job || !f.rate} onClick={() => void save()}>
        Add the rate
      </Button>
    </Card>
  );
}

export function NewBill({ cards, onDone, onError }: { cards: RateCardLite[]; onDone: (id: number) => void; onError: (e: string) => void }) {
  const contractors = useContractors();
  const [kind, setKind] = useState<"piece" | "attendance">("piece");
  const [contractor, setContractor] = useState("");
  const [sites, setSites] = useState<{ id: number; code: string; name: string }[]>([]);
  const [site, setSite] = useState("");
  const [lines, setLines] = useState<ContractLine[]>([]);
  const [picks, setPicks] = useState<Record<number, string>>({});
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [preview, setPreview] = useState<Preview | null>(null);
  useEffect(() => {
    api<{ items: { id: number; code: string; name: string }[] }>("/api/sites?limit=200&status=active").then(
      (r) => setSites(r.items),
      () => setSites([]),
    );
  }, []);
  useEffect(() => {
    if (!site) return;
    api<{ lines: ContractLine[] } | null>(`/api/finance/sites/${site}/contract`).then(
      (c) => setLines(c?.lines ?? []),
      () => setLines([]),
    );
  }, [site]);
  const myCards = cards.filter((c) => String(c.contractor_id) === contractor && c.in_force);
  const body = () => ({
    contractor_id: Number(contractor),
    site_id: Number(site),
    period_from: from,
    period_to: to,
    lines: Object.entries(picks)
      .filter(([, card]) => card)
      .map(([line, card]) => ({ contract_line_id: Number(line), rate_card_id: Number(card) })),
  });
  async function doPreview() {
    try {
      setPreview(await api<Preview>("/api/labour/bills/piece/preview", { method: "POST", json: body() }));
    } catch (e) {
      onError(errorText(e));
    }
  }
  async function create() {
    try {
      const b =
        kind === "piece"
          ? await api<{ id: number }>("/api/labour/bills/piece", { method: "POST", json: body() })
          : await api<{ id: number }>("/api/labour/bills/attendance", { method: "POST", json: { contractor_id: Number(contractor), month: `${month}-01` } });
      setPreview(null);
      onDone(b.id);
    } catch (e) {
      onError(errorText(e));
    }
  }
  const pieceReady = contractor && site && from && to;
  return (
    <Card as="div">
      <h2 className="section-title">New labour bill</h2>
      <div className="tabs tabs-inline">
        <button className={`tab ${kind === "piece" ? "active" : ""}`} onClick={() => setKind("piece")}>
          Piece rate
        </button>
        <button className={`tab ${kind === "attendance" ? "active" : ""}`} onClick={() => setKind("attendance")}>
          Gang on attendance
        </button>
      </div>
      <Field label="Labour contractor" className="top-gap">
        <select value={contractor} onChange={(e) => setContractor(e.target.value)}>
          <option value="">Choose…</option>
          {contractors.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>
      {kind === "attendance" ? (
        <Field label="Month (hours per site from attendance)">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        </Field>
      ) : (
        <>
          <div className="grid-3">
            <Field label="Site">
              <select value={site} onChange={(e) => setSite(e.target.value)}>
                <option value="">Choose…</option>
                {sites.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.code} {x.name.slice(0, 40)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="From">
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </Field>
            <Field label="To">
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </Field>
          </div>
          {lines.length > 0 && (
            <table className="table compact">
              <tbody>
                {lines.map((ln) => (
                  <tr key={ln.id}>
                    <td className="small">
                      {ln.item_no} {ln.description.slice(0, 70)} ({ln.unit})
                    </td>
                    <td>
                      <Field label="Job" bare>
                        <select value={picks[ln.id] ?? ""} onChange={(e) => setPicks({ ...picks, [ln.id]: e.target.value })} aria-label="Job">
                          <option value="">— not in this bill —</option>
                          {myCards.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.job} ₹{c.rate}/{c.unit}
                            </option>
                          ))}
                        </select>
                      </Field>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {preview && (
            <table className="table compact">
              <tbody>
                {preview.lines.map((ln, i) => (
                  <tr key={i}>
                    <td className="small">{ln.description}</td>
                    <td className="small">{BASIS[ln.basis] ?? ln.basis}</td>
                    <td className="num">
                      {num(ln.qty, 3)} {ln.unit}
                    </td>
                    <td className="num">{inr(ln.amount)}</td>
                  </tr>
                ))}
                <tr className="row-total">
                  <td colSpan={3}>Gross</td>
                  <td className="num">{inr(preview.gross)}</td>
                </tr>
              </tbody>
            </table>
          )}
        </>
      )}
      <div className="top-gap">
        {kind === "piece" && (
          <Button disabled={!pieceReady} onClick={() => void doPreview()}>
            Preview
          </Button>
        )}{" "}
        <Button variant="primary" disabled={!contractor || (kind === "piece" && !pieceReady)} onClick={() => void create()}>
          Make the bill
        </Button>
      </div>
    </Card>
  );
}
