// The role SOPs in the app (docs/sop, assembled by the backend): Help > How to reads the person's own
// role's SOP (the super admin and the director may pick any); the "How to" link at the top of each
// page (HowTo.tsx) opens that page's section in it.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import { Select } from "../ui/components";

type SopRef = { role: string; title: string; mine: boolean };
type Section = { id: string; title: string; page: string; html: string };
type Sop = { role: string; title: string; version: string; sections: Section[] };

export default function SopPage() {
  const [params, setParams] = useSearchParams();
  const page = params.get("page") ?? "";
  const [list, setList] = useState<SopRef[] | null>(null);
  const [role, setRole] = useState<string>(params.get("role") ?? "");
  const [target, setTarget] = useState<string>("");
  const [sop, setSop] = useState<Sop | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<{ sops: SopRef[]; open: { role: string; id: string } | null }>(`/api/sop${page ? `?page=${encodeURIComponent(page)}` : ""}`).then(
      (r) => {
        setList(r.sops);
        const pick = params.get("role") || r.open?.role || r.sops.find((s) => s.mine)?.role || r.sops[0]?.role || "";
        setRole(pick);
        setTarget(r.open && r.open.role === pick ? r.open.id : window.location.hash.slice(1));
      },
      (e) => setError(errorText(e)),
    );
    // the list is loaded once per page asked for
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  useEffect(() => {
    if (!role) return;
    setSop(null);
    api<Sop>(`/api/sop/${encodeURIComponent(role)}`).then(setSop, (e) => setError(errorText(e)));
  }, [role]);

  useEffect(() => {
    if (!sop || !target) return;
    document.getElementById(`sop-${target}`)?.scrollIntoView({ block: "start" });
  }, [sop, target]);

  if (error) return <p className="error">{error}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  if (!list.length) return <p className="muted">There is no SOP for your role yet.</p>;
  const others = list.length > 1;
  return (
    <div className="sop">
      <div className="sop-head">
        <h1>How to: {sop?.title ?? ""}</h1>
        {others && (
          <Select
            label="SOP for"
            value={role}
            onChange={(v) => {
              setTarget("");
              setRole(v);
              setParams({ role: v });
            }}
            options={list.map((s) => ({ value: s.role, label: s.mine ? `${s.title} (yours)` : s.title }))}
          />
        )}
      </div>
      {sop && (
        <>
          <p className="muted small">
            Version {sop.version}. Practise in the training company first: it is reset every night. The printed copy (PDF or Word) has the pictures.
          </p>
          <nav className="sop-toc" aria-label="Contents">
            <ol>
              {sop.sections
                .filter((s) => s.title)
                .map((s) => (
                  <li key={s.id}>
                    <a href={`#sop-${s.id}`} onClick={() => setTarget(s.id)}>
                      {s.title}
                    </a>
                  </li>
                ))}
            </ol>
          </nav>
          {sop.sections.map((s) => (
            <section key={s.id} id={`sop-${s.id}`} className={`sop-section${s.id === target ? " sop-here" : ""}`} aria-label={s.title || undefined}>
              {s.title && <h2>{s.title}</h2>}
              {s.page && <p className="muted small">Page: {s.page}</p>}
              {/* our own text from docs/sop, rendered by the backend (escaped, links to app pages only) */}
              <div className="sop-body" dangerouslySetInnerHTML={{ __html: s.html }} />
            </section>
          ))}
        </>
      )}
    </div>
  );
}
