// The helper card: when something goes wrong, it says so in plain words. A wrong entry: each field's
// problem and its fix, from the field's rule (no AI), the field itself marked. Anything else:
// "Something went wrong", recorded in the issue log book with its request id, and "Report this" for
// the user's words. "Ask the helper" (when the company has switched the AI on) explains it; it only
// answers, it never changes anything.
import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api, ApiError, onApiFailure, type FieldProblem } from "../api";
import { crashReport, currentAction, formValues, pagePath, reportForFailure, send, trackActions } from "./report";

type Problem =
  | { kind: "mistake"; message: string; fields: FieldProblem[]; unmarked: FieldProblem[]; requestId: string | null }
  | { kind: "error"; message: string; requestId: string | null; issueId: number | null };

// --- the wrong fields, marked beside themselves ------------------------------------------------------

const norm = (s: string) =>
  s
    .toLowerCase()
    .replace(/\*|\(.*?\)/g, "")
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/** The form's field for a problem: by name, else by its label's words ("Line 2: Quantity" finds the
 * field labelled "Quantity *"). An open dialog's fields first. */
export function findField(p: FieldProblem, root: ParentNode = document): HTMLElement | null {
  const scope = root.querySelector(".modal") ?? root;
  if (p.field) {
    const named = scope.querySelector<HTMLElement>(`[name="${p.field.replace(/["\\]/g, "")}"]`);
    if (named) return named.closest("label") ?? named;
  }
  const labels = Array.from(scope.querySelectorAll<HTMLLabelElement>("label.field"));
  const i = pickLabel(
    labels.map((l) => l.querySelector("span")?.textContent ?? ""),
    p,
  );
  return i >= 0 ? labels[i] : null;
}

/** Which of the form's field labels a problem is about (-1: none): the same words first ("Contact
 * name" is "Contact name *"), then the field's own name, then a label that starts with them. */
export function pickLabel(texts: string[], p: FieldProblem): number {
  const want = norm(p.label.split(":").pop() ?? "");
  const words = p.field ? norm(p.field.replace(/_/g, " ")) : "";
  if (!want && !words) return -1;
  const t = texts.map(norm);
  let i = t.findIndex((x) => x === want);
  if (i < 0 && words) i = t.findIndex((x) => x === words);
  if (i < 0 && want.length > 2) i = t.findIndex((x) => x.length > 2 && (x.startsWith(want) || want.startsWith(x)));
  return i;
}

export function clearMarks(root: ParentNode = document) {
  root.querySelectorAll(".field-msg[data-helper]").forEach((n) => n.remove());
  root.querySelectorAll(".field-wrong").forEach((n) => {
    n.classList.remove("field-wrong");
    n.querySelector("[aria-invalid]")?.removeAttribute("aria-invalid");
  });
}

/** Marks each wrong field and writes its problem and fix beside it; returns the problems whose
 * field is not on the page (the card says those; the marked ones are said beside their field). */
export function markFields(fields: FieldProblem[], root: ParentNode = document): FieldProblem[] {
  clearMarks(root);
  let found = 0;
  const unmarked: FieldProblem[] = [];
  for (const p of fields) {
    const el = findField(p, root);
    if (!el) {
      unmarked.push(p);
      continue;
    }
    found += 1;
    el.classList.add("field-wrong");
    const input = el.querySelector("input, select, textarea") ?? el;
    input.setAttribute("aria-invalid", "true");
    const msg = document.createElement("small");
    msg.className = "field-msg";
    msg.dataset.helper = "1";
    msg.setAttribute("role", "alert");
    msg.textContent = `${p.plain} ${p.fix}`;
    el.appendChild(msg);
    // typing in the field takes its mark away
    input.addEventListener(
      "input",
      () => {
        el.classList.remove("field-wrong");
        input.removeAttribute("aria-invalid");
        msg.remove();
      },
      { once: true },
    );
    if (found === 1 && input instanceof HTMLElement && typeof input.focus === "function") input.focus({ preventScroll: false });
  }
  return unmarked;
}

// --- the card ----------------------------------------------------------------------------------------

