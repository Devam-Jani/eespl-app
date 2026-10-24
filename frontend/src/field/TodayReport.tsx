// Today's report on the site engineer's phone (EESPL UI v1, Figma 03): the place and its step, the
// work done as big buttons, the length in ft + in (a wrong entry offers its one-tap fix), photos
// from the camera, and one send button that says what is missing until the report is complete.
// Without signal the report is kept on the phone and sent when the signal is back.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import type { SiteTask } from "../types";
import { BackButton, Button, EmptyState, Icon, ProgressBar, Skeleton } from "../ui/components";
import { checkFtIn, FtInInput } from "../ui/FtIn";
import { useToast } from "../ui/Overlay";
import { flush, sendOrKeep, type QueuedReport } from "./reportQueue";

type Place = { node_id: number; name: string; floor: string; steps: SiteTask[]; current: SiteTask | null; at: number };
type Choice = "done" | "part" | "none";

const todayIso = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

/** The places to report today: those with a step under way or due to start, their current step. */
export function placesToday(tasks: SiteTask[], day: string): Place[] {
  const by = new Map<number, SiteTask[]>();
  for (const t of tasks) if (t.node_id !== null) by.set(t.node_id, [...(by.get(t.node_id) ?? []), t]);
  const out: Place[] = [];
  for (const [node_id, list] of by) {
    const steps = [...list].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
    const current = steps.find((t) => t.status !== "done" && t.status !== "certified") ?? null;
    if (!current) continue;
    const due = current.status === "in_progress" || current.status === "blocked" || (current.planned_start !== null && current.planned_start <= day);
    if (!due) continue;
    const path = (current.node_path ?? "").split(" › ");
    out.push({ node_id, name: path[path.length - 1] || current.name, floor: path.length > 1 ? path[path.length - 2] : "", steps, current, at: steps.indexOf(current) + 1 });
  }
  return out.sort((a, b) => a.floor.localeCompare(b.floor) || a.name.localeCompare(b.name));
}

/** What the send button says: the first thing missing, else what it will do. */
export function sendLabel(choice: Choice | null, ft: string, inch: string, photos: number, needsLength: boolean): { ready: boolean; label: string } {
  if (!choice) return { ready: false, label: "Choose the work done to send" };
  if (choice !== "none" && needsLength && !checkFtIn(ft, inch).ok) return { ready: false, label: "Fix the length to send" };
  if (choice !== "none" && photos === 0) return { ready: false, label: "Add a photo to send" };
  return { ready: true, label: "Send today's report" };
}

const DONE_KEY = (site: string, day: string) => `eespl.report.${site}.${day}`;

