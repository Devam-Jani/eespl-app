import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText } from "../format";
import type { Site, SiteLookups, SiteTask } from "../types";
import DrawingsTab from "./site/DrawingsTab";
import ScopeTab from "./site/ScopeTab";
import StructureTab from "./site/StructureTab";
import TasksTab from "./site/TasksTab";

// three.js is only downloaded when the 3D tab is opened
const Site3DTab = lazy(() => import("./site/Site3DTab"));
const MaterialTab = lazy(() => import("./site/MaterialTab"));
// the execution tabs are their own chunk too
const DprTab = lazy(() => import("./site/DprTab"));
const LabourTab = lazy(() => import("./site/LabourTab"));
const WorkOrdersTab = lazy(() => import("./site/WorkOrdersTab"));
const InspectionsTab = lazy(() => import("./site/InspectionsTab"));
const MomTab = lazy(() => import("./site/MomTab"));
const AssetsTab = lazy(() => import("./site/AssetsTab"));
const BudgetTab = lazy(() => import("./site/BudgetTab"));
const FinanceTab = lazy(() => import("./site/FinanceTab"));
// the portal tab carries the client portal pages (for the preview)
const PortalTab = lazy(() => import("./site/PortalTab"));
import { ProgressBar, SiteForm, SiteStatusBadge } from "./Sites";
import { shortDate } from "./Tenders";

type Tab =
  | "overview"
  | "structure"
  | "scope"
  | "tasks"
  | "drawings"
  | "material"
  | "3d"
  | "dpr"
  | "labour"
  | "workorders"
  | "inspections"
  | "mom"
  | "assets"
  | "budget"
  | "finance"
  | "portal";

