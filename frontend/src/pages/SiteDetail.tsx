import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
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
import { ProgressBar, SiteForm, SiteStatusBadge } from "./Sites";
import { shortDate } from "./Tenders";

type Tab = "overview" | "structure" | "scope" | "tasks" | "drawings" | "material" | "3d";

export default function SiteDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [site, setSite] = useState<Site | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
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
          </p>
        </div>
        <div className="rate-badge">
          <span className="muted small">Progress</span>
          <ProgressBar value={site.progress_percent} />
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="tabs tabs-inline">
        {(
          [
            ["overview", "Overview"],
            ["structure", "Structure"],
            ["scope", "Scope"],
            ["tasks", "Tasks"],
            ["drawings", "Drawings"],
            ...(can("indent.view", "indent.create", "store.view", "grn.view", "po.view") ? [["material", "Material"]] : []),
            ["3d", "3D"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button key={key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
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

function Overview({ site, onChange }: { site: Site; onChange: (s: Site) => void }) {
  const { can } = useAuth();
  const canEdit = can("site.edit");
  const [editing, setEditing] = useState(false);
  const [lookups, setLookups] = useState<SiteLookups | null>(null);
  const [late, setLate] = useState<SiteTask[]>([]);
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