export default function TodayReport() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const day = todayIso();
  const [site, setSite] = useState<{ code: string; name: string } | null>(null);
  const [tasks, setTasks] = useState<SiteTask[] | null>(null);
  const [pick, setPick] = useState<number | null>(null);
  const [changing, setChanging] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [ft, setFt] = useState("");
  const [inch, setInch] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState(false);
  const [fullName, setFullName] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<number[]>(() => {
    try {
      return JSON.parse(window.localStorage.getItem(DONE_KEY(id, day)) ?? "[]") as number[];
    } catch {
      return [];
    }
  });

  const load = useCallback(() => {
    api<{ code: string; name: string }>(`/api/sites/${id}`).then(setSite, (e) => setError(errorText(e)));
    api<SiteTask[]>(`/api/sites/${id}/tasks`).then(setTasks, (e) => setError(errorText(e)));
  }, [id]);
  useEffect(load, [load]);
  // what was kept on the phone goes when the signal is back
  useEffect(() => {
    const go = () =>
      void flush().then(({ sent, left }) => {
        if (sent) toast.show({ text: `${sent} report${sent > 1 ? "s" : ""} sent now that the signal is back.` });
        setKept(left > 0);
      });
    go();
    window.addEventListener("online", go);
    return () => window.removeEventListener("online", go);
  }, [toast]);

  const places = useMemo(() => (tasks ? placesToday(tasks, day) : []), [tasks, day]);
  const place = places.find((p) => p.node_id === pick) ?? places.find((p) => !done.includes(p.node_id)) ?? places[0] ?? null;
  const count = places.filter((p) => done.includes(p.node_id)).length;
  const step = place?.current ?? null;
  const send = sendLabel(choice, ft, inch, photos.length, true);
  const previews = useMemo(() => photos.map((p) => URL.createObjectURL(p)), [photos]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  function reset() {
    setChoice(null);
    setFt("");
    setInch("");
    setPhotos([]);
    setPick(null);
  }

  async function submit() {
    if (!place || !step || !send.ready) return;
    setBusy(true);
    setError(null);
    const len = checkFtIn(ft, inch);
    const what = choice === "done" ? `${step.name}: done` : choice === "part" ? `${step.name}: part done` : `${step.name}: no work today`;
    const report: QueuedReport = {
      id: `${id}-${day}-${place.node_id}-${Date.now()}`,
      site_id: Number(id),
      day,
      line: { description: `${place.name} · ${what}${len.ok ? ` · ${len.feet} ft ${len.inches} in` : ""}`, qty: len.ok && choice !== "none" ? len.metres : null, unit: len.ok && choice !== "none" ? "m" : null, node_id: place.node_id, area_scope_id: step.area_scope_id },
      photos,
      submit: count + 1 >= places.length,
      at: Date.now(),
    };
    try {
      const how = await sendOrKeep(report);
      const next = [...done, place.node_id];
      setDone(next);
      try {
        window.localStorage.setItem(DONE_KEY(id, day), JSON.stringify(next));
      } catch {
        // storage blocked: the count restarts on reload
      }
      setKept(how === "kept");
      toast.show({ text: how === "sent" ? `${place.name}: sent.` : `${place.name}: saved on the phone; it sends when the signal is back.` });
      reset();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !tasks) return <div className="alert alert-error">{error}</div>;

  return (
    <div className="report">
      <header className="report-head">
        <BackButton onClick={() => navigate(`/my-site/${id}`)} label="Back to my site" />
        <div className="report-title">
          {/* one line; the full name on tap */}
          <button type="button" className={`report-site muted small ${fullName ? "full" : ""}`} onClick={() => setFullName(!fullName)} title={site?.name} aria-expanded={fullName}>
            {site?.name ?? ""}
            {place?.floor ? ` · ${place.floor}` : ""}
          </button>
          <h1>Today's report</h1>
        </div>
        {places.length > 0 && (
          <span className="chip chip-count">
            {count} of {places.length} done
          </span>
        )}
      </header>
      <ProgressBar value={places.length ? (count / places.length) * 100 : 0} thin label={`${count} of ${places.length} places reported`} />

      {!tasks ? (
        <Skeleton height={70} lines={4} />
      ) : !place || !step ? (
        <EmptyState title="Nothing to report today" hint="No step on this site is under way or due today." />
      ) : (
        <div className="report-form">
          <div className="card card-sm current-task">
            <span className={`swatch swatch-${step.status === "blocked" ? "block" : "prog"}`} aria-hidden="true" />
            <div>
              <b>{place.name}</b>
              <span className="muted">
                Step {place.at} of {place.steps.length} · {step.name}
              </span>
            </div>
            <button type="button" className="link-button" onClick={() => setChanging(!changing)} aria-expanded={changing}>
              Change
            </button>
          </div>
          {changing && (
            <ul className="place-list" aria-label="Places to report today">
              {places.map((p) => (
                <li key={p.node_id}>
                  <button
                    type="button"
                    className="room-row"
                    aria-pressed={p.node_id === place.node_id}
                    onClick={() => {
                      setPick(p.node_id);
                      setChanging(false);
                    }}
                  >
                    <span className={`swatch swatch-${done.includes(p.node_id) ? "done" : "prog"}`} aria-hidden="true" />
                    <span className="room-name">
                      {p.name}
                      {p.floor ? <span className="muted small"> · {p.floor}</span> : null}
                    </span>
                    <span className="muted small">{done.includes(p.node_id) ? "sent" : `step ${p.at}`}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <p className="report-label">Work done today</p>
          <div className="choices" role="radiogroup" aria-label="Work done today">
            {(
              [
                ["done", `${step.name} done`],
                ["part", "Part done"],
                ["none", "No work today"],
              ] as [Choice, string][]
            ).map(([k, label]) => (
              <Button key={k} variant={choice === k ? "primary" : "secondary"} role="radio" aria-checked={choice === k} onClick={() => setChoice(k)}>
                {label}
              </Button>
            ))}
          </div>

          {choice !== "none" && (
            <>
              <FtInInput label="Length measured (ft + in)" ft={ft} inch={inch} onChange={(f, i) => (setFt(f), setInch(i))} />
              <p className="report-label">Photos (at least 1)</p>
              <div className="photos">
                {previews.map((u, i) => (
                  <img key={u} src={u} alt={`Photo ${i + 1}`} />
                ))}
                <label className="camera">
                  <Icon name="camera" size={22} />
                  Camera
                  <input
                    type="file"
                    accept="image/*"
                    capture="environment"
                    multiple
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? []);
                      setPhotos((p) => [...p, ...files].slice(0, 6));
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
            </>
          )}
          {error && <div className="alert alert-error">{error}</div>}
        </div>
      )}

      {place && step && (
        <footer className="report-send">
          <Button variant={send.ready ? "primary" : "secondary"} block disabled={!send.ready} loading={busy} onClick={() => void submit()}>
            {send.label}
          </Button>
          <p className="muted small">{kept ? "Saved on the phone; it sends when the signal is back" : "Saved on the phone if there is no signal; it sends when the signal is back"}</p>
        </footer>
      )}
    </div>
  );
}
