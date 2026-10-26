// The site's material request, in place of the WhatsApp order: on the phone the site engineer asks
// by area and thickness and sees the working as it is typed ("280 sqm × 10.7639 × 2.77 kg/sqft =
// 8,349 kg = 334 bags of 25 kg") against what the estimate has left; planning approves (or changes,
// with a note) and it becomes an indent.
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { errorText, num } from "../format";
import { BackButton, Button, Card, EmptyState, Field, PageSkeleton } from "../ui/components";
import { Modal, useToast } from "../ui/Overlay";
import { Table } from "../ui/Table";
import { E, REQUEST_BADGE, REQUEST_STATUS, when } from "./common";
import type { MaterialRequest } from "./common";
import "./estimate.css";

type AskForm = {
  site: { id: number; code: string; name: string };
  estimate: { id: number; code: string; status: string } | null;
  products: { id: number; name: string; unit: string; mix_design_id: number | null; thickness_mm: string | null; pack_size: string | null; pack_unit: string | null }[];
  areas: { id: number; code: string | null; name: string; floor_sqm: string }[];
  mixes: { id: number; name: string; thickness_mm: string }[];
  requests: MaterialRequest[];
};

type Preview = { qty: string; formula: string; packs: number | null; left: string | null; over: boolean };

function Status({ r }: { r: MaterialRequest }) {
  return <span className={`badge ${REQUEST_BADGE[r.status] ?? "badge-muted"}`}>{REQUEST_STATUS[r.status] ?? r.status}</span>;
}

// --- the phone: ask for material ----------------------------------------------------------------

