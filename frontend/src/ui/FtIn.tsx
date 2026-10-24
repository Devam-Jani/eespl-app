// A length in feet and inches, as site people measure it. A wrong entry says what is wrong beside
// the boxes and, where there is one clear fix, offers it in one tap ("Did you mean 20 ft 2 in?").
import { useId } from "react";
import { Button, Icon } from "./components";

export type FtInCheck = { ok: true; metres: number; feet: number; inches: number } | { ok: false; problem: string; fix?: { ft: string; inch: string; label: string } };

const FT_M = 0.3048;

function num(s: string): number | null {
  const t = s.trim();
  if (t === "") return 0;
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  return Number(t);
}

/** Is this a length? (blank inches are 0). */
export function checkFtIn(ft: string, inch: string): FtInCheck {
  const f = num(ft);
  const i = num(inch);
  if (ft.trim() === "" && inch.trim() === "") return { ok: false, problem: "Type the length: feet, and inches if any." };
  if (f === null || i === null) {
    const clean = (s: string) => s.replace(/[^\d.]/g, "");
    const fixed = { ft: clean(ft), inch: clean(inch) };
    const both = num(fixed.ft) !== null && num(fixed.inch) !== null && (fixed.ft !== ft.trim() || fixed.inch !== inch.trim());
    return {
      ok: false,
      problem: "Type digits only (no letters, units or commas).",
      fix: both && (fixed.ft || fixed.inch) ? { ...fixed, label: `${fixed.ft || 0} ft ${fixed.inch || 0} in` } : undefined,
    };
  }
  if (i >= 12) {
    const total = Math.round((f * 12 + i) * 100) / 100;
    const nf = Math.floor(total / 12);
    const ni = Math.round((total - nf * 12) * 100) / 100;
    return { ok: false, problem: `Inches must be 0 to 11. Did you mean ${nf} ft ${ni} in?`, fix: { ft: String(nf), inch: String(ni), label: `${nf} ft ${ni} in` } };
  }
  if (f === 0 && i === 0) return { ok: false, problem: "The length cannot be 0." };
  if (f > 2000) return { ok: false, problem: "That is longer than any site: check the feet." };
  const metres = Math.round((f + i / 12) * FT_M * 1000) / 1000;
  return { ok: true, metres, feet: f, inches: i };
}

/** The two boxes, their one message, and the one-tap fix. */
export function FtInInput({ label, ft, inch, onChange, showError = true }: { label: string; ft: string; inch: string; onChange: (ft: string, inch: string) => void; showError?: boolean }) {
  const id = useId();
  const check = checkFtIn(ft, inch);
  const wrong = showError && !check.ok && (ft !== "" || inch !== "");
  return (
    <div className="ftin-field">
      <span className="ftin-label" id={`${id}-l`}>
        {label}
      </span>
      <div className="ftin" role="group" aria-labelledby={`${id}-l`}>
        <label data-wrong={wrong || undefined}>
          <input inputMode="decimal" value={ft} onChange={(e) => onChange(e.target.value, inch)} aria-label={`${label}: feet`} aria-invalid={wrong || undefined} aria-describedby={wrong ? `${id}-e` : undefined} />
          <span aria-hidden="true">ft</span>
        </label>
        <label data-wrong={wrong || undefined}>
          <input inputMode="decimal" value={inch} onChange={(e) => onChange(ft, e.target.value)} aria-label={`${label}: inches`} aria-invalid={wrong || undefined} aria-describedby={wrong ? `${id}-e` : undefined} />
          <span aria-hidden="true">in</span>
        </label>
      </div>
      {wrong && !check.ok && (
        <div className="fix-msg" id={`${id}-e`} role="alert">
          <Icon name="alert" />
          <div>
            <p>{check.problem}</p>
            {check.fix && (
              <Button size="small" onClick={() => onChange(check.fix!.ft, check.fix!.inch)}>
                Use {check.fix.label}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
