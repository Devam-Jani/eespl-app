// An estimate's areas on the site's measured drawing, read only: planning sees where each area is
// without the billing permission Measure and bill needs. Pan, zoom and pick an area; nothing here
// changes the drawing. Billing also gets the link to Measure and bill.
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { errorText, num } from "../format";
import { DrawingView } from "../measure/Pages";
import type { Area, Drawing, Edge } from "../measure/Pages";
import { buttonClass, Card, EmptyState, PageSkeleton } from "../ui/components";
import { E } from "./common";
import "./estimate.css";

type Row = Omit<Area, "billed"> & { in_estimate: "in" | "excluded" | "missed"; excluded_reason: string | null };
type View = {
  estimate: { id: number; code: string; title: string | null };
  site: { id: number; code: string; name: string };
  drawing: (Drawing & { title: string; rev: number; unit_m: number }) | null;
  areas: Row[];
  edges: Edge[];
  can_measure: boolean;
};

const STATE: Record<Row["in_estimate"], [string, string]> = {
  in: ["In the estimate", "badge-ok"],
  excluded: ["Left out", "badge-muted"],
  missed: ["Not in the estimate", "badge-warn"],
};

export default function EstimateDrawing() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [v, setV] = useState<View | null>(null);
  const [error, setError] = useState("");
  const areaId = params.get("area") ? Number(params.get("area")) : null;

  useEffect(() => {
    api<View>(`${E}/estimates/${id}/drawing`).then(setV, (e) => setError(errorText(e)));
  }, [id]);

  if (!v) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton label="Loading the drawing" />;
  const picked = v.areas.find((a) => a.id === areaId) ?? null;
  const pick = (aid: number) => setParams({ area: String(aid) }, { replace: true });
  const areas = v.areas.map((a) => ({ ...a, billed: false }));

  return (
    <div className="mb-page">
      <header className="page-header">
        <div>
          <Link to={`/estimates/${v.estimate.id}`} className="muted">
            ← {v.estimate.code} {v.estimate.title ?? ""}
          </Link>
          <h1>Drawing: {v.site.code} {v.site.name}</h1>
          <p className="muted small">Read only. {v.drawing ? `${v.drawing.title} rev ${v.drawing.rev}` : ""}</p>
        </div>
        {v.can_measure && (
          <div className="row-actions">
            <Link className={buttonClass()} to={`/sites/${v.site.id}/measure?ask=no${areaId ? `&area=${areaId}` : ""}`}>
              Open in Measure and bill
            </Link>
          </div>
        )}
      </header>
      {!v.drawing ? (
        <EmptyState title="No drawing read for this site" hint="Billing uploads the DWG and measures it; the areas then show here." />
      ) : (
        <div className="measure-grid">
          <div className="measure-canvas">
            <DrawingView
              drawing={v.drawing}
              areas={areas}
              edges={v.edges}
              mode="look"
              pick={{ areaId, edgeId: null }}
              levels={[]}
              onPoint={() => undefined}
              onTraced={() => undefined}
              onLevel={() => undefined}
              onArea={pick}
              onEdge={() => undefined}
            />
            <p className="muted measure-hint">Drag to pan, wheel to zoom. Click an area to see it in the list.</p>
          </div>
          <div className="measure-side">
            {picked && (
              <Card title={`${picked.code} ${picked.name}`} size="small">
                <p>
                  <span className={`badge ${STATE[picked.in_estimate][1]}`}>{STATE[picked.in_estimate][0]}</span>
                  {picked.excluded_reason && <span className="small muted"> {picked.excluded_reason}</span>}
                </p>
                <p className="small">
                  {num(picked.net_area_sqm, 2)} sqm, periphery {num(picked.net_periphery_m, 2)} m
                </p>
              </Card>
            )}
            <Card title="Measured areas" size="small">
              <ul className="est-drawing-areas">
                {v.areas.map((a) => (
                  <li key={a.id}>
                    <button type="button" className={`link-button ${a.id === areaId ? "strong" : ""}`} onClick={() => pick(a.id)}>
                      {a.code} {a.name}
                    </button>
                    <span className="small muted"> {num(a.net_area_sqm, 2)} sqm</span> <span className={`badge ${STATE[a.in_estimate][1]}`}>{STATE[a.in_estimate][0]}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
