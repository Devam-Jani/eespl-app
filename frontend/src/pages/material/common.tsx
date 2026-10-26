import { useEffect, useState } from "react";
import { api } from "../../api";
import { label, STATUS_BADGE } from "../../material/gst";
import type { MaterialLookups, ProductPick } from "../../material/types";
import { Field } from "../../ui/components";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? "badge-muted"}`}>{label(status)}</span>;
}

let cached: Promise<MaterialLookups> | null = null;

/** The material form lookups (sites, stores, products, vendors ...), fetched once per page load. */
export function useMaterialLookups(): MaterialLookups | null {
  const [data, setData] = useState<MaterialLookups | null>(null);
  useEffect(() => {
    cached ??= api<MaterialLookups>("/api/material/lookups").catch((err) => {
      cached = null;
      throw err;
    });
    cached.then(setData, () => setData(null));
  }, []);
  return data;
}

export function refreshLookups() {
  cached = null;
}

export function ProductSelect({
  products,
  value,
  onChange,
  required,
  label: text,
  className,
}: {
  products: ProductPick[];
  value: number | "";
  onChange: (p: ProductPick | null) => void;
  required?: boolean;
  /** shown above the select; without it the label is for screen readers only (a grid cell) */
  label?: string;
  className?: string;
}) {
  return (
    <Field label={text ?? "Product"} bare={!text} className={className}>
      <select required={required} value={value} onChange={(e) => onChange(products.find((p) => p.id === Number(e.target.value)) ?? null)}>
        <option value="">— product —</option>
        {products.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.code}, {p.unit})
          </option>
        ))}
      </select>
    </Field>
  );
}

export function UnitSelect({ units, value, onChange, label: text }: { units: string[]; value: string; onChange: (u: string) => void; label?: string }) {
  return (
    <Field label={text ?? "Unit"} bare={!text}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {units.map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function dateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata",  day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export const today = () => new Date().toISOString().slice(0, 10);
