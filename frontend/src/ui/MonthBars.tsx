// The last six months of one number, as bars (this month in full colour, the others dimmed); a
// month with no record shows as an empty slot, said so in its label.
export type MonthPoint = { month: string; value: number | null };

export function MonthBars({ points, format, label }: { points: MonthPoint[]; format: (v: number) => string; label: string }) {
  const known = points.map((p) => p.value ?? 0);
  const max = Math.max(1, ...known.map((v) => Math.abs(v)));
  const any = points.some((p) => p.value !== null);
  return (
    <figure className="month-bars" aria-label={label}>
      {!any && <figcaption className="muted small">No history yet: the nightly summary fills one month at a time.</figcaption>}
      <ol>
        {points.map((p, i) => {
          const h = p.value === null ? 0 : Math.max(4, Math.round((Math.abs(p.value) / max) * 120));
          const last = i === points.length - 1;
          return (
            <li key={`${p.month}-${i}`} className={last ? "now" : undefined}>
              <span className="mb-value">{p.value === null ? "—" : format(p.value)}</span>
              <span className={`mb-bar ${p.value === null ? "mb-none" : ""}`} style={{ height: p.value === null ? 4 : h }} aria-hidden="true" />
              <span className="mb-month">{p.month}</span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
