// "Work front ready": the supervisor ticks each place (block, floor, area) as it opens for our
// work, from the phone, with an optional photo. Indent drafts from a survey order for ready
// places only (planning can switch that off to order ahead).
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fetchObjectUrl } from "../../api";
import { useAuth } from "../../auth";
import { errorText } from "../../format";

type Node = {
  id: number;
  parent_id: number | null;
  kind: string;
  name: string;
  path: string;
  front_ready: boolean;
  front_ready_by_name: string | null;
  front_ready_at: string | null;
  front_ready_photo: boolean;
};

export default function WorkFronts() {
  const { id } = useParams();
  const { can } = useAuth();
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [site, setSite] = useState<{ code: string; name: string } | null>(null);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const mayTick = can("site.update", "site.edit");
  useEffect(() => {
    api<Node[]>(`/api/sites/${id}/nodes`).then(setNodes, (e) => setError(errorText(e)));
    api<{ code: string; name: string }>(`/api/sites/${id}`).then(setSite, () => undefined);
  }, [id]);
  async function mark(n: Node, ready: boolean, file?: File) {
    setBusy(n.id);
    setError("");
    const form = new FormData();
    form.append("ready", String(ready));
    if (file) form.append("photo", file);
    try {
      setNodes(await api<Node[]>(`/api/sites/${id}/nodes/${n.id}/front-ready`, { method: "POST", form }));
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(0);
  }
  async function show(n: Node) {
    setPhoto(await fetchObjectUrl(`/api/sites/${id}/nodes/${n.id}/front-ready/photo`));
  }
  const ready = nodes?.filter((n) => n.front_ready).length ?? 0;
  return (
    <div className="fronts-page">
      <div className="breadcrumb">
        <Link to={`/sites/${id}`}>{site ? `${site.code} · ${site.name}` : "Site"}</Link> / Work fronts
      </div>
      <h1>Work fronts</h1>
      <p className="muted small">
        Tick a place when it is open for our work. Material is ordered for ready places. {ready} of {nodes?.length ?? 0} ready.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {!nodes ? (
        <p className="muted">Loading…</p>
      ) : nodes.length === 0 ? (
        <p className="empty">No structure yet: add blocks and floors on the Structure tab.</p>
      ) : (
        <ul className="fronts">
          {nodes.map((n) => (
            <li key={n.id} className={n.front_ready ? "ready" : undefined} style={{ paddingLeft: `${(n.path.split(" › ").length - 1) * 14 + 8}px` }}>
              <div className="front-name">
                <b>{n.name}</b> <span className="muted small">{n.kind.replace("_", " ")}</span>
                {n.front_ready && (
                  <div className="small">
                    ✓ ready · {n.front_ready_by_name ?? "—"} ·{" "}
                    {n.front_ready_at ? new Date(n.front_ready_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}
                    {n.front_ready_photo && (
                      <button className="btn btn-small btn-ghost" onClick={() => void show(n)}>
                        photo
                      </button>
                    )}
                  </div>
                )}
              </div>
              {mayTick &&
                (n.front_ready ? (
                  <button className="btn btn-small" disabled={busy === n.id} onClick={() => void mark(n, false)}>
                    Not ready
                  </button>
                ) : (
                  <span className="front-actions">
                    <button className="btn btn-primary" disabled={busy === n.id} onClick={() => void mark(n, true)}>
                      Ready
                    </button>
                    <label className="btn btn-ghost">
                      📷
                      <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => e.target.files?.[0] && void mark(n, true, e.target.files[0])} />
                    </label>
                  </span>
                ))}
            </li>
          ))}
        </ul>
      )}
      {photo && (
        <div className="modal-backdrop" onMouseDown={() => setPhoto(null)}>
          <img className="front-photo" src={photo} alt="Work front" />
        </div>
      )}
    </div>
  );
}
