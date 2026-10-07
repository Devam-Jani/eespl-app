import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { errorText, inr } from "../../format";
import type { Grn, Indent, Issue, SiteMaterialSummary, Transfer } from "../../material/types";
import type { Page, Site } from "../../types";
import { GrnForm, GrnTable, GrnView } from "../material/Grns";
import { IndentForm, IndentTable, IndentView } from "../material/Indents";
import { IssueForm, IssueTable, ReceiveForm, StockTable, TransferForm, TransferTable } from "../material/Stores";
import { useMaterialLookups } from "../material/common";

/** A site's material: its store's stock, indents, transfers in, GRNs, issues and freight. */
export default function MaterialTab({ site }: { site: Site }) {
  const lookups = useMaterialLookups();
  const [summary, setSummary] = useState<SiteMaterialSummary | null>(null);
  const [indents, setIndents] = useState<Indent[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [grns, setGrns] = useState<Grn[]>([]);
  const [dialog, setDialog] = useState<null | "indent" | "issue" | "return" | "transfer" | "grn">(null);
  const [openIndent, setOpenIndent] = useState<Indent | null>(null);
  const [openGrn, setOpenGrn] = useState<Grn | null>(null);
  const [receiving, setReceiving] = useState<Transfer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api<SiteMaterialSummary>(`/api/material/sites/${site.id}/summary`);
      setSummary(s);
      const p = s.permissions;
      if (p["indent.view"]) setIndents((await api<Page<Indent>>(`/api/material/indents?site_id=${site.id}&limit=100`)).items);
      if (p["store.view"]) {
        setTransfers((await api<Page<Transfer>>(`/api/material/transfers?site_id=${site.id}&limit=100`)).items);
        setIssues((await api<Page<Issue>>(`/api/material/issues?site_id=${site.id}&limit=100`)).items);
      }
      if (p["grn.view"] && s.store) setGrns((await api<Page<Grn>>(`/api/material/grns?store_id=${s.store.id}&limit=100`)).items);
    } catch (err) {
      setError(errorText(err));
    }
  }, [site.id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!summary) return error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>;
  const p = summary.permissions;
  const done = async () => {
    setDialog(null);
    await load();
  };

  return (
    <>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="tiles">
        <div className="tile">
          <div className="tile-title">Stock at site</div>
          <b>{inr(summary.store?.value ?? 0)}</b>
          {summary.store && (
            <div className="small">
              <Link to={`/stores/${summary.store.id}`}>{summary.store.name}</Link>
            </div>
          )}
        </div>
        <div className="tile">
          <div className="tile-title">Issued to work</div>
          <b>{inr(Number(summary.issued_value) - Number(summary.returned_value))}</b>
          <div className="small muted">net of returns</div>
        </div>
        <div className="tile">
          <div className="tile-title">Freight charged</div>
          <b>{inr(summary.freight.total)}</b>
          <div className="small muted">
            inbound {inr(summary.freight.inbound)} · godown → site {inr(summary.freight.godown_to_site)}
          </div>
        </div>
      </div>
      {lookups && (
        <div className="page-actions top-gap">
          {p["indent.create"] && (
            <button className="btn btn-primary" onClick={() => setDialog("indent")}>
              New indent
            </button>
          )}
          {p["grn.edit"] && summary.store && (
            <button className="btn" onClick={() => setDialog("grn")}>
              Receive material (GRN)
            </button>
          )}
          {p["store.edit"] && (
            <>
              <button className="btn" onClick={() => setDialog("issue")}>
                Issue to work
              </button>
              <button className="btn" onClick={() => setDialog("return")}>
                Return to store
              </button>
              <button className="btn" onClick={() => setDialog("transfer")}>
                Request / send transfer
              </button>
            </>
          )}
        </div>
      )}
      {p["store.view"] && (
        <>
          <h2 className="section-title top-gap">Stock</h2>
          <StockTable rows={summary.stock} />
        </>
      )}
      {p["indent.view"] && (
        <>
          <h2 className="section-title top-gap">Indents</h2>
          <IndentTable indents={indents} onOpen={setOpenIndent} hideSite />
        </>
      )}
      {p["store.view"] && (
        <>
          <h2 className="section-title top-gap">Transfers</h2>
          <TransferTable transfers={transfers} onReceive={setReceiving} onChanged={load} />
          <h2 className="section-title top-gap">Issues &amp; returns</h2>
          <IssueTable issues={issues} />
        </>
      )}
      {p["grn.view"] && (
        <>
          <h2 className="section-title top-gap">Received at site (GRN)</h2>
          <GrnTable grns={grns} onOpen={setOpenGrn} />
        </>
      )}
      {lookups && dialog === "indent" && <IndentForm lookups={lookups} siteId={site.id} onClose={() => setDialog(null)} onSaved={done} />}
      {lookups && (dialog === "issue" || dialog === "return") && (
        <IssueForm lookups={lookups} kind={dialog} siteId={site.id} storeId={summary.store?.id} onClose={() => setDialog(null)} onSaved={done} />
      )}
      {lookups && dialog === "transfer" && <TransferForm lookups={lookups} toStoreId={summary.store?.id} onClose={() => setDialog(null)} onSaved={done} />}
      {lookups && dialog === "grn" && <GrnForm lookups={lookups} storeId={summary.store?.id} onClose={() => setDialog(null)} onSaved={done} />}
      {openIndent && lookups && <IndentView indent={openIndent} lookups={lookups} onClose={() => setOpenIndent(null)} onChange={async (i) => (setOpenIndent(i), await load())} />}
      {openGrn && <GrnView grn={openGrn} onClose={() => setOpenGrn(null)} onChange={async (g) => (setOpenGrn(g), await load())} />}
      {receiving && <ReceiveForm transfer={receiving} onClose={() => setReceiving(null)} onSaved={async () => (setReceiving(null), await load())} />}
    </>
  );
}
