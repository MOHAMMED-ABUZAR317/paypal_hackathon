import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Tone = "ok" | "error" | "info";

type ToastItem = { id: number; message: string; tone: Tone };

type ToastApi = { push: (message: string, tone?: Tone) => void };

const ToastContext = createContext<ToastApi>({ push: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((message: string, tone: Tone = "info") => {
    const id = nextId.current++;
    setItems((previous) => [...previous.slice(-3), { id, message, tone }]);
    window.setTimeout(() => {
      setItems((previous) => previous.filter((item) => item.id !== id));
    }, 6000);
  }, []);

  const api = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast toast--${item.tone}`}>
            <span className="toast__mark" aria-hidden="true">
              {item.tone === "ok" ? "✓" : item.tone === "error" ? "!" : "i"}
            </span>
            <span>{item.message}</span>
            <button
              type="button"
              className="toast__close"
              aria-label="Dismiss notification"
              onClick={() =>
                setItems((previous) => previous.filter((entry) => entry.id !== item.id))
              }
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
