import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { Badge, ProviderPill, StatusPill } from "../components/Badge";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { PoolSplit } from "../components/PoolSplit";
import { StatCard } from "../components/StatCard";
import { ErrorState, Loading } from "../components/StateBlocks";
import { api } from "../lib/api";
import {
  formatDate,
  formatMoney,
  formatNumber,
  formatSeconds,
  percent,
  timeAgo,
  zoneLabel,
} from "../lib/format";
import { useApi } from "../lib/hooks";
import type { EventRow, LedgerRow, PoolStats } from "../lib/types";

type DashboardData = {
  stats: PoolStats;
  ledger: Awaited<ReturnType<typeof api.ledger>>;
  events: { events: EventRow[] };
  config: Awaited<ReturnType<typeof api.config>>;
};

export function DashboardPage() {
  const [status, setStatus] = useState("");
  const [zone, setZone] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [query]);

  const { data, loading, error, reload } = useApi<DashboardData>(async () => {
    const [stats, ledger, events, config] = await Promise.all([
      api.poolStats(),
      api.ledger({ status: status || undefined, zone: zone || undefined, q: search || undefined, limit: 300 }),
      api.events(5),
      api.config(),
    ]);
    return { stats, ledger, events, config };
  }, [status, zone, search]);

  const columnDefs = useMemo<ColDef<LedgerRow>[]>(
    () => [
      {
        headerName: "Time",
        field: "created_at",
        width: 145,
        valueFormatter: (params) => formatDate(params.value),
      },
      {
        headerName: "Member",
        field: "member_name",
        minWidth: 160,
        flex: 1.2,
      },
      {
        headerName: "Zone",
        field: "zone",
        width: 160,
        valueFormatter: (params) => zoneLabel(params.value, data?.config.zones),
      },
      {
        headerName: "Rain",
        field: "rainfall_mm",
        width: 90,
        valueFormatter: (params) => (params.value == null ? "—" : `${params.value} mm`),
      },
      {
        headerName: "Payout",
        field: "amount_display",
        width: 120,
        cellStyle: { fontWeight: "650" },
      },
      {
        headerName: "Sent",
        field: "send_amount",
        width: 130,
        valueFormatter: (params) =>
          `${params.data?.send_currency ?? "USD"} ${params.data?.send_amount ?? "—"}`,
      },
      {
        headerName: "Status",
        field: "status",
        width: 122,
        cellRenderer: (params: { value: string }) => <StatusPill status={params.value} />,
      },
      {
        headerName: "Reason",
        field: "reason_code",
        width: 165,
        cellRenderer: (params: { value: string | null }) => (
          <span className="mono small">{params.value ?? "—"}</span>
        ),
      },
      {
        headerName: "Provider",
        field: "provider",
        width: 105,
        cellRenderer: (params: { data?: LedgerRow }) => (
          <ProviderPill provider={params.data?.provider ?? "mock"} mock={params.data?.mock ?? true} />
        ),
      },
      {
        headerName: "Batch",
        field: "batch_id",
        width: 150,
        cellRenderer: (params: { value: string | null }) => (
          <span className="mono small" title={params.value ?? ""}>
            {params.value ? `${params.value.slice(0, 14)}…` : "—"}
          </span>
        ),
      },
    ],
    [data?.config.zones],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      sortable: true,
      resizable: true,
      filter: true,
      suppressHeaderMenuButton: true,
    }),
    [],
  );

  if (loading && !data) {
    return (
      <>
        <PageHeader eyebrow="Live pool" title="Loading the pool…" />
        <Loading label="Reading balances, ledger and coverage" />
      </>
    );
  }

  if (error && !data) {
    return (
      <>
        <PageHeader eyebrow="Live pool" title="The pool is out of reach" />
        <ErrorState message={error} onRetry={() => void reload()} />
      </>
    );
  }

  if (!data) return null;

  const { stats, ledger, events, config } = data;
  const pool = stats.pool;
  const topZone = Math.max(1, ...stats.members.zones.map((row) => row.members));
  const coveragePct = Math.min(100, (stats.coverage.events_covered / 3) * 100);

  return (
    <>
      <PageHeader
        eyebrow="Live pool"
        title="Rain today. Paid in seconds."
        lead={
          <>
            A community pool for gig workers. The rule engine watches 24-hour rainfall, decides
            who is covered, and PayPal pays — no claim form.{" "}
            <strong>{stats.performance.events_processed}</strong> event(s) processed so far.
          </>
        }
        actions={
          <>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void reload()}
              aria-busy={loading}
            >
              <Icon name="refresh" size={16} /> Refresh
            </button>
            <Link className="btn btn--primary" to="/operator">
              Simulate a storm <Icon name="arrow" size={16} />
            </Link>
          </>
        }
      />

      <section className="grid grid--main">
        <article className="card card--dark hero__copy">
          <div className="row row--between">
            <Badge tone={stats.guards.paused ? "warn" : "ok"} dot>
              {stats.guards.paused ? "Payouts paused" : "Rules running"}
            </Badge>
            <ProviderPill
              provider={stats.guards.provider}
              mock={stats.guards.mock}
            />
          </div>
          <h2 className="hero__title">
            {stats.members.policies_active
              ? `${formatNumber(stats.members.policies_active)} workers are covered by one deterministic rule.`
              : "No active policies yet. Enroll the first worker."}
          </h2>
          <p className="hero__lead">
            AI can turn a sentence into a policy and explain a receipt. It cannot approve a
            payout. The rule engine is plain code with hard caps, and every decision leaves a
            reason code in the ledger.
          </p>
          <div className="hero__actions">
            <Link className="btn btn--primary" to="/enroll">
              Enroll a worker
            </Link>
            <Link className="btn btn--secondary" to="/receipts">
              Open receipts
            </Link>
          </div>
          <div className="hero__facts">
            <div className="hero__fact">
              <strong>{formatSeconds(stats.performance.avg_seconds_trigger_to_payout)}</strong>
              <span>average trigger → payout</span>
            </div>
            <div className="hero__fact">
              <strong>{stats.coverage.events_covered.toFixed(1)}</strong>
              <span>storm events covered</span>
            </div>
            <div className="hero__fact">
              <strong>{stats.performance.total_paid_display}</strong>
              <span>paid to workers</span>
            </div>
            <div className="hero__fact">
              <strong>{stats.performance.payouts_failed}</strong>
              <span>failed payouts</span>
            </div>
          </div>
        </article>

        <article className="card">
          <div className="card__head">
            <div>
              <h2>Pool money</h2>
              <p className="card__sub">Two boxes, never mixed.</p>
            </div>
            {pool.paused ? (
              <Badge tone="warn" dot>
                Paused
              </Badge>
            ) : (
              <Badge tone="ok" dot>
                Active
              </Badge>
            )}
          </div>
          <PoolSplit
            payoutMinor={pool.payout_balance_minor}
            reserveMinor={pool.reserve_balance_minor}
          />
          <div className="kv" style={{ marginTop: 16 }}>
            <div className="kv__row">
              <span className="kv__key">Total under management</span>
              <span className="kv__value">{pool.display.total}</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">Monthly contribution</span>
              <span className="kv__value">{pool.display.contribution}</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">Running costs collected</span>
              <span className="kv__value">{formatMoney(pool.running_costs_minor)}</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">Payout currency</span>
              <span className="kv__value">
                {pool.currency} → {config.app.paypal.payout_currency} @{" "}
                {config.app.paypal.inr_per_usd}/USD
              </span>
            </div>
          </div>
          {pool.paused && pool.pause_reason ? (
            <div className="callout callout--warn" style={{ marginTop: 14 }}>
              <span className="callout__mark">!</span>
              <div>
                <strong>The pause switch is on.</strong>
                {pool.pause_reason}
              </div>
            </div>
          ) : null}
          <div className="card__foot">
            <Link className="btn btn--secondary btn--sm" to="/fund">
              Fund the pool
            </Link>
            <Link className="link-btn" to="/operator">
              Manage the pause switch
            </Link>
          </div>
        </article>
      </section>

      <section className="section grid grid--stats">
        <StatCard
          label="Members"
          value={formatNumber(stats.members.total)}
          hint={`${formatNumber(stats.members.active)} active · ${formatNumber(
            stats.members.blocked,
          )} blocked by screening`}
          tone="rain"
        />
        <StatCard
          label="Covered policies"
          value={formatNumber(stats.members.policies_active)}
          hint={`${formatNumber(stats.members.verified)} verified members in 6 zones`}
        />
        <StatCard
          label="Payouts settled"
          value={formatNumber(stats.performance.payouts_success)}
          hint={`${stats.performance.total_paid_display} total · p95 ${formatSeconds(
            stats.performance.p95_seconds_trigger_to_payout,
          )}`}
          tone="ok"
        />
        <StatCard
          label="Held for review"
          value={formatNumber(stats.performance.decisions_held)}
          hint="Risk flags never auto-pay. A human sees these."
          tone="warn"
          aside={<Badge tone="warn">human</Badge>}
        />
      </section>

      <section className="section grid grid--main">
        <div className="card card--flush">
          <div className="grid-toolbar">
            <div>
              <h2>Payout ledger</h2>
              <p className="card__sub">
                {formatNumber(ledger.total)} rows · every row carries a reason code.
              </p>
            </div>
            <span className="spacer" />
            <label className="sr-only" htmlFor="ledger-search">
              Search member
            </label>
            <input
              id="ledger-search"
              className="input input--sm grow"
              placeholder="Search name or email"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <label className="sr-only" htmlFor="ledger-status">
              Filter by status
            </label>
            <select
              id="ledger-status"
              className="select input--sm"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">All statuses</option>
              <option value="SUCCESS">Success</option>
              <option value="PENDING">Pending</option>
              <option value="FAILED">Failed</option>
              <option value="HELD">Held</option>
            </select>
            <label className="sr-only" htmlFor="ledger-zone">
              Filter by zone
            </label>
            <select
              id="ledger-zone"
              className="select input--sm"
              value={zone}
              onChange={(event) => setZone(event.target.value)}
            >
              <option value="">All zones</option>
              {config.zones.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div
            className="ag-theme-quartz ledger-grid"
            role="region"
            aria-label="Payout ledger table"
          >
            <AgGridReact<LedgerRow>
              rowData={ledger.rows}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              pagination
              paginationPageSize={20}
              paginationPageSizeSelector={[20, 50, 100]}
              animateRows={false}
              overlayNoRowsTemplate="<span style='padding:16px;color:#5b7076'>No payouts match these filters yet.</span>"
            />
          </div>
        </div>

        <div className="stack">
          <article className="card">
            <div className="card__head">
              <div>
                <h2>Coverage forecast</h2>
                <p className="card__sub">Assumption-based, not a guarantee.</p>
              </div>
              <Badge tone={stats.coverage.events_covered >= 3 ? "ok" : "warn"}>
                {stats.coverage.events_covered >= 3 ? "healthy" : "thin"}
              </Badge>
            </div>
            <div className="row row--between small">
              <span className="muted">Funds cover</span>
              <strong>{stats.coverage.events_covered.toFixed(1)} storm events</strong>
            </div>
            <div className="progress" style={{ marginTop: 6 }} aria-hidden="true">
              <div className="progress__fill" style={{ width: `${coveragePct}%` }} />
            </div>
            <p className="small muted" style={{ marginTop: 6 }}>
              Stress test: one storm hits {percent(stats.forecast.stress_fraction, 1)}% of the
              largest zone ({formatNumber(stats.forecast.assumed_affected_members)} members ×{" "}
              {formatMoney(stats.forecast.expected_payout_per_member_minor)}).
            </p>
            <div className="kv" style={{ marginTop: 12 }}>
              <div className="kv__row">
                <span className="kv__key">Expected cost per event</span>
                <span className="kv__value">{stats.coverage.display.expected_event_cost}</span>
              </div>
              <div className="kv__row">
                <span className="kv__key">Monthly inflow if all pay</span>
                <span className="kv__value">{formatMoney(stats.forecast.monthly_inflow_minor)}</span>
              </div>
            </div>
            <p className="small muted" style={{ marginTop: 11, lineHeight: 1.55 }}>
              {stats.forecast.narrative}
            </p>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Where members are</h2>
                <p className="card__sub">A single-zone storm is the main concentration risk.</p>
              </div>
            </div>
            <div className="bars">
              {stats.members.zones.map((row) => (
                <div className="bar-row" key={row.zone}>
                  <span title={zoneLabel(row.zone, config.zones)}>
                    {zoneLabel(row.zone, config.zones)}
                  </span>
                  <div className="bar-row__track">
                    <div
                      className="bar-row__fill"
                      style={{ width: `${Math.max(3, (row.members / topZone) * 100)}%` }}
                    />
                  </div>
                  <span className="bar-row__value">{formatNumber(row.members)}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Recent triggers</h2>
                <p className="card__sub">Newest first. Simulated and live feeds share this table.</p>
              </div>
              <Link className="link-btn" to="/operator">
                Open console
              </Link>
            </div>
            {events.events.length === 0 ? (
              <p className="small muted">No events yet. The operator can simulate a storm.</p>
            ) : (
              events.events.map((event) => (
                <div className="event-line" key={event.id}>
                  <span className="event-line__rain">{event.value} mm</span>
                  <span className="event-line__zone">
                    {zoneLabel(event.zone, config.zones)}
                    <span className="muted small"> · {event.mode}</span>
                  </span>
                  <span className="event-line__time">{timeAgo(event.created_at)}</span>
                </div>
              ))
            )}
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Guardrails in force</h2>
                <p className="card__sub">Server-side, not UI-side.</p>
              </div>
            </div>
            <div className="stack stack--sm small">
              <div className="row row--between">
                <span className="muted">AI can move money</span>
                <Badge tone="ok">No</Badge>
              </div>
              <div className="row row--between">
                <span className="muted">Per member per day</span>
                <strong>1 payout</strong>
              </div>
              <div className="row row--between">
                <span className="muted">Per member per month</span>
                <strong>{stats.guards.max_payouts_per_month} days</strong>
              </div>
              <div className="row row--between">
                <span className="muted">Idempotency</span>
                <span className="mono small">event + policy</span>
              </div>
              <div className="row row--between">
                <span className="muted">Webhooks</span>
                <strong>signature-checked</strong>
              </div>
              <div className="row row--between">
                <span className="muted">Provider</span>
                <span>{stats.guards.provider_label}</span>
              </div>
            </div>
          </article>
        </div>
      </section>
    </>
  );
}
