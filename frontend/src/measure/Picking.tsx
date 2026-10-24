// Measuring real drawings, as a person clicks: choosing among the outlines around a click, picking a
// line (a slope on a section, a wall drawn on its own), a height added up from numbers on the
// drawing, the wall drawn between two areas, an item's parts not done in an area, and a study (the
// same areas measured another way, to compare; never sent or billed).
import { useEffect, useState } from "react";
import { api } from "../api";
import { errorText, num } from "../format";
import { Button, Field } from "../ui/components";
import { Modal } from "../ui/Overlay";

export type Candidate = { handle: string; layer: string; area_sqm: string; periphery_m: string; gap_mm: number | null; drawn_m: number | null };
export type NearLine = { handle: string; layer: string; length_m: string; distance_m: number; path: number[] };
type AreaRef = { id: number; code: string; name: string };

/** The outlines around a click, smallest first; the chosen one is measured. */
export function OutlineChooser({ siteId, fileId, x, y, value, onChange }: { siteId: number; fileId: number; x: number; y: number; value: string | null; onChange: (h: string | null) => void }) {
  const [list, setList] = useState<Candidate[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Candidate[]>(`/api/measure/sites/${siteId}/drawing/${fileId}/at?x=${x}&y=${y}`).then(
      (l) => {
        setList(l);
        onChange(l[0]?.handle ?? null);
      },
      (e) => setErr(errorText(e)),
    );
  }, [siteId, fileId, x, y]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="alert alert-error">{err}</div>;
  if (!list) return <p className="muted">Finding the outlines around the click…</p>;
  if (!list.length) return <div className="alert alert-warn">No closed outline around that point: trace it instead.</div>;
  return (
    <fieldset className="m-choose">
      <legend>{list.length === 1 ? "The outline around the click" : `${list.length} outlines around the click: choose the one to measure`}</legend>
      {list.map((c) => (
        <label key={c.handle} className={value === c.handle ? "on" : ""}>
          <input type="radio" name="outline" checked={value === c.handle} onChange={() => onChange(c.handle)} />
          <span>
            <b>Layer {c.layer}</b> · {num(c.area_sqm, 4)} sqm · periphery {num(c.periphery_m, 3)} m
            {c.gap_mm !== null && (
              <span className="m-why">
                {" "}
                · drawn open ({num(c.gap_mm, 1)} mm gap), closed by the app; its line as drawn is {num(c.drawn_m ?? 0, 3)} m
              </span>
            )}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** The lines near a click, nearest first: one is picked. */
export function LineChoice({ siteId, fileId, x, y, title, askSection, onPick, onClose }: { siteId: number; fileId: number; x: number; y: number; title: string; askSection?: boolean; onPick: (l: NearLine, section: string) => Promise<void>; onClose: () => void }) {
  const [list, setList] = useState<NearLine[] | null>(null);
  const [section, setSection] = useState("Section X-X");
  const [chosen, setChosen] = useState<string | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<NearLine[]>(`/api/measure/sites/${siteId}/drawing/${fileId}/near?x=${x}&y=${y}`).then(
      (l) => {
        setList(l);
        setChosen(l[0]?.handle ?? null);
      },
      (e) => setErr(errorText(e)),
    );
  }, [siteId, fileId, x, y]);
  const line = list?.find((l) => l.handle === chosen);
  return (
    <Modal title={title} onClose={onClose}>
      {err && <div className="alert alert-error">{err}</div>}
      {!list && !err && <p className="muted">Finding the lines near the click…</p>}
      {list && !list.length && <div className="alert alert-warn">No line within half a metre of the click: click on the line.</div>}
      {list && list.length > 0 && (
        <fieldset className="m-choose">
          <legend>Lines near the click, nearest first</legend>
          {list.map((l) => (
            <label key={l.handle} className={chosen === l.handle ? "on" : ""}>
              <input type="radio" name="line" checked={chosen === l.handle} onChange={() => setChosen(l.handle)} />
              <span>
                <b>Layer {l.layer}</b> · {num(Number(l.length_m) * 1000, 2)} mm long (an arc measured as an arc) · {num(l.distance_m * 1000, 0)} mm from the click
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {askSection && (
        <Field label="The section it is on">
          <input value={section} onChange={(e) => setSection(e.target.value)} />
        </Field>
      )}
      <div className="row-actions">
        <Button
          variant="primary"
          type="button"
          disabled={!line}
          onClick={async () => {
            try {
              if (line) await onPick(line, section);
            } catch (e) {
              setErr(errorText(e));
            }
          }}
        >
          Use this line
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

/** A height added up from numbers on the drawing ("750 + 150"), with its source. */
export function SumHeight({ area, which, onClose, onDone }: { area: AreaRef; which: 1 | 2; onClose: () => void; onDone: () => Promise<void> }) {
  const [section, setSection] = useState("Section X-X");
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const parts = text.split("+").map((s) => s.trim()).filter(Boolean);
  const total = parts.reduce((s, p) => s + (Number(p.replace(/[^\d.]/g, "")) || 0), 0);
  async function save() {
    try {
      await api(`/api/measure/areas/${area.id}/height`, { method: "POST", json: { section, sum_of: parts, which } });
      await onDone();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title={`${area.code} ${area.name}: a height added up`} onClose={onClose}>
      <Field label="Section">
        <input value={section} onChange={(e) => setSection(e.target.value)} />
      </Field>
      <Field label="The numbers on the drawing, added (mm)" hint="As written: 750 + 150">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="750 + 150" />
      </Field>
      {parts.length > 0 && (
        <p className="m-source">
          {section}: {parts.join(" + ")} = {total} mm
        </p>
      )}
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={!parts.length}>
          Use it
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

/** The two areas a wall drawn on its own runs between; the line is then picked on the drawing. */
export function DrawnWallStart({ areas, onStart, onClose }: { areas: AreaRef[]; onStart: (a: number, b: number) => void; onClose: () => void }) {
  const [a, setA] = useState(areas[0]?.id ?? 0);
  const [b, setB] = useState(areas[1]?.id ?? 0);
  return (
    <Modal title="A wall drawn on its own between two areas" onClose={onClose}>
      <p className="muted">When two areas are drawn apart, the wall between them is often drawn as its own line. Choose the two areas, then click on that line.</p>
      <Field label="One area">
        <select value={a} onChange={(e) => setA(Number(e.target.value))}>
          {areas.map((x) => (
            <option key={x.id} value={x.id}>
              {x.code} {x.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="The other area">
        <select value={b} onChange={(e) => setB(Number(e.target.value))}>
          {areas.map((x) => (
            <option key={x.id} value={x.id}>
              {x.code} {x.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="row-actions">
        <Button variant="primary" type="button" disabled={!a || !b || a === b} onClick={() => onStart(a, b)}>
          Click on its line
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

/** A study: the same areas measured another way (the billing team's old sheets), to compare. */
export function StudyForm({ siteId, areas, onClose, onDone }: { siteId: number; areas: AreaRef[]; onClose: () => void; onDone: (id: number) => Promise<void> }) {
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const [title, setTitle] = useState("The billing team's way");
  const [chosen, setChosen] = useState<number[]>(areas.map((a) => a.id));
  const [truncate, setTruncate] = useState(true);
  const [sqft, setSqft] = useState("10.76");
  const [perItem, setPerItem] = useState(true);
  const [drawn, setDrawn] = useState(true);
  const [err, setErr] = useState("");
  async function save() {
    try {
      const s = await api<{ id: number }>(`/api/measure/sites/${siteId}/studies`, {
        method: "POST",
        json: { measured_on: on, title, options: { areas: chosen, sizes: truncate ? "truncate3" : "full", sqft_per_sqm: sqft, convert: perItem ? "item" : "line", periphery: drawn ? "drawn" : "closed" } },
      });
      await onDone(s.id);
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Modal title="Compare another way of measuring" onClose={onClose} wide>
      <p className="muted">A study is kept beside the app's sheet to compare; it is never sent or billed.</p>
      <Field label="Title">
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Measured on">
        <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </Field>
      <Field label="Areas" as="fieldset">
        <div className="m-parts">
          {areas.map((a) => (
            <label key={a.id}>
              <input type="checkbox" checked={chosen.includes(a.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, a.id] : chosen.filter((x) => x !== a.id))} /> {a.code} {a.name}
            </label>
          ))}
        </div>
      </Field>
      <Field label="How" as="fieldset">
        <div className="m-parts">
          <label>
            <input type="checkbox" checked={truncate} onChange={(e) => setTruncate(e.target.checked)} /> Sizes cut to 3 decimals (as the old sheets)
          </label>
          <label>
            <input type="checkbox" checked={perItem} onChange={(e) => setPerItem(e.target.checked)} /> Converted once per item (a total line)
          </label>
          <label>
            <input type="checkbox" checked={drawn} onChange={(e) => setDrawn(e.target.checked)} /> An outline left open: its line as drawn
          </label>
        </div>
      </Field>
      <Field label="1 sqm =">
        <select value={sqft} onChange={(e) => setSqft(e.target.value)}>
          <option value="10.76">10.76 sqft (the old sheets)</option>
          <option value="10.7639">10.7639 sqft (the app)</option>
        </select>
      </Field>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="row-actions">
        <Button variant="primary" type="button" onClick={save} disabled={!chosen.length}>
          Make the study
        </Button>
        <Button variant="ghost" type="button" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

const PARTS: Record<string, string> = { floor: "Floor", walls: "Walls", tops: "Wall tops", slope: "Slope", count: "Count" };

/** Per area: the item's parts not done there, and a count made on site. */
export function ItemAreas({
  areas,
  parts,
  skip,
  manual,
  onSave,
}: {
  areas: AreaRef[];
  parts: string[];
  skip: Record<string, string[]>;
  manual: Record<string, string>;
  onSave: (skip: Record<string, string[]>, manual: Record<string, string>) => void;
}) {
  if (!areas.length || !parts.length) return null;
  return (
    <details className="m-item-areas">
      <summary>Per area</summary>
      <table className="table compact">
        <thead>
          <tr>
            <th>Area</th>
            {parts.map((p) => (
              <th key={p}>{PARTS[p] ?? p}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {areas.map((a) => {
            const off = skip[String(a.id)] ?? [];
            return (
              <tr key={a.id}>
                <td>{a.code}</td>
                {parts.map((p) => (
                  <td key={p}>
                    {p === "count" ? (
                      <Field label={`${a.code}: counted on site`} bare>
                        <input
                          className="m-count"
                          inputMode="numeric"
                          defaultValue={manual[String(a.id)] ?? ""}
                          placeholder="from the drawing"
                          onBlur={(e) => {
                            const next = { ...manual };
                            if (e.target.value.trim()) next[String(a.id)] = e.target.value.trim();
                            else delete next[String(a.id)];
                            onSave(skip, next);
                          }}
                        />
                      </Field>
                    ) : (
                      <label>
                        <input
                          type="checkbox"
                          checked={!off.includes(p)}
                          onChange={(e) => {
                            const next = { ...skip, [String(a.id)]: e.target.checked ? off.filter((x) => x !== p) : [...off, p] };
                            onSave(next, manual);
                          }}
                        />{" "}
                        <span className="sr-only">
                          {PARTS[p]} done in {a.code}
                        </span>
                      </label>
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
