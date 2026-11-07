import { useEffect, useState } from "react";

/**
 * Two-step confirmation without a modal: the first click arms the action, the
 * second performs it. Safer than a single click for destructive demo tools and
 * fully keyboard accessible.
 */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  busy = false,
  tone = "danger",
  hint,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  busy?: boolean;
  tone?: "danger" | "warn";
  hint?: string;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 5000);
    return () => window.clearTimeout(timer);
  }, [armed]);

  return (
    <div className="confirm">
      <button
        type="button"
        className={`btn btn--${armed ? tone : "secondary"} btn--sm`}
        onClick={() => {
          if (armed) {
            setArmed(false);
            onConfirm();
          } else {
            setArmed(true);
          }
        }}
        disabled={busy}
        aria-busy={busy}
      >
        {busy ? "Working…" : armed ? confirmLabel : label}
      </button>
      {armed ? (
        <span className="confirm__hint" role="status">
          {hint ?? "Click again to confirm."}
        </span>
      ) : null}
    </div>
  );
}
