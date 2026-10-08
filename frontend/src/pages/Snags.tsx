import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, fetchObjectUrl, queryString } from "../api";
import { useAuth } from "../auth";
import Modal from "../components/Modal";
import { errorText } from "../format";
import { day, Thread } from "../portal/Portal";

type Snag = {
  id: number;
  code: string;
  site_id: number;
  site_code: string;
  title: string;
  description: string | null;
  area: string | null;
  status: "open" | "in_progress" | "fixed" | "verified" | "closed";
  raised_by_side: "client" | "staff";
  due_date: string | null;
  reopened: number;
  created_at: string;
  assigned_to: string | null;
  assigned_to_name: string | null;
  raised_by_name: string | null;
  photos: { id: number; kind: "before" | "after"; filename: string }[];
};

const BADGE: Record<string, string> = { open: "badge-danger", in_progress: "badge-warn", fixed: "badge-info", verified: "badge-ok", closed: "badge-muted" };
const STATUSES = ["open", "in_progress", "fixed", "verified", "closed"];

/** Snags across all the sites the user can see, raised by clients in the portal or by staff. */
export default function Snags() {
  const [params, setParams] = useSearchParams();
  const [list, setList] = useState<Snag[]>([]);
  const [sites, setSites] = useState<{ id: number; code: string; name: string }[]>([]);
  const [filters, setFilters] = useState({ site_id: "", status: "", side: "", open_only: "true" });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { can } = useAuth();
  const openId = Number(params.get("open")) || null;

  const load = useCallback(
    () =>
      api<Snag[]>(
        `/api/snags${queryString({ site_id: filters.site_id, status: filters.status, side: filters.side, open_only: filters.status ? undefined : filters.open_only || undefined })}`,
      ).then(setList, (err) => setError(errorText(err))),
    [filters],
  );
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    api<{ items: { id: number; code: string; name: string }[] }>("/api/sites?limit=200").then(
      (r) => setSites(r.items),
      () => setSites([]),
    );
  }, []);

  return (
    <>
      <div className="page-header">
        <h1>Snags</h1>
        {can("site.update") && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            New snag
          </button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="filters">
        <select value={filters.site_id} onChange={(e) => setFilters({ ...filters, site_id: e.target.value })} aria-label="Site">
          <option value="">All sites</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })} aria-label="Status">
          <option value="">Any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </select>
        <select value={filters.side} onChange={(e) => setFilters({ ...filters, side: e.target.value })} aria-label="Raised by">
          <option value="">Raised by anyone</option>
          <option value="client">Raised by the client</option>
          <option value="staff">Raised by staff</option>
        </select>
        {!filters.status && (
          <label className="check">
            <input type="checkbox" checked={filters.open_only === "true"} onChange={(e) => setFilters({ ...filters, open_only: e.target.checked ? "true" : "" })} /> Open only
          </label>
        )}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Site</th>
              <th>Snag</th>
              <th>Raised</th>
              <th>Assigned</th>
              <th>Due</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => setParams({ open: String(s.id) })}>
                <td>
                  <code>{s.code}</code>
                </td>
                <td>
                  <Link to={`/sites/${s.site_id}`} onClick={(e) => e.stopPropagation()}>
                    {s.site_code}
                  </Link>
                </td>
                <td>
                  {s.title}
                  <div className="muted small">{s.area ?? "—"}</div>
                </td>
                <td className="small">
                  {s.raised_by_side === "client" ? <span className="badge badge-orange">client</span> : "staff"} {day(s.created_at)}
                </td>
                <td className="small">{s.assigned_to_name ?? "—"}</td>
                <td className="nowrap small">{day(s.due_date)}</td>
                <td>
                  <span className={`badge ${BADGE[s.status]}`}>{s.status.replace("_", " ")}</span> {s.reopened > 0 && <span className="small muted">reopened {s.reopened}×</span>}
                </td>
              </tr>
            ))}
            {list.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  No snags.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {openId && <SnagDialog id={openId} onClose={() => setParams({})} onChange={() => void load()} />}
      {creating && (
        <NewSnag
          sites={sites}
          onClose={() => setCreating(false)}
          onDone={(id) => {
            setCreating(false);
            void load();
            setParams({ open: String(id) });
          }}
        />
      )}
    </>
  );
}

