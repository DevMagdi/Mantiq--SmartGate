import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Icon } from "@/components/Icon";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastContextValue {
  push: (tone: ToastTone, title: string, description?: string) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_STYLES: Record<ToastTone, string> = {
  success: "border-brand-200 bg-white text-ink-900 dark:border-brand-900/70 dark:bg-ink-900 dark:text-ink-100",
  error: "border-rose-200 bg-white text-ink-900 dark:border-rose-900/70 dark:bg-ink-900 dark:text-ink-100",
  info: "border-sky-200 bg-white text-ink-900 dark:border-sky-900/70 dark:bg-ink-900 dark:text-ink-100",
};

const TONE_ICONS: Record<ToastTone, { name: "check" | "alert" | "info"; className: string }> = {
  success: { name: "check", className: "bg-brand-100 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300" },
  error: { name: "alert", className: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300" },
  info: { name: "info", className: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
};

export function ToastProvider({ children }: { children: ReactNode }): JSX.Element {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (tone: ToastTone, title: string, description?: string) => {
      counter.current += 1;
      const id = counter.current;
      setToasts((current) => [...current.slice(-3), { id, tone, title, description }]);
      window.setTimeout(() => dismiss(id), 5_000);
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      success: (title, description) => push("success", title, description),
      error: (title, description) => push("error", title, description),
      info: (title, description) => push("info", title, description),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[80] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((toast) => {
          const tone = TONE_ICONS[toast.tone];
          return (
            <div
              key={toast.id}
              role="status"
              className={`pointer-events-auto animate-fade-in rounded-xl border p-3.5 shadow-card ${TONE_STYLES[toast.tone]}`}
            >
              <div className="flex items-start gap-3">
                <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${tone.className}`}>
                  <Icon name={tone.name} className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{toast.title}</p>
                  {toast.description ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-500 dark:text-ink-400">
                      {toast.description}
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  className="rounded-md p-1 text-ink-400 transition hover:bg-ink-100 hover:text-ink-600 dark:hover:bg-ink-800"
                  aria-label="Dismiss notification"
                >
                  <Icon name="close" className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
