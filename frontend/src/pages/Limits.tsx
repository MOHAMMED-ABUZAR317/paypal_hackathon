import { Link } from "react-router-dom";
import { Badge } from "../components/Badge";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, Loading } from "../components/StateBlocks";
import { api } from "../lib/api";
import { formatMoney, formatNumber } from "../lib/format";
import { useApi } from "../lib/hooks";

const REASONS: { code: string; meaning: string }[] = [
  { code: "OK", meaning: "Threshold crossed, waiting period met, under every cap." },
  { code: "THRESHOLD_NOT_MET", meaning: "Measured rainfall is below this policy's threshold." },
  { code: "WAITING_PERIOD_NOT_MET", meaning: "Cover has not started yet (24–168 hour waiting period)." },
  { code: "MEMBER_NOT_VERIFIED", meaning: "Identity is unverified. Denied at trigger time." },
  { code: "MEMBER_BLOCKED", meaning: "Screening blocked the account before or after enrollment." },
  { code: "ZONE_MISMATCH", meaning: "The event is in a different zone from the policy." },
  { code: "POLICY_INACTIVE", meaning: "The policy was deactivated by the member or an operator." },
  { code: "POLICY_WINDOW_CLOSED", meaning: "The policy's cover window has ended." },
  { code: "DAILY_CAP_REACHED", meaning: "One payout per member per calendar day." },
  { code: "MONTHLY_CAP_REACHED", meaning: "Three payout days per month at most." },
  { code: "PARTIAL_MONTHLY_CAP", meaning: "A multi-day event was trimmed to the remaining monthly cap." },
  { code: "POOL_PAUSED", meaning: "The operator's emergency stop is on. Nothing pays." },
  { code: "POOL_INSUFFICIENT_FUNDS", meaning: "The payout box cannot cover the amount. No overdraft." },
  { code: "HIGH_RISK_HOLD", meaning: "Risk score is high enough to require a human review first." },
  { code: "DUPLICATE_EVENT", meaning: "The same event key was replayed. No second payout." },
  { code: "TRIGGER_TYPE_MISMATCH", meaning: "Only rainfall triggers are supported in v1." },
];

const SCHEMA_SAMPLE = `{
  "schema_version": "1.0",
  "trigger_type": "rainfall",
  "data_source": "open-meteo",
  "zone": "hyderabad-central",
  "metric": "precipitation_sum_mm_24h",
  "operator": ">=",
  "threshold": 50,
  "payout_amount_minor": 50000,
  "currency": "INR",
  "max_payouts_per_day": 1,
  "max_payouts_per_month": 3,
  "waiting_period_hours": 48,
  "plain_language": "If 24-hour rainfall reaches 50 mm, you get Rs 500 for that day.",
  "source": "llm",
  "confidence": 0.86
}`;