function SnagDialog({ id, onClose, onChange }: { id: number; onClose: () => void; onChange: () => void }) {
  const { me } = useAuth();
  const [s, setS] = useState<Snag | null>(null);
  const [images, setImages] = useState<Record<number, string | null>>({});
  const [staff, setStaff] = useState<{ id: string; full_name: string }[]>([]);
  const siteId = s?.site_id;
  useEffect(() => {
    if (siteId) api<{ id: string; full_name: string }[]>(`/api/snags/assignees?site_id=${siteId}`).then(setStaff, () => setStaff([]));
  }, [siteId]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Snag>(`/api/snags/${id}`).then(setS, (err) => setError(errorText(err)));
  }, [id]);
  useEffect(() => {
    if (!s) return;
    for (const p of s.photos) if (!(p.id in images)) void fetchObjectUrl(`/api/snags/${s.id}/photos/${p.id}`).then((u) => setImages((m) => ({ ...m, [p.id]: u })));
  }, [s, images]);

  async function patch(json: Record<string, unknown>) {
    setError(null);
    try {
      setS(await api<Snag>(`/api/snags/${id}`, { method: "PATCH", json }));
      onChange();
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function photo(file: File) {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", "after");
    try {
      setS(await api<Snag>(`/api/snags/${id}/photos`, { method: "POST", form }));
    } catch (err) {
      setError(errorText(err));
    }
  }
  if (!s) return null;
  const next: Record<string, [string, string][]> = {
    open: [
      ["in_progress", "Start work"],
      ["fixed", "Mark fixed"],
    ],
    in_progress: [["fixed", "Mark fixed"]],
    fixed:
      s.raised_by_side === "staff"
        ? [
            ["verified", "Verified"],
            ["in_progress", "Back to in progress"],
          ]
        : [["in_progress", "Back to in progress"]],
    verified: [["closed", "Close"]],
    closed: [],
  };
  return (
    <Modal title={`${s.code} · ${s.site_code}`} onClose={onClose} wide>
      {error && <div className="alert alert-error">{error}</div>}
      <p>
        <strong>{s.title}</strong> <span className={`badge ${BADGE[s.status]}`}>{s.status.replace("_", " ")}</span>
      </p>
      <p className="small muted">
        {s.area ?? "site"} · raised by {s.raised_by_side === "client" ? `the client (${s.raised_by_name ?? "—"})` : (s.raised_by_name ?? "staff")} on {day(s.created_at)}
        {s.status === "fixed" && s.raised_by_side === "client" && " · waiting for the client to verify"}
      </p>
      {s.description && <p>{s.description}</p>}
      <div className="photo-strip">
        {s.photos.map((p) => (
          <figure key={p.id}>
            {images[p.id] ? <img src={images[p.id]!} alt={p.filename} /> : <span className="muted small">{p.filename}</span>}
            <figcaption className="small muted">{p.kind}</figcaption>
          </figure>
        ))}
      </div>
      {s.status !== "closed" && (
        <div className="inline-form top-gap">
          <label className="btn btn-small">
            Add "after" photo
            <input type="file" hidden accept="image/*" capture="environment" onChange={(e) => e.target.files?.[0] && void photo(e.target.files[0])} />
          </label>
          <label className="small">
            Assigned to{" "}
            <select value={s.assigned_to ?? ""} onChange={(e) => e.target.value && void patch({ assigned_to: e.target.value })}>
              <option value="">— choose —</option>
              {staff.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                  {u.id === me?.user.id ? " (me)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="small">
            Due <input type="date" value={s.due_date ?? ""} onChange={(e) => void patch({ due_date: e.target.value || null })} />
          </label>
          {next[s.status].map(([st, l]) => (
            <button key={st} className="btn btn-small btn-primary" onClick={() => void patch({ status: st })}>
              {l}
            </button>
          ))}
        </div>
      )}
      <Thread entityType="snag" entityId={s.id} staff />
    </Modal>
  );
}

function NewSnag({ sites, onClose, onDone }: { sites: { id: number; code: string; name: string }[]; onClose: () => void; onDone: (id: number) => void }) {
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      const s = await api<Snag>("/api/snags", { method: "POST", form: new FormData(e.currentTarget) });
      onDone(s.id);
    } catch (err) {
      setError(errorText(err));
    }
  }
  return (
    <Modal title="New snag" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)}>
        {error && <div className="alert alert-error">{error}</div>}
        <label className="field">
          <span>Site</span>
          <select name="site_id" required>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Title</span>
          <input name="title" required maxLength={300} />
        </label>
        <label className="field">
          <span>Area</span>
          <input name="area" maxLength={200} />
        </label>
        <label className="field">
          <span>Details</span>
          <textarea name="description" rows={3} />
        </label>
        <label className="field">
          <span>Photos</span>
          <input name="photos" type="file" accept="image/*" multiple />
        </label>
        <div className="form-actions">
          <button className="btn btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
