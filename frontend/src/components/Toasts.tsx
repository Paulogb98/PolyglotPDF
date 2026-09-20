import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { t } from "../i18n";

export type ToastKind = "info" | "success" | "error";

export interface ToastInput {
  kind?: ToastKind;
  title: string;
  body?: string;
  action?: { label: string; run: () => void };
}

interface ToastItem extends ToastInput {
  id: number;
}

const ToastContext = createContext<(toast: ToastInput) => void>(() => undefined);
const ICONS = { info: Info, success: CircleCheck, error: CircleAlert };

/** Notices in ink, bottom right — the same card the translation progress uses. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: ToastInput) => {
      counter.current += 1;
      const id = counter.current;
      setToasts((list) => [...list.slice(-2), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), toast.kind === "error" ? 9000 : 4500);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => {
          const Icon = ICONS[toast.kind ?? "info"];
          return (
            <div key={toast.id} className="toast">
              <div className="toast-head">
                <Icon size={15} />
                <span className="spacer">{toast.title}</span>
                <button type="button" aria-label={t("common.closeNotice")} onClick={() => dismiss(toast.id)}>
                  <X size={14} />
                </button>
              </div>
              {toast.body ? <div className="toast-body">{toast.body}</div> : null}
              {toast.action ? (
                <div className="toast-actions">
                  <button
                    type="button"
                    className="btn btn-xs btn-on-night solid"
                    onClick={() => {
                      toast.action?.run();
                      dismiss(toast.id);
                    }}
                  >
                    {toast.action.label}
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (toast: ToastInput) => void {
  return useContext(ToastContext);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
