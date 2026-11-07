import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "ok" | "warn" | "danger" | "info" | "mock" | "ai";

export function Badge({
  children,
  tone = "neutral",
  dot = false,
  title,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  dot?: boolean;
  title?: string;
}) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function StatusPill({ status }: { status: string | null | undefined }) {
  const value = (status ?? "UNKNOWN").toUpperCase();
  const map: Record<string, BadgeTone> = {
    SUCCESS: "ok",
    APPROVE: "ok",
    COMPLETED: "ok",
    ACTIVE: "ok",
    PENDING: "info",
    CREATED: "info",
    RECEIVED: "info",
    PROCESSED: "ok",
    HELD: "warn",
    HOLD_FOR_REVIEW: "warn",
    FAILED: "danger",
    DENY: "neutral",
    BLOCKED: "danger",
    PAUSED: "warn",
  };
  return (
    <Badge tone={map[value] ?? "neutral"} dot>
      {value.replaceAll("_", " ")}
    </Badge>
  );
}

export function ProviderPill({ provider, mock }: { provider: string; mock: boolean }) {
  if (mock || provider === "mock") {
    return (
      <Badge tone="mock" title="Simulated transport. No real money moves.">
        MOCK
      </Badge>
    );
  }
  return (
    <Badge tone="info" title="PayPal sandbox: test money, real API calls.">
      PayPal sandbox
    </Badge>
  );
}
