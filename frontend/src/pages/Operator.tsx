import { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { Badge, ProviderPill, StatusPill } from "../components/Badge";
import { ConfirmButton } from "../components/ConfirmButton";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { EmptyState, ErrorState, Loading } from "../components/StateBlocks";
import { useToast } from "../components/Toast";
import { api, defaultOperatorKey, getOperatorKey, setOperatorKey } from "../lib/api";
import {
  formatDate,
  formatMoney,
  formatNumber,
  safeMessage,
  timeAgo,
  zoneLabel,
} from "../lib/format";
import { useApi } from "../lib/hooks";
import type {
  AiReview,
  AiStatus,
  AuditEntry,
  DecisionRow,
  EventRow,
  FraudAttemptResponse,
  PollResult,
  SimulateResponse,
} from "../lib/types";

export function OperatorPage() {
  const toast = useToast();
  const [tick, setTick] = useState(0);
  const [keyDraft, setKeyDraft] = useState(getOperatorKey());
  const [zone, setZone] = useState("hyderabad-central");
  const [rainfall, setRainfall] = useState(62);
  const [days, setDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<SimulateResponse | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [pauseReason, setPauseReason] = useState("Demo: operator pause");
  const [fraud, setFraud] = useState<FraudAttemptResponse | null>(null);
  const [poll, setPoll] = useState<PollResult | null>(null);
  const [aiReview, setAiReview] = useState<AiReview | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const statsState = useApi(api.poolStats, [tick]);
  const eventsState = useApi(() => api.events(12), [tick]);
  const auditState = useApi(() => api.audit(30), [tick]);
  const aiState = useApi<AiStatus>(api.aiStatus, [tick]);
  const configState = useApi(api.config, []);

  const summaryState = useApi(
    () => (selectedEventId ? api.eventSummary(selectedEventId) : Promise.resolve(null)),
    [selectedEventId, tick],
  );

  const events: EventRow[] = eventsState.data?.events ?? [];
  const stats = statsState.data;
  const config = configState.data;

  useEffect(() => {
    if (!selectedEventId && events.length > 0) {
      setSelectedEventId(events[0].id);
    }
  }, [events, selectedEventId]);

  const suggestedKey = useMemo(() => {
    const day = new Date().toISOString().slice(0, 10);
    return `demo:${zone}:${rainfall}:${days}:${day}`;
  }, [zone, rainfall, days]);

  function refresh() {
    setTick((value) => value + 1);
  }

  async function simulate(eventKey?: string) {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.simulate({
        zone,
        rainfall_mm: rainfall,
        days,
        event_key: eventKey ?? suggestedKey,
      });
      setLastResult(response);
      setSelectedEventId(response.event.id);
      setAiReview(null);
      refresh();
      toast.push(
        response.duplicate
          ? "Replay detected. No second payout was created."
          : `Event processed: ${response.counts.APPROVE} approved, ${response.counts.HOLD_FOR_REVIEW} held.`,
        response.duplicate ? "info" : "ok",
      );
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function replay() {
    if (!lastResult) return;
    setBusy(true);
    setActionError(null);
    try {
      const keyResponse = await api.eventKey(lastResult.event.id);
      await simulate(keyResponse.event_key);
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function togglePause(paused: boolean) {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.pause(paused, paused ? pauseReason : undefined);
      toast.push(response.message, paused ? "info" : "ok");
      refresh();
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function runFraudDemo() {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.fraudAttempt();
      setFraud(response);
      refresh();
      toast.push(
        response.blocked
          ? "Screening blocked the sybil account before activation."
          : "Screening allowed it — check the flags.",
        response.blocked ? "ok" : "error",
      );
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    setBusy(true);
    setActionError(null);
    try {
      await api.resetDemo();
      setLastResult(null);
      setFraud(null);
      setPoll(null);
      setAiReview(null);
      setSelectedEventId(null);
      refresh();
      toast.push(
        "Demo reset: events cleared, balances restored, seeded members kept.",
        "ok",
      );
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function pollLive() {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.pollLive();
      setPoll(response);
      refresh();
      toast.push(
        response.events_fired
          ? `${response.events_fired} live event(s) fired.`
          : "Poll finished. No zone crossed its policy thresholds.",
        "info",
      );
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function retryFailed() {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.retryPayouts();
      toast.push(
        response.retried
          ? `${response.retried} failed payout(s) retried.`
          : response.message ?? "No failed payouts.",
        "info",
      );
      refresh();
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function reconcile() {
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.reconcile();
      toast.push(`${response.batches_checked} pending batch(es) reconciled.`, "info");
      refresh();
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function reviewEvent() {
    if (!selectedEventId) return;
    setBusy(true);
    setActionError(null);
    try {
      const response = await api.aiEventReview(selectedEventId);
      setAiReview(response);
      toast.push(
        response.source === "llm" ? "AI review received." : "Deterministic review used.",
        "info",
      );
    } catch (error) {
      setActionError(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function saveKey() {
    setOperatorKey(keyDraft);
    toast.push("Operator key saved for this browser session.", "ok");
    refresh();
  }

  const decisionColumns = useMemo<ColDef<DecisionRow>[]>(
    () => [
      { headerName: "Member", field: "member_name", minWidth: 160, flex: 1.2 },
      {
        headerName: "Outcome",
        field: "outcome",
        width: 150,
        cellRenderer: (params: { value?: string }) => <StatusPill status={params.value} />,
      },
      {
        headerName: "Reason",
        field: "reason_code",
        width: 190,
        cellRenderer: (params: { value?: string }) => (
          <span className="mono small">{params.value}</span>
        ),
      },
      {
        headerName: "Amount",
        field: "amount_minor",
        width: 105,
        valueFormatter: (params) => formatMoney(params.value ?? 0),
      },
      { headerName: "Risk", field: "risk_score", width: 85 },
      {
        headerName: "Payout",
        field: "payout_status",
        width: 115,
        cellRenderer: (params: { value?: string }) => <StatusPill status={params.value ?? "—"} />,
      },
    ],
    [],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({ sortable: true, resizable: true, suppressHeaderMenuButton: true }),
    [],
  );

  if (statsState.loading && !stats) {
    return (
      <>
        <PageHeader eyebrow="Operator" title="Loading the console…" />
        <Loading label="Reading pool, events and audit trail" />
      </>
    );
  }

  if (statsState.error && !stats) {
    return (
      <>
        <PageHeader eyebrow="Operator" title="Console unavailable" />
        <ErrorState message={statsState.error} onRetry={() => void statsState.reload()} />
      </>
    );
  }

  if (!stats) return null;

  const paused = stats.pool.paused;
  const summary = summaryState.data ?? lastResult;

  return (
    <>
      <PageHeader
        eyebrow="Operator console"
        title="Run the storm. Watch the guards hold."
        lead="Every demo action goes through the same pipeline as a live trigger: normalise, screen, decide, pay, audit. The operator key is required for anything that can move money."
        actions={
          <>
            <Badge tone="neutral" dot>
              key: {getOperatorKey()}
            </Badge>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={refresh}
              aria-busy={statsState.loading}
            >
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </>
        }
      />

      {actionError ? (
        <div className="callout callout--danger" style={{ marginBottom: 16 }} role="alert">
          <span className="callout__mark">!</span>
          <div>
            <strong>That action failed.</strong>
            {actionError}
            {actionError.toLowerCase().includes("operator") ? (
              <span> Check the operator key in the access card below.</span>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="grid grid--stats">
        <StatCard
          label="Payouts"
          value={paused ? "Paused" : "Running"}
          hint={paused ? stats.pool.pause_reason ?? "Pause switch is on." : "All guards active."}
          tone={paused ? "warn" : "ok"}
          aside={<Badge tone={paused ? "warn" : "ok"} dot>{paused ? "STOP" : "LIVE"}</Badge>}
        />
        <StatCard
          label="Covered policies"
          value={formatNumber(stats.members.policies_active)}
          hint={`${formatNumber(stats.members.total)} members seeded`}
          tone="rain"
        />
        <StatCard
          label="Payouts settled"
          value={formatNumber(stats.performance.payouts_success)}
          hint={stats.performance.total_paid_display}
        />
        <StatCard
          label="Failed / held"
          value={`${stats.performance.payouts_failed} / ${stats.performance.decisions_held}`}
          hint="Retry and review tools are below."
          tone="warn"
        />
      </div>

      <section className="section grid grid--2">
        <article className="card">
          <div className="card__head">
            <div>
              <h2>Simulate a rainfall trigger</h2>
              <p className="card__sub">
                Same event shape as the live scheduler. Uses the seeded policies for the zone.
              </p>
            </div>
            <Badge tone="neutral">demo tool</Badge>
          </div>

          <div className="field-row field-row--4">
            <div className="field">
              <label htmlFor="storm-zone">Zone</label>
              <select
                id="storm-zone"
                className="select"
                value={zone}
                onChange={(event) => setZone(event.target.value)}
              >
                {(config?.zones ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="storm-rain">Rainfall (mm/24h)</label>
              <input
                id="storm-rain"
                className="input"
                type="number"
                min={0}
                max={1000}
                value={rainfall}
                onChange={(event) => setRainfall(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="storm-days">Days</label>
              <input
                id="storm-days"
                className="input"
                type="number"
                min={1}
                max={3}
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="storm-key">Event key</label>
              <input
                id="storm-key"
                className="input mono"
                value={suggestedKey}
                readOnly
                title="Deterministic key for this zone, rainfall, days and date"
              />
            </div>
          </div>
          <p className="field__hint" style={{ marginTop: 6 }}>
            Replaying the same key is safe: the pipeline returns the original summary and pays
            nobody twice.
          </p>

          <div className="row" style={{ marginTop: 14 }}>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void simulate()}
              disabled={busy}
              aria-busy={busy}
            >
              {busy ? "Processing…" : "Simulate storm"}
            </button>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void replay()}
              disabled={busy || !lastResult}
            >
              Replay same key
            </button>
            <span className="spacer" />
            <Badge tone="mock">no real money</Badge>
          </div>

          {summary ? (
            <div className="callout callout--info" style={{ marginTop: 14 }} role="status">
              <span className="callout__mark">{summary.duplicate ? "↺" : "✓"}</span>
              <div style={{ width: "100%" }}>
                <strong>
                  {summary.duplicate
                    ? "Duplicate key ignored — original event returned."
                    : `${summary.event.value} mm in ${zoneLabel(summary.event.zone, config?.zones)} processed.`}
                </strong>
                <div className="row" style={{ marginTop: 8 }}>
                  <Badge tone="ok">APPROVE {summary.counts.APPROVE}</Badge>
                  <Badge tone="warn">HOLD {summary.counts.HOLD_FOR_REVIEW}</Badge>
                  <Badge tone="neutral">DENY {summary.counts.DENY}</Badge>
                  <Badge tone="info">
                    {formatMoney(summary.total_paid_minor)} paid
                  </Badge>
                  <Badge tone="neutral">{summary.payout_rows} payout rows</Badge>
                </div>
                <p className="small muted" style={{ marginTop: 8 }}>
                  {summary.batches.length} PayPal batch(es) ·{" "}
                  {summary.reasons
                    .slice(0, 4)
                    .map((reason) => `${reason.code} (${reason.count})`)
                    .join(" · ")}
                </p>
              </div>
            </div>
          ) : null}
        </article>

        <article className="card">
          <div className="card__head">
            <div>
              <h2>Emergency stop</h2>
              <p className="card__sub">
                When paused, every new decision is denied with{" "}
                <span className="inline-code">POOL_PAUSED</span>. No partial payouts.
              </p>
            </div>
            <Badge tone={paused ? "warn" : "ok"} dot>
              {paused ? "Paused" : "Payouts live"}
            </Badge>
          </div>

          <div className="field">
            <label htmlFor="pause-reason">Reason (written to the audit log)</label>
            <input
              id="pause-reason"
              className="input"
              value={pauseReason}
              onChange={(event) => setPauseReason(event.target.value)}
              disabled={paused}
            />
          </div>

          <div className="row" style={{ marginTop: 12 }}>
            {paused ? (
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void togglePause(false)}
                disabled={busy}
              >
                Resume payouts
              </button>
            ) : (
              <button
                type="button"
                className="btn btn--danger"
                onClick={() => void togglePause(true)}
                disabled={busy}
                aria-busy={busy}
              >
                Pause all payouts
              </button>
            )}
            <span className="small muted">
              Reversible · audit-logged · checked by the rule engine, not the UI.
            </span>
          </div>

          {paused ? (
            <div className="callout callout--warn" style={{ marginTop: 13 }}>
              <span className="callout__mark">!</span>
              <div>
                <strong>All payouts are paused.</strong>
                {stats.pool.pause_reason ?? "No reason recorded."}
              </div>
            </div>
          ) : null}

          <div className="hr" style={{ margin: "16px 0" }} />

          <div className="row row--between">
            <div>
              <h3>Recovery tools</h3>
              <p className="card__sub">For failed or stuck provider batches.</p>
            </div>
            <div className="row">
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => void retryFailed()}
                disabled={busy}
              >
                Retry failed
              </button>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => void reconcile()}
                disabled={busy}
              >
                Reconcile
              </button>
            </div>
          </div>
        </article>
      </section>

      <section className="section grid grid--2">
        <article className="card">
          <div className="card__head">
            <div>
              <h2>Fraud attempt</h2>
              <p className="card__sub">
                Tries to enroll a new account sharing the seeded ring's PayPal address and device.
              </p>
            </div>
            <Badge tone="warn">screening demo</Badge>
          </div>
          <p className="small muted">
            The block happens before activation: no policy, no payout, and the attempt is written
            to the audit log.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => void runFraudDemo()}
              disabled={busy}
            >
              Attempt a sybil enrollment
            </button>
          </div>

          {fraud ? (
            <div
              className={`callout callout--${fraud.blocked ? "ok" : "danger"}`}
              style={{ marginTop: 13 }}
              role="status"
            >
              <span className="callout__mark">{fraud.blocked ? "✓" : "!"}</span>
              <div>
                <strong>
                  {fraud.blocked ? "Blocked before activation." : "Not blocked — investigate."}
                </strong>
                {fraud.receipt}
                <div className="pill-row" style={{ marginTop: 7 }}>
                  <Badge tone="neutral">score {fraud.screening.score}/100</Badge>
                  {fraud.screening.flags.map((flag) => (
                    <Badge key={flag.code} tone="warn">
                      {flag.code}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </article>

        <article className="card">
          <div className="card__head">
            <div>
              <h2>Demo controls</h2>
              <p className="card__sub">Rehearsal tools. Every action is audit-logged.</p>
            </div>
          </div>
          <div className="stack stack--sm">
            <div className="row row--between">
              <div>
                <h3>Poll Open-Meteo now</h3>
                <p className="card__sub">Fail-closed: a feed error creates no event.</p>
              </div>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => void pollLive()}
                disabled={busy}
              >
                Poll live feed
              </button>
            </div>
            <div className="hr" />
            <div className="row row--between">
              <div>
                <h3>Reset the demo</h3>
                <p className="card__sub">
                  Clears events, decisions and payouts; restores seed balances; keeps
                  the 10,000 seeded members. Rehearsal enrollments are removed.
                </p>
              </div>
              <ConfirmButton
                label="Reset demo"
                confirmLabel="Confirm reset"
                onConfirm={() => void resetDemo()}
                busy={busy}
              />
            </div>
          </div>

          {poll ? (
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>Status</th>
                    <th>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {poll.results.map((row) => (
                    <tr key={row.zone}>
                      <td>{zoneLabel(row.zone, config?.zones)}</td>
                      <td>
                        <StatusPill status={row.status} />
                      </td>
                      <td>{row.value != null ? `${row.value} mm` : row.error ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      </section>

      <section className="section grid grid--main">
        <div className="card card--flush">
          <div className="grid-toolbar">
            <div>
              <h2>Decisions for the selected event</h2>
              <p className="card__sub">
                A deterministic outcome and one reason code per member.
              </p>
            </div>
            <span className="spacer" />
            <label className="sr-only" htmlFor="event-select">
              Choose event
            </label>
            <select
              id="event-select"
              className="select input--sm"
              value={selectedEventId ?? ""}
              onChange={(event) => {
                setSelectedEventId(event.target.value || null);
                setAiReview(null);
              }}
            >
              <option value="">Latest event</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  {zoneLabel(event.zone, config?.zones)} · {event.value} mm ·{" "}
                  {formatDate(event.created_at)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => void reviewEvent()}
              disabled={!selectedEventId || busy}
            >
              Review with AI
            </button>
          </div>

          {summary ? (
            <div
              className="ag-theme-quartz ledger-grid"
              role="region"
              aria-label="Event decisions table"
            >
              <AgGridReact<DecisionRow>
                rowData={summary.decisions_sample}
                columnDefs={decisionColumns}
                defaultColDef={defaultColDef}
                pagination
                paginationPageSize={10}
                paginationPageSizeSelector={[10, 20, 50, 100]}
                animateRows={false}
                overlayNoRowsTemplate="<span style='padding:16px;color:#5b7076'>No decisions for this event.</span>"
              />
            </div>
          ) : (
            <EmptyState
              title="No event selected"
              hint="Simulate a storm above, then the decision sample appears here."
            />
          )}

          {aiReview ? (
            <div className="callout callout--info" style={{ margin: 14 }} role="status">
              <span className="callout__mark">i</span>
              <div>
                <strong>
                  {aiReview.source === "llm" ? "AI advisory" : "Deterministic advisory"} ·{" "}
                  {aiReview.ai.risk_level ?? "review"}
                </strong>
                {aiReview.ai.summary}
                {aiReview.ai.recommendation ? (
                  <p className="small" style={{ marginTop: 4 }}>
                    Recommendation: <strong>{aiReview.ai.recommendation}</strong>. The AI cannot
                    change a decision.
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <div className="stack">
          <article className="card">
            <div className="card__head">
              <div>
                <h2>AI layer</h2>
                <p className="card__sub">Source: {aiState.data?.mode ?? "…"}</p>
              </div>
              <Badge tone={aiState.data?.enabled ? "ai" : "neutral"} dot>
                {aiState.data?.enabled ? "model on" : "fallback"}
              </Badge>
            </div>
            <p className="small muted">{aiState.data?.note}</p>
            <div className="kv" style={{ marginTop: 11 }}>
              <div className="kv__row">
                <span className="kv__key">Model</span>
                <span className="kv__value mono small">{aiState.data?.model ?? "—"}</span>
              </div>
              <div className="kv__row">
                <span className="kv__key">Can move money</span>
                <span className="kv__value">{aiState.data?.can_move_money ? "Yes" : "No"}</span>
              </div>
              <div className="kv__row">
                <span className="kv__key">Jobs</span>
                <span className="kv__value small">{aiState.data?.jobs.length ?? 0} bounded jobs</span>
              </div>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Operator access</h2>
                <p className="card__sub">
                  Stored in sessionStorage. Default for local dev:{" "}
                  <span className="inline-code">{defaultOperatorKey()}</span>
                </p>
              </div>
            </div>
            <div className="field">
              <label htmlFor="operator-key">X-Operator-Key</label>
              <input
                id="operator-key"
                className="input mono"
                value={keyDraft}
                onChange={(event) => setKeyDraft(event.target.value)}
                autoComplete="off"
              />
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button type="button" className="btn btn--secondary btn--sm" onClick={saveKey}>
                Save key
              </button>
              <span className="small muted">Never sent to the AI or written to logs.</span>
            </div>
          </article>

          <article className="card card--flush">
            <div className="card__head" style={{ padding: "18px 18px 0" }}>
              <div>
                <h2>Audit trail</h2>
                <p className="card__sub">Actors, actions and detail, newest first.</p>
              </div>
              <Badge tone="neutral">{auditState.data?.entries.length ?? 0}</Badge>
            </div>
            <div style={{ maxHeight: 400, overflowY: "auto" }}>
              {(auditState.data?.entries ?? []).map((entry: AuditEntry) => (
                <div className="event-line" key={`${entry.id}`} style={{ padding: "9px 18px" }}>
                  <div style={{ minWidth: 0 }}>
                    <span className="mono small">{entry.action}</span>
                    <p className="small muted">
                      {entry.actor} · {entry.entity_type}
                    </p>
                  </div>
                  <span className="event-line__time">{timeAgo(entry.ts)}</span>
                </div>
              ))}
              {(auditState.data?.entries ?? []).length === 0 ? (
                <p className="small muted" style={{ padding: 18 }}>
                  No audit entries yet.
                </p>
              ) : null}
            </div>
          </article>
        </div>
      </section>

      <section className="section">
        <article className="card card--flush">
          <div className="card__head" style={{ padding: "18px 18px 0" }}>
            <div>
              <h2>Recent events</h2>
              <p className="card__sub">
                Simulated and live-polled. Click a row's selector above to inspect its decisions.
              </p>
            </div>
            <ProviderPill
              provider={stats.guards.provider}
              mock={stats.guards.mock}
            />
          </div>
          <div className="table-wrap" style={{ border: 0, borderRadius: 0, marginTop: 12 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Zone</th>
                  <th>Rain</th>
                  <th>Days</th>
                  <th>Mode</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>{formatDate(event.created_at)}</td>
                    <td>{zoneLabel(event.zone, config?.zones)}</td>
                    <td>{event.value} mm</td>
                    <td>{event.days}</td>
                    <td>
                      <Badge tone={event.mode === "live" ? "info" : "neutral"}>{event.mode}</Badge>
                    </td>
                    <td>
                      <StatusPill status={event.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </>
  );
}
