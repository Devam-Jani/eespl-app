// Where the worker's read of a drawing is: queued, converting (DWG to DXF), reading (lines and
// texts), finding areas, done; the page polls the file and shows this instead of a loader.
const STEPS = [
  ["queued", "Waiting for the reader"],
  ["converting", "Converting the DWG"],
  ["reading", "Reading the lines and texts"],
  ["finding areas", "Finding the rooms and notes"],
] as const;

export function ReadProgress({ filename, progress, since }: { filename: string | null; progress: string | null; since?: string | null }) {
  const at = Math.max(0, STEPS.findIndex(([k]) => k === (progress ?? "queued")));
  const secs = since ? Math.max(0, Math.round((Date.now() - Date.parse(since)) / 1000)) : null;
  return (
    <div className="alert alert-warn read-progress" role="status" aria-live="polite">
      <b>Reading {filename ?? "the drawing"}</b> — a large drawing takes a minute or two; you can leave this page, it carries on.
      <ol>
        {STEPS.map(([k, label], i) => (
          <li key={k} className={i < at ? "done" : i === at ? "now" : ""}>
            {label}
            {i === at && secs != null && <span className="muted"> ({secs} s)</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
