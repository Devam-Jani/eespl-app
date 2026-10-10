// The "site average": the median actual consumption per unit over completed areas, per system and
// product. Shown next to the system's own figure; it never changes the system by itself.
import { useEffect, useState } from "react";
import { api } from "../api";

export type Learned = { system_id: number; system: string | null; product_id: number; product: string; site_average: string; areas: number; master: string | null };

export function useLearned(systemId?: number | null): Learned[] {
  const [rows, setRows] = useState<Learned[]>([]);
  useEffect(() => {
    if (systemId === null) return;
    void api<Learned[]>(`/api/sitecontrol/learned${systemId ? `?system_id=${systemId}` : ""}`).then(setRows, () => setRows([]));
  }, [systemId]);
  return rows;
}
