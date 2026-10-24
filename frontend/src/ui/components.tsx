// The shared components (EESPL UI v1): every page builds from these. Their look is in ui/base.css;
// /dev/ui shows each one in each state.
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { forwardRef } from "react";
import { NavLink } from "react-router-dom";
import { STATUS_LABEL, type Status } from "./tokens";
import alert from "./icons/alert.svg";
import back from "./icons/back.svg";
import camera from "./icons/camera.svg";
import day from "./icons/day.svg";
import materials from "./icons/materials.svg";
import me from "./icons/me.svg";
import play from "./icons/play.svg";
import search from "./icons/search.svg";
import sites from "./icons/sites.svg";

// --- icons: the design's SVGs, painted in the current colour (a mask) ------------------------------

const ICONS = { alert, back, camera, day, materials, me, play, search, sites };
export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 18, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <span
      className="icon"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ "--icon": `url("${ICONS[name]}")`, width: size, height: size } as CSSProperties}
    />
  );
}

// --- button ------------------------------------------------------------------------------------

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "normal" | "small";
  loading?: boolean;
  block?: boolean;
};

/** Primary = the one main action on a card; secondary = everything else. 44 px high for touch. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "normal", loading = false, block = false, className = "", disabled, children, type = "button", ...rest },
  ref,
) {
  const cls = ["btn", `btn-${variant}`, size === "small" ? "btn-small" : "", block ? "btn-block" : "", className].filter(Boolean).join(" ");
  return (
    <button ref={ref} type={type} className={cls} disabled={disabled || loading} data-loading={loading || undefined} aria-busy={loading || undefined} {...rest}>
      {children}
    </button>
  );
});

// --- status chip, legend, progress -----------------------------------------------------------------

/** A work status (a room, a stage, a site): the colour at 18% behind text in the full colour. */
export function StatusChip({ status, children }: { status: Status; children?: ReactNode }) {
  return <span className={`chip chip-${status}`}>{children ?? STATUS_LABEL[status]}</span>;
}

export function Legend({ counts, label = "Status" }: { counts?: Partial<Record<Status, number>>; label?: string }) {
  const order: Status[] = ["done", "prog", "hold", "block", "idle"];
  return (
    <ul className="legend" aria-label={label} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {order.map((s) => (
        <li key={s} className="legend-item">
          <span className={`swatch swatch-${s}`} aria-hidden="true" />
          {STATUS_LABEL[s]}
          {counts && counts[s] !== undefined ? ` ${counts[s]}` : ""}
        </li>
      ))}
    </ul>
  );
}

export function ProgressBar({ value, status, label, thin, showValue }: { value: number | string; status?: "done" | "prog" | "block"; label?: string; thin?: boolean; showValue?: boolean }) {
  const v = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  const bar = (
    <div className={`progress ${status ? `progress-${status}` : ""} ${thin ? "progress-thin" : ""}`} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label={label ?? `${v}%`}>
      <span style={{ width: `${v}%` }} />
    </div>
  );
  return showValue ? (
    <span className="progress-with-value">
      {bar}
      <span className="small muted">{v}%</span>
    </span>
  ) : (
    bar
  );
}

// --- KPI card -----------------------------------------------------------------------------------

/** One key number. With onClick it switches the chart below to that number (pressed when shown). */
export function KpiCard({ label, value, note, active, onClick }: { label: string; value: ReactNode; note?: ReactNode; active?: boolean; onClick?: () => void }) {
  const inner = (
    <>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {note !== undefined && <span className="kpi-note">{note}</span>}
    </>
  );
  return onClick ? (
    <button type="button" className="kpi" aria-pressed={!!active} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <div className="kpi">{inner}</div>
  );
}

// --- nav item -----------------------------------------------------------------------------------

export function NavItem({ to, label, count, icon, onHover }: { to: string; label: string; count?: number; icon?: ReactNode; onHover?: () => void }) {
  return (
    <NavLink to={to} className="nav-item" onMouseEnter={onHover} onFocus={onHover} data-nav={to}>
      {icon && <span className="nav-icon">{icon}</span>}
      <span className="nav-label">{label}</span>
      {count ? (
        <span className="nav-count" aria-label={`${count} waiting`}>
          {count}
        </span>
      ) : null}
    </NavLink>
  );
}

