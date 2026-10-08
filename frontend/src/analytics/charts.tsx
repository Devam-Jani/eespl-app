// Small SVG charts for the analytics pages (no chart library: this chunk is lazy-loaded).
// Okabe–Ito colours (safe for colour-blind readers); every bar / point carries its value as a
// label and a tooltip, and can be clicked through to the records behind it.

export const PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"];

export type Row = Record<string, unknown>;
export type Series = { key: string; label: string; color?: string; kind?: "bar" | "line" };
type Fmt = (v: number) => string;

export function compact(v: number): string {
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(a >= 1e8 ? 0 : 1)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e6 ? 0 : 1)} L`;
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(0)} k`;
  return `${sign}₹${a.toFixed(0)}`;
}

export const num = (v: unknown): number | null => (v === null || v === undefined || v === "" ? null : Number(v));

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function Legend({ series }: { series: Series[] }) {
  return (
    <div className="chart-legend">
      {series.map((s, i) => (
        <span key={s.key}>
          <i style={{ background: s.color ?? PALETTE[i % PALETTE.length], borderRadius: s.kind === "line" ? 6 : 2 }} /> {s.label}
        </span>
      ))}
    </div>
  );
}

/** Grouped bars by x (with optional line series drawn over them). */
export function BarChart({
  rows,
  x,
  series,
  fmt = compact,
  height = 260,
  onClick,
}: {
  rows: Row[];
  x: string;
  series: Series[];
  fmt?: Fmt;
  height?: number;
  onClick?: (row: Row) => void;
}) {
  const W = 760;
  const longest = Math.max(1, ...rows.map((r) => String(r[x]).length));
  const tilt = (W - 66) / Math.max(1, rows.length) < longest * 6.5; // labels would overlap: slant them
  const pad = { l: 56, r: 10, t: 22, b: tilt ? 22 + Math.min(70, longest * 4.6) : 34 };
  const bars = series.filter((s) => s.kind !== "line");
  const lines = series.filter((s) => s.kind === "line");
  const max = niceMax(Math.max(0, ...rows.flatMap((r) => series.map((s) => num(r[s.key]) ?? 0))));
  const min = Math.min(0, ...rows.flatMap((r) => series.map((s) => num(r[s.key]) ?? 0)));
  const span = max - min || 1;
  const iw = W - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const slot = iw / Math.max(1, rows.length);
  const bw = Math.min(28, (slot * 0.8) / Math.max(1, bars.length));
  const y = (v: number) => pad.t + ih - ((v - min) / span) * ih;
  const label = bw >= 16;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const v = min + span * f;
          return (
            <g key={f}>
              <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="grid" />
              <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="axis">
                {fmt(v)}
              </text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          const cx = pad.l + slot * i + slot / 2;
          return (
            <g key={i} className={onClick ? "clickable" : undefined} onClick={onClick ? () => onClick(r) : undefined}>
              {bars.map((s, j) => {
                const v = num(r[s.key]) ?? 0;
                const bx = cx - (bars.length * bw) / 2 + j * bw;
                const top = y(Math.max(0, v));
                const h = Math.abs(y(v) - y(0));
                return (
                  <g key={s.key}>
                    <rect x={bx} y={top} width={bw - 2} height={Math.max(1, h)} fill={s.color ?? PALETTE[series.indexOf(s) % PALETTE.length]}>
                      <title>{`${String(r[x])} · ${s.label}: ${fmt(v)}`}</title>
                    </rect>
                    {label && v !== 0 && (
                      <text x={bx + (bw - 2) / 2} y={top - 3} textAnchor="middle" className="value" transform={`rotate(-90 ${bx + (bw - 2) / 2} ${top - 3})`}>
                        {fmt(v)}
                      </text>
                    )}
                  </g>
                );
              })}
              <text x={cx} y={height - pad.b + 14} textAnchor={tilt ? "end" : "middle"} className="axis" transform={tilt ? `rotate(-40 ${cx} ${height - pad.b + 14})` : undefined}>
                {String(r[x])}
              </text>
            </g>
          );
        })}
        {lines.map((s) => {
          const pts = rows.map((r, i) => [pad.l + slot * i + slot / 2, num(r[s.key])] as const).filter((p) => p[1] !== null);
          const color = s.color ?? PALETTE[series.indexOf(s) % PALETTE.length];
          return (
            <g key={s.key}>
              <polyline fill="none" stroke={color} strokeWidth={2.5} points={pts.map(([px, v]) => `${px},${y(v as number)}`).join(" ")} />
              {pts.map(([px, v], i) => (
                <g key={i}>
                  <circle cx={px} cy={y(v as number)} r={4} fill={color}>
                    <title>{`${s.label}: ${fmt(v as number)}`}</title>
                  </circle>
                  {!label && (
                    <text x={px} y={y(v as number) - 8} textAnchor="middle" className="value">
                      {fmt(v as number)}
                    </text>
                  )}
                </g>
              ))}
            </g>
          );
        })}
      </svg>
      <Legend series={series} />
    </figure>
  );
}

