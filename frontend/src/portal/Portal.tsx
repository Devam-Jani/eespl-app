// The client portal: a separate, phone-first layout (works at 360 px) on the same login.
// Every call goes to /api/portal, which scopes to the client's own visible sites. Staff can
// render the same pages for one client user, read-only ("preview as client").
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, Navigate, Outlet, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, downloadFile, fetchObjectUrl } from "../api";
import { useAuth } from "../auth";
import Bell from "../components/Bell";
import { isClientLogin } from "../components/Guards";
import Modal from "../components/Modal";
import { errorText, inr, num } from "../format";
import SignaturePad from "../pages/site/SignaturePad";

const Site3DTab = lazy(() => import("../pages/site/Site3DTab"));

type Sections = Record<"overview" | "dpr" | "photos" | "inspections" | "documents" | "billing" | "snags", boolean>;
type SiteCard = { id: number; code: string; name: string; city: string | null; percent: number; last_dpr: string | null; open_snags: number; sections: Sections };
type Overview = SiteCard & {
  start_date: string | null;
  target_date: string | null;
  parts: { id: number; parent_id: number | null; kind: string; name: string; percent: number }[];
  stages: Record<string, number>;
  open_points: { id: number; text: string; due_date: string | null; acknowledged: boolean }[];
};

/** Preview mode: the client user staff are previewing as (read-only), else none. */
const PreviewContext = createContext<string | null>(null);
function usePortal() {
  const preview = useContext(PreviewContext);
  const headers = useMemo<Record<string, string> | undefined>(() => (preview ? { "X-Preview-As": preview } : undefined), [preview]);
  const get = useCallback(<T,>(path: string) => api<T>(path, { headers }), [headers]);
  const file = useCallback((path: string) => downloadFile(path, true, "GET", headers), [headers]);
  const image = useCallback((path: string) => fetchObjectUrl(path, true, headers), [headers]);
  return { preview, readOnly: !!preview, headers, get, file, image };
}

