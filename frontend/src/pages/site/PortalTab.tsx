import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { errorText } from "../../format";
import { day, Framed, PortalSite } from "../../portal/Portal";
import type { Site } from "../../types";

type PortalUser = {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  is_active: boolean;
  has_password: boolean;
  last_login_at: string | null;
  has_site: boolean;
  invite: { expires_at: string; used: boolean; expired: boolean } | null;
};
type Settings = { site_id: number; client_id: number | null; client_name: string | null; visible: boolean; sections: Record<string, boolean>; users: PortalUser[] };
type Doc = { id: number; title: string; kind: string; source: "staff" | "client"; filename: string; share_with_client: boolean; created_at: string; by: string | null };

const SECTION_LABEL: Record<string, string> = {
  overview: "Overview & 3D",
  dpr: "Daily reports",
  photos: "Photos",
  inspections: "Inspections & MOM",
  documents: "Drawings & documents",
  billing: "Billing",
  snags: "Snags",
};

/** Staff: who of the client can see this site, what it shows, and a preview as that client. */
export default function PortalTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const manage = can("portal.manage");
  const [s, setS] = useState<Settings | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [link, setLink] = useState<{ name: string; url: string; expires_at: string } | null>(null);
  const [invite, setInvite] = useState({ full_name: "", email: "", phone: "" });
  const [preview, setPreview] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (manage) api<Settings>(`/api/portal-admin/sites/${site.id}`).then(setS, (err) => setError(errorText(err)));
    api<Doc[]>(`/api/portal-admin/sites/${site.id}/documents`).then(setDocs, () => setDocs([]));
  }, [manage, site.id]);
  useEffect(load, [load]);

  async function run<T>(p: Promise<T>): Promise<T | undefined> {
    setError(null);
    try {
      return await p;
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function save(next: Partial<Settings>) {
    if (!s) return;
    const r = await run(
      api<Settings>(`/api/portal-admin/sites/${site.id}`, { method: "PUT", json: { visible: next.visible ?? s.visible, sections: next.sections ?? s.sections } }),
    );
    if (r) setS(r);
  }
  function showLink(name: string, r: { link: string; expires_at: string }) {
    setLink({ name, url: `${window.location.origin}${r.link}`, expires_at: r.expires_at });
  }
  async function sendInvite(e: FormEvent) {
    e.preventDefault();
    if (!s?.client_id) return;
    const r = await run(
      api<{ link: string; expires_at: string }>("/api/portal-admin/invites", {
        method: "POST",
        json: { ...invite, phone: invite.phone || null, client_id: s.client_id, site_ids: [site.id] },
      }),
    );
    if (r) {
      showLink(invite.full_name, r);
      setInvite({ full_name: "", email: "", phone: "" });
      load();
    }
  }
  async function uploadDoc(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const r = await run(api<Doc>(`/api/portal-admin/sites/${site.id}/documents`, { method: "POST", form }));
    if (r) {
      e.currentTarget?.reset();
      load();
    }
  }

  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      {manage && s && (
        <>
          {!s.client_id && <div className="alert alert-warn">Set the site's client before sharing it in the portal.</div>}
          <div className="card">
            <label className="check">
              <input type="checkbox" checked={s.visible} onChange={(e) => void save({ visible: e.target.checked })} /> <strong>Visible in the client portal</strong>
            </label>
            <div className="checks top-gap">
              {Object.entries(SECTION_LABEL).map(([k, l]) => (
                <label key={k} className="check">
                  <input type="checkbox" checked={s.sections[k]} disabled={!s.visible} onChange={(e) => void save({ sections: { ...s.sections, [k]: e.target.checked } })} /> {l}
                </label>
              ))}
            </div>
            <p className="small muted">Costs, supplier rates, margins, budgets, salaries and wages are never shown in the portal.</p>
          </div>

          {link && (
            <div className="alert alert-ok top-gap">
              Invite link for {link.name} (one-time, expires {day(link.expires_at)}). No email or SMS is sent: copy it and send it yourself.
              <div className="inline-form top-gap">
                <input className="grow" readOnly value={link.url} onFocus={(e) => e.target.select()} />
                <button className="btn btn-small" onClick={() => void navigator.clipboard?.writeText(link.url)}>
                  Copy
                </button>
              </div>
            </div>
          )}

          <h3 className="section-title top-gap">Client users {s.client_name && <span className="muted small">({s.client_name})</span>}</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>This site</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {s.users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      {u.full_name}
                      <div className="muted small">
                        {u.email}
                        {u.phone ? ` · ${u.phone}` : ""}
                      </div>
                    </td>
                    <td className="small">
                      {!u.is_active ? (
                        <span className="badge badge-danger">disabled</span>
                      ) : u.has_password ? (
                        <span className="badge badge-ok">active</span>
                      ) : (
                        <span className="badge badge-warn">{u.invite?.expired ? "invite expired" : "invited"}</span>
                      )}
                      {u.last_login_at && <div className="muted">last in {day(u.last_login_at)}</div>}
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label="Can see this site"
                        checked={u.has_site}
                        onChange={(e) =>
                          void run(api<Settings>(`/api/portal-admin/users/${u.id}/sites`, { method: "PUT", json: { site_id: site.id, has_site: e.target.checked } })).then(
                            (r) => r && setS(r),
                          )
                        }
                      />
                    </td>
                    <td className="row-actions">
                      {!u.has_password && u.is_active && (
                        <button
                          className="btn btn-small"
                          onClick={() =>
                            void run(api<{ link: string; expires_at: string }>(`/api/portal-admin/users/${u.id}/reinvite`, { method: "POST" })).then(
                              (r) => r && (showLink(u.full_name, r), load()),
                            )
                          }
                        >
                          New link
                        </button>
                      )}
                      <button
                        className={`btn btn-small ${u.is_active ? "btn-danger" : ""}`}
                        onClick={() =>
                          (!u.is_active || confirm(`Disable ${u.full_name}? Their session ends at once.`)) &&
                          void run(api(`/api/portal-admin/users/${u.id}/active`, { method: "PUT", json: { is_active: !u.is_active } })).then(load)
                        }
                      >
                        {u.is_active ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                ))}
                {s.users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      No client users yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {s.client_id && (
            <form className="card top-gap" onSubmit={sendInvite}>
              <h3 className="section-title">Invite a client contact</h3>
              <div className="inline-form">
                <input className="grow" placeholder="Name" value={invite.full_name} onChange={(e) => setInvite({ ...invite, full_name: e.target.value })} required />
                <input className="grow" type="email" placeholder="Email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} required />
                <input placeholder="Phone" value={invite.phone} onChange={(e) => setInvite({ ...invite, phone: e.target.value })} />
                <button className="btn btn-primary">Create invite link</button>
              </div>
            </form>
          )}
        </>
      )}

      <h3 className="section-title top-gap">Documents</h3>
      <div className="table-wrap">
        <table className="table">
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>
                  <button className="as-button" onClick={() => void downloadFile(`/api/portal-admin/documents/${d.id}/file`).catch((err) => setError(errorText(err)))}>
                    {d.title}
                  </button>
                  <div className="muted small">
                    {d.source === "client" ? "Uploaded by the client" : "EESPL"} · {d.by ?? "—"} · {day(d.created_at)}
                  </div>
                </td>
                <td>
                  {d.source === "staff" ? (
                    <label className="check small">
                      <input
                        type="checkbox"
                        checked={d.share_with_client}
                        onChange={(e) => void run(api(`/api/portal-admin/documents/${d.id}/share`, { method: "PUT", json: { share: e.target.checked } })).then(load)}
                      />{" "}
                      Share with client
                    </label>
                  ) : (
                    <span className="badge badge-info">client's own</span>
                  )}
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr>
                <td className="empty">No documents yet. Drawings are shared from the Drawings tab.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <form className="inline-form top-gap" onSubmit={(e) => void uploadDoc(e)}>
        <input name="title" placeholder="Title" required className="grow" />
        <input name="file" type="file" accept=".pdf,image/*" required />
        <label className="check small">
          <input name="share_with_client" type="checkbox" value="true" /> Share with client
        </label>
        <button className="btn">Upload</button>
      </form>

      {manage && s && s.users.length > 0 && (
        <>
          <h3 className="section-title top-gap">Preview as client</h3>
          <div className="inline-form">
            <select value={preview} onChange={(e) => setPreview(e.target.value)}>
              <option value="">Choose a client user…</option>
              {s.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </select>
            {preview && (
              <button className="btn btn-small btn-ghost" onClick={() => setPreview("")}>
                Close preview
              </button>
            )}
          </div>
          {preview && (
            <Framed>
              <div className="alert alert-warn small">Preview: exactly what this client sees (read-only).</div>
              <PortalSite key={preview} siteId={site.id} preview={preview} />
            </Framed>
          )}
        </>
      )}
    </>
  );
}
