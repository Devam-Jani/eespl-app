// Modal, side drawer and the toast with Undo. Escape closes, focus goes into the dialog and back.
// A modal or drawer renders on <body> (a portal), not where the page puts it: a page part that makes
// its own stacking (a card, a modal opening another) can then never hold it under the top bar.
import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "./components";

function useDialog(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not([aria-label='Close']), [href]");
    (first ?? ref.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, [onClose]);
  return ref;
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useDialog(onClose);
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <Button variant="ghost" icon onClick={onClose} aria-label="Close">
            ×
          </Button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useDialog(onClose);
  return createPortal(
    <>
      <div className="modal-backdrop" style={{ background: "transparent" }} onMouseDown={onClose} />
      <aside ref={ref} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <Button variant="ghost" icon onClick={onClose} aria-label="Close">
            ×
          </Button>
        </div>
        {children}
      </aside>
    </>,
    document.body,
  );
}

// --- toasts -------------------------------------------------------------------------------------

export type Toast = { id: number; text: string; kind?: "info" | "error"; undo?: () => void; ms?: number };
type ToastApi = {
  show: (t: Omit<Toast, "id">) => number;
  dismiss: (id: number) => void;
  /** Runs `action` after a few seconds unless Undo is pressed first (nothing is sent until then). */
  later: (text: string, action: () => void | Promise<void>, ms?: number, onUndo?: () => void) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast needs <ToastProvider>");
  return api;
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<number, number>());
  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.filter((t) => t.id !== id));
    const h = timers.current.get(id);
    if (h) window.clearTimeout(h);
    timers.current.delete(id);
  }, []);
  const show = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = nextId++;
      setToasts((ts) => [...ts.slice(-2), { ...t, id }]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), t.ms ?? 5000));
      return id;
    },
    [dismiss],
  );
  const later = useCallback(
    (text: string, action: () => void | Promise<void>, ms = 6000, onUndo?: () => void) => {
      let undone = false;
      const id = show({
        text,
        ms,
        undo: () => {
          undone = true;
          onUndo?.();
        },
      });
      window.setTimeout(() => {
        if (!undone) void action();
      }, ms);
      return id;
    },
    [show],
  );
  return (
    <ToastContext.Provider value={{ show, dismiss, later }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind === "error" ? "toast-error" : ""}`}>
            <span className="toast-text">{t.text}</span>
            {t.undo && (
              <Button
                size="small"
                onClick={() => {
                  t.undo!();
                  dismiss(t.id);
                }}
              >
                Undo
              </Button>
            )}
            <Button variant="ghost" size="small" onClick={() => dismiss(t.id)} aria-label="Dismiss">
              ×
            </Button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