export function day(value: string | null): string {
  if (!value) return "—";
  return new Date(value.length === 10 ? `${value}T00:00:00` : value).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const STATUS_BADGE: Record<string, string> = {
  open: "badge-danger",
  in_progress: "badge-warn",
  fixed: "badge-info",
  verified: "badge-ok",
  closed: "badge-muted",
  submitted: "badge-info",
  certified_by_client: "badge-warn",
  rejected_by_client: "badge-danger",
  certified: "badge-ok",
  invoiced: "badge-ok",
  pass: "badge-ok",
  fail: "badge-danger",
  pass_with_remarks: "badge-warn",
};
const label = (s: string) => s.replace(/_/g, " ");

function Badge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_BADGE[status] ?? "badge-muted"}`}>{label(status)}</span>;
}

function Bar({ percent }: { percent: number }) {
  return (
    <div className="portal-bar" aria-label={`${percent.toFixed(0)}%`}>
      <span style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}

function Logo() {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    void fetchObjectUrl("/api/portal/logo").then((u) => {
      url = u;
      setSrc(u);
    });
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, []);
  return src ? <img className="portal-logo" src={src} alt="EESPL" /> : <span className="brand-mark">E</span>;
}

// --- layout and home -----------------------------------------------------------------------------

export function PortalLayout() {
  const { me, logout } = useAuth();
  if (me && !isClientLogin(me.permissions)) return <Navigate to="/" replace />;
  return (
    <div className="portal">
      <header className="portal-top">
        <Link to="/portal" className="portal-brand">
          <Logo /> <span>EESPL · Client portal</span>
        </Link>
        <div className="portal-actions">
          <Bell />
          <button className="btn btn-ghost btn-small" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="portal-main">
        <Outlet />
      </main>
    </div>
  );
}

export function PortalHome() {
  const { me } = useAuth();
  const [sites, setSites] = useState<SiteCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<SiteCard[]>("/api/portal/sites").then(setSites, (err) => setError(errorText(err)));
  }, []);
  return (
    <>
      <h1 className="portal-title">Hello, {me?.user.full_name}</h1>
      {error && <div className="alert alert-error">{error}</div>}
      {sites?.length === 0 && <p className="empty">No sites are shared with you yet.</p>}
      <div className="portal-cards">
        {sites?.map((s) => (
          <Link key={s.id} to={`/portal/sites/${s.id}`} className="card portal-card">
            <div className="toolbar">
              <strong>{s.name}</strong>
              <span className="portal-percent">{s.percent.toFixed(0)}%</span>
            </div>
            <div className="muted small">
              {s.code}
              {s.city ? ` · ${s.city}` : ""}
            </div>
            <Bar percent={s.percent} />
            <div className="small portal-facts">
              <span>Last report: {day(s.last_dpr)}</span>
              <span>Open snags: {s.open_snags}</span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

// --- a site --------------------------------------------------------------------------------------

const TABS: [keyof Sections, string][] = [
  ["overview", "Overview"],
  ["dpr", "Daily reports"],
  ["photos", "Photos"],
  ["inspections", "Inspections & MOM"],
  ["documents", "Drawings & documents"],
  ["billing", "Billing"],
  ["snags", "Snags"],
];

export function PortalSitePage() {
  const { id } = useParams();
  return <PortalSite siteId={Number(id)} />;
}

/** One site in the portal. With `preview` (a client user id) staff see it as that client. */
export function PortalSite({ siteId, preview }: { siteId: number; preview?: string }) {
  return (
    <PreviewContext.Provider value={preview ?? null}>
      <SiteView siteId={siteId} />
    </PreviewContext.Provider>
  );
}

function SiteView({ siteId }: { siteId: number }) {
  const { get, preview } = usePortal();
  const [params, setParams] = useSearchParams();
  const [localTab, setLocalTab] = useState<keyof Sections>("overview");
  const tab = (preview ? localTab : (params.get("tab") as keyof Sections)) || "overview";
  const setTab = (t: keyof Sections) => (preview ? setLocalTab(t) : setParams({ tab: t }, { replace: true }));
  const [site, setSite] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => get<Overview>(`/api/portal/sites/${siteId}`).then(setSite, (err) => setError(errorText(err))), [get, siteId]);
  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <div className="alert alert-error">{error}</div>;
  if (!site) return <p className="muted">Loading…</p>;
  const tabs = TABS.filter(([k]) => site.sections[k]);
  return (
    <>
      {!preview && (
        <Link to="/portal" className="small">
          ← All sites
        </Link>
      )}
      <h1 className="portal-title">
        {site.name} <span className="muted small">{site.code}</span>
      </h1>
      <select className="tab-select tap-input" value={tab} onChange={(e) => setTab(e.target.value as keyof Sections)} aria-label="Section">
        {tabs.map(([k, l]) => (
          <option key={k} value={k}>
            {l}
          </option>
        ))}
      </select>
      <div className="tabs tabs-inline tab-bar">
        {tabs.map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>
      <div className="top-gap">
        {tab === "overview" && <OverviewTab site={site} onChange={load} />}
        {tab === "dpr" && <DprTab siteId={siteId} />}
        {tab === "photos" && <PhotosTab siteId={siteId} />}
        {tab === "inspections" && <InspectionsTab siteId={siteId} />}
        {tab === "documents" && <DocumentsTab siteId={siteId} />}
        {tab === "billing" && <BillingTab siteId={siteId} />}
        {tab === "snags" && <SnagsTab site={site} />}
      </div>
    </>
  );
}

function OverviewTab({ site, onChange }: { site: Overview; onChange: () => void }) {
  const { readOnly, headers } = usePortal();
  const [error, setError] = useState<string | null>(null);
  const portal = useMemo(() => ({ modelPath: `/api/portal/sites/${site.id}/model`, headers }), [site.id, headers]);
  const towers = site.parts.filter((p) => p.kind !== "floor" && p.kind !== "basement");
  const floorsOf = (id: number | null) => site.parts.filter((p) => (p.kind === "floor" || p.kind === "basement") && p.parent_id === id);
  async function ack(id: number) {
    try {
      await api(`/api/portal/sites/${site.id}/mom-points/${id}/acknowledge`, { method: "POST" });
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="portal-grid">
        <div className="card">
          <div className="muted small">Overall progress</div>
          <div className="portal-big">{site.percent.toFixed(0)}%</div>
          <Bar percent={site.percent} />
          <div className="small portal-facts">
            <span>Last report: {day(site.last_dpr)}</span>
            <span>Open snags: {site.open_snags}</span>
          </div>
          <div className="chips top-gap">
            {Object.entries(site.stages).map(([k, v]) => (
              <span key={k} className="chip">
                {label(k)}: {v}
              </span>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="muted small">By tower / floor</div>
          {towers.length === 0 && floorsOf(null).length === 0 && <p className="muted small">No towers or floors yet.</p>}
          {[...towers, { id: -1, parent_id: null, kind: "", name: "", percent: 0 }].map((t) => {
            const floors = floorsOf(t.id === -1 ? null : t.id);
            if (t.id === -1 && floors.length === 0) return null;
            return (
              <div key={t.id} className="portal-part">
                {t.id !== -1 && (
                  <div className="toolbar small">
                    <strong>{t.name}</strong> <span>{t.percent.toFixed(0)}%</span>
                  </div>
                )}
                {floors.map((f) => (
                  <div key={f.id} className="portal-floor small">
                    <span>{f.name}</span>
                    <Bar percent={f.percent} />
                    <span className="num">{f.percent.toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
      {site.open_points.length > 0 && (
        <div className="card top-gap">
          <div className="muted small">Open meeting points for you</div>
          {site.open_points.map((p) => (
            <div key={p.id} className="toolbar portal-row">
              <span>
                {p.text} {p.due_date && <span className="muted small">due {day(p.due_date)}</span>}
              </span>
              {p.acknowledged ? (
                <span className="badge badge-ok">acknowledged</span>
              ) : (
                !readOnly && (
                  <button className="btn btn-small" onClick={() => void ack(p.id)}>
                    Acknowledge
                  </button>
                )
              )}
            </div>
          ))}
        </div>
      )}
      <div className="top-gap portal-3d">
        <Suspense fallback={<p className="muted">Loading the 3D view…</p>}>
          <Site3DTab site={{ id: site.id, code: site.code, name: site.name, progress_percent: String(site.percent) }} onChange={() => undefined} portal={portal} />
        </Suspense>
      </div>
    </>
  );
}

// --- daily reports and photos --------------------------------------------------------------------

type PDpr = {
  id: number;
  on_date: string;
  weather: string | null;
  work_done: string | null;
  hindrances: string | null;
  next_day_plan: string | null;
  status: string;
  photos: { id: number; caption: string }[];
  tasks: { where: string; name: string; status: string; percent: number }[];
  material_in: string[];
  headcount: { present: number; half_day: number; by_trade: Record<string, number> };
  equipment: string[];
};

function Thumb({ path, alt }: { path: string; alt: string }) {
  const { image } = usePortal();
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    void image(path).then((u) => {
      url = u;
      setSrc(u);
    });
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [image, path]);
  return src ? (
    <a href={src} target="_blank" rel="noreferrer">
      <img className="portal-thumb" src={src} alt={alt} />
    </a>
  ) : (
    <span className="portal-thumb muted small">{alt}</span>
  );
}

function DprTab({ siteId }: { siteId: number }) {
  const { get, file } = usePortal();
  const [list, setList] = useState<PDpr[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<PDpr[]>(`/api/portal/sites/${siteId}/dprs`).then(setList, (err) => setError(errorText(err)));
  }, [get, siteId]);
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {list?.length === 0 && <p className="empty">No daily reports yet.</p>}
      {list?.map((d) => (
        <div key={d.id} className="card portal-item">
          <div className="toolbar">
            <button className="as-button" onClick={() => setOpen(open === d.id ? null : d.id)}>
              <strong>{day(d.on_date)}</strong> {d.weather && <span className="muted small">· {d.weather}</span>}
            </button>
            <button className="btn btn-small" onClick={() => void file(`/api/portal/sites/${siteId}/dprs/${d.id}/pdf`).catch((err) => setError(errorText(err)))}>
              PDF
            </button>
          </div>
          <p className="portal-text">{d.work_done}</p>
          <div className="small muted">
            People on site: {d.headcount.present + d.headcount.half_day}
            {Object.keys(d.headcount.by_trade).length > 0 &&
              ` (${Object.entries(d.headcount.by_trade)
                .map(([t, n]) => `${t} ${n}`)
                .join(", ")})`}
          </div>
          {open === d.id && (
            <div className="top-gap">
              {d.tasks.length > 0 && (
                <ul className="plain-list small">
                  {d.tasks.map((t, i) => (
                    <li key={i}>
                      {t.where} · {t.name} — {label(t.status)} ({t.percent.toFixed(0)}%)
                    </li>
                  ))}
                </ul>
              )}
              {d.hindrances && <p className="small">Hindrances: {d.hindrances}</p>}
              {d.next_day_plan && <p className="small">Plan for tomorrow: {d.next_day_plan}</p>}
              {d.material_in.length > 0 && <p className="small">Material received: {d.material_in.join("; ")}</p>}
              {d.equipment.length > 0 && <p className="small">Equipment: {d.equipment.join(", ")}</p>}
              <div className="portal-photos">
                {d.photos.map((p) => (
                  <Thumb key={p.id} path={`/api/portal/sites/${siteId}/dprs/${d.id}/photos/${p.id}`} alt={p.caption} />
                ))}
              </div>
              <Thread entityType="dpr" entityId={d.id} />
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function PhotosTab({ siteId }: { siteId: number }) {
  const { get } = usePortal();
  const [list, setList] = useState<{ id: number; taken_on: string; step: string; area: string }[] | null>(null);
  const [area, setArea] = useState("");
  useEffect(() => {
    get<{ id: number; taken_on: string; step: string; area: string }[]>(`/api/portal/sites/${siteId}/photos`).then(setList, () => setList([]));
  }, [get, siteId]);
  const areas = [...new Set((list ?? []).map((p) => p.area))].sort();
  const shown = (list ?? []).filter((p) => !area || p.area === area);
  const byDate = shown.reduce<Record<string, typeof shown>>((m, p) => ({ ...m, [p.taken_on]: [...(m[p.taken_on] ?? []), p] }), {});
  return (
    <>
      {areas.length > 1 && (
        <select className="tap-input" value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
          <option value="">All areas</option>
          {areas.map((a) => (
            <option key={a} value={a}>
              {a || "Site"}
            </option>
          ))}
        </select>
      )}
      {list?.length === 0 && <p className="empty">No photos shared yet.</p>}
      {Object.entries(byDate).map(([d, photos]) => (
        <div key={d} className="top-gap">
          <h3 className="section-title">{day(d)}</h3>
          <div className="portal-photos">
            {photos.map((p) => (
              <figure key={p.id}>
                <Thumb path={`/api/portal/sites/${siteId}/photos/${p.id}`} alt={p.step} />
                <figcaption className="small muted">
                  {p.area} · {p.step}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

// --- inspections and MOM -------------------------------------------------------------------------

type PInspection = {
  id: number;
  code: string;
  checklist: string;
  on_date: string;
  result: string;
  step: string | null;
  remark: string | null;
  client_signoff: string;
  client_signed_name: string | null;
  client_signed_at: string | null;
};
type PMom = {
  id: number;
  code: string;
  on_date: string;
  title: string;
  points: { id: number; text: string; due_date: string | null; status: string; yours: boolean; owner: string | null; acknowledged_at: string | null }[];
};

function InspectionsTab({ siteId }: { siteId: number }) {
  const { get, file, readOnly } = usePortal();
  const [list, setList] = useState<PInspection[]>([]);
  const [moms, setMoms] = useState<PMom[]>([]);
  const [signing, setSigning] = useState<PInspection | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    get<PInspection[]>(`/api/portal/sites/${siteId}/inspections`).then(setList, (err) => setError(errorText(err)));
    get<PMom[]>(`/api/portal/sites/${siteId}/moms`).then(setMoms, () => undefined);
  }, [get, siteId]);
  useEffect(load, [load]);
  async function ack(id: number) {
    try {
      await api(`/api/portal/sites/${siteId}/mom-points/${id}/acknowledge`, { method: "POST" });
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  const dl = (path: string) => void file(path).catch((err) => setError(errorText(err)));
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      <h3 className="section-title">Inspections</h3>
      {list.length === 0 && <p className="empty">No inspections yet.</p>}
      {list.map((i) => (
        <div key={i.id} className="card portal-item">
          <div className="toolbar">
            <button className="as-button" onClick={() => setOpen(open === i.id ? null : i.id)}>
              <strong>{i.code}</strong> <span className="muted small">{day(i.on_date)}</span>
            </button>
            <Badge status={i.result} />
          </div>
          <div className="small">
            {i.checklist}
            {i.step ? ` · ${i.step}` : ""}
          </div>
          <div className="portal-buttons">
            <button className="btn btn-small" onClick={() => dl(`/api/portal/sites/${siteId}/inspections/${i.id}/pdf`)}>
              PDF
            </button>
            {i.client_signoff === "waiting" && !readOnly && (
              <button className="btn btn-small btn-primary" onClick={() => setSigning(i)}>
                Sign off
              </button>
            )}
            {i.client_signoff === "waiting" && readOnly && <span className="badge badge-warn">waiting for sign-off</span>}
            {i.client_signoff === "signed" && <span className="badge badge-ok">signed by {i.client_signed_name}</span>}
          </div>
          {open === i.id && <Thread entityType="inspection" entityId={i.id} />}
        </div>
      ))}
      <h3 className="section-title top-gap">Minutes of meeting</h3>
      {moms.length === 0 && <p className="empty">No meetings recorded.</p>}
      {moms.map((m) => (
        <div key={m.id} className="card portal-item">
          <div className="toolbar">
            <span>
              <strong>{m.title}</strong> <span className="muted small">{day(m.on_date)}</span>
            </span>
            <button className="btn btn-small" onClick={() => dl(`/api/portal/sites/${siteId}/moms/${m.id}/pdf`)}>
              PDF
            </button>
          </div>
          {m.points.map((p) => (
            <div key={p.id} className="toolbar portal-row small">
              <span>
                {p.text}{" "}
                <span className="muted">
                  ({p.owner ?? "EESPL"}, {p.status})
                </span>
              </span>
              {p.yours &&
                p.status === "open" &&
                (p.acknowledged_at ? (
                  <span className="badge badge-ok">acknowledged</span>
                ) : (
                  !readOnly && (
                    <button className="btn btn-small" onClick={() => void ack(p.id)}>
                      Acknowledge
                    </button>
                  )
                ))}
            </div>
          ))}
        </div>
      ))}
      {signing && (
        <SignDialog
          siteId={siteId}
          inspection={signing}
          onClose={() => setSigning(null)}
          onDone={() => {
            setSigning(null);
            load();
          }}
        />
      )}
    </>
  );
}

function SignDialog({ siteId, inspection, onClose, onDone }: { siteId: number; inspection: PInspection; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [signature, setSignature] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/portal/sites/${siteId}/inspections/${inspection.id}/sign`, { method: "POST", json: { name, signature } });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title={`Sign off ${inspection.code}`} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Your name</span>
          <input className="tap-input" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <div className="field">
          <span>Signature</span>
          <SignaturePad onChange={setSignature} />
        </div>
        <div className="form-actions">
          <button className="btn btn-primary tap-wide" disabled={!name.trim() || !signature}>
            Sign
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- documents -----------------------------------------------------------------------------------