export function LimitsPage() {
  const configState = useApi(api.config, []);
  const config = configState.data;

  if (configState.loading && !config) {
    return (
      <>
        <PageHeader eyebrow="Safety" title="Loading the rule limits…" />
        <Loading label="Reading hard limits" />
      </>
    );
  }

  if (configState.error && !config) {
    return (
      <>
        <PageHeader eyebrow="Safety" title="Limits are unavailable" />
        <ErrorState message={configState.error} onRetry={() => void configState.reload()} />
      </>
    );
  }

  if (!config) return null;

  const limits = config.limits;

  return (
    <>
      <PageHeader
        eyebrow="Limits, disclosures & data"
        title="The boring parts are the safety feature."
        lead="RainCheck is a sandbox prototype of a community-funded parametric pool. This page states the hard limits, every decision reason, the data source, and the risks we are not hiding."
        actions={
          <>
            <Badge tone="mock" dot>
              mock transport available
            </Badge>
            <Badge tone="info">schema 1.0</Badge>
          </>
        }
      />

      <div className="grid grid--main">
        <div className="stack">
          <article className="card">
            <div className="card__head">
              <div>
                <h2>Hard limits</h2>
                <p className="card__sub">
                  Enforced by <span className="inline-code">enforce_bounds()</span> on the server,
                  after the browser and after the model. The UI cannot raise them.
                </p>
              </div>
            </div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Control</th>
                    <th>Allowed</th>
                    <th>Enforced by</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Rain threshold</td>
                    <td>
                      {limits.min_threshold_mm}–{limits.max_threshold_mm} mm / 24 h
                    </td>
                    <td className="mono small">enforce_bounds</td>
                  </tr>
                  <tr>
                    <td>Payout amount</td>
                    <td>
                      {formatMoney(limits.min_payout_minor)}–
                      {formatMoney(limits.max_payout_minor)}
                    </td>
                    <td className="mono small">enforce_bounds</td>
                  </tr>
                  <tr>
                    <td>Payout frequency</td>
                    <td>1 per member per day</td>
                    <td className="mono small">rules.py</td>
                  </tr>
                  <tr>
                    <td>Monthly cap</td>
                    <td>{limits.max_payouts_per_month} payout days</td>
                    <td className="mono small">rules.py</td>
                  </tr>
                  <tr>
                    <td>Waiting period</td>
                    <td>24–168 hours</td>
                    <td className="mono small">rules.py</td>
                  </tr>
                  <tr>
                    <td>Allowed trigger</td>
                    <td>Rainfall only (v1)</td>
                    <td className="mono small">schema validator</td>
                  </tr>
                  <tr>
                    <td>Pool overdraft</td>
                    <td>Not allowed</td>
                    <td className="mono small">rules.py</td>
                  </tr>
                  <tr>
                    <td>AI authority</td>
                    <td>Propose and explain only</td>
                    <td className="mono small">architecture + test</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>How a payment is authorised</h2>
                <p className="card__sub">
                  Ten ordered guards. The first failure wins and becomes the reason code.
                </p>
              </div>
            </div>
            <ol className="small" style={{ margin: 0, paddingLeft: 20, lineHeight: 1.75 }}>
              <li>Is the pool paused?</li>
              <li>Is the policy active and inside its cover window?</li>
              <li>Has the waiting period passed?</li>
              <li>Is the member verified and not blocked?</li>
              <li>Does the event zone match the policy zone?</li>
              <li>Is the trigger a rainfall trigger?</li>
              <li>Did measured 24-hour rainfall cross the threshold?</li>
              <li>Is the daily cap already reached?</li>
              <li>Is the monthly cap available (and how many days remain)?</li>
              <li>Does the payout box have enough money?</li>
            </ol>
            <div className="callout callout--info" style={{ marginTop: 12 }}>
              <span className="callout__mark">i</span>
              <div>
                <strong>AI is not in this list.</strong>
                An advisory can add a hold flag, but it can never turn a deny into a pay, or
                choose an amount.
              </div>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Decision reason codes</h2>
                <p className="card__sub">The ledger is explainable by construction.</p>
              </div>
              <Badge tone="neutral">{REASONS.length} codes</Badge>
            </div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Reason code</th>
                    <th>What it means</th>
                  </tr>
                </thead>
                <tbody>
                  {REASONS.map((reason) => (
                    <tr key={reason.code}>
                      <td className="mono small nowrap">{reason.code}</td>
                      <td>{reason.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Policy schema v1.0</h2>
                <p className="card__sub">
                  The frozen contract shared by the AI parser, the rule engine, the API and this
                  UI. Amounts are integer paise.
                </p>
              </div>
            </div>
            <pre className="code">{SCHEMA_SAMPLE}</pre>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Data source and assumptions</h2>
                <p className="card__sub">Numbers we use, and numbers we assume.</p>
              </div>
            </div>
            <div className="stack stack--sm small">
              <p>
                <strong>Rainfall:</strong> Open-Meteo daily{" "}
                <span className="inline-code">precipitation_sum</span>, polled once per zone per
                interval. Each zone has one coordinate:
              </p>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th>Latitude</th>
                      <th>Longitude</th>
                    </tr>
                  </thead>
                  <tbody>
                    {config.zones.map((zone) => (
                      <tr key={zone.id}>
                        <td>{zone.name}</td>
                        <td className="num">{zone.latitude.toFixed(4)}</td>
                        <td className="num">{zone.longitude.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                <strong>Coverage stress test:</strong> a single storm is assumed to affect 15% of
                the largest zone. This is a stated planning assumption, not a weather forecast or
                a guarantee. The dashboard shows the resulting number of events covered.
              </p>
              <p>
                <strong>Currency:</strong> the ledger stores INR paise. PayPal Payouts does not
                support INR, so disbursements are converted to{" "}
                <strong>{config.app.paypal.payout_currency}</strong> at{" "}
                <strong>{config.app.paypal.inr_per_usd} INR/USD</strong> and both values are
                stored. A real deployment would use a quoted FX rate and disclose it.
              </p>
              <p>
                <strong>Seed:</strong> 10,000 fictional members across six Hyderabad/Warangal
                zones, a fraud ring, unverified accounts, accounts inside the waiting period, and
                historical storms. All names and payout addresses are fictional.
              </p>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>What this is — and is not</h2>
              </div>
            </div>
            <div className="grid grid--2">
              <div>
                <h3 style={{ color: "var(--ok)" }}>It is</h3>
                <ul className="small" style={{ paddingLeft: 18, lineHeight: 1.7 }}>
                  <li>A working sandbox prototype of parametric rain cover.</li>
                  <li>A community pool with a payout box and a reserve.</li>
                  <li>Deterministic authorisation with a full audit trail.</li>
                  <li>PayPal Orders for funding and Payouts for disbursement.</li>
                </ul>
              </div>
              <div>
                <h3 style={{ color: "var(--danger)" }}>It is not</h3>
                <ul className="small" style={{ paddingLeft: 18, lineHeight: 1.7 }}>
                  <li>Insurance, or a licensed financial product.</li>
                  <li>A guarantee of payout, solvency or return.</li>
                  <li>Live money in mock mode; sandbox money in sandbox mode.</li>
                  <li>A replacement for loss assessment or government relief.</li>
                </ul>
              </div>
            </div>
            <div className="callout callout--warn" style={{ marginTop: 12 }}>
              <span className="callout__mark">!</span>
              <div>
                <strong>Basis risk is disclosed, not hidden.</strong>
                Parametric cover pays on a measured threshold. A worker can lose a day's income
                and still receive nothing if the gauge did not cross the line. The receipt and
                this page say so in plain language.
              </div>
            </div>
          </article>
        </div>

        <aside className="stack">
          <article className="card card--dark">
            <h2>At a glance</h2>
            <div className="hero__facts" style={{ marginTop: 12 }}>
              <div className="hero__fact">
                <strong>{formatNumber(config.zones.length)}</strong>
                <span>weather zones</span>
              </div>
              <div className="hero__fact">
                <strong>{limits.max_payouts_per_month}</strong>
                <span>paid days / month</span>
              </div>
              <div className="hero__fact">
                <strong>{formatMoney(limits.max_payout_minor)}</strong>
                <span>maximum payout</span>
              </div>
              <div className="hero__fact">
                <strong>1</strong>
                <span>payout / member / day</span>
              </div>
            </div>
            <p className="small" style={{ marginTop: 13, color: "#c7dde1" }}>
              The pool can run out. When the payout box cannot cover a decision, the decision is
              denied with <span className="mono">POOL_INSUFFICIENT_FUNDS</span>. The reserve is a
              buffer, not an infinite backstop.
            </p>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Security posture</h2>
                <p className="card__sub">Hackathon-sized, honestly stated.</p>
              </div>
            </div>
            <div className="stack stack--sm small">
              <p>
                <strong>Secrets:</strong> environment variables only; <span className="inline-code">.env</span>{" "}
                is git-ignored and never returned by the API.
              </p>
              <p>
                <strong>Operator routes:</strong> require{" "}
                <span className="inline-code">X-Operator-Key</span>; demo default must be changed
                before any public deployment.
              </p>
              <p>
                <strong>Webhooks:</strong> PayPal signature verification with the configured
                webhook id before any state change.
              </p>
              <p>
                <strong>Idempotency:</strong> event + policy uniqueness, PayPal idempotency keys,
                and a replay-safe demo button.
              </p>
              <p>
                <strong>Audit:</strong> every operator action, decision and provider call writes
                an audit row.
              </p>
              <p>
                <strong>Known gaps:</strong> SQLite for the demo, no KYC provider, no formal
                actuarial model, no multi-currency settlement, no production rate limiting at the
                edge.
              </p>
            </div>
          </article>

          <article className="card">
            <div className="card__head">
              <div>
                <h2>Read next</h2>
              </div>
            </div>
            <div className="stack stack--sm">
              <Link className="btn btn--secondary btn--sm btn--block" to="/operator">
                Run a storm in the console
              </Link>
              <Link className="btn btn--secondary btn--sm btn--block" to="/enroll">
                Enroll a worker
              </Link>
              <Link className="btn btn--secondary btn--sm btn--block" to="/receipts">
                See the numeric guard in action
              </Link>
            </div>
            <p className="small muted" style={{ marginTop: 11 }}>
              Full technical detail lives in <span className="inline-code">docs/</span>: architecture,
              API, PayPal, policy schema and AI usage.
            </p>
          </article>
        </aside>
      </div>
    </>
  );
}