export default function SiteDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [site, setSite] = useState<Site | null>(null);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "overview";
  const setTab = (t: Tab) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSite(await api<Site>(`/api/sites/${id}`));
    } catch (err) {
      setError(errorText(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!site) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;

  return (
    <>
      <p className="breadcrumb">
        <Link to="/sites">Sites</Link> / <code>{site.code}</code>
      </p>
      <div className="page-header">
        <div>
          <h1>
            {site.name} <SiteStatusBadge status={site.status} />
          </h1>
          <p className="muted">
            {site.client_name ?? "Client unknown"}
            {site.channel_name ? ` · via ${site.channel_name}` : ""}
            {site.tender_code && (
              <>
                {" · from "}
                <Link to={`/tenders/${site.tender_id}`}>{site.tender_code}</Link>
              </>
            )}
            {" · target "}
            <span className={site.late ? "text-danger" : ""}>{shortDate(site.target_date)}</span>
            {can("survey.view") && (
              <>
                {" · "}
                <Link to={`/surveys?site=${site.id}`}>Surveys</Link>
              </>
            )}
          </p>
        </div>
        <div className="rate-badge">
          <span className="muted small">Progress</span>
          <ProgressBar value={site.progress_percent} />
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {(() => {
        const tabs = (
          [
            ["overview", "Overview", true],
            ["dpr", "DPR", can("dpr.view")],
            ["tasks", "Tasks", true],
            ["labour", "Labour", can("labour.view")],
            ["material", "Material", can("indent.view", "indent.create", "store.view", "grn.view", "po.view")],
            ["inspections", "Inspections", can("inspection.view")],
            ["workorders", "Work orders", can("subcon.view")],
            ["mom", "MOM", can("inspection.view")],
            ["assets", "Assets", can("asset.view")],
            ["budget", "Budget", can("budget.view")],
            ["finance", "Finance", can("billing.view")],
            ["structure", "Structure", true],
            ["scope", "Scope", true],
            ["drawings", "Drawings", true],
            ["3d", "3D", true],
            ["portal", "Portal", can("portal.manage")],
          ] as [Tab, string, boolean][]
        ).filter(([, , show]) => show);
        return (
          <>
            {/* on a phone the tab bar is a menu */}
            <select className="tab-select tap-input" value={tab} onChange={(e) => setTab(e.target.value as Tab)} aria-label="Section">
              {tabs.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            <div className="tabs tabs-inline tab-bar">
              {tabs.map(([key, label]) => (
                <button key={key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
                  {label}
                </button>
              ))}
            </div>
          </>
        );
      })()}
      <div className="top-gap">
        {tab === "overview" && <Overview site={site} onChange={setSite} />}
        {tab === "structure" && <StructureTab site={site} onChange={load} />}
        {tab === "scope" && <ScopeTab site={site} onChange={load} />}
        {tab === "tasks" && <TasksTab site={site} onChange={load} />}
        {tab === "drawings" && <DrawingsTab site={site} />}
        {tab === "material" && (
          <Suspense fallback={<p className="muted">Loading…</p>}>
            <MaterialTab site={site} />
          </Suspense>
        )}
        <Suspense fallback={<p className="muted">Loading…</p>}>
          {tab === "dpr" && <DprTab site={site} />}
          {tab === "labour" && <LabourTab site={site} />}
          {tab === "workorders" && <WorkOrdersTab site={site} />}
          {tab === "inspections" && <InspectionsTab site={site} onChange={load} />}
          {tab === "mom" && <MomTab site={site} />}
          {tab === "assets" && <AssetsTab site={site} />}
          {tab === "budget" && <BudgetTab site={site} />}
          {tab === "finance" && <FinanceTab site={site} />}
          {tab === "portal" && <PortalTab site={site} />}
        </Suspense>
        {tab === "3d" && (
          <Suspense fallback={<p className="muted">Loading the 3D view…</p>}>
            <Site3DTab site={site} onChange={load} onOpenStructure={() => setTab("structure")} />
          </Suspense>
        )}
      </div>
    </>
  );
}

const ROLES = ["incharge", "supervisor", "sales", "office", "viewer"];

type ExecOverview = {
  dpr_missing: { count: number; days: string[] } | null;
  open_points: { id: number; text: string; due_date: string | null; mom_code: string; overdue: boolean }[] | null;
};

function Overview({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const [editing, setEditing] = useState(false);
  const [lookups, setLookups] = useState<SiteLookups | null>(null);
  const [late, setLate] = useState<SiteTask[]>([]);
  const [ex, setEx] = useState<ExecOverview | null>(null);
  const [members, setMembers] = useState(
    site.members.map((m) => ({
      user_id: m.user_id,
      role_on_site: m.role_on_site,
    })),
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<SiteLookups>("/api/sites/lookups").then(setLookups, () => setLookups(null));
    api<SiteTask[]>(`/api/sites/${site.id}/tasks?filter=late`).then(setLate, () => setLate([]));
    api<ExecOverview>(`/api/execution/sites/${site.id}/overview`).then(setEx, () => setEx(null));
  }, [site.id]);

  async function saveMembers() {
    setError(null);
    try {
      onChange(
        await api<Site>(`/api/sites/${site.id}/members`, {
          method: "PUT",
          json: { members },
        }),
      );
    } catch (err) {
      setError(errorText(err));
    }
  }

  const rows: [string, string][] = [
    ["Code", site.code],
    ["Client", site.client_name ?? "—"],
    ["Channel", site.channel_name ?? "—"],
    ["Address", [site.address, site.city, site.state].filter(Boolean).join(", ") || "—"],
    ["Location", site.lat && site.lng ? `${site.lat}, ${site.lng}` : "—"],
    ["Start", shortDate(site.start_date)],
    ["Target", shortDate(site.target_date)],
    ["In-charge", site.incharge_name ?? "—"],
    ["Source", site.source === "powerplay" ? `Powerplay (${site.source_ref})` : "This app"],
    ["Notes", site.notes ?? "—"],
  ];

  return (
    <div className="split">
      <div className="card">
        <div className="toolbar">
          <h2 className="section-title">Site details</h2>
          {canEdit && lookups && (
            <button className="btn btn-primary" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
        </div>
        <dl className="detail-list">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className="pre-line">{v}</dd>
            </div>
          ))}
        </dl>
        {ex?.dpr_missing && (
          <p className={ex.dpr_missing.count ? "alert alert-warn" : "muted"}>
            {ex.dpr_missing.count ? (
              <>
                DPR missing on {ex.dpr_missing.count} day(s) in the last 30
                {ex.dpr_missing.days.length > 0 && ` (latest ${shortDate(ex.dpr_missing.days[ex.dpr_missing.days.length - 1])})`} · <Link to="?tab=dpr">write it</Link>
              </>
            ) : (
              "Every DPR of the last 30 days is in."
            )}
          </p>
        )}
        {ex?.open_points && (
          <>
            <h2 className="section-title top-gap">Open MOM points ({ex.open_points.length})</h2>
            {ex.open_points.length === 0 ? (
              <p className="muted">None.</p>
            ) : (
              <ul className="plain-list">
                {ex.open_points.map((p) => (
                  <li key={p.id} className={p.overdue ? "text-danger" : ""}>
                    {p.text}{" "}
                    <span className="small muted">
                      {p.mom_code}
                      {p.due_date ? ` · due ${shortDate(p.due_date)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        <h2 className="section-title top-gap">Late tasks ({late.length})</h2>
        {late.length === 0 ? (
          <p className="muted">Nothing is late.</p>
        ) : (
          <table className="table compact">
            <tbody>
              {late.slice(0, 15).map((t) => (
                <tr key={t.id}>
                  <td>{t.node_path}</td>
                  <td>{t.name}</td>
                  <td className="text-danger nowrap">due {shortDate(t.planned_end)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h2 className="section-title">Team on site</h2>
        {error && <div className="alert alert-error">{error}</div>}
        <table className="table compact">
          <tbody>
            {members.map((m, i) => (
              <tr key={i}>
                <td>
                  {canEdit && lookups ? (
                    <select value={m.user_id} onChange={(e) => setMembers((ms) => ms.map((x, j) => (j === i ? { ...x, user_id: e.target.value } : x)))}>
                      {lookups.users.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    site.members.find((x) => x.user_id === m.user_id)?.full_name
                  )}
                </td>
                <td>
                  {canEdit ? (
                    <select value={m.role_on_site} onChange={(e) => setMembers((ms) => ms.map((x, j) => (j === i ? { ...x, role_on_site: e.target.value } : x)))}>
                      {ROLES.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  ) : (
                    m.role_on_site
                  )}
                </td>
                {canEdit && (
                  <td>
                    <button className="btn btn-small btn-ghost" onClick={() => setMembers((ms) => ms.filter((_, j) => j !== i))}>
                      Remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {canEdit && lookups && (
          <div className="form-actions">
            <button
              className="btn"
              onClick={() =>
                setMembers((ms) => [
                  ...ms,
                  {
                    user_id: lookups.users[0]?.id ?? "",
                    role_on_site: "supervisor",
                  },
                ])
              }
            >
              Add person
            </button>
            <button className="btn btn-primary" onClick={() => void saveMembers()}>
              Save team
            </button>
          </div>
        )}
      </div>
      {editing && lookups && (
        <SiteForm
          lookups={lookups}
          site={site}
          onClose={() => setEditing(false)}
          onSaved={(s) => {
            setEditing(false);
            onChange(s);
          }}
        />
      )}
    </div>
  );
}
