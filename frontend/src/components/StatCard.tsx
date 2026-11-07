import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  hint,
  tone = "plain",
  aside,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "plain" | "rain" | "warn" | "ok";
  aside?: ReactNode;
}) {
  return (
    <article className={`stat stat--${tone}`}>
      <div className="stat__top">
        <p className="stat__label">{label}</p>
        {aside}
      </div>
      <p className="stat__value">{value}</p>
      {hint ? <p className="stat__hint">{hint}</p> : null}
    </article>
  );
}
