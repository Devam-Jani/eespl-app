import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { Modal } from "../../ui/Overlay";
import { errorText } from "../../format";
import type { Drawing, DrawingRevision, Site } from "../../types";
import { useNodes } from "./StructureTab";
import { ShareTick } from "./TasksTab";
import { Button, buttonClass, Card, Field, FilePicker } from "../../ui/components";

// what the backend takes (DRAWING_TYPES in backend/app/sites/routers.py)
export const DRAWING_ACCEPT = ".pdf,.png,.jpg,.jpeg,.dwg,.dxf";
const REV_BADGE: Record<string, string> = { draft: "badge-muted", submitted: "badge-info", approved: "badge-ok", rejected: "badge-danger" };

export default function DrawingsTab({ site }: { site: Site }) {
  const { can } = useAuth();
  const canUpload = can("site.update", "site.edit");
  const canApprove = can("drawings.approve");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { nodes } = useNodes(site.id);
  const base = `/api/sites/${site.id}/drawings`;

  const load = useCallback(async () => {
    try {
      setDrawings(await api<Drawing[]>(base));
    } catch (err) {
      setError(errorText(err));
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(p: Promise<Drawing[]>) {
    setError(null);
    try {
      setDrawings(await p);
    } catch (err) {
      setError(errorText(err));
    }
  }

  function newRevision(d: Drawing, file: File) {
    const form = new FormData();
    form.append("file", file);
    void run(api<Drawing[]>(`${base}/${d.id}/revisions`, { method: "POST", form }));
  }

  function decide(d: Drawing, r: DrawingRevision, approve: boolean) {
    const remark = prompt(approve ? `Approve ${r.rev}? Remark (optional)` : `Reject ${r.rev}: why?`, "");
    if (remark === null) return;
    void run(api<Drawing[]>(`${base}/${d.id}/revisions/${r.id}/${approve ? "approve" : "reject"}`, { method: "POST", json: { remark: remark || null } }));
  }

  return (
    <Card as="div">
      <div className="toolbar">
        <h2 className="section-title">Drawings ({drawings.length})</h2>
        {canUpload && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            Upload drawing
          </Button>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {drawings.length === 0 && <p className="empty">No drawings yet.</p>}
      {drawings.map((d) => (
        <div key={d.id} className="scope-line">
          <div className="toolbar">
            <div>
              <strong>{d.title}</strong>{" "}
              <span className="muted small">
                {d.discipline}
                {d.node_path ? ` · ${d.node_path}` : ""}
              </span>
              {(canUpload || can("portal.manage")) && <ShareTick path={`/api/portal-admin/drawings/${d.id}/share`} shared={!!d.share_with_client} />}
              <div className="small">
                {d.latest_approved ? <span className="badge badge-ok">Approved: {d.latest_approved.rev}</span> : <span className="badge badge-warn">No approved revision</span>}
                {d.latest && d.latest.id !== d.latest_approved?.id && (
                  <span className="badge badge-info">
                    Latest: {d.latest.rev} ({d.latest.status})
                  </span>
                )}
              </div>
            </div>
            {canUpload && (
              <label className={buttonClass({ size: "small" })}>
                New revision
                <input type="file" hidden accept={DRAWING_ACCEPT} onChange={(e) => e.target.files?.[0] && newRevision(d, e.target.files[0])} />
              </label>
            )}
          </div>
          <table className="table compact">
            <tbody>
              {d.revisions.map((r) => (
                <tr key={r.id}>
                  <td>
                    <strong>{r.rev}</strong>
                  </td>
                  <td>
                    <button className="as-button" onClick={() => void downloadFile(`${base}/${d.id}/revisions/${r.id}/file`).catch((err) => setError(errorText(err)))}>
                      {r.filename}
                    </button>{" "}
                    <span className="muted small">{(r.size_bytes / 1024).toFixed(0)} KB</span>
                  </td>
                  <td className="muted small">
                    {r.uploaded_by_name ?? "—"} · {new Date(r.uploaded_at).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" })}
                  </td>
                  <td>
                    <span className={`badge ${REV_BADGE[r.status]}`}>{r.status}</span>
                    {r.approved_by_name && <span className="muted small"> by {r.approved_by_name}</span>}
                    {r.remark && <div className="small">{r.remark}</div>}
                  </td>
                  <td className="row-actions nowrap">
                    {canUpload && r.status === "draft" && (
                      <Button variant="ghost" size="small" onClick={() => void run(api<Drawing[]>(`${base}/${d.id}/revisions/${r.id}/submit`, { method: "POST" }))}>
                        Submit
                      </Button>
                    )}
                    {canApprove && (r.status === "draft" || r.status === "submitted") && (
                      <>
                        <Button size="small" onClick={() => decide(d, r, true)}>
                          Approve
                        </Button>
                        <Button variant="ghost" size="small" onClick={() => decide(d, r, false)}>
                          Reject
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {adding && (
        <UploadDrawing
          nodes={nodes.map((n) => ({ id: n.id, path: n.path }))}
          onClose={() => setAdding(false)}
          onUpload={async (form) => {
            await run(api<Drawing[]>(base, { method: "POST", form }));
            setAdding(false);
          }}
        />
      )}
    </Card>
  );
}

function UploadDrawing({ nodes, onClose, onUpload }: { nodes: { id: number; path: string }[]; onClose: () => void; onUpload: (f: FormData) => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [discipline, setDiscipline] = useState("waterproofing");
  const [node, setNode] = useState("");
  const [file, setFile] = useState<File | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("title", title);
    form.append("discipline", discipline);
    if (node) form.append("node_id", node);
    form.append("file", file);
    void onUpload(form);
  }
  return (
    <Modal title="Upload a drawing" onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Title *">
          <input required autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Discipline">
          <select value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
            {["architectural", "structural", "waterproofing", "other"].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </Field>
        <Field label="Place (optional)">
          <select value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">Whole site</option>
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.path}
              </option>
            ))}
          </select>
        </Field>
        <Field as="div" label="File (PDF, PNG, JPG or DWG, up to 50 MB) — saved as R0">
          <FilePicker label="Choose the drawing" required accept={DRAWING_ACCEPT} onFiles={(fs) => setFile(fs[0] ?? null)} />
        </Field>
        <div className="form-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!file}>
            Upload
          </Button>
        </div>
      </form>
    </Modal>
  );
}
