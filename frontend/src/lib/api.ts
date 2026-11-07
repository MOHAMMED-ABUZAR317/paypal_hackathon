import type {
  AiReview,
  AiStatus,
  AuditEntry,
  ContributionResponse,
  EnrollResponse,
  ExplainResponse,
  FraudAttemptResponse,
  FundResponse,
  LedgerResponse,
  Member,
  Overview,
  ParseResponse,
  PolicyPreview,
  PollResult,
  Pool,
  PoolStats,
  PublicConfig,
  Receipt,
  SimulateResponse,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const OPERATOR_KEY_STORAGE = "raincheck.operatorKey";
const DEFAULT_OPERATOR_KEY = "dev-operator-key";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getOperatorKey(): string {
  try {
    return sessionStorage.getItem(OPERATOR_KEY_STORAGE) || DEFAULT_OPERATOR_KEY;
  } catch {
    return DEFAULT_OPERATOR_KEY;
  }
}

export function setOperatorKey(value: string): void {
  try {
    sessionStorage.setItem(OPERATOR_KEY_STORAGE, value.trim() || DEFAULT_OPERATOR_KEY);
  } catch {
    /* private mode: keep the in-memory default */
  }
}

export function defaultOperatorKey(): string {
  return DEFAULT_OPERATOR_KEY;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  operator?: boolean;
  signal?: AbortSignal;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.operator) {
    headers["X-Operator-Key"] = getOperatorKey();
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      "Cannot reach the RainCheck API. Is the backend running on port 8000?",
      0,
      error,
    );
  }

  if (!response.ok) {
    let detail: unknown = null;
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload;
      if (typeof payload?.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload?.detail) && payload.detail[0]?.msg) {
        message = payload.detail[0].msg as string;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () =>
    request<{ status: string; seeded: boolean; members: number; paypal_mode: string }>(
      "/api/health",
    ),

  config: () => request<PublicConfig>("/api/config"),

  overview: () => request<Overview>("/api/overview"),

  pool: () => request<{ pool: Pool }>("/api/pool"),

  poolStats: () => request<PoolStats>("/api/pool/stats"),

  ledger: (params: {
    status?: string;
    zone?: string;
    event_id?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }) => request<LedgerResponse>(`/api/ledger${query(params)}`),

  members: (q?: string, limit = 25) =>
    request<{ members: Member[] }>(`/api/members${query({ q, limit })}`),

  member: (memberId: string) =>
    request<{
      member: Member;
      policies: (PolicyPreview & { id: string; payout_display: string; active: boolean })[];
      receipts: Receipt[];
      pledge_display: string | null;
      hold_note: string | null;
    }>(`/api/members/${encodeURIComponent(memberId)}`),

  parsePolicy: (text: string, zone: string) =>
    request<ParseResponse>("/api/policies/parse", {
      method: "POST",
      body: { text, zone },
    }),

  enroll: (body: {
    member: {
      name: string;
      email: string;
      paypal_email: string;
      zone: string;
      device_id?: string;
      signup_ip?: string;
      verified: boolean;
    };
    policy: PolicyPreview;
    source_text?: string;
  }) =>
    request<EnrollResponse>("/api/policies", {
      method: "POST",
      body,
    }),

  fund: (memberId: string, amountMinor?: number) =>
    request<FundResponse>("/api/pool/fund", {
      method: "POST",
      body: { member_id: memberId, amount_minor: amountMinor ?? null },
    }),

  captureFunding: (orderId: string) =>
    request<FundResponse>(`/api/pool/fund/${encodeURIComponent(orderId)}/capture`, {
      method: "POST",
    }),

  contributions: (memberId?: string, limit = 20) =>
    request<ContributionResponse>(
      `/api/contributions${query({ member_id: memberId, limit })}`,
    ),

  events: (limit = 20) =>
    request<{ events: import("./types").EventRow[] }>(`/api/events${query({ limit })}`),

  eventSummary: (eventId: string) =>
    request<SimulateResponse>(`/api/events/${encodeURIComponent(eventId)}`),

  eventKey: (eventId: string) =>
    request<{ event_id: string; event_key: string }>(
      `/api/events/${encodeURIComponent(eventId)}/last-key`,
    ),

  simulate: (body: {
    zone: string;
    rainfall_mm: number;
    days: number;
    event_key?: string;
  }) =>
    request<SimulateResponse>("/api/events/simulate", {
      method: "POST",
      body,
      operator: true,
    }),

  pollLive: () =>
    request<PollResult>("/api/events/poll", { method: "POST", operator: true }),

  pause: (paused: boolean, reason?: string) =>
    request<{ pool: Pool; message: string }>("/api/operator/pause", {
      method: "POST",
      body: { paused, reason: reason ?? null },
      operator: true,
    }),

  retryPayouts: (eventId?: string) =>
    request<{ retried: number; message?: string }>("/api/operator/payouts/retry", {
      method: "POST",
      body: eventId ? { event_id: eventId } : {},
      operator: true,
    }),

  reconcile: () =>
    request<{ batches_checked: number }>("/api/operator/payouts/reconcile", {
      method: "POST",
      operator: true,
    }),

  resetDemo: () =>
    request<{ pool_id: string; reset: boolean; members_kept: boolean; history: unknown }>(
      "/api/operator/demo/reset",
      { method: "POST", operator: true },
    ),

  fraudAttempt: () =>
    request<FraudAttemptResponse>("/api/operator/demo/fraud-attempt", {
      method: "POST",
      operator: true,
    }),

  receipts: (memberId?: string, limit = 25) =>
    request<{ receipts: Receipt[] }>(
      `/api/receipts${query({ member_id: memberId, limit })}`,
    ),

  receipt: (payoutId: string) =>
    request<{ receipt: Receipt }>(`/api/receipts/${encodeURIComponent(payoutId)}`),

  explainReceipt: (payoutId: string, language: "en" | "hi" | "te") =>
    request<ExplainResponse>(
      `/api/ai/receipts/${encodeURIComponent(payoutId)}/explain${query({ language })}`,
      { method: "POST" },
    ),

  aiStatus: () => request<AiStatus>("/api/ai/status"),

  aiPoolInsight: () => request<AiReview>("/api/ai/pool-insight"),

  aiEventReview: (eventId: string) =>
    request<AiReview>(`/api/ai/event/${encodeURIComponent(eventId)}/review`, {
      method: "POST",
      operator: true,
    }),

  aiMemberReview: (memberId: string) =>
    request<AiReview>(`/api/ai/member/${encodeURIComponent(memberId)}/review`, {
      method: "POST",
      operator: true,
    }),

  audit: (limit = 30) => request<{ entries: AuditEntry[] }>(`/api/audit${query({ limit })}`),
};