let aiOn: Promise<boolean> | null = null;
function helperAi(): Promise<boolean> {
  aiOn ??= api<{ ai: boolean }>("/api/me/helper").then(
    (r) => r.ai,
    () => {
      aiOn = null;
      return false;
    },
  );
  return aiOn;
}

// a crash outside React (an event handler, a promise nobody waited for) reaches the card here
const crashListeners = new Set<(p: Problem) => void>();
export function showCrash(err: unknown) {
  const page = pagePath(window.location.href);
  const r = crashReport(err, page, currentAction());
  void send(r).then((rec) => {
    for (const fn of crashListeners) fn({ kind: "error", message: "Something went wrong on this page.", requestId: rec?.request_id ?? null, issueId: rec?.issue_id ?? null });
  });
}

/** Mounted once for the whole app (App.tsx): staff pages, the portal and the sign-in page. */
export function HelperCard() {
  const location = useLocation();
  const portal = location.pathname.startsWith("/portal");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [ai, setAi] = useState(false);
  const [mode, setMode] = useState<"" | "report" | "ask">("");
  const [words, setWords] = useState("");
  const [withValues, setWithValues] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const stopActions = trackActions();
    const onError = (ev: ErrorEvent) => {
      // a script from another site, or the browser's own resize-observer note: not ours
      if (!ev.error && /ResizeObserver|Script error/.test(ev.message)) return;
      showCrash(ev.error ?? ev.message);
    };
    const onRejection = (ev: PromiseRejectionEvent) => {
      if (ev.reason instanceof ApiError) return; // a failed request: the api already told the card
      showCrash(ev.reason);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    const onCrash = (p: Problem) => open(p);
    crashListeners.add(onCrash);
    const stopApi = onApiFailure((e) => {
      const r = reportForFailure(e, pagePath(window.location.href));
      if (!r) return;
      r.action = [currentAction(), r.action].filter(Boolean).join(" · ") || null;
      if (r.kind === "mistake") {
        const unmarked = markFields(e.fields);
        void send(r); // "user mistake, guided" in the log book
        open({ kind: "mistake", message: e.message, fields: e.fields, unmarked, requestId: e.requestId });
      } else {
        void send(r).then((rec) => open({ kind: "error", message: e.message, requestId: e.requestId, issueId: rec?.issue_id ?? null }));
      }
    });
    return () => {
      stopActions();
      stopApi();
      crashListeners.delete(onCrash);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  function open(p: Problem) {
    setProblem(p);
    setMode("");
    setAnswer(null);
    setNote(null);
    setWords("");
    setQuestion("");
    setWithValues(false);
    void helperAi().then(setAi);
  }
  function close() {
    setProblem(null);
    clearMarks();
  }
  // another page: the card and the marks go
  useEffect(() => {
    setProblem(null);
    clearMarks();
  }, [location.pathname]);

  if (!problem) return null;

  async function report() {
    if (!problem || !words.trim()) return;
    setBusy(true);
    const values = withValues ? formValues() : undefined;
    try {
      let issueId = problem.kind === "error" ? problem.issueId : null;
      if (issueId === null) {
        // not recorded yet (a wrong entry the user thinks is right): the report carries the words
        const rec = await send(
          { kind: "report", page: pagePath(window.location.href), action: currentAction(), error: problem.message, words: words.trim(), include_values: withValues, values },
          true,
        );
        issueId = rec?.issue_id ?? null;
        if (issueId === null) throw new Error("not recorded");
      } else {
        await api(`/api/me/issues/${issueId}/words`, { method: "POST", json: { words: words.trim(), include_values: withValues, values } });
      }
      setNote(`Thank you: it is in the issue log as #${issueId}. You can follow it under ${portal ? "My reports" : "My work > My reports"}.`);
      setMode("");
    } catch {
      setNote("It could not be sent just now. Try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  async function ask() {
    if (!problem) return;
    setBusy(true);
    setAnswer(null);
    try {
      const r = await api<{ answer: string }>("/api/me/helper/ask", {
        method: "POST",
        json: {
          issue_id: problem.kind === "error" ? problem.issueId : null,
          page: pagePath(window.location.href),
          error: problem.message,
          field_rules: problem.kind === "mistake" ? problem.fields.map((f) => `${f.label}: ${f.plain} ${f.fix}`) : [],
          question: question.trim() || null,
        },
      });
      setAnswer(r.answer);
    } catch (e) {
      setAnswer(e instanceof Error ? e.message : "The helper could not answer just now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className={`helper-card helper-${problem.kind}`} role="alertdialog" aria-labelledby="helper-title">
      <div className="helper-head">
        <b id="helper-title">{problem.kind === "mistake" ? "Please check this" : "Something went wrong"}</b>
        <button className="btn btn-ghost btn-small" onClick={close} aria-label="Close the helper">
          ×
        </button>
      </div>
      {problem.kind === "mistake" ? (
        <>
          {problem.unmarked.length < problem.fields.length && (
            <p className="helper-text">
              {problem.fields.length - problem.unmarked.length === 1 ? "The marked field needs a change" : `The ${problem.fields.length - problem.unmarked.length} marked fields need a change`}: what is wrong is written beside it.
            </p>
          )}
          {problem.unmarked.length > 0 && (
            <ul className="helper-fields">
              {problem.unmarked.map((f, i) => (
                <li key={i}>
                  <b>{f.plain}</b> {f.fix}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="helper-text">
          {problem.message}
          {problem.requestId && <span className="muted helper-rid"> Reference: {problem.requestId}</span>}
        </p>
      )}
      {note && <p className="helper-note">{note}</p>}
      {mode === "report" && (
        <div className="helper-form">
          <label className="field">
            <span>What were you doing?</span>
            <textarea rows={3} value={words} onChange={(e) => setWords(e.target.value)} maxLength={2000} autoFocus placeholder="I was saving the bill after adding a line…" />
          </label>
          <label className="check">
            <input type="checkbox" checked={withValues} onChange={(e) => setWithValues(e.target.checked)} /> Also send what I typed on this form (never passwords)
          </label>
          <div className="row">
            <button className="btn btn-primary btn-small" disabled={busy || !words.trim()} onClick={() => void report()}>
              Send
            </button>
            <button className="btn btn-ghost btn-small" onClick={() => setMode("")}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {mode === "ask" && (
        <div className="helper-form">
          <label className="field">
            <span>Your question (optional)</span>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={1000} placeholder="What do I do now?" />
          </label>
          <button className="btn btn-primary btn-small" disabled={busy} onClick={() => void ask()}>
            {busy ? "Asking…" : "Ask"}
          </button>
          {answer && (
            <div className="helper-answer">
              <p>{answer}</p>
              <p className="muted">The helper only explains; it never changes anything.</p>
            </div>
          )}
        </div>
      )}
      {mode === "" && (
        <div className="row helper-actions">
          {problem.kind === "error" && !note && (
            <button className="btn btn-small" onClick={() => setMode("report")}>
              Report this
            </button>
          )}
          {ai && (
            <button className="btn btn-small" onClick={() => setMode("ask")}>
              Ask the helper
            </button>
          )}
          {problem.kind === "mistake" && !note && (
            <button className="btn btn-ghost btn-small" onClick={() => setMode("report")}>
              This looks wrong? Report it
            </button>
          )}
        </div>
      )}
    </aside>
  );
}

/** A page that crashes while drawing shows this instead of a blank screen; the crash is recorded. */
export class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    const e = new Error(error.message);
    e.name = error.name;
    e.stack = `${error.stack ?? ""}\n${info.componentStack ?? ""}`;
    showCrash(e);
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="alert alert-error page-crash">
        <b>This page hit a problem.</b> It is recorded in the issue log. Go back, or reload the page; if it happens again use <i>Report this</i> on the card below.
        <div className="row">
          <button className="btn btn-small" onClick={() => window.location.reload()}>
            Reload the page
          </button>
          <button className="btn btn-ghost btn-small" onClick={() => window.history.back()}>
            Go back
          </button>
        </div>
      </div>
    );
  }
}
