// Material estimates (app/estimate): the library, mix designs, estimates, the site's requests and
// the checks. The shapes the API answers, and a few helpers shared by the pages.
import { useEffect, useState } from "react";
import { api } from "../api";

export const E = "/api/estimate";

export type Coverage = {
  id: number;
  product_id: number;
  system_id: number | null;
  system: string | null;
  value: string;
  min_value: string | null;
  max_value: string | null;
  unit: string;
  source: string;
  source_label: string;
  doc_name: string | null;
  has_doc: boolean;
  note: string | null;
  per_sqm: string;
  label: string;
  updated_at: string | null;
};

export type LibProduct = {
  id: number;
  code: string;
  name: string;
  brand: string | null;
  unit: string;
  wastage_percent: string | null;
  pack_size: string | null;
  pack_unit: string | null;
  coverages: Coverage[];
};

export type Library = {
  products: LibProduct[];
  units: string[];
  sources: { key: string; label: string }[];
  systems: { id: number; name: string; upturn_mm: string | null }[];
  can_edit: boolean;
};

export type MixComponent = { role: string; product_id: number | null; parts: number; density: number };

export type MixPart = { role: string; product_id: number | null; product: string | null; unit: string; per_sqm: string; per_sqft: string; how: string };

export type Mix = {
  id: number;
  code: string;
  name: string;
  kind: string;
  thickness_mm: string;
  dry_volume_factor: string;
  components: MixComponent[];
  admixture_product_id: number | null;
  admixture_per_bag: string | null;
  cement_bag_kg: string;
  round_sqft: number | null;
  source: string;
  note: string | null;
  at_mm: string;
  parts: MixPart[];
};

export type Finding = { where: string; text: string; corrected: string; warning: string; clause_id?: number };
export type CoverageWarning = { product: string; product_id: number; where: string; written: string; warning: string };
export type Checks = { coverage: CoverageWarning[]; terms: Finding[] };

export type MaterialRequest = {
  id: number;
  code: string;
  site_id: number;
  site?: string | null;
  estimate_id: number | null;
  area: string | null;
  estimate_area_id: number | null;
  product_id: number;
  product: string | null;
  unit: string | null;
  mix_design_id: number | null;
  area_sqm: string;
  thickness_mm: string | null;
  qty: string;
  packs: number | null;
  formula: string;
  left_before: string | null;
  over_reason: string | null;
  status: string;
  approved_qty: string | null;
  change_note: string | null;
  decided_at: string | null;
  indent: { id: number; code: string; status: string } | null;
  created_at: string;
};

export const MIX_KINDS: Record<string, string> = { nodular: "Nodular concrete", plaster: "Plaster", brick_bat: "Brick bat", other: "Other" };
export const PARTS: Record<string, string> = { both: "Floor and upturn", floor: "Floor only", upturn: "Upturn only" };
export const REQUEST_BADGE: Record<string, string> = { requested: "badge-info", approved: "badge-ok", indented: "badge-ok", rejected: "badge-danger" };
export const REQUEST_STATUS: Record<string, string> = { requested: "Waiting for planning", approved: "Approved", indented: "Approved: indent raised", rejected: "Refused" };

export const when = (d: string | null | undefined, time = true) =>
  d
    ? new Date(d).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", ...(time ? { hour: "2-digit", minute: "2-digit" } : {}) })
    : "—";

/** The library (the products with their coverages, the units, sources and systems), loaded once per page. */
export function useLibrary(): [Library | null, () => void, string] {
  const [lib, setLib] = useState<Library | null>(null);
  const [error, setError] = useState("");
  const [n, setN] = useState(0);
  useEffect(() => {
    api<Library>(`${E}/library`).then(setLib, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, [n]);
  return [lib, () => setN((x) => x + 1), error];
}
