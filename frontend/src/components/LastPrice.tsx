// Beside a price being entered (rate working, PO, rate contract): the last price used for the
// product, its date and who entered it, and a flag when the new price changes it by more than the
// setting (10 %).
import { useEffect, useState } from "react";
import { api } from "../api";
import { inr } from "../format";

type Check = {
  last: { rate: string; unit: string | null; date: string; by: string | null; source: string; ref: string | null; vendor: string | null } | null;
  change_percent: string | null;
  limit_percent: string;
  flagged: boolean;
};

const SOURCE: Record<string, string> = { vendor_quote: "vendor quote", rate_contract: "rate contract", po: "PO", manual: "entered" };

export function LastPrice({ productId, rate, excludeId }: { productId: number | null | undefined; rate: string | number | null | undefined; excludeId?: number | null }) {
  const [c, setC] = useState<Check | null>(null);
  useEffect(() => {
    if (!productId) return;
    const value = rate === null || rate === undefined || rate === "" ? "" : `&rate=${encodeURIComponent(String(rate))}`;
    const t = setTimeout(() => {
      api<Check>(`/api/prices/last?product_id=${productId}${value}${excludeId ? `&exclude_id=${excludeId}` : ""}`).then(setC, () => setC(null));
    }, 250);
    return () => clearTimeout(t);
  }, [productId, rate, excludeId]);
  if (!productId || !c) return null;
  if (!c.last) return <span className="last-price muted">No price used before</span>;
  const d = new Date(`${c.last.date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  return (
    <span className={`last-price ${c.flagged ? "flagged" : ""}`}>
      Last {inr(c.last.rate)}
      {c.last.unit ? `/${c.last.unit}` : ""} on {d}
      {c.last.by ? ` by ${c.last.by}` : ""} ({SOURCE[c.last.source] ?? c.last.source}
      {c.last.ref ? ` ${c.last.ref}` : ""})
      {c.change_percent !== null && Number(c.change_percent) !== 0 && (
        <b>
          {" "}
          · {Number(c.change_percent) > 0 ? "+" : ""}
          {c.change_percent} %{c.flagged ? ` (more than ${Number(c.limit_percent)} %)` : ""}
        </b>
      )}
    </span>
  );
}
