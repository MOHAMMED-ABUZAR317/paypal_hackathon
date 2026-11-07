export type PayoutStatus = "CREATED" | "PENDING" | "SUCCESS" | "FAILED" | "HELD";
export type Outcome = "APPROVE" | "DENY" | "HOLD_FOR_REVIEW";

export interface Zone {
  id: string;
  name: string;
  city: string;
  latitude: number;
  longitude: number;
}

export interface Limits {
  max_payouts_per_day: number;
  max_payouts_per_month: number;
  min_threshold_mm: number;
  max_threshold_mm: number;
  min_payout_minor: number;
  max_payout_minor: number;
}

export interface PublicConfig {
  app: {
    app_name: string;
    env: string;
    paypal: {
      mode: "mock" | "sandbox";
      configured: boolean;
      webhook_configured: boolean;
      payout_currency: string;
      inr_per_usd: number;
    };
    ai: { enabled: boolean; model: string; provider: string };
    poll_interval_minutes: number;
  };
  zones: Zone[];
  limits: Limits;
}

export interface Pool {
  id: string;
  name: string;
  currency: string;
  payout_balance_minor: number;
  reserve_balance_minor: number;
  total_balance_minor: number;
  running_costs_minor: number;
  contribution_amount_minor: number;
  paused: boolean;
  pause_reason: string | null;
  display: {
    payout_box: string;
    reserve_box: string;
    total: string;
    contribution: string;
  };
  updated_at: string | null;
}

export interface Forecast {
  active_policies: number;
  verified_members: number;
  zone_counts: Record<string, number>;
  biggest_zone: number;
  stress_fraction: number;
  assumed_affected_members: number;
  expected_payout_per_member_minor: number;
  expected_event_cost_minor: number;
  events_covered: number;
  monthly_inflow_minor: number;
  narrative: string;
  source: string;
}

export interface PoolStats {
  pool: Pool;
  members: {
    total: number;
    active: number;
    verified: number;
    blocked: number;
    policies_active: number;
    zones: { zone: string; members: number }[];
  };
  coverage: {
    total_balance_minor: number;
    payout_box_minor: number;
    reserve_box_minor: number;
    expected_event_cost_minor: number;
    assumed_affected_members: number;
    stress_fraction: number;
    events_covered: number;
    storm_days_covered: number;
    member_payouts_covered: number;
    display: { total: string; expected_event_cost: string };
  };
  performance: {
    payouts_success: number;
    total_paid_minor: number;
    total_paid_display: string;
    payouts_failed: number;
    decisions_held: number;
    events_processed: number;
    avg_seconds_trigger_to_payout: number | null;
    p95_seconds_trigger_to_payout: number | null;
    last_event_at: string | null;
    contributions_count: number;
    contributions_minor: number;
  };
  forecast: Forecast;
  guards: {
    paused: boolean;
    pause_reason: string | null;
    max_payouts_per_day: number;
    max_payouts_per_month: number;
    idempotency: string;
    webhook_signature: string;
    ai_moves_money: boolean;
    provider: "paypal" | "mock";
    provider_label: string;
    mock: boolean;
  };
}

export interface EventRow {
  id: string;
  zone: string;
  metric: string;
  value: number;
  threshold: number;
  days: number;
  mode: string;
  status: string;
  created_at: string;
  processed_at: string | null;
}

export interface Overview {
  seeded: boolean;
  stats: PoolStats | null;
  recent_events: EventRow[];
}

export interface LedgerRow {
  id: string;
  created_at: string;
  updated_at: string | null;
  event_id: string;
  zone: string;
  rainfall_mm: number | null;
  member_id: string;
  member_name: string;
  amount_minor: number;
  amount_display: string;
  send_amount: string;
  send_currency: string;
  status: PayoutStatus;
  reason_code: string | null;
  provider: string;
  batch_id: string | null;
  item_id: string | null;
  receiver: string | null;
  failure_reason: string | null;
  mock: boolean;
}