/** A line per series over x, each point labelled. */
export function LineChart({ rows, x, series, fmt = (v) => v.toFixed(0), height = 220 }: { rows: Row[]; x: string; series: Series[]; fmt?: Fmt; height?: number }) {
  return <BarChart rows={rows} x={x} series={series.map((s) => ({ ...s, kind: "line" as const }))} fmt={fmt} height={height} />;
}

/** Horizontal bars, one per row: for rankings (spend, win rate, reasons). */
export function HBarChart({
  rows,
  label,
  value,
  fmt = compact,
  color = PALETTE[0],
  onClick,
  note,
  scale,
}: {
  rows: Row[];
  label: string;
  value: string;
  fmt?: Fmt;
  color?: string;
  onClick?: (row: Row) => void;
  note?: (row: Row) => string;
  /** a fixed scale (e.g. 100 for percentages); else the largest value */
  scale?: number;
}) {
  const max = scale ?? Math.max(1e-9, ...rows.map((r) => Math.abs(num(r[value]) ?? 0))); // negative values (a loss) draw by size too
  return (
    <div className="hbars">
      {rows.map((r, i) => {
        const v = num(r[value]) ?? 0;
        return (
          <div key={i} className={`hbar ${onClick ? "clickable" : ""}`} onClick={onClick ? () => onClick(r) : undefined} title={`${String(r[label])}: ${fmt(v)}`}>
            <span className="hbar-label">{String(r[label])}</span>
            <span className="hbar-track">
              <span className="hbar-fill" style={{ width: `${(Math.abs(v) / max) * 100}%`, opacity: v < 0 ? 0.7 : 1, background: color }} />
            </span>
            <span className="hbar-value">
              {fmt(v)}
              {note && <span className="muted small"> {note(r)}</span>}
            </span>
          </div>
        );
      })}
      {rows.length === 0 && <p className="muted small">No data in this range.</p>}
    </div>
  );
}

/** Progress against time gone, one dot per site; on the diagonal = on time. */
export type Placed = { x: number; y: number; anchor: "start" | "end" | "middle" } | null;

/** Where to put each label so none overlaps another label or a dot, or runs off the chart:
 * right of the dot, then left, above, below, then nudged up / down; null = hover only. */
export function placeLabels(points: { x: number; y: number; text: string }[], width: number, height: number, charW = 5.6, h = 11): Placed[] {
  const boxes: { x0: number; x1: number; y0: number; y1: number }[] = points.map((p) => ({ x0: p.x - 5, x1: p.x + 5, y0: p.y - 5, y1: p.y + 5 }));
  const hit = (b: { x0: number; x1: number; y0: number; y1: number }) => boxes.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0);
  return points.map((p) => {
    const w = p.text.length * charW;
    const tries: [number, number, "start" | "end" | "middle"][] = [
      [p.x + 8, p.y + 4, "start"],
      [p.x - 8, p.y + 4, "end"],
      [p.x, p.y - 9, "middle"],
      [p.x, p.y + 17, "middle"],
      [p.x + 8, p.y - 8, "start"],
      [p.x + 8, p.y + 16, "start"],
      [p.x - 8, p.y - 8, "end"],
      [p.x - 8, p.y + 16, "end"],
    ];
    for (const [tx, ty, anchor] of tries) {
      const x0 = anchor === "start" ? tx : anchor === "end" ? tx - w : tx - w / 2;
      const b = { x0, x1: x0 + w, y0: ty - h + 2, y1: ty + 2 };
      if (b.x0 < 2 || b.x1 > width - 2 || b.y0 < 2 || b.y1 > height - 2 || hit(b)) continue;
      boxes.push(b);
      return { x: tx, y: ty, anchor };
    }
    return null;
  });
}

