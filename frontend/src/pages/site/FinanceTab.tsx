import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { errorText } from "../../format";
import type { Profit } from "../../finance/types";
import type { Site } from "../../types";
import { SiteBilling } from "../finance/Billing";
import { ProfitCard } from "../finance/Reports";

/** The site's contract, RA bills and invoices; and its profit (with tender.margin). */
export default function FinanceTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const [profit, setProfit] = useState<Profit | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (can("tender.margin")) api<Profit>(`/api/finance/sites/${site.id}/profit`).then(setProfit, (err) => setError(errorText(err)));
  }, [site.id, can]);
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {profit && <ProfitCard p={profit} />}
      <div className="top-gap">
        <SiteBilling siteId={site.id} />
      </div>
    </>
  );
}