export interface LedgerResponse {
  rows: LedgerRow[];
  total: number;
  counts: Record<string, number>;
  limit: number;
  offset: number;
  mock: boolean;
}

export interface PolicyPreview {
  schema_version: string;
  trigger_type: string;
  data_source: string;
  zone: string;
  metric: string;
  operator: string;
  threshold: number;
  payout_amount_minor: number;
  currency: string;
  max_payouts_per_day: number;
  max_payouts_per_month: number;
  waiting_period_hours: number;
  plain_language: string;
  source: "llm" | "rules" | "edited";
  warnings: string[];
  confidence: number;
}

export interface ParseResponse {
  ok: boolean;
  policy: PolicyPreview | null;
  error: string | null;
  attempts: number;
}

export interface Member {
  id: string;
  name: string;
  email: string;
  paypal_email: string;
  zone: string;
  verified: boolean;
  status: string;
  created_at: string;
}

export interface Screening {
  score: number;
  recommendation: "allow" | "review" | "block";
  flags: { code: string; detail: string; weight: number }[];
  explanation: string;
}

export interface EnrollResponse {
  member: Member;
  policy: PolicyPreview & { id: string; payout_display: string; risk_score: number; risk_flags: string[] };
  screening: Screening;
  receipt: string;
  blocked: boolean;
}

export interface FundResponse {
  contribution_id: string;
  order_id: string;
  provider: string;
  mock: boolean;
  approve_url: string | null;
  amount_minor: number;
  currency: string;
  status: string;
}

export interface Contribution {
  id: string;
  member_id: string;
  amount_minor: number;
  amount_display: string;
  currency: string;
  status: string;
  provider: string;
  order_id: string | null;
  capture_id: string | null;
  mock: boolean;
  created_at: string;
}

export interface ContributionResponse {
  contributions: Contribution[];
  completed_total_minor: number;
  completed_total_display: string;
}

export interface DecisionRow {
  decision_id: string;
  member_id: string;
  member_name: string;
  zone: string;
  outcome: Outcome;
  reason_code: string;
  reason_detail: string;
  risk_score: number;
  payable_days: number;
  amount_minor: number;
  payout_status: PayoutStatus | null;
  mock: boolean | null;
}

export interface SimulateResponse {
  event: EventRow;
  duplicate: boolean;
  counts: Record<Outcome, number>;
  reasons: { code: string; count: number }[];
  total_paid_minor: number;
  payout_rows: number;
  batches: { batch_id: string; provider: string; items: number }[];
  decisions_sample: DecisionRow[];
}

export interface Receipt {
  id: string;
  payout_id: string;
  created_at: string;
  member_id: string;
  member_name: string;
  amount_minor: number;
  amount_display: string;
  status: string;
  provider: string;
  zone: string;
  rainfall_mm: number | null;
  text: string;
}

export interface ExplainResponse {
  payout_id: string;
  language: "en" | "hi" | "te";
  text: string;
  source: "llm" | "rules";
  guard: string;
  note?: string;
  ai_error?: string;
}

export interface AiStatus {
  enabled: boolean;
  mode: "llm" | "rules";
  provider: string;
  model: string;
  jobs: string[];
  can_move_money: boolean;
  note: string;
}

export interface AiReview {
  source: "llm" | "rules";
  ai: { risk_level?: string; summary: string; recommendation?: string; action?: string };
  ai_error: string | null;
  facts?: Record<string, unknown>;
  decision_authority?: string;
  note?: string;
}

export interface AuditEntry {
  id: string;
  ts: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  detail: Record<string, unknown>;
}

export interface PollResult {
  results: {
    zone: string;
    status: string;
    value?: number;
    event_id?: string;
    error?: string;
  }[];
  zones_checked: number;
  events_fired: number;
  note: string;
}

export interface FraudAttemptResponse {
  blocked: boolean;
  member: Member;
  screening: Screening;
  receipt: string;
  note: string;
  pledge_display: string;
}