export function ScatterChart({
  rows,
  x,
  y,
  label,
  flag,
  threshold = 0,
  onClick,
}: {
  rows: Row[];
  x: string;
  y: string;
  label: string;
  flag: string;
  threshold?: number;
  onClick?: (row: Row) => void;
}) {
  const S = 360;
  const pad = 36;
  const inner = S - 2 * pad;
  const px = (v: number) => pad + (v / 100) * inner;
  const py = (v: number) => S - pad - (v / 100) * inner;
  const late = rows.filter((r) => Boolean(r[flag]));
  const spots = placeLabels(
    late.map((r) => ({ x: px(num(r[x]) ?? 0), y: py(num(r[y]) ?? 0), text: String(r[label]) })),
    S,
    S,
  );
  const hidden = spots.filter((p) => p === null).length;
  return (
    <figure className="chart scatter">
      <svg viewBox={`0 0 ${S} ${S}`} role="img">
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line x1={px(v)} x2={px(v)} y1={py(0)} y2={py(100)} className="grid" />
            <line x1={px(0)} x2={px(100)} y1={py(v)} y2={py(v)} className="grid" />
            <text x={px(v)} y={S - pad + 14} textAnchor="middle" className="axis">
              {v}%
            </text>
            <text x={pad - 6} y={py(v) + 4} textAnchor="end" className="axis">
              {v}%
            </text>
          </g>
        ))}
        <polygon points={`${px(threshold)},${py(0)} ${px(100)},${py(0)} ${px(100)},${py(100 - threshold)}`} className="late-zone" />
        <line x1={px(0)} y1={py(0)} x2={px(100)} y2={py(100)} className="diagonal" />
        {rows.map((r, i) => {
          const vx = num(r[x]) ?? 0;
          const vy = num(r[y]) ?? 0;
          const isLate = Boolean(r[flag]);
          return (
            <g key={i} className={onClick ? "clickable" : undefined} onClick={onClick ? () => onClick(r) : undefined}>
              {isLate ? <rect x={px(vx) - 5} y={py(vy) - 5} width={10} height={10} fill={PALETTE[3]} /> : <circle cx={px(vx)} cy={py(vy)} r={5} fill={PALETTE[0]} />}
              <title>{`${String(r[label])}: ${vy.toFixed(0)}% done, ${vx.toFixed(0)}% of the time gone`}</title>
            </g>
          );
        })}
        {late.map((r, i) => {
          const at = spots[i];
          return at ? (
            <text key={i} x={at.x} y={at.y} textAnchor={at.anchor} className="value" onClick={onClick ? () => onClick(r) : undefined}>
              {String(r[label])}
            </text>
          ) : null;
        })}
        <text x={S / 2} y={S - 4} textAnchor="middle" className="axis">
          time gone →
        </text>
        <text x={10} y={S / 2} textAnchor="middle" className="axis" transform={`rotate(-90 10 ${S / 2})`}>
          progress →
        </text>
      </svg>
      <div className="chart-legend">
        <span>
          <i style={{ background: PALETTE[0], borderRadius: 6 }} /> on track
        </span>
        <span>
          <i style={{ background: PALETTE[3] }} /> delayed
        </span>
        <span className="muted small">
          shaded: more than {threshold} points behind time · delayed sites labelled{hidden ? ` (${hidden} without room: hover)` : ""}, hover for the rest
        </span>
      </div>
    </figure>
  );
}

/** The tender funnel: bars shrinking step by step, with count, value and conversion. */
export function FunnelChart({
  steps,
  onClick,
}: {
  steps: { step: string; label: string; count: number; value: number | string; conversion: number | null }[];
  onClick?: (step: string) => void;
}) {
  const max = Math.max(1, ...steps.map((s) => s.count));
  return (
    <div className="funnel">
      {steps.map((s, i) => (
        <div key={s.step} className={`funnel-step ${onClick ? "clickable" : ""}`} onClick={onClick ? () => onClick(s.step) : undefined}>
          <div className="funnel-bar" style={{ width: `${Math.max(8, (s.count / max) * 100)}%`, background: PALETTE[i % PALETTE.length] }}>
            <b>{s.count}</b>
          </div>
          <div className="funnel-text">
            <b>{s.label}</b> · {compact(Number(s.value))}
            {s.conversion !== null && <span className="muted"> · {s.conversion}% of the step before</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
