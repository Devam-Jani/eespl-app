import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
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
const ProcessTab = lazy(() => import("../process/Pages").then((m) => ({ default: m.ProcessTab })));
const QualityChecklist = lazy(() => import("../closeout/Screens").then((m) => ({ default: m.QualityChecklist })));
const HandoverTab = lazy(() => import("../schedule/Pages").then((m) => ({ default: m.HandoverTab })));
const PlanLots = lazy(() => import("../schedule/Pages").then((m) => ({ default: m.PlanLots })));
const SiteVisits = lazy(() => import("../team/Pages").then((m) => ({ default: m.SiteVisits })));
const SiteControlStrip = lazy(() => import("../sitecontrol/Pages").then((m) => ({ default: m.SiteControlStrip })));
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
const SiteLocationTab = lazy(() => import("../field/Maps").then((m) => ({ default: m.SiteLocationTab })));
import { SiteForm } from "./Sites";
import { shortDate } from "./Tenders";
import { BackButton, Button, buttonClass, Card, Field, PageSkeleton, StatusChip } from "../ui/components";
import type { Status } from "../ui/tokens";

type Tab =
  | "overview"
  | "visits"
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
  | "portal"
  | "process"
  | "lots"
  | "handover"
  | "location";

export default function SiteDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
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

  if (!site) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton label="Loading the site" />;

  const tools: [string, string, boolean][] = [
    ["Surveys", `/surveys?site=${site.id}`, can("survey.view")],
    ["Work fronts", `/sites/${site.id}/fronts`, can("survey.view")],
    ["Material plan", `/sites/${site.id}/material-plan`, can("planning.view", "indent.view")],
    ["Measurement book", `/measurements?site=${site.id}`, can("measurement.view")],
    ["AutoCAD takeoff", `/sites/${site.id}/takeoff`, can("takeoff.view")],
    ["Measure and bill", `/sites/${site.id}/measure`, can("billing.view")],
    ["Methodology", `/sites/${site.id}/methodology`, can("methodology.site")],
    ["RFI zones", `/sites/${site.id}/zones`, can("closeout.site") || can("closeout.billing")],
    ["Measure", `/sites/${site.id}/measurements`, can("closeout.billing")],
    ["Billing checklist", `/sites/${site.id}/billing-checklist`, can("closeout.billing")],
    ["Material reconciliation", `/sites/${site.id}/reconciliation`, can("closeout.billing")],
    ["Labour claims", `/sites/${site.id}/labour-claims`, can("closeout.billing")],
    ["Bills", `/bills?site=${site.id}`, can("closeout.billing")],
    ["Work completion", `/sites/${site.id}/work-completions`, can("closeout.billing")],
    ["Issues", `/issues?site=${site.id}`, can("issues.view")],
  ];
  const progress = Math.round(Number(site.progress_percent) || 0);
  const chip: Status = site.late ? "block" : site.status === "on_hold" ? "hold" : site.status === "planned" ? "idle" : progress >= 100 ? "done" : "prog";
  const chipText = site.late ? "late" : site.status === "on_hold" ? "on hold" : site.status === "planned" ? "not started" : progress >= 100 ? "done" : "in progress";
  // the design's seven sections first; the rest of the site's sections under "More"
  const all = (
    [
      ["overview", "Overview", true],
      ["3d", "3D building", true],
      ["tasks", "Stages", true],
      ["dpr", "Daily reports", can("dpr.view")],
      ["material", "Materials", can("indent.view", "indent.create", "store.view", "grn.view", "po.view")],
      ["finance", "Measurements & bills", can("billing.view")],
      ["drawings", "Drawings", true],
      ["visits", "Site visits", can("sitevisit.log")],
      ["process", "Process", true],
      ["handover", "Handover", true],
      ["location", "Location & visits", true],
      ["lots", "Plan & lots", can("planning.view", "indent.view", "indent.create")],
      ["labour", "Labour", can("labour.view")],
      ["inspections", "Inspections", can("inspection.view")],
      ["workorders", "Work orders", can("subcon.view")],
      ["mom", "MOM", can("inspection.view")],
      ["assets", "Assets", can("asset.view")],
      ["budget", "Budget", can("budget.view")],
      ["structure", "Structure", true],
      ["scope", "Scope", true],
      ["portal", "Portal", can("portal.manage")],
    ] as [Tab, string, boolean][]
  ).filter(([, , show]) => show);
  const main = all.slice(0, 7);
  const more = all.slice(7);
  const inMore = more.find(([k]) => k === tab);

  return (
    <>
      <header className="site-head">
        <BackButton onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/sites"))} label="Back to sites" />
        <div className="site-title">
          <p className="muted small">
            <Link to="/sites">Sites</Link> · <code>{site.code}</code>
          </p>
          <h1>{site.name}</h1>
          <p className="muted site-scope">
            {site.client_name ?? "Client unknown"}
            {site.channel_name ? ` · via ${site.channel_name}` : ""}
            {site.tender_code && (
              <>
                {" · from "}
                <Link to={`/tenders/${site.tender_id}`}>{site.tender_code}</Link>
              </>
            )}
            {" · target "}
            <span className={site.late ? "tone-block" : ""}>{shortDate(site.target_date)}</span>
          </p>
        </div>
        <StatusChip status={chip}>
          {progress}% done · {chipText}
        </StatusChip>
        {can("site.update") && (
          <Link className={buttonClass({ variant: "primary" })} to={`/my-site/${site.id}`}>
            Update work
          </Link>
        )}
      </header>
      {error && <div className="alert alert-error">{error}</div>}
      {/* on a phone the tabs are one menu */}
      <Field label="Section" bare>
        <select
          className="tab-select"
          value={tab}
          onChange={(e) => (e.target.value.startsWith("/") ? navigate(e.target.value) : setTab(e.target.value as Tab))}
          aria-label="Section"
        >
          {all.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
          {tools
            .filter(([, , show]) => show)
            .map(([label, to]) => (
              <option key={to} value={to}>
                Open: {label}
              </option>
            ))}
        </select>
      </Field>
      <div className="tabs site-tabs" role="tablist" aria-label="Site sections">
        {main.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
        {more.length > 0 && (
          <Field label="More sections and the site's other pages" bare>
            <select
              className={`tab tab-more ${inMore ? "active" : ""}`}
              value={inMore ? tab : ""}
              onChange={(e) => {
                const v = e.target.value;
                if (v.startsWith("/")) navigate(v);
                else if (v) setTab(v as Tab);
              }}
              aria-label="More sections and the site's other pages"
            >
              <option value="">{inMore ? inMore[1] : "More"}</option>
              <optgroup label="Sections">
                {more.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </optgroup>
              {tools.some(([, , show]) => show) && (
                <optgroup label="Open">
                  {tools
                    .filter(([, , show]) => show)
                    .map(([label, to]) => (
                      <option key={to} value={to}>
                        {label}
                      </option>
                    ))}
                </optgroup>
              )}
            </select>
          </Field>
        )}
      </div>
      <div className="top-gap">
        {tab === "overview" && (
          <>
            <Suspense fallback={null}>
              <SiteControlStrip siteId={site.id} />
            </Suspense>
            <Overview site={site} onChange={setSite} />
          </>
        )}
        {tab === "visits" && (
          <Suspense fallback={null}>
            <SiteVisits siteId={site.id} />
          </Suspense>
        )}
        {tab === "structure" && <StructureTab site={site} onChange={load} />}
        {tab === "scope" && <ScopeTab site={site} onChange={load} />}
        {tab === "tasks" && (
          <>
            <TasksTab site={site} onChange={load} />
            {(can("closeout.site") || can("closeout.billing")) && <QualityChecklist siteId={site.id} />}
          </>
        )}
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
        {tab === "process" && (
          <Suspense fallback={<p className="muted">Loading…</p>}>
            <ProcessTab siteId={site.id} />
          </Suspense>
        )}
        <Suspense fallback={<p className="muted">Loading…</p>}>
          {tab === "handover" && <HandoverTab siteId={site.id} />}
          {tab === "location" && <SiteLocationTab siteId={site.id} />}
          {tab === "lots" && <PlanLots siteId={site.id} />}
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

const ROLES = ["incharge", "supervisor", "sales", "office", "viewer", "receiver"];

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
      <Card as="div">
        <div className="toolbar">
          <h2 className="section-title">Site details</h2>
          {canEdit && lookups && (
            <Button variant="primary" onClick={() => setEditing(true)}>
              Edit
            </Button>
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
      </Card>
      <Card as="div">
        <h2 className="section-title">Team on site</h2>
        {error && <div className="alert alert-error">{error}</div>}
        <table className="table compact">
          <tbody>
            {members.map((m, i) => (
              <tr key={i}>
                <td>
                  {canEdit && lookups ? (
                    <Field label="Member" bare>
                      <select value={m.user_id} onChange={(e) => setMembers((ms) => ms.map((x, j) => (j === i ? { ...x, user_id: e.target.value } : x)))}>
                        {lookups.users.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.full_name}
                          </option>
                        ))}
                      </select>
                    </Field>
                  ) : (
                    site.members.find((x) => x.user_id === m.user_id)?.full_name
                  )}
                </td>
                <td>
                  {canEdit ? (
                    <Field label="Role on site" bare>
                      <select value={m.role_on_site} onChange={(e) => setMembers((ms) => ms.map((x, j) => (j === i ? { ...x, role_on_site: e.target.value } : x)))}>
                        {ROLES.map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                    </Field>
                  ) : (
                    m.role_on_site
                  )}
                </td>
                {canEdit && (
                  <td>
                    <Button variant="ghost" size="small" onClick={() => setMembers((ms) => ms.filter((_, j) => j !== i))}>
                      Remove
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {canEdit && lookups && (
          <div className="form-actions">
            <Button
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
            </Button>
            <Button variant="primary" onClick={() => void saveMembers()}>
              Save team
            </Button>
          </div>
        )}
      </Card>
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