export function AskMaterial() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [form, setForm] = useState<AskForm | null>(null);
  const [error, setError] = useState("");
  const [f, setF] = useState({ product_id: "", estimate_area_id: "", area_sqm: "", thickness_mm: "", reason: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api<AskForm>(`${E}/sites/${id}/ask`).then(setForm, (e) => setError(errorText(e)));
  useEffect(() => {
    void load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const product = form?.products.find((p) => String(p.id) === f.product_id);
  const mix = product?.mix_design_id ? form?.mixes.find((m) => m.id === product.mix_design_id) : undefined;
  const body = {
    site_id: Number(id),
    product_id: Number(f.product_id),
    area_sqm: f.area_sqm,
    thickness_mm: mix && f.thickness_mm ? f.thickness_mm : null,
    mix_design_id: mix?.id ?? null,
    estimate_area_id: f.estimate_area_id ? Number(f.estimate_area_id) : null,
  };
  const key = JSON.stringify(body);

  // the working as it is typed
  useEffect(() => {
    setPreview(null);
    setPreviewError("");
    if (!f.product_id || !(Number(f.area_sqm) > 0)) return;
    const t = window.setTimeout(() => {
      api<Preview>(`${E}/requests`, { method: "POST", json: { ...body, preview: true } }).then(setPreview, (e) => setPreviewError(errorText(e) || "The working could not be shown"));
    }, 300);
    return () => window.clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<MaterialRequest>(`${E}/requests`, { method: "POST", json: { ...body, reason: f.reason || null } });
      toast.show({ text: `${r.code} sent to planning: ${r.formula}` });
      setF({ product_id: "", estimate_area_id: "", area_sqm: "", thickness_mm: "", reason: "" });
      void load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  if (!form) return error ? <div className="alert alert-error">{error}</div> : <PageSkeleton label="Loading" />;
  return (
    <div className="ask-page">
      <header className="report-head">
        <BackButton onClick={() => navigate(`/my-site/${id}`)} label="Back to my site" />
        <div className="report-title">
          <span className="muted small">
            {form.site.code} · {form.site.name}
          </span>
          <h1>Ask for material</h1>
        </div>
      </header>
      {!form.estimate ? (
        <EmptyState title="No material estimate for this site yet" hint="Planning makes the estimate first: the materials and areas come from it." />
      ) : (
        <Card as="form" onSubmit={(e: FormEvent) => void send(e)}>
          <Field label="Material">
            <select required value={f.product_id} onChange={(e) => {
              const p = form.products.find((x) => String(x.id) === e.target.value);
              const m = p?.mix_design_id ? form.mixes.find((x) => x.id === p.mix_design_id) : undefined;
              setF({ ...f, product_id: e.target.value, thickness_mm: p?.thickness_mm ?? m?.thickness_mm ? String(Number(p?.thickness_mm ?? m?.thickness_mm)) : "" });
            }}>
              <option value="">— material —</option>
              {form.products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.unit})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Area of the estimate" hint="Optional: the request is checked against what that area has left">
            <select value={f.estimate_area_id} onChange={(e) => {
              const a = form.areas.find((x) => String(x.id) === e.target.value);
              setF({ ...f, estimate_area_id: e.target.value, area_sqm: f.area_sqm || (a ? String(Number(a.floor_sqm)) : "") });
            }}>
              <option value="">— the whole site —</option>
              {form.areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code ? `${a.code} ` : ""}
                  {a.name} ({num(a.floor_sqm, 2)} sqm)
                </option>
              ))}
            </select>
          </Field>
          <Field label="Area to do (sqm)">
            <input type="number" inputMode="decimal" min="0" step="any" required value={f.area_sqm} onChange={(e) => setF({ ...f, area_sqm: e.target.value })} />
          </Field>
          {mix && (
            <Field label="Thickness (mm)" hint={mix.name}>
              <input type="number" inputMode="decimal" min="0" max="1000" step="any" value={f.thickness_mm} onChange={(e) => setF({ ...f, thickness_mm: e.target.value })} />
            </Field>
          )}
          {preview && (
            <div className={`alert ${preview.over ? "alert-warn" : "alert-info"}`} aria-live="polite">
              <p className="ask-formula">{preview.formula}</p>
              {preview.left !== null && (
                <p className="ask-left">
                  The estimate has <strong>{num(preview.left, 2)} {product?.unit}</strong> left{f.estimate_area_id ? " for this area" : ""}
                  {preview.over ? ": this is more." : "."}
                </p>
              )}
            </div>
          )}
          {previewError && <div className="alert alert-error">{previewError}</div>}
          {preview?.over && (
            <Field label="Why more than the estimate">
              <textarea required rows={3} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
            </Field>
          )}
          {error && <div className="alert alert-error">{error}</div>}
          <Button type="submit" variant="primary" block loading={busy} disabled={!preview}>
            Send to planning
          </Button>
        </Card>
      )}
      <Card title="This site's requests" size="small">
        {form.requests.length === 0 ? (
          <EmptyState title="No request yet" />
        ) : (
          <ul className="ask-requests">
            {form.requests.map((r) => (
              <li key={r.id}>
                <div>
                  <strong>{r.code}</strong> {r.product} <Status r={r} />
                </div>
                <div className="small">{r.formula}</div>
                <div className="small muted">
                  {when(r.created_at)}
                  {r.area ? ` · ${r.area}` : ""}
                  {r.indent ? ` · indent ${r.indent.code}` : ""}
                  {r.approved_qty && Number(r.approved_qty) !== Number(r.qty) ? ` · approved ${num(r.approved_qty, 2)} ${r.unit}` : ""}
                  {r.change_note ? ` · ${r.change_note}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// --- planning: the requests ---------------------------------------------------------------------

export default function MaterialRequests() {
  const { can } = useAuth();
  const [rows, setRows] = useState<MaterialRequest[] | null>(null);
  const [error, setError] = useState("");
  const [deciding, setDeciding] = useState<{ r: MaterialRequest; approve: boolean } | null>(null);
  const load = () => api<MaterialRequest[]>(`${E}/requests`).then(setRows, (e) => setError(errorText(e)));
  useEffect(() => {
    void load();
  }, []);
  const approver = can("material_request.approve");
  return (
    <>
      <div className="page-header">
        <h1>Material requests</h1>
      </div>
      <p className="muted">What the sites ask for, worked out from the library and checked against the estimate. Approving raises the indent.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {!rows && !error && <PageSkeleton />}
      {rows && (
        <Card>
          <Table
            rows={rows}
            rowKey={(r) => r.id}
            cards
            label="Material requests"
            filters={[
              { key: "open", label: "Waiting", test: (r) => r.status === "requested" },
              { key: "over", label: "Over the estimate", test: (r) => !!r.over_reason },
              { key: "all", label: "All", test: () => true },
            ]}
            empty={{ title: "Nothing here", hint: "The sites ask from their phone: My site → Ask for material." }}
            columns={[
              {
                key: "code",
                label: "Request",
                render: (r) => (
                  <>
                    <strong>{r.code}</strong> {r.product}
                    <div className="small muted">{when(r.created_at)}</div>
                  </>
                ),
                sort: (r) => r.id,
              },
              { key: "site", label: "Site", render: (r) => <Link to={`/sites/${r.site_id}`}>{r.site ?? `Site ${r.site_id}`}</Link> },
              { key: "area", label: "Area", render: (r) => r.area ?? "—" },
              { key: "formula", label: "Working", render: (r) => <span className="small">{r.formula}</span> },
              {
                key: "left",
                label: "Left before",
                num: true,
                render: (r) => (r.left_before === null ? "—" : `${num(r.left_before, 2)} ${r.unit ?? ""}`),
              },
              {
                key: "over",
                label: "Over the estimate",
                render: (r) => (r.over_reason ? <span className="badge badge-danger" title={r.over_reason}>Over: {r.over_reason}</span> : "—"),
              },
              {
                key: "status",
                label: "Status",
                render: (r) => (
                  <>
                    <Status r={r} />
                    {r.approved_qty && Number(r.approved_qty) !== Number(r.qty) && (
                      <div className="small">
                        Changed to {num(r.approved_qty, 2)} {r.unit}: {r.change_note}
                      </div>
                    )}
                    {r.status === "rejected" && r.change_note && <div className="small">{r.change_note}</div>}
                    {r.indent && (
                      <div className="small">
                        <Link to={`/indents?open=${r.indent.id}`}>Indent {r.indent.code}</Link> ({r.indent.status.replace(/_/g, " ")})
                      </div>
                    )}
                  </>
                ),
              },
              {
                key: "act",
                label: "",
                render: (r) =>
                  approver && r.status === "requested" ? (
                    <div className="row-actions">
                      <Button size="small" variant="primary" onClick={() => setDeciding({ r, approve: true })}>
                        Approve…
                      </Button>
                      <Button size="small" onClick={() => setDeciding({ r, approve: false })}>
                        Refuse…
                      </Button>
                    </div>
                  ) : null,
              },
            ]}
          />
        </Card>
      )}
      {deciding && <Decide {...deciding} onClose={() => setDeciding(null)} onDone={() => void load()} />}
    </>
  );
}

function Decide({ r, approve, onClose, onDone }: { r: MaterialRequest; approve: boolean; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState(String(Number(r.qty)));
  const [note, setNote] = useState("");
  const [by, setBy] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const changed = approve && Number(qty) !== Number(r.qty);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`${E}/requests/${r.id}/decide`, {
        method: "POST",
        json: approve ? { approve: true, qty: changed ? qty : null, note: note || null, required_by: by || null } : { approve: false, note },
      });
      onDone();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`${approve ? "Approve" : "Refuse"} ${r.code}`} onClose={onClose}>
      <form onSubmit={save}>
        <p>
          <strong>{r.product}</strong>: {r.formula}
        </p>
        {r.over_reason && <div className="alert alert-warn">Over the estimate ({num(r.left_before, 2)} {r.unit} left): {r.over_reason}</div>}
        {approve && (
          <div className="grid-2">
            <Field label={`Quantity (${r.unit ?? ""})`} hint="Change it only with a note">
              <input type="number" min="0" step="any" required value={qty} onChange={(e) => setQty(e.target.value)} />
            </Field>
            <Field label="Required by" hint="Optional">
              <input type="date" value={by} onChange={(e) => setBy(e.target.value)} />
            </Field>
          </div>
        )}
        <Field label={approve ? (changed ? "Why the quantity is changed" : "Note (optional)") : "Why it is refused"}>
          <textarea required={!approve || changed} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="form-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant={approve ? "primary" : "danger"} loading={busy}>
            {approve ? "Approve and raise the indent" : "Refuse"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