// --- card, empty state, skeleton -------------------------------------------------------------------

export function Card({ title, actions, children, size = "main", className = "", as: As = "section" }: { title?: ReactNode; actions?: ReactNode; children?: ReactNode; size?: "main" | "small"; className?: string; as?: "section" | "div" }) {
  return (
    <As className={`card ${size === "small" ? "card-sm" : ""} ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 className="card-title">{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </As>
  );
}

/** Nothing here yet: says so, and what to do next. */
export function EmptyState({ title, hint, action }: { title: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {hint && <span>{hint}</span>}
      {action}
    </div>
  );
}

/** A grey shape where content is coming (no spinner on a whole page). */
export function Skeleton({ width = "100%", height = 16, lines = 1, radius }: { width?: number | string; height?: number; lines?: number; radius?: number }) {
  return (
    <span aria-hidden="true" style={{ display: "grid", gap: 8 }}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: i === lines - 1 && lines > 1 ? "60%" : width, height, borderRadius: radius }} />
      ))}
    </span>
  );
}

/** The page's place-holder while it loads: a title bar, a row of cards and a table. */
export function PageSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-label={label} className="page-skeleton">
      <Skeleton width={260} height={30} />
      <div className="kpi-grid" style={{ marginTop: 20 }}>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} height={96} radius={16} />
        ))}
      </div>
      <Skeleton height={220} radius={20} />
    </div>
  );
}

// --- tabs ---------------------------------------------------------------------------------------

export type TabDef = { key: string; label: string; count?: number };

/** Tabs (a select on a phone). */
export function Tabs({ tabs, value, onChange, label = "Sections" }: { tabs: TabDef[]; value: string; onChange: (key: string) => void; label?: string }) {
  return (
    <>
      <select className="tab-select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {tabs.map((t) => (
          <option key={t.key} value={t.key}>
            {t.label}
          </option>
        ))}
      </select>
      <div className="tabs" role="tablist" aria-label={label}>
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={t.key === value}
            className={`tab ${t.key === value ? "active" : ""}`}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => {
              const i = tabs.findIndex((x) => x.key === value);
              if (e.key === "ArrowRight") onChange(tabs[(i + 1) % tabs.length].key);
              if (e.key === "ArrowLeft") onChange(tabs[(i - 1 + tabs.length) % tabs.length].key);
            }}
          >
            {t.label}
            {t.count ? <span className="tab-count">{t.count}</span> : null}
          </button>
        ))}
      </div>
    </>
  );
}

// --- form fields --------------------------------------------------------------------------------

export function Field({ label, children, hint, error }: { label: string; children: ReactNode; hint?: ReactNode; error?: string | null }) {
  return (
    <label className={`field ${error ? "field-wrong" : ""}`}>
      <span>{label}</span>
      {children}
      {hint && !error && <small className="muted">{hint}</small>}
      {error && (
        <small className="field-msg" role="alert">
          {error}
        </small>
      )}
    </label>
  );
}

export function Select({ label, value, onChange, options, ...rest }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] } & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value">) {
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function DateField({ label, value, onChange, min, max }: { label: string; value: string; onChange: (v: string) => void; min?: string; max?: string }) {
  return (
    <Field label={label}>
      <input type="date" value={value} min={min} max={max} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function BackButton({ onClick, label = "Back" }: { onClick: () => void; label?: string }) {
  return (
    <button type="button" className="btn btn-secondary btn-icon" onClick={onClick} aria-label={label}>
      <Icon name="back" />
    </button>
  );
}

/** Initials for a round badge (a person, a client's logo slot). */
export function initials(text: string): string {
  const w = text.trim().split(/\s+/).filter(Boolean);
  return ((w[0]?.[0] ?? "") + (w.length > 1 ? w[w.length - 1][0] : (w[0]?.[1] ?? ""))).toUpperCase();
}