function DocumentsTab({ siteId }: { siteId: number }) {
  const { get, file, readOnly } = usePortal();
  const [list, setList] = useState<{ key: string; title: string; kind: string; source: string; revision: string | null; filename: string; date: string; url: string }[]>([]);
  const [title, setTitle] = useState("");
  const [upload, setUpload] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const load = useCallback(() => get<typeof list>(`/api/portal/sites/${siteId}/documents`).then(setList, (err) => setError(errorText(err))), [get, siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!upload) return;
    const form = new FormData();
    form.append("file", upload);
    form.append("title", title);
    form.append("kind", "drawing");
    try {
      await api(`/api/portal/sites/${siteId}/documents`, { method: "POST", form });
      setTitle("");
      setUpload(null);
      setMessage("Uploaded. EESPL has been told.");
      void load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-ok">{message}</div>}
      {list.length === 0 && <p className="empty">No documents shared yet.</p>}
      {list.map((d) => (
        <div key={d.key} className="card portal-item toolbar">
          <span>
            <strong>{d.title}</strong> {d.revision && <span className="badge badge-ok">{d.revision}</span>}
            <div className="muted small">
              {d.source === "You" ? "Uploaded by you" : "From EESPL"} · {day(d.date)}
            </div>
          </span>
          <button className="btn btn-small" onClick={() => void file(d.url).catch((err) => setError(errorText(err)))}>
            Download
          </button>
        </div>
      ))}
      {!readOnly && (
        <form className="card top-gap" onSubmit={send}>
          <h3 className="section-title">Upload your drawing</h3>
          <label className="field">
            <span>Title</span>
            <input className="tap-input" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label className="field">
            <span>File (PDF, photo, DWG or DXF)</span>
            <input type="file" accept=".pdf,image/*,.dwg,.dxf" onChange={(e) => setUpload(e.target.files?.[0] ?? null)} required />
          </label>
          <button className="btn btn-primary tap-wide" disabled={!upload || !title.trim()}>
            Upload
          </button>
        </form>
      )}
    </>
  );
}

// --- billing -------------------------------------------------------------------------------------

type PRa = {
  id: number;
  code: string;
  seq: number;
  period_from: string | null;
  period_to: string;
  status: string;
  gross: string;
  certified_gross: string | null;
  retention: string;
  advance_recovery: string;
  other_deduction: string;
  net: string;
  invoice_number: string | null;
  client_remark: string | null;
  lines: {
    contract_line_id: number;
    item_no: string | null;
    description: string;
    unit: string;
    qty: string;
    previous_qty: string;
    certified_qty: string | null;
    rate: string;
    amount: string;
    your_qty: string | null;
  }[];
};
type PInvoice = {
  id: number;
  number: string;
  kind: string;
  invoice_date: string;
  due_date: string | null;
  taxable: string;
  cgst: string;
  sgst: string;
  igst: string;
  total: string;
  outstanding: string | null;
  retention_held: string | null;
  due: string | null;
  age_days: number | null;
  credit_notes: { id: number; number: string; total: string }[];
};
type PBilling = {
  contract: { value: string; retention_percent: string; gst_percent: string } | null;
  ra_bills: PRa[];
  invoices: PInvoice[];
  receipts: { number: string; on_date: string; mode: string; ref_no: string | null; amount: string; tds_amount: string; is_advance: boolean }[];
  outstanding: Record<string, string>;
};

function BillingTab({ siteId }: { siteId: number }) {
  const { get, file, readOnly } = usePortal();
  const [data, setData] = useState<PBilling | null>(null);
  const [certifying, setCertifying] = useState<PRa | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => get<PBilling>(`/api/portal/sites/${siteId}/billing`).then(setData, (err) => setError(errorText(err))), [get, siteId]);
  useEffect(() => {
    void load();
  }, [load]);
  const dl = (path: string) => void file(path).catch((err) => setError(errorText(err)));
  async function reject(b: PRa) {
    const remark = prompt(`Why are you rejecting ${b.code}?`);
    if (!remark) return;
    try {
      await api(`/api/portal/sites/${siteId}/ra-bills/${b.id}/reject`, { method: "POST", json: { remark } });
      void load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  if (!data) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const o = data.outstanding;
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="portal-grid">
        <div className="card">
          <div className="muted small">Due now</div>
          <div className="portal-big">{inr(o.due)}</div>
          <div className="small">
            Total outstanding {inr(o.total)} (incl. retention {inr(o.retention_in_total)})
          </div>
          <div className="small muted">Due now is the outstanding less the retention held until handover.</div>
          <div className="chips">
            {["0-30", "31-60", "61-90", "90+"].map((b) => (
              <span key={b} className="chip">
                {b} days: {inr(o[b])}
              </span>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="muted small">Retention held</div>
          <div className="portal-big">{inr(o.retention_held)}</div>
          {data.contract && (
            <div className="small muted">
              Contract {inr(data.contract.value)} · retention {num(data.contract.retention_percent, 2)}%
            </div>
          )}
        </div>
      </div>

      <h3 className="section-title top-gap">RA bills</h3>
      {data.ra_bills.length === 0 && <p className="empty">No bills yet.</p>}
      {data.ra_bills.map((b) => (
        <div key={b.id} className="card portal-item">
          <div className="toolbar">
            <button className="as-button" onClick={() => setOpen(open === b.id ? null : b.id)}>
              <strong>{b.code}</strong> <span className="muted small">to {day(b.period_to)}</span>
            </button>
            <Badge status={b.status} />
          </div>
          <div className="portal-figures small">
            <span>Submitted {inr(b.gross)}</span>
            <span>Certified {b.certified_gross ? inr(b.certified_gross) : "—"}</span>
            <span>Net {inr(b.net)}</span>
          </div>
          {b.client_remark && <div className="small muted">Your remark: {b.client_remark}</div>}
          <div className="portal-buttons">
            <button className="btn btn-small" onClick={() => dl(`/api/portal/sites/${siteId}/ra-bills/${b.id}/pdf`)}>
              PDF
            </button>
            {b.status === "submitted" && !readOnly && (
              <>
                <button className="btn btn-small btn-primary" onClick={() => setCertifying(b)}>
                  Certify
                </button>
                <button className="btn btn-small btn-danger" onClick={() => void reject(b)}>
                  Reject
                </button>
              </>
            )}
          </div>
          {open === b.id && (
            <>
              <div className="table-wrap top-gap">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th className="num">This bill</th>
                      <th className="num">Certified</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {b.lines.map((l) => (
                      <tr key={l.contract_line_id}>
                        <td>
                          {l.item_no ? `${l.item_no}. ` : ""}
                          {l.description.split(" — ")[0]}
                        </td>
                        <td className="num">
                          {num(l.qty, 2)} {l.unit}
                        </td>
                        <td className="num">{l.certified_qty !== null ? num(l.certified_qty, 2) : l.your_qty !== null ? `${num(l.your_qty, 2)} (yours)` : "—"}</td>
                        <td className="num">{inr(l.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Thread entityType="ra_bill" entityId={b.id} />
            </>
          )}
        </div>
      ))}

      <h3 className="section-title top-gap">Tax invoices</h3>
      {data.invoices.length === 0 && <p className="empty">No invoices yet.</p>}
      {data.invoices.map((i) => (
        <div key={i.id} className="card portal-item">
          <div className="toolbar">
            <span>
              <strong>{i.number}</strong> <span className="muted small">{day(i.invoice_date)}</span>{" "}
              {i.kind === "credit_note" && <span className="badge badge-info">credit note</span>}
            </span>
            <button className="btn btn-small" onClick={() => dl(`/api/portal/sites/${siteId}/invoices/${i.id}/pdf`)}>
              PDF
            </button>
          </div>
          <div className="portal-figures small">
            <span>Total {inr(i.total)}</span>
            {i.outstanding !== null && <span>Outstanding {inr(i.outstanding)}</span>}
            {i.due !== null && Number(i.due) > 0 && (
              <span>
                Due {inr(i.due)} ({i.age_days} days)
              </span>
            )}
          </div>
          {i.credit_notes.length > 0 && <div className="small muted">Credit notes: {i.credit_notes.map((c) => `${c.number} (${inr(c.total)})`).join(", ")}</div>}
        </div>
      ))}

      <h3 className="section-title top-gap">Receipts</h3>
      {data.receipts.length === 0 && <p className="empty">No receipts yet.</p>}
      {data.receipts.length > 0 && (
        <div className="table-wrap">
          <table className="table compact">
            <tbody>
              {data.receipts.map((r) => (
                <tr key={r.number}>
                  <td>
                    {r.number}
                    <div className="muted small">
                      {day(r.on_date)} · {r.mode.toUpperCase()} {r.ref_no ?? ""}
                    </div>
                  </td>
                  <td className="num">
                    {inr(r.amount)}
                    {Number(r.tds_amount) > 0 && <div className="muted small">TDS {inr(r.tds_amount)}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {certifying && (
        <CertifyDialog
          siteId={siteId}
          bill={certifying}
          onClose={() => setCertifying(null)}
          onDone={() => {
            setCertifying(null);
            void load();
          }}
        />
      )}
    </>
  );
}

function CertifyDialog({ siteId, bill, onClose, onDone }: { siteId: number; bill: PRa; onClose: () => void; onDone: () => void }) {
  const billed = bill.lines.filter((l) => Number(l.qty) > 0);
  const [qty, setQty] = useState<Record<number, string>>(Object.fromEntries(billed.map((l) => [l.contract_line_id, l.qty])));
  const [remark, setRemark] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/api/portal/sites/${siteId}/ra-bills/${bill.id}/certify`, {
        method: "POST",
        json: { lines: Object.entries(qty).map(([k, v]) => ({ contract_line_id: Number(k), qty: v || "0" })), remark: remark || null },
      });
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title={`Certify ${bill.code}`} onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <p className="small muted">Enter the quantity you certify for each line. EESPL confirms it before it counts.</p>
        {billed.map((l) => (
          <label key={l.contract_line_id} className="field">
            <span>
              {l.description.split(" — ")[0]}{" "}
              <span className="muted">
                (billed {num(l.qty, 2)} {l.unit})
              </span>
            </span>
            <input
              className="tap-input"
              type="number"
              inputMode="decimal"
              min="0"
              max={l.qty}
              step="any"
              value={qty[l.contract_line_id]}
              onChange={(e) => setQty({ ...qty, [l.contract_line_id]: e.target.value })}
            />
          </label>
        ))}
        <label className="field">
          <span>Remark</span>
          <input className="tap-input" value={remark} onChange={(e) => setRemark(e.target.value)} />
        </label>
        <div className="form-actions">
          <button className="btn btn-primary tap-wide">Certify</button>
        </div>
      </form>
    </Modal>
  );
}

// --- snags ---------------------------------------------------------------------------------------

type PSnag = {
  id: number;
  code: string;
  title: string;
  description: string | null;
  area: string | null;
  status: string;
  raised_by_side: string;
  due_date: string | null;
  reopened: number;
  created_at: string;
  photos: { id: number; kind: string; filename: string }[];
};

function SnagsTab({ site }: { site: Overview }) {
  const { get, readOnly } = usePortal();
  const [list, setList] = useState<PSnag[]>([]);
  const [raising, setRaising] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => get<PSnag[]>(`/api/portal/sites/${site.id}/snags`).then(setList, (err) => setError(errorText(err))), [get, site.id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function act(s: PSnag, action: "verify" | "reopen") {
    let json: unknown;
    if (action === "reopen") {
      const remark = prompt("What is still wrong?");
      if (!remark) return;
      json = { remark };
    }
    try {
      await api(`/api/portal/sites/${site.id}/snags/${s.id}/${action}`, { method: "POST", json });
      void load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {!readOnly && (
        <button className="btn btn-primary tap-wide" onClick={() => setRaising(true)}>
          Raise a snag
        </button>
      )}
      {list.length === 0 && <p className="empty">No snags.</p>}
      {list.map((s) => (
        <div key={s.id} className="card portal-item">
          <div className="toolbar">
            <button className="as-button" onClick={() => setOpen(open === s.id ? null : s.id)}>
              <strong>{s.title}</strong>
            </button>
            <Badge status={s.status} />
          </div>
          <div className="muted small">
            {s.code} · {s.area ?? "site"} · raised by {s.raised_by_side === "client" ? "you" : "EESPL"} on {day(s.created_at)}
            {s.reopened > 0 && ` · reopened ${s.reopened}×`}
          </div>
          {s.status === "fixed" && !readOnly && (
            <div className="portal-buttons">
              <button className="btn btn-small btn-primary" onClick={() => void act(s, "verify")}>
                Verify fixed
              </button>
              <button className="btn btn-small" onClick={() => void act(s, "reopen")}>
                Reopen
              </button>
            </div>
          )}
          {s.status === "verified" && !readOnly && (
            <div className="portal-buttons">
              <button className="btn btn-small" onClick={() => void act(s, "reopen")}>
                Reopen
              </button>
            </div>
          )}
          {open === s.id && (
            <>
              {s.description && <p className="portal-text">{s.description}</p>}
              <div className="portal-photos">
                {s.photos.map((p) => (
                  <figure key={p.id}>
                    <Thumb path={`/api/portal/sites/${site.id}/snags/${s.id}/photos/${p.id}`} alt={p.filename} />
                    <figcaption className="small muted">{p.kind}</figcaption>
                  </figure>
                ))}
              </div>
              <Thread entityType="snag" entityId={s.id} />
            </>
          )}
        </div>
      ))}
      {raising && (
        <SnagForm
          site={site}
          onClose={() => setRaising(false)}
          onDone={() => {
            setRaising(false);
            void load();
          }}
        />
      )}
    </>
  );
}

export function SnagForm({ site, onClose, onDone }: { site: Pick<Overview, "id" | "parts">; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ title: "", description: "", node_id: "", area: "" });
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const data = new FormData();
    data.append("title", form.title);
    if (form.description) data.append("description", form.description);
    if (form.node_id) data.append("node_id", form.node_id);
    if (form.area) data.append("area", form.area);
    photos.forEach((p) => data.append("photos", p));
    setBusy(true);
    try {
      await api(`/api/portal/sites/${site.id}/snags`, { method: "POST", form: data });
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Raise a snag" onClose={onClose}>
      <form onSubmit={submit} className="snag-form">
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>What is wrong?</span>
          <input
            className="tap-input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            required
            maxLength={300}
            placeholder="e.g. Damp patch on the ceiling"
          />
        </label>
        <label className="field">
          <span>Where</span>
          <select className="tap-input" value={form.node_id} onChange={(e) => setForm({ ...form, node_id: e.target.value })}>
            <option value="">Somewhere else (type below)</option>
            {site.parts.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {!form.node_id && (
          <label className="field">
            <span>Area</span>
            <input className="tap-input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} placeholder="e.g. Flat 302, kitchen" />
          </label>
        )}
        <label className="field">
          <span>Details</span>
          <textarea className="tap-input" rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </label>
        <label className="field">
          <span>Photos</span>
          <input type="file" accept="image/*" capture="environment" multiple onChange={(e) => setPhotos([...photos, ...Array.from(e.target.files ?? [])])} />
          {photos.length > 0 && <span className="small muted">{photos.length} photo(s) added</span>}
        </label>
        <div className="form-actions">
          <button className="btn btn-primary tap-wide" disabled={busy || !form.title.trim()}>
            {busy ? "Sending…" : "Send to EESPL"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- comments ------------------------------------------------------------------------------------

type PComment = { id: number; body: string; internal: boolean; author: string | null; side: string; created_at: string };

/** A comment thread. In the portal internal notes never arrive; staff (`staff`) can add them. */
export function Thread({ entityType, entityId, staff = false }: { entityType: string; entityId: number; staff?: boolean }) {
  const portal = usePortal();
  const base = staff ? "/api/comments" : "/api/portal/comments";
  const [list, setList] = useState<PComment[]>([]);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      (staff ? api<PComment[]>(`${base}?entity_type=${entityType}&entity_id=${entityId}`) : portal.get<PComment[]>(`${base}?entity_type=${entityType}&entity_id=${entityId}`)).then(
        setList,
        (err) => setError(errorText(err)),
      ),
    [staff, base, entityType, entityId, portal],
  );
  useEffect(() => {
    void load();
  }, [load]);
  async function send(e: FormEvent) {
    e.preventDefault();
    try {
      await api(base, { method: "POST", json: { entity_type: entityType, entity_id: entityId, body, ...(staff ? { internal } : {}) } });
      setBody("");
      void load();
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div className="thread top-gap">
      {error && <div className="alert alert-error">{error}</div>}
      {list.map((c) => (
        <div key={c.id} className={`comment ${c.side} ${c.internal ? "internal" : ""}`}>
          <div className="small muted">
            {c.author ?? "—"} · {c.side === "client" ? "client" : "EESPL"} ·{" "}
            {new Date(c.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            {c.internal && <span className="badge badge-warn">internal</span>}
          </div>
          <div>{c.body}</div>
        </div>
      ))}
      {!portal.readOnly && (
        <form className="inline-form" onSubmit={send}>
          <input className="tap-input grow" value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a comment" required maxLength={4000} />
          {staff && (
            <label className="check small">
              <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> internal note
            </label>
          )}
          <button className="btn btn-small">Send</button>
        </form>
      )}
    </div>
  );
}

// --- invite --------------------------------------------------------------------------------------

export function InviteAccept() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState<{ full_name: string; email: string } | null>(null);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => {
    api<{ full_name: string; email: string }>(`/api/portal/invite/${token}`).then(setInfo, (err) => setError(err instanceof ApiError ? err.message : errorText(err)));
  }, [token]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== again) return setError("The two passwords differ");
    try {
      await api(`/api/portal/invite/${token}`, { method: "POST", json: { password } });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="brand-mark">E</span>
          <div>
            <h1>EESPL client portal</h1>
            <p className="muted">{info ? `Welcome, ${info.full_name}` : "Set your password"}</p>
          </div>
        </div>
        {error && <div className="alert alert-error">{error}</div>}
        {done ? (
          <>
            <div className="alert alert-ok">Your password is set. Sign in with {info?.email}.</div>
            <button type="button" className="btn btn-primary btn-block" onClick={() => navigate("/login")}>
              Go to sign in
            </button>
          </>
        ) : (
          info && (
            <>
              <label className="field">
                <span>Email</span>
                <input value={info.email} disabled />
              </label>
              <label className="field">
                <span>New password (10 characters or more)</span>
                <input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
              <label className="field">
                <span>Repeat it</span>
                <input type="password" autoComplete="new-password" minLength={10} value={again} onChange={(e) => setAgain(e.target.value)} required />
              </label>
              <button className="btn btn-primary btn-block">Set password</button>
            </>
          )
        )}
      </form>
    </div>
  );
}

export function Framed({ children }: { children: ReactNode }) {
  return <div className="portal portal-framed">{children}</div>;
}
